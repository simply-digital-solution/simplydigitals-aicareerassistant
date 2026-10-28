"""The generate-resume endpoint's default body is a shared read-only instance."""
import inspect

from app.modules.agents.router import (
    _DEFAULT_GENERATE_RESUME_REQUEST,
    GenerateResumeRequest,
    generate_resume,
)


def test_default_body_is_an_empty_generate_resume_request():
    assert isinstance(_DEFAULT_GENERATE_RESUME_REQUEST, GenerateResumeRequest)
    assert _DEFAULT_GENERATE_RESUME_REQUEST.additional_context == ""


def test_endpoint_uses_the_shared_default_body():
    default = inspect.signature(generate_resume).parameters["body"].default
    assert default is _DEFAULT_GENERATE_RESUME_REQUEST
