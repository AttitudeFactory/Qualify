"""The bridge between the referentes search and Claude's review of its accounts
(`qualify_api.referentes.ai`, the `revisar_cuentas` tool).

Two jobs:

- `make_reviewer` — the `creator_discovery.AccountReviewer` a search runs with: each
  phase's shortlist goes to Claude, which says per account whether it is a real peer of
  the brand (the ones that are not are dropped) and what it is (marca / creador /
  medio). No API key → no reviewer, and the search runs as before.
- `add_manual_account` — a referente the operator adds by hand because the search
  cannot find it (little activity, few followers, or not on TikTok / Instagram at all).
  Read from the vendor when it is on a network we read, reviewed by the same tool with
  `manual=True` — which never drops it: the operator's call stands, the verdict only
  warns — and returned as a card like any other.

Kept OUT of `creator_discovery.py`: that module's code is fingerprinted as the
algorithm, and how a model is called is not part of it — the algorithm only knows that
a reviewer may drop accounts (`apply_review`).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from qualify_api.claude_tools import CallStats, MissingAPIKey, ModelConfig, api_key_from_env
from qualify_api.referentes import ai as review_ai

from . import creator_discovery
from .creator_discovery import AccountReviewer, AccountVerdict, Candidate, DiscoverySeed

logger = logging.getLogger(__name__)

ReviewFn = Callable[..., tuple[list[review_ai.AccountReview], CallStats]]

#: Networks a manual referente can be on — id → label shown on the card. The label's
#: lowercase is the id for every network but `otro`, which `referentes_provider.
#: card_identity` maps back (`NETWORK_BY_LABEL`).
MANUAL_NETWORKS: dict[str, str] = {
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "facebook": "Facebook",
    "x": "X",
    "linkedin": "LinkedIn",
    "web": "Web",
    "otro": "Sin redes",
}
NETWORK_BY_LABEL: dict[str, str] = {label.lower(): key for key, label in MANUAL_NETWORKS.items()}

#: Networks the vendor reads — a manual account on one of these is looked up.
READABLE_NETWORKS = ("instagram", "tiktok")

MANUAL_REASON = "agregado a mano"

#: Short texts in `Candidate.texts` are Instagram categories, not captions (the same cut
#: `creator_discovery._is_media_outlet` uses).
_CATEGORY_MAX = 60

#: Accounts per review call; a phase's shortlist (≤ 2 × `REVIEW_PER_NETWORK`) goes out as
#: parallel calls of this size (`_review`).
PARALLEL_BATCH = 10


def brand_brief(
    seed: DiscoverySeed,
    *,
    bio: str = "",
    category: str = "",
    positioning: str = "",
    audience: str = "",
) -> review_ai.BrandBrief:
    return review_ai.BrandBrief(
        handle=seed.handle,
        bio=bio,
        category=category,
        rubro=seed.terms,
        niches=tuple(creator_discovery.NICHE_LABELS.get(n, n) for n in seed.niches),
        hashtags=tuple(dict.fromkeys((*seed.hashtags[:3], *seed.steering_hashtags()))),
        city=seed.city,
        country=creator_discovery.country_name(seed.country_code),
        positioning=positioning,
        audience=audience,
    )


def account_id(candidate: Candidate) -> str:
    return f"{candidate.network}:{candidate.username.lower()}"


def to_review(
    candidate: Candidate, *, manual: bool = False, note: str = ""
) -> review_ai.AccountToReview:
    short = [t for t in candidate.texts if t.strip() and len(t) <= _CATEGORY_MAX]
    captions = [t for t in candidate.texts if len(t) > _CATEGORY_MAX and t != candidate.bio]
    return review_ai.AccountToReview(
        id=account_id(candidate),
        network=MANUAL_NETWORKS.get(candidate.network, candidate.network),
        handle=candidate.username,
        name=candidate.full_name,
        bio=candidate.bio,
        category=short[0] if short else "",
        followers=candidate.followers,
        captions=tuple(captions[: review_ai.MAX_CAPTIONS]),
        hashtags=tuple(candidate.hashtags_seen),
        manual=manual,
        note=note,
    )


def _resolve_key(api_key: str | None) -> str | None:
    if api_key:
        return api_key
    try:
        return api_key_from_env()
    except MissingAPIKey:
        return None


def _review(
    brief: review_ai.BrandBrief,
    items: Sequence[review_ai.AccountToReview],
    *,
    api_key: str,
    config: ModelConfig,
    review: ReviewFn,
) -> tuple[dict[str, review_ai.AccountReview], str]:
    """Every item reviewed, in `PARALLEL_BATCH`-sized calls run at the same time: id →
    review, plus the model id. The time of a review is the model writing one verdict per
    account, so two calls of ten finish in about half the time of one of twenty — and the
    operator is waiting on the loading screen for it. A batch that fails fails the whole
    review (the phase then falls back to the unreviewed pick)."""
    batches = [
        list(items[start : start + PARALLEL_BATCH])
        for start in range(0, len(items), PARALLEL_BATCH)
    ]
    if not batches:
        return {}, config.model_id

    def one(batch: list[review_ai.AccountToReview]) -> tuple[list[review_ai.AccountReview], Any]:
        return review(brief, batch, api_key=api_key, config=config)

    with ThreadPoolExecutor(max_workers=len(batches)) as pool:
        answered = list(pool.map(one, batches))
    out: dict[str, review_ai.AccountReview] = {}
    model = config.model_id
    for batch, (reviews, stats) in zip(batches, answered, strict=True):
        model = stats.model_id
        logger.info(
            "referentes review: %d accounts, %d answered, %s, $%.4f",
            len(batch),
            len(reviews),
            stats.model_id,
            stats.cost_usd,
        )
        out.update({r.id: r for r in reviews})
    return out, model


def make_reviewer(
    brief: review_ai.BrandBrief,
    *,
    api_key: str | None = None,
    config: ModelConfig | None = None,
    review: ReviewFn = review_ai.review_accounts,
) -> AccountReviewer | None:
    """The reviewer a search runs with, or None without an API key (the search then
    runs unreviewed, as before version 9)."""
    key = _resolve_key(api_key)
    if key is None:
        return None
    model = config or ModelConfig(review_ai.REVIEW_MODEL, review_ai.REVIEW_EFFORT)

    def reviewer(
        phase_key: str, accounts: list[Candidate]
    ) -> dict[tuple[str, str], AccountVerdict]:
        by_id = {account_id(c): c for c in accounts}
        answers, model_id = _review(
            brief,
            [to_review(c) for c in accounts],
            api_key=key,
            config=model,
            review=review,
        )
        return {
            by_id[r.id].key: AccountVerdict(
                kind=r.kind, fits=r.fits, reason=r.reason, reviewed_by=model_id
            )
            for r in answers.values()
            if r.id in by_id
        }

    return reviewer


# --------------------------------------------------------------------------------------
# manual referentes
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualTarget:
    """What the operator typed, understood: which network, which handle, which link."""

    network: str
    handle: str
    url: str = ""
    #: A readable name when the operator typed one rather than a handle.
    name: str = ""


_URL_NETWORKS: tuple[tuple[str, str], ...] = (
    ("instagram.com", "instagram"),
    ("tiktok.com", "tiktok"),
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("facebook.com", "facebook"),
    ("fb.com", "facebook"),
    ("x.com", "x"),
    ("twitter.com", "x"),
    ("linkedin.com", "linkedin"),
)
#: Path segments that are not the account (`/in/`, `/company/`, `/c/`, `/channel/`…).
_URL_PREFIXES = frozenset({"in", "company", "c", "channel", "user", "pg", "people"})
_HANDLE_RE = re.compile(r"^@?[A-Za-z0-9_.]{1,40}$")


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _name_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(text)).strip("-")[:60]


def _profile_url(network: str, handle: str) -> str:
    return {
        "instagram": f"https://www.instagram.com/{handle}/",
        "tiktok": f"https://www.tiktok.com/@{handle}",
        "youtube": f"https://www.youtube.com/@{handle}",
        "facebook": f"https://www.facebook.com/{handle}",
        "x": f"https://x.com/{handle}",
    }.get(network, "")


def parse_manual(text: str, network: str) -> ManualTarget:
    """The operator's input — a link, `@usuario` / `usuario`, or a plain name for an
    account with no profile we can read — into a `ManualTarget`. A link decides its
    own network; otherwise `network` (the select) does. Raises `ValueError` with a
    message for the operator."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Escribe el usuario, el enlace o el nombre de la cuenta.")
    chosen = network if network in MANUAL_NETWORKS else "instagram"
    looks_like_url = raw.startswith(("http://", "https://", "www.")) or re.match(
        r"^[\w-]+(\.[\w-]+)+/", raw
    )
    if looks_like_url:
        url = raw if raw.startswith("http") else f"https://{raw}"
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
        found = next((net for domain, net in _URL_NETWORKS if host.endswith(domain)), "")
        if not found:
            if not host:
                raise ValueError("Ese enlace no se entiende. Revisa que esté completo.")
            return ManualTarget(network="web", handle=host, url=url, name=host)
        parts = [p for p in parsed.path.split("/") if p and p.lower() not in _URL_PREFIXES]
        if not parts:
            raise ValueError("Ese enlace no lleva a un perfil. Pega el enlace del perfil.")
        handle = parts[0].lstrip("@").lower()
        return ManualTarget(network=found, handle=handle, url=_profile_url(found, handle) or url)
    if chosen in ("web", "otro") or not _HANDLE_RE.match(raw):
        if chosen in READABLE_NETWORKS and " " not in raw:
            raise ValueError("Ese usuario no es válido: solo letras, números, puntos y _.")
        slug = _name_slug(raw)
        if not slug:
            raise ValueError("Escribe un nombre con letras o números.")
        # a name typed with Instagram / TikTok selected is an account we cannot read
        target_network = "otro" if chosen in READABLE_NETWORKS else chosen
        return ManualTarget(
            network=target_network,
            handle=slug,
            url=_profile_url(target_network, slug),
            name=raw,
        )
    handle = raw.lstrip("@").lower()
    return ManualTarget(network=chosen, handle=handle, url=_profile_url(chosen, handle))


@dataclass
class ManualResult:
    """A manual referente, ready for the wizard."""

    card: dict[str, str]
    candidate: Candidate
    #: On a network we read, but the profile does not exist (or is private).
    missing: bool = False
    #: The review ran and said it does not fit — the operator is warned, not blocked.
    warning: str = ""
    errors: list[str] = field(default_factory=list)


LookupFn = Callable[..., tuple[Candidate, bool, str | None]]


def manual_card(candidate: Candidate, target: ManualTarget, *, note: str = "") -> dict[str, str]:
    card = creator_discovery.account_card(candidate)
    card["network"] = MANUAL_NETWORKS.get(target.network, target.network)
    if target.network not in READABLE_NETWORKS:
        # no profile to read: the handle is a slug of what was typed, so show it plain
        card["handle"] = target.handle if target.network in ("web", "otro") else card["handle"]
        card["followers"] = "—"
        card["blurb"] = (note or target.name)[:110]
    elif not card["blurb"] and note:
        card["blurb"] = note[:110]
    card["url"] = card["url"] or target.url
    card["reason"] = MANUAL_REASON
    card["manual"] = "1"
    card["note"] = note
    return card


def add_manual_account(
    target: ManualTarget,
    brief: review_ai.BrandBrief,
    *,
    note: str = "",
    api_key: str | None = None,
    config: ModelConfig | None = None,
    lookup: LookupFn = creator_discovery.lookup_account,
    review: ReviewFn = review_ai.review_accounts,
    store_path: Path | None = creator_discovery.PROFILE_CACHE_PATH,
) -> ManualResult:
    """Look the account up (when it is on a network we read), review it with
    `manual=True`, and build its card. Never raises for a vendor or model failure —
    the operator asked for this account, so it is added with whatever we could learn."""
    errors: list[str] = []
    missing = False
    if target.network in READABLE_NETWORKS:
        candidate, found, error = lookup(target.network, target.handle, store_path=store_path)
        missing = not found
        if error:
            errors.append(error)
    else:
        candidate = Candidate(
            network=target.network,
            username=target.handle,
            full_name=target.name,
            profile_url=target.url,
            sources=[f"{target.network}:manual"],
        )
    warning = ""
    key = _resolve_key(api_key)
    if key is not None:
        model = config or ModelConfig(review_ai.REVIEW_MODEL, review_ai.REVIEW_EFFORT)
        try:
            answers, model_id = _review(
                brief,
                [to_review(candidate, manual=True, note=note)],
                api_key=key,
                config=model,
                review=review,
            )
        except Exception as exc:  # a model failure never blocks a manual add
            logger.warning("manual referente review failed: %s", exc)
            errors.append(f"review: {exc}")
        else:
            answer = answers.get(account_id(candidate))
            if answer is not None:
                candidate.account_kind = answer.kind
                candidate.review_reason = answer.reason
                candidate.reviewed_by = model_id
                if not answer.fits:
                    warning = answer.reason or "La IA cree que esta cuenta no encaja con tu marca."
    card = manual_card(candidate, target, note=note)
    card["fits"] = "no" if warning else ("si" if candidate.reviewed_by else "")
    return ManualResult(
        card=card, candidate=candidate, missing=missing, warning=warning, errors=errors
    )
