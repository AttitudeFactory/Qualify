"""The business context the generator reads beside the kit (§ request 2026-10-01: "que
lo que se guarda en el brandkit lo use como contexto"), built from what finishing the
Brand Kit saved (`brand_kit_store`) and from the referentes the operator sorted.

`build_context` is pure (tested offline); `DbBrandContextReader` only reads. Kept small
on purpose: the prompt's prefix is cached, so it carries the standing facts — rubro,
location, hashtags, the account, the brandboard's elements, the top referentes and
competitors — not a dump of everything stored."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from qualify_creative.schemas import BrandContext, BrandElement

from qualify_api.creative.brand_kit_store import (
    EXTRA,
    LOGO_VERSION,
    BrandAsset,
    BrandKitDetails,
    BrandKitStore,
)

#: How many of each list reach the prompt (the most influential first).
MAX_ACCOUNTS = 8
MAX_HASHTAGS = 12
_VERSION_NAMES = {
    "logotipo": "Logotipo",
    "isotipo": "Isotipo",
    "imagotipo": "Imagotipo",
    "isologo": "Isologo",
}


def _accounts(labels: Iterable[Any], label: str) -> tuple[str, ...]:
    """`@handle (network)` of the accounts with `label`, in influence order (the ones
    never ordered after, as found)."""
    chosen = [item for item in labels if getattr(item, "label", "") == label]
    chosen.sort(key=lambda item: (item.position is None, item.position or 0))
    return tuple(
        f"@{str(item.handle).lstrip('@')} ({item.network})" for item in chosen[:MAX_ACCOUNTS]
    )


def _elements(assets: Iterable[BrandAsset]) -> tuple[BrandElement, ...]:
    out: list[BrandElement] = []
    for asset in assets:
        if asset.kind == LOGO_VERSION:
            name = _VERSION_NAMES.get(asset.slot, asset.slot.title())
        elif asset.kind == EXTRA:
            name = asset.label.strip() or asset.filename or "Elemento de marca"
        else:
            name = "Logo"
        out.append(BrandElement(name=name, context=asset.context.strip()))
    return tuple(out)


def build_context(
    details: BrandKitDetails, assets: Iterable[BrandAsset], labels: Iterable[Any]
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
        sector=str(connect.get("rubro_text") or connect.get("sector") or ""),
        location=location,
        hashtags=hashtags,
        account_bio=str(profile.get("bio", "")),
        account_category=str(profile.get("category", "")),
        elements=_elements(assets),
        referentes=_accounts(labels, "referente"),
        competitors=_accounts(labels, "competencia"),
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
        return build_context(
            self._store.load_details(tenant_id=tenant_id, brand_id=brand_id),
            self._store.list_assets(tenant_id=tenant_id, brand_id=brand_id),
            self._labels(tenant_id, brand_id),
        )
