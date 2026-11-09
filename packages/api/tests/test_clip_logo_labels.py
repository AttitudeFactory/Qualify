"""Draft 35a5918b (2026-11-03): a clip's logo, named and traced the way the owner sees it.

The owner's «Imagotipo» reached the resource selector labelled with its upload filename
(«isologo.png»), and the Seedance trace said «referencias: ninguna» while the selector had
made that logo a corner signature laid after the video — read as «the logo was dropped».
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from qualify_api.creative.brand_kit_store import BrandAsset
from qualify_api.creative.brand_references import (
    BrandReference,
    BrandReferenceRole,
    BrandReferencesSet,
    resolve_brand_references,
)
from qualify_api.creative.media import _clip_logo_trace

TENANT = uuid4()
BRAND = uuid4()
PREFIX = f"t/{TENANT}/brand/{BRAND}/logo_version"
IMAGOTIPO = f"{PREFIX}/imagotipo/8161_isologo.png"
ISOLOGO = f"{PREFIX}/isologo/0352_Gemini_Generated_Image.jpg"
NAMED = f"{PREFIX}/isotipo/5ea6_imagotipo.png"
MAIN = f"t/{TENANT}/brand/{BRAND}/logo/main.png"
EXTRA = f"t/{TENANT}/brand/{BRAND}/extra/bag.png"


def _reader(tenant: Any, brand: Any) -> list[BrandAsset]:
    return [
        BrandAsset("logo_version", "imagotipo", IMAGOTIPO, "isologo.png", "image/png"),
        BrandAsset("logo_version", "isologo", ISOLOGO, "Gemini_Generated_Image.jpg", "image/jpeg"),
        BrandAsset("logo_version", "isotipo", NAMED, "imagotipo.png", "image/png", "Sello"),
        BrandAsset("logo", "", MAIN, "main.png", "image/png"),
        BrandAsset("extra", "bag", EXTRA, "bag.png", "image/png"),
    ]


def _resolve(**kwargs: Any) -> BrandReferencesSet:
    return resolve_brand_references(
        _reader,
        tenant_id=TENANT,
        brand_id=BRAND,
        **{
            "brand_logo_key": None,
            "brand_element_keys": (),
            "brand_logo_reference_keys": (),
            "logo_in_scene": True,
            **kwargs,
        },
    )


def _labels(refs: BrandReferencesSet) -> dict[str, str]:
    return {ref.asset_key: ref.label for ref in (*refs.refs, *(r for r in [refs.overlay] if r))}


def test_a_logo_version_goes_by_its_slot_not_its_upload_filename() -> None:
    labels = _labels(_resolve(brand_logo_key=IMAGOTIPO, brand_logo_reference_keys=(ISOLOGO,)))

    assert labels[IMAGOTIPO] == "Imagotipo"
    assert labels[ISOLOGO] == "Isologo"


def test_an_owner_label_still_wins_and_the_main_logo_is_logo() -> None:
    labels = _labels(_resolve(brand_logo_key=NAMED, brand_logo_reference_keys=(MAIN,)))

    assert labels[NAMED] == "Sello"
    assert labels[MAIN] == "Logo"


def test_an_unlabelled_element_keeps_its_filename() -> None:
    labels = _labels(_resolve(brand_element_keys=(EXTRA,)))

    assert labels[EXTRA] == "bag.png"


def _ref(kind: str, label: str, role: BrandReferenceRole) -> BrandReference:
    return BrandReference(
        rol=role,
        asset_key=f"{PREFIX}/{label.lower()}/x.png",
        label=label,
        content_type="image/png",
        asset_kind=kind,
    )


def test_the_trace_names_a_corner_signature_laid_after_the_video() -> None:
    refs = BrandReferencesSet(
        overlay=_ref("logo_version", "Imagotipo", BrandReferenceRole.FIRMA_OVERLAY)
    )

    assert _clip_logo_trace(True, refs, False) == (
        "firma en una esquina, puesta después del video (Imagotipo)"
    )


def test_the_trace_names_a_logo_sent_inside_the_scene() -> None:
    refs = BrandReferencesSet(
        refs=(
            _ref("logo_version", "Isotipo", BrandReferenceRole.ELEMENTO_DE_MARCA),
            _ref("extra", "Bolsa", BrandReferenceRole.ELEMENTO_DE_MARCA),
        )
    )

    assert _clip_logo_trace(False, refs, True) == "dentro de la escena, como referencia: Isotipo"


def test_the_trace_says_no_logo_when_none_travels() -> None:
    assert _clip_logo_trace(False, BrandReferencesSet(), False) == "ninguno"
