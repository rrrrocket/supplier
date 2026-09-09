from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import and_, delete, or_

from app.core.integration_security import create_integration_token
from app.db.session import SessionLocal
from app.models.entities import (
    EventLog,
    IntegrationClient,
    IntegrationClientType,
    User,
    UserRole,
)
from app.schemas.integration import INTEGRATION_SCOPES
from tests.test_integrations import cost_catalog, integration_catalog


BASE_PATH = "/api/integrations/v1"
SUPPLIER_NOT_FOUND = {
    "detail": {"code": "SUPPLIER_NOT_FOUND", "message": "供应商不存在"}
}
SKU_NOT_FOUND = {
    "detail": {"code": "SKU_NOT_FOUND", "message": "Supplier SKU 不存在"}
}
MISSING_SKU_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture()
def supplier_token_factory() -> Iterator[Callable[[str], dict[str, str]]]:
    created_ids: list[str] = []
    issuer_ids: list[str] = []

    def create(owner_organization_id: str) -> dict[str, str]:
        plaintext, prefix, token_hash = create_integration_token()
        with SessionLocal() as db:
            issuer = User(
                organization_id=owner_organization_id,
                email=f"integration-access-{uuid4().hex}@example.com",
                name="集成访问签发人",
                role=UserRole.SUPPLIER.value,
                password_hash="not-used",
            )
            db.add(issuer)
            db.flush()
            credential = IntegrationClient(
                name="供应商租户隔离测试",
                client_type=IntegrationClientType.SUPPLIER.value,
                owner_organization_id=owner_organization_id,
                issuer_user_id=issuer.id,
                token_prefix=prefix,
                token_hash=token_hash,
                scopes=list(INTEGRATION_SCOPES),
            )
            db.add(credential)
            db.commit()
            created_ids.append(credential.id)
            issuer_ids.append(issuer.id)
        return {
            "id": credential.id,
            "token": plaintext,
            "owner_organization_id": owner_organization_id,
        }

    yield create

    if created_ids:
        with SessionLocal() as db:
            db.execute(
                delete(EventLog).where(
                    or_(
                        and_(
                            EventLog.actor_type == "INTEGRATION_CLIENT",
                            EventLog.actor_id.in_(created_ids),
                        ),
                        and_(
                            EventLog.entity_type == "IntegrationClient",
                            EventLog.entity_id.in_(created_ids),
                        ),
                    )
                )
            )
            db.execute(
                delete(IntegrationClient).where(IntegrationClient.id.in_(created_ids))
            )
            db.execute(delete(User).where(User.id.in_(issuer_ids)))
            db.commit()


def test_supplier_token_lists_and_reads_only_its_owner_supplier(
    client: TestClient,
    supplier_token_factory: Callable[[str], dict[str, str]],
    integration_catalog: dict[str, Any],
) -> None:
    token = supplier_token_factory(integration_catalog["first_supplier_id"])
    headers = {"Authorization": f"Bearer {token['token']}"}

    listed = client.get(f"{BASE_PATH}/suppliers", headers=headers)

    assert listed.status_code == status.HTTP_200_OK
    assert [item["supplier_id"] for item in listed.json()["items"]] == [
        token["owner_organization_id"]
    ]
    owner = client.get(
        f"{BASE_PATH}/suppliers/{integration_catalog['first_supplier_id']}",
        headers=headers,
    )
    assert owner.status_code == status.HTTP_200_OK

    foreign_supplier_id = integration_catalog["second_supplier_id"]
    detail = client.get(
        f"{BASE_PATH}/suppliers/{foreign_supplier_id}", headers=headers
    )
    assert detail.status_code == status.HTTP_404_NOT_FOUND
    assert detail.json() == SUPPLIER_NOT_FOUND
    for resource in ("brands", "skus"):
        response = client.get(
            f"{BASE_PATH}/suppliers/{foreign_supplier_id}/{resource}",
            headers=headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == SUPPLIER_NOT_FOUND


def test_supplier_token_single_cost_rejects_foreign_supplier_before_sku_lookup(
    client: TestClient,
    supplier_token_factory: Callable[[str], dict[str, str]],
    cost_catalog: dict[str, Any],
) -> None:
    token = supplier_token_factory(cost_catalog["first_supplier_id"])
    headers = {"Authorization": f"Bearer {token['token']}"}

    owned = client.get(
        f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}"
        f"/skus/{cost_catalog['active_sku_id']}/cost",
        headers=headers,
    )
    foreign = client.get(
        f"{BASE_PATH}/suppliers/{cost_catalog['second_supplier_id']}"
        f"/skus/{cost_catalog['active_sku_id']}/cost",
        headers=headers,
    )

    assert owned.status_code == status.HTTP_200_OK
    assert owned.json()["cost_price"] == "28.5000"
    assert foreign.status_code == status.HTTP_404_NOT_FOUND
    assert foreign.json() == SUPPLIER_NOT_FOUND


def test_supplier_token_single_cost_hides_foreign_sku_existence(
    client: TestClient,
    supplier_token_factory: Callable[[str], dict[str, str]],
    cost_catalog: dict[str, Any],
) -> None:
    token = supplier_token_factory(cost_catalog["first_supplier_id"])
    headers = {"Authorization": f"Bearer {token['token']}"}
    path = f"{BASE_PATH}/suppliers/{cost_catalog['first_supplier_id']}/skus"

    foreign = client.get(
        f"{path}/{cost_catalog['other_sku_id']}/cost",
        headers=headers,
    )
    missing = client.get(f"{path}/{MISSING_SKU_ID}/cost", headers=headers)

    assert (foreign.status_code, foreign.json()) == (
        status.HTTP_404_NOT_FOUND,
        SKU_NOT_FOUND,
    )
    assert (missing.status_code, missing.json()) == (
        status.HTTP_404_NOT_FOUND,
        SKU_NOT_FOUND,
    )


def test_supplier_token_batch_cost_isolates_each_foreign_supplier_item(
    client: TestClient,
    supplier_token_factory: Callable[[str], dict[str, str]],
    cost_catalog: dict[str, Any],
) -> None:
    token = supplier_token_factory(cost_catalog["first_supplier_id"])
    response = client.post(
        f"{BASE_PATH}/sku-costs/query",
        headers={"Authorization": f"Bearer {token['token']}"},
        json={
            "items": [
                {
                    "client_sku_id": "owned",
                    "supplier_id": cost_catalog["first_supplier_id"],
                    "supplier_sku_id": cost_catalog["b2b_sku_id"],
                },
                {
                    "client_sku_id": "foreign",
                    "supplier_id": cost_catalog["second_supplier_id"],
                    "supplier_sku_id": cost_catalog["other_sku_id"],
                },
            ]
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["items"] == [
        {
            "client_sku_id": "owned",
            "supplier_id": cost_catalog["first_supplier_id"],
            "supplier_sku_id": cost_catalog["b2b_sku_id"],
            "status": "ERROR",
            "error_code": "NOT_SELF_PURCHASE",
            "message": "该货号所属品牌不是自营采购模式",
        },
        {
            "client_sku_id": "foreign",
            "supplier_id": cost_catalog["second_supplier_id"],
            "supplier_sku_id": cost_catalog["other_sku_id"],
            "status": "ERROR",
            "error_code": "SUPPLIER_NOT_FOUND",
            "message": "供应商不存在",
        },
    ]


def test_supplier_token_batch_cost_hides_foreign_sku_existence(
    client: TestClient,
    supplier_token_factory: Callable[[str], dict[str, str]],
    cost_catalog: dict[str, Any],
) -> None:
    token = supplier_token_factory(cost_catalog["first_supplier_id"])
    response = client.post(
        f"{BASE_PATH}/sku-costs/query",
        headers={"Authorization": f"Bearer {token['token']}"},
        json={
            "items": [
                {
                    "client_sku_id": "foreign-existing",
                    "supplier_id": cost_catalog["first_supplier_id"],
                    "supplier_sku_id": cost_catalog["other_sku_id"],
                },
                {
                    "client_sku_id": "missing",
                    "supplier_id": cost_catalog["first_supplier_id"],
                    "supplier_sku_id": MISSING_SKU_ID,
                },
            ]
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["items"] == [
        {
            "client_sku_id": "foreign-existing",
            "supplier_id": cost_catalog["first_supplier_id"],
            "supplier_sku_id": cost_catalog["other_sku_id"],
            "status": "ERROR",
            "error_code": "SKU_NOT_FOUND",
            "message": "Supplier SKU 不存在",
        },
        {
            "client_sku_id": "missing",
            "supplier_id": cost_catalog["first_supplier_id"],
            "supplier_sku_id": MISSING_SKU_ID,
            "status": "ERROR",
            "error_code": "SKU_NOT_FOUND",
            "message": "Supplier SKU 不存在",
        },
    ]


def test_supplier_list_cursor_is_bound_to_credential_owner_scope(
    client: TestClient,
    integration_client: dict[str, Any],
    supplier_token_factory: Callable[[str], dict[str, str]],
    integration_catalog: dict[str, Any],
) -> None:
    platform_page = client.get(
        f"{BASE_PATH}/suppliers",
        headers={"Authorization": f"Bearer {integration_client['token']}"},
        params={"include_inactive": "true", "limit": 1},
    )
    assert platform_page.status_code == status.HTTP_200_OK
    platform_cursor = platform_page.json()["next_cursor"]
    assert platform_cursor is not None
    supplier_token = supplier_token_factory(integration_catalog["first_supplier_id"])

    response = client.get(
        f"{BASE_PATH}/suppliers",
        headers={"Authorization": f"Bearer {supplier_token['token']}"},
        params={
            "include_inactive": "true",
            "limit": 1,
            "cursor": platform_cursor,
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {
        "detail": {"code": "INVALID_CURSOR", "message": "分页游标无效"}
    }
