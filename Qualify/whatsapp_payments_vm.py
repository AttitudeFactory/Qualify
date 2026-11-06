"""View models of «Formas de pago» (WhatsApp → Tu número, m-24955648) — pure, no Reflex.

Spec: `docs/ux-paso-de-pago.md` §1–§2 (first PR: the owner manages the business's
payment methods; nothing the customer sees changes yet). Copy follows qualify-copy-es.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

MAX_NAME: Final = 20
MAX_INSTRUCTIONS: Final = 900
MAX_ACTIVE: Final = 10

# -- copy (§2) ---------------------------------------------------------------------------
TITLE: Final = "Formas de pago"
HELP: Final = (
    "Tu cliente las elige al terminar su pedido y le llegan tus datos al instante. Tú solo "
    "confirmas que el pago llegó."
)
SAME_FOR_ALL: Final = "Son las mismas para todos tus números."
BUTTONS_OR_LIST: Final = "Con hasta 3, tu cliente las ve como botones; con más, en una lista."
ADD: Final = "Agregar forma de pago"
OFFERED: Final = "La ofreces"
NO_QR: Final = "Sin QR"
EDIT: Final = "Editar"
DELETE: Final = "Borrar"
KEEP: Final = "Dejarla"
EMPTY_TITLE: Final = "Cobra por WhatsApp sin dictar tus datos"
EMPTY_TEXT: Final = (
    "Carga tu pago móvil, tu llave o tu QR una vez. Cuando alguien termine su pedido, le "
    "llegan tus datos y tú solo confirmas el pago."
)
INCOMPLETE: Final = "Para ofrecerla, escribe cómo te pagan o sube tu QR."
SAVE_FAILED: Final = "No pudimos guardar la forma de pago. Inténtalo otra vez en un minuto."
NO_BRAND: Final = (
    "Este número no tiene una marca. Conéctalo a tu marca en Estado y vuelve aquí para "
    "cargar tus formas de pago."
)
UNDO_LABEL: Final = "Deshacer"
UNDONE: Final = "Listo: volvió el orden que tenías."

STEP_TITLES: Final = (
    "¿Cómo se llama esta forma de pago?",
    "¿Qué tiene que saber tu cliente para pagarte?",
    "¿Tienes un QR para esta forma de pago?",
    "Así le llega a tu cliente",
)
STEPS: Final = len(STEP_TITLES)
NAME_LABEL: Final = "Nombre que ve tu cliente"
CURRENCY_LABEL: Final = "¿En qué moneda?"
WHEN_LABEL: Final = "¿Cuándo te paga?"
WHEN_BEFORE: Final = "Antes de recibir (te manda el comprobante)"
WHEN_ON_DELIVERY: Final = "Al recibir el pedido"
INSTRUCTIONS_LABEL: Final = "Lo que le llega a tu cliente"
INSTRUCTIONS_HELP: Final = (
    "Escribe solo lo que le dirías por WhatsApp. Qualify no pide ni muestra más datos que estos."
)
PLACEHOLDER_LEFT: Final = "Cambia lo que está entre [ ] por tus datos."
QR_DROP: Final = "Sube la foto o captura de tu QR"
QR_HELP: Final = "En JPG o PNG, de menos de 15 MB."
QR_WRONG_TYPE: Final = "Ese archivo no es una foto. Sube tu QR en JPG o PNG."
QR_TOO_LARGE: Final = "Esa foto pesa más de 15 MB. Toma una captura de pantalla del QR y súbela."
QR_UNREADABLE: Final = "No pudimos leer esa foto. Prueba con una captura de pantalla del QR."
QR_REMOVE: Final = "Quitar el QR"
NO_QR_BUTTON: Final = "Sin QR"
NEXT: Final = "Siguiente"
BACK: Final = "Atrás"
CHANGE: Final = "Cambiar"
SAVE: Final = "Guardar"
OFFER_NOW: Final = "Ofrecerla desde ya"
EXAMPLE_TOTAL: Final = "Total: $18 (ejemplo)"
CLOSING_BEFORE: Final = (
    "Cuando pagues, envíanos el comprobante o el número de referencia por aquí. Una persona "
    "del equipo lo revisa y te confirma."
)
CLOSING_ON_DELIVERY: Final = (
    "Pagas al recibir tu pedido. Una persona del equipo te confirma en un momento."
)
NAME_EMPTY: Final = "Escribe el nombre de la forma de pago."
NAME_TOO_LONG: Final = f"El nombre admite hasta {MAX_NAME} caracteres."
INSTRUCTIONS_TOO_LONG: Final = f"Las instrucciones admiten hasta {MAX_INSTRUCTIONS} caracteres."

#: The step 1 shortcuts: (key, name, currency ("" = the business's), paid on delivery,
#: the example the owner replaces). «Otra» starts empty.
SHORTCUTS: Final[tuple[tuple[str, str, str, bool, str], ...]] = (
    (
        "pago-movil",
        "Pago móvil",
        "VES",
        False,
        "Banco [nombre] ([código]) · Cédula o RIF: [número] · Teléfono: [número]",
    ),
    (
        "transferencia",
        "Transferencia",
        "",
        False,
        "Banco [nombre], cuenta [número], a nombre de [titular]",
    ),
    ("bre-b", "Bre-B", "COP", False, "Llave Bre-B: [tu llave] · A nombre de: [titular]"),
    ("nequi", "Nequi", "COP", False, "Nequi al [número], a nombre de [titular]"),
    ("binance", "Binance", "USDT", False, "Binance Pay ID: [número] · Solo USDT"),
    (
        "efectivo",
        "Efectivo al recibir",
        "",
        True,
        "Pagas en efectivo cuando te llega. Si necesitas vuelto, dinos con cuánto pagas.",
    ),
    ("otra", "Otra", "", False, ""),
)
SHORTCUT_KEYS: Final = frozenset(k for k, *_ in SHORTCUTS)

#: The currencies offered, by name; the four markets first. "" is not a Radix value.
CURRENCIES: Final[tuple[tuple[str, str], ...]] = (
    ("COP", "Pesos colombianos (COP)"),
    ("VES", "Bolívares (VES)"),
    ("USD", "Dólares (USD)"),
    ("UYU", "Pesos uruguayos (UYU)"),
    ("USDT", "USDT"),
    ("EUR", "Euros (EUR)"),
)
CURRENCY_CODES: Final = frozenset(code for code, _ in CURRENCIES)
_IN_WORDS: Final = {
    "VES": "En bolívares",
    "COP": "En pesos",
    "UYU": "En pesos",
    "ARS": "En pesos",
    "CLP": "En pesos",
    "MXN": "En pesos",
    "USD": "En dólares",
    "USDT": "En USDT",
    "EUR": "En euros",
    "PEN": "En soles",
}
_MONTHS: Final = (
    "ene.",
    "feb.",
    "mar.",
    "abr.",
    "may.",
    "jun.",
    "jul.",
    "ago.",
    "sep.",
    "oct.",
    "nov.",
    "dic.",
)


def currency_words(code: str) -> str:
    """«En bolívares»; an unknown code as «En XYZ»; none → ""."""
    clean = (code or "").strip().upper()
    if not clean:
        return ""
    return _IN_WORDS.get(clean, f"En {clean}")


def updated_label(iso: str) -> str:
    """«Actualizado el 5 nov.»."""
    try:
        when = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return f"Actualizado el {when.day} {_MONTHS[when.month - 1]}"


def counter(text: str, limit: int) -> str:
    """«12/20»."""
    return f"{len((text or '').strip())}/{limit}"


def name_problem(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        return NAME_EMPTY
    if len(cleaned) > MAX_NAME:
        return NAME_TOO_LONG
    return ""


def instructions_problem(text: str, gaps: Sequence[str]) -> str:
    if len((text or "").strip()) > MAX_INSTRUCTIONS:
        return INSTRUCTIONS_TOO_LONG
    if gaps:
        return PLACEHOLDER_LEFT
    return ""


def can_offer(*, pay_on_delivery: bool, instructions: str, has_qr: bool) -> bool:
    """The backend's rule: paid on delivery, or something to send."""
    return pay_on_delivery or bool((instructions or "").strip()) or has_qr


def moved_text(name: str, position: int, total: int) -> str:
    """«Listo: «Pago móvil» va primero.»."""
    if position == 1:
        return f"Listo: «{name}» va primero."
    if position == total:
        return f"Listo: «{name}» va al final."
    return f"Listo: «{name}» va en el lugar {position}."


def saved_text(name: str, active: bool) -> str:
    if active:
        return f"Listo: tus clientes ya pueden elegir «{name}»."
    return "Guardada. Enciéndela cuando quieras."


def delete_title(name: str) -> str:
    return f"¿Borrar «{name}»?"


DELETE_TEXT: Final = "Tus clientes dejan de verla. Los chats donde ya la enviaste no cambian."


def preview_lines(
    *, instructions: str, currency: str, business_currency: str, pay_on_delivery: bool
) -> list[str]:
    """The text under the QR in «Así le llega a tu cliente» (§3), with a sample total."""
    lines: list[str] = []
    if instructions.strip():
        lines.append(instructions.strip())
    lines.append(EXAMPLE_TOTAL)
    words = currency_words(currency)
    if currency and business_currency and currency.upper() != business_currency.upper() and words:
        lines.append(f"Te confirmamos el monto {words[0].lower()}{words[1:]}.")
    lines.append(CLOSING_ON_DELIVERY if pay_on_delivery else CLOSING_BEFORE)
    return lines


@dataclass(frozen=True)
class PaymentRowVM:
    method_id: str
    name: str
    currency_label: str
    updated_label: str
    thumb_url: str
    has_qr: bool
    active: bool
    position: int
    total: int
    movable: bool
    up_to: int
    down_to: int
    last_to: int
    handle_label: str  # «Mover «Pago móvil», posición 1 de 3»
    more_label: str  # «Más opciones para «Pago móvil»»
    switch_label: str  # «La ofreces: Pago móvil»
    thumb_alt: str  # «QR de Pago móvil»


def payment_rows(methods: Sequence[dict[str, Any]]) -> list[PaymentRowVM]:
    total = len(methods)
    out: list[PaymentRowVM] = []
    for i, m in enumerate(methods):
        position = i + 1
        out.append(
            PaymentRowVM(
                method_id=m["method_id"],
                name=m["name"],
                currency_label=currency_words(m.get("currency", "")),
                updated_label=updated_label(m.get("updated_at", "")),
                thumb_url=m.get("thumb_url", ""),
                has_qr=bool(m.get("has_qr")),
                active=bool(m.get("active")),
                position=position,
                total=total,
                movable=total > 1,
                up_to=max(0, i - 1),
                down_to=min(total - 1, i + 1),
                last_to=total - 1,
                handle_label=f"Mover «{m['name']}», posición {position} de {total}",
                more_label=f"Más opciones para «{m['name']}»",
                switch_label=f"{OFFERED}: {m['name']}",
                thumb_alt=f"QR de {m['name']}",
            )
        )
    return out


def moved(items: Sequence[Any], index: int, to: int) -> list[Any]:
    out = list(items)
    item = out.pop(index)
    out.insert(max(0, min(len(out), to)), item)
    return out
