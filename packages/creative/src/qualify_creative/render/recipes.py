"""The recipe router (plan-mvp-plantillas-remotion.md §3; backlog MP-09).

Six ordered rules over what the Post has — not what the operator asked for. It always
returns the engines it knows about, each with its ETA/cost, the suggested one marked and
the rule that chose it recorded, so that "how often does the user override rule 2" is a
query later. Pure: no I/O, no clock. The template registry is the only input besides
the Post's facts, which keeps the rules unit-testable one by one.

Rules (in order; the first that applies suggests):
 1. the script wants a person on camera and the tenant has an avatar → HeyGen
 2. ≥2 product photos, no video → Remotion, promo_producto
 3. ≥1 real video → Remotion, corte_video (when published)
 4. the angle is a menu / several products → Remotion, menu (when published)
 5. no assets, or a scene the operator does not have → UGC (quote only, no render yet)
 6. nothing applies → Remotion, promo_producto with the main photo
A tenant monthly cap, when the suggested option exceeds it, falls through to the next.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from qualify_creative.enums import ContentType
from qualify_creative.render.manifest import OutputKind, TemplateManifest
from qualify_creative.render.registry import TemplateRegistry

PRESENTER_ANGLES: frozenset[ContentType] = frozenset(
    {ContentType.TESTIMONIAL, ContentType.TEAM_STORY, ContentType.FAQ}
)
MENU_ANGLES: frozenset[ContentType] = frozenset({ContentType.MENU, ContentType.COMBO})

PROMO_TEMPLATE = "promo_producto"
VIDEO_TEMPLATE = "corte_video"
MENU_TEMPLATE = "menu_productos"

#: Rough quotes for the engines whose adapter is not the one being decided here. They
#: come from the vendor sheets of 2026-10 (backlog §3) and exist so the user sees that a
#: template costs cents and a synthetic scene costs dollars. Real estimates come from the
#: engines' own adapters when the option is chosen.
HEYGEN_QUOTE_USD = (Decimal("0.50"), Decimal("2.00"))
UGC_QUOTE_USD = (Decimal("1.50"), Decimal("3.50"))


class Engine(StrEnum):
    REMOTION = "remotion"
    HEYGEN = "heygen"
    UGC = "ugc"


@dataclass(frozen=True)
class PostFacts:
    angle: ContentType
    photo_count: int
    video_count: int = 0
    product_count: int = 1
    #: The script/brief asks for a person talking to camera.
    wants_presenter: bool = False
    #: The tenant configured an avatar/voice for HeyGen.
    has_avatar: bool = False
    #: Nothing in the catalog matches the scene the script describes.
    needs_missing_scene: bool = False
    niche: str | None = None
    #: USD left in the tenant's monthly cap; None = no cap.
    cap_remaining_usd: Decimal | None = None
    #: Expected video length for the ETA (seconds).
    video_duration_sec: float = 15.0


@dataclass(frozen=True)
class RecipeOption:
    engine: Engine
    label: str
    template_id: str | None
    template_version: int | None
    rule: int | None  # the rule that made this the suggestion; None if not suggested
    suggested: bool
    available: bool
    reason: str
    eta_sec: float | None
    cost_usd_min: Decimal
    cost_usd_max: Decimal
    outputs: tuple[str, ...] = ()

    @property
    def cost_label(self) -> str:
        if self.cost_usd_min == self.cost_usd_max:
            return f"USD {self.cost_usd_min:.2f}"
        return f"USD {self.cost_usd_min:.2f} a {self.cost_usd_max:.2f}"


def suggest_recipes(
    facts: PostFacts,
    registry: TemplateRegistry,
    *,
    remotion_cost_per_render_usd: Decimal = Decimal("0"),
) -> list[RecipeOption]:
    """Always three engines, in a fixed order (Remotion, HeyGen, UGC), exactly one
    `suggested=True` — unless nothing is renderable, in which case none is."""
    remotion = _remotion_option(facts, registry, remotion_cost_per_render_usd)
    heygen = RecipeOption(
        engine=Engine.HEYGEN,
        label="Avatar hablando a cámara",
        template_id="tpl_testimonio_avatar",
        template_version=None,
        rule=None,
        suggested=False,
        available=facts.has_avatar,
        reason="" if facts.has_avatar else "el negocio no tiene avatar configurado",
        eta_sec=None,
        cost_usd_min=HEYGEN_QUOTE_USD[0],
        cost_usd_max=HEYGEN_QUOTE_USD[1],
        outputs=("reel",),
    )
    ugc = RecipeOption(
        engine=Engine.UGC,
        label="Escena sintética + voz",
        template_id="tpl_ugc_escena",
        template_version=None,
        rule=None,
        suggested=False,
        available=False,
        reason="solo cotiza; el motor UGC no renderiza todavía",
        eta_sec=None,
        cost_usd_min=UGC_QUOTE_USD[0],
        cost_usd_max=UGC_QUOTE_USD[1],
        outputs=("reel",),
    )

    order = _decide(facts, remotion)
    options = {Engine.REMOTION: remotion, Engine.HEYGEN: heygen, Engine.UGC: ugc}
    for rule, engine in order:
        candidate = options[engine]
        if not candidate.available:
            continue
        if _exceeds_cap(candidate, facts.cap_remaining_usd):
            continue
        options[engine] = _mark(candidate, rule)
        break
    return [options[Engine.REMOTION], options[Engine.HEYGEN], options[Engine.UGC]]


def _decide(facts: PostFacts, remotion: RecipeOption) -> list[tuple[int, Engine]]:
    """The ordered (rule, engine) candidates for this Post. The first available one that
    fits the cap wins; the others stay as visible alternatives."""
    order: list[tuple[int, Engine]] = []
    if facts.wants_presenter or facts.angle in PRESENTER_ANGLES:
        order.append((1, Engine.HEYGEN))
    if facts.photo_count >= 2 and facts.video_count == 0:
        order.append((2, Engine.REMOTION))
    if facts.video_count >= 1:
        order.append((3, Engine.REMOTION))
    if facts.angle in MENU_ANGLES or facts.product_count >= 2:
        order.append((4, Engine.REMOTION))
    if (facts.photo_count == 0 and facts.video_count == 0) or facts.needs_missing_scene:
        order.append((5, Engine.UGC))
    order.append((6, Engine.REMOTION))
    return order


def _remotion_option(
    facts: PostFacts, registry: TemplateRegistry, per_render: Decimal
) -> RecipeOption:
    manifest = _pick_template(facts, registry)
    if manifest is None:
        return RecipeOption(
            engine=Engine.REMOTION,
            label="Plantilla de marca",
            template_id=None,
            template_version=None,
            rule=None,
            suggested=False,
            available=False,
            reason="ninguna plantilla publicada sirve a este ángulo con estos assets",
            eta_sec=None,
            cost_usd_min=Decimal(0),
            cost_usd_max=Decimal(0),
        )
    min_photos, _ = manifest.required_photos()
    available = facts.photo_count >= min_photos and (not manifest.needs_video or facts.video_count)
    reason = ""
    if not available:
        reason = (
            f"la plantilla «{manifest.name}» necesita {min_photos} fotos"
            if facts.photo_count < min_photos
            else f"la plantilla «{manifest.name}» necesita un video"
        )
    cost = per_render * manifest.render_count
    return RecipeOption(
        engine=Engine.REMOTION,
        label=manifest.name,
        template_id=manifest.id,
        template_version=manifest.version,
        rule=None,
        suggested=False,
        available=bool(available),
        reason=reason,
        eta_sec=manifest.cost_model.eta_seconds(manifest.outputs, facts.video_duration_sec),
        cost_usd_min=cost,
        cost_usd_max=cost,
        outputs=tuple(manifest.outputs),
    )


def _pick_template(facts: PostFacts, registry: TemplateRegistry) -> TemplateManifest | None:
    """Which template Remotion would use for this Post: the video template when there is
    a video, the menu template for a menu angle, otherwise the promo. Falls back to the
    promo (rule 6) whenever the preferred one is not published yet."""
    preferred: list[str] = []
    if facts.video_count >= 1:
        preferred.append(VIDEO_TEMPLATE)
    if facts.angle in MENU_ANGLES or facts.product_count >= 2:
        preferred.append(MENU_TEMPLATE)
    preferred.append(PROMO_TEMPLATE)
    candidates = registry.for_post(angle=facts.angle.value, niche=facts.niche)
    by_id = {m.id: m for m in candidates}
    for tid in preferred:
        if tid in by_id:
            return by_id[tid]
    if candidates:
        with_video = [m for m in candidates if m.has_video_output]
        return (with_video or candidates)[0]
    # Rule 6 is "nothing applies → the promo with the main photo": the promo is the
    # universal fallback even for an angle it does not list, as long as it is published
    # for this niche. Better a plain promo than no piece at all.
    try:
        promo = registry.get(PROMO_TEMPLATE)
    except KeyError:
        return None
    return promo if promo.fits_niche(facts.niche) else None


def _exceeds_cap(option: RecipeOption, cap: Decimal | None) -> bool:
    return cap is not None and option.cost_usd_min > cap


def _mark(option: RecipeOption, rule: int) -> RecipeOption:
    return RecipeOption(**{**option.__dict__, "rule": rule, "suggested": True})


def video_outputs(manifest: TemplateManifest) -> tuple[str, ...]:
    return tuple(p for p, o in manifest.outputs.items() if o.kind is OutputKind.VIDEO)
