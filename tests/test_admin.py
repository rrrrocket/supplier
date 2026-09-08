from __future__ import annotations

from uuid import uuid4

from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.entities import (
    Brand,
    CatalogStatus,
    EventLog,
    Organization,
    Product,
    SupplierBrandCooperation,
    SupplierSku,
    User,
)
from app.schemas.catalog import BrandCreate
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, SUPPLIER_EMAIL, SUPPLIER_PASSWORD


def login_supplier(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": SUPPLIER_EMAIL, "password": SUPPLIER_PASSWORD},
    )
    assert response.status_code == 200


def login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "PLATFORM_ADMIN"


def create_application(client: TestClient, suffix: str) -> dict:
    response = client.post(
        "/api/public/applications",
        json={
            "company_name": f"管理端测试供应商-{suffix}",
            "company_type": "工贸一体",
            "province": "广东省",
            "city": "东莞市",
            "contact_name": "审核测试人",
            "phone": "13800138001",
            "email": f"approved-{suffix}@example.com",
            "categories": ["工业自动化"],
            "cooperation_modes": ["联营代运营", "B2B外贸"],
            "supports_dropshipping": True,
            "supports_oem": True,
            "has_export_experience": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_supplier_cannot_access_admin_api(client: TestClient) -> None:
    login_supplier(client)
    response = client.get("/api/admin/applications")
    assert response.status_code == 403


def test_admin_cannot_use_supplier_business_api(client: TestClient) -> None:
    login_admin(client)
    response = client.get("/api/dashboard")
    assert response.status_code == 403


def test_admin_can_list_and_approve_application(client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    application = create_application(client, suffix)

    login_admin(client)
    applications = client.get("/api/admin/applications")
    assert applications.status_code == 200
    assert any(item["id"] == application["id"] for item in applications.json())

    approval = client.post(
        f"/api/admin/applications/{application['id']}/approve",
        json={"notes": "资料已核验，进入首批试点。"},
    )
    assert approval.status_code == 200
    result = approval.json()
    assert result["status"] == "APPROVED"
    assert result["organization_code"].startswith("SUP-")
    assert result["login_email"] == f"approved-{suffix}@example.com"
    assert len(result["temporary_password"]) >= 12

    suppliers = client.get("/api/admin/suppliers")
    assert suppliers.status_code == 200
    assert any(
        item["organization_id"] == result["organization_id"]
        and item["organization_name"] == f"管理端测试供应商-{suffix}"
        for item in suppliers.json()
    )

    client.post("/api/auth/logout")
    first_login = client.post(
        "/api/auth/login",
        json={
            "email": result["login_email"],
            "password": result["temporary_password"],
        },
    )
    assert first_login.status_code == 200
    assert first_login.json()["user"]["role"] == "SUPPLIER"

    profile = client.get("/api/profile")
    assert profile.status_code == 200
    assert profile.json()["legal_name"] == f"管理端测试供应商-{suffix}"
    assert profile.json()["supplier_type"] == "FACTORY_TRADER"


def test_admin_reject_requires_pending_application(client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    application = create_application(client, suffix)
    login_admin(client)

    rejected = client.post(
        f"/api/admin/applications/{application['id']}/reject",
        json={"notes": "需要补充真实营业执照和产品认证。"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert "营业执照" in rejected.json()["review_notes"]

    second_review = client.post(
        f"/api/admin/applications/{application['id']}/approve",
        json={"notes": "重复审核"},
    )
    assert second_review.status_code == 409


def test_admin_can_create_deduplicate_and_search_brands(client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    login_admin(client)

    created = client.post(
        "/api/admin/brands",
        json={
            "name": f"  测试 品牌 {suffix}  ",
            "code": f"ADMIN-{suffix}",
            "aliases": [f"品牌别名 {suffix}", f"  品牌别名 {suffix}  "],
        },
    )
    assert created.status_code == 201
    brand = created.json()
    assert brand["name"] == f"测试 品牌 {suffix}"
    assert brand["code"] == f"ADMIN-{suffix}"

    duplicate = client.post(
        "/api/admin/brands",
        json={"name": f"测试   品牌 {suffix}", "code": f"ADMIN-{suffix}"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == brand["id"]

    normalized_name_conflict = client.post(
        "/api/admin/brands",
        json={"name": f" 测试 品牌  {suffix} ", "code": f"OTHER-{suffix}"},
    )
    assert normalized_name_conflict.status_code == 409

    search = client.get("/api/admin/brands", params={"q": f"品牌 {suffix}"})
    assert search.status_code == 200
    assert [item["id"] for item in search.json()] == [brand["id"]]

    conflict = client.post(
        "/api/admin/brands",
        json={"name": f"另一个品牌 {suffix}", "code": f"ADMIN-{suffix}"},
    )
    assert conflict.status_code == 409

    with SessionLocal() as db:
        created_events = db.scalar(
            select(func.count(EventLog.id)).where(
                EventLog.event_type == "BRAND_CREATED",
                EventLog.entity_id == brand["id"],
            )
        )
        assert created_events == 1


def test_supplier_can_create_product_for_assigned_brand_up_to_160_characters(
    client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    long_brand_name = f"{'长' * 131}-{suffix}"
    assert 121 <= len(long_brand_name) <= 160
    login_admin(client)
    created_brand = client.post(
        "/api/admin/brands",
        json={
            "name": long_brand_name,
            "code": f"LONG-{suffix}",
        },
    )
    assert created_brand.status_code == 201
    brand_id = created_brand.json()["id"]
    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        assert supplier is not None
        supplier_id = supplier.id

    assigned = client.put(
        f"/api/admin/suppliers/{supplier_id}/brands/{brand_id}/cooperation",
        json={"commercial_mode": "SELF_PURCHASE"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "ACTIVE"

    client.post("/api/auth/logout")
    login_supplier(client)
    product = client.post(
        "/api/products",
        json={
            "name": f"长品牌商品-{suffix}",
            "brand": long_brand_name,
            "category": "工业自动化",
            "status": "ACTIVE",
        },
    )

    assert product.status_code == 201
    assert product.json()["brand_id"] == brand_id
    assert product.json()["brand"] == long_brand_name


def test_create_brand_recovers_canonical_row_after_unique_insert_race(
    client: TestClient,
    monkeypatch,
) -> None:
    del client
    from app.api.routes.admin_catalog import create_brand

    suffix = uuid4().hex[:8]
    name = f"并发品牌 {suffix}"
    code = f"RACE-{suffix}"
    canonical_id: str | None = None

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert admin is not None
        original_flush = db.flush

        def lose_insert_race(*args, **kwargs) -> None:
            nonlocal canonical_id
            monkeypatch.setattr(db, "flush", original_flush)
            with SessionLocal() as winner:
                canonical = Brand(
                    code=code,
                    name=name,
                    normalized_name=name.lower(),
                    aliases=[],
                    status=CatalogStatus.ACTIVE.value,
                )
                winner.add(canonical)
                winner.commit()
                canonical_id = canonical.id
            raise IntegrityError("INSERT INTO brands", {}, Exception("duplicate key"))

        monkeypatch.setattr(db, "flush", lose_insert_race)
        response = Response(status_code=201)
        result = create_brand(
            BrandCreate(name=name, code=code),
            response,
            db,
            admin,
        )

        assert canonical_id is not None
        assert result.id == canonical_id
        assert response.status_code == 200
        assert db.scalar(
            select(func.count(EventLog.id)).where(EventLog.entity_id == canonical_id)
        ) == 0


def test_admin_replaces_brand_cooperation_without_changing_supplier_sku(
    client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    login_admin(client)

    brand_response = client.post(
        "/api/admin/brands",
        json={"name": f"合作品牌 {suffix}", "code": f"COOP-{suffix}"},
    )
    assert brand_response.status_code == 201
    brand_id = brand_response.json()["id"]

    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        assert supplier is not None
        product = Product(
            created_by_organization_id=supplier.id,
            brand_id=brand_id,
            name=f"合作模式测试商品 {suffix}",
            category="测试类目",
        )
        cooperation = SupplierBrandCooperation(
            supplier_id=supplier.id,
            brand_id=brand_id,
            commercial_mode="SELF_PURCHASE",
            status=CatalogStatus.ACTIVE.value,
        )
        db.add_all([product, cooperation])
        db.flush()
        supplier_sku = SupplierSku(
            supplier_id=supplier.id,
            brand_id=brand_id,
            product_id=product.id,
            supplier_sku_code=f"COOP-SKU-{suffix}",
            status=CatalogStatus.ACTIVE.value,
        )
        db.add(supplier_sku)
        db.commit()
        supplier_id = supplier.id
        cooperation_id = cooperation.id
        supplier_sku_id = supplier_sku.id

    first_same_mode = client.put(
        f"/api/admin/suppliers/{supplier_id}/brands/{brand_id}/cooperation",
        json={"commercial_mode": "SELF_PURCHASE"},
    )
    assert first_same_mode.status_code == 200
    assert first_same_mode.json()["id"] == cooperation_id

    second_same_mode = client.put(
        f"/api/admin/suppliers/{supplier_id}/brands/{brand_id}/cooperation",
        json={"commercial_mode": "SELF_PURCHASE"},
    )
    assert second_same_mode.status_code == 200
    assert second_same_mode.json()["id"] == cooperation_id

    changed = client.put(
        f"/api/admin/suppliers/{supplier_id}/brands/{brand_id}/cooperation",
        json={"commercial_mode": "JOINT_OPERATION"},
    )
    assert changed.status_code == 200
    assert changed.json()["id"] != cooperation_id
    assert changed.json()["commercial_mode"] == "JOINT_OPERATION"
    assert changed.json()["status"] == "ACTIVE"

    cooperations = client.get(
        f"/api/admin/suppliers/{supplier_id}/brand-cooperations"
    )
    assert cooperations.status_code == 200
    assert [
        (item["brand_id"], item["commercial_mode"], item["status"])
        for item in cooperations.json()
        if item["brand_id"] == brand_id
    ] == [(brand_id, "JOINT_OPERATION", "ACTIVE")]

    with SessionLocal() as db:
        history = db.scalars(
            select(SupplierBrandCooperation)
            .where(
                SupplierBrandCooperation.supplier_id == supplier_id,
                SupplierBrandCooperation.brand_id == brand_id,
            )
            .order_by(SupplierBrandCooperation.created_at)
        ).all()
        assert [(item.id, item.status, item.commercial_mode) for item in history] == [
            (cooperation_id, "INACTIVE", "SELF_PURCHASE"),
            (changed.json()["id"], "ACTIVE", "JOINT_OPERATION"),
        ]
        assert db.get(SupplierSku, supplier_sku_id).id == supplier_sku_id
        change_events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "SUPPLIER_BRAND_COOPERATION_CHANGED",
                EventLog.entity_id == changed.json()["id"],
            )
        ).all()
        assert len(change_events) == 1
        assert change_events[0].organization_id == supplier_id
        assert change_events[0].payload == {
            "brand_id": brand_id,
            "previous_mode": "SELF_PURCHASE",
            "commercial_mode": "JOINT_OPERATION",
        }


def test_admin_catalog_routes_enforce_roles_and_supplier_identity(
    client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    login_admin(client)
    brand_response = client.post(
        "/api/admin/brands",
        json={"name": f"权限品牌 {suffix}", "code": f"AUTH-{suffix}"},
    )
    assert brand_response.status_code == 201
    brand = brand_response.json()
    with SessionLocal() as db:
        platform = db.scalar(
            select(Organization).where(Organization.code == "TEST-PLATFORM")
        )
        assert platform is not None
        platform_id = platform.id

    unknown_id = str(uuid4())
    for organization_id in (unknown_id, platform_id):
        listed = client.get(
            f"/api/admin/suppliers/{organization_id}/brand-cooperations"
        )
        assert listed.status_code == 404
        updated = client.put(
            f"/api/admin/suppliers/{organization_id}/brands/{brand['id']}/cooperation",
            json={"commercial_mode": "B2B"},
        )
        assert updated.status_code == 404

    client.post("/api/auth/logout")
    login_supplier(client)
    supplier_requests = (
        client.get("/api/admin/brands"),
        client.post(
            "/api/admin/brands",
            json={"name": f"越权品牌 {suffix}", "code": f"DENY-{suffix}"},
        ),
        client.get(
            f"/api/admin/suppliers/{unknown_id}/brand-cooperations"
        ),
        client.put(
            f"/api/admin/suppliers/{unknown_id}/brands/{brand['id']}/cooperation",
            json={"commercial_mode": "B2B"},
        ),
    )
    assert [response.status_code for response in supplier_requests] == [403, 403, 403, 403]


def test_admin_page_exposes_brand_cooperation_controls(client: TestClient) -> None:
    page = client.get("/admin")
    assert page.status_code == 200
    assert 'id="brand-cooperation-dialog"' in page.text
    assert 'id="brand-cooperation-form"' in page.text
    assert 'id="brand-cooperation-brand"' in page.text
    assert 'id="brand-cooperation-mode"' in page.text
    assert "模式 A · 自营采购" in page.text
    assert "模式 B · 联营" in page.text
    assert "模式 C · ToB 合作" in page.text

    script = client.get("/assets/admin.js")
    assert script.status_code == 200
    assert "/api/admin/brands" in script.text
    assert "/brand-cooperations" in script.text
    assert "/cooperation" in script.text


def test_supplier_profile_labels_cooperation_intent_without_formal_mode_editor(
    client: TestClient,
) -> None:
    page = client.get("/app")
    assert page.status_code == 200
    assert "合作意向（非平台确认模式）" in page.text
    assert 'name="cooperation_modes"' in page.text
    assert 'name="commercial_mode"' not in page.text
    assert 'id="brand-cooperation-mode"' not in page.text
    assert "模式 A · 自营采购" not in page.text
