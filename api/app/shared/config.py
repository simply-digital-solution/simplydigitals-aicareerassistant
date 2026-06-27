from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    frontend_url: str = "http://localhost:5173"
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"
    enable_scheduler: bool = True

    # Database — must be set in .env (PostgreSQL for both dev and prod)
    database_url: str = ""

    # Auth
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 days

    # Gemini — required in production, optional in dev (falls back to Ollama)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_fallback_model: str = "gemini-2.5-flash"

    # Ollama — local dev only, not used in production
    specialist_model: str = "deepseek-r1:7b"

    # Agent limits
    max_tool_iterations: int = 25
    max_self_corrections: int = 3
    max_concurrent_jobs: int = 5
    scorer_batch_size: int = 1
    max_scorings_per_user_per_day: int = 50    # existing users
    new_user_scoring_limit: int = 250          # users who have never had a job scored
    token_budget_per_session: int = 100_000

    # LLM rate limiting — Gemini paid tier is 1000 RPM; free tier was 15
    llm_rpm_limit: int = 1000

    # LLM Traffic Controller — set to true in .env to enable (Release 5)
    enable_llm_traffic_controller: bool = False

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
            raise RuntimeError("DATABASE_URL is not set in production.")
        if self.database_url.startswith("${{"):
            raise RuntimeError(
                "DATABASE_URL contains an unexpanded GitHub Actions secret — check the deploy workflow heredoc."
            )
        if self.jwt_secret_key in ("change-me", ""):
            raise RuntimeError("JWT_SECRET_KEY is not set in production.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
