"""TikTok refresh-token rotation behind the resolver (m-24921091), offline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.locks import RefreshLock
from qualify_api.connections.resolver import EncryptedCredential
from qualify_api.connections.tiktok_credentials import (
    TikTokCredentialResolver,
    TikTokReconnectRequired,
)
from qualify_api.connections.tiktok_oauth import TikTokOAuthError, TikTokTokens

TENANT = uuid4()
CONN = uuid4()
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
ENC = DevEncryptor()


def tokens(access: str, refresh: str, *, access_in: timedelta, refresh_in=timedelta(days=300)):
    return TikTokTokens(
        access_token=access,
        refresh_token=refresh,
        open_id="o",
        access_expires_at=NOW + access_in,
        refresh_expires_at=NOW + refresh_in,
        scopes=("video.upload",),
    )


class Store:
    """Reader + rotator over one in-memory append-only list of versions."""

    def __init__(self, first: TikTokTokens) -> None:
        self.versions: list[bytes] = [ENC.encrypt(first.to_blob())]

    def read_current(self, connection_id: UUID) -> EncryptedCredential:
        return EncryptedCredential(ciphertext=self.versions[-1], key_id=ENC.key_id)

    def current_version(self, *, tenant_id: UUID, connection_id: UUID) -> int | None:
        return len(self.versions)

    def rotate(self, *, expected_version: int, ciphertext: bytes, **_: object) -> int | None:
        if expected_version != len(self.versions):
            return None
        self.versions.append(ciphertext)
        return len(self.versions)


class Oauth:
    def __init__(self, result: TikTokTokens | TikTokOAuthError) -> None:
        self.result = result
        self.refreshed_with: list[str] = []

    async def refresh(self, refresh_token: str) -> TikTokTokens:
        self.refreshed_with.append(refresh_token)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeRedis:
    def __init__(self) -> None:
        self.held: set[str] = set()

    def set(self, name: str, value: str, *, nx: bool = False, ex: int | None = None):
        if nx and name in self.held:
            return None
        self.held.add(name)
        return True

    def eval(self, script: str, numkeys: int, *args: str) -> int:
        self.held.discard(args[0])
        return 1


def resolver(
    store: Store, oauth: Oauth, degraded: list[UUID], redis=None
) -> TikTokCredentialResolver:
    return TikTokCredentialResolver(
        tenant_id=TENANT,
        reader=store,
        encryptor=ENC,
        oauth=oauth,  # type: ignore[arg-type]
        rotator=store,  # type: ignore[arg-type]
        lock=RefreshLock(redis or FakeRedis()),
        degrader=degraded.append,
        now=lambda: NOW,
    )


async def test_fresh_token_is_used_without_refresh() -> None:
    store = Store(tokens("A1", "R1", access_in=timedelta(hours=5)))
    oauth = Oauth(tokens("A2", "R2", access_in=timedelta(hours=24)))
    client = await resolver(store, oauth, []).client_for(CONN)
    assert "redacted" in repr(client) and oauth.refreshed_with == [] and len(store.versions) == 1


async def test_expiring_token_refreshes_and_rotates_the_refresh_token() -> None:
    store = Store(tokens("A1", "R1", access_in=timedelta(minutes=2)))
    oauth = Oauth(tokens("A2", "R2", access_in=timedelta(hours=24)))
    await resolver(store, oauth, []).client_for(CONN)
    assert oauth.refreshed_with == ["R1"]
    assert len(store.versions) == 2  # append-only: a NEW version, nothing overwritten
    stored = TikTokTokens.from_blob(ENC.decrypt(store.versions[-1], key_id=ENC.key_id))
    assert stored.refresh_token == "R2"  # the rotated refresh token replaced the old one


async def test_dead_refresh_token_degrades_and_asks_to_reconnect() -> None:
    store = Store(tokens("A1", "R1", access_in=timedelta(minutes=-5)))
    degraded: list[UUID] = []
    oauth = Oauth(TikTokOAuthError("x", code="invalid_grant"))
    with pytest.raises(TikTokReconnectRequired):
        await resolver(store, oauth, degraded).client_for(CONN)
    assert degraded == [CONN] and len(store.versions) == 1


async def test_expired_refresh_token_never_calls_tiktok() -> None:
    store = Store(
        tokens("A1", "R1", access_in=timedelta(minutes=-5), refresh_in=timedelta(days=-1))
    )
    degraded: list[UUID] = []
    oauth = Oauth(tokens("A2", "R2", access_in=timedelta(hours=24)))
    with pytest.raises(TikTokReconnectRequired):
        await resolver(store, oauth, degraded).client_for(CONN)
    assert oauth.refreshed_with == [] and degraded == [CONN]


async def test_reconnect_that_lands_during_refresh_is_not_overwritten() -> None:
    store = Store(tokens("A1", "R1", access_in=timedelta(minutes=2)))

    class RacingOauth(Oauth):
        async def refresh(self, refresh_token: str) -> TikTokTokens:
            # a fresh grant (version 2) lands while our refresh is in flight
            store.versions.append(
                ENC.encrypt(tokens("NEW", "NEWR", access_in=timedelta(hours=24)).to_blob())
            )
            return await super().refresh(refresh_token)

    oauth = RacingOauth(tokens("STALE", "STALER", access_in=timedelta(hours=24)))
    await resolver(store, oauth, []).client_for(CONN)
    assert len(store.versions) == 2  # the stale refresh wrote nothing
    last = TikTokTokens.from_blob(ENC.decrypt(store.versions[-1], key_id=ENC.key_id))
    assert last.access_token == "NEW"


async def test_a_contender_that_loses_the_lock_uses_the_winners_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(tokens("A1", "R1", access_in=timedelta(minutes=2)))
    redis = FakeRedis()
    redis.held.add(f"refresh:{TENANT}:{CONN}")  # someone else is refreshing

    async def winner_finishes(_: float) -> None:
        store.versions.append(
            ENC.encrypt(tokens("A2", "R2", access_in=timedelta(hours=24)).to_blob())
        )

    monkeypatch.setattr("qualify_api.connections.tiktok_credentials.asyncio.sleep", winner_finishes)
    oauth = Oauth(tokens("X", "X", access_in=timedelta(hours=24)))
    await resolver(store, oauth, [], redis).client_for(CONN)
    assert oauth.refreshed_with == []  # no second refresh: it would invalidate the rotation
