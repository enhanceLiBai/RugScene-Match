# Final review findings to fix

## Critical

1. `backend/services.py:142-175` — file cleanup is not atomically bound to database outcome. Two sessions importing the same SHA can interleave so the failed creator deletes a file while the other session commits a row pointing to it. A commit acknowledgement failure can also delete a file after the database actually committed. Serialize the full same-SHA work unit with a PostgreSQL transaction-scoped advisory lock. Delete a newly created file only for failures known to occur before commit is attempted; after commit begins, retain it when the outcome is uncertain. Add focused real two-session/barrier regression coverage for A failure/B success and a focused commit-ack-loss test.

## Important

2. `index.html:63` — price input allows backend decimals but browser default step is 1. Add `step="0.01"` and page contract coverage.

3. `app.js:16-29,201-207` — overlapping `refreshLibrary()` calls can apply an older response after a newer upload refresh. Add latest-request-wins token or AbortController behavior and a focused async test.

4. `README.md:54` — Node verification command omits `tests/app.test.js`. Include it and state/verify the complete 12-test set.

## Minor

5. `backend/api.py:130-141` — price values above PostgreSQL `NUMERIC(12,2)` capacity become 503. Reject values above `9999999999.99` at the API boundary as 400 with one focused test.

6. `app.js:16-29,index.html:15` — first library load failure should show count `—`; later failures should preserve the last successful count/list.

7. `app.js:140-145` — revoke preview object URLs on replacement, successful reset, and page unload.

8. `README.md:14` — describe bootstrap accurately as creating/reusing `.venv`, upgrading pip, and installing dependencies.

9. `app.js:198-211` — upload-time edits can be cleared by an older submission's success reset. Disable the entire entry form during upload, restoring all controls in `finally`, with a focused test.

## Constraints

- Prioritize functional correctness and stability; keep each regression test focused and do not add a broad security matrix.
- Preserve the current public API and no-build frontend architecture.
- Use simplified Chinese for necessary comments.
- Use the parent virtualenv and a worktree-local pytest basetemp.
- Do not read or output `.env`, database URLs, or passwords.
