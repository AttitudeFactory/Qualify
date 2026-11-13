"""`db` tests for the «Publicar» backfill and the permalink filler (m-25019220, migration
0160): the settled-row trigger's one new exception, the backfill end to end (clear match,
burst, doubtful → Instagram copy, unreadable, dry run, twice, tenant isolation) and the
tick's permalink step. R2 is an in-memory store, Graph a fake reader, the picture
download a fake fetcher — never the real ones.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate, StoredObject
from qualify_shared.objects.memory import MemoryObjectStore
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.creative import models as creative
from qualify_api.inbox.media_client import MediaReadError, MediaSummary
from qualify_api.inbox.thumbnails import ThumbnailUnavailable
from qualify_api.planner.discovery import DiscoveredTenants
from qualify_api.planner.models import CalendarEvent
from qualify_api.planner.permalinks import Outcome as LinkOutcome
from qualify_api.planner.permalinks import fill_recent_permalinks
from qualify_api.planner.publish_backfill import PIPELINE_VERSION, Deps, probe, run_backfill
from qualify_api.publishing.models import PublishAttempt, PublishAttemptChild
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db

JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 2000
MP4 = b"\0\0\0\x18ftypisom" + b"\0" * 2000
BASE = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)


# -- fakes ----------------------------------------------------------------------------------


class TimedStore(MemoryObjectStore):
    """The in-memory bucket (write-once under `t/`), with chosen `last_modified` dates
    and a record of every listed prefix."""

    def __init__(self) -> None:
        super().__init__(locked=True)
        self.dates: dict[str, datetime] = {}
        self.listed: list[str] = []

    def seed(self, key: str, body: bytes, at: datetime) -> None:
        self.objects[key] = body
        self.content_types[key] = "application/octet-stream"
        self.dates[key] = at

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        self.listed.append(prefix)
        for key in sorted(self.objects):
            if key.startswith(prefix):
                yield StoredObject(key, len(self.objects[key]), self.dates.get(key, BASE))


@dataclass
class FakeReader:
    answers: dict[str, MediaSummary | Exception] = field(default_factory=dict)
    reads: list[str] = field(default_factory=list)

    async def get_media(self, *, media_id: str) -> MediaSummary:
        self.reads.append(media_id)
        answer = self.answers.get(media_id, MediaReadError("gone", http_status=400))
        if isinstance(answer, Exception):
            raise answer
        return answer


@dataclass
class FakeBudget:
    left: int = 200
    spent: int = 0

    def remaining(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> int:
        return self.left - self.spent

    def spend(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> None:
        self.spent += 1


@dataclass
class FakeFetcher:
    body: bytes = JPEG
    fail: bool = False
    fetched: list[str] = field(default_factory=list)

    async def fetch(self, url: str) -> tuple[bytes, str]:
        self.fetched.append(url)
        if self.fail:
            raise ThumbnailUnavailable("down")
        return self.body, "image/jpeg"


@dataclass
class Harness:
    store: TimedStore
    reader: FakeReader
    budget: FakeBudget
    fetcher: FakeFetcher
    asked: list[UUID]

    def deps(self) -> Deps:
        async def readers(tenant_id: UUID, connection_id: UUID) -> FakeReader:
            self.asked.append(connection_id)
            return self.reader

        return Deps(
            gate=ObjectGate(self.store),
            fetcher=self.fetcher,
            readers=readers,
            budget=self.budget,
            clock=lambda: BASE + timedelta(days=1),
        )


@pytest.fixture
def harness() -> Harness:
    return Harness(TimedStore(), FakeReader(), FakeBudget(), FakeFetcher(), [])


# -- the world ------------------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    tenant_id: UUID
    brand_id: UUID
    user_id: UUID
    connection_id: UUID

    @property
    def folder(self) -> str:
        return f"t/{self.tenant_id}/media/{self.connection_id}/"


def _world() -> World:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"backfill-{tenant_id}",
                country="VE",
                timezone="America/Caracas",
                currency="USD",
            )
        )
        session.flush()
        brand = Brand(tenant_id=tenant_id, name="Bianki")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"o-{uuid4()}@p.co", display_name="Owner")
        session.add_all([brand, app, user])
        session.flush()
        session.add(TenantMember(tenant_id=tenant_id, user_id=user.id, role="owner"))
        session.flush()
        brand_id, app_id, user_id = brand.id, app.id, user.id
    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            brand_id=brand_id,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        connection_id = conn.id
    return World(tenant_id, brand_id, user_id, connection_id)


def _attempt(
    world: World,
    started_at: datetime,
    *,
    product: str = "IMAGE",
    media_id: str | None = None,
    settled: bool = True,
    status: str = "published",
    raw_key: str | None = None,
    connection_id: UUID | None = None,
    children: tuple[str, ...] = (),
) -> UUID:
    with tenant_session(world.tenant_id) as session:
        row = PublishAttempt(
            tenant_id=world.tenant_id,
            connection_id=connection_id or world.connection_id,
            idempotency_key=f"web:{uuid4()}",
            caption="Shawarma 2x1",
            media_product_type=product,
            adapter_version="test",
            status=status,
            started_at=started_at,
            settled_at=started_at + timedelta(seconds=20) if settled else None,
            published_media_id=media_id or str(uuid4().int)[:17],
            raw_response_r2_key=raw_key,
        )
        session.add(row)
        session.flush()
        for position, key in enumerate(children):
            session.add(
                PublishAttemptChild(
                    tenant_id=world.tenant_id,
                    attempt_id=row.id,
                    position=position,
                    media_object_key=key,
                    media_content_type="image/jpeg",
                    media_product_type="IMAGE",
                    status="finished",
                )
            )
        session.flush()
        return row.id


def _second_connection(world: World) -> UUID:
    with tenant_session(world.tenant_id) as session:
        first = session.get(SocialConnection, world.connection_id)
        assert first is not None
        conn = SocialConnection(
            tenant_id=world.tenant_id,
            brand_id=world.brand_id,
            platform_app_id=first.platform_app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-2",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=world.user_id,
        )
        session.add(conn)
        session.flush()
        return conn.id


def _media_id(world: World, attempt_id: UUID) -> str:
    with tenant_session(world.tenant_id) as session:
        row = session.get(PublishAttempt, attempt_id)
        assert row is not None and row.published_media_id is not None
        return row.published_media_id


def _ig(media_id: str, *, kind: str = "IMAGE", url: bool = True) -> MediaSummary:
    return MediaSummary(
        id=media_id,
        timestamp=BASE,
        media_type=kind,
        permalink=f"https://www.instagram.com/p/{media_id}/",
        media_url="https://scontent.cdninstagram.com/x.jpg" if url else None,
    )


def _pieces(world: World) -> list[tuple[str, str, str, dict]]:
    """(reuse_type, pipeline_version, asset key, asset params) of every piece."""
    with tenant_session(world.tenant_id) as session:
        rows = session.execute(
            select(
                creative.ContentDraft.reuse_type,
                creative.ContentDraft.pipeline_version,
                creative.ImageAsset.object_key,
                creative.ImageAsset.params,
            ).join(creative.ImageAsset, creative.ImageAsset.draft_id == creative.ContentDraft.id)
        ).all()
    return [tuple(row) for row in rows]  # type: ignore[misc]


def _counts(world: World) -> tuple[int, int]:
    with tenant_session(world.tenant_id) as session:
        drafts = session.scalar(select(func.count()).select_from(creative.ContentDraft))
        events = session.scalar(select(func.count()).select_from(CalendarEvent))
    return int(drafts or 0), int(events or 0)


def _row(world: World, attempt_id: UUID) -> PublishAttempt:
    with tenant_session(world.tenant_id) as session:
        row = session.get(PublishAttempt, attempt_id)
        assert row is not None
        session.expunge(row)
        return row


# -- 0160: the settled-row trigger ----------------------------------------------------------


def _update(world: World, attempt_id: UUID, sql: str, **params: object) -> None:
    with tenant_session(world.tenant_id) as session:
        session.execute(text(sql), {"id": attempt_id, **params})


def test_a_settled_attempt_accepts_its_permalink_once_and_nothing_else() -> None:
    world = _world()
    attempt = _attempt(world, BASE)
    link = "https://www.instagram.com/p/A/"
    _update(world, attempt, "UPDATE publish_attempts SET permalink = :p WHERE id = :id", p=link)
    assert _row(world, attempt).permalink == link
    for sql, params in (
        ("UPDATE publish_attempts SET permalink = :p WHERE id = :id", {"p": "https://x/"}),
        ("UPDATE publish_attempts SET permalink = NULL WHERE id = :id", {}),
        ("UPDATE publish_attempts SET media_object_key = 'k' WHERE id = :id", {}),
        ("UPDATE publish_attempts SET status = 'failed' WHERE id = :id", {}),
    ):
        with pytest.raises(DBAPIError, match="already settled"):
            _update(world, attempt, sql, **params)
    other = _attempt(world, BASE + timedelta(minutes=5))
    with pytest.raises(DBAPIError, match="already settled"):  # permalink AND another column
        _update(
            world,
            other,
            "UPDATE publish_attempts SET permalink = 'https://x/', caption = 'c' WHERE id = :id",
        )


def test_an_unsettled_attempt_updates_as_before() -> None:
    world = _world()
    attempt = _attempt(world, BASE, settled=False, status="pending")
    _update(world, attempt, "UPDATE publish_attempts SET caption = 'otra' WHERE id = :id")
    _update(
        world,
        attempt,
        "UPDATE publish_attempts SET status = 'published', settled_at = now() WHERE id = :id",
    )
    assert _row(world, attempt).caption == "otra"


def test_the_purge_roles_exception_still_works() -> None:
    world = _world()
    attempt = _attempt(world, BASE, raw_key=f"t/{uuid4()}/fp/raw")
    with connection_purge_session(world.tenant_id) as session:
        session.execute(
            text(
                "UPDATE publish_attempts SET raw_response_r2_key = NULL "
                "WHERE tenant_id = :tid AND connection_id = :cid"
            ),
            {"tid": world.tenant_id, "cid": world.connection_id},
        )
    assert _row(world, attempt).raw_response_r2_key is None


# -- the backfill ---------------------------------------------------------------------------


async def test_a_clear_match_records_a_reusable_piece_at_original_quality(
    harness: Harness,
) -> None:
    world = _world()
    attempt = _attempt(world, BASE)
    staged = world.folder + uuid4().hex
    harness.store.seed(staged, JPEG, BASE - timedelta(seconds=2))
    harness.store.seed(world.folder + "dm-" + uuid4().hex, JPEG, BASE - timedelta(seconds=1))
    media_id = _media_id(world, attempt)
    harness.reader.answers[media_id] = _ig(media_id)

    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    assert [line.action.value for line in report.lines] == ["original"]
    [(reuse, pipeline, key, params)] = _pieces(world)
    assert (reuse, pipeline, key) == ("recurrente", PIPELINE_VERSION, staged)
    assert params["match"] == "original" and params["source_attempt_id"] == str(attempt)
    row = _row(world, attempt)
    assert row.media_object_key is None  # the settled attempt is never written…
    assert row.permalink == f"https://www.instagram.com/p/{media_id}/"  # …but its address
    with tenant_session(world.tenant_id) as session:
        event = session.scalar(select(CalendarEvent))
    assert event is not None and event.status == "published"
    assert event.scheduled_at == row.settled_at and event.publish_attempt_id == attempt
    assert harness.store.puts == [] and harness.fetcher.fetched == []


async def test_a_burst_of_nine_gives_each_attempt_its_own_file(harness: Harness) -> None:
    world = _world()
    attempts, files = [], []
    for i in range(9):
        start = BASE + timedelta(seconds=40 * i)
        attempts.append(_attempt(world, start))
        files.append(world.folder + uuid4().hex)
        harness.store.seed(files[-1], JPEG, start - timedelta(seconds=1 + i % 3))

    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    assert [line.action.value for line in report.lines] == ["original"] * 9
    with tenant_session(world.tenant_id) as session:
        pairs = dict(
            session.execute(
                select(CalendarEvent.publish_attempt_id, creative.ImageAsset.object_key).join(
                    creative.ImageAsset, creative.ImageAsset.draft_id == CalendarEvent.post_id
                )
            ).all()
        )
    assert [pairs[a] for a in attempts] == files


async def test_a_doubtful_match_uses_instagrams_copy_view_only(harness: Harness) -> None:
    world = _world()
    attempt = _attempt(world, BASE)
    for seconds in (2, 9):  # two candidates: never guessed
        harness.store.seed(world.folder + uuid4().hex, JPEG, BASE - timedelta(seconds=seconds))
    media_id = _media_id(world, attempt)
    harness.reader.answers[media_id] = _ig(media_id)

    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    assert [line.action.value for line in report.lines] == ["instagram_copy"]
    copy_key = f"{world.folder}ig-{media_id}"
    [(reuse, pipeline, key, params)] = _pieces(world)
    assert (reuse, pipeline, key) == ("promocional", PIPELINE_VERSION, copy_key)
    assert params["match"] == "instagram_copy" and params["instagram_media_id"] == media_id
    assert harness.store.puts == [copy_key] and harness.store.objects[copy_key] == JPEG
    assert _row(world, attempt).media_object_key is None


async def test_no_candidate_at_all_also_uses_instagrams_copy(harness: Harness) -> None:
    world = _world()
    attempt = _attempt(world, BASE)
    media_id = _media_id(world, attempt)
    harness.reader.answers[media_id] = _ig(media_id)
    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)
    assert [line.action.value for line in report.lines] == ["instagram_copy"]
    assert _counts(world) == (1, 1)


async def test_doubtful_and_unreadable_is_skipped_with_nothing_written(harness: Harness) -> None:
    world = _world()
    attempt = _attempt(world, BASE)  # the fake reader answers «gone» for unknown ids

    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    [line] = report.lines
    assert line.action.value == "skip" and "not readable" in line.detail
    assert _counts(world) == (0, 0)
    assert harness.store.puts == [] and _row(world, attempt).permalink is None


async def test_a_video_without_a_clear_file_is_skipped_without_reading_graph(
    harness: Harness,
) -> None:
    world = _world()
    _attempt(world, BASE, product="REELS")
    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)
    [line] = report.lines
    assert line.action.value == "skip" and "video" in line.detail
    assert harness.reader.reads == [] and _counts(world) == (0, 0)


async def test_a_clear_video_match_is_recorded_as_a_reel(harness: Harness) -> None:
    world = _world()
    _attempt(world, BASE, product="REELS")
    staged = world.folder + uuid4().hex
    harness.store.seed(staged, MP4, BASE - timedelta(seconds=3))
    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)
    assert [line.action.value for line in report.lines] == ["original"]
    [(_, _, key, _)] = _pieces(world)
    assert key == staged


async def test_a_dry_run_writes_nothing_and_says_the_same_twice(harness: Harness) -> None:
    world = _world()
    _attempt(world, BASE)
    _attempt(world, BASE + timedelta(minutes=5))
    harness.store.seed(world.folder + uuid4().hex, JPEG, BASE - timedelta(seconds=2))

    first = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps())
    second = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps())

    assert first.render() == second.render()
    assert first.render().startswith("DRY RUN")
    assert [line.action.value for line in first.lines] == ["original", "instagram_copy"]
    assert _counts(world) == (0, 0)
    assert harness.store.puts == [] and harness.fetcher.fetched == []
    assert harness.asked == [] and harness.reader.reads == [] and harness.budget.spent == 0
    with tenant_session(world.tenant_id) as session:
        assert (
            session.scalar(select(func.count()).where(PublishAttempt.permalink.is_not(None))) == 0
        )


async def test_executing_twice_creates_nothing_more(harness: Harness) -> None:
    world = _world()
    clear = _attempt(world, BASE)
    harness.store.seed(world.folder + uuid4().hex, JPEG, BASE - timedelta(seconds=2))
    doubtful = _attempt(world, BASE + timedelta(minutes=5))
    for attempt in (clear, doubtful):
        media_id = _media_id(world, attempt)
        harness.reader.answers[media_id] = _ig(media_id)

    await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)
    reads, puts = len(harness.reader.reads), list(harness.store.puts)
    again = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    assert again.lines == []
    assert _counts(world) == (2, 2)
    assert len(harness.reader.reads) == reads and harness.store.puts == puts


async def test_an_earlier_instagram_copy_is_reused_never_overwritten(harness: Harness) -> None:
    world = _world()
    attempt = _attempt(world, BASE)
    media_id = _media_id(world, attempt)
    harness.reader.answers[media_id] = _ig(media_id)
    harness.store.seed(f"{world.folder}ig-{media_id}", JPEG, BASE)  # a run died after the PUT
    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)
    assert [line.action.value for line in report.lines] == ["instagram_copy"]
    assert harness.store.puts == [] and harness.fetcher.fetched == []


async def test_a_spent_budget_stops_cleanly_and_the_next_run_continues(harness: Harness) -> None:
    world = _world()
    attempts = [_attempt(world, BASE + timedelta(minutes=5 * i)) for i in range(3)]
    for attempt in attempts:
        media_id = _media_id(world, attempt)
        harness.reader.answers[media_id] = _ig(media_id)
    harness.budget.left = 1

    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)
    assert len(report.lines) == 1 and "2 publication(s) left" in report.stopped
    harness.budget.left = 100
    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)
    assert len(report.lines) == 2 and _counts(world) == (3, 3)


async def test_tenant_b_is_never_listed_read_or_touched(harness: Harness) -> None:
    a, b = _world(), _world()
    _attempt(a, BASE)
    b_attempt = _attempt(b, BASE)
    harness.store.seed(b.folder + uuid4().hex, JPEG, BASE - timedelta(seconds=2))

    report = await run_backfill(tenant_id=a.tenant_id, deps=harness.deps(), execute=True)
    aimed_at_b = await run_backfill(  # RLS: A's session cannot see B's connection
        tenant_id=a.tenant_id, deps=harness.deps(), connection_id=b.connection_id, execute=True
    )

    assert aimed_at_b.lines == []

    assert all(line.attempt_id != b_attempt for line in report.lines)
    assert harness.store.listed == [a.folder]
    assert b.connection_id not in harness.asked
    assert _counts(b) == (0, 0) and _row(b, b_attempt).permalink is None


async def test_the_probe_reads_one_media_and_prints_no_signed_address(harness: Harness) -> None:
    world = _world()
    attempt = _attempt(world, BASE)
    media_id = _media_id(world, attempt)
    harness.reader.answers[media_id] = _ig(media_id)
    out = await probe(tenant_id=world.tenant_id, deps=harness.deps())
    lines = [line.strip() for line in out.splitlines()]
    assert "result=readable" in lines[0]
    printed = next(line for line in lines if line.startswith("permalink="))
    assert urlsplit(printed.removeprefix("permalink=")).hostname == "www.instagram.com"
    # only the parsed host of the signed CDN address is printed, never the address
    assert "media_url=present (scontent.cdninstagram.com, allowed)" in lines
    assert not any("x.jpg" in line for line in lines)
    assert harness.reader.reads == [media_id] and _counts(world) == (0, 0)


# -- the tick's permalink step --------------------------------------------------------------


async def test_the_tick_fills_a_new_publications_permalink_once(harness: Harness) -> None:
    world = _world()
    now = datetime.now(UTC)
    attempt = _attempt(world, now - timedelta(minutes=2))
    media_id = _media_id(world, attempt)
    harness.reader.answers[media_id] = _ig(media_id)
    deps = harness.deps()
    assert world.tenant_id in DiscoveredTenants(permalinks=True).tenants(now=now)

    first = await fill_recent_permalinks(
        tenant_id=world.tenant_id, now=now, readers=deps.readers, budget=harness.budget
    )
    second = await fill_recent_permalinks(
        tenant_id=world.tenant_id, now=now, readers=deps.readers, budget=harness.budget
    )

    assert [r.outcome for r in first] == [LinkOutcome.FILLED] and second == []
    assert _row(world, attempt).permalink == f"https://www.instagram.com/p/{media_id}/"
    assert harness.reader.reads == [media_id]
    assert world.tenant_id not in DiscoveredTenants(permalinks=True).tenants(now=now)


async def test_an_unreadable_media_is_only_retried_inside_the_bands(harness: Harness) -> None:
    world = _world()
    settled = datetime.now(UTC) - timedelta(hours=3)
    _attempt(world, settled - timedelta(seconds=20))  # the fake answers «gone»
    deps = harness.deps()
    for offset in (
        timedelta(minutes=1),
        timedelta(minutes=30),
        timedelta(hours=1, minutes=1),
        timedelta(hours=3),
        timedelta(hours=24, minutes=1),
        timedelta(hours=30),
    ):
        await fill_recent_permalinks(
            tenant_id=world.tenant_id,
            now=settled + offset,
            readers=deps.readers,
            budget=harness.budget,
        )
    assert len(harness.reader.reads) == 3  # 1 min, 1 h 1 min, 24 h 1 min


async def test_the_tick_ignores_a_non_instagram_answer(harness: Harness) -> None:
    world = _world()
    now = datetime.now(UTC)
    attempt = _attempt(world, now - timedelta(minutes=2))
    media_id = _media_id(world, attempt)
    harness.reader.answers[media_id] = MediaSummary(
        id=media_id, timestamp=now, permalink="https://evil.example/p/"
    )
    deps = harness.deps()
    results = await fill_recent_permalinks(
        tenant_id=world.tenant_id, now=now, readers=deps.readers, budget=harness.budget
    )
    assert [r.outcome for r in results] == [LinkOutcome.IGNORED]
    assert _row(world, attempt).permalink is None


def test_the_fake_bucket_is_write_once_under_t_like_production() -> None:
    store = TimedStore()
    store.put("t/x/a", io.BytesIO(b"1"), "image/jpeg")
    with pytest.raises(RuntimeError):
        store.put("t/x/a", io.BytesIO(b"2"), "image/jpeg")


# -- bursts («Una por una») -----------------------------------------------------------------

NINE_GAPS = (0, 6, 12, 8, 10, 7, 11, 9, 12)


def _starts(gaps: tuple[int, ...], origin: datetime = BASE) -> list[datetime]:
    out, at = [], origin
    for gap in gaps:
        at = at + timedelta(seconds=gap)
        out.append(at)
    return out


def _assets_by_attempt(world: World) -> dict[UUID, tuple[str, dict]]:
    with tenant_session(world.tenant_id) as session:
        rows = session.execute(
            select(
                CalendarEvent.publish_attempt_id,
                creative.ImageAsset.object_key,
                creative.ImageAsset.params,
            ).join(creative.ImageAsset, creative.ImageAsset.draft_id == CalendarEvent.post_id)
        ).all()
    return {row[0]: (row[1], row[2]) for row in rows}


def _answer_all(harness: Harness, world: World, attempts: list[UUID]) -> None:
    for attempt in attempts:
        media_id = _media_id(world, attempt)
        harness.reader.answers[media_id] = _ig(media_id)


@pytest.mark.parametrize("offset", [0, 4, -4])
async def test_nine_images_one_by_one_get_their_originals_in_order(
    harness: Harness, offset: int
) -> None:
    world = _world()
    attempts, files = [], []
    for start in _starts(NINE_GAPS):
        attempts.append(_attempt(world, start))
        files.append(world.folder + uuid4().hex)
        harness.store.seed(files[-1], JPEG, start - timedelta(seconds=1.5 - offset))

    dry = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps())
    assert [line.detail.split(":")[0] for line in dry.lines] == [
        f"burst {k}/9" for k in range(1, 10)
    ]
    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    assert [line.action.value for line in report.lines] == ["original"] * 9
    assets = _assets_by_attempt(world)
    assert [assets[a][0] for a in attempts] == files
    assert [assets[a][1]["match_rule"] for a in attempts] == [f"burst {k}/9" for k in range(1, 10)]
    assert {reuse for reuse, *_ in _pieces(world)} == {"recurrente"}


async def test_a_failed_attempt_in_a_burst_keeps_its_file_from_everyone(
    harness: Harness,
) -> None:
    world = _world()
    starts = _starts((0, 8, 9, 10, 7))
    attempts, files = [], []
    for index, start in enumerate(starts):
        status = "failed" if index == 2 else "published"
        attempts.append(_attempt(world, start, status=status))
        files.append(world.folder + uuid4().hex)
        harness.store.seed(files[-1], JPEG, start - timedelta(seconds=2))

    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    assert len(report.lines) == 4 and all(line.action.value == "original" for line in report.lines)
    assets = _assets_by_attempt(world)
    assert attempts[2] not in assets
    assert files[2] not in {key for key, _ in assets.values()}
    assert [assets[a][0] for i, a in enumerate(attempts) if i != 2] == [
        f for i, f in enumerate(files) if i != 2
    ]


async def test_a_replayed_extra_file_leaves_the_whole_burst_doubtful(harness: Harness) -> None:
    world = _world()
    starts = _starts((0, 8, 9))
    attempts = [_attempt(world, start) for start in starts]
    for start in starts:
        harness.store.seed(world.folder + uuid4().hex, JPEG, start - timedelta(seconds=2))
    harness.store.seed(world.folder + uuid4().hex, JPEG, starts[1] - timedelta(seconds=4))
    _answer_all(harness, world, attempts)

    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    assert [line.action.value for line in report.lines] == ["instagram_copy"] * 3
    assert all("3 attempts to pair but 4" in line.detail for line in report.lines)
    assert {reuse for reuse, *_ in _pieces(world)} == {"promocional"}


async def test_a_carousel_inside_a_burst_is_recorded_from_its_children(
    harness: Harness,
) -> None:
    world = _world()
    starts = _starts((0, 9, 10, 8))
    children = tuple(world.folder + uuid4().hex for _ in range(3))
    for key in children:
        harness.store.seed(key, JPEG, starts[1] - timedelta(seconds=3))
    attempts, files = [], {}
    for index, start in enumerate(starts):
        if index == 1:
            attempts.append(_attempt(world, start, product="CAROUSEL", children=children))
            continue
        attempts.append(_attempt(world, start))
        files[attempts[-1]] = world.folder + uuid4().hex
        harness.store.seed(files[attempts[-1]], JPEG, start - timedelta(seconds=1))

    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    actions = {line.attempt_id: line.action.value for line in report.lines}
    assert actions[attempts[1]] == "carousel_children"
    assert [actions[a] for a in files] == ["original"] * 3
    assets = _assets_by_attempt(world)
    assert {a: assets[a][0] for a in files} == files
    assert [assets[a][1]["match_rule"] for a in files] == ["burst 1/3", "burst 2/3", "burst 3/3"]


async def test_bursts_on_two_connections_never_mix(harness: Harness) -> None:
    world = _world()
    other = _second_connection(world)
    other_folder = f"t/{world.tenant_id}/media/{other}/"
    owners: dict[UUID, str] = {}
    for start in _starts((0, 8, 9)):
        for conn, folder, shift in ((None, world.folder, 0), (other, other_folder, 2)):
            at = start + timedelta(seconds=shift)
            attempt = _attempt(world, at, connection_id=conn)
            owners[attempt] = folder + uuid4().hex
            harness.store.seed(owners[attempt], JPEG, at - timedelta(seconds=1))

    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    assert [line.action.value for line in report.lines] == ["original"] * 6
    assets = _assets_by_attempt(world)
    assert {a: assets[a][0] for a in owners} == owners


async def test_a_burst_interrupted_by_the_budget_continues_with_the_same_files(
    harness: Harness,
) -> None:
    world = _world()
    attempts, files = [], []
    for start in _starts((0, 7, 9, 8)):
        attempts.append(_attempt(world, start))
        files.append(world.folder + uuid4().hex)
        harness.store.seed(files[-1], JPEG, start - timedelta(seconds=2))
    _answer_all(harness, world, attempts)
    harness.budget.left = 2

    first = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)
    assert len(first.lines) == 2 and first.stopped
    harness.budget.left = 100
    second = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    assert [line.action.value for line in second.lines] == ["original"] * 2
    assets = _assets_by_attempt(world)
    assert [assets[a][0] for a in attempts] == files


async def test_an_image_and_a_reel_in_one_burst_pair_when_their_bytes_fit(
    harness: Harness,
) -> None:
    world = _world()
    starts = _starts((0, 10))
    image = _attempt(world, starts[0])
    reel = _attempt(world, starts[1], product="REELS")
    image_file, reel_file = world.folder + uuid4().hex, world.folder + uuid4().hex
    harness.store.seed(image_file, JPEG, starts[0] - timedelta(seconds=1))
    harness.store.seed(reel_file, MP4, starts[1] - timedelta(seconds=3))

    report = await run_backfill(tenant_id=world.tenant_id, deps=harness.deps(), execute=True)

    assert [line.action.value for line in report.lines] == ["original", "original"]
    assets = _assets_by_attempt(world)
    assert (assets[image][0], assets[reel][0]) == (image_file, reel_file)
