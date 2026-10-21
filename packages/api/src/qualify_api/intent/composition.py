"""Production assembly for commercial intent (m-24789644) — the analogue of
`sentiment/composition.py`. `analyze_pending_intents` and `current_signals` are the
published seams (plain functions over ids); the Interacciones UI and QUA-229 call these,
never the repository or the classifier directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final
from uuid import UUID

from qualify_shared.db.session import tenant_session

from qualify_api.claude_tools import MissingAPIKey, api_key_from_env
from qualify_api.connections.models import SocialConnection
from qualify_api.intent.classifier import CLAUDE_INTENT_MODEL, ClaudeIntentClassifier
from qualify_api.intent.contract import IntentSignal
from qualify_api.intent.repository import PostgresIntentRepository
from qualify_api.intent.service import IntentAnalysisSummary, IntentService
from qualify_api.sentiment.repository import AnalysisVersion

#: The version this deployment analyzes under. Bumping any field (a new prompt, a new
#: model) makes every comment pending again under the new version — no backfill flag;
#: the old rows stay, append-only.
CURRENT_INTENT_VERSION: Final = AnalysisVersion(
    detector_version="intent-claude-v2",
    pipeline_version="intent-pipeline-v1",
    model_id=CLAUDE_INTENT_MODEL,
    model_revision=None,
)


class IntentModelUnavailable(Exception):
    """The classifier cannot run here (`QUALIFY_ANTHROPIC_API_KEY` is not set). Raised
    before any read, so a deployment without the key refuses cleanly."""


class UnknownIntentConnection(Exception):
    """No connection with this id is visible to this tenant. Duplicated rather than
    imported from `sentiment`, the same self-containment its own docstring explains."""


def _require_connection_visible(*, tenant_id: UUID, connection_id: UUID) -> None:
    """RLS filters out another tenant's connection, so missing and cross-tenant are the
    same case, on purpose — same shape as `sentiment.composition`'s."""
    with tenant_session(tenant_id) as session:
        connection_row = session.get(SocialConnection, connection_id)
    if connection_row is None:
        raise UnknownIntentConnection(
            f"connection {connection_id} is not visible to tenant {tenant_id}"
        )


def production_intent_service() -> IntentService:
    """Built per call (not cached like sentiment's): it holds the API key, read from the
    environment each time so a rotated key is picked up without a restart."""
    try:
        api_key = api_key_from_env()
    except MissingAPIKey as exc:
        raise IntentModelUnavailable(str(exc)) from exc
    return IntentService(
        repository=PostgresIntentRepository(),
        version=CURRENT_INTENT_VERSION,
        classifier=ClaudeIntentClassifier(api_key=api_key),
    )


def analyze_pending_intents(*, tenant_id: UUID, connection_id: UUID) -> IntentAnalysisSummary:
    """Classify every pending comment of the connection under `CURRENT_INTENT_VERSION`.
    Raises `UnknownIntentConnection` or `IntentModelUnavailable` before any work."""
    _require_connection_visible(tenant_id=tenant_id, connection_id=connection_id)
    return production_intent_service().analyze_pending_intents(
        tenant_id=tenant_id, connection_id=connection_id
    )


def current_signals(*, tenant_id: UUID, message_ids: Iterable[UUID]) -> dict[UUID, IntentSignal]:
    """The signal of each comment under the current version (absent = not analyzed)."""
    return PostgresIntentRepository().get_signals(
        tenant_id=tenant_id, message_ids=message_ids, version=CURRENT_INTENT_VERSION
    )
