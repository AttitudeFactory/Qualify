"""The paid «Buscar más cuentas en TikTok» of «Descubrir cuentas nuevas» can be charged
under its own feature (RF-07b, m-25119482, epic m-24872324, `docs/epica-filtrado-reels.md`
cost option B)

Revision ID: 0184
Revises: 0182
Create Date: 2026-11-25

When the free list of RF-07a (`qualify_api.creators.discover_accounts`) has fewer than
eight accounts, the owner may ask for a paid TikTok keyword search
(`qualify_api.creators.discover_paid`). It has its OWN budget per business — 50 credits a
local day, 200 a local month — summed over its own feature, so it never draws on the
Creators module's sub-budget (`creator_profile` + `creator_reels`) and its spend can be
read apart from the reels runs' (`reels_list`, `referentes_search`, ...). Every credit is
still booked by the metered gate inside the business's 150/600 cap (ADR 42 R5).

One CHECK widens; no table, column, grant or policy is added:

- `vendor_usage_events.ck_vendor_usage_feature` (ten features since 0167) gains
  `discover_accounts_search`. Tenant RLS of 0117 (`tenant_id = NULLIF(current_setting(
  'app.tenant_id', true), '')::uuid`, ENABLE + FORCE) is unchanged.

The raw answers go to `vendor_payloads` (0036, any path, 7-day TTL for a search) and the
accounts to the global `creators` / `creator_sightings` (kind `keyword`): no change there.

Numbering: `main` is at 0182 when this is written and 0183 is RF-05's
(`0183_reels_competitors`, not merged yet). Whichever lands second must be renumbered or
re-parented onto the other before merging (`just migration-guard`).

## Downgrade

Puts back 0167's ten-feature CHECK (validated). To do so it first **deletes** the
`discover_accounts_search` bookings — the same precedent as 0125 and 0167: what those
searches cost each business is lost, so its caps (the search's own 50/200 and the
business's 150/600) undercount that day and month. The answers stay in `vendor_payloads`,
so a repeated search inside the week is still served for free.
"""

from __future__ import annotations

from alembic import op

revision = "0184"
down_revision = "0182"
branch_labels = None
depends_on = None

_FEATURE_CHECK = "ck_vendor_usage_feature"
# 0167's ten (ADR 42 R5, the Creators module, the weekly hashtag read), and this search.
_TEN = (
    "'reels_list','reels_transcript','avatar_refresh','profile',"
    "'posts','referentes_search','trending','creator_profile','creator_reels',"
    "'hashtag_weekly'"
)
_ELEVEN = f"{_TEN},'discover_accounts_search'"


def upgrade() -> None:
    op.drop_constraint(_FEATURE_CHECK, "vendor_usage_events", type_="check")
    op.create_check_constraint(_FEATURE_CHECK, "vendor_usage_events", f"feature IN ({_ELEVEN})")


def downgrade() -> None:
    # The DELETE must reach every tenant's rows, never zero through RLS (as 0125, 0167).
    op.execute("SET LOCAL row_security = off;")
    op.execute("DELETE FROM vendor_usage_events WHERE feature = 'discover_accounts_search';")
    op.drop_constraint(_FEATURE_CHECK, "vendor_usage_events", type_="check")
    op.create_check_constraint(_FEATURE_CHECK, "vendor_usage_events", f"feature IN ({_TEN})")
