"""The owner's ask for the parts of a video by parts, kept on the parent (m-24921081, UI-6).

«Revisa y crea» creates the PARENT of a video by parts with what the owner asked of its
parts in its brief — `media.parts_request` (`qualify_creative.schemas.PartsRequest`):
`scope="all"` («Crear las n partes») or `scope="first"` («Probar solo la parte 1»: 1
vista previa, the others stay «Sin crear»). The parent's text is made by the creative
worker (`PipelinePreparation`, phase `generation`); right after it, OUT OF THE REQUEST
PATH and with no screen open, the worker calls `PartsRequests.after_generation`, which
creates the parts asked for (`PartsService.create_parts`) and writes the outcome back on
the parent's brief:

- made (or already made): `refused` None;
- refused: `refused` = a `PartsRefusal` code (`refusal_of`), with `part` (the part it is
  about) and `missing` (vistas previas short). Nothing was created nor charged — the
  `create_parts` all-or-nothing guarantee.

The hook acts on the parent's FIRST generation only (no attempt recorded yet): a
regenerated text never creates nor charges parts on its own — every later creation is
the owner's tap. `create_parts` is idempotent besides (the parts that exist are returned,
never charged twice). A parent whose text is still being made is left alone; one whose
first text failed reads `text_missing`, and the owner asks again from the screen. A hook
that raises is logged and never fails nor loops the worker's run. The stored outcome
only moves forward: each attempt takes a number from the database before it creates
anything, and its outcome is written only while no later attempt was started (one
counter, the database's clock — never two processes' clocks compared). A hook that breaks
before writing keeps `refused="error"` (`record_failure`).

Later asks are the owner's own taps (`PartsRequests.request_parts`): «Crear las que
faltan» (every part not created) or «Crear esta parte» (one), all or nothing over the
parts asked for. They record their outcome the same way and raise the refusal for the
screen that asked. The result screen reads the stored ask through
`part_progress.read_part_progress` (`PartProgress.request`); it chooses its words from
the code, never from `str(exc)`.

`parts_preview_use` answers, before the parent exists, «¿me alcanzan las vistas previas
para n partes?»: `final_video.PreviewUse` (uses, left, quota, unlimited, renews_on), the
same shape «Tu video completo» reads for «Crear la parte N otra vez».
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol
from uuid import UUID

from qualify_creative.creations import CreationNotOffered, load_weights, weight_for_request
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import (
    PART_GENERATION_MIN_SECONDS,
    ContentBrief,
    PartsRefusal,
    PartsRequest,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.final_video import PreviewUse
from qualify_api.creative.fsm import DRAFTING
from qualify_api.creative.parts import (
    ExtendOutOfOrder,
    ExtendTooShort,
    ParentTextMissing,
    PartChangeRefused,
    PartNeedsDescription,
    PartNeedsPrevious,
    PartRemoved,
    PartsExtendUnavailable,
    PartsOverBudget,
    PartsPlanBusy,
    PartsService,
    PartsSourceInvalid,
    PartsUnavailable,
    removed_part_indexes,
)
from qualify_api.creative.service import (
    BrandNotReady,
    ContentService,
    RouteBlockedByPolicy,
    UnknownDraft,
)
from qualify_api.referentes.reel_analysis_types import ReelAnalysis

logger = logging.getLogger(__name__)

#: «Probar solo la parte 1».
FIRST_PART: tuple[int, ...] = (1,)


def refusal_of(exc: BaseException) -> tuple[PartsRefusal, int | None, int] | None:
    """The stored code of a refusal of `create_parts`, the part it is about and the
    vistas previas short — or None when `exc` is not a refusal (a bug, a database
    error: the caller decides). Pure."""
    if isinstance(exc, PartsExtendUnavailable):
        return "extend_unavailable", None, 0
    if isinstance(exc, PartsSourceInvalid):
        return "extend_invalid", None, 0
    if isinstance(exc, PartsUnavailable):
        return "unavailable", None, 0
    if isinstance(exc, ParentTextMissing):
        return "text_missing", None, 0
    if isinstance(exc, PartNeedsDescription):
        return "needs_description", exc.index, 0
    if isinstance(exc, PartRemoved):
        return "removed", exc.index, 0
    if isinstance(exc, PartNeedsPrevious):
        return "needs_previous", exc.index, 0
    if isinstance(exc, ExtendTooShort | ExtendOutOfOrder):
        return "extend_invalid", None, 0
    if isinstance(exc, PartsOverBudget):
        return "over_budget", None, 0
    if isinstance(exc, NotEnoughCreations):
        return "not_enough_previews", None, exc.missing_previews or exc.missing
    if isinstance(exc, PartsPlanBusy):
        return "plan_busy", None, 0
    if isinstance(exc, PartChangeRefused):
        return "purged", None, 0
    if isinstance(exc, BrandNotReady | RouteBlockedByPolicy):
        return "brand_not_ready", None, 0
    return None


class PartsRequestStore(Protocol):
    """Where the ask lives: who asked (the parent's author), the attempts and their
    outcome. ONE clock and ONE counter, the store's own: an attempt takes its number
    (`begin`) before it creates anything, and its outcome (`record`) is written only
    while no later attempt was started — never by comparing two processes' clocks."""

    def requester(self, *, tenant_id: UUID, parent_id: UUID) -> UUID | None: ...

    def begin(self, *, tenant_id: UUID, parent_id: UUID) -> int | None: ...

    def record(
        self, *, tenant_id: UUID, parent_id: UUID, request: PartsRequest
    ) -> PartsRequest | None: ...

    def fail(self, *, tenant_id: UUID, parent_id: UUID, attempt: int) -> bool: ...


_PARENT_BRIEF = """
SELECT p.brief_id, b.kind, b.media ? 'parts_request' AS asked FROM content_drafts p
JOIN content_briefs b ON b.id = p.brief_id
WHERE p.id = :p AND p.parent_draft_id IS NULL FOR UPDATE OF p
"""
#: the stored attempt number (0 when none was started)
_ATTEMPT = "COALESCE(CAST(media->'parts_request'->>'attempt' AS integer), 0)"


class PostgresPartsRequestStore:
    """The ask on the parent's current brief (`content_briefs.media->'parts_request'`),
    written in place under the parent's row lock — the lock `save_parts_plan` and
    `create_parts` take — so neither of them rewrites the brief over it. The attempt
    number grows in the database and `attempted_at` is the database's
    `clock_timestamp()`. RLS: another business's parent is not found (nothing written)."""

    def requester(self, *, tenant_id: UUID, parent_id: UUID) -> UUID | None:
        with tenant_session(tenant_id) as session:
            return session.execute(
                text("""
                SELECT b.created_by FROM content_drafts p
                JOIN content_briefs b ON b.id = p.brief_id
                WHERE p.id = :p AND p.parent_draft_id IS NULL
                """),
                {"p": parent_id},
            ).scalar()

    def _brief(self, session: Any, parent_id: UUID) -> Any | None:
        row = session.execute(text(_PARENT_BRIEF), {"p": parent_id}).first()
        if row is None or row.kind != "shot_video":
            logger.warning("parent %s: no video by parts to keep its parts ask on", parent_id)
            return None
        return row

    def begin(self, *, tenant_id: UUID, parent_id: UUID) -> int | None:
        """Start an attempt: its number (the stored one + 1), or None (no such parent)."""
        with tenant_session(tenant_id) as session:
            row = self._brief(session, parent_id)
            if row is None:
                return None
            return session.execute(
                text(f"""
                UPDATE content_briefs SET media = jsonb_set(
                    media, '{{parts_request}}',
                    COALESCE(media->'parts_request', '{{}}'::jsonb)
                        || jsonb_build_object('attempt', {_ATTEMPT} + 1))
                WHERE id = :b
                RETURNING {_ATTEMPT}
                """),
                {"b": row.brief_id},
            ).scalar()

    def record(
        self, *, tenant_id: UUID, parent_id: UUID, request: PartsRequest
    ) -> PartsRequest | None:
        """Write the outcome of attempt `request.attempt`, stamped with the database's
        clock — only while it is still the last attempt started (a late, older outcome
        never overwrites a newer attempt's). The stored ask, or None when not written."""
        with tenant_session(tenant_id) as session:
            row = self._brief(session, parent_id)
            if row is None:
                return None
            stored = session.execute(
                text(f"""
                UPDATE content_briefs SET media = jsonb_set(
                    media, '{{parts_request}}',
                    CAST(:request AS jsonb)
                        || jsonb_build_object('attempted_at', clock_timestamp()))
                WHERE id = :b AND {_ATTEMPT} = :attempt
                RETURNING media->'parts_request'
                """),
                {
                    "b": row.brief_id,
                    "request": request.model_dump_json(exclude={"attempted_at"}),
                    "attempt": request.attempt,
                },
            ).scalar()
            if stored is None:
                logger.info("parent %s: a later parts attempt is kept", parent_id)
                return None
            return PartsRequest.model_validate(stored)

    def fail(self, *, tenant_id: UUID, parent_id: UUID, attempt: int) -> bool:
        """The hook broke before it could keep an outcome: `refused="error"`, so the
        screen never waits forever — only on a parent with an ask, and only while the
        stored attempt is still `attempt` (the one this hook took, or 0 when it took
        none): a good outcome already kept (a regenerated text whose hook did nothing,
        a later attempt) is never overwritten."""
        with tenant_session(tenant_id) as session:
            row = session.execute(text(_PARENT_BRIEF), {"p": parent_id}).first()
            if row is None or row.kind != "shot_video" or not row.asked:
                return False
            done = session.execute(
                text(f"""
                UPDATE content_briefs SET media = jsonb_set(
                    media, '{{parts_request}}',
                    media->'parts_request' || jsonb_build_object(
                        'attempt', GREATEST({_ATTEMPT}, 1), 'refused', 'error',
                        'part', NULL, 'missing', 0, 'attempted_at', clock_timestamp()))
                WHERE id = :b AND {_ATTEMPT} = :attempt
                """),
                {"b": row.brief_id, "attempt": attempt},
            )
            return bool(getattr(done, "rowcount", 0))


def _analysis_of(tenant_id: UUID, brief: ContentBrief) -> ReelAnalysis | None:
    """The reel analysis the plan was made from (its `extend` parts are checked against
    its cuts), or None for a plan without a reel."""
    found = next((p.analysis_id for p in brief.media.parts if p.analysis_id is not None), None)
    if found is None:
        return None
    from qualify_api.referentes.reel_analysis import get_analysis  # noqa: PLC0415

    return get_analysis(tenant_id, found)


class PartsRequests:
    """Creates the parts the owner asked for, and keeps the outcome on the parent."""

    def __init__(
        self,
        content: ContentService,
        *,
        parts: PartsService | None = None,
        store: PartsRequestStore | None = None,
        analysis_of: Callable[[UUID, ContentBrief], ReelAnalysis | None] = _analysis_of,
    ) -> None:
        self._content = content
        self._parts = parts or PartsService(content)
        self._store = store or PostgresPartsRequestStore()
        self._analysis_of = analysis_of
        #: the attempt each parent's hook took in this process (`record_failure`)
        self._begun: dict[tuple[UUID, UUID], int] = {}

    def _parent(self, tenant_id: UUID, parent_id: UUID) -> tuple[Any, ContentBrief] | None:
        repo = self._content.repository
        draft = repo.get_draft(tenant_id=tenant_id, draft_id=parent_id)
        if draft is None or draft.parent_draft_id is not None:
            return None
        brief = repo.get_brief(tenant_id=tenant_id, brief_id=draft.brief_id)
        if brief is None or not brief.kind.is_parts_parent:
            return None
        return draft, brief

    def after_generation(self, *, tenant_id: UUID, parent_id: UUID) -> PartsRequest | None:
        """The creative worker's hook, right after a draft's `generation` run: when the
        draft is a video by parts whose owner asked for its parts, create them (all, or
        the first) and keep the outcome. None (nothing done) for any other draft, a
        parent with no ask, or a text still being made. Never raises a refusal: it is
        stored, for the result screen.

        FIRST GENERATION ONLY (coordinator decision, m-24921081): once an attempt is
        started (`attempt` > 0), a regenerated text creates and charges nothing
        on its own — creating or charging parts without the owner's tap would break
        the house rule. Every later creation is the owner's (`request_parts`)."""
        self._begun.pop((tenant_id, parent_id), None)
        found = self._parent(tenant_id, parent_id)
        if found is None:
            return None
        draft, brief = found
        asked = brief.media.parts_request
        if asked is None or draft.status == DRAFTING or asked.attempt > 0:
            return None
        user_id = self._store.requester(tenant_id=tenant_id, parent_id=parent_id)
        if user_id is None:
            logger.warning("parent %s: its parts were asked for by nobody known", parent_id)
            return None
        indexes = FIRST_PART if asked.scope == "first" else None
        outcome, _, _ = self._attempt(tenant_id, parent_id, user_id, brief, asked, indexes)
        return outcome

    def record_failure(self, *, tenant_id: UUID, parent_id: UUID) -> bool:
        """The worker's hook raised before keeping an outcome (a database error):
        keep `refused="error"` on a parent with an ask, so its screen never shows
        «pending» forever. Only over the attempt this hook took — or, when it took
        none, a parent never attempted: a good outcome already kept is never
        overwritten. Raises what the store raises (the caller logs it)."""
        attempt = self._begun.pop((tenant_id, parent_id), 0)
        return self._store.fail(tenant_id=tenant_id, parent_id=parent_id, attempt=attempt)

    def request_parts(
        self,
        *,
        tenant_id: UUID,
        parent_id: UUID,
        user_id: UUID,
        part_indexes: Sequence[int] | None = None,
    ) -> list[UUID]:
        """The owner's tap: «Crear las que faltan» (`part_indexes` None: every part not
        created) or «Crear esta parte» (`(n,)`) — all or nothing over the parts asked
        for. Returns their ids in plan order. The outcome is kept on the parent as the
        worker's is, and a refusal is raised to the caller as `create_parts` raises it
        (`refusal_of` gives its code). `UnknownDraft`: not a video by parts of this
        business, or an index outside its plan."""
        found = self._parent(tenant_id, parent_id)
        if found is None:
            raise UnknownDraft(str(parent_id))
        _, brief = found
        asked = brief.media.parts_request or PartsRequest(scope="all")
        indexes = None if part_indexes is None else tuple(sorted(set(part_indexes)))
        _, error, ids = self._attempt(tenant_id, parent_id, user_id, brief, asked, indexes)
        if error is not None:
            raise error
        return ids

    def _attempted_parts(
        self,
        tenant_id: UUID,
        parent_id: UUID,
        brief: ContentBrief,
        indexes: Sequence[int] | None,
    ) -> tuple[int, ...]:
        """The parts an attempt asks for, always spelled out (m-24993031): the indexes
        given, or — «Crear las que faltan», scope `all` — every part of the plan the
        owner did not remove, as `create_parts` reads None (and the ids it returns).
        Never empty for a plan with parts: «all» and «the first» are kept alike."""
        if indexes is not None:
            return tuple(sorted(set(indexes)))
        removed = removed_part_indexes(
            self._content.repository, tenant_id=tenant_id, parent_id=parent_id
        )
        return tuple(
            index for index in range(1, len(brief.media.parts) + 1) if index not in removed
        )

    def _attempt(
        self,
        tenant_id: UUID,
        parent_id: UUID,
        user_id: UUID,
        brief: ContentBrief,
        asked: PartsRequest,
        indexes: Sequence[int] | None,
    ) -> tuple[PartsRequest | None, BaseException | None, list[UUID]]:
        """One `create_parts`, its outcome written on the parent. Returns the outcome
        stored (None when the parent is gone or a later attempt was started), the
        refusal, if any, and the parts' ids."""
        attempted = self._attempted_parts(tenant_id, parent_id, brief, indexes)
        attempt = self._store.begin(tenant_id=tenant_id, parent_id=parent_id)
        if attempt is None:
            raise UnknownDraft(str(parent_id))
        self._begun[(tenant_id, parent_id)] = attempt
        error: BaseException | None = None
        ids: list[UUID] = []
        refused: tuple[PartsRefusal, int | None, int] | None = None
        try:
            ids = self._parts.create_parts(
                tenant_id=tenant_id,
                parent_id=parent_id,
                user_id=user_id,
                analysis=self._analysis_of(tenant_id, brief),
                part_indexes=indexes,
            )
        except UnknownDraft:
            raise
        except Exception as exc:  # noqa: BLE001 — every refusal is kept for the screen
            error = exc
            refused = refusal_of(exc)
            if refused is None:
                logger.exception("parent %s: its parts could not be created", parent_id)
                refused = ("error", None, 0)
        outcome = asked.model_copy(
            update={
                "refused": None if refused is None else refused[0],
                "part": None if refused is None else refused[1],
                "missing": 0 if refused is None else refused[2],
                "attempted_parts": attempted,
                "attempted_at": None,
                "attempt": attempt,
            }
        )
        kept = self._store.record(tenant_id=tenant_id, parent_id=parent_id, request=outcome)
        # the outcome is kept: a later failure of this hook must not write «error» over it
        self._begun.pop((tenant_id, parent_id), None)
        return kept, error, ids


def parts_preview_use(
    content: ContentService, *, tenant_id: UUID, brand_id: UUID, parts: int
) -> PreviewUse | None:
    """«¿Me alcanzan las vistas previas para `parts` partes?», read only, before the
    parent exists: what creating them uses of the month's vistas previas (1 per part,
    at any length), how many are left (packs included), the month's quota and the day
    it renews (`PreviewUse.short` = they do not reach). None when no ledger is wired."""
    ledger = content.creations
    if ledger is None:
        return None
    balance = ledger.balance(tenant_id=tenant_id, brand_id=brand_id)
    try:
        one = weight_for_request(
            ContentKind.CLIP.value,
            duration_seconds=PART_GENERATION_MIN_SECONDS,
            weights=load_weights(),
        )
        uses = one.videos * max(parts, 0)
    except CreationNotOffered:
        uses = 0
    return PreviewUse(
        uses=uses,
        left=balance.previews_left,
        quota=balance.preview_quota,
        unlimited=balance.unlimited,
        renews_on=balance.renews_on,
    )


__all__ = [
    "FIRST_PART",
    "PartsRequestStore",
    "PartsRequests",
    "PostgresPartsRequestStore",
    "parts_preview_use",
    "refusal_of",
]
