"""«Tu local en el mapa» in Tu número › Perfil (m-24945889, `docs/ux-whatsapp-atajos.md`
§3) — the words and the pure rules: the browser's position and its accuracy, what to say
for each reason a Google Maps link gave no point, and the way back to the chat. The link
itself is read only by the backend (`qualify_api.whatsapp.maps_link.resolve_maps_link`,
which also follows the short links «Compartir» gives)."""

from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

MAP_TITLE: Final = "Tu local en el mapa"
MAP_HELP: Final = "Así tu cliente abre la ruta con un toque."
USE_MY_LOCATION: Final = "Usar mi ubicación"
GEO_EXPLAIN: Final = (
    "Tócalo estando en tu local: tu navegador te pide permiso para ver dónde estás."
)
GEO_WAITING: Final = "Buscando tu ubicación…"
GEO_DENIED: Final = "Tu navegador no nos dejó ver la ubicación. Pega el enlace de Google Maps."
LINK_LABEL: Final = "Enlace de Google Maps de tu local"
LINK_PLACEHOLDER: Final = "Por ejemplo: https://maps.app.goo.gl/…"
LINK_HELP: Final = "En Google Maps, abre tu local, toca «Compartir» y copia el enlace."
LINK_SAVE: Final = "Guardar en el mapa"
LINK_READING: Final = "Leyendo el enlace…"
#: `MapsLinkResult.reason` → the owner's words, each with the next step.
LINK_NOT_MAPS: Final = (
    "Ese enlace no es de Google Maps. En Google Maps, abre tu local, toca «Compartir» "
    "y copia el enlace."
)
LINK_BAD: Final = (
    "No pudimos leer ese enlace. Copia el de «Compartir» en Google Maps y pégalo otra vez."
)
LINK_NO_POINT: Final = (
    "Ese enlace no marca un lugar. Abre tu local en Google Maps, toca «Compartir» y "
    "copia el enlace."
)
LINK_UNREACHABLE: Final = "No pudimos abrir el enlace ahora. Inténtalo otra vez en un momento."
LINK_REASONS: Final[dict[str, str]] = {
    "not_a_maps_link": LINK_NOT_MAPS,
    "unsafe_redirect": LINK_BAD,
    "no_point": LINK_NO_POINT,
    "unreachable": LINK_UNREACHABLE,
}


def link_refusal(reason: str) -> str:
    return LINK_REASONS.get(reason, LINK_BAD)


SAVED: Final = "Listo: tu local quedó en el mapa."
VIEW_ON_MAP: Final = "Ver en el mapa"
REMOVE: Final = "Quitar del mapa"
REMOVED: Final = "Listo: quitamos tu local del mapa. Tu dirección sigue igual."
NOT_ON_MAP: Final = "Tu local todavía no está en el mapa."
SAVE_FAILED: Final = "No pudimos guardar tu local en el mapa. Vuelve a intentarlo en un momento."
LOAD_FAILED: Final = "No pudimos leer tu local en el mapa. Vuelve a intentarlo en un momento."
NO_SESSION: Final = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
BACK_TO_CHAT: Final = "Volver al chat"
#: Past this many meters the browser's position is not good enough for a pin.
MAX_ACCURACY_M: Final = 100


def approximate_note(accuracy_m: float) -> str:
    """«La ubicación salió aproximada (a unos 300 m)…» past `MAX_ACCURACY_M`, else ""."""
    if accuracy_m <= MAX_ACCURACY_M:
        return ""
    rounded = max(150, int(round(accuracy_m / 50.0)) * 50)
    return (
        f"La ubicación salió aproximada (a unos {rounded} m). Mejor pega el enlace de Google Maps."
    )


def position_point(result: object) -> tuple[float, float] | str:
    """The browser's answer → (lat, lng), or the owner's words for why not: refused,
    malformed, out of range, or vaguer than `MAX_ACCURACY_M`."""
    if not isinstance(result, dict) or "error" in result:
        return GEO_DENIED
    try:
        lat, lng = float(result["lat"]), float(result["lng"])
        accuracy = float(result.get("acc") or 0)
    except (KeyError, TypeError, ValueError):
        return GEO_DENIED
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return GEO_DENIED
    return approximate_note(accuracy) or (lat, lng)


def point_label(latitude: object, longitude: object) -> str:
    """The stored point, plain: «7.76712, -72.22501» (five decimals ≈ 1 m)."""
    try:
        return f"{float(str(latitude)):.5f}, {float(str(longitude)):.5f}"
    except (TypeError, ValueError):
        return ""


def chat_back_path(path: str) -> str:
    """`?volver=` only when it is the app's own WhatsApp chats address (already made
    safe by `catalog_vm.safe_return_path`); anything else is dropped."""
    from urllib.parse import parse_qs  # noqa: PLC0415

    if not path:
        return ""
    parts = urlsplit(path)
    tabs = parse_qs(parts.query).get("tab", [])
    return path if parts.path == "/whatsapp" and tabs == ["chats"] else ""


#: The browser's position (a Promise the event's callback receives): never throws.
GEO_JS: Final = (
    "new Promise((resolve) => {"
    " if (!navigator.geolocation) { resolve({error: 'unavailable'}); return; }"
    " navigator.geolocation.getCurrentPosition("
    "  (p) => resolve({lat: p.coords.latitude, lng: p.coords.longitude,"
    " acc: p.coords.accuracy}),"
    "  (e) => resolve({error: String(e && e.code)}),"
    "  {enableHighAccuracy: true, timeout: 15000, maximumAge: 0});"
    "})"
)
