"""VE-12 RA5 (m-24921060): the 30-day purge of the reel cuts a part keeps in its piece
folder (`referentes.reel_window_retention`), offline — the real `ObjectGate` over an
in-memory store that reports each object's `LastModified`.

Pins: a window written 29 days ago stays, one of 30 days goes although the piece lives
90; the rest of the piece folder is never touched; a second pass deletes nothing; a dry
run deletes nothing; a bucket refusal stops the pass once, transient errors skip one
draft; the daily chore runs it isolated from the piece purge (both ways) and never calls
the global `reel_retention`."""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.objects.gate import DeleteRefused, ObjectGate, StoredObject

from qualify_api.creative import retention_job
from qualify_api.referentes import reel_window_retention as wr
from qualify_api.referentes.reel_analysis_window import window_key

NOW = datetime(2026, 12, 20, 9, 0, tzinfo=UTC)
TENANT = UUID("11111111-1111-1111-1111-111111111111")
OTHER = UUID("22222222-2222-2222-2222-222222222222")


class DatedStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, datetime]] = {}
        self.refuse: str | None = None
        self.fail: set[str] = set()
        self.delete_calls = 0

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        self.objects[key] = (fileobj.read(), NOW)

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key][0])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for key, (data, at) in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield StoredObject(key, len(data), at)

    def delete_keys(self, keys: Sequence[str]) -> None:
        self.delete_calls += 1
        if self.refuse:
            raise DeleteRefused(len(keys), (self.refuse,))
        if any(any(f in k for f in self.fail) for k in keys):
            raise DeleteRefused(len(keys), ("InternalError",))
        for key in keys:
            self.objects.pop(key, None)


def _window(store: DatedStore, tenant: UUID, draft: UUID, days_ago: float) -> str:
    key = window_key(tenant, draft, uuid4(), 0, 6)
    store.objects[key] = (b"mp4" * 5, NOW - timedelta(days=days_ago))
    return key


def _piece_file(store: DatedStore, tenant: UUID, draft: UUID, name: str) -> str:
    key = f"t/{tenant}/generated/{draft}/{name}"
    store.objects[key] = (b"x", NOW - timedelta(days=60))
    return key


def _drafts(mapping: dict[UUID, list[UUID]]) -> Any:
    seen: list[tuple[UUID, datetime]] = []

    def read(tenant_id: UUID, cutoff: datetime) -> list[UUID]:
        seen.append((tenant_id, cutoff))
        return mapping.get(tenant_id, [])

    read.seen = seen  # type: ignore[attr-defined]
    return read


def test_day_29_stays_day_30_goes_and_the_piece_is_untouched() -> None:
    store = DatedStore()
    draft = uuid4()
    young = _window(store, TENANT, draft, 29)
    old = _window(store, TENANT, draft, 30)
    piece = {
        _piece_file(store, TENANT, draft, "r1/video.mp4"),
        _piece_file(store, TENANT, draft, "r1/final.mp4"),
    }
    gate = ObjectGate(store)
    drafts = _drafts({TENANT: [draft]})

    [report] = wr.run_window_purge([TENANT], execute=True, now=NOW, gate=gate, drafts=drafts)
    assert (report.drafts, report.objects, report.errors, report.refused) == (1, 1, [], False)
    assert old not in store.objects and young in store.objects
    assert piece <= set(store.objects)
    assert drafts.seen == [(TENANT, NOW - timedelta(days=30))]

    [again] = wr.run_window_purge([TENANT], execute=True, now=NOW, gate=gate, drafts=drafts)
    assert again.objects == 0


def test_a_dry_run_reports_and_deletes_nothing() -> None:
    store = DatedStore()
    draft = uuid4()
    _window(store, TENANT, draft, 45)
    [report] = wr.run_window_purge(
        [TENANT], execute=False, now=NOW, gate=ObjectGate(store), drafts=_drafts({TENANT: [draft]})
    )
    assert report.objects == 1 and len(store.objects) == 1 and store.delete_calls == 0


def test_a_bucket_refusal_stops_the_pass_once(caplog: pytest.LogCaptureFixture) -> None:
    store = DatedStore()
    store.refuse = "ObjectLockedByBucketPolicy"
    a, b = uuid4(), uuid4()
    _window(store, TENANT, a, 40)
    _window(store, TENANT, b, 40)
    _window(store, OTHER, uuid4(), 40)
    drafts = _drafts({TENANT: [a, b], OTHER: [uuid4()]})
    with caplog.at_level("ERROR", logger=wr.logger.name):
        reports = wr.run_window_purge(
            [TENANT, OTHER], execute=True, now=NOW, gate=ObjectGate(store), drafts=drafts
        )
    assert [r.refused for r in reports] == [True]  # OTHER never tried
    assert store.delete_calls == 1 and len(store.objects) == 3
    assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 1


def test_a_transient_error_skips_one_draft_and_the_others_go_on() -> None:
    store = DatedStore()
    bad, good = uuid4(), uuid4()
    _window(store, TENANT, bad, 40)
    kept = _window(store, TENANT, good, 40)
    store.fail.add(str(bad))
    [report] = wr.run_window_purge(
        [TENANT],
        execute=True,
        now=NOW,
        gate=ObjectGate(store),
        drafts=_drafts({TENANT: [bad, good]}),
    )
    assert report.errors == [bad] and report.objects == 1 and kept not in store.objects


def test_no_scope_and_no_discovery_does_nothing() -> None:
    assert wr.run_window_purge(None, execute=True, now=NOW, discover=lambda _now: []) == []


# --------------------------------------------------------------------------------------
# the daily chore
# --------------------------------------------------------------------------------------


def _quiet_chore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(retention_job.WARNING_ENV, "0")
    import qualify_api.creative.brand_prefill_media as prefill

    monkeypatch.setattr(prefill, "run_cleanup", lambda scope, execute: None)


def test_a_failing_piece_purge_does_not_stop_the_window_purge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _quiet_chore(monkeypatch)
    calls: list[tuple[object, bool]] = []

    def broken(scope: object, *, execute: bool) -> list[object]:
        raise RuntimeError("R2 down")

    monkeypatch.setattr(retention_job, "run_piece_purge", broken)
    monkeypatch.setattr(
        wr, "run_window_purge", lambda scope, *, execute: calls.append((scope, execute))
    )
    monkeypatch.setenv(retention_job.EXECUTE_ENV, "0")
    assert retention_job.daily_chore([TENANT])() == []
    assert calls == [([TENANT], False)]


def test_a_failing_window_purge_does_not_stop_the_piece_purge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _quiet_chore(monkeypatch)
    pieces: list[object] = []

    def broken(scope: object, *, execute: bool) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(wr, "run_window_purge", broken)
    monkeypatch.setattr(
        retention_job,
        "run_piece_purge",
        lambda scope, *, execute: pieces.append(scope) or ["report"],
    )
    assert retention_job.daily_chore(None)() == ["report"]
    assert pieces == [None]


def test_the_daily_chore_never_runs_the_global_reel_purge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RN14: only the `reels-worker` deletes under `public/reel-analyses/`; a
    `calendar-worker --tenant X` must never purge every business's reels."""
    from qualify_api.referentes import reel_retention

    _quiet_chore(monkeypatch)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("daily_chore called the global reel purge")

    monkeypatch.setattr(reel_retention, "purge_reel_sources", forbidden)
    monkeypatch.setattr(retention_job, "run_piece_purge", lambda scope, *, execute: [])
    monkeypatch.setattr(wr, "run_window_purge", lambda scope, *, execute: [])
    retention_job.daily_chore([TENANT])()
    retention_job.daily_chore(None)()


def test_just_piece_purge_runs_the_window_purge_too(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.planner import worker

    seen: list[tuple[object, bool]] = []
    monkeypatch.setattr(retention_job, "run_piece_purge", lambda ids, *, execute: [])
    monkeypatch.setattr(
        retention_job,
        "run_reel_windows_purge",
        lambda ids, *, execute: seen.append((ids, execute)),
    )
    assert worker.main(["--purge-pieces", "--tenant", str(TENANT)]) == 0
    assert seen == [([TENANT], False)]  # a dry run unless --execute


def test_an_injected_purge_replaces_both_halves(monkeypatch: pytest.MonkeyPatch) -> None:
    """The planner's `purge=` seam stands for the whole manual purge: injecting it runs
    neither the default piece purge nor the window purge (like `chore=` for the chore)."""
    from qualify_api.planner import worker

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the default purge ran despite an injected one")

    monkeypatch.setattr(retention_job, "run_piece_purge", forbidden)
    monkeypatch.setattr(retention_job, "run_reel_windows_purge", forbidden)
    injected: list[tuple[object, bool]] = []
    code = worker.main(
        ["--purge-pieces", "--tenant", str(TENANT), "--execute"],
        purge=lambda ids, execute: injected.append((ids, execute)),
    )
    assert code == 0 and injected == [([TENANT], True)]
