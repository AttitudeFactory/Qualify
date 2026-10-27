"""Shared owner-facing connection vocabulary (m-24854866).

Display values only, never new server states. Revocation can also mean a manual
unlink; a revoked state alone does not prove that a Facebook permission was removed.
"""

CONNECTED = "Conectada"
DISCONNECTED = "Desconectada"
NO_ACCESS = "Sin acceso"
RECONNECT_ACTION = "Volver a conectar"
ACCESS_HELP = "¿No tienes acceso a ese Facebook? Pide ayuda"
WHATSAPP_SUPPORT_ACTION = "Avisar al equipo de Qualify"
WHATSAPP_RECONNECT_HINT = "Este arreglo lo hace el equipo de Qualify"

STATUS_LABELS: dict[str, tuple[str, str, str]] = {
    "active": (CONNECTED, "ok", "circle-check"),
    "degraded": (DISCONNECTED, "warn", "triangle-alert"),
    "revoked": (DISCONNECTED, "warn", "circle-x"),
}

DISCONNECTED_NOTICE = (
    "Esta cuenta está desconectada. Lo que ya tenías guardado sigue aquí. "
    "Pulsa «Volver a conectar» para recibir comentarios y mensajes nuevos."
)
PERMISSION_MISSING_NOTICE = (
    "Esta cuenta no tiene el permiso necesario. Lo que ya tenías guardado sigue aquí. "
    "Pulsa «Volver a conectar» y acepta el permiso para continuar."
)


def connection_status_display(status: str) -> tuple[str, str]:
    """An unknown server status must never be shown as a raw internal value."""
    if status == "pending":
        return "Conectando…", "info"
    label, tone, _icon = STATUS_LABELS.get(status, ("Sin verificar", "neutral", "circle-help"))
    return label, tone
