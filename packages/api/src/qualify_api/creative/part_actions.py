"""What the owner may do with a part of a video by parts that did not come out
(m-24921082, UI-7) — always on his explicit tap, never by itself.

- `retry_part` «Intentar de nuevo»: the same part made again, same form. With
  `PartChanges` it is «Cambiar»: its description or photos first (never its mode).
- `make_part_new` «Hacerla nueva»: an «Igual al original» part the original could not be
  used for (`refused_face`, a window that could not be cut…) made «Nueva, inspirada en
  el original» — the ONE change of form here, and only because the owner asked for it.

Both take a FAILED part (its vista previa was given back when it failed) to a new
revision in `drafting` through `DraftTrigger.PART_RETRY`, and charge it exactly as
creating the part did: one vista previa (`weight_for` of its brief, the same price
`create_parts` charged), refused with `NotEnoughCreations` before anything is written
when the month cannot pay — and given back again if this attempt fails too (the
generation's own refund at that revision). In ONE `tenant_unit_of_work` under the
parent's fence (`lock_parent_for_part_change`: a video being published, scheduled,
staged/published or purged refuses). «Hay que rehacerla» and «Venció» need no new
service: they are another version of a made part (`PartsService.regenerate_part`).

`remove_part` «Quitar parte» (m-24985192): a failed part is MARKED removed
(`content_drafts.part_removed_at`, Deivid's decision of 2026-11-09) — never deleted: its
charges, jobs and versions stay — and its video goes on without it. Nothing is charged.
Every reader of the video's parts skips it; `part_index` is not renumbered (it keys the
plan, the children and their provenance): the screens number the parts kept without gaps.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from qualify_creative.creations import weight_for
from qualify_creative.schemas import ContentBrief, VideoPartPlan
from sqlalchemy import text

from qualify_api.creative.fsm import (
    APPROVED,
    DRAFTING,
    FAILED,
    GENERATED,
    PUBLISHED,
    REJECTED,
    STAGED,
    DraftTrigger,
    apply_transition,
)
from qualify_api.creative.part_progress import (
    EDIT,
    EXTEND,
    PLANNED,
    PartAction,
    PartProgress,
    PartState,
    failed_part,
    read_part_progress,
)
from qualify_api.creative.parts import (
    PART_SCHEDULED_TEXT,
    PURGED_PARENT_TEXT,
    PartChangeRefused,
    PartChanges,
    PartsService,
    _child_brief,
    lock_parent_for_part_change,
    mark_parent_dirty,
    part_brief_with,
    part_changing,
    removed_part_indexes,
)
from qualify_api.creative.service import DraftRecord, UnknownDraft

# Refusals (nothing written, nothing charged). Copy proposed, pending UX review.
#: The part is being made again (another tab asked for it first).
PART_BEING_MADE_TEXT = "Esta parte ya se está creando otra vez. Mira cómo va en la lista."
#: The part has its vista previa again (made, or approved with its video).
PART_NOT_FAILED_TEXT = "Esta parte ya no necesita otro intento."
#: «Hacerla nueva» on a part that is already made new.
PART_ALREADY_NEW_TEXT = (
    "Esta parte ya se está haciendo nueva. Cuando termine, podrás cambiar sus fotos o quitarla."
)
#: m-24985192 «Quitar parte» (UX review of 2026-11-09): the only part left — «No salió».
PART_LAST_TEXT = (
    "Es la única parte de tu video, así que no se puede quitar. Intenta de nuevo o cámbiala."
)
#: The only part left, «No se pudo con el original» (it only offers «Hacerla nueva»).
PART_LAST_MAKE_NEW_TEXT = (
    "Es la única parte de tu video, así que no se puede quitar. Puedes hacerla nueva."
)
#: «Quitar parte» on a part that came out («Lista», «Para revisar»).
PART_CAME_OUT_TEXT = "Esta parte salió bien, así que se queda en tu video."
#: «Quitar parte» on a part in any other state that does not offer it.
PART_NOT_REMOVABLE_TEXT = "Solo puedes quitar una parte que no salió."
#: «Quitar parte» while the «Sigue a la anterior» part after it is being made: it would
#: be made continuing a part that is no longer in the video.
PART_NEXT_BEING_MADE_TEXT = (
    "La parte que sigue a esta se está creando ahora. Cuando termine, podrás quitar esta."
)
#: «Intentar de nuevo» on a «Nueva» part refused for its photos: the same photos would be
#: refused again.
PART_SAME_PHOTOS_TEXT = "Con las mismas fotos no saldría. Cambia las fotos de esta parte."
#: «Intentar de nuevo» / «Cambiar» on an «Igual al original» part the original cannot be
#: used for.
PART_ONLY_NEW_TEXT = "Esta parte no puede quedar igual al original. Puedes hacerla nueva."
#: «Hacerla nueva» on an «Igual al original» part that failed for another reason.
PART_RETRY_AS_IS_TEXT = "Esta parte se puede intentar de nuevo tal como está."


#: The part states whose part came out («Para revisar», «Lista»).
_CAME_OUT = frozenset({GENERATED, REJECTED, APPROVED})
#: The screen states «Crearla otra vez» is for (`part_progress.derive_state`).
_RECREATABLE = frozenset({PartState.REDO, PartState.EXPIRED})
#: Part statuses «Crearla otra vez» refuses before looking at the screen state.
_NEVER_RECREATED = frozenset({APPROVED, STAGED, PUBLISHED})


def _refusal(action: PartAction, mode: str, failure_reason: str | None) -> str | None:
    """Why the screen's rule (`part_progress.failed_part`) does not offer `action` on this
    failed part, or None when it does."""
    _, allowed = failed_part(mode, failure_reason)
    if action in allowed:
        return None
    if action is PartAction.MAKE_NEW:
        return PART_ALREADY_NEW_TEXT if mode != EDIT else PART_RETRY_AS_IS_TEXT
    if PartAction.MAKE_NEW in allowed:
        return PART_ONLY_NEW_TEXT
    return PART_SAME_PHOTOS_TEXT


@dataclass(frozen=True)
class _Sibling:
    """One part of the video as «Quitar parte» judges it."""

    draft_id: UUID | None  # None: in the plan, not made yet
    index: int
    status: str
    failure_reason: str | None
    mode: str
    removed: bool = False
    purged: bool = False


def _with_plan(parts: Sequence[_Sibling], plan_modes: Sequence[str]) -> list[_Sibling]:
    """Every place of the parent's plan (`plan_modes[i]` = the mode of part `i + 1`), the
    made ones as stored and the ones not made yet as `PLANNED`, in plan order. A made
    part outside the plan (never expected) is kept too. Pure."""
    made = {p.index: p for p in parts}
    out = [
        made.get(index)
        or _Sibling(draft_id=None, index=index, status=PLANNED, failure_reason=None, mode=mode)
        for index, mode in enumerate(plan_modes, start=1)
    ]
    out.extend(p for i, p in sorted(made.items()) if i > len(plan_modes))
    return out


def _check_removable(
    me: _Sibling, parts: Sequence[_Sibling], plan_modes: Sequence[str] = ()
) -> _Sibling | None:
    """Refuse «Quitar parte» on `me` (`PartChangeRefused`, the text says why), else the
    «Sigue a la anterior» part right after it that must become «Nueva» (None when the
    next kept part is not one). The parts left are counted on the parent's PLAN (its
    places minus the removed ones), so a part not made yet still counts. Pure."""
    if me.purged:
        raise PartChangeRefused(PURGED_PARENT_TEXT)
    if me.status == DRAFTING:
        raise PartChangeRefused(PART_BEING_MADE_TEXT)
    if me.status != FAILED or PartAction.REMOVE not in failed_part(me.mode, me.failure_reason)[1]:
        raise PartChangeRefused(
            PART_CAME_OUT_TEXT if me.status in _CAME_OUT else PART_NOT_REMOVABLE_TEXT
        )
    kept = [p for p in _with_plan(parts, plan_modes) if not p.removed]
    if len(kept) < 2:
        state, _ = failed_part(me.mode, me.failure_reason)
        raise PartChangeRefused(
            PART_LAST_MAKE_NEW_TEXT if state is PartState.ORIGINAL_REFUSED else PART_LAST_TEXT
        )
    after = next((p for p in kept if p.index > me.index), None)
    if after is None or after.mode != EXTEND:
        return None
    if after.draft_id is None:
        # not made yet: `PartsService.create_parts` («Crear las que faltan») makes it
        # «Nueva» since the part before it is removed
        return None
    # an `extend` continues the part right before it (`check_extend_parts`): with that
    # part gone it would continue nothing
    if after.status == DRAFTING:
        raise PartChangeRefused(PART_NEXT_BEING_MADE_TEXT)
    return after


def _siblings(session: Any, parent_id: UUID, *, lock: Sequence[UUID] = ()) -> list[_Sibling]:
    """The video's made parts in plan order; the rows in `lock` are locked first (in
    plan order, `FOR UPDATE`), then every part is read."""
    if lock:
        session.execute(
            text("""
            SELECT id FROM content_drafts WHERE id = ANY(:ids)
            ORDER BY part_index FOR UPDATE
        """),
            {"ids": list(lock)},
        )
    rows = (
        session.execute(
            text("""
            SELECT c.id, c.part_index, c.status, c.failure_reason,
                   c.part_removed_at IS NOT NULL AS removed,
                   c.media_purged_at IS NOT NULL AS purged,
                   b.media->'part'->>'mode' AS mode
            FROM content_drafts c JOIN content_briefs b ON b.id = c.brief_id
            WHERE c.parent_draft_id = :p
            ORDER BY c.part_index
        """),
            {"p": parent_id},
        )
        .mappings()
        .all()
    )
    return [
        _Sibling(
            draft_id=row["id"],
            index=int(row["part_index"]),
            status=str(row["status"]),
            failure_reason=row["failure_reason"],
            mode=str(row["mode"] or "reference"),
            removed=bool(row["removed"]),
            purged=bool(row["purged"]),
        )
        for row in rows
    ]


class PartRecovery:
    """«Intentar de nuevo», «Cambiar», «Hacerla nueva» and «Quitar parte» on a failed
    part."""

    def __init__(
        self,
        parts: PartsService,
        *,
        progress: Callable[..., PartProgress | None] = read_part_progress,
    ) -> None:
        self._parts = parts
        #: how a part's state is read (`read_part_progress`; a double in offline tests)
        self._progress = progress

    def recreate_part(
        self, *, tenant_id: UUID, parent_id: UUID, part_index: int, user_id: UUID
    ) -> UUID:
        """«Crearla otra vez» (`PartAction.RECREATE`): another version of a part as it is
        (`PartsService.regenerate_part` with empty `PartChanges`, 1 vista previa) — ONLY
        for a part the screen offers it on, «Hay que rehacerla» (`redo`) or «Venció»
        (`expired`, files not purged). The part's draft id.

        The state is derived as the screen derives it (`read_part_progress` →
        `derive_state`) INSIDE the transaction, after the video's fence
        (`lock_parent_for_part_change`: calendar events → video) and the part's row lock,
        so an old screen or a hand-made request never regenerates (and charges) a part
        that is `to_review`, `ready` or approved — nor sends an approved video back to the
        gate. Refused (`PartChangeRefused`, nothing written or charged): any other state
        (`PART_NOT_FAILED_TEXT`; `PART_BEING_MADE_TEXT` while it is being made), a purged
        part (`PURGED_PARENT_TEXT`), and everything the fence refuses. `UnknownDraft` for
        no such part of this business. `regenerate_part` itself stays unguarded: UI-8 and
        VE-10b call it on made and approved parts on purpose."""
        parent, _ = self._parts._parent(tenant_id, parent_id)
        child = self._child(tenant_id, parent_id, part_index)
        with self._parts._unit(tenant_id) as session:
            if session is not None:
                lock_parent_for_part_change(session, parent.id)
                status = session.execute(
                    text("SELECT status FROM content_drafts WHERE id = :c FOR UPDATE"),
                    {"c": child.id},
                ).scalar()
            else:
                if parent.status in (STAGED, PUBLISHED):
                    raise PartChangeRefused(PART_SCHEDULED_TEXT)
                status = child.status
            if status in _NEVER_RECREATED:
                # an approved part is never made again by this button, whatever its vista
                # previa's age: it would charge and send the approved video back to the gate
                raise PartChangeRefused(PART_NOT_FAILED_TEXT)
            progress = self._progress(tenant_id=tenant_id, parent_id=parent_id)
            row = next(
                (r for r in (progress.parts if progress else ()) if r.index == part_index),
                None,
            )
            if row is None or row.draft_id != child.id:
                raise UnknownDraft(f"{parent_id}#{part_index}")
            if row.purged:
                raise PartChangeRefused(PURGED_PARENT_TEXT)
            if row.state not in _RECREATABLE or PartAction.RECREATE not in row.actions:
                raise PartChangeRefused(
                    PART_BEING_MADE_TEXT
                    if row.state in (PartState.QUEUED, PartState.CREATING)
                    else PART_NOT_FAILED_TEXT
                )
            # same fence again inside (`part_changing`): re-entrant under this transaction
            return self._parts.regenerate_part(
                tenant_id=tenant_id,
                parent_id=parent_id,
                part_index=part_index,
                changes=PartChanges(),
                user_id=user_id,
            )

    @property
    def _content(self) -> Any:
        return self._parts._content

    @property
    def _repo(self) -> Any:
        return self._parts._repo

    def _child(self, tenant_id: UUID, parent_id: UUID, part_index: int) -> DraftRecord:
        child = next(
            (
                c
                for c in self._repo.parts_of(tenant_id=tenant_id, parent_id=parent_id)
                if c.part_index == part_index
            ),
            None,
        )
        if child is None:
            raise UnknownDraft(f"{parent_id}#{part_index}")
        return child

    def retry_part(
        self,
        *,
        tenant_id: UUID,
        parent_id: UUID,
        part_index: int,
        user_id: UUID,
        changes: PartChanges | None = None,
    ) -> UUID:
        """«Intentar de nuevo» (no `changes`) or «Cambiar» (its description and photos)
        of a failed part: made again in the form it has. The part's draft id."""
        parent, parent_brief = self._parts._parent(tenant_id, parent_id)
        child = self._child(tenant_id, parent_id, part_index)
        old = self._repo.get_brief(tenant_id=tenant_id, brief_id=child.brief_id)
        if old is None or old.media.part is None:
            raise UnknownDraft(str(child.id))
        new = part_brief_with(parent_brief, old, changes) if changes is not None else None
        self._restart(
            tenant_id,
            parent,
            child,
            new or old,
            action=PartAction.RETRY if changes is None else PartAction.CHANGE,
            mode=old.media.part.mode,
            replace=new,
            user_id=user_id,
        )
        return child.id

    def make_part_new(
        self, *, tenant_id: UUID, parent_id: UUID, part_index: int, user_id: UUID
    ) -> UUID:
        """«Hacerla nueva»: a failed «Igual al original» part made «Nueva, inspirada en el
        original» — same description, cuts, length and photos, no window of the reel. The
        part's draft id. Refused (`PartChangeRefused`, nothing written) on a part that is
        not «Igual al original»."""
        parent, parent_brief = self._parts._parent(tenant_id, parent_id)
        child = self._child(tenant_id, parent_id, part_index)
        old = self._repo.get_brief(tenant_id=tenant_id, brief_id=child.brief_id)
        if old is None or old.media.part is None:
            raise UnknownDraft(str(child.id))
        part = old.media.part
        if part.mode != "edit":
            raise PartChangeRefused(PART_ALREADY_NEW_TEXT)
        entry = VideoPartPlan.model_validate(
            {**part.model_dump(exclude={"index"}), "mode": "reference"}
        )
        fresh = _child_brief(parent_brief, entry, part_index, None)
        fresh = ContentBrief.model_validate(
            {
                **fresh.model_dump(),
                "media": {
                    **fresh.media.model_dump(),
                    # the photos the part had (the owner may have changed them)
                    "clip_image_keys": old.media.clip_image_keys,
                    "clip_image_roles": old.media.clip_image_roles,
                },
            }
        )
        fresh, _voice, pipeline_version = self._content.prepare_new_generation(
            tenant_id=tenant_id, brand_id=parent.brand_id, brief=fresh
        )
        self._restart(
            tenant_id,
            parent,
            child,
            fresh,
            action=PartAction.MAKE_NEW,
            mode=part.mode,
            replace=fresh,
            user_id=user_id,
            pipeline_version=pipeline_version,
        )
        return child.id

    def remove_part(
        self, *, tenant_id: UUID, parent_id: UUID, part_index: int, user_id: UUID
    ) -> bool:
        """«Quitar parte» (m-24985192): a FAILED part — the states that offer it, «No
        salió» and «No se pudo con el original» (`failed_part`) — is marked removed
        (`content_drafts.part_removed_at`) and its video goes on without it. True when
        this call removed it, False when it was removed already (idempotent).

        Nothing is deleted or charged: its charges (its vista previa was given back when
        it failed), jobs, versions and provenance stay, and the retention purge takes its
        files with its video. A «Sigue a la anterior» (`extend`) part right after it
        loses the part it continues, so it becomes «Nueva, inspirada en el original»
        (`reference`): a NEW brief (`replace_brief`), so the versions it already made keep
        the brief they were made from. The video is joined again without the part
        (`mark_parent_dirty`).

        In ONE `tenant_unit_of_work` under the parent's fence (`part_changing`: calendar
        events → video → part; a video being published, scheduled, staged/published or
        purged refuses, and an approved one goes back to the gate). Refused
        (`PartChangeRefused`, nothing written): the last part left (`PART_LAST_TEXT`), a
        part being made (`PART_BEING_MADE_TEXT`), one that came out
        (`PART_NOT_REMOVABLE_TEXT`), a part whose files were purged, or while the
        «Sigue a la anterior» part after it is being made (`PART_NEXT_BEING_MADE_TEXT`).
        `UnknownDraft` for no such video or part of this business (RLS)."""
        parent, parent_brief = self._parts._parent(tenant_id, parent_id)
        plan_modes = tuple(entry.mode for entry in parent_brief.media.parts)
        with self._parts._unit(tenant_id) as session:
            if session is None:
                return self._remove_in_memory(tenant_id, parent, part_index, user_id, plan_modes)
            child = (
                session.execute(
                    text("""
                    SELECT id, part_removed_at IS NOT NULL AS removed FROM content_drafts
                    WHERE parent_draft_id = :p AND part_index = :i
                """),
                    {"p": parent_id, "i": part_index},
                )
                .mappings()
                .first()
            )
            if child is None:
                raise UnknownDraft(f"{parent_id}#{part_index}")
            if child["removed"]:
                return False
            with part_changing(session, tenant_id, parent_id, child["id"], "part_removed"):
                # The fence locked the video, which serializes every removal of its parts
                # (the count of parts left cannot move under us). Only the part removed and
                # the one after it are locked, in plan order — the only rows written here.
                # Locking every sibling would hold rows the generation path updates
                # without the video's lock; with two rows the window for a lock cycle is
                # the smallest possible.
                facts = _siblings(session, parent_id)
                first = next(f for f in facts if f.index == part_index)
                follower = next((f for f in facts if f.index > part_index and not f.removed), None)
                locked = [first.draft_id]
                if follower is not None and follower.draft_id is not None:
                    locked.append(follower.draft_id)
                facts = _siblings(session, parent_id, lock=locked)
                me = next(f for f in facts if f.index == part_index)
                if me.removed:
                    return False  # another tab removed it while we waited for the lock
                after = _check_removable(me, facts, plan_modes)
                if after is not None and after.draft_id is not None:
                    self._as_reference(tenant_id, after.draft_id, user_id)
                if not self._repo.mark_part_removed(
                    tenant_id=tenant_id, draft_id=me.draft_id, user_id=user_id
                ):
                    return False
                mark_parent_dirty(session, me.draft_id)
            return True

    def _remove_in_memory(
        self,
        tenant_id: UUID,
        parent: DraftRecord,
        part_index: int,
        user_id: UUID,
        plan_modes: Sequence[str],
    ) -> bool:
        """`remove_part` for the in-memory doubles (no transaction, no lock)."""
        if parent.status in (STAGED, PUBLISHED):
            raise PartChangeRefused(PART_SCHEDULED_TEXT)
        removed = removed_part_indexes(self._repo, tenant_id=tenant_id, parent_id=parent.id)
        if part_index in removed:
            return False
        kept = self._repo.parts_of(tenant_id=tenant_id, parent_id=parent.id)
        facts = [
            _Sibling(
                draft_id=None, index=i, status=FAILED, failure_reason=None, mode="", removed=True
            )
            for i in removed
        ]
        for record in kept:
            brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
            part = None if brief is None else brief.media.part
            facts.append(
                _Sibling(
                    draft_id=record.id,
                    index=int(record.part_index or 0),
                    status=record.status,
                    failure_reason=record.failure_reason,
                    mode=part.mode if part is not None else "reference",
                )
            )
        me = next((f for f in facts if f.index == part_index), None)
        if me is None:
            raise UnknownDraft(f"{parent.id}#{part_index}")
        after = _check_removable(me, facts, plan_modes)
        if after is not None and after.draft_id is not None:
            self._as_reference(tenant_id, after.draft_id, user_id)
        assert me.draft_id is not None
        return bool(
            self._repo.mark_part_removed(tenant_id=tenant_id, draft_id=me.draft_id, user_id=user_id)
        )

    def _as_reference(self, tenant_id: UUID, draft_id: UUID, user_id: UUID) -> None:
        """An orphan «Sigue a la anterior» part made «Nueva, inspirada en el original»:
        a new brief with the same description, cuts, length and photos (the rule of
        `parts_plan._same_entries`: an orphan `extend` comes back as `reference`)."""
        record = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        old = (
            None
            if record is None
            else self._repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
        )
        if old is None or old.media.part is None:
            raise UnknownDraft(str(draft_id))
        fresh = ContentBrief.model_validate(
            {
                **old.model_dump(),
                "media": {
                    **old.media.model_dump(),
                    "part": old.media.part.model_copy(update={"mode": "reference"}),
                    "clip_reference_mode": "motion",
                },
            }
        )
        self._repo.replace_brief(
            tenant_id=tenant_id, draft_id=draft_id, user_id=user_id, brief=fresh
        )

    def _restart(
        self,
        tenant_id: UUID,
        parent: DraftRecord,
        child: DraftRecord,
        priced: ContentBrief,
        *,
        action: PartAction,
        mode: str,
        replace: ContentBrief | None,
        user_id: UUID,
        pipeline_version: str | None = None,
    ) -> None:
        """The part's new revision: fence, charge, brief, revision, status, dispatch — one
        transaction on Postgres; a refusal writes nothing. Only what the screen offers for
        this failed part (`failed_part`) is done: e.g. a «Nueva» part refused for its
        photos is never asked again with the same photos."""
        with self._parts._unit(tenant_id) as session:
            if session is not None:
                lock_parent_for_part_change(session, parent.id)
                locked = session.execute(
                    text(
                        "SELECT status, revision, failure_reason, "
                        "media_purged_at IS NOT NULL AS purged "
                        "FROM content_drafts WHERE id = :c FOR UPDATE"
                    ),
                    {"c": child.id},
                ).first()
                if locked is None:
                    raise UnknownDraft(str(child.id))
                if locked.purged:  # the part's own files were purged (m-24921069)
                    raise PartChangeRefused(PURGED_PARENT_TEXT)
                status, revision = str(locked.status), int(locked.revision)
                reason = locked.failure_reason
            else:
                if parent.status in (STAGED, PUBLISHED):
                    raise PartChangeRefused(PART_SCHEDULED_TEXT)
                current = self._repo.get_draft(tenant_id=tenant_id, draft_id=child.id)
                status, revision = current.status, current.revision
                reason = current.failure_reason
            if status != FAILED:
                raise PartChangeRefused(
                    PART_BEING_MADE_TEXT if status == DRAFTING else PART_NOT_FAILED_TEXT
                )
            refused = _refusal(action, mode, reason)
            if refused is not None:
                raise PartChangeRefused(refused)
            new_status = apply_transition(status, DraftTrigger.PART_RETRY)
            creations = self._content.creations
            if creations is not None:
                # the same price creating the part charged (`create_parts`): 1 vista previa
                creations.charge(
                    tenant_id=tenant_id,
                    brand_id=parent.brand_id,
                    draft_id=child.id,
                    revision=revision + 1,
                    price=weight_for(priced),
                )
            if replace is not None:
                self._repo.replace_brief(
                    tenant_id=tenant_id, draft_id=child.id, user_id=user_id, brief=replace
                )
            if session is not None and pipeline_version is not None:
                # the version `prepare_new_generation` stamped the new brief for
                self._repo.bump_revision(
                    tenant_id=tenant_id, draft_id=child.id, pipeline_version=pipeline_version
                )
            else:
                self._repo.bump_revision(tenant_id=tenant_id, draft_id=child.id)
            self._repo.update_status(
                tenant_id=tenant_id, draft_id=child.id, new_status=new_status, failure_reason=None
            )
            if session is not None:
                session.execute(
                    text("UPDATE content_drafts SET failure_detail = NULL WHERE id = :c"),
                    {"c": child.id},
                )
            dispatcher = self._content.dispatcher
            if dispatcher is not None:
                dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=child.id)


__all__ = [
    "PART_ALREADY_NEW_TEXT",
    "PART_BEING_MADE_TEXT",
    "PART_CAME_OUT_TEXT",
    "PART_LAST_MAKE_NEW_TEXT",
    "PART_LAST_TEXT",
    "PART_NEXT_BEING_MADE_TEXT",
    "PART_NOT_FAILED_TEXT",
    "PART_NOT_REMOVABLE_TEXT",
    "PART_ONLY_NEW_TEXT",
    "PART_RETRY_AS_IS_TEXT",
    "PART_SAME_PHOTOS_TEXT",
    "PartRecovery",
]
