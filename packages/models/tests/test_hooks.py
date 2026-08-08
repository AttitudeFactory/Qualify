"""Tests for the hook-pattern spike.

Everything here is offline: no network, no model weights. The one end-to-end test runs
the real extractor over the real fixture mp4 with fake providers, which is what proves
the plumbing works without paying for it.
"""

from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from PIL import Image

from qualify_models.hooks.analysis import (
    CONFOUNDERS,
    Normalization,
    Outcome,
    PostObservation,
    assess_viability,
    bonferroni_alpha,
    hook_type_effects,
    inverse_normal_cdf,
    minimum_n_for_correlation,
    minimum_n_per_group,
    normalized_outcomes,
    spearman_rho,
)
from qualify_models.hooks.corpus import estimate_corpus_cost, plan_corpus
from qualify_models.hooks.lexical import analyze_speech, classify_lexical, second_person_register
from qualify_models.hooks.schema import FLAT_ROW_COLUMNS
from qualify_models.hooks.spec import HOOK_SPEC_VERSION, HookType, Setting, TextDensity
from qualify_models.hooks.visual import analyze_frames
from qualify_models.hooks.vlm import build_prompt, parse_vlm_output

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_VIDEO = FIXTURES / "sample_source.mp4"

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


# --- Fase A: the definition -----------------------------------------------------------


def test_none_detected_and_unknown_are_distinct_categories() -> None:
    """The whole point of keeping them apart: one is a fact about the video, the other is
    a failure of the extractor. Collapsing them would let broken runs look like silence."""
    assert HookType.NONE_DETECTED is not HookType.UNKNOWN
    assert HookType.NONE_DETECTED.value == "none_detected"


def test_hook_spec_version_is_pinned() -> None:
    assert HOOK_SPEC_VERSION


# --- lexical tier ---------------------------------------------------------------------


def test_founder_example_is_typed_as_question() -> None:
    """'¿Estás cansado de la ciudad?' — the literal example from the brief. It is both a
    question and a pain point; the documented precedence says question wins."""
    assert classify_lexical("¿Estás cansado de la ciudad?") is HookType.QUESTION


def test_pain_point_without_a_question_mark_stays_pain_point() -> None:
    assert classify_lexical("Estás cansado de pagar un alquiler carísimo.") is HookType.PAIN_POINT


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3 cosas que nadie te dice antes de comprar", HookType.NUMERIC_LIST),
        ("No vas a creer lo que hay detrás de esta puerta", HookType.CURIOSITY_GAP),
        ("No firmes nada sin ver esto", HookType.NEGATION_WARNING),
        ("Mira este salón con vistas al mar", HookType.COMMAND_CTA),
        ("Esta casa cuesta 85.000 euros", HookType.PRICE_REVEAL),
        ("Esto está a 40 minutos de Madrid", HookType.LOCATION_REVEAL),
        ("Hace dos años yo vivía en un piso interior", HookType.PERSONAL_STORY),
    ],
)
def test_lexical_rules(text: str, expected: HookType) -> None:
    assert classify_lexical(text) is expected


def test_accents_are_folded_so_asr_spelling_does_not_change_the_type() -> None:
    assert classify_lexical("Fijate en esta cocina") is classify_lexical("Fíjate en esta cocina")


def test_unmatched_text_returns_none_rather_than_a_catch_all() -> None:
    """A catch-all category would become the biggest bucket in the corpus and make every
    statistic about it meaningless."""
    assert classify_lexical("La cocina tiene electrodomésticos nuevos") is None


def test_on_screen_text_alone_can_carry_the_hook() -> None:
    """A silent drone shot with a burned-in caption has a hook. Reading only the
    transcript would have scored it as having none."""
    assert classify_lexical("", "¿Cansado del ruido?") is HookType.QUESTION


def test_speech_markers_and_pace() -> None:
    spoken = analyze_speech("¿Estás cansado de la ciudad? No sigas pagando 900 €", 3.0)
    assert spoken.has_speech
    assert spoken.has_question_mark
    assert spoken.has_second_person
    assert spoken.has_negation
    assert spoken.has_numeral
    assert spoken.has_price_token
    assert spoken.words_per_second == pytest.approx(spoken.word_count / 3.0)


def test_second_person_survives_pro_drop_without_firing_on_the_homograph() -> None:
    """Spanish drops subject pronouns, so "¿Estás cansado?" addresses the viewer with no
    pronoun in sight — but accent-folded "estas" is also the demonstrative in "estas
    casas". Both halves have to hold at once."""
    assert analyze_speech("¿Estás cansado de la ciudad?", 3.0).has_second_person
    assert not analyze_speech("Estas casas están en la sierra", 3.0).has_second_person


# --- dialect: the Venezuela-Colombia border corpus ---------------------------------------
#
# This file was written in peninsular Spanish and the chosen corpus is San Cristóbal
# (Táchira, VE) and Cúcuta (Norte de Santander, CO). None of these cases used to raise —
# they returned confident wrong values, which is the failure mode that survives a test
# suite. Every peninsular case above still has to pass alongside these.


def test_the_founder_example_works_in_both_registers() -> None:
    """*"¿Estás cansado de la ciudad?"* from a Cúcuta advisor is *"¿Está cansado...?"*.
    Same hook, same type, and both must count as addressing the viewer."""
    tu = analyze_speech("¿Estás cansado de la ciudad?", 3.0)
    usted = analyze_speech("¿Está cansado de la ciudad?", 3.0)
    assert tu.has_second_person and usted.has_second_person
    assert tu.second_person_register == "tu"
    assert usted.second_person_register == "usted"
    assert classify_lexical("¿Está cansado de la ciudad?") is HookType.QUESTION


@pytest.mark.parametrize(
    ("tu_form", "usted_form"),
    [
        ("Mira este apartamento", "Mire este apartamento"),
        ("Ven y te muestro el lote", "Venga y le muestro el lote"),
        ("Fíjate en el precio", "Fíjese en el precio"),
        ("No firmes nada sin ver esto", "No firme nada sin ver esto"),
    ],
)
def test_command_and_warning_hooks_survive_the_usted_register(
    tu_form: str, usted_form: str
) -> None:
    """The sharpest damage was here, not in the markers: an usted-speaking advisor's
    command hooks used to fall out of the taxonomy into `unknown` entirely, which would
    have reported that half the corpus does not use command hooks."""
    assert classify_lexical(tu_form) is classify_lexical(usted_form)
    assert analyze_speech(usted_form, 3.0).has_second_person


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("¿Estás cansado de la ciudad?", "tu"),
        ("No firmes nada", "tu"),
        ("¿Está pagando arriendo?", "usted"),
        ("¿Quiere comprar casa en Cúcuta?", "usted"),
        ("Mire este lote", "usted"),
        ("No firme nada", "usted"),
        ("Ustedes ya saben", "usted"),
        # Usted-shaped verb, nothing to disambiguate it: neither a detection nor a denial.
        ("El apartamento está en el centro", "ambiguous"),
        ("La casa tiene tres cuartos", "ambiguous"),
        ("Mi cliente quiere comprar rápido", "ambiguous"),
        # No address of any kind.
        ("Estas casas están en la sierra", "none"),
        ("El vendedor no espera respuesta", "none"),
    ],
)
def test_second_person_register_is_recorded_not_guessed(text: str, expected: str) -> None:
    assert second_person_register(text) == expected


def test_the_demonstrative_does_not_inflate_the_ambiguous_bucket() -> None:
    """Accent-folded "esta" is the demonstrative that opens half the real-estate hooks in
    the corpus ("esta casa"), and folded it looks exactly like the usted verb "está". Left
    folded, nearly every row would land in `ambiguous` and the bucket would stop meaning
    anything. Same homograph the tú path already guards, handled the same way."""
    assert second_person_register("La compra de esta casa empieza aquí") == "none"
    assert second_person_register("Esta casa está en el centro") == "ambiguous"


def test_ambiguous_register_never_sets_the_second_person_flag() -> None:
    """The whole reason the register exists. Resolving "La casa tiene tres cuartos" to
    `usted` would manufacture direct address; resolving it to `none` would hide how much
    of the corpus is undecidable. It is recorded as its own state and the flag stays
    False."""
    spoken = analyze_speech("La casa tiene tres cuartos", 3.0)
    assert spoken.second_person_register == "ambiguous"
    assert not spoken.has_second_person


@pytest.mark.parametrize(
    "text",
    [
        # Colombia: millions of pesos, usually with no symbol and no thousands separator.
        "Esta casa sale en 250 millones de pesos",
        "Se lo dejo en 300 millones",
        "180 millones, con lote",
        "Son 300 palos",
        # Venezuela: US dollars, including the slang.
        "Esta casa cuesta 20 mil dólares",
        "$45.000 y es suya",
        "Le vale 18 mil verdes",
        # Peninsular, which must keep working rather than be traded away.
        "Esta casa cuesta 85.000 euros",
        "85.000 € y con parcela",
    ],
)
def test_prices_are_detected_in_all_three_currencies_of_the_corpus(text: str) -> None:
    assert analyze_speech(text, 3.0).has_price_token
    assert classify_lexical(text) is HookType.PRICE_REVEAL


@pytest.mark.parametrize(
    "text",
    ["Un millón de razones para mudarte", "Las paredes verdes del salón"],
)
def test_magnitude_words_are_not_prices_without_a_number(text: str) -> None:
    """`millones`/`verdes` need a numeral in front. Otherwise a figure of speech becomes a
    price and `price_reveal` inflates on the most common hook type in the corpus."""
    assert not analyze_speech(text, 3.0).has_price_token


def test_prepositions_that_look_like_imperatives_do_not_fire() -> None:
    """Two traps that a real-estate corpus hits constantly: "para" as a preposition (a
    pre-existing false positive, now fixed) and "entre" as "between", which is why the
    usted imperative list deliberately omits it."""
    assert not analyze_speech("Ideal para comprar y arrendar", 3.0).has_imperative_marker
    assert classify_lexical("Entre 200 y 300 millones hay mucha oferta") is not HookType.COMMAND_CTA


@pytest.mark.parametrize(
    ("tu_form", "usted_form"),
    [
        ("Mírala bien", "Mírela bien"),
        ("Muéstrame el lote", "Muéstreme el lote"),
        ("Cómprala ya", "Cómprela ya"),
        ("Llámame hoy", "Llámeme hoy"),
    ],
)
def test_imperatives_with_attached_pronouns_are_still_commands(
    tu_form: str, usted_form: str
) -> None:
    """Spanish glues object pronouns onto imperatives: "mírala", "cómprela", "muéstreme".
    Every one of these used to score as having no command at all. The gap was symmetric
    across registers, so this is a plain bug the dialect pass surfaced rather than a
    dialect problem — and both halves have to be fixed together."""
    for text in (tu_form, usted_form):
        assert analyze_speech(text, 3.0).has_imperative_marker
        assert classify_lexical(text) is HookType.COMMAND_CTA
    assert second_person_register(tu_form) == "tu"
    assert second_person_register(usted_form) == "usted"


@pytest.mark.parametrize("text", ["La compra de esta casa empieza aquí", "Una llamada y listo"])
def test_nouns_that_share_a_stem_with_an_imperative_do_not_fire(text: str) -> None:
    """`compra` and `llama` are also everyday nouns, so they only count as commands with a
    pronoun attached — nouns do not take enclitics. That is what keeps "la compra de esta
    casa" from being read as a call to action."""
    assert not analyze_speech(text, 3.0).has_imperative_marker


def test_both_registers_get_credit_for_imperatives() -> None:
    """Regression guard on a bias this file briefly shipped: only the usted imperatives
    fed the register, so usted-speaking accounts looked like they addressed the viewer more
    often than tú-speaking ones. That plants a systematic difference inside the very column
    F5 uses to test whether register tracks country."""
    assert second_person_register("Mira este apartamento") == "tu"
    assert second_person_register("Mire este apartamento") == "usted"
    assert analyze_speech("Mira este apartamento", 3.0).has_second_person
    assert analyze_speech("Mire este apartamento", 3.0).has_second_person


def test_colombian_verb_for_renting_is_recognised() -> None:
    """`arrendar` (CO) alongside `alquilar` (ES/VE) — the one genuine regionalism in the
    rule set. Housing nouns (piso/parcela/dormitorio) never appear in these rules at all,
    so they needed nothing."""
    assert classify_lexical("Antes de arrendar mire esto") is classify_lexical(
        "Antes de alquilar mira esto"
    )


def test_silence_produces_no_speech() -> None:
    spoken = analyze_speech("   ", 3.0)
    assert not spoken.has_speech
    assert spoken.word_count == 0
    assert spoken.words_per_second == 0.0


# --- deterministic visual tier ---------------------------------------------------------


def _write_frame(path: Path, color: tuple[int, int, int]) -> Path:
    Image.new("RGB", (120, 200), color).save(path)
    return path


def test_identical_frames_have_no_cuts_and_no_motion(tmp_path: Path) -> None:
    frames = [_write_frame(tmp_path / f"f{i}.jpg", (30, 60, 90)) for i in range(4)]
    result = analyze_frames(frames, window_seconds=3.0)
    assert result.cut_count == 0
    assert result.motion_energy == pytest.approx(0.0, abs=0.02)
    assert result.n_frames == 4


def test_alternating_frames_register_cuts(tmp_path: Path) -> None:
    colors = [(0, 0, 0), (255, 255, 255), (0, 0, 0), (255, 255, 255)]
    frames = [_write_frame(tmp_path / f"f{i}.jpg", c) for i, c in enumerate(colors)]
    result = analyze_frames(frames, window_seconds=3.0)
    assert result.cut_count == 3
    assert result.cuts_per_second == pytest.approx(1.0)
    assert len(result.dominant_colors) >= 2


def test_no_frames_is_an_empty_result_not_a_crash() -> None:
    result = analyze_frames([], window_seconds=3.0)
    assert result.n_frames == 0
    assert result.cut_count == 0


# --- VLM parsing ------------------------------------------------------------------------


def test_parses_clean_json() -> None:
    reading = parse_vlm_output(
        '{"hook_type": "question", "setting": "land_plot", "face_present": false, '
        '"person_count": 0, "on_screen_text": "¿Cansado?", "text_density": "low"}'
    )
    assert reading.parse_ok
    assert reading.hook_type is HookType.QUESTION
    assert reading.setting is Setting.LAND_PLOT
    assert reading.face_present is False
    assert reading.text_density is TextDensity.LOW


def test_parses_json_wrapped_in_prose_and_fences() -> None:
    raw = 'Sure! Here is the analysis:\n```json\n{"hook_type": "price_reveal"}\n```\nHope it helps.'
    reading = parse_vlm_output(raw)
    assert reading.parse_ok
    assert reading.hook_type is HookType.PRICE_REVEAL


def test_out_of_vocabulary_value_becomes_unknown_not_a_plausible_guess() -> None:
    reading = parse_vlm_output('{"hook_type": "clickbait_shock", "setting": "kitchen"}')
    assert reading.hook_type is HookType.UNKNOWN
    assert reading.setting is Setting.UNKNOWN
    assert not reading.parse_ok


def test_unparseable_output_is_kept_verbatim() -> None:
    reading = parse_vlm_output("I cannot analyse this image.")
    assert not reading.parse_ok
    assert reading.hook_type is HookType.UNKNOWN
    assert reading.raw_output == "I cannot analyse this image."


def test_prompt_lists_the_closed_vocabulary_and_never_offers_unknown() -> None:
    prompt = build_prompt("¿Estás cansado de la ciudad?", n_frames=9, window_seconds=3.0)
    assert "question" in prompt and "none_detected" in prompt
    # `unknown` is the extractor's failure state, not a category the model may pick.
    assert '"hook_type": one of [' in prompt
    assert "unknown" not in prompt.split('"hook_type": one of [')[1].split("]")[0]
    assert "¿Estás cansado de la ciudad?" in prompt


# --- end to end over the real fixture -----------------------------------------------------


class _FakeVision:
    model_id = "fake/vision"

    def describe(self, image_path: Path, prompt: str) -> str:
        assert image_path.exists()
        return (
            '{"hook_type": "question", "setting": "urban_street", "face_present": true, '
            '"person_count": 1, "on_screen_text": "¿Cansado?", "text_density": "low"}'
        )


class _FakeTranscription:
    model_id = "fake/asr"

    def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        assert audio_path.exists()
        return "¿Estás cansado de la ciudad?", "es"


@needs_ffmpeg
def test_extract_hook_features_end_to_end_on_the_real_fixture() -> None:
    from qualify_models.hooks.extract import DETECTOR_VERSION, extract_hook_features

    features = extract_hook_features(
        SAMPLE_VIDEO,
        source_id="sample_tiktok",
        windows=(3.0, 5.0),
        vlm_windows=(3.0,),
        vision_provider=_FakeVision(),
        transcription_provider=_FakeTranscription(),
    )

    assert features.detector_version == DETECTOR_VERSION
    assert features.hook_spec_version == HOOK_SPEC_VERSION
    # A caller-supplied provider is neither of the two known backends; say so.
    assert features.vlm_backend == "injected"
    assert len(features.video_sha256) == 64
    assert features.duration_seconds and features.duration_seconds > 60
    assert [w.window_seconds for w in features.windows] == [3.0, 5.0]

    primary = features.window(3.0)
    assert primary is not None
    assert primary.hook_type is HookType.QUESTION
    assert primary.hook_type_source == "vlm"
    assert primary.hook_type_lexical is HookType.QUESTION
    assert primary.visual.n_frames_sampled == 9  # 3 s at 3 fps
    assert primary.visual.setting is Setting.URBAN_STREET

    # The 5 s window got no VLM call, so its model-derived fields stay None — and the
    # lexical tier still types it. That asymmetry is the design, not a bug.
    wider = features.window(5.0)
    assert wider is not None
    assert wider.visual.setting is None
    assert wider.hook_type_source == "lexical"
    assert wider.visual.n_frames_sampled == 15


@needs_ffmpeg
def test_deterministic_only_mode_needs_no_provider_at_all() -> None:
    from qualify_models.hooks.extract import extract_hook_features

    features = extract_hook_features(
        SAMPLE_VIDEO,
        source_id="sample_tiktok",
        windows=(3.0,),
        use_vlm=False,
        use_asr=False,
    )
    window = features.window(3.0)
    assert window is not None
    assert features.vlm_model_id is None
    assert features.asr_model_id is None
    # Nothing looked at the pixels for burned-in text and nothing heard the audio, so the
    # only honest answer is `unknown` — never `none_detected`.
    assert window.hook_type is HookType.UNKNOWN
    assert window.hook_type_source == "unknown"
    assert window.visual.brightness > 0.0


@needs_ffmpeg
def test_flat_row_matches_the_declared_csv_header() -> None:
    from qualify_models.hooks.extract import extract_hook_features

    features = extract_hook_features(
        SAMPLE_VIDEO,
        source_id="sample_tiktok",
        windows=(3.0,),
        use_vlm=False,
        use_asr=False,
    )
    row = features.to_flat_row(3.0)
    assert tuple(row) == FLAT_ROW_COLUMNS
    # Provenance travels on every row, not just in the report header.
    assert row["hook_spec_version"] == HOOK_SPEC_VERSION
    assert row["detector_version"]
    assert row["video_sha256"]
    # No VLM ran, so the backend column is empty rather than naming one that did not run.
    assert row["vlm_backend"] is None


# --- which VLM actually ran -------------------------------------------------------------
#
# The spike's original CLI could only ever run the local VLM: `extract_hook_features`
# hardcoded it as the default and no flag reached past that. The measured consequence was
# >20 min/video instead of ~15 s, and it was misread as "the hosted provider rejects this
# account". These tests exist so the backend is a choice that is made, recorded and
# testable, rather than a default nobody can see.


def test_backend_names_resolve_to_the_right_provider() -> None:
    from qualify_models.providers import (
        HFInferenceVisionProvider,
        LocalQwenVisionProvider,
        build_vision_provider,
    )

    assert isinstance(build_vision_provider("hosted"), HFInferenceVisionProvider)
    assert isinstance(build_vision_provider("local"), LocalQwenVisionProvider)
    assert build_vision_provider("none") is None
    with pytest.raises(ValueError):
        build_vision_provider("gpu")  # type: ignore[arg-type]


def test_backend_label_distinguishes_paths_a_model_id_cannot() -> None:
    from qualify_models.providers import (
        HFInferenceVisionProvider,
        LocalQwenVisionProvider,
        label_vision_backend,
    )

    hosted = HFInferenceVisionProvider()
    local = LocalQwenVisionProvider()
    # Same checkpoint id on both paths: without the label, a row cannot say which ran.
    assert hosted.model_id == local.model_id
    assert label_vision_backend(hosted) == "hosted"
    assert label_vision_backend(local) == "local"
    assert label_vision_backend(_FakeVision()) == "injected"
    assert label_vision_backend(None) is None


@needs_ffmpeg
def test_extractor_asks_for_the_hosted_backend_by_default(monkeypatch) -> None:
    """Offline check of the default: record which backend the extractor requests without
    letting either backend actually run."""
    from qualify_models.hooks import extract as extract_module

    asked: list[str] = []

    def _spy(backend: str, model_id: str = "") -> None:
        asked.append(backend)
        return None

    monkeypatch.setattr(extract_module, "build_vision_provider", _spy)
    video = SAMPLE_VIDEO
    for kwargs, expected in (
        ({}, "hosted"),
        ({"vision_backend": "local"}, "local"),
        ({"vision_backend": "none"}, "none"),
    ):
        asked.clear()
        extract_module.extract_hook_features(
            video, source_id="x", windows=(3.0,), use_asr=False, **kwargs
        )
        assert asked == [expected]


@needs_ffmpeg
def test_use_vlm_false_still_skips_the_model_without_asking_for_a_backend(monkeypatch) -> None:
    """The older negative flag keeps working, and short-circuits before any backend is
    built — the documented `--no-vlm` commands must not start paying for a hosted call."""
    from qualify_models.hooks import extract as extract_module

    def _explode(backend: str, model_id: str = "") -> None:
        raise AssertionError(f"no backend should be built, got {backend!r}")

    monkeypatch.setattr(extract_module, "build_vision_provider", _explode)
    features = extract_module.extract_hook_features(
        SAMPLE_VIDEO, source_id="x", windows=(3.0,), use_vlm=False, use_asr=False
    )
    assert features.vlm_model_id is None
    assert features.vlm_backend is None


def test_cli_exposes_the_backend_and_defaults_to_hosted() -> None:
    from qualify_models.hooks.cli import build_parser, resolve_backend

    parser = build_parser()
    base = ["--video", "a.mp4", "--out-dir", "out"]
    assert parser.parse_args(base).vision == "hosted"
    assert parser.parse_args([*base, "--vision", "local"]).vision == "local"

    # --no-vlm is deprecated but must still win, including against an explicit --vision.
    assert resolve_backend("hosted", no_vlm=False) == "hosted"
    assert resolve_backend("hosted", no_vlm=True) == "none"
    assert resolve_backend("local", no_vlm=True) == "none"
    with pytest.raises(SystemExit):
        parser.parse_args([*base, "--vision", "gpu"])


# --- Fase D: the analysis --------------------------------------------------------------


def test_inverse_normal_cdf_matches_known_quantiles() -> None:
    assert inverse_normal_cdf(0.975) == pytest.approx(1.959964, abs=1e-5)
    assert inverse_normal_cdf(0.80) == pytest.approx(0.841621, abs=1e-5)
    assert inverse_normal_cdf(0.5) == pytest.approx(0.0, abs=1e-9)


def test_minimum_n_grows_as_the_effect_shrinks() -> None:
    large = minimum_n_per_group(0.8)
    medium = minimum_n_per_group(0.5)
    small = minimum_n_per_group(0.2)
    assert large < medium < small
    # Sanity against the textbook figures for a two-sample test at 80% power.
    assert 24 <= large <= 30
    assert 60 <= medium <= 70


def test_minimum_n_for_correlation_is_in_the_expected_range() -> None:
    assert 80 <= minimum_n_for_correlation(0.3) <= 100


def test_bonferroni_shrinks_alpha_with_the_number_of_types() -> None:
    assert bonferroni_alpha(13) == pytest.approx(0.05 / 13)


def test_spearman_is_undefined_below_three_points() -> None:
    assert spearman_rho([1.0, 2.0], [1.0, 2.0]) is None


def test_spearman_detects_monotone_relationships() -> None:
    rho = spearman_rho([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 25.0, 40.0])
    assert rho == pytest.approx(1.0)


def test_within_account_normalization_removes_the_follower_confound() -> None:
    """The load-bearing test of the whole Fase D design.

    Two accounts. The big one has 100x the engagement of the small one on every post, and
    happens to use `direct_claim`. The small one uses `question`, and inside its own
    library the question posts are its best. A raw pooled analysis crowns `direct_claim`
    purely because that account has an audience; within-account normalization does not.
    """
    observations = [
        # Big account: huge absolute numbers, but these are its *worst* posts.
        PostObservation(
            source_id="b1", account_id="big", hook_type="direct_claim", engagement=8000
        ),
        PostObservation(
            source_id="b2", account_id="big", hook_type="direct_claim", engagement=9000
        ),
        PostObservation(source_id="b3", account_id="big", hook_type="question", engagement=30000),
        PostObservation(source_id="b4", account_id="big", hook_type="question", engagement=40000),
        # Small account: tiny absolute numbers, same internal ordering.
        PostObservation(
            source_id="s1", account_id="small", hook_type="direct_claim", engagement=80
        ),
        PostObservation(
            source_id="s2", account_id="small", hook_type="direct_claim", engagement=90
        ),
        PostObservation(source_id="s3", account_id="small", hook_type="question", engagement=300),
        PostObservation(source_id="s4", account_id="small", hook_type="question", engagement=400),
    ]

    raw = normalized_outcomes(observations, normalization=Normalization.RAW)
    # Raw: every post of the big account outranks every post of the small one.
    assert min(raw["b1"], raw["b2"]) > max(raw["s3"], raw["s4"])

    within = normalized_outcomes(observations, normalization=Normalization.WITHIN_ACCOUNT)
    # Within-account: the question posts sit at the top of *both* libraries.
    assert within["s3"] > within["b1"]
    assert within["b3"] > within["b1"]
    assert within["s4"] == within["b4"]


def test_recency_adjustment_removes_a_pure_growth_trend() -> None:
    """An account whose engagement rises monotonically with time only because its audience
    grew. After adjustment the residuals must not still rank by date."""
    observations = [
        PostObservation(
            source_id=f"p{i}",
            account_id="grower",
            hook_type="question",
            engagement=float(i * 100),
            posted_at=date(2026, 1, i + 1),
        )
        for i in range(1, 9)
    ]
    adjusted = normalized_outcomes(observations, normalization=Normalization.RECENCY_ADJUSTED)
    first, last = adjusted["p1"], adjusted["p8"]
    assert abs(first - last) < 0.5  # the trend is gone, not merely reduced


# --- viability: is there anything to explain? -------------------------------------------


def _library(account: str, hook_types: list[str], values: list[float], as_views: bool):
    return [
        PostObservation(
            source_id=f"{account}-{i}",
            account_id=account,
            hook_type=hook_types[i % len(hook_types)],
            engagement=0.0 if as_views else values[i],
            views=values[i] if as_views else None,
        )
        for i in range(len(values))
    ]


def test_small_integer_likes_are_mostly_ties_by_pigeonhole() -> None:
    """Measured on a real candidate account: likes 2-14 across its posts. That range holds
    13 possible values, so a 30-post library has a tie fraction of at least 1 - 13/30 =
    0.57 **whatever the distribution** — it is arithmetic, not an unlucky sample. Above the
    0.5 threshold, so within-account ranking on likes has little left to order."""
    values = [float(2 + (i % 13)) for i in range(30)]
    posts = _library("a1", ["question", "direct_claim"], values, as_views=False)
    report = assess_viability(posts, Outcome.ENGAGEMENT)
    assert report.median_tie_fraction >= 0.56
    assert not report.viable
    assert any("mostly ties" in r for r in report.reasons)


def test_views_have_the_resolution_that_likes_lack() -> None:
    """Same account, same posts, the other column: views measured 383-1324. Nearly a
    thousand possible values across 30 posts forces no ties at all."""
    values = [float(383 + i * 31) for i in range(30)]
    posts = _library("a1", ["question", "direct_claim"], values, as_views=True)
    report = assess_viability(posts, Outcome.VIEWS)
    assert report.median_tie_fraction == 0.0
    assert report.viable
    assert report.median_spread_ratio is not None


def test_a_single_caption_template_kills_the_design_whatever_the_outcome() -> None:
    """The sourcing agent found a candidate publishing five consecutive videos on one
    caption template. If the hook never varies inside an account, within-account
    comparison has nothing to compare — and no corpus size fixes it."""
    values = [float(400 + i * 37) for i in range(20)]
    posts = _library("a1", ["direct_claim"], values, as_views=True)
    report = assess_viability(posts, Outcome.VIEWS)
    assert not report.viable
    assert report.accounts_with_hook_variety == 0
    assert any("one template" in r for r in report.reasons)


def test_engagement_rate_is_undefined_rather_than_zero_without_views() -> None:
    """An empty denominator is an absent measurement, not a low rate. Imputing 0 would
    quietly rank unmeasured posts as the worst performers in their library."""
    seen = PostObservation(
        source_id="a", account_id="x", hook_type="question", engagement=10, views=500
    )
    unseen = PostObservation(
        source_id="b", account_id="x", hook_type="question", engagement=10, views=0
    )
    missing = PostObservation(source_id="c", account_id="x", hook_type="question", engagement=10)
    assert seen.outcome(Outcome.ENGAGEMENT_RATE) == pytest.approx(0.02)
    assert unseen.outcome(Outcome.ENGAGEMENT_RATE) is None
    assert missing.outcome(Outcome.ENGAGEMENT_RATE) is None
    assert missing.outcome(Outcome.VIEWS) is None


def test_viability_on_an_empty_corpus_is_a_verdict_not_a_crash() -> None:
    report = assess_viability([], Outcome.VIEWS)
    assert not report.viable
    assert report.n_posts == 0


def test_report_is_not_conclusive_on_a_tiny_corpus() -> None:
    observations = [
        PostObservation(
            source_id=f"p{i}", account_id="a", hook_type="question", engagement=float(i)
        )
        for i in range(6)
    ]
    report = hook_type_effects(observations)
    assert not report.conclusive
    assert report.n_accounts == 1
    effect = report.effects[0]
    assert not effect.meets_min_posts
    assert not effect.meets_min_accounts
    # Underpowered rows are reported, never suppressed — suppression is cherry-picking.
    assert effect.n_posts == 6


def test_report_always_carries_the_confounder_registry_and_refuses_causal_language() -> None:
    report = hook_type_effects(
        [PostObservation(source_id="p1", account_id="a", hook_type="question", engagement=1.0)]
    )
    assert report.causal_claim_supported is False
    assert len(report.confounders) == len(CONFOUNDERS)
    assert any(c.handled == "uncontrolled" for c in report.confounders)
    assert "non-causal" in report.interpretation


def test_missing_outcome_is_dropped_not_imputed() -> None:
    observations = [
        PostObservation(
            source_id="p1",
            account_id="a",
            hook_type="question",
            engagement=1.0,
            positive_sentiment_ratio=0.8,
        ),
        PostObservation(
            source_id="p2",
            account_id="a",
            hook_type="question",
            engagement=2.0,
        ),
    ]
    normalized = normalized_outcomes(observations, metric=Outcome.POSITIVE_SENTIMENT_RATIO)
    assert "p1" in normalized
    assert "p2" not in normalized


# --- Fase C: corpus sizing and cost --------------------------------------------------------


def test_plan_scales_with_the_effect_being_chased() -> None:
    large = plan_corpus(detectable_effect_d=0.8)
    medium = plan_corpus(detectable_effect_d=0.5)
    assert medium.total_posts_needed > large.total_posts_needed
    assert large.posts_per_account * large.min_accounts >= large.total_posts_needed


def test_unsourced_rates_stay_none_and_propagate() -> None:
    """`eval/cost.py`'s discipline, inherited: a total that quietly omits an unpriced
    stage is worse than no total."""
    cost = estimate_corpus_cost(plan_corpus())
    assert cost.acquisition_usd_zyte is None
    assert cost.vlm_usd is None
    assert cost.total_usd_high is None
    assert cost.total_usd_low is not None
    assert cost.human_labeling_hours > 0


def test_wall_clock_separates_the_two_vision_backends() -> None:
    """The money is ~$7 whichever VLM runs; the clock is not. Keeping both numbers stops
    "the corpus costs seven dollars" from hiding a three-day run inside it."""
    cost = estimate_corpus_cost(plan_corpus())
    assert cost.extraction_hours_hosted_vlm < 2  # ~1 h for 217 videos, serial
    assert cost.extraction_hours_local_vlm > 48  # ~72 h for the same 217, serial
    assert cost.extraction_hours_local_vlm > 20 * cost.extraction_hours_hosted_vlm


def test_contact_sheet_subsamples_frames_for_the_vlm(tmp_path: Path) -> None:
    """The deterministic tier reads every frame (free); the VLM must not (not free).
    First and last are always kept so the sheet still spans the whole window."""
    from qualify_models.hooks.media import build_contact_sheet, select_evenly

    frames = [_write_frame(tmp_path / f"f{i}.jpg", (i * 20, 0, 0)) for i in range(9)]
    chosen = select_evenly(frames, 6)
    assert len(chosen) == 6
    assert chosen[0] == frames[0]
    assert chosen[-1] == frames[-1]

    sheet = build_contact_sheet(frames, tmp_path / "sheet.jpg", max_frames=4)
    assert sheet.n_frames == 4
    assert sheet.path.exists()


# --- Fase C: what the reachable corpus can honestly deliver ------------------------------


def test_three_accounts_is_measurement_only_not_a_smaller_inferential_study() -> None:
    """The measured reality of this niche on TikTok: 3 accounts, 711 videos. Videos are
    plentiful and accounts are not, and it is accounts that bind."""
    from qualify_models.hooks.corpus import (
        CorpusStudyKind,
        assess_corpus_feasibility,
        plan_corpus,
    )

    verdict = assess_corpus_feasibility(plan_corpus(), available_accounts=3, videos_available=711)
    assert verdict.kind is CorpusStudyKind.MEASUREMENT_ONLY
    assert verdict.supports_hook_performance_claim is False
    # Zero degrees of freedom: a hook type must appear in every account to count.
    assert verdict.accounts_margin == 0
    # It is still worth running — it settles the assumptions the real study rests on.
    assert any("rarest_type_share" in s for s in verdict.what_it_can_settle)
    assert any("variety" in s for s in verdict.what_it_can_settle)


def test_feasibility_never_lowers_the_plan_floor_to_fit_the_data() -> None:
    """Lowering `min_accounts` until the available corpus clears it is how a study
    manufactures a finding. The plan is what the question costs; it does not bend."""
    from qualify_models.hooks.corpus import assess_corpus_feasibility, plan_corpus

    plan = plan_corpus()
    verdict = assess_corpus_feasibility(plan, available_accounts=3, videos_available=711)
    assert verdict.plan_min_accounts == plan.min_accounts == 8


def test_enough_accounts_and_videos_is_inferential() -> None:
    from qualify_models.hooks.corpus import (
        CorpusStudyKind,
        assess_corpus_feasibility,
        plan_corpus,
    )

    verdict = assess_corpus_feasibility(plan_corpus(), available_accounts=8, videos_available=711)
    assert verdict.kind is CorpusStudyKind.INFERENTIAL
    assert verdict.supports_hook_performance_claim is True


def test_plenty_of_videos_cannot_rescue_too_few_accounts() -> None:
    """711 videos from one advertiser measure that advertiser's template. Corpus size does
    not substitute for account count, and the verdict must not let it."""
    from qualify_models.hooks.corpus import (
        CorpusStudyKind,
        assess_corpus_feasibility,
        plan_corpus,
    )

    verdict = assess_corpus_feasibility(
        plan_corpus(), available_accounts=1, videos_available=100_000
    )
    assert verdict.kind is CorpusStudyKind.NOT_VIABLE
    assert verdict.what_it_can_settle == []


# --- the metrics <-> features seam --------------------------------------------------------


def _write_csv(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_empty_cell_is_missing_and_zero_is_a_measured_zero(tmp_path: Path) -> None:
    """The other half of the corpus runner's guarantee. `float(x or 0)` collapses these
    two into the same number, and the collapse is invisible downstream because 0.0 is a
    perfectly valid value."""
    from qualify_models.hooks.join import optional_float

    assert optional_float("") is None
    assert optional_float("   ") is None
    assert optional_float(None) is None
    assert optional_float("0") == 0.0
    assert optional_float("0.0") == 0.0


def test_join_maps_blank_views_to_none_not_zero(tmp_path: Path) -> None:
    from qualify_models.hooks.join import join_observations

    metrics = _write_csv(
        tmp_path / "metrics.csv",
        "source_id,account_id,posted_at,likes,comments,views,duration_seconds",
        [
            "p1,acct,2026-07-26T14:03:00Z,8,1,750,59.0",
            "p2,acct,2026-07-22T09:00:00Z,2,0,,41.0",  # views unreported
            "p3,acct,2026-07-16T09:00:00Z,0,0,0,30.0",  # genuinely zero everything
        ],
    )
    features = _write_csv(
        tmp_path / "hook_features.csv",
        "source_id,window_seconds,hook_type",
        ["p1,3.0,question", "p2,3.0,price_reveal", "p3,3.0,question"],
    )

    result = join_observations(metrics, features, window_seconds=3.0)
    by_id = {o.source_id: o for o in result.observations}

    assert by_id["p1"].views == 750.0
    # Unreported: must NOT arrive as 0.0, which would rank it worst in its library.
    assert by_id["p2"].views is None
    # Measured zero: must survive as a real 0.0.
    assert by_id["p3"].views == 0.0
    assert by_id["p3"].engagement == 0.0


def test_unknown_engagement_component_makes_engagement_unknown(tmp_path: Path) -> None:
    """8 likes + unreported comments is not engagement 8. It is unknown engagement."""
    from qualify_models.hooks.join import join_observations

    metrics = _write_csv(
        tmp_path / "metrics.csv",
        "source_id,account_id,likes,comments,views",
        ["p1,acct,8,,750"],
    )
    features = _write_csv(
        tmp_path / "hook_features.csv",
        "source_id,window_seconds,hook_type",
        ["p1,3.0,question"],
    )
    obs = join_observations(metrics, features, window_seconds=3.0).observations[0]
    assert obs.engagement is None
    assert obs.views == 750.0


def test_missing_outcome_never_reaches_the_ranking(tmp_path: Path) -> None:
    """End-to-end: a post with no views must be dropped by the normalizer, not ranked."""
    from qualify_models.hooks.analysis import Outcome, normalized_outcomes
    from qualify_models.hooks.join import join_observations

    metrics = _write_csv(
        tmp_path / "metrics.csv",
        "source_id,account_id,likes,comments,views",
        ["p1,acct,8,1,750", "p2,acct,2,0,", "p3,acct,4,0,1200"],
    )
    features = _write_csv(
        tmp_path / "hook_features.csv",
        "source_id,window_seconds,hook_type",
        ["p1,3.0,question", "p2,3.0,question", "p3,3.0,question"],
    )
    result = join_observations(metrics, features, window_seconds=3.0)
    ranked = normalized_outcomes(result.observations, metric=Outcome.VIEWS)
    assert set(ranked) == {"p1", "p3"}
    assert "p2" not in ranked


def test_engagement_rate_needs_both_halves() -> None:
    from qualify_models.hooks.analysis import Outcome, PostObservation

    no_views = PostObservation(source_id="a", account_id="x", hook_type="question", engagement=5)
    assert no_views.outcome(Outcome.ENGAGEMENT_RATE) is None

    zero_views = PostObservation(
        source_id="b", account_id="x", hook_type="question", engagement=5, views=0
    )
    assert zero_views.outcome(Outcome.ENGAGEMENT_RATE) is None

    no_engagement = PostObservation(source_id="c", account_id="x", hook_type="question", views=100)
    assert no_engagement.outcome(Outcome.ENGAGEMENT_RATE) is None

    both = PostObservation(
        source_id="d", account_id="x", hook_type="question", engagement=5, views=100
    )
    assert both.outcome(Outcome.ENGAGEMENT_RATE) == pytest.approx(0.05)


def test_join_reports_what_did_not_join_instead_of_dropping_it_silently(tmp_path: Path) -> None:
    """A join that quietly halves the corpus is what makes an underpowered study look
    adequately powered."""
    from qualify_models.hooks.join import join_observations

    metrics = _write_csv(
        tmp_path / "metrics.csv",
        "source_id,account_id,likes,comments,views",
        ["p1,acct,8,1,750", "p2,acct,2,0,426"],
    )
    features = _write_csv(
        tmp_path / "hook_features.csv",
        "source_id,window_seconds,hook_type",
        ["p1,3.0,question", "p9,3.0,question"],
    )
    result = join_observations(metrics, features, window_seconds=3.0)

    assert len(result.observations) == 1
    assert result.missing_hook_features == ["p2"]
    assert result.missing_metrics == ["p9"]
    assert result.join_rate == pytest.approx(0.5)


def test_join_selects_the_requested_window_only(tmp_path: Path) -> None:
    from qualify_models.hooks.join import join_observations

    metrics = _write_csv(
        tmp_path / "metrics.csv", "source_id,account_id,likes,comments,views", ["p1,acct,8,1,750"]
    )
    features = _write_csv(
        tmp_path / "hook_features.csv",
        "source_id,window_seconds,hook_type",
        ["p1,3.0,question", "p1,7.0,price_reveal"],
    )
    assert join_observations(metrics, features, 3.0).observations[0].hook_type == "question"
    assert join_observations(metrics, features, 7.0).observations[0].hook_type == "price_reveal"


def test_posted_at_accepts_a_full_utc_timestamp(tmp_path: Path) -> None:
    """The runner writes yt-dlp's `timestamp` (full UTC), not date-only `upload_date`."""
    from qualify_models.hooks.join import parse_posted_at

    assert parse_posted_at("2026-07-26T14:03:00Z") == date(2026, 7, 26)
    assert parse_posted_at("2026-07-26T14:03:00+00:00") == date(2026, 7, 26)
    assert parse_posted_at("2026-07-26") == date(2026, 7, 26)
    assert parse_posted_at("") is None
    assert parse_posted_at("not-a-date") is None


def test_missing_required_column_fails_loudly(tmp_path: Path) -> None:
    from qualify_models.hooks.join import join_observations

    metrics = _write_csv(tmp_path / "metrics.csv", "source_id,likes,views", ["p1,8,750"])
    features = _write_csv(
        tmp_path / "hook_features.csv", "source_id,window_seconds,hook_type", ["p1,3.0,question"]
    )
    with pytest.raises(ValueError, match="account_id"):
        join_observations(metrics, features, window_seconds=3.0)


def test_absent_follower_count_stays_absent(tmp_path: Path) -> None:
    from qualify_models.hooks.join import load_follower_counts

    accounts = _write_csv(
        tmp_path / "accounts.csv",
        "account_id,handle,follower_count,fetched_at",
        ["a1,@one,5400,2026-08-06", "a2,@two,,2026-08-06"],
    )
    counts = load_follower_counts(accounts)
    assert counts == {"a1": 5400}
    assert "a2" not in counts


# --- is the observed variety usable, or is it drift? --------------------------------------


def _obs(source_id: str, hook: str, day: int, account: str = "acct") -> PostObservation:
    return PostObservation(
        source_id=source_id,
        account_id=account,
        hook_type=hook,
        engagement=10.0,
        views=500.0,
        posted_at=date(2026, 1, 1) + timedelta(days=day),
    )


def test_variety_that_is_really_drift_is_flagged_as_confounded() -> None:
    """An account that used `question` in its first era and `price_reveal` in its second
    shows two hook types in a frequency table and has NO usable variety: hook type is a
    proxy for date, and the recency adjustment would delete the effect with the trend."""
    from qualify_models.hooks.analysis import hook_temporal_separation

    observations = [_obs(f"a{i}", "question", i) for i in range(10)]
    observations += [_obs(f"b{i}", "price_reveal", 200 + i) for i in range(10)]

    verdict = hook_temporal_separation(observations)
    assert verdict.hook_type_is_confounded_with_time is True
    assert verdict.max_separation is not None and verdict.max_separation >= 0.5
    assert "standing in for date" in verdict.reasons[0]


def test_interleaved_hook_types_are_repertoire_not_drift() -> None:
    """The same two types alternating throughout the catalogue is usable variety."""
    from qualify_models.hooks.analysis import hook_temporal_separation

    observations = [
        _obs(f"p{i}", "question" if i % 2 == 0 else "price_reveal", i * 10) for i in range(20)
    ]
    verdict = hook_temporal_separation(observations)
    assert verdict.hook_type_is_confounded_with_time is False
    assert verdict.max_separation is not None and verdict.max_separation < 0.2
    assert "repertoire" in verdict.reasons[0]


def test_single_hook_type_yields_no_separation_rather_than_zero() -> None:
    """Nothing to separate is not the same as well mixed, and must not read as a pass."""
    from qualify_models.hooks.analysis import hook_temporal_separation

    verdict = hook_temporal_separation([_obs(f"p{i}", "question", i * 5) for i in range(8)])
    assert verdict.accounts[0].separation is None
    assert verdict.max_separation is None
    assert verdict.hook_type_is_confounded_with_time is False
    assert "cannot be assessed" in verdict.reasons[0]


def test_undated_posts_are_ignored_not_assumed_contemporaneous() -> None:
    from qualify_models.hooks.analysis import hook_temporal_separation

    observations = [_obs("p1", "question", 0), _obs("p2", "price_reveal", 100)]
    observations.append(
        PostObservation(source_id="p3", account_id="acct", hook_type="question", views=500.0)
    )
    verdict = hook_temporal_separation(observations)
    assert verdict.accounts[0].n_posts == 2


def test_separation_reports_the_span_actually_sampled() -> None:
    """The span is what makes a sampling strategy auditable after the fact: a 67-day span
    from a 1549-day catalogue is a recency sample whatever it was called."""
    from qualify_models.hooks.analysis import hook_temporal_separation

    verdict = hook_temporal_separation([_obs(f"p{i}", "question", i) for i in range(0, 70, 10)])
    assert verdict.accounts[0].span_days == 60
    assert verdict.accounts[0].earliest == date(2026, 1, 1)


def test_complete_segregation_of_two_balanced_types_is_exactly_the_ceiling() -> None:
    """Pins the arithmetic the threshold rests on: two equally-sized types splitting the
    timeline produce a separation of exactly 0.5, which is the MAXIMUM such an account can
    produce — not a midpoint. A threshold of 0.5 with a strict `>` could never fire for the
    case it exists to catch, which is how the first version of this was wrong."""
    from qualify_models.hooks.analysis import MAX_HOOK_TIME_SEPARATION, hook_temporal_separation

    observations = [_obs(f"a{i}", "question", i) for i in range(10)]
    observations += [_obs(f"b{i}", "price_reveal", 100 + i) for i in range(10)]
    verdict = hook_temporal_separation(observations)

    assert verdict.max_separation == pytest.approx(0.5)
    assert MAX_HOOK_TIME_SEPARATION < 0.5
    assert verdict.hook_type_is_confounded_with_time is True


# --- did the detrending actually work? -----------------------------------------------------


def _dated(source_id: str, day: int, views: float, account: str = "acct") -> PostObservation:
    return PostObservation(
        source_id=source_id,
        account_id=account,
        hook_type="question",
        views=views,
        posted_at=date(2022, 1, 1) + timedelta(days=day),
    )


def test_linear_growth_is_fully_detrended() -> None:
    from qualify_models.hooks.analysis import detrend_residual_check

    observations = [_dated(f"p{i}", i * 30, float(100 + i * 50)) for i in range(12)]
    check = detrend_residual_check(observations)
    assert check.detrending_worked is True
    assert check.max_era_gap is not None
    assert check.max_era_gap <= 0.2


def test_a_monotone_step_change_is_fully_absorbed_because_the_fit_is_on_ranks() -> None:
    """Pins the property that decides what this adjustment can do. The fit is linear **on
    ranks**, so ANY monotone trend — steady growth, or a one-off jump after a viral post —
    is perfectly linear in rank space and comes out completely. A step change is therefore
    NOT a counterexample, which is what an earlier version of this test got wrong."""
    from qualify_models.hooks.analysis import detrend_residual_check

    flat_then_jump = [_dated(f"a{i}", i * 30, 100.0 + i) for i in range(8)]
    flat_then_jump += [_dated(f"b{i}", 300 + i * 30, 5000.0 + i) for i in range(8)]

    check = detrend_residual_check(flat_then_jump)
    assert check.accounts_checked == 1
    assert check.max_era_gap == pytest.approx(0.0)
    assert check.detrending_worked is True


def test_non_monotone_drift_survives_linear_detrending_and_is_reported() -> None:
    """The failure the fit genuinely cannot see: an account that grew and then declined.
    In rank space that is a curve, a straight line barely touches it, and without this
    check the adjusted numbers would look corrected while still carrying the confounder.
    On a multi-year catalogue — exactly what full-catalogue spread sampling returns — this
    is the realistic shape."""
    from qualify_models.hooks.analysis import detrend_residual_check

    rise = [_dated(f"up{i}", i * 30, float(100 + i * 100)) for i in range(8)]
    fall = [_dated(f"dn{i}", 240 + i * 30, float(900 - i * 100)) for i in range(8)]

    check = detrend_residual_check(rise + fall)
    assert check.accounts_checked == 1
    assert check.max_era_gap is not None
    assert check.max_era_gap > 0.2
    assert check.detrending_worked is False
    assert "not linear in ranks" in check.reasons[0]


def test_detrend_check_is_honest_when_it_cannot_check() -> None:
    """Too few dated posts must not read as a clean bill of health by accident — it says
    so in `reasons` and reports zero accounts checked."""
    from qualify_models.hooks.analysis import detrend_residual_check

    check = detrend_residual_check([_dated("p1", 0, 100.0), _dated("p2", 30, 200.0)])
    assert check.accounts_checked == 0
    assert check.max_era_gap is None
    assert "could not be checked" in check.reasons[0]
    assert "Not evidence that it is absent" in check.reasons[0]


def test_span_shortfall_invalidates_a_negative_variety_finding_only() -> None:
    """Measured case: a run targeting 365 days came back with 98 because the picks at both
    ends failed. The asymmetry is the point — a hook type used only in the missing months
    is absent from the corpus and reads as 'this account does not vary'."""
    from qualify_models.hooks.analysis import hook_temporal_separation

    # 98 days of a requested 365, two hook types interleaved.
    observations = [
        _obs(f"p{i}", "question" if i % 2 == 0 else "price_reveal", i * 7) for i in range(15)
    ]
    verdict = hook_temporal_separation(observations, requested_span_days=365)

    assert verdict.min_span_coverage is not None
    assert verdict.min_span_coverage < 0.5
    assert verdict.negative_findings_interpretable is False
    assert any("NEGATIVE variety finding is not interpretable" in r for r in verdict.reasons)
    # The positive half still stands: variety was observed, so variety exists.
    assert verdict.hook_type_is_confounded_with_time is False


def test_full_span_coverage_leaves_negatives_interpretable() -> None:
    from qualify_models.hooks.analysis import hook_temporal_separation

    observations = [
        _obs(f"p{i}", "question" if i % 2 == 0 else "price_reveal", i * 25) for i in range(15)
    ]
    verdict = hook_temporal_separation(observations, requested_span_days=365)
    assert verdict.min_span_coverage is not None
    assert verdict.min_span_coverage >= 0.5
    assert verdict.negative_findings_interpretable is True


def test_no_requested_span_means_no_coverage_claim_either_way() -> None:
    """Without knowing what was asked for, coverage is unknown — not assumed complete."""
    from qualify_models.hooks.analysis import hook_temporal_separation

    verdict = hook_temporal_separation([_obs(f"p{i}", "question", i * 7) for i in range(10)])
    assert verdict.min_span_coverage is None
    assert verdict.negative_findings_interpretable is True


# --- guards must be shown to FIRE, not merely to be present ---------------------------------
#
# Audit prompted by a pattern that showed up four times in one day across two packages:
# `int(x or 0)` collapsing a missing metric to zero, a `> 0.5` threshold on a statistic whose
# maximum is 0.5, a Spearman check against a symmetric U it reads as ~0, and recency sampling
# where a span was wanted. Every one was a guard aimed at the right hazard and positioned
# where it could never trigger, and every one was found by something other than the suite
# covering it.
#
# Applying the lesson here found the same shape: `CorrelationReport.conclusive` and
# `HookTypeEffect.separates_from_chance` were only ever asserted FALSE. Had either been
# wired so it could never return True, nothing would have failed. These tests make them fire.


def _effect_corpus(n_accounts: int, n_per_type: int) -> list[PostObservation]:
    """A corpus where `question` genuinely outranks `direct_claim` inside every account."""
    observations: list[PostObservation] = []
    for account in range(n_accounts):
        for i in range(n_per_type):
            observations.append(
                PostObservation(
                    source_id=f"a{account}-q{i}",
                    account_id=f"acct{account}",
                    hook_type="question",
                    views=float(1000 + i),
                )
            )
            observations.append(
                PostObservation(
                    source_id=f"a{account}-d{i}",
                    account_id=f"acct{account}",
                    hook_type="direct_claim",
                    views=float(100 + i),
                )
            )
    return observations


def test_conclusive_can_actually_be_true_when_an_effect_exists() -> None:
    """The positive path of the whole Fase D gate. Without this, a `conclusive` wired so it
    could never return True would pass every other test in this file."""
    from qualify_models.hooks.analysis import Outcome, hook_type_effects

    report = hook_type_effects(_effect_corpus(4, 40), metric=Outcome.VIEWS)

    assert report.conclusive is True
    assert report.n_accounts == 4
    winner = next(e for e in report.effects if e.hook_type == "question")
    assert winner.meets_min_posts is True
    assert winner.meets_min_accounts is True
    assert winner.separates_from_chance is True
    assert winner.median_outcome > 0.5
    # Still never a causal claim, however clean the separation.
    assert report.causal_claim_supported is False


def test_separates_from_chance_is_false_when_the_interval_straddles_the_middle() -> None:
    """The other half of the same guard: an interval containing 0.5 is a non-finding
    however pretty the point estimate."""
    from qualify_models.hooks.analysis import HookTypeEffect

    straddling = HookTypeEffect(
        hook_type="question",
        n_posts=40,
        n_accounts=4,
        median_outcome=0.62,
        ci_low=0.41,
        ci_high=0.78,
        meets_min_posts=True,
        meets_min_accounts=True,
    )
    assert straddling.separates_from_chance is False

    clear = straddling.model_copy(update={"ci_low": 0.56, "ci_high": 0.79})
    assert clear.separates_from_chance is True


def test_an_effect_in_one_account_only_never_becomes_conclusive() -> None:
    """The house-style guard, fired. A huge, perfectly clean effect inside a single account
    must not license a claim — that is one advertiser's habit, not a pattern."""
    from qualify_models.hooks.analysis import Outcome, hook_type_effects

    report = hook_type_effects(_effect_corpus(1, 200), metric=Outcome.VIEWS)
    assert report.conclusive is False
    winner = next(e for e in report.effects if e.hook_type == "question")
    assert winner.meets_min_posts is True  # plenty of posts...
    assert winner.meets_min_accounts is False  # ...from one account
    assert winner.separates_from_chance is True  # ...and a clean interval


def test_tie_guard_fires_on_small_integer_likes() -> None:
    """`MAX_TIE_FRACTION` shown firing, not merely present."""
    from qualify_models.hooks.analysis import Outcome, assess_viability

    tied = [
        PostObservation(
            source_id=f"p{i}",
            account_id="acct",
            hook_type="question" if i % 2 else "direct_claim",
            engagement=float(2 + (i % 3)),
        )
        for i in range(30)
    ]
    verdict = assess_viability(tied, metric=Outcome.ENGAGEMENT)
    assert verdict.viable is False
    assert verdict.median_tie_fraction > 0.5
    assert any("mostly ties" in r for r in verdict.reasons)


def test_noise_floor_fires_when_a_trend_explains_the_library_completely() -> None:
    """`_RESIDUAL_NOISE_FLOOR` shown firing: perfectly linear growth must flatten to 0.5
    everywhere, not become a full-range ranking of floating-point dust."""
    from qualify_models.hooks.analysis import Normalization, Outcome, normalized_outcomes

    observations = [_dated(f"p{i}", i * 30, float(100 + i * 50)) for i in range(12)]
    adjusted = normalized_outcomes(
        observations, metric=Outcome.VIEWS, normalization=Normalization.RECENCY_ADJUSTED
    )
    assert set(adjusted.values()) == {0.5}


# --- the real corpus file, not my idea of it ------------------------------------------------

REAL_CORPUS = Path(__file__).resolve().parents[2] / "scraper" / "tests" / "fixtures" / "corpus"

real_corpus = pytest.mark.skipif(
    not (REAL_CORPUS / "metrics.csv").exists(),
    reason="scraper corpus fixture not present",
)


@real_corpus
def test_real_metrics_file_has_the_contracted_columns() -> None:
    """Synthesized rows test MY reading of the runner's format, not the runner's format.
    This points at the file the runner actually produced (10 real posts from two Cucuta
    accounts, harvested 2026-08-06), so a renamed column fails here rather than at pilot
    time."""
    import csv as _csv

    with (REAL_CORPUS / "metrics.csv").open(encoding="utf-8") as handle:
        reader = _csv.DictReader(handle)
        assert reader.fieldnames == [
            "source_id",
            "account_id",
            "posted_at",
            "likes",
            "comments",
            "views",
            "duration_seconds",
            "fetched_at",
            "video_path",
        ]
        assert len(list(reader)) == 10


@real_corpus
def test_real_metrics_join_end_to_end(tmp_path: Path) -> None:
    from qualify_models.hooks.join import join_observations

    metrics = REAL_CORPUS / "metrics.csv"
    import csv as _csv

    with metrics.open(encoding="utf-8") as handle:
        rows = list(_csv.DictReader(handle))

    features = _write_csv(
        tmp_path / "hook_features.csv",
        "source_id,window_seconds,hook_type",
        [
            f"{row['source_id']},3.0,{'question' if i % 2 == 0 else 'price_reveal'}"
            for i, row in enumerate(rows)
        ],
    )

    result = join_observations(metrics, features, window_seconds=3.0)
    assert len(result.observations) == 10
    assert result.join_rate == pytest.approx(1.0)
    assert result.missing_hook_features == []

    # Real values, decoded through the real contract.
    first = next(o for o in result.observations if o.source_id == "7666950720377097479")
    assert first.views == 750.0
    assert first.engagement == 8.0  # 8 likes + 0 comments, a genuine zero
    assert first.posted_at == date(2026, 7, 26)
    assert first.duration_seconds == 59.0


@real_corpus
def test_real_accounts_file_has_no_follower_counts_and_that_is_correct() -> None:
    """`follower_count` is blank in both rows because yt-dlp cannot supply it. The loader
    must leave it absent rather than inventing a 0, which would be a per-account covariate
    of exactly zero followers."""
    from qualify_models.hooks.join import load_follower_counts

    assert load_follower_counts(REAL_CORPUS / "accounts.csv") == {}


@real_corpus
def test_real_corpus_shows_why_ranking_happens_inside_an_account(tmp_path: Path) -> None:
    """The strongest empirical support the design has received. Across the two real
    accounts views differ by ~40x (10-21 against 426-12800), and one account carries a
    single 12800 post against a ~600 baseline. Pooled, account 1 would determine every
    result; ranked within accounts, both contribute on equal terms — and the median-plus-
    bootstrap choice keeps the one viral post from becoming a general finding."""
    from qualify_models.hooks.analysis import Normalization, Outcome, normalized_outcomes
    from qualify_models.hooks.join import join_observations

    metrics = REAL_CORPUS / "metrics.csv"
    import csv as _csv

    with metrics.open(encoding="utf-8") as handle:
        rows = list(_csv.DictReader(handle))
    features = _write_csv(
        tmp_path / "hook_features.csv",
        "source_id,window_seconds,hook_type",
        [f"{row['source_id']},3.0,question" for row in rows],
    )
    observations = join_observations(metrics, features, window_seconds=3.0).observations

    raw = normalized_outcomes(observations, Outcome.VIEWS, Normalization.RAW)
    within = normalized_outcomes(observations, Outcome.VIEWS, Normalization.WITHIN_ACCOUNT)

    small_account = "MS4wLjABAAAACAiinXzfGN_3JjEiwrLvctWSPdMQO5c30jN6gSnAGvzRvvW0ERqH0XY2KufxoDrX"
    small_ids = [o.source_id for o in observations if o.account_id == small_account]
    big_ids = [o.source_id for o in observations if o.account_id != small_account]

    # Pooled: every post of the big account beats every post of the small one.
    assert min(raw[i] for i in big_ids) > max(raw[i] for i in small_ids)
    # Within-account: the small account's best post outranks the big account's worst.
    assert max(within[i] for i in small_ids) > min(within[i] for i in big_ids)
