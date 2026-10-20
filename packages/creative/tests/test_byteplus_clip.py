"""The Seedance adapter's clip inputs (§ request 2026-10-14): the closing frame and the
2.x references — images, videos, audio — and what ModelArk refuses to mix."""

from __future__ import annotations

import pytest

from qualify_creative.adapters.byteplus_ark import SeedanceVideoAdapter

V1 = "seedance-1-0-pro-250528"
V2 = "dreamina-seedance-2-0-mini-260615"
IMG = "data:image/jpeg;base64,AAAA"
VIDEO = "https://qualify.example/public/media/tok-video"
AUDIO = "https://qualify.example/public/media/tok-audio"


ENDPOINTS = {V1: "ep-v1", V2: "ep-v2"}


def _body(**params: object) -> dict[str, object]:
    adapter = SeedanceVideoAdapter(model=V1, endpoints=ENDPOINTS)
    spec = adapter.spec({"prompt": "Un clip del producto", **params})
    return spec.body(adapter.wire_model(spec.model_id))


def test_the_closing_frame_rides_after_the_opening_one() -> None:
    body = _body(first_frame=IMG, last_frame="data:image/jpeg;base64,BBBB")
    roles = [item.get("role") for item in body["content"]]  # type: ignore[union-attr]
    assert roles == [None, "first_frame", "last_frame"]


def test_a_closing_frame_alone_is_refused() -> None:
    with pytest.raises(ValueError, match="needs a 'first_frame'"):
        _body(last_frame=IMG)


def test_references_go_to_a_2x_model_with_their_own_roles() -> None:
    body = _body(
        model=V2,
        reference_images=[IMG, IMG],
        reference_videos=[VIDEO],
        reference_audios=[AUDIO],
        duration_seconds=5,
    )
    content = body["content"]
    assert body["model"] == ENDPOINTS[V2]  # the per-request model's own endpoint
    assert [(item["type"], item.get("role")) for item in content] == [  # type: ignore[index, union-attr]
        ("text", None),
        ("image_url", "reference_image"),
        ("image_url", "reference_image"),
        ("video_url", "reference_video"),
        ("audio_url", "reference_audio"),
    ]
    assert content[3]["video_url"] == {"url": VIDEO}  # type: ignore[index]


def test_a_1x_model_takes_no_references() -> None:
    with pytest.raises(ValueError, match="takes no references"):
        _body(reference_images=[IMG])


def test_references_and_frame_roles_are_never_mixed() -> None:
    with pytest.raises(ValueError, match="cannot be mixed"):
        _body(model=V2, first_frame=IMG, reference_images=[IMG])


def test_reference_videos_and_audio_must_be_public_https() -> None:
    with pytest.raises(ValueError, match="not data URLs"):
        _body(model=V2, reference_videos=["data:video/mp4;base64,AAAA"])
    with pytest.raises(ValueError, match="https"):
        _body(model=V2, reference_audios=["http://insecure/a.mp3"])


def test_the_reference_limits_are_the_vendors() -> None:
    with pytest.raises(ValueError, match="at most 9 reference images"):
        _body(model=V2, reference_images=[IMG] * 10)
    with pytest.raises(ValueError, match="at most 3 reference videos"):
        _body(model=V2, reference_videos=[VIDEO] * 4)
