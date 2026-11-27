"""m-25042483: a part join and a local assembly never run at the same time in the creative
worker — the local one waits for the next pass (never fails); offline."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from qualify_api.creative import heavy_video
from qualify_api.creative.heavy_video import LocalAssemblyWait, assembling, joining
from qualify_api.creative.queue_dispatch import CheckpointError
from qualify_api.creative.worker import pipeline as worker_pipeline
from qualify_api.creative.worker.pipeline import BackgroundJoins, PipelinePreparation

TENANT = uuid4()


def test_a_local_assembly_waits_while_a_join_holds_the_gate() -> None:
    assert issubclass(LocalAssemblyWait, CheckpointError)  # the worker retries it
    with joining():
        assert heavy_video.busy()
        with pytest.raises(LocalAssemblyWait), assembling():
            pytest.fail("a local assembly never runs during a join")
    with assembling():  # the join over: it goes on
        assert heavy_video.busy()
    assert not heavy_video.busy()


def test_a_join_waits_for_the_local_assembly_in_flight() -> None:
    order: list[str] = []

    def join() -> None:
        with joining():
            order.append("join")

    with assembling():
        thread = threading.Thread(target=join)
        thread.start()
        time.sleep(0.2)  # the join thread is blocked on the gate by now
        order.append("local done")
    thread.join(5)
    assert order == ["local done", "join"]


def test_the_gate_is_released_when_the_local_assembly_fails() -> None:
    with pytest.raises(OSError), assembling():
        raise OSError("disk full")
    assert not heavy_video.busy()


class LeaseStore:
    def __init__(self, run: Any = None) -> None:
        self.run = run
        self.releases: list[bool] = []

    def acquire(self, *_args: Any) -> Any:
        return self.run

    def renew(self, run: object) -> bool:
        return True

    def release(self, run: object, *, completed: bool) -> None:
        self.releases.append(completed)


def test_a_background_join_holds_the_gate_while_it_runs() -> None:
    store = LeaseStore()
    preparation = PipelinePreparation(SimpleNamespace(), store, [TENANT])  # type: ignore[arg-type]
    seen: list[bool] = []
    preparation._join = lambda _tenant, _draft: seen.append(heavy_video.busy())  # type: ignore[method-assign]
    joins = BackgroundJoins(store)  # type: ignore[arg-type]
    run = SimpleNamespace(draft_id=uuid4(), tenant_id=TENANT, phase="join")
    assert joins.start(run, preparation._join_run)
    assert joins.shutdown(timeout=None)
    assert seen == [True] and store.releases == [True]
    assert not heavy_video.busy()


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> _Rows:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


def test_a_waiting_local_video_is_released_not_done_and_not_an_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    draft_id = uuid4()
    run = SimpleNamespace(
        draft_id=draft_id, tenant_id=TENANT, revision=1, phase="generation", step=0, video=0
    )

    @contextmanager
    def session(_tenant: Any) -> Any:
        yield SimpleNamespace(
            execute=lambda *_a, **_k: _Rows(
                [{"draft_id": draft_id, "revision": 1, "phase": "generation"}]
            )
        )

    monkeypatch.setattr(worker_pipeline, "tenant_session", session)

    def run_generation(**_kwargs: Any) -> None:
        with assembling():  # what `produce_local` does
            pytest.fail("made during a join")

    service = SimpleNamespace(
        _repo=SimpleNamespace(get_draft=lambda **_k: SimpleNamespace(revision=1)),
        run_generation=run_generation,
    )
    store = LeaseStore(run)
    preparation = PipelinePreparation(service, store, [TENANT])  # type: ignore[arg-type]
    with caplog.at_level(logging.INFO, logger=worker_pipeline.logger.name), joining():
        preparation()
    assert store.releases == [False]  # still dirty: the next pass makes it
    assert "local_waits" in caplog.text and "reason=LocalAssemblyWait" in caplog.text
    assert "preparation_failed" not in caplog.text
