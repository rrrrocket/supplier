# Repository Documentation Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commit the approved PostgreSQL platform changes, organize every non-entrypoint Markdown document under `docs/`, repair references and generic terminology, and remove only files proven obsolete or reproducible.

**Architecture:** Preserve root `README.md` as the repository entrypoint and make `docs/README.md` the documentation index. Separate architecture, product, operations, integrations, designs, and plans by responsibility; keep runtime assets that `start.sh` or the application references, and move generated local artifacts to Trash so cleanup remains recoverable.

**Tech Stack:** Git, Markdown, Bash, Node.js link validation, Docker Compose through `./start.sh`, PostgreSQL 16 on port 6432.

**Spec:** `docs/designs/2026-09-08-repository-documentation-cleanup-design.md`

## Global Constraints

- Keep root `README.md` as the only Markdown document outside `docs/`.
- Keep `.env` local, ignored, unread during cleanup, and absent from every commit.
- Keep `Dockerfile`, both Compose files, Nginx configuration, and `app/web/sample-offers.csv`; remove the redundant `Makefile`.
- Do not delete PostgreSQL volumes, tables, records, or migration history.
- Start and test only through `./start.sh` and `./start.sh test`.
- Runtime and test database URLs use `postgresql+psycopg`; PostgreSQL listens on port 6432.
- Public integration documentation addresses generic calling systems and uses `/api/integrations/v1` plus `client_sku_id`.
- Configure only repository-local Git identity as `rrrrocket <standxh@163.com>`.
- Preserve unrelated user changes and stage only the exact files listed in each task.

---

## File Structure

### Documentation files created or moved

- `docs/README.md` — index for every maintained document.
- `docs/architecture/overview.md` — platform boundaries, data flow, and technical evolution.
- `docs/architecture/data-dictionary.md` — entities, fields, uniqueness, and ownership.
- `docs/product/project-status.md` — currently working and explicitly incomplete capabilities.
- `docs/product/roadmap.md` — planned product increments and acceptance targets.
- `docs/operations/validation.md` — verified commands, results, and remaining operational checks.
- `docs/integrations/system-integration-guide.md` — generic external-system onboarding and cost-query contract.
- `docs/designs/2026-09-08-supplier-brand-sku-integration-design.md` — approved supplier/brand/SKU domain design.
- `docs/plans/2026-09-08-supplier-brand-sku-integration.md` — implementation plan for the domain design.

### Repository entrypoint modified

- `README.md` — links to `docs/README.md` and no longer points to root-level documentation.

### Files removed

- `app/db/seed.py` — obsolete deterministic demo seeding.
- `data/.gitkeep` — obsolete local file-database directory placeholder.
- `deploy/supplier.service` — obsolete legacy-port virtual-environment service unit.
- `scripts/reset_demo.py` — obsolete file-database reset utility.
- `start-macos.command` — obsolete legacy-port virtual-environment launcher.
- `scripts/dev.sh` — redundant four-line proxy to `start.sh`.
- `.venv/`, `.pytest_cache/`, Python `__pycache__/`, and `.pyc` files — ignored reproducible artifacts.
- `Makefile` — redundant wrapper around `start.sh` and direct container commands.

---

### Task 1: Verify and Commit the Existing PostgreSQL Platform Changes

**Files:**
- Modify: `.env.example`
- Modify: `.gitignore`
- Create: `.dockerignore`
- Modify: `Dockerfile`
- Modify: `Makefile`
- Modify: `alembic.ini`
- Modify: `app/api/deps.py`
- Modify: `app/api/routes/admin.py`
- Modify: `app/api/routes/auth.py`
- Modify: `app/api/routes/imports.py`
- Modify: `app/api/routes/offers.py`
- Modify: `app/core/config.py`
- Create: `app/db/bootstrap.py`
- Modify: `app/db/session.py`
- Modify: `app/main.py`
- Modify: `app/models/entities.py`
- Modify: `app/schemas/admin.py`
- Modify: `app/schemas/auth.py`
- Create: `app/services/import_mapping.py`
- Modify: `app/web/assets/admin.js`
- Modify: `app/web/assets/app.js`
- Modify: `app/web/assets/common.js`
- Modify: `app/web/assets/login.js`
- Modify: `app/web/assets/styles.css`
- Modify: `app/web/pages/admin.html`
- Modify: `app/web/pages/app.html`
- Modify: `app/web/pages/apply.html`
- Modify: `app/web/pages/index.html`
- Modify: `app/web/pages/login.html`
- Modify: `deploy/nginx-supplier.conf`
- Modify: `docker-compose.yml`
- Create: `docker-compose.test.yml`
- Create: `migrations/versions/7f22c89a41bd_unify_supplier_user_role.py`
- Modify: `requirements-dev.txt`
- Modify: `requirements.txt`
- Create: `start.sh`
- Modify: `tests/conftest.py`
- Modify: `tests/test_admin.py`
- Modify: `tests/test_api.py`
- Create: `tests/test_database_backend.py`
- Create: `tests/test_public_auth.js`
- Create: `tests/test_public_pages.py`
- Create: `tests/test_role_migration.py`
- Create: `tests/test_roles.py`
- Modify: `tests/test_security.py`

**Interfaces:**
- Consumes: Docker Engine through `./start.sh`, PostgreSQL 16 images, and repository-local `.env`.
- Produces: one verified commit containing the already-approved PostgreSQL-only runtime, unified supplier role, migrated account/bootstrap behavior, and logged-in public-page state.

- [ ] **Step 1: Confirm repository-local identity and secret exclusion**

Run:

```bash
git config --local user.name
git config --local user.email
git check-ignore -v .env
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo '.env must not be tracked' >&2
  exit 1
fi
```

Expected: the first two commands print `rrrrocket` and `standxh@163.com`; `git check-ignore` identifies `.gitignore`; `git ls-files --error-unmatch .env` exits nonzero because `.env` is not tracked.

- [ ] **Step 2: Verify the current implementation before staging**

Run:

```bash
bash -n start.sh
./start.sh test
```

Expected: shell syntax passes; backend and frontend tests pass using the isolated PostgreSQL service on port 6432.

- [ ] **Step 3: Stage only the platform implementation**

Run:

```bash
git add -- .env.example .gitignore .dockerignore Dockerfile Makefile alembic.ini \
  app/api/deps.py app/api/routes/admin.py app/api/routes/auth.py \
  app/api/routes/imports.py app/api/routes/offers.py app/core/config.py \
  app/db/bootstrap.py app/db/session.py app/main.py app/models/entities.py \
  app/schemas/admin.py app/schemas/auth.py app/services/import_mapping.py \
  app/web/assets/admin.js app/web/assets/app.js app/web/assets/common.js \
  app/web/assets/login.js app/web/assets/styles.css app/web/pages/admin.html \
  app/web/pages/app.html app/web/pages/apply.html app/web/pages/index.html \
  app/web/pages/login.html deploy/nginx-supplier.conf docker-compose.yml \
  docker-compose.test.yml migrations/versions/7f22c89a41bd_unify_supplier_user_role.py \
  requirements-dev.txt requirements.txt start.sh tests/conftest.py \
  tests/test_admin.py tests/test_api.py tests/test_database_backend.py \
  tests/test_public_auth.js tests/test_public_pages.py tests/test_role_migration.py \
  tests/test_roles.py tests/test_security.py
git diff --cached --check
git diff --cached --name-status
```

Expected: the staged list contains only the files above, has no whitespace errors, and excludes `.env`, all Markdown documents, and every cleanup deletion.

- [ ] **Step 4: Commit the verified platform implementation**

Run:

```bash
git commit -m "feat: standardize PostgreSQL supplier platform"
```

Expected: the commit author is `rrrrocket <standxh@163.com>` and the remaining worktree contains only documentation and cleanup changes.

---

### Task 2: Classify Documentation and Repair References

**Files:**
- Create: `docs/README.md`
- Move: `ARCHITECTURE.md` → `docs/architecture/overview.md`
- Move: `DATA_DICTIONARY.md` → `docs/architecture/data-dictionary.md`
- Move: `PROJECT_STATUS.md` → `docs/product/project-status.md`
- Move: `ROADMAP.md` → `docs/product/roadmap.md`
- Move: `VALIDATION.md` → `docs/operations/validation.md`
- Move: `docs/SYSTEM_INTEGRATION_GUIDE.md` → `docs/integrations/system-integration-guide.md`
- Move: `docs/superpowers/specs/2026-09-08-supplier-brand-sku-integration-design.md` → `docs/designs/2026-09-08-supplier-brand-sku-integration-design.md`
- Move: `docs/superpowers/plans/2026-09-08-supplier-brand-sku-integration.md` → `docs/plans/2026-09-08-supplier-brand-sku-integration.md`
- Modify: `README.md`
- Modify: `docs/plans/2026-09-08-supplier-brand-sku-integration.md`

**Interfaces:**
- Consumes: the approved directory mapping in the cleanup design.
- Produces: stable documentation paths rooted at `docs/`, a navigable index, valid Markdown links, and generic calling-system terminology.

- [ ] **Step 1: Move documents into responsibility-based directories**

Run:

```bash
mkdir -p docs/architecture docs/product docs/operations docs/integrations docs/designs docs/plans
mv ARCHITECTURE.md docs/architecture/overview.md
mv DATA_DICTIONARY.md docs/architecture/data-dictionary.md
mv PROJECT_STATUS.md docs/product/project-status.md
mv ROADMAP.md docs/product/roadmap.md
mv VALIDATION.md docs/operations/validation.md
mv docs/SYSTEM_INTEGRATION_GUIDE.md docs/integrations/system-integration-guide.md
mv docs/superpowers/specs/2026-09-08-supplier-brand-sku-integration-design.md docs/designs/2026-09-08-supplier-brand-sku-integration-design.md
mv docs/superpowers/plans/2026-09-08-supplier-brand-sku-integration.md docs/plans/2026-09-08-supplier-brand-sku-integration.md
rmdir docs/superpowers/specs docs/superpowers/plans docs/superpowers
```

Expected: root contains only `README.md`; all other Markdown files exist at the target paths; the empty `docs/superpowers` tree is removed.

- [ ] **Step 2: Create the documentation index**

Create `docs/README.md` with exactly these maintained-document links:

```markdown
# Supplier Network 文档

## 架构

- [系统架构](architecture/overview.md)
- [数据字典](architecture/data-dictionary.md)

## 产品

- [项目状态](product/project-status.md)
- [产品路线图](product/roadmap.md)

## 运维与验证

- [验证报告](operations/validation.md)

## 系统集成

- [通用系统接入指南](integrations/system-integration-guide.md)

## 设计与实施计划

- [供应商品牌、SKU 与通用系统集成设计](designs/2026-09-08-supplier-brand-sku-integration-design.md)
- [供应商品牌、SKU 与通用系统集成实施计划](plans/2026-09-08-supplier-brand-sku-integration.md)
- [仓库文档归档与清理设计](designs/2026-09-08-repository-documentation-cleanup-design.md)
- [仓库文档归档与清理实施计划](plans/2026-09-08-repository-documentation-cleanup.md)
```

- [ ] **Step 3: Update root README and moved-document paths**

Change the root README architecture links to:

```markdown
详细说明见 [文档索引](docs/README.md)、[系统架构](docs/architecture/overview.md) 和 [数据字典](docs/architecture/data-dictionary.md)。
```

Remove the obsolete `scripts/` row from its repository tree. In the supplier integration plan, replace every old spec, guide, architecture, data-dictionary, and validation path with:

```text
docs/designs/2026-09-08-supplier-brand-sku-integration-design.md
docs/integrations/system-integration-guide.md
docs/architecture/overview.md
docs/architecture/data-dictionary.md
docs/operations/validation.md
```

- [ ] **Step 4: Make calling-system terminology generic**

Apply these exact semantic replacements in the maintained prose documents:

```text
existing business execution product name → 外部业务系统 / 调用方
product-specific execution layer → 业务执行系统 + Data / AI
product-specific synchronization → 外部系统同步
product-specific roadmap section → 通用系统接入
```

Do not change `supplier_id`, `supplier_sku_id`, `client_sku_id`, `/api/integrations/v1`, or any documented API payload.

- [ ] **Step 5: Validate Markdown inventory and links**

Run:

```bash
find . -maxdepth 1 -type f -name '*.md' -print
find docs -type f -name '*.md' | sort
node <<'NODE'
const fs = require('fs');
const path = require('path');
const files = [];
function walk(directory) {
  for (const entry of fs.readdirSync(directory, {withFileTypes: true})) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) walk(target);
    else if (target.endsWith('.md')) files.push(target);
  }
}
files.push('README.md');
walk('docs');
const missing = [];
for (const file of files) {
  const source = fs.readFileSync(file, 'utf8');
  for (const match of source.matchAll(/\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)/g)) {
    const link = match[1];
    if (/^(?:https?:|mailto:|\/)/.test(link)) continue;
    const target = path.resolve(path.dirname(file), decodeURIComponent(link));
    if (!fs.existsSync(target)) missing.push(`${file}: ${link}`);
  }
}
if (missing.length) {
  console.error(missing.join('\n'));
  process.exit(1);
}
console.log(`${files.length} Markdown files checked; all local links resolve.`);
NODE
git diff --check -- README.md docs
```

Expected: the root listing contains only `README.md`; every local Markdown link resolves; no whitespace errors are reported.

- [ ] **Step 6: Commit the documentation structure**

Run:

```bash
git add -- README.md docs
git diff --cached --check
git commit -m "docs: organize repository documentation"
```

Expected: Git records the root-document moves as renames where content similarity permits and includes the new documentation index.

---

### Task 3: Remove Proven Obsolete and Reproducible Files

**Files:**
- Delete: `app/db/seed.py`
- Delete: `data/.gitkeep`
- Delete: `deploy/supplier.service`
- Delete: `scripts/reset_demo.py`
- Delete: `start-macos.command`
- Delete: `scripts/dev.sh`
- Delete locally: `.venv/`, `.pytest_cache/`, all Python cache directories and bytecode.

**Interfaces:**
- Consumes: `start.sh`, `app/db/bootstrap.py`, Docker runtime files, and the approved cleanup inventory.
- Produces: no duplicate launch/reset path, no file-database artifacts, and no ignored generated Python environment in the workspace.

- [ ] **Step 1: Prove runtime references do not require deletion candidates**

Run:

```bash
if rg -n 'seed_database|reset_demo|start-macos|scripts/dev|supplier\.service|data/' \
  app tests start.sh Dockerfile Makefile docker-compose.yml docker-compose.test.yml \
  deploy README.md docs --glob '!docs/designs/2026-09-08-repository-documentation-cleanup-design.md' \
  --glob '!docs/plans/2026-09-08-repository-documentation-cleanup.md'; then
  echo 'obsolete path still has an active reference' >&2
  exit 1
fi
```

Expected: no active runtime, test, deployment, entrypoint, or maintained-document reference is returned.

- [ ] **Step 2: Move obsolete tracked files to Trash**

Run after confirming the repository root is `/Users/haixiao/Desktop/supplier`. Some files are already deleted in the current worktree, so only move candidates that still exist:

```bash
pwd
for cleanup_path in app/db/seed.py data/.gitkeep deploy/supplier.service scripts/reset_demo.py start-macos.command scripts/dev.sh; do
  test ! -e "$cleanup_path" || trash "$cleanup_path"
done
```

Expected: `pwd` prints the exact repository root; any candidate still present is recoverable from macOS Trash; all six paths remain represented as deletions in Git.

- [ ] **Step 3: Move ignored generated artifacts to Trash**

Run:

```bash
for generated_path in .venv .pytest_cache; do
  test ! -e "$generated_path" || trash "$generated_path"
done
find app migrations scripts tests -type d -name __pycache__ -prune -exec trash {} +
find app migrations scripts tests -type f -name '*.pyc' -exec trash {} +
rmdir data scripts 2>/dev/null || true
```

Expected: `.venv` and test/Python caches are gone; `.env` remains; application source, migrations, and tests remain.

- [ ] **Step 4: Commit tracked cleanup**

Run:

```bash
git add -u -- app/db/seed.py data/.gitkeep deploy/supplier.service scripts/reset_demo.py start-macos.command scripts/dev.sh
git diff --cached --check
git diff --cached --name-status
git commit -m "chore: remove obsolete local runtime files"
```

Expected: the staged diff contains exactly six deletions and no data, environment, or runtime configuration file.

---

### Task 4: Run Final Repository Verification

**Files:**
- Modify when results changed: `docs/operations/validation.md`

**Interfaces:**
- Consumes: the reorganized repository and all commits from Tasks 1–3.
- Produces: verified startup/test behavior, valid documentation links, clean Git metadata, and an accurate validation report.

- [ ] **Step 1: Run syntax and full automated verification**

Run:

```bash
bash -n start.sh
./start.sh test
```

Expected: shell syntax passes and all backend/frontend tests pass against isolated PostgreSQL 16 on port 6432.

- [ ] **Step 2: Verify the running stack and database port**

Run:

```bash
./start.sh
./start.sh status
curl --fail --silent http://127.0.0.1:6790/api/health
docker compose exec -T db psql -U supplier -d supplier -tAc 'SHOW port'
```

Expected: app and database report healthy; health endpoint succeeds; PostgreSQL prints `6432`.

- [ ] **Step 3: Verify repository invariants**

Run:

```bash
test -f README.md
test -f docs/README.md
test -f .env
test ! -e .venv
test ! -e .pytest_cache
test ! -e scripts
test ! -e data
test "$(git config --local user.name)" = "rrrrocket"
test "$(git config --local user.email)" = "standxh@163.com"
test -z "$(git ls-files .env)"
git diff --check
git status --short
```

Expected: every assertion succeeds; `.env` exists but is untracked; no generated directories return; status is clean except for a validation-report update made from the actual test output.

- [ ] **Step 4: Record changed verification results and commit only if needed**

If test counts or verification results differ from `docs/operations/validation.md`, replace its stale values with the exact output from Steps 1–2, then run:

```bash
git add -- docs/operations/validation.md
git diff --cached --check
git commit -m "docs: refresh repository validation results"
```

If the report already matches, do not create an empty commit.

- [ ] **Step 5: Inspect final history and status**

Run:

```bash
git log -5 --format='%h %an <%ae> %s'
git status --short --ignored
```

Expected: new commits show `rrrrocket <standxh@163.com>`; tracked worktree is clean; `.env` is the only required ignored local configuration, while Docker-managed PostgreSQL data remains outside the repository.

---

### Task 5: Persist the Automated Test Database and Remove the Make Wrapper

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.test.yml`
- Modify: `start.sh`
- Modify: `tests/conftest.py`
- Modify: `tests/test_database_backend.py`
- Modify: `README.md`
- Modify: `docs/designs/2026-09-08-repository-documentation-cleanup-design.md`
- Modify: `docs/plans/2026-09-08-repository-documentation-cleanup.md`
- Modify: `docs/operations/validation.md`
- Delete: `Makefile`

**Interfaces:**
- Consumes: the isolated Compose project name `supplier-tests`, test database `supplier_test`, and `./start.sh test` entrypoint.
- Produces: persistent named volume `supplier_test_postgres`, a retained `test-db` service after each run, idempotent fixed test accounts, and repeatable tests over accumulated test data.

- [ ] **Step 1: Add failing persistence contract tests**

Add these tests to `tests/test_database_backend.py`:

```python
def test_test_compose_uses_persistent_database_volume() -> None:
    compose_source = (PROJECT_ROOT / "docker-compose.test.yml").read_text()
    assert "tmpfs:" not in compose_source
    assert "supplier_test_postgres:/var/lib/postgresql/data" in compose_source
    assert re.search(r"(?m)^  supplier_test_postgres:\s*$", compose_source)


def test_test_command_does_not_destroy_persistent_database() -> None:
    start_source = (PROJECT_ROOT / "start.sh").read_text()
    assert "cleanup_test_environment" not in start_source
    assert "down --volumes" not in start_source
```

- [ ] **Step 2: Run the current suite and observe the persistence tests fail**

Run:

```bash
./start.sh test
```

Expected: the two new tests fail because the test database still uses `tmpfs` and `start.sh` still destroys the test Compose project and volume.

- [ ] **Step 3: Replace tmpfs with a named test volume**

Change `docker-compose.test.yml` so `test-db` contains:

```yaml
    volumes:
      - supplier_test_postgres:/var/lib/postgresql/data
```

Add this top-level declaration:

```yaml
volumes:
  supplier_test_postgres:
```

Keep `docker-compose.test.yml` separate from `docker-compose.yml`. Do not expose a host port and do not change the fixed test database name, credentials, PostgreSQL internal port 6432, or application test service URL.

- [ ] **Step 4: Stop destroying the test project after each run**

Remove `cleanup_test_environment`, its `EXIT INT TERM` trap, the explicit cleanup call, and trap removal from `start.sh`. Keep `docker compose run --rm` for the backend and frontend runner containers; leave `supplier-tests-test-db-1`, its network, and `supplier-tests_supplier_test_postgres` running after the command completes or fails.

- [ ] **Step 5: Make fixed test records idempotent**

In `tests/conftest.py`, import `select` and replace unconditional creation in `create_test_accounts()` with select-or-create behavior:

```python
def create_test_accounts() -> None:
    with SessionLocal() as db:
        platform = db.scalar(
            select(Organization).where(Organization.code == "TEST-PLATFORM")
        )
        if platform is None:
            platform = Organization(
                code="TEST-PLATFORM",
                name="测试平台组织",
                organization_type=OrganizationType.PLATFORM.value,
            )
            db.add(platform)
            db.flush()

        supplier = db.scalar(
            select(Organization).where(Organization.code == "TEST-SUPPLIER")
        )
        if supplier is None:
            supplier = Organization(
                code="TEST-SUPPLIER",
                name="测试供应商组织",
                organization_type=OrganizationType.SUPPLIER.value,
            )
            db.add(supplier)
            db.flush()

        admin_user = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if admin_user is None:
            admin_user = User(email=ADMIN_EMAIL, name="测试平台管理员")
            db.add(admin_user)
        admin_user.organization_id = platform.id
        admin_user.role = UserRole.PLATFORM_ADMIN.value
        admin_user.password_hash = hash_password(ADMIN_PASSWORD)
        admin_user.is_active = True

        supplier_user = db.scalar(select(User).where(User.email == SUPPLIER_EMAIL))
        if supplier_user is None:
            supplier_user = User(email=SUPPLIER_EMAIL, name="测试供应商")
            db.add(supplier_user)
        supplier_user.organization_id = supplier.id
        supplier_user.role = UserRole.SUPPLIER.value
        supplier_user.password_hash = hash_password(SUPPLIER_PASSWORD)
        supplier_user.is_active = True

        profile = db.scalar(
            select(SupplierProfile).where(
                SupplierProfile.organization_id == supplier.id
            )
        )
        if profile is None:
            profile = SupplierProfile(
                organization_id=supplier.id,
                legal_name="测试供应商有限公司",
                supplier_type="FACTORY",
                categories=["工业自动化"],
                cooperation_modes=["B2B外贸"],
                status=SupplierStatus.APPROVED.value,
            )
            db.add(profile)
        db.commit()
```

Do not delete or truncate existing rows. Randomized application, product, offer, and role-test rows may remain between runs.

- [ ] **Step 6: Remove Makefile and update documentation**

Keep the user-provided `Makefile` deletion. Update `README.md` to state that `./start.sh test` uses an isolated persistent PostgreSQL volume, retains accumulated test records and the test database service after completion, and never connects to the business database.

Update the cleanup design and plan to classify `Makefile` as deleted rather than retained. Update `docs/operations/validation.md` only after Step 7 with the exact passing test count and persistence result.

- [ ] **Step 7: Verify two consecutive runs reuse the database**

Run:

```bash
bash -n start.sh
./start.sh test
first_volume_id="$(docker volume inspect supplier-tests_supplier_test_postgres --format '{{.Name}}:{{.CreatedAt}}')"
first_user_count="$(docker compose -p supplier-tests -f docker-compose.test.yml exec -T test-db psql -U supplier_test -d supplier_test -tAc 'SELECT count(*) FROM users')"
./start.sh test
second_volume_id="$(docker volume inspect supplier-tests_supplier_test_postgres --format '{{.Name}}:{{.CreatedAt}}')"
second_user_count="$(docker compose -p supplier-tests -f docker-compose.test.yml exec -T test-db psql -U supplier_test -d supplier_test -tAc 'SELECT count(*) FROM users')"
test "$first_volume_id" = "$second_volume_id"
test "$first_user_count" -gt 0
test "$second_user_count" -ge "$first_user_count"
docker compose -p supplier-tests -f docker-compose.test.yml ps test-db
```

Expected: both complete test runs pass; the named volume identity is unchanged; user rows remain and do not decrease; `test-db` remains healthy after both runs.

- [ ] **Step 8: Update validation results and commit**

Record the exact backend and frontend test counts from both runs, the unchanged volume identity, nondecreasing user count, retained healthy test database, and PostgreSQL port 6432 in `docs/operations/validation.md`.

Run:

```bash
git add -- Dockerfile docker-compose.test.yml start.sh tests/conftest.py tests/test_database_backend.py README.md docs/designs/2026-09-08-repository-documentation-cleanup-design.md docs/plans/2026-09-08-repository-documentation-cleanup.md docs/operations/validation.md
git add -u -- Makefile
git diff --cached --check
git diff --cached --name-status
git commit -m "feat: persist automated test database"
```

Expected: the commit contains exactly the nine modified files and the `Makefile` deletion, uses author `rrrrocket <standxh@163.com>`, and leaves only ignored `.env` plus the SDD workspace in Git status.
