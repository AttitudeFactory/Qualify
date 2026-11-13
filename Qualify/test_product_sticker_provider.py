"""«Tu producto en sticker» gateway (m-25017372): the cost words are creaciones, never money,
and the backend's rows become the cards the screens draw. The services are faked."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from Qualify.product_sticker_provider import (
    ProductionProductStickerGateway,
    cost_texts,
)

TENANT = uuid4()
BRAND = uuid4()
PRODUCT = uuid4()


def test_the_cost_is_said_in_creaciones() -> None:
    assert cost_texts(1, 12, False) == (
        "Este dibujo usa 1 creación. Te quedan 12 este mes.",
        "Crear dibujo · 1 creación",
    )
    assert cost_texts(1, 1, False)[0].endswith("Te queda 1 este mes.")
    assert cost_texts(2, None, True) == (
        "Este dibujo usa 2 creaciones.",
        "Crear dibujo · 2 creaciones",
    )
    for text in cost_texts(1, 3, False):
        assert "US$" not in text and "$" not in text


class FakeService:
    def __init__(self) -> None:
        self.character_id = uuid4()

    def quote(self, tenant_id: UUID, brand_id: UUID) -> Any:
        return SimpleNamespace(creations=1, left=0, unlimited=False, can_pay=False, message="x")

    def products(self, tenant_id: UUID, brand_id: UUID) -> Any:
        return SimpleNamespace(
            products=[SimpleNamespace(product_id=PRODUCT, name="Shawarma", object_key=None)],
            without_photo=3,
        )

    def last_product(self, tenant_id: UUID, brand_id: UUID) -> Any:
        return None

    def characters(
        self, tenant_id: UUID, brand_id: UUID, product_id: Any = None, **_: Any
    ) -> list[Any]:
        return [
            SimpleNamespace(
                id=self.character_id,
                product_id=PRODUCT,
                product_name="Shawarma",
                status="failed",
                object_key=None,
                failure_text="Este dibujo no salió y no se te cobró. Puedes pedir otro.",
                created_at=datetime(2026, 11, 12, tzinfo=UTC),
            )
        ]

    def stickers(self, tenant_id: UUID, brand_id: UUID) -> list[Any]:
        return [
            SimpleNamespace(
                id=uuid4(),
                source_ref=f"{self.character_id}:En camino",
                recipe="k-quieto",
                status="ready",
                object_key=None,
                fail_reason=None,
            )
        ]


def test_cards_carry_status_words_and_alt_text() -> None:
    gateway = ProductionProductStickerGateway(service=FakeService(), library=object())
    cost = gateway.cost(TENANT, BRAND)
    assert not cost.can_pay and cost.message == "x" and cost.button_label.startswith("Crear")
    step = gateway.products(TENANT, BRAND)
    assert step.preselected == str(PRODUCT) and step.without_photo == 3
    (card,) = gateway.characters(TENANT, BRAND)
    assert card.status == "failed" and "no se te cobró" in card.failure_text
    (sticker,) = gateway.stickers(TENANT, BRAND)
    assert sticker.message == "En camino" and not sticker.animated
    assert sticker.alt == "Sticker quieto de Shawarma que dice En camino"
