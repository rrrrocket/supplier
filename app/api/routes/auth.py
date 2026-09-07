from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.security import verify_password
from app.db.base import utcnow
from app.models.entities import User
from app.schemas.auth import LoginRequest, LoginResponse, UserView
from app.services.events import record_event


router = APIRouter(prefix="/auth", tags=["认证"])


def to_user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        organization_id=user.organization_id,
        organization_type=user.organization.organization_type,
        organization_name=user.organization.name,
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> LoginResponse:
    user = db.scalar(
        select(User).where(func.lower(User.email) == payload.email.lower())
    )
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    request.session.clear()
    request.session.update(
        {
            "user_id": user.id,
            "organization_id": user.organization_id,
        }
    )
    user.last_login_at = utcnow()
    record_event(
        db,
        event_type="USER_LOGGED_IN",
        entity_type="User",
        entity_id=user.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={"email": user.email},
    )
    db.commit()
    return LoginResponse(user=to_user_view(user))


@router.get("/me", response_model=UserView)
def me(user: CurrentUser) -> UserView:
    return to_user_view(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, user: CurrentUser, db: DbSession) -> None:
    record_event(
        db,
        event_type="USER_LOGGED_OUT",
        entity_type="User",
        entity_id=user.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
    )
    db.commit()
    request.session.clear()
