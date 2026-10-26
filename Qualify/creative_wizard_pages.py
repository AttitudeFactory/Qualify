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

    1 Brief            2 Identidad       3 ¿Tienes brandboard?  4 Brandboard (on 3)
    5 Paleta           6 Voz · tono      7 Voz · ejemplos       8 Restricciones
    9 Confirmación     10 Resultados

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
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.auth import SIGNUP_ROUTE
from qualify_api.claude_tools import api_key_from_env
from qualify_api.creative import brand_prefill, kept_pictures, logo_palette
from qualify_api.hashtags import catalog as hashtag_catalog
from qualify_api.hashtags import fold, from_profile, normalize_tag
from qualify_api.referentes import discovery_seed, scrapecreators_client
from qualify_creative.brand import fonts as brand_fonts
from reflex.constants import Dirs
from reflex.utils.imports import ImportVar
from reflex.vars import VarData
from sqlalchemy.exc import SQLAlchemyError

from . import (
    avatar_proxy,
    brand_documents,
    creator_cache_provider,
    creator_discovery,
    creator_pool_provider,
    growth_provider,
    referentes_provider,
    referentes_review,
)
from .auth_state import BRAND_READY_QUERY, AuthState, brand_tenant_id
from .connections_provider import acting_user_id
from .creative_provider import default_brand_id
from .creative_state import CreativeState
from .r2_media import BACKEND_BASE, issue_view_path
from .tenant import tenant_uuid
from .ui import (
    DragCard,
    app_shell,
    asset_script,
    callout,
    card,
    choice_card,
    choice_card_check,
    dropzone,
    loading_spinner,
    media_thumb,
    mono,
    page_body,
    page_header,
    progress_panel,
    qualify_mark,
    removable_pill,
    skeleton_card,
    step_foot,
    step_frame,
    step_head,
    step_sync,
    tag,
    tone_badge,
)
from .ui import tokens as T
from .ui.steps_vm import (
    DIR_BACK,
    DIR_NEXT,
    NEXT_LABEL,
    STEP_PARAM,
    guard_step,
    parse_step_param,
    step_direction,
    step_position,
)
from .upload_names import safe_upload_name as _safe_upload_name
from .voice_lab import voice_analysis_result, voice_lab_panel

logger = logging.getLogger(__name__)

#: Fire-and-forget work started by a state handler (the AI classification of the hashtag
#: catalog). Held here so the event loop keeps a strong reference until it finishes.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _finish_background_task(task: asyncio.Task) -> None:
    _BACKGROUND_TASKS.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("background task failed: %s", task.exception())


_NO_SESSION = "Tu sesión se cerró. Vuelve a entrar para seguir."
_UPLOAD_FAILED = "No se pudo leer el archivo. Inténtalo de nuevo."
_FONT_TOO_LARGE = (
    f"El archivo de fuente pesa más de {brand_fonts.MAX_FONT_BYTES // (1024 * 1024)} MB."
    " Sube solo el peso que usas (TTF, OTF o WOFF)."
)

# Title + one-line subtitle per step. The index IS the cursor value, so this tuple is
# the single source of truth for the counter and the heading.
#
# § request 2026-10-05, the wizard slimmed down — gone from BOTH flows:
# - Tu brief de marca as its own view: it is now the top of ¿Quién es la marca?
#   (`_IDENTITY_HEADING`), and what it says goes straight into the fields.
# - Tu voz and ¿Cómo suena?: configured later, from the Brand Kit editor (/brand/kit)
#   — "las guardamos aparte, porque quiero que se pueda configurar después".
# - Enséñale a hablar and Lo que nunca debe decir: their five lists are filled on
#   ¿Todo correcto?, with examples, instead of on two screens of their own.
# - (connect flow only) Lo que te proponemos and the two Google Maps views.

#: ¿Quién es la marca?'s heading — one constant, both flows. Carries the brief now.
_IDENTITY_HEADING = (
    "¿Quién es la marca?",
    "Qué te hace distinto y quién te compra. Si tienes un documento de tu marca, súbelo "
    "y lo completamos.",
)

#: Tipografía's title + subtitle, shared by the three flows so the copy cannot drift.
_TYPOGRAPHY_HEADING = ("Tipografía", "La letra con la que se te reconoce, antes que el color.")
STEPS: tuple[tuple[str, str], ...] = (
    _IDENTITY_HEADING,
    ("¿Ya tienes logo?", "De tu respuesta depende el siguiente paso."),
    ("Tu logo", "Lo usaremos en cada publicación que crees."),
    # Tipografía — its own view right before Paleta de colores (§ request 2026-10-05):
    # the family names (and, optionally, the files) of the brand's type faces, editable
    # whether or not a brandboard was uploaded. Optional: nothing blocks Continuar.
    _TYPOGRAPHY_HEADING,
    ("Paleta de colores", "Los colores con los que se te reconoce."),
    ("¿Todo correcto?", "Revisa, completa los ejemplos y las reglas, y guarda."),
    ("Así quedó tu marca", "Revisa y termina."),
)
LAST_STEP = len(STEPS) - 1
#: The manual flow's steps a rule names (the rest are read off `_window`).
_M_IDENTITY_STEP = 0
_M_HAS_LOGO_STEP = 1
_M_LOGO_STEP = 2
_M_TYPOGRAPHY_STEP = 3
_M_PALETTE_STEP = 4
assert STEPS[_M_IDENTITY_STEP] == _IDENTITY_HEADING
assert STEPS[_M_LOGO_STEP][0] == "Tu logo"
assert STEPS[_M_TYPOGRAPHY_STEP] == _TYPOGRAPHY_HEADING
assert STEPS[_M_PALETTE_STEP][0] == "Paleta de colores"
assert _M_TYPOGRAPHY_STEP + 1 == _M_PALETTE_STEP
#: ¿Todo correcto? — one before the true final screen. `resume` opens here on a kit
#: with no gaps, not on `LAST_STEP`: re-entering should offer a review, not skip
#: straight past it to the "you're done" screen.
_CONFIRM_STEP = LAST_STEP - 1

# `rx.upload`'s id must be a string literal or a module-level constant — it is what
# links the dropzone to `rx.upload_files(upload_id=...)`.
#: Tu brandboard's "+" (§ request 2026-09-29): stickers, patterns, a mascot... Several
#: files may be dropped at once; each becomes its own element.
_EXTRA_UPLOAD_ID = "brand_extra"
_MAX_EXTRAS_PER_DROP = 10
#: What a logo version's card and the "+" take — an image.
#: `detect_fonts`'s notes (Spanish, product voice).
_FONTS_NEED_LOGO = "Sube primero una versión de tu logo: de ahí leemos la tipografía."
_FONTS_NO_KEY = (
    "Ahora no podemos leer la tipografía de tu logo. Escríbela tú o inténtalo más tarde."
)
_FONTS_NO_IMAGE = "No podemos leer la tipografía de un SVG: sube una versión en PNG, JPG o WebP."
_FONTS_FAILED = "No pudimos leer la tipografía de tu logo. Escríbela o inténtalo de nuevo."
#: What reading an uploaded font FILE found (§ request 2026-10-05, `check_font_file`).
_FONT_FILE_UNNAMED = "No pudimos leer el nombre de la fuente en el archivo. Escríbelo tú."


def font_file_message(family: str, open_source: bool | None) -> tuple[str, str]:
    """The toast after a font file is read: its family, and whether it is open source
    (on Google Fonts) — `(message, tone)` for `brand_documents.notify`."""
    if not family:
        return _FONT_FILE_UNNAMED, "info"
    if open_source is True:
        return (
            f"Detectamos «{family}» en tu archivo. Es de uso libre: está en Google Fonts.",
            "ok",
        )
    if open_source is False:
        return (
            f"Detectamos «{family}» en tu archivo. No está en Google Fonts: usaremos tu archivo.",
            "info",
        )
    return f"Detectamos «{family}» en tu archivo.", "info"


def _read_logo_files(tenant_id: UUID | None, keys: list[str]) -> list[tuple[str, bytes]]:
    """The bytes behind each staged logo version — a local upload, or the R2 object a
    previous save moved it to (read through the tenant-checked gate). Off the event
    loop (`detect_fonts`). A file that cannot be read is skipped, not fatal."""
    from .brand_finish import _r2_gate
    from .r2_media import is_r2_key

    files: list[tuple[str, bytes]] = []
    gate = None
    for key in keys:
        try:
            if is_r2_key(key):
                if tenant_id is None:
                    continue
                gate = gate or _r2_gate()
                data = gate.open_object(tenant_id, key).read()
            else:
                data = (rx.get_upload_dir() / key).read_bytes()
        except Exception as exc:  # noqa: BLE001 — one unreadable version must not void the rest
            logger.warning("brand fonts: %s unreadable: %s", key, type(exc).__name__)
            continue
        files.append((Path(key).name, data))
    return files


_LOGO_VERSION_ACCEPT = {"image/*": [".png", ".jpg", ".jpeg", ".webp", ".svg"]}
#: What a typography tile's dropzone takes — a font file (§ request 2026-10-05). The
#: browser reports fonts under several MIME types (or none), so the extensions are what
#: actually matches.
_FONT_ACCEPT = {
    "font/ttf": [".ttf"],
    "font/otf": [".otf"],
    "font/woff": [".woff"],
    "font/woff2": [".woff2"],
}

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


def manual_completes(
    *,
    positioning: str,
    audience: str,
    has_logo: str,
    has_files: bool,
    brief: str,
    palette: str,
) -> list[bool]:
    """Whether each of the manual flow's seven steps is answered, in order — the same
    gates as `_manual_requirement` — so `?paso=N` never opens past an unanswered one
    (PASOS-4, `steps_vm.guard_step`). Tipografía, ¿Todo correcto? and Así quedó ask
    for nothing."""
    logo_done = has_files if has_logo == "si" else bool(brief.strip())
    return [
        bool(positioning.strip() and audience.strip()),
        has_logo != "",
        logo_done,
        True,
        bool(palette.strip()),
        True,
        True,
    ]


class BrandWizardState(rx.State):
    """The cursor, plus the fields this screen adds that `CreativeState` has no home for.

    Existing kit fields stay in `CreativeState` — a wizard is a navigation concern, not
    a second copy of the record. What lives here is only what is genuinely new.

    Setters are explicit: this Reflex version generates none, the same reason
    `CreativeState` writes its own.
    """

    step: int = 0
    #: PASOS-4 (m-24852243): `data-dir` of the step frame's body, and whether `resume`
    #: has decided the step (until then the address is not written — `step_sync`).
    direction: str = DIR_NEXT
    steps_ready: bool = False

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
    #: One staged file per version of the logo (`LOGO_VERSIONS` key → upload key),
    #: dropped on its own card on Tu brandboard (§ request 2026-09-29). Session-only,
    #: like `logo_key`.
    logo_versions: dict[str, str] = {}
    #: What the operator wrote about each staged version (key → free text): when and how
    #: to use it (§ request 2026-09-29, "que se pueda poner un contexto de esto subido").
    logo_version_context: dict[str, str] = {}
    #: Anything else the brand is made of, added with Tu brandboard's "+" (stickers,
    #: patterns, a mascot...): one dict per file — `id`, `key` (upload key), `name`
    #: (file name), `label` (what it is) and `context`.
    brand_extras: list[dict[str, str]] = []
    #: The font file dropped on each typography tile (`FONT_SLOTS` key → upload key, or
    #: R2 key once saved), § request 2026-10-05. The family NAMES are kit fields
    #: (`CreativeState.kit_font_heading` / `kit_font_body`); only the optional file is here.
    font_files: dict[str, str] = {}
    #: "Detectar desde tu logo" (`detect_fonts`) in flight, and what it had to say.
    detecting_fonts: bool = False
    font_note: str = ""
    font_note_tone: str = "info"
    #: Since 2026-10-01 all of the above is SAVED at the end (`brand_finish`) and read
    #: back on entry (`load_saved_assets`): a saved file's key is an R2 key, shown
    #: through its short-lived `/r2media/<token>` path kept here (R2 key → path).
    asset_views: dict[str, str] = {}
    #: Save-as-you-go in flight (`brand_finish.save_progress`), shared by both flows.
    _progress_saving: bool = False
    #: `load_saved_assets` finished: until then a save would drop the stored brandboard
    #: (the save replaces the whole stored set), so save-as-you-go waits for it.
    _assets_loaded: bool = False

    @rx.event(background=True)
    async def persist_progress(self) -> None:
        """Fired each time the manual flow's step changes (§ request 2026-10-02): the
        half-written kit and the position go to the database."""
        from .brand_finish import MANUAL_FLOW, save_progress

        await save_progress(self, MANUAL_FLOW)

    # -- step 5 -----------------------------------------------------------------------
    # The wheel/readout's pending pick. They ONLY ever add a new colour — nothing here
    # is shared with editing an existing one (see `set_swatch_color`), so there is no
    # hidden mode to get wrong: the wheel always appends, a swatch always edits itself.
    picker_color: str = "#0A3D2E"
    # m-24842965 (N3, docs/ux-guia-navegacion.md): the achievement card «Tu marca está
    # lista», shared by BOTH flows' pages. Raised by `_finish_navigation` when a session
    # WITH an account finishes either flow; while it is up, `brand_manual_index`/
    # `brand_connect_index` show the card instead of the steps (`_or_ready_frame`). Cleared
    # when the owner leaves through it and on every entry to a wizard page (`resume`,
    # `BrandConnectState.load_saved_details`), so coming back later opens the steps,
    # not a stale card. Not touched by `_reset_fields`: `finish` resets, THEN raises it.
    brand_ready: bool = False

    @rx.event
    def leave_brand_ready(self, route: str) -> rx.event.EventSpec:
        """Close the card and go — only to one of the card's own routes (the route
        arrives from the client)."""
        self.brand_ready = False
        return rx.redirect(route if route in _READY_ROUTES else _READY_BRAND_ROUTE)

    @rx.event
    def hide_brand_ready(self) -> None:
        """The «Ver mi marca» link navigates on its own (a real anchor); this only
        closes the card behind it."""
        self.brand_ready = False

    @rx.var
    def step_n(self) -> int:
        """«Paso N de 7» and `?paso=N` (every step of this flow is shown)."""
        return self.step + 1

    @rx.var
    def is_last(self) -> bool:
        return self.step == LAST_STEP

    async def _completes(self) -> list[bool]:
        creative = await self.get_state(CreativeState)
        return manual_completes(
            positioning=creative.kit_positioning,
            audience=creative.kit_audience,
            has_logo=self.has_logo,
            has_files=bool(self.logo_versions or self.brand_extras),
            brief=self.logo_brief_1,
            palette=creative.kit_palette,
        )

    def _go(self, index: int) -> None:
        index = max(0, min(index, LAST_STEP))
        self.direction = step_direction(self.step + 1, index + 1, self.direction)
        self.step = index

    @rx.event
    def leave_frame(self) -> None:
        """The frame unmounted: the next visit writes no address until `resume`."""
        self.steps_ready = False

    @rx.event
    async def pop_step(self) -> None:
        """The browser's «atrás»/«adelante» (`step_frame(on_pop=...)`): the step in
        `?paso=`, never past the first step still unanswered. Idempotent."""
        raw = step_param(self)
        if raw is None or not self.steps_ready:
            return
        target = guard_step(parse_step_param(raw, len(STEPS)), await self._completes())
        self._go(target - 1)

    @rx.event
    def primary(self) -> rx.event.EventSpec | None:
        """The frame's primary: «Siguiente», or the finish on the last step."""
        if self.step == LAST_STEP:
            return BrandWizardState.finish
        self._go(self.step + 1)
        return None

    @rx.event(background=True)
    async def save_for_later(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Seguir después»: save, then Inicio (an account) — `leave_flow`."""
        from .brand_finish import MANUAL_FLOW

        async for event in leave_flow(self, MANUAL_FLOW, later=True):
            yield event

    @rx.event(background=True)
    async def leave(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """The head's «‹ Inicio» / «‹ Tu correo»: save, then go — `leave_flow`."""
        from .brand_finish import MANUAL_FLOW

        async for event in leave_flow(self, MANUAL_FLOW, later=False):
            yield event

    @rx.event
    async def resume(self) -> None:
        """Open the flow on the FIRST step still missing data, not wherever the cursor
        happened to be left. Runs on page load, after `CreativeState.load_brand` has
        filled the kit — so re-entering never parks you on step 6 while step 2 is empty.

        Tipografía is optional, so it is never a gap. A kit with no gaps left opens on the
        confirmation screen (`_CONFIRM_STEP`) — also when its examples are still empty:
        since 2026-10-05 that is where they are filled. Not on `LAST_STEP` — Resultados
        e insights is a destination, not something to resume into.
        """
        # m-24842965: entering the wizard opens the steps, never a card left from before
        # — unless the signup that adopted this draft sent the owner here for the card
        self.steps_ready = False
        self.brand_ready = _asks_for_ready_card(self)
        creative = await self.get_state(CreativeState)
        # ¿Quién es la marca? carries the brief (§ request 2026-10-05): an empty or
        # half-filled identity opens there, where a brief can fill most of what follows.
        if not creative.kit_positioning.strip() or not creative.kit_audience.strip():
            self.step = _M_IDENTITY_STEP
        elif not self.has_logo:
            self.step = _M_HAS_LOGO_STEP
        elif self.has_logo == "si" and not self.logo_versions and not self.brand_extras:
            self.step = _M_LOGO_STEP
        elif self.has_logo == "no" and not self.logo_brief_1.strip():
            self.step = _M_LOGO_STEP
        elif not creative.kit_palette.strip():
            self.step = _M_PALETTE_STEP
        else:
            self.step = _CONFIRM_STEP
        # PASOS-4: `?paso=N` (a reload, the browser's «atrás», a shared link) opens that
        # step — never past the first one still unanswered (`guard_step`)
        raw = step_param(self)
        if raw is not None:
            target = guard_step(parse_step_param(raw, len(STEPS)), await self._completes())
            self.step = target - 1
        self.direction = DIR_NEXT
        self.steps_ready = True

    @rx.event
    def go_to(self, index: int) -> None:
        """Jump straight to a step. Clamped so a stale client event cannot park the
        cursor outside the flow and render nothing."""
        self._go(index)

    @rx.event
    def next_step(self) -> None:
        self._go(self.step + 1)

    @rx.event
    def prev_step(self) -> rx.event.EventSpec | None:
        """Atrás from the very first step leaves the wizard — there is no step -1 to
        land on, so "back" means back to the fork, not a disabled button. (The step
        frame shows no «Atrás» on step 1: the way out is the head's «‹ Inicio».)"""
        if self.step == 0:
            return rx.redirect("/brand")
        self._go(self.step - 1)
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
        self.logo_versions = {}
        self.logo_version_context = {}
        self.brand_extras = []
        self.font_files = {}
        self.detecting_fonts = False
        self.font_note = ""
        self.asset_views = {}
        self.picker_color = "#0A3D2E"

    @rx.event(background=True)
    async def load_saved_assets(self) -> AsyncIterator[None]:
        """On entry: the brand's saved brandboard and logo brief (`brand_finish.
        load_saved`), merged under what this session already staged — a slot the
        session filled keeps the session's file. The save replaces the whole stored
        set, so everything stored has to be here for it not to be dropped."""
        from .brand_finish import load_saved, session_ids

        ids = await session_ids(self)
        if ids is None:
            return
        try:
            saved = await asyncio.to_thread(load_saved, ids[0], ids[1])
        except SQLAlchemyError as exc:
            logger.warning("brand kit assets unreadable: %s", type(exc).__name__)
            return
        async with self:
            versions = dict(self.logo_versions)
            contexts = dict(self.logo_version_context)
            extras = list(self.brand_extras)
            fonts = dict(self.font_files)
            known_extras = {extra["id"] for extra in extras}
            for file in saved.files:
                if file.kind == "logo" and not self.logo_key:
                    self.logo_key, self.logo_name = file.key, file.name
                elif file.kind == "logo_version" and file.slot not in versions:
                    versions[file.slot] = file.key
                    if file.context:
                        contexts.setdefault(file.slot, file.context)
                elif file.kind == "font" and file.slot not in fonts:
                    fonts[file.slot] = file.key
                elif file.kind == "extra" and file.slot not in known_extras:
                    extras.append(
                        {
                            "id": file.slot,
                            "key": file.key,
                            "name": file.name,
                            "label": file.label,
                            "context": file.context,
                        }
                    )
            self.logo_versions = versions
            self.logo_version_context = contexts
            self.brand_extras = extras
            self.font_files = fonts
            self.asset_views = {**self.asset_views, **saved.views}
            if saved.files and not self.has_logo:
                self.has_logo = "si"
            brief = saved.details.logo_brief
            if not (self.logo_brief_1 or self.logo_brief_2 or self.logo_brief_3):
                self.logo_brief_1 = str(brief.get("style", ""))
                self.logo_brief_2 = str(brief.get("feeling", ""))
                self.logo_brief_3 = str(brief.get("references", ""))
            # save-as-you-go may write the brandboard from now on: what was stored is here
            self._assets_loaded = True

    @rx.event(background=True)
    async def finish(self) -> AsyncIterator[rx.event.EventSpec]:
        """The manual flow's final button (§ request 2026-10-01): save EVERYTHING
        (`brand_finish.save_brand_kit`) and only then move on — a failed save stays on
        screen instead of being lost behind the redirect."""
        from .brand_finish import MANUAL_FLOW, save_brand_kit

        if not await save_brand_kit(self, MANUAL_FLOW):
            await _explain_finish_failure(self)
            return
        async with self:
            self._reset_fields()
            navigation = await _finish_navigation(self)
        yield brand_documents.BrandDocumentState.reset_documents
        if navigation is not None:
            yield navigation

    @rx.event
    async def finish_to_signals(self) -> rx.event.EventSpec | None:
        """The final button («Terminar mi marca»), on this flow's own Resultados e
        insights — the TRUE final screen. Replaces Finalizar entirely (§ request
        2026-09-05): fired REGARDLESS of what `save_kit_form` does — for now this is
        the whole "save", simulated (there is no success/failure branch to key off
        yet). The actual kit content (`CreativeState`'s fields) is untouched; only
        this screen's own navigation/staging state resets, same shape
        `BrandConnectState.finish_to_signals` uses for the connect flow."""
        self._reset_fields()
        return await _finish_navigation(self)

    @rx.event
    def answer_has_logo(self, value: str) -> None:
        """Answering step 2 moves straight on — the question has no other content, so
        making the user press Next again would be a dead click."""
        self.has_logo = value
        self._go(self.step + 1)

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
        served to another. No screen drops a file here since 2026-09-29 (Tu brandboard
        takes only the logo versions and extras now); kept for its palette wiring.
        """
        staged = await self._stage_logo_file(files, "logo")
        if staged is None:
            return
        key, name, data = staged
        self.logo_key = key
        self.logo_name = name
        await self.apply_logo_colours(data, LOGO_SOURCE_UPLOAD)

    @rx.event
    async def handle_logo_version_upload(self, files: list[rx.UploadFile], version: str) -> None:
        """Stage one version of the logo (Logotipo, Isotipo, ...) dropped on its own card
        on Tu brandboard (§ request 2026-09-29). Its colours go into the palette when it is
        the brand's fullest mark so far (`_palette_version`) — § 2026-10-01: they used not
        to, and since Tu brandboard takes only versions and extras, no upload ever
        coloured the palette any more."""
        if version not in LOGO_VERSION_KEYS:
            return
        staged = await self._stage_logo_file(files, f"logo/{version}")
        if staged is None:
            return
        self.logo_versions = {**self.logo_versions, version: staged[0]}
        if self._palette_version() == version:
            await self.apply_logo_colours(staged[2], LOGO_SOURCE_UPLOAD)

    @rx.event
    async def clear_logo_version(self, version: str) -> None:
        was_palette = self._palette_version() == version
        self.logo_versions = {k: v for k, v in self.logo_versions.items() if k != version}
        self.logo_version_context = {
            k: v for k, v in self.logo_version_context.items() if k != version
        }
        if was_palette:
            await self._colour_from_versions()

    def _palette_version(self) -> str | None:
        """Which staged version colours the palette: the fullest mark first — the same
        order the save picks the brand's main logo in (`brand_kit_store.MAIN_LOGO_ORDER`)."""
        return next((v for v in _PALETTE_VERSION_ORDER if v in self.logo_versions), None)

    async def _colour_from_versions(self) -> None:
        """The palette follows the (new) fullest version; with none left, the colours an
        upload put in go back out. A version saved in R2 already has its colours in the
        saved palette, so it is not read again."""
        version = self._palette_version()
        if version is None:
            if self.logo_source == LOGO_SOURCE_UPLOAD and not self.logo_key:
                await self.retire_logo_colours()
            return
        key = self.logo_versions[version]
        if key.startswith("t/"):
            return
        try:
            data = (rx.get_upload_dir() / key).read_bytes()
        except OSError:
            return
        await self.apply_logo_colours(data, LOGO_SOURCE_UPLOAD)

    @rx.event
    def set_logo_version_context(self, version: str, value: str) -> None:
        if version in LOGO_VERSION_KEYS:
            self.logo_version_context = {**self.logo_version_context, version: value}

    # -- typography (§ request 2026-10-05) -------------------------------------------

    @rx.var
    def font_file_names(self) -> dict[str, str]:
        """The file name behind each staged font (slot → name), for the tile's dropzone
        label: a key is `<folder>/<hex>_<name>` locally and in R2 alike."""
        return {slot: Path(key).name.split("_", 1)[-1] for slot, key in self.font_files.items()}

    @rx.event
    async def handle_font_upload(
        self, files: list[rx.UploadFile], slot: str
    ) -> rx.event.EventSpec | None:
        """Stage the font file dropped on Tipografía's tile, then read it (§ request
        2026-10-05, "la busca y rellena el input"): the family the file declares
        (`qualify_creative.brand.fonts.family_name` — its own `name` table, or its file
        name for a WOFF2) goes into the name field at once, and whether it is open source
        is asked of Google Fonts in the background (`check_font_file`)."""
        if slot not in FONT_SLOT_KEYS:
            return None
        staged = await self._stage_logo_file(
            files, f"font/{slot}", max_bytes=brand_fonts.MAX_FONT_BYTES, too_large=_FONT_TOO_LARGE
        )
        if staged is None:
            return None
        self.font_files = {**self.font_files, slot: staged[0]}
        # off the event loop: a user's file, up to `MAX_FONT_BYTES`, inflated for a WOFF
        family = await asyncio.to_thread(brand_fonts.family_name, staged[2], staged[1])
        if not family:
            return brand_documents.notify(*font_file_message("", None))
        creative = await self.get_state(CreativeState)
        creative.kit_font_heading = creative.kit_font_body = family  # the one face
        return BrandWizardState.check_font_file(family)

    @rx.event(background=True)
    async def check_font_file(self, family: str) -> AsyncIterator[rx.event.EventSpec | None]:
        """Is the family just read off a font file on Google Fonts — and so open source?
        One request to its CSS API, off the event loop; the answer is a toast."""
        open_source = await asyncio.to_thread(brand_fonts.on_google_fonts, family)
        yield brand_documents.notify(*font_file_message(family, open_source))

    @rx.event
    def clear_font_file(self, slot: str) -> None:
        self.font_files = {k: v for k, v in self.font_files.items() if k != slot}

    @rx.event(background=True)
    async def detect_fonts(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """\"Detectar desde tu logo\" (§ request 2026-10-05, \"que se pueda extraer la
        tipografía desde las opciones del brandboard\"): Claude looks at the staged logo
        versions — fullest mark first, the same order the palette follows — and names the
        family their lettering most resembles (`qualify_api.creative.font_ai`). The guess
        goes into the one editable name field, and what it found pops up as a toast
        (§ request 2026-10-05, "no quiero ese tipo de notificación" — it was a callout
        under the tile) saying \"parece\" with the alternatives — a resemblance, never
        an identification.
        Background: a vision call takes seconds. No key, no call (`MissingAPIKey`)."""
        from qualify_api.claude_tools import ClaudeToolError, MissingAPIKey, api_key_from_env
        from qualify_api.creative import font_ai

        async with self:
            if self.detecting_fonts:
                return
            keys = [
                self.logo_versions[v] for v in _PALETTE_VERSION_ORDER if v in self.logo_versions
            ]
            if not keys:
                self.font_note, self.font_note_tone = _FONTS_NEED_LOGO, "info"
                yield brand_documents.notify(_FONTS_NEED_LOGO, "info")
                return
            auth = await self.get_state(AuthState)
            tenant_id = tenant_uuid(brand_tenant_id(auth))
            self.detecting_fonts = True
            self.font_note = ""
        note, tone = "", "info"
        try:
            api_key = api_key_from_env()  # before any read: no key, no work
            files = await asyncio.to_thread(_read_logo_files, tenant_id, keys)
            guess, stats = await asyncio.to_thread(font_ai.identify_fonts, files, api_key=api_key)
            logger.info(
                "brand fonts: %s read by %s → %r ($%.4f)",
                len(files),
                stats.model_revision or stats.model_id,
                guess.heading,
                stats.cost_usd,
            )
            async with self:
                creative = await self.get_state(CreativeState)
                if guess.heading:
                    creative.kit_font_heading = creative.kit_font_body = guess.heading
            note = font_ai.describe(guess)
            tone = "info" if guess.found_anything else "warn"
        except MissingAPIKey:
            note, tone = _FONTS_NO_KEY, "warn"
        except font_ai.NoUsableImage:
            note, tone = _FONTS_NO_IMAGE, "warn"
        except (ClaudeToolError, OSError) as exc:
            logger.warning("brand fonts: detection failed: %s", exc)
            note, tone = _FONTS_FAILED, "error"
        except Exception as exc:  # noqa: BLE001 — SDK/transport errors: never crash the step
            logger.warning("brand fonts: detection failed: %s", exc)
            note, tone = _FONTS_FAILED, "error"
        async with self:
            self.detecting_fonts = False
            self.font_note, self.font_note_tone = note, tone
        yield brand_documents.notify(note, tone)

    @rx.event
    async def handle_extra_upload(self, files: list[rx.UploadFile]) -> None:
        """Tu brandboard's "+" (§ request 2026-09-29): every dropped file becomes one more
        element of the brand, each with its own label and context to fill in."""
        added = []
        for upload in files[:_MAX_EXTRAS_PER_DROP]:
            staged = await self._stage_logo_file([upload], "logo/extra")
            if staged is None:
                break
            added.append(
                {
                    "id": uuid4().hex[:8],
                    "key": staged[0],
                    "name": staged[1],
                    "label": "",
                    "context": "",
                }
            )
        self.brand_extras = [*self.brand_extras, *added]

    @rx.event
    def set_extra_field(self, extra_id: str, field: str, value: str) -> None:
        if field not in ("label", "context"):
            return
        self.brand_extras = [
            {**extra, field: value} if extra["id"] == extra_id else extra
            for extra in self.brand_extras
        ]

    @rx.event
    def remove_extra(self, extra_id: str) -> None:
        self.brand_extras = [extra for extra in self.brand_extras if extra["id"] != extra_id]

    async def _stage_logo_file(
        self,
        files: list[rx.UploadFile],
        folder: str,
        *,
        max_bytes: int | None = None,
        too_large: str = _UPLOAD_FAILED,
    ) -> tuple[str, str, bytes] | None:
        """Write the first dropped file under the tenant's upload dir → (key, name, bytes),
        or None (with `logo_error` set) when there is no session, it cannot be read, or it
        is above `max_bytes` (`too_large` says so; nothing is written)."""
        if not files:
            return None
        auth = await self.get_state(AuthState)
        tenant_id = tenant_uuid(brand_tenant_id(auth))
        if tenant_id is None:
            self.logo_error = _NO_SESSION
            return None
        upload = files[0]
        # refused before it is read when the upload says its size; otherwise read at
        # most one byte past the cap — never the whole of an oversized file
        if max_bytes is not None and (getattr(upload, "size", None) or 0) > max_bytes:
            self.logo_error = too_large
            return None
        try:
            data = await (upload.read() if max_bytes is None else upload.read(max_bytes + 1))
        except Exception:
            self.logo_error = _UPLOAD_FAILED
            return None
        if max_bytes is not None and len(data) > max_bytes:
            self.logo_error = too_large
            return None
        name = _safe_upload_name(upload.name)
        key = f"uploads/{tenant_id}/{folder}/{uuid4().hex}_{name}"
        target = rx.get_upload_dir() / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.logo_error = ""
        return key, name, data

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
        creative = await self.get_state(CreativeState)
        creative.kit_palette, colours = await asyncio.to_thread(
            brand_prefill.logo_colours_update, creative.kit_palette, self.logo_colors, data
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
            # no bare 0-100 number (m-24848529 UX review): it says nothing to an owner
            rx.text(right, size="2", color=T.TEXT_MUTED),
            width="100%",
            align="center",
        ),
        rx.slider(
            value=[value],
            on_change=handler,
            min=0,
            max=100,
            step=1,
            width="100%",
            aria_label=f"Entre {left} y {right}",
        ),
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

    `name` accepts a plain string OR an `rx.Var[str]` — `rx.icon` is fine either
    way."""
    return rx.box(
        rx.icon(name, size=22),
        class_name="q-brand-glyph",
        width="3rem",
        height="3rem",
        min_height="3rem",
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


def _loading_view(title: str, subtitle: str = "", *, creep_seconds: int = 6) -> rx.Component:
    """The one loading affordance the Brand Kit uses, wherever something is still in
    flight (`CreativeState.kit_loading` on page load, `BrandConnectState.analyzing`
    mid-scrape): the progress bar (`progress_panel`), never a spinner (§ request
    2026-10-02: every Brand Kit loader is the progress-bar one). None of these waits
    reports progress, so the bar creeps over `creep_seconds` and the screen goes away
    when the work ends. Centring is the CALLER's job: this returns the content, and
    every caller places it inside a `card(..., flex="1", display="flex",
    align_items="center", justify_content="center")` — the exact shape
    `brand_manual_index`/`brand_connect_index` already give the rest of each step, so a
    loading screen sits in the middle of the same frame the real content would."""
    return progress_panel(title, subtitle, creep_seconds=creep_seconds)


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

    ``icon`` is optional and additive (§ request 2026-09-09): a per-option leading
    icon in the same tinted-circle treatment `_step_icon` gives a whole step's own
    anchor icon, just smaller and inline.

    Liquid Glass: it is `ui.choice_card` — the card material, a 2px accent ring when
    selected, a softer ring and the kit's lift under the pointer — so no colour or
    shadow is written here."""
    return choice_card(
        rx.hstack(
            *(
                [
                    rx.box(
                        rx.icon(icon, size=18),
                        class_name="q-brand-glyph",
                        width="2.25rem",
                        height="2.25rem",
                        min_width="2.25rem",
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
                choice_card_check(),
            ),
            width="100%",
            align="start",
            spacing="3",
        ),
        selected=selected,
        on_select=on_click,
    )


# ---------------------------------------------------------------------------
# The Resultados e insights building blocks — SHARED by both flows' final screen
# (`_step_insights` in the manual flow, `_connect_step_insights` in the connect one):
# same "cuentas parecidas" section either way, so the two paths cannot drift on it.

#: Where the final button of BOTH flows («Terminar mi marca») sends a pre-login draft
#: (§ request 2026-10-05: "que el botón de mejorar tu perfil vaya al registro
#: directamente"): the signup, prefilled with the draft's email — creating the account
#: with it adopts the kit just saved.
_SIGNUP_ROUTE = SIGNUP_ROUTE


async def _finish_route(state: rx.State) -> str | None:
    """The signup for a pre-login draft — every Brand Kit starts as one since 2026-10-02.
    `None` for a session that already has an account: it has nothing to sign up for, and
    since m-24842965 it no longer lands on `/` (Menciones, an empty screen of another
    domain) either — the wizard shows «Tu marca está lista» instead
    (`BrandWizardState.brand_ready`). Call it holding the state lock in a background handler."""
    auth = await state.get_state(AuthState)
    return None if auth.session_tenant_id else _SIGNUP_ROUTE


async def _finish_navigation(state: rx.State) -> rx.event.EventSpec | None:
    """What the end of either flow does, decided under the state lock: the redirect to
    the signup for a draft, or — for an account — raise the «Tu marca está lista» card
    (no navigation). Both flows' `finish`/`finish_to_signals` go through here so the
    two cannot drift."""
    route = await _finish_route(state)
    if route is not None:
        return rx.redirect(route)
    wizard = state if isinstance(state, BrandWizardState) else None
    if wizard is None:
        wizard = await state.get_state(BrandWizardState)
    wizard.brand_ready = True
    return None


# ---------------------------------------------------------------------------------------
# Leaving Tu marca (PASOS-4, m-24852243 — rule N2, docs/design-system.md §4.5)

#: Where an account goes from any step of Tu marca: Inicio, which lists «Termina tu
#: marca» first while the kit is unfinished (`home_vm`).
HOME_ROUTE = "/"
#: The head's «‹ destino»: Inicio for an account; for a guest (a draft before the
#: login, no Inicio yet) the screen that asked for the email (`/brand/start`).
EXIT_LABEL_SESSION = "Inicio"
EXIT_LABEL_GUEST = "Tu correo"
SAVED_FOR_LATER = "Guardamos lo que llevas. Cuando vuelvas a Tu marca, sigues en este mismo paso."
SAVED_FOR_LATER_GUEST = (
    "Guardamos lo que llevas. Cuando vuelvas, escribe tu correo y sigues en este mismo paso."
)
SAVE_LATER_FAILED = "No pudimos guardar lo que llevas. Revisa tu conexión e inténtalo de nuevo."


def exit_label() -> rx.Var[str]:
    return rx.cond(AuthState.session_tenant_id != "", EXIT_LABEL_SESSION, EXIT_LABEL_GUEST)


async def leave_flow(state: rx.State, flow: str, *, later: bool) -> AsyncIterator[Any]:
    """«Seguir después» (``later``) and the head's «‹ Inicio» / «‹ Tu correo», from a
    background handler: what is written is saved first (`brand_finish.save_progress`),
    never lost (N6). An account then goes to Inicio (N2) — «Seguir después» says it was
    saved. A guest has no Inicio: «Seguir después» saves and says how to come back,
    staying on the step; «‹ Tu correo» forgets the draft in this browser (it stays saved
    under its email) and asks for an email again (`AuthState.leave_brand_draft`). A
    failed save stays on the step and says so."""
    from .brand_finish import save_progress

    async with state:
        in_session = (await state.get_state(AuthState)).session_tenant_id != ""
    try:
        await save_progress(state, flow)
    except Exception as exc:  # noqa: BLE001 — a toast, never a crash
        logger.warning("brand flow: save before leaving failed: %s", type(exc).__name__)
        yield brand_documents.notify(SAVE_LATER_FAILED, "error")
        return
    if in_session:
        if later:
            yield brand_documents.notify(SAVED_FOR_LATER, "ok")
        yield rx.redirect(HOME_ROUTE)
        return
    if later:
        yield brand_documents.notify(SAVED_FOR_LATER_GUEST, "ok")
        return
    yield AuthState.leave_brand_draft


def step_param(state: rx.State) -> object | None:
    """The raw ``?paso=`` of the address the event came from, or None without one."""
    params = state.router.url.query_parameters
    return params.get(STEP_PARAM) if STEP_PARAM in params else None


#: The final button of both flows (m-24842965): an account finishes its brand; a
#: pre-login draft finishes it AND goes on to create the account that adopts it.
_FINISH_LABEL = "Terminar mi marca"
_FINISH_DRAFT_LABEL = "Terminar y crear mi cuenta"


def _asks_for_ready_card(state: rx.State) -> bool:
    """Whether this page load came with `?lista=1` — the signup that adopted a draft
    sends the owner to `AuthState`'s `BRAND_READY_ROUTE`, so that path ends on the same
    «Tu marca está lista» card a logged-in finish shows."""
    key, _, value = BRAND_READY_QUERY.partition("=")
    return state.router.url.query_parameters.get(key, "") == value


async def _explain_finish_failure(state: rx.State) -> None:
    """A failed finish keeps the steps on screen (no card, no redirect) with an error
    that names the button to press again. Only the kit failure is reworded: «archivos
    no guardados» and «sin sesión» already say what to do."""
    from .brand_finish import _KIT_FAILED

    async with state:
        creative = await state.get_state(CreativeState)
        if creative.kit_error != _KIT_FAILED:
            return
        auth = await state.get_state(AuthState)
        label = _FINISH_LABEL if auth.session_tenant_id else _FINISH_DRAFT_LABEL
        creative.kit_error = f"No pudimos guardar tu marca. Toca «{label}» otra vez."


#: The three ways out of «Tu marca está lista» (m-24842965, N3): one solid button to the
#: next job, one soft one, and a link back. The handler only follows these routes — the
#: route arrives from the client, so anything else falls back to the brand itself.
_READY_CREATE_ROUTE = "/create"
_READY_CONNECT_ROUTE = "/connections"
_READY_BRAND_ROUTE = "/brand/kit"
_READY_ROUTES = frozenset({_READY_CREATE_ROUTE, _READY_CONNECT_ROUTE, _READY_BRAND_ROUTE})


def _ready_button(label: str, icon: str, route: str, *, variant: str) -> rx.Component:
    """One of the card's buttons: full width of the card's column (one column on a
    phone, N12) and at least 44 px tall — a Radix size-3 button is 40 px."""
    return rx.button(
        label,
        rx.icon(icon, size=T.ICON_MD),
        size="3",
        variant=variant,
        radius=_CONTROL_RADIUS,
        width="100%",
        min_height="44px",
        on_click=BrandWizardState.leave_brand_ready(route),
    )


def _brand_ready_card() -> rx.Component:
    """«Tu marca está lista»: the fact, what it means for the owner, and the next job
    (m-24842965 — exact copy from the ticket)."""
    return card(
        rx.vstack(
            _step_icon("circle-check"),
            # §8: the page's h1 is `page_header`'s; the card's title is an h2
            rx.heading("Tu marca está lista", size="6", as_="h2", text_align="center"),
            rx.text(
                "Tus publicaciones saldrán con tu logo, tus colores y tu forma de hablar.",
                size="3",
                color=T.TEXT_MUTED,
                text_align="center",
            ),
            rx.vstack(
                _ready_button(
                    "Crear mi primera publicación",
                    "wand-sparkles",
                    _READY_CREATE_ROUTE,
                    variant="solid",
                ),
                _ready_button(
                    "Conectar mi Instagram",
                    "link",
                    _READY_CONNECT_ROUTE,
                    variant="soft",
                ),
                rx.link(
                    "Ver mi marca",
                    href=_READY_BRAND_ROUTE,
                    on_click=BrandWizardState.hide_brand_ready,
                    size="2",
                    min_height="44px",
                    display="inline-flex",
                    align_items="center",
                    justify_content="center",
                ),
                spacing="3",
                width="100%",
                align="center",
                padding_top="0.5rem",
            ),
            spacing="3",
            align="center",
            width="100%",
            max_width="26rem",
        ),
        padding="1.75rem",
        width="100%",
        max_width="34rem",
        align_self="center",
        display="flex",
        justify_content="center",
    )


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
            media_thumb("", size="2.5rem", round=True, icon="user-round", icon_size=18),
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


def _finish_label() -> rx.Var[str]:
    return rx.cond(AuthState.session_tenant_id != "", _FINISH_LABEL, _FINISH_DRAFT_LABEL)


def _finish_button(on_click: rx.event.EventType[()]) -> rx.Component:
    """The last control of BOTH flows' Resultados e insights screen — replaces
    Finalizar entirely (§ request 2026-09-05), it does not sit next to it. `on_click`
    is each flow's own chain (`[CreativeState.save_kit_form, <flow>.finish_to_signals]`
    — the reset differs per flow, the button never should), so the two flows share the
    label/icon while keeping their own state. «Terminar mi marca» since m-24842965: it
    used to invite the owner to improve the profile and land on Menciones; now an
    account gets «Tu marca está lista» (`_finish_navigation`), a draft still goes on to
    the signup."""
    return rx.button(
        rx.cond(AuthState.session_tenant_id != "", _FINISH_LABEL, _FINISH_DRAFT_LABEL),
        rx.icon("check", size=T.ICON_SM),
        size="2",
        radius=_CONTROL_RADIUS,
        on_click=on_click,
        # the save is awaited now (§ 2026-10-01): show it working
        loading=CreativeState.kit_saving,
    )


# ---------------------------------------------------------------------------
# The nine steps


def _step_identity() -> rx.Component:
    """¿Quién es la marca?, in both flows — WITH the brief on top (§ request 2026-10-05,
    "el brief y el quién es tu marca vamos a unificarlo"; the brief had its own screen
    since 2026-09-29). Uploading one is optional; when Claude reads it, what it can quote
    goes straight into Posicionamiento and Audiencia below and into the lists that
    ¿Todo correcto? shows (`brand_documents.apply_directly`) — no review panel."""
    return _step_body(*_identity_editor(), icon="compass")


def _identity_editor() -> tuple[rx.Component, ...]:
    """¿Quién es la marca?'s controls — the brief and the two fields — shared by the
    wizard step and the Brand Kit editor's "Marca" section."""
    # § third round of 2026-10-05: while the brief is read, its progress screen is all
    # the step shows — the fields come back, filled, when the read is done
    return (
        brand_documents.brief_upload_card(),
        rx.cond(
            ~brand_documents.BrandDocumentState.brief_busy,
            rx.fragment(
                _labeled_area(
                    "¿Qué te hace distinto?",
                    CreativeState.kit_positioning,
                    CreativeState.set_kit_positioning,
                    "Ej.: Cafetería de especialidad en Cúcuta que tuesta su propio café de "
                    "Santander y te lo sirve en menos de 5 minutos.",
                ),
                _labeled_area(
                    "¿Quién te compra?",
                    CreativeState.kit_audience,
                    CreativeState.set_kit_audience,
                    "Ej.: Oficinistas de 25 a 40 años del centro de Cúcuta que quieren un "
                    "buen café para llevar antes de las 9 a. m.",
                ),
            ),
        ),
    )


#: ¿Tienes brandboard?'s two answers — (value, title, blurb), shared by both flows so
#: their copy cannot drift (§ request 2026-09-29: "ya tengo uno o generar").
BRANDBOARD_ANSWERS: tuple[tuple[str, str, str], ...] = (
    ("si", "Ya tengo uno", "Súbelo en el siguiente paso y lo usaremos tal cual."),
    ("no", "Ayúdame a crearlo", "Te hacemos tres preguntas y lo creamos contigo."),
)


def _step_has_logo() -> rx.Component:
    return _step_body(
        *(
            _choice_card(
                title,
                blurb,
                BrandWizardState.has_logo == value,
                BrandWizardState.answer_has_logo(value),
            )
            for value, title, blurb in BRANDBOARD_ANSWERS
        ),
        icon="image",
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
    """The three questions behind "te haremos tres preguntas para generarlo"
    (`BRANDBOARD_ANSWERS`' own "Generar uno" copy). These used to be literal lorem
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
                "Ej.: Minimalista, una taza dibujada con una sola línea",
                height="3.25rem",
            ),
            _labeled_input(
                "¿Qué quieres que transmita?",
                BrandWizardState.logo_brief_2,
                BrandWizardState.set_logo_brief_2,
                "Ej.: Cercanía y calidad, sin sentirse caro",
                height="3.25rem",
            ),
            _labeled_input(
                "¿Tienes referencias que te gusten?",
                BrandWizardState.logo_brief_3,
                BrandWizardState.set_logo_brief_3,
                "Ej.: Lo simple y redondo del logo de Airbnb",
                height="3.25rem",
            ),
            icon="pencil-line",
        ),
        _hidden_submit(),
        on_submit=next_handler,
        width="100%",
    )


#: The versions of a logo a brandboard lays out — (name, what it is). Shown as skeleton
#: cards on Tu brandboard (§ request 2026-09-29) until something fills them in.
LOGO_VERSIONS: tuple[tuple[str, str, str], ...] = (
    ("logotipo", "Logotipo", "Solo texto."),
    ("isotipo", "Isotipo", "Imagen sin texto."),
    ("imagotipo", "Imagotipo", "Imagen + texto, en vertical u horizontal."),
    ("isologo", "Isologo", "Texto y símbolo fundidos o integrados."),
)
LOGO_VERSION_KEYS = frozenset(key for key, _, _ in LOGO_VERSIONS)
#: The version whose colours seed the palette, fullest mark first (§ 2026-10-01).
_PALETTE_VERSION_ORDER = ("imagotipo", "logotipo", "isologo", "isotipo")

#: Tipografía's tile (§ request 2026-10-05, "un apartado para la tipografía antes de la
#: paleta de colores") — (key, name, what it is): the family's NAME (a kit field,
#: `CreativeState.kit_font_heading`) and, optionally, its FILE (`BrandWizardState.
#: font_files`, saved with the brandboard). ONE face since the third round of that day
#: ("solo haz una tipografía"): Títulos + Cuerpo de texto became a single tile, and
#: `set_kit_font_heading` mirrors it into `kit_font_body`, so whatever reads either
#: field gets the same family.
FONT_SLOTS: tuple[tuple[str, str, str], ...] = (
    ("heading", "Tu tipografía", "La usamos en los títulos y los textos de lo que generemos."),
)
FONT_SLOT_KEYS = frozenset(key for key, _, _ in FONT_SLOTS)
#: The `@font-face` family an uploaded font file is registered under, per slot.
_FONT_FACE_FAMILY = {"heading": "q-brand-heading", "body": "q-brand-body"}

_REFERENCE_HEIGHT = "5.5rem"
#: Tu brandboard's tiles (logo versions, other elements, the "+") share one responsive
#: grid shape (§ request 2026-09-30): as many ~14rem columns as the column's width fits,
#: stretched to fill it. The step's column is capped at `_BRANDBOARD_COLUMN_MAX` and
#: centred (§ request 2026-10-05, "la view Tu brandboard no está centrada"): with the
#: card's whole width, a wide screen fitted six tracks and the four versions sat in the
#: first four, leaving a void on the right — the block read as left-aligned.
_TILE_GRID = {
    "display": "grid",
    "grid_template_columns": "repeat(auto-fill, minmax(min(100%, 14rem), 1fr))",
    "gap": "0.75rem",
    "width": "100%",
}
#: Four 14rem tiles plus their three gaps: the logo versions fill exactly one row, so the
#: column is as wide as the brandboard's widest section and no wider.
_BRANDBOARD_COLUMN_MAX = "min(100%, 58.25rem)"
#: The one typography tile (a preview, a name and a dropzone) in a column of its own
#: (`_TYPOGRAPHY_COLUMN_MAX`), centred like every other step's fields.
_TYPOGRAPHY_COLUMN_MAX = "min(100%, 26rem)"
_FONT_GRID = {**_TILE_GRID, "grid_template_columns": "1fr"}
#: The frame every tile of that grid has, so an uploaded element and the "+" read as
#: the same object as a logo version.
_TILE_FRAME = {
    "spacing": "2",
    "align_items": "start",
    "width": "100%",
    # the card material (`ui.card`'s own class, `.q-card`): a tile is a block
    "class_name": "q-card",
    "padding": "0.75rem",
}


def _mark_icon(size: int) -> rx.Component:
    return qualify_mark(size)


def _mark_text(size: str) -> rx.Component:
    return rx.text("Qualify", size=size, weight="bold", letter_spacing="-0.02em")


def _logo_version_reference(key: str) -> rx.Component:
    """What that version looks like, drawn with Qualify's own mark (`ui.layout.
    brand_mark`: the radar icon + "Qualify") so each slot shows an example rather
    than just a definition (§ request 2026-09-29, "una mini referencia a partir del
    logo de Qualify")."""
    if key == "logotipo":
        mark = _mark_text("4")
    elif key == "isotipo":
        mark = _mark_icon(32)
    elif key == "imagotipo":
        mark = rx.hstack(
            rx.hstack(_mark_icon(18), _mark_text("2"), align="center", spacing="1"),
            rx.vstack(_mark_icon(18), _mark_text("1"), align="center", spacing="0"),
            align="center",
            spacing="4",
        )
    else:  # isologo: the symbol and the name inside one shape
        mark = rx.vstack(
            _mark_icon(16),
            rx.text("Qualify", size="1", weight="bold", letter_spacing="-0.02em"),
            align="center",
            justify="center",
            spacing="0",
            width="3.75rem",
            height="3.75rem",
            border_radius="9999px",
            border=f"2px solid {T.tone_color('accent', 9)}",
            background=T.tone_color("accent", 3),
        )
    return rx.center(mark, height=_REFERENCE_HEIGHT, width="100%", opacity="0.85")


def _asset_src(key: rx.Var[str]) -> rx.Var[str]:
    """Where to show a brandboard file from: a saved one (R2) through its `/r2media`
    path (`BrandWizardState.asset_views`), a just-staged one from the upload store."""
    return rx.cond(
        BrandWizardState.asset_views.contains(key),
        BACKEND_BASE + BrandWizardState.asset_views[key].to(str),
        rx.get_upload_url(key),
    )


def _remove_button(label: rx.Var[str] | str, on_click: rx.event.EventSpec) -> rx.Component:
    return rx.icon_button(
        rx.icon("x", size=T.ICON_SM),
        variant="ghost",
        color_scheme="gray",
        size="1",
        aria_label=label,
        on_click=on_click,
    )


def _context_field(
    value: rx.Var[str], on_change: Callable[[rx.Var[str]], rx.event.EventSpec]
) -> rx.Component:
    """The free-text context of an uploaded element (§ request 2026-09-29, "que se pueda
    poner un contexto de esto subido"): when and how to use it."""
    return rx.text_area(
        value=value,
        on_change=on_change,
        placeholder="Ej.: Va en las historias y sobre fondos oscuros; nunca encima de fotos.",
        size="2",
        rows="2",
        width="100%",
        radius=_CONTROL_RADIUS,
    )


def _logo_version_card(key: str, name: str, blurb: str) -> rx.Component:
    """One version of the logo. The top is its own dropzone (§ request 2026-09-29, "que
    se puedan arrastrar"): Qualify's example until a file is dropped, then that file.
    Name, ✕ and the context field sit OUTSIDE the dropzone, so clicking or typing in
    them never opens the file picker."""
    upload_id = f"brand_logo_{key}"
    staged = BrandWizardState.logo_versions.contains(key)
    return rx.vstack(
        dropzone(
            rx.vstack(
                rx.cond(
                    staged,
                    rx.image(
                        src=_asset_src(BrandWizardState.logo_versions[key].to(str)),
                        alt=f"Tu {name.lower()}",
                        height=_REFERENCE_HEIGHT,
                        width="100%",
                        object_fit="contain",
                    ),
                    _logo_version_reference(key),
                ),
                rx.text(
                    rx.cond(staged, "Suelta otro para cambiarlo", f"Arrastra tu {name.lower()}"),
                    size="1",
                    color=T.TEXT_FAINT,
                ),
                spacing="1",
                align="center",
                width="100%",
            ),
            upload_id=upload_id,
            accept=_LOGO_VERSION_ACCEPT,
            max_files=1,
            on_drop=BrandWizardState.handle_logo_version_upload(
                rx.upload_files(upload_id=upload_id), key
            ),
            variant="compact",
            padding="0.5rem",
            width="100%",
        ),
        rx.hstack(
            rx.text(name, size="2", weight="medium"),
            rx.spacer(),
            rx.cond(
                staged,
                _remove_button(
                    f"Quitar tu {name.lower()}", BrandWizardState.clear_logo_version(key)
                ),
            ),
            align="center",
            width="100%",
        ),
        rx.text(blurb, size="1", color=T.TEXT_MUTED),
        # no usage note here (§ request 2026-10-01): only the extras added with the "+"
        # take one — a logo version is already defined by its own name
        **_TILE_FRAME,
    )


def _extra_card(extra: rx.Var[dict[str, str]]) -> rx.Component:
    """One element added with the "+", shaped like a logo version's tile: its image on
    top, then what it is (with the ✕), the file it came from and its context."""
    return rx.vstack(
        rx.center(
            rx.image(
                src=_asset_src(extra["key"]),
                alt=extra["name"],
                height=_REFERENCE_HEIGHT,
                width="100%",
                object_fit="contain",
            ),
            class_name="q-tile-preview",
            padding="0.5rem",
            width="100%",
        ),
        rx.hstack(
            rx.input(
                value=extra["label"],
                on_change=lambda value: BrandWizardState.set_extra_field(
                    extra["id"], "label", value
                ),
                placeholder="Ej.: Patrón de granos de café para fondos",
                size="2",
                width="100%",
                radius=_CONTROL_RADIUS,
            ),
            _remove_button("Quitar este elemento", BrandWizardState.remove_extra(extra["id"])),
            align="center",
            spacing="2",
            width="100%",
        ),
        rx.text(
            extra["name"],
            size="1",
            color=T.TEXT_FAINT,
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
            max_width="100%",
        ),
        _context_field(
            extra["context"],
            lambda value: BrandWizardState.set_extra_field(extra["id"], "context", value),
        ),
        **_TILE_FRAME,
    )


def _add_extra_skeleton() -> rx.Component:
    """The "+" tile's picture: just the "+", centred where a logo version shows
    Qualify's example (§ request 2026-09-30: no text skeleton beside it)."""
    return rx.center(
        rx.center(
            rx.icon("plus", size=22),
            class_name="q-brand-glyph q-brand-glyph--square",
            width="3.25rem",
            height="3.25rem",
        ),
        height=_REFERENCE_HEIGHT,
        width="100%",
    )


def _add_extra_button() -> rx.Component:
    """The "+" (§ request 2026-09-29), as a tile like the others (§ request 2026-09-30):
    the dropzone on top — a skeleton of an element, since there is no example to show
    — and its name and description below. Drop or pick one or more images; each
    becomes its own tile before this one."""
    return dropzone(
        rx.vstack(
            rx.vstack(
                _add_extra_skeleton(),
                rx.text("Arrastra o haz clic", size="1", color=T.TEXT_FAINT),
                spacing="1",
                align="center",
                width="100%",
                # the look only: the whole tile (the `bare` dropzone) is the hit area
                class_name="q-dropzone q-dropzone--compact",
                padding="0.5rem",
            ),
            rx.text("Añadir más", size="2", weight="medium"),
            rx.text(
                "Calcomanías, patrones, mascota, íconos… cualquier otro elemento de tu marca.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            **_TILE_FRAME,
        ),
        upload_id=_EXTRA_UPLOAD_ID,
        accept=_LOGO_VERSION_ACCEPT,
        max_files=_MAX_EXTRAS_PER_DROP,
        multiple=True,
        on_drop=BrandWizardState.handle_extra_upload(rx.upload_files(upload_id=_EXTRA_UPLOAD_ID)),
        variant="bare",
        width="100%",
    )


def _font_face(slot: str) -> rx.Component:
    """Registers the font file staged for `slot` under its `@font-face` family
    (`_FONT_FACE_FAMILY`), so the tile's preview can be set in it. Built by Var
    concatenation, not an f-string: the CSS braces would read as Var placeholders."""
    src = _asset_src(BrandWizardState.font_files[slot].to(str)).to(str)
    head = rx.Var.create(f'@font-face {{ font-family: "{_FONT_FACE_FAMILY[slot]}"; src: url("').to(
        str
    )
    tail = rx.Var.create('"); }').to(str)
    return rx.el.style(head + src + tail)


#: Per slot: the kit field holding the family name, its setter, the preview family
#: (`font_family_css` of the name) and the Google Fonts stylesheet for it.
_FONT_NAME_FIELDS: dict[str, tuple[Any, Any, Any, Any]] = {
    "heading": (
        CreativeState.kit_font_heading,
        CreativeState.set_kit_font_heading,
        CreativeState.kit_font_heading_family,
        CreativeState.kit_font_heading_css_url,
    ),
    "body": (
        CreativeState.kit_font_body,
        CreativeState.set_kit_font_body,
        CreativeState.kit_font_body_family,
        CreativeState.kit_font_body_css_url,
    ),
}


def _font_card(key: str, name: str, blurb: str) -> rx.Component:
    """One type face of the brand (§ request 2026-10-05), shaped like a logo version's
    tile: a preview on top ("Aa" + a sample line, set in the uploaded file when there is
    one, else in the typed family through Google Fonts), the name and ✕, what the face
    is for, the family's name field and a small dropzone for the file — optional, the
    name alone is a complete answer."""
    upload_id = f"brand_font_{key}"
    value, setter, name_family, css_url = _FONT_NAME_FIELDS[key]
    staged = BrandWizardState.font_files.contains(key)
    family = rx.cond(staged, f'"{_FONT_FACE_FAMILY[key]}", sans-serif', name_family)
    return rx.vstack(
        rx.cond(staged, _font_face(key)),
        rx.cond(~staged & (css_url != ""), rx.el.link(rel="stylesheet", href=css_url)),
        rx.center(
            rx.vstack(
                rx.text("Aa", size="8", weight="bold", line_height="1", font_family=family),
                rx.text(
                    "Así se lee tu marca.",
                    size="2",
                    color=T.TEXT_MUTED,
                    font_family=family,
                    text_align="center",
                ),
                spacing="1",
                align="center",
            ),
            height=_REFERENCE_HEIGHT,
            width="100%",
            class_name="q-tile-preview",
            padding="0.5rem",
        ),
        rx.hstack(
            rx.text(name, size="2", weight="medium"),
            rx.spacer(),
            rx.cond(
                staged,
                _remove_button(
                    "Quitar el archivo de la fuente", BrandWizardState.clear_font_file(key)
                ),
            ),
            align="center",
            width="100%",
        ),
        rx.text(blurb, size="1", color=T.TEXT_MUTED),
        rx.input(
            value=value,
            on_change=setter,
            placeholder="Nombre de la fuente. Ej.: Montserrat",
            size="2",
            width="100%",
            radius=_CONTROL_RADIUS,
            aria_label="Nombre de la fuente",
        ),
        dropzone(
            rx.hstack(
                rx.icon("upload", size=T.ICON_SM, color=T.TEXT_FAINT),
                rx.text(
                    rx.cond(
                        staged,
                        BrandWizardState.font_file_names[key].to(str),
                        "Archivo de la fuente (opcional): .ttf, .otf, .woff",
                    ),
                    size="1",
                    color=T.TEXT_FAINT,
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                    min_width="0",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            upload_id=upload_id,
            accept=_FONT_ACCEPT,
            max_files=1,
            max_size=brand_fonts.MAX_FONT_BYTES,  # the server re-checks (`_stage_logo_file`)
            on_drop=BrandWizardState.handle_font_upload(rx.upload_files(upload_id=upload_id), key),
            variant="compact",
            padding="0.5rem",
            width="100%",
        ),
        **_TILE_FRAME,
    )


def _detect_fonts_button() -> rx.Component:
    """\"Detectar desde tu logo\" (§ request 2026-10-05): the same quiet AI affordance
    as Tu rubro's \"Sugerir\" — soft, with the sparkles, spinning while the run lasts.
    Disabled until a logo version is staged: nothing to look at before that."""
    return rx.tooltip(
        rx.button(
            rx.cond(
                BrandWizardState.detecting_fonts,
                loading_spinner("sm"),
                rx.icon("sparkles", size=T.ICON_SM),
            ),
            "Detectar desde tu logo",
            on_click=BrandWizardState.detect_fonts,
            disabled=BrandWizardState.detecting_fonts
            | (BrandWizardState.logo_versions.length() == 0),
            variant="soft",
            size="1",
            radius=_CONTROL_RADIUS,
            flex_shrink="0",
        ),
        content="Miramos las letras de tu logo y proponemos la tipografía que más se le parece",
    )


def _typography_editor() -> rx.Component:
    """Tipografía's content (§ request 2026-10-05): what to do, \"Detectar desde tu
    logo\" and the one tile (`FONT_SLOTS`) — what the detection found is a toast, not a
    note here. Shared by the three flows through `_step_typography`."""
    return rx.vstack(
        rx.hstack(
            rx.text(
                "Escribe el nombre de tu fuente o sube su archivo. Si no tienes una, "
                "deja el nombre de la que te gustaría usar.",
                size="2",
                color=T.TEXT_MUTED,
                flex="1",
                min_width="0",
            ),
            _detect_fonts_button(),
            align="center",
            spacing="3",
            width="100%",
        ),
        rx.box(
            *(_font_card(key, name, blurb) for key, name, blurb in FONT_SLOTS),
            **_FONT_GRID,
        ),
        spacing="3",
        align_items="start",
        width="100%",
    )


def _step_typography() -> rx.Component:
    """Tipografía — its own view right before Paleta de colores in every flow (§ request
    2026-10-05: \"que antes de la paleta de colores esté la view y pueda modificar la
    tipografía si se quiere o poner una si no tiene\"). Optional: a brand may leave both
    faces blank and still continue."""
    return _step_body(_typography_editor(), icon="type")


def _logo_versions() -> rx.Component:
    return rx.vstack(
        _section_label("Versiones de tu logo"),
        rx.box(
            *(_logo_version_card(key, name, blurb) for key, name, blurb in LOGO_VERSIONS),
            **_TILE_GRID,
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _brand_extras() -> rx.Component:
    return rx.vstack(
        _section_label("Otros elementos"),
        rx.box(
            rx.foreach(BrandWizardState.brand_extras, _extra_card),
            _add_extra_button(),
            **_TILE_GRID,
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _step_logo(next_handler: rx.event.EventHandler) -> rx.Component:
    """Branches on ¿Tienes brandboard?. `has_logo == "si"` takes one file per logo
    version (`LOGO_VERSIONS`) plus any other element added with the "+", each with its
    own context; anything else asks the brief — so an unanswered question lands on the
    brief rather than on a blank screen. The typography is the NEXT step (§ 2026-10-05,
    `_step_typography`), asked on both branches. § request 2026-09-29 removed both the
    whole-brandboard upload and the optional brief document that used to sit here.
    `next_handler` (§ request 2026-09-09) is which flow's cursor the brief form's
    Enter-to-submit should advance — see `_logo_brief_form`."""
    return rx.cond(
        BrandWizardState.has_logo == "si",
        rx.vstack(
            rx.cond(
                BrandWizardState.logo_error != "",
                callout(BrandWizardState.logo_error, "error"),
            ),
            _logo_versions(),
            _brand_extras(),
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
                rx.icon("pencil", size=11),  # ink: `.q-brand-swatch .q-swatch-edit`
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
            # `.q-swatch` is what the pencil's hover rule keys on (`assets/qualify.css`);
            # `.q-brand-swatch--edit` (`assets/qualify-brand.css`) is the ring and the
            # grow under the pointer (P8: a size change, so the spring). The colour
            # itself is the brand's data, so it stays inline.
            class_name="q-swatch q-brand-swatch q-brand-swatch--edit",
            position="relative",
            width="2.25rem",
            height="2.25rem",
            background=colour,
        ),
        rx.el.button(
            rx.icon("x", size=10),
            on_click=BrandWizardState.remove_colour(index).stop_propagation,
            aria_label="Quitar este color",
            type="button",
            class_name="q-swatch-remove",
            position="absolute",
            top="-0.25rem",
            right="-0.25rem",
            width="1rem",
            height="1rem",
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
        # the hue circle and its ring are `.q-colour-wheel` (`assets/qualify-brand.css`)
        class_name="q-colour-wheel",
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
    return card(
        rx.hstack(
            rx.box(
                class_name="q-brand-swatch",
                width="2.5rem",
                height="2.5rem",
                border_radius=T.RADIUS_CARD,
                background=BrandWizardState.picker_color,
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
        # Not `interactive=True` (no cursor, no lift): this card does nothing when
        # clicked, so it must not advertise that it does.
        padding="0.65rem 0.9rem",
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
    return _step_body(*_palette_editor(), icon="palette")


def _palette_editor() -> tuple[rx.Component, ...]:
    """Paleta de colores's controls — the swatches and the wheel — shared by the
    wizard step and the Brand Kit editor (§ request 2026-09-30)."""
    return (
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
    )


def _step_voice() -> rx.Component:
    """Tu voz (§ request 2026-10-01): its own view before ¿Cómo suena? — record or
    upload, Analizar pre-fills the next screen's sliders, Clonar is manual. Optional:
    nothing here gates Continuar."""
    return _step_body(voice_lab_panel(), icon="mic")


def _step_voice_tone() -> rx.Component:
    # § 2026-10-01: an analysis of Tu voz lands here, with its result above the sliders
    return _step_body(voice_analysis_result(), *_tone_sliders(), icon="sliders-horizontal")


def _tone_sliders() -> tuple[rx.Component, ...]:
    """¿Cómo suena?'s four axes, shared with the Brand Kit editor."""
    return (
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


#: The five kit lists ¿Todo correcto? fills (§ request 2026-10-05: "las views de enséñale
#: a hablar y lo que nunca debe decir vamos a dejarlo solo en el ¿Todo correcto?, que allí
#: se puedan poner y que aparezcan los ejemplos") — (pill field, label, what it is for,
#: an example — shown as a pill while the list is empty).
_KIT_LISTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "do",
        "Ejemplos que SÍ suenan a la marca",
        "Frases reales de tu marca: las imitamos al escribir.",
        "¡Tu primer café del día corre por nuestra cuenta!",
    ),
    (
        "dont",
        "Ejemplos que NO suenan a la marca",
        "Cómo no debe sonar nunca, para alejarnos de ahí.",
        "Estimado cliente, le informamos que disponemos de café.",
    ),
    (
        "cta",
        "Cómo invitas a comprar",
        "Cómo pides que te escriban, compren o visiten.",
        "Pide el tuyo por WhatsApp y pásalo a recoger",
    ),
    (
        "banned",
        "Palabras vetadas",
        "Palabras que nunca deben aparecer.",
        "barato",
    ),
    (
        "claims",
        "Promesas que no puedes hacer",
        "Por ejemplo, decir que eres el mejor o compararte con otro negocio.",
        "el mejor café de Colombia",
    ),
)
#: Which `CreativeState` list var each pill field renders.
_KIT_LIST_ITEMS = {
    "do": CreativeState.kit_do_items,
    "dont": CreativeState.kit_dont_items,
    "cta": CreativeState.kit_cta_items,
    "banned": CreativeState.kit_banned_items,
    "claims": CreativeState.kit_claims_items,
}


def _kit_list_editor(field: str, label: str, hint: str, example: str) -> rx.Component:
    """One kit list (¿Todo correcto? and the Brand Kit editor): its label and what it is
    for, the values as pills that edit in place (`_editable_pill`) and a "+" at their
    end — no input until it is pressed, like Tu rubro's hashtags (§ request 2026-10-06);
    Enter or leaving it adds, Escape or leaving it empty puts the "+" back. While the
    list is empty its example sits there as a faint pill, and goes with the first value."""
    items = _KIT_LIST_ITEMS[field]
    adding = CreativeState.kit_pill_adding == field
    return rx.vstack(
        rx.vstack(
            rx.text(label, size="2", weight="medium"),
            rx.text(hint, size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
        ),
        rx.flex(
            rx.foreach(items, lambda item, index: _editable_pill(field, item, index)),
            rx.cond(items.length() == 0, _example_pill(example)),
            rx.cond(
                ~adding,
                rx.icon_button(
                    rx.icon("plus", size=T.ICON_SM),
                    on_click=CreativeState.open_kit_pill_input(field),
                    variant="soft",
                    color_scheme="gray",
                    size="1",
                    radius="full",
                    aria_label=f"Agregar a {label.lower()}",
                    margin_y="0.25rem",
                ),
            ),
            wrap="wrap",
            column_gap="0.75rem",
            row_gap="0.75rem",
            align="center",
            width="100%",
        ),
        rx.cond(
            adding,
            rx.form(
                rx.input(
                    value=CreativeState.kit_pill_drafts[field],
                    on_change=lambda value: CreativeState.set_kit_pill_draft(field, value),
                    on_key_down=CreativeState.kit_pill_add_key,
                    on_blur=CreativeState.kit_pill_add_blur,
                    auto_focus=True,
                    placeholder=f"Ej.: {example}",
                    width="100%",
                    size="2",
                    radius=_CONTROL_RADIUS,
                ),
                on_submit=CreativeState.add_kit_pill(field),
                reset_on_submit=False,
                width="100%",
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _example_pill(example: str) -> rx.Component:
    """A list's example while it has no values: a pill in outline, faint and prefixed
    "Ej.:", so it never reads as a value of the kit — it adds nothing and has no ✕.
    Wraps like a value pill (`_KIT_PILL_TEXT`); the italic's last glyph leans past its
    box, so the text keeps a hair of room on the right instead of being clipped."""
    return rx.badge(
        rx.text(f"Ej.: {example}", padding_right="0.15em", **_KIT_PILL_TEXT),
        size="2",
        variant="outline",
        color_scheme="gray",
        color=T.TEXT_FAINT,
        border_style="dashed",
        font_style="italic",
        title="Un ejemplo: agrega los tuyos con +",
        **_KIT_PILL_BOX,
    )


#: A kit list's values are sentences, not tokens (§ 2026-10-06, "las pills recortan el
#: contenido"): they wrap onto more lines instead of ending in "…" — a pill that hid a
#: third of an example hid what the copy is told to imitate. The radius is a fixed
#: half-height, not "full", so one line still reads as a pill and two as a rounded card.
_KIT_PILL_TEXT: dict[str, str] = {
    "white_space": "normal",
    "overflow_wrap": "anywhere",
    "text_align": "left",
    "line_height": "1.35",
}
_KIT_PILL_BOX: dict[str, str] = {
    "radius": "full",
    "border_radius": "0.875rem",
    "height": "auto",
    "padding_y": "0.3rem",
    "white_space": "normal",
    "max_width": "100%",
}


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
                        class_name="q-brand-swatch",
                        width="1.25rem",
                        height="1.25rem",
                        background=colour,
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


def _pill_button(**props: object) -> dict[str, object]:
    """A button reset to sit inside a pill: no chrome of its own."""
    return {
        "type": "button",
        "display": "flex",
        "align_items": "center",
        "background": "transparent",
        "border": "none",
        "padding": "0",
        "color": "inherit",
        "font": "inherit",
        "cursor": "pointer",
        **props,
    }


def _editable_pill(field: str, item: rx.Var[str], index: rx.Var[int]) -> rx.Component:
    """One value of a kit list on ¿Todo correcto? (§ request 2026-09-30): click it to
    edit it in place (Enter or leaving the input saves, Escape cancels, emptying it
    removes it), or ✕ to remove it."""
    editing = (CreativeState.kit_pill_edit_field == field) & (
        CreativeState.kit_pill_edit_index == index
    )
    return rx.cond(
        editing,
        rx.form(
            rx.input(
                value=CreativeState.kit_pill_edit_value,
                on_change=CreativeState.set_kit_pill_edit_value,
                on_blur=CreativeState.save_kit_pill_edit,
                on_key_down=CreativeState.kit_pill_edit_key,
                auto_focus=True,
                size="1",
                radius="full",
                min_width="12rem",
                aria_label="Editar valor",
            ),
            on_submit=CreativeState.save_kit_pill_edit,
            reset_on_submit=False,
        ),
        rx.badge(
            rx.el.button(
                rx.text(item, **_KIT_PILL_TEXT),
                rx.icon("pencil", size=11, opacity="0.55", flex_shrink="0"),
                on_click=CreativeState.start_kit_pill_edit(field, index),
                title="Editar",
                gap="0.3rem",
                min_width="0",
                **_pill_button(),
            ),
            rx.el.button(
                rx.icon("x", size=12),
                on_click=CreativeState.remove_kit_pill(field, index),
                aria_label="Quitar",
                flex_shrink="0",
                **_pill_button(),
            ),
            size="2",
            variant="surface",
            color_scheme="gray",
            gap="2",
            align_items="center",
            **_KIT_PILL_BOX,
        ),
    )


def _confirm_section(title: str, *children: rx.Component) -> rx.Component:
    return card(
        rx.vstack(
            _section_label(title),
            *children,
            spacing="4",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
        width="100%",
    )


def _step_confirm() -> rx.Component:
    """¿Todo correcto?: the recap of the kit AND, since 2026-10-05, where its five lists
    are filled (Enséñale a hablar and Lo que nunca debe decir left the wizard): each
    with what it is for, its example, in-place editing and an input to add. The voice
    and the tone sliders are configured later, in the Brand Kit editor. No logo row
    (per request) — the staged logo isn't part of this recap."""
    lists = {spec[0]: _kit_list_editor(*spec) for spec in _KIT_LISTS}
    return _step_body(
        _confirm_section(
            "Tu marca",
            _recap_row("¿Qué te hace distinto?", CreativeState.kit_positioning),
            _recap_row("¿Quién te compra?", CreativeState.kit_audience),
            _palette_recap_row(),
            _recap_row("Tipografía", CreativeState.kit_typography_summary),
        ),
        _confirm_section("Cómo habla tu marca", lists["do"], lists["dont"], lists["cta"]),
        _confirm_section(
            "Lo que nunca debe decir",
            lists["banned"],
            lists["claims"],
            callout(
                "Esto se comprueba siempre, incluso si desactivas el resto.",
                "warn",
                icon="shield-alert",
            ),
        ),
        rx.text(
            "Toca un valor para cambiarlo. Tu forma de hablar la eliges después, en «Tu marca».",
            size="1",
            color=T.TEXT_FAINT,
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
                src=_asset_src(BrandWizardState.logo_key),
                alt="Logo",
                height="6rem",
                max_width="100%",
                object_fit="contain",
            ),
            media_thumb("", size="6rem", round=True, icon="image", icon_size=28),
        ),
        _competitors_section(),
    )


def _window() -> rx.Component:
    """One step at a time. `rx.match` on the cursor, with step 0 as the fallback so an
    out-of-range cursor still renders a form instead of a blank screen."""
    return rx.fragment(_progress_trigger(BrandWizardState), _manual_steps())


def _progress_trigger(state: type[rx.State]) -> rx.Component:
    """Save-as-you-go's one hook (§ request 2026-10-02): an invisible box keyed by the
    step, so every step change — whichever handler made it — remounts it and fires
    `persist_progress` once. Nothing per handler to keep in sync."""
    return rx.box(key=state.step, on_mount=state.persist_progress, display="none")


def _manual_steps() -> rx.Component:
    return rx.match(
        BrandWizardState.step,
        (_M_IDENTITY_STEP, _step_identity()),
        (_M_HAS_LOGO_STEP, _step_has_logo()),
        (_M_LOGO_STEP, _step_logo(BrandWizardState.next_step)),
        (_M_TYPOGRAPHY_STEP, _step_typography()),
        (_M_PALETTE_STEP, _step_palette()),
        (_CONFIRM_STEP, _step_confirm()),
        (LAST_STEP, _step_insights()),
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


def _manual_can_continue() -> rx.Var[bool]:
    """Whether the CURRENT step's requirement is satisfied (§ request 2026-09-09) —
    gates `_controls`'s Continuar the same way `_connect_can_continue` gates the
    connect flow's, reading the exact same shared fields (`_identity_complete`/
    `_logo_step_complete` are the one place either flow checks them, so the two
    gates cannot drift). Every step not named below always returns True: Tipografía
    (optional) and ¿Todo correcto? (the examples and rules filled there are optional,
    as they were on their own screens before 2026-10-05)."""
    return rx.cond(
        _manual_busy(),
        False,  # § 2026-10-01: nothing moves while the voice or the brief is being read
        _manual_requirement(),
    )


def _manual_busy() -> rx.Var[bool]:
    return brand_documents.BrandDocumentState.brief_busy


def _manual_requirement() -> rx.Var[bool]:
    return rx.match(
        BrandWizardState.step,
        (_M_IDENTITY_STEP, _identity_complete()),
        (_M_HAS_LOGO_STEP, BrandWizardState.has_logo != ""),
        (_M_LOGO_STEP, _logo_step_complete()),
        (_M_PALETTE_STEP, CreativeState.kit_palette != ""),
        True,
    )


def _wizard_shell(*children: rx.Component) -> rx.Component:
    """The Brand Kit's frame: the panel alone, no sidebar (§ request 2026-10-02: "solo
    las views, más nada"). Every wizard page — the question, the connect flow and its
    account-setup detour, the manual flow — goes through here; the editor inside the
    session (`brand_kit_editor`) keeps the app's rail."""
    return app_shell(*children, rail=False)


def _controls() -> rx.Component:
    """The manual flow's foot in the step frame (PASOS-4): «Atrás» (never on step 1 —
    the way out is the head's «‹ Inicio»), «Seguir después» (save, then Inicio) and the
    primary: «Siguiente», gated by `_manual_can_continue`, or on the last step the
    finish (`_finish_button`'s label; `BrandWizardState.finish`)."""
    return step_foot(
        rx.cond(BrandWizardState.is_last, _finish_label(), NEXT_LABEL),
        step=BrandWizardState.step_n,
        on_primary=BrandWizardState.primary,
        on_back=BrandWizardState.prev_step,
        on_later=BrandWizardState.save_for_later,
        primary_disabled=~_manual_can_continue(),
        primary_loading=BrandWizardState.is_last & CreativeState.kit_saving,
    )


def _step_column_width(
    on_logo_step: rx.Var[bool],
    on_confirm: rx.Var[bool],
    *,
    on_typography: rx.Var[bool] | bool = False,
) -> rx.Var[str]:
    """The step column's width, shared by both flows (§ request 2026-09-30): Tu
    brandboard's tiles get a wide column once there is a brandboard to upload — as wide
    as one row of the four logo versions and centred in the card (`_BRANDBOARD_COLUMN_
    MAX`, § request 2026-10-05; the brief form keeps the narrow column), Tipografía gets
    room for its two tiles side by side (`_TYPOGRAPHY_COLUMN_MAX`), ¿Todo correcto? for
    its lists, and every other step keeps 34rem."""
    return rx.cond(
        on_logo_step & (BrandWizardState.has_logo == "si"),
        _BRANDBOARD_COLUMN_MAX,
        rx.cond(
            on_typography,
            _TYPOGRAPHY_COLUMN_MAX,
            rx.cond(on_confirm, "46rem", "34rem"),
        ),
    )


def _manual_column_width() -> rx.Var[str]:
    return _step_column_width(
        BrandWizardState.step == _M_LOGO_STEP,
        BrandWizardState.step == _CONFIRM_STEP,
        on_typography=BrandWizardState.step == _M_TYPOGRAPHY_STEP,
    )


def _kit_notices() -> rx.Component:
    return rx.vstack(
        rx.cond(CreativeState.kit_error != "", callout(CreativeState.kit_error, "error")),
        rx.cond(
            CreativeState.kit_notice != "",
            callout(CreativeState.kit_notice, "ok", icon="circle-check"),
        ),
        spacing="3",
        width="100%",
        max_width="34rem",
        align_self="center",
        align_items="center",
    )


def _frame_loading(content: rx.Component) -> rx.Component:
    """A wait inside the step frame (the kit loading, a profile read, the search for
    referentes): its own progress panel in the body; the head and its way out stay."""
    return card(
        content,
        padding="1.75rem",
        width="100%",
        display="flex",
        align_items="center",
        justify_content="center",
    )


def _frame_step(
    window: rx.Component,
    *,
    subtitle: rx.Var[str],
    column: rx.Var[str],
    first_step: rx.Var[bool],
    padding: rx.Var[str] | str = "1.75rem",
) -> rx.Component:
    """A step in the frame's body: its subtitle, then the step in its centred column
    on a card. A guest keeps «Usar otro correo» on the first step."""
    return rx.fragment(
        rx.text(subtitle, size="3", color=T.TEXT_MUTED, width="100%"),
        card(
            rx.vstack(
                window,
                rx.cond(first_step, _change_email_button()),
                width="100%",
                max_width=column,
                align_self="center",
                align_items="center",
                spacing="4",
            ),
            padding=rx.breakpoints(initial="1rem", sm=padding),
            width="100%",
            # a flex column, so the step's column centres in the card
            display="flex",
            flex_direction="column",
        ),
    )


def _or_ready_frame(frame: rx.Component) -> rx.Component:
    """The step frame, swapped for «Tu marca está lista» (a header and its body) while
    `BrandWizardState.brand_ready` — never over a failed save."""
    shown = BrandWizardState.brand_ready & (CreativeState.kit_error == "")
    return rx.cond(
        shown,
        rx.fragment(page_header("Tu marca", title_size="8"), page_body(_brand_ready_card())),
        frame,
    )


def brand_manual_index() -> rx.Component:
    """The manual flow in the step frame (PASOS-4, m-24852243; docs/design-system.md
    §4.5): «‹ Inicio» on every step, «Paso N de 7» with its bar and the step's name as
    the h1 in the fixed head; the step in the body; Atrás · Seguir después · Siguiente
    in the fixed foot. While the kit loads, the head stays and the foot waits."""
    loading = CreativeState.kit_loading | ~BrandWizardState.steps_ready
    return _wizard_shell(
        _or_ready_frame(
            step_frame(
                _kit_notices(),
                rx.cond(
                    loading,
                    _frame_loading(_loading_view("Cargando tu marca")),
                    rx.fragment(
                        rx.cond(
                            BrandWizardState.steps_ready,
                            step_sync(BrandWizardState.step_n, BrandWizardState.direction),
                        ),
                        _frame_step(
                            _window(),
                            subtitle=_heading_for(1),
                            column=_manual_column_width(),
                            first_step=BrandWizardState.step == 0,
                        ),
                    ),
                ),
                head=step_head(
                    rx.cond(loading, "Tu marca", _heading_for(0)),
                    step=BrandWizardState.step_n,
                    total=len(STEPS),
                    back_label=exit_label(),
                    on_exit=BrandWizardState.leave,
                ),
                foot=rx.cond(loading, rx.fragment(), _controls()),
                step=BrandWizardState.step_n,
                direction=BrandWizardState.direction,
                on_pop=BrandWizardState.pop_step,
                on_leave=BrandWizardState.leave_frame,
            )
        )
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


def _change_email_button() -> rx.Component:
    """Back to the screen that asks for the email (§ request 2026-10-02), at the bottom
    where Atrás would be — across from Continuar — on the question and on each flow's
    first step (the only steps with nothing behind them). Guests only: a session has no
    email to change here. The draft stays saved under its email (its progress too);
    `AuthState.leave_brand_draft` only forgets it in this browser."""
    return rx.cond(
        AuthState.is_guest,
        rx.button(
            rx.icon("mail", size=T.ICON_SM),
            "Usar otro correo",
            variant="ghost",
            color_scheme="gray",
            size="3",
            radius=_CONTROL_RADIUS,
            min_height="44px",  # N12, like every other footer control
            on_click=AuthState.leave_brand_draft,
            title=AuthState.guest_email,
        ),
    )


def brand_choice_index() -> rx.Component:
    """The entry the guest rail's «Marca» lands on (§ 2026-10-02: the Brand Kit is made
    before the login; inside a session there is only the editor, Negocio → Brand Kit,
    and `BrandConnectState.enter_brand_home` sends a login there) — a yes/no question instead of a
    manual-vs-connect fork (§ request 2026-09-09): every brand kit starts from a
    social profile now, "Empezar de cero" as a parallel path stopped making sense.
    "Sí" walks straight into the scraper (`/brand/connect`); "No" detours through
    `brand_connect_setup_index` first, then joins the exact same door. Same framing
    the old fork used: `page_header` (the wizard's own
    header was folded into the standard one) sits outside `page_body`, and the border
    below it grows to fill the panel (`flex="1"` on the card, `min_height` on this
    vstack so there is room to grow into) instead of stopping short and leaving bare
    panel background below it."""
    return _wizard_shell(
        page_header("Crea tu marca", "¿Tienes redes sociales para tu marca?", title_size="8"),
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
                            "Te ayudamos a crear tu cuenta en una red social antes de empezar.",
                            "/brand/connect/setup",
                        ),
                        spacing="4",
                        width="100%",
                        # Same centring as every step screen: the two options sit in the
                        # middle of the frame rather than at its top.
                        flex="1",
                        justify_content="center",
                    ),
                    # The same bottom row the steps have, with the one control this
                    # screen needs where Atrás would be (§ request 2026-10-02).
                    rx.hstack(_change_email_button(), rx.spacer(), width="100%", align="center"),
                    padding="1.75rem",
                    width="100%",
                    flex="1",
                    display="flex",
                    flex_direction="column",
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
#: rule the account-setup copy follows: a first-time user reads this as the actual
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
    return _wizard_shell(
        page_header(
            "Crea tu cuenta",
            "Necesitas un perfil en una red social antes de leer tu contenido.",
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
_NETWORK_REQUIRED = "Elige Instagram o TikTok para leer tu perfil."
_PROFILE_UNAVAILABLE = "No pudimos leer el perfil. Revisa el usuario e inténtalo de nuevo."
#: § request 2026-10-06: the account is another email's own account — said without naming
#: who, and without reading anything of it.
_ACCOUNT_TAKEN = (
    "Esta cuenta ya está registrada en Qualify con otro correo. Si es tuya, entra con el "
    "correo con el que la registraste."
)

#: (key, label, blurb, icon) — the icon is the same generic stand-in
#: `ACCOUNT_SETUP_INFO` already uses for each network (Lucide ships no brand-logo
#: icons, see that tuple's own comment), reused here so ¿Qué red usas? and Crea tu
#: cuenta read as one consistent visual language for the same two networks (§
#: request 2026-09-09 — a shared icon per option instead of one icon for the whole
#: step).
NETWORKS: tuple[tuple[str, str, str, str], ...] = (
    ("instagram", "Instagram", "Reels, carruseles y publicaciones.", "camera"),
    ("tiktok", "TikTok", "Videos cortos y fotos.", "music_2"),
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
    # ¿Qué red usas? and ¿Cuál es tu usuario? are ONE screen since 2026-10-05 (§ request
    # "vamos a unificar el qué red usas y cuál es tu usuario"): the handle on top, the
    # two networks as buttons below it — pressing one reads the profile on that network.
    ("Tu cuenta", "Escribe tu usuario y elige la red donde lo tienes."),
    ("Esto es lo que vemos", "Confirma que es tu perfil."),
    # Gone on 2026-10-05 (see the note above STEPS): Lo que te proponemos (it sat here),
    # the Google Maps pair (after Tu rubro), Tu brief de marca as its own screen (now the
    # top of ¿Quién es la marca?), Tu voz, ¿Cómo suena?, Enséñale a hablar and Lo que
    # nunca debe decir (their lists are filled on ¿Todo correcto?).
    #
    # ¿Eres influencer o una marca? comes BEFORE ¿Quién es la marca? (§ request
    # 2026-09-11, "invertir" the two).
    ("¿Eres influencer o una marca?", "Así te mostramos los pasos que sí aplican para ti."),
    # Tu rubro y ubicación (2026-09-11) — the input the creator discovery on
    # Resultados e insights needs; its hashtags are created on arrival from the
    # account's own description, category and latest posts (§ 2026-10-05).
    (
        "Tu rubro y ubicación",
        "Así buscamos negocios parecidos al tuyo en tu sector, tu país y tu ciudad.",
    ),
    _IDENTITY_HEADING,
    # ¿Tienes logo? / Tu logo — ALWAYS shown, right before Paleta de colores (§ request
    # 2026-09-16). They used to be skipped whenever the scraped profile had a picture,
    # which is nearly every account, so uploading a logo or asking for one through the
    # brief was unreachable. A profile picture is not a logo. An uploaded logo's colours
    # seed the palette on the next screen (`handle_logo_upload`). Same copy + renderers
    # the manual flow uses (`_step_has_logo`/`_step_logo`) via `_connect_step_has_logo`,
    # so the two flows cannot drift.
    ("¿Ya tienes logo?", "De tu respuesta depende el siguiente paso."),
    ("Tu logo", "Lo usaremos en cada publicación que crees."),
    _TYPOGRAPHY_HEADING,  # § request 2026-10-05, see the manual flow's STEPS
    ("Paleta de colores", "Los colores con los que se te reconoce."),
    ("¿Todo correcto?", "Revisa, completa los ejemplos y las reglas, y guarda."),
    # Referente, competencia o detractor (§ request 2026-09-11, "algo divertido antes
    # del resultado"): the accounts the discovery found, sorted by the operator into
    # three buckets by drag and drop or a tap. Optional — nothing blocks Continuar.
    (
        "¿Cómo ves estas cuentas?",
        "Toca la flecha de cada cuenta, o arrástrala: te inspira, compite contigo o no va contigo.",
    ),
    ("Así se ve tu cuenta hoy", "Revisa y termina."),
)
CONNECT_LAST = len(CONNECT_STEPS) - 1
_SORT_STEP = CONNECT_LAST - 1
_CONNECT_CONFIRM_STEP = CONNECT_LAST - 2

#: Named indices into `CONNECT_STEPS` — every skip, gate and renderer refers to these,
#: never to a literal, so the next reorder of the tuple is a one-place change.
_ACCOUNT_STEP = 0
_PROFILE_STEP = 1
_ACCOUNT_KIND_STEP = 2
_RUBRO_STEP = 3
_IDENTITY_STEP = 4
_LOGO_QUESTION_STEP = 5
_LOGO_UPLOAD_STEP = 6
_TYPOGRAPHY_STEP = 7
_PALETTE_STEP = 8
assert CONNECT_STEPS[_ACCOUNT_STEP][0] == "Tu cuenta"
assert CONNECT_STEPS[_PROFILE_STEP][0] == "Esto es lo que vemos"
assert CONNECT_STEPS[_ACCOUNT_KIND_STEP][0] == "¿Eres influencer o una marca?"
assert CONNECT_STEPS[_RUBRO_STEP][0] == "Tu rubro y ubicación"
assert CONNECT_STEPS[_IDENTITY_STEP] == _IDENTITY_HEADING
assert CONNECT_STEPS[_LOGO_QUESTION_STEP][0] == "¿Ya tienes logo?"
assert CONNECT_STEPS[_LOGO_UPLOAD_STEP][0] == "Tu logo"
assert CONNECT_STEPS[_TYPOGRAPHY_STEP] == _TYPOGRAPHY_HEADING
assert CONNECT_STEPS[_PALETTE_STEP][0] == "Paleta de colores"
assert _LOGO_UPLOAD_STEP + 1 == _TYPOGRAPHY_STEP and _TYPOGRAPHY_STEP + 1 == _PALETTE_STEP
assert _PALETTE_STEP + 1 == _CONNECT_CONFIRM_STEP
assert CONNECT_STEPS[_CONNECT_CONFIRM_STEP][0] == "¿Todo correcto?"
assert CONNECT_STEPS[_SORT_STEP][0] == "¿Cómo ves estas cuentas?"

#: The three buckets of the sort step — (key, title, blurb, icon).
BUCKETS: tuple[tuple[str, str, str, str], ...] = (
    ("referente", "Te inspira", "Te gustaría parecerte a esta cuenta.", "star"),
    ("competencia", "Compite contigo", "Le vende a tu mismo público.", "swords"),
    ("detractor", "No va contigo", "No se parece a tu marca.", "thumbs-down"),
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


#: A card of the influence ranking (§ request 2026-09-29): the kit's `DragCard`, which
#: `assets/rank-drag.js` moves — the same trick the deck's `_DropZone` uses.
_RankCard = DragCard


#: ¿Eres influencer o una marca?'s options — (key, title, blurb). "ambas" (§ request
#: 2026-09-11, "influencer y/o marca") behaves as a brand for every gate: it has a
#: business to list on Maps and a location the discovery should use.
ACCOUNT_KINDS: tuple[tuple[str, str, str], ...] = (
    ("marca", "Soy una marca o negocio", "Te preguntaremos tu rubro y dónde estás."),
    ("influencer", "Soy creador o influencer", "Buscaremos cuentas parecidas a la tuya."),
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
        return out, f"Caben {cap} etiquetas: quita alguna para agregar otra."
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
            "No encontramos etiquetas en lo que publica tu cuenta. Agrega las tuyas: "
            "con ellas buscamos."
        )
    return out, note


#: The shared hashtag catalog (`qualify_api.hashtags.catalog`), as the prefill's step
#: functions take it — the same object path the Alta's worker runs.
_HASHTAG_CATALOG = brand_prefill.CatalogHashtags()


def _prefill_ports() -> brand_prefill.PrefillPorts:
    """What `brand_prefill.prefill_brand_kit` talks to: the backend's own claim, cache,
    Scrape Creators read and hashtag catalog — the Alta's defaults. A function so tests
    can swap the whole set."""
    return brand_prefill.PrefillPorts(catalog=_HASHTAG_CATALOG)


def _generate_from_account(account: from_profile.AccountText) -> from_profile.Proposal | None:
    """Claude reads the account (`brand_prefill.generate_from_account`): a rubro phrase
    and the tags its content lives under. None without a key, with nothing to read, or
    when the call fails — every caller has a fallback."""
    return brand_prefill.generate_from_account(account, api_key=api_key_from_env)


def _propose_rubro(
    account: from_profile.AccountText,
) -> tuple[str, from_profile.Proposal | None]:
    """Tu rubro, autocompleted (§ third round of 2026-10-05, "que autocompletes el input de
    tu rubro"): `brand_prefill.propose_rubro`, the same step the Alta's prefill runs."""
    return brand_prefill.propose_rubro(account, api_key=api_key_from_env)


def _hashtags_db_first(
    tenant_id: UUID | None,
    seed: creator_discovery.DiscoverySeed,
    account: from_profile.AccountText,
    *,
    network: str = "",
    created: from_profile.Proposal | None = None,
) -> tuple[brand_prefill.HashtagChoice | None, str]:
    """Tu rubro's hashtags — the database, else the latest posts, else created
    (`brand_prefill.hashtags_db_first`, with this app's catalog). Returns the choice for
    `merge_suggestions`, or None with the note to show."""
    return brand_prefill.hashtags_db_first(
        tenant_id,
        seed,
        account,
        network=network,
        created=created,
        catalog=_HASHTAG_CATALOG,
        api_key=api_key_from_env,
    )


#: Every key a card may carry beyond `account_card`'s original ones, defaulted so a
#: card stored before they existed (or a manual one) renders the same (`card_view`).
_CARD_DEFAULTS: dict[str, str] = {
    "kind": "",
    "kind_label": "",
    "review": "",
    "reviewed_by": "",
    "manual": "",
    "fits": "",
    "note": "",
    # § 2026-10-01: the bio in full, the profile's link, the AI share, the reach signal
    "bio": "",
    "external_url": "",
    "ai": "",
    "signal": "",
}


def card_view(card: Mapping[str, object]) -> dict[str, str]:
    """A stored or fresh card as the state keeps it: every optional key present (a Var
    reading a missing key renders `undefined`), plus the picture's backend path."""
    out = {**_CARD_DEFAULTS, **{str(k): str(v) for k, v in card.items()}}
    out["avatar_src"] = creator_discovery.avatar_path(out)
    return out


def manual_outcome(
    card: Mapping[str, str], bucket: str, result: referentes_review.ManualResult
) -> tuple[str, str]:
    """The pop-up after a manual add: what happened, in the operator's words, and its
    tone — `warn` when the profile was not found or Claude thinks it does not fit."""
    title = next((t for b, t, _, _ in BUCKETS if b == bucket), "Te inspira")
    who = card.get("handle") or "La cuenta"
    parts = [f"Agregamos {who} a «{title}»."]
    tone = "ok"
    if result.missing:
        network = card.get("network") or ""
        parts.append(f"No encontramos ese perfil en {network}; la guardamos con lo que escribiste.")
        tone = "warn"
    if result.warning:
        parts.append(f"Ojo, la IA cree que no encaja: {result.warning}")
        tone = "warn"
    elif card.get("review"):
        kind = card.get("kind_label") or ""
        parts.append(f"{kind}: {card['review']}" if kind else card["review"])
    return " ".join(parts), tone


#: Networks the manual form offers, in the select's order.
MANUAL_NETWORK_OPTIONS: tuple[tuple[str, str], ...] = tuple(
    referentes_review.MANUAL_NETWORKS.items()
)


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


#: The connect flow's route: its `?paso=` is read only there (`load_saved_details` also
#: runs on /brand and /brand/kit).
CONNECT_ROUTE = "/brand/connect"
_CREATOR_SKIPS = frozenset(
    {_LOGO_QUESTION_STEP, _LOGO_UPLOAD_STEP, _TYPOGRAPHY_STEP, _PALETTE_STEP}
)


def connect_skipped(account_kind: str, logo_from_profile: bool) -> frozenset[int]:
    """THE rule of which `CONNECT_STEPS` a session skips (`BrandConnectState.
    _is_skipped`, see its docstring): the logo block for a creator; Tu logo while the
    profile picture stands as the logo."""
    skipped: set[int] = set()
    if account_kind == "influencer":
        skipped |= _CREATOR_SKIPS
    if logo_from_profile:
        skipped.add(_LOGO_UPLOAD_STEP)
    return frozenset(skipped)


def connect_visible(account_kind: str, logo_from_profile: bool) -> list[int]:
    """The step indices this owner walks, in order."""
    skipped = connect_skipped(account_kind, logo_from_profile)
    return [index for index in range(len(CONNECT_STEPS)) if index not in skipped]


def connect_position(step: int, account_kind: str, logo_from_profile: bool) -> tuple[int, int]:
    """(N, M) of «Paso N de M» over the visible steps (`steps_vm.step_position`)."""
    visible = [str(index) for index in connect_visible(account_kind, logo_from_profile)]
    return step_position(str(step), visible)


def connect_completes(
    *,
    profile_read: bool,
    account_kind: str,
    rubro_complete: bool,
    identity: bool,
    has_logo: str,
    logo_done: bool,
    palette: bool,
) -> list[bool]:
    """Whether each of the twelve `CONNECT_STEPS` is answered (the gates of
    `_connect_requirement`; Tu cuenta and Esto es lo que vemos need a read profile)."""
    return [
        profile_read,
        profile_read,
        account_kind != "",
        rubro_complete,
        identity,
        has_logo != "",
        logo_done,
        True,
        palette,
        True,
        True,
        True,
    ]


class BrandConnectState(rx.State):
    """Cursor and profile read for the connect flow. Kept apart from `BrandWizardState`
    so the two entry paths cannot fight over one cursor — the kit fields they share
    still live in `CreativeState`."""

    @rx.event(background=True)
    async def persist_progress(self) -> None:
        """Fired each time this flow's step changes (§ request 2026-10-02: "lo puede
        dejar a la mitad pero se guarda lo hecho en la db"): the half-written kit, the
        answers, the account as read and the position go to the database."""
        from .brand_finish import CONNECT_FLOW, save_progress

        await save_progress(self, CONNECT_FLOW)

    #: `load_saved_details` finished: until then a save would overwrite the stored
    #: answers with an empty session, so save-as-you-go waits for it.
    _details_loaded: bool = False
    #: The same, for the page: the Brand Kit editor decides what to show first only once
    #: the saved details are in (§ request 2026-10-05).
    details_loaded: bool = False
    #: The operator saved Tu voz y tono from the Brand Kit editor (§ request 2026-10-05:
    #: until then it is the first thing the editor shows). Stored in the `connect`
    #: document (`brand_finish._connect_document`) — a JSONB key, no migration.
    voice_configured: bool = False

    step: int = 0
    #: PASOS-4 (m-24852243): `data-dir` of the step frame's body, and whether this
    #: route's load has decided the step (until then the address is not written).
    direction: str = DIR_NEXT
    steps_ready: bool = False
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
    #: m-24852537: the copy of the profile picture the Alta kept in R2
    #: (`brand_kit_details.profile.pic_key`), carried so every save keeps it, and its
    #: `/r2media` view — shown before the `/avatar` proxy (the CDN link expires in days).
    profile_pic_key: str = ""
    profile_pic_content_type: str = ""
    profile_pic_view: str = ""
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
    #: lets `discovery_seed.seed_from_profile` detect (bio, Instagram category, the
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
    #: The run that is also naming the rubro (the input was empty): the whole step waits
    #: behind its progress screen, since the field it would fill is on it.
    filling_rubro: bool = False
    #: The rubro the current pills were found for — leaving the input with a DIFFERENT
    #: one runs the search again (`rubro_input_blur`).
    hashtags_rubro: str = ""
    hashtag_note: str = ""
    #: The hashtag input shows only after its "+" is pressed (§ request 2026-09-30).
    adding_hashtag: bool = False
    #: The Brand Kit editor's Resultados e insights reading the stored referentes back
    #: (`load_saved_referentes`).
    referentes_loading: bool = False

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
    #: The influence order of the sorted accounts on Resultados e insights (§ request
    #: 2026-09-29): account keys, most influential first, one list per bucket
    #: concatenated. Dragging a card rewrites it (`rank_drop`); stored as
    #: `brand_account_labels.position` (`sync_order`) and restored with the sort.
    #: Accounts not in it rank after the ordered ones, in the order the search found them.
    influence_order: list[str] = []
    #: The card being dragged on the ranking (`rank_pick`), "" otherwise.
    rank_dragging: str = ""
    #: Accounts the operator sorted that this search did NOT find again (a newer
    #: algorithm dropped them) — their decision still stands, so they stay in their
    #: bucket, with the card of the newest stored phase that found them. Never dealt
    #: into the deck: they are sorted already.
    kept_accounts: list[dict[str, str]] = []
    #: Accounts Claude's review dropped from this run's phases (`creator_discovery.
    #: apply_review`), each with its phase key and the reason — listed under the deck
    #: so a drop can be checked. Fresh runs only: a stored phase keeps what was shown.
    discarded_accounts: list[dict[str, str]] = []
    # -- A referente added by hand (`add_manual_account`): the search cannot find an
    # account with little activity, few followers or no TikTok / Instagram at all.
    manual_open: bool = False
    manual_input: str = ""
    manual_network: str = "instagram"
    manual_bucket: str = "referente"
    manual_note: str = ""
    adding_manual: bool = False
    manual_error: str = ""
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
        - Tu rubro y ubicación: ALWAYS shown since 2026-09-11 ("para cuando se es
          influencer también quiero que me deje escoger rubro y ubicación") — for an
          existing account it arrives prefilled from the profile read, which is the
          moment to correct it.
        - ¿Tienes logo?, Tu logo, Tipografía and Paleta de colores: skipped as a block for
          "influencer" (§ request 2026-09-29) — ¿Quién es la marca? goes straight to
          ¿Todo correcto? since the voice screens left the wizard (2026-10-05).
        - ¿Tienes brandboard?: a brand or "ambas" is ALWAYS asked, and since 2026-09-29
          nothing pre-answers it.
        - Tu brandboard: skipped while `logo_from_profile` stands — no screen offers
          that answer any more (§ request 2026-09-29), so in practice never.
        Lo que te proponemos and the Google Maps pair, which this used to skip
        conditionally, are gone altogether (§ request 2026-10-05)."""
        return index in connect_skipped(self.account_kind, self.logo_from_profile)

    @rx.var
    def step_n(self) -> int:
        """«Paso N de M» and `?paso=N`, over the steps this owner walks (H5: a creator
        skips the logo block, so the count never jumps from 5 to 10)."""
        return connect_position(self.step, self.account_kind, self.logo_from_profile)[0]

    @rx.var
    def step_m(self) -> int:
        return connect_position(self.step, self.account_kind, self.logo_from_profile)[1]

    @rx.var
    def is_last(self) -> bool:
        return self.step == CONNECT_LAST

    async def _completes(self) -> list[bool]:
        """Whether each VISIBLE step is answered, in order (`connect_completes`)."""
        wizard = await self.get_state(BrandWizardState)
        creative = await self.get_state(CreativeState)
        everything = connect_completes(
            profile_read=bool(self.profile_username),
            account_kind=self.account_kind,
            rubro_complete=self._rubro_complete(),
            identity=bool(creative.kit_positioning.strip() and creative.kit_audience.strip()),
            has_logo=wizard.has_logo,
            logo_done=(
                bool(wizard.logo_versions or wizard.brand_extras)
                if wizard.has_logo == "si"
                else bool(wizard.logo_brief_1.strip())
            ),
            palette=bool(creative.kit_palette.strip()),
        )
        visible = connect_visible(self.account_kind, self.logo_from_profile)
        return [everything[index] for index in visible]

    async def _apply_step_param(self) -> None:
        """`?paso=N` → the N-th VISIBLE step, never past the first unanswered one."""
        raw = step_param(self)
        if raw is None:
            return
        visible = connect_visible(self.account_kind, self.logo_from_profile)
        target = guard_step(parse_step_param(raw, len(visible)), await self._completes())
        index = visible[target - 1]
        old = connect_position(self.step, self.account_kind, self.logo_from_profile)[0]
        self.direction = step_direction(old, target, self.direction)
        self._land(index)

    @rx.event
    def leave_frame(self) -> None:
        """The frame unmounted: the next visit writes no address until its load."""
        self.steps_ready = False

    @rx.event
    async def pop_step(self) -> None:
        """The browser's «atrás»/«adelante» (`step_frame(on_pop=...)`). Idempotent."""
        if self.steps_ready and self.router.url.path.rstrip("/") == CONNECT_ROUTE:
            await self._apply_step_param()

    @rx.event
    def primary(self) -> rx.event.EventSpec | None:
        """The frame's primary: the finish on the last step, the count-up on the sort
        step (`advance_to_insights`), «Siguiente» everywhere else."""
        if self.step == CONNECT_LAST:
            return BrandConnectState.finish
        if self.step == _SORT_STEP:
            return BrandConnectState.advance_to_insights
        return BrandConnectState.next_step

    @rx.event(background=True)
    async def save_for_later(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Seguir después»: save, then Inicio (an account) — `leave_flow`."""
        from .brand_finish import CONNECT_FLOW

        async for event in leave_flow(self, CONNECT_FLOW, later=True):
            yield event

    @rx.event(background=True)
    async def leave(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """The head's «‹ Inicio» / «‹ Tu correo»: save, then go — `leave_flow`."""
        from .brand_finish import CONNECT_FLOW

        async for event in leave_flow(self, CONNECT_FLOW, later=False):
            yield event

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
        if target != self.step:
            self.direction = DIR_NEXT if target > self.step else DIR_BACK
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
        stretch — Esto es lo que vemos, since Lo que te proponemos left the flow
        (§ request 2026-10-05)."""
        return self.step == _PROFILE_STEP

    @rx.event
    def next_step(self) -> rx.event.EventSpec | None:
        """Continuar. Leaving Tu rubro y ubicación (re)starts the creator discovery
        when the answers differ from what the running search was seeded with —
        `run_discovery` handles the token; this only decides whether to fire it."""
        leaving_rubro = self.step == _RUBRO_STEP
        self.direction = DIR_NEXT
        self._land(self._walk(min(self.step + 1, CONNECT_LAST), +1))
        if leaving_rubro and self._answers() != self.discovery_answers:
            return BrandConnectState.run_discovery
        # § 2026-10-05: arriving at Tu rubro with no suggested hashtag yet, they are
        # created on their own from the account's description, category and latest posts
        if (
            self.step == _RUBRO_STEP
            and not self.suggesting_hashtags
            and not any(p["origin"] != "manual" for p in self.rubro_hashtags)
        ):
            return BrandConnectState.suggest_hashtags
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
        self.direction = DIR_BACK
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
    def set_sector(self, value: str) -> rx.event.EventSpec | None:
        """A creator has no rubro input — their category IS the rubro, so changing it
        looks for their hashtags again, the way leaving a brand's rubro input does."""
        changed = value != self.sector
        self.sector = value
        if changed and self.account_kind == "influencer" and self.step == _RUBRO_STEP:
            return BrandConnectState.suggest_hashtags
        return None

    @rx.event
    def set_rubro_text(self, value: str) -> None:
        self.rubro_text = value

    @rx.event
    def rubro_input_blur(self, value: str) -> rx.event.EventSpec | None:
        """Leaving Tu rubro (§ third round of 2026-10-05, "al salir del input cuando se
        edite se vuelve a ejecutar la tool"): an edited rubro looks for its hashtags
        again; the same one, or an empty field, changes nothing."""
        self.rubro_text = value
        rubro = value.strip()
        if not rubro or rubro == self.hashtags_rubro or self.suggesting_hashtags:
            return None
        return BrandConnectState.suggest_hashtags

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
        """Enter in the hashtag input (and leaving it, `hashtag_input_blur`): one
        hand-typed hashtag, normalised the way the catalog stores them (no `#`,
        lowercase, one token)."""
        self._add_typed_hashtag()

    def _add_typed_hashtag(self) -> None:
        raw = self.new_hashtag.strip()
        if not raw:
            return
        try:
            tag = normalize_tag(raw)
        except ValueError:
            # the input stays open with the text, so it can be fixed
            self.hashtag_note = "Una etiqueta es una sola palabra, sin espacios."
            return
        self.new_hashtag = ""
        self.adding_hashtag = False
        self.rubro_hashtags, self.hashtag_note = add_pills(
            self.rubro_hashtags, [{"tag": tag, "origin": "manual"}]
        )

    @rx.event
    def open_hashtag_input(self) -> None:
        """The pills' "+": only now does the input appear."""
        self.adding_hashtag = True
        self.hashtag_note = ""

    @rx.event
    def hashtag_input_key(self, key: str) -> None:
        """Escape closes the input and forgets what was typed."""
        if key == "Escape":
            self.adding_hashtag = False
            self.new_hashtag = ""

    @rx.event
    def hashtag_input_blur(self, value: str) -> None:
        """Leaving the input adds what was typed, like Enter (§ request 2026-09-30);
        left empty, it just puts the "+" back."""
        if not value.strip():
            self.adding_hashtag = False
            self.new_hashtag = ""
            return
        self.new_hashtag = value
        self._add_typed_hashtag()

    @rx.event
    def remove_hashtag(self, tag: str) -> None:
        self.rubro_hashtags = [item for item in self.rubro_hashtags if item["tag"] != tag]
        self.hashtag_note = ""

    @rx.event(background=True)
    async def suggest_hashtags(self) -> None:
        """Tu rubro y sus hashtags (§ third round of 2026-10-05). Runs on its own when the
        step opens with no suggestion yet (`next_step`) and again when the rubro is edited
        (`rubro_input_blur`) — there is no "Sugerir" button any more:

        1. An empty Tu rubro is autocompleted from what the account says about itself —
           description, category, latest posts (`_propose_rubro`).
        2. The hashtags: the database, else the latest posts' own hashtags, else created
           from the description and the posts (`_hashtags_db_first`, § fourth round).

        Background: the Claude runs take seconds."""
        async with self:
            if self.suggesting_hashtags:
                return
            self.suggesting_hashtags = True
            self.filling_rubro = self.account_kind != "influencer" and not self.rubro_text.strip()
            fill_rubro = self.filling_rubro
            self.hashtag_note = ""
            network = self.network
            handle = self.profile_username or self.username.strip()
            fallback_profile = {
                "username": self.profile_username,
                "bio": self.profile_bio,
                "category": self.profile_category,
            }
            sector_label = creator_discovery.NICHE_LABELS.get(self.sector, "")
            account = from_profile.AccountText(
                handle=self.profile_username,
                bio=self.profile_bio,
                category=self.profile_category,
                rubro=", ".join(p for p in (sector_label, self.rubro_text.strip()) if p),
                city=self.city.strip(),
                country=creator_discovery.country_name(self.country_code)
                if self.country_code
                else "",
            )
        ids = await self._referentes_ids()
        snapshot: dict[str, Any] | None = None
        if ids is not None and handle:
            try:
                snapshot = await asyncio.to_thread(
                    creator_cache_provider.cached_snapshot, ids[0], network, handle
                )
            except (SQLAlchemyError, OSError, ValueError) as exc:
                logger.warning("hashtags: profile snapshot unreadable: %s", exc)
                snapshot = None
            if snapshot:
                account = replace(
                    account,
                    bio=account.bio or str(snapshot.get("bio") or ""),
                    category=account.category or str(snapshot.get("category") or ""),
                    captions=tuple(str(c) for c in snapshot.get("recentCaptions") or ()),
                    used_hashtags=tuple(str(t) for t in snapshot.get("topHashtags") or ()),
                )
        created: from_profile.Proposal | None = None
        if fill_rubro:
            rubro, created = await asyncio.to_thread(_propose_rubro, account)
            async with self:
                if rubro and not self.rubro_text.strip():
                    self.rubro_text = rubro
                self.filling_rubro = False
                rubro_text = self.rubro_text.strip()
            account = replace(account, rubro=", ".join(p for p in (sector_label, rubro_text) if p))
        async with self:
            answers = {
                "sector": self.sector,
                "rubro_text": self.rubro_text.strip(),
                "country_code": self.country_code,
                "city": self.city.strip(),
            }
        seed = discovery_seed.seed_from_profile(snapshot or fallback_profile, **answers)
        choice, note = await asyncio.to_thread(
            _hashtags_db_first,
            ids[0] if ids is not None else None,
            seed,
            account,
            network=network,
            created=created,
        )
        async with self:
            self.suggesting_hashtags = False
            self.filling_rubro = False
            self.hashtags_rubro = answers["rubro_text"]
            if choice is not None:
                self.rubro_hashtags, self.hashtag_note = merge_suggestions(
                    self.rubro_hashtags, choice
                )
            else:
                self.hashtag_note = note

    @rx.event
    def analyze_on(self, key: str) -> rx.event.EventSpec | None:
        """Tu cuenta's Instagram / TikTok buttons (§ request 2026-10-05): the network is
        the button pressed, and pressing it reads the profile — the old two screens'
        choose-then-Analizar in one gesture."""
        if key not in scrapecreators_client.SUPPORTED_NETWORKS:
            return None
        self.network = key
        return BrandConnectState.analyze

    @rx.event
    def submit_account(self) -> rx.event.EventSpec | None:
        """Enter in Tu cuenta's field: reads the profile on the network already chosen
        (a walk resumed, a retry); with none yet, asks for one."""
        if self.network in scrapecreators_client.SUPPORTED_NETWORKS:
            return BrandConnectState.analyze
        self.error = _NETWORK_REQUIRED if self.username.strip() else _USERNAME_REQUIRED
        return None

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
    def answer_account_kind(self, value: str) -> rx.event.EventSpec | None:
        """¿Eres influencer o una marca?'s own choice handler — records the answer and
        moves on (to Tu rubro y ubicación). It RETURNS what `next_step` fires: arriving
        at Tu rubro creates the hashtags (§ 2026-10-05), and dropping that event here —
        as this handler did — meant they were never created on this, the usual, path."""
        self.account_kind = value
        return self.next_step()

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
        self.forget_kept_picture()
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
        self.adding_hashtag = False
        self.suggesting_hashtags = False
        self.filling_rubro = False
        self.hashtags_rubro = ""
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
        self.influence_order = []
        self.rank_dragging = ""
        self.kept_accounts = []
        self.discarded_accounts = []
        self.manual_error = ""
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
            # `card_view` resolves `avatar_src` — the backend path the card's picture is
            # served from (`creator_discovery.avatar_path` → `avatar_proxy.py`) — so a
            # cached result from before pictures existed gets one too, and defaults the
            # keys cards stored before the AI review lack.
            card_view(a)
            for a in phase.get("accounts") or []
            if isinstance(a, dict)
        ]
        discarded = [
            {
                "phase": key,
                "handle": str(d.get("handle") or ""),
                "network": str(d.get("network") or ""),
                "reason": str(d.get("reason") or ""),
            }
            for d in phase.get("discarded") or []
            if isinstance(d, dict)
        ]
        self.discarded_accounts = [
            d for d in self.discarded_accounts if d["phase"] != key
        ] + discarded
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
        # With the paid last resort (§ 2026-09-29): a picture whose URL arrived dead
        # (a vendor-cached profile read) is replaced now, not when a card is on screen.
        avatar_proxy.warm_avatars_in_background(accounts, refresh=avatar_proxy.fresh_vendor_url)

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

    @rx.var
    def results_note(self) -> str:
        """Why Resultados e insights' list is empty once the search finished: the first
        category's own note (a failed search says so), else a plain "nothing found"."""
        if self.discovering or self.discovered_accounts:
            return ""
        for key in creator_discovery.PHASES:
            if note := self._phase_note(key):
                return note
        return "Todavía no encontramos negocios parecidos al tuyo." if self.discovery_ran else ""

    def keep_picture_of(self, tenant_id: UUID, brand_id: UUID, profile: Any) -> None:
        """The saved `profile`'s kept picture (m-24852537): its key and content type, and
        a `/r2media` view of it — only for a kept picture of THIS tenant's brand
        (`kept_pictures.is_kept_key`); anything else is ignored. Not an event handler."""
        self.forget_kept_picture()
        key = profile.get("pic_key") if isinstance(profile, dict) else None
        if not kept_pictures.is_kept_key(tenant_id, brand_id, key):
            return
        self.profile_pic_key = str(key)
        self.profile_pic_content_type = str(profile.get("pic_content_type") or "image/jpeg")
        try:
            self.profile_pic_view = issue_view_path(
                tenant_id, self.profile_pic_key, "image", self.profile_pic_content_type
            )
        except Exception as exc:  # noqa: BLE001 - cosmetic: the proxy stands in
            logger.warning("brand connect: picture view not issued: %s", type(exc).__name__)
            self.profile_pic_view = ""

    def forget_kept_picture(self) -> None:
        """Drop the kept picture (a new read, or the account forgotten)."""
        self.profile_pic_key = ""
        self.profile_pic_content_type = ""
        self.profile_pic_view = ""

    @rx.var
    def profile_avatar_src(self) -> str:
        """The read account's own picture through the backend proxy (`avatar_proxy.py`),
        like every referente card — never the vendor's signed URL straight in an `<img>`:
        Instagram's expire (§ request 2026-09-29, "en algunas cuentas no carga la foto de
        perfil"), and the proxy serves its kept copy or finds a fresh one. The copy the
        Alta kept in R2 (m-24852537) comes first."""
        if self.profile_pic_view:
            return self.profile_pic_view
        return creator_discovery.avatar_path(
            {"network": self.network, "handle": self.profile_username, "avatar": self.profile_pic}
        )

    @rx.var
    def ranked_referentes(self) -> list[dict[str, str]]:
        """The referentes in influence order (`_rank`) — the ranking on Resultados."""
        return _rank(self.referente_accounts, self.influence_order)

    @rx.var
    def ranked_competencia(self) -> list[dict[str, str]]:
        return _rank(self.competencia_accounts, self.influence_order)

    @rx.var
    def has_ranking(self) -> bool:
        """Something was sorted as referente or competencia — the ranking replaces the
        plain list (an account only marked detractor is not ranked)."""
        return bool(self.ranked_referentes or self.ranked_competencia)

    def _phase_cards(self, key: str) -> list[dict[str, str]]:
        """One category's cards with their bucket key and current bucket."""
        out: list[dict[str, str]] = []
        for item in self._phase_accounts(key):
            account_key = _account_key(item)
            bucket = self.account_buckets.get(account_key, "")
            out.append({**item, "key": account_key, "bucket": bucket})
        return out

    def _stage_is_empty(self, index: int) -> bool:
        """A category with nothing in it (§ request 2026-09-30): its search finished,
        did not fail, and found no account. The deck skips it on its own; a failed one
        stays, since its Reintentar is something to do, and so does one still loading.

        Except the CITY one (§ 2026-10-05: "nunca está entrando los referentes de tu
        ciudad … solo me dice anterior en tu país"): skipping it made the city look
        like a step that never ran. Once its search ran it is shown, with its note
        ("No encontramos cuentas de Táchira…"), and Continuar goes on from there. Only
        a city that was never asked for (no city given) is still skipped."""
        key = creator_discovery.PHASES[index]
        if self._phase_accounts(key):
            return False
        note = self._phase_note(key)
        failed = note.startswith("No pudimos")
        pending = self.discovering and not self._phase_title(key) and not note
        if key == "local" and note and not note.startswith("Indica tu ciudad"):
            return False
        return not failed and not pending

    def _shown_stage(self) -> int:
        """The category actually on screen: `sort_stage`, or — when that one is empty —
        the next one that is not, else the previous one. Derived, never stored, so a
        category that fills up later (a Reintentar, a late phase) is shown again."""
        count = len(creator_discovery.PHASES)
        stage = min(max(self.sort_stage, 0), count - 1)
        if not self._stage_is_empty(stage):
            return stage
        for index in range(stage + 1, count):
            if not self._stage_is_empty(index):
                return index
        for index in range(stage - 1, -1, -1):
            if not self._stage_is_empty(index):
                return index
        return stage

    def _neighbour_stage(self, step: int) -> int | None:
        """The closest non-empty category before (`step=-1`) or after (`+1`) the one on
        screen, or None when there is none."""
        index = self._shown_stage() + step
        while 0 <= index < len(creator_discovery.PHASES):
            if not self._stage_is_empty(index):
                return index
            index += step
        return None

    @rx.var
    def stage_key(self) -> str:
        return creator_discovery.PHASES[self._shown_stage()]

    @rx.var
    def stage_label(self) -> str:
        return f"Categoría {self._shown_stage() + 1} de {len(creator_discovery.PHASES)}"

    @rx.var
    def nothing_to_sort(self) -> bool:
        """Every category came back empty: there is nothing to classify at all."""
        return not any(
            not self._stage_is_empty(index) for index in range(len(creator_discovery.PHASES))
        )

    @rx.var
    def stage_title(self) -> str:
        titles = {"sector": "En tu sector", "national": "En tu país", "local": "En tu ciudad"}
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
            "sector": "En tu sector",
            "national": "En tu país",
            "local": "En tu ciudad",
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
    def discovery_percent(self) -> int:
        """The referentes search's progress bar: each category found is a third, the
        one being searched counts as a third of a third so the bar moves meanwhile."""
        rows = self.discovery_progress
        if not rows:
            return 0
        done = sum(1 for row in rows if row["status"] == "done")
        running = any(row["status"] == "running" for row in rows)
        share = (done + (0.35 if running else 0.0)) / len(rows)
        return max(5, min(100, round(share * 100)))

    @rx.var
    def stage_discarded(self) -> list[dict[str, str]]:
        """What the AI review dropped from the category on screen."""
        key = self.stage_key
        return [d for d in self.discarded_accounts if d["phase"] == key]

    @rx.var
    def stage_discarded_label(self) -> str:
        count = len(self.stage_discarded)
        noun = "cuenta que no encaja" if count == 1 else "cuentas que no encajan"
        return f"La IA descartó {count} {noun} con tu marca"

    @rx.var
    def manual_accounts(self) -> list[dict[str, str]]:
        """The referentes the operator added by hand, in whichever bucket."""
        return [a for a in self.discovered_accounts if a.get("manual") == "1"]

    @rx.var
    def manual_placeholder(self) -> str:
        if self.manual_network in ("web", "otro"):
            return "Ej.: Café del Parque o cafedelparque.co"
        return "Ej.: @cafedelparque o instagram.com/cafedelparque"

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
    def toggle_manual(self) -> None:
        self.manual_open = not self.manual_open
        self.manual_error = ""

    @rx.event
    def set_manual_input(self, value: str) -> None:
        self.manual_input = value
        self.manual_error = ""

    @rx.event
    def set_manual_network(self, value: str) -> None:
        if value in referentes_review.MANUAL_NETWORKS:
            self.manual_network = value

    @rx.event
    def set_manual_bucket(self, value: str) -> None:
        if value in {b for b, _, _, _ in BUCKETS}:
            self.manual_bucket = value

    @rx.event
    def set_manual_note(self, value: str) -> None:
        self.manual_note = value

    @rx.event
    def remove_manual(self, key: str) -> rx.event.EventSpec:
        """Take an account out of its bucket — a manual one, or (§ request 2026-10-05,
        the ✕ on a ranking card) one the search found: its label is cleared
        (`sync_labels`), and a card with no label is not shown in the ranking — the
        stored card stays for provenance only, and a searched one can be sorted again."""
        buckets = dict(self.account_buckets)
        buckets.pop(key, None)
        self.account_buckets = buckets
        self.kept_accounts = [c for c in self.kept_accounts if _account_key(c) != key]
        return BrandConnectState.sync_labels

    @rx.event(background=True)
    async def add_manual_account(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """A referente the search could not find (§ request 2026-09-25): little activity,
        few followers or no TikTok / Instagram at all. Read from the vendor when it is
        on a network we read (1 credit, remembered), reviewed by Claude with the same
        tool as the search (`referentes_review.add_manual_account`) — which never
        refuses it: the operator decides, the review only warns — stored with the
        brand's manual referentes and sorted into the chosen bucket."""
        async with self:
            if self.adding_manual:
                return
            try:
                target = referentes_review.parse_manual(self.manual_input, self.manual_network)
            except ValueError as exc:
                self.manual_error = str(exc)
                return
            self.adding_manual = True
            self.manual_error = ""
            note = self.manual_note.strip()
            bucket = self.manual_bucket
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
            pills = [dict(item) for item in self.rubro_hashtags]
            creative = await self.get_state(CreativeState)
            positioning = creative.kit_positioning.strip()
            audience = creative.kit_audience.strip()
        yield

        result: referentes_review.ManualResult | None = None
        ids = await self._referentes_ids()
        try:
            profile = (
                await asyncio.to_thread(
                    creator_cache_provider.cached_snapshot, ids[0], network, handle
                )
                if ids is not None
                else None
            )
            seed = discovery_seed.seed_from_profile(profile or fallback, **answers)
            if pills:
                seed, _ = seed_with_pills(seed, pills)
            brief = referentes_review.brand_brief(
                seed,
                bio=str((profile or fallback).get("bio") or ""),
                category=str((profile or fallback).get("category") or ""),
                positioning=positioning,
                audience=audience,
            )
            result = await asyncio.to_thread(
                referentes_review.add_manual_account,
                target,
                brief,
                note=note,
                payload_cache=creator_pool_provider.payload_cache(ids[0] if ids else None),
            )
            if ids is not None:
                # § 2026-10-01: the shared pool learns this account too
                await asyncio.to_thread(
                    creator_pool_provider.record_pool, ids[0], [result.candidate], seed
                )
                try:
                    await asyncio.to_thread(
                        referentes_provider.save_manual_account,
                        ids[0],
                        ids[1],
                        result.candidate,
                        result.card,
                        brand_handle=handle,
                    )
                except (SQLAlchemyError, ValueError) as exc:
                    # Still added for this session; only the reuse is lost.
                    logger.warning("referentes: could not store a manual account: %s", exc)
        except (ValueError, OSError) as exc:
            logger.warning("manual referente failed: %s", exc)
        async with self:
            self.adding_manual = False
            if result is None:
                self.manual_error = "No pudimos agregar esa cuenta ahora. Inténtalo de nuevo."
                return
            card = card_view(result.card)
            key = _account_key(card)
            self.kept_accounts = [c for c in self.kept_accounts if _account_key(c) != key] + [card]
            self.account_buckets = {**self.account_buckets, key: bucket}
            message, tone = manual_outcome(card, bucket, result)
            self.manual_input = ""
            self.manual_note = ""
            self.manual_open = False
        yield BrandConnectState.sync_labels
        # § request 2026-10-05: what happened is a pop-up, never a message left on the page
        yield brand_documents.notify(message, tone)

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
        """No non-empty category before this one (the empty ones are skipped)."""
        return self._neighbour_stage(-1) is None

    @rx.var
    def is_last_stage(self) -> bool:
        return self._neighbour_stage(+1) is None

    @rx.event
    def next_sort_stage(self) -> None:
        """Siguiente: the next category with something in it — an empty one is jumped
        over (§ request 2026-09-30). With none left, the deck stays where it is."""
        target = self._neighbour_stage(+1)
        self.sort_stage = self._shown_stage() if target is None else target
        self.stage_cursor = 0

    @rx.event
    def prev_sort_stage(self) -> None:
        target = self._neighbour_stage(-1)
        self.sort_stage = self._shown_stage() if target is None else target
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

    @rx.event(background=True)
    async def finish(self) -> AsyncIterator[rx.event.EventSpec]:
        """The connect flow's final button (§ request 2026-10-01): save EVERYTHING —
        the kit, the brandboard, the answers and the account as read — and only then
        move on (`brand_finish.save_brand_kit`)."""
        from .brand_finish import CONNECT_FLOW, save_brand_kit

        if not await save_brand_kit(self, CONNECT_FLOW):
            await _explain_finish_failure(self)
            return
        async with self:
            self._reset_fields()
            navigation = await _finish_navigation(self)
        yield brand_documents.BrandDocumentState.reset_documents
        if navigation is not None:
            yield navigation

    @rx.event(background=True)
    async def load_saved_details(self) -> None:
        """The Brand Kit editor (§ request 2026-10-01): the connect flow's saved
        answers and the account as read, with its metrics, back into this state — only
        where the session holds nothing of its own. On /brand/connect it is also how a
        walk left halfway resumes (§ 2026-10-02): the saved position puts the cursor back
        where it was."""
        from .brand_finish import CONNECT_FLOW, PROGRESS_KEY, load_saved, session_ids

        # m-24842965: entering the wizard opens the steps, never a card left from before
        async with self:
            (await self.get_state(BrandWizardState)).brand_ready = _asks_for_ready_card(self)
            on_route = self.router.url.path.rstrip("/") == CONNECT_ROUTE
            if on_route and self.router.url.path.rstrip("/") == CONNECT_ROUTE:
                self.steps_ready = False
        ids = await session_ids(self)
        saved = None
        if ids is not None:
            try:
                saved = await asyncio.to_thread(load_saved, ids[0], ids[1])
            except SQLAlchemyError as exc:
                logger.warning("brand kit details unreadable: %s", type(exc).__name__)
        if saved is None:
            async with self:
                self.details_loaded = True  # nothing to read: the editor must not wait on it
                if on_route and self.router.url.path.rstrip("/") == CONNECT_ROUTE:
                    await self._enter_steps()
            return
        connect, profile = saved.details.connect, saved.details.profile
        raw_progress = (connect or {}).get(PROGRESS_KEY)
        progress = raw_progress if isinstance(raw_progress, dict) else {}
        async with self:
            self._details_loaded = True
            self.details_loaded = True
            self.voice_configured = bool((connect or {}).get("voice_configured"))
            if (
                progress.get("flow") == CONNECT_FLOW
                and progress.get("completed") is False
                and self.step == 0
            ):
                self.started_without_socials = bool(progress.get("started_without_socials"))
                self.rubro_asked = bool(progress.get("rubro_asked"))
                self.logo_from_profile = bool(progress.get("logo_from_profile"))
                self.profile_pic_is_real = bool(progress.get("profile_pic_is_real"))
                try:
                    self.step = max(0, min(int(progress.get("step", 0)), CONNECT_LAST))
                except (TypeError, ValueError):
                    self.step = 0
            if connect and not (self.network or self.rubro_text or self.city):
                self.network = str(connect.get("network", ""))
                self.username = str(connect.get("username", ""))
                self.account_kind = str(connect.get("account_kind", ""))
                self.has_maps = str(connect.get("has_maps", ""))
                self.sector = str(connect.get("sector", ""))
                self.rubro_text = str(connect.get("rubro_text", ""))
                self.hashtags_rubro = self.rubro_text.strip()  # its pills come with it
                self.country_code = str(connect.get("country_code", ""))
                self.city = str(connect.get("city", ""))
                self.rubro_hashtags = [
                    {str(k): str(v) for k, v in item.items()}
                    for item in connect.get("hashtags", [])
                    if isinstance(item, dict)
                ]
                if not self.discovery_signals:
                    self.discovery_signals = [
                        chip
                        for chip in (
                            self.rubro_text,
                            ", ".join(c for c in (self.city, self.country_code) if c),
                            *(f"#{item.get('tag', '')}" for item in self.rubro_hashtags),
                        )
                        if chip and chip != "#"
                    ]
            if profile and not self.profile_username:
                self.profile_username = str(profile.get("username", ""))
                self.profile_fullname = str(profile.get("fullname", ""))
                self.profile_bio = str(profile.get("bio", ""))
                self.profile_category = str(profile.get("category", ""))
                self.profile_followers = str(profile.get("followers", ""))
                self.profile_followers_count = int(profile.get("followers_count", 0) or 0)
                self.profile_pic = str(profile.get("pic", ""))
                self.keep_picture_of(ids[0], ids[1], profile)
                metrics = [m for m in profile.get("metrics", []) if isinstance(m, dict)]
                try:
                    self._set_metrics(metrics)
                    self.metric_values = list(self.metric_targets)  # no count-up on entry
                except (KeyError, TypeError, ValueError):
                    self._set_metrics([])
            if on_route and self.router.url.path.rstrip("/") == CONNECT_ROUTE:
                await self._enter_steps()

    async def _enter_steps(self) -> None:
        """PASOS-4: once the saved walk is back, `?paso=N` (guarded) decides the step,
        and the address may be written from now on (`step_sync`). Under the lock."""
        await self._apply_step_param()
        self.steps_ready = True

    @rx.event
    async def finish_to_signals(self) -> rx.event.EventSpec | None:
        """The final button («Terminar mi marca»), on Resultados e insights — the TRUE
        final screen. Replaces Finalizar entirely (§ request 2026-09-05): same reset
        `restart` does, but the destination is `_finish_navigation`'s, not the fork — the same
        "regardless of the process" way `BrandWizardState.finish_to_signals` fires for
        the manual flow's own final screen."""
        self._reset_fields()
        return await _finish_navigation(self)

    @rx.event(background=True)
    async def advance_stage_if_exhausted(self) -> AsyncIterator[None]:
        """Chained by `assign()` when a decision leaves the current category with
        nothing left to classify (§ request 2026-09-14: "que cuando se acaben los
        referentes pase a la siguiente categoria y si no hay categorias que vaya a
        la otra view"). Waits `_STAGE_ADVANCE_DELAY` — long enough for the panel's
        hit-flash/the fly-ghost/the drag-release shrink to finish reading before the
        deck changes under the operator — then re-checks: a `Reintentar` or a slow
        phase landing more cards in the meantime cancels it. Moves to the next
        category; on the last one (`local`) it does NOTHING — § request 2026-10-05
        ("al terminar el drag and drop no quiero que se vaya a la otra view
        directamente, quiero que eso sea manual"): the deck shows "Todas clasificadas"
        and Resultados e insights is reached only through Continuar
        (`advance_to_insights`). Until then it used to chain that handler itself."""
        await asyncio.sleep(_STAGE_ADVANCE_DELAY)
        async with self:
            if self.has_current_card or self.stage_pending or self.stage_failed:
                return
            if not self.is_last_stage:
                self.next_sort_stage()
        yield

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
                # Defensive: the network buttons set it before calling this. A dev
                # backend restart can still wipe it under a page that survived — ask for
                # the network rather than surface Scrape Creators' `unsupported network`.
                self.step = _ACCOUNT_STEP
                self.error = _NETWORK_REQUIRED
                return
            self.error = ""
            self.analyzing = True
            network, handle = self.network, self.username.strip()
            auth = await self.get_state(AuthState)
            session_tenant_id = brand_tenant_id(auth)
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        yield

        # § request 2026-10-06: the account is claimed for this brand BEFORE anything of
        # it is read — cache included — so another email's own account never reaches
        # this session. No Brand Kit session means no brand to claim it for: no read.
        # The claim, the read (the tenant's cache first, § 2026-10-01) and what it says
        # are `brand_prefill.prefill_brand_kit` — the same run the Alta makes (PB-3);
        # `propose=False`: here the operator walks the rest, nothing is written.
        brand_id = await self._session_brand(tenant_id)
        if tenant_id is None or brand_id is None:
            async with self:
                self.analyzing = False
                self.error = _PROFILE_UNAVAILABLE
            return
        result = await asyncio.to_thread(
            brand_prefill.prefill_brand_kit,
            tenant_id,
            brand_id,
            network,
            handle,
            propose=False,
            ports=_prefill_ports(),
        )
        if not result.read or result.profile is None:
            # The vendor detail stays in the server log (`brand_prefill`); what reaches
            # the screen is the one generic, translated message every other
            # provider-call failure in this flow uses — or that the account is taken.
            async with self:
                self.analyzing = False
                self.error = (
                    _ACCOUNT_TAKEN
                    if result.outcome is brand_prefill.PrefillOutcome.ACCOUNT_TAKEN
                    else _PROFILE_UNAVAILABLE
                )
            return
        profile = result.profile
        if result.fetched_live:
            await self._record_read(tenant_id, network, handle, profile)

        followers = profile.get("followers")
        async with self:
            self.profile_username = str(profile.get("username", ""))
            self.profile_fullname = str(profile.get("fullName", ""))
            self.profile_bio = str(profile.get("bio", ""))
            self.profile_category = str(profile.get("category", ""))
            self.profile_followers = f"{followers:,}".replace(",", ".") if followers else "—"
            self.profile_followers_count = int(followers) if followers else 0
            self.profile_pic = str(profile.get("profilePicUrl", ""))
            self.forget_kept_picture()  # a new read: the previous account's copy goes
            if self.logo_from_profile:
                await self._forget_profile_picture_logo()  # the previous read's picture
            self.logo_from_profile = False  # a new read: its picture was not taken yet
            self.profile_pic_is_real = False  # checked below, once the read is on screen
            read_pic, read_handle = self.profile_pic, self.profile_username
            # Real figures over the window (`recentPosts` of this same read).
            self._set_metrics(result.metrics)
            # Prefill Tu rubro y ubicación with what the read lets us detect (bio,
            # Instagram category, the account's own hashtags) — the step then only
            # shows for an existing account when something is still missing.
            self.sector = result.sector
            self.country_code = result.country_code
            self.city = result.city
            self.rubro_asked = False
            self._clear_discovery()
            self.analyzing = False
            self.step = _PROFILE_STEP
            # § request 2026-09-11: the search is slow, so it starts NOW, from what the
            # profile alone says, and runs while the operator walks the kit steps; the
            # rubro step restarts it only if it changes the seed (`next_step`). A fresh
            # start has nothing to seed from until that step.
            detected = result.seed
            start_now = (
                not self._is_fresh()
                and detected is not None
                and bool(detected.niches or detected.hashtags)
            )
        if start_now:
            yield BrandConnectState.run_discovery
        # After the read is on screen and the search has started: whether its picture is
        # real (not the network's default silhouette). It used to PRE-ANSWER ¿Tienes
        # logo? with "Mi foto de perfil es mi logo" (§ request 2026-09-21); that answer
        # is gone (§ request 2026-09-29), so ¿Tienes brandboard? always opens blank.
        is_real = await self._picture_is_real(network, read_handle, read_pic)
        async with self:
            if self.profile_pic == read_pic:
                self.profile_pic_is_real = is_real

    @staticmethod
    async def _session_brand(tenant_id: UUID | None) -> UUID | None:
        """The session's brand (the eldest, like every Brand Kit screen), or None — no
        Brand Kit session, no brand, or the database unreachable. Must NOT be called
        while holding the lock."""
        if tenant_id is None:
            return None
        try:
            return await asyncio.to_thread(default_brand_id, tenant_id)
        except SQLAlchemyError as exc:
            logger.warning("brand connect: the session's brand is unreadable: %s", exc)
            return None

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
        # (tenant, brand, user) when the session has them — then phases, the sort and
        # every profile read live in Postgres (`referentes_provider`,
        # `creator_cache_provider`). Without them (no login, e.g. the offline tests)
        # nothing is remembered: the run reads live and keeps its results to itself.
        ids = await self._referentes_ids()
        try:
            profile = (
                await asyncio.to_thread(
                    creator_cache_provider.cached_snapshot, ids[0], network, handle
                )
                if ids is not None
                else None
            )
            seed = discovery_seed.seed_from_profile(profile or fallback, **answers)
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

            # Claude reviews each phase's shortlist (version 9): what is not a real peer
            # of the brand is dropped, the rest carries marca / creador. No API key → no
            # reviewer, and the search runs unreviewed.
            reviewer = referentes_review.make_reviewer(
                referentes_review.brand_brief(
                    seed,
                    bio=str((profile or fallback).get("bio") or ""),
                    category=str((profile or fallback).get("category") or ""),
                )
            )
            # § 2026-10-01: every vendor call asks the shared pool first
            # (`creator_pool_provider.PayloadCache`); without a session, live as before.
            cache = creator_pool_provider.payload_cache(ids[0] if ids else None)
            runner = creator_discovery.PhasedDiscovery(seed, payload_cache=cache, reviewer=reviewer)
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
                if ids is not None:
                    # everything this run has seen so far, into the shared pool
                    await asyncio.to_thread(
                        creator_pool_provider.record_pool,
                        ids[0],
                        list(runner.pool.values()),
                        seed,
                    )
                if cache is not None:
                    logger.info(
                        "referentes %s: %d vendor answers from the pool, %d from the vendor",
                        key,
                        cache.hits,
                        cache.misses,
                    )
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
                        "No pudimos buscar negocios parecidos ahora. Inténtalo más tarde."
                    )
        finally:
            if runner is not None:
                await asyncio.to_thread(runner.close)
            restored, kept = await self._stored_sort(ids, my_id)
            async with self:
                on_screen = [*self.sector_accounts, *self.national_accounts, *self.local_accounts]
            order = await self._stored_order(ids, [*on_screen, *kept])
            async with self:
                if self.discovery_run_id == my_id and order and not self.influence_order:
                    # Like the sort: an order made in this session while the search ran
                    # wins over the stored one.
                    self.influence_order = order
                if self.discovery_run_id == my_id:
                    if restored:
                        # A decision made in this session while the search ran wins
                        # over the stored one; the next `sync_labels` writes it.
                        self.account_buckets = {**restored, **self.account_buckets}
                        self._persisted_buckets = {**self._persisted_buckets, **restored}
                    if ids is not None:
                        self.kept_accounts = [card_view(card) for card in kept]
                    self.discovering = False
                    self.discovery_running = ""

    @rx.event(background=True)
    async def enter_brand_home(self) -> AsyncIterator[rx.event.EventSpec]:
        """/brand's entry, for a login and a guest alike (§ request 2026-10-02): a
        finished kit goes to the editor (Negocio → Brand Kit), a kit left halfway back
        into its wizard, and no kit yet stays on the "¿Tienes redes?" question — which is
        where `AuthState.require_login` sends a session without a complete kit."""
        from .brand_finish import tenant_kit_status

        async with self:
            auth = await self.get_state(AuthState)
            tenant = brand_tenant_id(auth)
            tenant_id = tenant_uuid(tenant) if tenant else None
        if tenant_id is None:
            return
        try:
            status = await asyncio.to_thread(tenant_kit_status, tenant_id)
        except SQLAlchemyError as exc:
            logger.warning("brand kit status unreadable: %s", type(exc).__name__)
            return
        if status.completed:
            yield rx.redirect("/brand/kit")
        elif status.resume_route is not None:
            yield rx.redirect(status.resume_route)

    @rx.event(background=True)
    async def load_saved_referentes(self) -> None:
        """The Brand Kit editor's Resultados e insights (§ request 2026-09-30): the
        brand's referentes as they were last left — phases, sort, kept cards and the
        influence order — read from Postgres, with no search and no credits. A search
        this session already ran (or is running) wins: its state is left alone."""
        async with self:
            if self.discovery_ran or self.discovering:
                return
            self.referentes_loading = True
        ids = await self._referentes_ids()
        saved: referentes_provider.SavedReferentes | None = None
        if ids is not None:
            try:
                saved = await asyncio.to_thread(referentes_provider.load_saved, ids[0], ids[1])
            except SQLAlchemyError as exc:
                logger.warning("referentes: stored referentes unreadable: %s", exc)
        async with self:
            self.referentes_loading = False
            if saved is None or self.discovery_ran or self.discovering:
                return
            self._clear_discovery()
            for phase in saved.phases:
                self._apply_phase(phase)
            self.account_buckets = dict(saved.buckets)
            self._persisted_buckets = dict(saved.buckets)
            self.kept_accounts = [card_view(card) for card in saved.kept]
            self.influence_order = list(saved.order)
            # A search found before (a walk resumed, § 2026-10-02): arriving at the sort
            # step shows it instead of buying it again.
            if saved.phases:
                self.discovery_ran = True

    # -- Postgres persistence of phases and the sort (`referentes_provider`) --------

    async def _record_read(self, tenant_id: UUID, network: str, handle: str, profile: dict) -> None:
        """The read just made, into the creator history (`growth_provider`, 2026-10-01):
        the brand's own figures and posts at this moment. Never fails the analysis — a
        row lost is a point of the series lost, nothing more."""
        try:
            await asyncio.to_thread(
                growth_provider.record_profile_read, tenant_id, network, handle, profile
            )
        except SQLAlchemyError as exc:
            logger.warning("creator history: profile read not recorded: %s", exc)

    async def _referentes_ids(self) -> tuple[UUID, UUID, UUID | None] | None:
        """(tenant, brand, acting user) for the session, or None — no login, no brand,
        or the database unreachable. Must NOT be called while holding the state lock."""
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = brand_tenant_id(auth)
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
            return None  # no session: nothing remembered, nothing to reuse
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
            return  # no session: the result lives in this walk only
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
            # § 2026-10-01: each referente's size today, a point of its own series
            await asyncio.to_thread(growth_provider.record_discovered, ids[0], result.accounts)
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

    # -- The influence ranking on Resultados e insights (§ request 2026-09-29) --------

    @rx.event
    def rank_pick(self, key: str) -> None:
        """A card on the ranking was lifted (`assets/rank-drag.js` fires `dragstart` on
        it); `rank_drop` on the card it is released over does the move."""
        self.rank_dragging = key

    @rx.event
    def rank_drop(self, target_key: str) -> rx.event.EventSpec | None:
        """The lifted card takes `target_key`'s place — inside the same bucket and the
        same group only (pinned among pinned, the rest among the rest)."""
        source, self.rank_dragging = self.rank_dragging, ""
        if not source or source == target_key:
            return None
        return self._reorder(source, target_key)

    def _reorder(self, source: str, target_key: str) -> rx.event.EventSpec | None:
        lists = [self.ranked_referentes, self.ranked_competencia]
        for i, ranked in enumerate(lists):
            keys = [a["key"] for a in ranked]
            if source not in keys:
                continue
            if target_key not in keys:
                return None
            moved = _move_in_ranking(ranked, source, keys.index(target_key))
            if moved is None:
                return None
            orders = [[a["key"] for a in other] for other in lists]
            orders[i] = moved
            self.influence_order = [key for order in orders for key in order]
            return BrandConnectState.sync_order
        return None

    @rx.event(background=True)
    async def sync_order(self) -> None:
        """Writes the influence order to Postgres (`brand_account_labels.position`),
        serialized with `sync_labels` so a position never lands before its label."""
        ids = await self._referentes_ids()
        if ids is None:
            return
        tenant_id, brand_id, _user_id = ids
        async with _labels_lock(brand_id):
            async with self:
                order = list(self.influence_order)
            try:
                await asyncio.to_thread(referentes_provider.write_order, tenant_id, brand_id, order)
            except (SQLAlchemyError, ValueError) as exc:
                # Left un-persisted: the next move writes the whole order again.
                logger.warning("referentes: could not store the influence order: %s", exc)

    async def _stored_order(
        self, ids: tuple[UUID, UUID, UUID | None] | None, cards: list[dict[str, str]]
    ) -> list[str]:
        """The stored influence order of these cards (`referentes_provider.load_order`)."""
        if ids is None or not cards:
            return []
        try:
            return await asyncio.to_thread(referentes_provider.load_order, ids[0], ids[1], cards)
        except SQLAlchemyError as exc:
            logger.warning("referentes: stored influence order unreadable: %s", exc)
            return []


# ---------------------------------------------------------------------------
# The screens specific to this flow


def _network_button(key: str, label: str, icon: str) -> rx.Component:
    """One of Tu cuenta's two networks (§ request 2026-10-05): pressing it reads the
    profile on that network. Disabled until a handle is typed — nothing to read yet."""
    return rx.button(
        rx.icon(icon, size=T.ICON_SM),
        label,
        type="button",
        on_click=BrandConnectState.analyze_on(key),
        disabled=BrandConnectState.username.strip() == "",
        variant=rx.cond(BrandConnectState.network == key, "solid", "surface"),
        size="3",
        radius=_CONTROL_RADIUS,
        width="100%",
    )


def _connect_step_account() -> rx.Component:
    """Tu cuenta — ¿Qué red usas? and ¿Cuál es tu usuario? as one screen (§ request
    2026-10-05): the Usuario field on top and the two networks as buttons under it,
    each one the screen's way forward (`analyze_on`), so there is no Continuar. Wrapped
    in `rx.form` (`_hidden_submit` included) so Enter in the field reads the profile on
    the network already chosen (`submit_account`)."""
    return rx.form(
        _step_body(
            _labeled_input(
                "Usuario",
                BrandConnectState.username,
                BrandConnectState.set_username,
                "Ej.: cafedelparque.cuc",
            ),
            rx.grid(
                *(_network_button(key, label, icon) for key, label, _blurb, icon in NETWORKS),
                columns="2",
                spacing="3",
                width="100%",
            ),
            rx.cond(
                BrandConnectState.error != "",
                callout(BrandConnectState.error, "error"),
            ),
            icon="at-sign",
        ),
        _hidden_submit(),
        on_submit=BrandConnectState.submit_account,
        width="100%",
    )


def _connect_step_profile() -> rx.Component:
    return _step_body(
        card(
            rx.vstack(
                _profile_avatar("5.5rem", 28),
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


def _connect_step_has_logo() -> rx.Component:
    """Same question and copy as the manual flow's `_step_has_logo`, asked of every
    account right before Paleta de colores (§ request 2026-09-16). Cannot
    reuse `_step_has_logo` as-is: its choice cards call `BrandWizardState.
    answer_has_logo`, which advances `BrandWizardState.step` — a cursor this flow
    never reads. `BrandConnectState.answer_has_logo` writes the same `has_logo`
    field but advances the right cursor.

    "Mi foto de perfil es mi logo" is no longer offered (§ request 2026-09-29, "quita el
    mi foto de perfil es mi logo"), and `analyze` no longer pre-answers it."""
    return _step_body(
        *(
            _choice_card(
                title,
                blurb,
                BrandWizardState.has_logo == value,
                BrandConnectState.answer_has_logo(value),
            )
            for value, title, blurb in BRANDBOARD_ANSWERS
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
    """Tu rubro y ubicación — behind a progress screen while the hashtags are being
    suggested (§ request 2026-10-01): one Claude tool run that reports no progress, so
    the bar creeps and the screen goes away when the pills land. The creep is paced to
    the run as measured (`packages/api/evals/hashtag_ai`: 2-4 turns, 8-14 s live, p50
    9.4 s) — the run itself is already the eval's pick for quality, not for speed."""
    # § third round of 2026-10-05: the whole step waits only while the rubro itself is
    # being filled in; a re-run after an edit waits inside the hashtags block
    return rx.cond(
        BrandConnectState.suggesting_hashtags & BrandConnectState.filling_rubro,
        progress_panel(
            "Preparando tu rubro y tus etiquetas",
            "Leemos tu descripción, tu categoría y tus últimas publicaciones.",
            steps=None,
            creep_seconds=20,
        ),
        _rubro_fields(),
    )


def _rubro_fields() -> rx.Component:
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
                # autocompleted from the account; leaving it edited looks for its
                # hashtags again (§ third round of 2026-10-05 — no "Sugerir" button)
                rx.input(
                    value=BrandConnectState.rubro_text,
                    on_change=BrandConnectState.set_rubro_text,
                    on_blur=BrandConnectState.rubro_input_blur,
                    placeholder="Ej.: cafetería de especialidad para llevar",
                    width="100%",
                    size="3",
                    height="2.75rem",
                    radius=_CONTROL_RADIUS,
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
                placeholder="Ej.: Cúcuta",
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
                "Con esto buscamos negocios parecidos al tuyo en tu sector, tu país y tu ciudad.",
                "Lo completamos con lo que leímos de tu perfil. Corrígelo si hace falta.",
            ),
            size="2",
            color=T.TEXT_MUTED,
            text_align="center",
        ),
        icon="map-pin",
    )


def _hashtag_pill_body(item: rx.Var[dict[str, str]], *, suggested: bool) -> rx.Component:
    return removable_pill(
        # § request 2026-10-02: a hair of space between the "#" and the word
        rx.fragment(rx.el.span("#", margin_right="2px"), item["tag"]),
        BrandConnectState.remove_hashtag(item["tag"]),
        suggested=suggested,
        remove_label="Quitar esta etiqueta",
    )


def _hashtag_pill(item: rx.Var[dict[str, str]]) -> rx.Component:
    """One pill: accent for a suggestion (hover shows Claude's reason), neutral for
    one the operator typed; the ✕ removes it either way."""
    suggested = rx.tooltip(
        _hashtag_pill_body(item, suggested=True),
        content=rx.cond(item["reason"] != "", item["reason"], "Sugerido para tu rubro"),
    )
    typed = _hashtag_pill_body(item, suggested=False)
    return rx.cond(item["origin"] == "manual", typed, suggested)


def _rubro_hashtags_block() -> rx.Component:
    """The hashtags the search will use, as pills (§ request 2026-09-25): found for the
    rubro (`suggest_hashtags`, on arrival and after each edit of the rubro) and/or typed
    here, each removable. While a re-run looks for them, the block is its progress bar."""
    return rx.cond(
        BrandConnectState.suggesting_hashtags,
        progress_panel(
            "Buscando etiquetas para tu rubro",
            "En nuestro catálogo, luego en tus publicaciones y, si no hay, los creamos.",
            steps=None,
            creep_seconds=15,
        ),
        _rubro_hashtags_editor(),
    )


def _rubro_hashtags_editor() -> rx.Component:
    return rx.vstack(
        rx.text("Etiquetas para buscar negocios parecidos", size="2", weight="medium"),
        # § request 2026-09-30: no input until the "+" is pressed — the pills, then a
        # "+" at their end; pressing it swaps the "+" for the input (Enter adds,
        # Escape or leaving it empty puts the "+" back).
        rx.flex(
            rx.foreach(BrandConnectState.rubro_hashtags, _hashtag_pill),
            rx.cond(
                ~BrandConnectState.adding_hashtag,
                rx.icon_button(
                    rx.icon("plus", size=T.ICON_SM),
                    on_click=BrandConnectState.open_hashtag_input,
                    variant="soft",
                    color_scheme="gray",
                    size="1",
                    radius="full",
                    aria_label="Agregar etiqueta",
                    margin_y="0.25rem",
                ),
            ),
            wrap="wrap",
            # § request 2026-10-05, "un spacing entre hashtags": 12 px between pills, and
            # the same between rows when they wrap (was 8 px, read as one block)
            column_gap="0.75rem",
            row_gap="0.75rem",
            align="center",
            width="100%",
        ),
        rx.cond(
            BrandConnectState.adding_hashtag,
            rx.form(
                rx.input(
                    value=BrandConnectState.new_hashtag,
                    on_change=BrandConnectState.set_new_hashtag,
                    on_key_down=BrandConnectState.hashtag_input_key,
                    on_blur=BrandConnectState.hashtag_input_blur,
                    auto_focus=True,
                    placeholder="Ej.: #cafedeespecialidad",
                    width="100%",
                    size="2",
                    radius=_CONTROL_RADIUS,
                ),
                on_submit=BrandConnectState.add_hashtag,
                reset_on_submit=False,
                width="100%",
            ),
        ),
        rx.cond(
            BrandConnectState.hashtag_note != "",
            rx.text(BrandConnectState.hashtag_note, size="1", color=T.TEXT_MUTED),
            rx.cond(
                BrandConnectState.rubro_hashtags.length() > 0,
                rx.text(
                    "Buscaremos negocios parecidos con estas etiquetas. Quita las que no encajen.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _metric_tile(item: rx.Var[dict[str, str]]) -> rx.Component:
    """One metric of the read account, compact enough to sit three in a row beside the
    profile (§ request 2026-10-05, the results screen's header). Same figure, label and
    hint as the `stat_card` it replaces."""
    return rx.vstack(
        rx.text(item["label"], size="1", color=T.TEXT_MUTED),
        rx.text(item["value"], size="6", weight="bold", class_name="q-nums", line_height="1.1"),
        rx.text(item["hint"], size="1", color=T.TEXT_FAINT, line_height="1.3"),
        spacing="1",
        align_items="start",
        class_name="q-metric-tile",
        width="100%",
        min_width="0",
    )


def _metric_grid() -> rx.Component:
    """One tile per entry of `BrandConnectState.metric_cards` — real figures, already
    formatted server-side (see that computed var), up to three in a row."""
    return rx.grid(
        rx.foreach(BrandConnectState.metric_cards, _metric_tile),
        columns=rx.breakpoints(initial="1", xs="3"),
        spacing="2",
        width="100%",
    )


def _insights_profile() -> rx.Component:
    """The read account: picture, handle, followers."""
    return rx.hstack(
        _profile_avatar("3.5rem", 22),
        rx.vstack(
            rx.text(BrandConnectState.profile_username, size="4", weight="bold"),
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
        min_width="0",
    )


def _insights_header() -> rx.Component:
    """Resultados e insights' header (§ request 2026-10-05): the read profile and its
    metrics in ONE band — profile on the left, the metric tiles on the right, stacked on
    a phone — where they used to be two blocks one under the other. Same content: the
    metrics are still skipped for a new account or when nothing was computable. Shared
    with the Brand Kit editor, which shows it only while this session holds the read."""
    metrics = rx.vstack(
        _section_label(f"Últimos {scrapecreators_client.METRICS_WINDOW_DAYS} días"),
        _metric_grid(),
        spacing="2",
        width="100%",
        align_items="start",
    )
    return card(
        rx.cond(
            ~BrandConnectState.is_new_account & BrandConnectState.has_metrics,
            rx.grid(
                _insights_profile(),
                metrics,
                grid_template_columns=rx.breakpoints(
                    initial="minmax(0, 1fr)", sm="minmax(0, 1fr) minmax(0, 1.7fr)"
                ),
                gap="1.25rem",
                align_items="center",
                width="100%",
            ),
            _insights_profile(),
        ),
        padding="1.25rem 1.5rem",
        width="100%",
    )


def _connect_step_insights() -> rx.Component:
    """The TRUE final screen of the whole flow (§ CONNECT_STEPS, `CONNECT_LAST`) —
    after ¿Todo correcto?, not before it. Redesigned 2026-10-05 (UI only, same content):
    the whole card width (`_RESULTS_COLUMN_MAX`, it used to be a 34rem column), the
    profile and its metrics in one header band (`_insights_header`), then the
    referentes — one grid of compact cards, sector, country and city merged
    (`_discovery_section`, § 2026-10-06) or, once the operator sorted, the influence
    ranking with Referentes and Competencia side by side (`_ranking_panel`). Its Finalizar-replacing
    CTA (`_finish_button`) lives in `_connect_controls`.

    The metrics are REAL (2026-09-10) and cover the last
    `scrapecreators_client.METRICS_WINDOW_DAYS` days; they are skipped for a brand-new
    account (§ 2026-09-09) or when nothing was computable (`has_metrics`)."""
    return rx.vstack(
        _insights_header(),
        _discovery_section(),
        rx.cond(BrandConnectState.has_ranking, _ranking_panel()),
        spacing="5",
        width="100%",
        align_items="stretch",
        class_name="q-settle",
    )


def _kind_flag(item: rx.Var[dict[str, str]]) -> rx.Component:
    """Marca / Creador / Medio, as the AI review read the account (hover: its reason).
    Nothing for an unreviewed card or an `otro`."""
    return rx.cond(
        item["kind_label"] != "",
        rx.tooltip(
            rx.badge(
                rx.match(
                    item["kind"],
                    ("marca", rx.icon("store", size=12)),
                    ("creador", rx.icon("user-round", size=12)),
                    rx.icon("newspaper", size=12),
                ),
                item["kind_label"],
                variant="soft",
                size="1",
                gap="1",
            ),
            content=rx.cond(item["review"] != "", item["review"], "Según la revisión de la IA"),
        ),
    )


def _signal_flags(item: rx.Var[dict[str, str]]) -> rx.Component:
    """What tells an account apart at a glance (§ request 2026-10-01): **IA** when the
    videos the search saw carry the platform's own "made with AI" label (`ai` = how many
    of how many, hover for the words), and **Quizá paga anuncios** when its reach is far
    above the phase's with far less interaction per view (`signal`, the reason on
    hover) — the same test the organic growth estimate runs, here on the search's own
    sightings. Neither says "not AI" / "organic": a card without a flag is simply one
    the search saw nothing on."""
    return rx.fragment(
        rx.cond(
            item["ai"] != "",
            rx.tooltip(
                tone_badge(rx.text("IA ", item["ai"]), "info", icon="bot"),
                content=item["ai"].to(str)
                + " de los vídeos vistos llevan la etiqueta de contenido hecho con IA que "
                "pone la propia red (declarada por el creador o detectada).",
            ),
        ),
        rx.cond(
            item["signal"] != "",
            rx.tooltip(
                tone_badge("Quizá paga anuncios", "warn", icon="megaphone"),
                content=item["signal"],
            ),
        ),
    )


def _bio_block(item: rx.Var[dict[str, str]], **props: object) -> rx.Component:
    """The bio in full (§ request 2026-10-01: web addresses, contacts) — the blurb when
    the search only saw a caption — and the link the profile points at."""
    return rx.fragment(
        rx.cond(
            item["bio"] != "",
            rx.text(
                item["bio"],
                size="2",
                color=T.TEXT_MUTED,
                white_space="pre-line",
                max_width="100%",
                overflow_wrap="anywhere",
                **props,
            ),
            rx.cond(
                item["blurb"] != "",
                rx.text(
                    item["blurb"],
                    size="2",
                    color=T.TEXT_MUTED,
                    max_width="100%",
                    overflow_wrap="anywhere",
                    **props,
                ),
            ),
        ),
        rx.cond(
            item["external_url"] != "",
            rx.hstack(
                rx.icon("link", size=12, color=T.TEXT_FAINT, flex_shrink="0"),
                rx.text(
                    item["external_url"],
                    size="1",
                    color=T.tone_color("accent", 11),
                    min_width="0",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                spacing="1",
                align="center",
                min_width="0",
                max_width="100%",
                overflow="hidden",
            ),
        ),
    )


def _review_line(item: rx.Var[dict[str, str]], **props: object) -> rx.Component:
    """Claude's one-line reason under a card — a warning tone when it thinks a manual
    account does not fit."""
    return rx.cond(
        item["review"] != "",
        rx.hstack(
            rx.cond(
                item["fits"] == "no",
                rx.icon("triangle-alert", size=12, color=T.tone_color("warn", 11), flex_shrink="0"),
                rx.icon("sparkles", size=12, color=T.TEXT_FAINT, flex_shrink="0"),
            ),
            rx.text(
                item["review"],
                size="1",
                color=T.TEXT_FAINT,
                min_width="0",
                overflow_wrap="anywhere",
                **props,
            ),
            spacing="1",
            align="start",
            max_width="100%",
        ),
    )


def _discovery_account(item: rx.Var[dict[str, str]]) -> rx.Component:
    """One referente as a compact card of the results grid (§ request 2026-10-05, UI
    only — same fields as the full-width row it replaces): picture, handle, network and
    what it is on top; followers and likes; the bio clamped to two lines (whole on the
    profile); Claude's reason as the footer. The whole card links to the public profile
    (new tab). The picture comes through `_avatar` — the backend proxy, never the
    vendor's signed URL (which expires within hours; see `avatar_proxy.py`)."""
    return rx.link(
        card(
            rx.vstack(
                rx.hstack(
                    _avatar(item, "2.5rem", 18),
                    rx.vstack(
                        mono(item["handle"], size="2", max_width="100%", overflow_wrap="anywhere"),
                        rx.hstack(
                            tag(item["network"]),
                            _kind_flag(item),
                            _signal_flags(item),
                            spacing="1",
                            align="center",
                            wrap="wrap",
                        ),
                        spacing="1",
                        align_items="start",
                        min_width="0",
                    ),
                    spacing="3",
                    align="center",
                    width="100%",
                    min_width="0",
                ),
                rx.hstack(
                    rx.text(item["followers"], " seguidores", size="1", color=T.TEXT_MUTED),
                    rx.cond(
                        item["likes"] != "",
                        rx.text("♥ ", item["likes"], size="1", color=T.TEXT_MUTED),
                    ),
                    spacing="3",
                    align="center",
                    wrap="wrap",
                ),
                _bio_block(item, class_name="q-clamp-2"),
                _review_line(item),
                spacing="2",
                align_items="start",
                width="100%",
                min_width="0",
            ),
            padding="0.9rem 1rem",
            width="100%",
            height="100%",
            min_width="0",
            overflow="hidden",
            interactive=True,
        ),
        href=item["url"],
        is_external=True,
        display="block",
        width="100%",
        height="100%",
        text_decoration="none",
        color="inherit",
    )


#: The results grid (§ 2026-10-05): as many ~16rem cards per row as the width fits.
_RESULTS_GRID = {
    "display": "grid",
    "grid_template_columns": "repeat(auto-fill, minmax(min(100%, 16rem), 1fr))",
    "gap": "0.75rem",
    "width": "100%",
}


def _discovery_list() -> rx.Component:
    """Every account the search found, as ONE grid of compact cards (§ request
    2026-10-06: "no quiero la separación entre el país… solo quiero la lista") — the
    sector, the country and the city merged, each account once, in the order they were
    found (`discovered_accounts`). While nothing has landed: skeleton cards (no spinner
    on the Brand Kit); finished empty: why (`results_note`). Shared with the Brand Kit
    editor."""
    return rx.cond(
        BrandConnectState.discovered_accounts.length() > 0,
        rx.box(
            rx.foreach(BrandConnectState.discovered_accounts, _discovery_account),
            **_RESULTS_GRID,
        ),
        rx.cond(
            BrandConnectState.discovering,
            rx.box(*(skeleton_card(3) for _ in range(3)), **_RESULTS_GRID),
            rx.cond(
                BrandConnectState.results_note != "",
                rx.text(BrandConnectState.results_note, size="2", color=T.TEXT_FAINT),
            ),
        ),
    )


def _rank_card(item: rx.Var[dict[str, str]], bucket: str) -> rx.Component:
    """One cell of the influence ranking grid: its position, picture and handle. The
    card IS the control (§ request 2026-09-29, same gestures as the deck): a click opens
    the profile (`data-profile-url`), a long press lifts it for `assets/rank-drag.js` to
    drag onto another card. `data-rank-group` (bucket + pinned/rest) is what keeps a drop
    inside its own grid and group."""
    pinned = item["group"] == RANK_PINNED
    return _RankCard.create(
        rx.vstack(
            rx.hstack(
                rx.badge(
                    "#",
                    item["rank"],
                    variant="soft",
                    radius="full",
                    size="1",
                ),
                rx.cond(
                    pinned,
                    rx.hstack(
                        rx.icon("pin", size=12),
                        rx.text("Fijado", size="1"),
                        spacing="1",
                        align="center",
                        color=T.tone_color("accent", 11),
                    ),
                ),
                rx.spacer(),
                # § request 2026-10-05: the ✕ that takes it out of the ranking (a button,
                # so `rank-drag.js` neither drags nor opens the profile from it)
                rx.tooltip(
                    rx.icon_button(
                        rx.icon("x", size=12),
                        on_click=BrandConnectState.remove_manual(item["key"]),
                        variant="ghost",
                        color_scheme="gray",
                        size="1",
                        radius="full",
                        aria_label="Quitar " + item["handle"].to(str) + " del ranking",
                    ),
                    content="Quitar del ranking",
                ),
                align="center",
                width="100%",
            ),
            _avatar(item, "3.5rem", 22),
            rx.vstack(
                mono(item["handle"], size="2"),
                rx.text(item["followers"], " seguidores", size="1", color=T.TEXT_MUTED),
                rx.hstack(_signal_flags(item), spacing="1", wrap="wrap", justify="center"),
                spacing="0",
                align="center",
                min_width="0",
                width="100%",
                text_align="center",
                overflow="hidden",
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        # `.q-rank-card` (`assets/qualify-brand.css`) is the card material under the
        # motion `rank-drag.js` drives; `--pinned` the accent wash of the hand-added ones
        class_name=rx.cond(pinned, "q-rank-card q-rank-card--pinned", "q-rank-card"),
        custom_attrs={
            "data-rank-group": f"{bucket}:" + item["group"].to(str),
            "data-rank-key": item["key"],
            "data-profile-url": item["url"],
            "role": "link",
            "tabindex": "0",
            "aria-label": "Abrir el perfil de " + item["handle"].to(str),
        },
        on_drag_start=BrandConnectState.rank_pick(item["key"]),
        on_drop=BrandConnectState.rank_drop(item["key"]),
        width="100%",
        min_width="0",
    )


_asset_script = asset_script


#: The deck's and the ranking's pointer scripts, run when their screen mounts. They used
#: to be `head_components` only, which go through react-helmet and on Reflex < 0.9.9
#: could be dropped around hydration (measured 2026-10-01 on a 0.9.7 venv; fixed
#: upstream in 0.9.9, see the note on `head_components` in Qualify.py). Both files
#: guard against running twice, so the head copy (kept) and this one never stack
#: listeners.
_DECK_DRAG_JS = _asset_script("deck-drag.js")
_RANK_DRAG_JS = _asset_script("rank-drag.js")


def _script_on_mount(code: str) -> rx.Component:
    return rx.box(display="none", on_mount=rx.call_script(code))


def _ranking_grid(title: str, bucket: str, accounts: rx.Var[list[dict[str, str]]]) -> rx.Component:
    return rx.cond(
        accounts.length() > 0,
        rx.vstack(
            rx.hstack(
                _section_label(title),
                rx.text(accounts.length(), size="1", color=T.TEXT_FAINT),
                spacing="2",
                align="center",
            ),
            rx.box(
                rx.foreach(accounts, lambda item: _rank_card(item, bucket)),
                # the width decides how many fit in a row — Referentes and Competencia
                # sit side by side on a wide screen (§ 2026-10-05), so each grid only
                # has half the card
                display="grid",
                grid_template_columns="repeat(auto-fill, minmax(min(100%, 8.5rem), 1fr))",
                gap="0.75rem",
                width="100%",
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
    )


def _ranking_panel() -> rx.Component:
    """Resultados e insights' influence ranking (§ requests 2026-09-29): the referentes
    and the competencia as a grid of cards, read left to right and top to bottom — that
    reading order IS the influence order. A click on a card opens the profile; a long
    press lifts it and dropping it on another card takes that card's place. The accounts
    added by hand stay pinned first and only move among themselves."""
    return rx.vstack(
        rx.vstack(
            rx.text("Ranking de influencia", size="3", weight="bold"),
            rx.text(
                "Mantén pulsada una card y suéltala sobre otra para cambiar su posición: de"
                " izquierda a derecha y de arriba abajo, de la que más influye en tu marca a"
                " la que menos. Un clic abre el perfil. Las que agregaste a mano van fijadas"
                " primero.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            spacing="1",
            align_items="start",
        ),
        _script_on_mount(_RANK_DRAG_JS),
        rx.grid(
            _ranking_grid("Te inspiran", "referente", BrandConnectState.ranked_referentes),
            _ranking_grid("Compiten contigo", "competencia", BrandConnectState.ranked_competencia),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="5",
            width="100%",
            align_items="start",
        ),
        spacing="4",
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
                "Buscar negocios parecidos",
                variant="soft",
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandConnectState.run_discovery,
            ),
            rx.cond(
                BrandConnectState.has_ranking,
                # § request 2026-09-29: the operator's own sorting (referentes and
                # competencia) is the ranking now (`_ranking_panel`), not a list here.
                rx.fragment(),
                _discovery_list(),
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


#: The two groups of the influence ranking (§ request 2026-09-29): the accounts added by
#: hand are PINNED ahead of the searched ones, and a card only moves inside its group.
RANK_PINNED = "pinned"
RANK_REST = "rest"


def _rank(accounts: list[dict[str, str]], order: list[str]) -> list[dict[str, str]]:
    """One bucket's accounts in influence order: pinned (added by hand) first, then the
    rest; inside each group the operator's `order`, then — for accounts never ordered —
    the order the search found them. Each row gets its `group` and 1-based `rank`."""
    index = {key: i for i, key in enumerate(order)}

    def sort_key(pair: tuple[int, dict[str, str]]) -> tuple[int, int, int]:
        found_at, account = pair
        pinned = 0 if account.get("manual") == "1" else 1
        ordered = index.get(account["key"])
        return (
            pinned,
            0 if ordered is not None else 1,
            ordered if ordered is not None else found_at,
        )

    ranked = sorted(enumerate(accounts), key=sort_key)
    return [
        {
            **account,
            "group": RANK_PINNED if account.get("manual") == "1" else RANK_REST,
            "rank": str(position + 1),
        }
        for position, (_found_at, account) in enumerate(ranked)
    ]


def _move_in_ranking(
    ranked: list[dict[str, str]], source: str, target_index: int
) -> list[str] | None:
    """`ranked`'s keys with `source` moved to `target_index`, or None when the move
    would cross between the pinned and the other accounts (or `source` is not there)."""
    keys = [a["key"] for a in ranked]
    if source not in keys or not 0 <= target_index < len(keys):
        return None
    if ranked[keys.index(source)]["group"] != ranked[target_index]["group"]:
        return None
    keys.remove(source)
    keys.insert(target_index, source)
    return keys


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
    return media_thumb(
        _AVATAR_BASE + item["avatar_src"],
        has=item["avatar_src"] != "",
        size=size,
        round=True,
        icon="user-round",
        icon_size=icon_size,
        pointer_events="none",
        custom_attrs={
            "loading": "lazy",
            "referrerpolicy": "no-referrer",
            "draggable": "false",
        },
    )


def _profile_avatar(size: str, icon_size: int) -> rx.Component:
    """The read account's own picture, through the same proxy and with the same
    icon-under-the-picture fallback as `_avatar` (`BrandConnectState.profile_avatar_src`)."""
    return media_thumb(
        _AVATAR_BASE + BrandConnectState.profile_avatar_src,
        has=BrandConnectState.profile_avatar_src != "",
        size=size,
        round=True,
        icon="user",
        icon_size=icon_size,
        custom_attrs={"referrerpolicy": "no-referrer", "draggable": "false"},
    )


def _deck_face(item: rx.Var[dict[str, str]]) -> rx.Component:
    """The face of a deck card — shared by the live card and its flying ghost."""
    # Every text line is bounded by the card (bug 2026-10-05, "algunos textos se salen
    # de la card"): a long handle, Claude's reason or a bio made of one unbroken URL has
    # no space to wrap at, and a flex item's min-width is its content's width — so each
    # gets `max_width="100%"` + `overflow_wrap="anywhere"`, and the column `min_width="0"`.
    return card(
        rx.vstack(
            _avatar(item, "4.5rem", 26),
            mono(
                item["handle"],
                size="3",
                max_width="100%",
                overflow_wrap="anywhere",
                text_align="center",
            ),
            rx.hstack(
                tag(item["network"]),
                _kind_flag(item),
                _signal_flags(item),
                rx.text(item["followers"], " seguidores", size="1", color=T.TEXT_MUTED),
                rx.cond(
                    item["likes"] != "",
                    rx.text("♥ ", item["likes"], size="1", color=T.TEXT_MUTED),
                ),
                spacing="2",
                align="center",
                wrap="wrap",
                justify="center",
                max_width="100%",
            ),
            _review_line(item, text_align="center"),
            # the bio in full, clamped to 3 lines on a phone (`assets/qualify.css`)
            _bio_block(item, text_align="center", class_name="q-deck-blurb"),
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
            min_width="0",
        ),
        padding=rx.breakpoints(initial="1rem 0.75rem", sm="1.5rem 1.25rem"),
        width="100%",
        min_width="0",
        overflow="hidden",
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
    ("referente", "Te inspira", "Te gustaría parecerte", "arrow-left", "left"),
    ("competencia", "Compite contigo", "Le vende a tu público", "arrow-right", "right"),
    ("detractor", "No va contigo", "No se parece a tu marca", "arrow-down", "down"),
)
#: The sort step is not a field list: its three panels reach the card's own edges
#: (§ request 2026-09-14, "que ocupen hasta los bordes"), so `brand_connect_index`
#: lifts the 34rem column cap and tightens the card's padding for this one step.
_SORT_COLUMN_MAX = "100%"
_SORT_CARD_PADDING = "1rem"
#: Resultados e insights (§ request 2026-10-05, the redesign): the whole screen takes this
#: width — header band, tabs and card grid alike — instead of a 34rem column.
_RESULTS_COLUMN_MAX = "62rem"


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
                    # an empty category that is still shown (the city, § 2026-10-05):
                    # why it is empty, and what to press
                    rx.vstack(
                        rx.icon("map-pin-off", size=22, color=T.TEXT_FAINT),
                        rx.text(
                            BrandConnectState.stage_note,
                            size="2",
                            color=T.TEXT_MUTED,
                            text_align="center",
                        ),
                        rx.cond(
                            BrandConnectState.is_last_stage,
                            rx.text(
                                "Pulsa Continuar para ver tus resultados.",
                                size="1",
                                color=T.TEXT_FAINT,
                            ),
                        ),
                        spacing="2",
                        align="center",
                    ),
                    # § request 2026-10-05: the last category done does not move on by
                    # itself — Continuar does (see `advance_stage_if_exhausted`)
                    rx.text(
                        rx.cond(
                            BrandConnectState.is_last_stage,
                            "Todas clasificadas. Pulsa Continuar para ver tus resultados.",
                            "Todas clasificadas.",
                        ),
                        size="2",
                        color=T.TEXT_MUTED,
                        text_align="center",
                    ),
                ),
            ),
        ),
    )
    zones = {spec[-1]: _deck_zone(*spec) for spec in _DECK_ZONES}
    return _step_body(
        _script_on_mount(_DECK_DRAG_JS),
        rx.cond(
            BrandConnectState.discovery_error != "",
            callout(BrandConnectState.discovery_error, "error"),
        ),
        # § request 2026-09-30: the empty categories are skipped on their own; when
        # every one came back empty there is no deck to deal, and the step says so.
        rx.cond(
            BrandConnectState.nothing_to_sort,
            callout(
                "No hay nada para clasificar: la búsqueda no encontró cuentas en ninguna "
                "categoría. Puedes añadir alguna a mano abajo o continuar.",
                "warn",
            ),
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
        _stage_discarded(),
        _manual_section(),
        icon="layout-grid",
        grow=True,
    )


def _discarded_row(item: rx.Var[dict[str, str]]) -> rx.Component:
    return rx.hstack(
        mono(item["handle"], size="1"),
        tag(item["network"]),
        rx.text(item["reason"], size="1", color=T.TEXT_MUTED),
        spacing="2",
        align="center",
        wrap="wrap",
    )


def _stage_discarded() -> rx.Component:
    """What the AI review dropped from this category, folded: the operator can check
    a drop, and add the account by hand if the review was wrong."""
    return rx.cond(
        BrandConnectState.stage_discarded.length() > 0,
        rx.el.details(
            rx.el.summary(
                rx.hstack(
                    rx.icon("sparkles", size=14, color=T.TEXT_FAINT),
                    rx.text(BrandConnectState.stage_discarded_label, size="1", color=T.TEXT_MUTED),
                    spacing="1",
                    align="center",
                    display="inline-flex",
                ),
                cursor="pointer",
            ),
            rx.vstack(
                rx.foreach(BrandConnectState.stage_discarded, _discarded_row),
                spacing="1",
                padding_top="0.5rem",
                width="100%",
            ),
            width="100%",
        ),
    )


def _manual_chip(item: rx.Var[dict[str, str]]) -> rx.Component:
    bucket_title = rx.match(
        item["bucket"],
        *((key, title) for key, title, _, _ in BUCKETS),
        "",
    )
    return removable_pill(
        rx.fragment(item["handle"], " · ", bucket_title),
        BrandConnectState.remove_manual(item["key"]),
        leading=rx.cond(item["fits"] == "no", rx.icon("triangle-alert", size=12)),
        remove_label="Quitar esta cuenta",
    )


def _manual_form() -> rx.Component:
    return rx.form(
        rx.vstack(
            rx.hstack(
                rx.box(
                    _select_field(
                        "Red",
                        BrandConnectState.manual_network,
                        BrandConnectState.set_manual_network,
                        MANUAL_NETWORK_OPTIONS,
                        "Red",
                    ),
                    flex="1 1 8rem",
                ),
                rx.box(
                    _select_field(
                        "Lo agregas como",
                        BrandConnectState.manual_bucket,
                        BrandConnectState.set_manual_bucket,
                        tuple((key, title) for key, title, _, _ in BUCKETS),
                        "Te inspira",
                    ),
                    flex="1 1 8rem",
                ),
                spacing="2",
                width="100%",
                wrap="wrap",
            ),
            rx.input(
                value=BrandConnectState.manual_input,
                on_change=BrandConnectState.set_manual_input,
                placeholder=BrandConnectState.manual_placeholder,
                width="100%",
                size="2",
                radius=_CONTROL_RADIUS,
            ),
            rx.text_area(
                value=BrandConnectState.manual_note,
                on_change=BrandConnectState.set_manual_note,
                placeholder=(
                    "Ej.: Cafetería del mismo barrio con el mismo menú; es competencia directa."
                ),
                width="100%",
                rows="2",
                radius=_CONTROL_RADIUS,
            ),
            rx.cond(
                BrandConnectState.manual_error != "",
                rx.text(BrandConnectState.manual_error, size="1", color=T.tone_color("error", 11)),
            ),
            rx.hstack(
                rx.button(
                    "Cancelar",
                    type="button",
                    variant="ghost",
                    size="2",
                    radius=_CONTROL_RADIUS,
                    on_click=BrandConnectState.toggle_manual,
                ),
                rx.button(
                    rx.cond(
                        BrandConnectState.adding_manual,
                        loading_spinner("sm"),
                        rx.icon("user-plus", size=T.ICON_SM),
                    ),
                    rx.cond(BrandConnectState.adding_manual, "Revisando…", "Agregar"),
                    type="submit",
                    variant="soft",
                    size="2",
                    radius=_CONTROL_RADIUS,
                    disabled=BrandConnectState.adding_manual,
                ),
                spacing="2",
                justify="end",
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
        on_submit=BrandConnectState.add_manual_account,
        width="100%",
    )


def _manual_section(*, with_chips: bool = True) -> rx.Component:
    """Agregar a mano (§ request 2026-09-25): an account the search cannot find —
    little activity, few followers, or not on TikTok / Instagram at all — added by
    handle, link or plain name, then reviewed by Claude like the search's. The Brand Kit
    editor passes `with_chips=False` (§ request 2026-10-05): its added accounts show —
    and are taken out with their ✕ — in the ranking right above, not as pills here."""
    chips = rx.cond(
        BrandConnectState.manual_accounts.length() > 0,
        rx.flex(
            rx.foreach(BrandConnectState.manual_accounts, _manual_chip),
            wrap="wrap",
            gap="2",
            width="100%",
        ),
    )
    return rx.vstack(
        # the outcome of an add is a toast (`add_manual_account`), not a callout here
        *([chips] if with_chips else []),
        rx.cond(
            BrandConnectState.manual_open,
            card(_manual_form(), padding="1rem", width="100%"),
            rx.button(
                rx.icon("user-plus", size=T.ICON_SM),
                "¿Falta alguien? Agrégalo a mano",
                variant="soft",
                color_scheme="gray",
                size="2",
                radius=_CONTROL_RADIUS,
                on_click=BrandConnectState.toggle_manual,
            ),
        ),
        spacing="2",
        width="100%",
        align_items="center",
    )


def _connect_window() -> rx.Component:
    """One renderer per `CONNECT_STEPS` index, all by name. Which of them a session
    actually reaches is `BrandConnectState._is_skipped`'s call — every step still
    needs a renderer for the sessions where it is shown. The kit-setup steps reuse the
    manual flow's renderers, so the shared half of the two paths is literally the
    same code."""
    return rx.fragment(_progress_trigger(BrandConnectState), _connect_steps())


def _connect_steps() -> rx.Component:
    return rx.match(
        BrandConnectState.step,
        (_ACCOUNT_STEP, _connect_step_account()),
        (_PROFILE_STEP, _connect_step_profile()),
        (_ACCOUNT_KIND_STEP, _connect_step_account_kind()),
        (_RUBRO_STEP, _connect_step_rubro()),
        (_IDENTITY_STEP, _step_identity()),
        (_LOGO_QUESTION_STEP, _connect_step_has_logo()),
        (_LOGO_UPLOAD_STEP, _step_logo(BrandConnectState.next_step)),
        (_TYPOGRAPHY_STEP, _step_typography()),
        (_PALETTE_STEP, _step_palette()),
        (_CONNECT_CONFIRM_STEP, _step_confirm()),
        (_SORT_STEP, _connect_step_sort()),
        (CONNECT_LAST, _connect_step_insights()),
        _connect_step_account(),
    )


def _connect_heading_for(index: int) -> rx.Var[str]:
    return rx.match(
        BrandConnectState.step,
        *((position, text[index]) for position, text in enumerate(CONNECT_STEPS)),
        CONNECT_STEPS[0][index],
    )


def _connect_loading() -> rx.Component:
    # the profile plus up to five pages of posts: several reads, so a longer creep
    return _loading_view(
        "Leyendo tu perfil",
        "Tomamos de ahí tu logo, tus colores y a qué te dedicas. Tarda unos segundos.",
        creep_seconds=20,
    )


def _referentes_loading() -> rx.Component:
    """The loading screen in front of Referente, competencia o detractor while the
    search is still running (`BrandConnectState.waiting_for_referentes`) — no deck
    and no Atrás/Continuar under it, so the step cannot be skipped half-loaded. Lists
    the three categories with a check for each one already found, so a long wait
    visibly moves. It clears on its own when the last category lands."""
    # § 2026-10-01: the same progress screen as the voice analysis and the hashtags,
    # its bar moving one category at a time
    return progress_panel(
        "Buscando negocios parecidos al tuyo",
        "En cuanto termine podrás clasificarlos. Puede tardar unos minutos.",
        value=BrandConnectState.discovery_percent,
        steps=BrandConnectState.discovery_progress,
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
        # Any one version of the logo, or any added element, will do (§ request 2026-09-29).
        (BrandWizardState.logo_versions.length() > 0)
        | (BrandWizardState.brand_extras.length() > 0),
        BrandWizardState.logo_brief_1 != "",
    )


def _connect_can_continue() -> rx.Var[bool]:
    """Whether the CURRENT step's requirement is satisfied (§ request 2026-09-09) —
    gates `_connect_controls`'s forward button (Continuar) so a choice step
    can't be skipped unanswered and a required-input step can't be skipped empty.

    Every step not named below has nothing to require and always returns True:
    Esto es lo que vemos (read-only recap), Tipografía (optional), ¿Todo correcto?
    (its examples and rules are optional) and Resultados e insights (its own
    `_finish_button`, not this gate, on step CONNECT_LAST). Shared steps (identidad,
    logo, paleta) read the SAME `BrandWizardState`/`CreativeState` fields the manual
    flow's own `_manual_can_continue` checks — the two functions stay side by side
    with it so a future reorder of either STEPS tuple is easy to keep in sync. Tu rubro
    y ubicación needs a rubro always, and país + ciudad unless the account is a creator
    (`rubro_complete`)."""
    return rx.cond(
        _connect_busy(),
        False,  # nothing moves while the hashtags are being created or the brief read
        _connect_requirement(),
    )


def _connect_busy() -> rx.Var[bool]:
    return BrandConnectState.suggesting_hashtags | brand_documents.BrandDocumentState.brief_busy


def _connect_requirement() -> rx.Var[bool]:
    return rx.match(
        BrandConnectState.step,
        (_ACCOUNT_KIND_STEP, BrandConnectState.account_kind != ""),
        (_RUBRO_STEP, BrandConnectState.rubro_complete),
        (_LOGO_QUESTION_STEP, BrandWizardState.has_logo != ""),
        (_LOGO_UPLOAD_STEP, _logo_step_complete()),
        (_IDENTITY_STEP, _identity_complete()),
        (_PALETTE_STEP, CreativeState.kit_palette != ""),
        True,
    )


def _connect_controls() -> rx.Component:
    """The connect flow's foot in the step frame (PASOS-4). «Atrás» walks back over
    exactly the steps «Siguiente» walks over (`_is_skipped`) and is never on step 1.
    Tu cuenta has no primary: its network buttons read the profile (§ 2026-10-05). The
    sort step's primary starts the metric count-up (`advance_to_insights`), the last
    one is the finish (`_finish_button`'s label). Every forward button is gated by
    `_connect_can_continue`. «Cancelar» (Esto es lo que vemos) moved into that step's
    body as «No es mi cuenta» (`_not_my_account`): the foot's left slot is «Atrás»,
    which keeps what was read."""
    common: dict[str, Any] = {
        "step": BrandConnectState.step_n,
        "on_back": BrandConnectState.prev_step,
        "on_later": BrandConnectState.save_for_later,
    }
    return rx.cond(
        BrandConnectState.step == _ACCOUNT_STEP,
        step_foot(None, on_primary=None, **common),
        step_foot(
            rx.cond(BrandConnectState.is_last, _finish_label(), NEXT_LABEL),
            on_primary=BrandConnectState.primary,
            primary_disabled=~_connect_can_continue(),
            primary_loading=BrandConnectState.is_last & CreativeState.kit_saving,
            **common,
        ),
    )


def _not_my_account() -> rx.Component:
    """Esto es lo que vemos: «No es mi cuenta» drops what was read and starts again
    (`BrandConnectState.restart`, what «Cancelar» did there)."""
    return rx.button(
        rx.icon("rotate-ccw", size=T.ICON_SM),
        "No es mi cuenta",
        type="button",
        variant="soft",
        color_scheme="gray",
        size="3",
        radius=_CONTROL_RADIUS,
        width="100%",
        min_height="44px",
        on_click=BrandConnectState.restart,
        disabled=_connect_busy(),
    )


def _connect_column() -> rx.Var[str]:
    # The deck (three panels around a card) needs more room than a field list, and so
    # does Resultados with its lateral ranking; every other step keeps the 34rem.
    return rx.cond(
        BrandConnectState.step == _SORT_STEP,
        _SORT_COLUMN_MAX,
        rx.cond(
            BrandConnectState.step == CONNECT_LAST,
            _RESULTS_COLUMN_MAX,
            _step_column_width(
                BrandConnectState.step == _LOGO_UPLOAD_STEP,
                BrandConnectState.step == _CONNECT_CONFIRM_STEP,
                on_typography=BrandConnectState.step == _TYPOGRAPHY_STEP,
            ),
        ),
    )


def brand_connect_index() -> rx.Component:
    """The connect flow in the step frame (PASOS-4, m-24852243; §4.5): the head's «‹
    Inicio» on every step and «Paso N de M» over the steps this owner walks (H5); the
    foot fixed. Three waits keep their progress panels in the body, with the head (and
    its way out) still there and no foot, so no step is skipped half-loaded: the kit
    loading, the profile read (`analyzing`) and the search for referentes in front of
    the sort step (`waiting_for_referentes`)."""
    waiting = (
        CreativeState.kit_loading
        | ~BrandConnectState.steps_ready
        | BrandConnectState.analyzing
        | BrandConnectState.waiting_for_referentes
    )
    return _wizard_shell(
        _or_ready_frame(
            step_frame(
                _kit_notices(),
                rx.cond(
                    CreativeState.kit_loading | ~BrandConnectState.steps_ready,
                    _frame_loading(_loading_view("Cargando tu marca")),
                    rx.cond(
                        BrandConnectState.analyzing,
                        _frame_loading(_connect_loading()),
                        rx.cond(
                            BrandConnectState.waiting_for_referentes,
                            _frame_loading(_referentes_loading()),
                            rx.fragment(
                                rx.cond(
                                    BrandConnectState.steps_ready,
                                    step_sync(
                                        BrandConnectState.step_n, BrandConnectState.direction
                                    ),
                                ),
                                _frame_step(
                                    rx.fragment(
                                        _connect_window(),
                                        rx.cond(
                                            BrandConnectState.step == _PROFILE_STEP,
                                            _not_my_account(),
                                        ),
                                    ),
                                    subtitle=_connect_heading_for(1),
                                    column=_connect_column(),
                                    first_step=BrandConnectState.step == _ACCOUNT_STEP,
                                    padding=rx.cond(
                                        BrandConnectState.step == _SORT_STEP,
                                        _SORT_CARD_PADDING,
                                        "1.75rem",
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                head=step_head(
                    rx.cond(
                        CreativeState.kit_loading | ~BrandConnectState.steps_ready,
                        "Tu marca",
                        _connect_heading_for(0),
                    ),
                    step=BrandConnectState.step_n,
                    total=BrandConnectState.step_m,
                    back_label=exit_label(),
                    on_exit=BrandConnectState.leave,
                ),
                foot=rx.cond(waiting, rx.fragment(), _connect_controls()),
                step=BrandConnectState.step_n,
                direction=BrandConnectState.direction,
                on_pop=BrandConnectState.pop_step,
                on_leave=BrandConnectState.leave_frame,
            )
        )
    )
