# Supplier ERP and Unified Admin Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move read-only ERP API credentials to supplier ownership, remove operator API access, and reorganize the admin UI into consistent supplier, operator, cooperation, and platform management sections.

**Architecture:** Keep `IntegrationClient` as the shared secret-safe credential record, but replace the operator-owned type with a supplier-owned type and enforce tenant scope in both session management APIs and Bearer-token data queries. Put credential lifecycle helpers in a focused service used by admin and supplier routers; keep platform tokens global, supplier tokens tenant-bound, and cooperation UUIDs authentication-neutral. Restructure only the affected HTML/JavaScript views and preserve existing route hashes where possible.

**Tech Stack:** FastAPI, SQLAlchemy 2, PostgreSQL 16, Alembic, Pydantic 2, server-rendered HTML, vanilla JavaScript, Node test runner, pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-supplier-erp-admin-management-design.md`

## Global Constraints

- ERP API access is read-only in this release; add no integration write endpoint.
- A `SYSTEM` credential has no owner and retains platform-wide reads.
- A `SUPPLIER` credential is owned by one active supplier organization and reads only that organization's data.
- Operators have no credential management UI, session API, or valid Bearer credential type.
- Delete every existing `OPERATOR` integration client during upgrade, as explicitly requested by the user.
- Never return or log plaintext tokens except in the one-time create or rotate response; those responses use `Cache-Control: no-store`.
- Cross-organization credential and resource access returns 404 without revealing ownership.
- User-facing copy says “合作绑定 UUID”; the `erp_bindings` table name stays unchanged.
- Pagination controls support 20, 50, 100, and 200 rows.
- Preserve the untracked root file `image copy.png`.

---

### Task 1: Replace operator credentials with supplier-owned credentials in the data model

**Files:**
- Create: `migrations/versions/6f4a2b8c9d10_replace_operator_clients_with_supplier_clients.py`
- Create: `tests/test_supplier_integration_client_migration.py`
- Modify: `app/models/entities.py:IntegrationClientType, IntegrationClient.__table_args__`
- Modify: `tests/test_roles.py`

**Interfaces:**
- Produces: `IntegrationClientType.SYSTEM` and `IntegrationClientType.SUPPLIER`.
- Produces: database constraint `ck_integration_client_owner` allowing `(SYSTEM, NULL)` or `(SUPPLIER, non-NULL)`.
- Consumes: migration head `f3b8a2197c41`.

- [ ] **Step 1: Write the failing migration and enum tests**

Create a migration test that upgrades a temporary database from `f3b8a2197c41`, seeds one `SYSTEM` client and one `OPERATOR` client, and verifies the operator row is deleted while the system row remains:

```python
PREVIOUS_REVISION = "f3b8a2197c41"
SUPPLIER_CLIENT_REVISION = "6f4a2b8c9d10"

def test_supplier_client_migration_deletes_operator_clients_and_replaces_constraint():
    with temporary_postgresql_database("supplier_clients") as migration_url:
        database_name = migration_url.database
        assert database_name is not None
        run_migrations(migration_url, PREVIOUS_REVISION)
        with connect(migration_url, database_name) as connection:
            connection.execute(
                "INSERT INTO organizations (id, code, name, organization_type, is_active, created_at, updated_at) "
                "VALUES ('supplier-owner', 'SUP-OWNER', '供应商', 'SUPPLIER', true, now(), now())"
            )
            connection.execute(
                "INSERT INTO integration_clients "
                "(id, name, client_type, owner_organization_id, token_prefix, token_hash, scopes, is_active) VALUES "
                "('system-client', 'System', 'SYSTEM', NULL, 'm1i_system00', 'hash', '[]', true), "
                "('operator-client', 'Operator', 'OPERATOR', 'supplier-owner', 'm1i_operatr0', 'hash', '[]', true)"
            )
        run_migrations(migration_url, SUPPLIER_CLIENT_REVISION)
        with connect(migration_url, database_name) as connection:
            assert connection.execute(
                "SELECT id FROM integration_clients ORDER BY id"
            ).fetchall() == [("system-client",)]
            connection.execute(
                "INSERT INTO integration_clients "
                "(id, name, client_type, owner_organization_id, token_prefix, token_hash, scopes, is_active) "
                "VALUES ('supplier-client', 'Supplier', 'SUPPLIER', 'supplier-owner', "
                "'m1i_supplie0', 'hash', '[]', true)"
            )
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "INSERT INTO integration_clients "
                    "(id, name, client_type, owner_organization_id, token_prefix, token_hash, scopes, is_active) "
                    "VALUES ('invalid-client', 'Invalid', 'SUPPLIER', NULL, "
                    "'m1i_invalid0', 'hash', '[]', true)"
                )
```

Update `tests/test_roles.py` to assert `IntegrationClientType.SUPPLIER.value == "SUPPLIER"` and that `OPERATOR` is no longer a member.

- [ ] **Step 2: Run the tests and verify they fail for the missing revision and enum**

Run:

```bash
docker compose -p supplier-tests -f docker-compose.test.yml build test
docker compose -p supplier-tests -f docker-compose.test.yml up -d --wait test-db
docker compose -p supplier-tests -f docker-compose.test.yml run --rm --no-deps test \
  pytest -q tests/test_supplier_integration_client_migration.py tests/test_roles.py
```

Expected: FAIL because revision `6f4a2b8c9d10` and `IntegrationClientType.SUPPLIER` do not exist.

- [ ] **Step 3: Implement the enum and Alembic migration**

Use this model shape:

```python
class IntegrationClientType(str, Enum):
    SYSTEM = "SYSTEM"
    SUPPLIER = "SUPPLIER"

__table_args__ = (
    CheckConstraint(
        "(client_type = 'SYSTEM' AND owner_organization_id IS NULL) OR "
        "(client_type = 'SUPPLIER' AND owner_organization_id IS NOT NULL)",
        name="ck_integration_client_owner",
    ),
)
```

The migration upgrade must execute the destructive operation before replacing the constraint:

```python
def upgrade() -> None:
    op.execute("DELETE FROM integration_clients WHERE client_type = 'OPERATOR'")
    op.drop_constraint("ck_integration_client_owner", "integration_clients", type_="check")
    op.create_check_constraint(
        "ck_integration_client_owner",
        "integration_clients",
        "(client_type = 'SYSTEM' AND owner_organization_id IS NULL) OR "
        "(client_type = 'SUPPLIER' AND owner_organization_id IS NOT NULL)",
    )
```

The downgrade must delete `SUPPLIER` clients before restoring the old `SYSTEM`/`OPERATOR` constraint. Add a module docstring stating that deleted credentials cannot be reconstructed in either direction.

- [ ] **Step 4: Run the migration and model tests**

Run the command from Step 2.

Expected: PASS; invalid owner combinations raise `CheckViolation`.

- [ ] **Step 5: Commit the data model change**

```bash
git add migrations/versions/6f4a2b8c9d10_replace_operator_clients_with_supplier_clients.py \
  app/models/entities.py tests/test_supplier_integration_client_migration.py tests/test_roles.py
git commit -m "feat: assign integration credentials to suppliers"
```

---

### Task 2: Add supplier credential lifecycle APIs and restrict admin lifecycle actions

**Files:**
- Create: `app/services/integration_clients.py`
- Create: `app/api/routes/supplier_integrations.py`
- Create: `tests/test_supplier_integration_clients.py`
- Modify: `app/api/router.py`
- Modify: `app/api/routes/admin_catalog.py`
- Modify: `tests/test_admin.py`
- Modify: `tests/test_integration_auth.py`

**Interfaces:**
- Produces: `create_client_with_unique_token(db, *, name, scopes, expires_at, client_type, owner_organization_id) -> tuple[IntegrationClient, str]` in `app.services.integration_clients`.
- Produces: `rotate_client_with_unique_token(db, client) -> str`, `integration_client_view(client)`, and `integration_client_credential(client, token)` in the same service.
- Produces: supplier session routes under `/api/supplier/integration-clients`.
- Consumes: `SupplierUser`, `IntegrationClientCreate`, `IntegrationClientPage`, and `IntegrationClientType.SUPPLIER`.

- [ ] **Step 1: Write failing supplier ownership and one-time token tests**

Add tests that log in as the seeded supplier and create a credential:

```python
def test_supplier_creates_lists_rotates_and_revokes_only_its_credential(client):
    login(client, SUPPLIER_EMAIL, SUPPLIER_PASSWORD)
    created_response = client.post(
        "/api/supplier/integration-clients",
        json={"name": "自有 ERP", "scopes": ["supplier-skus:read", "supplier-costs:read"]},
    )
    assert created_response.status_code == 201
    assert created_response.headers["cache-control"] == "no-store"
    created = created_response.json()
    assert created["client_type"] == "SUPPLIER"
    assert created["owner_organization_id"] == supplier_organization_id()
    assert created["token"].startswith("m1i_")

    listed = client.get("/api/supplier/integration-clients?page=1&page_size=20").json()
    assert listed["items"][0]["id"] == created["id"]
    assert "token" not in listed["items"][0]

    rotated = client.post(
        f"/api/supplier/integration-clients/{created['id']}/rotate"
    )
    assert rotated.status_code == 200
    assert rotated.headers["cache-control"] == "no-store"
    assert rotated.json()["token"] != created["token"]

    revoked = client.post(
        f"/api/supplier/integration-clients/{created['id']}/revoke"
    )
    assert revoked.status_code == 200
    assert revoked.json()["is_active"] is False
```

Seed a second supplier organization and credential directly, then assert all three supplier management actions return 404 for the first supplier. Assert an operator session receives 403 on the supplier route.

Add an admin test asserting rotate on a supplier-owned client returns 404 or 409, while admin revoke succeeds without returning a token.

- [ ] **Step 2: Run the focused API tests and verify route failures**

Run:

```bash
docker compose -p supplier-tests -f docker-compose.test.yml build test
docker compose -p supplier-tests -f docker-compose.test.yml run --rm --no-deps test \
  pytest -q tests/test_supplier_integration_clients.py tests/test_admin.py tests/test_integration_auth.py
```

Expected: FAIL because supplier routes and shared service do not exist, and admin rotation is not type-restricted.

- [ ] **Step 3: Extract secret-safe credential lifecycle helpers**

Move `TOKEN_PREFIX_RETRY_LIMIT`, collision detection, view/credential serialization, create, and rotate helpers from `admin_catalog.py` to `app/services/integration_clients.py`. Preserve nested-transaction collision handling and the existing 503 behavior. Update all imports and monkeypatch targets in tests to use the service module.

- [ ] **Step 4: Implement supplier credential routes**

Create a focused router:

```python
router = APIRouter(prefix="/supplier/integration-clients", tags=["供应商 ERP 接入"])

def owned_supplier_client(db: DbSession, client_id: str, organization_id: str) -> IntegrationClient:
    client = db.scalar(select(IntegrationClient).where(
        IntegrationClient.id == client_id,
        IntegrationClient.client_type == IntegrationClientType.SUPPLIER.value,
        IntegrationClient.owner_organization_id == organization_id,
    ))
    if client is None:
        raise HTTPException(status_code=404, detail="凭证不存在或不可访问")
    return client
```

Implement list/create/rotate/revoke with the existing page sizes `{20, 50, 100, 200}`. Derive `owner_organization_id` only from `user.organization_id`; normalize name and scopes exactly once; write `SUPPLIER_INTEGRATION_CLIENT_CREATED`, `SUPPLIER_INTEGRATION_CLIENT_ROTATED`, and `SUPPLIER_INTEGRATION_CLIENT_REVOKED` events without plaintext.

- [ ] **Step 5: Restrict admin create/rotate and retain revoke oversight**

Make admin creation always pass `client_type=SYSTEM` and `owner_organization_id=None`. Change the admin rotation lookup to require `SYSTEM`; keep list visibility for both types and allow admin revoke for any client. Do not expose a token when revoking supplier credentials.

- [ ] **Step 6: Register the supplier router and run focused tests**

Add `supplier_integrations.router` to `app/api/router.py`, then run the Step 2 command.

Expected: PASS with no plaintext present in list responses, storage, events, or revoke responses.

- [ ] **Step 7: Commit the lifecycle API change**

```bash
git add app/services/integration_clients.py app/api/routes/supplier_integrations.py \
  app/api/router.py app/api/routes/admin_catalog.py tests/test_supplier_integration_clients.py \
  tests/test_admin.py tests/test_integration_auth.py
git commit -m "feat: add supplier ERP credentials"
```

---

### Task 3: Enforce supplier tenant scope on every integration read

**Files:**
- Modify: `app/api/integration_deps.py`
- Modify: `app/api/routes/integrations.py`
- Create: `tests/test_supplier_integration_access.py`
- Delete: `tests/test_operator_integration_access.py`
- Modify: `tests/test_integrations.py`
- Modify: `tests/test_integration_contract.py`

**Interfaces:**
- Produces: `supplier_scope(principal: AuthenticatedIntegrationClient) -> str | None` where `None` means platform scope.
- Produces: `require_permitted_supplier(principal, supplier_id) -> None` returning 404 on tenant mismatch.
- Consumes: supplier-owned Bearer credentials from Task 2.

- [ ] **Step 1: Write failing cross-supplier isolation tests**

Create one supplier-owned credential with all four read scopes and two approved suppliers. Assert literal outcomes:

```python
def test_supplier_token_lists_and_reads_only_its_owner_supplier(client, supplier_token, catalog):
    headers = {"Authorization": f"Bearer {supplier_token['token']}"}
    listed = client.get("/api/integrations/v1/suppliers", headers=headers)
    assert [item["supplier_id"] for item in listed.json()["items"]] == [
        supplier_token["owner_organization_id"]
    ]
    assert client.get(
        f"/api/integrations/v1/suppliers/{catalog['other_supplier_id']}", headers=headers
    ).status_code == 404
    for resource in ("brands", "skus"):
        assert client.get(
            f"/api/integrations/v1/suppliers/{catalog['other_supplier_id']}/{resource}",
            headers=headers,
        ).status_code == 404
```

Add cost tests for both single and batch endpoints. A foreign supplier item in a batch must return `status="ERROR"` and `error_code="SUPPLIER_NOT_FOUND"`; an owned item follows existing cost rules. Verify the same cursor cannot escape supplier scope.

Add authentication tests asserting a supplier token fails with 401 when its owner organization is inactive or is not type `SUPPLIER`. Assert a seeded old `OPERATOR` client cannot authenticate.

- [ ] **Step 2: Run isolation tests and verify current global access fails them**

Run:

```bash
docker compose -p supplier-tests -f docker-compose.test.yml build test
docker compose -p supplier-tests -f docker-compose.test.yml run --rm --no-deps test \
  pytest -q tests/test_supplier_integration_access.py tests/test_integrations.py \
  tests/test_integration_auth.py tests/test_integration_contract.py
```

Expected: FAIL because a supplier-owned principal is not yet restricted to its owner.

- [ ] **Step 3: Authenticate only system and active supplier principals**

In `authenticate_integration_client`, accept `SYSTEM` only with no owner. For `SUPPLIER`, load the owner and require `owner.is_active` and `owner.organization_type == OrganizationType.SUPPLIER.value`. Reject every other `client_type` through the existing constant-time invalid credential path.

- [ ] **Step 4: Add reusable tenant-boundary helpers**

Replace operator binding checks with:

```python
def supplier_scope(principal: AuthenticatedIntegrationClient) -> str | None:
    if principal.client_type == IntegrationClientType.SYSTEM.value:
        return None
    if principal.client_type == IntegrationClientType.SUPPLIER.value:
        return principal.owner_organization_id
    raise unauthorized()

def require_permitted_supplier(
    principal: AuthenticatedIntegrationClient, supplier_id: str
) -> None:
    scoped_id = supplier_scope(principal)
    if scoped_id is not None and scoped_id != supplier_id:
        raise supplier_not_found()
```

Use one `supplier_not_found()` factory so detail, brand, SKU, single-cost, and batch paths return the established error body consistently.

- [ ] **Step 5: Apply scope to list, detail, child resources, costs, and cursors**

Pass the principal into `list_suppliers` and filter `Organization.id` when `supplier_scope(principal)` is non-null. Bind supplier-list cursor snapshot and encoding to that scoped ID so a platform cursor is not reusable in supplier scope. Call `require_permitted_supplier` before resource lookup on every route containing `{supplier_id}` and before each batch cost item is resolved.

Remove `ErpBinding` and `OperatorSupplierCooperation` from integration authorization logic. The cooperation binding UUID must have no effect on Bearer access.

- [ ] **Step 6: Run focused integration tests**

Run the Step 2 command.

Expected: PASS; existing `SYSTEM` integration tests retain platform-wide results and supplier tests see one tenant only.

- [ ] **Step 7: Commit tenant scoping**

```bash
git add app/api/integration_deps.py app/api/routes/integrations.py \
  tests/test_supplier_integration_access.py tests/test_integrations.py \
  tests/test_integration_auth.py tests/test_integration_contract.py
git rm tests/test_operator_integration_access.py
git commit -m "fix: isolate supplier integration reads"
```

---

### Task 4: Add the supplier ERP page and remove operator credential UI

**Files:**
- Create: `app/web/assets/supplier-integration.js`
- Create: `tests/test_supplier_integration.js`
- Modify: `app/web/pages/app.html`
- Modify: `app/web/assets/app.js`
- Modify: `app/web/pages/operator.html`
- Modify: `app/web/assets/operator.js`
- Modify: `app/web/assets/styles.css`
- Modify: `docker-compose.test.yml`
- Modify: `tests/test_public_pages.py`

**Interfaces:**
- Consumes: `/api/supplier/integration-clients` lifecycle API from Task 2.
- Produces: supplier workspace hash route `#erp-integration`.
- Removes: operator workspace hash route `#integration` and all `/api/operator/integration-clients` calls.

- [ ] **Step 1: Write failing page structure and token lifecycle tests**

In `tests/test_public_pages.py`, assert supplier HTML contains `data-view="erp-integration"`, `id="supplier-client-form"`, and `id="supplier-client-pagination"`. Assert operator HTML contains none of `data-view="integration"`, `operator-client-form`, `operator-token-dialog`, or the text `集成凭证`. Assert both workspaces contain `合作绑定 UUID` and no user-facing `ERP 绑定`.

Create a Node harness for `supplier-integration.js` and test:

```javascript
test("supplier credential creation shows plaintext once and list never renders it", async () => {
  const harness = supplierIntegrationHarness({
    api: async (path, options) => path === "/api/supplier/integration-clients"
      && options?.method === "POST"
      ? { id: "client-a", token: "m1i_secret", token_prefix: "m1i_secret00", scopes: ["supplier-skus:read"], is_active: true }
      : { items: [], total: 0, page: 1, page_size: 50 },
  });
  await harness.submit();
  assert.equal(harness.tokenValue.textContent, "m1i_secret");
  harness.dialog.dispatch("close");
  assert.equal(harness.tokenValue.textContent, "");
  assert.doesNotMatch(harness.table.innerHTML, /m1i_secret/);
});
```

Also test rotate clears the previous token before the request, revoke asks for confirmation, pagination sends the selected page size, and current request failures show a toast.

- [ ] **Step 2: Run page and Node tests and verify missing UI failures**

Run:

```bash
docker compose -p supplier-tests -f docker-compose.test.yml build test
docker compose -p supplier-tests -f docker-compose.test.yml run --rm --no-deps test \
  pytest -q tests/test_public_pages.py
docker run --rm -v "$PWD:/workspace:ro" -w /workspace node:22-alpine \
  node --test tests/test_supplier_integration.js
```

Expected: FAIL because supplier ERP markup/script do not exist and operator credential markup still exists.

- [ ] **Step 3: Build the supplier ERP access view**

Add a sidebar entry under “账号与接入” and a `data-view="erp-integration"` section containing the read-only API base URL `/api/integrations/v1`, Bearer authentication guidance, the four existing read scopes, a create form, credential table, and unified pagination. Use labels “ERP 接入” and “只读 API 凭证”.

Implement `supplier-integration.js` as a focused module with `loadSupplierClients`, `renderSupplierClients`, `showSupplierToken`, `clearSupplierToken`, create, rotate, and revoke handlers. Use `Matrix.escapeHtml`, `Matrix.statusBadge`, and `MatrixPagination.render`; never place a returned plaintext token into table state.

- [ ] **Step 4: Remove operator credential management and rename binding copy**

Delete credential state, rendering, API calls, form handlers, and token dialog behavior from `operator.js`. Remove the credential page and dialog from `operator.html`. Rename the operator route/title from `bindings: ["ERP 绑定", ...]` to `bindings: ["合作绑定", ...]` and update table copy to “合作绑定 UUID”. Update supplier cooperation and admin cooperation copy to the same terminology.

- [ ] **Step 5: Register frontend syntax and run tests**

Add `node --check app/web/assets/supplier-integration.js` and `node --test tests/test_supplier_integration.js` to `docker-compose.test.yml`. Run the Step 2 commands.

Expected: PASS; token DOM content is cleared on every close path and no operator credential controls remain.

- [ ] **Step 6: Commit workspace UI changes**

```bash
git add app/web/pages/app.html app/web/assets/app.js app/web/assets/supplier-integration.js \
  app/web/pages/operator.html app/web/assets/operator.js app/web/assets/styles.css \
  docker-compose.test.yml tests/test_supplier_integration.js tests/test_public_pages.py
git commit -m "feat: add supplier ERP access workspace"
```

---

### Task 5: Unify admin supplier/operator management and extract cooperation management

**Files:**
- Modify: `app/web/pages/admin.html`
- Modify: `app/web/assets/admin.js`
- Modify: `app/web/assets/admin-operator.js`
- Modify: `app/web/assets/styles.css`
- Modify: `app/api/routes/admin.py`
- Modify: `app/schemas/operator.py`
- Modify: `tests/test_admin.py`
- Modify: `tests/test_admin_catalog.js`
- Modify: `tests/test_public_pages.py`

**Interfaces:**
- Produces: `GET /api/admin/operator-summary -> OperatorManagementSummary`.
- Extends: operator application list with `keyword` and `status_filter` query parameters.
- Extends: operator account list with `keyword` query parameter.
- Consumes: admin credential rules from Task 2.

- [ ] **Step 1: Write failing navigation, summary, filter, and credential action tests**

Assert admin HTML contains these section labels in order: `供应商管理`, `运营商管理`, `合作管理`, `平台管理`. Assert `data-route="operator-cooperations"` occurs under the cooperation section rather than the operator section. Assert the navigation and view say `平台 API 凭证`.

Add API tests:

```python
def test_operator_admin_summary_and_filters(client):
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    summary = client.get("/api/admin/operator-summary")
    assert summary.status_code == 200
    assert set(summary.json()) == {
        "pending_applications", "approved_applications", "active_operators"
    }
    pending = client.get(
        "/api/admin/operator-applications?status_filter=PENDING&keyword=联系人"
    )
    assert pending.status_code == 200
    assert all(item["status"] == "PENDING" for item in pending.json()["items"])
    accounts = client.get("/api/admin/operators?keyword=运营")
    assert accounts.status_code == 200
```

Add Node assertions that supplier and operator application views both render metric cards, `.toolbar`, `.data-card`, a result count, and unified pagination; operator list search resets to page 1; cooperation rendering remains independently pageable. Test that supplier-owned credential rows show revoke but no rotate action, while `SYSTEM` rows show both.

- [ ] **Step 2: Run admin tests and verify missing summary/structure failures**

Run:

```bash
docker compose -p supplier-tests -f docker-compose.test.yml build test
docker compose -p supplier-tests -f docker-compose.test.yml run --rm --no-deps test \
  pytest -q tests/test_admin.py tests/test_public_pages.py
docker run --rm -v "$PWD:/workspace:ro" -w /workspace node:22-alpine \
  node --test tests/test_admin_catalog.js
```

Expected: FAIL because the new grouping, summary route, filters, and type-specific credential actions are absent.

- [ ] **Step 3: Implement operator summary and server filters**

Add:

```python
class OperatorManagementSummary(BaseModel):
    pending_applications: int
    approved_applications: int
    active_operators: int
```

Implement `/admin/operator-summary` with three `count()` queries. For application keyword matching, search normalized contact name, phone, email, company name, application number, operator type, and ERP name; apply an exact validated status filter. For account keyword matching, search organization name/code, contact name/email/phone, operator type, and ERP name. Apply filters before count, offset, and limit.

- [ ] **Step 4: Reorganize admin navigation and normalize markup**

Move cooperation navigation into its own labeled section. Rename routes without changing their hashes:

```javascript
const adminRoutes = {
  applications: ["供应商入驻申请", "供应网络 / 供应商管理 / 入驻申请"],
  suppliers: ["供应商列表", "供应网络 / 供应商管理 / 供应商列表"],
  "operator-applications": ["运营商入驻申请", "供应网络 / 运营商管理 / 入驻申请"],
  operators: ["运营商列表", "供应网络 / 运营商管理 / 运营商列表"],
  "operator-cooperations": ["合作记录", "供应网络 / 合作管理 / 合作记录"],
  integrations: ["平台 API 凭证", "供应网络 / 平台管理 / 平台 API 凭证"],
  system: ["平台能力", "供应网络 / 平台管理 / 平台能力"],
};
```

Give both application views a three-card metric region, matching view actions, toolbar search/status controls, count text, table wrapper, error/empty states, and unified pagination. Give both organization lists matching search, count, table, empty state, and pagination placement. Keep supplier-specific brand cooperation actions and operator-specific ERP/type fields.

- [ ] **Step 5: Rewrite operator admin UI logic in maintainable form**

Format `admin-operator.js` into named state, query, render, load, and review functions. Use request generations for searchable list loads so an older response cannot overwrite a newer filter. After approval or rejection, refresh the application list, account list, and summary. Catch current request failures and render an explicit table error rather than leaving “正在加载”.

- [ ] **Step 6: Apply platform/supplier credential row actions**

Rename all admin copy to “平台 API 凭证”. In `renderIntegrationClients`, show owner type and organization ID. Render rotate only when `item.client_type === "SYSTEM"` and the credential is usable; render revoke for any active credential. The create form explicitly says it creates a platform-wide `SYSTEM` credential.

- [ ] **Step 7: Run admin API and UI tests**

Run the Step 2 commands.

Expected: PASS; navigation hierarchy, filters, summary totals, request ordering, and type-specific credential actions are protected.

- [ ] **Step 8: Commit admin management changes**

```bash
git add app/web/pages/admin.html app/web/assets/admin.js app/web/assets/admin-operator.js \
  app/web/assets/styles.css app/api/routes/admin.py app/schemas/operator.py \
  tests/test_admin.py tests/test_admin_catalog.js tests/test_public_pages.py
git commit -m "feat: unify supplier and operator administration"
```

---

### Task 6: Update integration documentation and remove operator access claims

**Files:**
- Modify: `docs/integrations/system-integration-guide.md`
- Modify: `README.md`
- Modify: `tests/test_integration_contract.py`

**Interfaces:**
- Documents: platform `SYSTEM` credentials and supplier `SUPPLIER` credentials.
- Removes: operator credential creation and cooperation-bound API access documentation.

- [ ] **Step 1: Write failing contract assertions for the public integration contract**

Update contract tests to require the guide to identify `/app#erp-integration` as the supplier credential entry, state that supplier tokens are read-only and owner-scoped, and call the admin entry “平台 API 凭证”. Assert the guide does not claim `/operator#integration` exists or that a cooperation binding grants API access.

- [ ] **Step 2: Run the contract test and verify old operator wording fails**

Run:

```bash
docker compose -p supplier-tests -f docker-compose.test.yml build test
docker compose -p supplier-tests -f docker-compose.test.yml run --rm --no-deps test \
  pytest -q tests/test_integration_contract.py
```

Expected: FAIL on the existing operator credential instructions.

- [ ] **Step 3: Rewrite credential ownership and examples**

Document these exact concepts:

- Platform administrators create global read-only credentials in `/admin#integrations`.
- Suppliers create organization-scoped read-only credentials in `/app#erp-integration`.
- The same Bearer header format is used for both.
- Supplier credentials see only their own supplier ID and receive 404 for foreign IDs.
- Cooperation binding UUIDs are identifiers, not credentials.
- Operators have no ERP API credential workflow.

Update README navigation and feature descriptions to match.

- [ ] **Step 4: Run contract tests and documentation checks**

Run the Step 2 command plus:

```bash
rg -n "运营商凭证|/operator#integration|ERP 绑定" README.md docs/integrations app/web/pages app/web/assets
```

Expected: tests PASS; search returns no obsolete user-facing access claim. Internal `ErpBinding` class/table references are allowed outside user-facing text.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md docs/integrations/system-integration-guide.md tests/test_integration_contract.py
git commit -m "docs: describe supplier-scoped ERP access"
```

---

### Task 7: Full verification, review, merge, and restart

**Files:**
- Verify all changed files from Tasks 1–6.
- Preserve: `image copy.png`.

**Interfaces:**
- Consumes: completed feature branch based on `main`.
- Produces: reviewed commits merged into `main` and a healthy restarted service.

- [ ] **Step 1: Run static verification**

```bash
git diff --check
python3 -m compileall -q app
node --check app/web/assets/common.js
node --check app/web/assets/admin.js
node --check app/web/assets/admin-operator.js
node --check app/web/assets/app.js
node --check app/web/assets/operator.js
node --check app/web/assets/supplier-integration.js
```

Expected: every command exits 0.

- [ ] **Step 2: Run the complete isolated test suite**

```bash
./start.sh test
```

Expected: backend reaches 100%; all Node tests pass with zero failures.

- [ ] **Step 3: Request independent code review**

Provide the reviewer the base and head SHAs plus these requirements: destructive operator-client migration, supplier ownership isolation, no integration writes, no operator credential route/UI, cooperation UUID neutrality, admin hierarchy/style consistency, one-time token secrecy, and full regression results. Fix every Critical and Important finding with a red-green test cycle, then rerun Steps 1–2.

- [ ] **Step 4: Merge into main as already requested by the user**

From the main repository root:

```bash
git merge --ff-only feat/supplier-erp-admin-management
./start.sh test
```

Expected: fast-forward merge succeeds; merged backend and frontend suites pass.

- [ ] **Step 5: Remove the owned worktree and feature branch**

```bash
git worktree remove .worktrees/supplier-erp-admin-management
git worktree prune
git branch -d feat/supplier-erp-admin-management
```

Expected: only the main worktree remains; `image copy.png` remains untracked and untouched.

- [ ] **Step 6: Restart and smoke-test the service**

```bash
./start.sh restart
./start.sh status
curl -fsS http://127.0.0.1:6790/api/health
curl -fsS -o /dev/null http://127.0.0.1:6790/admin
curl -fsS -o /dev/null http://127.0.0.1:6790/app
curl -fsS -o /dev/null http://127.0.0.1:6790/operator
docker compose exec -T app alembic current
```

Expected: application and database are healthy, all pages return 200, health JSON reports `status: ok`, and Alembic current is `6f4a2b8c9d10 (head)`.

- [ ] **Step 7: Browser smoke-test role boundaries**

Verify as administrator that the four navigation groups and consistent management views render. Verify as supplier that “ERP 接入” can create a one-time token and list only supplier-owned credentials. Verify as operator that no credential entry exists and cooperation screens say “合作绑定 UUID”. Revoke the smoke-test supplier token before handoff.
