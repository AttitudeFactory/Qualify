"""«Descubrir cuentas nuevas» against Postgres (RF-07a, m-25119467).

Pins the SQL twin of the offline tests: the brand's labels (detractors too) are left out,
the median comes from `public_reels` with the sightings' average as the fallback and each
fact says where it came from, the default order, a follow writes once through
`tenant_session` and hides the account, listing books no `vendor_usage_events`, and two
businesses never see each other's labels.

The pool is global and shared with other tests, so every test scopes its read to a region
code no other test uses.
"""

from __future__ import annotations

import random
import string
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creators.discover_accounts import (
    MAX_PAGE_SIZE,
    VIEWS_PUBLIC_REELS,
    VIEWS_SIGHTINGS,
    DiscoverFilters,
    DiscoverPage,
    PostgresDiscoverStore,
    follow_account,
)
from qualify_api.referentes.repository import PostgresReferentesRepository
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

NOW = datetime.now(UTC)
STORE = PostgresDiscoverStore()
REPO = PostgresReferentesRepository()


def _business() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant, name="RF-07a", country="CO", timezone="America/Bogota", currency="COP"
            )
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="RF-07a brand"))
    return tenant, brand


#: Q? / X? are not real ISO countries; no other test writes them.
_REGIONS = [p + s for p in "QX" for s in string.ascii_uppercase]
_TAKEN: set[str] = set()


@pytest.fixture
def region() -> str:
    """A region no other test of this run uses, and the least used by earlier runs: the
    pool is global and `qualify_test` keeps it between runs (no role may delete from
    `creators`), so assertions also look only at the test's own handles (`_mine`)."""
    with admin_session() as session:
        used = dict(
            session.execute(
                text(
                    "SELECT region_code, count(*) FROM creators "
                    "WHERE region_code = ANY(:codes) GROUP BY region_code"
                ),
                {"codes": _REGIONS},
            ).all()
        )
    free = [r for r in _REGIONS if r not in _TAKEN]
    code = min(free, key=lambda r: (used.get(r, 0), random.random()))
    _TAKEN.add(code)
    return code


def _mine(page: DiscoverPage, *handles: str) -> list[str]:
    return [a.handle for a in page.accounts if a.handle in handles]


@pytest.fixture
def business() -> Iterator[tuple[UUID, UUID]]:
    yield _business()


def _handle(tag: str) -> str:
    return f"rf07a{tag}{uuid4().hex[:8]}"


def _creator(tenant: UUID, handle: str, region: str, **cols: object) -> None:
    values = {
        "network": "instagram",
        "handle": handle,
        "region_code": region,
        "region_source": "profile",
        "region_inferred_at": NOW,
        "seen_at": NOW,
        **cols,
    }
    names = ", ".join(values)
    binds = ", ".join(f":{k}" for k in values)
    with tenant_session(tenant) as session:
        session.execute(text(f"INSERT INTO creators ({names}) VALUES ({binds})"), values)


def _reels(
    tenant: UUID,
    handle: str,
    views: list[int],
    likes: int = 10,
    age_days: int = 10,
    counts_hidden: bool = False,
) -> None:
    with tenant_session(tenant) as session:
        for v in views:
            session.execute(
                text(
                    "INSERT INTO public_reels (network, reel_id, handle, taken_at, views, likes, "
                    "comments, counts_hidden, metrics_at, parser_version) VALUES ('instagram', "
                    ":r, :h, :t, :v, :l, 0, :hidden, :t, 1)"
                ),
                {
                    "r": uuid4().hex,
                    "h": handle,
                    "t": NOW - timedelta(days=age_days),
                    "v": v,
                    "l": likes,
                    "hidden": counts_hidden,
                },
            )


def _sighting(tenant: UUID, handle: str, times: int) -> None:
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO creator_sightings (network, handle, kind, term, times, seen_at) "
                "VALUES ('instagram', :h, 'keyword', :t, :times, now())"
            ),
            {"h": handle, "t": f"t-{uuid4().hex[:6]}", "times": times},
        )


def _page(tenant: UUID, brand: UUID, region: str, **filters: object):  # noqa: ANN202
    return STORE.page(
        tenant_id=tenant,
        brand_id=brand,
        filters=DiscoverFilters(region_codes=(region,), **filters),  # type: ignore[arg-type]
        page_size=MAX_PAGE_SIZE,
        now=NOW,
    )


def test_facts_sources_and_default_order(business, region) -> None:  # noqa: ANN001
    tenant, brand = business
    reels, sightings, blank, young, hidden_likes = (_handle(t) for t in ("r", "s", "b", "y", "h"))
    mine = (reels, sightings, blank, young, hidden_likes)
    _creator(tenant, reels, region, followers=8_000, read_at=NOW)
    _reels(tenant, reels, [100, 300, 200, 50_000])
    _reels(tenant, reels, [9_000_000] * 5, counts_hidden=True)  # not measurable
    # the searches saw views but no likes (hidden): views yes, interaction unknown
    _creator(tenant, hidden_likes, region, posts_seen=3, views_seen=30, likes_seen=0)
    _creator(
        tenant,
        sightings,
        region,
        followers=90_000,
        posts_seen=4,
        views_seen=4_000,
        likes_seen=40,
        comments_seen=0,
    )
    _creator(tenant, blank, region, followers=2_000_000)
    _creator(tenant, young, region)
    _reels(tenant, young, [9_000, 9_000, 9_000], age_days=1)  # too young to measure
    _sighting(tenant, blank, 3)

    page = _page(tenant, brand, region)
    assert _mine(page, *mine) == [reels, sightings, hidden_likes, blank, young]
    by_handle = {a.handle: a for a in page.accounts}
    first, second, third, fourth = (by_handle[h] for h in (reels, sightings, blank, young))
    assert (by_handle[hidden_likes].median_views, by_handle[hidden_likes].engagement) == (
        10.0,
        None,
    )
    assert by_handle[hidden_likes].engagement_source == ""
    assert (first.median_views, first.views_source, first.views_sample) == (
        250.0,
        VIEWS_PUBLIC_REELS,
        4,
    )
    assert first.engagement_source == VIEWS_PUBLIC_REELS and first.followers_source == "profile"
    assert first.engagement == pytest.approx((10 / 200 + 10 / 300) / 2)
    assert (second.median_views, second.views_source, second.engagement) == (
        1_000.0,
        VIEWS_SIGHTINGS,
        pytest.approx(0.01),
    )
    assert second.followers_source == "search"
    assert third.median_views is None and third.views_source == ""
    assert fourth.median_views is None and fourth.followers_source == ""
    assert (first.region_code, first.region_source) == (region, "profile")
    assert page.total >= len(mine)

    assert _mine(_page(tenant, brand, region, min_median_views=500), *mine) == [sightings]
    assert _mine(_page(tenant, brand, region, follower_bands=("mas_1m",)), *mine) == [blank]
    assert _mine(_page(tenant, brand, region, min_engagement=0.0), *mine) == [reels, sightings]


def test_labeled_and_private_accounts_are_left_out(business, region) -> None:  # noqa: ANN001
    tenant, brand = business
    det, ref, hidden, fresh = (_handle(t) for t in ("d", "r", "p", "f"))
    for handle in (det, ref, fresh):
        _creator(tenant, handle, region)
    _creator(tenant, hidden, region, is_private=True)
    REPO.set_label(
        tenant_id=tenant, brand_id=brand, network="instagram", handle=det, label="detractor"
    )
    REPO.set_label(
        tenant_id=tenant, brand_id=brand, network="instagram", handle=ref, label="referente"
    )
    assert _mine(_page(tenant, brand, region), det, ref, hidden, fresh) == [fresh]


def test_follow_hides_the_account_once_and_books_nothing(business, region) -> None:  # noqa: ANN001
    tenant, brand = business
    one, two = _handle("1"), _handle("2")
    _creator(tenant, one, region)
    _creator(tenant, two, region)
    with admin_session() as session:
        before = session.scalar(text("SELECT count(*) FROM vendor_usage_events"))

    assert set(_mine(_page(tenant, brand, region), one, two)) == {one, two}
    STORE.suggested_filters(tenant_id=tenant, brand_id=brand)
    kw = dict(tenant_id=tenant, brand_id=brand, labeled_by=_user(tenant), network="instagram")
    first = follow_account(REPO, handle=one, label="competencia", **kw)  # type: ignore[arg-type]
    again = follow_account(REPO, handle=one, label="referente", **kw)  # type: ignore[arg-type]
    assert first.created and not again.created and again.label.label == "competencia"
    assert _mine(_page(tenant, brand, region), one, two) == [two]
    assert STORE.suggested_filters(tenant_id=tenant, brand_id=brand).region_code == region

    with admin_session() as session:
        after = session.scalar(text("SELECT count(*) FROM vendor_usage_events"))
    assert after == before


def _user(tenant: UUID) -> UUID:
    user = uuid4()
    with admin_session() as session:
        session.add(
            User(id=user, tenant_id=tenant, email=f"{user}@test.invalid", display_name="Owner")
        )
    return user


def test_two_businesses_never_see_each_others_labels(region) -> None:  # noqa: ANN001
    tenant_a, brand_a = _business()
    tenant_b, brand_b = _business()
    shared = _handle("x")
    _creator(tenant_a, shared, region)
    REPO.set_label(
        tenant_id=tenant_a,
        brand_id=brand_a,
        network="instagram",
        handle=shared,
        label="competencia",
    )
    assert _mine(_page(tenant_a, brand_a, region), shared) == []
    assert _mine(_page(tenant_b, brand_b, region), shared) == [shared]
    # B's suggestions come from B's labels only (none), never from A's
    assert STORE.suggested_filters(tenant_id=tenant_b, brand_id=brand_b).region_code == ""
    # B passing A's brand id reads nothing and writes nothing
    with pytest.raises(ValueError):
        _page(tenant_b, brand_a, region)
    with pytest.raises(ValueError):
        STORE.suggested_filters(tenant_id=tenant_b, brand_id=brand_a)
    with pytest.raises(ValueError):
        REPO.set_label(
            tenant_id=tenant_b,
            brand_id=brand_a,
            network="instagram",
            handle=shared,
            label="referente",
        )
    # and RLS hands B none of A's label rows at all
    with tenant_session(tenant_b) as session:
        rows = session.scalar(
            text("SELECT count(*) FROM brand_account_labels WHERE handle = :h"), {"h": shared}
        )
    assert rows == 0


def test_past_the_last_page_still_counts(business, region) -> None:  # noqa: ANN001
    tenant, brand = business
    for i in range(3):
        _creator(tenant, _handle(f"p{i}"), region)
    filters = DiscoverFilters(region_codes=(region,))
    first = STORE.page(tenant_id=tenant, brand_id=brand, filters=filters, page_size=2, now=NOW)
    far = STORE.page(
        tenant_id=tenant, brand_id=brand, filters=filters, page=100_000, page_size=2, now=NOW
    )
    assert first.total >= 3 and first.has_more
    assert far.accounts == () and far.total == first.total and not far.has_more
