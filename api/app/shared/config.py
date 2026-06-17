from pydantic_settings import BaseSettings, SettingsConfigDict
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

    # Claude
    anthropic_api_key: str = ""

    # Ollama model (local, no API cost)
    coordinator_model: str = "llama3.1:8b"
    specialist_model: str = "llama3.1:8b"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"

    # Agent limits
    max_tool_iterations: int = 25
    max_self_corrections: int = 3
    max_concurrent_jobs: int = 5
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
