"""Production assembly for publishing (A5) — the analogue of `connections/composition.py`.

The R2 store is imported LAZILY inside the factory: `boto3` is not yet a declared
dependency (C3 owns that declaration and the venv ritual), so importing it at module
level would break every consumer of this package today. The tests never call this
factory — they inject fakes — which is exactly why the lazy import is safe.
"""

from __future__ import annotations

from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate
from sqlalchemy import select

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import DevEncryptor, Encryptor
from qualify_api.connections.models import SocialConnection
from qualify_api.connections.resolver import InjectingCredentialResolver
from qualify_api.publishing.client import HttpPublishClient, PublishClient
from qualify_api.publishing.repository import PostgresPublishAttemptRepository
from qualify_api.publishing.service import ConnectionTarget, PublishService


class PostgresConnectionTargetReader:
    """Reads the two facts publishing needs from `social_connections`, RLS-scoped."""

    def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(SocialConnection).where(SocialConnection.id == connection_id)
            )
            if row is None:
                return None
            return ConnectionTarget(ig_user_id=row.external_account_id, status=row.status)


class ResolverPublishClientFactory:
    """Two authenticated clients per publish — one per host/scheme (R12) — resolved at
    publish time through the credential seam. Nothing here ever holds a token."""

    def __init__(self, settings: MetaOAuthSettings, encryptor: Encryptor) -> None:
        self._settings = settings
        self._encryptor = encryptor

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> PublishClient:
        resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), self._encryptor)
        graph = await resolver.client_for(connection_id, scheme=self._settings.graph_auth_scheme)
        rupload = await resolver.client_for(
            connection_id, scheme=self._settings.rupload_auth_scheme
        )
        return HttpPublishClient(
            graph_client=graph, rupload_client=rupload, graph_url=self._settings.graph_url
        )


def production_publish_service() -> PublishService:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415 — see module docstring
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    settings = MetaOAuthSettings.from_env()
    return PublishService(
        repository=PostgresPublishAttemptRepository(),
        gate=ObjectGate(R2ObjectStore(R2Settings.from_env())),
        connections=PostgresConnectionTargetReader(),
        client_factory=ResolverPublishClientFactory(settings, DevEncryptor()),
    )
