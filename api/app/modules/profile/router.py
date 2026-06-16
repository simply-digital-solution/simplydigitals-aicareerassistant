import io
import json
import pdfplumber
import docx

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.database import get_db
from app.modules.auth.router import get_current_user
from app.shared.models import Profile
from app.shared.resume_analyser import analyse_resume
from app.shared.skill_extractor import extract_skills
from app.shared.seniority_extractor import extract_seniority
from app.shared.industry_extractor import extract_industries

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


def _dedupe_json_array(value: str | None) -> str | None:
    """Deduplicate a JSON array string, case-insensitively, preserving first occurrence."""
    if not value:
        return value
    try:
        items = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        key = str(item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return json.dumps(deduped)


class ProfileUpdate(BaseModel):
    resume_text: str | None = None
    resume_html: str | None = None
    linkedin_url: str | None = None
    full_name: str | None = None
    target_locations: str | None = None      # JSON array string
    skills: str | None = None                # JSON array string
    seniority_level: str | None = None       # junior|mid|senior|lead|principal|director|vp|executive
    target_industries: str | None = None     # JSON array string
    target_titles: str | None = None         # JSON array string of target job titles
    remote_preference: str | None = None     # remote | hybrid | onsite | any
    employment_type: str | None = None       # full_time | contract | any
    salary_floor: int | None = None
    salary_currency: str | None = None
    excluded_companies: str | None = None    # JSON array string
    years_experience: int | None = None


class ProfileResponse(BaseModel):
    resume_text: str | None
    resume_html: str | None
    linkedin_url: str | None
    full_name: str | None
    target_locations: str | None
    years_experience: int | None
    skills: str | None
    remote_preference: str | None
    employment_type: str | None
    salary_floor: int | None
    salary_currency: str | None
    excluded_companies: str | None
    role_fit_json: str | None
    seniority_level: str | None
    target_industries: str | None
    target_titles: str | None

    model_config = {"from_attributes": True}


async def _get_or_create(db: AsyncSession, user_id: int) -> Profile:
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        profile = Profile(user_id=user_id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


class ParsedResumeResponse(BaseModel):
    text: str
    html: str


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pdf_to_html(content: bytes) -> tuple[str, str]:
    """Extract text + basic HTML from a PDF using pdfplumber."""
    text_parts: list[str] = []
    html_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if not page_text:
                continue
            text_parts.append(page_text)
            for line in page_text.splitlines():
                stripped = line.strip()
                if not stripped:
                    html_parts.append("<br>")
                    continue
                # Heuristic: short ALL-CAPS lines (≤60 chars) are section headings
                if stripped.isupper() and len(stripped) <= 60:
                    html_parts.append(f'<h2 class="resume-heading">{_escape(stripped)}</h2>')
                # Heuristic: lines starting with ● or • are bullets
                elif stripped.startswith(("●", "•", "-", "–")):
                    bullet = _escape(stripped.lstrip("●•–- ").strip())
                    html_parts.append(f'<li>{bullet}</li>')
                else:
                    html_parts.append(f'<p>{_escape(stripped)}</p>')
    return "\n\n".join(text_parts), "\n".join(html_parts)


def _docx_to_html(content: bytes) -> tuple[str, str]:
    """Extract text + styled HTML from a DOCX preserving bold/italic/bullets/headings."""
    doc = docx.Document(io.BytesIO(content))
    text_lines: list[str] = []
    html_parts: list[str] = []

    for para in doc.paragraphs:
        raw = para.text.strip()
        if not raw:
            html_parts.append("<br>")
            continue

        text_lines.append(raw)
        style_name = (getattr(para.style, "name", None) or "").lower()

        # Build inline HTML for runs (preserving bold/italic per run)
        inner = ""
        for run in para.runs:
            chunk = _escape(run.text)
            if not chunk:
                continue
            if run.bold and run.italic:
                chunk = f"<strong><em>{chunk}</em></strong>"
            elif run.bold:
                chunk = f"<strong>{chunk}</strong>"
            elif run.italic:
                chunk = f"<em>{chunk}</em>"
            inner += chunk
        if not inner:
            inner = _escape(raw)

        # Map Word styles to HTML elements
        if "heading 1" in style_name or "title" in style_name:
            html_parts.append(f'<h1 class="resume-name">{inner}</h1>')
        elif "heading 2" in style_name or "heading 3" in style_name:
            html_parts.append(f'<h2 class="resume-heading">{inner}</h2>')
        elif style_name and "list" in style_name:
            html_parts.append(f'<li>{inner}</li>')
        # Heuristic fallback: short ALL-CAPS = section heading
        elif raw.isupper() and len(raw) <= 60:
            html_parts.append(f'<h2 class="resume-heading">{inner}</h2>')
        else:
            html_parts.append(f'<p>{inner}</p>')

    return "\n".join(text_lines), "\n".join(html_parts)


@router.post("/parse-resume", response_model=ParsedResumeResponse)
async def parse_resume_file(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".pdf"):
        try:
            text, html = _pdf_to_html(content)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not parse PDF: {e}")

    elif filename.endswith(".docx"):
        try:
            text, html = _docx_to_html(content)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not parse DOCX: {e}")

    elif filename.endswith((".txt", ".md")):
        text = content.decode("utf-8", errors="replace")
        html = "".join(f"<p>{_escape(l)}</p>" for l in text.splitlines() if l.strip())

    else:
        raise HTTPException(status_code=415, detail="Unsupported file type. Upload PDF, DOCX, TXT, or MD.")

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the file.")

    # Persist both text and HTML to the profile immediately on upload
    profile = await _get_or_create(db, current_user.id)
    profile.resume_html = html
    await db.commit()

    return ParsedResumeResponse(text=text, html=html)


@router.get("", response_model=ProfileResponse)
async def get_profile(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create(db, current_user.id)
    return profile


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create(db, current_user.id)
    updates = body.model_dump(exclude_none=True)

    # Deduplicate JSON array fields before writing
    for array_field in ('skills', 'target_industries', 'target_titles', 'target_locations', 'excluded_companies'):
        if array_field in updates:
            updates[array_field] = _dedupe_json_array(updates[array_field])

    for field, value in updates.items():
        setattr(profile, field, value)

    if 'resume_text' in updates and updates['resume_text']:
        analysis = analyse_resume(updates['resume_text'])
        if analysis["years_experience"] is not None:
            profile.years_experience = analysis["years_experience"]
        profile.seniority_level = analysis["seniority_level"]
        profile.target_industries = _dedupe_json_array(json.dumps(analysis["industries"]))
        # target_titles intentionally not set here — use POST /extract-titles (LLM-based)
        existing_skills = json.loads(profile.skills) if profile.skills else []
        if not existing_skills and analysis["skills"]:
            profile.skills = _dedupe_json_array(json.dumps(analysis["skills"]))

    await db.commit()
    await db.refresh(profile)
    return profile


class SeniorityResponse(BaseModel):
    seniority_level: str
    method: str
    titles_found: list[str]
    confidence: float


@router.post("/extract-seniority", response_model=SeniorityResponse)
async def extract_seniority_from_resume(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-run seniority extraction on the saved resume and persist the result.
    Returns the detected tier plus which titles were found and the method used.
    """
    profile = await _get_or_create(db, current_user.id)
    if not profile.resume_text or not profile.resume_text.strip():
        raise HTTPException(status_code=422, detail="No resume found. Upload your resume first.")

    result = extract_seniority(profile.resume_text, profile.years_experience)
    profile.seniority_level = result["seniority_level"]
    await db.commit()

    return SeniorityResponse(**result)


class IndustryResult(BaseModel):
    industry: str
    confidence: float
    method: str


class ExtractIndustriesResponse(BaseModel):
    industries: list[IndustryResult]


@router.post("/extract-industries", response_model=ExtractIndustriesResponse)
async def extract_industries_from_resume(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detect industries from saved resume text and persist as target_industries."""
    profile = await _get_or_create(db, current_user.id)
    if not profile.resume_text or not profile.resume_text.strip():
        raise HTTPException(status_code=422, detail="No resume found. Upload your resume first.")

    results = extract_industries(profile.resume_text)
    profile.target_industries = json.dumps([r["industry"] for r in results])
    await db.commit()

    return ExtractIndustriesResponse(industries=[IndustryResult(**r) for r in results])


class ExtractTitlesResponse(BaseModel):
    titles: list[str]
    new_titles: list[str]
    existing_titles: list[str]


@router.post("/extract-titles", response_model=ExtractTitlesResponse)
async def extract_titles_from_resume(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Infer target job titles from saved resume text and persist as target_titles."""
    from app.shared.title_extractor import extract_target_titles
    from app.shared.api_client import get_claude_client
    profile = await _get_or_create(db, current_user.id)
    if not profile.resume_text or not profile.resume_text.strip():
        raise HTTPException(status_code=422, detail="No resume found. Upload your resume first.")

    client = get_claude_client()
    titles = await extract_target_titles(profile.resume_text, api_client=client)
    existing = json.loads(profile.target_titles) if profile.target_titles else []
    existing_lower = {t.lower() for t in existing}
    new_titles = [t for t in titles if t.lower() not in existing_lower]
    merged = _dedupe_json_array(json.dumps(existing + new_titles))
    profile.target_titles = merged
    await db.commit()

    return ExtractTitlesResponse(
        titles=titles,
        new_titles=new_titles,
        existing_titles=existing,
    )


class ExtractedSkill(BaseModel):
    skill: str
    category: str


class ExtractSkillsResponse(BaseModel):
    extracted: list[ExtractedSkill]
    new_skills: list[str]
    existing_skills: list[str]


@router.post("/extract-skills", response_model=ExtractSkillsResponse)
async def extract_skills_from_resume(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Scan saved resume_text against the skills taxonomy and return extracted skills,
    split into new (not yet saved) vs already in profile.
    Does not modify the profile — the frontend confirms before saving.
    """
    profile = await _get_or_create(db, current_user.id)
    if not profile.resume_text or not profile.resume_text.strip():
        raise HTTPException(status_code=422, detail="No resume found. Upload your resume first.")

    extracted = extract_skills(profile.resume_text)
    existing = json.loads(profile.skills) if profile.skills else []
    existing_lower = {s.lower() for s in existing}

    new_skills = [e["skill"] for e in extracted if e["skill"].lower() not in existing_lower]

    return ExtractSkillsResponse(
        extracted=[ExtractedSkill(**e) for e in extracted],
        new_skills=new_skills,
        existing_skills=existing,
    )


class AddSkillsRequest(BaseModel):
    skills: list[str]


@router.post("/add-skills", response_model=ProfileResponse)
async def add_skills_to_profile(
    body: AddSkillsRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Merge confirmed skills into profile.skills (deduped)."""
    profile = await _get_or_create(db, current_user.id)
    existing = json.loads(profile.skills) if profile.skills else []
    existing_lower = {s.lower() for s in existing}
    merged = existing + [s for s in body.skills if s.strip().lower() not in existing_lower]
    profile.skills = _dedupe_json_array(json.dumps(merged))
    await db.commit()
    await db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Skill gap endpoints
# ---------------------------------------------------------------------------

class SkillGapItem(BaseModel):
    title: str
    required_skills: list[str]
    have: list[str]
    missing: list[str]
    coverage: float
    last_updated: str | None


class SkillGapResponse(BaseModel):
    gaps: list[SkillGapItem]


@router.get("/skill-gaps", response_model=SkillGapResponse)
async def get_skill_gaps(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return gap analysis only for titles that are in the user's current target_titles."""
    from app.shared.skill_gap import get_all_title_skills, compute_gap
    profile = await _get_or_create(db, current_user.id)
    profile_skills = json.loads(profile.skills) if profile.skills else []
    target_titles_lower = {
        t.strip().lower()
        for t in (json.loads(profile.target_titles) if profile.target_titles else [])
    }
    rows = await get_all_title_skills(db, current_user.id)
    gaps = []
    for row in rows:
        # Skip titles no longer in the user's target list
        if target_titles_lower and row["title"].strip().lower() not in target_titles_lower:
            continue
        gap = compute_gap(row["required_skills"], profile_skills)
        gaps.append(SkillGapItem(
            title=row["title"],
            required_skills=row["required_skills"],
            have=gap["have"],
            missing=gap["missing"],
            coverage=gap["coverage"],
            last_updated=str(row["last_updated"]) if row["last_updated"] else None,
        ))
    # Sort: lowest coverage first so gaps stand out
    gaps.sort(key=lambda g: g.coverage)
    return SkillGapResponse(gaps=gaps)


class RefreshGapRequest(BaseModel):
    title: str


@router.post("/skill-gaps/refresh", response_model=SkillGapItem)
async def refresh_skill_gap(
    body: RefreshGapRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-run LLM distillation for a single title using its stored source keywords."""
    from app.shared.skill_gap import get_all_title_skills, distill_required_skills, save_title_skills, compute_gap
    from app.shared.api_client import get_claude_client

    profile = await _get_or_create(db, current_user.id)
    profile_skills = json.loads(profile.skills) if profile.skills else []

    rows = await get_all_title_skills(db, current_user.id)
    row = next((r for r in rows if r["title"].lower() == body.title.lower()), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"No data for title '{body.title}'. Run a research search first.")

    client = get_claude_client()
    skills = await distill_required_skills(body.title, row["source_keywords"], client)
    if not skills:
        raise HTTPException(status_code=422, detail="LLM could not distill skills. Try again.")

    await save_title_skills(db, current_user.id, body.title, skills, row["source_keywords"])
    gap = compute_gap(skills, profile_skills)

    return SkillGapItem(
        title=body.title,
        required_skills=skills,
        have=gap["have"],
        missing=gap["missing"],
        coverage=gap["coverage"],
        last_updated=None,
    )


class SeedGapRequest(BaseModel):
    title: str


class SeedAllGapResponse(BaseModel):
    seeded: list[str]
    skipped: list[str]


@router.post("/skill-gaps/seed", response_model=SkillGapItem)
async def seed_skill_gap(
    body: SeedGapRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate required skills for a title using LLM knowledge (no JD keywords needed)."""
    from app.shared.skill_gap import seed_required_skills, save_title_skills, compute_gap
    from app.shared.api_client import get_claude_client

    profile = await _get_or_create(db, current_user.id)
    profile_skills = json.loads(profile.skills) if profile.skills else []

    client = get_claude_client()
    skills = await seed_required_skills(body.title, client)
    if not skills:
        raise HTTPException(status_code=422, detail="LLM could not generate skills. Try again.")

    await save_title_skills(db, current_user.id, body.title, skills, [])
    gap = compute_gap(skills, profile_skills)

    return SkillGapItem(
        title=body.title,
        required_skills=skills,
        have=gap["have"],
        missing=gap["missing"],
        coverage=gap["coverage"],
        last_updated=None,
    )


@router.post("/skill-gaps/seed-all", response_model=SeedAllGapResponse)
async def seed_all_skill_gaps(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Seed required skills for all target titles that have no data yet."""
    import asyncio
    from app.shared.skill_gap import get_all_title_skills, seed_required_skills, save_title_skills
    from app.shared.api_client import get_claude_client

    profile = await _get_or_create(db, current_user.id)
    target_titles = json.loads(profile.target_titles) if profile.target_titles else []
    if not target_titles:
        return SeedAllGapResponse(seeded=[], skipped=[])

    existing_rows = await get_all_title_skills(db, current_user.id)
    existing_titles_lower = {r["title"].strip().lower() for r in existing_rows}

    # Only seed titles with no existing data
    to_seed = [t for t in target_titles if t.strip().lower() not in existing_titles_lower]
    already_have = [t for t in target_titles if t.strip().lower() in existing_titles_lower]

    client = get_claude_client()

    async def _seed_one(title: str) -> str | None:
        skills = await seed_required_skills(title, client)
        if skills:
            await save_title_skills(db, current_user.id, title, skills, [])
            return title
        return None

    # Run sequentially to avoid hammering the local LLM
    seeded: list[str] = []
    for title in to_seed:
        result = await _seed_one(title)
        if result:
            seeded.append(result)

    return SeedAllGapResponse(seeded=seeded, skipped=already_have)
