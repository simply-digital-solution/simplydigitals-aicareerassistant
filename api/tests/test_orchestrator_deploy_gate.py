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


# ── Path filters: a change to a pipeline's own workflow file must trigger that pipeline ──

WORKFLOWS = ORCHESTRATOR.parent


@pytest.fixture(scope="module")
def path_filters(jobs):
    step = next(s for s in jobs["detect"]["steps"] if s.get("id") == "filter")
    return yaml.safe_load(step["with"]["filters"])


@pytest.mark.parametrize(
    "pipeline, workflow",
    [("api", "api-ci.yml"), ("ui", "ui-ci.yml"), ("website", "website-ci.yml")],
)
def test_pipeline_workflow_file_triggers_its_pipeline(path_filters, pipeline, workflow):
    assert (WORKFLOWS / workflow).exists()
    assert f".github/workflows/{workflow}" in path_filters[pipeline]


@pytest.mark.parametrize("pipeline", ["api", "ui", "website"])
def test_orchestrator_change_triggers_every_pipeline(path_filters, pipeline):
    assert ".github/workflows/orchestrator.yml" in path_filters[pipeline]
