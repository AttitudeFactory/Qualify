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

    1 Identidad        2 ¿Tienes logo?  3 Logo (branches on 2)  4 Paleta
    5 Voz · tono       6 Voz · ejemplos 7 Restricciones         8 Confirmación
    9 Resultados

"Elige tu plan" was removed from BOTH flows on 2026-09-11 (§ request: "quitemos la
view de Elige tu plan, independientemente si tenga o no redes") — the plan tiers were
placeholder copy with no column behind them, so nothing persisted is lost.

NOT YET PERSISTED — several fields here edit state `save_kit_form` does not carry, so
they survive navigation between steps but not a reload:
  - the logo-creation brief: placeholder copy, no columns at all.
  - the connect flow's account kind, rubro and location (`BrandConnectState`).
  - the staged logo: `brand_kits.logo_asset_key` DOES exist and `creative_provider.
    save_kit` deliberately preserves whatever is stored (so nothing is lost by saving
    here), but no path writes a NEW key. Wiring it means R2 upload + a `logo_asset_key`
    on `KitFormVM`.
Left as a follow-up rather than widening `CreativeState` from this module.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.hashtags import fold, normalize_tag
from reflex.constants import Dirs
from reflex.utils.imports import ImportVar
from reflex.vars import VarData
from sqlalchemy.exc import SQLAlchemyError

from . import (
    avatar_proxy,
    brand_documents,
    creator_discovery,
    hashtag_catalog,
    logo_palette,
    referentes_provider,
    scrapecreators_client,
)
from .auth_state import AuthState
from .connections_provider import acting_user_id
from .creative_provider import default_brand_id
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

#: Fire-and-forget work started by a state handler (the AI classification of the hashtag
#: catalog). Held here so the event loop keeps a strong reference until it finishes.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _finish_background_task(task: asyncio.Task) -> None:
    _BACKGROUND_TASKS.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("background task failed: %s", task.exception())


_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_UPLOAD_FAILED = "No se pudo leer el archivo. Inténtalo de nuevo."

# Title + one-line subtitle per step. The index IS the cursor value, so this tuple is
# the single source of truth for the counter and the heading.
STEPS: tuple[tuple[str, str], ...] = (
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

#: Where a logo's colours came from (`BrandWizardState.logo_source`). GENERATED is
#: reserved for the logo generator the brief ("No, todavía no") will feed — it does not
#: exist yet; when it does it hands its image to `apply_logo_colours` with this source.
LOGO_SOURCE_UPLOAD = "upload"
LOGO_SOURCE_PROFILE = "profile"
LOGO_SOURCE_GENERATED = "generated"

#: ¿Tienes logo?'s third answer in the connect flow (§ request 2026-09-16): the scraped
#: profile picture IS the logo. Alongside "si" (upload one) and "no" (the brief).
HAS_LOGO_PROFILE = "perfil"

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


class BrandWizardState(rx.State):
    """The cursor, plus the fields this screen adds that `CreativeState` has no home for.

    Existing kit fields stay in `CreativeState` — a wizard is a navigation concern, not
    a second copy of the record. What lives here is only what is genuinely new.

    Setters are explicit: this Reflex version generates none, the same reason
    `CreativeState` writes its own.
    """

    step: int = 0

    # -- step 2/3 -------------------------------------------------------------
    has_logo: str = ""  # "si" | "no" | "" (unanswered)
    logo_brief_1: str = ""
    logo_brief_2: str = ""
    logo_brief_3: str = ""

    # -- staged logo file -----------------------------------------------------
    logo_key: str = ""
    logo_name: str = ""
    logo_error: str = ""
    #: The colours the staged logo put into the palette (`logo_palette.
    #: extract_palette`), so replacing or removing the logo takes exactly those back
    #: out and never a colour picked by hand.
    logo_colors: list[str] = []
    #: Where `logo_colors` came from — one of the `LOGO_SOURCE_*` constants, "" when
    #: nothing contributed any. Drives the palette step's note ("de tu logo" / "de tu
    #: foto de perfil") and lets choosing another logo source retire them.
    logo_source: str = ""

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
        if not creative.kit_positioning.strip() or not creative.kit_audience.strip():
            self.step = 0
        elif not self.has_logo:
            self.step = 1
        elif self.has_logo == "si" and not self.logo_key:
            self.step = 2
        elif self.has_logo == "no" and not self.logo_brief_1.strip():
            self.step = 2
        elif not creative.kit_palette.strip():
            self.step = 3
        elif not creative.kit_do_examples.strip():
            self.step = 5
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
        self.has_logo = ""
        self.logo_brief_1 = ""
        self.logo_brief_2 = ""
        self.logo_brief_3 = ""
        self.logo_key = ""
        self.logo_name = ""
        self.logo_error = ""
        self.logo_colors = []
        self.logo_source = ""
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
    def answer_has_logo(self, value: str) -> None:
        """Answering step 2 moves straight on — the question has no other content, so
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
        await self.apply_logo_colours(data, LOGO_SOURCE_UPLOAD)

    async def apply_logo_colours(self, data: bytes, source: str) -> None:
        """THE one way a logo's colours reach the palette (§ request 2026-09-16), for
        every source: an uploaded file, the scraped profile picture and — once it
        exists — a generated logo. Replaces whatever colours a previous logo put there
        and never touches a hand-picked one (`logo_palette.merge_into_palette`).
        Extraction runs off the event loop: decoding a large export is CPU work. A
        format Pillow cannot read (SVG) contributes no colours, and retires the
        previous ones all the same — that logo is no longer the logo.

        Not an event handler: callers are handlers already running in an event context
        (it needs `get_state`), including `BrandConnectState.answer_has_logo` through
        `get_state(BrandWizardState)`."""
        colours = await asyncio.to_thread(logo_palette.extract_palette, data)
        creative = await self.get_state(CreativeState)
        creative.kit_palette = logo_palette.merge_into_palette(
            creative.kit_palette, self.logo_colors, colours
        )
        self.logo_colors = colours
        self.logo_source = source if colours else ""

    async def retire_logo_colours(self) -> None:
        """Take the current logo's colours back out of the palette (hand-picked stay)."""
        if self.logo_colors:
            creative = await self.get_state(CreativeState)
            creative.kit_palette = logo_palette.merge_into_palette(
                creative.kit_palette, self.logo_colors, []
            )
        self.logo_colors = []
        self.logo_source = ""

    @rx.event
    async def clear_logo(self) -> None:
        """Drop the staged logo, and the palette colours it contributed (hand-picked
        ones stay). The file on disk is left alone — it is namespaced and unreferenced,
        and deleting it here would race a preview still being fetched."""
        self.logo_key = ""
        self.logo_name = ""
        self.logo_error = ""
        if self.logo_source == LOGO_SOURCE_UPLOAD:
            await self.retire_logo_colours()

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


def _step_body(
    *children: rx.Component, icon: str | rx.Var[str] | None = None, grow: bool = False
) -> rx.Component:
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
        # `grow` (the deck): take the card's whole height so a child with `flex="1"`
        # can stretch to it — every other step keeps its natural height, centred.
        **({"flex": "1", "align_self": "stretch"} if grow else {}),
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


def _step_identity() -> rx.Component:
    """¿Quién es la marca?, in both flows. Opens with the brief upload (§ request
    2026-09-25, `brand_documents.brief_upload_card`): a brief read by Claude proposes
    values for this step AND the later ones (tone, examples, restrictions, palette), and
    whatever the operator applies is already in place when they get there."""
    return _step_body(
        brand_documents.brief_upload_card(),
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
    input, unlike placeholder copy elsewhere in this module (the plan tiers, removed
    2026-09-11, were the last of it). Slightly taller inputs than
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
        rx.vstack(
            _logo_upload_field(),
            brand_documents.brandboard_upload_field(),
            spacing="4",
            width="100%",
        ),
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
                # § request 2026-09-16: say where the colours came from when the logo
                # step put them there, so a palette the operator never picked does not
                # read as a bug.
                rx.cond(
                    BrandWizardState.logo_colors.length() > 0,
                    rx.hstack(
                        rx.icon("sparkles", size=T.ICON_SM, color=T.TEXT_MUTED),
                        rx.text(
                            rx.cond(
                                BrandWizardState.logo_source == LOGO_SOURCE_PROFILE,
                                "Tomamos estos colores de tu foto de perfil. ",
                                "Tomamos estos colores de tu logo. ",
                            ),
                            "Cámbialos o quítalos si no te convencen.",
                            size="1",
                            color=T.TEXT_MUTED,
                        ),
                        spacing="2",
                        align="center",
                    ),
                ),
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
    """One step at a time. `rx.match` on the cursor, with step 0 as the fallback so an
    out-of-range cursor still renders a form instead of a blank screen."""
    return rx.match(
        BrandWizardState.step,
        (0, _step_identity()),
        (1, _step_has_logo()),
        (2, _step_logo(BrandWizardState.next_step)),
        (3, _step_palette()),
        (4, _step_voice_tone()),
        (5, _step_voice_examples()),
        (6, _step_restrictions()),
        (7, _step_confirm()),
        (8, _step_insights()),
        _step_identity(),
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
        (0, _identity_complete()),
        (1, BrandWizardState.has_logo != ""),
        (2, _logo_step_complete()),
        (3, CreativeState.kit_palette != ""),
        (5, CreativeState.kit_do_examples != ""),
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
            _finish_button(
                [
                    CreativeState.save_kit_form,
                    brand_documents.BrandDocumentState.reset_documents,
                    BrandWizardState.finish_to_signals,
                ]
            ),
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
#: rule `RECOMMENDATIONS` follows: a first-time user reads this as the actual
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
                            # Flags the walk as a fresh start (§ `is_fresh_start`) on
                            # its way to the same `/brand/connect` door "Sí" uses.
                            on_click=BrandConnectState.start_without_socials,
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
# Steps 6, 11-15 are the SAME renderers the manual flow uses, so the two paths
# cannot drift. Specific to this flow: 0-3 (network, username, profile,
# recommendations), 4-5 (¿Eres influencer o una marca? / Tu rubro y ubicación), 7-8
# (¿Tienes logo?/Tu logo, own `_connect_step_has_logo` because the choice needs to
# advance THIS flow's cursor), 9-10 (the Google Maps pair) and CONNECT_LAST,
# Resultados e insights — which now carries the phased creator discovery.
#
# Which steps a session actually SEES is decided in one place,
# `BrandConnectState._is_skipped` (2026-09-11) — every forward and backward move walks
# over the skipped ones, so a skip can never be honoured going forward and forgotten
# going back.

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
    # Lo que te proponemos — SKIPPED for a fresh start (§ request 2026-09-11: "quitemos
    # la view de Lo que te proponemos, solo cuando no tenga redes"). See `is_fresh_start`.
    ("Lo que te proponemos", "Podrás ajustarlo todo después."),
    # "Elige tu plan" sat here until 2026-09-11 — removed from both flows.
    #
    # ¿Eres influencer o una marca? now comes BEFORE ¿Quién es la marca? (§ request
    # 2026-09-11, "invertir" the two). It still gates the Google Maps pair: an
    # influencer has no local business to list.
    ("¿Eres influencer o una marca?", "Así te mostramos los pasos que sí aplican para ti."),
    # Tu rubro y ubicación (2026-09-11) — the input the creator discovery on
    # Resultados e insights needs. Always shown for a fresh start (no content to read
    # it from); for an existing account only when the profile read could not detect
    # what the discovery needs (`needs_rubro_step`).
    ("Tu rubro y ubicación", "Así buscamos referentes de tu sector, tu país y tu ciudad."),
    # ¿Estás en Google Maps? / Súmate a Google Maps — swapped with ¿Quién es la marca?
    # (§ request 2026-09-15, "intercambiar las views"): the pair now runs right after
    # Tu rubro y ubicación and ¿Quién es la marca? takes the slot they used to close.
    # SKIPPED as a pair for "influencer"; for "marca"/"ambas" the question is always
    # asked and only the follow-up screen is conditional, on the answer ("no").
    ("¿Tu negocio está en Google Maps?", "Así te encuentran cuando buscan cerca."),
    ("Súmate a Google Maps", "Son unos minutos y quedas visible en el mapa."),
    ("¿Quién es la marca?", "Lo que define su lugar y a quién le habla."),
    # ¿Tienes logo? / Tu logo — ALWAYS shown, right before Paleta de colores (§ request
    # 2026-09-16). They used to be skipped whenever the scraped profile had a picture,
    # which is nearly every account, so uploading a logo or asking for one through the
    # brief was unreachable. A profile picture is not a logo. An uploaded logo's colours
    # seed the palette on the next screen (`handle_logo_upload`). Same copy + renderers
    # the manual flow uses (`_step_has_logo`/`_step_logo`) via `_connect_step_has_logo`,
    # so the two flows cannot drift.
    ("¿Tienes logo?", "De tu respuesta depende el siguiente paso."),
    ("Tu logo", "Lo usaremos en cada pieza que generemos."),
    ("Paleta de colores", "Los colores con los que se te reconoce."),
    ("¿Cómo suena?", "Ajusta el tono en cuatro ejes."),
    ("Enséñale a hablar", "Ejemplos reales valen más que cualquier descripción."),
    ("Lo que nunca debe decir", "Reglas duras: una violación es un rechazo."),
    ("¿Todo correcto?", "Revisa antes de guardar."),
    # Referente, competencia o detractor (§ request 2026-09-11, "algo divertido antes
    # del resultado"): the accounts the discovery found, sorted by the operator into
    # three buckets by drag and drop or a tap. Optional — nothing blocks Continuar.
    ("Referente, competencia o detractor", "Arrastra cada cuenta a su flecha, o toca la flecha."),
    ("Resultados e insights", "Cómo se ve tu cuenta hoy."),
)
CONNECT_LAST = len(CONNECT_STEPS) - 1
_SORT_STEP = CONNECT_LAST - 1
_CONNECT_CONFIRM_STEP = CONNECT_LAST - 2

#: Named indices into `CONNECT_STEPS` — every skip, gate and renderer refers to these,
#: never to a literal, so the next reorder of the tuple is a one-place change.
_PROFILE_STEP = 2
_RECOMMENDATIONS_STEP = 3
_ACCOUNT_KIND_STEP = 4
_RUBRO_STEP = 5
_MAPS_QUESTION_STEP = 6
_MAPS_STEPS_STEP = 7
_IDENTITY_STEP = 8
_LOGO_QUESTION_STEP = 9
_LOGO_UPLOAD_STEP = 10
_PALETTE_STEP = 11
_VOICE_TONE_STEP = 12
_VOICE_EXAMPLES_STEP = 13
_RESTRICTIONS_STEP = 14
assert CONNECT_STEPS[_RUBRO_STEP][0] == "Tu rubro y ubicación"
assert CONNECT_STEPS[_MAPS_QUESTION_STEP][0] == "¿Tu negocio está en Google Maps?"
assert CONNECT_STEPS[_MAPS_STEPS_STEP][0] == "Súmate a Google Maps"
assert CONNECT_STEPS[_IDENTITY_STEP][0] == "¿Quién es la marca?"
assert CONNECT_STEPS[_LOGO_QUESTION_STEP][0] == "¿Tienes logo?"
assert CONNECT_STEPS[_LOGO_UPLOAD_STEP][0] == "Tu logo"
assert CONNECT_STEPS[_PALETTE_STEP][0] == "Paleta de colores"
assert _LOGO_UPLOAD_STEP + 1 == _PALETTE_STEP
assert CONNECT_STEPS[_RESTRICTIONS_STEP + 1][0] == "¿Todo correcto?"
assert CONNECT_STEPS[_SORT_STEP][0] == "Referente, competencia o detractor"

#: The three buckets of the sort step — (key, title, blurb, icon).
BUCKETS: tuple[tuple[str, str, str, str], ...] = (
    ("referente", "Referentes", "Te inspiran, te gustaría parecerte.", "star"),
    ("competencia", "Competencia", "Le hablan a tu misma audiencia.", "swords"),
    ("detractor", "Detractores", "No van con tu marca.", "thumbs-down"),
)
#: Where each bucket sits around the deck — the way the ghost card flies.
_FLY_DIRECTION = {"referente": "left", "competencia": "right", "detractor": "down"}
#: How long `advance_stage_if_exhausted` waits before moving the deck on, so the
#: just-played decision animation (hit-flash ≤0.6s, fly-ghost/drag-release ≤0.5s)
#: finishes reading first (§ request 2026-09-14).
_STAGE_ADVANCE_DELAY = 0.65


class _DropZone(rx.el.Button):
    """A panel the deck's card can be dropped on. Reflex's HTML elements declare no
    `on_drop` trigger of their own, so it is added here. The event is not the
    browser's HTML5 drop any more: `assets/deck-drag.js` drives the card with pointer
    events and, on a release over a panel, dispatches a synthetic `drop` on it —
    React's `onDrop` catches it either way. A real button, not a `div` (§8): the
    panel IS the tap alternative to dragging (the row of buttons under the card is
    gone), so it has to be reachable by keyboard and named to a screen reader."""

    on_drop: rx.EventHandler[rx.event.no_args_event_spec]


#: ¿Eres influencer o una marca?'s options — (key, title, blurb). "ambas" (§ request
#: 2026-09-11, "influencer y/o marca") behaves as a brand for every gate: it has a
#: business to list on Maps and a location the discovery should use.
ACCOUNT_KINDS: tuple[tuple[str, str, str], ...] = (
    ("marca", "Soy una marca o negocio", "Te preguntaremos tu rubro y dónde estás."),
    ("influencer", "Soy creador o influencer", "Buscaremos referentes de tu temática."),
    ("ambas", "Las dos cosas", "Creas contenido y además tienes un negocio."),
)

#: Countries the rubro step offers — the same table the discovery detects locations
#: against, so a chosen country is always one the search knows how to name.
COUNTRY_OPTIONS: tuple[tuple[str, str], ...] = tuple(
    (code, country.name) for code, country in creator_discovery.COUNTRIES.items()
)


def add_pills(
    pills: list[dict[str, str]], items: list[dict[str, str]]
) -> tuple[list[dict[str, str]], str]:
    """`pills` plus `items`, skipping ones already there (accents/case folded) and
    stopping at `CHOSEN_HASHTAGS`. Returns the new pills and the note to show ("" when
    everything fitted)."""
    out = [dict(p) for p in pills]
    present = {fold(p["tag"]) for p in out}
    dropped = 0
    for item in items:
        slug = fold(item["tag"])
        if slug in present:
            continue
        if len(out) >= creator_discovery.CHOSEN_HASHTAGS:
            dropped += 1
            continue
        out.append({"tag": item["tag"], "origin": "manual", "reason": "", "model": "", **item})
        present.add(slug)
    if dropped:
        cap = creator_discovery.CHOSEN_HASHTAGS
        return out, f"Caben {cap} hashtags: quita alguno para agregar otro."
    return out, ""


def merge_suggestions(
    pills: list[dict[str, str]], choice: hashtag_catalog.HashtagChoice
) -> tuple[list[dict[str, str]], str]:
    """A "Sugerir" answer into the pills: the operator's hand-typed pills stay, the
    previous suggestions are replaced by the new ones."""
    kept = [p for p in pills if p["origin"] == "manual"]
    origin = "ai" if choice.by == "ai" else "catalog"
    suggested = [
        {
            "tag": tag,
            "origin": origin,
            "reason": str(choice.picks.get(tag, {}).get("reason", "")),
            "model": str(choice.picks.get(tag, {}).get("model", "")),
        }
        for tag in choice.tags
    ]
    out, note = add_pills(kept, suggested)
    if not choice.tags:
        note = (
            "No encontramos hashtags de tu rubro en nuestra base todavía. Agrega los tuyos: "
            "con ellos buscamos."
        )
    return out, note


def seed_with_pills(
    seed: creator_discovery.DiscoverySeed, pills: list[dict[str, str]]
) -> tuple[creator_discovery.DiscoverySeed, dict[str, dict[str, str]]]:
    """The seed with the operator's pills as its hashtags (`chosen_hashtags`), and each
    one's provenance for the stored phase (`referentes_provider.seed_payload`)."""
    picks: dict[str, dict[str, str]] = {}
    for item in pills:
        if item["origin"] == "ai":
            picks[item["tag"]] = {"suggested_by": item["model"], "reason": item["reason"]}
        elif item["origin"] == "catalog":
            picks[item["tag"]] = {"suggested_by": "catalogo"}
        else:
            picks[item["tag"]] = {}
    tags = tuple(item["tag"] for item in pills)
    return replace(seed, chosen_hashtags=tags), picks


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
    #: ¿Tienes logo? answered "Usar mi foto de perfil" (`answer_has_logo`). Mirrored
    #: here from `BrandWizardState.has_logo` because `_is_skipped` is synchronous and
    #: cannot `get_state`: it is what skips Tu logo.
    logo_from_profile: bool = False
    #: The read's picture is a REAL one: fetched, and not the grey "no picture"
    #: silhouette Instagram/TikTok show for an account without one
    #: (`logo_palette.is_placeholder_avatar`, § request 2026-09-16). Only then is
    #: "Mi foto de perfil es mi logo" offered. Worked out by `analyze` right after the
    #: read; False until then, and whenever the picture cannot be fetched.
    profile_pic_is_real: bool = False

    #: ¿Eres influencer o una marca?'s answer — "marca" | "influencer" | "ambas" | ""
    #: (unanswered). Gates the Google Maps pair (an influencer has no local business
    #: to list) and whether the rubro step requires a location.
    account_kind: str = ""

    #: ¿Tu negocio está en Google Maps?'s answer — "si" | "no" | "" (unanswered).
    #: Self-reported only: unlike a logo, there is no scraped signal to check this
    #: against, so it lives here rather than being auto-set like `profile_pic`.
    has_maps: str = ""

    #: True when the operator came in through "No, todavía no" → Crea tu cuenta (§
    #: request 2026-09-11). Set by `start_without_socials`, cleared on every visit to
    #: the `/brand` fork (`clear_entry`). See `is_fresh_start`.
    started_without_socials: bool = False

    #: Tu rubro y ubicación — a `creator_discovery.NICHE_TAXONOMY` key, an ISO country
    #: code and a free-text city. PREFILLED by `analyze()` from what the profile read
    #: lets `creator_discovery.seed_from_profile` detect (bio, Instagram category, the
    #: account's own hashtags), editable on the step. Not persisted, like `account_kind`.
    sector: str = ""
    #: The rubro in the operator's own words ("peluquería canina") — what the discovery
    #: searches with for any rubro; `sector` (a taxonomy category) is optional
    #: vocabulary on top. Either one completes the step.
    rubro_text: str = ""
    country_code: str = ""
    city: str = ""
    #: The hashtags the search will use, as pills under the rubro (§ request
    #: 2026-09-25): suggested by Claude with its catalog tools (`suggest_hashtags`) and/or
    #: typed by hand, each removable. `{"tag", "origin", "reason", "model"}` — origin is
    #: `ai` (Claude suggested it), `catalog` (the rule path suggested it, no key) or
    #: `manual`. When there are any they BECOME the search's hashtags
    #: (`DiscoverySeed.chosen_hashtags`) and the search makes no AI call of its own.
    rubro_hashtags: list[dict[str, str]] = []
    new_hashtag: str = ""
    suggesting_hashtags: bool = False
    hashtag_note: str = ""

    #: The phased creator discovery on Resultados e insights (`run_discovery`). One
    #: list of account cards per phase (`creator_discovery.account_card` shape), plus
    #: its title and the note shown when it came back empty.
    discovering: bool = False
    discovery_ran: bool = False
    discovery_error: str = ""
    discovery_signals: list[str] = []
    sector_title: str = ""
    sector_note: str = ""
    sector_accounts: list[dict[str, str]] = []
    national_title: str = ""
    national_note: str = ""
    national_accounts: list[dict[str, str]] = []
    local_title: str = ""
    local_note: str = ""
    local_accounts: list[dict[str, str]] = []
    #: Which phase is running right now, for the loading line ("" when idle).
    discovery_running: str = ""
    #: Run token (§ request 2026-09-11, "que la búsqueda inicie desde que se obtiene
    #: el perfil"): the search starts as soon as the profile is read and starts AGAIN
    #: if the rubro step changes what it is seeded with. A superseded run still
    #: finishes its vendor calls but applies nothing — every write checks the token.
    discovery_run_id: int = 0
    #: The rubro answers the running search was seeded with (`_answers`), so leaving
    #: the rubro step only restarts it when something actually changed.
    discovery_answers: list[str] = []

    #: Referente, competencia o detractor — bucket per account key
    #: (`"<network>:@<handle>"`, see `_account_key`). Stored in Postgres per brand
    #: (`sync_labels`) and restored when a search puts the accounts back on screen.
    account_buckets: dict[str, str] = {}
    #: Backend-only: the sort as last written to Postgres, what `sync_labels` diffs
    #: `account_buckets` against.
    _persisted_buckets: dict[str, str] = {}
    #: Accounts the operator sorted that this search did NOT find again (a newer
    #: algorithm dropped them) — their decision still stands, so they stay in their
    #: bucket, with the card of the newest stored phase that found them. Never dealt
    #: into the deck: they are sorted already.
    kept_accounts: list[dict[str, str]] = []
    #: The card being dragged, same key.
    dragging: str = ""
    #: Which category the sort step is on (index into `creator_discovery.PHASES`):
    #: sector first, then national, then local (§ request 2026-09-11, "por pasos").
    #: Each category is sorted on its own, so one that failed never blocks the rest.
    sort_stage: int = 0
    #: Position in the category's unsorted pool of the account shown in the middle
    #: (§ request 2026-09-11, "una cuenta en el medio"); Omitir moves it on.
    stage_cursor: int = 0
    #: The last account sent to a bucket, for Deshacer.
    last_assigned: str = ""
    #: The card that just left the deck and the way it went ("left" / "right" /
    #: "down") — rendered once more as a ghost that flies out (`.q-fly-*`, keyed by
    #: `fly_token` so every decision restarts the animation). Pure presentation: the
    #: assignment itself is immediate and synchronous.
    fly_card: dict[str, str] = {}
    fly_direction: str = ""
    fly_token: int = 0
    #: The bucket the last decision landed in — the zone that flashes (`.q-deck-zone
    #: [data-hit]`, re-keyed by `fly_token` so a second hit on the same zone replays).
    hit_bucket: str = ""

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

    #: Set when the cursor lands on Tu rubro y ubicación, so a step the operator was
    #: actually shown stays reachable with Atrás after they complete it — otherwise
    #: completing it would make `_is_skipped` hide the very screen they just edited.
    rubro_asked: bool = False

    # -- which steps a session sees ---------------------------------------------------
    # Plain methods for the backend walk; the `@rx.var`s below repeat the same
    # expressions over fields directly (computed-var dependency tracking reads field
    # access, and a helper call would hide it).

    def _is_fresh(self) -> bool:
        return self.started_without_socials or (
            self.profile_followers_count < _NEW_ACCOUNT_FOLLOWER_THRESHOLD
        )

    def _rubro_complete(self) -> bool:
        if self.account_kind == "influencer":
            return bool(self.sector)  # category only (§ request 2026-09-11)
        if not self.sector and not self.rubro_text.strip():
            return False
        return bool(self.country_code and self.city.strip())

    def _answers(self) -> list[str]:
        """What the discovery is seeded with from this state, in one comparable shape."""
        return [
            self.sector,
            self.rubro_text.strip(),
            self.country_code,
            self.city.strip(),
            ",".join(item["tag"] for item in self.rubro_hashtags),
        ]

    def _is_skipped(self, index: int) -> bool:
        """THE one place deciding which steps a session sees (2026-09-11):
        - Lo que te proponemos: skipped on a fresh start — nothing to propose FROM.
        - Tu rubro y ubicación: ALWAYS shown since 2026-09-11 ("para cuando se es
          influencer también quiero que me deje escoger rubro y ubicación") — for an
          existing account it arrives prefilled from the profile read, which is the
          moment to correct it.
        - ¿Tienes logo? (§ request 2026-09-21): a brand or "ambas" is ALWAYS asked — a
          real profile picture does not skip it, it PRE-ANSWERS it: `analyze` detects the
          picture (`_use_profile_picture_as_logo`) and leaves "Mi foto de perfil es mi
          logo" selected, so Continuar accepts it and the operator can pick another
          answer. An INFLUENCER is asked only when that detection found nothing to
          take — no picture at all, the network's default silhouette, or one that cannot
          be fetched: a creator with a real picture already has their logo, so
          `logo_from_profile` skips the question for them.
        - Tu logo: skipped only while "Mi foto de perfil es mi logo" stands
          (`logo_from_profile`), for any kind of account — with the picture as the logo
          there is nothing left to upload or describe.
        - ¿Tu negocio está en Google Maps?: skipped for "influencer".
        - Súmate a Google Maps: skipped for "influencer" and on a "sí"."""
        if index == _RECOMMENDATIONS_STEP:
            return self._is_fresh()
        if index == _LOGO_QUESTION_STEP:
            return self.account_kind == "influencer" and self.logo_from_profile
        if index == _LOGO_UPLOAD_STEP:
            return self.logo_from_profile
        if index == _MAPS_QUESTION_STEP:
            return self.account_kind == "influencer"
        if index == _MAPS_STEPS_STEP:
            return self.account_kind == "influencer" or self.has_maps == "si"
        return False

    def _walk(self, start: int, direction: int) -> int:
        """From `start`, keep moving in `direction` past skipped steps. Steps 0 and
        `CONNECT_LAST` are never skipped, so the walk always ends inside the flow."""
        target = start
        while 0 < target < CONNECT_LAST and self._is_skipped(target):
            target += direction
        return target

    def _land(self, target: int) -> None:
        if target == _RUBRO_STEP:
            self.rubro_asked = True
        self.step = target

    @rx.var
    def is_fresh_start(self) -> bool:
        """Came in through "No, todavía no", or the read account is brand new."""
        return self.started_without_socials or (
            self.profile_followers_count < _NEW_ACCOUNT_FOLLOWER_THRESHOLD
        )

    @rx.var
    def needs_location(self) -> bool:
        """A brand (or both) must say where it is; for a creator it is optional."""
        return self.account_kind != "influencer"

    @rx.var
    def rubro_complete(self) -> bool:
        if self.account_kind == "influencer":
            return self.sector != ""
        if not self.sector and self.rubro_text.strip() == "":
            return False
        return self.country_code != "" and self.city.strip() != ""

    @rx.var
    def is_influencer(self) -> bool:
        return self.account_kind == "influencer"

    @rx.var
    def shows_cancel(self) -> bool:
        """Cancelar replaces Atrás on the LAST screen of this flow's own preview
        stretch — Lo que te proponemos, or Esto es lo que vemos when that one is
        skipped for a fresh start."""
        fresh = self.started_without_socials or (
            self.profile_followers_count < _NEW_ACCOUNT_FOLLOWER_THRESHOLD
        )
        return self.step == (_PROFILE_STEP if fresh else _RECOMMENDATIONS_STEP)

    @rx.event
    def next_step(self) -> rx.event.EventSpec | None:
        """Continuar. Leaving Tu rubro y ubicación (re)starts the creator discovery
        when the answers differ from what the running search was seeded with —
        `run_discovery` handles the token; this only decides whether to fire it."""
        leaving_rubro = self.step == _RUBRO_STEP
        self._land(self._walk(min(self.step + 1, CONNECT_LAST), +1))
        if leaving_rubro and self._answers() != self.discovery_answers:
            return BrandConnectState.run_discovery
        # Arriving at the sort step with no search ever started (a backend restart
        # wiped the session mid-walk, or nothing was detectable to start it from):
        # start it now, or the loading screen there would wait for nothing.
        if self.step == _SORT_STEP and not self.discovery_ran and not self.discovering:
            return BrandConnectState.run_discovery
        return None

    @rx.event
    def prev_step(self) -> rx.event.EventSpec | None:
        """Same rule as the manual flow's `BrandWizardState.prev_step`: back from the
        first step leaves the wizard rather than sitting disabled. Walks back over
        exactly the steps `next_step` walks forward over (`_is_skipped`)."""
        if self.step == 0:
            return rx.redirect("/brand")
        self._land(self._walk(self.step - 1, -1))
        return None

    @rx.event
    def start_without_socials(self) -> rx.event.EventSpec:
        """ "Ya la creé, continuar" on Crea tu cuenta — the "No, todavía no" branch.
        Starts a clean walk flagged as a fresh start (§ `is_fresh_start`)."""
        self._reset_fields()
        self.started_without_socials = True
        return rx.redirect("/brand/connect")

    @rx.event
    def clear_entry(self) -> None:
        """On every visit to the `/brand` fork: whichever answer comes next decides
        again whether this is a fresh start."""
        self.started_without_socials = False

    @rx.event
    def set_sector(self, value: str) -> None:
        self.sector = value

    @rx.event
    def set_rubro_text(self, value: str) -> None:
        self.rubro_text = value

    @rx.event
    def set_country_code(self, value: str) -> None:
        self.country_code = value

    @rx.event
    def set_city(self, value: str) -> None:
        self.city = value

    @rx.event
    def set_new_hashtag(self, value: str) -> None:
        self.new_hashtag = value

    @rx.event
    def add_hashtag(self) -> None:
        """The pills' "+" (and Enter in its input): one hand-typed hashtag, normalised
        the way the catalog stores them (no `#`, lowercase, one token)."""
        raw = self.new_hashtag.strip()
        if not raw:
            return
        try:
            tag = normalize_tag(raw)
        except ValueError:
            self.hashtag_note = "Un hashtag es una sola palabra, sin espacios."
            return
        self.new_hashtag = ""
        self.rubro_hashtags, self.hashtag_note = add_pills(
            self.rubro_hashtags, [{"tag": tag, "origin": "manual"}]
        )

    @rx.event
    def remove_hashtag(self, tag: str) -> None:
        self.rubro_hashtags = [item for item in self.rubro_hashtags if item["tag"] != tag]
        self.hashtag_note = ""

    @rx.event(background=True)
    async def suggest_hashtags(self) -> None:
        """The button next to Tu rubro: Claude explores the hashtag catalog with its
        tools (`hashtag_catalog.suggest_hashtags`) for this rubro, this brand's profile
        and place, and the answer lands as pills the operator can curate. Background:
        a tool run takes several seconds and the step stays usable meanwhile."""
        async with self:
            if self.suggesting_hashtags:
                return
            if not self.sector and not self.rubro_text.strip():
                self.hashtag_note = "Escribe tu rubro (o elige una categoría) y te sugerimos."
                return
            self.suggesting_hashtags = True
            self.hashtag_note = ""
            network = self.network
            handle = self.profile_username or self.username.strip()
            answers = {
                "sector": self.sector,
                "rubro_text": self.rubro_text.strip(),
                "country_code": self.country_code,
                "city": self.city.strip(),
            }
            fallback = {
                "username": self.profile_username,
                "bio": self.profile_bio,
                "category": self.profile_category,
            }
        ids = await self._referentes_ids()
        choice: hashtag_catalog.HashtagChoice | None = None
        note = ""
        if ids is None:
            note = "Inicia sesión con tu negocio para que te sugiramos hashtags."
        else:
            try:
                profile = await asyncio.to_thread(
                    scrapecreators_client.load_cached_profile, network, handle
                )
                source = profile or fallback
                seed = creator_discovery.seed_from_profile(source, **answers)
                choice = await asyncio.to_thread(
                    hashtag_catalog.suggest_hashtags,
                    ids[0],
                    seed,
                    bio=str(source.get("bio") or ""),
                    category=str(source.get("category") or ""),
                )
            except (SQLAlchemyError, OSError, ValueError) as exc:
                logger.warning("hashtags: suggestion failed: %s", exc)
                note = "No pudimos sugerir hashtags ahora. Agrega los tuyos o inténtalo luego."
        async with self:
            self.suggesting_hashtags = False
            if choice is not None:
                self.rubro_hashtags, self.hashtag_note = merge_suggestions(
                    self.rubro_hashtags, choice
                )
            else:
                self.hashtag_note = note

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
        a cursor nothing in this flow reads.

        "perfil" (§ request 2026-09-16) takes the scraped profile picture as the logo:
        its colours go to the palette (`BrandWizardState.apply_logo_colours`) and Tu
        logo is skipped — there is nothing left to upload or describe. The picture comes
        through `avatar_proxy.resolve_avatar`, which reads it from disk when a previous
        render already kept it and otherwise fetches it once from the vendor's CDN — no
        Scrape Creators credit either way. A picture that cannot be fetched just leaves
        the palette as it is. Any other answer retires colours the picture contributed."""
        if value == HAS_LOGO_PROFILE and not self.profile_pic_is_real:
            return  # not offered for a default or missing picture; nothing to take
        wizard = await self.get_state(BrandWizardState)
        wizard.has_logo = value
        self.logo_from_profile = value == HAS_LOGO_PROFILE
        if self.logo_from_profile:
            await self._apply_profile_picture_colours(wizard)
        elif wizard.logo_source == LOGO_SOURCE_PROFILE:
            await wizard.retire_logo_colours()
        self.next_step()

    async def _apply_profile_picture_colours(self, wizard: BrandWizardState) -> bool:
        """Put the profile picture's colours in the palette. False when the picture cannot
        be fetched (then the palette is left as it is). No Scrape Creators credit."""
        found = await avatar_proxy.resolve_avatar(
            self.network, self.profile_username, self.profile_pic
        )
        if found is None:
            return False
        await wizard.apply_logo_colours(found[0], LOGO_SOURCE_PROFILE)
        return True

    async def _use_profile_picture_as_logo(self) -> None:
        """Detect that the profile picture is the logo and PRE-ANSWER ¿Tienes logo? with it
        (§ request 2026-09-21: "que detecte 'mi foto de perfil es mi logo' cuando tenga
        foto de perfil y no sea la predeterminada"). Only for a picture that passed
        `_picture_is_real` and can be fetched now — otherwise nothing is set and the
        question opens unanswered. A brand or "ambas" still sees the question with the
        picture selected; an influencer, whose picture IS their logo, is not asked at all
        (see `_is_skipped`). Setting `logo_from_profile` also skips Tu logo. Runs inside
        the caller's `async with self`."""
        wizard = await self.get_state(BrandWizardState)
        if not await self._apply_profile_picture_colours(wizard):
            return
        wizard.has_logo = HAS_LOGO_PROFILE
        self.logo_from_profile = True

    async def _forget_profile_picture_logo(self) -> None:
        """A NEW profile read: what the previous read's picture put in the palette goes
        back out, so a brand with no real picture is not left with another account's
        colours and a "yes, profile picture" answer it never gave. Runs inside the
        caller's `async with self`."""
        wizard = await self.get_state(BrandWizardState)
        if wizard.has_logo == HAS_LOGO_PROFILE:
            wizard.has_logo = ""
        if wizard.logo_source == LOGO_SOURCE_PROFILE:
            await wizard.retire_logo_colours()

    @rx.event
    def answer_account_kind(self, value: str) -> None:
        """¿Eres influencer o una marca?'s own choice handler — records the answer and
        moves on; which steps follow is `_is_skipped`'s call (the Maps pair for an
        influencer, the rubro step when nothing is missing)."""
        self.account_kind = value
        self.next_step()

    @rx.event
    def answer_has_maps(self, value: str) -> None:
        """¿Tu negocio está en Google Maps?'s own choice handler. Both answers stay in
        `BrandConnectState` itself — not a kit field, no manual-flow counterpart. "Sí"
        makes `_is_skipped` jump Súmate a Google Maps; "no" shows it."""
        self.has_maps = value
        self.next_step()

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
        self.logo_from_profile = False
        self.profile_pic_is_real = False
        self.account_kind = ""
        self.has_maps = ""
        self.started_without_socials = False
        self.sector = ""
        self.rubro_text = ""
        self.country_code = ""
        self.city = ""
        self.rubro_hashtags = []
        self.new_hashtag = ""
        self.suggesting_hashtags = False
        self.hashtag_note = ""
        self.rubro_asked = False
        self._clear_discovery()
        self._set_metrics([])

    def _clear_discovery(self) -> None:
        self.discovering = False
        self.discovery_ran = False
        self.discovery_error = ""
        self.discovery_signals = []
        self.discovery_running = ""
        self.discovery_answers = []
        self.account_buckets = {}
        self._persisted_buckets = {}
        self.kept_accounts = []
        self.dragging = ""
        self.sort_stage = 0
        self.stage_cursor = 0
        self.last_assigned = ""
        self.fly_card = {}
        self.fly_direction = ""
        self.hit_bucket = ""
        for key in creator_discovery.PHASES:
            setattr(self, f"{key}_title", "")
            setattr(self, f"{key}_note", "")
            setattr(self, f"{key}_accounts", [])

    def _apply_phase(self, phase: dict) -> None:
        """One phase's result (`creator_discovery.phase_to_dict` shape, fresh or from
        the cache) into its three vars. A phase that failed on vendor errors and found
        nothing says so instead of pretending the sector is empty."""
        key = str(phase.get("key", ""))
        if key not in creator_discovery.PHASES:
            return
        accounts = [
            # `avatar_src`: the backend path the card's picture is served from
            # (`creator_discovery.avatar_path` → `avatar_proxy.py`), resolved here so a
            # cached result from before pictures existed gets one too.
            {**a, "avatar_src": creator_discovery.avatar_path(a)}
            for a in phase.get("accounts") or []
            if isinstance(a, dict)
        ]
        note = str(phase.get("note") or "")
        if phase.get("errors") and not accounts:
            note = "No pudimos completar esta búsqueda ahora. Inténtalo más tarde."
        setattr(self, f"{key}_title", str(phase.get("title") or ""))
        setattr(self, f"{key}_note", note)
        setattr(self, f"{key}_accounts", accounts)
        # Fire-and-forget (§ request 2026-09-14, "más rápido cargar las imágenes"):
        # download every one of this phase's pictures into the proxy's cache right
        # now, in parallel, instead of waiting for the browser to ask for each one
        # as the deck/list renders it. A no-op outside a running loop, so calling
        # `_apply_phase` directly and synchronously (existing tests do) is unaffected.
        avatar_proxy.warm_avatars_in_background(accounts)

    # -- Referente, competencia o detractor -------------------------------------------

    # The three readers below load the phase vars by NAME, not through
    # `getattr(self, f"{key}_…")` — and that is load-bearing, not style. Reflex works
    # a computed var's dependencies out from its bytecode (`LOAD_ATTR self.<name>`,
    # recursing into methods called on `self`), so a dynamic `getattr` registers no
    # dependency at all: the deck's vars used to depend only on `sort_stage`/
    # `stage_cursor`/`account_buckets`, never on `sector_accounts` & co., and the
    # step opened EMPTY until Siguiente + Anterior touched `sort_stage` and forced a
    # recompute (bug reported 2026-09-14). `test_brand_connect_flow` pins the
    # dependency set so this cannot regress quietly.
    def _phase_title(self, key: str) -> str:
        return {
            "sector": self.sector_title,
            "national": self.national_title,
            "local": self.local_title,
        }[key]

    def _phase_note(self, key: str) -> str:
        return {
            "sector": self.sector_note,
            "national": self.national_note,
            "local": self.local_note,
        }[key]

    def _phase_accounts(self, key: str) -> list[dict[str, str]]:
        return {
            "sector": self.sector_accounts,
            "national": self.national_accounts,
            "local": self.local_accounts,
        }[key]

    @rx.var
    def discovered_accounts(self) -> list[dict[str, str]]:
        """Every account the three phases found, once each, with its bucket key and
        its current bucket ("" while unsorted) — what the sort step deals out — plus
        the kept accounts (`kept_accounts`, read by name for the dependency tracking
        explained above), which only ever show inside their bucket."""
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for key in creator_discovery.PHASES:
            for item in self._phase_accounts(key):
                account_key = _account_key(item)
                if account_key in seen:
                    continue
                seen.add(account_key)
                bucket = self.account_buckets.get(account_key, "")
                out.append({**item, "key": account_key, "bucket": bucket})
        for item in self.kept_accounts:
            account_key = _account_key(item)
            bucket = self.account_buckets.get(account_key, "")
            if account_key in seen or not bucket:
                continue
            seen.add(account_key)
            out.append({**item, "key": account_key, "bucket": bucket})
        return out

    @rx.var
    def unsorted_accounts(self) -> list[dict[str, str]]:
        return [a for a in self.discovered_accounts if a["bucket"] == ""]

    @rx.var
    def referente_accounts(self) -> list[dict[str, str]]:
        return [a for a in self.discovered_accounts if a["bucket"] == "referente"]

    @rx.var
    def competencia_accounts(self) -> list[dict[str, str]]:
        return [a for a in self.discovered_accounts if a["bucket"] == "competencia"]

    @rx.var
    def detractor_accounts(self) -> list[dict[str, str]]:
        return [a for a in self.discovered_accounts if a["bucket"] == "detractor"]

    @rx.var
    def has_sorted(self) -> bool:
        return len(self.account_buckets) > 0

    def _phase_cards(self, key: str) -> list[dict[str, str]]:
        """One category's cards with their bucket key and current bucket."""
        out: list[dict[str, str]] = []
        for item in self._phase_accounts(key):
            account_key = _account_key(item)
            bucket = self.account_buckets.get(account_key, "")
            out.append({**item, "key": account_key, "bucket": bucket})
        return out

    @rx.var
    def stage_key(self) -> str:
        return creator_discovery.PHASES[min(self.sort_stage, len(creator_discovery.PHASES) - 1)]

    @rx.var
    def stage_label(self) -> str:
        return f"Categoría {self.sort_stage + 1} de {len(creator_discovery.PHASES)}"

    @rx.var
    def stage_title(self) -> str:
        titles = {"sector": "Referentes del sector", "national": "Nacionales", "local": "Locales"}
        return self._phase_title(self.stage_key) or titles[self.stage_key]

    @rx.var
    def stage_note(self) -> str:
        return self._phase_note(self.stage_key)

    @rx.var
    def stage_failed(self) -> bool:
        """The category's search hit vendor errors and found nothing — offer a retry."""
        return self.stage_note.startswith("No pudimos")

    @rx.var
    def stage_pending(self) -> bool:
        """Nothing landed for this category yet and the search is still running."""
        key = self.stage_key
        return self.discovering and not self._phase_title(key) and not self._phase_note(key)

    @rx.var
    def waiting_for_referentes(self) -> bool:
        """The sort step is behind a loading screen while the search runs (§ request
        2026-09-14: "una pantalla de carga antes de Referente, competencia o
        detractor para obligar al usuario a esperar"). It used to render the deck
        category by category as each phase landed — and its Continuar let the
        operator skip straight to Resultados e insights before anything had loaded.
        Now the whole step, controls included, waits for every phase."""
        return self.step == _SORT_STEP and self.discovering

    @rx.var
    def discovery_progress(self) -> list[dict[str, str]]:
        """One row per category for the loading screen: `done` once its result
        landed, `running` for the first one still missing (phases run in order —
        they share the account pool, `creator_discovery.PhasedDiscovery`), `pending`
        after it. Phase fields are read by NAME (`_phase_title`/`_phase_note`), so
        each landing recomputes this — see the dependency note above them."""
        generic = {
            "sector": "Referentes del sector",
            "national": "Referentes nacionales",
            "local": "Referentes locales",
        }
        rows: list[dict[str, str]] = []
        running_taken = False
        for key in creator_discovery.PHASES:
            landed_title = self._phase_title(key)
            if landed_title or self._phase_note(key):
                rows.append({"title": landed_title or generic[key], "status": "done"})
            elif not running_taken and self.discovering:
                running_taken = True
                rows.append({"title": self.discovery_running or generic[key], "status": "running"})
            else:
                rows.append({"title": generic[key], "status": "pending"})
        return rows

    @rx.var
    def stage_pool(self) -> list[dict[str, str]]:
        return [a for a in self._phase_cards(self.stage_key) if a["bucket"] == ""]

    @rx.var
    def stage_referente(self) -> list[dict[str, str]]:
        return [a for a in self._phase_cards(self.stage_key) if a["bucket"] == "referente"]

    @rx.var
    def stage_competencia(self) -> list[dict[str, str]]:
        return [a for a in self._phase_cards(self.stage_key) if a["bucket"] == "competencia"]

    @rx.var
    def stage_detractor(self) -> list[dict[str, str]]:
        return [a for a in self._phase_cards(self.stage_key) if a["bucket"] == "detractor"]

    @rx.var
    def current_card(self) -> dict[str, str]:
        """The account in the middle of the deck: the pool entry at `stage_cursor`
        (wrapping, so Omitir cycles), or an empty dict when the pool is empty."""
        pool = self.stage_pool
        if not pool:
            return {}
        return pool[self.stage_cursor % len(pool)]

    @rx.var
    def has_current_card(self) -> bool:
        return len(self.stage_pool) > 0

    @rx.var
    def stage_remaining(self) -> int:
        return len(self.stage_pool)

    @rx.var
    def is_dragging(self) -> bool:
        return self.dragging != ""

    @rx.var
    def can_undo(self) -> bool:
        return self.last_assigned != "" and self.last_assigned in self.account_buckets

    @rx.event
    def skip_card(self) -> None:
        if self.stage_pool:
            self.stage_cursor = (self.stage_cursor + 1) % len(self.stage_pool)

    @rx.event
    def send_current(self, bucket: str) -> rx.event.EventSpec | None:
        """The three arrow buttons under the card — the tap alternative to dragging.
        Propagates `assign`'s own chained event (§ `advance_stage_if_exhausted`)."""
        card_ = self.current_card
        if card_:
            return self.assign(card_["key"], bucket)
        return None

    @rx.event
    def undo_last(self) -> None:
        if self.last_assigned:
            self.assign(self.last_assigned, "")
            self.last_assigned = ""

    @rx.var
    def is_first_stage(self) -> bool:
        return self.sort_stage <= 0

    @rx.var
    def is_last_stage(self) -> bool:
        return self.sort_stage >= len(creator_discovery.PHASES) - 1

    @rx.event
    def next_sort_stage(self) -> None:
        self.sort_stage = min(self.sort_stage + 1, len(creator_discovery.PHASES) - 1)
        self.stage_cursor = 0

    @rx.event
    def prev_sort_stage(self) -> None:
        self.sort_stage = max(self.sort_stage - 1, 0)
        self.stage_cursor = 0

    @rx.event
    def start_drag(self, key: str) -> None:
        self.dragging = key

    @rx.event
    def end_drag(self) -> None:
        self.dragging = ""

    @rx.event
    def drop_into(self, bucket: str) -> rx.event.EventSpec | None:
        """A card released over a panel. Since 2026-09-14 the drag is pointer-driven
        (`assets/deck-drag.js`): the card in the middle physically follows the pointer
        and shrinks into the panel, and the script then dispatches `drop` on the
        panel — so the card to assign is the one in the middle (`dragging` is only
        set by the older HTML5 path, kept for the tests), and NO ghost flies: the
        operator just watched the real card land there. The panel still flashes.
        Propagates `assign`'s own chained event (§ `advance_stage_if_exhausted`)."""
        key = self.dragging or (self.current_card.get("key", "") if self.current_card else "")
        result = self.assign(key, bucket, fly=False) if key else None
        self.dragging = ""
        return result

    @rx.event
    def assign(self, key: str, bucket: str, fly: bool = True) -> rx.event.EventSpec | None:
        """Tap or drop. An empty bucket puts the account back in the pool. `fly`
        launches the ghost (`_deck_ghost`) — a tap needs it (the card would just
        vanish), a pointer drop does not.

        Chains `advance_stage_if_exhausted` (§ request 2026-09-14: "que cuando se
        acaben los referentes pase a la siguiente categoria y si no hay categorias
        que vaya a la otra view") whenever THIS decision is the one that empties the
        current category's pool — not when a `Reintentar`/still-loading category
        happens to be at zero, and not on the "quitar" branch (reverting only ever
        grows the pool back)."""
        buckets = dict(self.account_buckets)
        chain: rx.event.EventSpec | None = None
        if bucket in {b for b, _, _, _ in BUCKETS}:
            buckets[key] = bucket
            self.last_assigned = key
            leaving = next((a for a in self.stage_pool if a["key"] == key), None)
            if leaving is not None and fly:
                self.fly_card = leaving
                self.fly_direction = _FLY_DIRECTION[bucket]
            else:
                self.fly_direction = ""
            self.fly_token += 1
            self.hit_bucket = bucket
        else:
            buckets.pop(key, None)
            self.fly_direction = ""
            self.hit_bucket = ""
        self.account_buckets = buckets
        # the pool just shrank or grew: keep the cursor inside it
        remaining = len([a for a in self._phase_cards(self.stage_key) if a["bucket"] == ""])
        self.stage_cursor = min(self.stage_cursor, max(remaining - 1, 0))
        if (
            bucket in {b for b, _, _, _ in BUCKETS}
            and remaining == 0
            and not self.stage_pending
            and not self.stage_failed
        ):
            chain = BrandConnectState.advance_stage_if_exhausted
        return chain

    @rx.event
    def restart(self) -> rx.event.EventSpec:
        """Cancelar on the last preview screen before the shared kit-setup steps
        begin (§ `shows_cancel`). Drops everything read/entered and goes back to the
        fork."""
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
    async def advance_stage_if_exhausted(self) -> AsyncIterator[None]:
        """Chained by `assign()` when a decision leaves the current category with
        nothing left to classify (§ request 2026-09-14: "que cuando se acaben los
        referentes pase a la siguiente categoria y si no hay categorias que vaya a
        la otra view"). Waits `_STAGE_ADVANCE_DELAY` — long enough for the panel's
        hit-flash/the fly-ghost/the drag-release shrink to finish reading before the
        deck changes under the operator — then re-checks: a `Reintentar` or a slow
        phase landing more cards in the meantime cancels it. Moves to the next
        category, or — on the last one (`local`) — to Resultados e insights, reusing
        `advance_to_insights` exactly as Continuar would (same metric count-up)."""
        await asyncio.sleep(_STAGE_ADVANCE_DELAY)
        go_to_insights = False
        async with self:
            if self.has_current_card or self.stage_pending or self.stage_failed:
                return
            if self.is_last_stage:
                go_to_insights = True
            else:
                self.next_sort_stage()
        if go_to_insights:
            # a background handler cannot call another one directly (Reflex raises
            # `RuntimeError` on that, by design) — `yield` the chain instead, the
            # same idiom `assign()` uses to hand off to THIS handler.
            yield BrandConnectState.advance_to_insights

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
                # Deliberately NOT re-read from the snapshot file after this save. The
                # snapshot is one global, non-tenant-keyed JSON file (by design — see
                # scrapecreators_client's module docstring); this is a multi-session
                # async backend, so a concurrent session's own `save_profile_snapshot`
                # can land in the window between this save and a re-read, handing this
                # session someone else's real profile data (confirmed reproducible: two
                # interleaved saves, then a blind re-read, return the SECOND tenant's
                # profile to the FIRST). `profile` here is already the exact dict this
                # call just fetched — using it directly costs nothing extra and has no
                # race window, unlike reading it back from shared state. The save above
                # stays: it is what makes `load_cached_profile` (which DOES validate
                # network+handle before returning anything) a same-handle cache hit on
                # a later analyze() call.
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
            if self.logo_from_profile:
                await self._forget_profile_picture_logo()  # the previous read's picture
            self.logo_from_profile = False  # a new read: its picture was not taken yet
            self.profile_pic_is_real = False  # checked below, once the read is on screen
            read_pic, read_handle = self.profile_pic, self.profile_username
            # Real figures over the window (`recentPosts` of this same read).
            self._set_metrics(scrapecreators_client.profile_metrics(network, profile))
            # Prefill Tu rubro y ubicación with what the read lets us detect (bio,
            # Instagram category, the account's own hashtags) — the step then only
            # shows for an existing account when something is still missing.
            detected = creator_discovery.seed_from_profile(profile)
            self.sector = detected.niches[0] if detected.niches else ""
            self.country_code = detected.country_code
            self.city = detected.city
            self.rubro_asked = False
            self._clear_discovery()
            self.analyzing = False
            self.step = _PROFILE_STEP
            # § request 2026-09-11: the search is slow, so it starts NOW, from what the
            # profile alone says, and runs while the operator walks the kit steps; the
            # rubro step restarts it only if it changes the seed (`next_step`). A fresh
            # start has nothing to seed from until that step.
            start_now = not self._is_fresh() and bool(detected.niches or detected.hashtags)
        if start_now:
            yield BrandConnectState.run_discovery
        # After the read is on screen and the search has started: whether its picture
        # can stand in for a logo. Also leaves the picture on disk, so taking it below
        # reads it instantly. A real picture PRE-ANSWERS ¿Tienes logo? (§ request
        # 2026-09-21): "Mi foto de perfil es mi logo" arrives selected and its colours
        # seed the palette; the question is still shown (to a brand or "ambas") and Tu
        # logo is skipped while that answer stands. With no real picture it opens blank.
        is_real = await self._picture_is_real(network, read_handle, read_pic)
        async with self:
            if self.profile_pic == read_pic:
                self.profile_pic_is_real = is_real
                if is_real:
                    await self._use_profile_picture_as_logo()

    async def _picture_is_real(self, network: str, handle: str, picture_url: str) -> bool:
        """True when the profile picture exists, can be fetched (`avatar_proxy.
        resolve_avatar`: disk, then the network's CDN — never a Scrape Creators credit)
        and is not the network's default "no picture" image — recognised first by its
        shared object in the URL (`logo_palette.is_default_avatar_url`, no download at
        all: TikTok's), then by what it looks like (`is_placeholder_avatar`: the grey
        silhouette of Instagram and TikTok). Never raises: anything unknown is "not
        real", which only hides an optional choice."""
        if not picture_url or logo_palette.is_default_avatar_url(picture_url):
            return False
        try:
            found = await avatar_proxy.resolve_avatar(network, handle, picture_url)
            if found is None:
                return False
            return not await asyncio.to_thread(logo_palette.is_placeholder_avatar, found[0])
        except Exception as exc:  # noqa: BLE001 - an optional choice must never break the read
            logger.info("brand connect: profile picture check failed: %s", type(exc).__name__)
            return False

    @rx.event(background=True)
    async def run_discovery(self) -> AsyncIterator[None]:
        """The phased creator discovery (§ request 2026-09-11): the sector's most
        influential accounts, then the country's, then the city's — each phase
        applied as soon as it lands, so the sort step and the summary fill in that
        order instead of after one long wait. Starts at the profile read
        (`analyze`), restarts from the rubro step when the seed changed (`next_step`).

        Seeded from the cached profile snapshot (bio, category, `topHashtags` — zero
        credits, same file `analyze()` wrote) plus the rubro step's answers, which win
        over detection. The file first, per phase (`creator_discovery.
        load_cached_phase`): a remembered phase is applied at once and only the
        missing ones go to the vendor, in parallel calls, with the profile reads
        remembered on disk too (`PROFILE_CACHE_PATH`)."""
        async for _ in self._discovery(None):
            yield

    @rx.event(background=True)
    async def retry_phase(self, key: str) -> AsyncIterator[None]:
        """Reintentar on a category whose search failed (vendor 5xx): that one
        category again, the vendor's cache skipped, the other two untouched
        (§ request 2026-09-11: "si falla algún paso se puedan seleccionar el resto")."""
        if key not in creator_discovery.PHASES:
            return
        async for _ in self._discovery([key]):
            yield

    async def _discovery(self, only: list[str] | None) -> AsyncIterator[None]:
        """The shared body of `run_discovery` (every phase, cache first) and
        `retry_phase` (the given phases, cache skipped). Takes the run token either
        way: a superseded run finishes its vendor calls but applies nothing."""
        async with self:
            self.discovery_run_id += 1
            my_id = self.discovery_run_id
            if only is None:
                self._clear_discovery()
            else:
                self.discovery_error = ""
                for key in only:
                    setattr(self, f"{key}_title", "")
                    setattr(self, f"{key}_note", "")
                    setattr(self, f"{key}_accounts", [])
            self.discovering = True
            self.discovery_ran = True
            self.discovery_answers = self._answers()
            network = self.network
            handle = self.profile_username or self.username.strip()
            answers = {
                "sector": self.sector,
                "rubro_text": self.rubro_text.strip(),
                "country_code": self.country_code,
                "city": self.city.strip(),
            }
            fallback = {
                "username": self.profile_username,
                "bio": self.profile_bio,
                "category": self.profile_category,
            }
            # Bound under the lock: the pills as they were when the search started.
            pills = [dict(item) for item in self.rubro_hashtags]
        yield

        runner: creator_discovery.PhasedDiscovery | None = None
        # (tenant, brand, user) when the session has them — then phases and the sort
        # live in Postgres (`referentes_provider`, migration 0020). Without them (no
        # login, e.g. the offline tests) the JSON cache is used as before.
        ids = await self._referentes_ids()
        try:
            profile = await asyncio.to_thread(
                scrapecreators_client.load_cached_profile, network, handle
            )
            seed = creator_discovery.seed_from_profile(profile or fallback, **answers)
            if pills:
                # The operator's pills ARE the hashtags: no AI call of the search's own.
                seed, hashtag_picks = seed_with_pills(seed, pills)
            else:
                seed, hashtag_picks = await self._with_catalog_hashtags(
                    ids, seed, profile or fallback
                )
            async with self:
                if self.discovery_run_id != my_id:
                    return
                self.discovery_signals = seed.chips()
            yield

            keys = list(creator_discovery.PHASES) if only is None else list(only)
            if only is None:
                # Stored results first, one phase at a time: a phase already computed
                # for this seed by THIS algorithm version is applied at once, and only
                # the missing ones (a new city → the local phase alone) go to the vendor.
                for key in keys:
                    cached = await self._stored_phase(ids, key, seed)
                    if cached is None:
                        continue
                    async with self:
                        if self.discovery_run_id != my_id:
                            return
                        self._apply_phase(cached)
                    yield
                async with self:
                    keys = [
                        key
                        for key in keys
                        if not getattr(self, f"{key}_title") and not getattr(self, f"{key}_note")
                    ]
            if not keys:
                return

            runner = creator_discovery.PhasedDiscovery(
                seed, profile_cache=creator_discovery.PROFILE_CACHE_PATH
            )
            for key in keys:
                async with self:
                    if self.discovery_run_id != my_id:
                        return
                    self.discovery_running = creator_discovery.phase_title(key, seed)
                yield
                result = await asyncio.to_thread(runner.run, key)
                phase = creator_discovery.phase_to_dict(result)
                if result.errors:
                    logger.warning("brand discovery %s phase errors: %s", key, result.errors)
                await self._store_phase(ids, key, seed, result, phase, hashtag_picks)
                async with self:
                    if self.discovery_run_id != my_id:
                        return
                    self._apply_phase(phase)
                yield
        except (scrapecreators_client.ScrapeCreatorsError, ValueError, OSError) as exc:
            logger.warning("brand discovery failed: %s", exc)
            async with self:
                if self.discovery_run_id == my_id:
                    self.discovery_error = (
                        "No pudimos buscar referentes ahora. Inténtalo más tarde."
                    )
        finally:
            if runner is not None:
                await asyncio.to_thread(runner.close)
            restored, kept = await self._stored_sort(ids, my_id)
            async with self:
                if self.discovery_run_id == my_id:
                    if restored:
                        # A decision made in this session while the search ran wins
                        # over the stored one; the next `sync_labels` writes it.
                        self.account_buckets = {**restored, **self.account_buckets}
                        self._persisted_buckets = {**self._persisted_buckets, **restored}
                    if ids is not None:
                        self.kept_accounts = [
                            {**card, "avatar_src": creator_discovery.avatar_path(card)}
                            for card in kept
                        ]
                    self.discovering = False
                    self.discovery_running = ""

    # -- Postgres persistence of phases and the sort (`referentes_provider`) --------

    async def _referentes_ids(self) -> tuple[UUID, UUID, UUID | None] | None:
        """(tenant, brand, acting user) for the session, or None — no login, no brand,
        or the database unreachable. Must NOT be called while holding the state lock."""
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            return None
        try:
            brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
            if brand_id is None:
                return None
            user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        except SQLAlchemyError as exc:
            logger.warning("referentes: could not resolve the session's brand: %s", exc)
            return None
        return tenant_id, brand_id, user_id

    async def _stored_phase(
        self,
        ids: tuple[UUID, UUID, UUID | None] | None,
        key: str,
        seed: creator_discovery.DiscoverySeed,
    ) -> dict | None:
        if ids is None:
            return await asyncio.to_thread(creator_discovery.load_cached_phase, key, seed)
        try:
            return await asyncio.to_thread(
                referentes_provider.find_phase, ids[0], ids[1], key, seed
            )
        except SQLAlchemyError as exc:
            # A read failure is a cache miss, not a failed search.
            logger.warning("referentes: stored %s phase unreadable: %s", key, exc)
            return None

    async def _store_phase(
        self,
        ids: tuple[UUID, UUID, UUID | None] | None,
        key: str,
        seed: creator_discovery.DiscoverySeed,
        result: creator_discovery.PhaseResult,
        phase: dict,
        hashtag_picks: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        if ids is None:
            await asyncio.to_thread(creator_discovery.save_cached_phase, key, seed, phase)
            return
        try:
            await asyncio.to_thread(
                referentes_provider.save_phase,
                ids[0],
                ids[1],
                key,
                seed,
                result,
                phase,
                hashtag_picks,
            )
        except SQLAlchemyError as exc:
            # The operator still sees the result; only the reuse is lost.
            logger.warning("referentes: could not store the %s phase: %s", key, exc)
        await self._capture_hashtags(ids[0], key, seed, result)

    async def _with_catalog_hashtags(
        self,
        ids: tuple[UUID, UUID, UUID | None] | None,
        seed: creator_discovery.DiscoverySeed,
        profile: dict,
    ) -> tuple[creator_discovery.DiscoverySeed, dict[str, dict[str, str]]]:
        """The seed plus the catalog hashtags that fit this brand — chosen by Claude from
        a wide catalog pool (`hashtag_catalog.ai_hashtags_for`), or by the rule path when
        there is no key or the call fails — and the provenance of an AI choice, which is
        stored with each phase. Without a session that has a tenant, or when the catalog
        cannot be read, the seed comes back unchanged and the search runs as it did
        before the catalog existed."""
        if ids is None:
            return seed, {}
        try:
            choice = await asyncio.to_thread(
                hashtag_catalog.ai_hashtags_for,
                ids[0],
                seed,
                bio=str(profile.get("bio") or ""),
                category=str(profile.get("category") or ""),
            )
        except SQLAlchemyError as exc:
            logger.warning("hashtags: catalog unreadable, searching without it: %s", exc)
            return seed, {}
        picks = {tag: dict(info) for tag, info in choice.picks.items()}
        return replace(seed, catalog_hashtags=choice.tags), picks

    async def _capture_hashtags(
        self,
        tenant_id: UUID,
        key: str,
        seed: creator_discovery.DiscoverySeed,
        result: creator_discovery.PhaseResult,
    ) -> None:
        """Feed the shared hashtag catalog with what this fresh run saw, then let Claude
        classify a batch of what the rules left open — in the background: the operator
        is waiting for the next phase, not for the catalog. Its own guard: the catalog
        only ever ADDS knowledge, so a failure here must never touch the result the
        operator is looking at (nor the phase that was just stored)."""
        try:
            await asyncio.to_thread(hashtag_catalog.ensure_seeded, tenant_id)
            await asyncio.to_thread(
                hashtag_catalog.capture, tenant_id, seed, key, list(result.accounts)
            )
        except SQLAlchemyError as exc:
            logger.warning("hashtags: could not capture the %s phase: %s", key, exc)
            return
        task = asyncio.create_task(asyncio.to_thread(hashtag_catalog.classify_pending, tenant_id))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_finish_background_task)

    async def _stored_sort(
        self, ids: tuple[UUID, UUID, UUID | None] | None, run_id: int
    ) -> tuple[dict[str, str], list[dict[str, str]]]:
        """The stored sort for this run's accounts, plus the kept cards
        (`referentes_provider.load_sort`)."""
        if ids is None:
            return {}, []
        async with self:
            if self.discovery_run_id != run_id:
                return {}, []
            cards = [*self.sector_accounts, *self.national_accounts, *self.local_accounts]
        try:
            return await asyncio.to_thread(referentes_provider.load_sort, ids[0], ids[1], cards)
        except SQLAlchemyError as exc:
            logger.warning("referentes: stored sort unreadable: %s", exc)
            return {}, []

    @rx.event(background=True)
    async def sync_labels(self) -> None:
        """Writes the sort to Postgres. Fired right after every decision (the zones'
        tap and drop, Deshacer) and diff-based — it stores whatever changed since the
        last write, so it cannot miss an undo or write one twice. Serialized per brand
        so two quick taps are stored in the order they were made."""
        ids = await self._referentes_ids()
        if ids is None:
            return
        tenant_id, brand_id, user_id = ids
        async with _labels_lock(brand_id):
            async with self:
                current = dict(self.account_buckets)
                persisted = dict(self._persisted_buckets)
            changes = referentes_provider.label_changes(persisted, current)
            if not changes:
                return
            try:
                await asyncio.to_thread(
                    referentes_provider.write_labels, tenant_id, brand_id, user_id, changes
                )
            except (SQLAlchemyError, ValueError) as exc:
                # Left un-persisted: the next decision's sync retries the same diff.
                logger.warning("referentes: could not store the sort: %s", exc)
                return
            async with self:
                self._persisted_buckets = current


# ---------------------------------------------------------------------------
# The screens specific to this flow


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
    """Same question and copy as the manual flow's `_step_has_logo`, asked of every
    account right before Paleta de colores (§ request 2026-09-16). Cannot
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
        # § request 2026-09-16: the profile picture we already read is, for many
        # brands, the logo itself. Offered only for a REAL picture — not for none, and
        # not for the default grey silhouette (`profile_pic_is_real`).
        rx.cond(
            BrandConnectState.profile_pic_is_real,
            _choice_card(
                "Mi foto de perfil es mi logo",
                "Tomaremos sus colores para tu paleta.",
                BrandWizardState.has_logo == HAS_LOGO_PROFILE,
                BrandConnectState.answer_has_logo(HAS_LOGO_PROFILE),
            ),
        ),
        icon="image",
    )


def _connect_step_account_kind() -> rx.Component:
    """¿Eres influencer o una marca?. Always shown, self-reported, lives entirely in
    `BrandConnectState` (not a `brand_kits` field, no manual-flow counterpart). Since
    2026-09-11 it comes right after the profile recap — before ¿Quién es la marca? —
    and offers "Las dos cosas" next to the two single answers (`ACCOUNT_KINDS`)."""
    return _step_body(
        *(
            _choice_card(
                title,
                blurb,
                BrandConnectState.account_kind == key,
                BrandConnectState.answer_account_kind(key),
            )
            for key, title, blurb in ACCOUNT_KINDS
        ),
        icon="user-round",
    )


def _select_field(
    label: rx.Var[str] | str,
    value: rx.Var[str],
    handler: rx.event.EventHandler,
    options: tuple[tuple[str, str], ...],
    placeholder: str,
) -> rx.Component:
    """A labelled Radix select whose stored value is the option KEY, not its label —
    same `select.root` + `select.item(value=...)` shape `creative_pages` uses for the
    content type. Sized like `_labeled_input` so the rubro step reads as one form."""
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        rx.select.root(
            rx.select.trigger(placeholder=placeholder, width="100%", radius=_CONTROL_RADIUS),
            rx.select.content(
                *(rx.select.item(option_label, value=key) for key, option_label in options),
            ),
            value=value,
            on_change=handler,
            size="3",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _connect_step_rubro() -> rx.Component:
    """Tu rubro y ubicación (§ request 2026-09-11: "si es marca decidir qué rubro es y
    dónde se encuentra ubicado"). The three inputs the creator discovery on Resultados
    e insights is seeded with. A brand (or both) gives the rubro in its own words
    (any rubro at all: the discovery searches with them) or as a taxonomy category,
    either one, plus país + ciudad; a creator picks only a category and, optionally,
    where they are (§ request 2026-09-11: "solo la categoría y la ubicación") — without
    them the national / local phases simply say what is missing. For an existing account the fields
    arrive prefilled from the profile read (`analyze()`), which is why the hint
    changes."""
    return _step_body(
        rx.cond(
            ~BrandConnectState.is_influencer,
            rx.vstack(
                rx.text("Tu rubro, con tus palabras", size="2", weight="medium"),
                rx.hstack(
                    rx.input(
                        value=BrandConnectState.rubro_text,
                        on_change=BrandConnectState.set_rubro_text,
                        placeholder="Ej. peluquería canina, fisioterapia deportiva",
                        width="100%",
                        size="3",
                        height="2.75rem",
                        radius=_CONTROL_RADIUS,
                    ),
                    _suggest_hashtags_button(),
                    spacing="2",
                    width="100%",
                    align="center",
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        _select_field(
            rx.cond(BrandConnectState.is_influencer, "Categoría", "Categoría (opcional)"),
            BrandConnectState.sector,
            BrandConnectState.set_sector,
            tuple(creator_discovery.NICHE_LABELS.items()),
            "Elige una categoría",
        ),
        _rubro_hashtags_block(),
        _select_field(
            rx.cond(BrandConnectState.needs_location, "País", "País (opcional)"),
            BrandConnectState.country_code,
            BrandConnectState.set_country_code,
            COUNTRY_OPTIONS,
            "Elige el país",
        ),
        rx.vstack(
            rx.text(
                rx.cond(BrandConnectState.needs_location, "Ciudad", "Ciudad (opcional)"),
                size="2",
                weight="medium",
            ),
            rx.input(
                value=BrandConnectState.city,
                on_change=BrandConnectState.set_city,
                placeholder="Ej. Cúcuta",
                width="100%",
                size="3",
                height="2.75rem",
                radius=_CONTROL_RADIUS,
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        rx.text(
            rx.cond(
                BrandConnectState.is_fresh_start,
                "Con esto buscamos referentes de tu sector, de tu país y de tu ciudad.",
                "Lo completamos con lo que leímos de tu perfil. Corrígelo si hace falta.",
            ),
            size="2",
            color=T.TEXT_MUTED,
            text_align="center",
        ),
        icon="map-pin",
    )


def _suggest_hashtags_button() -> rx.Component:
    """The small button next to Tu rubro (§ request 2026-09-25): asks Claude, with its
    catalog tools, for the hashtags to search with (`BrandConnectState.
    suggest_hashtags`). Spins while the run lasts — a tool run takes a few seconds."""
    return rx.tooltip(
        rx.button(
            rx.cond(
                BrandConnectState.suggesting_hashtags,
                rx.spinner(size="2"),
                rx.icon("sparkles", size=T.ICON_SM),
            ),
            "Sugerir",
            on_click=BrandConnectState.suggest_hashtags,
            disabled=BrandConnectState.suggesting_hashtags,
            variant="soft",
            size="3",
            height="2.75rem",
            radius=_CONTROL_RADIUS,
            flex_shrink="0",
        ),
        content="Sugerir hashtags de tu rubro para buscar referentes",
    )


def _hashtag_pill_body(item: rx.Var[dict[str, str]], **badge: object) -> rx.Component:
    return rx.badge(
        rx.text("#", item["tag"]),
        rx.el.button(
            rx.icon("x", size=12),
            on_click=BrandConnectState.remove_hashtag(item["tag"]),
            type="button",
            aria_label="Quitar este hashtag",
            display="flex",
            align_items="center",
            background="transparent",
            border="none",
            padding="0",
            color="inherit",
            cursor="pointer",
        ),
        size="2",
        radius="full",
        gap="1",
        align_items="center",
        **badge,
    )


def _hashtag_pill(item: rx.Var[dict[str, str]]) -> rx.Component:
    """One pill: accent for a suggestion (hover shows Claude's reason), neutral for
    one the operator typed; the ✕ removes it either way."""
    suggested = rx.tooltip(
        _hashtag_pill_body(item, variant="soft"),
        content=rx.cond(item["reason"] != "", item["reason"], "Sugerido para tu rubro"),
    )
    typed = _hashtag_pill_body(item, variant="surface", color_scheme="gray")
    return rx.cond(item["origin"] == "manual", typed, suggested)


def _rubro_hashtags_block() -> rx.Component:
    """The hashtags the search will use, as pills (§ request 2026-09-25): filled by
    "Sugerir" and/or typed here, each removable. An influencer has no rubro input, so
    the suggest button sits in this block's header for them."""
    return rx.vstack(
        rx.hstack(
            rx.text("Hashtags para buscar referentes", size="2", weight="medium"),
            rx.spacer(),
            rx.cond(BrandConnectState.is_influencer, _suggest_hashtags_button()),
            width="100%",
            align="center",
        ),
        rx.cond(
            BrandConnectState.rubro_hashtags.length() > 0,
            rx.flex(
                rx.foreach(BrandConnectState.rubro_hashtags, _hashtag_pill),
                wrap="wrap",
                gap="2",
                width="100%",
            ),
        ),
        rx.form(
            rx.hstack(
                rx.input(
                    value=BrandConnectState.new_hashtag,
                    on_change=BrandConnectState.set_new_hashtag,
                    placeholder="Agrega un hashtag, ej. #streetfood",
                    width="100%",
                    size="2",
                    radius=_CONTROL_RADIUS,
                ),
                rx.icon_button(
                    rx.icon("plus", size=T.ICON_SM),
                    type="submit",
                    variant="soft",
                    color_scheme="gray",
                    size="2",
                    radius=_CONTROL_RADIUS,
                    aria_label="Agregar hashtag",
                ),
                spacing="2",
                width="100%",
            ),
            on_submit=BrandConnectState.add_hashtag,
            width="100%",
        ),
        rx.cond(
            BrandConnectState.hashtag_note != "",
            rx.text(BrandConnectState.hashtag_note, size="1", color=T.TEXT_MUTED),
            rx.cond(
                BrandConnectState.rubro_hashtags.length() > 0,
                rx.text(
                    "Buscaremos referentes con estos hashtags. Quita los que no encajen.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
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
#: `ACCOUNT_SETUP_INFO` follows: a first-time user reads this as the actual
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
    and the phased creator discovery (`_discovery_section`, filled in by
    `run_discovery` on the way in). Its own Finalizar-replacing CTA
    (`_finish_button`) lives in `_connect_controls`, not here — the fixed control bar,
    not the scrolling content, is what both flows' final screen shares that button
    through.

    The metrics are REAL (2026-09-10) and cover the last
    `scrapecreators_client.METRICS_WINDOW_DAYS` days: derived by `profile_metrics`
    from the post list `analyze()` read alongside the profile — see the comment
    above `_METRIC_ANIMATION_SECONDS`.
    The referentes below them are REAL since 2026-09-11 (they replaced the
    `COMPETITOR_SUGGESTIONS` placeholder here; the manual flow still shows it).

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
        _discovery_section(),
    )


def _discovery_account(item: rx.Var[dict[str, str]]) -> rx.Component:
    """One referente: the whole card links to the public profile (new tab). The
    picture comes through `_avatar` — the backend proxy, never the vendor's signed
    URL (which expires within hours and would leave a cached result full of broken
    pictures; see `avatar_proxy.py`)."""
    return rx.link(
        card(
            rx.hstack(
                _avatar(item, "2.5rem", 18),
                rx.vstack(
                    rx.hstack(
                        mono(item["handle"], size="2"),
                        tag(item["network"]),
                        rx.text(item["followers"], " seguidores", size="1", color=T.TEXT_MUTED),
                        rx.cond(
                            item["likes"] != "",
                            rx.text("♥ ", item["likes"], size="1", color=T.TEXT_MUTED),
                        ),
                        spacing="2",
                        align="center",
                        wrap="wrap",
                    ),
                    rx.cond(
                        item["blurb"] != "",
                        rx.text(item["blurb"], size="2", color=T.TEXT_MUTED),
                    ),
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
            interactive=True,
        ),
        href=item["url"],
        is_external=True,
        display="block",
        width="100%",
        text_decoration="none",
        color="inherit",
    )


def _discovery_phase(
    title: rx.Var[str] | str,
    fallback_title: str,
    note: rx.Var[str] | str,
    accounts: rx.Var[list[dict[str, str]]],
) -> rx.Component:
    """One phase block: its title, then its accounts — or, while nothing has landed
    yet, a small inline spinner (the run is still on an earlier phase or on this one),
    or the phase's own note once it finished empty."""
    return rx.vstack(
        rx.text(rx.cond(title != "", title, fallback_title), size="2", weight="bold"),
        rx.cond(
            accounts.length() > 0,
            rx.vstack(
                rx.foreach(accounts, _discovery_account),
                spacing="2",
                width="100%",
            ),
            rx.cond(
                note != "",
                rx.text(note, size="2", color=T.TEXT_FAINT),
                rx.cond(
                    BrandConnectState.discovering,
                    rx.hstack(
                        loading_spinner("sm"),
                        rx.text("Buscando…", size="2", color=T.TEXT_MUTED),
                        spacing="2",
                        align="center",
                    ),
                ),
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _discovery_section() -> rx.Component:
    """Referentes para tu marca (§ request 2026-09-11) — the phased search, rendered
    in the order it runs: sector → country → city. "Buscamos con" lists the signals
    the seed was built from, so an odd result can be traced to the bio line, category
    or hashtag that caused it. If the event never ran for this session (a dev reload
    straight onto this step), a button runs it instead of leaving the section blank.

    No "Referentes para tu marca" heading: dropped 2026-09-15 by request — the section
    opens straight on "Buscamos con"."""
    return rx.vstack(
        rx.cond(
            BrandConnectState.discovery_signals.length() > 0,
            rx.hstack(
                rx.text("Buscamos con", size="1", color=T.TEXT_MUTED),
                rx.foreach(BrandConnectState.discovery_signals, lambda chip: tag(chip)),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
        ),
        rx.cond(
            BrandConnectState.discovery_error != "",
            callout(BrandConnectState.discovery_error, "error"),
        ),
        rx.cond(
            ~BrandConnectState.discovery_ran,
            rx.button(
                rx.icon("search", size=T.ICON_SM),
                "Buscar referentes",
                variant="soft",
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandConnectState.run_discovery,
            ),
            rx.cond(
                BrandConnectState.has_sorted,
                rx.vstack(
                    # § request 2026-09-11: the summary is the operator's own sorting —
                    # referentes and competencia, each only when it has accounts; the
                    # detractores and whatever was left unsorted are omitted.
                    *(
                        rx.cond(
                            getattr(BrandConnectState, f"{key}_accounts").length() > 0,
                            _discovery_phase(
                                title, title, "", getattr(BrandConnectState, f"{key}_accounts")
                            ),
                        )
                        for key, title, _, _ in BUCKETS
                        if key != "detractor"
                    ),
                    spacing="4",
                    width="100%",
                ),
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
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


#: One lock per brand for `sync_labels`, so the writes of two quick decisions land in
#: the order they were made. Process-local, which is enough: a brand's sort is written
#: by the session walking its wizard.
_LABEL_LOCKS: dict[UUID, asyncio.Lock] = {}


def _labels_lock(brand_id: UUID) -> asyncio.Lock:
    return _LABEL_LOCKS.setdefault(brand_id, asyncio.Lock())


def _account_key(card: dict[str, str]) -> str:
    return f"{card.get('network', '')}:{card.get('handle', '')}"


#: The backend's origin, worked out in the browser the same way `rx.get_upload_url`
#: does (`getBackendURL(env.UPLOAD)` minus its `/_upload` path) — so a card's
#: `avatar_src` (`creator_discovery.avatar_path`, served by `avatar_proxy.py`) resolves
#: against whichever backend this frontend actually talks to, dev or deployed.
_AVATAR_BASE: rx.Var[str] = rx.Var(
    _js_expr='(String(getBackendURL(env.UPLOAD)).replace(/\\/_upload\\/?$/, ""))',
    _var_data=VarData(
        imports={
            f"$/{Dirs.STATE_PATH}": "getBackendURL",
            "$/env.json": ImportVar(tag="env", is_default=True),
        }
    ),
).to(str)


def _avatar(item: rx.Var[dict[str, str]], size: str, icon_size: int) -> rx.Component:
    """An account's round picture with the placeholder icon UNDER it: the `<img>`
    comes from the backend proxy (`item["avatar_src"]`) and carries an empty `alt`,
    so a picture the proxy cannot find (404) renders as nothing at all and the icon
    shows through — no broken-image glyph, no handler needed. `draggable="false"` +
    `pointer-events: none` keep the browser from starting a native IMAGE drag when the
    operator grabs a deck card by its picture (that would swallow the card's own
    drag)."""
    return rx.box(
        rx.icon("user-round", size=icon_size, color=T.TEXT_FAINT),
        rx.cond(
            item["avatar_src"] != "",
            rx.el.img(
                src=_AVATAR_BASE + item["avatar_src"],
                alt="",
                position="absolute",
                inset="0",
                width="100%",
                height="100%",
                object_fit="cover",
                border_radius="9999px",
                pointer_events="none",
                custom_attrs={
                    "loading": "lazy",
                    "referrerpolicy": "no-referrer",
                    "draggable": "false",
                },
            ),
        ),
        position="relative",
        width=size,
        height=size,
        min_width=size,
        border_radius="9999px",
        background=T.SURFACE_BG_RAISED,
        display="flex",
        align_items="center",
        justify_content="center",
        overflow="hidden",
        flex_shrink="0",
    )


def _deck_face(item: rx.Var[dict[str, str]]) -> rx.Component:
    """The face of a deck card — shared by the live card and its flying ghost."""
    return card(
        rx.vstack(
            _avatar(item, "4.5rem", 26),
            mono(item["handle"], size="3"),
            rx.hstack(
                tag(item["network"]),
                rx.text(item["followers"], " seguidores", size="1", color=T.TEXT_MUTED),
                rx.cond(
                    item["likes"] != "",
                    rx.text("♥ ", item["likes"], size="1", color=T.TEXT_MUTED),
                ),
                spacing="2",
                align="center",
                wrap="wrap",
                justify="center",
            ),
            rx.cond(
                item["blurb"] != "",
                rx.text(
                    item["blurb"],
                    size="2",
                    color=T.TEXT_MUTED,
                    text_align="center",
                    # clamped to 3 lines on a phone (`assets/qualify.css`)
                    class_name="q-deck-blurb",
                ),
            ),
            rx.hstack(
                rx.icon("external-link", size=14, color=T.TEXT_FAINT),
                rx.text("Toca para ver el perfil", size="1", color=T.TEXT_FAINT),
                spacing="1",
                align="center",
            ),
            rx.hstack(
                rx.icon("move", size=14, color=T.TEXT_FAINT),
                rx.text("Mantén presionado para arrastrar", size="1", color=T.TEXT_FAINT),
                spacing="1",
                align="center",
            ),
            spacing=rx.breakpoints(initial="2", sm="3"),
            align="center",
            width="100%",
        ),
        padding=rx.breakpoints(initial="1rem 0.75rem", sm="1.5rem 1.25rem"),
        width="100%",
        interactive=True,
    )


def _deck_card(item: rx.Var[dict[str, str]]) -> rx.Component:
    """The one account in the middle of the deck (§ request 2026-09-14: "dandole
    click se pueda ir a ver el perfil y el toque largo si el drag and drop"): a
    quick click/tap opens the profile in a new tab; holding it down arms the drag,
    and only THEN does moving it drag the card. Both are driven by
    `assets/deck-drag.js` off the `q-deck-card` class and the `data-profile-url`
    attribute — neither is something Reflex needs to see: opening the profile is a
    plain `window.open`, and the drag ends in a synthetic `drop` dispatched on
    whichever panel it lands on. Keyed by the account so every new card mounts fresh
    and plays `.q-deck-enter` (a settle plus one nudge left and right — the cue that
    it moves). `touch-action: none` is what lets a finger hold-and-drag it instead of
    the browser reading the hold as a page scroll; `user-select: none` keeps the
    press from selecting the handle's text."""
    return rx.box(
        _deck_face(item),
        class_name="q-deck-card q-deck-enter",
        key=item["key"],
        custom_attrs={"data-profile-url": item["url"]},
        cursor="pointer",
        touch_action="none",
        user_select="none",
        width="100%",
        max_width="20rem",
    )


def _deck_ghost() -> rx.Component:
    """The card that just left, flying out the way it went (§ request 2026-09-12,
    "una animación de drag and click"): mounted over the deck with `.q-fly-<dir>`,
    re-keyed by `fly_token` so each decision replays it; the animation ends
    invisible and inert, so nothing is left to clean up."""
    return rx.cond(
        BrandConnectState.fly_direction != "",
        rx.box(
            _deck_face(BrandConnectState.fly_card),
            class_name="q-deck-ghost q-fly-" + BrandConnectState.fly_direction,
            key=BrandConnectState.fly_token.to_string(),
            position="absolute",
            inset="0",
            display="flex",
            align_items="center",
            justify_content="center",
            pointer_events="none",
            width="100%",
            max_width="20rem",
            margin="0 auto",
        ),
    )


#: The three zones around the card — (bucket, title, blurb, arrow icon, grid area).
#: Referentes to the LEFT, Competencia to the RIGHT, Detractores BELOW, matching
#: `_FLY_DIRECTION`.
_DECK_ZONES: tuple[tuple[str, str, str, str, str], ...] = (
    ("referente", "Referentes", "Te inspiran", "arrow-left", "left"),
    ("competencia", "Competencia", "Tu misma audiencia", "arrow-right", "right"),
    ("detractor", "Detractores", "No van con tu marca", "arrow-down", "down"),
)
#: The sort step is not a field list: its three panels reach the card's own edges
#: (§ request 2026-09-14, "que ocupen hasta los bordes"), so `brand_connect_index`
#: lifts the 34rem column cap and tightens the card's padding for this one step.
_SORT_COLUMN_MAX = "100%"
_SORT_CARD_PADDING = "1rem"


def _deck_zone(bucket: str, title: str, blurb: str, arrow: str, area: str) -> rx.Component:
    """One of the three targets around the card — a whole PANEL, not a small box
    (§ request 2026-09-14: "que las flechas ocupen todo el espacio"): the arrow fills
    it, the panel is the drop target AND the tap target — a tap sends the card in the
    middle there (`send_current`), which is what the old row of buttons under the
    card did.

    No background at any state (§ request 2026-09-14: "quites el fondo de las
    opciones… en vez de eso que las letras y flecha sufran un scale"): the panel
    itself never tints in `assets/qualify.css` (`.q-deck-zone`) — only its text
    colour does, plus a keyboard `:focus-visible` outline (accessibility, not
    decoration). What used to be the panel's tint is now the arrow AND the label
    (`.q-deck-arrow` / `.q-deck-label`, the latter wrapping title + blurb as one
    block) POPPING — scaling up — while the dragged card is over this panel
    (`data-over`, set by `deck-drag.js`) and again, bigger, when it lands
    (`data-hit`, re-keyed by `fly_token` so every landing replays it — a second hit
    on the same zone included). The arrow's own idle animation is gone (§ request
    2026-09-14: "no quiero la animacion de las flechas parpadeando… solo quiero el
    scale cuando esté cerca la card a la opción") — `data-over`/`data-hit`'s pop is
    the only motion left on it, so `area` no longer needs to reach the CSS as a
    `data-dir` (it still names the grid cell)."""
    hit = BrandConnectState.hit_bucket == bucket
    side = area != "down"
    return _DropZone.create(
        rx.vstack(
            rx.icon(arrow, size=44, class_name="q-deck-arrow"),
            rx.vstack(
                rx.text(title, size="2", weight="bold", class_name="q-deck-zone-title"),
                rx.text(
                    blurb,
                    size="1",
                    color=T.TEXT_MUTED,
                    text_align="center",
                    class_name="q-deck-zone-blurb",
                ),
                spacing="1",
                align="center",
                class_name="q-deck-label",
            ),
            spacing="1",
            align="center",
            justify="center",
            width="100%",
        ),
        # `sync_labels` right after the decision: it stores the sort (§ referentes
        # persistence, migration 0020).
        on_click=[BrandConnectState.send_current(bucket), BrandConnectState.sync_labels],
        on_drop=[BrandConnectState.drop_into(bucket), BrandConnectState.sync_labels],
        type="button",
        aria_label=title,
        # `--side` / `--down` only matter on a phone (`assets/qualify.css`): the side
        # panels become thin strips with a vertical title, the bottom one a short row.
        class_name="q-deck-zone q-deck-zone--side" if side else "q-deck-zone q-deck-zone--down",
        custom_attrs={"data-hit": hit.to_string()},
        key=rx.cond(hit, "hit-" + BrandConnectState.fly_token.to_string(), bucket),
        grid_area=area,
        width="100%",
        height="100%",
        min_width="0",
        min_height=(
            rx.breakpoints(initial="12rem", sm="14rem")
            if side
            else rx.breakpoints(initial="4rem", sm="7rem")
        ),
        padding=rx.breakpoints(initial="0.5rem 0.25rem", sm="1rem 0.75rem"),
        display="flex",
        align_items="center",
        justify_content="center",
        font="inherit",
        color=T.TEXT_MUTED,
        border="none",
        border_radius=T.RADIUS_CARD,
        cursor="pointer",
    )


def _stage_nav_button(
    label: str, icon: str, handler: rx.event.EventHandler, **props
) -> rx.Component:
    return rx.button(
        *([rx.icon(icon, size=T.ICON_SM)] if icon == "chevron-left" else []),
        label,
        *([rx.icon(icon, size=T.ICON_SM)] if icon == "chevron-right" else []),
        variant="soft",
        size="2",
        radius=_CONTROL_RADIUS,
        on_click=handler,
        **props,
    )


def _connect_step_sort() -> rx.Component:
    """Referente, competencia o detractor (§ request 2026-09-11) as a DECK, one
    category at a time — the sector's accounts, then the country's, then the city's
    (`sort_stage`). One account sits in the middle; it goes LEFT to Referentes,
    RIGHT to Competencia, DOWN to Detractores, by dragging the card onto that side
    or with the three arrow buttons under it; Omitir shows the next one, Deshacer
    brings the last one back. Each category is its own deck and its own three
    buckets, so a category whose search failed shows a Reintentar and never blocks
    the others. Entirely optional: nothing here gates Continuar."""
    # Anterior/Siguiente sit ON the same line as "Categoría N de 3" + its title, never
    # under it (§ request 2026-09-15). That means NO `wrap="wrap"` here: the text column
    # is the one that gives way (`min_width=0`, so the title wraps inside it) while the
    # buttons keep their intrinsic width (`flex_shrink=0`) — which is what keeps them
    # from overlapping the text at any width instead of pushing them to a second row.
    stage_header = rx.hstack(
        rx.vstack(
            _section_label(BrandConnectState.stage_label),
            rx.text(BrandConnectState.stage_title, size="3", weight="bold"),
            spacing="1",
            align_items="start",
            min_width="0",
            flex="1 1 auto",
        ),
        rx.cond(
            ~BrandConnectState.is_first_stage,
            _stage_nav_button(
                "Anterior",
                "chevron-left",
                BrandConnectState.prev_sort_stage,
                flex_shrink="0",
            ),
        ),
        rx.cond(
            ~BrandConnectState.is_last_stage,
            _stage_nav_button(
                "Siguiente",
                "chevron-right",
                BrandConnectState.next_sort_stage,
                flex_shrink="0",
            ),
        ),
        spacing="2",
        align="center",
        wrap="nowrap",
        width="100%",
    )
    middle = rx.cond(
        BrandConnectState.has_current_card,
        rx.vstack(
            _deck_card(BrandConnectState.current_card),
            rx.text(
                BrandConnectState.stage_remaining.to_string(),
                " por ordenar",
                size="1",
                color=T.TEXT_FAINT,
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        rx.cond(
            BrandConnectState.stage_pending,
            rx.hstack(
                loading_spinner("sm"),
                rx.text("Buscando cuentas de esta categoría…", size="2", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
            rx.cond(
                BrandConnectState.stage_failed,
                rx.vstack(
                    rx.text(BrandConnectState.stage_note, size="2", color=T.TEXT_MUTED),
                    rx.button(
                        rx.icon("refresh-cw", size=T.ICON_SM),
                        "Reintentar",
                        variant="soft",
                        size="1",
                        radius=_CONTROL_RADIUS,
                        on_click=BrandConnectState.retry_phase(BrandConnectState.stage_key),
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.cond(
                    BrandConnectState.stage_note != "",
                    rx.text(BrandConnectState.stage_note, size="2", color=T.TEXT_MUTED),
                    rx.text("Todas clasificadas.", size="2", color=T.TEXT_MUTED),
                ),
            ),
        ),
    )
    zones = {spec[-1]: _deck_zone(*spec) for spec in _DECK_ZONES}
    return _step_body(
        rx.cond(
            BrandConnectState.discovery_error != "",
            callout(BrandConnectState.discovery_error, "error"),
        ),
        stage_header,
        # A named-area grid: the two side panels stretch to the card's full height and
        # the bottom one spans all three columns — every zone is as big as the space
        # around the card allows. SAME spatial layout at every width (§ request
        # 2026-09-14, "adáptalo a móviles"): a phone keeps Referentes LEFT, Competencia
        # RIGHT and Detractores BELOW — the directions the card is dragged in — with the
        # side panels narrowed to thin strips (vertical label, `assets/qualify.css`)
        # so the card keeps most of the width. It used to stack everything in one
        # column below 62em, which put Detractores off-screen and made "drag it down"
        # impossible on a phone.
        rx.box(
            zones["left"],
            rx.box(
                middle,
                _deck_ghost(),
                grid_area="card",
                position="relative",
                display="flex",
                align_items="center",
                justify_content="center",
                width="100%",
                min_width="0",
                min_height=rx.breakpoints(initial="12rem", sm="16rem"),
            ),
            zones["right"],
            zones["down"],
            display="grid",
            grid_template_columns=rx.breakpoints(
                initial="2.75rem minmax(0, 1fr) 2.75rem", sm="1fr 1.6fr 1fr"
            ),
            grid_template_areas='"left card right" "down down down"',
            # the first row takes whatever height the card leaves free, so the two
            # side panels run from the header down to the bottom panel
            grid_template_rows=rx.breakpoints(
                initial="minmax(12rem, 1fr) auto", sm="minmax(16rem, 1fr) auto"
            ),
            gap=rx.breakpoints(initial="0.5rem", sm="0.75rem"),
            width="100%",
            flex="1",
        ),
        rx.hstack(
            rx.button(
                rx.icon("undo-2", size=T.ICON_SM),
                "Deshacer",
                variant="ghost",
                size="1",
                radius=_CONTROL_RADIUS,
                on_click=[BrandConnectState.undo_last, BrandConnectState.sync_labels],
                disabled=~BrandConnectState.can_undo,
            ),
            rx.button(
                "Omitir",
                rx.icon("skip-forward", size=T.ICON_SM),
                variant="ghost",
                size="1",
                radius=_CONTROL_RADIUS,
                on_click=BrandConnectState.skip_card,
                disabled=~BrandConnectState.has_current_card,
            ),
            spacing="2",
            align="center",
            justify="center",
            width="100%",
        ),
        icon="layout-grid",
        grow=True,
    )


def _connect_window() -> rx.Component:
    """One renderer per `CONNECT_STEPS` index, all by name. Which of them a session
    actually reaches is `BrandConnectState._is_skipped`'s call — every step still
    needs a renderer for the sessions where it is shown. The kit-setup steps reuse the
    manual flow's renderers, so the shared half of the two paths is literally the
    same code."""
    return rx.match(
        BrandConnectState.step,
        (0, _connect_step_network()),
        (1, _connect_step_username()),
        (_PROFILE_STEP, _connect_step_profile()),
        (_RECOMMENDATIONS_STEP, _connect_step_recommendations()),
        (_ACCOUNT_KIND_STEP, _connect_step_account_kind()),
        (_RUBRO_STEP, _connect_step_rubro()),
        (_MAPS_QUESTION_STEP, _connect_step_has_maps()),
        (_MAPS_STEPS_STEP, _connect_step_maps_setup()),
        (_LOGO_QUESTION_STEP, _connect_step_has_logo()),
        (_LOGO_UPLOAD_STEP, _step_logo(BrandConnectState.next_step)),
        (_IDENTITY_STEP, _step_identity()),
        (_PALETTE_STEP, _step_palette()),
        (_VOICE_TONE_STEP, _step_voice_tone()),
        (_VOICE_EXAMPLES_STEP, _step_voice_examples()),
        (_RESTRICTIONS_STEP, _step_restrictions()),
        (_CONNECT_CONFIRM_STEP, _step_confirm()),
        (_SORT_STEP, _connect_step_sort()),
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


def _discovery_progress_row(row: rx.Var[dict[str, str]]) -> rx.Component:
    return rx.hstack(
        rx.match(
            row["status"],
            ("done", rx.icon("circle-check", size=16, color=T.tone_color("ok", 10))),
            ("running", loading_spinner("sm")),
            rx.icon("circle", size=16, color=T.TEXT_FAINT),
        ),
        rx.text(
            row["title"],
            size="2",
            color=rx.cond(row["status"] == "pending", T.TEXT_FAINT, T.TEXT_STRONG),
            weight=rx.cond(row["status"] == "running", "medium", "regular"),
        ),
        spacing="2",
        align="center",
    )


def _referentes_loading() -> rx.Component:
    """The loading screen in front of Referente, competencia o detractor while the
    search is still running (`BrandConnectState.waiting_for_referentes`) — no deck
    and no Atrás/Continuar under it, so the step cannot be skipped half-loaded. Lists
    the three categories with a check for each one already found, so a long wait
    visibly moves. It clears on its own when the last category lands."""
    return rx.vstack(
        loading_spinner("lg"),
        rx.text("Buscando referentes para tu marca", size="2", weight="medium"),
        rx.text(
            "En cuanto termine podrás clasificarlos. Puede tardar unos minutos.",
            size="1",
            color=T.TEXT_MUTED,
            text_align="center",
        ),
        rx.vstack(
            rx.foreach(BrandConnectState.discovery_progress, _discovery_progress_row),
            spacing="2",
            align_items="start",
            padding_top="0.5rem",
        ),
        spacing="3",
        align="center",
        width="100%",
        padding="3rem 0",
    )


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
        # A brandboard carries the logo too (§ request 2026-09-25): either file will do.
        (BrandWizardState.logo_key != "")
        | (brand_documents.BrandDocumentState.brandboard_key != ""),
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
    this gate, on step CONNECT_LAST). Shared steps (identidad, logo, paleta,
    voz · ejemplos) read the SAME `BrandWizardState`/`CreativeState` fields the
    manual flow's own `_manual_can_continue` checks — the two functions stay
    side by side with it so a future reorder of either STEPS tuple is easy to keep
    in sync. Tu rubro y ubicación needs a rubro always, and país + ciudad unless the
    account is a creator (`rubro_complete`)."""
    return rx.match(
        BrandConnectState.step,
        (0, BrandConnectState.network != ""),
        (1, BrandConnectState.username != ""),
        (_ACCOUNT_KIND_STEP, BrandConnectState.account_kind != ""),
        (_RUBRO_STEP, BrandConnectState.rubro_complete),
        (_MAPS_QUESTION_STEP, BrandConnectState.has_maps != ""),
        (_LOGO_QUESTION_STEP, BrandWizardState.has_logo != ""),
        (_LOGO_UPLOAD_STEP, _logo_step_complete()),
        (_IDENTITY_STEP, _identity_complete()),
        (_PALETTE_STEP, CreativeState.kit_palette != ""),
        (_VOICE_EXAMPLES_STEP, CreativeState.kit_do_examples != ""),
        True,
    )


def _connect_controls() -> rx.Component:
    """Same quiet chrome as the manual flow, with three exceptions: the username
    screen's Continue kicks off the analysis instead of stepping; the last screen
    before the shared kit-setup steps begin (§ `shows_cancel`) offers Cancel rather
    than Back; and the sort step's Continue kicks off the metric count-up
    (`advance_to_insights`) instead of a plain step (the creator discovery itself
    started long before, at the profile read). `right`'s Resultados e insights branch is
    `_finish_button` — it replaces
    Finalizar entirely (§ request 2026-09-05), not alongside it. `back` is never
    disabled: `prev_step` redirects to `/brand` once already at step 0.

    Every forward button (Analizar/Continuar, not `_finish_button` — Confirmación
    already passed this gate) carries `disabled=~_connect_can_continue()` (§ request
    2026-09-09): a choice step with nothing selected, or a required field left
    empty, no longer lets Continuar through un-set."""
    forward_disabled = ~_connect_can_continue()
    left = rx.cond(
        BrandConnectState.shows_cancel,
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
        _finish_button(
            [
                CreativeState.save_kit_form,
                brand_documents.BrandDocumentState.reset_documents,
                BrandConnectState.finish_to_signals,
            ]
        ),
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
                BrandConnectState.step == _SORT_STEP,
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
                        rx.cond(
                            # The sort step waits for the whole search behind its own
                            # loading screen — no controls, so it cannot be skipped.
                            BrandConnectState.waiting_for_referentes,
                            card(
                                _referentes_loading(),
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
                                    # The deck (three panels around a card) needs more room
                                    # than a field list; every other step keeps the 34rem.
                                    max_width=rx.cond(
                                        BrandConnectState.step == _SORT_STEP,
                                        _SORT_COLUMN_MAX,
                                        "34rem",
                                    ),
                                    align_self="center",
                                    align_items="center",
                                    flex="1",
                                    justify_content="center",
                                ),
                                _connect_controls(),
                                padding=rx.cond(
                                    BrandConnectState.step == _SORT_STEP,
                                    _SORT_CARD_PADDING,
                                    "1.75rem",
                                ),
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
                ),
                spacing="4",
                width="100%",
                flex="1",
                min_height="0",
            ),
        ),
    )
