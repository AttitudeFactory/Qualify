"""m-25129408 (ADR 50 §13.4, built with §12.4 of m-25128784): approving a Clip with AI
children — ONE path for its «parte con IA» children and its character scenes.

The Clip is the only container (§13.2). Its AI children are made as 480p drafts at
«Crear» (1 vista previa each, `charge_many`) and the Clip is assembled locally from them.
Approving it (`ContentService.approve`, `_approve_clip_children`) does, for both kinds of
child alike:

1. **Checks before any write.** Every child is made and still plays in the Clip the owner
   saw (`children_problem`), no child's draft expired, the copy passes the approval guard,
   and the month pays the REQUESTED seconds of every child not charged yet — all or
   nothing, in ONE `charged_videos_many` call on each child's own charge row at its
   generation's revision (§13.4.2). A child already charged (another approval of the Clip,
   «Aprobar» twice) is skipped by the ledger: never charged twice.
2. **Writes, in one transaction** (the Clip's row lock serializes a double tap): the Clip
   and its children approved through the state machine, and the Clip's video marked
   `clip_final_pending` (`params.draft`, `finish = clip_final`) — which keeps it out of
   the calendar (`draft_mode.draft_pending`) until its final is in place and confirmed.
3. **Then the finals** (the queue's outbox commits with the approval): each child's 1080p
   from its draft task (`_order_finals`: an AI part's `part_final`, a scene's Seedance
   final), charged on the revision that paid it so a failed one gives its seconds back
   there (D9, `_refund_final_part`).
4. **The Clip assembled again with the finals** (`run_clip_final`, the worker's
   `clip_final` phase, opened when the last child's final is kept — `open_clip_final` in
   `settle_final`): the same recipe, each AI part stretch now playing its 1080p
   (`final_brief`) and each scene laid from its final (the scene's row reads it), made by
   the same local assembly at US$0. The Clip's video row takes the new file IN PLACE with
   the provenance of every child's final (`clip_final.children`), its preview file kept on
   record. A run that fails marks the row `clip_final_failed` and the Clip keeps its
   preview video — nothing the owner had is lost; «Intentar de nuevo» (`retry_final`)
   orders again what failed (children's finals free, never charged again) and reopens the
   run. Assembling again is automatic: it never counts in the day's 10 local builds
   (§13.5, answer 5).

Idempotent: a second approval of the same Clip charges, writes and orders nothing; the
child's final has one claim per order (`claim_final`); the assembly's run is one row per
(Clip, revision, phase) and its save is fenced by the run's lease and by the pending block.
Tenant isolation: every read and write through `tenant_session` / `tenant_unit_of_work`.
No migration: the block lives in `image_assets.params`, the phase is a new value of
`creative_pipeline_runs.phase` (no check constraint).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from qualify_creative.enums import ContentKind
from qualify_creative.queue_errors import FINAL_EXPIRED_TEXT
from qualify_creative.schemas import ContentBrief

from qualify_api.creative.draft_mode import (
    DRAFT_EXPIRED_TEXT,
    DRAFT_FAILED,
    DRAFT_FINAL,
    DRAFT_FINAL_READY,
    draft_expired,
    draft_state,
    final_retryable,
)

logger = logging.getLogger(__name__)

#: The worker's phase that assembles an approved Clip again with its children's finals.
CLIP_FINAL_PHASE = "clip_final"
#: `params.draft.finish` of the Clip's video while it waits for (or holds) that final.
FINISH_CLIP_FINAL = "clip_final"
#: Approved, waiting for the children's finals and its assembly.
CLIP_FINAL_PENDING = "clip_final_pending"
#: The assembly with the finals failed: the Clip keeps its preview video.
CLIP_FINAL_FAILED = "clip_final_failed"
#: Provenance of this path's rules.
CLIP_FINAL_VERSION = "clip-final-v1"

#: `part_final.PART_FINAL` (a part's kept raw 1080p), without importing that module here.
_PART_FINAL = "part_final"

ChildKind = Literal["ai_part", "scene"]
ChildFinalState = Literal["kept", "waiting", "failed", "expired"]

# -- what the owner reads (Spanish, `qualify-copy-es`) -------------------------------------

#: A child is not made (still being made, failed, or made again since the Clip was put
#: together): approving waits.
CHILDREN_NOT_READY = "clip_children_not_ready"
CHILDREN_NOT_READY_TEXT = (
    "Una parte de tu video todavía no está lista. Cuando termine, podrás aprobarlo."
)
#: The video the owner saw is not the one its children make now.
CHILDREN_CHANGED = "clip_children_changed"
CHILDREN_CHANGED_TEXT = (
    "Tu video cambió mientras lo veías. Ábrelo de nuevo y revísalo antes de aprobarlo."
)
#: The assembly with the finals failed: the preview video stays (assembling costs 0).
CLIP_FINAL_FAILED_TEXT = (
    "No pudimos preparar la versión final de tu video. Tu video sigue como lo aprobaste. "
    "Toca «Intentar de nuevo»: no se te cobra otra vez."
)
#: What the Clip shows while it waits (`final_view`). No notice is sent: the screen shows it.
WAITING_TEXT = "Estamos preparando la versión final de tu video. Cuando esté lista, la verás aquí."
#: A child's final failed and its seconds went back (D9: its block is `failed`).
CHILD_FINAL_FAILED_TEXT = (
    "No pudimos preparar la versión final de una parte de tu video. Te devolvimos sus "
    "segundos. Toca «Intentar de nuevo»: no se te cobra otra vez."
)
#: A child's final never left, or was left half-made: nothing failed, nothing given back.
CHILD_FINAL_STUCK_TEXT = (
    "La versión final de una parte de tu video no avanzó. "
    "Toca «Intentar de nuevo»: no se te cobra otra vez."
)
#: A child's vendor draft expired before its final was made: no final can be made from
#: it any more, and it is not marked (nor given back) yet: the owner's tap does both.
CHILD_EXPIRED_UNSETTLED_TEXT = (
    "Ya no podemos preparar la versión final de una parte de tu video porque pasó mucho "
    "tiempo. Toca «Intentar de nuevo» y te devolvemos sus segundos."
)
#: The same, once marked and its seconds given back. Terminal: no «Intentar de nuevo».
CHILD_EXPIRED_TEXT = (
    "Ya no podemos preparar la versión final de una parte de tu video porque pasó mucho "
    "tiempo. Te devolvimos sus segundos. Crea el video de nuevo para tener su versión final."
)
READY_TEXT = "La versión final de tu video está lista. Revísala antes de programarla."


def child_kind(brief: ContentBrief | None) -> ChildKind | None:
    """An AI child of a Clip: a character scene, or a «parte con IA» (a `CLIP` with
    `media.part`). An avatar block (or anything else) is not one: None. Pure."""
    if brief is None:
        return None
    if brief.kind is ContentKind.CHARACTER_SCENE:
        return "scene"
    if brief.kind is ContentKind.CLIP and brief.media.part is not None:
        return "ai_part"
    return None


@dataclass(frozen=True)
class ClipChild:
    """One AI child of a Clip as approving reads it: its draft and what it is."""

    record: Any  # service.DraftRecord
    kind: ChildKind
    brief: ContentBrief

    @property
    def id(self) -> UUID:
        return self.record.id  # type: ignore[no-any-return]


# -- a child's final -----------------------------------------------------------------------


def child_final_state(
    params: Mapping[str, Any] | None, now: float | None = None
) -> ChildFinalState:
    """Where one draft video of an approved child is: its 1080p kept (an AI part's
    `part_final` with its file, a scene's final in place); `expired` — its vendor draft
    expired, or its final's deadline passed, so no final can be made from it any more;
    `failed` or never ordered — the owner's «Intentar de nuevo» (`final_retryable`); or
    on its way. Pure."""
    block = draft_state(params) or {}
    status = block.get("status")
    if status == _PART_FINAL and block.get("part_final_key"):
        return "kept"
    if status in (DRAFT_FINAL_READY, DRAFT_FINAL) and block.get("final_object_key"):
        return "kept"
    if block.get("error") in (DRAFT_EXPIRED_TEXT, FINAL_EXPIRED_TEXT):
        return "expired"
    if final_retryable(block, now, approved=True):
        return "expired" if draft_expired(block, now) else "failed"
    return "waiting"


def child_final_key(params: Mapping[str, Any] | None, object_key: str | None) -> str | None:
    """The file of a kept final: an AI part's 1080p (`part_final_key`, its row keeps the
    preview), a scene's final (its row's file, replaced in place). Pure."""
    block = draft_state(params) or {}
    if block.get("status") == _PART_FINAL:
        key = block.get("part_final_key")
        return str(key) if key else None
    return object_key


def _final_seconds(params: Mapping[str, Any] | None) -> float | None:
    block = draft_state(params) or {}
    raw = block.get("raw_final")
    seconds = raw.get("duration_seconds") if isinstance(raw, Mapping) else None
    if isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds > 0:
        return float(seconds)
    return None


@dataclass(frozen=True)
class ChildFinal:
    """One child's kept final as the assembly with the finals plays it."""

    kind: ChildKind
    draft_id: UUID
    slot: int | None
    revision: int
    asset_id: UUID
    preview_key: str
    final_key: str
    seconds: float | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    provider: str | None = None
    model_id: str | None = None

    def provenance(self) -> dict[str, Any]:
        """What the Clip's final records of this child (§12.7, §13.4): its draft,
        revision, asset, both files, vendor, model, prompt and its final's task and cost."""
        block = draft_state(self.params) or {}
        found = block.get("raw_final")
        raw: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
        scene = self.params.get("character_scene")
        own: Mapping[str, Any] = scene if isinstance(scene, Mapping) else {}
        return {
            "kind": self.kind,
            "slot": self.slot,
            "draft_id": str(self.draft_id),
            "revision": self.revision,
            "asset_id": str(self.asset_id),
            "preview_object_key": self.preview_key,
            "final_object_key": self.final_key,
            "provider": self.provider or raw.get("provider") or own.get("provider"),
            "model_id": (
                self.model_id or raw.get("model_id") or block.get("model") or own.get("model_id")
            ),
            "prompt_version": self.params.get("prompt_version") or own.get("prompt_version"),
            "draft_task_id": block.get("draft_task_id") or self.params.get("task_id"),
            "final_task_id": block.get("final_task_id"),
            "final_cost_usd": block.get("final_cost_usd"),
            "final_resolution": block.get("final_resolution") or self.params.get("resolution"),
        }


def preview_key_of(asset: Any) -> str | None:
    """The 480p file the Clip's preview played for this child's video: an AI part's row
    keeps it; a scene's final replaced its row's file, so it is the block's record."""
    block = draft_state(asset.params) or {}
    if block.get("status") in (DRAFT_FINAL_READY, DRAFT_FINAL):
        kept = block.get("draft_object_key")
        return str(kept) if kept else None
    return str(asset.object_key) if asset.object_key else None


def final_brief(brief: ContentBrief, finals: Mapping[str, ChildFinal]) -> ContentBrief:
    """The approved Clip's recipe with each stretch that played a child's 480p file
    (`finals`: that file → its final) playing the 1080p instead — the same cut, speed and
    join; a final a hair shorter than the cut ends where the file ends. The scenes are
    windows laid from their rows, which already read their finals. Pure."""
    media = brief.media
    segments = []
    changed = False
    for segment in media.segments:
        final = finals.get(segment.key) if segment.kind == "video" else None
        if final is None:
            segments.append(segment)
            continue
        end = segment.end_s
        if final.seconds is not None and final.seconds < end:
            end = round(final.seconds, 3)
        start = min(segment.start_s, max(0.0, end - 0.1))
        segments.append(
            segment.model_copy(update={"key": final.final_key, "start_s": start, "end_s": end})
        )
        changed = True
    if not changed:
        return brief
    return brief.model_copy(
        update={"media": media.model_copy(update={"segments": tuple(segments)})}
    )


def expired_children(videos: Mapping[UUID, Sequence[Any]]) -> tuple[UUID, ...]:
    """The children with a draft video whose vendor draft expired (its 1080p can no
    longer be made from it): approving them is refused before anything is written."""
    return tuple(
        child
        for child, assets in videos.items()
        if any(draft_expired(draft_state(a.params) or {}) for a in assets)
    )


# -- what the screen reads -----------------------------------------------------------------


@dataclass(frozen=True)
class ClipFinalView:
    """The approved Clip's final as the screen shows it (PR 8, m-25112921): `waiting`,
    `failed` (a child's final or the assembly — «Intentar de nuevo»), `expired` (a child's
    final can no longer be made: no retry), or `ready` (the owner reviews it before
    scheduling). `failed_children`: the drafts whose final failed or expired."""

    state: Literal["waiting", "failed", "expired", "ready"]
    owner_text: str
    failed_children: tuple[UUID, ...] = ()
    can_retry: bool = False


def final_view(
    clip_block: Mapping[str, Any] | None,
    children: Mapping[UUID, Sequence[Mapping[str, Any] | None]],
    now: float | None = None,
) -> ClipFinalView | None:
    """`ClipFinalView` from the Clip's video block and each child's draft video params —
    None when the Clip has no final of this path. Pure."""
    block = dict(clip_block or {})
    if block.get("finish") != FINISH_CLIP_FINAL:
        return None
    if block.get("status") in (DRAFT_FINAL_READY, DRAFT_FINAL):
        return ClipFinalView("ready", READY_TEXT)
    states = {
        child: [(p, child_final_state(p, now)) for p in params]
        for child, params in children.items()
    }
    expired = tuple(c for c, found in states.items() if any(st == "expired" for _, st in found))
    unsettled = any(
        st == "expired"
        and (draft_state(p) or {}).get("error") not in (DRAFT_EXPIRED_TEXT, FINAL_EXPIRED_TEXT)
        # a final that failed gave its seconds back already (D9)
        and (draft_state(p) or {}).get("status") != DRAFT_FAILED
        for c in expired
        for p, st in states[c]
    )
    if unsettled:
        # not marked nor given back yet (`_retry_clip_final` does both): the owner's tap
        # settles it — never «te devolvimos» before it happened
        return ClipFinalView("expired", CHILD_EXPIRED_UNSETTLED_TEXT, expired, can_retry=True)
    if expired:
        return ClipFinalView("expired", CHILD_EXPIRED_TEXT, expired)
    failed = tuple(c for c, found in states.items() if any(st == "failed" for _, st in found))
    if failed:
        # «Te devolvimos sus segundos» only when a final really failed (D9 gave them
        # back); one never ordered, or left half-made, gave nothing back
        given_back = any(
            (draft_state(p) or {}).get("status") == DRAFT_FAILED
            for c in failed
            for p, st in states[c]
            if st == "failed"
        )
        words = CHILD_FINAL_FAILED_TEXT if given_back else CHILD_FINAL_STUCK_TEXT
        return ClipFinalView("failed", words, failed, can_retry=True)
    if block.get("status") == CLIP_FINAL_FAILED:
        return ClipFinalView("failed", CLIP_FINAL_FAILED_TEXT, can_retry=True)
    return ClipFinalView("waiting", WAITING_TEXT)


# -- the store -----------------------------------------------------------------------------


class ClipFinalStore(Protocol):
    def open(self, *, tenant_id: UUID, clip_id: UUID) -> None:
        """Open (or dirty) the Clip's `clip_final` run at its revision."""
        ...

    def save(
        self,
        *,
        tenant_id: UUID,
        clip_id: UUID,
        asset_id: UUID,
        revision: int,
        write: Any,
    ) -> bool:
        """The Clip's video row takes the final IN PLACE — only while the Clip is still
        approved at `revision` and the row's block still waits for it. False otherwise."""
        ...

    def fail(self, *, tenant_id: UUID, clip_id: UUID, asset_id: UUID, error: str) -> bool:
        """Mark the pending block `clip_final_failed` with why; the preview stays."""
        ...


def open_clip_final(session: Any, clip_id: UUID) -> bool:
    """Open (or dirty) the `clip_final` run of an approved top-level Clip, at its revision,
    in the caller's transaction. False (nothing written) for anything else. Idempotent."""
    from sqlalchemy import text  # noqa: PLC0415

    done = session.execute(
        text("""
        INSERT INTO creative_pipeline_runs AS r
            (tenant_id, draft_id, revision, phase, pipeline_version)
        SELECT p.tenant_id, p.id, p.revision, :phase, p.pipeline_version
        FROM content_drafts p JOIN content_briefs b ON b.id = p.brief_id AND b.kind = 'clip'
        WHERE p.id = :c AND p.parent_draft_id IS NULL AND p.status = 'approved'
        ON CONFLICT (tenant_id, draft_id, revision, phase)
        DO UPDATE SET dirty_version = r.dirty_version + 1
        RETURNING r.draft_id
        """),
        {"c": clip_id, "phase": CLIP_FINAL_PHASE},
    ).first()
    return done is not None


def clip_parent_of(session: Any, draft_id: UUID) -> UUID | None:
    """The top-level Clip `draft_id` is a child of, or None (no parent, or another kind:
    a video by parts joins its own finals)."""
    from sqlalchemy import text  # noqa: PLC0415

    return session.execute(  # type: ignore[no-any-return]
        text("""
        SELECT p.id FROM content_drafts d
        JOIN content_drafts p ON p.tenant_id = d.tenant_id AND p.id = d.parent_draft_id
            AND p.parent_draft_id IS NULL
        JOIN content_briefs b ON b.id = p.brief_id AND b.kind = 'clip'
        WHERE d.id = :d
        """),
        {"d": draft_id},
    ).scalar()


class PostgresClipFinalStore:
    """Every write through the tenant's unit of work (RLS), fenced by the run's lease."""

    def open(self, *, tenant_id: UUID, clip_id: UUID) -> None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            open_clip_final(session, clip_id)

    def _locked_block(self, session: Any, clip_id: UUID, asset_id: UUID) -> Any:
        from sqlalchemy import text  # noqa: PLC0415

        from qualify_api.creative.pipeline import PipelineStore, current_preparation  # noqa: PLC0415

        run = current_preparation()
        if run is not None:
            PipelineStore().fence(session, run)  # a lost lease never writes
        clip = session.execute(
            text("""
            SELECT status, revision, active_version_id FROM content_drafts
            WHERE id = :c AND parent_draft_id IS NULL FOR UPDATE
        """),
            {"c": clip_id},
        ).first()
        asset = session.execute(
            text("""
            SELECT params->'draft' AS block, version_id FROM image_assets
            WHERE id = :a AND draft_id = :c FOR UPDATE
        """),
            {"a": asset_id, "c": clip_id},
        ).first()
        return clip, asset

    def save(
        self,
        *,
        tenant_id: UUID,
        clip_id: UUID,
        asset_id: UUID,
        revision: int,
        write: Any,
    ) -> bool:
        from qualify_shared.db.session import tenant_unit_of_work  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_unit_of_work(tenant_id) as session:
            clip, asset = self._locked_block(session, clip_id, asset_id)
            block = dict(asset.block or {}) if asset is not None else {}
            if (
                clip is None
                or asset is None
                or clip.status != "approved"
                or clip.revision != revision
                or asset.version_id != clip.active_version_id
                or block.get("finish") != FINISH_CLIP_FINAL
                or block.get("status") != CLIP_FINAL_PENDING
                or block.get("approved_revision") != revision
            ):
                logger.info("clip %s moved on before its final was saved", clip_id)
                return False
            session.execute(
                text("""
                UPDATE image_assets SET media_url = :url, object_key = :key, content_type = :ct,
                    width = :w, height = :h, aspect_ratio = :ratio, model_id = :model,
                    provider = :provider,
                    params = CAST(:params AS jsonb), updated_at = now()
                WHERE id = :id
            """),
                {
                    "id": asset_id,
                    "url": write.media_url,
                    "key": write.object_key,
                    "ct": write.content_type,
                    "w": write.width,
                    "h": write.height,
                    "ratio": write.aspect_ratio,
                    "model": write.model_id,
                    "provider": write.provider,
                    "params": json.dumps(write.params),
                },
            )
            session.execute(
                text("UPDATE content_drafts SET preview_key = :preview WHERE id = :c"),
                {"c": clip_id, "preview": write.params.get("thumbnail_key") or write.media_url},
            )
        return True

    def fail(self, *, tenant_id: UUID, clip_id: UUID, asset_id: UUID, error: str) -> bool:
        from qualify_shared.db.session import tenant_unit_of_work  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_unit_of_work(tenant_id) as session:
            clip, asset = self._locked_block(session, clip_id, asset_id)
            block = dict(asset.block or {}) if asset is not None else {}
            if (
                clip is None
                or clip.status != "approved"
                or block.get("finish") != FINISH_CLIP_FINAL
                or block.get("status") != CLIP_FINAL_PENDING
            ):
                return False
            session.execute(
                text("""
                UPDATE image_assets SET params = jsonb_set(
                        jsonb_set(params, '{draft,status}', to_jsonb(CAST(:failed AS text))),
                        '{draft,error}', to_jsonb(CAST(:error AS text))),
                    updated_at = now()
                WHERE id = :a
            """),
                {"a": asset_id, "failed": CLIP_FINAL_FAILED, "error": error},
            )
        return True


def final_write(
    write: Any,
    *,
    block: Mapping[str, Any],
    preview: Any,
    revision: int,
    digest: str | None,
    finals: Sequence[ChildFinal],
) -> Any:
    """The assembly's `MediaWrite` as it goes in place of the preview: its own params, the
    pending block turned `final_ready` (the owner confirms it before it is scheduled, as
    any final), the preview's file and local record kept as provenance, and each child's
    final (`clip_final`). Pure."""
    from dataclasses import replace  # noqa: PLC0415

    params = dict(write.params or {})
    preview_params = dict(preview.params or {})
    params["clip_final"] = {
        "version": CLIP_FINAL_VERSION,
        "revision": revision,
        "preview_object_key": preview.object_key,
        "preview_local": preview_params.get("local"),
        "children": [final.provenance() for final in finals],
        "cost_usd": "0",
    }
    params["draft"] = {
        **dict(block),
        "finish": FINISH_CLIP_FINAL,
        "status": DRAFT_FINAL_READY,
        "final_object_key": write.object_key,
        "final_sha256": digest,
        "final_revision": revision,
        "preview_object_key": preview.object_key,
        "error": None,
        "confirmed_by": None,
        "confirmed_at": None,
        "confirmed_sha256": None,
        "confirmed_object_key": None,
        "confirmed_revision": None,
    }
    return replace(write, params=params)


def failed_block(block: Mapping[str, Any] | None) -> bool:
    """The Clip's final assembly failed (the owner may ask again)."""
    block = dict(block or {})
    return block.get("finish") == FINISH_CLIP_FINAL and block.get("status") in (
        CLIP_FINAL_FAILED,
        DRAFT_FAILED,
    )


__all__ = [
    "CHILDREN_CHANGED",
    "CHILDREN_CHANGED_TEXT",
    "CHILDREN_NOT_READY",
    "CHILDREN_NOT_READY_TEXT",
    "CHILD_EXPIRED_TEXT",
    "CHILD_EXPIRED_UNSETTLED_TEXT",
    "CHILD_FINAL_FAILED_TEXT",
    "CHILD_FINAL_STUCK_TEXT",
    "CLIP_FINAL_FAILED",
    "CLIP_FINAL_FAILED_TEXT",
    "CLIP_FINAL_PENDING",
    "CLIP_FINAL_PHASE",
    "CLIP_FINAL_VERSION",
    "FINISH_CLIP_FINAL",
    "READY_TEXT",
    "WAITING_TEXT",
    "ChildFinal",
    "ClipChild",
    "ClipFinalStore",
    "ClipFinalView",
    "PostgresClipFinalStore",
    "child_final_key",
    "child_final_state",
    "child_kind",
    "clip_parent_of",
    "expired_children",
    "failed_block",
    "final_brief",
    "final_view",
    "final_write",
    "open_clip_final",
    "preview_key_of",
]
