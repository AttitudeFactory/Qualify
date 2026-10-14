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

### [wa14-persistence / pipeline-engineer] 2026-10-14 — migration 0058 + `MenuRepository` (branch `feat/wa-14-menus-migration`, based on `origin/feat/wa-04-migration-0057`)

- **Verified on `qualify_test`:** `0057 → 0058 → 0057 → 0058` round trip, zero residue (no
  `whatsapp_menu*` relations, no `uq_wa_phone_id_tenant` / `fk_wa_thread_state_menu_version_tenant` /
  `ck_wa_thread_state_attempts`, no `attempts` column after `downgrade 0057`). `qualify_test` is now at **0058**.
- **Schema decisions taken here (not in the brief), for the architect to veto:**
  1. `whatsapp_menus.published_version_id` is a COMPOSITE FK `(published_version_id, id) → whatsapp_menu_versions (id, menu_id)`
     (unique `uq_wa_menu_version_id_menu`), so a menu can only publish one of its OWN versions.
  2. **At most one published menu per phone number** — partial unique index `uq_wa_menu_phone_published ON whatsapp_menus
     (phone_number_row_id) WHERE published_version_id IS NOT NULL`. Reason: the WA-07 loader must be deterministic.
     `publish_version` demotes the number's other live menu in the same transaction.
  3. `whatsapp_menus.is_paused` pauses the automation for the WHOLE number; the loader returns `None` for a paused menu
     (handler stays silent). Per-thread pause stays in `whatsapp_thread_state.automation_paused_at`.
  4. Column names follow 0057's convention: `created_by_user_id`, `published_by_user_id` (the brief said `created_by`/`published_by`).
- **Catalog fact for test authors:** a column-level `GRANT UPDATE (published_at, published_by_user_id)` does NOT appear in
  `information_schema.role_table_grants` (only in `column_privileges`), so the 0057 table-level pin in
  `test_whatsapp_schema_db.py` now filters by the three 0057 tables instead of `LIKE 'whatsapp_%'`.
- **Repository API (`qualify_api.whatsapp.menus`, all keyword-only, `tenant_id` first):**
  `create_menu(tenant_id, phone_number_row_id, name, brand_id=None, created_by_user_id=None) -> MenuRecord`,
  `get_menu(tenant_id, menu_id) -> MenuRecord | None`, `list_menus(tenant_id, phone_number_row_id) -> list[MenuRecord]`,
  `save_version(tenant_id, menu_id, definition: MenuDefinition | Mapping) -> MenuVersionRecord` (raises `pydantic.ValidationError`),
  `list_versions(tenant_id, menu_id)`, `publish_version(tenant_id, menu_id, version_id, user_id, now=None) -> MenuRecord`,
  `set_paused(tenant_id, menu_id, paused) -> MenuRecord`, `get_published(tenant_id, menu_id) -> MenuDefinition | None`,
  and the worker-door loader **`load_published_menu_for_phone(phone_number_row_id: UUID) -> tuple[MenuDefinition, UUID] | None`**
  (module-level function AND a method on both impls; type alias `MenuLoader`). Impls: `PostgresMenuRepository`, `MemoryMenuRepository`.
  Errors: `MenuNotFound`, `MenuVersionNotFound`.
- **WA-07 contract:** `menu_loader(phone_number_row_id)` returns `(definition, version_id)`; store `version_id` in
  `whatsapp_thread_state.menu_version_id` (now FK-checked, composite with `tenant_id`) and the engine's `attempts` in the new
  `whatsapp_thread_state.attempts` column (worker already has table-level UPDATE on thread_state).
- **PR:** https://github.com/AttitudeFactory/Qualify/pull/132 (`feat/wa-14-menus-migration` → `main`, carries 0057 until PR WA-04 merges). Offline 3819 / db 591 green; alembic 0057↔0058 round trip clean.
