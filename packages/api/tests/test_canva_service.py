"""The Canva round trip's orchestration, with an in-memory repository and a fake Canva
client (the real client is covered against a mock transport in `qualify_creative`)."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.adapters.canva_connect import (
    CanvaDesign,
    CanvaJobFailed,
    CanvaTokens,
)

from qualify_api.canva.repository import InMemoryCanvaRepository, MediaRef
from qualify_api.canva.service import (
    CanvaConfig,
    CanvaNotConnected,
    CanvaService,
    NothingToSend,
    UnknownReturn,
)
from qualify_api.connections.crypto import DevEncryptor

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
OTHER_TENANT = UUID("a0000000-0000-4000-8000-000000000002")
USER = UUID("c0000000-0000-4000-8000-000000000001")
DRAFT = UUID("d0000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


class FakeCanva:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.refresh_fails = False
        self.export_fails = False
        self.refresh_count = 0

    def _tokens(self, n: int) -> CanvaTokens:
        return CanvaTokens(
            access_token=f"at{n}",
            refresh_token=f"rt{n}",
            expires_at=NOW + timedelta(hours=4),
            scope="asset:write",
        )

    def exchange_code(self, **kw: Any) -> CanvaTokens:
        self.calls.append(("exchange_code", kw))
        return self._tokens(0)

    def refresh(self, **kw: Any) -> CanvaTokens:
        self.calls.append(("refresh", kw))
        if self.refresh_fails:
            raise CanvaJobFailed("r", "invalid_grant", "spent")
        self.refresh_count += 1
        return self._tokens(self.refresh_count)

    def upload_asset(self, **kw: Any) -> str:
        self.calls.append(("upload_asset", kw))
        return "A1"

    def create_design(self, **kw: Any) -> CanvaDesign:
        self.calls.append(("create_design", kw))
        return CanvaDesign("D1", "https://www.canva.com/design/D1/edit", "https://v", 100)

    def get_design(self, **kw: Any) -> CanvaDesign:
        self.calls.append(("get_design", kw))
        return CanvaDesign("D1", "https://www.canva.com/design/D1/edit", "https://v", 200)

    def export_design(self, **kw: Any) -> list[str]:
        self.calls.append(("export_design", kw))
        if self.export_fails:
            raise CanvaJobFailed("E1", "license_required", "premium element")
        return ["https://dl/1"]

    def download(self, url: str) -> bytes:
        self.calls.append(("download", {"url": url}))
        return b"edited-bytes"

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class MemoryStore:
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = dict(files or {})

    def read(self, key: str) -> bytes:
        return self.files[key]

    def write(self, key: str, data: bytes) -> None:
        self.files[key] = data


def _service(
    media: list[MediaRef] | None = None, *, connected: bool = True
) -> tuple[CanvaService, FakeCanva, InMemoryCanvaRepository, MemoryStore]:
    repo = InMemoryCanvaRepository()
    canva = FakeCanva()
    store = MemoryStore({"generated/t/d/image.png": b"png", "generated/t/d/video.mp4": b"mp4"})
    if media is not None:
        repo.media[(TENANT, DRAFT)] = media
    service = CanvaService(
        config=CanvaConfig("cid", "secret", "http://127.0.0.1:3000/canva/callback"),
        repository=repo,
        client=canva,  # type: ignore[arg-type]
        encryptor=DevEncryptor(),
        store=store,
        now=lambda: NOW,
    )
    if connected:
        service.finish_connect(tenant_id=TENANT, user_id=USER, code="c", code_verifier="v")
        canva.calls.clear()
    return service, canva, repo, store


IMAGE = MediaRef("generated/t/d/image.png", "image", 1080, 1350, 0)
VIDEO = MediaRef("generated/t/d/video.mp4", "video", None, None, 0)


def _jwt(claims: dict[str, Any]) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"e30.{payload}.sig"


def test_connect_start_keeps_pkce_and_state() -> None:
    service, *_ = _service(connected=False)
    start = service.start_connect(state="st-1")
    assert "code_challenge=" in start.url and "state=st-1" in start.url
    assert start.code_verifier not in start.url  # only the challenge travels


def test_tokens_are_stored_encrypted_per_user() -> None:
    service, _, repo, _ = _service()
    account = repo.accounts[(TENANT, USER)]
    assert b"at0" not in account.access_token_ciphertext
    assert DevEncryptor().decrypt(account.access_token_ciphertext, key_id=account.key_id) == "at0"
    assert service.is_connected(tenant_id=TENANT, user_id=USER)
    service.disconnect(tenant_id=TENANT, user_id=USER)
    assert not service.is_connected(tenant_id=TENANT, user_id=USER)


def test_an_image_is_uploaded_placed_in_a_same_size_design_and_linked() -> None:
    service, canva, repo, _ = _service([IMAGE])
    sent = service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)

    assert canva.names() == ["upload_asset", "create_design"]
    upload = canva.calls[0][1]
    assert upload["data"] == b"png" and upload["is_video"] is False
    assert upload["access_token"] == "at0"
    design = canva.calls[1][1]
    assert (design["width"], design["height"], design["asset_id"]) == (1080, 1350, "A1")
    assert sent.video_needs_drag is False
    link = sent.link
    assert sent.open_url == f"{link.edit_url}?correlation_state={link.correlation_state}"
    assert repo.links_for_draft(tenant_id=TENANT, draft_id=DRAFT) == [link]


def test_a_video_is_uploaded_but_not_placed() -> None:
    service, canva, *_ = _service([VIDEO])
    sent = service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)
    assert canva.calls[0][1]["is_video"] is True
    design = canva.calls[1][1]
    assert design["asset_id"] is None and (design["width"], design["height"]) == (1080, 1920)
    assert sent.video_needs_drag is True


def test_sending_needs_a_file_and_a_connection() -> None:
    service, *_ = _service([])
    with pytest.raises(NothingToSend):
        service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)
    service, *_ = _service([IMAGE], connected=False)
    with pytest.raises(CanvaNotConnected):
        service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)


def test_an_expiring_token_is_refreshed_and_the_new_pair_replaces_the_old() -> None:
    service, canva, repo, _ = _service([IMAGE])
    account = repo.accounts[(TENANT, USER)]
    repo.accounts[(TENANT, USER)] = type(account)(
        **{**account.__dict__, "expires_at": NOW + timedelta(seconds=30)}
    )
    service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)
    assert canva.calls[0] == ("refresh", {"refresh_token": "rt0"})
    assert canva.calls[1][1]["access_token"] == "at1"
    stored = repo.accounts[(TENANT, USER)]
    assert DevEncryptor().decrypt(stored.refresh_token_ciphertext, key_id=stored.key_id) == "rt1"


def test_a_spent_refresh_token_disconnects_instead_of_looping() -> None:
    service, canva, repo, _ = _service([IMAGE])
    account = repo.accounts[(TENANT, USER)]
    repo.accounts[(TENANT, USER)] = type(account)(**{**account.__dict__, "expires_at": NOW})
    canva.refresh_fails = True
    with pytest.raises(CanvaNotConnected):
        service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)
    assert (TENANT, USER) not in repo.accounts


def test_the_return_brings_the_edit_back_next_to_the_draft() -> None:
    service, canva, _, store = _service([IMAGE])
    sent = service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)
    canva.calls.clear()
    token = _jwt({"design_id": "D1", "correlation_state": sent.link.correlation_state})

    link = service.handle_return(tenant_id=TENANT, user_id=USER, correlation_jwt=token)

    assert canva.names() == ["get_design", "export_design", "download"]
    assert canva.calls[1][1]["file_type"] == "png"
    assert link.status == "exported" and link.design_updated_at == 200
    assert link.exported_object_key is not None
    assert link.exported_object_key.startswith(f"generated/{TENANT}/{DRAFT}/canva-")
    assert store.files[link.exported_object_key] == b"edited-bytes"


def test_a_video_comes_back_as_a_vertical_1080p_mp4() -> None:
    service, canva, *_ = _service([VIDEO])
    sent = service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)
    link = service.pull(tenant_id=TENANT, user_id=USER, link_id=sent.link.id)
    export = next(kw for name, kw in canva.calls if name == "export_design")
    assert (export["file_type"], export["mp4_quality"]) == ("mp4", "vertical_1080p")
    assert link.exported_object_key is not None and link.exported_object_key.endswith(".mp4")


@pytest.mark.parametrize(
    "claims",
    [
        {"design_id": "D1", "correlation_state": "not-ours"},
        {"design_id": "D-other", "correlation_state": "<ours>"},
        {"design_id": "D1"},
    ],
)
def test_a_return_that_matches_nothing_of_ours_is_refused(claims: dict[str, Any]) -> None:
    service, *_ = _service([IMAGE])
    sent = service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)
    if claims.get("correlation_state") == "<ours>":
        claims = {**claims, "correlation_state": sent.link.correlation_state}
    with pytest.raises(UnknownReturn):
        service.handle_return(tenant_id=TENANT, user_id=USER, correlation_jwt=_jwt(claims))


def test_another_user_or_tenant_cannot_claim_the_return() -> None:
    service, *_ = _service([IMAGE])
    sent = service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)
    token = _jwt({"design_id": "D1", "correlation_state": sent.link.correlation_state})
    with pytest.raises(UnknownReturn):
        service.handle_return(tenant_id=TENANT, user_id=uuid4(), correlation_jwt=token)
    with pytest.raises(UnknownReturn):
        service.handle_return(tenant_id=OTHER_TENANT, user_id=USER, correlation_jwt=token)
    with pytest.raises(UnknownReturn):
        service.handle_return(tenant_id=TENANT, user_id=USER, correlation_jwt="garbage")


def test_a_failed_export_is_recorded_and_keeps_the_last_good_file() -> None:
    service, canva, *_ = _service([IMAGE])
    sent = service.send(tenant_id=TENANT, user_id=USER, draft_id=DRAFT)
    canva.export_fails = True
    failed = service.pull(tenant_id=TENANT, user_id=USER, link_id=sent.link.id)
    assert failed.status == "failed" and "license_required" in (failed.error or "")

    canva.export_fails = False
    good = service.pull(tenant_id=TENANT, user_id=USER, link_id=sent.link.id)
    canva.export_fails = True
    again = service.pull(tenant_id=TENANT, user_id=USER, link_id=sent.link.id)
    assert again.status == "exported" and again.exported_object_key == good.exported_object_key
