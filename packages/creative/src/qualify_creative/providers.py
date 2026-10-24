"""The single seam between the engine and any creative vendor.

Business code imports THIS, never `anthropic` / `fal_client` / `replicate`. The point is
not purity for its own sake: it is that swapping an aggregator, adding a model or moving
from a platform key to a per-brand key becomes one implementation, not an audit of every
call site.

Note `api_key` is a REQUIRED keyword argument of `generate`. That is deliberate and it is
a type-level guard, not ceremony: every vendor SDK resolves credentials from the process
environment when constructed with no arguments, so an adapter that forgot to pass one
would not fail — it would silently bill somebody else's account. A signature that cannot
express the mistake is worth more than a test that catches it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from qualify_creative.enums import GenerationTask, PaidBy


@dataclass(frozen=True)
class RenderedPrompt:
    """Split rather than concatenated, and that is the whole point.

    `stable_prefix` is byte-identical for every generation of the same brand and voice
    version, so it takes the prompt-cache breakpoint (cache reads cost roughly a tenth of
    fresh input). `volatile_suffix` carries the brief. Nothing volatile may appear in the
    prefix — no timestamp, no request id, no unsorted mapping — or the cache never hits
    and the copy layer costs an order of magnitude more than it should.
    """

    stable_prefix: str
    volatile_suffix: str
    prefix_fingerprint: str


@dataclass(frozen=True)
class Usage:
    """What a call consumed. Token fields stay zero for per-piece vendors and `pieces`
    stays zero for token-priced ones; both shapes coexist because the pricing table
    carries two units and the budget check has to compare like with like.

    `media_seconds` is the third shape: video vendors bill by rendered second, and the
    duration is only known once the render finishes — it is the vendor-reported length,
    never the pre-flight estimate."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    pieces: int = 0
    media_seconds: Decimal = Decimal(0)


class VendorTaskObserver(Protocol):
    """Hears of an asynchronous vendor task while an adapter waits for it (m-24852154).

    `created` is called as soon as the vendor accepted the task (2xx, before any wait):
    the caller persists the id there, so a task that outlives the wait — the vendor's
    queue, the process dying on a deploy — is resumed by id later, never submitted again
    nor lost while it is billed. `polled` is called on every answer while waiting (the
    caller's sign of life). Neither may break the generation: an adapter swallows what
    they raise."""

    def created(self, task_id: str) -> None: ...

    def polled(self, task_id: str, status: str) -> None: ...


@dataclass(frozen=True)
class GenerationRequest:
    task: GenerationTask
    rendered_prompt: RenderedPrompt
    params: Mapping[str, object] = field(default_factory=dict)
    output_schema: Mapping[str, object] | None = None
    source_media_url: str | None = None
    #: Only asynchronous adapters use it (Seedance); never part of the request's identity.
    observer: VendorTaskObserver | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class GenerationResult:
    """`media_expires_at_seconds` is how long the vendor guarantees the returned URL, as
    the vendor reports it — never a constant. The two aggregators differ by two orders of
    magnitude, so a hardcoded window starts lying the moment the router falls back."""

    payload: bytes | Mapping[str, object]
    model_id: str
    provider: str
    usage: Usage
    model_revision: str | None = None
    media_url: str | None = None
    media_expires_at_seconds: int | None = None


@dataclass(frozen=True)
class ResolvedKey:
    api_key: str
    paid_by: PaidBy
    fingerprint: str

    def __repr__(self) -> str:
        """The key never reaches a log, a traceback or an error report. Overriding repr
        is cheap insurance against the one place nobody remembers to redact."""
        return f"ResolvedKey(fingerprint={self.fingerprint!r}, paid_by={self.paid_by})"


class CredentialResolver(Protocol):
    """Only the platform implementation exists today (Qualify pays). The tenant and brand
    parameters stay in the signature anyway, because they are the ones the usage event
    needs regardless — taking them out now would mean threading them back through every
    adapter the day a customer brings their own key."""

    def resolve(self, *, tenant_id: UUID, brand_id: UUID, provider: str) -> ResolvedKey: ...


class PricingTable(Protocol):
    """Versioned and cached. Aggregator prices move by multiples, so a literal in code is
    a margin bug waiting for a release."""

    version: str

    def unit_price(self, *, model_id: str, unit: str) -> Decimal: ...


class GenerationProvider(Protocol):
    """One vendor, one implementation."""

    name: str
    supports: frozenset[GenerationTask]

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult: ...

    def estimate_cost_usd(self, request: GenerationRequest, pricing: PricingTable) -> Decimal:
        """Pre-flight estimate for the router's budget check. For token-priced models this
        MUST call the vendor's own counter rather than a heuristic: tiktoken-style
        estimators undercount Claude tokens by 15-20%, and more on code and Spanish."""
        ...
