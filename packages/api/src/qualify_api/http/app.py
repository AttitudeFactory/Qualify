"""FastAPI application factory.

A factory rather than a module-level `app`: a module-level instance is built at import
time, which forces every test that imports anything nearby to construct real settings and
real clients. `create_app()` lets the tests build an app with faked dependencies and
nothing else.

The real wiring lives in `connections.composition` — HTTP is not the only caller (the
Reflex CRM calls the same services in-process, without an HTTP hop), so the assembly must
not be owned by the HTTP layer. `build_production_service` stays here as the name the
routes bind to.
"""

from __future__ import annotations

from fastapi import FastAPI

from qualify_api.connections.composition import production_connect_service
from qualify_api.connections.service import ConnectService
from qualify_api.creative.service import ContentService
from qualify_api.http import (
    access_log,
    connections_routes,
    creative_routes,
    deps,
    inbox_routes,
    leads_routes,
    meegle_routes,
    mentions_routes,
    public_media_routes,
    publishing_routes,
    replies_routes,
    sentiment_routes,
    whatsapp_routes,
)
from qualify_api.http.inbox_routes import SyncComments
from qualify_api.http.replies_routes import (
    DecideDraft,
    GenerateDrafts,
    ListPendingDrafts,
    SendDraft,
)
from qualify_api.http.sentiment_routes import AnalyzePendingComments
from qualify_api.leads.interest import AccessInterestService
from qualify_api.leads.service import LeadIntakeService
from qualify_api.mail import routes as mail_routes
from qualify_api.publishing.media_token import MediaTokenStore
from qualify_api.publishing.service import PublishService
from qualify_api.publishing.staging import MediaStagingService


def build_production_service() -> ConnectService:
    """The route dependency. Assembly (and its cache) belongs to `composition`."""
    return production_connect_service()


def build_production_publish_service() -> PublishService:
    """Lazy on purpose: constructing it needs the R2 env, and an app booted without R2
    should fail the PUBLISHING request loudly, not the whole boot."""
    from qualify_api.publishing.composition import production_publish_service  # noqa: PLC0415

    return production_publish_service()


def build_production_staging_service() -> MediaStagingService:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return MediaStagingService(ObjectGate(R2ObjectStore(R2Settings.from_env())))


def build_production_media_token_store() -> MediaTokenStore:
    """QUA-68 — same cached factory `PublishService` itself uses
    (`publishing.composition.production_media_token_store`), reused here rather than
    duplicated so the HTTP route and the Reflex-facing service share one Redis pool."""
    from qualify_api.publishing.composition import production_media_token_store  # noqa: PLC0415

    return production_media_token_store()


def build_production_public_media_gate():  # noqa: ANN201 — see module note below
    """Lazy on purpose, like `build_production_staging_service`: constructing it needs the
    R2 env, and an app booted without it should fail the first `/public/media/*` request
    loudly, not the whole boot."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return ObjectGate(R2ObjectStore(R2Settings.from_env()))


def build_production_inbox_sync() -> SyncComments:
    """Lazy on purpose: constructing credentials needs the Meta env, same reason
    `build_production_publish_service` defers its import."""
    from qualify_api.inbox.composition import sync_comments  # noqa: PLC0415

    return sync_comments


def build_production_analyze_pending_comments() -> AnalyzePendingComments:
    """Lazy import like `build_production_inbox_sync`: keeps importing this module
    from requiring the sentiment stack (transformers) unless the route is actually
    exercised."""
    from qualify_api.sentiment.composition import analyze_pending_comments  # noqa: PLC0415

    return analyze_pending_comments


def build_production_mentions_settings() -> mentions_routes.MentionsWebhookSettings:
    """Not lazy, unlike the publish/inbox/creative builders above: reading env vars
    has no heavy import and no external dependency to fail on, so there is nothing
    here worth deferring past app boot."""
    return mentions_routes.MentionsWebhookSettings.from_env()


def build_production_delivery_recorder() -> mentions_routes.DeliveryRecorder:
    """The INSERT-only intake recorder (QUA-147). Resolution, Graph enrichment and
    persistence of the mention run later in `qualify_api.webhooks.processor`, never in
    the request."""
    from qualify_api.webhooks.receiver import record_delivery  # noqa: PLC0415

    return record_delivery


def build_production_list_mentions() -> mentions_routes.ListMentions:
    from qualify_api.mentions.composition import list_mentions_for_tenant  # noqa: PLC0415

    return list_mentions_for_tenant


def build_production_analyze_mention_sentiment() -> mentions_routes.AnalyzeMentionSentiment:
    """Lazy import: keeps `qualify_models` (the `ml` group) out of this route's import
    graph unless the trigger is actually exercised, same reasoning
    `build_production_analyze_pending_comments` gives for the comments analogue."""
    from qualify_api.mentions.composition import analyze_pending_mentions  # noqa: PLC0415

    return analyze_pending_mentions


def build_production_meegle_event_settings() -> meegle_routes.MeegleEventSettings:
    """Env read only (plugin id + callback token). Raises `MeegleNotConfigured` on the
    first event when the engine is off — a loud 500, never an accepted unverified event."""
    return meegle_routes.MeegleEventSettings.from_env()


def build_production_meegle_delivery_recorder() -> meegle_routes.MeegleDeliveryRecorder:
    """The same INSERT-only intake door as the Meta webhooks, with the Meegle parser."""
    from qualify_api.meegle.receiver import record_meegle_delivery  # noqa: PLC0415

    return record_meegle_delivery


def build_production_resend_delivery_recorder() -> mail_routes.ResendDeliveryRecorder:
    """The same INSERT-only intake door as the Meta and Meegle webhooks, with the Resend
    parser (M2). The settings builder lives next to the route: an unset secret is a 503."""
    from qualify_api.mail.webhook import record_resend_delivery  # noqa: PLC0415

    return record_resend_delivery


def build_production_whatsapp_settings() -> whatsapp_routes.WhatsAppWebhookSettings:
    """Env read only, not lazy — same reasoning as `build_production_mentions_settings`."""
    return whatsapp_routes.WhatsAppWebhookSettings.from_env()


def build_production_whatsapp_chat_service() -> whatsapp_routes.ChatService:
    """WA-10. Lazy like the publishing builders; the service holds no connection of its
    own (each call opens `tenant_session`), so building it per request is cheap."""
    from qualify_api.whatsapp.chats import production_chat_service  # noqa: PLC0415

    return production_chat_service()


def build_production_whatsapp_media_locator() -> whatsapp_routes.MediaLocator:
    """0061: download-on-first-request into R2, served through the public-media token.
    Lazy like `build_production_public_media_gate`: it needs the R2, Redis, public base URL
    and Meta env, and an app booted without them should fail the media request loudly,
    not the whole boot."""
    from qualify_api.whatsapp.media import production_media_locator  # noqa: PLC0415

    return production_media_locator()


def build_production_whatsapp_metrics_service() -> whatsapp_routes.ConversationMetricsService:
    """WA-17. Lazy like the chat service; per-call `tenant_session`, cheap to build."""
    from qualify_api.whatsapp.metrics import production_metrics_service  # noqa: PLC0415

    return production_metrics_service()


def build_production_whatsapp_qr_prefix_source() -> whatsapp_routes.QrPrefixSource:
    """WA-17: QR codes listed through the resolver-built client; Meta settings are read
    only when a metrics request actually arrives."""
    from qualify_api.whatsapp.metrics import production_qr_prefix_source  # noqa: PLC0415

    return production_qr_prefix_source()


def build_production_whatsapp_analytics_service() -> whatsapp_routes.WabaAnalyticsService:
    """WA-21. Lazy for the same reason as the QR source: Meta settings at request time."""
    from qualify_api.whatsapp.analytics import production_analytics_service  # noqa: PLC0415

    return production_analytics_service()


def build_production_leads_service() -> LeadIntakeService:
    """Lazy import like the publishing builders: the leads module needs Redis only at
    the first intake, and an app booted without one should fail THAT request loudly."""
    from qualify_api.leads.composition import production_leads_service  # noqa: PLC0415

    return production_leads_service()


def build_production_interest_service() -> AccessInterestService:
    """MARCA-5: the house tenant's interest form, lazy for the same Redis reason."""
    from qualify_api.leads.composition import production_interest_service  # noqa: PLC0415

    return production_interest_service()


def build_production_generate_drafts() -> GenerateDrafts:
    """Lazy import like `build_production_analyze_pending_comments`: keeps
    `qualify_models` (the `ml` group) out of this route's import graph unless the
    trigger is actually exercised."""
    from qualify_api.replies.composition import generate_drafts  # noqa: PLC0415

    return generate_drafts


def build_production_list_pending_drafts() -> ListPendingDrafts:
    from qualify_api.replies.composition import list_pending_drafts  # noqa: PLC0415

    return list_pending_drafts


def build_production_decide_draft() -> DecideDraft:
    from qualify_api.replies.composition import decide_draft  # noqa: PLC0415

    return decide_draft


def build_production_send_draft() -> SendDraft:
    """Lazy import like `build_production_inbox_sync`: resolving credentials needs the
    Meta env, and an app booted without it should fail the SEND request loudly, not
    the whole boot."""
    from qualify_api.replies.composition import send_draft  # noqa: PLC0415

    return send_draft


def build_production_content_service() -> ContentService:
    """Lazy on purpose, like the publishing builders: composing the creative service
    builds the real Anthropic router, and an app booted without the creative env should
    fail the CREATIVE request loudly, not the whole boot."""
    from qualify_api.creative.composition import production_content_service  # noqa: PLC0415

    return production_content_service()


def build_production_draft_image_reader() -> creative_routes.DraftImageReader:
    return creative_routes.read_draft_image


def build_production_approved_creative_reader() -> creative_routes.ApprovedCreativeReader:
    from qualify_api.creative.read import approved_creative  # noqa: PLC0415

    return approved_creative


def create_app(*, configure_production: bool = True) -> FastAPI:
    # QUA-68: attached unconditionally (not gated on `configure_production`) — a token must
    # never reach an access log in ANY mode, tests included, and the filter is a no-op
    # until uvicorn's own protocol layer actually emits an access-log record (which never
    # happens for the in-process ASGI transport tests in this suite use).
    access_log.configure_access_log_redaction()
    app = FastAPI(title="Qualify API", version="0.1.0")
    app.include_router(connections_routes.router)
    app.include_router(publishing_routes.router)
    app.include_router(public_media_routes.router)
    app.include_router(inbox_routes.router)
    app.include_router(leads_routes.router)
    app.include_router(creative_routes.router)
    app.include_router(sentiment_routes.router)
    app.include_router(mentions_routes.router)
    app.include_router(replies_routes.router)
    app.include_router(whatsapp_routes.router)
    app.include_router(meegle_routes.router)
    app.include_router(mail_routes.router)
    if configure_production:
        app.dependency_overrides[connections_routes.get_connect_service] = build_production_service
        app.dependency_overrides[publishing_routes.get_publish_service] = (
            build_production_publish_service
        )
        app.dependency_overrides[publishing_routes.get_staging_service] = (
            build_production_staging_service
        )
        app.dependency_overrides[public_media_routes.get_media_token_store] = (
            build_production_media_token_store
        )
        app.dependency_overrides[public_media_routes.get_public_media_gate] = (
            build_production_public_media_gate
        )
        app.dependency_overrides[inbox_routes.get_sync_comments] = build_production_inbox_sync
        app.dependency_overrides[sentiment_routes.get_analyze_pending_comments] = (
            build_production_analyze_pending_comments
        )
        app.dependency_overrides[leads_routes.get_leads_service] = build_production_leads_service
        app.dependency_overrides[leads_routes.get_interest_service] = (
            build_production_interest_service
        )
        app.dependency_overrides[mentions_routes.get_webhook_settings] = (
            build_production_mentions_settings
        )
        app.dependency_overrides[mentions_routes.get_delivery_recorder] = (
            build_production_delivery_recorder
        )
        app.dependency_overrides[mentions_routes.get_list_mentions] = build_production_list_mentions
        app.dependency_overrides[mentions_routes.get_analyze_mention_sentiment] = (
            build_production_analyze_mention_sentiment
        )
        app.dependency_overrides[replies_routes.get_generate_drafts] = (
            build_production_generate_drafts
        )
        app.dependency_overrides[replies_routes.get_list_pending_drafts] = (
            build_production_list_pending_drafts
        )
        app.dependency_overrides[replies_routes.get_decide_draft] = build_production_decide_draft
        app.dependency_overrides[replies_routes.get_send_draft] = build_production_send_draft
        app.dependency_overrides[creative_routes.get_content_service] = (
            build_production_content_service
        )
        app.dependency_overrides[creative_routes.get_draft_image_reader] = (
            build_production_draft_image_reader
        )
        app.dependency_overrides[creative_routes.get_approved_creative_reader] = (
            build_production_approved_creative_reader
        )
        app.dependency_overrides[whatsapp_routes.get_webhook_settings] = (
            build_production_whatsapp_settings
        )
        # The WhatsApp webhook records into the SAME intake log as the mentions one
        # (QUA-147): one recorder, one queue, one worker for every Meta product.
        app.dependency_overrides[whatsapp_routes.get_delivery_recorder] = (
            build_production_delivery_recorder
        )
        app.dependency_overrides[whatsapp_routes.get_chat_service] = (
            build_production_whatsapp_chat_service
        )
        app.dependency_overrides[whatsapp_routes.get_media_locator] = (
            build_production_whatsapp_media_locator
        )
        app.dependency_overrides[whatsapp_routes.get_metrics_service] = (
            build_production_whatsapp_metrics_service
        )
        app.dependency_overrides[whatsapp_routes.get_qr_prefix_source] = (
            build_production_whatsapp_qr_prefix_source
        )
        app.dependency_overrides[whatsapp_routes.get_analytics_service] = (
            build_production_whatsapp_analytics_service
        )
        app.dependency_overrides[meegle_routes.get_event_settings] = (
            build_production_meegle_event_settings
        )
        app.dependency_overrides[meegle_routes.get_delivery_recorder] = (
            build_production_meegle_delivery_recorder
        )
        app.dependency_overrides[mail_routes.get_webhook_settings] = (
            mail_routes.build_production_resend_webhook_settings
        )
        app.dependency_overrides[mail_routes.get_delivery_recorder] = (
            build_production_resend_delivery_recorder
        )
        # C1: parsed at assembly so a malformed QUALIFY_DEV_PRINCIPALS fails the boot,
        # not the first request.
        app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
    return app
