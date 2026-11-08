"""Backend access for «Stickers y videos de tu marca» (m-24976895): a thin gateway over
the backend's `SeasonalMediaService` (m-24976891, built in parallel — until it lands this
module imports it lazily and the screens show their load failure; tests fake the whole
gateway). Every read and write goes through the service's `tenant_session`; previews
through the object gate's signed read (`r2_media.issue_view_path`). Blocking: callers
run it off the event loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)


class SeasonalUnavailable(RuntimeError):
    """The backend's service is not deployed in this build yet."""


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

    def another(self, tenant_id: UUID, media_id: UUID, user_id: UUID | None) -> Any: ...

    def archive(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any: ...

    def restore(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any: ...

    def approved_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[Any]: ...

    def ai_video_cost_usd(self) -> Decimal | None: ...

    def preview_src(self, tenant_id: UUID, row: Any) -> str: ...

    def acting_user(self, tenant_id: UUID) -> UUID | None: ...


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
            try:
                from qualify_api.whatsapp.seasonal import (  # noqa: PLC0415
                    production_seasonal_media_service,
                )
            except ImportError as exc:  # the backend's module is not in this build yet
                raise SeasonalUnavailable(str(exc)) from exc
            self._service = production_seasonal_media_service()
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
            SeasonRow(
                key=str(getattr(r, "season_key", "") or getattr(r, "key", "")),
                label=str(getattr(r, "season_label", "") or getattr(r, "label", "")),
                archived=bool(getattr(r, "archived", False)),
            )
            for r in rows
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

    def another(self, tenant_id: UUID, media_id: UUID, user_id: UUID | None) -> Any:
        """«Pedir otro»: reject; the service re-plans that recipe."""
        return self.service.reject(tenant_id=tenant_id, media_id=media_id, user_id=user_id)

    def archive(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any:
        return self.service.archive(tenant_id=tenant_id, brand_id=brand_id, season_key=season_key)

    def restore(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> Any:
        return self.service.restore(tenant_id=tenant_id, brand_id=brand_id, season_key=season_key)

    def approved_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[Any]:
        return list(self.service.list_approved_for_chat(tenant_id=tenant_id, brand_id=brand_id))

    def ai_video_cost_usd(self) -> Decimal | None:
        """The estimate of one IA video from the CURRENT pricing table, as the service
        computes it; None when it cannot (then «Crear con IA» is not offered)."""
        try:
            estimate = getattr(self.service, "ai_video_cost_usd", None)
            return Decimal(str(estimate())) if callable(estimate) else None
        except Exception as exc:  # noqa: BLE001 — no price, no paid option
            logger.warning("seasonal ai cost unavailable: %s", type(exc).__name__)
            return None

    def preview_src(self, tenant_id: UUID, row: Any) -> str:
        """`/r2media/<token>` for a ready or approved piece ("" when the gate refuses)."""
        from .r2_media import issue_view_path  # noqa: PLC0415

        key = str(getattr(row, "object_key", "") or "")
        if not key:
            return ""
        video = str(getattr(row, "kind", "")) == "video"
        try:
            return issue_view_path(
                tenant_id,
                key,
                "video" if video else "image",
                "video/mp4" if video else "image/webp",
            )
        except Exception as exc:  # noqa: BLE001 — a preview is not worth the list
            logger.warning("seasonal preview not issued: %s", type(exc).__name__)
            return ""

    def acting_user(self, tenant_id: UUID) -> UUID | None:
        from .connections_provider import acting_user_id  # noqa: PLC0415

        return acting_user_id(tenant_id)


_GATEWAY: SeasonalGateway | None = None


def gateway() -> SeasonalGateway:
    global _GATEWAY  # noqa: PLW0603
    if _GATEWAY is None:
        _GATEWAY = ProductionSeasonalGateway()
    return _GATEWAY
