from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import EmailStr, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


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
    database_url: str
    session_secret: str = Field(
        default="dev-only-change-before-deploying-supplier-matrix-one-tech",
        min_length=32,
    )
    session_cookie_name: str = "matrix_supplier_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 7
    admin_email: EmailStr | None = None
    admin_password: str | None = Field(default=None, min_length=12)
    admin_name: str = "平台管理员"
    allowed_hosts: str = "localhost,127.0.0.1,supplier.matrix-one.tech"
    integration_rate_limit_requests: int = Field(default=600, gt=0)
    integration_rate_limit_window_seconds: int = Field(default=60, gt=0)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: str) -> str:
        try:
            driver_name = make_url(value).drivername
        except ValueError as error:
            raise ValueError("DATABASE_URL 必须是有效的 PostgreSQL URL") from error
        if driver_name != "postgresql+psycopg":
            raise ValueError("DATABASE_URL 必须使用 PostgreSQL 和 psycopg 3 驱动")
        return value

    @property
    def allowed_host_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
