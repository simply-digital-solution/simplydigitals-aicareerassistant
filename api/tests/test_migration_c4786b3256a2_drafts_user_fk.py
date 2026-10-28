"""Verifies the migration adding the drafts.user_id foreign key."""
import importlib.util
import pathlib
from unittest.mock import MagicMock, patch

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

API_DIR = pathlib.Path(__file__).parent.parent


def _load_migration():
    path = API_DIR / "migrations/versions/c4786b3256a2_add_drafts_user_id_fk.py"
    spec = importlib.util.spec_from_file_location("migration_c4786b3256a2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mock_op(dangling: int) -> MagicMock:
    mock_op = MagicMock()
    mock_op.get_bind.return_value.execute.return_value.scalar.return_value = dangling
    return mock_op


def test_upgrade_creates_foreign_key_to_users():
    mod = _load_migration()
    mock_op = _mock_op(dangling=0)
    with patch.object(mod, "op", mock_op):
        mod.upgrade()
    mock_op.create_foreign_key.assert_called_once_with(
        "drafts_user_id_fkey", "drafts", "users", ["user_id"], ["id"]
    )


def test_upgrade_raises_and_creates_nothing_when_dangling_rows_exist():
    mod = _load_migration()
    mock_op = _mock_op(dangling=2)
    with patch.object(mod, "op", mock_op):
        with pytest.raises(RuntimeError, match="2 drafts row"):
            mod.upgrade()
    mock_op.create_foreign_key.assert_not_called()


def test_downgrade_drops_foreign_key():
    mod = _load_migration()
    mock_op = MagicMock()
    with patch.object(mod, "op", mock_op):
        mod.downgrade()
    mock_op.drop_constraint.assert_called_once_with(
        "drafts_user_id_fkey", "drafts", type_="foreignkey"
    )


def test_migration_chains_onto_previous_revision_and_repo_has_single_head():
    mod = _load_migration()
    assert mod.down_revision == "cd67c0c34a89"
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    assert ScriptDirectory.from_config(cfg).get_heads() == ["c4786b3256a2"]
