"""Minimal creative router (design doc §4.1, backlog F5-MA-03 foundations).

Walks a provider chain applying two of the three planned checks:

- (P) pre-flight — the provider's cost estimate is compared against the remaining
  budget BEFORE the vendor call; an over-budget link is recorded as ``budget_blocked``
  and, under ``hard_stop``, the walk stops there.
- (F) provider failure — an exception from ``generate`` is recorded and the walk moves
  to the next link.

The (Q) fidelity check and the per-brand ``FallbackPolicy`` (``on_credential_failure``)
are deliberately not here yet — this is the minimal router the first slice needs.

Every hop is recorded in ``RouterOutcome.hops`` with its reason: a silent skip is a bug.

One contract note: this router calls ``estimate_cost_usd(request, pricing,
api_key=...)`` with the resolved key as a keyword argument. The base Protocol does not
carry the key, but token-priced vendors need an authenticated counter for an exact
pre-flight estimate; adapters routed here accept ``api_key`` as an optional keyword
(per-piece vendors may simply ignore it).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from qualify_creative.providers import (
    CredentialResolver,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    PricingTable,
)


class HopAction(StrEnum):
    """What happened at one link of the chain."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BUDGET_BLOCKED = "budget_blocked"


@dataclass(frozen=True)
class BudgetContext:
    """What is left to spend. ``hard_stop`` decides whether an over-budget link ends the
    walk (the financial guardrail default) or merely skips to the next — possibly
    cheaper — provider."""

    remaining_usd: Decimal
    hard_stop: bool = True


@dataclass(frozen=True)
class Hop:
    """One recorded step of the walk. ``reason`` is None only on success."""

    provider: str
    action: HopAction
    reason: str | None = None


@dataclass(frozen=True)
class RouterOutcome:
    """The result (if any link succeeded) plus the full, gap-free hop record."""

    result: GenerationResult | None
    hops: tuple[Hop, ...]

    @property
    def succeeded(self) -> bool:
        return self.result is not None


class CreativeRouter:
    """Walks a named provider chain for one generation request."""

    def __init__(
        self,
        providers: Mapping[str, GenerationProvider],
        pricing: PricingTable,
        credentials: CredentialResolver,
    ) -> None:
        self._providers = providers
        self._pricing = pricing
        self._credentials = credentials

    def run(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        chain: tuple[str, ...],
        request: GenerationRequest,
        budget: BudgetContext,
    ) -> RouterOutcome:
        hops: list[Hop] = []
        for name in chain:
            provider = self._providers.get(name)
            if provider is None:
                hops.append(Hop(name, HopAction.FAILED, "provider not registered"))
                continue
            if request.task not in provider.supports:
                hops.append(Hop(name, HopAction.FAILED, f"task {request.task!r} not supported"))
                continue
            try:
                key = self._credentials.resolve(
                    tenant_id=tenant_id, brand_id=brand_id, provider=name
                )
            except Exception as exc:  # noqa: BLE001 — every failure becomes a hop
                hops.append(Hop(name, HopAction.FAILED, f"credential resolution failed: {exc}"))
                continue

            # (P) pre-flight: estimate BEFORE the vendor call, never after.
            try:
                estimate = provider.estimate_cost_usd(request, self._pricing, api_key=key.api_key)
            except Exception as exc:  # noqa: BLE001
                hops.append(Hop(name, HopAction.FAILED, f"cost estimate failed: {exc}"))
                continue
            if estimate > budget.remaining_usd:
                hops.append(
                    Hop(
                        name,
                        HopAction.BUDGET_BLOCKED,
                        f"estimated ${estimate} exceeds remaining ${budget.remaining_usd}",
                    )
                )
                if budget.hard_stop:
                    break
                continue

            # (F) provider failure: record and fall through to the next link.
            try:
                result = provider.generate(request, api_key=key.api_key)
            except Exception as exc:  # noqa: BLE001
                hops.append(Hop(name, HopAction.FAILED, f"{type(exc).__name__}: {exc}"))
                continue

            hops.append(Hop(name, HopAction.SUCCEEDED))
            return RouterOutcome(result=result, hops=tuple(hops))

        return RouterOutcome(result=None, hops=tuple(hops))
