"""Database access seams. `tenant_session` (RLS-scoped, request path), `admin_session`
(BYPASSRLS, provisioning/seed) and `credential_session` (RLS-scoped, the only role that
may read `oauth_credentials.ciphertext`) are the sanctioned doors — see the module
docstrings and the C-01 static test that forbids Sessions elsewhere."""

from qualify_shared.db.admin import admin_session
from qualify_shared.db.credential import credential_session
from qualify_shared.db.session import tenant_session

__all__ = ["admin_session", "credential_session", "tenant_session"]
