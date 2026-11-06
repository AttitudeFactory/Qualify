"""Logical purge of pieces (m-24973446), offline: recognising the bucket's refusal, the
«is this object of a purged piece?» check every serving door uses, the server-side
readers that must fail as if the object were gone, and the `--pending` command.

The purge itself (marks, log, pending pass) needs `tenant_session`: it is in
`test_creative_retention_db.py`, against a gate over a store that refuses.
"""

from __future__ import annotations

import io
from uuid import UUID

import pytest
from botocore.exceptions import ClientError
from qualify_shared.objects.gate import ObjectNotFound

from qualify_api.creative import purged_media, retention_job
from qualify_api.creative.retention import is_delete_refused
from qualify_api.planner import worker

TENANT = UUID("a0000000-0000-4000-8000-000000973446")
OTHER = UUID("b0000000-0000-4000-8000-000000973446")
PURGED = UUID("c0000000-0000-4000-8000-000000973446")
LIVE = UUID("d0000000-0000-4000-8000-000000973446")


def _key(draft: UUID, tenant: UUID = TENANT) -> str:
    return f"t/{tenant}/generated/{draft}/r2/video.mp4"


@pytest.fixture
def lookup(monkeypatch: pytest.MonkeyPatch) -> list[tuple[UUID, UUID]]:
    asked: list[tuple[UUID, UUID]] = []

    def fake(tenant_id: UUID, draft_id: UUID) -> bool:
        asked.append((tenant_id, draft_id))
        return draft_id == PURGED

    purged_media.clear_cache()
    monkeypatch.setattr(purged_media, "lookup", fake)
    yield asked
    purged_media.clear_cache()


# -- recognising the refusal -----------------------------------------------------------


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "DeleteObjects")


@pytest.mark.parametrize(
    "code", ["ObjectLockedByBucketPolicy", "ObjectLocked", "AccessDenied", "InvalidObjectState"]
)
def test_a_refusing_bucket_is_recognised_from_boto(code: str) -> None:
    assert is_delete_refused(_client_error(code))


@pytest.mark.parametrize(
    "code", ["SlowDown", "InternalError", "NoSuchBucket", "InvalidAccessKeyId"]
)
def test_an_outage_is_not_a_refusal(code: str) -> None:
    assert not is_delete_refused(_client_error(code))
    assert not is_delete_refused(ConnectionError("R2 down"))
    assert not is_delete_refused(RuntimeError("R2 down"))


def test_per_key_errors_of_the_store_are_recognised_by_their_codes() -> None:
    """`R2ObjectStore.delete_keys` raises a RuntimeError naming the per-key codes."""
    assert is_delete_refused(
        RuntimeError("R2 refused to delete 3 object(s): ObjectLockedByBucketPolicy")
    )
    assert is_delete_refused(
        RuntimeError("R2 refused to delete 2 object(s): AccessDenied, ObjectLocked")
    )
    # one code that is not a refusal makes it an error, not a logical purge
    assert not is_delete_refused(
        RuntimeError("R2 refused to delete 2 object(s): AccessDenied, InternalError")
    )


def test_the_typed_refusal_of_the_store_is_recognised_once_it_lands() -> None:
    class DeleteRefused(Exception):  # VE-12's name; swap the helper when it is on main
        pass

    assert is_delete_refused(DeleteRefused("locked"))


# -- which objects are a piece's ----------------------------------------------------------


def test_only_this_tenants_piece_folders_name_a_piece() -> None:
    assert purged_media.piece_of_key(TENANT, _key(PURGED)) == PURGED
    assert purged_media.piece_of_key(OTHER, _key(PURGED)) is None  # another tenant's key
    for key in (
        f"t/{TENANT}/media/c1/video",
        f"t/{TENANT}/generated/not-a-uuid/r1/a.jpg",
        f"t/{TENANT}/generated/{PURGED}",  # no folder slash
        f"gallery/{TENANT}/{PURGED}/a.jpg",
        f"generated/{TENANT}/{PURGED}/a.jpg",  # pre-R2 local piece
        "",
    ):
        assert purged_media.piece_of_key(TENANT, key) is None


def test_the_check_asks_once_per_piece_and_never_for_other_keys(lookup) -> None:  # noqa: ANN001
    assert purged_media.is_purged_object(TENANT, _key(PURGED))
    assert purged_media.is_purged_object(TENANT, f"t/{TENANT}/generated/{PURGED}/r1/a.jpg")
    assert not purged_media.is_purged_object(TENANT, _key(LIVE))
    assert not purged_media.is_purged_object(TENANT, f"t/{TENANT}/brand/x/logo.png")
    assert lookup == [(TENANT, PURGED), (TENANT, LIVE)]  # cached per piece, other keys free


def test_a_failed_lookup_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(tenant_id: UUID, draft_id: UUID) -> bool:
        raise RuntimeError("db down")

    purged_media.clear_cache()
    monkeypatch.setattr(purged_media, "lookup", down)
    try:
        assert purged_media.is_purged_object(TENANT, _key(LIVE))  # fail closed
    finally:
        purged_media.clear_cache()


def test_refuse_if_purged_raises_what_a_deleted_object_raised(lookup) -> None:  # noqa: ANN001
    with pytest.raises(ObjectNotFound):
        purged_media.refuse_if_purged(TENANT, _key(PURGED))
    purged_media.refuse_if_purged(TENANT, _key(LIVE))


# -- the server-side readers ---------------------------------------------------------------


class _Gate:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def open_object(self, tenant_id: UUID, object_key: str) -> io.BytesIO:
        self.opened.append(object_key)
        return io.BytesIO(b"still in r2")


def test_the_generator_cannot_read_a_purged_piece_as_input(lookup, tmp_path) -> None:  # noqa: ANN001
    """Regenerate / variations / the carousel «De una pieza» / the piece download all read
    through `R2ReadingMediaStore`: an input from a purged piece fails like a deleted one."""
    from qualify_api.creative.media import LocalMediaStore, R2ReadingMediaStore

    gate = _Gate()
    store = R2ReadingMediaStore(LocalMediaStore(tmp_path), gate)
    with pytest.raises(ObjectNotFound):
        store.read(_key(PURGED))
    assert gate.opened == []
    assert store.read(_key(LIVE)) == b"still in r2"


def test_whatsapp_cannot_send_a_purged_piece(lookup) -> None:  # noqa: ANN001
    from qualify_api.whatsapp.attachments import ProductionBlobStore

    blobs = ProductionBlobStore()
    gate = _Gate()
    blobs._gate = gate  # the production gate is built lazily; this is its seat
    with pytest.raises(ObjectNotFound):
        blobs.read(TENANT, _key(PURGED))
    assert gate.opened == []
    assert blobs.read(TENANT, _key(LIVE)) == b"still in r2"


# -- the manual pass: `just piece-purge --pending` ------------------------------------------


def test_pending_runs_the_physical_pass_for_the_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[UUID] | None, bool]] = []
    monkeypatch.setattr(
        retention_job,
        "run_pending_purge",
        lambda ids, *, execute: calls.append((ids, execute)),
    )
    monkeypatch.setattr(
        retention_job,
        "run_piece_purge",
        lambda *a, **k: pytest.fail("--pending must not run the expiry purge"),
    )
    assert worker.main(["--tenant", str(TENANT), "--purge-pieces", "--pending"]) == 0
    assert worker.main(["--tenant", str(TENANT), "--purge-pieces", "--pending", "--execute"]) == 0
    assert calls == [([TENANT], False), ([TENANT], True)]


def test_pending_without_purge_pieces_is_refused() -> None:
    with pytest.raises(SystemExit):
        worker.main(["--tenant", str(TENANT), "--once", "--pending"])


def test_nothing_pending_builds_no_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        retention_job, "production_gate", lambda: pytest.fail("no gate without work")
    )
    assert retention_job.run_pending_purge(None, execute=True, discover=lambda: []) == []
