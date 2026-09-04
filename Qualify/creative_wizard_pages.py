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
from .ui import app_shell, callout, card, mono, page_body
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

# One radius, everywhere a real Radix control appears (input/text_area/button) — the
# whole point is that no two controls in this flow round differently. Box-based
# "buttons" (choice cards, the fork cards) are a different component family and use
# `T.RADIUS_CARD`, the app-wide card radius — the two happen to read as the same
# roundedness at this size, which is the point.
_CONTROL_RADIUS = "large"

# NO `100vh` ARITHMETIC LIVES HERE — deleted 2026-09-03 after measuring it in a real
# browser. This module used to carry `_SCREEN_MIN_HEIGHT = calc(100vh - 2 * gap - 2rem)`
# and it was wrong by exactly 2px: the chain it tried to cancel (shell 100vh → panel
# `100vh - 2 * gap` → this screen → `page_body`'s 2rem bottom padding) never subtracted
# the PANEL'S OWN 1px top+bottom border, so every screen overflowed the document by 2px
# and showed a scrollbar it did not need, on every step, always. The 4rem bottom padding
# that went with it left the card's border stopping ~97px short of the panel's bottom.
#
# `app_shell` now gives the panel a definite height and `overflow: auto`, so a screen
# fills it with `flex="1"` and cannot drift when some box upstream gains a border or a
# padding. If you find yourself typing `100vh` in this file, that is the bug coming
# back — and note the two files move together: restoring an older copy of THIS module
# on top of the current `ui/layout.py` is what visibly broke the layout once already.

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

    # -- step 5 -----------------------------------------------------------------------
    # The wheel/readout's pending pick. They ONLY ever add a new colour — nothing here
    # is shared with editing an existing one (see `set_swatch_color`), so there is no
    # hidden mode to get wrong: the wheel always appends, a swatch always edits itself.
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
    def prev_step(self) -> rx.event.EventSpec | None:
        """Atrás from the very first step leaves the wizard — there is no step -1 to
        land on, so "back" means back to the fork, not a disabled button."""
        if self.step == 0:
            return rx.redirect("/brand")
        self.step -= 1
        return None

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
        """Append the wheel/readout's pending pick to the palette `CreativeState`
        already persists. This is the ONLY way a colour gets ADDED — an existing swatch
        never routes through here, so there is nothing for this to accidentally
        overwrite (see the module docstring's step-5 note).

        Fired on the picker's blur — i.e. when the OS dialog closes — rather than on
        change: `input[type=color]` emits a change per mouse move while dragging, so
        committing on change would push a dozen intermediate colours into the palette.

        The palette stays a single comma-separated string in `CreativeState` (that is
        what `KitFormVM` saves), so the readout, the wheel and the swatch strip can
        never disagree. Joined without spaces so each entry is a clean CSS colour when
        it comes back out as a swatch.
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
    async def set_swatch_color(self, index: int, colour: str) -> None:
        """EDIT an existing palette entry in place — the only way one changes. Bound to
        that swatch's own colour input (`_swatch`), so the index and the new value
        arrive together in one call; unlike the wheel there is no separate pending value
        to stash and no `on_blur` to wire, because there is nothing ambiguous to commit
        later — this index, this colour, done.

        It also moves `picker_color`, which is what the readout card renders: while you
        drag inside a swatch's picker, the card below names the colour you are landing
        on. That is display only — the readout has no picker of its own — so tracking it
        here cannot add anything to the palette.
        """
        colour = colour.strip()
        if not colour:
            return
        self.picker_color = colour
        creative = await self.get_state(CreativeState)
        parts = [c.strip() for c in creative.kit_palette.split(",") if c.strip()]
        if not (0 <= index < len(parts)):
            return
        others = [p for i, p in enumerate(parts) if i != index]
        if colour.lower() in [p.lower() for p in others]:
            # Edited onto a colour already elsewhere in the palette — drop this entry
            # rather than leave a literal duplicate behind.
            parts.pop(index)
        else:
            parts[index] = colour
        creative.kit_palette = ",".join(parts)

    @rx.event
    async def remove_colour(self, index: int) -> None:
        """The delete affordance on each swatch — the palette had no way to shrink
        before this."""
        creative = await self.get_state(CreativeState)
        parts = [c.strip() for c in creative.kit_palette.split(",") if c.strip()]
        if 0 <= index < len(parts):
            parts.pop(index)
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

    @rx.var
    def picker_color_name(self) -> str:
        """The wheel's current pick, named — see `_nearest_colour_name`."""
        return _nearest_colour_name(self.picker_color)


# ---------------------------------------------------------------------------
# Field primitives — local copies of the accordion's, so this module stays standalone


def _labeled_area(
    label: str, value: rx.Var[str], handler: rx.event.EventHandler, placeholder: str = ""
) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        rx.text_area(
            value=value,
            on_change=handler,
            placeholder=placeholder,
            width="100%",
            rows="3",
            radius=_CONTROL_RADIUS,
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _labeled_input(
    label: str,
    value: rx.Var[str],
    handler: rx.event.EventHandler,
    placeholder: str = "",
    *,
    height: str = "2.75rem",
) -> rx.Component:
    """Radix's default `size="2"` reads cramped once the rest of the flow is set in the
    bigger macOS-setup type scale — `size="3"` plus a touch of extra height matches the
    weight of the labels and headings around it. `height` is a keyword so one screen
    (the logo brief) can ask for more without resizing every other input in the flow."""
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        rx.input(
            value=value,
            on_change=handler,
            placeholder=placeholder,
            width="100%",
            size="3",
            height=height,
            radius=_CONTROL_RADIUS,
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
                        radius=_CONTROL_RADIUS,
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
    design lands. Slightly taller inputs than the rest of the flow: three fields back
    to back on one screen read cramped at the default height."""
    return _step_body(
        _labeled_input(
            "Lorem ipsum dolor",
            BrandWizardState.logo_brief_1,
            BrandWizardState.set_logo_brief_1,
            "Consectetur adipiscing elit",
            height="3.25rem",
        ),
        _labeled_input(
            "Sed do eiusmod tempor",
            BrandWizardState.logo_brief_2,
            BrandWizardState.set_logo_brief_2,
            "Incididunt ut labore et dolore",
            height="3.25rem",
        ),
        _labeled_input(
            "Ut enim ad minim veniam",
            BrandWizardState.logo_brief_3,
            BrandWizardState.set_logo_brief_3,
            "Quis nostrud exercitation",
            height="3.25rem",
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


# A modest reference set for the palette readout's colour name — nearest match by RGB
# distance. There is no colour-naming service wired in, so this is approximate by
# design: good enough for a label next to a swatch, not a claim of precision.
_NAMED_COLOURS: tuple[tuple[str, str], ...] = (
    ("Negro", "#000000"),
    ("Gris oscuro", "#333333"),
    ("Gris", "#808080"),
    ("Gris claro", "#D3D3D3"),
    ("Blanco", "#FFFFFF"),
    ("Rojo", "#E53935"),
    ("Rojo oscuro", "#8B0000"),
    ("Vino", "#722F37"),
    ("Naranja", "#F2994A"),
    ("Ámbar", "#FFB020"),
    ("Amarillo", "#F2C94C"),
    ("Oliva", "#808000"),
    ("Verde lima", "#9ACD32"),
    ("Verde", "#27AE60"),
    ("Verde bosque", "#0A3D2E"),
    ("Verde azulado", "#0D7D72"),
    ("Menta", "#2ECC91"),
    ("Cian", "#00BCD4"),
    ("Azul cielo", "#56CCF2"),
    ("Azul", "#2F80ED"),
    ("Azul marino", "#1B2A4A"),
    ("Índigo", "#3F51B5"),
    ("Violeta", "#9B51E0"),
    ("Púrpura", "#6A1B9A"),
    ("Magenta", "#D81B60"),
    ("Rosa", "#F48FB1"),
    ("Beige", "#E8DCC8"),
    ("Marrón", "#6D4C33"),
    ("Terracota", "#C97452"),
)


def _nearest_colour_name(hex_colour: str) -> str:
    stripped = hex_colour.lstrip("#")
    if len(stripped) != 6:
        return "Personalizado"
    try:
        r, g, b = (int(stripped[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "Personalizado"
    best_name, best_distance = "Personalizado", float("inf")
    for name, reference in _NAMED_COLOURS:
        rr, gg, bb = (int(reference[1:][i : i + 2], 16) for i in (0, 2, 4))
        distance = (r - rr) ** 2 + (g - gg) ** 2 + (b - bb) ** 2
        if distance < best_distance:
            best_name, best_distance = name, distance
    return best_name


def _swatch(colour: rx.Var[str], index: rx.Var[int]) -> rx.Component:
    """One colour already in the palette. The circle IS the editor: a native
    `input[type=color]` sits transparent over it (same trick as the wheel), so clicking
    opens the OS picker seeded with this swatch's own colour, and `set_swatch_color`
    writes the result straight back into this same slot — there is no detour through the
    wheel. The small × removes it outright; it needs `stop_propagation` so that click
    does not also open the picker underneath it.

    `on_click` reads this swatch's colour into the readout card below BEFORE the picker
    dialog even returns a value, so clicking an existing colour names it immediately —
    the click alone is the "show me this one" gesture, no change required."""
    return rx.box(
        rx.box(
            rx.input(
                type="color",
                value=colour,
                on_click=BrandWizardState.set_picker_color(colour),
                on_change=BrandWizardState.set_swatch_color(index),
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
            title=colour,
            position="relative",
            cursor="pointer",
            width="2.25rem",
            height="2.25rem",
            border_radius="9999px",
            background=colour,
            box_shadow=f"inset 0 0 0 1px {rx.color('gray', 7)}",
            transition=f"transform {T.DUR} {T.EASE}",
            _hover={"transform": "scale(1.15)"},
        ),
        rx.box(
            rx.icon("x", size=10, color="white"),
            on_click=BrandWizardState.remove_colour(index).stop_propagation,
            position="absolute",
            top="-0.25rem",
            right="-0.25rem",
            width="1rem",
            height="1rem",
            border_radius="9999px",
            background=rx.color("tomato", 9),
            display="flex",
            align_items="center",
            justify_content="center",
            cursor="pointer",
            box_shadow=f"0 0 0 2px {rx.color('gray', 1)}",
        ),
        position="relative",
        width="2.25rem",
        height="2.25rem",
    )


def _colour_wheel() -> rx.Component:
    """Adds a colour — nothing else. The conic gradient is the affordance, and a native
    `input[type=color]` sits transparent on top of it, so clicking anywhere on the disc
    opens the OS picker. `on_change` drives the picked colour live; `on_blur` — the
    dialog closing — is what appends it (`commit_picked_color`, which never edits — see
    `_swatch` for how an existing colour gets changed instead). No centre hub any more
    (per request) — the readout below is the single place the current pick is shown."""
    return rx.box(
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
        position="relative",
        width="11rem",
        height="11rem",
        border_radius="9999px",
        background=(
            "conic-gradient(#ff0000, #ffff00, #00ff00, #00ffff, #0000ff, #ff00ff, #ff0000)"
        ),
        box_shadow=f"inset 0 0 0 1px {rx.color('gray', 6)}",
    )


def _colour_readout() -> rx.Component:
    """The colour currently in focus, read out as a name and its hex code — feedback,
    not a control. "In focus" means whichever colour you last touched: the wheel's
    pending pick, or the swatch you just clicked (`_swatch` sets it on click, and keeps
    it in step while you drag inside that swatch's picker).

    It used to carry its own transparent `input[type=color]`, which made it a SECOND way
    to add a colour; that was removed 2026-09-03 (per request) so the two jobs stay on
    exactly one control each: the wheel adds, a swatch edits itself. A card that also
    added was the third behaviour that made the step confusing.

    `min_width="0"` on the text column is load-bearing, not decorative: a flex item's
    default `min-width` is `auto`, which lets its content (a long colour name) force
    the column wider than the card's `max_width` and spill past the border — this is
    the standard fix, paired with `overflow`/`text_overflow` on the two text lines."""
    return rx.box(
        rx.hstack(
            rx.box(
                width="2.5rem",
                height="2.5rem",
                border_radius=T.RADIUS_CARD,
                background=BrandWizardState.picker_color,
                box_shadow=f"inset 0 0 0 1px {rx.color('gray', 7)}",
                flex_shrink="0",
            ),
            rx.vstack(
                rx.text(
                    BrandWizardState.picker_color_name,
                    size="2",
                    weight="medium",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                    width="100%",
                ),
                mono(BrandWizardState.picker_color, size="1"),
                spacing="0",
                align_items="start",
                min_width="0",
                overflow="hidden",
            ),
            spacing="3",
            align="center",
            width="100%",
            min_width="0",
        ),
        # No `cursor: pointer` and no `q-lift` any more: this card does nothing when
        # clicked, so it must not advertise that it does.
        padding="0.65rem 0.9rem",
        border=f"1px solid {rx.color('gray', 6)}",
        border_radius=T.RADIUS_CARD,
        background=T.CARD_BG,
        width="100%",
        max_width="16rem",
    )


def _step_palette() -> rx.Component:
    """The old raw-hex text field is gone (per request). Two separate jobs, two
    separate controls, on purpose (per request 2026-09-03 — the wheel used to also
    edit an existing swatch, via a shared `editing_index`, which was one hidden mode
    away from silently overwriting the wrong entry):

    - ADD a colour: the wheel, and only the wheel — `_colour_wheel`. Its readout
      (`_colour_readout`) just names what was picked; it is not a second way in.
    - EDIT a colour already in the palette: the swatch itself, in the strip below —
      `_swatch`. Its own × removes it outright.
    """
    return _step_body(
        rx.hstack(
            rx.foreach(CreativeState.kit_palette.split(","), _swatch),
            spacing="2",
            wrap="wrap",
            justify="center",
            width="100%",
        ),
        rx.vstack(
            _colour_wheel(),
            _colour_readout(),
            spacing="3",
            align="center",
            width="100%",
        ),
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


def _flow_header(
    title: str | rx.Var[str],
    subtitle: str | rx.Var[str],
    *,
    step_label: rx.Component | None = None,
) -> rx.Component:
    """The counter (when there is one) and the title/subtitle sit left, the colour-mode
    toggle sits right — `rx.color_mode.button()` is the exact same call `ui.layout.
    page_header` uses, so the toggle looks and behaves identically everywhere in the
    app. Full width on purpose: the narrower reading column is a property of the
    content below, not of this row."""
    return rx.hstack(
        rx.vstack(
            *([step_label] if step_label is not None else []),
            rx.heading(title, size="8", weight="bold"),
            rx.text(subtitle, size="3", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
        ),
        rx.spacer(),
        rx.color_mode.button(),
        width="100%",
        align="center",
    )


def _step_counter(step: rx.Var[int], total: int) -> rx.Component:
    return rx.text(
        "Paso ",
        step + 1,
        f" de {total}",
        size="1",
        color=T.TEXT_MUTED,
        letter_spacing="0.08em",
        text_transform="uppercase",
    )


def _controls() -> rx.Component:
    """Small, quiet, at the bottom. The last step swaps Next for Finish — the same
    `save_kit_form` the accordion always used, chained with a redirect back to the
    Brandkit entry so finishing actually lands somewhere instead of sitting on the
    confirmation screen it just submitted.

    `back` is never disabled any more: `prev_step` itself redirects to `/brand` once
    the cursor is already at step 0, so the button always does something."""
    back = rx.button(
        rx.icon("chevron-left", size=T.ICON_SM),
        "Atrás",
        variant="ghost",
        size="2",
        radius=_CONTROL_RADIUS,
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
                radius=_CONTROL_RADIUS,
                on_click=[CreativeState.save_kit_form, rx.redirect("/brand")],
            ),
            rx.button(
                "Continuar",
                rx.icon("chevron-right", size=T.ICON_SM),
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandWizardState.next_step,
            ),
        ),
        width="100%",
        align="center",
        spacing="3",
    )


def brand_manual_index() -> rx.Component:
    """The header spans the full page width (counter+title left, theme toggle right),
    and so does the border below it — reaching the same edges the header does, filling
    down to the panel's bottom (`flex="1"` all the way up through `page_body`, no
    `100vh` maths — see the note where `_SCREEN_MIN_HEIGHT` used to be) instead of hugging
    its own content height. Inside that tall frame, the card is itself a flex column
    with `justify_content="space-between"`: the fields stay in a narrow, readable,
    centred column at the top (a single-line hex input stretched to 1440px reads worse
    than the frame around it being that wide), while `_controls()` spans the card's
    FULL width and sits pinned to its bottom edge — Atrás at the bottom-left corner,
    Continuar/Finalizar at the bottom-right, not floating just under the fields."""
    return app_shell(
        page_body(
            rx.vstack(
                _flow_header(
                    _heading_for(0),
                    _heading_for(1),
                    step_label=_step_counter(BrandWizardState.step, len(STEPS)),
                ),
                rx.vstack(
                    rx.cond(
                        CreativeState.kit_error != "", callout(CreativeState.kit_error, "error")
                    ),
                    rx.cond(
                        CreativeState.kit_notice != "",
                        rx.callout(
                            CreativeState.kit_notice,
                            icon="circle-check",
                            color_scheme="grass",
                            width="100%",
                        ),
                    ),
                    spacing="3",
                    width="100%",
                    max_width="34rem",
                    align_self="center",
                    align_items="center",
                ),
                card(
                    rx.vstack(
                        rx.cond(
                            CreativeState.kit_loading,
                            rx.skeleton(rx.box(height="18rem", width="100%")),
                            _window(),
                        ),
                        width="100%",
                        max_width="34rem",
                        align_self="center",
                        align_items="center",
                        # Takes the card's free height and centres its content in it, so
                        # a two-field step sits in the middle of its frame instead of
                        # clinging to the top with a void above the controls.
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
                ),
                spacing="4",
                width="100%",
                # Fills the panel through `page_body` (`flex: 1 0 auto`) instead of
                # computing a height. No bottom padding: `PAD_BODY` already leaves the
                # page's bottom gutter, and stacking 4rem on top of it is what left the
                # card's border stopping short of the panel's bottom edge.
                flex="1",
                min_height="0",
                padding="3rem 0 0 0",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# /brand — the entry fork


def _fork_option(icon: str, title: str, description: str, href: str) -> rx.Component:
    """The whole card is the button now — no separate "Empezar"/"Conectar" element
    inside it. `card(interactive=True)` gives the hover lift + pointer cursor every
    other clickable card in the app uses; wrapping it in `rx.link` (rather than an
    `on_click=rx.redirect(...)`) keeps it a real anchor — middle-click, "open in new
    tab" and screen readers all keep working. `display="block"` is load-bearing: an
    `<a>` is inline by default, so `width="100%"` is silently ignored without it and
    the card inside shrinks to its own content's width instead of the frame's."""
    return rx.link(
        card(
            rx.vstack(
                rx.icon(icon, size=26, color=rx.color("accent", 10)),
                rx.heading(title, size="4"),
                rx.text(description, size="2", color=T.TEXT_MUTED),
                spacing="3",
                align_items="start",
                width="100%",
            ),
            padding="1.75rem",
            interactive=True,
        ),
        href=href,
        display="block",
        width="100%",
        text_decoration="none",
        color="inherit",
    )


def brand_choice_index() -> rx.Component:
    """The fork the sidebar's «Marca» lands on. Same framing as the two flows behind
    it now: a full-width border below the full-width header, rather than a border
    hugging a narrow centred column — and the border grows to fill the panel
    (`flex="1"` on the card, `min_height` on this vstack so there is room to grow
    into) instead of stopping short and leaving bare panel background below it."""
    return app_shell(
        page_body(
            rx.vstack(
                _flow_header("Brandkit", "El sustrato de marca del que sale cada pieza"),
                card(
                    rx.vstack(
                        _fork_option(
                            "pencil-line",
                            "Empezar de cero",
                            "Te guiamos paso a paso: plan, identidad, logo, colores, voz y "
                            "restricciones.",
                            "/brand/manual",
                        ),
                        _fork_option(
                            "at-sign",
                            "Ya tengo redes",
                            "Leemos tu perfil y te proponemos el kit a partir de lo que ya "
                            "publicas.",
                            "/brand/connect",
                        ),
                        spacing="4",
                        width="100%",
                    ),
                    padding="1.75rem",
                    width="100%",
                    flex="1",
                    # Same centring as every step screen: the two options sit in the
                    # middle of the frame rather than at its top.
                    display="flex",
                    flex_direction="column",
                    justify_content="center",
                ),
                spacing="4",
                width="100%",
                flex="1",
                min_height="0",
                padding="3rem 0 0 0",
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
    def prev_step(self) -> rx.event.EventSpec | None:
        """Same rule as the manual flow's `BrandWizardState.prev_step`: back from the
        first step leaves the wizard rather than sitting disabled."""
        if self.step == 0:
            return rx.redirect("/brand")
        self.step -= 1
        return None

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
    offers Cancel rather than Back. `back` is never disabled: `prev_step` redirects to
    `/brand` once already at step 0."""
    left = rx.cond(
        BrandConnectState.step == _RECOMMENDATIONS_STEP,
        rx.button(
            "Cancelar",
            variant="ghost",
            color_scheme="tomato",
            size="2",
            radius=_CONTROL_RADIUS,
            on_click=BrandConnectState.restart,
        ),
        rx.button(
            rx.icon("chevron-left", size=T.ICON_SM),
            "Atrás",
            variant="ghost",
            size="2",
            radius=_CONTROL_RADIUS,
            on_click=BrandConnectState.prev_step,
        ),
    )
    right = rx.cond(
        BrandConnectState.step == CONNECT_LAST,
        rx.button(
            rx.icon("check", size=T.ICON_SM),
            "Finalizar",
            size="2",
            radius=_CONTROL_RADIUS,
            on_click=[CreativeState.save_kit_form, rx.redirect("/brand")],
        ),
        rx.cond(
            BrandConnectState.step == 1,
            rx.button(
                "Analizar",
                rx.icon("chevron-right", size=T.ICON_SM),
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandConnectState.analyze,
            ),
            rx.button(
                "Continuar",
                rx.icon("chevron-right", size=T.ICON_SM),
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandConnectState.next_step,
            ),
        ),
    )
    return rx.hstack(left, rx.spacer(), right, width="100%", align="center", spacing="3")


def brand_connect_index() -> rx.Component:
    """Same shape as `brand_manual_index`: full-width header, full-width border filling
    down to the panel's bottom, fields in a narrow centred column at the top of the
    card, and `_connect_controls()` spanning the card's full width, pinned to its
    bottom corners. The loading card centres its spinner instead — there is no footer
    row while `analyzing` is true."""
    return app_shell(
        page_body(
            rx.vstack(
                _flow_header(
                    _connect_heading_for(0),
                    _connect_heading_for(1),
                    step_label=_step_counter(BrandConnectState.step, len(CONNECT_STEPS)),
                ),
                rx.vstack(
                    rx.cond(
                        CreativeState.kit_error != "", callout(CreativeState.kit_error, "error")
                    ),
                    rx.cond(
                        CreativeState.kit_notice != "",
                        rx.callout(
                            CreativeState.kit_notice,
                            icon="circle-check",
                            color_scheme="grass",
                            width="100%",
                        ),
                    ),
                    spacing="3",
                    width="100%",
                    max_width="34rem",
                    align_self="center",
                    align_items="center",
                ),
                rx.cond(
                    BrandConnectState.analyzing,
                    card(
                        _connect_loading(),
                        padding="1.75rem",
                        width="100%",
                        flex="1",
                        display="flex",
                        align_items="center",
                        justify_content="center",
                    ),
                    card(
                        rx.vstack(
                            _connect_window(),
                            width="100%",
                            max_width="34rem",
                            align_self="center",
                            align_items="center",
                            flex="1",
                            justify_content="center",
                        ),
                        _connect_controls(),
                        padding="1.75rem",
                        width="100%",
                        flex="1",
                        display="flex",
                        flex_direction="column",
                        justify_content="space-between",
                    ),
                ),
                spacing="4",
                width="100%",
                flex="1",
                min_height="0",
                padding="3rem 0 0 0",
            ),
        ),
    )
