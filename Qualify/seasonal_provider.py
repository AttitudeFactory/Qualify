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
    ) -> Any: ...

    def approve(
        self, tenant_id: UUID, brand_id: UUID, media_ids: list[UUID], user_id: UUID | None
    ) -> Any: ...

    def another(
        self, tenant_id: UUID, brand_id: UUID, media_id: UUID, user_id: UUID | None
    ) -> Any: ...

    def batch_counts(self, mode: str) -> tuple[int, int]: ...

    def archive(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any: ...

    def restore(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any: ...

    def approved_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[Any]: ...

    def ai_video_cost_usd(self) -> Decimal | None: ...

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
    ) -> Any:
        return self.service.plan_batch(
            tenant_id=tenant_id,
            brand_id=brand_id,
            season_key=season_key,
            season_label=season_label,
            mode=mode,
            user_id=user_id,
        )

    def approve(
        self, tenant_id: UUID, brand_id: UUID, media_ids: list[UUID], user_id: UUID | None
    ) -> Any:
        return self.service.approve(
            tenant_id=tenant_id, brand_id=brand_id, media_ids=media_ids, user_id=user_id
        )

    def another(self, tenant_id: UUID, brand_id: UUID, media_id: UUID, user_id: UUID | None) -> Any:
        """«Pedir otro»: the same slot is made again (`request_another`, from ready, rejected
        or failed; at most three times — `AttemptsExhausted` says so in Spanish)."""
        return self.service.request_another(
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

    def ai_video_cost_usd(self) -> Decimal | None:
        """The estimate of one IA video from the CURRENT pricing table, as the service
        computes it; None when it cannot (then «Crear con IA» is not offered). PENDING
        backend (m-24976893): the service has no estimate yet, so today this is None."""
        try:
            estimate = getattr(self.service, "ai_video_cost_usd", None)
            return Decimal(str(estimate())) if callable(estimate) else None
        except Exception as exc:  # noqa: BLE001 — no price, no paid option
            logger.warning("seasonal ai cost unavailable: %s", type(exc).__name__)
            return None

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
