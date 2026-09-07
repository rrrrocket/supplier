from __future__ import annotations

import json
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from tests.conftest import SUPPLIER_EMAIL, SUPPLIER_PASSWORD


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def two_sheet_workbook_content() -> bytes:
    workbook = Workbook()
    sheet1 = workbook.active
    sheet1.title = "Sheet1"
    sheet1.append([None, None, "货号"])
    sheet1.append([None, None, "SKU-001"])
    sheet2 = workbook.create_sheet("Sheet2")
    sheet2.append(["名称"])
    sheet2.append(["商品二"])
    content = BytesIO()
    workbook.save(content)
    return content.getvalue()


def multi_sheet_offer_workbook_content(second_sku: str = "DUP-001") -> bytes:
    workbook = Workbook()
    sheet1 = workbook.active
    sheet1.title = "Sheet1"
    sheet1.append(["货号", "名称", "成本"])
    sheet1.append(["DUP-001", "商品甲", 10])
    sheet2 = workbook.create_sheet("Sheet2")
    sheet2.append(["供应商成本表"])
    sheet2.append(["产品编码", "产品名称", "出厂价"])
    sheet2.append([second_sku, "商品乙", 12])
    content = BytesIO()
    workbook.save(content)
    return content.getvalue()


def multi_sheet_configs() -> list[dict[str, object]]:
    defaults = {"category": "测试类目", "currency": "CNY"}
    mapping = {"supplier_sku": "A", "product_name": "B", "price": "C"}
    return [
        {
            "sheet_name": "Sheet1",
            "header_row": 1,
            "mapping": mapping,
            "defaults": defaults,
        },
        {
            "sheet_name": "Sheet2",
            "header_row": 2,
            "mapping": mapping,
            "defaults": defaults,
        },
    ]


def submitted_offer_row(
    *,
    sku: str,
    name: str,
    source_sheet: object,
    source_row: object,
    included: object = True,
    price: str = "10",
) -> dict[str, object]:
    return {
        "source_sheet": source_sheet,
        "source_row": source_row,
        "included": included,
        "values": {
            "product_name": name,
            "brand": "TEST",
            "model": sku,
            "category": "测试类目",
            "supplier_sku": sku,
            "price": price,
            "currency": "CNY",
            "moq": "1",
            "stock_qty": "5",
            "lead_time_days": "3",
            "fulfillment_mode": "PURCHASE",
            "status": "ACTIVE",
        },
    }


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_excel_inspection_returns_all_sheets_and_active_sheet(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/imports/product-offers/workbook/inspect",
        files={
            "file": (
                "supplier.xlsx",
                BytesIO(two_sheet_workbook_content()),
                XLSX_MIME,
            )
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["active_sheet"] == "Sheet1"
    assert [sheet["name"] for sheet in data["sheets"]] == ["Sheet1", "Sheet2"]
    assert data["sheets"][0]["columns"][2]["key"] == "C"


def test_excel_inspection_rejects_csv(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/imports/product-offers/workbook/inspect",
        files={"file": ("supplier.csv", BytesIO(b"sku,name\n1,item\n"), "text/csv")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "工作簿扫描仅支持 XLSX 和 XLS 格式"


def test_multi_sheet_preview_reports_duplicate_sku_conflict(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/imports/product-offers/preview",
        data={"sheet_configs_json": json.dumps(multi_sheet_configs(), ensure_ascii=False)},
        files={
            "file": (
                "supplier.xlsx",
                BytesIO(multi_sheet_offer_workbook_content()),
                XLSX_MIME,
            )
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_rows"] == 2
    assert data["conflict_count"] == 1
    assert data["can_import"] is False
    assert {
        (row["source_sheet"], row["source_row"])
        for row in data["preview_rows"]
    } == {("Sheet1", 2), ("Sheet2", 3)}
    assert {row["conflict_group"] for row in data["preview_rows"]} == {"DUP-001"}
    assert all(row["included"] is True for row in data["preview_rows"])


def test_multi_sheet_preview_allows_distinct_skus(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/imports/product-offers/preview",
        data={"sheet_configs_json": json.dumps(multi_sheet_configs(), ensure_ascii=False)},
        files={
            "file": (
                "supplier.xlsx",
                BytesIO(multi_sheet_offer_workbook_content("UNIQUE-002")),
                XLSX_MIME,
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["can_import"] is True
    assert response.json()["conflict_count"] == 0


@pytest.mark.parametrize(
    ("sheet_configs_json", "detail"),
    [
        ("{", "工作表配置格式不正确"),
        ("{}", "工作表配置必须是数组"),
        ("[]", "请至少选择一个工作表"),
        (
            json.dumps([multi_sheet_configs()[0], multi_sheet_configs()[0]]),
            "工作表不能重复选择：Sheet1",
        ),
        (
            json.dumps(
                [
                    {
                        **multi_sheet_configs()[0],
                        "sheet_name": "Missing",
                    }
                ]
            ),
            "工作表不存在：Missing",
        ),
        (
            json.dumps([{**multi_sheet_configs()[0], "header_row": 4}]),
            "工作表 Sheet1 不存在第 4 行表头",
        ),
        (
            json.dumps(
                [
                    {
                        **multi_sheet_configs()[0],
                        "mapping": {"product_name": "A1"},
                    }
                ]
            ),
            "工作表 Sheet1 的字段映射引用了无效列：A1",
        ),
    ],
)
def test_multi_sheet_preview_rejects_invalid_configuration(
    authenticated_client: TestClient,
    sheet_configs_json: str,
    detail: str,
) -> None:
    response = authenticated_client.post(
        "/api/imports/product-offers/preview",
        data={"sheet_configs_json": sheet_configs_json},
        files={
            "file": (
                "supplier.xlsx",
                BytesIO(multi_sheet_offer_workbook_content()),
                XLSX_MIME,
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == detail


def test_final_import_rejects_duplicate_included_skus_without_writing_offer(
    authenticated_client: TestClient,
) -> None:
    sku = f"DUP-FINAL-{uuid4().hex[:8]}"
    rows = [
        submitted_offer_row(
            sku=sku,
            name="商品甲",
            source_sheet="Sheet1",
            source_row=2,
        ),
        submitted_offer_row(
            sku=sku,
            name="商品乙",
            source_sheet="Sheet2",
            source_row=3,
        ),
    ]

    response = authenticated_client.post(
        "/api/imports/product-offers",
        data={"rows_json": json.dumps(rows, ensure_ascii=False)},
        files={"file": ("supplier.xlsx", BytesIO(b"source"), XLSX_MIME)},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == f"供应商 SKU 在本次导入中重复：{sku}"
    offers = authenticated_client.get("/api/offers", params={"q": sku}).json()
    assert offers == []


def test_final_import_excludes_duplicate_row_and_preserves_partial_error_source(
    authenticated_client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    sku = f"RESOLVED-{suffix}"
    rows = [
        submitted_offer_row(
            sku=sku,
            name=f"保留商品-{suffix}",
            source_sheet="Sheet1",
            source_row=2,
        ),
        submitted_offer_row(
            sku=sku,
            name=f"排除商品-{suffix}",
            source_sheet="Sheet2",
            source_row=3,
            included=False,
        ),
        submitted_offer_row(
            sku=f"BAD-{suffix}",
            name=f"错误商品-{suffix}",
            source_sheet="Sheet2",
            source_row=4,
            price="错误价格",
        ),
    ]

    response = authenticated_client.post(
        "/api/imports/product-offers",
        data={"rows_json": json.dumps(rows, ensure_ascii=False)},
        files={"file": ("supplier.xlsx", BytesIO(b"source"), XLSX_MIME)},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "PARTIAL"
    assert data["total_rows"] == 2
    assert data["success_rows"] == 1
    assert data["error_rows"] == 1
    assert data["errors"][0]["sheet"] == "Sheet2"
    assert data["errors"][0]["row"] == 4
    offers = authenticated_client.get("/api/offers", params={"q": sku}).json()
    assert len(offers) == 1
    assert offers[0]["supplier_sku"] == sku


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"source_sheet": 123}, "目标列表第 1 行来源工作表格式不正确"),
        ({"source_row": "2"}, "目标列表第 1 行来源行号格式不正确"),
        ({"included": "true"}, "目标列表第 1 行是否导入格式不正确"),
    ],
)
def test_final_import_rejects_invalid_source_metadata(
    authenticated_client: TestClient,
    overrides: dict[str, object],
    detail: str,
) -> None:
    row = submitted_offer_row(
        sku=f"META-{uuid4().hex[:8]}",
        name="元数据测试商品",
        source_sheet="Sheet1",
        source_row=2,
    )
    row.update(overrides)

    response = authenticated_client.post(
        "/api/imports/product-offers",
        data={"rows_json": json.dumps([row], ensure_ascii=False)},
        files={"file": ("supplier.xlsx", BytesIO(b"source"), XLSX_MIME)},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == detail


def test_dashboard_requires_login(client: TestClient) -> None:
    client.post("/api/auth/logout")
    response = client.get("/api/dashboard")
    assert response.status_code == 401


def test_login_and_dashboard(client: TestClient) -> None:
    bad = client.post(
        "/api/auth/login",
        json={"email": SUPPLIER_EMAIL, "password": "wrong-password"},
    )
    assert bad.status_code == 401

    ok = client.post(
        "/api/auth/login",
        json={"email": SUPPLIER_EMAIL, "password": SUPPLIER_PASSWORD},
    )
    assert ok.status_code == 200
    assert ok.json()["user"].get("organization_type") == "SUPPLIER"
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


def test_offers_can_filter_by_brand(authenticated_client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    brands = [f"品牌甲-{suffix}", f"品牌乙-{suffix}"]
    for index, brand in enumerate(brands, start=1):
        product = authenticated_client.post(
            "/api/products",
            json={
                "name": f"品牌筛选商品-{index}-{suffix}",
                "brand": brand,
                "model": f"MODEL-{index}-{suffix}",
                "category": "工业自动化",
                "status": "ACTIVE",
            },
        ).json()
        response = authenticated_client.post(
            "/api/offers",
            json={
                "product_id": product["id"],
                "supplier_sku": f"BRAND-{index}-{suffix}",
                "price": 20 + index,
                "currency": "CNY",
                "moq": 1,
                "stock_qty": 10,
                "lead_time_days": 3,
                "fulfillment_mode": "PURCHASE",
                "status": "ACTIVE",
            },
        )
        assert response.status_code == 201

    brand_response = authenticated_client.get("/api/offers/brands")
    assert brand_response.status_code == 200
    assert all(brand in brand_response.json() for brand in brands)

    filtered = authenticated_client.get("/api/offers", params={"brand": brands[0]})
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["brand"] == brands[0]


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


def test_smart_import_preview_uses_description_and_detects_columns(
    authenticated_client: TestClient,
) -> None:
    csv_text = (
        "供应商报价单,,,,\n"
        "产品,货号,含税成本,可售数,交货周期\n"
        "工业传感器,A-001,￥28.50,60,7天\n"
    )
    description = (
        "第2行是表头，产品是商品名称，货号作为供应商SKU，含税成本作为采购价，"
        "全部商品类目统一填工业自动化，币种人民币"
    )
    response = authenticated_client.post(
        "/api/imports/product-offers/preview",
        data={"description": description},
        files={"file": ("supplier.csv", BytesIO(csv_text.encode()), "text/csv")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["header_row"] == 2
    assert data["total_rows"] == 1
    assert data["valid_rows"] == 1
    row = data["preview_rows"][0]["values"]
    assert row["product_name"] == "工业传感器"
    assert row["supplier_sku"] == "A-001"
    assert row["price"] == "￥28.50"
    assert row["category"] == "工业自动化"
    assert row["stock_qty"] == "60"
    assert row["lead_time_days"] == "7天"


def test_smart_xlsx_import_accepts_supplier_original_sheet(
    authenticated_client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "成本表"
    sheet.append(["供应商内部价格表"])
    sheet.append([])
    sheet.append(["货品名称", "内部料号", "工厂成本", "可供数量"])
    sheet.append([f"露营灯-{suffix}", f"LAMP-{suffix}", 35.8, 120])
    content = BytesIO()
    workbook.save(content)
    content.seek(0)
    description = (
        "成本表第3行是表头，内部料号作为供应商SKU，工厂成本作为采购价，"
        "全部商品类目为户外用品，币种人民币，默认交期5天"
    )

    response = authenticated_client.post(
        "/api/imports/product-offers",
        data={"description": description},
        files={
            "file": (
                "supplier.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["success_rows"] == 1
    offers = authenticated_client.get(
        "/api/offers", params={"search": f"LAMP-{suffix}"}
    ).json()
    assert offers[0]["category"] == "户外用品"
    assert offers[0]["lead_time_days"] == 5


def test_smart_pdf_preview_extracts_cost_table(authenticated_client: TestClient) -> None:
    content = BytesIO()
    document = SimpleDocTemplate(content, pagesize=A4)
    table = Table(
        [
            ["Product Name", "Item Code", "Factory Cost", "Available Qty"],
            ["Camping Light", "PDF-001", "19.90", "30"],
        ],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    document.build([table])
    content.seek(0)
    description = (
        "Item Code作为供应商SKU，Factory Cost作为采购价，"
        "全部商品类目为户外用品，币种美元"
    )

    response = authenticated_client.post(
        "/api/imports/product-offers/preview",
        data={"description": description},
        files={"file": ("supplier.pdf", content, "application/pdf")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["sheet_name"] == "PDF 第 1 页"
    assert data["valid_rows"] == 1
    row = data["preview_rows"][0]["values"]
    assert row["product_name"] == "Camping Light"
    assert row["supplier_sku"] == "PDF-001"
    assert row["price"] == "19.90"
    assert row["currency"] == "USD"
    assert row["stock_qty"] == "30"


def test_smart_import_uses_edited_target_rows(authenticated_client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    target_rows = [
        {
            "product_name": f"手动新增商品-{suffix}",
            "brand": "EDITED",
            "model": suffix,
            "category": "工业自动化",
            "supplier_sku": f"EDIT-{suffix}",
            "price": "88.50",
            "currency": "CNY",
            "moq": "2",
            "stock_qty": "45",
            "lead_time_days": "6",
            "fulfillment_mode": "PURCHASE",
            "status": "ACTIVE",
        }
    ]
    response = authenticated_client.post(
        "/api/imports/product-offers",
        data={"rows_json": json.dumps(target_rows, ensure_ascii=False)},
        files={"file": ("edited.csv", BytesIO(b"source file"), "text/csv")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["total_rows"] == 1
    assert data["success_rows"] == 1
    offers = authenticated_client.get(
        "/api/offers", params={"q": f"EDIT-{suffix}"}
    ).json()
    assert len(offers) == 1
    assert offers[0]["product_name"] == f"手动新增商品-{suffix}"
