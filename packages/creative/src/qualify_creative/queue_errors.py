"""Shared, pure presentation of generation queue failures."""

from qualify_creative.enums import FailureReason

FINAL_EXPIRED_TEXT = (
    "La vista previa de este video ya venció. "
    "Crea una vista previa nueva para hacer el video final."
)

UNCERTAIN_REASON = FailureReason.SUBMISSION_UNCERTAIN.value
UNCERTAIN_PUBLICATION_TEXT = (
    "No pudimos confirmar el estado de tu publicación. "
    "El equipo debe revisarlo antes de intentarlo de nuevo."
)
UNCERTAIN_VIDEO_TEXT = (
    "No pudimos confirmar el estado de tu video. "
    "El equipo debe revisarlo antes de intentarlo de nuevo."
)


def uncertain_error(value: object) -> bool:
    return value in (UNCERTAIN_REASON, UNCERTAIN_PUBLICATION_TEXT, UNCERTAIN_VIDEO_TEXT)
