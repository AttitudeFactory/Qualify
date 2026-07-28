"""Runtime configuration for the OAuth connect flow (C-04), read from the environment.

Two things here are deliberate and load-bearing:

**No Meta scope literal appears in this repo.** ADR 25 found FOUR spellings of the
publishing scope in circulation, and the correct set is `[V]` — resolvable only
empirically against the live authorization endpoint. So the requested scopes are
whatever `QUALIFY_META_SCOPES` holds, and the granted scopes come back from
`/me/permissions` and are persisted verbatim. Translating literals to capabilities is
`resolve_scope_keys`'s job (C-05, `packages/models`), downstream of everything here.

**The app secret and the state-signing secret are separate.** Reusing one secret for two
purposes means rotating either forces rotating both, and a leak of one compromises the
other. They are distinct env vars with distinct lifetimes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Dev-only fallbacks. Any real deployment overrides all three; the connect flow against
# real Meta credentials cannot work with these anyway (the app id/secret are not valid),
# so a forgotten override fails at the platform, not silently with weak crypto.
_DEV_STATE_SECRET = "dev-only-state-secret-not-for-production"
_DEFAULT_GRAPH_BASE_URL = "https://graph.facebook.com"
_DEFAULT_AUTHORIZE_URL = "https://www.facebook.com/dialog/oauth"
_DEFAULT_API_VERSION = "v21.0"
_DEFAULT_STATE_TTL_SECONDS = 600  # C-04.2: 10 minutes


@dataclass(frozen=True)
class MetaOAuthSettings:
    """Everything the connect flow needs to talk to Meta, as data.

    `api_version` is duplicated onto `platform_apps.api_version` as provenance (R1) — this
    is the version a request is made WITH; that column records what a stored payload was
    obtained UNDER. They are the same string today and must not be assumed to stay so.
    """

    app_id: str
    app_secret: str
    redirect_uri: str
    state_secret: str
    graph_base_url: str = _DEFAULT_GRAPH_BASE_URL
    authorize_url: str = _DEFAULT_AUTHORIZE_URL
    api_version: str = _DEFAULT_API_VERSION
    state_ttl_seconds: int = _DEFAULT_STATE_TTL_SECONDS
    # `[V]` — never hardcoded. Empty is a legitimate dev value: the fake platform double
    # in the tests does not care, and a real run without it simply requests no scopes.
    requested_scopes: tuple[str, ...] = ()
    # ADR 22(a): access level is data. Development Mode is the honest default for customer
    # zero; Advanced Access flips this to 'live' without a code change.
    access_posture: str = "development"

    @property
    def graph_url(self) -> str:
        """Versioned Graph base, e.g. `https://graph.facebook.com/v21.0`."""
        return f"{self.graph_base_url.rstrip('/')}/{self.api_version}"

    @classmethod
    def from_env(cls) -> MetaOAuthSettings:
        raw_scopes = os.environ.get("QUALIFY_META_SCOPES", "")
        scopes = tuple(s.strip() for s in raw_scopes.split(",") if s.strip())
        return cls(
            app_id=os.environ.get("QUALIFY_META_APP_ID", "dev-app-id"),
            app_secret=os.environ.get("QUALIFY_META_APP_SECRET", "dev-app-secret"),
            redirect_uri=os.environ.get(
                "QUALIFY_META_REDIRECT_URI", "http://localhost:8000/api/connections/callback"
            ),
            state_secret=os.environ.get("QUALIFY_OAUTH_STATE_SECRET", _DEV_STATE_SECRET),
            graph_base_url=os.environ.get("QUALIFY_GRAPH_BASE_URL", _DEFAULT_GRAPH_BASE_URL),
            authorize_url=os.environ.get("QUALIFY_META_AUTHORIZE_URL", _DEFAULT_AUTHORIZE_URL),
            api_version=os.environ.get("QUALIFY_META_API_VERSION", _DEFAULT_API_VERSION),
            state_ttl_seconds=int(
                os.environ.get("QUALIFY_OAUTH_STATE_TTL", str(_DEFAULT_STATE_TTL_SECONDS))
            ),
            requested_scopes=scopes,
            access_posture=os.environ.get("QUALIFY_META_ACCESS_POSTURE", "development"),
        )


def redis_url() -> str:
    """Redis for the one-shot `state` jti (C-04.2) and the refresh lock (C-03.4)."""
    return os.environ.get("QUALIFY_REDIS_URL", "redis://localhost:6379/0")
