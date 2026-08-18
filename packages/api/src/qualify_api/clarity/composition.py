"""Wiring for the clarity module — same shape as `leads.composition`.

`production_clarity_service` is what the Reflex dashboard binds to (in-process, no
HTTP hop — same pattern as the connections UI). There are no public HTTP routes: the
Data Export integration is operator-facing, so nothing here belongs on the internet.
"""

from __future__ import annotations

from functools import cache

from qualify_api.clarity.client import HttpClarityClient
from qualify_api.clarity.repository import PostgresClarityRepository
from qualify_api.clarity.service import ClarityService
from qualify_api.connections.crypto import DevEncryptor


@cache
def production_clarity_service() -> ClarityService:
    """Cached like `production_leads_service`: one client and one encryptor per
    process. The encryptor is the same Fernet seam C-03 uses (QUALIFY_DEV_FERNET_KEY /
    QUALIFY_DEV_KEY_ID in the environment), so key custody has one story, not two."""
    return ClarityService(
        repository=PostgresClarityRepository(),
        client=HttpClarityClient(),
        encryptor=DevEncryptor(),
    )
