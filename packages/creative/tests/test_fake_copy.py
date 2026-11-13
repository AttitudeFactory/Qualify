"""The E2E's copy writer (m-24955929): `QUALIFY_COPY_FAKE=1` — test-only, no paid call.

Pins: off by default; refused in production; a fixed Spanish copy in the copy slot
(`anthropic`), zero cost.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from qualify_creative.adapters.fake_copy import (
    FAKE_COPY_ENV,
    FakeCopyAdapter,
    FakeCopyRefused,
    fake_copy_enabled,
)
from qualify_creative.enums import GenerationTask


def test_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv(FAKE_COPY_ENV, raising=False)
    assert fake_copy_enabled() is False


def test_on_only_with_1_and_never_in_production(monkeypatch) -> None:
    monkeypatch.delenv("QUALIFY_DEPLOY_ENV", raising=False)
    monkeypatch.setenv(FAKE_COPY_ENV, "yes")
    assert fake_copy_enabled() is False
    monkeypatch.setenv(FAKE_COPY_ENV, "1")
    assert fake_copy_enabled() is True
    monkeypatch.setenv("QUALIFY_DEPLOY_ENV", "production")
    with pytest.raises(FakeCopyRefused):
        fake_copy_enabled()


def test_a_fixed_copy_at_no_cost() -> None:
    adapter = FakeCopyAdapter()
    assert adapter.name == "anthropic" and GenerationTask.COPY in adapter.supports
    result = adapter.generate(object(), api_key="anything")
    assert set(result.payload) == {"hook", "caption", "hashtags", "cta"}
    assert result.usage.input_tokens == 0 and result.usage.output_tokens == 0
    assert result.model_revision == "fake-copy-e2e"  # provenance: never the real model
    assert adapter.estimate_cost_usd(object(), object()) == Decimal("0")
