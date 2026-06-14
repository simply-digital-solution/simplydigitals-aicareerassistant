"""
Seniority level extractor.

Strategy:
1. Extract job titles from resume text using regex (lines near dates/companies).
2. Match each title against a keyword dictionary — covers ~95% of cases instantly.
3. For titles that don't match any keyword, use BERT zero-shot classification as fallback.
4. Combine with years-of-experience heuristic as a final validator/tiebreaker.

Returns one of: junior | mid | senior | lead | principal | director | vp | executive
"""
import re
from functools import lru_cache
from typing import Optional

# ---------------------------------------------------------------------------
# Seniority tiers (ordered low → high, used for comparison)
# ---------------------------------------------------------------------------

TIERS = ["junior", "mid", "senior", "lead", "principal", "director", "vp", "executive"]

# Years-of-experience thresholds as a fallback/validator
_YOE_TIERS = [
    (0,  2,  "junior"),
    (2,  5,  "mid"),
    (5,  9,  "senior"),
    (9,  13, "lead"),
    (13, 18, "principal"),
    (18, 25, "director"),
    (25, 99, "vp"),
]

# ---------------------------------------------------------------------------
# Keyword dictionary — longest phrases first (matched in order)
# ---------------------------------------------------------------------------

_KEYWORD_MAP: list[tuple[re.Pattern, str]] = []

_RAW_KEYWORDS: list[tuple[list[str], str]] = [
    # executive
    (["chief executive", "chief operating", "chief financial", "chief technology",
      "chief product", "chief marketing", "chief data", "chief revenue",
      r"\bceo\b", r"\bcoo\b", r"\bcfo\b", r"\bcto\b", r"\bcpo\b", r"\bcmo\b",
      r"\bcdo\b", "c-suite", "founder", "co-founder", "president", "managing partner"],
     "executive"),
    # vp
    (["vice president", r"\bvp\b", "svp", "evp", "group vp", "managing director",
      r"\bmd\b(?! of)", "group director"],
     "vp"),
    # director
    (["director", "head of", "global head", "regional head"],
     "director"),
    # principal
    (["principal", "distinguished engineer", "fellow", "staff engineer",
      "staff scientist", "staff researcher", "staff product manager",
      "partner", "associate partner", "associate director"],
     "principal"),
    # lead
    (["lead", "tech lead", "technical lead", "team lead", "squad lead",
      "chapter lead", "group manager", "engineering manager", "product manager",
      "product owner", "program manager", "project manager", "delivery manager",
      "product lead", "senior manager", "associate principal"],
     "lead"),
    # senior
    (["senior", r"\bsr\.?\b", "specialist", "experienced", "ii\b", r"\b2\b"],
     "senior"),
    # mid
    (["manager", "consultant", "analyst", "engineer", "developer", "designer",
      "scientist", "researcher", "associate"],
     "mid"),
    # junior
    (["junior", r"\bjr\.?\b", "graduate", "grad", "intern", "trainee",
      "entry level", "entry-level", "apprentice", "assistant", "i\b", r"\b1\b"],
     "junior"),
]


def _build_keyword_patterns():
    for keywords, tier in _RAW_KEYWORDS:
        combined = "|".join(keywords)
        pattern = re.compile(rf"(?i)(?:^|\s|,)({combined})(?:\s|$|,)", re.IGNORECASE)
        _KEYWORD_MAP.append((pattern, tier))


_build_keyword_patterns()


def _match_keywords(title: str) -> Optional[str]:
    """Return tier if any keyword matches the title, else None."""
    for pattern, tier in _KEYWORD_MAP:
        if pattern.search(title):
            return tier
    return None


# ---------------------------------------------------------------------------
# BERT zero-shot fallback (lazy-loaded, cached)
# ---------------------------------------------------------------------------

_ZS_LABELS = ["junior or entry level", "mid level", "senior", "lead or principal", "director or vp", "executive or c-suite"]
_ZS_TIER_MAP = {
    "junior or entry level": "junior",
    "mid level": "mid",
    "senior": "senior",
    "lead or principal": "lead",
    "director or vp": "director",
    "executive or c-suite": "executive",
}
_BERT_MIN_CONFIDENCE = 0.50   # below this, fall back to years-of-experience


@lru_cache(maxsize=1)
def _get_zs_pipeline():
    from transformers import pipeline  # type: ignore
    return pipeline("zero-shot-classification", model="cross-encoder/nli-MiniLM2-L6-H768")


def _classify_bert(title: str) -> Optional[str]:
    try:
        nlp = _get_zs_pipeline()
        result = nlp(title, _ZS_LABELS)
        top_label: str = result["labels"][0]
        top_score: float = result["scores"][0]
        if top_score >= _BERT_MIN_CONFIDENCE:
            return _ZS_TIER_MAP.get(top_label)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Job title extraction from resume text
# ---------------------------------------------------------------------------

_DATE_PATTERN = re.compile(
    r"""
    (?:
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+\d{4}  # "Jan 2020"
        |\d{4}\s*[-–—]\s*(?:\d{4}|present|current|now)                        # "2018 – 2022"
        |\d{1,2}/\d{4}                                                          # "01/2020"
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

_TITLE_PATTERNS = [
    # "Product Owner – Strategic Valuation..." (em-dash or en-dash separator)
    re.compile(r'^([A-Z][A-Za-z &/,\-\.]+?)\s*[–—]\s*[A-Z]', re.MULTILINE),
    # "Senior PM | Google | 2019 – Present"  or  "Senior PM @ Google"
    re.compile(r'^([A-Z][A-Za-z &/,\-\.]+?)(?:\s*[|@]\s*[A-Z])', re.MULTILINE),
    # "Senior PM, Google, 2019"
    re.compile(r'^([A-Z][A-Za-z &/,\-\.]+?),\s*[A-Z][a-zA-Z]', re.MULTILINE),
    # Standalone title line near a date
    re.compile(r'^([A-Z][A-Za-z &/,\-\.]{3,60})\s*$', re.MULTILINE),
]

_STOP_WORDS = {
    "education", "experience", "work experience", "skills", "summary", "profile",
    "projects", "certifications", "awards", "publications", "languages", "interests",
    "references", "objective", "achievements", "responsibilities", "duties",
    "university", "bachelor", "master", "phd", "b.sc", "m.sc", "b.eng",
    "professional experience", "career history", "employment history",
}


def _extract_titles(resume_text: str) -> list[str]:
    """
    Pull candidate job title strings from resume text.
    Returns deduplicated list, most recent first (approximate).
    """
    seen: set[str] = set()
    titles: list[str] = []

    # Only look in lines near date patterns for precision
    lines = resume_text.split("\n")
    date_line_indices: set[int] = set()
    for i, line in enumerate(lines):
        if _DATE_PATTERN.search(line):
            for j in range(max(0, i - 3), min(len(lines), i + 2)):
                date_line_indices.add(j)

    context = "\n".join(lines[i] for i in sorted(date_line_indices)) if date_line_indices else resume_text

    for pattern in _TITLE_PATTERNS:
        for m in pattern.finditer(context):
            candidate = m.group(1).strip().rstrip(".,;:")
            lower = candidate.lower()
            if lower in _STOP_WORDS or len(candidate) < 4 or len(candidate) > 80:
                continue
            if candidate not in seen:
                seen.add(candidate)
                titles.append(candidate)

    return titles


# ---------------------------------------------------------------------------
# Years-of-experience fallback
# ---------------------------------------------------------------------------

def _yoe_to_tier(years: Optional[int]) -> str:
    if years is None:
        return "mid"
    for lo, hi, tier in _YOE_TIERS:
        if lo <= years < hi:
            return tier
    return "vp"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_seniority(resume_text: str, years_experience: Optional[int] = None) -> dict:
    """
    Extract seniority level from resume text.

    Returns:
        {
            "seniority_level": str,   # one of TIERS
            "method": str,            # "keyword" | "bert" | "yoe_fallback"
            "titles_found": list[str],
            "confidence": float,      # 1.0 for keyword, bert score, 0.5 for fallback
        }
    """
    titles = _extract_titles(resume_text)

    # Score each title — take the highest tier found (most senior role held)
    tier_scores: dict[str, int] = {}
    method_used = "yoe_fallback"
    bert_confidence = 0.0

    for title in titles:
        # 1. Keyword match
        kw_tier = _match_keywords(title)
        if kw_tier:
            idx = TIERS.index(kw_tier)
            tier_scores[kw_tier] = max(tier_scores.get(kw_tier, 0), idx)
            method_used = "keyword"
            continue

        # 2. BERT fallback for unmatched titles
        bert_tier = _classify_bert(title)
        if bert_tier:
            idx = TIERS.index(bert_tier)
            tier_scores[bert_tier] = max(tier_scores.get(bert_tier, 0), idx)
            if method_used != "keyword":
                method_used = "bert"

    if tier_scores:
        # Pick the highest-scoring tier found
        best_tier = max(tier_scores, key=lambda t: TIERS.index(t))
        confidence = 1.0 if method_used == "keyword" else bert_confidence or 0.65
    else:
        # Nothing extracted — use years of experience
        best_tier = _yoe_to_tier(years_experience)
        confidence = 0.5
        method_used = "yoe_fallback"

    return {
        "seniority_level": best_tier,
        "method": method_used,
        "titles_found": titles[:10],
        "confidence": confidence,
    }
