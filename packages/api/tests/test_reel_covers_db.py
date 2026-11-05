"""R12 over the live schema (0127; ADR 42 R12, m-24854859): the cover URL is upserted like
the video's, the run records and bumps its R2 copy through `tenant_session`
(`PostgresCoverStore`), the CHECKs pin the key to the row's own reel, the 30-day purge
reads and clears through `global_session` under a row lock, and the screen's `ideas()`
carries the three cover fields. No network: R2 is an in-memory store behind the real
`PublicObjectGate`, the CDN an `httpx.MockTransport`."""

from __future__ import annotations

import io
import os
import threading
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectNotFound, StoredObject
from qualify_shared.objects.public import PublicObjectGate, reel_cover_key
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from qualify_api.referentes import reel_retention as rt
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_covers import PostgresCoverStore, copy_idea_covers
from qualify_api.referentes.reel_store import STATUS_OK, NewIdea, PostgresReelRunStore, PublicReel
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

NOW = datetime.now(UTC).replace(microsecond=0)
CDN = "scontent-bog1-1.cdninstagram.com"


@pytest.fixture(autouse=True)
def no_copies() -> Iterator[None]:
    """No cover copy left by another test (the purge is global; the test database only —
    the guard refuses any other)."""
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE public_reels SET cover_r2_key = NULL, cover_r2_used_at = NULL "
                "WHERE cover_r2_key IS NOT NULL"
            )
        )
    yield
    engine.dispose()


class R2:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        self.objects[key] = fileobj.read()

    def open(self, key: str) -> io.BytesIO:
        if key not in self.objects:
            raise ObjectNotFound(key)
        return io.BytesIO(self.objects[key])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for key, data in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield StoredObject(key, len(data))

    def delete_keys(self, keys: Sequence[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


def _business() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="R12", country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="R12 brand"))
    return tenant, brand


def _reel_id() -> str:
    return f"R12{uuid4().hex[:12]}"


def _url(reel_id: str, *, expires: datetime | None = None) -> str:
    stamp = int((expires or NOW + timedelta(days=4)).timestamp())
    return f"https://{CDN}/v/t51.2885-15/{reel_id}.jpg?oe={stamp:X}&_nc_sid=1"


def _reel(reel_id: str, at: datetime, cover: str | None) -> PublicReel:
    return PublicReel(
        network="instagram",
        reel_id=reel_id,
        handle="heladosdonde",
        taken_at=NOW - timedelta(days=2),
        metrics_at=at,
        parser_version=2,
        cover_url=cover,
    )


def _row(reel_id: str) -> Any:
    with admin_session() as session:
        return session.execute(
            text(
                "SELECT cover_url, cover_url_at, cover_r2_key, cover_r2_used_at "
                "FROM public_reels WHERE network = 'instagram' AND reel_id = :r"
            ),
            {"r": reel_id},
        ).one()


def _stored(tenant: UUID, *reel_ids: str) -> None:
    PostgresReelRunStore().upsert_reels(tenant, [_reel(r, NOW, _url(r)) for r in reel_ids])


# --------------------------------------------------------------------------------------
# the URL, upserted like the video's
# --------------------------------------------------------------------------------------


def test_the_cover_url_follows_the_video_urls_rule() -> None:
    tenant, _ = _business()
    store, reel_id = PostgresReelRunStore(), _reel_id()
    first, second = _url(reel_id), _url(reel_id, expires=NOW + timedelta(days=5))
    store.upsert_reels(tenant, [_reel(reel_id, NOW, first)])
    assert (_row(reel_id).cover_url, _row(reel_id).cover_url_at) == (first, NOW)

    later = NOW + timedelta(hours=1)
    store.upsert_reels(tenant, [_reel(reel_id, later, None)])  # a read without a cover
    assert (_row(reel_id).cover_url, _row(reel_id).cover_url_at) == (first, NOW)

    store.upsert_reels(tenant, [_reel(reel_id, later + timedelta(hours=1), second)])
    assert _row(reel_id).cover_url == second
    store.upsert_reels(tenant, [_reel(reel_id, NOW - timedelta(days=1), first)])  # late retry
    assert _row(reel_id).cover_url == second

    read = store.reels_of(tenant, [("instagram", "heladosdonde")], since=NOW - timedelta(days=3))
    [mine] = [r for r in read if r.reel_id == reel_id]
    assert (mine.cover_url, mine.cover_r2_key) == (second, None)


# --------------------------------------------------------------------------------------
# the copy: recorded once, bumped forward, pinned by the CHECKs
# --------------------------------------------------------------------------------------


def test_one_key_per_reel_recorded_once_and_its_date_only_moves_forward() -> None:
    (tenant_a, _), (tenant_b, _) = _business(), _business()
    reel_id = _reel_id()
    _stored(tenant_a, reel_id)
    covers, key = PostgresCoverStore(), reel_cover_key("instagram", reel_id)

    assert not covers.bump_cover(tenant_a, "instagram", reel_id, NOW)  # no copy yet
    assert covers.record_cover(tenant_a, "instagram", reel_id, key, NOW)
    assert not covers.record_cover(tenant_b, "instagram", reel_id, key, NOW)  # one object
    assert covers.bump_cover(tenant_b, "instagram", reel_id, NOW + timedelta(days=2))
    assert covers.bump_cover(tenant_a, "instagram", reel_id, NOW + timedelta(days=1))
    row = _row(reel_id)
    assert (row.cover_r2_key, row.cover_r2_used_at) == (key, NOW + timedelta(days=2))


def test_the_checks_pin_the_key_to_its_own_reel_and_to_a_date() -> None:
    tenant, _ = _business()
    mine, other = _reel_id(), _reel_id()
    _stored(tenant, mine, other)
    statements = [
        # another reel's object
        (
            "UPDATE public_reels SET cover_r2_key = :other_key, cover_r2_used_at = now() "
            "WHERE network = 'instagram' AND reel_id = :mine"
        ),
        # a key without the date of its last use (never purged)
        (
            "UPDATE public_reels SET cover_r2_key = :mine_key "
            "WHERE network = 'instagram' AND reel_id = :mine"
        ),
        # a date without a key
        (
            "UPDATE public_reels SET cover_r2_used_at = now() "
            "WHERE network = 'instagram' AND reel_id = :mine"
        ),
        # an URL without when it was read
        (
            "UPDATE public_reels SET cover_url_at = NULL "
            "WHERE network = 'instagram' AND reel_id = :mine"
        ),
        # a key outside the covers' shape
        (
            "UPDATE public_reels SET cover_r2_key = 'public/reel-covers/instagram/x.png', "
            "cover_r2_used_at = now() WHERE network = 'instagram' AND reel_id = :mine"
        ),
    ]
    params = {
        "mine": mine,
        "mine_key": reel_cover_key("instagram", mine),
        "other_key": reel_cover_key("instagram", other),
    }
    for statement in statements:
        with pytest.raises(IntegrityError), tenant_session(tenant) as session:
            session.execute(text(statement), params)


def test_the_run_copies_once_and_the_screen_reads_the_three_fields() -> None:
    runs, covers, r2 = PostgresReelRunStore(), PostgresCoverStore(), R2()
    tenant, brand = _business()
    ids = [_reel_id() for _ in range(3)]
    run = rr.enqueue_run(tenant, brand, "manual", store=runs, clock=NOW.timestamp)
    assert runs.claim(tenant, run.id, now=NOW) is not None
    runs.upsert_reels(tenant, [_reel(r, NOW, _url(r)) for r in ids])
    ideas = [NewIdea("instagram", r, n, 7, None) for n, r in enumerate(ids, 1)]
    assert runs.save_ideas(tenant, brand, run.id, ideas, started_at=NOW)
    assert runs.finish(
        tenant,
        run.id,
        status=STATUS_OK,
        now=NOW,
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash=None,
        started_at=NOW,
    )
    picture = io.BytesIO()
    Image.new("RGB", (1080, 1920), (1, 2, 3)).save(picture, "JPEG")
    asked: list[str] = []

    def cdn(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(
            200, headers={"content-type": "image/jpeg"}, content=picture.getvalue()
        )

    def sources() -> list[rr.IdeaSource]:
        return [
            rr.IdeaSource(
                i.reel.network,
                i.reel.reel_id,
                f"https://www.instagram.com/reel/{i.reel.reel_id}/",
                "",
                cover_url=i.reel.cover_url or "",
                cover_r2_key=i.reel.cover_r2_key,
            )
            for i in runs.ideas(tenant, brand, run.id)
        ]

    with httpx.Client(transport=httpx.MockTransport(cdn)) as client:
        first = copy_idea_covers(
            tenant,
            run.id,
            sources(),
            gate=PublicObjectGate(r2),
            store=covers,
            client=client,
            clock=NOW.timestamp,
        )
        later = (NOW + timedelta(days=1)).timestamp
        second = copy_idea_covers(
            tenant,
            run.id,
            sources(),
            gate=PublicObjectGate(r2),
            store=covers,
            client=client,
            clock=later,
        )
    assert (first.copied, second.reused, second.copied) == (3, 3, 0)
    assert len(asked) == 3 and len(r2.objects) == 3  # the second run downloaded nothing

    shown = rr.view(tenant, brand, store=runs).ideas
    for idea in shown:
        assert idea.reel.cover_url == _url(idea.reel.reel_id)
        assert idea.reel.cover_url_at == NOW
        assert idea.reel.cover_r2_key == reel_cover_key("instagram", idea.reel.reel_id)
        assert _row(idea.reel.reel_id).cover_r2_used_at == NOW + timedelta(days=1)


# --------------------------------------------------------------------------------------
# the 30-day purge, through global_session
# --------------------------------------------------------------------------------------


def _copied(tenant: UUID, r2: R2, *reel_ids: str, at: datetime = NOW) -> None:
    _stored(tenant, *reel_ids)
    for reel_id in reel_ids:
        key = reel_cover_key("instagram", reel_id)
        r2.objects[key] = b"\xff\xd8" + reel_id.encode()
        assert PostgresCoverStore().record_cover(tenant, "instagram", reel_id, key, at)


def test_the_purge_keeps_a_copy_on_day_29_and_deletes_it_on_day_31() -> None:
    tenant, _ = _business()
    r2, reel_id = R2(), _reel_id()
    _copied(tenant, r2, reel_id)
    gate, store = PublicObjectGate(r2), PostgresCoverStore()

    day29 = rt.purge_reel_covers(gate, NOW + timedelta(days=29), True, store=store)
    assert (day29.due, day29.purged) == (0, 0) and len(r2.objects) == 1
    dry = rt.purge_reel_covers(gate, NOW + timedelta(days=31), False, store=store)
    assert (dry.due, dry.purged, dry.objects) == (1, 0, 1) and _row(reel_id).cover_r2_key

    day31 = rt.purge_reel_covers(gate, NOW + timedelta(days=31), True, store=store)
    assert (day31.due, day31.purged, day31.objects, day31.failed) == (1, 1, 1, 0)
    assert r2.objects == {}
    row = _row(reel_id)
    assert (row.cover_r2_key, row.cover_r2_used_at) == (None, None)
    assert row.cover_url == _url(reel_id)  # the URL stays: a later run may copy again


def test_the_due_copies_are_paged_oldest_first() -> None:
    tenant, _ = _business()
    r2 = R2()
    ids = [_reel_id() for _ in range(3)]
    for n, reel_id in enumerate(ids):
        _copied(tenant, r2, reel_id, at=NOW + timedelta(minutes=n))
    store = PostgresCoverStore()
    cutoff = NOW + timedelta(days=1)
    page = store.due_covers(cutoff, after=None, limit=2)
    assert [d.reel_id for d in page] == ids[:2]
    last = page[-1]
    rest = store.due_covers(cutoff, after=(last.used_at, last.network, last.reel_id), limit=2)
    assert [d.reel_id for d in rest] == ids[2:]


def test_a_failing_delete_leaves_the_row() -> None:
    tenant, _ = _business()
    r2, reel_id = R2(), _reel_id()
    _copied(tenant, r2, reel_id)

    def broken(key: str) -> None:
        raise RuntimeError("R2 refused to delete 1 object(s): InternalError")

    with pytest.raises(RuntimeError):
        PostgresCoverStore().purge_cover("instagram", reel_id, NOW + timedelta(days=31), broken)
    assert _row(reel_id).cover_r2_key == reel_cover_key("instagram", reel_id)


def test_a_bump_waits_for_the_purge_and_then_finds_no_copy() -> None:
    """The row lock: an idea using the copy while the purge deletes it waits, then sees
    no copy — so its run copies the cover again instead of trusting a deleted object."""
    tenant, _ = _business()
    r2, reel_id = R2(), _reel_id()
    _copied(tenant, r2, reel_id)
    store = PostgresCoverStore()
    deleting, release = threading.Event(), threading.Event()
    purged: list[bool] = []
    bumped: list[bool] = []

    def slow_delete(key: str) -> None:
        deleting.set()
        assert release.wait(10)

    purge = threading.Thread(
        target=lambda: purged.append(
            store.purge_cover("instagram", reel_id, NOW + timedelta(days=31), slow_delete)
        )
    )
    purge.start()
    assert deleting.wait(10)
    bump = threading.Thread(
        target=lambda: bumped.append(
            store.bump_cover(tenant, "instagram", reel_id, NOW + timedelta(days=31))
        )
    )
    bump.start()
    bump.join(0.5)
    assert bump.is_alive()  # held by the purge's row lock
    release.set()
    purge.join(10)
    bump.join(10)
    assert purged == [True] and bumped == [False]
    assert _row(reel_id).cover_r2_key is None
