"""Pinterest connection lifecycle, credential refresh and authorized selections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

from cryptography.fernet import InvalidToken

from qualify_api.connections.crypto import Encryptor
from qualify_api.connections.locks import RedisLike, RefreshLock
from qualify_api.connections.state_token import (
    InvalidState,
    JtiStore,
    StartedConnect,
    StatePayload,
    binding_cookie_name,
    binding_hash,
    binding_matches,
    new_binding_nonce,
    new_payload,
    sign_state,
    verify_state,
)
from qualify_api.pinterest.client import (
    Board,
    Page,
    Pin,
    PinterestClient,
    PinterestError,
    PinterestReader,
)
from qualify_api.pinterest.oauth import OAuthClient, Tokens
from qualify_api.pinterest.repository import Connection, Repository
from qualify_api.pinterest.settings import PinterestSettings


class PendingFlows:
    """Latest pending flow per signed user/business, invalidated on logout/switch."""

    def __init__(self, redis: RedisLike, ttl_seconds: int = 600) -> None:
        self._redis, self._ttl = redis, ttl_seconds

    @staticmethod
    def _key(tenant_id: UUID, user_id: UUID) -> str:
        return f"pinterest:pending:{tenant_id}:{user_id}"

    def put(self, payload: StatePayload, nonce: str) -> None:
        self._redis.set(self._key(payload.tenant_id, payload.user_id), payload.jti, ex=self._ttl)
        self._redis.set(f"pinterest:handoff:{payload.jti}", nonce, ex=self._ttl)

    def handoff(self, payload: StatePayload) -> str | None:
        if not self.live(payload):
            return None
        raw = self._redis.eval(
            "return redis.call('getdel',KEYS[1])", 1, f"pinterest:handoff:{payload.jti}"
        )
        if not isinstance(raw, (str, bytes)):
            return None
        self._redis.set(f"pinterest:ready:{payload.jti}", "1", ex=self._ttl)
        return raw.decode() if isinstance(raw, bytes) else raw

    def live(self, payload: StatePayload) -> bool:
        return bool(
            self._redis.eval(
                """if redis.call('get',KEYS[1]) == ARGV[1]
            then return 1 else return 0 end""",
                1,
                self._key(payload.tenant_id, payload.user_id),
                payload.jti,
            )
        )

    def ready(self, payload: StatePayload) -> bool:
        return bool(
            self._redis.eval(
                "return redis.call('getdel',KEYS[1])", 1, f"pinterest:ready:{payload.jti}"
            )
        )

    def consume(self, payload: StatePayload) -> bool:
        return bool(
            self._redis.eval(
                """if redis.call('get',KEYS[1]) == ARGV[1] then
            return redis.call('del',KEYS[1]) else return 0 end""",
                1,
                self._key(payload.tenant_id, payload.user_id),
                payload.jti,
            )
        )

    def cancel(self, tenant_id: UUID, user_id: UUID) -> None:
        self._redis.eval("return redis.call('del',KEYS[1])", 1, self._key(tenant_id, user_id))


class PinterestService:
    def __init__(
        self,
        *,
        settings: PinterestSettings,
        repository: Repository,
        oauth: OAuthClient,
        jti: JtiStore,
        encryptor: Encryptor,
        refresh_lock: RefreshLock,
        pending: PendingFlows,
        client_factory: Callable[[str], PinterestReader] = PinterestClient,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings, self._repo, self._oauth = settings, repository, oauth
        self._jti, self._encryptor, self._lock = jti, encryptor, refresh_lock
        self._client, self._now = client_factory, now
        self._pending = pending

    def connection(self, tenant_id: UUID) -> Connection | None:
        return self._repo.connection(tenant_id)

    def start_connect(self, *, tenant_id: UUID, user_id: UUID) -> StartedConnect:
        self._repo.authorize(tenant_id, user_id)
        row = self._repo.ensure(tenant_id)
        nonce = new_binding_nonce()
        payload = new_payload(
            tenant_id,
            None,
            user_id,
            connection_id=row.id,
            cause=str(row.version),
            binding=binding_hash(nonce),
            redirect_uri=self._settings.redirect_uri,
        )
        self._jti.issue(payload.jti)
        self._pending.put(payload, nonce)
        state = sign_state(payload, self._settings.state_secret + ":pinterest")
        return StartedConnect(
            self._settings.redirect_uri.removesuffix("/callback")
            + "/handoff?"
            + urlencode({"state": state}),
            binding_cookie_name("pinterest", payload.jti),
            nonce,
            self._settings.state_ttl_seconds,
            self._settings.redirect_uri,
        )

    def callback_context(self, state: str) -> StatePayload:
        return verify_state(
            state,
            self._settings.state_secret + ":pinterest",
            ttl_seconds=self._settings.state_ttl_seconds,
        )

    def binding_cookie(self, state: str) -> str:
        return binding_cookie_name("pinterest", self.callback_context(state).jti)

    def handoff(self, state: str, *, binding_nonce: str | None) -> StartedConnect:
        payload = self.callback_context(state)
        if not binding_matches(payload, binding_nonce):
            self._jti.consume(payload.jti)
            self._pending.consume(payload)
            raise InvalidState("Invalid Pinterest browser binding")
        nonce = self._pending.handoff(payload)
        if nonce is None or nonce != binding_nonce:
            raise InvalidState("Invalid Pinterest handoff")
        return StartedConnect(
            self._oauth.authorization_url(state),
            self.binding_cookie(state),
            nonce,
            self._settings.state_ttl_seconds,
            self._settings.redirect_uri,
        )

    def _consume(self, state: str, binding_nonce: str | None) -> StatePayload:
        payload = self.callback_context(state)
        if (
            not self._jti.consume(payload.jti)
            or not self._pending.ready(payload)
            or not self._pending.live(payload)
            or not binding_matches(payload, binding_nonce)
        ):
            raise InvalidState("Invalid Pinterest callback")
        row = self._repo.connection(payload.tenant_id)
        if row is None or row.id != payload.connection_id or str(row.version) != payload.cause:
            raise InvalidState("Invalid Pinterest callback")
        return payload

    def abandon_callback(self, state: str, *, binding_nonce: str | None) -> None:
        payload = self._consume(state, binding_nonce)
        self._pending.consume(payload)

    def complete_connect(self, *, code: str, state: str, binding_nonce: str | None) -> Connection:
        payload = self._consume(state, binding_nonce)
        self._repo.authorize(payload.tenant_id, payload.user_id)
        tokens = self._oauth.exchange(code)
        username = self._client(tokens.access_token).profile().username
        # Keep cancellation live throughout external I/O. This atomic final claim is
        # the completion point: a logout/switch before it prevents any grant write.
        if not self._pending.consume(payload):
            raise InvalidState("Pinterest authorization was cancelled")
        if not self._repo.save(
            payload.tenant_id,
            expected_version=int(payload.cause),
            username=username,
            user_id=payload.user_id,
            ciphertext=self._encryptor.encrypt(tokens.to_blob()),
            key_id=self._encryptor.key_id,
            expires_at=tokens.access_expires_at,
        ):
            raise InvalidState("Pinterest connection changed")
        row = self._repo.connection(payload.tenant_id)
        if row is None:
            raise PinterestError("not_found")
        return row

    def disconnect(self, tenant_id: UUID, user_id: UUID) -> None:
        self._repo.authorize(tenant_id, user_id)
        self._repo.disconnect(tenant_id, user_id)

    def cancel_pending(self, tenant_id: UUID, user_id: UUID) -> None:
        self._pending.cancel(tenant_id, user_id)

    def _tokens(self, tenant_id: UUID) -> tuple[Tokens, int]:
        credential = self._repo.read(tenant_id)
        invalid = False
        try:
            tokens = Tokens.from_blob(
                self._encryptor.decrypt(credential.ciphertext, key_id=credential.key_id)
            )
        except (ValueError, KeyError, TypeError, InvalidToken):
            invalid = True
        if invalid:
            self._repo.unavailable(tenant_id, credential.version)
            raise PinterestError("authentication", 401)
        return tokens, credential.version

    def _reader(self, tenant_id: UUID) -> tuple[PinterestReader, int]:
        tokens, version = self._tokens(tenant_id)
        if tokens.access_expires_at > self._now() + timedelta(minutes=5):
            return self._client(tokens.access_token), version
        row = self._repo.connection(tenant_id)
        if row is None:
            raise PinterestError("authentication", 401)
        with self._lock.acquire(tenant_id, row.id) as acquired:
            if not acquired:
                raise PinterestError("busy")
            tokens, version = self._tokens(tenant_id)
            if tokens.access_expires_at > self._now() + timedelta(minutes=5):
                return self._client(tokens.access_token), version
            if tokens.refresh_expires_at <= self._now():
                self._repo.unavailable(tenant_id, version)
                raise PinterestError("authentication", 401)
            try:
                fresh = self._oauth.refresh(tokens.refresh_token)
            except PinterestError as error:
                if error.kind in {"authentication", "permission"}:
                    self._repo.unavailable(tenant_id, version)
                raise
            if not self._repo.save(
                tenant_id,
                expected_version=version,
                username=row.username,
                user_id=None,
                ciphertext=self._encryptor.encrypt(fresh.to_blob()),
                key_id=self._encryptor.key_id,
                expires_at=fresh.access_expires_at,
            ):
                raise PinterestError("busy")
            return self._client(fresh.access_token), version + 1

    def _read[T](self, tenant_id: UUID, action: Callable[[PinterestReader], T]) -> T:
        reader, version = self._reader(tenant_id)
        try:
            result = action(reader)
        except PinterestError as error:
            if error.kind in {"authentication", "permission"}:
                self._repo.unavailable(tenant_id, version)
            raise
        row = self._repo.connection(tenant_id)
        if row is None or row.status != "active" or row.version != version:
            raise PinterestError("authentication", 401)
        return result

    def boards(
        self, tenant_id: UUID, *, page_size: int = 25, bookmark: str | None = None
    ) -> Page[Board]:
        return self._read(
            tenant_id, lambda reader: reader.boards(page_size=page_size, bookmark=bookmark)
        )

    def pins(
        self, tenant_id: UUID, board_id: str, *, page_size: int = 25, bookmark: str | None = None
    ) -> Page[Pin]:
        return self._read(
            tenant_id, lambda reader: reader.pins(board_id, page_size=page_size, bookmark=bookmark)
        )

    def resolve_pin(
        self,
        tenant_id: UUID,
        board_id: str,
        pin_id: str,
        *,
        bookmark: str | None = None,
        page_size: int = 25,
    ) -> Pin:
        page = self.pins(tenant_id, board_id, page_size=page_size, bookmark=bookmark)
        pin = next((pin for pin in page.items if pin.id == pin_id), None)
        if pin is None:
            raise PinterestError("not_found", 404)
        return pin
