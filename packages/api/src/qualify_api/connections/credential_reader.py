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
    """Advertising USER token, never the organic Page token (m-24828972).

    Resolve the current grant through the application door before the narrow secret
    read. Revocation, reconnect, purge and expiry all fail closed.
    """

    def __init__(self, tenant_id: UUID, *, expected_version: int) -> None:
        self._tenant_id = tenant_id
        self._expected_version = expected_version

    def read_current(self, connection_id: UUID) -> EncryptedCredential:
        from qualify_shared.db.session import tenant_session

        with tenant_session(self._tenant_id) as session:
            version = session.scalar(
                text("""SELECT g.version FROM ad_oauth_credentials g
                JOIN social_connections c ON c.id=g.connection_id AND c.tenant_id=g.tenant_id
                  AND c.current_credential_version=g.version
                WHERE c.id=:cid AND c.platform='instagram' AND c.status='active'
                  AND c.purged_at IS NULL AND c.purge_started_at IS NULL
                  AND 'ads_management'=ANY(g.granted_scopes)
                  AND (g.expires_at IS NULL OR g.expires_at>now())"""),
                {"cid": connection_id},
            )
        if version is None or version != self._expected_version:
            raise CredentialNotFound("advertising credential unavailable")
        with credential_session(self._tenant_id) as session:
            row = session.execute(
                text("""SELECT ciphertext,key_id,version FROM ad_oauth_credentials
                WHERE connection_id=:cid AND version=:version"""),
                {"cid": connection_id, "version": version},
            ).first()
        if row is None:
            raise CredentialNotFound("advertising credential unavailable")
        # The secret door and the metadata gate use different roles. Fence the read
        # once more so an intervening reconnect/revoke cannot hand back a stale grant.
        with tenant_session(self._tenant_id) as session:
            still_current = session.scalar(
                text("""SELECT EXISTS(SELECT 1
                FROM social_connections WHERE id=:cid AND current_credential_version=:version
                AND status='active' AND purged_at IS NULL AND purge_started_at IS NULL)"""),
                {"cid": connection_id, "version": self._expected_version},
            )
        if not still_current:
            raise CredentialNotFound("advertising credential unavailable")
        return EncryptedCredential(bytes(row.ciphertext), str(row.key_id), int(row.version))
