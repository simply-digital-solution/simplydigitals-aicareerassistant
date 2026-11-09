"""
Keeps scripts/scrape_and_score.sh's default backend URL in step with the port
`make dev` serves on.
"""
import re
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent


def _makefile_dev_port() -> str:
    makefile = (API_DIR / "Makefile").read_text()
    match = re.search(r"^dev:.*?--port (\d+)", makefile, re.MULTILINE | re.DOTALL)
    assert match, "could not find --port in the Makefile's dev target"
    return match.group(1)


def _script_default_url() -> str:
    script = (API_DIR / "scripts" / "scrape_and_score.sh").read_text()
    match = re.search(r'^BACKEND_URL="\$\{2:-([^}]+)\}"', script, re.MULTILINE)
    assert match, "could not find the BACKEND_URL default in scrape_and_score.sh"
    return match.group(1)


def test_default_backend_url_matches_make_dev_port():
    assert _script_default_url() == f"http://localhost:{_makefile_dev_port()}"
