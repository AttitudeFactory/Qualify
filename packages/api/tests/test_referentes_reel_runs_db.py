"""The persistent reels run over the live schema of 0117 (ADR 42 R4, m-24854848):
`PostgresReelRunStore` through `tenant_session`, with the vendor and Claude scripted
(nothing paid, nothing on the network).

Pins acceptance criterion 5 — tenant isolation of the runs, verdicts and ideas the run
writes — plus, against real SQL: one read for two businesses (the global rows are shared,
the per-tenant ones are not), provenance on every stored verdict, the idempotent enqueue,
the refresh lock, the monotonic upsert and the transcript that is never overwritten."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.claude_tools import CallStats
from qualify_api.referentes import MemoryReferentesRepository, brand_brief, reels_ai
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_store import STATUS_CHECK_FAILED, STATUS_OK, PostgresReelRunStore
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

BRIEF = review_ai.BrandBrief(handle="burgerco", rubro=("hamburguesería",))


def _world() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="R4", country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="R4 brand"))
    return tenant, brand


class Vendor:
    """Two reels per account, ids unique to this test run (the global tables outlive it)."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.lists: list[str] = []
        self.transcripts: list[str] = []

    def fetch(self, network: str, handle: str, *, since: float, client: Any, max_pages: int):
        self.lists.append(handle)
        now = datetime.now(UTC).timestamp()
        return [
            {
                "id": f"{self.token}{handle[-3:]}{n}",
                "network": network,
                "handle": handle,
                "url": "",
                "caption": caption,
                "takenAt": now - (n + 1) * 86400,
                "views": 1000 * (3 - n),
                "likes": 10,
                "comments": 1,
                "shares": None,
                "saves": None,
                "seconds": 9,
                "sound": "Audio original",
                "video": f"https://scontent.cdninstagram.com/{n}.mp4",
            }
            for n, caption in enumerate(("smash burger", "mi rutina de maquillaje"))
        ]

    def transcribe(self, reel: dict[str, Any], client: Any) -> str:
        self.transcripts.append(reel["id"])
        return f"dicen {reel['caption']}"


def _review(brief: Any, batch: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
    return (
        [
            ReelReview(
                id=r.id,
                fits="maquillaje" not in r.caption,
                reason="ok",
                affinity="producto" if "maquillaje" not in r.caption else "otro",
            )
            for r in batch
        ],
        CallStats(reels_ai.REVIEW_MODEL, None, 500, 50),
    )


def _down(*_: Any, **__: Any) -> Any:
    raise RuntimeError("anthropic down")


@pytest.fixture
def setup() -> Iterator[dict[str, Any]]:
    token = uuid4().hex[:8]
    handle = f"r4{token}"  # one public account both businesses follow
    repo = MemoryReferentesRepository()
    (ta, ba), (tb, bb) = _world(), _world()
    for tenant, brand in ((ta, ba), (tb, bb)):
        repo.add_brand(tenant_id=tenant, brand_id=brand)
        repo.set_label(
            tenant_id=tenant,
            brand_id=brand,
            network="instagram",
            handle=handle,
            label="referente",
            labeled_by=None,
        )
    yield {
        "repo": repo,
        "vendor": Vendor(token),
        "store": PostgresReelRunStore(),
        "a": (ta, ba),
        "b": (tb, bb),
        "handle": handle,
    }


def _run(env: dict[str, Any], who: str, trigger: str = "weekly", **kwargs: Any) -> rr.RunOutcome:
    tenant, brand = env[who]
    queued = rr.enqueue_run(
        tenant, brand, trigger, store=env["store"], retry=kwargs.pop("retry", False)
    )
    return rr.run(
        tenant,
        queued.id,
        store=env["store"],
        repository=env["repo"],
        brief=lambda t, b: BRIEF,
        api_key="k",
        fetch=env["vendor"].fetch,
        transcribe_fetch=env["vendor"].transcribe,
        review=kwargs.pop("review", _review),
        sleep=lambda s: None,
        **kwargs,
    )


def _count(tenant: UUID, table: str, brand: UUID) -> int:
    with tenant_session(tenant) as session:
        return session.scalar(
            text(f"SELECT count(*) FROM {table} WHERE brand_id = :b"), {"b": brand}
        )


def test_runs_verdicts_and_ideas_are_isolated_per_tenant(setup: dict[str, Any]) -> None:
    env = setup
    (ta, ba), (tb, _) = env["a"], env["b"]
    first = _run(env, "a")
    assert first.status == STATUS_OK and first.ideas == 1
    for table in ("brand_reel_runs", "brand_reel_verdicts", "brand_reel_ideas"):
        assert _count(ta, table, ba) >= 1
        assert _count(tb, table, ba) == 0  # B cannot see A's rows, even naming A's brand
    assert env["store"].get_run(tb, first.run_id) is None
    assert rr.view(tb, ba, store=env["store"]).shown is None
    seen = rr.view(ta, ba, store=env["store"])
    assert seen.shown is not None and seen.shown.id == first.run_id
    assert [i.reel.caption for i in seen.ideas] == ["smash burger"]
    # B cannot finish, cost or claim A's run either: RLS hides the row from its writes
    started_at = env["store"].get_run(ta, first.run_id).started_at
    assert (
        env["store"].finish(
            tb,
            first.run_id,
            status="error",
            now=datetime.now(UTC),
            credits=9,
            cost_usd=Decimal(1),
            brief_hash=None,
            started_at=started_at,
        )
        is False
    )
    assert env["store"].get_run(ta, first.run_id).status == STATUS_OK


def test_two_businesses_make_one_read_and_every_verdict_has_provenance(
    setup: dict[str, Any],
) -> None:
    env = setup
    (ta, ba), (tb, bb) = env["a"], env["b"]
    assert _run(env, "a").status == STATUS_OK
    assert _run(env, "b").status == STATUS_OK
    assert env["vendor"].lists == [env["handle"]]  # one read for both businesses
    assert len(env["vendor"].transcripts) == 2  # each reel transcribed once
    for tenant, brand in ((ta, ba), (tb, bb)):
        with tenant_session(tenant) as session:
            rows = session.execute(
                text(
                    "SELECT model_id, prompt_version, effort, cost_usd FROM "
                    "brand_reel_verdicts WHERE brand_id = :b"
                ),
                {"b": brand},
            ).all()
        assert len(rows) == 2
        for model_id, prompt_version, effort, cost in rows:
            assert model_id == reels_ai.REVIEW_MODEL
            assert prompt_version == reels_ai.REVIEW_PROMPT_VERSION
            assert effort == reels_ai.REVIEW_EFFORT and cost > 0
    with tenant_session(ta) as session:
        account = session.execute(
            text(
                "SELECT page1_at, full_walk_at, covered_days, refresh_lock_until "
                "FROM reel_accounts WHERE network = 'instagram' AND handle = :h"
            ),
            {"h": env["handle"]},
        ).one()
    assert account.full_walk_at is not None and account.covered_days == 30
    assert account.refresh_lock_until is None


def test_claude_down_keeps_what_was_paid_and_the_retry_pays_nothing(
    setup: dict[str, Any],
) -> None:
    env = setup
    (ta, ba) = env["a"]
    failed = _run(env, "a", review=_down)
    assert failed.status == STATUS_CHECK_FAILED
    lists, transcripts = list(env["vendor"].lists), list(env["vendor"].transcripts)
    assert _count(ta, "brand_reel_verdicts", ba) == 0
    retried = _run(env, "a", retry=True)
    assert retried.run_id == failed.run_id and retried.status == STATUS_OK
    assert env["vendor"].lists == lists and env["vendor"].transcripts == transcripts


def test_enqueue_lock_upsert_and_transcript_are_idempotent(setup: dict[str, Any]) -> None:
    env = setup
    store: PostgresReelRunStore = env["store"]
    (ta, ba) = env["a"]
    one = rr.enqueue_run(ta, ba, "manual", store=store)
    assert rr.enqueue_run(ta, ba, "manual", store=store).id == one.id
    now = datetime.now(UTC)
    handle = f"lk{uuid4().hex[:8]}"
    mine = now + timedelta(minutes=5)
    assert store.try_lock_account(ta, "tiktok", handle, now=now, until=mine)
    assert not store.try_lock_account(
        env["b"][0], "tiktok", handle, now=now, until=now + timedelta(minutes=5)
    )
    # a stale lock value never releases the current one
    store.finish_account(ta, "tiktok", handle, now=now, status="ok", lock_until=now)
    store.release_account(ta, "tiktok", handle, lock_until=now)
    assert not store.try_lock_account(
        env["b"][0], "tiktok", handle, now=now, until=now + timedelta(minutes=5)
    )
    store.finish_account(ta, "tiktok", handle, now=now, status="ok", page1=True, lock_until=mine)
    assert store.try_lock_account(
        env["b"][0], "tiktok", handle, now=now, until=now + timedelta(minutes=5)
    )
    reel = rr._public_reel(
        {
            "id": f"m{uuid4().hex[:8]}",
            "network": "tiktok",
            "handle": handle,
            "takenAt": now.timestamp() - 3600,
            "views": 10,
            "caption": "a",
        },
        now,
    )
    store.upsert_reels(ta, [reel])
    stale = rr._public_reel(
        {
            "id": reel.reel_id,
            "network": "tiktok",
            "handle": handle,
            "takenAt": now.timestamp() - 3600,
            "views": 1,
            "caption": "old",
        },
        now - timedelta(hours=1),
    )
    store.upsert_reels(ta, [stale])  # a late retry never overwrites newer metrics
    store.save_transcript(ta, "tiktok", reel.reel_id, text="uno", source="tiktok_vtt", now=now)
    store.save_transcript(ta, "tiktok", reel.reel_id, text="dos", source="tiktok_vtt", now=now)
    (got,) = store.reels_of(ta, [("tiktok", handle)], since=now - timedelta(days=1))
    assert got.views == 10 and got.caption == "a" and got.transcript == "uno"


def test_the_default_brief_loaders_read_the_kit_and_catalog(setup: dict[str, Any]) -> None:
    """The packages-side loaders (no Reflex): no kit and no products on a new brand."""
    (ta, ba) = setup["a"]
    assert brand_brief.load_kit(ta, ba) is None
    assert brand_brief.load_products(ta, ba) == ()
