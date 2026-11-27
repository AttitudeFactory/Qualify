"""m-25143229: Instagram's «+» — «Formas de pago» and «Cómo llegar».

Network- and Postgres-free: the gateway runs over the backend's own in-memory
conversation service (`test_conversations_provider.World`) with a fake reader of the
business behind the account, so these pin what is queued, by whom and when:

- the payment's QR goes as an image reply and its text as the next message, both with
  THIS user's approval; a method without QR is the text alone; nothing is sent inline;
- a closed window, another account's thread or a method no longer offered refuse
  BEFORE anything is written;
- «Cómo llegar» is one text (WhatsApp's «Estamos en …» with a maps link), refused when
  there is no address any more;
- the lists are read for the account's OWN business (the reader is asked with it);
- the panel's pure rules (when «Enviar» is on, the owner's words for a refusal);
- the Postgres reader goes through `tenant_session` only.
"""

from __future__ import annotations

import inspect
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_api.conversations.service import ThreadNotFound, WindowClosed
from qualify_api.whatsapp.directions import NumberLocation
from qualify_api.whatsapp.menus.engine import PAYMENT_CLOSING
from qualify_api.whatsapp.payments import PaymentMethod, PaymentMethodNotFound

from . import ig_plus_provider
from .conversations_pick_state import ig_pick_can_send, ig_send_error
from .ig_plus_provider import (
    DirectionsUnavailable,
    PlusScope,
    directions_text,
    payment_text,
    qr_content_type,
)
from .test_conversations_provider import (
    CONNECTION,
    NOW,
    OTHER_CONNECTION,
    TENANT,
    USER,
    World,
)
from .whatsapp_chats_vm import (
    DIRECTIONS_NO_LOCATION,
    EMPTY_DIRECTIONS,
    PAYMENT_GONE,
    PICK_DIRECTIONS,
    PICK_PAYMENTS,
    DirectionsVM,
)

BRAND = uuid4()
NUMBER = uuid4()
QR_KEY = f"t/{TENANT}/whatsapp/payments/{BRAND}/qr-nequi.png"


def _method(name: str = "Nequi", *, qr: str | None = None, **kw: object) -> PaymentMethod:
    return PaymentMethod(
        id=uuid4(),
        tenant_id=TENANT,
        brand_id=BRAND,
        name=name,
        name_key=name.lower(),
        currency="COP",
        instructions=f"{name} 300 123 4567 a nombre de Bianki",
        qr_media_key=qr,
        active=True,
        **kw,  # type: ignore[arg-type]
    )


class FakePlus:
    """The business behind CONNECTION only (another account reads as none)."""

    def __init__(self, methods: list[PaymentMethod], location: NumberLocation | None) -> None:
        self.methods = methods
        self.location = location
        self.asked: list[tuple[UUID, UUID]] = []

    def scope(self, tenant_id: UUID, connection_id: UUID) -> PlusScope:
        if tenant_id != TENANT or connection_id != CONNECTION:
            return PlusScope()
        return PlusScope(brand_id=BRAND, whatsapp_connection_id=NUMBER, location=self.location)

    def payment_methods(self, tenant_id: UUID, brand_id: UUID) -> list[PaymentMethod]:
        self.asked.append((tenant_id, brand_id))
        return [m for m in self.methods if m.tenant_id == tenant_id and m.brand_id == brand_id]


ADDRESS = NumberLocation(name="Bianki", address="Calle 10 # 5-20, Cúcuta")


@pytest.fixture
def world() -> World:
    w = World()
    w.plus = FakePlus([], ADDRESS)
    w.gateway._plus = w.plus
    return w


# --- what goes out (pure) --------------------------------------------------------------


def test_directions_text_is_whatsapps_text_with_the_right_link() -> None:
    assert directions_text(None) == ""
    assert directions_text(NumberLocation()) == ""
    assert directions_text(ADDRESS) == (
        "Estamos en Calle 10 # 5-20, Cúcuta.\n"
        "https://maps.google.com/?q=Calle%2010%20%23%205-20%2C%20C%C3%BAcuta"
    )
    # with a point the link IS the point (Instagram has no location message)
    pinned = NumberLocation(
        latitude=Decimal("7.893907"), longitude=Decimal("-72.507820"), address="Calle 10"
    )
    assert directions_text(pinned) == (
        "Estamos en Calle 10.\nhttps://www.google.com/maps/search/?api=1&query=7.893907,-72.507820"
    )
    # a point and only the name; a point with nothing else is the bare link
    named = NumberLocation(latitude=Decimal("1"), longitude=Decimal("2"), name="Bianki")
    assert directions_text(named).startswith("Estamos en Bianki.\nhttps://www.google.com/maps")
    bare = NumberLocation(latitude=Decimal("1"), longitude=Decimal("2"))
    assert directions_text(bare) == "https://www.google.com/maps/search/?api=1&query=1,2"


def test_payment_text_is_whatsapps_card_without_an_order_total() -> None:
    text = payment_text(_method())
    assert text.startswith("Nequi 300 123 4567 a nombre de Bianki")
    assert text.endswith(PAYMENT_CLOSING)
    assert "Total" not in text
    assert qr_content_type("a/qr.PNG") == "image/png"
    assert qr_content_type("a/qr.jpg") == "image/jpeg"


# --- Formas de pago ----------------------------------------------------------------------


def test_the_list_is_the_accounts_own_business_with_the_qr_through_r2media(world) -> None:  # noqa: ANN001
    with_qr, plain = _method(qr=QR_KEY), _method("Efectivo", pay_on_delivery=True)
    world.plus.methods = [with_qr, plain]
    picks = world.gateway.list_payment_methods_for_chat(TENANT, CONNECTION)
    assert [(p.name, p.has_qr, p.currency_label) for p in picks] == [
        ("Nequi", True, "En pesos"),
        ("Efectivo", False, "Al recibir"),
    ]
    assert picks[0].thumb_url == "/r2media/image/qr-nequi.png" and picks[1].thumb_url == ""
    assert world.plus.asked == [(TENANT, BRAND)]
    # another account of the tenant, or another tenant: no business, no list
    assert world.gateway.list_payment_methods_for_chat(TENANT, OTHER_CONNECTION) == []
    assert world.gateway.list_payment_methods_for_chat(uuid4(), CONNECTION) == []


def test_a_method_with_qr_queues_the_image_then_the_text_with_this_users_approval(world) -> None:  # noqa: ANN001
    method = _method(qr=QR_KEY)
    world.plus.methods = [method]
    thread = world.inbound()
    preview = world.gateway.payment_preview(TENANT, CONNECTION, thread, method.id)
    assert preview.qr_src == "/r2media/image/qr-nequi.png"
    image_id, text_id = world.gateway.send_payment_method(
        TENANT, CONNECTION, thread, USER, method.id
    )
    image, text = world.outbox.rows[image_id], world.outbox.rows[text_id]
    assert image.media is not None
    assert (image.media.object_key, image.media.media_type, image.media.content_type) == (
        QR_KEY,
        "image",
        "image/png",
    )
    assert image.payload["message"]["attachment"]["type"] == "image"
    assert text.payload == {
        "recipient": {"id": "igsid-alice"},
        "message": {"text": preview.text},
    }
    assert {image.approved_by_user_id, text.approved_by_user_id} == {USER}
    assert image.approved_at == text.approved_at == NOW
    assert image.status == text.status == "pending"
    assert world.sender.sent == []  # nothing inline: the worker drains the queue


def test_a_method_without_qr_is_the_text_alone(world) -> None:  # noqa: ANN001
    method = _method()
    world.plus.methods = [method]
    thread = world.inbound()
    assert world.gateway.payment_preview(TENANT, CONNECTION, thread, method.id).qr_src == ""
    (only,) = world.gateway.send_payment_method(TENANT, CONNECTION, thread, USER, method.id)
    assert world.outbox.rows[only].media is None
    assert world.outbox.rows[only].payload["message"]["text"] == payment_text(method)


def test_payment_refusals_write_nothing(world) -> None:  # noqa: ANN001
    method = _method(qr=QR_KEY)
    world.plus.methods = [method]
    late = world.inbound(at=NOW - timedelta(hours=25))
    with pytest.raises(WindowClosed):
        world.gateway.send_payment_method(TENANT, CONNECTION, late, USER, method.id)
    fresh = world.inbound(counterpart="igsid-bob")
    with pytest.raises(PaymentMethodNotFound):  # turned off meanwhile / never ours
        world.gateway.send_payment_method(TENANT, CONNECTION, fresh, USER, uuid4())
    other = world.inbound(connection_id=OTHER_CONNECTION, counterpart="igsid-carl")
    with pytest.raises(ThreadNotFound):  # a thread of another account of the tenant
        world.gateway.send_payment_method(TENANT, CONNECTION, other, USER, method.id)
    with pytest.raises(ThreadNotFound):  # another tenant
        world.gateway.send_payment_method(uuid4(), CONNECTION, fresh, USER, method.id)
    assert world.outbox.rows == {}


# --- Cómo llegar ---------------------------------------------------------------------------


def test_directions_preview_and_send_are_one_text(world) -> None:  # noqa: ANN001
    thread = world.inbound()
    preview = world.gateway.directions_preview(TENANT, CONNECTION)
    assert preview == DirectionsVM(present=True, empty=False, text=directions_text(ADDRESS))
    (item,) = world.gateway.send_directions(TENANT, CONNECTION, thread, USER)
    row = world.outbox.rows[item]
    assert row.payload["message"] == {"text": directions_text(ADDRESS)}
    assert row.approved_by_user_id == USER and row.media is None


def test_directions_without_an_address_is_the_empty_state_and_refuses_to_send(world) -> None:  # noqa: ANN001
    world.plus.location = None
    thread = world.inbound()
    assert world.gateway.directions_preview(TENANT, CONNECTION) == DirectionsVM(present=True)
    with pytest.raises(DirectionsUnavailable):
        world.gateway.send_directions(TENANT, CONNECTION, thread, USER)
    late = world.inbound(at=NOW - timedelta(hours=25), counterpart="igsid-bob")
    world.plus.location = ADDRESS
    with pytest.raises(WindowClosed):
        world.gateway.send_directions(TENANT, CONNECTION, late, USER)
    assert world.outbox.rows == {}


# --- the panel's pure rules ------------------------------------------------------------


def test_send_is_on_only_once_what_goes_out_is_on_screen() -> None:
    ready = DirectionsVM(present=True, empty=False, text="Estamos en …")
    base = dict(
        reviewing=True,
        sending=False,
        payment_id="m1",
        payment_text="Nequi …",
        payment_loading=False,
        directions=ready,
    )
    assert ig_pick_can_send(source=PICK_PAYMENTS, **base)
    assert ig_pick_can_send(source=PICK_DIRECTIONS, **base)
    assert not ig_pick_can_send(source=PICK_PAYMENTS, **{**base, "sending": True})
    assert not ig_pick_can_send(source=PICK_PAYMENTS, **{**base, "reviewing": False})
    assert not ig_pick_can_send(source=PICK_PAYMENTS, **{**base, "payment_text": ""})
    assert not ig_pick_can_send(source=PICK_PAYMENTS, **{**base, "payment_loading": True})
    assert not ig_pick_can_send(source=PICK_DIRECTIONS, **{**base, "directions": EMPTY_DIRECTIONS})
    assert not ig_pick_can_send(
        source=PICK_DIRECTIONS, **{**base, "directions": DirectionsVM(present=True)}
    )
    assert not ig_pick_can_send(source="menu", **base)


def test_refusals_are_worded_for_the_owner() -> None:
    assert ig_send_error(PaymentMethodNotFound("x"), PICK_PAYMENTS) == PAYMENT_GONE
    assert ig_send_error(DirectionsUnavailable("x"), PICK_DIRECTIONS) == DIRECTIONS_NO_LOCATION
    assert "ya no está disponible" in ig_send_error(ThreadNotFound("x"), PICK_PAYMENTS)
    assert "Boom" not in ig_send_error(RuntimeError("Boom"), PICK_DIRECTIONS)


def test_the_reader_goes_through_tenant_session_only() -> None:
    source = inspect.getsource(ig_plus_provider.PostgresPlusReader.scope)
    assert "tenant_session(tenant_id)" in source
    assert "admin_session" not in inspect.getsource(ig_plus_provider)
