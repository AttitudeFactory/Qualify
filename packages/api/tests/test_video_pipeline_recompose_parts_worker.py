"""m-25103284 review: a part's final composed again takes minutes (Seedance's 10-bit H.265,
~3 min for 15 s on amd64, more on arm64), so the creative worker makes it OFF its main loop —
on the background thread the parts' joins use, its lease renewed the whole time — and its
`rendering_at` is stamped while it runs. Offline: the store, the service and the loop's
database reads are doubles."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from qualify_api.creative import pipeline as creative_pipeline
from qualify_api.creative import service as creative_service
from qualify_api.creative.heavy_video import LocalAssemblyWait
from qualify_api.creative.video_pipeline.recompose import part_final_composes
from qualify_api.creative.worker import pipeline as worker_pipeline
from qualify_api.creative.worker.pipeline import BackgroundJoins, PipelinePreparation

TENANT = uuid4()
ASSET = uuid4()
#: the lease the tests shorten `pipeline.LEASE` to: the compose outlasts it several times
LEASE_S = 0.3


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> _Rows:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class ExpiringLeases:
    """A lease that runs out `LEASE_S` after it was taken or last renewed — what
    `settle_final`'s fence checks before the final is written."""

    def __init__(self, run: Any) -> None:
        self.run = run
        self.until = 0.0
        self.renews = 0
        self.acquires = 0
        self.releases: list[bool] = []

    def acquire(self, *_args: Any) -> Any:
        self.acquires += 1
        self.until = time.monotonic() + LEASE_S
        return self.run

    def renew(self, run: object) -> bool:
        self.renews += 1
        self.until = time.monotonic() + LEASE_S
        return True

    def held(self) -> bool:
        return time.monotonic() < self.until

    def release(self, run: object, *, completed: bool) -> None:
        self.releases.append(completed)


@pytest.fixture
def one_final(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The loop's pass finds ONE dirty `final:<asset>` run; the lease is `LEASE_S`."""
    draft_id = uuid4()
    run = SimpleNamespace(
        draft_id=draft_id,
        tenant_id=TENANT,
        revision=1,
        phase=f"final:{ASSET}@a1",
        step=0,
        video=0,
        params=lambda: {"t": TENANT, "d": draft_id, "r": 1},
    )

    @contextmanager
    def session(_tenant: Any) -> Any:
        yield SimpleNamespace(
            execute=lambda *_a, **_k: _Rows(
                [{"draft_id": draft_id, "revision": 1, "phase": run.phase}]
            )
        )

    monkeypatch.setattr(worker_pipeline, "tenant_session", session)
    monkeypatch.setattr(creative_pipeline, "LEASE", timedelta(seconds=LEASE_S))
    monkeypatch.setattr(PipelinePreparation, "_settle_local", lambda self, run: None)
    return run


class SlowFinals:
    """`ContentService`'s double: a final that takes `seconds` and, at its end, checks
    the lease as `settle_final`'s fence does (`lost` when it ran out)."""

    def __init__(self, store: ExpiringLeases, *, composes: bool, seconds: float) -> None:
        self.store, self.composes, self.seconds = store, composes, seconds
        self._repo = SimpleNamespace(get_draft=lambda **_k: SimpleNamespace(revision=1))
        self.done = threading.Event()
        self.threads: list[str] = []
        self.lost = False

    def queued_final_composes(self, **_kwargs: Any) -> bool:
        return self.composes

    def run_queued_final(self, *, tenant_id: Any, draft_id: Any, asset_id: Any) -> None:
        assert asset_id == ASSET
        self.threads.append(threading.current_thread().name)
        time.sleep(self.seconds)
        self.lost = not self.store.held()  # `fence`: «preparation lease lost»
        self.done.set()


def test_a_parts_composed_final_runs_off_the_loop_with_its_lease_kept(one_final: Any) -> None:
    """The bloqueante of the review: the compose outlasts the lease (here 4x); made on
    the background thread, the lease is renewed the whole time and the final settles.
    The loop's pass returns at once — `claim_round`, `recover` and `monitor.beat` keep
    running (`test_the_loop_keeps_beating_and_claiming_while_a_slow_join_runs`)."""
    store = ExpiringLeases(one_final)
    service = SlowFinals(store, composes=True, seconds=4 * LEASE_S)
    preparation = PipelinePreparation(service, store, [TENANT], background_joins=True)  # type: ignore[arg-type]

    began = time.monotonic()
    preparation()
    assert time.monotonic() - began < LEASE_S  # the pass did not wait for the compose
    assert not service.done.is_set() and preparation.joins.busy()

    assert preparation.shutdown(timeout=None)
    assert service.done.is_set() and service.threads == ["creative-join"]
    assert not service.lost and store.renews >= 3  # renewed: never «lease lost»
    assert store.releases == [True]


def test_without_the_renewals_that_compose_would_lose_its_lease(one_final: Any) -> None:
    """The same final made inline, as before the fix: nobody renews the lease, and by
    the time it settles it is gone — the failure the review found."""
    store = ExpiringLeases(one_final)
    service = SlowFinals(store, composes=True, seconds=2 * LEASE_S)
    PipelinePreparation(service, store, [TENANT])()  # type: ignore[arg-type]  # no background
    assert service.lost and store.renews == 0


def test_an_ordinary_final_still_runs_inline(one_final: Any) -> None:
    store = ExpiringLeases(one_final)
    service = SlowFinals(store, composes=False, seconds=0.0)
    preparation = PipelinePreparation(service, store, [TENANT], background_joins=True)  # type: ignore[arg-type]
    preparation()
    assert service.threads == [threading.current_thread().name]
    assert not preparation.joins.busy() and store.releases == [True]


def test_while_a_join_runs_the_composed_final_waits_for_a_later_pass(one_final: Any) -> None:
    store = ExpiringLeases(one_final)
    service = SlowFinals(store, composes=True, seconds=0.0)
    preparation = PipelinePreparation(service, store, [TENANT], background_joins=True)  # type: ignore[arg-type]
    gate = threading.Event()
    assert preparation.joins.start(SimpleNamespace(draft_id=uuid4()), lambda _r: gate.wait(5))
    for _ in range(3):  # three passes of the loop while the thread is busy
        preparation()
    # never claimed nor released: no lease churn while it waits for the thread
    assert service.threads == [] and store.acquires == 0 and store.releases == []
    gate.set()
    assert preparation.shutdown(timeout=None)
    preparation()  # the thread is free: now it is taken
    assert store.acquires == 1
    assert preparation.shutdown(timeout=None) and service.threads == ["creative-join"]


def test_while_a_join_runs_an_ordinary_final_still_runs_inline(one_final: Any) -> None:
    store = ExpiringLeases(one_final)
    service = SlowFinals(store, composes=False, seconds=0.0)
    preparation = PipelinePreparation(service, store, [TENANT], background_joins=True)  # type: ignore[arg-type]
    gate = threading.Event()
    assert preparation.joins.start(SimpleNamespace(draft_id=uuid4()), lambda _r: gate.wait(5))
    preparation()
    assert store.acquires == 1 and service.threads == [threading.current_thread().name]
    gate.set()
    assert preparation.shutdown(timeout=None)


def test_a_composed_final_waiting_for_a_local_assembly_is_not_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = ExpiringLeases(None)
    joins = BackgroundJoins(store)  # type: ignore[arg-type]

    def waits(_run: Any) -> None:
        raise LocalAssemblyWait("a local video holds the gate")

    run = SimpleNamespace(draft_id=uuid4())
    with caplog.at_level("INFO", logger=worker_pipeline.logger.name):
        assert joins.start(run, waits)
        assert joins.shutdown(timeout=None)
    assert store.releases == [False]
    assert "local_waits" in caplog.text and "preparation_failed" not in caplog.text


def test_only_a_parts_final_with_a_frozen_recipe_goes_off_the_loop() -> None:
    recipe = {"recipe": {"text_layers": [{"text": "Hola"}], "effects": [], "brand": {}}}
    recipe["recipe"]["effects_pipeline_version"] = 1
    assert part_final_composes({"part": {"index": 1}, "compose": recipe})
    assert not part_final_composes({"compose": recipe})  # a Clip's final: inline, as EF-14
    assert not part_final_composes({"part": {"index": 1}})  # a part without texts


# ---------------------------------------------------------------------------
# `rendering_at` stamped while the final is made (`FINAL_STALE_SECONDS`)


def test_the_final_restarts_its_rendering_at_while_it_is_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .test_content_service import make_kit, make_service, make_voice

    monkeypatch.setattr(creative_service, "FINAL_HEARTBEAT_EVERY_S", 0.05)
    service, _, _ = make_service(kit=make_kit(), voice=make_voice())
    stamps: list[float] = []
    asset = SimpleNamespace(id=ASSET, params={"draft": {"status": "rendering"}})
    service._repo = SimpleNamespace(  # type: ignore[assignment]
        draft_videos_for=lambda **_k: (asset,),
        budget_state=lambda **_k: None,
        set_video_draft=lambda **k: stamps.append(k["changes"]["rendering_at"]),
    )
    service._final_context = lambda *_a: (  # type: ignore[method-assign]
        SimpleNamespace(revision=1, brand_id=uuid4()),
        None,
        None,
    )

    def finalize(**_kwargs: Any) -> Any:
        time.sleep(0.4)  # minutes, in production
        return SimpleNamespace(pending=True)

    service._media = SimpleNamespace(finalize=finalize)  # type: ignore[assignment]
    service.run_queued_final(tenant_id=TENANT, draft_id=uuid4(), asset_id=ASSET)
    assert len(stamps) >= 3 and stamps == sorted(stamps)
    after = len(stamps)
    time.sleep(0.2)
    assert len(stamps) == after  # the beat stops with the final: none lands after it


# ---------------------------------------------------------------------------
# a lease really lost at `settle_final`: the run stays undone, nothing failed or refunded


def test_a_lease_lost_when_the_final_is_saved_fails_nothing_and_refunds_nothing() -> None:
    from qualify_api.creative.queue_dispatch import CheckpointError

    from .test_content_service import make_kit, make_service, make_voice

    service, _, _ = make_service(kit=make_kit(), voice=make_voice())
    failed: list[Any] = []
    refunded: list[Any] = []

    def settle_final(**_kwargs: Any) -> None:
        raise CheckpointError("preparation lease lost")  # `PipelineStore.fence`

    service._repo = SimpleNamespace(settle_final=settle_final)  # type: ignore[assignment]
    service._fail_final = lambda *a, **_k: failed.append(a)  # type: ignore[method-assign]
    service._refund_final_part = lambda *a, **_k: refunded.append(a)  # type: ignore[method-assign]
    outcome = SimpleNamespace(
        media=SimpleNamespace(object_key="k"),
        detail=None,
        usage=(),
        spent_usd=0,
        draft_changes={"raw_final": {"key": "raw"}},
    )
    with pytest.raises(CheckpointError):
        service._settle_final(TENANT, uuid4(), uuid4(), ASSET, None, outcome)  # type: ignore[arg-type]
    assert failed == [] and refunded == []


def test_the_loop_leaves_a_final_whose_lease_was_lost_undone(one_final: Any) -> None:
    from qualify_api.creative.queue_dispatch import CheckpointError

    store = ExpiringLeases(one_final)
    service = SlowFinals(store, composes=False, seconds=0.0)

    def lost(**_kwargs: Any) -> None:
        raise CheckpointError("preparation lease lost")

    service.run_queued_final = lost  # type: ignore[method-assign]
    PipelinePreparation(service, store, [TENANT])()  # type: ignore[arg-type]
    assert store.releases == [False]  # not done: the next pass finishes it
