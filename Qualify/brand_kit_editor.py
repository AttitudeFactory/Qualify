"""/brand/kit — edit an existing Brand Kit (§ request 2026-09-30), from the sidebar's
"Negocio" block, laid out as views exactly like the Brand Kit wizard: one decision per
screen, "Paso N de M", Atrás / Continuar, and "Guardar cambios" on the last view,
Resultados e insights — the brand's referentes as they were last left, read back from
Postgres (`BrandConnectState.load_saved_referentes`), sortable and rankable as in the
wizard.

The wizards (/brand/manual, /brand/connect) BUILD a kit; this walks the same screens to
change one. Every view is the wizard's own step renderer on the same `CreativeState` /
`BrandWizardState`, so the two can never drift; only the cursor is this module's
(`BrandEditState`). There is no brief and no ¿Tienes brandboard? question (the
brandboard view shows its tiles directly); an edit ends by saving.

Tu brandboard's logo versions and other elements are session-only in the wizard too —
nothing writes them to the kit yet (see `creative_wizard_pages`' "NOT YET PERSISTED").
The view says so rather than letting "Guardar cambios" imply otherwise."""

from __future__ import annotations

import reflex as rx

from .creative_state import CreativeState
from .creative_wizard_pages import (  # the wizard's own views and chrome, shared on purpose
    _CONTROL_RADIUS,
    _RESULTS_COLUMN_MAX,
    BrandConnectState,
    BrandWizardState,
    _brand_extras,
    _discovery_phase,
    _identity_complete,
    _insights_metrics,
    _insights_profile_card,
    _loading_view,
    _logo_versions,
    _ranking_panel,
    _step_body,
    _step_confirm,
    _step_counter,
    _step_identity,
    _step_palette,
    _step_restrictions,
    _step_voice,
    _step_voice_examples,
    _step_voice_tone,
)
from .ui import app_shell, callout, card, page_body, page_header
from .ui import tokens as T
from .voice_lab import VoiceLabState

#: Title + subtitle per view; the index IS the cursor value.
EDIT_STEPS: tuple[tuple[str, str], ...] = (
    ("¿Quién es la marca?", "Lo que define su lugar y a quién le habla."),
    ("Tu brandboard", "Las versiones de tu logo y los otros elementos de la marca."),
    ("Paleta de colores", "Los colores con los que se te reconoce."),
    ("Tu voz", "Grábala o súbela: ajustamos el tono con ella y, si quieres, la clonamos."),
    ("¿Cómo suena?", "Ajusta el tono en cuatro ejes."),
    ("Enséñale a hablar", "Ejemplos reales valen más que cualquier descripción."),
    ("Lo que nunca debe decir", "Reglas duras: una violación es un rechazo."),
    ("¿Todo correcto?", "Revisa y edita lo que haga falta."),
    ("Resultados e insights", "Tus referentes y tu competencia, en orden de influencia."),
)
EDIT_LAST = len(EDIT_STEPS) - 1
_CONFIRM_STEP = EDIT_LAST - 1
_BRANDBOARD_STEP = 1
_PALETTE_STEP = 2
_VOICE_STEP = 3
_EXAMPLES_STEP = 5


class BrandEditState(rx.State):
    """The editor's cursor — the kit itself lives in `CreativeState`."""

    step: int = 0

    @rx.event
    def restart(self) -> None:
        """Every visit starts on the first view."""
        self.step = 0

    @rx.event
    def next_step(self) -> None:
        self.step = min(self.step + 1, EDIT_LAST)

    @rx.event
    def prev_step(self) -> None:
        self.step = max(self.step - 1, 0)

    @rx.event(background=True)
    async def save(self) -> None:
        """Guardar cambios: everything — the kit, the brandboard's files, the answers
        (`brand_finish.save_brand_kit`); the outcome shows above the card."""
        from .brand_finish import save_brand_kit

        await save_brand_kit(self)


def _step_brandboard() -> rx.Component:
    """Tu brandboard's tiles, straight away: editing a kit does not ask again whether
    there is a brandboard."""
    return _step_body(
        rx.cond(BrandWizardState.logo_error != "", callout(BrandWizardState.logo_error, "error")),
        callout(
            "Por ahora las versiones del logo y los otros elementos duran solo esta sesión: "
            "todavía no se guardan en la marca.",
            "info",
        ),
        _logo_versions(),
        _brand_extras(),
    )


def _step_insights() -> rx.Component:
    """Resultados e insights, from what is stored: the profile and its metrics only
    while this session still holds the read (the wizard's finish clears it), then the
    referentes — the influence ranking once something was sorted, else each category's
    list, like the wizard's own final screen."""
    has_referentes = (BrandConnectState.discovered_accounts.length() > 0) | (
        BrandConnectState.has_sorted
    )
    main = _step_body(
        rx.cond(BrandConnectState.profile_username != "", _insights_profile_card()),
        _insights_metrics(),
        rx.cond(
            has_referentes,
            rx.cond(
                BrandConnectState.has_sorted,
                rx.fragment(),
                rx.vstack(
                    _discovery_phase(
                        BrandConnectState.sector_title,
                        "Referentes del sector",
                        BrandConnectState.sector_note,
                        BrandConnectState.sector_accounts,
                    ),
                    _discovery_phase(
                        BrandConnectState.national_title,
                        "Referentes nacionales",
                        BrandConnectState.national_note,
                        BrandConnectState.national_accounts,
                    ),
                    _discovery_phase(
                        BrandConnectState.local_title,
                        "Referentes locales",
                        BrandConnectState.local_note,
                        BrandConnectState.local_accounts,
                    ),
                    spacing="4",
                    width="100%",
                ),
            ),
            callout(
                "Todavía no hay referentes guardados para esta marca: se buscan al conectar "
                "tus redes, en Marca.",
                "info",
            ),
        ),
        icon="trophy",
    )
    return rx.cond(
        BrandConnectState.referentes_loading,
        _loading_view("Cargando tus referentes"),
        rx.vstack(
            rx.box(main, width="100%", max_width="34rem", align_self="center"),
            rx.cond(
                BrandConnectState.has_sorted,
                rx.box(_ranking_panel(), width="100%", padding_top="1.25rem", border_top=T.BORDER),
            ),
            spacing="4",
            width="100%",
        ),
    )


def _window() -> rx.Component:
    return rx.match(
        BrandEditState.step,
        (0, _step_identity()),
        (_BRANDBOARD_STEP, _step_brandboard()),
        (_PALETTE_STEP, _step_palette()),
        (_VOICE_STEP, _step_voice()),
        (4, _step_voice_tone()),
        (_EXAMPLES_STEP, _step_voice_examples()),
        (6, _step_restrictions()),
        (_CONFIRM_STEP, _step_confirm()),
        (EDIT_LAST, _step_insights()),
        _step_identity(),
    )


def _heading_for(index: int) -> rx.Var[str]:
    return rx.match(
        BrandEditState.step,
        *((position, text[index]) for position, text in enumerate(EDIT_STEPS)),
        EDIT_STEPS[0][index],
    )


def _can_continue() -> rx.Var[bool]:
    """The wizard's own requirements, for the views that have one."""
    return rx.cond(
        VoiceLabState.analyzing,
        False,  # § 2026-10-01: nothing moves while the voice is being analysed
        rx.match(
            BrandEditState.step,
            (0, _identity_complete()),
            (_PALETTE_STEP, CreativeState.kit_palette != ""),
            (_EXAMPLES_STEP, CreativeState.kit_do_examples != ""),
            True,
        ),
    )


def _column_width() -> rx.Var[str]:
    """Same widths as the wizard: the brandboard's tiles take the card's whole width,
    ¿Todo correcto? gets room for its lists, Resultados e insights for its ranking
    once something was sorted, and every other view keeps 34rem."""
    return rx.cond(
        BrandEditState.step == _BRANDBOARD_STEP,
        "100%",
        rx.cond(
            BrandEditState.step == _CONFIRM_STEP,
            "46rem",
            rx.cond(
                (BrandEditState.step == EDIT_LAST) & BrandConnectState.has_sorted,
                _RESULTS_COLUMN_MAX,
                "34rem",
            ),
        ),
    )


def _controls() -> rx.Component:
    return rx.hstack(
        rx.cond(
            BrandEditState.step > 0,
            rx.button(
                rx.icon("chevron-left", size=T.ICON_SM),
                "Atrás",
                variant="ghost",
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandEditState.prev_step,
                disabled=VoiceLabState.analyzing,
            ),
        ),
        rx.spacer(),
        rx.cond(
            BrandEditState.step == EDIT_LAST,
            # the flow's one solid action (§5.5): an edit ends by saving
            rx.button(
                rx.icon("save", size=T.ICON_SM),
                "Guardar cambios",
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandEditState.save,
                loading=CreativeState.kit_saving,
            ),
            rx.button(
                "Continuar",
                rx.icon("chevron-right", size=T.ICON_SM),
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandEditState.next_step,
                disabled=~_can_continue(),
            ),
        ),
        width="100%",
        align="center",
        spacing="3",
    )


def brand_edit_index() -> rx.Component:
    """The wizard's page shape (`creative_wizard_pages.brand_manual_index`): the header
    with the step counter, one card filling the panel, the view centred in it and the
    controls pinned to its bottom."""
    return app_shell(
        page_header(
            _heading_for(0),
            _heading_for(1),
            kicker=_step_counter(BrandEditState.step, len(EDIT_STEPS)),
            title_size="8",
        ),
        page_body(
            rx.vstack(
                rx.vstack(
                    rx.cond(
                        CreativeState.kit_error != "", callout(CreativeState.kit_error, "error")
                    ),
                    rx.cond(
                        CreativeState.kit_notice != "",
                        callout(CreativeState.kit_notice, "ok", icon="circle-check"),
                    ),
                    spacing="3",
                    width="100%",
                    max_width="34rem",
                    align_self="center",
                    align_items="center",
                ),
                rx.cond(
                    CreativeState.kit_loading,
                    card(
                        _loading_view("Cargando tu marca"),
                        padding="1.75rem",
                        width="100%",
                        flex="1",
                        display="flex",
                        align_items="center",
                        justify_content="center",
                    ),
                    card(
                        rx.vstack(
                            _window(),
                            width="100%",
                            max_width=_column_width(),
                            align_self="center",
                            align_items="center",
                            flex="1",
                            justify_content="center",
                        ),
                        _controls(),
                        padding="1.75rem",
                        width="100%",
                        flex="1",
                        display="flex",
                        flex_direction="column",
                        justify_content="space-between",
                        # remount per view so the frame settles in too (the wizard's
                        # own note on this `key` explains why it sits on the card)
                        key=BrandEditState.step.to_string(),
                        gap="1.5rem",
                    ),
                ),
                spacing="4",
                width="100%",
                flex="1",
                min_height="0",
            ),
        ),
    )
