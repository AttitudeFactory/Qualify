"""a regeneration replaces a draft's rows: DELETE on `copy_variants` for the app role

`finish_generation` writes the new copy variants of a regenerated draft with the same
ordinals as the previous revision's, and `uq_copy_variant_ordinal` (0009) refused them
— after the vendor had been paid (seen 2026-10-09 on every «Regenerar»). The repository
now deletes the draft's previous variants first, which the app role could not do:
0009's `_grants_and_rls` gave it SELECT, INSERT, UPDATE only. Same for `image_assets`,
whose rows the same method already replaced on paper (the DELETE there failed the same
way the moment a regeneration reached it).

Numbering: PR #106 (signup invites) also proposes a 0046; this one follows 0046 (the
carousel kind). Whichever merges second renumbers, as 0043 did.
"""

from __future__ import annotations

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

_TABLES = ("copy_variants", "image_assets")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"GRANT DELETE ON {table} TO qualify_app;")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"REVOKE DELETE ON {table} FROM qualify_app;")
