from qualify_models.schemas import FilterResult


def test_filter_result_carries_provenance() -> None:
    result = FilterResult(
        source_id="post_123",
        detector_version="siglip2-base-patch16-224-v1",
        pipeline_version="0.1.0",
        labels=["brand logo"],
        scores=[0.9],
        passed=True,
        threshold=0.22,
    )
    assert result.source_id == "post_123"
    assert result.passed is True
