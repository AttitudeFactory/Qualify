import logging

import reflex as rx

from .auth_pages import login_index, signup_index
from .auth_state import AuthState
from .avatar_proxy import avatar_api
from .clarity_page import clarity_index
from .clarity_state import ClarityState
from .components import filter_bar, mentions_body, stats_row, topbar
from .connections_page import connections_index
from .connections_state import ConnectionsState
from .creative_pages import (
    create_index,
    draft_detail_index,
    drafts_index,
)
from .creative_state import CreativeState
from .creative_wizard_pages import (
    BrandConnectState,
    BrandWizardState,
    brand_choice_index,
    brand_connect_index,
    brand_connect_setup_index,
    brand_manual_index,
)
from .inbox_page import inbox_index
from .inbox_state import InboxState
from .leads_page import leads_index
from .leads_state import LeadsState
from .publishing_page import publish_index
from .publishing_state import PublishState
from .signals_page import signals_index
from .state import DashboardState
from .stories_page import stories_index
from .stories_state import StoriesState
from .styleguide_page import styleguide_index
from .ui import app_shell, page_body
from .vitrina_page import vitrina_index

# QUA-99 latency follow-up: this app never configured Python's logging at all before
# now — `logging.getLogger(__name__).info(...)` calls anywhere in the codebase (e.g.
# `qualify_api.publishing.service`'s per-stage timing) were silently dropped, because
# the root logger's default level is WARNING and nothing had ever attached a handler.
# Verified 2026-09-10: a real, settled carousel publish left zero trace in the log
# despite the instrumentation already being in the code. `basicConfig` here is what
# turns that instrumentation into something actually visible in `reflex_*.log`/stdout.
# Third-party libraries this app depends on are explicitly quieted back down — without
# this, INFO-level app visibility comes with httpx logging every Meta request line and
# botocore/sqlalchemy adding their own noise, drowning out the one thing this exists to
# surface.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for _noisy_logger in ("httpx", "httpcore", "botocore", "boto3", "urllib3", "sqlalchemy.engine"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

# QUA-49: the Dashboard de Menciones no longer depends on the local SQLite mock
# (`db.py`/`models.py`/`seed_data.py`) — its data comes from the real `mentions` backend
# via `state.py`/`mentions_provider.py`. Those files stay on disk (still useful for a
# quick manual demo or a future fixture), just no longer wired into the app's boot path.


def index() -> rx.Component:
    return app_shell(
        topbar(),
        page_body(stats_row(), filter_bar(), mentions_body()),
    )


# Type faces + the `--q-*` tokens (assets/qualify.css) layer on top of the Radix theme
# configured in rxconfig.py. See docs/design-system.md.
_FONTS = (
    "https://fonts.googleapis.com/css2"
    "?family=IBM+Plex+Mono:wght@400;500"
    "&family=IBM+Plex+Sans:wght@400;500;600;700"
    "&display=swap"
)
app = rx.App(
    stylesheets=[_FONTS, "/qualify.css"],
    html_lang="es",
    # Bug reported 2026-08-25, revised same day: bottom-right (Sonner's own default)
    # is the preferred position after all — the actual complaint was that it was easy
    # to miss there, not that the corner itself was wrong. Fixed two ways instead of
    # by relocating it: the "Built with Reflex" badge that used to sit in the same
    # corner is now disabled (rxconfig.py), and the toast itself gets an attention
    # cue on entrance — see `q-toast-pop`/`[data-sonner-toast]` in assets/qualify.css.
    toaster=rx.toast.provider(position="bottom-right", close_button=True),
    # The creator-discovery cards' pictures (`avatar_proxy.py`): a FastAPI app mounted
    # on the same backend, so the browser never touches a vendor's signed URL.
    api_transformer=avatar_api,
    # The Brand Kit deck's pointer drag (`assets/deck-drag.js`): plain DOM, delegated
    # at the document, so it is loaded once here rather than per page.
    head_components=[rx.script(src="/deck-drag.js")],
)

# Living style guide: static, no tenant data, so it needs no session. Not linked from
# the sidebar on purpose — it is for whoever builds screens, not for the business.
app.add_page(styleguide_index, route="/design", title="Qualify · Design system")

# Auth screens (QUA-66). An authenticated session skips them straight to the app.
app.add_page(
    login_index,
    route="/login",
    on_load=AuthState.redirect_if_authenticated,
    title="Qualify · Entrar",
)
app.add_page(
    signup_index,
    route="/signup",
    on_load=AuthState.redirect_if_authenticated,
    title="Qualify · Registrar negocio",
)

# Every business page requires a session: `require_login` runs FIRST in each on_load
# chain and redirects to /login when there is none. The loads behind it also refuse on
# their own when no tenant is present — the guard is UX, RLS + AuthState is the wall.
app.add_page(
    index,
    on_load=[AuthState.require_login, DashboardState.load_mentions],
    title="Qualify · Menciones",
)
app.add_page(
    connections_index,
    route="/connections",
    on_load=[AuthState.require_login, ConnectionsState.load_connections],
    title="Qualify · Conexiones",
)
app.add_page(
    publish_index,
    route="/publish",
    on_load=[AuthState.require_login, PublishState.load_active_connections],
    title="Qualify · Publicar",
)
app.add_page(
    inbox_index,
    route="/inbox",
    on_load=[AuthState.require_login, InboxState.load_screen],
    title="Qualify · Contenido",
)
app.add_page(
    leads_index,
    route="/leads",
    on_load=[AuthState.require_login, LeadsState.load_leads],
    title="Qualify · Leads",
)
app.add_page(
    clarity_index,
    route="/clarity",
    on_load=[AuthState.require_login, ClarityState.load],
    title="Qualify · Clarity",
)
# Fase 3 placeholder (see signals_page.py's module docstring) — static, no load beyond
# the session gate. Reached today only from the Brand Kit connect flow's final screen.
app.add_page(
    signals_index,
    route="/signals",
    on_load=AuthState.require_login,
    title="Qualify · Señales",
)
# Brand Content Engine (design §6): /brand is the default entry when the brand is not
# ready; /create is gated server-side by BrandReadiness (the load stores the verdict).
# The entry is now a yes/no question (¿tienes redes?, § request 2026-09-09) rather
# than a manual-vs-lookup fork — "Sí" and "No" both end up scraping a profile.
# `clear_entry` forgets a previous "No" answer, so only the answer given NOW decides
# whether the connect flow treats the walk as a fresh start.
app.add_page(
    brand_choice_index,
    route="/brand",
    on_load=[AuthState.require_login, BrandConnectState.clear_entry],
    title="Qualify · Marca",
)

# The "No, todavía no" answer's detour: instructions for creating an Instagram or
# TikTok account before the scraper has anything to read. Purely informational, no
# load beyond the session gate — Continuar hands off to /brand/connect itself.
app.add_page(
    brand_connect_setup_index,
    route="/brand/connect/setup",
    on_load=[AuthState.require_login],
    title="Qualify · Crea tu cuenta",
)

# The nine-step manual flow. No longer linked from the /brand fork (§ request
# 2026-09-09 — every kit now starts from a scraped profile), left routable directly:
# it also replaced the accordion screen in routing only (`creative_pages.brand_index`
# is left untouched in the code and simply has no route — re-adding it is one
# `app.add_page` call, no rewrite).
app.add_page(
    brand_manual_index,
    route="/brand/manual",
    # `resume` runs LAST on purpose: it decides the opening step by reading the kit, so
    # it has to see what `load_brand` just put there.
    on_load=[
        AuthState.require_login,
        CreativeState.load_brand,
        CreativeState.load_voice,
        BrandWizardState.resume,
    ],
    title="Qualify · Brand Kit",
)

# The scraper flow — reached from BOTH /brand answers now. No `resume` here: its
# first four screens read a profile rather than the kit, so there is no gap to jump
# to until the analysis has run.
app.add_page(
    brand_connect_index,
    route="/brand/connect",
    on_load=[AuthState.require_login, CreativeState.load_brand, CreativeState.load_voice],
    title="Qualify · Conectar redes",
)

app.add_page(
    create_index,
    route="/create",
    on_load=[AuthState.require_login, CreativeState.load_create],
    title="Qualify · Nuevo encargo",
)
app.add_page(
    drafts_index,
    route="/drafts",
    on_load=[AuthState.require_login, CreativeState.load_drafts],
    title="Qualify · Borradores",
)
app.add_page(
    draft_detail_index,
    route="/drafts/[draft_id]",
    on_load=[AuthState.require_login, CreativeState.load_draft],
    title="Qualify · Borrador",
)
# QUA-106 — Stories: un solo formulario de publicación (cuenta -> video -> preview
# -> Publicar -> STORIES), mismo patrón que /publish, con un panel de tendencias
# como referencia. No hay concepto de propuesta/aprobación/revisión ni pantalla de
# detalle — ver el rediseño de QUA-106.
app.add_page(
    stories_index,
    route="/stories",
    on_load=[AuthState.require_login, StoriesState.load_stories_screen],
    title="Qualify · Stories",
)
# UI demo, no backend: nothing to load, but the session gate still applies.
app.add_page(
    vitrina_index,
    route="/vitrina",
    on_load=AuthState.require_login,
    title="Qualify · Vitrina de locales",
)
