"""
Keeps scripts/scrape_and_score.sh's default backend URL in step with the port
`make dev` serves on.
"""
import os
import re
import subprocess
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


# ---------------------------------------------------------------------------
# Anthropic key handling: only the script's classify/score steps get the key.
# ---------------------------------------------------------------------------

REPO_DIR = API_DIR.parent
SCRIPT = API_DIR / "scripts" / "scrape_and_score.sh"


def _run_script_in_sandbox(tmp_path, key_file_content):
    """Run a copy of the script in a temp api/ dir so its API_DIR has no real
    .env.anthropic. The key guard runs before the backend check, so these runs
    never reach the network, poetry, or the Anthropic API."""
    scripts_dir = tmp_path / "api" / "scripts"
    scripts_dir.mkdir(parents=True)
    script_copy = scripts_dir / "scrape_and_score.sh"
    script_copy.write_text(SCRIPT.read_text())
    if key_file_content is not None:
        (tmp_path / "api" / ".env.anthropic").write_text(key_file_content)
    return subprocess.run(
        # Port 1 is never served, so even past the guard the run stops at the
        # backend check and cannot scrape or score against a real dev backend.
        ["bash", str(script_copy), "user@example.com", "http://127.0.0.1:1"],
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"]},
        timeout=30,
    )


def test_script_stops_when_key_file_is_missing(tmp_path):
    result = _run_script_in_sandbox(tmp_path, key_file_content=None)
    assert result.returncode == 1
    assert ".env.anthropic" in result.stderr
    assert "Checking backend" not in result.stdout


def test_script_stops_when_key_is_empty(tmp_path):
    result = _run_script_in_sandbox(tmp_path, key_file_content="ANTHROPIC_API_KEY=\n")
    assert result.returncode == 1
    assert "empty" in result.stderr
    assert "Checking backend" not in result.stdout


def test_script_proceeds_past_key_guard_when_key_present(tmp_path):
    # With a key the guard passes and the script moves on to the backend check
    # (which then fails: nothing listens on port 1).
    result = _run_script_in_sandbox(
        tmp_path, key_file_content="ANTHROPIC_API_KEY=sk-ant-test\n"
    )
    assert "Checking backend" in result.stdout


def test_key_is_passed_only_to_classify_and_score_commands():
    lines = SCRIPT.read_text().splitlines()
    prefix = 'ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" '

    def command_lines(fragment):
        return [ln for ln in lines if fragment in ln and not ln.lstrip().startswith("#")]

    for fragment in ("app.pipeline.industry_backfill", "scripts.score_idle_jobs"):
        found = command_lines(fragment)
        assert len(found) == 1, f"expected one command for {fragment}"
        assert prefix in found[0]

    # Never exported, and never given to the scrape or the scrape summary.
    assert not any(re.match(r"\s*export\s+ANTHROPIC", ln) for ln in lines)
    for fragment in ("$SCRAPE_URL", "scripts.scrape_result"):
        for ln in command_lines(fragment):
            assert "ANTHROPIC_API_KEY" not in ln


def test_key_file_is_gitignored_and_has_a_template():
    gitignore = (REPO_DIR / ".gitignore").read_text().splitlines()
    assert ".env.anthropic" in gitignore
    assert (API_DIR / ".env.anthropic.example").exists()


def test_env_examples_do_not_set_the_key_for_the_server():
    for path in (API_DIR / ".env.example", REPO_DIR / ".env.example"):
        active = [
            ln for ln in path.read_text().splitlines()
            if ln.startswith("ANTHROPIC_API_KEY=")
        ]
        assert not active, f"{path} must not define ANTHROPIC_API_KEY for the server"


def test_deploy_pipeline_writes_the_key_into_the_production_env():
    api_ci = (REPO_DIR / ".github" / "workflows" / "api-ci.yml").read_text()
    orchestrator = (REPO_DIR / ".github" / "workflows" / "orchestrator.yml").read_text()
    assert 'echo "ANTHROPIC_API_KEY=${{ secrets.ANTHROPIC_API_KEY }}"' in api_ci
    assert "ANTHROPIC_API_KEY:     { required: false }" in api_ci
    assert "ANTHROPIC_API_KEY:     ${{ secrets.ANTHROPIC_API_KEY }}" in orchestrator
