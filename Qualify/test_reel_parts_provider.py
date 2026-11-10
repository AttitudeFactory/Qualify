"""UI-6 (m-24921081): `creative_provider.submit_parts_brief` creates the PARENT of a video
by parts — a `shot_video` brief with the plan and the owner's ask — after reading the
month's vistas previas (all or nothing). Doubles only: no database, no vendor."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import ContentBrief, PartsRequest

from . import reel_parts_vm as parts_vm
from .creative_provider import PartsPreviewsShort, parent_media, submit_parts_brief
from .test_reel_review_state import four_parts

TENANT, BRAND, USER = uuid4(), uuid4(), uuid4()


class Content:
    """The composed content service, as far as the parent needs it."""

    def __init__(self, *, left: int, quota: int = 20, unlimited: bool = False) -> None:
        self.creations = SimpleNamespace(
            balance=lambda **_: SimpleNamespace(
                previews_left=left,
                preview_quota=quota,
                unlimited=unlimited,
                renews_on=date(2026, 12, 1),
            )
        )
        self.briefs: list[ContentBrief] = []
        self.draft = uuid4()

    def create_draft(
        self, *, tenant_id: UUID, brand_id: UUID, brief: ContentBrief, user_id: UUID
    ) -> UUID:
        assert (tenant_id, brand_id, user_id) == (TENANT, BRAND, USER)
        self.briefs.append(brief)
        return self.draft


def form_and_plans() -> tuple[dict[str, Any], Any]:
    state = four_parts()
    state.clip_audio = False
    return state._generator_form(), parts_vm.plans(state._reel_plan)


def submit(content: Content, scope: str) -> UUID:
    form, plans = form_and_plans()
    return submit_parts_brief(
        TENANT, BRAND, USER, parts=plans, scope=scope, content=content, **form
    )  # type: ignore[arg-type]


@pytest.mark.parametrize("scope", ["all", "first"])
def test_the_parent_carries_the_plan_and_the_ask(scope: str) -> None:
    content = Content(left=10)
    assert submit(content, scope) == content.draft
    (brief,) = content.briefs
    _, plans = form_and_plans()
    assert brief.kind is ContentKind.SHOT_VIDEO
    assert [(p.mode, p.seconds) for p in brief.media.parts] == [(p.mode, p.seconds) for p in plans]
    assert brief.media.parts_request == PartsRequest(scope=scope)  # type: ignore[arg-type]
    # a parent keeps none of a single clip's inputs
    assert brief.media.clip_video_keys == () and brief.media.source_reel is None
    assert brief.media.clip_reference_mode == "motion" and not brief.media.clip_audio
    assert brief.product_ref == "Smash doble"


def test_short_of_vistas_previas_creates_nothing() -> None:
    content = Content(left=2)
    with pytest.raises(PartsPreviewsShort) as caught:
        submit(content, "all")
    assert content.briefs == []
    assert caught.value.parts == 4 and caught.value.use.left == 2 and caught.value.use.short


def test_the_first_part_alone_needs_one() -> None:
    content = Content(left=1)
    submit(content, "first")
    assert len(content.briefs) == 1
    with pytest.raises(PartsPreviewsShort):
        submit(Content(left=0), "first")


def test_unlimited_or_no_quota_never_holds() -> None:
    for content in (Content(left=0, unlimited=True), Content(left=0, quota=0)):
        submit(content, "all")
        assert len(content.briefs) == 1


def test_parent_media_keeps_only_what_a_parent_takes() -> None:
    media = {
        "clip_image_keys": ["uploads/t/a.jpg"],
        "clip_image_roles": ["product"],
        "clip_video_keys": ["uploads/t/reel.mp4"],
        "clip_first_frame_key": "uploads/t/a.jpg",
        "clip_reference_mode": "edit",
        "source_reel": {"handle": "@x"},
        "clip_audio_keys": ["uploads/t/a.mp3"],
        "brand_logo_key": "uploads/t/logo.png",
    }
    assert parent_media(media) == {
        "clip_image_keys": ["uploads/t/a.jpg"],
        "clip_image_roles": ["product"],
        "brand_logo_key": "uploads/t/logo.png",
    }
