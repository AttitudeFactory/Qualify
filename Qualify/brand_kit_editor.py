"""/brand/kit — «Tu marca» inside a session (§ request 2026-09-30), from the sidebar's
"Negocio" block. Since m-24842970 (UX audit m1, finding 12: «entré a cambiar mi logo y me
muestra cuentas de otros») it opens on the brand itself:

- **The summary is the page.** A card per section with what is there and «Cambiar»;
  «Cambiar» opens it in place (one at a time) with the wizard's own controls, and each
  section saves on its own («Guardar») or puts back what it had («Cancelar»). Saving
  writes the whole kit (`brand_finish.save_brand_kit`), as the wizards do.
- **The referentes are one more section**, «Negocios parecidos al tuyo», folded by
  default — the stored ranking (`BrandConnectState.load_saved_referentes`) and the form
  to add one by hand, which save on their own.
- **Tu voz y tono still to prepare is an optional row**, «Mejora tu marca (opcional)»,
  with «Ahora no» (asked again on the next visit) and «Preparar mi voz» (opens Voz y
  tono) — never a notice that takes over the page.

Every control is the wizard's own renderer on the same `CreativeState` /
`BrandWizardState`, so the two can never drift; only the page's mode is this module's
(`BrandEditState`)."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator
from typing import Any

import reflex as rx
from qualify_creative.ad_destination import validate_ad_destination_url

from . import brand_documents
from . import brand_rubro_vm as rubro_vm
from .ad_enhancements_ui import ad_enhancement_permissions
from .brand_avatar_panel import brand_avatar_card
from .catalog_vm import (
    IDEAS_RETURN_LABEL,
    REFERENTES_SECTION,
    RETURN_LABEL,
    return_label_for,
    return_path_from_query,
)
from .creative_state import CreativeState
from .creative_vm import KitFormVM
from .creative_wizard_pages import (  # the wizard's own controls, shared on purpose
    _KIT_LISTS,
    _PERKS_LIST,
    BrandConnectState,
    BrandWizardState,
    _brand_extras,
    _identity_editor,
    _insights_header,
    _kit_list_editor,
    _loading_view,
    _logo_versions,
    _manual_section,
    _palette_editor,
    _sorted_panel,
    _tone_sliders,
    _typography_editor,
)
from .ui import (
    app_shell,
    callout,
    card,
    page_body,
    page_header,
    progress_panel,
    removable_pill,
    skeleton_card,
    tag,
    tone_badge,
)
from .ui import tokens as T
from .voice_lab import VoiceLabState, voice_analysis_result, voice_lab_panel

logger = logging.getLogger(__name__)

#: The editor's sections, in page order — (key, title, icon, what it holds).
SECTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("marca", "Marca", "compass", "Qué te hace distinto, quién te compra y tu documento de marca."),
    (
        rubro_vm.RUBRO_SECTION,
        "Tu rubro y tus etiquetas",
        "tag",
        "A qué se dedica tu negocio, con tus palabras, y hasta 5 etiquetas.",
    ),
    ("brandboard", "Logo", "image", "Las versiones de tu logo y los otros elementos."),
    ("tipografia", "Tu letra", "type", "La letra con la que se te reconoce."),
    ("paleta", "Colores", "palette", "Los colores con los que se te reconoce."),
    ("voz", "Voz y tono", "mic", "Tu voz grabada y cómo suena tu marca."),
    (
        "ofrece",
        "Lo que ofrece tu negocio",
        "store",
        "Tus ideas contarán por qué vale la pena visitarte o comprarte.",
    ),
    (
        "habla",
        "Cómo hablas",
        "message-circle",
        "Ejemplos de lo que sí dices, lo que no y cómo invitas a comprar.",
    ),
    (
        "nunca",
        "Lo que nunca dices",
        "shield-alert",
        "Palabras que nunca usas y promesas que no puedes hacer.",
    ),
    (
        "anuncios",
        "Enlace para anuncios",
        "link",
        "La web, catálogo o WhatsApp al que llevarán tus anuncios.",
    ),
)
SECTION_KEYS = frozenset(key for key, *_ in SECTIONS)
#: m-24820842: `/brand/kit?seccion=<key>&volver=<ruta>` — another screen sends the owner
#: to one section and offers the way back (Crear pieza's reel replica → «Cómo hablas»).
SECTION_PARAM = "seccion"
RETURN_PARAM = "volver"
VOICE_SECTION = "voz"
#: «Lo que ofrece tu negocio» (0166): the only section whose «Guardar» writes the perks.
PERKS_SECTION = "ofrece"
#: Its closed summary while the owner has written none.
PERKS_EMPTY = "Todavía no has escrito nada"

#: «Tu rubro y tus etiquetas» (m-25029206): what the etiquetas are for — true for every
#: business today (the weekly trend read is a pilot, so it is not promised here).
RUBRO_HELP = (
    "Con tus etiquetas buscamos negocios parecidos al tuyo y te sugerimos etiquetas para "
    "tus publicaciones. Escribe cada una todo junto, por ejemplo: comidaarabe, pizzeria, "
    "ropadeportiva."
)
#: Saving runs no search: where a new one is asked for — shown only when «Buscar de
#: nuevo» can run for this brand (it needs the brand's account, `refresh_discovery`).
RUBRO_NO_SEARCH = (
    "Para ver otros negocios parecidos al tuyo, toca «Buscar de nuevo» en su sección, más abajo."
)
RUBRO_TAGS_EMPTY = (
    "Agrega hasta 5 palabras que describan tu negocio: con ellas buscamos negocios "
    "parecidos al tuyo y te sugerimos etiquetas para tus publicaciones. Toca «Cambiar»."
)
RUBRO_ADD_TAG = "Agregar etiqueta"
RUBRO_SAVE_FAILED = "No pudimos guardar tu rubro. Inténtalo de nuevo en un momento."
RUBRO_NO_SESSION = "Tu sesión se cerró. Vuelve a entrar para seguir."

#: The brandboard's files, put back by "Cancelar" with the kit's fields.
_ASSET_FIELDS = ("logo_versions", "logo_version_context", "brand_extras", "font_files")


class BrandEditState(rx.State):
    """The page's mode — the kit itself lives in `CreativeState` / `BrandWizardState`."""

    #: The section open for editing ("" for none) — one at a time.
    open_section: str = ""
    #: «Negocios parecidos al tuyo» is unfolded (it saves on its own, so it has no
    #: Cancelar / Guardar and does not count as the open section).
    referentes_open: bool = False
    #: "Ahora no" on «Mejora tu marca (opcional)»: hidden this visit; the next one asks again.
    voice_skipped: bool = False
    #: What the open section had when it was opened, for "Cancelar".
    _before: dict[str, Any] = {}
    #: m-24820842: `?seccion=` — the section another screen sent the owner to ("" none),
    #: and its title; opened by a tap («Ir a …»), never on load: the kit form is still
    #: loading then, and «Cancelar» would put back an empty snapshot.
    focus_section: str = ""
    focus_title: str = ""
    #: m-24820842: `?volver=` — where «Volver a tu publicación» leads ("" = no way back).
    return_to: str = ""
    #: What that way back says (`catalog_vm.return_label_for`): «Ideas de videos» back to
    #: the reels ideas (R7, m-24854854), else «Volver a tu publicación».
    return_label: str = ""
    #: `?seccion=referentes`: «Negocios parecidos al tuyo» is brought into view once it is
    #: drawn — the summary waits for the saved details, so its own mount says when
    #: (`referentes_in_view`; UX re-check 2: a timed wait gave up on a cold phone load).
    scroll_to_referentes: bool = False
    #: «Tu rubro y tus etiquetas» (m-25029206) while open: drafts of their own, so
    #: «Cancelar» only drops them — the saved ones stay in `BrandConnectState`.
    rubro_draft: str = ""
    tags_draft: list[dict[str, str]] = []
    #: The etiqueta being typed: the input shows only after its «+» (like the wizard).
    tag_input: str = ""
    adding_tag: bool = False
    #: What to fix in the etiqueta typed, or why it did not fit ("" none).
    tag_note: str = ""
    rubro_error: str = ""
    rubro_saving: bool = False
    #: Old etiquetas in the drafts the catalog would refuse: marked, and «Guardar» waits.
    invalid_tags: list[str] = []
    #: «Buscar de nuevo» can run for this brand (`rubro_vm.can_search_again`, the same
    #: condition `refresh_discovery` checks): only then the line pointing at it shows.
    can_search_again: bool = False

    @rx.event
    async def restart(self) -> rx.event.EventSpec | None:
        """Every visit opens on the summary of the brand, every section closed — and waits
        for the saved details before showing it (`BrandConnectState.details_loaded`).
        `?seccion=referentes` (R7, m-24854854: the reels ideas' empty states) opens
        «Negocios parecidos al tuyo» instead; it comes into view when it is drawn, after
        those details (`referentes_in_view`)."""
        self.open_section = ""
        self.referentes_open = False
        self.voice_skipped = False
        self._before = {}
        self._clear_rubro_drafts()
        self.rubro_saving = False
        self._read_return_query()
        self.scroll_to_referentes = self.referentes_open
        connect = await self.get_state(BrandConnectState)
        connect.details_loaded = False
        return None

    def _read_return_query(self) -> None:
        """`?seccion=` and `?volver=` (m-24820842): only a known section and only one of
        the app's own routes (`return_path_from_query`, no open redirect)."""
        try:
            params = self.router.url.query_parameters
        except Exception:  # noqa: BLE001 — no router outside a request (tests)
            params = {}
        key = str(params.get(SECTION_PARAM, "") or "")
        self.focus_section = key if key in SECTION_KEYS else ""
        self.focus_title = next((t for k, t, *_ in SECTIONS if k == self.focus_section), "")
        # «Negocios parecidos al tuyo» saves on its own (no Cancelar to put back), so it
        # can open on arrival, unlike the kit's sections
        self.referentes_open = key == REFERENTES_SECTION
        self.return_to = return_path_from_query(params)
        self.return_label = return_label_for(self.return_to) if self.return_to else ""

    @rx.event
    def referentes_in_view(self) -> rx.event.EventSpec | None:
        """«Negocios parecidos al tuyo» was just drawn (its trigger mounts with it, after
        the saved details): bring it into view once — a short pause lets what sits above
        it settle first."""
        if not self.scroll_to_referentes:
            return None
        self.scroll_to_referentes = False
        return rx.call_script(
            "setTimeout(() => document.getElementById('seccion-referentes')"
            "?.scrollIntoView({behavior: 'smooth', block: 'start'}), 250)"
        )

    @rx.event
    def toggle_referentes(self) -> rx.event.EventSpec | None:
        """Fold or unfold «Negocios parecidos al tuyo»; folding brings its title back into
        view, so on a phone the owner is not left at the bottom of a long list."""
        self.referentes_open = not self.referentes_open
        if not self.referentes_open:
            return rx.scroll_to("seccion-referentes")
        return None

    @rx.event
    async def open_and_show(self, key: str) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Editar mi marca»: open a section and bring it into view — on a phone it sits
        below the voice row and the avatar, so the result of the tap must be seen (N12)."""
        await self._open(key)
        if self.open_section == key:
            yield rx.scroll_to(f"seccion-{key}")

    @rx.event
    async def open_voice(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Preparar mi voz» on the optional row: Voz y tono opens in place and comes into
        view — the same section «Cambiar» opens."""
        await self._open(VOICE_SECTION)
        yield rx.scroll_to(f"seccion-{VOICE_SECTION}")

    @rx.event
    async def open(self, key: str) -> None:
        """Open one section; another one left open puts back its unsaved changes first."""
        await self._open(key)

    async def _open(self, key: str) -> None:
        if key not in SECTION_KEYS or key == self.open_section:
            return
        await self._put_back()
        creative = await self.get_state(CreativeState)
        wizard = await self.get_state(BrandWizardState)
        self._before = {
            "form": dataclasses.asdict(creative._kit_form()),
            **{field: _copy(getattr(wizard, field)) for field in _ASSET_FIELDS},
        }
        if key == rubro_vm.RUBRO_SECTION:
            connect = await self.get_state(BrandConnectState)
            self.rubro_draft = connect.rubro_text
            self.tags_draft = rubro_vm.stored_pills(connect.rubro_hashtags)
            self.invalid_tags = rubro_vm.invalid_tags(self.tags_draft)
            self.can_search_again = rubro_vm.can_search_again(
                connect.profile_username, connect.username, connect.network
            )
        self.open_section = key

    @rx.event
    async def cancel(self) -> None:
        await self._put_back()

    async def _put_back(self) -> None:
        if self.open_section and self._before:
            creative = await self.get_state(CreativeState)
            wizard = await self.get_state(BrandWizardState)
            creative._apply_kit_form(KitFormVM(**self._before["form"]))
            for field in _ASSET_FIELDS:
                setattr(wizard, field, self._before[field])
        self.open_section = ""
        self._before = {}
        self._clear_rubro_drafts()

    def _clear_rubro_drafts(self) -> None:
        self.rubro_draft = ""
        self.tags_draft = []
        self.tag_input = ""
        self.adding_tag = False
        self.tag_note = ""
        self.rubro_error = ""
        self.invalid_tags = []

    @rx.event(background=True)
    async def refresh_rubro(self) -> None:
        """Every visit reads the rubro and its etiquetas from the database: a session
        loaded earlier (another tab or phone) shows what is saved now, not its old copy
        (`load_saved_details` keeps a session's own values) — m-25029206."""
        from .brand_finish import load_rubro, session_ids

        ids = await session_ids(self)
        if ids is None:
            return
        try:
            rubro, pills = await asyncio.to_thread(load_rubro, ids[0], ids[1])
        except Exception as exc:  # the page still shows the session's copy
            logger.warning("rubro not refreshed: %s", type(exc).__name__)
            return
        async with self:
            connect = await self.get_state(BrandConnectState)
            # a session that never loaded its details gets them all from
            # `load_saved_details` (it fills `connect` only while the rubro is empty)
            if not connect._details_loaded:
                return
            if (connect.rubro_text, connect.rubro_hashtags) == (rubro, pills):
                return
            connect.rubro_text = rubro
            connect.rubro_hashtags = pills
            connect.hashtags_rubro = rubro.strip()

    # -- «Tu rubro y tus etiquetas» (m-25029206) ------------------------------------
    # Its own handlers, NOT the wizard's: leaving the wizard's rubro input asks Claude
    # for etiquetas (`BrandConnectState.rubro_input_blur` → `suggest_hashtags`); here the
    # owner types them and nothing is suggested or searched.

    @rx.event
    def set_rubro_draft(self, value: str) -> None:
        self.rubro_draft = value
        self.rubro_error = ""

    @rx.event
    def open_tag_input(self) -> None:
        self.adding_tag = True
        self.tag_note = ""

    @rx.event
    def set_tag_input(self, value: str) -> None:
        self.tag_input = value

    @rx.event
    def add_tag(self, _form: dict[str, Any] = {}) -> None:
        """Enter in the etiqueta's input: the typed one joins the list, or the note says
        what to fix and the text stays to be fixed."""
        _take_typed_tag(self)

    @rx.event
    def tag_input_key(self, key: str) -> None:
        """Escape closes the input and forgets what was typed."""
        if key == "Escape":
            self.adding_tag = False
            self.tag_input = ""
            self.tag_note = ""

    @rx.event
    def tag_input_blur(self, value: str) -> None:
        """Leaving the input adds what was typed, like Enter; left empty, the button is
        back. A blur from an input already closed (by Enter or Escape) does nothing."""
        if not self.adding_tag:
            return
        if not value.strip():
            self.adding_tag = False
            self.tag_input = ""
            return
        self.tag_input = value
        _take_typed_tag(self)

    @rx.event
    def remove_tag(self, tag: str) -> None:
        self.tags_draft = rubro_vm.remove_tag(self.tags_draft, tag)
        self.invalid_tags = rubro_vm.invalid_tags(self.tags_draft)
        self.tag_note = ""
        if not self.invalid_tags and self.rubro_error == rubro_vm.NOTE_INVALID_STORED:
            self.rubro_error = ""

    @rx.event(background=True)
    async def save_rubro(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Guardar» on «Tu rubro y tus etiquetas»: ONLY `connect.rubro_text` and
        `connect.hashtags` are written (`brand_finish.save_rubro`) — never the whole kit,
        no search and no AI call. The session's copy follows, so a later save of another
        section writes the new ones and not the old."""
        from .brand_finish import save_rubro, session_ids

        async with self:
            if self.open_section != rubro_vm.RUBRO_SECTION or self.rubro_saving:
                return
            # an etiqueta still in its input counts, as leaving the input would add it
            if self.tag_input.strip() and not _take_typed_tag(self):
                return
            connect = await self.get_state(BrandConnectState)
            rubro = rubro_vm.clean_rubro(self.rubro_draft)
            if not rubro and not connect.sector:
                self.rubro_error = rubro_vm.RUBRO_MISSING
                return
            if rubro_vm.invalid_tags(self.tags_draft):
                # an old etiqueta that no longer passes never vanishes unseen (U6)
                self.invalid_tags = rubro_vm.invalid_tags(self.tags_draft)
                self.rubro_error = rubro_vm.NOTE_INVALID_STORED
                return
            pills = rubro_vm.pills_for_save(self.tags_draft)
            self.rubro_saving = True
            self.rubro_error = ""
        failed = RUBRO_SAVE_FAILED
        try:
            ids = await session_ids(self)
            if ids is None:
                failed = RUBRO_NO_SESSION
            else:
                await asyncio.to_thread(save_rubro, *ids, rubro, pills)
                failed = ""
        except Exception as exc:  # the database: the drafts stay, to try again
            logger.warning("rubro not saved: %s", type(exc).__name__)
        finally:
            async with self:
                self.rubro_saving = False
        async with self:
            if failed:
                self.rubro_error = failed
                return
            connect = await self.get_state(BrandConnectState)
            connect.rubro_text = rubro
            connect.rubro_hashtags = pills
            # the etiquetas of this rubro are the owner's: walking the wizard later does
            # not ask Claude for others just because the text is new to the session
            connect.hashtags_rubro = rubro
            self.open_section = ""
            self._before = {}
            self._clear_rubro_drafts()
        yield brand_documents.notify("Sección guardada.", "ok")

    @rx.event(background=True)
    async def save_section(
        self, form_data: dict[str, Any] = {}
    ) -> AsyncIterator[rx.event.EventSpec | None]:
        """A section's "Guardar": the whole kit is written (`save_brand_kit`); on success
        the section closes with its changes kept, and says so with a toast — not the
        callout the wizards leave on the page (§ 2026-10-05, no inline notices)."""
        from .brand_finish import save_brand_kit

        async with self:
            creative = await self.get_state(CreativeState)
            if self.open_section == "anuncios":
                if "ads_destination_url" in form_data:
                    creative.kit_ads_destination_url = form_data["ads_destination_url"]
                try:
                    validate_ad_destination_url(creative.kit_ads_destination_url.strip() or None)
                except ValueError:
                    creative.kit_error = (
                        "Escribe un enlace completo que empiece por https://, sin espacios."
                    )
                    return
            with_perks = self.open_section == PERKS_SECTION
            connect = await self.get_state(BrandConnectState)
            was = connect.voice_configured
            if self.open_section == VOICE_SECTION:
                # saving Voz y tono IS configuring it, cloned voice or not
                connect.voice_configured = True
        saved = await save_brand_kit(self, with_perks=with_perks)
        async with self:
            if not saved:
                # nothing was stored: Voz y tono is as configured as it was before
                (await self.get_state(BrandConnectState)).voice_configured = was
            else:
                self.open_section = ""
                self._before = {}
                creative = await self.get_state(CreativeState)
                creative.kit_notice = ""
                creative.tone_saved_custom = creative.tone_is_custom()
        if saved:
            yield brand_documents.notify("Sección guardada.", "ok")

    @rx.event
    def skip_voice(self) -> None:
        self.voice_skipped = True


def _take_typed_tag(editor: Any) -> bool:
    """The etiqueta in the input, into the drafts (`brand_rubro_vm.add_typed`). True when
    the text was taken (the input closes); False leaves it there with the note."""
    pills, note, left = rubro_vm.add_typed_parts(editor.tags_draft, editor.tag_input)
    editor.tags_draft = pills
    editor.tag_note = note
    # what was refused (or had no room) stays in the input to be fixed; the rest is in
    editor.tag_input = left
    if not left:
        editor.adding_tag = False
    return not left


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return [dict(item) if isinstance(item, dict) else item for item in value]
    return value


def needs_voice() -> rx.Var[bool]:
    """Tu voz y tono is still to configure: never saved here, no cloned voice, and the
    tone still on its defaults — moving any axis and saving is configuring it; cloning
    the voice is optional (§ request 2026-10-05)."""
    return (
        ~BrandConnectState.voice_configured
        & (VoiceLabState.clone_status == "")
        & ~CreativeState.tone_saved_custom
        & ~BrandEditState.voice_skipped
    )


# --------------------------------------------------------------------------------------
# summaries (a closed section) and editors (an open one)
# --------------------------------------------------------------------------------------


def _faint(text: str) -> rx.Component:
    return rx.text(text, size="2", color=T.TEXT_FAINT)


def _summary_text(value: rx.Var[str], empty: str) -> rx.Component:
    return rx.cond(
        value != "",
        rx.text(value, size="2", color=T.TEXT_MUTED, class_name="q-clamp-2"),
        _faint(empty),
    )


def _palette_summary() -> rx.Component:
    return rx.cond(
        CreativeState.has_palette_colors,
        rx.hstack(
            rx.foreach(
                CreativeState.palette_colors,
                lambda colour: rx.box(
                    title=colour,
                    class_name="q-brand-swatch",  # the ring; the colour is the brand's data
                    width="1.1rem",
                    height="1.1rem",
                    background=colour,
                ),
            ),
            spacing="2",
            wrap="wrap",
        ),
        _faint("Sin colores"),
    )


def _voice_summary() -> rx.Component:
    return rx.text(
        rx.match(
            VoiceLabState.clone_status,
            ("complete", "Voz clonada"),
            ("processing", "Clonando tu voz…"),
            ("failed", "El clon de tu voz falló"),
            # no "Pendiente" here (§ request 2026-10-05): editing comes after the first
            # check, which already asked for the voice — a missing clone is just a fact
            "Sin voz clonada",
        ),
        size="2",
        color=T.TEXT_MUTED,
    )


def _summary(key: str) -> rx.Component:
    if key == "marca":
        return _summary_text(CreativeState.kit_positioning, "Sin posicionamiento")
    if key == "brandboard":
        return rx.text(
            BrandWizardState.logo_versions.length(),
            " versiones del logo · ",
            BrandWizardState.brand_extras.length(),
            " otros elementos",
            size="2",
            color=T.TEXT_MUTED,
        )
    if key == "tipografia":
        return _summary_text(CreativeState.kit_typography_summary, "Sin definir")
    if key == "paleta":
        return _palette_summary()
    if key == VOICE_SECTION:
        return _voice_summary()
    if key == "anuncios":
        return _summary_text(CreativeState.kit_ads_destination_url, "Sin enlace predeterminado")
    if key == PERKS_SECTION:
        return _summary_text(CreativeState.kit_perks_summary, PERKS_EMPTY)
    if key == rubro_vm.RUBRO_SECTION:
        return _rubro_summary()
    blurb = next(text for k, _t, _i, text in SECTIONS if k == key)
    return rx.text(blurb, size="2", color=T.TEXT_MUTED)


def _rubro_summary() -> rx.Component:
    """Closed: the rubro and its etiquetas as they are saved — with none, the invitation
    to add them (most businesses have none yet, m-25029206)."""
    return rx.vstack(
        _summary_text(BrandConnectState.rubro_text, "Sin rubro"),
        rx.cond(
            BrandConnectState.rubro_hashtags.length() > 0,
            rx.flex(
                rx.foreach(
                    BrandConnectState.rubro_hashtags,
                    lambda pill: tag("#" + pill["tag"].to(str), size="2"),
                ),
                wrap="wrap",
                gap="2",
                width="100%",
            ),
            _faint(RUBRO_TAGS_EMPTY),
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _rubro_tag_pill(pill: rx.Var[dict[str, str]]) -> rx.Component:
    invalid = BrandEditState.invalid_tags.contains(pill["tag"])
    return removable_pill(
        rx.fragment(rx.el.span("#", margin_right="2px"), pill["tag"]),
        BrandEditState.remove_tag(pill["tag"]),
        leading=rx.cond(
            invalid,
            rx.icon(
                "triangle-alert",
                size=12,
                color=T.tone_color("warn"),
                aria_label="Esta etiqueta no sirve, cámbiala",
            ),
        ),
        remove_label="Quitar esta etiqueta",
    )


def _rubro_editor() -> tuple[rx.Component, ...]:
    """Open: the rubro in the owner's words and the etiquetas — the wizard's pills with
    their ✕ and «Agregar etiqueta», which opens the input (Enter or leaving it adds;
    Escape cancels). An old etiqueta that no longer passes is marked, with what to do.
    Nothing here is suggested: the owner types every etiqueta."""
    has_room = BrandEditState.tags_draft.length() < rubro_vm.CHOSEN_HASHTAGS
    return (
        rx.vstack(
            rx.el.label(
                rx.text(
                    "A qué se dedica tu negocio, con tus palabras",
                    as_="span",
                    size="2",
                    weight="medium",
                ),
                html_for="brand-rubro-text",
            ),
            rx.input(
                id="brand-rubro-text",
                value=BrandEditState.rubro_draft,
                on_change=BrandEditState.set_rubro_draft,
                placeholder="Ej.: cafetería de especialidad para llevar",
                max_length=rubro_vm.RUBRO_MAX_LENGTH,
                size="3",
                width="100%",
                min_height="44px",
            ),
            spacing="2",
            width="100%",
            align_items="stretch",
        ),
        rx.vstack(
            rx.text("Tus etiquetas (hasta 5)", size="2", weight="medium"),
            rx.flex(
                rx.foreach(BrandEditState.tags_draft, _rubro_tag_pill),
                rx.cond(
                    ~BrandEditState.adding_tag & has_room,
                    rx.button(
                        rx.icon("plus", size=T.ICON_SM),
                        RUBRO_ADD_TAG,
                        on_click=BrandEditState.open_tag_input,
                        variant="soft",
                        size="3",  # ≥ 44 px on a phone (N12)
                        type="button",
                    ),
                ),
                wrap="wrap",
                column_gap="0.75rem",
                row_gap="0.75rem",
                align="center",
                width="100%",
            ),
            rx.cond(
                BrandEditState.adding_tag,
                rx.form(
                    rx.input(
                        value=BrandEditState.tag_input,
                        on_change=BrandEditState.set_tag_input,
                        on_key_down=BrandEditState.tag_input_key,
                        on_blur=BrandEditState.tag_input_blur,
                        auto_focus=True,
                        placeholder="Ej.: pizzeria",
                        aria_label="Nueva etiqueta",
                        max_length=80,
                        size="3",
                        width="100%",
                        min_height="44px",
                    ),
                    on_submit=BrandEditState.add_tag,
                    reset_on_submit=False,
                    width="100%",
                ),
            ),
            rx.cond(
                BrandEditState.tag_note != "",
                rx.text(BrandEditState.tag_note, size="2", color=T.TEXT_MUTED, role="status"),
            ),
            rx.cond(
                (BrandEditState.invalid_tags.length() > 0)
                & (BrandEditState.rubro_error != rubro_vm.NOTE_INVALID_STORED),
                rx.text(rubro_vm.NOTE_INVALID_STORED, size="2", color=T.TEXT_MUTED),
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        rx.text(RUBRO_HELP, size="2", color=T.TEXT_MUTED),
        rx.cond(
            BrandEditState.can_search_again, rx.text(RUBRO_NO_SEARCH, size="2", color=T.TEXT_MUTED)
        ),
        rx.cond(
            BrandEditState.rubro_error != "",
            rx.box(callout(BrandEditState.rubro_error, "error"), role="alert", width="100%"),
        ),
    )


def _editor(key: str) -> tuple[rx.Component, ...]:
    lists = {spec[0]: spec for spec in _KIT_LISTS}
    if key == rubro_vm.RUBRO_SECTION:
        return _rubro_editor()
    if key == "marca":
        return _identity_editor()
    if key == "brandboard":
        return (
            rx.cond(
                BrandWizardState.logo_error != "", callout(BrandWizardState.logo_error, "error")
            ),
            _logo_versions(),
            _brand_extras(),
        )
    if key == "tipografia":
        return (_typography_editor(),)
    if key == "paleta":
        return _palette_editor()
    if key == VOICE_SECTION:
        return (voice_lab_panel(), voice_analysis_result(), *_tone_sliders())
    if key == "habla":
        return tuple(_kit_list_editor(*lists[k]) for k in ("do", "dont", "cta"))
    if key == PERKS_SECTION:
        # the section title names the list; only its hint shows under it
        return (_kit_list_editor(*_PERKS_LIST, show_label=False),)
    if key == "anuncios":
        return (
            rx.el.label("Enlace para anuncios", html_for="brand-ad-destination-url"),
            rx.input(
                id="brand-ad-destination-url",
                name="ads_destination_url",
                type="url",
                default_value=CreativeState.kit_ads_destination_url,
                placeholder="https://tunegocio.com",
                max_length=2048,
                min_height="44px",
                width="100%",
            ),
            rx.cond(
                CreativeState.kit_error != "",
                rx.box(
                    callout(CreativeState.kit_error, "error"),
                    role="alert",
                    id="brand-ad-destination-error",
                    width="100%",
                ),
            ),
            rx.text(
                "Las piezas nuevas usarán este enlace. Puedes cambiarlo en cada pieza. "
                "Déjalo vacío si prefieres elegirlo después.",
                size="2",
                color=T.TEXT_MUTED,
            ),
        )
    return (
        _kit_list_editor(*lists["banned"]),
        _kit_list_editor(*lists["claims"]),
        callout("Esto se comprueba siempre, incluso si desactivas el resto.", "warn"),
    )


def _save_props(key: str) -> dict[str, Any]:
    """What a section's «Guardar» does: «Enlace para anuncios» submits its form; «Tu
    rubro y tus etiquetas» writes only those (`save_rubro`); every other one the kit."""
    if key == rubro_vm.RUBRO_SECTION:
        return {"on_click": BrandEditState.save_rubro, "loading": BrandEditState.rubro_saving}
    action = {"type": "submit"} if key == "anuncios" else {"on_click": BrandEditState.save_section}
    return {**action, "loading": CreativeState.kit_saving, "disabled": _busy()}


def _busy() -> rx.Var[bool]:
    """Nothing saves while the voice is analysed or the brief is read."""
    return VoiceLabState.analyzing | brand_documents.BrandDocumentState.brief_busy


def _section_icon(icon: str) -> rx.Component:
    return rx.center(
        rx.icon(icon, size=18),
        class_name="q-brand-glyph",
        width="2.25rem",
        height="2.25rem",
    )


def _ad_section_form(*children: rx.Component, **props: Any) -> rx.Component:
    """Submit the current DOM value with Save, without waiting for change events."""
    return rx.form(
        rx.vstack(*children, **props),
        id="brand-ad-destination-form",
        class_name="q-ad-destination-editor",
        on_submit=BrandEditState.save_section,
        reset_on_submit=False,
        no_validate=True,
        width="100%",
    )


def _section(key: str, title: str, icon: str, blurb: str) -> rx.Component:
    """One section: closed, its summary and "Editar"; open, the wizard's controls and
    its own Cancelar / Guardar."""
    is_open = BrandEditState.open_section == key
    return card(
        rx.vstack(
            rx.hstack(
                _section_icon(icon),
                rx.vstack(
                    rx.text(title, size="3", weight="bold"),
                    rx.cond(is_open, rx.text(blurb, size="2", color=T.TEXT_MUTED), _summary(key)),
                    spacing="1",
                    align_items="start",
                    min_width="0",
                    flex="1",
                ),
                rx.cond(
                    is_open,
                    tone_badge("Editando", "info"),
                    rx.button(
                        rx.icon("pencil", size=T.ICON_SM),
                        "Cambiar",
                        variant="soft",
                        size="3",  # ≥ 44 px on a phone (N12)
                        on_click=BrandEditState.open(key),
                        flex_shrink="0",
                    ),
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            rx.cond(
                is_open,
                (_ad_section_form if key == "anuncios" else rx.vstack)(
                    *_editor(key),
                    rx.hstack(
                        rx.spacer(),
                        rx.button(
                            "Cancelar",
                            variant="soft",
                            color_scheme="gray",
                            size="3",
                            on_click=BrandEditState.cancel,
                            type="button",
                            disabled=CreativeState.kit_saving | BrandEditState.rubro_saving,
                        ),
                        rx.button(
                            rx.icon("save", size=T.ICON_SM),
                            "Guardar",
                            size="3",
                            **_save_props(key),
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    spacing="4",
                    width="100%",
                    align_items="stretch",
                    padding_top="0.5rem",
                ),
            ),
            spacing="3",
            width="100%",
            align_items="stretch",
        ),
        id=f"seccion-{key}",
        # the open section wears the accent edge (`.q-kit-section--open`) over the card
        class_name=rx.cond(is_open, "q-card q-kit-section--open", "q-card"),
        scroll_margin_top=T.SCROLL_MARGIN_TOP,
    )


def _voice_row() -> rx.Component:
    """«Mejora tu marca (opcional)» — Voz y tono still to prepare is one optional row
    above the summary, never a notice that covers the page (m-24842970)."""
    return card(
        rx.flex(
            rx.hstack(
                _section_icon("mic"),
                rx.vstack(
                    rx.text("Mejora tu marca (opcional)", size="3", weight="bold"),
                    rx.text(
                        "Prepara tu voz y cómo suena tu marca. La usamos en tus videos y en "
                        "tus textos.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    align_items="start",
                    min_width="0",
                    flex="1",
                ),
                spacing="3",
                align="center",
                flex="1",
                min_width="0",
            ),
            rx.hstack(
                rx.button(
                    "Ahora no",
                    variant="soft",
                    color_scheme="gray",
                    size="3",
                    on_click=BrandEditState.skip_voice,
                ),
                rx.button(
                    rx.icon("mic", size=T.ICON_SM),
                    "Preparar mi voz",
                    variant="soft",
                    size="3",
                    on_click=BrandEditState.open_voice,
                ),
                spacing="2",
                justify="end",
                flex_shrink="0",
            ),
            direction={"initial": "column", "sm": "row"},
            gap="3",
            align={"initial": "stretch", "sm": "center"},
            width="100%",
        ),
        id="mejora-tu-marca",
    )


def _referentes_summary() -> rx.Component:
    """The folded count — the same condition as `_referentes_body`, so the summary never
    says «Todavía no hay…» over a list: the sorted accounts count when nothing discovered
    came back."""
    discovered = BrandConnectState.discovered_accounts.length()
    count = rx.cond(discovered > 0, discovered, BrandConnectState.account_buckets.length())
    has_referentes = (discovered > 0) | BrandConnectState.has_sorted
    return rx.cond(
        has_referentes,
        rx.text(
            count,
            rx.cond(count == 1, " negocio guardado", " negocios guardados"),
            size="2",
            color=T.TEXT_MUTED,
        ),
        _faint("Todavía no hay negocios guardados"),
    )


#: «Buscar de nuevo»'s confirmation — it spends search credits and takes a while, so it
#: is asked once; the owner's sort is promised to stay (`refresh_discovery` keeps it).
REFRESH_TITLE = "¿Buscamos de nuevo?"
REFRESH_BODY = (
    "Vamos a buscar otra vez negocios parecidos al tuyo, con lo más reciente de las redes. "
    "Los que ya marcaste se quedan donde los dejaste. Tarda un par de minutos."
)
REFRESH_BUTTON = "Buscar de nuevo"


def _refresh_button() -> rx.Component:
    """«Buscar de nuevo» and its confirmation (§ request 2026-11-03): the search run
    again from today's accounts (`BrandConnectState.refresh_discovery`). Disabled while
    a search runs, so a second tap cannot spend twice."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                REFRESH_BUTTON,
                variant="soft",
                size="3",
                disabled=BrandConnectState.discovering,
                flex_shrink="0",
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title(REFRESH_TITLE),
            rx.alert_dialog.description(REFRESH_BODY, size="2"),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button("Ahora no", variant="soft", color_scheme="gray", size="3"),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        rx.icon("refresh-cw", size=T.ICON_SM),
                        REFRESH_BUTTON,
                        size="3",
                        on_click=BrandConnectState.refresh_discovery,
                    ),
                ),
                justify="end",
                gap="0.75rem",
                margin_top="1.25rem",
                wrap="wrap",
            ),
            max_width="28rem",
        ),
    )


def _refresh_row() -> rx.Component:
    """The top of the open section: what «Buscar de nuevo» brings, and the button —
    under the line on a phone, beside it from `sm` up."""
    return rx.flex(
        rx.text(
            "¿Ya pasó un tiempo? Busca otra vez para ver los negocios parecidos de hoy.",
            size="2",
            color=T.TEXT_MUTED,
            flex="1",
            min_width="0",
        ),
        _refresh_button(),
        direction={"initial": "column", "sm": "row"},
        gap="3",
        align={"initial": "stretch", "sm": "center"},
        width="100%",
    )


def _refresh_progress() -> rx.Component:
    """While «Buscar de nuevo» runs: the wizard's own progress, one category at a time
    (Brand Kit loaders are `progress_panel`, never a spinner)."""
    return progress_panel(
        "Buscando negocios parecidos al tuyo",
        "Los que ya marcaste se quedan donde los dejaste. Puede tardar un par de minutos.",
        value=BrandConnectState.discovery_percent,
        steps=BrandConnectState.discovery_progress,
    )


def _referentes_body() -> rx.Component:
    """The brand's referentes as last left, read back from Postgres — one card grid, or
    the influence ranking once something was sorted as referente or competencia — and
    the form to add one by hand. Every change there saves on its own. «Buscar de nuevo»
    on top runs the search again; while it runs the list gives way to its progress."""
    has_referentes = (BrandConnectState.discovered_accounts.length() > 0) | (
        BrandConnectState.has_sorted
    )
    return rx.cond(
        BrandConnectState.referentes_loading,
        _loading_view("Cargando los negocios parecidos al tuyo"),
        rx.vstack(
            # hidden while the deck is open: a new search mid-classification would clear
            # the deck, and only the cards to sort should be on screen then
            rx.cond(~BrandConnectState.sorting_open, _refresh_row()),
            rx.cond(
                BrandConnectState.discovery_error != "",
                callout(BrandConnectState.discovery_error, "error"),
            ),
            rx.cond(BrandConnectState.profile_username != "", _insights_header()),
            rx.cond(
                BrandConnectState.discovering,
                _refresh_progress(),
                rx.cond(
                    has_referentes,
                    _sorted_panel(),
                    rx.cond(
                        # a search that just ran and found nothing says why (its note)
                        BrandConnectState.results_note != "",
                        callout(BrandConnectState.results_note, "info"),
                        callout(
                            "Todavía no hay negocios parecidos guardados. Los buscamos cuando "
                            "conectas tu Instagram al preparar tu marca, o puedes agregarlos "
                            "a mano.",
                            "info",
                        ),
                    ),
                ),
            ),
            # § request 2026-10-05: a referente, a competitor or a detractor the search
            # did not find, added by hand — the wizard's own form (`_manual_section`)
            _manual_section(with_chips=False),
            spacing="5",
            width="100%",
            align_items="stretch",
            padding_top="0.5rem",
        ),
    )


def _referentes_section() -> rx.Component:
    """«Negocios parecidos al tuyo»: one more section of the summary, folded by default
    (m-24842970 — the owner who came to change the logo does not land on other accounts)."""
    is_open = BrandEditState.referentes_open
    return card(
        rx.vstack(
            rx.hstack(
                _section_icon("users"),
                rx.vstack(
                    rx.text("Negocios parecidos al tuyo", size="3", weight="bold"),
                    rx.cond(
                        is_open,
                        rx.text(
                            "Los que te inspiran y los que compiten contigo, del que más pesa "
                            "al que menos.",
                            size="2",
                            color=T.TEXT_MUTED,
                        ),
                        _referentes_summary(),
                    ),
                    spacing="1",
                    align_items="start",
                    min_width="0",
                    flex="1",
                ),
                rx.button(
                    rx.cond(
                        is_open,
                        rx.icon("chevron-up", size=T.ICON_SM),
                        rx.icon("pencil", size=T.ICON_SM),
                    ),
                    rx.cond(is_open, "Cerrar", "Ver y cambiar"),
                    variant="soft",
                    size="3",
                    on_click=BrandEditState.toggle_referentes,
                    flex_shrink="0",
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            rx.cond(is_open, _referentes_body()),
            # UX re-check 2: sent here from the reels ideas, the way back is also at the foot
            # of the section the owner just used (the one at the top is out of sight)
            rx.cond(is_open & _to_ideas(), rx.box(_return_link(), padding_top="0.25rem")),
            # mounts with the section — after the saved details — to bring it into view
            rx.cond(
                BrandEditState.scroll_to_referentes,
                rx.box(on_mount=BrandEditState.referentes_in_view, display="none"),
            ),
            spacing="3",
            width="100%",
            align_items="stretch",
        ),
        id="seccion-referentes",
        class_name=rx.cond(is_open, "q-card q-kit-section--open", "q-card"),
        scroll_margin_top=T.SCROLL_MARGIN_TOP,
    )


def _to_ideas() -> rx.Var[bool]:
    """The way back leads to the reels ideas (R7)."""
    return BrandEditState.return_label == IDEAS_RETURN_LABEL


def _return_link() -> rx.Component:
    """The way back, saying where it leads: «‹ Ideas de videos» or «Volver a tu
    publicación»."""
    return rx.link(
        rx.button(
            rx.cond(
                _to_ideas(),
                rx.icon("chevron-left", size=T.ICON_SM),
                rx.icon("arrow-left", size=T.ICON_SM),
            ),
            BrandEditState.return_label,
            variant="outline",
            size="3",
            min_height="44px",
        ),
        href=BrandEditState.return_to,
    )


def _return_banner() -> rx.Component:
    """m-24820842: sent here from another screen — the section to fill and the way back.
    Back to the reels ideas (R7) it is only «‹ Ideas de videos»: nothing there waits for
    a save, so the publication's reminder would be wrong."""
    # Only a publication waits for the save; the ideas and the chats (m-25017173) do not.
    to_publication = BrandEditState.return_label == RETURN_LABEL
    return rx.cond(
        BrandEditState.return_to != "",
        rx.vstack(
            rx.cond(
                to_publication,
                callout(
                    "Cuando guardes tus cambios, vuelve para seguir con tu publicación.", "info"
                ),
            ),
            rx.flex(
                rx.cond(
                    BrandEditState.focus_section != "",
                    rx.button(
                        "Ir a «" + BrandEditState.focus_title + "»",
                        variant="soft",
                        size="3",
                        min_height="44px",
                        on_click=BrandEditState.open_and_show(BrandEditState.focus_section),
                    ),
                ),
                _return_link(),
                gap="2",
                wrap="wrap",
            ),
            spacing="2",
            width="100%",
            max_width="46rem",
            align_self="center",
        ),
    )


def _summary_view() -> rx.Component:
    """The page by default (m-24842970): the brand by sections, one column, centred
    (§ request 2026-10-05: no side index) — the optional voice row first while it is
    pending, «Tu avatar animado» (§ request 2026-10-19 — generated, so it has no
    «Cambiar»), the kit's sections and, last, «Negocios parecidos al tuyo»."""
    from .seasonal_ui import brand_section  # noqa: PLC0415

    return rx.vstack(
        rx.cond(needs_voice(), _voice_row()),
        brand_avatar_card(),
        *(_section(*spec) for spec in SECTIONS),
        ad_enhancement_permissions(),
        # m-24976895: stickers and short videos of the brand, by season
        brand_section(),
        _referentes_section(),
        spacing="3",
        width="100%",
        max_width="46rem",
        align_self="center",
        class_name="q-settle q-content-ready",
    )


def brand_edit_index() -> rx.Component:
    loading = CreativeState.kit_loading | ~BrandConnectState.details_loaded
    return app_shell(
        page_header(
            "Tu marca",
            "Tus colores, tu logo y tu forma de hablar, para que todo lo que crees salga con tu "
            "estilo. Toca «Cambiar» en lo que quieras.",
            rx.button(
                rx.icon("pencil", size=T.ICON_SM),
                "Editar mi marca",
                variant="soft",
                size="3",
                on_click=BrandEditState.open_and_show("marca"),
            ),
            title_size="7",
        ),
        page_body(
            rx.vstack(
                rx.cond(
                    (CreativeState.kit_error != "") & (BrandEditState.open_section != "anuncios"),
                    callout(CreativeState.kit_error, "error"),
                ),
                _return_banner(),
                rx.cond(
                    CreativeState.kit_notice != "",
                    callout(CreativeState.kit_notice, "ok", icon="circle-check"),
                ),
                rx.cond(
                    loading,
                    rx.vstack(
                        skeleton_card(3),
                        skeleton_card(3),
                        skeleton_card(2),
                        spacing="4",
                        width="100%",
                        aria_label="Cargando tu marca",
                        aria_busy=True,
                    ),
                    _summary_view(),
                ),
                spacing="4",
                width="100%",
            ),
        ),
    )
