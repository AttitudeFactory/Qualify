"""The one place the real implementations get wired together (C-04).

Two callers, one assembly. The FastAPI app needs a `ConnectService` per request; the Reflex
CRM needs to start a connect and revoke one **without an HTTP hop** — it runs in the same
process, so posting to its own localhost port would be a pointless serialization round trip
that also loses the exception types. Both take their objects from here, so there is exactly
one function to audit for "does anything in this graph hold a token longer than it should".

The module-level `start_connect` / `revoke_connection` below are the **published seam for
the UI**. They are plain Python functions over ids: no HTTP, no request objects, nothing
credential-bearing in or out. `list_connections` completes the trio and already lives in
`read.py` — it is re-exported from the package `__init__` alongside these.

Everything here is **blocking** (Postgres, Redis, and — for the connect flow — a Meta call
in the callback, not in `start_connect`). A Reflex event handler must run them off the
event loop, exactly as `connections_for` already does.
"""

from __future__ import annotations

from functools import cache
from uuid import UUID

from qualify_api.config import MetaOAuthSettings, redis_url
from qualify_api.connections.auth_error import ConnectionStatus, degrade_on_auth_error
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.events import EventPublisher, InMemoryEventPublisher
from qualify_api.connections.meta_oauth import HttpMetaOAuthClient
from qualify_api.connections.repository import PostgresConnectionRepository
from qualify_api.connections.revoke import (
    PostgresRevocationRepository,
    RevokeResult,
    RevokeService,
)
from qualify_api.connections.service import ConnectService
from qualify_api.connections.state_token import JtiStore
from qualify_api.connections.verifier import ResolverConnectionVerifier


@cache
def production_event_publisher() -> EventPublisher:
    """In-process for now (ADR 6's real bus slots in behind the same Protocol).

    Shared by the connect and revoke paths deliberately: two publishers would mean a
    subscriber could see one half of a connection's lifecycle and not the other.
    """
    return InMemoryEventPublisher()


@cache
def production_connect_service() -> ConnectService:
    """Wire the real Meta client, the Postgres repository and a live Redis, once.

    Cached because FastAPI calls a dependency per request: without it every callback would
    open a fresh Redis connection pool. `redis` is imported inside the function so merely
    importing this module never requires a Redis to exist.
    """
    import redis

    settings = MetaOAuthSettings.from_env()
    encryptor = DevEncryptor()
    return ConnectService(
        settings=settings,
        oauth_client=HttpMetaOAuthClient(settings),
        repository=PostgresConnectionRepository(),
        jti_store=JtiStore(
            redis.Redis.from_url(redis_url(), decode_responses=True),
            ttl_seconds=settings.state_ttl_seconds,
        ),
        encryptor=encryptor,
        verifier=ResolverConnectionVerifier(settings, encryptor),
        publisher=production_event_publisher(),
    )


@cache
def production_revoke_service() -> RevokeService:
    """No Redis, no platform client — revocation is a local state transition."""
    return RevokeService(
        repository=PostgresRevocationRepository(),
        publisher=production_event_publisher(),
    )


def start_connect(*, tenant_id: UUID, brand_id: UUID | None, user_id: UUID) -> str:
    """Register a one-shot `state` and return the Meta authorization URL to redirect to.

    Keyword-only on purpose: three same-typed UUIDs in a row is precisely the signature
    where a positional swap compiles, type-checks, and silently connects the wrong tenant.

    Requires Redis (the `state` jti lives there) and Postgres is untouched until the
    callback. Blocking — call it off the event loop.
    """
    return production_connect_service().start_connect(
        tenant_id=tenant_id, brand_id=brand_id, user_id=user_id
    )


def revoke_connection(*, tenant_id: UUID, connection_id: UUID, actor: str = "user") -> RevokeResult:
    """Revoke a connection through the C-03 FSM. Idempotent; see `revoke.RevokeService`.

    Raises `ConnectionNotFound` when no such connection is visible to this tenant (which
    includes another tenant's id — RLS makes the two cases the same read), and
    `InvalidTransition` when the FSM has no `revoke` edge out of the current status.
    Blocking — call it off the event loop.
    """
    return production_revoke_service().revoke(
        tenant_id=tenant_id, connection_id=connection_id, actor=actor
    )


def degrade_connection_on_auth_error(
    *, tenant_id: UUID, connection_id: UUID
) -> ConnectionStatus | None:
    """QUA-90's published seam — the degrade analogue of `revoke_connection` above.
    Publishing and inbox call this by name (injected as their `connection_degrader`
    dependency, see `publishing/composition.py`/`inbox/composition.py`) when a call they
    were already making to Meta comes back 401/190.

    Reuses the same repositories `production_connect_service`/`production_revoke_service`
    build from, and the same shared `production_event_publisher()` — no separate publisher
    instance, for the reason `production_event_publisher`'s own docstring already gives.
    Never raises; see `degrade_on_auth_error`'s docstring. Blocking — call it off the
    event loop, same as `revoke_connection`.
    """
    return degrade_on_auth_error(
        tenant_id=tenant_id,
        connection_id=connection_id,
        reader=PostgresRevocationRepository(),
        writer=PostgresConnectionRepository(),
        publisher=production_event_publisher(),
    )
