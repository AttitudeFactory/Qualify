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
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from qualify_creative.creations import weight_for
from qualify_creative.schemas import ContentBrief, VideoPartPlan
from sqlalchemy import text

from qualify_api.creative.fsm import (
    DRAFTING,
    FAILED,
    PUBLISHED,
    STAGED,
    DraftTrigger,
    apply_transition,
)
from qualify_api.creative.part_progress import EDIT, PartAction, failed_part
from qualify_api.creative.parts import (
    PART_SCHEDULED_TEXT,
    PURGED_PARENT_TEXT,
    PartChangeRefused,
    PartChanges,
    PartsService,
    _child_brief,
    lock_parent_for_part_change,
    part_brief_with,
)
from qualify_api.creative.service import DraftRecord, UnknownDraft

# Refusals (nothing written, nothing charged). Copy proposed, pending UX review.
#: The part is being made again (another tab asked for it first).
PART_BEING_MADE_TEXT = "Esta parte ya se está creando otra vez. Mira cómo va en la lista."
#: The part has its vista previa again (made, or approved with its video).
PART_NOT_FAILED_TEXT = "Esta parte ya no necesita otro intento."
#: «Hacerla nueva» on a part that is already made new.
PART_ALREADY_NEW_TEXT = (
    "Esta parte ya se está haciendo nueva. Si quieres otra cosa, cambia sus fotos."
)
#: «Intentar de nuevo» on a «Nueva» part refused for its photos: the same photos would be
#: refused again.
PART_SAME_PHOTOS_TEXT = "Con las mismas fotos no saldría. Cambia las fotos de esta parte."
#: «Intentar de nuevo» / «Cambiar» on an «Igual al original» part the original cannot be
#: used for.
PART_ONLY_NEW_TEXT = "Esta parte no puede quedar igual al original. Puedes hacerla nueva."
#: «Hacerla nueva» on an «Igual al original» part that failed for another reason.
PART_RETRY_AS_IS_TEXT = "Esta parte se puede intentar de nuevo tal como está."


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


class PartRecovery:
    """«Intentar de nuevo», «Cambiar» and «Hacerla nueva» on a failed part."""

    def __init__(self, parts: PartsService) -> None:
        self._parts = parts

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
    "PART_NOT_FAILED_TEXT",
    "PART_ONLY_NEW_TEXT",
    "PART_RETRY_AS_IS_TEXT",
    "PART_SAME_PHOTOS_TEXT",
    "PartRecovery",
]
