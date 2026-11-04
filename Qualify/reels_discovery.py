"""«Ideas para tus reels» — the Reflex app's door to the stored ideas (ADR 42 R7,
m-24854854; «Descubrir reels» in the code).

Opening the screen never spends (ADR 42 §2.1, decision 1). Nothing here calls
ScrapeCreators or the model: the persistent run (`qualify_api.referentes.reel_runs.run`,
the `reels-worker`'s) is the only door that pays, and the screen reads what it stored:

- `stored_ideas` — the latest run and the latest `ok` one with its ideas
  (`reel_runs.view`), how many accounts the brand follows, whether something says what it
  sells, the business's zone and the stored reels each idea's lift is measured against.
  Postgres only, never a write;
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
from qualify_api.referentes import reel_runs, reels
from qualify_api.referentes.reel_store import ReelRunStore

from . import reels_ideas_vm, referentes_provider
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
) -> reels_ideas_vm.StoredIdeas:
    """Everything «Ideas para tus reels» shows, read from Postgres — never the vendor,
    never the model, never a write."""
    runs = store or reel_runs.default_store()
    repo = repository or referentes_provider.REPOSITORY
    seen = reel_runs.view(tenant_id, brand_id, store=runs)
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
) -> reels_ideas_vm.IdeasScreen:
    """What the screen shows now (`reels_ideas_vm.ideas_screen`). A brand that could
    have ideas but never had a run gets its first one queued (option A) and the view is
    read again, so the screen says it is being prepared. `first_run=False` is the
    «preparando» screen's own re-read: it never queues."""
    stored = stored_ideas(
        tenant_id, brand_id, store=store, repository=repository, timezone=timezone
    )
    if first_run and reels_ideas_vm.wants_first_run(stored):
        # option A (founder, 2026-11-04): the first open queues the brand's first run
        ensure_first_run(tenant_id, brand_id, store=store)
        stored = replace(stored, view=reel_runs.view(tenant_id, brand_id, store=store))
    return reels_ideas_vm.ideas_screen(stored, now=now or datetime.now(UTC))


__all__ = [
    "BRIEF_HASHTAGS",
    "brand_brief",
    "cover_path",
    "ensure_first_run",
    "has_brief",
    "load_ideas",
    "mark_opened",
    "stored_ideas",
]
