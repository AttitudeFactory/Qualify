"""CM-9 (m-24957283): the owner's uploads live in R2 — keys, the write-once PUT, the
readers that resolve an old local key through the key map. Offline: an in-memory bucket
with the production lock on `t/` (write-once, undeletable), never R2."""

from __future__ import annotations

import io
from pathlib import Path
from uuid import UUID

import pytest
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore, ObjectLockedError

from qualify_api.creative import owner_uploads as ou
from qualify_api.creative.media import LocalMediaStore, R2ReadingMediaStore, _key_problems

TENANT = UUID("a0000000-0000-4000-8000-00000000c901")
OTHER = UUID("b0000000-0000-4000-8000-00000000c902")


@pytest.fixture
def bucket() -> MemoryObjectStore:
    return MemoryObjectStore()


@pytest.fixture
def gate(bucket: MemoryObjectStore) -> ObjectGate:
    return ObjectGate(bucket)


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ou.time, "sleep", lambda _s: None)
    ou.clear_moved_cache()


# -- keys ----------------------------------------------------------------------------


def test_old_local_keys_map_one_to_one_under_t() -> None:
    assert ou.moved_key_for(f"uploads/{TENANT}/catalog/p/x.jpg") == (
        f"t/{TENANT}/uploads/catalog/p/x.jpg"
    )
    # old pieces: outside `generated/`, which the 90-day rule of ADR 39 empties
    assert ou.moved_key_for(f"generated/{TENANT}/d/video.mp4") == (
        f"t/{TENANT}/generated-local/d/video.mp4"
    )


@pytest.mark.parametrize(
    "key",
    [
        "uploads/not-a-uuid/x.jpg",
        f"uploads/{TENANT}",
        f"uploads/{TENANT}/../x.jpg",
        f"uploads/{TENANT}//x.jpg",
        f"t/{TENANT}/uploads/x.jpg",
        f"gallery/{TENANT}/m/photo.jpg",
        f"other/{TENANT}/x.jpg",
        "x.jpg",
    ],
)
def test_a_key_whose_business_cannot_be_determined_maps_to_nothing(key: str) -> None:
    assert ou.moved_key_for(key) is None
    assert ou.local_key_tenant(key) is None


def test_a_new_upload_key_is_fresh_safe_and_under_the_tenants_uploads() -> None:
    first = ou.new_upload_key(TENANT, "../../menú del día.pdf", folder="brief")
    second = ou.new_upload_key(TENANT, "../../menú del día.pdf", folder="brief")
    assert first != second  # a fresh uuid4 each time: never meets an object of its name
    assert first.startswith(f"t/{TENANT}/uploads/brief/")
    assert first.endswith("_menú del día.pdf") and ".." not in first
    with pytest.raises(ValueError):
        ou.owner_upload_key(TENANT, "a/../b")


def test_only_uploads_and_copied_pieces_are_served_by_the_upload_route() -> None:
    assert ou.served_upload_tenant(f"t/{TENANT}/uploads/x_a.jpg") == TENANT
    assert ou.served_upload_tenant(f"t/{TENANT}/generated-local/d/v.mp4") == TENANT
    for key in (
        f"t/{TENANT}/brand/b/logo.png",
        f"t/{TENANT}/generated/d/r1/video.mp4",
        f"t/{TENANT}/uploads",
        f"t/{TENANT}/uploads/../brand/x",
        f"gallery/{TENANT}/m/photo.jpg",
        f"uploads/{TENANT}/x.jpg",
    ):
        assert ou.served_upload_tenant(key) is None, key


def test_waiting_rooms_are_recognized() -> None:
    assert ou.is_staging(f"uploads/{TENANT}/gallery-staging/u")
    assert ou.is_staging(f"uploads/{TENANT}/catalog_staging/a.jpg")
    assert not ou.is_staging(f"uploads/{TENANT}/catalog/p/a.jpg")


# -- the write-once PUT --------------------------------------------------------------


def test_put_once_writes_the_stream_with_its_type(gate, bucket) -> None:
    key = ou.new_upload_key(TENANT, "a.jpg")
    ou.put_once(TENANT, key, io.BytesIO(b"jpeg"), "image/jpeg", gate=gate)
    assert bucket.objects[key] == b"jpeg" and bucket.content_types[key] == "image/jpeg"


def test_a_retry_after_a_landed_put_does_not_write_again(gate, bucket) -> None:
    key = ou.new_upload_key(TENANT, "a.jpg")
    ou.put_bytes_once(TENANT, key, b"jpeg", "image/jpeg", gate=gate)
    ou.put_bytes_once(TENANT, key, b"jpeg", "image/jpeg", gate=gate)
    assert bucket.puts == [key]


def test_a_key_holding_another_file_is_never_overwritten(gate, bucket) -> None:
    key = ou.new_upload_key(TENANT, "a.jpg")
    ou.put_bytes_once(TENANT, key, b"first", "image/jpeg", gate=gate)
    with pytest.raises(ou.UploadNotKept):
        ou.put_bytes_once(TENANT, key, b"another file", "image/jpeg", gate=gate)
    assert bucket.objects[key] == b"first" and bucket.puts == [key]


def test_a_passing_failure_is_retried_from_the_start_of_the_stream(gate, bucket) -> None:
    key = ou.new_upload_key(TENANT, "a.mp4")
    bucket.fail_puts = 2
    ou.put_once(TENANT, key, io.BytesIO(b"video"), "video/mp4", gate=gate)
    assert bucket.objects[key] == b"video"


def test_r2_down_for_good_fails_the_upload(gate, bucket) -> None:
    bucket.fail_puts = 99
    with pytest.raises(ou.UploadNotKept):
        ou.put_bytes_once(TENANT, ou.new_upload_key(TENANT, "a.jpg"), b"x", "image/jpeg", gate=gate)
    assert bucket.objects == {}


def test_another_tenants_prefix_is_refused_without_retry(gate, bucket) -> None:
    bucket.fail_puts = 0
    with pytest.raises(ou.UploadNotKept):
        ou.put_bytes_once(TENANT, ou.new_upload_key(OTHER, "a.jpg"), b"x", "image/jpeg", gate=gate)
    assert bucket.objects == {}


def test_no_r2_configured_is_a_refusal_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_shared.objects.config import R2ConfigurationError

    def unconfigured():
        raise R2ConfigurationError("QUALIFY_R2_BUCKET")

    monkeypatch.setattr(ou, "default_gate", unconfigured)
    with pytest.raises(ou.UploadNotKept):
        ou.put_bytes_once(TENANT, ou.new_upload_key(TENANT, "a.jpg"), b"x", "image/jpeg")


def test_the_memory_bucket_keeps_the_production_lock() -> None:
    bucket = MemoryObjectStore()
    bucket.put(f"t/{TENANT}/uploads/a", io.BytesIO(b"1"), "image/jpeg")
    with pytest.raises(ObjectLockedError):
        bucket.put(f"t/{TENANT}/uploads/a", io.BytesIO(b"2"), "image/jpeg")
    with pytest.raises(ObjectLockedError):
        bucket.delete_keys([f"t/{TENANT}/uploads/a"])


def test_materialize_copies_range_by_range_and_cleans_up(gate, bucket, monkeypatch) -> None:
    key = f"t/{TENANT}/uploads/x_voz.wav"
    bucket.put(key, io.BytesIO(b"0123456789" * 3), "audio/wav")
    monkeypatch.setattr(ou, "_CHUNK", 7)
    ranges: list[tuple[int, int]] = []
    original = bucket.open_range

    def spy(k: str, start: int, end: int):
        ranges.append((start, end))
        return original(k, start, end)

    monkeypatch.setattr(bucket, "open_range", spy)
    with ou.materialize(TENANT, key, gate=gate) as path:
        assert path.read_bytes() == b"0123456789" * 3 and path.suffix == ".wav"
        kept = path
    assert not kept.exists()
    assert ranges[0] == (0, 6) and all(e - s < 7 for s, e in ranges)


# -- readers: an old key resolves through the map ------------------------------------


def _store(tmp_path: Path, gate: ObjectGate, moved: dict[tuple[UUID, str], str]):
    return R2ReadingMediaStore(
        LocalMediaStore(tmp_path), gate=gate, moved=lambda t, k: moved.get((t, k))
    )


def test_an_old_key_still_on_the_volume_is_read_from_the_volume(tmp_path, gate) -> None:
    old = f"uploads/{TENANT}/x_a.jpg"
    (tmp_path / old).parent.mkdir(parents=True)
    (tmp_path / old).write_bytes(b"local")
    assert _store(tmp_path, gate, {}).read(old) == b"local"


def test_an_old_key_kept_in_a_json_field_resolves_to_r2(tmp_path, gate, bucket) -> None:
    """The acceptance criterion: a brief's `brand_logo_reference_keys` was never rewritten,
    its file left the volume, and the piece still reads it — from R2, through the map."""
    from qualify_api.creative.media import BrandKit, ContentBrief, MediaInputs

    old = f"uploads/{TENANT}/logo/ref/x_logo.png"
    new = ou.moved_key_for(old)
    assert new is not None
    bucket.put(new, io.BytesIO(b"logo bytes"), "image/png")
    brief = ContentBrief.model_construct(
        source_media_key=None, media=MediaInputs(brand_logo_reference_keys=[old])
    )
    kit = BrandKit.model_construct(logo_asset_key=None)
    assert _key_problems(TENANT, brief, kit) == ([], [])  # still the brand's own key
    store = _store(tmp_path, gate, {(TENANT, old): new})
    assert store.read(old) == b"logo bytes"
    assert store.sha256(TENANT, old) == bucket.sha256(new)


def test_an_old_key_nowhere_is_still_not_found(tmp_path, gate) -> None:
    with pytest.raises(FileNotFoundError):
        _store(tmp_path, gate, {}).read(f"uploads/{TENANT}/gone.jpg")


def test_an_unreadable_map_keeps_the_not_found(tmp_path, gate) -> None:
    def down(_t, _k):
        raise ConnectionError("database down")

    store = R2ReadingMediaStore(LocalMediaStore(tmp_path), gate=gate, moved=down)
    with pytest.raises(FileNotFoundError):
        store.read(f"uploads/{TENANT}/gone.jpg")


def test_write_puts_an_r2_key_in_r2_once_and_a_local_key_locally(tmp_path, gate, bucket) -> None:
    store = _store(tmp_path, gate, {})
    key = ou.owner_upload_key(TENANT, "catalog/p/x.jpg")
    store.write(key, b"photo")
    assert bucket.objects[key] == b"photo" and bucket.content_types[key] == "image/jpeg"
    assert not (tmp_path / key).exists()
    with pytest.raises(ou.UploadNotKept):  # the same key, other bytes: never overwritten
        store.write(key, b"other photo")
    store.write(f"generated/{TENANT}/d/scratch.bin", b"local")
    assert (tmp_path / f"generated/{TENANT}/d/scratch.bin").read_bytes() == b"local"


def test_read_owner_media_refuses_another_tenants_key(tmp_path, gate) -> None:
    with pytest.raises(PermissionError):
        ou.read_owner_media(TENANT, f"uploads/{OTHER}/x.jpg", root=tmp_path, gate=gate)
    with pytest.raises(PermissionError):
        ou.read_owner_media(TENANT, f"t/{OTHER}/uploads/x.jpg", root=tmp_path, gate=gate)


def test_read_owner_media_reads_r2_volume_and_map(tmp_path, gate, bucket) -> None:
    r2 = ou.owner_upload_key(TENANT, "x_a.jpg")
    bucket.put(r2, io.BytesIO(b"r2"), "image/jpeg")
    local = f"uploads/{TENANT}/x_b.jpg"
    (tmp_path / local).parent.mkdir(parents=True)
    (tmp_path / local).write_bytes(b"volume")
    moved = f"uploads/{TENANT}/x_c.jpg"
    bucket.put(ou.moved_key_for(moved), io.BytesIO(b"moved"), "image/jpeg")
    resolver = {(TENANT, moved): ou.moved_key_for(moved)}.get

    def read(key: str) -> bytes:
        return ou.read_owner_media(
            TENANT, key, root=tmp_path, gate=gate, resolver=lambda t, k: resolver((t, k))
        )

    assert (read(r2), read(local), read(moved)) == (b"r2", b"volume", b"moved")
    with ou.owner_media_path(
        TENANT, moved, root=tmp_path, gate=gate, resolver=lambda t, k: resolver((t, k))
    ) as path:
        assert path.read_bytes() == b"moved"


def test_the_map_lookup_never_crosses_tenants() -> None:
    """The tenant comes from the key: a key of another tenant is never even looked up."""
    assert ou.resolve_moved_key(TENANT, f"uploads/{OTHER}/x.jpg") is None


def test_whatsapp_reads_a_moved_catalog_photo_from_r2(tmp_path, gate, bucket, monkeypatch) -> None:
    from qualify_api.creative import composition
    from qualify_api.whatsapp.attachments import ProductionBlobStore

    old = f"uploads/{TENANT}/catalog/p/x.jpg"
    bucket.put(ou.moved_key_for(old), io.BytesIO(b"catalog photo"), "image/jpeg")
    monkeypatch.setattr(composition, "media_root", lambda: tmp_path)
    monkeypatch.setattr(ou, "resolve_moved_key", lambda t, k: ou.moved_key_for(k))
    store = ProductionBlobStore()
    store._gate = gate
    assert store.read(TENANT, old) == b"catalog photo"
    with pytest.raises(PermissionError):
        store.read(OTHER, old)


def test_catalog_upload_failure_says_so_in_spanish(monkeypatch) -> None:
    from qualify_api.catalog import service as mod

    for message in (mod.MEDIA_NOT_SAVED_TEXT, ou.UPLOAD_NOT_SAVED):
        assert "guard" in message and "Vuelve a subirlo" in message
        assert "upload" not in message.lower()


def test_a_file_over_the_put_ceiling_is_too_large_before_any_r2_call(
    gate, bucket, monkeypatch
) -> None:
    from qualify_shared.objects import gate as gate_module

    monkeypatch.setattr(gate_module, "MAX_MEDIA_BYTES", 4)
    monkeypatch.setattr(ou, "default_gate", lambda: pytest.fail("R2 reached"))
    with pytest.raises(ou.UploadTooLarge):
        ou.put_bytes_once(TENANT, ou.new_upload_key(TENANT, "a.mp4"), b"12345", "video/mp4")
    assert bucket.objects == {}


def test_the_owner_reads_too_large_in_plain_spanish() -> None:
    from qualify_api.catalog.business_media import VIDEO_TOO_HEAVY_TEXT

    too_large = ou.UploadTooLarge("x")
    assert ou.refusal_text(too_large, "menú.pdf") == ou.UPLOAD_TOO_LARGE
    assert ou.UPLOAD_TOO_LARGE == "Ese archivo es muy pesado. Prueba con uno más liviano."
    # a video: the Galería's own words
    assert ou.refusal_text(too_large, "reel.mp4") == VIDEO_TOO_HEAVY_TEXT
    assert ou.refusal_text(ou.UploadNotKept("down"), "a.jpg") == ou.UPLOAD_NOT_SAVED
