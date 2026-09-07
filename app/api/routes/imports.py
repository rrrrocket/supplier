from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import DbSession, SupplierUser
from app.models.entities import (
    ImportJob,
    ImportStatus,
    InventorySnapshot,
    OfferStatus,
    Product,
    ProductStatus,
    SupplierOffer,
)
from app.services.events import record_event
from app.services.import_mapping import (
    FIELD_DEFINITIONS,
    MAX_IMPORT_ROWS,
    infer_defaults,
    infer_mapping,
    mapping_view,
    normalize_rows,
    parse_table,
)


router = APIRouter(prefix="/imports", tags=["数据导入"])
MAX_FILE_SIZE = 10 * 1024 * 1024


def _to_int(value: str, default: int, field_name: str) -> int:
    if not value:
        return default
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        raise ValueError(f"{field_name}必须是整数")
    try:
        result = int(float(match.group()))
    except ValueError as exc:
        raise ValueError(f"{field_name}必须是整数") from exc
    if result < 0:
        raise ValueError(f"{field_name}不能小于0")
    return result


def _to_decimal(value: str) -> Decimal:
    cleaned = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
    try:
        result = Decimal(cleaned)
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("价格格式不正确") from exc
    if result <= 0:
        raise ValueError("价格必须大于0")
    return result


def _normalize_fulfillment(value: str) -> str:
    normalized = value.strip().upper()
    labels = {
        "采购": "PURCHASE",
        "自营采购": "PURCHASE",
        "一件代发": "DROPSHIP",
        "代发": "DROPSHIP",
        "寄售": "CONSIGNMENT",
        "联营": "JOINT_OPERATION",
        "联营代运营": "JOINT_OPERATION",
    }
    return labels.get(value.strip(), normalized or "PURCHASE")


def _normalize_status(value: str) -> str:
    normalized = value.strip().upper()
    labels = {
        "有效": "ACTIVE",
        "在售": "ACTIVE",
        "启用": "ACTIVE",
        "草稿": "DRAFT",
        "停售": "PAUSED",
        "暂停": "PAUSED",
        "过期": "EXPIRED",
    }
    return labels.get(value.strip(), normalized or OfferStatus.ACTIVE.value)


def _validate_row(row: dict[str, str]) -> list[str]:
    errors = []
    required = {
        "product_name": "商品名称不能为空",
        "category": "类目不能为空",
        "supplier_sku": "供应商SKU不能为空",
        "price": "价格不能为空",
    }
    for field, message in required.items():
        if not row.get(field):
            errors.append(message)
    if row.get("price"):
        try:
            _to_decimal(row["price"])
        except ValueError as exc:
            errors.append(str(exc))
    for field, default, label in (
        ("moq", 1, "起订量"),
        ("stock_qty", 0, "库存"),
        ("lead_time_days", 3, "交期"),
    ):
        try:
            _to_int(row.get(field, ""), default, label)
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def _job_view(job: ImportJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "file_name": job.file_name,
        "import_type": job.import_type,
        "status": job.status,
        "total_rows": job.total_rows,
        "success_rows": job.success_rows,
        "error_rows": job.error_rows,
        "errors": job.errors,
        "created_at": job.created_at,
    }


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择表格文件")
    extension = file.filename.lower().rsplit(".", 1)[-1]
    if extension not in {"csv", "tsv", "txt", "xlsx", "xls", "pdf"}:
        raise HTTPException(status_code=400, detail="支持 CSV、XLSX、XLS 和 PDF 格式")
    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="文件不能超过 10MB")
    return file.filename, raw


def _json_object(value: str, field_name: str) -> dict[str, str]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name}格式不正确") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=f"{field_name}必须是对象")
    return {str(key): str(item) for key, item in data.items() if item is not None}


def _effective_mapping(
    headers: list[str],
    description: str,
    mapping_json: str,
) -> dict[str, str]:
    mapping = infer_mapping(headers, description)
    overrides = _json_object(mapping_json, "字段映射")
    for field, source in overrides.items():
        if field not in FIELD_DEFINITIONS:
            continue
        if source and source not in headers:
            raise HTTPException(status_code=400, detail=f"字段映射引用了不存在的列：{source}")
        if source:
            mapping[field] = source
        else:
            mapping.pop(field, None)
    return mapping


def _effective_defaults(description: str, defaults_json: str) -> dict[str, str]:
    defaults = infer_defaults(description)
    defaults.update(_json_object(defaults_json, "默认值"))
    return defaults


def _submitted_rows(rows_json: str) -> list[dict[str, str]] | None:
    if not rows_json:
        return None
    try:
        data = json.loads(rows_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="目标列表格式不正确") from exc
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="目标列表必须是数组")
    if not data:
        raise HTTPException(status_code=400, detail="目标列表至少保留一行")
    if len(data) > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=400, detail=f"单次最多导入 {MAX_IMPORT_ROWS} 行")

    rows = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"目标列表第 {index} 行格式不正确")
        rows.append(
            {
                field: str(item.get(field, "") or "").strip()
                for field in FIELD_DEFINITIONS
            }
        )
    return rows


@router.get("")
def list_imports(db: DbSession, user: SupplierUser) -> list[dict[str, Any]]:
    jobs = db.scalars(
        select(ImportJob)
        .where(ImportJob.organization_id == user.organization_id)
        .order_by(ImportJob.created_at.desc())
        .limit(30)
    ).all()
    return [_job_view(job) for job in jobs]


@router.post("/product-offers/preview")
async def preview_product_offers(
    user: SupplierUser,
    file: UploadFile = File(...),
    description: str = Form(default="", max_length=2000),
    mapping_json: str = Form(default=""),
    defaults_json: str = Form(default=""),
) -> dict[str, Any]:
    del user
    filename, raw = await _read_upload(file)
    try:
        table = parse_table(raw, filename, description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mapping = _effective_mapping(table.headers, description, mapping_json)
    defaults = _effective_defaults(description, defaults_json)
    rows = normalize_rows(table, mapping, defaults)
    preview_rows = []
    valid_rows = 0
    for offset, row in enumerate(rows, start=1):
        errors = _validate_row(row)
        if not errors:
            valid_rows += 1
        preview_rows.append(
            {
                "row": table.header_row + offset,
                "values": row,
                "errors": errors,
            }
        )

    missing_fields = [
        definition["label"]
        for field, definition in FIELD_DEFINITIONS.items()
        if definition["required"] and not mapping.get(field) and not defaults.get(field)
    ]
    warnings = []
    if missing_fields:
        warnings.append(f"仍需指定：{'、'.join(missing_fields)}")
    invalid_rows = len(rows) - valid_rows
    if invalid_rows:
        warnings.append(f"检测到 {invalid_rows} 行数据需要修正")

    return {
        "file_name": filename,
        "sheet_name": table.sheet_name,
        "header_row": table.header_row,
        "total_rows": len(rows),
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
        "headers": table.headers,
        "mapping": mapping_view(mapping, table.headers),
        "defaults": defaults,
        "preview_rows": preview_rows,
        "warnings": warnings,
    }


@router.post("/product-offers", status_code=status.HTTP_201_CREATED)
async def import_product_offers(
    db: DbSession,
    user: SupplierUser,
    file: UploadFile = File(...),
    description: str = Form(default="", max_length=2000),
    mapping_json: str = Form(default=""),
    defaults_json: str = Form(default=""),
    rows_json: str = Form(default=""),
) -> dict[str, Any]:
    filename, raw = await _read_upload(file)
    job = ImportJob(
        organization_id=user.organization_id,
        file_name=filename,
        import_type="SMART_PRODUCT_OFFER",
        status=ImportStatus.PROCESSING.value,
    )
    db.add(job)
    db.flush()

    try:
        rows = _submitted_rows(rows_json)
        if rows is None:
            table = parse_table(raw, filename, description)
            mapping = _effective_mapping(table.headers, description, mapping_json)
            defaults = _effective_defaults(description, defaults_json)
            rows = normalize_rows(table, mapping, defaults)
            first_row_number = table.header_row + 1
        else:
            mapping = {}
            first_row_number = 1
    except (ValueError, HTTPException) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        job.status = ImportStatus.FAILED.value
        job.errors = [{"row": 0, "message": message}]
        job.error_rows = 1
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=message) from exc

    errors: list[dict[str, Any]] = []
    success = 0
    for index, row in enumerate(rows, start=first_row_number):
        try:
            row_errors = _validate_row(row)
            if row_errors:
                raise ValueError("；".join(row_errors))

            price = _to_decimal(row["price"])
            moq = max(1, _to_int(row["moq"], 1, "起订量"))
            stock_qty = _to_int(row["stock_qty"], 0, "库存")
            lead_time_days = _to_int(row["lead_time_days"], 3, "交期")
            brand = row["brand"] or None
            model = row["model"] or None
            product = db.scalar(
                select(Product).where(
                    Product.created_by_organization_id == user.organization_id,
                    Product.name == row["product_name"],
                    Product.brand == brand,
                    Product.model == model,
                )
            )
            if product is None:
                product = Product(
                    created_by_organization_id=user.organization_id,
                    name=row["product_name"],
                    brand=brand,
                    model=model,
                    category=row["category"],
                    status=ProductStatus.ACTIVE.value,
                )
                db.add(product)
                db.flush()

            offer = db.scalar(
                select(SupplierOffer).where(
                    SupplierOffer.organization_id == user.organization_id,
                    SupplierOffer.supplier_sku == row["supplier_sku"],
                )
            )
            if offer is None:
                offer = SupplierOffer(
                    organization_id=user.organization_id,
                    product_id=product.id,
                    supplier_sku=row["supplier_sku"],
                    price=price,
                    currency=(row["currency"] or "CNY").upper(),
                    moq=moq,
                    stock_qty=stock_qty,
                    lead_time_days=lead_time_days,
                    fulfillment_mode=_normalize_fulfillment(row["fulfillment_mode"]),
                    status=_normalize_status(row["status"]),
                )
                db.add(offer)
                db.flush()
            else:
                offer.product_id = product.id
                offer.price = price
                offer.currency = (row["currency"] or "CNY").upper()
                offer.moq = moq
                offer.stock_qty = stock_qty
                offer.lead_time_days = lead_time_days
                offer.fulfillment_mode = _normalize_fulfillment(row["fulfillment_mode"])
                offer.status = _normalize_status(row["status"])

            db.add(
                InventorySnapshot(
                    offer_id=offer.id,
                    quantity=stock_qty,
                    source="SMART_TABLE_IMPORT",
                )
            )
            success += 1
        except ValueError as exc:
            errors.append({"row": index, "message": str(exc)})

    job.total_rows = len(rows)
    job.success_rows = success
    job.error_rows = len(errors)
    job.errors = errors[:100]
    if success and errors:
        job.status = ImportStatus.PARTIAL.value
    elif success:
        job.status = ImportStatus.COMPLETED.value
    else:
        job.status = ImportStatus.FAILED.value

    record_event(
        db,
        event_type="PRODUCT_OFFERS_IMPORTED",
        entity_type="ImportJob",
        entity_id=job.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={
            "file_name": job.file_name,
            "import_mode": "SMART_TABLE_MAPPING",
            "total_rows": job.total_rows,
            "success_rows": job.success_rows,
            "error_rows": job.error_rows,
            "mapping": mapping,
        },
    )
    db.commit()
    db.refresh(job)
    return _job_view(job)
