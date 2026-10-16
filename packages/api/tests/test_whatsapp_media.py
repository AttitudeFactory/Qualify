"""0061 — inbound WhatsApp media: the handler's projection, the capturing locator, and the
media route end to end.

Fully offline: `MemoryChatRepository` (which also implements the locator's
`MediaRecordRepository`), a scripted fake `WhatsAppClient`, an in-memory R2 sink and a
recording public-media linker. The Postgres half (`PostgresMediaRecordRepository` + the
0061 columns + RLS) is `test_whatsapp_media_db.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import IO
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from qualify_shared.objects.keys import TenantPrefixViolation, require_tenant_prefix
from qualify_shared.social.wa_shapes import WAMessage

from qualify_api.http import deps, whatsapp_routes
from qualify_api.http.app import create_app
from qualify_api.whatsapp.chats import (
    ChatService,
    MediaExpired,
    MediaMessageNotFound,
    MediaNotCaptured,
    MediaUnavailable,
    MemoryChatRepository,
)
from qualify_api.whatsapp.client import MediaInfo, WhatsAppApiError
from qualify_api.whatsapp.handler import message_media, message_text
from qualify_api.whatsapp.media import CapturingMediaLocator, inbound_media_key
from qualify_api.whatsapp.outbox import MemoryOutboxRepository

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
TENANT_A = UUID("a1000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("b1000000-0000-4000-8000-00000000000b")
USER_A = UUID("a2000000-0000-4000-8000-00000000000a")
USER_B = UUID("b2000000-0000-4000-8000-00000000000b")
CONN_A = UUID("a4000000-0000-4000-8000-00000000000a")
CONN_B = UUID("b4000000-0000-4000-8000-00000000000b")
WA_ID = "573001234567"
MEDIA_ID = "1122334455"
AUTH_A = {"Authorization": "Bearer token-a"}


# ======================================================================================
# Fakes
# ======================================================================================


class FakeMediaClient:
    """`media_url` + `download_media`, scripted. Records the calls (never the URL)."""

    def __init__(
        self,
        *,
        content: bytes = b"bytes",
        mime: str | None = "image/jpeg",
        url_error: WhatsAppApiError | None = None,
        download_error: WhatsAppApiError | None = None,
    ) -> None:
        self.content = content
        self.mime = mime
        self.url_error = url_error
        self.download_error = download_error
        self.calls: list[str] = []
        self.closed = 0

    async def media_url(self, media_id: str) -> MediaInfo:
        self.calls.append(f"media_url:{media_id}")
        if self.url_error is not None:
            raise self.url_error
        return MediaInfo(
            id=media_id,
            url="https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1",
            mime_type=self.mime,
            sha256=None,
            file_size=len(self.content),
        )

    async def download_media(self, url: str) -> bytes:
        self.calls.append("download")
        if self.download_error is not None:
            raise self.download_error
        return self.content

    async def aclose(self) -> None:
        self.closed += 1


class MemorySink:
    """`ObjectGate.put_media`'s contract, prefix check included."""

    def __init__(self, *, fail: bool = False) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail = fail

    def put_media(
        self, tenant_id: UUID, object_key: str, fileobj: IO[bytes], content_type: str
    ) -> None:
        require_tenant_prefix(tenant_id, object_key)
        if self.fail:
            raise OSError("r2 down")
        self.objects[object_key] = (fileobj.read(), content_type)


class RecordingLinker:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, str]] = []

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        self.calls.append((tenant_id, object_key, content_type))
        return f"https://public.example/public/media/token-{len(self.calls)}"


class Rig:
    def __init__(self, client: FakeMediaClient | None = None, *, sink_fails: bool = False):
        self.repo = MemoryChatRepository()
        self.client = client or FakeMediaClient()
        self.sink = MemorySink(fail=sink_fails)
        self.linker = RecordingLinker()
        self.factory_calls: list[tuple[UUID, UUID]] = []
        self.locator = CapturingMediaLocator(self.repo, self.sink, self._factory, self.linker)

    async def _factory(self, *, tenant_id: UUID, connection_id: UUID) -> FakeMediaClient:
        self.factory_calls.append((tenant_id, connection_id))
        return self.client

    def message(
        self,
        *,
        tenant_id: UUID = TENANT_A,
        connection_id: UUID = CONN_A,
        direction: str = "inbound",
        media_kind: str | None = "image",
        media_id: str | None = MEDIA_ID,
        media_mime: str | None = "image/jpeg",
    ) -> UUID:
        thread_id = self.repo.add_thread(
            tenant_id=tenant_id, connection_id=connection_id, wa_id=WA_ID
        )
        return self.repo.add_message(
            thread_id=thread_id,
            direction=direction,
            text_value=None,
            posted_at=NOW - timedelta(minutes=5),
            media_kind=media_kind,
            media_id=media_id,
            media_mime=media_mime,
        )


def _key(tenant_id: UUID = TENANT_A, connection_id: UUID = CONN_A) -> str:
    return f"t/{tenant_id}/fp/whatsapp/{connection_id}/media/{MEDIA_ID}"


# ======================================================================================
# The handler's projection (what WA-07 now writes)
# ======================================================================================


def _wa(payload: dict) -> WAMessage:
    return WAMessage.model_validate(
        {"id": "wamid.X", "from": WA_ID, "timestamp": "1760450000", **payload}
    )


def test_an_image_with_caption_keeps_id_mime_and_caption() -> None:
    message = _wa(
        {
            "type": "image",
            "image": {
                "id": MEDIA_ID,
                "mime_type": "image/jpeg",
                "sha256": "abc=",
                "caption": "mira el pedido",
            },
        }
    )
    media = message_media(message)
    assert (media.media_type, media.media_id, media.media_mime) == (
        "image",
        MEDIA_ID,
        "image/jpeg",
    )
    assert message_text(message) == "mira el pedido"


def test_a_voice_note_has_no_caption() -> None:
    message = _wa(
        {"type": "audio", "audio": {"id": MEDIA_ID, "mime_type": "audio/ogg; codecs=opus"}}
    )
    assert message_media(message).media_mime == "audio/ogg; codecs=opus"
    assert message_text(message) is None


def test_a_document_keeps_its_filename_in_the_shape() -> None:
    message = _wa(
        {
            "type": "document",
            "document": {"id": MEDIA_ID, "mime_type": "application/pdf", "filename": "menu.pdf"},
        }
    )
    assert message.media is not None and message.media.filename == "menu.pdf"
    assert message_media(message).media_type == "document"


def test_a_location_has_a_type_but_no_media_id() -> None:
    message = _wa({"type": "location", "location": {"latitude": 4.6, "longitude": -74.1}})
    media = message_media(message)
    assert (media.media_type, media.media_id, media.media_mime) == ("location", None, None)


@pytest.mark.parametrize("unknown", ["reaction", "system", "unsupported", "nfm_whatever"])
def test_an_unknown_type_is_other_never_a_check_violation(unknown: str) -> None:
    assert message_media(_wa({"type": unknown})).media_type == "other"


def test_a_text_has_no_media_type() -> None:
    media = message_media(_wa({"type": "text", "text": {"body": "hola"}}))
    assert (media.media_type, media.media_id) == (None, None)


def test_an_image_whose_object_meta_left_out_still_names_its_type() -> None:
    media = message_media(_wa({"type": "image"}))
    assert (media.media_type, media.media_id) == ("image", None)


# ======================================================================================
# The R2 key
# ======================================================================================


def test_the_key_sits_under_the_tenant_first_party_prefix() -> None:
    key = inbound_media_key(TENANT_A, CONN_A, MEDIA_ID)
    assert key == _key()
    assert require_tenant_prefix(TENANT_A, key) == key
    with pytest.raises(TenantPrefixViolation):
        require_tenant_prefix(TENANT_B, key)


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "x" * 201, "id with space"])
def test_an_unsafe_media_id_never_becomes_a_key(bad: str) -> None:
    with pytest.raises(ValueError):
        inbound_media_key(TENANT_A, CONN_A, bad)


# ======================================================================================
# The locator
# ======================================================================================


async def test_first_request_downloads_stores_and_links() -> None:
    rig = Rig(FakeMediaClient(content=b"\xff\xd8jpeg"))
    message_id = rig.message()

    url = await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)

    assert url == "https://public.example/public/media/token-1"
    assert rig.client.calls == [f"media_url:{MEDIA_ID}", "download"]
    assert rig.sink.objects == {_key(): (b"\xff\xd8jpeg", "image/jpeg")}
    assert rig.linker.calls == [(TENANT_A, _key(), "image/jpeg")]
    assert rig.factory_calls == [(TENANT_A, CONN_A)]
    assert rig.client.closed == 1
    assert rig.repo.get_media(tenant_id=TENANT_A, message_id=message_id).media_object_key == _key()


async def test_later_requests_skip_meta() -> None:
    rig = Rig()
    message_id = rig.message()
    await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)
    await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)
    assert rig.client.calls == [f"media_url:{MEDIA_ID}", "download"]
    assert len(rig.factory_calls) == 1
    assert len(rig.linker.calls) == 2  # a fresh token per view


async def test_meta_mime_is_the_fallback_when_the_webhook_had_none() -> None:
    rig = Rig(FakeMediaClient(mime="video/mp4"))
    message_id = rig.message(media_kind="video", media_mime=None)
    await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)
    assert rig.sink.objects[_key()][1] == "video/mp4"


async def test_unknown_message_is_not_found() -> None:
    rig = Rig()
    with pytest.raises(MediaMessageNotFound):
        await rig.locator.locate(tenant_id=TENANT_A, message_id=uuid4())


async def test_another_tenants_message_is_not_found_and_meta_is_not_called() -> None:
    rig = Rig()
    message_id = rig.message(tenant_id=TENANT_B, connection_id=CONN_B)
    with pytest.raises(MediaMessageNotFound):
        await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)
    assert rig.client.calls == [] and rig.factory_calls == []


@pytest.mark.parametrize(
    ("direction", "media_kind", "media_id"),
    [
        ("inbound", "location", None),  # a type without bytes
        ("inbound", None, None),  # a text, or a row stored before 0061
        ("outbound", "image", MEDIA_ID),  # we sent it; not re-served here
    ],
)
async def test_messages_without_downloadable_media_are_not_captured(
    direction: str, media_kind: str | None, media_id: str | None
) -> None:
    rig = Rig()
    message_id = rig.message(direction=direction, media_kind=media_kind, media_id=media_id)
    with pytest.raises(MediaNotCaptured):
        await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)
    assert rig.client.calls == []


@pytest.mark.parametrize(
    ("url_error", "download_error"),
    [
        (WhatsAppApiError("gone", status=404), None),
        (WhatsAppApiError("gone", status=400, code=100), None),
        (None, WhatsAppApiError("gone", status=404)),
    ],
)
async def test_media_meta_no_longer_holds_is_expired(
    url_error: WhatsAppApiError | None, download_error: WhatsAppApiError | None
) -> None:
    rig = Rig(FakeMediaClient(url_error=url_error, download_error=download_error))
    message_id = rig.message()
    with pytest.raises(MediaExpired):
        await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)
    assert rig.sink.objects == {}
    assert rig.client.closed == 1
    assert rig.repo.get_media(tenant_id=TENANT_A, message_id=message_id).media_object_key is None


@pytest.mark.parametrize(
    "error",
    [
        WhatsAppApiError("timeout", is_transport=True),
        WhatsAppApiError("boom", status=500),
        WhatsAppApiError("auth", status=401, code=190),
        WhatsAppApiError("throttled", status=400, code=4),
    ],
)
async def test_retryable_or_operator_failures_are_unavailable(error: WhatsAppApiError) -> None:
    rig = Rig(FakeMediaClient(url_error=error))
    message_id = rig.message()
    with pytest.raises(MediaUnavailable):
        await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)


async def test_an_r2_failure_is_unavailable_and_leaves_the_key_unset() -> None:
    rig = Rig(sink_fails=True)
    message_id = rig.message()
    with pytest.raises(MediaUnavailable):
        await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)
    assert rig.repo.get_media(tenant_id=TENANT_A, message_id=message_id).media_object_key is None


async def test_no_client_for_the_connection_is_unavailable() -> None:
    rig = Rig()

    async def broken(*, tenant_id: UUID, connection_id: UUID) -> FakeMediaClient:
        raise LookupError("no phone number")

    rig.locator = CapturingMediaLocator(rig.repo, rig.sink, broken, rig.linker)
    message_id = rig.message()
    with pytest.raises(MediaUnavailable):
        await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)


async def test_a_linker_failure_is_unavailable() -> None:
    class BrokenLinker:
        def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
            raise ConnectionError("redis down")

    rig = Rig()
    rig.locator = CapturingMediaLocator(rig.repo, rig.sink, rig._factory, BrokenLinker())
    message_id = rig.message()
    with pytest.raises(MediaUnavailable):
        await rig.locator.locate(tenant_id=TENANT_A, message_id=message_id)
    # The capture itself landed: the next view will not hit Meta again.
    assert rig.repo.get_media(tenant_id=TENANT_A, message_id=message_id).media_object_key == _key()


# ======================================================================================
# The route, end to end with the real locator
# ======================================================================================


@pytest.fixture
def http_rig(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Rig]:
    monkeypatch.setenv(
        "QUALIFY_DEV_PRINCIPALS", f"token-a:{TENANT_A}:{USER_A},token-b:{TENANT_B}:{USER_B}"
    )
    rig = Rig(FakeMediaClient(content=b"\xff\xd8jpeg"))
    service = ChatService(rig.repo, MemoryOutboxRepository(clock=lambda: NOW), clock=lambda: NOW)
    app = create_app(configure_production=False)
    app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
    app.dependency_overrides[whatsapp_routes.get_chat_service] = lambda: service
    app.dependency_overrides[whatsapp_routes.get_media_locator] = lambda: rig.locator
    return TestClient(app), rig


def test_route_307s_to_the_public_media_url_and_captures_once(
    http_rig: tuple[TestClient, Rig],
) -> None:
    http, rig = http_rig
    message_id = rig.message()
    first = http.get(f"/api/whatsapp/media/{message_id}", headers=AUTH_A, follow_redirects=False)
    second = http.get(f"/api/whatsapp/media/{message_id}", headers=AUTH_A, follow_redirects=False)
    assert (first.status_code, second.status_code) == (307, 307)
    assert first.headers["location"] == "https://public.example/public/media/token-1"
    assert second.headers["location"] == "https://public.example/public/media/token-2"
    assert rig.client.calls == [f"media_url:{MEDIA_ID}", "download"]


def test_route_answers_410_when_meta_no_longer_holds_it(
    http_rig: tuple[TestClient, Rig],
) -> None:
    http, rig = http_rig
    rig.client.download_error = WhatsAppApiError("gone", status=404)
    message_id = rig.message()
    response = http.get(f"/api/whatsapp/media/{message_id}", headers=AUTH_A)
    assert response.status_code == 410
    assert response.json()["detail"] == {"code": "media_expired"}


def test_route_answers_404_for_another_tenants_message(
    http_rig: tuple[TestClient, Rig],
) -> None:
    http, rig = http_rig
    message_id = rig.message(tenant_id=TENANT_B, connection_id=CONN_B)
    response = http.get(f"/api/whatsapp/media/{message_id}", headers=AUTH_A)
    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "message_not_found"}
    assert rig.client.calls == []


def test_route_requires_a_principal(http_rig: tuple[TestClient, Rig]) -> None:
    http, rig = http_rig
    message_id = rig.message()
    assert http.get(f"/api/whatsapp/media/{message_id}").status_code == 401
