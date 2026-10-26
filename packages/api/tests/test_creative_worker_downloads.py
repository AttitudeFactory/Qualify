"""m-24852163 — platform-engineer's criterion, offline: `creative-worker` fits in 512 MiB
because downloads are capped (2–3 at once) and written to disk in chunks, never whole in
memory; the temporary file is removed also when the download fails."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import httpx
import pytest

from qualify_api.creative.worker import downloads as dl


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", 2), ("1", 1), ("3", 3), ("10", 3), ("0", 1), ("-4", 1), ("many", 2)],
)
def test_the_cap_is_two_by_default_and_never_above_three(raw: str, expected: int) -> None:
    assert dl.downloads_allowed({dl.DOWNLOADS_ENV: raw}) == expected


def test_the_gate_never_lets_more_than_its_limit_in() -> None:
    gate = dl.DownloadGate(2)
    inside = 0
    worst = 0
    lock = threading.Lock()

    def download() -> None:
        nonlocal inside, worst
        with gate.hold():
            with lock:
                inside += 1
                worst = max(worst, inside)
            time.sleep(0.02)
            with lock:
                inside -= 1

    threads = [threading.Thread(target=download) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert worst == 2 and gate.peak == 2


def test_a_gate_needs_a_place() -> None:
    with pytest.raises(ValueError):
        dl.DownloadGate(0)


def _client(body: bytes, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_video_is_written_in_chunks_and_removed_afterwards(tmp_path: Path) -> None:
    body = b"x" * (3 * 1024 + 17)
    with _client(body) as client:
        with dl.stream_to_tempfile(
            "https://vendor.example/v.mp4", client=client, chunk_bytes=1024, directory=str(tmp_path)
        ) as path:
            assert path.read_bytes() == body
            kept = path
    assert not kept.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_body_over_the_ceiling_is_cut_off_and_nothing_is_kept(tmp_path: Path) -> None:
    with _client(b"y" * 5000) as client:
        with pytest.raises(dl.DownloadTooLarge):
            with dl.stream_to_tempfile(
                "https://vendor.example/v.mp4",
                client=client,
                max_bytes=4096,
                chunk_bytes=1024,
                directory=str(tmp_path),
            ):
                pytest.fail("never yields an incomplete file")
    assert list(tmp_path.iterdir()) == []


def test_a_failed_download_removes_the_file(tmp_path: Path) -> None:
    with _client(b"gone", status=404) as client:
        with pytest.raises(httpx.HTTPStatusError):
            with dl.stream_to_tempfile(
                "https://vendor.example/v.mp4", client=client, directory=str(tmp_path)
            ):
                pytest.fail("never yields")
    assert list(tmp_path.iterdir()) == []


def test_an_error_inside_the_block_also_removes_the_file(tmp_path: Path) -> None:
    with _client(b"video") as client:
        with pytest.raises(RuntimeError):
            with dl.stream_to_tempfile(
                "https://vendor.example/v.mp4", client=client, directory=str(tmp_path)
            ):
                raise RuntimeError("R2 upload failed")
    assert list(tmp_path.iterdir()) == []
