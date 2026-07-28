# qualify-api

Qualify's CRM backend: a modular monolith (ADR 1). Internal modules are Python packages,
not separate distributions:

- `tenancy` — multi-tenant foundation (C-01): `tenant_id` schema, provisioning, seed.
- `connections` — social-account credential custody + connection FSM (C-03).
- `oauth` — the end-to-end connect flow (C-04): signed one-time `state`, callback,
  `granted_scopes` capture (raw literals only).

The Postgres schema is versioned with Alembic (ADR 27); RLS, roles and `FORCE ROW LEVEL
SECURITY` are hand-written in `op.execute()` (autogenerate never sees them). Migrations run
as `qualify_owner`; the application runs as `qualify_app` (subject to RLS).

Tests are `db`-marked when they need the local Postgres/Redis from `docker-compose`; the
platform (Meta) is always a double — no test hits the network.
