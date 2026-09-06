from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_requires_login(client: TestClient) -> None:
    client.post("/api/auth/logout")
    response = client.get("/api/dashboard")
    assert response.status_code == 401


def test_login_and_dashboard(client: TestClient) -> None:
    bad = client.post(
        "/api/auth/login",
        json={"email": "supplier@matrix-one.tech", "password": "wrong-password"},
    )
    assert bad.status_code == 401

    ok = client.post(
        "/api/auth/login",
        json={"email": "supplier@matrix-one.tech", "password": "MatrixOne123!"},
    )
    assert ok.status_code == 200
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert len(dashboard.json()["metrics"]) == 4


def test_supplier_application(client: TestClient) -> None:
    unique = uuid4().hex[:8]
    response = client.post(
        "/api/public/applications",
        json={
            "company_name": f"测试供应商-{unique}",
            "company_type": "生产工厂",
            "province": "浙江省",
            "city": "宁波市",
            "contact_name": "测试联系人",
            "phone": "13800138000",
            "email": f"supplier-{unique}@example.com",
            "categories": ["工业自动化"],
            "cooperation_modes": ["B2B外贸"],
            "supports_dropshipping": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["application_no"].startswith("SUP-")
    assert data["status"] == "PENDING"


def test_create_product_and_offer(authenticated_client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    product_response = authenticated_client.post(
        "/api/products",
        json={
            "name": f"测试接近传感器-{suffix}",
            "brand": "TEST",
            "model": suffix,
            "category": "工业自动化/接近传感器",
            "attributes": {"输出": "PNP NO"},
            "status": "ACTIVE",
        },
    )
    assert product_response.status_code == 201
    product_id = product_response.json()["id"]

    offer_response = authenticated_client.post(
        "/api/offers",
        json={
            "product_id": product_id,
            "supplier_sku": f"SKU-{suffix}",
            "price": 45.8,
            "currency": "CNY",
            "moq": 10,
            "stock_qty": 120,
            "lead_time_days": 3,
            "fulfillment_mode": "PURCHASE",
            "status": "ACTIVE",
        },
    )
    assert offer_response.status_code == 201
    assert offer_response.json()["stock_qty"] == 120


def test_csv_import_supports_partial_success(authenticated_client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    csv_text = (
        "商品名称,品牌,型号,类目,供应商SKU,采购价,币种,起订量,库存,交期天数,履约模式,状态\n"
        f"有效商品,TEST,{suffix},工业自动化/传感器,IMPORT-{suffix},28.5,CNY,5,60,2,PURCHASE,ACTIVE\n"
        f"错误商品,TEST,BAD-{suffix},工业自动化/传感器,IMPORT-BAD-{suffix},错误价格,CNY,5,60,2,PURCHASE,ACTIVE\n"
    )
    response = authenticated_client.post(
        "/api/imports/product-offers",
        files={"file": ("offers.csv", BytesIO(csv_text.encode("utf-8-sig")), "text/csv")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "PARTIAL"
    assert data["success_rows"] == 1
    assert data["error_rows"] == 1
