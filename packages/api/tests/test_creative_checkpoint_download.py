"""Streaming paid-video checkpoint: guarded URLs, bounded files and crash recovery."""

from __future__ import annotations

import io
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from qualify_shared.objects.gate import ObjectGate, ObjectNotFound
from qualify_shared.objects.keys import TenantPrefixViolation

from qualify_api.creative import media
from qualify_api.creative.worker.downloads import DownloadTooLarge


class Store:
    def __init__(self):
        self.data = {}
        self.paths = []
        self.puts = 0
        self.lose_ack = False
        self.head_error = False

    def size(self, key):
        if self.head_error:
            raise ConnectionError("storage unavailable")
        if key not in self.data:
            raise ObjectNotFound(key)
        return len(self.data[key])

    def put(self, key, source, content_type):
        assert content_type == "video/mp4"
        assert not isinstance(source, io.BytesIO)
        self.paths.append(Path(source.name))
        self.puts += 1
        pieces = []
        while chunk := source.read(1024):
            pieces.append(chunk)
        self.data[key] = b"".join(pieces)
        if self.lose_ack:
            raise ConnectionError("PUT committed but acknowledgment lost")


@pytest.fixture
def checkpoint(monkeypatch):
    backend = Store()
    store = media.R2ReadingMediaStore(None, ObjectGate(backend))
    tenant = uuid4()
    key = f"t/{tenant}/generated/draft/r1/queue-job.bin"
    calls = []
    original = httpx.Client

    def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "http://unsafe.invalid/video"})
        return httpx.Response(200, content=b"synthetic-video")

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler))
    )
    return store, backend, tenant, key, calls


def test_real_file_upload_and_idempotent_retry_after_lost_put_ack(checkpoint):
    store, backend, tenant, key, calls = checkpoint
    backend.lose_ack = True
    with pytest.raises(ConnectionError):
        store.checkpoint_download(tenant, key, "https://vendor.invalid/video")
    assert backend.data[key] == b"synthetic-video"
    assert all(not path.exists() for path in backend.paths)
    # Database has not recorded the result yet. A retry reuses this job's R2 object.
    store.checkpoint_download(tenant, key, "https://expired.invalid/video")
    assert backend.puts == 1 and len(calls) == 1


@pytest.mark.parametrize("url", ["http://unsafe.invalid/video", "https://vendor.invalid/redirect"])
def test_http_and_https_to_http_redirect_never_upload(checkpoint, url):
    store, backend, tenant, key, calls = checkpoint
    with pytest.raises(media.DownloadRefused):
        store.checkpoint_download(tenant, key, url)
    assert not backend.puts
    assert all(not call.startswith("http:") for call in calls)


def test_size_limit_refuses_before_storage_write(checkpoint, monkeypatch):
    store, backend, tenant, key, _ = checkpoint
    monkeypatch.setattr(media, "MAX_DOWNLOAD_BYTES", 3)
    with pytest.raises(DownloadTooLarge):
        store.checkpoint_download(tenant, key, "https://vendor.invalid/video")
    assert not backend.puts


def test_unknown_storage_outcome_does_not_download_again(checkpoint):
    store, backend, tenant, key, calls = checkpoint
    backend.head_error = True
    with pytest.raises(ConnectionError):
        store.checkpoint_download(tenant, key, "https://vendor.invalid/video")
    assert not calls and not backend.puts


def test_foreign_tenant_key_refused_before_network(checkpoint):
    store, backend, _, key, calls = checkpoint
    with pytest.raises(TenantPrefixViolation):
        store.checkpoint_download(uuid4(), key, "https://vendor.invalid/video")
    assert not calls and not backend.puts


def test_upload_remains_seekable_and_releases_consumed_pages(tmp_path, monkeypatch):
    from qualify_api.creative.worker import downloads

    path = tmp_path / "upload.mp4"
    path.write_bytes(b"0123456789" * 1024)
    released = []
    monkeypatch.setattr(
        downloads, "_release_cache", lambda fd, offset, size: released.append((offset, size))
    )
    with downloads.UncachedUploadFile(path, "r") as source:
        assert source.seekable()
        assert source.read(1024) == path.read_bytes()[:1024]
        source.seek(0)
        assert source.read(10) == b"0123456789"
        assert source.tell() == 10
    assert released == [(0, 1024), (0, 10)]


@pytest.mark.parametrize("error", ["EINVAL", "ENOSYS", "EOPNOTSUPP", "EIO"])
def test_cache_advice_unsupported_is_optional_but_io_failure_propagates(monkeypatch, error):
    import errno

    from qualify_api.creative.worker import downloads

    def advise(*args):
        raise OSError(getattr(errno, error), "synthetic filesystem result")

    monkeypatch.setattr(downloads.os, "posix_fadvise", advise, raising=False)
    monkeypatch.setattr(downloads.os, "POSIX_FADV_DONTNEED", 4, raising=False)
    if error == "EIO":
        with pytest.raises(OSError) as raised:
            downloads._release_cache(1, 0, 1024)
        assert raised.value.errno == errno.EIO
    else:
        downloads._release_cache(1, 0, 1024)
