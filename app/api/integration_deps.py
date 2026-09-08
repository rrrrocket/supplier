from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.integration_security import verify_integration_token
from app.db.session import SessionLocal
from app.models.entities import IntegrationClient


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="集成凭证无效或已失效",
        headers={"WWW-Authenticate": "Bearer"},
    )


def persist_last_used_at(client_id: str, used_at: datetime) -> None:
    with SessionLocal.begin() as usage_db:
        client = usage_db.get(IntegrationClient, client_id)
        if client is not None:
            client.last_used_at = used_at


def get_integration_principal(request: Request, db: DbSession) -> IntegrationClient:
    authorization = request.headers.get("Authorization", "")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise unauthorized()

    plaintext = parts[1]
    if not plaintext.startswith("m1i_") or len(plaintext) <= 12:
        raise unauthorized()

    client = db.scalar(
        select(IntegrationClient).where(
            IntegrationClient.token_prefix == plaintext[:12]
        )
    )
    expected_hash = client.token_hash if client is not None else "0" * 64
    valid_hash = verify_integration_token(plaintext, expected_hash)
    now = datetime.now(timezone.utc)
    if (
        client is None
        or not valid_hash
        or not client.is_active
        or (
            client.expires_at is not None
            and client.expires_at.astimezone(timezone.utc) <= now
        )
    ):
        raise unauthorized()

    persist_last_used_at(client.id, now)
    return client


IntegrationPrincipal = Annotated[
    IntegrationClient,
    Depends(get_integration_principal),
]


def require_integration_scope(
    scope: str,
) -> Callable[[IntegrationPrincipal], IntegrationClient]:
    def dependency(principal: IntegrationPrincipal) -> IntegrationClient:
        if scope not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="集成凭证缺少所需权限范围",
            )
        return principal

    return dependency


SupplierReader = Annotated[
    IntegrationClient,
    Depends(require_integration_scope("suppliers:read")),
]
BrandReader = Annotated[
    IntegrationClient,
    Depends(require_integration_scope("supplier-brands:read")),
]
SkuReader = Annotated[
    IntegrationClient,
    Depends(require_integration_scope("supplier-skus:read")),
]
CostReader = Annotated[
    IntegrationClient,
    Depends(require_integration_scope("supplier-costs:read")),
]
