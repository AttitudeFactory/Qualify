"""m-25128784 PR 3 of 3 (ADR 50 §12): what the owner does with a character scene that
failed, while its Clip waits for them (`drafting`, the owner's 72 h of §11 P2).

The failure email of m-25120319 names the two choices, and these are their exact words:

- **«Intentar de nuevo»** (`retry_scene`): a NEW attempt of the same scene — its child
  draft goes to its next revision (`PART_RETRY`), 1 vista previa is charged on that
  revision now (`character_scene_price`, D7; given back by the run when the vendor
  delivers nothing) and it is one more scene of the business's day (§11 P1: a retry
  counts). The Clip's item loses its `failed_at` in a new brief (the provenance of the
  one before stays), so a new failure is stamped and mailed again. Everything is checked
  BEFORE anything is written or paid: the switch, the Clip still waiting with the brief
  we read, the scene failed (a double tap while it is being made again is the answer
  itself), its character still usable (never a scene the vendor already refused as a
  real face: the owner redraws it), its files the business's, today's cap and the
  month (1 vista previa now, its seconds at approval with every uncharged scene).
- **«Quitar escena»** (`remove_scene`): the scene leaves the Clip's «Personajes» track
  (a new brief without its item) and its child is MARKED removed
  (`content_drafts.part_removed_at`) in the same write — nothing deleted, nothing
  charged; its vista previa was given back when it failed. The Clip goes on with the
  other scenes; with none left it is made from the owner's own material.

Both run in ONE transaction under the business's lock, with the Clip then the scene
locked `FOR UPDATE` (the order the Clip's own wait takes them); dispatch happens after the
commit (`ClipAvatarService._write_and_dispatch`). Tenant isolation: every read through the
content repository or the scenes' store (`tenant_session`, RLS).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from qualify_creative.creations import character_scene_price
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import ContentBrief

from qualify_api.creative.character_scene import (
    FILE_NOT_OWNED,
    FILE_NOT_OWNED_TEXT,
    NEEDS_REDRAW,
    NEEDS_REDRAW_TEXT,
    CharacterReferenceSource,
    CharacterSceneService,
    CharacterSceneStore,
    PlacedScene,
    PostgresCharacterSceneStore,
    SceneRowsStore,
    check_character,
    placed_scenes,
    refuse_if_off,
)
from qualify_api.creative.clip_avatar import ClipAvatarRefused

logger = logging.getLogger(__name__)

#: The two choices, in the words of the failure email (`mail.clip_avatar.SCENE_LEAD`).
RETRY_LABEL = "Intentar de nuevo"
REMOVE_LABEL = "Quitar escena"

# -- what the owner reads (Spanish, `qualify-copy-es`) -------------------------------------

CLIP_NOT_WAITING = "clip_not_waiting"
CLIP_NOT_WAITING_TEXT = (
    "Este video ya no necesita que elijas nada. Ábrelo de nuevo para ver cómo quedó."
)
SCENE_NOT_FAILED = "scene_not_failed"
SCENE_NOT_FAILED_TEXT = "Esta escena no falló. No hace falta intentarla de nuevo."
SCENE_NOT_REMOVABLE = "scene_not_removable"
SCENE_NOT_REMOVABLE_TEXT = (
    "Esta escena salió bien, así que se queda en tu video. "
    "Solo puedes quitar una escena que no se pudo crear."
)


class _BriefMoved(ClipAvatarRefused):
    """The Clip still waits but its brief changed under us (its pass stamped a failure):
    the action reads the Clip again ONCE."""

    def __init__(self) -> None:
        super().__init__(CLIP_NOT_WAITING, CLIP_NOT_WAITING_TEXT, raw="brief moved")


class CharacterSceneActions(CharacterSceneService):
    """«Intentar de nuevo» and «Quitar escena» of a failed scene, over the same
    `ContentService` (drafts, quota, dispatch) and the scenes' stores."""

    def __init__(
        self,
        content: Any,
        *,
        references: CharacterReferenceSource,
        store: CharacterSceneStore | None = None,
        rows: SceneRowsStore | None = None,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(content, references=references, store=store, env=env, clock=clock)
        found = rows or getattr(content, "_character_scene_store", None)
        self._rows: SceneRowsStore = found or PostgresCharacterSceneStore()

    # -- «Intentar de nuevo» ---------------------------------------------------------------

    def retry_scene(self, *, tenant_id: UUID, user_id: UUID, clip_id: UUID, scene_id: UUID) -> UUID:
        """«Intentar de nuevo» of a failed scene (module docstring). The scene's id.
        Refused with nothing written nor paid (`ClipAvatarRefused`, `NotEnoughCreations`)."""
        try:
            return self._retry_once(tenant_id, user_id, clip_id, scene_id)
        except _BriefMoved:
            return self._retry_once(tenant_id, user_id, clip_id, scene_id)

    def _retry_once(self, tenant_id: UUID, user_id: UUID, clip_id: UUID, scene_id: UUID) -> UUID:
        from qualify_api.creative.fsm import FAILED, DraftTrigger, apply_transition  # noqa: PLC0415
        from qualify_api.creative.media import owned_by  # noqa: PLC0415

        refuse_if_off(self._env)
        clip, brief = self._waiting_clip(tenant_id, clip_id)
        placed = self._placed(tenant_id, clip_id, brief, scene_id)
        row = placed.row
        assert row is not None
        if row.status == "drafting":
            return scene_id  # being made again already (a double tap, another tab)
        if not row.failed:
            raise ClipAvatarRefused(SCENE_NOT_FAILED, SCENE_NOT_FAILED_TEXT)
        if row.failure_reason == NEEDS_REDRAW:
            # the vendor refused this character as a real face: the same one fails again
            raise ClipAvatarRefused(NEEDS_REDRAW, NEEDS_REDRAW_TEXT, raw="retry refused")
        item = placed.item
        if any(
            not owned_by(tenant_id, key) for key in (item.product.photo_key, item.background.key)
        ):
            raise ClipAvatarRefused(FILE_NOT_OWNED, FILE_NOT_OWNED_TEXT, raw="a file of another")
        reference = self._references.scene_character(
            tenant_id=tenant_id, brand_id=clip.brand_id, character_id=item.character_id
        )
        check_character(reference, self._clock())
        clip_after = _with_scenes(
            brief,
            tuple(
                scene.model_copy(update={"failed_at": None}) if index == placed.index else scene
                for index, scene in enumerate(brief.media.character_scenes)
            ),
            clip.brief_id,
        )
        repo = self._content.repository

        def write() -> list[UUID]:
            status, revision, removed = self._lock(tenant_id, clip, scene_id)
            if removed:
                # «Quitar escena» won meanwhile (another tab): never made again
                raise ClipAvatarRefused(CLIP_NOT_WAITING, CLIP_NOT_WAITING_TEXT, raw="removed")
            if status == "drafting":
                return []  # made again meanwhile: nothing more
            if status != FAILED:
                raise ClipAvatarRefused(SCENE_NOT_FAILED, SCENE_NOT_FAILED_TEXT)
            # §11 P1: a retry is one more scene of the day; the month pays its vista
            # previa now and its seconds at the Clip's approval
            self._check_daily_cap(tenant_id, asking=1)
            self._check_month(tenant_id, clip.brand_id, scenes=1, seconds=int(item.duration))
            creations = self._content.creations
            if creations is not None:
                creations.charge(
                    tenant_id=tenant_id,
                    brand_id=clip.brand_id,
                    draft_id=scene_id,
                    revision=revision + 1,
                    price=character_scene_price(item.duration),
                )
            repo.bump_revision(tenant_id=tenant_id, draft_id=scene_id)
            repo.update_status(
                tenant_id=tenant_id,
                draft_id=scene_id,
                new_status=apply_transition(status, DraftTrigger.PART_RETRY),
                failure_reason=None,
            )
            self._tx._clear_failure_detail(tenant_id, scene_id)  # noqa: SLF001
            repo.replace_brief(
                tenant_id=tenant_id, draft_id=clip.id, user_id=user_id, brief=clip_after
            )
            return [scene_id]

        self._tx._write_and_dispatch(tenant_id, write)  # noqa: SLF001
        logger.info("clip %s: character scene %s asked for again", clip_id, scene_id)
        return scene_id

    # -- «Quitar escena» -------------------------------------------------------------------

    def remove_scene(
        self, *, tenant_id: UUID, user_id: UUID, clip_id: UUID, scene_id: UUID
    ) -> bool:
        """«Quitar escena» of a failed scene (module docstring). True when this call removed
        it, False when it was removed already (idempotent). Refused with nothing written:
        the Clip no longer waits, or the scene did not fail (`scene_not_removable`)."""
        try:
            return self._remove_once(tenant_id, user_id, clip_id, scene_id)
        except _BriefMoved:
            return self._remove_once(tenant_id, user_id, clip_id, scene_id)

    def _remove_once(self, tenant_id: UUID, user_id: UUID, clip_id: UUID, scene_id: UUID) -> bool:
        from qualify_api.creative.service import UnknownDraft  # noqa: PLC0415

        rows = self._rows.scene_rows(tenant_id=tenant_id, clip_id=clip_id)
        mine = next((r for r in rows if r.id == scene_id), None)
        if mine is None:
            raise UnknownDraft(str(scene_id))
        if mine.removed:
            return False
        clip, brief = self._waiting_clip(tenant_id, clip_id)
        placed = self._placed(tenant_id, clip_id, brief, scene_id)
        assert placed.row is not None
        if not placed.row.failed:
            raise ClipAvatarRefused(SCENE_NOT_REMOVABLE, SCENE_NOT_REMOVABLE_TEXT)
        clip_after = _with_scenes(
            brief,
            tuple(
                scene
                for index, scene in enumerate(brief.media.character_scenes)
                if index != placed.index
            ),
            clip.brief_id,
        )
        repo = self._content.repository
        removed: list[bool] = []

        def write() -> list[UUID]:
            status, _revision, gone = self._lock(tenant_id, clip, scene_id)
            if gone:
                removed.append(False)  # another tab removed it while we waited
                return []
            if status != "failed":
                raise ClipAvatarRefused(SCENE_NOT_REMOVABLE, SCENE_NOT_REMOVABLE_TEXT)
            removed.append(
                bool(
                    repo.mark_part_removed(tenant_id=tenant_id, draft_id=scene_id, user_id=user_id)
                )
            )
            repo.replace_brief(
                tenant_id=tenant_id, draft_id=clip.id, user_id=user_id, brief=clip_after
            )
            self._wake(tenant_id, clip.id)
            return []

        self._tx._write_and_dispatch(tenant_id, write)  # noqa: SLF001
        done = bool(removed and removed[0])
        if done:
            logger.info("clip %s: character scene %s removed by its owner", clip_id, scene_id)
        return done

    # -- reads and locks -------------------------------------------------------------------

    def _waiting_clip(self, tenant_id: UUID, clip_id: UUID) -> tuple[Any, ContentBrief]:
        """The Clip, still waiting for its scenes (`drafting`, a top-level `CLIP` with a
        «Personajes» track) — else `clip_not_waiting`. `UnknownDraft` for no Clip of this
        business (RLS)."""
        from qualify_api.creative.service import UnknownDraft  # noqa: PLC0415

        repo = self._content.repository
        clip = repo.get_draft(tenant_id=tenant_id, draft_id=clip_id)
        if clip is None or clip.parent_draft_id is not None:
            raise UnknownDraft(str(clip_id))
        brief = repo.get_brief(tenant_id=tenant_id, brief_id=clip.brief_id)
        if brief is None:
            raise UnknownDraft(str(clip_id))
        if (
            clip.status != "drafting"
            or brief.kind is not ContentKind.CLIP
            or not brief.media.character_scenes
        ):
            raise ClipAvatarRefused(CLIP_NOT_WAITING, CLIP_NOT_WAITING_TEXT)
        return clip, brief

    def _placed(
        self, tenant_id: UUID, clip_id: UUID, brief: ContentBrief, scene_id: UUID
    ) -> PlacedScene:
        """The Clip's scene whose child is `scene_id` (`placed_scenes`)."""
        from qualify_api.creative.service import UnknownDraft  # noqa: PLC0415

        rows = self._rows.scene_rows(tenant_id=tenant_id, clip_id=clip_id)
        if not any(row.id == scene_id for row in rows):
            raise UnknownDraft(str(scene_id))
        found = next(
            (
                p
                for p in placed_scenes(brief.media.character_scenes, rows)
                if p.row is not None and p.row.id == scene_id
            ),
            None,
        )
        if found is None:
            # removed, or no longer the scene the Clip plays
            raise ClipAvatarRefused(CLIP_NOT_WAITING, CLIP_NOT_WAITING_TEXT, raw="not placed")
        return found

    def _is_postgres(self) -> bool:
        from qualify_api.creative.service import PostgresContentRepository  # noqa: PLC0415

        return isinstance(self._content.repository, PostgresContentRepository)

    def _lock(self, tenant_id: UUID, clip: Any, scene_id: UUID) -> tuple[str, int, bool]:
        """Inside the unit of work: the Clip, then the scene, `FOR UPDATE`. The Clip must
        still wait with the brief we read (another brief is `_BriefMoved`). The scene's
        (status, revision, removed) now."""
        if not self._is_postgres():
            repo = self._content.repository
            now = repo.get_draft(tenant_id=tenant_id, draft_id=clip.id)
            if now is None or now.status != "drafting":
                raise ClipAvatarRefused(CLIP_NOT_WAITING, CLIP_NOT_WAITING_TEXT, raw="moved")
            if now.brief_id != clip.brief_id:
                raise _BriefMoved()
            scene = repo.get_draft(tenant_id=tenant_id, draft_id=scene_id)
            row = next(
                (
                    r
                    for r in self._rows.scene_rows(tenant_id=tenant_id, clip_id=clip.id)
                    if r.id == scene_id
                ),
                None,
            )
            if scene is None or row is None:
                raise ClipAvatarRefused(CLIP_NOT_WAITING, CLIP_NOT_WAITING_TEXT, raw="gone")
            return str(scene.status), int(scene.revision), bool(row.removed)
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            locked = session.execute(
                text("SELECT status, brief_id FROM content_drafts WHERE id = :c FOR UPDATE"),
                {"c": clip.id},
            ).first()
            if locked is None or str(locked.status) != "drafting":
                raise ClipAvatarRefused(CLIP_NOT_WAITING, CLIP_NOT_WAITING_TEXT, raw="moved")
            if locked.brief_id != clip.brief_id:
                raise _BriefMoved()
            scene = session.execute(
                text("""
                SELECT status, revision, part_removed_at IS NOT NULL AS removed
                FROM content_drafts WHERE id = :s AND parent_draft_id = :c FOR UPDATE
            """),
                {"s": scene_id, "c": clip.id},
            ).first()
        if scene is None:
            raise ClipAvatarRefused(CLIP_NOT_WAITING, CLIP_NOT_WAITING_TEXT, raw="gone")
        return str(scene.status), int(scene.revision), bool(scene.removed)

    def _wake(self, tenant_id: UUID, clip_id: UUID) -> None:
        """Open or dirty the waiting Clip's `generation` run so it is made as soon as
        nothing is left to wait for (in the caller's transaction)."""
        if not self._is_postgres():
            return
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            session.execute(
                text("""
                INSERT INTO creative_pipeline_runs AS r
                    (tenant_id, draft_id, revision, phase, pipeline_version)
                SELECT p.tenant_id, p.id, p.revision, 'generation', p.pipeline_version
                FROM content_drafts p WHERE p.id = :c AND p.status = 'drafting'
                ON CONFLICT (tenant_id, draft_id, revision, phase)
                DO UPDATE SET dirty_version = r.dirty_version + 1
            """),
                {"c": clip_id},
            )


def _with_scenes(brief: ContentBrief, scenes: tuple[Any, ...], brief_id: UUID) -> ContentBrief:
    """The Clip's brief with its «Personajes» track replaced, pointing to the one it came
    from (provenance: the brief the owner sent stays). Pure."""
    media = brief.media.model_copy(
        update={
            "character_scenes": scenes,
            "derived_from_brief_id": brief.media.derived_from_brief_id or brief_id,
        }
    )
    return brief.model_copy(update={"media": media})


__all__ = [
    "CLIP_NOT_WAITING",
    "CLIP_NOT_WAITING_TEXT",
    "REMOVE_LABEL",
    "RETRY_LABEL",
    "SCENE_NOT_FAILED",
    "SCENE_NOT_FAILED_TEXT",
    "SCENE_NOT_REMOVABLE",
    "SCENE_NOT_REMOVABLE_TEXT",
    "CharacterSceneActions",
]
