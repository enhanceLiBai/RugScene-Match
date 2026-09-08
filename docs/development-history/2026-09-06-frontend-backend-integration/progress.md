# SDD ledger — plan: docs/superpowers/plans/2026-09-06-frontend-backend-integration.md

Workspace: `D:/电商ai应用/.worktrees/frontend-backend-integration`
Branch: `codex/frontend-backend-integration`
Starting commit: `7208559d3eabfe98cde3b2db20b49016909de672`
Baseline JavaScript: 3 passed, 0 failed (`node --test tests/matcher-core.test.js`).
Baseline Python: 103 passed, 1 deselected, 2 pre-existing dependency deprecation warnings.

Ruling: All pytest commands use the parent checkout interpreter `D:/电商ai应用/.venv/Scripts/python.exe` and an ignored worktree-local `--basetemp .superpowers/tmp/<run>` — ignored environments are not copied into worktrees and the sandbox denies the user temp root — if wrong, tests may fail for environment-path reasons or leave only ignored temporary files.

## Pre-flight interface and file scan

| Tasks | Producer / consumer or self-check | Finding |
|---|---|---|
| 1 → 2 | Task 1 produces `ImageMetadata` and `update_metadata`; Task 2 consumes both. | Signatures and non-`None` merge semantics agree. |
| 1 → 3 | Task 1 adds metadata to `LibraryRow`/`SearchRow`; Task 3 serializes those fields. | Field names agree; API price is deliberately converted from `Decimal` to `float`. |
| 2 → 3 | Task 2 produces `import_bytes` and `ImportResult.image_id`; Task 3 consumes them. | Invalid image validation remains typed outside the transaction catch; internal work-unit failure maps to 503. |
| 3 → 4 | Task 3 defines HTTP endpoints; Task 4 implements their JavaScript client. | Paths, multipart field names, `top_k`, and lowercase HTTP status strings agree. |
| 3 → 5 | Both modify `tests/test_api.py`; Task 5 extends Task 3's static-root contract. | Sequential edits required; Task 5 builds on the named test from Task 3. |
| 3 → 6 | Task 3 serves same-origin UI and APIs; Task 6 documents and smoke-tests them. | Routes and default address agree. |
| 4 → 5 | Task 4 produces `CarpetApiClient` and snake_case display helpers; Task 5 consumes them. | Script order and global names agree. |
| 5 → 6 | Task 5 replaces browser-local behavior; Task 6 removes obsolete README instructions. | User workflow agrees with implementation order. |
| 1 self | Test expectations vs ORM/migration/repository changes. | Consistent; fresh and existing schema paths are both covered by idempotent initialization. |
| 2 self | Tests vs shared `_import_validated` implementation. | Consistent; CLI passes empty metadata while bytes upload preserves typed validation errors. |
| 3 self | Upload/list/search/static tests vs API code. | Consistent; `frontend_root` isolates static assets from temporary image roots. |
| 4 self | Client tests vs UMD client and matcher-core changes. | Consistent; no package manager or browser DOM dependency required. |
| 5 self | HTML contract and syntax checks vs DOM wiring. | Consistent; pure request/display behavior remains covered in Task 4, while Task 5 tests integration structure. |
| 6 self | README, static checks, automated suites and HTTP smoke. | Consistent; real model download remains explicitly optional. |

Ruling: Task 3 exposes `frontend_root` as a keyword-only test/embedding seam while defaulting to the source project root — `Settings.project_root` continues to own database-adjacent image storage — if wrong, an embedding caller could point static assets at an unintended but explicitly supplied directory.

Ruling: A service `FAILED` result during HTTP library upload maps to 503, while image and price validation errors map to 400 before the work unit — this preserves safe error classification without leaking caught internals — if wrong, a non-database encoder failure may be presented as temporary service unavailability.

Ruling: Per user direction, tests prioritize core feature behavior and stability; retain essential input validation already required by the API contract, but do not add broad adversarial/path-attack matrices or redundant security permutations — if wrong, uncommon hostile-input regressions may have less dedicated coverage.

Task 1: initial implementer stopped due account usage limit after modifying `tests/test_repository.py`; no commit or report was produced. A fresh implementer inherits and validates that uncommitted TDD test rather than discarding it.

Task 1: Ruling: extend `backend.services.SearchResult` and its focused service test during the fix round even though the Task 1 file list omitted them — Task 1's `SearchRow` expansion otherwise deterministically breaks all non-empty searches, while the confirmed spec requires metadata-bearing search results — if wrong, Task 2 loses a small portion of its originally expected service-layer edit but no public behavior is added beyond the spec.

Task 1: fix round 1/5 (3 addressed, 0 open; commits d3a0b77..31ae4e1).
Task 1: complete (commits 7208559..31ae4e1, review clean).

Task 2: Ruling: allow the fix round to touch `backend/image_assets.py` and `tests/test_image_assets.py` to expose whether the current call actually created the hash file — pre-checking `Path.exists()` cannot establish ownership under concurrent identical uploads, and the confirmed spec requires failure cleanup to remove only this call's file — if wrong, the asset helper gains a small additional result contract earlier than the original task split.

Task 2: fix round 1/5 (1 addressed, 0 open; commits 9c631d2..f35c34d).
Task 2: complete (commits 31ae4e1..f35c34d, review clean).

Task 3: cross-task check resolved — `/api-client.js` route points to a file created by Task 4; the fixed whitelist and default root were verified in Task 3.
Task 3: complete (commits f35c34d..8a03317, review clean).

Task 4: fix round 1/5 (1 addressed, 0 open; commits b3b5ab4..e8c7da2).
Task 4: complete (commits 8a03317..e8c7da2, review clean).
Task 4: out-of-scope observation carried to Task 5 — existing `app.js` still uses local ranking and old color/composition copy; Task 5 must remove it and consume `view.matchReason`.

Task 5: Ruling: allow a dependency-free `tests/app.test.js` and minimal test seams in `app.js` for focused async UI behavior — HTML marker assertions alone cannot verify refresh preservation or query/request binding, while the user prioritized stability — if wrong, `app.js` gains a small CommonJS test export that the browser path does not consume.
Task 5: minor (deferred): object URLs are not revoked when previews are replaced/reset, so long sessions may retain image blobs in browser memory.

Task 5: fix round 1/5 (3 addressed, 0 open; commits 7140edd..3a76ed1).
Task 5: complete (commits e8c7da2..3a76ed1, review clean; 1 deferred minor).

Task 6: minor (deferred): README says bootstrap only creates `.venv`, but it also upgrades pip and installs requirements; wording can be more precise.
Task 6: complete (commits 3a76ed1..a6d29c0, review approved; 1 deferred minor).

Final review: Critical — same-SHA concurrent imports and uncertain commit acknowledgement can leave a committed image row pointing to a deleted file.
Final review: Important — price input lacks `step="0.01"`; library refresh lacks latest-request-wins; README Node command omits `tests/app.test.js`.
Final review: Minor — price upper bound maps overflow to 503; initial load failure count differs from design; preview object URLs are not revoked; bootstrap wording is incomplete; upload-time form edits can be reset after an earlier request finishes.

Ruling: use a PostgreSQL transaction-scoped advisory lock keyed by SHA-256 for the real repository import work unit, while test doubles may provide a no-op lock seam — this serializes same-image database/file ownership without globally locking unrelated imports — if wrong, a hash-key collision could unnecessarily serialize unrelated images, affecting throughput but not correctness.

Ruling: once commit has been attempted, a raised exception is treated as outcome-uncertain and the image file is retained for later orphan reconciliation; pre-commit failures still delete files created by this call — preserving a possible committed row is safer than eager cleanup — if wrong, definitively failed commits may leave recoverable orphan files in `data/images`.

Ruling: README and final evidence must report the actual 15 passing Node tests after focused regression cases were added, rather than preserve the reviewer's earlier expected count of 12 — truthful current evidence overrides a stale count — if wrong, documentation differs from the original review estimate but remains reproducible.

Final fix wave: commit `fe7b1cb` addressed findings 2–9; scoped re-review found finding 1 still open.
Final review residual (load-bearing): `backend/services.py` rolls back before unlinking a pre-commit-created file, which releases the transaction advisory lock and lets a waiting same-SHA importer commit before the first importer deletes that shared file.
Ruling: the residual is real and cannot be parked as merge-safe; cleanup must occur while the transaction-scoped advisory lock is still held, before rollback releases it, with a barrier-controlled regression covering rollback-to-unlink ordering — if wrong, changing compensation order could hold the failed transaction/lock slightly longer while deleting one file, but avoids committed rows losing their image.
