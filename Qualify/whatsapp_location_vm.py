"""«Tu local en el mapa» in Tu número › Perfil (m-24945889, `docs/ux-whatsapp-atajos.md`
§3) — the words and the pure rules: reading a point out of a Google Maps link, the
browser's position and its accuracy, and the way back to the chat. Nothing here touches
the network: a short link (maps.app.goo.gl) is not followed — the owner is told how to
copy the long one."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote, urlsplit

MAP_TITLE: Final = "Tu local en el mapa"
MAP_HELP: Final = "Así tu cliente abre la ruta con un toque."
USE_MY_LOCATION: Final = "Usar mi ubicación"
GEO_EXPLAIN: Final = (
    "Tócalo estando en tu local: tu navegador te pide permiso para ver dónde estás."
)
GEO_WAITING: Final = "Buscando tu ubicación…"
GEO_DENIED: Final = "Tu navegador no nos dejó ver la ubicación. Pega el enlace de Google Maps."
LINK_LABEL: Final = "Enlace de Google Maps de tu local"
LINK_PLACEHOLDER: Final = "Por ejemplo: https://www.google.com/maps/place/…"
LINK_HELP: Final = (
    "En Google Maps, abre tu local y copia el enlace completo de la barra de direcciones."
)
LINK_SAVE: Final = "Guardar en el mapa"
LINK_BAD: Final = (
    "No pudimos leer ese enlace. Abre tu local en Google Maps, copia el enlace completo "
    "y pégalo otra vez."
)
LINK_SHORT: Final = (
    "Ese enlace es corto y todavía no podemos leerlo. Ábrelo en tu navegador, copia el "
    "enlace completo que aparece arriba y pégalo aquí."
)
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

_NUMBER = r"(-?\d{1,3}(?:\.\d+)?)"
_PLACE = re.compile(r"!3d" + _NUMBER + r"!4d" + _NUMBER)
_AT = re.compile(r"@" + _NUMBER + r"," + _NUMBER)
_QUERY = re.compile(r"(?:^|[?&])(?:q|query|ll|destination|center)=" + _NUMBER + r",\s*" + _NUMBER)
_SHORT_HOSTS: Final = frozenset({"maps.app.goo.gl", "goo.gl", "g.co"})


@dataclass(frozen=True)
class LinkPoint:
    """`parse_maps_link`'s answer: a point, or why not (`error` is the owner's words)."""

    latitude: float | None = None
    longitude: float | None = None
    error: str = ""


def _is_google_maps(host: str, path: str) -> bool:
    host = host.lower().removeprefix("www.")
    if host.startswith("maps.google."):
        return True
    return host.startswith("google.") and path.startswith("/maps")


def _point(lat: str, lng: str) -> LinkPoint:
    latitude, longitude = float(lat), float(lng)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return LinkPoint(error=LINK_BAD)
    return LinkPoint(latitude=latitude, longitude=longitude)


def parse_maps_link(text: str) -> LinkPoint:
    """The point of a Google Maps link: the place's own pin (`!3d…!4d…`) first, then
    `?q=`/`query=`/`ll=` coordinates, then the view's centre (`@lat,lng`). Anything that
    is not a Google Maps link is refused; a short link is refused with how to fix it."""
    raw = (text or "").strip()
    if not raw:
        return LinkPoint(error=LINK_BAD)
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return LinkPoint(error=LINK_BAD)
    host = (parts.hostname or "").lower()
    if host in _SHORT_HOSTS:
        return LinkPoint(error=LINK_SHORT)
    if parts.scheme not in ("http", "https") or not _is_google_maps(host, parts.path):
        return LinkPoint(error=LINK_BAD)
    body = unquote(parts.path + "?" + parts.query)
    for pattern in (_PLACE, _QUERY, _AT):
        found = pattern.search(body if pattern is not _QUERY else unquote(parts.query))
        if found:
            return _point(found.group(1), found.group(2))
    return LinkPoint(error=LINK_BAD)


def approximate_note(accuracy_m: float) -> str:
    """«La ubicación salió aproximada (a unos 300 m)…» past `MAX_ACCURACY_M`, else ""."""
    if accuracy_m <= MAX_ACCURACY_M:
        return ""
    rounded = max(150, int(round(accuracy_m / 50.0)) * 50)
    return (
        f"La ubicación salió aproximada (a unos {rounded} m). Mejor pega el enlace de Google Maps."
    )


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
