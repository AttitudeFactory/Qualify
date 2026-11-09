"""Offline tests for the read-only Pinterest boundary, never live credentials."""

import httpx
import pytest

from qualify_api.pinterest.client import (
    Board,
    FakePinterestClient,
    Page,
    Pin,
    PinterestClient,
    PinterestError,
    PinterestReader,
    Profile,
)


def test_reads_fixed_host_with_encoded_cursor_and_explicit_credential() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.pinterest.com"
        assert request.headers["authorization"] == "Bearer test-secret"
        if len(requests) == 1:
            assert request.url.path == "/v5/boards"
            assert request.url.params == httpx.QueryParams(page_size=1)
            return httpx.Response(
                200, json={"items": [{"id": "12", "name": "Ideas"}], "bookmark": "a&b=1"}
            )
        assert request.url.params["bookmark"] == "a&b=1"
        assert set(request.url.params) == {"bookmark", "page_size"}
        return httpx.Response(200, json={"items": [], "bookmark": None})

    client = PinterestClient("test-secret", transport=httpx.MockTransport(handler))
    first = client.boards(page_size=1)
    assert first == Page((Board("12", "Ideas"),), "a&b=1")
    assert client.boards(page_size=1, bookmark=first.bookmark) == Page(())
    assert "test-secret" not in repr(client)


def test_pin_variants_and_nonimage_media_are_ephemeral_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v5/boards/12/pins"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "1",
                        "title": None,
                        "media": {
                            "media_type": "image",
                            "images": {
                                "600x": {"url": "https://i.pinimg.com/example.jpg"},
                                "1200x": {"url": "http://unsafe.example/image"},
                                "150x150": None,
                            },
                        },
                    },
                    {"id": "2", "media": {"media_type": "video", "images": None}},
                    {"id": "3", "media": {"media_type": "multiple_mixed", "items": []}},
                    {"id": "4", "media": None},
                ]
            },
        )

    page = PinterestClient("test", transport=httpx.MockTransport(handler)).pins("12")
    assert page.items[0].url == "https://www.pinterest.com/pin/1/"
    assert page.items[0].title == ""
    assert [image.variant for image in page.items[0].images] == ["600x"]
    assert [pin.images for pin in page.items[1:]] == [(), (), ()]


@pytest.mark.parametrize(
    "status,kind",
    [
        (401, "authentication"),
        (403, "permission"),
        (404, "not_found"),
        (429, "rate_limit"),
        (503, "unavailable"),
        (400, "request"),
        (302, "request"),
    ],
)
def test_errors_never_expose_vendor_body_or_follow_redirect(status: int, kind: str) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            status, json={"message": "test-secret"}, headers={"location": "https://evil.example/"}
        )

    with pytest.raises(PinterestError) as error:
        PinterestClient("test-secret", transport=httpx.MockTransport(handler)).boards()
    assert error.value.kind == kind
    assert error.value.status == status
    assert "test-secret" not in str(error.value)
    assert error.value.__context__ is None
    assert len(calls) == 1


def test_transport_error_has_no_credential_bearing_exception_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test-secret", request=request)

    with pytest.raises(PinterestError, match="unavailable") as error:
        PinterestClient("test-secret", transport=httpx.MockTransport(handler)).boards()
    assert error.value.__context__ is None
    assert "test-secret" not in repr(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"items": None},
        {"items": [None]},
        {"items": [{"id": "../escape", "name": "bad"}]},
        {"items": [], "bookmark": 123},
        {"items": [], "bookmark": "\n"},
        {"items": [{"id": "1", "name": 12}]},
    ],
)
def test_invalid_board_responses_are_sanitized(payload: object) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    with pytest.raises(PinterestError, match="invalid_response"):
        PinterestClient("test", transport=transport).boards()


@pytest.mark.parametrize("media", [[], "bad", {"images": []}, {"media_type": 23}])
def test_invalid_pin_responses_are_sanitized(media: object) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"items": [{"id": "1", "media": media}]})
    )
    with pytest.raises(PinterestError, match="invalid_response"):
        PinterestClient("test", transport=transport).pins("12")


def test_non_json_response_is_sanitized() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text="test-secret"))
    with pytest.raises(PinterestError, match="invalid_response"):
        PinterestClient("test-secret", transport=transport).boards()


def test_profile_is_optional_and_separate_from_board_reads() -> None:
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"username": "fixture"})

    assert PinterestClient("test", transport=httpx.MockTransport(handler)).profile() == Profile(
        "fixture"
    )
    assert paths == ["/v5/user_account"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page_size": 0},
        {"page_size": 251},
        {"page_size": True},
        {"bookmark": ""},
        {"bookmark": "\n"},
        {"bookmark": "x" * 4097},
    ],
)
def test_pagination_validation_matches_fake_before_any_request(kwargs: dict) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid input must not send a request")

    for client in (
        PinterestClient("test", transport=httpx.MockTransport(handler)),
        FakePinterestClient(),
    ):
        with pytest.raises(ValueError):
            client.boards(**kwargs)


@pytest.mark.parametrize("board_id", ["../user_account", "1?bookmark=x", "", "１２", 12])
def test_board_id_rejects_path_injection(board_id: object) -> None:
    for client in (PinterestClient("test"), FakePinterestClient()):
        with pytest.raises(ValueError):
            client.pins(board_id)


def test_fake_paginates_resource_scoped_fixture_without_global_state() -> None:
    fake: PinterestReader = FakePinterestClient(
        boards=(Board("1", "One"), Board("2", "Two")), pins={"1": (Pin("10"), Pin("11"))}
    )
    first = fake.boards(page_size=1)
    assert first.items == (Board("1", "One"),)
    assert fake.boards(page_size=1, bookmark=first.bookmark).items == (Board("2", "Two"),)
    pins = fake.pins("1", page_size=1)
    assert fake.pins("1", page_size=1, bookmark=pins.bookmark).items == (Pin("11"),)
    with pytest.raises(PinterestError, match="request"):
        fake.pins("1", bookmark=first.bookmark)
    other = FakePinterestClient(boards=(Board("1", "One"),))
    with pytest.raises(PinterestError, match="request"):
        other.boards(bookmark=first.bookmark)
    with pytest.raises(PinterestError, match="not_found"):
        fake.pins("3")


@pytest.mark.parametrize("token", ["", " ", "with space", "line\nfeed", "á"])
def test_invalid_token_is_rejected_without_exposing_it(token: str) -> None:
    with pytest.raises(ValueError):
        PinterestClient(token)
