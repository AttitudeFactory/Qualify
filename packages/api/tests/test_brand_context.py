"""`brand_context.build_context` — what the Brand Kit saved, as the generator's business
context (§ request 2026-10-01). Pure: no database."""

from __future__ import annotations

from dataclasses import dataclass

from qualify_api.creative.brand_context import MAX_ACCOUNTS, build_context
from qualify_api.creative.brand_kit_store import EXTRA, LOGO_VERSION, BrandAsset, BrandKitDetails


@dataclass
class Label:
    network: str
    handle: str
    label: str
    position: int | None = None


def test_the_saved_answers_assets_and_sort_become_the_context() -> None:
    details = BrandKitDetails(
        connect={
            "rubro_text": "cafetería de especialidad",
            "city": "Cúcuta",
            "country_code": "CO",
            "hashtags": [{"tag": "cafe", "origin": "manual"}, {"tag": "#cucuta"}],
        },
        profile={"bio": "Tostamos en casa", "category": "Cafetería"},
    )
    assets = [
        BrandAsset(LOGO_VERSION, "isotipo", "t/x/a.png", "a.png", context="Solo en fondos oscuros"),
        BrandAsset(EXTRA, "e1", "t/x/b.png", "mascota.png", label="Mascota"),
        BrandAsset(EXTRA, "e2", "t/x/c.png", "patron.png"),
    ]
    labels = [
        Label("instagram", "segundo", "referente", position=1),
        Label("instagram", "primero", "referente", position=0),
        Label("tiktok", "sin_orden", "referente"),
        Label("instagram", "vecino", "competencia"),
        Label("instagram", "malo", "detractor"),
    ]
    context = build_context(details, assets, labels)
    assert context is not None
    assert context.sector == "cafetería de especialidad"
    assert context.location == "Cúcuta, CO"
    assert context.hashtags == ("cafe", "cucuta")
    assert context.account_category == "Cafetería"
    assert [(e.name, e.context) for e in context.elements] == [
        ("Isotipo", "Solo en fondos oscuros"),
        ("Mascota", ""),
        ("patron.png", ""),
    ]
    # influence order; never-ordered last; detractors are not context
    assert context.referentes == (
        "@primero (instagram)",
        "@segundo (instagram)",
        "@sin_orden (tiktok)",
    )
    assert context.competitors == ("@vecino (instagram)",)


def test_nothing_saved_is_no_context_and_lists_are_capped() -> None:
    assert build_context(BrandKitDetails(), [], []) is None
    many = [Label("instagram", f"r{i}", "referente", position=i) for i in range(20)]
    context = build_context(BrandKitDetails(), [], many)
    assert context is not None and len(context.referentes) == MAX_ACCOUNTS
