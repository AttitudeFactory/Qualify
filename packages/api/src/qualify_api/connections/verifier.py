"""Post-connection identity verification (C-04.1 step 7).

The check itself is trivial — one cheap Graph call that proves the stored credential
actually works. What matters is HOW it gets its credential: through `CredentialResolver`,
which hands back an already-authenticated client and never a token. So the verification
path holds no plaintext at all, even though it is the step that proves a token is valid.

This is also why verification is a separate seam from the service: the service briefly
holds the plaintext (it must, to encrypt it), and reusing that value here would make the
resolver boundary decorative. Going back through the resolver proves the round trip —
encrypt → store → read as `qualify_credential` → decrypt → authenticate — actually works,
which is the only thing that makes `active` an honest status.
"""

from __future__ import annotations

from uuid import UUID

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import Encryptor
from qualify_api.connections.resolver import InjectingCredentialResolver


class ResolverConnectionVerifier:
    """Verifies via the resolver. Any failure — HTTP, decrypt, missing row — is a failed
    verification, not an exception: the caller's job is to record `degraded`, and a raised
    error would abort the callback and leave the connection with no status at all."""

    def __init__(self, settings: MetaOAuthSettings, encryptor: Encryptor) -> None:
        self._settings = settings
        self._encryptor = encryptor

    async def verify(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), self._encryptor)
        try:
            # `/me` is a graph call, so it takes the graph scheme (R12). Named explicitly
            # because `client_for` has no default — the value is contested in the corpus and
            # must be stated by whoever knows which host they are about to call.
            client = await resolver.client_for(
                connection_id, scheme=self._settings.graph_auth_scheme
            )
        except Exception:
            # Missing row, RLS-filtered row, unknown key_id, decrypt failure — to the FSM
            # these are one thing: this credential does not work.
            return False
        try:
            response = await client.get(f"{self._settings.graph_url}/me", params={"fields": "id"})
        except Exception:
            return False  # transport/timeout — degraded, not a crashed callback
        finally:
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                await aclose()
        return response.status_code == 200
