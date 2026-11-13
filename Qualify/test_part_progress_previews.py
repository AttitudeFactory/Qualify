"""m-24992894: `part_progress_provider.part_previews` signs, for each part with a vista
previa to watch, its video and poster through `/r2media` (as «Tu video completo») and
gives its length — "" for a token it could not mint, never an error; no row for a part
without one."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_api.creative.fsm import FAILED, GENERATED
from qualify_api.creative.part_progress import PartFacts, derive_progress

from . import part_progress_provider as provider

NOW = 1_800_000_000.0
TENANT = UUID("9cd9637c-8bd0-4293-9d68-40a71c140c00")
PARENT = UUID("7a7a0000-0000-4000-8000-000000000003")
VIDEO = f"t/{TENANT}/generated/c/r1/clip-logo.mp4"
POSTER = f"t/{TENANT}/generated/c/r1/first-frame.jpg"


def _made(index: int, **kw: object) -> PartFacts:
    base: dict[str, object] = {
        "index": index,
        "mode": "reference",
        "seconds": 4,
        "draft_id": uuid4(),
        "status": GENERATED,
        "has_video": True,
        "preview": {"status": "draft", "created_at": NOW - 60},
        "video_key": VIDEO,
        "poster_key": POSTER,
        "video_seconds": 6.0,
    }
    base.update(kw)
    return PartFacts(**base)  # type: ignore[arg-type]


@pytest.fixture
def minted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[UUID, str, str]]:
    calls: list[tuple[UUID, str, str]] = []

    def issue(tenant_id: UUID, key: str, media_type: str) -> str:
        calls.append((tenant_id, key, media_type))
        return f"/r2media/{media_type}-{len(calls)}"

    monkeypatch.setattr(provider, "issue_view_path", issue)
    return calls


def test_each_part_with_a_preview_gets_its_signed_video_poster_and_length(
    minted: list[tuple[UUID, str, str]],
) -> None:
    progress = derive_progress(
        PARENT,
        [_made(1), _made(2, status=FAILED, has_video=False), _made(3, video_seconds=None)],
        now=NOW,
    )
    previews = provider.part_previews(TENANT, progress)
    assert set(previews) == {1, 3}
    first = previews[1]
    assert first == provider.PartPreview(
        index=1, video_url="/r2media/video-1", poster_url="/r2media/image-2", seconds=6.0
    )
    assert previews[3].seconds == 4.0  # no length recorded: the part's own seconds
    assert minted[:2] == [(TENANT, VIDEO, "video"), (TENANT, POSTER, "image")]


def test_a_token_that_cannot_be_minted_is_an_empty_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> str:
        raise ConnectionError("redis down")

    monkeypatch.setattr(provider, "issue_view_path", broken)
    progress = derive_progress(PARENT, [_made(1)], now=NOW)
    preview = provider.part_previews(TENANT, progress)[1]
    assert (preview.video_url, preview.poster_url, preview.seconds) == ("", "", 6.0)


def test_a_key_outside_r2_or_no_progress_mints_nothing(
    minted: list[tuple[UUID, str, str]],
) -> None:
    progress = derive_progress(PARENT, [_made(1, poster_key="uploads/x.jpg")], now=NOW)
    preview = provider.part_previews(TENANT, progress)[1]
    assert preview.poster_url == "" and preview.video_url
    assert provider.part_previews(TENANT, None) == {}
    assert [key for _, key, _ in minted] == [VIDEO]
