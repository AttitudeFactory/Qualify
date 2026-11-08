"""«Promoción de la semana» (m-24945889, spec `docs/ux-whatsapp-enviar-imagen.md` §2.4):
the one piece a business keeps at hand to send from a chat in one tap.

- **One per business.** `whatsapp_weekly_promotions` (0140) has a UNIQUE brand: marking
  another piece replaces the row in ONE statement (`INSERT … ON CONFLICT (brand_id) DO
  UPDATE`), so the previous one is unmarked atomically — never two marks, never none in
  between.
- **No expiry** (founder decision): it stays until the owner marks another or unmarks it.
- **What may be marked:** an approved, staged or published piece of THAT business that
  the chat can send (a photo or a video piece — `attachments.PostgresAttachmentReads.
  piece`), not purged. «Sin aprobar» is not offered as the week's promotion.
- **Retention (ADR 39):** while marked, the piece is HELD like a scheduled one — its
  files are never purged (`creative.retention.read_facts`).
- **Assisted:** marking sends nothing; the chat sends the piece only on the owner's tap
  (`attachments.ChatAttachmentService.send_piece`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

#: The piece statuses that may be the week's promotion (approved for the networks).
PROMOTABLE_STATUSES: Final = frozenset({"approved", "staged", "published"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PromotionNotAllowed(ValueError):
    """The piece cannot be the week's promotion; `message` is the owner's Spanish text."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


NOT_FOUND_TEXT: Final = "Esa pieza ya no está disponible."
NOT_APPROVED_TEXT: Final = "Aprueba la pieza antes de usarla como promoción de la semana."


@dataclass(frozen=True)
class WeeklyPromotion:
    brand_id: UUID
    draft_id: UUID
    marked_at: datetime
    marked_by: UUID | None = None


class PromotionRepository(Protocol):
    """Tenant-scoped (Postgres: `tenant_session`, RLS)."""

    def get(self, *, tenant_id: UUID, brand_id: UUID) -> WeeklyPromotion | None: ...

    def mark(
        self, *, tenant_id: UUID, brand_id: UUID, draft_id: UUID, by: UUID | None, at: datetime
    ) -> WeeklyPromotion:
        """Upsert the business's one row (the previous mark goes in the same statement)."""
        ...

    def unmark(self, *, tenant_id: UUID, brand_id: UUID) -> bool: ...


class PieceReader(Protocol):
    """`attachments.AttachmentReads.piece`'s shape."""

    def piece(self, tenant_id: UUID, draft_id: UUID) -> Any: ...


class WeeklyPromotionService:
    def __init__(
        self,
        repo: PromotionRepository,
        pieces: PieceReader,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repo = repo
        self._pieces = pieces
        self._clock = clock

    def get_weekly_promotion(self, *, tenant_id: UUID, brand_id: UUID) -> WeeklyPromotion | None:
        return self._repo.get(tenant_id=tenant_id, brand_id=brand_id)

    def mark_weekly_promotion(
        self, *, tenant_id: UUID, brand_id: UUID, draft_id: UUID, user_id: UUID | None
    ) -> WeeklyPromotion:
        """Make `draft_id` the business's promotion, unmarking the previous one."""
        piece = self._pieces.piece(tenant_id, draft_id)
        if piece is None or piece.brand_id != brand_id:
            raise PromotionNotAllowed(NOT_FOUND_TEXT)
        if piece.status not in PROMOTABLE_STATUSES:
            raise PromotionNotAllowed(NOT_APPROVED_TEXT)
        return self._repo.mark(
            tenant_id=tenant_id, brand_id=brand_id, draft_id=draft_id, by=user_id, at=self._clock()
        )

    def unmark_weekly_promotion(self, *, tenant_id: UUID, brand_id: UUID) -> bool:
        return self._repo.unmark(tenant_id=tenant_id, brand_id=brand_id)


class MemoryPromotionRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, tuple[UUID, WeeklyPromotion]] = {}  # brand → (tenant, row)

    def get(self, *, tenant_id: UUID, brand_id: UUID) -> WeeklyPromotion | None:
        found = self.rows.get(brand_id)
        return found[1] if found and found[0] == tenant_id else None

    def mark(
        self, *, tenant_id: UUID, brand_id: UUID, draft_id: UUID, by: UUID | None, at: datetime
    ) -> WeeklyPromotion:
        row = WeeklyPromotion(brand_id=brand_id, draft_id=draft_id, marked_at=at, marked_by=by)
        self.rows[brand_id] = (tenant_id, row)
        return row

    def unmark(self, *, tenant_id: UUID, brand_id: UUID) -> bool:
        found = self.rows.get(brand_id)
        if found is None or found[0] != tenant_id:
            return False
        del self.rows[brand_id]
        return True


_MARK = """
INSERT INTO whatsapp_weekly_promotions (tenant_id, brand_id, draft_id, marked_at, marked_by)
VALUES (:tenant_id, :brand_id, :draft_id, :at, :by)
ON CONFLICT (brand_id) DO UPDATE
   SET draft_id = EXCLUDED.draft_id,
       marked_at = EXCLUDED.marked_at,
       marked_by = EXCLUDED.marked_by
RETURNING brand_id, draft_id, marked_at, marked_by
"""


class PostgresPromotionRepository:
    def get(self, *, tenant_id: UUID, brand_id: UUID) -> WeeklyPromotion | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.whatsapp.models import WhatsAppWeeklyPromotion as T  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                select(T.brand_id, T.draft_id, T.marked_at, T.marked_by).where(
                    T.brand_id == brand_id
                )
            ).first()
        return WeeklyPromotion(*row) if row is not None else None

    def mark(
        self, *, tenant_id: UUID, brand_id: UUID, draft_id: UUID, by: UUID | None, at: datetime
    ) -> WeeklyPromotion:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(_MARK),
                {
                    "tenant_id": tenant_id,
                    "brand_id": brand_id,
                    "draft_id": draft_id,
                    "at": at,
                    "by": by,
                },
            ).one()
        return WeeklyPromotion(*row)

    def unmark(self, *, tenant_id: UUID, brand_id: UUID) -> bool:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import delete  # noqa: PLC0415

        from qualify_api.whatsapp.models import WhatsAppWeeklyPromotion as T  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            result = session.execute(delete(T).where(T.brand_id == brand_id))
        return bool(result.rowcount)


def production_weekly_promotion_service() -> WeeklyPromotionService:
    from qualify_api.whatsapp.attachments import PostgresAttachmentReads  # noqa: PLC0415

    return WeeklyPromotionService(PostgresPromotionRepository(), PostgresAttachmentReads())


__all__ = [
    "PROMOTABLE_STATUSES",
    "MemoryPromotionRepository",
    "PostgresPromotionRepository",
    "PromotionNotAllowed",
    "WeeklyPromotion",
    "WeeklyPromotionService",
    "production_weekly_promotion_service",
]
