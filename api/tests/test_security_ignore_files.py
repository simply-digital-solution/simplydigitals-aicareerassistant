"""
Guards the dependency-advisory allowlists read by CI (.pip-audit-ignore, .trivyignore).

Every ignored ID must carry a '# <package>: <reason>' comment directly above it,
and no ID may be listed twice, so the allowlist can't turn into a silent dump.
"""
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parent.parent
IGNORE_FILES = [API_DIR / ".pip-audit-ignore", API_DIR / ".trivyignore"]


def _entries(path: Path):
    """Yield (line_number, id, previous_line) for every non-comment, non-blank line."""
    lines = path.read_text().splitlines()
    for n, line in enumerate(lines, start=1):
        if line.strip() and not line.startswith("#"):
            yield n, line.strip(), lines[n - 2] if n > 1 else ""


@pytest.mark.parametrize("path", IGNORE_FILES, ids=lambda p: p.name)
def test_every_ignored_id_has_a_reason_comment_above_it(path):
    assert path.exists()
    for n, advisory_id, previous in _entries(path):
        assert " " not in advisory_id and "#" not in advisory_id, (
            f"{path.name}:{n} must hold only the advisory id (put the reason on the line above)"
        )
        assert previous.startswith("# ") and ":" in previous, (
            f"{path.name}:{n} ({advisory_id}) needs a '# <package>: <reason>' comment above it"
        )


@pytest.mark.parametrize("path", IGNORE_FILES, ids=lambda p: p.name)
def test_no_advisory_id_is_listed_twice(path):
    ids = [advisory_id for _, advisory_id, _ in _entries(path)]
    assert len(ids) == len(set(ids))


def test_guard_detects_missing_reason(tmp_path):
    bad = tmp_path / "bad-ignore"
    bad.write_text("# header\n\nCVE-2026-0001\n")

    [(_, advisory_id, previous)] = list(_entries(bad))

    assert advisory_id == "CVE-2026-0001"
    assert not (previous.startswith("# ") and ":" in previous)
