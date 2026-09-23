# SDD ledger — plan: docs/superpowers/plans/2026-09-07-product-buyer-image-linking.md

Workspace: `D:/电商ai应用/.worktrees/product-buyer-image-linking`
Branch: `codex/product-buyer-image-linking`
Starting commit: `d69a772d776fefe94d2da51b6d54051f4053ba42`

Baseline:
- `node --test tests/matcher-core.test.js`: 3 passed.
- `pytest tests/test_services.py --basetemp .pytest-tmp/baseline -q`: 8 passed.
- Database-backed baseline could not complete because the local PostgreSQL connection did not respond; task tests will use the configured database when reachable and otherwise report this environment limitation.

## Pre-flight interface scan

| Tasks | Producer / consumer | Finding |
|---|---|---|
| 1 | Own model and repository tests versus declared methods | Consistent; model fields support the repository operations. |
| 2 | Own parser fixture versus `iter_product_images` | Consistent; fixture covers only structural XML and selected columns. |
| 3 | Own import tests versus service/API implementation | Consistent; upload, background execution and cleanup are covered. |
| 4 | Own search tests versus response contract | Consistent; candidate recall precedes product de-duplication. |
| 5 | Own frontend mapping test versus reused DOM | Consistent; pure mapper is testable without adding a framework. |
| 6 | Own documentation and verification steps | Consistent; commands remain limited to the feature. |
| 1 → 3 | `ProductImage`/`ImportJob` and repository methods consumed by import service | Consistent. |
| 1 → 4 | Product-image associations consumed by search query | Consistent. |
| 2 → 3 | `WorkbookImage` iterator consumed by import service | Consistent. |
| 3 ↔ 4 | Both modify `backend/api.py`; Task 4 builds on Task 3 | Sequential order resolves overlap. |
| 4 → 5 | Search response fields consumed by frontend | Consistent names and roles. |
| 3/4/5 → 6 | Final behavior documented after implementation | Consistent. |

Ruling: `import_jobs` is a technical progress table in addition to the single `product_images` business association table — persistent task status was approved in the design and must survive a process restart — if wrong, one extra technical table would need removal and progress would become in-memory only.
Ruling: Use a workspace-local pytest base temp because the sandbox denies the user profile temp directory — this changes only test execution paths, not application behavior — if wrong, test artifacts may need cleanup from `.pytest-tmp`.

Task 1: complete (commits d69a772..54b21b5, review clean; database-backed GREEN deferred until PostgreSQL responds).
Task 2: fix round 1/5 (1 addressed, 0 open — stream worksheet/sharedStrings/drawing XML with iterparse; commits a712dab..538a3af).
Task 2: complete (commits 54b21b5..538a3af, review clean; 7 parser tests passed).
