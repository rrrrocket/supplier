from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.core.config import get_settings
from app.core.integration_rate_limit import FixedWindowRateLimiter
from app.core.integration_security import verify_integration_token
from app.db.session import SessionLocal
from app.models.entities import IntegrationClient
from app.schemas.integration import IntegrationScope


settings = get_settings()
integration_rate_limiter = FixedWindowRateLimiter(
    max_requests=settings.integration_rate_limit_requests,
    window_seconds=settings.integration_rate_limit_window_seconds,
)
integration_bearer = HTTPBearer(auto_error=False, scheme_name="IntegrationBearer")


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


def authenticate_integration_client(
    authorization: str,
) -> AuthenticatedIntegrationClient:
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

    return principal


def get_integration_principal(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(integration_bearer),
    ],
) -> AuthenticatedIntegrationClient:
    principal = getattr(request.state, "integration_principal", None)
    if not isinstance(principal, AuthenticatedIntegrationClient):
        authorization = (
            f"{credentials.scheme} {credentials.credentials}"
            if credentials is not None
            else ""
        )
        principal = authenticate_integration_client(authorization)
        request.state.integration_principal = principal

    enforce_integration_rate_limit(request, principal)
    return principal


def enforce_integration_rate_limit(
    request: Request,
    principal: AuthenticatedIntegrationClient,
) -> None:
    if getattr(request.state, "integration_rate_limit_checked", False):
        return

    retry_after = integration_rate_limiter.consume(principal.id)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="集成客户端请求频率超限",
            headers={"Retry-After": str(retry_after)},
        )
    request.state.integration_rate_limit_checked = True


IntegrationPrincipal = Annotated[
    AuthenticatedIntegrationClient,
    Depends(get_integration_principal),
]


def require_integration_scope(
    scope: IntegrationScope,
) -> Callable[[IntegrationPrincipal], AuthenticatedIntegrationClient]:
    def dependency(
        principal: IntegrationPrincipal,
    ) -> AuthenticatedIntegrationClient:
        if scope.value not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="集成凭证缺少所需权限范围",
            )
        return principal

    return dependency


SupplierReader = Annotated[
    AuthenticatedIntegrationClient,
    Depends(require_integration_scope(IntegrationScope.SUPPLIERS_READ)),
]
BrandReader = Annotated[
    AuthenticatedIntegrationClient,
    Depends(require_integration_scope(IntegrationScope.SUPPLIER_BRANDS_READ)),
]
SkuReader = Annotated[
    AuthenticatedIntegrationClient,
    Depends(require_integration_scope(IntegrationScope.SUPPLIER_SKUS_READ)),
]
CostReader = Annotated[
    AuthenticatedIntegrationClient,
    Depends(require_integration_scope(IntegrationScope.SUPPLIER_COSTS_READ)),
]
