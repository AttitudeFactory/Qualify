"""The object gate's invariants (QUA-19 / ADR 28c), all offline.

The store is an in-memory double, so nothing here imports boto3 or touches a network — the
gate is exactly the layer where tenant isolation and the size ceiling live, and both are
testable without a bucket.
"""

from __future__ import annotations

import io
from typing import IO
from uuid import UUID, uuid4

import pytest

from qualify_shared.objects import (
    MAX_MEDIA_BYTES,
    ObjectGate,
    ObjectSizeExceeded,
    PrefixDeletion,
    StoredObject,
    TenantPrefixViolation,
    UnsizedStream,
    media_key,
    tenant_prefix,
)
from qualify_shared.objects.gate import DELETE_BATCH

_TENANT = UUID("11111111-1111-1111-1111-111111111111")
_OTHER_TENANT = UUID("22222222-2222-2222-2222-222222222222")


class InMemoryStore:
    """Records what it was asked to write, so tests can assert on the KEY the gate derived
    rather than on the gate's return value (it has none)."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> IO[bytes]:
        if key not in self.objects:
            raise KeyError(key)
        return io.BytesIO(self.objects[key][0])


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def gate(store: InMemoryStore) -> ObjectGate:
    return ObjectGate(store)


def test_put_media_stores_bytes_and_content_type(gate: ObjectGate, store: InMemoryStore) -> None:
    key = media_key(_TENANT, uuid4(), "reel-1")
    gate.put_media(_TENANT, key, io.BytesIO(b"video-bytes"), "video/mp4")
    assert store.objects[key] == (b"video-bytes", "video/mp4")


def test_media_key_sits_under_the_tenant_prefix() -> None:
    key = media_key(_TENANT, uuid4(), "reel-1")
    assert key.startswith(tenant_prefix(_TENANT))


def test_tenant_prefix_ends_with_a_slash() -> None:
    """Without the trailing slash, `t/{a}` would prefix-match `t/{ab}/...`. The tenant ids
    are UUIDs of fixed length today, so this cannot bite yet — which is precisely why it
    would survive unnoticed if the key space ever gained a shorter identifier."""
    assert tenant_prefix(_TENANT).endswith("/")


def test_put_media_rejects_a_key_belonging_to_another_tenant(gate: ObjectGate) -> None:
    foreign = media_key(_OTHER_TENANT, uuid4(), "reel-1")
    with pytest.raises(TenantPrefixViolation):
        gate.put_media(_TENANT, foreign, io.BytesIO(b"x"), "video/mp4")


def test_put_media_rejects_an_unprefixed_key(gate: ObjectGate) -> None:
    with pytest.raises(TenantPrefixViolation):
        gate.put_media(_TENANT, "media/loose-key", io.BytesIO(b"x"), "video/mp4")


def test_put_media_rejects_parent_traversal(gate: ObjectGate) -> None:
    key = f"{tenant_prefix(_TENANT)}media/../../{_OTHER_TENANT}/media/stolen"
    with pytest.raises(TenantPrefixViolation):
        gate.put_media(_TENANT, key, io.BytesIO(b"x"), "video/mp4")


def test_violation_message_does_not_echo_the_offending_key(gate: ObjectGate) -> None:
    """The rejected key can carry another tenant's identifier, and exception messages end up
    in logs. The message names the expected prefix, never the input."""
    foreign = media_key(_OTHER_TENANT, uuid4(), "reel-1")
    with pytest.raises(TenantPrefixViolation) as excinfo:
        gate.put_media(_TENANT, foreign, io.BytesIO(b"x"), "video/mp4")
    assert str(_OTHER_TENANT) not in str(excinfo.value)


def test_open_object_rechecks_the_prefix(gate: ObjectGate, store: InMemoryStore) -> None:
    """A key read back from a database row is still input. The other tenant's object exists
    in the store, so this asserts the GATE refused rather than the store missing."""
    foreign = media_key(_OTHER_TENANT, uuid4(), "reel-1")
    store.objects[foreign] = (b"not-yours", "video/mp4")
    with pytest.raises(TenantPrefixViolation):
        gate.open_object(_TENANT, foreign)


def test_open_object_round_trips_its_own_bytes(gate: ObjectGate) -> None:
    key = media_key(_TENANT, uuid4(), "reel-1")
    gate.put_media(_TENANT, key, io.BytesIO(b"video-bytes"), "video/mp4")
    assert gate.open_object(_TENANT, key).read() == b"video-bytes"


def test_put_media_rejects_over_the_ceiling(gate: ObjectGate) -> None:
    """300 MB is Meta's reel ceiling (`ig-user/media.md:86`). Asserting on a real oversized
    buffer would allocate 300 MB, so this drives a stream that reports its size without
    holding the bytes — the gate only ever seeks to measure."""

    class OversizedStream(io.RawIOBase):
        def seek(self, offset: int, whence: int = 0) -> int:
            return MAX_MEDIA_BYTES + 1 if whence == 2 else offset

    with pytest.raises(ObjectSizeExceeded):
        gate.put_media(_TENANT, media_key(_TENANT, uuid4(), "big"), OversizedStream(), "video/mp4")


def test_put_media_accepts_exactly_the_ceiling(gate: ObjectGate) -> None:
    """The boundary is inclusive. Off-by-one here would reject a legal 300 MB reel."""

    class ExactStream(io.RawIOBase):
        def seek(self, offset: int, whence: int = 0) -> int:
            return MAX_MEDIA_BYTES if whence == 2 else offset

        def read(self, size: int = -1) -> bytes:
            return b""

    gate.put_media(_TENANT, media_key(_TENANT, uuid4(), "exact"), ExactStream(), "video/mp4")


def test_put_media_measures_from_the_current_position(
    gate: ObjectGate, store: InMemoryStore
) -> None:
    """A stream handed over mid-read has fewer bytes remaining than its total length. If the
    gate measured absolute length it would over-count, and — worse — `put` would store only
    the remainder while the size check judged the whole."""
    stream = io.BytesIO(b"HEADERvideo-bytes")
    stream.seek(len(b"HEADER"))
    key = media_key(_TENANT, uuid4(), "reel-1")
    gate.put_media(_TENANT, key, stream, "video/mp4")
    assert store.objects[key][0] == b"video-bytes"


def test_put_media_leaves_the_stream_position_untouched(gate: ObjectGate) -> None:
    """Measuring must not consume: the store reads the same stream immediately afterwards."""

    class PositionSpy(io.BytesIO):
        pass

    stream = PositionSpy(b"video-bytes")
    ObjectGate(_NullStore()).put_media(
        _TENANT, media_key(_TENANT, uuid4(), "reel-1"), stream, "video/mp4"
    )
    assert stream.tell() == 0


def test_put_media_refuses_an_unseekable_stream(gate: ObjectGate) -> None:
    """An unmeasurable stream would silently exempt itself from the ceiling."""

    class Unseekable(io.RawIOBase):
        def seek(self, offset: int, whence: int = 0) -> int:
            raise OSError("not seekable")

    with pytest.raises(UnsizedStream):
        gate.put_media(_TENANT, media_key(_TENANT, uuid4(), "x"), Unseekable(), "video/mp4")


def test_put_media_requires_a_content_type(gate: ObjectGate) -> None:
    """Stored `Content-Type` is replayed to Meta later; an octet-stream default is a
    plausible cause of a container ERROR that looks unrelated."""
    with pytest.raises(ValueError):
        gate.put_media(_TENANT, media_key(_TENANT, uuid4(), "x"), io.BytesIO(b"x"), "")


def test_gate_exposes_no_presign_method() -> None:
    """ADR 28c: `presign_get` served only the deferred image branch (QUA-68). Its absence is
    the guarantee that this sprint opens no public HTTP surface, so it is asserted rather
    than left to review."""
    surface = {name for name in dir(ObjectGate) if not name.startswith("_")}
    # 2026-09-30: `object_size` + `open_range` added for the browser's video preview
    # (`Qualify/r2_media.py`, HTTP Range). Both are READS behind the same tenant-prefix
    # check as `open_object`; the bytes still leave only through a backend route that
    # resolves an opaque token. Still no signed/public URL of any kind.
    # 2026-10-22 (m-24828907, ADR 39): `delete_prefix` added for the piece retention rule —
    # the only deletion, restricted to folders under `PURGEABLE_ROOTS` (tests below).
    # ADR 41: sha256 reads the existing final to compare the confirmed binary;
    # the same tenant-prefix gate applies, with no public/signed URL capability.
    # m-24789547: connection-scoped object lifecycle methods remain behind the same
    # tenant + connection-prefix checks; they do not add signed/public URL capability.
    # 2026-11-05 (m-24955918, ADR 39 amendment / ADR 47): `delete_gallery_media` empties
    # ONE Galería medium's folder `t/{tenant}/gallery/{uuid}/` (prefix built from the
    # UUID, never caller text) and `list_gallery_media` lists the tenant's `gallery/` root
    # with each object's age for the daily reconciler. `PURGEABLE_ROOTS` is unchanged.
    assert surface == {
        "delete_gallery_media",
        "list_gallery_media",
        "put_media",
        "open_object",
        "object_size",
        "open_range",
        "delete_prefix",
        "sha256",
        "put_connection_media",
        "list_connection_objects",
        "delete_connection_objects",
        "delete_brand_prefill_objects",
        # m-24955648: one payment-method QR at a time, key shape checked (tests below).
        "delete_payment_qr",
    }
    assert not any("presign" in name or "sign" in name for name in surface)


def test_ranged_reads_keep_the_tenant_prefix_check() -> None:
    gate = ObjectGate(_NullStore())
    other = media_key(uuid4(), uuid4(), "x")
    with pytest.raises(TenantPrefixViolation):
        gate.object_size(_TENANT, other)
    with pytest.raises(TenantPrefixViolation):
        gate.open_range(_TENANT, other, 0, 1)


class _NullStore:
    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        return None

    def open(self, key: str) -> IO[bytes]:
        raise KeyError(key)


# -- delete_prefix (m-24828907) ------------------------------------------------------------


class ListingStore(InMemoryStore):
    """An in-memory store that can list and delete, recording each delete batch."""

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[str]] = []

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        return [
            StoredObject(key=key, size=len(data))
            for key, (data, _) in sorted(self.objects.items())
            if key.startswith(prefix)
        ]

    def delete_keys(self, keys: list[str]) -> None:
        self.batches.append(list(keys))
        for key in keys:
            self.objects.pop(key, None)


def _piece(tenant: UUID, draft: UUID) -> str:
    return f"{tenant_prefix(tenant)}generated/{draft}/"


def test_delete_prefix_dry_run_reports_without_deleting() -> None:
    store = ListingStore()
    draft = uuid4()
    store.objects[f"{_piece(_TENANT, draft)}r1/a.jpg"] = (b"12345", "image/jpeg")
    store.objects[f"{_piece(_TENANT, draft)}r2/b.mp4"] = (b"123", "video/mp4")
    result = ObjectGate(store).delete_prefix(_TENANT, _piece(_TENANT, draft))
    assert result == PrefixDeletion(objects=2, bytes=8)
    assert len(store.objects) == 2 and store.batches == []


def test_delete_prefix_removes_every_revision_and_nothing_else() -> None:
    """Old revisions have no `image_assets` row any more (a regeneration replaces them),
    so only a prefix delete reaches them."""
    store = ListingStore()
    draft, other = uuid4(), uuid4()
    store.objects[f"{_piece(_TENANT, draft)}r1/a.jpg"] = (b"1", "image/jpeg")
    store.objects[f"{_piece(_TENANT, draft)}r2/a.jpg"] = (b"2", "image/jpeg")
    store.objects[f"{_piece(_TENANT, other)}r1/a.jpg"] = (b"3", "image/jpeg")
    kit = f"{tenant_prefix(_TENANT)}brand/logo.png"
    store.objects[kit] = (b"4", "image/png")
    result = ObjectGate(store).delete_prefix(_TENANT, _piece(_TENANT, draft), execute=True)
    assert result.objects == 2
    assert set(store.objects) == {f"{_piece(_TENANT, other)}r1/a.jpg", kit}


def test_delete_prefix_is_idempotent() -> None:
    store = ListingStore()
    draft = uuid4()
    store.objects[f"{_piece(_TENANT, draft)}r1/a.jpg"] = (b"1", "image/jpeg")
    gate = ObjectGate(store)
    gate.delete_prefix(_TENANT, _piece(_TENANT, draft), execute=True)
    assert gate.delete_prefix(_TENANT, _piece(_TENANT, draft), execute=True) == PrefixDeletion(0, 0)


def test_delete_prefix_batches_at_the_s3_limit() -> None:
    store = ListingStore()
    draft = uuid4()
    for i in range(DELETE_BATCH + 5):
        store.objects[f"{_piece(_TENANT, draft)}r1/{i:05}.jpg"] = (b"x", "image/jpeg")
    ObjectGate(store).delete_prefix(_TENANT, _piece(_TENANT, draft), execute=True)
    assert [len(batch) for batch in store.batches] == [DELETE_BATCH, 5]
    assert store.objects == {}


@pytest.mark.parametrize(
    "prefix",
    [
        f"{tenant_prefix(_OTHER_TENANT)}generated/{uuid4()}/",  # another tenant
        f"{tenant_prefix(_TENANT)}",  # the whole tenant
        f"{tenant_prefix(_TENANT)}generated/",  # every piece at once
        f"{tenant_prefix(_TENANT)}brand/",  # a root that is not purgeable
        f"{tenant_prefix(_TENANT)}media/{uuid4()}/",  # publish media
        f"{tenant_prefix(_TENANT)}generated/{uuid4()}",  # no trailing slash
        f"{tenant_prefix(_TENANT)}generated//",  # empty segment
        f"{tenant_prefix(_TENANT)}generated/../brand/",  # traversal
        f"generated/{_TENANT}/{uuid4()}/",  # the legacy local store, not R2
    ],
)
def test_delete_prefix_refuses_anything_but_one_piece_folder(prefix: str) -> None:
    store = ListingStore()
    store.objects[f"{tenant_prefix(_TENANT)}brand/logo.png"] = (b"1", "image/png")
    with pytest.raises(TenantPrefixViolation):
        ObjectGate(store).delete_prefix(_TENANT, prefix, execute=True)
    assert store.batches == []


def test_final_digest_rejects_another_tenant_before_storage() -> None:
    gate = ObjectGate(_NullStore())
    with pytest.raises(TenantPrefixViolation):
        gate.sha256(_TENANT, media_key(uuid4(), uuid4(), "video"))


class _DeletingStore(_NullStore):
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_keys(self, keys: list[str]) -> None:
        self.deleted.extend(keys)


def test_a_payment_qr_is_deleted_only_by_its_exact_key() -> None:
    brand = uuid4()
    store = _DeletingStore()
    gate = ObjectGate(store)  # type: ignore[arg-type]
    good = f"t/{_TENANT}/whatsapp/payments/{brand}/{'a' * 32}.jpg"
    gate.delete_payment_qr(_TENANT, brand, good)
    assert store.deleted == [good]
    for bad in (
        f"t/{_TENANT}/whatsapp/payments/{brand}/",  # a prefix
        f"t/{_TENANT}/whatsapp/payments/{uuid4()}/{'a' * 32}.jpg",  # another brand
        f"t/{uuid4()}/whatsapp/payments/{brand}/{'a' * 32}.jpg",  # another tenant
        f"t/{_TENANT}/generated/{brand}/{'a' * 32}.jpg",  # another root
        f"t/{_TENANT}/whatsapp/payments/{brand}/../x/{'a' * 32}.jpg",
    ):
        with pytest.raises(TenantPrefixViolation):
            gate.delete_payment_qr(_TENANT, brand, bad)
    assert store.deleted == [good]


# -- Galería (m-24955918, ADR 39 amendment 2026-11-05) -------------------------------------


def _gallery(tenant: UUID, media: UUID) -> str:
    return f"{tenant_prefix(tenant)}gallery/{media}/"


def test_purgeable_roots_do_not_include_the_gallery() -> None:
    from qualify_shared.objects import PURGEABLE_ROOTS

    assert PURGEABLE_ROOTS == ("generated/",)
    store = ListingStore()
    with pytest.raises(TenantPrefixViolation):
        ObjectGate(store).delete_prefix(_TENANT, _gallery(_TENANT, uuid4()), execute=True)


def test_delete_gallery_media_empties_one_folder_and_nothing_else() -> None:
    store = ListingStore()
    media, sibling = uuid4(), uuid4()
    store.objects[f"{_gallery(_TENANT, media)}video.mp4"] = (b"12345", "video/mp4")
    store.objects[f"{_gallery(_TENANT, media)}poster.jpg"] = (b"12", "image/jpeg")
    keep = {
        f"{_gallery(_TENANT, sibling)}photo.jpg",
        f"{_gallery(_OTHER_TENANT, media)}video.mp4",  # same UUID, other tenant
        f"{tenant_prefix(_TENANT)}generated/{media}/r1/a.jpg",
        f"{tenant_prefix(_TENANT)}gallery/{str(media)[:8]}x/photo.jpg",
    }
    for key in keep:
        store.objects[key] = (b"9", "image/jpeg")
    result = ObjectGate(store).delete_gallery_media(_TENANT, media)
    assert result == PrefixDeletion(objects=2, bytes=7)
    assert set(store.objects) == keep


def test_delete_gallery_media_is_idempotent() -> None:
    store = ListingStore()
    media = uuid4()
    store.objects[f"{_gallery(_TENANT, media)}photo.jpg"] = (b"1", "image/jpeg")
    gate = ObjectGate(store)
    assert gate.delete_gallery_media(_TENANT, media).objects == 1
    assert gate.delete_gallery_media(_TENANT, media) == PrefixDeletion(0, 0)


@pytest.mark.parametrize("bad", ["", "../brand", f"{uuid4()}/../..", "generated/"])
def test_delete_gallery_media_accepts_only_a_uuid(bad: str) -> None:
    store = ListingStore()
    store.objects[f"{tenant_prefix(_TENANT)}brand/logo.png"] = (b"1", "image/png")
    with pytest.raises(TenantPrefixViolation):
        ObjectGate(store).delete_gallery_media(_TENANT, bad)  # type: ignore[arg-type]
    assert store.batches == [] and len(store.objects) == 1


class _LeakyStore(ListingStore):
    """A store that (wrongly) answers keys outside the prefix it was asked for."""

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        return [StoredObject(key=k, size=len(d)) for k, (d, _) in sorted(self.objects.items())]


def test_delete_gallery_media_never_deletes_outside_the_folder_even_if_the_store_leaks() -> None:
    store = _LeakyStore()
    media = uuid4()
    store.objects[f"{_gallery(_TENANT, media)}photo.jpg"] = (b"1", "image/jpeg")
    store.objects[f"{_gallery(_OTHER_TENANT, uuid4())}photo.jpg"] = (b"2", "image/jpeg")
    ObjectGate(store).delete_gallery_media(_TENANT, media)
    assert store.batches == [[f"{_gallery(_TENANT, media)}photo.jpg"]]


def test_list_gallery_media_returns_folder_ids_and_ages_of_this_tenant_only() -> None:
    from datetime import UTC, datetime

    moment = datetime(2026, 11, 5, tzinfo=UTC)

    class _Dated(_LeakyStore):
        def list_prefix(self, prefix: str) -> list[StoredObject]:
            return [
                StoredObject(key=k, size=len(d), last_modified=moment)
                for k, (d, _) in sorted(self.objects.items())
                if k.startswith(prefix)
            ]

    store = _Dated()
    media = uuid4()
    store.objects[f"{_gallery(_TENANT, media)}video.mp4"] = (b"123", "video/mp4")
    store.objects[f"{tenant_prefix(_TENANT)}gallery/stray.bin"] = (b"1", "x/y")
    store.objects[f"{tenant_prefix(_TENANT)}generated/{media}/a.jpg"] = (b"1", "image/jpeg")
    store.objects[f"{_gallery(_OTHER_TENANT, uuid4())}photo.jpg"] = (b"1", "image/jpeg")
    found = ObjectGate(store).list_gallery_media(_TENANT)
    assert sorted((o.media_id, o.size) for o in found if o.media_id) == [(media, 3)]
    assert [o.key for o in found if o.media_id is None] == [
        f"{tenant_prefix(_TENANT)}gallery/stray.bin"
    ]
    assert {o.last_modified for o in found} == {moment}
    assert all(o.key.startswith(f"{tenant_prefix(_TENANT)}gallery/") for o in found)
    # Even a store that leaks other prefixes cannot widen the listing.
    leaky = _LeakyStore()
    leaky.objects = dict(store.objects)
    assert all(
        o.key.startswith(f"{tenant_prefix(_TENANT)}gallery/")
        for o in ObjectGate(leaky).list_gallery_media(_TENANT)
    )
