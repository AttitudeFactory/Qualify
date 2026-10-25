"""m-24854340: the local sentiment model (robertuito, torch) is OFF unless
`QUALIFY_SENTIMENT_ENABLED` is truthy — it OOM-killed the webhook worker (and loads inside
the Reflex process on the after-sync pass). Off, no path runs it or imports the model
library; commercial intent and the queries it opens run unchanged."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import textwrap
from uuid import UUID

import pytest

from qualify_api.comment_analysis import composition
from qualify_api.comment_analysis.runner import SKIP_NONE, SKIP_UNAVAILABLE
from qualify_api.mentions import composition as mentions_composition
from qualify_api.planner.locks import MemoryExecutionLock
from qualify_api.sentiment.repository import AnalysisVersion, MemorySentimentRepository
from qualify_api.sentiment.service import (
    ENABLED_ENV,
    SentimentDisabled,
    SentimentModelUnavailable,
    SentimentService,
    sentiment_enabled,
)
from qualify_api.webhooks import worker as webhook_worker

TENANT = UUID("e0000000-0000-4000-8000-0000000000d7")
CONNECTION = UUID("c0000000-0000-4000-8000-0000000000d7")
VERSION = AnalysisVersion(
    detector_version="d1", pipeline_version="p1", model_id="stub", model_revision=None
)


@pytest.fixture(autouse=True)
def _switch_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENABLED_ENV, raising=False)


def test_off_by_default_and_only_explicit_values_turn_it_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert sentiment_enabled() is False
    for value in ("", "0", "false", "no", "off", "enabled"):
        monkeypatch.setenv(ENABLED_ENV, value)
        assert sentiment_enabled() is False, value
    for value in ("1", "true", "YES", " on "):
        monkeypatch.setenv(ENABLED_ENV, value)
        assert sentiment_enabled() is True, value


def test_disabled_degrades_like_an_unavailable_model() -> None:
    assert issubclass(SentimentDisabled, SentimentModelUnavailable)


def _wire(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The real runner with the sentiment composition, intent and followups recorded."""
    from qualify_api.sentiment import composition as sentiment_composition
    from qualify_api.sentiment.service import AnalysisSummary

    calls: list[str] = []

    def sentiment(**_kwargs: object) -> AnalysisSummary:
        calls.append("sentiment")
        return AnalysisSummary(comments_checked=1, new_results=1, skipped_empty=0)

    def intent(_t: UUID, _c: UUID, _limit: int) -> int:
        calls.append("intent")
        return 2

    def followups(_t: UUID, _c: UUID) -> int:
        calls.append("followups")
        return 1

    monkeypatch.setattr(sentiment_composition, "analyze_pending_comments", sentiment)
    monkeypatch.setattr(composition, "_intent_pass", intent)
    monkeypatch.setattr(composition, "_followups_pass", followups)
    return calls


def test_off_the_runner_skips_sentiment_and_runs_intent_and_followups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _wire(monkeypatch)
    report = composition.build_runner(lock=MemoryExecutionLock()).analyze_connection(
        tenant_id=TENANT, connection_id=CONNECTION
    )
    assert calls == ["intent", "followups"]
    assert report.sentiment_skipped == SKIP_UNAVAILABLE and report.sentiment_new == 0
    assert report.intent_skipped == SKIP_NONE and report.intent_new == 2
    assert report.followups_opened == 1
    assert not report.errored


def test_off_the_after_sync_pass_of_the_app_skips_sentiment_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _wire(monkeypatch)
    runner = composition.build_runner(lock=MemoryExecutionLock())
    monkeypatch.setattr(composition, "production_runner", lambda: runner)
    report = composition.analyze_after_sync(tenant_id=TENANT, connection_id=CONNECTION)
    assert calls == ["intent", "followups"]
    assert report.sentiment_skipped == SKIP_UNAVAILABLE and not report.errored


def test_on_the_runner_runs_sentiment_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENABLED_ENV, "1")
    calls = _wire(monkeypatch)
    report = composition.build_runner(lock=MemoryExecutionLock()).analyze_connection(
        tenant_id=TENANT, connection_id=CONNECTION
    )
    assert calls == ["sentiment", "intent", "followups"]
    assert report.sentiment_new == 1 and report.sentiment_skipped == SKIP_NONE


def test_off_the_service_refuses_the_local_model_but_not_an_injected_provider() -> None:
    local = SentimentService(repository=MemorySentimentRepository(), version=VERSION)
    with pytest.raises(SentimentDisabled):
        local.analyze_pending_comments(tenant_id=TENANT, connection_id=CONNECTION)

    class Stub:
        model_id = "stub"

        def classify(self, text: str) -> tuple[str, float]:
            return ("POS", 0.9)

    injected = SentimentService(
        repository=MemorySentimentRepository(), version=VERSION, provider=Stub()
    )
    assert injected.analyze_pending_comments(tenant_id=TENANT, connection_id=CONNECTION)


def test_off_the_mention_sweep_reads_nothing_and_reports_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_run() -> tuple[UUID, ...]:
        raise AssertionError("the sweep listed tenants while sentiment is off")

    monkeypatch.setattr(mentions_composition, "instagram_tenant_ids", must_not_run)
    report = mentions_composition.sweep_pending_mention_sentiment()
    assert report.skipped == mentions_composition.SWEEP_SKIPPED_DISABLED
    assert report.tenants == report.tenants_errored == 0


def test_off_the_mention_after_ingest_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def must_not_run() -> object:
        raise AssertionError("the mention service was built while sentiment is off")

    monkeypatch.setattr(mentions_composition, "_production_mention_sentiment_service", must_not_run)
    mentions_composition.analyze_mention_after_ingest(tenant_id=TENANT, mention_id=CONNECTION)
    with pytest.raises(SentimentDisabled):
        mentions_composition.analyze_pending_mentions(tenant_id=TENANT)


def test_off_the_worker_mention_sweep_logs_no_sweep_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger=webhook_worker.logger.name):
        asyncio.run(webhook_worker._sentiment_sweep())
    assert not [r for r in caplog.records if r.levelno >= logging.INFO]


_PROBE = textwrap.dedent(
    """
    import json, sys
    from uuid import UUID
    from qualify_api.comment_analysis import composition
    from qualify_api.mentions import composition as mentions
    from qualify_api.planner.locks import MemoryExecutionLock
    from qualify_api.webhooks import worker  # noqa: F401 - the worker module itself

    composition._intent_pass = lambda _t, _c, _l: 0
    composition._followups_pass = lambda _t, _c: 0
    composition.production_runner = lambda: composition.build_runner(lock=MemoryExecutionLock())
    t = UUID("e0000000-0000-4000-8000-0000000000d7")
    after_sync = composition.analyze_after_sync(tenant_id=t, connection_id=t)
    sweep = composition.build_runner(lock=MemoryExecutionLock()).sweep([(t, t)])
    mentions.analyze_mention_after_ingest(tenant_id=t, mention_id=t)
    mention_sweep = mentions.sweep_pending_mention_sentiment()
    loaded = sorted(
        m for m in sys.modules
        if m.split(".")[0] in ("torch", "transformers") or m.startswith("qualify_models")
    )
    print(json.dumps({
        "after_sync": after_sync.sentiment_skipped,
        "sweep_errored": sweep.errored,
        "mention_sweep": mention_sweep.skipped,
        "loaded": loaded,
    }))
    """
)


def test_off_no_pass_imports_torch_transformers_or_the_model_library() -> None:
    """A fresh interpreter (other tests may have imported anything): the after-sync pass
    (the Reflex process), the comment sweep, and both mention paths, all with the switch
    unset — afterwards none of the model modules is in `sys.modules`."""
    env = {k: v for k, v in os.environ.items() if k != ENABLED_ENV}
    out = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, env=env, timeout=120
    )
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result == {
        "after_sync": SKIP_UNAVAILABLE,
        "sweep_errored": 0,
        "mention_sweep": "disabled",
        "loaded": [],
    }
