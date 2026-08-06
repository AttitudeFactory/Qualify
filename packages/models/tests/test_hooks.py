"""Tests for the hook-pattern spike.

Everything here is offline: no network, no model weights. The one end-to-end test runs
the real extractor over the real fixture mp4 with fake providers, which is what proves
the plumbing works without paying for it.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from qualify_models.hooks.analysis import (
    CONFOUNDERS,
    Normalization,
    Outcome,
    PostObservation,
    bonferroni_alpha,
    hook_type_effects,
    inverse_normal_cdf,
    minimum_n_for_correlation,
    minimum_n_per_group,
    normalized_outcomes,
    spearman_rho,
)
from qualify_models.hooks.corpus import estimate_corpus_cost, plan_corpus
from qualify_models.hooks.lexical import analyze_speech, classify_lexical
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
