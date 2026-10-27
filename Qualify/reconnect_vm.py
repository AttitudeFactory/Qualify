"""Account-specific reconnect results shared by the original screens (m-24854865)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from qualify_api.connections.state_token import safe_return_path


def reconnect_origin(path: str, params: Mapping[str, object]) -> str:
    """Map the canonical responder tab back to its signed, query-free logical origin."""
    if path.rstrip("/") == "/responder":
        tab = str(params.get("tab", "mensajes") or "mensajes")
        return {"comentarios": "/inbox", "mensajes": "/conversations"}.get(tab, "")
    return safe_return_path(path)


@dataclass(frozen=True)
class ReconnectNotice:
    message: str = ""
    tone: str = "info"
    retry: bool = False
    help: bool = False


def reconnect_notice(code: str, account: str, *, origin: str = "/inbox") -> ReconnectNotice:
    """Closed outcomes, literal product copy; account comes only from a scoped read."""
    if code == "active":
        return ReconnectNotice(
            f"Listo: {account} está conectada otra vez. "
            "Estamos trayendo lo que llegó mientras tanto.",
            "ok",
        )
    if code == "permission_missing":
        missing = "ver tus comentarios" if origin == "/inbox" else "ver tus mensajes"
        return ReconnectNotice(
            f"{account} se conectó, pero falta una casilla para {missing}. "
            "Vuelve a conectarla y déjalas todas marcadas.",
            "warn",
            retry=True,
        )
    if code == "denied":
        return ReconnectNotice(
            "No se conectó: saliste antes de terminar en Facebook. "
            "Puedes intentarlo cuando quieras.",
            "warn",
            retry=True,
        )
    if code == "account_access_required":
        return ReconnectNotice(
            f"Esa cuenta de Facebook no administra {account}. "
            "Entra con la que la administra o pide ayuda.",
            "warn",
            retry=True,
            help=True,
        )
    if code in ("degraded", "invalid_state"):
        return ReconnectNotice(
            "No pudimos confirmar la conexión. Vuelve a intentarlo o pide ayuda.",
            "warn",
            retry=True,
            help=True,
        )
    return ReconnectNotice()
