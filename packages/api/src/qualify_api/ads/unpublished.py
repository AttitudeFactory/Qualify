"""Canonical image-pair recipes, independent of creative copy generation (m-24828982)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from qualify_api.ads.promotions import fingerprint

PIPELINE = "ad-unpublished-images-v1"
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # Local policy, not a claimed Meta limit.


class UnpublishedUnavailable(ValueError):
    """Owner-readable boundary error; never a provider payload."""


@dataclass(frozen=True)
class ImageSelection:
    asset_id: UUID
    object_key: str
    content_type: str
    width: int
    height: int

    def validate(self, ratio: tuple[int, int]) -> None:
        if (
            self.content_type not in {"image/jpeg", "image/png"}
            or type(self.width) is not int
            or type(self.height) is not int
            or min(self.width, self.height) <= 0
            or self.width * ratio[1] != self.height * ratio[0]
        ):
            raise UnpublishedUnavailable(
                "Elige dos imágenes: una de 4:5 para las publicaciones y otra vertical de 9:16."
            )


@dataclass(frozen=True)
class ImageSource:
    tenant_id: UUID
    draft_id: UUID
    brand_id: UUID
    version_id: UUID
    revision: int
    account_id: UUID
    connection_id: UUID
    credential_version: int
    meta_account_id: str
    instagram_id: str
    page_id: str
    currency: str
    timezone_name: str
    feed: ImageSelection
    vertical: ImageSelection

    def snapshot(self) -> dict[str, Any]:
        import json

        self.feed.validate((4, 5))
        self.vertical.validate((9, 16))
        if self.feed.asset_id == self.vertical.asset_id:
            raise UnpublishedUnavailable("Elige una imagen distinta para cada formato.")
        return json.loads(json.dumps(asdict(self), default=str)) | {"pipeline": PIPELINE}


@dataclass(frozen=True)
class ImageAdForm:
    """Explicit ads input; never writes CopyPayload, draft fields or CTA enums."""

    message: str
    headline: str
    link_url: str
    budget_minor: int
    start_time: datetime
    end_time: datetime
    country: str
    cta_type: str = "LEARN_MORE"

    def validate(self, now: datetime) -> None:
        # Limits are Qualify preparation policy; Meta validates its own current limits.
        if (
            not all(
                isinstance(value, str)
                for value in (
                    self.message,
                    self.headline,
                    self.link_url,
                    self.country,
                    self.cta_type,
                )
            )
            or not isinstance(self.start_time, datetime)
            or not isinstance(self.end_time, datetime)
        ):
            raise UnpublishedUnavailable(
                "Revisa el texto, enlace, presupuesto y fechas del anuncio."
            )
        if len(self.message) > 2200:
            raise UnpublishedUnavailable("El texto del anuncio admite hasta 2.200 caracteres.")
        if len(self.headline) > 100:
            raise UnpublishedUnavailable("El título del anuncio admite hasta 100 caracteres.")
        try:
            url = urlsplit(self.link_url)
            valid_url = (
                url.scheme == "https"
                and url.hostname
                and not url.username
                and not url.password
                and (url.port is None or 0 < url.port <= 65535)
                and not any(c.isspace() or ord(c) < 32 for c in self.link_url)
            )
        except ValueError:
            valid_url = False
        if (
            not valid_url
            or len(self.link_url) > 2048
            or any(ord(c) < 32 for c in self.link_url)
            or not self.message.strip()
            or len(self.message) > 2200
            or not self.headline.strip()
            or len(self.headline) > 100
            or self.cta_type != "LEARN_MORE"
            or type(self.budget_minor) is not int
            or self.budget_minor <= 0
            or self.budget_minor % 100
            or not re.fullmatch(r"[A-Z]{2}", self.country)
            or self.start_time.utcoffset() is None
            or self.end_time.utcoffset() is None
            or not now < self.start_time < self.end_time
        ):
            raise UnpublishedUnavailable(
                "Revisa el texto, enlace, presupuesto y fechas del anuncio."
            )

    def snapshot(self) -> dict[str, Any]:
        return asdict(self) | {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
        }


def creative_payload(source: ImageSource, form: ImageAdForm, hashes: tuple[str, str]) -> dict:
    """SDK26 fields; exact account compatibility must still pass Meta validate_only."""
    source.snapshot()
    if len(hashes) != 2 or any(
        not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)
        for value in hashes
    ):
        raise UnpublishedUnavailable("Meta no confirmó las imágenes de este anuncio.")
    return {
        "object_story_spec": {"page_id": source.page_id, "instagram_user_id": source.instagram_id},
        "asset_feed_spec": {
            "ad_formats": ["SINGLE_IMAGE"],
            "images": [
                {"hash": value, "adlabels": [{"name": name}]}
                for value, name in zip(hashes, ("feed", "vertical"), strict=True)
            ],
            "bodies": [{"text": form.message}],
            "titles": [{"text": form.headline}],
            "link_urls": [{"website_url": form.link_url}],
            "call_to_action_types": [form.cta_type],
            "asset_customization_rules": [
                {
                    "customization_spec": {
                        "publisher_platforms": ["instagram"],
                        "instagram_positions": positions,
                    },
                    "image_label": {"name": name},
                    "priority": index,
                }
                for index, (name, positions) in enumerate(
                    (("feed", ["stream"]), ("vertical", ["story", "reels"])), 1
                )
            ],
        },
    }


def recipe_hash(source: ImageSource, form: ImageAdForm, actor: UUID) -> str:
    return fingerprint({"source": source.snapshot(), "form": form.snapshot(), "actor": str(actor)})
