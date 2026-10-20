"""brand_voice_clones: the voice can live in Seed Speech (ByteDance), not only HeyGen

(Renumbered from 0066 on 2026-10-19, after `0065_conversations` from `main`.)

Revision ID: 0067
Revises: 0066
Create Date: 2026-10-16

§ request 2026-10-16 («migremos todo lo que está en HeyGen… esto incluye el clonador de voz
del brandkit»): the brand's voice is cloned in BytePlus Seed Speech from now on. The table
of 0032 assumed HeyGen; this revision makes it vendor-neutral, additively:

- `provider` — `heygen` (every row written before today) | `seed_speech`.
- `external_voice_id` — the voice's id at its provider (HeyGen's `voice_id`, or our own
  post-paid `custom_speaker_id` in Seed Speech, `qlf-…`, opaque: no tenant in clear).
  Backfilled from `heygen_voice_id`, which stays for history but is no longer required.
- `sample_object_key` — the recording the voice was cloned from, in R2 under the tenant's
  prefix (provenance; Seed Speech keeps no export of it, and has no delete API).
- `preview_object_key` — the provider's demo clip copied to R2 (its URL lives one hour).
- `consent_text` — the sentence the operator confirmed, word for word.
- `activated_at` — the first real synthesis: Seed Speech charges the voice's slot then and
  the voice can no longer be retrained.

Also: `template_runs.engine` (0038) accepts `omnihuman`, the recipe router's talking
presenter since HeyGen's retirement (`heygen` stays allowed for history).

No RLS change: the tables already self-isolate (0032, 0038).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "brand_voice_clones",
        sa.Column("provider", sa.Text(), server_default="heygen", nullable=False),
    )
    op.add_column("brand_voice_clones", sa.Column("external_voice_id", sa.Text(), nullable=True))
    op.execute("UPDATE brand_voice_clones SET external_voice_id = heygen_voice_id")
    op.alter_column("brand_voice_clones", "external_voice_id", nullable=False)
    op.alter_column("brand_voice_clones", "heygen_voice_id", nullable=True)
    op.add_column("brand_voice_clones", sa.Column("sample_object_key", sa.Text(), nullable=True))
    op.add_column("brand_voice_clones", sa.Column("preview_object_key", sa.Text(), nullable=True))
    op.add_column("brand_voice_clones", sa.Column("consent_text", sa.Text(), nullable=True))
    op.add_column(
        "brand_voice_clones",
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_voice_clone_provider", "brand_voice_clones", "provider IN ('heygen','seed_speech')"
    )
    op.drop_constraint("ck_template_runs_engine", "template_runs", type_="check")
    op.create_check_constraint(
        "ck_template_runs_engine",
        "template_runs",
        "engine IN ('remotion','heygen','omnihuman','ugc')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_template_runs_engine", "template_runs", type_="check")
    op.create_check_constraint(
        "ck_template_runs_engine", "template_runs", "engine IN ('remotion','heygen','ugc')"
    )
    op.drop_constraint("ck_voice_clone_provider", "brand_voice_clones", type_="check")
    op.drop_column("brand_voice_clones", "activated_at")
    op.drop_column("brand_voice_clones", "consent_text")
    op.drop_column("brand_voice_clones", "preview_object_key")
    op.drop_column("brand_voice_clones", "sample_object_key")
    # a Seed Speech row had no HeyGen id: keep its own id there so NOT NULL holds again
    op.execute(
        "UPDATE brand_voice_clones SET heygen_voice_id = external_voice_id "
        "WHERE heygen_voice_id IS NULL"
    )
    op.alter_column("brand_voice_clones", "heygen_voice_id", nullable=False)
    op.drop_column("brand_voice_clones", "external_voice_id")
    op.drop_column("brand_voice_clones", "provider")
