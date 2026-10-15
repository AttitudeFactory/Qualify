"""Graph API error signatures shared by every Meta client in this codebase.

One definition per signature, so the inbox and the mentions module cannot drift apart.
"""

from __future__ import annotations


def is_missing_object_error(
    *, http_status: int | None, platform_code: int | None, platform_subcode: int | None
) -> bool:
    """Meta's "this object does not exist, or this app can no longer see it": HTTP 400,
    `error.code=100`, `error.error_subcode=33`. The pairing — never `code=100` alone, which
    also covers over a dozen unrelated validation errors — is the documented Graph API
    convention for a dead or inaccessible node id. [VERIFIED live 2026-09-01] on a deleted
    Instagram media (`inbox.service`).

    It does NOT say which: deleted, made private, blocked, or a node in the call the app
    lost access to are the same answer. Callers decide what that ambiguity allows.
    """
    return http_status == 400 and platform_code == 100 and platform_subcode == 33


def is_auth_error(*, http_status: int | None, platform_code: int | None) -> bool:
    """An expired or revoked token: HTTP 401 and/or `error.code=190` (QUA-90, [VERIFIED
    live 2026-08-14]). About the credential, never about the object asked for."""
    return http_status == 401 or platform_code == 190
