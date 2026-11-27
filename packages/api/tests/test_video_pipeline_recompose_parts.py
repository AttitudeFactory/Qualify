"""m-25103284: a `reference` PART of a video by parts made by Seedance carries the owner's
texts and the library's layers — composed over its preview BEFORE its logo (so the file
the join reads carries them), composed again over its paid raw 1080p with the preview's
own text PNGs, and the final join reads that composed 1080p.

Seedance, the composer and the join are doubles (nothing paid, nothing rendered): the
fakes of `test_creative_seedance_draft.py`, `test_video_pipeline_recompose.py` and
`test_creative_part_join.py`. The pixels — the boxes of the preview and of the final at
the same place relative to the frame — are measured with real PyAV in
`test_a_parts_boxes_scale_between_its_preview_and_its_final`."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind, FailureReason, GenerationTask
from qualify_creative.providers import GenerationRequest, RenderedPrompt
from qualify_creative.schemas import (
    ContentBrief,
    EffectUse,
    MediaInputs,
    PartRef,
    VideoPartPlan,
    VideoTextLayer,
)

from qualify_api.creative import part_final
from qualify_api.creative.heavy_video import LocalAssemblyWait, assembling
from qualify_api.creative.part_final import join_final, preview_fingerprint
from qualify_api.creative.part_join import PART_FINAL, PartPreview
from qualify_api.creative.pipeline import CheckpointRouter, Preparation, encode_result, preparing
from qualify_api.creative.video_pipeline import recompose
from qualify_api.creative.video_pipeline.local import effects_version_for
from qualify_api.creative.video_pipeline.recipe import (
    subtitle_overlap_problems,
    unbuilt_recipe_problems,
)
from qualify_api.creative.video_pipeline.recompose import (
    COMPOSE_NOT_ADDED,
    COMPOSE_TEXTS_STEP,
    FINAL_COMPOSE_FAILED_TEXT,
    SEEDANCE_COMPOSE_EFFECTS_VERSION,
    compose_recipe_of,
    stored_recipe,
)

from .test_content_service import TENANT_ID as MEDIA_TENANT_OF_PARTS
from .test_content_service import USER_ID as USER_OF_PARTS
from .test_content_service import make_brief, make_kit
from .test_creative_media_byteplus import BUDGET, COPY, _kit
from .test_creative_media_byteplus import TENANT_ID as MEDIA_TENANT
from .test_creative_part_final import FinalJoins, _approved, _snapshot
from .test_creative_part_join import PARENT, Joiner, Store
from .test_creative_parts import parent_brief
from .test_creative_queue_pipeline import Checkpoints
from .test_creative_seedance_draft import (
    DraftSeedance,
    RecordingFitter,
    _clip,
    _producer,
    _store,
)
from .test_video_pipeline_recompose import FakeComposer, _with_attempt

WORDS = VideoTextLayer(text="Shawarma mixto", place="top")
LOW = VideoTextLayer(text="Ensalada griega", place="bottom", start_s=1.0, end_s=3.0)
SMOKE = EffectUse(effect_id="humo_capa", version=1, params={"intensity": 0.8, "zone": "top"})
LOGO = f"t/{MEDIA_TENANT}/brand/logo.png"


@pytest.fixture(autouse=True)
def in_the_worker() -> Iterator[None]:
    """The compose decodes video: only inside the creative worker (`is_worker_process`)."""
    from qualify_api.creative.process import mark_worker_process, unmark_worker_process

    mark_worker_process()
    yield
    unmark_worker_process()


def _part_brief(
    *, mode: str = "reference", version: int = SEEDANCE_COMPOSE_EFFECTS_VERSION, **part: Any
) -> ContentBrief:
    """A part's child brief (what `parts._child_brief` makes): a 9:16 `CLIP` whose recipe
    is its `part`, stamped as the server stamps a part it will compose."""
    brief = _clip(effects_pipeline_version=version)
    fields: dict[str, Any] = {"index": 1, "seconds": 4, "description": "La arepa.", **part}
    ref = PartRef(mode=mode, **fields)  # type: ignore[arg-type]
    media = {
        **brief.media.model_dump(),
        "part": ref.model_dump(),
        "duration_seconds": ref.generation_seconds,
        "text_layers": ref.text_layers,
        "effects": ref.effects,
        "clip_reference_mode": "motion",
    }
    return ContentBrief.model_validate(
        {**brief.model_dump(), "format": ContentFormat.REELS_9_16, "media": media}
    )


# ---------------------------------------------------------------------------
# criterion 1: no longer `recipe_unavailable`


def test_a_reference_part_with_a_text_and_a_layer_is_no_longer_refused() -> None:
    child = _part_brief(text_layers=(WORDS,), effects=(SMOKE,))
    assert unbuilt_recipe_problems(child) == ()
    assert recompose.composes_over_seedance(child)
    # the server stamps it as a piece to compose (`ContentService.prepare_new_generation`)
    assert effects_version_for(child) == SEEDANCE_COMPOSE_EFFECTS_VERSION
    parent = parent_brief(
        VideoPartPlan(seconds=5, description="Uno.", text_layers=(WORDS,)),
        VideoPartPlan(seconds=4, description="Dos.", effects=(SMOKE,)),
    )
    assert unbuilt_recipe_problems(parent) == ()


def test_a_parent_with_a_texted_reference_part_makes_its_parts_stamped_to_compose() -> None:
    """End to end through `PartsService.create_parts`: the part is created (not
    `recipe_unavailable`), its child brief carries its text and is stamped by the server
    with the compose's effects pipeline (so the producer composes it); a part without
    texts stays at 0, made as before."""
    from .test_creative_parts import world

    plan = (
        VideoPartPlan(seconds=5, description="Uno.", text_layers=(WORDS,)),
        VideoPartPlan(seconds=5, description="Dos."),
    )
    parts, _, repo, _, dispatcher, _, parent = world(plan=plan)
    parts.create_parts(tenant_id=MEDIA_TENANT_OF_PARTS, parent_id=parent, user_id=USER_OF_PARTS)
    children = sorted(
        repo.parts_of(tenant_id=MEDIA_TENANT_OF_PARTS, parent_id=parent),
        key=lambda d: d.part_index,
    )
    assert len(children) == 2 and len(dispatcher.calls) == 2
    first, second = (repo.briefs[child.brief_id] for child in children)
    assert first.media.part.text_layers == (WORDS,)
    assert first.media.effects_pipeline_version == SEEDANCE_COMPOSE_EFFECTS_VERSION
    assert second.media.effects_pipeline_version == 0


def test_an_extend_part_with_a_text_stays_refused() -> None:
    """«Sigue a la anterior» continues the previous part's own vendor file: not composed."""
    parent = parent_brief(
        VideoPartPlan(seconds=5, description="Uno."),
        VideoPartPlan(mode="extend", seconds=4, description="Dos.", text_layers=(WORDS,)),
    )
    assert [(p.code, p.part, p.field) for p in unbuilt_recipe_problems(parent)] == [
        ("recipe_unavailable", 2, "text_layers")
    ]


def test_a_part_trimmed_by_the_plan_moves_its_times_to_the_kept_interval() -> None:
    """The join keeps `[trim_start_s, trim_end_s]` of the part's file: the recipe's times
    (seconds of the part as it shows) are moved by the trim's start."""
    trimmed = _part_brief(
        seconds=2,
        trim_start_s=1.5,
        trim_end_s=3.5,
        text_layers=(WORDS, LOW),
        effects=(SMOKE.model_copy(update={"start_s": 0.5, "end_s": 1.5}),),
    )
    recipe = compose_recipe_of(trimmed, make_kit())
    assert recipe is not None
    assert [(t.start_s, t.end_s) for t in recipe.text_layers] == [(1.5, None), (2.5, 4.5)]
    assert [(e.start_s, e.end_s) for e in recipe.effects] == [(2.0, 3.0)]
    plain = compose_recipe_of(_part_brief(text_layers=(LOW,)), make_kit())
    assert plain is not None and plain.text_layers == (LOW,)


def test_a_part_carries_no_subtitles_so_a_bottom_text_is_allowed() -> None:
    """Criterion 5: «Subtítulos» is a normal Clip's switch (a part is born without it and
    the producer lays subtitles only when `media.part` is None), so a part's bottom text
    is never refused for it — while a Clip with subtitles still is."""
    child = _part_brief(text_layers=(LOW,))
    with_switch = child.model_copy(
        update={"media": child.media.model_copy(update={"clip_subtitles": True})}
    )
    assert subtitle_overlap_problems(with_switch) == ()
    assert unbuilt_recipe_problems(with_switch) == ()
    clip = make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(duration_seconds=5, clip_subtitles=True, text_layers=(LOW,)),
    )
    assert [p.code for p in subtitle_overlap_problems(clip)] == ["text_bottom_with_subtitles"]


# ---------------------------------------------------------------------------
# the part's preview: composed, before its logo


class LogoFitter(RecordingFitter):
    """Lays a logo by prefixing it (the overlay is a PNG), records every call."""

    def fit(self, data: bytes, *, size: tuple[int, int], **kw: Any) -> Any:
        fitted = super().fit(data, size=size, **kw)
        if kw.get("overlay") is not None:
            return replace(fitted, data=b"LOGO|" + data)
        return fitted


def _logo_png() -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(out, "PNG")
    return out.getvalue()


def _part_producer(composer: FakeComposer, *, logo: bool = True) -> tuple[Any, Any, Any, Any]:
    store, seedance, fitter = _store(), DraftSeedance(), LogoFitter()
    producer = _producer(store, seedance, fitter)
    producer._clip_composer = composer
    if logo:
        store.files[LOGO] = _logo_png()
    producer._part_joins = SimpleNamespace(parent_logo_key=lambda **_: LOGO if logo else None)
    return producer, store, seedance, fitter


def _produce(producer: Any, brief: ContentBrief, draft_id: Any = None) -> Any:
    return producer.produce(
        tenant_id=MEDIA_TENANT,
        draft_id=draft_id or uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )


def _preview_of(write: Any) -> PartPreview:
    return PartPreview(
        draft_id=uuid4(),
        part_index=1,
        status="generated",
        revision=1,
        version_id=uuid4(),
        object_key=write.object_key,
        params=write.params,
    )


def test_a_parts_preview_is_composed_before_its_logo_and_the_join_reads_it() -> None:
    composer = FakeComposer()
    producer, store, seedance, fitter = _part_producer(composer)
    outcome = _produce(producer, _part_brief(text_layers=(WORDS,), effects=(SMOKE,)))

    assert outcome.failure is None, outcome.detail
    assert len(seedance.requests) == 1 and len(composer.draws) == 1
    ((source, recipe, drawn, stage),) = composer.composes
    assert stage == "preview" and recipe.text_layers == (WORDS,) and recipe.effects == (SMOKE,)
    assert [d.png for d in drawn] == [b"png-Shawarma mixto"]
    (video,) = outcome.media
    part = video.params["part"]
    # the file the join reads: the texts, and no logo (the join lays it once)
    assert store.files[part["clean_key"]] == b"composed-" + source
    # the file the owner sees: the texts under the logo
    assert video.object_key.endswith("clip-logo.mp4") and video.params["logo"] is True
    assert store.files[video.object_key] == b"LOGO|composed-" + source
    assert fitter.calls[-1]["overlay"] is not None and fitter.calls[-1]["size"] == (480, 854)
    assert _preview_of(video).join_source == part["clean_key"]
    # the recipe is frozen for the part's final, with its text PNGs kept beside it
    assert stored_recipe(video.params) == recipe
    texts = video.params["compose"]["texts"]
    assert store.files[texts[0]["key"]] == b"png-Shawarma mixto"
    assert video.params["draft"]["task_id"] == "cgt-draft"  # its final is ordered from it


def test_a_part_without_a_logo_shows_and_joins_its_composed_file() -> None:
    composer = FakeComposer()
    producer, store, _, _ = _part_producer(composer, logo=False)
    (video,) = _produce(producer, _part_brief(text_layers=(WORDS,))).media
    assert video.params["part"]["clean_key"] == video.object_key
    assert store.files[video.object_key].startswith(b"composed-")


def test_a_parts_preview_whose_compose_fails_keeps_the_paid_clip_with_a_warning() -> None:
    composer = FakeComposer(fail_compose=True)
    producer, store, seedance, _ = _part_producer(composer)
    outcome = _produce(producer, _part_brief(text_layers=(WORDS,)))
    assert outcome.failure is None and len(seedance.requests) == 1
    assert COMPOSE_NOT_ADDED in [w.code for w in outcome.warnings]
    (video,) = outcome.media
    assert "compose" not in video.params  # its final lays none either
    assert store.files[video.params["part"]["clean_key"]] == b"hevc-bytes"


def test_a_part_without_texts_is_made_exactly_as_before() -> None:
    composer = FakeComposer()
    producer, store, _, _ = _part_producer(composer)
    (video,) = _produce(producer, _part_brief(version=0)).media
    assert composer.draws == [] and composer.composes == []
    assert "compose" not in video.params
    assert store.files[video.params["part"]["clean_key"]] == b"hevc-bytes"


# ---------------------------------------------------------------------------
# the part's final: its raw 1080p composed again, what the final join reads


def _final(producer: Any, brief: ContentBrief, asset: Any, draft_id: Any) -> Any:
    return producer.finalize(
        tenant_id=MEDIA_TENANT,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        asset=asset,
        budget=BUDGET,
        revision=1,
    )


def _drafted(composer: FakeComposer, **part: Any) -> tuple[Any, ...]:
    producer, store, seedance, fitter = _part_producer(composer)
    draft_id = uuid4()
    brief = _part_brief(**part)
    (draft,) = _produce(producer, brief, draft_id).media
    return producer, store, seedance, fitter, draft_id, brief, draft


def _paid_finals(seedance: DraftSeedance) -> int:
    return sum(1 for r in seedance.requests if "draft_task_id" in r.params)


def test_a_parts_final_is_its_raw_1080p_composed_with_the_previews_own_texts() -> None:
    composer = FakeComposer()
    producer, store, seedance, fitter, draft_id, brief, draft = _drafted(
        composer, text_layers=(WORDS,), effects=(SMOKE,)
    )
    fitted_before = len(fitter.calls)

    outcome = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)

    assert outcome.failure is None and outcome.media is not None, outcome.detail
    assert len(composer.draws) == 1  # the preview's PNGs: the render service not asked again
    preview, final = composer.composes
    assert final[3] == "final" and final[0] == b"hevc-bytes"  # over the raw 1080p, unfitted
    assert final[1] == preview[1] and [d.png for d in final[2]] == [b"png-Shawarma mixto"]
    assert len(fitter.calls) == fitted_before  # no H.264 fit, no logo: the join's job
    write = outcome.media
    block = write.params["draft"]
    assert block["status"] == PART_FINAL
    assert store.files[block["raw_final"]["key"]] == b"hevc-bytes"  # kept as it came
    composed = block["composed_final"]
    assert store.files[composed["key"]] == b"composed-hevc-bytes"
    assert block["part_final_key"] == composed["key"] != block["raw_final"]["key"]
    assert composed["from_raw_final_key"] == block["raw_final"]["key"]
    assert composed["recipe_sha256"] == draft.params["compose"]["preview"]["recipe_sha256"]
    # the row still shows its preview; the final's provenance joins the preview's
    assert write.object_key == draft.object_key
    assert write.params["compose"]["final"]["from_task_id"] == "cgt-final"
    assert write.params["compose"]["final"]["part"] is True
    assert write.params["compose"]["recipe"] == draft.params["compose"]["recipe"]
    # and the final join reads the composed file, not the raw one
    assert part_final.raw_key(_preview_of(write)) == composed["key"]
    assert _paid_finals(seedance) == 1


def test_two_retries_of_a_parts_final_pay_and_compose_once() -> None:
    """Criterion 3: the last write never landed — the retry (same order) finds the raw
    1080p AND the composed one kept: nothing paid, drawn or composed again."""
    composer = FakeComposer()
    producer, store, seedance, _, draft_id, brief, draft = _drafted(composer, text_layers=(WORDS,))
    first = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)
    assert first.failure is None and first.media is not None
    paid, drawn, composed = _paid_finals(seedance), len(composer.draws), len(composer.composes)

    retry = _final(
        producer, brief, _with_attempt(draft, "a1", **(first.draft_changes or {})), draft_id
    )

    assert retry.failure is None and retry.media is not None
    assert _paid_finals(seedance) == paid == 1
    assert (len(composer.draws), len(composer.composes)) == (drawn, composed)
    again = retry.media.params["draft"]["composed_final"]
    assert again["key"] == first.media.params["draft"]["composed_final"]["key"]
    assert retry.media.params["compose"]["final"]["reused"] is True
    finals = [k for k in store.files if "-final-" in k and k.endswith(".mp4") and "raw" not in k]
    assert finals == [again["key"]]


def test_a_parts_final_whose_compose_fails_keeps_its_raw_1080p_for_a_free_retry() -> None:
    composer = FakeComposer()
    producer, _, seedance, _, draft_id, brief, draft = _drafted(composer, text_layers=(WORDS,))
    composer.fail_compose = True

    failed = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)

    assert failed.failure == FailureReason.PROVIDER_ERROR.value and failed.media is None
    assert failed.detail == FINAL_COMPOSE_FAILED_TEXT
    assert failed.draft_changes and failed.draft_changes["raw_final"]["key"]
    composer.fail_compose = False
    retry = _final(producer, brief, _with_attempt(draft, "a2", **failed.draft_changes), draft_id)
    assert retry.failure is None and retry.media is not None
    assert _paid_finals(seedance) == 1  # never paid twice
    assert retry.media.params["draft"]["composed_final"]["key"]


def test_a_part_without_texts_keeps_its_raw_1080p_as_before() -> None:
    composer = FakeComposer()
    producer, _, _, _, draft_id, brief, draft = _drafted(composer, version=0)
    outcome = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)
    assert outcome.failure is None and composer.composes == []
    block = outcome.media.params["draft"]
    assert "composed_final" not in block and block["part_final_key"] == block["raw_final"]["key"]


def test_a_parts_final_waits_for_a_part_join_and_pays_nothing_again() -> None:
    """Criterion 4: with a join holding the heavy-video gate the composing pass waits
    (`LocalAssemblyWait`, a checkpoint error) — its raw 1080p is kept, the next pass
    composes it without paying the vendor again."""
    composer = FakeComposer()
    producer, _, seedance, _, draft_id, brief, draft = _drafted(composer, text_layers=(WORDS,))
    kept: list[Any] = []
    with assembling():  # a part join holds the gate
        with pytest.raises(LocalAssemblyWait):
            producer.finalize(
                tenant_id=MEDIA_TENANT,
                draft_id=draft_id,
                brief=brief,
                kit=_kit(),
                asset=_with_attempt(draft, "a1"),
                budget=BUDGET,
                revision=1,
                on_raw_kept=kept.append,
            )
    assert len(composer.composes) == 1 and _paid_finals(seedance) == 1  # only the preview
    (raw,) = kept
    retry = _final(producer, brief, _with_attempt(draft, "a1", raw_final=raw), draft_id)
    assert retry.failure is None and _paid_finals(seedance) == 1
    assert retry.media.params["draft"]["composed_final"]["key"]


def test_a_parts_preview_waits_for_a_part_join_once_its_clip_is_there() -> None:
    composer = FakeComposer()
    producer, _, _, _ = _part_producer(composer)
    with assembling():
        with pytest.raises(LocalAssemblyWait):
            _produce(producer, _part_brief(text_layers=(WORDS,)))
    assert composer.composes == []


# ---------------------------------------------------------------------------
# criterion 2: the final join reads every part's composed 1080p


def _part_final_preview(index: int, write: Any) -> PartPreview:
    return PartPreview(
        draft_id=uuid4(),
        part_index=index,
        status="approved",
        revision=1,
        version_id=uuid4(),
        object_key=write.object_key,
        params=write.params,
    )


def test_the_final_join_lays_every_parts_composed_1080p() -> None:
    composer = FakeComposer()
    producer, store, _, _, draft_id, brief, draft = _drafted(composer, text_layers=(WORDS,))
    one = _final(producer, brief, _with_attempt(draft, "a1"), draft_id).media
    other = _part_brief(index=2, text_layers=(LOW,))
    draft_two = uuid4()
    (preview_two,) = _produce(producer, other, draft_two).media
    two = _final(producer, other, _with_attempt(preview_two, "a2"), draft_two).media
    parts = (_part_final_preview(1, one), _part_final_preview(2, two))
    shown = {
        "finish": "join",
        "status": "join_preview",
        "fingerprint": preview_fingerprint(parts, {"logo": "sin logo"}),
        "parent_revision": 1,
        "logo": "sin logo",
    }
    snapshot = _approved(_snapshot(*parts, block=shown))
    joiner, files = Joiner(), Store(dict(store.files))

    write = join_final(files, FinalJoins(snapshot), MEDIA_TENANT, PARENT, joiner=joiner)

    assert write is not None, "the final join did not run"
    assert len(joiner.calls) == 1
    # the joined stand-in is every part's file as the join read it: both composed
    assert files.files[write.object_key] == b"joined:composed-hevc-bytes|composed-hevc-bytes"
    keys = [p["raw_final_key"] for p in write.params["join_final"]["parts"]]
    assert keys == [p.params["draft"]["raw_final"]["key"] for p in parts]
    composed = [p["composed_final_key"] for p in write.params["join_final"]["parts"]]
    assert composed == [p.params["draft"]["composed_final"]["key"] for p in parts]


# ---------------------------------------------------------------------------
# criterion 3: no double charge across the queue's passes (`CheckpointRouter`)


class _PartRouter(CheckpointRouter):
    """The worker's router, without the database read of `_is_part` (it is one)."""

    def _is_part(self, run: Any) -> bool:
        return True


@pytest.fixture
def checkpoints() -> Iterator[Checkpoints]:
    rows = Checkpoints()
    with patch("qualify_api.creative.pipeline.PipelineStore", return_value=rows):
        yield rows


def test_the_queues_passes_pay_seedance_once_and_draw_once(checkpoints: Checkpoints) -> None:
    """Pass 1 draws and keeps the PNGs, then orders Seedance (paid by the executor); the
    pass that brings the clip replays it from its checkpoint and composes with the kept
    PNGs; a third pass (a lost write) neither pays nor draws again. No Claude call is
    made anywhere: a part's words come from its parent's text."""
    composer = FakeComposer()
    producer, files, seedance, _ = _part_producer(composer)
    router = producer._router
    calls: list[str] = []
    real_run = router.run

    def counting(**kwargs: Any) -> Any:
        calls.append(kwargs["chain"][0])
        return real_run(**kwargs)

    router.run = counting  # type: ignore[method-assign]
    draft_id, brief = uuid4(), _part_brief(text_layers=(WORDS,))

    def one_pass() -> Any:
        producer._router = _PartRouter(router, checkpoints, files)
        run = Preparation(MEDIA_TENANT, draft_id, 1, "generation", uuid4(), 1)
        with preparing(run):
            return _produce(producer, brief, draft_id)

    first = one_pass()
    assert first.pending and len(composer.draws) == 1 and seedance.requests == []
    assert COMPOSE_TEXTS_STEP in checkpoints.rows
    (row,) = [r for r in checkpoints.rows.values() if r["job_id"] is not None]
    remote = seedance.generate(
        GenerationRequest(
            task=GenerationTask.SCENE_VIDEO, rendered_prompt=RenderedPrompt("", "", "")
        ),
        api_key="fake",
    )
    row["result"] = encode_result(remote, files, "result", MEDIA_TENANT)

    second = one_pass()
    third = one_pass()

    for outcome in (second, third):
        assert outcome.failure is None and not outcome.pending, outcome.detail
        (video,) = outcome.media
        assert video.params["compose"]["recipe"]["text_layers"][0]["text"] == WORDS.text
    assert len(seedance.requests) == 1  # the executor's one order
    assert len(composer.draws) == 1  # the render service asked once
    assert calls == []  # every vendor call came back from its checkpoint


# ---------------------------------------------------------------------------
# criterion 1: the same place in the preview and the final, ±2 px (real PyAV)


def test_a_parts_boxes_scale_between_its_preview_and_its_final(tmp_path: Path) -> None:
    """A part's preview goes as `_compose_clip` takes it (Seedance's 496x864 cut to 9:16,
    then composed); its final is composed straight over the 1080x1920 raw file, as
    `_composed_part_final` does when the vendor's size is 9:16."""
    pytest.importorskip("av")
    from qualify_api.creative.video_pipeline.recompose import ClipComposer, ComposeRecipe

    from .test_video_pipeline_recompose_pixels import (
        BOTTOM,
        TOLERANCE_PX,
        TOP,
        _boxes,
        _drawn,
        _luma,
        _preview,
        _scaled,
        _video,
    )

    texts = (
        VideoTextLayer(text="Shawarma mixto", place="top", fade_s=0.3),
        VideoTextLayer(text="Ensalada", place="bottom", fade_s=0.3),
    )
    recipe = ComposeRecipe(text_layers=texts, brand={"palette": [], "fonts": {}})
    drawn = _drawn(TOP, BOTTOM)
    composer = ClipComposer(render_client=object())

    preview = _preview(composer, recipe, drawn, tmp_path, 40)
    raw = _video(tmp_path / "raw.mp4", (1080, 1920), 40)
    assert recompose.nine_sixteen_size(1080, 1920) is None  # composed over the raw as it is
    final = composer.compose(raw, recipe, drawn=drawn, stage="final")

    seen = _boxes(_luma(preview.data, tmp_path, "p.mp4"), 0.5)
    made = _boxes(_luma(final.data, tmp_path, "f.mp4"), 0.5)
    sx, sy = preview.width / final.width, preview.height / final.height
    for shown, composed in zip(seen, made, strict=True):
        back = _scaled(composed, sx, sy)
        assert all(abs(a - b) <= TOLERANCE_PX for a, b in zip(shown, back, strict=True)), (
            shown,
            back,
        )


# ---------------------------------------------------------------------------
# EF-18 (#788): the part's contact sheet, with its texts composed before the logo


@pytest.mark.parametrize("logo_fails", [False, True], ids=["logo_laid", "logo_failed"])
def test_a_parts_contact_sheet_follows_the_file_the_owner_sees(
    tmp_path: Path, logo_fails: bool
) -> None:
    """A part is composed BEFORE its logo, so its clean file carries the texts: the sheet
    (made from the composed file) is tied to the shown file whether the logo was laid
    or not; the part's final makes no sheet of its own."""
    from qualify_api.creative.contact_sheet import contact_sheet_of

    from .test_video_pipeline_recompose import _sheet_video

    composer = FakeComposer()
    composer.sheet_video = _sheet_video(tmp_path)
    producer, _, _, fitter = _part_producer(composer)
    fitter.fail_overlay = logo_fails
    draft_id, brief = uuid4(), _part_brief(text_layers=(WORDS,))
    (draft,) = _produce(producer, brief, draft_id).media

    assert draft.params["logo"] is (not logo_fails)
    block = draft.params["contact_sheet"]
    assert block["source"]["object_key"] == draft.object_key
    assert contact_sheet_of(draft.object_key, draft.params) is not None
    if logo_fails:
        assert draft.object_key == draft.params["part"]["clean_key"]  # composed, shown

    final = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)
    assert final.failure is None and composer.sheet_hooks[-1] is None
