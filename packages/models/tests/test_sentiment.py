from qualify_models.sentiment import run_sentiment


def test_run_sentiment_on_spanish_text() -> None:
    result = run_sentiment(
        "Me encanta este producto, la verdad superó mis expectativas!",
        source_id="comment_1",
        pipeline_version="0.1.0",
    )
    assert result.label in {"POS", "NEG", "NEU"}
    assert 0.0 <= result.score <= 1.0
