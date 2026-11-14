"""Session auth for the CRM (QUA-66): the ONE source of the active tenant.

Replaces the dev tenant selector (`qualify_shared.dev` via `tenant.py`). Since ADR 43
(signed 2026-10-25; it reverses the `1 login = 1 tenant` rule of
`docs/modelo-negocio-operador-multi-emprendimiento.md` §6.1) one login may own several
businesses:

- **S3 (m-24849190):** a login with 2+ businesses lands on «¿Con qué negocio quieres
  trabajar?» (`/elegir-negocio`) before any `session_tenant_id` exists; the sidebar's
  top row then names the business (m-24976899; on a phone, «Estás en {negocio}» in the
  header).
- **S4 (m-24849191):** «Cambiar de negocio» does NOT reset this state in place: it
  abandons it for a NEW Reflex state, through a single-use pass (`business_switch.py`).

Custody rules, inherited from the states this replaces:

- `session_tenant_id` lives per-session (each websocket session has its own instance);
  it is set ONLY by a verified login (a single business), by `open_business` on the
  selector, or by a redeemed switch pass — never from a URL param, never defaulted to
  "the first tenant". No tenant id is ever sent to the browser: the selector and the
  menu send a position in the list, mapped back on the server (`_choice_ids`).
- `_auth_user_id` (the provider's id of the login) is backend-only and comes only from
  a verified `LoginResult` or a redeemed pass — never from a browser argument.
- `_access_token` is a backend-only var (leading underscore): it never serializes to
  the client. The browser holds nothing but the Reflex client token.
- All provider/DB work runs off the event loop (`asyncio.to_thread`), same as every
  other state here.

Logout hygiene (criteria 1-5 of the signed doc): revoke server-side FIRST
(`sign_out`, global scope), then destroy the Reflex state of every business substate,
then redirect to `/login` — the UI is never "cleaned in place". Client-persisted
business data is forbidden outside tenant-namespaced keys (enforced by
`test_auth_state.py`); today the app persists nothing, which trivially satisfies it.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator, Mapping
from urllib.parse import parse_qs, urlencode
from uuid import UUID

import reflex as rx
from qualify_api.auth import (
    INVITE_PARAM,
    LEGACY_INVITE_PARAM,
    SIGNUP_ROUTE,
    ActiveBusiness,
    AuthNotConfigured,
    AuthProviderError,
    DraftEmailInvalid,
    EmailHasAccount,
    IncompleteRegistration,
    InvalidCredentials,
    LoginResult,
    NoBusinessAccess,
    NotAMember,
    PasswordChangeInvalid,
    PasswordRejected,
    RateLimited,
    RegisteredBusiness,
    RegistrationInvalid,
    SessionExpired,
    SignupNotAllowed,
    authorize_signup,
    change_password,
    complete_password_reset,
    default_auth_provider,
    login_throttle,
    lookup_invite,
    memberships_for,
    open_business,
    register_business,
    request_password_reset,
    reset_request_throttle,
    resolve_login,
    signup_open,
    start_brand_kit_draft,
    throttle_key,
)
from qualify_api.tenancy.locale import LocaleInvalid, resolve_locale
from redis.exceptions import RedisError
from reflex.config import get_config
from sqlalchemy.exc import SQLAlchemyError

from .access_vm import ACCESS_DOWN, CODE_DEAD, CODE_EMPTY, invite_token_from_text
from .business_switch import (
    issue_switch_pass,
    pass_from_fragment,
    redeem_switch_pass,
    switch_script,
)
from .business_vm import (
    CHOICE_EXPIRED,
    CHOOSE_ROUTE,
    SWITCH_DOWN,
    SWITCH_NO_ACCESS,
    SWITCH_PASS_DEAD,
    business_menu,
    chip_label,
    logo_needs_refresh,
    opening_label,
    parse_choice_index,
    switch_choices,
    switch_trigger_aria,
    trigger_label,
)
from .pending_vm import FORGET_TITLE_BUSINESS_JS
from .review_links import review_destination

logger = logging.getLogger(__name__)

_BAD_CREDENTIALS = "Correo o contraseña incorrectos."  # one message for every cause, on purpose
_INCOMPLETE = (
    "El registro de esta cuenta quedó incompleto. Repite el registro con el mismo "
    "correo y contraseña para completarlo."
)
_AUTH_DOWN = "No se pudo verificar la sesión. Inténtalo de nuevo en un momento."
_RATE_LIMITED = "Demasiados intentos seguidos. Espera un minuto y vuelve a intentarlo."
_RESET_LINK_DEAD = "Este enlace ya venció o ya se usó. Pide uno nuevo y ábrelo desde el correo."
_RESET_LINK_MISSING = "Abre el enlace que te enviamos por correo para crear tu nueva contraseña."
_SESSION_STALE = "Tu sesión es antigua. Sal, vuelve a entrar y cambia la contraseña."


def _wait_message(seconds: int) -> str:
    """ "Try again later" with the real wait, so a locked-out operator is not guessing."""
    if seconds < 60:
        return f"Demasiados intentos fallidos. Espera {seconds} s y vuelve a intentarlo."
    return (
        f"Demasiados intentos fallidos. Espera {math.ceil(seconds / 60)} min y vuelve a "
        "intentarlo, o recupera tu contraseña."
    )


def _email_looks_valid(email: str) -> bool:
    return email.count("@") == 1 and "." in email.split("@")[1] and " " not in email


_SIGNUP_DEFAULTS = {"country": "VE", "timezone": "America/Caracas", "currency": "USD"}


def _login_blocking(email: str, password: str):
    return resolve_login(default_auth_provider(), email, password)


def _signup_blocking(
    business_name: str,
    email: str,
    password: str,
    country: str,
    timezone: str,
    currency: str,
    invite_token: str = "",
):
    # The gate decides BEFORE the identity user exists; the invite is spent inside
    # register_business's transaction (`invites` module docstring).
    invite_id = authorize_signup(email, invite_token or None)
    if invite_token:
        invite = lookup_invite(invite_token)
        if invite is not None and invite.is_add_business:
            raise SignupNotAllowed(
                "Abre de nuevo el enlace del correo y confirma tu contraseña actual "
                "para agregar este negocio."
            )
    return register_business(
        default_auth_provider(),
        business_name=business_name,
        email=email,
        password=password,
        country=country,
        timezone=timezone,
        currency=currency,
        invite_id=invite_id,
    )


def invite_token_from_query(params: Mapping[str, object]) -> str:
    """The invite token of the signup URL: `?invitacion=` (what emails carry since
    2026-10-21) or the old `?invite=` of links sent before, still within their days."""
    for name in (INVITE_PARAM, LEGACY_INVITE_PARAM):
        token = str(params.get(name, "") or "")
        if token:
            return token
    return ""


def _invite_blocking(token: str) -> tuple[str, str, bool]:
    """(email, business, add-business mode) of a still-usable invite; empty when
    unknown, used or expired."""
    invite = lookup_invite(token)
    return (
        (invite.email, invite.business_name, invite.is_add_business)
        if invite is not None
        else ("", "", False)
    )


def _add_business_blocking(
    password: str, token: str, access_token: str, has_session: bool
) -> tuple[RegisteredBusiness, LoginResult | None]:
    """Resolve the invitation again on the server; form fields never choose its account.

    A live session may keep its tenant only after the provider confirms that its token
    belongs to the invited account. Changing identities requires the normal logout,
    which clears every business substate.
    """
    invite = lookup_invite(token)
    if invite is None or not invite.is_add_business:
        raise SignupNotAllowed(
            "Esta invitación venció o ya se usó. Pide una nueva a quien te invitó."
        )
    provider = default_auth_provider()
    if has_session:
        try:
            session_email = provider.user_email(access_token) if access_token else ""
        except SessionExpired:
            session_email = ""
        if session_email.strip().casefold() != invite.email.strip().casefold():
            raise SignupNotAllowed(
                "Esta invitación es para otra cuenta o tu sesión venció. "
                "Cierra sesión y vuelve a abrir el enlace del correo."
            )
    invite_id = authorize_signup(invite.email, token)
    # Resolve the anonymous login before consuming the invite: an IdP failure after
    # commit must not leave a successful registration displayed as an unusable link.
    try:
        login = None if has_session else resolve_login(provider, invite.email, password)
    except InvalidCredentials:
        raise RegistrationInvalid("Esa contraseña no coincide. Inténtalo otra vez.") from None
    registered = register_business(
        provider,
        business_name=invite.business_name,
        email=invite.email,
        password=password,
        **_SIGNUP_DEFAULTS,
        invite_id=invite_id,
    )
    return registered, login


def _sign_out_blocking(access_token: str) -> None:
    default_auth_provider().sign_out(access_token)


def _open_business_blocking(auth_user_id: str, tenant_id: str) -> ActiveBusiness:
    """The fresh membership check (ADR 43 §2.1): `NotAMember` unless the login still
    has a seat in that business. Both ids come from server-side state, never the client."""
    return open_business(UUID(auth_user_id), UUID(tenant_id))


def _memberships_blocking(auth_user_id: str) -> list[tuple[str, str]]:
    """(tenant id, business name) of every business the login may open, by name."""
    return [(str(m.tenant_id), m.tenant_name) for m in memberships_for(UUID(auth_user_id))]


#: What a switch pass store or a Redis outage raises: the switch is refused and the
#: owner stays in the business they were in.
_SWITCH_STORE_ERRORS: tuple[type[BaseException], ...] = (RedisError, OSError)


def business_state_classes() -> tuple[type[rx.State], ...]:
    """Every state that holds data of ONE business. A logout resets all of them, and so
    does a redeemed switch pass (defence in depth: the pass already lands in a NEW
    Reflex state, ADR 43 §2.2). `test_auth_state.py` enumerates every `rx.State` at
    runtime and fails when a new one is neither here nor in its reviewed list of
    states without business data (A13).

    Imported here, not at module top: these modules read AuthState, and a top-level
    import would be circular."""
    from .ad_accounts_state import AdAccountsState
    from .ad_enhancements_state import AdEnhancementsState
    from .ad_forms_state import AdFormsState
    from .ad_results_state import AdResultsState
    from .ask_more_state import AskMoreState
    from .brand_answers import BrandAnswersState
    from .brand_avatar_panel import BrandAvatarState
    from .brand_documents import BrandDocumentState
    from .brand_kit_editor import BrandEditState
    from .brand_minimal import BrandMinimalState
    from .brand_proposal import BrandProposalState
    from .campaign_state import CampaignState
    from .canva_state import CanvaState
    from .catalog_choose_state import CatalogChooseState
    from .catalog_cut_state import CatalogCutState
    from .catalog_gallery_state import CatalogGalleryState
    from .catalog_group_state import CatalogGroupState
    from .catalog_order_state import CatalogOrderState
    from .catalog_state import CatalogState
    from .catalog_whatsapp_state import CatalogWhatsAppState
    from .clarity_state import ClarityState
    from .connections_state import ConnectionsState
    from .conversations_state import ConversationsState
    from .create_gallery_state import CreateGalleryState
    from .creative_state import CreativeState
    from .creative_wizard_pages import BrandConnectState, BrandWizardState
    from .creators_access import CreatorsAccessState
    from .creators_state import CreatorsCompareState, CreatorSheetState, CreatorsState
    from .discover_reels import DiscoverReelsState
    from .final_review_state import FinalReviewState
    from .final_video_card_state import FinalVideoState
    from .followups_state import FollowupsState
    from .gallery_state import GalleryState
    from .gen_gallery_pick_state import GenGalleryPickState
    from .generation_state import GenerationState
    from .home_state import HomeState
    from .ice_breakers_state import IceBreakersState
    from .inbox_list_state import InboxListState
    from .inbox_state import InboxState
    from .leads_state import LeadsState
    from .offer_mark_state import OfferMarkState
    from .part_progress_state import PartProgressState
    from .parts_start_state import PartsStartState
    from .pending_state import PendingState
    from .pinterest_state import PinterestState
    from .planner_back import WeekBackState
    from .planner_state import PlannerState
    from .product_sticker_state import ProductStickerState
    from .promotion_state import PromotionState
    from .publish_hub_state import PublishHubState
    from .publishing_state import PublishState
    from .reconnect_state import ReconnectState
    from .replies_state import RepliesState
    from .responder_state import ResponderState
    from .results_state import ResultsState
    from .seasonal_state import SeasonalState
    from .settings_state import SettingsState
    from .state import DashboardState
    from .tiktok_state import TikTokConnectionsState, TikTokDraftState
    from .trending_state import TrendingState
    from .variations_state import VariationsState
    from .voice_lab import VoiceLabState
    from .whatsapp_campaigns_state import WhatsAppCampaignsState
    from .whatsapp_chats_state import WhatsAppChatsState
    from .whatsapp_contacts_state import WhatsAppContactsState
    from .whatsapp_location_state import WhatsAppLocationState
    from .whatsapp_menu_state import WhatsAppMenuState
    from .whatsapp_metrics_state import WhatsAppMetricsState
    from .whatsapp_payments_state import WhatsAppPaymentsState
    from .whatsapp_state import WhatsAppState
    from .whatsapp_templates_state import WhatsAppTemplatesState

    return (
        AdAccountsState,
        # m-24985141: the generator's «Elegir de tu Galería» drawer
        GenGalleryPickState,
        AdEnhancementsState,
        AdFormsState,
        PromotionState,
        AdResultsState,
        ConnectionsState,
        # m-24946129 / m-24946132: Creadores — the switch, the list, a sheet, Comparar
        CreatorsAccessState,
        CreatorsState,
        CreatorSheetState,
        CreatorsCompareState,
        # m-24921091: the tenant's TikTok accounts and a piece's last draft
        TikTokConnectionsState,
        TikTokDraftState,
        ReconnectState,
        LeadsState,
        # m-24842990 «Por responder»: the open tab and the tenant's pending counts
        ResponderState,
        ClarityState,
        InboxState,
        PublishState,
        # «Publicar ahora»: the assistant's motion and its leave guard
        PublishHubState,
        DashboardState,
        CreativeState,
        # m-24921082 UI-7: the rows of a video by parts
        PartProgressState,
        PinterestState,
        FinalVideoState,  # m-24921084: «Tu video completo» of a video by parts
        # «Descubrir reels» (2026-10-15): the brand's referentes' reels
        DiscoverReelsState,
        # The Brand Kit wizard's OWN draft fields (request 2026-09-08) — step, chosen
        # plan, staged logo, the connect flow's read profile. None of this lives in
        # `CreativeState`, so it was never covered by the reset above: without these
        # two, a logout still left an in-progress wizard's cursor and unsaved choices
        # sitting in memory for whoever logs in next on this browser.
        BrandWizardState,
        BrandConnectState,
        # m-24848529: the five steps' cursor and example phrase
        BrandMinimalState,
        # m-24852199: the Alta's proposed Brand Kit under review (tenant data)
        BrandProposalState,
        # The wizard's staged brief / brandboard and their pending proposals (request
        # 2026-09-25) — tenant files and tenant kit values.
        BrandDocumentState,
        RepliesState,
        # the trending panel: its Meta audio list belongs to a tenant account
        TrendingState,
        PlannerState,
        FinalReviewState,
        # the POST gallery (QUA-118): the tenant's POSTs and the filters
        GalleryState,
        # Inicio (m-24842962): the tenant's pending counts and week figures
        HomeState,
        # Resultados (m-24843003): the open tab and the week's figures
        ResultsState,
        # the POST's «Campaña» field (QUA-143): the brand's campaigns
        CampaignState,
        # the Canva card: links of a draft and the pending OAuth verifier
        CanvaState,
        # Tu voz (2026-09-30): the staged recording, the analysis and the clone
        VoiceLabState,
        # the product catalog (2026-10-05): the tenant's products, the open editor and
        # any files still parked for ingest
        CatalogState,
        # m-24955643 «Ordenar tu menú»: the brand's categories and products in order,
        # the queued writes and the cached brand id
        CatalogOrderState,
        # m-24955838 «Agrupa tus productos»: the products without a category, the
        # proposed groups and the last move («Deshacer»)
        CatalogGroupState,
        # m-25017357 Galería › WhatsApp catalog: the per-product states, the plan the
        # owner is confirming and the products sent from this tab
        CatalogWhatsAppState,
        # m-24955648 «Formas de pago»: the business's methods, the open form and the QR
        # parked for it
        WhatsAppPaymentsState,
        # m-24955919 «Fotos y videos de tu negocio»: the business's own media (their
        # view paths), its jobs and the cached brand id
        CatalogGalleryState,
        # m-24955924 «Corta tu video en partes»: the open video and its timeline
        CatalogCutState,
        # m-24955926 «Elegir para una publicación»: the media on screen and the choice
        CatalogChooseState,
        # m-24955928 «Crear» with Galería media: the chosen media and the request key
        CreateGalleryState,
        # m-24803289 «Variaciones»: the chosen catalog product, its presets and the
        # angles under review (with the brand id cached behind them)
        VariationsState,
        # WA-12: the tenant's WhatsApp numbers, business profile and QR codes
        WhatsAppState,
        # WA-11: the number's conversations, the open thread, the composer draft and the
        # acting user's id (a backend var — `reset` clears those too)
        WhatsAppChatsState,
        # QUA-226: the private inbox — accounts, access state, threads, the open
        # conversation, the reply draft and the acting user's id
        ConversationsState,
        # m-25017859: the single chat list of «Por responder» — rows, counts, the
        # notice's per-business dismissal and the scroll kept for the way back
        InboxListState,
        # m-24789646: «Consultas desde comentarios» (cards, drafts being edited)
        FollowupsState,
        # m-24789472: «Preguntas iniciales» — the account's draft questions, its status
        # and the acting user's id
        IceBreakersState,
        # WA-16: the number's menus, the open editor draft and the preview chat
        WhatsAppMenuState,
        # WA-18: templates, opt-ins, campaigns and the Conexión metrics block
        WhatsAppTemplatesState,
        WhatsAppContactsState,
        WhatsAppCampaignsState,
        WhatsAppMetricsState,
        # m-24842963: the menu's pending counts of this tenant
        PendingState,
        # m-24945889: which piece is this business's «Tu oferta», and the map point
        OfferMarkState,
        WhatsAppLocationState,
        # m-24973458: whether a publication of this tenant is being made
        GenerationState,
        # m-24842967: Configuración's country and currency of the business
        SettingsState,
        # m-24976895: the brand's seasonal stickers and videos and their flow
        SeasonalState,
        # m-25017912: «Tu producto en sticker»'s products, drawings and chosen messages
        ProductStickerState,
        # m-24852129: the ask-more button — whether this business's request waits
        AskMoreState,
        # m-24921079: «Armar mi video por partes» — the sentence about this business's product
        PartsStartState,
        # Found by the runtime enumeration of ADR 43 A13 (2026-11-02): four states with
        # business data that no logout reset before. The answers path's drafts of the
        # tenant's own proposal; the avatar card's signed image link; the kit editor's
        # «Cancelar» snapshot of the kit; «‹ Tu semana»'s link back from a ficha.
        BrandAnswersState,
        BrandAvatarState,
        BrandEditState,
        WeekBackState,
    )


#: Where the recovery email's link lands. Must be in Supabase's "Redirect URLs" allow
#: list (Authentication → URL Configuration), or GoTrue falls back to the Site URL and
#: the token never reaches this page.
RESET_ROUTE = "/reset"


def _reset_redirect_url() -> str:
    base = (get_config().deploy_url or "http://localhost:3000").rstrip("/")
    return f"{base}{RESET_ROUTE}"


def _request_reset_blocking(email: str) -> None:
    request_password_reset(default_auth_provider(), email, _reset_redirect_url())


def _complete_reset_blocking(token: str, password: str, confirm: str) -> LoginResult:
    return complete_password_reset(default_auth_provider(), token, password, confirm)


def _change_password_blocking(email: str, current: str, new: str, confirm: str) -> str:
    return change_password(default_auth_provider(), email, current, new, confirm)


def _start_draft_blocking(email: str, invite_token: str = ""):
    """The pre-login draft for `email`. With the session's invite (PB-5, m-24852199), the
    draft an Alta prepared for that invite — its proposed Brand Kit included — is the one
    resumed (`start_brand_kit_draft` checks the invite is usable, for that email and that
    Alta); without it, reserved drafts stay invisible."""
    return start_brand_kit_draft(email, **_SIGNUP_DEFAULTS, invite_token=invite_token or None)


def _kit_complete_blocking(tenant_id) -> bool:
    """Does the business have a finished Brand Kit? (§ request 2026-10-02: a session
    without one is sent to make it.)"""
    from .brand_finish import tenant_kit_status  # brand_finish imports this module

    return tenant_kit_status(tenant_id).completed


def _draft_destination_blocking(tenant_id) -> str:
    """Where a pre-login draft goes after its email (§ request 2026-10-02): a finished
    kit to the signup (there is no account to log into yet), a wizard left halfway back
    into it, anything else to the start of the Brand Kit."""
    from .brand_finish import tenant_kit_status  # brand_finish imports this module

    status = tenant_kit_status(tenant_id)
    if status.completed:
        return SIGNUP_ROUTE
    return status.resume_route or "/brand"


#: The Brand Kit's first view, before any login: asks for the email (§ 2026-10-02).
BRAND_START_ROUTE = "/brand/start"


def brand_gate_url(path: str) -> str:
    """Where an unfinished brand is sent from another page: /brand, saying which page
    it came from (`?desde=responder`), so /brand can tell why (PASOS-4 UX review)."""
    slug = (path or "").strip().strip("/")
    if not slug or slug.startswith("brand"):
        return "/brand"
    return f"/brand?{urlencode({'desde': slug})}"


#: m-24842965: a signup that adopted the pre-login Brand Kit ends on the same «Tu marca
#: está lista» card a logged-in finish shows — the manual wizard's page raises it when the
#: URL carries this query (`creative_wizard_pages._asks_for_ready_card`).
BRAND_READY_QUERY = "lista=1"
BRAND_READY_ROUTE = f"/brand/manual?{BRAND_READY_QUERY}"

#: Where a login may land: the app, the Brand Kit, or the card of a Brand Kit a signup
#: just adopted.
_POST_LOGIN_ROUTES = frozenset({"/", "/brand/kit", BRAND_READY_ROUTE})


def brand_tenant_id(auth: AuthState) -> str:
    """The tenant the Brand Kit reads and writes: the logged-in one, else the pre-login
    draft's (§ request 2026-10-02). Only the Brand Kit may use this — every other page
    keeps `session_tenant_id`, so a draft never opens anything but the Brand Kit."""
    return auth.session_tenant_id or auth.guest_tenant_id


async def reload_business_logo(state: rx.State, *, stale: bool = False) -> None:
    """Read the open business's logo into `AuthState.business_logo_src` from a
    background handler's `state` (any state of the tab). `stale` skips the freshness
    test — Tu marca was just saved, so the logo may have changed. Never raises: a
    database or token-store failure leaves the store icon."""
    from .business_logo_provider import business_logo_path  # noqa: PLC0415

    async with state:
        auth = state if isinstance(state, AuthState) else await state.get_state(AuthState)
        tenant = auth.session_tenant_id
        if not tenant:
            auth.business_logo_src = ""
            auth._logo_tenant = ""
            return
        fetched_at = 0.0 if stale else auth._logo_fetched_at
        if not logo_needs_refresh(
            tenant=tenant,
            logo_tenant=auth._logo_tenant,
            fetched_at=fetched_at,
            now=time.time(),
        ):
            return
        # Claimed before the read: a second mount meanwhile does not read it twice.
        auth._logo_fetched_at = time.time()
        auth._logo_tenant = tenant
    failed = False
    try:
        path = await asyncio.to_thread(business_logo_path, UUID(tenant))
    except Exception as exc:  # never sinks the caller (a Tu marca save, a page mount)
        logger.warning("business logo unreadable: %s", type(exc).__name__)
        path, failed = "", True
    async with state:
        auth = state if isinstance(state, AuthState) else await state.get_state(AuthState)
        if auth.session_tenant_id == tenant:  # still the same business
            auth.business_logo_src = path
            if failed:
                auth._logo_fetched_at = 0.0  # the next mount tries again


class AuthState(rx.State):
    """Login/signup/logout and custody of the authenticated tenant."""

    # Set exclusively by a verified login, the business selector or a redeemed switch
    # pass. Every other state reads it via `self.get_state(AuthState)`; none may write it.
    session_tenant_id: str = ""
    business_name: str = ""
    user_email: str = ""

    # ADR 43 (S3/S4): the login's businesses, by name — ONLY names reach the browser; the
    # tenant id of each position lives in the backend-only `_choice_ids`.
    business_names: list[str] = []
    #: Position of the open business in `business_names`; -1 before one is open.
    active_business_index: int = -1
    #: True between a login with 2+ businesses and the choice on /elegir-negocio.
    awaiting_business_choice: bool = False
    #: The business being opened (selector or switch): «Abriendo {negocio}…».
    opening_business: str = ""
    #: m-24976899: the open business's main Brand Kit logo, as a short-lived
    #: `/r2media/<token>` path ("" = none: the sidebar shows the store icon). Read by
    #: `refresh_business_logo` on the shell's mount and after Tu marca is saved.
    business_logo_src: str = ""

    auth_error: str = ""
    is_authenticating: bool = False
    #: The password fields' eye toggle (login, signup, reset, change). UI only.
    show_password: bool = False

    # Forgotten password (2026-10-06). `reset_sent_to` is the address the screen says
    # it emailed — shown back whether or not it has an account (no enumeration).
    reset_sent_to: str = ""
    #: The /reset page: "checking" (reading the link), "ready" (form), "invalid".
    reset_link_state: str = "checking"
    #: Change-password card on /settings: a success line after saving.
    password_saved: bool = False

    # Signup gate: invite-only for the MVP (founder decision 2026-10-14).
    #: MVP: signup is invite-only. True only in dev (`QUALIFY_SIGNUP_OPEN=1`).
    signup_open: bool = False
    #: "" (no invite in the URL), "ok" (valid: the email is fixed) or "invalid".
    invite_state: str = ""
    invite_email: str = ""
    invite_business: str = ""
    invite_is_add_business: bool = False
    added_business_name: str = ""
    #: MARCA-5 (m-24842968): the code typed on the access gate did not open anything.
    invite_code_error: str = ""

    # The Brand Kit before login (§ request 2026-10-02): the draft tenant provisioned for
    # the email typed on /brand/start. Set ONLY by `start_brand_kit` and read ONLY by the
    # Brand Kit (`brand_tenant_id`); it opens no other page — every other route still
    # requires `session_tenant_id`. A login clears it.
    guest_tenant_id: str = ""
    guest_email: str = ""
    guest_error: str = ""
    guest_has_account: bool = False
    #: The email typed on /brand/start when it already has an account: /login opens
    #: with it filled in (§ 2026-10-02). Never used to authenticate anything.
    login_email_hint: str = ""
    #: Whether the session's business has a FINISHED Brand Kit (§ request 2026-10-02:
    #: a session without one is sent to make it). Read once at login
    #: (`brand_finish.tenant_kit_status`), set again when a wizard finishes.
    brand_kit_complete: bool = True

    # Backend-only (never serialized to the client). Held so logout can revoke.
    _access_token: str = ""
    _session_user_id: str = ""
    # The recovery link's token while /reset is open. Backend-only, like the above:
    # it can set the account's password, so it never goes back to the browser.
    _recovery_token: str = ""
    # The invite link's token while the signup page is open. Backend-only: it is a credential.
    _invite_token: str = ""
    # The rate-limit key must come from the server lookup, never a display var's setter.
    _invite_email: str = ""
    _invite_add_business: bool = False
    # ADR 43: the provider's id of the login (from the verified LoginResult or a redeemed
    # switch pass, never from the browser) and the tenant id behind each position of
    # `business_names`. Backend-only.
    _auth_user_id: str = ""
    _choice_ids: list[str] = []
    # Where a login waiting on the selector goes once a business is open.
    _choice_next: str = ""
    # A notice the next /login shows once (its on_load clears every other error).
    _login_notice: str = ""
    # m-24976899: which tenant `business_logo_src` belongs to and when it was minted
    # (time.time()); 0 = read it again on the next shell mount.
    _logo_tenant: str = ""
    _logo_fetched_at: float = 0.0
    #: That notice, on screen: not an error (a reload, a pass that ran out), so /login
    #: shows it in the informative tone, apart from `auth_error`.
    login_notice: str = ""

    @rx.var
    def is_authenticated(self) -> bool:
        return bool(self.session_tenant_id)

    @rx.var
    def can_switch_business(self) -> bool:
        """«Cambiar de negocio» exists only for a session whose login has 2+ businesses."""
        return bool(self.session_tenant_id) and len(self.business_names) > 1

    @rx.var
    def added_business_next(self) -> str:
        """Where «Continuar» goes after an add-business Alta (S7): the selector when the
        login is waiting to choose a business, else the app."""
        return CHOOSE_ROUTE if self.awaiting_business_choice else "/"

    @rx.var
    def business_chip_label(self) -> str:
        """The header chip: «Estás en {negocio}», or «Abriendo {negocio}…» while a
        switch is on its way."""
        if self.opening_business:
            return opening_label(self.opening_business)
        return chip_label(self.business_name)

    @rx.var
    def business_trigger_label(self) -> str:
        """The sidebar's top row: the business name, or «Abriendo {negocio}…»."""
        return trigger_label(self.business_name, self.opening_business)

    @rx.var
    def business_trigger_aria(self) -> str:
        """«Estás en {negocio}. Cambiar de negocio» on the name that opens the menu."""
        return switch_trigger_aria(self.business_name, self.opening_business)

    @rx.var
    def business_menu(self) -> list[dict[str, str]]:
        """Every business of the login for the sidebar's menu, the open one flagged."""
        return business_menu(self.business_names, self.active_business_index)

    @rx.var
    def business_choices(self) -> list[dict[str, str]]:
        """Every business of a login waiting on the selector, each with its position."""
        return switch_choices(self.business_names, -1)

    @rx.var
    def opening_business_label(self) -> str:
        return opening_label(self.opening_business) if self.opening_business else ""

    @rx.var
    def switch_options(self) -> list[dict[str, str]]:
        """The other businesses of the login, each with its position (never its id).
        No screen reads it since m-24976899 (the sidebar uses `business_menu`); kept
        as the S4 contract its tests pin."""
        return switch_choices(self.business_names, self.active_business_index)

    @rx.var
    def is_guest(self) -> bool:
        return not self.session_tenant_id and bool(self.guest_tenant_id)

    @rx.event
    def require_login(self) -> rx.event.EventSpec | None:
        """First `on_load` event of every protected page. Without a session the first
        view is the Brand Kit, never the login (§ request 2026-10-02: "/brand/start y
        después /login"): its email screen links to /login for an existing account, and
        a guest already in a draft goes back to it. A session whose business has no
        finished Brand Kit is sent to make it (/brand: the question, or the wizard it
        left halfway) — the Brand Kit's own pages use `require_brand_access`."""
        if not self.session_tenant_id:
            from urllib.parse import urlencode

            try:
                destination = review_destination(
                    self.router.url.path + "?" + urlencode(dict(self.router.url.query_parameters))
                )
            except Exception:
                destination = ""
            if destination:
                return rx.redirect("/login?" + urlencode({"volver": destination}))
            return rx.redirect("/brand" if self.guest_tenant_id else BRAND_START_ROUTE)
        if not self.brand_kit_complete:
            return rx.redirect(brand_gate_url(self.router.url.path))
        return None

    @rx.event
    def require_session(self) -> rx.event.EventSpec | None:
        """`on_load` of the account's own settings: a login is enough. Unlike
        `require_login` it does not send an unfinished Brand Kit to /brand — changing
        the password must never wait on the kit. A pre-login draft does not pass."""
        if not self.session_tenant_id:
            return rx.redirect("/login")
        return None

    @rx.event
    def require_brand_access(self) -> rx.event.EventSpec | None:
        """First `on_load` of the Brand Kit's pages: a login OR a pre-login draft. With
        neither, the first view asks for the email (/brand/start)."""
        if not self.session_tenant_id and not self.guest_tenant_id:
            return rx.redirect(BRAND_START_ROUTE)
        return None

    @rx.event
    def require_login_or_brand_start(self) -> rx.event.EventSpec | None:
        """`on_load` of `/`: the Brand Kit comes before the login (§ 2026-10-02), so an
        anonymous visitor lands on its first view — which links to /login.

        PASOS-4 (m-24852243, N2): a session opens Inicio even with Tu marca half done —
        «‹ Inicio» and «Seguir después» lead there from every step, and Inicio lists
        «Termina tu marca» first (`home_vm`). Every other page still sends an
        unfinished kit to /brand (`require_login`)."""
        if self.session_tenant_id:
            return None
        return rx.redirect("/brand" if self.guest_tenant_id else BRAND_START_ROUTE)

    @rx.event
    def redirect_if_authenticated(self) -> rx.event.EventSpec | None:
        """`on_load` of /login, the signup and /forgot: an authenticated session skips
        them; otherwise each opens clean (no error or eye state left by another) — except
        the one notice a business choice or switch left on purpose (`_login_notice`).

        A login that was still waiting on the business selector (the owner pressed «atrás»
        on it) is dropped here: entering again starts over."""
        self.auth_error = ""
        self.login_notice = self._login_notice
        self._login_notice = ""
        self.show_password = False
        self.reset_sent_to = ""
        self.signup_open = signup_open()
        if self.session_tenant_id:
            return rx.redirect(self.login_return or "/")
        if self.awaiting_business_choice:
            self._forget_business_choice()
        return None

    def _forget_business_choice(self) -> None:
        self.awaiting_business_choice = False
        self.opening_business = ""
        self.business_names = []
        self.active_business_index = -1
        self._choice_ids = []
        self._choice_next = ""
        self._auth_user_id = ""
        # Not revoked: the provider's sign-out is global and would also close the
        # owner's other tabs. It simply leaves this state (and expires on its own).
        self._access_token = ""

    @rx.var
    def login_return(self) -> str:
        try:
            raw = str(self.router.url.query_parameters.get("volver", ""))
        except Exception:
            return ""
        return review_destination(raw)

    @rx.event
    async def enter_signup(self):
        """`on_load` of the signup (/registro and its old alias /signup): bounce a
        session and read the invite link. Without a valid invite the page says Qualify
        is invite-only (unless dev opened signup). The token leaves the URL right away."""
        self.auth_error = ""
        self.show_password = False
        self.signup_open = signup_open()
        token = invite_token_from_query(self.router.url.query_parameters)
        if not token:
            if self.added_business_name:
                return None
            if self.session_tenant_id and not (
                self._invite_token and self.invite_is_add_business and self.invite_state == "ok"
            ):
                return rx.redirect("/")
            if not self._invite_token:  # a reload after the URL was cleaned keeps it
                self.invite_state = ""
                self.invite_email = ""
                self._invite_email = ""
                self.invite_business = ""
                self.invite_is_add_business = False
                self._invite_add_business = False
            return None
        self.added_business_name = ""
        try:
            email, business, is_add_business = await asyncio.to_thread(_invite_blocking, token)
        except SQLAlchemyError as exc:
            logger.error("invite lookup failed: %s", type(exc).__name__)
            email, business, is_add_business = "", "", False
        if self.session_tenant_id and email and not is_add_business:
            return rx.redirect("/")
        self._invite_token = token if email else ""
        self.invite_email = email
        self._invite_email = email
        self.invite_business = business
        self.invite_is_add_business = is_add_business
        self._invite_add_business = is_add_business
        self.invite_state = "ok" if email else "invalid"
        return rx.call_script("history.replaceState(null, '', window.location.pathname)")

    @rx.event
    def toggle_show_password(self) -> None:
        self.show_password = not self.show_password

    @rx.event
    def enter_brand_start(self) -> rx.event.EventSpec | None:
        """`on_load` of /brand/start: someone already in (login or draft) goes on."""
        self.guest_error = ""
        self.guest_has_account = False
        self.invite_code_error = ""
        self.signup_open = signup_open()
        if self.session_tenant_id or self.guest_tenant_id:
            return rx.redirect("/brand")
        return None

    @rx.event(background=True)
    async def redeem_invite_code(self, form_data: dict):
        """MARCA-5 (m-24842968, founder decision 7b): the access gate's «Tengo mi
        código». A usable invite becomes this session's invite (the same custody as the
        emailed link: the token stays backend-only) and the visitor goes on — into the
        Brand Kit, saved under the invite's email, from /brand/start; straight to the
        form from the signup page (`next` = "signup"). A code that opens nothing says so
        and how to get a good one."""
        token = invite_token_from_text(str(form_data.get("code", "")))
        to_signup = str(form_data.get("next", "")) == "signup"
        if not token:
            async with self:
                self.invite_code_error = CODE_EMPTY
            return
        async with self:
            self.is_authenticating = True
            self.invite_code_error = ""
        try:
            email, business, is_add_business = await asyncio.to_thread(_invite_blocking, token)
        except SQLAlchemyError as exc:
            logger.error("invite code lookup failed: %s", type(exc).__name__)
            async with self:
                self.is_authenticating = False
                self.invite_code_error = ACCESS_DOWN
            return
        async with self:
            self.is_authenticating = False
            if not email:
                self.invite_code_error = CODE_DEAD
                return
            self._invite_token = token
            self.invite_email = email
            self._invite_email = email
            self.invite_business = business
            self.invite_is_add_business = is_add_business
            self._invite_add_business = is_add_business
            self.added_business_name = ""
            self.invite_state = "ok"
        if is_add_business and not to_signup:
            yield rx.redirect(SIGNUP_ROUTE)
        elif not to_signup:
            yield AuthState.start_brand_kit({"email": email})

    @rx.event(background=True)
    async def start_brand_kit(self, form_data: dict):
        """The Brand Kit's first view: provision (or resume) the draft tenant for this
        email, then into the wizard. The Brand Kit saves into it from the first step."""
        email = str(form_data.get("email", ""))
        async with self:
            self.is_authenticating = True
            self.guest_error = ""
            self.guest_has_account = False
            invite_token = self._invite_token  # backend-only: never leaves the server
        try:
            draft = await asyncio.to_thread(_start_draft_blocking, email, invite_token)
        except DraftEmailInvalid as exc:
            async with self:
                self.is_authenticating = False
                self.guest_error = exc.message
            return
        except EmailHasAccount:
            # § 2026-10-02: an email with an account has its Brand Kit behind the login
            async with self:
                self.is_authenticating = False
                self.guest_has_account = True
                self.login_email_hint = email.strip()
            yield rx.redirect("/login")
            return
        except SQLAlchemyError as exc:
            logger.error("brand kit draft failed: %s", type(exc).__name__)
            async with self:
                self.is_authenticating = False
                self.guest_error = _AUTH_DOWN
            return
        try:
            destination = await asyncio.to_thread(_draft_destination_blocking, draft.tenant_id)
        except SQLAlchemyError as exc:
            logger.warning("brand kit draft status unreadable: %s", type(exc).__name__)
            destination = "/brand"
        async with self:
            self.guest_tenant_id = str(draft.tenant_id)
            self.guest_email = draft.email
            self.is_authenticating = False
        yield rx.redirect(destination)

    @rx.event
    async def leave_brand_draft(self) -> rx.event.EventSpec:
        """ "Usar otro correo" on the Brand Kit's first view: forget the draft in this
        browser (it stays saved under its email) and ask for an email again."""
        await self._reset_brand_kit_states()
        self.guest_tenant_id = ""
        self.guest_email = ""
        return rx.redirect(BRAND_START_ROUTE)

    async def _reset_brand_kit_states(self) -> None:
        """Drop the Brand Kit's in-memory draft (cached brand id, wizard cursor, staged
        files) when the tenant behind it changes without a logout."""
        from .brand_answers import BrandAnswersState
        from .brand_documents import BrandDocumentState
        from .brand_kit_editor import BrandEditState
        from .brand_minimal import BrandMinimalState
        from .brand_proposal import BrandProposalState
        from .creative_state import CreativeState
        from .creative_wizard_pages import BrandConnectState, BrandWizardState
        from .voice_lab import VoiceLabState

        for state_cls in (
            CreativeState,
            # found by the A13 enumeration (2026-11-02): the answers path's drafts and
            # the kit editor's «Cancelar» snapshot are the draft brand's data too
            BrandAnswersState,
            BrandEditState,
            BrandWizardState,
            BrandConnectState,
            BrandMinimalState,
            BrandProposalState,
            BrandDocumentState,
            VoiceLabState,
        ):
            substate = await self.get_state(state_cls)
            substate.reset()

    @rx.event(background=True)
    async def handle_login(self, form_data: dict):
        # Surrounding whitespace only (phone keyboards append a space after an
        # autocompleted email). The `+alias` and the case stay literal — criterion 6.
        email = str(form_data.get("email", "")).strip()
        password = str(form_data.get("password", ""))
        async with self:
            self.is_authenticating = True
            self.auth_error = ""
            self.login_notice = ""
        # The attempt is reserved BEFORE the provider is called (check + count under one
        # lock), keyed case-insensitively: parallel guesses, or the same email in other
        # capitalisations, share the one window. Only a wrong password keeps the count.
        key = throttle_key(email)
        wait = login_throttle.try_acquire(key)
        if wait:
            async with self:
                self.is_authenticating = False
                self.auth_error = _wait_message(wait)
            return
        try:
            result = await asyncio.to_thread(_login_blocking, email, password)
        except InvalidCredentials:
            async with self:
                self.is_authenticating = False
                self.auth_error = _BAD_CREDENTIALS
            return
        except NoBusinessAccess as exc:
            # ADR 43 A15: right password, but no seat in any business any more. Its own
            # text (a subclass of IncompleteRegistration, so it must be caught first).
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except IncompleteRegistration:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _INCOMPLETE
            return
        except RateLimited:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _RATE_LIMITED
            return
        except (AuthProviderError, AuthNotConfigured, SQLAlchemyError) as exc:
            # Only the exception type is logged — same hygiene rule as every state.
            logger.error("login failed: %s", type(exc).__name__)
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return
        login_throttle.clear(key)
        # Only the in-app destinations below; never a URL from the form itself.
        next_route = str(form_data.get("next", self.login_return or "/"))
        yield rx.redirect(await self._open_session(result, next_route))

    async def _open_session(self, result: LoginResult, next_route: str) -> str:
        """Make a verified login this session's tenant; returns where to go. Shared by
        the login form and the password reset.

        ADR 43 (S3): a login with 2+ businesses does NOT get a `session_tenant_id` here.
        It is parked for the selector (`/elegir-negocio`), which opens the chosen one
        with `open_business`. A login with one business opens it straight away, as
        before."""
        destination = review_destination(next_route) or (
            next_route if next_route in _POST_LOGIN_ROUTES else "/"
        )
        # A password reset can complete inside a tab that is already in session (`/reset`
        # is not bounced), possibly for another login: nothing of that session — its
        # business, its login, its businesses' data — may survive into the new one.
        async with self:
            # Revoked only for ANOTHER login: the provider's sign-out is global, and a
            # reset of this same login already closed its older sessions.
            other_login = self._auth_user_id != str(result.auth_user_id)
            stale_token = self._access_token if self.session_tenant_id and other_login else ""
            if self.session_tenant_id:
                await self._reset_business_states()
                self.reset()
        if stale_token and stale_token != result.access_token:
            await asyncio.to_thread(_sign_out_blocking, stale_token)
        memberships = result.memberships
        if result.needs_business_choice:
            async with self:
                self._forget_business_choice()
                self.awaiting_business_choice = True
                self.business_names = [m.tenant_name for m in memberships]
                self._choice_ids = [str(m.tenant_id) for m in memberships]
                self._choice_next = destination
                self._auth_user_id = str(result.auth_user_id)
                self._access_token = result.access_token
                self.user_email = result.email
                self.is_authenticating = False
                self.show_password = False
            return CHOOSE_ROUTE

        kit_complete = await self._kit_complete(result.tenant_id)
        async with self:
            self._forget_business_choice()
            # Hand-built results (tests, older fakes) may carry no memberships.
            self.business_names = [m.tenant_name for m in memberships] or [result.display_name]
            self._choice_ids = [str(m.tenant_id) for m in memberships] or [str(result.tenant_id)]
            self._auth_user_id = str(result.auth_user_id)
            self._access_token = result.access_token
            await self._enter_business(
                tenant_id=str(result.tenant_id),
                business_name=result.display_name,
                email=result.email,
                user_id=str(result.user_id),
                kit_complete=kit_complete,
            )
        return destination

    async def _kit_complete(self, tenant_id: object) -> bool:
        try:
            return await asyncio.to_thread(_kit_complete_blocking, tenant_id)
        except SQLAlchemyError as exc:
            # A transient read failure must not lock the business out of its app: it
            # is treated as complete, and the next login checks again.
            logger.warning("brand kit status unreadable at login: %s", type(exc).__name__)
            return True

    async def _enter_business(
        self,
        *,
        tenant_id: str,
        business_name: str,
        email: str,
        user_id: str,
        kit_complete: bool,
    ) -> None:
        """THE one place `session_tenant_id` is written. Call inside `async with self`,
        with values that come from a verified `LoginResult` or from `open_business`."""
        if tenant_id != self.session_tenant_id:
            self.business_logo_src = ""
        self._logo_fetched_at = 0.0
        self.session_tenant_id = tenant_id
        self.business_name = business_name
        self.user_email = email
        self._session_user_id = user_id
        self.brand_kit_complete = kit_complete
        self.active_business_index = (
            self._choice_ids.index(tenant_id) if tenant_id in self._choice_ids else -1
        )
        self.awaiting_business_choice = False
        self.opening_business = ""
        self._choice_next = ""
        self.is_authenticating = False
        # A login supersedes the pre-login draft: after a signup that adopted it, the
        # session tenant IS the draft; after logging into another account, the draft
        # stays saved under its email and its in-memory state must not leak into that
        # account's Brand Kit.
        if self.guest_tenant_id and self.guest_tenant_id != self.session_tenant_id:
            await self._reset_brand_kit_states()
        self.guest_tenant_id = ""
        self.guest_email = ""
        self.login_email_hint = ""
        self.show_password = False

    # ----------------------------------------------------------------------------------
    # m-24976899: the business logo on the sidebar's top row
    # ----------------------------------------------------------------------------------

    @rx.event(background=True)
    async def refresh_business_logo(self):
        """The shell's mount (every page): mint the logo's path again when it belongs
        to another business, was marked stale, or is older than `LOGO_FRESH_SECONDS`
        (the `/r2media` token lives an hour). Cheap when fresh: nothing leaves the
        process."""
        await reload_business_logo(self)

    # ----------------------------------------------------------------------------------
    # ADR 43 S3: «¿Con qué negocio quieres trabajar?» (/elegir-negocio)
    # ----------------------------------------------------------------------------------

    @rx.event
    def enter_business_choice(self) -> rx.event.EventSpec | None:
        """`on_load` of the selector. A session goes on to the app; a browser with no
        login waiting for a choice (reload after leaving, a new tab) goes to /login."""
        if self.session_tenant_id:
            return rx.redirect("/")
        if not self.awaiting_business_choice or not self._choice_ids:
            self._login_notice = CHOICE_EXPIRED
            return rx.redirect("/login")
        self.auth_error = ""
        self.opening_business = ""
        return None

    @rx.event(background=True)
    async def choose_business(self, position: str):
        """One tap on a business of the selector. `position` is all the browser sends;
        the tenant behind it is the server's (`_choice_ids`), and the membership is
        checked again, without cache, before anything is opened (ADR 43 §2.1)."""
        async with self:
            if self.session_tenant_id or not self.awaiting_business_choice:
                return
            if self.opening_business:  # a second tap while the first one opens
                return
            index = parse_choice_index(position, len(self._choice_ids))
            if index is None:
                self.auth_error = "Elige uno de los negocios de la lista."
                return
            auth_user_id = self._auth_user_id
            tenant_id = self._choice_ids[index]
            self.opening_business = self.business_names[index]
            self.auth_error = ""
        try:
            active = await asyncio.to_thread(_open_business_blocking, auth_user_id, tenant_id)
        except NotAMember as exc:
            # The seat was removed between the login and the tap: start over (A15).
            async with self:
                self._forget_business_choice()
                self.user_email = ""
                self._login_notice = exc.message
            yield rx.redirect("/login")
            return
        except (SQLAlchemyError, ValueError) as exc:
            logger.error("business choice failed: %s", type(exc).__name__)
            async with self:
                self.opening_business = ""
                self.auth_error = _AUTH_DOWN
            return
        kit_complete = await self._kit_complete(active.tenant_id)
        async with self:
            if self.session_tenant_id or not self.awaiting_business_choice:
                return  # left the selector meanwhile (Salir, another login)
            destination = self._choice_next or "/"
            await self._enter_business(
                tenant_id=str(active.tenant_id),
                business_name=active.business_name,
                email=active.email,
                user_id=str(active.user_id),
                kit_complete=kit_complete,
            )
        yield rx.redirect(destination)

    @rx.event(background=True)
    async def leave_business_choice(self):
        """«Salir» on the selector: the same as a logout (revoke, forget), then /login."""
        async with self:
            token = self._access_token
        if token:
            await asyncio.to_thread(_sign_out_blocking, token)
        async with self:
            await self._reset_business_states()
            self.reset()
        yield rx.call_script(FORGET_TITLE_BUSINESS_JS)
        yield rx.redirect("/login")

    # ----------------------------------------------------------------------------------
    # ADR 43 S4: «Cambiar de negocio» from the header — a NEW Reflex state per business
    # ----------------------------------------------------------------------------------

    @rx.event(background=True)
    async def switch_business(self, position: str):
        """Step 1 of ADR 43 §2.2. Verify the membership fresh, mint a single-use pass
        and hand the browser the script that drops this tab's Reflex token and opens
        `/cambiar#pase=…`. Any refusal leaves the current business exactly as it was."""
        async with self:
            if not self.session_tenant_id or self.opening_business:
                return
            index = parse_choice_index(position, len(self._choice_ids))
            if index is None or index == self.active_business_index:
                return
            auth_user_id = self._auth_user_id
            tenant_id = self._choice_ids[index]
            access_token = self._access_token
            current = self.business_name
            outgoing_tenant_id = self.session_tenant_id
            self.opening_business = self.business_names[index]
        if not auth_user_id:
            async with self:
                self.opening_business = ""
            yield rx.toast.error(SWITCH_DOWN.format(business=current))
            return
        try:
            await asyncio.to_thread(_open_business_blocking, auth_user_id, tenant_id)
            # The outgoing Reflex state is kept intact during a tab switch.
            # Invalidate its pending Pinterest consent before a new state is opened.
            from .pinterest_provider import cancel_pending

            await asyncio.to_thread(cancel_pending, UUID(outgoing_tenant_id), auth_user_id)
            pass_value = await asyncio.to_thread(
                issue_switch_pass, UUID(auth_user_id), UUID(tenant_id), access_token
            )
        except NotAMember:
            # The current session stays; the list is read again so the business that
            # is no longer reachable leaves the menu. Not the signed «Vuelve a entrar…»
            # text: the owner is still in, and must not log out to fix anything.
            await self._refresh_businesses(auth_user_id)
            async with self:
                target = self.opening_business
                self.opening_business = ""
            yield rx.toast.error(SWITCH_NO_ACCESS.format(target=target, business=current))
            return
        except (SQLAlchemyError, ValueError, *_SWITCH_STORE_ERRORS) as exc:
            logger.error("business switch failed: %s", type(exc).__name__)
            async with self:
                self.opening_business = ""
            yield rx.toast.error(SWITCH_DOWN.format(business=current))
            return
        # `opening_business` stays set: the chip says «Abriendo {negocio}…» until the
        # browser leaves this page. Nothing else of this state is touched — it is
        # abandoned, and «Duplicar pestaña» may still be using it (ADR 43 §2.3).
        yield rx.call_script(switch_script(pass_value))

    async def _refresh_businesses(self, auth_user_id: str) -> None:
        try:
            rows = await asyncio.to_thread(_memberships_blocking, auth_user_id)
        except SQLAlchemyError as exc:
            logger.warning("memberships unreadable: %s", type(exc).__name__)
            return
        async with self:
            ids = [tenant for tenant, _name in rows]
            if self.session_tenant_id and self.session_tenant_id not in ids:
                return  # S5 decides what happens to a session whose own seat is gone
            self._choice_ids = ids
            self.business_names = [name for _tenant, name in rows]
            self.active_business_index = (
                ids.index(self.session_tenant_id) if self.session_tenant_id in ids else -1
            )

    @rx.event
    def enter_switch(self) -> rx.event.EventSpec:
        """`on_load` of /cambiar. The pass is in the URL FRAGMENT, which never reaches a
        server, so the page reads it in the browser and hands it to the redemption."""
        self.auth_error = ""
        return rx.call_script("window.location.hash", callback=AuthState.redeem_switch)

    @rx.event(background=True)
    async def redeem_switch(self, fragment: str):
        """Step 3 of ADR 43 §2.2, in the NEW state the browser opened without a token:
        redeem the pass once, check the membership fresh again, open that business."""
        from .business_switch import switch_destination

        pass_value = pass_from_fragment(fragment)
        destination = switch_destination(fragment)
        # The pass must not linger in the address bar, the history or a shared URL.
        yield rx.call_script("history.replaceState(null, '', window.location.pathname)")
        target = None
        if pass_value:
            try:
                target = await asyncio.to_thread(redeem_switch_pass, pass_value)
            except _SWITCH_STORE_ERRORS as exc:
                logger.error("switch pass unreadable: %s", type(exc).__name__)
        if target is None:
            async with self:
                in_session = bool(self.session_tenant_id)
                if not in_session:
                    self._login_notice = SWITCH_PASS_DEAD
            # «Atrás» onto /cambiar from the business it opened: nothing to redeem, the
            # session is already there — back to it, without an error.
            yield rx.redirect("/" if in_session else "/login")
            return
        auth_user_id, tenant_id = str(target.auth_user_id), str(target.tenant_id)
        try:
            active = await asyncio.to_thread(_open_business_blocking, auth_user_id, tenant_id)
            rows = await asyncio.to_thread(_memberships_blocking, auth_user_id)
        except NotAMember as exc:
            async with self:
                self._login_notice = exc.message
            yield rx.redirect("/login")
            return
        except (SQLAlchemyError, ValueError) as exc:
            logger.error("switch redemption failed: %s", type(exc).__name__)
            async with self:
                self._login_notice = _AUTH_DOWN
            yield rx.redirect("/login")
            return
        kit_complete = await self._kit_complete(active.tenant_id)
        async with self:
            # Defence in depth: the browser dropped its token, so this IS a new state.
            # Should it ever not be (a client that kept the token), nothing of whatever
            # this state held survives into the business being opened.
            if self.session_tenant_id or self._auth_user_id or self.guest_tenant_id:
                await self._reset_business_states()
                self.reset()
            self._auth_user_id = auth_user_id
            self._access_token = target.access_token
            self._choice_ids = [tenant for tenant, _name in rows]
            self.business_names = [name for _tenant, name in rows]
            await self._enter_business(
                tenant_id=str(active.tenant_id),
                business_name=active.business_name,
                email=active.email,
                user_id=str(active.user_id),
                kit_complete=kit_complete,
            )
        yield rx.redirect(destination)

    @rx.event(background=True)
    async def open_pinterest_connections(self, request_id: str):
        """Open the SAME business in a new tab using the existing one-use switch pass."""
        from .business_switch import connections_tab_script

        if not request_id:
            yield rx.toast.error("Permite abrir otra pestaña para conectar Pinterest en Tus redes.")
            return
        try:
            UUID(request_id)
        except (ValueError, TypeError, AttributeError):
            return
        async with self:
            tenant_id, user_id, token = (
                self.session_tenant_id,
                self._auth_user_id,
                self._access_token,
            )
        try:
            if not tenant_id or not user_id or not token:
                raise ValueError("missing actor")
            await asyncio.to_thread(_open_business_blocking, user_id, tenant_id)
            pass_value = await asyncio.to_thread(
                issue_switch_pass, UUID(user_id), UUID(tenant_id), token
            )
            async with self:
                if (tenant_id, user_id, token) != (
                    self.session_tenant_id,
                    self._auth_user_id,
                    self._access_token,
                ):
                    raise ValueError("changed actor")
        except (NotAMember, SQLAlchemyError, ValueError, *_SWITCH_STORE_ERRORS):
            yield rx.call_script(connections_tab_script(request_id))
            yield rx.toast.error("No pudimos abrir Tus redes. Vuelve a intentarlo.")
            return
        yield rx.call_script(connections_tab_script(request_id, pass_value))

    async def _reset_business_states(self) -> None:
        """Reset every business substate (`business_state_classes`). Inside `async with
        self`."""
        # Consent opened before logout/switch must not complete for the old business.
        try:
            from .pinterest_provider import cancel_pending
            from .tenant import tenant_uuid

            old_tenant = tenant_uuid(getattr(self, "session_tenant_id", ""))
            if old_tenant is not None:
                await asyncio.to_thread(
                    cancel_pending, old_tenant, getattr(self, "_auth_user_id", "")
                )
        except Exception as exc:  # noqa: BLE001 — logout still clears every state
            logger.warning("pinterest consent cancellation failed: %s", type(exc).__name__)
        for state_cls in business_state_classes():
            substate = await self.get_state(state_cls)
            # A state that parks files outside itself (the «Formas de pago» QR) deletes
            # them first: `reset` only clears the fields that point at them.
            discard = getattr(substate, "_discard_files", None)
            if callable(discard):
                try:
                    discard()
                except Exception as exc:  # noqa: BLE001 — never skip the other resets
                    logger.warning(
                        "discard files failed state=%s error=%s",
                        state_cls.__name__,
                        type(exc).__name__,
                    )
            substate.reset()

    @rx.event(background=True)
    async def handle_signup(self, form_data: dict):
        """Register a business — a fresh `tenant_id` is assigned automatically — then
        sign straight in as it (founder ruling 2026-08-18)."""
        if self._invite_add_business:
            async for event in self._handle_add_business(str(form_data.get("password", ""))):
                yield event
            return
        business_name = str(form_data.get("business_name", ""))
        email = str(form_data.get("email", ""))
        password = str(form_data.get("password", ""))
        # m-24842967: the owner picks only the country; zone and currency follow it
        # (Venezuela → dollars, decision 10) and are changed later in Configuración.
        try:
            locale = resolve_locale(str(form_data.get("country", "")))
        except LocaleInvalid as exc:
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        country, timezone, currency = locale.country, locale.timezone, locale.currency
        async with self:
            self.is_authenticating = True
            self.auth_error = ""
            invite_token = self._invite_token
        try:
            await asyncio.to_thread(
                _signup_blocking,
                business_name,
                email,
                password,
                country,
                timezone,
                currency,
                invite_token,
            )
        except SignupNotAllowed as exc:
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except RegistrationInvalid as exc:
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except RateLimited:
            async with self:
                self.is_authenticating = False
                self.auth_error = _RATE_LIMITED
            return
        except (AuthProviderError, AuthNotConfigured, SQLAlchemyError) as exc:
            logger.error("signup failed: %s", type(exc).__name__)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return

        # Auto sign-in with the same credentials the operator just chose. A signup that
        # adopted the pre-login Brand Kit (same email, § 2026-10-02) opens on «Tu marca
        # está lista» (m-24842965), the same end a logged-in finish has.
        async with self:
            self._invite_token = ""
            self.invite_state = ""
            self.invite_email = ""
            self._invite_email = ""
            self.invite_business = ""
            # Literal comparison (criterion 6): the field comes prefilled with it.
            adopted = bool(self.guest_email) and self.guest_email == email
        credentials = {
            "email": email,
            "password": password,
            "next": BRAND_READY_ROUTE if adopted else "/",
        }
        async for event in AuthState.handle_login.fn(self, credentials):
            yield event

    async def _handle_add_business(self, password: str) -> AsyncIterator[rx.event.EventSpec]:
        """Confirm the current password without changing an existing session's tenant."""
        async with self:
            if self.is_authenticating or self.added_business_name:
                return
            self.is_authenticating = True
            self.auth_error = ""
            token = self._invite_token
            access_token = self._access_token
            has_session = bool(self.session_tenant_id)
            key = throttle_key(self._invite_email)
        wait = login_throttle.try_acquire(key)
        if wait:
            async with self:
                self.is_authenticating = False
                self.auth_error = _wait_message(wait)
            return
        try:
            registered, login = await asyncio.to_thread(
                _add_business_blocking, password, token, access_token, has_session
            )
        except (SignupNotAllowed, RegistrationInvalid) as exc:
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except RateLimited:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _RATE_LIMITED
            return
        except IncompleteRegistration:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _INCOMPLETE
            return
        except (AuthProviderError, AuthNotConfigured, SQLAlchemyError) as exc:
            logger.error("add business failed: %s", type(exc).__name__)
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return
        login_throttle.clear(key)
        if login is not None:
            # ADR 43 S3: a login that already had 2+ businesses is parked for the
            # selector (no session yet); «Continuar» then leads there
            # (`added_business_next`).
            await self._open_session(login, "/")
        # The login was resolved before the new business existed: read its businesses
        # again so the selector and «Cambiar de negocio» offer the one just added.
        async with self:
            auth_user_id = self._auth_user_id
        if auth_user_id:
            await self._refresh_businesses(auth_user_id)
        async with self:
            self.is_authenticating = False
            self.added_business_name = registered.business_name
            self._invite_token = ""
            self.invite_state = ""
            self.invite_email = ""
            self._invite_email = ""
            self.invite_business = ""
            self.invite_is_add_business = False
            self._invite_add_business = False
            self.show_password = False
        yield rx.call_script("document.getElementById('q-add-business-form')?.reset()")

    # ----------------------------------------------------------------------------------
    # Forgotten password (2026-10-06): /forgot asks for the email, the provider mails a
    # link to /reset, /reset sets the new password and signs in.
    # ----------------------------------------------------------------------------------

    @rx.event(background=True)
    async def request_reset(self, form_data: dict):
        email = str(form_data.get("email", "")).strip()
        async with self:
            self.is_authenticating = True
            self.auth_error = ""
            self.reset_sent_to = ""
        if not _email_looks_valid(email):
            async with self:
                self.is_authenticating = False
                self.auth_error = "Escribe un correo válido."
            return
        if reset_request_throttle.retry_after(throttle_key(email)):
            # Already sent one a moment ago: the screen says the same as a fresh send.
            async with self:
                self.is_authenticating = False
                self.reset_sent_to = email
            return
        try:
            await asyncio.to_thread(_request_reset_blocking, email)
        except RateLimited:
            async with self:
                self.is_authenticating = False
                self.auth_error = (
                    "Enviamos demasiados correos en poco tiempo. Espera unos minutos y "
                    "vuelve a intentarlo."
                )
            return
        except (AuthProviderError, AuthNotConfigured) as exc:
            logger.error("password reset request failed: %s", type(exc).__name__)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return
        reset_request_throttle.note(throttle_key(email))
        async with self:
            self.is_authenticating = False
            self.reset_sent_to = email

    @rx.event
    def enter_reset(self) -> rx.event.EventSpec:
        """`on_load` of /reset. The provider puts the recovery token in the URL
        FRAGMENT (`#access_token=…&type=recovery`), which never reaches a server — so
        the page reads it in the browser and hands it to `receive_recovery_link`."""
        self.auth_error = ""
        self.show_password = False
        self.reset_link_state = "checking"
        return rx.call_script("window.location.hash", callback=AuthState.receive_recovery_link)

    @rx.event
    def receive_recovery_link(self, fragment: str) -> rx.event.EventSpec:
        params = parse_qs(str(fragment or "").lstrip("#"))
        token = (params.get("access_token") or [""])[0]
        if token and (params.get("type") or [""])[0] == "recovery":
            self._recovery_token = token
            self.reset_link_state = "ready"
        elif params.get("error") or params.get("error_code"):
            self._recovery_token = ""
            self.reset_link_state = "invalid"
            self.auth_error = _RESET_LINK_DEAD
        elif self._recovery_token:
            self.reset_link_state = "ready"  # a reload of /reset after the hash was wiped
        else:
            self.reset_link_state = "invalid"
            self.auth_error = _RESET_LINK_MISSING
        # The token must not linger in the address bar, the history or a shared URL.
        return rx.call_script("history.replaceState(null, '', window.location.pathname)")

    @rx.event(background=True)
    async def submit_new_password(self, form_data: dict):
        password = str(form_data.get("password", ""))
        confirm = str(form_data.get("confirm", ""))
        async with self:
            token = self._recovery_token
            self.is_authenticating = True
            self.auth_error = ""
        if not token:
            async with self:
                self.is_authenticating = False
                self.reset_link_state = "invalid"
                self.auth_error = _RESET_LINK_MISSING
            return
        try:
            result = await asyncio.to_thread(_complete_reset_blocking, token, password, confirm)
        except (PasswordChangeInvalid, PasswordRejected) as exc:
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except SessionExpired:
            async with self:
                self._recovery_token = ""
                self.is_authenticating = False
                self.reset_link_state = "invalid"
                self.auth_error = _RESET_LINK_DEAD
            return
        except RateLimited:
            async with self:
                self.is_authenticating = False
                self.auth_error = _RATE_LIMITED
            return
        except NoBusinessAccess as exc:
            # The password IS changed; the login has no business left to open.
            async with self:
                self._recovery_token = ""
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except IncompleteRegistration:
            # The password IS changed; only the account's local half is missing.
            async with self:
                self._recovery_token = ""
                self.is_authenticating = False
                self.auth_error = _INCOMPLETE
            return
        except (
            InvalidCredentials,
            AuthProviderError,
            AuthNotConfigured,
            SQLAlchemyError,
        ) as exc:
            logger.error("password reset failed: %s", type(exc).__name__)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return
        async with self:
            self._recovery_token = ""
        login_throttle.clear(throttle_key(result.email))
        yield rx.redirect(await self._open_session(result, "/"))
        yield rx.toast.success("Listo: tu contraseña quedó cambiada.")

    # ----------------------------------------------------------------------------------
    # Change password while logged in (/settings)
    # ----------------------------------------------------------------------------------

    @rx.event
    def enter_settings(self) -> None:
        self.auth_error = ""
        self.show_password = False
        self.password_saved = False

    @rx.event(background=True)
    async def submit_password_change(self, form_data: dict):
        current = str(form_data.get("current_password", ""))
        new = str(form_data.get("password", ""))
        confirm = str(form_data.get("confirm", ""))
        async with self:
            email = self.user_email
            self.is_authenticating = True
            self.auth_error = ""
            self.password_saved = False
        if not email:
            async with self:
                self.is_authenticating = False
                self.auth_error = _SESSION_STALE
            return
        # Same reservation as the login: the current password is a guess until the
        # provider says otherwise; every other outcome gives the attempt back.
        key = throttle_key(email)
        wait = login_throttle.try_acquire(key)
        if wait:
            async with self:
                self.is_authenticating = False
                self.auth_error = _wait_message(wait)
            return
        try:
            token = await asyncio.to_thread(_change_password_blocking, email, current, new, confirm)
        except InvalidCredentials:
            async with self:
                self.is_authenticating = False
                self.auth_error = "La contraseña actual no es correcta."
            return
        except (PasswordChangeInvalid, PasswordRejected) as exc:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except SessionExpired:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _SESSION_STALE
            return
        except RateLimited:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _RATE_LIMITED
            return
        except (AuthProviderError, AuthNotConfigured) as exc:
            logger.error("password change failed: %s", type(exc).__name__)
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return
        login_throttle.clear(key)
        async with self:
            self._access_token = token
            self.is_authenticating = False
            self.show_password = False
            self.password_saved = True
        yield rx.call_script("document.getElementById('q-password-form')?.reset()")
        yield rx.toast.success("Contraseña actualizada.")

    @rx.event(background=True)
    async def logout(self):
        """Hygiene criterion 1: revoke server-side, destroy state, reload to /login."""
        async with self:
            token = self._access_token
        if token:
            # Best-effort by provider contract: a dead IdP must not block logout.
            await asyncio.to_thread(_sign_out_blocking, token)
        async with self:
            # Destroy every business substate so no stale tenant data survives into
            # the next login on this browser (`business_state_classes`).
            await self._reset_business_states()
            self.reset()
        # A toast still on screen (e.g. a sync result) must not follow the person out.
        yield rx.toast.dismiss()
        # The redirect is a client-side navigation: the tab title script keeps the
        # business name in the document, and it must not title the next screens.
        yield rx.call_script(FORGET_TITLE_BUSINESS_JS)
        # § 2026-10-02: the first view after a logout is the Brand Kit, as on arrival
        yield rx.redirect(BRAND_START_ROUTE)
