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
            # selects only columns the role holds (0002 grants `version` too).
            row = session.execute(
                text(
                    "SELECT ciphertext, key_id, version FROM oauth_credentials "
                    "WHERE connection_id = :cid ORDER BY version DESC LIMIT 1"
                ),
                {"cid": str(connection_id)},
            ).first()
        if row is None:
            raise CredentialNotFound(f"no credential for connection {connection_id}")
        return EncryptedCredential(
            ciphertext=bytes(row.ciphertext), key_id=str(row.key_id), version=int(row.version)
        )


class DbAdCredentialReader:
    """Current advertising or explicitly USER principal grant, never a Page token.

    Resolve the current grant through the application door before the narrow secret
    read. Revocation, reconnect, purge and expiry all fail closed.
    """

    def __init__(self, tenant_id: UUID, *, expected_version: int) -> None:
        self._tenant_id = tenant_id
        self._expected_version = expected_version

    def read_current(self, connection_id: UUID) -> EncryptedCredential:
        from qualify_shared.db.session import tenant_session

        from qualify_api.connections.ad_accounts import _connection, _permission_reason

        with tenant_session(self._tenant_id) as session:
            try:
                connection = _connection(session, connection_id)
            except ValueError:
                raise CredentialNotFound("advertising credential unavailable") from None
        if _permission_reason(connection) or connection.version != self._expected_version:
            raise CredentialNotFound("advertising credential unavailable")
        # Both table names are fixed code-owned values, never caller input. The
        # metadata door above proves a principal credential is a USER token.
        table = (
            "oauth_credentials"
            if connection.credential_source == "principal"
            else "ad_oauth_credentials"
        )
        with credential_session(self._tenant_id) as session:
            row = session.execute(
                text(f"""SELECT ciphertext,key_id,version FROM {table}
                WHERE connection_id=:cid AND version=:version"""),
                {"cid": connection_id, "version": connection.version},
            ).first()
        if row is None:
            raise CredentialNotFound("advertising credential unavailable")
        # The secret door and the metadata gate use different roles. Fence the read
        # once more so an intervening reconnect/revoke cannot hand back a stale grant.
        with tenant_session(self._tenant_id) as session:
            try:
                current = _connection(session, connection_id)
            except ValueError:
                raise CredentialNotFound("advertising credential unavailable") from None
        if current != connection or _permission_reason(current):
            raise CredentialNotFound("advertising credential unavailable")
        return EncryptedCredential(bytes(row.ciphertext), str(row.key_id), int(row.version))
