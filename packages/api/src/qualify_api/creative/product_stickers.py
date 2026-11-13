"""Product «tierno» stickers for WhatsApp (m-25017372; founder 2026-11-12). The service the
screens call (through `Qualify/product_sticker_provider.py`).

The flow, assisted end to end (nothing is sent automatically):

1. **A character of a product** (paid): the owner picks a catalog product WITH a photo
   (`products`), sees the cost IN CREACIONES, never in money (decision 8: `quote`), and asks
   for it (`request_character`). One creation is charged at once in «creaciones del mes»
   (`creation_charges`, `request_kind = product_sticker`, the weight of one image in the
   weights table in force); the row and its `creative_jobs` job (kind `sticker_character`,
   pool `byteplus:seedream-5-0-pro`) are written in ONE transaction. `creative-worker`
   (`product_sticker_ai`) applies the price guard against the brand's monthly dollar cap at
   the paid boundary, calls Seedream 5.0 pro once, books the real USD cost in
   `creative_usage_events` + the brand's monthly spend, cuts the character out and marks it
   `ready`. A character that does not come out is `failed` and its creation is GIVEN BACK
   (decision 2: failures are not charged).
2. **«Pedir otro» keeps every character** (decision 3): asking again makes a NEW character;
   the owner sees them all (`characters`) and picks one (`approve_character`) — the first
   approval of the double approval. There is no count cap: the month's creations are the
   limit.
3. **Stickers from the picked character** (free): `make_stickers` plans one library row per
   (message × animated/still) in `brand_seasonal_media`, season `productos` («De tus
   productos»), `source_kind = character`, `source_ref = {character_id}:{message}`; the
   `media-worker` draws them with the Remotion `sticker` template v2 (caption mode). They land
   `ready` in «Por aprobar»; the owner approves each one (the second approval) with the
   library's own `SeasonalMediaService.approve` — the same approve / «Pedir otro» / delete /
   archive / chat send as the seasonal stickers. The chat lists the seasons first and the
   product stickers after them (decision 4).

Messages: the presets of `MESSAGE_PRESETS` or the owner's own text (≤ 25 characters).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from qualify_creative.creations import CreationPrice, CreationWeights, load_weights
from qualify_creative.seasonal.kawaii import (
    CHARACTER_PIPELINE_VERSION,
    KAWAII_MODEL,
    KAWAII_PRICING_VERSION,
    KAWAII_PROMPT_VERSION,
    character_quote_usd,
)
from qualify_creative.seasonal.sticker_caption import (
    MAX_MESSAGE_CHARS,
    PIPELINE_VERSION_PRODUCT,
    clean_message,
)

from qualify_api.creative.creations import NotEnoughCreations, not_enough_text

logger = logging.getLogger("qualify_api.creative.product_stickers")

# --- vocabulary ---------------------------------------------------------------------------

STATUS_PENDING: Final = "pending"
STATUS_READY: Final = "ready"
STATUS_FAILED: Final = "failed"
STATUS_APPROVED: Final = "approved"
STATUS_DISCARDED: Final = "discarded"
#: `creation_charges.request_kind` of a character (one per character, `revision` 1).
REQUEST_PRODUCT_STICKER: Final = "product_sticker"
CHARGE_REVISION: Final = 1
#: The library rows: an animated sticker and its still twin (≤ 100 KB).
RECIPE_ANIMATED: Final = "k-animado"
RECIPE_STATIC: Final = "k-quieto"
#: The messages offered first (UX doc §2); the owner may write their own.
MESSAGE_PRESETS: Final[tuple[str, ...]] = (
    "¡Gracias por tu pedido!",
    "Bienvenido",
    "En camino",
    "Entregado",
    "Listo para recoger",
)
#: The R2 «season» of the characters' own files (never a library row).
CHARACTER_FOLDER: Final = "personajes"
#: The file numbers under `seasonal/{tenant}/{brand}/personajes/{id}-{n}.webp`.
CUT_FILE: Final = 1
RAW_FILE: Final = 2

#: Why a character failed (`fail_reason`) → the owner's words (`qualify-copy-es`). Every one
#: says whether it was charged: the creation is always given back on a failure.
REASON_TEXT: Final[dict[str, str]] = {
    "budget_cap": (
        "Este mes ya se usó el presupuesto para dibujos. No se te cobró. "
        "Escríbenos y lo revisamos contigo."
    ),
    "no_budget_cap": (
        "Todavía no podemos dibujar para tu negocio. No se te cobró. Escríbenos y lo dejamos listo."
    ),
    "no_source": (
        "No pudimos abrir la foto del producto. No se te cobró. "
        "Sube otra foto en Tus productos y pide otro."
    ),
    "vendor_failed": "Este no salió y no se te cobró. Pide otro.",
    "no_character": "Este no salió y no se te cobró. Pide otro.",
    "unreadable_image": "Este no salió y no se te cobró. Pide otro.",
    "uncertain": "Este no salió y no se te cobró. Pide otro.",
    "lost_result": "Este no salió y no se te cobró. Pide otro.",
}
_DEFAULT_REASON = "Este no salió y no se te cobró. Pide otro."


def reason_text(reason: str | None) -> str:
    return REASON_TEXT.get(reason or "", _DEFAULT_REASON)


# --- errors: every one carries the owner's words -------------------------------------------


class ProductStickerError(ValueError):
    """Base: `message` is what the screen shows (Spanish, says what to do next)."""

    message = "No pudimos hacerlo. Vuelve a intentarlo en un momento."

    def __init__(self, message: str | None = None) -> None:
        if message:
            self.message = message
        super().__init__(self.message)


class ProductNotFound(ProductStickerError):
    message = "No encontramos ese producto. Elige otro de Tus productos."


class NoProductPhoto(ProductStickerError):
    message = (
        "Para dibujar tu producto necesitamos una foto de él. "
        "Sube la foto en Tus productos y vuelve aquí."
    )


class CostChanged(ProductStickerError):
    message = "El costo cambió. Revísalo antes de crear."


class NotEnoughCreationsLeft(ProductStickerError):
    """The month cannot pay the character (`creaciones del mes`): nothing was created."""

    def __init__(self, missing: int, renews_on: date | None = None) -> None:
        text = not_enough_text(missing)
        if renews_on is not None:
            text += f" Vuelves a tener el {renews_on.day} de {_MONTHS[renews_on.month - 1]}."
        super().__init__(text)
        self.missing = missing


class StartFailed(ProductStickerError):
    message = "No pudimos empezar a dibujar. No se te cobró. Vuelve a intentarlo en un momento."


class CharacterNotFound(ProductStickerError):
    message = "No encontramos ese dibujo. Actualiza la pantalla."


class CharacterChanged(ProductStickerError):
    """The row is not in the status the action needs (another tap, the worker)."""

    message = "Este dibujo cambió mientras tanto. Actualiza la pantalla."


class CharacterNotReady(ProductStickerError):
    message = "Este dibujo todavía no está listo. Llega en unos minutos."


class CharacterNotApproved(ProductStickerError):
    message = "Primero elige este dibujo para hacer stickers con él."


class MessageEmpty(ProductStickerError):
    message = "Escribe el mensaje del sticker."


class MessageTooLong(ProductStickerError):
    message = f'Máximo {MAX_MESSAGE_CHARS} letras. Prueba algo más corto, como "¡Gracias!".'


class NoMessages(ProductStickerError):
    message = "Elige al menos un mensaje."


class NoVariant(ProductStickerError):
    message = "Elige si lo quieres con movimiento, quieto o los dos."


_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


# --- records ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductPhoto:
    """A catalog product that can be drawn: its photo (the primary one, else the first)."""

    product_id: UUID
    name: str
    media_id: UUID
    object_key: str


@dataclass(frozen=True)
class ProductChoices:
    """Step 1: the products with a photo, in the catalog's order, and how many have none."""

    products: tuple[ProductPhoto, ...]
    without_photo: int


@dataclass(frozen=True)
class CharacterQuote:
    """What a character uses, in CREACIONES (the owner never sees money). `left` is None
    for an unlimited plan; `can_pay` False means the month cannot pay it (`message` says
    so in the owner's words)."""

    creations: int
    left: int | None
    unlimited: bool
    renews_on: date | None
    can_pay: bool
    message: str = ""


@dataclass(frozen=True)
class StickerCharacter:
    id: UUID
    tenant_id: UUID
    brand_id: UUID
    product_id: UUID | None
    product_name: str
    source_media_id: UUID
    status: str = STATUS_PENDING
    fail_reason: str | None = None
    object_key: str | None = None
    raw_object_key: str | None = None
    width: int | None = None
    height: int | None = None
    model_id: str = KAWAII_MODEL
    prompt_version: str = KAWAII_PROMPT_VERSION
    pipeline_version: str = CHARACTER_PIPELINE_VERSION
    pricing_table_version: str = KAWAII_PRICING_VERSION
    quoted_usd: Decimal = Decimal("0")
    cost_usd: Decimal = Decimal("0")
    vendor_request_id: str | None = None
    creation_charge_id: UUID | None = None
    vendor_request_started_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None
    approved_at: datetime | None = None

    @property
    def failure_text(self) -> str:
        return reason_text(self.fail_reason) if self.status == STATUS_FAILED else ""


# --- seams --------------------------------------------------------------------------------


class CharacterRepository(Protocol):
    """Tenant-scoped (Postgres: `tenant_session`, RLS)."""

    def insert_with_job(self, character: StickerCharacter) -> StickerCharacter:
        """Insert the `pending` character AND its `creative_jobs` job in ONE transaction."""
        ...

    def get(self, *, tenant_id: UUID, character_id: UUID) -> StickerCharacter | None: ...

    def list_brand(
        self, *, tenant_id: UUID, brand_id: UUID, product_id: UUID | None = None
    ) -> list[StickerCharacter]: ...

    def save(self, character: StickerCharacter, *, expected_status: str) -> StickerCharacter:
        """Write `character` only if the LOCKED stored row is still `expected_status`
        (else `CharacterChanged`)."""
        ...

    def start_request(self, *, tenant_id: UUID, character_id: UUID, at: datetime) -> bool:
        """Mark the paid POST as started — only on a `pending` row never started; False
        when it was already started (a previous claim may have paid)."""
        ...

    def clear_request(self, *, tenant_id: UUID, character_id: UUID) -> None:
        """Undo `start_request` when the vendor refused before creating anything (429)."""
        ...


class ProductReads(Protocol):
    def products_with_photos(
        self, tenant_id: UUID, brand_id: UUID
    ) -> tuple[list[ProductPhoto], int]: ...

    def product_photo(
        self, tenant_id: UUID, brand_id: UUID, product_id: UUID
    ) -> ProductPhoto | None: ...


class CreationsLedgerPort(Protocol):
    def balance(self, *, tenant_id: UUID, brand_id: UUID) -> Any: ...

    def charge(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        price: CreationPrice,
    ) -> UUID | None: ...

    def refund(self, *, tenant_id: UUID, draft_id: UUID, revision: int, reason: str) -> bool: ...


class StickerLibrary(Protocol):
    """The seasonal library (`whatsapp.seasonal.SeasonalMediaService`)."""

    def plan_rows(self, rows: Sequence[Any]) -> list[Any]: ...

    def list_season(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> list[Any]: ...


def product_sticker_price(weights: CreationWeights | None = None) -> CreationPrice:
    """One character = the weight of one image in the weights table in force (one Seedream
    image; `pesos-creaciones-v3`: 1 creation) — read from the data, never a literal."""
    table = weights or load_weights()
    return CreationPrice(REQUEST_PRODUCT_STICKER, table.flat_weight("image"))


def source_ref_of(character_id: UUID, message: str) -> str:
    """The library row's `source_ref`: `{character_id}:{message}`."""
    return f"{character_id}:{message}"


def parse_source_ref(source_ref: str) -> tuple[UUID, str]:
    """`(character_id, message)` of a product sticker row; `ValueError` otherwise."""
    head, sep, message = (source_ref or "").partition(":")
    if not sep or not message:
        raise ValueError("not a product sticker source")
    return UUID(head), message


def check_message(message: str) -> str:
    """The message as it will be drawn, or the owner's error."""
    words = " ".join((message or "").split())
    if not words:
        raise MessageEmpty()
    if len(words) > MAX_MESSAGE_CHARS:
        raise MessageTooLong()
    return clean_message(words)


# --- the service --------------------------------------------------------------------------


class ProductStickerService:
    def __init__(
        self,
        *,
        repo: CharacterRepository,
        products: ProductReads,
        ledger: CreationsLedgerPort,
        library: StickerLibrary,
        weights: CreationWeights | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repo = repo
        self._products = products
        self._ledger = ledger
        self._library = library
        self._weights = weights
        self._clock = clock
        self._new_id = id_factory

    # --- step 1: what can be drawn ------------------------------------------------------

    def products(self, tenant_id: UUID, brand_id: UUID) -> ProductChoices:
        found, without = self._products.products_with_photos(tenant_id, brand_id)
        return ProductChoices(products=tuple(found), without_photo=without)

    def last_product(self, tenant_id: UUID, brand_id: UUID) -> UUID | None:
        """The product of the business's latest character (to pre-select it), or None."""
        rows = self._repo.list_brand(tenant_id=tenant_id, brand_id=brand_id)
        return next((c.product_id for c in rows if c.product_id is not None), None)

    # --- the cost, in creaciones -----------------------------------------------------------

    def quote(self, tenant_id: UUID, brand_id: UUID) -> CharacterQuote:
        price = product_sticker_price(self._weights)
        balance = self._ledger.balance(tenant_id=tenant_id, brand_id=brand_id)
        unlimited = bool(getattr(balance, "unlimited", False))
        left = None if unlimited else int(balance.left)
        can_pay = unlimited or price.weight <= (left or 0)
        renews = getattr(balance, "renews_on", None)
        message = ""
        if not can_pay:
            message = NotEnoughCreationsLeft(price.weight - (left or 0), renews).message
        return CharacterQuote(
            creations=price.weight,
            left=left,
            unlimited=unlimited,
            renews_on=renews,
            can_pay=can_pay,
            message=message,
        )

    # --- the paid step ------------------------------------------------------------------

    def request_character(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        product_id: UUID,
        user_id: UUID | None,
        *,
        accepted_creations: int,
    ) -> StickerCharacter:
        """Ask for ONE new character of `product_id` («Crear» or «Pedir otro»: both make a
        new one; the earlier ones are kept). `accepted_creations` is what the screen showed
        (`quote().creations`): a different current weight is `CostChanged` and nothing is
        charged. The month cannot pay → `NotEnoughCreationsLeft`."""
        photo = self._products.product_photo(tenant_id, brand_id, product_id)
        if photo is None:
            raise NoProductPhoto()
        price = product_sticker_price(self._weights)
        if int(accepted_creations) != price.weight:
            raise CostChanged()
        character_id = self._new_id()
        try:
            charge_id = self._ledger.charge(
                tenant_id=tenant_id,
                brand_id=brand_id,
                draft_id=character_id,
                revision=CHARGE_REVISION,
                price=price,
            )
        except NotEnoughCreations as exc:
            balance = self._ledger.balance(tenant_id=tenant_id, brand_id=brand_id)
            raise NotEnoughCreationsLeft(
                max(exc.missing, 1), getattr(balance, "renews_on", None)
            ) from exc
        character = StickerCharacter(
            id=character_id,
            tenant_id=tenant_id,
            brand_id=brand_id,
            product_id=photo.product_id,
            product_name=photo.name,
            source_media_id=photo.media_id,
            quoted_usd=character_quote_usd(),
            creation_charge_id=charge_id,
            created_by=user_id,
            created_at=self._clock(),
        )
        try:
            stored = self._repo.insert_with_job(character)
        except Exception as exc:
            logger.exception("product_stickers.start_failed character=%s", character_id)
            self._ledger.refund(
                tenant_id=tenant_id,
                draft_id=character_id,
                revision=CHARGE_REVISION,
                reason="not_started",
            )
            raise StartFailed() from exc
        logger.info(
            "product_stickers.requested tenant=%s brand=%s character=%s product=%s",
            tenant_id,
            brand_id,
            character_id,
            product_id,
        )
        return stored

    # --- the owner's choice -------------------------------------------------------------

    def characters(
        self, tenant_id: UUID, brand_id: UUID, product_id: UUID | None = None
    ) -> list[StickerCharacter]:
        """Every character of the business (or of one product), newest first; discarded ones
        are left out."""
        rows = self._repo.list_brand(tenant_id=tenant_id, brand_id=brand_id, product_id=product_id)
        return [c for c in rows if c.status != STATUS_DISCARDED]

    def character(self, tenant_id: UUID, brand_id: UUID, character_id: UUID) -> StickerCharacter:
        found = self._repo.get(tenant_id=tenant_id, character_id=character_id)
        if found is None or found.brand_id != brand_id:
            raise CharacterNotFound()
        return found

    def approve_character(
        self, tenant_id: UUID, brand_id: UUID, character_id: UUID, user_id: UUID | None
    ) -> StickerCharacter:
        """«Usar este dibujo»: a `ready` character becomes the one its stickers are made from
        (the first approval). Approving an already approved one returns it."""
        found = self.character(tenant_id, brand_id, character_id)
        if found.status == STATUS_APPROVED:
            return found
        if found.status == STATUS_PENDING:
            raise CharacterNotReady()
        if found.status != STATUS_READY:
            raise CharacterChanged()
        return self._repo.save(
            replace(found, status=STATUS_APPROVED, approved_at=self._clock()),
            expected_status=STATUS_READY,
        )

    def discard_character(
        self, tenant_id: UUID, brand_id: UUID, character_id: UUID, user_id: UUID | None
    ) -> StickerCharacter:
        """«No me gusta»: a ready, approved or failed character leaves the list (the row is
        kept: its cost is provenance). Stickers already made from it stay in the library."""
        found = self.character(tenant_id, brand_id, character_id)
        if found.status == STATUS_DISCARDED:
            return found
        if found.status == STATUS_PENDING:
            raise CharacterNotReady()
        return self._repo.save(
            replace(found, status=STATUS_DISCARDED), expected_status=found.status
        )

    # --- the free step: stickers from the picked character --------------------------------

    @staticmethod
    def presets() -> tuple[str, ...]:
        return MESSAGE_PRESETS

    def make_stickers(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        character_id: UUID,
        messages: Sequence[str],
        user_id: UUID | None,
        *,
        animated: bool = True,
        still: bool = False,
    ) -> list[Any]:
        """Plan the stickers of an APPROVED character: one library row per message and per
        variant (animated and/or still), `pending`, each with its `media-worker` job; they
        arrive `ready` in «Por aprobar». Free (Remotion). Idempotent: a sticker already
        planned is returned as it is; one the owner deleted is made again."""
        from qualify_api.whatsapp.seasonal import (  # noqa: PLC0415
            KIND_STICKER,
            PRODUCT_SEASON_KEY,
            PRODUCT_SEASON_LABEL,
            SOURCE_CHARACTER,
            SeasonalMedia,
        )

        found = self.character(tenant_id, brand_id, character_id)
        if found.status != STATUS_APPROVED:
            raise CharacterNotApproved()
        cleaned = list(dict.fromkeys(check_message(m) for m in messages))
        if not cleaned:
            raise NoMessages()
        recipes = [r for r, on in ((RECIPE_ANIMATED, animated), (RECIPE_STATIC, still)) if on]
        if not recipes:
            raise NoVariant()
        now = self._clock()
        rows = [
            SeasonalMedia(
                id=self._new_id(),
                tenant_id=tenant_id,
                brand_id=brand_id,
                season_key=PRODUCT_SEASON_KEY,
                season_label=PRODUCT_SEASON_LABEL,
                kind=KIND_STICKER,
                recipe=recipe,
                source_kind=SOURCE_CHARACTER,
                source_ref=source_ref_of(character_id, message),
                pipeline_version=PIPELINE_VERSION_PRODUCT,
                created_by=user_id,
                created_at=now,
            )
            for message in cleaned
            for recipe in recipes
        ]
        return self._library.plan_rows(rows)

    def stickers(self, tenant_id: UUID, brand_id: UUID) -> list[Any]:
        """Every product sticker of the business (the library's «De tus productos»)."""
        from qualify_api.whatsapp.seasonal import PRODUCT_SEASON_KEY  # noqa: PLC0415

        return list(self._library.list_season(tenant_id, brand_id, PRODUCT_SEASON_KEY))

    # --- the worker -----------------------------------------------------------------------

    def mark_character_ready(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        character_id: UUID,
        object_key: str,
        raw_object_key: str,
        width: int,
        height: int,
    ) -> StickerCharacter:
        found = self.character(tenant_id, brand_id, character_id)
        if found.status != STATUS_PENDING:
            raise CharacterChanged()
        return self._repo.save(
            replace(
                found,
                status=STATUS_READY,
                object_key=object_key,
                raw_object_key=raw_object_key,
                width=width,
                height=height,
                fail_reason=None,
                finished_at=self._clock(),
            ),
            expected_status=STATUS_PENDING,
        )

    def note_paid(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        character_id: UUID,
        cost_usd: Decimal,
        vendor_request_id: str,
    ) -> None:
        """The real cost of the paid call, on the row (provenance), right after it."""
        found = self.character(tenant_id, brand_id, character_id)
        try:
            self._repo.save(
                replace(found, cost_usd=cost_usd, vendor_request_id=vendor_request_id),
                expected_status=found.status,
            )
        except CharacterChanged:
            logger.warning("product_stickers.cost_not_noted character=%s", character_id)

    def mark_character_failed(
        self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID, reason: str
    ) -> StickerCharacter | None:
        """A `pending` character that did not come out: `failed` and its creation given
        back (decision 2). Anything else is left alone (None)."""
        found = self.character(tenant_id, brand_id, character_id)
        if found.status != STATUS_PENDING:
            return None
        try:
            stored = self._repo.save(
                replace(
                    found,
                    status=STATUS_FAILED,
                    fail_reason=(reason or "vendor_failed")[:200],
                    finished_at=self._clock(),
                ),
                expected_status=STATUS_PENDING,
            )
        except CharacterChanged:
            return None
        self._ledger.refund(
            tenant_id=tenant_id,
            draft_id=character_id,
            revision=CHARGE_REVISION,
            reason=f"character_failed:{reason}"[:200],
        )
        return stored


# ======================================================================================
# In memory (tests)
# ======================================================================================


class MemoryCharacterRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, StickerCharacter] = {}
        self.jobs: list[UUID] = []

    def insert_with_job(self, character: StickerCharacter) -> StickerCharacter:
        if character.id not in self.rows:
            self.rows[character.id] = character
            self.jobs.append(character.id)
        return self.rows[character.id]

    def get(self, *, tenant_id: UUID, character_id: UUID) -> StickerCharacter | None:
        found = self.rows.get(character_id)
        return found if found is not None and found.tenant_id == tenant_id else None

    def list_brand(
        self, *, tenant_id: UUID, brand_id: UUID, product_id: UUID | None = None
    ) -> list[StickerCharacter]:
        rows = [
            c
            for c in self.rows.values()
            if c.tenant_id == tenant_id
            and c.brand_id == brand_id
            and (product_id is None or c.product_id == product_id)
        ]
        epoch = datetime.min.replace(tzinfo=UTC)
        return sorted(rows, key=lambda c: (c.created_at or epoch, str(c.id)), reverse=True)

    def save(self, character: StickerCharacter, *, expected_status: str) -> StickerCharacter:
        stored = self.rows.get(character.id)
        if stored is None or stored.status != expected_status:
            raise CharacterChanged()
        self.rows[character.id] = character
        return character

    def start_request(self, *, tenant_id: UUID, character_id: UUID, at: datetime) -> bool:
        found = self.get(tenant_id=tenant_id, character_id=character_id)
        if found is None or found.status != STATUS_PENDING:
            return False
        if found.vendor_request_started_at is not None:
            return False
        self.rows[character_id] = replace(found, vendor_request_started_at=at)
        return True

    def clear_request(self, *, tenant_id: UUID, character_id: UUID) -> None:
        found = self.get(tenant_id=tenant_id, character_id=character_id)
        if found is not None and found.status == STATUS_PENDING:
            self.rows[character_id] = replace(found, vendor_request_started_at=None)


class MemoryProductReads:
    def __init__(self) -> None:
        self.photos: list[ProductPhoto] = []
        self.without_photo = 0
        self.brand_of: dict[UUID, UUID] = {}

    def products_with_photos(
        self, tenant_id: UUID, brand_id: UUID
    ) -> tuple[list[ProductPhoto], int]:
        return [p for p in self.photos if self.brand_of.get(p.product_id) == brand_id], (
            self.without_photo
        )

    def product_photo(
        self, tenant_id: UUID, brand_id: UUID, product_id: UUID
    ) -> ProductPhoto | None:
        return next(
            (
                p
                for p in self.photos
                if p.product_id == product_id and self.brand_of.get(product_id) == brand_id
            ),
            None,
        )


# ======================================================================================
# Postgres
# ======================================================================================

_COLUMNS: Final = (
    "id, tenant_id, brand_id, product_id, product_name, source_media_id, status, fail_reason, "
    "object_key, raw_object_key, width, height, model_id, prompt_version, pipeline_version, "
    "pricing_table_version, quoted_usd, cost_usd, vendor_request_id, creation_charge_id, "
    "vendor_request_started_at, created_by, created_at, finished_at, approved_at"
)
_TABLE: Final = "product_sticker_characters"


def _from_row(row: Any) -> StickerCharacter:
    return StickerCharacter(
        id=row.id,
        tenant_id=row.tenant_id,
        brand_id=row.brand_id,
        product_id=row.product_id,
        product_name=row.product_name,
        source_media_id=row.source_media_id,
        status=row.status,
        fail_reason=row.fail_reason,
        object_key=row.object_key,
        raw_object_key=row.raw_object_key,
        width=row.width,
        height=row.height,
        model_id=row.model_id,
        prompt_version=row.prompt_version,
        pipeline_version=row.pipeline_version,
        pricing_table_version=row.pricing_table_version,
        quoted_usd=Decimal(row.quoted_usd),
        cost_usd=Decimal(row.cost_usd),
        vendor_request_id=row.vendor_request_id,
        creation_charge_id=row.creation_charge_id,
        vendor_request_started_at=row.vendor_request_started_at,
        created_by=row.created_by,
        created_at=row.created_at,
        finished_at=row.finished_at,
        approved_at=row.approved_at,
    )


class PostgresCharacterRepository:
    """`tenant_session(tenant_id)` per call (`qualify_app`, RLS)."""

    def insert_with_job(self, character: StickerCharacter) -> StickerCharacter:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        from qualify_api.creative import job_queue as q  # noqa: PLC0415

        with tenant_session(character.tenant_id) as session:
            row = session.execute(
                text(
                    f"""
                    INSERT INTO {_TABLE} (
                        id, tenant_id, brand_id, product_id, product_name, source_media_id,
                        status, model_id, prompt_version, pipeline_version,
                        pricing_table_version, quoted_usd, creation_charge_id, created_by,
                        created_at
                    ) VALUES (
                        :id, :tenant_id, :brand_id, :product_id, :product_name,
                        :source_media_id, 'pending', :model_id, :prompt_version,
                        :pipeline_version, :pricing_table_version, :quoted_usd,
                        :creation_charge_id, :created_by,
                        COALESCE(CAST(:created_at AS timestamptz), now())
                    )
                    RETURNING {_COLUMNS}
                    """
                ),
                {
                    "id": character.id,
                    "tenant_id": character.tenant_id,
                    "brand_id": character.brand_id,
                    "product_id": character.product_id,
                    "product_name": character.product_name[:200],
                    "source_media_id": character.source_media_id,
                    "model_id": character.model_id,
                    "prompt_version": character.prompt_version,
                    "pipeline_version": character.pipeline_version,
                    "pricing_table_version": character.pricing_table_version,
                    "quoted_usd": character.quoted_usd,
                    "creation_charge_id": character.creation_charge_id,
                    "created_by": character.created_by,
                    "created_at": character.created_at,
                },
            ).one()
            q.enqueue_character_job(
                session,
                tenant_id=character.tenant_id,
                character_id=character.id,
                pricing_version=character.pricing_table_version,
                pipeline_version=character.pipeline_version,
            )
            return _from_row(row)

    def get(self, *, tenant_id: UUID, character_id: UUID) -> StickerCharacter | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(f"SELECT {_COLUMNS} FROM {_TABLE} WHERE id = :id"), {"id": character_id}
            ).one_or_none()
            return _from_row(row) if row is not None else None

    def list_brand(
        self, *, tenant_id: UUID, brand_id: UUID, product_id: UUID | None = None
    ) -> list[StickerCharacter]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        where = "brand_id = :brand_id" + (" AND product_id = :product_id" if product_id else "")
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM {_TABLE} WHERE {where} "
                    "ORDER BY created_at DESC, id DESC LIMIT 500"
                ),
                {"brand_id": brand_id, "product_id": product_id},
            ).all()
            return [_from_row(r) for r in rows]

    def save(self, character: StickerCharacter, *, expected_status: str) -> StickerCharacter:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(character.tenant_id) as session:
            current = session.execute(
                text(f"SELECT status FROM {_TABLE} WHERE id = :id FOR UPDATE"),
                {"id": character.id},
            ).scalar_one_or_none()
            if current is None or current != expected_status:
                raise CharacterChanged()
            row = session.execute(
                text(
                    f"""
                    UPDATE {_TABLE} SET
                        status = :status, fail_reason = :fail_reason,
                        object_key = :object_key, raw_object_key = :raw_object_key,
                        width = :width, height = :height, cost_usd = :cost_usd,
                        vendor_request_id = :vendor_request_id,
                        finished_at = :finished_at, approved_at = :approved_at
                    WHERE id = :id
                    RETURNING {_COLUMNS}
                    """
                ),
                {
                    "id": character.id,
                    "status": character.status,
                    "fail_reason": character.fail_reason,
                    "object_key": character.object_key,
                    "raw_object_key": character.raw_object_key,
                    "width": character.width,
                    "height": character.height,
                    "cost_usd": character.cost_usd,
                    "vendor_request_id": character.vendor_request_id,
                    "finished_at": character.finished_at,
                    "approved_at": character.approved_at,
                },
            ).one()
            return _from_row(row)

    def start_request(self, *, tenant_id: UUID, character_id: UUID, at: datetime) -> bool:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            started = session.execute(
                text(
                    f"UPDATE {_TABLE} SET vendor_request_started_at = :at "
                    "WHERE id = :id AND status = 'pending' "
                    "AND vendor_request_started_at IS NULL RETURNING id"
                ),
                {"id": character_id, "at": at},
            ).scalar_one_or_none()
            return started is not None

    def clear_request(self, *, tenant_id: UUID, character_id: UUID) -> None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    f"UPDATE {_TABLE} SET vendor_request_started_at = NULL "
                    "WHERE id = :id AND status = 'pending'"
                ),
                {"id": character_id},
            )


class PostgresProductReads:
    """The catalog's active products and their first photo (the primary one first)."""

    _SQL: Final = """
        SELECT p.id AS product_id, p.name, m.id AS media_id, m.object_key
        FROM brand_products p
        LEFT JOIN LATERAL (
            SELECT pm.id, pm.object_key FROM product_media pm
            WHERE pm.product_id = p.id AND pm.brand_id = p.brand_id
              AND pm.media_type = 'image'
            ORDER BY pm.is_primary DESC, pm.position, pm.created_at
            LIMIT 1
        ) m ON TRUE
        WHERE p.brand_id = :brand_id AND p.is_active {extra}
        ORDER BY p.position, p.created_at, p.id
    """

    def _rows(self, tenant_id: UUID, brand_id: UUID, product_id: UUID | None) -> list[Any]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        extra = "AND p.id = :product_id" if product_id is not None else ""
        with tenant_session(tenant_id) as session:
            return list(
                session.execute(
                    text(self._SQL.format(extra=extra)),
                    {"brand_id": brand_id, "product_id": product_id},
                ).all()
            )

    def products_with_photos(
        self, tenant_id: UUID, brand_id: UUID
    ) -> tuple[list[ProductPhoto], int]:
        rows = self._rows(tenant_id, brand_id, None)
        found = [
            ProductPhoto(
                product_id=r.product_id, name=r.name, media_id=r.media_id, object_key=r.object_key
            )
            for r in rows
            if r.media_id is not None
        ]
        return found, len(rows) - len(found)

    def product_photo(
        self, tenant_id: UUID, brand_id: UUID, product_id: UUID
    ) -> ProductPhoto | None:
        rows = self._rows(tenant_id, brand_id, product_id)
        if not rows or rows[0].media_id is None:
            return None
        r = rows[0]
        return ProductPhoto(
            product_id=r.product_id, name=r.name, media_id=r.media_id, object_key=r.object_key
        )


def production_product_sticker_service() -> ProductStickerService:
    from qualify_api.creative.creations import PostgresCreationsLedger  # noqa: PLC0415
    from qualify_api.whatsapp.seasonal import production_seasonal_service  # noqa: PLC0415

    return ProductStickerService(
        repo=PostgresCharacterRepository(),
        products=PostgresProductReads(),
        ledger=PostgresCreationsLedger(),
        library=production_seasonal_service(),
    )


__all__ = [
    "MESSAGE_PRESETS",
    "REASON_TEXT",
    "CharacterChanged",
    "CharacterNotApproved",
    "CharacterNotFound",
    "CharacterNotReady",
    "CharacterQuote",
    "CostChanged",
    "MessageEmpty",
    "MessageTooLong",
    "NoMessages",
    "NoProductPhoto",
    "NoVariant",
    "NotEnoughCreationsLeft",
    "ProductChoices",
    "ProductNotFound",
    "ProductPhoto",
    "ProductStickerError",
    "ProductStickerService",
    "StartFailed",
    "StickerCharacter",
    "production_product_sticker_service",
    "reason_text",
]
