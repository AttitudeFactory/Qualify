"""The weekly TikTok read per hashtag of a business's rubro can be charged and kept
(m-25026378, epic m-25026375 «Etiquetas que se están viendo»,
`docs/epica-etiquetas-publicaciones.md` entrega 3)

Revision ID: 0165
Revises: 0164
Create Date: 2026-11-13

Once a week, per business, `qualify_api.hashtags.weekly` reads up to five hashtags of its
rubro on TikTok (`/v1/tiktok/search/hashtag`) through the metered gate (ADR 42), charged
to that business's cap. Two CHECKs widen; no table, column, grant or policy is added.

- `vendor_usage_events.ck_vendor_usage_feature` (nine features since 0125) gains
  `hashtag_weekly`: every credit of the weekly read is booked under it, so it sums apart
  from the rest of the business's 150/600 (`usage.store().spent(features=...)`) and is
  what «this business already read this week» is asked of. Tenant RLS of 0117 unchanged.
- `hashtag_post_sightings.ck_hashtag_sighting_source` (0162: `referentes`,
  `public_reels`) gains `hashtag_weekly`: the provenance of a sighting that came from
  this read. Its `source_ref` is `tiktok:hashtag_weekly`, which 0162's
  `ck_hashtag_sighting_source_ref` (`<network>:<kind>`) already admits — a kind, never
  the hashtag that was read nor who asked for it. The table keeps 0162's rule: no
  tenant, no brand, no user, nothing that says which business triggered a read.

The raw answers go to `vendor_payloads` (0036), which already admits any path: no change.
That table is upserted on path + parameters, so each week's read REPLACES the previous one
for the same hashtag and region (and shares the row with the referentes search's cache of
the same first page): only the latest read of each can be re-parsed.

## Downgrade

Puts back both CHECKs exactly as 0125 and 0162 created them (validated). To do so it first
**deletes** the rows that only the wider CHECKs admit — the same precedent as 0125:

- the `hashtag_weekly` bookings of `vendor_usage_events` (kept, they would break 0125's
  own downgrade, which validates its nine-feature CHECK). What the weekly reads cost each
  business is lost, so its caps undercount that day and month; and the once-a-day hold
  of a failed attempt goes with them. After a downgrade and re-upgrade within the same
  week, a hashtag whose answer is still in `vendor_payloads` is not paid again, but one
  whose read had failed may be attempted — and paid — again at once;
- the `hashtag_weekly` sightings. They are derived: those of the latest read of each
  hashtag can be rebuilt from `vendor_payloads`, which the downgrade does not touch;
  those of earlier weeks cannot (their answers were replaced).
"""

from __future__ import annotations

from alembic import op

revision = "0165"
down_revision = "0164"
branch_labels = None
depends_on = None

_FEATURE_CHECK = "ck_vendor_usage_feature"
# 0125's nine (ADR 42 R5 + the Creators module), and the weekly hashtag read.
_NINE = (
    "'reels_list','reels_transcript','avatar_refresh','profile',"
    "'posts','referentes_search','trending','creator_profile','creator_reels'"
)
_TEN = f"{_NINE},'hashtag_weekly'"

_SOURCE_CHECK = "ck_hashtag_sighting_source"
_TWO_SOURCES = "'referentes','public_reels'"
_THREE_SOURCES = f"{_TWO_SOURCES},'hashtag_weekly'"


def upgrade() -> None:
    op.drop_constraint(_FEATURE_CHECK, "vendor_usage_events", type_="check")
    op.create_check_constraint(_FEATURE_CHECK, "vendor_usage_events", f"feature IN ({_TEN})")
    op.drop_constraint(_SOURCE_CHECK, "hashtag_post_sightings", type_="check")
    op.create_check_constraint(
        _SOURCE_CHECK, "hashtag_post_sightings", f"source IN ({_THREE_SOURCES})"
    )


def downgrade() -> None:
    # The DELETE must reach every tenant's rows, never zero through RLS (as 0125).
    op.execute("SET LOCAL row_security = off;")
    op.execute("DELETE FROM vendor_usage_events WHERE feature = 'hashtag_weekly';")
    op.drop_constraint(_FEATURE_CHECK, "vendor_usage_events", type_="check")
    op.create_check_constraint(_FEATURE_CHECK, "vendor_usage_events", f"feature IN ({_NINE})")
    op.execute("DELETE FROM hashtag_post_sightings WHERE source = 'hashtag_weekly';")
    op.drop_constraint(_SOURCE_CHECK, "hashtag_post_sightings", type_="check")
    op.create_check_constraint(
        _SOURCE_CHECK, "hashtag_post_sightings", f"source IN ({_TWO_SOURCES})"
    )
