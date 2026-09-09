from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.integration_security import create_integration_token
from app.models.entities import IntegrationClient
from app.schemas.integration import IntegrationClientCredential, IntegrationClientView


TOKEN_PREFIX_RETRY_LIMIT = 5
TOKEN_PREFIX_INDEX_NAME = "ix_integration_clients_token_prefix"


def integration_client_view(client: IntegrationClient) -> IntegrationClientView:
    return IntegrationClientView.model_validate(client)


def integration_client_credential(
    client: IntegrationClient,
    token: str,
) -> IntegrationClientCredential:
    return IntegrationClientCredential(
        **integration_client_view(client).model_dump(),
        token=token,
    )


def is_token_prefix_collision(exc: IntegrityError) -> bool:
    diagnostics = getattr(exc.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None) == TOKEN_PREFIX_INDEX_NAME


def create_client_with_unique_token(
    db: Session,
    *,
    name: str,
    scopes: list[str],
    expires_at: datetime | None,
    client_type: str,
    owner_organization_id: str | None,
) -> tuple[IntegrationClient, str]:
    for _ in range(TOKEN_PREFIX_RETRY_LIMIT):
        plaintext, prefix, token_hash = create_integration_token()
        client = IntegrationClient(
            name=name,
            client_type=client_type,
            owner_organization_id=owner_organization_id,
            token_prefix=prefix,
            token_hash=token_hash,
            scopes=scopes,
            expires_at=expires_at,
        )
        try:
            with db.begin_nested():
                db.add(client)
                db.flush()
        except IntegrityError as exc:
            if not is_token_prefix_collision(exc):
                raise
            continue
        return client, plaintext
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="暂时无法签发唯一集成凭证，请稍后重试",
    )


def rotate_client_with_unique_token(
    db: Session,
    client: IntegrationClient,
) -> str:
    for _ in range(TOKEN_PREFIX_RETRY_LIMIT):
        plaintext, prefix, token_hash = create_integration_token()
        try:
            with db.begin_nested():
                client.token_prefix = prefix
                client.token_hash = token_hash
                client.last_used_at = None
                db.flush()
        except IntegrityError as exc:
            if not is_token_prefix_collision(exc):
                raise
            continue
        return plaintext
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="暂时无法轮换为唯一集成凭证，旧凭证仍然有效",
    )
