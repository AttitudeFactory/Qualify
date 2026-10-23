"""The owner's words for why a publish attempt failed (NAV-11, m-24849129).

`publish_attempts.platform_error_code` is a diagnostic — `connection_not_active:expired`,
`container_error`, `platform_error_code:9007`, `http_500`, an Instagram error type — and
it stays exactly that in the database and the logs. What reaches the publish screen is
`failure_text(code)`: Spanish, plain, with what to do next, and never the code itself
(qualify-copy-es). The codes come from `publishing.service` and `publishing.client`.
"""

from __future__ import annotations

from typing import Final

from qualify_api.publishing.service import (
    CEILING_EXCEEDED,
    CHILD_ERROR_PREFIX,
    CONNECTION_NOT_ACTIVE_PREFIX,
    CONTAINER_ERROR_PREFIX,
    PLATFORM_CODE_PREFIX,
)

CONNECTION_TEXT: Final = (
    "Tu cuenta de Instagram se desconectó. Vuelve a conectarla en Tus redes y publica de nuevo."
)
SLOW_TEXT: Final = (
    "Instagram tardó demasiado en preparar la publicación. Vuelve a intentarlo en unos minutos."
)
FILE_REFUSED_TEXT: Final = (
    "Instagram no aceptó el archivo. Revisa la foto o el video y vuelve a intentarlo."
)
CAROUSEL_ITEM_TEXT: Final = (
    "Instagram no aceptó una de las fotos o videos del carrusel. "
    "Revisa los archivos y vuelve a intentarlo."
)
REFUSED_TEXT: Final = "Instagram no aceptó la publicación. Vuelve a intentarlo en unos minutos."
UPLOAD_TEXT: Final = "El archivo no llegó a Instagram. Vuelve a intentarlo en unos minutos."
GENERIC_TEXT: Final = "No se pudo publicar. Vuelve a intentarlo en un momento."


def failure_text(code: str | None) -> str:
    """What the owner reads for a failed attempt with this diagnostic code."""
    code = (code or "").strip()
    if not code:
        return GENERIC_TEXT
    if code.startswith(f"{CONNECTION_NOT_ACTIVE_PREFIX}:"):
        return CONNECTION_TEXT
    if code == CEILING_EXCEEDED:
        return SLOW_TEXT
    if code.startswith(f"{CHILD_ERROR_PREFIX}:"):
        return CAROUSEL_ITEM_TEXT
    if code.startswith(f"{CONTAINER_ERROR_PREFIX}_"):
        return FILE_REFUSED_TEXT
    if code.startswith(f"{PLATFORM_CODE_PREFIX}:"):
        return REFUSED_TEXT
    if code.startswith("http_") or code in ("upload_failed", "unrecognised_response"):
        return UPLOAD_TEXT
    return GENERIC_TEXT
