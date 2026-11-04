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
from qualify_creative.schemas import MAX_BRAND_ELEMENTS

from qualify_api.creative.brand_kit_store import BrandAsset
from qualify_api.privacy import strip_phones

BRAND_REFERENCE_BLOCK_VERSION = 5
SEMANTIC_BRAND_REFERENCE_BLOCK_VERSION = 9
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
    additional_logo: bool = False
    # Missing metadata belongs to the original v2 compiler, never today's rules.
    instruction_version: int = 2

    @property
    def effective_note(self) -> str:
        return self.note or NEUTRAL_NOTE


class BrandReferencesSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    refs: tuple[BrandReference, ...] = ()
    overlay: BrandReference | None = None
    # Missing version/asset metadata identifies a legacy frozen snapshot.
    selection: dict = {}
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


def _reference_label(asset: BrandAsset) -> str:
    """The name a resource goes by in the selector and the prompts: the owner's label,
    else — for a logo — the name the picker shows (its version's slot, «Logo» for the
    main one). A logo version's upload filename is not its name: draft 35a5918b
    (2026-11-03) sent the «Imagotipo» to the selector as «isologo.png»."""
    if asset.label.strip():
        return asset.label
    if asset.kind == "logo_version" and asset.slot.strip():
        return asset.slot.replace("_", " ").strip().capitalize()
    if asset.kind == "logo":
        return "Logo"
    return asset.filename or "Recurso de marca"


def resolve_brand_references(
    reader: BrandAssetReader | None,
    *,
    tenant_id: UUID,
    brand_id: UUID,
    brand_logo_key: str | None,
    brand_element_keys: Sequence[str],
    brand_logo_reference_keys: Sequence[str] = (),
    logo_in_scene: bool = False,
) -> BrandReferencesSet:
    """Validate LIVE rows scoped to this brand, before reading any objects.

    Legacy callers without a reader can compose a logo locally, but cannot silently
    accept references. Production always supplies the reader.
    """
    if not brand_logo_key and not brand_element_keys and not brand_logo_reference_keys:
        return BrandReferencesSet()
    secondary_logos = tuple(dict.fromkeys(brand_logo_reference_keys))
    if brand_logo_key in secondary_logos and not logo_in_scene:
        raise BrandReferenceError("Elegiste el mismo logo dos veces. Déjalo marcado una sola vez.")
    additional = (set(brand_element_keys) | set(secondary_logos)) - {brand_logo_key}
    if len(additional) > MAX_BRAND_ELEMENTS:
        raise BrandReferenceError("Elige hasta seis recursos adicionales de tu marca.")
    if reader is None:
        if brand_element_keys or secondary_logos or logo_in_scene:
            raise BrandReferenceError("No pudimos leer tus recursos de marca. Inténtalo de nuevo.")
        return BrandReferencesSet()
    selected_keys = set(brand_element_keys) | set(secondary_logos)
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
                f"No sabemos si «{_clean(_reference_label(asset))}» es un logo o una imagen "
                "de tu marca. Arréglalo en Tu marca y vuelve a elegirlo."
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
            instruction_version=BRAND_REFERENCE_BLOCK_VERSION,
            rol=role,
            asset_key=key,
            label=_clean(_reference_label(asset)),
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
    for key in secondary_logos:
        if key == brand_logo_key and logo_in_scene:
            continue
        asset = assets.get(key)
        if asset is not None and asset.kind not in {"logo", "logo_version"}:
            raise BrandReferenceError("Elige un logo guardado en la identidad de tu marca.")
        logo = descriptor(key, BrandReferenceRole.ELEMENTO_DE_MARCA)
        existing = next((index for index, ref in enumerate(refs) if ref.asset_key == key), None)
        authority = not any(ref.selected_logo for ref in refs)
        if existing is not None:
            refs[existing] = refs[existing].model_copy(
                update={
                    "selected_logo": refs[existing].selected_logo or authority,
                    "additional_logo": True,
                }
            )
        else:
            refs.append(
                logo.model_copy(update={"selected_logo": authority, "additional_logo": True})
            )
    return BrandReferencesSet(
        refs=tuple(refs), overlay=overlay, block_version=BRAND_REFERENCE_BLOCK_VERSION
    )


def snapshot_brand_references(
    selected: BrandReferencesSet,
    *,
    read: Callable[[str], bytes],
    keep: Callable[[str, bytes], str],
    owned: Callable[[str], bool],
    keep_typed: Callable[[str, bytes, str], str] | None = None,
) -> BrandReferencesSet:
    """Capture only validated tenant keys; draft copies share the output's lifetime.
    `keep_typed` (preferred) also gets the resource's own content type, so a JPEG or WebP
    logo is not stored as PNG (review nit #9)."""
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
            stored = (
                keep_typed(digest, data, ref.content_type or "application/octet-stream")
                if keep_typed is not None
                else keep(digest, data)
            )
            captured[ref.asset_key] = (stored, digest)
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
    if refs and all(ref.instruction_version >= 7 for ref in refs):
        block = _selective_brand_reference_block(refs, base_index, video, numbered)
        return block.replace(
            "Consider ALL candidates; use only needed ones, possibly none. "
            "Honor operator/usage notes; otherwise prefer one logo. Never force all.",
            "Integrate EVERY reference below in its own role; none is optional. "
            "Honor usage notes. Logo alternatives were already resolved. "
            "Keep logos on suitable existing surfaces; no invented marks/props.",
            1,
        )
    if refs and all(ref.instruction_version >= 6 for ref in refs):
        block = _selective_brand_reference_block(refs, base_index, video, numbered)
        return block.replace(
            "Consider ALL candidates; use only needed ones, possibly none. "
            "Honor operator/usage notes; otherwise prefer one logo. Never force all.",
            "Only these resources were required by the scene plan. Integrate them on "
            "existing suitable surfaces, honoring operator/usage notes. "
            "Do not add other marks or invent props to display them.",
            1,
        )
    if refs and all(ref.instruction_version >= 5 for ref in refs):
        return _selective_brand_reference_block(refs, base_index, video, numbered)
    if refs and all(ref.instruction_version >= 4 for ref in refs):
        return _v4_brand_reference_block(refs, base_index, video, numbered)
    if any(ref.additional_logo for ref in refs):
        return _compact_brand_reference_block(refs, base_index, video, numbered)
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


#: Prompt compiler 2 (2026-11-03, audit `auditoria-prompts-clip-20261103.md` H3): what each
#: logo category means, in plain words the video model can follow — no aliases, no notes
#: about earlier steps («already resolved»), no filenames (the model never sees them).
_LOGO_CATEGORY_V2 = {
    "logotipo": "logotipo: the brand name in its own lettering; do not add a symbol",
    "isotipo": "isotipo: the symbol alone; do not add any lettering",
    "imagotipo": (
        "imagotipo: the symbol and the name together; keep their layout and proportions "
        "unless its usage note asks for a change"
    ),
    "isologo": "isologo: the symbol and the name fused into one unit; never split or rearrange it",
}
_LOGO_CATEGORY_UNKNOWN_V2 = "its category is not given: keep the whole image exactly as supplied"


def _v2_text(text: str) -> str:
    return " ".join(text.split()).replace('"', "'")


def _v2_resource(ref: BrandReference) -> str:
    """What one chosen resource is, in plain words (compiler 2), without its index."""
    if ref.asset_kind in {"logo", "logo_version"}:
        category = ref.asset_slot if ref.asset_kind == "logo_version" else ""
        what = (
            "the client's logo"
            if ref.selected_logo
            else "an alternative version of the client's logo, used only if its usage note "
            "asks for it"
        )
        return f"{what} ({_LOGO_CATEGORY_V2.get(category, _LOGO_CATEGORY_UNKNOWN_V2)})"
    label = _v2_text(ref.label) or "a brand resource"
    if ref.rol is BrandReferenceRole.PERSONAJE_PRESENTADOR:
        return f'the presenter, "{label}": keep their identity and the actions asked of them'
    return f'"{label}", a brand element: not the product and not a presenter'


def _v2_note(ref: BrandReference) -> str:
    note = _v2_text(ref.note)
    return f' Usage note (in Spanish): "{note}".' if note else ""


def brand_reference_block_v2(
    refs: Sequence[BrandReference],
    *,
    base_index: int,
    prefix: str | None = "Image",
    already_in_scene: bool = False,
    still: bool = False,
) -> str:
    """The chosen Brand Kit resources of a Seedance 2.x video at prompt compiler 2 (audit
    2026-11-03 §7.3): each image named with the SAME syntax as the rest of its prompt
    (`prefix` "Image" → «Image 3», "@Image" → «@Image3» in a reel replica), told what it is
    in plain sentences, its usage note literal. `prefix=None`: no image is sent (an animated
    slide animates a photograph that already shows them) — they are only named, to keep.
    `already_in_scene`: they are in the opening scene already (an animated slide): keep
    them, never add another copy. `still` (compiler 3, a Seedream gallery slide): the same
    sentences said of one photograph, with no shots to stay consistent across. "" without
    resources."""
    if not refs:
        return ""
    logos = any(ref.asset_kind in {"logo", "logo_version"} for ref in refs)
    if prefix is None:
        named = "; ".join(_v2_resource(ref) + _v2_note(ref).rstrip(".") for ref in refs)
        return (
            f"The photograph already shows the client's brand resources: {named}. Keep each "
            "one exactly where and as it is while the camera moves; do not add a second logo "
            "or any other mark."
        )
    lines = [
        "The client's brand resources below are already in the scene (Image 1): use them "
        "only to keep those marks exact while the camera moves, and do not add another copy."
        if already_in_scene
        else f"Use every brand image below in the {'photograph' if still else 'video'}, each "
        "in its own role."
    ]
    for offset, ref in enumerate(refs):
        index = base_index + offset
        name = f"{prefix}{index}" if prefix.startswith("@") else f"{prefix} {index}"
        lines.append(f"{name} is {_v2_resource(ref)}.{_v2_note(ref)}")
    if logos and not already_in_scene:
        lines.append(
            "Put each logo on a surface that already exists in the scene, such as packaging, "
            "a sign or a wall, never on food or bare skin, and do not invent props to carry it."
        )
    lines.append(
        "Keep every brand image exactly as supplied, with the same shapes, colors, "
        "proportions and lettering; do not merge two of them and never write a usage note "
        "in the image."
        if still
        else "Keep every brand image exactly as supplied, with the same shapes, colors, "
        "proportions and lettering, and consistent across shots; do not merge two of them "
        "and never write a usage note on screen."
    )
    return " ".join(lines)


def _selective_brand_reference_block(
    refs: Sequence[BrandReference], base_index: int, video: bool, numbered: bool
) -> str:
    """All images inform the model; availability does not mandate visible inclusion."""
    lines = [
        "Consider ALL candidates; use only needed ones, possibly none. "
        "Honor operator/usage notes; otherwise prefer one logo. Never force all."
    ]
    categories: dict[str, None] = {}
    for offset, ref in enumerate(refs):
        index = base_index + offset
        name = f"Image {index}" if numbered else f"Scene resource {offset + 1}"
        if ref.asset_kind in {"logo", "logo_version"}:
            category = ref.asset_slot if ref.asset_kind == "logo_version" else "unspecified"
            alias = f"{'principal' if ref.selected_logo else 'alternative'} {category}"
            categories[category] = None
        else:
            role = (
                "presenter"
                if ref.rol is BrandReferenceRole.PERSONAJE_PRESENTADOR
                else "brand element, not product/presenter"
            )
            alias = f"{ref.label} ({role})"
        lines.append(f"{name}: {alias}." + (f" Usage: {ref.note}." if ref.note else ""))
    rules = {
        "logotipo": "logotipo: exact wordmark, no added symbol.",
        "isotipo": "isotipo: symbol only, no added lettering.",
        "imagotipo": "imagotipo: keep internal layout/proportions unless its note requests change.",
        "isologo": "isologo: inseparable whole; never split/rearrange.",
    }
    lines.extend(
        rules.get(category, "Logo: preserve whole asset; do not guess category.")
        for category in categories
    )
    if categories:
        lines.append("Categories override filenames. Never add logos to food/bare skin.")
    lines.append(
        "Used assets: exact identity/colors/proportions; no merged roles/logos or printed notes."
    )
    if video:
        lines.append("Keep used assets consistent across shots.")
    return " ".join(lines)


def _v4_brand_reference_block(
    refs: Sequence[BrandReference], base_index: int, video: bool, numbered: bool
) -> str:
    """Typed aliases avoid contradictory filenames; stored labels remain provenance."""
    lines = []
    categories: dict[str, None] = {}
    for offset, ref in enumerate(refs):
        index = base_index + offset
        name = f"Image {index}" if numbered else f"Scene resource {offset + 1}"
        if ref.asset_kind in {"logo", "logo_version"}:
            category = ref.asset_slot if ref.asset_kind == "logo_version" else "unspecified"
            authority = "principal" if ref.selected_logo else "secondary"
            alias = f"{authority} {category} logo {index}"
            categories[category] = None
        else:
            alias = ref.label
        role = "presenter" if ref.rol is BrandReferenceRole.PERSONAJE_PRESENTADOR else ""
        lines.append(
            f"{name}: {alias}{' (presenter)' if role else ''}. "
            f"Usage: {ref.note or 'integrate naturally'}."
        )
    rules = {
        "logotipo": "logotipo: exact wordmark, no added symbol.",
        "isotipo": "isotipo: selected symbol only, no added lettering.",
        "imagotipo": (
            "imagotipo: preserve original internal layout, relative positions/proportions; "
            "separate/rearrange only if its usage explicitly requests it."
        ),
        "isologo": "isologo: inseparable whole; never split/rearrange, even if a note asks.",
    }
    lines.extend(
        rules.get(category, "Logo: preserve whole asset; do not guess its category.")
        for category in categories
    )
    if categories:
        lines.append(
            "Typed category overrides filenames/labels elsewhere. Whole-logo perspective/rotation "
            "is allowed. No newly painted logos on food/bare skin unless usage explicitly asks; "
            "preserve existing manufacturer labels."
        )
    lines.append(
        "Keep exact identities/colors/proportions and distinct roles; "
        "never merge logos or print notes."
    )
    if video:
        lines.append("Keep resources recognizable on intended surfaces/shots across cuts.")
    return " ".join(lines)


def _compact_brand_reference_block(
    refs: Sequence[BrandReference], base_index: int, video: bool, numbered: bool
) -> str:
    """Deduplicate scaffolding, never an operator's note or a resource descriptor."""
    lines = []
    current = all(ref.instruction_version >= 3 for ref in refs)
    categories: dict[str, None] = {}
    for offset, ref in enumerate(refs):
        name = f"Image {base_index + offset}" if numbered else f"Scene resource {offset + 1}"
        role = (
            "presenter" if ref.rol is BrandReferenceRole.PERSONAJE_PRESENTADOR else "brand element"
        )
        lines.append(
            f"{name}: {ref.label} [{ref.asset_kind}/{ref.asset_slot}; {role}]. "
            f"Usage: {ref.note or ('integrate naturally' if current else 'preserve identity')}."
        )
        if ref.asset_kind in {"logo", "logo_version"}:
            categories[ref.asset_slot if ref.asset_kind == "logo_version" else ""] = None
    rules = {
        "logotipo": "logotipo: exact wordmark, no added symbol.",
        "isotipo": "isotipo: chosen symbol only, no added lettering.",
        "imagotipo": "imagotipo: chosen lockup; separate only if its note allows.",
        "isologo": "isologo: inseparable whole, never split or rearrange.",
    }
    lines.extend(
        rules.get(category, "Logo: preserve the whole asset; do not guess its category.")
        for category in categories
    )
    lines.append(
        "Show every chosen resource naturally in its role, with exact colors/proportions; "
        "never merge logos, swap product/presenter/element roles or print notes."
        if current
        else "Keep distinct identities/colors/proportions; never merge logo variants, "
        "swap product/presenter/element roles or print notes."
    )
    if video:
        lines.append(
            "Keep each resource recognizable and present on its intended surfaces/shots, "
            "across cuts."
            if current
            else "Maintain each resource's instructed identity, presence and action across cuts."
        )
    return " ".join(lines)
