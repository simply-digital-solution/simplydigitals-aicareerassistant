"""Guards against the ORM models drifting from what the migrations create."""
from app.shared.models import AgentRun, Draft, GeneratedResume

# Columns the live schema has (from migrations 012 and later) for generated_resumes.
_GENERATED_RESUME_COLUMNS = {
    "id", "user_id", "job_posting_id", "application_id", "resume_json",
    "drive_file_id", "drive_link", "created_at", "updated_at",
}


def test_generated_resume_model_has_no_column_missing_from_the_schema():
    # drive_pdf_file_id was once declared on the model with no migration,
    # so any ORM select of GeneratedResume failed with UndefinedColumnError.
    assert set(GeneratedResume.__table__.columns.keys()) == _GENERATED_RESUME_COLUMNS


def test_agent_run_user_id_is_nullable_like_the_database():
    # Migration a4001bda2f32 made it nullable so system runs
    # (industry_backfill) can log without a user.
    assert AgentRun.__table__.columns["user_id"].nullable is True


def test_draft_user_id_declares_foreign_key_to_users():
    fks = {fk.target_fullname for fk in Draft.__table__.columns["user_id"].foreign_keys}
    assert fks == {"users.id"}
