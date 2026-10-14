"""`brand_context.build_context` — what the Brand Kit saved, as the generator's business
context (§ request 2026-10-01). Pure: no database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qualify_api.creative.brand_context import MAX_ACCOUNTS, build_context
from qualify_api.creative.brand_kit_store import EXTRA, LOGO_VERSION, BrandAsset, BrandKitDetails


@dataclass
class Label:
    network: str
    handle: str
    label: str
    position: int | None = None


@dataclass
class Found:
    """`StoredDiscoveredAccount`'s two fields the context reads."""

    card: dict[str, Any] = field(default_factory=dict)
    bio: str = ""


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
    found = {
        ("instagram", "primero"): Found(
            card={
                "kind": "creador",
                "review": "Reseña cafés de especialidad en Cúcuta",
                "note": "me encanta su humor",
                "blurb": "Probé el\nmejor flat white\nde la ciudad",
            }
        ),
        ("instagram", "vecino"): Found(card={"kind": "marca", "review": "Misma oferta"}),
        ("instagram", "malo"): Found(card={"review": "Tono agresivo"}, bio="Solo ofertas"),
    }
    context = build_context(details, assets, labels, found)
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
    # influence order; never-ordered last
    assert [(a.handle, a.network) for a in context.referentes] == [
        ("@primero", "instagram"),
        ("@segundo", "instagram"),
        ("@sin_orden", "tiktok"),
    ]
    first = context.referentes[0]
    # § 2026-10-06: what the discovery learned travels with the handle, one line each
    assert (first.kind, first.why, first.note) == (
        "creador",
        "Reseña cafés de especialidad en Cúcuta",
        "me encanta su humor",
    )
    assert first.sample == "Probé el mejor flat white de la ciudad"
    assert context.referentes[1].why == ""  # found by hand, never by the discovery
    assert [(a.handle, a.kind, a.why) for a in context.competitors] == [
        ("@vecino", "marca", "Misma oferta")
    ]
    # detractors are context too now: what the brand must not resemble
    (bad,) = context.detractors
    assert (bad.handle, bad.why, bad.sample) == ("@malo", "Tono agresivo", "Solo ofertas")


def test_an_accounts_texts_are_capped() -> None:
    from qualify_api.creative.brand_context import MAX_ACCOUNT_TEXT

    found = {("tiktok", "largo"): Found(card={"review": "x" * 500})}
    context = build_context(BrandKitDetails(), [], [Label("tiktok", "largo", "referente")], found)
    assert context is not None
    assert len(context.referentes[0].why) == MAX_ACCOUNT_TEXT
    assert context.referentes[0].why.endswith("…")


def test_nothing_saved_is_no_context_and_lists_are_capped() -> None:
    assert build_context(BrandKitDetails(), [], []) is None
    many = [Label("instagram", f"r{i}", "referente", position=i) for i in range(20)]
    context = build_context(BrandKitDetails(), [], many)
    assert context is not None and len(context.referentes) == MAX_ACCOUNTS


def test_a_font_is_no_element_and_each_element_knows_its_key() -> None:
    """A font file used to fall through to «Logo» in the prompt (§ 2026-10-06)."""
    from qualify_api.creative.brand_kit_store import FONT, LOGO

    assets = [
        BrandAsset(LOGO, "", "t/x/logo.png", "logo.png"),
        BrandAsset(FONT, "heading", "t/x/f.woff2", "f.woff2"),
        BrandAsset(EXTRA, "e1", "t/x/bolsa.png", "bolsa.png", label="Bolsa"),
    ]
    context = build_context(BrandKitDetails(), assets, [])
    assert context is not None
    assert [(e.name, e.key, e.kind) for e in context.elements] == [
        ("Logo", "t/x/logo.png", "logo"),
        ("Bolsa", "t/x/bolsa.png", "element"),
    ]
