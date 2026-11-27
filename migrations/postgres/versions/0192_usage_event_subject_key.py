"""creative_usage_events.subject_key: what a free suggestion was asked for (m-25129386)

Revision ID: 0192
Revises: 0191
Create Date: 2026-11-27

«Sugerir con IA» the line of a character's scene (m-25129386, ADR 50 §12.2) is free for
the owner but capped: at most 10 suggestions per scene and 30 per business, each per day
of the business (`tenants.timezone`). Every suggestion is one `creative_usage_events`
row (`unit = 'character_line'`, provider `anthropic`, draft-less), RESERVED before the
Claude call and settled to what it billed (`creative.character_line_ai`); a call that
billed nothing voids its row (`unit = 'character_line_released'`, US$0) — the app role
keeps no DELETE on this table. The per-scene cap needs to know which scene a row was
for, and the scene has no draft yet — it lives only in the editor until «Crear».

- `subject_key` (uuid, NULL-able): the thing a draft-less usage row was asked for — here
  the scene's own key (`CharacterSceneItem.key`, minted by the editor). NULL for every
  other row and for every row written before this revision (nothing to backfill).
  Deivid's decision (Q1, 2026-11-27): a column of its own, not an overload of
  `vendor_task_id` (which is the vendor's id and carries a UNIQUE partial index).
- `ix_usage_event_tenant_unit_subject`: `(tenant_id, unit, subject_key, created_at)
  WHERE subject_key IS NOT NULL` — the cap's count (one business, one unit, one scene,
  since the start of its day; the query says `subject_key IS NOT NULL`) is an index
  range scan. Partial: every other row has no
  subject and stays out of it.

Plain `CREATE INDEX`, not `CONCURRENTLY` (every revision here runs in a transaction, as
0179): the column is new, so the partial index holds no row and the build is one scan of
an append-only table. `ADD COLUMN` without a default is a catalogue change.

RLS and grants are unchanged: the table keeps ENABLE + FORCE and its NULLIF policy (0009),
and the table-level grants cover the new column.
"""

from alembic import op

revision = "0192"
down_revision = "0191"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE creative_usage_events ADD COLUMN subject_key uuid")
    op.execute(
        "CREATE INDEX ix_usage_event_tenant_unit_subject "
        "ON creative_usage_events (tenant_id, unit, subject_key, created_at) "
        "WHERE subject_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_usage_event_tenant_unit_subject")
    op.execute("ALTER TABLE creative_usage_events DROP COLUMN IF EXISTS subject_key")
