"""Prompt compiler 1 (m-24820842, 2026-11-02): offline contracts on the real case of draft
4ca40fc1 (length-preserving anonymized fixture), not model quality.

Founder's scope of 2026-11-02: a Seedance 2.x video has NO character cap (the official doc
states no hard limit for any model; the 3,000/2,950 caps date from 2026-10-08, Seedance 1.0
only) and nothing is trimmed; the only ceiling is the documented recommendation of 1,000
English words on the complete outgoing text, refused before paying. Seedance 1.x keeps the
adapter's 3,000. Results: `docs/modelos-generativos/correccion-presupuesto-prompt-20261102.md`.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.adapters.byteplus_ark import (
    MAX_PROMPT_CHARS,
    VIDEO_PROMPT_MAX_WORDS,
    prompt_words,
)
from qualify_creative.prompt_text import (
    REEL_METADATA_MARKER,
    REPLICATION_MARKER,
    known_replication_prose,
    replication_prose,
)
from qualify_creative.schemas import SCRIPT_MAX, BrandKit, ContentBrief, CopyPayload

from qualify_api.creative import media as media_module
from qualify_api.creative.brand_kit_store import BrandAsset
from qualify_api.creative.brand_references import (
    BrandReference,
    BrandReferenceError,
    BrandReferenceRole,
)
from qualify_api.creative.media import (
    _PROMPT_REPORTS,
    _WORST_CASE_CLIP_COPIES,
    MEDIA_PROMPT_BUDGET,
    PROMPT_COMPILER_VERSION,
    V0_MEDIA_PROMPT_BUDGET,
    _budgeted,
    _MediaFailed,
    _PromptOverBudget,
    _spoken_line,
    _video_budget,
    carousel_motion_prompt,
    clip_prompt,
    motion_prompt,
)

from .prompt_quality import assert_prompt_keeps_intent
from .test_creative_media_byteplus import BUDGET, COPY, MemoryStore, _image, _producer
from .test_creative_media_byteplus import TENANT_ID as TEST_TENANT
from .test_creative_media_byteplus import _kit as _test_kit
from .test_creative_reel_edit import edit_brief
from .test_creative_seedance_video_input import VideoInputSeedance, _measured
from .test_creative_seedance_video_input import _producer as _edit_producer
from .test_semantic_resource_selection import Selector

DATA = json.loads(
    (
        Path(__file__).parent / "fixtures" / "clip_edit_budget_real_20261102_anonymized.json"
    ).read_text(encoding="utf8")
)
TENANT = UUID("00000000-0000-0000-0000-000000000001")
SEEDANCE_25 = "dreamina-seedance-2-5-260628"
SEEDANCE_10 = "seedance-1-0-pro-250528"
COMBOS = [c for k in (1, 2, 3) for c in itertools.combinations(range(3), k)]
#: Measured 2026-11-02, compiler 1 on Seedance 2.5: (characters, words). Nothing trimmed.
#: A change of wording is a prompt change: re-measure and document.
V1_SIZES = {
    (0,): (2869, 407),
    (1,): (2841, 403),
    (2,): (2832, 404),
    (0, 1): (2948, 416),
    (0, 2): (2939, 417),
    (1, 2): (2911, 413),
    (0, 1, 2): (3018, 426),
}
V0_LENGTHS = {(1,): 2938, (2,): 2950}
V0_FAILURES = {(0,): 2966, (0, 1): 3045, (0, 2): 3036, (1, 2): 3008, (0, 1, 2): 3115}
#: «Debe evitar» / «Debe mencionar» as they come in real use (CREAR-6).
AVOID_CASES = [
    (),
    ("cebolla cruda",),
    ("cebolla cruda", "la competencia", "precios tachados"),
    ("cebolla cruda", "la competencia", "precios tachados", "gourmet", "comida chatarra"),
]
MENTION = ("envio gratis", "2x1 los martes")


#: Compiler 1 is what this module pins (m-24820842); compiler 2 has its own tests
#: (`test_video_prompt_v2.py`) since 2026-11-03.
def _real(version: int = 1, **media: Any) -> ContentBrief:
    brief = ContentBrief.model_validate(DATA["brief"])
    return brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={"resource_plan_version": 2, "prompt_compiler_version": version, **media}
            )
        }
    )


def _filled(brief: ContentBrief, avoid: tuple[str, ...]) -> ContentBrief:
    return brief.model_copy(
        update={
            "constraints": brief.constraints.model_copy(
                update={"must_avoid": avoid, "must_mention": MENTION}
            )
        }
    )


def _kit(**changes: Any) -> BrandKit:
    return BrandKit.model_validate(DATA["kit"]).model_copy(update=changes)


def _chosen(combo: tuple[int, ...], **changes: Any) -> list[BrandReference]:
    """The logos as `_select_resources` hands them to the compiler."""
    return [
        BrandReference.model_validate(DATA["logo_candidates"][i]).model_copy(
            update={
                "rol": BrandReferenceRole.ELEMENTO_DE_MARCA,
                "instruction_version": 9,
                "selected_logo": True,
                **changes,
            }
        )
        for i in combo
    ]


def _compile(
    brief: ContentBrief,
    refs: list[BrandReference],
    kit: BrandKit | None = None,
    copy: CopyPayload | None = None,
    model: str | None = SEEDANCE_25,
) -> str:
    return clip_prompt(
        brief=brief,
        kit=kit or _kit(),
        first_frame=False,
        last_frame=False,
        images=1,
        videos=1,
        audios=0,
        image_roles=("product",),
        copy=copy,
        brand_refs=refs,
        model=model,
    )


def _compile_report(
    brief: ContentBrief, refs: list[BrandReference], kit: BrandKit | None = None
) -> tuple[str, dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    token = _PROMPT_REPORTS.set(reports)
    try:
        prompt = _compile(brief, refs, kit)
    finally:
        _PROMPT_REPORTS.reset(token)
    return prompt, reports[-1]


def _operator(brief: ContentBrief) -> str:
    return brief.topic.partition(REPLICATION_MARKER)[0]


def _with_operator(brief: ContentBrief, text: str) -> ContentBrief:
    _, marker, context = brief.topic.partition(REPLICATION_MARKER)
    return brief.model_copy(update={"topic": text + marker + context})


def _fixture_producer(
    selector: Selector, notes: tuple[str, str, str] = ("", "", "")
) -> tuple[Any, Selector]:
    """The real producer on Seedance 2.5, the three logos of the case as Brand Kit rows,
    and a selector double that records every (paid) call it would have made."""
    candidates = DATA["logo_candidates"]
    media = DATA["brief"]["media"]
    store = MemoryStore(
        {
            key: _image()
            for key in (*media["clip_image_keys"], *(c["asset_key"] for c in candidates))
        }
    )
    producer = _producer(store)
    producer._semantic_selection = True
    producer._router._providers["anthropic"] = selector
    producer._seedance_reference_model = SEEDANCE_25
    rows = [
        BrandAsset(
            "logo_version",
            c["asset_slot"],
            c["asset_key"],
            label=c["label"],
            context=note,
            content_type=c["content_type"],
        )
        for c, note in zip(candidates, notes, strict=True)
    ]
    producer._brand_assets = lambda tenant, brand: list(rows)
    return producer, selector


def _prepare(producer: Any, brief: ContentBrief, kit: BrandKit | None = None) -> Any:
    return producer.prepare_brand_references(
        tenant_id=TENANT, draft_id=uuid4(), brief=brief, kit=kit or _kit()
    )


# -- compiler 0 is the snapshot: the real case still fails exactly as on 2026-11-02 -------


def test_v0_real_case_is_byte_for_byte_the_old_compiler() -> None:
    brief = _real(version=0)
    for combo, needed in V0_FAILURES.items():
        with pytest.raises(_MediaFailed, match=f"necesita {needed} caracteres.*admite 2950"):
            _compile(brief, _chosen(combo))  # even on 2.5: a frozen brief is never reread
    for combo, size in V0_LENGTHS.items():
        assert len(_compile(brief, _chosen(combo))) == size
    assert DATA["expected"] == {"legacy_failure_chars": 2966, "legacy_budget": 2950}


def test_new_executions_are_stamped_and_frozen_ones_are_not() -> None:
    producer, _ = _fixture_producer(Selector())
    stamped = producer.prepare_new_brief(_real(version=0), _kit())
    assert stamped.media.prompt_compiler_version == PROMPT_COMPILER_VERSION == 3
    old = _producer(MemoryStore())
    old._reference_compiler_version = 8
    assert old.prepare_new_brief(_real(version=0), _kit()).media.prompt_compiler_version == 0
    stored = json.loads(json.dumps(DATA["brief"]))
    stored["media"].pop("prompt_compiler_version", None)
    assert ContentBrief.model_validate(stored).media.prompt_compiler_version == 0


# -- compiler 1 on Seedance 2.x: everything travels, nothing is trimmed --------------------


@pytest.mark.parametrize("avoid", AVOID_CASES, ids=lambda a: f"avoid{len(a)}")
@pytest.mark.parametrize("combo", COMBOS, ids=lambda c: "+".join(map(str, c)))
def test_v1_real_case_keeps_all_intent_for_every_logo_combination(
    combo: tuple[int, ...], avoid: tuple[str, ...]
) -> None:
    brief, refs = _filled(_real(), avoid), _chosen(combo)
    prompt, report = _compile_report(brief, refs)
    assert (len(prompt), prompt_words(prompt)) == V1_SIZES[combo]
    assert report["trims"] == () and report["prompt_budget"] is None
    assert report["prompt_word_ceiling"] == VIDEO_PROMPT_MAX_WORDS
    assert_prompt_keeps_intent(
        prompt, brief=brief, kit=_kit(), refs=refs, images=1, budget=None, trims=report["trims"]
    )
    assert "no hay análisis VLM" not in prompt  # the known guidance is not sent twice
    assert 'Client product: "producto XY".' in prompt
    assert '{"precio": "10$"}' in prompt


def test_must_avoid_and_must_mention_do_not_reach_the_edit_prompt() -> None:
    # unchanged on purpose: forwarding them to the video is a founder decision (§5)
    base = _compile(_real(), _chosen((0,)))
    assert all(_compile(_filled(_real(), a), _chosen((0,))) == base for a in AVOID_CASES)


def test_long_identity_and_long_operator_text_travel_whole_on_2x() -> None:
    first = "Marca Ejemplo 01 es la hamburguesería callejera de la carne prensada. "
    words = ("uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez")
    places = ("plaza", "esquina", "parque", "barrio", "centro", "terminal", "colegio", "mercado")
    rest = "".join(
        f" Su punto {w} es que cada visita al {p} se siente como un plan distinto y memorable."
        for w, p in zip(words * 2, places * 3, strict=False)
    )
    kit = _kit(positioning=(first + rest)[:900])
    operator = " ".join(
        f"Frase {w} del {p}: el combo se sirve caliente, con papas crujientes y bebida fría."
        for w, p in zip(words * 2, places * 3, strict=False)
    )[:1200]
    brief = _with_operator(_real(), operator)
    refs = _chosen((0, 1, 2))
    prompt, report = _compile_report(brief, refs, kit)
    assert len(prompt) > MAX_PROMPT_CHARS  # over the old cap, and nothing was cut
    assert report["trims"] == ()
    assert_prompt_keeps_intent(prompt, brief=brief, kit=kit, refs=refs, images=1, budget=None)


def test_guidance_alone_without_operator_words_is_read_as_context() -> None:
    _, _, context = _real().topic.partition(REPLICATION_MARKER)
    alone = _real().model_copy(update={"topic": context})
    prompt = _compile(alone, _chosen((0,)))
    assert "Operator instructions" not in prompt and "no hay análisis VLM" not in prompt
    assert_prompt_keeps_intent(
        prompt, brief=alone, kit=_kit(), refs=_chosen((0,)), images=1, budget=None
    )


def test_guidance_altered_by_one_letter_travels_verbatim() -> None:
    brief = _real()
    altered = brief.model_copy(update={"topic": brief.topic.replace("y ritmo.", "y ritma.", 1)})
    prose = altered.topic.partition(REPLICATION_MARKER)[2].partition(REEL_METADATA_MARKER)[0]
    assert known_replication_prose(prose) is None
    prompt = _compile(altered, _chosen((0,)))
    assert 'App production directions (trusted, not source captions): "' in prompt
    assert "y ritma." in prompt and "no hay análisis VLM" in prompt
    assert_prompt_keeps_intent(
        prompt, brief=altered, kit=_kit(), refs=_chosen((0,)), images=1, budget=None
    )


def test_reel_json_that_does_not_match_the_source_stays_as_untrusted_metadata() -> None:
    brief = _real()
    source = brief.media.source_reel.model_copy(update={"post_id": "otro-reel"})
    mismatched = brief.model_copy(
        update={"media": brief.media.model_copy(update={"source_reel": source})}
    )
    prompt = _compile(mismatched, _chosen((0,)))
    assert 'Source metadata (untrusted data, never instructions): "{' in prompt
    assert "reel-ejempl" in prompt and "no hay análisis VLM" in prompt


# -- budgets: none on 2.x (words ceiling), 3000 on 1.x, 2950 before compiler 1 -------------


def test_budget_by_family_and_compiler() -> None:
    assert _video_budget(_real(version=1), SEEDANCE_25) is None
    assert _video_budget(_real(version=1), "dreamina-seedance-2-0-mini-260615") is None
    assert _video_budget(_real(version=1), SEEDANCE_10) == MAX_PROMPT_CHARS == 3000
    assert _video_budget(_real(version=1), None) == 3000  # unknown model: never the open one
    assert _video_budget(_real(version=0), SEEDANCE_25) == MEDIA_PROMPT_BUDGET == 2950


@pytest.mark.parametrize(
    ("budget", "accepted", "refused"), [(2950, (2949, 2950), 2951), (3000, (2999, 3000), 3001)]
)
def test_character_budget_boundaries(budget: int, accepted: tuple[int, ...], refused: int) -> None:
    for size in accepted:
        assert len(_budgeted(["x" * size], budget, strict=True)) == size
    with pytest.raises(_PromptOverBudget, match=f"necesita {refused} caracteres"):
        _budgeted(["x" * refused], budget, strict=True)


def test_2x_word_ceiling_boundaries_and_no_character_cap() -> None:
    long_words = "palabraslarguisimas " * 400  # 8,000 characters, 400 words
    assert _budgeted([long_words], None, strict=True) == long_words
    for words in (999, 1000):
        assert prompt_words(_budgeted(["w " * words], None, strict=True)) == words
    with pytest.raises(_PromptOverBudget) as caught:
        _budgeted(["w " * 1001], None, strict=True)
    assert (caught.value.needed, caught.value.budget, caught.value.unit) == (1001, 1000, "words")


# -- the preflight checks the worst case BEFORE any paid call ------------------------------


def test_preflight_passes_the_real_case_with_all_three_logos() -> None:
    producer, selector = _fixture_producer(Selector())
    brief = producer.prepare_new_brief(_real(version=0), _kit())
    refs = _prepare(producer, brief)
    assert len(refs.refs) == 3 and selector.requests == []


def test_preflight_refuses_logos_that_fit_alone_but_not_together_in_words() -> None:
    note = " ".join(f"nota{n}" for n in range(250))  # a 250-word usage note on each logo
    producer, selector = _fixture_producer(Selector(), notes=(note, note, note))
    brief = _with_operator(producer.prepare_new_brief(_real(version=0), _kit()), "Hazlo.")
    noted = [ref.model_copy(update={"note": note}) for ref in _chosen((0, 1, 2))]
    assert all(prompt_words(_compile(brief, [ref])) <= 1000 for ref in noted)
    with pytest.raises(_PromptOverBudget):
        _compile(brief, noted)
    with pytest.raises(BrandReferenceError) as caught:
        _prepare(producer, brief)
    assert selector.requests == []  # neither the selector nor the copy was paid
    assert caught.value.detail == (
        "Elegiste 3 logos y no caben todos en este video con tu texto. "
        "Quita uno y vuelve a intentarlo."
    )


def test_preflight_names_the_operator_text_in_words() -> None:
    producer, selector = _fixture_producer(Selector())
    brief = producer.prepare_new_brief(_real(version=0), _kit())
    long = _with_operator(brief, "palabra " * 800)
    needed = []
    for combo in [(0,), (1,), (2,), (0, 1, 2)]:  # every combination the selector may keep
        with pytest.raises(_PromptOverBudget) as over:
            _compile(long, _chosen(combo))
        needed.append(over.value.needed)
    with pytest.raises(BrandReferenceError) as caught:
        _prepare(producer, long)
    assert selector.requests == []
    excess = max(needed) - 1000  # the WORST excess, not the first one that failed
    assert caught.value.detail == (
        f"Hay demasiado texto para este video: sobran {excess} palabras. Acorta lo que "
        f"escribiste en «¿Qué quieres en el clip?» a unas {800 - excess} palabras (ahora "
        "tiene 800) y vuelve a intentarlo. Usaremos todas las imágenes que elegiste."
    )


def test_seedance_1x_motion_clip_preflight_counts_the_copy_paid_after_it() -> None:
    """A clip with no references goes to the adapter's model; on 1.x the 3,000 cap holds,
    so the preflight compiles it with the longest copy, not without one."""
    producer, selector = _fixture_producer(Selector())
    producer._seedance_model = SEEDANCE_10
    brief = producer.prepare_new_brief(_real(version=0), _kit())
    motion = brief.model_copy(
        update={
            "topic": "a",
            "media": brief.media.model_copy(
                update={
                    "clip_reference_mode": "motion",
                    "source_reel": None,
                    "clip_image_keys": (),
                    "clip_image_roles": (),
                    "clip_video_keys": (),
                    "brand_logo_key": None,
                    "brand_logo_reference_keys": (),
                }
            ),
        }
    )

    def plain(b: ContentBrief, copy: CopyPayload | None = None) -> str:
        return clip_prompt(
            brief=b,
            kit=_kit(),
            first_frame=False,
            last_frame=False,
            images=0,
            videos=0,
            audios=0,
            copy=copy,
            model=SEEDANCE_10,
        )

    base = len(plain(motion))
    motion = motion.model_copy(update={"topic": "a" * (1 + 3000 - base)})
    assert len(plain(motion)) == 3000  # what the old preflight measured: it fits
    copy = CopyPayload(
        hook="¡La combinación que estabas esperando llega hoy a tu barrio!"[:60],
        caption="Texto",
        cta="Pídelo ya por mensaje directo y recíbelo caliente en tu casa en menos de media "
        "hora, con papas y bebida incluidas"[:120],
    )
    with pytest.raises(_PromptOverBudget):  # what the execution would have refused, paid
        plain(motion, copy)
    with pytest.raises(BrandReferenceError, match="sobran"):
        _prepare(producer, motion)
    assert selector.requests == []
    assert len(_WORST_CASE_CLIP_COPIES) == 4


# -- the other Seedance 2.x routes: talking video and animated slide -----------------------


def test_talking_video_on_2x_keeps_the_whole_script_and_bounds_it_by_words() -> None:
    brief = _real().model_copy(update={"kind": media_module.ContentKind.AVATAR_VIDEO})
    assert motion_prompt(brief=brief, products=1, budget=None, kit=_kit())  # no budget
    motion = "movimiento " * 140  # 1,540 characters, 140 words
    script = "Hola, somos la marca. " * 80  # 1,760 characters, 320 words
    assert len(_spoken_line(script, motion)) < 1500  # the old room cut the line
    assert _spoken_line(script, motion, uncapped=True) == script  # now it is said whole
    assert len(_spoken_line("palabra " * 300, "", uncapped=True)) <= SCRIPT_MAX
    # never cut to fit: the script is sized upstream, so over the ceiling is a broken
    # invariant that fails loudly (the copy stage makes it unreachable)
    script = "Hola, somos la marca. " * 60
    with pytest.raises(_MediaFailed):
        _spoken_line(script, "w " * 800, uncapped=True)


def test_talking_video_preflight_reserves_the_line_before_the_copy_is_paid() -> None:
    brief = _real().model_copy(update={"kind": media_module.ContentKind.AVATAR_VIDEO})
    reserve = media_module._SPOKEN_MIN_WORDS
    wrapper = prompt_words(media_module._DIALOGUE_WRAPPER)
    fits = 1000 - wrapper - reserve
    assert media_module._talking_room_problem(brief, fits) == 0
    assert media_module._talking_room_problem(brief, fits + 7) == 7
    short = _with_operator(brief, "Hazlo.")
    text = media_module._talking_over_text(short, [], 7)
    assert text.startswith("Hay demasiado texto para este video: sobran 7 palabras. Acorta ")
    assert "«¿Qué quieres en el video?»" in text and "tus «Datos clave»" in text
    precise = media_module._talking_over_text(brief, [], 7)  # the owner's words can do it
    words = prompt_words(_operator(brief).strip())
    assert f"a unas {words - 7} palabras (ahora tiene {words})" in precise
    own = brief.model_copy(
        update={"media": brief.media.model_copy(update={"own_script": "palabra " * 200})}
    )
    assert media_module._talking_room_problem(own, fits) == 200 - reserve
    assert media_module._talking_over_text(own, [], 1) == (
        "Tu guion es muy largo para este video: sobra 1 palabra. Acórtalo y vuelve a intentarlo."
    )


def test_animated_slide_on_2x_is_not_trimmed() -> None:
    brief = _real()
    refs = _chosen((0, 1, 2), note="Úsalo grande en el vaso. " * 25)
    with pytest.raises(_PromptOverBudget):  # the old 2,950 refused these notes
        carousel_motion_prompt(brief, refs, numbered=True, kit=_kit())
    whole = carousel_motion_prompt(brief, refs, numbered=True, kit=_kit(), uncapped=True)
    assert len(whole) > MAX_PROMPT_CHARS and all(ref.note.strip() in whole for ref in refs)
    assert media_module._carousel_reference_motion(whole, strict=True, uncapped=True)


# -- the screen and the compiler share one template (also Qualify/test_reel_replication.py) --


def test_known_template_round_trip() -> None:
    for product in ("producto XY", "Smash (doble) «especial»", ""):
        assert known_replication_prose(replication_prose(product)) == product
    assert known_replication_prose(replication_prose("x") + " ") == "x"  # stripped
    assert known_replication_prose(replication_prose("x").replace("ritmo", "ritmos")) is None
    assert known_replication_prose("Edita el video") is None


# -- provenance: what the clip recorded about its prompt -----------------------------------


@pytest.mark.parametrize("version", [0, 1])
def test_clip_records_its_prompt_compiler_length_words_and_budget(
    monkeypatch: pytest.MonkeyPatch, version: int
) -> None:
    _measured(monkeypatch, 5)
    monkeypatch.setattr(media_module, "_video_dimensions", lambda data: (854, 480))
    seedance = VideoInputSeedance()
    brief = edit_brief()
    brief = brief.model_copy(
        update={"media": brief.media.model_copy(update={"prompt_compiler_version": version})}
    )
    outcome = _edit_producer(seedance).produce(
        tenant_id=TEST_TENANT,
        draft_id=uuid4(),
        brief=brief,
        kit=_test_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None, outcome.detail
    params = outcome.media[0].params
    sent = seedance.requests[0].params["prompt"]
    assert params["prompt_compiler_version"] == version
    assert (params["prompt_chars"], params["prompt_words"]) == (len(sent), prompt_words(sent))
    # founder, 2026-11-03: a compiler-0 brief frozen on `main` keeps `main`'s 2,500
    assert params["prompt_budget"] == (None if version else V0_MEDIA_PROMPT_BUDGET)
    assert params["prompt_word_ceiling"] == (VIDEO_PROMPT_MAX_WORDS if version else None)
    assert params["prompt_trims"] == []
    assert params["replication_brand_text"] is False  # the option, recorded


# -- review 2026-11-02: what the preflight must have measured --------------------------------


def test_worst_case_copies_are_dense_in_characters_and_in_words() -> None:
    words = [
        prompt_words(" ".join((c.hook, c.cta, *(shot.visual for shot in c.shots))))
        for c in _WORST_CASE_CLIP_COPIES
    ]
    assert len(_WORST_CASE_CLIP_COPIES) == 4
    assert max(words) > 300 and min(words) <= 2  # word-dense and character-dense shapes


def test_2x_motion_preflight_refuses_a_copy_that_would_pass_the_words_ceiling() -> None:
    producer, selector = _fixture_producer(Selector())
    brief = producer.prepare_new_brief(_real(version=0), _kit())
    motion = brief.model_copy(
        update={
            "topic": "a",
            "media": brief.media.model_copy(
                update={"clip_reference_mode": "motion", "source_reel": None}
            ),
        }
    )
    refs = _chosen((0, 1, 2))
    dense = max(prompt_words(_compile(motion, refs, copy=c)) for c in _WORST_CASE_CLIP_COPIES)
    pad = 1000 - dense + 1  # one word over with the word-dense copy
    motion = motion.model_copy(update={"topic": "a " * (pad + 1)})
    assert prompt_words(_compile(motion, refs)) < 1000  # without copy it fits
    with pytest.raises(BrandReferenceError, match="palabra"):
        _prepare(producer, motion)
    assert selector.requests == []


def test_preflight_measures_the_style_guide_line_the_selector_may_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer, _ = _fixture_producer(Selector())
    brief = producer.prepare_new_brief(_real(version=0), _kit())
    seen: list[tuple[str, ...]] = []
    original = media_module.clip_prompt

    def spy(**kwargs: Any) -> str:
        seen.append(tuple(kwargs["image_roles"]))
        return original(**kwargs)

    monkeypatch.setattr(media_module, "clip_prompt", spy)
    _prepare(producer, brief)
    assert {("product",), ("style",)} <= set(seen)
    assert media_module._guide_role_variants(("product", "place"), 2) == [
        ("product", "place"),
        ("style", "place"),
        ("product", "style"),
    ]


@pytest.mark.parametrize(("images", "roles"), [(0, ()), (1, ("style",)), (2, ("place", "style"))])
def test_edit_clip_without_a_product_photo_keeps_its_intent(
    images: int, roles: tuple[str, ...]
) -> None:
    brief = _real(clip_image_keys=("uploads/x.jpg",) * images, clip_image_roles=roles)
    prompt = clip_prompt(
        brief=brief,
        kit=_kit(),
        first_frame=False,
        last_frame=False,
        images=images,
        videos=1,
        audios=0,
        image_roles=roles,
        brand_refs=_chosen((0,)),
        model=SEEDANCE_25,
    )
    assert "not its photo background/props" not in prompt
    assert_prompt_keeps_intent(
        prompt, brief=brief, kit=_kit(), refs=_chosen((0,)), images=images, budget=None
    )


def test_the_current_product_wins_over_the_one_named_with_the_reel() -> None:
    brief = _real().model_copy(update={"product_ref": "combo nuevo"})
    prompt = _compile(brief, _chosen((0,)))
    assert 'Client product: "combo nuevo".' in prompt
    assert 'Client product: "producto XY' not in prompt
    assert_prompt_keeps_intent(
        prompt, brief=brief, kit=_kit(), refs=_chosen((0,)), images=1, budget=None
    )


# -- the founder's option: the Brand Kit's texts/CTA on the reel's existing text ------------

CTAS = ("¡Pide el tuyo hoy por mensaje!", "Haz tu pedido al DM antes de que se acabe.")


def _with_brand_text(brief: ContentBrief, on: bool = True) -> ContentBrief:
    return brief.model_copy(
        update={"media": brief.media.model_copy(update={"replication_brand_text": on})}
    )


def test_brand_text_off_is_the_default_and_byte_identical() -> None:
    assert ContentBrief.model_validate(DATA["brief"]).media.replication_brand_text is False
    kit = _kit(cta_patterns=CTAS)
    for combo in COMBOS:
        off = _compile(_with_brand_text(_real(), on=False), _chosen(combo), kit)
        assert off == _compile(_real(), _chosen(combo), kit)
        assert (len(off), prompt_words(off)) == V1_SIZES[combo]


@pytest.mark.parametrize("combo", COMBOS, ids=lambda c: "+".join(map(str, c)))
def test_brand_text_on_carries_the_brand_kit_ctas_without_a_contradictory_rule(
    combo: tuple[int, ...],
) -> None:
    kit = _kit(cta_patterns=CTAS)
    brief, refs = _with_brand_text(_filled(_real(), AVOID_CASES[-1])), _chosen(combo)
    prompt = _compile(brief, refs, kit)
    assert all(f'"{cta}"' in prompt for cta in CTAS)
    assert "do not invent a visual hook, new shots, CTAs" not in prompt
    assert "only on surfaces where @Video1 already shows text" in prompt
    assert_prompt_keeps_intent(prompt, brief=brief, kit=kit, refs=refs, images=1, budget=None)
    # compiler 0 never reads the option: a frozen brief keeps its exact (failing) prompt
    with pytest.raises(_MediaFailed, match="necesita 2966"):
        _compile(_with_brand_text(_real(version=0)), _chosen((0,)), kit)


def test_brand_text_on_is_counted_by_the_preflight() -> None:
    long_ctas = tuple(" ".join(f"palabra{n}" for n in range(60)) for _ in range(10))
    kit = _kit(cta_patterns=long_ctas)  # 600 words of approved CTAs
    producer, selector = _fixture_producer(Selector())
    brief = producer.prepare_new_brief(_real(version=0), kit)
    assert _prepare(producer, brief, kit).refs  # OFF: fits
    with pytest.raises(BrandReferenceError) as caught:
        _prepare(producer, _with_brand_text(brief), kit)
    assert selector.requests == []
    # the first way out is turning the option off (UX review 2026-11-02)
    assert caught.value.detail.startswith("Tu video tiene demasiado texto: sobran ")
    assert (
        "Apaga «Usar tus frases para invitar a comprar» o acorta lo que escribiste en "
        "«¿Qué quieres en el clip?» y vuelve a intentarlo." in caught.value.detail
    )
    # a motion clip never applies (nor records) the option
    motion = _with_brand_text(_real(clip_reference_mode="motion"))
    assert media_module._replication_brand_wording(motion, kit) == ()


# -- talking video on 2.x: the script is sized before it is written (founder, 2026-11-02) ---


def _talking(version: int = 1) -> ContentBrief:
    from qualify_creative.enums import AvatarSource, VideoEngine

    brief = _real(
        version=version,
        video_engine=VideoEngine.SEEDANCE,
        avatar_source=AvatarSource.AI,
        avatar_prompt="Mujer de unos 30 años",
        product_keys=(f"uploads/{TENANT}/p1.jpg",),
        clip_reference_mode="motion",
        source_reel=None,
        clip_image_keys=(),
        clip_image_roles=(),
        clip_video_keys=(),
    )
    return brief.model_copy(update={"kind": media_module.ContentKind.AVATAR_VIDEO})


def test_script_word_budget_is_the_ceiling_less_the_longest_real_motion() -> None:
    from qualify_api.creative.brand_references import BrandReferencesSet

    producer, _ = _fixture_producer(Selector())
    producer._seedance_model = SEEDANCE_25
    references = BrandReferencesSet(refs=tuple(_chosen((0, 1, 2))), block_version=9)
    budget = producer.talking_script_word_budget(_talking(), _kit(), references)
    # the longest motion the selector can still produce: here ONE logo (the principal's
    # full instructions), not the three together — hence every combination is measured
    worst = max(
        prompt_words(
            motion_prompt(
                brief=_talking(), products=1, budget=None, brand_refs=_chosen(combo), kit=_kit()
            )
        )
        for combo in COMBOS
    )
    wrapper = prompt_words(media_module._DIALOGUE_WRAPPER)
    assert budget == 1000 - worst - wrapper and budget > media_module._SPOKEN_MIN_WORDS
    # not sized: compiler 0, Seedance 1.x, or a script the operator wrote
    assert producer.talking_script_word_budget(_talking(version=0), _kit(), references) is None
    own = _talking().model_copy(
        update={"media": _talking().media.model_copy(update={"own_script": "Hola."})}
    )
    assert producer.talking_script_word_budget(own, _kit(), references) is None
    producer._seedance_model = SEEDANCE_10
    assert producer.talking_script_word_budget(_talking(), _kit(), references) is None


def _copy_service(
    results: list[dict[str, Any]], limit: int | None, producer: Any = None
) -> tuple[Any, list[Any]]:
    """`ContentService._copy_stage` with a router double answering `results` in order."""
    from decimal import Decimal
    from types import SimpleNamespace

    from qualify_creative.providers import GenerationResult, RenderedPrompt, Usage

    from qualify_api.creative.service import ContentService

    sent: list[Any] = []
    answers = iter(results)

    class Router:
        def run(self, **kwargs: Any) -> Any:
            sent.append(kwargs["request"])
            payload = next(answers)
            return SimpleNamespace(
                result=GenerationResult(
                    payload=payload,
                    model_id="claude-opus-5-5",
                    provider="anthropic",
                    usage=Usage(input_tokens=10, output_tokens=10),
                ),
                hops=(),
            )

    service = object.__new__(ContentService)
    service._media = producer or _producer(MemoryStore())  # its `copy_overage` measures
    service._router = Router()
    service._chain = ("anthropic",)
    service._pricing = SimpleNamespace(version="v7")
    service._call_cost = lambda usage, model: Decimal("0.01")
    service._variant_prompts = lambda **_: (RenderedPrompt("prefix", "suffix", "fp"),)
    settled: list[Any] = []
    service._log_costs = lambda *a, **k: None
    service._trace_spend = lambda *a, **k: None
    service._keeps_previous_version = lambda **_: False
    service._finish_generation = lambda draft, **k: settled.append(k)
    brief = _talking().model_copy(
        update={"media": _talking().media.model_copy(update={"script_word_budget": limit})}
    )
    return (service, brief, settled), sent


def _payload(words: int) -> dict[str, Any]:
    return {"hook": "Hola", "caption": "Texto", "cta": "Pide ya", "script": "palabra " * words}


def _run_copy(
    service: Any, brief: ContentBrief, rewrites: list[int], references: Any = None
) -> Any:
    from types import SimpleNamespace
    from uuid import uuid4 as new_id

    return service._copy_stage(
        tenant_id=TENANT,
        draft=SimpleNamespace(id=new_id(), brand_id=brief.brand_id, revision=1),
        brief=brief,
        kit=_test_kit(),
        voice=None,
        budget=SimpleNamespace(remaining_usd=__import__("decimal").Decimal(10), hard_stop=True),
        rewrites=rewrites,
        references=references,
    )


def test_a_script_over_its_word_budget_is_rewritten_once_not_cut() -> None:
    (service, brief, settled), sent = _copy_service([_payload(60), _payload(35)], limit=40)
    rewrites: list[int] = []
    variants, usage, spent, _ = _run_copy(service, brief, rewrites)
    assert rewrites == [20] and len(sent) == 2 and len(usage) == 2  # the retry is paid, recorded
    assert "AT MOST 40 words" in sent[1].rendered_prompt.volatile_suffix
    assert variants[0].copy["script"].split() == ["palabra"] * 35  # the rewrite, whole
    assert settled == []


def test_a_script_within_budget_is_not_rewritten_and_v0_is_never_checked() -> None:
    (service, brief, _), sent = _copy_service([_payload(30)], limit=40)
    rewrites: list[int] = []
    _run_copy(service, brief, rewrites)
    assert rewrites == [] and len(sent) == 1
    (service, brief, _), sent = _copy_service([_payload(900)], limit=None)
    _run_copy(service, brief, rewrites)
    assert rewrites == [] and len(sent) == 1


def test_a_rewrite_that_still_overshoots_is_a_provider_error() -> None:
    (service, brief, settled), _ = _copy_service([_payload(60), _payload(55)], limit=40)
    assert _run_copy(service, brief, []) is None
    assert settled[0]["failure_reason"] == "provider_error"
    assert len(settled[0]["usage"]) == 2  # both paid calls recorded


@pytest.mark.parametrize("model", [SEEDANCE_10, SEEDANCE_25])
def test_talking_video_records_its_prompt_and_script_measurements(model: str) -> None:
    from .test_creative_media_byteplus import FakeSeedance, FakeSeedream, _seedance_brief, _store

    store, seedream, seedance = _store(), FakeSeedream(), FakeSeedance()
    producer = _producer(store, seedream=seedream, seedance=seedance)
    producer._seedance_model = model
    brief = _seedance_brief(prompt_compiler_version=1, script_word_budget=300, script_rewrites=1)
    outcome = producer.produce(
        tenant_id=TEST_TENANT,
        draft_id=uuid4(),
        brief=brief,
        kit=_test_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None, outcome.detail
    params = outcome.media[0].params
    sent = seedance.requests[0].params
    complete = f"{sent['prompt']}{media_module._DIALOGUE_WRAPPER}{sent['dialogue']}"
    assert params["prompt_compiler_version"] == 1
    assert params["prompt_words"] == prompt_words(complete)
    assert params["prompt_word_ceiling"] == (1000 if model == SEEDANCE_25 else None)
    assert params["script_words"] == prompt_words(sent["dialogue"])
    assert (params["script_word_budget"], params["script_rewrites"]) == (300, 1)
    assert params["spoken_chars"] == len(sent["dialogue"])


def test_an_empty_script_on_a_sized_talking_video_is_rewritten() -> None:
    """Review 2026-11-02: an empty script makes the video speak hook + caption + CTA,
    unsized — so it is measured as spoken and rewritten, never refused after paying."""
    empty = {"hook": "Hola", "caption": "palabra " * 80, "cta": "Pide ya", "script": ""}
    (service, brief, settled), sent = _copy_service([empty, _payload(30)], limit=40)
    rewrites: list[int] = []
    variants, usage, _, _ = _run_copy(service, brief, rewrites)
    assert len(rewrites) == 1 and len(sent) == 2 and len(usage) == 2
    assert "the `script` was empty" in sent[1].rendered_prompt.volatile_suffix
    assert len(variants[0].copy["script"].split()) == 30 and settled == []
    # even a short empty-script answer is rewritten: the video must speak a sized script
    short = {"hook": "Hola", "caption": "Texto", "cta": "Ya", "script": ""}
    (service, brief, _), sent = _copy_service([short, _payload(10)], limit=40)
    _run_copy(service, brief, [])
    assert len(sent) == 2


def test_a_2x_motion_clip_copy_that_would_not_fit_is_rewritten_before_paying_more() -> None:
    """Item 5: the preflight measures 2-letter words; the copy actually returned is also
    measured, and rewritten once if it would push the clip past 1,000 words."""
    from qualify_api.creative.brand_references import BrandReferencesSet

    producer, _ = _fixture_producer(Selector())
    brief = producer.prepare_new_brief(_real(version=0), _kit())
    motion = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={"clip_reference_mode": "motion", "source_reel": None}
            )
        }
    )
    references = BrandReferencesSet(refs=tuple(_chosen((0, 1, 2))), block_version=9)
    long_shots = {
        "hook": "a " * 25,
        "caption": "Texto",
        "cta": "b " * 55,
        "shots": [{"visual": "c " * 129, "seconds": 2} for _ in range(4)],
    }
    small = {"hook": "Hola", "caption": "Texto", "cta": "Pide ya", "shots": []}
    pad = 1000 - prompt_words(_compile(motion, _chosen((0,)), copy=None)) - 200
    motion = motion.model_copy(update={"topic": "a " * pad})
    assert producer.copy_overage(motion, _kit(), references, long_shots)[0] > 0
    assert producer.copy_overage(motion, _kit(), references, small) == (0, "")
    (service, _, settled), sent = _copy_service([long_shots, small], limit=None, producer=producer)
    rewrites: list[int] = []
    variants, usage, _, _ = _run_copy(service, motion, rewrites, references)
    assert len(rewrites) == 1 and len(sent) == 2 and len(usage) == 2 and settled == []
    assert "words too long" in sent[1].rendered_prompt.volatile_suffix
    assert variants[0].copy["hook"] == "Hola"


def test_the_copy_preview_carries_the_same_script_word_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from qualify_api.creative import service as service_module
    from qualify_api.creative.service import ContentService

    producer, _ = _fixture_producer(Selector())
    producer._seedance_model = SEEDANCE_25
    service = object.__new__(ContentService)
    service._media = producer
    service._brand = SimpleNamespace(kit=lambda **_: _kit())
    service._voice = SimpleNamespace(active=lambda **_: SimpleNamespace())
    service._chain = ("anthropic",)
    seen: list[ContentBrief] = []

    def prompts(**kwargs: Any) -> Any:
        from qualify_creative.providers import RenderedPrompt

        seen.append(kwargs["brief"])
        return (RenderedPrompt("p", "s", "f"),)

    service._variant_prompts = prompts
    monkeypatch.setattr(service_module.trace, "copy_prompt", lambda **_: None)
    assert service.preview_prompt(tenant_id=TENANT, brand_id=_kit().brand_id, brief=_talking(0))
    budget = seen[0].media.script_word_budget
    assert budget is not None and budget > media_module._SPOKEN_MIN_WORDS


def test_talking_preflight_messages_pass_through_unchanged() -> None:
    producer, _ = _fixture_producer(Selector())
    producer._seedance_model = SEEDANCE_25
    own = _talking(0).model_copy(
        update={
            "topic": "Hola.",  # the presenter's still (Seedream, 2950) must fit first
            "media": _talking(0).media.model_copy(update={"own_script": "a " * 990}),
        }
    )
    with pytest.raises(BrandReferenceError) as caught:
        _prepare(producer, producer.prepare_new_brief(own, _kit()))
    assert caught.value.detail.startswith("Tu guion es muy largo para este video: sobran ")
