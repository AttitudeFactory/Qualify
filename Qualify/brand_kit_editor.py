"""/brand/kit — the Brand Kit inside a session (§ request 2026-09-30), from the sidebar's
"Negocio" block. Reworked on 2026-10-05 ("una vez logueado, que el botón del Brand Kit
sirva para editar y terminar configuraciones"):

- **What is still to configure comes first.** Tu voz y tono is the one part the wizards
  no longer ask (it is configured "después"), so until the operator saves it here — or
  the brand already has a cloned voice — the page opens on it, with "Ahora no" (asked
  again on the next visit) and "Guardar voz".
- **Otherwise it opens on Resultados e insights** — the brand's referentes as last left,
  read back from Postgres (`BrandConnectState.load_saved_referentes`) — with "Editar
  Brand Kit" in the header.
- **Editing is ONE view, not steps:** a card per section with a summary of what is there;
  "Editar" opens it in place (one at a time) with the wizard's own controls, and each
  section saves on its own ("Guardar") or puts back what it had ("Cancelar"). Saving
  writes the whole kit (`brand_finish.save_brand_kit`), as the wizards do.

Every control is the wizard's own renderer on the same `CreativeState` /
`BrandWizardState`, so the two can never drift; only the page's mode is this module's
(`BrandEditState`)."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from typing import Any

import reflex as rx

from . import brand_documents
from .brand_avatar_panel import brand_avatar_card
from .creative_state import CreativeState
from .creative_vm import KitFormVM
from .creative_wizard_pages import (  # the wizard's own controls, shared on purpose
    _KIT_LISTS,
    _RESULTS_COLUMN_MAX,
    BrandConnectState,
    BrandWizardState,
    _brand_extras,
    _discovery_list,
    _identity_editor,
    _insights_header,
    _kit_list_editor,
    _loading_view,
    _logo_versions,
    _manual_section,
    _palette_editor,
    _ranking_panel,
    _tone_sliders,
    _typography_editor,
)
from .ui import app_shell, callout, card, page_body, page_header, tone_badge
from .ui import tokens as T
from .voice_lab import VoiceLabState, voice_analysis_result, voice_lab_panel

#: The editor's sections, in page order — (key, title, icon, what it holds).
SECTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("marca", "Marca", "compass", "Posicionamiento, audiencia y tu brief."),
    ("brandboard", "Brandboard", "image", "Las versiones de tu logo y los otros elementos."),
    ("tipografia", "Tipografía", "type", "La letra con la que se te reconoce."),
    ("paleta", "Paleta", "palette", "Los colores con los que se te reconoce."),
    ("voz", "Voz y tono", "mic", "Tu voz, su clon y cómo suena tu marca."),
    ("habla", "Cómo habla", "message-circle", "Ejemplos que sí, que no y tus llamados."),
    ("nunca", "Lo que nunca dice", "shield-alert", "Palabras vetadas y claims prohibidos."),
)
SECTION_KEYS = frozenset(key for key, *_ in SECTIONS)
VOICE_SECTION = "voz"

#: The brandboard's files, put back by "Cancelar" with the kit's fields.
_ASSET_FIELDS = ("logo_versions", "logo_version_context", "brand_extras", "font_files")


class BrandEditState(rx.State):
    """The page's mode — the kit itself lives in `CreativeState` / `BrandWizardState`."""

    #: The single editing view is showing (else Resultados e insights, or Tu voz first).
    editing: bool = False
    #: The section open for editing ("" for none) — one at a time.
    open_section: str = ""
    #: "Ahora no" on Tu voz y tono: this visit goes to the results; the next one asks again.
    voice_skipped: bool = False
    #: What the open section had when it was opened, for "Cancelar".
    _before: dict[str, Any] = {}

    @rx.event
    async def restart(self) -> None:
        """Every visit opens on what is still to configure, else on the results — and
        waits for the saved details before deciding (`BrandConnectState.details_loaded`)."""
        self.editing = False
        self.open_section = ""
        self.voice_skipped = False
        self._before = {}
        connect = await self.get_state(BrandConnectState)
        connect.details_loaded = False

    @rx.event
    def start_editing(self) -> None:
        self.editing = True

    @rx.event
    async def show_results(self) -> None:
        """Back to Resultados e insights; a section left open puts back what it had."""
        await self._put_back()
        self.editing = False

    @rx.event
    async def open(self, key: str) -> None:
        """Open one section; another one left open puts back its unsaved changes first."""
        if key not in SECTION_KEYS or key == self.open_section:
            return
        await self._put_back()
        creative = await self.get_state(CreativeState)
        wizard = await self.get_state(BrandWizardState)
        self._before = {
            "form": dataclasses.asdict(creative._kit_form()),
            **{field: _copy(getattr(wizard, field)) for field in _ASSET_FIELDS},
        }
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

    @rx.event(background=True)
    async def save_section(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """A section's "Guardar": the whole kit is written (`save_brand_kit`); on success
        the section closes with its changes kept, and says so with a toast — not the
        callout the wizards leave on the page (§ 2026-10-05, no inline notices)."""
        from .brand_finish import save_brand_kit

        async with self:
            connect = await self.get_state(BrandConnectState)
            was = connect.voice_configured
            if self.open_section == VOICE_SECTION:
                # saving Voz y tono IS configuring it, cloned voice or not
                connect.voice_configured = True
        saved = await save_brand_kit(self)
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

    @rx.event(background=True)
    async def save_voice(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """Tu voz y tono's "Guardar voz" when it opens the page: marks it configured (the
        page stops opening on it) and saves the kit with its tone; then the results."""
        from .brand_finish import save_brand_kit

        async with self:
            connect = await self.get_state(BrandConnectState)
            was = connect.voice_configured
            connect.voice_configured = True
        saved = await save_brand_kit(self)
        async with self:
            if not saved:
                connect = await self.get_state(BrandConnectState)
                connect.voice_configured = was
            else:
                self.open_section = ""
                self._before = {}
                creative = await self.get_state(CreativeState)
                creative.kit_notice = ""
                creative.tone_saved_custom = creative.tone_is_custom()
        if saved:
            yield brand_documents.notify("Voz y tono guardados.", "ok")


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
    blurb = next(text for k, _t, _i, text in SECTIONS if k == key)
    return rx.text(blurb, size="2", color=T.TEXT_MUTED)


def _editor(key: str) -> tuple[rx.Component, ...]:
    lists = {spec[0]: spec for spec in _KIT_LISTS}
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
    return (
        _kit_list_editor(*lists["banned"]),
        _kit_list_editor(*lists["claims"]),
        callout("Esto se comprueba siempre, incluso si desactivas el resto.", "warn"),
    )


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
                        "Editar",
                        variant="soft",
                        size="2",
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
                rx.vstack(
                    *_editor(key),
                    rx.hstack(
                        rx.spacer(),
                        rx.button(
                            "Cancelar",
                            variant="soft",
                            color_scheme="gray",
                            size="2",
                            on_click=BrandEditState.cancel,
                            disabled=CreativeState.kit_saving,
                        ),
                        rx.button(
                            rx.icon("save", size=T.ICON_SM),
                            "Guardar",
                            size="2",
                            on_click=BrandEditState.save_section,
                            loading=CreativeState.kit_saving,
                            disabled=_busy(),
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
        scroll_margin_top="1rem",
    )


def _edit_view() -> rx.Component:
    """The sections, one column, centred (§ request 2026-10-05: no side index), under
    «Tu avatar animado» (§ request 2026-10-19 — generated, so it has no «Editar»)."""
    return rx.vstack(
        brand_avatar_card(),
        *(_section(*spec) for spec in SECTIONS),
        spacing="3",
        width="100%",
        max_width="46rem",
        align_self="center",
        class_name="q-settle",
    )


# --------------------------------------------------------------------------------------
# Tu voz y tono first, and Resultados e insights
# --------------------------------------------------------------------------------------


def _voice_first_view() -> rx.Component:
    """What is still to configure, before anything else (§ request 2026-10-05)."""
    return rx.vstack(
        callout(
            "Te falta configurar tu voz y cómo suena tu marca. Lo usamos al generar vídeos "
            "y textos con tu marca.",
            "warn",
            icon="mic",
        ),
        card(
            rx.vstack(
                rx.hstack(
                    _section_icon("mic"),
                    rx.vstack(
                        rx.text("Voz y tono", size="3", weight="bold"),
                        rx.text(
                            "Graba o sube tu voz, clónala si quieres y ajusta los cuatro ejes.",
                            size="2",
                            color=T.TEXT_MUTED,
                        ),
                        spacing="1",
                        align_items="start",
                    ),
                    spacing="3",
                    align="center",
                    width="100%",
                ),
                *_editor(VOICE_SECTION),
                rx.hstack(
                    rx.spacer(),
                    rx.button(
                        "Ahora no",
                        variant="soft",
                        color_scheme="gray",
                        size="2",
                        on_click=BrandEditState.skip_voice,
                    ),
                    rx.button(
                        rx.icon("save", size=T.ICON_SM),
                        "Guardar voz",
                        size="2",
                        on_click=BrandEditState.save_voice,
                        loading=CreativeState.kit_saving,
                        disabled=_busy(),
                    ),
                    spacing="2",
                    width="100%",
                ),
                spacing="4",
                width="100%",
                align_items="stretch",
            ),
            class_name="q-card q-kit-section--open",
        ),
        spacing="4",
        width="100%",
        max_width="46rem",
        align_self="center",
        class_name="q-settle",
    )


def _results_view() -> rx.Component:
    """Resultados e insights, from what is stored — the same screen as the wizard's final
    one: the profile header while the saved read has it, then the referentes — one card
    grid, or the influence ranking once something was sorted as referente or
    competencia."""
    has_referentes = (BrandConnectState.discovered_accounts.length() > 0) | (
        BrandConnectState.has_sorted
    )
    return rx.cond(
        BrandConnectState.referentes_loading,
        _loading_view("Cargando tus referentes"),
        rx.vstack(
            rx.cond(BrandConnectState.profile_username != "", _insights_header()),
            rx.cond(
                has_referentes,
                rx.cond(BrandConnectState.has_ranking, _ranking_panel(), _discovery_list()),
                callout(
                    "Todavía no hay referentes guardados para esta marca: se buscan al "
                    "conectar tus redes al crear el Brand Kit, o agrégalos a mano.",
                    "info",
                ),
            ),
            # § request 2026-10-05: a referente, a competitor or a detractor the search
            # did not find, added by hand — the wizard's own form (`_manual_section`)
            _manual_section(with_chips=False),
            spacing="5",
            width="100%",
            max_width=_RESULTS_COLUMN_MAX,
            align_self="center",
            align_items="stretch",
            class_name="q-settle",
        ),
    )


def _header_action() -> rx.Component:
    return rx.cond(
        BrandEditState.editing,
        rx.button(
            rx.icon("chart-bar", size=T.ICON_SM),
            "Ver resultados",
            variant="soft",
            size="2",
            on_click=BrandEditState.show_results,
        ),
        rx.button(
            rx.icon("pencil", size=T.ICON_SM),
            "Editar Brand Kit",
            # P3, one solid per screen: while Tu voz y tono is what the page shows, its
            # "Guardar voz" is the primary action and this one steps back to soft
            variant=rx.cond(needs_voice(), "soft", "solid"),
            size="2",
            on_click=BrandEditState.start_editing,
        ),
    )


def _subtitle() -> rx.Var[str]:
    return rx.cond(
        BrandEditState.editing,
        "Edita cada sección y guárdala por separado.",
        rx.cond(
            needs_voice(),
            "Antes de nada, termina de configurar tu marca.",
            "Tus referentes y tu competencia, en orden de influencia.",
        ),
    )


def brand_edit_index() -> rx.Component:
    loading = CreativeState.kit_loading | ~BrandConnectState.details_loaded
    return app_shell(
        page_header("Tu marca", _subtitle(), _header_action(), title_size="7"),
        page_body(
            rx.vstack(
                rx.cond(CreativeState.kit_error != "", callout(CreativeState.kit_error, "error")),
                rx.cond(
                    CreativeState.kit_notice != "",
                    callout(CreativeState.kit_notice, "ok", icon="circle-check"),
                ),
                rx.cond(
                    loading,
                    _loading_view("Cargando tu marca"),
                    rx.cond(
                        BrandEditState.editing,
                        _edit_view(),
                        rx.cond(needs_voice(), _voice_first_view(), _results_view()),
                    ),
                ),
                spacing="4",
                width="100%",
            ),
        ),
    )
