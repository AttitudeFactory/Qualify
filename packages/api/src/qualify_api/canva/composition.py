"""Production wiring for the Canva round trip: env config, Postgres, the same encryptor
as the Meta credentials, and the creative media store (so an export from Canva lands
next to the draft's own files and is served by the same upload route)."""

from __future__ import annotations

from qualify_creative.adapters.canva_connect import CanvaConnectClient

from qualify_api.canva.repository import PostgresCanvaRepository
from qualify_api.canva.service import CanvaConfig, CanvaService
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.creative.composition import media_root
from qualify_api.creative.media import LocalMediaStore


def production_canva_service() -> CanvaService:
    """Raises `CanvaNotConfigured` while the integration's credentials are not set."""
    config = CanvaConfig.from_env()
    return CanvaService(
        config=config,
        repository=PostgresCanvaRepository(),
        client=CanvaConnectClient(client_id=config.client_id, client_secret=config.client_secret),
        encryptor=DevEncryptor(),
        store=LocalMediaStore(media_root()),
    )
