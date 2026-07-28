"""The DB-backed `CredentialReader` C-03 deferred to C-04 (see `resolver.py`).

This is the ONLY code in the repo that reads `oauth_credentials.ciphertext`, and it does
so through `credential_session` — the `qualify_credential` role, the only grantee of that
column (R3). `qualify_app`, which runs everything else, gets `permission denied` from
Postgres if it tries. The isolation is structural: two roles, two column grants, both
RLS-subject.

The reader returns the ciphertext, never plaintext. Decryption happens one layer up, in
`InjectingCredentialResolver`, where the plaintext lives only long enough to become an
`Authorization` header on a client object. Splitting it this way means no single object
holds both the ability to fetch a credential and the decrypted value of one.

The reader is bound to a tenant at construction rather than taking one per call: a reader
handed a `connection_id` from a different tenant must not be able to widen its own scope
by passing a different tenant id later.
"""

from __future__ import annotations

from uuid import UUID

from qualify_shared.db.credential import credential_session
from sqlalchemy import text

from qualify_api.connections.resolver import EncryptedCredential


class CredentialNotFound(Exception):
    """No credential row visible for this connection under this tenant.

    Ambiguous on purpose: a connection in another tenant and a connection with no
    credential are indistinguishable here, because RLS filters the first to zero rows
    before this code sees it. Both mean "you get nothing".
    """


class DbCredentialReader:
    """Reads the current (highest-version) credential for a connection, in one tenant."""

    def __init__(self, tenant_id: UUID) -> None:
        self._tenant_id = tenant_id

    def read_current(self, connection_id: UUID) -> EncryptedCredential:
        with credential_session(self._tenant_id) as session:
            # Raw SQL, not the ORM: the ORM model maps columns `qualify_credential` is not
            # granted (e.g. token_type), and a `SELECT *` would fail on privilege. This
            # selects exactly the two columns the role holds.
            row = session.execute(
                text(
                    "SELECT ciphertext, key_id FROM oauth_credentials "
                    "WHERE connection_id = :cid ORDER BY version DESC LIMIT 1"
                ),
                {"cid": str(connection_id)},
            ).first()
        if row is None:
            raise CredentialNotFound(f"no credential for connection {connection_id}")
        return EncryptedCredential(ciphertext=bytes(row.ciphertext), key_id=str(row.key_id))
