"""The Brand Kit proposed from a brand's own account, without Reflex (m-24852197, PB-3 of
the epic m-24852192, docs/epica-prellenado-brand-kit-alta.md §2 items 3, 5, 6, 7).

One implementation of what the connect wizard does with an account
(`Qualify/creative_wizard_pages.py`): `BrandConnectState.analyze` (claim the account,
read it — the tenant's cache first —, what it says about the rubro and the place, its
metrics), `suggest_hashtags` (Tu rubro named by Claude, then the hashtags: the shared
catalog, else the account's own, else created by Claude) and `apply_logo_colours` (the
profile picture's colours into the palette). The wizard's `analyze` calls
`prefill_brand_kit(..., propose=False)` and maps the result onto its screen; its
`suggest_hashtags` and `apply_logo_colours` call the step functions below. The Alta
(PB-4) calls `prefill_brand_kit` whole, from a worker.

Why `qualify_api.creative`: what it writes is the Brand Kit (`brand_kit_store`), and the
two pieces it stands on that are the Brand Kit's own — the account claim
(`account_claims`) and the logo palette (`logo_palette`) — already live here. The
account read and the seed are `qualify_api.referentes` (PB-2) and are only called.

**Assisted, never autonomous.** With `propose=True` the result is written as a
PROPOSAL, and only there: the key `prefill` of the `brand_kit_details.connect` document
(`PREFILL_KEY`), reserved so a wizard's save never erases it
(`brand_kit_store.RESERVED_DETAIL_KEYS`). The top-level `connect` keys and the `profile`
document are what generation reads (`brand_context.build_context`), so they are NOT
touched: nothing proposed reaches a piece until the owner approves it (PB-5 moves the
proposal there). No logo or avatar is generated, and no website is read.

**The profile picture is kept in R2** (m-24852537): the network's CDN link expires in
days (Instagram ~4.4 days, TikTok ~47 h, measured 2026-10-25), and «Aprobar» uses the
picture as the logo. The bytes the run already downloaded for the palette are copied —
no second download, no credit — under the brand's own prefix
(`kept_pictures.kept_key`: `t/{tenant}/brand/{brand}/kept/profile/{sha256}.{ext}`). The
proposal's `profile` carries that key (`pic_key`, `pic_content_type`) and an empty
`pic`; the CDN URL survives only as provenance (`provenance.picture.source_url`). A copy
that fails leaves the proposal written with `provenance.picture.status = "missing"` and
no key — the run, its outcome and its cap accounting are unchanged.

Other rows a run writes, both tenant-scoped and both what the wizard already writes:
the account claim (`creative.account_claims`, so one email never reads another's
account) and the tenant's profile cache (`referentes.profile_cache`, so a second run
costs no credit). The shared hashtag catalog gets no tag or link from a proposal
(`remember=False`); its one write on this path is the catalog's own idempotent taxonomy
seed (`hashtags.catalog.ensure_seeded`: the hand-written niches as data, once per
process, the same any first catalog read in the wizard does).

**Costs are capped per run** (`CallCaps`): every Scrape Creators request and every
Claude run spends from it, and the one that would exceed it is not made — the run stops
with `PrefillOutcome.CAP_REACHED`. Nothing raises out of `prefill_brand_kit`: every
failure is a typed outcome (`PrefillResult`), with the counts spent (`PrefillUsage`).

**Provenance** rides in the proposal (`provenance`): the read (vendor, client module,
snapshot schema, endpoints, cache or live), each Claude run (step, model id and
revision, prompt version, tokens) and the caller's `source` (PB-4: the Meegle item).

**Phone numbers are masked at the read** (m-24854323, `qualify_api.privacy`): the
profile — bio, name, captions, links — is masked before it is cached, sent to Claude,
proposed, returned to the wizard or logged, so the full number never leaves the tenant.

All database access goes through `qualify_shared.db.session.tenant_session(tenant_id)`
(the store, the claim and the cache repository), so RLS scopes every write.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy.exc import SQLAlchemyError

from qualify_api.claude_tools import (
    CallStats,
    ClaudeToolError,
    MissingAPIKey,
    api_key_from_env,
)
from qualify_api.creative import account_claims, kept_pictures, logo_palette
from qualify_api.creative.brand_kit_store import PREFILL_DOCUMENT, PREFILL_KEY, BrandKitStore
from qualify_api.creative.brand_prefill_review import is_decided
from qualify_api.hashtags import ai as hashtag_ai
from qualify_api.hashtags import catalog as hashtag_catalog
from qualify_api.hashtags import fold, from_profile
from qualify_api.privacy import mask_phones, mask_phones_in
from qualify_api.referentes import discovery_seed, scrapecreators_client
from qualify_api.referentes.discovery_seed import DiscoverySeed
from qualify_api.referentes.profile_cache import (
    PostgresProfileCacheRepository,
    ProfileCacheRepository,
)

logger = logging.getLogger(__name__)

#: The pipeline's own version, bumped when what a run proposes changes shape or meaning.
PREFILL_VERSION = 2  # 2: the profile picture kept in R2 (m-24852537)
#: The proposal's review state. PB-5 writes the others ("approved", "discarded").
STATE_PROPOSED = "proposed"
#: The pills Tu rubro holds — the referentes search's own cap.
CHOSEN_HASHTAGS = discovery_seed.CHOSEN_HASHTAGS
#: Where the palette came from — `Qualify/creative_wizard_pages.LOGO_SOURCE_PROFILE`.
LOGO_SOURCE_PROFILE = "profile"
#: Same name the wizard's cache provider uses for the brand's own account snapshot.
_SNAPSHOT_KIND = "snapshot"
#: The vendor's host: only requests to it spend from the Scrape Creators cap.
_SCRAPECREATORS_HOST = urlsplit(scrapecreators_client.BASE_URL).hostname or ""

#: The profile picture is read from the network's own CDN — never a credit.
_PICTURE_HOST_SUFFIXES = (
    "cdninstagram.com",
    "fbcdn.net",
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "tiktokcdn-eu.com",
)
_PICTURE_MAX_BYTES = 3_000_000
_PICTURE_TIMEOUT_SECONDS = 8.0
_PICTURE_MAX_REDIRECTS = 3
_PICTURE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


# --------------------------------------------------------------------------------------
# What a run returns
# --------------------------------------------------------------------------------------


class PrefillOutcome(StrEnum):
    """How a run ended. PB-4 writes its Meegle comment from it:
    `PRIVATE_ACCOUNT` → «…la cuenta de Instagram es privada.»; `NOT_FOUND`,
    `READ_FAILED` and `CAP_REACHED` → «…no se pudo leer la cuenta de Instagram.»."""

    OK = "ok"
    #: Read, but private: nothing to propose from.
    PRIVATE_ACCOUNT = "private_account"
    #: The vendor answered 404: no such account (or one it cannot see).
    NOT_FOUND = "not_found"
    #: The read (or the claim before it) could not be made: vendor, network, database.
    READ_FAILED = "read_failed"
    #: Another tenant's brand holds this account (`account_claims.AccountTaken`).
    ACCOUNT_TAKEN = "account_taken"
    #: The next call would have exceeded `CallCaps`; the run stopped before making it.
    CAP_REACHED = "cap_reached"


@dataclass(frozen=True)
class CallCaps:
    """The most external calls one run may make. Defaults are the most a run can need:
    Scrape Creators 1 profile + 5 post pages (`scrapecreators_client._MAX_POST_PAGES`),
    Claude 3 runs (the rubro, the catalog choice, the creation when the rubro run
    proposed no tags). A worker passes lower ones to bound the cost of one Alta."""

    scrapecreators_requests: int = 6
    claude_calls: int = 3


DEFAULT_CAPS = CallCaps()


@dataclass(frozen=True)
class PrefillUsage:
    """What a run spent — what PB-6 measures. A live Scrape Creators request costs one
    credit on these endpoints (`scrapecreators instagram profile --help`, 2026-10-24);
    a cache hit makes none. Claude tokens are summed from every run whose stats are
    known; `claude_tokens_complete` is False only when a run was made but failed before
    returning its stats (the SDK raised mid-run; Langfuse still has those tokens)."""

    scrapecreators_requests: int = 0
    scrapecreators_credits: int = 0
    claude_calls: int = 0
    claude_input_tokens: int = 0
    claude_output_tokens: int = 0
    claude_cache_read_tokens: int = 0
    claude_cost_usd: float = 0.0
    claude_tokens_complete: bool = True
    claude_cache_creation_tokens: int = 0

    def as_document(self) -> dict[str, Any]:
        return {
            "scrapecreators_requests": self.scrapecreators_requests,
            "scrapecreators_credits": self.scrapecreators_credits,
            "claude_calls": self.claude_calls,
            "claude_input_tokens": self.claude_input_tokens,
            "claude_output_tokens": self.claude_output_tokens,
            "claude_cache_read_tokens": self.claude_cache_read_tokens,
            "claude_cache_creation_tokens": self.claude_cache_creation_tokens,
            "claude_cost_usd": round(self.claude_cost_usd, 6),
            "claude_tokens_complete": self.claude_tokens_complete,
        }


@dataclass(frozen=True)
class PrefillResult:
    outcome: PrefillOutcome
    network: str
    handle: str
    #: The normalized read (`fetch_profile_and_posts`' dict), when there was one.
    profile: dict[str, Any] | None = None
    #: True when it came from Scrape Creators now (not the tenant's cache).
    fetched_live: bool = False
    #: What the account says about its rubro and place (`seed_from_profile`).
    seed: DiscoverySeed | None = None
    #: `profile_metrics` over the read.
    metrics: list[dict[str, Any]] = field(default_factory=list)
    #: What was written under `connect.prefill.proposal` (None: nothing proposed).
    proposal: dict[str, Any] | None = None
    #: Whether the proposal document was written (`propose=True` and persisted).
    written: bool = False
    usage: PrefillUsage = field(default_factory=PrefillUsage)
    #: For the logs only — never shown to a client.
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is PrefillOutcome.OK

    @property
    def read(self) -> bool:
        """The account was read (public or private)."""
        return self.profile is not None and self.outcome in (
            PrefillOutcome.OK,
            PrefillOutcome.PRIVATE_ACCOUNT,
        )

    @property
    def sector(self) -> str:
        return self.seed.niches[0] if self.seed and self.seed.niches else ""

    @property
    def country_code(self) -> str:
        return self.seed.country_code if self.seed else ""

    @property
    def city(self) -> str:
        return self.seed.city if self.seed else ""


# --------------------------------------------------------------------------------------
# The per-run budget
# --------------------------------------------------------------------------------------


class _ScrapeCreatorsCapReached(scrapecreators_client.ScrapeCreatorsError):
    """Raised from the HTTP client's request hook: the request is never sent. A
    `ScrapeCreatorsError` so a blocked post page is handled like any failed one."""


class ClaudeCapReached(RuntimeError):
    """The next Claude run would exceed the cap; it is not made."""


@dataclass
class CallBudget:
    """What one run may still spend, and what it spent (with the Claude stats)."""

    caps: CallCaps = DEFAULT_CAPS
    scrapecreators_requests: int = 0
    claude_calls: int = 0
    claude_stats: list[CallStats] = field(default_factory=list)
    claude_tokens_complete: bool = True
    #: "scrapecreators" / "claude" once a call was refused.
    exhausted: str = ""

    def spend_scrapecreators(self, request: httpx.Request) -> None:
        if request.url.host != _SCRAPECREATORS_HOST:
            return
        if self.scrapecreators_requests >= self.caps.scrapecreators_requests:
            self.exhausted = "scrapecreators"
            raise _ScrapeCreatorsCapReached(
                f"Scrape Creators cap of {self.caps.scrapecreators_requests} requests reached"
            )
        self.scrapecreators_requests += 1

    def spend_claude(self) -> None:
        if self.claude_calls >= self.caps.claude_calls:
            self.exhausted = "claude"
            raise ClaudeCapReached(f"Claude cap of {self.caps.claude_calls} runs reached")
        self.claude_calls += 1

    def usage(self) -> PrefillUsage:
        return PrefillUsage(
            scrapecreators_requests=self.scrapecreators_requests,
            scrapecreators_credits=self.scrapecreators_requests,
            claude_calls=self.claude_calls,
            claude_input_tokens=sum(s.input_tokens for s in self.claude_stats),
            claude_output_tokens=sum(s.output_tokens for s in self.claude_stats),
            claude_cache_read_tokens=sum(s.cache_read_tokens for s in self.claude_stats),
            claude_cost_usd=sum(s.cost_usd for s in self.claude_stats),
            claude_tokens_complete=self.claude_tokens_complete,
            claude_cache_creation_tokens=sum(s.cache_creation_tokens for s in self.claude_stats),
        )


# --------------------------------------------------------------------------------------
# The seams (fakes in tests)
# --------------------------------------------------------------------------------------

#: `ai` (Claude chose or created) / `rule`, the tags, their reasons, and the Claude run.
HashtagChoice = hashtag_catalog.HashtagChoice


class HashtagCatalog(Protocol):
    """The shared hashtag catalog's read side and its writer of created tags. Without
    one, `hashtags_db_first` starts at the account's own tags."""

    def suggest(
        self, tenant_id: UUID, seed: DiscoverySeed, *, bio: str, category: str
    ) -> HashtagChoice: ...

    def remember_created(
        self, tenant_id: UUID, seed: DiscoverySeed, tags: tuple[str, ...], *, network: str | None
    ) -> None: ...


@dataclass
class CatalogHashtags:
    """`qualify_api.hashtags.catalog` — the one the wizard and the Alta both use.
    `repository` / `selector` / `api_key` are for tests (None = the catalog's own:
    Postgres, `hashtag_ai.select_hashtags`, the env key)."""

    repository: Any = None
    selector: Callable[..., Any] | None = None
    api_key: str | None = None

    def suggest(
        self, tenant_id: UUID, seed: DiscoverySeed, *, bio: str, category: str
    ) -> HashtagChoice:
        return hashtag_catalog.suggest_hashtags(
            tenant_id,
            seed,
            bio=bio,
            category=category,
            repository=self.repository,
            api_key=self.api_key,
            selector=self.selector,
        )

    def remember_created(
        self, tenant_id: UUID, seed: DiscoverySeed, tags: tuple[str, ...], *, network: str | None
    ) -> None:
        hashtag_catalog.remember_created(
            tenant_id, seed, tags, network=network, repository=self.repository
        )


class AccountClaims(Protocol):
    def claim(self, tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> bool: ...

    def release(self, tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> None: ...

    def keep_only(self, tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> None: ...


class ProfileCache(Protocol):
    def get(self, tenant_id: UUID, network: str, handle: str) -> dict[str, Any] | None: ...

    def put(self, tenant_id: UUID, network: str, handle: str, profile: dict[str, Any]) -> None: ...


class _Claims:
    """`creative.account_claims` (tenant_session inside)."""

    def claim(self, tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> bool:
        return account_claims.claim(tenant_id, brand_id, network, handle)

    def release(self, tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> None:
        account_claims.release(tenant_id, brand_id, network, handle)

    def keep_only(self, tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> None:
        account_claims.keep_only(tenant_id, brand_id, network, handle)


@dataclass
class RepositoryProfileCache:
    """The tenant's own account snapshot, same rules as `Qualify/creator_cache_provider`
    (7 days, only a snapshot of the current `SNAPSHOT_SCHEMA`, a database failure is a
    miss and never an error)."""

    repository: ProfileCacheRepository = field(default_factory=PostgresProfileCacheRepository)

    def get(self, tenant_id: UUID, network: str, handle: str) -> dict[str, Any] | None:
        try:
            hit = self.repository.get(tenant_id, network, handle, _SNAPSHOT_KIND)
        except (SQLAlchemyError, ValueError) as exc:
            logger.warning("brand prefill: cached snapshot not read: %s", exc)
            return None
        if hit is None or hit.missing:
            return None
        if hit.document.get("schema") != scrapecreators_client.SNAPSHOT_SCHEMA:
            return None
        profile = hit.document.get("profile")
        return dict(profile) if isinstance(profile, dict) else None

    def put(self, tenant_id: UUID, network: str, handle: str, profile: dict[str, Any]) -> None:
        fetched = profile.get("fetchedAt")
        try:
            self.repository.put(
                tenant_id,
                network,
                handle,
                _SNAPSHOT_KIND,
                {"schema": scrapecreators_client.SNAPSHOT_SCHEMA, "profile": profile},
                now=fetched if isinstance(fetched, float) else None,
            )
        except (SQLAlchemyError, ValueError) as exc:
            logger.warning("brand prefill: snapshot not cached: %s", exc)


ProfileReader = Callable[[str, str, httpx.Client], dict[str, Any]]
PictureFetcher = Callable[[str, httpx.Client], bytes | None]
AccountReader = Callable[..., from_profile.Proposal]


def _read_profile(network: str, handle: str, client: httpx.Client) -> dict[str, Any]:
    # The Alta records no growth history, so it does not pay a second credit for
    # Instagram's per-post AI label (snapshot 5, m-24854324).
    return scrapecreators_client.fetch_profile_and_posts(
        network, handle, client=client, ai_labels=False
    )


def picture_allowed(url: str) -> bool:
    """An `https` URL on the network's own CDN."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(
        host == suffix or host.endswith("." + suffix) for suffix in _PICTURE_HOST_SUFFIXES
    )


def fetch_picture(url: str, client: httpx.Client) -> bytes | None:
    """The profile picture's bytes from the network's CDN, or None (not allowed, not
    an image, too large, or not reachable). Never a Scrape Creators credit.

    Redirects are followed by hand, at most `_PICTURE_MAX_REDIRECTS`, and every hop must
    be on the CDN allow-list too; the body is streamed and dropped as soon as it passes
    `_PICTURE_MAX_BYTES` (a declared larger `content-length` is not read at all)."""
    for _hop in range(_PICTURE_MAX_REDIRECTS + 1):
        if not picture_allowed(url):
            return None
        try:
            with client.stream(
                "GET",
                url,
                headers=_PICTURE_HEADERS,
                timeout=_PICTURE_TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    url = str(response.url.join(response.headers.get("location", "")))
                    continue
                response.raise_for_status()
                return _picture_body(response)
        except httpx.HTTPError as exc:
            logger.info("brand prefill: profile picture not fetched: %s", type(exc).__name__)
            return None
    return None


def _picture_body(response: httpx.Response) -> bytes | None:
    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not kind.startswith("image/"):
        return None
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > _PICTURE_MAX_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > _PICTURE_MAX_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class PrefillPorts:
    """Everything outside the process a run talks to. The defaults are the real ones
    (all tenant-scoped); tests pass fakes and an `httpx.MockTransport`."""

    claims: AccountClaims = field(default_factory=_Claims)
    cache: ProfileCache = field(default_factory=RepositoryProfileCache)
    store: BrandKitStore = field(default_factory=BrandKitStore)
    read_profile: ProfileReader = _read_profile
    fetch_picture: PictureFetcher = fetch_picture
    #: The shared hashtag catalog — the same for the wizard and the Alta.
    catalog: HashtagCatalog | None = field(default_factory=CatalogHashtags)
    #: `from_profile.generate`'s signature; tests pass a fake Claude.
    generate: AccountReader = from_profile.generate
    #: Copies the profile picture to the brand's R2 prefix (m-24852537); tests fake it.
    pictures: kept_pictures.PictureKeeper = field(default_factory=kept_pictures.R2PictureKeeper)
    api_key: Callable[[], str] = api_key_from_env
    #: Only for tests: every HTTP request of the run goes through it.
    transport: httpx.BaseTransport | None = None


# --------------------------------------------------------------------------------------
# Provenance helpers
# --------------------------------------------------------------------------------------


def _fingerprint(*parts: Any) -> str:
    """A prompt version that changes whenever the prompt does: the hash of the system
    text, the tool schema and the model settings."""
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def rubro_prompt_version(max_tags: int = CHOSEN_HASHTAGS) -> str:
    """`from_profile.generate`'s prompt (Tu rubro + created hashtags)."""
    return "from_profile:" + _fingerprint(
        from_profile.SYSTEM,
        from_profile._tool(max_tags),  # noqa: SLF001 - the prompt IS the provenance
        from_profile.MODEL,
        from_profile.EFFORT,
    )


def catalog_prompt_version() -> str:
    """`hashtags.ai.select_hashtags`' prompt (the catalog choice)."""
    return "select_hashtags:" + _fingerprint(
        hashtag_ai.SELECT_SYSTEM, hashtag_ai.SELECT_MODEL, hashtag_ai.SELECT_EFFORT
    )


@dataclass
class _Trail:
    """The Claude runs of one run, for `provenance.claude`."""

    runs: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        step: str,
        prompt_version: str,
        stats: CallStats | None = None,
        *,
        model: str = "",
    ) -> None:
        entry: dict[str, Any] = {"step": step, "prompt_version": prompt_version}
        if stats is not None:
            entry |= {
                "model_id": stats.model_id,
                "model_revision": stats.model_revision or "",
                "input_tokens": stats.input_tokens,
                "output_tokens": stats.output_tokens,
                "cache_read_tokens": stats.cache_read_tokens,
                "cache_creation_tokens": stats.cache_creation_tokens,
                "turns": stats.turns,
                "cost_usd": round(stats.cost_usd, 6),
            }
        else:
            entry["model_id"] = model
        self.runs.append(entry)


# --------------------------------------------------------------------------------------
# Steps (also what the wizard's handlers call)
# --------------------------------------------------------------------------------------


def generate_from_account(
    account: from_profile.AccountText,
    *,
    budget: CallBudget | None = None,
    trail: _Trail | None = None,
    step: str = "rubro",
    generate: AccountReader = from_profile.generate,
    api_key: Callable[[], str] = api_key_from_env,
) -> from_profile.Proposal | None:
    """Claude reads the account (`from_profile.generate`): a rubro phrase and the tags
    its content lives under. None without a key, with nothing to read, or when the call
    fails — every caller has a fallback. Raises `ClaudeCapReached` (before calling)
    when the run's budget has no Claude call left."""
    if not account.has_content:
        return None
    try:
        key = api_key()
    except MissingAPIKey:
        return None
    if budget is not None:
        budget.spend_claude()
    try:
        proposal = generate(account, api_key=key, max_tags=CHOSEN_HASHTAGS)
    except (ClaudeToolError, ValueError) as exc:
        logger.warning("hashtags: creation failed: %s", exc)
        if budget is not None:
            budget.claude_tokens_complete = False  # a run was made; its tokens are lost
        return None
    except Exception as exc:  # noqa: BLE001 — SDK/transport errors: never break the step
        logger.warning("hashtags: creation failed: %s", exc)
        if budget is not None:
            budget.claude_tokens_complete = False
        return None
    if proposal.stats is not None:
        if budget is not None:
            budget.claude_stats.append(proposal.stats)
        logger.info(
            "hashtags: %s read @%s → rubro %r, created %s ($%.4f)",
            proposal.model,
            account.handle,
            mask_phones(proposal.rubro),
            [t.tag for t in proposal.tags],
            proposal.stats.cost_usd,
        )
    elif budget is not None:
        budget.claude_tokens_complete = False
    if trail is not None:
        trail.add(step, rubro_prompt_version(), proposal.stats, model=proposal.model)
    return proposal


def propose_rubro(
    account: from_profile.AccountText,
    *,
    budget: CallBudget | None = None,
    trail: _Trail | None = None,
    generate: AccountReader = from_profile.generate,
    api_key: Callable[[], str] = api_key_from_env,
) -> tuple[str, from_profile.Proposal | None]:
    """Tu rubro, autocompleted: the phrase Claude reads off the account, and the
    proposal it came with (its tags are kept for when the catalog has none). Without
    Claude, the profile's own category ("Restaurante") stands in, or nothing."""
    proposal = generate_from_account(
        account, budget=budget, trail=trail, generate=generate, api_key=api_key
    )
    rubro = proposal.rubro if proposal is not None else ""
    return (rubro or account.category.strip().lower()), proposal


def _as_choice(proposal: from_profile.Proposal, by: str) -> HashtagChoice:
    return HashtagChoice(
        tags=tuple(t.tag for t in proposal.tags),
        by=by,
        picks={t.tag: {"reason": t.reason, "model": proposal.model} for t in proposal.tags},
    )


def _account_catalog_run(
    found: HashtagChoice, budget: CallBudget | None, trail: _Trail | None
) -> None:
    """The catalog's answer into the run's books: its Claude run (stats and tokens) when
    it made one; no call at all for the rule path or a choice served from memory."""
    stats = getattr(found, "stats", None)
    attempted = bool(getattr(found, "attempted", False)) or stats is not None
    if budget is not None:
        if stats is not None:
            budget.claude_stats.append(stats)
        elif attempted:
            budget.claude_tokens_complete = False  # the run failed mid-way
        else:
            budget.claude_calls -= 1  # no run was made: give the call back
    if trail is not None and attempted:
        trail.add("hashtags_catalog", catalog_prompt_version(), stats)


def hashtags_db_first(
    tenant_id: UUID | None,
    seed: DiscoverySeed,
    account: from_profile.AccountText,
    *,
    network: str = "",
    created: from_profile.Proposal | None = None,
    catalog: HashtagCatalog | None = None,
    remember: bool = True,
    budget: CallBudget | None = None,
    trail: _Trail | None = None,
    generate: AccountReader = from_profile.generate,
    api_key: Callable[[], str] = api_key_from_env,
) -> tuple[HashtagChoice | None, str]:
    """Tu rubro's hashtags, in three cases tried in order (§ fourth round of 2026-10-05):

    1. **The database** — the shared catalog (`catalog.suggest`: Claude explores it with
       its tools; the rule path without a key). Skipped without a catalog.
    2. **The latest posts** — the hashtags the account itself used
       (`from_profile.from_posts`, reach-only tags like #fyp left out).
    3. **Created** — Claude writes them from the description and the posts (or the
       proposal `created` already made while it named the rubro); with `remember`, they
       are stored in the catalog so the next brand with that rubro finds them in case 1.

    Returns the choice, or None with the note to show (the wizard's own copy)."""
    # 1. the database
    if catalog is not None and tenant_id is not None and (seed.terms or seed.niches):
        if budget is not None:
            budget.spend_claude()  # before: the run may happen, and the cap is a ceiling
        try:
            found = catalog.suggest(tenant_id, seed, bio=account.bio, category=account.category)
        except (SQLAlchemyError, OSError, ValueError) as exc:
            logger.warning("hashtags: catalog unreadable, trying the posts: %s", exc)
            if budget is not None:
                if getattr(exc, "claude_attempted", False):
                    # a run was made, then the rule path's database failed: the call
                    # stays spent and its tokens are unknown here
                    budget.claude_tokens_complete = False
                else:
                    budget.claude_calls -= 1  # failed before any Claude run
        else:
            _account_catalog_run(found, budget, trail)
            if found.tags:
                return found, ""
    # 2. the latest posts
    own = from_profile.from_posts(account.used_hashtags, max_tags=CHOSEN_HASHTAGS)
    if own.tags:
        return _as_choice(own, "rule"), ""
    # 3. created from the description and the posts
    proposal = created if created is not None and created.tags else None
    if proposal is None:
        proposal = generate_from_account(
            account,
            budget=budget,
            trail=trail,
            step="hashtags_created",
            generate=generate,
            api_key=api_key,
        )
    if proposal is None or not proposal.tags:
        if not account.has_content:
            return None, "Escribe tu rubro (o elige una categoría) y te sugerimos etiquetas."
        return None, (
            "No encontramos etiquetas para tu rubro ni en tus publicaciones. Agrega las "
            "tuyas: con ellas buscamos."
        )
    if remember and catalog is not None and tenant_id is not None and seed.terms:
        try:
            catalog.remember_created(
                tenant_id, seed, tuple(t.tag for t in proposal.tags), network=network or None
            )
        except (SQLAlchemyError, ValueError) as exc:
            logger.warning("hashtags: created tags not stored in the catalog: %s", exc)
    return _as_choice(proposal, "ai"), ""


def pills_from_choice(choice: HashtagChoice) -> list[dict[str, str]]:
    """The pills an empty Tu rubro gets from a choice — what the wizard's
    `merge_suggestions([], choice)` makes: deduplicated (accents/case folded), at most
    `CHOSEN_HASHTAGS`, each with its origin, reason and model."""
    origin = "ai" if choice.by == "ai" else "catalog"
    out: list[dict[str, str]] = []
    present: set[str] = set()
    for tag in choice.tags:
        slug = fold(tag)
        if slug in present or len(out) >= CHOSEN_HASHTAGS:
            continue
        present.add(slug)
        pick = choice.picks.get(tag, {})
        out.append(
            {
                "tag": tag,
                "origin": origin,
                "reason": str(pick.get("reason", "")),
                "model": str(pick.get("model", "")),
            }
        )
    return out


def logo_colours_update(
    palette: str, previous_logo: list[str], data: bytes
) -> tuple[str, list[str]]:
    """THE one way a logo's colours reach a palette (§ request 2026-09-16), for every
    source: `(new palette, the logo's colours)`. Replaces whatever colours a previous
    logo put there and never touches a hand-picked one (`logo_palette.
    merge_into_palette`). A format Pillow cannot read contributes no colours, and
    retires the previous ones all the same. CPU work: callers on an event loop run it
    in a thread."""
    colours = logo_palette.extract_palette(data)
    return logo_palette.merge_into_palette(palette, previous_logo, colours), colours


def picture_is_real(picture_url: str, data: bytes | None) -> bool:
    """A profile picture that exists and is not the network's default silhouette."""
    if not picture_url or logo_palette.is_default_avatar_url(picture_url) or not data:
        return False
    try:
        return not logo_palette.is_placeholder_avatar(data)
    except Exception as exc:  # noqa: BLE001 - an unreadable picture is "not real"
        logger.info("brand prefill: profile picture check failed: %s", type(exc).__name__)
        return False


def format_followers(followers: object) -> str:
    """How the wizard shows the follower count (`12.000`, `—` when unknown)."""
    if isinstance(followers, int | float) and followers:
        return f"{int(followers):,}".replace(",", ".")
    return "—"


def profile_document(profile: Mapping[str, Any], metrics: Sequence[Mapping[str, Any]]) -> dict:
    """The account as the wizard saves it in `brand_kit_details.profile`
    (`Qualify/brand_finish._profile_document`)."""
    followers = profile.get("followers")
    return {
        "username": str(profile.get("username", "")),
        "fullname": str(profile.get("fullName", "")),
        "bio": str(profile.get("bio", "")),
        "category": str(profile.get("category", "")),
        "followers": format_followers(followers),
        "followers_count": int(followers) if isinstance(followers, int | float) else 0,
        "pic": str(profile.get("profilePicUrl", "")),
        "metrics": [
            {
                "label": str(m["label"]),
                "hint": str(m["hint"]),
                "suffix": str(m["suffix"]),
                "decimals": int(m["decimals"]),
                "target": float(m["target"]),
            }
            for m in metrics
        ],
    }


# --------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------


def _settle(action: Callable[[UUID, UUID, str, str], None], *args: Any) -> None:
    """`release` / `keep_only` after the read. Never fails the run: a claim left behind
    only keeps an account this brand already read reserved for it."""
    try:
        action(*args)
    except SQLAlchemyError as exc:
        logger.warning("brand prefill: account claim not settled: %s", exc)


def _client(budget: CallBudget, ports: PrefillPorts, endpoints: list[str]) -> httpx.Client:
    """The run's HTTP client: every Scrape Creators request spends from the budget (the
    one over the cap is never sent) and is recorded for the provenance."""

    def record(request: httpx.Request) -> None:
        if request.url.host == _SCRAPECREATORS_HOST:
            endpoints.append(request.url.path)

    return httpx.Client(
        timeout=scrapecreators_client._TIMEOUT_SECONDS,  # noqa: SLF001 - the client's own
        transport=ports.transport,
        event_hooks={"request": [budget.spend_scrapecreators, record]},
    )


def prefill_brand_kit(
    tenant_id: UUID,
    brand_id: UUID,
    network: str,
    handle: str,
    *,
    source: Mapping[str, Any] | None = None,
    caps: CallCaps = DEFAULT_CAPS,
    propose: bool = True,
    ports: PrefillPorts | None = None,
) -> PrefillResult:
    """Read `handle` on `network` for this brand and, with `propose`, write what it
    proposes for the Brand Kit under `brand_kit_details.connect.prefill`.

    1. Claim the account for the brand (never read another tenant's own account).
    2. Read it: the tenant's cache first, else Scrape Creators (profile + a week of
       posts), remembered for the next run.
    3. What it says: rubro category, country and city (`seed_from_profile`), metrics.
    4. With `propose`: Tu rubro named by Claude, its hashtags (`hashtags_db_first`,
       the shared catalog first, as the wizard — it learns no tag from a proposal),
       the profile picture's colours as the palette; then the proposal, written.

    `propose=False` is the wizard's read: steps 1-3, no Claude, nothing written beyond
    the claim and the cache — the operator walks the rest. `source` (e.g.
    `{"kind": "alta", "meegle_work_item_id": 123}`) goes into the provenance.

    Never raises: every failure is an outcome (an unexpected error is logged and is
    `READ_FAILED`). Blocking (HTTP + database): run it in a thread from an event loop."""
    ports = ports or PrefillPorts()
    budget = CallBudget(caps=caps)
    try:
        return _run(tenant_id, brand_id, network, handle, source, propose, ports, budget)
    except Exception as exc:  # noqa: BLE001 - a worker and a screen both need an outcome
        logger.exception("brand prefill: unexpected failure")
        return PrefillResult(
            PrefillOutcome.READ_FAILED,
            network,
            handle.strip(),
            usage=budget.usage(),
            detail=f"unexpected: {type(exc).__name__}",
        )


def _run(
    tenant_id: UUID,
    brand_id: UUID,
    network: str,
    handle: str,
    source: Mapping[str, Any] | None,
    propose: bool,
    ports: PrefillPorts,
    budget: CallBudget,
) -> PrefillResult:
    clean = handle.strip()

    def done(outcome: PrefillOutcome, detail: str = "", **kw: Any) -> PrefillResult:
        return PrefillResult(
            outcome, network, clean, usage=budget.usage(), detail=mask_phones(detail), **kw
        )

    if network not in scrapecreators_client.SUPPORTED_NETWORKS or not clean.lstrip("@"):
        return done(PrefillOutcome.READ_FAILED, f"unsupported network or empty handle: {network}")

    # 1. the claim, before anything of the account is read — cache included
    try:
        newly_claimed = ports.claims.claim(tenant_id, brand_id, network, clean)
    except account_claims.AccountTaken:
        result = done(PrefillOutcome.ACCOUNT_TAKEN, "the account is another brand's")
        _write_status(tenant_id, brand_id, result, ports, source, propose, [], False)
        return result
    except (SQLAlchemyError, LookupError, ValueError) as exc:
        logger.warning("brand prefill: account claim not checked: %s", exc)
        result = done(PrefillOutcome.READ_FAILED, f"claim not checked: {type(exc).__name__}")
        _write_status(tenant_id, brand_id, result, ports, source, propose, [], False)
        return result

    # 2. the read
    fetched_live = False
    endpoints: list[str] = []
    try:
        profile = ports.cache.get(tenant_id, network, clean)
        if profile is None:
            fetched_live = True
            with _client(budget, ports, endpoints) as client:
                profile = ports.read_profile(network, clean, client)
            if budget.exhausted:
                raise _ScrapeCreatorsCapReached("a post page was over the cap")
            # m-24854323: masked before anything keeps or sends it — the cache, Claude,
            # the proposal, the wizard's screen and what generation later reads
            profile = mask_phones_in(profile)
            ports.cache.put(tenant_id, network, clean, profile)
        else:
            profile = mask_phones_in(profile)  # a snapshot cached before the masking
    except (scrapecreators_client.ScrapeCreatorsError, ValueError, OSError) as exc:
        logger.warning("brand prefill: profile read failed: %s", exc)
        if newly_claimed:  # a typo must not lock an account nobody was shown
            _settle(ports.claims.release, tenant_id, brand_id, network, clean)
        if isinstance(exc, _ScrapeCreatorsCapReached) or budget.exhausted:
            outcome = PrefillOutcome.CAP_REACHED
        elif getattr(exc, "status_code", None) == 404:
            outcome = PrefillOutcome.NOT_FOUND
        else:
            outcome = PrefillOutcome.READ_FAILED
        result = done(outcome, str(exc)[:200])
        _write_status(tenant_id, brand_id, result, ports, source, propose, endpoints, False)
        return result

    # the account read is now the brand's one account on this network
    _settle(ports.claims.keep_only, tenant_id, brand_id, network, clean)

    # 3. what the read says
    seed = discovery_seed.seed_from_profile(profile)
    metrics = scrapecreators_client.profile_metrics(network, profile)
    read = {"profile": profile, "fetched_live": fetched_live, "seed": seed, "metrics": metrics}
    if bool(profile.get("isPrivate")):
        result = done(PrefillOutcome.PRIVATE_ACCOUNT, "private account", **read)
        _write_status(tenant_id, brand_id, result, ports, source, propose, endpoints, fetched_live)
        return result
    if not propose:
        return done(PrefillOutcome.OK, **read)

    # 4. the proposal
    trail = _Trail()
    try:
        proposal = _propose(
            tenant_id, brand_id, network, profile, seed, metrics, budget, trail, ports
        )
    except ClaudeCapReached as exc:
        result = done(PrefillOutcome.CAP_REACHED, str(exc), **read)
        _write_status(
            tenant_id, brand_id, result, ports, source, propose, endpoints, fetched_live, trail
        )
        return result
    result = done(PrefillOutcome.OK, proposal=proposal, **read)
    written = _write_status(
        tenant_id, brand_id, result, ports, source, propose, endpoints, fetched_live, trail
    )
    return replace(result, written=written)


def _propose(
    tenant_id: UUID,
    brand_id: UUID,
    network: str,
    profile: dict[str, Any],
    seed: DiscoverySeed,
    metrics: list[dict[str, Any]],
    budget: CallBudget,
    trail: _Trail,
    ports: PrefillPorts,
) -> dict[str, Any]:
    """What the wizard's rubro step and ¿Tienes logo? «Mi foto de perfil es mi logo»
    would fill for an account whose operator has typed nothing yet."""
    sector = seed.niches[0] if seed.niches else ""
    country_code, city = seed.country_code, seed.city
    sector_label = discovery_seed.NICHE_LABELS.get(sector, "")
    account = from_profile.AccountText(
        handle=str(profile.get("username", "")),
        bio=str(profile.get("bio") or ""),
        category=str(profile.get("category") or ""),
        captions=tuple(str(c) for c in profile.get("recentCaptions") or ()),
        used_hashtags=tuple(str(t) for t in profile.get("topHashtags") or ()),
        rubro=sector_label,
        city=city,
        country=discovery_seed.country_name(country_code) if country_code else "",
    )
    rubro, created = propose_rubro(
        account, budget=budget, trail=trail, generate=ports.generate, api_key=ports.api_key
    )
    account = replace(account, rubro=", ".join(p for p in (sector_label, rubro) if p))
    answered = discovery_seed.seed_from_profile(
        profile, sector=sector, rubro_text=rubro, country_code=country_code, city=city
    )
    choice, _note = hashtags_db_first(
        tenant_id,
        answered,
        account,
        network=network,
        created=created,
        catalog=ports.catalog,
        remember=False,  # a proposal teaches the shared catalog nothing until approved
        budget=budget,
        trail=trail,
        generate=ports.generate,
        api_key=ports.api_key,
    )
    data = _picture(profile, ports)
    palette = _palette(data)
    picture = _keep_picture(tenant_id, brand_id, profile, data, ports)
    account_doc = profile_document(profile, metrics)
    # m-24852537: what is promoted points at the R2 copy, never at the expiring CDN link
    account_doc["pic"] = ""
    account_doc["pic_key"] = picture.get("key", "")
    account_doc["pic_content_type"] = picture.get("content_type", "")
    return {
        "connect": {
            "network": network,
            "username": str(profile.get("username", "")),
            "sector": sector,
            "rubro_text": rubro,
            "country_code": country_code,
            "city": city,
            "hashtags": pills_from_choice(choice) if choice is not None else [],
        },
        "profile": account_doc,
        "palette": palette,
        "picture": picture,
    }


def _picture(profile: Mapping[str, Any], ports: PrefillPorts) -> bytes | None:
    """The profile picture's bytes, downloaded ONCE from the network's CDN, when it is a
    real picture (not the network's default silhouette) — or None."""
    url = str(profile.get("profilePicUrl", ""))
    if not url or logo_palette.is_default_avatar_url(url):
        return None
    try:
        with httpx.Client(transport=ports.transport) as client:  # redirects: by hand
            data = ports.fetch_picture(url, client)
    except Exception as exc:  # noqa: BLE001 - an optional proposal never fails the run
        logger.info("brand prefill: profile picture unavailable: %s", type(exc).__name__)
        return None
    return data if picture_is_real(url, data) else None


def _palette(data: bytes | None) -> dict | None:
    """The profile picture's colours: what «Mi foto de perfil es mi logo» puts in the
    palette."""
    if not data:
        return None
    try:
        palette, colours = logo_colours_update("", [], data)
    except Exception as exc:  # noqa: BLE001 - an unreadable picture contributes nothing
        logger.info("brand prefill: palette not extracted: %s", type(exc).__name__)
        return None
    if not colours:
        return None
    return {"palette": palette, "logo_colors": colours, "logo_source": LOGO_SOURCE_PROFILE}


#: `proposal.picture.status`: kept in R2, could not be kept, or no real picture at all.
PICTURE_KEPT = "kept"
PICTURE_MISSING = "missing"
PICTURE_NONE = "none"


def _keep_picture(
    tenant_id: UUID,
    brand_id: UUID,
    profile: Mapping[str, Any],
    data: bytes | None,
    ports: PrefillPorts,
) -> dict[str, Any]:
    """The same bytes the palette read, copied to the brand's R2 prefix (m-24852537).
    Never raises: a copy that fails is `missing`, and the proposal is written anyway.
    The CDN link is not in here: it is provenance only (`_picture_provenance`)."""
    if not data:
        return {"status": PICTURE_NONE}
    try:
        kept = ports.pictures.keep(tenant_id, brand_id, kept_pictures.KIND_PROFILE, data)
    except Exception as exc:  # noqa: BLE001 - the picture is optional, the run is not
        logger.warning("brand prefill: profile picture not kept: %s", type(exc).__name__)
        return {"status": PICTURE_MISSING}
    if not kept_pictures.is_kept_key(tenant_id, brand_id, kept.key):
        logger.warning("brand prefill: kept picture key outside the brand prefix, dropped")
        return {"status": PICTURE_MISSING}
    return {
        "status": PICTURE_KEPT,
        "key": kept.key,
        "content_type": kept.content_type,
        "sha256": kept.sha256,
        "bytes": kept.size,
    }


def _picture_provenance(result: PrefillResult) -> dict[str, Any] | None:
    """Where the kept picture came from: the CDN link (only here), its hash and size."""
    picture = (result.proposal or {}).get("picture")
    if not isinstance(picture, Mapping):
        return None
    return {
        "store": "r2",
        "keeper": kept_pictures.__name__,
        "source_url": str((result.profile or {}).get("profilePicUrl", "")),
        **{k: picture[k] for k in ("status", "sha256", "bytes") if k in picture},
    }


def _write_status(
    tenant_id: UUID,
    brand_id: UUID,
    result: PrefillResult,
    ports: PrefillPorts,
    source: Mapping[str, Any] | None,
    propose: bool,
    endpoints: list[str],
    fetched_live: bool,
    trail: _Trail | None = None,
) -> bool:
    """`connect.prefill` ← this run (outcome, proposal, provenance, usage), the rest of
    `connect` and `profile` as they were. Only when proposing — the wizard's read
    writes nothing. False when it could not be written (logged, never raised)."""
    if not propose:
        return False
    document: dict[str, Any] = {
        "version": PREFILL_VERSION,
        "status": result.outcome.value,
        "state": STATE_PROPOSED if result.proposal is not None else "",
        "network": result.network,
        "username": result.handle.lstrip("@").lower(),
        "created_at": datetime.now(UTC).isoformat(),
        "proposal": result.proposal,
        "usage": result.usage.as_document(),
        "provenance": {
            "pipeline": "qualify_api.creative.brand_prefill",
            "pipeline_version": PREFILL_VERSION,
            "read": {
                "provider": "scrapecreators",
                "client": scrapecreators_client.__name__,
                "snapshot_schema": scrapecreators_client.SNAPSHOT_SCHEMA,
                "from_cache": result.profile is not None and not fetched_live,
                "endpoints": list(endpoints),
                "fetched_at": (result.profile or {}).get("fetchedAt"),
            },
            "claude": list(trail.runs) if trail is not None else [],
            "palette": (
                {"extractor": logo_palette.__name__, "max_colours": logo_palette.MAX_COLOURS}
                if result.proposal and result.proposal.get("palette")
                else None
            ),
            # m-24852537: where the R2 copy came from (the CDN link, kept only here)
            "picture": _picture_provenance(result),
            "source": dict(source) if source else None,
        },
    }
    try:
        # only the `prefill` key, atomically: the owner's own answers in `connect` are
        # whatever the database holds at the write, never a copy read earlier
        written = ports.store.set_document_key(
            tenant_id=tenant_id,
            brand_id=brand_id,
            document=PREFILL_DOCUMENT,
            key=PREFILL_KEY,
            value=document,
            # m-24852199: a proposal the owner already decided stays decided
            keep_current=is_decided,
        )
    except (SQLAlchemyError, ValueError) as exc:
        logger.warning("brand prefill: proposal not written: %s", exc)
        return False
    if written is False:
        logger.info("brand prefill: proposal already decided by the owner, kept")
        return False
    return True


__all__ = [
    "CHOSEN_HASHTAGS",
    "DEFAULT_CAPS",
    "PREFILL_KEY",
    "PICTURE_KEPT",
    "PICTURE_MISSING",
    "PICTURE_NONE",
    "PREFILL_VERSION",
    "STATE_PROPOSED",
    "CallBudget",
    "CallCaps",
    "CatalogHashtags",
    "ClaudeCapReached",
    "HashtagCatalog",
    "HashtagChoice",
    "PrefillOutcome",
    "PrefillPorts",
    "PrefillResult",
    "PrefillUsage",
    "RepositoryProfileCache",
    "fetch_picture",
    "format_followers",
    "generate_from_account",
    "hashtags_db_first",
    "logo_colours_update",
    "picture_allowed",
    "picture_is_real",
    "pills_from_choice",
    "prefill_brand_kit",
    "profile_document",
    "propose_rubro",
]
