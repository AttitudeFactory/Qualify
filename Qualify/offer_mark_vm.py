"""«Usar como tu oferta» on a piece (m-24945889, `docs/ux-whatsapp-atajos.md` §2) — the
words and the pure rules of the one small control shown in Por aprobar and in the
Planificador's panel. One offer per business: marking another replaces it and says so,
with «Deshacer»; nothing here sends anything (the chat's «Tu oferta» does, on a tap)."""

from __future__ import annotations

from typing import Final

MARK_LABEL: Final = "Usar como tu oferta"
UNMARK_LABEL: Final = "Dejar de usar como tu oferta"
NOT_APPROVED_HINT: Final = "Apruébala primero para usarla como tu oferta."
RETENTION_NOTE: Final = "Mientras sea tu oferta, no se borra."
OFFER_BADGE: Final = "Tu oferta"
UNMARKED_TOAST: Final = "Listo: ya no tienes oferta marcada."
UNDO_LABEL: Final = "Deshacer"
UNDONE_TOAST: Final = "Listo: dejamos tu oferta como estaba."
MARK_FAILED: Final = "No pudimos marcar tu oferta. Vuelve a intentarlo en un momento."
UNMARK_FAILED: Final = "No pudimos quitar tu oferta. Vuelve a intentarlo en un momento."
NO_SESSION: Final = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
#: The statuses that may be an offer (the backend's `PROMOTABLE_STATUSES`).
PROMOTABLE: Final = frozenset({"approved", "staged", "published"})


def marked_toast(title: str, previous_title: str = "") -> str:
    """«Listo: «2x1 martes» es tu oferta. Antes era «Combo vecino».» (6 s, «Deshacer»)."""
    name = title.strip() or "esta pieza"
    head = f"Listo: «{name}» es tu oferta."
    before = previous_title.strip()
    return f"{head} Antes era «{before}»." if before else head
