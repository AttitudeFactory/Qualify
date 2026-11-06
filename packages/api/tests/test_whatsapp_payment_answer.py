"""m-24955648 §6 — the starter's «Formas de pago» answer is composed live from the
methods offered at that moment, offline; and `save_payment_method`, one save for the
fields and the QR."""

from __future__ import annotations

import io
import json
from uuid import UUID

import pytest
from PIL import Image

from qualify_api.whatsapp.menus.engine import (
    Inbound,
    PaymentOption,
    SendText,
    ThreadMenuState,
    step,
)
from qualify_api.whatsapp.menus.schema import MenuDefinition
from qualify_api.whatsapp.menus.starter import (
    PAYMENT_ANSWER_NODE_ID,
    PAYMENT_ANSWER_UNSET,
    PAYMENT_TEXT,
    StarterFacts,
    build_starter_menu,
    definition_gaps,
    payment_answer,
)
from qualify_api.whatsapp.payments import (
    MemoryPaymentMethodRepository,
    MemoryQrStore,
    PaymentImageRefused,
    PaymentMethodIncomplete,
    PaymentMethodService,
    QrChange,
    payments_prefix,
)

TENANT = UUID("a0000000-0000-4000-8000-000000955652")
BRAND = UUID("c0000000-0000-4000-8000-000000955652")
USER = UUID("e0000000-0000-4000-8000-000000955652")
PAGO = PaymentOption(id="m1", name="Pago móvil", currency="VES", instructions="Banco")
EFECTIVO = PaymentOption(id="m2", name="Efectivo al recibir", pay_on_delivery=True)
LIVE = (
    "Aceptamos Pago móvil (en bolívares) y Efectivo al recibir. Te pasamos los datos al "
    "terminar tu pedido."
)


def _menu(body: str | None = None, *, node_id: str = PAYMENT_ANSWER_NODE_ID) -> MenuDefinition:
    data = build_starter_menu(StarterFacts(business_name="Bianki")).model_dump(mode="json")
    answer = data["nodes"].pop(PAYMENT_ANSWER_NODE_ID)
    if body is not None:
        answer["body"] = body
    data["nodes"][node_id] = answer
    data = json.loads(json.dumps(data).replace(f'"{PAYMENT_ANSWER_NODE_ID}"', f'"{node_id}"'))
    data["entry"]["keywords"] = {"pagos": node_id}
    return MenuDefinition.model_validate(data)


def _answer(definition: MenuDefinition, offered) -> str:
    result = step(definition, ThreadMenuState(), Inbound.text("pagos"), payment_methods=offered)
    texts = [a.body for a in result.actions if isinstance(a, SendText)]
    assert len(texts) == 1
    return texts[0]


class Counting(tuple):
    """A lazy-looking sequence that records whether it was read."""

    reads = 0

    def __bool__(self) -> bool:
        type(self).reads += 1
        return super().__len__() > 0

    def __iter__(self):
        type(self).reads += 1
        return super().__iter__()


def test_the_starter_answer_reads_the_methods_offered_now() -> None:
    definition = _menu()  # still holds the stored gap: published while methods were offered
    assert _answer(definition, (PAGO, EFECTIVO)) == LIVE
    assert _answer(definition, (PAGO,)).startswith("Aceptamos Pago móvil (en bolívares).")


def test_with_none_offered_the_owner_text_goes_out_as_today() -> None:
    owner = "Pagas en efectivo o por transferencia."
    assert _answer(_menu(owner), ()) == owner
    # A stored gap never reaches a customer, even if every method was turned off later.
    assert _answer(_menu(PAYMENT_TEXT), ()) == PAYMENT_ANSWER_UNSET


def test_an_answer_made_by_hand_with_the_same_title_is_not_composed() -> None:
    owner = "Solo efectivo, gracias."
    hand_made = _menu(owner, node_id="formas-de-pago-3fa9")
    assert _answer(hand_made, (PAGO,)) == owner
    assert payment_answer(hand_made, (PAGO,)) is None


def test_the_methods_are_read_only_when_the_answer_is_rendered() -> None:
    definition = _menu()
    Counting.reads = 0
    step(definition, ThreadMenuState(), Inbound.text("hola"), payment_methods=Counting((PAGO,)))
    assert Counting.reads == 0
    _answer(definition, Counting((PAGO,)))
    assert Counting.reads > 0


def test_the_gap_blocks_only_while_no_method_is_offered() -> None:
    definition = _menu(PAYMENT_TEXT)
    gaps = definition_gaps(definition)
    assert any(g.node_id == PAYMENT_ANSWER_NODE_ID for g in gaps)
    offered = definition_gaps(definition, payments_offered=True)
    assert all(g.node_id != PAYMENT_ANSWER_NODE_ID for g in offered)
    # A hand-made answer's gap always blocks.
    hand_made = _menu(PAYMENT_TEXT, node_id="formas-de-pago-3fa9")
    assert any(
        g.node_id == "formas-de-pago-3fa9"
        for g in definition_gaps(hand_made, payments_offered=True)
    )


def test_the_editor_read_model_says_composed_and_what_it_reads() -> None:
    definition = _menu("Texto del dueño")
    live = payment_answer(definition, (PAGO, EFECTIVO))
    assert (live.node_id, live.auto_composed, live.text, live.stored_text) == (
        "pagos",
        True,
        LIVE,
        "Texto del dueño",
    )
    idle = payment_answer(definition, ())
    assert (idle.auto_composed, idle.text) == (False, "Texto del dueño")


# --- one save for fields + QR -------------------------------------------------------------


def _png(color: tuple[int, int, int] = (0, 0, 0)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(out, format="PNG")
    return out.getvalue()


class World:
    def __init__(self) -> None:
        self.repo = MemoryPaymentMethodRepository()
        self.qr = MemoryQrStore()
        self.service = PaymentMethodService(self.repo, self.qr)
        method = self.service.create_payment_method(
            tenant_id=TENANT, brand_id=BRAND, user_id=USER, name="Pago móvil", instructions="Viejo"
        )
        self.method = self.service.set_qr_image(
            tenant_id=TENANT,
            brand_id=BRAND,
            method_id=method.id,
            user_id=USER,
            content=_png(),
            content_type="image/png",
        )
        self.old_key = self.method.qr_media_key
        self.service.set_active(
            tenant_id=TENANT, brand_id=BRAND, method_id=method.id, user_id=USER, active=True
        )

    def save(self, **kw):
        return self.service.save_payment_method(
            tenant_id=TENANT, brand_id=BRAND, method_id=self.method.id, user_id=USER, **kw
        )


@pytest.fixture
def world() -> World:
    return World()


def test_text_and_qr_change_in_one_write(world: World) -> None:
    writes: list = []
    save = world.repo.save

    def counted(method):
        writes.append(method)
        return save(method)

    world.repo.save = counted  # type: ignore[method-assign]
    saved = world.save(instructions="Nuevo", qr=QrChange.image(_png((9, 9, 9)), "image/png"))
    assert len(writes) == 1
    assert saved.instructions == "Nuevo" and saved.qr_media_key != world.old_key
    assert saved.qr_media_key.startswith(payments_prefix(TENANT, BRAND)) and saved.active
    assert world.qr.deleted == [world.old_key]  # only after the write


def test_a_failed_write_keeps_the_old_pair_and_drops_the_new_image(world: World) -> None:
    def failing(method):
        raise RuntimeError("db down")

    world.repo.save = failing  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        world.save(instructions="Nuevo", qr=QrChange.image(_png((9, 9, 9)), "image/png"))
    row = world.repo.rows[world.method.id]
    assert (row.instructions, row.qr_media_key) == ("Viejo", world.old_key)
    assert (TENANT, world.old_key) in world.qr.objects
    assert len(world.qr.deleted) == 1 and world.qr.deleted[0] != world.old_key


def test_the_final_state_is_validated_before_anything_is_uploaded(world: World) -> None:
    with pytest.raises(PaymentMethodIncomplete):  # offered, no text, QR removed
        world.save(instructions="", qr=QrChange.remove())
    with pytest.raises(PaymentImageRefused):
        world.save(instructions="Nuevo", qr=QrChange.image(b"%PDF", "application/pdf"))
    row = world.repo.rows[world.method.id]
    assert (row.instructions, row.qr_media_key) == ("Viejo", world.old_key)
    assert len(world.qr.objects) == 1 and world.qr.deleted == []


def test_removing_the_qr_and_keeping_it(world: World) -> None:
    kept = world.save(currency="USD")
    assert kept.qr_media_key == world.old_key and world.qr.deleted == []
    removed = world.save(qr=QrChange.remove())
    assert removed.qr_media_key is None and world.qr.deleted == [world.old_key]
