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
    connections_routes,
    creative_routes,
    deps,
    inbox_routes,
    leads_routes,
    publishing_routes,
)
from qualify_api.http.inbox_routes import SyncComments
from qualify_api.leads.service import LeadIntakeService
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


def build_production_inbox_sync() -> SyncComments:
    """Lazy on purpose: constructing credentials needs the Meta env, same reason
    `build_production_publish_service` defers its import."""
    from qualify_api.inbox.composition import sync_comments  # noqa: PLC0415

    return sync_comments


def build_production_leads_service() -> LeadIntakeService:
    """Lazy import like the publishing builders: the leads module needs Redis only at
    the first intake, and an app booted without one should fail THAT request loudly."""
    from qualify_api.leads.composition import production_leads_service  # noqa: PLC0415

    return production_leads_service()


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
    app = FastAPI(title="Qualify API", version="0.1.0")
    app.include_router(connections_routes.router)
    app.include_router(publishing_routes.router)
    app.include_router(inbox_routes.router)
    app.include_router(leads_routes.router)
    app.include_router(creative_routes.router)
    if configure_production:
        app.dependency_overrides[connections_routes.get_connect_service] = build_production_service
        app.dependency_overrides[publishing_routes.get_publish_service] = (
            build_production_publish_service
        )
        app.dependency_overrides[publishing_routes.get_staging_service] = (
            build_production_staging_service
        )
        app.dependency_overrides[inbox_routes.get_sync_comments] = build_production_inbox_sync
        app.dependency_overrides[leads_routes.get_leads_service] = build_production_leads_service
        app.dependency_overrides[creative_routes.get_content_service] = (
            build_production_content_service
        )
        app.dependency_overrides[creative_routes.get_draft_image_reader] = (
            build_production_draft_image_reader
        )
        app.dependency_overrides[creative_routes.get_approved_creative_reader] = (
            build_production_approved_creative_reader
        )
        # C1: parsed at assembly so a malformed QUALIFY_DEV_PRINCIPALS fails the boot,
        # not the first request.
        app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
    return app
