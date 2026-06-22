"""Ensures the production config guard raises on misconfigured secrets."""
import pytest
from app.shared.config import Settings


VALID = dict(
    app_env="production",
    database_url="postgresql+asyncpg://user:pass@host/db",
    jwt_secret_key="a-real-secret-key-that-is-long-enough",
)


def test_production_empty_database_url_raises():
    with pytest.raises(RuntimeError, match="not set"):
        Settings(**{**VALID, "database_url": ""})


def test_production_unexpanded_secret_raises():
    with pytest.raises(RuntimeError, match="unexpanded"):
        Settings(**{**VALID, "database_url": "${{ secrets.DATABASE_URL }}"})


def test_production_empty_jwt_raises():
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        Settings(**{**VALID, "jwt_secret_key": ""})


def test_production_default_jwt_raises():
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        Settings(**{**VALID, "jwt_secret_key": "change-me"})


def test_production_valid_config_passes():
    s = Settings(**VALID)
    assert s.app_env == "production"
    assert "postgresql" in s.database_url
