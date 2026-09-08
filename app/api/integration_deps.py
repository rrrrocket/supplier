from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from app.core.integration_security import verify_integration_token
from app.db.session import SessionLocal
from app.models.entities import IntegrationClient


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="集成凭证无效或已失效",
        headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass(frozen=True, slots=True)
class AuthenticatedIntegrationClient:
    id: str
    name: str
    scopes: tuple[str, ...]


def get_integration_principal(request: Request) -> AuthenticatedIntegrationClient:
    authorization = request.headers.get("Authorization", "")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise unauthorized()

    plaintext = parts[1]
    if not plaintext.startswith("m1i_") or len(plaintext) <= 12:
        raise unauthorized()

    with SessionLocal.begin() as auth_db:
        client = auth_db.scalar(
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

        client.last_used_at = now
        principal = AuthenticatedIntegrationClient(
            id=client.id,
            name=client.name,
            scopes=tuple(client.scopes),
        )

    request.state.integration_principal = principal
    return principal


IntegrationPrincipal = Annotated[
    AuthenticatedIntegrationClient,
    Depends(get_integration_principal),
]


def require_integration_scope(
    scope: str,
) -> Callable[[IntegrationPrincipal], AuthenticatedIntegrationClient]:
    def dependency(
        principal: IntegrationPrincipal,
    ) -> AuthenticatedIntegrationClient:
        if scope not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="集成凭证缺少所需权限范围",
            )
        return principal

    return dependency


SupplierReader = Annotated[
    AuthenticatedIntegrationClient,
    Depends(require_integration_scope("suppliers:read")),
]
BrandReader = Annotated[
    AuthenticatedIntegrationClient,
    Depends(require_integration_scope("supplier-brands:read")),
]
SkuReader = Annotated[
    AuthenticatedIntegrationClient,
    Depends(require_integration_scope("supplier-skus:read")),
]
CostReader = Annotated[
    AuthenticatedIntegrationClient,
    Depends(require_integration_scope("supplier-costs:read")),
]
