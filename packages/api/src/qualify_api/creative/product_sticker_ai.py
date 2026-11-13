"""The paid step of a product sticker (m-25017372): ONE Seedream 5.0 pro image per character,
run by `creative-worker` under ADR 41 — its own vendor pool (`byteplus:seedream-5-0-pro`,
never a Seedance slot), the price guard at the paid boundary, the result kept before any
further work, an idempotent finish. Mirrors `creative.seasonal_ai`.

Seedream answers SYNCHRONOUSLY (the image is in the POST's response, ~30 s): there is no
vendor task to poll. So:

**submit** — reads the character tenant-side (the worker role cannot, ADR 41) and refuses
anything but a `pending` character. Price guard: the quote of the versioned table (`v9`,
`per_sticker_character`) against the brand's remaining monthly dollar cap — over it (or no
cap configured) the character fails (`budget_cap` / `no_budget_cap`), its creation is given
back, `PriceGuardRefused` is raised and nothing reaches BytePlus. Then, BEFORE the POST,
`start_request` stamps `vendor_request_started_at` on the row (only once): a later claim of
the same job that finds it stamped never posts again — it fails the character as
`uncertain` (creation given back) and books the quote as spent, because the first POST may
have been billed («never paid twice», and an overcount beats an undercount against a cap).
The product photo goes as a JPEG data URL (never a public link). A 429 (`VendorBusy`) clears
the stamp and is re-raised (the runner defers: nothing was created). A dropped connection
books the quote (the image may exist and be billed) and fails the character. Any other
vendor error (moderation, 4xx) is not billed (Seedream bills only images it returns) and
fails the character. On success: the REAL cost (`usage.generated_images` × the table's 1K
price) is booked in `creative_usage_events` + the brand's monthly spend under an id derived
from the character (a second booking adds nothing), noted on the row, and the raw image is
written to R2 (`…/personajes/{id}-2.webp`, retried) — all before `submit` returns the
synthetic task id `seedream-sync:{character_id}`, which the runner records.

**poll** — the task ended with the POST: `succeeded` at once.

**finish** (idempotent) — a character no longer `pending` is left alone. `failed` / no task:
the character fails (creation given back). `succeeded`: the raw image is read back from R2,
cut out (`kawaii.cut_out`, numpy chroma key), the cut-out written (`…-1.webp`) and the
character marked `ready` — a cut that finds no character fails it (`no_character`, creation
given back; the USD cost stays booked: the call was paid).
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid5

from qualify_creative.enums import GenerationTask
from qualify_creative.providers import GenerationRequest, PricingTable, RenderedPrompt
from qualify_creative.seasonal.kawaii import (
    KAWAII_MODEL,
    KAWAII_PRICING_VERSION,
    KAWAII_PROMPT_VERSION,
    CharacterError,
    character_params,
    character_quote_usd,
    character_real_cost_usd,
    cut_out,
    pricing_table,
    raw_webp,
)
from qualify_creative.seasonal.look import load_image

from qualify_api.creative.product_stickers import (
    CHARACTER_FOLDER,
    CUT_FILE,
    RAW_FILE,
    STATUS_PENDING,
    CharacterChanged,
    StickerCharacter,
)
from qualify_api.creative.worker.executor import SUCCEEDED, JobContext, TaskPoll

logger = logging.getLogger("qualify_api.creative.product_sticker_ai")

KIND_STICKER_CHARACTER = "sticker_character"
PROVIDER = "byteplus"
#: The platform key of the generator's Seedream images (`PlatformKeyResolver`).
CREDENTIAL_PROVIDER = "seedream"
#: `creative_usage_events.unit` of a character booking (draft-less, like the seasonal AI).
CHARACTER_USAGE_UNIT = "sticker_character_image"
TASK_PREFIX = "seedream-sync:"
#: Reasons on the row (`product_stickers.REASON_TEXT` words them for the owner).
BUDGET_CAP = "budget_cap"
NO_BUDGET_CAP = "no_budget_cap"
VENDOR_FAILED = "vendor_failed"
UNCERTAIN = "uncertain"
LOST_RESULT = "lost_result"
NO_SOURCE = "no_source"
#: The largest product photo read into memory.
MAX_PHOTO_BYTES = 25 * 1024 * 1024
#: The largest raw image read back (a 1K lossless WebP is ~1–2 MB).
MAX_RAW_BYTES = 30 * 1024 * 1024
PUT_ATTEMPTS = 3
PUT_BACKOFF_SECONDS = 2.0
#: Each Seedream POST waits at most this (two drops at most: ≤ 4 min < the 5 min lease).
REQUEST_TIMEOUT_SECONDS = 120.0
_USAGE_NAMESPACE = UUID("8a3e1f52-6c0d-4b7e-9f21-25017372a1d0")


class PriceGuardRefused(Exception):
    """Over the brand's remaining budget (or no cap): nothing was sent to BytePlus."""


class SubmissionAborted(Exception):
    """The paid POST had already been started by an earlier claim: not posted again."""


def usage_event_id(character_id: UUID) -> UUID:
    """The `creative_usage_events.id` of a character's call: one character, one booking."""
    return uuid5(_USAGE_NAMESPACE, f"sticker-character:{character_id}")


def task_id_of(character_id: UUID) -> str:
    return f"{TASK_PREFIX}{character_id}"


@dataclass(frozen=True)
class Budget:
    remaining_usd: Decimal


# --- seams --------------------------------------------------------------------------------


class CharacterReads(Protocol):
    def character(self, tenant_id: UUID, character_id: UUID) -> StickerCharacter | None: ...

    def photo_key(
        self, tenant_id: UUID, brand_id: UUID, product_id: UUID | None, media_id: UUID
    ) -> str | None:
        """The product photo's object key — re-checked to be THIS brand's image."""
        ...

    def budget(self, tenant_id: UUID, brand_id: UUID) -> Budget | None: ...


class CharacterRequests(Protocol):
    def start_request(self, *, tenant_id: UUID, character_id: UUID, at: datetime) -> bool: ...

    def clear_request(self, *, tenant_id: UUID, character_id: UUID) -> None: ...


class CharacterMarks(Protocol):
    def mark_character_ready(self, **kwargs: Any) -> Any: ...

    def mark_character_failed(self, **kwargs: Any) -> Any: ...

    def note_paid(self, **kwargs: Any) -> Any: ...


class CharacterObjects(Protocol):
    def open_object(self, tenant_id: UUID, object_key: str) -> Any: ...

    def put_seasonal_media(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        season_key: str,
        media_id: UUID,
        extension: str,
        fileobj: Any,
        content_type: str,
        attempt: int = 1,
    ) -> str: ...


class UsageLedger(Protocol):
    def record(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        character_id: UUID,
        model_id: str,
        pieces: int,
        cost_usd: Decimal,
        pricing_version: str,
        occurred_at: datetime,
    ) -> bool: ...


class SeedreamAdapter(Protocol):
    def generate(self, request: GenerationRequest, *, api_key: str) -> Any: ...


# --- the executor -------------------------------------------------------------------------


def _request(params: dict[str, object]) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.PRODUCT_IMAGE,
        rendered_prompt=RenderedPrompt(
            stable_prefix="", volatile_suffix=str(params["prompt"]), prefix_fingerprint=""
        ),
        params=params,
    )


def _is_disconnect(exc: Exception) -> bool:
    """The connection dropped mid-generation: the image may exist and be billed."""
    from qualify_creative.adapters.byteplus_ark import SeedreamDisconnected  # noqa: PLC0415

    return isinstance(exc, SeedreamDisconnected)


def _maybe_billed(exc: Exception) -> bool:
    """The image may exist and be billed: a dropped connection, or a 5xx from the gateway
    (Ark may already be generating). An overcount beats an undercount against a cap."""
    from qualify_creative.adapters.byteplus_ark import ArkAPIError  # noqa: PLC0415

    if _is_disconnect(exc):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(exc, ArkAPIError) and isinstance(status, int) and status >= 500


def _is_busy(exc: Exception) -> bool:
    from qualify_creative.adapters.byteplus_ark import VendorBusy  # noqa: PLC0415

    return isinstance(exc, VendorBusy)


class ProductCharacterExecutor:
    """`JobExecutor` for `sticker_character` jobs (module docstring)."""

    def __init__(
        self,
        *,
        adapter: SeedreamAdapter,
        reads: CharacterReads,
        requests: CharacterRequests,
        marks: CharacterMarks,
        objects: CharacterObjects,
        ledger: UsageLedger,
        api_key: Callable[[UUID, UUID], str],
        pricing: PricingTable | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] | None = None,
        put_attempts: int = PUT_ATTEMPTS,
    ) -> None:
        import time  # noqa: PLC0415

        self._adapter = adapter
        self._reads = reads
        self._requests = requests
        self._marks = marks
        self._objects = objects
        self._ledger = ledger
        self._api_key = api_key
        self._pricing = pricing or pricing_table()
        self._clock = clock
        self._sleep = sleep or time.sleep
        self._put_attempts = max(1, put_attempts)

    # -- the contract --------------------------------------------------------------------

    def submit(self, job: JobContext) -> str:
        character = self._runnable(job)
        if character is None:
            raise ValueError("not a pending product sticker character")
        quote = character_quote_usd(self._pricing)
        budget = self._reads.budget(character.tenant_id, character.brand_id)
        if budget is None:
            self._fail(character, NO_BUDGET_CAP)
            raise PriceGuardRefused("no monthly cap configured for the brand")
        if quote > budget.remaining_usd:
            self._fail(character, BUDGET_CAP)
            logger.info(
                "product_sticker_ai.price_guard tenant=%s character=%s quote=%s remaining=%s",
                character.tenant_id,
                character.id,
                quote,
                budget.remaining_usd,
            )
            raise PriceGuardRefused(f"quote {quote} over remaining {budget.remaining_usd}")
        photo = self._photo(character)
        if not self._requests.start_request(
            tenant_id=character.tenant_id, character_id=character.id, at=self._clock()
        ):
            # an earlier claim started the paid POST and died. If its image reached R2 the
            # call was paid and booked: finish cuts it (review of m-25017372)
            if self._has_raw(character):
                return task_id_of(character.id)
            # otherwise it may have been billed: book the quote, never post again
            self._book(character, 0, quote)
            self._fail(character, UNCERTAIN)
            raise SubmissionAborted(str(character.id))
        key = self._api_key(character.tenant_id, character.brand_id)
        try:
            result = self._adapter.generate(_request(character_params(photo)), api_key=key)
        except Exception as exc:
            if _is_busy(exc):  # nothing created, nothing billed: the runner defers it
                self._requests.clear_request(
                    tenant_id=character.tenant_id, character_id=character.id
                )
                raise
            if _maybe_billed(exc):
                self._book(character, 0, quote)
            self._fail(character, VENDOR_FAILED)
            logger.warning(
                "product_sticker_ai.vendor_failed character=%s error=%s",
                character.id,
                type(exc).__name__,
            )
            raise
        pieces = int(getattr(result.usage, "pieces", 0) or 0)
        images = (result.payload or {}).get("images") or []
        cost = character_real_cost_usd(pieces or (1 if images else 0), self._pricing)
        self._book(character, pieces, cost)
        task_id = task_id_of(character.id)
        self._marks.note_paid(
            tenant_id=character.tenant_id,
            brand_id=character.brand_id,
            character_id=character.id,
            cost_usd=cost,
            vendor_request_id=task_id,
        )
        if not images:
            self._fail(character, VENDOR_FAILED)
            raise ValueError("Seedream returned no image")
        self._put(character, RAW_FILE, raw_webp(images[0]))
        logger.info(
            "product_sticker_ai.generated tenant=%s character=%s model=%s pieces=%d cost=%s "
            "prompt=%s",
            character.tenant_id,
            character.id,
            KAWAII_MODEL,
            pieces,
            cost,
            KAWAII_PROMPT_VERSION,
        )
        return task_id

    def give_up(self, job: JobContext) -> None:
        """The runner ran out of finish attempts: a character still `pending` fails and its
        creation is given back (never left charged and waiting for ever)."""
        character = self._runnable(job)
        if character is not None:
            self._fail(character, VENDOR_FAILED)

    def poll(self, job: JobContext, vendor_task_id: str) -> TaskPoll:
        return TaskPoll(status=SUCCEEDED, next_poll_seconds=0.0)

    def finish(self, job: JobContext, vendor_task_id: str | None, status: str) -> None:
        character = self._runnable(job)
        if character is None:
            return  # settled meanwhile: nothing to do
        if status != SUCCEEDED or vendor_task_id is None:
            self._fail(character, VENDOR_FAILED)
            return
        raw_key = self._key(character, RAW_FILE)
        try:
            stream = self._objects.open_object(character.tenant_id, raw_key)
        except Exception as exc:  # noqa: BLE001 — missing: the result is lost, never re-paid
            from qualify_shared.objects.gate import ObjectNotFound  # noqa: PLC0415

            if isinstance(exc, ObjectNotFound | KeyError | FileNotFoundError):
                self._fail(character, LOST_RESULT)
                return
            raise  # an R2 hiccup: the runner calls finish again
        try:
            raw = stream.read(MAX_RAW_BYTES + 1)
        finally:
            getattr(stream, "close", lambda: None)()
        try:
            cut = cut_out(raw)
        except CharacterError as exc:
            self._fail(character, exc.code)
            return
        object_key = self._put(character, CUT_FILE, cut.data)
        try:
            self._marks.mark_character_ready(
                tenant_id=character.tenant_id,
                brand_id=character.brand_id,
                character_id=character.id,
                object_key=object_key,
                raw_object_key=raw_key,
                width=cut.width,
                height=cut.height,
            )
        except CharacterChanged:
            logger.info("product_sticker_ai.settled_meanwhile character=%s", character.id)
            return
        logger.info(
            "product_sticker_ai.ready tenant=%s character=%s size=%dx%d coverage=%s bg=%s",
            character.tenant_id,
            character.id,
            cut.width,
            cut.height,
            cut.coverage,
            cut.background,
        )

    # -- helpers -------------------------------------------------------------------------

    def _runnable(self, job: JobContext) -> StickerCharacter | None:
        character_id = getattr(job, "sticker_character_id", None)
        if job.kind != KIND_STICKER_CHARACTER or character_id is None:
            return None
        found = self._reads.character(job.tenant_id, character_id)
        if found is None or found.status != STATUS_PENDING:
            return None
        return found

    def _photo(self, character: StickerCharacter):  # noqa: ANN202
        key = self._reads.photo_key(
            character.tenant_id,
            character.brand_id,
            character.product_id,
            character.source_media_id,
        )
        if not key:
            self._fail(character, NO_SOURCE)
            raise ValueError("no product photo to draw")
        stream = self._objects.open_object(character.tenant_id, key)
        try:
            data = stream.read(MAX_PHOTO_BYTES + 1)
        finally:
            getattr(stream, "close", lambda: None)()
        if len(data) > MAX_PHOTO_BYTES:
            self._fail(character, NO_SOURCE)
            raise ValueError("photo over the size limit")
        try:
            return load_image(data, rgba=False)
        except Exception:
            self._fail(character, NO_SOURCE)
            raise

    def _has_raw(self, character: StickerCharacter) -> bool:
        try:
            stream = self._objects.open_object(character.tenant_id, self._key(character, RAW_FILE))
        except Exception:  # noqa: BLE001 — not there (or unreadable): treat as absent
            return False
        getattr(stream, "close", lambda: None)()
        return True

    @staticmethod
    def _key(character: StickerCharacter, number: int) -> str:
        from qualify_shared.objects.keys import seasonal_media_key  # noqa: PLC0415

        return seasonal_media_key(
            character.tenant_id, character.brand_id, CHARACTER_FOLDER, character.id, "webp", number
        )

    def _put(self, character: StickerCharacter, number: int, data: bytes) -> str:
        last: Exception | None = None
        for attempt in range(self._put_attempts):
            try:
                return self._objects.put_seasonal_media(
                    character.tenant_id,
                    character.brand_id,
                    CHARACTER_FOLDER,
                    character.id,
                    "webp",
                    io.BytesIO(data),
                    "image/webp",
                    attempt=number,
                )
            except Exception as exc:  # noqa: BLE001 — retried (creative rule 3)
                last = exc
                if attempt + 1 < self._put_attempts:
                    self._sleep(PUT_BACKOFF_SECONDS * (attempt + 1))
        assert last is not None
        raise last

    def _book(self, character: StickerCharacter, pieces: int, cost: Decimal) -> None:
        self._ledger.record(
            tenant_id=character.tenant_id,
            brand_id=character.brand_id,
            character_id=character.id,
            model_id=KAWAII_MODEL,
            pieces=pieces,
            cost_usd=cost,
            pricing_version=getattr(self._pricing, "version", KAWAII_PRICING_VERSION),
            occurred_at=self._clock(),
        )

    def _fail(self, character: StickerCharacter, reason: str) -> None:
        try:
            self._marks.mark_character_failed(
                tenant_id=character.tenant_id,
                brand_id=character.brand_id,
                character_id=character.id,
                reason=reason,
            )
        except CharacterChanged:
            pass


# --- production wiring --------------------------------------------------------------------


class PostgresCharacterReads:
    def character(self, tenant_id: UUID, character_id: UUID) -> StickerCharacter | None:
        from qualify_api.creative.product_stickers import (  # noqa: PLC0415
            PostgresCharacterRepository,
        )

        return PostgresCharacterRepository().get(tenant_id=tenant_id, character_id=character_id)

    def photo_key(
        self, tenant_id: UUID, brand_id: UUID, product_id: UUID | None, media_id: UUID
    ) -> str | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            return session.execute(
                text(
                    "SELECT object_key FROM product_media WHERE id = :id "
                    "AND brand_id = :brand_id AND media_type = 'image'"
                    + (" AND product_id = :product_id" if product_id is not None else "")
                ),
                {"id": media_id, "brand_id": brand_id, "product_id": product_id},
            ).scalar_one_or_none()

    def budget(self, tenant_id: UUID, brand_id: UUID) -> Budget | None:
        from qualify_api.creative.service import PostgresContentRepository  # noqa: PLC0415

        state = PostgresContentRepository().budget_state(tenant_id=tenant_id, brand_id=brand_id)
        return Budget(remaining_usd=state.remaining_usd) if state is not None else None


class PostgresCharacterUsageLedger:
    """`creative_usage_events` (draft-less, unit `CHARACTER_USAGE_UNIT`) + the brand's
    `creative_engine_config.budget_spent_usd`, in ONE `tenant_session` — so the monthly
    dollar cap counts the characters. Once per character (the event id is derived from it)."""

    def record(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        character_id: UUID,
        model_id: str,
        pieces: int,
        cost_usd: Decimal,
        pricing_version: str,
        occurred_at: datetime,
    ) -> bool:
        from qualify_creative.enums import PaidBy  # noqa: PLC0415
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        from qualify_api.creative import models as orm  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            booked = session.scalar(
                insert(orm.CreativeUsageEvent)
                .values(
                    id=usage_event_id(character_id),
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    draft_id=None,
                    provider=PROVIDER,
                    model_id=model_id,
                    unit=CHARACTER_USAGE_UNIT,
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_creation_tokens=0,
                    pieces=pieces,
                    cost_usd=cost_usd,
                    paid_by=PaidBy.PLATFORM.value,
                    pricing_table_version=pricing_version,
                    occurred_at=occurred_at,
                )
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(orm.CreativeUsageEvent.id)
            )
            if booked is None:
                return False
            config = session.scalar(
                select(orm.CreativeEngineConfig)
                .where(orm.CreativeEngineConfig.brand_id == brand_id)
                .with_for_update()
            )
            if config is not None:
                config.budget_spent_usd = Decimal(config.budget_spent_usd) + cost_usd
        return True


def production_character_executor() -> ProductCharacterExecutor:
    import os  # noqa: PLC0415

    from qualify_creative.adapters.byteplus_ark import SeedreamImageAdapter  # noqa: PLC0415
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    from qualify_api.creative.composition import (  # noqa: PLC0415
        ARK_BASE_URL,
        ARK_BASE_URL_ENV,
        PlatformKeyResolver,
    )
    from qualify_api.creative.product_stickers import (  # noqa: PLC0415
        PostgresCharacterRepository,
        production_product_sticker_service,
    )

    keys = PlatformKeyResolver()
    return ProductCharacterExecutor(
        adapter=SeedreamImageAdapter(
            model=KAWAII_MODEL,
            base_url=os.environ.get(ARK_BASE_URL_ENV) or ARK_BASE_URL,
            request_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        ),
        reads=PostgresCharacterReads(),
        requests=PostgresCharacterRepository(),
        marks=production_product_sticker_service(),
        objects=ObjectGate(R2ObjectStore(R2Settings.from_env())),
        ledger=PostgresCharacterUsageLedger(),
        api_key=lambda tenant, brand: (
            keys.resolve(tenant_id=tenant, brand_id=brand, provider=CREDENTIAL_PROVIDER).api_key
        ),
    )


class UnknownKindExecutor:
    """The Seedream pool's default: only `sticker_character` jobs ride it; anything else
    is refused before any paid call (the runner fails the job)."""

    def submit(self, job: JobContext) -> str:
        raise ValueError(f"the Seedream pool runs no {job.kind!r} jobs")

    def poll(self, job: JobContext, vendor_task_id: str) -> TaskPoll:
        return TaskPoll(status="unknown")

    def finish(self, job: JobContext, vendor_task_id: str | None, status: str) -> None:
        return None
