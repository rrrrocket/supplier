from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Matrix One Supplier Network"
    app_env: str = "development"
    app_url: str = "https://supplier.matrix-one.tech"
    debug: bool = True
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'supplier.db'}"
    session_secret: str = Field(
        default="dev-only-change-before-deploying-supplier-matrix-one-tech",
        min_length=32,
    )
    session_cookie_name: str = "matrix_supplier_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 7
    demo_email: str = "supplier@matrix-one.tech"
    demo_password: str = "MatrixOne123!"
    demo_admin_email: str = "admin@matrix-one.tech"
    demo_admin_password: str = "MatrixAdmin123!"
    seed_demo_data: bool = True
    allowed_hosts: str = "localhost,127.0.0.1,supplier.matrix-one.tech"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def allowed_host_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
