"""`refresh_referentes` — the `just refresh-referentes` command — over the in-memory
repository and a fake vendor run. Fully offline: no tenant listing, no credits."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_api.referentes import MemoryReferentesRepository

from . import creator_discovery as cd
from . import referentes_provider as rp
from . import refresh_referentes as cli

TENANT = UUID("5e5e0000-0000-4000-8000-0000000000b3")


def _candidate(username: str) -> cd.Candidate:
    return cd.Candidate(network="tiktok", username=username, followers=1000)


def _seed() -> cd.DiscoverySeed:
    return cd.DiscoverySeed(handle="marca", niches=("food",), country_code="CO", city="Cúcuta")


@pytest.fixture
def two_stale_brands(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID]:
    repo = MemoryReferentesRepository()
    monkeypatch.setattr(rp, "REPOSITORY", repo)
    brands = (uuid4(), uuid4())
    current = cd.PHASED_PLAN_VERSION
    monkeypatch.setattr(cd, "PHASED_PLAN_VERSION", current - 1)
    for brand, credits in zip(brands, (5, 30), strict=True):
        repo.add_brand(tenant_id=TENANT, brand_id=brand)
        result = cd.PhaseResult(
            key="sector", title="t", accounts=[_candidate("vieja")], credits=credits
        )
        rp.save_phase(TENANT, brand, "sector", _seed(), result, cd.phase_to_dict(result))
    monkeypatch.setattr(cd, "PHASED_PLAN_VERSION", current)
    return brands


class _FakeRun:
    def __init__(self, credits: int = 4) -> None:
        self.calls: list[list[str]] = []
        self.credits = credits

    def __call__(
        self, seed: cd.DiscoverySeed, keys: list[str], tenant_id: object
    ) -> list[cd.PhaseResult]:
        self.calls.append(keys)
        return [
            cd.PhaseResult(key=k, title=k, accounts=[_candidate("nueva")], credits=self.credits)
            for k in keys
        ]


def _main(args: list[str], run: _FakeRun) -> tuple[int, str]:
    lines: list[str] = []
    code = cli.main(args, tenants=lambda: [TENANT], run=run, out=lines.append)
    return code, "\n".join(lines)


def test_dry_run_reports_the_plan_and_spends_nothing(two_stale_brands: tuple[UUID, UUID]) -> None:
    run = _FakeRun()
    code, output = _main(["--dry-run"], run)
    assert code == 0
    assert run.calls == []
    assert "2 marca(s)" in output and "~35 créditos" in output
    assert f"v{cd.PHASED_PLAN_VERSION - 1} -> v{cd.PHASED_PLAN_VERSION}" in output
    assert len(rp.plan_refresh(TENANT)) == 2  # still stale


def test_a_run_respects_the_credit_budget(two_stale_brands: tuple[UUID, UUID]) -> None:
    cheap, expensive = two_stale_brands
    run = _FakeRun(credits=4)
    code, output = _main(["--max-credits", "20"], run)
    assert code == 0
    assert run.calls == [["sector"]]  # only the brand that fits the budget ran
    assert "omitida (tope de créditos)" in output
    (left,) = rp.plan_refresh(TENANT)
    assert left.brand_id == expensive


def test_brand_filter_and_nothing_to_do(two_stale_brands: tuple[UUID, UUID]) -> None:
    cheap, _expensive = two_stale_brands
    run = _FakeRun()
    _main(["--brand", str(cheap)], run)
    assert run.calls == [["sector"]]
    _main(["--brand", str(cheap)], run)  # already current: nothing runs
    assert run.calls == [["sector"]]

    code, output = _main(["--brand", str(uuid4())], run)
    assert code == 0 and "Todo al día" in output
