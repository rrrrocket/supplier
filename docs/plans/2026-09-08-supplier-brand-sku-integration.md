# Supplier Brand, SKU, and System Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add supplier-brand cooperation modes, stable Supplier SKU identities, generic integration credentials and APIs, and mode-A SKU cost lookup without coupling Supplier Network to any specific calling system.

**Architecture:** Introduce normalized `Brand`, historical `SupplierBrandCooperation`, and stable `SupplierSku` entities while retaining `SupplierOffer` as the current commercial data record. Calling systems own their local SKU mappings and pass an opaque `client_sku_id`; generic read-only integration endpoints authenticate with scoped bearer tokens and expose costs only when the current supplier-brand mode is `SELF_PURCHASE`.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16 on port 6432, psycopg 3, vanilla JavaScript, Node test runner, Docker Compose.

**Spec:** `docs/designs/2026-09-08-supplier-brand-sku-integration-design.md`

## Global Constraints

- Production and tests use PostgreSQL 16 with `postgresql+psycopg`; PostgreSQL listens on port `6432`.
- The default operational command remains `./start.sh`; automated verification runs through `./start.sh test`.
- API paths and schemas must not mention any specific calling system; use `/api/integrations/v1` and `client_sku_id`.
- Supplier Network never persists a calling system's SKU ID or its confirmed local mapping.
- `supplier_sku_id` is stable when cost, inventory, MOQ, lead time, or cooperation mode changes.
- A supplier-brand pair has at most one active cooperation mode at a time; mode changes preserve history.
- Only a SKU whose current supplier-brand cooperation is `SELF_PURCHASE` may return `cost_price`.
- Cost lookup returns only the current price, currency, and update time; it does not calculate tax, freight, landed cost, price tiers, or historical cost.
- Supplier and platform permissions remain distinct; Integration Clients never authenticate with a web Session.
- Existing supplier IDs, users, products, offers, inventory snapshots, imports, and event logs must survive every migration.
- Existing dirty-worktree changes belong to the user; stage and commit only files listed by the current task.
- Before executing commit steps, configure repository-local Git `user.name` and `user.email`; do not invent an identity.

## File Structure

### New files

- `app/api/integration_deps.py` — bearer-token authentication and scope dependencies for system callers.
- `app/api/routes/admin_catalog.py` — platform-only brand, cooperation, and Integration Client management endpoints.
- `app/api/routes/supplier_catalog.py` — supplier-visible read-only cooperation endpoint.
- `app/api/routes/integrations.py` — generic `/integrations/v1` supplier, brand, SKU, and cost endpoints.
- `app/core/integration_security.py` — high-entropy token generation, hashing, and verification.
- `app/schemas/catalog.py` — brand, cooperation, and Supplier SKU schemas shared by platform and supplier APIs.
- `app/schemas/integration.py` — Integration Client, paginated resource, and cost-query schemas.
- `app/services/catalog.py` — normalized brand resolution, Supplier SKU creation, cooperation replacement, and current-cost resolution.
- `app/services/integration_pagination.py` — opaque cursor encode/decode helpers.
- `migrations/versions/9a61d5c312ef_add_supplier_catalog_entities.py` — expand schema and backfill Brand, cooperation, and Supplier SKU data.
- `migrations/versions/b742e6d423f0_add_integration_clients.py` — Integration Client credentials.
- `migrations/versions/cc83f7e534a1_finish_supplier_catalog_migration.py` — enforce final foreign keys and remove legacy duplicate columns.
- `tests/migration_utils.py` — temporary PostgreSQL database and Alembic helpers.
- `tests/test_supplier_catalog_migration.py` — migration and data-preservation coverage.
- `tests/test_catalog.py` — cooperation and stable Supplier SKU API coverage.
- `tests/test_integration_auth.py` — token, scope, expiry, and revocation coverage.
- `tests/test_integrations.py` — generic catalog and cost endpoint coverage.
- `tests/test_integration_contract.py` — OpenAPI and documentation contract checks.

### Existing files modified

- `app/models/entities.py` — new enums/entities/relationships and final Product/Offer foreign keys.
- `app/api/router.py` — register the three focused route modules.
- `app/api/routes/products.py` — resolve product brands through `Brand`.
- `app/api/routes/offers.py` — create and return stable Supplier SKU records.
- `app/api/routes/imports.py` — upsert Brand and Supplier SKU while importing offers.
- `app/schemas/product.py` — expose `brand_id`, `supplier_sku_id`, and `supplier_sku_code`.
- `app/web/pages/admin.html` and `app/web/assets/admin.js` — cooperation and Integration Client management UI.
- `app/web/pages/app.html` and `app/web/assets/app.js` — assigned-brand selection and mode-A “成本价” wording.
- `app/web/assets/common.js` — labels for catalog and integration audit events.
- `app/web/assets/styles.css` — small catalog-management layout additions.
- `tests/conftest.py` — deterministic Brand/cooperation fixtures and Integration Client helper.
- `tests/test_api.py`, `tests/test_admin.py`, `tests/test_role_migration.py` — adapt current behavior and reuse migration helpers.
- `docs/architecture/overview.md`, `docs/architecture/data-dictionary.md`, `README.md`, `docs/operations/validation.md`, and `docs/integrations/system-integration-guide.md` — describe the implemented contract and verified behavior.

---

### Task 1: Expand the Catalog Schema and Backfill Existing Data

**Files:**
- Create: `tests/migration_utils.py`
- Create: `tests/test_supplier_catalog_migration.py`
- Create: `migrations/versions/9a61d5c312ef_add_supplier_catalog_entities.py`
- Modify: `tests/test_role_migration.py:1-110`
- Modify: `app/models/entities.py:8-246`

**Interfaces:**
- Produces: `CommercialMode`, `CatalogStatus`, `Brand`, `SupplierBrandCooperation`, and `SupplierSku` ORM types.
- Produces: nullable transitional `Product.brand_id` and `SupplierOffer.supplier_sku_id` fields while legacy string columns remain available.
- Produces: `temporary_postgresql_database()` and `run_migrations(database_url, revision)` test helpers.
- Consumes: existing revision `7f22c89a41bd`, PostgreSQL-only test environment, and current Product/Offer data.

- [ ] **Step 1: Extract reusable PostgreSQL migration test helpers**

Create `tests/migration_utils.py` with these public signatures:

```python
@contextmanager
def temporary_postgresql_database(prefix: str) -> Iterator[URL]:
    server_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"{prefix}_{uuid4().hex}_test"
    database_url = server_url.set(database=database_name)

    with connect(server_url, "postgres") as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )

    try:
        yield database_url
    finally:
        with connect(server_url, "postgres") as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(database_name)
                )
            )


def run_migrations(database_url: URL, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url.render_as_string(
        hide_password=False
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
```

Move the create-database, terminate-connections, and drop-database logic from `tests/test_role_migration.py` into the context manager. Keep the database-name `_test` suffix and use psycopg SQL identifiers rather than string interpolation.

- [ ] **Step 2: Write the failing migration preservation test**

In `tests/test_supplier_catalog_migration.py`, migrate a temporary database to `7f22c89a41bd`, insert one supplier, two named brands represented by Product strings, two offers, and one inventory snapshot, then migrate to `9a61d5c312ef` and assert:

```python
assert connection.execute("SELECT count(*) FROM brands").fetchone()[0] == 2
assert dict(connection.execute(
    "SELECT name, commercial_mode FROM brands "
    "JOIN supplier_brand_cooperations ON brands.id = supplier_brand_cooperations.brand_id"
)) == {"品牌A": "SELF_PURCHASE", "品牌B": "SELF_PURCHASE"}
assert connection.execute("SELECT count(*) FROM supplier_skus").fetchone()[0] == 2
assert connection.execute(
    "SELECT count(*) FROM supplier_offers WHERE supplier_sku_id IS NOT NULL"
).fetchone()[0] == 2
assert connection.execute("SELECT count(*) FROM inventory_snapshots").fetchone()[0] == 1
```

Also assert each backfilled `supplier_skus.id` equals the source `supplier_offers.id`, each SKU code is preserved, and the existing organization, product, offer, and inventory IDs are unchanged.

- [ ] **Step 3: Run the full test command and verify the new test fails**

Run: `./start.sh test`

Expected: FAIL because revision `9a61d5c312ef` and the catalog tables do not exist; all earlier tests still execute against PostgreSQL on port 6432.

- [ ] **Step 4: Add catalog enums and transitional ORM entities**

Add to `app/models/entities.py`:

```python
class CommercialMode(str, Enum):
    SELF_PURCHASE = "SELF_PURCHASE"
    JOINT_OPERATION = "JOINT_OPERATION"
    B2B = "B2B"


class CatalogStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
```

Define `Brand`, `SupplierBrandCooperation`, and `SupplierSku` using the exact field names from the spec. Add a PostgreSQL partial unique index named `uq_active_supplier_brand_cooperation` over `(supplier_id, brand_id)` where `status = 'ACTIVE'`. Add indexes for normalized brand name, Supplier SKU supplier, brand, product, code, barcode, and manufacturer part number.

Add nullable `Product.brand_id` and nullable unique `SupplierOffer.supplier_sku_id` so the application remains compatible while later tasks switch writes to the new model.

- [ ] **Step 5: Implement the expand-and-backfill Alembic revision**

Create revision `9a61d5c312ef` with `down_revision = "7f22c89a41bd"`. Its upgrade must:

1. Reject products referenced by offers when `trim(products.brand)` is empty, with an exception containing the invalid count.
2. Create `brands`, `supplier_brand_cooperations`, and `supplier_skus`.
3. Add nullable `products.brand_id` and `supplier_offers.supplier_sku_id`.
4. Deduplicate brands with the same rule as `normalize_brand_name`: trim, lowercase, and collapse every whitespace run to one space. In PostgreSQL use `lower(regexp_replace(btrim(products.brand), '\s+', ' ', 'g'))`; generate deterministic codes as `BR-` plus the first 10 uppercase characters of `md5(normalized_name)`.
5. Backfill `products.brand_id`.
6. Create one active `SELF_PURCHASE` cooperation for each distinct existing supplier/brand represented by an offer.
7. Create one `SupplierSku` per existing offer using `supplier_skus.id = supplier_offers.id`, preserving the old supplier code, product, and variant.
8. Backfill `supplier_offers.supplier_sku_id`.

The downgrade removes only the new foreign-key columns and tables; it must not alter legacy Product/Offer values.

- [ ] **Step 6: Run tests and inspect the migrated row counts**

Run: `./start.sh test`

Expected: PASS, including the migration data-preservation test and the existing role migration test.

- [ ] **Step 7: Commit the schema expansion**

```bash
git add app/models/entities.py migrations/versions/9a61d5c312ef_add_supplier_catalog_entities.py tests/migration_utils.py tests/test_role_migration.py tests/test_supplier_catalog_migration.py
git commit -m "feat: add supplier catalog identities"
```

### Task 2: Route Product, Offer, and Import Writes Through Stable Supplier SKUs

**Files:**
- Create: `app/services/catalog.py`
- Create: `app/schemas/catalog.py`
- Create: `app/api/routes/supplier_catalog.py`
- Create: `tests/test_catalog.py`
- Modify: `app/api/routes/products.py:1-90`
- Modify: `app/api/routes/offers.py:1-170`
- Modify: `app/api/routes/imports.py:320-390`
- Modify: `app/schemas/product.py:8-90`
- Modify: `tests/conftest.py:45-85`
- Modify: `tests/test_api.py:55-145`

**Interfaces:**
- Consumes: `Brand`, `SupplierBrandCooperation`, `SupplierSku`, and transitional foreign keys from Task 1.
- Produces: `normalize_brand_name(value: str) -> str`, `resolve_brand(db: Session, name: str) -> Brand`, and `ensure_supplier_sku(db: Session, *, supplier_id: str, brand_id: str, product_id: str, variant_id: str | None, supplier_sku_code: str, manufacturer_part_number: str | None = None, barcode: str | None = None) -> SupplierSku`.
- Produces: API fields `brand_id`, `supplier_sku_id`, and `supplier_sku_code` while keeping response field `brand` as the display name.
- Produces: `GET /api/supplier-catalog/brand-cooperations` for supplier-visible assigned brands.

- [ ] **Step 1: Write failing stable-SKU and tenant-isolation tests**

Add tests that create an active brand cooperation and then create/update an offer:

```python
created = authenticated_client.post("/api/offers", json=offer_payload).json()
supplier_sku_id = created["supplier_sku_id"]

updated = authenticated_client.patch(
    f"/api/offers/{created['id']}",
    json={"price": "49.9000"},
).json()

assert updated["supplier_sku_id"] == supplier_sku_id
assert updated["supplier_sku_code"] == offer_payload["supplier_sku_code"]
```

Add a direct service test asserting `ensure_supplier_sku` rejects a product or brand from another supplier. Add an import test asserting reimporting the same supplier code reuses the same `SupplierSku.id`.

- [ ] **Step 2: Run tests and verify failures**

Run: `./start.sh test`

Expected: FAIL because offer responses do not expose a Supplier SKU ID and write flows do not create `SupplierSku` records.

- [ ] **Step 3: Implement focused catalog service functions**

In `app/services/catalog.py`, implement:

```python
def normalize_brand_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def resolve_brand(db: Session, name: str) -> Brand:
    normalized_name = normalize_brand_name(name)
    if not normalized_name:
        raise ValueError("brand name is required")

    brand = db.scalar(
        select(Brand).where(Brand.normalized_name == normalized_name)
    )
    if brand is not None:
        return brand

    digest = md5(
        normalized_name.encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:10].upper()
    brand = Brand(
        code=f"BR-{digest}",
        name=name.strip(),
        normalized_name=normalized_name,
        aliases=[],
        status=CatalogStatus.ACTIVE.value,
    )
    db.add(brand)
    db.flush()
    return brand


def ensure_supplier_sku(
    db: Session,
    *,
    supplier_id: str,
    brand_id: str,
    product_id: str,
    variant_id: str | None,
    supplier_sku_code: str,
    manufacturer_part_number: str | None = None,
    barcode: str | None = None,
) -> SupplierSku:
    code = supplier_sku_code.strip()
    if not code:
        raise ValueError("supplier SKU code is required")

    product = db.get(Product, product_id)
    if product is None or product.created_by_organization_id != supplier_id:
        raise ValueError("product does not belong to supplier")
    if product.brand_id != brand_id:
        raise ValueError("product does not belong to brand")

    cooperation = db.scalar(
        select(SupplierBrandCooperation).where(
            SupplierBrandCooperation.supplier_id == supplier_id,
            SupplierBrandCooperation.brand_id == brand_id,
            SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
        )
    )
    if cooperation is None:
        raise ValueError("brand is not assigned to supplier")

    if variant_id is not None:
        variant = db.get(ProductVariant, variant_id)
        if variant is None or variant.product_id != product_id:
            raise ValueError("variant does not belong to product")

    supplier_sku = db.scalar(
        select(SupplierSku).where(
            SupplierSku.supplier_id == supplier_id,
            SupplierSku.supplier_sku_code == code,
        )
    )
    if supplier_sku is not None:
        identity = (
            supplier_sku.brand_id,
            supplier_sku.product_id,
            supplier_sku.variant_id,
        )
        if identity != (brand_id, product_id, variant_id):
            raise ValueError("supplier SKU code is already bound")
        for field, value in (
            ("manufacturer_part_number", manufacturer_part_number),
            ("barcode", barcode),
        ):
            current = getattr(supplier_sku, field)
            if value is not None and current not in (None, value):
                raise ValueError(f"supplier SKU {field} conflicts")
            if current is None and value is not None:
                setattr(supplier_sku, field, value)
        return supplier_sku

    supplier_sku = SupplierSku(
        supplier_id=supplier_id,
        brand_id=brand_id,
        product_id=product_id,
        variant_id=variant_id,
        supplier_sku_code=code,
        manufacturer_part_number=manufacturer_part_number,
        barcode=barcode,
        status=CatalogStatus.ACTIVE.value,
    )
    db.add(supplier_sku)
    db.flush()
    return supplier_sku
```

`resolve_brand` must normalize before lookup and generate the same deterministic brand code as the migration. `ensure_supplier_sku` must query by `(supplier_id, supplier_sku_code)`, verify all ownership fields, and update only optional matching metadata; it must never generate a second stable ID for the same supplier code.

- [ ] **Step 4: Update Product and Offer contracts**

Require a non-empty brand on new Product requests. Resolve `brand_id`, require an active `SupplierBrandCooperation` for the authenticated supplier and brand, and serialize `brand` from `Brand.name`.

Change offer request/response names to:

```python
class OfferCreate(BaseModel):
    product_id: str
    supplier_sku_code: str = Field(min_length=1, max_length=120)
    # existing price, currency, MOQ, stock, lead-time, fulfillment, status, notes


class OfferView(BaseModel):
    id: str
    supplier_sku_id: str
    supplier_sku_code: str
    brand_id: str
    brand: str
    # existing commercial fields
```

On create, call `ensure_supplier_sku`, set `SupplierOffer.supplier_sku_id`, and temporarily dual-write legacy `supplier_sku`. On update, never change `supplier_sku_id` or `supplier_sku_code`.

- [ ] **Step 5: Update import upsert behavior**

Keep accepting the existing import column named `supplier_sku`, but treat its value as `supplier_sku_code`. Resolve Brand and Product, call `ensure_supplier_sku`, then find/update the current Offer by `supplier_sku_id`. Continue writing inventory snapshots and import row errors exactly as before.

- [ ] **Step 6: Add supplier-visible cooperation read endpoint**

Create `app/api/routes/supplier_catalog.py` with:

```http
GET /api/supplier-catalog/brand-cooperations
```

It uses `SupplierUser`, returns only the authenticated supplier's active relationships, and exposes `brand_id`, `brand_code`, `brand_name`, `commercial_mode`, and status. Register the router in `app/api/router.py`.

- [ ] **Step 7: Run the full test suite**

Run: `./start.sh test`

Expected: PASS; existing Product/Offer/import behavior remains intact and new stable-SKU assertions pass.

- [ ] **Step 8: Commit stable write flows**

```bash
git add app/services/catalog.py app/schemas/catalog.py app/api/router.py app/api/routes/supplier_catalog.py app/api/routes/products.py app/api/routes/offers.py app/api/routes/imports.py app/schemas/product.py tests/conftest.py tests/test_api.py tests/test_catalog.py
git commit -m "feat: persist stable supplier SKUs"
```

### Task 3: Add Platform Brand and Cooperation Management

**Files:**
- Create: `app/api/routes/admin_catalog.py`
- Modify: `app/api/router.py:1-20`
- Modify: `app/schemas/catalog.py`
- Modify: `app/services/catalog.py`
- Modify: `app/web/pages/admin.html`
- Modify: `app/web/assets/admin.js`
- Modify: `app/web/assets/styles.css`
- Modify: `app/web/assets/common.js`
- Modify: `tests/test_admin.py`
- Modify: `tests/test_catalog.py`

**Interfaces:**
- Consumes: Task 2 catalog schemas and brand normalization.
- Produces: `replace_active_cooperation(db, supplier_id, brand_id, commercial_mode, actor_id) -> SupplierBrandCooperation`.
- Produces: platform endpoints for brand creation/listing and supplier-brand cooperation list/update.

- [ ] **Step 1: Write failing platform API tests**

Cover these exact routes:

```http
GET  /api/admin/brands?q=品牌
POST /api/admin/brands
GET  /api/admin/suppliers/{supplier_id}/brand-cooperations
PUT  /api/admin/suppliers/{supplier_id}/brands/{brand_id}/cooperation
```

The PUT body is `{"commercial_mode": "SELF_PURCHASE"}`. Assert a second PUT with the same mode is idempotent, while changing to `JOINT_OPERATION` makes the prior row `INACTIVE`, creates one new active row, preserves Supplier SKU IDs, and writes a `SUPPLIER_BRAND_COOPERATION_CHANGED` event.

Also assert suppliers receive HTTP 403 and an unknown/non-supplier organization receives HTTP 404.

- [ ] **Step 2: Run tests and verify the routes are missing**

Run: `./start.sh test`

Expected: FAIL with 404 for the new platform routes.

- [ ] **Step 3: Implement schemas and cooperation replacement service**

Add these schema names to `app/schemas/catalog.py`:

```python
BrandCreate(name: str, code: str | None = None,
            aliases: list[str] = Field(default_factory=list))
BrandView(id: str, code: str, name: str, status: str, updated_at: datetime)
CooperationUpdate(commercial_mode: Literal["SELF_PURCHASE", "JOINT_OPERATION", "B2B"])
CooperationView(id: str, supplier_id: str, brand_id: str, brand_name: str,
                commercial_mode: str, status: str, valid_from: date | None,
                valid_to: date | None, updated_at: datetime)
```

`replace_active_cooperation` must load the current row with `select(SupplierBrandCooperation).where(SupplierBrandCooperation.supplier_id == supplier_id, SupplierBrandCooperation.brand_id == brand_id, SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value).with_for_update()`, return it unchanged when the mode matches, otherwise deactivate it and create the replacement in one transaction.

- [ ] **Step 4: Implement platform routes and events**

Use the existing `PlatformAdmin` dependency. Normalize and deduplicate brand names, return HTTP 409 on conflicting explicit brand codes, and record `BRAND_CREATED` and `SUPPLIER_BRAND_COOPERATION_CHANGED` events without storing sensitive data.

- [ ] **Step 5: Add the platform management UI**

In the supplier-management view, add a “品牌合作” action that opens a dialog showing brand, current mode, and status. The dialog must allow platform users to select one of:

```text
SELF_PURCHASE → 模式 A · 自营采购
JOINT_OPERATION → 模式 B · 联营
B2B → 模式 C · ToB 合作
```

Submit through the PUT endpoint. Do not expose cooperation-mode editing in the supplier workbench.

- [ ] **Step 6: Add UI source assertions and run tests**

Add assertions to `tests/test_admin.py` that `/admin` contains the dialog IDs and `admin.js` references the exact cooperation endpoints. Run: `./start.sh test`

Expected: PASS for backend, HTML, and JavaScript tests.

- [ ] **Step 7: Commit cooperation management**

```bash
git add app/api/routes/admin_catalog.py app/api/router.py app/schemas/catalog.py app/services/catalog.py app/web/pages/admin.html app/web/assets/admin.js app/web/assets/styles.css app/web/assets/common.js tests/test_admin.py tests/test_catalog.py
git commit -m "feat: manage supplier brand cooperation"
```

### Task 4: Add Scoped Integration Client Credentials

**Files:**
- Create: `migrations/versions/b742e6d423f0_add_integration_clients.py`
- Create: `app/core/integration_security.py`
- Create: `app/api/integration_deps.py`
- Create: `app/schemas/integration.py`
- Create: `tests/test_integration_auth.py`
- Modify: `app/models/entities.py`
- Modify: `app/api/routes/admin_catalog.py`
- Modify: `app/web/pages/admin.html`
- Modify: `app/web/assets/admin.js`

**Interfaces:**
- Consumes: platform administration dependency and PostgreSQL migrations.
- Produces: `create_integration_token() -> tuple[str, str, str]` returning `(plaintext, prefix, sha256_hash)`.
- Produces: `IntegrationPrincipal` and `require_integration_scope(scope: str)`.
- Produces: platform endpoints to create, list, revoke, and rotate Integration Clients.

- [ ] **Step 1: Write failing token-security tests**

Assert:

```python
plaintext, prefix, digest = create_integration_token()
assert plaintext.startswith("m1i_")
assert plaintext.startswith(prefix)
assert plaintext not in digest
assert verify_integration_token(plaintext, digest)
assert not verify_integration_token(plaintext + "x", digest)
```

Add API tests proving plaintext is returned only by create/rotate responses, never by list responses or database rows. Cover expired, revoked, malformed, missing, and missing-scope tokens with HTTP 401/403.

- [ ] **Step 2: Run tests and verify failures**

Run: `./start.sh test`

Expected: FAIL because the token module, table, and dependencies do not exist.

- [ ] **Step 3: Add the Integration Client migration and model**

Create revision `b742e6d423f0` with `down_revision = "9a61d5c312ef"`. Add `integration_clients` fields from the spec, unique `token_prefix`, JSON scopes, `expires_at`, `is_active`, and `last_used_at`.

- [ ] **Step 4: Implement token generation and verification**

Use `secrets.token_urlsafe(32)` and SHA-256 because the source token has at least 256 bits of entropy:

```python
def create_integration_token() -> tuple[str, str, str]:
    plaintext = f"m1i_{secrets.token_urlsafe(32)}"
    return plaintext, plaintext[:12], hashlib.sha256(plaintext.encode()).hexdigest()


def verify_integration_token(plaintext: str, expected_hash: str) -> bool:
    actual = hashlib.sha256(plaintext.encode()).hexdigest()
    return hmac.compare_digest(actual, expected_hash)
```

- [ ] **Step 5: Implement bearer authentication and scope checks**

`app/api/integration_deps.py` must read `Authorization: Bearer`, locate by the first 12 token characters, verify the hash in constant time, enforce active/not-expired state, update `last_used_at`, and expose reusable dependencies:

```python
SupplierReader = Annotated[IntegrationClient, Depends(require_integration_scope("suppliers:read"))]
BrandReader = Annotated[IntegrationClient, Depends(require_integration_scope("supplier-brands:read"))]
SkuReader = Annotated[IntegrationClient, Depends(require_integration_scope("supplier-skus:read"))]
CostReader = Annotated[IntegrationClient, Depends(require_integration_scope("supplier-costs:read"))]
```

- [ ] **Step 6: Add platform credential management and UI**

Add:

```http
GET  /api/admin/integration-clients
POST /api/admin/integration-clients
POST /api/admin/integration-clients/{client_id}/rotate
POST /api/admin/integration-clients/{client_id}/revoke
```

Create and rotate responses return plaintext once under `token`; list responses expose only `token_prefix`. The admin UI must display the one-time token in a copyable warning dialog and never persist it in browser storage.

- [ ] **Step 7: Run tests and commit**

Run: `./start.sh test`

Expected: PASS, including token secrecy, scope, expiry, revocation, and platform-only management checks.

```bash
git add migrations/versions/b742e6d423f0_add_integration_clients.py app/models/entities.py app/core/integration_security.py app/api/integration_deps.py app/schemas/integration.py app/api/routes/admin_catalog.py app/web/pages/admin.html app/web/assets/admin.js tests/test_integration_auth.py
git commit -m "feat: add scoped integration credentials"
```

### Task 5: Expose Generic Supplier, Brand, and SKU Resources

**Files:**
- Create: `app/api/routes/integrations.py`
- Create: `app/services/integration_pagination.py`
- Create: `tests/test_integrations.py`
- Modify: `app/api/router.py`
- Modify: `app/schemas/integration.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: Task 4 `SupplierReader`, `BrandReader`, and `SkuReader` dependencies.
- Produces: generic integration resources under `/api/integrations/v1`.
- Produces: `encode_cursor(updated_at: datetime, entity_id: str) -> str` and `decode_cursor(value: str) -> tuple[datetime, str]`.

- [ ] **Step 1: Add failing resource and pagination tests**

Create an Integration Client fixture that obtains a token through the platform API. Test:

```http
GET /api/integrations/v1/suppliers
GET /api/integrations/v1/suppliers/{supplier_id}
GET /api/integrations/v1/suppliers/{supplier_id}/brands
GET /api/integrations/v1/suppliers/{supplier_id}/skus
```

Assert only supplier organizations are returned, inactive suppliers are excluded from lists, `updated_since` is honored, `(updated_at, id)` cursor pagination has no duplicate rows, `limit > 500` returns 422, and each endpoint requires its documented scope.

- [ ] **Step 2: Run tests and verify 404 failures**

Run: `./start.sh test`

Expected: FAIL because `/api/integrations/v1` is not registered.

- [ ] **Step 3: Implement opaque cursor helpers**

Encode compact JSON containing UTC ISO timestamp `u` and ID `i` with URL-safe base64. Reject malformed cursors with HTTP 400 and detail code `INVALID_CURSOR`. Queries must order by `(updated_at, id)` and apply a strict tuple-greater-than filter after the decoded cursor.

- [ ] **Step 4: Implement integration response schemas**

Define:

```python
class SupplierIntegrationView(BaseModel):
    supplier_id: str
    supplier_code: str
    supplier_name: str
    status: str
    updated_at: datetime


class SupplierSkuIntegrationView(BaseModel):
    supplier_sku_id: str
    supplier_sku_code: str
    brand_id: str
    brand_name: str
    product_name: str
    model: str | None
    manufacturer_part_number: str | None
    barcode: str | None
    commercial_mode: str
    status: str
    updated_at: datetime
```

Paginated responses contain `items` and nullable `next_cursor`.

- [ ] **Step 5: Implement and register read-only integration routes**

Return only Supplier Network IDs and domain fields; never accept or persist `client_sku_id` in list/detail routes. Supplier SKU rows derive `commercial_mode` from the current active cooperation for `(supplier_id, brand_id)`. Missing active cooperation excludes the SKU from the active list unless the caller explicitly requests `include_inactive=true`.

- [ ] **Step 6: Run tests and commit**

Run: `./start.sh test`

Expected: PASS for scope isolation, pagination, updated-since, and tenant-safe resource traversal.

```bash
git add app/api/routes/integrations.py app/services/integration_pagination.py app/api/router.py app/schemas/integration.py tests/conftest.py tests/test_integrations.py
git commit -m "feat: expose generic supplier catalog API"
```

### Task 6: Implement Mode-A Current Cost Lookup

**Files:**
- Modify: `app/services/catalog.py`
- Modify: `app/api/routes/integrations.py`
- Modify: `app/schemas/integration.py`
- Modify: `app/web/assets/common.js`
- Modify: `tests/test_integrations.py`

**Interfaces:**
- Consumes: Task 4 `CostReader`, Task 5 integration routes, and the current Brand/cooperation/SKU/Offer relations.
- Produces: `resolve_current_sku_cost(db, supplier_id, supplier_sku_id) -> CurrentSkuCost`.
- Produces: single and batch current-cost endpoints.

- [ ] **Step 1: Write failing single-cost behavior tests**

Test `GET /api/integrations/v1/suppliers/{supplier_id}/skus/{supplier_sku_id}/cost` for:

- active mode A SKU returns exact decimal string, currency, and Offer `updated_at` as `cost_updated_at`;
- mode B and mode C return `NOT_SELF_PURCHASE`;
- inactive supplier returns `SUPPLIER_INACTIVE`;
- inactive SKU returns `SKU_INACTIVE`;
- mismatched supplier/SKU returns `SKU_SUPPLIER_MISMATCH`;
- missing or non-active Offer returns `COST_PRICE_MISSING`;
- a token without `supplier-costs:read` returns 403.

- [ ] **Step 2: Write failing batch behavior tests**

POST three lines to `/api/integrations/v1/sku-costs/query`: one valid, one mode B, and one mismatched supplier. Assert HTTP 200, preserved input order, unchanged `client_sku_id`, one `OK`, two independent `ERROR` results, and no `client_sku_id` persisted in the database or event payload.

- [ ] **Step 3: Run tests and verify failures**

Run: `./start.sh test`

Expected: FAIL because cost schemas, service, and endpoints do not exist.

- [ ] **Step 4: Implement deterministic cost resolution**

Add:

```python
@dataclass(frozen=True)
class CurrentSkuCost:
    supplier_id: str
    supplier_sku_id: str
    supplier_sku_code: str
    cost_price: Decimal
    currency: str
    cost_updated_at: datetime


class SkuCostError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def resolve_current_sku_cost(
    db: Session,
    *,
    supplier_id: str,
    supplier_sku_id: str,
) -> CurrentSkuCost:
    supplier = db.get(Organization, supplier_id)
    if (
        supplier is None
        or supplier.organization_type != OrganizationType.SUPPLIER.value
    ):
        raise SkuCostError("SUPPLIER_NOT_FOUND", "供应商不存在")
    if not supplier.is_active:
        raise SkuCostError("SUPPLIER_INACTIVE", "供应商已停用")

    supplier_sku = db.get(SupplierSku, supplier_sku_id)
    if supplier_sku is None:
        raise SkuCostError("SKU_NOT_FOUND", "Supplier SKU 不存在")
    if supplier_sku.supplier_id != supplier_id:
        raise SkuCostError(
            "SKU_SUPPLIER_MISMATCH", "Supplier SKU 不属于该供应商"
        )
    if supplier_sku.status != CatalogStatus.ACTIVE.value:
        raise SkuCostError("SKU_INACTIVE", "Supplier SKU 已停用")

    cooperation = db.scalar(
        select(SupplierBrandCooperation).where(
            SupplierBrandCooperation.supplier_id == supplier_id,
            SupplierBrandCooperation.brand_id == supplier_sku.brand_id,
            SupplierBrandCooperation.status == CatalogStatus.ACTIVE.value,
        )
    )
    if cooperation is None:
        raise SkuCostError(
            "BRAND_COOPERATION_INACTIVE", "品牌合作关系未启用"
        )
    if cooperation.commercial_mode != CommercialMode.SELF_PURCHASE.value:
        raise SkuCostError(
            "NOT_SELF_PURCHASE", "该货号所属品牌不是自营采购模式"
        )

    offer = db.scalar(
        select(SupplierOffer).where(
            SupplierOffer.supplier_sku_id == supplier_sku_id,
            SupplierOffer.status == OfferStatus.ACTIVE.value,
        )
    )
    if offer is None or offer.price is None:
        raise SkuCostError("COST_PRICE_MISSING", "当前成本价不存在")

    return CurrentSkuCost(
        supplier_id=supplier_id,
        supplier_sku_id=supplier_sku_id,
        supplier_sku_code=supplier_sku.supplier_sku_code,
        cost_price=offer.price,
        currency=offer.currency,
        cost_updated_at=offer.updated_at,
    )
```

Resolve in the exact validation order from spec section 9. Query the current active cooperation by `SupplierSku.brand_id`, require `SELF_PURCHASE`, and require one active Offer. Do not evaluate quantity, tax, freight, price tiers, or historical dates.

- [ ] **Step 5: Implement single and batch endpoints**

Use these schemas:

```python
class SkuCostQueryItem(BaseModel):
    client_sku_id: str = Field(min_length=1, max_length=200)
    supplier_id: str
    supplier_sku_id: str


class SkuCostBatchRequest(BaseModel):
    items: list[SkuCostQueryItem] = Field(min_length=1, max_length=500)
```

Single-resource business errors use HTTP 404 for missing entities and HTTP 409 for inactive/mode/cost-state conflicts. For example, mode mismatch returns `detail = {"code": "NOT_SELF_PURCHASE", "message": "该货号所属品牌不是自营采购模式"}`. Batch requests return HTTP 200 and one `OK` or `ERROR` object per input row.

Record one aggregate `INTEGRATION_SKU_COSTS_QUERIED` event per request with Integration Client ID, result counts, and no cost values, token, or `client_sku_id`.

- [ ] **Step 6: Run tests and commit**

Run: `./start.sh test`

Expected: PASS for all single/batch cost cases and unchanged earlier API behavior.

```bash
git add app/services/catalog.py app/api/routes/integrations.py app/schemas/integration.py app/web/assets/common.js tests/test_integrations.py
git commit -m "feat: expose current supplier SKU costs"
```

### Task 6A: Enforce Integration Client Rate Limits

**Files:**
- Create: `app/core/integration_rate_limit.py`
- Modify: `app/core/config.py`
- Modify: `app/api/integration_deps.py`
- Modify: `app/api/routes/integrations.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Create: `tests/test_integration_rate_limit.py`
- Modify: `tests/test_integrations.py`

**Interfaces:**
- Consumes: Task 4 authenticated Integration Client identity and Task 6 cost audit middleware.
- Produces: per-client fixed-window request limiting for every `/api/integrations/v1` route.
- Produces: HTTP 429 responses with integer `Retry-After` seconds.

- [ ] **Step 1: Write failing limiter unit tests**

Use an injected monotonic clock. Assert that one client can consume the configured request count, the next request is rejected with a ceiling-rounded positive retry delay, a different client has an independent window, and the first client can call again after the window expires.

- [ ] **Step 2: Write failing integration behavior tests**

Temporarily install a low-limit limiter and assert:

- authenticated integration calls return 429 after the configured count and include `Retry-After`;
- all integration resource and cost scopes share the same per-client budget;
- different Integration Clients have independent budgets;
- ordinary web/session endpoints are not rate limited;
- a rate-limited cost request writes exactly one redacted cost-query audit event with the caller `X-Request-ID` and zero results/one error;
- invalid bearer credentials still return 401 and never receive a rate-limit identity;
- advancing the injected clock reopens the window.

- [ ] **Step 3: Run tests and verify RED**

Run the focused unit and integration tests. Expected: FAIL because the limiter and 429 wiring do not exist.

- [ ] **Step 4: Implement a bounded, thread-safe fixed-window limiter**

Add configurable positive settings `integration_rate_limit_requests` (default `600`) and `integration_rate_limit_window_seconds` (default `60`). Implement an in-process limiter keyed only by the authenticated Integration Client ID, protected by a lock and using monotonic time. Remove expired client windows opportunistically so the key map cannot grow without bound. Return a ceiling-rounded positive `Retry-After` value without persisting bearer tokens or request bodies.

The deployed runtime currently starts one Uvicorn worker, so an in-process budget is authoritative for the supported topology. Task 8 must document that multi-worker or multi-replica deployments require a shared limiter at the gateway or data-store layer.

- [ ] **Step 5: Enforce once per authenticated integration request**

After authentication identifies the client, set the principal on request state, enforce the limiter before scope authorization, and mark the request as checked so the Task 6 cost pre-authentication and the route dependency cannot consume twice. For a cost request rejected before entering FastAPI body parsing, send the same 429 JSON/headers from the pure-ASGI layer and let its existing post-request audit hook record exactly one event. Unauthenticated clients remain actorless and are not assigned a budget.

- [ ] **Step 6: Expose deployment configuration and verify**

Pass both settings through `docker-compose.yml` and list them in `.env.example`. Run focused tests, `./start.sh test`, compile checks, Compose validation, and `git diff --check` before committing.

### Task 7: Update Supplier Workbench Semantics and Contract Legacy Columns

**Files:**
- Create: `migrations/versions/cc83f7e534a1_finish_supplier_catalog_migration.py`
- Modify: `app/models/entities.py`
- Modify: `app/api/routes/products.py`
- Modify: `app/api/routes/offers.py`
- Modify: `app/api/routes/imports.py`
- Modify: `app/schemas/product.py`
- Modify: `app/web/pages/app.html`
- Modify: `app/web/assets/app.js`
- Modify: `app/web/assets/styles.css`
- Modify: `tests/test_api.py`
- Modify: `tests/test_catalog.py`
- Modify: `tests/test_supplier_catalog_migration.py`

**Interfaces:**
- Consumes: all new code paths from Tasks 1–6.
- Produces: final schema with non-null `Product.brand_id` and `SupplierOffer.supplier_sku_id`, no legacy `products.brand` or `supplier_offers.supplier_sku` columns.
- Produces: supplier UI that selects assigned brands and labels mode-A price as “成本价”.

- [ ] **Step 1: Add failing final-schema and UI contract tests**

Extend the migration test to upgrade through `cc83f7e534a1` and assert:

```python
assert "brand" not in product_columns
assert product_columns["brand_id"]["nullable"] is False
assert "supplier_sku" not in offer_columns
assert offer_columns["supplier_sku_id"]["nullable"] is False
```

Add API assertions that Product responses still expose display field `brand`, Offer responses expose `supplier_sku_id` and `supplier_sku_code`, and request bodies containing the removed `supplier_sku` field receive 422.

Add UI source assertions that the Product dialog loads assigned brands, mode A Offer fields say “成本价”, and no editable commercial-mode field exists in the supplier page.

- [ ] **Step 2: Run tests and verify expected failures**

Run: `./start.sh test`

Expected: FAIL because legacy columns remain and the supplier UI still uses free-text brand/“采购价” semantics.

- [ ] **Step 3: Implement the contract migration**

Create revision `cc83f7e534a1` with `down_revision = "b742e6d423f0"`. Before altering columns, fail with clear row counts if any Product lacks `brand_id` or any Offer lacks `supplier_sku_id`. Then:

1. make both foreign keys non-null;
2. replace the Product unique constraint with `(created_by_organization_id, brand_id, model, name)`;
3. replace the Offer unique constraint with unique `supplier_sku_id`;
4. drop `products.brand` and `supplier_offers.supplier_sku` plus their indexes.

The downgrade recreates and backfills the display/code strings from `Brand` and `SupplierSku` before removing constraints.

- [ ] **Step 4: Remove transitional dual reads/writes**

Delete all ORM fields and route/import assignments for legacy string columns. Keep API display compatibility by serializing `Brand.name` to response field `brand`; accept only `supplier_sku_code` for new offers.

- [ ] **Step 5: Update the supplier workbench**

Load `/api/supplier-catalog/brand-cooperations` before the Product dialog opens. Replace free-text brand input with a select containing assigned active brands. Display the cooperation label next to each option. On mode A Offer forms and tables, render “成本价”; for other modes retain neutral “供货价”. Show the stable Supplier SKU ID in secondary text without allowing it to be edited.

- [ ] **Step 6: Run tests and commit**

Run: `./start.sh test`

Expected: PASS, including fresh-database migration, historical data preservation, API contract, and frontend source checks.

```bash
git add migrations/versions/cc83f7e534a1_finish_supplier_catalog_migration.py app/models/entities.py app/api/routes/products.py app/api/routes/offers.py app/api/routes/imports.py app/schemas/product.py app/web/pages/app.html app/web/assets/app.js app/web/assets/styles.css tests/test_api.py tests/test_catalog.py tests/test_supplier_catalog_migration.py
git commit -m "refactor: complete stable supplier SKU migration"
```

### Task 8: Verify the Public Contract, Documentation, and Live Migration

**Files:**
- Create: `tests/test_integration_contract.py`
- Modify: `docs/integrations/system-integration-guide.md`
- Modify: `docs/designs/2026-09-08-supplier-brand-sku-integration-design.md`
- Modify: `docs/architecture/overview.md`
- Modify: `docs/architecture/data-dictionary.md`
- Modify: `README.md`
- Modify: `docs/operations/validation.md`

**Interfaces:**
- Consumes: implemented OpenAPI schema and all completed migrations/APIs.
- Produces: documentation whose paths, fields, scopes, modes, and error codes are checked against the running application.

- [ ] **Step 1: Write failing documentation-contract tests**

In `tests/test_integration_contract.py`, read `app.openapi()` and assert all six documented paths exist, Integration endpoints contain no specific-caller naming, `SkuCostQueryItem` contains `client_sku_id` and not caller-specific aliases, and the documented scopes/error codes match constants exported by the application.

Read `docs/integrations/system-integration-guide.md` and assert it contains each implemented path, contains `supplier_network_supplier_id`, `supplier_network_sku_id`, and `client_sku_id`, and contains none of the removed legacy or specific-caller terminology.

- [ ] **Step 2: Run tests and verify documentation drift fails**

Run: `./start.sh test`

Expected: FAIL until the documents and exported constants match the final OpenAPI contract.

- [ ] **Step 3: Update all documentation to implemented status**

Change the guide status from “设计稿，接口尚未实现” to the implemented version. Update architecture and data dictionary entity tables, ownership rules, authentication, generic routes, cost semantics, and the verified test count. Keep the guide caller-neutral.

- [ ] **Step 4: Run complete automated verification**

Run:

```bash
./start.sh test
bash -n start.sh
docker compose -f docker-compose.yml config --quiet
docker compose -p supplier-tests -f docker-compose.test.yml config --quiet
git diff --check
```

Expected: every Python and JavaScript test passes, Compose configurations validate, shell syntax passes, and no whitespace errors remain. Verify the separate `supplier-tests` project leaves no containers, networks, or volumes.

- [ ] **Step 5: Back up and migrate the live PostgreSQL data**

Create a custom-format `pg_dump` backup outside the repository, record its SHA-256, then run the default command:

```bash
./start.sh
```

Expected: the app and database become healthy; Alembic reports `cc83f7e534a1 (head)`; PostgreSQL `SHOW port` returns `6432`.

- [ ] **Step 6: Reconcile live records and exercise the generic API**

Compare pre/post counts and IDs for organizations, users, supplier profiles, products, offers, inventory snapshots, import jobs, applications, and event logs. Confirm every existing Offer has one Supplier SKU and every current product has a Brand.

Create a temporary Integration Client through the platform API, call supplier/brand/SKU listing and both cost endpoints, verify mode A returns the current cost, revoke the client, and verify the token immediately receives 401. Do not include plaintext credentials or tokens in the handoff.

- [ ] **Step 7: Commit verified documentation and contract checks**

```bash
git add tests/test_integration_contract.py docs/integrations/system-integration-guide.md docs/designs/2026-09-08-supplier-brand-sku-integration-design.md docs/architecture/overview.md docs/architecture/data-dictionary.md README.md docs/operations/validation.md
git commit -m "docs: publish system integration contract"
```

- [ ] **Step 8: Final review**

Run `git status --short` and inspect every remaining path. Confirm no unrelated user changes were staged or committed. Report migration backup path/checksum, test totals, live health, PostgreSQL port, and any intentionally uncommitted pre-existing work.
