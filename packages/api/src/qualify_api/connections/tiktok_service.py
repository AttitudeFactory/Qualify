"""The TikTok connect flow (m-24921091), mirroring `service.ConnectService`.

Same order of operations, same security design:

1. Verify the `state` signature and spend its `jti` BEFORE exchanging the code — a forged or
   replayed callback costs nothing. The signing key is domain-separated from Meta's
   (`<secret>:tiktok`), so a Meta `state` is never valid here and vice versa.
2. **PKCE.** The `code_verifier` is generated at `start_connect` and kept SERVER-SIDE in
   Redis next to the jti (`oauth:pkce:<jti>`, `GETDEL` at the callback). It never rides in
   the `state`, which is readable by whoever holds it.
3. Record what was GRANTED, never what was requested: TikTok lets the user untick scopes.
   Without `video.upload` the connection cannot do its only job (send drafts), so it lands
   `degraded` with `reconnect_reason = permission_missing` and the outcome says so.
4. Encrypt before persisting; verify after through the resolver (never reusing the plaintext).
5. A reconnect (`connection_id` in the state) must come back as the SAME TikTok account; a
   different one is `account_access_required` and nothing is persisted.

Idempotency: `social_connections` natural key `(tenant, platform, external_account_id)` with
`external_account_id = open_id`; reconnecting appends credential version+1, never a second row.

Status for apps TikTok has not audited yet: `access_posture` is `development` until
`TIKTOK_ACCESS_POSTURE=live`; see `tiktok_access_notice`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.config import TikTokSettings
from qualify_api.connections.crypto import Encryptor
from qualify_api.connections.events import DomainEvent, DomainEventName, EventPublisher
from qualify_api.connections.read import list_connections
from qualify_api.connections.repository import ConnectionRepository, GrantInput
from qualify_api.connections.service import (
    ConnectionVerifier,
    ConnectOutcome,
    ConnectResult,
    apply_post_grant_status,
)
from qualify_api.connections.state_token import (
    InvalidState,
    JtiStore,
    StatePayload,
    StateRedis,
    new_payload,
    sign_state,
    verify_state,
)
from qualify_api.connections.tiktok_oauth import (
    TikTokOAuthClient,
    code_challenge_for,
    new_code_verifier,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM = "tiktok"
ACCOUNT_TYPE = "creator"
UPLOAD_SCOPE = "video.upload"

# Client-facing, Spanish, plain (qualify-copy-es). Shown next to the TikTok account.
NOTICE_DEVELOPMENT = (
    "TikTok todavía no ha revisado la aplicación de Qualify. Mientras tanto, solo puedes "
    "enviar borradores a cuentas autorizadas como probadoras, y los videos solo los verás tú."
)
NOTICE_PERMISSION_MISSING = (
    "Falta el permiso para enviar videos a tus borradores de TikTok. "
    "Vuelve a conectar la cuenta y acepta ese permiso."
)


def tiktok_access_notice(access_posture: str) -> str:
    """The status line for a TikTok account: empty once TikTok audited the client."""
    return "" if access_posture == "live" else NOTICE_DEVELOPMENT


def state_secret(settings: TikTokSettings) -> str:
    """Domain separation from the Meta flow, which signs with the bare shared secret."""
    return f"{settings.state_secret}:tiktok"


class PkceStore:
    """The code verifier of one in-flight authorization, keyed by the state's jti."""

    def __init__(self, redis: StateRedis, *, ttl_seconds: int = 600) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(jti: str) -> str:
        return f"oauth:pkce:{jti}"

    def put(self, jti: str, verifier: str) -> None:
        if not self._redis.set(self._key(jti), verifier, nx=True, ex=self._ttl):
            raise InvalidState("pkce already in flight")

    def take(self, jti: str) -> str | None:
        raw = self._redis.getdel(self._key(jti))
        if raw is None:
            return None
        return raw.decode("ascii") if isinstance(raw, bytes) else raw


class TikTokConnectService:
    def __init__(
        self,
        *,
        settings: TikTokSettings,
        oauth_client: TikTokOAuthClient,
        repository: ConnectionRepository,
        jti_store: JtiStore,
        pkce_store: PkceStore,
        encryptor: Encryptor,
        verifier: ConnectionVerifier,
        publisher: EventPublisher,
    ) -> None:
        self._settings = settings
        self._oauth = oauth_client
        self._repo = repository
        self._jti = jti_store
        self._pkce = pkce_store
        self._encryptor = encryptor
        self._verifier = verifier
        self._publisher = publisher

    def start_connect(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID | None,
        user_id: UUID,
        connection_id: UUID | None = None,
        return_to: str = "",
        cause: str = "",
    ) -> str:
        """Register a one-shot `state` + PKCE verifier and return the TikTok consent URL."""
        external_account_id = ""
        if connection_id is not None:
            target = next(
                (row for row in list_connections(tenant_id) if row.connection_id == connection_id),
                None,
            )
            if target is None or target.platform != PLATFORM:
                from qualify_api.connections.revoke import ConnectionNotFound

                raise ConnectionNotFound()
            brand_id = target.brand_id
            external_account_id = target.external_account_id
            cause = target.reconnect_reason or cause
        payload = new_payload(
            tenant_id,
            brand_id,
            user_id,
            return_to=return_to if connection_id else "",
            connection_id=connection_id,
            external_account_id=external_account_id,
            cause=cause,
        )
        verifier = new_code_verifier()
        self._jti.issue(payload.jti)
        self._pkce.put(payload.jti, verifier)
        state = sign_state(payload, state_secret(self._settings))
        return self._oauth.authorization_url(
            state=state, code_challenge=code_challenge_for(verifier)
        )

    def callback_context(self, state: str) -> StatePayload:
        return verify_state(
            state, state_secret(self._settings), ttl_seconds=self._settings.state_ttl_seconds
        )

    def consume_callback_state(self, state: str) -> StatePayload:
        payload = self.callback_context(state)
        if not self._jti.consume(payload.jti):
            raise InvalidState("state already consumed")
        return payload

    async def complete_connect(self, *, code: str, state: str) -> ConnectResult:
        payload = self.consume_callback_state(state)
        code_verifier = self._pkce.take(payload.jti)
        if code_verifier is None:
            raise InvalidState("pkce verifier missing or expired")

        tokens = await self._oauth.exchange_code(code=code, code_verifier=code_verifier)
        user = await self._oauth.fetch_user(tokens.access_token)

        if payload.connection_id is not None and user.open_id != payload.external_account_id:
            # The owner logged into a different TikTok account. Persist nothing.
            return ConnectResult(
                outcome=ConnectOutcome.ACCOUNT_ACCESS_REQUIRED,
                connection_id=payload.connection_id,
                external_username=None,
                return_to=payload.return_to,
            )

        now = datetime.now(UTC)
        record = self._repo.persist_grant(
            GrantInput(
                tenant_id=payload.tenant_id,
                brand_id=payload.brand_id,
                user_id=payload.user_id,
                platform_app_id=self._repo.platform_app_id(
                    self._settings.client_key, tenant_id=payload.tenant_id
                ),
                platform=PLATFORM,
                account_type=ACCOUNT_TYPE,
                external_account_id=user.open_id,
                external_username=user.display_name,
                linked_page_id=None,  # a TikTok account has no Page (migration 0109)
                granted_scopes=tokens.scopes,
                access_posture=self._settings.access_posture,
                ciphertext=self._encryptor.encrypt(tokens.to_blob()),
                key_id=self._encryptor.key_id,
                token_type="tiktok",
                issued_at=now,
                expires_at=tokens.access_expires_at,
            )
        )
        self._publisher.publish(
            DomainEvent(
                name=DomainEventName.GRANTED,
                connection_id=record.connection_id,
                tenant_id=record.tenant_id,
                occurred_at=now,
                data={"credential_version": record.credential_version},
            )
        )
        verified = await self._verifier.verify(
            tenant_id=record.tenant_id, connection_id=record.connection_id
        )
        permission_missing = UPLOAD_SCOPE not in tokens.scopes
        status = apply_post_grant_status(
            self._repo,
            self._publisher,
            previous_status=record.previous_status,
            verified=verified and not permission_missing,
            connection_id=record.connection_id,
            tenant_id=record.tenant_id,
            credential_version=record.credential_version,
            now=now,
            reconnect_reason="permission_missing" if permission_missing else None,
        )
        if permission_missing:
            outcome = ConnectOutcome.PERMISSION_MISSING
        elif str(status) == "active":
            outcome = ConnectOutcome.ACTIVE
        else:
            outcome = ConnectOutcome.DEGRADED
        return ConnectResult(
            outcome=outcome,
            connection_id=record.connection_id,
            external_username=user.display_name,
            return_to=payload.return_to,
        )
