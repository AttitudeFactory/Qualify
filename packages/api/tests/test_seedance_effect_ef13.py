"""EF-13 (m-25026589, ADR 50 D5): effects asked of Seedance as «an object in a zone of the
frame». Offline: the Seedance fakes of `test_creative_seedance_draft.py`; nothing paid.

Criteria covered here: the prompt carries the template and the provenance keeps
`effect_id`, version and `prompt_version`; no `seed` is sent and the returned one is kept;
an effect without a bench result over D5's bar — on the model it is asked of — is never
offered; the price guard runs before the call and the seconds are charged as today; the
line is budgeted with the prompt, so a piece it does not fit in is refused before the
copy. Plus the switch `QUALIFY_SEEDANCE_EFFECTS` (off = as on main)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.effects import (
    AI_EFFECT_COST_NOTE,
    DEFAULT_EFFECT_SUBJECT,
    EffectsLibrary,
    Measured,
    ai_effect_cost_text,
    effect_subject,
    load_effects,
    measured_on_model,
    parse_library,
    preview_file,
    seedance_effect_line,
)
from qualify_creative.enums import FailureReason
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.router import BudgetContext, CreativeRouter
from qualify_creative.schemas import EffectUse, PartRef

from qualify_api.creative import media as media_module
from qualify_api.creative.brand_references import BrandReferenceError
from qualify_api.creative.media import (
    AI_EFFECT_DOES_NOT_FIT_TEXT,
    AI_EFFECT_MODEL_TEXT,
    MediaProducer,
    ai_effect_does_not_fit_text,
    ai_effect_model_text,
)
from qualify_api.creative.video_pipeline import seedance_effect as effect_module
from qualify_api.creative.video_pipeline.recipe import (
    RecipeRefused,
    refuse_unbuilt_recipe,
    unbuilt_recipe_problems,
)
from qualify_api.creative.video_pipeline.seedance_effect import (
    SEEDANCE_EFFECT_PARAMS_KEY,
    SEEDANCE_EFFECTS_SWITCH,
    is_built_seedance_effect,
    seedance_effect_of,
    seedance_effects_on,
)

from .test_creative_media_byteplus import (
    COPY,
    SEEDANCE_MODEL,
    TENANT_ID,
    FakeSeedance,
    KeysByProvider,
    _kit,
)
from .test_creative_seedance_draft import (
    BUDGET,
    DRAFT_MODEL,
    DraftSeedance,
    RecordingFitter,
    _clip,
    _finalize,
    _producer,
    _record,
    _store,
)

DATA = Path(__file__).parents[2] / "creative" / "src" / "qualify_creative" / "effects_data"
LIBRARIES = sorted(p.stem for p in DATA.glob("v*.json"))


def _use(effect_id: str = "humo_denso", **params: object) -> EffectUse:
    return EffectUse(effect_id=effect_id, version=1, params=params)


def _bench_json(successes: int = 4, n: int = 4, model: str = DRAFT_MODEL) -> dict[str, Any]:
    return {
        "successes": successes,
        "n": n,
        "wilson_low": 0.1,
        "wilson_high": 0.9,
        "measured_on": "2026-11-24",
        "model": model,
    }


def _measured_library(
    root: Path, *, successes: int = 4, n: int = 4, model: str = DRAFT_MODEL
) -> EffectsLibrary:
    """The v5 library with `humo_denso` and `brasas` OFFERED, measured on `model`, each
    with an example file under `root`: a library as EF-12 would leave it (v6)."""
    raw = json.loads((DATA / "v5.json").read_text(encoding="utf-8"))
    for entry in raw["entries"]:
        if entry["id"] in ("humo_denso", "brasas"):
            preview = f"effects/{entry['id']}/v1/ejemplo.mp4"
            file = preview_file(preview, root)
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"mp4")
            entry.update(
                offered=True,
                preview_asset=preview,
                measured=_bench_json(successes, n, model),
            )
    for entry in raw["entries"]:  # the layers' loops, as packaged
        if entry.get("preview_asset"):
            file = preview_file(entry["preview_asset"], root)
            file.parent.mkdir(parents=True, exist_ok=True)
            if not file.exists():
                file.write_bytes(b"webm")
    return parse_library(raw, assets_root=root)


@pytest.fixture
def switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SEEDANCE_EFFECTS_SWITCH, "on")


def _serve(monkeypatch: pytest.MonkeyPatch, library: EffectsLibrary) -> None:
    """The producer and the gate read `library` instead of the packaged one."""
    monkeypatch.setattr(effect_module, "load_effects", lambda *_: library)


@pytest.fixture
def measured(switch_on: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> EffectsLibrary:
    """Switch on, `humo_denso`/`brasas` measured on the 2.5 draft model."""
    library = _measured_library(tmp_path)
    _serve(monkeypatch, library)
    return library


# -- D5: the bench's bar, its model and what a screen may offer --------------------------------


def _bench(successes: int, n: int) -> Measured:
    return Measured.model_validate(_bench_json(successes, n))


@pytest.mark.parametrize(
    ("successes", "n", "passes"),
    [(3, 4, True), (4, 6, True), (4, 4, True), (2, 3, False), (2, 4, False), (5, 8, False)],
)
def test_d5_bar_is_two_of_three_with_at_least_four_tries(
    successes: int, n: int, passes: bool
) -> None:
    assert _bench(successes, n).passes is passes


def test_a_measurement_names_the_model_it_ran_on() -> None:
    bench = _bench_json()
    del bench["model"]
    with pytest.raises(ValidationError, match="model"):
        Measured.model_validate(bench)


def test_an_effect_measured_under_the_bar_cannot_be_offered(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="2/3"):
        _measured_library(tmp_path, successes=2, n=4)
    with pytest.raises(ValidationError, match="2/3"):
        _measured_library(tmp_path, successes=3, n=3)  # n < 4
    library = _measured_library(tmp_path, successes=3, n=4)
    assert {"humo_denso", "brasas"} <= {e.id for e in library.offered()}


def test_an_effect_is_offered_only_for_the_model_it_was_measured_on(tmp_path: Path) -> None:
    library = _measured_library(tmp_path)
    ai = {e.id for e in library.offered(model=DRAFT_MODEL) if e.stage == "seedance_prompt"}
    assert ai == {"humo_denso", "brasas"}
    other = library.offered(model=SEEDANCE_MODEL)
    assert not any(e.stage == "seedance_prompt" for e in other)
    assert "texto" in {e.id for e in other}  # the rest is untouched
    entry = library.get("humo_denso", 1)
    assert entry is not None
    assert measured_on_model(entry, DRAFT_MODEL)
    assert not measured_on_model(entry, SEEDANCE_MODEL)
    assert not measured_on_model(entry, None)


def test_offered_never_lists_an_effect_under_the_bar_even_built_around_the_validator(
    tmp_path: Path,
) -> None:
    library = _measured_library(tmp_path)
    entry = library.get("humo_denso", 1)
    assert entry is not None
    weak = entry.model_construct(**{**dict(entry), "measured": _bench(1, 4)})
    unmeasured = entry.model_construct(**{**dict(entry), "measured": None})
    for bad in (weak, unmeasured):
        forged = library.model_construct(version=5, notes="", entries=(bad,))
        assert forged.offered() == ()


@pytest.mark.parametrize("version", LIBRARIES)
def test_no_library_offers_an_unmeasured_seedance_effect(version: str) -> None:
    """Criterion: an effect without `measured` over the bar reaches no screen — every
    screen lists `offered()`, and the recipe gate refuses it as `not_offered`."""
    library = load_effects(version)
    for entry in library.entries:
        if entry.stage == "seedance_prompt":
            assert entry.measured is None and entry.offered is False
    assert not any(e.stage == "seedance_prompt" for e in library.offered())


def test_an_unmeasured_effect_is_refused_at_creation_even_with_the_switch_on(
    switch_on: None,
) -> None:
    brief = _clip(effects=(_use(),))
    with pytest.raises(RecipeRefused) as refused:
        refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)
    codes = {p.code for p in refused.value.problems}
    assert "not_offered" in codes and "recipe_unavailable" not in codes


# -- the template, filled ----------------------------------------------------------------------


def test_the_template_is_filled_with_the_zone_and_the_product() -> None:
    entry = load_effects().get("humo_denso", 1)
    assert entry is not None
    line = seedance_effect_line(entry, _use(zone="bottom"), subject=effect_subject("Smash doble"))
    assert line == (
        "Dense grey smoke drifts through the lower third of the frame above "
        '"Smash doble", as from a grill, without hiding it. Everything else stays as it is.'
    )
    # no zone chosen: the entry's default (top for humo_denso)
    assert "upper third" in seedance_effect_line(entry, _use(), subject="x")


def test_the_subject_is_the_product_or_a_neutral_default() -> None:
    assert effect_subject(None) == DEFAULT_EFFECT_SUBJECT
    assert effect_subject('  Pan "de" {bono} ') == '"Pan de bono"'
    assert effect_subject("Smash 🍔 doble 🔥") == '"Smash doble"'
    assert effect_subject("🍔") == DEFAULT_EFFECT_SUBJECT
    assert len(effect_subject("a " * 100)) <= 82


def test_the_cost_copy_is_spanish_and_counts_whole_seconds() -> None:
    assert AI_EFFECT_COST_NOTE == "Hecho con IA: usa segundos de video de tu plan"
    assert ai_effect_cost_text(5) == "Esta parte usa 5 segundos de video cuando la apruebes."
    assert ai_effect_cost_text(1) == "Esta parte usa 1 segundo de video cuando la apruebes."


# -- the switch and the gate -------------------------------------------------------------------


def test_the_switch_is_off_by_default_and_a_typo_reads_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SEEDANCE_EFFECTS_SWITCH, raising=False)
    assert not seedance_effects_on()
    monkeypatch.setenv(SEEDANCE_EFFECTS_SWITCH, "sí")
    assert not seedance_effects_on()
    monkeypatch.setenv(SEEDANCE_EFFECTS_SWITCH, " ON ")
    assert seedance_effects_on()


def test_switch_off_refuses_a_seedance_effect_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SEEDANCE_EFFECTS_SWITCH, raising=False)
    problems = unbuilt_recipe_problems(_clip(effects=(_use(),)))
    assert [(p.code, p.field) for p in problems] == [("recipe_unavailable", "effects")]


def test_switch_on_builds_it_only_on_a_reference_piece_over_the_whole_part(
    switch_on: None,
) -> None:
    assert unbuilt_recipe_problems(_clip(effects=(_use(),))) == ()
    assert is_built_seedance_effect(_use(), "reference")
    for mode in ("edit", "extend", "local"):
        assert not is_built_seedance_effect(_use(), mode)  # D4 / no Seedance
    spanned = EffectUse(effect_id="humo_denso", version=1, start_s=0.0, end_s=2.0)
    assert not is_built_seedance_effect(spanned, "reference")
    # a layer is not a Seedance template
    assert not is_built_seedance_effect(EffectUse(effect_id="humo_capa", version=1), "reference")


def test_the_effect_is_read_only_where_it_is_built(
    measured: EffectsLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert seedance_effect_of(_clip(effects=(_use(),))) is not None
    spanned = EffectUse(effect_id="humo_denso", version=1, start_s=0.0, end_s=2.0)
    assert seedance_effect_of(_clip(effects=(spanned,))) is None
    monkeypatch.setenv(SEEDANCE_EFFECTS_SWITCH, "off")
    assert seedance_effect_of(_clip(effects=(_use(),))) is None


# -- the prompt, the seed and the provenance --------------------------------------------------


def _produce(producer: MediaProducer, brief: Any, budget: BudgetContext = BUDGET) -> Any:
    return producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=budget
    )


def test_a_clip_with_the_effect_asks_it_in_its_prompt_sends_no_seed_and_keeps_provenance(
    measured: EffectsLibrary,
) -> None:
    seedance = DraftSeedance()
    outcome = _produce(
        _producer(_store(), seedance, RecordingFitter()), _clip(effects=(_use(zone="middle"),))
    )

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    prompt = str(request.params["prompt"])
    entry = measured.get("humo_denso", 1)
    assert entry is not None
    expected = seedance_effect_line(entry, _use(zone="middle"), subject=effect_subject(None))
    assert prompt.endswith(" " + expected)
    assert "seed" not in request.params  # never sent
    assert request.params["draft"] is True and request.params["resolution"] == "480p"
    (video,) = outcome.media
    assert video.params["seed"] == 33608  # the vendor's, kept
    assert video.params["prompt_chars"] == len(prompt)
    block = video.params[SEEDANCE_EFFECT_PARAMS_KEY]
    assert block["effect_id"] == "humo_denso" and block["version"] == 1
    assert block["prompt_version"] == "efecto-humo_denso-v1"
    assert block["zone"] == "middle" and block["line"] == expected
    assert block["fill_version"] == 1 and block["library_version"] == "v5"
    assert block["measured_model"] == DRAFT_MODEL
    # its final (the draft's own task) carries the same provenance
    assert video.params["draft"][SEEDANCE_EFFECT_PARAMS_KEY] == block


def test_the_seconds_and_cost_are_charged_as_without_the_effect(measured: EffectsLibrary) -> None:
    plain = _produce(_producer(_store(), DraftSeedance(), RecordingFitter()), _clip())
    with_effect = _produce(
        _producer(_store(), DraftSeedance(), RecordingFitter()), _clip(effects=(_use(),))
    )
    assert plain.failure is None and with_effect.failure is None
    assert [(u.unit, u.quantity, u.cost_usd) for u in with_effect.usage] == [
        (u.unit, u.quantity, u.cost_usd) for u in plain.usage
    ]


def test_the_final_of_an_effect_comes_from_the_draft_with_no_prompt_and_no_seed(
    measured: EffectsLibrary,
) -> None:
    store, seedance, fitter, draft_id = _store(), DraftSeedance(), RecordingFitter(), uuid4()
    producer = _producer(store, seedance, fitter)
    brief = _clip(effects=(_use(),))
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    ).media

    outcome = _finalize(producer, brief, _record(draft), draft_id)

    assert outcome.failure is None, outcome.detail
    final = seedance.requests[-1].params
    assert final["draft_task_id"] == "cgt-draft"
    assert "prompt" not in final and "seed" not in final
    assert outcome.media is not None
    assert outcome.media.params[SEEDANCE_EFFECT_PARAMS_KEY]["effect_id"] == "humo_denso"
    assert outcome.media.params["resolution"] == "1080p"


def test_another_version_after_the_switch_went_off_has_no_line(
    measured: EffectsLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Otra versión» / a retry of a piece stored with an effect, once the switch is off:
    asked as on main — no line, no provenance."""
    monkeypatch.setenv(SEEDANCE_EFFECTS_SWITCH, "off")
    seedance = DraftSeedance()
    outcome = _produce(_producer(_store(), seedance, RecordingFitter()), _clip(effects=(_use(),)))
    assert outcome.failure is None
    entry = measured.get("humo_denso", 1)
    assert entry is not None and entry.prompt_template is not None
    assert "Dense grey smoke" not in str(seedance.requests[0].params["prompt"])
    (video,) = outcome.media
    assert SEEDANCE_EFFECT_PARAMS_KEY not in video.params


def test_a_part_with_the_effect_asks_it_too(measured: EffectsLibrary) -> None:
    part = PartRef(index=1, mode="reference", seconds=5, effects=(_use("brasas"),))
    brief = _clip(part=part, duration_seconds=5)
    effect = seedance_effect_of(brief)
    assert effect is not None and effect.entry.id == "brasas"
    assert effect.provenance["prompt_version"] == "efecto-brasas-v1"
    prompt = media_module._part_prompt(brief=brief, kit=_kit(), images=0, model=DRAFT_MODEL)
    assert prompt.endswith(effect.line)


def test_a_clip_without_an_effect_is_asked_as_on_main(measured: EffectsLibrary) -> None:
    seedance = DraftSeedance()
    outcome = _produce(_producer(_store(), seedance, RecordingFitter()), _clip())
    (video,) = outcome.media
    assert SEEDANCE_EFFECT_PARAMS_KEY not in video.params
    assert SEEDANCE_EFFECT_PARAMS_KEY not in video.params["draft"]
    assert seedance_effect_of(_clip()) is None


def test_the_price_guard_runs_before_the_effect_is_asked(measured: EffectsLibrary) -> None:
    """Criterion (rule 7): the effect's request goes through the same router pre-flight —
    a budget under the estimate blocks it before ModelArk is called, nothing spent."""
    seedance = DraftSeedance()
    outcome = _produce(
        _producer(_store(), seedance, RecordingFitter()),
        _clip(effects=(_use(),)),
        budget=BudgetContext(remaining_usd=Decimal("0.01")),
    )
    assert outcome.failure == FailureReason.BUDGET_EXCEEDED.value
    assert seedance.requests == []


# -- D5: the model it is asked of ---------------------------------------------------------------


def test_an_effect_measured_on_another_model_is_refused_before_the_copy_and_the_call(
    switch_on: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _serve(monkeypatch, _measured_library(tmp_path, model="dreamina-seedance-2-0-260128"))
    seedance = DraftSeedance()
    producer = _producer(_store(), seedance, RecordingFitter())
    brief = _clip(effects=(_use(),))
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_new_brief(brief, _kit())  # before the copy is paid
    assert str(refused.value) == AI_EFFECT_MODEL_TEXT
    outcome = _produce(producer, brief)
    # inside the production the copy was paid: the text says it is given back
    assert outcome.detail == ai_effect_model_text(spent=True)
    assert seedance.requests == []


# -- the line inside the budget ------------------------------------------------------------------


def _capped_producer(seedance: FakeSeedance) -> MediaProducer:
    """Seedance 1.0 (`seedance-1-0-pro-250528`): a character cap, no draft mode."""
    pricing = JsonPricingTable("v5")
    return MediaProducer(
        store=_store(),
        router=CreativeRouter({"seedance": seedance}, pricing, KeysByProvider()),
        credentials=KeysByProvider(),
        pricing=pricing,
        download=lambda url: b"mp4",
        seedance_model=SEEDANCE_MODEL,
    )


@pytest.fixture
def measured_on_1_0(
    switch_on: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> EffectsLibrary:
    library = _measured_library(tmp_path, model=SEEDANCE_MODEL)
    _serve(monkeypatch, library)
    return library


def test_on_a_capped_model_the_owners_words_are_trimmed_never_the_effect(
    measured_on_1_0: EffectsLibrary,
) -> None:
    seedance = FakeSeedance()
    brief = _clip(effects=(_use(),), prompt_compiler_version=1)
    brief = brief.model_copy(update={"topic": "Smash doble con papas y salsa " * 150})
    producer = _capped_producer(seedance)
    producer.prepare_new_brief(brief, _kit())  # fits: nothing refused before the copy

    outcome = _produce(producer, brief)

    assert outcome.failure is None, outcome.detail
    prompt = str(seedance.requests[0].params["prompt"])
    entry = measured_on_1_0.get("humo_denso", 1)
    assert entry is not None
    assert prompt.endswith(seedance_effect_line(entry, _use(), subject=effect_subject(None)))
    assert len(prompt) <= media_module.MAX_PROMPT_CHARS
    (video,) = outcome.media
    trims = video.params["prompt_trims"]
    assert trims  # the topic was cut to make room…
    assert all(trim["kept"] > 0 for trim in trims)  # …never to nothing


def test_a_prompt_at_its_limit_is_refused_before_the_copy_and_never_asked(
    measured_on_1_0: EffectsLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's words at their least and the line still does not fit: refused in the
    check before the copy is paid (`prepare_new_brief`), and — were it reached — before
    the call, never sent with a cut template."""
    monkeypatch.setattr(media_module, "MAX_PROMPT_CHARS", 400)
    seedance = FakeSeedance()
    producer = _capped_producer(seedance)
    brief = _clip(effects=(_use(),), prompt_compiler_version=1)
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_new_brief(brief, _kit())
    assert str(refused.value) == AI_EFFECT_DOES_NOT_FIT_TEXT
    outcome = _produce(producer, brief)
    assert outcome.detail == ai_effect_does_not_fit_text(part=False, spent=True)
    assert seedance.requests == []


def test_the_compose_ignores_a_seedance_effect(measured: EffectsLibrary) -> None:
    """EF-14's compose lays only the library's layers: a Seedance template is in the
    prompt, never laid again over the clip."""
    from qualify_api.creative.video_pipeline.recompose import compose_recipe_of

    assert compose_recipe_of(_clip(effects=(_use(),)), _kit()) is None


def test_the_copy_check_counts_the_effect_line(
    measured: EffectsLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`copy_overage` (before the selector and the video are paid) compiles the same
    prompt the call sends — the line included: a copy that fits without the effect but
    not with it is sent back to be shortened."""
    producer = _producer(_store(), DraftSeedance(), RecordingFitter())
    plain = _clip(prompt_compiler_version=1)
    with_effect = _clip(effects=(_use(),), prompt_compiler_version=1)
    base = media_module.prompt_words(
        media_module.clip_prompt(
            brief=plain,
            kit=_kit(),
            first_frame=True,
            last_frame=False,
            images=0,
            videos=0,
            audios=0,
            copy=COPY,
            model=DRAFT_MODEL,
        )
    )
    monkeypatch.setattr(media_module, "VIDEO_PROMPT_MAX_WORDS", base + 2)
    payload = COPY.model_dump()
    assert producer.copy_overage(plain, _kit(), None, payload)[0] == 0
    over, note = producer.copy_overage(with_effect, _kit(), None, payload)
    assert over > 0 and note


def test_with_an_effect_the_owners_words_never_go_below_their_floors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 2: on a capped model the pass «below the floors» would cut the topic
    to nothing and keep the effect — an effect over nothing. With a line it stops at the
    floors and refuses instead; without one it still cuts as on main."""
    topic = media_module._Flex('It is about: "', "tema " * 100)
    lines: list[Any] = ["Fixed line.", topic]
    line = "An effect line of the library."
    budget = len("Fixed line.") + len(line) + 60  # room under the topic's 200 floor

    holder = media_module._EFFECT_SUFFIX.set([line])
    try:
        with pytest.raises(media_module._EffectDoesNotFit) as refused:
            media_module._budgeted_report(lines, budget)
    finally:
        media_module._EFFECT_SUFFIX.reset(holder)
    assert refused.value.detail == AI_EFFECT_DOES_NOT_FIT_TEXT

    prompt, trims = media_module._budgeted_report(lines, budget)  # no effect: as on main
    assert len(prompt) <= budget and trims


def test_the_texts_say_where_and_whether_anything_was_spent() -> None:
    assert AI_EFFECT_DOES_NOT_FIT_TEXT.endswith(
        "para este video. Acorta la descripción o quita el efecto. No se gastó nada."
    )
    assert "para esta parte" in ai_effect_does_not_fit_text(part=True, spent=False)
    assert ai_effect_does_not_fit_text(part=True, spent=True).endswith(
        "Te devolvimos lo que usaste."
    )
    assert AI_EFFECT_MODEL_TEXT == (
        "Este efecto no se puede usar en este video. Quítalo o elige otro, y vuelve a "
        "intentarlo. No se gastó nada."
    )


def test_switch_off_runs_nothing_of_ef13(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SEEDANCE_EFFECTS_SWITCH, raising=False)

    def boom(*_: object) -> None:
        raise AssertionError("read with the switch off")

    monkeypatch.setattr(effect_module, "load_effects", boom)
    assert seedance_effect_of(_clip(effects=(_use(),))) is None


def test_a_part_that_no_longer_fits_is_refused_before_the_copy_with_its_own_words(
    measured: EffectsLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(media_module, "VIDEO_PROMPT_MAX_WORDS", 20)
    part = PartRef(index=1, mode="reference", seconds=5, effects=(_use("brasas"),))
    brief = _clip(part=part, duration_seconds=5, prompt_compiler_version=1)
    producer = _producer(_store(), DraftSeedance(), RecordingFitter())
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_new_brief(brief, _kit())
    assert str(refused.value) == ai_effect_does_not_fit_text(part=True, spent=False)


@pytest.mark.parametrize("method", ["recreate_price", "regeneration_price"])
def test_a_remake_the_producer_would_refuse_has_no_price(method: str) -> None:
    from types import SimpleNamespace

    from qualify_api.creative.service import ContentService

    def refuse(brief: object, kit: object) -> object:
        raise BrandReferenceError(AI_EFFECT_MODEL_TEXT)

    brief = _clip(effects=(_use(),))
    service = object.__new__(ContentService)
    service._creations = object()
    service._repo = SimpleNamespace(
        get_draft=lambda **_: SimpleNamespace(brief_id=uuid4()), get_brief=lambda **_: brief
    )
    service._media = SimpleNamespace(prepare_new_brief=refuse)
    service._brand = SimpleNamespace(kit=lambda **_: _kit())
    assert getattr(service, method)(tenant_id=TENANT_ID, draft_id=uuid4()) is None
