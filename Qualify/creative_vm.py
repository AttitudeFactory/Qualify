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

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

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
    # CREAR-5 (decision 8): the owner never reads money — the team's dollar cap is a
    # safety net, and a generation it stops gives its creations back
    "budget_exceeded": (
        "No pudimos crear esta publicación: tu marca llegó a su límite de este mes. "
        "Te devolvimos tus creaciones.",
        "Escríbenos y lo revisamos contigo",
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
        "Ningún texto generado cumplió las reglas de tu marca (palabras prohibidas, "
        "promesas que no se pueden hacer, largo, emojis o hashtags), así que la "
        "publicación no se guardó. Reintenta: cada intento escribe textos nuevos.",
        "Reintenta, o revisa las reglas en Tu marca",
        "/brand/kit",
    ),
    "route_blocked_by_policy": (
        "La ruta de imagen elegida está bloqueada para esta marca.",
        "Elige otra ruta de imagen en un nuevo encargo",
        "/create",
    ),
    "refusal": (
        "La IA rechazó el encargo por política de contenido.",
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
    # Template render (plan-mvp-plantillas-remotion.md; packages/render/CONTRACT.md §4.2)
    "render_error": (
        "No pudimos armar la publicación con la plantilla.",
        "Crea un nuevo encargo para intentarlo otra vez",
        "/create",
    ),
    "invalid_parameters": (
        "El texto o las fotos no caben en la plantilla (gancho muy largo, fotos de menos).",
        "Ajusta el encargo: acorta el texto o agrega fotos del producto",
        "/create",
    ),
    "dependency_failed": (
        "No pudimos leer una foto, un video o una tipografía de tu marca.",
        "Revisa los archivos del producto y de tu marca y reintenta",
        "/brand/kit",
    ),
    "cancelled": (
        "La publicación se canceló antes de terminar.",
        "Crea un nuevo encargo para intentarlo otra vez",
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


#: Readiness gap name -> Spanish label. Every gap is fixed in the kit inside the
#: session (/brand/kit, m-24842979). Order of appearance is the backend's (highest
#: impact first).
GAP_LABELS: dict[str, tuple[str, str]] = {
    "positioning": ("¿Qué te hace distinto?", "/brand/kit"),
    "audience": ("¿Quién te compra?", "/brand/kit"),
    "tone_axes": ("Cómo suena tu marca", "/brand/kit"),
    "do_examples": ("Ejemplos de cómo sí hablas", "/brand/kit"),
    "dont_examples": ("Ejemplos de cómo no hablas", "/brand/kit"),
    "cta_patterns": ("Cómo invitas a comprar", "/brand/kit"),
    "palette_rgb": ("Colores", "/brand/kit"),
    "logo_asset_key": ("Logo", "/brand/kit"),
    "active_voice_profile": ("Tu voz", "/brand/kit"),
}

_FIX_LABELS: dict[str, str] = {
    "/brand/kit": "Completar mi marca",
}


def gap_vm(key: str) -> GapVM:
    label, route = GAP_LABELS.get(key, (key, "/brand/kit"))
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
    "manual_kit": "tu marca",
    "owned_media": "tus publicaciones",
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
    #: The brand's type faces by family name (§ 2026-10-05): headlines and body copy.
    font_heading: str = ""
    font_body: str = ""
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
    "y Meta obliga a etiquetarlo. Úsalo solo para publicaciones SIN producto "
    "(horarios, promos, fondos)."
)

_ONE_CREATION = "Usa 1 creación"

_ROUTE_COPY: dict[ImageRoute, tuple[str, str, str]] = {
    # route -> (title, description, what it uses of the month). CREAR-5 decision 8: never
    # money — every image route is one image, 1 creation (`pesos-creaciones-v2`).
    ImageRoute.TEMPLATE_ONLY: (
        "Solo tu plantilla",
        "Tarjeta de marca sin fotografía: horarios, menú, promos de texto. Sin IA.",
        _ONE_CREATION,
    ),
    ImageRoute.FROM_UPLOAD: (
        "Tu foto, con tu marca",
        "Sube la foto y la ponemos en tu marco. Sin retoque de IA.",
        _ONE_CREATION,
    ),
    ImageRoute.RESTYLE_ENHANCE: (
        "Tu foto, mejorada",
        "Corregimos luz y color sobre TU foto real. No requiere etiqueta de IA en anuncios.",
        _ONE_CREATION,
    ),
    ImageRoute.RESTYLE_SCENE: (
        "Tu producto, en otro fondo",
        "Lleva tu producto real a un contexto nuevo. Meta obliga a marcarlo como IA en anuncios.",
        _ONE_CREATION,
    ),
    ImageRoute.GENERATE: (
        "Generar desde cero",
        "La imagen se inventa por completo a partir del encargo.",
        _ONE_CREATION,
    ),
}

_NOT_DEFENSIBLE_FOR_TYPE = (
    "Esta publicación muestra algo que el cliente va a recibir: inventar su imagen no es "
    "defendible."
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


#: What «las reglas de tu marca» are, on the pill's hover: the layer-1 checks of
#: `qualify_creative.brand.fidelity` in the operator's words.
HARD_RULES_HINT = (
    "Lo que tu marca no permite: palabras prohibidas, promesas que no se pueden "
    "hacer, largo del texto, emojis y hashtags fuera de tu política."
)
#: Why a piece carries the AI mark, on its pill's hover.
AI_LABEL_HINT = (
    "La imagen se generó con IA. Instagram y TikTok piden avisarlo al publicar; el "
    "aviso va con la publicación, no hay que colocarlo a mano."
)


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
    #: What "Copiar guion" puts on the clipboard: the script, then its shots
    #: (§ request 2026-10-06 — the creator records from both).
    script_clipboard: str = ""
    #: A creator's script shows the post it goes out with (§ request 2026-10-08): its
    #: caption and CTA — not the hook, already the script's first line.
    description: str = ""


def _shot_lines(payload: CopyPayload) -> tuple[str, ...]:
    return tuple(
        f"{n} · {shot.seconds} s — {shot.visual}" + (f": «{shot.line}»" if shot.line else "")
        for n, shot in enumerate(payload.shots, 1)
    )


def script_clipboard(script: str, shots: tuple[str, ...]) -> str:
    """The script and, under a "Tomas:" line, one shot per line — plain text that pastes
    the same into a notes app, a doc or a chat."""
    if not shots:
        return script
    return "\n".join((script.rstrip(), "", "Tomas:", *shots))


# The brand rules (layer 1, `qualify_creative.brand.fidelity`) report in English with the
# rule id first — right for logs, unreadable for the operator ("caption_length: caption is
# 19 characters, below the brand minimum of 80"). Each known shape is said in Spanish,
# with what to do; an unknown one still shows, prefixed, rather than disappearing.
_FAILURE_PATTERNS: tuple[tuple[str, re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (
        "caption_length",
        re.compile(r"caption is (\d+) characters, below the brand minimum of (\d+)"),
        lambda m: (
            f"El texto de la publicación tiene {m[1]} caracteres y tu marca pide al menos "
            f"{m[2]}: "
            f"agrega {int(m[2]) - int(m[1])} más."
        ),
    ),
    (
        "caption_length",
        re.compile(r"caption is (\d+) characters, above the brand maximum of (\d+)"),
        lambda m: (
            f"El texto de la publicación tiene {m[1]} caracteres y tu marca permite como "
            f"máximo {m[2]}: "
            f"quita {int(m[1]) - int(m[2])}."
        ),
    ),
    (
        "banned_word",
        re.compile(r"banned word '(.+)' appears in the copy"),
        lambda m: f"El texto usa «{m[1]}», una palabra que tu marca tiene prohibida.",
    ),
    (
        "forbidden_claim",
        re.compile(r"forbidden claim '(.+)' appears in the copy"),
        lambda m: f"El texto dice «{m[1]}», una afirmación que tu marca no permite.",
    ),
    (
        "emoji_policy",
        re.compile(r"emoji policy is 'none' but the copy contains (\d+) emoji"),
        lambda m: f"Tu marca no usa emojis y el texto tiene {m[1]}.",
    ),
    (
        "emoji_policy",
        re.compile(r"at most (\d+)\) but the copy contains (\d+) emoji"),
        lambda m: f"Tu marca usa como máximo {m[1]} emojis y el texto tiene {m[2]}.",
    ),
    (
        "hashtag_policy",
        re.compile(r"(\d+) hashtags, below the brand minimum of (\d+)"),
        lambda m: f"Hay {m[1]} hashtags y tu marca pide al menos {m[2]}.",
    ),
    (
        "hashtag_policy",
        re.compile(r"(\d+) hashtags, above the brand maximum of (\d+)"),
        lambda m: f"Hay {m[1]} hashtags y tu marca permite como máximo {m[2]}.",
    ),
    (
        "hashtag_policy",
        re.compile(r"hashtag '#(.+)' is on the brand's never list"),
        lambda m: f"El hashtag #{m[1]} está entre los que tu marca nunca usa.",
    ),
    (
        "hashtag_policy",
        re.compile(r"required hashtag '#(.+)' is missing from the copy"),
        lambda m: f"Falta el hashtag #{m[1]}, que tu marca usa siempre.",
    ),
)


def failure_label(rule: str, detail: str) -> str:
    """One brand-rule failure in the operator's words (Spanish, with what to do)."""
    for known_rule, pattern, render in _FAILURE_PATTERNS:
        if rule == known_rule:
            match = pattern.search(detail)
            if match:
                return render(match)
    if rule == "route_blocked":
        return detail  # the brand's own policy reason, already written for people
    return f"Regla de marca ({rule}): {detail}"


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
            failure_label(str(f.get("rule", "")), str(f.get("detail", "")))
            for f in verdict.get("hard_failures", ())
            if isinstance(f, Mapping)
        )
    shots = _shot_lines(payload)
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
        shots=shots,
        script_clipboard=script_clipboard(payload.script, shots),
        description="\n\n".join(block for block in (payload.caption, payload.cta) if block),
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
    """One generated media item. Since 2026-10-06 a generated file lives in R2 only, so
    the page shows it through `url` (`/r2media/<token>`); `key` resolves with
    `rx.get_upload_url` only for a piece generated before that, still on disk."""

    key: str
    media_type: str  # "image" | "video"
    position: int
    label: str  # "Imagen", "Diapositiva 2 de 4", "Video"
    poster_key: str = ""
    #: One slide of a carousel — images and videos alike (§ 2026-10-09): what makes the
    #: piece show as a carousel instead of its files one under the other.
    is_slide: bool = False
    #: Backend path for media that lives only in R2 (`r2_media.issue_view_path`); "" →
    #: the page resolves `key` in the local upload store as before.
    url: str = ""
    #: The same for the video's poster frame (`poster_key`).
    poster_url: str = ""


#: Output ports of a template run (CONTRACT §1) → what the planner calls them. The
#: planner's vocabulary is its own ticket's; the review screen says it in the owner's
#: words (`REVIEW_PORT_LABELS`, m-24842979).
PORT_LABELS: dict[str, str] = {
    "reel": "Reel 9:16",
    "feed": "Feed 4:5",
    "story": "Historia 9:16",
}
REVIEW_PORT_LABELS: dict[str, str] = {
    "reel": "Reel (video corto) 9:16",
    "feed": "Publicación 4:5",
    "story": "Historia 9:16",
}


def build_media_vms(
    items: Sequence[tuple[str, str, int, Mapping[str, object] | None]],
) -> tuple[MediaVM, ...]:
    """(key, media_type, position, params) rows → display items, in order. A carousel
    kind's slides (`params.slide`, § 2026-10-09) are numbered whatever their type; an ad
    image's carousel is its images."""
    ordered = sorted(items, key=lambda item: item[2])
    images = [item for item in ordered if item[1] == "image"]
    out: list[MediaVM] = []
    for key, media_type, position, params in ordered:
        port = str((params or {}).get("port") or "")
        poster = str((params or {}).get("thumbnail_key") or "")
        if (params or {}).get("slide") is not None:
            label = f"Diapositiva {position + 1} de {len(ordered)}"
            out.append(MediaVM(key, media_type, position, label, poster, is_slide=True))
        elif port:
            # A template run's outputs are named by their port (one run → Reel + feed +
            # story), not numbered as slides.
            out.append(
                MediaVM(key, media_type, position, REVIEW_PORT_LABELS.get(port, port.title()))
            )
        elif media_type == "video":
            out.append(MediaVM(key, media_type, position, "Video", poster))
        elif len(images) > 1:
            label = f"Diapositiva {position + 1} de {len(images)}"
            out.append(MediaVM(key, media_type, position, label, is_slide=True))
        else:
            out.append(MediaVM(key, media_type, position, "Imagen"))
    return tuple(out)


#: The generator's content kinds as /create offers them (`ContentKind`), in order.
#: (key, title, blurb, icon)
KIND_OPTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "creator_script",
        "Guion para grabar",
        "Te damos lo que hay que decir y cada toma; lo graba alguien de tu equipo o un creador.",
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
        "Imagen publicitaria",
        "Un anuncio con tu producto, tu local o ambos. Una imagen o una galería.",
        "image",
    ),
    (
        "template",
        "Con plantilla",
        "Tus fotos reales en una plantilla de tu nicho: reel, publicación e historia de una vez.",
        "layout-template",
    ),
    (
        "carousel",
        "Galería",
        "Tres fotos o videos en una sola publicación: escenas generadas, una animada o "
        "publicaciones que ya hiciste.",
        "gallery-horizontal-end",
    ),
    (
        "clip",
        "Clip",
        "Un video generado sin presentador, desde fotogramas o referencias.",
        "film",
    ),
)
KIND_LABELS: dict[str, str] = {key: title for key, title, _, _ in KIND_OPTIONS}
#: «¿Qué quieres crear?» since 2026-10-06 — (key, title, blurb, icon). Carrusel joined on
#: 2026-10-09.
#: Imagen publicitaria left the picker the same day ("quita la variante de imagen
#: publicitaria") and came back on 2026-10-07, generated by Seedream ("crea de nuevo la
#: generación de imágenes publicitarias") — the fourth category.
CATEGORY_OPTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "script",
        "Guion para grabar",
        "Te damos lo que hay que decir y cada toma; lo graba alguien de tu equipo o un creador.",
        "clapperboard",
    ),
    # § request 2026-10-14: «Avatar» — a presenter, human or animated, tells it (the
    # key stays "video": the category every avatar kind was filed under)
    (
        "video",
        "Avatar",
        "Un video generado completo, presentado por un avatar humano o un personaje animado.",
        "user-round",
    ),
    # § request 2026-10-14: a generated video with no presenter — from its frames, or
    # from references (images, videos, audio), the catalog's or uploaded
    (
        "clip",
        "Clip",
        "Un video corto sin presentador, a partir de una foto (o de una foto de inicio y "
        "otra de final) o de tus fotos, videos y audios de referencia.",
        "film",
    ),
    # § request 2026-10-09: "poner la opción de carrusel al momento del tipo del post"
    (
        "carousel",
        "Galería",
        "Tres fotos o videos en una sola publicación: escenas generadas, un video animado "
        "como máximo o publicaciones que ya hiciste.",
        "gallery-horizontal-end",
    ),
    (
        "image",
        "Imagen",
        "Una escena generada con IA, con tu producto o tu local si subes sus fotos, tu "
        "texto y tu logo. Una imagen o una galería.",
        "image",
    ),
    (
        "template",
        "Plantilla",
        "Tus fotos reales en un diseño listo para tu rubro: una imagen para publicación o "
        "historia.",
        "layout-template",
    ),
    # «Ad» (the template's video) left the panel on 2026-10-14
)
#: Within Avatar, its types — (key, title, blurb, icon): the two avatar kinds.
VIDEO_TYPE_OPTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "avatar_video",
        "Avatar humano",
        "Un presentador humano generado con IA lee tu guion a cámara.",
        "user-round",
    ),
    (
        "animated_avatar_video",
        "Avatar animado",
        "Un personaje animado, creado por IA o desde tu imagen, cuenta tu mensaje.",
        "smile",
    ),
)
#: What a video piece is called: the clip types, and «Ad»'s Reel — the template kind
#: that rendered a video (`build_draft_vm` names a draft by it too).
VIDEO_TYPE_LABELS: dict[str, str] = {
    **{key: title for key, title, _, _ in VIDEO_TYPE_OPTIONS},
    "ad_video": "Video publicitario",
}


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
    #: The spend alone («$0.06», «Gratis»): what the pill shows. `cost_label` keeps the
    #: profile and models for its hover (request 2026-10-22: an operator does not read
    #: «Perfil v1 · claude-opus-5-5 + seedream-5-0-lite-260128»).
    cost_short: str = ""
    can_approve: bool = False
    # FSM facts for the review buttons: only a GENERATED draft can be rejected; a
    # GENERATED or already-REJECTED one can go back to generation.
    can_reject: bool = False
    can_regenerate: bool = False
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
    #: Why it failed, in the operator's words — never a vendor, model or cost.
    failure_detail: str = ""
    #: What the composition had to leave out (ticket 24803289: a catalog price that
    #: could not be printed whole), in the operator's words.
    warnings: tuple[str, ...] = ()
    #: The copy may be edited (the FSM's `edit` edge exists from this status).
    can_edit: bool = False
    #: «Descargar todo» (m-24828908): the backend path of the piece's `.zip` and its file
    #: name — "" while there is nothing to download (a draft still generating).
    download_path: str = ""
    download_name: str = ""
    #: m-24828907: «Descarga esta pieza: se elimina el …» (tone `warn`) while the piece is
    #: within 15 days of its deletion; "" otherwise.
    retention_notice: str = ""
    #: The piece's files were deleted after 3 months: the screen says «Contenido
    #: eliminado» instead of the media, and offers no download.
    media_purged: bool = False
    purged_label: str = ""
    #: m-24820142: the piece's Seedance 2.5 videos as one draft state — "" (no draft
    #: video), `draft`, `rendering`, `final`, `failed` or `expired` — and what the
    #: screen says about it.
    video_draft: VideoDraftVM = field(default_factory=lambda: NO_VIDEO_DRAFT)


# -- Seedance 2.5 draft mode (m-24820142) --------------------------------------------------

#: `draft_mode` states (strings, so the view-model never imports the backend; a test
#: that may import both keeps them equal: `test_creative_vm`).
VIDEO_DRAFT = "draft"
VIDEO_RENDERING = "rendering"
VIDEO_FINAL = "final"
VIDEO_FAILED = "failed"
VIDEO_EXPIRED = "expired"
APPROVE_VERSION_LABEL = "Aprobar esta versión"


@dataclass(frozen=True)
class VideoDraftVM:
    state: str
    #: «Vista previa» — the badge over the video. Never money (founder decision 8,
    #: m-24851824): the owner counts creations; the dollar cost is the team's.
    badge: str
    #: `signal_pill` tone of the badge.
    tone: str
    #: What happens or happened, in the operator's words.
    note: str
    #: The final failed (or was left half-made), its draft still lives and the piece is
    #: approved — `ContentService.retry_final` orders finals of an approved piece only.
    can_retry: bool = False
    #: A final is being made (this one, or another video of the piece while this
    #: state shows one that failed): the screen polls until none is left.
    rendering: bool = False


#: A piece without Seedance 2.5 draft videos.
NO_VIDEO_DRAFT = VideoDraftVM("", "", "neutral", "")

#: `final_poll_step` verdicts: keep polling; the finals landed; a final failed and
#: nothing is left rendering; stop without a word (the piece was regenerated).
FINAL_POLL_CONTINUE = "continue"
FINAL_POLL_DONE = "done"
FINAL_POLL_FAILED = "failed"
FINAL_POLL_STOP = "stop"


def final_poll_step(video: VideoDraftVM) -> str:
    """What the 1080p final poll does after one refresh of the piece (m-24820142): it
    keeps going while ANY video still renders, reports a failure only once nothing is
    left rendering, and goes quiet when the piece no longer waits for a final (it was
    regenerated: back to a draft, or no draft video at all)."""
    if video.rendering:
        return FINAL_POLL_CONTINUE
    if video.state == VIDEO_FINAL:
        return FINAL_POLL_DONE
    if video.state in (VIDEO_FAILED, VIDEO_EXPIRED):
        return FINAL_POLL_FAILED
    return FINAL_POLL_STOP


#: m-24842978: what approving a publication with no final to wait for says — it is not
#: out yet — on the publication's own page and in the gallery alike: the way to choose
#: when it goes out when it can go out, or that something is missing first.
APPROVED_TOAST = "Publicación aprobada. Ahora elige cuándo sale."
APPROVED_NOT_READY_TOAST = "Publicación aprobada. Revisa lo que falta antes de elegir cuándo sale."
APPROVED_TOAST_ACTION = "Elegir día y hora"
#: m-24842981 (review 2026-10-24, finding 8): a screen that is not the publication's own
#: page, after approving one whose final is being made or could not be ordered, offers
#: the way there (`/drafts/<id>`) — the toast alone left the owner nowhere to tap (N3).
APPROVED_OPEN_ACTION = "Ver publicación"
#: The default `approved` text of `approval_notice` (kept under its earlier name).
POST_APPROVED_TEXT = APPROVED_TOAST


class ApprovalNotice(NamedTuple):
    """The toast after approving, as `rx.toast` kind and text, and whether to offer
    «Elegir día y hora» with it (`offer_schedule`) or, on a screen that is not the
    publication's own page, «Ver publicación» (`offer_open`: its final is being made or
    could not be ordered, m-24842981)."""

    kind: str
    text: str
    offer_schedule: bool
    offer_open: bool = False


def approval_notice(
    video: VideoDraftVM,
    *,
    ready: bool = True,
    approved: str = APPROVED_TOAST,
    not_ready: str = APPROVED_NOT_READY_TOAST,
    elsewhere: str = "",
) -> ApprovalNotice:
    """The notice after approving a piece (m-24820142, m-24842978), from the piece
    itself — not from whether a final poll had to start, since one may already run for
    it. A 1080p final being made, or one that could not be ordered (the piece offers
    «Reintentar»), comes first: the publication cannot be given a day and time until
    its final exists (the Planificador refuses a draft, `MEDIA_DRAFT_PENDING`), so no
    way to schedule is offered then. Otherwise it is approved but not out yet: `ready`
    (the gallery's `schedule_readiness`) says whether it can be scheduled now
    (`approved`, with «Elegir día y hora») or something is missing first (`not_ready`).
    Every screen that approves uses it — the piece's page, the gallery's quick approval,
    Variaciones. A screen that is not the piece's own page says where to open it
    (`elsewhere`: «Ábrela», «Ábrela en Por aprobar»)."""
    if video.rendering:
        tail = f" {elsewhere} para ver cuándo está listo." if elsewhere else ""
        return ApprovalNotice(
            "info",
            f"Aprobada. Estamos preparando el video en alta calidad.{tail}",
            False,
            bool(elsewhere),
        )
    if video.can_retry:
        tail = f" {elsewhere} para reintentarlo." if elsewhere else " Puedes reintentarlo."
        return ApprovalNotice(
            "error",
            f"Versión aprobada, pero no pudimos pedir el video final.{tail}",
            False,
            bool(elsewhere),
        )
    if ready:
        return ApprovalNotice("success", approved, True)
    return ApprovalNotice("success", not_ready, False)


#: A final being made, in words: the piece's badge and the «Por aprobar» card's state
#: and (disabled) main button say the same (m-24842981, review 2026-10-24 finding 8).
FINAL_PREPARING_LABEL = "Preparando el video final"


#: The final's own note while it is not there yet, in the «Aprobada. Todavía no se
#: publica.» card: why no day and time can be chosen yet.
FINAL_RENDERING_NOTE = (
    "Estamos preparando el video en alta calidad. Cuando esté listo podrás elegir cuándo sale."
)
FINAL_FAILED_NOTE = (
    "No pudimos generar el video final. Reinténtalo y después podrás elegir cuándo sale."
)


#: The toast when the final lands while the piece is on screen: it is still not out —
#: choose when it goes out, or first see what is missing (m-24842978).
FINAL_READY_TEXT = "Tu video ya está listo. Ahora elige cuándo sale."
FINAL_READY_NOT_READY = "Tu video ya está listo. Revisa lo que falta antes de elegir cuándo sale."


def final_pending_note(video: VideoDraftVM) -> str:
    """Why an approved publication cannot be given a day and time because of its own
    video (m-24820142): its 1080p final is being made, or could not be ordered. Empty
    when its video does not hold it back."""
    if video.rendering:
        return FINAL_RENDERING_NOTE
    if video.can_retry:
        return FINAL_FAILED_NOTE
    return ""


#: A failed final on a piece no longer approved (edited after its approval): approving
#: it again orders the final, so that is what the screen says instead of «Reintentar».
FINAL_NEEDS_APPROVAL_TEXT = (
    "El video final no está listo. Cuando vuelvas a aprobar la publicación, lo preparamos "
    "en alta calidad."
)


def video_draft_vm(
    state: str,
    cost_usd: str | None,
    error: str = "",
    *,
    still_rendering: bool = False,
    approved: bool = False,
) -> VideoDraftVM:
    """The draft facts `draft_mode.draft_summary` returned, as the screen shows them.
    `still_rendering` (`draft_mode.draft_rendering`): some video of the piece has its
    final being made right now, whatever state the summary shows first. `approved`: the
    piece is approved — only then can a failed final be ordered again (`can_retry`);
    otherwise approving it again is what orders it. `cost_usd` is never shown: the
    owner never sees money (founder decision 8, m-24851824) — the spend stays recorded
    for the team, not on this screen."""
    del cost_usd
    if not state:
        return NO_VIDEO_DRAFT
    if state == VIDEO_DRAFT:
        return VideoDraftVM(
            state,
            "Vista previa",
            "info",
            "Es una vista previa en calidad baja, para que decidas rápido. Al aprobarla "
            "preparamos el mismo video en alta calidad.",
        )
    if state == VIDEO_RENDERING:
        return VideoDraftVM(
            state,
            FINAL_PREPARING_LABEL,
            "info",
            "Estamos preparando el video en alta calidad. Tarda unos minutos; puedes salir "
            "y lo verás aquí cuando esté listo.",
            rendering=True,
        )
    if state == VIDEO_FAILED and not approved:
        return VideoDraftVM(
            state,
            "Falta el video final",
            "warn",
            FINAL_NEEDS_APPROVAL_TEXT,
            rendering=still_rendering,
        )
    if state == VIDEO_FAILED:
        return VideoDraftVM(
            state,
            "Falta el video final",
            "error",
            error or "No pudimos generar el video final.",
            can_retry=True,
            rendering=still_rendering,
        )
    if state == VIDEO_EXPIRED:
        return VideoDraftVM(
            state,
            "La vista previa venció",
            "warn",
            "Las vistas previas duran 7 días. Crea la publicación otra vez para tener una nueva.",
            rendering=still_rendering,
        )
    return VideoDraftVM(state, "Video final", "ok", "")


# -- piece retention (m-24828907) ----------------------------------------------------------

#: `creative.retention.RetentionState` values the screens react to (kept as strings so
#: the view-model never imports the backend).
RETENTION_WARNING = "warning"
RETENTION_PURGED = "purged"

PURGED_TITLE = "Contenido eliminado"
PURGED_TEXT = (
    "Los archivos de esta publicación se eliminaron a los 3 meses para ahorrar espacio. "
    "El texto y su historial se conservan."
)


def short_date(iso: str | None) -> str:
    """`2027-01-10T12:00:00+00:00` → `10/01/2027`; "" when absent or unreadable."""
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{match.group(3)}/{match.group(2)}/{match.group(1)}" if match else ""


def retention_notice(state: str, deadline_iso: str | None, days_left: int | None) -> str:
    """The warning the ticket asks for, with its countdown — only in the warning window."""
    if state != RETENTION_WARNING:
        return ""
    when = short_date(deadline_iso)
    if days_left is None or not when:
        return ""
    if days_left <= 0:
        countdown = "hoy"
    elif days_left == 1:
        countdown = "mañana"
    else:
        countdown = f"en {days_left} días"
    return f"Descarga esta publicación: se elimina el {when} ({countdown})."


def purged_label(purged_iso: str | None) -> str:
    when = short_date(purged_iso)
    return f"{PURGED_TITLE} el {when}" if when else PURGED_TITLE


def draft_kind_label(kind: str, *, has_video: bool) -> str:
    """What the piece is called: a template that rendered its Reel is the Video
    publicitario (§ 2026-10-06), every other kind its own name."""
    if kind == "template" and has_video:
        return VIDEO_TYPE_LABELS["ad_video"]
    return KIND_LABELS.get(kind, "")


# Mirrors `qualify_api.creative.fsm.EDITABLE_STATUSES` (pinned equal by a test): editing is
# legal in review, after approval (it sends the draft back to review) and after a rejection.
EDITABLE_DRAFT_STATUSES: frozenset[str] = frozenset(
    {DraftStatus.GENERATED.value, DraftStatus.APPROVED.value, DraftStatus.REJECTED.value}
)


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
    failure_detail: str | None = None,
    warnings: Sequence[str] = (),
) -> DraftVM:
    """Assemble the detail view-model. `can_approve` is the FSM fact (only a GENERATED
    draft has the approve edge); which VARIANT may be approved is per-variant `passed` —
    the state combines both with the operator's selection."""
    passing = sum(1 for v in variants if v.passed)
    # said as an operator reads it (request 2026-10-22: «reglas duras» meant nothing);
    # what the rules are is the pill's hover (`HARD_RULES_HINT`)
    if not variants:
        fidelity_summary = ""
    elif passing == len(variants):
        fidelity_summary = "Cumple las reglas de tu marca"
    else:
        fidelity_summary = f"{passing} de {len(variants)} textos cumplen las reglas de tu marca"
    can_approve = status == DraftStatus.GENERATED.value
    blocking_reason: str | None = None
    if can_approve and variants and passing == 0:
        can_approve = False
        blocking_reason = "Ningún texto cumple las reglas de tu marca; no se puede aprobar."
    return DraftVM(
        draft_id=draft_id,
        status=status,
        status_label=status_label(status),
        status_tone=status_tone(status),
        variants=tuple(variants),
        image_url=image_url,
        fidelity_summary=fidelity_summary,
        cost_label=format_cost_label(total_cost_usd, voice_profile_version, model_ids),
        cost_short=format_cost_label(total_cost_usd, None, ()),
        can_approve=can_approve,
        # an approved piece is rejected from Piezas, where the calendar is known
        can_reject=status == DraftStatus.GENERATED.value,
        can_regenerate=status in (DraftStatus.GENERATED.value, DraftStatus.REJECTED.value),
        blocking_reason=blocking_reason,
        failure=failure_vm(failure_reason),
        requires_ai_disclosure=requires_ai_disclosure,
        created_label=created_label,
        is_drafting=status == DraftStatus.DRAFTING.value,
        is_failed=status == DraftStatus.FAILED.value,
        kind=kind,
        kind_label=draft_kind_label(
            kind, has_video=any(item.media_type == "video" for item in media)
        ),
        media=tuple(media),
        has_video=any(item.media_type == "video" for item in media),
        has_script=kind in ("creator_script", "avatar_video", "animated_avatar_video"),
        failure_detail=failure_detail or "",
        warnings=tuple(warnings),
        can_edit=status in EDITABLE_DRAFT_STATUSES,
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


# ---------------------------------------------------------------------------
# The recipe step of the template kind (plan-mvp-plantillas-remotion.md §2.1 #4, MP-10):
# the router's three options as the cards the operator picks from.

#: `Engine` value → (badge label, tone). Remotion is the product's own engine (accent);
#: the talking presenter is a vendor (info); UGC is a quote with no renderer yet (neutral).
ENGINE_BADGES: dict[str, tuple[str, str]] = {
    "remotion": ("Remotion", "accent"),
    "omnihuman": ("Avatar", "info"),
    "ugc": ("Para grabar", "neutral"),
}
#: Output port → the word the card prints, same vocabulary as `PORT_LABELS` but short:
#: "Reel · Feed · Historia" has to fit one line of a card.
OUTPUT_WORDS: dict[str, str] = {"reel": "Reel", "feed": "Feed", "story": "Historia"}
UGC_QUOTE_ONLY = "solo cotiza"


@dataclass(frozen=True)
class RecipeOptionVM:
    """One of the three cards of «¿Cómo la hacemos?». `key` is what the state stores
    as the selection (the engine value — the router returns one option per engine)."""

    key: str  # Engine value
    engine_label: str  # "Remotion" | "Avatar" | "UGC"
    engine_tone: str
    label: str  # the manifest's name, or the engine's own label
    template_id: str  # "" for a non-template option
    template_version: int  # 0 when none
    cost_label: str  # "USD 0.00" | "USD 0.50 a 2.00"
    eta_label: str  # "~40 s", "" when unknown
    outputs_label: str  # "Reel · Feed · Historia"
    suggested: bool
    available: bool
    reason: str  # why it cannot be chosen ("" when it can)
    selectable: bool  # available AND an engine the generator can run from this step
    rule: int  # the router rule that suggested it, 0 when not suggested


def eta_label(eta_sec: float | None) -> str:
    """Render time the operator can read: seconds under a minute and a half, minutes
    (rounded up) after — a template takes "~40 s", a quote has no time at all."""
    if eta_sec is None:
        return ""
    seconds = int(round(eta_sec))
    if seconds <= 90:
        return f"~{max(seconds, 1)} s"
    minutes = -(-seconds // 60)
    return f"~{minutes} min"


def outputs_label(outputs: Sequence[str]) -> str:
    return " · ".join(OUTPUT_WORDS.get(port, port.title()) for port in outputs)


def build_recipe_options(options: Sequence[object]) -> tuple[RecipeOptionVM, ...]:
    """`suggest_recipes`' options (`qualify_creative.render.RecipeOption`, duck-typed so
    this module stays import-light) → the cards, in the router's order. UGC is never
    selectable from the generator: it quotes, it does not render yet (plan §5, Vie 9)."""
    out: list[RecipeOptionVM] = []
    for option in options:
        engine = str(getattr(option, "engine"))
        label, tone = ENGINE_BADGES.get(engine, (engine.title(), "neutral"))
        available = bool(getattr(option, "available"))
        reason = str(getattr(option, "reason") or "")
        selectable = available and engine != "ugc"
        if engine == "ugc" and not reason:
            reason = UGC_QUOTE_ONLY
        rule = getattr(option, "rule")
        out.append(
            RecipeOptionVM(
                key=engine,
                engine_label=label,
                engine_tone=tone,
                label=str(getattr(option, "label")),
                template_id=str(getattr(option, "template_id") or ""),
                template_version=int(getattr(option, "template_version") or 0),
                cost_label=str(getattr(option, "cost_label")),
                eta_label=eta_label(getattr(option, "eta_sec")),
                outputs_label=outputs_label(tuple(getattr(option, "outputs") or ())),
                suggested=bool(getattr(option, "suggested")),
                available=available,
                reason=reason,
                selectable=selectable,
                rule=int(rule) if rule is not None else 0,
            )
        )
    return tuple(out)


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
    "RecipeOptionVM",
    "RouteOptionVM",
    "SelectOptionVM",
    "SourceVM",
    "ToneRowVM",
    "VoiceProposalVM",
    "build_draft_summary_vm",
    "build_draft_vm",
    "build_readiness_vm",
    "build_recipe_options",
    "build_route_options",
    "build_variant_vm",
    "build_voice_proposal_vm",
    "content_type_options",
    "failure_vm",
    "creations_left_label",
    "creations_use_notice",
    "format_cost_label",
    "not_enough_creations_text",
    "pieces_use_notice",
    "presenter_fallback_text",
    "renewal_day_label",
    "videos_short_text",
    "VIDEO_TOO_LONG",
    "gap_vm",
    "status_label",
    "status_tone",
]


# ---------------------------------------------------------------------------------------
# Draft review (QUA-118 v2 polish): hashtags suggested from the caption, CTA ideas.

# Words that never make a useful hashtag on their own (Spanish + a few English fillers).
_HASHTAG_STOPWORDS: frozenset[str] = frozenset(
    """
    para como esta este esto estos estas pero porque sobre entre desde hasta donde cuando
    todo toda todos todas tiene tienen hacer hace hacemos puede pueden nuestro nuestra
    nuestros nuestras vuestro tuyo suyo cada otro otra otros otras mismo misma muy mucho
    mucha muchos muchas poco poca algo nada solo sólo tambien también ahora aqui aquí alli
    allí ellos ellas usted ustedes somos eres será sera fue fueron estar estamos están estan
    tener tengo tienes había habia haber hoy ayer mañana manana siempre nunca contenido
    unicamente únicamente prueba técnica tecnica publicacion publicación desde with that this
    your from have will just more about into
    """.split()
)
HASHTAG_LIMIT = 30  # Instagram's own limit per post
CAPTION_LIMIT = 2200
HOOK_LIMIT = 60

#: Calls to action people recognise — what the operator can drop in with one click.
CTA_SUGGESTIONS: tuple[str, ...] = (
    "Escríbenos por mensaje directo",
    "Reserva en el link de la bio",
    "Guarda esta publicación para después",
    "Comenta tu favorito",
    "Compártelo con alguien",
    "Visítanos hoy",
)


def _fold(text: str) -> str:
    """Lowercase without accents: «Promoción» → «promocion» (hashtags are typed so)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def hashtag_list(text: str) -> list[str]:
    """ "#promo, #2x1 sabor" → ["promo", "2x1", "sabor"]: what the field holds, as tags
    without «#», each once, in order."""
    seen: list[str] = []
    for raw in re.split(r"[\s,;]+", text or ""):
        tag = _fold(raw.strip().lstrip("#"))
        tag = re.sub(r"[^a-z0-9_ñ]", "", tag)
        if tag and tag not in seen:
            seen.append(tag)
    return seen


def format_hashtags(tags: list[str]) -> str:
    return " ".join(f"#{tag}" for tag in tags)


def caption_hashtag_suggestions(
    caption: str, current: str, extra: tuple[str, ...] | list[str] = (), limit: int = 10
) -> list[str]:
    """Hashtags suggested from what the caption says: the brand's catalog matches first
    (`extra`, real tags people use), then the caption's own #tags, then its strongest
    words (repeated ones first, then in order of appearance). Never one already chosen."""
    chosen = set(hashtag_list(current))
    found: list[str] = []

    def take(tag: str) -> None:
        tag = re.sub(r"[^a-z0-9_ñ]", "", _fold(tag.lstrip("#")))
        if len(tag) >= 3 and tag not in chosen and tag not in found:
            found.append(tag)

    for tag in extra:
        take(tag)
    for tag in re.findall(r"#(\w+)", caption or ""):
        take(tag)
    words = [
        w
        for w in re.findall(r"[a-záéíóúüñ]+", (caption or "").lower())
        if len(w) >= 4 and _fold(w) not in _HASHTAG_STOPWORDS and w not in _HASHTAG_STOPWORDS
    ]
    order = {w: i for i, w in reversed(list(enumerate(words)))}
    counts: dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    for w in sorted(counts, key=lambda w: (-counts[w], order[w])):
        take(w)
    return found[:limit]


def caption_keywords(caption: str, limit: int = 5) -> list[str]:
    """The caption's strongest words — what the hashtag catalog is asked about."""
    return [t for t in caption_hashtag_suggestions(caption, "", limit=limit * 2) if t][:limit]


# Several calls to action in the one `cta` field, separated so they read as a list.
CTA_SEPARATOR = " · "


def cta_list(text: str) -> list[str]:
    """ "Escríbenos por DM · Guarda este post" → both, each once, in order."""
    items: list[str] = []
    for part in re.split(r"\s*(?:·|\n|\|)\s*", text or ""):
        part = part.strip()
        if part and part not in items:
            items.append(part)
    return items


def format_ctas(items: list[str]) -> str:
    return CTA_SEPARATOR.join(items)


# CREAR-6 (m-24842980): «Debe mencionar» / «Debe evitar» are typed one phrase at a time
# and shown as chips; the brief still carries them as one comma-separated text (the
# contract `context_ai`/the copy pipeline already read), so the owner never types a comma.
PHRASE_SEPARATOR = ", "
PHRASE_LIMIT = 12
#: What the help says once `PHRASE_LIMIT` is reached (UX review).
PHRASE_LIMIT_HINT = "Ya tienes 12 frases, el máximo. Quita una para agregar otra."


def phrase_list(text: str) -> list[str]:
    """ "envío gratis, reserva por WhatsApp" → both, each once (case-insensitive), in
    order; empty pieces dropped."""
    items: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"\s*[,;\n]\s*", text or ""):
        part = " ".join(part.split())
        if part and _fold(part) not in seen:
            seen.add(_fold(part))
            items.append(part)
    return items


def format_phrases(items: list[str]) -> str:
    return PHRASE_SEPARATOR.join(items)


def add_phrase(current: str, new: str, limit: int = PHRASE_LIMIT) -> str:
    """`current` with what was typed in `new` appended (a pasted list is split), never a
    repeat and never past `limit`."""
    items = phrase_list(current)
    folded = {_fold(item) for item in items}
    for item in phrase_list(new):
        if len(items) >= limit:
            break
        if _fold(item) not in folded:
            folded.add(_fold(item))
            items.append(item)
    return format_phrases(items)


def remove_phrase(current: str, phrase: str) -> str:
    return format_phrases([item for item in phrase_list(current) if item != phrase])


HASHTAG_KIND_LABELS: dict[str, str] = {
    "popular": "Populares",
    "nicho": "De nicho",
    "marca": "Locales y de marca",
}


@dataclass(frozen=True)
class HashtagIdeaVM:
    """One AI-suggested hashtag for the caption (`qualify_api.hashtags.caption`)."""

    tag: str
    kind: str  # popular / nicho / marca
    reason: str
    seen_label: str = ""  # "visto 1.2k veces" when the catalog has seen it on real posts


def seen_label(count: int) -> str:
    if count <= 0:
        return ""
    shown = f"{count / 1000:.1f}k".replace(".0k", "k") if count >= 1000 else str(count)
    return f"visto {shown} {'vez' if count == 1 else 'veces'} en publicaciones reales"


# ---------------------------------------------------------------------------------------
# «Creaciones del mes» (CREAR-5, m-24848531): what the owner reads instead of money.

#: What a presenter the weights table does not price says (an own script too long).
PRESENTER_TOO_LONG = (
    "Tu guion es muy largo para un video con presentador: acórtalo a unos 30 segundos."
)
#: A generated video longer than the table offers (founder, 2026-10-24: up to 10 s).
VIDEO_TOO_LONG = "Este video puede durar 5 o 10 segundos. Cámbialo en Duración."


def creations_left_label(left: int, quota: int, videos_left: int = 0, video_quota: int = 0) -> str:
    """The month's balance, never money. With a video quota it is the founder's
    sentence (2026-10-24): «Te quedan {n} de 30 creaciones y {v} de 4 videos este mes.»;
    without one, «Te quedan 18 de 30 este mes»."""
    verb = "Te queda" if left == 1 else "Te quedan"
    if video_quota > 0:
        return (
            f"{verb} {left} de {quota} creaciones y {videos_left} de {video_quota} videos este mes."
        )
    return f"{verb} {left} de {quota} este mes"


def videos_short_text(videos: int, videos_left: int, video_quota: int, *, renews: str = "") -> str:
    """The month has no video left for this piece (founder, 2026-10-24): «Ya usaste tus
    4 videos de este mes. Vuelven el 1 de noviembre.» — or, for a carousel with more
    animated slides than videos left, how many it uses and how many are left."""
    day = renews or "próximo mes"
    if videos_left <= 0:
        return f"Ya usaste tus {video_quota} videos de este mes. Vuelven el {day}."
    left = "te queda 1" if videos_left == 1 else f"te quedan {videos_left}"
    drop = videos - videos_left
    remove = "Quita 1 video animado" if drop == 1 else f"Quita {drop} videos animados"
    return (
        f"Esta publicación usa {videos} videos y este mes {left}. "
        f"{remove} o espera al {day}, cuando vuelven tus {video_quota}."
    )


_MONTHS_LONG = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

#: What the owner can still do when the month is short (UX review 2026-10-23, N8).
SHORT_ADVICE_SIMPLER = "Elige algo más sencillo, como una imagen, o espera"
SHORT_ADVICE_FEWER_IDEAS = "Descarta algunas ideas o espera"


def renewal_day_label(day: date | None) -> str:
    """«1 de noviembre» — the day the month's creations renew ("" when unknown)."""
    if day is None:
        return ""
    return f"{day.day} de {_MONTHS_LONG[day.month - 1]}"


def not_enough_creations_text(
    missing: int, *, quota: int = 0, renews: str = "", advice: str = ""
) -> str:
    """«Te faltan 2 creaciones este mes.» — nothing is created, never half of it — plus
    what to do now (UX review 2026-10-23): `advice` (what else the owner can make) and
    the day the `quota` renews. Without a quota only the first sentence is said."""
    if missing == 1:
        short = "Te falta 1 creación este mes."
    else:
        short = f"Te faltan {missing} creaciones este mes."
    if quota <= 0:
        return short
    when = renews or "próximo mes"
    if advice:
        return f"{short} {advice} al {when}, cuando se renuevan tus {quota}."
    return f"{short} El {when} se renuevan tus {quota}."


def creations_use_notice(
    weight: int,
    left: int,
    quota: int,
    *,
    presenter: bool = False,
    video: bool = False,
    subject: str = "",
    videos: int = 0,
    videos_left: int = 0,
    video_quota: int = 0,
) -> str:
    """What one request uses, said before it is created. The presenter's sentence is the
    founder's (2026-10-23): «Este video con presentador usa 25 de tus creaciones. Te
    quedarían {n} este mes.»; a generated video's too (2026-10-24): «Este video usa 1
    de tus 4 videos del mes. Te quedarían {v}.»"""
    after = max(left - weight, 0)
    if videos > 0:
        videos_after = max(videos_left - videos, 0)
        if weight <= 0:
            what = subject or ("Este video" if videos == 1 else "Esta publicación")
            remain = "Te quedaría" if videos_after == 1 else "Te quedarían"
            return (
                f"{what} usa {videos} de tus {video_quota} videos del mes. {remain} {videos_after}."
            )
        what = subject or "Esta publicación"
        uses = "1 creación" if weight == 1 else f"{weight} creaciones"
        clips = "1 video" if videos == 1 else f"{videos} videos"
        remain = "Te quedaría" if after == 1 else "Te quedarían"
        return (
            f"{what} usa {uses} y {clips}. {remain} {after} de {quota} creaciones y "
            f"{videos_after} de {video_quota} videos."
        )
    if presenter:
        return (
            f"Este video con presentador usa {weight} de tus creaciones. "
            f"Te quedarían {after} este mes."
        )
    what = subject or ("Este video" if video else "Esta publicación")
    return f"{what} usa {weight} de tus creaciones. Te quedarían {after} de {quota}."


def presenter_fallback_text(seconds: int, weight: int) -> str:
    """The shorter presenter a short month still pays for (CREAR-5: 15 s, 13)."""
    return f"Te alcanza para el video de {seconds} segundos, que usa {weight} de tus creaciones."


def pieces_use_notice(
    pieces: int, left: int, quota: int, weight: int = 1, *, renews: str = ""
) -> str:
    """«Variaciones»: what generating the kept ideas uses, or what is missing — the batch
    is all or nothing (CREAR-5)."""
    needed = pieces * weight
    if needed > left:
        return not_enough_creations_text(
            needed - left,
            quota=quota,
            renews=renews,
            advice=SHORT_ADVICE_FEWER_IDEAS if left > 0 else "",
        )
    after = left - needed
    if pieces == 1:
        return f"Esta publicación usa {needed} de tus creaciones. Te quedarían {after} de {quota}."
    return (
        f"Estas {pieces} publicaciones usan {needed} de tus creaciones. "
        f"Te quedarían {after} de {quota}."
    )
