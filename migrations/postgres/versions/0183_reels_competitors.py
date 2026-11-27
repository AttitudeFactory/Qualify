"""reels of the competitors: the owner's 6 weekly picks, «Ver sus reels ahora» and their
spend apart (m-25119465)

Revision ID: 0183
Revises: 0182
Create Date: 2026-11-25

RF-05 of the reel-filter epic (m-24872324, `docs/epica-filtrado-reels.md`, decision 5,
cost option B signed by Deivid on 2026-11-25; amends R4/R8 of
`docs/adr-42-ideas-reels-costo.md`). Until now the reels run read only the accounts
labelled `referente`; the ones labelled `competencia` gave no reel at all. Three changes,
no new table:

- `brand_account_labels.read_weekly` (boolean, default false) — which `competencia`
  accounts the owner chose to have read every Monday (at most 6, enforced by
  `qualify_api.referentes.competitors`). None chosen = the first 6 by `position`. A
  column of a table that already has `tenant_id` + RLS ENABLE/FORCE + the NULLIF policy
  (0020): no grant or policy to add (`qualify_app` already has UPDATE). No index: the picks
  are read with the brand's labels (`uq_account_label`, `brand_id` first).
- `brand_reel_runs` — the manual read of ONE competitor («Ver sus reels ahora») is a run
  of its own, trigger `competitor_now`, that names its account (`account_network`,
  `account_handle`, set exactly for that trigger). `uq_brand_reel_run` keeps its name
  (`ON CONFLICT ON CONSTRAINT uq_brand_reel_run` keeps working) but now spans the
  account too, `NULLS NOT DISTINCT` (PostgreSQL 15+): one weekly run per brand and day as
  before, and one manual read per brand, account and day — a second click returns the
  same row (idempotent). The weekly run's spend on competitors is kept apart in
  `competitor_credits` / `competitor_cost_usd` (a part of `credits` / `cost_usd`, never
  more); a `competitor_now` run is all competitor spend, both columns equal its totals.
- `vendor_usage_events.ck_vendor_usage_feature` (ten since 0167) gains
  `competitor_reels_list` and `competitor_reels_transcript`: the gate books a
  competitor's list pages and transcripts under them (`usage.UsageCharge.account_label`),
  so they sum apart from the referentes' `reels_list` / `reels_transcript` inside the same
  150/600 caps of the business. Tenant RLS of 0117 unchanged.

The reels-worker's door (`qualify_reels_worker`, 0134) gets no new column: the queue
reads `trigger`, which it already may.

## Downgrade

Puts everything back exactly as 0117/0134/0167 left it. To do so it first **deletes**
what only this revision admits (RLS off, so every tenant's rows go, as 0167 does): the
`competitor_now` runs (and any idea row pointing at one — there are none by design) and
the bookings under the two competitor features. The owner's picks and the competitor
split of the weekly runs are lost; the caps of the day and month undercount what the
competitor reads cost.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0183"
down_revision = "0182"
branch_labels = None
depends_on = None

_RUNS = "brand_reel_runs"
_LABELS = "brand_account_labels"
_USAGE = "vendor_usage_events"

_FEATURE_CHECK = "ck_vendor_usage_feature"
# 0167's ten, and the two competitor features of RF-05.
_TEN = (
    "'reels_list','reels_transcript','avatar_refresh','profile',"
    "'posts','referentes_search','trending','creator_profile','creator_reels',"
    "'hashtag_weekly'"
)
_TWELVE = f"{_TEN},'competitor_reels_list','competitor_reels_transcript'"

_TRIGGER_CHECK = "ck_brand_reel_run_trigger"
_THREE_TRIGGERS = "'weekly','manual','operator_90d'"
_FOUR_TRIGGERS = f"{_THREE_TRIGGERS},'competitor_now'"

_HANDLE_CHECK = (
    "account_handle <> '' AND account_handle = lower(account_handle) "
    "AND left(account_handle, 1) <> '@'"
)
_NEW_CHECKS = {
    # the account is named exactly by a manual competitor read
    "ck_brand_reel_run_account": (
        "(trigger = 'competitor_now') = (account_network IS NOT NULL) "
        "AND (account_network IS NULL) = (account_handle IS NULL)"
    ),
    "ck_brand_reel_run_account_network": (
        "account_network IS NULL OR account_network IN ('tiktok','instagram')"
    ),
    "ck_brand_reel_run_account_handle": f"account_handle IS NULL OR ({_HANDLE_CHECK})",
    # the competitor part of a run's spend is never more than the run's spend
    "ck_brand_reel_run_competitor_spend": (
        "competitor_credits >= 0 AND competitor_cost_usd >= 0 "
        "AND competitor_credits <= credits AND competitor_cost_usd <= cost_usd"
    ),
}


def upgrade() -> None:
    # 1. the owner's weekly picks among its competitors
    op.add_column(
        _LABELS,
        sa.Column("read_weekly", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    # 2. the manual read of one competitor, and the competitor part of a run's spend
    op.add_column(_RUNS, sa.Column("account_network", sa.Text(), nullable=True))
    op.add_column(_RUNS, sa.Column("account_handle", sa.Text(), nullable=True))
    op.add_column(
        _RUNS,
        sa.Column("competitor_credits", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        _RUNS,
        sa.Column("competitor_cost_usd", sa.Numeric(12, 6), server_default="0", nullable=False),
    )
    op.drop_constraint(_TRIGGER_CHECK, _RUNS, type_="check")
    op.create_check_constraint(_TRIGGER_CHECK, _RUNS, f"trigger IN ({_FOUR_TRIGGERS})")
    for name, condition in _NEW_CHECKS.items():
        op.create_check_constraint(name, _RUNS, condition)
    op.drop_constraint("uq_brand_reel_run", _RUNS, type_="unique")
    op.execute(
        "ALTER TABLE brand_reel_runs ADD CONSTRAINT uq_brand_reel_run UNIQUE NULLS NOT "
        "DISTINCT (brand_id, trigger, run_date, account_network, account_handle);"
    )

    # 3. the competitor features of the usage ledger
    op.drop_constraint(_FEATURE_CHECK, _USAGE, type_="check")
    op.create_check_constraint(_FEATURE_CHECK, _USAGE, f"feature IN ({_TWELVE})")


def downgrade() -> None:
    # The DELETEs must reach every tenant's rows, never zero through RLS (as 0167).
    op.execute("SET LOCAL row_security = off;")

    op.execute(
        "DELETE FROM vendor_usage_events "
        "WHERE feature IN ('competitor_reels_list','competitor_reels_transcript');"
    )
    op.drop_constraint(_FEATURE_CHECK, _USAGE, type_="check")
    op.create_check_constraint(_FEATURE_CHECK, _USAGE, f"feature IN ({_TEN})")

    op.execute(
        "DELETE FROM brand_reel_ideas WHERE run_id IN "
        "(SELECT id FROM brand_reel_runs WHERE trigger = 'competitor_now');"
    )
    op.execute("DELETE FROM brand_reel_runs WHERE trigger = 'competitor_now';")
    op.drop_constraint("uq_brand_reel_run", _RUNS, type_="unique")
    op.create_unique_constraint("uq_brand_reel_run", _RUNS, ["brand_id", "trigger", "run_date"])
    for name in reversed(list(_NEW_CHECKS)):
        op.drop_constraint(name, _RUNS, type_="check")
    op.drop_constraint(_TRIGGER_CHECK, _RUNS, type_="check")
    op.create_check_constraint(_TRIGGER_CHECK, _RUNS, f"trigger IN ({_THREE_TRIGGERS})")
    op.drop_column(_RUNS, "competitor_cost_usd")
    op.drop_column(_RUNS, "competitor_credits")
    op.drop_column(_RUNS, "account_handle")
    op.drop_column(_RUNS, "account_network")

    op.drop_column(_LABELS, "read_weekly")
