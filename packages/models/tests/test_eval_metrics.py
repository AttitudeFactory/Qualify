from qualify_models.eval.metrics import filter_metrics, sentiment_accuracy, transcription_wer


def test_filter_metrics_known_confusion() -> None:
    # predicted vs truth: TP, FP, FN, TN respectively.
    result = filter_metrics(predicted=[True, True, False, False], truth=[True, False, True, False])
    assert (result.true_positives, result.false_positives) == (1, 1)
    assert (result.false_negatives, result.true_negatives) == (1, 1)
    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.f1 == 0.5
    assert result.support == 4


def test_filter_metrics_no_positive_predictions() -> None:
    result = filter_metrics(predicted=[False, False], truth=[True, False])
    assert result.precision == 0.0
    assert result.recall == 0.0
    assert result.f1 == 0.0


def test_sentiment_accuracy_case_insensitive() -> None:
    result = sentiment_accuracy(predicted=["POS", "neg", "NEU"], truth=["POS", "NEG", "POS"])
    assert result.correct == 2
    assert result.total == 3
    assert result.accuracy == 2 / 3


def test_transcription_wer_single_substitution() -> None:
    # 1 substituted word out of 6 reference words.
    result = transcription_wer(
        hypotheses=["the cat sat on a mat"], references=["the cat sat on the mat"]
    )
    assert result.n_pairs == 1
    assert result.n_skipped_empty_reference == 0
    assert abs(result.wer - 1 / 6) < 1e-9


def test_transcription_wer_normalizes_case_and_punctuation() -> None:
    result = transcription_wer(hypotheses=["Hola, que tal!"], references=["hola que tal"])
    assert result.wer == 0.0


def test_transcription_wer_skips_empty_reference() -> None:
    result = transcription_wer(hypotheses=["anything"], references=[""])
    assert result.n_pairs == 0
    assert result.n_skipped_empty_reference == 1
    assert result.wer == 0.0
