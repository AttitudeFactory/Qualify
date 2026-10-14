# Sprint state — Módulo WhatsApp, Entrega 1 (2026-10-14)

In-flight state for the WA-04…WA-08 wave (`docs/backlog-modulo-whatsapp.md` §2). Append-only;
each agent records what changes someone else's assumptions here, by the durable-findings rule.

## Findings

### [wa04 / pipeline-engineer] 2026-10-14 — Revision `0056` is TAKEN; the WhatsApp migration is `0057_whatsapp`

- **Verified on disk and in the DB:** `migrations/postgres/versions/0056_support_requests.py`
  (QUA-202, commit `e7aa361`, merged to `main`) already holds `revision = "0056"`, and both
  `qualify` and `qualify_test` report `alembic_version = 0056`.
- **Consequence for WA-04:** the file is `0057_whatsapp.py`, `revision = "0057"`,
  `down_revision = "0056"`. The branch is `feat/wa-04-migration-0057`. Nothing else changes.
- **Consequence for the backlog:** every "0056"/"0057" in `docs/backlog-modulo-whatsapp.md`
  shifts by one. In particular `whatsapp_thread_state.menu_version_id` is described as
  "nullable hasta 0057" — the menu migration (WA-14) must be **`0058`** (or later), never
  `0057`. Whoever creates the next migration: `ls migrations/postgres/versions | tail -1`
  first; the number on the backlog is stale by construction.
- **Consequence for WA-07/08 tests:** `packages/api/tests/test_webhook_schema_db.py` pins
  `qualify_webhook_worker`'s grants cell by cell (`test_exactly_the_documented_grants_and_nothing_more`,
  `test_worker_is_denied_everything_else` includes `SELECT 1 FROM messages`). WA-04 widens that
  role (threads/messages S/I/U, whatsapp_* grants) and updates that test in the same PR —
  do not re-widen it from another story without updating the pin.
- **Alembic round-trips run against `qualify_test` only** (`QUALIFY_MIGRATION_DSN=
  postgresql+psycopg://qualify_owner:dev_only@localhost:5432/qualify_test`). `env.py`'s
  default DSN is the dev `qualify` database — `alembic downgrade base` with the default
  would wipe dev data other agents rely on.

### [wa04 / pipeline-engineer] 2026-10-14 — `alembic downgrade base` cannot complete on this host; it is NOT 0057

- **Measured on a freshly reset `qualify_test`:** `downgrade base` runs 0057 → … → 0002 and
  dies at `0002 -> 0001` with `dependent_objects_still_exist` on `DROP ROLE qualify_credential`:
  roles are cluster-wide and the dev `qualify` database in the same Postgres still holds that
  role's grants. 0050 handles this case with a NOTICE; 0001/0002 predate it and use a bare
  `DROP ROLE`. CI (one database per run) does not hit it — `test-db` is green on `main`.
- **Verified instead, same DB:** `downgrade 0056` (just 0057's own downgrade) leaves the
  catalog exactly as 0056 left it — no `whatsapp_*` tables, no `delivery_*` columns,
  `ck_thread_channel` back to `('comment','dm')`, `linked_page_id` `NOT NULL`, no
  `ck_conn_linked_page_by_platform`, worker grants back to the 0050 set. `upgrade head` then
  re-applies 0057 cleanly. The 0057 ↔ 0056 edge was run three times without residue.
- With rows left by earlier test runs (no reset), the chain dies even earlier (0016/0018,
  `ck_attempt_child_media_product_type`) — also pre-existing. Reset before measuring.
