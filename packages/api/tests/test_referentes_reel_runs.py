"""The persistent reels run (`qualify_api.referentes.reel_runs`, ADR 42 R4, m-24854848),
offline: the store is `MemoryReelRunStore`, the referentes `MemoryReferentesRepository`,
and the vendor (lists, transcripts) and Claude are scripted fakes that count their calls —
nothing here can reach ScrapeCreators or Anthropic.

What it pins, per the ticket's acceptance criteria:
1. without a brief (or without a key) the provider is never called;
2. with Claude down, a second run pays no list and no transcript again — only the review;
3. two businesses that follow the same account make ONE read (sequentially, and while
   the other holds the refresh lock);
4. every stored verdict carries `model_id` and `prompt_version` (and its effort);
plus `view()` only reads, `enqueue_run()` is idempotent, the 24 h / 72 h refresh, a gate
refusal and the ADR 44 analysis hook. Tenant isolation over Postgres is
`test_referentes_reel_runs_db.py`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.claude_tools import CallStats, ModelConfig
from qualify_api.referentes import (
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    reels,
    reels_ai,
)
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_store import (
    STATUS_BUDGET_STOPPED,
    STATUS_CHECK_FAILED,
    STATUS_OK,
    STATUS_QUEUED,
    MemoryReelRunStore,
)
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview
from qualify_api.vendors import scrapecreators as sc

NOW = 1_800_000_000.0
DAY = 24 * 3600
BRIEF = review_ai.BrandBrief(handle="burgerco", rubro=("hamburguesería",))
TENANT_A = UUID("a0000000-0000-4000-8000-0000000000a1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000b2")


def _reel(network: str, handle: str, reel_id: str, days_ago: float, views: int, caption: str):
    return {
        "id": reel_id,
        "network": network,
        "handle": handle,
        "url": f"https://www.instagram.com/reel/{reel_id}/",
        "caption": caption,
        "cover": "",
        "takenAt": NOW - days_ago * DAY,
        "views": views,
        "likes": views // 10,
        "comments": 1,
        "shares": None,
        "saves": None,
        "seconds": 12,
        "sound": "Audio original",
        "video": f"https://scontent.cdninstagram.com/{reel_id}.mp4",
        **({"captionUrl": f"https://v.tiktokcdn.com/{reel_id}.vtt"} if network == "tiktok" else {}),
    }


FEEDS: dict[str, list[dict[str, Any]]] = {
    "foodie": [
        _reel("instagram", "foodie", "F1", 2, 9_000, "la smash burger del centro"),
        _reel("instagram", "foodie", "F2", 3, 99_000, "mi rutina de maquillaje"),
        _reel("instagram", "foodie", "F3", 20, 5_000, "probando hamburguesas"),
    ],
    "vecino": [_reel("tiktok", "vecino", "V1", 1, 1_500, "papas y burger")],
}


@dataclass
class Vendor:
    """The paid side, scripted: list reads and transcripts, counted."""

    lists: list[tuple[str, str, int]] = field(default_factory=list)
    transcripts: list[str] = field(default_factory=list)
    blocked: bool = False

    def fetch(
        self, network: str, handle: str, *, since: float, client: Any, max_pages: int
    ) -> list[dict[str, Any]]:
        if self.blocked:
            raise sc.ScrapeCreatorsBlocked("floor", reason="below_floor")
        self.lists.append((network, handle, max_pages))
        return [dict(r) for r in FEEDS[handle]]

    def transcribe(self, reel: dict[str, Any], client: Any) -> str:
        self.transcripts.append(f"{reel['network']}:{reel['id']}")
        return f"dicen {reel['caption']}"


@dataclass
class Claude:
    """The rubro check, scripted: up or down, counted."""

    down: bool = False
    asked: list[list[ReelToReview]] = field(default_factory=list)

    def review(self, brief: Any, batch: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
        self.asked.append(list(batch))
        if self.down:
            raise RuntimeError("anthropic is down")
        answers = [
            ReelReview(
                id=r.id,
                fits="maquillaje" not in r.caption,
                reason=f"ok {r.id}",
                format="receta",
                hook="pregunta",
                affinity="producto" if "maquillaje" not in r.caption else "otro",
            )
            for r in batch
        ]
        return answers, CallStats(reels_ai.REVIEW_MODEL, None, 1000, 100)


class Clock:
    def __init__(self, moment: float = NOW) -> None:
        self.moment = moment

    def __call__(self) -> float:
        return self.moment


def _brand(repo: MemoryReferentesRepository, tenant: UUID, *, seed: bool = True) -> UUID:
    """A brand of `tenant` whose referentes are @foodie (Instagram) and @vecino (TikTok)."""
    brand = uuid4()
    repo.add_brand(tenant_id=tenant, brand_id=brand)
    repo.save_phase(
        NewDiscoveryPhase(
            tenant_id=tenant,
            brand_id=brand,
            phase_key="sector",
            algorithm_version=1,
            seed_signature="s",
            seed={"handle": "burgerco", "terms": ["hamburguesería"], "hashtags": []}
            if seed
            else {},
            title="Sector",
            accounts=(
                NewDiscoveredAccount(
                    network="instagram", handle="foodie", card={"kind": "creador"}
                ),
                NewDiscoveredAccount(network="tiktok", handle="vecino", card={"kind": "marca"}),
            ),
        )
    )
    for network, handle in (("instagram", "foodie"), ("tiktok", "vecino")):
        repo.set_label(
            tenant_id=tenant,
            brand_id=brand,
            network=network,
            handle=handle,
            label="referente",
            labeled_by=None,
        )
    return brand


@pytest.fixture
def world() -> tuple[MemoryReelRunStore, MemoryReferentesRepository, Vendor, Claude, Clock]:
    return MemoryReelRunStore(), MemoryReferentesRepository(), Vendor(), Claude(), Clock()


def _run(
    tenant: UUID,
    brand: UUID,
    world: Any,
    *,
    trigger: str = "weekly",
    retry: bool = False,
    **kwargs: Any,
) -> rr.RunOutcome:
    store, repo, vendor, claude, clock = world
    queued = rr.enqueue_run(tenant, brand, trigger, store=store, clock=clock, retry=retry)
    kwargs.setdefault("brief", lambda t, b: BRIEF)
    kwargs.setdefault("api_key", "k")
    kwargs.setdefault("sleep", lambda seconds: None)
    return rr.run(
        tenant,
        queued.id,
        store=store,
        repository=repo,
        fetch=vendor.fetch,
        transcribe_fetch=vendor.transcribe,
        review=claude.review,
        clock=clock,
        **kwargs,
    )


# --------------------------------------------------------------------------------------
# criterion 1 — no brief / no key: no call to the provider
# --------------------------------------------------------------------------------------


def test_without_a_brief_the_provider_is_never_called(world: Any) -> None:
    store, repo, vendor, claude, _ = world
    brand = _brand(repo, TENANT_A, seed=False)  # the brand never ran its referentes search
    # the real brief builder (moved to packages/api by R4) finds nothing to say
    outcome = _run(TENANT_A, brand, world, brief=None)
    assert outcome.status == STATUS_CHECK_FAILED and outcome.check == rr.CHECK_NO_BRIEF
    assert vendor.lists == [] and vendor.transcripts == [] and claude.asked == []
    assert store.accounts == {} and store.reels == {}  # nothing read, nothing locked
    assert store.runs[outcome.run_id].status == STATUS_CHECK_FAILED


def test_without_an_anthropic_key_the_provider_is_never_called(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, repo, vendor, claude, _ = world
    brand = _brand(repo, TENANT_A)
    monkeypatch.setattr(reels, "_env_key", lambda: None)
    outcome = _run(TENANT_A, brand, world, api_key=None)
    assert outcome.status == STATUS_CHECK_FAILED and outcome.check == rr.CHECK_UNAVAILABLE
    assert vendor.lists == [] and vendor.transcripts == [] and claude.asked == []


# --------------------------------------------------------------------------------------
# criterion 2 — Claude down: the second run pays no list again
# --------------------------------------------------------------------------------------


def test_with_claude_down_a_second_run_does_not_pay_the_lists_again(world: Any) -> None:
    store, repo, vendor, claude, clock = world
    brand = _brand(repo, TENANT_A)
    claude.down = True
    first = _run(TENANT_A, brand, world)
    assert first.status == STATUS_CHECK_FAILED and first.check == rr.CHECK_UNAVAILABLE
    paid_lists, paid_transcripts = list(vendor.lists), list(vendor.transcripts)
    assert len(paid_lists) == 2 and paid_transcripts  # both accounts read, transcripts paid
    # nothing deleted: the reels, their transcripts and the accounts' freshness stay
    assert {k[1] for k in store.reels} == {"F1", "F2", "F3", "V1"}
    assert all(r.transcript_at is not None for r in store.reels.values())
    assert store.verdict_rows == {} and store.idea_rows == []

    claude.down = False
    clock.moment += 3600  # «Intentar de nuevo» an hour later: the same run, re-queued
    retried = _run(TENANT_A, brand, world, retry=True)
    assert retried.run_id == first.run_id and retried.status == STATUS_OK
    assert vendor.lists == paid_lists and vendor.transcripts == paid_transcripts  # no new pay
    assert len(claude.asked) == 2 and retried.ideas == 3  # only the review was redone
    # another trigger the same day reads nothing either: the accounts are fresh
    manual = _run(TENANT_A, brand, world, trigger="manual")
    assert manual.status == STATUS_OK and vendor.lists == paid_lists
    assert manual.verdicts_new == 0 and manual.verdicts_reused == 4  # no Claude call either
    assert len(claude.asked) == 2


# --------------------------------------------------------------------------------------
# criterion 3 — two businesses, one referente, one read
# --------------------------------------------------------------------------------------


def test_two_businesses_with_the_same_referente_make_a_single_read(world: Any) -> None:
    store, repo, vendor, _, _ = world
    brand_a, brand_b = _brand(repo, TENANT_A), _brand(repo, TENANT_B)
    assert _run(TENANT_A, brand_a, world).status == STATUS_OK
    assert _run(TENANT_B, brand_b, world).status == STATUS_OK
    assert vendor.lists == [("instagram", "foodie", 4), ("tiktok", "vecino", 4)]
    assert len(vendor.transcripts) == 4  # each reel transcribed once, for both businesses
    # each business has its own verdicts and ideas
    owners = {(tenant, brand) for tenant, brand, _ in store.verdict_rows.values()}
    assert owners == {(TENANT_A, brand_a), (TENANT_B, brand_b)}


def test_a_business_waits_for_the_other_ones_refresh_instead_of_reading_again(
    world: Any,
) -> None:
    store, repo, vendor, _, clock = world
    brand_b = _brand(repo, TENANT_B)
    now = datetime.fromtimestamp(NOW, UTC)
    # business A is refreshing @foodie right now (its lock is held)
    lock_a = now + timedelta(minutes=10)
    assert store.try_lock_account(TENANT_A, "instagram", "foodie", now=now, until=lock_a)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        # while B waits, A finishes its read: the account is fresh and unlocked
        sleeps.append(seconds)
        store.upsert_reels(
            TENANT_A,
            [rr._public_reel(r, now) for r in FEEDS["foodie"]],
        )
        store.finish_account(
            TENANT_A,
            "instagram",
            "foodie",
            now=now,
            status="ok",
            page1=True,
            full_walk_days=30,
            lock_until=lock_a,
        )

    outcome = _run(TENANT_B, brand_b, world, sleep=sleep)
    assert outcome.status == STATUS_OK and sleeps
    assert vendor.lists == [("tiktok", "vecino", 4)]  # @foodie was not read a second time
    assert outcome.ideas == 3


class _RacingStore(MemoryReelRunStore):
    """Between this run's freshness check and its lock, another business's refresh of
    @foodie finishes (and releases its own lock)."""

    def try_lock_account(self, tenant_id: UUID, network: str, handle: str, **kw: Any) -> bool:
        if handle == "foodie" and self.account(tenant_id, network, handle) is None:
            now = kw["now"]
            other = now + timedelta(minutes=1)
            assert super().try_lock_account(TENANT_A, network, handle, now=now, until=other)
            self.upsert_reels(TENANT_A, [rr._public_reel(r, now) for r in FEEDS["foodie"]])
            self.finish_account(
                TENANT_A,
                network,
                handle,
                now=now,
                status="ok",
                page1=True,
                full_walk_days=30,
                lock_until=other,
            )
        return super().try_lock_account(tenant_id, network, handle, **kw)


def test_a_refresh_finished_just_before_the_lock_is_not_read_again(world: Any) -> None:
    _, repo, vendor, claude, clock = world
    store = _RacingStore()
    brand_b = _brand(repo, TENANT_B)
    outcome = _run(TENANT_B, brand_b, (store, repo, vendor, claude, clock))
    assert outcome.status == STATUS_OK
    assert vendor.lists == [("tiktok", "vecino", 4)]  # freshness re-checked under the lock
    assert store.account(TENANT_B, "instagram", "foodie").refresh_lock_until is None


def test_a_refresh_never_releases_a_lock_another_run_took_since(world: Any) -> None:
    store = world[0]
    now = datetime.fromtimestamp(NOW, UTC)
    mine, theirs = now + timedelta(minutes=10), now + timedelta(minutes=30)
    assert store.try_lock_account(TENANT_A, "instagram", "x", now=now, until=mine)
    # mine expired; another run took the account
    later = mine + timedelta(seconds=1)
    assert store.try_lock_account(TENANT_B, "instagram", "x", now=later, until=theirs)
    store.finish_account(TENANT_A, "instagram", "x", now=later, status="ok", lock_until=mine)
    store.release_account(TENANT_A, "instagram", "x", lock_until=mine)
    assert store.account(TENANT_A, "instagram", "x").refresh_lock_until == theirs


def test_a_retry_with_claude_down_pays_no_new_transcript(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the most viewed `MAX_PAID_TRANSCRIPTS` Instagram candidates are eligible,
    transcribed or not: a retry never reaches further down the ranking."""
    _, repo, vendor, claude, clock = world
    monkeypatch.setattr(reels, "MAX_PAID_TRANSCRIPTS", 2)
    brand = _brand(repo, TENANT_A)
    claude.down = True
    assert _run(TENANT_A, brand, world).status == STATUS_CHECK_FAILED
    paid = list(vendor.transcripts)
    assert {"instagram:F2", "instagram:F1"} <= set(paid) and "instagram:F3" not in paid
    for _ in range(2):
        clock.moment += 600
        again = _run(TENANT_A, brand, world, retry=True)
        assert again.status == STATUS_CHECK_FAILED and again.transcripts_paid == 0
    assert vendor.transcripts == paid


# --------------------------------------------------------------------------------------
# criterion 4 — provenance on every verdict; redone only when brief or input changes
# --------------------------------------------------------------------------------------


def test_every_stored_verdict_has_its_model_and_prompt_version(world: Any) -> None:
    store, repo, _, claude, clock = world
    brand = _brand(repo, TENANT_A)
    outcome = _run(TENANT_A, brand, world)
    verdicts = [v for _, _, v in store.verdict_rows.values()]
    assert len(verdicts) == 4 and outcome.verdicts_new == 4
    for verdict in verdicts:
        assert verdict.model_id == reels_ai.REVIEW_MODEL
        assert verdict.prompt_version == reels_ai.REVIEW_PROMPT_VERSION
        assert verdict.prompt_version.startswith("v")
        assert verdict.effort == reels_ai.REVIEW_EFFORT
        assert verdict.brief_hash == rr.brief_hash(BRIEF) and verdict.input_hash
        assert verdict.cost_usd > 0
    assert store.runs[outcome.run_id].cost_usd == sum(v.cost_usd for v in verdicts)

    # a week later the lists are read again, unchanged reels are not judged again…
    clock.moment += 8 * DAY
    claude.asked.clear()
    again = _run(TENANT_A, brand, world)
    assert again.verdicts_reused >= 1 and all(
        r.id not in {"instagram:F1", "instagram:F3"} for b in claude.asked for r in b
    )
    # …but a new brief is a new verdict for every reel
    clock.moment += 1
    other = review_ai.BrandBrief(handle="burgerco", rubro=("pizzería",))
    claude.asked.clear()
    changed = _run(TENANT_A, brand, world, trigger="manual", brief=lambda t, b: other)
    assert changed.verdicts_reused == 0 and sum(len(b) for b in claude.asked) == 4


def test_the_input_hash_follows_what_the_model_reads() -> None:
    config = ModelConfig(reels_ai.REVIEW_MODEL, reels_ai.REVIEW_EFFORT)
    item = ReelToReview(id="instagram:A", network="instagram", handle="x", caption="hola")
    same = ReelToReview(id="other-id", network="instagram", handle="x", caption="hola")
    assert rr.input_hash(item, config) == rr.input_hash(same, config)  # the id is ours
    said = ReelToReview(
        id="instagram:A", network="instagram", handle="x", caption="hola", transcript="burger"
    )
    assert rr.input_hash(item, config) != rr.input_hash(said, config)
    assert rr.input_hash(item, config) != rr.input_hash(item, ModelConfig("other", "low"))


# --------------------------------------------------------------------------------------
# view, enqueue_run, freshness, the gate, the analysis hook
# --------------------------------------------------------------------------------------


def test_view_only_reads(world: Any) -> None:
    store, repo, vendor, claude, _ = world
    brand = _brand(repo, TENANT_A)
    empty = rr.view(TENANT_A, brand, store=store)
    assert empty.latest is None and empty.shown is None and empty.ideas == []
    _run(TENANT_A, brand, world)
    calls, writes = (len(vendor.lists), len(vendor.transcripts), len(claude.asked)), store.writes
    seen = rr.view(TENANT_A, brand, store=store)
    assert store.writes == writes
    assert (len(vendor.lists), len(vendor.transcripts), len(claude.asked)) == calls
    assert seen.shown is not None and seen.shown.status == STATUS_OK
    assert [i.reel.reel_id for i in seen.ideas] == ["F1", "F3", "V1"]  # by views; make-up out
    assert seen.ideas[0].verdict is not None and seen.ideas[0].reel.transcript
    assert seen.latest.accounts_done == seen.latest.accounts_total == 2
    # another tenant sees nothing of it
    assert rr.view(TENANT_B, brand, store=store).shown is None


def test_view_judges_the_retry_and_replicar_at_the_callers_clock(world: Any) -> None:
    """The screen reads at one moment (`reels_discovery.load_ideas`), so the view judges at
    the `now` it is handed — not at the machine's clock — when a failed check is retried
    and whether an idea's CDN link still serves «Replicar»."""
    store, repo, _, claude, clock = world
    brand = _brand(repo, TENANT_A)
    ok = _run(TENANT_A, brand, world)  # read at NOW: the video links are fresh then
    claude.down = True
    clock.moment += 60
    other = review_ai.BrandBrief(handle="burgerco", rubro=("pizzería",))  # new verdicts
    failed = _run(TENANT_A, brand, world, trigger="manual", brief=lambda t, b: other)
    assert failed.status == STATUS_CHECK_FAILED
    ended = datetime.fromtimestamp(clock.moment, UTC)

    def replicable(seen: rr.RunView) -> list[bool]:
        # the Instagram ideas: their links are on Instagram's CDN (this file's TikTok one
        # is not on TikTok's, so it never replicates from its link)
        return [i.can_replicate for i in seen.ideas if i.reel.network == "instagram"]

    soon = rr.view(TENANT_A, brand, store=store, now=ended + timedelta(hours=1))
    assert soon.next_retry_at == ended + rr.CHECK_RETRY_AFTER
    assert soon.shown is not None and soon.shown.id == ok.run_id
    assert replicable(soon) == [True, True]  # links read an hour ago

    later = rr.view(TENANT_A, brand, store=store, now=ended + rr.CHECK_RETRY_WITHIN)
    assert later.next_retry_at is None  # an old day's check is never retried
    assert replicable(later) == [False, False]  # links past their 20 h


def test_enqueue_run_is_idempotent(world: Any) -> None:
    store, repo, _, _, clock = world
    brand = _brand(repo, TENANT_A)
    first = rr.enqueue_run(TENANT_A, brand, "manual", store=store, clock=clock)
    second = rr.enqueue_run(TENANT_A, brand, "manual", store=store, clock=clock)
    assert first.id == second.id and first.status == STATUS_QUEUED and len(store.runs) == 1
    weekly = rr.enqueue_run(TENANT_A, brand, "weekly", store=store, clock=clock)
    assert weekly.id != first.id and weekly.days == 30
    deep = rr.enqueue_run(TENANT_A, brand, "operator_90d", store=store, clock=clock)
    assert deep.days == 90
    # a finished run is not re-queued, not even with retry
    done = _run(TENANT_A, brand, world, trigger="manual")
    assert done.status == STATUS_OK
    again = rr.enqueue_run(TENANT_A, brand, "manual", store=store, clock=clock, retry=True)
    assert again.status == STATUS_OK
    # a run already taken by a worker is left alone
    assert not rr.run(TENANT_A, done.run_id, store=store).ran
    with pytest.raises(ValueError):
        rr.enqueue_run(TENANT_A, brand, "hourly", store=store, clock=clock)


def test_page_one_after_24_hours_and_the_whole_walk_after_72(world: Any) -> None:
    _, repo, vendor, _, clock = world
    brand = _brand(repo, TENANT_A)
    _run(TENANT_A, brand, world)  # cold: the whole walk
    assert [p for *_, p in vendor.lists] == [4, 4]
    clock.moment += 23 * 3600
    _run(TENANT_A, brand, world, trigger="manual")  # fresh: nothing
    assert len(vendor.lists) == 2
    clock.moment += 2 * 3600  # 25 h after the walk: page 1 only
    _run(TENANT_A, brand, world, trigger="operator_90d")
    assert [p for *_, p in vendor.lists[2:]] == [12, 12]  # …unless deeper than covered
    clock.moment += 25 * 3600  # the 90-day walk covers the month: page 1 only
    vendor.lists.clear()
    rr.enqueue_run(TENANT_A, brand, "weekly", store=world[0], clock=clock)
    _run(TENANT_A, brand, world, trigger="weekly")
    assert [p for *_, p in vendor.lists] == [1, 1]
    clock.moment += 73 * 3600  # the walk is older than 72 h: the whole walk again
    vendor.lists.clear()
    _run(TENANT_A, brand, world, trigger="manual")
    assert [p for *_, p in vendor.lists] == [4, 4]


def test_a_gate_refusal_stops_the_run_and_frees_the_lock(world: Any) -> None:
    store, repo, vendor, claude, _ = world
    brand = _brand(repo, TENANT_A)
    vendor.blocked = True
    outcome = _run(TENANT_A, brand, world)
    assert outcome.status == STATUS_BUDGET_STOPPED and claude.asked == []
    state = store.account(TENANT_A, "instagram", "foodie")
    assert state is not None and state.refresh_lock_until is None and state.page1_at is None


def test_the_analysis_of_the_ideas_adds_its_cost_and_never_fails_the_run(world: Any) -> None:
    store, repo, _, _, clock = world
    brand = _brand(repo, TENANT_A)
    got: list[Any] = []

    def analyze(tenant: UUID, brand_id: UUID, run_id: UUID, sources: Any) -> Decimal:
        got.append((tenant, brand_id, run_id, list(sources)))
        return Decimal("0.0165")

    outcome = _run(TENANT_A, brand, world, analyze=analyze)
    ((tenant, brand_id, run_id, sources),) = got
    assert (tenant, brand_id, run_id) == (TENANT_A, brand, outcome.run_id)
    assert [s.post_id for s in sources] == ["F1", "F3", "V1"]
    assert sources[0].video_url.endswith("F1.mp4") and sources[0].transcript
    record = store.runs[outcome.run_id]
    verdict_cost = sum(v.cost_usd for _, _, v in store.verdict_rows.values())
    assert record.cost_usd == verdict_cost + Decimal("0.0165")

    def broken(*_: Any) -> Decimal:
        raise RuntimeError("analysis down")

    clock.moment += 1
    failed = _run(TENANT_A, brand, world, trigger="manual", analyze=broken)
    assert failed.status == STATUS_OK and store.runs[failed.run_id].status == STATUS_OK


def test_the_run_service_never_imports_the_reflex_app() -> None:
    import inspect

    from qualify_api.referentes import brand_brief, reel_store

    for module in (rr, reel_store, brand_brief):
        source = inspect.getsource(module)
        assert "from Qualify" not in source and "import Qualify" not in source


def test_the_doors_are_reachable_from_the_reels_service() -> None:
    assert reels.run is rr.run and reels.view is rr.view and reels.enqueue_run is rr.enqueue_run


def test_the_prompt_version_follows_the_prompt_the_clips_and_the_fits_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored verdict is reused only under the prompt, clip limits and `fits` rule it
    was made with: changing any of them is a new `prompt_version`."""
    base = reels_ai._prompt_version()
    assert base == reels_ai.REVIEW_PROMPT_VERSION
    for name, value in (
        ("REVIEW_SYSTEM", reels_ai.REVIEW_SYSTEM + " Nueva regla."),
        ("FITS", frozenset({"producto"})),
        ("CAPTION_CHARS", reels_ai.CAPTION_CHARS + 1),
        ("TRANSCRIPT_CHARS", reels_ai.TRANSCRIPT_CHARS - 1),
        ("REASON_CHARS", reels_ai.REASON_CHARS + 1),
        ("REVIEW_BATCH", reels_ai.REVIEW_BATCH - 1),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(reels_ai, name, value)
            assert reels_ai._prompt_version() != base, name
    assert reels_ai._prompt_version() == base


def test_the_refresh_lock_outlasts_the_walk() -> None:
    assert rr.lock_seconds(1) == rr.LOCK_SECONDS
    deep = reels.reel_pages(reels.QUARTER_DAYS)
    assert rr.lock_seconds(deep) >= deep * 2 * rr.READ_TIMEOUT_SECONDS + 60
    assert rr.lock_seconds(100) > rr.LOCK_SECONDS  # a deeper walk grows the lock


def test_the_timed_transcript_is_stored_and_reaches_the_analysis(world: Any) -> None:
    """VE-04b (m-24921057): the stretches the listing's transcript call already brought
    are stored on the reel — verbatim, music heard as "ah" included — and handed to the
    analysis with no new call; a second run reads them back from the store."""
    store, repo, vendor, _, clock = world
    brand = _brand(repo, TENANT_A)

    def timed(reel: dict[str, Any], client: Any) -> sc.Transcript:
        vendor.transcripts.append(f"{reel['network']}:{reel['id']}")
        return sc.Transcript(
            text=f"dicen {reel['caption']}",
            segments=(sc.Segment(0.0, 1.5, "dicen"), sc.Segment(10.749, 12.829, "ah")),
            source=sc.TRANSCRIPT_VENDOR_STT,
        )

    vendor.transcribe = timed  # the run's transcript fetcher, now a timed one
    got: list[list[Any]] = []

    def analyze(tenant: UUID, brand_id: UUID, run_id: UUID, sources: Any) -> Decimal:
        got.append(list(sources))
        return Decimal("0")

    _run(TENANT_A, brand, world, analyze=analyze)
    paid = list(vendor.transcripts)
    assert paid  # the listing paid its transcripts once
    stored = store.reels[("instagram", "F1")]
    assert [s.text for s in stored.transcript_segments or ()] == ["dicen", "ah"]
    expected = [(0.0, 1.5, "dicen"), (10.749, 12.829, "ah")]
    assert [(s.start_s, s.end_s, s.text) for s in got[0][0].transcript_segments] == expected
    clock.moment += 1
    _run(TENANT_A, brand, world, trigger="manual", analyze=analyze)
    assert vendor.transcripts == paid  # stored: nothing paid again
    assert [(s.start_s, s.end_s, s.text) for s in got[1][0].transcript_segments] == expected
