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
    cors_origins: list[str] = []

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
