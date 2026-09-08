from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import AwareDatetime
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.deps import DbSession
from app.api.integration_deps import (
    AuthenticatedIntegrationClient,
    BrandReader,
    CostReader,
    SkuReader,
    SupplierReader,
    authenticate_integration_client,
    enforce_integration_rate_limit,
)
from app.db.session import SessionLocal
from app.models.entities import (
    Brand,
    CatalogStatus,
    Organization,
    OrganizationType,
    Product,
    SupplierBrandCooperation,
    SupplierProfile,
    SupplierSku,
    SupplierStatus,
)
from app.schemas.integration import (
    CurrentSkuCostView,
    SkuCostBatchError,
    SkuCostBatchRequest,
    SkuCostBatchResponse,
    SkuCostBatchSuccess,
    SkuCostErrorCode,
    SupplierBrandIntegrationPage,
    SupplierBrandIntegrationView,
    SupplierIntegrationPage,
    SupplierIntegrationView,
    SupplierSkuIntegrationPage,
    SupplierSkuIntegrationView,
)
from app.services.catalog import CurrentSkuCost, SkuCostError, resolve_current_sku_cost
from app.services.events import record_event
from app.services.integration_pagination import decode_cursor, encode_cursor


router = APIRouter(prefix="/integrations/v1", tags=["通用系统集成"])
logger = logging.getLogger(__name__)

ACTIVE = CatalogStatus.ACTIVE.value
INACTIVE = CatalogStatus.INACTIVE.value
MISSING_COST_CODES = {
    SkuCostErrorCode.SUPPLIER_NOT_FOUND,
    SkuCostErrorCode.SKU_NOT_FOUND,
}
COST_BATCH_PATH = "/api/integrations/v1/sku-costs/query"
COST_SINGLE_PATH_PATTERN = re.compile(
    r"^/api/integrations/v1/suppliers/[^/]+/skus/[^/]+/cost$"
)

INTEGRATION_AUTH_RESPONSES = {
    401: {"description": "Integration Client token is invalid or expired."},
    403: {"description": "Integration Client scope is insufficient."},
    429: {
        "description": "Integration Client request rate exceeded.",
        "headers": {
            "Retry-After": {
                "description": "Seconds until the current rate-limit window resets.",
                "schema": {"type": "integer", "minimum": 1},
            }
        },
    },
}
INTEGRATION_VALIDATION_RESPONSE = {
    400: {"description": "The integration request is invalid."}
}
INTEGRATION_NOT_FOUND_RESPONSE = {
    404: {"description": "The requested integration resource does not exist."}
}
COST_BUSINESS_RESPONSE = {
    409: {"description": "The Supplier SKU is not eligible for a current cost."}
}


class CostValidationRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        route_handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await route_handler(request)
            except RequestValidationError as exc:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": jsonable_encoder(exc.errors())},
                )

        return handle


def is_cost_query_scope(scope: Scope) -> bool:
    if scope["type"] != "http":
        return False
    method = scope.get("method")
    path = scope.get("path", "")
    return (method == "POST" and path == COST_BATCH_PATH) or (
        method == "GET" and COST_SINGLE_PATH_PATTERN.fullmatch(path) is not None
    )


class CostAuditMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if not is_cost_query_scope(scope):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        try:
            principal = await run_in_threadpool(
                authenticate_integration_client,
                request.headers.get("Authorization", ""),
            )
        except HTTPException as exc:
            if exc.status_code != status.HTTP_401_UNAUTHORIZED:
                raise
        else:
            request.state.integration_principal = principal

        try:
            stored_principal = getattr(request.state, "integration_principal", None)
            if isinstance(stored_principal, AuthenticatedIntegrationClient):
                try:
                    enforce_integration_rate_limit(request, stored_principal)
                except HTTPException as exc:
                    if exc.status_code != status.HTTP_429_TOO_MANY_REQUESTS:
                        raise
                    response = JSONResponse(
                        status_code=exc.status_code,
                        content={"detail": exc.detail},
                        headers=exc.headers,
                    )
                    await response(scope, receive, send)
                    return
            await self.app(scope, receive, send)
        finally:
            await run_in_threadpool(record_cost_query_event, request)


def utc_value(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def after_cursor(
    updated_at: ColumnElement[datetime],
    entity_id: ColumnElement[str],
    cursor: str,
) -> ColumnElement[bool]:
    cursor_updated_at, cursor_id = decode_cursor(cursor)
    return or_(
        updated_at > cursor_updated_at,
        and_(updated_at == cursor_updated_at, entity_id > cursor_id),
    )


def page_cursor(
    rows: list[Any],
    *,
    limit: int,
    updated_at_index: int,
    id_index: int,
) -> tuple[list[Any], str | None]:
    page = rows[:limit]
    if len(rows) <= limit:
        return page, None
    last = page[-1]
    return page, encode_cursor(last[updated_at_index], last[id_index])


def supplier_active_condition() -> ColumnElement[bool]:
    return and_(
        Organization.is_active.is_(True),
        SupplierProfile.status == SupplierStatus.APPROVED.value,
    )


def supplier_updated_at() -> ColumnElement[datetime]:
    return func.greatest(
        Organization.updated_at,
        func.coalesce(SupplierProfile.updated_at, Organization.updated_at),
    )


def supplier_view(
    supplier: Organization,
    effective_updated_at: datetime,
    resource_status: str,
) -> SupplierIntegrationView:
    return SupplierIntegrationView(
        supplier_id=supplier.id,
        supplier_code=supplier.code,
        supplier_name=supplier.name,
        status=resource_status,
        updated_at=effective_updated_at,
    )


def supplier_context(
    db: Session,
    supplier_id: str,
) -> tuple[Organization, SupplierProfile | None]:
    row = db.execute(
        select(Organization, SupplierProfile)
        .outerjoin(
            SupplierProfile,
            SupplierProfile.organization_id == Organization.id,
        )
        .where(
            Organization.id == supplier_id,
            Organization.organization_type == OrganizationType.SUPPLIER.value,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": SkuCostErrorCode.SUPPLIER_NOT_FOUND.value,
                "message": "供应商不存在",
            },
        )
    return row[0], row[1]


def is_supplier_active(
    supplier: Organization,
    profile: SupplierProfile | None,
) -> bool:
    return bool(
        supplier.is_active
        and profile is not None
        and profile.status == SupplierStatus.APPROVED.value
    )


def supplier_context_updated_at(
    supplier: Organization,
    profile: SupplierProfile | None,
) -> datetime:
    if profile is None:
        return supplier.updated_at
    return max(supplier.updated_at, profile.updated_at)


def cost_view(cost: CurrentSkuCost) -> CurrentSkuCostView:
    return CurrentSkuCostView(
        supplier_id=cost.supplier_id,
        supplier_sku_id=cost.supplier_sku_id,
        supplier_sku_code=cost.supplier_sku_code,
        cost_price=cost.cost_price,
        currency=cost.currency,
        cost_updated_at=cost.cost_updated_at,
    )


def request_id_for_audit(request: Request) -> str:
    request_id = request.headers.get("X-Request-ID")
    if request_id is None or not request_id.strip():
        return str(uuid4())
    return request_id


def set_cost_query_counts(
    request: Request,
    *,
    result_count: int,
    error_count: int,
) -> None:
    request.state.cost_query_result_count = result_count
    request.state.cost_query_error_count = error_count


def record_cost_query_event(request: Request) -> None:
    principal = getattr(request.state, "integration_principal", None)
    if not isinstance(principal, AuthenticatedIntegrationClient):
        return

    try:
        with SessionLocal.begin() as audit_db:
            record_event(
                audit_db,
                event_type="INTEGRATION_SKU_COSTS_QUERIED",
                entity_type="IntegrationClient",
                entity_id=principal.id,
                organization_id=None,
                actor_type="INTEGRATION_CLIENT",
                actor_id=principal.id,
                payload={
                    "request_id": request_id_for_audit(request),
                    "endpoint": request.url.path,
                    "result_count": getattr(
                        request.state, "cost_query_result_count", 0
                    ),
                    "error_count": getattr(
                        request.state, "cost_query_error_count", 1
                    ),
                },
            )
    except Exception:
        logger.exception("Failed to record integration cost query audit event")


def ranked_cooperations(supplier_id: str):
    active_first = case(
        (SupplierBrandCooperation.status == ACTIVE, 0),
        else_=1,
    )
    return (
        select(
            SupplierBrandCooperation.id.label("cooperation_id"),
            SupplierBrandCooperation.brand_id.label("brand_id"),
            SupplierBrandCooperation.commercial_mode.label("commercial_mode"),
            SupplierBrandCooperation.status.label("cooperation_status"),
            SupplierBrandCooperation.updated_at.label("cooperation_updated_at"),
            func.row_number()
            .over(
                partition_by=SupplierBrandCooperation.brand_id,
                order_by=(
                    active_first,
                    SupplierBrandCooperation.updated_at.desc(),
                    SupplierBrandCooperation.id.desc(),
                ),
            )
            .label("cooperation_rank"),
        )
        .where(SupplierBrandCooperation.supplier_id == supplier_id)
        .subquery()
    )


@router.get(
    "/suppliers",
    response_model=SupplierIntegrationPage,
    responses={**INTEGRATION_AUTH_RESPONSES},
)
def list_suppliers(
    db: DbSession,
    _: SupplierReader,
    updated_since: AwareDatetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    include_inactive: bool = Query(default=False),
) -> SupplierIntegrationPage:
    effective_updated_at = supplier_updated_at().label("effective_updated_at")
    resource_status = case(
        (supplier_active_condition(), ACTIVE),
        else_=INACTIVE,
    ).label("resource_status")
    statement = (
        select(
            Organization,
            effective_updated_at,
            resource_status,
            Organization.id.label("entity_id"),
        )
        .outerjoin(
            SupplierProfile,
            SupplierProfile.organization_id == Organization.id,
        )
        .where(Organization.organization_type == OrganizationType.SUPPLIER.value)
    )
    if not include_inactive:
        statement = statement.where(supplier_active_condition())
    if updated_since is not None:
        statement = statement.where(effective_updated_at > utc_value(updated_since))
    if cursor is not None:
        statement = statement.where(after_cursor(effective_updated_at, Organization.id, cursor))
    rows = db.execute(
        statement.order_by(effective_updated_at, Organization.id).limit(limit + 1)
    ).all()
    page, next_cursor = page_cursor(
        rows,
        limit=limit,
        updated_at_index=1,
        id_index=3,
    )
    return SupplierIntegrationPage(
        items=[supplier_view(row[0], row[1], row[2]) for row in page],
        next_cursor=next_cursor,
    )


@router.get(
    "/suppliers/{supplier_id}",
    response_model=SupplierIntegrationView,
    responses={
        **INTEGRATION_AUTH_RESPONSES,
        **INTEGRATION_NOT_FOUND_RESPONSE,
    },
)
def get_supplier(
    supplier_id: str,
    db: DbSession,
    _: SupplierReader,
) -> SupplierIntegrationView:
    effective_updated_at = supplier_updated_at().label("effective_updated_at")
    resource_status = case(
        (supplier_active_condition(), ACTIVE),
        else_=INACTIVE,
    ).label("resource_status")
    row = db.execute(
        select(Organization, effective_updated_at, resource_status)
        .outerjoin(
            SupplierProfile,
            SupplierProfile.organization_id == Organization.id,
        )
        .where(
            Organization.id == supplier_id,
            Organization.organization_type == OrganizationType.SUPPLIER.value,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": SkuCostErrorCode.SUPPLIER_NOT_FOUND.value,
                "message": "供应商不存在",
            },
        )
    return supplier_view(row[0], row[1], row[2])


@router.get(
    "/suppliers/{supplier_id}/brands",
    response_model=SupplierBrandIntegrationPage,
    responses={
        **INTEGRATION_AUTH_RESPONSES,
        **INTEGRATION_NOT_FOUND_RESPONSE,
    },
)
def list_supplier_brands(
    supplier_id: str,
    db: DbSession,
    _: BrandReader,
    updated_since: AwareDatetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    include_inactive: bool = Query(default=False),
) -> SupplierBrandIntegrationPage:
    supplier, profile = supplier_context(db, supplier_id)
    current = ranked_cooperations(supplier_id)
    effective_updated_at = func.greatest(
        supplier_context_updated_at(supplier, profile),
        Brand.updated_at,
        current.c.cooperation_updated_at,
    ).label("effective_updated_at")
    active_condition = and_(
        is_supplier_active(supplier, profile),
        Brand.status == ACTIVE,
        current.c.cooperation_status == ACTIVE,
    )
    resource_status = case(
        (active_condition, ACTIVE),
        else_=INACTIVE,
    ).label("resource_status")
    statement = (
        select(
            Brand,
            current.c.commercial_mode,
            effective_updated_at,
            resource_status,
            Brand.id.label("entity_id"),
        )
        .join(current, current.c.brand_id == Brand.id)
        .where(current.c.cooperation_rank == 1)
    )
    if not include_inactive:
        statement = statement.where(active_condition)
    if updated_since is not None:
        statement = statement.where(effective_updated_at > utc_value(updated_since))
    if cursor is not None:
        statement = statement.where(after_cursor(effective_updated_at, Brand.id, cursor))
    rows = db.execute(
        statement.order_by(effective_updated_at, Brand.id).limit(limit + 1)
    ).all()
    page, next_cursor = page_cursor(
        rows,
        limit=limit,
        updated_at_index=2,
        id_index=4,
    )
    return SupplierBrandIntegrationPage(
        items=[
            SupplierBrandIntegrationView(
                brand_id=row[0].id,
                brand_code=row[0].code,
                brand_name=row[0].name,
                commercial_mode=row[1],
                status=row[3],
                updated_at=row[2],
            )
            for row in page
        ],
        next_cursor=next_cursor,
    )


@router.get(
    "/suppliers/{supplier_id}/skus",
    response_model=SupplierSkuIntegrationPage,
    responses={
        **INTEGRATION_AUTH_RESPONSES,
        **INTEGRATION_NOT_FOUND_RESPONSE,
    },
)
def list_supplier_skus(
    supplier_id: str,
    db: DbSession,
    _: SkuReader,
    updated_since: AwareDatetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    include_inactive: bool = Query(default=False),
) -> SupplierSkuIntegrationPage:
    supplier, profile = supplier_context(db, supplier_id)
    current = ranked_cooperations(supplier_id)
    effective_updated_at = func.greatest(
        supplier_context_updated_at(supplier, profile),
        SupplierSku.updated_at,
        Brand.updated_at,
        Product.updated_at,
        current.c.cooperation_updated_at,
    ).label("effective_updated_at")
    active_condition = and_(
        is_supplier_active(supplier, profile),
        SupplierSku.status == ACTIVE,
        Brand.status == ACTIVE,
        current.c.cooperation_status == ACTIVE,
    )
    resource_status = case(
        (active_condition, ACTIVE),
        else_=INACTIVE,
    ).label("resource_status")
    statement = (
        select(
            SupplierSku,
            Brand,
            Product,
            current.c.commercial_mode,
            effective_updated_at,
            resource_status,
            SupplierSku.id.label("entity_id"),
        )
        .join(Brand, Brand.id == SupplierSku.brand_id)
        .join(
            Product,
            and_(
                Product.id == SupplierSku.product_id,
                Product.created_by_organization_id == supplier_id,
            ),
        )
        .outerjoin(
            current,
            and_(
                current.c.brand_id == SupplierSku.brand_id,
                current.c.cooperation_rank == 1,
            ),
        )
        .where(SupplierSku.supplier_id == supplier_id)
    )
    if not include_inactive:
        statement = statement.where(active_condition)
    if updated_since is not None:
        statement = statement.where(effective_updated_at > utc_value(updated_since))
    if cursor is not None:
        statement = statement.where(
            after_cursor(effective_updated_at, SupplierSku.id, cursor)
        )
    rows = db.execute(
        statement.order_by(effective_updated_at, SupplierSku.id).limit(limit + 1)
    ).all()
    page, next_cursor = page_cursor(
        rows,
        limit=limit,
        updated_at_index=4,
        id_index=6,
    )
    return SupplierSkuIntegrationPage(
        items=[
            SupplierSkuIntegrationView(
                supplier_sku_id=row[0].id,
                supplier_sku_code=row[0].supplier_sku_code,
                brand_id=row[1].id,
                brand_name=row[1].name,
                product_name=row[2].name,
                model=row[2].model,
                manufacturer_part_number=row[0].manufacturer_part_number,
                barcode=row[0].barcode,
                commercial_mode=row[3],
                status=row[5],
                updated_at=row[4],
            )
            for row in page
        ],
        next_cursor=next_cursor,
    )


def get_supplier_sku_cost(
    supplier_id: str,
    supplier_sku_id: str,
    request: Request,
    db: DbSession,
    _: CostReader,
) -> CurrentSkuCostView | JSONResponse:
    try:
        cost = resolve_current_sku_cost(
            db,
            supplier_id=supplier_id,
            supplier_sku_id=supplier_sku_id,
        )
    except SkuCostError as exc:
        set_cost_query_counts(request, result_count=0, error_count=1)
        error_status = (
            status.HTTP_404_NOT_FOUND
            if exc.code in MISSING_COST_CODES
            else status.HTTP_409_CONFLICT
        )
        return JSONResponse(
            status_code=error_status,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    set_cost_query_counts(request, result_count=1, error_count=0)
    return cost_view(cost)


def query_supplier_sku_costs(
    payload: SkuCostBatchRequest,
    request: Request,
    db: DbSession,
    _: CostReader,
) -> SkuCostBatchResponse:
    results: list[SkuCostBatchSuccess | SkuCostBatchError] = []
    result_count = 0
    error_count = 0
    for item in payload.items:
        try:
            cost = resolve_current_sku_cost(
                db,
                supplier_id=item.supplier_id,
                supplier_sku_id=item.supplier_sku_id,
            )
        except SkuCostError as exc:
            error_count += 1
            results.append(
                SkuCostBatchError(
                    client_sku_id=item.client_sku_id,
                    supplier_id=item.supplier_id,
                    supplier_sku_id=item.supplier_sku_id,
                    error_code=exc.code,
                    message=exc.message,
                )
            )
            continue

        result_count += 1
        results.append(
            SkuCostBatchSuccess(
                client_sku_id=item.client_sku_id,
                supplier_id=cost.supplier_id,
                supplier_sku_id=cost.supplier_sku_id,
                supplier_sku_code=cost.supplier_sku_code,
                cost_price=cost.cost_price,
                currency=cost.currency,
                cost_updated_at=cost.cost_updated_at,
            )
        )

    set_cost_query_counts(
        request,
        result_count=result_count,
        error_count=error_count,
    )
    return SkuCostBatchResponse(items=results)


router.add_api_route(
    "/suppliers/{supplier_id}/skus/{supplier_sku_id}/cost",
    get_supplier_sku_cost,
    methods=["GET"],
    response_model=CurrentSkuCostView,
    route_class_override=CostValidationRoute,
    responses={
        **INTEGRATION_AUTH_RESPONSES,
        **INTEGRATION_VALIDATION_RESPONSE,
        **INTEGRATION_NOT_FOUND_RESPONSE,
        **COST_BUSINESS_RESPONSE,
    },
)
router.add_api_route(
    "/sku-costs/query",
    query_supplier_sku_costs,
    methods=["POST"],
    response_model=SkuCostBatchResponse,
    route_class_override=CostValidationRoute,
    responses={
        **INTEGRATION_AUTH_RESPONSES,
        **INTEGRATION_VALIDATION_RESPONSE,
    },
)
