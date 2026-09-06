from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
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


router = APIRouter(prefix="/imports", tags=["数据导入"])

HEADER_ALIASES = {
    "product_name": ["product_name", "商品名称", "产品名称", "name"],
    "brand": ["brand", "品牌"],
    "model": ["model", "型号"],
    "category": ["category", "类目", "分类"],
    "supplier_sku": ["supplier_sku", "供应商sku", "sku", "货号"],
    "price": ["price", "采购价", "供货价", "价格"],
    "currency": ["currency", "币种"],
    "moq": ["moq", "起订量", "最小起订量"],
    "stock_qty": ["stock_qty", "库存", "库存数量"],
    "lead_time_days": ["lead_time_days", "交期", "交期天数"],
    "fulfillment_mode": ["fulfillment_mode", "履约模式", "合作模式"],
    "status": ["status", "状态"],
}


def _decode_csv(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文件编码无法识别，请使用 UTF-8 或 GB18030 编码")


def _normalize_row(row: dict[str, str | None]) -> dict[str, str]:
    lowered = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()}
    normalized: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lowered:
                normalized[canonical] = lowered[alias.lower()]
                break
        normalized.setdefault(canonical, "")
    return normalized


def _to_int(value: str, default: int, field_name: str) -> int:
    if not value:
        return default
    try:
        result = int(float(value))
    except ValueError as exc:
        raise ValueError(f"{field_name}必须是整数") from exc
    if result < 0:
        raise ValueError(f"{field_name}不能小于0")
    return result


def _to_decimal(value: str) -> Decimal:
    try:
        result = Decimal(value.replace(",", ""))
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("价格格式不正确") from exc
    if result <= 0:
        raise ValueError("价格必须大于0")
    return result


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


@router.get("")
def list_imports(db: DbSession, user: SupplierUser) -> list[dict[str, Any]]:
    jobs = db.scalars(
        select(ImportJob)
        .where(ImportJob.organization_id == user.organization_id)
        .order_by(ImportJob.created_at.desc())
        .limit(30)
    ).all()
    return [_job_view(job) for job in jobs]


@router.post("/product-offers", status_code=status.HTTP_201_CREATED)
async def import_product_offers(
    db: DbSession,
    user: SupplierUser,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 CSV 文件")

    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件不能超过 5MB")

    job = ImportJob(
        organization_id=user.organization_id,
        file_name=file.filename,
        status=ImportStatus.PROCESSING.value,
    )
    db.add(job)
    db.flush()

    try:
        text = _decode_csv(raw)
        reader = csv.DictReader(StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV 缺少表头")
        rows = list(reader)
    except ValueError as exc:
        job.status = ImportStatus.FAILED.value
        job.errors = [{"row": 0, "message": str(exc)}]
        job.error_rows = 1
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    errors: list[dict[str, Any]] = []
    success = 0
    for index, raw_row in enumerate(rows, start=2):
        try:
            row = _normalize_row(raw_row)
            if not row["product_name"]:
                raise ValueError("商品名称不能为空")
            if not row["category"]:
                raise ValueError("类目不能为空")
            if not row["supplier_sku"]:
                raise ValueError("供应商SKU不能为空")
            if not row["price"]:
                raise ValueError("价格不能为空")

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
                    fulfillment_mode=(row["fulfillment_mode"] or "PURCHASE").upper(),
                    status=(row["status"] or OfferStatus.ACTIVE.value).upper(),
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
                offer.fulfillment_mode = (row["fulfillment_mode"] or "PURCHASE").upper()
                offer.status = (row["status"] or OfferStatus.ACTIVE.value).upper()

            db.add(
                InventorySnapshot(
                    offer_id=offer.id,
                    quantity=stock_qty,
                    source="CSV_IMPORT",
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
            "total_rows": job.total_rows,
            "success_rows": job.success_rows,
            "error_rows": job.error_rows,
        },
    )
    db.commit()
    db.refresh(job)
    return _job_view(job)
