"""Connections module (C-03/C-04): social-account credential custody, the connection FSM,
and the OAuth connect/revoke flow.

Pure-logic seams (no DB/network) — the FSM, domain-event bus, encryptor, refresh lock, and
credential resolver — ship as Protocols + fakes; DDL/RLS/column-grants are Alembic
migration 0002. The credential resolver returns an authenticated client, never a token.

`list_connections`, `start_connect` and `revoke_connection` are the **published seam for
the Reflex CRM** — direct Python calls over ids, no HTTP hop. See `composition.py`."""

from qualify_api.connections.composition import revoke_connection, start_connect
from qualify_api.connections.crypto import DevEncryptor, Encryptor
from qualify_api.connections.events import (
    DomainEvent,
    DomainEventName,
    EventPublisher,
    InMemoryEventPublisher,
)
from qualify_api.connections.fsm import (
    ConnectionStatus,
    InvalidTransition,
    Trigger,
    apply_transition,
    next_status,
)
from qualify_api.connections.locks import RefreshLock, run_refresh
from qualify_api.connections.read import ConnectionSummary, list_connections
from qualify_api.connections.resolver import (
    AuthenticatedClient,
    CredentialReader,
    CredentialResolver,
    EncryptedCredential,
    InjectingCredentialResolver,
)
from qualify_api.connections.revoke import (
    ConnectionNotFound,
    RevokeResult,
    RevokeService,
)
from qualify_api.connections.service import (
    ConnectOutcome,
    ConnectResult,
    ConnectService,
)

__all__ = [
    "AuthenticatedClient",
    "ConnectOutcome",
    "ConnectResult",
    "ConnectService",
    "ConnectionNotFound",
    "ConnectionStatus",
    "ConnectionSummary",
    "CredentialReader",
    "CredentialResolver",
    "DevEncryptor",
    "DomainEvent",
    "DomainEventName",
    "EncryptedCredential",
    "Encryptor",
    "EventPublisher",
    "InMemoryEventPublisher",
    "InjectingCredentialResolver",
    "InvalidTransition",
    "RefreshLock",
    "RevokeResult",
    "RevokeService",
    "Trigger",
    "apply_transition",
    "list_connections",
    "next_status",
    "revoke_connection",
    "run_refresh",
    "start_connect",
]
