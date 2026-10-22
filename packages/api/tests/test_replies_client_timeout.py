"""The public reply to a comment waits long enough for Meta (m-24789646, R4).

Measured live on 2026-10-22: `POST /{comment-id}/replies` answered after httpx's default
5 s, and the reply had been published — so a 5 s client turned a success into an
ambiguous failure (the public notice of Fase C recorded `notice_ambiguous` for a notice
that was visible on Instagram). The client must send its own, longer timeout.
"""

from __future__ import annotations

import httpx

from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.replies.client import REPLY_TIMEOUT, HttpCommentReplyClient


async def test_the_reply_is_posted_with_a_long_read_timeout() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "17913205365515196"})

    graph = _InjectedAuthClient("t", scheme="Bearer", transport=httpx.MockTransport(handler))
    client = HttpCommentReplyClient(graph_client=graph, graph_url="https://graph.test/v21.0")
    reply_id = await client.post_reply(ig_comment_id="1789", message="Te enviamos la info por DM")

    assert reply_id == "17913205365515196"
    [request] = seen
    timeout = request.extensions["timeout"]
    assert timeout["read"] == REPLY_TIMEOUT.read >= 60.0
    assert timeout["connect"] == REPLY_TIMEOUT.connect
