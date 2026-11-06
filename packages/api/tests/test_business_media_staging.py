"""The Galería's chunked waiting room (m-24955918, ADR 47 §4.3), offline: files are written
chunk by chunk with their SHA-256, a file over the cap is cut and deleted before it is
whole on disk, extra videos are refused, and an interrupted upload leaves nothing."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qualify_api.catalog.business_media_staging import (
    MAX_UPLOAD_BYTES,
    OUTCOME_EMPTY,
    OUTCOME_FULL,
    OUTCOME_NO_SLOT,
    OUTCOME_STAGED,
    OUTCOME_TOO_LARGE,
    discard_staged,
    resolve_staged,
    stage_chunks,
    staging_dir,
)

TENANT = UUID("a0000000-0000-4000-8000-00000000ca01")
MIB = 1024 * 1024


@dataclass
class Chunk:
    filename: str
    data: bytes
    offset: int = 0
    content_type: str = ""


async def _aiter(chunks: Iterable[Chunk]) -> AsyncIterator[Chunk]:
    for chunk in chunks:
        yield chunk


def _stage(root: Path, chunks: Iterable[Chunk], *, max_videos: int = 3, **kw: int):
    return asyncio.run(
        stage_chunks(_aiter(chunks), root=root, tenant_id=TENANT, max_videos=max_videos, **kw)
    )


def test_the_cap_is_caddys_500mb() -> None:
    assert MAX_UPLOAD_BYTES == 500_000_000


def test_a_file_is_written_by_chunks_with_its_digest(tmp_path: Path) -> None:
    parts = [b"a" * 1000, b"b" * 1000, b"c" * 10]
    offsets = [0, 1000, 2000]
    [staged] = _stage(tmp_path, [Chunk("tienda.mov", p, o) for p, o in zip(parts, offsets)])
    assert staged.outcome == OUTCOME_STAGED and staged.is_video
    assert staged.bytes == 2010
    assert staged.sha256 == hashlib.sha256(b"".join(parts)).hexdigest()
    path = resolve_staged(tmp_path, TENANT, staged.relpath)
    assert staged.relpath == f"uploads/{TENANT}/gallery-staging/{staged.upload_id}"
    assert path.read_bytes() == b"".join(parts)


def _body_watcher(root: Path, total: int, chunk: int, seen: list[int]) -> Iterable[Chunk]:
    """Yields `total` bytes; before each chunk records how much is on disk."""
    sent = 0
    while sent < total:
        offset = sent
        folder = staging_dir(root, TENANT)
        files = list(folder.glob("*")) if folder.exists() else []
        seen.append(sum(f.stat().st_size for f in files))
        size = min(chunk, total - sent)
        sent += size
        yield Chunk("grande.mov", b"\0" * size, offset)


def test_a_body_over_the_cap_is_cut_without_reaching_disk_whole(tmp_path: Path) -> None:
    """Scaled model of «a 501 MB body»: cap 5 MB, body 5 MB + 1 MiB (the real-size run is
    the `slow` test below)."""
    cap = 5_000_000
    seen: list[int] = []
    [staged] = _stage(tmp_path, _body_watcher(tmp_path, cap + MIB, MIB, seen), max_bytes=cap)
    assert staged.outcome == OUTCOME_TOO_LARGE and staged.relpath == ""
    assert max(seen) <= cap  # never more than the cap on disk at any moment
    assert list(staging_dir(tmp_path, TENANT).iterdir()) == []


@pytest.mark.slow
def test_a_501_mb_body_is_cut_at_500_mb(tmp_path: Path) -> None:
    seen: list[int] = []
    [staged] = _stage(tmp_path, _body_watcher(tmp_path, 501_000_000, MIB, seen))
    assert staged.outcome == OUTCOME_TOO_LARGE
    assert max(seen) <= MAX_UPLOAD_BYTES
    assert list(staging_dir(tmp_path, TENANT).iterdir()) == []


def test_videos_beyond_the_free_slots_are_refused_photos_are_not(tmp_path: Path) -> None:
    chunks = [
        Chunk("uno.mp4", b"1"),
        Chunk("dos.mp4", b"2"),
        Chunk("foto.jpg", b"3"),
        Chunk("tres.mp4", b"4"),
    ]
    results = _stage(tmp_path, chunks, max_videos=1)
    assert [(r.filename, r.outcome) for r in results] == [
        ("uno.mp4", OUTCOME_STAGED),
        ("dos.mp4", OUTCOME_NO_SLOT),
        ("foto.jpg", OUTCOME_STAGED),
        ("tres.mp4", OUTCOME_NO_SLOT),
    ]
    assert len(list(staging_dir(tmp_path, TENANT).iterdir())) == 2


def test_two_files_with_the_same_name_stay_two_files(tmp_path: Path) -> None:
    """Phone pickers often name every file `image.jpg`: a new part starts at offset 0."""
    chunks = [
        Chunk("image.jpg", b"first-", 0),
        Chunk("image.jpg", b"photo", 6),
        Chunk("image.jpg", b"second", 0),
    ]
    first, second = _stage(tmp_path, chunks)
    assert first.outcome == second.outcome == OUTCOME_STAGED
    assert first.sha256 == hashlib.sha256(b"first-photo").hexdigest()
    assert second.sha256 == hashlib.sha256(b"second").hexdigest()
    assert first.relpath != second.relpath


def test_files_beyond_the_free_places_are_full(tmp_path: Path) -> None:
    chunks = [Chunk("a.jpg", b"1"), Chunk("b.mov", b"2"), Chunk("c.jpg", b"3")]
    results = _stage(tmp_path, chunks, max_files=1)
    assert [r.outcome for r in results] == [OUTCOME_STAGED, OUTCOME_FULL, OUTCOME_FULL]
    assert len(list(staging_dir(tmp_path, TENANT).iterdir())) == 1


def test_an_empty_file_is_not_kept(tmp_path: Path) -> None:
    [staged] = _stage(tmp_path, [Chunk("vacio.jpg", b"")])
    assert staged.outcome == OUTCOME_EMPTY
    assert list(staging_dir(tmp_path, TENANT).iterdir()) == []


def test_an_interrupted_upload_deletes_its_partial_files(tmp_path: Path) -> None:
    async def broken() -> AsyncIterator[Chunk]:
        yield Chunk("a.mp4", b"x" * 100)
        yield Chunk("b.jpg", b"y" * 100)
        raise ConnectionResetError("the owner closed the screen")

    with pytest.raises(ConnectionResetError):
        asyncio.run(stage_chunks(broken(), root=tmp_path, tenant_id=TENANT, max_videos=3))
    assert list(staging_dir(tmp_path, TENANT).iterdir()) == []


@pytest.mark.parametrize(
    "relpath",
    [
        f"uploads/{uuid4()}/gallery-staging/{uuid4()}",  # another tenant
        f"uploads/{TENANT}/gallery-staging/../../etc/passwd",
        f"uploads/{TENANT}/catalog/{uuid4()}",
        "",
    ],
)
def test_resolve_staged_refuses_anything_else(tmp_path: Path, relpath: str) -> None:
    with pytest.raises(ValueError):
        resolve_staged(tmp_path, TENANT, relpath)
    discard_staged(tmp_path, TENANT, relpath)  # never raises
