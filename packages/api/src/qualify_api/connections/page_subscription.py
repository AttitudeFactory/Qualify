"""Subscribe the connected Facebook Page to Qualify's Meta app webhooks (m-24789549).

## Why this exists

On the Instagram-API-with-Facebook-Login fork, an app only receives Instagram webhooks for
an account whose **Page** has the app installed through `POST /{page-id}/subscribed_apps`
(`reference/meta-instagram-platform/docs/graph-api/webhooks/getting-started/
webhooks-for-instagram.md`, «Step 2: Enable Page Subscriptions»). Measured live on
2026-10-22 (`docs/conversaciones-limitaciones-meta.md` §7, R3): with the edge empty, Meta
rejects every normal DM with `(#10)` subcode 2534022 («fuera del período permitido») and no
message webhook arrives; after `POST …/subscribed_apps?subscribed_fields=messages` a new
message from the tester opened the window and the DM went out. Until this module the
founder did that by hand in Graph API Explorer, per account.

## Which `subscribed_fields`, and why only `messages`

The Page edge takes **Page** fields, never Instagram ones: «You cannot use the
`subscribed_fields` parameter to configure or subscribe to Webhooks for Instagram. You must
use your app dashboard» (`docs/graph-api/reference/page/subscribed_apps.md`). The Instagram
fields our receivers consume — `instagram:messages` (Conversaciones), `instagram:comments`
and `mentions` (Interacciones / Menciones) — are therefore chosen in the app dashboard; the
Page subscription only has to exist, «subscribing to any Page field».

`messages` is the field that was verified live to open the DM window, and it is the Page
field whose webhooks (`object: page`, Messenger) we would receive at most for a Page that
also uses Messenger. `feed`, `mention` and friends would each start a stream of
`object: page` deliveries that no handler reads (they would settle `unsupported`), so they
are not requested. Adding a Page field is a change to `PAGE_SUBSCRIBED_FIELDS` plus
evidence in the doc above, never an env setting.

## Guarantees

- **Idempotent.** `POST subscribed_apps` with the same fields is a no-op for Meta, so a
  reconnect simply re-subscribes. `DELETE` on a Page the app is not installed on is also
  harmless.
- **Never fails the connection.** Every failure (HTTP, Graph error, missing credential,
  transport) is returned as a `SubscriptionResult`, recorded as a `connection_events` row
  and logged; nothing here raises into the callback.
- **Token discipline.** Subscribing goes through `CredentialResolver` (the Page token is
  read back as `qualify_credential` and injected as a header — this module never sees
  it). Unsubscribing uses the **app** access token, which Meta documents for this exact
  call («An app can remove its own webhook subscription from a Page with an App Access
  Token»), so revocation still never reads credential material. Only Graph error CODES are
  persisted, never a response body.
- **Provenance.** Each row carries the connection id, the credential version whose token
  was used and the actor; `social_connections.platform_app_id` names the app and Graph
  version; the field list is this module's versioned constant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import httpx
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import Encryptor
from qualify_api.connections.models import ConnectionEvent, SocialConnection
from qualify_api.connections.resolver import CredentialResolver, InjectingCredentialResolver

_LOGGER = logging.getLogger(__name__)

# Page fields for `POST /{page-id}/subscribed_apps`. See the module docstring for why this
# is `messages` alone.
PAGE_SUBSCRIBED_FIELDS: tuple[str, ...] = ("messages",)

# `connection_events.event_type` vocabulary (short form, like 'granted'/'revoked').
EVENT_PAGE_SUBSCRIBED = "page_subscribed"
EVENT_PAGE_SUBSCRIBE_FAILED = "page_subscribe_failed"
EVENT_PAGE_UNSUBSCRIBED = "page_unsubscribed"
EVENT_PAGE_UNSUBSCRIBE_FAILED = "page_unsubscribe_failed"
PAGE_SUBSCRIPTION_EVENT_TYPES: tuple[str, ...] = (
    EVENT_PAGE_SUBSCRIBED,
    EVENT_PAGE_SUBSCRIBE_FAILED,
    EVENT_PAGE_UNSUBSCRIBED,
    EVENT_PAGE_UNSUBSCRIBE_FAILED,
)

# What the /connections card can read (`ConnectionSummary.page_subscription`).
STATE_SUBSCRIBED = "subscribed"
STATE_FAILED = "failed"
STATE_UNSUBSCRIBED = "unsubscribed"
_STATE_BY_EVENT: dict[str, str] = {
    EVENT_PAGE_SUBSCRIBED: STATE_SUBSCRIBED,
    EVENT_PAGE_SUBSCRIBE_FAILED: STATE_FAILED,
    EVENT_PAGE_UNSUBSCRIBED: STATE_UNSUBSCRIBED,
    # A failed DELETE leaves the Page as it was: most likely still subscribed. The card
    # shows a revoked connection anyway, so "failed" is the honest, conservative reading.
    EVENT_PAGE_UNSUBSCRIBE_FAILED: STATE_FAILED,
}

# Non-Graph failure codes stored in `platform_error_code`.
ERROR_CREDENTIAL = "credential_unavailable"
ERROR_TRANSPORT = "transport_error"
ERROR_UNEXPECTED = "unexpected_response"


def subscription_state(event_type: str | None) -> str | None:
    """The card-facing state for the latest subscription event, or None if never tried."""
    return _STATE_BY_EVENT.get(event_type) if event_type is not None else None


@dataclass(frozen=True)
class SubscriptionResult:
    ok: bool
    # Meta's `error.code` (`code/subcode` when a subcode came back), `http_<status>` when
    # the body carried no Graph error, or one of the `ERROR_*` constants above. None on ok.
    error_code: str | None = None


def _graph_error_code(response: httpx.Response) -> str:
    """Graph error codes only — never the message, which may echo request material."""
    try:
        body = response.json()
    except ValueError:
        return f"http_{response.status_code}"
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("code") is not None:
        subcode = error.get("error_subcode")
        return f"{error['code']}/{subcode}" if subcode is not None else str(error["code"])
    return f"http_{response.status_code}"


def _parse_success(response: httpx.Response) -> SubscriptionResult:
    """[V] Documented return: `{"success": true}` (DELETE adds `messaging_success`)."""
    if response.status_code != 200:
        return SubscriptionResult(ok=False, error_code=_graph_error_code(response))
    try:
        body: Any = response.json()
    except ValueError:
        return SubscriptionResult(ok=False, error_code=ERROR_UNEXPECTED)
    if isinstance(body, dict) and body.get("success") is True:
        return SubscriptionResult(ok=True)
    return SubscriptionResult(ok=False, error_code=ERROR_UNEXPECTED)


class PageSubscriptionClient(Protocol):
    """The Graph seam. Implementations never raise: failure is a `SubscriptionResult`."""

    async def subscribe(
        self, *, tenant_id: UUID, connection_id: UUID, page_id: str
    ) -> SubscriptionResult: ...

    def unsubscribe(self, *, page_id: str) -> SubscriptionResult: ...


class GraphPageSubscriptionClient:
    """Real Graph implementation, on the configured base URL and API version."""

    def __init__(
        self,
        settings: MetaOAuthSettings,
        encryptor: Encryptor,
        *,
        resolver: CredentialResolver | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._encryptor = encryptor
        # Injected in tests; built per tenant otherwise (the reader is tenant-scoped).
        self._resolver = resolver
        self._transport = transport

    def _url(self, page_id: str) -> str:
        return f"{self._settings.graph_url}/{page_id}/subscribed_apps"

    async def subscribe(
        self, *, tenant_id: UUID, connection_id: UUID, page_id: str
    ) -> SubscriptionResult:
        resolver = self._resolver or InjectingCredentialResolver(
            DbCredentialReader(tenant_id), self._encryptor
        )
        try:
            client = await resolver.client_for(
                connection_id, scheme=self._settings.graph_auth_scheme
            )
        except Exception:  # noqa: BLE001 — missing/undecryptable credential is a result
            return SubscriptionResult(ok=False, error_code=ERROR_CREDENTIAL)
        try:
            response = await client.post(
                self._url(page_id),
                data={"subscribed_fields": ",".join(PAGE_SUBSCRIBED_FIELDS)},
            )
        except Exception:  # noqa: BLE001 — transport/timeout must not fail the connect
            return SubscriptionResult(ok=False, error_code=ERROR_TRANSPORT)
        finally:
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                await aclose()
        return _parse_success(response)

    def unsubscribe(self, *, page_id: str) -> SubscriptionResult:
        # App access token (`app_id|app_secret`) as a header, not a query parameter, so it
        # never lands in an httpx request log line.
        app_token = f"{self._settings.app_id}|{self._settings.app_secret}"
        try:
            with httpx.Client(transport=self._transport, timeout=10.0) as client:
                response = client.delete(
                    self._url(page_id),
                    headers={"Authorization": f"{self._settings.graph_auth_scheme} {app_token}"},
                )
        except Exception:  # noqa: BLE001 — best effort by contract
            return SubscriptionResult(ok=False, error_code=ERROR_TRANSPORT)
        return _parse_success(response)


class PageSubscriptionRecorder(Protocol):
    def record(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        credential_version: int | None,
        event_type: str,
        actor: str,
        error_code: str | None,
    ) -> None: ...

    def page_shared_by_live_connection(
        self, *, tenant_id: UUID, connection_id: UUID, page_id: str
    ) -> bool: ...


class PostgresPageSubscriptionRecorder:
    """Audit rows through `tenant_session` (RLS-scoped), same table as every other fact
    about a connection."""

    def record(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        credential_version: int | None,
        event_type: str,
        actor: str,
        error_code: str | None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.add(
                ConnectionEvent(
                    connection_id=connection_id,
                    tenant_id=tenant_id,
                    credential_version=credential_version,
                    event_type=event_type,
                    actor=actor,
                    platform_error_code=error_code,
                )
            )
            session.flush()

    def page_shared_by_live_connection(
        self, *, tenant_id: UUID, connection_id: UUID, page_id: str
    ) -> bool:
        """Another non-revoked connection of this tenant still relies on the Page."""
        with tenant_session(tenant_id) as session:
            other = session.scalar(
                select(SocialConnection.id).where(
                    SocialConnection.linked_page_id == page_id,
                    SocialConnection.id != connection_id,
                    SocialConnection.status != "revoked",
                )
            )
        return other is not None


class PageSubscriptions:
    """Subscribe on connect, unsubscribe on revoke; record both, never raise."""

    def __init__(
        self, *, client: PageSubscriptionClient, recorder: PageSubscriptionRecorder
    ) -> None:
        self._client = client
        self._recorder = recorder

    async def subscribe_after_connect(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        page_id: str,
        credential_version: int,
    ) -> SubscriptionResult:
        try:
            result = await self._client.subscribe(
                tenant_id=tenant_id, connection_id=connection_id, page_id=page_id
            )
        except Exception:  # noqa: BLE001 — a misbehaving client must not fail the connect
            result = SubscriptionResult(ok=False, error_code=ERROR_UNEXPECTED)
        if not result.ok:
            _LOGGER.warning(
                "page subscription failed: connection=%s error=%s",
                connection_id,
                result.error_code,
            )
        self._record_quietly(
            tenant_id=tenant_id,
            connection_id=connection_id,
            credential_version=credential_version,
            event_type=EVENT_PAGE_SUBSCRIBED if result.ok else EVENT_PAGE_SUBSCRIBE_FAILED,
            actor="system",
            error_code=result.error_code,
        )
        return result

    def unsubscribe_after_revoke(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        page_id: str | None,
        credential_version: int,
        actor: str,
    ) -> SubscriptionResult | None:
        """Best effort. None when nothing was attempted: no Page (WhatsApp), or another
        live connection of the tenant still needs the Page's webhooks."""
        if not page_id:
            return None
        try:
            if self._recorder.page_shared_by_live_connection(
                tenant_id=tenant_id, connection_id=connection_id, page_id=page_id
            ):
                return None
            result = self._client.unsubscribe(page_id=page_id)
        except Exception:  # noqa: BLE001 — the revocation already happened
            result = SubscriptionResult(ok=False, error_code=ERROR_UNEXPECTED)
        if not result.ok:
            _LOGGER.warning(
                "page unsubscription failed: connection=%s error=%s",
                connection_id,
                result.error_code,
            )
        self._record_quietly(
            tenant_id=tenant_id,
            connection_id=connection_id,
            credential_version=credential_version,
            event_type=EVENT_PAGE_UNSUBSCRIBED if result.ok else EVENT_PAGE_UNSUBSCRIBE_FAILED,
            actor=actor,
            error_code=result.error_code,
        )
        return result

    def _record_quietly(self, **kwargs: Any) -> None:
        try:
            self._recorder.record(**kwargs)
        except Exception:  # noqa: BLE001 — losing an audit row must not undo a connect
            _LOGGER.exception("page subscription: could not record %s", kwargs.get("event_type"))
