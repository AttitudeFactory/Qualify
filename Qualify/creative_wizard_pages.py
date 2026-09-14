"""Brand Kit as a nine-step setup flow — the editor that replaced
`creative_pages.brand_index`'s accordion in routing.

The replacement is routing-only: `creative_pages.py` and `creative_state.py` are
untouched, and `brand_index` still exists in the code, simply without a route. The kit
fields that already exist bind to the SAME `CreativeState` vars and save through the
SAME `save_kit_form` handler, so re-registering the accordion at any time would edit
the same row this screen does.

Screens:
  - `brand_choice_index`       (/brand)                — ¿Tienes redes sociales? Sí goes
    straight to the scraper (`/brand/connect`); No goes to the account-setup
    instructions first (§ request 2026-09-09 — the old "empezar de cero vs. ya tengo
    redes" fork stopped making sense once every brand is expected to have a social
    profile to read).
  - `brand_connect_setup_index` (/brand/connect/setup) — instructions for creating an
    Instagram or TikTok account, shown only on the "No" answer. Purely informational:
    Continuar lands on the exact same `/brand/connect` step 0 the "Sí" answer does.
  - `brand_manual_index`       (/brand/manual)          — the nine-step flow. No longer
    linked from the fork above (§ same request), left in place and routable directly:
    `_step_identity`/`_step_palette`/etc. are still shared with `/brand/connect`.

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
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

import reflex as rx

from . import scrapecreators_client
from .auth_state import AuthState
from .creative_state import CreativeState
from .tenant import tenant_uuid
from .ui import (
    app_shell,
    callout,
    card,
    loading_spinner,
    mono,
    page_body,
    page_header,
    stat_card,
    tag,
)
from .ui import tokens as T

logger = logging.getLogger(__name__)

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
    ("Resultados e insights", "Tu marca, lista."),
)
LAST_STEP = len(STEPS) - 1
#: ¿Todo correcto? — one before the true final screen. `resume` opens here on a kit
#: with no gaps, not on `LAST_STEP`: re-entering should offer a review, not skip
#: straight past it to the "you're done" screen.
_CONFIRM_STEP = LAST_STEP - 1

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

# Placeholder plans — the real tiers/pricing are not decided (see CLAUDE.md), but the
# copy itself is real Spanish describing plausible scope per tier, not lorem: nothing
# a first-time user sees should read as unfinished. Revisit the wording once product
# actually locks the tiers.
PLANS: tuple[tuple[str, str, str], ...] = (
    ("basico", "Básico", "Monitorea tu marca y publica contenido en una cuenta conectada."),
    ("pro", "Pro", "Suma señales de la competencia y descubre creadores afines a tu marca."),
    (
        "negocio",
        "Negocio",
        "Varias personas del equipo, más cuentas conectadas y soporte prioritario.",
    ),
    ("agencia", "Agencia", "Gestiona la marca de varios clientes desde un mismo lugar."),
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
        no gaps left opens on the confirmation screen (`_CONFIRM_STEP`), not on
        `LAST_STEP` — Resultados e insights is a destination, not something to resume
        into.
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
            self.step = _CONFIRM_STEP

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

    def _reset_fields(self) -> None:
        """Every wizard-local field back to its default. Plain method, not `@rx.event`
        — same split `BrandConnectState._reset_fields` uses, kept here for the day
        this flow grows a second caller (a Cancelar point of its own, say).

        Named via `finish_to_signals` below, not `reset`: `reset` shadows a built-in
        `rx.State` method (`EventHandlerShadowsBuiltInStateMethodError` at import time
        if a PUBLIC event handler is named that; this private helper is safe, but the
        convention is kept anyway so nobody "simplifies" it back into one)."""
        self.step = 0
        self.subscription = ""
        self.has_logo = ""
        self.logo_brief_1 = ""
        self.logo_brief_2 = ""
        self.logo_brief_3 = ""
        self.logo_key = ""
        self.logo_name = ""
        self.logo_error = ""
        self.picker_color = "#0A3D2E"

    @rx.event
    def finish_to_signals(self) -> rx.event.EventSpec:
        """Mejorar tu perfil y posicionamiento, on this flow's own Resultados e
        insights — the TRUE final screen. Replaces Finalizar entirely (§ request
        2026-09-05): fired REGARDLESS of what `save_kit_form` does — for now this is
        the whole "save", simulated (there is no success/failure branch to key off
        yet). The actual kit content (`CreativeState`'s fields) is untouched; only
        this screen's own navigation/staging state resets, same shape
        `BrandConnectState.finish_to_signals` uses for the connect flow."""
        self._reset_fields()
        return rx.redirect(_SIGNALS_ROUTE)

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
            rows="4",
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


def _step_icon(name: str | rx.Var[str]) -> rx.Component:
    """A themed anchor above a step's fields — the same icon-in-a-tinted-circle
    shape `_fork_option` and the profile/logo avatar placeholders already use
    elsewhere in this file, just applied to the plainer field steps too (request
    2026-09-08: a short field list centred in a full-height card read as too sparse
    on its own — one icon gives the eye something to land on before the small type
    starts).

    `name` accepts a plain string OR an `rx.Var[str]` (§ request 2026-09-09):
    `_connect_step_username` passes a Var that switches with the chosen network so
    the anchor icon reads Instagram vs. TikTok apart, not just the generic "@" every
    network used to share. `rx.icon` itself is fine either way — only the type hint
    here used to claim otherwise."""
    return rx.box(
        rx.icon(name, size=22, color=T.tone_color("accent", 10)),
        width="3rem",
        height="3rem",
        min_height="3rem",
        border_radius="9999px",
        background=T.tone_color("accent", 3),
        display="flex",
        align_items="center",
        justify_content="center",
    )


def _step_body(*children: rx.Component, icon: str | rx.Var[str] | None = None) -> rx.Component:
    """Every step centres its content. Fields still span the column, so their labels
    stay left-read while the block itself sits centred under the title. `icon` is
    optional and additive — steps that already show a prominent graphic of their own
    (the logo preview, a profile avatar) skip it rather than stack two.

    `class_name="q-settle"` (the same entrance `page_body` gives a whole page on
    load — `assets/qualify.css`) so a step's own fields settle in staggered too, not
    just once at page load. On its own this class does nothing on a step CHANGE:
    React reuses the surrounding `<div>` across steps (same position, same tag), so
    the CSS animation never restarts without help — that help is the `key=` on the
    `card(...)` that WRAPS the whole step (content + `_controls()`/`_connect_
    controls()`) in `brand_manual_index`/`brand_connect_index`, not on some inner
    wrapper: keying only the content used to leave the card's own border/shadow
    node reused across steps (request 2026-09-05 — the frame needs to settle in
    too, not just what's inside it), so the key sits as high as the whole card."""
    return rx.vstack(
        *([_step_icon(icon)] if icon is not None else []),
        *children,
        spacing="4",
        width="100%",
        align_items="center",
        class_name="q-settle",
    )


def _loading_view(title: str, subtitle: str = "") -> rx.Component:
    """The one loading affordance both flows use — a spinner, centred, wherever
    something is still in flight (`CreativeState.kit_loading` on page load,
    `BrandConnectState.analyzing` mid-scrape). Centring is the CALLER's job: this
    returns the content, and every caller places it inside a `card(..., flex="1",
    display="flex", align_items="center", justify_content="center")` — the exact shape
    `brand_manual_index`/`brand_connect_index` already give the rest of each step, so a
    loading screen sits in the middle of the same frame the real content would.

    `loading_spinner("lg")` (design-system §5.4), not `rx.spinner` — bigger ring,
    smaller text (`size="2"`, not `size="3"`) than a generic loading state: a
    full-panel wait is the one thing on screen, so the ring can lead and the copy
    can sit quietly under it instead of competing for size."""
    return rx.vstack(
        loading_spinner("lg"),
        rx.text(title, size="2", weight="medium"),
        *([rx.text(subtitle, size="1", color=T.TEXT_MUTED)] if subtitle else []),
        spacing="3",
        align="center",
        width="100%",
        padding="4rem 0",
    )


def _choice_card(
    title: str,
    description: str,
    selected: rx.Var[bool],
    on_click: rx.event.EventHandler,
    *,
    icon: str | None = None,
) -> rx.Component:
    """A big, quiet button that reads as a card. Selection is a ring plus a check mark
    — never a ring alone (§8: a state must not rely on colour/shape alone), same small
    circled-icon affordance `_swatch`'s own delete mark already uses elsewhere in this
    file, so the two "circle in the corner" cues in this flow read as one language.

    A real ``rx.el.button``, not ``rx.box`` + ``on_click`` — §8 forbids that combination
    outright (`layout.py::logout_action` is the existing precedent for a button reset to
    look like a plain row/card): a `<div onClick>` is invisible to the keyboard and to a
    screen reader, and this flow's first two decisions (plan, logo) had no other way to
    reach them without a mouse.

    ``icon`` is optional and additive (§ request 2026-09-09) — every existing call
    site is unaffected. `_connect_step_network` is the one caller that passes it: a
    per-option leading icon so ¿Qué red usas? reads Instagram vs. TikTok apart at a
    glance, not just by the label text next to it. Same tinted-circle treatment
    `_step_icon` gives a whole step's own anchor icon, just smaller and inline."""
    return rx.el.button(
        rx.hstack(
            *(
                [
                    rx.box(
                        rx.icon(icon, size=18, color=T.tone_color("accent", 10)),
                        width="2.25rem",
                        height="2.25rem",
                        min_width="2.25rem",
                        border_radius="9999px",
                        background=T.tone_color("accent", 3),
                        display="flex",
                        align_items="center",
                        justify_content="center",
                    )
                ]
                if icon is not None
                else []
            ),
            rx.vstack(
                rx.text(
                    title,
                    size="3",
                    weight="bold",
                    color=rx.cond(selected, T.tone_color("accent", 11), T.TEXT_STRONG),
                ),
                rx.text(description, size="2", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
            rx.spacer(),
            rx.cond(
                selected,
                rx.box(
                    rx.icon("check", size=12, color="white"),
                    width="1.15rem",
                    height="1.15rem",
                    min_width="1.15rem",
                    border_radius="9999px",
                    background=T.tone_color("accent", 9),
                    display="flex",
                    align_items="center",
                    justify_content="center",
                ),
            ),
            width="100%",
            align="start",
            spacing="3",
        ),
        on_click=on_click,
        type="button",
        cursor="pointer",
        width="100%",
        padding="1rem 1.25rem",
        border="none",
        font="inherit",
        text_align="left",
        border_radius=T.RADIUS_CARD,
        background=T.CARD_BG,
        box_shadow=rx.cond(
            selected,
            f"inset 0 0 0 2px {T.tone_color('accent', 9)}",
            f"inset 0 0 0 1px {rx.color('gray', 7)}",
        ),
        transition=f"box-shadow {T.DUR} {T.EASE}",
        _hover={"box_shadow": f"inset 0 0 0 2px {T.tone_color('accent', 7)}"},
    )


# ---------------------------------------------------------------------------
# The Resultados e insights building blocks — SHARED by both flows' final screen
# (`_step_insights` in the manual flow, `_connect_step_insights` in the connect one):
# same "cuentas parecidas" section either way, so the two paths cannot drift on it.

#: Fase 3 (typed signal detectors, `signals.events` — docs/plan-ingesta-social.md) is
#: not built yet. `/signals` is a standalone placeholder route (`signals_page.py`) so
#: the "Mejorar tu perfil y posicionamiento" CTA — final step of BOTH flows — has
#: somewhere honest to land instead of a dead link or a made-up one.
_SIGNALS_ROUTE = "/signals"

#: Placeholder competitor/influencer suggestions (handle, role label, blurb).
#: Placeholder explicit: hardcoded tuple, not a query — no connection to
#: `search.content_index` / `signals.events` (Fase 2/3) or anything real.
COMPETITOR_SUGGESTIONS: tuple[tuple[str, str, str], ...] = (
    ("@competidor.uno", "Competidor", "Mismo nicho, audiencia parecida."),
    ("@influencer.dos", "Influencer afín", "Podría amplificar tu marca."),
)


def _section_label(text: str) -> rx.Component:
    return rx.text(
        text,
        size="1",
        weight="bold",
        color=T.TEXT_MUTED,
        letter_spacing="0.08em",
        text_transform="uppercase",
    )


def _competitor_card(handle: str, role: str, blurb: str) -> rx.Component:
    return card(
        rx.hstack(
            rx.box(
                rx.icon("user-round", size=18, color=T.TEXT_FAINT),
                width="2.5rem",
                height="2.5rem",
                border_radius="9999px",
                background=T.SURFACE_BG_RAISED,
                display="flex",
                align_items="center",
                justify_content="center",
                flex_shrink="0",
            ),
            rx.vstack(
                rx.hstack(
                    mono(handle, size="2"),
                    tag(role),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(blurb, size="2", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
                min_width="0",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        padding="0.85rem 1rem",
        width="100%",
    )


def _competitors_section() -> rx.Component:
    return rx.vstack(
        _section_label("Cuentas parecidas"),
        *(_competitor_card(handle, role, blurb) for handle, role, blurb in COMPETITOR_SUGGESTIONS),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _finish_button(on_click: rx.event.EventType[()]) -> rx.Component:
    """The last control of BOTH flows' Resultados e insights screen — replaces
    Finalizar entirely (§ request 2026-09-05), it does not sit next to it. `on_click`
    is each flow's own chain (`[CreativeState.save_kit_form, <flow>.finish_to_signals]`
    — the reset differs per flow, the button never should), so the two flows share the
    label/icon while keeping their own state."""
    return rx.button(
        "Mejorar tu perfil",
        rx.icon("arrow-right", size=T.ICON_SM),
        size="2",
        radius=_CONTROL_RADIUS,
        on_click=on_click,
    )


# ---------------------------------------------------------------------------
# The nine steps


def _step_subscription() -> rx.Component:
    return _step_body(
        icon="credit-card",
        *(
            _choice_card(
                label,
                blurb,
                BrandWizardState.subscription == key,
                BrandWizardState.select_plan(key),
            )
            for key, label, blurb in PLANS
        ),
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
        icon="compass",
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
        icon="image",
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
                        color_scheme=T.tone_scale("error"),
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


def _hidden_submit() -> rx.Component:
    """A form's "default button" (WHATWG §4.10.22.2, implicit submission), present so
    Enter reliably submits — invisible, not removed: `display="none"` still counts as
    a valid default button in every major browser, it just does not paint. Without ANY
    submit button, a `<form>` with more than one text field does NOT implicitly submit
    on Enter in some browsers (verified live 2026-09-08 — `_logo_brief_form`'s three
    inputs did not advance the wizard until this was added); a form with exactly one
    field is more forgiving, but this makes every `rx.form` in the wizard behave the
    same way regardless of how many fields it holds, rather than leaning on a browser
    quirk that only covers the single-field case."""
    return rx.el.button(type="submit", tab_index=-1, aria_hidden="true", display="none")


def _logo_brief_form(next_handler: rx.event.EventHandler) -> rx.Component:
    """The three questions behind "te haremos tres preguntas para proponerte uno"
    (`_step_has_logo`'s own "No, todavía no" copy). These used to be literal lorem
    ipsum — as actual field LABELS a first-time user would read, not just example
    input, unlike `PLANS`' pricing copy (real tiers not decided, but that copy is
    real Spanish too now — see `PLANS`'s own comment). Slightly taller inputs than
    the rest of the flow: three fields back to back on one screen read cramped at
    the default height.

    Wrapped in `rx.form` (request 2026-09-08 — same idiom `auth_pages.py`'s login
    already uses) so Enter in any of the three single-line inputs continues, same
    as clicking Continuar: `on_submit=next_handler` fires with no args because
    `next_step` itself takes none on either flow's state — Reflex picks the matching
    `on_submit` event-spec variant off the target handler's own signature, the same
    way `on_click=BrandWizardState.next_step` already works with no args elsewhere
    in this file. `next_handler` is a parameter, not hardcoded to `BrandWizardState.
    next_step` (as it used to be before `_step_logo` was shared with the connect
    flow, § request 2026-09-09): each flow keeps its own cursor
    (`BrandWizardState.step` vs. `BrandConnectState.step`), and this form has no way
    to know which one is live without being told. `_labeled_area` (multi-line, "uno
    por línea") deliberately does NOT get this: Enter there has to stay a newline."""
    return rx.form(
        _step_body(
            _labeled_input(
                "¿Qué estilo buscas?",
                BrandWizardState.logo_brief_1,
                BrandWizardState.set_logo_brief_1,
                "Minimalista, ilustrado, tipográfico…",
                height="3.25rem",
            ),
            _labeled_input(
                "¿Qué quieres que transmita?",
                BrandWizardState.logo_brief_2,
                BrandWizardState.set_logo_brief_2,
                "Confianza, cercanía, innovación…",
                height="3.25rem",
            ),
            _labeled_input(
                "¿Tienes referencias que te gusten?",
                BrandWizardState.logo_brief_3,
                BrandWizardState.set_logo_brief_3,
                "Una marca, un logo o un estilo que admires",
                height="3.25rem",
            ),
            icon="pencil-line",
        ),
        _hidden_submit(),
        on_submit=next_handler,
        width="100%",
    )


def _step_logo(next_handler: rx.event.EventHandler) -> rx.Component:
    """Branches on ¿Tienes logo?. `has_logo == "si"` imports a file; anything else
    asks the brief — so an unanswered question lands on the brief rather than on a
    blank screen. `next_handler` (§ request 2026-09-09) is which flow's cursor the
    brief form's Enter-to-submit should advance — see `_logo_brief_form`."""
    return rx.cond(
        BrandWizardState.has_logo == "si",
        _logo_upload_field(),
        _logo_brief_form(next_handler),
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
    the click alone is the "show me this one" gesture, no change required.

    The pencil (`.q-swatch-edit`, ruled in `assets/qualify.css` next to `.q-fork-arrow`)
    fades in on hover over a dark scrim, `pointer_events="none"` so it never steals the
    click from the transparent colour input underneath — a second, visual reinforcement
    of "this circle is what you edit", on top of the text hint `_step_palette` gives
    the same rule (request 2026-09-08: a swatch reading only as "selected" led a
    first-time user to reach for the wheel instead, which ADDS rather than edits).

    The delete mark is a real `<button>` (§8 — same reason `_choice_card` moved off
    `rx.box` + `on_click`), not just for the keyboard: it also carries the accessible
    name (`aria-label`) the bare colour swap circle has no room for."""
    return rx.box(
        rx.box(
            rx.input(
                type="color",
                value=colour,
                on_click=BrandWizardState.set_picker_color(colour),
                on_change=BrandWizardState.set_swatch_color(index),
                aria_label="Editar este color",
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
            rx.box(
                rx.icon("pencil", size=11, color="white"),
                class_name="q-swatch-edit",
                position="absolute",
                inset="0",
                border_radius="9999px",
                display="flex",
                align_items="center",
                justify_content="center",
                pointer_events="none",
            ),
            title=colour,
            class_name="q-swatch",
            position="relative",
            cursor="pointer",
            width="2.25rem",
            height="2.25rem",
            border_radius="9999px",
            background=colour,
            box_shadow=f"inset 0 0 0 1px {rx.color('gray', 7)}",
            # P8: a transform/scale change is a size change, not a color/opacity one —
            # `T.SPRING`, not `T.EASE` (same split `.q-lift`'s own transform/box-shadow
            # pair makes in `assets/qualify.css`).
            transition=f"transform {T.DUR} {T.SPRING}",
            _hover={"transform": "scale(1.15)"},
        ),
        rx.el.button(
            rx.icon("x", size=10, color="white"),
            on_click=BrandWizardState.remove_colour(index).stop_propagation,
            aria_label="Quitar este color",
            type="button",
            border="none",
            padding="0",
            font="inherit",
            position="absolute",
            top="-0.25rem",
            right="-0.25rem",
            width="1rem",
            height="1rem",
            border_radius="9999px",
            background=T.tone_color("error", 9),
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
            aria_label="Añadir un color a la paleta",
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
        box_shadow=f"inset 0 0 0 1px {rx.color('gray', 7)}",
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
        border=f"1px solid {rx.color('gray', 7)}",
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

    Renders `CreativeState.palette_colors` (filtered), not `kit_palette.split(",")`
    directly — a fresh kit's `kit_palette` is `""`, and `"".split(",")` is `['']`, not
    `[]`: rendering the raw split put one phantom swatch on screen that no click could
    ever remove (every handler already filters empty entries before indexing, so that
    swatch's index pointed past the end of the real list). The empty-state line covers
    the same gap for a first-time user: an empty step with nothing but a wheel gives no
    hint that the wheel is what starts the palette.

    The swatches now sit inside their own `card()` (request 2026-09-08) instead of
    floating loose on the panel background — the same bordered-surface treatment
    `_colour_readout` already gives the current pick, so "these are your saved
    colours" and "this is what you're about to add" read as two related but distinct
    surfaces, not one undifferentiated wash of circles.

    The one-line hint used to live ONLY under the wheel ("toca la rueda para añadir…
    toca uno ya añadido para editarlo"), which is the correct rule but the wrong
    place to read it: a first-time user clicks a swatch (which lights up in the
    readout, reading as "selected"), reaches for the big colourful wheel to change
    it — the most prominent control on screen — and gets a new colour ADDED instead,
    the old one untouched (reported live, 2026-09-08). The rule was never wrong, the
    single caption just wasn't anchored where the mistake actually happens. Split in
    two, each next to the control it describes: "toca un color para cambiarlo" sits
    under the swatches themselves, "toca la rueda para añadir uno nuevo" stays under
    the wheel — so whichever control you're looking at when you reach for it is the
    one telling you what it does.
    """
    return _step_body(
        card(
            rx.vstack(
                _section_label("Tu paleta"),
                rx.cond(
                    CreativeState.has_palette_colors,
                    rx.fragment(
                        rx.hstack(
                            rx.foreach(CreativeState.palette_colors, _swatch),
                            spacing="3",
                            wrap="wrap",
                            justify="center",
                            width="100%",
                        ),
                        rx.text(
                            "Toca un color para cambiarlo.",
                            size="1",
                            color=T.TEXT_FAINT,
                        ),
                    ),
                    rx.text(
                        "Aún no has añadido ningún color.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                ),
                spacing="3",
                width="100%",
                align_items="center",
            ),
            padding="1.25rem 1.5rem",
            width="100%",
        ),
        rx.vstack(
            _colour_wheel(),
            rx.text(
                "Toca la rueda para añadir un color nuevo.",
                size="1",
                color=T.TEXT_FAINT,
                text_align="center",
                max_width="18rem",
            ),
            _colour_readout(),
            spacing="3",
            align="center",
            width="100%",
        ),
        icon="palette",
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
        icon="sliders-horizontal",
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
        icon="message-square-text",
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
        callout(
            "Esto se comprueba siempre, incluso si desactivas el resto.",
            "warn",
            icon="shield-alert",
        ),
        icon="shield-alert",
    )


def _recap_row(label: str, value: rx.Var[str], fallback: str = "Sin definir") -> rx.Component:
    """A label + value line. The value column needs `min_width="0"` +
    `overflow_wrap="anywhere"` — a flex item's default min-width is its content's
    natural width, so an UNBROKEN value (e.g. two comma-joined hex codes, no spaces to
    wrap at — `CreativeState.kit_palette` with 2+ colours) pushes the row past the
    card's edge instead of wrapping onto a second line. Same fix `_colour_readout`
    documents for the same reason."""
    return rx.hstack(
        rx.text(label, size="2", color=T.TEXT_MUTED, min_width="9rem", flex_shrink="0"),
        rx.cond(
            value != "",
            rx.text(value, size="2", overflow_wrap="anywhere", min_width="0", flex="1"),
            rx.text(fallback, size="2", color=T.TEXT_FAINT),
        ),
        spacing="3",
        width="100%",
        align="start",
    )


def _plan_label(key: rx.Var[str]) -> rx.Var[str]:
    """The plan's human label for the recap — `BrandWizardState.subscription` stores
    the internal `PLANS` key ("basico"), which is what a first-time user would see on
    ¿Todo correcto? without this: the slug they never typed, not the label they
    clicked. Falls to "" (unmatched, or nothing chosen yet) so `_recap_row`'s own
    "Sin definir" still applies — this only ever renames a real value, never invents
    one for an empty key."""
    return rx.match(key, *[(k, label) for k, label, _ in PLANS], "")


def _palette_recap_row() -> rx.Component:
    """Same label column `_recap_row` uses, but the value is a row of small swatches —
    not the raw comma-joined hex string `_recap_row` would otherwise show. A confirm
    screen exists so the operator can catch a mistake before saving; a colour reads in
    a glance, six characters of hex do not."""
    return rx.hstack(
        rx.text("Paleta", size="2", color=T.TEXT_MUTED, min_width="9rem", flex_shrink="0"),
        rx.cond(
            CreativeState.has_palette_colors,
            rx.hstack(
                rx.foreach(
                    CreativeState.palette_colors,
                    lambda colour: rx.box(
                        title=colour,
                        width="1.25rem",
                        height="1.25rem",
                        border_radius="9999px",
                        background=colour,
                        box_shadow=f"inset 0 0 0 1px {rx.color('gray', 7)}",
                        flex_shrink="0",
                    ),
                ),
                spacing="2",
                wrap="wrap",
            ),
            rx.text("Sin definir", size="2", color=T.TEXT_FAINT),
        ),
        spacing="3",
        width="100%",
        align="center",
    )


def _step_confirm() -> rx.Component:
    # No logo row here (per request) — the staged logo isn't part of this recap.
    return _step_body(
        card(
            rx.vstack(
                _recap_row("Plan", _plan_label(BrandWizardState.subscription)),
                rx.divider(),
                _recap_row("Posicionamiento", CreativeState.kit_positioning),
                _recap_row("Audiencia", CreativeState.kit_audience),
                rx.divider(),
                _palette_recap_row(),
                rx.divider(),
                _recap_row("Palabras vetadas", CreativeState.kit_banned_words, "Ninguna"),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            padding="1.25rem 1.5rem",
            width="100%",
        ),
        icon="clipboard-check",
    )


def _step_insights() -> rx.Component:
    """The manual flow's own TRUE final screen (§ STEPS, `LAST_STEP`) — mirrors
    `_connect_step_insights`'s shape (identity block + `_competitors_section`, both
    ending in `_finish_button`), but with just the uploaded logo standing in for a
    profile recap — no name, no card chrome around it (per request 2026-09-05: the
    logo alone, not a bordered identity card) — and NO metrics: a from-scratch kit
    has no scraped account to report a rate or an average FOR, so this shows none
    rather than numbers that would not correspond to anything real.
    """
    return _step_body(
        rx.cond(
            BrandWizardState.logo_key != "",
            rx.image(
                src=rx.get_upload_url(BrandWizardState.logo_key),
                alt="Logo",
                height="6rem",
                max_width="100%",
                object_fit="contain",
            ),
            rx.box(
                rx.icon("image", size=28, color=T.TEXT_FAINT),
                width="6rem",
                height="6rem",
                border_radius="9999px",
                background=T.SURFACE_BG_RAISED,
                display="flex",
                align_items="center",
                justify_content="center",
            ),
        ),
        _competitors_section(),
    )


def _window() -> rx.Component:
    """One step at a time. `rx.match` on the cursor, with step 1 as the fallback so an
    out-of-range cursor still renders a form instead of a blank screen."""
    return rx.match(
        BrandWizardState.step,
        (0, _step_subscription()),
        (1, _step_identity()),
        (2, _step_has_logo()),
        (3, _step_logo(BrandWizardState.next_step)),
        (4, _step_palette()),
        (5, _step_voice_tone()),
        (6, _step_voice_examples()),
        (7, _step_restrictions()),
        (8, _step_confirm()),
        (9, _step_insights()),
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


def _step_counter(step: rx.Var[int], total: int) -> rx.Component:
    """The wizard's `kicker` for `ui.page_header` — "PASO 5 DE 10" above the title,
    same eyebrow treatment `_section_label`/the sidebar's zone labels already use.
    Was its own header (`_flow_header`, since removed) built a title row from scratch
    next to `page_header`'s own, duplicating the exact same title+subtitle+colour-mode
    scaffold for no reason a shared header couldn't cover — the only real difference
    the wizard needs is a bigger title and this line above it, and `page_header` now
    takes both as plain parameters (`title_size`, `kicker`)."""
    return rx.text(
        "Paso ",
        step + 1,
        f" de {total}",
        size="1",
        weight="bold",
        color=T.TEXT_MUTED,
        letter_spacing="0.08em",
        text_transform="uppercase",
    )


def _manual_can_continue() -> rx.Var[bool]:
    """Whether the CURRENT step's requirement is satisfied (§ request 2026-09-09) —
    gates `_controls`'s Continuar the same way `_connect_can_continue` gates the
    connect flow's, reading the exact same shared fields (`_identity_complete`/
    `_logo_step_complete` are the one place either flow checks them, so the two
    gates cannot drift). Every step not named below always returns True: ¿Cómo
    suena? (the tone sliders default to 50 — never a gap), Lo que nunca debe decir
    (this module's own docstring: "legitimately optional") and ¿Todo correcto?
    (review only)."""
    return rx.match(
        BrandWizardState.step,
        (0, BrandWizardState.subscription != ""),
        (1, _identity_complete()),
        (2, BrandWizardState.has_logo != ""),
        (3, _logo_step_complete()),
        (4, CreativeState.kit_palette != ""),
        (6, CreativeState.kit_do_examples != ""),
        True,
    )


def _controls() -> rx.Component:
    """Small, quiet, at the bottom. The last step (Resultados e insights) swaps
    Continuar for `_finish_button` — it replaces Finalizar entirely (§ request
    2026-09-05), `save_kit_form` still chained with it so finishing actually persists
    before it lands anywhere. ¿Todo correcto? (`_CONFIRM_STEP`) is a plain Continuar
    now, same as any other step — it no longer sits at the end.

    `back` is never disabled any more: `prev_step` itself redirects to `/brand` once
    the cursor is already at step 0, so the button always does something. Continuar
    IS disabled (§ request 2026-09-09, `disabled=~_manual_can_continue()`) while the
    current step's own requirement is unmet — see that function."""
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
            _finish_button([CreativeState.save_kit_form, BrandWizardState.finish_to_signals]),
            rx.button(
                "Continuar",
                rx.icon("chevron-right", size=T.ICON_SM),
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandWizardState.next_step,
                disabled=~_manual_can_continue(),
            ),
        ),
        width="100%",
        align="center",
        spacing="3",
    )


def brand_manual_index() -> rx.Component:
    """`page_header` (the app's one standard header, `title_size="8"` + `kicker` — see
    `_step_counter`'s own docstring for why this no longer builds a header of its own)
    sits OUTSIDE `page_body`, exactly like every other page in the app: it is a sibling
    `app_shell` child, not content inside the scrolling panel. The border below it
    fills down to the panel's bottom (`flex="1"` all the way through `page_body`, no
    `100vh` maths — see the note where `_SCREEN_MIN_HEIGHT` used to be) instead of
    hugging its own content height. Inside that tall frame, the card is itself a flex
    column with `justify_content="space-between"`: the fields stay in a narrow,
    readable, centred column at the top (a single-line hex input stretched to 1440px
    reads worse than the frame around it being that wide), while `_controls()` spans
    the card's FULL width and sits pinned to its bottom edge — Atrás at the
    bottom-left corner, Continuar/Finalizar at the bottom-right, not floating just
    under the fields."""
    return app_shell(
        page_header(
            _heading_for(0),
            _heading_for(1),
            kicker=_step_counter(BrandWizardState.step, len(STEPS)),
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
                    # No controls while loading — same shape `brand_connect_index` uses
                    # for `BrandConnectState.analyzing`: a spinner, centred in the same
                    # frame the real step would occupy, nothing to click yet.
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
                            max_width="34rem",
                            align_self="center",
                            align_items="center",
                            # Takes the card's free height and centres its content in it,
                            # so a two-field step sits in the middle of its frame instead
                            # of clinging to the top with a void above the controls.
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
                        # `key` on the CARD itself, not just its content — request
                        # 2026-09-05: the border/frame is part of what should settle in,
                        # not just what's inside it. Keying only the inner vstack (the
                        # first cut of this fix) left the card's own DOM node reused
                        # across steps, so the border/shadow never moved — only the text
                        # inside it did. Keying the whole `card()` forces IT to remount
                        # too, which is what makes `page_body`'s own "q-settle" (the
                        # card is one of ITS direct children) replay on every step
                        # change, animating the frame and its content as one unit.
                        key=BrandWizardState.step.to_string(),
                        # `justify_content="space-between"` alone collapses to ~0 the
                        # moment the fields fill the card's free height — true on a short
                        # mobile viewport for most steps (Plan, Paleta, Enséñale a
                        # hablar, Lo que nunca debe decir, Todo correcto...), pinning
                        # Atrás/Continuar right under the content. `gap` sets a MINIMUM
                        # the two flex items are never closer than, regardless of how
                        # much free space is left — space-between still spreads any
                        # space beyond it, so a short step still looks exactly as it did
                        # before.
                        gap="1.5rem",
                    ),
                ),
                spacing="4",
                width="100%",
                # Fills the panel through `page_body` (`flex: 1 0 auto`) instead of
                # computing a height. No top/bottom padding of its own: `page_header`
                # (now a sibling, not a sibling-turned-first-child) already gives the
                # standard `PAD_HEADER` gap above, and `PAD_BODY` already leaves the
                # page's bottom gutter — stacking a manual 3rem on top of that was
                # only ever compensating for not using `page_header` in the first
                # place.
                flex="1",
                min_height="0",
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
    the card inside shrinks to its own content's width instead of the frame's.

    The trailing arrow (`.q-fork-arrow`, ruled in `assets/qualify.css` next to `.q-lift`
    itself) nudges right and turns accent on hover — a second, cheap reinforcement that
    this whole surface goes somewhere, on top of the lift the card already gets."""
    return rx.link(
        card(
            rx.vstack(
                rx.hstack(
                    rx.icon(icon, size=26, color=T.tone_color("accent", 10)),
                    rx.spacer(),
                    rx.icon(
                        "arrow-right",
                        size=T.ICON_MD,
                        class_name="q-fork-arrow",
                    ),
                    width="100%",
                    align="center",
                ),
                # §8: one h1 per page, owned by `page_header` — an entity title inside
                # a card is h3 (design-system.md §3.2's own table), never the default h1
                # `rx.heading` renders without an explicit `as_=`.
                rx.heading(title, size="4", as_="h3"),
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
    """The entry the sidebar's «Marca» lands on — now a yes/no question instead of a
    manual-vs-connect fork (§ request 2026-09-09): every brand kit starts from a
    social profile now, "Empezar de cero" as a parallel path stopped making sense.
    "Sí" walks straight into the scraper (`/brand/connect`); "No" detours through
    `brand_connect_setup_index` first, then joins the exact same door. Same framing
    the old fork used: `page_header` (§ `_step_counter`'s docstring — the wizard's own
    header was folded into the standard one) sits outside `page_body`, and the border
    below it grows to fill the panel (`flex="1"` on the card, `min_height` on this
    vstack so there is room to grow into) instead of stopping short and leaving bare
    panel background below it."""
    return app_shell(
        page_header("Brandkit", "¿Tienes redes sociales para tu marca?", title_size="8"),
        page_body(
            rx.vstack(
                card(
                    rx.vstack(
                        _fork_option(
                            "at-sign",
                            "Sí, tengo redes",
                            "Leemos tu perfil y te proponemos el kit a partir de lo que ya "
                            "publicas.",
                            "/brand/connect",
                        ),
                        _fork_option(
                            "user-plus",
                            "No, todavía no",
                            "Te ayudamos a crear tu cuenta en Instagram o TikTok antes de empezar.",
                            "/brand/connect/setup",
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
            ),
        ),
    )


# ---------------------------------------------------------------------------
# /brand/connect/setup — shown only on brand_choice_index's "No, todavía no" answer.
# Purely informational: no state of its own, nothing to persist. Both buttons are
# plain redirects, not a wizard cursor — this screen sits BEFORE the scraper flow's
# own step 0, not inside it.

#: (icon, network name, what to do, signup URL). Real Spanish copy, not lorem — same
#: rule `PLANS`/`RECOMMENDATIONS` follow: a first-time user reads this as the actual
#: instructions, not filler.
#: Lucide has no brand-logo icons (verified against `reflex_components_lucide.icon`
#: — "instagram"/"tiktok" both fall back to a generic circle-help with a compile
#: warning), so these are generic stand-ins: a camera for Instagram's photo/reels
#: focus, a music note for TikTok's audio-led short video.
ACCOUNT_SETUP_INFO: tuple[tuple[str, str, str, str], ...] = (
    (
        "camera",
        "Instagram",
        "Crea una cuenta gratuita, cámbiala a perfil profesional y sube al menos una "
        "publicación — así tenemos contenido real que leer.",
        "https://www.instagram.com/accounts/emailsignup/",
    ),
    (
        "music_2",
        "TikTok",
        "Regístrate, verifica tu correo y sube un primer vídeo antes de continuar.",
        "https://www.tiktok.com/signup",
    ),
)


def _account_setup_card(icon: str, title: str, blurb: str, href: str) -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.icon(icon, size=22, color=T.tone_color("accent", 10)),
                rx.heading(title, size="4", as_="h3"),
                spacing="2",
                align="center",
            ),
            rx.text(blurb, size="2", color=T.TEXT_MUTED),
            rx.link(
                rx.hstack(
                    rx.text(f"Crear cuenta en {title}", size="2", weight="medium"),
                    rx.icon("external-link", size=T.ICON_SM),
                    spacing="1",
                    align="center",
                ),
                href=href,
                target="_blank",
                rel="noopener noreferrer",
                color=T.tone_color("accent", 11),
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        padding="1.5rem",
        width="100%",
    )


def brand_connect_setup_index() -> rx.Component:
    """The "No, todavía no" branch of `brand_choice_index`. Same shell as every other
    screen in this file (`app_shell` + `page_header` outside `page_body`), but not a
    wizard step: it has no cursor, no state, nothing that survives leaving the page —
    it exists purely to hand off to `/brand/connect` once an account exists. Atrás
    goes back to the question (`/brand`); Continuar goes to `/brand/connect`'s own
    step 0 (choose network) — the exact same door the "Sí" answer walks through,
    since by the time the operator is back here they should have a profile to
    scrape."""
    return app_shell(
        page_header(
            "Crea tu cuenta",
            "Necesitas un perfil en Instagram o TikTok antes de leer tu contenido.",
            title_size="8",
        ),
        page_body(
            rx.vstack(
                card(
                    # Same narrow-centred-column wrapper `brand_manual_index`/
                    # `brand_connect_index` give every step's own content (`max_width`
                    # + `align_self="center"`) — missing here is why this screen read
                    # "descentrada" (request 2026-09-09): without it the two account
                    # cards stretched to the CARD's full panel-spanning width instead
                    # of sitting in a readable centred column like every other step.
                    rx.vstack(
                        *(
                            _account_setup_card(icon, title, blurb, href)
                            for icon, title, blurb, href in ACCOUNT_SETUP_INFO
                        ),
                        spacing="4",
                        width="100%",
                        max_width="34rem",
                        align_self="center",
                        flex="1",
                        justify_content="center",
                    ),
                    rx.hstack(
                        rx.button(
                            rx.icon("chevron-left", size=T.ICON_SM),
                            "Atrás",
                            variant="ghost",
                            size="2",
                            radius=_CONTROL_RADIUS,
                            on_click=rx.redirect("/brand"),
                        ),
                        rx.spacer(),
                        rx.button(
                            "Ya la creé, continuar",
                            rx.icon("chevron-right", size=T.ICON_SM),
                            size="2",
                            radius=_CONTROL_RADIUS,
                            on_click=rx.redirect("/brand/connect"),
                        ),
                        width="100%",
                        align="center",
                        spacing="3",
                    ),
                    padding="1.75rem",
                    width="100%",
                    flex="1",
                    display="flex",
                    flex_direction="column",
                    justify_content="space-between",
                    gap="1.5rem",
                ),
                spacing="4",
                width="100%",
                flex="1",
                min_height="0",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# /brand/connect — the scraper flow, reached from both /brand answers now (§ request
# 2026-09-09; it used to be only the "ya tengo redes" fork option).
#
# Steps 5, 11-15 are the SAME renderers the manual flow uses, so the two paths
# cannot drift: only steps 0-3 (network, username, profile, recommendations), 6-7
# (¿Tienes logo?/Tu logo, skipped when the scraped profile already has a picture —
# own `_connect_step_has_logo` because the choice needs to advance THIS flow's
# cursor, see its docstring), 8-10 (¿Eres influencer o una marca?/¿Tu negocio está
# en Google Maps?/Súmate a Google Maps, § request 2026-09-09 — same self-reported,
# not-scraped reasoning as the logo pair) and CONNECT_LAST, Resultados e insights
# (added 2026-09-04, moved the same day to sit AFTER ¿Todo correcto? instead of
# before it) are specific to this one.

_USERNAME_REQUIRED = "Escribe tu usuario para continuar."
_PROFILE_UNAVAILABLE = "No pudimos leer el perfil. Revisa el usuario e inténtalo de nuevo."

#: (key, label, blurb, icon) — the icon is the same generic stand-in
#: `ACCOUNT_SETUP_INFO` already uses for each network (Lucide ships no brand-logo
#: icons, see that tuple's own comment), reused here so ¿Qué red usas? and Crea tu
#: cuenta read as one consistent visual language for the same two networks (§
#: request 2026-09-09 — a shared icon per option instead of one icon for the whole
#: step).
NETWORKS: tuple[tuple[str, str, str, str], ...] = (
    ("instagram", "Instagram", "Reels, carruseles y publicaciones.", "camera"),
    ("tiktok", "TikTok", "Vídeos cortos y galerías de fotos.", "music_2"),
)

#: Placeholder recommendations — hardcoded until the real analysis produces them
#: (no connection to `search.content_index`/`signals.events` yet), but written as
#: real, generic-but-plausible advice, not lorem: this screen exists to feel like
#: "we read your profile", and Latin filler text says the opposite.
RECOMMENDATIONS: tuple[tuple[str, str], ...] = (
    (
        "Publica más vídeo corto",
        "Es el formato que más se comparte en tu categoría ahora mismo.",
    ),
    (
        "Refuerza tu llamada a la acción",
        "Cierra cada pieza con una acción clara: seguir, comprar, escribir.",
    ),
    (
        "Unifica la paleta",
        "Usa los mismos colores en cada publicación para que te reconozcan de inmediato.",
    ),
    (
        "Responde los comentarios",
        "Contestar rápido mejora tu alcance y la confianza de tu audiencia.",
    ),
)

#: Metrics are REAL since 2026-09-10 (§ request "quiero que las métricas sean
#: reales") and WINDOWED over the last `scrapecreators_client.METRICS_WINDOW_DAYS`
#: days (§ request, same day: "un tiempo al cual sacarle la métrica, por ahora
#: semana"): `analyze()` reads the profile AND the user's recent post list
#: (`fetch_profile_and_posts`, a second Scrape Creators read), and
#: `profile_metrics` derives up to three figures from the posts inside the window —
#: publicaciones, interacción (likes + comentarios sobre seguidores) and likes por
#: publicación/vídeo. What was dropped, on purpose: the old placeholder "Crecimiento
#: mensual" — a growth figure needs two reads apart in time and this flow keeps one
#: snapshot with no history, so there is nothing real to put behind it yet. The
#: eventual version over `search.content_index` / `signals.events` (Fase 2/3,
#: `docs/plan-ingesta-social.md`) can bring it back. Only the connect flow has
#: metrics — the manual flow has no scraped profile to report a rate or an average
#: FOR, so it shows none at all.

#: The count-up animation (§ request 2026-09-05): `BrandConnectState.metric_values`
#: ticks from 0 to each target over this many seconds, in this many frames — a
#: background event walking the value up server-side (`advance_to_insights`), since
#: there is no client-side animation primitive in play here. ~37ms/frame is smooth
#: enough for a plain numeric counter without needing more frames than a websocket
#: update per frame can comfortably carry.
_METRIC_ANIMATION_SECONDS = 0.9
_METRIC_ANIMATION_STEPS = 24

#: § request 2026-09-09 — a placeholder threshold (no product decision behind the
#: exact number), just enough to distinguish "just created" from "has some real
#: activity". See `BrandConnectState.is_new_account`.
_NEW_ACCOUNT_FOLLOWER_THRESHOLD = 50

CONNECT_STEPS: tuple[tuple[str, str], ...] = (
    ("¿Qué red usas?", "Empezamos por donde ya tienes audiencia."),
    ("¿Cuál es tu usuario?", "Lo leeremos para proponerte el kit."),
    ("Esto es lo que vemos", "Confirma que es tu perfil."),
    ("Lo que te proponemos", "Podrás ajustarlo todo después."),
    ("Elige tu plan", "Puedes cambiarlo más adelante."),
    ("¿Quién es la marca?", "Lo que define su lugar y a quién le habla."),
    # ¿Tienes logo? / Tu logo (§ request 2026-09-09) — SKIPPED at runtime (see
    # `next_step`/`prev_step`) when the scraped profile already has a picture; only
    # actually shown when `profile_pic` came back empty. Same copy + renderers the
    # manual flow uses (`_step_has_logo`/`_step_logo`, STEPS[2]/STEPS[3]) via
    # `_connect_step_has_logo`, so the two flows cannot drift on this question either.
    ("¿Tienes logo?", "De tu respuesta depende el siguiente paso."),
    ("Tu logo", "Lo usaremos en cada pieza que generemos."),
    # ¿Eres influencer o una marca? (§ request 2026-09-09) — gates the Google Maps
    # pair below: a creator has no "local" business to list, so `answer_account_kind`
    # skips both of them outright on "influencer". Always asked, self-reported, same
    # as the Maps question itself.
    ("¿Eres influencer o una marca?", "Así te mostramos los pasos que sí aplican para ti."),
    # ¿Estás en Google Maps? / Súmate a Google Maps (§ request 2026-09-09) — SKIPPED
    # as a pair for "influencer" (above); for "marca" the question is ALWAYS asked
    # (there is no scraped signal to auto-detect a Maps listing the way `profile_pic`
    # stands in for a logo) and only the follow-up steps screen is conditional, on
    # the ANSWER ("no"). See `answer_account_kind` / `answer_has_maps`.
    ("¿Tu negocio está en Google Maps?", "Así te encuentran cuando buscan cerca."),
    ("Súmate a Google Maps", "Son unos minutos y quedas visible en el mapa."),
    ("Paleta de colores", "Los colores con los que se te reconoce."),
    ("¿Cómo suena?", "Ajusta el tono en cuatro ejes."),
    ("Enséñale a hablar", "Ejemplos reales valen más que cualquier descripción."),
    ("Lo que nunca debe decir", "Reglas duras: una violación es un rechazo."),
    ("¿Todo correcto?", "Revisa antes de guardar."),
    ("Resultados e insights", "Cómo se ve tu cuenta hoy."),
)
CONNECT_LAST = len(CONNECT_STEPS) - 1
#: The last screen of this flow's OWN preview stretch (steps 0-3) before it joins the
#: shared kit-setup steps — where Cancelar makes sense instead of Atrás. Resultados e
#: insights (the true final screen, CONNECT_LAST) needs neither: Atrás still works
#: normally there (back to Todo correcto), and Finalizar is the forward action.
_LAST_PREVIEW_STEP = 3

#: ¿Tienes logo? / Tu logo's indices in `CONNECT_STEPS` — the two steps `next_step`/
#: `prev_step` jump clean over whenever `profile_pic` is already set. Named rather
#: than inlined as literal 6/7 so a future reorder of the tuple above cannot silently
#: desync the skip logic from the steps it is skipping.
_LOGO_QUESTION_STEP = 6
_LOGO_UPLOAD_STEP = 7

#: ¿Eres influencer o una marca?'s own index — answering "influencer" here jumps
#: clean over BOTH Maps steps below (see `answer_account_kind`).
_ACCOUNT_KIND_STEP = 8

#: ¿Tu negocio está en Google Maps? / Súmate a Google Maps's indices — the pair is
#: skipped together on "influencer" above; independently, the SECOND one alone is
#: also skipped on a "sí" answer to the question itself (see `answer_has_maps`).
#: Neither skip is automatic the way the logo question's is: there is no scraped
#: signal for either "is this an influencer" or "is there a Maps listing" the way
#: `profile_pic` stands in for a logo.
_MAPS_QUESTION_STEP = 9
_MAPS_STEPS_STEP = 10


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
    profile_category: str = ""
    profile_followers: str = ""
    #: Raw follower count `analyze()` also stashes — `profile_followers` is already
    #: formatted for display ("12.345" or "—"), so `is_new_account` needs its own
    #: numeric copy rather than parsing that string back apart.
    profile_followers_count: int = 0
    profile_pic: str = ""

    #: ¿Eres influencer o una marca?'s answer — "influencer" | "marca" | ""
    #: (unanswered). Gates whether the Google Maps question even gets asked (see
    #: `answer_account_kind`) — a creator has no "local" business to list.
    account_kind: str = ""

    #: ¿Tu negocio está en Google Maps?'s answer — "si" | "no" | "" (unanswered).
    #: Self-reported only: unlike a logo, there is no scraped signal to check this
    #: against, so it lives here rather than being auto-set like `profile_pic`.
    has_maps: str = ""

    #: The real metrics `analyze()` derived from the profile read
    #: (`scrapecreators_client.profile_metrics`), as parallel lists — one entry per
    #: metric, in display order, possibly empty. Parallel typed lists rather than one
    #: `list[dict]` of mixed value types: Reflex serializes `list[str]`/`list[float]`
    #: state vars without ceremony, and `metric_cards` below zips them back into the
    #: one shape the grid renders.
    metric_labels: list[str] = []
    metric_hints: list[str] = []
    metric_suffixes: list[str] = []
    metric_decimals: list[int] = []
    metric_targets: list[float] = []
    #: The count-up animation's live values, same length as `metric_targets`, ticked
    #: from 0 up to each target by `advance_to_insights`.
    metric_values: list[float] = []

    @rx.var
    def is_new_account(self) -> bool:
        """§ request 2026-09-09: a brand-new account's real follower count (near
        zero) makes a per-follower rate meaningless — "3.2% interacción" over a
        handful of followers is noise, not a measurement. `_connect_step_insights`
        hides the whole Métricas section below it rather than showing that, same
        principle `_step_insights` (the manual flow's own final screen) already
        follows for having no scraped account to report a rate FOR at all."""
        return self.profile_followers_count < _NEW_ACCOUNT_FOLLOWER_THRESHOLD

    @rx.var
    def has_metrics(self) -> bool:
        """False when `profile_metrics` could derive nothing from the read (private
        profile, empty post sample, no stats) — the Métricas section is then hidden
        outright instead of rendering an empty grid."""
        return len(self.metric_targets) > 0

    @rx.var
    def metric_cards(self) -> list[dict[str, str]]:
        """What `_metric_grid` renders: `{label, value, hint}` per metric, `value`
        already formatted from the live `metric_values` frame (`12.4K`, `3.2%`,
        `2.5/sem`, `850`) so the component only ever prints a string."""
        cards: list[dict[str, str]] = []
        for i, label in enumerate(self.metric_labels):
            value = self.metric_values[i] if i < len(self.metric_values) else 0.0
            decimals = self.metric_decimals[i]
            cards.append(
                {
                    "label": label,
                    "value": f"{value:.{decimals}f}{self.metric_suffixes[i]}",
                    "hint": self.metric_hints[i],
                }
            )
        return cards

    def _set_metrics(self, metrics: list[dict]) -> None:
        """Unpack `profile_metrics`' output into the parallel lists above."""
        self.metric_labels = [str(m["label"]) for m in metrics]
        self.metric_hints = [str(m["hint"]) for m in metrics]
        self.metric_suffixes = [str(m["suffix"]) for m in metrics]
        self.metric_decimals = [int(m["decimals"]) for m in metrics]
        self.metric_targets = [float(m["target"]) for m in metrics]
        self.metric_values = [0.0] * len(metrics)

    @rx.event
    def next_step(self) -> None:
        """Jumps clean over ¿Tienes logo?/Tu logo (§ `_LOGO_QUESTION_STEP`) when the
        scraped profile already came back with a picture — that picture stands in
        for a logo, so asking would be a dead question. A profile with no picture
        falls through to the question normally, exactly like a from-scratch kit
        does."""
        target = self.step + 1
        if target == _LOGO_QUESTION_STEP and self.profile_pic.strip():
            target = _LOGO_UPLOAD_STEP + 1
        self.step = min(target, CONNECT_LAST)

    @rx.event
    def prev_step(self) -> rx.event.EventSpec | None:
        """Same rule as the manual flow's `BrandWizardState.prev_step`: back from the
        first step leaves the wizard rather than sitting disabled. Mirrors three
        forward skips:
          - `next_step`'s own: stepping back into the logo steps from ¿Eres
            influencer o una marca? jumps straight to ¿Quién es la marca? when they
            were skipped going forward too (neither logo step was ever shown —
            there is nothing to land ON).
          - `answer_account_kind`'s "influencer": stepping back from Paleta lands ON
            ¿Eres influencer o una marca?, not past it — THAT question was shown and
            answered; the two Maps steps after it were what got skipped.
          - `answer_has_maps`'s "sí": stepping back from Paleta lands ON ¿Tu negocio
            está en Google Maps?, not past it — same reasoning, only its follow-up
            steps screen was skipped."""
        if self.step == 0:
            return rx.redirect("/brand")
        target = self.step - 1
        if target == _LOGO_UPLOAD_STEP and self.profile_pic.strip():
            target = _LOGO_QUESTION_STEP - 1
        elif target == _MAPS_STEPS_STEP:
            if self.account_kind == "influencer":
                target = _ACCOUNT_KIND_STEP
            elif self.has_maps == "si":
                target = _MAPS_QUESTION_STEP
        self.step = target
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
    async def answer_has_logo(self, value: str) -> None:
        """¿Tienes logo?'s own choice handler — same shape as `BrandWizardState.
        answer_has_logo` (answering has no other content on the screen, so it moves
        straight on rather than waiting for a second click on Continuar), but writing
        into `BrandWizardState.has_logo` (cross-state, same idiom `commit_picked_color`
        already uses) while advancing THIS flow's own cursor. Reusing the manual
        flow's handler directly would have advanced `BrandWizardState.step` instead —
        a cursor nothing in this flow reads."""
        wizard = await self.get_state(BrandWizardState)
        wizard.has_logo = value
        self.next_step()

    @rx.event
    def answer_account_kind(self, value: str) -> None:
        """¿Eres influencer o una marca?'s own choice handler. "Marca" continues
        normally into ¿Tu negocio está en Google Maps? (`_MAPS_QUESTION_STEP`); an
        influencer has no local business to list, so this skips BOTH Maps steps
        outright — straight to Paleta."""
        self.account_kind = value
        target = self.step + (3 if value == "influencer" else 1)
        self.step = min(target, CONNECT_LAST)

    @rx.event
    def answer_has_maps(self, value: str) -> None:
        """¿Tu negocio está en Google Maps?'s own choice handler. Unlike
        `answer_has_logo`, both answers stay in `BrandConnectState` itself — nothing
        here is a `CreativeState`/`BrandWizardState` kit field, there is no manual-flow
        counterpart to share it with. "Sí" has nothing further to say, so it skips
        straight past Súmate a Google Maps (`_MAPS_STEPS_STEP`); "no" shows it."""
        self.has_maps = value
        target = self.step + (2 if value == "si" else 1)
        self.step = min(target, CONNECT_LAST)

    def _reset_fields(self) -> None:
        """Every wizard-local field back to its default. Plain method, not `@rx.event`
        — both `restart` and `finish_to_signals` call it and then choose their own
        destination, so the reset itself lives in exactly one place."""
        self.step = 0
        self.network = ""
        self.username = ""
        self.error = ""
        self.profile_username = ""
        self.profile_fullname = ""
        self.profile_bio = ""
        self.profile_category = ""
        self.profile_followers = ""
        self.profile_followers_count = 0
        self.profile_pic = ""
        self.account_kind = ""
        self.has_maps = ""
        self._set_metrics([])

    @rx.event
    def restart(self) -> rx.event.EventSpec:
        """Cancelar on Lo que te proponemos — the flow's own last preview screen
        before the shared kit-setup steps begin (§ `_LAST_PREVIEW_STEP`). Drops
        everything read/entered and goes back to the fork."""
        self._reset_fields()
        return rx.redirect("/brand")

    @rx.event
    def finish_to_signals(self) -> rx.event.EventSpec:
        """Mejorar tu perfil y posicionamiento, on Resultados e insights — the TRUE
        final screen. Replaces Finalizar entirely (§ request 2026-09-05): same reset
        `restart` does, but the destination is Señales, not the fork — the same
        "regardless of the process" way `BrandWizardState.finish_to_signals` fires for
        the manual flow's own final screen."""
        self._reset_fields()
        return rx.redirect(_SIGNALS_ROUTE)

    @rx.event(background=True)
    async def advance_to_insights(self) -> AsyncIterator[None]:
        """Continuar from ¿Todo correcto? — the one caller that lands on Resultados e
        insights (`CONNECT_LAST`) from elsewhere, so it is also the one place that
        kicks off the metric count-up (§ `_METRIC_ANIMATION_SECONDS`): walks
        `metric_values` from 0 up to each `metric_targets` entry over
        `_METRIC_ANIMATION_SECONDS`, `_METRIC_ANIMATION_STEPS` frames. Background
        because there is no client-side animation primitive here — this is a real
        per-frame state update, same discipline `CreativeState.poll_draft` already
        uses for its own loop. With no metrics (`has_metrics` False) there is nothing
        to animate and the loop is skipped.
        """
        async with self:
            self.step = CONNECT_LAST
            targets = list(self.metric_targets)
            decimals = list(self.metric_decimals)
            self.metric_values = [0.0] * len(targets)
        yield
        if not targets:
            return
        frame_delay = _METRIC_ANIMATION_SECONDS / _METRIC_ANIMATION_STEPS
        for frame in range(1, _METRIC_ANIMATION_STEPS + 1):
            await asyncio.sleep(frame_delay)
            progress = frame / _METRIC_ANIMATION_STEPS
            async with self:
                self.metric_values = [
                    round(target * progress, d) for target, d in zip(targets, decimals)
                ]
            yield

    @rx.event(background=True)
    async def analyze(self) -> AsyncIterator[None]:
        """Read the profile behind a loading screen.

        Background plus an early `yield` so the spinner actually paints before the read
        starts; a foreground handler would block and the user would see nothing until it
        finished. The cache check, the live Scrape Creators call, and the snapshot file
        I/O all go through `asyncio.to_thread` — all blocking, and the event loop serves
        every other session.

        Checks the JSON snapshot FIRST (`load_cached_profile`): re-analyzing the same
        handle costs zero API credits, and only a genuinely new (network, handle) hits
        Scrape Creators. Not saved to a table on purpose
        (`scrapecreators_client`'s module docstring) — a fetched read is written to the
        one generic, overwritable JSON snapshot and then read BACK from that same
        file, same shape the earlier hardcoded fixture had, now backed by a real
        profile instead of a demo one.
        """
        async with self:
            if not self.username.strip():
                self.error = _USERNAME_REQUIRED
                return
            if self.network not in scrapecreators_client.SUPPORTED_NETWORKS:
                # Defensive: step 1 is only reachable via `choose_network`, which sets
                # `network` and `step` together — this should never fire from a normal
                # click. Seen in practice after a dev backend restart (session state
                # resets to defaults) while the client's own `step` survives the
                # reconnect, landing on the username screen with no network chosen.
                # Self-heal back to step 0 rather than surface Scrape Creators'
                # `unsupported network: ''` — an implementation detail, not something
                # the operator did wrong.
                self.step = 0
                self.error = ""
                return
            self.error = ""
            self.analyzing = True
            network, handle = self.network, self.username.strip()
        yield

        try:
            profile = await asyncio.to_thread(
                scrapecreators_client.load_cached_profile, network, handle
            )
            if profile is None:
                # Profile + the last `METRICS_WINDOW_DAYS` days of posts (two reads,
                # one normalized dict — the posts are what the metrics are computed on).
                profile = await asyncio.to_thread(
                    scrapecreators_client.fetch_profile_and_posts, network, handle
                )
                await asyncio.to_thread(
                    scrapecreators_client.save_profile_snapshot, network, handle, profile
                )
                profile = await asyncio.to_thread(scrapecreators_client.load_profile_snapshot)
        except (scrapecreators_client.ScrapeCreatorsError, ValueError, OSError) as exc:
            # The vendor detail (HTTP status, "insufficient credits", etc. — see
            # scrapecreators_client._error_detail) is diagnostic, not for the operator:
            # it stays in the server log. What reaches the screen is the one generic,
            # translated message every other provider-call failure in this flow uses.
            logger.warning("brand connect profile read failed: %s", exc)
            async with self:
                self.analyzing = False
                self.error = _PROFILE_UNAVAILABLE
            return

        followers = profile.get("followers")
        async with self:
            self.profile_username = str(profile.get("username", ""))
            self.profile_fullname = str(profile.get("fullName", ""))
            self.profile_bio = str(profile.get("bio", ""))
            self.profile_category = str(profile.get("category", ""))
            self.profile_followers = f"{followers:,}".replace(",", ".") if followers else "—"
            self.profile_followers_count = int(followers) if followers else 0
            self.profile_pic = str(profile.get("profilePicUrl", ""))
            # Real figures over the window (`recentPosts` of this same read).
            self._set_metrics(scrapecreators_client.profile_metrics(network, profile))
            self.analyzing = False
            self.step = 2


# ---------------------------------------------------------------------------
# The four screens specific to this flow


def _connect_step_network() -> rx.Component:
    """No step-level anchor icon here (unlike most other steps) — § request
    2026-09-09 gave each option its OWN icon instead (`_choice_card`'s `icon=`), so a
    second generic "share-2" above both would be a redundant third icon on a screen
    that already reads Instagram vs. TikTok apart at a glance."""
    return _step_body(
        *(
            _choice_card(
                label,
                blurb,
                BrandConnectState.network == key,
                BrandConnectState.choose_network(key),
                icon=icon,
            )
            for key, label, blurb, icon in NETWORKS
        ),
    )


def _connect_network_icon() -> rx.Var[str]:
    """The chosen network's own icon (§ request 2026-09-09 — this, not ¿Qué red
    usas? itself, is the "al momento de seleccionar la red social para hacer el
    scraper" screen the request meant: choosing a network already got a per-option
    icon on its OWN step; this is the icon on the step right after, while `network`
    is still live). Same `NETWORKS` lookup `_connect_step_network` builds its cards
    from, so the two screens can never show a different icon for the same network.
    Falls back to the generic "at-sign" before a network is set — should not
    happen in practice (this step is only reachable via `choose_network`, which
    sets `network` and `step` together)."""
    return rx.match(
        BrandConnectState.network,
        *((key, icon) for key, _, _, icon in NETWORKS),
        "at-sign",
    )


def _connect_step_username() -> rx.Component:
    """Wrapped in `rx.form` (same reasoning as `_logo_brief_form`, `_hidden_submit`
    included) so Enter in the single Usuario field triggers `BrandConnectState.
    analyze` — the same handler `_connect_controls`'s "Analizar" button already calls
    on this step, not a plain `next_step` (this step never just advances; it kicks
    off the profile read)."""
    return rx.form(
        _step_body(
            _labeled_input(
                "Usuario",
                BrandConnectState.username,
                BrandConnectState.set_username,
                "username",
            ),
            rx.cond(
                BrandConnectState.error != "",
                callout(BrandConnectState.error, "error"),
            ),
            icon=_connect_network_icon(),
        ),
        _hidden_submit(),
        on_submit=BrandConnectState.analyze,
        width="100%",
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
                # §8: h3 for an entity title inside a card — `page_header` already
                # owns this page's one h1.
                rx.heading(BrandConnectState.profile_username, size="4", as_="h3"),
                rx.text(BrandConnectState.profile_fullname, size="2", color=T.TEXT_MUTED),
                rx.cond(
                    BrandConnectState.profile_category != "",
                    tag(BrandConnectState.profile_category),
                ),
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
            rx.icon("sparkles", size=18, color=T.tone_color("accent", 10)),
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
    return _step_body(
        icon="lightbulb",
        *(_recommendation_card(title, blurb) for title, blurb in RECOMMENDATIONS),
    )


def _connect_step_has_logo() -> rx.Component:
    """Same question and copy as the manual flow's `_step_has_logo`, only shown when
    the scraped profile came back with no picture (§ `next_step`'s skip). Cannot
    reuse `_step_has_logo` as-is: its choice cards call `BrandWizardState.
    answer_has_logo`, which advances `BrandWizardState.step` — a cursor this flow
    never reads. `BrandConnectState.answer_has_logo` writes the same `has_logo`
    field but advances the right cursor."""
    return _step_body(
        _choice_card(
            "Sí, ya tengo uno",
            "Súbelo en el siguiente paso y lo usaremos tal cual.",
            BrandWizardState.has_logo == "si",
            BrandConnectState.answer_has_logo("si"),
        ),
        _choice_card(
            "No, todavía no",
            "Te haremos tres preguntas para proponerte uno.",
            BrandWizardState.has_logo == "no",
            BrandConnectState.answer_has_logo("no"),
        ),
        icon="image",
    )


def _connect_step_account_kind() -> rx.Component:
    """¿Eres influencer o una marca?. Always shown, self-reported, lives entirely in
    `BrandConnectState` — same reasoning `_connect_step_has_maps` below already
    documents for `has_maps` (not a `brand_kits` field, no manual-flow counterpart).
    Gates the Google Maps pair right after it: "marca" continues into
    `_connect_step_has_maps` normally, "influencer" skips both Maps steps
    outright (`answer_account_kind`) — a creator has no local business to list."""
    return _step_body(
        _choice_card(
            "Soy una marca o negocio",
            "Te preguntaremos si ya apareces en Google Maps.",
            BrandConnectState.account_kind == "marca",
            BrandConnectState.answer_account_kind("marca"),
        ),
        _choice_card(
            "Soy creador o influencer",
            "Saltamos directo a la paleta de colores.",
            BrandConnectState.account_kind == "influencer",
            BrandConnectState.answer_account_kind("influencer"),
        ),
        icon="user-round",
    )


def _connect_step_has_maps() -> rx.Component:
    """¿Tu negocio está en Google Maps?. Only reached when ¿Eres influencer o una
    marca? was answered "marca" (an influencer skips straight past this pair — see
    `answer_account_kind`); within that, always shown (no scraped signal exists to
    skip it like the logo question does), and self-reported: "sí" trusts the answer
    and moves straight to Paleta; "no" shows `_connect_step_maps_setup` first. Lives
    entirely in `BrandConnectState` — unlike `has_logo`, this isn't a `brand_kits`
    field either flow persists, so there is no manual-flow counterpart to keep in
    sync with."""
    return _step_body(
        _choice_card(
            "Sí, ya está",
            "Perfecto, seguimos con el siguiente paso.",
            BrandConnectState.has_maps == "si",
            BrandConnectState.answer_has_maps("si"),
        ),
        _choice_card(
            "No, todavía no",
            "Te mostramos cómo sumarla en unos minutos.",
            BrandConnectState.has_maps == "no",
            BrandConnectState.answer_has_maps("no"),
        ),
        icon="map-pin",
    )


#: Real steps for creating a Google Business Profile — not lorem, same rule
#: `ACCOUNT_SETUP_INFO`/`PLANS` follow: a first-time user reads this as the actual
#: instructions. No product-side verification exists for any of this (§
#: `BrandConnectState.has_maps`'s own docstring) — it is a checklist, not a gate.
MAPS_SETUP_STEPS: tuple[tuple[str, str], ...] = (
    (
        "Crea tu Perfil de Negocio",
        'Entra a business.google.com con tu cuenta de Google y elige "Administrar ahora".',
    ),
    (
        "Ingresa los datos de tu negocio",
        "Nombre, categoría y la dirección exacta donde atiendes.",
    ),
    (
        "Verifica la ubicación",
        "Google te ofrece verificar por correo, teléfono o videollamada, según tu negocio.",
    ),
    (
        "Espera la aprobación",
        "Una vez verificado, apareces en Google Maps y en la Búsqueda de Google.",
    ),
)


def _maps_setup_row(index: int, title: str, blurb: str) -> rx.Component:
    """A numbered row — same "circle + text" language `_step_icon` already uses for
    a single anchor icon, here repeated once per step so the sequence reads as an
    ordered checklist rather than a flat list."""
    return rx.hstack(
        rx.box(
            rx.text(str(index), size="2", weight="bold", color=T.tone_color("accent", 11)),
            width="1.75rem",
            height="1.75rem",
            min_width="1.75rem",
            border_radius="9999px",
            background=T.tone_color("accent", 3),
            display="flex",
            align_items="center",
            justify_content="center",
        ),
        rx.vstack(
            rx.text(title, size="2", weight="bold"),
            rx.text(blurb, size="2", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
        ),
        spacing="3",
        align="start",
        width="100%",
    )


def _connect_step_maps_setup() -> rx.Component:
    """Súmate a Google Maps — only reached on a "No" answer to ¿Tu negocio está en
    Google Maps? (`answer_has_maps`). Purely instructional, same as
    `brand_connect_setup_index`: Continuar (the generic `next_step`, wired in
    `_connect_controls`) moves on to Paleta once read — nothing here is verified,
    the question itself is already self-reported."""
    return _step_body(
        card(
            rx.vstack(
                *(
                    _maps_setup_row(i, title, blurb)
                    for i, (title, blurb) in enumerate(MAPS_SETUP_STEPS, start=1)
                ),
                spacing="4",
                width="100%",
            ),
            padding="1.25rem 1.5rem",
            width="100%",
        ),
        rx.link(
            rx.hstack(
                rx.text("Crear Perfil de Negocio en Google", size="2", weight="medium"),
                rx.icon("external-link", size=T.ICON_SM),
                spacing="1",
                align="center",
            ),
            href="https://business.google.com/",
            target="_blank",
            rel="noopener noreferrer",
            color=T.tone_color("accent", 11),
        ),
        icon="map-pin",
    )


def _metric_card(item: rx.Var[dict[str, str]]) -> rx.Component:
    return stat_card(item["label"], item["value"], hint=item["hint"])


def _metric_grid() -> rx.Component:
    """One `stat_card` per entry of `BrandConnectState.metric_cards` — real figures,
    already formatted server-side (see that computed var). Up to three; the column
    count stays 3 so a two-metric profile leaves a gap rather than stretching."""
    return rx.grid(
        rx.foreach(BrandConnectState.metric_cards, _metric_card),
        columns=rx.breakpoints(initial="1", sm="3"),
        spacing="3",
        width="100%",
    )


def _connect_step_insights() -> rx.Component:
    """The TRUE final screen of the whole flow (§ CONNECT_STEPS, `CONNECT_LAST`) —
    after ¿Todo correcto?, not before it: a condensed profile recap, the animated
    metric grid (`_metric_grid`, counted up by `advance_to_insights` on the way in),
    and 1-2 placeholder competitor/influencer suggestions (`_competitors_section`,
    shared with the manual flow's own final screen). Its own Finalizar-replacing CTA
    (`_finish_button`) lives in `_connect_controls`, not here — the fixed control bar,
    not the scrolling content, is what both flows' final screen shares that button
    through.

    The metrics are REAL (2026-09-10) and cover the last
    `scrapecreators_client.METRICS_WINDOW_DAYS` days: derived by `profile_metrics`
    from the post list `analyze()` read alongside the profile — see the comment
    above `_METRIC_ANIMATION_SECONDS`.
    The competitor suggestions below them are still a PLACEHOLDER: no analytical
    pipeline backs them yet (Fase 2/3, `docs/plan-ingesta-social.md`) —
    `COMPETITOR_SUGGESTIONS` is a hardcoded tuple, not a query.

    The metric grid is skipped outright for a brand-new account (§ request
    2026-09-09, `BrandConnectState.is_new_account`) — a per-follower rate over a
    handful of followers is noise, not a measurement — and whenever the read yielded
    no computable metric at all (`has_metrics`). Same "nothing to report a rate FOR"
    principle the manual flow's `_step_insights` already follows by never showing
    metrics at all (it has no scraped account, new or old).
    """
    return _step_body(
        card(
            rx.hstack(
                rx.cond(
                    BrandConnectState.profile_pic != "",
                    rx.image(
                        src=BrandConnectState.profile_pic,
                        alt="Foto de perfil",
                        width="3rem",
                        height="3rem",
                        border_radius="9999px",
                        object_fit="cover",
                        flex_shrink="0",
                    ),
                    rx.box(
                        rx.icon("user", size=18, color=T.TEXT_FAINT),
                        width="3rem",
                        height="3rem",
                        border_radius="9999px",
                        background=T.SURFACE_BG_RAISED,
                        display="flex",
                        align_items="center",
                        justify_content="center",
                        flex_shrink="0",
                    ),
                ),
                rx.vstack(
                    rx.text(BrandConnectState.profile_username, size="3", weight="bold"),
                    rx.text(
                        BrandConnectState.profile_followers,
                        " seguidores",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="0",
                    align_items="start",
                    min_width="0",
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            padding="1rem 1.25rem",
            width="100%",
        ),
        rx.cond(
            ~BrandConnectState.is_new_account & BrandConnectState.has_metrics,
            rx.vstack(
                _section_label(
                    f"Métricas · últimos {scrapecreators_client.METRICS_WINDOW_DAYS} días"
                ),
                _metric_grid(),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        _competitors_section(),
    )


def _connect_window() -> rx.Component:
    """Screens 0-3 and CONNECT_LAST (Resultados e insights, the true final screen —
    moved 2026-09-04 to sit AFTER ¿Todo correcto?) are this flow's own; steps 6-7
    (¿Tienes logo?/Tu logo) are skipped whenever the scraped profile already has a
    picture, and steps 9-10 (¿Tu negocio está en Google Maps?/Súmate a Google Maps)
    are skipped together on "influencer" at step 8, or step 10 alone on a "sí"
    answer at step 9 (§ request 2026-09-09) — all still need a renderer for the
    sessions where they are shown. Everything else in between reuses the manual
    flow's renderers, so the shared half of the two paths is literally the same
    code."""
    return rx.match(
        BrandConnectState.step,
        (0, _connect_step_network()),
        (1, _connect_step_username()),
        (2, _connect_step_profile()),
        (3, _connect_step_recommendations()),
        (4, _step_subscription()),
        (5, _step_identity()),
        (_LOGO_QUESTION_STEP, _connect_step_has_logo()),
        (_LOGO_UPLOAD_STEP, _step_logo(BrandConnectState.next_step)),
        (_ACCOUNT_KIND_STEP, _connect_step_account_kind()),
        (_MAPS_QUESTION_STEP, _connect_step_has_maps()),
        (_MAPS_STEPS_STEP, _connect_step_maps_setup()),
        (11, _step_palette()),
        (12, _step_voice_tone()),
        (13, _step_voice_examples()),
        (14, _step_restrictions()),
        (15, _step_confirm()),
        (CONNECT_LAST, _connect_step_insights()),
        _connect_step_network(),
    )


def _connect_heading_for(index: int) -> rx.Var[str]:
    return rx.match(
        BrandConnectState.step,
        *((position, text[index]) for position, text in enumerate(CONNECT_STEPS)),
        CONNECT_STEPS[0][index],
    )


def _connect_loading() -> rx.Component:
    return _loading_view("Analizando perfil", "Esto tarda solo unos segundos.")


def _identity_complete() -> rx.Var[bool]:
    """¿Quién es la marca? needs BOTH fields, not just one — same pair
    `BrandWizardState.resume` already treats as one completeness checkpoint
    (`not creative.kit_positioning.strip() or not creative.kit_audience.strip()`).
    Shared by `_connect_can_continue` and `_manual_can_continue`: this step is the
    same `_step_identity` renderer and the same `CreativeState` fields either way."""
    return rx.cond(
        CreativeState.kit_positioning != "",
        CreativeState.kit_audience != "",
        False,
    )


def _logo_step_complete() -> rx.Var[bool]:
    """Tu logo needs an uploaded file on "sí" but only the FIRST of the three brief
    questions on "no" — the one field `BrandWizardState.resume` itself already
    treats as the completeness signal for this step
    (`self.has_logo == "no" and not self.logo_brief_1.strip()`). Shared by both
    flows' gate for the same reason `_identity_complete` is."""
    return rx.cond(
        BrandWizardState.has_logo == "si",
        BrandWizardState.logo_key != "",
        BrandWizardState.logo_brief_1 != "",
    )


def _connect_can_continue() -> rx.Var[bool]:
    """Whether the CURRENT step's requirement is satisfied (§ request 2026-09-09) —
    gates `_connect_controls`'s forward button (Analizar/Continuar) so a choice step
    can't be skipped unanswered and a required-input step can't be skipped empty.

    Every step not named below has nothing to require and always returns True:
    Esto es lo que vemos / Lo que te proponemos (read-only recaps), Súmate a Google
    Maps (informational, nothing to fill in), ¿Cómo suena? (the tone sliders always
    hold a value — they default to 50, see the manual flow's own `resume` docstring),
    Lo que nunca debe decir (`resume`'s docstring: "legitimately optional"), ¿Todo
    correcto? (review only) and Resultados e insights (its own `_finish_button`, not
    this gate, on step CONNECT_LAST). Shared steps (plan, identidad, logo, paleta,
    voz · ejemplos) read the SAME `BrandWizardState`/`CreativeState` fields the
    manual flow's own `_manual_can_continue` checks — the two functions stay
    side by side with it so a future reorder of either STEPS tuple is easy to keep
    in sync."""
    return rx.match(
        BrandConnectState.step,
        (0, BrandConnectState.network != ""),
        (1, BrandConnectState.username != ""),
        (4, BrandWizardState.subscription != ""),
        (5, _identity_complete()),
        (_LOGO_QUESTION_STEP, BrandWizardState.has_logo != ""),
        (_LOGO_UPLOAD_STEP, _logo_step_complete()),
        (_ACCOUNT_KIND_STEP, BrandConnectState.account_kind != ""),
        (_MAPS_QUESTION_STEP, BrandConnectState.has_maps != ""),
        (11, CreativeState.kit_palette != ""),
        (13, CreativeState.kit_do_examples != ""),
        True,
    )


def _connect_controls() -> rx.Component:
    """Same quiet chrome as the manual flow, with three exceptions: the username
    screen's Continue kicks off the analysis instead of stepping; Lo que te
    proponemos — the last screen before the shared kit-setup steps begin (§
    `_LAST_PREVIEW_STEP`) — offers Cancel rather than Back; and ¿Todo correcto?'s
    Continue kicks off the metric count-up (`advance_to_insights`) instead of a plain
    step. `right`'s Resultados e insights branch is `_finish_button` — it replaces
    Finalizar entirely (§ request 2026-09-05), not alongside it. `back` is never
    disabled: `prev_step` redirects to `/brand` once already at step 0.

    Every forward button (Analizar/Continuar, not `_finish_button` — Confirmación
    already passed this gate) carries `disabled=~_connect_can_continue()` (§ request
    2026-09-09): a choice step with nothing selected, or a required field left
    empty, no longer lets Continuar through un-set."""
    forward_disabled = ~_connect_can_continue()
    left = rx.cond(
        BrandConnectState.step == _LAST_PREVIEW_STEP,
        rx.button(
            "Cancelar",
            # §5.5: destructive is `soft` + the error tone, not `ghost` + a literal
            # color name — matches "Quitar" on the logo step.
            variant="soft",
            color_scheme=T.tone_scale("error"),
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
        _finish_button([CreativeState.save_kit_form, BrandConnectState.finish_to_signals]),
        rx.cond(
            BrandConnectState.step == 1,
            rx.button(
                "Analizar",
                rx.icon("chevron-right", size=T.ICON_SM),
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandConnectState.analyze,
                disabled=forward_disabled,
            ),
            rx.cond(
                BrandConnectState.step == CONNECT_LAST - 1,
                rx.button(
                    "Continuar",
                    rx.icon("chevron-right", size=T.ICON_SM),
                    size="2",
                    radius=_CONTROL_RADIUS,
                    on_click=BrandConnectState.advance_to_insights,
                    disabled=forward_disabled,
                ),
                rx.button(
                    "Continuar",
                    rx.icon("chevron-right", size=T.ICON_SM),
                    size="2",
                    radius=_CONTROL_RADIUS,
                    on_click=BrandConnectState.next_step,
                    disabled=forward_disabled,
                ),
            ),
        ),
    )
    return rx.hstack(left, rx.spacer(), right, width="100%", align="center", spacing="3")


def brand_connect_index() -> rx.Component:
    """Same shape as `brand_manual_index`, `page_header` included (§ `_step_counter`'s
    docstring): full-width header outside `page_body`, full-width border filling down
    to the panel's bottom, fields in a narrow centred column at the top of the card,
    and `_connect_controls()` spanning the card's full width, pinned to its bottom
    corners. Two loading states, both a centred spinner with no footer row:
    `CreativeState.kit_loading` on page load, `BrandConnectState.analyzing` mid-scrape."""
    return app_shell(
        page_header(
            _connect_heading_for(0),
            _connect_heading_for(1),
            kicker=_step_counter(BrandConnectState.step, len(CONNECT_STEPS)),
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
                            # Same mobile fix as `brand_manual_index`'s card — `gap`
                            # floors the distance to Atrás/Continuar so it cannot
                            # collapse to ~0 on a short viewport once the step's content
                            # fills the free height (Perfil, Lo que te proponemos,
                            # Resultados e insights, and the shared steps 5-11).
                            gap="1.5rem",
                            # `key` on the CARD itself, not just its content — same fix
                            # `brand_manual_index` gets: keying only the inner vstack
                            # left the card's own border/shadow node reused across
                            # steps, so the frame never moved, only the text inside it
                            # did. Keying the whole `card()` remounts it too, which is
                            # what makes `page_body`'s own "q-settle" (the card is one
                            # of its direct children) replay on every step change.
                            key=BrandConnectState.step.to_string(),
                        ),
                    ),
                ),
                spacing="4",
                width="100%",
                flex="1",
                min_height="0",
            ),
        ),
    )
