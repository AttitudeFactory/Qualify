"""EF-02 (ADR 50): the recipe of a video with effects — `recipe_of` (1 part for a Clip, N
for a video by parts), `validate_recipe`'s codes, the stretches' files checked against
the business (two tenants), `local` failing closed everywhere a video could start (the
service, the parts, the producer), and `save_parts_plan` keeping each part's effects when
the owner reorders or joins parts. Offline: no database, no network, no paid call."""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind, FailureReason
from qualify_creative.layer_spec import LAYOUT_VERSION
from qualify_creative.schemas import (
    ContentBrief,
    EffectUse,
    MediaInputs,
    PartRef,
    SourceSegment,
    VideoPartPlan,
    VideoRecipe,
    VideoTextLayer,
)

from qualify_api.creative import parts_plan
from qualify_api.creative.media import LOCAL_CLIP_UNAVAILABLE, _key_problems
from qualify_api.creative.part_request import refusal_of
from qualify_api.creative.parts import PartsLocalUnavailable
from qualify_api.creative.parts_plan import (
    MERGED_PARTS_REASON,
    PLAN_EFFECTS,
    PLAN_MEDIA_KEY,
    PLAN_MERGE_EFFECTS,
    PLAN_MERGE_TEXT,
    PartsPlanRefused,
    merge_short_part,
    merged_recipe,
    save_parts_plan,
)
from qualify_api.creative.video_pipeline import (
    PartRecipe,
    RecipeRefused,
    recipe_of,
    validate_brief_recipe,
    validate_recipe,
    validate_video_recipe,
)

from .test_content_service import (
    BRAND_ID,
    TENANT_ID,
    USER_ID,
    make_brief,
    make_kit,
    make_service,
    make_voice,
)
from .test_creative_parts import analysis, parent_brief, shot, world

OTHER_TENANT = UUID("0b0b0000-0000-4000-8000-0000000000ee")
OWN = f"uploads/{TENANT_ID}/mi-cocina.mp4"
FOREIGN = f"uploads/{OTHER_TENANT}/su-cocina.mp4"
FIXTURES = Path(__file__).parents[2] / "creative" / "tests" / "fixtures" / "briefs_f55f1d73"

SMOKE = EffectUse(effect_id="humo_capa", version=1, params={"intensity": 0.8, "zone": "top"})
TEXT = EffectUse(effect_id="texto", version=1, params={"size": "large"})
FAST = EffectUse(effect_id="camara_rapida", version=1, params={"speed": 12.0})
FADE = EffectUse(effect_id="fundido", version=1, params={"duration_s": 0.5})
EMBERS_AI = EffectUse(effect_id="brasas", version=1)
VAPOR = EffectUse(effect_id="vapor_capa", version=1)
WORDS = VideoTextLayer(text="Shawarma mixto", place="top")


@pytest.fixture(autouse=True)
def layers_offered(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory):
    """v1 does not offer the smoke, ember and steam layers yet (their loops are not
    recorded) nor `camara_rapida` (D-T3: fast motion is `segments[].speed`). These tests
    check the recipe rules with all four OFFERED (previews in a temporary folder), except
    the two `test_the_real_v1_library_*` tests, which read v1 itself."""
    from qualify_creative.effects import parse_library, preview_file

    from qualify_api.creative.video_pipeline import recipe

    root = tmp_path_factory.mktemp("effects_assets")
    raw = json.loads(
        (
            Path(__file__).parents[2] / "creative/src/qualify_creative/effects_data/v1.json"
        ).read_text(encoding="utf-8")
    )
    for entry in raw["entries"]:
        if entry["id"] in ("humo_capa", "brasas_capa", "vapor_capa", "camara_rapida"):
            preview = f"effects/{entry['id']}/v1/preview.webm"
            preview_file(preview, root).parent.mkdir(parents=True, exist_ok=True)
            preview_file(preview, root).write_bytes(b"webm")
            entry.update(offered=True, preview_asset=preview)
    library = parse_library(raw, assets_root=root)
    monkeypatch.setattr(recipe, "load_effects", lambda: library)
    return library


def test_the_real_v1_library_refuses_an_unoffered_layer() -> None:
    from qualify_creative.effects import load_effects

    # EF-08: the default library (v3) offers the recorded layers; v2 still does not
    part = PartRecipe(index=1, seconds=5, effects=(SMOKE,))
    problems = validate_recipe((part,), video_by_parts=False, library=load_effects("v2"))
    assert [(p.code, p.field, p.effect_id) for p in problems] == [
        ("not_offered", "effects[0]", "humo_capa")
    ]


def test_the_real_v3_library_offers_the_recorded_layers() -> None:
    """EF-08 (m-25029102): smoke, embers and steam are recorded and offered from v3."""
    from qualify_creative.effects import load_effects

    for layer in ("humo_capa", "brasas_capa", "vapor_capa"):
        use = SMOKE.model_copy(update={"effect_id": layer, "params": ()})
        part = PartRecipe(index=1, seconds=5, effects=(use,))
        assert validate_recipe((part,), video_by_parts=False, library=load_effects()) == ()


def _stretch(key: str = OWN) -> SourceSegment:
    return SourceSegment(key=key, start_s=2.0, end_s=62.0, speed=12.0, rotate=90)


def _clip(**media: Any) -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(**{"duration_seconds": 5, **media}),
    )


def _codes(problems: tuple) -> list[str]:
    return [p.code for p in problems]


def ledger_price(row: Any) -> tuple[str, int, int, int]:
    """What a charge row of the in-memory ledger priced: (kind, creations, vistas previas,
    video seconds)."""
    price = row.price
    return price.request_kind, price.weight, price.videos, price.video_seconds


# ---------------------------------------------------------------------------
# recipe_of


def test_a_clip_is_a_recipe_of_one_part_with_its_effects() -> None:
    brief = _clip(effects=(SMOKE, TEXT), text_layer=WORDS, mode_reason="own_video_local")
    (part,) = recipe_of(brief)
    assert (part.index, part.mode, part.seconds) == (1, "reference", 5)
    assert part.effects == (SMOKE, TEXT) and part.text_layers == (WORDS,)
    assert part.transition_in is None and part.mode_reason == "own_video_local"
    edit = _clip(
        clip_reference_mode="edit",
        clip_video_keys=(OWN,),
        clip_image_keys=(f"uploads/{TENANT_ID}/foto.jpg",),
    )
    assert recipe_of(edit)[0].mode == "edit"


def test_a_local_clip_reads_as_a_local_part_with_its_stretches() -> None:
    (part,) = recipe_of(_clip(clip_reference_mode="local", segments=(_stretch(),)))
    assert part.mode == "local" and part.segments == (_stretch(),) and part.has_own_video


def test_a_parent_is_its_plan_in_order_with_its_transitions() -> None:
    plan = (
        VideoPartPlan(seconds=5, description="Uno.", effects=(SMOKE,)),
        VideoPartPlan(seconds=4, description="Dos.", transition_in=FADE, text_layer=WORDS),
        VideoPartPlan(mode="local", seconds=6, segments=(_stretch(),), effects=(FAST,)),
    )
    recipe = recipe_of(parent_brief(*plan))
    assert [p.index for p in recipe] == [1, 2, 3]
    assert [p.seconds for p in recipe] == [5, 4, 6]
    assert [p.effects for p in recipe] == [(SMOKE,), (), (FAST,)]
    assert [p.transition_in for p in recipe] == [None, FADE, None]
    assert recipe[1].text_layers == (WORDS,) and recipe[2].mode == "local"


def test_a_child_is_its_part_at_its_index() -> None:
    part = PartRef(index=3, seconds=3, effects=(SMOKE,), text_layer=WORDS)
    child = _clip(part=part, duration_seconds=4)
    (recipe,) = recipe_of(child)
    assert (recipe.index, recipe.seconds, recipe.effects) == (3, 3, (SMOKE,))
    assert recipe.transition_in is None  # it lives on the parent's plan


def test_a_part_child_carries_its_parts_recipe_never_the_parents_text() -> None:
    from qualify_api.creative.parts import _child_brief

    entry = VideoPartPlan(seconds=5, description="Uno.", effects=(SMOKE,), transition_in=None)
    parent = parent_brief(entry, text_layer=VideoTextLayer(text="Todo el video"))
    child = _child_brief(parent, entry, 1, None)
    assert child.media.effects == (SMOKE,) and child.media.text_layers == ()
    assert child.media.part is not None and child.media.part.effects == (SMOKE,)
    assert recipe_of(child)[0].effects == (SMOKE,)


def test_other_kinds_have_no_recipe() -> None:
    assert recipe_of(make_brief()) == ()


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_a_brief_from_before_the_recipe_has_an_empty_valid_recipe(path: Path) -> None:
    brief = ContentBrief.model_validate(json.loads(path.read_text(encoding="utf-8")))
    for part in recipe_of(brief):
        assert part.effects == () and part.segments == () and part.text_layers == ()
        assert part.transition_in is None and part.mode != "local"
    assert validate_brief_recipe(brief, tenant_id=TENANT_ID) == ()


def test_a_part_recipe_round_trips_through_json() -> None:
    part = PartRecipe(
        index=2,
        mode="local",
        seconds=6,
        effects=(FAST,),
        segments=(_stretch(),),
        transition_in=FADE,
    )
    assert PartRecipe.model_validate_json(part.model_dump_json()) == part


# ---------------------------------------------------------------------------
# validate_recipe: every refusal with its code, all at once


def test_a_transition_in_a_normal_clip_is_refused() -> None:
    clip = PartRecipe(index=1, seconds=5, transition_in=FADE)
    problems = validate_recipe((clip,), video_by_parts=False)
    assert _codes(problems) == ["transition_on_clip"]
    assert problems[0].field == "transition_in" and problems[0].part is None
    effect = validate_brief_recipe(_clip(effects=(FADE,)))
    assert _codes(effect) == ["transition_on_clip"]


def test_a_transition_on_the_first_part_is_refused() -> None:
    first = PartRecipe(index=1, seconds=5, transition_in=FADE)
    assert _codes(validate_recipe((first,), video_by_parts=True)) == ["transition_on_first_part"]
    with pytest.raises(ValueError, match="transition_on_first_part"):
        parent_brief(VideoPartPlan(seconds=5, transition_in=FADE))


def test_local_without_own_video_is_refused() -> None:
    part = PartRecipe(index=1, mode="local", seconds=5)
    assert _codes(validate_recipe((part,), video_by_parts=False)) == ["local_needs_own_video"]


def test_local_with_an_ai_effect_is_refused() -> None:
    part = PartRecipe(
        index=1, mode="local", seconds=5, segments=(_stretch(),), effects=(EMBERS_AI,)
    )
    codes = _codes(validate_recipe((part,), video_by_parts=False))
    assert codes == ["not_offered", "local_with_ai_effect"]


def test_every_problem_comes_back_with_its_part_and_field() -> None:
    parts = (
        PartRecipe(index=1, seconds=5, effects=(EffectUse(effect_id="chispas", version=1),)),
        PartRecipe(
            index=2,
            seconds=5,
            effects=(EffectUse(effect_id="humo_capa", version=1, params={"intensity": 9.0}),),
            transition_in=SMOKE,
        ),
    )
    problems = validate_recipe(parts, video_by_parts=True)
    assert [(p.code, p.part, p.field) for p in problems] == [
        ("unknown_effect", 1, "effects[0]"),
        ("param_out_of_range", 2, "effects[0].params.intensity"),
        ("transition_not_a_transition", 2, "transition_in"),
    ]


def test_validation_reads_no_network_nor_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """The library is the process's cached one: nothing else is read. Every real DB door
    (`qualify_shared.db`, where it is defined and where it is re-exported) and the socket
    fail the test if touched."""
    import socket

    import qualify_shared.db as db
    import qualify_shared.db.admin as db_admin
    import qualify_shared.db.credential as db_credential
    import qualify_shared.db.session as db_session

    def closed(*_a: object, **_k: object) -> None:
        pytest.fail("database")

    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network"))
    for module, name in (
        (db, "tenant_session"),
        (db, "admin_session"),
        (db, "credential_session"),
        (db_session, "tenant_session"),
        (db_admin, "admin_session"),
        (db_credential, "credential_session"),
        (parts_plan, "tenant_session"),
    ):
        monkeypatch.setattr(module, name, closed)
    part = PartRecipe(index=1, mode="local", seconds=5, segments=(_stretch(),), effects=(FAST,))
    assert validate_recipe((part,), video_by_parts=False, tenant_id=TENANT_ID) == ()
    parent = parent_brief(VideoPartPlan(seconds=5, effects=(SMOKE,)), text_layer=WORDS)
    assert validate_brief_recipe(parent, tenant_id=TENANT_ID) == ()


# ---------------------------------------------------------------------------
# The stretches' files are the business's (two tenants)


def test_a_stretch_of_another_business_is_refused() -> None:
    mine = PartRecipe(index=1, mode="local", seconds=5, segments=(_stretch(OWN),))
    theirs = PartRecipe(index=1, mode="local", seconds=5, segments=(_stretch(FOREIGN),))
    assert validate_recipe((mine,), video_by_parts=False, tenant_id=TENANT_ID) == ()
    problems = validate_recipe((theirs,), video_by_parts=False, tenant_id=TENANT_ID)
    assert [(p.code, p.field) for p in problems] == [("foreign_key", "segments[0].key")]
    # the same stretch is the other business's own
    assert validate_recipe((theirs,), video_by_parts=False, tenant_id=OTHER_TENANT) == ()
    bad = PartRecipe(
        index=1, mode="local", seconds=5, segments=(_stretch(f"uploads/{TENANT_ID}/../x.mp4"),)
    )
    assert _codes(validate_recipe((bad,), video_by_parts=False, tenant_id=TENANT_ID)) == [
        "malformed_key"
    ]


def test_the_producer_refuses_a_stretch_of_another_business_before_any_read() -> None:
    kit = make_kit()
    clip = _clip(effects=(SMOKE,), segments=(_stretch(FOREIGN),))
    assert _key_problems(TENANT_ID, clip, kit) == ([], [FOREIGN])
    assert _key_problems(OTHER_TENANT, clip, kit) == ([], [])
    plan = VideoPartPlan(mode="local", seconds=5, segments=(_stretch(FOREIGN),))
    parent = parent_brief(VideoPartPlan(seconds=5), parts_removed=(plan,))
    assert FOREIGN in _key_problems(TENANT_ID, parent, kit)[1]
    child = _clip(part=PartRef(index=1, seconds=5, segments=(_stretch(FOREIGN),)))
    assert _key_problems(TENANT_ID, child, kit)[1] == [FOREIGN]


def test_saving_a_plan_with_a_stretch_of_another_business_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = VideoPartPlan(mode="local", seconds=5, segments=(_stretch(FOREIGN),), description="X.")
    _saving(monkeypatch, parent_brief(VideoPartPlan(seconds=5, description="Uno.")))
    with pytest.raises(PartsPlanRefused) as refused:
        save_parts_plan(
            tenant_id=TENANT_ID,
            parent_id=uuid4(),
            parts=(VideoPartPlan(seconds=5, description="Uno."), entry),
        )
    assert refused.value.reason == PLAN_MEDIA_KEY


# ---------------------------------------------------------------------------
# `local` (EF-06): its stretches are made; what the engine does not draw yet fails closed


def test_a_local_clip_with_effects_is_refused_before_any_row_or_dispatch() -> None:
    """EF-06 makes a `local` Clip from its stretches and EF-08 lays the library's layers
    over it; any OTHER effect (here fast motion as an effect) is still refused — and only
    it: neither `local` nor its stretches."""
    service, repo, dispatcher = make_service(kit=make_kit(), voice=make_voice())
    brief = _clip(clip_reference_mode="local", segments=(_stretch(),), effects=(FAST,))
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID)
    assert [(p.code, p.field) for p in refused.value.problems] == [
        ("recipe_unavailable", "effects")
    ]
    assert repo.drafts == {} and repo.briefs == {} and dispatcher.calls == []


def test_a_refused_recipe_is_refused_before_any_row_with_every_code() -> None:
    service, repo, dispatcher = make_service(kit=make_kit(), voice=make_voice())
    brief = _clip(effects=(EMBERS_AI, FAST), segments=(_stretch(FOREIGN),))
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID)
    assert set(_codes(refused.value.problems)) == {
        "not_offered",
        "foreign_key",
        "recipe_unavailable",
    }
    assert repo.drafts == {} and dispatcher.calls == []


def test_the_effects_pipeline_version_is_the_servers() -> None:
    """A caller cannot pick the effects pipeline: a brief with NO recipe that claims a
    version is stored at 0 (and made as today)."""
    service, repo, dispatcher = make_service(kit=make_kit(), voice=make_voice())
    brief = _clip(effects_pipeline_version=3)
    draft = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID
    )
    stored = repo.briefs[repo.drafts[draft].brief_id]
    assert stored.media.effects_pipeline_version == 0 and stored.media.effects == ()
    assert dispatcher.calls == [(TENANT_ID, draft)]


@pytest.mark.parametrize(
    ("media", "field"),
    [
        # (EF-14 composes the library's layers and the texts over a 9:16 Seedance Clip:
        # `test_video_pipeline_recompose.py`)
        # D4 (EF-11): stretches of own video never go to an `edit` — only a `reference`
        # (`motion`) piece opens on them, prepared
        (
            {
                "clip_reference_mode": "edit",
                "clip_video_keys": (f"uploads/{TENANT_ID}/reel.mp4",),
                "clip_image_keys": (f"uploads/{TENANT_ID}/p.jpg",),
                "segments": (_stretch(),),
            },
            "segments",
        ),
    ],
)
def test_any_recipe_is_refused_until_the_engine_exists(media: dict, field: str) -> None:
    """EF-02: the owner never pays for a video without what he chose — a Clip with effects,
    a text over the video or stretches of own video (outside `local`) is refused before
    any row."""
    service, repo, dispatcher = make_service(kit=make_kit(), voice=make_voice())
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_clip(**media), user_id=USER_ID
        )
    assert [(p.code, p.part, p.field) for p in refused.value.problems] == [
        ("recipe_unavailable", None, field)
    ]
    assert repo.drafts == {} and dispatcher.calls == []


def test_a_local_piece_carries_its_texts_now_that_the_compose_draws_them() -> None:
    """EF-06 + EF-05: the texts of a `local` Clip or a `local` part are drawn over the
    built video, so they are no longer `recipe_unavailable`; a text over a part that is
    NOT `local` (Seedance) still is. EF-08: a library layer over a `local` part is laid
    too, so it is no longer refused either."""
    from qualify_api.creative.video_pipeline.recipe import unbuilt_recipe_problems

    local_clip = _clip(clip_reference_mode="local", segments=(_stretch(),), text_layers=(WORDS,))
    assert unbuilt_recipe_problems(local_clip) == ()
    parent = parent_brief(
        VideoPartPlan(seconds=5, description="Uno.", text_layers=(WORDS,)),
        VideoPartPlan(
            mode="local",
            seconds=5,
            segments=(_stretch(),),
            description="Dos.",
            text_layers=(WORDS,),
        ),
        VideoPartPlan(
            mode="local", seconds=5, segments=(_stretch(),), description="Tres.", effects=(SMOKE,)
        ),
    )
    assert [(p.code, p.part, p.field) for p in unbuilt_recipe_problems(parent)] == [
        ("recipe_unavailable", 1, "text_layers"),
    ]


def test_a_local_text_in_a_design_the_video_does_not_draw_is_unknown_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EF-05 draws only the `scrim` over a video: a `local` Clip whose text asks for the
    band is refused as `unknown_layout` on that text — before any row or charge — and not
    as `recipe_unavailable`."""
    from qualify_creative.layer_spec import LayoutId

    from qualify_api.creative.queue_dispatch import SWITCH

    monkeypatch.setenv(SWITCH, "queue")
    band = VideoTextLayer(text="Hola", layout_id=LayoutId.BAND, layout_version=LAYOUT_VERSION)
    brief = _clip(clip_reference_mode="local", segments=(_stretch(),), text_layers=(band,))
    service, repo, dispatcher = make_service(kit=make_kit(), voice=make_voice())
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID)
    assert [(p.code, p.part, p.field) for p in refused.value.problems] == [
        ("unknown_layout", None, "text_layers[0].layout_id")
    ]
    assert repo.drafts == {} and dispatcher.calls == []
    # the scrim, at the catalog's version, goes on
    scrim = band.model_copy(update={"layout_id": LayoutId.SCRIM})
    ok = _clip(clip_reference_mode="local", segments=(_stretch(),), text_layers=(scrim,))
    draft = service.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=ok, user_id=USER_ID)
    assert draft in repo.drafts


def test_a_parent_with_a_recipe_is_refused_but_its_plan_may_be_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative.video_pipeline.recipe import unbuilt_recipe_problems

    plan = (
        VideoPartPlan(seconds=5, description="Uno."),
        VideoPartPlan(seconds=4, description="Dos.", transition_in=FADE),
    )
    parent = parent_brief(*plan, text_layer=WORDS)
    assert [(p.code, p.part, p.field) for p in unbuilt_recipe_problems(parent)] == [
        ("recipe_unavailable", 2, "transition_in"),
        ("recipe_unavailable", None, "text_layers"),
    ]
    service, repo, _ = make_service(kit=make_kit(), voice=make_voice())
    with pytest.raises(RecipeRefused):
        service.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=parent, user_id=USER_ID)
    assert repo.drafts == {}
    row = _saving(
        monkeypatch, parent_brief(*(p.model_copy(update={"transition_in": None}) for p in plan))
    )
    save_parts_plan(tenant_id=TENANT_ID, parent_id=uuid4(), parts=plan)  # saving stays free
    assert _saved_parts(row)[1].transition_in == FADE


def test_a_part_with_a_recipe_makes_no_part_and_charges_nothing() -> None:
    plan = (
        VideoPartPlan(seconds=5, description="Uno."),
        VideoPartPlan(seconds=5, description="Dos."),
    )
    parts, _, repo, ledger, dispatcher, router, parent = world(plan=plan)
    brief = repo.briefs[repo.drafts[parent].brief_id]
    smoky = plan[1].model_copy(update={"effects": (SMOKE,)})
    repo.briefs[repo.drafts[parent].brief_id] = brief.model_copy(
        update={"media": brief.media.model_copy(update={"parts": (plan[0], smoky)})}
    )
    before = dict(ledger.rows)
    with pytest.raises(RecipeRefused) as refused:
        parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    assert refusal_of(refused.value) == ("recipe_unavailable", 2, 0)
    assert repo.parts_of(tenant_id=TENANT_ID, parent_id=parent) == ()
    assert ledger.rows == before and dispatcher.calls == []


def test_the_parents_whole_video_text_is_validated() -> None:
    from qualify_creative.layer_spec import LayoutId

    bad = VideoTextLayer(text="Hola", layout_id=LayoutId.PHOTO_ONLY, layout_version=1)
    parent = parent_brief(VideoPartPlan(seconds=5, description="Uno."), text_layer=bad)
    problems = validate_brief_recipe(parent)
    assert [(p.code, p.part, p.field) for p in problems] == [
        ("unknown_layout", None, "text_layers[0].layout_id")
    ]


def test_a_plan_with_a_local_part_makes_it_and_charges_it_nothing() -> None:
    """EF-06: a `local` part is made like the others — its child stamped for the local
    pipeline, its charge of 0 creations, 0 vistas previas, 0 seconds (D3); the
    `reference` part beside it is charged as before."""
    plan = (
        VideoPartPlan(seconds=5, description="Uno."),
        VideoPartPlan(seconds=5, description="Dos."),
    )
    parts, _, repo, ledger, dispatcher, router, parent = world(plan=plan)
    brief = repo.briefs[repo.drafts[parent].brief_id]
    local = VideoPartPlan(mode="local", seconds=5, segments=(_stretch(),), description="Dos.")
    repo.briefs[repo.drafts[parent].brief_id] = brief.model_copy(
        update={"media": brief.media.model_copy(update={"parts": (plan[0], local)})}
    )
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    assert len(ids) == 2 and len(dispatcher.calls) == 2
    child = repo.briefs[repo.drafts[ids[1]].brief_id]
    assert child.media.clip_reference_mode == "local"
    assert child.media.effects_pipeline_version == 1
    first = repo.briefs[repo.drafts[ids[0]].brief_id]
    assert first.media.effects_pipeline_version == 0
    assert parts.estimated_usd([child]) == 0
    prices = {key[0]: row for key, row in ledger.rows.items()}
    assert ledger_price(prices[ids[1]]) == ("local_video", 0, 0, 0)
    assert ledger_price(prices[ids[0]])[2] == 1  # the `reference` part: one vista previa


def test_a_stored_local_refusal_still_reads() -> None:
    """EF-06 no longer raises `PartsLocalUnavailable`; a refusal stored before it reads."""
    assert refusal_of(PartsLocalUnavailable()) == ("local_unavailable", None, 0)


def test_a_parent_with_a_local_part_may_be_created() -> None:
    """EF-06: a `local` part is made — the parent with one is no longer refused."""
    service, repo, _ = make_service(kit=make_kit(), voice=make_voice())
    local = VideoPartPlan(mode="local", seconds=5, segments=(_stretch(),), description="Uno.")
    service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=parent_brief(local), user_id=USER_ID
    )
    assert len(repo.drafts) == 1


def test_a_recipe_refusal_of_a_part_is_a_stored_code() -> None:
    from qualify_creative.effects import RecipeProblem

    refused = RecipeRefused((RecipeProblem(code="not_offered", part=2, field="effects[0]"),))
    assert refusal_of(refused) == ("effects_invalid", 2, 0)


def test_the_producer_never_sends_an_unstamped_local_clip_to_seedance() -> None:
    """A `local` brief the server never stamped (`effects_pipeline_version` 0: stored
    before EF-06) is refused before any read — never made as a Seedance clip."""
    from .test_creative_media import TENANT_ID as MEDIA_TENANT
    from .test_creative_media import MemoryStore, SpyVendor, _produce, _producer

    vendor = SpyVendor()
    stretch = _stretch(f"uploads/{MEDIA_TENANT}/mi-cocina.mp4")
    brief = _clip(clip_reference_mode="local", segments=(stretch,))
    assert brief.media.effects_pipeline_version == 0
    outcome = _produce(_producer(MemoryStore(), vendor), brief, uuid4())
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == LOCAL_CLIP_UNAVAILABLE
    assert vendor.requests == [] and outcome.spent_usd == 0 and outcome.media == ()


# ---------------------------------------------------------------------------
# save_parts_plan keeps each part's effects: reordered, and joined


class _Row:
    media: Any = None


def _saving(monkeypatch: pytest.MonkeyPatch, current: ContentBrief) -> _Row:
    """`save_parts_plan` over an in-memory parent (no database): the lock, the purge
    check and «no part made yet» pass; `row.media` is what it writes."""
    row = _Row()
    session = SimpleNamespace(flush=lambda: None)
    monkeypatch.setattr(parts_plan, "tenant_session", lambda tenant: nullcontext(session))
    monkeypatch.setattr(parts_plan, "_parent_rows", lambda s, parent, lock: (None, row))
    monkeypatch.setattr(parts_plan, "refuse_if_parent_purged", lambda s, parent: None)
    monkeypatch.setattr(parts_plan, "_has_parts", lambda s, parent: False)
    monkeypatch.setattr(parts_plan, "brief_from_row", lambda r: current)
    return row


def _saved_parts(row: _Row) -> tuple[VideoPartPlan, ...]:
    return MediaInputs.model_validate(row.media).parts


def test_reordering_keeps_each_parts_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    one = VideoPartPlan(seconds=5, description="Uno.", effects=(SMOKE,))
    two = VideoPartPlan(seconds=4, description="Dos.", effects=(TEXT,), text_layer=WORDS)
    three = VideoPartPlan(seconds=6, description="Tres.", transition_in=FADE)
    row = _saving(monkeypatch, parent_brief(one, two, three))
    save_parts_plan(tenant_id=TENANT_ID, parent_id=uuid4(), parts=(two, three, one))
    assert _saved_parts(row) == (two, three, one)
    assert [p.effects for p in _saved_parts(row)] == [(TEXT,), (), (SMOKE,)]
    assert _saved_parts(row)[0].text_layers == (WORDS,)
    assert _saved_parts(row)[1].transition_in == FADE


def test_the_owner_may_change_a_parts_effects_when_saving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    one = VideoPartPlan(seconds=5, description="Uno.")
    two = VideoPartPlan(seconds=4, description="Dos.")
    row = _saving(monkeypatch, parent_brief(one, two))
    edited = two.model_copy(update={"effects": (SMOKE,), "transition_in": FADE})
    save_parts_plan(tenant_id=TENANT_ID, parent_id=uuid4(), parts=(one, edited))
    assert _saved_parts(row)[1] == edited


def test_a_plan_whose_effects_the_library_refuses_is_not_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    one = VideoPartPlan(seconds=5, description="Uno.")
    _saving(monkeypatch, parent_brief(one))
    bad = one.model_copy(update={"effects": (EMBERS_AI, SMOKE, SMOKE)})
    with pytest.raises(PartsPlanRefused) as refused:
        save_parts_plan(tenant_id=TENANT_ID, parent_id=uuid4(), parts=(bad,))
    assert refused.value.reason == PLAN_EFFECTS
    assert _codes(refused.value.problems) == ["not_offered", "too_many_of_effect"]


REEL = analysis(shot(0, 0, 2), shot(1, 2, 5), shot(2, 5, 10))


def _cut(index: int, seconds: int, **fields: Any) -> VideoPartPlan:
    return VideoPartPlan(
        seconds=seconds,
        analysis_id=REEL.id,
        shot_indexes=(index,),
        description=f"C{index}.",
        **fields,
    )


# Times are seconds of each part's OWN output, from its start. `_cut(0, 2)` lasts 2 s and
# `_cut(1, 3)` 3 s: joined, the second's times move 2 s later.


@pytest.mark.parametrize(
    "other",
    [
        EffectUse(effect_id="humo_capa", version=1, params={"intensity": 0.3, "zone": "top"}),
        SMOKE.model_copy(update={"start_s": 1.0, "end_s": 2.0}),  # does not start the part
    ],
    ids=["params", "span"],
)
def test_the_same_effect_chosen_differently_is_refused(other: EffectUse) -> None:
    with pytest.raises(PartsPlanRefused) as refused:
        merge_short_part(_cut(0, 2, effects=(SMOKE,)), _cut(1, 3, effects=(other,)), REEL)
    assert refused.value.reason == PLAN_MERGE_EFFECTS


@pytest.mark.parametrize(
    "other",
    [
        VideoTextLayer(text="Otra cosa", place="top"),
        VideoTextLayer(text="Shawarma mixto", place="bottom"),
        # the design named explicitly (EF-05: the scrim is the one a video text draws)
        VideoTextLayer(
            text="Shawarma mixto", place="top", layout_id="scrim", layout_version=LAYOUT_VERSION
        ),
    ],
    ids=["words", "place", "design"],
)
def test_joining_two_parts_with_different_texts_keeps_both(other: VideoTextLayer) -> None:
    """ED-15: a part holds up to 3 texts, so two different texts are both kept, each at
    its own place in the joined part (EF-02 refused them: one text per part)."""
    merged = merge_short_part(_cut(0, 2, text_layer=WORDS), _cut(1, 3, text_layer=other), REEL)
    assert merged.text_layers == (
        WORDS.model_copy(update={"start_s": 0.0, "end_s": 2.0}),
        other.model_copy(update={"start_s": 2.0, "end_s": 5.0}),
    )


def test_joining_parts_with_more_than_three_texts_is_refused() -> None:
    """ED-15: the joined part keeps every text of both — never more than 3."""
    two = (
        VideoTextLayer(text="Uno", place="top"),
        VideoTextLayer(text="Dos", place="bottom"),
    )
    others = (
        VideoTextLayer(text="Tres", place="top"),
        VideoTextLayer(text="Cuatro", place="bottom"),
    )
    with pytest.raises(PartsPlanRefused) as refused:
        merge_short_part(_cut(0, 2, text_layers=two), _cut(1, 3, text_layers=others), REEL)
    assert refused.value.reason == PLAN_MERGE_TEXT


def test_joining_effects_the_library_refuses_together_is_refused() -> None:
    wrong = EffectUse(effect_id="humo_capa", version=1, params={"intensity": 9.0})
    with pytest.raises(PartsPlanRefused) as refused:
        merge_short_part(_cut(0, 2, effects=(wrong,)), _cut(1, 3), REEL)
    assert refused.value.reason == PLAN_MERGE_EFFECTS
    assert _codes(refused.value.problems) == ["param_out_of_range"]


def test_joining_two_parts_keeps_both_parts_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rule (`merged_recipe`): every span made explicit in the joined 5 s part — «the
    whole part» is `[0, 2]` for the first (2 s) and `[2, 5]` for the second (3 s) —, the
    second's own spans moved 2 s, the one text with explicit times, the first's
    transition, and the provenance of a mode the join forced."""
    embers = EffectUse(effect_id="brasas_capa", version=1, start_s=0.5, end_s=2.5)
    first = _cut(0, 2, effects=(SMOKE, TEXT), mode_reason="reel_no_people", mode_rule_version=1)
    second = _cut(1, 3, effects=(embers, VAPOR), text_layer=WORDS, transition_in=FADE)
    third = _cut(2, 5)
    merged = merge_short_part(first, second, REEL)
    assert merged.effects == (
        SMOKE.model_copy(update={"start_s": 0.0, "end_s": 2.0}),
        TEXT.model_copy(update={"start_s": 0.0, "end_s": 2.0}),
        embers.model_copy(update={"start_s": 2.5, "end_s": 4.5}),
        VAPOR.model_copy(update={"start_s": 2.0, "end_s": 5.0}),
    )
    assert merged.text_layers == (WORDS.model_copy(update={"start_s": 2.0, "end_s": 5.0}),)
    assert merged.transition_in is None  # the first part's (none): the fade is now inside
    assert (merged.mode, merged.mode_reason, merged.mode_rule_version) == (
        "edit",
        MERGED_PARTS_REASON,
        0,
    )
    assert merged.mode_changed_by_owner is False

    row = _saving(monkeypatch, parent_brief(first, second, third))
    save_parts_plan(tenant_id=TENANT_ID, parent_id=uuid4(), parts=(merged, third), analysis=REEL)
    saved = _saved_parts(row)
    assert saved[0].effects == merged.effects and saved[0].text_layers == merged.text_layers
    assert saved[0].shot_indexes == (0, 1) and saved[1] == third


def test_joining_parts_2_and_3_does_not_depend_on_their_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parts of 5, 2 and 3 s: joining the 2nd and the 3rd gives the same recipe as if they
    were first — the times are each part's own — and the plan saves it."""
    reel = analysis(shot(0, 0, 5), shot(1, 5, 7), shot(2, 7, 10))
    head = VideoPartPlan(seconds=5, analysis_id=reel.id, shot_indexes=(0,), description="A.")
    smoke = EffectUse(effect_id="humo_capa", version=1, start_s=0.5, end_s=1.5)
    current = VideoPartPlan(
        seconds=2, analysis_id=reel.id, shot_indexes=(1,), description="B.", effects=(smoke,)
    )
    following = VideoPartPlan(
        seconds=3, analysis_id=reel.id, shot_indexes=(2,), description="C.", effects=(VAPOR,)
    )
    merged = merge_short_part(current, following, reel)
    assert merged.effects == (smoke, VAPOR.model_copy(update={"start_s": 2.0, "end_s": 5.0}))
    row = _saving(monkeypatch, parent_brief(head, current, following))
    save_parts_plan(tenant_id=TENANT_ID, parent_id=uuid4(), parts=(head, merged), analysis=reel)
    assert _saved_parts(row)[1].effects == merged.effects


def test_the_same_effect_in_both_parts_is_one_use_only_where_they_meet() -> None:
    whole, _ = merged_recipe(_cut(0, 2, effects=(SMOKE,)), _cut(1, 3, effects=(SMOKE,)))
    assert whole == (SMOKE.model_copy(update={"start_s": 0.0, "end_s": 5.0}),)
    # the first ends at its end (2 s) and the second starts at its start: they meet
    ending = EffectUse(effect_id="humo_capa", version=1, start_s=1.0, end_s=2.0)
    starting = EffectUse(effect_id="humo_capa", version=1, start_s=0.0, end_s=1.0)
    met, _ = merged_recipe(_cut(0, 2, effects=(ending,)), _cut(1, 3, effects=(starting,)))
    assert met == (ending.model_copy(update={"start_s": 1.0, "end_s": 3.0}),)


def test_the_same_effect_that_does_not_meet_is_refused_never_filled_in() -> None:
    """Smoke at 0-1 s of a 2 s part and at 0-1 s of the next: one use would be 0-3 s, with
    smoke at 1-2 s where the owner put none — refused, and `max_per_part` = 1 leaves no
    room for two uses."""
    early = EffectUse(effect_id="humo_capa", version=1, start_s=0.0, end_s=1.0)
    with pytest.raises(PartsPlanRefused) as refused:
        merge_short_part(_cut(0, 2, effects=(early,)), _cut(1, 3, effects=(early,)), REEL)
    assert refused.value.reason == PLAN_MERGE_EFFECTS


def test_a_text_for_the_whole_part_gets_explicit_times() -> None:
    _, text = merged_recipe(_cut(0, 2, text_layer=WORDS), _cut(1, 3))
    assert text == (WORDS.model_copy(update={"start_s": 0.0, "end_s": 2.0}),)
    _, same = merged_recipe(_cut(0, 2, text_layer=WORDS), _cut(1, 3, text_layer=WORDS))
    assert same == (WORDS.model_copy(update={"start_s": 0.0, "end_s": 5.0}),)
    ending = WORDS.model_copy(update={"start_s": 1.0, "end_s": 2.0})
    starting = WORDS.model_copy(update={"start_s": 0.0, "end_s": 1.0})
    _, met = merged_recipe(_cut(0, 2, text_layer=ending), _cut(1, 3, text_layer=starting))
    assert met == (WORDS.model_copy(update={"start_s": 1.0, "end_s": 3.0}),)


def test_the_same_text_that_does_not_meet_stays_two_texts() -> None:
    """ED-15: the same words at 0-2 s of the first part and at 1-2 s of the second do not
    meet: two texts (0-2 and 3-4 s of the joined part), never one filled in between."""
    late = WORDS.model_copy(update={"start_s": 1.0, "end_s": 2.0})
    merged = merge_short_part(_cut(0, 2, text_layer=WORDS), _cut(1, 3, text_layer=late), REEL)
    assert merged.text_layers == (
        WORDS.model_copy(update={"start_s": 0.0, "end_s": 2.0}),
        WORDS.model_copy(update={"start_s": 3.0, "end_s": 4.0}),
    )


def test_a_join_of_fractional_cuts_fits_the_joined_length() -> None:
    """Cuts of 1.6 s and 2.6 s make parts of 2 and 3 s, but the joined part lasts
    round(4.2) = 4 s: «the whole part» of the second is cut at 4, and a span that would
    start at or after 4 is refused, never dropped."""
    reel = analysis(shot(0, 0.0, 1.6), shot(1, 1.6, 4.2), shot(2, 4.2, 9.0))

    def cut(index: int, seconds: int, **fields: Any) -> VideoPartPlan:
        return VideoPartPlan(seconds=seconds, analysis_id=reel.id, shot_indexes=(index,), **fields)

    merged = merge_short_part(
        cut(0, 2, effects=(TEXT,), text_layer=WORDS), cut(1, 3, effects=(SMOKE,)), reel
    )
    assert merged.seconds == 4
    assert merged.effects == (
        TEXT.model_copy(update={"start_s": 0.0, "end_s": 2.0}),
        SMOKE.model_copy(update={"start_s": 2.0, "end_s": 4.0}),
    )
    assert merged.text_layers == (WORDS.model_copy(update={"start_s": 0.0, "end_s": 2.0}),)
    lost = EffectUse(effect_id="humo_capa", version=1, start_s=2.5, end_s=3.0)
    with pytest.raises(PartsPlanRefused) as refused:
        merge_short_part(cut(0, 2), cut(1, 3, effects=(lost,)), reel)  # would start at 4.5
    assert refused.value.reason == PLAN_MERGE_EFFECTS


# ---------------------------------------------------------------------------
# Times are each part's own: reordering moves nothing


def test_reordering_three_parts_keeps_each_parts_recipe_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    one = VideoPartPlan(seconds=3, description="Uno.", effects=(SMOKE,))
    two = VideoPartPlan(
        seconds=4,
        description="Dos.",
        effects=(TEXT.model_copy(update={"start_s": 1.0, "end_s": 3.0}),),
        text_layer=WORDS,
        transition_in=FADE,
    )
    three = VideoPartPlan(
        seconds=5,
        description="Tres.",
        effects=(VAPOR.model_copy(update={"start_s": 0.0, "end_s": 5.0}),),
        text_layer=WORDS.model_copy(update={"start_s": 1.0, "end_s": 3.0}),
    )
    row = _saving(monkeypatch, parent_brief(one, two, three))
    save_parts_plan(tenant_id=TENANT_ID, parent_id=uuid4(), parts=(three, one, two))
    assert _saved_parts(row) == (three, one, two)  # identical: nothing recalculated


def test_a_parts_times_fall_in_its_own_length() -> None:
    plan = (
        PartRecipe(index=1, seconds=3),
        PartRecipe(
            index=2, seconds=4, effects=(TEXT.model_copy(update={"start_s": 3.0, "end_s": 5.0}),)
        ),
        PartRecipe(index=3, seconds=5, text_layer=WORDS.model_copy(update={"start_s": 4.0})),
    )
    problems = validate_recipe(plan, video_by_parts=True)
    # part 2 lasts 4 s, so 3-5 runs past it; the third's text at 4 is inside its 5 s
    assert [(p.code, p.part, p.field) for p in problems] == [("span_outside_part", 2, "effects[0]")]


def test_a_clip_lasts_its_stretches_at_their_speed_or_its_duration() -> None:
    from qualify_api.creative.video_pipeline.recipe import clip_seconds

    fast = SourceSegment(key=OWN, start_s=0.0, end_s=60.0, speed=12.0)  # 5 s of output
    clip = PartRecipe(index=1, mode="local", seconds=10, segments=(fast,))
    assert clip_seconds(clip) == 5.0 and clip_seconds(PartRecipe(index=1, seconds=10)) == 10
    late = TEXT.model_copy(update={"start_s": 6.0, "end_s": 7.0})
    with_late = clip.model_copy(update={"effects": (late,)})
    assert _codes(validate_recipe((with_late,), video_by_parts=False)) == ["span_outside_part"]
    plain = PartRecipe(index=1, seconds=10, effects=(late,))
    assert validate_recipe((plain,), video_by_parts=False) == ()
    # a `motion` Clip makes `duration_seconds` of video: its stretch is only a reference
    reference = SourceSegment(key=OWN, start_s=0.0, end_s=60.0)
    motion = PartRecipe(index=1, seconds=5, segments=(reference,))
    assert clip_seconds(motion) == 5
    deep = TEXT.model_copy(update={"start_s": 30.0, "end_s": 40.0})
    in_motion = motion.model_copy(update={"effects": (deep,)})
    assert _codes(validate_recipe((in_motion,), video_by_parts=False)) == ["span_outside_part"]


def test_the_parents_text_falls_inside_the_whole_video() -> None:
    plan = (
        VideoPartPlan(seconds=5, description="Uno."),
        VideoPartPlan(seconds=4, description="Dos."),
    )
    good = parent_brief(*plan, text_layer=WORDS.model_copy(update={"start_s": 2.0, "end_s": 9.0}))
    late = parent_brief(*plan, text_layer=WORDS.model_copy(update={"start_s": 9.5}))
    assert validate_brief_recipe(good) == ()
    assert [(p.code, p.part) for p in validate_brief_recipe(late)] == [("span_outside_part", None)]


def test_the_real_v1_library_refuses_fast_motion_as_an_effect() -> None:
    """D-T3: fast motion is `segments[].speed`; `camara_rapida` is not offered in v1."""
    from qualify_creative.effects import load_effects

    real = load_effects()
    part = PartRecipe(index=1, mode="local", seconds=5, segments=(_stretch(),), effects=(FAST,))
    for by_parts, number in ((False, None), (True, 1)):
        problems = validate_recipe((part,), video_by_parts=by_parts, library=real)
        assert [(p.code, p.part, p.effect_id) for p in problems] == [
            ("not_offered", number, "camara_rapida")
        ]


def test_a_local_part_must_last_its_seconds() -> None:
    """A `local` part IS its stretches at their speed: 0-6 s at ×3 is 2 s, not its 5."""
    short = SourceSegment(key=OWN, start_s=0.0, end_s=6.0, speed=3.0)
    part = PartRecipe(index=1, mode="local", seconds=5, segments=(short,))
    problems = validate_recipe((part,), video_by_parts=True)
    # option A: 2 s is also under the speed step's 3 s
    assert [(p.code, p.part, p.field, p.duration_s) for p in problems] == [
        ("local_length_out_of_range", 1, "segments", 2.0),
        ("segments_length_mismatch", 1, "segments", 2.0),
    ]
    fits = SourceSegment(key=OWN, start_s=0.0, end_s=15.3, speed=3.0)  # 5.1 s: within 0.5
    ok = part.model_copy(update={"segments": (fits,)})
    assert validate_recipe((ok,), video_by_parts=True) == ()


@pytest.mark.parametrize(("end_s", "ok"), [(2.0, False), (3.0, True), (60.0, True), (61.0, False)])
def test_a_local_clip_lasts_3_to_60_seconds(end_s: float, ok: bool) -> None:
    stretch = SourceSegment(key=OWN, start_s=0.0, end_s=end_s)
    clip = PartRecipe(index=1, mode="local", seconds=5, segments=(stretch,))
    problems = validate_recipe((clip,), video_by_parts=False)
    assert "local_length_out_of_range" in _codes(problems) if not ok else problems == ()


@pytest.mark.parametrize(
    ("start_s", "end_s", "speed", "refused"),
    [
        (0.0, 60.0, 1.0, False),  # exactly 60 s of source: made
        (10.0, 70.03, 2.0, False),  # within a frame of float slack
        (0.0, 60.5, 2.0, True),
        (30.0, 120.0, 10.0, True),  # 90 s of source at ×10: 9 s out, still refused
        (0.0, 1800.0, 30.0, True),  # the ×30 case the limit is for
    ],
)
def test_a_video_stretch_takes_at_most_60_seconds_of_its_source(
    start_s: float, end_s: float, speed: float, refused: bool
) -> None:
    """m-25042483: each video stretch reads at most 60 s of its source, whatever its
    speed — refused before anything is created, with how much it takes."""
    long = SourceSegment(key=OWN, start_s=start_s, end_s=end_s, speed=speed)
    short = SourceSegment(key=OWN, start_s=0.0, end_s=20.0, speed=2.0)
    for by_parts, number in ((False, None), (True, 2)):
        seconds = (end_s - start_s) / speed + 10.0
        part = PartRecipe(index=2, mode="local", seconds=seconds, segments=(short, long))
        problems = [
            (p.code, p.part, p.field, p.duration_s)
            for p in validate_recipe((part,), video_by_parts=by_parts)
            if p.code == "segment_source_too_long"
        ]
        want = [("segment_source_too_long", number, "segments", round(end_s - start_s, 1))]
        assert problems == (want if refused else [])


def test_a_photo_is_never_a_long_stretch() -> None:
    """Photos have their own 1-5 s; the 60 s of source is a video stretch's."""
    photo = SourceSegment(key=OWN, start_s=0.0, end_s=4.0, kind="photo")
    video = SourceSegment(key=OWN, start_s=0.0, end_s=30.0, speed=10.0)
    part = PartRecipe(index=1, mode="local", seconds=7, segments=(video, photo))
    assert "segment_source_too_long" not in _codes(validate_recipe((part,), video_by_parts=False))


# ---------------------------------------------------------------------------
# ED-15: the parent's VideoRecipe — what crosses parts, in seconds of the whole video


def _whole(**fields: Any) -> VideoRecipe:
    parts = (PartRecipe(index=1, seconds=5), PartRecipe(index=2, seconds=4))
    return VideoRecipe(parts=parts, **fields)


def test_a_parent_without_a_video_recipe_reads_and_with_one_round_trips() -> None:
    plan = (
        VideoPartPlan(seconds=5, description="Uno."),
        VideoPartPlan(seconds=4, description="Dos."),
    )
    stored = json.loads(parent_brief(*plan).model_dump_json())
    del stored["media"]["video_recipe"]  # a parent stored before ED-15
    assert ContentBrief.model_validate(stored).media.video_recipe is None
    recipe = _whole(
        text_layers=(WORDS.model_copy(update={"start_s": 3.0, "end_s": 7.0}),),
        effects=(SMOKE.model_copy(update={"start_s": 4.0, "end_s": 6.0}),),
    )
    parent = parent_brief(*plan, video_recipe=recipe)
    again = ContentBrief.model_validate_json(parent.model_dump_json())
    assert again == parent and again.media.video_recipe == recipe
    assert validate_brief_recipe(parent, tenant_id=TENANT_ID) == ()


def test_a_video_recipe_is_only_a_parents() -> None:
    with pytest.raises(ValueError, match="effects_not_for_kind"):
        _clip(video_recipe=_whole())


def test_a_video_recipe_has_a_parts_limits_in_whole_video_seconds() -> None:
    late = WORDS.model_copy(update={"start_s": 8.0, "end_s": 10.0})  # the video lasts 9 s
    clash = (
        WORDS.model_copy(update={"start_s": 0.0, "end_s": 4.0}),
        WORDS.model_copy(update={"text": "Otro", "start_s": 3.0, "end_s": 5.0}),
    )
    twice = (VAPOR.model_copy(update={"start_s": 5.0, "end_s": 8.0}),) * 2
    problems = validate_video_recipe(_whole(text_layers=(*clash, late), effects=twice))
    assert [(p.code, p.part, p.field) for p in problems] == [
        ("span_outside_part", None, "text_layers[2]"),
        ("texts_overlap", None, "text_layers[1]"),
        ("too_many_of_effect", None, "effects[1]"),  # v1 (this file's library): one use
    ]
    fade = validate_video_recipe(_whole(effects=(FADE,)))
    assert [(p.code, p.part) for p in fade] == [("transition_in_effects", None)]


def test_a_parent_with_a_video_recipe_is_refused_until_the_engine_exists() -> None:
    from qualify_api.creative.video_pipeline.recipe import unbuilt_recipe_problems

    parent = parent_brief(
        VideoPartPlan(seconds=5, description="Uno."),
        VideoPartPlan(seconds=4, description="Dos."),
        video_recipe=_whole(),
    )
    assert [(p.code, p.part, p.field) for p in unbuilt_recipe_problems(parent)] == [
        ("recipe_unavailable", None, "video_recipe")
    ]


def test_a_parts_child_never_carries_the_parents_video_recipe() -> None:
    from qualify_api.creative.parts import _child_brief

    entry = VideoPartPlan(seconds=5, description="Uno.", effects=(SMOKE,))
    parent = parent_brief(
        entry, VideoPartPlan(seconds=4, description="Dos."), video_recipe=_whole()
    )
    child = _child_brief(parent, entry, 1, None)
    assert child.media.video_recipe is None and child.media.part is not None
    assert recipe_of(child)[0].effects == (SMOKE,)


def test_a_text_that_meets_itself_with_another_fade_is_one_text_with_the_first_fade() -> None:
    """EF-05 (owner-chosen fade): a text that runs on across the join never appears again,
    so the second part's fade has nothing to fade — the same words, place and design are
    one text, with the fade it appeared with (the first part's)."""
    slow = WORDS.model_copy(update={"fade_s": 1.0})
    merged = merge_short_part(_cut(0, 2, text_layer=WORDS), _cut(1, 3, text_layer=slow), REEL)
    assert merged.text_layers == (WORDS.model_copy(update={"start_s": 0.0, "end_s": 5.0}),)
    assert merged.text_layers[0].fade_s == 0.5
