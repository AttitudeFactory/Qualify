"""Reflex state for the Brand Content Engine screens (design §6).

Custody rules inherited from `connections_state.py` / `publishing_state.py`:

- Holds only whitelisted `creative_vm` dataclasses, never ORM rows or service records.
- The active tenant comes from `AuthState.session_tenant_id` (set only by login) and is
  parsed through `tenant.tenant_uuid` immediately before it reaches the provider.
- Every provider call is blocking (SQLAlchemy is synchronous here), so state events run
  them off the event loop with `asyncio.to_thread` inside `background=True` handlers.
- The upload handler (`handle_photo_upload`) is FOREGROUND on purpose: Reflex forbids
  `background=True` on a handler that receives `list[rx.UploadFile]` (same constraint
  `publishing_state.py` documents). It only writes the bytes locally — quick local I/O.

Polling (§6.6): `poll_draft` backs off 1s → 2s → 4s, caps at 5s, and gives up at 5
minutes with an explicit timeout state — an infinite spinner is a lie about the system.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import urllib.parse
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import reflex as rx
from pydantic import ValidationError
from qualify_api.creative.fsm import InvalidTransition
from qualify_api.creative.service import (
    BrandNotReady,
    RouteBlockedByPolicy,
    UnknownDraft,
    UnknownVariant,
)
from qualify_api.creative.voice_service import NotProposed, UnknownBrandKit, UnknownVersion
from qualify_creative.enums import (
    BriefIntent,
    BriefObjective,
    ContentFormat,
    ContentKind,
    ContentType,
)
from qualify_creative.schemas import MAX_BRAND_ELEMENTS
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState, brand_tenant_id
from .creative_provider import (
    HeyGenNotConfigured,
    acting_user_id,
    approve_draft,
    approve_voice,
    brand_clone_voice,
    brand_media,
    brand_pieces,
    brand_readiness,
    catalog_products,
    configured_video_engine,
    default_brand_id,
    draft_detail,
    edit_variant,
    heygen_catalog,
    list_drafts,
    load_kit_form,
    load_voice_screen,
    preview_brief_prompt,
    propose_voice,
    reject_draft,
    route_options_for,
    save_kit,
    submit_brief,
    template_blocker,
)
from .creative_vm import (
    CAPTION_LIMIT,
    CTA_SUGGESTIONS,
    HASHTAG_LIMIT,
    HOOK_LIMIT,
    KIND_LABELS,
    VIDEO_TYPE_LABELS,
    CopyVariantVM,
    DraftSummaryVM,
    DraftVM,
    HashtagIdeaVM,
    KitFormVM,
    ReadinessVM,
    RouteOptionVM,
    VoiceProposalVM,
    caption_hashtag_suggestions,
    caption_keywords,
    content_type_options,
    cta_list,
    format_ctas,
    format_hashtags,
    hashtag_list,
    seen_label,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_BRAND = "Este negocio no tiene ninguna marca provisionada todavía."
_NO_USER = "Este negocio no tiene ningún usuario al que atribuir la acción."
_DB_ERROR = "No se pudo hablar con la base de datos. Inténtalo de nuevo en un momento."
_KIT_SAVED = "Brand kit guardado."
_KIT_INVALID = "Revisa los campos del kit: "
_NO_KIT_TO_PROPOSE = (
    "Aún no hay un brand kit del que destilar la voz. Complétalo primero en /brand."
)
_STALE_PROPOSAL = "Esa propuesta ya no está vigente. Recargamos el estado real."
_BRIEF_NOT_READY = "La marca aún no está lista para generar. Completa lo que falta en /brand."
_ROUTE_BLOCKED = "Esa ruta de imagen está bloqueada para esta marca: "
_BRIEF_INVALID = "El encargo no se puede ejecutar: "
_UPLOAD_FAILED = "No se pudo leer la foto subida. Intenta con otro archivo."
_UPLOAD_REQUIRED = "Esta ruta trabaja sobre tu foto: súbela antes de enviar el encargo."
_TOPIC_REQUIRED = "Cuéntanos qué quieres en la pieza: es lo único obligatorio."
_SCENE_REQUIRED = "Describe la escena de la imagen: es lo único obligatorio."
_HEYGEN_OFF = "Los videos con avatar no están disponibles ahora mismo."
_HEYGEN_DOWN = "No pudimos cargar los avatares. Inténtalo de nuevo."

#: `ContentKind` values that can be chosen today — all five since the template engine
#: landed (plan-mvp-plantillas-remotion.md, 2026-10-05).
_ENABLED_KINDS = (
    "creator_script",
    "avatar_video",
    "animated_avatar_video",
    "static_flyer",
    "template",
    "carousel",
)
#: «¿Qué quieres crear?» since 2026-10-06: three categories, and Video has its types.
#: `ad_video` is the template kind rendering its Reel; «Con plantilla» is the same
#: kind rendering one still (feed or story).
GEN_CATEGORIES = ("script", "video", "image", "template", "carousel")
VIDEO_TYPES = ("avatar_video", "animated_avatar_video", "ad_video")
_CATEGORY_KIND = {
    "script": "creator_script",
    "video": "avatar_video",
    "image": "static_flyer",
    "template": "template",
    "carousel": "carousel",
}
#: The carousel's slides (§ request 2026-10-09): where each comes from, what it prints,
#: how long a video lasts — the editor's values, `CarouselSlide`'s fields.
_SLIDE_SOURCES = ("generated", "animated")
_SLIDE_TEXTS = ("none", "hook", "cta")
_SLIDE_SECONDS = ("5", "10")
_CAROUSEL_MIN = 2
_CAROUSEL_MAX = 10
#: A Seedance presenter has no library: «Mujer» / «Hombre» are a described synthetic
#: person like «Personalizado», with this description (§ request 2026-10-07).
_SEEDANCE_PRESENTERS = {
    "female": "Mujer latina de unos 30 años, sonriente y cercana, ropa casual moderna.",
    "male": "Hombre latino de unos 30 años, sonriente y cercano, ropa casual moderna.",
}
#: The formats each template use renders — ONE output, the one of this format.
_TEMPLATE_FORMATS = {
    "video": (ContentFormat.REELS_9_16,),
    "template": (ContentFormat.FEED_4_5, ContentFormat.STORY_9_16),
}
#: Copy options per piece (§ request 2026-10-08): only a real creator's script offers
#: several — it has no media made from one of them; every other kind asks for ONE until
#: the angles engine exists.
_SCRIPT_OPTIONS = 3
#: The template's photos (`promo_producto`, photos.min): asked for in its own section,
#: not discovered on Generar. The ad image takes one (§ request 2026-10-08).
_TEMPLATE_MIN_PHOTOS = 2
#: HeyGen's own gender values, as the catalog carries them on looks and voices.
_GENDERS = ("female", "male")
#: `AdImageMode` values, in the picker's order.
_AD_MODES = ("product", "background", "both")
_OBJECTIVES = frozenset(o.value for o in BriefObjective)
_INTENTS = frozenset(i.value for i in BriefIntent)
#: When a piece lands (§ request 2026-10-09): what the toast says, and what the
#: browser's own notification says when the tab is in the background.
_GEN_READY_TOAST = "Tu pieza está lista. Revísala en Crear pieza o en Borradores."
_GEN_FAILED_TOAST = "No se pudo generar la pieza. El detalle está en Crear pieza."
_DRAFT_READY_TOAST = "Tu borrador ya está regenerado. Revísalo en Borradores."
_DRAFT_FAILED_TOAST = "No se pudo regenerar el borrador. El detalle está en Borradores."
_ASK_NOTIFICATIONS_JS = (
    "if (window.Notification && Notification.permission === 'default') "
    "{ Notification.requestPermission(); }"
)


def _notify_js(title: str, body: str) -> str:
    """The browser's notification — only when the tab is NOT in front (the toast covers
    the rest), and only if the operator allowed it."""
    return (
        "if (document.hidden && window.Notification && Notification.permission === 'granted') "
        f"{{ new Notification({title!r}, {{body: {body!r}}}); }}"
    )


def _generation_done_events(outcome: str, source: str = "generator") -> list[rx.event.EventSpec]:
    """What the app says when a piece lands: `outcome` is "ready" or "failed"; `source`
    is "generator" (a piece from /create) or "draft" (a draft regenerated in Borradores,
    § pendientes-generador-contenido.md §5)."""
    texts = {
        ("generator", "ready"): _GEN_READY_TOAST,
        ("generator", "failed"): _GEN_FAILED_TOAST,
        ("draft", "ready"): _DRAFT_READY_TOAST,
        ("draft", "failed"): _DRAFT_FAILED_TOAST,
    }
    text = texts[(source, outcome)]
    toast = rx.toast.success if outcome == "ready" else rx.toast.error
    return [toast(text, duration=8000), rx.call_script(_notify_js("Qualify", text))]


#: The generator's numbered sections, in order, under «¿Qué creamos?» (§ request
#: 2026-10-08: one view with sections replaced the step-by-step wizard). `presenter`
#: only applies to the two avatar kinds; «Reglas» is a folded, unnumbered extra.
GENERATOR_SECTIONS = ("topic", "channel", "presenter", "details")


def _is_carousel(draft: DraftVM | None) -> bool:
    """A piece whose media is more than one image (an ad image's slides), or a carousel
    kind's slides — images and videos alike (§ 2026-10-09)."""
    if draft is None:
        return False
    images = sum(1 for item in draft.media if item.media_type == "image")
    return images > 1 or sum(1 for item in draft.media if item.is_slide) > 1


def _next_slide(draft: DraftVM | None, index: int) -> int:
    """The slide after `index`, wrapping to the first. A video slide holds the carousel
    still (§ 2026-10-09): the tick would cut it every 4 s — the arrows move on."""
    total = len(draft.media) if draft is not None else 0
    if not total:
        return 0
    if 0 <= index < total and draft.media[index].media_type == "video":  # type: ignore[union-attr]
        return index
    return (index + 1) % total


def _new_slide(source: str, *, text: str = "none") -> dict[str, str]:
    """One editor row of a generated or animated slide. Its product photo is its own
    (§ 2026-10-09: uploaded in the slide, not in a list for the whole carousel)."""
    return {
        "source": source,
        "scene": "",
        "photo_key": "",
        "photo_name": "",
        "background": "1",
        "text": text,
        "seconds": "5",
        "key": "",
        "label": "",
        "view": "",
        "media_type": "image" if source == "generated" else "video",
    }


def _default_slides() -> list[dict[str, str]]:
    """What a new carousel opens on: a generated cover with the hook, then an animated
    slide — with the closing CTA slide, three slides ready to generate."""
    return [_new_slide("generated", text="hook"), _new_slide("animated")]


def _slide(draft: DraftVM | None, index: int) -> int:
    """`index` kept within the piece's slides."""
    last = len(draft.media) - 1 if draft is not None else 0
    return max(0, min(int(index), max(last, 0)))


def generator_sections(kind: str) -> list[str]:
    """The sections `kind` shows, in order. The ad image asks no «¿Qué quieres en la
    imagen?» (§ request 2026-10-08): its scene, in its details, is it."""
    has_presenter = kind in ("avatar_video", "animated_avatar_video")
    # the carousel says what it is about in «topic»; its slides are its details
    return [
        section
        for section in GENERATOR_SECTIONS
        if (section != "presenter" or has_presenter)
        and (section != "topic" or kind != "static_flyer")
    ]


#: The Brand Kit's list fields edited as pills: pill-input key → the `kit_*` attr that
#: stores the list (one value per line, the format the kit form and the brief/brandboard
#: proposals already use).
_KIT_PILL_FIELDS = {
    "do": "kit_do_examples",
    "dont": "kit_dont_examples",
    "cta": "kit_cta_patterns",
    "banned": "kit_banned_words",
    "claims": "kit_forbidden_claims",
}


def _pill_items(text: str) -> list[str]:
    """A newline-joined kit list as its non-empty, trimmed values."""
    return [line.strip() for line in text.splitlines() if line.strip()]


_DURATIONS = ("15", "30", "45", "60")
_FORMAT_LABELS = {
    "feed_4_5": "Post 4:5",
    "feed_1_1": "Post cuadrado 1:1",
    "reels_9_16": "Reel 9:16",
    "story_9_16": "Story 9:16",
}
#: What the result view says while the piece is being made, per kind — generic, with
#: no vendor or model (§ request 2026-10-08).
_GEN_WAITING = {
    "creator_script": "Escribiendo tu guion…",
    "avatar_video": "Generando tu video. Puede tardar unos minutos…",
    "animated_avatar_video": "Generando tu video. Puede tardar unos minutos…",
    "static_flyer": "Generando tu imagen, ya casi está…",
    "template": "Generando tu pieza, ya casi está…",
    "carousel": "Armando tu carrusel. Si lleva videos, puede tardar unos minutos…",
}
_TEMPLATE_PHOTO_REQUIRED = (
    "Una plantilla trabaja sobre fotos reales: necesita al menos 2 (las del producto del "
    "catálogo cuentan)."
)
_CATALOG_ERROR = "No pudimos leer el catálogo. Puedes seguir subiendo tus fotos."
_TEMPLATE_BLOCKED = "No podemos hacer esta pieza con plantilla: "
_GEN_POLL_SECONDS = 3.0
#: An AI avatar plus its render can take many minutes; the draft's reaper is 20.
_GEN_POLL_BUDGET_SECONDS = 20 * 60
_MAX_PRODUCTS = 10
_NOT_REJECTABLE = (
    "Este borrador ya no se puede rechazar: ya fue rechazado o aprobado. "
    "Actualiza la página para ver su estado."
)
_DRAFT_GONE = "Ese borrador no existe o ya no es visible para este negocio."
_NOT_EDITABLE = (
    "Este borrador ya no se puede editar: está en preparación, publicado o falló. "
    "No se guardó ningún cambio."
)
_VARIANT_REQUIRED = "Elige una variante antes de aprobar."
_POLL_TIMEOUT = (
    "La generación lleva más de 5 minutos sin terminar. La bandeja mostrará el "
    "estado real cuando el sistema la marque como fallida."
)

#: §6.6 polling schedule: backoff 1s → 2s → 4s, cap 5s, give up at 5 minutes.
_POLL_DELAYS = (1.0, 2.0, 4.0)
_POLL_CAP_SECONDS = 5.0
_POLL_BUDGET_SECONDS = 300.0

#: The generation stages the progress indicator names (§6.4: a real per-stage
#: indicator, not a blind spinner). The MVP pipeline generates copy, then verifies.
GENERATION_STAGES = ("Copy", "Imagen", "Verificación")


#: Where each of ¿Cómo suena?'s four axes starts — the middle.
TONE_DEFAULT = 50


class CreativeState(rx.State):
    """State for /brand, /brand/voice, /create, /drafts and /drafts/[draft_id]."""

    # -- shared -------------------------------------------------------------
    readiness: ReadinessVM | None = None
    _brand_id: str = ""

    # -- /brand -------------------------------------------------------------
    kit_loading: bool = False
    kit_error: str = ""
    kit_notice: str = ""
    #: Draft vs. finalized (request 2026-09-08): the `brand_kits` row `load_brand`
    #: reads and `save_kit_form` writes is the ONE finalized copy — there is
    #: deliberately no separate "draft" table/column. The draft is just these `kit_*`
    #: fields living in THIS session's state, same as any other Reflex state; the only
    #: thing that made it feel otherwise was `load_brand` re-fetching and overwriting
    #: them on every `/brand/manual` `on_load`, which fires on more than a fresh visit
    #: — a refresh, "Atrás" back out and in, or navigating to another screen and back
    #: all re-run it too, silently discarding whatever the operator had just typed.
    #: `_kit_draft_loaded` (backend-only — leading underscore, never serializes to the
    #: client, same convention as `_brand_id`) makes the fetch-and-apply run exactly
    #: ONCE per session: `load_brand` only calls `_apply_kit_form` while this is
    #: False, then flips it. Every later `on_load` this session is a no-op on the kit
    #: fields — the in-session draft is now the source of truth until either a save
    #: (which does not need to re-read what it just wrote) or `AuthState.logout`
    #: (`.reset()`s this whole state, this flag included, so the NEXT session reads
    #: fresh from the database instead of a stale in-memory draft).
    _kit_draft_loaded: bool = False
    kit_positioning: str = ""
    kit_audience: str = ""
    kit_regional_variant: str = "es-CO"
    tone_formal_casual: int = TONE_DEFAULT
    tone_sober_enthusiastic: int = TONE_DEFAULT
    tone_technical_plain: int = TONE_DEFAULT
    tone_brief_elaborate: int = TONE_DEFAULT
    #: The kit as loaded already has a tone of its own — an axis moved off the default
    #: (§ request 2026-10-05: "si se cambian los sliders, que ya se marque como
    #: configurado", a cloned voice is not required). Read when the kit loads, not live,
    #: so moving a slider does not whisk away the screen being edited.
    tone_saved_custom: bool = False
    kit_do_examples: str = ""
    kit_dont_examples: str = ""
    kit_banned_words: str = ""
    kit_forbidden_claims: str = ""
    kit_cta_patterns: str = ""
    kit_palette: str = ""
    #: The brand's type faces by family name (§ request 2026-10-05, Tu brandboard's
    #: typography tiles): headlines and body copy. The optional font FILES are
    #: `BrandWizardState.font_files` — brandboard assets, not kit fields.
    kit_font_heading: str = ""
    kit_font_body: str = ""
    #: What each list's pill input holds before Enter (`_KIT_PILL_FIELDS` keys). The
    #: lists themselves stay the newline-joined `kit_*` strings above.
    #: The whole Brand Kit is being saved (`brand_finish.save_brand_kit`).
    kit_saving: bool = False
    kit_pill_drafts: dict[str, str] = {key: "" for key in ("do", "dont", "cta", "banned", "claims")}
    #: The one pill being edited in place on ¿Todo correcto? (§ request 2026-09-30):
    #: its list (`_KIT_PILL_FIELDS` key, "" = none), its index and the text so far.
    kit_pill_edit_field: str = ""
    kit_pill_edit_index: int = -1
    kit_pill_edit_value: str = ""
    #: The list whose "+" was pressed, so its input is open (`_KIT_PILL_FIELDS` key, ""
    #: = none) — no input until then, like Tu rubro's hashtags (§ request 2026-10-06).
    kit_pill_adding: str = ""

    # -- /brand/voice -------------------------------------------------------
    voice_loading: bool = False
    voice_error: str = ""
    voice_proposal: VoiceProposalVM | None = None
    voice_active: VoiceProposalVM | None = None

    # -- /create ------------------------------------------------------------
    create_loading: bool = False
    create_error: str = ""
    #: The Brand Kit's Tu voz y tono is still to configure (`brand_finish.
    #: kit_voice_configured`): the generator flags it and sends there (§ request
    #: 2026-10-06). Read on load; a failed read never flags.
    kit_voice_missing: bool = False
    brief_objective: str = "consideration"
    brief_content_type: str = "product"
    brief_topic: str = ""
    brief_product_ref: str = ""
    brief_intent: str = "organic"
    brief_must_mention: str = ""
    brief_must_avoid: str = ""
    route_options: list[RouteOptionVM] = []
    selected_route: str = "from_upload"
    staged_media_key: str = ""
    staged_media_name: str = ""
    upload_error: str = ""
    is_submitting: bool = False
    # The content kind and its inputs (§ request 2026-09-25, `ContentKind`/`MediaInputs`).
    #: Imagen publicitaria left the picker on 2026-10-06: the guion opens the wizard.
    brief_kind: str = "creator_script"
    media_background_key: str = ""
    media_background_name: str = ""
    media_product_keys: list[str] = []
    media_product_names: list[str] = []
    #: The Brand Kit's images (`creative_provider.brand_media`): `{key, label, view,
    #: kind, usage}` — «Recursos de tu marca», a section of its own apart from the
    #: background and the products (§ request 2026-10-06). Read on load; only a key in
    #: this list is ever accepted from the picker.
    brand_media_items: list[dict[str, str]] = []
    #: The piece's chosen resources: one logo (the brand mark's place) and the elements
    #: it uses as each one's usage note says (`MediaInputs.brand_logo_key` / `…_keys`).
    brand_logo_key: str = ""
    brand_element_keys: list[str] = []
    media_carousel: bool = False
    #: The carousel kind (§ request 2026-10-09): its slides in order, as editor rows —
    #: `{source, scene, photo_key, photo_name, background, text, seconds, key, label,
    #: view, media_type}` (`_new_slide`) — and whether a closing CTA slide ends it.
    carousel_slides: list[dict[str, str]] = _default_slides()
    carousel_closing: bool = True
    #: The strip of thumbnails (§ 2026-10-09, option A): the slide being edited below
    #: it, and whether «+» is showing the three kinds of slide to add.
    carousel_selected: int = 0
    carousel_adding: bool = False
    #: The brand's pieces' files (`creative_provider.brand_pieces`), read when «De una
    #: pieza» is first opened: `{key, media_type, label, view}`. Only a key in this list
    #: is accepted, and the producer checks it again against the brand's drafts.
    piece_items: list[dict[str, str]] = []
    piece_picker_open: bool = False
    pieces_loading: bool = False
    media_duration: str = "30"
    #: The advertising image: built from the product, the background or both
    #: (`AdImageMode`), and the scene the image model will be asked for.
    ad_mode: str = "both"
    ad_scene_prompt: str = ""
    avatar_look_id: str = ""
    voice_id: str = ""
    avatar_source: str = "ai"
    avatar_prompt: str = ""
    avatar_image_key: str = ""
    avatar_image_name: str = ""
    avatar_rights_confirmed: bool = False
    #: The human presenter: a woman or a man from HeyGen's library, or "custom" — a
    #: synthetic photoreal person generated from `human_avatar_prompt`.
    human_avatar_mode: str = "female"
    human_avatar_prompt: str = ""
    #: Which voices the voice picker lists. Follows the library gender on its own; for a
    #: custom or animated presenter the operator picks it.
    voice_gender: str = "female"
    #: HeyGen's library looks `{id, name, preview, gender}` and Spanish voices
    #: `{id, name, gender}`, read once when an avatar kind is first chosen.
    heygen_looks: list[dict[str, str]] = []
    heygen_voices: list[dict[str, str]] = []
    heygen_loading: bool = False
    heygen_error: str = ""
    #: The operator's own script for a video (instead of Claude's), and the engine.
    own_script_on: bool = False
    own_script: str = ""
    avatar_engine: str = "avatar_iv"
    #: Which vendor renders the avatar kinds ("seedance" | "heygen",
    #: `QUALIFY_VIDEO_ENGINE`), read when an avatar kind is chosen. With Seedance there is
    #: no library look, no voice and no HeyGen engine to pick.
    video_engine: str = "seedance"
    #: The format picked for the kind ("" = the kind's default, `ContentKind.formats`).
    brief_format: str = ""
    # -- the template kind (plan-mvp-plantillas-remotion.md): the catalog product the
    # piece is about
    catalog_items: list[dict[str, str]] = []
    catalog_loading: bool = False
    catalog_error: str = ""
    selected_product_id: str = ""
    selected_product_photo_key: str = ""
    _selected_product_photo_keys: list[str] = []
    #: «¿Qué quieres crear?» (§ request 2026-10-06): the category — "script" | "video" |
    #: "template" — and, within Video, the type: an avatar kind or "ad_video" (the
    #: template's Reel). `brief_kind` stays the real `ContentKind`.
    gen_category: str = "script"
    #: "result" once Generar created a piece: it shows below the form, on the same page
    #: (§ request 2026-10-08); "form" = nothing generated yet, or «Crear otro».
    generator_view: str = "form"
    #: «Reglas (opcional)» is folded until the operator opens it.
    rules_open: bool = False
    #: The carousel slide in view (§ request 2026-10-08): the generator's result, and
    #: the draft screen's.
    gen_slide: int = 0
    draft_slide: int = 0
    gen_draft_id: str = ""
    gen_draft: DraftVM | None = None
    #: Which variant the result view shows (index into `gen_draft.variants`).
    gen_variant: int = 0
    gen_timed_out: bool = False

    # -- /drafts ------------------------------------------------------------
    drafts: list[DraftSummaryVM] = []
    drafts_loading: bool = False
    drafts_error: str = ""

    # -- /drafts/[draft_id] -------------------------------------------------
    draft: DraftVM | None = None
    detail_loading: bool = False
    detail_error: str = ""
    selected_variant_id: str = ""
    edit_hook: str = ""
    edit_caption: str = ""
    edit_hashtags: str = ""
    edit_cta: str = ""
    edit_script: str = ""
    edit_blocking: list[str] = []
    edit_saving: bool = False
    # The copy fields are read-only until the operator presses "Editar"; "Cancelar" puts
    # the saved copy back. Approving is not offered over unsaved edits.
    edit_mode: bool = False
    # Hashtags the brand's catalog associates with the caption's words (read when the
    # editor opens and when the caption loses focus), and the free-form tag being typed.
    edit_catalog_tags: list[str] = []
    edit_hashtag_query: str = ""
    # «Sugerir con IA»: Claude reads the WHOLE caption and proposes a mix of popular,
    # niche and local/brand hashtags, grounded in the catalog (`hashtags.caption`).
    ai_hashtags: list[HashtagIdeaVM] = []
    ai_hashtags_loading: bool = False
    ai_hashtags_note: str = ""
    # The CTA field holds several calls to action (`cta_list`); this is the one typed.
    edit_cta_query: str = ""
    # The review decision asks before discarding: "reject" / "regenerate" while the
    # confirmation is open, "" otherwise — a mis-click must not throw a draft away.
    reject_confirm: str = ""
    action_error: str = ""
    poll_timed_out: bool = False
    poll_elapsed_label: str = ""
    _polling_draft_id: str = ""

    # -- computed -----------------------------------------------------------

    @rx.var
    def content_type_choices(self) -> list[list[str]]:
        return [[opt.value, opt.label] for opt in content_type_options()]

    @rx.var
    def selected_variant(self) -> CopyVariantVM | None:
        if self.draft is None:
            return None
        for variant in self.draft.variants:
            if variant.variant_id == self.selected_variant_id:
                return variant
        return None

    # -- the review editor's helpers -------------------------------------------------

    @rx.var
    def caption_blocking(self) -> list[str]:
        """The brand rules the caption breaks — shown under the caption itself."""
        return [m for m in self.edit_blocking if "caption" in m.lower()]

    @rx.var
    def other_blocking(self) -> list[str]:
        return [m for m in self.edit_blocking if "caption" not in m.lower()]

    @rx.var
    def edit_hashtag_chips(self) -> list[str]:
        return hashtag_list(self.edit_hashtags)

    @rx.var
    def hashtag_suggestions(self) -> list[str]:
        """Suggested from what the caption says (catalog matches first)."""
        return caption_hashtag_suggestions(
            self.edit_caption, self.edit_hashtags, extra=self.edit_catalog_tags
        )

    @rx.var
    def hook_count_label(self) -> str:
        return f"{len(self.edit_hook)}/{HOOK_LIMIT}"

    @rx.var
    def caption_count_label(self) -> str:
        return f"{len(self.edit_caption)}/{CAPTION_LIMIT}"

    @rx.var
    def hashtag_count_label(self) -> str:
        return f"{len(hashtag_list(self.edit_hashtags))}/{HASHTAG_LIMIT}"

    @rx.var
    def cta_chips(self) -> list[str]:
        return cta_list(self.edit_cta)

    @rx.var
    def cta_suggestions(self) -> list[str]:
        chosen = set(cta_list(self.edit_cta))
        return [c for c in CTA_SUGGESTIONS if c not in chosen]

    @rx.event
    def add_cta(self, text: str) -> None:
        items = cta_list(self.edit_cta)
        for item in cta_list(text):
            if item not in items:
                items.append(item)
        self.edit_cta = format_ctas(items)

    @rx.event
    def remove_cta(self, text: str) -> None:
        self.edit_cta = format_ctas([c for c in cta_list(self.edit_cta) if c != text])

    @rx.event
    def set_edit_cta_query(self, value: str) -> None:
        self.edit_cta_query = value

    @rx.event
    def add_typed_cta(self) -> None:
        self.add_cta(self.edit_cta_query)
        self.edit_cta_query = ""

    def _ai_ideas(self, kind: str) -> list[HashtagIdeaVM]:
        chosen = set(hashtag_list(self.edit_hashtags))
        return [h for h in self.ai_hashtags if h.kind == kind and h.tag not in chosen]

    @rx.var
    def ai_popular(self) -> list[HashtagIdeaVM]:
        return self._ai_ideas("popular")

    @rx.var
    def ai_niche(self) -> list[HashtagIdeaVM]:
        return self._ai_ideas("nicho")

    @rx.var
    def ai_brand(self) -> list[HashtagIdeaVM]:
        return self._ai_ideas("marca")

    @rx.var
    def ai_pending_count(self) -> int:
        chosen = set(hashtag_list(self.edit_hashtags))
        return sum(1 for h in self.ai_hashtags if h.tag not in chosen)

    @rx.event
    def add_all_ai_hashtags(self) -> None:
        self.add_hashtag(" ".join(h.tag for h in self.ai_hashtags))

    @rx.event(background=True)
    async def suggest_hashtags_ai(self):
        """«Sugerir con IA»: the whole caption to Claude, with the catalog's real tags for
        its words (and how often they were seen) as grounding."""
        async with self:
            if self.ai_hashtags_loading:
                return
            caption, current = self.edit_caption, hashtag_list(self.edit_hashtags)
            if not caption.strip():
                self.ai_hashtags_note = "Escribe primero el texto de la publicación."
                return
            self.ai_hashtags_loading = True
            self.ai_hashtags_note = ""
        ids = await self._session_ids()
        api_key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            async with self:
                self.ai_hashtags_loading = False
                self.ai_hashtags_note = "Las sugerencias con IA no están disponibles ahora mismo."
            return

        def run() -> list[HashtagIdeaVM]:
            from qualify_api.hashtags.caption import SeenTag, suggest_for_caption

            seen: list[SeenTag] = []
            if ids is not None:
                try:
                    from . import hashtag_catalog

                    for term in caption_keywords(caption, limit=8):
                        for hit in hashtag_catalog.REPOSITORY.resolve(
                            ids[0], term, limit=4, min_similarity=0.5
                        ):
                            if all(s.tag != hit.hashtag.tag for s in seen):
                                seen.append(SeenTag(hit.hashtag.tag, hit.hashtag.seen_count))
                except Exception as exc:  # noqa: BLE001 — grounding is optional
                    logger.info("caption hashtags: catalog skipped (%s)", type(exc).__name__)
            picks = suggest_for_caption(caption, seen=seen, current=current, api_key=api_key)
            return [
                HashtagIdeaVM(
                    tag=p.tag, kind=p.kind, reason=p.reason, seen_label=seen_label(p.seen_count)
                )
                for p in picks
            ]

        try:
            ideas = await asyncio.to_thread(run)
        except Exception as exc:  # noqa: BLE001 — the editor keeps working without it
            logger.warning("caption hashtags failed: %s", type(exc).__name__)
            async with self:
                self.ai_hashtags_loading = False
                self.ai_hashtags_note = (
                    "No se pudieron generar sugerencias ahora. Inténtalo de nuevo."
                )
            return
        async with self:
            self.ai_hashtags = ideas
            self.ai_hashtags_loading = False
            self.ai_hashtags_note = "" if ideas else "No hubo sugerencias nuevas para este texto."

    @rx.event
    def add_hashtag(self, tag: str) -> None:
        tags = hashtag_list(self.edit_hashtags)
        for new in hashtag_list(tag):
            if new not in tags and len(tags) < HASHTAG_LIMIT:
                tags.append(new)
        self.edit_hashtags = format_hashtags(tags)

    @rx.event
    def remove_hashtag(self, tag: str) -> None:
        self.edit_hashtags = format_hashtags(
            [t for t in hashtag_list(self.edit_hashtags) if t != tag]
        )

    @rx.event
    def set_edit_hashtag_query(self, value: str) -> None:
        self.edit_hashtag_query = value

    @rx.event
    def add_typed_hashtag(self) -> None:
        self.add_hashtag(self.edit_hashtag_query)
        self.edit_hashtag_query = ""

    @rx.event(background=True)
    async def load_catalog_hashtags(self) -> None:
        """Ask the brand's hashtag catalog what people tag the caption's words with — real
        tags first among the suggestions. Best effort: no catalog, no answer, no error."""
        async with self:
            terms = caption_keywords(self.edit_caption)
        if not terms:
            return
        ids = await self._session_ids()
        if ids is None:
            return
        tenant_id = ids[0]

        def lookup() -> list[str]:
            from . import hashtag_catalog  # the catalog pulls in discovery; load it late

            found: list[str] = []
            for term in terms:
                for hit in hashtag_catalog.REPOSITORY.resolve(
                    tenant_id, term, limit=2, min_similarity=0.55
                ):
                    if hit.hashtag.tag not in found:
                        found.append(hit.hashtag.tag)
            return found[:6]

        try:
            tags = await asyncio.to_thread(lookup)
        except Exception as exc:  # noqa: BLE001 — suggestions never break the editor
            logger.info("hashtag catalog lookup skipped: %s", type(exc).__name__)
            return
        async with self:
            self.edit_catalog_tags = tags

    @rx.var
    def can_approve_now(self) -> bool:
        """§6.5: approve needs a GENERATED draft, a selected variant that passes layer
        1, and no blocking edit failure on screen."""
        variant = self.selected_variant
        return (
            self.draft is not None
            and self.draft.can_approve
            and variant is not None
            and variant.passed
            and not self.edit_blocking
            and not self.edit_mode
        )

    @rx.var
    def kind_is_video(self) -> bool:
        return self.brief_kind in ("avatar_video", "animated_avatar_video")

    @rx.var
    def kind_is_flyer(self) -> bool:
        return self.brief_kind == "static_flyer"

    @rx.var
    def kind_takes_images(self) -> bool:
        """Background and product images: every kind but the creator's script."""
        return self.brief_kind in (
            "avatar_video",
            "animated_avatar_video",
            "static_flyer",
            "carousel",
        )

    # -- the carousel's slides (§ request 2026-10-09) -----------------------------------
    #
    # A strip of thumbnails, Instagram's order (option A, chosen 2026-10-09): «+» offers
    # the three kinds of slide, a thumbnail opens its slide in the editor below.

    @rx.var
    def carousel_slide_count(self) -> int:
        """Slides the carousel will have, the closing one included."""
        return len(self.carousel_slides) + int(self.carousel_closing)

    @rx.var
    def carousel_full(self) -> bool:
        return self.carousel_slide_count >= _CAROUSEL_MAX

    @rx.var
    def carousel_slide_rows(self) -> list[dict[str, str]]:
        """The strip's thumbnails: each row with its 1-based number, whether it is the one
        being edited and what its text label says."""
        selected = self._carousel_index()
        rows: list[dict[str, str]] = []
        for index, slide in enumerate(self.carousel_slides):
            row = dict(slide)
            row["n"] = str(index + 1)
            row["selected"] = "1" if index == selected else ""
            row["text_label"] = {"hook": "Título", "cta": "Botón"}.get(slide.get("text", ""), "")
            rows.append(row)
        return rows

    @rx.var
    def carousel_current(self) -> dict[str, str]:
        """The slide open in the editor below the strip ({} with no slides)."""
        index = self._carousel_index()
        if index < 0:
            return {}
        row = dict(self.carousel_slides[index])
        row["n"] = str(index + 1)
        row["first"] = "1" if index == 0 else ""
        row["last"] = "1" if index == len(self.carousel_slides) - 1 else ""
        return row

    def _carousel_index(self) -> int:
        if not self.carousel_slides:
            return -1
        return max(0, min(self.carousel_selected, len(self.carousel_slides) - 1))

    def _replace_slide(self, index: int, **fields: str) -> None:
        slides = [dict(slide) for slide in self.carousel_slides]
        slides[index].update(fields)
        self.carousel_slides = slides

    @rx.event
    def select_carousel_slide(self, index: int) -> None:
        if 0 <= int(index) < len(self.carousel_slides):
            self.carousel_selected = int(index)
            self.carousel_adding = False
            self.piece_picker_open = False

    @rx.event
    def toggle_carousel_adding(self) -> None:
        self.carousel_adding = not self.carousel_adding and not self.carousel_full
        self.piece_picker_open = False

    @rx.event
    def add_carousel_slide(self, source: str) -> None:
        """A new slide at the end of the strip, open in the editor."""
        if source not in _SLIDE_SOURCES or self.carousel_full:
            return
        self.carousel_slides = [*self.carousel_slides, _new_slide(source)]
        self.carousel_selected = len(self.carousel_slides) - 1
        self.carousel_adding = False

    @rx.event
    def remove_carousel_slide(self, index: int) -> None:
        slides = list(self.carousel_slides)
        index = int(index)
        if 0 <= index < len(slides):
            slides.pop(index)
            self.carousel_slides = slides
            self.carousel_selected = max(0, min(self.carousel_selected, len(slides) - 1))

    @rx.event
    def move_carousel_slide(self, index: int, delta: int) -> None:
        """Swap a slide with its neighbour; the editor follows it."""
        slides = list(self.carousel_slides)
        index, target = int(index), int(index) + int(delta)
        if 0 <= index < len(slides) and 0 <= target < len(slides):
            slides[index], slides[target] = slides[target], slides[index]
            self.carousel_slides = slides
            self.carousel_selected = target

    @rx.event
    def set_slide_field(self, index: int, field: str, value: str) -> None:
        """One field of one slide, kept to the values `CarouselSlide` takes."""
        allowed = {
            "scene": None,
            "background": ("1", ""),
            "text": _SLIDE_TEXTS,
            "seconds": _SLIDE_SECONDS,
        }
        index = int(index)
        if field not in allowed or not 0 <= index < len(self.carousel_slides):
            return
        value = str(value)
        if field == "scene":
            value = value[:600]
        elif value not in allowed[field]:  # type: ignore[operator]
            return
        if self.carousel_slides[index]["source"] == "existing":
            return  # a reused piece goes as it is
        self._replace_slide(index, **{field: value})

    @rx.event
    def toggle_slide_background(self, index: int) -> None:
        index = int(index)
        if 0 <= index < len(self.carousel_slides):
            current = self.carousel_slides[index].get("background", "1")
            self.set_slide_field(index, "background", "" if current else "1")

    @rx.event
    async def handle_slide_photo_upload(self, files: list[rx.UploadFile]) -> None:
        """The product photo of the slide open in the editor (§ 2026-10-09: uploaded in
        the slide itself). One photo per slide; a new one replaces it."""
        index = self._carousel_index()
        if index < 0 or self.carousel_slides[index]["source"] == "existing":
            return
        saved = await self._save_uploads(files[:1])
        if saved:
            key, name = saved[0]
            self._replace_slide(index, photo_key=key, photo_name=name)

    @rx.event
    def clear_slide_photo(self) -> None:
        index = self._carousel_index()
        if index >= 0:
            self._replace_slide(index, photo_key="", photo_name="")

    @rx.event
    def set_carousel_closing(self, value: bool) -> None:
        if value and len(self.carousel_slides) >= _CAROUSEL_MAX:
            return
        self.carousel_closing = bool(value)

    @rx.event
    def toggle_piece_picker(self) -> rx.event.EventSpec | None:
        self.piece_picker_open = not self.piece_picker_open
        if self.piece_picker_open and not self.piece_items and not self.pieces_loading:
            return CreativeState.load_brand_pieces
        return None

    @rx.event(background=True)
    async def load_brand_pieces(self) -> None:
        """«De una pieza»: the images and videos of the brand's own drafts. A list that
        cannot be read leaves the picker empty, never the carousel blocked."""
        async with self:
            self.pieces_loading = True
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.pieces_loading = False
            return
        tenant_id, brand_id, _ = ids
        try:
            items = list(await asyncio.to_thread(brand_pieces, tenant_id, brand_id))
        except Exception as exc:  # noqa: BLE001 — the other slides still work
            logger.warning("brand pieces unreadable: %s", type(exc).__name__)
            items = []
        async with self:
            self.piece_items = items
            self.pieces_loading = False

    @rx.event
    def pick_piece(self, key: str) -> None:
        """A file of one of the brand's pieces as the next slide, open in the editor."""
        if self.carousel_full:
            return
        item = next((item for item in self.piece_items if item.get("key") == key), None)
        if item is None:
            return
        slide = _new_slide("generated")
        slide.update(
            source="existing",
            key=item["key"],
            label=item.get("label", ""),
            view=item.get("view", ""),
            media_type=item.get("media_type", "image"),
        )
        self.carousel_slides = [*self.carousel_slides, slide]
        self.carousel_selected = len(self.carousel_slides) - 1
        self.piece_picker_open = False
        self.carousel_adding = False

    def _carousel_slides_payload(self, background: bool) -> tuple[list[str], list[dict]]:
        """The editor rows as `CarouselSlide` fields, and the product photos they point
        at (`MediaInputs.product_keys`, each slide's own, deduplicated in order)."""
        photos: list[str] = []
        out: list[dict] = []
        for slide in self.carousel_slides:
            if slide["source"] == "existing":
                out.append({"source": "existing", "object_key": slide["key"]})
                continue
            photo = slide.get("photo_key", "")
            if photo and photo not in photos:
                photos.append(photo)
            out.append(
                {
                    "source": slide["source"],
                    "scene_prompt": slide.get("scene", "").strip(),
                    "product_index": photos.index(photo) if photo else None,
                    "use_background": background and bool(slide.get("background")),
                    "text": slide.get("text", "none"),
                    "seconds": int(slide.get("seconds", "5")),
                }
            )
        return photos, out

    @rx.var
    def format_options(self) -> list[list[str]]:
        """[value, label] of the formats the chosen kind offers, its default first."""
        try:
            kind = ContentKind(self.brief_kind)
        except ValueError:
            return []
        formats = (
            _TEMPLATE_FORMATS["video" if self.gen_category == "video" else "template"]
            if kind is ContentKind.TEMPLATE
            else kind.formats
        )
        return [[fmt.value, _FORMAT_LABELS[fmt.value]] for fmt in formats]

    @rx.var
    def effective_format(self) -> str:
        options = [value for value, _ in self.format_options]
        if self.brief_format in options:
            return self.brief_format
        return options[0] if options else "feed_4_5"

    @rx.var
    def effective_format_label(self) -> str:
        return _FORMAT_LABELS.get(self.effective_format, "")

    @rx.var
    def gen_sections(self) -> list[str]:
        """The sections the chosen kind shows (`generator_sections`)."""
        return generator_sections(self.brief_kind)

    @rx.var
    def gen_section_numbers(self) -> dict[str, int]:
        """Each shown section's number, 1-based: they renumber as the kind changes."""
        return {key: n for n, key in enumerate(generator_sections(self.brief_kind), 1)}

    @rx.var
    def gen_generating(self) -> bool:
        """A piece is being created or is still generating: Generar waits for it."""
        if self.is_submitting:
            return True
        return (
            self.generator_view == "result"
            and not self.gen_timed_out
            and (self.gen_draft is None or self.gen_draft.is_drafting)
        )

    @rx.var
    def template_photo_count(self) -> int:
        """Photos the template would get: the piece's own uploads plus the chosen
        catalog product's, deduplicated."""
        return len(set(self.media_product_keys) | set(self._selected_product_photo_keys))

    @rx.var
    def carousel_allowed(self) -> bool:
        """The advertising image is one image (§ request 2026-10-09: "quitar la opción de
        carrusel en imágenes publicitarias") — a carousel is its own kind now. A flyer
        brief stored with `carousel` still regenerates as it was asked."""
        return False

    @rx.var
    def gen_is_drafting(self) -> bool:
        return self.gen_draft is None or self.gen_draft.is_drafting

    @rx.var
    def gen_is_failed(self) -> bool:
        return self.gen_draft is not None and self.gen_draft.is_failed

    @rx.var
    def gen_is_ready(self) -> bool:
        return (
            self.gen_draft is not None
            and not self.gen_draft.is_drafting
            and not self.gen_draft.is_failed
        )

    @rx.var
    def gen_is_done(self) -> bool:
        """The piece finished generating, well or not: until then «Revisar y aprobar» is
        held back (§ request 2026-10-06 — nothing moves on before the video is there)."""
        return self.gen_draft is not None and not self.gen_draft.is_drafting

    @rx.var
    def gen_is_carousel(self) -> bool:
        """More than one image: shown as a carousel, not one under the other."""
        return _is_carousel(self.gen_draft)

    @rx.var
    def draft_is_carousel(self) -> bool:
        return _is_carousel(self.draft)

    @rx.event
    def gen_slide_step(self, delta: int) -> None:
        self.gen_slide = _slide(self.gen_draft, self.gen_slide + delta)

    @rx.event
    def gen_slide_pick(self, index: int) -> None:
        self.gen_slide = _slide(self.gen_draft, index)

    @rx.event
    def draft_slide_step(self, delta: int) -> None:
        self.draft_slide = _slide(self.draft, self.draft_slide + delta)

    @rx.event
    def draft_slide_pick(self, index: int) -> None:
        self.draft_slide = _slide(self.draft, index)

    @rx.event
    def gen_slide_auto(self) -> None:
        """The carousel's own tick: the next slide, back to the first after the last."""
        self.gen_slide = _next_slide(self.gen_draft, self.gen_slide)

    @rx.event
    def draft_slide_auto(self) -> None:
        self.draft_slide = _next_slide(self.draft, self.draft_slide)

    @rx.var
    def gen_kind(self) -> str:
        return self.gen_draft.kind if self.gen_draft is not None else self.brief_kind

    @rx.var
    def gen_variant_vm(self) -> CopyVariantVM | None:
        if self.gen_draft is None or not self.gen_draft.variants:
            return None
        variants = self.gen_draft.variants
        return variants[min(self.gen_variant, len(variants) - 1)]

    @rx.var
    def gen_variant_labels(self) -> list[list[str]]:
        """[index, label] per variant, for the result view's switch."""
        if self.gen_draft is None:
            return []
        return [[str(i), f"Opción {i + 1}"] for i in range(len(self.gen_draft.variants))]

    @rx.var
    def gen_waiting_label(self) -> str:
        return _GEN_WAITING.get(self.gen_kind, "Generando…")

    @rx.var
    def video_on_seedance(self) -> bool:
        return self.video_engine == "seedance"

    @rx.var
    def gen_failure_label(self) -> str:
        """The precise reason when the media step gave one (HeyGen without credit…),
        else the failure code's translation."""
        if self.gen_draft is None:
            return ""
        if self.gen_draft.failure_detail:
            return self.gen_draft.failure_detail
        return self.gen_draft.failure.label if self.gen_draft.failure is not None else ""

    def _choices(self, kind: str | None) -> list[dict[str, str]]:
        elements = set(self.brand_element_keys)
        return [
            {
                **item,
                # "1" when the piece uses it: as its logo / an element / the character
                "chosen": (
                    "1"
                    if item.get("key") == self.brand_logo_key or item.get("key") in elements
                    else ""
                ),
                "avatar": "1" if item.get("key") == self.avatar_image_key else "",
            }
            for item in self.brand_media_items
            if kind is None or item.get("kind") == kind
        ]

    @rx.var
    def brand_logo_choices(self) -> list[dict[str, str]]:
        """«Recursos de tu marca» → the logos (one can be chosen)."""
        return self._choices("logo")

    @rx.var
    def brand_element_choices(self) -> list[dict[str, str]]:
        """«Recursos de tu marca» → the other elements, each with its usage note."""
        return self._choices("element")

    @rx.var
    def brand_media_choices(self) -> list[dict[str, str]]:
        """Every Brand Kit image, for the animated character's «O elige del Brand Kit»."""
        return self._choices(None)

    @rx.var
    def product_items(self) -> list[dict[str, str]]:
        return [
            {"key": key, "name": name}
            for key, name in zip(self.media_product_keys, self.media_product_names, strict=False)
        ]

    @rx.var
    def visible_looks(self) -> list[dict[str, str]]:
        """The library looks of the chosen gender (none for a custom presenter)."""
        return [look for look in self.heygen_looks if look.get("gender") == self.human_avatar_mode]

    # One fixed list per gender, each rendered by its own always-mounted grid: switching
    # Mujer/Hombre then only shows/hides a grid. A single grid over `visible_looks` made
    # React recycle the `<img>` nodes by position, so the old gender's photos lingered
    # (mixed with the new ones) until each new `src` loaded.
    @rx.var
    def female_looks(self) -> list[dict[str, str]]:
        return [look for look in self.heygen_looks if look.get("gender") == "female"]

    @rx.var
    def male_looks(self) -> list[dict[str, str]]:
        return [look for look in self.heygen_looks if look.get("gender") == "male"]

    @rx.var
    def visible_voices(self) -> list[dict[str, str]]:
        """The listed gender's voices — plus the brand's own clone, always."""
        return [
            voice
            for voice in self.heygen_voices
            if voice.get("own") == "1" or voice.get("gender") == self.voice_gender
        ]

    @rx.var
    def selected_look_name(self) -> str:
        for look in self.heygen_looks:
            if look.get("id") == self.avatar_look_id:
                return look.get("name", "")
        return ""

    @rx.var
    def selected_needs_upload(self) -> bool:
        for option in self.route_options:
            if option.key == self.selected_route:
                return option.needs_upload
        return False

    @rx.var
    def palette_colors(self) -> list[str]:
        """Non-empty palette entries, in order — the render-side twin of the filtered
        `parts` every Brand Kit wizard palette handler (`commit_picked_color`,
        `set_swatch_color`, `remove_colour` in `creative_wizard_pages.py`) builds from
        this same string. Rendering `kit_palette.split(",")` directly (the previous
        approach) desyncs from that filtered index the moment the palette is empty or
        carries a stray comma — `"".split(",")` is `['']`, not `[]` — which put one
        phantom swatch on screen for a brand-new kit that no click could ever remove
        (`remove_colour` filters empty entries out of `parts` before indexing, so
        index 0 already pointed past the end of the real list)."""
        return [c.strip() for c in self.kit_palette.split(",") if c.strip()]

    @rx.var
    def has_palette_colors(self) -> bool:
        return bool(self.palette_colors)

    # -- helpers ------------------------------------------------------------

    async def _session_ids(self) -> tuple[UUID, UUID, UUID] | None:
        """(tenant, brand, acting user) for the current session, or None (with the
        reason already stored) when any of the three cannot be resolved."""
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = brand_tenant_id(auth)
            cached_brand_id = self._brand_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            return None
        brand_id: UUID | None
        if cached_brand_id:
            brand_id = UUID(cached_brand_id)
        else:
            brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
            if brand_id is not None:
                async with self:
                    self._brand_id = str(brand_id)
        if brand_id is None:
            return None
        user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        if user_id is None:
            return None
        return tenant_id, brand_id, user_id

    def _apply_kit_form(self, form: KitFormVM) -> None:
        self.kit_positioning = form.positioning
        self.kit_audience = form.audience
        self.kit_regional_variant = form.regional_variant
        self.tone_formal_casual = form.tone_formal_casual
        self.tone_sober_enthusiastic = form.tone_sober_enthusiastic
        self.tone_technical_plain = form.tone_technical_plain
        self.tone_brief_elaborate = form.tone_brief_elaborate
        self.kit_do_examples = form.do_examples
        self.kit_dont_examples = form.dont_examples
        self.kit_banned_words = form.banned_words
        self.kit_forbidden_claims = form.forbidden_claims
        self.kit_cta_patterns = form.cta_patterns
        self.kit_palette = form.palette_rgb
        self.kit_font_heading = form.font_heading
        self.kit_font_body = form.font_body

    def tone_is_custom(self) -> bool:
        """Any of the four axes moved off `TONE_DEFAULT`."""
        return any(
            value != TONE_DEFAULT
            for value in (
                self.tone_formal_casual,
                self.tone_sober_enthusiastic,
                self.tone_technical_plain,
                self.tone_brief_elaborate,
            )
        )

    def _kit_form(self) -> KitFormVM:
        return KitFormVM(
            positioning=self.kit_positioning,
            audience=self.kit_audience,
            regional_variant=self.kit_regional_variant,
            tone_formal_casual=self.tone_formal_casual,
            tone_sober_enthusiastic=self.tone_sober_enthusiastic,
            tone_technical_plain=self.tone_technical_plain,
            tone_brief_elaborate=self.tone_brief_elaborate,
            do_examples=self.kit_do_examples,
            dont_examples=self.kit_dont_examples,
            banned_words=self.kit_banned_words,
            forbidden_claims=self.kit_forbidden_claims,
            cta_patterns=self.kit_cta_patterns,
            palette_rgb=self.kit_palette,
            font_heading=self.kit_font_heading,
            font_body=self.kit_font_body,
        )

    # -- explicit setters (this Reflex version generates none) ----------------

    @rx.event
    def set_kit_positioning(self, value: str) -> None:
        self.kit_positioning = value

    @rx.event
    def set_kit_audience(self, value: str) -> None:
        self.kit_audience = value

    @rx.event
    def set_kit_regional_variant(self, value: str) -> None:
        self.kit_regional_variant = value

    @rx.event
    def set_kit_do_examples(self, value: str) -> None:
        self.kit_do_examples = value

    @rx.event
    def set_kit_dont_examples(self, value: str) -> None:
        self.kit_dont_examples = value

    @rx.event
    def set_kit_banned_words(self, value: str) -> None:
        self.kit_banned_words = value

    @rx.event
    def set_kit_forbidden_claims(self, value: str) -> None:
        self.kit_forbidden_claims = value

    @rx.event
    def set_kit_cta_patterns(self, value: str) -> None:
        self.kit_cta_patterns = value

    @rx.event
    def set_kit_palette(self, value: str) -> None:
        self.kit_palette = value

    @rx.event
    def set_kit_font_heading(self, value: str) -> None:
        """The brand's ONE typography (§ request 2026-10-05, "solo haz una tipografía"):
        the body face follows it, so whatever reads `font_body` gets the same family."""
        self.kit_font_heading = value
        self.kit_font_body = value

    @rx.event
    def set_kit_font_body(self, value: str) -> None:
        self.kit_font_body = value

    # -- typography previews (Tu brandboard, § request 2026-10-05) ------------------
    # A typed family name is previewed through Google Fonts: the tile links the family's
    # stylesheet and sets it as `font-family`. A family not on Google Fonts just falls
    # back (the browser ignores a 400 stylesheet), so the preview is best-effort by
    # design — the uploaded file, when there is one, is what the tile really shows.

    @rx.var
    def kit_font_heading_family(self) -> str:
        return font_family_css(self.kit_font_heading)

    @rx.var
    def kit_font_body_family(self) -> str:
        return font_family_css(self.kit_font_body)

    @rx.var
    def kit_font_heading_css_url(self) -> str:
        return google_fonts_url(self.kit_font_heading)

    @rx.var
    def kit_font_body_css_url(self) -> str:
        return google_fonts_url(self.kit_font_body)

    @rx.var
    def kit_typography_summary(self) -> str:
        """¿Todo correcto?'s one-line recap: "Montserrat", or "Montserrat · Inter" for a kit
        saved with two faces before there was only one, or ""."""
        names: list[str] = []
        for name in (self.kit_font_heading.strip(), self.kit_font_body.strip()):
            if name and name not in names:
                names.append(name)
        return " · ".join(names)

    # -- the Brand Kit's list fields, as pills ----------------------------------
    # One computed var per list, each naming its own `kit_*` attr: a `getattr` with a
    # dynamic name inside an `@rx.var` registers no dependency and never recomputes.

    @rx.var
    def kit_do_items(self) -> list[str]:
        return _pill_items(self.kit_do_examples)

    @rx.var
    def kit_dont_items(self) -> list[str]:
        return _pill_items(self.kit_dont_examples)

    @rx.var
    def kit_cta_items(self) -> list[str]:
        return _pill_items(self.kit_cta_patterns)

    @rx.var
    def kit_banned_items(self) -> list[str]:
        return _pill_items(self.kit_banned_words)

    @rx.var
    def kit_claims_items(self) -> list[str]:
        return _pill_items(self.kit_forbidden_claims)

    @rx.event
    def set_kit_pill_draft(self, field: str, value: str) -> None:
        if field in _KIT_PILL_FIELDS:
            self.kit_pill_drafts = {**self.kit_pill_drafts, field: value}

    @rx.event
    def add_kit_pill(self, field: str) -> None:
        """Enter in a list's pill input: the typed value joins the list (a value already
        there, ignoring case, is not added twice) and the input closes back into "+"."""
        self._add_kit_pill(field)

    def _add_kit_pill(self, field: str) -> None:
        attr = _KIT_PILL_FIELDS.get(field)
        if attr is None:
            return
        value = " ".join(self.kit_pill_drafts.get(field, "").split())
        if value:
            items = _pill_items(getattr(self, attr))
            if value.casefold() not in {item.casefold() for item in items}:
                setattr(self, attr, "\n".join([*items, value]))
        self.kit_pill_drafts = {**self.kit_pill_drafts, field: ""}
        if self.kit_pill_adding == field:
            self.kit_pill_adding = ""

    @rx.event
    def open_kit_pill_input(self, field: str) -> None:
        """A list's "+": only now does its input appear (one list at a time)."""
        if field in _KIT_PILL_FIELDS:
            self._clear_kit_pill_edit()
            self.kit_pill_adding = field

    @rx.event
    def kit_pill_add_key(self, key: str) -> None:
        """Escape closes the open input and forgets what was typed."""
        if key == "Escape" and self.kit_pill_adding:
            self.kit_pill_drafts = {**self.kit_pill_drafts, self.kit_pill_adding: ""}
            self.kit_pill_adding = ""

    @rx.event
    def kit_pill_add_blur(self, value: str) -> None:
        """Leaving the input adds what was typed, like Enter; left empty, it just puts
        the "+" back (the same rule as Tu rubro's hashtags)."""
        field = self.kit_pill_adding
        if not field:
            return
        if not value.strip():
            self.kit_pill_drafts = {**self.kit_pill_drafts, field: ""}
            self.kit_pill_adding = ""
            return
        self.kit_pill_drafts = {**self.kit_pill_drafts, field: value}
        self._add_kit_pill(field)

    @rx.event
    def remove_kit_pill(self, field: str, index: int) -> None:
        attr = _KIT_PILL_FIELDS.get(field)
        if attr is None:
            return
        items = _pill_items(getattr(self, attr))
        if 0 <= index < len(items):
            del items[index]
            setattr(self, attr, "\n".join(items))
        # the indices behind any open edit just moved
        self._clear_kit_pill_edit()

    @rx.event
    def start_kit_pill_edit(self, field: str, index: int) -> None:
        """Click on a pill of ¿Todo correcto?: that value becomes an input, in place."""
        attr = _KIT_PILL_FIELDS.get(field)
        if attr is None:
            return
        items = _pill_items(getattr(self, attr))
        if 0 <= index < len(items):
            self.kit_pill_edit_field = field
            self.kit_pill_edit_index = index
            self.kit_pill_edit_value = items[index]

    @rx.event
    def set_kit_pill_edit_value(self, value: str) -> None:
        self.kit_pill_edit_value = value

    @rx.event
    def save_kit_pill_edit(self) -> None:
        """Enter or leaving the input: the edited text replaces the value. Emptied, the
        value goes; turned into one the list already has (ignoring case), the two merge."""
        attr = _KIT_PILL_FIELDS.get(self.kit_pill_edit_field)
        index = self.kit_pill_edit_index
        if attr is not None:
            items = _pill_items(getattr(self, attr))
            if 0 <= index < len(items):
                value = " ".join(self.kit_pill_edit_value.split())
                others = {item.casefold() for i, item in enumerate(items) if i != index}
                if not value or value.casefold() in others:
                    del items[index]
                else:
                    items[index] = value
                setattr(self, attr, "\n".join(items))
        self._clear_kit_pill_edit()

    @rx.event
    def cancel_kit_pill_edit(self) -> None:
        self._clear_kit_pill_edit()

    @rx.event
    def kit_pill_edit_key(self, key: str) -> None:
        """Escape leaves the value as it was."""
        if key == "Escape":
            self._clear_kit_pill_edit()

    def _clear_kit_pill_edit(self) -> None:
        self.kit_pill_edit_field = ""
        self.kit_pill_edit_index = -1
        self.kit_pill_edit_value = ""

    @rx.event
    def set_brief_topic(self, value: str) -> None:
        self.brief_topic = value

    @rx.event
    def set_brief_product_ref(self, value: str) -> None:
        self.brief_product_ref = value

    @rx.event
    def set_brief_must_mention(self, value: str) -> None:
        self.brief_must_mention = value

    @rx.event
    def set_brief_must_avoid(self, value: str) -> None:
        self.brief_must_avoid = value

    @rx.event
    def set_edit_hook(self, value: str) -> None:
        self.edit_hook = value

    @rx.event
    def set_edit_caption(self, value: str) -> None:
        self.edit_caption = value

    @rx.event
    def set_edit_hashtags(self, value: str) -> None:
        self.edit_hashtags = value

    @rx.event
    def set_edit_cta(self, value: str) -> None:
        self.edit_cta = value

    @rx.event
    def set_edit_script(self, value: str) -> None:
        self.edit_script = value

    # -- /brand -------------------------------------------------------------

    # Slider setters: the radix slider reports `list[int | float]`, so the
    # auto-generated scalar setters cannot receive it — these overrides unpack it.
    @rx.event
    def set_tone_formal_casual(self, value: list[int | float]) -> None:
        self.tone_formal_casual = int(value[0])

    @rx.event
    def set_tone_sober_enthusiastic(self, value: list[int | float]) -> None:
        self.tone_sober_enthusiastic = int(value[0])

    @rx.event
    def set_tone_technical_plain(self, value: list[int | float]) -> None:
        self.tone_technical_plain = int(value[0])

    @rx.event
    def set_tone_brief_elaborate(self, value: list[int | float]) -> None:
        self.tone_brief_elaborate = int(value[0])

    @rx.event(background=True)
    async def load_brand(self) -> None:
        """Runs on every `/brand/manual` and `/brand/connect` `on_load` — not just a
        fresh visit (see `_kit_draft_loaded`'s own comment on the field). `readiness`
        is refreshed every time regardless (it is a derived read, not draft data —
        cheap, and other screens editing the same brand should still be reflected);
        the kit FORM is only fetched and applied the first time this session, so nothing
        already typed into the draft this session is ever silently overwritten.

        Errors never set `_kit_draft_loaded`: a failed load must be retryable on the
        next `on_load` (e.g. re-entering the page), not permanently treated as "already
        loaded" with nothing actually in state.
        """
        async with self:
            self.kit_loading = True
            self.kit_error = ""
            self.kit_notice = ""
            already_loaded = self._kit_draft_loaded
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.kit_loading = False
                self.kit_error = _NO_SESSION if not self._brand_id else _NO_BRAND
            return
        tenant_id, brand_id, _ = ids
        try:
            verdict = await asyncio.to_thread(brand_readiness, tenant_id, brand_id)
            form = (
                None
                if already_loaded
                else await asyncio.to_thread(load_kit_form, tenant_id, brand_id)
            )
        except SQLAlchemyError as exc:
            logger.error("brand load failed: %s", type(exc).__name__)
            async with self:
                self.kit_loading = False
                self.kit_error = _DB_ERROR
            return
        async with self:
            self.readiness = verdict
            if not already_loaded:
                if form is not None:
                    self._apply_kit_form(form)
                self._kit_draft_loaded = True
            self.tone_saved_custom = self.tone_is_custom()
            self.kit_loading = False

    @rx.event(background=True)
    async def save_kit_form(self) -> None:
        async with self:
            self.kit_error = ""
            self.kit_notice = ""
            form = self._kit_form()
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.kit_error = _NO_SESSION
            return
        tenant_id, brand_id, user_id = ids
        try:
            await asyncio.to_thread(save_kit, tenant_id, brand_id, user_id, form)
            verdict = await asyncio.to_thread(brand_readiness, tenant_id, brand_id)
        except ValidationError as exc:
            first = exc.errors()[0]
            async with self:
                self.kit_error = _KIT_INVALID + str(first.get("msg", ""))
            return
        except SQLAlchemyError as exc:
            logger.error("kit save failed: %s", type(exc).__name__)
            async with self:
                self.kit_error = _DB_ERROR
            return
        async with self:
            self.readiness = verdict
            self.kit_notice = _KIT_SAVED

    # -- /brand/voice (HITL #0) ---------------------------------------------

    @rx.event(background=True)
    async def load_voice(self) -> None:
        async with self:
            self.voice_loading = True
            self.voice_error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.voice_loading = False
                self.voice_error = _NO_SESSION
            return
        tenant_id, brand_id, _ = ids
        try:
            verdict = await asyncio.to_thread(brand_readiness, tenant_id, brand_id)
            proposal, active = await asyncio.to_thread(load_voice_screen, tenant_id, brand_id)
        except SQLAlchemyError as exc:
            logger.error("voice load failed: %s", type(exc).__name__)
            async with self:
                self.voice_loading = False
                self.voice_error = _DB_ERROR
            return
        async with self:
            self.readiness = verdict
            self.voice_proposal = proposal
            self.voice_active = active
            self.voice_loading = False

    @rx.event(background=True)
    async def distill_voice(self) -> AsyncIterator[None]:
        """S1 'destilar': propose the next profile from the kit, then reload."""
        async with self:
            self.voice_error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.voice_error = _NO_SESSION
            return
        tenant_id, brand_id, user_id = ids
        try:
            await asyncio.to_thread(propose_voice, tenant_id, brand_id, user_id)
        except UnknownBrandKit:
            async with self:
                self.voice_error = _NO_KIT_TO_PROPOSE
            return
        except SQLAlchemyError as exc:
            logger.error("voice propose failed: %s", type(exc).__name__)
            async with self:
                self.voice_error = _DB_ERROR
            return
        yield CreativeState.load_voice

    @rx.event(background=True)
    async def approve_voice_version(self, version: int) -> AsyncIterator[None]:
        async with self:
            self.voice_error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.voice_error = _NO_SESSION
            return
        tenant_id, brand_id, user_id = ids
        try:
            await asyncio.to_thread(approve_voice, tenant_id, brand_id, int(version), user_id)
        except (UnknownVersion, NotProposed):
            async with self:
                self.voice_error = _STALE_PROPOSAL
            yield CreativeState.load_voice
            return
        except SQLAlchemyError as exc:
            logger.error("voice approve failed: %s", type(exc).__name__)
            async with self:
                self.voice_error = _DB_ERROR
            return
        yield CreativeState.load_voice

    # -- /create ------------------------------------------------------------

    @rx.event(background=True)
    async def load_create(self) -> None:
        async with self:
            self.create_loading = True
            self.create_error = ""
            self.upload_error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.create_loading = False
                self.create_error = _NO_SESSION
            return
        tenant_id, brand_id, _ = ids
        async with self:
            content_type = self.brief_content_type
        try:
            verdict = await asyncio.to_thread(brand_readiness, tenant_id, brand_id)
            options = await asyncio.to_thread(route_options_for, tenant_id, brand_id, content_type)
        except SQLAlchemyError as exc:
            logger.error("create load failed: %s", type(exc).__name__)
            async with self:
                self.create_loading = False
                self.create_error = _DB_ERROR
            return
        voice_missing = await self._kit_voice_missing(tenant_id, brand_id)
        try:
            assets = list(await asyncio.to_thread(brand_media, tenant_id, brand_id))
        except Exception as exc:  # the uploads still work: never a reason to block
            logger.warning("brand media unreadable: %s", type(exc).__name__)
            assets = []
        async with self:
            self.readiness = verdict
            self.route_options = list(options)
            self._select_default_route()
            self.kit_voice_missing = voice_missing
            self.brand_media_items = assets
            self.create_loading = False

    @staticmethod
    async def _kit_voice_missing(tenant_id: UUID, brand_id: UUID) -> bool:
        from .brand_finish import kit_voice_configured

        try:
            return not await asyncio.to_thread(kit_voice_configured, tenant_id, brand_id)
        except Exception as exc:  # a flag, never a reason to block the generator
            logger.warning("brand voice check failed: %s", type(exc).__name__)
            return False

    @rx.event
    def configure_voice(self) -> rx.event.EventSpec:
        """The flag's "Configurar voz": the Brand Kit editor opens on Tu voz y tono while
        it is still to configure (`brand_kit_editor.needs_voice`)."""
        return rx.redirect("/brand/kit")

    def _select_default_route(self) -> None:
        """Preset the accordion on the content type's default route (§6.4: the first
        submodule open by default), falling back to the first enabled one."""
        try:
            default = ContentType(self.brief_content_type).default_image_route.value
        except ValueError:
            default = "from_upload"
        enabled = {opt.key for opt in self.route_options if opt.enabled}
        if default in enabled:
            self.selected_route = default
        elif enabled:
            self.selected_route = next(opt.key for opt in self.route_options if opt.enabled)

    @rx.event
    def set_objective(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value in _OBJECTIVES:
            self.brief_objective = value

    @rx.event
    def set_intent(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value in _INTENTS:
            self.brief_intent = value

    @rx.event(background=True)
    async def set_content_type(self, value: str) -> None:
        """Content type presets the image route (ContentType.default_image_route) and
        re-derives the accordion (GENERATE defensibility depends on the type)."""
        async with self:
            self.brief_content_type = value
        ids = await self._session_ids()
        if ids is None:
            return
        tenant_id, brand_id, _ = ids
        try:
            options = await asyncio.to_thread(route_options_for, tenant_id, brand_id, value)
        except SQLAlchemyError as exc:
            logger.error("route options failed: %s", type(exc).__name__)
            return
        async with self:
            self.route_options = list(options)
            self._select_default_route()

    # -- the content kind and its inputs ------------------------------------------

    @rx.var
    def video_type(self) -> str:
        """Within Video, which type is chosen ("" outside Video)."""
        if self.gen_category != "video":
            return ""
        return "ad_video" if self.brief_kind == "template" else self.brief_kind

    @rx.var
    def gen_kind_label(self) -> str:
        """What the piece is called on «¿Todo listo?»: the video type within Video."""
        if self.gen_category == "video":
            return VIDEO_TYPE_LABELS.get(self.video_type, "")
        return KIND_LABELS.get(self.brief_kind, "")

    @rx.event
    def choose_category(self, category: str) -> rx.event.EventSpec | None:
        """Guion · Video · Con plantilla. Video opens on its first type unless one of its
        types is already chosen."""
        if category not in GEN_CATEGORIES:
            return None
        if category == self.gen_category and (
            category != "video" or self.video_type in VIDEO_TYPES
        ):
            return None
        self.gen_category = category
        return self._set_kind(_CATEGORY_KIND[category])

    @rx.event
    def choose_video_type(self, video_type: str) -> rx.event.EventSpec | None:
        """Avatar humano · Avatar animado · Video publicitario (the template's Reel)."""
        if video_type not in VIDEO_TYPES:
            return None
        self.gen_category = "video"
        return self._set_kind("template" if video_type == "ad_video" else video_type)

    @rx.event
    def choose_kind(self, key: str) -> rx.event.EventSpec | None:
        """One of the kinds, directly (the picker goes through `choose_category` /
        `choose_video_type`)."""
        return self._set_kind(key)

    def _set_kind(self, key: str) -> rx.event.EventSpec | None:
        """An avatar kind loads HeyGen's looks and voices the first time it is chosen;
        the template kind, the catalog."""
        if key not in _ENABLED_KINDS:
            return None
        self.brief_kind = key
        self.brief_format = ""  # each kind starts on its own default format
        self.create_error = ""
        if key != "static_flyer":
            self.media_carousel = False
        if key == "carousel" and not self.carousel_slides:
            self.carousel_slides = _default_slides()
            self.carousel_closing = True
        if key in ("avatar_video", "animated_avatar_video"):
            self.video_engine = configured_video_engine()
            if self.video_engine == "heygen" and not self.heygen_voices:
                return CreativeState.load_heygen_catalog
        if key == "template" and not self.catalog_items:
            return CreativeState.load_catalog_products
        return None

    # -- the template kind: the catalog product ---------------------------------------------

    @rx.event(background=True)
    async def load_catalog_products(self) -> None:
        """The picker of «¿Qué anuncias?» for the template kind: the brand's products,
        with their primary photo. A catalog that cannot be read does not block the
        step — the operator can still upload the photos by hand."""
        async with self:
            self.catalog_loading = True
            self.catalog_error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.catalog_loading = False
            return
        tenant_id, brand_id, _ = ids
        try:
            items = await asyncio.to_thread(catalog_products, tenant_id, brand_id)
        except SQLAlchemyError as exc:
            logger.error("catalog products failed: %s", type(exc).__name__)
            async with self:
                self.catalog_loading = False
                self.catalog_error = _CATALOG_ERROR
            return
        async with self:
            self.catalog_items = [dict(item) for item in items]
            self.catalog_loading = False

    @rx.event
    def choose_product(self, product_id: str) -> None:
        """Pick (or unpick) the catalog product the piece is about: the brief's
        `product_ref` becomes its name (what `DbProductCatalog` resolves), its photos
        ride along as the piece's product keys, and an empty topic takes the name."""
        if self.selected_product_id == product_id:
            self.clear_product()
            return
        item = next((i for i in self.catalog_items if i.get("id") == product_id), None)
        if item is None:
            return
        self.selected_product_id = product_id
        self.brief_product_ref = item.get("name", "")
        self.selected_product_photo_key = item.get("photo_key", "")
        self._selected_product_photo_keys = [
            key for key in item.get("photo_keys", "").split("\n") if key
        ]
        if not self.brief_topic.strip():
            self.brief_topic = item.get("name", "")
        self.create_error = ""

    @rx.event
    def clear_product(self) -> None:
        self.selected_product_id = ""
        self.selected_product_photo_key = ""
        self._selected_product_photo_keys = []
        self.brief_product_ref = ""

    @rx.event(background=True)
    async def load_heygen_catalog(self) -> None:
        async with self:
            if self.heygen_loading:
                return
            self.heygen_loading = True
            self.heygen_error = ""
        try:
            looks, voices = await asyncio.to_thread(heygen_catalog)
        except HeyGenNotConfigured:
            async with self:
                self.heygen_loading = False
                self.heygen_error = _HEYGEN_OFF
            return
        except Exception as exc:  # HeyGen's own errors, network
            logger.warning("heygen catalog failed: %s", exc)
            async with self:
                self.heygen_loading = False
                self.heygen_error = _HEYGEN_DOWN
            return
        # § 2026-09-30: the brand's own cloned voice (Tu voz, on ¿Cómo suena?) leads
        # the list — and so becomes the default — once HeyGen finished it.
        own = None
        ids = await self._session_ids()
        if ids is not None:
            try:
                own = await asyncio.to_thread(brand_clone_voice, ids[0], ids[1])
            except SQLAlchemyError as exc:
                logger.warning("brand voice clone unreadable: %s", type(exc).__name__)
        async with self:
            self.heygen_looks = looks
            self.heygen_voices = [own, *voices] if own else voices
            self._sync_voice()
            self.heygen_loading = False

    @rx.event
    def choose_look(self, look_id: str) -> None:
        self.avatar_look_id = look_id

    @rx.event
    def set_voice_id(self, value: str) -> None:
        self.voice_id = value

    @rx.event
    def set_human_avatar_mode(self, value: str | list[str]) -> None:
        """Mujer / Hombre / Personalizado. A library gender also switches the voices to
        that gender, and drops a look picked under the other one."""
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value not in (*_GENDERS, "custom"):
            return
        self.human_avatar_mode = value
        if value in _GENDERS:
            self.voice_gender = value
            genders = {look.get("id"): look.get("gender") for look in self.heygen_looks}
            if genders.get(self.avatar_look_id) != value:
                self.avatar_look_id = ""
        self._sync_voice()

    @rx.event
    def set_ad_mode(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value in _AD_MODES:
            self.ad_mode = value

    @rx.event
    def set_ad_scene_prompt(self, value: str) -> None:
        self.ad_scene_prompt = value

    @rx.event
    def set_human_avatar_prompt(self, value: str) -> None:
        self.human_avatar_prompt = value

    @rx.event
    def set_voice_gender(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value in _GENDERS:
            self.voice_gender = value
            self._sync_voice()

    def _sync_voice(self) -> None:
        """Keep the chosen voice inside the listed gender: the first one of that gender
        when the current one is not (or none is chosen yet)."""
        voices = [
            v
            for v in self.heygen_voices
            if v.get("own") == "1" or v.get("gender") == self.voice_gender
        ]
        if not any(v.get("id") == self.voice_id for v in voices):
            self.voice_id = voices[0]["id"] if voices else ""

    @rx.event
    def set_avatar_source(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value in ("ai", "image"):
            self.avatar_source = value

    @rx.event
    def set_avatar_prompt(self, value: str) -> None:
        self.avatar_prompt = value

    @rx.event
    def set_avatar_rights_confirmed(self, value: bool) -> None:
        self.avatar_rights_confirmed = bool(value)

    @rx.event
    def set_own_script_on(self, value: bool) -> None:
        self.own_script_on = bool(value)

    @rx.event
    def set_own_script(self, value: str) -> None:
        self.own_script = value

    @rx.event
    def set_avatar_engine(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value in ("avatar_iv", "avatar_iii"):
            self.avatar_engine = value

    @rx.event
    def set_media_carousel(self, value: bool) -> None:
        self.media_carousel = bool(value) and self.carousel_allowed

    @rx.event
    def set_brief_format(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value in {v for v, _ in self.format_options}:
            self.brief_format = value
            if not value.startswith("feed_"):
                self.media_carousel = False

    @rx.event
    def choose_gen_variant(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "0")
        try:
            self.gen_variant = max(int(value), 0)
        except ValueError:
            self.gen_variant = 0

    @rx.event
    def review_in_drafts(self) -> rx.event.EventSpec | None:
        """«Revisar y aprobar en Borradores»: the piece moves on to Borradores, and the
        generator starts over — coming back to «Crear pieza» shows its first screen, not
        the piece already sent (§ request 2026-10-08)."""
        draft_id = self.gen_draft_id
        self._back_to_form()
        self.brief_topic = ""
        self._reset_media_inputs()
        return rx.redirect(f"/drafts/{draft_id}") if draft_id else None

    @rx.event
    def new_generation(self) -> rx.event.EventSpec:
        """«Crear otro»: the result goes away and the form, inputs kept, is back on top —
        to try a variation."""
        self._back_to_form()
        return rx.call_script("window.scrollTo({top: 0, behavior: 'smooth'})")

    def _back_to_form(self) -> None:
        self.generator_view = "form"
        self.gen_draft = None
        self.gen_draft_id = ""
        self.gen_variant = 0
        self.gen_slide = 0
        self.gen_timed_out = False
        self.create_error = ""

    @rx.event(background=True)
    async def poll_generator(self) -> AsyncIterator[rx.event.EventSpec]:
        """The result view waits here: the draft is read until it leaves `drafting`
        (an avatar video can take several minutes). Stops on its own when the operator
        goes back to the form or starts another piece. When the piece lands it says so
        (§ request 2026-10-09): a toast in the app, and the browser's own notification
        when the tab is not in front — generation goes on while the operator is away."""
        async with self:
            draft_id = self.gen_draft_id
        ids = await self._session_ids()
        if ids is None or not draft_id:
            return
        tenant_id = ids[0]
        started = time.monotonic()
        while True:
            try:
                vm = await asyncio.to_thread(draft_detail, tenant_id, UUID(draft_id))
            except SQLAlchemyError as exc:
                logger.warning("generator poll failed: %s", type(exc).__name__)
                vm = None
            outcome = ""
            async with self:
                if self.gen_draft_id != draft_id or self.generator_view != "result":
                    return
                if vm is not None:
                    self.gen_draft = vm
                    if not vm.is_drafting:
                        outcome = "failed" if vm.is_failed else "ready"
                elif time.monotonic() - started > _GEN_POLL_BUDGET_SECONDS:
                    self.gen_timed_out = True
                    return
                if not outcome and time.monotonic() - started > _GEN_POLL_BUDGET_SECONDS:
                    self.gen_timed_out = True
                    return
            if outcome:
                for event in _generation_done_events(outcome):
                    yield event
                return
            await asyncio.sleep(_GEN_POLL_SECONDS)

    @rx.event
    def set_media_duration(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value in _DURATIONS:
            self.media_duration = value

    async def _save_uploads(self, files: list[rx.UploadFile]) -> list[tuple[str, str]]:
        """Store uploaded files under the tenant's namespace; `(key, name)` each. Sets
        `upload_error` and returns nothing on a missing session or unreadable file."""
        auth = await self.get_state(AuthState)
        tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            self.upload_error = _NO_SESSION
            return []
        saved: list[tuple[str, str]] = []
        for upload in files:
            try:
                data = await upload.read()
            except Exception:
                self.upload_error = _UPLOAD_FAILED
                return []
            name = upload.name or "imagen"
            key = f"uploads/{tenant_id}/{uuid4().hex}_{name}"
            target = rx.get_upload_dir() / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            saved.append((key, name))
        self.upload_error = ""
        return saved

    @rx.event
    async def handle_background_upload(self, files: list[rx.UploadFile]) -> None:
        saved = await self._save_uploads(files[:1])
        if saved:
            self.media_background_key, self.media_background_name = saved[0]

    @rx.event
    async def handle_product_uploads(self, files: list[rx.UploadFile]) -> None:
        room = _MAX_PRODUCTS - len(self.media_product_keys)
        saved = await self._save_uploads(files[: max(room, 0)])
        self.media_product_keys = [*self.media_product_keys, *(k for k, _ in saved)]
        self.media_product_names = [*self.media_product_names, *(n for _, n in saved)]

    @rx.event
    async def handle_avatar_upload(self, files: list[rx.UploadFile]) -> None:
        saved = await self._save_uploads(files[:1])
        if saved:
            self.avatar_image_key, self.avatar_image_name = saved[0]

    def _brand_asset(self, key: str) -> dict[str, str] | None:
        """The Brand Kit image behind `key` — None for anything else, so the picker can
        never place a key the session's own Brand Kit did not list."""
        return next((item for item in self.brand_media_items if item.get("key") == key), None)

    @rx.event
    def toggle_brand_logo(self, key: str) -> None:
        """«Recursos de tu marca»: the ONE logo of the piece — it takes the brand mark's
        place (the template's and flyer's logo slot, a corner of the avatar's scene). The
        same one again takes it off; another one replaces it."""
        asset = self._brand_asset(key)
        if asset is None or asset.get("kind") != "logo":
            return
        self.brand_logo_key = "" if self.brand_logo_key == key else key

    @rx.event
    def toggle_brand_element(self, key: str) -> None:
        """«Recursos de tu marca»: an element (a mascot, a pattern, the bag…) the piece
        uses as its usage note says — in, or out again."""
        asset = self._brand_asset(key)
        if asset is None or asset.get("kind") != "element":
            return
        if key in self.brand_element_keys:
            self.brand_element_keys = [k for k in self.brand_element_keys if k != key]
        elif len(self.brand_element_keys) < MAX_BRAND_ELEMENTS:
            self.brand_element_keys = [*self.brand_element_keys, key]

    @rx.event
    def use_brand_avatar_image(self, key: str) -> None:
        """«Del Brand Kit» as the animated character (a mascot, the isotipo…)."""
        asset = self._brand_asset(key)
        if asset is None:
            return
        if self.avatar_image_key == key:
            self.avatar_image_key, self.avatar_image_name = "", ""
            return
        self.avatar_image_key, self.avatar_image_name = key, asset.get("label", "")

    @rx.event
    def remove_product(self, key: str) -> None:
        self._drop_product(key)

    def _drop_product(self, key: str) -> None:
        pairs = [
            (k, n)
            for k, n in zip(self.media_product_keys, self.media_product_names, strict=False)
            if k != key
        ]
        self.media_product_keys = [k for k, _ in pairs]
        self.media_product_names = [n for _, n in pairs]

    @rx.event
    def clear_background(self) -> None:
        self.media_background_key = ""
        self.media_background_name = ""

    @rx.event
    def clear_avatar_image(self) -> None:
        self.avatar_image_key = ""
        self.avatar_image_name = ""

    def _kind_problem(self) -> str:
        """What the chosen kind still needs, in the operator's words ("" when ready)."""
        return self._presenter_problem() or self._details_problem()

    def _presenter_problem(self) -> str:
        """The wizard's «¿Quién lo presenta?» step: the avatar or character, and the
        voice. Only the two avatar kinds have a presenter."""
        seedance = self.video_engine == "seedance"
        if self.brief_kind == "avatar_video":
            if self.human_avatar_mode == "custom":
                if not self.human_avatar_prompt.strip():
                    return "Describe cómo es la persona que va a presentar el video."
            elif not self.avatar_look_id and not seedance:
                return "Elige el avatar que va a presentar el video."
        if self.brief_kind == "animated_avatar_video":
            if self.avatar_source == "ai" and not self.avatar_prompt.strip():
                return "Describe cómo es el personaje animado."
            if self.avatar_source == "image":
                if not self.avatar_image_key:
                    return "Sube la imagen del personaje que quieres animar."
                if not self.avatar_rights_confirmed:
                    return "Confirma que tienes derecho a animar esa imagen."
        if (
            self.brief_kind in ("avatar_video", "animated_avatar_video")
            and not seedance
            and not self.voice_id
        ):
            return "Elige la voz que va a leer el guion."
        return ""

    def _effective_topic(self) -> str:
        """What the piece is about: the ad image's scene is its whole brief (§ request
        2026-10-08), every other kind says it in «¿Qué quieres…?»."""
        if self.brief_kind == "static_flyer":
            return self.ad_scene_prompt.strip()
        return self.brief_topic.strip()

    def _details_problem(self) -> str:
        """The wizard's kind step: the ad's photos, or the operator's own script."""
        if self.brief_kind == "static_flyer":
            if self.ad_mode != "background" and not self.media_product_keys:
                return "Sube la foto de tu producto."
            if self.ad_mode != "product" and not self.media_background_key:
                return "Sube la foto del fondo (por ejemplo, tu local)."
            if not self.ad_scene_prompt.strip():
                return _SCENE_REQUIRED
        if self.kind_is_video and self.own_script_on and not self.own_script.strip():
            return "Escribe tu guion o apaga «Escribir mi propio guion»."
        if self.brief_kind == "template" and self.template_photo_count < _TEMPLATE_MIN_PHOTOS:
            return _TEMPLATE_PHOTO_REQUIRED
        if self.brief_kind == "carousel":
            if self.carousel_slide_count < _CAROUSEL_MIN:
                return "Un carrusel necesita al menos 2 diapositivas (el cierre cuenta)."
            if self.carousel_slide_count > _CAROUSEL_MAX:
                return "Un carrusel tiene como máximo 10 diapositivas (el cierre cuenta)."
        return ""

    def _form_problem(self) -> str:
        """The first thing the form still lacks, in the order of its sections — what
        Generar says above its button ("" when it may generate)."""
        if not self._effective_topic():
            return _SCENE_REQUIRED if self.brief_kind == "static_flyer" else _TOPIC_REQUIRED
        return self._kind_problem()

    @rx.event
    def toggle_rules(self) -> None:
        self.rules_open = not self.rules_open

    def _media_inputs(self) -> dict[str, object]:
        kind = self.brief_kind
        takes_images = kind != "creator_script"
        # the ad image sends only the photos its mode is built from
        is_ad = kind == "static_flyer"
        is_template = kind == "template"
        takes_background = (
            takes_images and not is_template and not (is_ad and self.ad_mode == "product")
        )
        takes_products = takes_images and not (is_ad and self.ad_mode == "background")
        product_keys = list(self.media_product_keys) if takes_products else []
        if is_template:
            # the catalog product's own photos ride along (deduplicated, the piece's
            # uploads first — the order `build_props` fills the photo port in)
            for key in self._selected_product_photo_keys:
                if key not in product_keys:
                    product_keys.append(key)
            product_keys = product_keys[:_MAX_PRODUCTS]
        media: dict[str, object] = {
            "duration_seconds": int(self.media_duration),
            "background_key": self.media_background_key or None if takes_background else None,
            "product_keys": product_keys,
            "carousel": self.media_carousel and self.carousel_allowed and takes_products,
            # «Recursos de tu marca» (§ 2026-10-06): apart from the background/products;
            # never for a real creator's script, which does not offer them (2026-10-08)
            "brand_logo_key": (self.brand_logo_key or None) if takes_images else None,
            "brand_element_keys": list(self.brand_element_keys) if takes_images else [],
        }
        if is_ad:
            media["ad_mode"] = self.ad_mode
            media["scene_prompt"] = self.ad_scene_prompt.strip()
        if kind == "carousel":
            # each slide's own photo is the product reference it is generated from
            photos, slides = self._carousel_slides_payload(bool(media["background_key"]))
            media.update(product_keys=photos, slides=slides, closing_slide=self.carousel_closing)
            return media
        if kind in ("avatar_video", "animated_avatar_video"):
            media["engine"] = self.avatar_engine
            media["video_engine"] = self.video_engine
            if self.own_script_on:
                media["own_script"] = self.own_script.strip()
        if kind in ("avatar_video", "animated_avatar_video") and self.video_engine == "seedance":
            # no library and no voice: the presenter is described (§ 2026-10-07)
            if kind == "avatar_video":
                described = (
                    self.human_avatar_prompt.strip()
                    if self.human_avatar_mode == "custom"
                    else _SEEDANCE_PRESENTERS.get(self.human_avatar_mode, "")
                )
                media.update(avatar_source="ai", avatar_prompt=described)
                return media
            media["avatar_source"] = self.avatar_source
            if self.avatar_source == "ai":
                media["avatar_prompt"] = self.avatar_prompt.strip()
            else:
                media.update(
                    avatar_image_key=self.avatar_image_key,
                    avatar_rights_confirmed=self.avatar_rights_confirmed,
                )
            return media
        if kind == "avatar_video":
            media["voice_id"] = self.voice_id
            if self.human_avatar_mode == "custom":
                media.update(avatar_source="ai", avatar_prompt=self.human_avatar_prompt.strip())
            else:
                media["avatar_look_id"] = self.avatar_look_id
        if kind == "animated_avatar_video":
            media.update(voice_id=self.voice_id, avatar_source=self.avatar_source)
            if self.avatar_source == "ai":
                media["avatar_prompt"] = self.avatar_prompt.strip()
            else:
                media.update(
                    avatar_image_key=self.avatar_image_key,
                    avatar_rights_confirmed=self.avatar_rights_confirmed,
                )
        return media

    def _reset_media_inputs(self) -> None:
        self.clear_product()
        self.brand_logo_key = ""
        self.brand_element_keys = []
        self.media_background_key = ""
        self.media_background_name = ""
        self.media_product_keys = []
        self.media_product_names = []
        self.media_carousel = False
        self.carousel_slides = _default_slides()
        self.carousel_closing = True
        self.carousel_selected = 0
        self.carousel_adding = False
        self.piece_picker_open = False
        self.avatar_prompt = ""
        self.human_avatar_prompt = ""
        self.ad_scene_prompt = ""
        self.avatar_image_key = ""
        self.avatar_image_name = ""
        self.avatar_rights_confirmed = False

    @rx.event
    def select_route(self, key: str) -> None:
        for option in self.route_options:
            if option.key == key and option.enabled:
                self.selected_route = key
                self.upload_error = ""
                return

    @rx.event
    async def handle_photo_upload(self, files: list[rx.UploadFile]) -> None:
        """Receive the FROM_UPLOAD photo. FOREGROUND on purpose (Reflex forbids
        background handlers that receive uploads). The file lands under a
        tenant-namespaced key — the logout-hygiene rule of §6."""
        if not files:
            return
        auth = await self.get_state(AuthState)
        tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            self.upload_error = _NO_SESSION
            return
        upload = files[0]
        try:
            data = await upload.read()
        except Exception:
            self.upload_error = _UPLOAD_FAILED
            return
        name = upload.name or "photo"
        key = f"uploads/{tenant_id}/{uuid4().hex}_{name}"
        target = rx.get_upload_dir() / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.staged_media_key = key
        self.staged_media_name = name
        self.upload_error = ""

    @rx.event(background=True)
    async def submit_brief_form(self) -> AsyncIterator[rx.event.EventSpec]:
        """/create's form: the image route picked in the accordion."""
        async with self:
            if self.is_submitting:
                return
            if not self.brief_topic.strip():
                self.create_error = _TOPIC_REQUIRED
                return
            if self.selected_needs_upload and not self.staged_media_key:
                self.create_error = _UPLOAD_REQUIRED
                return
            self.is_submitting = True
            self.create_error = ""
            form = {
                "objective": self.brief_objective,
                "content_type": self.brief_content_type,
                "topic": self.brief_topic,
                "product_ref": self.brief_product_ref,
                "intent": self.brief_intent,
                "image_route": self.selected_route,
                "source_media_key": self.staged_media_key,
                "must_mention": self.brief_must_mention,
                "must_avoid": self.brief_must_avoid,
            }
        draft_id = await self._create_draft(form)
        if draft_id is not None:
            async with self:
                self.brief_topic = ""
                self.staged_media_key = ""
                self.staged_media_name = ""
            yield rx.redirect(f"/drafts/{draft_id}")

    @rx.event(background=True)
    async def submit_generator_form(self) -> AsyncIterator[rx.event.EventSpec]:
        """The content generator on /signals (`content_generator.py`): the content kind
        and its inputs; the image route is derived from them
        (`creative_provider.submit_brief`)."""
        async with self:
            if self.is_submitting or self.gen_generating:
                return
            problem = self._form_problem()
            if problem:
                self.create_error = problem
                return
            self.is_submitting = True
            self.create_error = ""
            form = self._generator_form()
            template_form = self._template_form() if self.brief_kind == "template" else None
        # A template the router cannot make from what the piece has is said here, before
        # anything is created (it used to be checked on «¿Todo listo?»).
        if template_form is not None:
            blocker = await self._template_blocker(template_form)
            if blocker:
                async with self:
                    self.is_submitting = False
                    self.create_error = _TEMPLATE_BLOCKED + blocker
                return
        yield CreativeState.preview_prompt  # the prompt it sends, in the console
        # ask once for the browser's notifications, so the piece can say "listo" even
        # when the operator went to another tab meanwhile (§ request 2026-10-09)
        yield rx.call_script(_ASK_NOTIFICATIONS_JS)
        draft_id = await self._create_draft(form)
        if draft_id is None:
            return
        # The piece shows below the form, on the same page (§ request 2026-10-08).
        async with self:
            self.generator_view = "result"
            self.gen_draft_id = str(draft_id)
            self.gen_draft = None
            self.gen_variant = 0
            self.gen_slide = 0
            self.gen_timed_out = False
        yield CreativeState.poll_generator
        yield rx.call_script(
            "setTimeout(() => document.getElementById('gen-result')"
            "?.scrollIntoView({behavior: 'smooth', block: 'start'}), 150)"
        )

    def _generator_form(self) -> dict[str, object]:
        """The generator's brief as `creative_provider.build_brief` takes it — what
        Generar submits and what «¿Todo listo?» previews (caller holds the lock)."""
        return {
            "objective": self.brief_objective,
            "content_type": self.brief_content_type,
            "topic": self._effective_topic(),
            "product_ref": self.brief_product_ref,
            "intent": self.brief_intent,
            "image_route": "",
            "source_media_key": "",
            "must_mention": self.brief_must_mention,
            "must_avoid": self.brief_must_avoid,
            "kind": self.brief_kind,
            "media": self._media_inputs(),
            "content_format": self.effective_format,
            "variants_requested": _SCRIPT_OPTIONS if self.brief_kind == "creator_script" else 1,
        }

    @rx.event(background=True)
    async def preview_prompt(self) -> None:
        """On Generar: the copy prompt it sends, printed to the console
        (`trace.copy_prompt`, § request 2026-10-06) — nothing is created or spent. Only a
        debugging aid: any failure is logged and the screen is left alone."""
        ids = await self._session_ids()
        if ids is None:
            return
        tenant_id, brand_id, _ = ids
        async with self:
            form = self._generator_form()
        try:
            await asyncio.to_thread(lambda: preview_brief_prompt(tenant_id, brand_id, **form))
        except Exception as exc:  # a preview must never break the generator
            logger.warning("prompt preview failed: %s: %s", type(exc).__name__, exc)

    def _template_form(self) -> dict[str, object]:
        """What `template_blocker` needs to judge the template (caller holds the lock)."""
        return {
            "content_type": self.brief_content_type,
            "product_ref": self.brief_product_ref,
            "product_keys": list(self._media_inputs()["product_keys"]),  # type: ignore[arg-type]
            "source_media_key": self.staged_media_key,
            "content_format": self.effective_format,
        }

    async def _template_blocker(self, form: dict[str, object]) -> str:
        """Whether the router's template can be made from what the piece has — what
        «¿Cómo la hacemos?» used to say. A check that cannot run blocks nothing: the
        draft then says what failed. Called outside the state lock."""
        ids = await self._session_ids()
        if ids is None:
            return ""
        try:
            return await asyncio.to_thread(lambda: template_blocker(ids[0], ids[1], **form))
        except Exception as exc:  # noqa: BLE001 — the render either works or says why
            logger.warning("template check failed: %s", type(exc).__name__)
            return ""

    async def _create_draft(self, form: dict[str, object]) -> UUID | None:
        """Create the draft from a form — shared by both forms. Must be called outside
        the state lock, with `is_submitting` already set; clears it either way and
        leaves the reason in `create_error` when nothing was created."""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.is_submitting = False
                self.create_error = _NO_SESSION
            return None
        tenant_id, brand_id, user_id = ids
        try:
            draft_id = await asyncio.to_thread(
                lambda: submit_brief(tenant_id, brand_id, user_id, **form)
            )
        except BrandNotReady:
            async with self:
                self.is_submitting = False
                self.create_error = _BRIEF_NOT_READY
            return None
        except RouteBlockedByPolicy as exc:
            async with self:
                self.is_submitting = False
                self.create_error = _ROUTE_BLOCKED + exc.detail
            return None
        except (ValidationError, ValueError) as exc:
            async with self:
                self.is_submitting = False
                self.create_error = _BRIEF_INVALID + str(exc).splitlines()[0]
            return None
        except SQLAlchemyError as exc:
            logger.error("submit brief failed: %s", type(exc).__name__)
            async with self:
                self.is_submitting = False
                self.create_error = _DB_ERROR
            return None
        async with self:
            self.is_submitting = False
        return draft_id

    # -- /drafts ------------------------------------------------------------

    @rx.event(background=True)
    async def load_drafts(self) -> None:
        async with self:
            self.drafts_loading = True
            self.drafts_error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.drafts_loading = False
                self.drafts_error = _NO_SESSION
            return
        tenant_id, brand_id, _ = ids
        try:
            # Through the service: its listing runs the reaper first (§7.4).
            data = await asyncio.to_thread(list_drafts, tenant_id, brand_id)
        except SQLAlchemyError as exc:
            logger.error("drafts load failed: %s", type(exc).__name__)
            async with self:
                self.drafts_loading = False
                self.drafts_error = _DB_ERROR
            return
        async with self:
            self.drafts = list(data)
            self.drafts_loading = False

    # -- /drafts/[draft_id] (HITL #2) ----------------------------------------

    def _route_draft_id(self) -> UUID | None:
        """The dynamic route arg, parsed. Refuses junk rather than querying with it."""
        raw = getattr(self, "draft_id", "")
        try:
            return UUID(str(raw))
        except (ValueError, AttributeError):
            return None

    def _apply_detail(self, vm: DraftVM) -> None:
        if self.draft is None or self.draft.draft_id != vm.draft_id:
            self.draft_slide = 0  # another draft opens on its first slide
        self.draft = vm
        current = {v.variant_id for v in vm.variants}
        if self.selected_variant_id not in current:
            self.selected_variant_id = vm.variants[0].variant_id if vm.variants else ""
        self._fill_edit_fields()

    def _fill_edit_fields(self) -> None:
        for variant in self.draft.variants if self.draft is not None else ():
            if variant.variant_id == self.selected_variant_id:
                self.edit_hook = variant.hook
                self.edit_caption = variant.caption
                self.edit_hashtags = variant.hashtags_text
                self.edit_cta = variant.cta
                self.edit_script = variant.script
                self.edit_blocking = list(variant.failure_labels)
                # Suggestions belong to the text they were made for.
                self.ai_hashtags = []
                self.ai_hashtags_note = ""
                self.edit_catalog_tags = []
                self.edit_hashtag_query = ""
                self.edit_cta_query = ""
                return

    @rx.event(background=True)
    async def load_draft(self) -> AsyncIterator[None]:
        async with self:
            self.detail_loading = True
            self.detail_error = ""
            self.action_error = ""
            self.poll_timed_out = False
            self.edit_mode = False
            draft_id = self._route_draft_id()
        if draft_id is None:
            async with self:
                self.detail_loading = False
                self.detail_error = _DRAFT_GONE
            return
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.detail_loading = False
                self.detail_error = _NO_SESSION
            return
        tenant_id, _, _ = ids
        try:
            vm = await asyncio.to_thread(draft_detail, tenant_id, draft_id)
        except SQLAlchemyError as exc:
            logger.error("draft load failed: %s", type(exc).__name__)
            async with self:
                self.detail_loading = False
                self.detail_error = _DB_ERROR
            return
        async with self:
            self.detail_loading = False
            if vm is None:
                self.detail_error = _DRAFT_GONE
                return
            self._apply_detail(vm)
            should_poll = vm.is_drafting and self._polling_draft_id != str(draft_id)
            if should_poll:
                self._polling_draft_id = str(draft_id)
        if should_poll:
            yield CreativeState.poll_draft

    @rx.event(background=True)
    async def poll_draft(self) -> AsyncIterator[rx.event.EventSpec]:
        """Poll while DRAFTING. Backs off 1s → 2s → 4s, caps at 5s, gives up at 5 min
        with a visible timeout state (§6.6). Since 2026-10-09 (pendientes §5) the poll
        outlives the screen: opening another draft or another page no longer stops it —
        the generation is running anyway — it only stops refreshing a detail that is not
        on screen, and when the draft lands it says so (toast; the browser's own
        notification when the tab is behind)."""
        async with self:
            polling_id = self._polling_draft_id
        draft_id = tenant_uuid(polling_id)  # UUID-or-None parse, same shape as tenants
        if draft_id is None:
            return
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self._polling_draft_id = ""
            return
        tenant_id, _, _ = ids
        started = time.monotonic()
        attempt = 0
        try:
            while True:
                elapsed = time.monotonic() - started
                if elapsed >= _POLL_BUDGET_SECONDS:
                    async with self:
                        if self._polling_draft_id == polling_id:
                            self.poll_timed_out = True
                            self.detail_error = _POLL_TIMEOUT
                    return
                delay = _POLL_DELAYS[attempt] if attempt < len(_POLL_DELAYS) else _POLL_CAP_SECONDS
                attempt += 1
                await asyncio.sleep(delay)
                try:
                    vm = await asyncio.to_thread(draft_detail, tenant_id, draft_id)
                except SQLAlchemyError as exc:
                    logger.error("draft poll failed: %s", type(exc).__name__)
                    continue  # transient; the budget above still bounds the loop
                outcome = ""
                async with self:
                    # still the draft on screen? then its detail is refreshed; otherwise
                    # the poll only waits for the end to say so
                    on_screen = self._polling_draft_id == polling_id
                    if on_screen:
                        self.poll_elapsed_label = f"{int(time.monotonic() - started)} s"
                    if vm is not None:
                        if on_screen:
                            self._apply_detail(vm)
                        if not vm.is_drafting:
                            outcome = "failed" if vm.is_failed else "ready"
                if outcome:
                    for event in _generation_done_events(outcome, source="draft"):
                        yield event
                    return
        finally:
            async with self:
                if self._polling_draft_id == polling_id:
                    self._polling_draft_id = ""

    @rx.event
    def select_variant(self, variant_id: str) -> None:
        self.selected_variant_id = variant_id
        self.edit_mode = False
        self._fill_edit_fields()

    @rx.event
    def start_edit(self):
        self.edit_mode = True
        return CreativeState.load_catalog_hashtags

    @rx.event
    def cancel_edit(self) -> None:
        """Discard unsaved changes: the fields show the saved copy again."""
        self.edit_mode = False
        self._fill_edit_fields()

    @rx.event(background=True)
    async def save_edit(self) -> None:
        """Re-run layer 1 over the edit IN THE ACT (§6.5): blocking failures render and
        keep the approve button disabled with the reason."""
        async with self:
            if self.edit_saving or not self.selected_variant_id:
                return
            self.edit_saving = True
            self.action_error = ""
            variant_id = self.selected_variant_id
            hook, caption = self.edit_hook, self.edit_caption
            hashtags, cta = self.edit_hashtags, self.edit_cta
            script = self.edit_script if self.draft is not None and self.draft.has_script else None
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.edit_saving = False
                self.action_error = _NO_SESSION
            return
        tenant_id, _, user_id = ids
        try:
            failures = await asyncio.to_thread(
                lambda: edit_variant(
                    tenant_id,
                    UUID(variant_id),
                    user_id,
                    hook=hook,
                    caption=caption,
                    hashtags=hashtags,
                    cta=cta,
                    script=script,
                )
            )
        except (UnknownVariant, UnknownDraft):
            async with self:
                self.edit_saving = False
                self.action_error = _DRAFT_GONE
            return
        except InvalidTransition:
            # The FSM refuses edits once the draft is staged, published or failed — e.g.
            # it was published while this screen was open. Reload to show where it is.
            async with self:
                self.edit_saving = False
                self.edit_mode = False
                self.action_error = _NOT_EDITABLE
            await self._reload_detail()
            return
        except SQLAlchemyError as exc:
            logger.error("edit failed: %s", type(exc).__name__)
            async with self:
                self.edit_saving = False
                self.action_error = _DB_ERROR
            return
        async with self:
            self.edit_saving = False
            self.edit_blocking = list(failures)
            if not failures:
                self.edit_mode = False  # saved: back to read-only
        if not failures:
            await self._reload_detail()

    async def _reload_detail(self) -> None:
        async with self:
            draft_id = self._route_draft_id()
        ids = await self._session_ids()
        if ids is None or draft_id is None:
            return
        tenant_id, _, _ = ids
        try:
            vm = await asyncio.to_thread(draft_detail, tenant_id, draft_id)
        except SQLAlchemyError as exc:
            logger.error("detail reload failed: %s", type(exc).__name__)
            return
        async with self:
            if vm is not None:
                self._apply_detail(vm)

    @rx.event(background=True)
    async def approve_selected(self) -> AsyncIterator[rx.event.EventSpec]:
        """Approve the selected variant (the FSM guard requires one). Approving no
        longer downloads anything (founder, 2026-10-06): the media has its own download
        under it, and the approved POST is ready for the Planificador."""
        async with self:
            draft = self.draft
            variant = self.selected_variant
            if draft is None or variant is None:
                self.action_error = _VARIANT_REQUIRED
                return
            if not self.can_approve_now:
                return
            self.action_error = ""
            draft_uuid = self._route_draft_id()
        if draft_uuid is None:
            return
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.action_error = _NO_SESSION
            return
        tenant_id, _, user_id = ids
        try:
            vm = await asyncio.to_thread(
                approve_draft, tenant_id, draft_uuid, UUID(variant.variant_id), user_id
            )
        except (UnknownDraft, UnknownVariant):
            async with self:
                self.action_error = _DRAFT_GONE
            return
        except SQLAlchemyError as exc:
            logger.error("approve failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _DB_ERROR
            return
        async with self:
            self._apply_detail(vm)
        yield rx.toast.success("POST aprobado: ya puedes programarlo en el Planificador.")

    @rx.event
    def ask_reject(self, regenerate: bool) -> None:
        self.reject_confirm = "regenerate" if regenerate else "reject"

    @rx.event
    def set_reject_confirm_open(self, value: bool) -> None:
        if not value:
            self.reject_confirm = ""

    @rx.event
    def confirm_reject(self):
        regenerate = self.reject_confirm == "regenerate"
        self.reject_confirm = ""
        return CreativeState.reject_current(regenerate)

    @rx.event(background=True)
    async def reject_current(self, regenerate: bool) -> AsyncIterator[None]:
        async with self:
            self.action_error = ""
            draft_uuid = self._route_draft_id()
        if draft_uuid is None:
            return
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.action_error = _NO_SESSION
            return
        tenant_id, _, user_id = ids
        try:
            vm = await asyncio.to_thread(
                lambda: reject_draft(
                    tenant_id,
                    draft_uuid,
                    user_id,
                    reason="rejected from HITL #2",
                    regenerate=bool(regenerate),
                )
            )
        except UnknownDraft:
            async with self:
                self.action_error = _DRAFT_GONE
            return
        except InvalidTransition:
            # The draft moved on (another tab, or an already-rejected/approved draft):
            # say so instead of letting the FSM error reach the generic Reflex toast.
            async with self:
                self.action_error = _NOT_REJECTABLE
            return
        except SQLAlchemyError as exc:
            logger.error("reject failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _DB_ERROR
            return
        async with self:
            self._apply_detail(vm)
            should_poll = vm.is_drafting and self._polling_draft_id != vm.draft_id
            if should_poll:
                self._polling_draft_id = vm.draft_id
        if should_poll:
            # the regeneration says "listo" even from another tab (pendientes §5)
            yield rx.call_script(_ASK_NOTIFICATIONS_JS)
            yield CreativeState.poll_draft


# ---------------------------------------------------------------------------------------
# Typography previews (pure helpers, tested without Reflex)

GOOGLE_FONTS_CSS = "https://fonts.googleapis.com/css2"


def _clean_family(name: str) -> str:
    """A family name as typed, minus what would break a CSS string or a URL: quotes,
    backslashes, braces, semicolons — a family name never legitimately holds them."""
    return " ".join(re.sub(r'["\\{};<>]', "", name).split())


def font_family_css(name: str) -> str:
    """The `font-family` for a typed family name — quoted, with a generic fallback so a
    family the browser cannot load degrades to the page's own sans; `inherit` for none."""
    clean = _clean_family(name)
    return f'"{clean}", sans-serif' if clean else "inherit"


def google_fonts_url(name: str) -> str:
    """The Google Fonts stylesheet for a family name ("" for none): regular + bold, so
    the "Aa" and the sample line both render in it when the family exists there."""
    clean = _clean_family(name)
    if not clean:
        return ""
    # encoded, so a typed "&", "#" or "%" can neither add a parameter nor break the URL
    family = urllib.parse.quote_plus(clean)
    return f"{GOOGLE_FONTS_CSS}?family={family}:wght@400;700&display=swap"
