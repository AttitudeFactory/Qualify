"""The email of a Clip whose AI part failed (m-25142979): one or more «partes con IA» of
the Clip could not be made, and the Clip waits for its owner's choice (m-25129407).

Pure assembly, no external reads: the outbox (`creative.clip_avatar_mail`) passes in the
business name, the Clip's link, the date the Clip stops waiting, which parts failed and
what the owner can do with them. The layout is the avatar email's
(`mail.clip_avatar.render_mail`). On screen a part is «Parte con IA n», counted among the
AI parts in track order (`Qualify/ai_block_vm.NAME`) — the same `n` as the part's place
(`part_index`), so the email names it the same way. The action names are the ones the
Clip's failed part offers (`clip_ai_part_actions`, `part_progress.failed_part`).
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

#: The kind of email (`clip_avatar_failure_mails.kind`, migration 0192).
AI_PART_FAILED = "ai_part_failed"

#: What the owner can ask for on a failed part, in the screen's words and order
#: (`part_progress.PartAction` values; «Quitar» as `clip_ai_part_actions` names it).
ACTION_WORDS: dict[str, str] = {
    "retry": "Intentar de nuevo",
    "change": "Cambiar",
    "make_new": "Hacerla nueva",
    "remove": "Quitar",
}

# -- one part ----------------------------------------------------------------------------
SUBJECT = "{business}: una parte con IA de tu video no salió"
HEADING = "La parte con IA {n} de tu video no salió"
LEAD = (
    "Tu video de {business} está esperando en Por aprobar. La parte con IA {n} no se pudo "
    "crear y no se descontó nada de tu plan por ella. Elige {actions}."
)
WAIT = (
    "Tienes hasta el {deadline} (hora de {business}). Si no eliges antes, el video se "
    "descarta y habría que crearlo de nuevo."
)
REMOVE = "Si quitas la parte, armamos tu video sin ella y tú lo apruebas antes de publicar."
# -- two or more parts seen failed in one pass (one email per Clip and pass) -------------
SUBJECT_MANY = "{business}: algunas partes con IA de tu video no salieron"
HEADING_MANY = "Algunas partes con IA de tu video no salieron"
LEAD_MANY = (
    "Tu video de {business} está esperando en Por aprobar. Las partes con IA {numbers} no "
    "se pudieron crear y no se descontó nada de tu plan por ellas. Con cada parte, elige "
    "{actions}."
)
REMOVE_MANY = "Si quitas una parte, armamos tu video sin ella y tú lo apruebas antes de publicar."
#: Making a part again charges one vista previa (`clip_ai_part_actions`, all or nothing);
#: taking it out charges nothing.
COST = "Volver a crear una parte usa una vista previa de tu plan. Quitarla no cuesta nada."
COST_NO_REMOVE = "Volver a crear una parte usa una vista previa de tu plan."
FOOTER = (
    "Recibes este aviso porque hay un video con partes con IA de {business} esperando en Qualify."
)
TEXTS = (
    SUBJECT,
    HEADING,
    LEAD,
    WAIT,
    REMOVE,
    SUBJECT_MANY,
    HEADING_MANY,
    LEAD_MANY,
    REMOVE_MANY,
    COST,
    COST_NO_REMOVE,
    FOOTER,
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
    """The quoted names of `actions`, in the screen's order, each once; an action the
    email has no words for (another mode) is left out. Pure."""
    wanted = set(actions)
    return [f"«{words}»" for action, words in ACTION_WORDS.items() if action in wanted]


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
) -> OutgoingMail:
    """The email of `slots` (the failed parts' places, «Parte con IA n») of one Clip;
    `actions`: what the owner can ask for on them (`ACTION_WORDS` keys)."""
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
    many = len(numbers) > 1
    if many:
        subject = SUBJECT_MANY.format(business=business)
        heading = HEADING_MANY
        lead = LEAD_MANY.format(
            business=business, numbers=spanish_list([str(n) for n in numbers]), actions=choice
        )
    else:
        subject = SUBJECT.format(business=business)
        heading = HEADING.format(n=numbers[0])
        lead = LEAD.format(business=business, n=numbers[0], actions=choice)
    wait = WAIT.format(business=business, deadline=deadline)
    paragraphs: list[str] = [lead, COST if removable else COST_NO_REMOVE, wait]
    if removable:
        paragraphs.append(REMOVE_MANY if many else REMOVE)
    return render_mail(
        to=to,
        subject=subject,
        heading=heading,
        preheader=PREHEADER.format(deadline=deadline),
        paragraphs=tuple(paragraphs),
        footer=FOOTER.format(business=business),
        url=video_url(base_url, clip_id),
        base_url=base_url,
        idempotency_key=idempotency_key,
    )


__all__ = [
    "ACTION_WORDS",
    "AI_PART_FAILED",
    "AI_PART_TEMPLATE_VERSION",
    "TEXTS",
    "action_words",
    "ai_part_failure_mail",
    "spanish_choice",
    "spanish_list",
]
