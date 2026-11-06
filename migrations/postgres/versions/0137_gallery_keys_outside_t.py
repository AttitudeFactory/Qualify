"""business media keys move from `t/{tenant}/gallery/` to `gallery/{tenant}/`

Revision ID: 0137
Revises: 0136
Create Date: 2026-11-06

Ticket m-24971181 (epic m-24955913; follows 0133, m-24955918). The production R2 bucket
keeps a lock rule on `t/` that refuses deletes and overwrites (founder, 2026-11-06), and
the Galería must really delete what the owner removes or cuts away (D4, ADR 47 and the
ADR 39 amendment). Its files therefore live at `gallery/{tenant}/{media_id}/<file>`,
outside `t/`. The `ObjectGate` builds those keys from UUIDs (`put_gallery_media`).

This revision only swaps `ck_business_media_key`, the CHECK that ties `object_key` and
`poster_key` to the medium's own folder, from the old shape to the new one. No row is
rewritten: production holds no Galería rows yet (the Galería screen, CM-2, is unmerged,
and every upload path goes through that screen). If a row with an old key did exist, the
`ADD CONSTRAINT` would fail loudly instead of leaving a key the gate refuses to delete.

**Downgrade** restores the 0133 CHECK; it fails the same way if rows with new keys exist
(delete them through «Quitar» first — never by hand in R2).
"""

from __future__ import annotations

from alembic import op

revision = "0137"
down_revision = "0136"
branch_labels = None
depends_on = None

_TABLE = "business_media"
_NAME = "ck_business_media_key"


def _check(root: str) -> str:
    """`object_key` (and `poster_key`, when set) = `<root>` + `<id>/<one file name>`."""
    folder = f"{root} || id::text || '/'"
    return (
        f"object_key = {folder} || split_part(object_key, '/', 4)"
        " AND split_part(object_key, '/', 4) <> ''"
        f" AND (poster_key IS NULL OR (poster_key = {folder}"
        " || split_part(poster_key, '/', 4) AND split_part(poster_key, '/', 4) <> ''))"
    )


#: New: `gallery/{tenant}/{id}/<file>` — 4 segments.
_NEW = _check("'gallery/' || tenant_id::text || '/'")
#: 0133's: `t/{tenant}/gallery/{id}/<file>` — 5 segments (kept verbatim for the downgrade).
_OLD = (
    "object_key = 't/' || tenant_id::text || '/gallery/' || id::text || '/'"
    " || split_part(object_key, '/', 5)"
    " AND split_part(object_key, '/', 5) <> ''"
    " AND (poster_key IS NULL OR poster_key ="
    " 't/' || tenant_id::text || '/gallery/' || id::text || '/'"
    " || split_part(poster_key, '/', 5) AND split_part(poster_key, '/', 5) <> '')"
)


def upgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _NEW)


def downgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _OLD)
