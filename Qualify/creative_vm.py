"""View-models for the Brand Content Engine screens (design §6) — frozen dataclasses.

Same custody rules as `connections_vm.py`: every Reflex var serializes to the client, so
the states only ever hold these whitelisted dataclasses — never an ORM row, never a
service record, and never anything credential-bearing (there is no field here that could
carry an API key, so there is no route from the platform key to the browser).

This module is pure on purpose: stdlib + `qualify_creative` (schemas/enums, itself pure)
only — no Reflex, no `qualify_api`, no database — so `test_creative_vm.py` runs with a
plain interpreter. Builders here do *display* work (labels, ordering, formatting), not
business logic: readiness verdicts, FSM edges and hard rules are computed server-side by
the backend and arrive as facts.

User-facing strings are Spanish (the operator is Spanish-speaking); code stays English.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from qualify_creative.enums import ContentType, DraftStatus, ImageRoute
from qualify_creative.schemas import CopyPayload, ImagePolicy

# ---------------------------------------------------------------------------
# Draft status display

#: DraftStatus value -> operator-facing label. Every enum member has an entry — the
#: fallback below exists for forward compatibility, not for laziness.
STATUS_LABELS: dict[str, str] = {
    DraftStatus.DRAFTING.value: "Generando",
    DraftStatus.GENERATED.value: "Listo para revisar",
    DraftStatus.APPROVED.value: "Aprobado",
    DraftStatus.REJECTED.value: "Rechazado",
    DraftStatus.STAGED.value: "Preparado en Meta",
    DraftStatus.PUBLISHED.value: "Publicado",
    DraftStatus.FAILED.value: "Fallido",
}

#: DraftStatus value -> Radix color scheme for the badge. Never color alone in the UI —
#: the label above always ships with it.
STATUS_TONES: dict[str, str] = {
    DraftStatus.DRAFTING.value: "blue",
    DraftStatus.GENERATED.value: "amber",
    DraftStatus.APPROVED.value: "grass",
    DraftStatus.REJECTED.value: "gray",
    DraftStatus.STAGED.value: "iris",
    DraftStatus.PUBLISHED.value: "grass",
    DraftStatus.FAILED.value: "tomato",
}

_UNKNOWN_TONE = "gray"


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def status_tone(status: str) -> str:
    return STATUS_TONES.get(status, _UNKNOWN_TONE)


# ---------------------------------------------------------------------------
# Failure reasons (design §6.5: translated + a CONCRETE action, never a bare code)


@dataclass(frozen=True)
class FailureVM:
    """A typed failure translated for the operator, with the concrete next step."""

    reason: str  # FailureReason value, stable key
    label: str  # what happened, in Spanish
    action_label: str  # what to DO about it
    action_route: str  # screen that fixes it ("" when the fix is not a screen)


#: FailureReason value -> (label, action, route). A FAILED draft is terminal in the FSM,
#: so "retry" always means a new brief — hence /create, not a regenerate edge.
FAILURE_INFO: dict[str, tuple[str, str, str]] = {
    "budget_exceeded": (
        "Se alcanzó el tope de gasto mensual de la marca.",
        "Sube el tope mensual y vuelve a intentarlo",
        "",
    ),
    "credential_invalid": (
        "La clave del proveedor de IA no es válida o expiró.",
        "Renueva la clave de la plataforma",
        "",
    ),
    "provider_error": (
        "El proveedor de IA falló al generar.",
        "Crea un nuevo encargo para reintentar",
        "/create",
    ),
    "fidelity_rejected": (
        "Ninguna variante pasó las reglas duras de la marca.",
        "Ajusta el kit o el encargo y reintenta",
        "/brand",
    ),
    "route_blocked_by_policy": (
        "La ruta de imagen elegida está bloqueada para esta marca.",
        "Elige otra ruta de imagen en un nuevo encargo",
        "/create",
    ),
    "refusal": (
        "El modelo rechazó el encargo por política de contenido.",
        "Reformula el tema y crea un nuevo encargo",
        "/create",
    ),
    "media_expired": (
        "La imagen caducó antes de publicarse.",
        "Crea un nuevo encargo para regenerar la imagen",
        "/create",
    ),
    "timeout": (
        "La generación tardó demasiado y se marcó como fallida.",
        "Crea un nuevo encargo para reintentarlo",
        "/create",
    ),
}


def failure_vm(reason: str | None) -> FailureVM | None:
    """Translate a typed failure reason; None in, None out. An unknown reason (a newer
    backend) degrades to showing the raw code with the generic retry action rather than
    hiding that the draft failed."""
    if not reason:
        return None
    label, action, route = FAILURE_INFO.get(
        reason, (f"Falló la generación ({reason}).", "Crea un nuevo encargo", "/create")
    )
    return FailureVM(reason=reason, label=label, action_label=action, action_route=route)


# ---------------------------------------------------------------------------
# Readiness (design §6.1: never a disabled button without a link to the fix)


@dataclass(frozen=True)
class GapVM:
    """One missing piece of the brand substrate, linked to the screen that fixes it."""

    key: str
    label: str
    fix_route: str
    fix_label: str


#: Readiness gap name -> Spanish label. Kit gaps route to /brand; the voice gap to
#: /brand/voice. Order of appearance is the backend's (highest impact first).
GAP_LABELS: dict[str, tuple[str, str]] = {
    "positioning": ("Posicionamiento de la marca", "/brand"),
    "audience": ("Audiencia objetivo", "/brand"),
    "tone_axes": ("Ejes de tono", "/brand"),
    "do_examples": ("Ejemplos de copy que SÍ suenan a la marca", "/brand"),
    "dont_examples": ("Ejemplos de copy que NO suenan a la marca", "/brand"),
    "cta_patterns": ("Patrones de llamado a la acción", "/brand"),
    "palette_rgb": ("Paleta de colores", "/brand"),
    "logo_asset_key": ("Logo de la marca", "/brand"),
    "active_voice_profile": ("Perfil de voz aprobado", "/brand"),
}

_FIX_LABELS: dict[str, str] = {
    "/brand": "Completar en el Brand Kit",
}


def gap_vm(key: str) -> GapVM:
    label, route = GAP_LABELS.get(key, (key, "/brand"))
    return GapVM(key=key, label=label, fix_route=route, fix_label=_FIX_LABELS[route])


@dataclass(frozen=True)
class ReadinessVM:
    """Display projection of the server-computed `BrandReadiness`. The verdicts
    (`can_distill`/`can_generate`) arrive computed — the UI never re-derives them."""

    has_kit: bool
    completeness_pct: int  # 0..100, for the meter
    has_active_voice: bool
    can_distill: bool
    can_generate: bool
    gaps: tuple[GapVM, ...] = ()


def build_readiness_vm(
    *,
    has_kit: bool,
    kit_completeness: float,
    has_active_voice: bool,
    can_distill: bool,
    can_generate: bool,
    missing: Sequence[str],
) -> ReadinessVM:
    return ReadinessVM(
        has_kit=has_kit,
        completeness_pct=int(round(kit_completeness * 100)),
        has_active_voice=has_active_voice,
        can_distill=can_distill,
        can_generate=can_generate,
        gaps=tuple(gap_vm(key) for key in missing),
    )


# ---------------------------------------------------------------------------
# Voice profile (HITL #0, design §6.3: every field next to its evidence)

#: ToneAxes field -> (left label, right label). Sliders show words, numbers underneath.
TONE_AXIS_LABELS: dict[str, tuple[str, str]] = {
    "formal_casual": ("formal", "coloquial"),
    "sober_enthusiastic": ("sobrio", "entusiasta"),
    "technical_plain": ("técnico", "llano"),
    "brief_elaborate": ("breve", "elaborado"),
}

_SOURCE_KIND_LABELS: dict[str, str] = {
    "manual_kit": "brand kit",
    "owned_media": "posts propios",
    "public_web": "sitio web",
}


@dataclass(frozen=True)
class ToneRowVM:
    axis: str
    label: str  # "formal ↔ coloquial"
    value: int  # distilled
    kit_value: int  # what the kit declares (same as value in S1)
    differs: bool


@dataclass(frozen=True)
class SourceVM:
    kind_label: str
    ref: str
    excerpt: str


@dataclass(frozen=True)
class VoiceProposalVM:
    version: int
    status: str  # VoiceProfileStatus value
    status_label: str
    tone_rows: tuple[ToneRowVM, ...]
    lexicon: tuple[str, ...]
    avoid_lexicon: tuple[str, ...]
    signature_moves: tuple[str, ...]
    sources: tuple[SourceVM, ...]
    can_approve: bool  # only a PROPOSED profile can be approved


_VOICE_STATUS_LABELS = {
    "proposed": "Propuesto",
    "active": "Activo",
    "superseded": "Reemplazado",
}


def build_voice_proposal_vm(
    *,
    version: int,
    status: str,
    tone_axes: Mapping[str, int],
    kit_tone_axes: Mapping[str, int] | None,
    lexicon: Sequence[str],
    avoid_lexicon: Sequence[str],
    signature_moves: Sequence[str],
    sources: Sequence[Mapping[str, str]],
) -> VoiceProposalVM:
    """Project one voice profile row for the HITL #0 screen. `kit_tone_axes` is the
    comparison column ("del kit"); when absent the distilled value doubles for it and
    nothing is flagged as differing."""
    rows: list[ToneRowVM] = []
    for axis, (left, right) in TONE_AXIS_LABELS.items():
        value = int(tone_axes.get(axis, 0))
        kit_value = int(kit_tone_axes.get(axis, value)) if kit_tone_axes else value
        rows.append(
            ToneRowVM(
                axis=axis,
                label=f"{left} ↔ {right}",
                value=value,
                kit_value=kit_value,
                differs=value != kit_value,
            )
        )
    return VoiceProposalVM(
        version=version,
        status=status,
        status_label=_VOICE_STATUS_LABELS.get(status, status),
        tone_rows=tuple(rows),
        lexicon=tuple(lexicon),
        avoid_lexicon=tuple(avoid_lexicon),
        signature_moves=tuple(signature_moves),
        sources=tuple(
            SourceVM(
                kind_label=_SOURCE_KIND_LABELS.get(str(s.get("kind", "")), str(s.get("kind", ""))),
                ref=str(s.get("ref", "")),
                excerpt=str(s.get("excerpt", "")),
            )
            for s in sources
        ),
        can_approve=status == "proposed",
    )


# ---------------------------------------------------------------------------
# Brand kit form (display shape for the /brand editor — parsing back happens in the
# provider, next to the service that persists it)


@dataclass(frozen=True)
class KitFormVM:
    """The stored kit flattened into editable form values (multiline fields join with
    newlines, the palette with commas)."""

    positioning: str = ""
    audience: str = ""
    regional_variant: str = "es-CO"
    tone_formal_casual: int = 50
    tone_sober_enthusiastic: int = 50
    tone_technical_plain: int = 50
    tone_brief_elaborate: int = 50
    do_examples: str = ""
    dont_examples: str = ""
    banned_words: str = ""
    forbidden_claims: str = ""
    cta_patterns: str = ""
    palette_rgb: str = ""
    has_logo: bool = False
    has_template: bool = False


# ---------------------------------------------------------------------------
# The image accordion (design §6.4 / D11: the ORDER is the recommendation)


@dataclass(frozen=True)
class RouteOptionVM:
    """One submodule of the image accordion. Blocked routes stay VISIBLE and disabled
    with their reason — hiding them invites the question, a reason answers it."""

    key: str  # ImageRoute value
    rank: int  # ImageRoute.rank — the accordion order
    title: str
    description: str
    cost_label: str
    badge: str  # "RECOMENDADO" | "requiere etiqueta" | "NO RECOMENDADA" | ""
    badge_tone: str
    enabled: bool
    disabled_reason: str  # "" when enabled
    warning: str  # the ⚠ §6.4 text; only GENERATE carries it
    requires_disclosure: bool
    needs_upload: bool  # route operates on a photo the operator supplies


#: The §6.4 warning, verbatim in spirit: shown BEFORE choosing, not after generating.
GENERATE_WARNING = (
    "⚠ La imagen no será tu producto. En comida y bebida esto destruye confianza "
    "y Meta obliga a etiquetarlo. Úsalo solo para piezas SIN producto "
    "(horarios, promos, fondos)."
)

_ROUTE_COPY: dict[ImageRoute, tuple[str, str, str]] = {
    # route -> (title, description, cost label)
    ImageRoute.TEMPLATE_ONLY: (
        "Solo tu plantilla",
        "Tarjeta de marca sin fotografía: horarios, menú, promos de texto. Sin IA.",
        "Gratis",
    ),
    ImageRoute.FROM_UPLOAD: (
        "Tu foto, con tu marca",
        "Sube la foto y la ponemos en tu marco. Sin retoque de IA.",
        "Gratis",
    ),
    ImageRoute.RESTYLE_ENHANCE: (
        "Tu foto, mejorada",
        "Corregimos luz y color sobre TU foto real. No requiere etiqueta de IA en anuncios.",
        "~$0.03",
    ),
    ImageRoute.RESTYLE_SCENE: (
        "Tu producto, en otro fondo",
        "Lleva tu producto real a un contexto nuevo. Meta obliga a marcarlo como IA en anuncios.",
        "~$0.03",
    ),
    ImageRoute.GENERATE: (
        "Generar desde cero",
        "La imagen se inventa por completo a partir del encargo.",
        "~$0.03–0.09",
    ),
}

_NOT_DEFENSIBLE_FOR_TYPE = (
    "Esta pieza muestra algo que el cliente va a recibir: inventar su imagen no es defendible."
)


def build_route_options(
    *, policy: ImagePolicy, content_type: ContentType
) -> tuple[RouteOptionVM, ...]:
    """The accordion, in `ImageRoute.rank` order — GENERATE is last by construction.

    A route is disabled when the brand's `ImagePolicy` blocks it (reason from
    `ImagePolicy.reason_for`) or, for GENERATE, when the content type depicts a
    sellable item (`ContentType.allows_generate`). The recommended badge follows
    `ContentType.default_image_route`; the disclosure badges are compliance facts from
    the enum, shown BEFORE choosing.
    """
    default_route = content_type.default_image_route
    options: list[RouteOptionVM] = []
    for route in sorted(ImageRoute, key=lambda r: r.rank):
        title, description, cost = _ROUTE_COPY[route]
        enabled = policy.allows(route)
        disabled_reason = "" if enabled else policy.reason_for(route)
        if route is ImageRoute.GENERATE and enabled and not content_type.allows_generate:
            enabled = False
            disabled_reason = _NOT_DEFENSIBLE_FOR_TYPE
        if route is ImageRoute.GENERATE:
            badge, badge_tone = "NO RECOMENDADA", "tomato"
        elif route is default_route:
            badge, badge_tone = "RECOMENDADO", "grass"
        elif route.requires_ai_disclosure:
            badge, badge_tone = "requiere etiqueta", "amber"
        else:
            badge, badge_tone = "", "gray"
        options.append(
            RouteOptionVM(
                key=route.value,
                rank=route.rank,
                title=title,
                description=description,
                cost_label=cost,
                badge=badge,
                badge_tone=badge_tone,
                enabled=enabled,
                disabled_reason=disabled_reason,
                warning=GENERATE_WARNING if route is ImageRoute.GENERATE else "",
                requires_disclosure=route.requires_ai_disclosure,
                needs_upload=route.needs_source_media,
            )
        )
    return tuple(options)


# ---------------------------------------------------------------------------
# Cost line (design §6.5: the cost is shown ALWAYS — hiding it produces the
# regeneration loop)


def format_cost_label(
    total_usd: Decimal | None, voice_version: int | None, model_ids: Sequence[str]
) -> str:
    """ "$0.04 · Perfil v1 · claude-opus-5" — or "Gratis" when nothing was spent.

    Cents when representable; four decimals when the spend is real but under a cent
    (rounding $0.004 to $0.00 would claim it was free).
    """
    if total_usd is None or total_usd == 0:
        cost = "Gratis"
    else:
        cents = total_usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cost = f"${cents}" if cents != 0 else f"${total_usd.quantize(Decimal('0.0001'))}"
    parts = [cost]
    if voice_version is not None:
        parts.append(f"Perfil v{voice_version}")
    if model_ids:
        parts.append(" + ".join(dict.fromkeys(model_ids)))
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Variants and drafts (HITL #2)


@dataclass(frozen=True)
class CopyVariantVM:
    """One copy variant, edited copy already merged over the model's when present."""

    variant_id: str
    ordinal: int
    label: str  # "Variante 1"
    hook: str
    caption: str
    hashtags_text: str  # "#a #b" — display form
    cta: str
    ads_primary_text: str
    ads_headline: str
    ads_description: str
    has_ads: bool
    passed: bool  # layer-1 verdict of the SHOWN copy
    failure_labels: tuple[str, ...]  # hard failures, "regla: detalle"
    was_edited: bool
    rendered_caption: str  # the paste-ready organic string
    #: The libreto (video kinds): the spoken text, and a real creator's shot list as
    #: display lines ("1 · 5 s — visual: line").
    script: str = ""
    shots: tuple[str, ...] = ()


def _shot_lines(payload: CopyPayload) -> tuple[str, ...]:
    return tuple(
        f"{n} · {shot.seconds} s — {shot.visual}" + (f": «{shot.line}»" if shot.line else "")
        for n, shot in enumerate(payload.shots, 1)
    )


def build_variant_vm(
    *,
    variant_id: str,
    ordinal: int,
    copy: Mapping[str, object],
    edited_copy: Mapping[str, object] | None,
    fidelity: Mapping[str, object] | None,
) -> CopyVariantVM:
    """Project one variant. The shown copy is `edited_copy` when the human touched it
    (the service only stores edits that PASSED layer 1, so an edited variant shows as
    passing); otherwise the model's copy with its stored fidelity verdict."""
    shown = edited_copy if edited_copy is not None else copy
    payload = CopyPayload.model_validate(shown)
    if edited_copy is not None:
        passed = True
        failures: tuple[str, ...] = ()
    else:
        verdict = fidelity or {}
        passed = bool(verdict.get("passed", True))
        failures = tuple(
            f"{f.get('rule', '')}: {f.get('detail', '')}"
            for f in verdict.get("hard_failures", ())
            if isinstance(f, Mapping)
        )
    return CopyVariantVM(
        variant_id=variant_id,
        ordinal=ordinal,
        label=f"Variante {ordinal + 1}",
        hook=payload.hook,
        caption=payload.caption,
        hashtags_text=" ".join(f"#{tag.lstrip('#')}" for tag in payload.hashtags),
        cta=payload.cta,
        ads_primary_text=payload.ads_primary_text or "",
        ads_headline=payload.ads_headline or "",
        ads_description=payload.ads_description or "",
        has_ads=payload.ads_headline is not None or payload.ads_primary_text is not None,
        passed=passed,
        failure_labels=failures,
        was_edited=edited_copy is not None,
        rendered_caption=payload.rendered_caption(),
        script=payload.script,
        shots=_shot_lines(payload),
    )


@dataclass(frozen=True)
class DraftSummaryVM:
    draft_id: str
    topic: str
    status: str
    status_label: str
    status_tone: str
    created_label: str  # PRE-FORMATTED server-side, never a raw datetime var
    failure_label: str  # "" unless FAILED


def build_draft_summary_vm(
    *,
    draft_id: str,
    topic: str,
    status: str,
    created_label: str,
    failure_reason: str | None,
) -> DraftSummaryVM:
    failure = failure_vm(failure_reason)
    return DraftSummaryVM(
        draft_id=draft_id,
        topic=topic,
        status=status,
        status_label=status_label(status),
        status_tone=status_tone(status),
        created_label=created_label,
        failure_label=failure.label if failure is not None else "",
    )


@dataclass(frozen=True)
class MediaVM:
    """One generated media item: `key` is the upload-store key the page resolves with
    `rx.get_upload_url`."""

    key: str
    media_type: str  # "image" | "video"
    position: int
    label: str  # "Imagen", "Slide 2 de 4", "Video"
    poster_key: str = ""


def build_media_vms(
    items: Sequence[tuple[str, str, int, Mapping[str, object] | None]],
) -> tuple[MediaVM, ...]:
    """(key, media_type, position, params) rows → display items, in order."""
    ordered = sorted(items, key=lambda item: item[2])
    images = [item for item in ordered if item[1] == "image"]
    out: list[MediaVM] = []
    for key, media_type, position, params in ordered:
        if media_type == "video":
            poster = str((params or {}).get("thumbnail_key") or "")
            out.append(MediaVM(key, media_type, position, "Video", poster))
        elif len(images) > 1:
            out.append(MediaVM(key, media_type, position, f"Slide {position + 1} de {len(images)}"))
        else:
            out.append(MediaVM(key, media_type, position, "Imagen"))
    return tuple(out)


#: The generator's content kinds as /create offers them (`ContentKind`), in order.
#: (key, title, blurb, icon)
KIND_OPTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "creator_script",
        "Guion para creador real",
        "Una persona de tu marca lo graba: generamos el guion y el texto del post.",
        "clapperboard",
    ),
    (
        "avatar_video",
        "Video con avatar humano",
        "Un presentador generado lee el guion. Fondo y producto opcionales.",
        "user-round",
    ),
    (
        "animated_avatar_video",
        "Video con avatar animado",
        "Un personaje animado, creado por IA o desde tu imagen. Fondo y producto opcionales.",
        "smile",
    ),
    (
        "static_flyer",
        "Imagen tipo flyer",
        "Una imagen o un carrusel con tu fondo y tus productos.",
        "image",
    ),
    (
        "template",
        "Con plantilla",
        "Tu plantilla de marca rellenada. Próximamente.",
        "layout-template",
    ),
)
KIND_LABELS: dict[str, str] = {key: title for key, title, _, _ in KIND_OPTIONS}


@dataclass(frozen=True)
class DraftVM:
    """The §6.6 contract, plus the display facts the detail screen renders."""

    draft_id: str
    status: str
    status_label: str
    status_tone: str
    variants: tuple[CopyVariantVM, ...] = ()
    image_url: str | None = None
    fidelity_summary: str = ""
    cost_label: str = ""
    can_approve: bool = False
    blocking_reason: str | None = None
    failure: FailureVM | None = None
    requires_ai_disclosure: bool = False
    created_label: str = ""
    is_drafting: bool = False
    is_failed: bool = False
    kind: str = "static_flyer"
    kind_label: str = ""
    media: tuple[MediaVM, ...] = ()
    has_video: bool = False
    has_script: bool = False


def build_draft_vm(
    *,
    draft_id: str,
    status: str,
    failure_reason: str | None,
    variants: Sequence[CopyVariantVM],
    image_url: str | None,
    total_cost_usd: Decimal | None,
    voice_profile_version: int | None,
    model_ids: Sequence[str],
    requires_ai_disclosure: bool,
    created_label: str,
    kind: str = "static_flyer",
    media: Sequence[MediaVM] = (),
) -> DraftVM:
    """Assemble the detail view-model. `can_approve` is the FSM fact (only a GENERATED
    draft has the approve edge); which VARIANT may be approved is per-variant `passed` —
    the state combines both with the operator's selection."""
    passing = sum(1 for v in variants if v.passed)
    if not variants:
        fidelity_summary = ""
    elif passing == len(variants):
        fidelity_summary = "✅ Todas las variantes pasan las reglas duras"
    else:
        fidelity_summary = f"{passing} de {len(variants)} variantes pasan las reglas duras"
    can_approve = status == DraftStatus.GENERATED.value
    blocking_reason: str | None = None
    if can_approve and variants and passing == 0:
        can_approve = False
        blocking_reason = "Ninguna variante pasa las reglas duras de la marca."
    return DraftVM(
        draft_id=draft_id,
        status=status,
        status_label=status_label(status),
        status_tone=status_tone(status),
        variants=tuple(variants),
        image_url=image_url,
        fidelity_summary=fidelity_summary,
        cost_label=format_cost_label(total_cost_usd, voice_profile_version, model_ids),
        can_approve=can_approve,
        blocking_reason=blocking_reason,
        failure=failure_vm(failure_reason),
        requires_ai_disclosure=requires_ai_disclosure,
        created_label=created_label,
        is_drafting=status == DraftStatus.DRAFTING.value,
        is_failed=status == DraftStatus.FAILED.value,
        kind=kind,
        kind_label=KIND_LABELS.get(kind, ""),
        media=tuple(media),
        has_video=any(item.media_type == "video" for item in media),
        has_script=kind in ("creator_script", "avatar_video", "animated_avatar_video"),
    )


# ---------------------------------------------------------------------------
# The brief form vocabulary (4 objective buttons, content-type select)

OBJECTIVE_LABELS: dict[str, str] = {
    "awareness": "Reconocimiento",
    "consideration": "Consideración",
    "lead": "Captar contacto",
    "sale": "Vender",
}

INTENT_LABELS: dict[str, str] = {
    "organic": "Orgánico",
    "ads": "Anuncio",
    "both": "Ambos",
}

CONTENT_TYPE_LABELS: dict[str, str] = {
    "product": "Producto",
    "new_product": "Producto nuevo",
    "menu": "Menú",
    "price": "Precio",
    "promotion": "Promoción",
    "combo": "Combo",
    "hours_location": "Horarios y ubicación",
    "behind_scenes": "Detrás de cámaras",
    "team_story": "Historia del equipo",
    "testimonial": "Testimonio",
    "faq": "Preguntas frecuentes",
    "loyalty": "Fidelización",
    "opening_countdown": "Cuenta regresiva de apertura",
    "seasonal": "Temporada",
    "sold_out": "Agotado",
    "poll": "Encuesta",
    "catering": "Catering",
    "subscription": "Suscripción",
}


@dataclass(frozen=True)
class SelectOptionVM:
    value: str
    label: str


def content_type_options() -> tuple[SelectOptionVM, ...]:
    """Every ContentType, labeled; declaration order (the enum groups them by intent)."""
    return tuple(
        SelectOptionVM(value=ct.value, label=CONTENT_TYPE_LABELS.get(ct.value, ct.value))
        for ct in ContentType
    )


@dataclass(frozen=True)
class BriefFormVM:
    """What the /create screen submits — plain strings, parsed by the provider next to
    the service that consumes them."""

    objective: str = "consideration"
    content_type: str = "product"
    topic: str = ""
    product_ref: str = ""
    intent: str = "organic"
    image_route: str = ""
    source_media_key: str = ""
    must_mention: str = ""
    must_avoid: str = ""
    variants_requested: int = 3


__all__ = [
    "CONTENT_TYPE_LABELS",
    "FAILURE_INFO",
    "GAP_LABELS",
    "GENERATE_WARNING",
    "INTENT_LABELS",
    "OBJECTIVE_LABELS",
    "STATUS_LABELS",
    "STATUS_TONES",
    "TONE_AXIS_LABELS",
    "BriefFormVM",
    "CopyVariantVM",
    "DraftSummaryVM",
    "DraftVM",
    "FailureVM",
    "GapVM",
    "KitFormVM",
    "ReadinessVM",
    "RouteOptionVM",
    "SelectOptionVM",
    "SourceVM",
    "ToneRowVM",
    "VoiceProposalVM",
    "build_draft_summary_vm",
    "build_draft_vm",
    "build_readiness_vm",
    "build_route_options",
    "build_variant_vm",
    "build_voice_proposal_vm",
    "content_type_options",
    "failure_vm",
    "format_cost_label",
    "gap_vm",
    "status_label",
    "status_tone",
]
