import os
from functools import lru_cache
from dotenv import load_dotenv
from pathlib import Path

# Load .env from the api/ directory regardless of cwd
load_dotenv(Path(__file__).parents[2] / ".env")


class VaultError(Exception):
    pass


class VaultClient:
    """
    Phase 0: reads secrets from environment variables / .env file.
    Interface is stable — swap in AWS Secrets Manager or HashiCorp Vault
    in Phase 2 without changing any call sites.
    """

    def get(self, key: str) -> str:
        value = os.environ.get(key, "").strip()
        if not value:
            raise VaultError(f"Secret '{key}' not found. Set it in .env")
        return value

    def get_optional(self, key: str, default: str = "") -> str:
        return os.environ.get(key, default).strip()

    def get_portal_credentials(self, portal: str) -> tuple[str, str]:
        """Returns (email, password) for a given job portal."""
        email_key = f"{portal.upper()}_EMAIL"
        password_key = f"{portal.upper()}_PASSWORD"
        email = self.get_optional(email_key)
        password = self.get_optional(password_key)
        if not email or not password:
            raise VaultError(
                f"Portal credentials for '{portal}' not configured. "
                f"Set {email_key} and {password_key} in .env"
            )
        return email, password


@lru_cache
def get_vault() -> VaultClient:
    return VaultClient()
