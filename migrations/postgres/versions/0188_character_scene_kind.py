"""character_scene_kind: a Clip's character scene is a draft kind of its own (m-25128784)

Revision ID: 0188
Revises: 0187
Create Date: 2026-11-26

Epic m-25026566, ADR 50 §12 (signed by Deivid on 2026-11-26). The brand's saved
character acts and speaks inside a scene with the business's product and place, made by
Seedance 2.5 in one omni-reference task. Each scene of a Clip's «Personajes» track is a
CHILD draft of the Clip (`parent_draft_id`, the link of 0119, its `part_index` its slot)
of a new kind, `character_scene` (`ContentKind.CHARACTER_SCENE`). Reusing `avatar_video`
/ `animated_avatar_video` was ruled out in §12.2: those kinds take the producer down the
presenter's path.

- `content_briefs.kind` admits `'character_scene'`. The CHECK was last widened by 0159.
  Nothing else changes: the scene's track lives in `content_briefs.media`
  (`character_scenes`, JSON), its charge in `creation_charges` (1 vista previa at
  creation, its seconds at the Clip's approval), its spend in `creative_usage_events`.

Grants and RLS: no new table, no new column. `content_briefs` keeps its `tenant_id`, its
forced RLS with the NULLIF policy and its grants.

Numbering: 0187 is m-25129385's (the saved characters' table), which lands first; this
revision sits on it (the coordinator's call, 2026-11-26).

**Downgrade** restores the CHECK of 0159. A `character_scene` brief cannot be expressed
below this revision, and its draft carries charges, usage events and vendor tasks of a
paid call: rather than delete that provenance, the downgrade REFUSES (fails loudly,
nothing half-done) while any such brief exists — an operator decides. On an empty schema
(the CI gate) there is none.
"""

from __future__ import annotations

from alembic import op

revision = "0188"
down_revision = "0187"
branch_labels = None
depends_on = None

_KINDS_BEFORE = (
    "creator_script",
    "avatar_video",
    "animated_avatar_video",
    "static_flyer",
    "template",
    "carousel",
    "clip",
    "shot_video",
    "own_media",
)
_KINDS = (*_KINDS_BEFORE, "character_scene")


def _kinds_check(kinds: tuple[str, ...]) -> str:
    return f"kind IN ({', '.join(repr(kind) for kind in kinds)})"


def upgrade() -> None:
    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.create_check_constraint("ck_content_briefs_kind", "content_briefs", _kinds_check(_KINDS))


def downgrade() -> None:
    # The owner is a superuser; `row_security = off` makes a non-bypassing role fail
    # loudly instead of counting zero rows through FORCE RLS (as 0159 does).
    op.execute("SET LOCAL row_security = off;")
    op.execute(
        """
        DO $$
        DECLARE n bigint;
        BEGIN
            SELECT count(*) INTO n FROM content_briefs WHERE kind = 'character_scene';
            IF n > 0 THEN
                RAISE EXCEPTION
                    '0188: % character scene brief(s) exist; they cannot be expressed below '
                    'this revision — remove them by hand (and their drafts) first', n;
            END IF;
        END
        $$;
        """
    )
    op.execute("SET LOCAL row_security = on;")
    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.create_check_constraint(
        "ck_content_briefs_kind", "content_briefs", _kinds_check(_KINDS_BEFORE)
    )
