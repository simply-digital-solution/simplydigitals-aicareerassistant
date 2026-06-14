"""
Skill extractor using taxonomy phrase matching.

Loads a curated skills taxonomy from data/skills_taxonomy.json and matches
multi-word and single-word skill phrases against resume text using whole-word
regex. Fast (~5ms), no GPU required, works offline.
"""
import json
import re
from pathlib import Path

_TAXONOMY_PATH = Path(__file__).parents[3] / "data" / "skills_taxonomy.json"
_taxonomy_mtime: float = 0.0


def _load_taxonomy() -> dict[str, list[str]]:
    return json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))


_patterns_cache: list[tuple[str, str, re.Pattern]] | None = None


def _build_patterns() -> list[tuple[str, str, re.Pattern]]:
    """
    Returns list of (category, skill, compiled_pattern) sorted longest-first
    so multi-word phrases match before their component words.

    Reloads taxonomy if the file has been modified since last build.
    """
    global _patterns_cache, _taxonomy_mtime
    mtime = _TAXONOMY_PATH.stat().st_mtime
    if _patterns_cache is not None and mtime == _taxonomy_mtime:
        return _patterns_cache

    taxonomy = _load_taxonomy()
    _taxonomy_mtime = mtime

    entries: list[tuple[str, str]] = []
    for category, skills in taxonomy.items():
        for skill in skills:
            entries.append((category, skill))

    # Sort by skill length descending — match "Machine Learning" before "Learning"
    entries.sort(key=lambda x: len(x[1]), reverse=True)

    patterns = []
    for category, skill in entries:
        escaped = re.escape(skill)
        # Word boundary aware: handles "C++" and "C#" which contain special chars
        pattern = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
        patterns.append((category, skill, pattern))

    _patterns_cache = patterns
    return patterns


def extract_skills(text: str) -> list[dict]:
    """
    Extract skills from resume text.

    Returns list of dicts: [{"skill": str, "category": str}]
    Ordered by category, deduplicated (case-insensitive).
    """
    patterns = _build_patterns()
    seen: set[str] = set()
    results: list[dict] = []

    for category, skill, pattern in patterns:
        if pattern.search(text):
            key = skill.lower()
            if key not in seen:
                seen.add(key)
                results.append({"skill": skill, "category": category})

    return results


def extract_skill_names(text: str) -> list[str]:
    """Return just skill names (no category), deduplicated, sorted alphabetically."""
    extracted = extract_skills(text)
    return sorted({e["skill"] for e in extracted})
