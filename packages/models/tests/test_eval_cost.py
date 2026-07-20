from qualify_models.eval.cost import estimate_cost


def test_default_cost_leaves_total_unresolved() -> None:
    cost = estimate_cost()
    assert cost.total_usd_per_video is None
    assert cost.total_usd_per_1k_videos is None
    stages = {s.stage: s for s in cost.stages}
    assert stages["vision"].documented is False
    assert stages["transcription"].documented is False
    assert stages["filter"].documented is True
    assert any("VLM" in c for c in cost.caveats)


def test_cost_totals_when_dominant_rates_supplied() -> None:
    cost = estimate_cost(vlm_usd_per_video=0.01, asr_usd_per_video=0.002)
    assert cost.total_usd_per_video == 0.012
    assert cost.total_usd_per_1k_videos == 12.0
    stages = {s.stage: s for s in cost.stages}
    assert stages["vision"].usd_per_video == 0.01
    assert stages["transcription"].usd_per_video == 0.002
