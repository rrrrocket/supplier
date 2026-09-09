# SDD ledger — plan: docs/plans/2026-09-08-supplier-brand-sku-integration.md

## Baseline

- Branch: `feat/system-integration`
- Worktree: `/Users/haixiao/Desktop/supplier/.worktrees/system-integration`
- Baseline: `./start.sh test` passed (96 Python tests, 23 Node tests).

## Preflight review

| Tasks | Shared file/interface | Finding |
|---|---|---|
| 1 → 2 | Catalog ORM types and transitional foreign keys | Clean: Task 2 consumes Task 1's nullable transition fields and backfilled rows. |
| 1 → 4 | `app/models/entities.py`, Alembic chain | Clean: Integration Client revision follows catalog expansion. |
| 1 → 7 | `app/models/entities.py`, final migration | Clean: Task 7 contracts only after all write paths use new IDs. |
| 1 → 8 | Migration preservation contract | Clean: final verification covers the expansion/backfill guarantees. |
| 2 → 3 | `catalog.py`, catalog schemas, router, catalog tests | Clean: cooperation replacement builds on brand/SKU services. |
| 2 → 5 | Router, fixtures, Supplier SKU read model | Clean: external resources consume stable identities created by Task 2. |
| 2 → 6 | `catalog.py`, current Offer/SKU relation | Clean: cost resolution consumes the stable one-to-one identity. |
| 2 → 7 | Product/Offer/import schemas, routes, and supplier UI | Clean: Task 7 removes transition writes only after Task 2 establishes replacements. |
| 2 → 8 | Public fields and documentation | Clean: docs publish the final, not transitional, contract. |
| 3 → 4 | `admin_catalog.py`, admin UI | Clean: credential management extends the same platform-only surface. |
| 3 → 5 | Router and current cooperation interface | Clean: integration listing reads platform-managed active relationships. |
| 3 → 6 | Cooperation state and audit labels | Clean: cost access follows the current relationship set by Task 3. |
| 3 → 7 | Supplier/admin UI and CSS | Clean: platform owns mode edits; supplier remains read-only. |
| 3 → 8 | Cooperation documentation | Clean. |
| 4 → 5 | Scoped bearer dependencies and integration schemas | Clean: resource endpoints consume per-scope principals. |
| 4 → 6 | `CostReader` | Clean: both cost endpoints share the same required scope. |
| 4 → 7 | ORM and migration chain | Clean: final catalog migration follows credential revision without altering credentials. |
| 4 → 8 | Auth/OpenAPI documentation | Clean. |
| 5 → 6 | `integrations.py`, integration schemas/tests | Clean: cost routes extend the generic resource router. |
| 5 → 8 | OpenAPI/public integration contract | Clean. |
| 6 → 7 | Supplier cost terminology and stable ID display | Clean: UI wording changes do not expose external cost endpoints. |
| 6 → 8 | Error codes, scopes, paths, cost semantics | Clean. |
| 7 → 8 | Final database/API/UI contract | Clean: documentation describes contracted columns and public names only. |
| 1 | Tests vs implementation/files | Clean. Migration IDs exist in sequence and preservation assertions are behavior-level. |
| 2 | Tests vs implementation/files | Clean with ruling below on the Product brand request/display boundary. |
| 3 | Tests vs implementation/files | Conflict: plan asks for JavaScript source-text assertions, which are change detectors rather than behavior tests. |
| 4 | Tests vs implementation/files | Clean. Token secrecy and scope behavior are externally observable. |
| 5 | Tests vs implementation/files | Ambiguity: supplier status and supplier `updated_at` derivation are not specified. |
| 6 | Tests vs implementation/files | Ambiguity: aggregate audit events spanning suppliers cannot use one supplier organization FK. |
| 7 | Tests vs implementation/files | Conflict: plan again asks for source assertions; behavioral DOM/API checks are preferable. |
| 8 | Tests vs implementation/files | Conflicts: prose-grep tests are change detectors; test-stack teardown contradicts the documented persistent test DB/network/volume lifecycle; live migration is an external side effect. |

Ruling: Product write requests retain the caller-facing `brand` display-name field during Task 2 and resolve it to an assigned `brand_id`; Task 7's supplier select submits that name. This preserves current API compatibility while enforcing normalized identity. Cost if wrong: callers may need a later request-field migration to `brand_id`.

Ruling: Replace plan-mandated JavaScript source-text assertions in Tasks 3 and 7 with behavior-level Node/DOM tests where practical, while retaining HTML endpoint assertions for user-visible controls. This follows the repository test-quality rules. Cost if wrong: a purely textual wiring regression not observable in the harness could escape until browser QA.

Ruling: Integration supplier status is `ACTIVE` only when the organization is active and its SupplierProfile is `APPROVED`; otherwise `INACTIVE`. Supplier `updated_at` is the later of organization/profile timestamps so status/profile changes participate in incremental sync. Cost if wrong: consumers expecting raw profile values such as `APPROVED` would need an adapter change.

Ruling: Integration audit events use `organization_id=None`, `actor_type=INTEGRATION_CLIENT`, and the Integration Client ID as `actor_id`; request metadata contains no token, cost value, or `client_sku_id`. Cost if wrong: per-supplier audit filtering will not include these aggregate requests without a later association table.

Ruling: Keep the repository's persistent `supplier-tests` database, network, and volume lifecycle; only one-shot test runners are removed. The plan's teardown sentence conflicts with the existing operational contract and is not required by the spec. Cost if wrong: CI environments expecting zero retained Docker resources must add an explicit cleanup job.

Ruling: Test the OpenAPI schema and runtime API behavior, but do not grep human documentation as an automated correctness test. Documentation is reviewed and updated manually against exported constants. Cost if wrong: documentation-only drift is caught at review time rather than by CI.

Ruling: Task 8 live backup, migration, and real credential exercise are excluded until separately authorized because they affect state outside this worktree. Cost if wrong: deployment readiness will still require an explicit production migration rehearsal.

## Task progress

Task 1: fix round 1/5 (2 addressed, 0 open — cooperation backfill now deduplicates before UUID generation; same-brand multi-offer migration regression added; commits e2b55d3..262b827)

Task 1: complete (commits 7c00914..262b827, review clean)

Task 2: Ruling: add transitional catch-up migration `3b9f7d2c8a11` after `9a61d5c312ef`, and make the later Integration Client migration depend on it. This closes the expand/deploy window in which legacy writers could create NULL catalog foreign keys before Task 2 code activates. Cost if wrong: one extra production migration and duplicated one-time reconciliation SQL must be maintained.

Task 2: Ruling: retain `supplier_sku` as a deprecated Offer request/response compatibility field through Task 6, then remove it in Task 7 as the plan's final contract requires. Cost if wrong: OpenAPI temporarily exposes both old and new names for one release boundary.

Task 2: fix round 1/5 (4 addressed, 0 open — transitional catch-up migration, legacy Offer compatibility, import tenant predicate, stable-ID mutation coverage; commits 2208c07..2cb3b33)

Task 2: complete (commits 262b827..2cb3b33, review clean)

Task 2A: Ruling: reproduce the user's already-written bulk correction-row exclusion feature in this isolated branch before later supplier-workbench edits, without modifying the main checkout. Cost if wrong: the same uncommitted feature remains duplicated in the main checkout until branch integration.

Task 2A: fix round 1/5 (3 addressed, 0 open — configuration invalidation now clears the restore group consistently; commits 73ae8c0..91046d3)

Task 2A: complete (commits 2cb3b33..91046d3, review clean)

Task 3: Ruling: keep SupplierProfile.cooperation_modes as editable supplier-declared cooperation intent/capability, but rename its UI copy to explicitly say it is not the platform-confirmed commercial mode; formal A/B/C mode remains platform-only. Cost if wrong: users may still assume the preference influences the formal relationship despite the explanatory copy.

Task 3: Ruling: add migration `5d91a2c74e30` after `3b9f7d2c8a11` to enforce unique normalized brand names, and make Task 4's credential migration depend on it. Cost if wrong: one additional migration is required before credential deployment.

Task 3: fix round 1/5 (4 addressed, 0 open — supplier intent copy, stale-response isolation, unique normalized brand migration, behavior tests; commits e3d0faf..a2d6d0b)

Task 3: complete (commits 91046d3..a2d6d0b, review clean)

Task 4: fix round 1/5 (6 addressed, 0 original open; one new pool-starvation finding — token cleanup, independent auth transaction, prefix retry, aware expiry, no-store, authorization; commits 7da5dce..5d2d595)

Task 4: fix round 2/5 (1 addressed, 0 open — auth lookup/verification/usage update now use one short connection and return a detached principal snapshot; commits 5d2d595..6e80991)

Task 4: complete (commits a2d6d0b..6e80991, review clean)

Task 4A: Ruling: preserve plain-array Product/Offer API responses, add deterministic offset pagination, fetch all matching chunks into client state, and render 50-row UI pages. This fixes the confirmed 1,792-row truncation without breaking existing API consumers. Cost if wrong: very large suppliers will still transfer the complete filtered result set and may later require server-driven cursor pagination.

Task 4A: fix round 1/5 (3 addressed, 1 new open — brand-selection request generation, stale list errors, Product option rebuild; commits c661e57..a299e8a)

Task 4A: fix round 2/5 (1 addressed, 0 open — stale brand-list rejection is ignored only when obsolete; commits a299e8a..cffc7c5)

Task 4A: complete (commits 6e80991..cffc7c5, review clean)

Task 5: Ruling: for `include_inactive=true`, expose structurally orphaned Supplier SKUs with `commercial_mode=null` and `status=INACTIVE`; active rows still use one of the three documented modes. This makes missing relationships observable without inventing a mode. Cost if wrong: clients that assumed commercial_mode is always a string must handle null for inactive corrupt/incomplete records.

Task 5: Ruling: public-guide pagination and inactive-sync documentation is explicitly owned by Task 8, so record the current drift and carry it into that task rather than editing docs in Task 5. Cost if wrong: intermediate commits do not yet provide publishable external documentation.

Task 5: fix round 1/5 (4 addressed, 0 open — nested timestamp propagation, orphan inactive SKU contract, incremental coverage, canonical cursors; commits a8eaa79..39b6098)

Task 5: complete (commits cffc7c5..39b6098, review clean)

Task 6: Ruling: preserve a caller-supplied nonblank `X-Request-ID` exactly in the aggregate cost-query audit event and generate a UUID only when the header is absent or blank. Cost if wrong: retry correlation would remain impossible for callers that deliberately reuse one request ID.

Task 6: Ruling: audit every cost request from an identifiable Integration Client, including schema 400, scope 403, business 404/409, and post-authentication 5xx outcomes; unauthenticated 401 attempts do not fabricate an actor. Cost if wrong: malformed or insufficiently scoped requests would remain an audit blind spot.

Task 6: Ruling: pre-authenticate only the two cost routes in a narrow pure-ASGI layer and persist their audit event after the inner FastAPI request/dependency stack has fully unwound. This avoids both malformed-JSON pre-auth gaps and connection-pool starvation from opening an audit transaction before the request DB session closes. Cost if wrong: the middleware is a specialized integration lifecycle boundary that must be kept aligned if cost paths change.

Task 6: fix round 1/5 (2 addressed, 2 new open — caller request-ID propagation and identifiable pre-handler outcomes fixed; pool-saturation lifecycle and malformed-JSON authentication gaps found; commits 2a8b895..fc9bef1)

Task 6: fix round 2/5 (2 addressed, 0 open — pure-ASGI post-cleanup audit lifecycle, pre-parse principal identification, single-connection and malformed-JSON regressions; commits fc9bef1..9f49c22)

Task 6: complete (commits 39b6098..9f49c22, review clean)

Task 6A: Ruling: implement the guide's 429 acceptance case as a configurable, per-Integration-Client in-process fixed-window limiter (`600` requests per `60` seconds by default) because the supported runtime starts one Uvicorn worker. Multi-worker or multi-replica deployment requires a shared gateway/data-store limiter and must be documented in Task 8. Cost if wrong: horizontally scaled deployments would multiply the effective request budget until a shared limiter is added.

Task 6A: Ruling: count every authenticated integration request once before scope authorization, share one budget across scopes, and never allocate a rate-limit identity to invalid credentials. Cost requests rejected with 429 retain their normal single redacted audit event and caller request ID. Cost if wrong: callers could evade limits by switching endpoints or rejected requests could create misleading identities/audit counts.

Task 6A: fix round 1/5 (1 Important and 1 Minor addressed, 1 new Important open — cost 429 restored global security/TrustedHost protections and cleanup became periodic; late-created client windows could remain blocked past their own expiry; commits ecd7a6e..0eb3e19)

Task 6A: fix round 2/5 (1 Important and 1 Minor addressed, 0 open — current-client O(1) exact expiry reset plus periodic global cleanup; production middleware test restores module/config state; commits 0eb3e19..91caeef)

Task 6A: complete (commits 9adb891..91caeef, review clean)

Task 7: Ruling: remove legacy Offer JSON fields strictly (`extra="forbid"`) for both create and update while preserving the workbook column named `supplier_sku` as an import-file compatibility boundary that maps to canonical `supplier_sku_code`. Cost if wrong: older direct Offer API callers must migrate their payload field, while existing import workbooks remain valid.

Task 7: Ruling: canonical Brand names and Product request/display fields support up to 160 Unicode characters end-to-end; the downgrade to the historical 120-character Product brand column fails before DDL with a clear affected-row count rather than truncating data. Cost if wrong: rollback requires shortening referenced canonical brand names longer than the historical limit.

Task 7: Ruling: a current or empty active brand-cooperation catalog prevents Product/Offer dialogs from opening and shows an actionable toast, while stale request outcomes remain silent. Cost if wrong: suppliers cannot edit an existing Offer while no active brand cooperation exists, matching the platform-owned relationship gate.

Task 7: fix round 1/5 (3 Important and 2 Minor addressed, 1 new Important open — strict PATCH identity contract, catalog empty/error states, 160-character Product brands, exact downgrade, tenant/mode coverage; Offer brand query still capped at 120; commits cbafddc..a1145e5)

Task 7: fix round 2/5 (1 Important and 3 coverage Minors addressed, 0 open — 160-character Offer filtering, current/stale UI error behavior, exact Unicode downgrade tests, isolated full-chain E2E; commits a1145e5..98a7e6a)

Task 7: complete (commits 91caeef..98a7e6a, review clean)

Task 8: Ruling: automated public-contract tests inspect the running application's OpenAPI and exported constants only; human documentation is updated and reviewed manually rather than grep-tested. Cost if wrong: prose drift remains a review responsibility while machine-readable contract drift fails CI.

Task 8: Ruling: Integration supplier eligibility is shared across list and cost surfaces: the Organization must be an active SUPPLIER and its SupplierProfile must exist with status APPROVED. Missing or non-approved profiles produce `SUPPLIER_INACTIVE` before any SKU validation. Cost if wrong: previously active organizations without an approved profile can no longer return costs.

Task 8: Ruling: OpenAPI publishes only reachable response states: invalid cursors use 400; framework validation on the three constrained list operations uses 422; batch cost validation uses 400; the two cost operations and unconstrained supplier detail omit auto-generated unreachable 422. Cost if wrong: custom OpenAPI normalization must remain aligned if route validation behavior changes.

Task 8: Ruling: build OpenAPI into a local object under a per-app lock, normalize it, and publish the cache once. This prevents concurrent callers or normalization failures from observing/persisting raw schemas. Cost if wrong: the helper mirrors FastAPI's `get_openapi` arguments and must be revisited on framework upgrades.

Task 8: fix round 1/5 (2 Important and 1 Minor addressed, 2 new Important open — approved-profile cost eligibility, cursor/401/cost response contracts, stable pagination assertions; supplier detail still exposed 422 and OpenAPI publication raced; commits 2f61720..e37d83d)

Task 8: fix round 2/5 (2 Important and 2 Minor addressed, 1 new Important open — detail 422 removal, locked normalization, production reload and batch-only client ID docs; FastAPI default builder still published raw cache internally; commits e37d83d..ce2d053)

Task 8: fix round 3/5 (1 Important addressed, 0 open — local `get_openapi` construction, atomic normalized cache publication, failure retry and concurrent-reader regressions; commits ce2d053..b63edaa)

Task 8: complete (commits 98a7e6a..b63edaa, review clean; live backup/migration/credential exercise intentionally not run)

Final branch review: fix wave 1/1 in progress (0 addressed, 7 Important and 3 Minor open — cross-tenant migration/domain integrity, stop-the-world deployment safety, snapshot-bound public cursors, stable full-list pagination, import validation parity, SupplierSku concurrency, persistent-test cleanup, credential expiry/rotation, query limits/UI errors, cooperation concurrency).

Ruling: Production rollout is stop-the-world only: stop all writers, back up and validate, migrate through the contract revision, then start the final binary. The transitional catch-up migration narrows the expand/deploy window but cannot close a live legacy-writer race, and rolling upgrade/rollback across the contract migration is unsupported. Cost if wrong: deployment requires a maintenance window and rollback after the contract migration requires a database downgrade or restore.

Ruling: Preserve the legacy plain-array Product and Offer list endpoints, add cursor-keyed internal page endpoints ordered by immutable ID for the supplier UI, and sort the fully collected client state for display. Cost if wrong: the UI still transfers the complete result set and inserts during a scan may join the current collection, though updates and deletes cannot shift offsets or hide pre-existing rows.

Ruling: Public integration cursors bind resource, supplier and filter semantics to a fixed database snapshot watermark, and every page returns that watermark for the caller's next incremental round. Cost if wrong: cursors become larger and callers must persist the explicit watermark instead of inferring one from the final item.

Ruling: Enforce final catalog domain integrity with migration preflights plus bidirectional PostgreSQL constraint triggers on SupplierSku, SupplierOffer, Product, ProductVariant, and supplier Organization mutations. Child writes take key-share locks on their stable parents so concurrent parent/child changes cannot create a write-skew mismatch. Cost if wrong: the final schema carries additional trigger functions that must remain installed and be considered when changing catalog parent keys.

Ruling: Preserve the persistent `supplier-tests` PostgreSQL service/network/volume, but truncate every mapped business table before and after each Python test session under a repeated `_test` database-name guard; function-scoped Integration Clients additionally clean their own clients and audit events. Cost if wrong: interrupted test processes can retain rows until the next session starts, when the guarded pre-suite cleanup removes them.

Final branch review: fix wave 1/1 complete (7 Important and 3 Minor addressed, 0 open — full-row migration/domain preflights and bidirectional durable triggers; stop-the-world compatibility runbook/tests; snapshot-bound public cursors with explicit `sync_watermark`; legacy array compatibility plus immutable-ID Product/Offer page APIs and 1,792-row UI coverage; brand-required import parity and deterministic row revalidation; concurrent SupplierSku upsert/savepoint isolation; persistent test cleanup; expiry/rotate UI/API semantics; 240-character search and Product error handling; serialized first cooperation creation; commits dc87aa4..9a86356).

Final verification: two consecutive `PYTHONDONTWRITEBYTECODE=1 ./start.sh test` runs passed on the same persistent test database (268 Python tests collected; 56 Node tests passed, 0 failed). `alembic heads`, `alembic current`, and `alembic check` report sole head/current `cc83f7e534a1` with no model drift; production/test Compose configs, Python compileall, shell/JavaScript syntax, documentation JSON examples, and `git diff --check` pass. After verification the retained `supplier-tests-test-db-1` is healthy, checked business tables are all empty, and no one-shot runner remains. Live production backup/migration/credential work remains intentionally excluded pending separate authorization.
