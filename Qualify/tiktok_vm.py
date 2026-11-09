"""View models for TikTok in the app (m-24921091): the account card in «Tus redes» and the
«Enviar a TikTok» card on an approved piece.

Pure: no Reflex, no database, no network — the whitelist and the copy are asserted by plain
unit tests (`test_tiktok_vm.py`). Like `connections_vm.ConnectionVM`, nothing here can carry
a token: an account is an id, a display name, a status and the sentences the owner reads.

**Assisted, never autonomous.** Qualify only sends the video to the creator's TikTok inbox
(`video.upload`): TikTok shows it as a notification, and the owner taps it to finish and
publish the video in the TikTok app. It does not land in the profile's «Borradores» folder,
so no sentence says it does. Nothing here schedules (ADR 23c), and
no sentence promises otherwise (`qualify-copy-es` §6).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from .final_review_vm import FINAL_NIGHT_RUNNING_NOTE, FINAL_SCHEDULED_NOTE
from .review_links import review_href

PLATFORM = "tiktok"
UPLOAD_SCOPE = "video.upload"

# --- «Tus redes»: the TikTok card ---------------------------------------------------------

#: The TikTok cards of «Tus redes»; «Ver mi TikTok» scrolls here (m-24945912).
ACCOUNTS_ELEMENT_ID = "tiktok-cuentas"
#: The benefit, said before the owner connects anything (qualify-ux §2).
INVITE_TITLE = "Lleva tus videos también a TikTok"
INVITE_BODY = (
    "Tus videos aprobados llegan a tu TikTok con un toque. "
    "Tú los terminas y los publicas desde la aplicación."
)
CONNECT_ACTION = "Conectar TikTok"
CAN_DO = "enviar tus videos aprobados a TikTok para terminarlos y publicarlos allá"
#: Nothing is published or scheduled from Qualify: the owner decides in TikTok.
DRAFTS_ONLY_NOTE = "Qualify no publica en TikTok: tú decides cuándo sale, desde la aplicación."
UNAVAILABLE_NOTE = "Por ahora no puedes conectar TikTok desde aquí."
FALLBACK_NAME = "Tu cuenta de TikTok"
DISCONNECTED_PROBLEM = (
    "Tu TikTok está desconectado. Para seguir enviándole videos, pulsa «Volver a conectar»."
)
REVOKED_PROBLEM = (
    "Desconectaste esta cuenta. Para volver a enviarle videos, pulsa «Volver a conectar»."
)
#: Same words as `qualify_api.connections.tiktok_service.NOTICE_PERMISSION_MISSING` (a test
#: keeps them equal): the backend says it after the round trip, the card says it after.
PERMISSION_PROBLEM = (
    "Falta el permiso para enviar videos a tu TikTok. "
    "Vuelve a conectar la cuenta y acepta ese permiso."
)
#: Same words as `tiktok_service.NOTICE_DEVELOPMENT` (kept equal by a test).
DEVELOPMENT_NOTICE = (
    "TikTok todavía está revisando Qualify. Mientras tanto, solo funciona con las cuentas "
    "que te habilitamos, y lo que envíes lo verás solo tú."
)
DISCONNECT_TITLE = "¿Desconectar tu TikTok?"
DISCONNECT_BODY = (
    "Ya no podrás enviar videos a esta cuenta desde Qualify. Lo que ya "
    "está en TikTok no cambia. Puedes conectarla de nuevo cuando quieras."
)
CONNECTED_TITLE = "TikTok conectado"
SEE_ACCOUNT_ACTION = "Ver mi TikTok"
CONNECTED_BODY = (
    "Ya puedes enviar tus videos aprobados a TikTok. "
    "Los terminas y los publicas tú, desde la aplicación."
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
        "No pudimos terminar la conexión: el enlace venció o se abrió en otra aplicación "
        "(por ejemplo, la de TikTok). Toca el botón de TikTok otra vez y termina desde aquí, "
        "sin cambiar de aplicación.",
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


# --- an approved piece: «Enviar a TikTok» -------------------------------------------------

#: A piece made for TikTok (category `tiktok_video`): TikTok is where it goes.
DRAFT_TITLE_TIKTOK = "Llévalo a TikTok"
#: Any other approved video (a reel): TikTok is an extra.
DRAFT_TITLE = "Llévalo también a TikTok"
DRAFT_BODY = "Te lo enviamos a TikTok para que lo termines y lo publiques tú."
DRAFT_ACTION = "Enviar a TikTok"
DRAFT_RETRY = "Intentar de nuevo"
DRAFT_ACCOUNT_PREFIX = "Se envía a la cuenta: "
#: …while the final is not ready: it has not gone anywhere yet.
DRAFT_ACCOUNT_PREFIX_LATER = "Se enviará a la cuenta: "
DRAFT_SENDING = "Estamos enviando tu video a TikTok."
#: The backend's own words for a video that landed (`tiktok_drafts.IN_INBOX_TEXT`).
DRAFT_IN_INBOX = "Listo: abre TikTok y busca la notificación para terminar tu publicación."
DRAFT_FAILED_DEFAULT = "TikTok no pudo recibir tu video. Inténtalo de nuevo en unos minutos."
DRAFT_STILL_SENDING = (
    "TikTok todavía está recibiendo tu video. Vuelve a esta pantalla en unos minutos para "
    "ver si ya llegó."
)
DRAFT_SEND_FAILED = "No pudimos enviar tu video a TikTok. Vuelve a intentarlo en un momento."
#: The piece is approved and a video, but no TikTok account can receive it yet.
DRAFT_CONNECT_HINT = "¿Tienes TikTok? Conéctalo y envíale este video."
DRAFT_CONNECT_LINK = "Conectar TikTok"
DRAFT_RECONNECT_HINT = "Tu TikTok necesita que lo vuelvas a conectar para recibir este video."
DRAFT_RECONNECT_LINK = "Volver a conectar TikTok"

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
    STATUS_IN_INBOX: ("Enviado a TikTok", "ok"),
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
    #: Why a send was refused (`DraftRefused.code`, the backend gate's reason) — only on
    #: `refused`; it tells a preview still waiting for its final from a real problem.
    reason: str = ""


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


def refused_vm(message: str, reason: str = "") -> TikTokDraftVM:
    """Nothing was sent (the piece is not ready, the account needs a reconnect…)."""
    refused = build_draft_vm(
        draft_id="", status=STATUS_REFUSED, message=message or DRAFT_SEND_FAILED
    )
    return replace(refused, reason=reason)


# --- the video final is not ready yet (m-24945954) ---------------------------------------

#: The backend gate's reasons for a video still a vista previa
#: (`planner.post_reader.UnpublishableReason`; a test keeps them equal): the same rule
#: `send_tiktok_draft` refuses with, asked BEFORE offering the button.
REASON_DRAFT_PENDING = "media_draft_pending"
REASON_FINAL_UNCONFIRMED = "media_final_unconfirmed"
FINAL_WAIT_REASONS = frozenset({REASON_DRAFT_PENDING, REASON_FINAL_UNCONFIRMED})
#: `creative.draft_mode` states of the piece's video (kept equal by a test).
VIDEO_RENDERING = "rendering"
VIDEO_FINAL_SCHEDULED = "final_scheduled"
VIDEO_FINAL_READY = "final_ready"

FINAL_WAIT_NOTE = "Cuando tu video final esté listo podrás enviarlo a TikTok."
#: The nightly lane, in the same words of time as the piece's own video notice right above
#: (`creative_provider._with_expiry`: «mañana temprano», or «en unas horas» at night) —
#: said once, as when TikTok can get it, not as a second announcement of the final.
FINAL_WAIT_TOMORROW = (
    "Podrás enviarlo a TikTok mañana temprano, cuando tu video final esté listo y lo confirmes."
)
FINAL_WAIT_TONIGHT = (
    "Podrás enviarlo a TikTok en unas horas, cuando tu video final esté listo y lo confirmes."
)
#: The final being made right now (minutes), as the piece's notice says; confirming it
#: comes before TikTok, so the owner is not surprised by that step.
FINAL_WAIT_RENDERING = (
    "Tu video final estará listo en unos minutos. Cuando lo confirmes, podrás enviarlo a TikTok."
)
FINAL_WAIT_CONFIRM = "Tu video final ya está listo. Confírmalo y después podrás enviarlo a TikTok."
FINAL_WAIT_CONFIRM_ACTION = "Revisar video"


@dataclass(frozen=True)
class FinalWaitVM:
    """Whether the card must wait for the piece's video final before offering to send."""

    waiting: bool = False
    note: str = ""
    #: The final is there and only the owner's confirmation is missing: «Revisar video».
    review: bool = False


FINAL_OK = FinalWaitVM()


def final_wait_vm(reason: str, video_state: str = "", video_note: str = "") -> FinalWaitVM:
    """The card's wait from the backend gate's `reason` ("" = it would send). The piece's
    video (`creative_vm.VideoDraftVM` state and note, the notice shown above the card)
    only picks the words, so both say the same time."""
    if reason not in FINAL_WAIT_REASONS:
        return FINAL_OK
    if reason == REASON_FINAL_UNCONFIRMED or video_state == VIDEO_FINAL_READY:
        return FinalWaitVM(True, FINAL_WAIT_CONFIRM, review=True)
    if video_note == FINAL_NIGHT_RUNNING_NOTE:
        return FinalWaitVM(True, FINAL_WAIT_TONIGHT)
    if video_state == VIDEO_FINAL_SCHEDULED or video_note == FINAL_SCHEDULED_NOTE:
        return FinalWaitVM(True, FINAL_WAIT_TOMORROW)
    if video_state == VIDEO_RENDERING:
        return FinalWaitVM(True, FINAL_WAIT_RENDERING)
    return FinalWaitVM(True, FINAL_WAIT_NOTE)


def is_final_wait_refusal(draft: TikTokDraftVM) -> bool:
    """A send refused only because the video is still a vista previa: not a failure."""
    return draft.status == STATUS_REFUSED and draft.reason in FINAL_WAIT_REASONS


def final_review_href(post_id: str) -> str:
    """Where the owner confirms the video final — the piece's own «Revisar video»."""
    return review_href(post_id)


@dataclass(frozen=True)
class TikTokTarget:
    """Whether a piece can go to TikTok at all (one video), and which template output."""

    eligible: bool
    output_port: str = ""
    #: The piece was made for TikTok (category `tiktok_video`): it never goes to Instagram,
    #: so TikTok is its next step, not an extra.
    tiktok_only: bool = False


NOT_A_TARGET = TikTokTarget(False)


TIKTOK_CATEGORY = "tiktok_video"


def pick_target(
    outputs: Sequence[tuple[str, Sequence[str]]],
    media_types: Sequence[str],
    category: str | None = None,
) -> TikTokTarget:
    """The video TikTok receives: TikTok takes ONE video, never an image or a carousel.

    `outputs` are a template piece's ports with their media types (publisher names,
    "VIDEO"/"IMAGE"): the `reel` port first, else the first single-video port. A piece
    without ports qualifies when it is exactly one video. `category` only marks a piece
    made for TikTok (`tiktok_only`); it never makes a non-video eligible."""
    tiktok_only = category == TIKTOK_CATEGORY
    single_video = [port for port, types in outputs if tuple(types) == ("VIDEO",)]
    if outputs:
        if not single_video:
            return NOT_A_TARGET
        port = "reel" if "reel" in single_video else single_video[0]
        return TikTokTarget(True, port, tiktok_only)
    if tuple(media_types) == ("VIDEO",):
        return TikTokTarget(True, "", tiktok_only)
    return NOT_A_TARGET


def next_attempt(failed_attempts: int) -> int:
    """The `attempt` of the next send: a failed draft is final (settle-once), so trying
    again is attempt N+1; otherwise the same key, which returns the draft already sent
    instead of putting a second one in the owner's TikTok (idempotency)."""
    return max(failed_attempts, 0) + 1


#: How the card polls a draft still being received: one read every few seconds, then it
#: stops and says to come back (never an endless spinner).
POLL_SECONDS = 3.0
POLL_MAX_READS = 20
