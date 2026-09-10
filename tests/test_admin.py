from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.integration_security import create_integration_token
from app.db.session import SessionLocal
from app.models.entities import (
    Brand,
    CatalogStatus,
    EventLog,
    IntegrationClient,
    IntegrationClientType,
    OperatorApplication,
    OperatorProfile,
    Organization,
    OrganizationType,
    Product,
    SupplierBrandCooperation,
    SupplierApplication,
    SupplierOffer,
    SupplierSku,
    SupplierStatus,
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


def test_admin_application_list_returns_more_than_two_hundred_rows(client: TestClient) -> None:
    marker = uuid4().hex[:8]
    applications = [
        SupplierApplication(
            application_no=f"BULK-{marker}-{index:03d}",
            company_name=f"批量申请 {index}",
            company_type="工贸一体",
            province="广东省",
            city="东莞市",
            contact_name="审核测试人",
            phone="13800138001",
            email=f"bulk-{marker}-{index}@example.com",
            categories=["工业自动化"],
            cooperation_modes=["B2B外贸"],
        )
        for index in range(205)
    ]
    with SessionLocal() as db:
        db.add_all(applications)
        db.commit()
        created_ids = [item.id for item in applications]

    try:
        login_admin(client)
        response = client.get("/api/admin/applications")

        assert response.status_code == 200
        returned_ids = {item["id"] for item in response.json()}
        assert set(created_ids) <= returned_ids
    finally:
        with SessionLocal() as db:
            db.execute(delete(SupplierApplication).where(SupplierApplication.id.in_(created_ids)))
            db.commit()


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


def test_supplier_can_filter_offer_by_exact_160_character_assigned_brand(
    client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    long_brand_name = f"{'长' * 151}-{suffix}"
    assert len(long_brand_name) == 160
    brand_id: str | None = None
    product_id: str | None = None
    offer_id: str | None = None
    cooperation_id: str | None = None
    try:
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
            cooperation = SupplierBrandCooperation(
                supplier_id=supplier_id,
                brand_id=brand_id,
                commercial_mode="SELF_PURCHASE",
                status=CatalogStatus.ACTIVE.value,
            )
            db.add(cooperation)
            db.commit()
            cooperation_id = cooperation.id

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
        product_id = product.json()["id"]
        assert product.json()["brand_id"] == brand_id
        assert product.json()["brand"] == long_brand_name

        offer = client.post(
            "/api/offers",
            json={
                "product_id": product_id,
                "supplier_sku_code": f"LONG-BRAND-{suffix}",
                "price": "88.0000",
                "status": "ACTIVE",
            },
        )
        assert offer.status_code == 201
        offer_id = offer.json()["id"]

        brands = client.get("/api/offers/brands")
        assert brands.status_code == 200
        assert long_brand_name in brands.json()

        filtered = client.get("/api/offers", params={"brand": long_brand_name})
        assert filtered.status_code == 200
        assert [item["id"] for item in filtered.json()] == [offer_id]
        assert filtered.json()[0]["brand"] == long_brand_name
    finally:
        entity_ids = [
            entity_id
            for entity_id in (brand_id, cooperation_id, product_id, offer_id)
            if entity_id is not None
        ]
        with SessionLocal() as db:
            if offer_id is not None:
                db.execute(delete(SupplierOffer).where(SupplierOffer.id == offer_id))
            if product_id is not None:
                db.execute(
                    delete(SupplierSku).where(SupplierSku.product_id == product_id)
                )
                db.execute(delete(Product).where(Product.id == product_id))
            if brand_id is not None:
                db.execute(
                    delete(SupplierBrandCooperation).where(
                        SupplierBrandCooperation.brand_id == brand_id
                    )
                )
            if brand_id is not None:
                db.execute(delete(Brand).where(Brand.id == brand_id))
            if entity_ids:
                db.execute(delete(EventLog).where(EventLog.entity_id.in_(entity_ids)))
            db.commit()


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


def test_supplier_replaces_brand_cooperation_without_changing_supplier_sku(
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

    client.post("/api/auth/logout")
    login_supplier(client)

    first_same_mode = client.put(
        f"/api/supplier-catalog/brand-cooperations/{brand_id}",
        json={"commercial_mode": "SELF_PURCHASE"},
    )
    assert first_same_mode.status_code == 200
    assert first_same_mode.json()["brand_id"] == brand_id

    second_same_mode = client.put(
        f"/api/supplier-catalog/brand-cooperations/{brand_id}",
        json={"commercial_mode": "SELF_PURCHASE"},
    )
    assert second_same_mode.status_code == 200
    assert second_same_mode.json()["brand_id"] == brand_id

    changed = client.put(
        f"/api/supplier-catalog/brand-cooperations/{brand_id}",
        json={"commercial_mode": "JOINT_OPERATION"},
    )
    assert changed.status_code == 200
    assert changed.json()["commercial_mode"] == "JOINT_OPERATION"
    assert changed.json()["status"] == "ACTIVE"

    cooperations = client.get("/api/supplier-catalog/brand-cooperations")
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
            (history[1].id, "ACTIVE", "JOINT_OPERATION"),
        ]
        assert db.get(SupplierSku, supplier_sku_id).id == supplier_sku_id
        change_events = db.scalars(
            select(EventLog).where(
                EventLog.event_type == "SUPPLIER_BRAND_COOPERATION_CHANGED",
                EventLog.organization_id == supplier_id,
            )
        ).all()
        matching_events = [
            event for event in change_events if event.payload.get("brand_id") == brand_id
        ]
        assert len(matching_events) == 1
        assert matching_events[0].payload == {
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
    assert [response.status_code for response in supplier_requests] == [403, 403, 403, 404]


def test_admin_page_does_not_expose_brand_cooperation_controls(client: TestClient) -> None:
    page = client.get("/admin")
    assert page.status_code == 200
    assert 'data-brand-cooperation-id' not in page.text
    assert 'id="brand-cooperation-dialog"' not in page.text
    assert 'id="brand-cooperation-form"' not in page.text

    script = client.get("/assets/admin.js")
    assert script.status_code == 200
    assert "openBrandCooperation" not in script.text
    assert "saveBrandCooperation" not in script.text


def test_supplier_workbench_exposes_formal_mode_editor(
    client: TestClient,
) -> None:
    page = client.get("/app")
    assert page.status_code == 200
    assert "合作意向（非正式品牌模式）" in page.text
    assert "正式合作模式由供应商在商品报价页面配置" in page.text
    assert 'name="cooperation_modes"' in page.text
    assert 'id="brand-commercial-mode-list"' in page.text
    assert "A 模式（自营采购）" in page.text


def test_admin_cannot_rotate_but_can_revoke_supplier_owned_credential(
    client: TestClient,
) -> None:
    _, token_prefix, token_hash = create_integration_token()
    with SessionLocal() as db:
        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        assert supplier is not None
        issuer = db.scalar(select(User).where(User.email == SUPPLIER_EMAIL))
        assert issuer is not None
        credential = IntegrationClient(
            name=f"供应商监管凭证-{uuid4().hex[:8]}",
            client_type=IntegrationClientType.SUPPLIER.value,
            owner_organization_id=supplier.id,
            issuer_user_id=issuer.id,
            token_prefix=token_prefix,
            token_hash=token_hash,
            scopes=["supplier-skus:read"],
        )
        db.add(credential)
        db.commit()
        credential_id = credential.id

    try:
        login_admin(client)
        listed = client.get("/api/admin/integration-clients")
        assert listed.status_code == 200
        assert credential_id in {item["id"] for item in listed.json()}

        rotated = client.post(
            f"/api/admin/integration-clients/{credential_id}/rotate"
        )
        assert rotated.status_code in {404, 409}

        revoked = client.post(
            f"/api/admin/integration-clients/{credential_id}/revoke"
        )
        assert revoked.status_code == 200
        assert revoked.json()["is_active"] is False
        assert "token" not in revoked.json()
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(EventLog).where(
                    EventLog.entity_type == "IntegrationClient",
                    EventLog.entity_id == credential_id,
                )
            )
            db.execute(
                delete(IntegrationClient).where(IntegrationClient.id == credential_id)
            )
            db.commit()


def test_operator_admin_summary_and_filters(client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    target_application = OperatorApplication(
        application_no=f"OPR-FILTER-{suffix}",
        contact_name=f"筛选联系人-{suffix}",
        phone=f"188-{suffix}",
        email=f"filter-{suffix}@example.com",
        company_name=f"筛选运营公司-{suffix}",
        operator_type=f"代运营类型-{suffix}",
        erp_name=f"筛选ERP-{suffix}",
        status=SupplierStatus.PENDING.value,
    )
    approved_application = OperatorApplication(
        application_no=f"OPR-APPROVED-{suffix}",
        contact_name="已通过联系人",
        phone="18800000000",
        email=f"approved-filter-{suffix}@example.com",
        status=SupplierStatus.APPROVED.value,
    )
    active_operator = Organization(
        code=f"OPR-ACTIVE-{suffix}",
        name=f"活跃运营组织-{suffix}",
        organization_type=OrganizationType.OPERATOR.value,
        is_active=True,
    )
    inactive_operator = Organization(
        code=f"OPR-INACTIVE-{suffix}",
        name=f"停用运营组织-{suffix}",
        organization_type=OrganizationType.OPERATOR.value,
        is_active=False,
    )
    with SessionLocal() as db:
        db.add_all([
            target_application,
            approved_application,
            active_operator,
            inactive_operator,
        ])
        db.flush()
        db.add_all([
            OperatorProfile(
                organization_id=active_operator.id,
                company_name=f"运营主体-{suffix}",
                operator_type=f"运营类型-{suffix}",
                contact_name=f"账户联系人-{suffix}",
                contact_phone=f"199-{suffix}",
                contact_email=f"account-{suffix}@example.com",
                erp_name=f"账户ERP-{suffix}",
            ),
            OperatorProfile(
                organization_id=inactive_operator.id,
                contact_name="停用联系人",
                contact_phone="17700000000",
                contact_email=f"inactive-{suffix}@example.com",
            ),
        ])
        db.commit()
        application_id = target_application.id
        operator_id = active_operator.id
        application_ids = [target_application.id, approved_application.id]
        operator_ids = [active_operator.id, inactive_operator.id]
        expected_summary = {
            "pending_applications": db.scalar(
                select(func.count(OperatorApplication.id)).where(
                    OperatorApplication.status == SupplierStatus.PENDING.value
                )
            ),
            "approved_applications": db.scalar(
                select(func.count(OperatorApplication.id)).where(
                    OperatorApplication.status == SupplierStatus.APPROVED.value
                )
            ),
            "active_operators": db.scalar(
                select(func.count(Organization.id)).where(
                    Organization.organization_type == OrganizationType.OPERATOR.value,
                    Organization.is_active.is_(True),
                )
            ),
        }

    try:
        login_admin(client)
        summary = client.get("/api/admin/operator-summary")
        assert summary.status_code == 200
        assert summary.json() == expected_summary

        application_keywords = (
            f"筛选联系人-{suffix}",
            f"188-{suffix}",
            f"FILTER-{suffix.upper()}@EXAMPLE.COM",
            f"筛选运营公司-{suffix}",
            f"OPR-FILTER-{suffix}",
            f"代运营类型-{suffix}",
            f"筛选ERP-{suffix}",
        )
        for keyword in application_keywords:
            response = client.get(
                "/api/admin/operator-applications",
                params={"status_filter": "PENDING", "keyword": keyword},
            )
            assert response.status_code == 200
            assert response.json()["total"] == 1
            assert [item["id"] for item in response.json()["items"]] == [application_id]

        assert client.get(
            "/api/admin/operator-applications",
            params={"status_filter": "pending"},
        ).status_code == 422

        account_keywords = (
            f"活跃运营组织-{suffix}",
            f"OPR-ACTIVE-{suffix}",
            f"账户联系人-{suffix}",
            f"199-{suffix}",
            f"ACCOUNT-{suffix.upper()}@EXAMPLE.COM",
            f"运营类型-{suffix}",
            f"账户ERP-{suffix}",
        )
        for keyword in account_keywords:
            response = client.get("/api/admin/operators", params={"keyword": keyword})
            assert response.status_code == 200
            assert response.json()["total"] == 1
            assert [item["organization_id"] for item in response.json()["items"]] == [
                operator_id
            ]
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(OperatorApplication).where(OperatorApplication.id.in_(application_ids))
            )
            db.execute(
                delete(OperatorProfile).where(OperatorProfile.organization_id.in_(operator_ids))
            )
            db.execute(delete(Organization).where(Organization.id.in_(operator_ids)))
            db.commit()


@pytest.mark.parametrize(
    ("target_keyword", "wildcard_decoy"),
    [
        ("literal%term", "literalXterm"),
        ("literal_term", "literalXterm"),
        (r"literal\term", "literalterm"),
    ],
    ids=["percent", "underscore", "escape"],
)
def test_operator_application_keyword_treats_like_metacharacters_literally(
    client: TestClient,
    target_keyword: str,
    wildcard_decoy: str,
) -> None:
    suffix = uuid4().hex[:8]
    target = OperatorApplication(
        application_no=f"OPR-LITERAL-TARGET-{suffix}",
        contact_name=f"{target_keyword}-{suffix}",
        phone="18800000001",
        email=f"literal-target-{suffix}@example.com",
    )
    decoy = OperatorApplication(
        application_no=f"OPR-LITERAL-DECOY-{suffix}",
        contact_name=f"{wildcard_decoy}-{suffix}",
        phone="18800000002",
        email=f"literal-decoy-{suffix}@example.com",
    )
    with SessionLocal() as db:
        db.add_all([target, decoy])
        db.commit()
        target_id = target.id
        application_ids = [target.id, decoy.id]

    try:
        login_admin(client)
        response = client.get(
            "/api/admin/operator-applications",
            params={"keyword": f"{target_keyword}-{suffix}"},
        )

        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == [target_id]
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(OperatorApplication).where(
                    OperatorApplication.id.in_(application_ids)
                )
            )
            db.commit()


@pytest.mark.parametrize(
    ("target_keyword", "wildcard_decoy"),
    [
        ("literal%operator", "literalXoperator"),
        ("literal_operator", "literalXoperator"),
        (r"literal\operator", "literaloperator"),
    ],
    ids=["percent", "underscore", "escape"],
)
def test_operator_account_keyword_treats_like_metacharacters_literally(
    client: TestClient,
    target_keyword: str,
    wildcard_decoy: str,
) -> None:
    suffix = uuid4().hex[:8]
    target = Organization(
        code=f"OPR-LIKE-TARGET-{suffix}",
        name=f"{target_keyword}-{suffix}",
        organization_type=OrganizationType.OPERATOR.value,
    )
    decoy = Organization(
        code=f"OPR-LIKE-DECOY-{suffix}",
        name=f"{wildcard_decoy}-{suffix}",
        organization_type=OrganizationType.OPERATOR.value,
    )
    with SessionLocal() as db:
        db.add_all([target, decoy])
        db.flush()
        db.add_all(
            [
                OperatorProfile(
                    organization_id=target.id,
                    contact_name="目标联系人",
                    contact_phone="18800000001",
                    contact_email=f"operator-target-{suffix}@example.com",
                ),
                OperatorProfile(
                    organization_id=decoy.id,
                    contact_name="对照联系人",
                    contact_phone="18800000002",
                    contact_email=f"operator-decoy-{suffix}@example.com",
                ),
            ]
        )
        db.commit()
        target_id = target.id
        operator_ids = [target.id, decoy.id]

    try:
        login_admin(client)
        response = client.get(
            "/api/admin/operators",
            params={"keyword": f"{target_keyword}-{suffix}"},
        )

        assert response.status_code == 200
        assert [item["organization_id"] for item in response.json()["items"]] == [
            target_id
        ]
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(OperatorProfile).where(
                    OperatorProfile.organization_id.in_(operator_ids)
                )
            )
            db.execute(delete(Organization).where(Organization.id.in_(operator_ids)))
            db.commit()


@pytest.fixture()
def operator_status_applications() -> Iterator[dict[str, Any]]:
    suffix = uuid4().hex[:8]
    keyword = f"状态兼容-{suffix}"
    pending_application = OperatorApplication(
        application_no=f"OPR-STATUS-PENDING-{suffix}",
        contact_name=keyword,
        phone="18800000001",
        email=f"status-pending-{suffix}@example.com",
        status=SupplierStatus.PENDING.value,
    )
    rejected_application = OperatorApplication(
        application_no=f"OPR-STATUS-REJECTED-{suffix}",
        contact_name=keyword,
        phone="18800000002",
        email=f"status-rejected-{suffix}@example.com",
        status=SupplierStatus.REJECTED.value,
    )
    with SessionLocal() as db:
        db.add_all([pending_application, rejected_application])
        db.commit()
        pending_id = pending_application.id
        application_ids = [pending_application.id, rejected_application.id]

    try:
        yield {
            "keyword": keyword,
            "pending_id": pending_id,
            "application_ids": application_ids,
        }
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(OperatorApplication).where(
                    OperatorApplication.id.in_(application_ids)
                )
            )
            db.commit()


@pytest.mark.parametrize("legacy_status", ["pending", "PeNdInG"])
def test_operator_application_legacy_status_is_case_insensitive(
    client: TestClient,
    operator_status_applications: dict[str, Any],
    legacy_status: str,
) -> None:
    login_admin(client)

    response = client.get(
        "/api/admin/operator-applications",
        params={
            "keyword": operator_status_applications["keyword"],
            "status": legacy_status,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [
        operator_status_applications["pending_id"]
    ]


def test_operator_application_empty_legacy_status_means_no_filter(
    client: TestClient,
    operator_status_applications: dict[str, Any],
) -> None:
    login_admin(client)

    response = client.get(
        "/api/admin/operator-applications",
        params={
            "keyword": operator_status_applications["keyword"],
            "status": "",
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_operator_application_matching_mixed_case_legacy_and_strict_status_do_not_conflict(
    client: TestClient,
    operator_status_applications: dict[str, Any],
) -> None:
    login_admin(client)

    response = client.get(
        "/api/admin/operator-applications",
        params={
            "keyword": operator_status_applications["keyword"],
            "status": "pEnDiNg",
            "status_filter": "PENDING",
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [
        operator_status_applications["pending_id"]
    ]


def test_operator_application_invalid_legacy_status_is_rejected(
    client: TestClient,
) -> None:
    login_admin(client)

    response = client.get(
        "/api/admin/operator-applications",
        params={"status": "not-a-status"},
    )

    assert response.status_code == 422


def test_operator_application_conflicting_normalized_status_parameters_are_rejected(
    client: TestClient,
) -> None:
    login_admin(client)

    response = client.get(
        "/api/admin/operator-applications",
        params={"status": "pending", "status_filter": "REJECTED"},
    )

    assert response.status_code == 422


def test_operator_application_status_filter_remains_strict(
    client: TestClient,
) -> None:
    login_admin(client)

    response = client.get(
        "/api/admin/operator-applications",
        params={"status_filter": "pending"},
    )

    assert response.status_code == 422
