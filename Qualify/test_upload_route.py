"""CM-9 (m-24957283): `GET /_upload/<key>` keeps showing an upload once it lives in R2 —
the volume first, then an owner upload in R2, then an old key through the key map; never
any other R2 object. Offline: an in-memory bucket, a fake Reflex app behind it."""

from __future__ import annotations

import io
from pathlib import Path
from uuid import UUID

import pytest
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from .upload_route import R2UploadFallback

TENANT = UUID("a0000000-0000-4000-8000-00000000c911")
OTHER = UUID("b0000000-0000-4000-8000-00000000c912")


def _reflex(request) -> PlainTextResponse:
    return PlainTextResponse("reflex:" + request.url.path, status_code=404)


@pytest.fixture
def world(tmp_path: Path):
    bucket = MemoryObjectStore()
    gate = ObjectGate(bucket)
    moved: dict[tuple[UUID, str], str] = {}
    inner = Starlette(routes=[Route("/{path:path}", _reflex, methods=["GET", "HEAD", "POST"])])
    app = R2UploadFallback(
        inner, root=lambda: tmp_path, gate=lambda: gate, resolver=lambda t, k: moved.get((t, k))
    )
    return TestClient(app), bucket, moved, tmp_path


def test_a_file_on_the_volume_is_left_to_reflex(world) -> None:
    client, bucket, _moved, root = world
    key = f"uploads/{TENANT}/x_a.jpg"
    (root / key).parent.mkdir(parents=True)
    (root / key).write_bytes(b"local")
    bucket.put(f"t/{TENANT}/uploads/x_a.jpg", io.BytesIO(b"r2"), "image/jpeg")
    response = client.get(f"/_upload/{key}")
    assert response.text == f"reflex:/_upload/{key}"


def test_a_new_upload_in_r2_is_streamed_with_the_upload_headers(world) -> None:
    client, bucket, _moved, _root = world
    key = f"t/{TENANT}/uploads/x_foto.jpg"
    bucket.put(key, io.BytesIO(b"jpeg-bytes"), "image/jpeg")
    response = client.get(f"/_upload/{key}")
    assert response.status_code == 200 and response.content == b"jpeg-bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == "attachment"  # like Reflex's own route
    head = client.head(f"/_upload/{key}")
    assert head.status_code == 200 and head.headers["content-length"] == "10"


def test_a_pdf_opens_inline_like_on_reflexs_route(world) -> None:
    client, bucket, _moved, _root = world
    key = f"t/{TENANT}/uploads/brief/x_menu.pdf"
    bucket.put(key, io.BytesIO(b"%PDF"), "application/pdf")
    assert "content-disposition" not in client.get(f"/_upload/{key}").headers


def test_a_video_is_served_by_ranges(world) -> None:
    client, bucket, _moved, _root = world
    key = f"t/{TENANT}/uploads/catalog/p/x.mp4"
    bucket.put(key, io.BytesIO(b"0123456789"), "video/mp4")
    response = client.get(f"/_upload/{key}", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206 and response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert client.get(f"/_upload/{key}", headers={"Range": "bytes=50-"}).status_code == 416


def test_an_old_key_moved_by_the_copy_is_served_from_r2(world) -> None:
    client, bucket, moved, _root = world
    old = f"uploads/{TENANT}/catalog/p/x.jpg"
    new = f"t/{TENANT}/uploads/catalog/p/x.jpg"
    bucket.put(new, io.BytesIO(b"moved"), "image/jpeg")
    moved[(TENANT, old)] = new
    response = client.get(f"/_upload/{old}")
    assert response.status_code == 200 and response.content == b"moved"


def test_an_old_key_not_moved_falls_through_to_reflex(world) -> None:
    client, _bucket, _moved, _root = world
    old = f"uploads/{TENANT}/gone.jpg"
    assert client.get(f"/_upload/{old}").text == f"reflex:/_upload/{old}"


@pytest.mark.parametrize(
    "key",
    [
        f"t/{TENANT}/brand/b/logo.png",  # the Brand Kit stays behind /r2media tokens
        f"t/{TENANT}/generated/d/r1/video.mp4",  # so do the pieces
        f"t/{TENANT}/fp/instagram/c/raw.json",
        f"gallery/{TENANT}/m/photo.jpg",
    ],
)
def test_no_other_r2_object_is_reachable(world, key: str) -> None:
    client, bucket, _moved, _root = world
    bucket.put(key, io.BytesIO(b"secret"), "image/jpeg")
    response = client.get(f"/_upload/{key}")
    assert response.content != b"secret" and response.text == f"reflex:/_upload/{key}"


def test_a_missing_r2_upload_is_a_plain_404(world) -> None:
    client, _bucket, _moved, _root = world
    assert client.get(f"/_upload/t/{TENANT}/uploads/x_none.jpg").status_code == 404


def test_uploads_posts_and_other_routes_are_untouched(world) -> None:
    client, _bucket, _moved, _root = world
    assert client.post("/_upload").text == "reflex:/_upload"
    assert client.get("/login").text == "reflex:/login"


def test_a_map_that_cannot_be_read_falls_through(tmp_path: Path) -> None:
    def down(_t, _k):
        raise ConnectionError("database down")

    inner = Starlette(routes=[Route("/{path:path}", _reflex)])
    app = R2UploadFallback(
        inner, root=lambda: tmp_path, gate=lambda: ObjectGate(MemoryObjectStore()), resolver=down
    )
    old = f"uploads/{TENANT}/x.jpg"
    assert TestClient(app).get(f"/_upload/{old}").text == f"reflex:/_upload/{old}"


def test_a_map_row_pointing_outside_the_uploads_is_never_served(world) -> None:
    """Defence in depth over the 0138 CHECK: a row mapping an old key to a Brand Kit
    object would make it public without a token — it falls through instead."""
    client, bucket, moved, _root = world
    old = f"uploads/{TENANT}/x.jpg"
    brand = f"t/{TENANT}/brand/b/logo.png"
    bucket.put(brand, io.BytesIO(b"secret"), "image/png")
    moved[(TENANT, old)] = brand
    assert client.get(f"/_upload/{old}").text == f"reflex:/_upload/{old}"
    moved[(TENANT, old)] = f"t/{OTHER}/uploads/x.jpg"  # another business's upload
    assert client.get(f"/_upload/{old}").text == f"reflex:/_upload/{old}"
