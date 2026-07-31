"""publishing: publish_attempts (write-ahead) + scheduled_posts (QUA-19)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-29

Architect sign-off 2026-07-29, with three conditions encoded here:

A1: `publish_attempts` is ROW-PER-ATTEMPT WITH UPDATE, not append-only. The append-only
    precedent does not transfer — `connection_events` IS a log (history is its purpose) and
    `oauth_credentials` is append-only for CUSTODY (a secret is never overwritten in place).
    Neither reason applies to a table holding the state of ONE logical operation whose
    identity is exactly `(connection_id, idempotency_key)`.
A2: ...but transitions are MONOTONIC, enforced by the database rather than by caller
    discipline (see `_settle_once` below). A late reconciliation must not overwrite an
    already-settled outcome with stale information — that is precisely the failure ADR 22(e)
    exists to prevent.
A3: `scheduled_posts.scheduled_tz` stores the IANA zone used AT COMPOSE TIME, because
    `tenants.timezone` is mutable and means "the tenant's zone now". Correcting a
    misconfigured tenant zone must not silently shift every already-scheduled post.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see the note on 0001's `_enable_rls`. A custom GUC reverts
    # to the empty string, not to undefined, when its transaction ends; without NULLIF a reused
    # pooled connection raises `invalid input syntax for type uuid: ""` instead of failing closed.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


# A settled attempt is FINAL. Enforced as a trigger rather than as a CHECK because a CHECK
# cannot see the previous row: the invariant is about the TRANSITION, not about the value.
# Writing it here rather than as `UPDATE ... WHERE settled_at IS NULL` in the repository means
# a second code path — a backfill script, a psql session, a future worker — cannot bypass it.
_SETTLE_ONCE_FUNCTION = """
CREATE OR REPLACE FUNCTION publish_attempts_settle_once() RETURNS trigger AS $$
BEGIN
    IF OLD.settled_at IS NOT NULL THEN
        RAISE EXCEPTION
            'publish_attempts %: already settled at %, refusing to overwrite a terminal outcome',
            OLD.id, OLD.settled_at
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    # --- publish_attempts: the write-ahead record, written BEFORE the platform call ---
    op.create_table(
        "publish_attempts",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_post_id", PGUUID(as_uuid=True), nullable=True),
        # The caller-chosen identity of the operation. Retrying with the same key must never
        # publish twice; that is what makes ADR 22(e)'s "no blind retry" implementable.
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        # Null until Meta returns the container. Reconciliation enters by this value, so a
        # crash between "container created" and "row updated" is recoverable rather than
        # ambiguous — which is the entire reason the row is written first.
        sa.Column("creation_id", sa.Text(), nullable=True),
        # `media_product_type`, NOT `media_type`: publishing a reel and asking for `media_type`
        # returns VIDEO (`content-publishing.md:230,262`). Storing the wrong one would make
        # every later "was this a reel or a story?" query silently wrong.
        sa.Column("media_product_type", sa.Text(), nullable=False),
        sa.Column("adapter_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("platform_error_code", sa.Text(), nullable=True),
        # Meta's own first-hand signal from a `rupload` failure
        # (`content-publishing.md:187-194`) — strictly better than inferring from a timeout.
        # Nullable because most outcomes never produce it.
        sa.Column("retriable", sa.Boolean(), nullable=True),
        sa.Column("raw_response_r2_key", sa.Text(), nullable=True),
        sa.Column("published_media_id", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Non-null == terminal. The trigger below makes that one-way.
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("connection_id", "idempotency_key", name="uq_attempt_idempotency"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_attempt_conn_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('pending','uploading','processing','published','failed')",
            name="ck_attempt_status",
        ),
        # A settled attempt must have reached a terminal status, and an unsettled one must not.
        # Keeps the timestamp and the status from disagreeing about the same fact.
        sa.CheckConstraint(
            "(settled_at IS NULL) = (status NOT IN ('published','failed'))",
            name="ck_attempt_settled_matches_status",
        ),
    )
    op.create_index("ix_attempt_tenant", "publish_attempts", ["tenant_id"])
    # Reconciliation looks up by creation_id within a tenant — the ONLY supported way to
    # resolve an ambiguous outcome (ADR 22e forbids retrying blindly).
    op.create_index("ix_attempt_reconcile", "publish_attempts", ["tenant_id", "creation_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON publish_attempts TO qualify_app;")
    op.execute("GRANT SELECT ON publish_attempts TO qualify_admin;")
    _enable_tenant_rls("publish_attempts")

    op.execute(_SETTLE_ONCE_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER publish_attempts_settle_once
            BEFORE UPDATE ON publish_attempts
            FOR EACH ROW EXECUTE FUNCTION publish_attempts_settle_once();
        """
    )

    # --- scheduled_posts: what survives a restart ---
    op.create_table(
        "scheduled_posts",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        # The R2 key, always under `t/{tenant_id}/` — enforced in code by
        # `qualify_shared.objects.require_tenant_prefix`, which is why no key is built here.
        sa.Column("media_object_key", sa.Text(), nullable=False),
        sa.Column("media_content_type", sa.Text(), nullable=False),
        sa.Column("media_product_type", sa.Text(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        # Reel cover comes from a frame of the video itself. `cover_url` is deliberately absent:
        # it remains a URL parameter even in the resumable variant (`resumable-uploads.md:53`)
        # and would reintroduce the public hosting this whole scope avoids (ADR 28).
        sa.Column("thumb_offset", sa.Integer(), nullable=True),
        # The absolute instant the scheduler fires on.
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        # The IANA zone the user composed under. Together with `scheduled_for` this reconstructs
        # the wall clock they typed — so NO local-time column, which would be redundant and
        # could disagree.
        sa.Column("scheduled_tz", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_sched_conn_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','publishing','published','failed','cancelled')",
            name="ck_sched_status",
        ),
        sa.CheckConstraint(
            "media_product_type IN ('REELS','STORIES','VIDEO')", name="ck_sched_media_product_type"
        ),
    )
    op.create_index("ix_sched_tenant", "scheduled_posts", ["tenant_id"])
    # The scheduler's only query: what is due? Partial, because published/cancelled rows
    # accumulate forever and must not slow down the hot path.
    op.execute(
        "CREATE INDEX ix_sched_due ON scheduled_posts (scheduled_for) WHERE status = 'scheduled';"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON scheduled_posts TO qualify_app;")
    op.execute("GRANT SELECT ON scheduled_posts TO qualify_admin;")
    _enable_tenant_rls("scheduled_posts")

    op.create_foreign_key(
        "fk_attempt_scheduled_post",
        "publish_attempts",
        "scheduled_posts",
        ["scheduled_post_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_attempt_scheduled_post", "publish_attempts", type_="foreignkey")
    op.execute("DROP INDEX IF EXISTS ix_sched_due;")
    op.drop_index("ix_sched_tenant", table_name="scheduled_posts")
    op.drop_table("scheduled_posts")
    op.execute("DROP TRIGGER IF EXISTS publish_attempts_settle_once ON publish_attempts;")
    op.execute("DROP FUNCTION IF EXISTS publish_attempts_settle_once();")
    op.drop_index("ix_attempt_reconcile", table_name="publish_attempts")
    op.drop_index("ix_attempt_tenant", table_name="publish_attempts")
    op.drop_table("publish_attempts")
