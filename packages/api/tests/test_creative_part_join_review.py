"""VE-10a review fixes and the logo (Deivid, 2026-11-06), offline.

- The join runs off the worker's main loop (`BackgroundJoins`): the loop keeps beating
  and claiming, one join at a time, a clean shutdown.
- A `JoinError` is final only when the parts themselves are bad; IO errors retry.
- A PART's preview shows the parent's logo, laid after Seedance (never sent), and keeps
  its clean file; the join reads the clean files and lays the logo ONCE.
- A logo change is a new fingerprint; a brand without a logo gets none.
"""

from __future__ import annotations

import io
import threading
import time
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.video.join import JoinError

from qualify_api.creative import part_join
from qualify_api.creative.part_join import (
    PartPreview,
    PartsToJoin,
    io_failure,
    join_fingerprint,
    join_preview,
    part_span,
)
from qualify_api.creative.worker.pipeline import BackgroundJoins

from .test_creative_part_join import PARENT, TENANT, Joiner, Joins, Store, _files, _part, _snapshot

LOGO_KEY = f"t/{TENANT}/brand/logo.png"


def _logo_png() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(out, "PNG")
    return out.getvalue()


def _with_logo(snapshot: PartsToJoin, key: str | None = LOGO_KEY) -> PartsToJoin:
    return PartsToJoin(**{**snapshot.__dict__, "logo_key": key})


# ---------------------------------------------------------------------------
# fix 2: which JoinError is final


def test_a_part_that_cannot_be_decoded_is_final() -> None:
    try:
        try:
            raise ValueError("Invalid data found when processing input")
        except ValueError as cause:
            raise JoinError("part 2 could not be joined") from cause
    except JoinError as exc:
        assert not io_failure(exc)
    assert not io_failure(JoinError("part.mp4 has no video stream"))


def test_an_io_failure_inside_the_join_is_retried() -> None:
    parts = (_part(1), _part(2))
    for cause in (OSError(28, "No space left on device"), FileNotFoundError("part-1.mp4")):
        error = JoinError("part 1 could not be joined")
        error.__cause__ = cause
        joins = Joins(_snapshot(*parts))
        with pytest.raises(JoinError):
            join_preview(Store(_files(*parts)), joins, TENANT, PARENT, joiner=Joiner(error=error))
        assert io_failure(error) and joins.saved == []


def test_a_stream_cut_short_while_fetching_a_part_is_retried() -> None:
    parts = (_part(1), _part(2))

    class CutStore(Store):
        def copy_to_file(self, tenant_id, key, path):  # noqa: ANN001, ANN201
            raise OSError(f"{key}: copied 10 of 20 bytes")

    with pytest.raises(OSError):
        join_preview(CutStore(_files(*parts)), Joins(_snapshot(*parts)), TENANT, PARENT,
                     joiner=Joiner())  # fmt: skip


def test_the_r2_copy_checks_its_length(tmp_path: Path) -> None:
    from qualify_api.creative.media import R2ReadingMediaStore

    class Gate:
        def object_size(self, tenant_id, key):  # noqa: ANN001, ANN201
            return 20

        def open_object(self, tenant_id, key):  # noqa: ANN001, ANN201
            return io.BytesIO(b"x" * 10)  # the stream ends early

    store = R2ReadingMediaStore(local=None, gate=Gate())  # type: ignore[arg-type]
    with pytest.raises(OSError, match="10 of 20"):
        store.copy_to_file(TENANT, f"t/{TENANT}/generated/x/r1/clip.mp4", tmp_path / "a.mp4")


# ---------------------------------------------------------------------------
# the logo of the joined preview


def test_the_join_lays_the_logo_once_over_the_clean_parts() -> None:
    clean = [f"t/{TENANT}/generated/p{i}/r1/clip.mp4" for i in (1, 2)]
    parts = tuple(
        PartPreview(
            **{
                **_part(i).__dict__,
                "object_key": f"t/{TENANT}/generated/p{i}/r1/clip-logo.mp4",
                "params": {
                    **_part(i).params,
                    "part": {**_part(i).params["part"], "clean_key": clean[i - 1]},
                },
            }
        )
        for i in (1, 2)
    )
    store = Store(
        {
            clean[0]: b"clean-1",
            clean[1]: b"clean-2",
            str(parts[0].object_key): b"LOGO-1",
            str(parts[1].object_key): b"LOGO-2",
            LOGO_KEY: _logo_png(),
        }
    )
    joiner = Joiner()
    write = join_preview(store, Joins(_with_logo(_snapshot(*parts))), TENANT, PARENT,
                         joiner=joiner)  # fmt: skip
    assert write is not None
    # the clean files were joined — never the ones already carrying a logo
    assert store.files[write.object_key] == b"joined:clean-1|clean-2"
    # ONE overlay for the whole video, the logo-only layer every Clip uses
    (overlay,) = joiner.overlays
    assert overlay is not None and overlay[:4] == b"\x89PNG"
    logo = write.params["join"]["logo"]
    assert logo["key"] == LOGO_KEY and len(logo["sha256"]) == 16
    assert write.params["draft"]["logo"] == logo
    assert [p["joined_key"] for p in write.params["join"]["parts"]] == clean


def test_a_brand_without_a_logo_joins_without_one() -> None:
    parts = (_part(1), _part(2))
    joiner = Joiner()
    write = join_preview(Store(_files(*parts)), Joins(_snapshot(*parts)), TENANT, PARENT,
                         joiner=joiner)  # fmt: skip
    assert write is not None and joiner.overlays == [None]
    assert write.params["join"]["logo"] == "sin logo"


def test_a_logo_that_cannot_be_read_joins_without_it() -> None:
    parts = (_part(1), _part(2))
    joiner = Joiner()
    write = join_preview(Store(_files(*parts)), Joins(_with_logo(_snapshot(*parts))), TENANT,
                         PARENT, joiner=joiner)  # fmt: skip
    assert write is not None and joiner.overlays == [None]
    assert write.params["join"]["logo"] == "sin logo"


def test_another_logo_is_another_fingerprint() -> None:
    parts = (_part(1), _part(2))
    spans = [part_span(p.params) for p in parts]
    without = join_fingerprint(parts, spans)
    with_logo = join_fingerprint(parts, spans, LOGO_KEY)
    other = join_fingerprint(parts, spans, f"t/{TENANT}/brand/logo-2.png")
    assert len({without, with_logo, other}) == 3
    # and the joined preview made without a logo is joined again once one is chosen
    joins, store, joiner = Joins(_snapshot(*parts)), Store(_files(*parts)), Joiner()
    first = join_preview(store, joins, TENANT, PARENT, joiner=joiner)
    joins.save(tenant_id=TENANT, parent_id=PARENT, write=first)  # type: ignore[arg-type]
    store.files[LOGO_KEY] = _logo_png()
    joins.snapshot = _with_logo(joins.snapshot)
    second = join_preview(store, joins, TENANT, PARENT, joiner=joiner)
    assert second is not None and second.object_key != first.object_key  # type: ignore[union-attr]


def _clip(path: Path, seconds: float) -> bytes:
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=24)
        video.width, video.height, video.pix_fmt = 64, 114, "yuv420p"
        for i in range(round(seconds * 24)):
            frame = av.VideoFrame.from_ndarray(
                np.full((114, 64, 3), 30, dtype=np.uint8), format="rgb24"
            )
            frame.pts, frame.time_base = i, Fraction(1, 24)
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path.read_bytes()


def _frames(data: bytes, tmp: Path) -> list[Any]:
    av = pytest.importorskip("av")
    path = tmp / f"read-{uuid4().hex}.mp4"
    path.write_bytes(data)
    with av.open(str(path)) as source:
        return [f.to_ndarray(format="rgb24") for f in source.decode(source.streams.video[0])]


def test_the_real_join_shows_the_logo_on_every_frame_once(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    np = pytest.importorskip("numpy")
    monkeypatch.setattr(part_join, "JOIN_PREVIEW_SIZE", (96, 170))
    parts = (_part(1, seconds=1, generation=1), _part(2, seconds=1, generation=1))
    files = {str(p.object_key): _clip(tmp_path / f"{i}.mp4", 1) for i, p in enumerate(parts)}
    plain = Store(files)
    branded = Store({**files, LOGO_KEY: _logo_png()})
    without = join_preview(plain, Joins(_snapshot(*parts)), TENANT, PARENT)
    with_logo = join_preview(branded, Joins(_with_logo(_snapshot(*parts))), TENANT, PARENT)
    assert without is not None and with_logo is not None
    a = _frames(plain.files[without.object_key], tmp_path)
    b = _frames(branded.files[with_logo.object_key], tmp_path)
    assert len(a) == len(b) == 48
    reddish = [
        int(((fb[..., 0].astype(int) - fa[..., 0].astype(int)) > 60).sum())
        for fa, fb in zip(a, b, strict=True)
    ]
    # the logo is on every frame, first part to last, in the same place and size
    assert all(n > 0 for n in reddish) and max(reddish) - min(reddish) <= max(reddish) * 0.2
    assert np is not None


# ---------------------------------------------------------------------------
# fix 1: the join off the main loop


class LeaseStore:
    def __init__(self) -> None:
        self.releases: list[bool] = []
        self.renews = 0

    def renew(self, run: object) -> bool:
        self.renews += 1
        return True

    def release(self, run: object, *, completed: bool) -> None:
        self.releases.append(completed)


def _run() -> Any:
    return SimpleNamespace(draft_id=uuid4(), phase="join")


def test_one_join_at_a_time_and_the_thread_releases_its_run() -> None:
    store = LeaseStore()
    joins = BackgroundJoins(store)  # type: ignore[arg-type]
    gate, done = threading.Event(), []
    assert joins.start(_run(), lambda _run: (gate.wait(5), done.append(1)))
    assert joins.busy()
    assert not joins.start(_run(), lambda _run: done.append(2))  # never a second one
    gate.set()
    assert joins.shutdown(timeout=None)
    assert done == [1] and store.releases == [True]


def test_a_failed_join_releases_its_run_not_done() -> None:
    store = LeaseStore()
    joins = BackgroundJoins(store)  # type: ignore[arg-type]

    def boom(_run: object) -> None:
        raise OSError("disk full")

    assert joins.start(_run(), boom)
    assert joins.shutdown(timeout=None)
    assert store.releases == [False]


def test_a_stopping_worker_abandons_a_long_join_cleanly() -> None:
    store = LeaseStore()
    joins = BackgroundJoins(store)  # type: ignore[arg-type]
    release = threading.Event()
    assert joins.start(_run(), lambda _run: release.wait(5))
    began = time.monotonic()
    assert joins.shutdown(timeout=0.2) is False  # it did not finish in the grace
    assert time.monotonic() - began < 2
    assert store.releases == [False]  # handed back NOT done: redone or reused next start
    assert not joins.start(_run(), lambda _run: None)  # nothing new after shutdown
    release.set()


def test_the_loop_keeps_beating_and_claiming_while_a_slow_join_runs() -> None:
    from qualify_api.creative.worker.runner import run_loop

    from .test_creative_worker_runner import Clock, FakeBytePlus, MemoryStore, make_worker

    worker = make_worker(MemoryStore(), FakeBytePlus(), Clock())
    claims: list[int] = []
    real_claim = worker.claim_round

    def claim_round(capacity: int) -> list[Any]:
        claims.append(capacity)
        return real_claim(capacity)

    worker.claim_round = claim_round  # type: ignore[method-assign]
    store = LeaseStore()
    joins = BackgroundJoins(store)  # type: ignore[arg-type]
    finish = threading.Event()
    started: list[bool] = []
    beats: list[float] = []

    def preparation() -> None:  # what PipelinePreparation does with a join run
        started.append(joins.start(_run(), lambda _run: finish.wait(10)))

    began = time.monotonic()
    run_loop(
        worker,
        once=False,
        interval=0.02,
        preparation=preparation,
        on_round=lambda: beats.append(time.monotonic()),
        max_rounds=10,
    )
    assert time.monotonic() - began < 5  # the loop never waited for the join
    assert joins.busy()
    assert len(beats) == 10 and len(claims) == 10  # beat and claimed every round
    assert started == [True] + [False] * 9  # one join at a time
    finish.set()
    assert joins.shutdown(timeout=None) and store.releases == [True]


# ---------------------------------------------------------------------------
# a PART's own preview shows the logo (laid after Seedance, never sent)


class LogoFitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def fit(self, video: bytes, *, size, overlay=None, keep_audio=False, **_: Any):  # noqa: ANN001, ANN201
        self.calls.append({"video": video, "size": size, "overlay": overlay})
        return SimpleNamespace(data=b"LOGO|" + video, poster=None)


def _part_producer(logo_key: str | None):  # noqa: ANN202
    from .test_creative_media_byteplus import TENANT_ID
    from .test_creative_part_clip import _setup

    producer, store, seedance, _, _ = _setup()
    key = logo_key and logo_key.format(tenant=TENANT_ID)
    if key:
        store.files[key] = _logo_png()
    fitter = LogoFitter()
    producer._fitter = fitter
    producer._part_joins = SimpleNamespace(parent_logo_key=lambda **_: key)
    return producer, store, seedance, fitter, key


def test_a_part_preview_shows_the_logo_and_keeps_its_clean_file() -> None:
    from .test_creative_media_byteplus import _produce
    from .test_creative_part_clip import _part_brief

    producer, store, seedance, fitter, key = _part_producer("t/{tenant}/brand/logo.png")
    outcome = _produce(producer, _part_brief("reference"), uuid4())
    assert outcome.failure is None, outcome.detail
    # the logo never reaches the vendor: one photo, no logo image, the VE-09 prompt
    (request,) = seedance.requests
    assert len(request.params["reference_images"]) == 1
    assert "No logo image is supplied" in str(request.params["prompt"])
    (video,) = outcome.media
    part = video.params["part"]
    assert video.object_key.endswith("clip-logo.mp4") and video.params["logo"] is True
    assert part["clean_key"].endswith("/clip.mp4") and part["clean_key"] != video.object_key
    assert store.files[part["clean_key"]] == b"mp4-bytes"  # as Seedance made it
    assert store.files[video.object_key] == b"LOGO|mp4-bytes"
    (call,) = fitter.calls
    assert call["overlay"][:4] == b"\x89PNG" and call["video"] == b"mp4-bytes"
    assert part["logo"]["key"] == key and len(part["logo"]["sha256"]) == 16
    # and the join reads the clean one: never a second logo
    preview = PartPreview(
        draft_id=uuid4(), part_index=1, status="generated", revision=1, version_id=uuid4(),
        object_key=video.object_key, params=video.params,
    )  # fmt: skip
    assert preview.join_source == part["clean_key"]


def test_a_part_of_a_brand_without_a_logo_gets_none() -> None:
    from .test_creative_media_byteplus import _produce
    from .test_creative_part_clip import _part_brief

    producer, _, _, fitter, _ = _part_producer(None)
    outcome = _produce(producer, _part_brief("reference"), uuid4())
    assert outcome.failure is None, outcome.detail
    (video,) = outcome.media
    assert video.object_key.endswith("/clip.mp4") and fitter.calls == []
    assert video.params["part"]["clean_key"] == video.object_key
    assert video.params["part"]["logo"] == "sin logo"


def test_a_parents_logo_of_another_business_is_never_read() -> None:
    from .test_creative_media_byteplus import _produce
    from .test_creative_part_clip import _part_brief

    producer, store, _, fitter, _ = _part_producer(None)
    foreign = f"t/{uuid4()}/brand/logo.png"
    store.files[foreign] = _logo_png()
    producer._part_joins = SimpleNamespace(parent_logo_key=lambda **_: foreign)
    outcome = _produce(producer, _part_brief("reference"), uuid4())
    assert outcome.failure is None and fitter.calls == []


# ---------------------------------------------------------------------------
# re-review: missing files are final, failed reads retry


def test_a_part_file_missing_for_good_is_final() -> None:
    from qualify_shared.objects.gate import ObjectNotFound

    parts = (_part(1), _part(2))

    class Gone(Store):
        def copy_to_file(self, tenant_id, key, path):  # noqa: ANN001, ANN201
            raise ObjectNotFound(key)

    joiner = Joiner()
    write = join_preview(Gone(_files(*parts)), Joins(_snapshot(*parts)), TENANT, PARENT,
                         joiner=joiner)  # fmt: skip
    assert write is None and joiner.calls == []  # done: not re-acquired every pass


def test_a_part_file_that_fails_to_arrive_is_retried() -> None:
    parts = (_part(1), _part(2))

    class Flaky(Store):
        def copy_to_file(self, tenant_id, key, path):  # noqa: ANN001, ANN201
            raise ConnectionError("connection reset by peer")

    with pytest.raises(ConnectionError):
        join_preview(Flaky(_files(*parts)), Joins(_snapshot(*parts)), TENANT, PARENT,
                     joiner=Joiner())  # fmt: skip


def test_a_logo_that_fails_to_read_is_retried_not_dropped() -> None:
    parts = (_part(1), _part(2))

    class FlakyLogo(Store):
        def read(self, key: str) -> bytes:
            if key == LOGO_KEY:
                raise ConnectionError("R2 timed out")
            return super().read(key)

    joins = Joins(_with_logo(_snapshot(*parts)))
    with pytest.raises(ConnectionError):
        join_preview(FlakyLogo({**_files(*parts), LOGO_KEY: _logo_png()}), joins, TENANT,
                     PARENT, joiner=Joiner())  # fmt: skip
    assert joins.saved == []  # never a logo-less join saved in its place


def test_a_logo_missing_from_r2_joins_without_it() -> None:
    from qualify_shared.objects.gate import ObjectNotFound

    parts = (_part(1), _part(2))

    class NoLogo(Store):
        def read(self, key: str) -> bytes:
            if key == LOGO_KEY:
                raise ObjectNotFound(key)
            return super().read(key)

    joiner = Joiner()
    write = join_preview(NoLogo(_files(*parts)), Joins(_with_logo(_snapshot(*parts))), TENANT,
                         PARENT, joiner=joiner)  # fmt: skip
    assert write is not None and joiner.overlays == [None]
    assert write.params["join"]["logo"] == "sin logo"
