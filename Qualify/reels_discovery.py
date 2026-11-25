"""«Ideas para tus reels» — the Reflex app's door to the stored ideas (ADR 42 R7,
m-24854854; «Descubrir reels» in the code).

Opening the screen never spends (ADR 42 §2.1, decision 1). Nothing here calls
ScrapeCreators or the model: the persistent run (`qualify_api.referentes.reel_runs.run`,
the `reels-worker`'s) is the only door that pays, and the screen reads what it stored:

- `stored_ideas` — the latest run and the latest `ok` one with its ideas
  (`reel_runs.view`), how many accounts the brand follows, whether something says what it
  sells, the business's zone and the stored reels each idea's lift is measured against.
  Postgres only, never a write. RF-02 (m-25119460): the ideas and one page of «Más reels
  revisados» come narrowed by the owner's filters through RF-01's read
  (`reviewed_reels.reviewed_reels`) — filtering reads only what is stored, never pays;
- `more_reviewed` — the next page of «Más reels revisados», the same read;
- RF-05 (m-25119465): `competitor_rows` (the panel over the filter bar, Postgres only),
  `choose_competitors` (which 6 the Monday run reads, the brand's own labels) and
  `read_competitor_now` («Ver sus reels ahora»: it only QUEUES the read, inside the daily
  cap — the reels-worker pays);
- `mark_opened` — the brand's «last opened» signal the worker's 14-day inactivity rule
  reads (decided 2026-11-04); it never raises and never delays the screen;
- `ensure_first_run` — option A, confirmed by the founder on 2026-11-04: a brand with
  accounts and a brief but no run at all gets its first run queued when the owner
  opens the screen (the worker pays for it, not the screen), and the screen says it is
  being prepared. One call, in `load_ideas`.

What else stays here is what only the app knows: the doors of the brand brief (the
referentes store, the Brand Kit form, the catalog rows) and the signed cover path a card
shows (`cover_path`, `avatar_proxy.reel_cover_path`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import brand_brief as shared_brief
from qualify_api.referentes import competitors, reel_analysis, reel_runs, reels, reviewed_reels
from qualify_api.referentes.reel_analysis_types import AnalysisRef, ReelSource
from qualify_api.referentes.reel_store import ReelRunStore
from qualify_api.referentes.reviewed_reels import ReelFilters, ReviewedReelsStore

from . import reels_competitors_vm, reels_filters_vm, reels_ideas_vm, referentes_provider
from .avatar_proxy import reel_cover_path

logger = logging.getLogger(__name__)

BRIEF_HASHTAGS = shared_brief.BRIEF_HASHTAGS
KitLoader = Callable[[UUID, UUID], Any]
ProductsLoader = Callable[[UUID, UUID], Sequence[dict[str, str]]]


def _kit_form(tenant_id: UUID, brand_id: UUID) -> Any:
    from .creative_provider import load_kit_form  # the Brand Kit's door; lazy: heavy

    return load_kit_form(tenant_id, brand_id)


def _products(tenant_id: UUID, brand_id: UUID) -> Sequence[dict[str, str]]:
    from .creative_provider import catalog_products

    return catalog_products(tenant_id, brand_id)


def brand_brief(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    repository: Any = None,
    kit_form: KitLoader | None = None,
    products: ProductsLoader | None = None,
) -> review_ai.BrandBrief | None:
    """What the rubro check reads about the brand — built by the service
    (`qualify_api.referentes.brand_brief`, moved there by ADR 42 R4, m-24854848, so the
    `reels-worker` can build it alone), with the app's own doors: the referentes store,
    the Brand Kit form and the catalog rows. Unchanged for the screen."""
    return shared_brief.brand_brief(
        tenant_id,
        brand_id,
        repository=repository or referentes_provider.REPOSITORY,
        # resolved here, not in the signature, so a test can swap the module's doors
        kit_form=kit_form or _kit_form,
        products=products or _products,
    )


def cover_path(reel: dict[str, Any]) -> str:
    """The backend path a card shows a cover from (`avatar_proxy.reel_cover`), signed:
    the route serves only the covers this module handed out."""
    if not reel.get("cover"):
        return ""
    return reel_cover_path(reel["network"], str(reel["id"]), str(reel["cover"]))


# --------------------------------------------------------------------------------------
# the stored ideas (ADR 42 R7) — Postgres only
# --------------------------------------------------------------------------------------


def has_brief(tenant_id: UUID, brand_id: UUID, *, repository: Any = None) -> bool:
    """Whether something says what the brand sells — the same answer the run gets before
    it pays (`brand_brief` is None only without a search seed), so the Brand Kit and the
    catalog are not loaded just to ask."""
    brief = brand_brief(
        tenant_id,
        brand_id,
        repository=repository,
        kit_form=lambda tenant, brand: None,
        products=lambda tenant, brand: (),
    )
    return brief is not None


def _business_timezone(tenant_id: UUID) -> str:
    """The business's IANA zone (`tenants.timezone`), the planner's door."""
    from qualify_api.planner.composition import tenant_timezone  # lazy: heavy

    return tenant_timezone(tenant_id)


def stored_ideas(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    store: ReelRunStore | None = None,
    repository: Any = None,
    timezone: str | None = None,
    now: datetime | None = None,
    filters: ReelFilters | None = None,
    library: ReviewedReelsStore | None = None,
) -> reels_ideas_vm.StoredIdeas:
    """Everything «Ideas para tus reels» shows, read from Postgres — never the vendor,
    never the model, never a write. `now` is the moment the screen reads at (the run's
    retry and «Replicar» are judged at it); the real clock when not given. `filters`
    (RF-02) narrow the ideas and «Más reels revisados» (RF-01's read, first page); the
    run's state — which screen, its notice — never depends on them."""
    runs = store or reel_runs.default_store()
    repo = repository or referentes_provider.REPOSITORY
    # RF-13: one list of `LIST_PAGE` under the bar — the ideas, then as many reviewed
    # reels as fit — so the first read brings a whole page of them (the view trims it)
    reviewed = reviewed_reels.reviewed_reels(
        tenant_id,
        brand_id,
        filters=filters,
        limit=reels_filters_vm.LIST_PAGE,
        store=runs,
        library=library,
        now=now,
    )
    seen = reviewed.view
    account_reels: Sequence[Any] = ()
    if seen.shown is not None and seen.ideas:
        # each idea's lift is against its account's reels of the run's window, as stored
        since = reels_ideas_vm.run_moment(seen.shown) - timedelta(days=seen.shown.days)
        wanted = sorted({(idea.reel.network, idea.reel.handle) for idea in seen.ideas})
        account_reels = tuple(runs.reels_of(tenant_id, wanted, since=since))
    return reels_ideas_vm.StoredIdeas(
        view=seen,
        accounts=len(reels.brand_referentes(tenant_id, brand_id, repository=repo)),
        has_brief=has_brief(tenant_id, brand_id, repository=repo),
        timezone=timezone if timezone is not None else _business_timezone(tenant_id),
        account_reels=account_reels,
        reviewed=reviewed,
    )


def mark_opened(tenant_id: UUID, brand_id: UUID, *, store: ReelRunStore | None = None) -> None:
    """Record that the owner opened the screen (`reel_runs.mark_opened`, the signal of the
    worker's 14-day rule). Never raises: a failed mark must not cost the owner the
    screen — the log keeps it."""
    try:
        reel_runs.mark_opened(tenant_id, brand_id, store=store)
    except Exception as exc:  # noqa: BLE001 — the screen goes on; the log says why
        logger.warning("reel ideas opened mark failed: %s: %s", type(exc).__name__, exc)


def ensure_first_run(tenant_id: UUID, brand_id: UUID, *, store: ReelRunStore | None = None) -> bool:
    """Queue the brand's first run when it never had one (`reel_runs.ensure_first_run`,
    option A, confirmed 2026-11-04). Only queues: the worker pays, never the screen."""
    return bool(reel_runs.ensure_first_run(tenant_id, brand_id, store=store))


def load_ideas(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    now: datetime | None = None,
    first_run: bool = True,
    store: ReelRunStore | None = None,
    repository: Any = None,
    timezone: str | None = None,
    filters: ReelFilters | None = None,
    library: ReviewedReelsStore | None = None,
) -> reels_ideas_vm.IdeasScreen:
    """What the screen shows now (`reels_ideas_vm.ideas_screen`). A brand that could
    have ideas but never had a run gets its first one queued (option A) and the view is
    read again, so the screen says it is being prepared. `first_run=False` is the
    «preparando» screen's own re-read: it never queues.

    One clock for the whole read: the moment taken here judges the view (when a failed
    check is retried, whether «Replicar» can work) and every sentence and date of the
    screen alike — two clocks could disagree on whether the retry is still due."""
    moment = now or datetime.now(UTC)
    stored = stored_ideas(
        tenant_id,
        brand_id,
        store=store,
        repository=repository,
        timezone=timezone,
        now=moment,
        filters=filters,
        library=library,
    )
    if first_run and reels_ideas_vm.wants_first_run(stored):
        # option A (founder, 2026-11-04): the first open queues the brand's first run
        ensure_first_run(tenant_id, brand_id, store=store)
        stored = replace(stored, view=reel_runs.view(tenant_id, brand_id, store=store, now=moment))
    shown = reels_ideas_vm.ideas_screen(stored, now=moment)
    if not shown.cards:
        return shown
    return replace(shown, cards=with_badges(tenant_id, shown.cards))


def more_reviewed(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    filters: ReelFilters | None = None,
    offset: int,
    limit: int = reels_filters_vm.LIST_PAGE,
    now: datetime | None = None,
    store: ReelRunStore | None = None,
    library: ReviewedReelsStore | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """One more page of the reviewed reels («Ver más», RF-02/RF-13), from `offset`, narrowed by
    `filters`: its cards and whether a next page exists. RF-01's read — Postgres only,
    never the vendor, the model or a write."""
    moment = now or datetime.now(UTC)
    page = reviewed_reels.reviewed_reels(
        tenant_id,
        brand_id,
        filters=filters,
        offset=offset,
        limit=limit,
        store=store or reel_runs.default_store(),
        library=library,
        now=moment,
    )
    return reels_ideas_vm.more_cards(page.more, now=moment), page.has_more


# --------------------------------------------------------------------------------------
# the shared reel analysis (ADR 44 UI-1, m-24921075) — the screen only reads and enqueues
# --------------------------------------------------------------------------------------


def with_badges(tenant_id: UUID, cards: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """The cards with their analysis pill («Aparece una persona» / «Sin analizar»), read
    in ONE query (`reel_analysis.analysis_badges`). Never raises: an unreadable analysis
    leaves every card without a pill — the screen claims nothing it did not read, and
    the ideas still show."""
    keys = [(c.get("network", ""), c.get("id", "")) for c in cards]
    try:
        badges = reel_analysis.analysis_badges(tenant_id, keys)
    except Exception as exc:  # noqa: BLE001 — the ideas go on without their pills
        logger.warning("reel analysis badges unreadable: %s: %s", type(exc).__name__, exc)
        badges = {}
    return reels_ideas_vm.with_analysis_badges(cards, badges)


def reel_source(card: dict[str, str]) -> ReelSource:
    """The analysis' `ReelSource` from a SERVER-HELD card (never from an event's
    arguments): the reel's network, id, public URL and the CDN link the run read, with
    when it read it."""
    return ReelSource(
        network=card.get("network", ""),
        post_id=card.get("id", ""),
        post_url=card.get("url", ""),
        video_url=card.get("video", ""),
        video_url_at=reels_ideas_vm.card_video_read_at(card),
    )


def request_similar(tenant_id: UUID, card: dict[str, str]) -> AnalysisRef | None:
    """«Hacer uno parecido»: ask for the reel's shared analysis (`request_analysis` — an
    `ok` is reused, a queued one is moved ahead with `wanted_at`, else one is queued for
    the `reels-worker`). Only a database read and, at most, one insert: never the vendor,
    never the model, never a download. None when it could not be asked (the flow goes on
    without an analysis; the log keeps why)."""
    try:
        return reel_analysis.request_analysis(tenant_id, reel_source(card))
    except Exception as exc:  # noqa: BLE001 — the owner still gets the create flow
        logger.warning("reel analysis request failed: %s: %s", type(exc).__name__, exc)
        return None


# --------------------------------------------------------------------------------------
# RF-05 (m-25119465): the owner's competitors
# --------------------------------------------------------------------------------------


def competitor_rows(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    store: ReelRunStore | None = None,
    repository: Any = None,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """The panel's rows (`reels_competitors_vm.rows`): every competitor of the brand, which
    ones the Monday run reads, and today's manual read of each. Postgres only — never a
    write, never the vendor."""
    repo = repository or referentes_provider.REPOSITORY
    accounts = reels.competitor_accounts(tenant_id, brand_id, repository=repo)
    if not accounts:
        return []
    moment = (now or datetime.now(UTC)).timestamp()
    states = competitors.read_states(tenant_id, brand_id, store=store, clock=lambda: moment)
    return reels_competitors_vm.rows(
        accounts,
        {
            reels_filters_vm.account_key(network, handle): reels_competitors_vm.read_state(answer)
            for (network, handle), answer in states.items()
        },
    )


def choose_competitors(
    tenant_id: UUID,
    brand_id: UUID,
    picks: Sequence[tuple[str, str]],
    *,
    repository: Any = None,
) -> None:
    """Save which competitors the Monday run reads (`competitors.choose_weekly`): the
    brand's own labels, through `tenant_session`. Never pays."""
    competitors.choose_weekly(
        tenant_id, brand_id, picks, repository=repository or referentes_provider.REPOSITORY
    )


def read_competitor_now(
    tenant_id: UUID,
    brand_id: UUID,
    key: str,
    *,
    store: ReelRunStore | None = None,
    repository: Any = None,
) -> reels_competitors_vm.ReadState | None:
    """«Ver sus reels ahora» (`competitors.read_now`): queues the read of that competitor
    for today — once — unless the business's daily cap is spent. Never pays here: the
    reels-worker does. None for a key that is not one of the brand's competitors."""
    pair = reels_filters_vm.parse_account_key(key)
    if pair is None:
        return None
    moment = datetime.now(UTC).timestamp()  # the panel's clock (`competitor_rows`)
    answer = competitors.read_now(
        tenant_id,
        brand_id,
        pair[0],
        pair[1],
        store=store,
        repository=repository or referentes_provider.REPOSITORY,
        clock=lambda: moment,
    )
    if answer.state == competitors.STATE_NOT_COMPETITOR:
        return None
    return reels_competitors_vm.read_state(answer)


__all__ = [
    "BRIEF_HASHTAGS",
    "brand_brief",
    "choose_competitors",
    "competitor_rows",
    "cover_path",
    "read_competitor_now",
    "ensure_first_run",
    "has_brief",
    "load_ideas",
    "mark_opened",
    "more_reviewed",
    "reel_source",
    "request_similar",
    "stored_ideas",
    "with_badges",
]
