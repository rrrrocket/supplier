# 运营商入驻、供应商市场与 ERP 绑定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加经审核入驻的运营商身份、可检索的供应商市场、双方合作流程，以及仅对有效合作开放的 ERP 绑定与集成凭证。

**Architecture:** 在统一组织、用户、会话和审计基础上增加独立运营商域；合作与 ERP 绑定以稳定 UUID 建模，目录公开数据与合作后业务数据分层授权。现有系统集成客户端迁移为 `SYSTEM` 类型并保持原行为，运营商客户端按有效绑定限制品牌、SKU 和成本读取。

**Tech Stack:** Python 3.13、FastAPI 0.128、SQLAlchemy 2、Alembic、PostgreSQL 16、Pydantic 2、原生 HTML/CSS/JavaScript、Node test runner、pytest

**Spec:** `docs/superpowers/specs/2026-09-09-operator-marketplace-design.md`

## Global Constraints

- 运营商申请只有联系人、手机号、邮箱必填，其他申请字段全部选填。
- 供应商目录只展示组织启用且资料状态为 `APPROVED` 的供应商。
- 公开列表始终返回脱敏联系方式；完整联系方式只在已认证运营商查看详情时返回并审计。
- 同一运营商与供应商最多存在一个 `PENDING` 或 `ACTIVE` 合作。
- 业务集成数据只对有效 ERP 绑定开放；系统级集成客户端保持向后兼容。
- token 明文只展示一次，数据库和审计日志不得保存明文。
- 所有列表复用 `app/web/assets/pagination.js` 的统一分页风格。
- 开发、测试、迁移和服务管理统一使用 `./start.sh`。

---

### Task 1: 运营商数据模型与迁移

**Files:**
- Modify: `app/models/entities.py`
- Create: `migrations/versions/e8c4a91d2f70_add_operator_marketplace.py`
- Create: `tests/test_operator_marketplace_migration.py`
- Modify: `tests/test_roles.py`

**Interfaces:**
- Produces: `OrganizationType.OPERATOR`, `UserRole.OPERATOR`, `OperatorApplication`, `OperatorProfile`, `OperatorSupplierCooperation`, `ErpBinding`, `IntegrationClient.client_type`, `IntegrationClient.owner_organization_id`.
- Consumes: `UUIDPrimaryKeyMixin`, `TimestampMixin`, `SupplierStatus`, existing organization/user/client tables.

- [x] **Step 1: Write failing enum and migration tests**

Assert that `OPERATOR` is available in both enums; upgrade a database from `d14f0c6a7e92`; inspect the four new tables, partial active-cooperation unique index, new client columns, foreign keys and defaults; insert an existing-style client and assert it reads as `SYSTEM`; run downgrade and upgrade again.

- [x] **Step 2: Run focused tests and verify failure**

Run: `./start.sh test tests/test_roles.py tests/test_operator_marketplace_migration.py`

Expected: failure because the enum members, models and migration revision do not exist.

- [x] **Step 3: Add exact model contracts**

Add enums `CooperationStatus(PENDING, ACTIVE, REJECTED, TERMINATED)`, `BindingStatus(ACTIVE, INACTIVE)` and `IntegrationClientType(SYSTEM, OPERATOR)`. Define the four entities with fields and transitions from the spec. Add this PostgreSQL partial index to `OperatorSupplierCooperation`:

```python
Index(
    "uq_open_operator_supplier_cooperation",
    "operator_id",
    "supplier_id",
    unique=True,
    postgresql_where=text("status IN ('PENDING', 'ACTIVE')"),
)
```

Extend `IntegrationClient` with nullable `owner_organization_id` and non-null `client_type` defaulting to `SYSTEM`.

- [x] **Step 4: Implement reversible Alembic migration**

Create the new tables and indexes, add the two integration-client columns with server default `SYSTEM`, backfill all existing rows, then keep the default. Add a check constraint requiring an owner for operator clients and no owner for system clients. Downgrade deletes operator clients before removing columns and tables.

- [x] **Step 5: Run focused and full tests**

Run: `./start.sh test`

Expected: all backend and JavaScript tests pass.

- [x] **Step 6: Commit**

```bash
git add app/models/entities.py migrations/versions/e8c4a91d2f70_add_operator_marketplace.py tests/test_roles.py tests/test_operator_marketplace_migration.py
git commit -m "feat: add operator marketplace data model"
```

### Task 2: 运营商公开申请与管理员审核

**Files:**
- Create: `app/schemas/operator.py`
- Create: `app/api/routes/operators.py`
- Modify: `app/api/routes/public.py`
- Modify: `app/api/routes/admin.py`
- Modify: `app/api/router.py`
- Modify: `app/schemas/admin.py`
- Create: `tests/test_operator_onboarding.py`

**Interfaces:**
- Produces: `POST /api/public/operator-applications`, admin list/approve/reject endpoints, `OperatorApplicationCreate`, `OperatorApplicationCreated`, `OperatorApplicationAdminView`.
- Consumes: Task 1 entities, `generate_temporary_password()`, `record_event()` and password hashing.

- [x] **Step 1: Write failing public application tests**

Post only `contact_name`, `phone`, `email` and expect 201 with `OPR-` application number. Parameterize those three missing/invalid fields and expect 422. Post every optional field as absent and assert stored nullable values/empty arrays. Submit a duplicate pending email and expect 409; resubmit after rejection and expect 201.

- [x] **Step 2: Write failing admin review tests**

Assert only platform admins can list/review. Approval creates one active `OPERATOR` organization, one `OperatorProfile`, one `OPERATOR` user, lowercases email and returns the temporary password once. Reject requires pending state and stores notes. Duplicate existing user email returns 409 without partial organization rows.

- [x] **Step 3: Run focused tests and verify failure**

Run: `./start.sh test tests/test_operator_onboarding.py`

Expected: 404 responses and missing schemas.

- [x] **Step 4: Implement schemas and public route**

Use this required-field contract:

```python
class OperatorApplicationCreate(BaseModel):
    contact_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=6, max_length=60)
    email: EmailStr
    company_name: str | None = Field(default=None, max_length=240)
    unified_social_credit_code: str | None = Field(default=None, max_length=40)
    operator_type: str | None = Field(default=None, max_length=80)
    province: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=255)
    erp_name: str | None = Field(default=None, max_length=120)
    sales_channels: list[str] = Field(default_factory=list, max_length=30)
    categories: list[str] = Field(default_factory=list, max_length=30)
    target_markets: list[str] = Field(default_factory=list, max_length=30)
    qualification_files: list[str] = Field(default_factory=list, max_length=20)
    message: str | None = Field(default=None, max_length=2000)
```

Normalize optional blank strings to `None`, list values to unique trimmed entries, and email to lowercase. Record creation without including phone/email in event payload.

- [x] **Step 5: Implement admin approval atomically**

Generate `OPR-<application suffix>` organization code, use company name or `<contact_name>的运营团队` as organization name, create profile/user, update application review fields, and record `OPERATOR_APPLICATION_APPROVED` or `OPERATOR_APPLICATION_REJECTED`. Commit once after all records are flushed.

- [x] **Step 6: Run focused and full tests, then commit**

Run: `./start.sh test`

```bash
git add app/schemas/operator.py app/schemas/admin.py app/api/routes/operators.py app/api/routes/public.py app/api/routes/admin.py app/api/router.py tests/test_operator_onboarding.py
git commit -m "feat: add reviewed operator onboarding"
```

### Task 3: 运营商登录路由、资料与概览 API

**Files:**
- Modify: `app/api/deps.py`
- Modify: `app/api/routes/auth.py`
- Modify: `app/web/assets/common.js`
- Modify: `app/schemas/operator.py`
- Modify: `app/api/routes/operators.py`
- Create: `tests/test_operator_api.py`
- Modify: `tests/test_public_auth.js`

**Interfaces:**
- Produces: `OperatorUser`, `/api/operator/profile`, `/api/operator/dashboard`, `/operator` auth target.
- Consumes: approved operator organization/profile/user from Task 2.

- [x] **Step 1: Write failing role-isolation tests**

Assert a valid operator session is accepted by operator endpoints and rejected by supplier/admin endpoints. Assert mismatched role/type combinations receive 403. Test `/api/auth/me` returns role/type used by the client router.

- [x] **Step 2: Write failing profile/dashboard tests**

Assert operators only read/update their own profile, cannot blank contact fields, and receive counts for available suppliers, pending cooperation requests, active cooperations and active bindings.

- [x] **Step 3: Write failing browser routing tests**

Add Node tests that `OPERATOR` + `OPERATOR` resolves to `/operator` with label `运营商`, while mismatched identities remain unauthenticated.

- [x] **Step 4: Implement dependency and endpoints**

Add `get_current_operator_user()` mirroring the supplier dependency with the operator enum pair. Add profile view/update schemas and aggregate dashboard query. Never accept organization IDs in update payloads.

- [x] **Step 5: Update public auth routing and verify**

Update `publicAuthView()` and `userRoleLabel()` for operators. Run `./start.sh test`, then commit:

```bash
git add app/api/deps.py app/api/routes/auth.py app/api/routes/operators.py app/schemas/operator.py app/web/assets/common.js tests/test_operator_api.py tests/test_public_auth.js
git commit -m "feat: add operator workspace authorization"
```

### Task 4: 可检索供应商目录 API 与隐私边界

**Files:**
- Create: `app/services/supplier_directory.py`
- Create: `app/schemas/directory.py`
- Create: `app/api/routes/directory.py`
- Modify: `app/api/router.py`
- Create: `tests/test_supplier_directory.py`

**Interfaces:**
- Produces: `GET /api/public/suppliers`, `GET /api/public/suppliers/{id}`, `SupplierDirectoryPage`, `SupplierDirectoryDetail`, `mask_phone()`, `mask_email()`.
- Consumes: supplier organizations/profiles/products/offers and optional current session.

- [ ] **Step 1: Write failing eligibility and pagination tests**

Create approved/disabled/pending/suspended suppliers and assert only approved+enabled entries appear. Verify no duplicate card for a multi-category supplier; verify `page`, `page_size`, `total` and 50/100/200 sizes.

- [ ] **Step 2: Write failing filter and privacy tests**

Cover keyword, category, province/city, supplier type, cooperation mode and three capability flags. Assert public list/detail responses contain only masked values. Assert operator detail returns full values and records one `SUPPLIER_CONTACT_VIEWED` event; supplier sessions do not gain full access.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `./start.sh test tests/test_supplier_directory.py`

- [ ] **Step 4: Implement a single reusable base query**

Join product and active-offer count subqueries to eligible supplier organizations. Apply deterministic ordering by `created_at DESC, id DESC`. Keep contact selection server-side: the public serializer receives masked fields, the authenticated operator serializer receives full fields only for detail.

- [ ] **Step 5: Implement filters, routes and audit**

Validate query lengths and supported page sizes. Return 404 for ineligible supplier IDs. Record the contact event only after an operator successfully fetches an eligible detail record.

- [ ] **Step 6: Verify and commit**

Run: `./start.sh test`

```bash
git add app/services/supplier_directory.py app/schemas/directory.py app/api/routes/directory.py app/api/router.py tests/test_supplier_directory.py
git commit -m "feat: add privacy-aware supplier directory"
```

### Task 5: 运营商—供应商合作状态机与 ERP 绑定

**Files:**
- Create: `app/services/operator_cooperation.py`
- Create: `app/schemas/cooperation.py`
- Create: `app/api/routes/operator_cooperations.py`
- Create: `app/api/routes/supplier_operator.py`
- Modify: `app/api/router.py`
- Create: `tests/test_operator_cooperations.py`

**Interfaces:**
- Produces: operator list/create/terminate routes, supplier list/accept/reject/terminate routes, `transition_cooperation()` and active `ErpBinding` creation.
- Consumes: Task 1 state enums, `OperatorUser`, `SupplierUser`, `record_event()`.

- [ ] **Step 1: Write failing creation and duplicate tests**

Assert only approved active operators can apply to approved active suppliers; organization IDs come from session and route, not payload. Assert the second pending/active application returns 409 while a rejected history permits a new application.

- [ ] **Step 2: Write failing state-transition tests**

Verify only the target supplier can accept/reject; acceptance atomically creates one active binding; repeated action returns 409. Verify either party can terminate pending/active cooperation, binding becomes inactive, and rejected/terminated history remains queryable.

- [ ] **Step 3: Write failing notification-count and event tests**

Assert the supplier list exposes pending count and all transitions emit events without contact details or secrets.

- [ ] **Step 4: Implement state service and schemas**

Centralize allowed transitions in:

```python
ALLOWED_TRANSITIONS = {
    "PENDING": {"ACTIVE", "REJECTED", "TERMINATED"},
    "ACTIVE": {"TERMINATED"},
}
```

Lock the cooperation row during transitions, create the binding before flush on acceptance, and set binding inactive in the termination transaction.

- [ ] **Step 5: Implement role-scoped routes, verify and commit**

Run: `./start.sh test`

```bash
git add app/services/operator_cooperation.py app/schemas/cooperation.py app/api/routes/operator_cooperations.py app/api/routes/supplier_operator.py app/api/router.py tests/test_operator_cooperations.py
git commit -m "feat: add operator supplier cooperation workflow"
```

### Task 6: 运营商 ERP 凭证与集成数据隔离

**Files:**
- Modify: `app/api/integration_deps.py`
- Modify: `app/api/routes/integrations.py`
- Modify: `app/schemas/integration.py`
- Modify: `app/api/routes/operators.py`
- Modify: `app/core/integration_security.py`
- Create: `tests/test_operator_integration_access.py`
- Modify: `tests/test_integration_auth.py`
- Modify: `tests/test_integrations.py`

**Interfaces:**
- Produces: operator-owned client CRUD/rotation, authenticated principal owner/type, `allowed_supplier_ids()` and binding-filtered integration reads.
- Consumes: active bindings from Task 5 and existing four `IntegrationScope` values.

- [ ] **Step 1: Write failing credential lifecycle tests**

Assert operators can list only their clients, create allowed read scopes, receive token once, rotate to invalidate the old token, and revoke. Assert suppliers cannot access these routes and operators cannot request unknown/write scopes.

- [ ] **Step 2: Write failing access-isolation tests**

Create two suppliers with products/SKUs/costs and bind only one. Assert an operator token sees public supplier metadata but sees brand/SKU/cost data only for the bound supplier. Assert an unbound supplier-specific request returns 404. Terminate cooperation and assert access disappears immediately. Assert system tokens retain both suppliers.

- [ ] **Step 3: Extend authenticated principal**

Use this immutable shape:

```python
@dataclass(frozen=True, slots=True)
class AuthenticatedIntegrationClient:
    id: str
    name: str
    scopes: tuple[str, ...]
    client_type: str
    owner_organization_id: str | None
```

Reject operator clients whose owner organization is missing, inactive or not type `OPERATOR`.

- [ ] **Step 4: Implement operator client lifecycle**

Reuse `generate_integration_token`, `hash_integration_token` and current expiry validation. Set `client_type=OPERATOR`, owner from session and never include plaintext in event payloads.

- [ ] **Step 5: Apply binding constraints inside every business query**

For operator principals, join active cooperation and binding on supplier ID for brand/SKU/cost list/detail and incremental sync queries. Preserve current cursor and watermark semantics. Keep system-client query construction unchanged.

- [ ] **Step 6: Run contract/full tests and commit**

Run: `./start.sh test`

```bash
git add app/api/integration_deps.py app/api/routes/integrations.py app/api/routes/operators.py app/schemas/integration.py app/core/integration_security.py tests/test_operator_integration_access.py tests/test_integration_auth.py tests/test_integrations.py
git commit -m "feat: restrict operator integrations to active bindings"
```

### Task 7: 公开目录与运营商申请页面

**Files:**
- Modify: `app/main.py`
- Modify: `app/web/pages/index.html`
- Create: `app/web/pages/operator-apply.html`
- Create: `app/web/pages/suppliers.html`
- Create: `app/web/pages/supplier-detail.html`
- Create: `app/web/assets/operator-apply.js`
- Create: `app/web/assets/supplier-directory.js`
- Modify: `app/web/assets/styles.css`
- Create: `tests/test_supplier_directory_ui.js`
- Modify: `tests/test_public_pages.py`

**Interfaces:**
- Produces: `/operator/apply`, `/suppliers`, `/suppliers/{id}` pages and public navigation.
- Consumes: Task 2 application endpoint, Task 4 directory API, common auth/pagination helpers.

- [ ] **Step 1: Write failing static-page and form tests**

Assert routes serve pages, home navigation exposes both new entries, and only contact name/phone/email inputs use `required`. Node tests must verify blank optional values are omitted or sent as null/empty arrays and successful submission renders application number.

- [ ] **Step 2: Write failing directory behavior tests**

Verify filters reset page one, pagination uses `MatrixPagination`, cards do not duplicate multi-category suppliers, list contact stays masked, and detail renders full contacts only when returned by API.

- [ ] **Step 3: Build semantic pages and scripts**

Use existing header, form, card, badge, loading, toast and empty-state patterns. Render all API strings through `Matrix.escapeHtml`. Debounce keyword queries and ignore stale responses using monotonically increasing request IDs.

- [ ] **Step 4: Add responsive styling and accessibility**

Keep product-name-sized typography, visible focus rings, label every form control, set filter/status announcements with `aria-live`, and support desktop/mobile card layouts.

- [ ] **Step 5: Verify and commit**

Run: `./start.sh test`

```bash
git add app/main.py app/web/pages/index.html app/web/pages/operator-apply.html app/web/pages/suppliers.html app/web/pages/supplier-detail.html app/web/assets/operator-apply.js app/web/assets/supplier-directory.js app/web/assets/styles.css tests/test_supplier_directory_ui.js tests/test_public_pages.py
git commit -m "feat: add public supplier marketplace pages"
```

### Task 8: 运营商工作台

**Files:**
- Create: `app/web/pages/operator.html`
- Create: `app/web/assets/operator.js`
- Modify: `app/main.py`
- Modify: `app/web/assets/styles.css`
- Create: `tests/test_operator_ui.js`
- Modify: `tests/test_public_pages.py`

**Interfaces:**
- Produces: `/operator` SPA-style workspace with overview, directory, cooperations, suppliers, ERP and profile views.
- Consumes: Tasks 3–6 APIs and shared pagination/dialog/toast functions.

- [ ] **Step 1: Write failing routing and authorization UI tests**

Assert the page includes six navigation views, redirects 401 to login, rejects non-operator identities, and loads the hash-selected view without double requests.

- [ ] **Step 2: Write failing cooperation and credential UI tests**

Verify applying disables repeat action while pending; active supplier rows expose binding IDs; termination requires a confirmation dialog. Verify credential plaintext appears only in a warning dialog and is cleared on button close, Escape and native dialog close.

- [ ] **Step 3: Build operator shell and view loaders**

Reuse the supplier/admin shell structure and unified pagination. Fetch overview only for overview, directory only for find-suppliers, and so on. Guard asynchronous responses with per-view request generations.

- [ ] **Step 4: Implement cooperation, ERP and profile mutations**

Disable submit buttons during requests, show server conflict messages, refresh only affected views/counts, and never store tokens in local/session storage.

- [ ] **Step 5: Verify and commit**

Run: `./start.sh test`

```bash
git add app/main.py app/web/pages/operator.html app/web/assets/operator.js app/web/assets/styles.css tests/test_operator_ui.js tests/test_public_pages.py
git commit -m "feat: add operator workspace"
```

### Task 9: 供应商合作收件箱与管理端运营商管理

**Files:**
- Modify: `app/web/pages/app.html`
- Modify: `app/web/assets/app.js`
- Modify: `app/web/pages/admin.html`
- Modify: `app/web/assets/admin.js`
- Modify: `app/web/assets/common.js`
- Create: `tests/test_supplier_operator_ui.js`
- Create: `tests/test_admin_operator_ui.js`
- Modify: `tests/test_admin.py`

**Interfaces:**
- Produces: supplier cooperation inbox/history and admin operator application/account/cooperation views.
- Consumes: Task 2 admin API, Task 5 supplier API, existing admin/supplier layouts.

- [ ] **Step 1: Write failing supplier UI tests**

Assert navigation shows pending badge, list uses unified pagination, accept/reject/terminate call exact endpoints, stale responses cannot overwrite the latest filter, and buttons reflect legal transitions only.

- [ ] **Step 2: Write failing admin UI tests**

Assert operator applications can be filtered/reviewed, approval shows the one-time password warning, operator accounts and cooperation history paginate, and existing supplier application/client views continue working.

- [ ] **Step 3: Implement supplier view and event labels**

Add cooperation view markup and loaders/actions. Add Chinese labels for operator application, cooperation, binding and credential events in `common.js`.

- [ ] **Step 4: Implement admin views**

Follow existing admin table/dialog patterns, use separate state/pagination per table and clear temporary passwords from DOM on every dialog-close path.

- [ ] **Step 5: Verify and commit**

Run: `./start.sh test`

```bash
git add app/web/pages/app.html app/web/assets/app.js app/web/pages/admin.html app/web/assets/admin.js app/web/assets/common.js tests/test_supplier_operator_ui.js tests/test_admin_operator_ui.js tests/test_admin.py
git commit -m "feat: add operator cooperation administration"
```

### Task 10: 文档、全量验证、重启与交付

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/integrations/system-integration-guide.md`
- Modify: `docs/operations/validation.md`
- Modify: `.env.example` only if an implemented setting requires it

**Interfaces:**
- Produces: operator onboarding/use guide, ERP binding contract, verified deployable release.
- Consumes: all prior task interfaces and the current `./start.sh` deployment workflow.

- [ ] **Step 1: Update user and integration documentation**

Document the three identities, operator application required/optional fields, supplier directory privacy, cooperation states, binding identifiers, operator credential one-time display and system-vs-operator API authorization. Include request/response examples without real tokens or contact data.

- [ ] **Step 2: Run migration and static verification**

Run:

```bash
bash -n start.sh
python -m compileall -q app migrations tests
git diff --check
docker compose config --quiet
docker compose -f docker-compose.test.yml config --quiet
```

Expected: every command exits 0.

- [ ] **Step 3: Run full tests twice**

Run `./start.sh test` twice to prove the persistent test database and migration are repeatable. Expected: both runs pass all backend and frontend tests.

- [ ] **Step 4: Restart and smoke-test the service**

After merging into `main`, run:

```bash
./start.sh restart
./start.sh status
curl --fail --silent http://localhost:6790/api/health
```

Expected: application and database are healthy and the health response contains `"status":"ok"`.

- [ ] **Step 5: Record validation and commit docs**

Write the exact test counts, migration revision, restart status and smoke checks to `docs/operations/validation.md`.

```bash
git add README.md docs/README.md docs/integrations/system-integration-guide.md docs/operations/validation.md .env.example
git commit -m "docs: document operator supplier integration"
```

- [ ] **Step 6: Final branch review**

Review `git diff main...HEAD`, confirm every design acceptance criterion maps to passing tests, confirm no secret/contact fixture is real, and confirm `git status --short` contains no unintended files before requesting merge.
