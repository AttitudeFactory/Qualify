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


def test_the_published_manifests_load_from_the_repo(fresh_service) -> None:
    registry = fresh_service._media._templates
    assert registry.get("promo_producto").render_count == 3
