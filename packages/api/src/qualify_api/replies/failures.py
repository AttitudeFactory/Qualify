"""Why a public reply did not go out, in the four cases the owner is told about
(ATENDER-9, m-24849130; founder decision 2026-10-23, §2b-5 and §2b-7a).

- `transient` — the request never reached Meta (no connection), or Meta answered that it
  is momentarily unavailable / over its rate limit. Stored `send_failed` with a
  `transient:…` code. The owner reads «Tu respuesta no salió: Instagram no respondió.»
  and gets «Reintentar» (sent only on a tap).
- `comment_deleted` — Meta says the comment no longer exists (HTTP 400, code 100,
  subcode 33). Stored `send_failed`, `deleted:100/33`. «Borraron ese comentario. Ya no se
  puede responder.», no retry.
- `refused` — any other definite refusal (permissions, auth, validation, …). Stored
  `send_failed`, `platform:<code>` / `auth:<code>` / `unknown`. «Tu respuesta no salió.
  Respóndela en Instagram.», no retry.
- `unknown` — the request went out and the answer never came back (read timeout,
  connection reset after sending, a gateway timeout). Stored `send_ambiguous`. «No sabemos
  si salió. Revísalo en Instagram.», no retry.

**Why a timeout is NOT `transient`.** The ticket lists «tiempo agotado» among the passing
failures, but a read timeout does not prove the reply stayed unpublished: on 2026-10-22
(m-24789646 R4) the client gave up on `POST /{comment-id}/replies` and the reply WAS public.
Offering «Reintentar» there could answer the same person twice in public. Only a failure
that proves the request never reached Meta (`CommentReplyError.not_sent`: a connect error
or connect/pool timeout) or that Meta itself refused for a passing reason is retried.

**Meta's passing codes** — Graph API "Handling errors": code 1 (unknown, "possibly a
temporary issue due to downtime"), 2 (service temporarily unavailable), 4 / 17 / 32 / 613
(rate limits), and any error whose body says `is_transient: true`; plus a bare HTTP 503.
[DOCUMENTED, not yet observed live on this edge.] The deleted-comment signature is
`qualify_shared.social.graph_errors.is_missing_object_error`, [VERIFIED live 2026-09-01]
on a deleted media read.

The stored code is for the team (logs, support); no code ever reaches the screen — the
UI maps the KIND to the owner's sentence (`Qualify/replies_vm.py`).
"""

from __future__ import annotations

from typing import Final, Literal

from qualify_shared.social.graph_errors import is_auth_error, is_missing_object_error

from qualify_api.replies.client import CommentReplyError

FailureKind = Literal["transient", "comment_deleted", "refused", "unknown"]

#: Meta error codes that mean "try again later", not "no".
TRANSIENT_PLATFORM_CODES: Final = frozenset({1, 2, 4, 17, 32, 613})
#: HTTP answers without a Meta error body that say the same.
_TRANSIENT_HTTP: Final = frozenset({503})
#: HTTP answers without a Meta error body that may have been processed upstream.
_AMBIGUOUS_HTTP: Final = frozenset({502, 504})

TRANSIENT_PREFIX: Final = "transient:"
DELETED_PREFIX: Final = "deleted:"


def classify_reply_error(exc: CommentReplyError) -> FailureKind:
    """The kind of one failed `post_reply`. Order matters: proof that nothing was sent
    first, then ambiguity, then Meta's own answer."""
    if exc.not_sent:
        return "transient"
    if exc.is_ambiguous:
        return "unknown"
    if is_auth_error(http_status=exc.http_status, platform_code=exc.platform_code):
        return "refused"
    if is_missing_object_error(
        http_status=exc.http_status,
        platform_code=exc.platform_code,
        platform_subcode=exc.platform_subcode,
    ):
        return "comment_deleted"
    if exc.platform_is_transient or exc.platform_code in TRANSIENT_PLATFORM_CODES:
        return "transient"
    if exc.platform_code is None and exc.http_status in _TRANSIENT_HTTP:
        return "transient"
    if exc.platform_code is None and exc.http_status in _AMBIGUOUS_HTTP:
        return "unknown"
    return "refused"


def error_code_for(exc: CommentReplyError, kind: FailureKind) -> str:
    """What `send_error_code` records — short, for the team; never the response body."""
    if kind == "transient":
        if exc.not_sent:
            return f"{TRANSIENT_PREFIX}not_sent"
        if exc.platform_code is not None:
            return f"{TRANSIENT_PREFIX}platform:{exc.platform_code}"
        return f"{TRANSIENT_PREFIX}http:{exc.http_status}"
    if kind == "comment_deleted":
        return f"{DELETED_PREFIX}{exc.platform_code}/{exc.platform_subcode}"
    if kind == "unknown":
        return f"ambiguous:http:{exc.http_status}" if exc.http_status else "ambiguous:transport"
    if is_auth_error(http_status=exc.http_status, platform_code=exc.platform_code):
        return f"auth:{exc.platform_code}"
    return f"platform:{exc.platform_code}" if exc.platform_code is not None else "unknown"


def failure_kind(status: str, send_error_code: str | None) -> FailureKind | None:
    """The kind of a stored draft's outcome, or None if it did not fail. Rows written
    before ATENDER-9 (`platform:…`, `auth:…`, `unknown`) read as `refused`, which is what
    the screen told the owner then."""
    if status == "send_ambiguous":
        return "unknown"
    if status != "send_failed":
        return None
    code = send_error_code or ""
    if code.startswith(TRANSIENT_PREFIX):
        return "transient"
    if code.startswith(DELETED_PREFIX):
        return "comment_deleted"
    return "refused"


def is_retryable(status: str, send_error_code: str | None) -> bool:
    """Only a passing failure offers «Reintentar»."""
    return failure_kind(status, send_error_code) == "transient"
