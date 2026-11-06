"""m-24955648 — a business's payment methods (`whatsapp.payments`), offline.

`PaymentMethodService` over the in-memory repository and QR store; nothing reaches
Postgres or R2. Pinned: CRUD and `updated_*` stamps, order, the activation rules (content
unless paid on delivery, at most 10 active, no `[…]` placeholder), name folding and
limits, the QR normalised like a chat photo and the replaced one deleted, other
tenants'/businesses' methods unreachable, and the starter's «Formas de pago» answer.
"""

from __future__ import annotations

import io
import os
import struct
import zlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from PIL import Image

from qualify_api.whatsapp.attachments import MAX_IMAGE_BYTES
from qualify_api.whatsapp.menus.starter import (
    PAYMENT_TEXT,
    StarterFacts,
    build_starter_menu,
    definition_gaps,
    payment_phrase,
    payment_text,
)
from qualify_api.whatsapp.payments import (
    MAX_ACTIVE,
    MemoryPaymentMethodRepository,
    MemoryQrStore,
    PaymentCurrencyInvalid,
    PaymentImageRefused,
    PaymentInstructionsTooLong,
    PaymentMethodIncomplete,
    PaymentMethodNotFound,
    PaymentMethodService,
    PaymentNameRequired,
    PaymentNameTaken,
    PaymentNameTooLong,
    PaymentOrderMismatch,
    PaymentPlaceholderLeft,
    PaymentTooManyActive,
    payments_prefix,
    qr_thumb_url,
)

TENANT = UUID("a0000000-0000-4000-8000-000000955648")
OTHER_TENANT = UUID("b0000000-0000-4000-8000-000000955648")
BRAND = UUID("c0000000-0000-4000-8000-000000955648")
OTHER_BRAND = UUID("c1000000-0000-4000-8000-000000955648")
USER = UUID("e0000000-0000-4000-8000-000000955648")
T0 = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
PAGO_MOVIL = "Banco de Venezuela (0102) · Cédula: V-12345678 · Teléfono: 0414-1234567"


def _png(size: tuple[int, int] = (64, 64)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (0, 0, 0)).save(out, format="PNG")
    return out.getvalue()


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class World:
    def __init__(self) -> None:
        self.repo = MemoryPaymentMethodRepository()
        self.qr = MemoryQrStore()
        self.clock = Clock()
        self.service = PaymentMethodService(self.repo, self.qr, clock=self.clock)

    def create(self, name: str, **kw):
        kw.setdefault("tenant_id", TENANT)
        kw.setdefault("brand_id", BRAND)
        return self.service.create_payment_method(user_id=USER, name=name, **kw)

    def activate(self, method, active: bool = True):
        return self.service.set_active(
            tenant_id=method.tenant_id,
            brand_id=method.brand_id,
            method_id=method.id,
            user_id=USER,
            active=active,
        )


@pytest.fixture
def world() -> World:
    return World()


# --- create / update / delete ------------------------------------------------------------


def test_a_new_method_is_inactive_at_the_end_with_its_provenance(world: World) -> None:
    first = world.create("Pago móvil", currency=" ves ", instructions=PAGO_MOVIL)
    second = world.create("  Efectivo  ", pay_on_delivery=True)
    assert (first.position, second.position) == (0, 1)
    assert (first.active, first.currency, first.source) == (False, "VES", "manual")
    assert second.name == "Efectivo" and second.pay_on_delivery
    assert (first.created_by, first.updated_by, first.created_at) == (USER, USER, T0)
    listed = world.service.list_payment_methods(tenant_id=TENANT, brand_id=BRAND)
    assert [m.name for m in listed] == ["Pago móvil", "Efectivo"]


def test_names_fold_and_have_a_button_sized_limit(world: World) -> None:
    world.create("Pago Móvil")
    for clash in ("pago movil", "PAGO  MÓVIL", " Pago movil "):
        with pytest.raises(PaymentNameTaken):
            world.create(clash)
    with pytest.raises(PaymentNameTooLong):
        world.create("x" * 21)
    with pytest.raises(PaymentNameRequired):
        world.create("   ")
    # Another business may use the same name.
    world.create("Pago móvil", brand_id=OTHER_BRAND)


def test_instructions_length_currency_and_placeholders_are_checked(world: World) -> None:
    with pytest.raises(PaymentInstructionsTooLong):
        world.create("Nequi", instructions="x" * 901)
    with pytest.raises(PaymentCurrencyInvalid):
        world.create("Nequi", currency="pesos colombianos")
    with pytest.raises(PaymentPlaceholderLeft) as left:
        world.create("Nequi", instructions="Nequi al [número], a nombre de [titular]")
    assert left.value.gaps == ("número", "titular")
    assert "número" in left.value.message and "[ ]" in left.value.message
    # A link is not a placeholder.
    ok = world.create("Wompi", instructions="Paga aquí: [abrir el enlace](https://wompi.co/x)")
    assert ok.instructions.startswith("Paga aquí")


def test_update_stamps_and_refuses_a_name_taken(world: World) -> None:
    pago = world.create("Pago móvil", instructions=PAGO_MOVIL)
    world.create("Binance")
    world.clock.now = T0 + timedelta(hours=1)
    other_user = uuid4()
    updated = world.service.update_payment_method(
        tenant_id=TENANT,
        brand_id=BRAND,
        method_id=pago.id,
        user_id=other_user,
        name="Pago móvil BDV",
        currency="VES",
    )
    assert (updated.name, updated.updated_by, updated.updated_at) == (
        "Pago móvil BDV",
        other_user,
        T0 + timedelta(hours=1),
    )
    assert updated.created_by == USER
    with pytest.raises(PaymentNameTaken):
        world.service.update_payment_method(
            tenant_id=TENANT, brand_id=BRAND, method_id=pago.id, user_id=USER, name="binance"
        )


def test_delete_removes_the_method_and_its_qr(world: World) -> None:
    pago = world.create("Pago móvil")
    pago = world.service.set_qr_image(
        tenant_id=TENANT,
        brand_id=BRAND,
        method_id=pago.id,
        user_id=USER,
        content=_png(),
        content_type="image/png",
    )
    world.service.delete_payment_method(tenant_id=TENANT, brand_id=BRAND, method_id=pago.id)
    assert world.repo.rows == {} and world.qr.objects == {}
    assert world.qr.deleted == [pago.qr_media_key]


# --- order -------------------------------------------------------------------------------


def test_reorder_takes_the_whole_list_and_nothing_else(world: World) -> None:
    a, b, c = (world.create(n) for n in ("Pago móvil", "Binance", "Efectivo"))
    ordered = world.service.reorder_payment_methods(
        tenant_id=TENANT, brand_id=BRAND, user_id=USER, ids=[c.id, a.id, b.id]
    )
    assert [m.name for m in ordered] == ["Efectivo", "Pago móvil", "Binance"]
    for wrong in ([a.id, b.id], [a.id, b.id, c.id, uuid4()], [a.id, a.id, b.id]):
        with pytest.raises(PaymentOrderMismatch):
            world.service.reorder_payment_methods(
                tenant_id=TENANT, brand_id=BRAND, user_id=USER, ids=wrong
            )


# --- activation --------------------------------------------------------------------------


def test_a_method_needs_instructions_or_a_qr_to_be_offered(world: World) -> None:
    empty = world.create("Zelle")
    with pytest.raises(PaymentMethodIncomplete) as refused:
        world.activate(empty)
    assert refused.value.message == "Para ofrecerla, escribe cómo te pagan o sube tu QR."
    with_text = world.activate(world.create("Pago móvil", instructions=PAGO_MOVIL))
    assert with_text.active
    qr_only = world.create("Binance")
    world.service.set_qr_image(
        tenant_id=TENANT,
        brand_id=BRAND,
        method_id=qr_only.id,
        user_id=USER,
        content=_png(),
        content_type="image/png",
    )
    assert world.activate(world.repo.rows[qr_only.id]).active


def test_cash_on_delivery_is_offered_without_qr_or_instructions(world: World) -> None:
    cash = world.create("Efectivo", pay_on_delivery=True)
    assert world.activate(cash).active
    assert world.activate(world.create("Al recibir", instructions="Pagas al recibir.")).active


def test_an_active_method_cannot_be_left_with_nothing_to_send(world: World) -> None:
    pago = world.activate(world.create("Pago móvil", instructions=PAGO_MOVIL))
    with pytest.raises(PaymentMethodIncomplete):
        world.service.update_payment_method(
            tenant_id=TENANT, brand_id=BRAND, method_id=pago.id, user_id=USER, instructions=""
        )
    assert world.repo.rows[pago.id].instructions == PAGO_MOVIL


def test_at_most_ten_methods_are_offered_at_once(world: World) -> None:
    for i in range(MAX_ACTIVE):
        world.activate(world.create(f"Forma {i}", instructions="Pagas así."))
    eleventh = world.create("Forma 10", instructions="Pagas así.")
    with pytest.raises(PaymentTooManyActive) as refused:
        world.activate(eleventh)
    assert "hasta 10" in refused.value.message
    # Turning one off makes room.
    world.activate(world.repo.rows[next(iter(world.repo.rows))], active=False)
    assert world.activate(eleventh).active


def test_an_imported_placeholder_is_refused_at_activation(world: World) -> None:
    imported = world.create("Bre-B", source="import", external_code="BREB")
    # Written straight to the store, as an import of an old row could leave it.
    world.repo.rows[imported.id] = replace(imported, instructions="Llave: [tu llave]")
    with pytest.raises(PaymentPlaceholderLeft):
        world.activate(world.repo.rows[imported.id])
    assert imported.source == "import" and imported.external_code == "BREB"


# --- the QR image ------------------------------------------------------------------------


def test_the_qr_is_normalised_stored_under_the_brand_and_replaced(world: World) -> None:
    pago = world.create("Pago móvil")
    first = world.service.set_qr_image(
        tenant_id=TENANT,
        brand_id=BRAND,
        method_id=pago.id,
        user_id=USER,
        content=_png(),
        content_type="image/png",
    )
    assert first.qr_media_key.startswith(payments_prefix(TENANT, BRAND))
    assert first.qr_media_key.endswith(".png")
    # A big phone photo of the QR (> 5 MB) is re-encoded as a JPEG within 5 MB.
    side = 1500
    noisy = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
    out = io.BytesIO()
    noisy.save(out, format="PNG")
    second = world.service.set_qr_image(
        tenant_id=TENANT,
        brand_id=BRAND,
        method_id=pago.id,
        user_id=USER,
        content=out.getvalue(),
        content_type="image/png",
    )
    content, content_type = world.qr.objects[(TENANT, second.qr_media_key)]
    assert content_type == "image/jpeg" and len(content) <= MAX_IMAGE_BYTES
    assert world.qr.deleted == [first.qr_media_key]
    assert (TENANT, first.qr_media_key) not in world.qr.objects


def _png_header(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 64))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    ("content", "content_type", "reason"),
    [
        (_png_header(20_000, 20_000), "image/png", "too_large"),
        (b"%PDF-1.7", "application/pdf", "unsupported_type"),
        (b"", "image/png", "empty"),
    ],
)
def test_a_refused_qr_image_changes_nothing(
    world: World, content: bytes, content_type: str, reason: str
) -> None:
    pago = world.create("Pago móvil")
    with pytest.raises(PaymentImageRefused) as refused:
        world.service.set_qr_image(
            tenant_id=TENANT,
            brand_id=BRAND,
            method_id=pago.id,
            user_id=USER,
            content=content,
            content_type=content_type,
        )
    assert refused.value.reason == reason and refused.value.message
    assert world.qr.objects == {} and world.repo.rows[pago.id].qr_media_key is None


def test_removing_the_qr_of_a_qr_only_active_method_is_refused(world: World) -> None:
    binance = world.create("Binance")
    world.service.set_qr_image(
        tenant_id=TENANT,
        brand_id=BRAND,
        method_id=binance.id,
        user_id=USER,
        content=_png(),
        content_type="image/png",
    )
    world.activate(world.repo.rows[binance.id])
    with pytest.raises(PaymentMethodIncomplete):
        world.service.remove_qr_image(
            tenant_id=TENANT, brand_id=BRAND, method_id=binance.id, user_id=USER
        )


def test_a_thumbnail_is_minted_only_for_the_brands_own_qr(world: World) -> None:
    class Linker:
        def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
            return f"https://app.qualify.la/public/media/{content_type}"

    pago = world.service.set_qr_image(
        tenant_id=TENANT,
        brand_id=BRAND,
        method_id=world.create("Pago móvil").id,
        user_id=USER,
        content=_png(),
        content_type="image/png",
    )
    assert qr_thumb_url(TENANT, pago, Linker()).endswith("image/png")
    assert qr_thumb_url(OTHER_TENANT, pago, Linker()) == ""
    assert qr_thumb_url(TENANT, world.create("Efectivo"), Linker()) == ""


# --- isolation ---------------------------------------------------------------------------


def test_another_tenants_or_businesss_method_is_not_found(world: World) -> None:
    foreign = world.create("Pago móvil", tenant_id=OTHER_TENANT)
    other_brand = world.create("Binance", brand_id=OTHER_BRAND)
    for method_id in (foreign.id, other_brand.id, uuid4()):
        with pytest.raises(PaymentMethodNotFound):
            world.service.update_payment_method(
                tenant_id=TENANT, brand_id=BRAND, method_id=method_id, user_id=USER, name="x"
            )
        with pytest.raises(PaymentMethodNotFound):
            world.service.delete_payment_method(
                tenant_id=TENANT, brand_id=BRAND, method_id=method_id
            )
    assert world.service.list_payment_methods(tenant_id=TENANT, brand_id=BRAND) == ()
    assert len(world.repo.rows) == 2


def test_only_active_lists_what_a_customer_may_be_offered(world: World) -> None:
    world.activate(world.create("Pago móvil", instructions=PAGO_MOVIL))
    world.create("Zelle")
    world.activate(world.create("Efectivo", pay_on_delivery=True))
    offered = world.service.list_payment_methods(tenant_id=TENANT, brand_id=BRAND, only_active=True)
    assert [m.name for m in offered] == ["Pago móvil", "Efectivo"]


# --- the starter's «Formas de pago» answer -----------------------------------------------


def test_the_payment_answer_lists_the_active_methods() -> None:
    phrases = (
        payment_phrase("Pago móvil", "VES"),
        payment_phrase("Bre-B Bancolombia", "COP"),
        payment_phrase("Efectivo", "USD", pay_on_delivery=True),
    )
    assert payment_text(phrases) == (
        "Aceptamos Pago móvil (en bolívares), Bre-B Bancolombia (en pesos) y Efectivo al "
        "recibir. Te pasamos los datos al terminar tu pedido."
    )
    assert payment_text((payment_phrase("Binance", "USDT"),)) == (
        "Aceptamos Binance (en USDT). Te pasamos los datos al terminar tu pedido."
    )
    assert payment_text(()) == PAYMENT_TEXT


def test_the_starter_has_no_payment_gap_once_methods_are_active() -> None:
    def pagos_gaps(facts: StarterFacts) -> list:
        return [g for g in definition_gaps(build_starter_menu(facts)) if g.node_id == "pagos"]

    assert pagos_gaps(StarterFacts(business_name="Bianki"))  # the gap stays
    facts = StarterFacts(business_name="Bianki", payment_methods=("Pago móvil", "Efectivo"))
    assert pagos_gaps(facts) == []
    assert (
        build_starter_menu(facts)
        .nodes["pagos"]
        .body.startswith(  # type: ignore[union-attr]
            "Aceptamos Pago móvil y Efectivo."
        )
    )


# --- review fixes (code + UX review of part 1) --------------------------------------------


def test_the_cap_is_counted_where_the_write_happens(world: World) -> None:
    """The service never counts from a separate read: the repository's `activate`
    counts and writes in one transaction (Postgres: under the business's lock)."""

    class StaleList(MemoryPaymentMethodRepository):
        def list(self, *, tenant_id: UUID, brand_id: UUID):  # a read that missed 10 taps
            return [
                replace(m, active=False)
                for m in super().list(tenant_id=tenant_id, brand_id=brand_id)
            ]

    repo = StaleList()
    service = PaymentMethodService(repo, MemoryQrStore(), clock=world.clock)
    for i in range(MAX_ACTIVE):
        method = service.create_payment_method(
            tenant_id=TENANT, brand_id=BRAND, user_id=USER, name=f"F{i}", instructions="Así."
        )
        service.set_active(
            tenant_id=TENANT, brand_id=BRAND, method_id=method.id, user_id=USER, active=True
        )
    eleventh = service.create_payment_method(
        tenant_id=TENANT, brand_id=BRAND, user_id=USER, name="F10", instructions="Así."
    )
    with pytest.raises(PaymentTooManyActive) as refused:
        service.set_active(
            tenant_id=TENANT, brand_id=BRAND, method_id=eleventh.id, user_id=USER, active=True
        )
    assert refused.value.message == (
        "Puedes ofrecer hasta 10 formas de pago a la vez. Apaga una para ofrecer esta."
    )
    assert repo.rows[eleventh.id].active is False


def test_a_qr_whose_save_fails_leaves_no_object_behind(world: World) -> None:
    pago = world.create("Pago móvil")

    class Boom(RuntimeError):
        pass

    def failing_save(method):
        raise Boom()

    world.repo.save = failing_save  # type: ignore[method-assign]
    with pytest.raises(Boom):
        world.service.set_qr_image(
            tenant_id=TENANT,
            brand_id=BRAND,
            method_id=pago.id,
            user_id=USER,
            content=_png(),
            content_type="image/png",
        )
    assert world.qr.objects == {}
    assert len(world.qr.deleted) == 1 and world.qr.deleted[0].startswith(
        payments_prefix(TENANT, BRAND)
    )


class _Diag:
    def __init__(self, constraint: str | None) -> None:
        self.constraint_name = constraint


class _Orig(Exception):
    sqlstate = "23514"

    def __init__(self, constraint: str | None) -> None:
        super().__init__(
            "new row violates check constraint\nDETAIL: Failing row contains (…, Banco de "
            "Venezuela 0102-1234-56-7890123456, V-12345678, …)."
        )
        self.diag = _Diag(constraint)


def test_a_database_refusal_never_carries_the_row() -> None:
    from sqlalchemy.exc import IntegrityError

    from qualify_api.whatsapp.payments import PaymentMethodRejected, _refusal

    check = _refusal(IntegrityError("INSERT …", {}, _Orig("ck_brand_payment_methods_name")))
    assert isinstance(check, PaymentMethodRejected)
    assert check.message == (
        "No pudimos guardar la forma de pago. Revisa los datos y vuelve a intentarlo."
    )
    assert "Venezuela" not in str(check) and check.__cause__ is None
    taken = _refusal(IntegrityError("INSERT …", {}, _Orig("uq_brand_payment_methods_key")))
    assert isinstance(taken, PaymentNameTaken)


def test_the_postgres_write_raises_the_refusal_without_its_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    import qualify_shared.db.session as door
    from sqlalchemy.exc import IntegrityError

    from qualify_api.whatsapp.payments import (
        PaymentMethod,
        PaymentMethodRejected,
        PostgresPaymentMethodRepository,
    )

    class Session:
        def add(self, row) -> None:
            pass

        def flush(self) -> None:
            raise IntegrityError("INSERT …", {}, _Orig("ck_brand_payment_methods_qr_key"))

    @contextmanager
    def fake_session(tenant_id):
        yield Session()

    monkeypatch.setattr(door, "tenant_session", fake_session)
    method = PaymentMethod(id=uuid4(), tenant_id=TENANT, brand_id=BRAND, name="X", name_key="x")
    with pytest.raises(PaymentMethodRejected) as refused:
        PostgresPaymentMethodRepository().insert(method)
    assert refused.value.__cause__ is None and refused.value.__suppress_context__


@pytest.mark.parametrize(
    ("name", "currency", "pay_on_delivery", "sentence"),
    [
        # The shortcuts of «Formas de pago» (`Qualify/whatsapp_payments_vm.SHORTCUTS`).
        ("Pago móvil", "VES", False, "Aceptamos Pago móvil (en bolívares)."),
        ("Transferencia", "", False, "Aceptamos Transferencia."),
        ("Bre-B", "COP", False, "Aceptamos Bre-B (en pesos)."),
        ("Nequi", "COP", False, "Aceptamos Nequi (en pesos)."),
        ("Binance", "USDT", False, "Aceptamos Binance (en USDT)."),
        ("Efectivo al recibir", "", True, "Aceptamos Efectivo al recibir."),
        ("Otra", "", False, "Aceptamos Otra."),
        # Neighbours: names that already say it, and one that does not.
        ("Pago contra entrega", "", True, "Aceptamos Pago contra entrega."),
        ("Efectivo", "USD", True, "Aceptamos Efectivo al recibir."),
    ],
)
def test_each_shortcut_reads_as_one_sentence(
    name: str, currency: str, pay_on_delivery: bool, sentence: str
) -> None:
    text = payment_text((payment_phrase(name, currency, pay_on_delivery),))
    assert text == f"{sentence} Te pasamos los datos al terminar tu pedido."
    assert "al recibir al recibir" not in text
