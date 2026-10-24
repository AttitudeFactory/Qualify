"""The Instagram comment-reply write seam (QUA-22, comments tranche). Same shape as
`inbox/client.py` and `publishing/client.py`: a `Protocol` the service depends on, a
real HTTP implementation, and one `_parse_*` function marked with its evidence status.

    POST /{ig-comment-id}/replies?message={message}

## Evidence status — [VERIFIED] live (2026-10-22 and 2026-10-23)

The POST shape was first sourced from the harvested corpus:
`reference/meta-instagram-platform/.../ig-comment/replies.md` (`#replying`, worked
request/response example) and `comment-moderation.md` ("Reply to a comment"), both
under the Facebook Login fork (ADR 25) — never mixed with the Instagram Login column.
Both agree: `POST /<IG_COMMENT_ID>/replies` with `message` as a required parameter,
success response `{"id": "<new_comment_id>"}`. Permissions listed by both:
`instagram_basic`, `instagram_manage_comments`, `pages_show_list`/
`pages_read_engagement` — the same `manage_comments` gate `permission_capability.py`
already encodes for `REPLY_COMMENTS`, confirmed non-provisional (QUA-95).

Observed live against `@rauldevgames` (Facebook Login for Business, Standard Access):
the Fase C public notice (m-24789646 R4, 2026-10-22) and a Fase B commercial reply
(m-24789645, 2026-10-23: `sent`, Meta answered in about 6 s) both came back as
`{"id": ...}`, parsed by `_parse_reply_response`. Evidence:
`docs/conversaciones-limitaciones-meta.md` §7 and
`docs/interacciones-fase-b-respuestas-comerciales.md` §10.

## What this module deliberately does NOT do

- **No batching.** The corpus mentions batched replies as an option for high volume;
  out of scope for a human-approved, one-draft-at-a-time flow.
- **No persistence, no repository, no service.** Same posture `HttpCommentsClient` has
  — this is a write function over ids and text, nothing else.
- **No token appears here.** Same discipline as every other client: an already-
  authenticated `AuthenticatedClient` from `CredentialResolver.client_for(...,
  scheme=...)` is the only thing this module ever sees.
"""

from __future__ import annotations

from typing import Any, Final, Protocol

import httpx

from qualify_api.connections.resolver import AuthenticatedClient


class CommentReplyError(Exception):
    """A reply-post call failed. Never carries the token or the response body — same
    discipline as `CommentsReadError`/`PublishError`: the body of a failed Graph call
    routinely echoes request parameters, and `message` here is user-composed text that
    does not belong in a log either.

    `is_ambiguous` distinguishes a TRANSPORT failure (timeout, connection reset — the
    reply may or may not have posted) from a definite platform refusal (Meta answered
    with a non-200 and a body). Only the caller (the service) decides what to DO with
    that distinction; this exception only carries the fact.

    ATENDER-9 (m-24849130) adds two facts for `replies.failures.classify_reply_error`:
    `not_sent` — the request provably never reached Meta (connect error, connect or
    pool timeout), so a retry cannot duplicate the reply; and `platform_is_transient` —
    Meta's own `error.is_transient` flag."""

    def __init__(
        self,
        message: str,
        *,
        platform_code: int | None = None,
        platform_subcode: int | None = None,
        http_status: int | None = None,
        is_ambiguous: bool = False,
        not_sent: bool = False,
        platform_is_transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.platform_code = platform_code
        self.platform_subcode = platform_subcode
        self.http_status = http_status
        self.is_ambiguous = is_ambiguous
        self.not_sent = not_sent
        self.platform_is_transient = platform_is_transient


class CommentReplyClient(Protocol):
    async def post_reply(self, *, ig_comment_id: str, message: str) -> str:
        """Returns the new reply comment's id. Raises `CommentReplyError`."""
        ...


#: m-24789646 (R4, measured 2026-10-22 against @rauldevgames): `POST /{comment-id}/replies`
#: took longer than httpx's default 5 s to answer and the reply WAS published — the
#: client gave up first, so the caller saw an ambiguous transport error for a reply that
#: was public. Same lesson `publishing/client.py` (`GRAPH_WRITE_TIMEOUT`) and the DM
#: sender (`SEND_TIMEOUT_S`) already encode: a Graph write gets a generous read timeout.
REPLY_TIMEOUT: Final = httpx.Timeout(60.0, connect=30.0)


def _error_codes(response: httpx.Response) -> tuple[int | None, int | None]:
    """Duplicated from `inbox/client.py`/`publishing/client.py` rather than imported —
    each client module in this codebase is self-contained by convention."""
    try:
        error = dict(response.json()).get("error")
    except ValueError:
        return None, None
    if not isinstance(error, dict):
        return None, None
    code = error.get("code")
    subcode = error.get("error_subcode")
    return (
        code if isinstance(code, int) else None,
        subcode if isinstance(subcode, int) else None,
    )


def _is_transient_flag(response: httpx.Response) -> bool:
    """Meta's `error.is_transient` ("Handling errors": retry later), False if absent."""
    try:
        error = dict(response.json()).get("error")
    except ValueError:
        return False
    return isinstance(error, dict) and error.get("is_transient") is True


#: Transport failures that happen BEFORE the request is written: nothing reached Meta.
_NOT_SENT_ERRORS: Final = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def _parse_reply_response(payload: dict[str, Any]) -> str:
    """[VERIFIED] `{"id": "<new_comment_id>"}` — corpus citation and the live
    observations in the module docstring. The failure mode of an unexpected shape is a
    clear `CommentReplyError`, never a silent `None`/`KeyError` upstream."""
    reply_id = payload.get("id")
    if not isinstance(reply_id, str) or not reply_id:
        raise CommentReplyError(
            "reply response did not carry a string 'id' — does not match the "
            "ig-comment/replies.md contract"
        )
    return reply_id


class HttpCommentReplyClient:
    """Real client over one already-authenticated client — `graph.facebook.com` only,
    same host `HttpCommentsClient` uses (there is no `rupload` involved in a text
    reply)."""

    def __init__(self, *, graph_client: AuthenticatedClient, graph_url: str) -> None:
        self._graph = graph_client
        self._graph_url = graph_url.rstrip("/")

    async def post_reply(self, *, ig_comment_id: str, message: str) -> str:
        try:
            response = await self._graph.post(
                f"{self._graph_url}/{ig_comment_id}/replies",
                params={"message": message},
                timeout=REPLY_TIMEOUT,
            )
        except _NOT_SENT_ERRORS as exc:
            # ATENDER-9: the connection was never made, so the reply cannot have posted —
            # the one transport failure a retry cannot turn into a duplicate.
            raise CommentReplyError(
                f"could not reach Meta to reply to comment {ig_comment_id}: {type(exc).__name__}",
                not_sent=True,
            ) from exc
        except httpx.TransportError as exc:
            # The measured ambiguity `publishing/service.py` already names: a timeout or
            # connection reset here does NOT prove the reply did not post. The caller
            # (the service) is responsible for treating this as unsettled, never as a
            # definite failure.
            raise CommentReplyError(
                f"transport failure posting reply to comment {ig_comment_id}: {exc}",
                is_ambiguous=True,
            ) from exc

        if response.status_code != 200:
            code, subcode = _error_codes(response)
            raise CommentReplyError(
                f"POST /{ig_comment_id}/replies failed with HTTP {response.status_code}",
                platform_code=code,
                platform_subcode=subcode,
                http_status=response.status_code,
                platform_is_transient=_is_transient_flag(response),
            )
        return _parse_reply_response(dict(response.json()))
