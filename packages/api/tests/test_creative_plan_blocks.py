"""m-25129409 (ADR 50 §13.2, PR 5): from the AI's plan to the Clip's blocks.

`blocks_from_plan` turns what «Hacer uno parecido» (`plan_from_analysis`) and «Pedir una
idea» (`propose_parts`) propose into blocks of the Clip's timeline, in the shape of the
contract of PR 1, with every part's texts and effects in seconds of the final video.
Offline and pure: the real effects library, a built analysis, no file, no database, no
vendor."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    AI_PART_KIND,
    ContentBrief,
    EffectUse,
    MediaInputs,
    PartRef,
    PartsProvenance,
    SourceSegment,
    VideoPartPlan,
    VideoTextLayer,
    ai_part_key,
)

from qualify_api.creative import plan_blocks
from qualify_api.creative.parts import plan_from_analysis
from qualify_api.creative.parts_ai import PartsProposal, parse_parts
from qualify_api.creative.parts_plan import PLAN_OTHER_REEL, PartsPlanRefused
from qualify_api.creative.plan_blocks import (
    BLOCKS_SPAN_LOST,
    BLOCKS_TOO_MANY,
    BLOCKS_TOO_MANY_AI,
    BLOCKS_TOO_MANY_TEXTS,
    PLAN_BLOCKS_TEXTS,
    ClipBlocks,
    PlanBlocksRefused,
    blocks_from_analysis,
    blocks_from_plan,
    blocks_from_proposal,
)
from qualify_api.creative.video_pipeline.ai_parts import CLIP_AI_PARTS_SWITCH
from qualify_api.creative.video_pipeline.recipe import CLIP_BLOCK_TRANSITIONS_SWITCH

from .test_content_service import TENANT_ID, make_brief
from .test_creative_parts import ANALYSIS_ID, analysis, shot

VIDEO = f"uploads/{TENANT_ID}/mi-cocina.mp4"
FADE = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
SMOKE = EffectUse(effect_id="humo_capa", version=1)
PROVENANCE = PartsProvenance(
    model_id="claude-sonnet-5", prompt_version="propose-parts-v3", cost_usd=Decimal("0.01")
)


@pytest.fixture
def ai_parts_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")


@pytest.fixture(autouse=True)
def _switches_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLIP_AI_PARTS_SWITCH, raising=False)
    monkeypatch.delenv(CLIP_BLOCK_TRANSITIONS_SWITCH, raising=False)


def _reel():
    # 0-5 s nobody on screen (edit), 5-9 s a person (new), 9-24 s one long take (two
    # parts, the second «Sigue a la anterior»)
    return analysis(
        shot(0, 0.0, 5.0),
        shot(1, 5.0, 9.0, people="observed", faces="observed", subject="una persona cocina"),
        shot(2, 9.0, 24.0, subject="la plancha con arepas"),
    )


def _idea() -> PartsProposal:
    rows = [
        {"description": "Una arepa recién salida de la plancha.", "seconds": 5},
        {"description": "Manos que la rellenan con queso.", "seconds": 4},
        {"description": "El local lleno a la hora del almuerzo.", "seconds": 6},
    ]
    parts, problems = parse_parts({"parts": rows})
    assert problems == ()
    return PartsProposal(parts, PROVENANCE)


def _own(seconds: float, **kw: object) -> SourceSegment:
    return SourceSegment(key=VIDEO, start_s=0.0, end_s=seconds, **kw)


def _local(seconds: int, **kw: object) -> VideoPartPlan:
    return VideoPartPlan(mode="local", seconds=seconds, segments=(_own(float(seconds)),), **kw)


# ---------------------------------------------------------------------------
# A reel's plan and an idea give valid blocks


@pytest.mark.usefixtures("ai_parts_on")
def test_a_reel_plan_gives_valid_ai_blocks() -> None:
    reel = _reel()
    plan = plan_from_analysis(reel, extend_on=True)
    blocks = blocks_from_analysis(reel, extend_on=True)

    assert len(blocks.segments) == len(plan) == len(blocks.ai_parts) == 4
    for at, (segment, entry) in enumerate(zip(blocks.segments, plan, strict=True)):
        assert segment.kind == AI_PART_KIND
        assert segment.key == ai_part_key(at)
        assert segment.ai_part_at == at
        assert (segment.start_s, segment.end_s, segment.speed) == (0.0, entry.seconds, 1.0)
    # the entries are the plan's parts, unchanged (mode, reason, cuts, the reel)
    assert blocks.ai_parts == plan
    assert [p.mode for p in blocks.ai_parts][-1] == "extend"
    assert blocks.text_layers == blocks.effects == ()
    assert blocks.provenance is None
    assert blocks.seconds == 24.0
    assert blocks.problems(tenant_id=TENANT_ID) == ()


@pytest.mark.usefixtures("ai_parts_on")
def test_an_idea_gives_valid_ai_blocks_with_its_provenance() -> None:
    idea = _idea()
    blocks = blocks_from_proposal(idea)

    assert [s.key for s in blocks.segments] == ["ai_part:0", "ai_part:1", "ai_part:2"]
    assert [p.description for p in blocks.ai_parts] == [p.description for p in idea.parts]
    assert all(p.mode == "reference" and p.analysis_id is None for p in blocks.ai_parts)
    assert blocks.provenance == PROVENANCE
    assert blocks.seconds == 15.0
    assert blocks.problems(tenant_id=TENANT_ID) == ()


def test_switched_off_the_blocks_are_built_and_only_switched_off() -> None:
    blocks = blocks_from_proposal(_idea())
    assert {p.code for p in blocks.problems()} == {"switched_off"}


@pytest.mark.usefixtures("ai_parts_on")
def test_local_parts_become_own_blocks_and_the_rest_ai_blocks() -> None:
    plan = (
        _local(4),
        VideoPartPlan(seconds=5, description="Una arepa en la plancha."),
        VideoPartPlan(
            mode="local",
            seconds=6,
            segments=(_own(2.0), SourceSegment(key=VIDEO, start_s=10.0, end_s=14.0)),
        ),
    )
    blocks = blocks_from_plan(plan)

    assert [s.kind for s in blocks.segments] == ["video", AI_PART_KIND, "video", "video"]
    assert blocks.segments[1].key == ai_part_key(0)
    assert len(blocks.ai_parts) == 1
    assert blocks.seconds == 15.0
    assert blocks.problems(tenant_id=TENANT_ID) == ()


# ---------------------------------------------------------------------------
# Texts and effects move to the Clip, in seconds of the final video


@pytest.mark.usefixtures("ai_parts_on")
def test_texts_and_effects_land_in_seconds_of_the_final_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, "on")
    hello = VideoTextLayer(text="Recién hechas", place="top")
    plan = (
        _local(4),
        VideoPartPlan(
            seconds=5,
            description="Una arepa en la plancha.",
            text_layers=(hello, VideoTextLayer(text="Pide la tuya", start_s=1.0, end_s=3.0)),
            effects=(SMOKE,),
        ),
        VideoPartPlan(
            seconds=3,
            description="El local de noche.",
            effects=(SMOKE,),
            transition_in=FADE,
        ),
    )
    blocks = blocks_from_plan(plan)

    # 4 + 5 + 3 s, minus the 0.5 s fade between the second and third part
    assert blocks.seconds == pytest.approx(11.5)
    # the second part runs from 4 s; its window ends where the third part starts (8.5 s),
    # so its text «until the end» stops there and never overlaps the next part's
    assert blocks.text_layers[0].model_dump(include={"text", "start_s", "end_s"}) == {
        "text": "Recién hechas",
        "start_s": 4.0,
        "end_s": 8.5,
    }
    assert (blocks.text_layers[1].start_s, blocks.text_layers[1].end_s) == (5.0, 7.0)
    # the same smoke over both parts in a row is ONE use, to the Clip's end
    assert len(blocks.effects) == 1
    assert (blocks.effects[0].start_s, blocks.effects[0].end_s) == (4.0, pytest.approx(11.5))
    # the join moved to the block, the entries carry no recipe of their own
    assert blocks.segments[2].transition_in == FADE
    assert all(
        not (p.effects or p.text_layers or p.segments or p.transition_in) for p in blocks.ai_parts
    )
    assert blocks.problems(tenant_id=TENANT_ID) == ()


@pytest.mark.usefixtures("ai_parts_on")
def test_a_local_parts_join_goes_to_its_first_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, "on")
    plan = (
        VideoPartPlan(seconds=5, description="Una arepa en la plancha."),
        VideoPartPlan(
            mode="local",
            seconds=6,
            segments=(_own(3.0), SourceSegment(key=VIDEO, start_s=5.0, end_s=8.0)),
            transition_in=FADE,
            text_layers=(VideoTextLayer(text="En casa"),),
        ),
    )
    blocks = blocks_from_plan(plan)

    assert blocks.segments[1].transition_in == FADE
    assert blocks.segments[2].transition_in is None
    # the local part starts at 5 - 0.5 = 4.5 s and runs to the end (10.5 s)
    assert (blocks.text_layers[0].start_s, blocks.text_layers[0].end_s) == (
        4.5,
        pytest.approx(10.5),
    )
    assert blocks.problems(tenant_id=TENANT_ID) == ()


def test_a_text_that_would_not_show_is_refused_never_dropped() -> None:
    plan = (
        VideoPartPlan(
            seconds=5,
            description="Una arepa en la plancha.",
            text_layers=(VideoTextLayer(text="Al final", start_s=4.8),),
        ),
        VideoPartPlan(seconds=3, description="El local.", transition_in=FADE),
    )
    with pytest.raises(PlanBlocksRefused) as refused:
        blocks_from_plan(plan)
    assert refused.value.reason == BLOCKS_SPAN_LOST
    assert PLAN_BLOCKS_TEXTS[BLOCKS_SPAN_LOST] == (
        "Un texto o un efecto queda justo en el cambio a la parte siguiente y no se vería. "
        "Muévelo un poco antes o quítalo."
    )


def test_more_texts_than_a_clip_holds_are_refused() -> None:
    texts = (VideoTextLayer(text="Uno", start_s=0, end_s=1), VideoTextLayer(text="Dos", start_s=2))
    plan = (
        VideoPartPlan(seconds=5, description="Una arepa.", text_layers=texts),
        VideoPartPlan(seconds=5, description="El local.", text_layers=texts),
    )
    with pytest.raises(PlanBlocksRefused) as refused:
        blocks_from_plan(plan)
    assert refused.value.reason == BLOCKS_TOO_MANY_TEXTS
    assert [p.code for p in refused.value.problems] == ["too_many_texts"]


# ---------------------------------------------------------------------------
# «Pedir una idea» with the track already built adds at the end


@pytest.mark.usefixtures("ai_parts_on")
def test_an_idea_is_added_after_the_track_without_deleting_anything() -> None:
    first = VideoPartPlan(seconds=4, description="La puerta del local.")
    track = MediaInputs(
        clip_reference_mode="local",
        segments=(
            _own(3.0),
            SourceSegment(key=ai_part_key(0), kind=AI_PART_KIND, start_s=0, end_s=4),
        ),
        ai_parts=(first,),
        text_layers=(VideoTextLayer(text="Bienvenidos", start_s=0, end_s=2),),
    )
    before = ClipBlocks.of_media(track)
    blocks = blocks_from_proposal(_idea(), after=before)

    assert blocks.segments[:2] == track.segments
    assert blocks.ai_parts[0] == first
    assert [s.key for s in blocks.segments[2:]] == ["ai_part:1", "ai_part:2", "ai_part:3"]
    assert blocks.text_layers == track.text_layers
    assert blocks.provenance == PROVENANCE
    assert blocks.seconds == 22.0
    assert blocks.problems(tenant_id=TENANT_ID) == ()


@pytest.mark.usefixtures("ai_parts_on")
def test_a_join_into_the_added_parts_cuts_what_the_track_had(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, "on")
    track = ClipBlocks(
        segments=(_own(4.0),),
        text_layers=(VideoTextLayer(text="Hola", start_s=0, end_s=4),),
        effects=(SMOKE,),
    )
    added = (
        VideoPartPlan(
            seconds=5,
            description="Una arepa en la plancha.",
            transition_in=FADE,
            text_layers=(VideoTextLayer(text="Pide la tuya"),),
        ),
    )
    blocks = blocks_from_plan(added, after=track)

    # the new part starts at 4 - 0.5 = 3.5 s: the old text and the old smoke («the whole
    # video» of before) stop there, and the two texts never overlap
    assert [(t.start_s, t.end_s) for t in blocks.text_layers] == [(0.0, 3.5), (3.5, 8.5)]
    assert (blocks.effects[0].start_s, blocks.effects[0].end_s) == (0.0, 3.5)
    assert blocks.problems(tenant_id=TENANT_ID) == ()


def test_an_idea_that_does_not_fit_eight_blocks_is_refused() -> None:
    track = ClipBlocks(segments=tuple(_own(2.0) for _ in range(6)))
    with pytest.raises(PlanBlocksRefused) as refused:
        blocks_from_proposal(_idea(), after=track)
    assert refused.value.reason == BLOCKS_TOO_MANY
    assert [p.code for p in refused.value.problems] == ["too_many_blocks"]
    assert PLAN_BLOCKS_TEXTS[BLOCKS_TOO_MANY].startswith("Tu video puede tener hasta 8")


def test_ai_parts_and_scenes_share_six_places() -> None:
    with pytest.raises(PlanBlocksRefused) as refused:
        blocks_from_proposal(_idea(), other_ai_children=4)
    assert refused.value.reason == BLOCKS_TOO_MANY_AI
    assert [p.code for p in refused.value.problems] == ["too_many_ai_children"]


# ---------------------------------------------------------------------------
# The plan holds against its reel, as in the parts flow


def test_a_plan_of_another_reel_is_refused() -> None:
    reel = analysis(shot(0, 0.0, 5.0), shot(1, 5.0, 9.0))
    plan = plan_from_analysis(reel)
    other = analysis(shot(0, 0.0, 5.0))
    other = type(other)(**{**other.__dict__, "id": UUID("00000000-0000-4000-8000-0000000000bb")})
    with pytest.raises(PartsPlanRefused) as refused:
        blocks_from_plan(plan, other)
    assert refused.value.reason == PLAN_OTHER_REEL
    assert plan[0].analysis_id == ANALYSIS_ID


def test_it_writes_and_pays_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def no(*_: object, **__: object) -> None:
        raise AssertionError("blocks_from_plan must not open a session")

    monkeypatch.setattr("qualify_api.creative.parts_plan.tenant_session", no)
    blocks = blocks_from_analysis(_reel())
    assert len(blocks.segments) == len(blocks.ai_parts)
    assert "tenant_session" not in vars(plan_blocks)
    assert "propose_parts" not in vars(plan_blocks)


# ---------------------------------------------------------------------------
# m-25026636: the Clip brief keeps who proposed its AI parts


def _local_clip(**media: object):
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(duration_seconds=5, clip_reference_mode="local", **media),
    )


def test_an_ideas_provenance_is_carried_into_the_local_clip_brief() -> None:
    idea = _idea()
    fields = blocks_from_proposal(idea).media_fields()

    assert fields["parts_provenance"] == PROVENANCE
    brief = _local_clip(**fields)
    assert brief.media.parts_provenance == PROVENANCE
    assert brief.media.ai_parts == blocks_from_proposal(idea).ai_parts
    stored = MediaInputs.model_validate(brief.media.model_dump(mode="json"))
    assert stored.parts_provenance == PROVENANCE


def test_a_reel_plan_or_the_owners_own_blocks_carry_no_provenance() -> None:
    fields = blocks_from_analysis(_reel(), extend_on=True).media_fields()

    assert fields["parts_provenance"] is None
    assert _local_clip(**fields).media.parts_provenance is None


def test_an_old_provenance_without_a_proposal_id_still_validates() -> None:
    stored = _local_clip(
        segments=(_own(5.0),),
        parts_provenance=PROVENANCE.model_copy(update={"proposal_id": UUID(int=7)}),
    ).model_dump(mode="json")
    assert stored["media"]["parts_provenance"]["proposal_id"] == str(UUID(int=7))
    del stored["media"]["parts_provenance"]["proposal_id"]  # as stored before it existed

    old = ContentBrief.model_validate(stored)

    assert old.media.parts_provenance is not None
    assert old.media.parts_provenance.proposal_id is None
    assert old.media.parts_provenance.model_id == PROVENANCE.model_id


@pytest.mark.parametrize(
    ("kind", "media"),
    [
        (ContentKind.CLIP, {"clip_reference_mode": "motion"}),
        (
            ContentKind.CLIP,
            {
                "clip_reference_mode": "local",
                "segments": (_own(5.0),),
                "part": PartRef(index=1, seconds=5, mode="local", segments=(_own(5.0),)),
            },
        ),
        (ContentKind.STATIC_FLYER, {}),
    ],
    ids=["motion clip", "a part of a video by parts", "a flyer"],
)
def test_a_provenance_is_refused_where_no_idea_proposed_parts(
    kind: ContentKind, media: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="video by parts or a local clip"):
        make_brief(
            variants=1,
            kind=kind,
            media=MediaInputs(duration_seconds=5, parts_provenance=PROVENANCE, **media),
        )
