"""How big a logo or brand element may be, and what the owner reads when one is refused
(m-24946266).

On 2026-11-03 a 5000 x 4112 PNG logo took the one `reflex` worker past its 512 MB cap
while its colours were read; the worker was killed and the tab lost its session. The
colour reading no longer copies the image at full size (`logo_palette._sampled`), and
this cap bounds what reaches the server at all: the dropzone refuses a bigger file in the
browser (react-dropzone `max_size`), and `_stage_logo_file` refuses it again on the server
for a client that skips the check. Pure: tested without Reflex.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Per file. Well above any logo export a small business has (Bianki's 5000 px PNGs weigh
#: under 1 MB) and above the 10 MB the fix was asked to accept.
MAX_BRAND_IMAGE_MB = 25
MAX_BRAND_IMAGE_BYTES = MAX_BRAND_IMAGE_MB * 1024 * 1024

#: How many images the brandboard's «+» takes in one drop (`_MAX_EXTRAS_PER_DROP`).
MAX_IMAGES_PER_DROP = 10

BRAND_IMAGE_TOO_LARGE = (
    f"Esa imagen pesa más de {MAX_BRAND_IMAGE_MB} MB. Pide a quien hizo tu logo una versión"
    " más liviana en PNG o JPG y súbela de nuevo."
)
BRAND_IMAGE_NOT_ACCEPTED = "Ese archivo no es una imagen. Sube una imagen en PNG o JPG."
BRAND_IMAGE_TOO_MANY = (
    f"Puedes subir hasta {MAX_IMAGES_PER_DROP} imágenes a la vez. Sube el resto después."
)


def rejection_message(rejected: Sequence[object] | None) -> str:
    """The owner's sentence for the files a brand dropzone refused (react-dropzone's
    `fileRejections`: `{"file": …, "errors": [{"code": …}]}` each). Size first: it is the
    one an owner can fix without changing the file's type."""
    codes: set[str] = set()
    for row in rejected or ():
        errors = row.get("errors", []) if isinstance(row, dict) else []
        for error in errors or ():
            if isinstance(error, dict):
                codes.add(str(error.get("code", "")))
    if "file-too-large" in codes:
        return BRAND_IMAGE_TOO_LARGE
    if "too-many-files" in codes:
        return BRAND_IMAGE_TOO_MANY
    return BRAND_IMAGE_NOT_ACCEPTED
