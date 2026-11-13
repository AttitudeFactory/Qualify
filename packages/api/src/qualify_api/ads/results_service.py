"""Authenticated promotion reads and audited, guarded pause; never enables spending."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.client import MarketingAPI, MarketingClient
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.results import (
    MANAGEMENT_REASON,
    PIPELINE_VERSION,
    STATUS_LABELS,
    DailyInsight,
    PromotionResults,
    PromotionResultSummary,
    ResultsUnavailable,
    nonnegative,
    parse_insight,
    review_reason,
    safe_review_text,
)
from qualify_api.connections.ad_accounts import (
    AdAccountUnavailable,
    AdConnection,
    _authenticated_client,
    _connection,
    _permission_reason,
)
from qualify_api.tenancy.acting import current_acting_login, require_acting_member

if TYPE_CHECKING:
    from qualify_api.ads.edit_review import PreparedPromotionEdit, PromotionEditResult

UNAVAILABLE = (
    "No pudimos consultar esta promoción. Revisa la cuenta publicitaria e inténtalo de nuevo."
)
UNCERTAIN = "No pudimos confirmar la pausa. Actualiza el estado antes de intentar otro cambio."
POLL_INTERVAL = timedelta(minutes=25)


def _member(tenant_id: UUID, *, system: bool = False) -> None:
    if not system and current_acting_login() is None:
        raise ResultsUnavailable("Vuelve a entrar para consultar tus anuncios.")
    require_acting_member(tenant_id)


@dataclass(frozen=True)
class ResultScope:
    tenant_id: UUID
    promotion_id: UUID
    account_id: UUID
    connection: AdConnection
    meta_account_id: str
    ad_id: str
    adset_id: str
    campaign_id: str
    currency: str
    timezone_name: str


def _scope(tenant: UUID, promotion: UUID, *, system: bool = False) -> ResultScope:
    _member(tenant, system=system)
    with tenant_session(tenant, independent=True) as s:
        rows = (
            s.execute(
                text("""
            SELECT p.id,p.meta_ad_account_id,p.meta_ad_id,p.meta_adset_id,p.meta_campaign_id,
                   p.currency,a.id AS account_id,a.connection_id,a.timezone_name
            FROM ad_promotions p JOIN ad_accounts a
              ON a.tenant_id=p.tenant_id AND a.brand_id=p.brand_id
              AND a.ad_account_id=p.meta_ad_account_id AND a.currency=p.currency
            JOIN social_connections c ON c.id=a.connection_id AND c.tenant_id=a.tenant_id
              AND c.brand_id=p.brand_id
            JOIN publish_attempts pub ON pub.id=p.publish_attempt_id AND pub.tenant_id=p.tenant_id
              AND pub.connection_id=c.id AND pub.published_media_id=p.source_media_id
            JOIN calendar_events e ON e.publish_attempt_id=pub.id AND e.tenant_id=p.tenant_id
              AND e.connection_id=c.id AND e.brand_id=p.brand_id AND e.post_id=p.content_draft_id
            WHERE p.id=:id AND a.selected AND a.available
              AND a.credential_version=c.current_credential_version
              AND c.purged_at IS NULL AND c.purge_started_at IS NULL
            """),
                {"id": promotion},
            )
            .mappings()
            .all()
        )
        if not rows:
            # A distinct durable ownership path; do not weaken the published joins.
            rows = (
                s.execute(
                    text("""
              SELECT p.id,p.meta_ad_account_id,p.meta_ad_id,p.meta_adset_id,p.meta_campaign_id,
                     p.currency,a.id AS account_id,a.connection_id,a.timezone_name
              FROM ad_promotions p JOIN ad_unpublished_sources u
                ON u.promotion_id=p.id AND u.tenant_id=p.tenant_id
                AND u.draft_id=p.content_draft_id AND u.brand_id=p.brand_id
              JOIN ad_accounts a ON a.id=u.ad_account_id AND a.tenant_id=u.tenant_id
                AND a.brand_id=u.brand_id AND a.ad_account_id=p.meta_ad_account_id
                AND a.currency=p.currency AND a.connection_id=u.connection_id
              JOIN social_connections c ON c.id=u.connection_id AND c.tenant_id=u.tenant_id
                AND c.brand_id=u.brand_id
              WHERE p.id=:id AND p.publish_attempt_id IS NULL AND p.source_media_id IS NULL
                AND a.selected AND a.available AND c.status='active'
                AND a.credential_version=c.current_credential_version
                AND c.purged_at IS NULL AND c.purge_started_at IS NULL
                AND u.source->>'credential_version'=c.current_credential_version::text
              """),
                    {"id": promotion},
                )
                .mappings()
                .all()
            )
        if len(rows) != 1:
            raise ResultsUnavailable(UNAVAILABLE)
        row = rows[0]
        if not all(
            isinstance(row[k], str) and row[k].isdigit()
            for k in ("meta_ad_id", "meta_adset_id", "meta_campaign_id", "meta_ad_account_id")
        ):
            raise ResultsUnavailable("Esta promoción todavía no tiene un anuncio creado en Meta.")
        connection = _connection(s, row["connection_id"])
        if _permission_reason(connection):
            raise ResultsUnavailable(UNAVAILABLE)
        try:
            ZoneInfo(row["timezone_name"])
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            raise ResultsUnavailable(
                "Falta comprobar la zona horaria de la cuenta publicitaria."
            ) from None
        return ResultScope(
            tenant,
            promotion,
            row["account_id"],
            connection,
            row["meta_ad_account_id"],
            row["meta_ad_id"],
            row["meta_adset_id"],
            row["meta_campaign_id"],
            row["currency"],
            row["timezone_name"],
        )


def _same(scope: ResultScope, *, system: bool = False) -> None:
    if _scope(scope.tenant_id, scope.promotion_id, system=system) != scope:
        raise ResultsUnavailable(
            "Cambiaste la cuenta de anuncios mientras guardábamos. "
            "Ábrela de nuevo y vuelve a intentarlo."
        )


def _summary(row: Any) -> PromotionResultSummary:
    from qualify_api.ads.edit_ledger import overlay
    from qualify_api.ads.promotions import Promotion

    checked = row["checked_at"] if row["cache_current"] else None
    status = row["observed_status"] if checked is not None else "UNKNOWN"
    status = status if status in STATUS_LABELS else "UNKNOWN"
    stale = (
        checked is None or checked < datetime.now(UTC) - POLL_INTERVAL or row["read_failed"] is True
    )
    feedback = row.get("review_feedback")
    specific = ""
    if (
        isinstance(feedback, dict)
        and checked is not None
        and (
            feedback.get("source_id") == row["meta_ad_id"]
            and feedback.get("account_id") == row["meta_ad_account_id"]
            and feedback.get("checked_at") == checked.isoformat()
            and feedback.get("pipeline_version") == "ad-review-reason-v1"
        )
    ):
        specific = safe_review_text([{"error_summary": feedback.get("reason")}])
    current_budget, current_end = None, None
    editable = False
    try:
        effective = overlay(
            Promotion(row["id"], row["request_snapshot"]), row.get("edit_operations", [])
        )
        current_budget = effective.request["budget_minor"]
        current_end = datetime.fromisoformat(effective.request["end_time"])
        editable = bool(
            not stale
            and row["can_read"]
            and not row["outstanding"]
            and row["status"] == "active"
            and row.get("activation_confirmed", False)
            and effective.request.get("currency") == "COP"
            and effective.request.get("meta_currency_offset") == 1
            and effective.request.get("budget_kind") == "lifetime"
            and row.get("publish_attempt_id") is not None
        )
    except (ResultsUnavailable, KeyError, TypeError, ValueError):
        pass
    return PromotionResultSummary(
        row["id"],
        row["brand_id"],
        status,
        STATUS_LABELS.get(status, "Estado por comprobar"),
        row["currency"],
        current_budget if current_budget is not None else row["budget_minor"],
        row["budget_kind"],
        current_end if current_end is not None else row["end_time"],
        checked,
        review_reason(status, specific),
        caption=row["source_caption"],
        account_name=row["account_name"] or "",
        timezone_name=row["timezone_name"] or "",
        stale=stale,
        refresh_failed=bool(row["read_failed"]),
        current_budget_minor=current_budget,
        current_end_time=current_end,
        can_manage=editable,
        management_reason="" if editable else MANAGEMENT_REASON,
        can_resume=editable and status in {"PAUSED", "ADSET_PAUSED", "CAMPAIGN_PAUSED"},
        operation_pending=bool(row["outstanding"]),
        can_pause=bool(
            not stale
            and row["can_read"]
            and not row["outstanding"]
            and status
            in {
                "ACTIVE",
                "PENDING_REVIEW",
                "IN_PROCESS",
                "PREAPPROVED",
                "WITH_ISSUES",
            }
        ),
    )


_SUMMARY_SQL = """
    SELECT p.*,o.checked_at,o.insights_checked_at,o.read_failed,o.insights_read_failed,
      o.effective_status AS observed_status,
      a.name AS account_name,a.timezone_name,
      CASE WHEN source.id IS NOT NULL AND pub.status='published'
        THEN LEFT(COALESCE(pub.caption,''),160) ELSE '' END AS source_caption,
      (a.available AND a.selected AND a.credential_version=c.current_credential_version
       AND c.purged_at IS NULL AND c.purge_started_at IS NULL) AS can_read,
      (o.account_id=a.id AND o.credential_version=c.current_credential_version
       AND a.available AND a.selected AND c.purged_at IS NULL
       AND c.purge_started_at IS NULL) AS cache_current,
      EXISTS(SELECT 1 FROM ad_promotion_operations x WHERE x.promotion_id=p.id
             AND x.state IN ('in_flight','unknown')) AS outstanding,
      EXISTS(SELECT 1 FROM ad_promotion_activations x WHERE x.promotion_id=p.id
        AND x.tenant_id=p.tenant_id AND x.state='active' AND x.confirmed_by IS NOT NULL
        AND x.confirmed_at IS NOT NULL) AS activation_confirmed,
      COALESCE((SELECT jsonb_agg(jsonb_build_object('id',x.id,'state',x.state,
        'action',x.action,'payload',x.payload,'approval_evidence',x.approval_evidence)
        ORDER BY x.created_at,x.id) FROM ad_promotion_operations x
        WHERE x.promotion_id=p.id AND x.tenant_id=p.tenant_id),'[]'::jsonb) AS edit_operations
    FROM ad_promotions p LEFT JOIN ad_promotion_observations o ON o.promotion_id=p.id
      AND o.tenant_id=p.tenant_id
    LEFT JOIN ad_accounts a ON a.id=o.account_id AND a.tenant_id=p.tenant_id
      AND a.brand_id=p.brand_id AND a.ad_account_id=p.meta_ad_account_id
    LEFT JOIN social_connections c ON c.id=a.connection_id AND c.tenant_id=a.tenant_id
    LEFT JOIN publish_attempts pub ON pub.id=p.publish_attempt_id AND pub.tenant_id=p.tenant_id
      AND pub.published_media_id=p.source_media_id
    LEFT JOIN social_connections source ON source.id=pub.connection_id
      AND source.tenant_id=p.tenant_id AND source.brand_id=p.brand_id
      AND source.purged_at IS NULL AND source.purge_started_at IS NULL
"""


def list_promotion_results(
    *, tenant_id: UUID, brand_id: UUID | None = None
) -> tuple[PromotionResultSummary, ...]:
    _member(tenant_id)
    with tenant_session(tenant_id) as s:
        rows = (
            s.execute(
                text(
                    _SUMMARY_SQL + " WHERE (CAST(:brand AS uuid) IS NULL "
                    "OR p.brand_id=CAST(:brand AS uuid)) "
                    "ORDER BY p.created_at DESC,p.id LIMIT 200"
                ),
                {"brand": brand_id},
            )
            .mappings()
            .all()
        )
        return tuple(_summary(row) for row in rows)


def load_promotion_results(*, tenant_id: UUID, promotion_id: UUID) -> PromotionResults:
    _member(tenant_id)
    return _load(tenant_id, promotion_id)


def _load(tenant_id: UUID, promotion_id: UUID) -> PromotionResults:
    with tenant_session(tenant_id) as s:
        row = (
            s.execute(text(_SUMMARY_SQL + " WHERE p.id=:id"), {"id": promotion_id})
            .mappings()
            .first()
        )
        if row is None:
            raise ResultsUnavailable("Esta promoción no está disponible en tu negocio.")
        summary = _summary(row)
        daily = []
        if row["cache_current"]:
            rows = (
                s.execute(
                    text(
                        "SELECT day,currency,metrics FROM ad_promotion_insights "
                        "WHERE promotion_id=:id AND observed_at=:checked "
                        "ORDER BY day DESC LIMIT 28"
                    ),
                    {"id": promotion_id, "checked": row["insights_checked_at"]},
                )
                .mappings()
                .all()
            )
            for item in rows:
                metrics = item["metrics"]
                daily.append(
                    DailyInsight(
                        item["day"],
                        item["currency"],
                        nonnegative(metrics.get("spend")),
                        *(
                            nonnegative(metrics.get(k), integer=True)
                            for k in ("reach", "impressions", "clicks")
                        ),
                        *(nonnegative(metrics.get(k)) for k in ("ctr", "cpc", "cpm")),
                        tuple(metrics.get("actions", [])),
                    )
                )
        updated = row["insights_checked_at"] if row["cache_current"] else None
        from qualify_api.ads.messaging_attribution import promotion_conversation_count

        return PromotionResults(
            summary,
            tuple(daily),
            updated,
            insights_stale=updated is None
            or updated < datetime.now(UTC) - POLL_INTERVAL
            or bool(row["insights_read_failed"]),
            insights_refresh_failed=bool(row["insights_read_failed"]),
            observed_conversations=promotion_conversation_count(
                tenant_id=tenant_id,
                promotion_id=promotion_id,
            ),
        )


def _verify_delivery(scope: ResultScope, payload: dict[str, Any]) -> tuple[str, str]:
    expected = {
        "id": scope.ad_id,
        "account_id": scope.meta_account_id,
        "campaign_id": scope.campaign_id,
        "adset_id": scope.adset_id,
    }
    if any(payload.get(k) != v for k, v in expected.items()):
        raise ResultsUnavailable("No pudimos comprobar a qué cuenta pertenece este anuncio.")
    status = payload.get("effective_status")
    configured = payload.get("status")
    return (
        status if isinstance(status, str) and status in STATUS_LABELS else "UNKNOWN",
        configured
        if isinstance(configured, str) and configured in {"ACTIVE", "PAUSED", "ARCHIVED", "DELETED"}
        else "UNKNOWN",
    )


def _claim_refresh(scope: ResultScope, now: datetime) -> UUID:
    token = uuid4()
    with tenant_session(scope.tenant_id, independent=True) as s:
        s.execute(
            text("""INSERT INTO ad_promotion_observations
          (tenant_id,promotion_id,account_id,credential_version,refresh_token,refresh_started_at,
           pipeline_version,read_failed,insights_read_failed)
          VALUES (:tenant,:id,:account,:version,:token,:now,:pipeline,true,true)
          ON CONFLICT (promotion_id) DO UPDATE SET account_id=:account,credential_version=:version,
            refresh_token=:token,refresh_started_at=:now,read_failed=true,insights_read_failed=true,
            checked_at=CASE WHEN ad_promotion_observations.account_id=:account
              AND ad_promotion_observations.credential_version=:version
              THEN ad_promotion_observations.checked_at ELSE NULL END,
            insights_checked_at=CASE WHEN ad_promotion_observations.account_id=:account
              AND ad_promotion_observations.credential_version=:version
              THEN ad_promotion_observations.insights_checked_at ELSE NULL END
          """),
            {
                "tenant": scope.tenant_id,
                "id": scope.promotion_id,
                "account": scope.account_id,
                "version": scope.connection.version,
                "token": token,
                "now": now,
                "pipeline": PIPELINE_VERSION,
            },
        )
    return token


def _save_observation(
    scope: ResultScope,
    token: UUID,
    status: str,
    configured: str,
    daily: tuple[DailyInsight, ...] | None,
    now: datetime,
    feedback: dict[str, Any] | None = None,
) -> None:
    with tenant_session(scope.tenant_id, independent=True) as s:
        saved = s.execute(
            text("""UPDATE ad_promotion_observations
            SET checked_at=:now,effective_status=:status,
                configured_status=:configured,read_failed=false
            WHERE promotion_id=:id AND refresh_token=:token AND account_id=:account
              AND credential_version=:version RETURNING promotion_id"""),
            {
                "now": now,
                "status": status,
                "configured": configured,
                "id": scope.promotion_id,
                "token": token,
                "account": scope.account_id,
                "version": scope.connection.version,
            },
        ).scalar()
        if saved is None:
            raise ResultsUnavailable("Hay una consulta más reciente. Actualiza la promoción.")
        if feedback is not None:
            s.execute(
                text(
                    "UPDATE ad_promotions SET review_feedback=CAST(:feedback AS jsonb) WHERE id=:id"
                ),
                {"id": scope.promotion_id, "feedback": json.dumps(feedback)},
            )
        if daily is not None:
            s.execute(
                text(
                    "UPDATE ad_promotion_observations SET "
                    "insights_checked_at=:now,insights_read_failed=false "
                    "WHERE promotion_id=:id AND refresh_token=:token"
                ),
                {"now": now, "id": scope.promotion_id, "token": token},
            )
        for insight in daily or ():
            metrics = asdict(insight)
            metrics.pop("day")
            metrics.pop("currency")
            s.execute(
                text("""INSERT INTO ad_promotion_insights
              (tenant_id,promotion_id,day,currency,metrics,observed_at,pipeline_version)
              VALUES (:tenant,:id,:day,:currency,CAST(:metrics AS jsonb),:now,:pipeline)
              ON CONFLICT (promotion_id,day) DO UPDATE SET metrics=EXCLUDED.metrics,
                currency=EXCLUDED.currency,observed_at=EXCLUDED.observed_at,
                pipeline_version=EXCLUDED.pipeline_version"""),
                {
                    "tenant": scope.tenant_id,
                    "id": scope.promotion_id,
                    "day": insight.day,
                    "currency": insight.currency,
                    "metrics": json.dumps(metrics, default=str),
                    "now": now,
                    "pipeline": PIPELINE_VERSION,
                },
            )
        # Only a configured PAUSED is evidence of this specific pause intent;
        # CAMPAIGN_PAUSED/ADSET_PAUSED alone does not prove that our ad was paused.
        if configured == "PAUSED":
            s.execute(
                text("""UPDATE ad_promotion_operations SET state='reconciled',finished_at=:now
                WHERE promotion_id=:id AND action='pause' AND state IN ('in_flight','unknown')
                  AND created_at < :started
                  AND (dispatched_at IS NULL OR dispatched_at < :started)"""),
                {
                    "id": scope.promotion_id,
                    "now": now,
                    "started": now - timedelta(seconds=90),
                },
            )


async def _refresh(
    tenant_id: UUID,
    promotion_id: UUID,
    *,
    api: MarketingAPI | None = None,
    system: bool = False,
    now: datetime | None = None,
) -> PromotionResults:
    now = now or datetime.now(UTC)
    scope = _scope(tenant_id, promotion_id, system=system)
    token = _claim_refresh(scope, now)
    client = None
    try:
        if api is None:
            client = await _authenticated_client(
                tenant_id, scope.connection.connection_id, expected_version=scope.connection.version
            )
            api = MarketingClient(client=client, account_id=scope.meta_account_id)
        _same(scope, system=system)
        payload = await api.delivery(scope.ad_id)
        status, configured = _verify_delivery(scope, payload)
        _same(scope, system=system)
        reason = safe_review_text(payload.get("issues_info"))
        feedback = (
            {
                "reason": reason,
                "source_id": scope.ad_id,
                "account_id": scope.meta_account_id,
                "credential_version": scope.connection.version,
                "checked_at": now.isoformat(),
                "pipeline_version": "ad-review-reason-v1",
            }
            if reason and status in {"DISAPPROVED", "WITH_ISSUES"}
            else {}
        )
        _save_observation(scope, token, status, configured, None, now, feedback=feedback)
        local_day = now.astimezone(ZoneInfo(scope.timezone_name)).date()
        since, until = local_day - timedelta(days=28), local_day - timedelta(days=1)
        daily: dict[date, DailyInsight] = {}
        cursor = None
        seen = set()
        for _ in range(5):
            params: dict[str, Any] = {
                "fields": (
                    "ad_id,account_id,account_currency,date_start,date_stop,spend,reach,"
                    "impressions,clicks,ctr,cpc,cpm,actions"
                ),
                "time_increment": 1,
                "time_range": {"since": since.isoformat(), "until": until.isoformat()},
                "level": "ad",
                "limit": 100,
            }
            if cursor:
                params["after"] = cursor
            page = await api.insights(scope.ad_id, params=params)
            _same(scope, system=system)
            for row in page.data:
                item = parse_insight(
                    row,
                    ad_id=scope.ad_id,
                    account_id=scope.meta_account_id,
                    currency=scope.currency,
                )
                if not since <= item.day <= until or item.day in daily:
                    raise ResultsUnavailable(
                        "Los resultados contienen fechas repetidas o fuera del período."
                    )
                daily[item.day] = item
            if page.after is None:
                break
            if page.after in seen:
                raise ResultsUnavailable("No pudimos terminar la consulta de resultados.")
            seen.add(page.after)
            cursor = page.after
        else:
            raise ResultsUnavailable("No pudimos terminar la consulta de resultados.")
        _same(scope, system=system)
        _save_observation(scope, token, status, configured, tuple(daily.values()), now)
        _same(scope, system=system)
        if client is not None:
            from qualify_api.ads.live_management import reconcile_promotion_edit

            await reconcile_promotion_edit(scope, system=system)
            _same(scope, system=system)
        return _load(tenant_id, promotion_id)
    except (MarketingError, AdAccountUnavailable):
        raise ResultsUnavailable(UNAVAILABLE) from None
    finally:
        if client is not None and hasattr(client, "aclose"):
            await client.aclose()


async def refresh_promotion_results(*, tenant_id: UUID, promotion_id: UUID) -> PromotionResults:
    return await _refresh(tenant_id, promotion_id)


async def refresh_promotion_from_signal(*, tenant_id: UUID, promotion_id: UUID) -> PromotionResults:
    """System read triggered by an ad-account webhook (`ads.status_webhook`); the
    notification is only the trigger, this authenticated read is the evidence."""
    return await _refresh(tenant_id, promotion_id, system=True)


async def prepare_promotion_edit(
    *,
    tenant_id: UUID,
    promotion_id: UUID,
    request_key: str,
    action: str,
    budget_minor: int | None = None,
    end_time: datetime | None = None,
) -> PreparedPromotionEdit:
    from qualify_api.ads.live_management import prepare_promotion_edit as prepare
    from qualify_api.ads.wizard import WizardUnavailable

    try:
        return await prepare(
            tenant_id=tenant_id,
            promotion_id=promotion_id,
            request_key=request_key,
            action=action,
            budget_minor=budget_minor,
            end_time=end_time,
        )
    except (MarketingError, AdAccountUnavailable, WizardUnavailable):
        raise ResultsUnavailable(UNAVAILABLE) from None


async def confirm_promotion_edit(
    *,
    tenant_id: UUID,
    promotion_id: UUID,
    request_key: str,
    approval_token: str,
    confirm_change: bool,
) -> PromotionEditResult:
    from qualify_api.ads.live_management import confirm_promotion_edit as confirm
    from qualify_api.ads.wizard import WizardUnavailable

    try:
        return await confirm(
            tenant_id=tenant_id,
            promotion_id=promotion_id,
            request_key=request_key,
            approval_token=approval_token,
            confirm_change=confirm_change,
        )
    except (MarketingError, AdAccountUnavailable, WizardUnavailable):
        raise ResultsUnavailable(UNAVAILABLE) from None


def _claim_pause(
    scope: ResultScope,
    request_key: str,
    now: datetime,
    *,
    action: str = "pause",
    payload: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    expected_revision: str | None = None,
) -> tuple[UUID, str]:
    payload = payload or {"status": "PAUSED"}
    evidence = evidence or {}
    if not isinstance(request_key, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", request_key):
        raise ResultsUnavailable("Vuelve a confirmar la pausa de la promoción.")
    with tenant_session(scope.tenant_id, independent=True) as s:
        s.execute(
            text("SELECT id FROM ad_promotions WHERE id=:id FOR UPDATE"), {"id": scope.promotion_id}
        ).one()
        actor = s.scalar(
            text("SELECT id FROM users WHERE auth_user_id=:login"),
            {"login": current_acting_login()},
        )
        if actor is None:
            raise ResultsUnavailable("Vuelve a entrar para pausar la promoción.")
        existing = (
            s.execute(
                text("SELECT * FROM ad_promotion_operations WHERE request_key=:key"),
                {"key": request_key},
            )
            .mappings()
            .first()
        )
        if existing:
            if (
                existing["promotion_id"] != scope.promotion_id
                or existing["actor_id"] != actor
                or existing["action"] != action
                or existing["payload"] != payload
            ):
                raise ResultsUnavailable("Esta confirmación pertenece a otro cambio.")
            return existing["id"], existing["state"]
        if expected_revision is not None:
            from qualify_api.ads.edit_ledger import operations, revision

            if revision(operations(s, scope.promotion_id)) != expected_revision:
                raise ResultsUnavailable("El historial cambió. Vuelve a revisar el cambio.")
        recent = s.execute(
            text("""SELECT id FROM ad_promotion_operations WHERE promotion_id=:id
          AND (state IN ('in_flight','unknown') OR
               GREATEST(created_at,COALESCE(dispatched_at,created_at),
                        COALESCE(finished_at,created_at)) > :cutoff) LIMIT 1"""),
            {"id": scope.promotion_id, "cutoff": now - timedelta(seconds=30)},
        ).first()
        if recent:
            raise ResultsUnavailable(
                "Espera treinta segundos y actualiza el estado antes de otro cambio."
            )
        operation = uuid4()
        s.execute(
            text("""INSERT INTO ad_promotion_operations
          (id,tenant_id,promotion_id,request_key,actor_id,action,payload,approval_evidence,
           state,created_at,pipeline_version)
          VALUES (:operation,:tenant,:id,:key,:actor,:action,CAST(:payload AS jsonb),
                  CAST(:evidence AS jsonb),'in_flight',:now,:pipeline)"""),
            {
                "operation": operation,
                "tenant": scope.tenant_id,
                "id": scope.promotion_id,
                "key": request_key,
                "actor": actor,
                "now": now,
                "pipeline": PIPELINE_VERSION,
                "action": action,
                "payload": json.dumps(payload),
                "evidence": json.dumps(evidence),
            },
        )
        return operation, "claimed"


def _finish_pause(scope: ResultScope, operation: UUID, state: str) -> None:
    with tenant_session(scope.tenant_id, independent=True) as s:
        s.execute(
            text("""UPDATE ad_promotion_operations SET state=:state,finished_at=:now
          WHERE id=:operation AND promotion_id=:id AND state='in_flight'"""),
            {
                "state": state,
                "now": datetime.now(UTC),
                "operation": operation,
                "id": scope.promotion_id,
            },
        )


def _dispatch(scope: ResultScope, operation: UUID) -> None:
    """A cancelled/reconciled or expired claim may never dispatch after cooldown."""
    with tenant_session(scope.tenant_id, independent=True) as s:
        claimed = s.execute(
            text("""UPDATE ad_promotion_operations SET dispatched_at=:now
            WHERE id=:operation AND promotion_id=:id AND state='in_flight'
              AND dispatched_at IS NULL AND created_at > :deadline RETURNING id"""),
            {
                "now": datetime.now(UTC),
                "deadline": datetime.now(UTC) - timedelta(minutes=5),
                "operation": operation,
                "id": scope.promotion_id,
            },
        ).scalar()
        if claimed is None:
            raise ResultsUnavailable("La confirmación venció o cambió. Actualiza la promoción.")


async def _pause(
    tenant_id: UUID,
    promotion_id: UUID,
    request_key: str,
    *,
    api: MarketingAPI | None = None,
    action: str = "pause",
    payload: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    spending_guard: Callable[[ResultScope], None] | None = None,
) -> PromotionResults:
    payload = payload or {"status": "PAUSED"}
    if action != "pause" and spending_guard is None:
        raise ResultsUnavailable(MANAGEMENT_REASON)
    scope = _scope(tenant_id, promotion_id)
    client = None
    operation = None
    dispatched = False
    try:
        if api is None:
            client = await _authenticated_client(
                tenant_id, scope.connection.connection_id, expected_version=scope.connection.version
            )
            api = MarketingClient(client=client, account_id=scope.meta_account_id)
        _same(scope)
        _verify_delivery(scope, await api.delivery(scope.ad_id))
        _same(scope)
        if spending_guard is not None:
            spending_guard(scope)
        operation, state = _claim_pause(
            scope, request_key, datetime.now(UTC), action=action, payload=payload, evidence=evidence
        )
        if state != "claimed":
            operation = None  # Repeated intents cannot finish another dispatch.
            if state in {"completed", "reconciled"}:
                return _load(tenant_id, promotion_id)
            raise ResultsUnavailable(UNCERTAIN)

        def guard() -> None:
            nonlocal dispatched
            _same(scope)
            if spending_guard is not None:
                spending_guard(_scope(tenant_id, promotion_id))
            _dispatch(scope, operation)
            dispatched = True

        target = scope.adset_id if action in {"budget", "end_time"} else scope.ad_id
        await api.update(target, params=payload, before_write=guard)
        _same(scope)
        _finish_pause(scope, operation, "completed")
        # A success acknowledgement is not an effective-status observation.
        # The caller refreshes separately; a failed read must never retry pause.
        with tenant_session(tenant_id) as s:
            s.execute(
                text("UPDATE ad_promotion_observations SET checked_at=NULL WHERE promotion_id=:id"),
                {"id": promotion_id},
            )
        _same(scope)
        return _load(tenant_id, promotion_id)
    except (MarketingError, AdAccountUnavailable) as exc:
        if operation is not None:
            _finish_pause(
                scope,
                operation,
                "unknown" if dispatched or getattr(exc, "outcome_unknown", False) else "failed",
            )
        raise ResultsUnavailable(UNCERTAIN if dispatched else UNAVAILABLE) from None
    except BaseException:
        if operation is not None:
            _finish_pause(scope, operation, "unknown" if dispatched else "failed")
        raise
    finally:
        if client is not None and hasattr(client, "aclose"):
            await client.aclose()


async def edit_promotion(
    *,
    tenant_id: UUID,
    promotion_id: UUID,
    action: str,
    request_key: str,
    budget_minor: int | None = None,
    end_time: datetime | None = None,
) -> PromotionResults:
    _member(tenant_id)
    if action != "pause" or budget_minor is not None or end_time is not None:
        raise ResultsUnavailable(MANAGEMENT_REASON)
    return await _pause(tenant_id, promotion_id, request_key)


async def poll_promotion_results(*, tenant_id: UUID, limit: int = 100) -> dict[str, int]:
    """Readonly system tick. Production scheduling is a separate deployment step."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("limit must be between one and five hundred")
    with tenant_session(tenant_id) as s:
        ids = s.scalars(
            text("""SELECT p.id FROM ad_promotions p
          LEFT JOIN ad_promotion_observations o ON o.promotion_id=p.id AND o.tenant_id=p.tenant_id
          WHERE p.meta_ad_id IS NOT NULL
            AND (o.refresh_started_at IS NULL OR o.refresh_started_at < :due)
            AND (o.effective_status IS NULL OR o.effective_status NOT IN ('ARCHIVED','DELETED'))
          ORDER BY o.refresh_started_at NULLS FIRST,p.created_at LIMIT :limit"""),
            {"due": datetime.now(UTC) - POLL_INTERVAL, "limit": limit},
        ).all()
    counts = {"checked": 0, "unavailable": 0}
    for promotion_id in ids:
        try:
            await _refresh(tenant_id, promotion_id, system=True)
            counts["checked"] += 1
        except ResultsUnavailable:
            counts["unavailable"] += 1
    return counts
