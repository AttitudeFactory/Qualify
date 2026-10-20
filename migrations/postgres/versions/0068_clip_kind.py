"""clip kind: `content_briefs.kind` admits 'clip'

Revision ID: 0068
Revises: 0067
Create Date: 2026-10-20

`ContentKind.CLIP` (§ request 2026-10-14 — a generated Seedance video with no presenter,
from frames and references) reached the generator without this revision: the CHECK of
0026/0047 still listed six kinds, so every clip brief was refused at INSERT and the
operator read «No se pudo hablar con la base de datos» (found 2026-10-20 — the dev DB
holds no clip brief at all). Like 0047, the only schema change is that CHECK widened by
one value: a clip's frames and references travel in the brief's `media` JSONB.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None

_KINDS_BEFORE = (
    "creator_script",
    "avatar_video",
    "animated_avatar_video",
    "static_flyer",
    "template",
    "carousel",
)
_KINDS = (*_KINDS_BEFORE, "clip")


def _check(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{kind}'" for kind in kinds) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.create_check_constraint("ck_content_briefs_kind", "content_briefs", _check(_KINDS))


def downgrade() -> None:
    # A clip brief cannot be expressed before this revision, and no other kind can hold
    # it: its `media` carries frames and references that every other kind's validation
    # refuses, so rewriting its kind would leave drafts that no longer load (review
    # 2026-10-20). Refuse instead of corrupting; on an empty schema (the CI gate) this
    # never fires.
    clips = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM content_briefs WHERE kind = 'clip'"))
        .scalar_one()
    )
    if clips:
        raise RuntimeError(
            f"{clips} clip brief(s) exist: delete or export them before downgrading below 0068"
        )
    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.create_check_constraint("ck_content_briefs_kind", "content_briefs", _check(_KINDS_BEFORE))
