"""Production wiring; no network or environment customer token at import time."""

from __future__ import annotations

import os
from functools import cache

from qualify_api.pinterest.service import PendingFlows, PinterestService


@cache
def production_pinterest_service() -> PinterestService:
    import redis

    from qualify_api.config import redis_url
    from qualify_api.connections.crypto import DevEncryptor
    from qualify_api.connections.locks import RefreshLock
    from qualify_api.connections.state_token import JtiStore
    from qualify_api.pinterest.oauth import HttpOAuthClient
    from qualify_api.pinterest.repository import PostgresRepository
    from qualify_api.pinterest.settings import PinterestSettings

    settings = PinterestSettings.from_env()
    cipher_key = os.getenv("PINTEREST_FERNET_KEY") or os.getenv("QUALIFY_DEV_FERNET_KEY")
    if not cipher_key:
        raise ValueError("Pinterest credential encryption key is not configured")
    key_id = os.getenv("PINTEREST_FERNET_KEY_ID", "pinterest-1")
    client = redis.Redis.from_url(redis_url(), decode_responses=True)
    return PinterestService(
        settings=settings,
        repository=PostgresRepository(),
        oauth=HttpOAuthClient(settings),
        jti=JtiStore(client, ttl_seconds=settings.state_ttl_seconds),
        encryptor=DevEncryptor(key_id=key_id, keys={key_id: cipher_key}),
        refresh_lock=RefreshLock(client, ttl_seconds=120),
        pending=PendingFlows(client, settings.state_ttl_seconds),
    )
