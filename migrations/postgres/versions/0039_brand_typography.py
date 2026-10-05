"""brand typography: the kit's two type faces and their font files on the brandboard

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-05

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
  an in-place edit of 0033 (ADR 27 R8a allows the edit, but a dev database that already
  holds brandboards would need a full `just down` → `just dev` to see it).

Numbered 0039: it was written as 0038 on the Brand Kit branch while `main` landed its own
0038 (`catalog_and_template_runs`, the Remotion template engine), so it was renumbered
on merging (2026-10-05). The two touch different tables and do not depend on each other.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

_KINDS_WITH_FONT = "kind IN ('logo','logo_version','extra','font')"
_KINDS_BEFORE = "kind IN ('logo','logo_version','extra')"


def upgrade() -> None:
    op.add_column("brand_kits", sa.Column("font_heading", sa.Text(), nullable=True))
    op.add_column("brand_kits", sa.Column("font_body", sa.Text(), nullable=True))
    op.drop_constraint("ck_brand_kit_asset_kind", "brand_kit_assets", type_="check")
    op.create_check_constraint("ck_brand_kit_asset_kind", "brand_kit_assets", _KINDS_WITH_FONT)


def downgrade() -> None:
    # Font files recorded under the new kind would violate the old constraint: they go
    # first (their bytes stay in R2; nothing points at them any more).
    op.execute("DELETE FROM brand_kit_assets WHERE kind = 'font';")
    op.drop_constraint("ck_brand_kit_asset_kind", "brand_kit_assets", type_="check")
    op.create_check_constraint("ck_brand_kit_asset_kind", "brand_kit_assets", _KINDS_BEFORE)
    op.drop_column("brand_kits", "font_body")
    op.drop_column("brand_kits", "font_heading")
