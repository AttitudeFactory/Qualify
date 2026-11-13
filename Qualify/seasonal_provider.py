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
class AiPhoto:
    id: str
    title: str
    src: str = ""


@dataclass(frozen=True)
class AiQuote:
    """The IA batch's price before creating (`quote_batch`), or why it is not offered."""

    per_video_usd: Decimal | None = None
    total_usd: Decimal | None = None
    videos: int = 0
    unavailable: str = ""
    #: Off by configuration (generic `ModeNotAvailable`), not for lack of a photo.
    mode_off: bool = False
    #: The photos THIS quote animates (`BatchQuote.photos`); their ids go back to
    #: `plan_batch(accepted_draft_ids=…)`.
    photos: tuple[AiPhoto, ...] = ()


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
        accepted_draft_ids: list[UUID] | None = None,
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

    def delete(
        self, tenant_id: UUID, brand_id: UUID, media_id: UUID, user_id: UUID | None
    ) -> Any: ...

    def batch_counts(self, mode: str) -> tuple[int, int]: ...

    def archive(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any: ...

    def restore(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any: ...

    def approved_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[Any]: ...

    def ai_quote(self, tenant_id: UUID, brand_id: UUID) -> AiQuote: ...

    def month_ai_total(self, tenant_id: UUID, brand_id: UUID) -> Decimal: ...

    def reason_texts(self) -> dict[str, str]: ...

    def ai_video_price(self, tenant_id: UUID, brand_id: UUID) -> Decimal | None: ...

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
        accepted_draft_ids: list[UUID] | None = None,
    ) -> Any:
        """«Con IA» needs the TOTAL and the PHOTOS the owner confirmed from `ai_quote`
        (`CostNotConfirmed` / `SelectionChanged` otherwise)."""
        return self.service.plan_batch(
            tenant_id=tenant_id,
            brand_id=brand_id,
            season_key=season_key,
            season_label=season_label,
            mode=mode,
            user_id=user_id,
            accepted_total_usd=accepted_total_usd,
            accepted_draft_ids=accepted_draft_ids,
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
        or failed; no owner-facing cap since m-25016851 — only the technical ceiling's
        `AttemptsExhausted`, worded without a count). A video made with IA needs the
        per-video cost the owner confirmed."""
        return self.service.request_another(
            tenant_id=tenant_id,
            brand_id=brand_id,
            media_id=media_id,
            user_id=user_id,
            accepted_cost_usd=accepted_cost_usd,
        )

    def delete(self, tenant_id: UUID, brand_id: UUID, media_id: UUID, user_id: UUID | None) -> Any:
        """«Eliminar» (m-25016851): the medium leaves the library and the chat; its files
        are deleted through the gate (`SeasonalMediaService.delete`, idempotent)."""
        return self.service.delete(
            tenant_id=tenant_id, brand_id=brand_id, media_id=media_id, user_id=user_id
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
        from qualify_api.whatsapp.seasonal import (  # noqa: PLC0415
            ModeNotAvailable,
            NoPhotoToAnimate,
        )

        try:
            quote = self.service.quote_batch(tenant_id, brand_id, "ai")
        except NoPhotoToAnimate as exc:  # on, but nothing to animate: shown, disabled
            return AiQuote(unavailable=exc.message)
        except ModeNotAvailable as exc:  # off by configuration: not shown at all
            return AiQuote(unavailable=exc.message, mode_off=True)
        return AiQuote(
            per_video_usd=quote.per_ai_video_usd,
            total_usd=quote.total_usd,
            videos=quote.ai_videos,
            photos=tuple(
                AiPhoto(
                    id=str(p.draft_id),
                    title=p.name or "Pieza sin título",
                    src=_thumb(tenant_id, p.thumbnail_key),
                )
                for p in quote.photos
            ),
        )

    def month_ai_total(self, tenant_id: UUID, brand_id: UUID) -> Decimal:
        """What the business spent on seasonal IA videos this month (only those, from
        day 1 in the business's own zone — the backend decides both)."""
        from qualify_api.creative.seasonal_ai import seasonal_ai_month_total  # noqa: PLC0415

        return seasonal_ai_month_total(tenant_id, brand_id)

    def ai_video_price(self, tenant_id: UUID, brand_id: UUID) -> Decimal | None:
        """ONE IA video's price for «Pedir otro» (`ai_video_price_usd`, no photo needed);
        None while «Con IA» is off (`ModeNotAvailable`)."""
        from qualify_api.whatsapp.seasonal import ModeNotAvailable  # noqa: PLC0415

        try:
            return self.service.ai_video_price_usd()
        except ModeNotAvailable:
            return None

    def reason_texts(self) -> dict[str, str]:
        """The worker's refusal words (`budget_cap` → «Esta pieza superaría tu tope de
        gasto.»)."""
        from qualify_api.whatsapp.seasonal import REASON_TEXT  # noqa: PLC0415

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


def _thumb(tenant_id: UUID, key: str | None) -> str:
    """A quoted photo's signed thumbnail (`r2_media`: the piece's own key); "" when the
    gate refuses it (the card shows its name and icon)."""
    from .r2_media import issue_view_path  # noqa: PLC0415

    if not key:
        return ""
    try:
        return issue_view_path(tenant_id, key, "image")
    except Exception as exc:  # noqa: BLE001
        logger.warning("seasonal ai thumb not issued: %s", type(exc).__name__)
        return ""


_GATEWAY: SeasonalGateway | None = None


def gateway() -> SeasonalGateway:
    global _GATEWAY  # noqa: PLW0603
    if _GATEWAY is None:
        _GATEWAY = ProductionSeasonalGateway()
    return _GATEWAY
