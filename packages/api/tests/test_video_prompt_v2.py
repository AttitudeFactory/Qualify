"""Prompt compiler 2 (founder, 2026-11-03): the Seedance 2.x clip routes rewritten from the
audit `docs/modelos-generativos/auditoria-prompts-clip-20261103.md` §7 — motion clip, reel
replica and animated gallery slide — checked by the quality guard
(`prompt_quality.assert_video_prompt_v2_quality`), not by their wording; and the clip's copy
as subtitles laid after Seedance (`MediaInputs.clip_subtitles`). Offline, on the anonymized
real case; not model quality (that is the night A/B, audit §7)."""

from __future__ import annotations

import hashlib
import itertools
import re
from typing import Any

import pytest
from qualify_creative.adapters.byteplus_ark import VIDEO_PROMPT_MAX_WORDS, prompt_words
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import ContentBrief, CopyPayload, MediaInputs, ScriptShot

from qualify_api.creative import media as media_module
from qualify_api.creative.brand_references import BrandReference
from qualify_api.creative.media import (
    _CAROUSEL_REFERENCE_SUFFIX,
    _PROMPT_REPORTS,
    _SHOT_MAX,
    NO_LOGO_SUPPLIED_V2,
    PROMPT_COMPILER_VERSION,
    _carousel_reference_motion,
    _prints_words,
    carousel_motion_prompt,
    clip_prompt,
    clip_subtitle_cues,
)

from .prompt_quality import assert_video_prompt_v2_quality
from .test_prompt_budget_v1 import (
    DATA,
    SEEDANCE_10,
    SEEDANCE_25,
    _chosen,
    _kit,
    _real,
    _with_brand_text,
)

SHOTS = CopyPayload(
    hook="La que te llama",
    caption="Texto",
    cta="Pide ya",
    shots=(
        ScriptShot(visual="Primer plano de la carne sobre la plancha caliente.", seconds=2),
        ScriptShot(visual="El queso se derrite sobre la doble carne.", seconds=2),
        ScriptShot(
            visual="La hamburguesa servida en su papel, con el imagotipo de la marca en la "
            "fachada al fondo.",
            seconds=1,
        ),
    ),
)
#: The source brand's own words in the fixture (its handle, its post id, a name its caption
#: shows): never outside the untrusted metadata.
FOREIGN = ("@referencia_0001", "reel-ejempl", "Supanega")
COMBOS = [c for k in (0, 1, 2, 3) for c in itertools.combinations(range(3), k)]


def _motion(**media: Any) -> ContentBrief:
    brief = _real(
        version=2,
        clip_reference_mode="motion",
        source_reel=None,
        clip_image_keys=("a", "b"),
        clip_image_roles=("product", "product"),
        **media,
    )
    return brief.model_copy(update={"topic": brief.topic.split("\n\n")[0]})


def _clip(
    brief: ContentBrief,
    refs: list[BrandReference],
    *,
    copy: CopyPayload | None = SHOTS,
    images: int = 2,
    frames: tuple[bool, bool] = (False, False),
    model: str = SEEDANCE_25,
) -> str:
    return clip_prompt(
        brief=brief,
        kit=_kit(),
        first_frame=frames[0],
        last_frame=frames[1],
        images=images,
        videos=1,
        audios=0,
        image_roles=("product",) * images,
        brand_refs=refs,
        copy=copy,
        model=model,
    )


def _guard_motion(prompt: str, brief: ContentBrief, refs: list[BrandReference], **kw: Any) -> None:
    assert_video_prompt_v2_quality(
        prompt,
        route="motion",
        brief=brief,
        kit=_kit(),
        refs=refs,
        texts=(brief.topic, *(shot.visual for shot in SHOTS.shots)),
        product=brief.product_ref or "",
        **kw,
    )


# -- new executions get compiler 2; the frozen ones never change ---------------------------


def test_new_executions_are_stamped_with_compiler_2() -> None:
    from .test_prompt_budget_v1 import Selector, _fixture_producer

    producer, _ = _fixture_producer(Selector())
    stamped = producer.prepare_new_brief(_real(version=0), _kit())
    assert stamped.media.prompt_compiler_version == PROMPT_COMPILER_VERSION == 5


#: sha256 of the compiler-0 and compiler-1 prompts of the anonymized case, taken 2026-11-03
#: right after compiler 2 landed and checked equal to the pre-change compiler on the audit's
#: eleven scenarios (and to the two prompts logged for drafts ddfcafc9 / cfde8564): a frozen
#: draft is recompiled byte for byte, whatever compiler 2 does.
FROZEN_DIGESTS = {
    ("motion", 0): "047c6e0291064a0920802683ab9a31a58551542624d126569405122f8c8a1e35",
    ("motion", 1): "d8711b189957600e27202d1caad04f1dd98cb9da8bc8e54230b40f3cde7e5be8",
    ("edit", 0): "c47cf1f97c886f29060e82a6a970adf3cdaa7506c6f964f880cc19721cd1f046",
    ("edit", 1): "f4ba849db1643e8319f027ab4ea7b45e49db460394b7b4a17b4f49f988904b7a",
    ("slide", 0): "d8ea4ebe7902db74830c57f52ebf5ae39b7c3052f0677e6d23ce3bec66953ab5",
    ("slide", 1): "b53479f2e30db68b1d2e2159b1da98aa7c672631a0066833d45dd4c9bcffc3ba",
}


def _frozen(route: str, version: int) -> str:
    refs = _chosen((1,))  # the one logo compiler 0 fits in the replica (V0_LENGTHS)
    if route == "motion":
        brief = _motion().model_copy(
            update={
                "media": _motion().media.model_copy(update={"prompt_compiler_version": version})
            }
        )
        return _clip(brief, refs)
    if route == "edit":
        return _clip(_real(version=version), refs, copy=None, images=1)
    brief = _real(version=version, clip_reference_mode="motion", source_reel=None)
    brief = brief.model_copy(update={"kind": ContentKind.CAROUSEL})
    return carousel_motion_prompt(brief, refs, numbered=False, kit=_kit(), uncapped=True)


@pytest.mark.parametrize(("route", "version"), sorted(FROZEN_DIGESTS))
def test_frozen_compilers_are_byte_for_byte_unchanged(route: str, version: int) -> None:
    digest = hashlib.sha256(_frozen(route, version).encode()).hexdigest()
    assert digest == FROZEN_DIGESTS[(route, version)]


# -- the motion clip ------------------------------------------------------------------------


@pytest.mark.parametrize("combo", COMBOS)
@pytest.mark.parametrize("frames", [(False, False), (True, False), (True, True)])
def test_motion_clip_passes_the_quality_guard(
    combo: tuple[int, ...], frames: tuple[bool, bool]
) -> None:
    brief, refs = _motion(), _chosen(combo)
    prompt = _clip(brief, refs, frames=frames)
    _guard_motion(prompt, brief, refs, base_index=1 + sum(frames) + 2)


def test_motion_clip_says_no_text_and_drops_the_compressed_wording() -> None:
    prompt = _clip(_motion(), _chosen((0,)))
    assert "Do not show any written text, captions, subtitles or titles." in prompt
    for old in (
        "Restyle existing/approved client text",
        "Headlines/CTAs assigned to local composition",
        "Brand graphics/approved text accents",
        "Reference videos guide camera/actions only",
        "Categories override filenames",
        "Logo alternatives were already resolved",
        "Client typefaces: headlines=",
    ):
        assert old not in prompt
    # H7: the product sentence near the start, its photo line unrepeated
    assert prompt.index('It shows the client\'s real product, "producto XY"') < 250
    assert "Images 1 and 2: the client's real product — keep it exactly as it is" in prompt


def test_without_a_logo_the_shots_that_name_one_are_overruled() -> None:
    """H2: the copy's shots are written before the resource selector — a shot naming the
    logo («con el imagotipo de la marca…») with no logo sent says: draw none."""
    with_logo, without = _clip(_motion(), _chosen((0,))), _clip(_motion(), [])
    assert "imagotipo de la marca" in without  # the copy's shot travels literal
    assert NO_LOGO_SUPPLIED_V2 in without and "where a shot mentions a logo" in without
    assert NO_LOGO_SUPPLIED_V2 not in with_logo
    assert "Image 3 is the client's logo (imagotipo:" in with_logo


def test_the_frames_and_the_video_say_what_commands() -> None:
    prompt = _clip(_motion(), [], frames=(True, True))
    assert (
        "The video starts exactly on Image 1 (the opening frame) and ends exactly on Image 2 "
        "(the closing frame); adapt the shots to them."
    ) in prompt
    assert "Images 3 and 4: the client's real product" in prompt
    assert "Follow the camera movement, motion and pacing of Video 1; the shots above" in prompt


def test_on_2x_nothing_is_capped_per_field_and_on_1x_the_caps_stay() -> None:
    """H10: a long shot and the facts past 500 characters go whole on Seedance 2.x; a 1.x
    model keeps its character budget and the per-field caps."""
    long_shot = "La carne chisporrotea sobre la plancha " * 12
    copy = CopyPayload(
        hook="Gancho",
        caption="Texto",
        cta="Pide ya",
        shots=(ScriptShot(visual=long_shot, seconds=5),),
    )
    facts = tuple((f"dato {i}", "x" * 60) for i in range(10))
    brief = _motion()
    brief = brief.model_copy(
        update={"constraints": brief.constraints.model_copy(update={"highlights": facts})}
    )
    assert len(long_shot) > _SHOT_MAX
    whole = _clip(brief, [], copy=copy)
    assert " ".join(long_shot.split()) in whole
    assert all(f'"dato {i}": "{"x" * 60}"' in whole for i in range(10))
    capped = _clip(brief, [], copy=copy, model=SEEDANCE_10)
    assert " ".join(long_shot.split()) not in capped and len(capped) <= 3000


def test_over_the_word_ceiling_a_v2_clip_is_refused_before_paying() -> None:
    brief = _motion().model_copy(update={"topic": "palabra " * (VIDEO_PROMPT_MAX_WORDS + 10)})
    with pytest.raises(media_module._PromptOverBudget):
        _clip(brief, [])


def test_nothing_is_trimmed_and_the_report_says_compiler_2_has_no_char_budget() -> None:
    reports: list[dict[str, Any]] = []
    token = _PROMPT_REPORTS.set(reports)
    try:
        prompt = _clip(_motion(), _chosen((0, 1, 2)))
    finally:
        _PROMPT_REPORTS.reset(token)
    (report,) = reports
    assert report["prompt_budget"] is None and report["trims"] == ()
    assert report["prompt_words"] == prompt_words(prompt) <= VIDEO_PROMPT_MAX_WORDS


# -- the reel replica ---------------------------------------------------------------------


@pytest.mark.parametrize("combo", COMBOS)
@pytest.mark.parametrize("brand_text", [False, True])
def test_replica_passes_the_quality_guard(combo: tuple[int, ...], brand_text: bool) -> None:
    brief = _with_brand_text(_real(version=2), brand_text)
    refs = _chosen(combo)
    prompt = _clip(brief, refs, copy=None, images=1)
    assert_video_prompt_v2_quality(
        prompt,
        route="edit",
        brief=brief,
        kit=_kit(),
        refs=refs,
        base_index=2,
        product=brief.product_ref or "",
        product_photo=True,
        foreign=FOREIGN,
    )


def test_replica_keeps_the_footage_first_and_the_facts_as_context_only() -> None:
    prompt = _clip(_real(version=2), _chosen((0,)), copy=None, images=1)
    assert prompt.startswith("Edit @Video1 in place, not a new video: keep its footage,")
    # H4: the facts never reshape the reel; H5: no «not its visual style»
    assert "Context only: do not add or change shots for them" in prompt
    assert "shape the story" not in prompt and "not its visual style" not in prompt
    # H8: no positioning; §6: one image syntax
    assert "Client identity" not in prompt and _kit().positioning not in prompt
    assert "@Image2 is the client's logo" in prompt and not re.search(r"\bImage \d", prompt)
    # H3: `main`'s lost points
    for unit in (
        "do not show the fully assembled product early",
        "layers, shape, colors, proportions",
        "do not recreate its music or speech",
        "Do not cut to a catalog still or a new final hero shot",
        "shot count, shot order",
    ):
        assert unit in prompt


def test_a_replica_without_a_product_photo_or_a_logo_says_both() -> None:
    prompt = _clip(
        _real(version=2, clip_image_keys=(), clip_image_roles=()), [], copy=None, images=0
    )
    assert "No product photo is supplied" in prompt
    assert f"{NO_LOGO_SUPPLIED_V2}: do not draw any logo" in prompt


def test_an_unknown_guidance_still_travels_verbatim_in_a_v2_replica() -> None:
    brief = _real(version=2)
    edited = brief.topic.replace("Es solo la guía de secuencia", "Es la guía de secuencia")
    brief = brief.model_copy(update={"topic": edited})
    prompt = _clip(brief, _chosen((0,)), copy=None, images=1)
    assert "App production directions (trusted, not source captions)" in prompt
    assert "Es la guía de secuencia" in prompt


# -- the animated gallery slide --------------------------------------------------------------


def _slide(**media: Any) -> ContentBrief:
    brief = _real(version=2, clip_reference_mode="motion", source_reel=None, **media)
    return brief.model_copy(update={"kind": ContentKind.CAROUSEL})


@pytest.mark.parametrize("combo", COMBOS)
@pytest.mark.parametrize("numbered", [False, True])
def test_animated_slide_passes_the_quality_guard(combo: tuple[int, ...], numbered: bool) -> None:
    refs = _chosen(combo)
    prompt = carousel_motion_prompt(_slide(), refs, numbered=numbered, kit=_kit(), uncapped=True)
    if numbered:
        prompt = _carousel_reference_motion(prompt, strict=bool(refs), uncapped=True)
        assert prompt.endswith(_CAROUSEL_REFERENCE_SUFFIX)
    assert_video_prompt_v2_quality(
        prompt,
        route="slide",
        brief=_slide(),
        kit=_kit(),
        refs=refs,
        base_index=2,
        numbered=numbered,
    )
    # the photograph already shows the resources: kept, never added again (audit §6)
    assert "Integrate" not in prompt and "Let them shape" not in prompt
    if refs:
        assert "do not add" in prompt


# -- the subtitles option -------------------------------------------------------------------


def test_the_subtitles_option_is_off_by_default_and_frozen_with_the_inputs() -> None:
    assert MediaInputs().clip_subtitles is False
    stored = DATA["brief"]["media"]
    assert "clip_subtitles" not in stored  # a brief stored before it: off
    assert ContentBrief.model_validate(DATA["brief"]).media.clip_subtitles is False
    on = MediaInputs(clip_subtitles=True)
    assert MediaInputs.model_validate(on.model_dump()).clip_subtitles is True


def test_the_subtitles_option_never_reaches_the_video_prompt() -> None:
    off, on = _motion(), _motion(clip_subtitles=True)
    assert _clip(off, []) == _clip(on, [])
    assert "Do not show any written text" in _clip(on, [])


def test_the_clip_cues_are_the_hook_first_and_the_cta_last() -> None:
    cues = clip_subtitle_cues(SHOTS, 5)
    assert [cue["text"] for cue in cues] == ["La que te llama", "Pide ya"]
    hook, cta = cues
    assert 0 < hook["start"] < hook["end"] <= cta["start"] < cta["end"] <= 5
    assert _prints_words(_motion(clip_subtitles=True).model_copy(update={"kind": ContentKind.CLIP}))
    assert not _prints_words(_motion().model_copy(update={"kind": ContentKind.CLIP}))


@pytest.mark.parametrize("route", ["motion", "edit", "slide"])
def test_the_v2_guard_rejects_the_compiler_1_prompts(route: str) -> None:
    """The guard is not vacuous: the compiler-1 wording it replaces fails it (audit §5)."""
    with pytest.raises(AssertionError):
        assert_video_prompt_v2_quality(
            _frozen(route, 1),
            route=route,
            brief=_real(version=1),
            kit=_kit(),
            refs=_chosen((1,)),
            base_index={"motion": 3, "edit": 2, "slide": 2}[route],
            numbered=route != "slide",
        )
