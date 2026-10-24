import asyncio
import contextlib
import logging

import reflex as rx
from qualify_api.auth import LEGACY_SIGNUP_ROUTE, SIGNUP_ROUTE
from qualify_api.planner.embedded import calendar_worker

from .auth_pages import (
    brand_start_index,
    forgot_index,
    login_index,
    reset_index,
    signup_index,
)
from .auth_state import BRAND_START_ROUTE, RESET_ROUTE, AuthState
from .avatar_proxy import avatar_api
from .brand_kit_editor import BrandEditState, brand_edit_index
from .campaign_state import CampaignState
from .canva_pages import canva_callback_index, canva_return_index
from .canva_state import CanvaState
from .catalog_page import catalog_index
from .catalog_state import CatalogState
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
from .creators_page import creators_index
from .gallery_state import GalleryState
from .home_page import home_index
from .home_state import HomeState
from .piece_download import router as piece_download_router
from .planner_back import WeekBackState
from .planner_page import planner_index
from .planner_state import PlannerState
from .publish_hub_state import PublishHubState
from .publishing_page import publish_index
from .publishing_state import PublishState
from .r2_media import router as r2_media_router
from .responder_page import legacy_redirect, responder_index
from .responder_state import ResponderState
from .settings_page import settings_index
from .signals_page import signals_index
from .state import DashboardState
from .styleguide_page import styleguide_index
from .ui import app_shell, page_body
from .voice_lab import VoiceLabState
from .whatsapp_page import whatsapp_index
from .whatsapp_state import WhatsAppState

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


# R2-only media for the draft screen (`r2_media.py`), on the same backend FastAPI app the
# avatar proxy already mounts through `api_transformer`.
avatar_api.include_router(r2_media_router)
# «Descargar todo» (m-24828908): a piece as a .zip, same backend app (`piece_download.py`).
avatar_api.include_router(piece_download_router)


def mentions_index() -> rx.Component:
    """Menciones (m-24842962): no longer the home — Inicio is `/` now (founder decision
    1, 2026-10-23). It keeps its own stable route until Resultados › «Quién habla de
    ti» (m-24843003) hosts it."""
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
    # The design system (tokens, Liquid Glass bridge + Radix skin, shell, primitives)
    # first; then one sheet per domain, each owned by its migration batch (plan D10).
    stylesheets=[
        _FONTS,
        "/qualify.css",
        "/qualify-planner.css",
        "/qualify-brand.css",
        "/qualify-publish.css",
        "/qualify-inbox.css",
        "/qualify-listen.css",
        "/qualify-creative.css",
    ],
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
    # The Brand Kit deck's pointer drag (`assets/deck-drag.js`) and the influence
    # ranking's (`assets/rank-drag.js`): plain DOM, delegated at the document, so they
    # are loaded once here rather than per page. These go through react-helmet, which
    # only injects them on Reflex >= 0.9.9 (`defer=False`); a venv left at 0.9.7 shows
    # them missing in dev while production (lock: 0.9.12) is fine — measured
    # 2026-10-08, PR #101. The sidebar's `assets/glass-nav.js` is loaded by the rail
    # itself (`ui.layout.sidebar`, an async `<script>` React hoists), independent of
    # the Reflex version.
    head_components=[rx.script(src="/deck-drag.js"), rx.script(src="/rank-drag.js")],
)


# QUA-111: the calendar worker runs INSIDE the backend process, so a running app means
# scheduled posts get published — nobody has to remember a separate command. By default
# it serves every tenant with a connected account, discovered on each tick (no per-tenant
# config); `qualify_api.planner.embedded` documents the optional overrides. Several
# backend processes, or the app plus a CLI worker, are safe together (claim + locks +
# idempotency).
@app.register_lifespan_task
@contextlib.asynccontextmanager
async def calendar_worker_lifespan():
    worker = calendar_worker()
    worker.start()
    try:
        yield
    finally:
        await asyncio.to_thread(worker.stop)


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
# The signup lives at /registro (founder rule 2026-10-21: no English a client sees, and the
# invite link shows this path). /signup stays as an alias of the same page: invite links
# already emailed with it are valid for 7 days, and `enter_signup` reads both parameters.
for _signup_route in (SIGNUP_ROUTE, LEGACY_SIGNUP_ROUTE):
    app.add_page(
        signup_index,
        route=_signup_route,
        on_load=AuthState.enter_signup,
        title="Qualify · Registrar negocio",
    )
# Forgotten password (2026-10-06): /forgot mails the provider's recovery link, which
# lands on /reset (that URL must be in Supabase's Redirect URLs allow list). /reset is
# NOT bounced for a logged-in session: the link may be opened in a browser that is in.
app.add_page(
    forgot_index,
    route="/forgot",
    on_load=AuthState.redirect_if_authenticated,
    title="Qualify · Recuperar contraseña",
)
app.add_page(
    reset_index,
    route=RESET_ROUTE,
    on_load=AuthState.enter_reset,
    title="Qualify · Nueva contraseña",
)
# The Brand Kit before login (§ request 2026-10-02): its first view asks for the email
# the kit is saved to; from there the Brand Kit's pages accept that pre-login draft
# (`AuthState.require_brand_access`) and the signup with the same email adopts it.
app.add_page(
    brand_start_index,
    route=BRAND_START_ROUTE,
    on_load=AuthState.enter_brand_start,
    title="Qualify · Crea tu marca",
)

# Every business page requires a session: `require_login` runs FIRST in each on_load
# chain and redirects to /login when there is none. The loads behind it also refuse on
# their own when no tenant is present — the guard is UX, RLS + AuthState is the wall.
# m-24842962 (NAV-4, N2): `/` is Inicio — login, a finished brand and the old storefront
# link all land here. An anonymous visitor is still sent to the Brand Kit's first view.
app.add_page(
    home_index,
    route="/",
    on_load=[AuthState.require_login_or_brand_start, HomeState.load],
    title="Qualify · Inicio",
)
app.add_page(
    mentions_index,
    route="/menciones",
    on_load=[AuthState.require_login, DashboardState.load_mentions],
    title="Qualify · Menciones",
)
app.add_page(
    connections_index,
    route="/connections",
    on_load=[
        AuthState.require_login,
        ConnectionsState.read_connect_result,
        ConnectionsState.load_connections,
    ],
    title="Qualify · Tus redes",
)
# WA-12: the WhatsApp module. `enter_page` reads `?tab=` and loads the tenant's numbers;
# each tab loads its own data on mount (see `whatsapp_page.py`).
app.add_page(
    whatsapp_index,
    route="/whatsapp",
    on_load=[AuthState.require_login, WhatsAppState.enter_page],
    title="Qualify · WhatsApp",
)
app.add_page(
    publish_index,
    route="/publish",
    # QUA-113: Publicaciones and Stories are two flows of this one page. Only the
    # Publicaciones accounts load here; `enter_publish_page` reads `?flow=`, and loads
    # the Stories accounts only when the visit starts on Stories (otherwise the first
    # switch to Stories does it).
    on_load=[
        AuthState.require_login,
        PublishState.load_active_connections,
        PublishHubState.enter_publish_page,
    ],
    title="Qualify · Publicar ahora",
)
# m-24842990 (ATENDER-1, founder decision 3): one «Por responder» with a tab per channel
# (`?tab=`). `enter_page` reads the tab and loads only its list (Comentarios, the private
# inbox, the commercial queries, the leads), plus the pending counts.
app.add_page(
    responder_index,
    route="/responder",
    on_load=[AuthState.require_login, ResponderState.enter_page],
    title="Qualify · Por responder",
)
# The old addresses of those lists stay as compatibility routes so saved links do not
# break (ux-guia-navegacion §3): each only redirects to its tab, keeping its query
# (`/conversations?consulta=<id>` lands on that card in «Quieren comprar»). Their titles
# stay while the menu (NAV lane) still names them.
app.add_page(
    legacy_redirect,
    route="/inbox",
    on_load=ResponderState.redirect_legacy,
    title="Qualify · Comentarios",
)
app.add_page(
    legacy_redirect,
    route="/conversations",
    on_load=ResponderState.redirect_legacy,
    title="Qualify · Conversaciones",
)
app.add_page(
    legacy_redirect,
    route="/leads",
    on_load=ResponderState.redirect_legacy,
    title="Qualify · Clientes interesados",
)
app.add_page(
    clarity_index,
    route="/clarity",
    on_load=[AuthState.require_login, ClarityState.load],
    title="Qualify · Tu página web",
)
# The two «Pronto» screens of the menu (N10, NAV-1 m-24842957): static, no load beyond
# the session gate; each says what is coming and links to something that works today.
app.add_page(
    signals_index,
    route="/signals",
    on_load=[AuthState.require_login],
    title="Qualify · Oportunidades",
)
app.add_page(
    creators_index,
    route="/creadores",
    on_load=[AuthState.require_login],
    title="Qualify · Creadores",
)
app.add_page(
    settings_index,
    route="/settings",
    on_load=[AuthState.require_session, AuthState.enter_settings],
    title="Qualify · Configuración",
)
# Canva round trip (§ request 2026-09-28): where Canva sends the user back after the
# OAuth consent and after "Return" in its editor. Both work in on_load and redirect to
# /create (the generator); both URLs must be registered in Canva's developer portal.
app.add_page(
    canva_callback_index,
    route="/canva/callback",
    on_load=[AuthState.require_login, CanvaState.finish_connect],
    title="Qualify · Conectando Canva",
)
app.add_page(
    canva_return_index,
    route="/canva/return",
    on_load=[AuthState.require_login, CanvaState.finish_return],
    title="Qualify · Volviendo de Canva",
)

# Brand Content Engine (design §6): /brand is the default entry when the brand is not
# ready. /create is the content generator; its BrandReadiness gate is lifted for now
# (§ request 2026-09-30) — the service still needs a kit and a voice to exist.
# The entry is now a yes/no question (¿tienes redes?, § request 2026-09-09) rather
# than a manual-vs-lookup fork — "Sí" and "No" both end up scraping a profile.
# `clear_entry` forgets a previous "No" answer, so only the answer given NOW decides
# whether the connect flow treats the walk as a fresh start.
# § 2026-10-02: this is the pre-login entry — a guest making their kit. Inside a session
# there is no "Marca": `enter_brand_home` sends a login (and a guest whose kit is
# already finished) to the editor, Negocio → Brand Kit, and a kit left halfway back
# into its wizard.
app.add_page(
    brand_choice_index,
    route="/brand",
    on_load=[
        AuthState.require_brand_access,
        BrandConnectState.clear_entry,
        BrandConnectState.enter_brand_home,
    ],
    title="Qualify · Crea tu marca",
)

# The "No, todavía no" answer's detour: instructions for creating an Instagram or
# TikTok account before the scraper has anything to read. Purely informational, no
# load beyond the session gate — Continuar hands off to /brand/connect itself.
app.add_page(
    brand_connect_setup_index,
    route="/brand/connect/setup",
    on_load=[AuthState.require_brand_access],
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
        AuthState.require_brand_access,
        CreativeState.load_brand,
        CreativeState.load_voice,
        BrandWizardState.resume,
        # Tu voz: the brand's cloned voice (Seed Speech), if any
        VoiceLabState.load_clone,
        # the saved brandboard and logo brief (§ 2026-10-01)
        BrandWizardState.load_saved_assets,
    ],
    title="Qualify · Tu marca",
)

# Editing an existing kit (§ request 2026-09-30), from the sidebar's "Negocio" block:
# the wizard's views over the same state, with a cursor of its own that every visit
# puts back on the first view.
app.add_page(
    brand_edit_index,
    route="/brand/kit",
    on_load=[
        AuthState.require_brand_access,
        CreativeState.load_brand,
        BrandEditState.restart,
        # Resultados e insights reads the stored referentes back (no search, no credits)
        BrandConnectState.load_saved_referentes,
        VoiceLabState.load_clone,
        # everything else the Brand Kit saved (§ 2026-10-01): the brandboard, the
        # connect flow's answers and the account as read, with its metrics
        BrandWizardState.load_saved_assets,
        BrandConnectState.load_saved_details,
    ],
    title="Qualify · Tu marca",
)

# The scraper flow — reached from BOTH /brand answers now. No `resume` here: its
# first four screens read a profile rather than the kit, so there is no gap to jump
# to until the analysis has run.
app.add_page(
    brand_connect_index,
    route="/brand/connect",
    on_load=[
        AuthState.require_brand_access,
        CreativeState.load_brand,
        CreativeState.load_voice,
        VoiceLabState.load_clone,
        BrandWizardState.load_saved_assets,
        # § 2026-10-02: a walk left halfway resumes — the saved answers and position,
        # and the referentes already found (read back, never bought twice)
        BrandConnectState.load_saved_details,
        BrandConnectState.load_saved_referentes,
    ],
    title="Qualify · Tu marca",
)

app.add_page(
    create_index,
    route="/create",
    on_load=[
        AuthState.require_login,
        CreativeState.load_create,
        CreativeState.load_catalog_products,
    ],
    title="Qualify · Crear publicación",
)
app.add_page(
    drafts_index,
    route="/drafts",
    on_load=[AuthState.require_login, GalleryState.load],
    title="Qualify · Por aprobar",
)
app.add_page(
    draft_detail_index,
    route="/drafts/[draft_id]",
    on_load=[
        AuthState.require_login,
        WeekBackState.read,  # m-24842987: «‹ Tu semana» when opened from there
        CreativeState.load_draft,
        CampaignState.load,
    ],
    title="Qualify · Revisar publicación",
)
# QUA-108 — Planificador: calendario editorial (vista semanal por horas + lista).
# Planifica qué POST sale, cuándo y en qué cuenta; no publica (eso es /publish ahora,
# o QUA-111 después).
app.add_page(
    planner_index,
    route="/planner",
    on_load=[AuthState.require_login, PlannerState.load_current_week],
    title="Qualify · Tu semana",
)


# QUA-106's Stories flow lives inside /publish since QUA-113 (a second flow next to
# Publicaciones, same form, same trending panel below). /stories stays as a
# compatibility route for old links and bookmarks: it only redirects.
def _stories_redirect() -> rx.Component:
    return rx.fragment()


app.add_page(
    _stories_redirect,
    route="/stories",
    on_load=rx.redirect("/publish?flow=stories", replace=True),
    title="Qualify · Historias",
)
# Catálogo de productos (plan-mvp-plantillas-remotion.md §2.1 #1): the brand's real
# products and media — what the template engine composes. Negocio → Catálogo.
app.add_page(
    catalog_index,
    route="/catalog",
    on_load=[AuthState.require_login, CatalogState.load_catalog],
    title="Qualify · Tus productos",
)


# m-24848515: the storefront demo was removed (founder, 2026-10-23: no relation to the
# product for now). Its route stays as a compatibility route so saved links do not
# break (ux-guia-navegacion §3): it only redirects home.
def _retired_demo_redirect() -> rx.Component:
    return rx.fragment()


app.add_page(
    _retired_demo_redirect,
    route="/vitrina",
    on_load=rx.redirect("/", replace=True),
    title="Qualify",
)
