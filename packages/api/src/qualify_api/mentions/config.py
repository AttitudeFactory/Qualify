"""Runtime configuration for the `mentions` webhook receiver (QUA-49).

**Duplicates `QUALIFY_META_APP_SECRET`'s name/default rather than importing
`qualify_api.config.MetaOAuthSettings`.** Same discipline `inbox/client.py`'s
docstring already states explicitly for this codebase: each client/receiver
module stays self-contained rather than reaching into a sibling module's
settings, so this module can be read, tested and reasoned about without
pulling in the whole OAuth connect flow. The value is the same real secret
either way — Meta signs a webhook payload with the same App Secret used for
the OAuth token exchange, there is only one.

`verify_token` is a SEPARATE secret, used ONLY for the GET challenge — never
for signing/verifying the POST body. Reusing one secret for two purposes would
mean rotating either forces rotating both; `state_secret` vs. `app_secret` in
`connections/config.py` already draws this same line for the same reason.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Dev-only fallback, same posture as `connections/config.py`'s `_DEV_STATE_SECRET`: a real
# deployment overrides both, and a forgotten override fails signature verification loudly
# (every real Meta payload) rather than silently accepting anything.
_DEV_APP_SECRET = "dev-app-secret"
_DEV_VERIFY_TOKEN = "dev-only-webhook-verify-token"


@dataclass(frozen=True)
class MentionsWebhookSettings:
    """Everything the webhook receiver needs, as data — no Meta call is made here."""

    app_secret: str
    verify_token: str

    @classmethod
    def from_env(cls) -> MentionsWebhookSettings:
        return cls(
            app_secret=os.environ.get("QUALIFY_META_APP_SECRET", _DEV_APP_SECRET),
            verify_token=os.environ.get("QUALIFY_META_WEBHOOK_VERIFY_TOKEN", _DEV_VERIFY_TOKEN),
        )
