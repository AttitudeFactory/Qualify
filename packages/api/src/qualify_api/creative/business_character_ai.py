"""The paid step of a business character option (m-25129385): ONE Seedream 5.0 pro image,
run by `creative-worker` under ADR 41 on the Seedream pool (`byteplus:seedream-5-0-pro`,
never a Seedance slot). Mirrors `product_sticker_ai` (m-25017372) — same guarantees:

**submit** — reads the option tenant-side and refuses anything but a `pending` one. With
the switch off (`business_characters.characters_unavailable_reason`) the option fails
(`switched_off`) before any spend. Price guard: the option's quote from the versioned table
(`v10`, one 1080x1920 image, US$0.045) against the brand's remaining monthly dollar cap —
only a configured cap with `hard_stop_on_cap` refuses: the option fails (`budget_cap`),
`PriceGuardRefused` is raised and nothing reaches BytePlus. Drawing charges no creaciones
(Deivid, P2). BEFORE the POST `start_request` stamps the row once: a later claim that finds
it stamped never posts again — if the image already reached R2 it finishes, else it books
the quote as spent and fails the option (`uncertain`). A 429 clears the stamp and is
re-raised (the runner defers). A dropped connection or a 5xx books the quote. Moderation
fails the option as `moderated` (not billed). On success: the REAL cost
(`usage.generated_images` x the table's 1K price) is booked once in `creative_usage_events`
+ the brand's monthly spend, noted on the row, and the image is written to R2 EXACTLY as
received (`seasonal/{tenant}/{brand}/personajes-negocio/{id}.jpg`, 3 attempts) — Seedance
2.x takes a face only from its own account's Seedream output, unmodified. An R2 write that
keeps failing after the paid call fails the option (`lost_result`; the cost stays booked);
nothing the business already saved is touched. Then the option is `ready`, with its size,
sha256, model revision and `drawn_at`.

**poll** — the task ended with the POST: `succeeded` at once. **finish** — idempotent: a
`pending` option whose image is in R2 (a claim that died after the write) is marked ready;
anything else not succeeded fails it.
"""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid5

from qualify_creative.enums import GenerationTask
from qualify_creative.providers import GenerationRequest, PricingTable, RenderedPrompt

from qualify_api.creative.business_characters import (
    IMAGE_SIZE,
    MODEL_ID,
    PRICING_VERSION,
    PROMPT_VERSION,
    REASON_BUDGET_CAP,
    REASON_LOST_RESULT,
    REASON_MODERATED,
    REASON_SWITCHED_OFF,
    REASON_UNCERTAIN,
    REASON_VENDOR_FAILED,
    STATUS_PENDING,
    BusinessCharacter,
    CharacterChanged,
    characters_unavailable_reason,
    option_quote_usd,
    pricing_table,
)
from qualify_api.creative.job_queue import KIND_BUSINESS_CHARACTER
from qualify_api.creative.worker.executor import SUCCEEDED, JobContext, TaskPoll

logger = logging.getLogger("qualify_api.creative.business_character_ai")

PROVIDER = "byteplus"
#: The platform key of the generator's Seedream images (`PlatformKeyResolver`).
CREDENTIAL_PROVIDER = "seedream"
#: `creative_usage_events.unit` of one option's booking.
USAGE_UNIT = "business_character_image"
TASK_PREFIX = "seedream-sync:"
CONTENT_TYPE = "image/jpeg"
MAX_IMAGE_BYTES = 30 * 1024 * 1024
PUT_ATTEMPTS = 3
PUT_BACKOFF_SECONDS = 2.0
#: Each Seedream POST waits at most this (two drops at most: < the 5 min lease).
REQUEST_TIMEOUT_SECONDS = 120.0
_USAGE_NAMESPACE = UUID("5b1c7e2a-9d40-4f6e-8a31-25129385c0de")
_MODERATION_MARKERS = ("SensitiveContent", "PrivacyInformation", "InputImageSensitive")


class PriceGuardRefused(Exception):
    """Over the brand's hard monthly cap: nothing was sent to BytePlus."""


class SubmissionAborted(Exception):
    """The paid POST had already been started by an earlier claim: not posted again."""


class SwitchedOff(Exception):
    """The characters are switched off: nothing was sent to BytePlus."""


def usage_event_id(character_id: UUID) -> UUID:
    """The `creative_usage_events.id` of an option's call: one option, one booking."""
    return uuid5(_USAGE_NAMESPACE, f"business-character:{character_id}")


def task_id_of(character_id: UUID) -> str:
    return f"{TASK_PREFIX}{character_id}"


def real_cost_usd(pieces: int, pricing: PricingTable) -> Decimal:
    from qualify_creative.pricing import seedream_image_cost  # noqa: PLC0415

    return seedream_image_cost(
        pricing, model_id=MODEL_ID, size=IMAGE_SIZE, references=0, pieces=pieces
    )


@dataclass(frozen=True)
class Budget:
    remaining_usd: Decimal
    hard_stop: bool = True


# --- seams --------------------------------------------------------------------------------


class OptionReads(Protocol):
    def character(self, tenant_id: UUID, character_id: UUID) -> BusinessCharacter | None: ...

    def budget(self, tenant_id: UUID, brand_id: UUID) -> Budget | None: ...


class OptionRequests(Protocol):
    def start_request(self, *, tenant_id: UUID, character_id: UUID, at: datetime) -> bool: ...

    def clear_request(self, *, tenant_id: UUID, character_id: UUID) -> None: ...


class OptionMarks(Protocol):
    def mark_ready(self, **kwargs: Any) -> Any: ...

    def mark_failed(self, **kwargs: Any) -> Any: ...

    def note_paid(self, **kwargs: Any) -> Any: ...


class OptionObjects(Protocol):
    def put_business_character(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        character_id: UUID,
        fileobj: Any,
        content_type: str,
    ) -> str: ...

    def open_business_character(self, tenant_id: UUID, brand_id: UUID, object_key: str) -> Any: ...


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


def _request(prompt: str) -> GenerationRequest:
    params: dict[str, object] = {"model": MODEL_ID, "prompt": prompt, "size": IMAGE_SIZE}
    return GenerationRequest(
        task=GenerationTask.PRODUCT_IMAGE,
        rendered_prompt=RenderedPrompt(
            stable_prefix="", volatile_suffix=prompt, prefix_fingerprint=""
        ),
        params=params,
    )


def _maybe_billed(exc: Exception) -> bool:
    """The image may exist and be billed: a dropped connection, or a 5xx from the gateway.
    An overcount beats an undercount against a cap."""
    from qualify_creative.adapters.byteplus_ark import (  # noqa: PLC0415
        ArkAPIError,
        SeedreamDisconnected,
    )

    if isinstance(exc, SeedreamDisconnected):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(exc, ArkAPIError) and isinstance(status, int) and status >= 500


def _is_busy(exc: Exception) -> bool:
    from qualify_creative.adapters.byteplus_ark import VendorBusy  # noqa: PLC0415

    return isinstance(exc, VendorBusy)


def _is_moderated(exc: Exception) -> bool:
    text = f"{getattr(exc, 'code', '') or ''} {exc}"
    return any(marker in text for marker in _MODERATION_MARKERS)


def _jpeg_size(data: bytes) -> tuple[int | None, int | None]:
    """Width and height read from the bytes, never re-encoding them."""
    try:
        from PIL import Image  # noqa: PLC0415

        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:  # noqa: BLE001 — the size is informative only
        return None, None


class BusinessCharacterExecutor:
    """`JobExecutor` for `business_character` jobs (module docstring)."""

    def __init__(
        self,
        *,
        adapter: SeedreamAdapter,
        reads: OptionReads,
        requests: OptionRequests,
        marks: OptionMarks,
        objects: OptionObjects,
        ledger: UsageLedger,
        api_key: Callable[[UUID, UUID], str],
        pricing: PricingTable | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] | None = None,
        put_attempts: int = PUT_ATTEMPTS,
        env: Mapping[str, str] | None = None,
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
        self._env = env

    # -- the contract --------------------------------------------------------------------

    def submit(self, job: JobContext) -> str:
        option = self._runnable(job)
        if option is None:
            raise ValueError("not a pending business character option")
        if characters_unavailable_reason(self._env) is not None:
            self._fail(option, REASON_SWITCHED_OFF)
            raise SwitchedOff(str(option.id))
        quote = option_quote_usd(self._pricing)
        budget = self._reads.budget(option.tenant_id, option.brand_id)
        if budget is not None and budget.hard_stop and quote > budget.remaining_usd:
            self._fail(option, REASON_BUDGET_CAP)
            logger.info(
                "business_character_ai.price_guard tenant=%s option=%s quote=%s remaining=%s",
                option.tenant_id,
                option.id,
                quote,
                budget.remaining_usd,
            )
            raise PriceGuardRefused(f"quote {quote} over remaining {budget.remaining_usd}")
        if not self._requests.start_request(
            tenant_id=option.tenant_id, character_id=option.id, at=self._clock()
        ):
            # an earlier claim started the paid POST and died: if its image reached R2 it
            # was paid and booked — finish marks it ready; else book the quote, never repost
            if self._stored(option) is not None:
                return task_id_of(option.id)
            self._book(option, 0, quote)
            self._fail(option, REASON_UNCERTAIN)
            raise SubmissionAborted(str(option.id))
        key = self._api_key(option.tenant_id, option.brand_id)
        try:
            result = self._adapter.generate(_request(option.prompt), api_key=key)
        except Exception as exc:
            if _is_busy(exc):  # nothing created, nothing billed: the runner defers it
                self._requests.clear_request(tenant_id=option.tenant_id, character_id=option.id)
                raise
            if _maybe_billed(exc):
                self._book(option, 0, quote)
            self._fail(option, REASON_MODERATED if _is_moderated(exc) else REASON_VENDOR_FAILED)
            logger.warning(
                "business_character_ai.vendor_failed option=%s error=%s",
                option.id,
                type(exc).__name__,
            )
            raise
        payload = result.payload if isinstance(result.payload, Mapping) else {}
        images = list(payload.get("images") or ())
        pieces = int(getattr(result.usage, "pieces", 0) or 0) or (1 if images else 0)
        cost = real_cost_usd(pieces, self._pricing)
        self._book(option, pieces, cost)
        task_id = task_id_of(option.id)
        self._marks.note_paid(
            tenant_id=option.tenant_id,
            character_id=option.id,
            cost_usd=cost,
            vendor_request_id=task_id,
        )
        if not images:
            self._fail(option, REASON_VENDOR_FAILED)
            raise ValueError("Seedream returned no image")
        data = bytes(images[0])
        try:
            object_key = self._put(option, data)
        except Exception:
            self._fail(option, REASON_LOST_RESULT)
            raise
        self._ready(option, object_key, data, getattr(result, "model_revision", None))
        logger.info(
            "business_character_ai.drawn tenant=%s option=%s model=%s pieces=%d cost=%s prompt=%s",
            option.tenant_id,
            option.id,
            MODEL_ID,
            pieces,
            cost,
            PROMPT_VERSION,
        )
        return task_id

    def give_up(self, job: JobContext) -> None:
        """The runner ran out of finish attempts: a still `pending` option fails."""
        option = self._runnable(job)
        if option is not None:
            self._fail(option, REASON_VENDOR_FAILED)

    def poll(self, job: JobContext, vendor_task_id: str) -> TaskPoll:
        return TaskPoll(status=SUCCEEDED, next_poll_seconds=0.0)

    def finish(self, job: JobContext, vendor_task_id: str | None, status: str) -> None:
        option = self._runnable(job)
        if option is None:
            return  # settled by submit (ready or failed) or meanwhile
        if status != SUCCEEDED or vendor_task_id is None:
            self._fail(option, REASON_VENDOR_FAILED)
            return
        stored = self._stored(option)
        if stored is None:
            self._fail(option, REASON_LOST_RESULT)
            return
        object_key, data = stored
        self._ready(option, object_key, data, None)

    # -- helpers -------------------------------------------------------------------------

    def _runnable(self, job: JobContext) -> BusinessCharacter | None:
        character_id = getattr(job, "business_character_id", None)
        if job.kind != KIND_BUSINESS_CHARACTER or character_id is None:
            return None
        found = self._reads.character(job.tenant_id, character_id)
        if found is None or found.status != STATUS_PENDING:
            return None
        return found

    @staticmethod
    def _key(option: BusinessCharacter) -> str:
        from qualify_shared.objects.keys import business_character_key  # noqa: PLC0415

        return business_character_key(option.tenant_id, option.brand_id, option.id)

    def _stored(self, option: BusinessCharacter) -> tuple[str, bytes] | None:
        key = self._key(option)
        try:
            stream = self._objects.open_business_character(option.tenant_id, option.brand_id, key)
        except Exception:  # noqa: BLE001 — not there (or unreadable): treat as absent
            return None
        try:
            data = stream.read(MAX_IMAGE_BYTES + 1)
        finally:
            getattr(stream, "close", lambda: None)()
        if not data or len(data) > MAX_IMAGE_BYTES:
            return None
        return key, bytes(data)

    def _put(self, option: BusinessCharacter, data: bytes) -> str:
        last: Exception | None = None
        for attempt in range(self._put_attempts):
            try:
                return self._objects.put_business_character(
                    option.tenant_id, option.brand_id, option.id, io.BytesIO(data), CONTENT_TYPE
                )
            except Exception as exc:  # noqa: BLE001 — retried (creative rule 3)
                last = exc
                if attempt + 1 < self._put_attempts:
                    self._sleep(PUT_BACKOFF_SECONDS * (attempt + 1))
        assert last is not None
        raise last

    def _ready(
        self, option: BusinessCharacter, object_key: str, data: bytes, revision: str | None
    ) -> None:
        width, height = _jpeg_size(data)
        try:
            self._marks.mark_ready(
                tenant_id=option.tenant_id,
                character_id=option.id,
                object_key=object_key,
                content_type=CONTENT_TYPE,
                width=width,
                height=height,
                byte_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                model_revision=revision or MODEL_ID,
                drawn_at=self._clock(),
            )
        except CharacterChanged:
            logger.info("business_character_ai.settled_meanwhile option=%s", option.id)

    def _book(self, option: BusinessCharacter, pieces: int, cost: Decimal) -> None:
        self._ledger.record(
            tenant_id=option.tenant_id,
            brand_id=option.brand_id,
            character_id=option.id,
            model_id=MODEL_ID,
            pieces=pieces,
            cost_usd=cost,
            pricing_version=getattr(self._pricing, "version", PRICING_VERSION),
            occurred_at=self._clock(),
        )

    def _fail(self, option: BusinessCharacter, reason: str) -> None:
        try:
            self._marks.mark_failed(
                tenant_id=option.tenant_id, character_id=option.id, reason=reason
            )
        except CharacterChanged:
            pass


# --- production wiring --------------------------------------------------------------------


class PostgresOptionReads:
    def character(self, tenant_id: UUID, character_id: UUID) -> BusinessCharacter | None:
        from qualify_api.creative.business_characters import (  # noqa: PLC0415
            PostgresCharacterRepository,
        )

        return PostgresCharacterRepository().get(tenant_id=tenant_id, character_id=character_id)

    def budget(self, tenant_id: UUID, brand_id: UUID) -> Budget | None:
        from qualify_api.creative.service import PostgresContentRepository  # noqa: PLC0415

        state = PostgresContentRepository().budget_state(tenant_id=tenant_id, brand_id=brand_id)
        if state is None:
            return None
        return Budget(remaining_usd=state.remaining_usd, hard_stop=state.hard_stop)


class PostgresOptionUsageLedger:
    """`creative_usage_events` (draft-less, unit `USAGE_UNIT`) + the brand's
    `creative_engine_config.budget_spent_usd`, in ONE `tenant_session`, once per option."""

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
                    unit=USAGE_UNIT,
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


def production_business_character_executor() -> BusinessCharacterExecutor:
    import os  # noqa: PLC0415

    from qualify_creative.adapters.byteplus_ark import SeedreamImageAdapter  # noqa: PLC0415
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    from qualify_api.creative.business_characters import (  # noqa: PLC0415
        PostgresCharacterRepository,
        production_business_character_service,
    )
    from qualify_api.creative.composition import (  # noqa: PLC0415
        ARK_BASE_URL,
        ARK_BASE_URL_ENV,
        PlatformKeyResolver,
    )

    keys = PlatformKeyResolver()
    return BusinessCharacterExecutor(
        adapter=SeedreamImageAdapter(
            model=MODEL_ID,
            base_url=os.environ.get(ARK_BASE_URL_ENV) or ARK_BASE_URL,
            request_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        ),
        reads=PostgresOptionReads(),
        requests=PostgresCharacterRepository(),
        marks=production_business_character_service(),
        objects=ObjectGate(R2ObjectStore(R2Settings.from_env())),
        ledger=PostgresOptionUsageLedger(),
        api_key=lambda tenant, brand: (
            keys.resolve(tenant_id=tenant, brand_id=brand, provider=CREDENTIAL_PROVIDER).api_key
        ),
    )
