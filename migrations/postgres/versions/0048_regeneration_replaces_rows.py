"""a regeneration replaces a draft's rows: DELETE on `copy_variants` for the app role

`finish_generation` writes the new copy variants of a regenerated draft with the same
ordinals as the previous revision's, and `uq_copy_variant_ordinal` (0009) refused them
— after the vendor had been paid (seen 2026-10-09 on every «Regenerar»). The repository
now deletes the draft's previous variants first, which the app role could not do:
0009's `_grants_and_rls` gave it SELECT, INSERT, UPDATE only. Same for `image_assets`,
whose rows the same method already replaced on paper (the DELETE there failed the same
way the moment a regeneration reached it).

Numbering: written as 0047 after the carousel kind; both moved up one when PR #110
took 0046 on 2026-10-09 (see 0047's docstring).
"""

from __future__ import annotations

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

_TABLES = ("copy_variants", "image_assets")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"GRANT DELETE ON {table} TO qualify_app;")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"REVOKE DELETE ON {table} FROM qualify_app;")
