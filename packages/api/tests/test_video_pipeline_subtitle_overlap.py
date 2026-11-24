"""m-25026592 (decision 2026-11-23): a Clip with its copy as subtitles may not also carry
an owner's text at the bottom — the subtitles (y≈1360-1459 of 1920) and a `bottom` text
(y≈1410-1536) would cover each other. Refused on a NEW request, before any row, charge or
vendor call; never when a stored piece is read. Offline: fakes only."""

from __future__ import annotations

from typing import Any

import pytest
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    RECIPE_REFUSALS,
    ContentBrief,
    MediaInputs,
    PartRef,
    SourceSegment,
    VideoPartPlan,
    VideoTextLayer,
)

from qualify_api.creative.part_request import refusal_of
from qualify_api.creative.video_pipeline import RecipeRefused, validate_brief_recipe
from qualify_api.creative.video_pipeline.recipe import (
    TEXT_BOTTOM_WITH_SUBTITLES_TEXT,
    refuse_unbuilt_recipe,
    subtitle_overlap_problems,
)

from .test_content_service import (
    BRAND_ID,
    TENANT_ID,
    USER_ID,
    FakeRouter,
    make_brief,
    make_kit,
    make_service,
    make_voice,
)
from .test_creative_parts import parent_brief

OWN = f"uploads/{TENANT_ID}/mi-cocina.mp4"
BOTTOM = VideoTextLayer(text="Pide hoy", place="bottom")
TOP = VideoTextLayer(text="Shawarma mixto", place="top")
MIDDLE = VideoTextLayer(text="Shawarma mixto", place="middle")
OVERLAP = ("text_bottom_with_subtitles", None, "text_layers")


def _stretch() -> SourceSegment:
    return SourceSegment(key=OWN, start_s=0.0, end_s=5.0)


def _clip(**media: Any) -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(**{"duration_seconds": 5, **media}),
    )


def _local(**media: Any) -> ContentBrief:
    return _clip(clip_reference_mode="local", segments=(_stretch(),), **media)


def _problems(exc: RecipeRefused) -> list[tuple[str, int | None, str]]:
    return [(p.code, p.part, p.field) for p in exc.problems]


def test_the_code_is_appended_and_the_text_is_plain_spanish() -> None:
    # appended after its predecessors; ED-13 (m-25029108) appended six more after it
    assert RECIPE_REFUSALS[-7:] == (
        "text_bottom_with_subtitles",
        "unknown_text_motion",
        "typewriter_text_too_long",
        "bad_text_box_color",
        "bad_text_color",
        "unknown_text_size",
        "text_too_long_for_large",
    )
    assert TEXT_BOTTOM_WITH_SUBTITLES_TEXT == (
        "Abajo se ven los subtítulos y tu texto se taparía. "
        "Elige otra posición o apaga los subtítulos."
    )


def test_a_bottom_text_is_the_default_place_and_is_refused_too() -> None:
    """A text the owner never placed sits at the bottom (`VideoTextLayer.place`)."""
    brief = _local(clip_subtitles=True, text_layers=(VideoTextLayer(text="Pide hoy"),))
    assert [(p.code, p.part, p.field) for p in subtitle_overlap_problems(brief)] == [OVERLAP]


# ---------------------------------------------------------------------------
# Refused before any row, charge or vendor call — one test per path


def test_a_local_clip_with_subtitles_and_a_bottom_text_is_refused_before_anything() -> None:
    router = FakeRouter()
    service, repo, dispatcher = make_service(router=router, kit=make_kit(), voice=make_voice())
    brief = _local(clip_subtitles=True, text_layers=(TOP, BOTTOM))
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID)
    assert _problems(refused.value) == [OVERLAP]
    assert repo.drafts == {} and repo.briefs == {}
    assert dispatcher.calls == [] and router.requests == []  # nothing written, paid or sent


def test_a_seedance_clip_with_subtitles_and_a_bottom_text_is_refused_before_anything() -> None:
    """Made by Seedance (`motion`): today a text over it is also `recipe_unavailable`;
    once EF-14 composes it, this rule alone still refuses the overlap."""
    router = FakeRouter()
    service, repo, dispatcher = make_service(router=router, kit=make_kit(), voice=make_voice())
    brief = _clip(clip_subtitles=True, text_layers=(BOTTOM,))
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID)
    assert OVERLAP in _problems(refused.value)
    assert repo.drafts == {} and repo.briefs == {}
    assert dispatcher.calls == [] and router.requests == []


def test_parts_carry_no_subtitles_so_the_rule_does_not_apply_to_them() -> None:
    """A part (a child Clip) is born with `clip_subtitles` False and the producer lays
    subtitles only on a normal Clip; a parent drops the switch. Neither is refused by
    this rule, whatever its texts — so `PartsRefusal` needs no new code."""
    child = _clip(clip_subtitles=True, part=PartRef(index=1, seconds=5, text_layers=(BOTTOM,)))
    parent = parent_brief(
        VideoPartPlan(mode="local", seconds=5, segments=(_stretch(),), description="Uno."),
        clip_subtitles=True,
    )
    assert subtitle_overlap_problems(child) == ()
    assert subtitle_overlap_problems(parent) == ()
    assert "text_bottom_with_subtitles" not in {
        p.code for p in validate_brief_recipe(child, tenant_id=TENANT_ID)
    }


def test_the_refusal_reaches_a_part_request_as_a_bad_recipe() -> None:
    """Should it ever reach `create_parts`, it reads as any refused recipe."""
    with pytest.raises(RecipeRefused) as refused:
        refuse_unbuilt_recipe(
            _local(clip_subtitles=True, text_layers=(BOTTOM,)), tenant_id=TENANT_ID
        )
    assert refusal_of(refused.value) == ("effects_invalid", None, 0)


# ---------------------------------------------------------------------------
# Not refused


@pytest.mark.parametrize("text", [TOP, MIDDLE], ids=["top", "middle"])
def test_subtitles_with_a_text_above_or_in_the_middle_are_not_refused(
    monkeypatch: pytest.MonkeyPatch, text: VideoTextLayer
) -> None:
    from qualify_api.creative.queue_dispatch import SWITCH

    monkeypatch.setenv(SWITCH, "queue")  # a `local` Clip is made only with the queue
    brief = _local(clip_subtitles=True, text_layers=(text,))
    assert subtitle_overlap_problems(brief) == ()
    service, repo, _ = make_service(kit=make_kit(), voice=make_voice())
    draft = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID
    )
    assert draft in repo.drafts


def test_a_bottom_text_without_subtitles_is_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative.queue_dispatch import SWITCH

    monkeypatch.setenv(SWITCH, "queue")
    brief = _local(clip_subtitles=False, text_layers=(BOTTOM,))
    assert subtitle_overlap_problems(brief) == ()
    service, repo, _ = make_service(kit=make_kit(), voice=make_voice())
    draft = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID
    )
    assert draft in repo.drafts


def test_subtitles_without_any_text_are_not_refused() -> None:
    assert subtitle_overlap_problems(_clip(clip_subtitles=True)) == ()


def test_a_stored_piece_with_both_still_reads() -> None:
    """The rule runs on a new request only: a piece stored before it (or by an older
    screen) with subtitles and a bottom text reads back unchanged — the brief's own
    validation never refuses it."""
    stored = _local(clip_subtitles=True, text_layers=(BOTTOM,)).model_dump(mode="json")
    read = ContentBrief.model_validate(stored, context={"preserve_stored_logo_mode": True})
    assert read.media.clip_subtitles is True
    assert read.media.text_layers == (BOTTOM,)
