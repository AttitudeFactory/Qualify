"""creators: inferred region and rubro of each public account, with provenance (m-25119461)

Revision ID: 0182
Revises: 0181
Create Date: 2026-11-25

RF-04 of the reel-filter epic (m-24872324, `docs/epica-filtrado-reels.md`): the Región
and Nicho filters need a country and a rubro per account. RF-00 measured 0 % of the
`referente`/`competencia` accounts with `creators.country_code` or `creators.category`
(and `category` is the network's own category, not the Brand Kit's rubro). These columns
hold what Qualify INFERS, kept apart from what the network reports (`country_code`,
`category` stay untouched):

- `region_code` — ISO 3166-1 alpha-2, or '' when unknown. Filled first from free sources
  (`qualify_api.creators.region_rubro`): the network's own country already on the row
  (`profile`), the `region` TikTok returns with each video in the cached vendor answers
  (`tiktok_region`), the location of the account's saved reels (`reel_location`), the
  country of the searches that surfaced it (`sightings`); and only when none answers,
  from the account review Claude already runs (`ai`, `referentes.ai`).
- `rubro` — a key of the Brand Kit's rubro catalog
  (`referentes.discovery_seed.NICHE_LABELS`: `food_drink`, `real_estate`…), `otro` when
  none fits, '' when not inferred yet. Only the AI review fills it.
- Provenance per value: `*_source`, `*_source_ref` (the `vendor_payloads` id, the
  sighting term or the reel id it came from), `*_model` ('' for a free source),
  `*_version` (prompt version for `ai`, pipeline version for a free source) and
  `*_inferred_at`.

## Why `creators` has no `tenant_id` and no RLS — and what protects it

`creators` is a GLOBAL table: one row per public TikTok/Instagram account, public data of
the network, shared by every business — the signed precedent of 0036 (H9 in
`docs/adr-42-ideas-reels-costo.md`; the same rule as the hashtag catalog, 0023). The
columns added here keep it that way: a country and a rubro describe the PUBLIC ACCOUNT,
inferred from what the account itself publishes (bio, category, captions, hashtags,
the region TikTok attaches to its videos), never from a business. Nothing here names a
tenant, a brand, a user or a label: which business follows which account, and as what,
stays in `brand_account_labels` (tenant_id + RLS ENABLE/FORCE + the NULLIF policy, 0020).
What protects the table is the role grants, unchanged from 0036: `qualify_app` may
SELECT/INSERT/UPDATE (never DELETE) and `qualify_admin` may only SELECT; there is no
business-specific data in it to isolate. `test_rls_policy_shape` enumerates only the
tables that own a `tenant_id`, so it must not and does not see this one;
`test_creators_region_rubro_db` pins that the new columns name no tenant.

Downgrade drops the columns, their checks and the index (the inferred values are lost;
the backfill re-derives the free ones from the cached answers at no cost).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0182"
down_revision = "0181"
branch_labels = None
depends_on = None

_TEXT_COLUMNS = (
    "region_code",
    "region_source",
    "region_source_ref",
    "region_model",
    "region_version",
    "rubro",
    "rubro_source",
    "rubro_source_ref",
    "rubro_model",
    "rubro_version",
)

_CHECKS = {
    "ck_creator_region_code": "region_code = '' OR region_code ~ '^[A-Z]{2}$'",
    "ck_creator_region_source": (
        "region_source IN ('', 'profile', 'tiktok_region', 'reel_location', 'sightings', 'ai')"
    ),
    # a value always says where it came from, and an empty one says nothing
    "ck_creator_region_provenance": (
        "(region_code = '') = (region_source = '') "
        "AND (region_code = '' OR region_inferred_at IS NOT NULL) "
        "AND (region_source <> 'ai' OR region_model <> '')"
    ),
    # the catalog's keys are snake_case ascii; the list itself lives in code
    "ck_creator_rubro": "rubro ~ '^[a-z_]*$'",
    "ck_creator_rubro_source": "rubro_source IN ('', 'ai')",
    "ck_creator_rubro_provenance": (
        "(rubro = '') = (rubro_source = '') "
        "AND (rubro = '' OR (rubro_inferred_at IS NOT NULL AND rubro_model <> ''))"
    ),
}


def upgrade() -> None:
    for name in _TEXT_COLUMNS:
        op.add_column("creators", sa.Column(name, sa.Text(), server_default="", nullable=False))
    op.add_column(
        "creators", sa.Column("region_inferred_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "creators", sa.Column("rubro_inferred_at", sa.DateTime(timezone=True), nullable=True)
    )
    for name, condition in _CHECKS.items():
        op.create_check_constraint(name, "creators", condition)
    # RF-01 / RF-07a filter the pool by region and rubro
    op.create_index("ix_creators_region_rubro", "creators", ["region_code", "rubro"])
    # Grants unchanged (0036): qualify_app SELECT/INSERT/UPDATE, qualify_admin SELECT —
    # column grants follow the table's, so nothing to add.


def downgrade() -> None:
    op.drop_index("ix_creators_region_rubro", table_name="creators")
    for name in reversed(list(_CHECKS)):
        op.drop_constraint(name, "creators", type_="check")
    op.drop_column("creators", "rubro_inferred_at")
    op.drop_column("creators", "region_inferred_at")
    for name in reversed(_TEXT_COLUMNS):
        op.drop_column("creators", name)
