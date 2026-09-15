"""The publish client seam (QUA-19 / A3), fully offline.

Every call is driven through an `httpx.MockTransport`, so the real `HttpPublishClient` code
path runs — URL construction, headers, parsing — with zero network. Testing the parse
functions alone would leave the part most likely to be wrong (which header goes to which
host) unexercised.
"""

from __future__ import annotations

import io

import httpx
import pytest

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.publishing.client import (
    CONTAINER_POLL_CEILING_SECONDS,
    CONTAINER_POLL_INTERVAL_SECONDS,
    RESUMABLE_MEDIA_TYPES,
    ContainerStatus,
    HttpPublishClient,
    PublishError,
    _parse_upload_response,
)

SETTINGS = MetaOAuthSettings(
    app_id="app", app_secret="secret", redirect_uri="https://x/cb", state_secret="s"
)
GRAPH_AUTH_SCHEME = SETTINGS.graph_auth_scheme
RUPLOAD_AUTH_SCHEME = SETTINGS.rupload_auth_scheme

TOKEN = "SUPER_SECRET_PUBLISH_TOKEN"
GRAPH = "https://graph.facebook.com/v21.0"
IG_USER = "17841400000000000"
CONTAINER = "18000000000000000"
UPLOAD_URI = f"https://rupload.facebook.com/ig-api-upload/v21.0/{CONTAINER}"


def _client(handler) -> HttpPublishClient:
    """Drives the REAL credential-injection path: two `_InjectedAuthClient`s, exactly as
    `CredentialResolver.client_for(..., scheme=...)` would return them. Faking the
    `AuthenticatedClient` here would skip the very thing R12 changed — which scheme lands on
    which host."""
    transport = httpx.MockTransport(handler)
    return HttpPublishClient(
        graph_client=_InjectedAuthClient(
            TOKEN, scheme=SETTINGS.graph_auth_scheme, transport=transport
        ),
        rupload_client=_InjectedAuthClient(
            TOKEN, scheme=SETTINGS.rupload_auth_scheme, transport=transport
        ),
        graph_url=GRAPH,
    )


def _json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


# --------------------------------------------------------------------------------------
# create_container
# --------------------------------------------------------------------------------------


async def test_create_container_returns_id_and_uri() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{IG_USER}/media")
        assert request.url.params["upload_type"] == "resumable"
        assert request.url.params["media_type"] == "REELS"
        return _json({"id": CONTAINER, "uri": UPLOAD_URI})

    container = await _client(handler).create_container(ig_user_id=IG_USER, media_type="REELS")
    assert container.container_id == CONTAINER
    assert container.upload_uri == UPLOAD_URI


async def test_create_container_uses_the_bearer_scheme_on_graph() -> None:
    """`content-publishing.md:84` — graph calls use Bearer."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return _json({"id": CONTAINER, "uri": UPLOAD_URI})

    await _client(handler).create_container(ig_user_id=IG_USER, media_type="REELS")
    assert seen["auth"] == f"{GRAPH_AUTH_SCHEME} {TOKEN}"


async def test_create_container_passes_thumb_offset_and_never_cover_url() -> None:
    """ADR 28: reel covers come from `thumb_offset`. `cover_url` would need public hosting
    even in the resumable variant (`resumable-uploads.md:53`), so the client must have no way
    to send it — asserted on the wire, not left to review."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return _json({"id": CONTAINER, "uri": UPLOAD_URI})

    await _client(handler).create_container(
        ig_user_id=IG_USER, media_type="REELS", caption="hola", thumb_offset=1200
    )
    assert seen["thumb_offset"] == "1200"
    assert seen["caption"] == "hola"
    assert not any("cover" in key for key in seen)


@pytest.mark.parametrize("media_type", sorted(RESUMABLE_MEDIA_TYPES))
async def test_every_resumable_media_type_is_accepted(media_type: str) -> None:
    """`resumable-uploads.md:32` — REELS, STORIES and VIDEO all have this path."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": CONTAINER, "uri": UPLOAD_URI})

    container = await _client(handler).create_container(ig_user_id=IG_USER, media_type=media_type)
    assert container.container_id == CONTAINER


async def test_image_media_type_is_refused_before_any_request() -> None:
    """Image has NO resumable variant, so IMAGE is a scope error (QUA-68), not a bad request.
    Refusing locally means the mistake surfaces as "you are outside this slice" rather than as
    an opaque platform error."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no request should be made for an unsupported media type")

    with pytest.raises(PublishError, match="no resumable upload path"):
        await _client(handler).create_container(ig_user_id=IG_USER, media_type="IMAGE")


async def test_container_without_uri_is_rejected() -> None:
    """An id with no uri leaves the caller unable to upload; guessing the uri would pin an
    API version Meta chose for us."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": CONTAINER})

    with pytest.raises(PublishError, match="upload uri"):
        await _client(handler).create_container(ig_user_id=IG_USER, media_type="REELS")


# --------------------------------------------------------------------------------------
# create_carousel_container (QUA-99)
# --------------------------------------------------------------------------------------

CHILD_A = "18000000000000001"
CHILD_B = "18000000000000002"
CAROUSEL_CONTAINER = "18900000000000000"


def _client_with_transports(graph_handler, rupload_handler=None) -> HttpPublishClient:
    """Like `_client`, but with an INDEPENDENT transport per host — needed to assert that
    a call never reaches `rupload` at all (a carousel container has nothing uploaded to
    it), which a single shared transport/handler could not distinguish."""

    def _refuse(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("rupload must never be called by create_carousel_container")

    return HttpPublishClient(
        graph_client=_InjectedAuthClient(
            TOKEN, scheme=SETTINGS.graph_auth_scheme, transport=httpx.MockTransport(graph_handler)
        ),
        rupload_client=_InjectedAuthClient(
            TOKEN,
            scheme=SETTINGS.rupload_auth_scheme,
            transport=httpx.MockTransport(rupload_handler or _refuse),
        ),
        graph_url=GRAPH,
    )


async def test_create_carousel_container_builds_the_request_with_children() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{IG_USER}/media")
        assert request.url.params["media_type"] == "CAROUSEL"
        assert request.url.params["children"] == f"{CHILD_A},{CHILD_B}"
        return _json({"id": CAROUSEL_CONTAINER})

    container_id = await _client_with_transports(handler).create_carousel_container(
        ig_user_id=IG_USER, children=[CHILD_A, CHILD_B]
    )
    assert container_id == CAROUSEL_CONTAINER


async def test_create_carousel_container_includes_caption_when_given() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return _json({"id": CAROUSEL_CONTAINER})

    await _client_with_transports(handler).create_carousel_container(
        ig_user_id=IG_USER, children=[CHILD_A, CHILD_B], caption="hola carrusel"
    )
    assert seen["caption"] == "hola carrusel"


async def test_create_carousel_container_omits_caption_when_not_given() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return _json({"id": CAROUSEL_CONTAINER})

    await _client_with_transports(handler).create_carousel_container(
        ig_user_id=IG_USER, children=[CHILD_A, CHILD_B]
    )
    assert "caption" not in seen


async def test_create_carousel_container_uses_the_bearer_scheme_on_graph() -> None:
    """Same host, same scheme as `create_container` (`content-publishing.md:84`) — a
    carousel container is created with the same `POST /<IG_ID>/media` endpoint."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return _json({"id": CAROUSEL_CONTAINER})

    await _client_with_transports(handler).create_carousel_container(
        ig_user_id=IG_USER, children=[CHILD_A]
    )
    assert seen["auth"] == f"{GRAPH_AUTH_SCHEME} {TOKEN}"


async def test_create_carousel_container_never_touches_upload_or_publish() -> None:
    """The point of this PR: children are already-uploaded containers, so grouping them
    must not trigger any `rupload` call (nothing to upload) nor a `media_publish` call
    (that stays a separate, later, explicit step). `_client_with_transports`'s rupload
    handler raises if it is ever invoked, so this test fails loudly if that changes."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert not request.url.path.endswith("media_publish")
        return _json({"id": CAROUSEL_CONTAINER})

    await _client_with_transports(handler).create_carousel_container(
        ig_user_id=IG_USER, children=[CHILD_A, CHILD_B]
    )
    assert calls == 1  # exactly the one POST that creates the carousel container


async def test_create_carousel_container_rejects_an_empty_children_list_before_any_request() -> (
    None
):
    """Mirrors `test_image_media_type_is_refused_before_any_request`: a structurally
    impossible request is refused locally, never sent."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no request should be made for an empty children list")

    with pytest.raises(PublishError, match="at least one child"):
        await _client_with_transports(handler).create_carousel_container(
            ig_user_id=IG_USER, children=[]
        )


async def test_create_carousel_container_without_an_id_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({})

    with pytest.raises(PublishError, match="carousel container response carried no id"):
        await _client_with_transports(handler).create_carousel_container(
            ig_user_id=IG_USER, children=[CHILD_A, CHILD_B]
        )


async def test_create_carousel_container_does_not_require_a_uri() -> None:
    """The finding this PR exists to encode: confirmed against Meta real (2026-09-10),
    the carousel container response never carries `uri` — unlike `create_container`,
    whose `_parse_container_response` would reject exactly this payload."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": CAROUSEL_CONTAINER})  # note: no "uri" key at all

    container_id = await _client_with_transports(handler).create_carousel_container(
        ig_user_id=IG_USER, children=[CHILD_A, CHILD_B]
    )
    assert container_id == CAROUSEL_CONTAINER


async def test_create_carousel_container_error_follows_the_existing_pattern() -> None:
    """Same posture as every other `_post_graph` caller: HTTP status + numeric platform
    code only, never the response body (which may echo request parameters), never the
    token."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 100, "message": TOKEN}})

    with pytest.raises(PublishError) as excinfo:
        await _client_with_transports(handler).create_carousel_container(
            ig_user_id=IG_USER, children=[CHILD_A, CHILD_B]
        )
    assert excinfo.value.platform_code == 100
    assert excinfo.value.http_status == 400
    assert TOKEN not in str(excinfo.value)


# --------------------------------------------------------------------------------------
# create_image_container (QUA-68)
# --------------------------------------------------------------------------------------

IMAGE_CONTAINER = "18800000000000000"


async def test_create_image_container_sends_image_url_not_upload_type() -> None:
    """The whole reason this is a separate method, not a `create_container` overload:
    `image_url`, no `upload_type`, no `media_type` — a structurally different request."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{IG_USER}/media")
        assert request.url.params["image_url"] == "https://qualify.example/public/media/tok-1"
        assert "upload_type" not in request.url.params
        assert "media_type" not in request.url.params
        return _json({"id": IMAGE_CONTAINER})

    container_id = await _client(handler).create_image_container(
        ig_user_id=IG_USER, image_url="https://qualify.example/public/media/tok-1"
    )
    assert container_id == IMAGE_CONTAINER


async def test_create_image_container_includes_caption_when_given() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return _json({"id": IMAGE_CONTAINER})

    await _client(handler).create_image_container(
        ig_user_id=IG_USER, image_url="https://x/y", caption="hola imagen"
    )
    assert seen["caption"] == "hola imagen"


async def test_create_image_container_omits_caption_when_not_given() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return _json({"id": IMAGE_CONTAINER})

    await _client(handler).create_image_container(ig_user_id=IG_USER, image_url="https://x/y")
    assert "caption" not in seen


async def test_create_image_container_never_touches_rupload() -> None:
    """Nothing is ever uploaded for an image container — Meta fetches `image_url` itself.
    Same posture `test_create_carousel_container_never_touches_upload_or_publish` already
    asserts for carousels, for the identical reason."""

    def refuse_rupload(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("rupload must never be called by create_image_container")

    def graph_handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": IMAGE_CONTAINER})

    container_id = await _client_with_transports(
        graph_handler, refuse_rupload
    ).create_image_container(ig_user_id=IG_USER, image_url="https://x/y")
    assert container_id == IMAGE_CONTAINER


async def test_create_image_container_uses_the_bearer_scheme_on_graph() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return _json({"id": IMAGE_CONTAINER})

    await _client(handler).create_image_container(ig_user_id=IG_USER, image_url="https://x/y")
    assert seen["auth"] == f"{GRAPH_AUTH_SCHEME} {TOKEN}"


async def test_create_image_container_does_not_require_a_uri() -> None:
    """Same finding as the carousel container's: `_parse_image_container_response` must
    accept a response with no `uri` — nothing is ever uploaded TO this container."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": IMAGE_CONTAINER})  # note: no "uri" key at all

    container_id = await _client(handler).create_image_container(
        ig_user_id=IG_USER, image_url="https://x/y"
    )
    assert container_id == IMAGE_CONTAINER


async def test_create_image_container_without_an_id_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({})

    with pytest.raises(PublishError, match="image container response carried no id"):
        await _client(handler).create_image_container(ig_user_id=IG_USER, image_url="https://x/y")


async def test_create_image_container_error_follows_the_existing_pattern() -> None:
    """Same posture as every other `_post_graph` caller: status + numeric platform code
    only, never the response body, never the token."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 100, "message": TOKEN}})

    with pytest.raises(PublishError) as excinfo:
        await _client(handler).create_image_container(ig_user_id=IG_USER, image_url="https://x/y")
    assert excinfo.value.platform_code == 100
    assert excinfo.value.http_status == 400
    assert TOKEN not in str(excinfo.value)


# --------------------------------------------------------------------------------------
# upload_bytes
# --------------------------------------------------------------------------------------


async def test_upload_uses_the_oauth_scheme_and_size_headers() -> None:
    """The trap this test exists for: `rupload` uses `Authorization: OAuth`, NOT `Bearer`
    (`resumable-uploads.md:92`). The two hosts genuinely differ."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({key.lower(): value for key, value in request.headers.items()})
        return _json({"success": True, "message": "Upload successful."})

    outcome = await _client(handler).upload_bytes(
        upload_uri=UPLOAD_URI, fileobj=io.BytesIO(b"video-bytes"), file_size=11
    )
    assert outcome.success
    assert seen["authorization"] == f"{RUPLOAD_AUTH_SCHEME} {TOKEN}"
    assert seen["offset"] == "0"
    assert seen["file_size"] == "11"


async def test_upload_posts_to_the_uri_meta_supplied_verbatim() -> None:
    """The uri is used as given, not rebuilt from a template — it carries an API version."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return _json({"success": True})

    await _client(handler).upload_bytes(
        upload_uri=UPLOAD_URI, fileobj=io.BytesIO(b"x"), file_size=1
    )
    assert seen["url"] == UPLOAD_URI


async def test_upload_sends_a_sized_body_not_a_chunked_stream() -> None:
    """REVERSED from the original streaming assertion, on measurement (2026-08-07, live
    `rupload`): a chunked body — Transfer-Encoding, no Content-Length — is refused with a
    non-retriable `ParameterValidationError`, and the identical bytes sent sized succeed.
    The old test froze the memory argument into the suite; reality voted the other way.
    The buffer is bounded by the gate's `MAX_MEDIA_BYTES` ceiling upstream.
    """
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({key.lower(): value for key, value in request.headers.items()})
        return _json({"success": True})

    payload = b"a" * 4096
    await _client(handler).upload_bytes(
        upload_uri=UPLOAD_URI, fileobj=io.BytesIO(payload), file_size=len(payload)
    )

    assert seen.get("content-length") == str(len(payload))
    assert "transfer-encoding" not in seen


async def test_upload_sends_every_byte_it_was_given() -> None:
    """Buffering must not lose or reorder the tail — the failure mode would be a container
    that processes and then errors much later, far from its cause."""
    payload = b"".join(bytes([i % 256]) for i in range(65536 + 1234))
    seen: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return _json({"success": True})

    await _client(handler).upload_bytes(
        upload_uri=UPLOAD_URI, fileobj=io.BytesIO(payload), file_size=len(payload)
    )
    assert seen["body"] == payload


async def test_upload_failure_surfaces_metas_retriable_flag() -> None:
    """ADR 22(e) bans blind retries. `debug_info.retriable` is Meta's own judgement and is
    what makes the ban implementable — a timeout cannot tell a blip from poison."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "debug_info": {
                    "retriable": False,
                    "type": "ProcessingFailedError",
                    "message": '{"success":false}',
                }
            }
        )

    outcome = await _client(handler).upload_bytes(
        upload_uri=UPLOAD_URI, fileobj=io.BytesIO(b"x"), file_size=1
    )
    assert outcome.success is False
    assert outcome.retriable is False
    assert outcome.error_type == "ProcessingFailedError"


async def test_upload_failure_does_not_surface_metas_error_message() -> None:
    """`debug_info.message` embeds a nested JSON error string from an auth-bearing call. It is
    parsed past, never carried, so it cannot reach a log."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"debug_info": {"retriable": True, "type": "X", "message": TOKEN}})

    outcome = await _client(handler).upload_bytes(
        upload_uri=UPLOAD_URI, fileobj=io.BytesIO(b"x"), file_size=1
    )
    assert TOKEN not in repr(outcome)


def test_absent_retriable_is_unknown_not_false() -> None:
    """R10 applied to a flag: 'Meta said nothing' is not 'Meta said no'. Collapsing them would
    turn a recoverable failure into a permanently abandoned one."""
    outcome = _parse_upload_response({"debug_info": {"type": "Weird"}})
    assert outcome.success is False
    assert outcome.retriable is None


def test_unrecognised_upload_response_is_unknown_not_non_retriable() -> None:
    outcome = _parse_upload_response({"something": "else"})
    assert outcome.success is False
    assert outcome.retriable is None


async def test_non_json_upload_response_is_unknown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    outcome = await _client(handler).upload_bytes(
        upload_uri=UPLOAD_URI, fileobj=io.BytesIO(b"x"), file_size=1
    )
    assert outcome.success is False
    assert outcome.retriable is None
    assert outcome.error_type == "http_502"


# --------------------------------------------------------------------------------------
# container_status
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["EXPIRED", "ERROR", "FINISHED", "IN_PROGRESS", "PUBLISHED"])
async def test_all_five_documented_statuses_parse(raw: str) -> None:
    """`content-publishing.md:318-322` lists exactly five."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["fields"] == "status_code"
        return _json({"status_code": raw, "id": CONTAINER})

    assert await _client(handler).container_status(container_id=CONTAINER) == ContainerStatus(raw)


async def test_unknown_status_raises_rather_than_being_coerced() -> None:
    """If Meta adds a sixth value it must fail loudly. Reading it as IN_PROGRESS would make
    the poller wait out its ceiling; reading it as ERROR would abandon a live publish."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"status_code": "SOMETHING_NEW"})

    with pytest.raises(PublishError, match="unknown container status_code"):
        await _client(handler).container_status(container_id=CONTAINER)


def test_terminal_statuses_are_exactly_the_three_that_end_the_poll() -> None:
    terminal = {status for status in ContainerStatus if status.is_terminal}
    assert terminal == {
        ContainerStatus.EXPIRED,
        ContainerStatus.ERROR,
        ContainerStatus.PUBLISHED,
    }
    # FINISHED is deliberately NOT terminal: it means "ready to publish", so the work
    # continues rather than stopping.
    assert not ContainerStatus.FINISHED.is_terminal


# --------------------------------------------------------------------------------------
# publish_container + the ambiguity reconciliation exists for
# --------------------------------------------------------------------------------------


async def test_publish_returns_the_media_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{IG_USER}/media_publish")
        assert request.url.params["creation_id"] == CONTAINER
        return _json({"id": "17900000000000000"})

    media_id = await _client(handler).publish_container(ig_user_id=IG_USER, creation_id=CONTAINER)
    assert media_id == "17900000000000000"


async def test_publish_without_a_media_id_raises_so_the_caller_reconciles() -> None:
    """`content-publishing.md:316` documents this exact case: media_publish may not return
    the id. Raising is correct — the service reconciles by `creation_id` instead of retrying,
    which is what ADR 22(e) requires."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({})

    with pytest.raises(PublishError, match="no media id"):
        await _client(handler).publish_container(ig_user_id=IG_USER, creation_id=CONTAINER)


async def test_error_messages_never_carry_the_token_or_the_body() -> None:
    """A failed publish body routinely echoes request parameters, and this call is
    token-bearing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": TOKEN}})

    with pytest.raises(PublishError) as excinfo:
        await _client(handler).publish_container(ig_user_id=IG_USER, creation_id=CONTAINER)
    assert TOKEN not in str(excinfo.value)
    assert "400" in str(excinfo.value)


# --------------------------------------------------------------------------------------
# pinned constants
# --------------------------------------------------------------------------------------


def test_polling_cadence_matches_metas_documented_recommendation() -> None:
    """`content-publishing.md:324`: once per minute, no more than 5 minutes. Pinned as
    constants so nobody invents a tighter loop that just burns the 200 calls/hour budget."""
    assert CONTAINER_POLL_INTERVAL_SECONDS == 60
    assert CONTAINER_POLL_CEILING_SECONDS == 300
    assert CONTAINER_POLL_CEILING_SECONDS // CONTAINER_POLL_INTERVAL_SECONDS == 5


def test_the_two_auth_schemes_are_different() -> None:
    """If these ever collapse to one value, the distinction the corpus documents has been
    lost by an edit rather than by a decision. They live on settings (R12), not as literals
    in the client — so this asserts against the settings defaults."""
    assert GRAPH_AUTH_SCHEME != RUPLOAD_AUTH_SCHEME
    assert (GRAPH_AUTH_SCHEME, RUPLOAD_AUTH_SCHEME) == ("Bearer", "OAuth")


def test_the_schemes_are_env_overridable_without_a_code_change() -> None:
    """One live call may settle R12. When it does, the fix must be configuration, not a
    redeploy of edited literals."""
    import os
    from unittest import mock

    with mock.patch.dict(
        os.environ,
        {
            "QUALIFY_META_GRAPH_AUTH_SCHEME": "OAuth",
            "QUALIFY_META_RUPLOAD_AUTH_SCHEME": "OAuth",
        },
    ):
        settings = MetaOAuthSettings.from_env()
    assert settings.graph_auth_scheme == "OAuth"
    assert settings.rupload_auth_scheme == "OAuth"


async def test_publish_client_holds_no_token_attribute() -> None:
    """The point of taking authenticated clients: there is no token in this object to leak."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": CONTAINER, "uri": UPLOAD_URI})

    client = _client(handler)
    assert TOKEN not in repr(client)
    assert not any(TOKEN == getattr(client, name, None) for name in vars(client))


def test_image_is_not_a_resumable_media_type() -> None:
    """The scope boundary of ADR 28, asserted: image has no byte-upload path at all."""
    assert RESUMABLE_MEDIA_TYPES == {"REELS", "STORIES", "VIDEO"}
    assert "IMAGE" not in RESUMABLE_MEDIA_TYPES
