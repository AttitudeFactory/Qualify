"""Canonical image- or video-pair recipes, independent of creative copy (m-24828982)."""

from __future__ import annotations

import re
import struct
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import IO, Any
from urllib.parse import urlsplit
from uuid import UUID

from qualify_api.ads.promotions import fingerprint

PIPELINE = "ad-unpublished-images-v1"
VIDEO_PIPELINE = "ad-unpublished-video-v1"
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # Local policy, not a claimed Meta limit.
# Local policy, not claimed Meta limits: one story card is the tightest placement we target.
MAX_VIDEO_BYTES = 100 * 1024 * 1024
MIN_VIDEO_SECONDS, MAX_VIDEO_SECONDS = 1.0, 60.0
MAX_MOOV_BYTES = 8 * 1024 * 1024  # bounded metadata read
MAX_TOP_LEVEL_BOXES = 1000  # real MP4s have a handful
TOO_LARGE = "Cada video del anuncio debe ocupar como máximo 100 MB. Recórtalo o elige otro."


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
class VideoSelection:
    """An MP4 of the piece's active version plus the explicit cover the owner chose.

    Meta's asset feed video takes a thumbnail; we never invent a URL or hash for it.
    """

    asset_id: UUID
    object_key: str
    content_type: str
    width: int
    height: int
    thumbnail: ImageSelection | None

    def validate(self, ratio: tuple[int, int]) -> None:
        if (
            self.content_type != "video/mp4"
            or type(self.width) is not int
            or type(self.height) is not int
            or min(self.width, self.height) <= 0
            or self.width * ratio[1] != self.height * ratio[0]
        ):
            raise UnpublishedUnavailable(
                "Elige dos videos MP4: uno para el perfil (4:5) y otro vertical de pantalla "
                "completa (9:16)."
            )
        if self.thumbnail is None:
            raise UnpublishedUnavailable(
                "Falta la portada de cada video. Elige una imagen de la misma pieza "
                "con el mismo formato del video."
            )
        self.thumbnail.validate(ratio)


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
    feed: ImageSelection | VideoSelection
    vertical: ImageSelection | VideoSelection

    @property
    def is_video(self) -> bool:
        return isinstance(self.feed, VideoSelection)

    def snapshot(self) -> dict[str, Any]:
        import json

        if type(self.feed) is not type(self.vertical):
            raise UnpublishedUnavailable("Usa dos imágenes o dos videos; no se pueden mezclar.")
        self.feed.validate((4, 5))
        self.vertical.validate((9, 16))
        if self.feed.asset_id == self.vertical.asset_id:
            raise UnpublishedUnavailable("Elige un archivo distinto para cada formato.")
        pipeline = VIDEO_PIPELINE if self.is_video else PIPELINE
        return json.loads(json.dumps(asdict(self), default=str)) | {"pipeline": pipeline}


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


def _image_hash(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None


def _video_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9]{1,32}", value) is not None


def creative_payload(source: ImageSource, form: ImageAdForm, hashes: tuple[str, str]) -> dict:
    """SDK26 fields; exact account compatibility must still pass Meta validate_only."""
    source.snapshot()
    if source.is_video or len(hashes) != 2 or not all(_image_hash(value) for value in hashes):
        raise UnpublishedUnavailable("Meta no confirmó las imágenes de este anuncio.")
    media = [{"hash": value} for value in hashes]
    return _asset_feed(source, form, "SINGLE_IMAGE", "images", "image_label", media)


def video_creative_payload(
    source: ImageSource, form: ImageAdForm, videos: tuple[tuple[str, str], ...]
) -> dict:
    """`videos` = (video id, cover image hash) for feed, then vertical. An image hash is
    never accepted as a video id, nor the other way round."""
    source.snapshot()
    if (
        not source.is_video
        or len(videos) != 2
        or not all(
            len(pair) == 2 and _video_id(pair[0]) and _image_hash(pair[1]) for pair in videos
        )
    ):
        raise UnpublishedUnavailable("Meta no confirmó los videos de este anuncio.")
    media = [{"video_id": video, "thumbnail_hash": cover} for video, cover in videos]
    return _asset_feed(source, form, "SINGLE_VIDEO", "videos", "video_label", media)


def _asset_feed(
    source: ImageSource,
    form: ImageAdForm,
    ad_format: str,
    field: str,
    label: str,
    media: list[dict[str, str]],
) -> dict:
    return {
        "object_story_spec": {"page_id": source.page_id, "instagram_user_id": source.instagram_id},
        "asset_feed_spec": {
            "ad_formats": [ad_format],
            field: [
                item | {"adlabels": [{"name": name}]}
                for item, name in zip(media, ("feed", "vertical"), strict=True)
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
                    label: {"name": name},
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


def _boxes(data: bytes) -> dict[bytes, list[bytes]]:
    found: dict[bytes, list[bytes]] = {}
    index = 0
    while index + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[index : index + 8])
        if length < 8 or index + length > len(data):
            raise ValueError("truncated box")
        found.setdefault(kind, []).append(data[index + 8 : index + length])
        index += length
    return found


def mp4_facts(stream: IO[bytes]) -> tuple[int, float, int, int]:
    """(bytes, seconds, width, height) of a seekable MP4, reading box headers and `moov` only.

    The size is checked first; media bytes are then skipped with seeks (the stream decides
    what a read costs). Fails closed: anything that is not a plain MP4 with exactly one sized
    video track raises an owner-readable error.
    """
    try:
        size = stream.seek(0, 2)
        stream.seek(0)
    except OSError:
        size = -1
    if size > MAX_VIDEO_BYTES:
        raise UnpublishedUnavailable(TOO_LARGE)
    try:
        if size <= 0:
            raise ValueError("unsized")
        moov, offset, boxes = None, 0, 0
        while offset < size and moov is None:
            # Each header is a ranged read: a file of tiny boxes must not cost millions of them.
            boxes += 1
            if boxes > MAX_TOP_LEVEL_BOXES:
                raise ValueError("too many boxes")
            length, kind = struct.unpack(">I4s", stream.read(8))
            body = 8
            if length == 1:
                length, body = struct.unpack(">Q", stream.read(8))[0], 16
            elif length == 0:
                length = size - offset
            if length < body or offset + length > size or (offset == 0 and kind != b"ftyp"):
                raise ValueError("not an mp4")
            if kind == b"moov":
                if length - body > MAX_MOOV_BYTES:
                    raise ValueError("oversized metadata")
                moov = stream.read(length - body)
            offset += length
            stream.seek(offset)
        stream.seek(0)
        top = _boxes(moov or b"")
        (mvhd,) = top[b"mvhd"]
        layout = ">IQ" if mvhd[0] == 1 else ">II"
        start = 20 if mvhd[0] == 1 else 12
        scale, duration = struct.unpack_from(layout, mvhd, start)
        tracks = []
        for trak in top.get(b"trak", []):
            inner = _boxes(trak)
            if _boxes(inner[b"mdia"][0])[b"hdlr"][0][8:12] == b"vide":
                width, height = struct.unpack(">II", inner[b"tkhd"][0][-8:])
                tracks.append((width >> 16, height >> 16))
        if len(tracks) != 1 or not scale:
            raise ValueError("expected one video track")
    except (OSError, KeyError, IndexError, ValueError, struct.error):
        raise UnpublishedUnavailable(
            "No pudimos leer el video de esta pieza. Elige otro video MP4."
        ) from None
    return size, duration / scale, *tracks[0]
