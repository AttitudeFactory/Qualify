"""The Instagram comments read seam (B1, Fase 1 Parte 4-B).

Same shape as `connections/meta_oauth.py` and `publishing/client.py`, for the same
reason: a `Protocol` the future service depends on, a real HTTP implementation, and one
`_parse_*` function marked `[V]` per endpoint. This module has exactly one endpoint:

    GET /{ig-media-id}/comments

## This endpoint is not `[V]` in the usual sense

Every other client in this repo shipped its `_parse_*` function against a corpus
reading, never observed live. This one is different: on 2026-08-14 a real connection
(`@qualifymkt.co`, scope `instagram_manage_comments`) called this exact endpoint with
this exact field list and Meta returned a real comment that
`qualify_shared.social.ig_shapes.parse_comments_page` parsed without any adjustment.
`_parse_comments_response` below is that same call, not a new reading of the corpus —
see `packages/models/NOTES_ig_shapes_contract.md` §9 and the smoke scripts referenced
there for the observation this client formalizes.

## What this module deliberately does NOT do

- **No pagination-following.** `after` is a plain passthrough of Meta's own cursor
  (`IGCommentsPage.paging`); walking multiple pages, deciding when to stop, and
  deduplicating by comment id is B2's job (the sync service), not this client's.
- **No persistence, no repository, no service.** This is a read function over ids,
  same posture as `PublishClient` before `publishing/service.py` existed.
- **No field guessing.** `COMMENT_FIELDS` is exactly the field list QUA-67 models and
  that was verified live; nothing here re-derives a field list from the corpus.

## Token discipline

Same as the other two clients: no token appears in this file. The client receives an
already-authenticated `AuthenticatedClient` from `CredentialResolver.client_for(...,
scheme=...)` — this module never sees a credential at all, only Bearer/OAuth headers
already injected upstream. Error messages carry HTTP status and Meta's numeric
`error.code`/`error.error_subcode` only, never a response body (a failed Graph call
regularly echoes request parameters, and `text`/`username` are user-generated content
that does not belong in a log either).
"""

from __future__ import annotations

from typing import Any, Final, Protocol

import httpx
from pydantic import ValidationError
from qualify_shared.social.ig_shapes import IGCommentsPage, parse_comments_page

from qualify_api.connections.resolver import AuthenticatedClient

# Exactly the field list verified live 2026-08-14 against a real connection. Deliberately
# a flat literal, not derived from `IGComment`'s fields at import time: QUA-67 already
# tracks `UNSUPPORTED_FIELDS` as data, and re-deriving the request shape from the model
# would make a schema change silently change what this client asks Meta for.
COMMENT_FIELDS: Final = "id,text,timestamp,from,username,parent_id,hidden,like_count,media,replies"


class CommentsReadError(Exception):
    """A comments-read call failed. Never carries the token or the response body.

    `platform_code`/`platform_subcode` are Meta's numeric `error.code`/`error.error_subcode`
    when the failed response carried them — same discipline as `publishing.client.PublishError`,
    for the same reason: a numeric code lets a future caller distinguish a missing-permission
    refusal from a bad media id without a body ever traveling.

    `http_status` (QUA-90) is the raw HTTP status, captured alongside the platform code —
    same reasoning as `PublishError.http_status`: detecting a runtime auth failure is HTTP
    401 **or** code 190, and the code alone cannot express that "or".
    """

    def __init__(
        self,
        message: str,
        *,
        platform_code: int | None = None,
        platform_subcode: int | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.platform_code = platform_code
        self.platform_subcode = platform_subcode
        self.http_status = http_status


class CommentsClient(Protocol):
    async def list_comments(
        self, *, ig_media_id: str, after: str | None = None
    ) -> IGCommentsPage: ...


# --- [V] response parsing. One function per endpoint; the only place reality lands. ---


def _error_codes(response: httpx.Response) -> tuple[int | None, int | None]:
    """Meta's numeric `error.code`/`error.error_subcode` from a failed response, or Nones.

    Same extraction as `publishing.client._error_codes`, duplicated rather than imported:
    each client module is self-contained, the same discipline `meta_oauth.py` and
    `publishing/client.py` already follow independently of each other.
    """
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


def _parse_comments_response(payload: dict[str, Any]) -> IGCommentsPage:
    """[VERIFIED 2026-08-14 against a real connection] `{"data": [...], "paging": {...}}`.

    Delegates entirely to `qualify_shared.social.ig_shapes.parse_comments_page` — QUA-67
    owns the shape, this function owns turning a contract failure into `CommentsReadError`
    so callers only ever catch one exception type from this module.
    """
    try:
        return parse_comments_page(payload)
    except (ValueError, ValidationError) as exc:
        # NEVER interpolate `exc` itself: pydantic's ValidationError.__str__() echoes the
        # offending `input_value` verbatim (confirmed empirically, not assumed), and that
        # value can be a real comment's `text`/`username` — exactly the user-generated
        # content this module's docstring already promises never to log. Only the
        # exception's TYPE is structural and safe. `from exc` is kept: the original
        # ValidationError (with the field path and input) survives on `__cause__` for a
        # developer attached to a debugger or reading a local traceback — it just never
        # becomes part of CommentsReadError's own message/str().
        raise CommentsReadError(
            f"comments response did not match the QUA-67 contract ({type(exc).__name__})"
        ) from exc


class HttpCommentsClient:
    """Real client over one already-authenticated client — `graph.facebook.com` only.

    Unlike `HttpPublishClient`, there is no second host: the comments edge never touches
    `rupload`. Takes an `AuthenticatedClient` rather than a token, built upstream by
    `CredentialResolver.client_for(connection_id, scheme=settings.graph_auth_scheme)` —
    the same seam `connections` and `publishing` already use, honoured rather than
    reinvented.
    """

    def __init__(self, *, graph_client: AuthenticatedClient, graph_url: str) -> None:
        self._graph = graph_client
        self._graph_url = graph_url.rstrip("/")

    async def list_comments(self, *, ig_media_id: str, after: str | None = None) -> IGCommentsPage:
        params = {"fields": COMMENT_FIELDS}
        if after is not None:
            # Plain passthrough of Meta's own cursor (`ig_shapes.INCREMENTAL_POLLING_NOTE`:
            # comments cannot be filtered by timestamp, so a since-cursor does not exist —
            # `after` is the only pagination Meta offers here). Deciding to follow it,
            # when to stop, and how to dedupe is B2's job, not this client's.
            params["after"] = after
        response = await self._graph.get(f"{self._graph_url}/{ig_media_id}/comments", params=params)
        if response.status_code != 200:
            # Status and NUMERIC platform codes only — same reason as PublishError: the
            # body of a failed Graph call routinely echoes request parameters.
            code, subcode = _error_codes(response)
            raise CommentsReadError(
                f"GET /{ig_media_id}/comments failed with HTTP {response.status_code}",
                platform_code=code,
                platform_subcode=subcode,
                http_status=response.status_code,
            )
        return _parse_comments_response(dict(response.json()))
