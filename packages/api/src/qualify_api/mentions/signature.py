"""`X-Hub-Signature-256` verification for the `mentions` webhook (QUA-49).

Meta signs the raw POST body with the app's App Secret and sends
`X-Hub-Signature-256: sha256={hex-digest}`
(`docs/graph-api/webhooks/getting-started/webhooks-for-instagram.md:182-189`).
The comparison must run on the RAW bytes FastAPI received, before any JSON
parsing — parsing and re-serializing first would make the signature check
depend on byte-for-byte round-tripping that Meta's payload happens to survive
today, and stop meaning anything the day it does not.

Same HMAC primitives `connections/state_token.py` already uses for the OAuth
`state` token (`hmac.new(..., sha256)` + `hmac.compare_digest`), duplicated
rather than imported for the same self-containment reason `mentions/config.py`
gives for not importing `MetaOAuthSettings`.
"""

from __future__ import annotations

import hmac
from hashlib import sha256
from typing import Final

_SIGNATURE_PREFIX: Final = "sha256="


def verify_signature(*, body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """`True` iff `signature_header` is a valid `X-Hub-Signature-256` for `body`.

    `False` for a missing header, a header without the `sha256=` prefix, or a
    digest that does not match — one boolean, deliberately: a caller must reject
    all three identically (403), never distinguish "no signature" from "wrong
    signature" in its response, which would hand an attacker a free oracle for
    guessing the app secret.
    """
    if signature_header is None or not signature_header.startswith(_SIGNATURE_PREFIX):
        return False
    provided = signature_header[len(_SIGNATURE_PREFIX) :]
    expected = hmac.new(app_secret.encode("utf-8"), body, sha256).hexdigest()
    return hmac.compare_digest(provided, expected)
