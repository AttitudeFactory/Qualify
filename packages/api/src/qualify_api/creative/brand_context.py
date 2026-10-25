"""The business context the generator reads beside the kit (§ request 2026-10-01: "que
lo que se guarda en el brandkit lo use como contexto"), built from what finishing the
Brand Kit saved (`brand_kit_store`) and from the referentes the operator sorted.

`build_context` is pure (tested offline); `DbBrandContextReader` only reads. Kept small
on purpose: the prompt's prefix is cached, so it carries the standing facts — rubro,
location, hashtags, the account, the brandboard's elements, the top referentes,
competitors and detractors — not a dump of everything stored.

Each sorted account carries what the discovery learned about it (§ request 2026-10-06:
the handle alone told the model who, never why): its kind, the review of why it fits,
the operator's note and a sample of its own words, each one line and capped."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from qualify_creative.schemas import BrandAccount, BrandContext, BrandElement

from qualify_api.creative.brand_kit_store import (
    EXTRA,
    FONT,
    LOGO_VERSION,
    BrandAsset,
    BrandKitDetails,
    BrandKitStore,
)
from qualify_api.privacy import strip_phones

#: How many of each list reach the prompt (the most influential first).
MAX_ACCOUNTS = 8
#: Characters of each account text (review, note, sample) that reach the prompt.
MAX_ACCOUNT_TEXT = 160
MAX_HASHTAGS = 12
_VERSION_NAMES = {
    "logotipo": "Logotipo",
    "isotipo": "Isotipo",
    "imagotipo": "Imagotipo",
    "isologo": "Isologo",
}


def _line(value: Any) -> str:
    """One line, capped: the prompt is a list, and a caption may carry newlines. Its
    phone numbers are removed first (m-24854323), so a cut never leaves part of one."""
    text = " ".join(strip_phones(str(value or "")).split())
    return text if len(text) <= MAX_ACCOUNT_TEXT else text[: MAX_ACCOUNT_TEXT - 1].rstrip() + "…"


def _accounts(
    labels: Iterable[Any], label: str, found: Mapping[tuple[str, str], Any]
) -> tuple[BrandAccount, ...]:
    """The accounts with `label`, in influence order — the ones never ordered after, by
    network and handle so the cached prefix stays byte-stable — each with its card from
    the discovery (`found`, keyed by `(network, handle)`; an account typed by hand and
    never found keeps just its handle)."""
    chosen = [item for item in labels if getattr(item, "label", "") == label]
    chosen.sort(
        key=lambda item: (item.position is None, item.position or 0, item.network, item.handle)
    )
    out: list[BrandAccount] = []
    for item in chosen[:MAX_ACCOUNTS]:
        account = found.get((item.network, item.handle))
        card: Mapping[str, Any] = getattr(account, "card", None) or {}
        sample = card.get("blurb") or getattr(account, "bio", "") or card.get("bio")
        out.append(
            BrandAccount(
                handle=f"@{str(item.handle).lstrip('@')}",
                network=str(item.network),
                kind=_line(card.get("kind")),
                why=_line(card.get("review")),
                note=_line(card.get("note")),
                sample=_line(sample),
            )
        )
    return tuple(out)


def _elements(assets: Iterable[BrandAsset]) -> tuple[BrandElement, ...]:
    out: list[BrandElement] = []
    for asset in assets:
        if asset.kind == FONT:
            continue  # a type face, not a thing that appears in a piece
        if asset.kind == LOGO_VERSION:
            name = _VERSION_NAMES.get(asset.slot, asset.slot.title())
        elif asset.kind == EXTRA:
            name = asset.label.strip() or asset.filename or "Elemento de marca"
        else:
            name = "Logo"
        out.append(
            BrandElement(
                name=name,
                context=asset.context.strip(),
                key=asset.object_key,
                kind="element" if asset.kind == EXTRA else "logo",
            )
        )
    return tuple(out)


def build_context(
    details: BrandKitDetails,
    assets: Iterable[BrandAsset],
    labels: Iterable[Any],
    found: Mapping[tuple[str, str], Any] | None = None,
) -> BrandContext | None:
    connect: Mapping[str, Any] = details.connect
    profile: Mapping[str, Any] = details.profile
    labels = list(labels)
    location = ", ".join(
        part
        for part in (str(connect.get("city", "")), str(connect.get("country_code", "")))
        if part
    )
    hashtags = tuple(
        str(item.get("tag", "")).lstrip("#")
        for item in connect.get("hashtags", [])
        if isinstance(item, Mapping) and item.get("tag")
    )[:MAX_HASHTAGS]
    context = BrandContext(
        sector=strip_phones(str(connect.get("rubro_text") or connect.get("sector") or "")),
        location=location,
        hashtags=hashtags,
        # m-24854323: generation (Claude copy, angles, BytePlus scenes) never sees a
        # number — not even masked, which a copy model could print into a publication;
        # a bio saved before the masking, or typed by hand, is cleaned here too
        account_bio=strip_phones(str(profile.get("bio", ""))),
        account_category=strip_phones(str(profile.get("category", ""))),
        elements=_elements(assets),
        referentes=_accounts(labels, "referente", found or {}),
        competitors=_accounts(labels, "competencia", found or {}),
        detractors=_accounts(labels, "detractor", found or {}),
    )
    return None if context.is_empty else context


class DbBrandContextReader:
    """``BrandContextReader`` over the Brand Kit's saved details/assets and the
    referentes' labels (RLS-scoped reads only)."""

    def __init__(self, store: BrandKitStore | None = None, referentes: Any = None) -> None:
        self._store = store or BrandKitStore()
        self._referentes = referentes

    def _labels(self, tenant_id: UUID, brand_id: UUID) -> list[Any]:
        if self._referentes is None:
            from qualify_api.referentes import PostgresReferentesRepository  # noqa: PLC0415

            self._referentes = PostgresReferentesRepository()
        return list(self._referentes.labels(tenant_id=tenant_id, brand_id=brand_id))

    def context(self, *, tenant_id: UUID, brand_id: UUID) -> BrandContext | None:
        labels = self._labels(tenant_id, brand_id)
        # each sorted account as the discovery last stored it — its review, the
        # operator's note, a sample of what it posts (the cards behind the sort)
        found = self._referentes.latest_accounts(
            tenant_id=tenant_id,
            brand_id=brand_id,
            identities=[(item.network, item.handle) for item in labels],
        )
        return build_context(
            self._store.load_details(tenant_id=tenant_id, brand_id=brand_id),
            self._store.list_assets(tenant_id=tenant_id, brand_id=brand_id),
            labels,
            found,
        )
