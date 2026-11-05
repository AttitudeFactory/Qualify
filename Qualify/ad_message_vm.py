"""Display an origin only for the exact inbound message resolved by the backend."""

from __future__ import annotations

from typing import Any
from uuid import UUID


def ad_origin_label(message: Any) -> str:
    """No raw referral, identifier or link enters the browser view model."""
    if getattr(message, "direction", None) != "inbound":
        return ""
    if not isinstance(getattr(message, "ad_promotion_id", None), UUID):
        return ""
    label = getattr(message, "ad_origin_label", None)
    return label if isinstance(label, str) else ""


def ad_origin_href(message: Any) -> str:
    """Only the resolved local UUID may select the authenticated promotion page."""
    return f"/promotions/{message.ad_promotion_id}" if ad_origin_label(message) else ""
