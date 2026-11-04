"""Numeric error policy; never expose Meta's localized message or response body."""

from __future__ import annotations

from typing import Any

_REVIEW = "Meta no aceptó este anuncio. Revisa su configuración en el administrador de anuncios."
_WAIT = "Meta está recibiendo muchas solicitudes. Espera unos minutos antes de intentar de nuevo."
UNKNOWN_WRITE_MESSAGE = (
    "No pudimos confirmar si Meta guardó el cambio. "
    "Revisa tu cuenta en el administrador de anuncios de Meta antes de repetirlo."
)
READ_ERROR_MESSAGE = "No pudimos consultar esta información en Meta. Intenta de nuevo más tarde."

# These are separate namespaces: 17/294/etc. are Graph codes, not subcodes.
CODE_MESSAGES = {
    17: _WAIT,
    613: _WAIT,
    80004: _WAIT,
    294: "Meta no permitió esta acción. Revisa los permisos de la cuenta publicitaria.",
    2654: _REVIEW,
    190: "Meta pidió volver a conectar la cuenta. Conéctala de nuevo en Cuentas conectadas.",
}
# Conservative copy for undocumented cases: do not invent a specific cause. The
# discovery ticket must confirm the finer diagnoses before these become actionable.
SUBCODE_MESSAGES = {
    1885183: (
        "No pudimos promocionar esta publicación. Revísala en el administrador de anuncios de Meta."
    ),
    1815199: "Revisa que Instagram esté vinculado a la cuenta publicitaria en Meta.",
    2238055: _REVIEW,
    2446149: _REVIEW,
    1885272: _REVIEW,
    1885650: _REVIEW,
    1885621: _REVIEW,
    1885029: _REVIEW,
    1885557: _REVIEW,
    1713092: _REVIEW,
    4841018: "Meta necesita más tiempo entre cambios. Espera antes de volver a editar el anuncio.",
    1373054: "Revisa que el botón del anuncio corresponda al objetivo que elegiste.",
    2446383: "Revisa que el botón del anuncio corresponda al objetivo que elegiste.",
}


class MarketingError(Exception):
    """Safe diagnostic metadata only; no request/response or platform message."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        subcode: int | None = None,
        http_status: int | None = None,
        retry_after: float | None = None,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.http_status = http_status
        self.retry_after = retry_after
        self.outcome_unknown = outcome_unknown


def error_number(value: Any) -> int | None:
    return value if type(value) is int else None


def platform_error(
    payload: dict[str, Any], *, status: int, retry_after: float | None, write: bool
) -> MarketingError:
    error = payload.get("error", {})
    error = error if isinstance(error, dict) else {}
    code = error_number(error.get("code"))
    subcode = error_number(error.get("error_subcode"))
    message = SUBCODE_MESSAGES.get(subcode) or CODE_MESSAGES.get(code)
    if message is None:
        message = _WAIT if status == 429 else (_REVIEW if write else READ_ERROR_MESSAGE)
    if write and status >= 500:
        message = UNKNOWN_WRITE_MESSAGE
    return MarketingError(
        message,
        code=code,
        subcode=subcode,
        http_status=status,
        retry_after=retry_after,
        outcome_unknown=write and status >= 500,
    )
