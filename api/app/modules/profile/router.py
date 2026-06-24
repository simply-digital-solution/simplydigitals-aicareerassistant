import base64
import io
import json
import docx
import pdfplumber

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text

from app.shared.database import get_db, get_db_context
from app.modules.auth.router import get_current_user
from app.shared.models import Profile
from app.shared.resume_detail_extractor import extract_resume_details, deduplicate_certifications
from app.shared.api_client import get_llm_client

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


async def _get_job_industry_labels(user_id: int, db: AsyncSession) -> list[str]:
    """Return distinct industry labels from the user's job postings, sorted."""
    rows = await db.execute(text("""
        SELECT DISTINCT value
        FROM user_job_postings ujp
        JOIN job_postings jp ON jp.id = ujp.job_posting_id,
             json_array_elements_text(jp.inferred_industries::json) AS value
        WHERE ujp.user_id = :uid
          AND jp.inferred_industries IS NOT NULL
          AND jp.inferred_industries != '[]'
        ORDER BY value
    """), {"uid": user_id})
    return [r[0] for r in rows.fetchall()]


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
    resume_obj: str | None = None
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
    education: str | None = None             # JSON array of {degree, institution, year}
    certifications: str | None = None        # JSON array of {name, issuer, issued_date, expiry_date}
    phone_number: str | None = None


class ProfileResponse(BaseModel):
    resume_text: str | None
    resume_obj: str | None
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
    education: str | None
    certifications: str | None
    phone_number: str | None

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
    obj: str | None = None       # base64-encoded original file (PDF or DOCX); None for TXT/MD
    mime: str | None = None      # MIME type matching obj


def _extract_text_from_pdf(content: bytes) -> str:
    """Extract plain text from a PDF using pdfplumber."""
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                parts.append(page_text)
    return "\n\n".join(parts)


def _extract_text_from_docx(content: bytes) -> str:
    """Extract plain text from a DOCX."""
    doc = docx.Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


@router.post("/parse-resume", response_model=ParsedResumeResponse)
async def parse_resume_file(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    filename = (file.filename or "").lower()
    obj: str | None = None
    mime: str | None = None

    if filename.endswith(".pdf"):
        try:
            text = _extract_text_from_pdf(content)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not parse PDF: {e}")
        obj = base64.b64encode(content).decode("ascii")
        mime = "application/pdf"

    elif filename.endswith(".docx"):
        try:
            text = _extract_text_from_docx(content)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not parse DOCX: {e}")
        obj = base64.b64encode(content).decode("ascii")
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    elif filename.endswith((".txt", ".md")):
        text = content.decode("utf-8", errors="replace")

    else:
        raise HTTPException(status_code=415, detail="Unsupported file type. Upload PDF, DOCX, TXT, or MD.")

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the file.")

    profile = await _get_or_create(db, current_user.id)
    if obj is not None:
        profile.resume_obj = obj
    await db.commit()

    return ParsedResumeResponse(text=text, obj=obj, mime=mime)


@router.post("/extract-and-save", response_model=ProfileResponse)
async def extract_and_save(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run LLM extraction on the saved resume and additively merge all extracted
    fields into the profile. Nothing is ever removed — only new values added.
    Deduplication is applied to every array field.
    """
    profile = await _get_or_create(db, current_user.id)
    if not profile.resume_text or not profile.resume_text.strip():
        raise HTTPException(status_code=422, detail="No resume found. Upload your resume first.")

    client = get_llm_client()
    job_labels = await _get_job_industry_labels(current_user.id, db)
    extracted = await extract_resume_details(profile.resume_text, client, job_industry_labels=job_labels)

    # --- Additive merge helpers ---
    def _merge_str_array(existing_json: str | None, new_items: list[str]) -> str:
        existing = json.loads(existing_json) if existing_json else []
        existing_lower = {s.strip().lower() for s in existing}
        merged = existing + [s for s in new_items if s.strip().lower() not in existing_lower]
        return _dedupe_json_array(json.dumps(merged)) or "[]"

    def _merge_education(existing_json: str | None, new_items: list[dict]) -> str:
        existing = json.loads(existing_json) if existing_json else []
        existing_keys = {
            (e.get("degree", "").strip().lower(), e.get("institution", "").strip().lower())
            for e in existing
        }
        for entry in new_items:
            key = (entry.get("degree", "").strip().lower(), entry.get("institution", "").strip().lower())
            if key not in existing_keys and (key[0] or key[1]):
                existing.append(entry)
                existing_keys.add(key)
        return json.dumps(existing)

    def _merge_certifications(existing_json: str | None, new_items: list[dict]) -> str:
        existing = json.loads(existing_json) if existing_json else []
        existing_keys = {
            (e.get("name", "").strip().lower(), e.get("issuer", "").strip().lower())
            for e in existing
        }
        for entry in new_items:
            key = (entry.get("name", "").strip().lower(), entry.get("issuer", "").strip().lower())
            if key not in existing_keys and key[0]:
                existing.append(entry)
                existing_keys.add(key)
        return json.dumps(existing)

    # Merge each field additively
    if extracted["years_experience"] is not None:
        profile.years_experience = extracted["years_experience"]

    if extracted["seniority_level"]:
        profile.seniority_level = extracted["seniority_level"]

    if extracted["target_industries"]:
        profile.target_industries = _merge_str_array(profile.target_industries, extracted["target_industries"])

    if extracted["target_roles"]:
        profile.target_titles = _merge_str_array(profile.target_titles, extracted["target_roles"])

    if extracted["skills"]:
        profile.skills = _merge_str_array(profile.skills, extracted["skills"])

    if extracted["education"]:
        profile.education = _merge_education(profile.education, extracted["education"])

    merged_certs_json = _merge_certifications(profile.certifications, extracted["certifications"])
    merged_certs = json.loads(merged_certs_json)
    if len(merged_certs) > 1:
        merged_certs = await deduplicate_certifications(merged_certs, client)
    profile.certifications = json.dumps(merged_certs)

    # Contact: only write if currently empty
    phone = extracted["contact"].get("phone", "")
    if phone and not profile.phone_number:
        profile.phone_number = phone

    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("", response_model=ProfileResponse)
async def get_profile(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create(db, current_user.id)
    return profile


async def _background_extract(user_id: int) -> None:
    """Run LLM extraction on saved resume_text and merge results — called as a background task."""
    import logging
    _log = logging.getLogger(__name__)
    try:
        async with get_db_context() as db:
            result = await db.execute(select(Profile).where(Profile.user_id == user_id))
            profile = result.scalar_one_or_none()
            if not profile or not profile.resume_text:
                return
            client = get_llm_client()
            job_labels = await _get_job_industry_labels(user_id, db)
            extracted = await extract_resume_details(profile.resume_text, client, job_industry_labels=job_labels)
            if extracted["years_experience"] is not None:
                profile.years_experience = extracted["years_experience"]
            if extracted["seniority_level"]:
                profile.seniority_level = extracted["seniority_level"]
            if extracted["target_industries"]:
                profile.target_industries = _dedupe_json_array(json.dumps(extracted["target_industries"]))
            if extracted["skills"]:
                existing_skills = json.loads(profile.skills) if profile.skills else []
                if not existing_skills:
                    profile.skills = _dedupe_json_array(json.dumps(extracted["skills"]))
            await db.commit()
    except Exception:
        _log.warning("Background LLM extraction failed for user %s", user_id, exc_info=True)


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdate,
    background_tasks: BackgroundTasks,
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

    await db.commit()
    await db.refresh(profile)

    # Fire LLM extraction after response is sent — doesn't block the user
    if 'resume_text' in updates and updates['resume_text']:
        background_tasks.add_task(_background_extract, current_user.id)

    return profile


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
    profile = await _get_or_create(db, current_user.id)
    if not profile.resume_text or not profile.resume_text.strip():
        raise HTTPException(status_code=422, detail="No resume found. Upload your resume first.")

    client = get_llm_client()
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
    from app.shared.api_client import get_llm_client

    profile = await _get_or_create(db, current_user.id)
    profile_skills = json.loads(profile.skills) if profile.skills else []

    rows = await get_all_title_skills(db, current_user.id)
    row = next((r for r in rows if r["title"].lower() == body.title.lower()), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"No data for title '{body.title}'. Run a research search first.")

    client = get_llm_client()
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
    from app.shared.api_client import get_llm_client

    profile = await _get_or_create(db, current_user.id)
    profile_skills = json.loads(profile.skills) if profile.skills else []

    client = get_llm_client()
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
    from app.shared.api_client import get_llm_client

    profile = await _get_or_create(db, current_user.id)
    target_titles = json.loads(profile.target_titles) if profile.target_titles else []
    if not target_titles:
        return SeedAllGapResponse(seeded=[], skipped=[])

    existing_rows = await get_all_title_skills(db, current_user.id)
    existing_titles_lower = {r["title"].strip().lower() for r in existing_rows}

    # Only seed titles with no existing data
    to_seed = [t for t in target_titles if t.strip().lower() not in existing_titles_lower]
    already_have = [t for t in target_titles if t.strip().lower() in existing_titles_lower]

    client = get_llm_client()

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
