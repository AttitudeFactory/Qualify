"""Layout primitives: the app shell every business page is built from.

    app_shell(
        page_header("Leads", "Personas captadas por tu funnel"),
        page_body(...),
    )

The shell is built as **islands floating on the app ground** (design decision C,
docs/design-system.md §4 and §10.7): the sidebar is a stack of surfaces separated by
air, the page is another, and the ground shows between them. Grouping is done by the
gap, not by a rule.

Four guarantees a screen gets for free, so no page re-implements them:

* the sidebar — business on top, zones in the middle, sales metrics and Salir at the
  bottom — with the active item derived from the route;
* zen mode: one class on the nav root collapses every island to a 72 px rail, with the
  labels revealed by mask and the width springing (``assets/qualify.css``);
* the page panel, its gutter (``tokens.PAGE_X``) and its entrance;
* the header row with page actions and the colour-mode toggle in a fixed position.
"""

from __future__ import annotations

from collections.abc import Sequence

import reflex as rx
from qualify_api.auth import SIGNUP_ROUTE

from ..auth_state import AuthState
from . import tokens as T
from .state import NavState

LANDING_URL = "https://qualify.la"

# An item is (label, lucide icon, route, enabled). Enabled items navigate; disabled ones
# show a "pronto" badge. The active item is derived from the current route, never
# hardcoded.
Item = tuple[str, str, str, bool]

# Not a Lucide name: the app's own composed icon (`mention_icon`), resolved by `nav_icon`.
MENTION_ICON = "qualify-mention"

# Order follows the operator's flow, and the two tinted zones are the product's own two
# axes (docs/index.md): what the market says, and what the business says. Connections is
# the base of both, so it sits above them, untinted. The "Negocio" foot block is sales
# measurement — deliberately outside the colour zones.
NAV_BASE: list[Item] = [
    ("Conexiones", "link", "/connections", True),
    # WA-12: the WhatsApp module (own number: connection, profile, QR, chats, menu).
    ("WhatsApp", "message-circle", "/whatsapp", True),
]

NAV_ZONES: list[tuple[str, str, list[Item]]] = [
    (
        "listen",
        "Escuchas",
        [
            ("Menciones", MENTION_ICON, "/", True),
            # m-24789644 (B1): formerly «Contenido»; the route stays `/inbox`.
            ("Interacciones", "film", "/inbox", True),
            # QUA-226: the private inbox of the connected accounts. Founder's placement
            # (2026-10-16): inside Escuchas, after Interacciones, before Creadores.
            ("Conversaciones", "messages-square", "/conversations", True),
            ("Creadores", "users", "#", False),
            ("Señales", "bell", "#", False),
        ],
    ),
    (
        "publish",
        "Publicas",
        [
            # No "Marca" inside a session (§ request 2026-10-02): the Brand Kit is made
            # before the login and edited from Negocio → Brand Kit. The guest rail
            # keeps "Marca" as the entry to make it.
            ("Crear pieza", "wand-sparkles", "/create", True),
            ("Piezas", "layout-list", "/drafts", True),
            ("Planificador", "calendar-days", "/planner", True),
            # QUA-113: Stories is a flow inside Publicar, not an entry of its own.
            ("Publicar", "upload", "/publish", True),
        ],
    ),
]

NAV_LOOSE: list[Item] = [("Leads", "user-plus", "/leads", True)]

NAV_BUSINESS: list[Item] = [
    ("Clarity", "activity", "/clarity", True),
    ("Brand Kit", "swatch-book", "/brand/kit", True),
    # The product catalog (plan-mvp-plantillas-remotion.md §2.1 #1): the real photos
    # the templates compose. Next to the Brand Kit — both are what the brand IS.
    ("Catálogo", "package", "/catalog", True),
    # The account itself (2026-10-06): who is in, and changing the password.
    ("Configuración", "settings", "/settings", True),
]

# Flat view of the whole menu, in visual order. Kept because it is the cheapest thing to
# assert against in a test and the shape older code imported.
NAV_ITEMS: list[Item] = [
    *NAV_BASE,
    *[item for _zone, _label, items in NAV_ZONES for item in items],
    *NAV_LOOSE,
    *NAV_BUSINESS,
]

# `⌘ .` / `Ctrl .` toggles zen. Registered once per document: the sidebar mounts on every
# page, so the guard is what keeps it from stacking listeners.
_ZEN_SHORTCUT = """
if (!window.__qZenKey) {
  window.__qZenKey = true;
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === '.') {
      e.preventDefault();
      var b = document.getElementById('q-zen-toggle');
      if (b) b.click();
    }
  });
}
"""


# The Lucide `radar` icon (ISC), rotated 90° so its needle is the tail of a Q, and split
# in two layers: the Q (inner ring, centre dot, needle) and the waves (outer ring, the
# stray dot). Same 24-unit paths as the icon — nothing redrawn.
_MARK_Q: tuple[str, ...] = (
    "M16.24 7.76A6 6 0 1 0 8.23 16.67",
    "M17.99 11.66A6 6 0 0 1 15.77 16.67",
    "M12 18h.01",
    "m13.41 10.59 5.66-5.66",
)
_MARK_WAVES: tuple[str, ...] = (
    "M19.07 4.93A10 10 0 0 0 6.99 3.34",
    "M2.29 9.62A10 10 0 1 0 21.31 8.35",
    "M4 6h.01",
)


def qualify_mark(size: int = 22) -> rx.Component:
    """The isotype (decided 2026-10-12): a Q that is also a radar. One hue, two
    luminosities — the Q in accent 11, the waves in accent 9 at 45 % — so the near
    signal stands out over the far ones. Radix variables, so it follows light/dark on
    its own. Static copies for outside the app: ``assets/qualify-mark*.svg``."""
    svg = rx.el.svg
    return svg(
        svg.g(
            svg.g(
                *(svg.path(d=d) for d in _MARK_WAVES),
                stroke="var(--accent-9)",
                stroke_opacity="0.45",
            ),
            svg.g(*(svg.path(d=d) for d in _MARK_Q), stroke="var(--accent-11)"),
            svg.circle(cx=12, cy=12, r=2, fill="var(--accent-11)", stroke="var(--accent-11)"),
            fill="none",
            stroke_width="2",
            stroke_linecap="round",
            stroke_linejoin="round",
            transform="rotate(90 12 12)",
        ),
        view_box="0 0 24 24",
        width=f"{size}px",
        height=f"{size}px",
        flex_shrink="0",
        aria_hidden="true",
    )


# "Menciones": an @ that speaks (founder request 2026-10-14 — the plain bubble read as a
# conversation, and WhatsApp uses it). Lucide has no such glyph; it is built from two
# Lucide (ISC) icons that share the same r=10 ring around (12, 12): `at-sign`'s outer arc
# IS `message-circle`'s bubble. The @ keeps its opening bottom-right, the bubble keeps its
# tail bottom-left (verbatim from `message-circle`), and the hook of the @ runs into the
# ring as in `at-sign`. Inner circle 3.5 (not 4) for air at 18 px. Same 24-unit grid,
# 2-unit stroke and round caps as every other menu icon — nothing scaled.
_MENTION_INNER_RADIUS = "3.5"
_MENTION_RING = (
    "M15.5 8.5v4.5a3.25 3.25 0 0 0 6.5 0v-1"  # the @'s hook, into the ring at (22, 12)
    "A10 10 0 1 0 2.992 16.342"  # the ring, up and around, to the tail
    "a2 2 0 0 1 .094 1.167l-1.065 3.29a1 1 0 0 0 1.236 1.168l3.413-.998a2 2 0 0 1 1.099.092"
    "A10 10 0 0 0 18 20"  # on along the bottom, stopping at the @'s opening
)


def mention_icon(size: int) -> rx.Component:
    """The Menciones icon, drawn like `rx.icon` (currentColor, 2-unit stroke)."""
    svg = rx.el.svg
    return svg(
        svg.circle(cx=12, cy=12, r=_MENTION_INNER_RADIUS),
        svg.path(d=_MENTION_RING),
        view_box="0 0 24 24",
        width=f"{size}px",
        height=f"{size}px",
        fill="none",
        stroke="currentColor",
        stroke_width="2",
        stroke_linecap="round",
        stroke_linejoin="round",
        flex_shrink="0",
        aria_hidden="true",
    )


def nav_icon(icon: str, size: int) -> rx.Component:
    """A menu item's icon: a Lucide name, or one of the app's own composed icons."""
    if icon == MENTION_ICON:
        return mention_icon(size)
    return rx.icon(icon, size=size)


def brand_mark(size: int = 22, heading_size: str = "5") -> rx.Component:
    """The wordmark: the Q-radar mark + "Qualify". Same everywhere it appears."""
    return rx.hstack(
        qualify_mark(size),
        # A text, not a heading: the wordmark must not enter the page outline as an h1.
        rx.text("Qualify", size=heading_size, weight="bold", letter_spacing="-0.02em"),
        align="center",
        spacing="2",
    )


def _nav_row(
    icon: str,
    label: str,
    *,
    active: rx.Var | bool = False,
    disabled: bool = False,
    trailing: rx.Component | None = None,
    tooltip: str | None = None,
) -> rx.Component:
    """The geometry of every sidebar row, whatever wraps it.

    Kept in one place because zen centres the icon by collapsing the label to zero
    width: if a link row and a button row had different padding, their icons would land
    in different columns the moment the rail collapses. The wrapper (``rx.link`` or
    ``rx.el.button``) carries no padding of its own.
    """
    return rx.hstack(
        nav_icon(icon, T.ICON_MD),
        rx.el.span(
            label,
            class_name="q-label",
            style={"whiteSpace": "nowrap", "fontSize": "var(--font-size-3)"},
        ),
        *([trailing] if trailing is not None else []),
        # Centred on the label's line box: Reflex's hstack defaults to `start`, which
        # pinned the 18 px icon to the top of the 24 px text line.
        align="center",
        width="100%",
        gap="0.6rem",
        padding="0.5rem 0.6rem",
        border_radius=T.RADIUS_CONTROL,
        # No fill of its own: the active/hover surface is the glass capsule that
        # `assets/glass-nav.js` moves between rows (one per island). The flat fallback
        # for a document without the script lives in `assets/qualify.css`, keyed on the
        # wrapper's `aria-current="page"`.
        color=rx.cond(active, rx.color("accent", 11), rx.color("gray", 11)),
        font_weight=rx.cond(active, "600", "400"),
        opacity="0.55" if disabled else "1",
        class_name="q-nav-item",
        custom_attrs={"data-label": tooltip or label},
        **({"aria_disabled": "true"} if disabled else {}),
    )


def _nav_item(label: str, icon: str, route: str, enabled: bool) -> rx.Component:
    """One menu entry. Disabled entries render the row without a link, so they cannot be
    tabbed to or followed."""
    if not enabled:
        return _nav_row(
            icon,
            label,
            disabled=True,
            tooltip=f"{label} · pronto",
            trailing=rx.badge(
                "pronto",
                variant="soft",
                color_scheme="gray",
                size="1",
                class_name="q-soon",
                margin_left="auto",
            ),
        )

    active = NavState.router.page.path == route
    return rx.link(
        _nav_row(icon, label, active=active),
        href=route,
        width="100%",
        underline="none",
        aria_current=rx.cond(active, "page", ""),
        # No-op on desktop (the drawer is never open there); on a phone viewport
        # this is what makes picking a page also close the overlay instead of
        # leaving it covering the page that just loaded underneath it.
        on_click=NavState.close_mobile_nav,
    )


def _island(*children: rx.Component, tint: str | None = None, **props) -> rx.Component:
    """A floating block of the sidebar. `tint` names a zone; without one it is neutral.

    The material (translucent fill, backdrop blur, inset highlight, hairline) is CSS —
    `.q-island` in `assets/qualify.css`, "Liquid glass menu" — so light and dark are
    two sets of variables rather than two trees. A zone only hands the stylesheet its
    wash and its line colour through custom properties; the glass sits on top of them.
    """
    style: dict = {
        "padding": "0.4rem 0.35rem 0.5rem",
        "width": "100%",
        "class_name": "q-island",
    }
    if tint:
        style["style"] = {"--q-zone-tint": T.zone_tint(tint), "--q-zone-line": T.zone_line(tint)}
    style.update(props)
    return rx.vstack(*children, spacing="1", align_items="stretch", **style)


def _zone_head(label: str, zone: str) -> rx.Component:
    return rx.hstack(
        rx.text(
            label,
            size="1",
            weight="medium",
            color=T.zone_ink(zone),
            class_name="q-label q-mono",
            style={"letterSpacing": "0.09em", "textTransform": "uppercase"},
            white_space="nowrap",
        ),
        width="100%",
        padding="0.15rem 0.6rem 0.1rem",
        class_name="q-zone-head",
        height="1.35rem",
        align="center",
    )


def tenant_block() -> rx.Component:
    """Top island: the business owns the screen. Its name first, then "Supported by
    Qualify" linking to the landing, and the control that collapses the rail. Without a
    session (e.g. `/design`) the name falls back to "Qualify" so it never reads empty."""
    name = rx.cond(AuthState.business_name != "", AuthState.business_name, "Qualify")
    return _island(
        rx.hstack(
            rx.icon("store", size=T.ICON_MD, color=rx.color("accent", 9)),
            rx.text(
                name,
                size="4",
                weight="bold",
                letter_spacing="-0.02em",
                class_name="q-label",
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
            ),
            rx.spacer(),
            _zen_toggle(),
            align="center",
            spacing="2",
            width="100%",
            min_width="0",
            class_name="q-biz-row",
        ),
        rx.link(
            rx.hstack(
                rx.text("Supported by", size="1", color=T.TEXT_MUTED),
                qualify_mark(T.ICON_SM),
                rx.text("Qualify", size="1", weight="medium", color=rx.color("accent", 11)),
                align="center",
                spacing="1",
                white_space="nowrap",
            ),
            href=LANDING_URL,
            is_external=True,
            underline="none",
            class_name="q-label",
            aria_label="Qualify — ir al sitio",
        ),
        padding="0.7rem 0.75rem",
    )


def _zen_toggle() -> rx.Component:
    return rx.button(
        rx.icon(rx.cond(NavState.zen, "panel-left-open", "panel-left-close"), size=T.ICON_SM),
        id="q-zen-toggle",
        variant="ghost",
        color_scheme="gray",
        size="1",
        on_click=NavState.toggle_zen,
        aria_label=rx.cond(NavState.zen, "Expandir el menú", "Contraer el menú"),
        title="⌘ .",
    )


def logout_action() -> rx.Component:
    """Bottom of the sidebar. There is no tenant switch (`1 login = 1 tenant`): changing
    business = logout + login, so this is the only session control in the app."""
    return rx.el.button(
        _nav_row("log-out", "Salir"),
        on_click=AuthState.logout,
        width="100%",
        padding="0",
        border="none",
        background="transparent",
        cursor="pointer",
        text_align="left",
        font="inherit",
    )


def _guest_islands() -> rx.Component:
    """The rail of a pre-login Brand Kit (§ request 2026-10-02): no sections — every
    other page needs a login — only where the kit is being saved and the way into an
    account (the signup with that email adopts it)."""
    # Same labels and routes as the logged-in rail's own entries ("Marca", and "Brand
    # Kit" under "Negocio"), so the Brand Kit's own copy ("ve a Negocio → Brand Kit")
    # holds for a guest too.
    return rx.fragment(
        _island(
            _nav_item("Marca", "palette", "/brand", True),
            rx.text(
                "Guardando en ",
                rx.text.strong(AuthState.guest_email),
                size="1",
                color=T.TEXT_MUTED,
                class_name="q-label",
                padding="0.25rem 0.5rem",
                overflow_wrap="anywhere",
            ),
        ),
        rx.spacer(),
        _island(
            _zone_head("Negocio", "business"),
            _nav_item("Brand Kit", "swatch-book", "/brand/kit", True),
            rx.divider(margin="0.15rem 0"),
            _nav_item("Crear cuenta", "user-plus", SIGNUP_ROUTE, True),
            _nav_item("Iniciar sesión", "log-in", "/login", True),
            rx.divider(margin="0.15rem 0"),
            rx.el.button(
                _nav_row("mail", "Usar otro correo"),
                on_click=AuthState.leave_brand_draft,
                width="100%",
                padding="0",
                border="none",
                background="transparent",
                cursor="pointer",
                text_align="left",
                font="inherit",
            ),
        ),
    )


def sidebar() -> rx.Component:
    return rx.el.nav(
        rx.script(_ZEN_SHORTCUT),
        # The liquid glass capsule and zen label (assets/qualify.css, "Liquid glass
        # menu"). A plain `<script async src>` rendered here rather than an
        # `rx.App(head_components=…)` entry: React 19 hoists an async script to the
        # head and loads it once per document whatever page mounts the rail, and it
        # does not depend on react-helmet (which `head_components` use, and which only
        # injects on Reflex >= 0.9.9 — the shared venv was at 0.9.7 on 2026-10-08).
        # The file guards its own double-run.
        rx.el.script(src="/glass-nav.js", async_=True),
        tenant_block(),
        rx.cond(
            AuthState.is_guest,
            _guest_islands(),
            rx.fragment(
                _island(*[_nav_item(*item) for item in NAV_BASE]),
                *[
                    _island(_zone_head(label, zone), *[_nav_item(*i) for i in items], tint=zone)
                    for zone, label, items in NAV_ZONES
                ],
                _island(*[_nav_item(*item) for item in NAV_LOOSE]),
                rx.spacer(),
                _island(
                    _zone_head("Negocio", "business"),
                    *[_nav_item(*item) for item in NAV_BUSINESS],
                    rx.divider(margin="0.15rem 0"),
                    logout_action(),
                ),
            ),
        ),
        aria_label="Secciones",
        class_name=rx.cond(
            NavState.zen,
            rx.cond(NavState.mobile_open, "q-sidebar q-zen q-mobile-open", "q-sidebar q-zen"),
            rx.cond(NavState.mobile_open, "q-sidebar q-mobile-open", "q-sidebar"),
        ),
        display="flex",
        flex_direction="column",
        gap=T.GAP,
        padding=T.GAP,
        height="100vh",
        position="sticky",
        top="0",
        flex_shrink="0",
        overflow="hidden auto",
    )


def session_badge() -> rx.Component:
    """Kept for import compatibility; the session now lives in the sidebar
    (`tenant_block` on top, `logout_action` at the bottom). Renders nothing."""
    return rx.fragment()


def page_header(
    title: str | rx.Var,
    subtitle: str | rx.Var | None = None,
    *actions: rx.Component,
    badge: rx.Component | None = None,
    kicker: rx.Component | None = None,
    title_size: str = "6",
    show_session: bool = False,
) -> rx.Component:
    """Title row of a business page.

    ``actions`` render right-aligned, in the order given, before the colour-mode toggle.
    ``badge`` sits next to the title — for a state that describes the whole page ("demo",
    a count), never for an action. ``show_session`` is accepted for compatibility and
    ignored: the session lives in the sidebar.

    ``kicker`` and ``title_size`` are additive — every existing call site is unaffected
    (both default to the plain page style). ``kicker`` is a whole component (same
    convention as ``badge``, not a raw string) that renders ABOVE the title — pass it
    already styled as the small-caps eyebrow treatment the sidebar's zone labels and
    `section` already use elsewhere (uppercase, letter-spaced, muted), for the one case
    a page needs a label above its title rather than beside it, e.g. a step counter.
    ``title_size`` lets a page ask for a bigger h1 than the app-wide 6 — the Brand Kit
    wizard's full-screen, one-decision-per-step flow wants the heavier title weight a
    macOS-Setup-Assistant-style flow uses. Still exactly one ``h1`` per page (`as_="h1"`
    unconditionally below), so §8's accessibility rule holds regardless of size.
    """
    title_row = rx.hstack(
        rx.heading(title, size=title_size, as_="h1"),
        *([badge] if badge is not None else []),
        align="center",
        spacing="2",
    )
    title_block = rx.vstack(
        *([kicker] if kicker is not None else []),
        title_row,
        *([rx.text(subtitle, size="2", color=T.TEXT_MUTED)] if subtitle is not None else []),
        spacing="1",
        align_items="start",
    )
    return rx.hstack(
        title_block,
        rx.spacer(),
        *actions,
        # Ghost: the toggle is a page control, never the page's one solid action (P3).
        rx.color_mode.button(variant="ghost", color_scheme="gray"),
        width="100%",
        padding=T.PAD_HEADER,
        align="center",
        spacing="3",
        wrap="wrap",
        # A sheet of glass pinned to the top of the panel (`.q-page-header`,
        # assets/qualify.css): the panel is the scroll container, so `sticky` works.
        class_name="q-page-header",
    )


def page_body(
    *children: rx.Component, spacing: str = "4", align_items: str = "start"
) -> rx.Component:
    """The gutter every block below the header shares. Children settle in on load,
    staggered by position — one orchestrated entrance per screen, never per component.

    ``align_items`` defaults to "start" — every existing page reads left-to-right.
    Pass "center" for a screen whose body is a single narrow column that should sit
    in the middle of the panel instead of hugging its left edge (e.g. the Brand Kit
    wizard steps). Centering is set here, on the flex container, rather than left to
    a child's own ``align_self`` — the two must agree for a narrower child to
    actually land in the middle instead of at the container's own start edge.
    """
    return rx.vstack(
        *children,
        width="100%",
        max_width=T.CONTENT_MAX,
        spacing=spacing,
        align_items=align_items,
        padding=T.PAD_BODY,
        # Grow into the panel's spare height, never shrink below the content's own.
        # This is what lets a page hand a child `flex="1"` and have it reach the panel's
        # bottom edge without doing any `100vh` arithmetic of its own (see `app_shell`).
        flex="1 0 auto",
        class_name="q-settle",
    )


def _mobile_nav_toggle() -> rx.Component:
    """Hamburger button that opens the sidebar as an overlay drawer on a phone
    viewport. Lives OUTSIDE the sidebar (unlike `_zen_toggle`) precisely because the
    drawer is closed by default there — a control to open it can't live inside the
    thing it opens. Hidden on wider viewports by `.q-mobile-nav-toggle` in
    `assets/qualify.css`; nothing renders it there, `display: none` just keeps it
    out of the layout and off the tab order isn't needed since it's unreachable
    visually, but staying simple: the CSS rule is the only gate."""
    return rx.el.button(
        rx.icon("menu", size=T.ICON_MD),
        id="q-mobile-nav-toggle",
        on_click=NavState.toggle_mobile_nav,
        class_name="q-mobile-nav-toggle",
        aria_label="Abrir el menú",
    )


def _mobile_nav_backdrop() -> rx.Component:
    """Dims the page behind the open drawer and closes it on tap-outside. Only
    mounted while the drawer is open, so it can never intercept a click on desktop
    or while the drawer is closed."""
    return rx.box(
        on_click=NavState.close_mobile_nav,
        class_name="q-nav-backdrop",
        aria_hidden="true",
    )


# The Glass Lab's two dials that CSS cannot hold: refraction (feDisplacementMap scale)
# and surface frequency (feTurbulence baseFrequency = dial / 1000). Mirrored as the
# `--q-lab-refraction` / `--q-lab-frequency` records in assets/qualify.css, which is
# where the other dials live — change both when the Lab changes.
LAB_REFRACTION = 21
LAB_FREQUENCY = 9

_REFRACTION_SVG = f"""<svg width="0" height="0" aria-hidden="true" focusable="false">
  <filter id="q-refraction" x="-40%" y="-40%" width="180%" height="180%">
    <feTurbulence type="fractalNoise" baseFrequency="{LAB_FREQUENCY / 1000:.3f}"
      numOctaves="2" seed="12" result="noise"/>
    <feDisplacementMap in="SourceGraphic" in2="noise" scale="{LAB_REFRACTION}"/>
  </filter>
</svg>"""


def _refraction_filter() -> rx.Component:
    """The SVG filter every glass surface's depth layer refracts through
    (`.q-island::before { filter: url(#q-refraction) }`). Rendered once per shell;
    sized to nothing and kept in the flow (a `display: none` SVG would not resolve
    as a filter target in every browser)."""
    return rx.html(
        _REFRACTION_SVG,
        position="absolute",
        width="0",
        height="0",
        overflow="hidden",
        aria_hidden="true",
    )


def app_shell(*children: rx.Component, spacing: str = "0", rail: bool = True) -> rx.Component:
    """Sidebar + page panel, floating on the app ground. Pass ``page_header`` first,
    then the body blocks. ``rail=False`` drops the sidebar (and its phone toggle): the
    panel alone, for a flow that is only its views — the Brand Kit wizard (§ request
    2026-10-02: "solo las views, más nada").

    **The panel is the scroll container, not the document.** The shell is exactly one
    viewport tall and clips; the panel is a fixed ``calc(100vh - 2 * gap)`` box that
    scrolls internally only when its own content is genuinely taller. This replaced a
    chain of `min-height` arithmetic (shell 100vh → panel 100vh - 2*gap → each page
    subtracting its own paddings) that had to cancel to the pixel and did not: measured
    in a browser 2026-09-03, the panel's own 1px top+bottom border was never subtracted
    anywhere, so every screen overflowed the document by exactly 2px and showed a
    scrollbar it never needed. Arithmetic that must be exact across four nested boxes
    breaks whenever any of them gains a border or a padding — a definite height plus
    ``overflow: auto`` cannot drift, and it matches what the sidebar has always done
    (`height: 100vh`, `overflow: hidden auto`).

    **A page must fill the panel with ``flex``/``height``, never with its own ``100vh``
    maths.** This is not a style preference: a page that keeps computing
    ``calc(100vh - …)`` inside this fixed-height panel is measuring the VIEWPORT while
    living in a box that is already smaller than it, so its content overshoots and the
    layout visibly breaks. That exact mismatch happened on 2026-09-03 when
    `creative_wizard_pages.py` was restored from another worktree while this file kept
    the new model — if you are reverting one of the two, revert both.
    """
    chrome = (
        [_mobile_nav_toggle(), rx.cond(NavState.mobile_open, _mobile_nav_backdrop()), sidebar()]
        if rail
        else []
    )
    return rx.hstack(
        _refraction_filter(),
        *chrome,
        rx.el.main(
            rx.vstack(
                *children,
                width="100%",
                # Fills the panel when the page is short (so a page can hand its own
                # children a real height to grow into) and grows past it when the page
                # is long (so the panel scrolls instead of clipping).
                min_height="100%",
                spacing=spacing,
                align_items="start",
                # Without the rail the panel spans the whole window while `page_body`
                # stops at CONTENT_MAX: cap the header+body column to that width and
                # centre it, so a wide screen does not leave the wizard hugging the left.
                **({} if rail else {"max_width": T.CONTENT_MAX, "margin_x": "auto"}),
            ),
            background=T.SURFACE_BG,
            border=T.BORDER,
            class_name="q-panel",
            flex="1",
            min_width="0",
            height=f"calc(100vh - 2 * {T.GAP})",
            margin=f"{T.GAP} {T.GAP} {T.GAP} 0" if rail else T.GAP,
            overflow="hidden auto",
        ),
        width="100%",
        spacing="0",
        align_items="start",
        # The ground is `T.GROUND` plus a soft mesh of the two zone colours (`.q-ground`,
        # assets/qualify.css): the glass islands need something behind them to refract.
        class_name="q-ground",
        height="100vh",
        overflow="hidden",
    )


def section(
    title: str | rx.Var,
    *children: rx.Component,
    description: str | rx.Var | None = None,
    actions: Sequence[rx.Component] = (),
    spacing: str = "3",
) -> rx.Component:
    """A titled block inside ``page_body``: h2 + optional description + actions on the
    right, then its content. Use it instead of ad-hoc ``rx.heading(size="4")`` rows."""
    return rx.vstack(
        rx.hstack(
            rx.vstack(
                rx.heading(title, size="4", as_="h2"),
                *(
                    [rx.text(description, size="2", color=T.TEXT_MUTED)]
                    if description is not None
                    else []
                ),
                spacing="1",
                align_items="start",
            ),
            rx.spacer(),
            *actions,
            width="100%",
            align="center",
            spacing="3",
        ),
        *children,
        width="100%",
        spacing=spacing,
        align_items="start",
    )
