"""meta_webhook_deliveries + meta_webhook_events: the persistent intake log of Meta's
webhook (QUA-147, phase 1), and the two narrow roles that touch it

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-12

**What this is.** Every signature-valid `POST /api/mentions/webhook` is recorded here
BEFORE the receiver answers 200, and processed later, outside the HTTP request, by
`qualify_api.webhooks.worker`. Two tables:

- `meta_webhook_deliveries` — one row per HTTP delivery, ALWAYS with its exact `raw_body`
  (QUA-147: "registro de entrada (raw body + firma válida + estado de procesamiento)"),
  so a delivery can be re-verified against its signature and re-parsed.
- `meta_webhook_events` — one row per change (`entry[i].changes[j]`), the unit the
  processor claims, retries and settles. `delivery_id` points at the FIRST delivery that
  carried the change.

**Dedup, two levels.** `body_sha256` UNIQUE absorbs a byte-identical redelivery;
`dedup_key` UNIQUE (sha256 of the canonical `{object, entry_id, field, value}`) absorbs the
same change arriving inside a different delivery. Each table carries exactly those two
unique indexes (PK + one) — the receiver inserts with a TARGETLESS
`ON CONFLICT DO NOTHING` (a conflict target would require SELECT, which the receiver must
not hold), so any further unique index would be silently swallowed too.
`test_webhook_schema_db.py` pins the count.

**No `tenant_id`, no RLS — a deliberate, documented exception** (same reasoning ADR 18
gives `ingestion.raw_payloads`): at receipt the owning tenant is unknown, it is derived
later by the processor. Isolation is by GRANT, not by policy:

- `qualify_webhook` (the receiver, NOBYPASSRLS): INSERT on both tables. Nothing else.
- `qualify_webhook_worker` (the processor + purge, BYPASSRLS):
  - deliveries: SELECT of every column except `raw_body` and `signature_header`; DELETE;
  - events: SELECT, DELETE, and UPDATE of the queue columns only (never `value`);
  - `social_connections`: SELECT (id, tenant_id, platform, external_account_id, status).
- `qualify_app` / `qualify_admin` / `qualify_credential`: nothing on either table.

`qualify_webhook_worker` has BYPASSRLS only so its ONE cross-tenant read (resolving
`entry[].id` to its tenant, `mentions/resolve.py`) works under FORCE RLS; BYPASSRLS never
bypasses a GRANT, so its reach is exactly the list above.

**FK is `ON DELETE SET NULL`, not CASCADE.** Purging a delivery (by age, or by account for
QUA-127) must never delete a change still retained; the change keeps its `value` and only
loses its link. Retention itself lives in `qualify_api.webhooks.repository`.

**Roles are cluster-wide.** Created with IF NOT EXISTS and dev passwords like 0001/0002
(`deploy/bootstrap_db_roles.py` rotates them in production). `downgrade` drops this
database's grants and then tries `DROP ROLE`; if the role still holds privileges in
another database of the same cluster (local `qualify` + `qualify_test`), the role is kept
with a NOTICE — it owns nothing and is granted nothing here, and the next `upgrade`
re-grants it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

# Dev passwords, same convention as 0001/0002; production rotates them out-of-band.
_WEBHOOK_PASSWORD = "webhook_dev"
_WEBHOOK_WORKER_PASSWORD = "webhook_worker_dev"

_EVENT_STATUSES = (
    "pending",
    "processing",
    "processed",
    "unsupported",
    "orphan",
    "ambiguous",
    "failed",
    "dead",
)
_DELIVERY_READ_COLUMNS = (
    "id",
    "received_at",
    "body_sha256",
    "body_bytes",
    "object",
    "parse_status",
    "change_count",
    "entry_ids",
)
_EVENT_QUEUE_COLUMNS = (
    "status",
    "attempts",
    "next_attempt_at",
    "locked_at",
    "locked_by",
    "processed_at",
    "last_error",
)
_CONNECTION_RESOLVE_COLUMNS = ("id", "tenant_id", "platform", "external_account_id", "status")


def _create_role(name: str, password: str, *, bypassrls: bool) -> None:
    rls = "BYPASSRLS" if bypassrls else "NOBYPASSRLS"
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{name}') THEN
                CREATE ROLE {name} LOGIN PASSWORD '{password}'
                    NOSUPERUSER {rls} NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {name};")


def _drop_role(name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{name}') THEN
                REVOKE ALL ON SCHEMA public FROM {name};
                DROP OWNED BY {name};
                BEGIN
                    DROP ROLE {name};
                EXCEPTION WHEN dependent_objects_still_exist THEN
                    RAISE NOTICE 'role % kept: it still holds privileges in another '
                                 'database of this cluster', '{name}';
                END;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_role("qualify_webhook", _WEBHOOK_PASSWORD, bypassrls=False)
    _create_role("qualify_webhook_worker", _WEBHOOK_WORKER_PASSWORD, bypassrls=True)

    op.create_table(
        "meta_webhook_deliveries",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("raw_body", sa.LargeBinary(), nullable=False),
        sa.Column("body_sha256", sa.Text(), nullable=False),
        sa.Column("body_bytes", sa.Integer(), nullable=False),
        sa.Column("signature_header", sa.Text(), nullable=False),
        sa.Column("object", sa.Text(), nullable=True),
        sa.Column("parse_status", sa.Text(), nullable=False),
        sa.Column("change_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "entry_ids",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.CheckConstraint("parse_status IN ('parsed','unparseable')", name="ck_mwd_parse_status"),
        sa.UniqueConstraint("body_sha256", name="uq_mwd_body_sha256"),
    )
    op.create_index("ix_mwd_received", "meta_webhook_deliveries", ["received_at"])
    op.create_index(
        "ix_mwd_entry_ids", "meta_webhook_deliveries", ["entry_ids"], postgresql_using="gin"
    )

    statuses = ",".join(f"'{s}'" for s in _EVENT_STATUSES)
    op.create_table(
        "meta_webhook_events",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "delivery_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey(
                "meta_webhook_deliveries.id", name="fk_mwe_delivery", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column("change_index", sa.Integer(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("object", sa.Text(), nullable=False),
        sa.Column("entry_id", sa.Text(), nullable=False),
        sa.Column("entry_time", sa.BigInteger(), nullable=True),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("value", JSONB(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_mwe_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_mwe_attempts"),
        sa.UniqueConstraint("dedup_key", name="uq_mwe_dedup_key"),
    )
    op.create_index(
        "ix_mwe_queue",
        "meta_webhook_events",
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('pending','failed','processing')"),
    )
    op.create_index("ix_mwe_entry", "meta_webhook_events", ["entry_id"])
    op.create_index("ix_mwe_received", "meta_webhook_events", ["received_at"])
    op.create_index("ix_mwe_delivery", "meta_webhook_events", ["delivery_id"])

    # Receiver: INSERT only — no SELECT, so no RETURNING and no ON CONFLICT target.
    op.execute("GRANT INSERT ON meta_webhook_deliveries TO qualify_webhook;")
    op.execute("GRANT INSERT ON meta_webhook_events TO qualify_webhook;")

    # Processor + purge: never the raw body or the signature; UPDATE only the queue.
    op.execute(
        f"GRANT SELECT ({', '.join(_DELIVERY_READ_COLUMNS)}) "
        "ON meta_webhook_deliveries TO qualify_webhook_worker;"
    )
    op.execute("GRANT DELETE ON meta_webhook_deliveries TO qualify_webhook_worker;")
    op.execute("GRANT SELECT, DELETE ON meta_webhook_events TO qualify_webhook_worker;")
    op.execute(
        f"GRANT UPDATE ({', '.join(_EVENT_QUEUE_COLUMNS)}) "
        "ON meta_webhook_events TO qualify_webhook_worker;"
    )
    # The one cross-tenant read: `entry[].id` -> (tenant, connection).
    op.execute(
        f"GRANT SELECT ({', '.join(_CONNECTION_RESOLVE_COLUMNS)}) "
        "ON social_connections TO qualify_webhook_worker;"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT ({', '.join(_CONNECTION_RESOLVE_COLUMNS)}) "
        "ON social_connections FROM qualify_webhook_worker;"
    )
    op.drop_index("ix_mwe_delivery", table_name="meta_webhook_events")
    op.drop_index("ix_mwe_received", table_name="meta_webhook_events")
    op.drop_index("ix_mwe_entry", table_name="meta_webhook_events")
    op.drop_index("ix_mwe_queue", table_name="meta_webhook_events")
    op.drop_table("meta_webhook_events")
    op.drop_index("ix_mwd_entry_ids", table_name="meta_webhook_deliveries")
    op.drop_index("ix_mwd_received", table_name="meta_webhook_deliveries")
    op.drop_table("meta_webhook_deliveries")
    _drop_role("qualify_webhook_worker")
    _drop_role("qualify_webhook")
