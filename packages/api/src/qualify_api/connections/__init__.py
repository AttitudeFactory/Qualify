"""Connections module (C-03/C-04): social-account credential custody, the connection FSM,
and the OAuth connect/revoke flow.

Pure-logic seams (no DB/network) — the FSM, domain-event bus, encryptor, refresh lock, and
credential resolver — ship as Protocols + fakes; DDL/RLS/column-grants are Alembic
migration 0002. The credential resolver returns an authenticated client, never a token.

`list_connections`, `start_connect` and `revoke_connection` are the **published seam for
the Reflex CRM** — direct Python calls over ids, no HTTP hop. See `composition.py`."""

from qualify_api.connections.composition import (
    check_connection_health,
    degrade_connection_on_auth_error,
    revoke_connection,
    start_connect,
)
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
from qualify_api.connections.runtime_health import (
    ConnectionRuntimeState,
    ReconnectCause,
    consume_recovery_refresh,
    get_connection_runtime_state,
    mark_connection_unavailable,
    record_connection_success,
    record_connection_temporary_failure,
)
from qualify_api.connections.service import (
    ConnectOutcome,
    ConnectResult,
    ConnectService,
)
from qualify_api.connections.token_health import DATA_ACCESS_WARNING_THRESHOLD

__all__ = [
    "DATA_ACCESS_WARNING_THRESHOLD",
    "AuthenticatedClient",
    "ConnectOutcome",
    "ConnectResult",
    "ConnectService",
    "ConnectionNotFound",
    "ConnectionRuntimeState",
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
    "ReconnectCause",
    "RevokeResult",
    "RevokeService",
    "Trigger",
    "apply_transition",
    "check_connection_health",
    "consume_recovery_refresh",
    "degrade_connection_on_auth_error",
    "get_connection_runtime_state",
    "list_connections",
    "mark_connection_unavailable",
    "next_status",
    "record_connection_success",
    "record_connection_temporary_failure",
    "revoke_connection",
    "run_refresh",
    "start_connect",
]
