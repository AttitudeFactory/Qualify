"""publish_attempt_children: per-item state for a carousel publish attempt (QUA-99, 2/6)

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-10

## Scope: VIDEO-ONLY, schema only, not wired to anything yet

This is schema only — no `PublishService`/`repository.py` code reads or writes this table
yet (that is commit 3/6 and 4/6). `media_product_type` accepts only the three video values
`publish_attempts` already accepts (`REELS`/`STORIES`/`VIDEO`); there is no `IMAGE` value
anywhere in this migration, no `image_url` column, no crop metadata. Image support is
explicitly deferred to a future PR gated on QUA-68 (public media URL) — extending this
table for it later is an additive migration, not a rewrite of this one.

## Why a table, not N independent `publish_attempts` rows

A carousel is ONE Instagram post (`content-publishing.md:61`) with one `media_id` — the
parent `publish_attempts` row IS that post, exactly as it is today for a single video
(`creation_id` on that row becomes the CAROUSEL container's id once all children are
ready). This table exists only to track the N *child* containers a carousel needs before
that final container can be created — it has no independent "published" outcome of its
own, which is why it carries no `settled_at`/settle-once trigger the way `publish_attempts`
and `comment_reply_drafts` (0003, 0014) do: nothing here is ever handed to
`media_publish`, so there is no irreversible transition at THIS table's layer to guard.
If commit 4 (the orchestration service) surfaces a real invariant that needs DB-level
enforcement, that is a follow-up migration, not something to guess at now.

## Composite FK prerequisite (R2 discipline, same move 0012/0014 made)

`publish_attempts` never needed `(id, tenant_id)` before (nothing referenced it by more
than its own PK) — adding it here is safe post-hoc since `id` is already a PK, same
reasoning 0014 used for `comment_sentiment_results`. Note the established convention
(verified against `messages`/`Message` — 0012 added `uq_message_id_tenant` and the ORM
class was deliberately NOT updated to declare it): the bridging constraint lives in the
migration only. `PublishAttempt.__table_args__` is intentionally left unchanged.

## `position`, not insertion order

Instagram's carousel is DISPLAY-ordered — the order of `children` in the `CAROUSEL`
container's creation call is the order shown in the post (`content-publishing.md:100`,
`resumable-uploads.md:127`). Rows are read back ordered by `position`, never by `id`/
`created_at`, because Postgres row order is not guaranteed to survive an UPDATE.
`UNIQUE(attempt_id, position)` makes "two children claiming the same slot" a database
error, not a bug discovered by re-reading the carousel a client just built wrong.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`. Duplicated per-migration
    # rather than shared, same as every prior revision in this chain does.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def upgrade() -> None:
    # Prerequisite: `publish_attempts` needs a (id, tenant_id) unique pair before this
    # table's FK to it can be composite (R2 discipline). `id` is already globally unique
    # (PK), so this cannot fail against existing data.
    op.create_unique_constraint(
        "uq_publish_attempt_id_tenant",
        "publish_attempts",
        ["id", "tenant_id"],
    )

    op.create_table(
        "publish_attempt_children",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", PGUUID(as_uuid=True), nullable=False),
        # Display order inside the carousel (0-indexed) — see module docstring.
        sa.Column("position", sa.Integer(), nullable=False),
        # The R2 key this child's bytes were staged to — same `media_key()` layout every
        # other staged media in this module uses, always under `t/{tenant_id}/`.
        sa.Column("media_object_key", sa.Text(), nullable=False),
        sa.Column("media_content_type", sa.Text(), nullable=False),
        # VIDEO-ONLY for this PR — the same three values `publish_attempts` accepts.
        # No IMAGE value exists here; adding one later is an additive CHECK change.
        sa.Column("media_product_type", sa.Text(), nullable=False),
        # Null until Meta returns THIS child's own container. Distinct from
        # `publish_attempts.creation_id`, which (once all children are ready) holds the
        # CAROUSEL container's id, not any child's.
        sa.Column("creation_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("platform_error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("attempt_id", "position", name="uq_attempt_child_position"),
        sa.ForeignKeyConstraint(
            ["attempt_id", "tenant_id"],
            ["publish_attempts.id", "publish_attempts.tenant_id"],
            name="fk_attempt_child_attempt_tenant",
        ),
        sa.CheckConstraint(
            "media_product_type IN ('REELS','STORIES','VIDEO')",
            name="ck_attempt_child_media_product_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','uploading','processing','finished','failed')",
            name="ck_attempt_child_status",
        ),
    )
    op.create_index("ix_attempt_child_tenant", "publish_attempt_children", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON publish_attempt_children TO qualify_app;")
    op.execute("GRANT SELECT ON publish_attempt_children TO qualify_admin;")
    _enable_tenant_rls("publish_attempt_children")


def downgrade() -> None:
    op.drop_index("ix_attempt_child_tenant", table_name="publish_attempt_children")
    op.drop_table("publish_attempt_children")
    op.drop_constraint("uq_publish_attempt_id_tenant", "publish_attempts", type_="unique")
