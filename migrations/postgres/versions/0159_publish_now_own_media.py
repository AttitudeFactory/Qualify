"""«Publicar» → «Tu semana»: an immediate publication becomes a piece and a calendar event
(m-25019217, epic m-25019215; founder 2026-11-13)

Revision ID: 0159
Revises: 0158
Create Date: 2026-11-13

A publication made from «Publicar» wrote only `publish_attempts`; the calendar reads only
`calendar_events`, whose cards read the piece (`content_drafts`). The founder decided that
an immediate publication shows in the calendar as published at the time it went out, and
becomes a reusable piece of the owner («Aprobados»), exempt from ADR 39's 90 days.
`planner.immediate.record_publication` writes both, after the attempt settled `published`.
Nothing here starts, retries or advances a publication.

- `content_briefs.kind` admits `'own_media'` (`ContentKind.OWN_MEDIA`): the owner's own
  photo(s) or video, never generated. The CHECK was last widened by 0119.
- `publish_attempts.media_object_key` / `media_content_type`: the object «Publicar» staged
  (`t/{tenant}/media/{connection}/{uuid}`) for a SINGLE attempt, written with the attempt
  row. A carousel's items already live in `publish_attempt_children` (0016). NULL on every
  attempt written before this revision (the backfill delivery m-25019220 reads Meta).
- `publish_attempts.permalink`: the publication's Instagram URL — filled by the next
  delivery; only the column here.
- `uq_cal_event_attempt`: partial UNIQUE `(tenant_id, publish_attempt_id) WHERE
  publish_attempt_id IS NOT NULL` — the second idempotency layer (`ON CONFLICT DO NOTHING`).
  The planner executor links one event to one attempt (`cal:{event}:{revision}` keys), so
  no duplicate is expected; the upgrade checks first and FAILS LOUDLY on any, rather than
  deleting data or building a half-made index.

Grants and RLS: no new table. `qualify_app` holds table-level SELECT/INSERT/UPDATE on
`publish_attempts` (0003) and on the creative tables, so the new columns are covered; the
column-level grant of `qualify_connection_purge` (0106, `raw_response_r2_key`) is
untouched. Every table written by `record_publication` (`content_briefs`,
`content_drafts`, `piece_versions`, `copy_variants`, `image_assets`, `calendar_events`)
already has `tenant_id` + forced RLS with the NULLIF policy.

**Downgrade** deletes the `own_media` pieces and what `record_publication` hangs from
them (their calendar events and tags, variants, assets, versions, drafts, briefs) —
`own_media` cannot be expressed below this revision — then restores the CHECK, drops the
index and the columns. The publications themselves stay in `publish_attempts`. A row some
OTHER feature made pointing at such a piece (a WhatsApp send, a review…) makes the delete
fail on its foreign key: the downgrade then aborts whole, nothing half-done, and an
operator decides. On an empty schema (the CI gate) nothing is deleted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0159"
down_revision = "0158"
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
)
_KINDS = (*_KINDS_BEFORE, "own_media")


def _kinds_check(kinds: tuple[str, ...]) -> str:
    return f"kind IN ({', '.join(repr(kind) for kind in kinds)})"


def upgrade() -> None:
    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.create_check_constraint("ck_content_briefs_kind", "content_briefs", _kinds_check(_KINDS))

    op.add_column("publish_attempts", sa.Column("media_object_key", sa.Text(), nullable=True))
    op.add_column("publish_attempts", sa.Column("media_content_type", sa.Text(), nullable=True))
    op.add_column("publish_attempts", sa.Column("permalink", sa.Text(), nullable=True))

    # Server-side, so the refusal also holds in offline (`--sql`) upgrades. Nothing is
    # deleted: an operator decides which duplicate event is the right one.
    op.execute(
        """
        DO $$
        DECLARE n bigint;
        BEGIN
            SELECT count(*) INTO n FROM (
                SELECT 1 FROM calendar_events
                WHERE publish_attempt_id IS NOT NULL
                GROUP BY tenant_id, publish_attempt_id
                HAVING count(*) > 1
            ) AS duplicated;
            IF n > 0 THEN
                RAISE EXCEPTION
                    '0159: % publish attempt(s) are linked to more than one calendar event; '
                    'resolve them by hand before creating uq_cal_event_attempt', n;
            END IF;
        END
        $$;
        """
    )
    op.create_index(
        "uq_cal_event_attempt",
        "calendar_events",
        ["tenant_id", "publish_attempt_id"],
        unique=True,
        postgresql_where=sa.text("publish_attempt_id IS NOT NULL"),
    )


def downgrade() -> None:
    # `own_media` pieces cannot exist below this revision: remove them and every row that
    # points at them, children first (the FKs are not all ON DELETE CASCADE).
    # The owner is a superuser; `row_security = off` makes a non-bypassing role fail
    # loudly instead of matching zero rows through FORCE RLS (as 0081, 0087, 0094 do).
    op.execute("SET LOCAL row_security = off;")
    owned_drafts = (
        "SELECT d.id FROM content_drafts d JOIN content_briefs b ON b.id = d.brief_id "
        "WHERE b.kind = 'own_media'"
    )
    op.execute(
        "DELETE FROM calendar_event_tags WHERE event_id IN "
        f"(SELECT id FROM calendar_events WHERE post_id IN ({owned_drafts}))"
    )
    op.execute(f"DELETE FROM calendar_events WHERE post_id IN ({owned_drafts})")
    # the draft points at its variant and version: unhook it BEFORE deleting them
    op.execute(
        "UPDATE content_drafts SET active_version_id = NULL, selected_variant_id = NULL "
        f"WHERE id IN ({owned_drafts})"
    )
    op.execute(f"DELETE FROM copy_variants WHERE draft_id IN ({owned_drafts})")
    op.execute(f"DELETE FROM image_assets WHERE draft_id IN ({owned_drafts})")
    op.execute(f"DELETE FROM piece_versions WHERE draft_id IN ({owned_drafts})")
    op.execute(f"DELETE FROM content_drafts WHERE id IN ({owned_drafts})")
    op.execute(
        "DELETE FROM content_briefs b WHERE b.kind = 'own_media' "
        "AND NOT EXISTS (SELECT 1 FROM content_drafts d WHERE d.brief_id = b.id)"
    )
    op.execute("SET LOCAL row_security = on;")

    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.create_check_constraint(
        "ck_content_briefs_kind", "content_briefs", _kinds_check(_KINDS_BEFORE)
    )

    op.drop_index("uq_cal_event_attempt", table_name="calendar_events")
    op.drop_column("publish_attempts", "permalink")
    op.drop_column("publish_attempts", "media_content_type")
    op.drop_column("publish_attempts", "media_object_key")
