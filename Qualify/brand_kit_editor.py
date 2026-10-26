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
    ("marca", "Marca", "compass", "Qué te hace distinto, quién te compra y tu documento de marca."),
    ("brandboard", "Logo", "image", "Las versiones de tu logo y los otros elementos."),
    ("tipografia", "Tu letra", "type", "La letra con la que se te reconoce."),
    ("paleta", "Colores", "palette", "Los colores con los que se te reconoce."),
    ("voz", "Voz y tono", "mic", "Tu voz grabada y cómo suena tu marca."),
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
)
SECTION_KEYS = frozenset(key for key, *_ in SECTIONS)
VOICE_SECTION = "voz"

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

    @rx.event
    async def restart(self) -> None:
        """Every visit opens on the summary of the brand, every section closed — and waits
        for the saved details before showing it (`BrandConnectState.details_loaded`)."""
        self.open_section = ""
        self.referentes_open = False
        self.voice_skipped = False
        self._before = {}
        connect = await self.get_state(BrandConnectState)
        connect.details_loaded = False

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
                rx.vstack(
                    *_editor(key),
                    rx.hstack(
                        rx.spacer(),
                        rx.button(
                            "Cancelar",
                            variant="soft",
                            color_scheme="gray",
                            size="3",
                            on_click=BrandEditState.cancel,
                            disabled=CreativeState.kit_saving,
                        ),
                        rx.button(
                            rx.icon("save", size=T.ICON_SM),
                            "Guardar",
                            size="3",
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


def _referentes_body() -> rx.Component:
    """The brand's referentes as last left, read back from Postgres — one card grid, or
    the influence ranking once something was sorted as referente or competencia — and
    the form to add one by hand. Every change there saves on its own."""
    has_referentes = (BrandConnectState.discovered_accounts.length() > 0) | (
        BrandConnectState.has_sorted
    )
    return rx.cond(
        BrandConnectState.referentes_loading,
        _loading_view("Cargando los negocios parecidos al tuyo"),
        rx.vstack(
            rx.cond(BrandConnectState.profile_username != "", _insights_header()),
            rx.cond(
                has_referentes,
                rx.cond(BrandConnectState.has_ranking, _ranking_panel(), _discovery_list()),
                callout(
                    "Todavía no hay negocios parecidos guardados. Los buscamos cuando conectas "
                    "tu Instagram al preparar tu marca, o puedes agregarlos a mano.",
                    "info",
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
            spacing="3",
            width="100%",
            align_items="stretch",
        ),
        id="seccion-referentes",
        class_name=rx.cond(is_open, "q-card q-kit-section--open", "q-card"),
        scroll_margin_top=T.SCROLL_MARGIN_TOP,
    )


def _summary_view() -> rx.Component:
    """The page by default (m-24842970): the brand by sections, one column, centred
    (§ request 2026-10-05: no side index) — the optional voice row first while it is
    pending, «Tu avatar animado» (§ request 2026-10-19 — generated, so it has no
    «Cambiar»), the kit's sections and, last, «Negocios parecidos al tuyo»."""
    return rx.vstack(
        rx.cond(needs_voice(), _voice_row()),
        brand_avatar_card(),
        *(_section(*spec) for spec in SECTIONS),
        _referentes_section(),
        spacing="3",
        width="100%",
        max_width="46rem",
        align_self="center",
        class_name="q-settle",
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
                rx.cond(CreativeState.kit_error != "", callout(CreativeState.kit_error, "error")),
                rx.cond(
                    CreativeState.kit_notice != "",
                    callout(CreativeState.kit_notice, "ok", icon="circle-check"),
                ),
                rx.cond(loading, _loading_view("Cargando tu marca"), _summary_view()),
                spacing="4",
                width="100%",
            ),
        ),
    )
