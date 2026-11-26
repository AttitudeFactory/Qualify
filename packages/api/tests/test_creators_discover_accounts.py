"""«Descubrir cuentas nuevas», offline (RF-07a, m-25119467).

Pins: only accounts the brand has not labeled (detractors included) are offered; a follow
is the owner's click, writes `referente`/`competencia` once and hides the account; filters,
default order and pagination; the `few_results` signal for RF-07b; two businesses never
see each other's labels; the module cannot reach a paid vendor.
"""

from __future__ import annotations

import ast
import inspect
from uuid import UUID, uuid4

import pytest

from qualify_api.creators import discover_accounts as da
from qualify_api.creators.discover_accounts import (
    DiscoveredAccount,
    DiscoverFilters,
    MemoryDiscoverStore,
    follow_account,
)
from qualify_api.referentes.repository import MemoryReferentesRepository


def _acc(handle: str, **facts: object) -> DiscoveredAccount:
    return DiscoveredAccount(network=str(facts.pop("network", "instagram")), handle=handle, **facts)  # type: ignore[arg-type]


def _world(*accounts: DiscoveredAccount) -> tuple[MemoryDiscoverStore, UUID, UUID]:
    repo = MemoryReferentesRepository()
    tenant, brand = uuid4(), uuid4()
    repo.add_brand(tenant_id=tenant, brand_id=brand)
    store = MemoryDiscoverStore(labels_repo=repo, brands={brand: tenant})
    for account in accounts:
        store.add(account)
    return store, tenant, brand


def _handles(store: MemoryDiscoverStore, tenant: UUID, brand: UUID, **kw: object) -> list[str]:
    filters = kw.pop("filters", DiscoverFilters())
    page = store.page(tenant_id=tenant, brand_id=brand, filters=filters, **kw)  # type: ignore[arg-type]
    return [a.handle for a in page.accounts]


def test_exact_client_texts() -> None:
    assert da.TITLE == "Descubrir cuentas nuevas"
    assert da.FOLLOW_AS_INSPIRATION == "Seguir como inspiración"
    assert da.FOLLOW_AS_COMPETITOR == "Seguir como competidor"
    assert da.EMPTY_TEXT == "Todavía no encontramos cuentas nuevas con estos filtros."
    assert da.FOLLOW_BUTTONS == {
        "referente": "Seguir como inspiración",
        "competencia": "Seguir como competidor",
    }


def test_labeled_accounts_never_offered_detractor_included() -> None:
    store, tenant, brand = _world(_acc("ref"), _acc("comp"), _acc("det"), _acc("nueva"))
    repo = store.labels_repo
    for handle, label in (("ref", "referente"), ("comp", "competencia"), ("det", "detractor")):
        repo.set_label(
            tenant_id=tenant, brand_id=brand, network="instagram", handle=handle, label=label
        )
    assert _handles(store, tenant, brand) == ["nueva"]


def test_follow_labels_and_hides_account() -> None:
    store, tenant, brand = _world(_acc("uno"), _acc("dos"))
    owner = uuid4()
    result = follow_account(
        store.labels_repo,
        tenant_id=tenant,
        brand_id=brand,
        labeled_by=owner,
        network="Instagram",
        handle="@UNO",
        label="competencia",
    )
    assert result.created
    assert (result.label.handle, result.label.label, result.label.labeled_by) == (
        "uno",
        "competencia",
        owner,
    )
    assert _handles(store, tenant, brand) == ["dos"]
    stored = store.labels_repo.labels(tenant_id=tenant, brand_id=brand)
    assert [(s.handle, s.label) for s in stored] == [("uno", "competencia")]


def test_follow_is_idempotent_and_never_overwrites() -> None:
    store, tenant, brand = _world(_acc("uno"))
    repo = store.labels_repo
    owner = uuid4()
    kw = dict(tenant_id=tenant, brand_id=brand, labeled_by=owner, network="instagram")
    first = follow_account(repo, handle="uno", label="referente", **kw)  # type: ignore[arg-type]
    again = follow_account(repo, handle="uno", label="competencia", **kw)  # type: ignore[arg-type]
    assert first.created and not again.created
    assert again.label.label == "referente"
    # a detractor mark is never turned into a follow
    repo.set_label(
        tenant_id=tenant, brand_id=brand, network="tiktok", handle="malo", label="detractor"
    )
    kept = follow_account(
        repo,
        tenant_id=tenant,
        brand_id=brand,
        labeled_by=owner,
        network="tiktok",
        handle="malo",
        label="referente",
    )
    assert not kept.created and kept.label.label == "detractor"
    assert len(repo.labels(tenant_id=tenant, brand_id=brand)) == 2


@pytest.mark.parametrize("label", ["detractor", "otro", ""])
def test_follow_only_as_inspiration_or_competitor(label: str) -> None:
    store, tenant, brand = _world(_acc("uno"))
    with pytest.raises(ValueError):
        follow_account(
            store.labels_repo,
            tenant_id=tenant,
            brand_id=brand,
            labeled_by=uuid4(),
            network="instagram",
            handle="uno",
            label=label,  # type: ignore[arg-type]
        )
    assert store.labels_repo.labels(tenant_id=tenant, brand_id=brand) == ()


def test_follow_needs_the_owner() -> None:
    store, tenant, brand = _world(_acc("uno"))
    with pytest.raises(ValueError):
        follow_account(
            store.labels_repo,
            tenant_id=tenant,
            brand_id=brand,
            labeled_by=None,  # type: ignore[arg-type]
            network="instagram",
            handle="uno",
            label="referente",
        )


def test_listing_writes_no_label() -> None:
    store, tenant, brand = _world(*(_acc(f"c{i}") for i in range(30)))
    for page in range(3):
        store.page(tenant_id=tenant, brand_id=brand, filters=DiscoverFilters(), page=page)
    store.suggested_filters(tenant_id=tenant, brand_id=brand)
    assert store.labels_repo.labels(tenant_id=tenant, brand_id=brand) == ()


def test_filters() -> None:
    store, tenant, brand = _world(
        _acc("small", followers=5_000, region_code="CO", rubro="food_drink", median_views=900.0),
        _acc("mid", followers=30_000, region_code="VE", rubro="food_drink", engagement=0.05),
        _acc(
            "big", followers=2_000_000, region_code="CO", rubro="fashion_beauty", median_views=1e6
        ),
        _acc("tt", network="tiktok", followers=None, region_code="UY", engagement=0.01),
    )
    f = DiscoverFilters
    assert _handles(store, tenant, brand, filters=f(networks=("TikTok",))) == ["tt"]
    assert set(
        _handles(store, tenant, brand, filters=f(follower_bands=("hasta_10k", "mas_1m")))
    ) == {
        "small",
        "big",
    }
    assert set(_handles(store, tenant, brand, filters=f(region_codes=("co",)))) == {"small", "big"}
    assert _handles(
        store, tenant, brand, filters=f(rubros=("food_drink",), region_codes=("VE",))
    ) == ["mid"]
    assert _handles(store, tenant, brand, filters=f(min_median_views=1_000)) == ["big"]
    assert _handles(store, tenant, brand, filters=f(min_engagement=0.02)) == ["mid"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"networks": ("facebook",)},
        {"follower_bands": ("enorme",)},
        {"region_codes": ("Colombia",)},
        {"rubros": ("astronautas",)},
        {"min_median_views": -1},
        {"min_engagement": float("nan")},
    ],
)
def test_bad_filters_refused(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        DiscoverFilters(**kwargs)


def test_default_order_complete_then_interaction_then_views() -> None:
    store, tenant, brand = _world(
        _acc("blank", followers=9_000_000),
        _acc("big_low", median_views=1e6, engagement=0.01, followers=1_000_000),
        _acc("small_high", median_views=2_000.0, engagement=0.09, followers=4_000),
        _acc("views_only", median_views=5e6),
    )
    assert _handles(store, tenant, brand) == ["small_high", "big_low", "views_only", "blank"]


def test_pagination_is_total_and_stable() -> None:
    accounts = [_acc(f"c{i:02d}", followers=1_000) for i in range(25)]
    store, tenant, brand = _world(*accounts)
    seen: list[str] = []
    for page in range(3):
        result = store.page(
            tenant_id=tenant, brand_id=brand, filters=DiscoverFilters(), page=page, page_size=10
        )
        assert result.total == 25
        assert result.has_more == (page < 2)
        seen += [a.handle for a in result.accounts]
    assert seen == sorted(seen) and len(set(seen)) == 25
    with pytest.raises(ValueError):
        store.page(tenant_id=tenant, brand_id=brand, filters=DiscoverFilters(), page_size=51)


def test_few_results_is_only_a_signal() -> None:
    store, tenant, brand = _world(*(_acc(f"c{i}") for i in range(7)))
    page = store.page(tenant_id=tenant, brand_id=brand, filters=DiscoverFilters())
    assert page.few_results and page.total == 7
    store.add(_acc("c7"))
    assert not store.page(tenant_id=tenant, brand_id=brand, filters=DiscoverFilters()).few_results


def test_two_businesses_never_see_each_others_labels() -> None:
    repo = MemoryReferentesRepository()
    tenant_a, brand_a, tenant_b, brand_b = uuid4(), uuid4(), uuid4(), uuid4()
    repo.add_brand(tenant_id=tenant_a, brand_id=brand_a)
    repo.add_brand(tenant_id=tenant_b, brand_id=brand_b)
    store = MemoryDiscoverStore(labels_repo=repo, brands={brand_a: tenant_a, brand_b: tenant_b})
    store.add(_acc("compartida", region_code="CO", rubro="food_drink"))
    follow_account(
        repo,
        tenant_id=tenant_a,
        brand_id=brand_a,
        labeled_by=uuid4(),
        network="instagram",
        handle="compartida",
        label="competencia",
    )
    assert _handles(store, tenant_a, brand_a) == []
    assert _handles(store, tenant_b, brand_b) == ["compartida"]
    assert store.suggested_filters(tenant_id=tenant_b, brand_id=brand_b) == da.SuggestedFilters()
    assert store.suggested_filters(tenant_id=tenant_a, brand_id=brand_a) == da.SuggestedFilters(
        region_code="CO", rubro="food_drink"
    )
    with pytest.raises(ValueError):  # B cannot read through A's brand
        store.page(tenant_id=tenant_b, brand_id=brand_a, filters=DiscoverFilters())
    with pytest.raises(ValueError):  # nor label for it
        follow_account(
            repo,
            tenant_id=tenant_b,
            brand_id=brand_a,
            labeled_by=uuid4(),
            network="instagram",
            handle="otra",
            label="referente",
        )


def test_proposal_carries_no_other_business_data() -> None:
    fields = set(DiscoveredAccount.__dataclass_fields__)
    assert not {f for f in fields if any(w in f for w in ("tenant", "brand", "user", "term"))}


def test_band_of() -> None:
    assert da.band_of(None) == ""
    assert da.band_of(9_999) == "hasta_10k"
    assert da.band_of(10_000) == "10k_50k"
    assert da.band_of(1_000_000) == "mas_1m"


def test_module_cannot_reach_a_paid_vendor() -> None:
    tree = ast.parse(inspect.getsource(da))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    banned = ("vendors", "anthropic", "httpx", "scrapecreators", "usage", "claude")
    assert not [m for m in imported if any(b in m for b in banned)], imported
