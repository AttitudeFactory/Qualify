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
import time
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import reflex as rx
from pydantic import ValidationError
from qualify_api.creative.service import (
    BrandNotReady,
    RouteBlockedByPolicy,
    UnknownDraft,
    UnknownVariant,
)
from qualify_api.creative.voice_service import NotProposed, UnknownBrandKit, UnknownVersion
from qualify_creative.enums import ContentKind, ContentType
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .creative_provider import (
    HeyGenNotConfigured,
    acting_user_id,
    approve_draft,
    approve_voice,
    brand_readiness,
    default_brand_id,
    draft_detail,
    edit_variant,
    heygen_catalog,
    list_drafts,
    load_kit_form,
    load_voice_screen,
    propose_voice,
    reject_draft,
    route_options_for,
    save_kit,
    submit_brief,
)
from .creative_vm import (
    CopyVariantVM,
    DraftSummaryVM,
    DraftVM,
    KitFormVM,
    ReadinessVM,
    RouteOptionVM,
    VoiceProposalVM,
    content_type_options,
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
_TOPIC_REQUIRED = "Describe el tema o producto del encargo."
_HEYGEN_OFF = "Los videos con avatar no están disponibles: falta configurar HeyGen."
_HEYGEN_DOWN = "No pudimos cargar los avatares y voces de HeyGen. Inténtalo de nuevo."

#: `ContentKind` values that can be chosen today (`template` is shown, not selectable).
_ENABLED_KINDS = ("creator_script", "avatar_video", "animated_avatar_video", "static_flyer")
_DURATIONS = ("15", "30", "45", "60")
_FORMAT_LABELS = {
    "feed_4_5": "Post 4:5",
    "feed_1_1": "Post cuadrado 1:1",
    "reels_9_16": "Reel 9:16",
    "story_9_16": "Story 9:16",
}
#: What the result view says while the piece is being made, per kind.
_GEN_WAITING = {
    "creator_script": "Escribiendo el guion…",
    "avatar_video": (
        "Escribiendo el guion y generando el video en HeyGen. Puede tardar unos minutos."
    ),
    "animated_avatar_video": (
        "Creando el personaje y generando el video en HeyGen. Puede tardar varios minutos."
    ),
    "static_flyer": "Escribiendo el texto y componiendo la imagen…",
}
_GEN_POLL_SECONDS = 3.0
#: An AI avatar plus its render can take many minutes; the draft's reaper is 20.
_GEN_POLL_BUDGET_SECONDS = 20 * 60
_MAX_PRODUCTS = 10
_DRAFT_GONE = "Ese borrador no existe o ya no es visible para este negocio."
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
    tone_formal_casual: int = 50
    tone_sober_enthusiastic: int = 50
    tone_technical_plain: int = 50
    tone_brief_elaborate: int = 50
    kit_do_examples: str = ""
    kit_dont_examples: str = ""
    kit_banned_words: str = ""
    kit_forbidden_claims: str = ""
    kit_cta_patterns: str = ""
    kit_palette: str = ""

    # -- /brand/voice -------------------------------------------------------
    voice_loading: bool = False
    voice_error: str = ""
    voice_proposal: VoiceProposalVM | None = None
    voice_active: VoiceProposalVM | None = None

    # -- /create ------------------------------------------------------------
    create_loading: bool = False
    create_error: str = ""
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
    brief_kind: str = "static_flyer"
    media_background_key: str = ""
    media_background_name: str = ""
    media_product_keys: list[str] = []
    media_product_names: list[str] = []
    media_carousel: bool = False
    media_duration: str = "30"
    avatar_look_id: str = ""
    voice_id: str = ""
    avatar_source: str = "ai"
    avatar_prompt: str = ""
    avatar_image_key: str = ""
    avatar_image_name: str = ""
    avatar_rights_confirmed: bool = False
    #: HeyGen's library looks `{id, name, preview}` and Spanish voices `{id, name}`,
    #: read once when an avatar kind is first chosen.
    heygen_looks: list[dict[str, str]] = []
    heygen_voices: list[dict[str, str]] = []
    heygen_loading: bool = False
    heygen_error: str = ""
    #: The format picked for the kind ("" = the kind's default, `ContentKind.formats`).
    brief_format: str = ""
    # The generator's two views (/signals): "form" (configure) → "result" (the piece).
    generator_view: str = "form"
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
        return self.brief_kind in ("avatar_video", "animated_avatar_video", "static_flyer")

    @rx.var
    def format_options(self) -> list[list[str]]:
        """[value, label] of the formats the chosen kind offers, its default first."""
        try:
            kind = ContentKind(self.brief_kind)
        except ValueError:
            return []
        return [[fmt.value, _FORMAT_LABELS[fmt.value]] for fmt in kind.formats]

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
    def carousel_allowed(self) -> bool:
        """A carousel is a flyer in a feed format (Instagram takes none in a story)."""
        return self.brief_kind == "static_flyer" and self.effective_format.startswith("feed_")

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
    def gen_failure_label(self) -> str:
        if self.gen_draft is None or self.gen_draft.failure is None:
            return ""
        return self.gen_draft.failure.label

    @rx.var
    def product_items(self) -> list[dict[str, str]]:
        return [
            {"key": key, "name": name}
            for key, name in zip(self.media_product_keys, self.media_product_names, strict=False)
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
            session_tenant_id = auth.session_tenant_id
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
        async with self:
            self.readiness = verdict
            self.route_options = list(options)
            self._select_default_route()
            self.create_loading = False

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
    def set_objective(self, value: str) -> None:
        self.brief_objective = value

    @rx.event
    def set_intent(self, value: str) -> None:
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

    @rx.event
    def choose_kind(self, key: str) -> rx.event.EventSpec | None:
        """One of the five kinds; `template` is shown but not selectable yet. An avatar
        kind loads HeyGen's looks and voices the first time it is chosen."""
        if key not in _ENABLED_KINDS:
            return None
        self.brief_kind = key
        self.brief_format = ""  # each kind starts on its own default format
        self.create_error = ""
        if key != "static_flyer":
            self.media_carousel = False
        if key in ("avatar_video", "animated_avatar_video") and not self.heygen_voices:
            return CreativeState.load_heygen_catalog
        return None

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
        async with self:
            self.heygen_looks = looks
            self.heygen_voices = voices
            if voices and not self.voice_id:
                self.voice_id = voices[0]["id"]
            self.heygen_loading = False

    @rx.event
    def choose_look(self, look_id: str) -> None:
        self.avatar_look_id = look_id

    @rx.event
    def set_voice_id(self, value: str) -> None:
        self.voice_id = value

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
    def new_generation(self) -> None:
        """Back to the form, the inputs kept — to try a variation."""
        self.generator_view = "form"
        self.gen_draft = None
        self.gen_draft_id = ""
        self.gen_variant = 0
        self.gen_timed_out = False
        self.create_error = ""

    @rx.event(background=True)
    async def poll_generator(self) -> None:
        """The result view waits here: the draft is read until it leaves `drafting`
        (an avatar video can take several minutes). Stops on its own when the operator
        goes back to the form or starts another piece."""
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
            async with self:
                if self.gen_draft_id != draft_id or self.generator_view != "result":
                    return
                if vm is not None:
                    self.gen_draft = vm
                    if not vm.is_drafting:
                        return
                if time.monotonic() - started > _GEN_POLL_BUDGET_SECONDS:
                    self.gen_timed_out = True
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

    @rx.event
    def remove_product(self, key: str) -> None:
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
        if self.brief_kind == "avatar_video" and not self.avatar_look_id:
            return "Elige el avatar que va a presentar el video."
        if self.brief_kind in ("avatar_video", "animated_avatar_video") and not self.voice_id:
            return "Elige la voz que va a leer el guion."
        if self.brief_kind == "animated_avatar_video":
            if self.avatar_source == "ai" and not self.avatar_prompt.strip():
                return "Describe cómo es el personaje animado."
            if self.avatar_source == "image":
                if not self.avatar_image_key:
                    return "Sube la imagen del personaje que quieres animar."
                if not self.avatar_rights_confirmed:
                    return "Confirma que tienes derecho a animar esa imagen."
        return ""

    def _media_inputs(self) -> dict[str, object]:
        kind = self.brief_kind
        takes_images = kind != "creator_script"
        media: dict[str, object] = {
            "duration_seconds": int(self.media_duration),
            "background_key": self.media_background_key or None if takes_images else None,
            "product_keys": list(self.media_product_keys) if takes_images else [],
            "carousel": self.media_carousel and self.carousel_allowed,
        }
        if kind == "avatar_video":
            media.update(avatar_look_id=self.avatar_look_id, voice_id=self.voice_id)
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
        self.media_background_key = ""
        self.media_background_name = ""
        self.media_product_keys = []
        self.media_product_names = []
        self.media_carousel = False
        self.avatar_prompt = ""
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
            if self.is_submitting:
                return
            if not self.brief_topic.strip():
                self.create_error = _TOPIC_REQUIRED
                return
            problem = self._kind_problem()
            if problem:
                self.create_error = problem
                return
            self.is_submitting = True
            self.create_error = ""
            form = {
                "objective": self.brief_objective,
                "content_type": self.brief_content_type,
                "topic": self.brief_topic,
                "product_ref": self.brief_product_ref,
                "intent": self.brief_intent,
                "image_route": "",
                "source_media_key": "",
                "must_mention": self.brief_must_mention,
                "must_avoid": self.brief_must_avoid,
                "kind": self.brief_kind,
                "media": self._media_inputs(),
                "content_format": self.effective_format,
            }
        draft_id = await self._create_draft(form)
        if draft_id is None:
            return
        # The generator's second view: the piece, as it lands (§ request 2026-09-25).
        async with self:
            self.generator_view = "result"
            self.gen_draft_id = str(draft_id)
            self.gen_draft = None
            self.gen_variant = 0
            self.gen_timed_out = False
        yield CreativeState.poll_generator

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
                return

    @rx.event(background=True)
    async def load_draft(self) -> AsyncIterator[None]:
        async with self:
            self.detail_loading = True
            self.detail_error = ""
            self.action_error = ""
            self.poll_timed_out = False
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
    async def poll_draft(self) -> None:
        """Poll while DRAFTING. Backs off 1s → 2s → 4s, caps at 5s, gives up at 5 min
        with a visible timeout state (§6.6)."""
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
                async with self:
                    # The operator navigated to another draft or away: stop quietly.
                    if self._polling_draft_id != polling_id:
                        return
                try:
                    vm = await asyncio.to_thread(draft_detail, tenant_id, draft_id)
                except SQLAlchemyError as exc:
                    logger.error("draft poll failed: %s", type(exc).__name__)
                    continue  # transient; the budget above still bounds the loop
                async with self:
                    if self._polling_draft_id != polling_id:
                        return
                    self.poll_elapsed_label = f"{int(time.monotonic() - started)} s"
                    if vm is not None:
                        self._apply_detail(vm)
                        if not vm.is_drafting:
                            return
        finally:
            async with self:
                if self._polling_draft_id == polling_id:
                    self._polling_draft_id = ""

    @rx.event
    def select_variant(self, variant_id: str) -> None:
        self.selected_variant_id = variant_id
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
        """Approve the selected variant (the FSM guard requires one) and hand the
        operator the paste-ready caption — 'Aprobar y descargar'."""
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
        yield rx.download(
            data=variant.rendered_caption,
            filename=f"qualify-copy-{draft.draft_id[:8]}.txt",
        )

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
            yield CreativeState.poll_draft
