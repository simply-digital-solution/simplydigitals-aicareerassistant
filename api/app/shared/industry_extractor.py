"""
Industry extractor from resume text.

Strategy:
1. Match resume text against a keyword taxonomy per industry (fast, high precision).
2. Score each industry by keyword hit count — return top industries above threshold.
3. BERT zero-shot fallback for resumes with weak keyword signal.

Returns ranked list of industries with confidence scores.
"""
import re
from functools import lru_cache
from typing import Optional

# ---------------------------------------------------------------------------
# Industry taxonomy — keywords that strongly signal each industry
# ---------------------------------------------------------------------------

INDUSTRY_TAXONOMY: dict[str, list[str]] = {
    "Banking & Financial Services": [
        "bank", "banking", "investment bank", "retail bank", "commercial bank",
        "credit", "loan", "mortgage", "deposit", "treasury", "trade finance",
        "corporate banking", "transaction banking", "Basel", "AML", "KYC",
        "MAS", "FCA", "FINMA", "regulatory capital", "IFRS", "GAAP",
        "DBS", "OCBC", "UOB", "HSBC", "Citi", "JPMorgan", "Goldman Sachs",
        "Standard Chartered", "BNP Paribas", "Deutsche Bank",
    ],
    "Capital Markets & Investment Management": [
        "equity", "fixed income", "derivatives", "options", "futures", "bonds",
        "portfolio management", "asset management", "fund management",
        "hedge fund", "private equity", "venture capital", "IPO", "M&A",
        "DCF", "LBO", "valuation", "Bloomberg", "Reuters", "FactSet",
        "quant", "quantitative", "algorithmic trading", "market making",
        "prime brokerage", "FRM", "CFA", "securities",
    ],
    "Technology & Software": [
        "software engineer", "software development", "product manager",
        "SaaS", "cloud", "AWS", "Azure", "GCP", "Kubernetes", "Docker",
        "machine learning", "artificial intelligence", "data science",
        "startup", "tech company", "platform", "API", "microservices",
        "DevOps", "CI/CD", "agile", "scrum", "full stack",
        "Google", "Meta", "Amazon", "Microsoft", "Apple", "Grab", "Shopee",
        "Sea Group", "Stripe", "Twilio", "Salesforce",
    ],
    "Consulting & Professional Services": [
        "consulting", "management consulting", "strategy consulting",
        "McKinsey", "BCG", "Bain", "Deloitte", "PwC", "EY", "KPMG",
        "Accenture", "Oliver Wyman", "Roland Berger", "AT Kearney",
        "engagement manager", "associate consultant", "senior consultant",
        "client delivery", "transformation", "operating model",
    ],
    "Government & Public Sector": [
        "government", "ministry", "statutory board", "public sector",
        "GIC", "Temasek", "MAS", "EDB", "JTC", "HDB", "CPF", "IDA",
        "civil service", "policy", "regulation", "compliance officer",
        "public policy", "national", "federal", "municipal",
    ],
    "Healthcare & Life Sciences": [
        "hospital", "healthcare", "clinical", "pharmaceutical", "biotech",
        "medical device", "patient", "doctor", "nurse", "physician",
        "clinical trial", "FDA", "drug", "therapeutics", "genomics",
        "health system", "NHS", "MOH", "Singapore General Hospital",
    ],
    "Real Estate & Infrastructure": [
        "real estate", "property", "REIT", "construction", "infrastructure",
        "development", "asset", "facility management", "urban planning",
        "CapitaLand", "Mapletree", "Keppel", "Lendlease",
    ],
    "Supply Chain & Logistics": [
        "supply chain", "logistics", "procurement", "warehouse",
        "inventory", "shipping", "freight", "last mile", "3PL",
        "DHL", "FedEx", "UPS", "Maersk", "COSCO", "sourcing",
    ],
    "Media, Marketing & Communications": [
        "marketing", "brand", "advertising", "media", "PR",
        "communications", "content", "digital marketing", "SEO", "SEM",
        "social media", "campaign", "creative", "journalism", "publishing",
    ],
    "Education": [
        "education", "university", "school", "teaching", "curriculum",
        "academic", "research", "NUS", "NTU", "SMU", "SUTD", "lecturer",
        "professor", "student", "edtech", "learning",
    ],
    "Energy & Resources": [
        "energy", "oil", "gas", "renewable", "solar", "wind", "utilities",
        "mining", "commodities", "Shell", "ExxonMobil", "Chevron",
        "power plant", "grid", "sustainability", "ESG", "carbon",
    ],
    "Insurance": [
        "insurance", "underwriting", "actuary", "reinsurance", "claims",
        "AIA", "Prudential", "Great Eastern", "AXA", "Manulife",
        "life insurance", "general insurance", "policy", "premium",
    ],
}

_BERT_MIN_CONFIDENCE = 0.52
_MIN_KEYWORD_HITS = 2       # industry needs at least this many keyword hits
_MAX_INDUSTRIES = 3         # return at most this many industries


@lru_cache(maxsize=1)
def _build_patterns() -> dict[str, list[re.Pattern]]:
    patterns: dict[str, list[re.Pattern]] = {}
    for industry, keywords in INDUSTRY_TAXONOMY.items():
        patterns[industry] = [
            re.compile(rf"(?i)\b{re.escape(kw)}\b") for kw in keywords
        ]
    return patterns


def _keyword_score(text: str) -> dict[str, int]:
    """Return hit count per industry."""
    patterns = _build_patterns()
    scores: dict[str, int] = {}
    for industry, pats in patterns.items():
        hits = sum(1 for p in pats if p.search(text))
        if hits >= _MIN_KEYWORD_HITS:
            scores[industry] = hits
    return scores


@lru_cache(maxsize=1)
def _get_zs_pipeline():
    from transformers import pipeline  # type: ignore
    return pipeline("zero-shot-classification", model="cross-encoder/nli-MiniLM2-L6-H768")


def _bert_classify(text: str) -> list[dict]:
    """Run zero-shot classification against all industry labels."""
    try:
        nlp = _get_zs_pipeline()
        # Use a 512-token excerpt — BERT's max input length
        excerpt = text[:2000]
        labels = list(INDUSTRY_TAXONOMY.keys())
        result = nlp(excerpt, labels, multi_label=True)
        return [
            {"industry": label, "confidence": round(score, 3)}
            for label, score in zip(result["labels"], result["scores"])
            if score >= _BERT_MIN_CONFIDENCE
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_industries(resume_text: str) -> list[dict]:
    """
    Extract industries from resume text.

    Returns list of dicts ordered by confidence:
        [{"industry": str, "confidence": float, "method": str}]
    Max _MAX_INDUSTRIES results.
    """
    results: list[dict] = []

    # 1. Keyword scoring
    scores = _keyword_score(resume_text)
    if scores:
        max_hits = max(scores.values())
        for industry, hits in sorted(scores.items(), key=lambda x: -x[1]):
            confidence = round(min(hits / max(max_hits, 1), 1.0), 3)
            results.append({"industry": industry, "confidence": confidence, "method": "keyword"})

    # 2. BERT fallback for industries not caught by keywords
    keyword_industries = {r["industry"] for r in results}
    if len(results) < _MAX_INDUSTRIES:
        bert_results = _bert_classify(resume_text)
        for br in bert_results:
            if br["industry"] not in keyword_industries:
                results.append({**br, "method": "bert"})

    # Sort by confidence, cap at max
    results.sort(key=lambda x: -x["confidence"])
    return results[:_MAX_INDUSTRIES]


def extract_industry_names(resume_text: str) -> list[str]:
    """Return just industry names, ranked by confidence."""
    return [r["industry"] for r in extract_industries(resume_text)]
