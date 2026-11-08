"""Backend access for «Stickers y videos de tu marca» (m-24976895): a thin gateway over
the backend's `qualify_api.whatsapp.seasonal.SeasonalMediaService` (m-24976891; tests
fake the whole gateway). Every read and write goes through the service's `tenant_session`; previews
through `seasonal_media.issue_seasonal_view_path` (this business only). Blocking: callers
run it off the event loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AiQuote:
    """The IA batch's price before creating (`quote_batch`), or why it is not offered."""

    per_video_usd: Decimal | None = None
    total_usd: Decimal | None = None
    videos: int = 0
    unavailable: str = ""


@dataclass(frozen=True)
class AiPhoto:
    id: str
    title: str
    src: str = ""


@dataclass(frozen=True)
class SeasonRow:
    key: str
    label: str
    archived: bool = False


class SeasonalGateway(Protocol):
    def brand(self, tenant_id: UUID) -> UUID | None: ...

    def country(self, tenant_id: UUID) -> str: ...

    def seasons(self, tenant_id: UUID, brand_id: UUID) -> list[SeasonRow]: ...

    def season_items(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> list[Any]: ...

    def plan(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        season_key: str,
        season_label: str,
        mode: str,
        user_id: UUID | None,
        accepted_total_usd: Decimal | None = None,
    ) -> Any: ...

    def approve(
        self, tenant_id: UUID, brand_id: UUID, media_ids: list[UUID], user_id: UUID | None
    ) -> Any: ...

    def another(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        media_id: UUID,
        user_id: UUID | None,
        accepted_cost_usd: Decimal | None = None,
    ) -> Any: ...

    def batch_counts(self, mode: str) -> tuple[int, int]: ...

    def archive(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any: ...

    def restore(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any: ...

    def approved_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[Any]: ...

    def ai_quote(self, tenant_id: UUID, brand_id: UUID) -> AiQuote: ...

    def ai_photos(self, tenant_id: UUID, brand_id: UUID) -> list[AiPhoto]: ...

    def month_ai_total(self, tenant_id: UUID, brand_id: UUID) -> Decimal: ...

    def reason_texts(self) -> dict[str, str]: ...

    def preview_src(self, tenant_id: UUID, brand_id: UUID, row: Any) -> str: ...

    def acting_user(self, tenant_id: UUID) -> UUID | None: ...

    def calendar(self, tenant_id: UUID, n: int = 3) -> tuple[list[Any], Any]: ...


class ProductionSeasonalGateway:
    """The real thing. Method names follow the contract the coordinator relayed
    (`plan_batch`, `list_seasons`, `list_season`, `approve`, `reject`, `archive`,
    `restore`, `list_approved_for_chat`); the import path is confirmed when the backend
    branch is merged."""

    def __init__(self, service: Any = None) -> None:
        self._service = service

    @property
    def service(self) -> Any:
        if self._service is None:
            from qualify_api.whatsapp.seasonal import (  # noqa: PLC0415
                production_seasonal_service,
            )

            self._service = production_seasonal_service()
        return self._service

    def brand(self, tenant_id: UUID) -> UUID | None:
        from .creators_provider import session_brand  # noqa: PLC0415

        return session_brand(tenant_id)

    def country(self, tenant_id: UUID) -> str:
        from .settings_provider import read_locale  # noqa: PLC0415

        found = read_locale(tenant_id)
        return found.country if found is not None else ""

    def seasons(self, tenant_id: UUID, brand_id: UUID) -> list[SeasonRow]:
        rows = self.service.list_seasons(tenant_id=tenant_id, brand_id=brand_id)
        return [
            SeasonRow(key=r.season_key, label=r.season_label, archived=r.archived) for r in rows
        ]

    def season_items(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> list[Any]:
        return list(
            self.service.list_season(tenant_id=tenant_id, brand_id=brand_id, season_key=season_key)
        )

    def plan(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        season_key: str,
        season_label: str,
        mode: str,
        user_id: UUID | None,
        accepted_total_usd: Decimal | None = None,
    ) -> Any:
        """«Con IA» needs the TOTAL the owner confirmed from `ai_quote`
        (`CostNotConfirmed` otherwise: the price changed or nobody confirmed it)."""
        return self.service.plan_batch(
            tenant_id=tenant_id,
            brand_id=brand_id,
            season_key=season_key,
            season_label=season_label,
            mode=mode,
            user_id=user_id,
            accepted_total_usd=accepted_total_usd,
        )

    def approve(
        self, tenant_id: UUID, brand_id: UUID, media_ids: list[UUID], user_id: UUID | None
    ) -> Any:
        return self.service.approve(
            tenant_id=tenant_id, brand_id=brand_id, media_ids=media_ids, user_id=user_id
        )

    def another(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        media_id: UUID,
        user_id: UUID | None,
        accepted_cost_usd: Decimal | None = None,
    ) -> Any:
        """«Pedir otro»: the same slot is made again (`request_another`, from ready, rejected
        or failed; at most three times — `AttemptsExhausted` says so in Spanish). A video
        made with IA needs the per-video cost the owner confirmed."""
        return self.service.request_another(
            tenant_id=tenant_id,
            brand_id=brand_id,
            media_id=media_id,
            user_id=user_id,
            accepted_cost_usd=accepted_cost_usd,
        )

    def batch_counts(self, mode: str) -> tuple[int, int]:
        """(stickers, videos) of the standard batch for `mode` — the backend's
        `STANDARD_BATCH`, never a number written here."""
        from qualify_api.whatsapp.seasonal import (  # noqa: PLC0415
            KIND_STICKER,
            STANDARD_BATCH,
        )

        slots = STANDARD_BATCH.get(mode, ())
        stickers = sum(1 for slot in slots if slot.kind == KIND_STICKER)
        return stickers, len(slots) - stickers

    def archive(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any:
        return self.service.archive(tenant_id=tenant_id, brand_id=brand_id, season_key=season_key)

    def restore(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any:
        return self.service.restore(tenant_id=tenant_id, brand_id=brand_id, season_key=season_key)

    def approved_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[Any]:
        return list(self.service.list_approved_for_chat(tenant_id=tenant_id, brand_id=brand_id))

    def ai_quote(self, tenant_id: UUID, brand_id: UUID) -> AiQuote:
        """`quote_batch(mode="ai")`: «unos US$X por video» and the total, from the
        CURRENT pricing — never a price written here. `ModeNotAvailable` (IA off by config,
        or `NoPhotoToAnimate`) comes back as `unavailable` in the service's words."""
        from qualify_api.whatsapp.seasonal import ModeNotAvailable  # noqa: PLC0415

        try:
            quote = self.service.quote_batch(tenant_id, brand_id, "ai")
        except ModeNotAvailable as exc:
            return AiQuote(unavailable=exc.message)
        return AiQuote(
            per_video_usd=quote.per_ai_video_usd,
            total_usd=quote.total_usd,
            videos=quote.ai_videos,
        )

    def ai_photos(self, tenant_id: UUID, brand_id: UUID) -> list[AiPhoto]:
        """What the IA batch will animate — the SAME source read `plan_batch` uses
        (`PostgresSourceReads.approved_photo_pieces`, newest first, as many as the «ai»
        slots take), with each piece's title and a signed thumbnail."""
        from qualify_api.whatsapp.attachments import PostgresAttachmentReads  # noqa: PLC0415
        from qualify_api.whatsapp.seasonal import (  # noqa: PLC0415
            STANDARD_BATCH,
            PostgresSourceReads,
        )

        from .r2_media import issue_view_path  # noqa: PLC0415

        wanted = sum(slot.pieces for slot in STANDARD_BATCH.get("ai", ()))
        ids = PostgresSourceReads().approved_photo_pieces(tenant_id, brand_id, max(wanted, 1))
        rows = {r.id: r for r in PostgresAttachmentReads().pieces(tenant_id, brand_id)}
        photos = []
        for piece_id in ids:
            row = rows.get(piece_id)
            title = (row.title if row is not None else "") or "Pieza sin título"
            key = row.image_key if row is not None else ""
            try:
                src = issue_view_path(tenant_id, key, "image") if key else ""
            except Exception as exc:  # noqa: BLE001 — the name still shows
                logger.warning("seasonal ai thumb not issued: %s", type(exc).__name__)
                src = ""
            photos.append(AiPhoto(id=str(piece_id), title=title, src=src))
        return photos

    def month_ai_total(self, tenant_id: UUID, brand_id: UUID) -> Decimal:
        """What the business spent on IA video this calendar month (UTC)."""
        from datetime import UTC, datetime  # noqa: PLC0415

        from qualify_api.creative.seasonal_ai import seasonal_ai_month_total  # noqa: PLC0415

        now = datetime.now(UTC)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return seasonal_ai_month_total(tenant_id, brand_id, start)

    def reason_texts(self) -> dict[str, str]:
        """The worker's refusal words (`budget_cap` → «Esta pieza superaría tu tope de
        gasto.»)."""
        from qualify_api.creative.seasonal_ai import REASON_TEXT  # noqa: PLC0415

        return dict(REASON_TEXT)

    def preview_src(self, tenant_id: UUID, brand_id: UUID, row: Any) -> str:
        """`/r2seasonal/<token>` for one medium of THIS business ("" when its key is not
        exactly one of this business's seasonal keys) — `seasonal_media`, never the
        generic `r2_media` signer."""
        from .seasonal_media import issue_seasonal_view_path  # noqa: PLC0415

        try:
            return issue_seasonal_view_path(tenant_id, brand_id, getattr(row, "object_key", ""))
        except Exception as exc:  # noqa: BLE001 — a preview is not worth the list
            logger.warning("seasonal preview not issued: %s", type(exc).__name__)
            return ""

    def calendar(self, tenant_id: UUID, n: int = 3) -> tuple[list[Any], Any]:
        """(the next `n` `CalendarSeason`s of the business's country, the business's
        «today») — `SeasonCalendarService.upcoming` / `.today`."""
        from qualify_api.whatsapp.seasons import production_season_calendar  # noqa: PLC0415

        service = production_season_calendar()
        return service.upcoming(tenant_id, n=n), service.today(tenant_id)

    def acting_user(self, tenant_id: UUID) -> UUID | None:
        from .connections_provider import acting_user_id  # noqa: PLC0415

        return acting_user_id(tenant_id)


_GATEWAY: SeasonalGateway | None = None


def gateway() -> SeasonalGateway:
    global _GATEWAY  # noqa: PLW0603
    if _GATEWAY is None:
        _GATEWAY = ProductionSeasonalGateway()
    return _GATEWAY
