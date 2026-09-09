from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import OrganizationType, User, UserRole


DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DbSession) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")

    user = db.get(User, user_id)
    if user is None or not user.is_active or not user.organization.is_active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_supplier_user(user: CurrentUser) -> User:
    if (
        user.role != UserRole.SUPPLIER.value
        or user.organization.organization_type != OrganizationType.SUPPLIER.value
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要供应商组织账号权限",
        )
    return user


SupplierUser = Annotated[User, Depends(get_current_supplier_user)]


def get_current_operator_user(user: CurrentUser) -> User:
    if (
        user.role != UserRole.OPERATOR.value
        or user.organization.organization_type != OrganizationType.OPERATOR.value
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要运营商组织账号权限",
        )
    return user


OperatorUser = Annotated[User, Depends(get_current_operator_user)]
