# qualify-shared

Cross-cutting primitives shared by Qualify's backend packages (`qualify-api`) and the
scraper (`qualify-scraper`), so neither depends on the other for what they both need.

Home of:

- `db.session` — the single sanctioned door to Postgres for tenant-scoped code:
  `tenant_session(tenant_id)` fixes the `app.tenant_id` GUC per transaction so Row Level
  Security isolates tenants (C-01). The application `Engine` (`qualify_app` role) is private
  to this module; there is no exported `get_engine`/`SessionLocal`.
- `db.admin` — the privileged, cross-tenant door (`qualify_admin`, `BYPASSRLS`) used only by
  tenant provisioning and the seed, never by the request path.
- `dev` — a development-only helper (`set_dev_tenant`) the Reflex CRM uses to pick the active
  tenant before real auth exists.
- ID types, domain-event (`EventPublisher`) and encryption (`Encryptor`) Protocol seams.

Pure-logic modules carry no marker; anything touching Postgres/Redis is marked `db`.
