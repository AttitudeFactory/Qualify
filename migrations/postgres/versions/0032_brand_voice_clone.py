"""brand voice: one ACTIVE profile per brand, enforced; the brand's HeyGen voice clone

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-30

## One ACTIVE voice profile per brand

`VoiceProfileService` has always kept "at most one ACTIVE profile per brand" inside a
single transaction, but the database only had `UNIQUE (brand_id, version)`. Since
2026-09-30 (founder: no approval step) every kit save adopts the voice itself
(`VoiceProfileService.adopt_from_kit`), so two saves racing (a double click, the wizard
and the editor open at once) could each promote a row. The partial unique index makes
the invariant a database fact: the loser gets an IntegrityError instead of a second
ACTIVE.

## brand_voice_clones

The brand's own voice cloned in HeyGen (`POST /v3/voices/clone`) from a sample the
operator uploaded on ¿Cómo suena?. One row per brand: cloning again replaces it (and
the old clone is deleted in HeyGen, freeing a slot of the account's quota). Cloning is
MANUAL and needs the operator's explicit consent — who confirmed it and when is
recorded here, since a voice is a person's likeness. `status` mirrors HeyGen's own
(`processing` → `complete` | `failed`).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


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


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_voice_profiles_one_active "
        "ON brand_voice_profiles (brand_id) WHERE status = 'active';"
    )

    op.create_table(
        "brand_voice_clones",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("heygen_voice_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="processing", nullable=False),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("gender", sa.Text(), nullable=True),
        sa.Column("preview_audio_url", sa.Text(), nullable=True),
        sa.Column("consent_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint("brand_id", name="uq_voice_clone_brand"),
        sa.CheckConstraint(
            "status IN ('processing','complete','failed')", name="ck_voice_clone_status"
        ),
    )
    op.create_index("ix_voice_clones_tenant", "brand_voice_clones", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON brand_voice_clones TO qualify_app;")
    _enable_tenant_rls("brand_voice_clones")


def downgrade() -> None:
    op.drop_index("ix_voice_clones_tenant", table_name="brand_voice_clones")
    op.drop_table("brand_voice_clones")
    op.execute("DROP INDEX IF EXISTS uq_voice_profiles_one_active;")
