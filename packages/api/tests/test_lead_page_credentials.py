"""The principal USER grant never becomes a Page grant in storage or UI."""

from __future__ import annotations

import httpx
import pytest

from qualify_api.connections import resolver
from qualify_api.connections.credential_reader import CredentialNotFound


@pytest.mark.asyncio
async def test_page_token_is_only_used_for_exact_matched_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/me/accounts"):
            assert request.headers["Authorization"] == "OAuth synthetic-user"
            if "after" not in request.url.params:
                return httpx.Response(
                    200,
                    json={
                        "data": [{"id": "100", "access_token": "foreign-page"}],
                        "paging": {"cursors": {"after": "cursor"}, "next": "https://evil.invalid"},
                    },
                )
            return httpx.Response(
                200, json={"data": [{"id": "200", "access_token": "synthetic-page"}]}
            )
        assert request.headers["Authorization"] == "OAuth synthetic-page"
        return httpx.Response(200, json={"id": "200"})

    transport = httpx.MockTransport(handle)
    builder = resolver.build_authenticated_client
    monkeypatch.setattr(
        resolver,
        "build_authenticated_client",
        lambda token, *, scheme: builder(token, scheme=scheme, transport=transport),
    )
    user = builder("synthetic-user", scheme="OAuth", transport=transport)
    page = await resolver.derive_page_client(
        user, page_id="200", graph_url="https://graph.facebook.com/v26.0", scheme="OAuth"
    )
    assert "synthetic-page" not in repr(page) and "synthetic-user" not in repr(user)
    await page.get("https://graph.facebook.com/v26.0/200")
    await page.aclose()
    await user.aclose()
    assert all(request.url.host == "graph.facebook.com" for request in requests)
    assert len(requests) == 3
    assert all(
        "synthetic-user" not in str(request.url) and "synthetic-page" not in str(request.url)
        for request in requests
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"data": [{"id": "100", "access_token": "foreign"}]},
        {"data": [{"id": "200"}]},
        {"data": [{"id": "200", "access_token": "bad token"}]},
        {"data": [{"id": "200", "access_token": "one"}, {"id": "200", "access_token": "two"}]},
        {"data": [], "paging": {"next": "https://evil.invalid", "cursors": {"after": "../token"}}},
        {"error": {"message": "sensitive provider message"}},
    ],
)
async def test_wrong_page_missing_token_or_bad_pagination_fails_without_leak(payload: dict) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    with pytest.raises(CredentialNotFound, match="^page credential unavailable$"):
        await resolver.derive_page_client(
            client, page_id="200", graph_url="https://graph.facebook.com/v26.0", scheme="OAuth"
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_repeated_credential_cursor_is_bounded() -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [],
                "paging": {"next": "https://evil.invalid", "cursors": {"after": "same"}},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with pytest.raises(CredentialNotFound):
        await resolver.derive_page_client(
            client, page_id="200", graph_url="https://graph.facebook.com/v26.0", scheme="OAuth"
        )
    await client.aclose()
    assert len(requests) == 2
