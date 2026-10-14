"""Runtime configuration for the WhatsApp webhook receiver (WA-03).

Same self-containment discipline `mentions/config.py` documents: the app secret's env
var name is duplicated here rather than imported from `MetaOAuthSettings`, because it
is the same single App Secret Meta signs every webhook with (one app, one secret), and
this module must stay readable without pulling in the OAuth connect flow.

`verify_token` is deliberately a DIFFERENT variable from the mentions webhook's
(`QUALIFY_META_WEBHOOK_VERIFY_TOKEN`). Meta's panel configures the WhatsApp Business
Account product's callback separately from the User/Instagram one (observed 2026-10-13,
plan §10 point 4), so the two handshakes are independent and rotating one must never
force rotating the other — the same line `state_secret` vs `app_secret` already draws.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Dev-only fallbacks, same posture as `mentions/config.py`: a real deployment overrides
# both, and a forgotten app-secret override fails signature verification loudly on every
# real Meta payload rather than silently accepting anything.
_DEV_APP_SECRET = "dev-app-secret"
_DEV_VERIFY_TOKEN = "dev-only-wa-webhook-verify-token"


@dataclass(frozen=True)
class WhatsAppWebhookSettings:
    """Everything the receiver needs, as data — no Meta call is made here."""

    app_secret: str
    verify_token: str

    @classmethod
    def from_env(cls) -> WhatsAppWebhookSettings:
        return cls(
            app_secret=os.environ.get("QUALIFY_META_APP_SECRET", _DEV_APP_SECRET),
            verify_token=os.environ.get("QUALIFY_WA_WEBHOOK_VERIFY_TOKEN", _DEV_VERIFY_TOKEN),
        )
