"""The piece's advertising button and owner-supplied HTTPS destination (m-24828975)."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from enum import StrEnum
from urllib.parse import urlsplit


class AdCTA(StrEnum):
    LEARN_MORE = "LEARN_MORE"
    WHATSAPP_MESSAGE = "WHATSAPP_MESSAGE"
    MESSAGE_PAGE = "MESSAGE_PAGE"
    ORDER_NOW = "ORDER_NOW"
    BOOK_TRAVEL = "BOOK_TRAVEL"
    BOOK_NOW = "BOOK_NOW"
    GET_QUOTE = "GET_QUOTE"
    CONTACT_US = "CONTACT_US"
    CALL_NOW = "CALL_NOW"
    SIGN_UP = "SIGN_UP"
    SHOP_NOW = "SHOP_NOW"


AD_CTA_LABELS: dict[AdCTA, str] = {
    AdCTA.LEARN_MORE: "Más información",
    AdCTA.WHATSAPP_MESSAGE: "Enviar mensaje por WhatsApp",
    AdCTA.MESSAGE_PAGE: "Enviar mensaje",
    AdCTA.ORDER_NOW: "Pedir ahora",
    AdCTA.BOOK_TRAVEL: "Reservar viaje",
    AdCTA.BOOK_NOW: "Reservar",
    AdCTA.GET_QUOTE: "Solicitar cotización",
    AdCTA.CONTACT_US: "Contáctanos",
    AdCTA.CALL_NOW: "Llamar",
    AdCTA.SIGN_UP: "Registrarte",
    AdCTA.SHOP_NOW: "Comprar",
}


def _plain(value: str) -> str:
    return " ".join(
        "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
        .replace("_", " ")
        .replace("-", " ")
        .casefold()
        .split()
    )


_LEGACY = {_plain(cta.value): cta for cta in AdCTA} | {
    _plain(label): cta for cta, label in AD_CTA_LABELS.items()
}
_LEGACY.update(
    {
        "learn more": AdCTA.LEARN_MORE,
        "saber mas": AdCTA.LEARN_MORE,
        "mas informacion": AdCTA.LEARN_MORE,
        "comprar ahora": AdCTA.SHOP_NOW,
        "contactar": AdCTA.CONTACT_US,
        "contactanos": AdCTA.CONTACT_US,
        "registrarse": AdCTA.SIGN_UP,
        "send message": AdCTA.MESSAGE_PAGE,
        "instagram message": AdCTA.MESSAGE_PAGE,
        "whatsapp": AdCTA.WHATSAPP_MESSAGE,
        "enviar whatsapp": AdCTA.WHATSAPP_MESSAGE,
        "book": AdCTA.BOOK_NOW,
    }
)


def normalize_legacy_ad_cta(value: object) -> AdCTA | None:
    """Project old free text without rewriting stored history or inventing a live ad type."""
    if value is None:
        return None
    if isinstance(value, AdCTA):
        return value
    if isinstance(value, str):
        return _LEGACY.get(_plain(value), AdCTA.LEARN_MORE)
    return AdCTA.LEARN_MORE


def validate_ad_destination_url(value: str | None) -> str | None:
    """Validate text only; never resolve, fetch, follow redirects or infer a destination."""
    if value is None or value == "":
        return None
    message = "Escribe un enlace completo que empiece por https://, sin espacios."
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError(message)
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise ValueError(message)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
        ascii_host = host.encode("idna").decode("ascii")
    except (ValueError, UnicodeError):
        raise ValueError(message) from None
    if (
        parsed.scheme != "https"
        or not ascii_host
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        and not 1 <= port <= 65535
        or any(not label or len(label) > 63 for label in ascii_host.rstrip(".").split("."))
    ):
        raise ValueError(message)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-zA-Z0-9.-]+", ascii_host):
            raise ValueError(message) from None
        if "." not in ascii_host.rstrip(".") or ascii_host.rstrip(".").casefold() == "localhost":
            raise ValueError(message) from None
        if any(label.startswith("-") or label.endswith("-") for label in ascii_host.split(".")):
            raise ValueError(message) from None
    else:
        if not address.is_global:
            raise ValueError(message)
    return value
