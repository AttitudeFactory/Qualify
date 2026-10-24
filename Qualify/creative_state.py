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
from qualify_api.creative.campaigns import InvalidCampaignName, clean_name
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.fsm import InvalidTransition
from qualify_api.creative.service import (
    ApprovalBlocked,
    BrandNotReady,
    DraftExpired,
    RouteBlockedByPolicy,
    UnknownDraft,
    UnknownVariant,
)
from qualify_api.creative.voice_service import NotProposed, UnknownBrandKit, UnknownVersion
from qualify_api.stock.keys import is_stock_key
from qualify_creative.creations import (
    CreationNotOffered,
    CreationPrice,
    is_presenter_request,
    load_weights,
    weight_for_request,
)
from qualify_creative.enums import (
    BriefIntent,
    BriefObjective,
    ContentFormat,
    ContentKind,
    ContentType,
    DraftStatus,
)
from qualify_creative.schemas import (
    CLIP_IMAGE_ROLES,
    HIGHLIGHT_KEY_MAX,
    HIGHLIGHT_VALUE_MAX,
    HIGHLIGHTS_MAX,
    MAX_BRAND_ELEMENTS,
)
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState, brand_tenant_id
from .campaign_provider import (
    COLOR_LABELS,
    NEW_CAMPAIGN,
    NO_CAMPAIGN,
    CampaignOptionVM,
    apply_post_choice,
    brand_campaign_options,
    suggested_color,
)
from .campaign_provider import error_message as campaign_error_message
from .catalog_vm import VARIATIONS_MODE, create_mode_from_query, product_id_from_query
from .creative_provider import (
    FINAL_POLL_WINDOW_SECONDS,
    acting_user_id,
    approval_videos,
    approve_draft,
    approve_voice,
    brand_character,
    brand_media,
    brand_pieces,
    brand_readiness,
    catalog_products,
    configured_video_engine,
    creations_balance,
    default_brand_id,
    draft_detail,
    edit_variant,
    enhance_generator_context,
    final_video_state,
    list_drafts,
    load_kit_form,
    load_voice_screen,
    preview_brief_prompt,
    propose_voice,
    recreate_draft,
    recreate_note,
    regeneration_creations,
    reject_draft,
    retry_final,
    route_options_for,
    save_kit,
    submit_brief,
    template_blocker,
    voice_options,
)
from .creative_vm import (
    APPROVE_VERSION_LABEL,
    CAPTION_LIMIT,
    CATEGORY_OPTIONS,
    CTA_SUGGESTIONS,
    FINAL_POLL_CONTINUE,
    FINAL_POLL_DONE,
    FINAL_POLL_FAILED,
    FINAL_READY_NOT_READY,
    FINAL_READY_TEXT,
    HASHTAG_LIMIT,
    HOOK_LIMIT,
    KIND_LABELS,
    PRESENTER_TOO_LONG,
    SHORT_ADVICE_SIMPLER,
    VIDEO_DRAFT,
    VIDEO_TOO_LONG,
    VIDEO_TYPE_LABELS,
    CopyVariantVM,
    DraftSummaryVM,
    DraftVM,
    HashtagIdeaVM,
    KitFormVM,
    ReadinessVM,
    RouteOptionVM,
    VoiceProposalVM,
    add_phrase,
    approval_notice,
    approval_videos_notice,
    caption_hashtag_suggestions,
    caption_keywords,
    content_type_options,
    creations_left_label,
    creations_use_notice,
    cta_list,
    final_pending_note,
    final_poll_step,
    format_ctas,
    format_hashtags,
    hashtag_list,
    not_enough_creations_text,
    phrase_list,
    presenter_fallback_text,
    previews_left_label,
    previews_short_text,
    remove_phrase,
    seen_label,
    videos_short_text,
)
from .gallery_state import schedule_readiness
from .pending_state import PendingState
from .planner_provider import load_gallery, times_published
from .planner_vm import history_help, history_word
from .stock_provider import (
    PROVIDER_CREDITS,
    StockUnavailable,
    kit_search_queries,
    stock_available,
)
from .stock_provider import import_image as import_stock_image
from .stock_provider import import_video as import_stock_video
from .stock_provider import search_from_kit as search_stock_from_kit
from .stock_provider import search_images as search_stock_images
from .tenant import tenant_uuid
from .upload_names import safe_upload_name

logger = logging.getLogger(__name__)

#: What a handler that may chain others returns: one event, several, or none.
_Events = list[rx.event.EventHandler | rx.event.EventSpec] | rx.event.EventSpec | None


def _scroll_to_view() -> rx.event.EventSpec:
    """CREAR-6 (UX review): on a phone the options are one column taller than the
    screen, so what opens when one is chosen is below it — bring the centre
    (`#q-cr-view`) into sight. On a wide screen the centre is beside the panel: no-op."""
    return rx.call_script(
        "if (window.matchMedia('(max-width: 899px)').matches) {"
        " setTimeout(() => document.getElementById('q-cr-view')"
        "?.scrollIntoView({behavior: 'smooth', block: 'start'}), 120); }"
    )


def _with_scroll(events: _Events) -> _Events:
    """`events` followed by `_scroll_to_view`."""
    if events is None:
        return [_scroll_to_view()]
    if isinstance(events, list):
        return [*events, _scroll_to_view()]
    return [events, _scroll_to_view()]


_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_BRAND = "Este negocio no tiene ninguna marca provisionada todavía."
_NO_USER = "Este negocio no tiene ningún usuario al que atribuir la acción."
_DB_ERROR = "Algo falló de nuestro lado. Inténtalo de nuevo en un momento."
_KIT_SAVED = "Tu marca quedó guardada."
_KIT_INVALID = "Revisa los campos del kit: "
_NO_KIT_TO_PROPOSE = (
    "Todavía no sabemos lo suficiente de tu marca para proponer cómo habla. "
    "Complétala primero en Tu marca."
)
_STALE_PROPOSAL = "Esa propuesta ya no está vigente. Recargamos el estado real."
_BRIEF_NOT_READY = (
    "Completa tu marca (colores, logo y forma de hablar) para que todo salga con tu estilo."
)
_ROUTE_BLOCKED = (
    "Tu marca no permite crear la imagen de esa forma. Elige otra opción para la imagen."
)
# ImagePolicy.reason_for's fallback says the same thing again: never append it.
_ROUTE_BLOCKED_DEFAULT_DETAIL = "No habilitada para esta marca."


def route_blocked_text(detail: str) -> str:
    """What the owner reads when the brand's image policy refuses a route."""
    detail = (detail or "").strip()
    if not detail or detail == _ROUTE_BLOCKED_DEFAULT_DETAIL:
        return _ROUTE_BLOCKED
    return f"{_ROUTE_BLOCKED} {detail}"


#: NAV-11 (m-24849129): the brief's own refusal is an English invariant ("a template needs
#: at least one product photo"), so the owner reads this and the log keeps the detail.
_BRIEF_INVALID = (
    "Falta algo para crear esta publicación. Revisa lo que elegiste y vuelve a intentarlo."
)
#: «Potenciar con IA» (§ request 2026-10-20): what the operator reads around it.
_ENHANCE_MIN_CHARS = 8
#: The animated avatar with nothing in the Brand Kit to make its character from.
_NO_BRAND_CHARACTER = (
    "Tu marca todavía no tiene con qué crear el personaje animado. Complétala y vuelve."
)
_ENHANCE_TOO_SHORT = "Escribe primero unas palabras sobre lo que quieres: la IA parte de ellas."
_ENHANCE_FAILED = "No pudimos mejorar tu texto ahora mismo. Inténtalo de nuevo en un momento."
_ENHANCE_STALE = "Cambiaste el texto mientras tanto. Vuelve a pulsar «Mejorar mi texto»."
_ENHANCE_ADDED = "Revisa estos datos, que la IA añadió y no venían de ti: "
#: The flyer's scene field takes this much (its text area's `max_length`).
_SCENE_MAX_CHARS = 600
_UPLOAD_FAILED = "No se pudo leer la foto subida. Intenta con otro archivo."
#: The clip's middle images are references: only Seedance 2.x takes them (review
#: 2026-10-20 — without it the clip is made from its first and last image).
_CLIP_MIDDLE_NOTE = (
    "Las imágenes entre la primera y la última son referencias y necesitan el modelo de "
    "video avanzado. Si no está activado, el clip se hace solo con la primera y la última."
)
#: An animated slide takes one photo and one video: what its drop zone left out.
_SLIDE_MEDIA_EXTRA = (
    "Una diapositiva animada usa una foto y un video: subimos el primero de cada uno."
)
_UPLOAD_REQUIRED = "Esta ruta trabaja sobre tu foto: súbela antes de enviar el encargo."
_TOPIC_REQUIRED = "Cuéntanos qué quieres en la publicación: es lo único obligatorio."
_SCENE_REQUIRED = "Describe la escena de la imagen: es lo único obligatorio."
_VOICES_DOWN = "No pudimos cargar las voces. Inténtalo de nuevo."

#: `ContentKind` values that can be chosen today — all five since the template engine
#: landed (plan-mvp-plantillas-remotion.md, 2026-10-05).
_ENABLED_KINDS = (
    "creator_script",
    "avatar_video",
    "animated_avatar_video",
    "static_flyer",
    "template",
    "carousel",
    "clip",
)
#: The generator's options since 2026-10-14 (Guion · Clip · Galería · Flyer · Plantilla ·
#: Ad). Clip ("video") has its types — the two avatar kinds. «Ad» is the template kind
#: rendering its Reel (it was a type within Video until 2026-10-14); «Plantilla» is the
#: same kind rendering one still (feed or story).
GEN_CATEGORIES = ("script", "video", "clip", "image", "template", "carousel", "ad")
#: The options that take a reference clip before their context (§ request 2026-10-14).
REFERENCE_CATEGORIES = ("video", "ad", "clip")
#: The two that take ONE reference clip on the brief (`reference_video_key`); the clip
#: takes its own set — frames, images, videos, audio (`clip_*`).
_SINGLE_REFERENCE_CATEGORIES = ("video", "ad")
#: A clip's references, as Seedance 2.x takes them (frames count among the images).
CLIP_MAX_IMAGES = 9
CLIP_MAX_VIDEOS = 3
#: How many stock hits the product screen takes at once (§ request 2026-10-19).
STOCK_MAX_PICKS = 6
CLIP_MAX_AUDIOS = 3
#: The lengths a clip can be asked for (§ request 2026-10-23: «que empiece desde 5 seg»).
#: Founder, 2026-10-24: a generated video is 5 or 10 s and counts as one of the month's
#: videos; 15 s is not offered (`pesos-creaciones-v2` → `videos.offered_seconds`).
CLIP_DURATIONS = ("5", "10")
#: What a photo taken from the catalog product is called in the editor.
_CATALOG_PHOTO = "Foto del catálogo"
#: What a file of a stock inspiration is called in the editor (§ 2026-10-19: «stock» is
#: «inspiración» for the operator).
_INSPIRATION = "Inspiración"
#: The generator's slots that take a file (§ request 2026-10-14), each with its type
#: and whether it holds several; each shows the tabs «Catálogo» · «Subir» · «Piezas».
_PICKER_TARGETS: dict[str, tuple[str, bool]] = {
    "products": ("image", True),
    "reference": ("video", False),
    "clip_images": ("image", True),
    "clip_videos": ("video", True),
    "slide": ("image", False),
    #: § request 2026-10-19: the common background (flyer, avatar, gallery) and an
    #: animated slide's motion reference take files from a picker too
    "background": ("image", False),
    "slide_reference": ("video", False),
    #: § request 2026-10-20: an animated slide's ONE picker, images and videos together
    #: in every tab — an image is the slide's photo, a video its motion reference
    "slide_media": ("mixed", False),
}
#: A mixed slot's file goes to the single-type slot of its type.
_MIXED_SLOTS: dict[str, dict[str, str]] = {
    "slide_media": {"image": "slide", "video": "slide_reference"},
}
#: «catalog» is the chosen product's files — «Inspiración» when it came from stock;
#: «brandcat» (only then) is the brand's whole catalog, to bring its files in too
#: (§ request 2026-10-19). No «Stock» tab any more: stock is picked as the inspiration.
_PICKER_TABS = ("catalog", "brandcat", "inspiration", "upload", "pieces")
#: The slots whose picker can search inspiration — every one (§ requests 2026-10-19:
#: Flyer, Avatar's product photos and reference video too); the licence guard
#: (`qualify_api.stock.guard`) allows stock in all of them.
_INSPIRATION_TARGETS = (
    "products",
    "reference",
    "clip_images",
    "clip_videos",
    "slide",
    "background",
    "slide_reference",
    "slide_media",
)
#: The slots with no «Catálogo» tab (the catalog holds products, not places or motion):
#: with a stock product their first tab is still the inspiration's own files.
_NO_CATALOG_TARGETS = ("background", "slide_reference")


def _default_clip_role(source: str) -> str:
    """A clip reference image's first role: a piece already made is a look to borrow;
    a catalog photo or an upload, the product (§ 2026-10-14)."""
    return "style" if source in ("pieces", "inspiration") else "product"


#: The kinds that compose product photos, so the catalog product's own ride along.
_CATALOG_PHOTO_KINDS = ("template", "static_flyer", "avatar_video", "animated_avatar_video")
VIDEO_TYPES = ("avatar_video", "animated_avatar_video")
_CATEGORY_KIND = {
    "script": "creator_script",
    "video": "avatar_video",
    "image": "static_flyer",
    "template": "template",
    "carousel": "carousel",
    "ad": "template",
    "clip": "clip",
}
#: The carousel's slides (§ request 2026-10-09): where each comes from, what it prints,
#: how long a video lasts — the editor's values, `CarouselSlide`'s fields.
_SLIDE_SOURCES = ("generated", "animated")
#: What a slide may carry printed (§ 2026-10-14): nothing or the title — the hook. The
#: «Botón de acción» left: the scene already holds the button, and the post its CTA.
_SLIDE_TEXTS = ("none", "hook")
#: An animated slide's length — the editor's choices and what `set_slide_field` keeps.
SLIDE_SECONDS = ("5", "10")
_CAROUSEL_MIN = 2
_CAROUSEL_MAX = 10
#: The gallery (§ request 2026-10-14): exactly three slides, one video at most, no
#: closing slide.
_GALLERY_SLIDES = 3
_GALLERY_MAX_VIDEOS = 1
_GALLERY_ONE_VIDEO = "Una galería lleva como máximo 1 video: cambia la otra diapositiva primero."
#: The presenter has no library (Seedance 2026-10-07, OmniHuman 2026-10-16): «Mujer» /
#: «Hombre» are a described synthetic person like «Personalizado», with this description.
_PRESENTERS = {
    "female": "Mujer latina de unos 30 años, sonriente y cercana, ropa casual moderna.",
    "male": "Hombre latino de unos 30 años, sonriente y cercano, ropa casual moderna.",
}
#: The formats each template use renders — ONE output, the one of this format.
_TEMPLATE_FORMATS = {
    # «Video publicitario» (§ 2026-10-13): the template's video in every placement — a
    # Story video is the Reel's 9:16, a feed video is shown at its 4:5 / 1:1 shape
    "video": (
        ContentFormat.REELS_9_16,
        ContentFormat.STORY_9_16,
        ContentFormat.FEED_4_5,
        ContentFormat.FEED_1_1,
    ),
    # «Con plantilla»: the still, in the feed and story — a Reel is a video, not this
    "template": (ContentFormat.FEED_4_5, ContentFormat.FEED_1_1, ContentFormat.STORY_9_16),
}
#: The Flyer is an image (§ request 2026-10-21, «me genera un video cuando selecciono
#: reel»): the feed and the story, never a Reel — which would animate the still into a
#: video (`MediaProducer._ad_reel`, added 2026-10-13). The kind still accepts a Reel, so
#: a flyer stored that way opens and regenerates as it was asked.
_FLYER_FORMATS = (ContentFormat.FEED_4_5, ContentFormat.FEED_1_1, ContentFormat.STORY_9_16)
#: Copy options per piece (§ request 2026-10-08): only a real creator's script offers
#: several — it has no media made from one of them; every other kind asks for ONE until
#: the angles engine exists.
_SCRIPT_OPTIONS = 3
#: The template's photos (`promo_producto`, photos.min): asked for in its own section,
#: not discovered on Generar. The ad image takes one (§ request 2026-10-08).
_TEMPLATE_MIN_PHOTOS = 2
#: The voices' genders, as the voice options carry them.
_GENDERS = ("female", "male")
_OBJECTIVES = frozenset(o.value for o in BriefObjective)
_INTENTS = frozenset(i.value for i in BriefIntent)
#: When a piece lands (§ request 2026-10-09): what the toast says, and what the
#: browser's own notification says when the tab is in the background.
_GEN_READY_TOAST = "Tu publicación está lista. Revísala en Crear publicación o en Por aprobar."
_GEN_FAILED_TOAST = "No se pudo crear la publicación. El detalle está en Crear publicación."
_DRAFT_READY_TOAST = "Tu nueva versión está lista. Revísala en Por aprobar."
_DRAFT_FAILED_TOAST = "No se pudo crear la nueva versión. El detalle está en Por aprobar."
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


#: The publication's page shows «Ya probada» / «Por probar» only once it is approved —
#: that is when the owner decides whether to repeat it (UX review, m-24842981).
_HISTORY_STATUSES: frozenset[str] = frozenset(
    {DraftStatus.APPROVED.value, DraftStatus.STAGED.value, DraftStatus.PUBLISHED.value}
)


async def _history_texts(tenant_id: UUID, draft_id: UUID) -> tuple[str, str]:
    """(«Ya probada» / «Por probar», its help) for the publication's page (m-24842981).
    A failed read hides the line — it never blocks the review."""
    try:
        count = await asyncio.to_thread(times_published, tenant_id, draft_id)
    except Exception as exc:  # noqa: BLE001 — an extra line, not the page
        logger.warning("draft history read failed: %s", type(exc).__name__)
        return "", ""
    if count is None:
        return "", ""
    return history_word(count), history_help(count)


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
        # stable through a reorder: what `assets/slide-drag.js` tells the slides apart by
        "uid": uuid4().hex[:8],
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
        # an animated slide's motion reference (§ 2026-10-19): followed, never shown
        "ref_key": "",
        "ref_name": "",
        # an animated slide with the sound the video model makes (§ 2026-10-23): off
        "audio": "",
    }


def _is_video_slide(slide: dict[str, str]) -> bool:
    """An animated slide, or a reused piece that is a video."""
    return slide.get("source") == "animated" or slide.get("media_type") == "video"


def _default_slides() -> list[dict[str, str]]:
    """What a new carousel opens on: no slides (§ request 2026-10-12 — it used to open
    on a generated cover and an animated slide). The operator adds each one from «+»;
    only the closing CTA slide is on by default."""
    return []


def _slide(draft: DraftVM | None, index: int) -> int:
    """`index` kept within the piece's slides."""
    last = len(draft.media) - 1 if draft is not None else 0
    return max(0, min(int(index), max(last, 0)))


#: Each category's title, as the kind picker shows it.
_CATEGORY_TITLES = {key: title for key, title, _, _ in CATEGORY_OPTIONS}


def generator_views(category: str, kind: str) -> list[str]:
    """The views (sections) of `category`/`kind`, in the order of the four steps
    (`generator_steps`, CREAR-2 m-24848530): what the piece shows (Avatar's types, the
    references, the presenter, the kind's own section), then what it says («topic», with
    «Datos clave» behind its «Más opciones»), then how it is published («channel», with
    «Campaña» behind its own «Más opciones»), and the «Resumen» where Crear is."""
    head = ["avatar_type"] if category == "video" else []
    # § request 2026-10-20: an avatar's reference video is asked in «Guion y fondo»,
    # not in a view of its own; «Ad» and Clip keep theirs
    if category in REFERENCE_CATEGORIES and category != "video":
        head.append("reference")
    own = [s for s in generator_sections(kind) if s not in ("topic", "channel")]
    return [*head, *own, "topic", "rules", "channel", "campaign", "summary"]


#: CREAR-2 (m-24848530): the wizard is four short steps — ① Qué mostrar ② Qué decir
#: ③ Cómo la quieres ④ Revisa y crea. Each view (section) belongs to one step; what a
#: kind cannot do without is always in step 1, never behind «Más opciones».
GENERATOR_STEPS = ("show", "say", "how", "review")
GENERATOR_STEP_LABELS = {
    "show": "Qué mostrar",
    "say": "Qué decir",
    "how": "Cómo la quieres",
    "review": "Revisa y crea",
}
_STEP_OF_VIEW = {
    "avatar_type": "show",
    "reference": "show",
    "presenter": "show",
    "details": "show",
    "topic": "say",
    # UX review: the price, a discount, what to say or avoid are what the piece says
    "rules": "say",
    "channel": "how",
    "campaign": "how",
    "summary": "review",
}
#: The optional views, each folded under its step's «Más opciones»: «Datos clave» in
#: step 2, «Campaña» in step 3.
OPTIONAL_VIEWS = ("rules", "campaign")
#: A summary row's view with this suffix lives behind step 1's «Más opciones» (an
#: avatar's reference video and brand resources).
SHOW_MORE_SUFFIX = ":more"


def generator_steps(category: str, kind: str) -> list[tuple[str, list[str]]]:
    """The steps of `category`/`kind`: `(step, its views)` in order. A step with no
    view for this kind (the creator's script shows nothing of its own) is skipped, so
    «Paso N de M» counts only real steps (N6)."""
    views = generator_views(category, kind)
    steps = [(step, [v for v in views if _STEP_OF_VIEW.get(v) == step]) for step in GENERATOR_STEPS]
    return [(step, step_views) for step, step_views in steps if step_views]


def generator_step_of(category: str, kind: str, view: str) -> int:
    """The index of the step that holds `view` (-1 when this kind has no such view)."""
    for index, (_step, views) in enumerate(generator_steps(category, kind)):
        if view in views:
            return index
    return -1


#: The step bar's label of each view; «details» is named after the kind.
_VIEW_LABELS = {
    "avatar_type": "Tipo de avatar",
    "reference": "Referencia",
    "topic": "Contexto",
    "channel": "Publicación",
    "presenter": "Presentador",
    "rules": "Datos clave",
    "campaign": "Campaña",
    "summary": "Resumen",
}
_DETAILS_LABELS = {
    "creator_script": "Guion",
    "static_flyer": "Anuncio",
    "template": "Fotos",
    "carousel": "Diapositivas",
}


def generator_view_label(view: str, kind: str) -> str:
    if kind == "clip" and view in ("reference", "details"):
        return "Referencias" if view == "reference" else "Fotogramas"
    if view == "details":
        return _DETAILS_LABELS.get(kind, "Guion y fondo")
    return _VIEW_LABELS.get(view, view)


def generator_sections(kind: str) -> list[str]:
    """The sections `kind` shows, in order. The ad image's context is its scene (§
    requests 2026-10-08/20: asked in «Contexto» like every other kind's). The gallery
    builds its slides before saying where it is published (§ request 2026-10-15)."""
    # § request 2026-10-20: the animated avatar has no «Presentador» view — its character
    # (and voice) are chosen right under «Avatar animado», in «Tipo de avatar»
    has_presenter = kind == "avatar_video"
    # the carousel says what it is about in «topic»; its slides are its details. A clip's
    # frames are applied from its references and a script's length is asked in
    # «Publicación» (§ 2026-10-14), so neither has a «details» view any more
    sections = [
        section
        for section in GENERATOR_SECTIONS
        if (section != "presenter" or has_presenter)
        and (section != "details" or kind not in ("clip", "creator_script"))
    ]
    if kind == "carousel":
        sections.remove("details")
        sections.insert(sections.index("channel"), "details")
    return sections


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


def _is_caption_rule(message: str) -> bool:
    """A brand rule about the publication's text: the raw fidelity message names the
    caption, the Spanish one («El texto de la publicación tiene…») names the text."""
    low = message.lower()
    return "caption" in low or "texto de la publicación" in low


def _pill_items(text: str) -> list[str]:
    """A newline-joined kit list as its non-empty, trimmed values."""
    return [line.strip() for line in text.splitlines() if line.strip()]


#: The lengths a script / avatar video can be asked for (§ request 2026-10-23: from 5 s);
#: the brief validates the same set (`qualify_creative.schemas.DURATIONS_SECONDS`).
DURATIONS = ("5", "10", "15", "30", "45", "60")
#: CREAR-5 (`pesos-creaciones-v2`, founder 2026-10-24): a presenter is offered and priced
#: at 5, 10, 15 and 30 s only; 45 and 60 s carry no weight and are never offered.
_PRESENTER_LENGTHS = (
    "Un video con presentador dura 5, 10, 15 o 30 segundos: elige una de esas duraciones."
)
_FORMAT_LABELS = {
    "feed_4_5": "Publicación 4:5",
    "feed_1_1": "Publicación cuadrada 1:1",
    "reels_9_16": "Reel (video corto) 9:16",
    "story_9_16": "Historia 9:16",
}
#: What the result view says while the piece is being made, per kind — generic, with
#: no vendor or model (§ request 2026-10-08).
_GEN_WAITING = {
    "creator_script": "Escribiendo tu guion…",
    "avatar_video": "Creando tu video. Puede tardar unos minutos…",
    "animated_avatar_video": "Creando tu video. Puede tardar unos minutos…",
    "static_flyer": "Creando tu imagen, ya casi está…",
    "template": "Creando tu publicación, ya casi está…",
    "carousel": "Armando tu galería. Si lleva un video, puede tardar unos minutos…",
}
_TEMPLATE_PHOTO_REQUIRED = (
    "Una plantilla trabaja sobre fotos reales: necesita al menos 2 (las del producto del "
    "catálogo cuentan)."
)
_CATALOG_ERROR = "No pudimos leer el catálogo. Puedes seguir subiendo tus fotos."
_STOCK_OFF = "La inspiración no está disponible ahora mismo."
#: The options a stock VIDEO chosen as the product cannot feed (§ request 2026-10-16:
#: «un pequeño pop up si se selecciona por ejemplo un flyer»), by panel option, with
#: what the popup says. The Clip takes it as a reference video and the Galería as a
#: slide; the script only needs the product's name.
_VIDEO_PRODUCT_OFF: dict[str, tuple[str, str]] = {
    "video": ("un video con avatar", "el presentador se compone con fotos"),
    "image": ("una imagen", "la imagen se arma con fotos"),
    "template": ("una plantilla", "la plantilla se arma con fotos de tu producto"),
    "ad": ("un anuncio", "el anuncio se arma con fotos de tu producto"),
}
_VIDEO_PRODUCT_FITS = "Úsalo en un Clip o en una Galería, o cambia el producto por una imagen."
_STOCK_NO_KIT = "Tu marca aún no dice qué vendes. Escribe qué buscas, por ejemplo «hamburguesa»."
_TEMPLATE_BLOCKED = "No podemos hacer esta publicación con plantilla: "
_GEN_POLL_SECONDS = 3.0
#: An AI avatar plus its render can take many minutes; the draft's reaper is 20.
_GEN_POLL_BUDGET_SECONDS = 20 * 60
_MAX_PRODUCTS = 10
_NOT_REJECTABLE = (
    "Esta publicación ya no se puede descartar: ya fue descartada o aprobada. "
    "Actualiza la página para ver su estado."
)
_DRAFT_GONE = "Esa publicación no existe o ya no es visible para este negocio."
_NOT_EDITABLE = (
    "Esta publicación ya no se puede editar: se está preparando, ya salió o falló. "
    "No se guardó ningún cambio."
)
_VARIANT_REQUIRED = "Elige una variante antes de aprobar."
_POLL_TIMEOUT = (
    "Lleva más de 5 minutos sin terminar. Vuelve en un rato: en Por aprobar verás cómo quedó."
)

#: §6.6 polling schedule: backoff 1s → 2s → 4s, cap 5s, give up at 5 minutes.
_POLL_DELAYS = (1.0, 2.0, 4.0)
_POLL_CAP_SECONDS = 5.0
_POLL_BUDGET_SECONDS = 300.0
#: m-24820142: a 1080p final is polled every few seconds, until it is settled or turns
#: retryable (`creative_provider.FINAL_POLL_WINDOW_SECONDS`: past the stale threshold).
_FINAL_POLL_SECONDS = 5.0
_FINAL_POLL_BUDGET_SECONDS = float(FINAL_POLL_WINDOW_SECONDS)

#: The generation stages the progress indicator names (§6.4: a real per-stage
#: indicator, not a blind spinner). The MVP pipeline generates copy, then verifies.
GENERATION_STAGES = ("Texto", "Imagen", "Revisión")


#: Where each of ¿Cómo suena?'s four axes starts — the middle.
TONE_DEFAULT = 50


def _video_conflict_text(category: str) -> str:
    """The popup's sentence for a stock video product on `category`."""
    label, reason = _VIDEO_PRODUCT_OFF[category]
    return f"Un video de inspiración no sirve para {label}: {reason}. {_VIDEO_PRODUCT_FITS}"


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
    #: CREAR-6: what is being typed into «Debe mencionar» / «Debe evitar» before
    #: «Agregar» turns it into a chip (the brief keeps the joined text above).
    brief_must_mention_draft: str = ""
    brief_must_avoid_draft: str = ""
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
    carousel_closing: bool = False
    #: The strip of thumbnails (§ 2026-10-09, option A): the slide being edited below
    #: it, and whether «+» is showing the three kinds of slide to add.
    carousel_selected: int = 0
    #: The gallery (§ 2026-10-14): the thumbnail being dragged, and why a change was
    #: refused (one video at most).
    carousel_drag_from: int = -1
    clip_drag_from: int = -1
    #: The clip's images AND videos in the operator's order (§ request 2026-10-19: «el
    #: drag and drop que incluya los videos y que se puedan poner como inicio y final»):
    #: their keys. The first opens the clip, the last closes it (`_sync_clip_frames`).
    clip_sequence: list[str] = []
    carousel_notice: str = ""
    carousel_adding: bool = False
    #: The brand's pieces' files (`creative_provider.brand_pieces`), read when «De una
    #: pieza» is first opened: `{key, media_type, label, view}`. Only a key in this list
    #: is accepted, and the producer checks it again against the brand's drafts.
    piece_items: list[dict[str, str]] = []
    piece_picker_open: bool = False
    pieces_loading: bool = False
    media_duration: str = "30"
    #: The presenter's length the owner last chose (m-24851829): preselected the next
    #: time a presenter is asked, when the month still pays for it ("" = none yet).
    presenter_duration: str = ""
    #: A clip's length, one of `CLIP_DURATIONS` (§ request 2026-10-23).
    clip_duration: str = "5"
    #: «Con audio» (§ request 2026-10-23): the clip comes with the sound the video
    #: model makes — on, as every clip was before the switch.
    clip_audio: bool = True
    #: The advertising image: the scene the image model will be asked for. Its photos
    #: (product, background) are optional since 2026-10-12 — the mode (`AdImageMode`)
    #: is derived from what was uploaded (`_ad_mode`), not picked.
    ad_scene_prompt: str = ""
    voice_id: str = ""
    avatar_source: str = "ai"
    avatar_prompt: str = ""
    avatar_image_key: str = ""
    avatar_image_name: str = ""
    avatar_rights_confirmed: bool = False
    #: The human presenter: a described woman or man (`_PRESENTERS`), or "custom" — a
    #: synthetic photoreal person described in `human_avatar_prompt`.
    human_avatar_mode: str = "female"
    human_avatar_prompt: str = ""
    #: Which voices the voice picker lists. Follows the presenter's gender on its own; for
    #: a custom or animated presenter the operator picks it.
    voice_gender: str = "female"
    #: The voices the presenter may read with (§ 2026-10-16, Seed Speech): the brand's own
    #: clone (`id` "brand", resolved server-side) and the public Spanish ones
    #: `{id, name, gender}`, read once when an avatar kind is first chosen.
    voice_options: list[dict[str, str]] = []
    voices_loading: bool = False
    voices_error: str = ""
    #: The operator's own script for a video (instead of Claude's), and the engine.
    own_script_on: bool = False
    own_script: str = ""
    #: Avatar video (m-24828920): subtitles of what the presenter says, burnt in with
    #: the brand's font and colours — the operator's choice.
    media_subtitles: bool = False
    #: Which vendor renders the avatar kinds ("omnihuman" | "seedance",
    #: `configured_video_engine`), read when an avatar kind is chosen. OmniHuman reads the
    #: script in a voice (picked); Seedance speaks it with its own (2.x) or not at all.
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
    _selected_product_video_keys: list[str] = []
    #: The catalog product's photos the operator took out of THIS piece (§ 2026-10-14:
    #: they are all in by default, and each one can be seen and unticked).
    catalog_off: list[str] = []
    # -- the product from stock (plan-integracion-stock R2, 2026-10-16): «Mi catálogo ·
    # Imagen de stock» on the product screen. The stock image only ILLUSTRATES the
    # product, for THIS piece: no catalog product is created.
    #: "catalog" | "stock" — what the piece's product photo is (the brief carries it).
    product_source: str = "catalog"
    #: The product screen's tab: "catalog" | "stock".
    product_tab: str = "catalog"
    #: Whether a stock bank is configured (a key in the env): read when the tab opens.
    stock_on: bool = True
    stock_query: str = ""
    #: The results on screen came from the Brand Kit's words, not from a typed search;
    #: the words that brought images, shown above them.
    stock_from_kit: bool = False
    stock_kit_words: list[str] = []
    #: Backend only: every word the kit suggested — what «Ver más» asks again.
    _stock_kit_queries: list[str] = []
    #: The public fields of each hit (thumbnail, author, provider) — never a download URL.
    stock_results: list[dict[str, str]] = []
    stock_page: int = 1
    stock_has_more: bool = False
    stock_loading: bool = False
    stock_error: str = ""
    #: The hits picked, in the order picked (§ request 2026-10-19: «que se pueda
    #: seleccionar varias opciones»): each "image|provider:id" or "video|provider:id" —
    #: an image and a video of one bank may share an id. Stock is inspiration, so it
    #: carries no product name (§ 2026-10-19: «eso se pondrá en las reglas»).
    stock_picks: list[str] = []
    #: Why the last pick did not go in (a limit), "" when it did.
    stock_pick_notice: str = ""
    stock_importing: bool = False
    #: An imported stock file → its `/r2media` thumbnail (stock lives in R2 only).
    stock_views: dict[str, str] = {}
    stock_asset_id: str = ""
    #: Backend only: the full hits THIS session's searches returned, by choice id — what
    #: an import may take; the browser only ever names one.
    _stock_items: dict[str, dict] = {}
    #: The chosen product is a stock "image" (it has at least one stock photo) or a stock
    #: "video" (only videos) — "" otherwise.
    stock_product_media: str = ""
    #: The imported stock videos of the product — key, poster view, author — so the Clip
    #: and the Galería can take them when they are chosen.
    _stock_product_videos: list[dict[str, str]] = []
    #: The popup's text when the chosen option cannot take the stock video ("" = closed).
    kind_conflict: str = ""
    #: The video playing inside its own tile, one at a time like «Descubrir reels» (§
    #: requests 2026-10-19: «sin ver un modal», «que no desplace el contenido»): a bank
    #: hit's id (`hit_playing`) or a slot file's key (`file_playing`) — two fields, so
    #: neither is told from the other by the shape of its id; at most one is set.
    hit_playing: str = ""
    file_playing: str = ""
    #: An imported stock video's key → its `/r2media` view (the mp4, to play it; the
    #: slots show its poster through `stock_views`).
    stock_video_views: dict[str, str] = {}
    #: Whether a previewed stock video plays with its sound (§ request 2026-10-19: the
    #: preview may be heard; the piece never takes a stock file's audio).
    preview_sound: bool = False
    #: The inspiration hit being imported into a slot (its id), "" when none.
    inspiration_importing: str = ""
    #: The slots whose folded «Inspiración» search the operator opened again («Buscar
    #: otra»): a slot holding inspiration folds its search away (§ request 2026-10-19).
    inspiration_reopened: list[str] = []
    #: Backend only: the inspiration files imported into slots this session — key →
    #: {name, media}: what `pick_media` accepts from «Inspiración».
    _inspiration_files: dict[str, dict[str, str]] = {}
    # -- the videos on «Stock» (§ request 2026-10-16/17): searched with the images
    vstock_query: str = ""
    vstock_results: list[dict[str, str]] = []
    vstock_page: int = 1
    vstock_has_more: bool = False
    vstock_loading: bool = False
    vstock_error: str = ""
    vstock_from_kit: bool = False
    vstock_kit_words: list[str] = []
    _vstock_items: dict[str, dict] = {}
    _vstock_kit_queries: list[str] = []
    #: Each media slot's source tab (`_PICKER_TABS`) — «Catálogo»/«Inspiración», «Subir»…
    picker_tabs: dict[str, str] = {}
    #: «Datos clave» (§ request 2026-10-14): what the piece must feature exactly — rows
    #: of {key, value}; the prompt gets them as one JSON object.
    brief_highlights: list[dict[str, str]] = []
    #: The panel's option (§ request 2026-10-06, renamed 2026-10-14): one of
    #: `GEN_CATEGORIES` — "video" is Clip, whose type is an avatar kind; "ad" is the
    #: template's video. `brief_kind` stays the real `ContentKind`.
    gen_category: str = "script"
    #: "create" = the chosen option's views; "discover" = the reels discovery (§ request
    #: 2026-10-14, QUA-223 §2), the panel's own button.
    gen_mode: str = "create"
    #: The step in front, an index into `generator_steps` (CREAR-2 m-24848530).
    gen_step: int = 0
    #: The catalog product screen comes first (§ request 2026-10-14: "antes de aparecer
    #: el lateral bar quiero poder seleccionar un producto del catálogo"): False until
    #: the operator continues with a product or without one.
    product_confirmed: bool = False
    #: Clip and Ad: a video the piece takes as its reference (§ request 2026-10-14).
    reference_video_key: str = ""
    reference_video_name: str = ""
    #: Clip (§ request 2026-10-14): its opening and closing frames, and its references —
    #: each item {key, name, source}, `source` "catalog" or "upload".
    clip_first_frame_key: str = ""
    clip_first_frame_name: str = ""
    clip_last_frame_key: str = ""
    clip_last_frame_name: str = ""
    clip_images: list[dict[str, str]] = []
    clip_videos: list[dict[str, str]] = []
    clip_audios: list[dict[str, str]] = []
    #: "result" once Generar created a piece: it shows below the form, on the same page
    #: (§ request 2026-10-08); "form" = nothing generated yet, or «Crear otro».
    generator_view: str = "form"
    #: «Más opciones» of step 2 («Datos clave») is folded until the operator opens it
    #: (CREAR-2).
    rules_open: bool = False
    #: «Más opciones» of step 3 («Campaña»), folded (CREAR-2).
    campaign_open: bool = False
    #: «Más opciones» of an avatar's step 1 (reference video, brand resources), folded.
    show_more_open: bool = False
    #: The carousel slide in view (§ request 2026-10-08): the generator's result, and
    #: the draft screen's.
    gen_slide: int = 0
    draft_slide: int = 0
    gen_draft_id: str = ""
    gen_draft: DraftVM | None = None
    #: Which variant the result view shows (index into `gen_draft.variants`).
    gen_variant: int = 0
    gen_timed_out: bool = False
    #: «Campaña» (m-24820838): the brand's campaigns, and the one the piece joins —
    #: `NO_CAMPAIGN` (an independent piece), a campaign id, or `NEW_CAMPAIGN` with the
    #: name and colour typed here. Applied to the draft once Generar created it.
    gen_campaigns: list[CampaignOptionVM] = []
    gen_campaign: str = NO_CAMPAIGN
    gen_campaign_new_name: str = ""
    gen_campaign_new_color: str = ""

    # -- /drafts ------------------------------------------------------------
    drafts: list[DraftSummaryVM] = []
    drafts_loading: bool = False
    drafts_error: str = ""

    # -- /drafts/[draft_id] -------------------------------------------------
    draft: DraftVM | None = None
    detail_loading: bool = False
    detail_error: str = ""
    # m-24842981: «Ya probada» / «Por probar» and its help on the publication's page
    # ("" while unknown — the page then shows nothing rather than a guess).
    draft_history_word: str = ""
    draft_history_help: str = ""
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
    # m-24842978: the owner just approved this draft on this screen — the decision bar
    # gives way to «Aprobada. Todavía no se publica.» and its way to Tu semana. Cleared
    # whenever a draft (re)loads, so it never claims a decision taken somewhere else.
    just_approved: bool = False
    # …and whether it can be given a day and time yet: an approved publication can still
    # be «aprobada pero no lista»; `approved_note` is why, in the evaluator's words.
    approved_ready: bool = True
    approved_note: str = ""
    action_error: str = ""
    poll_timed_out: bool = False
    poll_elapsed_label: str = ""
    _polling_draft_id: str = ""
    #: m-24820142: the draft whose 1080p final is being polled ("" = none).
    _final_polling_id: str = ""

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
        return [m for m in self.edit_blocking if _is_caption_rule(m)]

    @rx.var
    def other_blocking(self) -> list[str]:
        return [m for m in self.edit_blocking if not _is_caption_rule(m)]

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
            # founder 2026-10-24: approving counts the videos — not without enough left
            and not self.approve_videos_short
        )

    @rx.var
    def approve_label(self) -> str:
        """«Aprobar esta versión» over a Seedance 2.5 draft (m-24820142): approving it
        also orders its 1080p final."""
        draft = self.draft
        if draft is not None and draft.video_draft.state == VIDEO_DRAFT:
            return APPROVE_VERSION_LABEL
        return "Aprobar"

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
        return len(self.carousel_slides) >= _GALLERY_SLIDES

    # -- the gallery (§ request 2026-10-14) --------------------------------------------

    def _three_slides(self) -> list[dict[str, str]]:
        """A gallery opens on its three slides, each a generated scene with no photo yet
        (§ 2026-10-14, «quita las imágenes por defecto»): each one picks its own among
        the catalog product's photos."""
        slides = [_new_slide("generated") for _ in range(_GALLERY_SLIDES)]
        # the title (the hook) opens the gallery: the first slide is what the feed shows
        slides[0]["text"] = "hook"
        return slides

    def _video_slides(self, *, besides: int = -1) -> int:
        return sum(
            1
            for index, slide in enumerate(self.carousel_slides)
            if index != besides and _is_video_slide(slide)
        )

    @rx.var
    def carousel_video_taken(self) -> bool:
        """Another slide already is the gallery's one video."""
        return self._video_slides(besides=self._carousel_index()) >= _GALLERY_MAX_VIDEOS

    @rx.event
    def set_slide_source(self, source: str) -> rx.event.EventSpec | None:
        """The open slide's kind: a generated scene, that scene animated (the gallery's
        one video), or a piece the brand already made (chosen in the picker)."""
        index = self._carousel_index()
        if index < 0:
            return None
        if source == "existing":
            self.piece_picker_open = True
            if not self.piece_items and not self.pieces_loading:
                return CreativeState.load_brand_pieces
            return None
        if source not in _SLIDE_SOURCES:
            return None
        if source == "animated" and self.carousel_video_taken:
            self.carousel_notice = _GALLERY_ONE_VIDEO
            return None
        current = self.carousel_slides[index]
        slide = _new_slide(source)
        slide["uid"] = current.get("uid") or slide["uid"]
        if current["source"] not in ("existing", "stock"):
            slide.update(
                {
                    field: current.get(field, slide[field])
                    for field in (
                        "scene",
                        "photo_key",
                        "photo_name",
                        "background",
                        "text",
                        "ref_key",
                        "ref_name",
                        "audio",
                    )
                }
            )
            if source != "animated":
                slide["audio"] = ""  # only the video has sound of its own
        slides = [dict(s) for s in self.carousel_slides]
        slides[index] = slide
        self.carousel_slides = slides
        self.piece_picker_open = False
        self.carousel_notice = ""
        return None

    @rx.event
    def start_slide_drag(self, index: int) -> None:
        """A thumbnail lifted (HTML5 drag and drop): which one moves."""
        self.carousel_drag_from = int(index)

    @rx.event
    def drop_slide(self, index: int) -> None:
        """Dropped on another thumbnail: the lifted slide takes its place; the editor
        follows it."""
        start, target = self.carousel_drag_from, int(index)
        self.carousel_drag_from = -1
        slides = list(self.carousel_slides)
        if start == target or not (0 <= start < len(slides) and 0 <= target < len(slides)):
            return
        slides.insert(target, slides.pop(start))
        self.carousel_slides = slides
        self.carousel_selected = target

    @rx.var
    def carousel_slide_rows(self) -> list[dict[str, str]]:
        """The strip's thumbnails: each row with its 1-based number, whether it is the one
        being edited and what its text label says."""
        selected = self._carousel_index()
        rows: list[dict[str, str]] = []
        for index, slide in enumerate(self.carousel_slides):
            row = dict(slide)
            row["n"] = str(index + 1)
            row["uid"] = slide.get("uid") or str(index)
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
        # a slide made before «Con audio» (2026-10-23) reads as silent, not undefined
        row.setdefault("audio", "")
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
            "text": (*_SLIDE_TEXTS, "cta"),
            "seconds": SLIDE_SECONDS,
            "audio": ("1", ""),
        }
        index = int(index)
        if field not in allowed or not 0 <= index < len(self.carousel_slides):
            return
        value = str(value)
        if field == "scene":
            value = value[:600]
        elif value not in allowed[field]:  # type: ignore[operator]
            return
        source = self.carousel_slides[index]["source"]
        if source == "existing":
            return  # a reused piece goes as it is
        if source == "stock":
            # a stock video always carries words: the title, or else the CTA button
            if field != "text":
                return
            value = value if value in ("hook", "cta") else "cta"
        elif value == "cta" and field == "text":
            return  # not offered on a generated slide: its scene holds the button
        if field == "audio" and value and source != "animated":
            return  # only the gallery's video has sound of its own (§ 2026-10-23)
        self._replace_slide(index, **{field: value})
        if field == "text" and value == "hook":
            # the title is the same hook on every slide: it goes on one only (2026-10-14)
            slides = [dict(slide) for slide in self.carousel_slides]
            for other, slide in enumerate(slides):
                if other != index and slide.get("text") == "hook":
                    slide["text"] = "cta" if slide.get("source") == "stock" else "none"
            self.carousel_slides = slides

    @rx.event
    def toggle_slide_title(self, index: int) -> None:
        """The title switch of a slide: on here (and off on the others), or off."""
        index = int(index)
        if 0 <= index < len(self.carousel_slides):
            on = self.carousel_slides[index].get("text") != "hook"
            self.set_slide_field(index, "text", "hook" if on else "none")

    @rx.event
    def toggle_slide_background(self, index: int) -> None:
        index = int(index)
        if 0 <= index < len(self.carousel_slides):
            current = self.carousel_slides[index].get("background", "1")
            self.set_slide_field(index, "background", "" if current else "1")

    @rx.event
    def toggle_slide_audio(self, index: int) -> None:
        """«Con audio» on the animated slide (§ request 2026-10-23): its video comes with
        the sound the video model makes for it."""
        index = int(index)
        if 0 <= index < len(self.carousel_slides):
            current = self.carousel_slides[index].get("audio", "")
            self.set_slide_field(index, "audio", "" if current else "1")

    @rx.event
    async def handle_slide_reference_upload(self, files: list[rx.UploadFile]) -> None:
        """The motion reference of the animated slide open in the editor (§ request
        2026-10-19): one video; a new one replaces it."""
        index = self._carousel_index()
        if index < 0 or self.carousel_slides[index]["source"] != "animated":
            return
        saved = await self._save_uploads(files[:1])
        if saved:
            key, name = saved[0]
            self._replace_slide(index, ref_key=key, ref_name=name)

    @rx.event
    def clear_slide_reference(self) -> None:
        index = self._carousel_index()
        if index >= 0:
            self._replace_slide(index, ref_key="", ref_name="")

    @rx.event
    async def handle_slide_photo_upload(self, files: list[rx.UploadFile]) -> None:
        """The product photo of the slide open in the editor (§ 2026-10-09: uploaded in
        the slide itself). One photo per slide; a new one replaces it."""
        index = self._carousel_index()
        if index < 0 or self.carousel_slides[index]["source"] in ("existing", "stock"):
            return
        saved = await self._save_uploads(files[:1])
        if saved:
            key, name = saved[0]
            self._replace_slide(index, photo_key=key, photo_name=name)

    @rx.event
    def set_slide_photo_from_catalog(self, key: str) -> None:
        """The open slide's photo, picked among the catalog product's — only those.
        Picking the one it already has takes it off (the scene from its words alone)."""
        index = self._carousel_index()
        if index < 0 or key not in self._selected_product_photo_keys:
            return
        slide = self.carousel_slides[index]
        if slide["source"] in ("existing", "stock"):
            return
        if slide.get("photo_key") == key:
            self._replace_slide(index, photo_key="", photo_name="")
        else:
            self._replace_slide(index, photo_key=key, photo_name=_CATALOG_PHOTO)

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
        """A file of one of the brand's pieces as the open slide (§ 2026-10-14: the
        gallery's three slides change kind, they are not added) — a video only while no
        other slide is the gallery's one video."""
        item = next((item for item in self.piece_items if item.get("key") == key), None)
        if item is None:
            return
        index = self._carousel_index()
        if item.get("media_type") == "video" and (
            self._video_slides(besides=index) >= _GALLERY_MAX_VIDEOS
        ):
            self.carousel_notice = _GALLERY_ONE_VIDEO
            return
        slide = _new_slide("generated")
        slide.update(
            source="existing",
            key=item["key"],
            label=item.get("label", ""),
            view=item.get("view", ""),
            media_type=item.get("media_type", "image"),
        )
        slides = [dict(s) for s in self.carousel_slides]
        if index >= 0:
            slide["uid"] = slides[index].get("uid") or slide["uid"]
        if index < 0:
            slides.append(slide)
            index = len(slides) - 1
        else:
            slides[index] = slide
        self.carousel_slides = slides
        self.carousel_selected = index
        self.piece_picker_open = False
        self.carousel_adding = False
        self.carousel_notice = ""

    def _carousel_slides_payload(self, background: bool) -> tuple[list[str], list[dict]]:
        """The editor rows as `CarouselSlide` fields, and the product photos they point
        at (`MediaInputs.product_keys`, each slide's own, deduplicated in order)."""
        photos: list[str] = []
        out: list[dict] = []
        for slide in self.carousel_slides:
            if slide["source"] == "existing":
                out.append({"source": "existing", "object_key": slide["key"]})
                continue
            if slide["source"] == "stock":
                text = slide.get("text") if slide.get("text") in ("hook", "cta") else "cta"
                out.append({"source": "stock", "object_key": slide["key"], "text": text})
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
                    # only an animated slide follows a motion reference (2026-10-19)
                    **(
                        {
                            "reference_video_key": slide.get("ref_key") or None,
                            "audio": bool(slide.get("audio")),
                        }
                        if slide["source"] == "animated"
                        else {}
                    ),
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
        if kind is ContentKind.TEMPLATE:
            formats = _TEMPLATE_FORMATS["video" if self.gen_category == "ad" else "template"]
        elif kind is ContentKind.STATIC_FLYER:
            formats = _FLYER_FORMATS
        else:
            formats = kind.formats
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
    def gen_views(self) -> list[str]:
        """The views of the chosen option, in order (`generator_views`)."""
        return generator_views(self.gen_category, self.brief_kind)

    def _gen_steps(self) -> list[tuple[str, list[str]]]:
        return generator_steps(self.gen_category, self.brief_kind)

    def _view_index(self) -> int:
        """The step in front (`gen_step` kept within the kind's steps)."""
        return min(max(self.gen_step, 0), len(self._gen_steps()) - 1)

    @rx.var
    def gen_step_key(self) -> str:
        """The step in front: "show", "say", "how" or "review" (`GENERATOR_STEPS`)."""
        return self._gen_steps()[self._view_index()][0]

    @rx.var
    def gen_step_views(self) -> list[str]:
        """The views the step in front stacks, in order."""
        return self._gen_steps()[self._view_index()][1]

    @rx.var
    def gen_view(self) -> str:
        """The first view of the step in front."""
        return self._gen_steps()[self._view_index()][1][0]

    @rx.var
    def gen_step_count(self) -> str:
        """«Paso N de M» (N6): M counts only this kind's real steps."""
        return f"Paso {self._view_index() + 1} de {len(self._gen_steps())}"

    @rx.var
    def gen_view_steps(self) -> list[dict[str, str]]:
        """The step bar: each step's index, label and whether it is done or current."""
        current = self._view_index()
        return [
            {
                "index": str(index),
                "number": str(index + 1),
                "label": GENERATOR_STEP_LABELS[step],
                "done": "true" if index < current else "",
                "current": "true" if index == current else "",
            }
            for index, (step, _views) in enumerate(self._gen_steps())
        ]

    @rx.var
    def gen_is_first_view(self) -> bool:
        return self._view_index() == 0

    @rx.var
    def gen_is_last_view(self) -> bool:
        return self._view_index() == len(self._gen_steps()) - 1

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
        catalog product's still ticked, deduplicated."""
        catalog = [k for k in self._selected_product_photo_keys if k not in self.catalog_off]
        return len(set(self.media_product_keys) | set(catalog))

    def _catalog_photos_in(self) -> list[str]:
        """The catalog product's photos this piece uses: all but those unticked."""
        return [k for k in self._selected_product_photo_keys if k not in self.catalog_off]

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
        return _GEN_WAITING.get(self.gen_kind, "Creando…")

    @rx.var
    def video_on_seedance(self) -> bool:
        return self.video_engine == "seedance"

    @rx.var
    def gen_failure_label(self) -> str:
        """The precise reason when the media step gave one (a vendor without credit…),
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
    def visible_voices(self) -> list[dict[str, str]]:
        """The listed gender's voices — plus the brand's own clone, always."""
        return [
            voice
            for voice in self.voice_options
            if voice.get("own") == "1" or voice.get("gender") == self.voice_gender
        ]

    @rx.var
    def video_reads_with_voice(self) -> bool:
        """OmniHuman: the script is read in a voice the operator picks (§ 2026-10-16)."""
        return self.video_engine == "omnihuman"

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

    @rx.var
    def brief_must_mention_items(self) -> list[str]:
        """CREAR-6: «Debe mencionar» as chips."""
        return phrase_list(self.brief_must_mention)

    @rx.var
    def brief_must_avoid_items(self) -> list[str]:
        """CREAR-6: «Debe evitar» as chips."""
        return phrase_list(self.brief_must_avoid)

    @rx.event
    def set_brief_must_mention_draft(self, value: str) -> None:
        self.brief_must_mention_draft = value

    @rx.event
    def set_brief_must_avoid_draft(self, value: str) -> None:
        self.brief_must_avoid_draft = value

    def _flush_phrase_drafts(self) -> None:
        """CREAR-6 (UX review): a phrase typed but never «Agregar»-ed still counts —
        flushed before anything reads «Debe mencionar» / «Debe evitar» (the summary,
        «Potenciar con IA», Generar), so it is never lost without a word."""
        self.brief_must_mention = add_phrase(self.brief_must_mention, self.brief_must_mention_draft)
        self.brief_must_mention_draft = ""
        self.brief_must_avoid = add_phrase(self.brief_must_avoid, self.brief_must_avoid_draft)
        self.brief_must_avoid_draft = ""

    @rx.event
    def add_must_mention_on_key(self, key: str) -> None:
        """The keyboard's Intro / «Listo» in «Debe mencionar» adds the phrase."""
        if key == "Enter":
            self.brief_must_mention = add_phrase(
                self.brief_must_mention, self.brief_must_mention_draft
            )
            self.brief_must_mention_draft = ""

    @rx.event
    def add_must_avoid_on_key(self, key: str) -> None:
        """The keyboard's Intro / «Listo» in «Debe evitar» adds the phrase."""
        if key == "Enter":
            self.brief_must_avoid = add_phrase(self.brief_must_avoid, self.brief_must_avoid_draft)
            self.brief_must_avoid_draft = ""

    @rx.event
    def add_must_mention(self) -> None:
        self.brief_must_mention = add_phrase(self.brief_must_mention, self.brief_must_mention_draft)
        self.brief_must_mention_draft = ""

    @rx.event
    def add_must_avoid(self) -> None:
        self.brief_must_avoid = add_phrase(self.brief_must_avoid, self.brief_must_avoid_draft)
        self.brief_must_avoid_draft = ""

    @rx.event
    def remove_must_mention(self, phrase: str) -> None:
        self.brief_must_mention = remove_phrase(self.brief_must_mention, phrase)

    @rx.event
    def remove_must_avoid(self, phrase: str) -> None:
        self.brief_must_avoid = remove_phrase(self.brief_must_avoid, phrase)

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
        try:
            campaigns = await asyncio.to_thread(brand_campaign_options, tenant_id, brand_id)
        except Exception as exc:  # the piece can still be independent, or a new campaign's
            logger.warning("brand campaigns unreadable: %s", type(exc).__name__)
            campaigns = None
        async with self:
            self.readiness = verdict
            # N4 (m-24842973): back on /create (from «Agregar producto») the route the
            # owner had open stays open; only a first visit takes the type's default.
            returning = bool(self.route_options)
            self.route_options = list(options)
            enabled = {opt.key for opt in self.route_options if opt.enabled}
            if not (returning and self.selected_route in enabled):
                self._select_default_route()
            self.kit_voice_missing = voice_missing
            self.brand_media_items = assets
            if campaigns is not None:
                self._set_gen_campaigns(campaigns)
            self.create_loading = False
        await self._refresh_creations(tenant_id, brand_id)

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
        """The flag's "Configurar voz": «Tu marca» shows «Mejora tu marca (opcional)»
        first while the voice is still to prepare (`brand_kit_editor.needs_voice`)."""
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
        """Within Clip, which type is chosen; "ad_video" for «Ad» (the template's Reel);
        "" otherwise."""
        if self.gen_category == "ad":
            return "ad_video"
        if self.gen_category != "video":
            return ""
        return self.brief_kind

    @rx.var
    def gen_kind_label(self) -> str:
        """What the piece is called on «¿Todo listo?»: the clip type within Clip."""
        if self.gen_category in ("video", "ad"):
            return VIDEO_TYPE_LABELS.get(self.video_type, "")
        return KIND_LABELS.get(self.brief_kind, "")

    @rx.event
    def choose_category(self, category: str) -> _Events:
        """One option of the panel. Clip opens on its first type unless one of its types
        is already chosen. Another option starts on its first view, with a finished
        piece's result put away (it is in Borradores)."""
        if category not in GEN_CATEGORIES:
            return None
        if self._video_product_conflict(category):
            return None
        self.gen_mode = "create"
        if category == self.gen_category and (
            category != "video" or self.video_type in VIDEO_TYPES
        ):
            return _with_scroll(None)
        if not self.gen_generating:
            self._back_to_form()
        self.gen_category = category
        self.gen_step = 0
        return _with_scroll(self._set_kind(_CATEGORY_KIND[category]))

    @rx.event
    def choose_video_type(self, video_type: str) -> _Events:
        """Avatar humano · Avatar animado — the first view of Avatar."""
        if video_type not in VIDEO_TYPES:
            return None
        if self._video_product_conflict("video"):
            return None
        self.gen_mode = "create"
        self.gen_category = "video"
        return self._set_kind(video_type)

    @rx.event
    def open_discover(self) -> rx.event.EventSpec:
        """The panel's «Descubrir ideas de videos» (ex «Descubrir reels»)."""
        self.gen_mode = "discover"
        return _scroll_to_view()

    @rx.event
    def open_variations(self) -> rx.event.EventSpec:
        """The panel's «Variaciones» (m-24803289): ten visual angles of one catalog
        product. Its own state (`VariationsState`) owns the flow; this only puts the
        centre in that mode."""
        self.gen_mode = "variations"
        return _scroll_to_view()

    # -- a stock video as the product: where it fits (§ request 2026-10-16) -------------

    def _video_product_conflict(self, category: str) -> bool:
        """True (and the popup open) when the product is a stock video and `category`
        cannot take one; the option is then not switched."""
        if self.stock_product_media != "video" or category not in _VIDEO_PRODUCT_OFF:
            return False
        self.kind_conflict = _video_conflict_text(category)
        return True

    @rx.event
    def close_kind_conflict(self) -> None:
        self.kind_conflict = ""

    @rx.event
    def set_kind_conflict_open(self, value: bool) -> None:
        if not value:
            self.kind_conflict = ""

    @rx.event
    def resolve_kind_conflict(self, choice: str) -> rx.event.EventSpec | None:
        """The popup's buttons: «Usar en un Clip» / «Usar en una Galería» switch the
        option; «Cambiar el producto» goes back to «Stock · Imágenes»."""
        self.kind_conflict = ""
        if choice in ("clip", "carousel"):
            return CreativeState.choose_category(choice)
        if choice == "product":
            self.product_confirmed = False
            self.product_tab = "stock"
            return CreativeState.set_product_tab("stock")
        return None

    # -- the clip (§ request 2026-10-14) ----------------------------------------------

    @rx.var
    def product_photo_keys(self) -> list[str]:
        """The catalog product's photos — what a clip can take as a frame or reference."""
        return list(self._selected_product_photo_keys)

    # -- the media pickers (§ request 2026-10-14) ----------------------------------------
    # «en todas partes se pueda ver y seleccionar lo que venga del catálogo, importarlo
    # a mano y/o desde las piezas ya creadas»: each slot that takes a file has the same
    # three tabs. Uploads keep their own handlers; the catalog and the pieces go
    # through `pick_media`, which only places a key the session itself listed.

    @rx.var
    def product_video_keys(self) -> list[str]:
        return list(self._selected_product_video_keys)

    @rx.var
    def product_chip_key(self) -> str:
        """The picture beside the product's name: its photo, or a stock video's poster
        (`piece_views` maps the video's key to it)."""
        if self.selected_product_photo_key:
            return self.selected_product_photo_key
        if self.stock_product_media == "video" and self._selected_product_video_keys:
            return self._selected_product_video_keys[0]
        return ""

    @rx.var
    def piece_images(self) -> list[dict[str, str]]:
        return [item for item in self.piece_items if item.get("media_type") == "image"]

    @rx.var
    def piece_videos(self) -> list[dict[str, str]]:
        return [item for item in self.piece_items if item.get("media_type") == "video"]

    @rx.var
    def piece_views(self) -> dict[str, str]:
        """A piece's file → its `/r2media` thumbnail: a piece lives in R2, not in the
        upload store, so this is how a slot shows one it took."""
        views = {item["key"]: item.get("view", "") for item in self.piece_items}
        # an imported stock file lives in R2 too (plan-integracion-stock R2)
        return {**self.stock_views, **views}

    @rx.var
    def picker_tab_view(self) -> dict[str, str]:
        """Each slot's open tab: the one picked, else «Catálogo» when the catalog
        product has files of the slot's type, else «Subir»."""
        tabs: dict[str, str] = {}
        for target, (media_type, _multiple) in _PICKER_TARGETS.items():
            photos, videos = self._selected_product_photo_keys, self._selected_product_video_keys
            catalog = {"image": photos, "video": videos}.get(media_type, [*photos, *videos])
            chosen = self.picker_tabs.get(target, "")
            if chosen == "brandcat" and self.product_source != "stock":
                chosen = ""  # the tab only exists beside a stock inspiration
            if chosen == "inspiration" and not self._inspiration_allowed(target):
                chosen = ""  # only where the licence lets stock go
            if chosen == "inspiration" and self.product_source == "stock":
                chosen = "catalog"  # a stock product's «Inspiración» is its picks
            stock = self.product_source == "stock"
            if target in _NO_CATALOG_TARGETS:
                if chosen in ("catalog", "brandcat") and not stock:
                    chosen = ""
                catalog = catalog if stock else []
            default = "catalog" if catalog else "upload"
            tabs[target] = chosen if chosen in _PICKER_TABS else default
        return tabs

    @rx.var
    def picker_selected(self) -> dict[str, list[str]]:
        """What each slot holds now — the tiles of its tabs show it ticked."""
        slides = self.carousel_slides
        index = max(0, min(self.carousel_selected, len(slides) - 1))
        current = slides[index] if slides else {}
        # a slide holds a photo, or an inspiration video (a stock slide's `key`)
        slide = current.get("photo_key", "") or (
            current.get("key", "") if current.get("source") == "stock" else ""
        )
        catalog = [k for k in self._selected_product_photo_keys if k not in self.catalog_off]
        return {
            "products": [*self.media_product_keys, *catalog],
            "reference": [self.reference_video_key],
            "clip_images": [item["key"] for item in self.clip_images],
            "clip_videos": [item["key"] for item in self.clip_videos],
            "slide": [slide],
            "background": [self.media_background_key],
            "slide_reference": [current.get("ref_key", "")],
            "slide_media": [current.get("photo_key", ""), current.get("ref_key", "")],
        }

    @rx.var
    def product_previews(self) -> list[dict[str, str]]:
        """The product photos the piece uses, as pictures: its own (uploaded or from a
        piece) and the catalog product's still ticked."""
        own = [
            {"key": key, "name": name, "source": "own"}
            for key, name in zip(self.media_product_keys, self.media_product_names, strict=False)
        ]
        catalog = [
            {"key": key, "name": _CATALOG_PHOTO, "source": "catalog"}
            for key in self._selected_product_photo_keys
            if key not in self.catalog_off and key not in self.media_product_keys
        ]
        return [*own, *catalog]

    @rx.event
    def remove_product_preview(self, key: str) -> None:
        """✕ on a product picture: one of the piece's own goes; a catalog one is
        unticked (it stays in the catalog tab)."""
        if key in self.media_product_keys:
            self._drop_product(key)
        elif key in self._selected_product_photo_keys and key not in self.catalog_off:
            self.catalog_off = [*self.catalog_off, key]

    @rx.event
    def set_picker_tab(self, target: str, tab: str) -> list | rx.event.EventSpec | None:
        if target not in _PICKER_TARGETS or tab not in _PICKER_TABS:
            return None
        if target in _NO_CATALOG_TARGETS and tab == "brandcat":
            return None
        if tab == "brandcat" and self.product_source != "stock":
            return None  # with a catalog product, «Catálogo» already is the catalog
        if tab == "inspiration" and not self._inspiration_allowed(target):
            return None
        self.picker_tabs = {**self.picker_tabs, target: tab}
        self._stop_playing()
        # the kit searches feed the «Inspiración» search: a catalog product's slots, and
        # the background beside a stock product (§ 2026-10-19: the other slots of a
        # stock product keep to its picks)
        stock_background = target == "background" and self.product_source == "stock"
        if tab == "inspiration" or (tab == "catalog" and stock_background):
            searches = self._inspiration_searches()
            if searches:
                return searches
        if tab == "pieces" and not self.piece_items and not self.pieces_loading:
            return CreativeState.load_brand_pieces
        if tab == "brandcat" and not self.catalog_items and not self.catalog_loading:
            return CreativeState.load_catalog_products
        return None

    def _inspiration_allowed(self, target: str) -> bool:
        """Whether `target`'s picker may search inspiration (`_INSPIRATION_TARGETS`)."""
        return target in _INSPIRATION_TARGETS

    @rx.var
    def inspiration_targets(self) -> list[str]:
        return [t for t in _PICKER_TARGETS if self._inspiration_allowed(t)]

    def _inspiration_searches(self) -> list:
        """The Brand Kit searches still to run for the inspiration grids (each bank the
        first time only, as on the product screen)."""
        try:
            self.stock_on = stock_available()
        except Exception:  # noqa: BLE001 — a check must not break the screen
            self.stock_on = False
        if not self.stock_on:
            return []
        searches = []
        if not self.stock_results and not self.stock_loading:
            searches.append(CreativeState.search_stock_from_kit)
        if not self.vstock_results and not self.vstock_loading:
            searches.append(CreativeState.search_stock_videos_from_kit)
        return searches

    @rx.var
    def inspiration_held(self) -> list[str]:
        """The slots already holding a file taken from inspiration: their search folds
        away until «Buscar otra» (§ request 2026-10-19: «que no aparezca de nuevo el
        discovery») — never the background's, which keeps its search."""
        return [
            target
            for target, keys in self.picker_selected.items()
            if target != "background" and any(is_stock_key(key) for key in keys if key)
        ]

    @rx.event
    def reopen_inspiration(self, target: str) -> None:
        if target in _PICKER_TARGETS and target not in self.inspiration_reopened:
            self.inspiration_reopened = [*self.inspiration_reopened, target]

    @rx.event
    def toggle_preview_sound(self) -> None:
        self.preview_sound = not self.preview_sound

    @rx.event(background=True)
    async def use_inspiration_hit(self, target: str, choice_id: str, media: str) -> None:
        """A hit of a slot's «Inspiración» search into the slot: copied to R2 with its
        provenance (a backend download — never a URL the browser chose; an image as it
        is, a video ≤ 15 s without its audio) and picked like any file of the slot. Only
        a hit this session listed, only where the licence lets stock go."""
        async with self:
            spec = _PICKER_TARGETS.get(target)
            video = media == "video"
            if self.inspiration_importing or spec is None or spec[0] not in (media, "mixed"):
                return
            if media not in ("image", "video"):
                return
            if not self._inspiration_allowed(target):
                return
            item = (self._vstock_items if video else self._stock_items).get(choice_id)
            if item is None:
                return
            query = self.stock_query or " ".join(
                self.vstock_kit_words if video else self.stock_kit_words
            )
            self.inspiration_importing = choice_id
            self.stock_error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.inspiration_importing = ""
                self.stock_error = _STOCK_OFF
            return
        tenant_id, brand_id, user_id = ids
        importer = import_stock_video if video else import_stock_image
        try:
            imported = await asyncio.to_thread(
                lambda: importer(tenant_id, brand_id, user_id, item, query=query)
            )
        except StockUnavailable as exc:
            async with self:
                self.inspiration_importing = ""
                self.stock_error = str(exc.args[0]) if exc.args else _STOCK_OFF
            return
        except Exception as exc:  # noqa: BLE001 — DB, R2, the encoder: say so
            logger.warning("inspiration import failed: %s", type(exc).__name__)
            async with self:
                self.inspiration_importing = ""
                self.stock_error = _STOCK_OFF
            return
        async with self:
            self.inspiration_importing = ""
            self._add_inspiration_file(imported, media)
            # a mixed slot (an animated slide) puts it in the slot of its type
            self._pick(
                _MIXED_SLOTS.get(target, {}).get(media, target), "inspiration", imported["key"]
            )
            # picked: the search folds away again
            self.inspiration_reopened = [t for t in self.inspiration_reopened if t != target]

    def _add_inspiration_file(self, imported: dict[str, str], media: str) -> None:
        key = imported["key"]
        author = imported.get("author") or imported.get("provider_label", "")
        poster = imported.get("poster_view") or imported.get("view", "")
        self.stock_views = {**self.stock_views, key: poster}
        if media == "video" and imported.get("view"):
            self.stock_video_views = {**self.stock_video_views, key: imported["view"]}
        self._inspiration_files = {
            **self._inspiration_files,
            key: {"name": f"{_INSPIRATION} · {author}", "media": media},
        }

    def _brand_catalog_files(self, field: str) -> list[dict[str, str]]:
        files: list[dict[str, str]] = []
        for item in self.catalog_items:
            for key in item.get(field, "").split("\n"):
                if key and not any(f["key"] == key for f in files):
                    files.append({"key": key, "name": item.get("name", "") or "Catálogo"})
        return files

    @rx.var
    def brand_catalog_photos(self) -> list[dict[str, str]]:
        """Every photo of the brand's catalog, with its product's name — what the
        «Catálogo» tab offers when the piece's product is stock inspiration (§ request
        2026-10-19: «una opción para importar desde el catálogo»)."""
        return self._brand_catalog_files("photo_keys")

    @rx.var
    def brand_catalog_videos(self) -> list[dict[str, str]]:
        return self._brand_catalog_files("video_keys")

    def _pickable(self, source: str, key: str, media_type: str) -> str | None:
        """The name a picked file goes by — None for a key the session did not list as
        the catalog product's or as one of the brand's pieces of that type."""
        if source == "catalog":
            stock = self.product_source == "stock"
            if media_type == "image" and key in self._selected_product_photo_keys:
                return _INSPIRATION if stock else _CATALOG_PHOTO
            if media_type == "video" and key in self._selected_product_video_keys:
                return _INSPIRATION if stock else "Video del catálogo"
            return None
        if source == "inspiration":
            item = self._inspiration_files.get(key)
            return item["name"] if item is not None and item["media"] == media_type else None
        if source == "brandcat":
            field = "photo_keys" if media_type == "image" else "video_keys"
            files = self._brand_catalog_files(field)
            item = next((f for f in files if f["key"] == key), None)
            return item["name"] if item is not None else None
        if source == "pieces":
            item = next((i for i in self.piece_items if i.get("key") == key), None)
            if item is not None and item.get("media_type") == media_type:
                return item.get("label") or "Publicación"
        return None

    @rx.event
    def pick_media(self, target: str, source: str, key: str) -> None:
        """A file of the catalog product or of one of the brand's pieces into a slot —
        a slot of one file takes it (the same one again takes it out), a slot of
        several adds it or takes it out."""
        self._pick(target, source, key)

    @rx.event
    def pick_mixed_media(self, target: str, source: str, key: str, media: str) -> None:
        """A file of a mixed slot's picker (§ request 2026-10-20: an animated slide shows
        images and videos together): it goes to the slot of its type — an image is the
        slide's photo, a video its motion reference."""
        slot = _MIXED_SLOTS.get(target, {}).get(media)
        if slot is not None:
            self._pick(slot, source, key)

    @rx.event
    async def handle_slide_media_upload(self, files: list[rx.UploadFile]) -> None:
        """The animated slide's one drop zone (§ request 2026-10-20): an image becomes its
        photo, a video its motion reference — one of each; a new one replaces it."""
        from qualify_creative.video import is_video_filename  # noqa: PLC0415 — as the provider

        index = self._carousel_index()
        if index < 0 or self.carousel_slides[index]["source"] != "animated":
            return
        images = [f for f in files if not is_video_filename(f.name or "")]
        videos = [f for f in files if is_video_filename(f.name or "")]
        saved = await self._save_uploads([*images[:1], *videos[:1]])
        if saved and (len(images) > 1 or len(videos) > 1):
            self.upload_error = _SLIDE_MEDIA_EXTRA
        for key, name in saved:
            if is_video_filename(name):
                self._replace_slide(index, ref_key=key, ref_name=name)
            else:
                self._replace_slide(index, photo_key=key, photo_name=name)

    def _pick(self, target: str, source: str, key: str) -> None:
        spec = _PICKER_TARGETS.get(target)
        if spec is None:
            return
        name = self._pickable(source, key, spec[0])
        if name is None:
            return
        if target == "products":
            if source == "catalog":
                off = self.catalog_off
                self.catalog_off = [k for k in off if k != key] if key in off else [*off, key]
            elif key in self.media_product_keys:
                self._drop_product(key)
            elif len(self.media_product_keys) < _MAX_PRODUCTS:
                self.media_product_keys = [*self.media_product_keys, key]
                self.media_product_names = [*self.media_product_names, name]
        elif target == "reference":
            held = ("", "") if self.reference_video_key == key else (key, name)
            self.reference_video_key, self.reference_video_name = held
        elif target in ("clip_images", "clip_videos"):
            items = self.clip_images if target == "clip_images" else self.clip_videos
            if any(item["key"] == key for item in items):
                items = [item for item in items if item["key"] != key]
            elif (target == "clip_images" and self.clip_image_room > 0) or (
                target == "clip_videos" and len(items) < CLIP_MAX_VIDEOS
            ):
                item = {"key": key, "name": name, "source": source}
                if target == "clip_images":
                    item["role"] = _default_clip_role(source)
                items = [*items, item]
            if target == "clip_images":
                self.clip_images = items
            else:
                self.clip_videos = items
            self._sync_clip_frames()
        elif target == "background":
            held = ("", "") if self.media_background_key == key else (key, name)
            self.media_background_key, self.media_background_name = held
        elif target == "slide_reference":
            index = self._carousel_index()
            if index < 0 or self.carousel_slides[index]["source"] != "animated":
                return
            if self.carousel_slides[index].get("ref_key") == key:
                self._replace_slide(index, ref_key="", ref_name="")
            else:
                self._replace_slide(index, ref_key=key, ref_name=name)
        elif target == "slide":
            index = self._carousel_index()
            if index < 0 or self.carousel_slides[index]["source"] in ("existing", "stock"):
                return
            if self.carousel_slides[index].get("photo_key") == key:
                self._replace_slide(index, photo_key="", photo_name="")
            else:
                self._replace_slide(index, photo_key=key, photo_name=name)

    # -- «Datos clave» (§ request 2026-10-14) ------------------------------------------

    def _highlight_pairs(self) -> list[list[str]]:
        """The rows that say something, as the brief takes them."""
        pairs: list[list[str]] = []
        for row in self.brief_highlights[:HIGHLIGHTS_MAX]:
            name = row.get("key", "").strip()[:HIGHLIGHT_KEY_MAX]
            fact = row.get("value", "").strip()[:HIGHLIGHT_VALUE_MAX]
            if name and fact:
                pairs.append([name, fact])
        return pairs

    @rx.event
    def add_highlight(self) -> None:
        if len(self.brief_highlights) < HIGHLIGHTS_MAX:
            self.brief_highlights = [*self.brief_highlights, {"key": "", "value": ""}]

    @rx.event
    def set_highlight(self, index: int, field: str, value: str) -> None:
        index = int(index)
        if field not in ("key", "value") or not 0 <= index < len(self.brief_highlights):
            return
        limit = HIGHLIGHT_KEY_MAX if field == "key" else HIGHLIGHT_VALUE_MAX
        rows = [dict(row) for row in self.brief_highlights]
        rows[index][field] = str(value)[:limit]
        rows[index].pop("auto", None)  # edited: the operator's now
        self.brief_highlights = rows

    @rx.event
    def remove_highlight(self, index: int) -> None:
        index = int(index)
        if 0 <= index < len(self.brief_highlights):
            self.brief_highlights = [
                row for i, row in enumerate(self.brief_highlights) if i != index
            ]

    @rx.var
    def clip_image_keys(self) -> list[str]:
        return [item["key"] for item in self.clip_images]

    @rx.var
    def clip_image_room(self) -> int:
        """Reference images still allowed — the frames are among them (§ 2026-10-14:
        a frame is applied from the references)."""
        return max(CLIP_MAX_IMAGES - len(self.clip_images), 0)

    @rx.var
    def clip_has_references(self) -> bool:
        return bool(self.clip_images or self.clip_videos or self.clip_audios)

    def _set_clip_frame(self, which: str, key: str, name: str) -> None:
        if which == "first":
            self.clip_first_frame_key, self.clip_first_frame_name = key, name
        elif which == "last":
            self.clip_last_frame_key, self.clip_last_frame_name = key, name

    @rx.event
    def set_clip_image_role(self, key: str, role: str) -> None:
        """What a reference image is for (§ request 2026-10-14): the product, the place,
        or a style to borrow — the clip's prompt tells the model."""
        if role not in CLIP_IMAGE_ROLES:
            return
        self.clip_images = [
            {**item, "role": role} if item["key"] == key else item for item in self.clip_images
        ]

    def _clip_strip(self) -> list[dict[str, str]]:
        """The clip's images and videos in `clip_sequence` order. A file the order does
        not know yet goes in: an image at the end; a video just before a closing image
        (two or more files) — so a reference video does not take an image's frame; it
        opens or closes the clip when the operator drags it there, or when it is last."""
        items = {item["key"]: {**item, "kind": "image"} for item in self.clip_images}
        for video in self.clip_videos:
            items.setdefault(video["key"], {**video, "kind": "video"})
        strip = [items[key] for key in self.clip_sequence if key in items]
        for key, item in items.items():
            if any(known["key"] == key for known in strip):
                continue
            if item["kind"] == "video" and len(strip) >= 2 and strip[-1]["kind"] == "image":
                strip.insert(len(strip) - 1, item)
            else:
                strip.append(item)
        return strip

    @rx.var
    def clip_strip(self) -> list[dict[str, str]]:
        """What the clip's draggable strip shows: `{key, name, kind, role, …}`."""
        return self._clip_strip()

    def _sync_clip_frames(self) -> None:
        """The frames follow the strip's order (§ requests 2026-10-14/19: «según el
        orden sea el clip inicial/final», videos included): the first file opens the
        clip, the last — when there are two or more — closes it. A video as a frame
        lends its first frame to open the clip and its last one to close it
        (`MediaProducer._clip_frame`)."""
        strip = self._clip_strip()
        keys = [item["key"] for item in strip]
        self.clip_sequence = keys
        # the images and the videos keep the strip's order too: the references between
        # the frames reach the model in the order the operator gave them
        for name in ("clip_images", "clip_videos"):
            items = getattr(self, name)
            ordered = sorted(items, key=lambda item: keys.index(item["key"]))
            if [i["key"] for i in ordered] != [i["key"] for i in items]:
                setattr(self, name, ordered)
        first = strip[0] if strip else None
        last = strip[-1] if len(strip) > 1 else None
        self._set_clip_frame("first", *((first["key"], first["name"]) if first else ("", "")))
        self._set_clip_frame("last", *((last["key"], last["name"]) if last else ("", "")))

    @rx.event
    def start_clip_image_drag(self, index: int) -> None:
        """A file of the strip lifted (`assets/slide-drag.js`): which one moves."""
        self.clip_drag_from = int(index)

    @rx.event
    def drop_clip_image(self, index: int) -> None:
        """Dropped on another file — an image or a video: it takes that place, and the
        frames follow."""
        start, target = self.clip_drag_from, int(index)
        self.clip_drag_from = -1
        keys = [item["key"] for item in self._clip_strip()]
        if start == target or not (0 <= start < len(keys) and 0 <= target < len(keys)):
            return
        keys.insert(target, keys.pop(start))
        self.clip_sequence = keys
        self._sync_clip_frames()

    @rx.event
    async def handle_clip_image_uploads(self, files: list[rx.UploadFile]) -> None:
        saved = await self._save_uploads(files[: self.clip_image_room])
        self.clip_images = [
            *self.clip_images,
            *(
                {"key": key, "name": name, "source": "upload", "role": "product"}
                for key, name in saved
            ),
        ]
        self._sync_clip_frames()

    @rx.event
    def remove_clip_image(self, key: str) -> None:
        self.clip_images = [item for item in self.clip_images if item["key"] != key]
        self._sync_clip_frames()

    @rx.event
    async def handle_clip_video_uploads(self, files: list[rx.UploadFile]) -> None:
        room = max(CLIP_MAX_VIDEOS - len(self.clip_videos), 0)
        saved = await self._save_uploads(files[:room])
        self.clip_videos = [
            *self.clip_videos,
            *({"key": key, "name": name, "source": "upload"} for key, name in saved),
        ]
        self._sync_clip_frames()

    @rx.event
    def remove_clip_video(self, key: str) -> None:
        self.clip_videos = [item for item in self.clip_videos if item["key"] != key]
        self._sync_clip_frames()

    @rx.event
    async def handle_clip_audio_uploads(self, files: list[rx.UploadFile]) -> None:
        room = max(CLIP_MAX_AUDIOS - len(self.clip_audios), 0)
        saved = await self._save_uploads(files[:room])
        self.clip_audios = [
            *self.clip_audios,
            *({"key": key, "name": name, "source": "upload"} for key, name in saved),
        ]

    @rx.event
    def remove_clip_audio(self, key: str) -> None:
        self.clip_audios = [item for item in self.clip_audios if item["key"] != key]

    def _clip_reference_items(self) -> list[dict[str, str]]:
        """The reference images that are not frames — a frame goes once, as the frame."""
        frames = (self.clip_first_frame_key, self.clip_last_frame_key)
        return [item for item in self.clip_images if item["key"] not in frames]

    def _clip_media(self) -> dict[str, object]:
        """A clip's brief media: its frames and references, nothing else."""
        return {
            "duration_seconds": int(self.clip_duration),
            "clip_audio": self.clip_audio,
            "clip_first_frame_key": self.clip_first_frame_key or None,
            "clip_last_frame_key": (
                self.clip_last_frame_key or None if self.clip_first_frame_key else None
            ),
            # the frames are applied from the references: they go as frames, once
            "clip_image_keys": [item["key"] for item in self._clip_reference_items()],
            "clip_image_roles": [
                item.get("role") or "product" for item in self._clip_reference_items()
            ],
            # a video is a motion reference even when it also lends the opening or
            # closing frame; without Seedance 2.x the producer falls back to the frames
            "clip_video_keys": [item["key"] for item in self.clip_videos],
            "clip_audio_keys": [item["key"] for item in self.clip_audios],
            "product_source": self.product_source,
            # § request 2026-10-20: the logo laid over every frame (no other element: a
            # clip has no place to put one)
            "brand_logo_key": self.brand_logo_key or None,
        }

    @rx.event
    def next_view(self) -> None:
        """«Siguiente»: the next step. Nothing is checked here — only the summary says
        what is missing — so with the same kind and format as last time, writing the
        topic and «Siguiente» reach «Crear» (CREAR-2)."""
        self._flush_phrase_drafts()
        self.gen_step = self._view_index() + 1
        self.gen_step = self._view_index()
        self.create_error = ""

    @rx.event
    def prev_view(self) -> None:
        """«Atrás»: the previous step; what was written stays in the state."""
        self._flush_phrase_drafts()
        self.gen_step = max(self._view_index() - 1, 0)
        self.create_error = ""

    @rx.event
    def go_to_view(self, index: str) -> None:
        """A step of the step bar: any step, back or ahead — only the context is
        required, and the summary says what is missing."""
        self._flush_phrase_drafts()
        try:
            self.gen_step = int(index)
        except ValueError:
            return
        self.gen_step = self._view_index()
        self.create_error = ""

    @rx.event
    def edit_view(self, view: str) -> None:
        """A summary row's «Editar»: the step that holds `view`, with that step's «Más
        opciones» unfolded when the row lives behind it."""
        base, more, _ = view.partition(SHOW_MORE_SUFFIX)
        index = generator_step_of(self.gen_category, self.brief_kind, base)
        if index < 0:
            return
        self.gen_step = index
        if base == "rules":
            self.rules_open = True
        elif base == "campaign" or (base == "channel" and more):
            # step 3's «Más opciones» holds the campaign and a clip's «Con sonido»
            self.campaign_open = True
        elif more:
            self.show_more_open = True
        self.create_error = ""

    # -- «Campaña» (m-24820838): the campaign the piece joins, optional ----------------

    def _set_gen_campaigns(self, options: list[CampaignOptionVM]) -> None:
        """The brand's campaigns; a chosen one that is gone leaves the piece independent."""
        self.gen_campaigns = list(options)
        known = {option.id for option in options}
        if self.gen_campaign not in (NO_CAMPAIGN, NEW_CAMPAIGN, *known):
            self.gen_campaign = NO_CAMPAIGN

    @rx.event
    def set_gen_campaign(self, value: str) -> None:
        """«Sin campaña», one of the brand's, or «+ Nueva campaña» — which preselects the
        next colour of the palette, as the planner does."""
        known = {option.id for option in self.gen_campaigns}
        if value not in (NO_CAMPAIGN, NEW_CAMPAIGN, *known):
            return
        self.gen_campaign = value
        if value == NEW_CAMPAIGN and self.gen_campaign_new_color not in COLOR_LABELS:
            self.gen_campaign_new_color = suggested_color(self.gen_campaigns)
        self.create_error = ""

    @rx.event
    def set_gen_campaign_new_name(self, value: str) -> None:
        self.gen_campaign_new_name = value
        self.create_error = ""

    @rx.event
    def set_gen_campaign_new_color(self, color: str) -> None:
        if color in COLOR_LABELS:
            self.gen_campaign_new_color = color

    def _campaign_problem(self) -> str:
        """A new campaign needs a valid name (`campaigns.clean_name` says why not)."""
        if self.gen_campaign != NEW_CAMPAIGN:
            return ""
        try:
            clean_name(self.gen_campaign_new_name)
        except InvalidCampaignName as exc:
            return str(exc)
        return ""

    def _campaign_summary(self) -> str:
        if self.gen_campaign == NEW_CAMPAIGN:
            name = " ".join(self.gen_campaign_new_name.split())
            return f"Nueva: {name}" if name else "Nueva (falta el nombre)"
        chosen = next((c for c in self.gen_campaigns if c.id == self.gen_campaign), None)
        return chosen.name if chosen is not None else "Sin campaña (publicación independiente)"

    def _reset_gen_campaign(self) -> None:
        self.gen_campaign = NO_CAMPAIGN
        self.gen_campaign_new_name = ""
        self.gen_campaign_new_color = ""

    async def _assign_gen_campaign(
        self, draft_id: UUID, choice: tuple[str, str, str]
    ) -> rx.event.EventSpec | None:
        """Generar's last step: the new draft joins the chosen campaign (a new one is
        created in the draft's brand). Only `campaign_id` is written, so the generation
        running meanwhile is untouched. A failure keeps the piece and says so; a new
        campaign becomes the choice for «Crear otro». Called outside the state lock."""
        value, new_name, new_color = choice
        if value == NO_CAMPAIGN:
            return None
        ids = await self._session_ids()
        if ids is None:
            return rx.toast.error(
                "Tu publicación se está creando, pero no se pudo guardar su campaña."
            )
        tenant_id, brand_id, user_id = ids
        try:
            await asyncio.to_thread(
                lambda: apply_post_choice(
                    tenant_id,
                    draft_id,
                    value,
                    new_name=new_name,
                    new_color=new_color,
                    user_id=user_id,
                )
            )
        except Exception as exc:  # noqa: BLE001 — the piece exists; only its campaign failed
            logger.warning("generated piece campaign failed: %s", type(exc).__name__)
            return rx.toast.error(
                "Tu publicación se está creando, pero no se pudo guardar su campaña: "
                + campaign_error_message(exc)
            )
        if value != NEW_CAMPAIGN:
            return None
        try:
            options = await asyncio.to_thread(brand_campaign_options, tenant_id, brand_id)
        except Exception as exc:  # the campaign is saved; the list refreshes on the next load
            logger.warning("brand campaigns unreadable: %s", type(exc).__name__)
            return None
        wanted = " ".join(new_name.split()).casefold()
        created = next((c for c in options if c.name.casefold() == wanted), None)
        async with self:
            self._set_gen_campaigns(options)
            if created is not None:
                self.gen_campaign = created.id
                self.gen_campaign_new_name = ""
        return None

    @rx.event
    def choose_kind(self, key: str) -> _Events:
        """One of the kinds, directly (the picker goes through `choose_category` /
        `choose_video_type`)."""
        return self._set_kind(key)

    def _set_kind(self, key: str) -> _Events:
        """An avatar kind on OmniHuman loads its voices the first time it is chosen;
        the template kind, the catalog."""
        if key not in _ENABLED_KINDS:
            return None
        self.brief_kind = key
        self.brief_format = ""  # each kind starts on its own default format
        self.create_error = ""
        # «Deshacer» of «Potenciar con IA» belongs to the kind's own field (a flyer's is
        # its scene): another kind must not get that text back
        self.context_before_enhance = ""
        self.context_enhance_note = ""
        self.context_enhance_error = ""
        if key != "static_flyer":
            self.media_carousel = False
        if key in ("avatar_video", "animated_avatar_video"):
            self.video_engine = configured_video_engine()
            self._fit_duration()
            loads: list[rx.event.EventHandler] = []
            if self.video_engine == "omnihuman" and not self.voice_options:
                loads.append(CreativeState.load_voice_options)
            if key == "animated_avatar_video":
                # § request 2026-10-20: the character comes from the Brand Kit
                loads.append(CreativeState.load_brand_character)
            if loads:
                return loads
        if key == "carousel" and len(self.carousel_slides) != _GALLERY_SLIDES:
            # the gallery opens on its three slides (§ 2026-10-14)
            self.carousel_slides = self._three_slides()
            self.carousel_selected = 0
            self.carousel_closing = False
        if key == "clip" and not self.clip_images and self.selected_product_photo_key:
            # the catalog product chosen first is a reference and the clip's opening frame
            # by default (frames are applied from the references since 2026-10-14)
            photo = self.selected_product_photo_key
            name = _INSPIRATION if self.product_source == "stock" else _CATALOG_PHOTO
            self.clip_images = [
                {"key": photo, "name": name, "source": "catalog", "role": "product"}
            ]
            self._sync_clip_frames()
        if self._stock_product_videos:
            self._seed_product_video(key)
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
            self._apply_product_from_query()

    def _apply_product_from_query(self) -> None:
        """«Crear publicación con este producto» (m-24842972): `/create?producto=<id>`
        opens with that product chosen and the product screen answered, so the owner
        lands on «¿Qué quieres crear?» («Cambiar» beside the product goes back). The id
        is only taken when THIS business's catalog — read under RLS — lists it: another
        tenant's product, a deleted one or a malformed id is ignored without an error,
        and the screen opens as usual on the product picker."""
        try:
            params = self.router.url.query_parameters
        except AttributeError:  # no router outside a request (tests, background start)
            params = {}
        wanted = product_id_from_query(params)
        variations = create_mode_from_query(params) == VARIATIONS_MODE
        if variations:
            # m-24842973 (N4): back from «Agregar producto» in Variaciones — the centre
            # reopens on Variaciones (`VariationsState.load_from_query` picks the new
            # product there). Whatever the owner had chosen and written here stays.
            self.gen_mode = "variations"
            if self.product_confirmed:
                return
        if not wanted or not any(i.get("id") == wanted for i in self.catalog_items):
            return
        self.product_tab = "catalog"
        if self.selected_product_id != wanted:
            self.choose_product(wanted)
        self.product_confirmed = True

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
        self._drop_product_video()
        self.selected_product_id = product_id
        self.product_source = "catalog"
        self.stock_product_media = ""
        self._stock_product_videos = []
        self.brief_product_ref = item.get("name", "")
        self.selected_product_photo_key = item.get("photo_key", "")
        self._selected_product_photo_keys = [
            key for key in item.get("photo_keys", "").split("\n") if key
        ]
        self._selected_product_video_keys = [
            key for key in item.get("video_keys", "").split("\n") if key
        ]
        self.catalog_off = []
        # the product's price is a «Dato clave» from the start (2026-10-14): before, the
        # copy only ever got the product's name
        if not self.brief_topic.strip():
            self.brief_topic = item.get("name", "")
        self.create_error = ""

    @rx.event
    def confirm_product(self) -> rx.event.EventSpec | None:
        """«Continuar» on the product screen: the side panel and the views appear. On
        «Imagen de stock» the chosen image is imported first (`confirm_stock_product`)."""
        if self.product_tab == "stock":
            return CreativeState.confirm_stock_product
        self.product_confirmed = True
        return None

    @rx.event
    def change_product(self) -> None:
        """«Cambiar» beside the product: back to the product screen, inputs kept."""
        self.product_confirmed = False

    @rx.event
    async def handle_reference_upload(self, files: list[rx.UploadFile]) -> None:
        """Clip and Ad's «Referencia»: one video."""
        saved = await self._save_uploads(files[:1])
        if saved:
            self.reference_video_key, self.reference_video_name = saved[0]

    @rx.event
    def clear_reference_video(self) -> None:
        self.reference_video_key = ""
        self.reference_video_name = ""

    @rx.event
    def clear_product(self) -> None:
        self.selected_product_id = ""
        self._drop_product_video()
        self.product_source = "catalog"
        self.stock_asset_id = ""
        self.stock_product_media = ""
        self._stock_product_videos = []
        self.selected_product_photo_key = ""
        self._selected_product_photo_keys = []
        self._selected_product_video_keys = []
        self.catalog_off = []
        self.brief_product_ref = ""

    # -- the product from stock (plan-integracion-stock R2, 2026-10-16) --------------------

    @rx.var
    def stock_tiles(self) -> list[dict[str, str]]:
        """«Stock»'s one grid: the images and the videos interleaved — one video after
        every two images while both last, so neither kind hides behind the other."""
        images, videos = list(self.stock_results), list(self.vstock_results)
        mixed: list[dict[str, str]] = []
        while images or videos:
            mixed.extend(images[:2])
            del images[:2]
            if videos:
                mixed.append(videos.pop(0))
        return mixed

    @rx.var
    def stock_any_loading(self) -> bool:
        return self.stock_loading or self.vstock_loading

    @rx.var
    def stock_any_more(self) -> bool:
        return self.stock_has_more or self.vstock_has_more

    @rx.var
    def stock_view_error(self) -> str:
        """One message for the one view: a bank down says so; «nothing found» only when
        neither images nor videos came back."""
        if self.stock_results or self.vstock_results:
            return ""
        if self.stock_loading or self.vstock_loading:
            return ""
        if self.stock_error and self.vstock_error:
            if "No encontramos" in self.stock_error and "No encontramos" in self.vstock_error:
                return "No encontramos imágenes ni videos sin personas. Prueba otras palabras."
            return self.stock_error
        return self.stock_error or self.vstock_error

    @rx.var
    def stock_chosen(self) -> list[dict[str, str]]:
        """The hits picked on «Stock» — images and videos — that are STILL listed (a
        search elsewhere may have replaced the list), in the order picked."""
        listed = {f"image|{t['id']}": t for t in self.stock_results}
        listed.update({f"video|{t['id']}": t for t in self.vstock_results})
        return [listed[pick] for pick in self.stock_picks if pick in listed]

    @rx.var
    def stock_chosen_has_image(self) -> bool:
        return any(t.get("media_type") != "video" for t in self.stock_chosen)

    @rx.var
    def stock_chosen_has_video(self) -> bool:
        return any(t.get("media_type") == "video" for t in self.stock_chosen)

    @rx.var
    def stock_inspiration_label(self) -> str:
        """What a stock product is, with no name (it is inspiration): «2 imágenes · 1
        video» (the side panel says «Inspiración» above it)."""
        photos = len(self._selected_product_photo_keys)
        videos = len(self._selected_product_video_keys)
        parts = []
        if photos:
            parts.append("1 imagen" if photos == 1 else f"{photos} imágenes")
        if videos:
            parts.append("1 video" if videos == 1 else f"{videos} videos")
        return " · ".join(parts) or _INSPIRATION

    @rx.var
    def can_continue_product(self) -> bool:
        """«Continuar»: a catalog product picked, or at least one stock hit that is STILL
        listed."""
        if self.product_tab == "stock":
            return bool(self.stock_chosen) and not self.stock_importing
        return self.selected_product_id != ""

    @rx.var
    def stock_credits(self) -> list[dict[str, str]]:
        """The banks the results on screen came from — each asks for a visible credit."""
        seen: list[str] = []
        for tile in [*self.stock_results, *self.vstock_results]:
            if tile.get("provider") and tile["provider"] not in seen:
                seen.append(tile["provider"])
        return [
            {"name": PROVIDER_CREDITS[p][0], "url": PROVIDER_CREDITS[p][1]}
            for p in seen
            if p in PROVIDER_CREDITS
        ]

    @rx.event
    def set_product_tab(self, value: str | list[str]) -> rx.event.EventSpec | None:
        """«Imagen de stock» searches straight away, with what the Brand Kit says the
        brand sells (§ request 2026-10-16) — the first time; coming back keeps the
        results and the choice."""
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value in ("catalog", "stock"):
            self.product_tab = value
        if value != "stock":
            return None
        try:
            self.stock_on = stock_available()
        except Exception:  # noqa: BLE001 — a check must not break the screen
            self.stock_on = False
        if not self.stock_on:
            return None
        # images and videos side by side: each bank searched the first time only
        searches = []
        if not self.stock_results and not self.stock_loading:
            searches.append(CreativeState.search_stock_from_kit)
        if not self.vstock_results and not self.vstock_loading:
            searches.append(CreativeState.search_stock_videos_from_kit)
        return searches or None

    @rx.event
    def set_stock_query(self, value: str) -> None:
        self.stock_query = value

    @rx.event
    def stock_search_on_enter(self, key: str) -> rx.event.EventSpec | None:
        """The search runs on Enter or the button, never while typing: the banks ask
        for real human requests, and each search spends the tenant's hourly quota."""
        return CreativeState.search_stock_products if key == "Enter" else None

    def _stock_pick_listed(self, pick: str) -> bool:
        media, _, choice_id = pick.partition("|")
        return choice_id in (self._vstock_items if media == "video" else self._stock_items)

    @rx.event
    def choose_stock_product(self, choice_id: str, media: str = "image") -> None:
        """Pick (or unpick) one more hit, an image or a video — only one the session
        listed, up to `STOCK_MAX_PICKS` (and `CLIP_MAX_VIDEOS` videos: what a Clip takes)."""
        media = "video" if media == "video" else "image"
        pick = f"{media}|{choice_id}"
        self.stock_pick_notice = ""
        if pick in self.stock_picks:
            self.stock_picks = [p for p in self.stock_picks if p != pick]
            return
        if not self._stock_pick_listed(pick):
            return
        picks = [p for p in self.stock_picks if self._stock_pick_listed(p)]
        if len(picks) >= STOCK_MAX_PICKS:
            self.stock_pick_notice = f"Puedes elegir hasta {STOCK_MAX_PICKS}."
            return
        if media == "video" and sum(p.startswith("video|") for p in picks) >= CLIP_MAX_VIDEOS:
            self.stock_pick_notice = (
                f"Puedes elegir hasta {CLIP_MAX_VIDEOS} videos: los que admite un Clip."
            )
            return
        self.stock_picks = [*picks, pick]
        self.stock_error = ""
        self.vstock_error = ""

    @rx.event
    def play_stock_video(self, choice_id: str) -> None:
        """«Ver» on a stock video: the bank's small rendition plays inside its own tile —
        only a hit this session listed (the URL comes from our own search, never the
        page); starting another stops the one playing."""
        tile = next((t for t in self.vstock_results if t.get("id") == choice_id), None)
        if tile is not None and tile.get("preview"):
            self.hit_playing, self.file_playing = choice_id, ""

    @rx.event
    def play_media(self, key: str) -> None:
        """The round play on a video in a slot's picker: it plays inside its tile — only
        a file the session listed (the product's, or one of the brand catalog's)."""
        if key in self._selected_product_video_keys or any(
            v["key"] == key for v in self._brand_catalog_files("video_keys")
        ):
            self.hit_playing, self.file_playing = "", key

    @rx.event
    def stop_stock_video(self) -> None:
        self._stop_playing()

    def _stop_playing(self) -> None:
        self.hit_playing = ""
        self.file_playing = ""

    @rx.event(background=True)
    async def search_stock_products(self) -> None:
        """«Buscar» / Enter: what the operator typed; with the box empty, the Brand
        Kit's own words."""
        async with self:
            typed = self.stock_query.strip()
            self.vstock_query = typed
        # both banks at once: the images and the videos land in the same grid
        images = self._stock_search(more=False) if typed else self._stock_kit_search()
        await asyncio.gather(images, self._vstock_search(more=False, from_kit=not typed))

    @rx.event(background=True)
    async def search_stock_from_kit(self) -> None:
        await self._stock_kit_search()

    async def _stock_kit_search(self, *, more: bool = False) -> None:
        """Search with the Brand Kit's words (`kit_search_queries`: rubro, hashtags,
        niche, catalog products) — several at once, mixed into one page (§ request
        2026-10-16: «búsquedas en paralelo para más opciones»). The words used show
        above the results; the box stays free for the operator's own search. «Ver más»
        asks every word for its next page."""
        async with self:
            if self.stock_loading:
                return
            page = self.stock_page + 1 if more else 1
            known_queries = list(self._stock_kit_queries) if more else []
            self.stock_loading = True
            self.stock_error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.stock_loading = False
                self.stock_error = _STOCK_OFF
            return
        tenant_id, brand_id, _ = ids
        try:
            queries = known_queries or await asyncio.to_thread(
                kit_search_queries, tenant_id, brand_id
            )
            if not queries:
                async with self:
                    self.stock_loading = False
                    self.stock_error = _STOCK_NO_KIT
                return
            words, tiles, items, has_more = await asyncio.to_thread(
                lambda: search_stock_from_kit(tenant_id, queries, page=page)
            )
        except StockUnavailable as exc:
            async with self:
                self.stock_loading = False
                self.stock_error = str(exc.args[0]) if exc.args else _STOCK_OFF
            return
        except Exception as exc:  # noqa: BLE001 — Redis, network, DB: the box still works
            logger.warning("stock kit search failed: %s", type(exc).__name__)
            async with self:
                self.stock_loading = False
                self.stock_error = _STOCK_OFF
            return
        async with self:
            self.stock_from_kit = True
            self._stock_kit_queries = queries
            if more:
                known = {t["id"] for t in self.stock_results}
                self.stock_results = self.stock_results + [t for t in tiles if t["id"] not in known]
                self._stock_items = {**self._stock_items, **items}
            else:
                self.stock_kit_words = words
                self.stock_results = tiles
                self._stock_items = items
                self.stock_picks = [
                    p for p in self.stock_picks if p.startswith("video|") or p[6:] in items
                ]
            self.stock_page = page
            self.stock_has_more = has_more
            self.stock_loading = False
            if not self.stock_results:
                self.stock_error = "No encontramos imágenes sin personas. Prueba otras palabras."

    @rx.event(background=True)
    async def more_stock_products(self) -> None:
        async with self:
            from_kit = self.stock_from_kit
            video_from_kit = self.vstock_from_kit
            more_images, more_videos = self.stock_has_more, self.vstock_has_more
        pending = []
        if more_images:
            pending.append(
                self._stock_kit_search(more=True) if from_kit else self._stock_search(more=True)
            )
        if more_videos:
            pending.append(self._vstock_search(more=True, from_kit=video_from_kit))
        await asyncio.gather(*pending)

    async def _stock_search(self, *, more: bool) -> None:
        async with self:
            if self.stock_loading:
                return
            text = self.stock_query.strip()
            if not text:
                self.stock_error = "Escribe qué buscas, por ejemplo «hamburguesa»."
                return
            page = self.stock_page + 1 if more else 1
            self.stock_loading = True
            self.stock_error = ""
            if not more:
                self.stock_from_kit = False
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.stock_loading = False
                self.stock_error = _STOCK_OFF
            return
        try:
            tiles, items, has_more = await asyncio.to_thread(
                lambda: search_stock_images(ids[0], text, page=page)
            )
        except StockUnavailable as exc:
            async with self:
                self.stock_loading = False
                self.stock_error = str(exc.args[0]) if exc.args else _STOCK_OFF
            return
        except Exception as exc:  # noqa: BLE001 — Redis, network: the screen stays usable
            logger.warning("stock search failed: %s", type(exc).__name__)
            async with self:
                self.stock_loading = False
                self.stock_error = _STOCK_OFF
            return
        async with self:
            if more:
                known = {t["id"] for t in self.stock_results}
                fresh = [t for t in tiles if t["id"] not in known]
                self.stock_results = self.stock_results + fresh
                self._stock_items = {**self._stock_items, **items}
            else:
                self.stock_results = tiles
                self._stock_items = items
                self.stock_picks = [
                    p for p in self.stock_picks if p.startswith("video|") or p[6:] in items
                ]
            self.stock_page = page
            self.stock_has_more = has_more
            self.stock_loading = False
            if not self.stock_results:
                self.stock_error = "No encontramos imágenes sin personas. Prueba otras palabras."

    @rx.event(background=True)
    async def confirm_stock_product(self) -> None:
        """«Continuar» on «Stock»: every pick is copied to R2 with its provenance (a
        backend download from the bank — never a URL the browser chose), all at once,
        and together they become THIS piece's inspiration."""
        async with self:
            if self.stock_importing:
                return
            picks: list[tuple[str, dict]] = []
            for pick in self.stock_picks:
                media, _, choice_id = pick.partition("|")
                item = (self._vstock_items if media == "video" else self._stock_items).get(
                    choice_id
                )
                if item is not None:
                    picks.append((media, item))
            if not picks:
                # searched again since they were picked: say so instead of doing nothing
                self.stock_picks = []
                self.stock_error = "Lo que elegiste ya no está en la lista. Elige otra vez."
                return
            queries = {
                "image": self.stock_query or " ".join(self.stock_kit_words),
                "video": self.stock_query or " ".join(self.vstock_kit_words),
            }
            self.stock_importing = True
            self.stock_error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.stock_importing = False
                self.stock_error = _STOCK_OFF
            return
        tenant_id, brand_id, user_id = ids
        # one failed download must not lose the others (review 2026-10-19): the ones
        # that arrived are used, the rest are reported
        outcomes = await asyncio.gather(
            *(
                asyncio.to_thread(
                    import_stock_video if media == "video" else import_stock_image,
                    tenant_id,
                    brand_id,
                    user_id,
                    item,
                    query=queries[media],
                )
                for media, item in picks
            ),
            return_exceptions=True,
        )
        failures = [one for one in outcomes if isinstance(one, BaseException)]
        for failure in failures:
            if not isinstance(failure, StockUnavailable):
                logger.warning("stock import failed: %s", type(failure).__name__)
        pairs = [
            (media, one)
            for (media, _), one in zip(picks, outcomes, strict=True)
            if not isinstance(one, BaseException)
        ]
        if not pairs:
            first = failures[0]
            async with self:
                self.stock_importing = False
                self.stock_error = (
                    str(first.args[0])
                    if isinstance(first, StockUnavailable) and first.args
                    else _STOCK_OFF
                )
            return
        images = [one for media, one in pairs if media == "image"]
        videos = [one for media, one in pairs if media == "video"]
        async with self:
            self._apply_stock_selection(images, videos)
            if failures:
                self.upload_error = (
                    f"No pudimos traer {len(failures)} de {len(picks)} de la inspiración "
                    "elegida; seguimos con el resto."
                )

    def _drop_product_video(self) -> None:
        """The stock videos that WERE the product leave the Clip's videos and the
        Galería's slides they were put in — a new product must not keep the old one's."""
        keys = {video["key"] for video in self._stock_product_videos if video.get("key")}
        if not keys:
            return
        self.clip_videos = [v for v in self.clip_videos if v.get("key") not in keys]
        self._sync_clip_frames()
        if any(slide.get("key") in keys for slide in self.carousel_slides):
            slides = []
            for slide in self.carousel_slides:
                if slide.get("key") in keys:
                    fresh = _new_slide("generated", text=slide.get("text", "none"))
                    fresh["uid"] = slide.get("uid") or fresh["uid"]
                    slide = fresh
                slides.append(slide)
            self.carousel_slides = slides

    def _apply_stock_selection(
        self, images: list[dict[str, str]], videos: list[dict[str, str]]
    ) -> None:
        """The imported stock picks become THIS piece's inspiration — no product name, no
        topic (the rules say what the brand sells): the images its photos (the first one
        the main one), the videos what the Clip takes as references and the Galería as a
        slide. With no image it is a video product — an option that needs a photo says so
        (`kind_conflict`)."""
        if not images and not videos:
            return
        self._drop_product_video()
        # a slot shows a video's POSTER (an mp4 in an <img> is a broken picture)
        self.stock_views = {
            **self.stock_views,
            **{image["key"]: image.get("view", "") for image in images},
            **{v["key"]: v.get("poster_view") or v.get("view", "") for v in videos},
        }
        self.stock_video_views = {
            **self.stock_video_views,
            **{v["key"]: v.get("view", "") for v in videos if v.get("view")},
        }
        first = images[0] if images else videos[0]
        self.selected_product_id = f"stock:{first['asset_id']}"
        self.stock_asset_id = first["asset_id"]
        self.product_source = "stock"
        self.stock_product_media = "image" if images else "video"
        self._stock_product_videos = [
            {
                "key": video["key"],
                "poster_view": video.get("poster_view") or video.get("view", ""),
                "author": video.get("author", ""),
                "provider_label": video.get("provider_label", ""),
            }
            for video in videos
        ]
        self.brief_product_ref = ""
        self.selected_product_photo_key = images[0]["key"] if images else ""
        self._selected_product_photo_keys = [image["key"] for image in images]
        self._selected_product_video_keys = [video["key"] for video in videos]
        self.catalog_off = []
        self.stock_importing = False
        self._stop_playing()
        self.create_error = ""
        self.product_confirmed = True
        # an option chosen earlier that cannot take a video-only product: say so now
        if not images and self.gen_category in _VIDEO_PRODUCT_OFF:
            self.kind_conflict = _video_conflict_text(self.gen_category)
        elif videos and self.gen_category in ("clip", "carousel"):
            self._seed_product_video(_CATEGORY_KIND[self.gen_category])

    def _seed_product_video(self, kind: str) -> None:
        """The product's stock videos into the Clip's videos (up to its limit). The
        Galería takes them only as an animated slide's motion reference (§ request
        2026-10-19), chosen in the slide: nothing is placed for it."""
        videos = [video for video in self._stock_product_videos if video.get("key")]
        if kind != "clip" or not videos:
            return
        for video in videos:
            if not any(v["key"] == video["key"] for v in self.clip_videos):
                self._place_stock_video(video)

    # -- the videos on «Stock» (§ requests 2026-10-16/17): searched with the images ---

    @rx.event(background=True)
    async def search_stock_videos_from_kit(self) -> None:
        await self._vstock_search(more=False, from_kit=True)

    async def _vstock_search(self, *, more: bool, from_kit: bool) -> None:
        async with self:
            if self.vstock_loading:
                return
            page = self.vstock_page + 1 if more else 1
            text = self.vstock_query.strip()
            known_queries = list(self._vstock_kit_queries) if more else []
            self.vstock_loading = True
            self.vstock_error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.vstock_loading = False
                self.vstock_error = _STOCK_OFF
            return
        tenant_id, brand_id, _ = ids
        words: list[str] = []
        queries: list[str] = []
        try:
            if from_kit:
                queries = known_queries or await asyncio.to_thread(
                    kit_search_queries, tenant_id, brand_id
                )
                if not queries:
                    async with self:
                        self.vstock_loading = False
                        self.vstock_error = _STOCK_NO_KIT
                    return
                words, tiles, items, has_more = await asyncio.to_thread(
                    lambda: search_stock_from_kit(tenant_id, queries, page=page, media="video")
                )
            else:
                tiles, items, has_more = await asyncio.to_thread(
                    lambda: search_stock_images(tenant_id, text, page=page, media="video")
                )
        except StockUnavailable as exc:
            async with self:
                self.vstock_loading = False
                self.vstock_error = str(exc.args[0]) if exc.args else _STOCK_OFF
            return
        except Exception as exc:  # noqa: BLE001 — Redis, network, DB: the panel still works
            logger.warning("stock video search failed: %s", type(exc).__name__)
            async with self:
                self.vstock_loading = False
                self.vstock_error = _STOCK_OFF
            return
        async with self:
            self.vstock_from_kit = from_kit
            if from_kit:
                self._vstock_kit_queries = queries
            if more:
                known = {t["id"] for t in self.vstock_results}
                self.vstock_results = self.vstock_results + [
                    t for t in tiles if t["id"] not in known
                ]
                self._vstock_items = {**self._vstock_items, **items}
            else:
                self.vstock_kit_words = words
                self.vstock_results = tiles
                self._vstock_items = items
                self.stock_picks = [
                    p for p in self.stock_picks if not p.startswith("video|") or p[6:] in items
                ]
                if self.hit_playing not in items:
                    self.hit_playing = ""
            self.vstock_page = page
            self.vstock_has_more = has_more
            self.vstock_loading = False
            if not self.vstock_results:
                self.vstock_error = "No encontramos videos sin personas. Prueba otras palabras."

    def _place_stock_video(self, imported: dict[str, str]) -> None:
        """The imported video into the Clip's videos."""
        key = imported["key"]
        name = f"Inspiración · {imported.get('author') or imported.get('provider_label', '')}"
        # like a piece's video (`piece_views`), the slot shows the POSTER: a thumbnail is
        # an <img>, and an mp4 there is a broken picture (seen live 2026-10-16)
        poster = imported.get("poster_view") or imported.get("view", "")
        self.stock_views = {**self.stock_views, key: poster}
        if not any(v["key"] == key for v in self.clip_videos) and (
            len(self.clip_videos) < CLIP_MAX_VIDEOS
        ):
            self.clip_videos = [*self.clip_videos, {"key": key, "name": name, "source": "stock"}]
            self._sync_clip_frames()

    @rx.event(background=True)
    async def load_voice_options(self) -> None:
        """The presenter's voices (§ 2026-10-16): the brand's own clone first when it is
        ready — and so the default — then the public Spanish ones. No vendor call."""
        async with self:
            if self.voices_loading:
                return
            self.voices_loading = True
            self.voices_error = ""
        ids = await self._session_ids()
        tenant_id, brand_id = (ids[0], ids[1]) if ids is not None else (None, None)
        try:
            options = await asyncio.to_thread(voice_options, tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — the picker must still open
            logger.warning("voice options failed: %s", type(exc).__name__)
            options = []
        async with self:
            self.voice_options = options
            self.voices_error = "" if options else _VOICES_DOWN
            self._sync_voice()
            self.voices_loading = False

    @rx.event
    def set_voice_id(self, value: str) -> None:
        self.voice_id = value

    @rx.event
    def set_human_avatar_mode(self, value: str | list[str]) -> None:
        """Mujer / Hombre / Personalizado. A gender also switches the voices to it."""
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value not in (*_GENDERS, "custom"):
            return
        self.human_avatar_mode = value
        if value in _GENDERS:
            self.voice_gender = value
        self._sync_voice()

    def _ad_mode(self) -> str:
        """`AdImageMode` for the advertising image, from the photos it has: both, one
        of them, or the scene alone (§ 2026-10-12: no photo is required). The catalog
        product chosen first counts as its product photo (2026-10-14) — before, with no
        upload the mode was the scene alone and the catalog's photos were dropped."""
        has_product = bool(self.media_product_keys or self._catalog_photos_in())
        if has_product and self.media_background_key:
            return "both"
        if self.media_background_key:
            return "background"
        if has_product:
            return "product"
        return "scene"

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
            for v in self.voice_options
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
    def set_media_subtitles(self, value: bool) -> None:
        self.media_subtitles = bool(value)

    @rx.event
    def set_own_script(self, value: str) -> None:
        self.own_script = value

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
    def review_in_drafts(self) -> list[rx.event.EventSpec | rx.event.EventHandler]:
        """«Revisar y aprobar en Borradores»: the piece moves on to Borradores, and the
        generator starts over — coming back to «Crear pieza» shows its first screen, not
        the piece already sent (§ request 2026-10-08). The reset clears the animated
        avatar's character too while the kind stays: it is loaded again from the Brand
        Kit, or the next piece would be blocked (review 2026-10-20)."""
        draft_id = self.gen_draft_id
        self._back_to_form()
        self.brief_topic = ""
        self._reset_media_inputs()
        self._reset_gen_campaign()
        self.product_confirmed = False
        events: list[rx.event.EventSpec | rx.event.EventHandler] = []
        if self.brief_kind == "animated_avatar_video":
            events.append(CreativeState.load_brand_character)
        if draft_id:
            events.append(rx.redirect(f"/drafts/{draft_id}"))
        return events

    @rx.event
    def new_generation(self) -> rx.event.EventSpec:
        """«Crear otro»: the result goes away and the form, inputs kept, is back on top —
        to try a variation."""
        self._back_to_form()
        return rx.call_script("window.scrollTo({top: 0, behavior: 'smooth'})")

    def _back_to_form(self) -> None:
        self.generator_view = "form"
        self.gen_step = 0
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
        """Only a length the control offers: a presenter's is one of `duration_choices`
        (5, 10, 15 or 30 s, those the month pays for), never 45 or 60 s (m-24851829)."""
        value = value if isinstance(value, str) else (value[0] if value else "")
        if self._is_presenter():
            if value in self._duration_choices():
                self.media_duration = self.presenter_duration = value
        elif value in self._duration_choices():
            self.media_duration = value

    @rx.event
    def set_clip_duration(self, value: str | list[str]) -> None:
        value = value if isinstance(value, str) else (value[0] if value else "")
        if value in CLIP_DURATIONS:
            self.clip_duration = value

    @rx.event
    def set_clip_audio(self, value: bool) -> None:
        """«Con audio» for a clip (§ request 2026-10-23)."""
        self.clip_audio = bool(value)

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
            # the client's name, reduced to a safe basename (PR #100 review): a crafted
            # `../x` or `..\x` must never write outside `uploads/<tenant>/`
            name = safe_upload_name(upload.name or "imagen")
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
        if self.stock_product_media == "video" and self.gen_category in _VIDEO_PRODUCT_OFF:
            return _video_conflict_text(self.gen_category)
        if self.brief_kind == "clip":
            return self._clip_problem()
        return self._presenter_problem() or self._details_problem()

    def _clip_problem(self) -> str:
        if len(self.clip_images) > CLIP_MAX_IMAGES:
            return f"Un clip admite hasta {CLIP_MAX_IMAGES} imágenes. Quita alguna."
        if self.clip_last_frame_key and not self.clip_first_frame_key:
            return "Para usar un fotograma final, elige primero el inicial."
        return ""

    def _presenter_problem(self) -> str:
        """The wizard's «¿Quién lo presenta?» step: the avatar or character, and the
        voice. Only the two avatar kinds have a presenter."""
        reads = self.video_engine == "omnihuman"
        if self.brief_kind == "avatar_video":
            if self.human_avatar_mode == "custom" and not self.human_avatar_prompt.strip():
                return "Describe cómo es la persona que va a presentar el video."
        if self.brief_kind == "animated_avatar_video":
            # § 2026-10-20: the character is the Brand Kit's, nothing to fill in here
            if self.brand_character_loading:
                return "Estamos cargando el personaje de tu marca."
            if self.brand_character_error:
                return self.brand_character_error
            if self.avatar_source == "ai" and not self.avatar_prompt.strip():
                return _NO_BRAND_CHARACTER
            if self.avatar_source == "image":
                if not self.avatar_image_key:
                    return _NO_BRAND_CHARACTER
                if not self.avatar_rights_confirmed:
                    return "Confirma que tienes derecho a animar esa imagen."
        if (
            self.brief_kind in ("avatar_video", "animated_avatar_video")
            and reads
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

    # -- the animated avatar's character, from the Brand Kit (§ request 2026-10-20) -----

    brand_character_loading: bool = False
    brand_character_error: str = ""
    #: What the summary calls it («El avatar de tu marca», «La mascota de tu marca…»).
    brand_character_label: str = ""

    @rx.event(background=True)
    async def load_brand_character(self) -> None:
        """The character the «Avatar animado» video animates: the Brand Kit's drawn
        avatar, else a mascot described from the kit (`creative_provider.brand_character`).
        No picker: the operator does not choose it here any more."""
        async with self:
            if self.brand_character_loading:
                return
            self.brand_character_loading = True
            self.brand_character_error = ""
        ids = await self._session_ids()
        try:
            found = (
                await asyncio.to_thread(brand_character, ids[0], ids[1]) if ids is not None else {}
            )
        except Exception as exc:  # noqa: BLE001 — the DB or R2: say so, never crash
            logger.warning("brand character failed: %s", type(exc).__name__)
            found = None
        async with self:
            self.brand_character_loading = False
            if found is None:
                self.brand_character_error = _DB_ERROR
                return
            if not found:
                self.brand_character_error = _NO_BRAND_CHARACTER
                self.brand_character_label = ""
                return
            self.brand_character_label = found.get("name", "")
            if found.get("source") == "image":
                # an image Qualify drew for the brand: its rights are the brand's own
                self.avatar_source = "image"
                self.avatar_image_key = found.get("key", "")
                self.avatar_image_name = found.get("name", "")
                self.avatar_rights_confirmed = True
                self.avatar_prompt = ""
            else:
                self.avatar_source = "ai"
                self.avatar_prompt = found.get("prompt", "")
                self.avatar_image_key, self.avatar_image_name = "", ""
                self.avatar_rights_confirmed = False

    # -- «Potenciar con IA» on the context (§ request 2026-10-20) -------------------------

    #: The rewrite is on its way.
    context_enhancing: bool = False
    context_enhance_error: str = ""
    #: Facts the model says it added that the operator never gave — shown to check.
    context_enhance_note: str = ""
    #: The text before the last rewrite: «Deshacer» puts it back ("" = nothing to undo).
    context_before_enhance: str = ""

    def _set_context_text(self, text: str) -> None:
        """The context field of the chosen kind: the flyer's scene, else the topic."""
        if self.brief_kind == "static_flyer":
            self.ad_scene_prompt = text[:_SCENE_MAX_CHARS]
        else:
            self.brief_topic = text

    def _piece_label(self) -> str:
        """What the piece is, in the operator's words — for the AI and the summary."""
        if self.gen_category == "video":
            return VIDEO_TYPE_LABELS.get(self.brief_kind, "Avatar")
        if self.gen_category == "ad":
            return VIDEO_TYPE_LABELS["ad_video"]
        return _CATEGORY_TITLES.get(self.gen_category, KIND_LABELS.get(self.brief_kind, ""))

    @rx.event(background=True)
    async def enhance_context(self) -> None:
        """«Potenciar con IA»: the context rewritten by Claude with the Brand Kit and the
        piece's «Datos clave», no new facts (`context_ai`). It replaces the text in the
        box — Generar sends whatever is there — and «Deshacer» brings the operator's
        own words back."""
        async with self:
            if self.context_enhancing:
                return
            text = self._effective_topic()
            self.context_enhance_note = ""
            if len(text) < _ENHANCE_MIN_CHARS:
                self.context_enhance_error = _ENHANCE_TOO_SHORT
                return
            self.context_enhancing = True
            self.context_enhance_error = ""
            self._flush_phrase_drafts()
            form = {
                "text": text,
                "piece": self._piece_label(),
                "scene": self.brief_kind == "static_flyer",
                "product": "" if self.product_source == "stock" else self.brief_product_ref,
                "highlights": self._highlight_pairs(),
                "must_mention": self.brief_must_mention,
                "must_avoid": self.brief_must_avoid,
            }
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.context_enhancing = False
                self.context_enhance_error = _NO_SESSION
            return
        try:
            proposal = await asyncio.to_thread(
                lambda: enhance_generator_context(ids[0], ids[1], **form)  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001 — no key, a refusal, the network: say so
            logger.warning("context enhancement failed: %s: %s", type(exc).__name__, exc)
            async with self:
                self.context_enhancing = False
                self.context_enhance_error = _ENHANCE_FAILED
            return
        async with self:
            self.context_enhancing = False
            if self._effective_topic() != text:
                # typed over meanwhile: the operator's newer words win
                self.context_enhance_error = _ENHANCE_STALE
                return
            self.context_before_enhance = text
            self._set_context_text(proposal.text)
            if proposal.added_facts:
                self.context_enhance_note = _ENHANCE_ADDED + "; ".join(proposal.added_facts)

    @rx.event
    def undo_enhance_context(self) -> None:
        if self.context_before_enhance:
            self._set_context_text(self.context_before_enhance)
        self.context_before_enhance = ""
        self.context_enhance_note = ""
        self.context_enhance_error = ""

    # -- «Creaciones del mes» (CREAR-5, m-24848531): never money ------------------------

    #: The month's balance; -1 = no quota wired (the screens say nothing about it).
    creations_left: int = -1
    creations_quota: int = 0
    #: The day it renews, as the owner reads it («1 de noviembre»; "" = unknown).
    creations_renews: str = ""
    #: The month's videos (counted at approval) and vistas previas (at creation) —
    #: founder, 2026-10-24; a quota of 0 = none wired.
    videos_left: int = 0
    videos_quota: int = 0
    previews_left: int = 0
    previews_quota: int = 0

    def _previews_short(self, price: CreationPrice) -> str:
        """What a video whose vistas previas the month cannot pay says ("" = it can).
        Its videos are not asked here: they are counted when the owner approves."""
        if self.creations_left < 0 or self.previews_quota <= 0 or price.videos <= 0:
            return ""
        if price.videos <= self.previews_left:
            return ""
        return previews_short_text(
            price.videos, self.previews_left, self.previews_quota, renews=self.creations_renews
        )

    def _not_enough_text(self, missing: int) -> str:
        """«Te faltan N…» plus what to do now: something simpler — only when anything is
        left at all — or wait until the quota renews (UX review 2026-10-23)."""
        return not_enough_creations_text(
            missing,
            quota=self.creations_quota,
            renews=self.creations_renews,
            advice=SHORT_ADVICE_SIMPLER if self.creations_left > 0 else "",
        )

    def _fit_duration(self) -> None:
        """A length the month no longer pays for is not left chosen: the longest one it
        still pays for is (UX review 2026-10-23, §4.4 values already filled in) — the
        presenter's and the clip's. A presenter starts on the length the owner last
        chose for one, when it is still offered (m-24851829)."""
        choices = self._duration_choices()
        if self._is_presenter() and self.presenter_duration in choices:
            self.media_duration = self.presenter_duration
        elif choices and self.media_duration not in choices:
            self.media_duration = choices[-1]
        clip = self._clip_duration_choices()
        if clip and self.clip_duration not in clip:
            self.clip_duration = clip[-1]

    def _is_presenter(self) -> bool:
        return is_presenter_request(self.brief_kind, self.video_engine)

    def _creations_price(self) -> CreationPrice | None:
        """What the piece in the form would use — the same rule the service charges
        with (`qualify_creative.creations`). None when the table does not price it."""
        kind = self.brief_kind
        clip = kind == "clip"
        return self._price_for(
            int(self.clip_duration or 5) if clip else int(self.media_duration or 30)
        )

    def _price_for(self, seconds: int) -> CreationPrice | None:
        """`_creations_price` at another length — what a duration control may offer. A
        clip is priced at ITS length (`clip_duration`, m-24851828), with its reference
        videos and sound as the brief will carry them."""
        kind = self.brief_kind
        clip = kind == "clip"
        slides = self.carousel_slides if kind == "carousel" else []
        animated = [s for s in slides if s.get("source") == "animated"]
        own = self.own_script.strip() if self.own_script_on and self._is_presenter() else ""
        try:
            return weight_for_request(
                kind,
                duration_seconds=seconds,
                video_engine=self.video_engine,
                own_script_chars=len(own),
                generated_slides=sum(1 for s in slides if s.get("source") == "generated"),
                animated_slide_seconds=tuple(int(s.get("seconds") or 5) for s in animated),
                animated_slide_references=tuple(
                    bool(s.get("reference_video_key")) for s in animated
                ),
                reference_videos=len(self.clip_videos) if clip else 0,
                audio=self.clip_audio if clip else False,
            )
        except (CreationNotOffered, ValueError):
            return None

    def _creations_problem(self) -> str:
        """Without enough creations nothing is created (\"\" = it can be paid)."""
        if self.creations_left < 0:
            return ""
        price = self._creations_price()
        if price is None:
            if self._is_presenter() and not (self.own_script_on and self.own_script.strip()):
                return _PRESENTER_LENGTHS
            return PRESENTER_TOO_LONG if self._is_presenter() else VIDEO_TOO_LONG
        if price.weight > self.creations_left:
            return self._not_enough_text(price.weight - self.creations_left)
        return self._previews_short(price)

    @rx.var
    def creations_left_text(self) -> str:
        """«Te quedan 18 de 30 este mes» ("" with no quota)."""
        if self.creations_left < 0:
            return ""
        return creations_left_label(
            self.creations_left,
            self.creations_quota,
            self.videos_left,
            self.videos_quota,
            self.previews_left,
            self.previews_quota,
        )

    @rx.var(cache=False)
    def gen_creations_notice(self) -> str:
        """On the summary, before Crear: what this piece uses and what would be left —
        the presenter's in the founder's words. "" when it cannot be paid (the problem
        above Crear says so) or with no quota."""
        if self.creations_left < 0 or not self._on_summary():
            return ""
        price = self._creations_price()
        if price is None or price.weight > self.creations_left or self._previews_short(price):
            return ""
        if price.weight <= 0:
            # a generated video uses no creations: its video is counted, and said, at
            # approval («Al aprobar usas 1 de tus 4 videos del mes»)
            return ""
        video = self.brief_kind in ("clip", "avatar_video", "animated_avatar_video") or (
            self.gen_category == "ad"
        )
        return creations_use_notice(
            price.weight,
            self.creations_left,
            self.creations_quota,
            presenter=price.is_presenter,
            video=video,
        )

    @rx.var(cache=False)
    def gen_presenter_fallback(self) -> str:
        """A presenter the month cannot pay, when a shorter one fits: the screen offers
        the longest that fits instead (CREAR-5 v2: under 25 left, the 15 s at 13; under
        13, the 10 s at 9; under 9, the 5 s at 5)."""
        if self.creations_left < 0 or not self._on_summary() or not self._is_presenter():
            return ""
        if self.own_script_on and self.own_script.strip():
            return ""  # its length is the script's: nothing to switch
        price = self._creations_price()
        if price is not None and price.weight <= self.creations_left:
            return ""
        fits = load_weights().longest_presenter_within(self.creations_left)
        if fits is None or self.media_duration == str(fits[0]):
            return ""
        return presenter_fallback_text(*fits)

    @rx.var
    def duration_choices(self) -> list[str]:
        """The lengths offered: a presenter is priced up to 30 s, and under a short
        month only the lengths it still pays for (CREAR-5) — at least the shortest."""
        return self._duration_choices()

    def _duration_choices(self) -> list[str]:
        """v2 (founder, 2026-10-24): a presenter is offered at 5, 10, 15 and 30 s only —
        the rows of the weights table; 45 and 60 s are never offered. An avatar on
        Seedance is a generated video: 5 or 10 s, one of the month's videos."""
        table = load_weights()
        if self.brief_kind in ("avatar_video", "animated_avatar_video") and not (
            self._is_presenter()
        ):
            if table.videos is not None:
                return [str(s) for s in table.videos.offered_seconds]
            return list(DURATIONS)
        if not is_presenter_request(self.brief_kind, self.video_engine):
            return list(DURATIONS)
        lengths = [step.up_to for step in table.presenter_by_seconds]
        if self.creations_left >= 0:
            fits = [s for s in lengths if table.presenter(s) <= self.creations_left]
            lengths = fits or lengths[:1]
        return [str(s) for s in lengths]

    @rx.var
    def clip_duration_choices(self) -> list[str]:
        """A clip's lengths: 5 or 10 s, each one of the month's videos whatever its
        length or references (founder, 2026-10-24) — so the month never narrows them;
        when no video is left the summary says so."""
        return self._clip_duration_choices()

    def _clip_duration_choices(self) -> list[str]:
        return list(CLIP_DURATIONS)

    @rx.event
    def use_short_presenter(self) -> None:
        """«Usar el más corto»: the longest presenter the month still pays for."""
        table = load_weights()
        fits = table.longest_presenter_within(max(self.creations_left, 0))
        self.media_duration = self.presenter_duration = str((fits or table.shortest_presenter)[0])
        self.create_error = ""

    async def _refresh_creations(self, tenant_id: UUID, brand_id: UUID) -> None:
        """Re-read the month's balance; never a reason to break the screen."""
        try:
            balance = await asyncio.to_thread(creations_balance, tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — the service still refuses what it cannot pay
            logger.warning("creations balance unreadable: %s", type(exc).__name__)
            return
        async with self:
            if balance is None:
                self.creations_left, self.creations_quota, self.creations_renews = -1, 0, ""
                self.videos_left, self.videos_quota = 0, 0
                self.previews_left, self.previews_quota = 0, 0
            else:
                (
                    self.creations_left,
                    self.creations_quota,
                    self.creations_renews,
                    self.videos_left,
                    self.videos_quota,
                    self.previews_left,
                    self.previews_quota,
                ) = balance
                self._fit_duration()

    # -- «Resumen» (§ request 2026-10-20): every option's last view, where Generar is ------

    def _on_summary(self) -> bool:
        return self._gen_steps()[self._view_index()][0] == "review"

    @rx.var(cache=False)
    def gen_problem(self) -> str:
        """What still keeps Generar from running ("" = ready) — shown on the summary
        before the operator presses it. Uncached (it reads most of the form), so it is
        only worked out while the summary is on screen (review 2026-10-20)."""
        return self._form_problem() if self._on_summary() else ""

    @rx.var(cache=False)
    def gen_summary(self) -> list[dict[str, str]]:
        """The summary's rows: `{label, value, index}` — `index` the view that edits it
        («Editar»), "" when it is not one of this option's views. Empty off the summary
        view, like `gen_problem`."""
        if not self._on_summary():
            return []
        kind = self.brief_kind
        rows: list[dict[str, str]] = []

        def row(label: str, value: str, view: str = "") -> None:
            # CREAR-2: «Editar» goes to the step that holds the view
            base = view.removesuffix(SHOW_MORE_SUFFIX)
            step = generator_step_of(self.gen_category, kind, base) if view else -1
            index = str(step) if step >= 0 else ""
            rows.append(
                {
                    "label": label,
                    "value": value or "—",
                    "index": index,
                    "view": view if index else "",
                }
            )

        row("Qué creamos", self._piece_label(), "avatar_type")
        if self.product_source == "stock":
            row("Inspiración", self.stock_inspiration_label)
        else:
            row("Producto", self.brief_product_ref if self.selected_product_id else "Sin producto")
        if kind == "avatar_video":
            mode = self.human_avatar_mode
            presenter = (
                f"Personalizado: {self.human_avatar_prompt.strip()}"
                if mode == "custom"
                else {"female": "Mujer", "male": "Hombre"}.get(mode, mode)
            )
            row("Presentador", presenter, "presenter")
        if kind == "animated_avatar_video":
            character = (
                "Cargando tu marca…"
                if self.brand_character_loading
                else self.brand_character_label or self.brand_character_error
            )
            row("Personaje", character)  # the Brand Kit's: nothing to edit here
        if kind in ("avatar_video", "animated_avatar_video") and self.video_engine == "omnihuman":
            voice = next((v["name"] for v in self.voice_options if v["id"] == self.voice_id), "")
            row("Voz", voice or "La de tu marca", "presenter" if kind == "avatar_video" else "")
        if self.gen_category in ("video", "ad"):
            # an avatar's reference is in «Guion y fondo» since 2026-10-20
            # behind step 1's «Más opciones» for an avatar (UX review, N6)
            where = "details" + SHOW_MORE_SUFFIX if self.gen_category == "video" else "reference"
            row("Video de referencia", self.reference_video_name or "Ninguno", where)
        if kind == "clip":
            first, last = self.clip_first_frame_name, self.clip_last_frame_name
            row(
                "Referencias",
                f"{len(self.clip_images)} imágenes · {len(self.clip_videos)} videos · "
                f"{len(self.clip_audios)} audios",
                "reference",
            )
            frames = " → ".join(name for name in (first, last) if name)
            row("Abre y cierra", frames or "Desde la descripción", "reference")
            if self._clip_reference_items():
                row("Imágenes del medio", _CLIP_MIDDLE_NOTE, "reference")
        if kind == "carousel":
            names = {"generated": "Imagen", "animated": "Video", "stock": "Video de inspiración"}
            slides = " · ".join(
                f"{n}. {names.get(slide.get('source', ''), 'De una publicación')}"
                for n, slide in enumerate(self.carousel_slides, 1)
            )
            row("Diapositivas", slides or "Sin diapositivas", "details")
        if kind == "static_flyer":
            photos = len(self.media_product_keys) + int(bool(self.media_background_key))
            row("Fotos", f"{photos} subidas" if photos else "Ninguna", "details")
        if kind == "template":
            row("Fotos", str(self.template_photo_count), "details")
        if kind in (
            "avatar_video",
            "animated_avatar_video",
            "static_flyer",
            "template",
            "carousel",
            "clip",
        ):
            logo = "Sí" if self.brand_logo_key else "No"
            elements = len(self.brand_element_keys)
            row(
                "Recursos de tu marca",
                f"Logo: {logo}" + (f" · {elements} elementos" if elements else ""),
                "reference"
                if kind == "clip"
                else "details" + SHOW_MORE_SUFFIX
                if self.gen_category == "video"
                else "details",
            )
        content_type = dict((opt.value, opt.label) for opt in content_type_options()).get(
            self.brief_content_type, ""
        )
        length = (
            f" · {self.media_duration} s"
            if kind == "creator_script"
            else f" · {self.clip_duration} s"
            if kind == "clip"
            else ""
        )
        row(
            "Publicación",
            f"{content_type} · {_FORMAT_LABELS.get(self.effective_format, '')}{length}",
            "channel",
        )
        if kind == "clip":
            # its own row: «Editar» opens step 3's «Más opciones», where the switch is
            # (UX review 2026-10-24, N2/N6)
            row(
                "Sonido",
                "Con sonido" if self.clip_audio else "Sin sonido",
                "channel" + SHOW_MORE_SUFFIX,
            )
        facts = " · ".join(f"{name}: {fact}" for name, fact in self._highlight_pairs())
        row("Datos clave", facts or "Ninguno", "rules")
        if self.brief_must_mention.strip():
            row("Debe mencionar", self.brief_must_mention.strip(), "rules")
        if self.brief_must_avoid.strip():
            row("Debe evitar", self.brief_must_avoid.strip(), "rules")
        row(
            "Escena" if kind == "static_flyer" else "Contexto",
            self._effective_topic() or "Falta: es lo único obligatorio",
            "topic",
        )
        row("Campaña", self._campaign_summary(), "campaign")
        return rows

    def _details_problem(self) -> str:
        """The wizard's kind step: the ad's scene, or the operator's own script. The
        ad's photos are optional (§ 2026-10-12)."""
        if self.brief_kind == "static_flyer" and not self.ad_scene_prompt.strip():
            return _SCENE_REQUIRED
        if self.kind_is_video and self.own_script_on and not self.own_script.strip():
            return "Escribe tu guion o apaga «Escribir mi propio guion»."
        if self.brief_kind == "template" and self.template_photo_count < _TEMPLATE_MIN_PHOTOS:
            return _TEMPLATE_PHOTO_REQUIRED
        if self.brief_kind == "carousel":
            if len(self.carousel_slides) != _GALLERY_SLIDES:
                return f"Una galería tiene {_GALLERY_SLIDES} diapositivas."
            if self._video_slides() > _GALLERY_MAX_VIDEOS:
                return "Una galería lleva como máximo 1 video."
        return ""

    def _form_problem(self) -> str:
        """The first thing the form still lacks, in the order of its sections — what
        Generar says above its button ("" when it may generate)."""
        if not self._effective_topic():
            return _SCENE_REQUIRED if self.brief_kind == "static_flyer" else _TOPIC_REQUIRED
        return self._kind_problem() or self._campaign_problem() or self._creations_problem()

    @rx.event
    def toggle_rules(self) -> None:
        self.rules_open = not self.rules_open

    @rx.event
    def toggle_campaign_open(self) -> None:
        self.campaign_open = not self.campaign_open

    @rx.event
    def toggle_show_more(self) -> None:
        self.show_more_open = not self.show_more_open

    def _media_inputs(self) -> dict[str, object]:
        kind = self.brief_kind
        if kind == "clip":
            return self._clip_media()
        takes_images = kind != "creator_script"
        # the ad image sends whichever photos were uploaded; its mode says which
        is_ad = kind == "static_flyer"
        is_template = kind == "template"
        takes_background = takes_images and not is_template
        takes_products = takes_images
        product_keys = list(self.media_product_keys) if takes_products else []
        if takes_products and kind in _CATALOG_PHOTO_KINDS:
            # the catalog product's own photos ride along (deduplicated, the piece's
            # uploads first — the order `build_props` fills the photo port in); since the
            # product is chosen first for every option (2026-10-14), not only a template
            for key in self._catalog_photos_in():
                if key not in product_keys:
                    product_keys.append(key)
            product_keys = product_keys[:_MAX_PRODUCTS]
        media: dict[str, object] = {
            # «Ad» (the «Video publicitario») renders the template's video in the chosen
            # format, «Plantilla» its still (§ 2026-10-13; «Ad» since 2026-10-14)
            **({"template_video": self.gen_category == "ad"} if is_template else {}),
            # Clip and Ad's reference clip (§ 2026-10-14), kept on the brief
            "reference_video_key": (
                self.reference_video_key or None
                if self.gen_category in _SINGLE_REFERENCE_CATEGORIES
                else None
            ),
            "duration_seconds": int(self.media_duration),
            "background_key": self.media_background_key or None if takes_background else None,
            "product_keys": product_keys,
            # where the product came from (catalog or inspiration) — provenance, not a
            # permission: the licence guard lets stock product photos through either way
            "product_source": self.product_source,
            "carousel": self.media_carousel and self.carousel_allowed and takes_products,
            # «Recursos de tu marca» (§ 2026-10-06): apart from the background/products;
            # never for a real creator's script, which does not offer them (2026-10-08)
            "brand_logo_key": (self.brand_logo_key or None) if takes_images else None,
            "brand_element_keys": list(self.brand_element_keys) if takes_images else [],
        }
        if is_ad:
            media["ad_mode"] = self._ad_mode()
            media["scene_prompt"] = self.ad_scene_prompt.strip()
        if kind == "carousel":
            # each slide's own photo is the product reference it is generated from
            photos, slides = self._carousel_slides_payload(bool(media["background_key"]))
            media.update(product_keys=photos, slides=slides, closing_slide=self.carousel_closing)
            return media
        if kind in ("avatar_video", "animated_avatar_video"):
            media["video_engine"] = self.video_engine
            if self.own_script_on:
                media["own_script"] = self.own_script.strip()
            if self.video_engine == "omnihuman":
                # the voice that reads it: "brand" or a public one (§ 2026-10-16), and the
                # subtitles of what it says — OmniHuman's only (m-24828920)
                media["voice_id"] = self.voice_id
                media["subtitles"] = self.media_subtitles
            # no library: the presenter is described (§ 2026-10-07) or the operator's image
            if kind == "avatar_video":
                described = (
                    self.human_avatar_prompt.strip()
                    if self.human_avatar_mode == "custom"
                    else _PRESENTERS.get(self.human_avatar_mode, "")
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
        self.carousel_closing = False
        self.carousel_selected = 0
        self.carousel_adding = False
        self.piece_picker_open = False
        self.avatar_prompt = ""
        self.human_avatar_prompt = ""
        self.ad_scene_prompt = ""
        self.avatar_image_key = ""
        self.avatar_image_name = ""
        self.avatar_rights_confirmed = False
        self.brand_character_label = ""
        self.brand_character_error = ""
        self.reference_video_key = ""
        self.reference_video_name = ""
        self.clip_first_frame_key = ""
        self.clip_first_frame_name = ""
        self.clip_last_frame_key = ""
        self.clip_last_frame_name = ""
        self.clip_images = []
        self.clip_videos = []
        self.clip_sequence = []
        self.clip_audios = []
        self.clip_audio = True
        self.clip_duration = "5"

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
        name = safe_upload_name(upload.name or "photo")  # PR #100 review, as above
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
            self._flush_phrase_drafts()
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
            self._flush_phrase_drafts()
            form = self._generator_form()
            template_form = self._template_form() if self.brief_kind == "template" else None
            campaign = (self.gen_campaign, self.gen_campaign_new_name, self.gen_campaign_new_color)
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
        campaign_notice = await self._assign_gen_campaign(draft_id, campaign)
        if campaign_notice is not None:
            yield campaign_notice
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
            "highlights": self._highlight_pairs(),
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
                self.create_error = route_blocked_text(exc.detail)
            return None
        except NotEnoughCreations as exc:
            # CREAR-5: the month cannot pay — nothing was created
            await self._refresh_creations(tenant_id, brand_id)
            async with self:
                self.is_submitting = False
                self.create_error = (
                    self._not_enough_text(exc.missing)
                    if exc.missing
                    else previews_short_text(
                        exc.previews,
                        exc.previews_left,
                        self.previews_quota,
                        renews=self.creations_renews,
                    )
                )
            return None
        except CreationNotOffered:
            async with self:
                self.is_submitting = False
                self.create_error = PRESENTER_TOO_LONG if self._is_presenter() else VIDEO_TOO_LONG
            return None
        except (ValidationError, ValueError) as exc:
            # the validators' messages only — never `input_value`, which holds the form
            why = (
                "; ".join(str(e.get("msg", "")) for e in exc.errors())
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            logger.warning("brief refused: %s", why[:300])
            async with self:
                self.is_submitting = False
                self.create_error = _BRIEF_INVALID
            return None
        except SQLAlchemyError as exc:
            logger.error("submit brief failed: %s", type(exc).__name__)
            async with self:
                self.is_submitting = False
                self.create_error = _DB_ERROR
            return None
        async with self:
            self.is_submitting = False
        await self._refresh_creations(tenant_id, brand_id)
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

    def _refresh_video(self, vm: DraftVM) -> None:
        """The piece on screen read again while its 1080p final is made (m-24820142):
        its media, badge and draft state change — the operator's edits in progress
        (caption, hook, CTA, hashtags) and the AI hashtag suggestions are left exactly
        as they are (`_fill_edit_fields` runs only when the operator opens the editor or
        a piece is loaded, never from a poll)."""
        self.draft = vm

    def _final_poll_on_screen(self, polling_id: str) -> bool:
        """Whether the final poll for `polling_id` still owns the slot AND its piece is
        the one the page shows: a poll for a piece no longer on screen stops, silently."""
        return (
            self._final_polling_id == polling_id
            and self.draft is not None
            and self.draft.draft_id == polling_id
        )

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
            self.just_approved = False
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
        tenant_id, brand_id, _ = ids
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
            self.draft_history_word = ""
            self.draft_history_help = ""
            if vm is None:
                self.detail_error = _DRAFT_GONE
                return
            self._apply_detail(vm)
            should_poll = vm.is_drafting and self._polling_draft_id != str(draft_id)
            if should_poll:
                self._polling_draft_id = str(draft_id)
            # m-24820142: a final still being made when the piece is opened
            final_poll = self._starts_final_poll(vm)
        await self._load_regen_creations(tenant_id, brand_id, draft_id)
        await self._load_approval_videos(tenant_id, draft_id)
        await self._load_recreate_note(tenant_id, brand_id, draft_id, vm.video_draft.expired)
        if should_poll:
            yield CreativeState.poll_draft
        if final_poll:
            yield CreativeState.poll_final
        if vm.status not in _HISTORY_STATUSES:  # before approval it helps no decision
            return
        word, help_text = await _history_texts(tenant_id, draft_id)
        async with self:
            if self.draft is not None and self.draft.draft_id == str(draft_id):
                self.draft_history_word = word
                self.draft_history_help = help_text

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
        except ApprovalBlocked as exc:
            # ticket 24803289: a variations piece whose copy quotes a price that is not
            # the catalog's — the operator edits the copy, then approves
            async with self:
                self.action_error = exc.detail
            return
        except DraftExpired as exc:
            # m-24820142: a 480p draft too old to make its final — the operator regenerates
            async with self:
                self.action_error = exc.detail
            return
        except NotEnoughCreations as exc:
            # founder 2026-10-24: approving counts the videos, all or nothing — without
            # enough left nothing was approved and the piece waits as it was
            await self._load_approval_videos(tenant_id, draft_uuid)
            async with self:
                self.action_error = self.approve_videos_text or videos_short_text(
                    exc.videos, exc.videos_left, load_weights().monthly_video_quota
                )
            return
        except SQLAlchemyError as exc:
            logger.error("approve failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _DB_ERROR
            return
        ready, note = await self._schedule_readiness(tenant_id, str(draft_uuid))
        async with self:
            self._apply_detail(vm)
            self.just_approved = True
            self.approved_ready = ready
            self.approved_note = note
            start_poll = self._starts_final_poll(vm)
        # The toast goes with the card, never instead of it — and it never says or
        # suggests the publication is already out. It follows the piece, not whether a
        # poll had to start (one may already run for it): a 1080p final being made or
        # that could not be ordered comes first (m-24820142), and then no day and time
        # is offered — the card says why (`approved_hold_note`).
        notice = approval_notice(vm.video_draft, ready=ready)
        yield getattr(rx.toast, notice.kind)(notice.text)
        yield PendingState.refresh_now  # m-24842963: the menu's count drops now
        if start_poll:
            yield CreativeState.poll_final

    #: Before approving a piece with videos (founder, 2026-10-24): «Al aprobar usas 1 de
    #: tus 4 videos del mes. Te quedarían {v}.» — or why it cannot be approved yet.
    approve_videos_text: str = ""
    approve_videos_short: bool = False

    async def _load_approval_videos(self, tenant_id: UUID, draft_id: UUID) -> None:
        try:
            quote = await asyncio.to_thread(approval_videos, tenant_id, draft_id)
        except Exception as exc:  # noqa: BLE001 — the service still refuses what it cannot pay
            logger.warning("approval videos unreadable: %s", type(exc).__name__)
            quote = None
        async with self:
            if quote is None:
                self.approve_videos_text, self.approve_videos_short = "", False
                return
            videos, left, quota, renews = quote
            self.approve_videos_short = quota > 0 and videos > left
            self.approve_videos_text = (
                videos_short_text(videos, left, quota, renews=renews)
                if self.approve_videos_short
                else approval_videos_notice(videos, left, quota)
                if quota > 0
                else ""
            )

    #: Under «Crearla otra vez», before it is pressed (founder, 2026-10-24): «Usa 1 de
    #: tus vistas previas. Te quedan {p}.»
    recreate_note: str = ""

    async def _load_recreate_note(
        self, tenant_id: UUID, brand_id: UUID, draft_id: UUID, expired: bool
    ) -> None:
        note = ""
        if expired:
            try:
                note = await asyncio.to_thread(recreate_note, tenant_id, brand_id, draft_id)
            except Exception as exc:  # noqa: BLE001 — the button still says what it does
                logger.warning("recreate note unreadable: %s", type(exc).__name__)
        async with self:
            self.recreate_note = note

    @rx.event(background=True)
    async def recreate_expired(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Crearla otra vez» (founder, 2026-10-24): the vista previa expired, so a new
        piece is made from the same request (one vista previa per video) and opened."""
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
        tenant_id, brand_id, user_id = ids
        try:
            new_id = await asyncio.to_thread(recreate_draft, tenant_id, draft_uuid, user_id)
        except NotEnoughCreations as exc:
            await self._refresh_creations(tenant_id, brand_id)
            async with self:
                self.action_error = (
                    self._not_enough_text(exc.missing)
                    if exc.missing
                    else previews_short_text(
                        exc.previews,
                        exc.previews_left,
                        self.previews_quota or load_weights().monthly_preview_quota,
                        renews=self.creations_renews,
                    )
                )
            return
        except (UnknownDraft, BrandNotReady):
            async with self:
                self.action_error = _DRAFT_GONE
            return
        except SQLAlchemyError as exc:
            logger.error("recreate failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _DB_ERROR
            return
        yield PendingState.refresh_now
        yield rx.redirect(f"/drafts/{new_id}")

    @rx.var
    def show_approved_next(self) -> bool:
        """m-24842978: the «Aprobada. Todavía no se publica.» card — right after this
        screen approved the draft, and only while it is still approved (saving an edit
        sends it back to review)."""
        return self.just_approved and self.draft is not None and self.draft.status == "approved"

    @rx.var
    def approved_can_schedule(self) -> bool:
        """«Elegir día y hora» on the «Aprobada» card: the publication can be planned
        (m-24842978) and its own video does not hold it back — a 1080p final being made
        or that could not be ordered cannot be scheduled yet (m-24820142)."""
        draft = self.draft
        held = draft is not None and bool(final_pending_note(draft.video_draft))
        return self.approved_ready and not held

    @rx.var
    def approved_hold_note(self) -> str:
        """Why the «Aprobada» card offers no day and time: the final's own words first,
        then the evaluator's (`approved_note`)."""
        draft = self.draft
        held = final_pending_note(draft.video_draft) if draft is not None else ""
        return held or self.approved_note

    @rx.event
    def go_schedule(self):
        """«Elegir día y hora»: Tu semana opens its assign drawer on this publication
        (`/planner?post=<id>`, the same door as the gallery's «Asignar»)."""
        if self.draft is None:
            return None
        return rx.redirect(f"/planner?post={self.draft.draft_id}")

    @rx.event
    def go_publish_now(self):
        """«Publicar ahora» (m-24842985): the same drawer with «Ahora» already chosen. It
        still waits for the owner's «Programar» there — nothing goes out from here."""
        if self.draft is None:
            return None
        return rx.redirect(f"/planner?post={self.draft.draft_id}&cuando=ahora")

    @rx.event
    def go_create_another(self):
        """«Crear otra publicación»: back to the start of the generator."""
        self.just_approved = False
        return rx.redirect("/create")

    #: CREAR-5: what «Pedir otra versión» uses and what would be left ("" = no quota).
    regen_creations_text: str = ""
    #: …and whether the month still pays for it.
    regen_creations_short: bool = False

    async def _load_regen_creations(self, tenant_id: UUID, brand_id: UUID, draft_id: UUID) -> None:
        try:
            quote = await asyncio.to_thread(regeneration_creations, tenant_id, brand_id, draft_id)
        except Exception as exc:  # noqa: BLE001 — the service still refuses what it cannot pay
            logger.warning("regeneration creations unreadable: %s", type(exc).__name__)
            quote = None
        async with self:
            if quote is None:
                self.regen_creations_text, self.regen_creations_short = "", False
                return
            weight, left, quota, renews, previews, previews_left, preview_quota = quote
            previews = previews if preview_quota > 0 else 0
            previews_short = previews > previews_left
            self.regen_creations_short = weight > left or previews_short
            if weight > left:
                self.regen_creations_text = not_enough_creations_text(
                    weight - left, quota=quota, renews=renews
                )
            elif previews_short:
                self.regen_creations_text = previews_short_text(
                    previews, previews_left, preview_quota, renews=renews
                )
            elif weight > 0:
                self.regen_creations_text = creations_use_notice(
                    weight, left, quota, subject="La nueva versión"
                )
            else:
                # a video's new version: a vista previa, said only when few are left
                self.regen_creations_text = previews_left_label(
                    previews_left - previews, preview_quota
                )

    @staticmethod
    async def _schedule_readiness(tenant_id: UUID, draft_id: str) -> tuple[bool, str]:
        """m-24842978: «Elegir día y hora» only for a publication Tu semana can plan. The
        same reader as the gallery; if it cannot be read the way is offered anyway and
        Tu semana, the real gate, says what is missing."""
        try:
            gallery = await asyncio.to_thread(load_gallery, tenant_id)
            return schedule_readiness(list(gallery.posts), draft_id)
        except Exception as exc:  # noqa: BLE001 — the approval already stands
            logger.warning("readiness after approve failed: %s", type(exc).__name__)
            return True, ""

    def _starts_final_poll(self, vm: DraftVM) -> bool:
        """Whether `vm` has a 1080p final being made that nobody polls yet — and claim
        it (m-24820142)."""
        if not vm.video_draft.rendering:
            return False
        if self._final_polling_id == vm.draft_id:
            return False
        self._final_polling_id = vm.draft_id
        return True

    @rx.event(background=True)
    async def retry_final_render(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Reintentar video final» (m-24820142): order again a final that failed."""
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
        tenant_id, _, _ = ids
        try:
            vm = await asyncio.to_thread(retry_final, tenant_id, draft_uuid)
        except UnknownDraft:
            async with self:
                self.action_error = _DRAFT_GONE
            return
        except InvalidTransition:
            async with self:
                self.action_error = (
                    "Primero aprueba la publicación; después preparamos el video final."
                )
            return
        except DraftExpired as exc:
            async with self:
                self.action_error = exc.detail
            return
        except SQLAlchemyError as exc:
            logger.error("final retry failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _DB_ERROR
            return
        async with self:
            self._apply_detail(vm)
            rendering = self._starts_final_poll(vm)
        if rendering:
            yield CreativeState.poll_final

    @rx.event(background=True)
    async def poll_final(self) -> AsyncIterator[rx.event.EventSpec]:
        """Watch the piece on screen every few seconds while its 1080p final is made
        (m-24820142), and say when it lands or fails.

        Each tick reads only the piece's draft-video state (`final_video_state`: the
        draft row and its draft videos); the whole piece is read again only when that
        state changes, when the poll ends, or on its last tick — and then only the
        video parts of the screen are refreshed (`_refresh_video`), never the
        operator's edits in progress. One poll at a time (`_final_polling_id`), and only
        for the piece the page shows: checked on every tick, so when another piece is
        opened (with or without a final of its own) or another poll takes the slot this
        one stops without a word — no toast lands on a piece that is not on screen.
        Bounded by `_FINAL_POLL_BUDGET_SECONDS`, which outlasts the stale threshold: a
        final a dead process left turns retryable inside the window, and the last tick
        refreshes the piece so «Reintentar» shows without a reload."""
        async with self:
            polling_id = self._final_polling_id
            shown = (
                self.draft.video_draft
                if self.draft is not None and self.draft.draft_id == polling_id
                else None
            )
        draft_id = tenant_uuid(polling_id)
        if draft_id is None:
            return
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self._final_polling_id = ""
            return
        tenant_id, _, _ = ids
        started = time.monotonic()
        try:
            while True:
                await asyncio.sleep(_FINAL_POLL_SECONDS)
                last_tick = time.monotonic() - started >= _FINAL_POLL_BUDGET_SECONDS
                async with self:
                    if not self._final_poll_on_screen(polling_id):
                        return  # another piece is on screen, or another poll took over
                try:
                    video = await asyncio.to_thread(final_video_state, tenant_id, draft_id)
                except SQLAlchemyError as exc:
                    logger.error("final poll failed: %s", type(exc).__name__)
                    if last_tick:
                        return
                    continue
                if video is None:
                    return
                step = final_poll_step(video)
                if video != shown or step != FINAL_POLL_CONTINUE or last_tick:
                    try:
                        vm = await asyncio.to_thread(draft_detail, tenant_id, draft_id)
                    except SQLAlchemyError as exc:
                        logger.error("final poll reload failed: %s", type(exc).__name__)
                        vm = None
                    async with self:
                        if not self._final_poll_on_screen(polling_id):
                            return
                        if vm is not None:
                            self._refresh_video(vm)
                            shown = video
                if step == FINAL_POLL_CONTINUE:
                    if last_tick:
                        return
                    continue
                if step == FINAL_POLL_DONE:
                    # the final no longer holds the publication back: the «Aprobada»
                    # card asks Tu semana's reader again whether it can be planned now
                    # (m-24842978), and offers «Elegir día y hora» only then
                    ready, note = await self._schedule_readiness(tenant_id, polling_id)
                    async with self:
                        if not self._final_poll_on_screen(polling_id):
                            return
                        self.approved_ready = ready
                        self.approved_note = note
                    yield rx.toast.success(FINAL_READY_TEXT if ready else FINAL_READY_NOT_READY)
                elif step == FINAL_POLL_FAILED:
                    yield rx.toast.error("No pudimos generar el video final. Puedes reintentarlo.")
                return
        finally:
            async with self:
                if self._final_polling_id == polling_id:
                    self._final_polling_id = ""

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
        tenant_id, brand_id, user_id = ids
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
        except NotEnoughCreations as exc:
            # CREAR-5: the month cannot pay another version — the piece stays as it was
            await self._load_regen_creations(tenant_id, brand_id, draft_uuid)
            async with self:
                # the dialog's own sentence carries the day the quota renews
                self.action_error = (
                    self.regen_creations_text
                    if self.regen_creations_short
                    else not_enough_creations_text(exc.missing)
                    if exc.missing
                    else previews_short_text(
                        exc.previews,
                        exc.previews_left,
                        load_weights().monthly_preview_quota,
                        renews=self.creations_renews,
                    )
                )
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
        if regenerate:
            await self._load_regen_creations(tenant_id, brand_id, draft_uuid)
        yield PendingState.refresh_now  # m-24842963: discarded or regenerated, recount
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
