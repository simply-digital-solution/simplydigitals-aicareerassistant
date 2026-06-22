"""Verifies migration 022 adds seniority_level and target_titles to profiles."""
import importlib.util
import pathlib

import sqlalchemy as sa
from unittest.mock import MagicMock, patch


def _load_migration():
    path = (
        pathlib.Path(__file__).parent.parent
        / "migrations/versions/c0d1e2f3a4b5_022_add_seniority_target_titles_to_profiles.py"
    )
    spec = importlib.util.spec_from_file_location("migration_022", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_upgrade_adds_seniority_level():
    mod = _load_migration()
    mock_op = MagicMock()
    with patch.object(mod, "op", mock_op):
        mod.upgrade()
    calls = mock_op.add_column.call_args_list
    tables = [c[0][0] for c in calls]
    col_names = [c[0][1].name for c in calls]
    assert "profiles" in tables
    assert "seniority_level" in col_names


def test_upgrade_adds_target_titles():
    mod = _load_migration()
    mock_op = MagicMock()
    with patch.object(mod, "op", mock_op):
        mod.upgrade()
    calls = mock_op.add_column.call_args_list
    col_names = [c[0][1].name for c in calls]
    assert "target_titles" in col_names


def test_upgrade_calls_add_column_twice():
    mod = _load_migration()
    mock_op = MagicMock()
    with patch.object(mod, "op", mock_op):
        mod.upgrade()
    assert mock_op.add_column.call_count == 2


def test_downgrade_drops_both_columns():
    mod = _load_migration()
    mock_op = MagicMock()
    with patch.object(mod, "op", mock_op):
        mod.downgrade()
    assert mock_op.drop_column.call_count == 2
    dropped = {c[0][1] for c in mock_op.drop_column.call_args_list}
    assert dropped == {"seniority_level", "target_titles"}
