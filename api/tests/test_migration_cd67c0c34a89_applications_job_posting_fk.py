"""Verifies the migration adding the applications.job_posting_id FK and index."""
import importlib.util
import pathlib
from unittest.mock import MagicMock, patch

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

API_DIR = pathlib.Path(__file__).parent.parent


def _load_migration():
    path = API_DIR / "migrations/versions/cd67c0c34a89_add_applications_job_posting_id_fk_and_.py"
    spec = importlib.util.spec_from_file_location("migration_cd67c0c34a89", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mock_op(dangling: int) -> MagicMock:
    mock_op = MagicMock()
    mock_op.get_bind.return_value.execute.return_value.scalar.return_value = dangling
    return mock_op


def test_upgrade_creates_foreign_key_to_job_postings():
    mod = _load_migration()
    mock_op = _mock_op(dangling=0)
    with patch.object(mod, "op", mock_op):
        mod.upgrade()
    mock_op.create_foreign_key.assert_called_once_with(
        "applications_job_posting_id_fkey",
        "applications",
        "job_postings",
        ["job_posting_id"],
        ["id"],
    )


def test_upgrade_creates_index():
    mod = _load_migration()
    mock_op = _mock_op(dangling=0)
    with patch.object(mod, "op", mock_op):
        mod.upgrade()
    mock_op.create_index.assert_called_once_with(
        "ix_applications_job_posting_id", "applications", ["job_posting_id"]
    )


def test_upgrade_raises_and_creates_nothing_when_dangling_rows_exist():
    mod = _load_migration()
    mock_op = _mock_op(dangling=3)
    with patch.object(mod, "op", mock_op):
        with pytest.raises(RuntimeError, match="3 applications row"):
            mod.upgrade()
    mock_op.create_foreign_key.assert_not_called()
    mock_op.create_index.assert_not_called()


def test_downgrade_drops_index_then_foreign_key():
    mod = _load_migration()
    mock_op = MagicMock()
    with patch.object(mod, "op", mock_op):
        mod.downgrade()
    mock_op.drop_index.assert_called_once_with(
        "ix_applications_job_posting_id", table_name="applications"
    )
    mock_op.drop_constraint.assert_called_once_with(
        "applications_job_posting_id_fkey", "applications", type_="foreignkey"
    )
    names = [c[0] for c in mock_op.method_calls]
    assert names.index("drop_index") < names.index("drop_constraint")


def test_migration_chains_onto_previous_head_and_repo_has_single_head():
    mod = _load_migration()
    assert mod.down_revision == "a4001bda2f32"
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1
    assert script.get_revision("cd67c0c34a89") is not None
