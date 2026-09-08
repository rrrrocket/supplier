from __future__ import annotations

import json
from typing import Any

from app.main import app
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


def schema_ref_name(schema: dict[str, Any]) -> str:
    return schema["$ref"].rsplit("/", 1)[-1]


def response_schema(operation: dict[str, Any], status_code: int) -> dict[str, Any]:
    return operation["responses"][str(status_code)]["content"]["application/json"][
        "schema"
    ]


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
        assert parameters["limit"]["schema"] == {
            "type": "integer",
            "maximum": 500,
            "minimum": 1,
            "default": 100,
            "title": "Limit",
        }
        assert parameters["include_inactive"]["schema"]["default"] is False


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
        retry_after = operation["responses"]["429"]["headers"]["Retry-After"]
        assert retry_after["schema"]["type"] == "integer"
        assert retry_after["schema"]["minimum"] == 1


def test_cost_operations_publish_validation_and_business_responses() -> None:
    """Catch the cost API documenting only its success branch."""
    openapi = app.openapi()
    single = openapi["paths"][
        "/api/integrations/v1/suppliers/{supplier_id}/skus/{supplier_sku_id}/cost"
    ]["get"]
    batch = openapi["paths"]["/api/integrations/v1/sku-costs/query"]["post"]

    assert {"200", "400", "401", "403", "404", "409", "429"}.issubset(
        single["responses"]
    )
    assert {"200", "400", "401", "403", "429"}.issubset(batch["responses"])
    assert schema_ref_name(response_schema(single, 200)) == "CurrentSkuCostView"
    assert schema_ref_name(response_schema(batch, 200)) == "SkuCostBatchResponse"
