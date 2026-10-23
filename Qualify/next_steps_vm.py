"""m-24842961 (NAV-3): the words of «no dead end» (N8) and «every task ends with its next
step» (N3), shared by the screens that end in «nobody is waiting» — pure, no Reflex.

N3 (docs/ux-guia-navegacion.md §4): a finished task shows a plain confirmation + ONE solid
button to the next job + a soft one to go back, never only a toast. N8: every empty state
says what is missing and leads to the step before it. Both meet when the owner has answered
everyone: the next job is the next publication («¡Al día! → Crear publicación»).
"""

from __future__ import annotations

from typing import Final

#: Where «Crear publicación» goes (the menu entry of the same name, `ui/layout.py`).
CREATE_ROUTE: Final = "/create"
CREATE_LABEL: Final = "Crear publicación"

#: Zero people waiting for an answer (ticket m-24842961, exact copy).
ALL_CLEAR_TITLE: Final = "¡Al día!"
ALL_CLEAR_BODY: Final = "No hay nadie esperando tu respuesta."
#: The same moment on Comentarios, scoped to comments: private messages or WhatsApp
#: chats may still wait, so the owner must not read «nadie» there.
COMMENTS_ALL_CLEAR: Final = "¡Al día con tus comentarios! No queda ninguno esperando respuesta."

#: After answering a comment while others still wait: the next one is on screen.
NEXT_PENDING_LABEL: Final = "Responder el siguiente"
#: The soft button that closes a confirmation and leaves the owner where they were.
DISMISS_LABEL: Final = "Entendido"


def all_clear(total: int, pending: int) -> bool:
    """True when there is something on the list and none of it waits for the owner —
    the moment to say «¡Al día!» instead of a list with nothing to do. An empty list is
    not «al día»: it is «nobody wrote yet», a different empty state."""
    return total > 0 and pending == 0
