"""Verifies migration 008 creates the job_feedback table from scratch."""
import importlib.util
import pathlib

import pytest
import sqlalchemy as sa
from unittest.mock import MagicMock, patch


def _load_migration():
    path = (
        pathlib.Path(__file__).parent.parent
        / "migrations/versions/276095669f8d_008_add_job_feedback_reason.py"
    )
    spec = importlib.util.spec_from_file_location("migration_008", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MIGRATION_MODULE = "migration_008"


def test_upgrade_calls_create_table():
    mod = _load_migration()
    mock_op = MagicMock()
    with patch.object(mod, "op", mock_op):
        mod.upgrade()
    assert mock_op.create_table.called
    table_name = mock_op.create_table.call_args[0][0]
    assert table_name == "job_feedback"


def test_upgrade_includes_required_columns():
    mod = _load_migration()
    mock_op = MagicMock()
    with patch.object(mod, "op", mock_op):
        mod.upgrade()
    col_names = {
        arg.name
        for arg in mock_op.create_table.call_args[0][1:]
        if isinstance(arg, sa.Column)
    }
    assert col_names >= {"id", "user_id", "job_url", "job_title", "company", "relevance", "reason"}


def test_upgrade_does_not_call_add_column():
    """Ensures the old broken approach (add_column on non-existent table) is gone."""
    mod = _load_migration()
    mock_op = MagicMock()
    with patch.object(mod, "op", mock_op):
        mod.upgrade()
    mock_op.add_column.assert_not_called()


def test_downgrade_calls_drop_table():
    mod = _load_migration()
    mock_op = MagicMock()
    with patch.object(mod, "op", mock_op):
        mod.downgrade()
    mock_op.drop_table.assert_called_once_with("job_feedback")
