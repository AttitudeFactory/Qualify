"""UI-6 (m-24921081): `creative_provider.submit_parts_brief` creates the PARENT of a video
by parts — a `shot_video` brief with the plan and the owner's ask — after reading the
month's vistas previas (all or nothing). Doubles only: no database, no vendor."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.creative.parts import PartsExtendUnavailable, PartsSourceInvalid
from qualify_api.creative.parts_plan import PLAN_MEDIA_KEY, PartsPlanRefused
from qualify_api.referentes import reel_analysis
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import ContentBrief, PartsRequest

from . import reel_parts_vm as parts_vm
from .creative_provider import PartsPreviewsShort, parent_media, submit_parts_brief
from .test_reel_parts_vm import MOCKUP
from .test_reel_review_state import four_parts

TENANT, BRAND, USER = uuid4(), uuid4(), uuid4()


@pytest.fixture(autouse=True)
def split_analysis(monkeypatch: pytest.MonkeyPatch) -> list[tuple[UUID, UUID]]:
    reads: list[tuple[UUID, UUID]] = []

    def read(tenant_id: UUID, analysis_id: UUID, **options: Any) -> Any:
        assert tenant_id == TENANT
        reads.append((tenant_id, analysis_id))
        return MOCKUP if analysis_id == MOCKUP.id else None

    monkeypatch.setattr(reel_analysis, "get_analysis", read)
    return reads


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


def test_fresh_parent_keeps_ui4_overrides_order_and_removed_history() -> None:
    """The production entry point is submit_parts_brief, without save_parts_plan."""
    from .test_part_editor import PHOTO, VIDEO, editor

    state = editor(2)
    state.set_reel_edit_open(False)
    state.edit_reel_part(state._reel_plan[3]["key"])
    state.set_reel_edit_mode("reference")
    state.save_reel_part()
    state.add_reel_part()
    video = {**VIDEO, "key": f"t/{TENANT}/own.mp4"}  # the business's own file
    state.reel_edit_videos = [video]
    state._reel_video_seconds = {video["key"]: 5.0}
    state.set_reel_edit_mode("edit")
    state.save_reel_part({"description": "Mi propio video"})
    new_key = state._reel_plan[-1]["key"]
    state.move_reel_part_up(new_key)
    state.remove_reel_part(state._reel_plan[0]["key"])
    content = Content(left=10)
    submit_parts_brief(
        TENANT,
        BRAND,
        USER,
        parts=parts_vm.plans(state._reel_plan),
        removed_parts=parts_vm.plans(state._reel_removed),
        scope="all",
        content=content,
        **state._generator_form(),
    )
    (brief,) = content.briefs
    assert len(brief.media.parts) == 4 and len(brief.media.parts_removed) == 1
    own = next(p for p in brief.media.parts if p.description == "Mi propio video")
    assert own.mode == "edit" and own.clip_video_keys == (video["key"],)
    assert own.clip_image_keys is None
    assert brief.media.clip_image_keys == (PHOTO["key"],)


@pytest.mark.parametrize("scope", ["all", "first"])
def test_fresh_parent_refuses_active_extend_before_balance_or_service(scope: str) -> None:
    from .test_reel_parts_state import planned

    class NeverUsed:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"must not touch the service: {name}")

    with pytest.raises(PartsExtendUnavailable):
        submit_parts_brief(
            TENANT,
            BRAND,
            USER,
            parts=parts_vm.plans(planned()._reel_plan),
            scope=scope,
            content=NeverUsed(),
        )


def test_removed_extend_does_not_block_creating_supported_active_parts() -> None:
    from .test_reel_parts_state import planned

    state = four_parts()
    state._reel_plan.pop()  # this canonical slot is removed, never active and removed twice
    removed = parts_vm.plans(planned()._reel_plan)[-1:]
    content = Content(left=10)
    submit_parts_brief(
        TENANT,
        BRAND,
        USER,
        parts=parts_vm.plans(state._reel_plan),
        removed_parts=removed,
        scope="all",
        content=content,
        **state._generator_form(),
    )
    assert len(content.briefs) == 1 and content.briefs[0].media.parts_removed == removed


def test_fresh_parent_checks_converted_slot_before_balance(
    split_analysis: list[tuple[UUID, UUID]],
) -> None:
    state = four_parts()
    state._reel_plan[-1]["plan"]["shot_indexes"] = [0]  # canonical cut is only 5 s
    plans = parts_vm.plans(state._reel_plan)

    class NeverUsed:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"must not touch the service: {name}")

    with pytest.raises(PartsSourceInvalid):
        submit_parts_brief(TENANT, BRAND, USER, parts=plans, scope="all", content=NeverUsed())
    assert split_analysis == [(TENANT, MOCKUP.id)]


def test_fresh_parent_checks_active_and_removed_marker_budget_before_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import creative_provider as provider

    state = four_parts()
    active = parts_vm.plans(state._reel_plan)
    forged_removed = active[-1:]  # claims the same continuation slot a second time
    checked: list[tuple[Any, ...]] = []
    guard = provider.check_split_parts_for_tenant

    def check(*, tenant_id: UUID, parts: tuple[Any, ...]) -> None:
        checked.append(parts)
        guard(tenant_id=tenant_id, parts=parts)

    class NeverUsed:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"must not touch the service: {name}")

    monkeypatch.setattr(provider, "check_split_parts_for_tenant", check)
    with pytest.raises(PartsSourceInvalid):
        submit_parts_brief(
            TENANT,
            BRAND,
            USER,
            parts=active,
            removed_parts=forged_removed,
            scope="first",
            content=NeverUsed(),
        )
    assert checked == [(*active, *forged_removed)]


@pytest.mark.parametrize("field", ["clip_image_keys", "clip_video_keys", "clip_audio_keys"])
@pytest.mark.parametrize("where", ["active", "removed"])
def test_fresh_parent_refuses_another_business_file_before_balance(field: str, where: str) -> None:
    """A part's own files come from the browser: one of another business's (active or
    removed part, photo, video or audio) is refused as `save_parts_plan` does, before
    the month's vistas previas are read or anything is created."""
    state = four_parts()
    plans = list(parts_vm.plans(state._reel_plan))
    foreign = plans[0].model_copy(update={field: (f"t/{uuid4()}/ajeno.mp4",)})
    active, removed = ([foreign, *plans[1:]], []) if where == "active" else (plans[1:], [foreign])

    class NeverUsed:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"must not touch the service: {name}")

    with pytest.raises(PartsPlanRefused) as refused:
        submit_parts_brief(
            TENANT,
            BRAND,
            USER,
            parts=active,
            removed_parts=removed,
            scope="all",
            content=NeverUsed(),
        )
    assert refused.value.reason == PLAN_MEDIA_KEY
