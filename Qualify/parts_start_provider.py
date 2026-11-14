"""The seam between «Armar mi video por partes» (m-24921079) and `parts_ai.propose_parts`.

`propose(...)` reads what the proposal starts from — the catalog product (photos, name,
description) and the brand (name, positioning, audience, palette, rubro, location) — builds
the `PartsBrief` and asks Claude for the plan: ONE paid call, at most one corrective
turn, booked to the session's business (`Attribution`, feature `partes-propuesta`).
Nothing is written and no video is asked for.

Every function here blocks (the database, then a Claude call of several seconds): callers
on the event loop run them off-thread (`await asyncio.to_thread(...)` in a background
event, as `PartsStartState.propose` does). Identity is always explicit, never ambient.

Errors never leave as exceptions: `propose` returns a `ProposalOutcome` whose `error` is
the owner's sentence (`parts_start_vm.error_text`), and logs the reason.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from qualify_api.claude_tools import Attribution
from qualify_api.creative.parts_ai import (
    DEFAULT_TARGET_SECONDS,
    PartsBrief,
    PartsProposal,
    propose_parts,
)
from qualify_creative.angles import AngleBrand, AngleProduct

from . import parts_start_vm as vm

logger = logging.getLogger(__name__)

#: The product function the monthly Claude report books these calls under.
FEATURE = "partes-propuesta"


class Proposer(Protocol):
    def __call__(self, brief: PartsBrief, *, attribution: Attribution) -> PartsProposal: ...


#: (tenant, brand, product id as the screen keeps it, product name) → the brand and the
#: product as the prompt needs them.
FactsReader = Callable[[UUID, UUID, str, str], tuple[AngleBrand, AngleProduct | None]]


@dataclass(frozen=True)
class ProposalOutcome:
    """What the card shows next: the plan's entries and who proposed it, or the owner's
    sentence for why there is no plan (`error` non-empty, `entries` empty)."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


# -- the facts (database) ---------------------------------------------------------------


def _catalog_id(raw: str) -> UUID | None:
    """A CATALOG product id; a stock pick (`stock:…`, a `t/…` key) or nothing is None."""
    try:
        return UUID((raw or "").strip())
    except ValueError:
        return None


def brand_facts(tenant_id: UUID, brand_id: UUID) -> AngleBrand:
    """The brand as the prompt needs it — the same facts the angles read
    (`composition._DbBrandFacts`). The brand only colours the prompt: a part that cannot
    be read is left out, never a failed proposal."""
    from qualify_api.creative.brand_context import DbBrandContextReader
    from qualify_api.creative.brand_names import DbBrandNames
    from qualify_api.creative.composition import DbBrandKitReader

    def read(what: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — decoration for the prompt
            logger.info("parts proposal: brand %s unreadable (%s)", what, type(exc).__name__)
            return None

    name = read("name", lambda: DbBrandNames()(tenant_id=tenant_id, brand_id=brand_id))
    kit = read("kit", lambda: DbBrandKitReader().kit(tenant_id=tenant_id, brand_id=brand_id))
    context = read(
        "context", lambda: DbBrandContextReader().context(tenant_id=tenant_id, brand_id=brand_id)
    )
    return AngleBrand(
        name=name or "",
        positioning=kit.positioning if kit is not None else "",
        audience=kit.audience if kit is not None else "",
        sector=context.sector if context is not None else "",
        location=context.location if context is not None else "",
        palette=tuple(kit.palette_rgb) if kit is not None else (),
        typeface=kit.typeface if kit is not None else "",
        # «Lo que ofrece tu negocio»: the only venue facts the parts may state
        perks=tuple(kit.business_perks) if kit is not None else (),
    )


def product_facts(
    tenant_id: UUID, brand_id: UUID, product_id: str, product_name: str
) -> AngleProduct | None:
    """The catalog product as the prompt sees it (`angle_sets.product_facts`: photos hero
    first). A stock pick or no product is None (the sentence tells the story); a catalog
    product that cannot be read keeps at least the name the screen shows."""
    pid = _catalog_id(product_id)
    if pid is None:
        return None
    from qualify_api.catalog.service import CatalogService
    from qualify_api.creative.angle_sets import product_facts as facts_of
    from qualify_api.creative.composition import media_root
    from qualify_api.creative.media import LocalMediaStore

    try:
        product = CatalogService(store=LocalMediaStore(media_root())).get_product(
            tenant_id=tenant_id, product_id=pid
        )
    except Exception as exc:  # noqa: BLE001 — the name the screen has is enough to go on
        logger.info("parts proposal: product unreadable (%s)", type(exc).__name__)
        product = None
    if product is None or product.brand_id != brand_id:
        name = " ".join((product_name or "").split())
        return AngleProduct(product_id=pid, name=name) if name else None
    return facts_of(product)


def read_facts(
    tenant_id: UUID, brand_id: UUID, product_id: str, product_name: str
) -> tuple[AngleBrand, AngleProduct | None]:
    return (
        brand_facts(tenant_id, brand_id),
        product_facts(tenant_id, brand_id, product_id, product_name),
    )


# -- the proposal -----------------------------------------------------------------------


def _platform_proposer(brief: PartsBrief, *, attribution: Attribution) -> PartsProposal:
    """`propose_parts` on the platform's Anthropic key (resolved per call)."""
    return propose_parts(brief, attribution=attribution)


def build_brief(
    story: str,
    brand: AngleBrand,
    product: AngleProduct | None,
    target_seconds: int = DEFAULT_TARGET_SECONDS,
) -> PartsBrief:
    return PartsBrief(
        story=vm.clean_story(story), brand=brand, product=product, target_seconds=target_seconds
    )


def propose(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    story: str,
    product_id: str = "",
    product_name: str = "",
    target_seconds: int = DEFAULT_TARGET_SECONDS,
    facts: FactsReader = read_facts,
    proposer: Proposer = _platform_proposer,
) -> ProposalOutcome:
    """Claude's plan for this sentence and product, as the card's entries — or why not,
    in the owner's words. Blocking: run it off the event loop."""
    if not vm.clean_story(story):
        return ProposalOutcome(error=vm.STORY_MISSING_TEXT)
    try:
        brand, product = facts(tenant_id, brand_id, product_id, product_name)
        brief = build_brief(story, brand, product, target_seconds)
        proposal = proposer(
            brief,
            attribution=Attribution(tenant_id=tenant_id, brand_id=brand_id, feature=FEATURE),
        )
    except Exception as exc:  # noqa: BLE001 — every failure reads as a sentence on the card
        logger.warning("parts proposal failed: %s", type(exc).__name__)
        return ProposalOutcome(error=vm.error_text(exc))
    return ProposalOutcome(
        entries=vm.entries_from_proposal(proposal),
        provenance=vm.provenance_json(proposal),
    )
