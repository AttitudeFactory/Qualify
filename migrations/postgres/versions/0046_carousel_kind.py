"""carousel kind: `content_briefs.kind` admits 'carousel' (§ request 2026-10-09)

The generator gains a fifth kind, `ContentKind.CAROUSEL` — a feed carousel the operator
lays out slide by slide (a generated scene, that scene animated, or a file of a piece the
brand already made). Its slides travel in the brief's `media` JSONB like every other
kind's inputs, so the only schema change is the CHECK of 0026 widened by one value.

Numbering: PR #106 (signup invites) also proposes a 0046. Whichever merges second
renumbers its revision and points `down_revision` at the other, as 0043 did.
"""

from __future__ import annotations

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

_KINDS_BEFORE = (
    "creator_script",
    "avatar_video",
    "animated_avatar_video",
    "static_flyer",
    "template",
)
_KINDS = (*_KINDS_BEFORE, "carousel")


def _check(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{kind}'" for kind in kinds) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.create_check_constraint("ck_content_briefs_kind", "content_briefs", _check(_KINDS))


def downgrade() -> None:
    # a carousel brief cannot be expressed before this revision: it reads as the closest
    # kind, the advertising image (whose carousel it extends), as 0026 did for old rows
    op.execute("UPDATE content_briefs SET kind = 'static_flyer' WHERE kind = 'carousel'")
    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.create_check_constraint("ck_content_briefs_kind", "content_briefs", _check(_KINDS_BEFORE))
