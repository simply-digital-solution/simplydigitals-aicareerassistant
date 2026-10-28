"""
Deployment is opt-in: every deploy / post-deploy path in the CI orchestrator must
be gated on the ENABLE_DEPLOY repository variable, so merging to main runs CI only
until deployment is deliberately switched on.
"""
from pathlib import Path

import pytest
import yaml

ORCHESTRATOR = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "orchestrator.yml"
GATE = "vars.ENABLE_DEPLOY == 'true'"


@pytest.fixture(scope="module")
def jobs():
    return yaml.safe_load(ORCHESTRATOR.read_text())["jobs"]


@pytest.mark.parametrize("job", ["api", "ui", "website"])
def test_run_deploy_input_requires_enable_deploy(jobs, job):
    assert GATE in jobs[job]["with"]["run_deploy"]


def test_post_deploy_tests_require_enable_deploy(jobs):
    assert GATE in jobs["post-deploy-tests"]["if"]


@pytest.mark.parametrize("job", ["api", "ui"])
def test_ci_inputs_are_not_gated_on_enable_deploy(jobs, job):
    for name in ("run_lint", "run_tests"):
        assert "ENABLE_DEPLOY" not in str(jobs[job]["with"][name])


def test_no_other_orchestrator_input_deploys_ungated(jobs):
    ungated = [
        name
        for name, job in jobs.items()
        if "run_deploy" in job.get("with", {}) and GATE not in job["with"]["run_deploy"]
    ]
    assert ungated == []
