from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from functools import lru_cache
from pathlib import Path

# Always resolve DB path relative to this file (api/app/shared/config.py → api/)
_API_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # Database — absolute path so it never moves regardless of cwd
    database_url: str = f"sqlite+aiosqlite:///{_API_DIR}/aicareercoach.db"

    # Auth
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 days

    # Gemini — required in production, optional in dev (falls back to Ollama)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"

    # Ollama — local dev only, not used in production
    specialist_model: str = "deepseek-r1:7b"

    # Agent limits
    max_tool_iterations: int = 25
    max_self_corrections: int = 3
    max_concurrent_jobs: int = 5
    scorer_batch_size: int = 20
    max_scorings_per_user_per_day: int = 50
    token_budget_per_session: int = 100_000

    # Monitor
    monitor_interval_seconds: int = 900  # 15 minutes
    stale_application_days: int = 14
    deadline_warning_hours: int = 48
    new_match_score_threshold: float = 0.75

    # Job board credentials (never sent to Claude)
    linkedin_email: str = ""
    linkedin_password: str = ""
    workday_email: str = ""
    workday_password: str = ""
    greenhouse_email: str = ""
    greenhouse_password: str = ""
    lever_email: str = ""
    lever_password: str = ""

    # Google OAuth2 (Drive integration)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"

    # Optional integrations
    news_api_key: str = ""

    # Adzuna (free tier: https://developer.adzuna.com)
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        if self.app_env != "production":
            return self
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set in production."
            )
        if "sqlite" in self.database_url:
            raise RuntimeError(
                "DATABASE_URL is SQLite in production — must be PostgreSQL."
            )
        if self.database_url.startswith("${{"):
            raise RuntimeError(
                "DATABASE_URL contains an unexpanded GitHub Actions secret — check the deploy workflow heredoc."
            )
        if self.jwt_secret_key in ("change-me", ""):
            raise RuntimeError(
                "JWT_SECRET_KEY is not set in production."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
