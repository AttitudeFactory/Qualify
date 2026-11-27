"""A paused Instagram carousel ad whose cards are products of the business's Catálogo
(m-25113484). Pure shapes and the Meta payload; reads live in `unpublished_repository`,
orchestration in `unpublished_service.CarouselAdService`."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from qualify_api.ads.unpublished import (
    ImageAdForm,
    ImageSelection,
    UnpublishedUnavailable,
    _image_hash,
    https_link,
)

CAROUSEL_PIPELINE = "ad-catalog-carousel-v1"
MIN_CARDS, MAX_CARDS = 2, 10  # Meta's carousel range (2-10 child attachments)
MAX_CARD_TITLE = 100  # Qualify policy, like the single-image headline; Meta validates its own
CARD_COUNT = "Elige entre 2 y 10 productos de tu Catálogo para el carrusel."


@dataclass(frozen=True)
class CarouselCard:
    """One product as a card: its primary photo, its name and its price, and the page the
    card opens. Everything but `link_url` is read from the Catálogo, never from the client."""

    product_id: UUID
    name: str
    price_label: str
    link_url: str
    photo: ImageSelection

    @property
    def title(self) -> str:
        # The price goes in the card's own title: Instagram shows the title on each card.
        return f"{self.name} · {self.price_label}"


@dataclass(frozen=True)
class CarouselSource:
    """Same account fields as `ImageSource`, so the shared preparation and activation code
    (`_observe`, uploads, `_remote`, `confirm`) treats both alike. No piece: `draft_id` is None
    and the provenance is the product and photo ids in `cards`."""

    tenant_id: UUID
    brand_id: UUID
    account_id: UUID
    connection_id: UUID
    credential_version: int
    meta_account_id: str
    instagram_id: str
    page_id: str
    currency: str
    timezone_name: str
    cards: tuple[CarouselCard, ...]

    draft_id = None
    is_video = False
    is_story = False

    @property
    def assets(self) -> tuple[ImageSelection, ...]:
        return tuple(card.photo for card in self.cards)

    def snapshot(self) -> dict[str, Any]:
        if not MIN_CARDS <= len(self.cards) <= MAX_CARDS:
            raise UnpublishedUnavailable(CARD_COUNT)
        if len({card.product_id for card in self.cards}) != len(self.cards):
            raise UnpublishedUnavailable("Cada producto puede ir una sola vez en el carrusel.")
        for card in self.cards:
            photo = card.photo
            if (
                photo.content_type not in {"image/jpeg", "image/png"}
                or type(photo.width) is not int
                or type(photo.height) is not int
                or min(photo.width, photo.height) <= 0
            ):
                raise UnpublishedUnavailable(
                    f"La foto de «{card.name}» no sirve para el anuncio. "
                    "Cámbiala en tu Catálogo por una foto JPG o PNG."
                )
            if not card.name.strip() or not card.price_label.strip():
                raise UnpublishedUnavailable(
                    "Cada producto del carrusel necesita nombre y precio en tu Catálogo."
                )
            if len(card.title) > MAX_CARD_TITLE:
                raise UnpublishedUnavailable(
                    f"El nombre de «{card.name[:40]}» es muy largo para el carrusel. "
                    "Acórtalo en tu Catálogo."
                )
            if not https_link(card.link_url):
                raise UnpublishedUnavailable(
                    f"Revisa el enlace de «{card.name}» en tu Catálogo: debe empezar por https://."
                )
        return json.loads(json.dumps(asdict(self), default=str)) | {"pipeline": CAROUSEL_PIPELINE}


def carousel_payload(source: CarouselSource, form: ImageAdForm, hashes: tuple[str, ...]) -> dict:
    """Cards in the owner's order (`multi_share_optimized` off) and no end card.

    facebook-python-business-sdk 26.0.0 `adobjects/`: AdCreativeObjectStorySpec (page_id,
    instagram_user_id, link_data), AdCreativeLinkData (link, message, child_attachments,
    multi_share_optimized, multi_share_end_card, call_to_action),
    AdCreativeLinkDataChildAttachment (link, image_hash, name, description, call_to_action),
    AdCreativeLinkDataCallToActionValue (link). `form.headline` is not sent: each card
    carries its own title."""
    source.snapshot()
    if len(hashes) != len(source.cards) or not all(_image_hash(value) for value in hashes):
        raise UnpublishedUnavailable(
            "Meta no recibió las fotos de los productos. Vuelve a intentarlo en unos minutos."
        )

    def cta(link: str) -> dict:
        return {"type": form.cta_type, "value": {"link": link}}

    return {
        "object_story_spec": {
            "page_id": source.page_id,
            "instagram_user_id": source.instagram_id,
            "link_data": {
                "link": form.link_url,
                "message": form.message,
                "child_attachments": [
                    {
                        "link": card.link_url,
                        "image_hash": value,
                        "name": card.title,
                        "description": card.price_label,
                        "call_to_action": cta(card.link_url),
                    }
                    for card, value in zip(source.cards, hashes, strict=True)
                ],
                "multi_share_optimized": False,
                "multi_share_end_card": False,
                "call_to_action": cta(form.link_url),
            },
        }
    }
