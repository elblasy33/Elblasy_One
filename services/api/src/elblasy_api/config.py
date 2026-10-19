from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELBLASY_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://elblasy:elblasy@localhost:5432/elblasy_one"
    # Base64 urlsafe 32-byte Fernet key(s), comma-separated; first encrypts, all decrypt (rotation).
    secret_keys: str = ""
    # Private-network Odoo targets (RFC1918, loopback) are refused unless explicitly allowed.
    allow_private_odoo_hosts: bool = False
    # Plain HTTP to Odoo is refused in production regardless of other settings.
    allow_insecure_odoo_http: bool = False
    jwt_secret: str = ""  # >= 32 chars; required outside tests
    session_ttl_minutes: int = 60 * 8
    cookie_secure: bool = True
    allow_bootstrap: bool = True  # lets the first owner create a tenant; disable after onboarding
    # Stock adjustments by non-managers above this absolute value change need approval.
    stock_adjust_approval_value: float = 500.0
    # Expenses above this amount, entered by anyone other than the owner/manager, need approval.
    expense_approval_value: float = 1000.0
    cors_origins: list[str] = []
    # Origins allowed to make state-changing requests with the session cookie (CSRF defence).
    # Required in production; empty in development means "do not enforce".
    allowed_origins: list[str] = []
    # Per-IP limits on state-changing requests (in-process; 0 disables). Auth endpoints use the tighter one.
    rate_limit_writes_per_min: int = 600
    rate_limit_auth_per_5min: int = 60
    log_json: bool = True

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
