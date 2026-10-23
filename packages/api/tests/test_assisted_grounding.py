"""`qualify_api.assisted` (m-24789645, Fase B · PR 1): the grounding shared by DM and
public comment drafts carries provenance, old stored records still read back, and the
names moved out of `conversations` are the very same objects there."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from qualify_api.assisted import (
    ApprovalRequired,
    GroundedProduct,
    Grounding,
    HumanApproval,
    grounding_from_products,
)

PRODUCT = UUID("44444444-4444-4444-8444-444444444444")
UPDATED = datetime(2026, 10, 20, 15, 30, tzinfo=UTC)


def test_as_record_carries_each_products_source() -> None:
    g = grounding_from_products(
        "Polet",
        [
            {
                "product_id": PRODUCT,
                "name": "Helado de yogur con fresas",
                "price_label": "$4.5",
                "price_amount": Decimal("4.50"),
                "currency": "USD",
                "category": "helados",
                "description": "Con granola",
                "updated_at": UPDATED,
            }
        ],
    )

    assert g.as_record() == {
        "business_name": "Polet",
        "products": [
            {
                "product_id": str(PRODUCT),
                "name": "Helado de yogur con fresas",
                "price": "$4.5",
                "price_amount": "4.50",
                "currency": "USD",
                "category": "helados",
                "updated_at": UPDATED.isoformat(),
            }
        ],
    }


def test_the_prompt_never_shows_ids_or_timestamps() -> None:
    g = Grounding(
        "Polet",
        (GroundedProduct("Taro", "$4.5", product_id=PRODUCT, updated_at=UPDATED),),
    )
    prompt = g.as_prompt()
    assert "Taro — $4.5" in prompt
    assert str(PRODUCT) not in prompt
    assert "2026-10-20" not in prompt


def test_a_record_round_trips() -> None:
    original = Grounding(
        "Polet",
        (
            GroundedProduct(
                "Taro",
                "$4.5",
                "bebidas",
                product_id=PRODUCT,
                price_amount=Decimal("4.50"),
                currency="USD",
                updated_at=UPDATED,
            ),
        ),
    )
    back = Grounding.from_record(original.as_record())
    assert back.business_name == "Polet"
    (p,) = back.products
    assert (p.product_id, p.price_amount, p.currency, p.updated_at) == (
        PRODUCT,
        Decimal("4.50"),
        "USD",
        UPDATED,
    )
    assert (p.name, p.price_label, p.category) == ("Taro", "$4.5", "bebidas")


def test_an_old_record_without_ids_still_reads() -> None:
    """Every `conversation_reply_drafts.grounding` written before this change looks like
    this (plus merged keys like `unsupported_claims`): it must still render."""
    old = {
        "business_name": "Bianki",
        "products": [{"name": "Gorra", "price": "$12", "category": "ropa"}],
        "unsupported_claims": ["envíos"],
        "followup_id": str(uuid4()),
    }
    g = Grounding.from_record(old)
    assert g.business_name == "Bianki"
    (p,) = g.products
    assert (p.name, p.price_label, p.category) == ("Gorra", "$12", "ropa")
    assert p.product_id is None and p.updated_at is None and p.price_amount is None
    assert p.currency == ""


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"products": "nope"},
        {"products": [{"name": "  "}, "x", {"name": "Ok", "product_id": "not-a-uuid"}]},
        {"products": [{"name": "Ok", "updated_at": "ayer", "price_amount": "doce"}]},
    ],
)
def test_from_record_never_raises_on_malformed_input(record: object) -> None:
    g = Grounding.from_record(record)  # type: ignore[arg-type]
    for p in g.products:
        assert p.name == "Ok"
        assert p.product_id is None and p.updated_at is None and p.price_amount is None


def test_the_names_moved_out_of_conversations_are_the_same_objects() -> None:
    from qualify_api.conversations import outbox, suggest

    assert suggest.Grounding is Grounding
    assert suggest.GroundedProduct is GroundedProduct
    assert suggest.grounding_from_products is grounding_from_products
    assert outbox.HumanApproval is HumanApproval
    assert outbox.ApprovalRequired is ApprovalRequired


def test_human_approval_validates_its_fields() -> None:
    with pytest.raises(ApprovalRequired):
        HumanApproval(user_id="u", approved_at=UPDATED)  # type: ignore[arg-type]
    with pytest.raises(ApprovalRequired):
        HumanApproval(user_id=PRODUCT, approved_at="now")  # type: ignore[arg-type]
