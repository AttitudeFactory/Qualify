"""«Descargar todo» (m-24828908): the token door, the route and the button."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any
from uuid import uuid4

import pytest
import reflex as rx

from . import creative_provider
from . import piece_download as pd
from .creative_state import CreativeState
from .creative_vm import build_draft_vm


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttl: dict[str, int | None] = {}

    def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        self.values[name], self.ttl[name] = value, ex
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)


def test_a_token_names_one_draft_and_only_its_hash_is_stored() -> None:
    redis = FakeRedis()
    store = pd.PieceTokenStore(redis)
    tenant, draft = uuid4(), uuid4()
    token = store.issue(tenant_id=tenant, draft_id=draft)
    assert len(token) >= 40 and store.resolve(token) == (tenant, draft)
    (key,) = redis.values
    assert token not in key and str(tenant) not in key  # the hash, never the token
    assert redis.ttl[key] == pd.DOWNLOAD_TTL_SECONDS
    assert store.resolve("otro") is None
    redis.values[key] = "{roto"
    assert store.resolve(token) is None


def test_the_path_is_the_route_and_a_fresh_token() -> None:
    store = pd.PieceTokenStore(FakeRedis())
    path = pd.issue_download_path(uuid4(), uuid4(), store=store)
    assert path.startswith(pd.DOWNLOAD_ROUTE + "/")


def test_the_route_serves_the_zip_or_one_404(monkeypatch: pytest.MonkeyPatch) -> None:
    store = pd.PieceTokenStore(FakeRedis())
    monkeypatch.setattr(pd, "_store", lambda: store)
    tenant, draft = uuid4(), uuid4()
    calls: list[tuple[Any, Any]] = []

    def archive(t: Any, d: Any) -> tuple[str, bytes] | None:
        calls.append((t, d))
        return ("nibbles-burger-smash-doble.zip", b"PK-zip") if d == draft else None

    monkeypatch.setattr(creative_provider, "piece_archive", archive)
    token = store.issue(tenant_id=tenant, draft_id=draft)
    response = asyncio.run(pd.piece_download(token))
    assert response.status_code == 200 and response.body == b"PK-zip"
    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"] == (
        'attachment; filename="nibbles-burger-smash-doble.zip"'
    )
    assert calls == [(tenant, draft)]
    assert asyncio.run(pd.piece_download("desconocido")).status_code == 404
    other = store.issue(tenant_id=tenant, draft_id=uuid4())
    assert asyncio.run(pd.piece_download(other)).status_code == 404  # draft not visible

    def boom(t: Any, d: Any) -> None:
        raise RuntimeError("R2 down")

    monkeypatch.setattr(creative_provider, "piece_archive", boom)
    assert asyncio.run(pd.piece_download(token)).status_code == 404


def _vm(status: str) -> Any:
    return build_draft_vm(
        draft_id=str(uuid4()),
        status=status,
        failure_reason=None,
        variants=(),
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=None,
        model_ids=(),
        requires_ai_disclosure=False,
        created_label="",
    )


def test_the_download_is_offered_once_there_is_something_to_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    minted: list[Any] = []
    monkeypatch.setattr(
        creative_provider,
        "issue_download_path",
        lambda tenant, draft: minted.append(draft) or "/piece-download/tok",
    )
    monkeypatch.setattr(creative_provider, "_brand_name", lambda tenant: "nibbles burger")
    detail = dataclasses.make_dataclass("D", ["id", "variants", "media", "title"])
    ready = detail(uuid4(), ("v",), (), "Smash doble")
    vm = creative_provider._with_download(uuid4(), ready, _vm("generated"))
    assert (vm.download_path, vm.download_name) == (
        "/piece-download/tok",
        "nibbles-burger-smash-doble.zip",
    )
    # never on every poll of a draft still generating, nor for an empty piece
    assert creative_provider._with_download(uuid4(), ready, _vm("drafting")).download_path == ""
    empty = detail(uuid4(), (), (), "")
    assert creative_provider._with_download(uuid4(), empty, _vm("failed")).download_path == ""
    assert minted == [ready.id]

    def down(tenant: Any, draft: Any) -> str:
        raise ConnectionError("redis")

    monkeypatch.setattr(creative_provider, "issue_download_path", down)
    assert creative_provider._with_download(uuid4(), ready, _vm("generated")).download_path == ""


def test_one_descargar_downloads_the_whole_piece() -> None:
    """§ request 2026-10-21 («un solo botón»): the «Descargar» under the image or the video
    is the piece's .zip; the file alone only when no .zip link could be minted. The code
    travels with the click — an `rx.script` defining `window.qualifyDownload` never ran,
    so «Descargar» did nothing."""
    from .download_buttons import piece_download_button

    path, name = rx.Var.create("/piece-download/t"), rx.Var.create("marca-pieza.zip")
    rendered = str(piece_download_button(path, name, file_url="/f.jpg", file_name="f.jpg"))
    assert rendered.count('"Descargar"') == 2  # the .zip, or the file as a fallback
    assert "piece-download" in rendered and "/f.jpg" in rendered
    assert "createObjectURL" in rendered and "qualifyDownload" not in rendered
    assert "Descargar todo" not in rendered
    # without a file (a script), only the .zip
    assert str(piece_download_button(path, name)).count('"Descargar"') == 1


def test_both_screens_offer_only_the_one_descargar() -> None:
    from .content_generator import _item_download, _script_result, generator_page
    from .creative_pages import _media_column, _media_item, draft_detail_index

    for page in (str(draft_detail_index()), str(generator_page())):
        assert "Descargar todo" not in page and "qualifyDownload" not in page
    # under each file, and in the pieces with no file (the script, the copy-only piece)
    for part, var in (
        (_media_item(CreativeState.draft.media[0]), "draft"),
        (_media_column(), "draft"),
        (_item_download(CreativeState.gen_draft.media[0]), "gen_draft"),
        (_script_result(), "gen_draft"),
    ):
        rendered = str(part)
        assert "download_path" in rendered and var in rendered, part
