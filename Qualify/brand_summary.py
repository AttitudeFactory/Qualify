"""TEMPORAL (pruebas) — Marca (/brand) as a read-only summary of the finished Brand Kit
(§ request 2026-10-01: "cuando se complete el brandkit, en el apartado de marca solo el
resumen sin poder editar nada y un botón para añadir uno nuevo y reemplazar el que está —
por ahora solo para pruebas, déjalo documentado para posteriormente eliminarlo").

Documented for its removal in `docs/brand-kit-resumen-temporal.md`.

- A brand WITH a saved kit lands on this summary: what was saved, nothing editable
  (editing lives in Negocio → Brand Kit, `/brand/kit`).
- "Crear uno nuevo" (after a confirmation) starts an EMPTY wizard that will REPLACE the
  saved kit when finished (`BrandWizardState.replacing_kit`): the session's kit draft,
  brandboard and answers are cleared and nothing saved is loaded back into it. The saved
  kit stays active until the new one is finished; "Cancelar" goes back to it.
- A brand WITHOUT a kit lands on the usual question (`brand_choice_index`).

Reads straight from what is stored (`creative_provider.load_kit_form`,
`brand_finish.load_saved`, the voice clone) — never the session's draft — so the summary
shows the kit as it really is."""

from __future__ import annotations

import asyncio
import logging

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .brand_finish import load_saved, session_ids
from .creative_provider import load_kit_form
from .creative_state import CreativeState
from .creative_vm import KitFormVM
from .creative_wizard_pages import (
    LOGO_VERSIONS,
    BrandConnectState,
    BrandWizardState,
    brand_choice_index,
)
from .r2_media import BACKEND_BASE
from .ui import (
    app_shell,
    callout,
    card,
    page_body,
    page_header,
    progress_panel,
    section,
    tag,
)
from .ui import tokens as T
from .voice_lab import VoiceLabState, brand_voice_clone

logger = logging.getLogger(__name__)

_TONE_AXES = (
    ("formal", "coloquial", "tone_formal_casual"),
    ("sobrio", "entusiasta", "tone_sober_enthusiastic"),
    ("técnico", "llano", "tone_technical_plain"),
    ("breve", "elaborado", "tone_brief_elaborate"),
)
_VERSION_NAMES = {key: name for key, name, _blurb in LOGO_VERSIONS}


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


class BrandSummaryState(rx.State):
    loading: bool = True
    has_kit: bool = False
    error: str = ""
    positioning: str = ""
    audience: str = ""
    #: {"poles", "value"} per tone axis.
    tone: list[dict[str, str]] = []
    palette: list[str] = []
    do_examples: list[str] = []
    dont_examples: list[str] = []
    cta_patterns: list[str] = []
    banned_words: list[str] = []
    forbidden_claims: list[str] = []
    #: {"name", "context", "src"} per brandboard file.
    files: list[dict[str, str]] = []
    sector: str = ""
    location: str = ""
    hashtags: list[str] = []
    account: str = ""
    voice_clone: str = ""

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            self.loading = True
            self.error = ""
        ids = await session_ids(self)
        if ids is None:
            async with self:
                self.loading = False
                self.has_kit = False
            return
        try:
            form = await asyncio.to_thread(load_kit_form, ids[0], ids[1])
            saved = await asyncio.to_thread(load_saved, ids[0], ids[1])
            clone = await asyncio.to_thread(brand_voice_clone, ids[0], ids[1])
        except SQLAlchemyError as exc:
            logger.warning("brand summary unreadable: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = "No se pudo leer tu Brand Kit."
            return
        async with self:
            self.loading = False
            self.has_kit = form is not None
            if form is None:
                return
            self._show(form)
            files = []
            for file in saved.files:
                if file.kind == "logo_version":
                    name = _VERSION_NAMES.get(file.slot, file.slot)
                elif file.kind == "extra":
                    name = file.label or file.name or "Elemento"
                else:
                    name = "Logo"
                view = saved.views.get(file.key, "")
                files.append({"name": name, "context": file.context, "src": view})
            self.files = files
            connect, profile = saved.details.connect, saved.details.profile
            self.sector = str(connect.get("rubro_text") or connect.get("sector") or "")
            self.location = ", ".join(
                p for p in (str(connect.get("city", "")), str(connect.get("country_code", ""))) if p
            )
            self.hashtags = [
                f"#{item.get('tag', '')}"
                for item in connect.get("hashtags", [])
                if isinstance(item, dict) and item.get("tag")
            ]
            username = str(profile.get("username", ""))
            followers = str(profile.get("followers", ""))
            self.account = (
                f"@{username} · {followers} seguidores" if username and followers else username
            )
            self.voice_clone = clone.name if clone is not None and clone.is_ready else ""

    def _show(self, form: KitFormVM) -> None:
        self.positioning = form.positioning
        self.audience = form.audience
        self.tone = [
            {"poles": f"{low} ↔ {high}", "value": str(getattr(form, field))}
            for low, high, field in _TONE_AXES
        ]
        self.palette = [c.strip() for c in form.palette_rgb.split(",") if c.strip()]
        self.do_examples = _lines(form.do_examples)
        self.dont_examples = _lines(form.dont_examples)
        self.cta_patterns = _lines(form.cta_patterns)
        self.banned_words = _lines(form.banned_words)
        self.forbidden_claims = _lines(form.forbidden_claims)

    @rx.event
    async def start_replacement(self) -> None:
        """TEMPORAL — "Crear uno nuevo": an empty wizard that replaces this kit when it
        is finished. The saved kit is NOT touched now: only the session's draft is."""
        creative = await self.get_state(CreativeState)
        creative._apply_kit_form(KitFormVM())
        creative._kit_draft_loaded = True  # do not load the saved kit back into the draft
        creative.kit_error = ""
        creative.kit_notice = ""
        wizard = await self.get_state(BrandWizardState)
        wizard._reset_fields()
        wizard.replacing_kit = True
        connect = await self.get_state(BrandConnectState)
        connect._reset_fields()
        voice = await self.get_state(VoiceLabState)
        voice.sample_key = ""
        voice.sample_name = ""
        voice.analysis_rows = []
        voice.analysis_error = ""

    @rx.event
    async def cancel_replacement(self) -> None:
        """Back to the saved kit: the next visit to a wizard loads it again."""
        wizard = await self.get_state(BrandWizardState)
        wizard._reset_fields()
        creative = await self.get_state(CreativeState)
        creative._kit_draft_loaded = False


# ---------------------------------------------------------------------------------------
# UI


def _text_row(label: str, value: rx.Var[str]) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="1", color=T.TEXT_MUTED),
        rx.cond(
            value != "",
            rx.text(value, size="2"),
            rx.text("Sin definir", size="2", color=T.TEXT_FAINT),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _tags_row(label: str, items: rx.Var[list[str]], fallback: str = "Ninguno") -> rx.Component:
    return rx.vstack(
        rx.text(label, size="1", color=T.TEXT_MUTED),
        rx.cond(
            items.length() > 0,
            rx.flex(rx.foreach(items, lambda item: tag(item, size="2")), wrap="wrap", gap="2"),
            rx.text(fallback, size="2", color=T.TEXT_FAINT),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _panel(*children: rx.Component) -> rx.Component:
    return card(
        rx.vstack(*children, spacing="3", width="100%", align_items="start"),
        padding="1.25rem 1.5rem",
        width="100%",
    )


def _tone_row(row: rx.Var[dict[str, str]]) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(row["poles"], size="2"),
            rx.spacer(),
            rx.text(row["value"], size="2", color=T.TEXT_MUTED, class_name="q-nums"),
            width="100%",
        ),
        rx.progress(value=row["value"].to(int), max=100, width="100%"),
        spacing="1",
        width="100%",
    )


def _file_tile(file: rx.Var[dict[str, str]]) -> rx.Component:
    return rx.vstack(
        rx.cond(
            file["src"] != "",
            rx.image(
                src=BACKEND_BASE + file["src"],
                alt=file["name"],
                height="5rem",
                width="100%",
                object_fit="contain",
            ),
            rx.center(rx.icon("image", size=22, color=T.TEXT_FAINT), height="5rem", width="100%"),
        ),
        rx.text(file["name"], size="2", weight="medium"),
        rx.cond(file["context"] != "", rx.text(file["context"], size="1", color=T.TEXT_MUTED)),
        spacing="2",
        align_items="start",
        border=T.BORDER,
        border_radius=T.RADIUS_CARD,
        padding="0.75rem",
        width="100%",
    )


def _replace_button() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(rx.icon("refresh-cw", size=T.ICON_SM), "Crear uno nuevo", size="2")
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title("¿Crear un Brand Kit nuevo?"),
            rx.alert_dialog.description(
                "Empiezas de cero. Cuando lo termines, reemplazará por completo al actual "
                "(kit, brandboard y respuestas). Hasta entonces el actual sigue activo.",
                size="2",
            ),
            rx.hstack(
                rx.alert_dialog.cancel(rx.button("Cancelar", variant="soft", color_scheme="gray")),
                rx.alert_dialog.action(
                    rx.button("Crear uno nuevo", on_click=BrandSummaryState.start_replacement)
                ),
                spacing="3",
                justify="end",
                width="100%",
                margin_top="1rem",
            ),
        ),
    )


def _summary() -> rx.Component:
    return app_shell(
        page_header(
            "Tu Brand Kit",
            "Así quedó tu marca. Para cambiar algo, ve a Negocio → Brand Kit.",
            _replace_button(),
        ),
        page_body(
            rx.vstack(
                callout(
                    "Vista temporal de pruebas: aquí solo se ve el resumen; crear uno nuevo "
                    "reemplaza el actual al terminarlo.",
                    "info",
                ),
                rx.grid(
                    section(
                        "Identidad",
                        _panel(
                            _text_row("Posicionamiento", BrandSummaryState.positioning),
                            _text_row("Audiencia", BrandSummaryState.audience),
                            _text_row("Rubro", BrandSummaryState.sector),
                            _text_row("Ubicación", BrandSummaryState.location),
                            _text_row("Cuenta", BrandSummaryState.account),
                        ),
                    ),
                    section(
                        "Tono y voz",
                        _panel(
                            rx.foreach(BrandSummaryState.tone, _tone_row),
                            _text_row("Voz clonada", BrandSummaryState.voice_clone),
                        ),
                    ),
                    columns=rx.breakpoints(initial="1", md="2"),
                    spacing="5",
                    width="100%",
                ),
                section(
                    "Brandboard",
                    _panel(
                        rx.text("Paleta", size="1", color=T.TEXT_MUTED),
                        rx.cond(
                            BrandSummaryState.palette.length() > 0,
                            rx.hstack(
                                rx.foreach(
                                    BrandSummaryState.palette,
                                    lambda colour: rx.box(
                                        title=colour,
                                        width="1.75rem",
                                        height="1.75rem",
                                        border_radius="9999px",
                                        background=colour,
                                        box_shadow=f"inset 0 0 0 1px {rx.color('gray', 7)}",
                                    ),
                                ),
                                spacing="2",
                                wrap="wrap",
                            ),
                            rx.text("Sin colores", size="2", color=T.TEXT_FAINT),
                        ),
                        rx.cond(
                            BrandSummaryState.files.length() > 0,
                            rx.box(
                                rx.foreach(BrandSummaryState.files, _file_tile),
                                display="grid",
                                grid_template_columns=(
                                    "repeat(auto-fill, minmax(min(100%, 12rem), 1fr))"
                                ),
                                gap="0.75rem",
                                width="100%",
                            ),
                            rx.text(
                                "Sin logo ni elementos guardados.", size="2", color=T.TEXT_FAINT
                            ),
                        ),
                    ),
                ),
                rx.grid(
                    section(
                        "Cómo habla",
                        _panel(
                            _tags_row("Ejemplos que SÍ", BrandSummaryState.do_examples),
                            _tags_row("Ejemplos que NO", BrandSummaryState.dont_examples),
                            _tags_row("Llamados a la acción", BrandSummaryState.cta_patterns),
                            _tags_row("Hashtags", BrandSummaryState.hashtags),
                        ),
                    ),
                    section(
                        "Lo que nunca dice",
                        _panel(
                            _tags_row(
                                "Palabras vetadas", BrandSummaryState.banned_words, "Ninguna"
                            ),
                            _tags_row("Claims prohibidos", BrandSummaryState.forbidden_claims),
                        ),
                    ),
                    columns=rx.breakpoints(initial="1", md="2"),
                    spacing="5",
                    width="100%",
                ),
                spacing="6",
                width="100%",
                max_width="72rem",
            ),
        ),
    )


def _replacing_notice() -> rx.Component:
    return rx.vstack(
        callout(
            "Estás creando un Brand Kit nuevo: reemplazará al actual cuando lo termines.",
            "warn",
        ),
        rx.button(
            rx.icon("undo-2", size=T.ICON_SM),
            "Volver al Brand Kit actual",
            variant="soft",
            size="1",
            on_click=BrandSummaryState.cancel_replacement,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def brand_home_index() -> rx.Component:
    """/brand: the summary for a finished kit (TEMPORAL), the usual question otherwise."""
    return rx.cond(
        BrandSummaryState.loading,
        # § request 2026-10-02: every Brand Kit loader is the progress-bar one
        app_shell(
            page_header("Brandkit", "Cargando tu marca…"),
            page_body(progress_panel("Cargando tu marca", creep_seconds=6)),
        ),
        rx.cond(
            BrandSummaryState.has_kit & ~BrandWizardState.replacing_kit,
            _summary(),
            brand_choice_index(
                rx.cond(BrandWizardState.replacing_kit, _replacing_notice(), rx.fragment())
            ),
        ),
    )
