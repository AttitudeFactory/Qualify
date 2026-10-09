"""brand typography: the kit's two type faces and their font files on the brandboard

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-05 (renumbered 0039 → 0043 on 2026-10-06, see below)

§ request 2026-10-05: "quiero que haya un apartado para la tipografía antes de la paleta
de colores y quiero que se pueda extraer la tipografía desde las opciones del brandboard".

Two things, both small:

- `brand_kits.font_heading` / `brand_kits.font_body`: the family names of the brand's
  headline and body type faces, as the operator typed them (or as Claude read them off
  the uploaded logo — `qualify_api.creative.font_ai`). Text, nullable, like every other
  optional kit field; readiness does not count them.
- `brand_kit_assets.kind` gains `'font'` (slot `heading` / `body`): the optional font
  file dropped on Tu brandboard's typography tiles, kept in R2 like a logo version. The
  CHECK constraint of 0033 is recreated with the new value — a new revision rather than
  an in-place edit of 0033.

## Why 0043 and not 0039

It was written as 0039 chaining from 0038, with 0040 (MP-11) re-pointed after it. But
production (Hetzner, `docs/despliegue-hetzner.md`) had already applied 0038 → 0040 → …
from `main`, and alembic treats every ancestor of the stamped revision as applied: a
0039 slotted *below* 0040 would never run there, leaving `brand_kits` without the font
columns the models select. Since the first deploy, migrations are additive and an
applied revision is never edited (`despliegue-hetzner.md`, "El primer despliegue cierra
ADR 27 R8a"), so this goes at the head instead and 0040 keeps chaining from 0038.

The DDL is idempotent (`IF NOT EXISTS` / `IF EXISTS`) on purpose: local databases that
ran the old 0039 → 0040 chain already hold the columns and the widened CHECK, and stay
stamped at 0040 — `alembic upgrade head` then runs 0041, 0042 and this one over them.
"""

from __future__ import annotations

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

_KINDS_WITH_FONT = "kind IN ('logo','logo_version','extra','font')"
_KINDS_BEFORE = "kind IN ('logo','logo_version','extra')"


def upgrade() -> None:
    op.execute("ALTER TABLE brand_kits ADD COLUMN IF NOT EXISTS font_heading text;")
    op.execute("ALTER TABLE brand_kits ADD COLUMN IF NOT EXISTS font_body text;")
    op.execute("ALTER TABLE brand_kit_assets DROP CONSTRAINT IF EXISTS ck_brand_kit_asset_kind;")
    op.create_check_constraint("ck_brand_kit_asset_kind", "brand_kit_assets", _KINDS_WITH_FONT)


def downgrade() -> None:
    # Font files recorded under the new kind would violate the old constraint: they go
    # first (their bytes stay in R2; nothing points at them any more).
    op.execute("DELETE FROM brand_kit_assets WHERE kind = 'font';")
    op.drop_constraint("ck_brand_kit_asset_kind", "brand_kit_assets", type_="check")
    op.create_check_constraint("ck_brand_kit_asset_kind", "brand_kit_assets", _KINDS_BEFORE)
    op.drop_column("brand_kits", "font_body")
    op.drop_column("brand_kits", "font_heading")
