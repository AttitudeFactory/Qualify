"""Do not submit paid video work when a stale media tunnel cannot serve the input."""

import httpx
import pytest

from qualify_api.creative.composition import _check_reference_url
from qualify_api.creative.media import REFERENCE_DOWNLOAD_TEXT, ark_failure_text


@pytest.mark.parametrize(
    "status,headers",
    [
        (530, {}),
        (404, {}),
        (302, {"location": "https://elsewhere.example"}),
        (200, {"content-type": "text/html", "content-length": "12"}),
        (200, {"content-type": "video/mp4", "content-length": "1"}),
    ],
)
def test_a_dead_or_wrong_media_response_is_rejected_without_leaking_its_token(
    monkeypatch, status, headers
):
    url = "https://media.example/public/media/private-token"
    monkeypatch.setattr(httpx, "head", lambda *a, **kw: httpx.Response(status, headers=headers))
    with pytest.raises(ValueError) as error:
        _check_reference_url(url, content_type="video/mp4", size=12)
    assert "private-token" not in str(error.value)


def test_downloadable_reference_passes_without_a_paid_generation(monkeypatch):
    def head(url, **kwargs):
        assert kwargs["follow_redirects"] is False
        return httpx.Response(200, headers={"content-type": "video/mp4", "content-length": "12"})

    monkeypatch.setattr(httpx, "head", head)
    _check_reference_url("https://media.example/video", content_type="video/mp4", size=12)


def test_network_failure_is_explained_without_the_bearer_url(monkeypatch):
    def head(url, **kwargs):
        raise httpx.ConnectError(url)

    monkeypatch.setattr(httpx, "head", head)
    with pytest.raises(ValueError, match="unreachable") as error:
        _check_reference_url(
            "https://media.example/private-token", content_type="video/mp4", size=12
        )
    assert "private-token" not in str(error.value)


def test_provider_download_error_explains_the_missing_reference_in_spanish():
    assert (
        ark_failure_text(
            "HTTP 400 InvalidParameter: content[2].video_url.url: resource download failed"
        )
        == REFERENCE_DOWNLOAD_TEXT
    )


def test_a_stopped_media_server_never_submits_the_paid_video(monkeypatch):
    from uuid import uuid4

    from qualify_api.creative import composition
    from qualify_api.creative.media import CLIP_NO_PUBLIC_URL

    from .test_creative_dispatch import _FakeGate, _wire_reference_links
    from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _kit
    from .test_creative_seedance_draft import _clip
    from .test_creative_seedance_video_input import REF, VideoInputSeedance, _producer

    _wire_reference_links(monkeypatch, _FakeGate({}))

    def unreachable(*args, **kwargs):
        raise ValueError("The public media server is unreachable")

    monkeypatch.setattr(composition, "_check_reference_url", unreachable)
    seedance = VideoInputSeedance()
    producer = _producer(seedance)
    producer._reference_links = composition.PublicReferenceLinks()
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_clip(clip_video_keys=(REF,)),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure == "invalid_parameters"
    assert outcome.detail == CLIP_NO_PUBLIC_URL
    assert seedance.requests == []
