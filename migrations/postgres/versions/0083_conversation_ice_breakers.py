"""conversation_ice_breakers: an Instagram account's «preguntas iniciales» (Ice Breakers),
edited in Qualify and published to Instagram by a person (m-24789472, PR 3, B2)

Revision ID: 0083
Revises: 0082
Create Date: 2026-10-23

Ice Breakers are up to four questions Instagram shows a person who opens a chat with the
business for the first time (`business-messaging/instagram-messaging/features/
ice-breakers.md`). Tapping one sends a `postback` with the question's payload; 0082 already
stores that tap (`messages.choice_kind = 'ice_breaker'`, the `QF_` prefix of
`qualify_api.conversations.choices`). This table is the other half: what Qualify proposes,
what the person edited, what was published, and what Instagram answered when read back.

ONE row per connected account (`connection_id` is the primary key):

- `items` — the DRAFT the person edits: a JSON array of at most 4 `{question, payload}`.
  Seeded lazily with the ticket's four defaults (`DEFAULT_ICE_BREAKERS`, payloads
  `QF_PRODUCTO`, `QF_PRECIO`, `QF_UBICACION_HORARIO`, `QF_CATALOGO`) the first time the
  account's screen opens: `INSERT … ON CONFLICT (connection_id) DO NOTHING`, so two
  concurrent first opens cannot create two rows. `defaults_version` says which defaults.
- `status` — the outcome of the last action against Instagram: `draft` (never published),
  `published`, `failed` (the last publish or removal did not go through; `last_error_code`
  says why), `removed`. Editing the draft does NOT change it: Instagram keeps showing what
  was published until a person publishes again.
- `published_items` / `published_at` / `published_by_user_id` — exactly what the last
  successful publish sent and who did it (publishing is a human action, never a worker's).
  «Cambios sin publicar» is `items <> published_items`. NULL once removed.
- `removed_at` / `removed_by_user_id` — the last successful removal.
- `remote_snapshot` / `remote_checked_at` — the last read-back
  (`GET messenger_profile?fields=ice_breakers&platform=instagram`), normalized by
  `conversations.ice_breakers_client` and stamped with its shape version (provenance of a
  corpus-only reading, `[V]`-pending).
- `last_attempt_at`, `last_error_code`, `last_error_detail` — CODES only, never text:
  both are CHECKed to `[a-z0-9_]`, so a Meta error message (which can echo the questions)
  or a token cannot be stored here by mistake.

CHECKs mirror the service: an array of ≤ 4 objects whose `question` and `payload` are
strings and whose payload starts with `QF_` (the 80-character question limit and the
no-duplicates rule live in the service — they need text normalization SQL would duplicate
badly); the four statuses; `published` ⇒ items and date; `draft`/`removed` ⇒ no published
items; `failed` ⇒ an error code.

The composite FK follows R2 and CASCADEs from the account. Standard RLS (R7).

**Grants.** `qualify_app`: SELECT, INSERT, UPDATE — the row is never deleted by the app
(restoring the defaults is an UPDATE; the account's deletion cascades). Nothing for
`qualify_webhook_worker` (a tap is a message, 0082) nor `qualify_admin`.

**Downgrade** drops the table; nothing else is touched. What was published stays on
Instagram — removing it is a person's action from the screen, not a schema change.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None

_TABLE = "conversation_ice_breakers"
# `qualify_api.conversations.ice_breakers` — kept in step by a test.
_STATUSES = ("draft", "published", "failed", "removed")
_MAX_ITEMS = 4
_CODE_PATTERN = "^[a-z0-9_]{1,64}$"
# Any element that is not an object with string `question` and `payload`, or whose payload
# lacks Qualify's Ice Breaker prefix. `!exists(...)` catches a missing key, which lax-mode
# `.type()` would silently skip.
_BAD_ITEM = (
    '$[*] ? (@.type() != "object" || !exists(@.question) || !exists(@.payload) '
    '|| @.question.type() != "string" || @.payload.type() != "string" '
    '|| !(@.payload starts with "QF_"))'
)


def _items_check(column: str, *, nullable: bool, min_items: int) -> str:
    body = (
        f"jsonb_typeof({column}) = 'array' "
        f"AND jsonb_array_length({column}) BETWEEN {min_items} AND {_MAX_ITEMS} "
        f"AND NOT jsonb_path_exists({column}, '{_BAD_ITEM}')"
    )
    return f"{column} IS NULL OR ({body})" if nullable else body


def _enable_tenant_rls(table: str) -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def _user_fk(name: str) -> sa.Column:
    return sa.Column(name, PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True)


def _timestamp(name: str, *, nullable: bool) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    statuses = ", ".join(f"'{s}'" for s in _STATUSES)
    op.create_table(
        _TABLE,
        sa.Column("connection_id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        # The draft the person edits: [{question, payload}], at most 4.
        sa.Column("items", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("defaults_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("published_items", JSONB(), nullable=True),
        _timestamp("published_at", nullable=True),
        _user_fk("published_by_user_id"),
        _timestamp("removed_at", nullable=True),
        _user_fk("removed_by_user_id"),
        sa.Column("remote_snapshot", JSONB(), nullable=True),
        _timestamp("remote_checked_at", nullable=True),
        _timestamp("last_attempt_at", nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_detail", sa.Text(), nullable=True),
        _timestamp("created_at", nullable=False),
        _timestamp("updated_at", nullable=False),
        _user_fk("updated_by_user_id"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_conv_ice_breakers_conn_tenant",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            _items_check("items", nullable=False, min_items=0), name="ck_conv_ice_breakers_items"
        ),
        sa.CheckConstraint(
            _items_check("published_items", nullable=True, min_items=1),
            name="ck_conv_ice_breakers_published_items",
        ),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_conv_ice_breakers_status"),
        sa.CheckConstraint(
            "status <> 'published' OR (published_items IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_conv_ice_breakers_published_state",
        ),
        sa.CheckConstraint(
            "status NOT IN ('draft', 'removed') OR published_items IS NULL",
            name="ck_conv_ice_breakers_unpublished_state",
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR last_error_code IS NOT NULL",
            name="ck_conv_ice_breakers_failed_state",
        ),
        sa.CheckConstraint(
            f"last_error_code IS NULL OR last_error_code ~ '{_CODE_PATTERN}'",
            name="ck_conv_ice_breakers_error_code",
        ),
        sa.CheckConstraint(
            f"last_error_detail IS NULL OR last_error_detail ~ '{_CODE_PATTERN}'",
            name="ck_conv_ice_breakers_error_detail",
        ),
        sa.CheckConstraint(
            "remote_snapshot IS NULL OR jsonb_typeof(remote_snapshot) = 'object'",
            name="ck_conv_ice_breakers_snapshot",
        ),
        sa.CheckConstraint("defaults_version >= 1", name="ck_conv_ice_breakers_defaults_version"),
    )
    op.create_index("ix_conv_ice_breakers_tenant", _TABLE, ["tenant_id"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {_TABLE} TO qualify_app;")
    # Deliberately nothing for qualify_webhook_worker or qualify_admin.
    _enable_tenant_rls(_TABLE)


def downgrade() -> None:
    op.drop_index("ix_conv_ice_breakers_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)
