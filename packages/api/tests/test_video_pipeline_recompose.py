"""EF-14 (m-25026592): texts and layers over a Clip made by Seedance, and its 1080p final
composed again with the SAME recipe — the preview's, never the brief as it reads later.

Seedance and the composer are doubles (nothing paid, nothing rendered): the same fakes as
`test_creative_seedance_draft.py`. The pixels — the boxes of the preview and of the final at
the same place relative to the frame — are measured with real PyAV in
`test_recompose_boxes_scale_between_the_preview_and_the_final`."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind, FailureReason
from qualify_creative.schemas import EffectUse, MediaInputs, VideoTextLayer

from qualify_api.creative.video_pipeline import recompose
from qualify_api.creative.video_pipeline.recipe import RecipeRefused, unbuilt_recipe_problems
from qualify_api.creative.video_pipeline.recompose import (
    COMPOSE_NOT_ADDED,
    FINAL_COMPOSE_FAILED_TEXT,
    ClipComposeFailed,
    ComposedClip,
    ComposeRecipe,
    nine_sixteen_size,
    stored_recipe,
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
from .test_creative_media_byteplus import BUDGET, COPY, _kit
from .test_creative_media_byteplus import TENANT_ID as MEDIA_TENANT
from .test_creative_seedance_draft import (
    DraftSeedance,
    RecordingFitter,
    _clip,
    _producer,
    _record,
    _store,
)

WORDS = VideoTextLayer(text="Shawarma mixto", place="top")
OTHER_WORDS = VideoTextLayer(text="Ensalada griega", place="bottom")
SMOKE = EffectUse(effect_id="humo_capa", version=1, params={"intensity": 0.8, "zone": "top"})
SWITCH = "QUALIFY_CREATIVE_DISPATCHER"


@pytest.fixture
def queue_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SWITCH, "queue")


@pytest.fixture(autouse=True)
def in_the_worker() -> Iterator[None]:
    """The compose decodes video: only inside the creative worker (`is_worker_process`)."""
    from qualify_api.creative.process import mark_worker_process, unmark_worker_process

    mark_worker_process()
    yield
    unmark_worker_process()


def _seedance_clip(fmt: ContentFormat = ContentFormat.REELS_9_16, **media: Any) -> Any:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=fmt,
        media=MediaInputs(**{"duration_seconds": 5, **media}),
    )


# ---------------------------------------------------------------------------
# what is composed, and what is still refused before any row


def test_texts_and_layers_over_a_9_16_seedance_clip_are_no_longer_refused() -> None:
    brief = _seedance_clip(text_layers=(WORDS,), effects=(SMOKE,))
    assert unbuilt_recipe_problems(brief) == ()
    assert recompose.composes_over_seedance(brief)


@pytest.mark.parametrize(
    ("brief", "fields"),
    [
        # the layers are drawn for a 9:16 frame
        (
            _seedance_clip(ContentFormat.FEED_1_1, text_layers=(WORDS,), effects=(SMOKE,)),
            ["effects", "text_layers"],
        ),
    ],
)
def test_a_clip_the_compose_does_not_run_over_stays_refused(brief: Any, fields: list) -> None:
    found = sorted(p.field for p in unbuilt_recipe_problems(brief))
    assert found == fields
    assert not recompose.composes_over_seedance(brief)


def test_an_edit_clip_with_texts_stays_refused() -> None:
    """An `edit` Clip comes out at the reel's own size (any aspect): not composed."""
    brief = _seedance_clip(
        clip_reference_mode="edit",
        clip_video_keys=(f"uploads/{TENANT_ID}/reel.mp4",),
        clip_image_keys=(f"uploads/{TENANT_ID}/p.jpg",),
        text_layers=(WORDS,),
    )
    assert ("recipe_unavailable", "text_layers") in [
        (p.code, p.field) for p in unbuilt_recipe_problems(brief)
    ]


def test_without_the_queue_it_is_refused_before_any_row() -> None:
    """The compose decodes and encodes: never in a Reflex thread (`local_unavailable`)."""
    service, repo, dispatcher = make_service(kit=make_kit(), voice=make_voice())
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            brief=_seedance_clip(text_layers=(WORDS,)),
            user_id=USER_ID,
        )
    assert [p.code for p in refused.value.problems] == ["local_unavailable"]
    assert repo.drafts == {} and dispatcher.calls == []


def test_the_server_stamps_the_effects_pipeline_on_a_clip_it_will_compose(queue_on: None) -> None:
    service, repo, _ = make_service(kit=make_kit(), voice=make_voice())
    draft = service.create_draft(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        brief=_seedance_clip(text_layers=(WORDS,)),
        user_id=USER_ID,
    )
    stored = repo.briefs[repo.drafts[draft].brief_id]
    assert stored.media.effects_pipeline_version == recompose.SEEDANCE_COMPOSE_EFFECTS_VERSION
    assert stored.media.text_layers == (WORDS,)


def test_seedances_480p_is_cut_to_9_16_and_1080p_is_left_alone() -> None:
    assert nine_sixteen_size(496, 864) == (486, 864)
    assert nine_sixteen_size(480, 854) is None
    assert nine_sixteen_size(1080, 1920) is None
    assert nine_sixteen_size(1088, 1920) is None
    with pytest.raises(ValueError):
        nine_sixteen_size(1080, 1080)


def test_a_piece_before_the_engine_is_never_composed() -> None:
    """Out of scope: a brief stamped 0 (made before EF-14) gets no recipe."""
    brief = _seedance_clip(text_layers=(WORDS,), effects_pipeline_version=0)
    assert recompose.compose_recipe_of(brief, make_kit()) is None
    assert stored_recipe({"compose": {"recipe": {"text_layers": [], "effects": []}}}) is None


# ---------------------------------------------------------------------------
# the preview and the final, with doubles


class FakeComposer:
    """`recompose.ClipComposer`'s double: records every draw and compose."""

    def __init__(
        self,
        *,
        fail_draw: ClipComposeFailed | None = None,
        fail_compose: bool = False,
    ) -> None:
        self.fail_draw = fail_draw
        self.fail_compose = fail_compose
        self.draws: list[ComposeRecipe] = []
        self.composes: list[tuple[bytes, ComposeRecipe, Any, str]] = []

    def draw(self, recipe: ComposeRecipe) -> tuple[Any, ...]:
        self.draws.append(recipe)
        if self.fail_draw is not None:
            raise self.fail_draw
        return tuple(
            SimpleNamespace(
                png=f"png-{layer.text}".encode(),
                job_id=f"job-{layer.text}",
                width=1080,
                height=1920,
                report={"lines": [layer.text]},
                provenance={"template": "video_text"},
            )
            for layer in recipe.text_layers
        )

    def compose(
        self,
        video: bytes,
        recipe: ComposeRecipe,
        *,
        drawn: Sequence[Any] | None = None,
        stage: str,
    ) -> ComposedClip:
        self.composes.append((video, recipe, drawn, stage))
        if self.fail_compose:
            raise ClipComposeFailed(
                "x", failure=FailureReason.RENDER_ERROR.value, code="compose_failed"
            )
        size = (1080, 1920) if stage == "final" else (480, 854)
        return ComposedClip(
            data=b"composed-" + video,
            width=size[0],
            height=size[1],
            poster=None,
            params={"stage": stage, "recipe_sha256": recipe.digest(), "cost_usd": "0.00"},
        )


def _composing_producer(composer: FakeComposer) -> tuple[Any, Any, Any]:
    store, seedance = _store(), DraftSeedance()
    producer = _producer(store, seedance, RecordingFitter())
    producer._clip_composer = composer
    return producer, store, seedance


def _brief_with(**media: Any) -> Any:
    return _clip(**{"effects_pipeline_version": 1, **media})


def _with_attempt(write: Any, attempt: str, **draft: Any) -> Any:
    record = _record(write)
    params = {
        **write.params,
        "draft": {**write.params["draft"], "attempt": attempt, **draft},
    }
    return record.__class__(**{**record.__dict__, "params": params})


def _final(producer: Any, brief: Any, asset: Any, draft_id: Any) -> Any:
    return producer.finalize(
        tenant_id=MEDIA_TENANT,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        asset=asset,
        budget=BUDGET,
        revision=1,
    )


def test_the_texts_are_drawn_before_seedance_is_paid() -> None:
    """A text that does not fit fails the piece with nothing spent."""
    refused = ClipComposeFailed(
        "El texto 1 no cabe.",
        failure=FailureReason.INVALID_PARAMETERS.value,
        code="text_layer_refused",
        owner_fault=True,
    )
    composer = FakeComposer(fail_draw=refused)
    producer, _, seedance = _composing_producer(composer)
    outcome = producer.produce(
        tenant_id=MEDIA_TENANT,
        draft_id=uuid4(),
        brief=_brief_with(text_layers=(WORDS,)),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == "El texto 1 no cabe."
    assert seedance.requests == [] and outcome.usage == ()


def test_the_preview_is_composed_and_its_recipe_frozen() -> None:
    composer = FakeComposer()
    producer, store, _ = _composing_producer(composer)
    outcome = producer.produce(
        tenant_id=MEDIA_TENANT,
        draft_id=uuid4(),
        brief=_brief_with(text_layers=(WORDS,), effects=(SMOKE,)),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None
    (video,) = outcome.media
    (draw,) = composer.draws
    ((source, recipe, drawn, stage),) = composer.composes
    assert stage == "preview" and [d.png for d in drawn] == [b"png-Shawarma mixto"]
    assert recipe.text_layers == (WORDS,) and recipe.effects == (SMOKE,)
    assert store.files[video.object_key] == b"composed-" + source
    frozen = video.params["compose"]
    assert stored_recipe(video.params) == recipe
    assert frozen["preview"]["recipe_sha256"] == recipe.digest()
    assert frozen["recipe"]["brand"]["palette"]  # the Brand Kit's palette went in
    # it still has its draft block: the final is made from it
    assert video.params["draft"]["task_id"] == "cgt-draft"


def test_a_preview_whose_compose_fails_keeps_the_paid_clip_with_a_warning() -> None:
    composer = FakeComposer(fail_compose=True)
    producer, store, _ = _composing_producer(composer)
    outcome = producer.produce(
        tenant_id=MEDIA_TENANT,
        draft_id=uuid4(),
        brief=_brief_with(text_layers=(WORDS,)),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None
    assert COMPOSE_NOT_ADDED in [w.code for w in outcome.warnings]
    (video,) = outcome.media
    assert "compose" not in video.params  # its final lays none either
    assert store.files[video.object_key] == b"hevc-bytes"


def _draft_and_final_inputs(composer: FakeComposer, **media: Any) -> tuple[Any, ...]:
    producer, store, seedance = _composing_producer(composer)
    draft_id = uuid4()
    brief = _brief_with(**media)
    outcome = producer.produce(
        tenant_id=MEDIA_TENANT,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    (draft,) = outcome.media
    return producer, store, seedance, draft_id, brief, draft


def test_the_final_is_composed_again_with_the_previews_recipe() -> None:
    """«Si la receta cambió de versión entre borrador y final, se usa la del borrador»:
    the brief now says something else; the final keeps what the owner approved."""
    composer = FakeComposer()
    producer, store, _, draft_id, _, draft = _draft_and_final_inputs(
        composer, text_layers=(WORDS,), effects=(SMOKE,)
    )
    changed = _brief_with(text_layers=(OTHER_WORDS,), effects_pipeline_version=2)

    final = _final(producer, changed, _with_attempt(draft, "a1"), draft_id)

    assert final.failure is None and final.media is not None
    preview, final_call = composer.composes
    assert final_call[3] == "final" and final_call[0] == b"h264-hevc-bytes"
    assert final_call[1] == preview[1]  # the same frozen recipe
    assert final_call[1].text_layers == (WORDS,)
    assert store.files[final.media.object_key] == b"composed-h264-hevc-bytes"
    assert (final.media.width, final.media.height) == (1080, 1920)
    block = final.media.params["compose"]
    assert block["recipe"] == draft.params["compose"]["recipe"]
    assert block["preview"] == draft.params["compose"]["preview"]
    # provenance: which final it was composed over
    assert block["final"]["from_task_id"] == "cgt-final"
    assert block["final"]["from_raw_final_key"]
    assert block["final"]["recipe_sha256"] == block["preview"]["recipe_sha256"]
    assert final.usage and all(u.cost_usd > 0 for u in final.usage)  # only Seedance costs


def test_two_retries_of_the_final_make_one_asset() -> None:
    """The first try composed and kept the final but its last write never landed: the
    retry (same order) pays nothing, composes nothing, and points at the same file."""
    composer = FakeComposer()
    producer, store, seedance, draft_id, brief, draft = _draft_and_final_inputs(
        composer, text_layers=(WORDS,)
    )
    first = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)
    assert first.failure is None and first.media is not None
    paid, composed = len(seedance.requests), len(composer.composes)

    retry = _final(
        producer, brief, _with_attempt(draft, "a1", **(first.draft_changes or {})), draft_id
    )

    assert retry.failure is None and retry.media is not None
    assert len(seedance.requests) == paid  # the raw 1080p is not paid twice
    assert len(composer.composes) == composed  # nor composed twice
    assert retry.media.object_key == first.media.object_key
    assert retry.media.params["compose"]["final"]["reused"] is True
    finals = [
        key for key in store.files if "-final-" in key and key.endswith(".mp4") and "raw" not in key
    ]
    assert finals == [first.media.object_key]


def test_a_final_whose_compose_fails_keeps_its_raw_file_for_a_free_retry() -> None:
    composer = FakeComposer()
    producer, _, seedance, draft_id, brief, draft = _draft_and_final_inputs(
        composer, text_layers=(WORDS,)
    )
    composer.fail_compose = True

    final = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)

    assert final.failure == FailureReason.PROVIDER_ERROR.value
    assert final.detail == FINAL_COMPOSE_FAILED_TEXT and final.media is None
    assert final.draft_changes and final.draft_changes["raw_final"]["key"]
    paid = len(seedance.requests)
    composer.fail_compose = False
    retry = _final(producer, brief, _with_attempt(draft, "a2", **final.draft_changes), draft_id)
    assert retry.failure is None and len(seedance.requests) == paid


def test_a_clip_without_texts_is_finished_exactly_as_before() -> None:
    composer = FakeComposer()
    producer, store, _, draft_id, brief, draft = _draft_and_final_inputs(composer)
    assert "compose" not in draft.params and composer.draws == []
    final = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)
    assert final.failure is None and "compose" not in final.media.params
    assert composer.composes == []
    assert store.files[final.media.object_key] == b"h264-hevc-bytes"


# ---------------------------------------------------------------------------
# review fixes: the v1 key, the heavy-video gate, the kept PNGs, a resumed task, the worker


def test_the_v1_text_key_is_composed_too() -> None:
    """A brief stored with the v1 `text_layer` key reads as `text_layers` and is composed."""
    brief = _seedance_clip(text_layer=WORDS)
    assert unbuilt_recipe_problems(brief) == ()
    assert recompose.composes_over_seedance(brief)
    recipe = recompose.compose_recipe_of(
        _seedance_clip(text_layer=WORDS, effects_pipeline_version=1), make_kit()
    )
    assert recipe is not None and recipe.text_layers == (WORDS,)


def test_the_preview_waits_for_a_part_join_once_its_clip_is_there() -> None:
    """A part join holds the gate: the pass that HAS the clip waits before any fit or
    compose (the queue replays the paid call from its checkpoint), and the worker leaves
    the piece out of its passes for a while (`retry_after_s` > 0)."""
    from qualify_api.creative.heavy_video import LocalAssemblyWait, joining

    composer = FakeComposer()
    producer, _, seedance = _composing_producer(composer)
    with joining(), pytest.raises(LocalAssemblyWait) as waited:
        producer.produce(
            tenant_id=MEDIA_TENANT,
            draft_id=uuid4(),
            brief=_brief_with(text_layers=(WORDS,)),
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
        )
    assert waited.value.retry_after_s == recompose.JOIN_RETRY_AFTER_SECONDS > 0
    assert composer.composes == [] and len(seedance.requests) == 1


def test_the_final_waits_for_a_part_join_before_it_fits_or_composes() -> None:
    """The pass that HAS the 1080p waits for a part join before any fit, subtitle or
    compose; its raw 1080p is kept, so the next pass pays nothing again."""
    from qualify_api.creative.heavy_video import LocalAssemblyWait, joining

    composer = FakeComposer()
    producer, _, seedance, draft_id, brief, draft = _draft_and_final_inputs(
        composer, text_layers=(WORDS,)
    )
    fitter = producer._fitter
    fitter.calls.clear()
    paid, composed = len(seedance.requests), len(composer.composes)
    kept: list[dict[str, Any]] = []
    with joining(), pytest.raises(LocalAssemblyWait) as waited:
        producer.finalize(
            tenant_id=MEDIA_TENANT,
            draft_id=draft_id,
            brief=brief,
            kit=_kit(),
            asset=_with_attempt(draft, "a1"),
            budget=BUDGET,
            revision=1,
            on_raw_kept=lambda raw: kept.append(dict(raw)),
        )
    assert waited.value.retry_after_s > 0
    assert fitter.calls == [] and len(composer.composes) == composed
    assert kept and kept[0]["key"] and len(seedance.requests) == paid + 1
    retry = _final(producer, brief, _with_attempt(draft, "a1", raw_final=kept[0]), draft_id)
    assert retry.failure is None and len(seedance.requests) == paid + 1  # paid once


def test_a_join_that_takes_the_gate_mid_pass_still_makes_the_final_wait() -> None:
    """The race the early check cannot see: the gate is taken between the check and the
    compose — the final waits (raw 1080p kept), it never overlaps the join."""
    from qualify_api.creative import heavy_video

    composer = FakeComposer()
    producer, _, seedance, draft_id, brief, draft = _draft_and_final_inputs(
        composer, text_layers=(WORDS,)
    )
    gate = heavy_video.joining()
    kept: list[dict[str, Any]] = []
    real_busy = heavy_video.busy
    heavy_video.busy = lambda: False  # the check passed just before the join started
    try:
        with gate, pytest.raises(heavy_video.LocalAssemblyWait) as waited:
            producer.finalize(
                tenant_id=MEDIA_TENANT,
                draft_id=draft_id,
                brief=brief,
                kit=_kit(),
                asset=_with_attempt(draft, "a1"),
                budget=BUDGET,
                revision=1,
                on_raw_kept=lambda raw: kept.append(dict(raw)),
            )
    finally:
        heavy_video.busy = real_busy
    assert waited.value.retry_after_s > 0 and kept and kept[0]["key"]
    paid = len(seedance.requests)
    retry = _final(producer, brief, _with_attempt(draft, "a1", raw_final=kept[0]), draft_id)
    assert retry.failure is None and len(seedance.requests) == paid  # never paid twice


def test_the_final_lays_the_previews_own_text_pngs() -> None:
    composer = FakeComposer()
    producer, store, _, draft_id, brief, draft = _draft_and_final_inputs(
        composer, text_layers=(WORDS,)
    )
    (text,) = draft.params["compose"]["texts"]
    assert store.files[text["key"]] == b"png-Shawarma mixto"
    draws = len(composer.draws)

    final = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)

    assert final.failure is None
    _, recipe, drawn, stage = composer.composes[-1]
    assert stage == "final" and [image.png for image in drawn] == [b"png-Shawarma mixto"]
    assert len(composer.draws) == draws  # the render service is not asked again
    assert final.media.params["compose"]["final"]["texts_reused"] is True


@pytest.mark.parametrize("damage", ["missing", "altered"])
def test_a_missing_or_altered_text_png_is_drawn_again(damage: str) -> None:
    composer = FakeComposer()
    producer, store, _, draft_id, brief, draft = _draft_and_final_inputs(
        composer, text_layers=(WORDS,)
    )
    (text,) = draft.params["compose"]["texts"]
    if damage == "missing":
        del store.files[text["key"]]
    else:
        store.files[text["key"]] = b"another picture"

    final = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)

    assert final.failure is None
    _, _, drawn, stage = composer.composes[-1]
    assert stage == "final" and drawn is None  # the composer draws them again
    assert final.media.params["compose"]["final"]["texts_reused"] is False


def test_a_resumed_seedance_task_goes_on_when_the_texts_cannot_be_drawn() -> None:
    """The clip of this generation is already paid (its task recorded): a failed drawing
    before the call is not fatal — the clip is kept, with the warning."""
    down = ClipComposeFailed(
        "El servicio no responde.",
        failure=FailureReason.DEPENDENCY_FAILED.value,
        code="text_layer_unavailable",
    )
    composer = FakeComposer(fail_draw=down)
    producer, store, seedance = _composing_producer(composer)
    producer._seedance_task_recorded = lambda: True
    outcome = producer.produce(
        tenant_id=MEDIA_TENANT,
        draft_id=uuid4(),
        brief=_brief_with(text_layers=(WORDS,)),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None and len(seedance.requests) == 1
    assert COMPOSE_NOT_ADDED in [w.code for w in outcome.warnings]
    (video,) = outcome.media
    assert "compose" not in video.params
    assert len(composer.draws) == 2  # before the call, and again after it


def test_outside_the_worker_the_preview_warns_and_the_final_fails_free() -> None:
    from qualify_api.creative.process import mark_worker_process, unmark_worker_process

    composer = FakeComposer()
    producer, store, seedance = _composing_producer(composer)
    unmark_worker_process()
    try:
        outcome = producer.produce(
            tenant_id=MEDIA_TENANT,
            draft_id=uuid4(),
            brief=_brief_with(text_layers=(WORDS,)),
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
        )
        assert outcome.failure is None and composer.composes == []
        assert COMPOSE_NOT_ADDED in [w.code for w in outcome.warnings]
        assert "compose" not in outcome.media[0].params
    finally:
        mark_worker_process()

    # a preview composed in the worker, its final ordered outside it
    producer, _, seedance, draft_id, brief, draft = _draft_and_final_inputs(
        FakeComposer(), text_layers=(WORDS,)
    )
    unmark_worker_process()
    try:
        final = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)
    finally:
        mark_worker_process()
    assert final.failure == FailureReason.PROVIDER_ERROR.value
    assert final.detail == FINAL_COMPOSE_FAILED_TEXT
    assert final.draft_changes and final.draft_changes["raw_final"]["key"]  # free retry


def test_a_retry_with_the_final_kept_fits_nothing_again() -> None:
    composer = FakeComposer()
    producer, _, _, draft_id, brief, draft = _draft_and_final_inputs(
        composer, text_layers=(WORDS,), clip_subtitles=True
    )
    first = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)
    assert first.failure is None
    fitter = producer._fitter
    fitter.calls.clear()

    retry = _final(
        producer, brief, _with_attempt(draft, "a1", **(first.draft_changes or {})), draft_id
    )

    assert retry.failure is None and retry.media.object_key == first.media.object_key
    assert fitter.calls == []  # no fit, no subtitles: the kept file is taken as it is
