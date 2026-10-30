"""Selected Brand Kit images frozen per revision, before any paid generation.

The source key identifies the live selection. A private draft copy and SHA256 preserve
the bytes on replay even if the owner replaces/deletes the source afterwards.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from PIL import Image
from pydantic import BaseModel, ConfigDict

from qualify_api.creative.brand_kit_store import BrandAsset
from qualify_api.privacy import strip_phones

BRAND_REFERENCE_BLOCK_VERSION = 2
NEUTRAL_NOTE = "integrate naturally, preserving its identity, colors and proportions"
BrandAssetReader = Callable[[UUID, UUID], list[BrandAsset]]


class BrandReferenceRole(StrEnum):
    ELEMENTO_DE_MARCA = "elemento_de_marca"
    PERSONAJE_PRESENTADOR = "personaje_presentador"
    FIRMA_OVERLAY = "firma_overlay"


class BrandReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    rol: BrandReferenceRole = BrandReferenceRole.ELEMENTO_DE_MARCA
    asset_key: str
    snapshot_key: str = ""
    fingerprint: str = ""
    label: str = ""
    note: str = ""
    content_type: str = ""
    asset_kind: str = ""
    asset_slot: str = ""
    selected_logo: bool = False

    @property
    def effective_note(self) -> str:
        return self.note or NEUTRAL_NOTE


class BrandReferencesSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    refs: tuple[BrandReference, ...] = ()
    overlay: BrandReference | None = None
    # Missing version/asset metadata identifies a legacy frozen snapshot.
    block_version: int = 1


@dataclass(frozen=True)
class BrandReferenceImage:
    reference: BrandReference
    image: bytes


class BrandReferenceError(ValueError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


MISSING_RESOURCE = (
    "Uno de los recursos de tu marca cambió o fue eliminado. Vuelve a elegirlo antes de generar."
)
INVALID_IMAGE = "Uno de los recursos de tu marca no es una imagen válida. Elige otra imagen."


def _clean(value: str) -> str:
    return " ".join(strip_phones(value).split())


def resolve_brand_references(
    reader: BrandAssetReader | None,
    *,
    tenant_id: UUID,
    brand_id: UUID,
    brand_logo_key: str | None,
    brand_element_keys: Sequence[str],
    logo_in_scene: bool = False,
) -> BrandReferencesSet:
    """Validate LIVE rows scoped to this brand, before reading any objects.

    Legacy callers without a reader can compose a logo locally, but cannot silently
    accept references. Production always supplies the reader.
    """
    if not brand_logo_key and not brand_element_keys:
        return BrandReferencesSet()
    if reader is None:
        if brand_element_keys or logo_in_scene:
            raise BrandReferenceError("No pudimos leer tus recursos de marca. Inténtalo de nuevo.")
        return BrandReferencesSet()
    selected_keys = set(brand_element_keys)
    if brand_logo_key:
        selected_keys.add(brand_logo_key)
    assets: dict[str, BrandAsset] = {}
    for asset in reader(tenant_id, brand_id):
        previous = assets.get(asset.object_key)
        if (
            asset.object_key in selected_keys
            and previous is not None
            and (previous.kind, previous.slot) != (asset.kind, asset.slot)
        ):
            raise BrandReferenceError(
                "Este recurso tiene más de una categoría. "
                "Guárdalo en una sola categoría y vuelve a elegirlo."
            )
        assets[asset.object_key] = asset

    def descriptor(key: str, role: BrandReferenceRole) -> BrandReference:
        asset = assets.get(key)
        if asset is None:
            raise BrandReferenceError(MISSING_RESOURCE)
        mime = asset.content_type.lower()
        if not mime:
            mime = next(
                (
                    m
                    for ext, m in (
                        (".png", "image/png"),
                        (".jpg", "image/jpeg"),
                        (".jpeg", "image/jpeg"),
                        (".webp", "image/webp"),
                    )
                    if key.lower().endswith(ext)
                ),
                "",
            )
        if not mime.startswith("image/") or asset.kind == "font":
            raise BrandReferenceError(INVALID_IMAGE)
        return BrandReference(
            rol=role,
            asset_key=key,
            label=_clean(asset.label or asset.filename or "Recurso de marca"),
            note=_clean(asset.context or ""),
            content_type=mime,
            asset_kind=asset.kind,
            asset_slot=asset.slot,
        )

    refs = [
        descriptor(key, BrandReferenceRole.ELEMENTO_DE_MARCA)
        for key in dict.fromkeys(brand_element_keys)
    ]
    overlay = None
    if brand_logo_key:
        logo_asset = assets.get(brand_logo_key)
        if logo_asset is not None and logo_asset.kind not in {"logo", "logo_version"}:
            raise BrandReferenceError("Elige un logo guardado en la identidad de tu marca.")
        logo = descriptor(
            brand_logo_key,
            BrandReferenceRole.ELEMENTO_DE_MARCA
            if logo_in_scene
            else BrandReferenceRole.FIRMA_OVERLAY,
        )
        if logo_in_scene:
            logo = logo.model_copy(update={"selected_logo": True})
            existing = next(
                (index for index, ref in enumerate(refs) if ref.asset_key == logo.asset_key), None
            )
            if existing is not None:
                refs[existing] = logo
            else:
                refs.append(logo)
        else:
            overlay = logo
    return BrandReferencesSet(
        refs=tuple(refs), overlay=overlay, block_version=BRAND_REFERENCE_BLOCK_VERSION
    )


def snapshot_brand_references(
    selected: BrandReferencesSet,
    *,
    read: Callable[[str], bytes],
    keep: Callable[[str, bytes], str],
    owned: Callable[[str], bool],
) -> BrandReferencesSet:
    """Capture only validated tenant keys; draft copies share the output's lifetime."""
    all_refs = (*selected.refs, *((selected.overlay,) if selected.overlay else ()))
    if any(not owned(ref.asset_key) for ref in all_refs):
        raise BrandReferenceError(MISSING_RESOURCE)
    captured: dict[str, tuple[str, str]] = {}

    def capture(ref: BrandReference) -> BrandReference:
        if ref.asset_key not in captured:
            try:
                data = read(ref.asset_key)
                with Image.open(io.BytesIO(data)) as image:
                    image.verify()
            except (OSError, ValueError) as exc:
                raise BrandReferenceError(INVALID_IMAGE) from exc
            digest = hashlib.sha256(data).hexdigest()
            captured[ref.asset_key] = (keep(digest, data), digest)
        key, digest = captured[ref.asset_key]
        return ref.model_copy(update={"snapshot_key": key, "fingerprint": digest})

    return selected.model_copy(
        update={
            "refs": tuple(capture(ref) for ref in selected.refs),
            "overlay": capture(selected.overlay) if selected.overlay else None,
        }
    )


def read_brand_reference_images(
    read: Callable[[str], bytes], refs: Sequence[BrandReference]
) -> list[BrandReferenceImage]:
    result = []
    for ref in refs:
        data = read(ref.snapshot_key)
        if hashlib.sha256(data).hexdigest() != ref.fingerprint:
            raise BrandReferenceError("Una imagen de esta generación cambió. Vuelve a generar.")
        result.append(BrandReferenceImage(ref, data))
    return result


def brand_reference_block(
    refs: Sequence[BrandReference],
    *,
    base_index: int,
    video: bool = False,
    numbered: bool = True,
) -> str:
    lines = []
    for offset, ref in enumerate(refs):
        name = f"Image {base_index + offset}" if numbered else "The element in the scene"
        preservation = (
            "Preserve identity, colors and proportions; do not recast as product, "
            "presenter or printed instructions."
        )
        if ref.rol is BrandReferenceRole.PERSONAJE_PRESENTADOR and ref.asset_kind:
            preservation = (
                "Preserve the presenter's identity and instructed actions; do not recast "
                "as product or decorative brand element."
            )
        elif ref.asset_kind in {"logo", "logo_version"}:
            category = ref.asset_slot if ref.asset_kind == "logo_version" else ""
            rules = {
                "logotipo": "Keep the exact wordmark and lettering; do not add a symbol.",
                "isotipo": "Keep only the selected symbol; do not invent or add lettering.",
                "imagotipo": (
                    "Keep the chosen symbol-and-wordmark lockup; separate only if the usage "
                    "note explicitly allows it."
                ),
                "isologo": (
                    "Keep the inseparable symbol-and-wordmark unit and its proportions; "
                    "never split or rearrange it."
                ),
            }
            rule = rules.get(category, "Keep the whole selected logo; do not guess its category.")
            preservation = (
                f"Brand Kit category: {category or 'unspecified'}. {rule} "
                "Preserve colors and proportions; do not turn it into a product or presenter."
            )
        lines.append(
            f"{name}: {ref.label} ({ref.rol.value}). Usage: {ref.effective_note}. {preservation}"
        )
    if video and refs:
        lines.append(
            "Maintain each element's identity and instructed presence/action "
            "throughout the relevant shots, including cuts; do not morph or omit it."
        )
    return " ".join(lines)
