"""The email of a Clip whose AI part failed (m-25142979): one or more «partes con IA» of
the Clip could not be made, and the Clip waits for its owner's choice (m-25129407), or a
part the owner added to a made Clip could not be made (m-25142982).

Pure assembly, no external reads: the outbox (`creative.clip_avatar_mail`) passes in the
business name, the Clip's link, the date the Clip stops waiting, which parts failed and
what the owner can do with them. The layout is the avatar email's
(`mail.clip_avatar.render_mail`). On screen a part is «Parte con IA n», counted among the
AI parts in track order (`Qualify/ai_block_vm.NAME`) — the same `n` as the part's place
(`part_index`) on a Clip's first «Crear», so the email names it the same way. A part
added to a made Clip is named «la parte con IA que agregaste» (its place counts the parts
made before, which the screen no longer shows as AI blocks). The action names are the
ones the Clip's failed part offers (`clip_ai_part_actions`, `part_progress.failed_part`).
Reviewed by ux-designer on 2026-11-27 (`qualify-copy-es`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from uuid import UUID

from qualify_api.mail import OutgoingMail
from qualify_api.mail.clip_avatar import (
    PREHEADER,
    business_zone,
    render_mail,
    spanish_deadline,
    video_url,
)

#: Provenance of every staged row (`clip_avatar_failure_mails.source_version`): bump it
#: when a word or the layout changes.
AI_PART_TEMPLATE_VERSION = "clip-ai-part-failed-v1"

#: The kind of email (`clip_avatar_failure_mails.kind`, migration 0193).
AI_PART_FAILED = "ai_part_failed"

#: What the owner can ask for on a failed part, in the screen's words and order
#: (`part_progress.PartAction` values; «Quitar» as `clip_ai_part_actions` names it).
ACTION_WORDS: dict[str, str] = {
    "retry": "Intentar de nuevo",
    "change": "Cambiar",
    "make_new": "Hacerla nueva",
    "remove": "Quitar",
}
#: «Cambiar» alone does not say what changes, outside the screen (ux-designer).
CHANGE_HINT = "(su descripción o sus fotos)"

# -- one part ----------------------------------------------------------------------------
SUBJECT = "{business}: una parte con IA de tu video no salió"
HEADING = "La parte con IA {n} de tu video no salió"
LEAD = (
    "Tu video de {business} está esperando en Por aprobar. La Parte con IA {n} no se pudo "
    "crear y no se descontó su vista previa. Elige {actions}."
)
#: Making a part again charges one vista previa (`clip_ai_part_actions`, all or nothing);
#: taking it out charges nothing.
COST = (
    "Volver a crearla usa una vista previa de tu plan. Quitarla no cuesta nada: armamos tu "
    "video sin ella y tú lo apruebas antes de publicar."
)
COST_NO_REMOVE = "Volver a crearla usa una vista previa de tu plan."
WAIT = (
    "Tienes hasta el {deadline} (hora de {business}). Si no eliges antes, el video se "
    "descarta y habría que crearlo de nuevo."
)
# -- two or more parts seen failed in one pass (one email per Clip and pass) -------------
SUBJECT_MANY = "{business}: algunas partes con IA de tu video no salieron"
HEADING_MANY = "Algunas partes con IA de tu video no salieron"
#: Each part offers its own actions: the list is what at least one of them offers, so
#: the owner chooses on the screen, part by part.
LEAD_MANY = (
    "Tu video de {business} está esperando en Por aprobar. Las Partes con IA {numbers} no "
    "se pudieron crear y no se descontaron sus vistas previas. Entra a tu video y elige "
    "qué hacer con cada una: {actions}."
)
COST_MANY = (
    "Volver a crear una parte usa una vista previa de tu plan. Quitar una parte no cuesta "
    "nada: armamos tu video sin ella y tú lo apruebas antes de publicar."
)
COST_MANY_NO_REMOVE = "Volver a crear una parte usa una vista previa de tu plan."
# -- m-25142982: a part added to a made Clip. Its owner's time running out never loses
# the video: it is assembled without the part, as it was (`ai_parts_gate`, `added`).
SUBJECT_ADDED = "{business}: la parte con IA que agregaste a tu video no salió"
HEADING_ADDED = "La parte con IA que agregaste no salió"
LEAD_ADDED = (
    "Tu video de {business} está esperando en Por aprobar. La parte con IA que agregaste "
    "no se pudo crear y no se descontó su vista previa. Elige {actions}."
)
COST_ADDED = (
    "Volver a crearla usa una vista previa de tu plan. Quitarla no cuesta nada: tu video "
    "queda como estaba."
)
WAIT_ADDED = (
    "Tienes hasta el {deadline} (hora de {business}). Si no eliges antes, tu video queda "
    "como estaba, sin esa parte."
)
PREHEADER_ADDED = "Elige antes del {deadline}. Si no, tu video queda como estaba."
FOOTER = (
    "Recibes este aviso porque un video de {business} con partes con IA está esperando en Qualify."
)
TEXTS = (
    SUBJECT,
    HEADING,
    LEAD,
    COST,
    COST_NO_REMOVE,
    WAIT,
    SUBJECT_MANY,
    HEADING_MANY,
    LEAD_MANY,
    COST_MANY,
    COST_MANY_NO_REMOVE,
    SUBJECT_ADDED,
    HEADING_ADDED,
    LEAD_ADDED,
    COST_ADDED,
    WAIT_ADDED,
    PREHEADER_ADDED,
    FOOTER,
    CHANGE_HINT,
    *ACTION_WORDS.values(),
)


def spanish_list(items: Sequence[str]) -> str:
    """«a», «a y b», «a, b y c». Pure."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} y {items[-1]}"


def spanish_choice(items: Sequence[str]) -> str:
    """«a», «a o b», «a, b o c». Pure."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} o {items[-1]}"


def action_words(actions: Iterable[str]) -> list[str]:
    """The quoted names of `actions`, in the screen's order, each once («Cambiar» with
    what it changes); an action the email has no words for (another mode) is left out.
    Pure."""
    wanted = set(actions)
    return [
        f"«{words}» {CHANGE_HINT}" if action == "change" else f"«{words}»"
        for action, words in ACTION_WORDS.items()
        if action in wanted
    ]


def ai_part_failure_mail(
    *,
    to: str,
    business: str,
    clip_id: UUID,
    wait_until: datetime,
    timezone: str,
    base_url: str,
    idempotency_key: str,
    slots: Sequence[int],
    actions: Iterable[str],
    added: bool = False,
) -> OutgoingMail:
    """The email of `slots` (the failed parts' places, «Parte con IA n») of one Clip;
    `actions`: what the owner can ask for on them (`ACTION_WORDS` keys); `added`: the part
    was added to a made Clip (m-25142982), whose video stays as it was."""
    if not slots:
        raise ValueError("an AI part failure email names at least one part")
    numbers = sorted(set(slots))
    wanted = set(actions)
    choices = action_words(wanted)
    if not choices:
        raise ValueError("an AI part failure email offers at least one action")
    removable = "remove" in wanted
    deadline = spanish_deadline(wait_until, business_zone(timezone))
    choice = spanish_choice(choices)
    if added:
        subject = SUBJECT_ADDED.format(business=business)
        heading = HEADING_ADDED
        lead = LEAD_ADDED.format(business=business, actions=choice)
        cost = COST_ADDED if removable else COST_NO_REMOVE
        wait = WAIT_ADDED.format(business=business, deadline=deadline)
    elif len(numbers) > 1:
        subject = SUBJECT_MANY.format(business=business)
        heading = HEADING_MANY
        lead = LEAD_MANY.format(
            business=business, numbers=spanish_list([str(n) for n in numbers]), actions=choice
        )
        cost = COST_MANY if removable else COST_MANY_NO_REMOVE
        wait = WAIT.format(business=business, deadline=deadline)
    else:
        subject = SUBJECT.format(business=business)
        heading = HEADING.format(n=numbers[0])
        lead = LEAD.format(business=business, n=numbers[0], actions=choice)
        cost = COST if removable else COST_NO_REMOVE
        wait = WAIT.format(business=business, deadline=deadline)
    return render_mail(
        to=to,
        subject=subject,
        heading=heading,
        preheader=(PREHEADER_ADDED if added else PREHEADER).format(deadline=deadline),
        paragraphs=(lead, cost, wait),
        footer=FOOTER.format(business=business),
        url=video_url(base_url, clip_id),
        base_url=base_url,
        idempotency_key=idempotency_key,
    )


__all__ = [
    "ACTION_WORDS",
    "AI_PART_FAILED",
    "AI_PART_TEMPLATE_VERSION",
    "CHANGE_HINT",
    "TEXTS",
    "action_words",
    "ai_part_failure_mail",
    "spanish_choice",
    "spanish_list",
]
