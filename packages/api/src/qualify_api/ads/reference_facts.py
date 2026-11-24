"""Each business's monthly ad results, kept for sector references (m-25091393, PR 1 of 3).

One `ad_reference_facts` row per promotion × month, summed from `ad_promotion_insights` and
tagged with the group key (sector, country, currency, objective). Runs inside
`reads_cli.tick`, under the tenant's advisory lock and its own `tenant_session`; it reads
only rows already stored, so it calls neither Meta nor any other vendor.

Nothing is recorded until `QUALIFY_AD_REFERENCE_FROM` is set, and then only promotions
approved on or after it: no result is used retroactively. The aggregate across businesses
(and the minimums below) belongs to the builder of PR 2, which waits for ADR 51.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.messaging_attribution import _VISIBLE_ORIGINS
from qualify_api.referentes.discovery_seed import NICHE_LABELS

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "ad-reference-facts-v1"
# D6 (Raul, 2026-11-23): hypotheses, applied by the PR 2 builder, versioned together here.
METHOD_VERSION = "ad-reference-v1"
MIN_IMPRESSIONS = 1_000
MIN_CLICKS = 20
MIN_CONVERSATIONS = 5
DOMINANCE_CAP = 0.5
# shortcut: action name is Meta's documented one [S], unverified live; confirm it in the live
# test m-24828971 before the cost per conversation is published (m-25091391 decides).
META_CONVERSATION_ACTION = "onsite_conversion.messaging_conversation_started_7d"
CUTOFF_ENV = "QUALIFY_AD_REFERENCE_FROM"
CLOSED_AFTER_DAYS = 28

_UPSERT = text(
    """
WITH eligible AS (
  SELECT p.id, p.brand_id, p.objective, p.currency, p.targeting,
    p.request_snapshot->'audience_snapshot'->'location' AS location
  FROM ad_promotions p WHERE p.approved_at >= :cutoff
),
months AS (
  SELECT i.promotion_id, date_trunc('month', i.day)::date AS month,
    -- shortcut: Insights `spend` taken as a major-unit decimal ("5339.5"), as results.py and
    -- budget_suggestion.py already assume; unverified live, confirm in m-24828971.
    COALESCE(sum(round((i.metrics->>'spend')::numeric * 100)), 0)::bigint AS spend_minor,
    COALESCE(sum((i.metrics->>'impressions')::bigint), 0) AS impressions,
    COALESCE(sum((i.metrics->>'clicks')::bigint), 0) AS clicks,
    round(sum((SELECT sum((x->>'value')::numeric)
      FROM jsonb_array_elements(CASE WHEN jsonb_typeof(i.metrics->'actions') = 'array'
        THEN i.metrics->'actions' ELSE '[]'::jsonb END) x
      WHERE x->>'action_type' = :meta_action)))::int AS conversations_meta,
    count(*)::int AS days,
    max(i.observed_at) AS source_observed_at,
    max(i.pipeline_version) AS source_pipeline_version
  FROM ad_promotion_insights i
  -- Never mix currencies: only days in the promotion's own (the account's) currency.
  JOIN eligible e ON e.id = i.promotion_id AND i.currency = e.currency
  WHERE NOT EXISTS (SELECT 1 FROM ad_reference_facts f WHERE f.promotion_id = i.promotion_id
    AND f.month = date_trunc('month', i.day)::date AND f.closed)
  GROUP BY 1, 2
),
observed AS (
  -- Qualify's own count: distinct threads attributed to the promotion (same definition as
  -- messaging_attribution.promotion_conversation_count), in the month of their first message.
  -- shortcut: buckets by the business time zone, not the ad account's; equal for every
  -- account seen so far, switch to ad_accounts.timezone_name if they ever differ.
  SELECT promotion_id, month, count(*)::int AS threads FROM (
    SELECT a.promotion_id, m.thread_id,
      date_trunc('month', min(a.attributed_at)
        AT TIME ZONE COALESCE((SELECT NULLIF(timezone, '') FROM tenants
          WHERE id = :tenant), 'UTC'))::date AS month
    """
    + _VISIBLE_ORIGINS
    + """
      AND a.promotion_id IN (SELECT id FROM eligible)
    GROUP BY 1, 2
  ) first_messages GROUP BY 1, 2
),
facts AS (
  SELECT mo.*, e.brand_id, e.objective, e.currency,
    (SELECT CASE WHEN bk.connect->>'sector' = ANY(CAST(:sectors AS text[]))
       THEN bk.connect->>'sector' END
     FROM brand_kit_details bk WHERE bk.brand_id = e.brand_id) AS sector,
    CASE WHEN e.location->>'country_code' ~ '^[A-Z]{2}$' THEN e.location->>'country_code'
      WHEN upper(t.country) ~ '^[A-Z]{2}$' THEN upper(t.country) END AS country_code,
    CASE WHEN e.location->>'country_code' ~ '^[A-Z]{2}$' THEN 'targeting' ELSE 'tenant'
      END AS geo_source,
    CASE WHEN e.location IS NOT NULL
      THEN CASE WHEN e.location->>'type' = 'city' THEN e.location->>'key' END
      ELSE e.targeting->'geo_locations'->'cities'->0->>'key' END AS city_key,
    COALESCE(o.threads, 0) AS conversations_observed
  FROM months mo
  JOIN eligible e ON e.id = mo.promotion_id
  JOIN tenants t ON t.id = :tenant
  LEFT JOIN observed o ON o.promotion_id = mo.promotion_id AND o.month = mo.month
)
INSERT INTO ad_reference_facts AS f (tenant_id, promotion_id, month, brand_id, sector,
  sector_read_at, country_code, geo_source, city_key, currency, objective, spend_minor,
  impressions, clicks, conversations_meta, conversations_observed, days, source_observed_at,
  source_pipeline_version, pipeline_version, method_version, closed, updated_at)
SELECT :tenant, promotion_id, month, brand_id, sector, :now, country_code, geo_source,
  CASE WHEN city_key ~ '^[0-9]{1,30}$' THEN city_key END, currency, objective, spend_minor,
  impressions, clicks, conversations_meta, conversations_observed, days, source_observed_at,
  source_pipeline_version, :pipeline, :method,
  (month + interval '1 month' - interval '1 day')::date
    + CAST(:closed_after AS integer) < :today, :now
FROM facts WHERE country_code IS NOT NULL
ON CONFLICT (promotion_id, month) DO UPDATE SET sector = EXCLUDED.sector,
  sector_read_at = EXCLUDED.sector_read_at, country_code = EXCLUDED.country_code,
  geo_source = EXCLUDED.geo_source, city_key = EXCLUDED.city_key,
  spend_minor = EXCLUDED.spend_minor, impressions = EXCLUDED.impressions,
  clicks = EXCLUDED.clicks, conversations_meta = EXCLUDED.conversations_meta,
  conversations_observed = EXCLUDED.conversations_observed, days = EXCLUDED.days,
  source_observed_at = EXCLUDED.source_observed_at,
  source_pipeline_version = EXCLUDED.source_pipeline_version,
  pipeline_version = EXCLUDED.pipeline_version, method_version = EXCLUDED.method_version,
  closed = EXCLUDED.closed, updated_at = EXCLUDED.updated_at
WHERE NOT f.closed AND (f.sector, f.country_code, f.geo_source, f.city_key, f.spend_minor,
  f.impressions, f.clicks, f.conversations_meta, f.conversations_observed, f.days,
  f.source_pipeline_version, f.pipeline_version, f.method_version, f.closed)
  IS DISTINCT FROM (EXCLUDED.sector, EXCLUDED.country_code, EXCLUDED.geo_source,
  EXCLUDED.city_key, EXCLUDED.spend_minor, EXCLUDED.impressions, EXCLUDED.clicks,
  EXCLUDED.conversations_meta, EXCLUDED.conversations_observed, EXCLUDED.days,
  EXCLUDED.source_pipeline_version, EXCLUDED.pipeline_version, EXCLUDED.method_version,
  EXCLUDED.closed)
"""
)


def cutoff() -> datetime | None:
    """`QUALIFY_AD_REFERENCE_FROM` as an aware datetime; unset or invalid → None (record
    nothing). A bare date means midnight UTC."""
    raw = os.environ.get(CUTOFF_ENV, "").strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("%s is not an ISO date; ad reference facts are not recorded", CUTOFF_ENV)
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def record_reference_facts(*, tenant_id: UUID, now: datetime | None = None) -> int:
    """Upsert this business's open months; closed months stay frozen. Returns rows changed
    (an unchanged month is not rewritten)."""
    since = cutoff()
    if since is None:
        return 0
    now = now or datetime.now(UTC)
    today: date = now.astimezone(UTC).date()
    with tenant_session(tenant_id) as session:
        result = session.execute(
            _UPSERT,
            {
                "tenant": tenant_id,
                "cutoff": since,
                "now": now,
                "today": today,
                "closed_after": CLOSED_AFTER_DAYS,
                "sectors": sorted(NICHE_LABELS),
                "meta_action": META_CONVERSATION_ACTION,
                "pipeline": PIPELINE_VERSION,
                "method": METHOD_VERSION,
            },
        )
        return result.rowcount
