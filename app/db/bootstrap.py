from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password, verify_password
from app.models.entities import Organization, OrganizationType, User, UserRole


def sync_platform_admin(db: Session, settings: Settings) -> None:
    if settings.app_env.lower() == "testing":
        return
    if settings.admin_email is None or settings.admin_password is None:
        raise RuntimeError("必须配置 ADMIN_EMAIL 和 ADMIN_PASSWORD")
    if settings.admin_password.startswith("replace-"):
        raise RuntimeError("ADMIN_PASSWORD 仍是占位值，请先设置真实密码")

    email = str(settings.admin_email).lower()
    platform = db.scalar(select(Organization).where(Organization.code == "MATRIX-ONE"))
    if platform is None:
        platform = Organization(
            code="MATRIX-ONE",
            name="Matrix One",
            organization_type=OrganizationType.PLATFORM.value,
        )
        db.add(platform)
        db.flush()

    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        user = User(
            organization_id=platform.id,
            email=email,
            name=settings.admin_name,
            role=UserRole.PLATFORM_ADMIN.value,
            password_hash=hash_password(settings.admin_password),
        )
        db.add(user)
    else:
        if user.organization_id != platform.id:
            raise RuntimeError("ADMIN_EMAIL 已被其他组织账号占用")
        user.name = settings.admin_name
        user.role = UserRole.PLATFORM_ADMIN.value
        user.is_active = True
        if not verify_password(settings.admin_password, user.password_hash):
            user.password_hash = hash_password(settings.admin_password)

    db.commit()
