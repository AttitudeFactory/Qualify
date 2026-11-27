"""The email of a Clip whose avatars need the owner (m-25120319, epic m-25026566): one
or more avatars could not be made («Uno de tus avatares no se pudo crear»), or one was
made but the Clip passes 60 s with it («Tu video quedó muy largo»). The words live in
`qualify_api.mail.clip_avatar`.

**When.** The worker's pass that sees an avatar block of a Clip failed — or refuses a
made one as too long — stamps its `failed_at` on the Clip's plan (`clip_avatar.plan_gate`
→ `PlanRefused("failure_seen" | "clip_too_long")`), in a new brief written under the
run's fence (`ContentService._replace_clip_brief`). In THAT same transaction `stage`
writes ONE row in `clip_avatar_failure_mails` (migration 0186) for everything the pass
stamped: the stamp and the email commit together or not at all.

**One email per Clip and pass** (Deivid, 2026-11-26). Every block a pass stamps carries
that pass's `failed_at`, so the identity `(clip_id, kind, failed_at)` — `UNIQUE`, staged
with `ON CONFLICT DO NOTHING` — groups two avatars failing together into one row and one
email; its Resend `Idempotency-Key` is derived from it. Re-reading the state, a second
pass or a restarted worker never stages a second row (the stamp is already on the plan;
and if it were written again, the same identity conflicts). The sender freezes the mail
before its first attempt and resends it verbatim with the same key; after
`RETRY_WINDOW` of uncertain attempts it closes the row instead of risking a double
(Resend keeps keys 24 h).

**A retry that fails again** is a new failure: «Intentar de nuevo» clears the slot's
`failed_at`; when the new attempt fails (or comes out too long again), a later pass
stamps a new `failed_at` — a new identity, one more email, once. Before EVERY attempt
(the first and each retry of a frozen mail) the sender re-reads the Clip and the
recipient: a row whose avatars were all retried or removed, or whose Clip moved on
(made, failed at 72 h), is closed `resolved`, never sent; one whose recipient left or
changed address is closed `no_recipient`.

**Switches.** Nothing is staged for a kind whose switch (`QUALIFY_CLIP_AVATAR_PRESENTER`
/ `QUALIFY_CLIP_AVATAR_ANIMATED`) is off, nor for a `switched_off` «failure»; the sender
checks the switches again before every attempt (`closed_reason='switched_off'`), and the
worker's chore reads nothing while both are off. With both off no block can exist.

**Character scenes** (m-25128784 PR 2, ADR 50 §12.1): a Clip's scene that could not be
made sends this same email, in the scene's words (`mail.clip_avatar`, its own template
version) — `block_kind` `character_scene`, `block_ids` the scenes' drafts, the stamp on
the Clip's own scene item (`character_scene.scenes_gate`). Its switch is
`QUALIFY_CLIP_CHARACTER_SCENE`: nothing staged nor sent while it is off, and the chore
reads nothing while it and both avatar switches are off.

**AI parts** (m-25142979, ADR 50 §13): a Clip's «parte con IA» that failed keeps the
Clip waiting 72 h for its owner (m-25129407) and sends ONE email per Clip and pass, in
its own words (`mail.clip_ai_part`) — `kind` `ai_part_failed`, `block_ids` the parts,
`block_revisions` each part's revision as it failed (migration 0192). The wait writes
nothing on the Clip, so the pass that sees a failed part stages its row in its own
fenced write (`ContentService._stage_ai_part_mail`), and a pair (part, revision) already
in a row is never staged again (`mailable_ai_part_failures`): only a part made again (a
new revision) that fails again sends one more. A Clip that failed at once
(`ai_part_failed`) or whose 72 h ran out (`ai_part_expired`) never waits, so it never
stages; a row staged before is closed `resolved` (the Clip is no longer `drafting`). Its
switch is `QUALIFY_CLIP_AI_PARTS`: nothing staged nor sent while it is off.

**Who.** The Clip's author (`content_briefs.created_by`), while still a member of the
business with a real seat and a confirmed address (`auth.confirmed_email`, fail closed).

**Privacy.** Logs carry ids, codes and an error's type only — never an address, a name, a
script, nor an exception's text or traceback (a database error carries its parameters).
`test_clip_avatar_mail.py` checks every record of a full run and every log call.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_creative.schemas import CharacterSceneItem, ClipAvatarSlot, SourceSegment

from qualify_api.creative.character_scene import (
    SWITCHED_OFF,
    PostgresCharacterSceneStore,
    SceneRow,
    placed_scenes,
    scene_enabled,
    scene_owner_deadline,
)
from qualify_api.creative.clip_ai_parts import (
    CLIP_AI_PART_OWNER_WAIT,
    AiPartRow,
    part_state,
)
from qualify_api.creative.clip_ai_parts import owner_deadline as ai_part_deadline
from qualify_api.creative.clip_avatar import (
    BlockRow,
    PlannedBlock,
    any_block_enabled,
    block_enabled,
    owner_deadline,
    plan_states,
)
from qualify_api.mail import Mailer, MailNotConfigured, MailRejected, OutgoingMail
from qualify_api.mail.clip_ai_part import (
    AI_PART_FAILED,
    AI_PART_TEMPLATE_VERSION,
    ai_part_failure_mail,
)
from qualify_api.mail.clip_avatar import (
    BLOCK_FAILED,
    CLIP_TOO_LONG,
    SCENE_TEMPLATE_VERSION,
    TEMPLATE_VERSION,
    failure_mail,
)

logger = logging.getLogger(__name__)

#: m-25128784 PR 2: the `block_kind` of a character scene's failure. The same table, kind
#: (`block_failed`) and identity as an avatar's; `block_ids` are the scenes' drafts.
SCENE_MAIL_KIND = "character_scene"
#: m-25142979: the `block_kind` of a Clip's AI part that failed — its own `kind`
#: (`ai_part_failed`) and words; `block_ids` are the parts, with their revisions.
AI_PART_MAIL_KIND = "ai_part"

#: Resend keeps an idempotency key 24 h: stop retrying an uncertain send before then.
RETRY_WINDOW = timedelta(hours=23)
#: How long a claimed row is held by one sender (the send itself times out at 15 s).
LEASE = timedelta(minutes=2)
#: Why a row was closed without being sent (migration 0186's CHECK).
CLOSE_REASONS = frozenset({"resolved", "switched_off", "no_recipient", "rejected", "uncertain"})

Verifier = Callable[[UUID, str], str | None]


@dataclass(frozen=True)
class AvatarFailure:
    """One avatar stamped on this pass (failed, or refused as too long)."""

    block_id: UUID
    slot: int
    block_kind: str
    code: str
    failed_at: datetime
    #: m-25142979: an AI part's revision as it failed (None for an avatar or a scene).
    revision: int | None = None

    @property
    def mail_kind(self) -> str:
        if self.block_kind == AI_PART_MAIL_KIND:
            return AI_PART_FAILED
        return CLIP_TOO_LONG if self.code == CLIP_TOO_LONG else BLOCK_FAILED


def mailable_failures(
    seen: Sequence[PlannedBlock], env: Mapping[str, str] | None = None
) -> tuple[AvatarFailure, ...]:
    """The avatars stamped on this pass that get an email: a real block that failed or
    was refused as too long, whose kind is switched on — never `switched_off` (nothing
    failed: the server stopped it) nor an entry without a block (no «Intentar de nuevo»
    to offer). Pure."""
    found: list[AvatarFailure] = []
    for planned in seen:
        row = planned.row
        if row is None or planned.entry.failed_at is None or planned.code == "switched_off":
            continue
        if not block_enabled(row.kind, env):
            continue
        found.append(
            AvatarFailure(
                block_id=row.id,
                slot=planned.entry.slot,
                block_kind=row.kind,
                code=planned.code or "failed",
                failed_at=planned.entry.failed_at,
            )
        )
    return tuple(found)


def ai_parts_mail_on(env: Mapping[str, str] | None = None) -> bool:
    """`QUALIFY_CLIP_AI_PARTS` read as the server reads it (`ai_parts.clip_ai_parts_on`);
    `env` for tests. Off: no AI part email is staged nor sent."""
    from qualify_api.creative.video_pipeline.ai_parts import (  # noqa: PLC0415
        CLIP_AI_PARTS_SWITCH,
        clip_ai_parts_on,
    )

    if env is None:
        return clip_ai_parts_on()
    return env.get(CLIP_AI_PARTS_SWITCH, "off").strip().lower() == "on"


def mailable_ai_part_failures(
    failed: Sequence[AiPartRow],
    mailed: Collection[tuple[UUID, int]],
    now: datetime,
    env: Mapping[str, str] | None = None,
) -> tuple[AvatarFailure, ...]:
    """m-25142979: the failed AI parts of a waiting Clip that get an email on this pass —
    not removed, failed, and their (part, revision) in no row yet (`mailed`). All are
    stamped with this pass's moment (`now`), so they share ONE row and ONE email.
    Nothing while `QUALIFY_CLIP_AI_PARTS` is off. Pure but for the switch."""
    if not ai_parts_mail_on(env):
        return ()
    return tuple(
        AvatarFailure(
            block_id=row.id,
            slot=row.slot,
            block_kind=AI_PART_MAIL_KIND,
            code=row.failure_reason or "failed",
            failed_at=now,
            revision=row.revision,
        )
        for row in sorted(failed, key=lambda r: r.slot)
        if part_state(row) == "failed" and (row.id, row.revision) not in mailed
    )


@dataclass(frozen=True)
class MailGroup:
    """What ONE row is staged for: a Clip's avatars stamped together, of one kind."""

    kind: str
    failed_at: datetime
    slots: tuple[int, ...]
    block_ids: tuple[UUID, ...]
    codes: tuple[str, ...]
    #: m-25128784: the group is of character scenes (a Clip has scenes or avatar blocks,
    #: never both): staged with the scene's template version.
    scene: bool = False
    #: m-25142979: each AI part's revision as it failed (`ai_part_failed` only).
    revisions: tuple[int, ...] | None = None

    @property
    def template_version(self) -> str:
        if self.kind == AI_PART_FAILED:
            return AI_PART_TEMPLATE_VERSION
        return SCENE_TEMPLATE_VERSION if self.scene else TEMPLATE_VERSION


def mail_groups(failures: Sequence[AvatarFailure]) -> tuple[MailGroup, ...]:
    """One group per (kind, failed_at) — one per pass in practice. Pure."""
    groups: dict[tuple[str, datetime], list[AvatarFailure]] = {}
    for failure in sorted(failures, key=lambda f: f.slot):
        groups.setdefault((failure.mail_kind, failure.failed_at), []).append(failure)
    return tuple(
        MailGroup(
            kind=kind,
            failed_at=failed_at,
            slots=tuple(f.slot for f in items),
            block_ids=tuple(f.block_id for f in items),
            codes=tuple(f.code for f in items),
            scene=any(f.block_kind == SCENE_MAIL_KIND for f in items),
            revisions=tuple(int(f.revision or 0) for f in items)
            if kind == AI_PART_FAILED
            else None,
        )
        for (kind, failed_at), items in groups.items()
    )


def failure_key(tenant_id: UUID, clip_id: UUID, kind: str, failed_at: datetime) -> str:
    """Resend's `Idempotency-Key` for one email: derived from its identity, no PII."""
    stamp = failed_at.astimezone(UTC).isoformat()
    digest = hashlib.sha256(f"{tenant_id}|{clip_id}|{kind}|{stamp}".encode()).hexdigest()
    return f"clip-avatar-failed/{digest}"


@dataclass(frozen=True)
class PendingMail:
    """A staged row as the sender claimed it (its lease taken)."""

    id: UUID
    tenant_id: UUID
    clip_id: UUID
    kind: str
    failed_at: datetime
    slots: tuple[int, ...]
    block_ids: tuple[UUID, ...]
    user_id: UUID
    idempotency_key: str
    lease: UUID
    payload: Mapping[str, Any] | None = None
    first_attempt_at: datetime | None = None
    #: m-25142979: each AI part's revision as it failed (`ai_part_failed` only).
    revisions: tuple[int, ...] | None = None


@dataclass(frozen=True)
class ClipView:
    """The Clip as the sender re-reads it before every attempt."""

    status: str
    business: str
    timezone: str
    plan: tuple[ClipAvatarSlot, ...]
    blocks: tuple[BlockRow, ...]
    #: m-25128784: the Clip's «Personajes» track (with each scene's `failed_at` stamp) and
    #: its scene children — empty for a Clip with avatar blocks.
    scene_items: tuple[CharacterSceneItem, ...] = ()
    scene_rows: tuple[SceneRow, ...] = ()
    #: m-25142979: the Clip's AI parts and its timeline's blocks (to tell whether
    #: «Quitar» is left for a part) — empty for a Clip without AI parts.
    ai_parts: tuple[AiPartRow, ...] = ()
    segments: tuple[SourceSegment, ...] = ()


@dataclass(frozen=True)
class Recipient:
    email: str
    auth_user_id: UUID


class AvatarFailureOutbox(Protocol):
    """Where the emails wait. `stage` runs INSIDE the Clip's fenced write (`session` is
    that transaction; None for the in-memory double); every other call is its own
    transaction, fenced by the claim's `lease`."""

    def stage(
        self,
        session: Any,
        *,
        tenant_id: UUID,
        clip_id: UUID,
        user_id: UUID,
        failures: Sequence[AvatarFailure],
    ) -> int: ...

    def mailed_ai_parts(
        self, session: Any, *, tenant_id: UUID, clip_id: UUID
    ) -> frozenset[tuple[UUID, int]]:
        """m-25142979: every (part, revision) of the Clip an `ai_part_failed` row holds,
        read inside the Clip's fenced write (`session`; None for the in-memory double)."""
        ...

    def pending_tenants(self) -> list[UUID]: ...

    def claim(self, tenant_id: UUID, *, now: datetime, include_new: bool) -> PendingMail | None: ...

    def clip_view(self, tenant_id: UUID, clip_id: UUID) -> ClipView | None: ...

    def recipient(self, tenant_id: UUID, user_id: UUID) -> Recipient | None: ...

    def freeze(self, mail: PendingMail, payload: Mapping[str, Any], *, now: datetime) -> bool: ...

    def close(self, mail: PendingMail, reason: str, *, now: datetime) -> None: ...

    def mark_sent(self, mail: PendingMail, provider_id: str | None, *, now: datetime) -> bool: ...


# -- the sender ------------------------------------------------------------------------------


def _due(
    mail: PendingMail, clip: ClipView | None, env: Mapping[str, str] | None
) -> tuple[str | None, datetime | None, int]:
    """Whether a row is still worth sending, before every attempt: (close reason, None,
    0), or (None, when the Clip stops waiting, how many of its avatars still wait). An
    avatar still waits when its plan entry keeps this row's `failed_at`, it is not
    removed, it is still failed (or still refused as too long, for that kind) and its
    kind is switched on. Pure."""
    if clip is None or clip.status != "drafting":
        return "resolved", None, 0
    if clip.scene_items:
        return _scene_due(mail, clip, env)
    states = {s.entry.slot: s for s in plan_states(clip.plan, clip.blocks, env)}
    waiting = 0
    switched = False
    for slot, block_id in zip(mail.slots, mail.block_ids, strict=True):
        planned = states.get(slot)
        if (
            planned is None
            or planned.entry.failed_at != mail.failed_at
            or planned.state != "failed"
            or planned.row is None
            or planned.row.id != block_id
            or (planned.code == CLIP_TOO_LONG) != (mail.kind == CLIP_TOO_LONG)
        ):
            continue
        if planned.code == "switched_off" or not block_enabled(planned.row.kind, env):
            switched = True
            continue
        waiting += 1
    if not waiting:
        return ("switched_off" if switched else "resolved"), None, 0
    return None, owner_deadline(tuple(states.values())), waiting


def _scene_due(
    mail: PendingMail, clip: ClipView, env: Mapping[str, str] | None
) -> tuple[str | None, datetime | None, int]:
    """`_due` for a Clip's character scenes (m-25128784): a scene still waits when its
    item keeps this row's `failed_at`, its child is the same draft and still failed (not
    a `switched_off` «failure»), and the scene switch is on. Pure."""
    placed = {p.slot: p for p in placed_scenes(clip.scene_items, clip.scene_rows)}
    if not scene_enabled(env):
        return "switched_off", None, 0
    waiting = 0
    for slot, scene_id in zip(mail.slots, mail.block_ids, strict=True):
        scene = placed.get(slot)
        if (
            scene is None
            or scene.row is None
            or scene.row.id != scene_id
            or not scene.row.failed
            or scene.item.failed_at != mail.failed_at
            or scene.row.failure_reason == SWITCHED_OFF
        ):
            continue
        waiting += 1
    if not waiting or mail.kind != BLOCK_FAILED:
        return "resolved", None, 0
    return None, scene_owner_deadline(tuple(placed.values())), waiting


@dataclass(frozen=True)
class AiPartsDue:
    """m-25142979: what an `ai_part_failed` row still says, before every attempt: the
    places of its parts that still wait (failed at the same revision, not removed), what
    the owner can ask for on them, and when the Clip stops waiting."""

    slots: tuple[int, ...]
    actions: frozenset[str]
    wait_until: datetime


def _removable(segments: Sequence[SourceSegment], removed: frozenset[int]) -> bool:
    """Whether the Clip keeps a block once the parts at `removed` are taken out
    (`clip_ai_part_actions.remove_part` refuses the last one, `last_block`); True when the
    timeline is unknown. Pure."""
    from qualify_api.creative.video_pipeline.ai_parts import ai_part_slots  # noqa: PLC0415

    if not segments:
        return True
    slots = ai_part_slots(segments)
    return any(s.ai_part_at is None or slots.get(s.ai_part_at) not in removed for s in segments)


def _ai_part_due(
    mail: PendingMail, clip: ClipView | None, env: Mapping[str, str] | None
) -> tuple[str | None, AiPartsDue | None]:
    """`_due` for a Clip's AI parts (m-25142979): (close reason, None), or (None, what
    is still due). A part still waits when the Clip still waits (`drafting`), the part
    is the same row at the same revision, still failed and not removed, and the switch is
    on. A Clip that failed at once (`ai_part_failed`) or ran out of time
    (`ai_part_expired`) is no longer `drafting`: `resolved`, never sent. Pure but for the
    switch."""
    from qualify_api.creative.part_progress import PartAction, failed_part  # noqa: PLC0415

    if clip is None or clip.status != "drafting" or mail.revisions is None:
        return "resolved", None
    if not ai_parts_mail_on(env):
        return "switched_off", None
    rows = {row.id: row for row in clip.ai_parts}
    waiting: list[AiPartRow] = []
    for slot, part_id, revision in zip(mail.slots, mail.block_ids, mail.revisions, strict=True):
        row = rows.get(part_id)
        if (
            row is None
            or row.slot != slot
            or row.revision != revision
            or part_state(row) != "failed"
        ):
            continue
        waiting.append(row)
    if not waiting:
        return "resolved", None
    removed = frozenset(row.slot for row in clip.ai_parts if row.removed)
    actions: set[str] = set()
    for row in waiting:
        _, allowed = failed_part(row.mode, row.failure_reason)
        for action in allowed:
            if action is PartAction.REMOVE and not _removable(clip.segments, removed | {row.slot}):
                continue
            actions.add(str(action))
    failed_now = [row for row in clip.ai_parts if part_state(row) == "failed"]
    deadline = ai_part_deadline(failed_now) or mail.failed_at + CLIP_AI_PART_OWNER_WAIT
    return None, AiPartsDue(
        slots=tuple(row.slot for row in waiting), actions=frozenset(actions), wait_until=deadline
    )


def send_pending(
    outbox: AvatarFailureOutbox,
    tenant_id: UUID,
    *,
    mailer: Mailer,
    base_url: str | None,
    verify: Verifier,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Send this business's staged failure emails; how many were sent. The time is read
    again before each claim (`clock`, or the fixed `now`). Without a `base_url` (mail
    links not configured) only already-frozen emails go out. Every attempt — the first
    and each retry of a frozen mail — checks first that the avatar still waits for the
    owner (`_due`) and that the recipient is still a confirmed member; otherwise the row
    is closed unsent."""
    if clock is None:
        if now is None:
            raise ValueError("send_pending needs `now` or `clock`")
        fixed = now

        def clock() -> datetime:
            return fixed

    sent = 0
    while True:
        moment = clock()
        mail = outbox.claim(tenant_id, now=moment, include_new=base_url is not None)
        if mail is None:
            return sent
        frozen = mail.first_attempt_at is not None
        if frozen and moment - mail.first_attempt_at >= RETRY_WINDOW:  # type: ignore[operator]
            _close(outbox, mail, "uncertain", moment, error=True)
            continue
        clip = outbox.clip_view(tenant_id, mail.clip_id)
        ai_due: AiPartsDue | None = None
        if mail.kind == AI_PART_FAILED:
            reason, ai_due = _ai_part_due(mail, clip, env)
            wait_until, waiting = (ai_due.wait_until, len(ai_due.slots)) if ai_due else (None, 0)
        else:
            reason, wait_until, waiting = _due(mail, clip, env)
        if reason is not None:
            _close(outbox, mail, reason, moment)
            continue
        confirmed = _confirmed(outbox, mail, verify)
        if confirmed is _DEFER:
            continue  # the lease lapses and a later pass tries again
        if frozen:
            assert mail.payload is not None
            outgoing = OutgoingMail(**mail.payload["mail"])
            if not confirmed or outgoing.to.casefold() != str(confirmed).casefold():
                _close(outbox, mail, "no_recipient", moment)
                continue
        else:
            if not confirmed:
                _close(outbox, mail, "no_recipient", moment)
                continue
            assert base_url is not None and clip is not None and wait_until is not None
            if ai_due is not None:
                outgoing = ai_part_failure_mail(
                    to=str(confirmed),
                    business=clip.business,
                    clip_id=mail.clip_id,
                    wait_until=wait_until,
                    timezone=clip.timezone,
                    base_url=base_url,
                    idempotency_key=mail.idempotency_key,
                    slots=ai_due.slots,
                    actions=ai_due.actions,
                )
            else:
                outgoing = failure_mail(
                    to=str(confirmed),
                    business=clip.business,
                    clip_id=mail.clip_id,
                    wait_until=wait_until,
                    timezone=clip.timezone,
                    base_url=base_url,
                    idempotency_key=mail.idempotency_key,
                    kind=mail.kind,
                    count=waiting,
                    scene=bool(clip.scene_items),
                )
            if not outbox.freeze(mail, {"mail": asdict(outgoing)}, now=moment):
                continue
        try:
            provider_id = mailer.send(outgoing)
        except MailRejected:
            _close(outbox, mail, "rejected", moment, error=True)
            continue
        except Exception as exc:
            # keep the frozen mail and its key: the next pass resends it verbatim
            logger.warning(
                "clip_avatar.failure_mail send deferred tenant=%s mail=%s error_type=%s",
                tenant_id,
                mail.id,
                type(exc).__name__,
            )
            return sent
        if outbox.mark_sent(mail, provider_id, now=clock()):
            sent += 1
            logger.info(
                "clip_avatar.failure_mail sent tenant=%s mail=%s clip=%s",
                mail.tenant_id,
                mail.id,
                mail.clip_id,
            )


#: `_confirmed` could not tell (the identity provider failed): try again later.
_DEFER = object()


def _confirmed(outbox: AvatarFailureOutbox, mail: PendingMail, verify: Verifier) -> object:
    """The recipient's confirmed address, None when there is none, `_DEFER` on a
    transient failure of the check (logged with ids and the error type only)."""
    recipient = outbox.recipient(mail.tenant_id, mail.user_id)
    if recipient is None:
        return None
    try:
        return verify(recipient.auth_user_id, recipient.email)
    except Exception as exc:
        logger.warning(
            "clip_avatar.failure_mail recipient unverified tenant=%s mail=%s error_type=%s",
            mail.tenant_id,
            mail.id,
            type(exc).__name__,
        )
        return _DEFER


def _close(
    outbox: AvatarFailureOutbox,
    mail: PendingMail,
    reason: str,
    now: datetime,
    *,
    error: bool = False,
) -> None:
    outbox.close(mail, reason, now=now)
    (logger.error if error else logger.info)(
        "clip_avatar.failure_mail closed tenant=%s mail=%s reason=%s",
        mail.tenant_id,
        mail.id,
        reason,
    )


def failure_mail_chore(
    tenant_ids: Sequence[UUID] | None,
    *,
    outbox: AvatarFailureOutbox | None = None,
    mailer: Callable[[], Mailer] | None = None,
    verify: Verifier | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Callable[[], int]:
    """The creative worker's pass over every business with a staged email (or only the
    ones of `--tenant`). Never raises: a business that fails is logged and skipped."""

    def run() -> int:
        from qualify_api.mail import default_mailer  # noqa: PLC0415
        from qualify_api.mail.config import public_app_url  # noqa: PLC0415

        if not any_block_enabled() and not scene_enabled() and not ai_parts_mail_on():
            # every avatar, scene and AI part switch off (every environment today): no
            # email, not even a read
            return 0
        box = outbox or PostgresAvatarFailureOutbox()
        tick = clock or (lambda: datetime.now(UTC))
        # Never log the traceback nor the exception text here: a database error carries
        # its SQL parameters (the frozen mail: address, business, body). Ids and the type.
        try:
            ids = list(tenant_ids) if tenant_ids is not None else box.pending_tenants()
        except Exception as exc:
            logger.error(
                "clip_avatar.failure_mail discovery failed error_type=%s", type(exc).__name__
            )
            return 0
        if not ids:
            return 0
        base_url: str | None
        try:
            base_url = public_app_url()
        except MailNotConfigured as exc:
            logger.warning(
                "clip_avatar.failure_mail new mails not built error_type=%s", type(exc).__name__
            )
            base_url = None
        if verify is None:
            from qualify_api.auth.confirmed_email import confirmed_email  # noqa: PLC0415

            check: Verifier = confirmed_email
        else:
            check = verify
        count = 0
        for tenant_id in ids:
            try:
                count += send_pending(
                    box,
                    tenant_id,
                    clock=tick,
                    mailer=(mailer or default_mailer)(),
                    base_url=base_url,
                    verify=check,
                )
            except Exception as exc:
                logger.error(
                    "clip_avatar.failure_mail pass failed tenant=%s error_type=%s",
                    tenant_id,
                    type(exc).__name__,
                )
        return count

    return run


# -- Postgres ----------------------------------------------------------------------------------


_COLUMNS = (
    "id, tenant_id, clip_id, kind, failed_at, slots, block_ids, user_id, idempotency_key, "
    "payload, first_attempt_at, block_revisions"
)


class PostgresAvatarFailureOutbox:
    """`clip_avatar_failure_mails` (migration 0186): every read and write through
    `tenant_session` (RLS); tenant discovery (ids only) through `admin_session`."""

    def stage(
        self,
        session: Any,
        *,
        tenant_id: UUID,
        clip_id: UUID,
        user_id: UUID,
        failures: Sequence[AvatarFailure],
    ) -> int:
        from sqlalchemy import text  # noqa: PLC0415

        if session is None:
            raise RuntimeError("a failure email is staged inside the Clip's own write")
        staged = 0
        for group in mail_groups(failures):
            staged += session.execute(
                text("""
                INSERT INTO clip_avatar_failure_mails
                    (tenant_id, clip_id, kind, failed_at, slots, block_ids, failure_codes,
                     user_id, idempotency_key, source_version, block_revisions)
                VALUES (:tenant, :clip, :kind, :failed_at, CAST(:slots AS smallint[]),
                        CAST(:blocks AS uuid[]), CAST(:codes AS text[]), :user, :key,
                        :version, CAST(:revisions AS integer[]))
                ON CONFLICT DO NOTHING
            """),
                {
                    "tenant": tenant_id,
                    "clip": clip_id,
                    "kind": group.kind,
                    "failed_at": group.failed_at,
                    "slots": list(group.slots),
                    "blocks": [str(b) for b in group.block_ids],
                    "codes": list(group.codes),
                    "user": user_id,
                    "key": failure_key(tenant_id, clip_id, group.kind, group.failed_at),
                    "version": group.template_version,
                    "revisions": list(group.revisions) if group.revisions is not None else None,
                },
            ).rowcount
        return staged

    def mailed_ai_parts(
        self, session: Any, *, tenant_id: UUID, clip_id: UUID
    ) -> frozenset[tuple[UUID, int]]:
        from sqlalchemy import text  # noqa: PLC0415

        if session is None:
            raise RuntimeError("the mailed AI parts are read inside the Clip's own write")
        rows = session.execute(
            text("""
            SELECT u.part_id, u.revision
            FROM clip_avatar_failure_mails m,
                 unnest(m.block_ids, m.block_revisions) AS u(part_id, revision)
            WHERE m.clip_id = :clip AND m.kind = 'ai_part_failed'
        """),
            {"clip": clip_id},
        ).all()
        return frozenset((UUID(str(row.part_id)), int(row.revision)) for row in rows)

    def pending_tenants(self) -> list[UUID]:
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with admin_session() as session:
            return list(
                session.scalars(
                    text("""
                    SELECT DISTINCT tenant_id FROM clip_avatar_failure_mails
                    WHERE sent_at IS NULL AND closed_at IS NULL
                """)
                )
            )

    def claim(self, tenant_id: UUID, *, now: datetime, include_new: bool) -> PendingMail | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        lease = uuid4()
        with tenant_session(tenant_id) as session:
            row = (
                session.execute(
                    text(f"""
                SELECT {_COLUMNS} FROM clip_avatar_failure_mails
                WHERE sent_at IS NULL AND closed_at IS NULL
                  AND (lease_until IS NULL OR lease_until <= :now)
                  AND (:include_new OR first_attempt_at IS NOT NULL)
                ORDER BY created_at, id
                FOR UPDATE SKIP LOCKED LIMIT 1
            """),
                    {"now": now, "include_new": include_new},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            session.execute(
                text("""
                UPDATE clip_avatar_failure_mails SET lease_token = :lease, lease_until = :until
                WHERE id = :id
            """),
                {"lease": lease, "until": now + LEASE, "id": row["id"]},
            )
        return PendingMail(
            id=row["id"],
            tenant_id=row["tenant_id"],
            clip_id=row["clip_id"],
            kind=row["kind"],
            failed_at=row["failed_at"],
            slots=tuple(int(s) for s in row["slots"]),
            block_ids=tuple(UUID(str(b)) for b in row["block_ids"]),
            user_id=row["user_id"],
            idempotency_key=row["idempotency_key"],
            lease=lease,
            payload=row["payload"],
            first_attempt_at=row["first_attempt_at"],
            revisions=tuple(int(r) for r in row["block_revisions"])
            if row["block_revisions"] is not None
            else None,
        )

    def clip_view(self, tenant_id: UUID, clip_id: UUID) -> ClipView | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        from qualify_api.creative.clip_ai_parts import PostgresAiPartsStore  # noqa: PLC0415
        from qualify_api.creative.clip_avatar import PostgresClipAvatarStore  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text("""
                SELECT d.status, b.media->'clip_avatar_plan' AS plan,
                       b.media->'character_scenes' AS scenes,
                       b.media->'segments' AS segments,
                       CASE WHEN jsonb_typeof(b.media->'ai_parts') = 'array'
                            THEN jsonb_array_length(b.media->'ai_parts') > 0
                            ELSE false END AS has_ai_parts,
                       COALESCE(NULLIF(br.name, ''), t.name) AS business,
                       COALESCE(NULLIF(t.timezone, ''), 'UTC') AS timezone
                FROM content_drafts d
                JOIN content_briefs b ON b.id = d.brief_id
                JOIN tenants t ON t.id = d.tenant_id
                LEFT JOIN brands br ON br.id = d.brand_id
                WHERE d.id = :clip
            """),
                {"clip": clip_id},
            ).first()
        if row is None:
            return None
        plan = tuple(ClipAvatarSlot.model_validate(entry) for entry in (row.plan or ()))
        blocks = PostgresClipAvatarStore().blocks_of(tenant_id=tenant_id, clip_id=clip_id)
        scenes = tuple(CharacterSceneItem.model_validate(item) for item in (row.scenes or ()))
        scene_rows: tuple[SceneRow, ...] = ()
        if scenes:
            scene_rows = PostgresCharacterSceneStore().scene_rows(
                tenant_id=tenant_id, clip_id=clip_id
            )
        ai_parts: tuple[AiPartRow, ...] = ()
        segments: tuple[SourceSegment, ...] = ()
        if row.has_ai_parts:
            # m-25142979: an AI part's row is read only for a Clip with AI parts
            ai_parts = PostgresAiPartsStore().parts_of(tenant_id=tenant_id, clip_id=clip_id)
            segments = tuple(SourceSegment.model_validate(s) for s in (row.segments or ()))
        return ClipView(
            status=str(row.status),
            business=str(row.business),
            timezone=str(row.timezone),
            plan=plan,
            blocks=blocks,
            scene_items=scenes,
            scene_rows=scene_rows,
            ai_parts=ai_parts,
            segments=segments,
        )

    def recipient(self, tenant_id: UUID, user_id: UUID) -> Recipient | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text("""
                SELECT u.email, u.auth_user_id FROM users u
                JOIN tenant_members m ON m.user_id = u.id AND m.tenant_id = u.tenant_id
                WHERE u.id = :user AND u.auth_user_id IS NOT NULL
            """),
                {"user": user_id},
            ).first()
        if row is None:
            return None
        return Recipient(email=str(row.email), auth_user_id=row.auth_user_id)

    def freeze(self, mail: PendingMail, payload: Mapping[str, Any], *, now: datetime) -> bool:
        import json  # noqa: PLC0415

        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(mail.tenant_id) as session:
            return bool(
                session.execute(
                    text("""
                    UPDATE clip_avatar_failure_mails
                    SET payload = CAST(:payload AS jsonb), first_attempt_at = :now
                    WHERE id = :id AND lease_token = :lease AND first_attempt_at IS NULL
                """),
                    {
                        "payload": json.dumps(payload),
                        "now": now,
                        "id": mail.id,
                        "lease": mail.lease,
                    },
                ).rowcount
            )

    def close(self, mail: PendingMail, reason: str, *, now: datetime) -> None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        if reason not in CLOSE_REASONS:
            raise ValueError(reason)
        with tenant_session(mail.tenant_id) as session:
            session.execute(
                text("""
                UPDATE clip_avatar_failure_mails
                SET closed_at = :now, closed_reason = :reason,
                    lease_token = NULL, lease_until = NULL
                WHERE id = :id AND lease_token = :lease AND sent_at IS NULL
            """),
                {"now": now, "reason": reason, "id": mail.id, "lease": mail.lease},
            )

    def mark_sent(self, mail: PendingMail, provider_id: str | None, *, now: datetime) -> bool:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(mail.tenant_id) as session:
            return bool(
                session.execute(
                    text("""
                    UPDATE clip_avatar_failure_mails
                    SET sent_at = :now, provider_id = :provider,
                        lease_token = NULL, lease_until = NULL
                    WHERE id = :id AND lease_token = :lease AND sent_at IS NULL
                """),
                    {"now": now, "provider": provider_id, "id": mail.id, "lease": mail.lease},
                ).rowcount
            )


# -- in memory (tests, and the in-memory ContentService) --------------------------------------


@dataclass
class _MemoryRow:
    id: UUID
    tenant_id: UUID
    clip_id: UUID
    kind: str
    failed_at: datetime
    slots: tuple[int, ...]
    block_ids: tuple[UUID, ...]
    codes: tuple[str, ...]
    user_id: UUID
    key: str
    created_at: int
    payload: dict[str, Any] | None = None
    lease: UUID | None = None
    lease_until: datetime | None = None
    first_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    provider_id: str | None = None
    closed_reason: str | None = None
    revisions: tuple[int, ...] | None = None
    source_version: str = ""


@dataclass
class MemoryAvatarFailureOutbox:
    """The same rules as Postgres, in memory: `(clip, kind, failed_at)` and the key are
    unique, claims take a lease. `clips` / `recipients` are what the test says the
    database holds."""

    clips: dict[tuple[UUID, UUID], ClipView] = field(default_factory=dict)
    recipients: dict[tuple[UUID, UUID], Recipient] = field(default_factory=dict)
    rows: list[_MemoryRow] = field(default_factory=list)

    def stage(
        self,
        session: Any,
        *,
        tenant_id: UUID,
        clip_id: UUID,
        user_id: UUID,
        failures: Sequence[AvatarFailure],
    ) -> int:
        staged = 0
        for group in mail_groups(failures):
            key = failure_key(tenant_id, clip_id, group.kind, group.failed_at)
            if any(
                (r.clip_id, r.kind, r.failed_at) == (clip_id, group.kind, group.failed_at)
                or r.key == key
                for r in self.rows
            ):
                continue
            self.rows.append(
                _MemoryRow(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    clip_id=clip_id,
                    kind=group.kind,
                    failed_at=group.failed_at,
                    slots=group.slots,
                    block_ids=group.block_ids,
                    codes=group.codes,
                    user_id=user_id,
                    key=key,
                    created_at=len(self.rows),
                    revisions=group.revisions,
                    source_version=group.template_version,
                )
            )
            staged += 1
        return staged

    def mailed_ai_parts(
        self, session: Any, *, tenant_id: UUID, clip_id: UUID
    ) -> frozenset[tuple[UUID, int]]:
        return frozenset(
            (part_id, revision)
            for row in self.rows
            if row.tenant_id == tenant_id
            and row.clip_id == clip_id
            and row.kind == AI_PART_FAILED
            and row.revisions is not None
            for part_id, revision in zip(row.block_ids, row.revisions, strict=True)
        )

    def pending_tenants(self) -> list[UUID]:
        return list(
            dict.fromkeys(
                r.tenant_id for r in self.rows if r.sent_at is None and r.closed_reason is None
            )
        )

    def claim(self, tenant_id: UUID, *, now: datetime, include_new: bool) -> PendingMail | None:
        for row in sorted(self.rows, key=lambda r: r.created_at):
            if (
                row.tenant_id != tenant_id
                or row.sent_at is not None
                or row.closed_reason is not None
                or (row.lease_until is not None and row.lease_until > now)
                or (not include_new and row.first_attempt_at is None)
            ):
                continue
            row.lease, row.lease_until = uuid4(), now + LEASE
            return PendingMail(
                id=row.id,
                tenant_id=row.tenant_id,
                clip_id=row.clip_id,
                kind=row.kind,
                failed_at=row.failed_at,
                slots=row.slots,
                block_ids=row.block_ids,
                user_id=row.user_id,
                idempotency_key=row.key,
                lease=row.lease,
                payload=row.payload,
                first_attempt_at=row.first_attempt_at,
                revisions=row.revisions,
            )
        return None

    def clip_view(self, tenant_id: UUID, clip_id: UUID) -> ClipView | None:
        return self.clips.get((tenant_id, clip_id))

    def recipient(self, tenant_id: UUID, user_id: UUID) -> Recipient | None:
        return self.recipients.get((tenant_id, user_id))

    def _row(self, mail: PendingMail) -> _MemoryRow | None:
        row = next((r for r in self.rows if r.id == mail.id), None)
        return row if row is not None and row.lease == mail.lease else None

    def freeze(self, mail: PendingMail, payload: Mapping[str, Any], *, now: datetime) -> bool:
        row = self._row(mail)
        if row is None or row.first_attempt_at is not None:
            return False
        row.payload, row.first_attempt_at = dict(payload), now
        return True

    def close(self, mail: PendingMail, reason: str, *, now: datetime) -> None:
        if reason not in CLOSE_REASONS:
            raise ValueError(reason)
        row = self._row(mail)
        if row is not None and row.sent_at is None:
            row.closed_reason, row.lease, row.lease_until = reason, None, None

    def mark_sent(self, mail: PendingMail, provider_id: str | None, *, now: datetime) -> bool:
        row = self._row(mail)
        if row is None or row.sent_at is not None:
            return False
        row.sent_at, row.provider_id, row.lease, row.lease_until = now, provider_id, None, None
        return True


__all__ = [
    "AI_PART_MAIL_KIND",
    "SCENE_MAIL_KIND",
    "AiPartsDue",
    "AvatarFailure",
    "AvatarFailureOutbox",
    "ClipView",
    "MailGroup",
    "MemoryAvatarFailureOutbox",
    "PendingMail",
    "PostgresAvatarFailureOutbox",
    "Recipient",
    "ai_parts_mail_on",
    "failure_key",
    "failure_mail_chore",
    "mail_groups",
    "mailable_ai_part_failures",
    "mailable_failures",
    "send_pending",
]
