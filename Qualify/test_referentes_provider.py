"""`referentes_provider` — the bridge between the phased search and its Postgres store —
over `MemoryReferentesRepository` (the Postgres implementation has its own contract suite
in `packages/api/tests/test_referentes_repository.py`). Fully offline."""

from __future__ import annotations

import time
from uuid import UUID, uuid4

import pytest
from qualify_api.referentes import MemoryReferentesRepository, validate_seed

from . import creator_discovery as cd
from . import referentes_provider as rp
from .creative_wizard_pages import BrandConnectState

TENANT = UUID("5e5e0000-0000-4000-8000-0000000000b1")
OTHER_TENANT = UUID("5e5e0000-0000-4000-8000-0000000000b2")


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> MemoryReferentesRepository:
    memory = MemoryReferentesRepository()
    monkeypatch.setattr(rp, "REPOSITORY", memory)
    return memory


@pytest.fixture
def brand(repo: MemoryReferentesRepository) -> UUID:
    brand_id = uuid4()
    repo.add_brand(tenant_id=TENANT, brand_id=brand_id)
    return brand_id


def _seed(city: str = "Cúcuta") -> cd.DiscoverySeed:
    return cd.DiscoverySeed(
        handle="midu.dev",
        niches=("tech",),
        hashtags=("programacion", "javascript"),
        country_code="CO",
        city=city,
    )


def _candidate(network: str, username: str, followers: int) -> cd.Candidate:
    return cd.Candidate(
        network=network,
        username=username,
        full_name=username.title(),
        followers=followers,
        profile_url=f"https://{network}.com/@{username}",
        sources=[f"{network}:hashtag:#programacion"],
    )


def _result(key: str = "sector", *, errors: tuple[str, ...] = ()) -> cd.PhaseResult:
    accounts = (
        []
        if errors
        else [
            _candidate("tiktok", "MiduDev", 900_000),
            _candidate("instagram", "carlosazaustre", 300_000),
        ]
    )
    return cd.PhaseResult(
        key=key,
        title="Referentes de tecnología",
        accounts=accounts,
        queries=["tiktok hashtag: programacion"],
        credits=2,
        errors=list(errors),
    )


def test_the_stored_seed_keeps_each_hashtag_origin() -> None:
    payload = rp.seed_payload(_seed())
    assert payload["hashtags"] == [
        {"tag": "programacion", "origin": "profile"},
        {"tag": "javascript", "origin": "profile"},
    ]
    assert validate_seed(payload) == payload


def test_a_stored_phase_renders_exactly_like_the_fresh_run(
    repo: MemoryReferentesRepository, brand: UUID
) -> None:
    result = _result()
    phase = cd.phase_to_dict(result)
    assert rp.save_phase(TENANT, brand, "sector", _seed(), result, phase) is True

    assert rp.find_phase(TENANT, brand, "sector", _seed()) == phase

    stored = repo.current_phases(tenant_id=TENANT, brand_id=brand)[0]
    assert stored.algorithm_version == cd.PHASED_PLAN_VERSION
    assert [(a.network, a.handle) for a in stored.accounts] == [
        ("tiktok", "midudev"),
        ("instagram", "carlosazaustre"),
    ]
    assert stored.accounts[0].found_by == ("tiktok:hashtag:#programacion",)


def test_a_new_algorithm_version_or_an_expired_result_is_a_miss(
    repo: MemoryReferentesRepository, brand: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _result()
    rp.save_phase(TENANT, brand, "sector", _seed(), result, cd.phase_to_dict(result))

    later = time.time() + rp.PHASE_TTL_SECONDS + 60
    assert rp.find_phase(TENANT, brand, "sector", _seed(), now=later) is None

    monkeypatch.setattr(cd, "PHASED_PLAN_VERSION", cd.PHASED_PLAN_VERSION + 1)
    assert rp.find_phase(TENANT, brand, "sector", _seed()) is None


def test_a_failed_phase_that_found_nothing_is_not_stored(
    repo: MemoryReferentesRepository, brand: UUID
) -> None:
    result = _result(errors=("tiktok: 500",))
    assert (
        rp.save_phase(TENANT, brand, "sector", _seed(), result, cd.phase_to_dict(result)) is False
    )
    assert repo.current_phases(tenant_id=TENANT, brand_id=brand) == ()


def test_going_back_to_a_city_already_searched_reuses_it(
    repo: MemoryReferentesRepository, brand: UUID
) -> None:
    for city in ("Cúcuta", "Bogotá"):
        result = _result("local")
        rp.save_phase(TENANT, brand, "local", _seed(city), result, cd.phase_to_dict(result))

    assert rp.find_phase(TENANT, brand, "local", _seed("Cúcuta")) is not None
    (current,) = repo.current_phases(tenant_id=TENANT, brand_id=brand)
    assert current.seed["city"] == "Cúcuta"


def test_the_sort_round_trips_through_the_bucket_keys(
    repo: MemoryReferentesRepository, brand: UUID
) -> None:
    cards = cd.phase_to_dict(_result())["accounts"]
    keys = [f"{c['network']}:{c['handle']}" for c in cards]
    assert keys == ["TikTok:@MiduDev", "Instagram:@carlosazaustre"]

    rp.write_labels(TENANT, brand, None, {keys[0]: "competencia", keys[1]: "referente"})
    assert rp.load_sort(TENANT, brand, cards) == (
        {keys[0]: "competencia", keys[1]: "referente"},
        [],
    )

    rp.write_labels(TENANT, brand, None, {keys[1]: ""})  # Deshacer
    assert rp.load_sort(TENANT, brand, cards) == ({keys[0]: "competencia"}, [])
    # another tenant sees none of it
    assert rp.load_sort(OTHER_TENANT, brand, cards) == ({}, [])


def _save(
    brand: UUID, key: str, result: cd.PhaseResult, seed: cd.DiscoverySeed | None = None
) -> None:
    rp.save_phase(TENANT, brand, key, seed or _seed(), result, cd.phase_to_dict(result))


def test_a_sorted_account_the_new_search_dropped_stays_in_its_bucket(
    repo: MemoryReferentesRepository, brand: UUID
) -> None:
    _save(brand, "sector", _result())
    rp.write_labels(TENANT, brand, None, {"TikTok:@MiduDev": "competencia"})

    # the recompute no longer finds MiduDev
    newer = cd.PhaseResult(key="sector", title="t", accounts=[_candidate("tiktok", "otra", 10)])
    _save(brand, "sector", newer)
    on_screen = cd.phase_to_dict(newer)["accounts"]

    buckets, kept = rp.load_sort(TENANT, brand, on_screen)
    assert buckets == {"TikTok:@MiduDev": "competencia"}
    assert [c["handle"] for c in kept] == ["@MiduDev"]
    assert kept[0]["reason"] == rp.KEPT_REASON
    assert kept[0]["followers"] == "900K"  # the stored card, not a blank one


def test_the_wizard_shows_kept_accounts_only_inside_their_bucket() -> None:
    state = BrandConnectState()
    state.sector_accounts = [{"handle": "@nueva", "network": "TikTok"}]
    state.kept_accounts = [
        {"handle": "@vieja", "network": "TikTok"},
        {"handle": "@sin_cubo", "network": "TikTok"},
    ]
    state.account_buckets = {"TikTok:@vieja": "detractor"}
    assert [a["handle"] for a in state.discovered_accounts] == ["@nueva", "@vieja"]
    assert [a["handle"] for a in state.detractor_accounts] == ["@vieja"]
    # never dealt into the deck
    assert [a["handle"] for a in state.stage_pool] == ["@nueva"]


# --------------------------------------------------------------------------------------
# recompute with a newer algorithm
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", cd.PHASES)
def test_a_rebuilt_seed_signs_exactly_like_the_original(key: str) -> None:
    seed = cd.DiscoverySeed(
        handle="midu.dev",
        niches=("tech", "education"),
        hashtags=("programacion", "javascript", "cucuta"),
        country_code="CO",
        city="Cúcuta",
        related=("mouredev",),
        terms=("desarrollo web",),
    )
    rebuilt = rp.rebuild_seed(rp.seed_payload(seed))
    assert rebuilt == seed
    assert cd.phase_signature(key, rebuilt) == cd.phase_signature(key, seed)


@pytest.fixture
def stored_v4(
    repo: MemoryReferentesRepository, brand: UUID, monkeypatch: pytest.MonkeyPatch
) -> UUID:
    """A brand whose sector and local phases version 4 computed, and a sort over them;
    the running algorithm is the current version again when the fixture returns."""
    current = cd.PHASED_PLAN_VERSION
    monkeypatch.setattr(cd, "PHASED_PLAN_VERSION", 4)
    _save(brand, "local", _result("local"))
    _save(brand, "sector", _result("sector"), _seed("Bogotá"))  # the newest answers
    monkeypatch.setattr(cd, "PHASED_PLAN_VERSION", current)
    rp.write_labels(TENANT, brand, None, {"TikTok:@MiduDev": "referente"})
    return brand


def test_plan_refresh_lists_brands_from_older_versions(stored_v4: UUID) -> None:
    (plan,) = rp.plan_refresh(TENANT)
    assert plan.brand_id == stored_v4
    assert plan.keys == ("sector", "local")  # PHASES order, not storage order
    assert plan.from_versions == (4,)
    assert plan.estimated_credits == 4
    assert plan.seed.city == "Bogotá"  # the newest phase's seed
    assert rp.plan_refresh(OTHER_TENANT) == []
    assert rp.plan_refresh(TENANT, brand_id=uuid4()) == []


def test_execute_refresh_stores_the_new_version_and_keeps_the_sort(
    repo: MemoryReferentesRepository, stored_v4: UUID
) -> None:
    (plan,) = rp.plan_refresh(TENANT)
    calls: list[tuple[cd.DiscoverySeed, list[str]]] = []

    def fake_run(seed: cd.DiscoverySeed, keys: list[str]) -> list[cd.PhaseResult]:
        calls.append((seed, keys))
        return [
            cd.PhaseResult(
                key=k, title=k, accounts=[_candidate("tiktok", f"nueva_{k}", 5)], credits=3
            )
            for k in keys
        ]

    spent, not_stored = rp.execute_refresh(plan, fake_run)
    assert (spent, not_stored) == (6, [])
    assert calls == [(plan.seed, ["sector", "local"])]

    current = repo.current_phases(tenant_id=TENANT, brand_id=stored_v4)
    assert {p.algorithm_version for p in current} == {cd.PHASED_PLAN_VERSION}
    assert rp.plan_refresh(TENANT) == []
    # the sort is untouched, and the dropped account still has its card
    assert rp.load_sort(TENANT, stored_v4, [])[0] == {"TikTok:@MiduDev": "referente"}


def test_a_phase_that_fails_again_keeps_the_brand_in_the_next_plan(stored_v4: UUID) -> None:
    (plan,) = rp.plan_refresh(TENANT)

    def failing_local(seed: cd.DiscoverySeed, keys: list[str]) -> list[cd.PhaseResult]:
        return [
            cd.PhaseResult(key="sector", title="s", accounts=[_candidate("tiktok", "x", 1)]),
            cd.PhaseResult(key="local", title="l", errors=["tiktok: 500"], credits=1),
        ]

    assert rp.execute_refresh(plan, failing_local) == (1, ["local"])
    (again,) = rp.plan_refresh(TENANT)
    assert again.keys == ("sector", "local")


def test_label_changes_is_the_diff_sync_labels_writes() -> None:
    persisted = {"TikTok:@a": "referente", "TikTok:@b": "detractor"}
    current = {"TikTok:@a": "competencia", "TikTok:@c": "referente"}
    assert rp.label_changes(persisted, current) == {
        "TikTok:@a": "competencia",
        "TikTok:@c": "referente",
        "TikTok:@b": "",
    }
    assert rp.label_changes(current, current) == {}


@pytest.mark.parametrize(
    ("key", "identity"),
    [
        ("TikTok:@MiduDev", ("tiktok", "midudev")),
        ("Instagram:@midu.dev", ("instagram", "midu.dev")),
        ("TikTok:", None),
        (":@midudev", None),
    ],
)
def test_key_identity(key: str, identity: tuple[str, str] | None) -> None:
    assert rp.key_identity(key) == identity


def test_clearing_the_discovery_forgets_what_was_persisted() -> None:
    state = BrandConnectState()
    state._persisted_buckets = {"TikTok:@a": "referente"}
    BrandConnectState._clear_discovery(state)
    assert state._persisted_buckets == {}


def test_catalog_hashtags_survive_the_stored_seed_with_their_origin() -> None:
    seed = cd.DiscoverySeed(
        "brand",
        ("food_drink",),
        hashtags=("mine",),
        country_code="CO",
        terms=("smash burgers",),
        catalog_hashtags=("burgers", "smash"),
    )
    payload = rp.seed_payload(seed)
    assert payload["hashtags"] == [
        {"tag": "mine", "origin": "profile"},
        {"tag": "burgers", "origin": "catalog"},
        {"tag": "smash", "origin": "catalog"},
    ]
    rebuilt = rp.rebuild_seed(payload)
    assert rebuilt.hashtags == ("mine",)
    assert rebuilt.catalog_hashtags == ("burgers", "smash")
    assert rebuilt == seed


def test_the_operators_pills_round_trip_with_their_provenance() -> None:
    """A pill is stored as `operator` (with who suggested it) and comes back as a
    chosen hashtag — so a recompute's signature matches the wizard's."""
    seed = cd.DiscoverySeed(
        "smash",
        ("food_drink",),
        hashtags=("smashburger",),
        catalog_hashtags=("foodie",),
        chosen_hashtags=("hamburguesas", "burgerlovers"),
    )
    payload = rp.seed_payload(
        seed,
        {
            "foodie": {"model": "m", "fit": "alta", "reason": "r"},
            "hamburguesas": {"suggested_by": "claude-sonnet-5", "reason": "producto"},
        },
    )
    validate_seed(payload)
    by_tag = {item["tag"]: item for item in payload["hashtags"]}
    assert by_tag["foodie"]["origin"] == "ai"
    assert by_tag["hamburguesas"] == {
        "tag": "hamburguesas",
        "origin": "operator",
        "suggested_by": "claude-sonnet-5",
        "reason": "producto",
    }
    assert by_tag["burgerlovers"] == {"tag": "burgerlovers", "origin": "operator"}
    rebuilt = rp.rebuild_seed(payload)
    assert rebuilt.chosen_hashtags == ("hamburguesas", "burgerlovers")
    assert rebuilt.catalog_hashtags == ("foodie",)
    assert rebuilt.hashtags == ("smashburger",)
    assert rebuilt.signature() == seed.signature()
