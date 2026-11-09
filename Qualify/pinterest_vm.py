"""Public, ephemeral Pinterest choices; no credential or arbitrary download URL."""

from __future__ import annotations

from dataclasses import dataclass

from qualify_api.pinterest.client import Pin


@dataclass(frozen=True)
class BoardVM:
    id: str
    name: str


@dataclass(frozen=True)
class PinVM:
    id: str
    title: str
    thumbnail: str
    url: str
    attribution: str
    usable: bool


def pin_vm(pin: Pin) -> PinVM:
    images = sorted(pin.images, key=lambda image: image.variant != "400x300")
    owner = getattr(pin, "board_owner", "")
    return PinVM(
        id=pin.id,
        title=pin.title or "Idea de Pinterest",
        thumbnail=images[0].url if images else "",
        url=pin.url,
        attribution=f"Pinterest · tablero de @{owner}" if owner else "Pinterest",
        usable=bool(images),
    )


def error_text(kind: str) -> str:
    return {
        "role": (
            "Solo el propietario o un administrador del negocio puede conectar "
            "o desconectar Pinterest."
        ),
        "authentication": "Vuelve a conectar Pinterest para ver tus ideas.",
        "reconnect": "Vuelve a conectar Pinterest para ver tus ideas.",
        "permission": "Falta permiso para leer este tablero. Vuelve a conectar Pinterest.",
        "rate_limit": "Pinterest recibió muchas consultas. Espera un minuto y vuelve a intentarlo.",
        "not_found": "Ese tablero o Pin ya no está disponible. Elige otro.",
        "invalid_state": "La conexión venció o ya se usó. Pulsa Conectar Pinterest otra vez.",
    }.get(kind, "No pudimos consultar Pinterest. Inténtalo de nuevo en un minuto.")


def connect_notice(code: str) -> tuple[str, str]:
    return {
        "connected": ("Pinterest conectado. Elige un tablero para ver sus ideas.", "ok"),
        "denied": ("Cancelaste la conexión. Puedes conectar Pinterest cuando quieras.", "info"),
        "invalid_state": (error_text("invalid_state"), "warn"),
        "degraded": ("No pudimos terminar la conexión. Vuelve a conectar Pinterest.", "warn"),
    }.get(code, ("", "info"))


def selected_sources(
    sources: list[dict[str, str]], images: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Only references still selected travel with the generation request."""
    keys = {image["key"] for image in images}
    return [dict(source) for source in sources if source.get("image_key") in keys]
