"""Automatic comment prioritization (m-24852204) — offline: the runner's order, bounds,
lock, silent degradation and sweep; the bounded pending reads of both analyses; the
composition's sweep listing; the webhook worker's wiring."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.comment_analysis import composition, runner
from qualify_api.comment_analysis.runner import (
    SKIP_BUSY,
    SKIP_NONE,
    SKIP_UNAVAILABLE,
    CommentAnalysisRunner,
    lock_key,
)
from qualify_api.intent import (
    CURRENT_INTENT_VERSION,
    IntentClass,
    IntentModelUnavailable,
    IntentService,
    MemoryIntentRepository,
)
from qualify_api.intent.classifier import Prediction
from qualify_api.planner.locks import MemoryExecutionLock
from qualify_api.sentiment.repository import AnalysisVersion, MemorySentimentRepository
from qualify_api.sentiment.service import SentimentModelUnavailable, SentimentService
from qualify_api.webhooks import worker as webhook_worker

TENANT = UUID("e0000000-0000-4000-8000-0000000000c1")
CONNECTION = UUID("c0000000-0000-4000-8000-0000000000c1")


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def sentiment(self, tenant_id: UUID, connection_id: UUID, limit: int) -> int:
        self.calls.append(("sentiment", (tenant_id, connection_id, limit)))
        return 3

    def intent(self, tenant_id: UUID, connection_id: UUID, limit: int) -> int:
        self.calls.append(("intent", (tenant_id, connection_id, limit)))
        return 2

    def followups(self, tenant_id: UUID, connection_id: UUID) -> int:
        self.calls.append(("followups", (tenant_id, connection_id)))
        return 1


def _runner(rec: _Recorder, lock: MemoryExecutionLock | None = None, **overrides: object):
    kwargs: dict[str, object] = {
        "sentiment": rec.sentiment,
        "intent": rec.intent,
        "open_followups": rec.followups,
        "lock": lock or MemoryExecutionLock(),
        "sentiment_unavailable": (SentimentModelUnavailable, ImportError, OSError),
        "intent_unavailable": (IntentModelUnavailable,),
        "batch": 40,
    }
    kwargs.update(overrides)
    return CommentAnalysisRunner(**kwargs)  # type: ignore[arg-type]


def _raise(exc: BaseException):
    def _fail(*_args: object) -> int:
        raise exc

    return _fail


# --- runner ------------------------------------------------------------------------------


def test_one_pass_runs_sentiment_then_intent_then_the_queries_bounded_by_the_batch() -> None:
    rec = _Recorder()
    report = _runner(rec).analyze_connection(tenant_id=TENANT, connection_id=CONNECTION)
    assert rec.calls == [
        ("sentiment", (TENANT, CONNECTION, 40)),
        ("intent", (TENANT, CONNECTION, 40)),
        ("followups", (TENANT, CONNECTION)),
    ]
    assert (report.sentiment_new, report.intent_new, report.followups_opened) == (3, 2, 1)
    assert report.changed and not report.errored
    assert (report.sentiment_skipped, report.intent_skipped) == (SKIP_NONE, SKIP_NONE)


def test_a_connection_already_being_analyzed_is_left_alone() -> None:
    rec = _Recorder()
    lock = MemoryExecutionLock()
    with lock.hold(tenant_id=TENANT, key=lock_key(CONNECTION)):
        report = _runner(rec, lock).analyze_connection(tenant_id=TENANT, connection_id=CONNECTION)
    assert rec.calls == []
    assert report.sentiment_skipped == report.intent_skipped == SKIP_BUSY
    assert not report.changed and not report.errored
    # Released afterwards: the next pass runs.
    assert _runner(rec, lock).analyze_connection(tenant_id=TENANT, connection_id=CONNECTION).changed


def test_the_lock_is_per_connection() -> None:
    rec = _Recorder()
    lock = MemoryExecutionLock()
    with lock.hold(tenant_id=TENANT, key=lock_key(uuid4())):
        report = _runner(rec, lock).analyze_connection(tenant_id=TENANT, connection_id=CONNECTION)
    assert report.changed


@pytest.mark.parametrize(
    "exc", [SentimentModelUnavailable("no ml"), ImportError("torch"), OSError()]
)
def test_without_the_local_model_intent_still_runs_and_nothing_raises(exc: Exception) -> None:
    rec = _Recorder()
    report = _runner(rec, sentiment=_raise(exc)).analyze_connection(
        tenant_id=TENANT, connection_id=CONNECTION
    )
    assert report.sentiment_skipped == SKIP_UNAVAILABLE
    assert [name for name, _ in rec.calls] == ["intent", "followups"]
    assert not report.errored


def test_without_the_claude_key_no_query_is_opened_and_nothing_raises() -> None:
    rec = _Recorder()
    report = _runner(rec, intent=_raise(IntentModelUnavailable("no key"))).analyze_connection(
        tenant_id=TENANT, connection_id=CONNECTION
    )
    assert report.intent_skipped == SKIP_UNAVAILABLE
    assert [name for name, _ in rec.calls] == ["sentiment"]
    assert report.sentiment_new == 3 and not report.errored


def test_an_unavailable_model_warns_once_per_process_then_stays_quiet(caplog) -> None:  # noqa: ANN001
    rec = _Recorder()
    analysis = _runner(
        rec,
        sentiment=_raise(SentimentModelUnavailable("no ml")),
        intent=_raise(IntentModelUnavailable("no key")),
    )
    with caplog.at_level(logging.DEBUG, logger="qualify_api.comment_analysis"):
        for _ in range(3):
            analysis.analyze_connection(tenant_id=TENANT, connection_id=CONNECTION)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2  # one for sentiment, one for intent — not one per pass
    assert all(
        "SentimentModelUnavailable" in r.getMessage() or "IntentModelUnavailable" in r.getMessage()
        for r in warnings
    )


def test_a_failing_half_is_logged_by_class_name_and_the_other_half_runs(caplog) -> None:  # noqa: ANN001
    rec = _Recorder()
    secret = "comentario con datos personales"
    with caplog.at_level(logging.WARNING, logger="qualify_api.comment_analysis"):
        report = _runner(rec, sentiment=_raise(RuntimeError(secret))).analyze_connection(
            tenant_id=TENANT, connection_id=CONNECTION
        )
    assert report.sentiment_skipped == "RuntimeError" and report.errored
    assert [name for name, _ in rec.calls] == ["intent", "followups"]
    assert secret not in caplog.text and "RuntimeError" in caplog.text


def test_a_failing_followups_step_never_undoes_the_analysis() -> None:
    rec = _Recorder()
    report = _runner(rec, open_followups=_raise(RuntimeError("db"))).analyze_connection(
        tenant_id=TENANT, connection_id=CONNECTION
    )
    assert (report.sentiment_new, report.intent_new, report.followups_opened) == (3, 2, 0)


def test_a_lock_that_cannot_be_taken_is_reported_not_raised() -> None:
    class _BrokenLock:
        def hold(self, *, tenant_id: UUID, key: str):  # noqa: ANN202
            raise ConnectionError("postgres down")

    rec = _Recorder()
    report = _runner(rec, lock=_BrokenLock()).analyze_connection(
        tenant_id=TENANT, connection_id=CONNECTION
    )
    assert rec.calls == [] and report.errored


def test_the_sweep_visits_every_connection_and_one_failure_stops_none() -> None:
    rec = _Recorder()
    broken = uuid4()

    def sentiment(tenant_id: UUID, connection_id: UUID, limit: int) -> int:
        if connection_id == broken:
            raise RuntimeError("boom")
        return rec.sentiment(tenant_id, connection_id, limit)

    targets = [(TENANT, CONNECTION), (TENANT, broken), (uuid4(), uuid4())]
    report = _runner(rec, sentiment=sentiment).sweep(targets)
    assert report.connections == 3
    assert report.sentiment_new == 6 and report.intent_new == 6 and report.followups_opened == 3
    assert report.errored == 1


def test_the_batch_must_be_positive() -> None:
    with pytest.raises(ValueError):
        _runner(_Recorder(), batch=0)


# --- bounded pending reads (memory repositories) ------------------------------------------

_VERSION = AnalysisVersion(
    detector_version="d1", pipeline_version="p1", model_id="m1", model_revision=None
)


class _StubSentiment:
    model_id = "stub/deterministic"

    def classify(self, text: str) -> tuple[str, float]:
        return ("POS", 0.9)


def test_a_bounded_sentiment_pass_takes_the_newest_and_drains_over_passes() -> None:
    repo = MemorySentimentRepository()
    base = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    ids = []
    for minutes in range(5):
        message_id = uuid4()
        ids.append(message_id)
        repo.seed_message(
            message_id=message_id,
            connection_id=CONNECTION,
            source_id=f"c{minutes}",
            text=f"comentario {minutes}",
            posted_at=base + timedelta(minutes=minutes),
        )
    pending = repo.list_pending_for_analysis(
        tenant_id=TENANT, connection_id=CONNECTION, version=_VERSION, limit=2
    )
    assert [p.message_id for p in pending] == [ids[4], ids[3]]

    service = SentimentService(repository=repo, version=_VERSION, provider=_StubSentiment())
    passes = [
        service.analyze_pending_comments(tenant_id=TENANT, connection_id=CONNECTION, limit=2)
        for _ in range(4)
    ]
    assert [p.new_results for p in passes] == [2, 2, 1, 0]  # the last pass is a no-op


class _StubClassifier:
    model_id = CURRENT_INTENT_VERSION.model_id
    model_revision = None

    def __init__(self) -> None:
        self.seen: list[list[str]] = []

    def classify(self, texts: Sequence[str]) -> list[Prediction]:
        self.seen.append(list(texts))
        return [{IntentClass.PRICE: 0.9} for _ in texts]


def test_a_bounded_intent_pass_sends_at_most_the_batch_and_then_nothing() -> None:
    repo = MemoryIntentRepository()
    for n in range(5):
        repo.seed_message(
            message_id=uuid4(), connection_id=CONNECTION, source_id=f"s{n}", text=f"¿precio {n}?"
        )
    classifier = _StubClassifier()
    service = IntentService(repository=repo, version=CURRENT_INTENT_VERSION, classifier=classifier)
    results = [
        service.analyze_pending_intents(tenant_id=TENANT, connection_id=CONNECTION, limit=3)
        for _ in range(3)
    ]
    assert [r.new_results for r in results] == [3, 2, 0]
    assert [len(batch) for batch in classifier.seen if batch] == [3, 2]


def test_a_single_comment_pass_is_not_cut_by_the_limit() -> None:
    """«Responder aquí» analyzes ONE comment by id; a limit never hides it."""
    repo = MemoryIntentRepository()
    target = uuid4()
    for n in range(3):
        repo.seed_message(message_id=uuid4(), connection_id=CONNECTION, source_id=f"s{n}", text="x")
    repo.seed_message(message_id=target, connection_id=CONNECTION, source_id="t", text="¿precio?")
    service = IntentService(
        repository=repo, version=CURRENT_INTENT_VERSION, classifier=_StubClassifier()
    )
    result = service.analyze_pending_intents(
        tenant_id=TENANT, connection_id=CONNECTION, message_ids=(target,), limit=1
    )
    assert result.new_results == 1


# --- composition ------------------------------------------------------------------------------


def test_the_real_runner_degrades_silently_without_model_and_key(monkeypatch) -> None:  # noqa: ANN001
    from qualify_api.intent import composition as intent_composition
    from qualify_api.sentiment import composition as sentiment_composition

    def no_model(**_kwargs: object) -> object:
        raise SentimentModelUnavailable("no ml")

    def no_key(**_kwargs: object) -> object:
        raise IntentModelUnavailable("no key")

    monkeypatch.setattr(sentiment_composition, "analyze_pending_comments", no_model)
    monkeypatch.setattr(intent_composition, "analyze_pending_intents", no_key)
    report = composition.build_runner(lock=MemoryExecutionLock()).analyze_connection(
        tenant_id=TENANT, connection_id=CONNECTION
    )
    assert report.sentiment_skipped == report.intent_skipped == SKIP_UNAVAILABLE
    assert not report.changed and not report.errored


def test_the_sweep_lists_every_tenants_instagram_connections_and_skips_a_bad_tenant(
    monkeypatch,  # noqa: ANN001
) -> None:
    from qualify_api.mentions import resolve

    good, bad = uuid4(), uuid4()
    conns = [uuid4(), uuid4()]

    def connections(tenant_id: UUID) -> list[UUID]:
        if tenant_id == bad:
            raise RuntimeError("rls")
        return conns

    monkeypatch.setattr(resolve, "instagram_tenant_ids", lambda: (bad, good))
    monkeypatch.setattr(composition, "_instagram_connections", connections)
    assert composition.sweep_targets() == [(good, conns[0]), (good, conns[1])]


def test_the_sweep_never_raises_when_the_tenant_listing_fails(monkeypatch) -> None:  # noqa: ANN001
    def broken() -> list[tuple[UUID, UUID]]:
        raise RuntimeError("no webhook-worker DSN")

    monkeypatch.setattr(composition, "sweep_targets", broken)
    report = composition.sweep_pending_comment_analysis()
    assert report.connections == 0 and report.errored == 1


def test_the_runner_module_never_imports_the_models_at_load_time() -> None:
    source = inspect.getsource(runner) + inspect.getsource(composition)
    assert "import qualify_models" not in source
    assert "from qualify_models" not in source


# --- webhook worker -------------------------------------------------------------------------


def test_the_webhook_worker_loop_sweeps_comments_on_the_sentiment_cadence() -> None:
    source = inspect.getsource(webhook_worker._run_loop)
    sweep = source.index("await _sentiment_sweep()")
    assert source.index("await _comment_analysis_sweep()") > sweep
    assert "next_sweep = started + SENTIMENT_SWEEP_EVERY" in source


def test_the_worker_sweep_never_stops_the_loop(monkeypatch) -> None:  # noqa: ANN001
    import qualify_api.comment_analysis as package

    def broken() -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(package, "sweep_pending_comment_analysis", broken)
    asyncio.run(webhook_worker._comment_analysis_sweep())  # no exception
