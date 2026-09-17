"""The referentes repository contract (migration 0020), run against BOTH implementations:
`MemoryReferentesRepository` offline, `PostgresReferentesRepository` against the compose
Postgres (`db` marker) — so the database's own guarantees (the partial unique index, the
CHECKs, RLS) are exercised, not just this module's belief in them."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.referentes import (
    ORIGIN_PROFILE,
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    PostgresReferentesRepository,
    ReferentesRepository,
    normalize_handle,
    validate_seed,
)

# Distinct from every other suite's tenants so the db runs stay independent (the `5e5e`
# prefix is used nowhere else — grep before reusing it).
TENANT_A = UUID("5e5e0000-0000-4000-8000-0000000000a1")
TENANT_B = UUID("5e5e0000-0000-4000-8000-0000000000a2")


@dataclass(frozen=True)
class Env:
    repo: ReferentesRepository
    tenant_a: UUID
    brand_a: UUID
    tenant_b: UUID
    brand_b: UUID


def _postgres_env() -> Env:
    from qualify_shared.db.admin import admin_session

    from qualify_api.tenancy.models import Brand, Tenant

    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"referentes-t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        # A fresh brand per test: the "one current phase per brand" invariant would
        # otherwise make re-runs depend on what the previous run left behind.
        brands = {}
        for tid in (TENANT_A, TENANT_B):
            brand = Brand(tenant_id=tid, name=f"referentes-{uuid4()}")
            session.add(brand)
            session.flush()
            brands[tid] = brand.id
    return Env(
        PostgresReferentesRepository(), TENANT_A, brands[TENANT_A], TENANT_B, brands[TENANT_B]
    )


def _memory_env() -> Env:
    repo = MemoryReferentesRepository()
    brand_a, brand_b = uuid4(), uuid4()
    repo.add_brand(tenant_id=TENANT_A, brand_id=brand_a)
    repo.add_brand(tenant_id=TENANT_B, brand_id=brand_b)
    return Env(repo, TENANT_A, brand_a, TENANT_B, brand_b)


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
def env(request: pytest.FixtureRequest) -> Iterator[Env]:
    if request.param == "memory":
        yield _memory_env()
        return
    pg = _postgres_env()
    yield pg
    _retire_test_phases(pg)


def _retire_test_phases(env: Env) -> None:
    """Leave no CURRENT phase behind in the dev database. These tests store phases of
    older algorithm versions on purpose, and a current one would show up in
    `just refresh-referentes` as a real brand to recompute — spending real credits on a
    test seed."""
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import func, update

    from qualify_api.referentes.models import BrandDiscoveryPhase

    for tenant_id, brand_id in ((env.tenant_a, env.brand_a), (env.tenant_b, env.brand_b)):
        with tenant_session(tenant_id) as session:
            session.execute(
                update(BrandDiscoveryPhase)
                .where(
                    BrandDiscoveryPhase.brand_id == brand_id,
                    BrandDiscoveryPhase.superseded_at.is_(None),
                )
                .values(superseded_at=func.now())
            )


def _seed(city: str = "Cúcuta") -> dict:
    return {
        "handle": "midu.dev",
        "niches": ["tech"],
        "terms": [],
        "related": [],
        "country_code": "CO",
        "city": city,
        "hashtags": [{"tag": "programacion", "origin": ORIGIN_PROFILE}],
    }


def _phase(
    env: Env,
    *,
    key: str = "sector",
    version: int = 5,
    signature: str = "sig-1",
    handles: tuple[str, ...] = ("@MiduDev", "carlosazaustre"),
    tenant: UUID | None = None,
    brand: UUID | None = None,
) -> NewDiscoveryPhase:
    return NewDiscoveryPhase(
        tenant_id=tenant or env.tenant_a,
        brand_id=brand or env.brand_a,
        phase_key=key,
        algorithm_version=version,
        seed_signature=signature,
        seed=_seed(),
        title="Referentes de tecnología",
        queries=("tiktok keyword: programacion",),
        credits=3,
        accounts=tuple(
            NewDiscoveredAccount(
                network="tiktok",
                handle=h,
                card={"handle": h, "followers": "1,2 M"},
                followers=1_200_000,
                found_by=("keyword:programacion",),
            )
            for h in handles
        ),
    )


# --------------------------------------------------------------------------------------
# phases
# --------------------------------------------------------------------------------------


def test_a_saved_phase_comes_back_with_its_accounts_in_rank_order(env: Env) -> None:
    saved = env.repo.save_phase(_phase(env))
    found = env.repo.find_phase(
        tenant_id=env.tenant_a,
        brand_id=env.brand_a,
        phase_key="sector",
        seed_signature="sig-1",
        algorithm_version=5,
    )
    assert found is not None and found.id == saved.id and found.is_current
    assert [(a.rank, a.handle) for a in found.accounts] == [(0, "midudev"), (1, "carlosazaustre")]
    assert found.accounts[0].found_by == ("keyword:programacion",)
    assert found.seed["hashtags"] == [{"tag": "programacion", "origin": "profile"}]
    assert (found.credits, found.queries, found.algorithm_version) == (
        3,
        ("tiktok keyword: programacion",),
        5,
    )


def test_a_result_is_only_reused_by_the_algorithm_version_that_computed_it(env: Env) -> None:
    env.repo.save_phase(_phase(env, version=4))
    lookup = dict(
        tenant_id=env.tenant_a, brand_id=env.brand_a, phase_key="sector", seed_signature="sig-1"
    )
    assert env.repo.find_phase(**lookup, algorithm_version=5) is None
    assert env.repo.find_phase(**lookup, algorithm_version=4) is not None
    # and a result older than the caller's TTL is a miss too
    future = datetime.now(UTC) + timedelta(hours=1)
    assert env.repo.find_phase(**lookup, algorithm_version=4, computed_after=future) is None


def test_saving_again_supersedes_the_old_phase_without_editing_it(env: Env) -> None:
    old = env.repo.save_phase(_phase(env, version=4, handles=("viejo",)))
    new = env.repo.save_phase(_phase(env, version=5, handles=("nuevo",)))

    current = env.repo.current_phases(tenant_id=env.tenant_a, brand_id=env.brand_a)
    assert [p.id for p in current] == [new.id]

    kept = env.repo.find_phase(
        tenant_id=env.tenant_a,
        brand_id=env.brand_a,
        phase_key="sector",
        seed_signature="sig-1",
        algorithm_version=4,
    )
    assert kept is not None and kept.id == old.id
    assert not kept.is_current
    assert [a.handle for a in kept.accounts] == ["viejo"]  # the old answer is intact


def test_a_superseded_phase_can_be_promoted_back(env: Env) -> None:
    cucuta = env.repo.save_phase(_phase(env, key="local", signature="cucuta"))
    bogota = env.repo.save_phase(_phase(env, key="local", signature="bogota"))

    promoted = env.repo.promote_phase(tenant_id=env.tenant_a, phase_id=cucuta.id)
    assert promoted.is_current
    current = env.repo.current_phases(tenant_id=env.tenant_a, brand_id=env.brand_a)
    assert [p.id for p in current] == [cucuta.id]
    # promoting what is already current is a no-op
    assert env.repo.promote_phase(tenant_id=env.tenant_a, phase_id=cucuta.id).is_current
    assert bogota.id not in {p.id for p in current}


def test_phase_keys_are_open_so_a_new_phase_needs_no_migration(env: Env) -> None:
    env.repo.save_phase(_phase(env, key="sector"))
    env.repo.save_phase(_phase(env, key="hashtags"))
    keys = {
        p.phase_key for p in env.repo.current_phases(tenant_id=env.tenant_a, brand_id=env.brand_a)
    }
    assert keys == {"sector", "hashtags"}


def test_stale_phases_lists_only_current_phases_from_older_versions(env: Env) -> None:
    env.repo.save_phase(_phase(env, key="sector", version=4))
    env.repo.save_phase(_phase(env, key="sector", version=5))  # supersedes the v4 sector
    stale_local = env.repo.save_phase(_phase(env, key="local", version=4))
    env.repo.save_phase(_phase(env, key="national", version=5))

    def stale_for_this_brand(version: int) -> list[UUID]:
        # tenant-wide by design; the db tenant also holds other tests' brands
        stale = env.repo.stale_phases(tenant_id=env.tenant_a, algorithm_version=version)
        return [p.id for p in stale if p.brand_id == env.brand_a]

    assert stale_for_this_brand(5) == [stale_local.id]
    assert stale_for_this_brand(4) == []


def test_latest_accounts_finds_an_account_a_recompute_dropped(env: Env) -> None:
    env.repo.save_phase(_phase(env, version=4, handles=("midudev", "viejo")))
    env.repo.save_phase(_phase(env, key="local", version=4, handles=("midudev",)))
    env.repo.save_phase(_phase(env, version=5, handles=("nuevo",)))

    found = env.repo.latest_accounts(
        tenant_id=env.tenant_a,
        brand_id=env.brand_a,
        identities=[("tiktok", "viejo"), ("tiktok", "midudev"), ("tiktok", "nunca")],
    )
    assert set(found) == {("tiktok", "viejo"), ("tiktok", "midudev")}
    assert found[("tiktok", "viejo")].card == {"handle": "viejo", "followers": "1,2 M"}
    # the newest phase that saw it wins: midudev was rank 0 in both, the local one is newer
    assert found[("tiktok", "midudev")].rank == 0
    assert (
        env.repo.latest_accounts(
            tenant_id=env.tenant_b, brand_id=env.brand_a, identities=[("tiktok", "viejo")]
        )
        == {}
    )
    assert (
        env.repo.latest_accounts(tenant_id=env.tenant_a, brand_id=env.brand_a, identities=[]) == {}
    )


# --------------------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------------------


def _label_map(env: Env) -> dict[tuple[str, str], str]:
    return {
        (item.network, item.handle): item.label
        for item in env.repo.labels(tenant_id=env.tenant_a, brand_id=env.brand_a)
    }


def test_labels_upsert_clear_and_normalize_the_handle(env: Env) -> None:
    ids = dict(tenant_id=env.tenant_a, brand_id=env.brand_a, network="TikTok")
    env.repo.set_label(**ids, handle="@MiduDev", label="competencia")
    assert _label_map(env) == {("tiktok", "midudev"): "competencia"}

    env.repo.set_label(**ids, handle="midudev", label="referente")  # re-sort = same row
    assert _label_map(env) == {("tiktok", "midudev"): "referente"}

    assert env.repo.clear_label(**ids, handle="MIDUDEV") is True
    assert env.repo.clear_label(**ids, handle="midudev") is False
    assert _label_map(env) == {}


def test_labels_survive_a_recompute_that_drops_the_account(env: Env) -> None:
    env.repo.save_phase(_phase(env, version=4, handles=("midudev",)))
    env.repo.set_label(
        tenant_id=env.tenant_a,
        brand_id=env.brand_a,
        network="tiktok",
        handle="midudev",
        label="detractor",
    )
    env.repo.save_phase(_phase(env, version=5, handles=("otracuenta",)))
    assert _label_map(env) == {("tiktok", "midudev"): "detractor"}


def test_an_unknown_label_is_rejected(env: Env) -> None:
    with pytest.raises(ValueError):
        env.repo.set_label(
            tenant_id=env.tenant_a,
            brand_id=env.brand_a,
            network="tiktok",
            handle="midudev",
            label="amigo",
        )


# --------------------------------------------------------------------------------------
# tenant isolation
# --------------------------------------------------------------------------------------


def test_another_tenant_sees_nothing_and_cannot_write_for_a_foreign_brand(env: Env) -> None:
    saved = env.repo.save_phase(_phase(env))
    env.repo.set_label(
        tenant_id=env.tenant_a,
        brand_id=env.brand_a,
        network="tiktok",
        handle="midudev",
        label="referente",
    )

    b = env.tenant_b
    assert env.repo.current_phases(tenant_id=b, brand_id=env.brand_a) == ()
    assert env.repo.labels(tenant_id=b, brand_id=env.brand_a) == ()
    assert env.repo.stale_phases(tenant_id=b, algorithm_version=99) == ()
    assert (
        env.repo.find_phase(
            tenant_id=b,
            brand_id=env.brand_a,
            phase_key="sector",
            seed_signature="sig-1",
            algorithm_version=5,
        )
        is None
    )
    assert (
        env.repo.clear_label(tenant_id=b, brand_id=env.brand_a, network="tiktok", handle="midudev")
        is False
    )

    with pytest.raises(ValueError):
        env.repo.save_phase(_phase(env, tenant=b, brand=env.brand_a))
    with pytest.raises(ValueError):
        env.repo.set_label(
            tenant_id=b, brand_id=env.brand_a, network="tiktok", handle="x", label="referente"
        )
    with pytest.raises(ValueError):
        env.repo.promote_phase(tenant_id=b, phase_id=saved.id)

    # and A's data is untouched by B's attempts
    assert _label_map(env) == {("tiktok", "midudev"): "referente"}


# --------------------------------------------------------------------------------------
# input validation (no repository needed)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"), [("@MiduDev", "midudev"), ("  midu.dev ", "midu.dev")]
)
def test_normalize_handle(raw: str, expected: str) -> None:
    assert normalize_handle(raw) == expected


@pytest.mark.parametrize("raw", ["", "@", "  @ "])
def test_normalize_handle_rejects_empty(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_handle(raw)


@pytest.mark.parametrize(
    "seed",
    [
        "not an object",
        {"hashtags": "cucuta"},
        {"hashtags": ["cucuta"]},  # a bare string: its origin would be lost
        {"hashtags": [{"tag": "cucuta"}]},
        {"hashtags": [{"tag": "", "origin": "profile"}]},
        {"when": datetime.now(UTC)},  # not JSON
    ],
)
def test_validate_seed_rejects_bad_shapes(seed: object) -> None:
    with pytest.raises(ValueError):
        validate_seed(seed)


def test_a_phase_cannot_list_the_same_account_twice() -> None:
    account = NewDiscoveredAccount(network="tiktok", handle="midudev", card={})
    duplicate = NewDiscoveredAccount(network="TikTok", handle="@MiduDev", card={})
    with pytest.raises(ValueError):
        NewDiscoveryPhase(
            tenant_id=TENANT_A,
            brand_id=uuid4(),
            phase_key="sector",
            algorithm_version=5,
            seed_signature="s",
            seed={"hashtags": []},
            accounts=(account, duplicate),
        )
