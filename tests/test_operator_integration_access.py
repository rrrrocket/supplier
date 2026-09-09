from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import SUPPLIER_EMAIL, SUPPLIER_PASSWORD
from tests.test_operator_marketplace_api import approved_operator, login, supplier_id_with_contacts


SCOPES = [
    "suppliers:read",
    "supplier-brands:read",
    "supplier-skus:read",
    "supplier-costs:read",
]


def test_operator_credential_only_reads_business_data_after_binding(client: TestClient) -> None:
    supplier_id = supplier_id_with_contacts()
    email, password, operator_id = approved_operator(client)
    login(client, email, password)
    created_client = client.post(
        "/api/operator/integration-clients",
        json={"name": "运营 ERP", "scopes": SCOPES},
    )
    assert created_client.status_code == 201
    credential = created_client.json()
    assert credential["client_type"] == "OPERATOR"
    assert credential["owner_organization_id"] == operator_id
    token = credential["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get(
        f"/api/integrations/v1/suppliers/{supplier_id}/brands", headers=headers
    ).status_code == 404

    cooperation = client.post(
        "/api/operator/cooperations", json={"supplier_id": supplier_id}
    )
    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)
    assert client.post(
        f"/api/supplier-operator/cooperations/{cooperation.json()['id']}/accept", json={}
    ).status_code == 200

    response = client.get(
        f"/api/integrations/v1/suppliers/{supplier_id}/brands", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["items"]

    assert client.post(
        f"/api/supplier-operator/cooperations/{cooperation.json()['id']}/terminate"
    ).status_code == 200
    assert client.get(
        f"/api/integrations/v1/suppliers/{supplier_id}/brands", headers=headers
    ).status_code == 404
