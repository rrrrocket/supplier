from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi as fastapi_get_openapi
from fastapi.testclient import TestClient

import app.main as main_module
from app.api.router import api_router
from app.main import app, normalize_public_openapi
from app.schemas import integration as integration_contract


PUBLIC_OPERATIONS = {
    "/api/integrations/v1/suppliers": ("get", "SupplierIntegrationPage"),
    "/api/integrations/v1/suppliers/{supplier_id}": (
        "get",
        "SupplierIntegrationView",
    ),
    "/api/integrations/v1/suppliers/{supplier_id}/brands": (
        "get",
        "SupplierBrandIntegrationPage",
    ),
    "/api/integrations/v1/suppliers/{supplier_id}/skus": (
        "get",
        "SupplierSkuIntegrationPage",
    ),
    "/api/integrations/v1/suppliers/{supplier_id}/skus/{supplier_sku_id}/cost": (
        "get",
        "CurrentSkuCostView",
    ),
    "/api/integrations/v1/sku-costs/query": ("post", "SkuCostBatchResponse"),
}
EXPECTED_RESPONSE_STATUSES = {
    "/api/integrations/v1/suppliers": {
        "200",
        "400",
        "401",
        "403",
        "422",
        "429",
    },
    "/api/integrations/v1/suppliers/{supplier_id}": {
        "200",
        "401",
        "403",
        "404",
        "429",
    },
    "/api/integrations/v1/suppliers/{supplier_id}/brands": {
        "200",
        "400",
        "401",
        "403",
        "404",
        "422",
        "429",
    },
    "/api/integrations/v1/suppliers/{supplier_id}/skus": {
        "200",
        "400",
        "401",
        "403",
        "404",
        "422",
        "429",
    },
    "/api/integrations/v1/suppliers/{supplier_id}/skus/{supplier_sku_id}/cost": {
        "200",
        "401",
        "403",
        "404",
        "409",
        "429",
    },
    "/api/integrations/v1/sku-costs/query": {
        "200",
        "400",
        "401",
        "403",
        "429",
    },
}
EXPECTED_SCOPES = {
    "suppliers:read",
    "supplier-brands:read",
    "supplier-skus:read",
    "supplier-costs:read",
}
EXPECTED_COST_ERROR_CODES = {
    "SUPPLIER_NOT_FOUND",
    "SUPPLIER_INACTIVE",
    "SKU_NOT_FOUND",
    "SKU_INACTIVE",
    "SKU_SUPPLIER_MISMATCH",
    "BRAND_COOPERATION_INACTIVE",
    "NOT_SELF_PURCHASE",
    "COST_PRICE_MISSING",
}
PUBLIC_SCHEMA_NAMES = {
    "CurrentSkuCostView",
    "SkuCostBatchError",
    "SkuCostBatchRequest",
    "SkuCostBatchResponse",
    "SkuCostBatchSuccess",
    "SkuCostErrorCode",
    "SkuCostQueryItem",
    "SupplierBrandIntegrationPage",
    "SupplierBrandIntegrationView",
    "SupplierIntegrationPage",
    "SupplierIntegrationView",
    "SupplierSkuIntegrationPage",
    "SupplierSkuIntegrationView",
}
HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}


@app.get("/api/test/structured-not-found", include_in_schema=False)
def structured_not_found() -> None:
    raise HTTPException(
        status_code=404,
        detail={"code": "SUPPLIER_NOT_FOUND", "message": "供应商不存在"},
    )


@app.get("/api/test/string-not-found", include_in_schema=False)
def string_not_found() -> None:
    raise HTTPException(status_code=404, detail="内部资源不存在")


def schema_ref_name(schema: dict[str, Any]) -> str:
    return schema["$ref"].rsplit("/", 1)[-1]


def response_schema(operation: dict[str, Any], status_code: int) -> dict[str, Any]:
    return operation["responses"][str(status_code)]["content"]["application/json"][
        "schema"
    ]


def test_global_404_handler_only_preserves_structured_error_details(
    client: TestClient,
) -> None:
    structured = client.get("/api/test/structured-not-found")
    string_error = client.get("/api/test/string-not-found")
    missing_page = client.get("/definitely-missing-page")

    assert structured.status_code == 404
    assert structured.json() == {
        "detail": {"code": "SUPPLIER_NOT_FOUND", "message": "供应商不存在"}
    }
    assert string_error.status_code == 404
    assert string_error.json() == {"detail": "页面或资源不存在"}
    assert missing_page.status_code == 404
    assert missing_page.json() == {"detail": "页面或资源不存在"}


def test_openapi_publishes_six_caller_neutral_integration_operations() -> None:
    """Catch a removed/renamed route or a caller-specific public contract."""
    openapi = app.openapi()
    integration_paths = {
        path
        for path in openapi["paths"]
        if path.startswith("/api/integrations/v1")
    }

    assert integration_paths == set(PUBLIC_OPERATIONS)

    for path, (method, response_model) in PUBLIC_OPERATIONS.items():
        path_item = openapi["paths"][path]
        assert HTTP_METHODS.intersection(path_item) == {method}
        assert schema_ref_name(response_schema(path_item[method], 200)) == response_model

    public_contract = json.dumps(
        {
            "paths": {
                path: openapi["paths"][path]
                for path in PUBLIC_OPERATIONS
            },
            "schemas": {
                name: openapi["components"]["schemas"][name]
                for name in PUBLIC_SCHEMA_NAMES
            },
        },
        ensure_ascii=False,
    ).lower()
    for caller_specific_name in ("miaoshou", "妙手", "erp_sku_id", "seller_sku_id"):
        assert caller_specific_name not in public_contract


def test_list_openapi_exposes_incremental_pagination_contract() -> None:
    """Catch loss of a sync control or a change to the public page-size boundary."""
    openapi = app.openapi()
    list_paths = (
        "/api/integrations/v1/suppliers",
        "/api/integrations/v1/suppliers/{supplier_id}/brands",
        "/api/integrations/v1/suppliers/{supplier_id}/skus",
    )

    for path in list_paths:
        response_model = PUBLIC_OPERATIONS[path][1]
        parameters = {
            parameter["name"]: parameter
            for parameter in openapi["paths"][path]["get"]["parameters"]
            if parameter["in"] == "query"
        }
        assert set(parameters) == {
            "updated_since",
            "cursor",
            "limit",
            "include_inactive",
        }
        limit_schema = parameters["limit"]["schema"]
        assert limit_schema["type"] == "integer"
        assert limit_schema["maximum"] == 500
        assert limit_schema["minimum"] == 1
        assert limit_schema["default"] == 100
        assert parameters["include_inactive"]["schema"]["default"] is False
        page_schema = openapi["components"]["schemas"][response_model]
        assert "sync_watermark" in page_schema["required"]
        assert page_schema["properties"]["sync_watermark"] == {
            "type": "string",
            "format": "date-time",
            "title": "Sync Watermark",
        }


def test_batch_cost_schema_uses_generic_client_identifier() -> None:
    """Catch replacement of the opaque caller-owned ID with a caller-specific alias."""
    openapi = app.openapi()
    item_schema = openapi["components"]["schemas"]["SkuCostQueryItem"]

    assert set(item_schema["properties"]) == {
        "client_sku_id",
        "supplier_id",
        "supplier_sku_id",
    }
    assert set(item_schema["required"]) == {
        "client_sku_id",
        "supplier_id",
        "supplier_sku_id",
    }
    request_schema = openapi["paths"]["/api/integrations/v1/sku-costs/query"][
        "post"
    ]["requestBody"]["content"]["application/json"]["schema"]
    assert schema_ref_name(request_schema) == "SkuCostBatchRequest"
    batch_items = openapi["components"]["schemas"]["SkuCostBatchRequest"][
        "properties"
    ]["items"]
    assert batch_items["minItems"] == 1
    assert batch_items["maxItems"] == 500

    commercial_mode = openapi["components"]["schemas"][
        "SupplierSkuIntegrationView"
    ]["properties"]["commercial_mode"]
    assert {option.get("type") for option in commercial_mode["anyOf"]} == {
        "string",
        "null",
    }


def test_openapi_scope_enum_matches_exported_integration_scopes() -> None:
    """Catch authorization scopes drifting away from the credential API schema."""
    openapi = app.openapi()
    exported_scopes = getattr(integration_contract, "INTEGRATION_SCOPES", ())
    scope_schema = openapi["components"]["schemas"].get("IntegrationScope")

    assert set(exported_scopes) == EXPECTED_SCOPES
    assert scope_schema is not None
    assert set(scope_schema["enum"]) == EXPECTED_SCOPES


def test_openapi_error_enum_matches_exported_cost_error_codes() -> None:
    """Catch a resolver error that batch callers cannot discover from the schema."""
    openapi = app.openapi()
    exported_codes = getattr(integration_contract, "SKU_COST_ERROR_CODES", ())
    error_schema = openapi["components"]["schemas"].get("SkuCostErrorCode")

    assert set(exported_codes) == EXPECTED_COST_ERROR_CODES
    assert error_schema is not None
    assert set(error_schema["enum"]) == EXPECTED_COST_ERROR_CODES


def test_every_integration_operation_documents_bearer_auth_and_rate_limits() -> None:
    """Catch authenticated runtime behavior disappearing from generated API docs."""
    openapi = app.openapi()
    security_schemes = openapi["components"].get("securitySchemes", {})

    assert security_schemes.get("IntegrationBearer") == {
        "type": "http",
        "scheme": "bearer",
    }
    for path, (method, _) in PUBLIC_OPERATIONS.items():
        operation = openapi["paths"][path][method]
        assert operation["security"] == [{"IntegrationBearer": []}]
        authenticate = operation["responses"]["401"]["headers"][
            "WWW-Authenticate"
        ]
        assert authenticate["schema"]["type"] == "string"
        retry_after = operation["responses"]["429"]["headers"]["Retry-After"]
        assert retry_after["schema"]["type"] == "integer"
        assert retry_after["schema"]["minimum"] == 1


def test_each_operation_publishes_only_its_reachable_response_statuses() -> None:
    """Catch documented responses that are missing at runtime or cannot occur."""
    openapi = app.openapi()

    for path, expected_statuses in EXPECTED_RESPONSE_STATUSES.items():
        method = PUBLIC_OPERATIONS[path][0]
        assert set(openapi["paths"][path][method]["responses"]) == expected_statuses


def test_openapi_schema_cache_keeps_the_normalized_public_contract() -> None:
    """Catch custom schema normalization rebuilding or mutating on every request."""
    app.openapi_schema = None

    first = app.openapi()
    second = app.openapi()

    assert first is second
    assert app.openapi_schema is first


def test_concurrent_openapi_callers_only_observe_the_normalized_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch publishing locally generated OpenAPI before normalization completes."""
    application = FastAPI()
    application.include_router(api_router, prefix="/api")
    local_schema_ready = Event()
    release_schema_builder = Event()
    competing_call_gate = Barrier(2)
    competing_call_started = Event()
    competing_call_returned = Event()

    def delayed_get_openapi(**kwargs: Any) -> dict[str, Any]:
        schema = fastapi_get_openapi(**kwargs)
        local_schema_ready.set()
        if not release_schema_builder.wait(timeout=5):
            raise TimeoutError("test did not release local OpenAPI generation")
        return schema

    monkeypatch.setattr(main_module, "get_openapi", delayed_get_openapi, raising=False)
    normalize_public_openapi(application)

    def competing_read() -> dict[str, Any]:
        competing_call_gate.wait(timeout=5)
        competing_call_started.set()
        schema = application.openapi()
        competing_call_returned.set()
        return schema

    with ThreadPoolExecutor(max_workers=2) as executor:
        generating = executor.submit(application.openapi)
        assert local_schema_ready.wait(timeout=5)
        assert application.openapi_schema is None
        competing = executor.submit(competing_read)
        competing_call_gate.wait(timeout=5)
        assert competing_call_started.wait(timeout=5)
        returned_before_normalization = competing_call_returned.wait(timeout=1)
        assert application.openapi_schema is None
        release_schema_builder.set()
        generated_schema = generating.result(timeout=5)
        competing_schema = competing.result(timeout=5)

    assert returned_before_normalization is False
    assert generated_schema is competing_schema
    assert application.openapi_schema is generated_schema
    for path in (
        "/api/integrations/v1/suppliers/{supplier_id}",
        (
            "/api/integrations/v1/suppliers/{supplier_id}/skus/"
            "{supplier_sku_id}/cost"
        ),
        "/api/integrations/v1/sku-costs/query",
    ):
        method = PUBLIC_OPERATIONS[path][0]
        assert "422" not in generated_schema["paths"][path][method]["responses"]


def test_openapi_normalization_failure_leaves_cache_empty_and_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch a failed normalization permanently caching the raw schema."""
    application = FastAPI()
    application.include_router(api_router, prefix="/api")
    normalize_public_openapi(application)

    def fail_normalization(_: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("injected normalization failure")

    with monkeypatch.context() as failure_context:
        failure_context.setattr(
            main_module,
            "normalize_public_openapi_schema",
            fail_normalization,
            raising=False,
        )
        with pytest.raises(RuntimeError, match="injected normalization failure"):
            application.openapi()

    assert application.openapi_schema is None
    recovered_schema = application.openapi()
    assert application.openapi_schema is recovered_schema
    for path in (
        "/api/integrations/v1/suppliers/{supplier_id}",
        (
            "/api/integrations/v1/suppliers/{supplier_id}/skus/"
            "{supplier_sku_id}/cost"
        ),
        "/api/integrations/v1/sku-costs/query",
    ):
        method = PUBLIC_OPERATIONS[path][0]
        assert "422" not in recovered_schema["paths"][path][method]["responses"]
