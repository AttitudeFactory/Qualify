"""View models for TikTok in the app (m-24921091): the account card in «Tus redes» and the
«Enviar a TikTok como borrador» card on an approved piece.

Pure: no Reflex, no database, no network — the whitelist and the copy are asserted by plain
unit tests (`test_tiktok_vm.py`). Like `connections_vm.ConnectionVM`, nothing here can carry
a token: an account is an id, a display name, a status and the sentences the owner reads.

**Assisted, never autonomous.** Qualify only puts the video in the creator's TikTok drafts;
the owner finishes and publishes it in the TikTok app. Nothing here schedules (ADR 23c), and
no sentence promises otherwise (`qualify-copy-es` §6).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

PLATFORM = "tiktok"
UPLOAD_SCOPE = "video.upload"

# --- «Tus redes»: the TikTok card ---------------------------------------------------------

SECTION_TITLE = "TikTok"
#: The benefit, said before the owner connects anything (qualify-ux §2).
INVITE_TITLE = "Lleva tus videos también a TikTok"
INVITE_BODY = (
    "Conecta tu TikTok y envía tus videos aprobados directo a tus borradores. "
    "Tú les das el último toque y los publicas desde la aplicación de TikTok."
)
CONNECT_ACTION = "Conectar TikTok"
CAN_DO = "enviar tus videos aprobados a tus borradores de TikTok"
#: Nothing is published or scheduled from Qualify: the owner decides in TikTok.
DRAFTS_ONLY_NOTE = "Qualify no publica en TikTok: tú decides cuándo sale, desde la aplicación."
UNAVAILABLE_NOTE = "Por ahora no puedes conectar TikTok desde aquí."
FALLBACK_NAME = "Tu cuenta de TikTok"
DISCONNECTED_PROBLEM = (
    "Tu TikTok está desconectado. Para seguir enviando videos a tus borradores, "
    "pulsa «Volver a conectar»."
)
REVOKED_PROBLEM = (
    "Desconectaste esta cuenta. Para volver a enviar videos a tus borradores, "
    "pulsa «Volver a conectar»."
)
#: Same words as `qualify_api.connections.tiktok_service.NOTICE_PERMISSION_MISSING` (a test
#: keeps them equal): the backend says it after the round trip, the card says it after.
PERMISSION_PROBLEM = (
    "Falta el permiso para enviar videos a tus borradores de TikTok. "
    "Vuelve a conectar la cuenta y acepta ese permiso."
)
#: Same words as `tiktok_service.NOTICE_DEVELOPMENT` (kept equal by a test).
DEVELOPMENT_NOTICE = (
    "TikTok todavía no ha revisado la aplicación de Qualify. Mientras tanto, solo puedes "
    "enviar borradores a cuentas autorizadas como probadoras, y los videos solo los verás tú."
)
DISCONNECT_TITLE = "¿Desconectar tu TikTok?"
DISCONNECT_BODY = (
    "Ya no podrás enviar videos a los borradores de esta cuenta desde Qualify. Lo que ya "
    "está en TikTok no cambia. Puedes conectarla de nuevo cuando quieras."
)
CONNECTED_TITLE = "TikTok conectado"
CONNECTED_BODY = (
    "Ya puedes enviar tus videos aprobados a tus borradores de TikTok. "
    "Los publicas tú, desde la aplicación."
)

LOAD_FAILED = "No pudimos cargar tu TikTok. Recarga la página en un momento."
CONNECT_FAILED = "No se pudo iniciar la conexión con TikTok. Vuelve a intentarlo en un momento."
DISCONNECT_FAILED = "No pudimos desconectar tu TikTok. Vuelve a intentarlo en un momento."
NOT_FOUND = "Esa cuenta de TikTok ya no está conectada. Actualizamos la lista."

#: `?connect=<code>&platform=tiktok` (`http/tiktok_routes.py`) → (message, tone). A closed
#: vocabulary: the four outcomes of `TikTokConnectService` plus the route's own two codes.
#: «active» shows as the «TikTok conectado» panel; its text is the notice-only fallback.
CONNECT_RESULT_NOTICES: dict[str, tuple[str, str]] = {
    "active": ("Listo: tu TikTok está conectado.", "ok"),
    "degraded": (
        "Tu TikTok se conectó, pero TikTok todavía no confirma el acceso. Si en unos minutos "
        "su tarjeta sigue diciendo «Desconectada», toca «Volver a conectar».",
        "warn",
    ),
    "permission_missing": (PERMISSION_PROBLEM, "warn"),
    "account_access_required": (
        "Entraste con otra cuenta de TikTok. Vuelve a conectar y entra con la cuenta que ya "
        "tenías conectada.",
        "warn",
    ),
    "denied": ("Cancelaste la conexión con TikTok. No se guardó nada.", "info"),
    "invalid_state": (
        "El enlace de conexión expiró o ya se usó. Pulsa «Conectar TikTok» de nuevo.",
        "warn",
    ),
}


def is_tiktok_result(params: dict[str, object]) -> bool:
    """The OAuth callback that came back is TikTok's (`&platform=tiktok`), not Meta's."""
    return str(params.get("platform", "") or "") == PLATFORM


def connect_result_notice(code: str) -> tuple[str, str]:
    """(message, tone) for a TikTok `?connect=` code; ("", "info") for none or junk — the
    value arrives in the URL, so an unknown one is ignored rather than echoed."""
    return CONNECT_RESULT_NOTICES.get(code, ("", "info"))


@dataclass
class TikTokAccountVM:
    """One TikTok account as the card shows it. Whitelisted: no field can hold a token."""

    id: str
    name: str
    status: str  # "active" | "degraded" | "revoked"
    #: What is wrong and how to fix it, in the owner's words; "" when it works.
    problem: str = ""
    #: The status line while TikTok has not audited the app (`tiktok_access_notice`).
    notice: str = ""
    #: Whether an approved video can be sent to this account's drafts right now.
    can_send: bool = False
    #: The fix is to accept a permission again — the card says «Sin acceso» (§7.3).
    permission_missing: bool = False


def build_account_vm(
    *,
    connection_id: str,
    display_name: str | None,
    status: str,
    granted_scopes: Sequence[str],
    reconnect_reason: str | None,
    access_notice: str,
) -> TikTokAccountVM:
    """The card of one `social_connections` row with `platform = 'tiktok'`."""
    has_upload = UPLOAD_SCOPE in granted_scopes
    if status == "revoked":
        problem = REVOKED_PROBLEM
    elif reconnect_reason == "permission_missing" or (status == "active" and not has_upload):
        problem = PERMISSION_PROBLEM
    elif status != "active":
        problem = DISCONNECTED_PROBLEM
    else:
        problem = ""
    return TikTokAccountVM(
        id=connection_id,
        name=(display_name or "").strip() or FALLBACK_NAME,
        status=status,
        problem=problem,
        notice=access_notice if status == "active" else "",
        can_send=status == "active" and has_upload,
        permission_missing=problem == PERMISSION_PROBLEM,
    )


def first_sendable(accounts: Sequence[TikTokAccountVM]) -> TikTokAccountVM | None:
    """The account an approved video goes to: the newest one that can receive it."""
    return next((account for account in accounts if account.can_send), None)


# --- an approved piece: «Enviar a TikTok como borrador» ----------------------------------

DRAFT_TITLE = "Llévalo también a TikTok"
DRAFT_BODY = (
    "Lo dejamos en tus borradores de TikTok. Tú le das el último toque y lo publicas "
    "desde la aplicación."
)
DRAFT_ACTION = "Enviar a TikTok como borrador"
DRAFT_RETRY = "Intentar de nuevo"
DRAFT_AGAIN = "Enviar otra vez"
DRAFT_ACCOUNT_PREFIX = "Va a: "
DRAFT_SENDING = "Estamos enviando tu video a los borradores de TikTok."
#: The backend's own words for a draft that landed (`tiktok_drafts.IN_INBOX_TEXT`).
DRAFT_IN_INBOX = "Listo: abre TikTok y termina tu publicación desde Borradores."
DRAFT_FAILED_DEFAULT = "TikTok no pudo recibir el borrador. Inténtalo de nuevo en unos minutos."
DRAFT_STILL_SENDING = (
    "TikTok todavía está recibiendo tu video. Vuelve a esta pantalla en unos minutos para "
    "ver si ya está en tus borradores."
)
DRAFT_SEND_FAILED = "No pudimos enviar tu video a TikTok. Vuelve a intentarlo en un momento."
#: The piece is approved and a video, but no TikTok account can receive it yet.
DRAFT_CONNECT_HINT = "¿Tienes TikTok? Conéctalo y envía este video a tus borradores."
DRAFT_CONNECT_LINK = "Conectar TikTok en Tus redes"
DRAFT_RECONNECT_HINT = "Tu TikTok necesita que lo vuelvas a conectar para recibir este video."
DRAFT_RECONNECT_LINK = "Ir a Tus redes"

STATUS_PENDING = "pending"
STATUS_UPLOADING = "uploading"
STATUS_PROCESSING = "processing"
STATUS_IN_INBOX = "in_inbox"
STATUS_FAILED = "failed"
#: A refusal before anything reached TikTok (`DraftRefused`): not a stored status.
STATUS_REFUSED = "refused"

#: The pill of a draft: (label, tone). Text always, never colour alone.
DRAFT_PILLS: dict[str, tuple[str, str]] = {
    STATUS_PENDING: ("Enviando…", "info"),
    STATUS_UPLOADING: ("Enviando…", "info"),
    STATUS_PROCESSING: ("Enviando…", "info"),
    STATUS_IN_INBOX: ("En tus borradores de TikTok", "ok"),
    STATUS_FAILED: ("No se pudo enviar", "warn"),
    STATUS_REFUSED: ("No se envió", "warn"),
}


@dataclass
class TikTokDraftVM:
    """The last draft of this piece sent to TikTok — or none (`status == ""`)."""

    draft_id: str = ""
    status: str = ""
    message: str = ""
    label: str = ""
    tone: str = "neutral"
    in_progress: bool = False
    done: bool = False
    failed: bool = False


NO_DRAFT = TikTokDraftVM()


def build_draft_vm(*, draft_id: str, status: str, message: str = "") -> TikTokDraftVM:
    """One draft's state for the card. `message` is the backend's sentence (already in the
    owner's words); a missing one falls back to this module's copy for the status."""
    label, tone = DRAFT_PILLS.get(status, ("Enviando…", "info"))
    failed = status in (STATUS_FAILED, STATUS_REFUSED)
    done = status == STATUS_IN_INBOX
    if not message:
        message = DRAFT_IN_INBOX if done else DRAFT_FAILED_DEFAULT if failed else DRAFT_SENDING
    return TikTokDraftVM(
        draft_id=draft_id,
        status=status,
        message=message,
        label=label,
        tone=tone,
        in_progress=not failed and not done,
        done=done,
        failed=failed,
    )


def refused_vm(message: str) -> TikTokDraftVM:
    """Nothing was sent (the piece is not ready, the account needs a reconnect…)."""
    return build_draft_vm(draft_id="", status=STATUS_REFUSED, message=message or DRAFT_SEND_FAILED)


@dataclass(frozen=True)
class TikTokTarget:
    """Whether a piece can go to TikTok at all (one video), and which template output."""

    eligible: bool
    output_port: str = ""


NOT_A_TARGET = TikTokTarget(False)


def pick_target(
    outputs: Sequence[tuple[str, Sequence[str]]], media_types: Sequence[str]
) -> TikTokTarget:
    """The video TikTok receives: TikTok takes ONE video, never an image or a carousel.

    `outputs` are a template piece's ports with their media types (publisher names,
    "VIDEO"/"IMAGE"): the `reel` port first, else the first single-video port. A piece
    without ports qualifies when it is exactly one video."""
    single_video = [port for port, types in outputs if tuple(types) == ("VIDEO",)]
    if outputs:
        if not single_video:
            return NOT_A_TARGET
        port = "reel" if "reel" in single_video else single_video[0]
        return TikTokTarget(True, port)
    return TikTokTarget(True) if tuple(media_types) == ("VIDEO",) else NOT_A_TARGET


def next_attempt(failed_attempts: int) -> int:
    """The `attempt` of the next send: a failed draft is final (settle-once), so trying
    again is attempt N+1; otherwise the same key, which returns the draft already sent
    instead of putting a second one in the owner's TikTok (idempotency)."""
    return max(failed_attempts, 0) + 1


#: How the card polls a draft still being received: one read every few seconds, then it
#: stops and says to come back (never an endless spinner).
POLL_SECONDS = 3.0
POLL_MAX_READS = 20
