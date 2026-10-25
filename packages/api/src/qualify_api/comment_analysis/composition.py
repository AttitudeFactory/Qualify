"""Production assembly for automatic comment prioritization (m-24852204).

Two triggers, one runner:

- **After every comment sync** — `analyze_after_sync`, called by Interacciones once
  `inbox.sync_comments` lands new comments (the screen calls it from a background event,
  through `asyncio.to_thread`: never on the Reflex event loop, never before the page has
  rendered).
- **A periodic sweep** — `sweep_pending_comment_analysis`, run by the webhook worker's
  loop (`webhooks.worker`), next to the mention-sentiment sweep it already runs (QUA-152).
  It catches what the after-sync pass could not finish: a backlog above the batch, a
  model outage, a pass that failed, comments synced while nobody kept the screen open.

Why the webhook worker and not a new process or an embedded thread: it is already always
on in production, already loads the same image (the `sentiment` group and its weights,
`deploy/Dockerfile`) and the same environment (the Claude key), already sweeps sentiment
for mentions, never talks to Meta and never publishes. A new service would be one more
runtime to operate; an embedded thread in the Reflex process (like `planner.embedded`)
would put model inference on the one Reflex worker the UI depends on, and production
forces that pattern off anyway.
"""

from __future__ import annotations

import logging
from functools import cache
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.comment_analysis.runner import (
    CommentAnalysisRunner,
    ConnectionAnalysisReport,
    SweepReport,
)
from qualify_api.connections.models import SocialConnection
from qualify_api.planner.locks import ExecutionLock, PostgresAdvisoryLock

logger = logging.getLogger("qualify_api.comment_analysis")

_PLATFORM_INSTAGRAM = "instagram"


def _sentiment_pass(tenant_id: UUID, connection_id: UUID, limit: int) -> int:
    # m-24854340: off by default (robertuito OOM-killed the webhook worker). Checked before
    # the sentiment composition is imported; the runner reports it as "unavailable".
    from qualify_api.sentiment.service import (  # noqa: PLC0415
        ENABLED_ENV,
        SentimentDisabled,
        sentiment_enabled,
    )

    if not sentiment_enabled():
        raise SentimentDisabled(f"{ENABLED_ENV} is off")
    from qualify_api.sentiment.composition import analyze_pending_comments  # noqa: PLC0415

    return analyze_pending_comments(
        tenant_id=tenant_id, connection_id=connection_id, limit=limit
    ).new_results


def _intent_pass(tenant_id: UUID, connection_id: UUID, limit: int) -> int:
    from qualify_api.intent.composition import analyze_pending_intents  # noqa: PLC0415

    return analyze_pending_intents(
        tenant_id=tenant_id, connection_id=connection_id, limit=limit
    ).new_results


def _followups_pass(tenant_id: UUID, connection_id: UUID) -> int:
    from qualify_api.followups.composition import production_workspace  # noqa: PLC0415

    return (
        production_workspace()
        .open_from_intents(tenant_id=tenant_id, connection_id=connection_id)
        .opened
    )


def build_runner(*, lock: ExecutionLock) -> CommentAnalysisRunner:
    """The runner over the real seams; `lock` is injectable so tests run without Postgres."""
    from qualify_api.intent.composition import IntentModelUnavailable  # noqa: PLC0415
    from qualify_api.sentiment.service import SentimentModelUnavailable  # noqa: PLC0415

    return CommentAnalysisRunner(
        sentiment=_sentiment_pass,
        intent=_intent_pass,
        open_followups=_followups_pass,
        lock=lock,
        # ImportError/OSError: the model runtime or its weights cannot load here — the
        # same "environment, not this comment" split `mentions.sentiment` makes.
        sentiment_unavailable=(SentimentModelUnavailable, ImportError, OSError),
        intent_unavailable=(IntentModelUnavailable,),
    )


@cache
def production_runner() -> CommentAnalysisRunner:
    return build_runner(lock=PostgresAdvisoryLock())


def analyze_after_sync(*, tenant_id: UUID, connection_id: UUID) -> ConnectionAnalysisReport:
    """One bounded pass right after a sync. Synchronous and never raises; the caller
    runs it off the event loop."""
    return production_runner().analyze_connection(tenant_id=tenant_id, connection_id=connection_id)


def _instagram_connections(tenant_id: UUID) -> list[UUID]:
    with tenant_session(tenant_id) as session:
        return list(
            session.scalars(
                select(SocialConnection.id).where(SocialConnection.platform == _PLATFORM_INSTAGRAM)
            ).all()
        )


def sweep_targets() -> list[tuple[UUID, UUID]]:
    """Every (tenant, Instagram connection). The tenant list is the webhook worker's
    narrow cross-tenant read (`mentions.resolve.instagram_tenant_ids`); each tenant's
    connections are read back through `tenant_session`, so RLS scopes them. A tenant
    whose read fails is skipped (logged), never the whole sweep."""
    from qualify_api.mentions.resolve import instagram_tenant_ids  # noqa: PLC0415

    targets: list[tuple[UUID, UUID]] = []
    for tenant_id in instagram_tenant_ids():
        try:
            targets.extend((tenant_id, conn) for conn in _instagram_connections(tenant_id))
        except Exception as exc:  # noqa: BLE001 — next tenant
            logger.warning(
                "comment_analysis.sweep tenant=%s skipped (%s)", tenant_id, type(exc).__name__
            )
    return targets


def sweep_pending_comment_analysis() -> SweepReport:
    """The webhook worker's periodic pass. Never raises."""
    try:
        targets = sweep_targets()
    except Exception as exc:  # noqa: BLE001 — a sweep must never crash its worker
        logger.warning("comment_analysis.sweep listing failed (%s)", type(exc).__name__)
        return SweepReport(
            connections=0, sentiment_new=0, intent_new=0, followups_opened=0, errored=1
        )
    return production_runner().sweep(targets)
