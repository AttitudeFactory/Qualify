"""Backend access for «Tu producto en sticker» (m-25017372): a thin gateway over
`qualify_api.creative.product_stickers.ProductStickerService` (characters, paid in
creaciones) and the seasonal library `qualify_api.whatsapp.seasonal.SeasonalMediaService`
(the stickers themselves, free). Tests fake the whole gateway. Every read and write goes
through the services' `tenant_session`; previews through
`seasonal_media.issue_seasonal_view_path` (this business only). Blocking: callers run it off
the event loop.

The flow the screens drive (UX doc `docs/ux-stickers-producto.md`, with the founder's
decisions of 2026-11-12: the cost is shown in CREACIONES, never in dollars; «Pedir otro»
keeps every drawing and the owner picks one; no cap but the month's creations; the chat
lists the season's stickers first):

1. `products()` → step 1's grid (only products with a photo) + `without_photo`.
2. `cost()` → «Este dibujo usa 1 creación. Te quedan 12 este mes.», the button label, and
   whether the month can pay it (`can_pay`, `message` when not).
3. `create_character(product_id, accepted_creations=cost().creations)` → a `pending`
   character card; it becomes `ready` (or `failed`, creation given back) in ~30 s–2 min.
   «Pedir otro» is the same call again: a NEW character, the earlier ones are kept.
4. `characters()` → every drawing (newest first) to pick from; `use_character(id)` picks
   one (`approved`), `discard_character(id)` hides one.
5. `make_stickers(character_id, messages, animated=…, still=…)` → library rows, `pending`,
   that arrive `ready` in «Por aprobar» (free).
6. `stickers()` → the «De tus productos» rows; `approve_stickers`, `another_sticker`
   (draw it again, free), `delete_sticker` are the library's own actions.

Every refusal is a `ProductStickerError` (or the library's `SeasonalError`) whose `.message`
is the Spanish text to show as it is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductOption:
    """One product of step 1 (it has a photo)."""

    id: str
    name: str
    src: str = ""


@dataclass(frozen=True)
class ProductStep:
    products: tuple[ProductOption, ...]
    #: «3 productos no salen porque no tienen foto.» (0: say nothing)
    without_photo: int
    #: The product to pre-select: the last one drawn, else the catalog's first ("" if none).
    preselected: str = ""


@dataclass(frozen=True)
class CreationsCost:
    """What a drawing uses, in the owner's unit (decision 8 / founder 2026-11-12)."""

    creations: int
    #: None for an unlimited plan.
    left: int | None
    unlimited: bool
    can_pay: bool
    #: «Este dibujo usa 1 creación. Te quedan 12 este mes.»
    cost_line: str
    #: «Crear dibujo · 1 creación»
    button_label: str
    #: Why it cannot be paid («Te falta 1 creación este mes. Vuelves a tener el 1 de
    #: diciembre.»); "" when it can.
    message: str = ""


@dataclass(frozen=True)
class CharacterCard:
    id: str
    product_id: str
    product_name: str
    #: pending | ready | failed | approved
    status: str
    src: str = ""
    #: The owner's words when `failed` («Este dibujo no salió y no se te cobró. Puedes pedir
    #: otro.»)
    failure_text: str = ""
    created_at: datetime | None = None


@dataclass(frozen=True)
class StickerCard:
    id: str
    character_id: str
    message: str
    animated: bool
    #: the library's: pending | ready | approved | rejected | failed | archived
    status: str
    src: str = ""
    failure_text: str = ""
    #: «Sticker con movimiento de Shawarma mixto que dice ¡Gracias por tu pedido!» (`alt`)
    alt: str = ""


class ProductStickerGateway(Protocol):
    def brand(self, tenant_id: UUID) -> UUID | None: ...

    def acting_user(self, tenant_id: UUID) -> UUID | None: ...

    def products(self, tenant_id: UUID, brand_id: UUID) -> ProductStep: ...

    def cost(self, tenant_id: UUID, brand_id: UUID) -> CreationsCost: ...

    def presets(self) -> tuple[str, ...]: ...

    def max_message_chars(self) -> int: ...

    def check_message(self, text: str) -> str: ...

    def create_character(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        product_id: UUID,
        user_id: UUID | None,
        accepted_creations: int,
    ) -> CharacterCard: ...

    def characters(
        self, tenant_id: UUID, brand_id: UUID, product_id: UUID | None = None
    ) -> list[CharacterCard]: ...

    def use_character(
        self, tenant_id: UUID, brand_id: UUID, character_id: UUID, user_id: UUID | None
    ) -> CharacterCard: ...

    def discard_character(
        self, tenant_id: UUID, brand_id: UUID, character_id: UUID, user_id: UUID | None
    ) -> CharacterCard: ...

    def restore_character(
        self, tenant_id: UUID, brand_id: UUID, character_id: UUID, user_id: UUID | None
    ) -> CharacterCard: ...

    def make_stickers(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        character_id: UUID,
        messages: list[str],
        user_id: UUID | None,
        *,
        animated: bool = True,
        still: bool = False,
    ) -> list[StickerCard]: ...

    def stickers(self, tenant_id: UUID, brand_id: UUID) -> list[StickerCard]: ...

    def approve_stickers(
        self, tenant_id: UUID, brand_id: UUID, sticker_ids: list[UUID], user_id: UUID | None
    ) -> list[StickerCard]: ...

    def another_sticker(
        self, tenant_id: UUID, brand_id: UUID, sticker_id: UUID, user_id: UUID | None
    ) -> StickerCard: ...

    def delete_sticker(
        self, tenant_id: UUID, brand_id: UUID, sticker_id: UUID, user_id: UUID | None
    ) -> StickerCard: ...


def creations_word(n: int) -> str:
    return "1 creación" if n == 1 else f"{n} creaciones"


def cost_texts(creations: int, left: int | None, unlimited: bool) -> tuple[str, str]:
    """(cost line, button label) in creaciones — never money."""
    line = f"Este dibujo usa {creations_word(creations)}."
    if not unlimited and left is not None:
        line += " Te queda 1 este mes." if left == 1 else f" Te quedan {left} este mes."
    return line, f"Crear dibujo · {creations_word(creations)}"


class ProductionProductStickerGateway:
    def __init__(self, service: Any = None, library: Any = None) -> None:
        self._service = service
        self._library = library

    @property
    def service(self) -> Any:
        if self._service is None:
            from qualify_api.creative.product_stickers import (  # noqa: PLC0415
                production_product_sticker_service,
            )

            self._service = production_product_sticker_service()
        return self._service

    @property
    def library(self) -> Any:
        if self._library is None:
            from qualify_api.whatsapp.seasonal import (  # noqa: PLC0415
                production_seasonal_service,
            )

            self._library = production_seasonal_service()
        return self._library

    def brand(self, tenant_id: UUID) -> UUID | None:
        from .creators_provider import session_brand  # noqa: PLC0415

        return session_brand(tenant_id)

    def acting_user(self, tenant_id: UUID) -> UUID | None:
        from .connections_provider import acting_user_id  # noqa: PLC0415

        return acting_user_id(tenant_id)

    # --- step 1 -------------------------------------------------------------------------

    def products(self, tenant_id: UUID, brand_id: UUID) -> ProductStep:
        choices = self.service.products(tenant_id, brand_id)
        options = tuple(
            ProductOption(id=str(p.product_id), name=p.name, src=_thumb(tenant_id, p.object_key))
            for p in choices.products
        )
        last = self.service.last_product(tenant_id, brand_id)
        ids = {o.id for o in options}
        preselected = str(last) if last is not None and str(last) in ids else ""
        if not preselected and options:
            preselected = options[0].id
        return ProductStep(
            products=options, without_photo=choices.without_photo, preselected=preselected
        )

    # --- the cost -----------------------------------------------------------------------

    def cost(self, tenant_id: UUID, brand_id: UUID) -> CreationsCost:
        quote = self.service.quote(tenant_id, brand_id)
        line, button = cost_texts(quote.creations, quote.left, quote.unlimited)
        return CreationsCost(
            creations=quote.creations,
            left=quote.left,
            unlimited=quote.unlimited,
            can_pay=quote.can_pay,
            cost_line=line,
            button_label=button,
            message=quote.message,
        )

    # --- messages -----------------------------------------------------------------------

    def presets(self) -> tuple[str, ...]:
        from qualify_api.creative.product_stickers import MESSAGE_PRESETS  # noqa: PLC0415

        return MESSAGE_PRESETS

    def max_message_chars(self) -> int:
        from qualify_creative.seasonal.sticker_caption import (  # noqa: PLC0415
            MAX_MESSAGE_CHARS,
        )

        return MAX_MESSAGE_CHARS

    def check_message(self, text: str) -> str:
        """The message as it will be drawn; `MessageEmpty` / `MessageTooLong` otherwise."""
        from qualify_api.creative.product_stickers import check_message  # noqa: PLC0415

        return check_message(text)

    # --- characters ---------------------------------------------------------------------

    def create_character(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        product_id: UUID,
        user_id: UUID | None,
        accepted_creations: int,
    ) -> CharacterCard:
        found = self.service.request_character(
            tenant_id, brand_id, product_id, user_id, accepted_creations=accepted_creations
        )
        return self._card(tenant_id, brand_id, found)

    def characters(
        self, tenant_id: UUID, brand_id: UUID, product_id: UUID | None = None
    ) -> list[CharacterCard]:
        return [
            self._card(tenant_id, brand_id, c)
            for c in self.service.characters(tenant_id, brand_id, product_id)
        ]

    def use_character(
        self, tenant_id: UUID, brand_id: UUID, character_id: UUID, user_id: UUID | None
    ) -> CharacterCard:
        found = self.service.approve_character(tenant_id, brand_id, character_id, user_id)
        return self._card(tenant_id, brand_id, found)

    def discard_character(
        self, tenant_id: UUID, brand_id: UUID, character_id: UUID, user_id: UUID | None
    ) -> CharacterCard:
        found = self.service.discard_character(tenant_id, brand_id, character_id, user_id)
        return self._card(tenant_id, brand_id, found)

    def restore_character(
        self, tenant_id: UUID, brand_id: UUID, character_id: UUID, user_id: UUID | None
    ) -> CharacterCard:
        found = self.service.restore_character(tenant_id, brand_id, character_id, user_id)
        return self._card(tenant_id, brand_id, found)

    # --- stickers -----------------------------------------------------------------------

    def make_stickers(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        character_id: UUID,
        messages: list[str],
        user_id: UUID | None,
        *,
        animated: bool = True,
        still: bool = False,
    ) -> list[StickerCard]:
        rows = self.service.make_stickers(
            tenant_id, brand_id, character_id, messages, user_id, animated=animated, still=still
        )
        return self._sticker_cards(tenant_id, brand_id, rows)

    def stickers(self, tenant_id: UUID, brand_id: UUID) -> list[StickerCard]:
        return self._sticker_cards(tenant_id, brand_id, self.service.stickers(tenant_id, brand_id))

    def approve_stickers(
        self, tenant_id: UUID, brand_id: UUID, sticker_ids: list[UUID], user_id: UUID | None
    ) -> list[StickerCard]:
        rows = self.library.approve(
            tenant_id=tenant_id, brand_id=brand_id, media_ids=sticker_ids, user_id=user_id
        )
        return self._sticker_cards(tenant_id, brand_id, rows)

    def another_sticker(
        self, tenant_id: UUID, brand_id: UUID, sticker_id: UUID, user_id: UUID | None
    ) -> StickerCard:
        row = self.library.request_another(
            tenant_id=tenant_id, brand_id=brand_id, media_id=sticker_id, user_id=user_id
        )
        return self._sticker_cards(tenant_id, brand_id, [row])[0]

    def delete_sticker(
        self, tenant_id: UUID, brand_id: UUID, sticker_id: UUID, user_id: UUID | None
    ) -> StickerCard:
        row = self.library.delete(
            tenant_id=tenant_id, brand_id=brand_id, media_id=sticker_id, user_id=user_id
        )
        return self._sticker_cards(tenant_id, brand_id, [row])[0]

    # --- helpers ------------------------------------------------------------------------

    def _card(self, tenant_id: UUID, brand_id: UUID, c: Any) -> CharacterCard:
        return CharacterCard(
            id=str(c.id),
            product_id=str(c.product_id or ""),
            product_name=c.product_name,
            status=c.status,
            src=_preview(tenant_id, brand_id, c.object_key),
            failure_text=c.failure_text,
            created_at=c.created_at,
        )

    def _sticker_cards(self, tenant_id: UUID, brand_id: UUID, rows: list[Any]) -> list[StickerCard]:
        from qualify_api.creative.product_stickers import (  # noqa: PLC0415
            RECIPE_ANIMATED,
            parse_source_ref,
        )
        from qualify_api.whatsapp.seasonal import reason_text  # noqa: PLC0415

        names = {
            str(c.id): c.product_name
            for c in self.service.characters(tenant_id, brand_id, include_discarded=True)
        }
        cards = []
        for row in rows:
            try:
                character_id, message = parse_source_ref(row.source_ref)
            except ValueError:
                continue  # not a product sticker
            name = names.get(str(character_id), "tu producto")
            cards.append(
                StickerCard(
                    id=str(row.id),
                    character_id=str(character_id),
                    message=message,
                    animated=row.recipe == RECIPE_ANIMATED,
                    status=row.status,
                    src=_preview(tenant_id, brand_id, row.object_key),
                    failure_text=reason_text(row.fail_reason) if row.status == "failed" else "",
                    alt=(
                        f"Sticker {'con movimiento' if row.recipe == RECIPE_ANIMATED else 'quieto'}"
                        f" de {name} que dice {message}"
                    ),
                )
            )
        return cards


def _preview(tenant_id: UUID, brand_id: UUID, key: str | None) -> str:
    """`/r2seasonal/<token>` for a character's cut-out or a sticker of THIS business ("" when
    there is no file yet, or the key is not exactly one of this business's)."""
    from .seasonal_media import issue_seasonal_view_path  # noqa: PLC0415

    if not key:
        return ""
    try:
        return issue_seasonal_view_path(tenant_id, brand_id, key)
    except Exception as exc:  # noqa: BLE001 — a preview is not worth the list
        logger.warning("product sticker preview not issued: %s", type(exc).__name__)
        return ""


def _thumb(tenant_id: UUID, key: str | None) -> str:
    """A product photo's signed thumbnail (`r2_media`); "" when the gate refuses it."""
    from .r2_media import issue_view_path  # noqa: PLC0415

    if not key:
        return ""
    try:
        return issue_view_path(tenant_id, key, "image")
    except Exception as exc:  # noqa: BLE001
        logger.warning("product photo thumb not issued: %s", type(exc).__name__)
        return ""


_GATEWAY: ProductStickerGateway | None = None


def gateway() -> ProductStickerGateway:
    global _GATEWAY  # noqa: PLW0603
    if _GATEWAY is None:
        _GATEWAY = ProductionProductStickerGateway()
    return _GATEWAY
