"""Catalog carousel (m-25113484) against real RLS: products are read through the Catálogo
under the tenant's session, the approval is stored without a piece, and nothing leaks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from packages.api.tests.test_ad_audience_db import audience_world as shared_audience_world
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.ads.carousel import CAROUSEL_PIPELINE
from qualify_api.ads.unpublished import ImageAdForm, UnpublishedUnavailable
from qualify_api.ads.unpublished_repository import (
    UnpublishedRepository,
    guard_source,
    load_carousel_source,
)
from qualify_api.catalog.models import BrandProduct, ProductMedia
from qualify_api.tenancy.acting import acting_login

pytestmark = pytest.mark.db
audience_world = shared_audience_world


def _product(tenant, brand, name, price):
    product, media = uuid4(), uuid4()
    with tenant_session(tenant) as session:
        session.add(
            BrandProduct(
                id=product,
                tenant_id=tenant,
                brand_id=brand,
                name=name,
                slug=f"p-{product}",
                price_amount=Decimal(price),
                price_currency="COP",
            )
        )
        session.flush()
        session.add(
            ProductMedia(
                id=media,
                tenant_id=tenant,
                brand_id=brand,
                product_id=product,
                media_type="image",
                object_key=f"t/{tenant}/uploads/catalog/{product}/photo.jpg",
                content_type="image/jpeg",
                width=1080,
                height=1080,
                is_primary=True,
            )
        )
    return product


def test_carousel_source_reads_the_catalog_and_stores_an_approval_without_piece(
    audience_world,
):
    ids, login, actor, _connection, brand = audience_world
    tenant, account = ids["tenant_id"], ids["ad_account_id"]
    first = _product(tenant, brand, "Shawarma mixto", "12000")
    second = _product(tenant, brand, "Ensalada", "9500.50")
    cards = ((first, "https://example.org/a"), (second, "https://example.org/b"))
    now = datetime.now(UTC)
    form = ImageAdForm(
        "Texto",
        "Título",
        "https://example.org",
        100_00,
        now + timedelta(days=1),
        now + timedelta(days=2),
        "CO",
    )
    with acting_login(login):
        source = load_carousel_source(tenant, account, cards)
        assert [card.title for card in source.cards] == [
            "Shawarma mixto · $12.000",
            "Ensalada · $9.500,50",
        ]
        with pytest.raises(UnpublishedUnavailable, match="ya no está"):
            load_carousel_source(tenant, account, ((first, "https://x.org"), (uuid4(), "")))
        with pytest.raises(UnpublishedUnavailable, match="entre 2 y 10"):
            load_carousel_source(tenant, account, cards[:1])
        recipe = UnpublishedRepository().approve(source, form, actor, uuid4())
        assert recipe["draft_id"] is None and recipe["pipeline_version"] == CAROUSEL_PIPELINE
        with tenant_session(tenant) as session:
            session.execute(
                text("UPDATE brand_products SET price_amount=13000 WHERE id=:id"), {"id": first}
            )
        with pytest.raises(UnpublishedUnavailable):
            guard_source(source)
    with tenant_session(uuid4()) as session:
        assert session.scalar(text("SELECT count(*) FROM ad_unpublished_sources")) == 0
    # Only the carousel pipeline may skip the piece.
    with pytest.raises(IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text("""INSERT INTO ad_unpublished_sources
          (tenant_id,brand_id,connection_id,ad_account_id,request_key,request_hash,source,form,
           approved_by) SELECT tenant_id,brand_id,connection_id,ad_account_id,gen_random_uuid(),
           'x','{}','{}',approved_by FROM ad_unpublished_sources WHERE id=:id"""),
            {"id": recipe["id"]},
        )


def test_carousel_promotion_has_results_and_pause_scope(audience_world):
    """A carousel has no piece: results, pause and edits find it through its approval."""
    from qualify_api.ads import results_service as service
    from qualify_api.ads.carousel import carousel_payload
    from qualify_api.ads.enhancements import BrandEnhancementSettings, compose_brand_policy
    from qualify_api.ads.promotion_repository import PostgresPromotionRepository
    from qualify_api.ads.promotions import STEPS, PromotionRequest, step_payload
    from qualify_api.ads.results import ResultsUnavailable

    ids, login, actor, _connection, brand = audience_world
    tenant, account = ids["tenant_id"], ids["ad_account_id"]
    cards = (
        (_product(tenant, brand, "Uno", "1000"), "https://example.org/a"),
        (_product(tenant, brand, "Dos", "2000"), "https://example.org/b"),
    )
    now = datetime.now(UTC)
    form = ImageAdForm(
        "Texto",
        "Título",
        "https://example.org",
        100_00,
        now + timedelta(days=1),
        now + timedelta(days=2),
        "CO",
    )
    promotions = PostgresPromotionRepository()

    def promotion_for(source_media_id, recipe):
        request = compose_brand_policy(
            PromotionRequest(
                tenant,
                source.brand_id,
                str(uuid4()),
                source.meta_account_id,
                "OUTCOME_TRAFFIC",
                "LEARN_MORE",
                form.link_url,
                "lifetime",
                form.budget_minor,
                "COP",
                form.start_time,
                form.end_time,
                actor,
                recipe["approved_at"],
                source_media_id=source_media_id,
                card_links=("https://example.org/a", "https://example.org/b"),
                creative=carousel_payload(source, form, ("hash1", "hash2")),
            ),
            BrandEnhancementSettings(tenant, source.brand_id),
        )
        promotion = promotions.create_or_get(request)
        repo.link(tenant, recipe["id"], promotion.id)
        for resource in STEPS:
            token = uuid4()
            promotion = promotions.get(tenant, promotion.id)
            assert promotions.claim(
                tenant, promotion.id, resource, step_payload(promotion, resource), token
            )
            assert promotions.complete(tenant, promotion.id, resource, token, str(uuid4().int))
        return promotion

    repo = UnpublishedRepository()
    with acting_login(login):
        source = load_carousel_source(tenant, account, cards)
        recipe = repo.approve(source, form, actor, uuid4())
        promotion = promotion_for(f"catalog-carousel:{recipe['id']}", recipe)
        scope = service._scope(tenant, promotion.id)
        assert scope.connection.connection_id == source.connection_id
        assert service.load_promotion_results(tenant_id=tenant, promotion_id=promotion.id)
        _, state = service._claim_pause(scope, "carousel-pause", datetime.now(UTC))
        assert state == "claimed"
        # Provenance must name THIS approval: another approval's id finds no scope.
        other = repo.approve(source, form, actor, uuid4())
        stray = promotion_for(f"catalog-carousel:{recipe['id']}", other)
        with pytest.raises(ResultsUnavailable):
            service._scope(tenant, stray.id)
