"""EF-13 (m-25026589, ADR 50 D5): effects asked of Seedance as «an object in a zone of the
frame». Offline: the Seedance fakes of `test_creative_seedance_draft.py`; nothing paid.

Criteria covered here: the prompt carries the template and the provenance keeps
`effect_id`, version and `prompt_version`; no `seed` is sent and the returned one is kept;
an effect without a bench result over D5's bar is never offered; the price guard runs
before the call. Plus the switch `QUALIFY_SEEDANCE_EFFECTS` (off = as on main)."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.effects import (
    AI_EFFECT_COST_NOTE,
    DEFAULT_EFFECT_SUBJECT,
    Measured,
    ai_effect_cost_text,
    effect_subject,
    load_effects,
    parse_library,
    preview_file,
    seedance_effect_line,
)
from qualify_creative.enums import FailureReason
from qualify_creative.router import BudgetContext
from qualify_creative.schemas import EffectUse, PartRef

from qualify_api.creative.media import (
    AI_EFFECT_DOES_NOT_FIT_TEXT,
    _PromptOverBudget,
    _with_effect_line,
)
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

from .test_creative_media_byteplus import COPY, TENANT_ID, _kit
from .test_creative_seedance_draft import (
    BUDGET,
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


@pytest.fixture
def switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SEEDANCE_EFFECTS_SWITCH, "on")


# -- D5: the bench's bar and what a screen may offer -----------------------------------------


def _bench(successes: int, n: int) -> Measured:
    return Measured(
        successes=successes, n=n, wilson_low=0.1, wilson_high=0.9, measured_on="2026-11-24"
    )


@pytest.mark.parametrize(
    ("successes", "n", "passes"),
    [(3, 4, True), (4, 6, True), (4, 4, True), (2, 3, False), (2, 4, False), (5, 8, False)],
)
def test_d5_bar_is_two_of_three_with_at_least_four_tries(
    successes: int, n: int, passes: bool
) -> None:
    assert _bench(successes, n).passes is passes


def _offered_entry(root: Path, successes: int, n: int) -> dict:
    raw = json.loads((DATA / "v5.json").read_text(encoding="utf-8"))
    entry = copy.deepcopy(next(e for e in raw["entries"] if e["id"] == "humo_denso"))
    preview = "effects/humo_denso/v1/ejemplo.mp4"
    file = preview_file(preview, root)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"mp4")
    entry.update(
        offered=True,
        preview_asset=preview,
        measured={
            "successes": successes,
            "n": n,
            "wilson_low": 0.1,
            "wilson_high": 0.9,
            "measured_on": "2026-11-24",
        },
    )
    return {"version": 5, "entries": [entry]}


def test_an_effect_measured_under_the_bar_cannot_be_offered(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="2/3"):
        parse_library(_offered_entry(tmp_path, 2, 4), assets_root=tmp_path)
    with pytest.raises(ValidationError, match="2/3"):
        parse_library(_offered_entry(tmp_path, 3, 3), assets_root=tmp_path)  # n < 4
    library = parse_library(_offered_entry(tmp_path, 3, 4), assets_root=tmp_path)
    assert [e.id for e in library.offered()] == ["humo_denso"]


def test_offered_never_lists_an_effect_under_the_bar_even_built_around_the_validator(
    tmp_path: Path,
) -> None:
    library = parse_library(_offered_entry(tmp_path, 3, 4), assets_root=tmp_path)
    (entry,) = library.entries
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
            assert entry.measured is None or entry.measured.passes
            assert entry.offered is False
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
    assert len(effect_subject("a " * 100)) <= 82


def test_the_cost_copy_is_spanish_and_counts_whole_seconds() -> None:
    assert AI_EFFECT_COST_NOTE == "Con IA: gasta segundos de video"
    assert ai_effect_cost_text(5) == "Esta parte gastará 5 segundos de video de tu plan."


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


# -- the prompt, the seed and the provenance --------------------------------------------------


def test_a_clip_with_the_effect_asks_it_in_its_prompt_sends_no_seed_and_keeps_provenance() -> None:
    seedance, draft_id = DraftSeedance(), uuid4()
    brief = _clip(effects=(_use(zone="middle"),))
    outcome = _producer(_store(), seedance, RecordingFitter()).produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    prompt = str(request.params["prompt"])
    entry = load_effects().get("humo_denso", 1)
    assert entry is not None and entry.prompt_template is not None
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
    # its final (the draft's own task) carries the same provenance
    assert video.params["draft"][SEEDANCE_EFFECT_PARAMS_KEY] == block


def test_the_final_of_an_effect_comes_from_the_draft_with_no_prompt_and_no_seed() -> None:
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


def test_a_part_with_the_effect_asks_it_too() -> None:
    part = PartRef(index=1, mode="reference", seconds=5, effects=(_use("brasas"),))
    brief = _clip(part=part, duration_seconds=5)
    effect = seedance_effect_of(brief)
    assert effect is not None and effect.entry.id == "brasas"
    assert effect.provenance["prompt_version"] == "efecto-brasas-v1"


def test_a_clip_without_an_effect_is_asked_as_on_main() -> None:
    seedance = DraftSeedance()
    outcome = _producer(_store(), seedance, RecordingFitter()).produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    )
    (video,) = outcome.media
    assert SEEDANCE_EFFECT_PARAMS_KEY not in video.params
    assert SEEDANCE_EFFECT_PARAMS_KEY not in video.params["draft"]
    assert seedance_effect_of(_clip()) is None


def test_the_price_guard_runs_before_the_effect_is_asked() -> None:
    """Criterion (rule 7): the effect's request goes through the same router pre-flight —
    a budget under the estimate blocks it before ModelArk is called, nothing spent."""
    seedance = DraftSeedance()
    outcome = _producer(_store(), seedance, RecordingFitter()).produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_clip(effects=(_use(),)),
        kit=_kit(),
        copy=COPY,
        budget=BudgetContext(remaining_usd=Decimal("0.01")),
    )
    assert outcome.failure == FailureReason.BUDGET_EXCEEDED.value
    assert seedance.requests == []


def test_the_line_is_never_trimmed_it_fits_whole_or_nothing_is_asked() -> None:
    assert _with_effect_line("base", "line", None) == "base line"
    assert _with_effect_line("base", "line", 9) == "base line"
    with pytest.raises(_PromptOverBudget) as over:
        _with_effect_line("base", "line", 8)
    assert over.value.detail == AI_EFFECT_DOES_NOT_FIT_TEXT
    with pytest.raises(_PromptOverBudget):
        _with_effect_line("palabra " * 999, "una dos", None)


def test_the_compose_ignores_a_seedance_effect(switch_on: None) -> None:
    """EF-14's compose lays only the library's layers: a Seedance template is in the
    prompt, never laid again over the clip."""
    from qualify_api.creative.video_pipeline.recompose import compose_recipe_of

    assert compose_recipe_of(_clip(effects=(_use(),)), _kit()) is None
