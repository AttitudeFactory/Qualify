"""Brand Kit as a nine-step setup flow — the editor that replaced
`creative_pages.brand_index`'s accordion in routing.

The replacement is routing-only: `creative_pages.py` and `creative_state.py` are
untouched, and `brand_index` still exists in the code, simply without a route. The kit
fields that already exist bind to the SAME `CreativeState` vars and save through the
SAME `save_kit_form` handler, so re-registering the accordion at any time would edit
the same row this screen does.

Screens:
  - `brand_choice_index`  (/brand)        — the entry fork.
  - `brand_manual_index`  (/brand/manual) — the nine-step flow.

Shape of the flow (one decision per screen, macOS-setup style: one big title, a small
step counter, the content, and small back/next controls at the bottom — no step rail):

    1 Suscripción      2 Identidad     3 ¿Tienes logo?   4 Logo (branches on 3)
    5 Paleta           6 Voz · tono    7 Voz · ejemplos  8 Restricciones
    9 Confirmación

NOT YET PERSISTED — several fields here edit state `save_kit_form` does not carry, so
they survive navigation between steps but not a reload:
  - `subscription` and the logo-creation brief: placeholder copy, no columns at all.
  - the staged logo: `brand_kits.logo_asset_key` DOES exist and `creative_provider.
    save_kit` deliberately preserves whatever is stored (so nothing is lost by saving
    here), but no path writes a NEW key. Wiring it means R2 upload + a `logo_asset_key`
    on `KitFormVM`.
Left as a follow-up rather than widening `CreativeState` from this module.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import reflex as rx

from .auth_state import AuthState
from .creative_state import CreativeState
from .tenant import tenant_uuid
from .ui import app_shell, callout, card, page_body
from .ui import tokens as T

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_UPLOAD_FAILED = "No se pudo leer el archivo. Inténtalo de nuevo."

# Title + one-line subtitle per step. The index IS the cursor value, so this tuple is
# the single source of truth for the counter and the heading.
STEPS: tuple[tuple[str, str], ...] = (
    ("Elige tu plan", "Puedes cambiarlo más adelante."),
    ("¿Quién es la marca?", "Lo que define su lugar y a quién le habla."),
    ("¿Tienes logo?", "De tu respuesta depende el siguiente paso."),
    ("Tu logo", "Lo usaremos en cada pieza que generemos."),
    ("Paleta de colores", "Los colores con los que se te reconoce."),
    ("¿Cómo suena?", "Ajusta el tono en cuatro ejes."),
    ("Enséñale a hablar", "Ejemplos reales valen más que cualquier descripción."),
    ("Lo que nunca debe decir", "Reglas duras: una violación es un rechazo."),
    ("¿Todo correcto?", "Revisa antes de guardar."),
)
LAST_STEP = len(STEPS) - 1

# `rx.upload`'s id must be a string literal or a module-level constant — it is what
# links the dropzone to `rx.upload_files(upload_id=...)`.
_LOGO_UPLOAD_ID = "brand_logo"

# Placeholder plans. Copy is deliberately lorem — the real tiers are not decided.
PLANS: tuple[tuple[str, str, str], ...] = (
    ("basico", "Básico", "Lorem ipsum dolor sit amet, consectetur adipiscing elit."),
    ("pro", "Pro", "Sed do eiusmod tempor incididunt ut labore et dolore magna."),
    ("negocio", "Negocio", "Ut enim ad minim veniam, quis nostrud exercitation ullamco."),
    ("agencia", "Agencia", "Duis aute irure dolor in reprehenderit in voluptate velit."),
)


class BrandWizardState(rx.State):
    """The cursor, plus the fields this screen adds that `CreativeState` has no home for.

    Existing kit fields stay in `CreativeState` — a wizard is a navigation concern, not
    a second copy of the record. What lives here is only what is genuinely new.

    Setters are explicit: this Reflex version generates none, the same reason
    `CreativeState` writes its own.
    """

    step: int = 0

    # -- step 1 ---------------------------------------------------------------
    subscription: str = ""

    # -- step 3/4 -------------------------------------------------------------
    has_logo: str = ""  # "si" | "no" | "" (unanswered)
    logo_brief_1: str = ""
    logo_brief_2: str = ""
    logo_brief_3: str = ""

    # -- staged logo file -----------------------------------------------------
    logo_key: str = ""
    logo_name: str = ""
    logo_error: str = ""

    # -- step 5 ---------------------------------------------------------------
    picker_color: str = "#0A3D2E"

    @rx.event
    async def resume(self) -> None:
        """Open the flow on the FIRST step still missing data, not wherever the cursor
        happened to be left. Runs on page load, after `CreativeState.load_brand` has
        filled the kit — so re-entering never parks you on step 6 while step 2 is empty.

        Two steps are never gaps by construction: the tone sliders always hold a value
        (they default to 50), and the restrictions are legitimately optional. A kit with
        no gaps left opens on the confirmation screen.
        """
        creative = await self.get_state(CreativeState)
        if not self.subscription:
            self.step = 0
        elif not creative.kit_positioning.strip() or not creative.kit_audience.strip():
            self.step = 1
        elif not self.has_logo:
            self.step = 2
        elif self.has_logo == "si" and not self.logo_key:
            self.step = 3
        elif self.has_logo == "no" and not self.logo_brief_1.strip():
            self.step = 3
        elif not creative.kit_palette.strip():
            self.step = 4
        elif not creative.kit_do_examples.strip():
            self.step = 6
        else:
            self.step = LAST_STEP

    @rx.event
    def go_to(self, index: int) -> None:
        """Jump straight to a step. Clamped so a stale client event cannot park the
        cursor outside the flow and render nothing."""
        self.step = max(0, min(index, LAST_STEP))

    @rx.event
    def next_step(self) -> None:
        self.step = min(self.step + 1, LAST_STEP)

    @rx.event
    def prev_step(self) -> None:
        self.step = max(self.step - 1, 0)

    @rx.event
    def select_plan(self, key: str) -> None:
        self.subscription = key

    @rx.event
    def answer_has_logo(self, value: str) -> None:
        """Answering step 3 moves straight on — the question has no other content, so
        making the user press Next again would be a dead click."""
        self.has_logo = value
        self.step = min(self.step + 1, LAST_STEP)

    @rx.event
    def set_logo_brief_1(self, value: str) -> None:
        self.logo_brief_1 = value

    @rx.event
    def set_logo_brief_2(self, value: str) -> None:
        self.logo_brief_2 = value

    @rx.event
    def set_logo_brief_3(self, value: str) -> None:
        self.logo_brief_3 = value

    @rx.event
    def set_picker_color(self, value: str) -> None:
        self.picker_color = value

    @rx.event
    async def commit_picked_color(self) -> None:
        """Append the wheel's colour to the palette `CreativeState` already persists.

        Fired on the picker's blur — i.e. when the OS dialog closes — rather than on
        change: `input[type=color]` emits a change per mouse move while dragging, so
        committing on change would push a dozen intermediate colours into the palette.

        The palette stays a single comma-separated string in `CreativeState` (that is
        what `KitFormVM` saves); this handler only appends to it, so the text field and
        the wheel can never disagree. Joined without spaces so each entry is a clean
        CSS colour when it comes back out as a swatch.
        """
        colour = self.picker_color.strip()
        if not colour:
            return
        creative = await self.get_state(CreativeState)
        parts = [c.strip() for c in creative.kit_palette.split(",") if c.strip()]
        if colour.lower() in [p.lower() for p in parts]:
            return
        parts.append(colour)
        creative.kit_palette = ",".join(parts)

    @rx.event
    async def handle_logo_upload(self, files: list[rx.UploadFile]) -> None:
        """Stage the brand logo and expose it for preview.

        FOREGROUND on purpose: this Reflex version forbids `background=True` on a
        handler that receives `list[rx.UploadFile]` (see `creative_state`'s module
        docstring). The key is tenant-namespaced, the same logout-hygiene rule
        `CreativeState.handle_photo_upload` follows — one tenant's logo can never be
        served to another.
        """
        if not files:
            return
        auth = await self.get_state(AuthState)
        tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            self.logo_error = _NO_SESSION
            return
        upload = files[0]
        try:
            data = await upload.read()
        except Exception:
            self.logo_error = _UPLOAD_FAILED
            return
        name = upload.name or "logo"
        key = f"uploads/{tenant_id}/logo/{uuid4().hex}_{name}"
        target = rx.get_upload_dir() / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.logo_key = key
        self.logo_name = name
        self.logo_error = ""

    @rx.event
    def clear_logo(self) -> None:
        """Drop the staged logo. The file on disk is left alone — it is namespaced and
        unreferenced, and deleting it here would race a preview still being fetched."""
        self.logo_key = ""
        self.logo_name = ""
        self.logo_error = ""


# ---------------------------------------------------------------------------
# Field primitives — local copies of the accordion's, so this module stays standalone


def _labeled_area(
    label: str, value: rx.Var[str], handler: rx.event.EventHandler, placeholder: str = ""
) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        rx.text_area(
            value=value, on_change=handler, placeholder=placeholder, width="100%", rows="3"
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _labeled_input(
    label: str, value: rx.Var[str], handler: rx.event.EventHandler, placeholder: str = ""
) -> rx.Component:
    """Radix's default `size="2"` reads cramped once the rest of the flow is set in the
    bigger macOS-setup type scale — `size="3"` plus a touch of extra height matches the
    weight of the labels and headings around it."""
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        rx.input(
            value=value,
            on_change=handler,
            placeholder=placeholder,
            width="100%",
            size="3",
            height="2.75rem",
            radius="large",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _tone_slider(
    left: str, right: str, value: rx.Var[int], handler: rx.event.EventHandler
) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(left, size="2", color=T.TEXT_MUTED),
            rx.spacer(),
            rx.text(value.to_string(), size="1", color=T.TEXT_FAINT),
            rx.spacer(),
            rx.text(right, size="2", color=T.TEXT_MUTED),
            width="100%",
            align="center",
        ),
        rx.slider(value=[value], on_change=handler, min=0, max=100, step=1, width="100%"),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _step_body(*children: rx.Component) -> rx.Component:
    """Every step centres its content. Fields still span the column, so their labels
    stay left-read while the block itself sits centred under the title."""
    return rx.vstack(*children, spacing="4", width="100%", align_items="center")


def _choice_card(
    title: str,
    description: str,
    selected: rx.Var[bool],
    on_click: rx.event.EventHandler,
) -> rx.Component:
    """A big, quiet button that reads as a card. Selection is a ring, not a fill —
    the surface stays calm while the choice stays unmistakable."""
    return rx.box(
        rx.vstack(
            rx.text(title, size="3", weight="bold"),
            rx.text(description, size="2", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        on_click=on_click,
        cursor="pointer",
        width="100%",
        padding="1rem 1.25rem",
        border_radius=T.RADIUS_CARD,
        background=T.CARD_BG,
        box_shadow=rx.cond(
            selected,
            f"inset 0 0 0 2px {rx.color('accent', 9)}",
            f"inset 0 0 0 1px {rx.color('gray', 6)}",
        ),
        transition=f"box-shadow {T.DUR} {T.EASE}",
        _hover={"box_shadow": f"inset 0 0 0 2px {rx.color('accent', 7)}"},
    )


# ---------------------------------------------------------------------------
# The nine steps


def _step_subscription() -> rx.Component:
    return _step_body(
        *(
            _choice_card(
                label,
                blurb,
                BrandWizardState.subscription == key,
                BrandWizardState.select_plan(key),
            )
            for key, label, blurb in PLANS
        )
    )


def _step_identity() -> rx.Component:
    return _step_body(
        _labeled_area(
            "Posicionamiento",
            CreativeState.kit_positioning,
            CreativeState.set_kit_positioning,
            "Qué es la marca y por qué importa",
        ),
        _labeled_area(
            "Audiencia",
            CreativeState.kit_audience,
            CreativeState.set_kit_audience,
            "A quién le habla",
        ),
    )


def _step_has_logo() -> rx.Component:
    return _step_body(
        _choice_card(
            "Sí, ya tengo uno",
            "Súbelo en el siguiente paso y lo usaremos tal cual.",
            BrandWizardState.has_logo == "si",
            BrandWizardState.answer_has_logo("si"),
        ),
        _choice_card(
            "No, todavía no",
            "Te haremos tres preguntas para proponerte uno.",
            BrandWizardState.has_logo == "no",
            BrandWizardState.answer_has_logo("no"),
        ),
    )


def _logo_upload_field() -> rx.Component:
    """Dropzone + live preview. `on_drop` receives the files through
    `rx.upload_files(...)`, the shape `creative_pages`'s photo upload already proves
    works on this Reflex version."""
    return rx.vstack(
        rx.upload(
            rx.vstack(
                rx.icon("image-up", size=24, color=T.TEXT_FAINT),
                rx.text("Arrastra el logo o haz clic para elegirlo", size="2"),
                rx.text("PNG, JPG, WEBP o SVG", size="1", color=T.TEXT_FAINT),
                align="center",
                spacing="2",
            ),
            id=_LOGO_UPLOAD_ID,
            accept={"image/*": [".png", ".jpg", ".jpeg", ".webp", ".svg"]},
            max_files=1,
            on_drop=BrandWizardState.handle_logo_upload(rx.upload_files(upload_id=_LOGO_UPLOAD_ID)),
            border=f"1px dashed {rx.color('gray', 7)}",
            border_radius=T.RADIUS_CARD,
            padding="2rem",
            width="100%",
        ),
        rx.cond(
            BrandWizardState.logo_error != "",
            callout(BrandWizardState.logo_error, "error"),
        ),
        rx.cond(
            BrandWizardState.logo_key != "",
            card(
                rx.hstack(
                    rx.image(
                        src=rx.get_upload_url(BrandWizardState.logo_key),
                        alt="Vista previa del logo",
                        height="4rem",
                        width="4rem",
                        object_fit="contain",
                        border_radius=T.RADIUS_CONTROL,
                    ),
                    rx.vstack(
                        rx.text(BrandWizardState.logo_name, size="2", weight="medium"),
                        rx.text("Cargado", size="1", color=T.TEXT_MUTED),
                        spacing="1",
                        align_items="start",
                    ),
                    rx.spacer(),
                    rx.button(
                        rx.icon("trash-2", size=T.ICON_SM),
                        "Quitar",
                        variant="soft",
                        color_scheme="tomato",
                        size="2",
                        on_click=BrandWizardState.clear_logo,
                    ),
                    align="center",
                    spacing="3",
                    width="100%",
                ),
                padding="0.75rem 1rem",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _logo_brief_form() -> rx.Component:
    """Placeholder brief — the three questions are lorem until the logo-generation
    design lands."""
    return _step_body(
        _labeled_input(
            "Lorem ipsum dolor",
            BrandWizardState.logo_brief_1,
            BrandWizardState.set_logo_brief_1,
            "Consectetur adipiscing elit",
        ),
        _labeled_input(
            "Sed do eiusmod tempor",
            BrandWizardState.logo_brief_2,
            BrandWizardState.set_logo_brief_2,
            "Incididunt ut labore et dolore",
        ),
        _labeled_input(
            "Ut enim ad minim veniam",
            BrandWizardState.logo_brief_3,
            BrandWizardState.set_logo_brief_3,
            "Quis nostrud exercitation",
        ),
    )


def _step_logo() -> rx.Component:
    """Branches on step 3. `has_logo == "si"` imports a file; anything else asks the
    brief — so an unanswered step 3 lands on the brief rather than on a blank screen."""
    return rx.cond(
        BrandWizardState.has_logo == "si",
        _logo_upload_field(),
        _logo_brief_form(),
    )


def _swatch(colour: rx.Var[str]) -> rx.Component:
    """One colour already in the palette. Clicking it loads that colour into the wheel,
    so an existing entry can be re-picked instead of retyped."""
    return rx.box(
        on_click=BrandWizardState.set_picker_color(colour),
        title=colour,
        cursor="pointer",
        width="1.75rem",
        height="1.75rem",
        border_radius="9999px",
        background=colour,
        box_shadow=f"inset 0 0 0 1px {rx.color('gray', 7)}",
        transition=f"transform {T.DUR} {T.EASE}",
        _hover={"transform": "scale(1.15)"},
    )


def _colour_wheel() -> rx.Component:
    """A real colour wheel: the conic gradient is the affordance, and a native
    `input[type=color]` sits transparent on top of it, so clicking anywhere on the disc
    opens the OS picker. `on_change` drives the live hub colour; `on_blur` — the dialog
    closing — is what commits it to the palette."""
    return rx.vstack(
        rx.box(
            rx.input(
                type="color",
                value=BrandWizardState.picker_color,
                on_change=BrandWizardState.set_picker_color,
                on_blur=BrandWizardState.commit_picked_color,
                position="absolute",
                top="0",
                left="0",
                width="100%",
                height="100%",
                opacity="0",
                padding="0",
                border="none",
                cursor="pointer",
            ),
            # The hub shows the current pick, so the disc doubles as the swatch.
            rx.box(
                position="absolute",
                top="50%",
                left="50%",
                transform="translate(-50%, -50%)",
                width="45%",
                height="45%",
                border_radius="9999px",
                background=BrandWizardState.picker_color,
                box_shadow=f"0 0 0 4px {rx.color('gray', 1)}",
                pointer_events="none",
            ),
            position="relative",
            width="11rem",
            height="11rem",
            border_radius="9999px",
            background=(
                "conic-gradient(#ff0000, #ffff00, #00ff00, #00ffff, #0000ff, #ff00ff, #ff0000)"
            ),
            box_shadow=f"inset 0 0 0 1px {rx.color('gray', 6)}",
        ),
        rx.text(BrandWizardState.picker_color, size="2", color=T.TEXT_MUTED),
        spacing="3",
        align="center",
        width="100%",
    )


def _step_palette() -> rx.Component:
    return _step_body(
        _labeled_input(
            "Paleta (hex, separados por coma)",
            CreativeState.kit_palette,
            CreativeState.set_kit_palette,
            "#0A3D2E,#F2C94C",
        ),
        rx.hstack(
            rx.foreach(CreativeState.kit_palette.split(","), _swatch),
            spacing="2",
            wrap="wrap",
            justify="center",
            width="100%",
        ),
        _colour_wheel(),
    )


def _step_voice_tone() -> rx.Component:
    return _step_body(
        _tone_slider(
            "formal",
            "coloquial",
            CreativeState.tone_formal_casual,
            CreativeState.set_tone_formal_casual,
        ),
        _tone_slider(
            "sobrio",
            "entusiasta",
            CreativeState.tone_sober_enthusiastic,
            CreativeState.set_tone_sober_enthusiastic,
        ),
        _tone_slider(
            "técnico",
            "llano",
            CreativeState.tone_technical_plain,
            CreativeState.set_tone_technical_plain,
        ),
        _tone_slider(
            "breve",
            "elaborado",
            CreativeState.tone_brief_elaborate,
            CreativeState.set_tone_brief_elaborate,
        ),
    )


def _step_voice_examples() -> rx.Component:
    return _step_body(
        _labeled_area(
            "Ejemplos que SÍ suenan a la marca (uno por línea)",
            CreativeState.kit_do_examples,
            CreativeState.set_kit_do_examples,
        ),
        _labeled_area(
            "Ejemplos que NO suenan a la marca (uno por línea)",
            CreativeState.kit_dont_examples,
            CreativeState.set_kit_dont_examples,
        ),
        _labeled_area(
            "Patrones de llamado a la acción (uno por línea)",
            CreativeState.kit_cta_patterns,
            CreativeState.set_kit_cta_patterns,
        ),
    )


def _step_restrictions() -> rx.Component:
    return _step_body(
        _labeled_area(
            "Palabras vetadas (una por línea)",
            CreativeState.kit_banned_words,
            CreativeState.set_kit_banned_words,
        ),
        _labeled_area(
            "Claims prohibidos (uno por línea)",
            CreativeState.kit_forbidden_claims,
            CreativeState.set_kit_forbidden_claims,
        ),
        rx.callout(
            "Esto se comprueba siempre, incluso si desactivas el resto.",
            icon="shield-alert",
            color_scheme="amber",
            width="100%",
        ),
    )


def _recap_row(label: str, value: rx.Var[str], fallback: str = "Sin definir") -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2", color=T.TEXT_MUTED, min_width="9rem"),
        rx.cond(
            value != "",
            rx.text(value, size="2"),
            rx.text(fallback, size="2", color=T.TEXT_FAINT),
        ),
        spacing="3",
        width="100%",
        align="start",
    )


def _step_confirm() -> rx.Component:
    return _step_body(
        card(
            rx.vstack(
                _recap_row("Plan", BrandWizardState.subscription),
                rx.divider(),
                _recap_row("Posicionamiento", CreativeState.kit_positioning),
                _recap_row("Audiencia", CreativeState.kit_audience),
                rx.divider(),
                _recap_row("Logo", BrandWizardState.logo_name, "Sin archivo"),
                _recap_row("Paleta", CreativeState.kit_palette),
                rx.divider(),
                _recap_row("Palabras vetadas", CreativeState.kit_banned_words, "Ninguna"),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            padding="1.25rem 1.5rem",
            width="100%",
        ),
    )


def _window() -> rx.Component:
    """One step at a time. `rx.match` on the cursor, with step 1 as the fallback so an
    out-of-range cursor still renders a form instead of a blank screen."""
    return rx.match(
        BrandWizardState.step,
        (0, _step_subscription()),
        (1, _step_identity()),
        (2, _step_has_logo()),
        (3, _step_logo()),
        (4, _step_palette()),
        (5, _step_voice_tone()),
        (6, _step_voice_examples()),
        (7, _step_restrictions()),
        (8, _step_confirm()),
        _step_subscription(),
    )


# ---------------------------------------------------------------------------
# Chrome: counter, title, controls


def _heading_for(index: int) -> rx.Var[str]:
    return rx.match(
        BrandWizardState.step,
        *((position, text[index]) for position, text in enumerate(STEPS)),
        STEPS[0][index],
    )


def _controls() -> rx.Component:
    """Small, quiet, at the bottom. The last step swaps Next for Finish — the same
    `save_kit_form` the accordion always used."""
    back = rx.button(
        rx.icon("chevron-left", size=T.ICON_SM),
        "Atrás",
        variant="ghost",
        size="2",
        disabled=BrandWizardState.step == 0,
        on_click=BrandWizardState.prev_step,
    )
    return rx.hstack(
        back,
        rx.spacer(),
        rx.cond(
            BrandWizardState.step == LAST_STEP,
            rx.button(
                rx.icon("check", size=T.ICON_SM),
                "Finalizar",
                size="2",
                on_click=CreativeState.save_kit_form,
            ),
            rx.button(
                "Continuar",
                rx.icon("chevron-right", size=T.ICON_SM),
                size="2",
                on_click=BrandWizardState.next_step,
            ),
        ),
        width="100%",
        align="center",
        spacing="3",
    )


def brand_manual_index() -> rx.Component:
    return app_shell(
        page_body(
            rx.vstack(
                rx.text(
                    "Paso ",
                    BrandWizardState.step + 1,
                    f" de {len(STEPS)}",
                    size="1",
                    color=T.TEXT_MUTED,
                    letter_spacing="0.08em",
                    text_transform="uppercase",
                ),
                rx.heading(_heading_for(0), size="8", weight="bold", text_align="center"),
                rx.text(_heading_for(1), size="3", color=T.TEXT_MUTED, text_align="center"),
                rx.cond(CreativeState.kit_error != "", callout(CreativeState.kit_error, "error")),
                rx.cond(
                    CreativeState.kit_notice != "",
                    rx.callout(
                        CreativeState.kit_notice,
                        icon="circle-check",
                        color_scheme="grass",
                        width="100%",
                    ),
                ),
                rx.cond(
                    CreativeState.kit_loading,
                    rx.skeleton(rx.box(height="18rem", width="100%")),
                    rx.box(_window(), width="100%", padding="1.5rem 0 0.5rem 0"),
                ),
                _controls(),
                spacing="4",
                width="100%",
                max_width="34rem",
                align_self="center",
                padding="3rem 0 4rem 0",
                align_items="center",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# /brand — the entry fork


def _fork_option(icon: str, title: str, description: str, action: rx.Component) -> rx.Component:
    return card(
        rx.vstack(
            rx.icon(icon, size=26, color=rx.color("accent", 10)),
            rx.heading(title, size="4"),
            rx.text(description, size="2", color=T.TEXT_MUTED),
            action,
            spacing="3",
            align_items="start",
            width="100%",
        ),
        padding="1.75rem",
        width="100%",
    )


def brand_choice_index() -> rx.Component:
    """The fork the sidebar's «Marca» lands on. «Ya tengo redes» carries no handler
    yet — by design.

    Same centred chrome as the flow itself: `page_body` aligns its children to the
    start, so `align_self="center"` is what overrides it (an auto margin would work too,
    but align-self says the intent out loud)."""
    return app_shell(
        page_body(
            rx.vstack(
                rx.heading("Brandkit", size="8", weight="bold", text_align="center"),
                rx.text(
                    "El sustrato de marca del que sale cada pieza",
                    size="3",
                    color=T.TEXT_MUTED,
                    text_align="center",
                ),
                rx.vstack(
                    _fork_option(
                        "pencil-line",
                        "Empezar de cero",
                        "Te guiamos paso a paso: plan, identidad, logo, colores, voz y "
                        "restricciones.",
                        rx.link(
                            rx.button("Empezar", size="3", width="100%"),
                            href="/brand/manual",
                            width="100%",
                        ),
                    ),
                    _fork_option(
                        "at-sign",
                        "Ya tengo redes",
                        "Leemos tu perfil y te proponemos el kit a partir de lo que ya publicas.",
                        rx.link(
                            rx.button("Conectar", size="3", variant="soft", width="100%"),
                            href="/brand/connect",
                            width="100%",
                        ),
                    ),
                    spacing="4",
                    width="100%",
                    padding_top="1.5rem",
                ),
                spacing="3",
                width="100%",
                max_width="44rem",
                align_self="center",
                align_items="center",
                padding="3rem 0 4rem 0",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# /brand/connect — the "ya tengo redes" flow
#
# Screens 5-11 are the SAME renderers the manual flow uses, so the two paths cannot
# drift: only the first four (network, username, profile, recommendations) are specific
# to this one.

#: Placeholder analysis source. Real profile reads are Parte 4 work; until then this
#: fixture stands in, resolved relative to this module so the app finds it from any cwd.
PROFILE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "midu.dev_prueba.json"

_USERNAME_REQUIRED = "Escribe tu usuario para continuar."
_PROFILE_UNAVAILABLE = "No pudimos leer el perfil. Inténtalo de nuevo."

NETWORKS: tuple[tuple[str, str, str], ...] = (
    ("instagram", "Instagram", "Reels, carruseles y publicaciones."),
    ("tiktok", "TikTok", "Vídeos cortos y galerías de fotos."),
)

#: Placeholder recommendations. Copy is lorem until the analysis actually produces them.
RECOMMENDATIONS: tuple[tuple[str, str], ...] = (
    ("Publica más vídeo corto", "Lorem ipsum dolor sit amet, consectetur adipiscing elit."),
    ("Refuerza tu llamada a la acción", "Sed do eiusmod tempor incididunt ut labore et dolore."),
    ("Unifica la paleta", "Ut enim ad minim veniam, quis nostrud exercitation ullamco."),
    ("Responde los comentarios", "Duis aute irure dolor in reprehenderit in voluptate velit."),
)

CONNECT_STEPS: tuple[tuple[str, str], ...] = (
    ("¿Qué red usas?", "Empezamos por donde ya tienes audiencia."),
    ("¿Cuál es tu usuario?", "Lo leeremos para proponerte el kit."),
    ("Esto es lo que vemos", "Confirma que es tu perfil."),
    ("Lo que te proponemos", "Podrás ajustarlo todo después."),
    ("Elige tu plan", "Puedes cambiarlo más adelante."),
    ("¿Quién es la marca?", "Lo que define su lugar y a quién le habla."),
    ("Paleta de colores", "Los colores con los que se te reconoce."),
    ("¿Cómo suena?", "Ajusta el tono en cuatro ejes."),
    ("Enséñale a hablar", "Ejemplos reales valen más que cualquier descripción."),
    ("Lo que nunca debe decir", "Reglas duras: una violación es un rechazo."),
    ("¿Todo correcto?", "Revisa antes de guardar."),
)
CONNECT_LAST = len(CONNECT_STEPS) - 1
_RECOMMENDATIONS_STEP = 3


class BrandConnectState(rx.State):
    """Cursor and profile read for the connect flow. Kept apart from `BrandWizardState`
    so the two entry paths cannot fight over one cursor — the kit fields they share
    still live in `CreativeState`."""

    step: int = 0
    network: str = ""
    username: str = ""
    analyzing: bool = False
    error: str = ""

    profile_username: str = ""
    profile_fullname: str = ""
    profile_bio: str = ""
    profile_followers: str = ""
    profile_pic: str = ""

    @rx.event
    def next_step(self) -> None:
        self.step = min(self.step + 1, CONNECT_LAST)

    @rx.event
    def prev_step(self) -> None:
        self.step = max(self.step - 1, 0)

    @rx.event
    def choose_network(self, key: str) -> None:
        """Choosing advances — the screen holds nothing else, so a second click on
        Continue would be a dead one."""
        self.network = key
        self.step = 1

    @rx.event
    def set_username(self, value: str) -> None:
        self.username = value
        self.error = ""

    @rx.event
    def restart(self) -> rx.event.EventSpec:
        """Cancel from the recommendations screen: drop what was read and go back to the
        fork, so the next entry starts clean."""
        self.step = 0
        self.network = ""
        self.username = ""
        self.error = ""
        self.profile_username = ""
        self.profile_fullname = ""
        self.profile_bio = ""
        self.profile_followers = ""
        self.profile_pic = ""
        return rx.redirect("/brand")

    @rx.event(background=True)
    async def analyze(self) -> AsyncIterator[None]:
        """Read the profile behind a loading screen.

        Background plus an early `yield` so the spinner actually paints before the read
        starts; a foreground handler would block and the user would see nothing until it
        finished. The file read goes through `asyncio.to_thread` — it is blocking I/O,
        and the event loop serves every other session.
        """
        async with self:
            if not self.username.strip():
                self.error = _USERNAME_REQUIRED
                return
            self.error = ""
            self.analyzing = True
        yield

        try:
            raw = await asyncio.to_thread(PROFILE_FIXTURE.read_text, "utf-8")
            profile = json.loads(raw)["profile"]
        except (OSError, ValueError, KeyError):
            async with self:
                self.analyzing = False
                self.error = _PROFILE_UNAVAILABLE
            return

        # Stands in for the real analysis, so the loading state is visible at all.
        await asyncio.sleep(1.2)

        followers = profile.get("followers")
        async with self:
            self.profile_username = str(profile.get("username", ""))
            self.profile_fullname = str(profile.get("fullName", ""))
            self.profile_bio = str(profile.get("bio", ""))
            self.profile_followers = f"{followers:,}".replace(",", ".") if followers else "—"
            self.profile_pic = str(profile.get("profilePicUrl", ""))
            self.analyzing = False
            self.step = 2


# ---------------------------------------------------------------------------
# The four screens specific to this flow


def _connect_step_network() -> rx.Component:
    return _step_body(
        *(
            _choice_card(
                label,
                blurb,
                BrandConnectState.network == key,
                BrandConnectState.choose_network(key),
            )
            for key, label, blurb in NETWORKS
        )
    )


def _connect_step_username() -> rx.Component:
    return _step_body(
        _labeled_input(
            "Usuario",
            BrandConnectState.username,
            BrandConnectState.set_username,
            "midu.dev",
        ),
        rx.cond(
            BrandConnectState.error != "",
            callout(BrandConnectState.error, "error"),
        ),
    )


def _connect_step_profile() -> rx.Component:
    return _step_body(
        card(
            rx.vstack(
                rx.cond(
                    BrandConnectState.profile_pic != "",
                    rx.image(
                        src=BrandConnectState.profile_pic,
                        alt="Foto de perfil",
                        width="5.5rem",
                        height="5.5rem",
                        border_radius="9999px",
                        object_fit="cover",
                    ),
                    rx.box(
                        rx.icon("user", size=28, color=T.TEXT_FAINT),
                        width="5.5rem",
                        height="5.5rem",
                        border_radius="9999px",
                        background=T.SURFACE_BG_RAISED,
                        display="flex",
                        align_items="center",
                        justify_content="center",
                    ),
                ),
                rx.heading(BrandConnectState.profile_username, size="4"),
                rx.text(BrandConnectState.profile_fullname, size="2", color=T.TEXT_MUTED),
                rx.text(
                    BrandConnectState.profile_followers,
                    " seguidores",
                    size="2",
                    weight="medium",
                ),
                rx.divider(),
                rx.text(
                    BrandConnectState.profile_bio,
                    size="2",
                    color=T.TEXT_MUTED,
                    white_space="pre-line",
                    text_align="center",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            padding="1.75rem",
            width="100%",
        )
    )


def _recommendation_card(title: str, blurb: str) -> rx.Component:
    return card(
        rx.hstack(
            rx.icon("sparkles", size=18, color=rx.color("accent", 10)),
            rx.vstack(
                rx.text(title, size="2", weight="bold"),
                rx.text(blurb, size="2", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        padding="1rem 1.25rem",
        width="100%",
    )


def _connect_step_recommendations() -> rx.Component:
    return _step_body(*(_recommendation_card(title, blurb) for title, blurb in RECOMMENDATIONS))


def _connect_window() -> rx.Component:
    """Screens 1-4 are this flow's own; 5-11 reuse the manual flow's renderers, so the
    shared half of the two paths is literally the same code."""
    return rx.match(
        BrandConnectState.step,
        (0, _connect_step_network()),
        (1, _connect_step_username()),
        (2, _connect_step_profile()),
        (3, _connect_step_recommendations()),
        (4, _step_subscription()),
        (5, _step_identity()),
        (6, _step_palette()),
        (7, _step_voice_tone()),
        (8, _step_voice_examples()),
        (9, _step_restrictions()),
        (10, _step_confirm()),
        _connect_step_network(),
    )


def _connect_heading_for(index: int) -> rx.Var[str]:
    return rx.match(
        BrandConnectState.step,
        *((position, text[index]) for position, text in enumerate(CONNECT_STEPS)),
        CONNECT_STEPS[0][index],
    )


def _connect_loading() -> rx.Component:
    return rx.vstack(
        rx.spinner(size="3"),
        rx.text("Analizando perfil", size="3", weight="medium"),
        rx.text("Esto tarda solo unos segundos.", size="2", color=T.TEXT_MUTED),
        spacing="3",
        align="center",
        width="100%",
        padding="4rem 0",
    )


def _connect_controls() -> rx.Component:
    """Same quiet chrome as the manual flow, with two exceptions: the username screen's
    Continue kicks off the analysis instead of stepping, and the recommendations screen
    offers Cancel rather than Back."""
    left = rx.cond(
        BrandConnectState.step == _RECOMMENDATIONS_STEP,
        rx.button(
            "Cancelar",
            variant="ghost",
            color_scheme="tomato",
            size="2",
            on_click=BrandConnectState.restart,
        ),
        rx.button(
            rx.icon("chevron-left", size=T.ICON_SM),
            "Atrás",
            variant="ghost",
            size="2",
            disabled=BrandConnectState.step == 0,
            on_click=BrandConnectState.prev_step,
        ),
    )
    right = rx.cond(
        BrandConnectState.step == CONNECT_LAST,
        rx.button(
            rx.icon("check", size=T.ICON_SM),
            "Finalizar",
            size="2",
            on_click=CreativeState.save_kit_form,
        ),
        rx.cond(
            BrandConnectState.step == 1,
            rx.button(
                "Analizar",
                rx.icon("chevron-right", size=T.ICON_SM),
                size="2",
                on_click=BrandConnectState.analyze,
            ),
            rx.button(
                "Continuar",
                rx.icon("chevron-right", size=T.ICON_SM),
                size="2",
                on_click=BrandConnectState.next_step,
            ),
        ),
    )
    return rx.hstack(left, rx.spacer(), right, width="100%", align="center", spacing="3")


def brand_connect_index() -> rx.Component:
    return app_shell(
        page_body(
            rx.vstack(
                rx.text(
                    "Paso ",
                    BrandConnectState.step + 1,
                    f" de {len(CONNECT_STEPS)}",
                    size="1",
                    color=T.TEXT_MUTED,
                    letter_spacing="0.08em",
                    text_transform="uppercase",
                ),
                rx.heading(_connect_heading_for(0), size="8", weight="bold", text_align="center"),
                rx.text(_connect_heading_for(1), size="3", color=T.TEXT_MUTED, text_align="center"),
                rx.cond(CreativeState.kit_error != "", callout(CreativeState.kit_error, "error")),
                rx.cond(
                    CreativeState.kit_notice != "",
                    rx.callout(
                        CreativeState.kit_notice,
                        icon="circle-check",
                        color_scheme="grass",
                        width="100%",
                    ),
                ),
                rx.cond(
                    BrandConnectState.analyzing,
                    _connect_loading(),
                    rx.vstack(
                        rx.box(_connect_window(), width="100%", padding="1.5rem 0 0.5rem 0"),
                        _connect_controls(),
                        spacing="4",
                        width="100%",
                        align_items="center",
                    ),
                ),
                spacing="4",
                width="100%",
                max_width="34rem",
                align_self="center",
                align_items="center",
                padding="3rem 0 4rem 0",
            ),
        ),
    )
