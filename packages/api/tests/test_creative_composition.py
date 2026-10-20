"""The production composition root wires the template engine (plan §2): the Remotion
adapter is a provider of the router AND the media producer's engine, the published
manifests are loaded, and the brand-name / catalog readers are attached. This exact
wiring was lost once on the way to main (2026-10-05) while every unit test stayed green,
because they all use fakes — hence a test on the real composition, with no network and
no database touched (constructing the readers opens nothing)."""

from __future__ import annotations

import pytest
from qualify_creative.render.adapter import RemotionTemplateAdapter
from qualify_creative.render.registry import TemplateRegistry

from qualify_api.creative import composition


@pytest.fixture
def fresh_service(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(composition.RENDER_URL_ENV, "http://render.test:3200")
    composition.production_content_service.cache_clear()
    try:
        yield composition.production_content_service()
    finally:
        composition.production_content_service.cache_clear()


def test_production_service_wires_the_remotion_template_engine(fresh_service) -> None:
    media = fresh_service._media
    assert media is not None
    assert isinstance(media._remotion, RemotionTemplateAdapter)
    assert isinstance(media._templates, TemplateRegistry)
    assert media._brand_names is not None and media._catalog is not None
    # the render client points at the configured service
    assert media._remotion._client._base == "http://render.test:3200"
    # and the router knows the engine by the adapter's name
    assert "remotion" in fresh_service._router._providers
    assert fresh_service._router._providers["remotion"] is media._remotion


@pytest.mark.parametrize(
    ("model", "resolution", "match"),
    [
        ("dreamina-seedance-2-0-fast-260128", "1080p", "is not one"),
        ("seedance-1-0-pro-250528", "720", "is not one"),
        ("seedance-9-9", "720p", "unknown Seedance model"),
    ],
)
def test_a_seedance_pair_the_family_cannot_render_fails_at_wiring(
    monkeypatch: pytest.MonkeyPatch, model: str, resolution: str, match: str
) -> None:
    """PR #100 review: not at every generation's pre-flight while the service came up."""
    monkeypatch.setenv(composition.SEEDANCE_MODEL_ENV, model)
    monkeypatch.setenv(composition.SEEDANCE_RESOLUTION_ENV, resolution)
    composition.production_content_service.cache_clear()
    try:
        with pytest.raises(ValueError, match=match):
            composition.production_content_service()
    finally:
        composition.production_content_service.cache_clear()


def test_the_published_manifests_load_from_the_repo(fresh_service) -> None:
    registry = fresh_service._media._templates
    # v2 (2026-10-13): the 9:16 / 4:5 / 1:1 video and the three stills
    assert registry.get("promo_producto").render_count == 6
    assert registry.get("promo_producto", 1).render_count == 3


def _ark(service, name: str):
    provider = service._router._providers[name]
    return getattr(provider, "inner", provider)


def test_without_endpoints_the_ark_adapters_refuse_every_model(monkeypatch, fresh_service) -> None:
    """m-24820898: production never falls back to a bare model id — the preset authorized
    for BytePlus's data collection — and there is no env switch that would allow it."""
    from qualify_creative.adapters import ArkPresetRefused

    monkeypatch.delenv(composition.ARK_ENDPOINTS_ENV, raising=False)
    for name in ("seedream", "seedance"):
        adapter = _ark(fresh_service, name)
        assert adapter.allow_presets is False
        with pytest.raises(ArkPresetRefused):
            adapter.wire_model(adapter.model)


def test_the_configured_endpoints_reach_both_ark_adapters(monkeypatch) -> None:
    from qualify_creative.adapters.byteplus_ark import (
        DEFAULT_SEEDANCE_MODEL,
        DEFAULT_SEEDREAM_MODEL,
    )

    monkeypatch.setenv(composition.RENDER_URL_ENV, "http://render.test:3200")
    monkeypatch.setenv(
        composition.ARK_ENDPOINTS_ENV,
        f"{DEFAULT_SEEDREAM_MODEL}=ep-img,{DEFAULT_SEEDANCE_MODEL}=ep-vid,"
        f"{composition.DEFAULT_SEEDANCE_REFERENCE_MODEL}=ep-ref",
    )
    composition.production_content_service.cache_clear()
    try:
        service = composition.production_content_service()
        assert _ark(service, "seedream").wire_model(DEFAULT_SEEDREAM_MODEL) == "ep-img"
        seedance = _ark(service, "seedance")
        assert seedance.wire_model(DEFAULT_SEEDANCE_MODEL) == "ep-vid"
        # the clip-with-references model rides the same map
        assert seedance.wire_model(composition.DEFAULT_SEEDANCE_REFERENCE_MODEL) == "ep-ref"
    finally:
        composition.production_content_service.cache_clear()


def test_a_malformed_endpoint_list_fails_at_wiring(monkeypatch) -> None:
    monkeypatch.setenv(composition.ARK_ENDPOINTS_ENV, "seedream-5-0-lite-260128")
    composition.production_content_service.cache_clear()
    try:
        with pytest.raises(ValueError, match="model=ep-"):
            composition.production_content_service()
    finally:
        composition.production_content_service.cache_clear()
