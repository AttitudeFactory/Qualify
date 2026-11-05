"""Every paid ScrapeCreators feature can be charged to a business (m-24854849, ADR 42 R5).

Revision ID: 0124
Revises: 0123

0117 created `vendor_usage_events` with a CHECK that admits four features (`reels_list`,
`reels_transcript`, `avatar_refresh`, `profile`) — the reels run's and the avatars'. R5
charges EVERY paid read a business triggers to that business, so its caps (150 credits a
local day, 600 a local month) see all of them: the Brand Kit read also pays for the post
list (`posts`), the referentes search pays per search page (`referentes_search`), and the
trending screen pays for its feeds (`trending`). The gate's `FEATURES`
(`qualify_api.vendors.scrapecreators`) and this CHECK now list the same seven.

No new table, no new grant, RLS unchanged (0117's tenant policy on the table stands).

**Downgrade** puts the four-feature CHECK back as `NOT VALID`: rows already booked under
the three new features are kept (they are what a business spent, and the caps of the
older code still count them), and only new rows are held to the narrower list.
"""

from __future__ import annotations

from alembic import op

revision = "0124"
down_revision = "0123"
branch_labels = None
depends_on = None

_NAME = "ck_vendor_usage_feature"
_FOUR = "'reels_list','reels_transcript','avatar_refresh','profile'"
_SEVEN = _FOUR + ",'posts','referentes_search','trending'"


def upgrade() -> None:
    op.drop_constraint(_NAME, "vendor_usage_events", type_="check")
    op.create_check_constraint(_NAME, "vendor_usage_events", f"feature IN ({_SEVEN})")


def downgrade() -> None:
    op.drop_constraint(_NAME, "vendor_usage_events", type_="check")
    op.execute(
        f"ALTER TABLE vendor_usage_events ADD CONSTRAINT {_NAME} "
        f"CHECK (feature IN ({_FOUR})) NOT VALID"
    )
