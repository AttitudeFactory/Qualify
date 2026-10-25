"""Runtime DSNs for the two application roles, read from the environment.

Roles are created by Alembic migration 0001 with dev passwords, so the local
docker-compose defaults and the CI service-container DSNs coincide. Production
overrides both via env (and rotates the passwords out-of-band with `ALTER ROLE`).

There is deliberately NO owner/migration DSN here — that belongs to Alembic
(`QUALIFY_MIGRATION_DSN`, see migrations/postgres/env.py). Application code must
never connect as the object owner.
"""

from __future__ import annotations

import os

# `qualify_app`: the request-path role — subject to RLS, no BYPASSRLS, no superuser.
DEFAULT_APP_DSN = "postgresql+psycopg://qualify_app:app_dev@localhost:5432/qualify"
# `qualify_admin`: cross-tenant provisioning/seed only — BYPASSRLS, never the request path.
DEFAULT_ADMIN_DSN = "postgresql+psycopg://qualify_admin:admin_dev@localhost:5432/qualify"
# `qualify_credential`: the ONLY role granted `oauth_credentials.ciphertext` (R3). Used
# solely by the CredentialResolver to decrypt in-memory; RLS-subject, so in-tenant only.
DEFAULT_CREDENTIAL_DSN = (
    "postgresql+psycopg://qualify_credential:credential_dev@localhost:5432/qualify"
)
# `qualify_webhook`: the Meta webhook RECEIVER (QUA-147) — INSERT on the two intake tables,
# nothing else; NOBYPASSRLS. See migration 0050.
DEFAULT_WEBHOOK_DSN = "postgresql+psycopg://qualify_webhook:webhook_dev@localhost:5432/qualify"
# `qualify_webhook_worker`: the intake processor + purge (QUA-147) — the intake tables' queue
# columns plus five columns of `social_connections` for the cross-tenant resolution.
DEFAULT_WEBHOOK_WORKER_DSN = (
    "postgresql+psycopg://qualify_webhook_worker:webhook_worker_dev@localhost:5432/qualify"
)

# `qualify_creative_worker`: the generation queue's worker (ADR 41, m-24852160) — the queue
# columns of `creative_jobs` and `vendor_slots`, nothing else; NOBYPASSRLS. See 0096.
DEFAULT_CREATIVE_WORKER_DSN = (
    "postgresql+psycopg://qualify_creative_worker:creative_worker_dev@localhost:5432/qualify"
)


def app_dsn() -> str:
    return os.environ.get("QUALIFY_APP_DSN", DEFAULT_APP_DSN)


def admin_dsn() -> str:
    return os.environ.get("QUALIFY_ADMIN_DSN", DEFAULT_ADMIN_DSN)


def credential_dsn() -> str:
    return os.environ.get("QUALIFY_CREDENTIAL_DSN", DEFAULT_CREDENTIAL_DSN)


def webhook_dsn() -> str:
    return os.environ.get("QUALIFY_WEBHOOK_DSN", DEFAULT_WEBHOOK_DSN)


def webhook_worker_dsn() -> str:
    return os.environ.get("QUALIFY_WEBHOOK_WORKER_DSN", DEFAULT_WEBHOOK_WORKER_DSN)


def creative_worker_dsn() -> str:
    return os.environ.get("QUALIFY_CREATIVE_WORKER_DSN", DEFAULT_CREATIVE_WORKER_DSN)
