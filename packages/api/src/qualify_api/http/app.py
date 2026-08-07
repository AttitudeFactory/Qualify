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
from qualify_api.http import connections_routes, deps


def build_production_service() -> ConnectService:
    """The route dependency. Assembly (and its cache) belongs to `composition`."""
    return production_connect_service()


def create_app(*, configure_production: bool = True) -> FastAPI:
    app = FastAPI(title="Qualify API", version="0.1.0")
    app.include_router(connections_routes.router)
    if configure_production:
        app.dependency_overrides[connections_routes.get_connect_service] = build_production_service
        # C1: parsed at assembly so a malformed QUALIFY_DEV_PRINCIPALS fails the boot,
        # not the first request.
        app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
    return app
