"""The idea covers in R2 (`qualify_api.referentes.reel_covers`, ADR 42 R12, m-24854859),
offline: the persistent run is R4's real `reel_runs.run` over `MemoryReelRunStore`, the
vendor and Claude are scripted, the networks' CDN is an `httpx.MockTransport` and R2 an
in-memory store behind the real `PublicObjectGate`.

Pins, per the ticket: 8 ideas among 40 candidates make exactly 8 PUTs; a second run
downloads nothing (only the copies' dates move); `scoped_run` makes no PUT while
`production_run` does; a failure is logged without the URL and never changes the run; a
copy purged since the run read the reel is made again; two businesses write ONE object;
the 30-day purge (day 29 nothing, day 31 the copy) with its dry run, its R2 error and an
idea that used the copy meanwhile; and the route's read (`open_cover`)."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image
from qualify_shared.objects.gate import ObjectNotFound, StoredObject
from qualify_shared.objects.public import PublicObjectGate, reel_cover_key

from qualify_api.claude_tools import CallStats
from qualify_api.referentes import (
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    reel_covers,
    reels_ai,
)
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reel_retention as rt
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_covers import MemoryCoverStore, copy_idea_covers
from qualify_api.referentes.reel_store import STATUS_OK, MemoryReelRunStore
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview

NOW = 1_800_000_000.0
DAY = 24 * 3600
TENANT_A = UUID("a0000000-0000-4000-8000-0000000000a1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000b2")
BRIEF = review_ai.BrandBrief(handle="heladeria", rubro=("heladería",))
CDN_HOST = "scontent-bog1-1.cdninstagram.com"


def _cover_url(reel_id: str, *, expires: float = NOW + 4 * DAY) -> str:
    """An Instagram cover URL as the vendor hands it: signed, `oe` = hex epoch."""
    return f"https://{CDN_HOST}/v/t51.2885-15/{reel_id}.jpg?oe={int(expires):X}&_nc_sid=8b3546"


def _jpeg(width: int = 1080, height: int = 1920) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (240, 180, 60)).save(out, "JPEG", quality=90)
    return out.getvalue()


PICTURE = _jpeg()


def _reel(reel_id: str, days_ago: float, views: int) -> dict[str, Any]:
    return {
        "id": reel_id,
        "network": "instagram",
        "handle": "heladosdonde",
        "url": f"https://www.instagram.com/reel/{reel_id}/",
        "caption": f"helado de yogur {reel_id}",
        "cover": _cover_url(reel_id),
        "takenAt": NOW - days_ago * DAY,
        "views": views,
        "likes": views // 10,
        "comments": 1,
        "shares": None,
        "saves": None,
        "seconds": 12,
        "sound": "Audio original",
        "video": f"https://{CDN_HOST}/o1/v/t16/{reel_id}.mp4",
    }


#: 40 candidates for a 30-day run: the month's 32 most viewed (8-29 days old) plus the
#: week's 8 (the least viewed, so they are not already in the month's top).
FEED = [_reel(f"M{n:02d}", 8 + n * 0.6, 50_000 - n * 1_000) for n in range(32)] + [
    _reel(f"W{n}", 1 + n * 0.5, 900 - n * 10) for n in range(8)
]


@dataclass
class Vendor:
    lists: int = 0

    def fetch(self, network: str, handle: str, **_: Any) -> list[dict[str, Any]]:
        self.lists += 1
        return [dict(r) for r in FEED]

    def transcribe(self, reel: dict[str, Any], client: Any) -> str:
        return ""


@dataclass
class Claude:
    """Keeps every reel: the ideas are then the 8 most viewed."""

    reviewed: list[str] = field(default_factory=list)

    def review(self, brief: Any, batch: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
        self.reviewed += [r.id for r in batch]
        answers = [
            ReelReview(id=r.id, fits=True, reason="ok", format="receta", affinity="producto")
            for r in batch
        ]
        return answers, CallStats(reels_ai.REVIEW_MODEL, None, 1000, 100)


class Clock:
    def __init__(self, moment: float = NOW) -> None:
        self.moment = moment

    def __call__(self) -> float:
        return self.moment


class R2:
    """The bucket: what was PUT, how often, and keys that refuse to be written/deleted."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.puts: list[str] = []
        self.broken: set[str] = set()

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        if key in self.broken:
            raise RuntimeError("R2 answered 503")
        self.puts.append(key)
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> io.BytesIO:
        if key not in self.objects:
            raise ObjectNotFound(key)
        return io.BytesIO(self.objects[key][0])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for key, (data, _) in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield StoredObject(key, len(data))

    def delete_keys(self, keys: Sequence[str]) -> None:
        if any(key in self.broken for key in keys):
            raise RuntimeError("R2 refused to delete 1 object(s): InternalError")
        for key in keys:
            self.objects.pop(key, None)


class CDN:
    """The network's CDN: answers every cover with a picture, or `status` for some."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.status: dict[str, int] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1].removesuffix(".jpg")
        self.asked.append(name)
        status = self.status.get(name, 200)
        if status != 200:
            return httpx.Response(status, headers={"content-type": "text/html"}, content=b"no")
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=PICTURE)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@dataclass
class World:
    store: MemoryReelRunStore
    covers: MemoryCoverStore
    repo: MemoryReferentesRepository
    vendor: Vendor
    claude: Claude
    clock: Clock
    r2: R2
    gate: PublicObjectGate
    cdn: CDN


@pytest.fixture
def world() -> World:
    store, r2 = MemoryReelRunStore(), R2()
    return World(
        store=store,
        covers=MemoryCoverStore(store),
        repo=MemoryReferentesRepository(),
        vendor=Vendor(),
        claude=Claude(),
        clock=Clock(),
        r2=r2,
        gate=PublicObjectGate(r2),
        cdn=CDN(),
    )


def _brand(world: World, tenant: UUID) -> UUID:
    brand = uuid4()
    world.repo.add_brand(tenant_id=tenant, brand_id=brand)
    world.repo.save_phase(
        NewDiscoveryPhase(
            tenant_id=tenant,
            brand_id=brand,
            phase_key="sector",
            algorithm_version=1,
            seed_signature="s",
            seed={"handle": "heladeria", "terms": ["heladería"], "hashtags": []},
            title="Sector",
            accounts=(
                NewDiscoveredAccount(
                    network="instagram", handle="heladosdonde", card={"kind": "marca"}
                ),
            ),
        )
    )
    world.repo.set_label(
        tenant_id=tenant,
        brand_id=brand,
        network="instagram",
        handle="heladosdonde",
        label="referente",
        labeled_by=None,
    )
    return brand


def _copying_hook(world: World, reports: list[reel_covers.CoverReport]) -> rr.IdeaAnalyzer:
    """The production hook's first half, with the test's R2, CDN and clock."""

    def hook(tenant: UUID, brand: UUID, run_id: UUID, sources: Any) -> Decimal:
        with world.cdn.client() as client:
            reports.append(
                copy_idea_covers(
                    tenant,
                    run_id,
                    sources,
                    gate=world.gate,
                    store=world.covers,
                    client=client,
                    clock=world.clock,
                )
            )
        return Decimal("0")

    return hook


def _run(
    world: World, tenant: UUID, brand: UUID, *, trigger: str = "weekly", **kwargs: Any
) -> rr.RunOutcome:
    queued = rr.enqueue_run(tenant, brand, trigger, store=world.store, clock=world.clock)
    return rr.run(
        tenant,
        queued.id,
        store=world.store,
        repository=world.repo,
        brief=lambda t, b: BRIEF,
        api_key="k",
        fetch=world.vendor.fetch,
        transcribe_fetch=world.vendor.transcribe,
        review=world.claude.review,
        clock=world.clock,
        sleep=lambda seconds: None,
        **kwargs,
    )


def _idea_ids(world: World, tenant: UUID, brand: UUID, run_id: UUID) -> list[str]:
    return [i.reel.reel_id for i in world.store.ideas(tenant, brand, run_id)]


# --------------------------------------------------------------------------------------
# the copy, during the run
# --------------------------------------------------------------------------------------


def test_eight_ideas_among_forty_candidates_make_exactly_eight_puts(world: World) -> None:
    brand = _brand(world, TENANT_A)
    reports: list[reel_covers.CoverReport] = []
    outcome = _run(world, TENANT_A, brand, analyze=_copying_hook(world, reports))

    assert outcome.status == STATUS_OK and len(world.claude.reviewed) == 40
    ideas = _idea_ids(world, TENANT_A, brand, outcome.run_id)
    assert len(ideas) == outcome.ideas == rr.IDEAS_PER_RUN == 8
    assert sorted(world.r2.puts) == sorted(reel_cover_key("instagram", i) for i in ideas)
    assert sorted(world.cdn.asked) == sorted(ideas)  # never a mere candidate
    (report,) = reports
    assert (report.ideas, report.copied, report.reused, report.failed) == (8, 8, 0, 0)
    for idea in world.store.ideas(TENANT_A, brand, outcome.run_id):
        assert idea.reel.cover_r2_key == reel_cover_key("instagram", idea.reel.reel_id)
        assert idea.reel.cover_url == _cover_url(idea.reel.reel_id)
        data, kind = world.r2.objects[idea.reel.cover_r2_key]
        with Image.open(io.BytesIO(data)) as copy:
            assert (kind, copy.format, max(copy.size)) == ("image/jpeg", "JPEG", 720)
    assert all(t == datetime.fromtimestamp(NOW, UTC) for t in world.covers.used.values())


def test_a_second_run_downloads_nothing_and_only_moves_the_dates(world: World) -> None:
    brand = _brand(world, TENANT_A)
    reports: list[reel_covers.CoverReport] = []
    first = _run(world, TENANT_A, brand, analyze=_copying_hook(world, reports))
    asked, puts = list(world.cdn.asked), list(world.r2.puts)

    world.clock.moment += DAY
    second = _run(world, TENANT_A, brand, trigger="manual", analyze=_copying_hook(world, reports))
    assert second.status == STATUS_OK
    assert _idea_ids(world, TENANT_A, brand, second.run_id) == _idea_ids(
        world, TENANT_A, brand, first.run_id
    )
    assert world.cdn.asked == asked and world.r2.puts == puts  # no download, no PUT
    assert (reports[-1].reused, reports[-1].copied) == (8, 0)
    later = datetime.fromtimestamp(NOW + DAY, UTC)
    assert set(world.covers.used.values()) == {later}


def test_two_businesses_with_the_same_idea_write_one_object(world: World) -> None:
    brand_a, brand_b = _brand(world, TENANT_A), _brand(world, TENANT_B)
    reports: list[reel_covers.CoverReport] = []
    _run(world, TENANT_A, brand_a, analyze=_copying_hook(world, reports))
    world.clock.moment += 60
    _run(world, TENANT_B, brand_b, analyze=_copying_hook(world, reports))
    assert len(world.r2.puts) == len(set(world.r2.puts)) == 8
    assert (reports[1].copied, reports[1].reused) == (0, 8)


def test_production_run_copies_the_covers_and_scoped_run_makes_no_put(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FN2 for R12: the `--tenant` worker (local) writes no public R2 object; the
    `--all-tenants` service copies its ideas' covers before VE-04a's analysis."""
    from qualify_api.referentes import reel_analysis_worker
    from qualify_api.referentes import reel_worker as rw

    real_run = rr.run

    def run_here(tenant_id: UUID, run_id: UUID, **kwargs: Any) -> rr.RunOutcome:
        return real_run(
            tenant_id,
            run_id,
            store=world.store,
            repository=world.repo,
            brief=lambda t, b: BRIEF,
            api_key="k",
            fetch=world.vendor.fetch,
            transcribe_fetch=world.vendor.transcribe,
            review=world.claude.review,
            clock=world.clock,
            sleep=lambda seconds: None,
            **kwargs,
        )

    analysed: list[int] = []
    monkeypatch.setattr(rw.reel_runs, "run", run_here)
    monkeypatch.setattr(reel_covers, "_default_gate", lambda: world.gate)
    monkeypatch.setattr(reel_covers, "default_store", lambda: world.covers)
    monkeypatch.setattr(reel_covers, "fetch_cover", lambda url, client: (PICTURE, "image/jpeg"))
    # the hook's copy judges each link's signature at the run's clock, never the machine's
    # (the feed's links are signed to expire at NOW + 4 days, a fixed date)
    monkeypatch.setattr(
        reel_covers, "copy_idea_covers", partial(reel_covers.copy_idea_covers, clock=world.clock)
    )
    monkeypatch.setattr(
        reel_analysis_worker,
        "analyze_run_ideas",
        lambda tenant, brand, run, sources: analysed.append(len(sources)) or Decimal("0"),
    )

    brand_a, brand_b = _brand(world, TENANT_A), _brand(world, TENANT_B)
    scoped = rr.enqueue_run(TENANT_B, brand_b, "weekly", store=world.store, clock=world.clock)
    assert rw.scoped_run(TENANT_B, scoped.id).status == STATUS_OK
    assert world.r2.puts == [] and analysed == []

    every = rr.enqueue_run(TENANT_A, brand_a, "weekly", store=world.store, clock=world.clock)
    outcome = rw.production_run(TENANT_A, every.id)
    assert outcome.status == STATUS_OK and len(world.r2.puts) == outcome.ideas == 8
    assert analysed == [8]


def test_a_failure_is_logged_without_the_url_and_never_changes_the_run(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    brand = _brand(world, TENANT_A)
    world.cdn.status["M00"] = 403  # the CDN refuses one
    world.r2.broken.add(reel_cover_key("instagram", "M01"))  # R2 refuses another
    analysed: list[str] = []
    reports: list[reel_covers.CoverReport] = []
    copy = _copying_hook(world, reports)

    def hook(tenant: UUID, brand_id: UUID, run_id: UUID, sources: Any) -> Decimal:
        copy(tenant, brand_id, run_id, sources)
        analysed.extend(s.post_id for s in sources)
        return Decimal("0.01")

    caplog.set_level(logging.DEBUG, logger="qualify_api.referentes.reel_covers")
    outcome = _run(world, TENANT_A, brand, analyze=hook)
    assert outcome.status == STATUS_OK
    assert world.store.runs[outcome.run_id].status == STATUS_OK
    assert len(analysed) == 8  # the analysis still got every idea
    (report,) = reports
    assert (report.copied, report.failed) == (6, 2)
    assert reel_cover_key("instagram", "M00") not in world.r2.objects
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "http_403" in text and "RuntimeError" in text
    assert CDN_HOST not in text and "oe=" not in text and "https://" not in text


class LockedR2(R2):
    """The production bucket's lock policy (measured on main, 2026-11-05): a stored key
    refuses another PUT (`ObjectLockedByBucketPolicy`); HEAD answers like R2."""

    def size(self, key: str) -> int:
        if key not in self.objects:
            raise ObjectNotFound(key)
        return len(self.objects[key][0])

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        if key in self.objects:
            raise PermissionError("ObjectLockedByBucketPolicy")
        super().put(key, fileobj, content_type)


def test_an_object_left_without_a_row_is_adopted_not_rewritten(world: World) -> None:
    """A PUT whose database write failed left an object no row names (accepted on R12's
    review): the next copy of that reel adopts it — the locked bucket would refuse to
    write it again — and records it on the row."""
    world.r2 = LockedR2()
    world.gate = PublicObjectGate(world.r2)
    brand = _brand(world, TENANT_A)
    reports: list[reel_covers.CoverReport] = []
    first = _run(world, TENANT_A, brand, analyze=_copying_hook(world, reports))
    orphan = _idea_ids(world, TENANT_A, brand, first.run_id)[0]
    reel = world.store.reels[("instagram", orphan)]
    world.store.reels[("instagram", orphan)] = replace(reel, cover_r2_key=None)  # lost row
    world.covers.used.pop(("instagram", orphan))
    puts = list(world.r2.puts)

    world.clock.moment += DAY
    _run(world, TENANT_A, brand, trigger="manual", analyze=_copying_hook(world, reports))

    assert world.r2.puts == puts  # nothing written again
    assert (reports[-1].copied, reports[-1].reused, reports[-1].failed) == (1, 7, 0)
    assert world.store.reels[("instagram", orphan)].cover_r2_key == reel_cover_key(
        "instagram", orphan
    )


def test_an_expired_or_missing_link_is_skipped_and_nothing_is_downloaded(world: World) -> None:
    gone = rr.IdeaSource(
        "instagram",
        "G1",
        "https://www.instagram.com/reel/G1/",
        "",
        cover_url=_cover_url("G1", expires=NOW - 60),
    )
    none = rr.IdeaSource("instagram", "G2", "https://www.instagram.com/reel/G2/", "")
    odd = rr.IdeaSource("instagram", "../G3", "x", "", cover_url=_cover_url("G3"))
    with world.cdn.client() as client:
        report = copy_idea_covers(
            TENANT_A,
            uuid4(),
            [gone, none, odd],
            gate=world.gate,
            store=world.covers,
            client=client,
            clock=world.clock,
        )
    assert (report.skipped, report.copied, report.failed) == (3, 0, 0)
    assert world.cdn.asked == [] and world.r2.puts == []


def test_a_copy_purged_since_the_run_read_the_reel_is_made_again(world: World) -> None:
    """The source says «copied» (read before a purge), but the store has no copy any more:
    the bump finds nothing, so the cover is copied again."""
    brand = _brand(world, TENANT_A)
    _run(world, TENANT_A, brand)  # the reels are stored, nothing copied
    source = rr.IdeaSource(
        "instagram",
        "M00",
        "https://www.instagram.com/reel/M00/",
        "",
        cover_url=_cover_url("M00"),
        cover_r2_key=reel_cover_key("instagram", "M00"),
    )
    with world.cdn.client() as client:
        report = copy_idea_covers(
            TENANT_A,
            uuid4(),
            [source],
            gate=world.gate,
            store=world.covers,
            client=client,
            clock=world.clock,
        )
    assert (report.copied, report.reused) == (1, 0)
    assert world.store.reels[("instagram", "M00")].cover_r2_key == source.cover_r2_key


def test_no_r2_configured_copies_nothing_and_raises_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_shared.objects.config import R2ConfigurationError

    def no_r2() -> PublicObjectGate:
        raise R2ConfigurationError("missing R2 configuration: QUALIFY_R2_BUCKET")

    monkeypatch.setattr(reel_covers, "_default_gate", no_r2)
    brand = _brand(world, TENANT_A)
    _run(world, TENANT_A, brand)
    source = rr.IdeaSource("instagram", "M00", "u", "", cover_url=_cover_url("M00"))
    with world.cdn.client() as client:
        report = copy_idea_covers(
            TENANT_A, uuid4(), [source], store=world.covers, client=client, clock=world.clock
        )
    assert (report.failed, report.copied) == (1, 0)


# --------------------------------------------------------------------------------------
# the route's read
# --------------------------------------------------------------------------------------


def test_open_cover_reads_the_copy_or_says_none(world: World) -> None:
    key = reel_cover_key("tiktok", "7301")
    world.r2.objects[key] = (b"\xff\xd8copy", "image/jpeg")
    assert reel_covers.open_cover("tiktok", "7301", gate=world.gate) == b"\xff\xd8copy"
    assert reel_covers.open_cover("tiktok", "7302", gate=world.gate) is None  # no copy
    assert reel_covers.open_cover("tiktok", "../7301", gate=world.gate) is None
    assert reel_covers.open_cover("facebook", "7301", gate=world.gate) is None

    class Down:
        def open(self, key: str) -> io.BytesIO:
            raise RuntimeError("R2 is down")

    assert reel_covers.open_cover("tiktok", "7301", gate=PublicObjectGate(Down())) is None


def test_the_route_reads_r2_through_its_own_bounded_door(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route's read (an `<img>` request) connects in 2 s, reads in 5 s and is never
    retried; the run's copy keeps botocore's defaults. Each door is built once."""
    built: list[bool] = []
    world.r2.objects[reel_cover_key("tiktok", "7301")] = (b"\xff\xd8x", "image/jpeg")

    def door(*, bounded: bool) -> PublicObjectGate:
        built.append(bounded)
        return PublicObjectGate(world.r2)

    monkeypatch.setattr(reel_covers, "_r2_gate", door)
    monkeypatch.setattr(reel_covers, "_route", None)
    monkeypatch.setattr(reel_covers, "_gate", None)
    assert reel_covers.open_cover("tiktok", "7301") == b"\xff\xd8x"
    assert reel_covers.open_cover("tiktok", "7301") == b"\xff\xd8x"
    assert built == [True]
    assert reel_covers._default_gate() is not reel_covers._route_gate()
    assert built == [True, False]


@pytest.mark.parametrize("door", ["_default_gate", "_route_gate"])
def test_each_door_is_built_once_however_many_threads_ask(
    door: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """boto3's default session is not thread-safe, and the route's reads come from several
    threads at once: a burst of first requests builds ONE client, never several."""
    import threading
    import time

    built: list[bool] = []

    def slow(*, bounded: bool) -> PublicObjectGate:
        built.append(bounded)
        time.sleep(0.05)  # long enough for every thread to arrive while it is built
        return PublicObjectGate(R2())

    monkeypatch.setattr(reel_covers, "_r2_gate", slow)
    monkeypatch.setattr(reel_covers, "_gate", None)
    monkeypatch.setattr(reel_covers, "_route", None)
    got: list[PublicObjectGate] = []
    start = threading.Barrier(16)

    def ask() -> None:
        start.wait()
        got.append(getattr(reel_covers, door)())

    threads = [threading.Thread(target=ask) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert len(built) == 1 and len(got) == 16 and len({id(g) for g in got}) == 1


def test_the_bounded_door_is_built_with_the_short_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in (
        ("QUALIFY_R2_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com"),
        ("QUALIFY_R2_ACCESS_KEY_ID", "test-key-id"),
        ("QUALIFY_R2_SECRET_ACCESS_KEY", "test-secret"),
        ("QUALIFY_R2_BUCKET", "qualify-test"),
    ):
        monkeypatch.setenv(name, value)
    route = reel_covers._r2_gate(bounded=True)._store._client.meta.config  # type: ignore[attr-defined]
    assert (route.connect_timeout, route.read_timeout) == (
        reel_covers.ROUTE_CONNECT_SECONDS,
        reel_covers.ROUTE_READ_SECONDS,
    )
    assert route.retries == {"total_max_attempts": 1, "mode": "standard"}
    copy = reel_covers._r2_gate(bounded=False)._store._client.meta.config  # type: ignore[attr-defined]
    assert (copy.connect_timeout, copy.read_timeout) == (60, 60)


# --------------------------------------------------------------------------------------
# the 30-day purge
# --------------------------------------------------------------------------------------

COPIED_AT = datetime.fromtimestamp(NOW, UTC)


def _copied(world: World, *reel_ids: str) -> None:
    """Covers copied at `COPIED_AT` (the run that kept them as ideas)."""
    brand = _brand(world, TENANT_A)
    _run(world, TENANT_A, brand)
    for reel_id in reel_ids:
        key = reel_cover_key("instagram", reel_id)
        world.r2.objects[key] = (b"\xff\xd8" + reel_id.encode(), "image/jpeg")
        assert world.covers.record_cover(TENANT_A, "instagram", reel_id, key, COPIED_AT)


def test_day_twenty_nine_keeps_the_copy_day_thirty_one_deletes_it(world: World) -> None:
    _copied(world, "M00")
    key = reel_cover_key("instagram", "M00")
    day29 = rt.purge_reel_covers(
        world.gate, COPIED_AT + timedelta(days=29), True, store=world.covers
    )
    assert (day29.due, day29.purged) == (0, 0) and key in world.r2.objects

    day31 = rt.purge_reel_covers(
        world.gate, COPIED_AT + timedelta(days=31), True, store=world.covers
    )
    assert (day31.due, day31.purged, day31.objects, day31.failed) == (1, 1, 1, 0)
    assert key not in world.r2.objects
    assert world.store.reels[("instagram", "M00")].cover_r2_key is None
    assert ("instagram", "M00") not in world.covers.used

    again = rt.purge_reel_covers(
        world.gate, COPIED_AT + timedelta(days=32), True, store=world.covers
    )
    assert (again.due, again.purged) == (0, 0)


def test_the_last_use_counts_not_the_copy(world: World) -> None:
    """30 days after the LAST idea that used it: a copy used again on day 10 lives to 40."""
    _copied(world, "M00")
    assert world.covers.bump_cover(TENANT_A, "instagram", "M00", COPIED_AT + timedelta(days=10))
    report = rt.purge_reel_covers(
        world.gate, COPIED_AT + timedelta(days=31), True, store=world.covers
    )
    assert report.due == 0
    later = rt.purge_reel_covers(
        world.gate, COPIED_AT + timedelta(days=41), True, store=world.covers
    )
    assert later.purged == 1


def test_without_execute_it_reports_and_changes_nothing(world: World) -> None:
    _copied(world, "M00", "M01")
    report = rt.purge_reel_covers(
        world.gate, COPIED_AT + timedelta(days=31), False, store=world.covers
    )
    assert (report.due, report.purged, report.objects, report.execute) == (2, 0, 2, False)
    assert len(world.r2.objects) == 2 and len(world.covers.used) == 2


def test_an_r2_error_leaves_that_row_and_the_others_go_on(world: World) -> None:
    _copied(world, "M00", "M01")
    world.r2.broken.add(reel_cover_key("instagram", "M00"))
    report = rt.purge_reel_covers(
        world.gate, COPIED_AT + timedelta(days=31), True, store=world.covers
    )
    assert (report.due, report.purged, report.failed) == (2, 1, 1)
    assert world.store.reels[("instagram", "M00")].cover_r2_key is not None
    assert world.store.reels[("instagram", "M01")].cover_r2_key is None


def test_the_purge_clears_the_row_before_it_deletes_and_a_failed_delete_undoes_it(
    world: World,
) -> None:
    """Review item 7, decided: UPDATE, delete, commit — the twin clears first and puts the
    row back when R2 refuses, as the transaction's rollback does."""
    _copied(world, "M00")
    key = reel_cover_key("instagram", "M00")
    seen: list[str | None] = []

    def refused(name: str) -> None:
        seen.append(world.store.reels[("instagram", "M00")].cover_r2_key)
        raise RuntimeError("R2 answered 503")

    cutoff = COPIED_AT + timedelta(days=1)
    with pytest.raises(RuntimeError):
        world.covers.purge_cover("instagram", "M00", cutoff, refused)
    assert seen == [None]  # cleared before the delete ran
    assert world.store.reels[("instagram", "M00")].cover_r2_key == key  # and put back
    assert world.covers.used[("instagram", "M00")] == COPIED_AT


class RefusingR2(R2):
    """The production bucket if its lock rule refuses deletes as it refuses overwrites
    (the `_LockedStore` of `test_reel_retention.py`, for the covers)."""

    def __init__(self) -> None:
        super().__init__()
        self.delete_calls = 0

    def delete_keys(self, keys: Sequence[str]) -> None:
        from qualify_shared.objects.gate import DeleteRefused

        self.delete_calls += 1
        raise DeleteRefused(len(keys), ("ObjectLockedByBucketPolicy",))


def test_a_bucket_that_refuses_deletes_stops_the_cover_purge_clears_nothing_logs_once(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """As #518 does for the sources: a refusal by the bucket stops the pass at the first
    cover — every other one would be refused the same way — with one ERROR line naming the
    code; nothing is cleared, so the same copies are due tomorrow."""
    world.r2 = RefusingR2()
    world.gate = PublicObjectGate(world.r2)
    ids = [f"M0{n}" for n in range(5)]
    _copied(world, *ids)
    with caplog.at_level(logging.ERROR, logger=rt.logger.name):
        report = rt.purge_reel_covers(
            world.gate, COPIED_AT + timedelta(days=31), True, store=world.covers, batch=2
        )
    assert report.refused == ("ObjectLockedByBucketPolicy",)
    assert (report.due, report.purged, report.failed) == (1, 0, 1)
    assert world.r2.delete_calls == 1 and len(world.r2.objects) == 5
    for reel_id in ids:
        assert world.store.reels[("instagram", reel_id)].cover_r2_key is not None
        assert world.covers.used[("instagram", reel_id)] == COPIED_AT
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1 and "ObjectLockedByBucketPolicy" in errors[0].getMessage()
    later = rt.purge_reel_covers(
        world.gate, COPIED_AT + timedelta(days=31), False, store=world.covers
    )
    assert later.due == 5


def test_a_cover_delete_that_answers_ok_but_keeps_the_object_is_not_cleared(
    world: World,
) -> None:
    """If R2 answered OK but kept the object (a lock rule that does not report), the row is
    not cleared: the purge lists the key again before it commits."""

    class Sticky(R2):
        def delete_keys(self, keys: Sequence[str]) -> None:
            return None

    world.r2 = Sticky()
    world.gate = PublicObjectGate(world.r2)
    _copied(world, "M00")
    report = rt.purge_reel_covers(
        world.gate, COPIED_AT + timedelta(days=31), True, store=world.covers
    )
    assert (report.purged, report.failed, report.refused) == (0, 1, ())
    assert world.store.reels[("instagram", "M00")].cover_r2_key is not None
    assert ("instagram", "M00") in world.covers.used


def test_purge_all_reports_a_refusal_of_either_half_as_failed() -> None:
    """The worker's daily pass: a refused cover purge is a failed step (exit 1 for `just
    reel-purge`), and it does not stop the sources' half."""
    sources = rt.PurgeReport(execute=True)
    covers = rt.CoverPurgeReport(execute=True, due=1, failed=1, refused=("AccessDenied",))
    assert rt.RetentionReport(sources=sources, covers=covers).failed == 1


def test_a_copy_an_idea_used_meanwhile_is_kept(world: World) -> None:
    """Read as due, but bumped before the purge took its row: the copy stays."""
    _copied(world, "M00")
    store = world.covers
    real_purge = store.purge_cover

    def bumped_first(network: str, reel_id: str, cutoff: datetime, delete: Any) -> bool:
        store.bump_cover(TENANT_A, network, reel_id, COPIED_AT + timedelta(days=31))
        return real_purge(network, reel_id, cutoff, delete)

    store.purge_cover = bumped_first  # type: ignore[method-assign]
    report = rt.purge_reel_covers(world.gate, COPIED_AT + timedelta(days=31), True, store=store)
    assert (report.due, report.kept, report.purged) == (1, 1, 0)
    assert reel_cover_key("instagram", "M00") in world.r2.objects


def test_every_due_copy_is_reached_in_batches(world: World) -> None:
    _copied(world, *(f"M{n:02d}" for n in range(5)))
    moment = COPIED_AT + timedelta(days=31)
    dry = rt.purge_reel_covers(world.gate, moment, False, store=world.covers, batch=2)
    assert (dry.due, dry.purged) == (5, 0)  # a dry run pages too, not 2 forever
    done = rt.purge_reel_covers(world.gate, moment, True, store=world.covers, batch=2)
    assert (done.due, done.purged) == (5, 5) and world.r2.objects == {}


def test_a_reel_that_becomes_an_idea_again_after_the_purge_is_copied_again(
    world: World,
) -> None:
    brand = _brand(world, TENANT_A)
    reports: list[reel_covers.CoverReport] = []
    _run(world, TENANT_A, brand, analyze=_copying_hook(world, reports))
    rt.purge_reel_covers(world.gate, COPIED_AT + timedelta(days=31), True, store=world.covers)
    assert world.r2.objects == {}
    # the purge's moment is its own argument: the next run keeps the same reels as ideas
    # while their links still live, and finds no copy
    world.clock.moment += DAY
    again = _run(world, TENANT_A, brand, trigger="manual", analyze=_copying_hook(world, reports))
    assert again.ideas == 8 and len(reports) == 2
    assert (reports[-1].copied, reports[-1].reused) == (8, 0) and len(world.r2.objects) == 8


def test_the_daily_pass_purges_sources_and_covers_under_one_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.referentes import worker as cli

    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        rt,
        "purge_reel_sources",
        lambda gate, now, execute: calls.append(("sources", execute)) or rt.PurgeReport(execute),
    )
    monkeypatch.setattr(
        rt,
        "purge_reel_covers",
        lambda gate, now, execute: (
            calls.append(("covers", execute)) or rt.CoverPurgeReport(execute)
        ),
    )
    monkeypatch.setattr(rt, "production_gate", lambda: PublicObjectGate(R2()))
    monkeypatch.setenv(rt.EXECUTE_ENV, "1")
    report = cli._production_purge(COPIED_AT)
    assert calls == [("sources", True), ("covers", True)]
    assert isinstance(report, rt.RetentionReport) and report.failed == 0

    def broken(gate: Any, now: datetime, execute: bool) -> rt.PurgeReport:
        raise RuntimeError("password authentication failed for qualify_reels_worker")

    calls.clear()
    monkeypatch.setattr(rt, "purge_reel_sources", broken)
    monkeypatch.setenv(rt.EXECUTE_ENV, "0")
    with pytest.raises(RuntimeError):
        cli._production_purge(COPIED_AT)
    assert calls == [("covers", False)]  # one half failing never stops the other
