"""RF-09 (m-25119466) against the live schema: `PostgresReelBadgeStore` through
`tenant_session` — the SQL of the account read, the rubro read and the rubro pool
(`percentile_cont`, maturity, window, distinct accounts) agreeing with the memory twin, and
two businesses that label different accounts getting the same badges for the same public
reels, with nothing of the other in them. Computing badges adds no `vendor_usage_events`
row.

The pool is global, so this test isolates its rows by a rubro of its own (random letters,
`ck_creator_rubro` allows any `^[a-z_]*$`) and a window in 2001, where no other test
writes reels."""

from __future__ import annotations

import random
import string
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.referentes import PostgresReferentesRepository
from qualify_api.referentes import reel_badges as rb
from qualify_api.referentes.reel_store import PostgresReelRunStore, PublicReel
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

NOW = datetime(2001, 3, 1, 12, tzinfo=UTC)


def _business() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="RF-09", country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="RF-09 brand"))
    return tenant, brand


def _usage_events() -> int:
    with admin_session() as session:
        return int(session.scalar(text("SELECT count(*) FROM vendor_usage_events")) or 0)


def _letters(n: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


class Env:
    def __init__(self) -> None:
        self.token = _letters(8)
        self.rubro = f"rfnine_{_letters()}"
        self.runs = PostgresReelRunStore()

    def handle(self, name: str) -> str:
        return f"rf09{name}{self.token}"

    def reels(self, name: str, views: list[int], **kwargs: object) -> list[PublicReel]:
        return [self.reel(name, f"{i}", v, **kwargs) for i, v in enumerate(views)]  # type: ignore[arg-type]

    def reel(
        self,
        name: str,
        tag: str,
        views: int,
        *,
        age_days: float = 10.0,
        read_after_days: float | None = None,
        hidden: bool = False,
    ) -> PublicReel:
        taken = NOW - timedelta(days=age_days)
        return PublicReel(
            network="instagram",
            reel_id=f"rf09{self.token}{name}{tag}",
            handle=self.handle(name),
            taken_at=taken,
            metrics_at=NOW if read_after_days is None else taken + timedelta(days=read_after_days),
            parser_version=2,
            views=views,
            likes=1,
            counts_hidden=hidden,
        )

    def save(self, reels: list[PublicReel]) -> None:
        self.runs.upsert_reels(uuid4(), reels)

    def creator(self, name: str, rubro: str) -> None:
        # `creators` is global: qualify_app writes it (qualify_admin may only read)
        with tenant_session(uuid4()) as session:
            session.execute(
                text(
                    "INSERT INTO creators (network, handle, seen_at, rubro, rubro_source, "
                    "rubro_model, rubro_version, rubro_inferred_at) "
                    "VALUES ('instagram', :h, now(), :r, CASE WHEN :r = '' THEN '' ELSE 'ai' END, "
                    "CASE WHEN :r = '' THEN '' ELSE 'claude-haiku' END, 'referentes-review-3', "
                    "CASE WHEN :r = '' THEN NULL ELSE now() END)"
                ),
                {"h": self.handle(name), "r": rubro},
            )


@pytest.fixture
def env() -> Env:
    return Env()


def test_postgres_and_memory_agree_on_every_badge(env: Env) -> None:
    tenant, _ = _business()
    flat = [env.reels(f"acc{a}", [1000 * (a + 1)] * 10) for a in range(3)]
    star = env.reel("acc2", "star", 9000)
    extra = [
        env.reel("acc0", "young", 1_000_000, age_days=1),  # young read: out of the pool
        env.reel("acc0", "hidden", 1_000_000, hidden=True),
        env.reel("acc0", "old", 1_000_000, age_days=rb.TOP_WINDOW_DAYS + 5),
    ]
    nobody = env.reels("norubro", [100, 100, 100, 5000])
    everything = [*flat[0], *flat[1], *flat[2], star, *extra, *nobody]
    env.save(everything)
    for a in range(3):
        env.creator(f"acc{a}", env.rubro)
    env.creator("norubro", "")

    pg = rb.PostgresReelBadgeStore()
    pools = pg.rubro_pools(
        tenant, [env.rubro], since=NOW - timedelta(days=rb.TOP_WINDOW_DAYS), until=NOW
    )
    assert pools[env.rubro].sample == 31  # 30 flat + the star; young, hidden, old out
    assert pools[env.rubro].accounts == 3
    assert pools[env.rubro].threshold == 3000.0

    memory = rb.MemoryReelBadgeStore(
        everything, {(r.network, r.handle): env.rubro for r in [*flat[0], *flat[1], *flat[2]]}
    )
    before = _usage_events()
    got = rb.reel_badges(tenant, everything, store=pg, now=NOW)
    assert _usage_events() == before
    assert got == rb.reel_badges(tenant, everything, store=memory, now=NOW)
    star_key = ("instagram", star.reel_id)
    assert [b.key for b in got[star_key]] == ["rising", "top_rubro"]
    # an account without a rubro is «rising» at most, never «Top 10 %»
    assert [b.key for b in got[("instagram", nobody[3].reel_id)]] == ["rising"]


def test_two_businesses_get_the_same_badges_and_nothing_of_each_other(env: Env) -> None:
    a, b = _business(), _business()
    labels = PostgresReferentesRepository()
    for who, name in ((a, "mine"), (b, "theirs")):
        labels.set_label(
            tenant_id=who[0],
            brand_id=who[1],
            network="instagram",
            handle=env.handle(name),
            label="referente",
            labeled_by=None,
        )
    mine = env.reels("mine", [100, 100, 100, 400])
    theirs = env.reels("theirs", [100, 100, 100, 900])
    env.save([*mine, *theirs])

    pg = rb.PostgresReelBadgeStore()
    badges_a = rb.reel_badges(a[0], mine, store=pg, now=NOW)
    assert set(badges_a) == {("instagram", mine[3].reel_id)}
    # public data only: who asks changes nothing, and B's account never shows up
    assert rb.reel_badges(b[0], mine, store=pg, now=NOW) == badges_a
    for earned in badges_a.values():
        for badge in earned:
            assert env.handle("theirs") not in repr(badge)
            assert str(b[0]) not in repr(badge) and str(b[1]) not in repr(badge)
