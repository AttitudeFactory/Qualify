"""«Crear con IA» for the seasonal library (m-24976893): one Seedance video per medium
attempt, run by `creative-worker` under ADR 41 — the shared Seedance slots, the price
guard at the paid boundary, the vendor task id recorded before any wait.

A seasonal AI job is a `creative_jobs` row of kind `seasonal_video` (migration 0143)
whose subject is `(seasonal_media_id, attempt)` instead of a draft. It rides the Seedance
pool (`SEASONAL_AI_POOL` = `job_queue.SEEDANCE_POOL`) so the account's 10-task cap counts
it like any generator job; `KindRoutedExecutor` sends it to `SeasonalAiVideoExecutor`.

**submit** — reads the row tenant-side (the worker role cannot: ADR 41 keeps the subject
out of its reach), refuses anything but the row's CURRENT `pending` attempt of
`ai-seedance`, loads the ONE approved photo piece (`source_ref`, re-checked to be this
brand's approved photo), prices the request with the versioned table and applies the
price guard: an estimate over the brand's remaining monthly budget marks the row
`failed` with `budget_cap` and raises `PriceGuardRefused` — nothing reaches BytePlus. The
photo goes as a JPEG data URL (never a public link). The task id is written on the job by
the observer the moment BytePlus accepts it (`SubmissionRecorder`), so a crash never leads
to a second paid call: the runner polls a job that has a task id, never re-submits it.

**poll** — one read of the task by id.

**finish** (idempotent) — a row no longer `pending` on this attempt is left alone. A
failed / expired / cancelled task (not billed by BytePlus) marks the row `failed`
(`vendor_failed`). A succeeded one: the clip is streamed to a temp file, re-encoded like
recipe B (`clip_from_video`: silent, 720 px, Main without B-frames, ≤ 1 MB target), stored
with `put_seasonal_media(attempt)`, its REAL cost (the task's billed tokens × the table's
rate) written to `creative_usage_events` and added to the brand's monthly spend, then
`mark_ready(cost_usd=<that same cost>)`. A `StaleAttempt` / `WrongState` (the owner asked
for another, or the row settled meanwhile) drops the result and deletes the file just
written. A transient post-process or storage error raises: the runner calls `finish`
again (polling the SAME task), never re-submitting.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from qualify_creative.adapters.byteplus_ark import video_cost_usd
from qualify_creative.enums import GenerationTask
from qualify_creative.providers import GenerationRequest, PricingTable, RenderedPrompt
from qualify_creative.seasonal import RecipeError
from qualify_creative.seasonal.ai import (
    AI_PRICING_VERSION,
    AI_PROMPT_VERSION,
    AI_VIDEO_RESOLUTION,
    DEFAULT_AI_VIDEO_MODEL,
    ai_video_params,
    estimate_ai_video_cost_usd,
    first_frame_data_url,
    pricing_table,
    ratio_for,
)
from qualify_creative.seasonal.errors import NO_SOURCE
from qualify_creative.seasonal.look import load_image
from qualify_creative.seasonal.video import clip_from_video

from qualify_api.creative.worker.executor import SUCCEEDED, JobContext, TaskPoll
from qualify_api.whatsapp.seasonal import StaleAttempt, WrongState

logger = logging.getLogger("qualify_api.creative.seasonal_ai")

KIND_SEASONAL_VIDEO = "seasonal_video"
AI_RECIPE = "ai-seedance"
PIPELINE_VERSION_AI = "seasonal-ai-1"
PROVIDER = "byteplus"
CREDENTIAL_PROVIDER = "seedance"

#: Typed reasons on the row (`mark_failed`) — the screen turns them into words.
BUDGET_CAP = "budget_cap"
VENDOR_FAILED = "vendor_failed"
NOT_RUNNABLE = "not_runnable"
#: Spanish for the owner, per reason (`qualify-copy-es`).
REASON_TEXT: dict[str, str] = {
    BUDGET_CAP: "Esta pieza superaría tu tope de gasto.",
    VENDOR_FAILED: "No pudimos crear el video con IA. Puedes pedir otro.",
    NO_SOURCE: "No encontramos la foto aprobada para animar. Elige otra.",
    "too_large": "El video salió muy pesado para WhatsApp. Puedes pedir otro.",
    "ffmpeg_failed": "No pudimos preparar el video. Puedes pedir otro.",
}
#: The largest photo read into memory (a piece image is far below).
MAX_PHOTO_BYTES = 25 * 1024 * 1024
_STUB_FRAME = "data:image/jpeg;base64,"


class PriceGuardRefused(Exception):
    """The estimate is over the brand's remaining budget: nothing was sent to BytePlus."""


@dataclass(frozen=True)
class AiMedium:
    """What the executor needs of the `brand_seasonal_media` row (read tenant-side)."""

    id: UUID
    tenant_id: UUID
    brand_id: UUID
    season_key: str
    kind: str
    recipe: str
    source_kind: str
    source_ref: str
    status: str
    attempt: int


@dataclass(frozen=True)
class Budget:
    remaining_usd: Decimal


# --- seams --------------------------------------------------------------------------------


class AiReads(Protocol):
    def medium(self, tenant_id: UUID, media_id: UUID) -> AiMedium | None: ...

    def piece_image_keys(
        self, tenant_id: UUID, brand_id: UUID, draft_ids: Sequence[UUID]
    ) -> list[str]: ...

    def budget(self, tenant_id: UUID, brand_id: UUID) -> Budget | None:
        """The brand's remaining monthly generation budget (None: no cap configured)."""
        ...


class AiObjects(Protocol):
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

    def delete_seasonal_media(
        self, tenant_id: UUID, brand_id: UUID, object_keys: list[str]
    ) -> None: ...


class AiMarks(Protocol):
    def mark_ready(self, **kwargs: Any) -> Any: ...

    def mark_failed(self, **kwargs: Any) -> Any: ...


class UsageLedger(Protocol):
    def record(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        model_id: str,
        tokens: int,
        cost_usd: Decimal,
        pricing_version: str,
        occurred_at: datetime,
    ) -> None:
        """One `creative_usage_events` row (draft-less) + the brand's monthly spend."""
        ...


class SeedanceAdapter(Protocol):
    def submit(
        self, request: GenerationRequest, *, api_key: str, priority: int | None = None
    ) -> str: ...

    def poll(self, task_id: str, *, api_key: str) -> Any: ...

    def result(self, request: GenerationRequest, state: Any) -> Any: ...

    def poll_delay(self, status: str, queued_for: float) -> float: ...


Downloader = Callable[[str], AbstractContextManager[Path]]


# --- the executor -------------------------------------------------------------------------


def _request(params: dict[str, object]) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.SCENE_VIDEO,
        rendered_prompt=RenderedPrompt(
            stable_prefix="", volatile_suffix=str(params["prompt"]), prefix_fingerprint=""
        ),
        params=params,
    )


class SeasonalAiVideoExecutor:
    """`JobExecutor` for `seasonal_video` jobs (module docstring)."""

    def __init__(
        self,
        *,
        adapter: SeedanceAdapter,
        reads: AiReads,
        objects: AiObjects,
        marks: AiMarks,
        ledger: UsageLedger,
        api_key: Callable[[UUID, UUID], str],
        download: Downloader,
        recorder: Callable[[JobContext], Any] | None = None,
        pricing: PricingTable | None = None,
        model: str = DEFAULT_AI_VIDEO_MODEL,
        tmp_root: Path | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._adapter = adapter
        self._reads = reads
        self._objects = objects
        self._marks = marks
        self._ledger = ledger
        self._api_key = api_key
        self._download = download
        self._recorder = recorder
        self._pricing = pricing or pricing_table()
        self._model = model
        self._tmp_root = tmp_root
        self._clock = clock

    # -- the contract --------------------------------------------------------------------

    def submit(self, job: JobContext) -> str:
        medium = self._runnable(job)
        if medium is None:
            raise ValueError("seasonal job is not the row's current pending AI attempt")
        image = self._photo(medium)
        ratio = ratio_for(image)
        estimate = estimate_ai_video_cost_usd(self._model, ratio=ratio, pricing=self._pricing)
        budget = self._reads.budget(medium.tenant_id, medium.brand_id)
        if budget is not None and estimate > budget.remaining_usd:
            self._fail(medium, BUDGET_CAP)
            logger.info(
                "seasonal_ai.price_guard tenant=%s media=%s estimate=%s remaining=%s",
                medium.tenant_id,
                medium.id,
                estimate,
                budget.remaining_usd,
            )
            raise PriceGuardRefused(f"estimate {estimate} over remaining {budget.remaining_usd}")
        params = ai_video_params(first_frame_data_url(image), ratio, model=self._model)
        request = _request(params)
        if self._recorder is not None:
            from dataclasses import replace  # noqa: PLC0415

            request = replace(request, observer=self._recorder(job))
        key = self._api_key(medium.tenant_id, medium.brand_id)
        return self._adapter.submit(request, api_key=key, priority=job.vendor_priority)

    def poll(self, job: JobContext, vendor_task_id: str) -> TaskPoll:
        key = self._api_key(job.tenant_id, self._brand_of(job))
        state = self._adapter.poll(vendor_task_id, api_key=key)
        return TaskPoll(
            status=str(state.status or "unknown"),
            next_poll_seconds=self._adapter.poll_delay(str(state.status or ""), 0.0),
        )

    def finish(self, job: JobContext, vendor_task_id: str | None, status: str) -> None:
        medium = self._runnable(job)
        if medium is None:
            return  # settled meanwhile (or another attempt): nothing to do
        if status != SUCCEEDED or vendor_task_id is None:
            self._fail(medium, VENDOR_FAILED)
            return
        key = self._api_key(medium.tenant_id, medium.brand_id)
        state = self._adapter.poll(vendor_task_id, api_key=key)
        result = self._adapter.result(
            _request(ai_video_params(_STUB_FRAME, "1:1", model=self._model)), state
        )
        payload = result.payload if isinstance(result.payload, dict) else {}
        url = payload.get("video_url") or result.media_url
        if not url:
            self._fail(medium, VENDOR_FAILED)
            return
        tokens = int(payload.get("tokens") or result.usage.output_tokens or 0)
        cost = self._real_cost(tokens)
        import tempfile  # noqa: PLC0415

        try:
            with (
                self._download(str(url)) as raw,
                tempfile.TemporaryDirectory(
                    prefix="qualify-seasonal-ai-", dir=self._tmp_root
                ) as tmp,
            ):
                clip = clip_from_video(raw, Path(tmp))
                data = clip.path.read_bytes()
        except RecipeError as exc:
            if exc.transient:
                raise
            # the task was paid: its cost is recorded even though the clip is unusable
            self._record(medium, tokens, cost)
            self._fail(medium, exc.code)
            return
        object_key = self._objects.put_seasonal_media(
            medium.tenant_id,
            medium.brand_id,
            medium.season_key,
            medium.id,
            "mp4",
            io.BytesIO(data),
            "video/mp4",
            attempt=medium.attempt,
        )
        # Ledger first (conservative for the price guard: a crash before mark_ready may
        # count a paid task twice on retry, never zero times).
        self._record(medium, tokens, cost)
        try:
            self._marks.mark_ready(
                tenant_id=medium.tenant_id,
                brand_id=medium.brand_id,
                media_id=medium.id,
                attempt=medium.attempt,
                object_key=object_key,
                bytes=len(data),
                width=clip.width,
                height=clip.height,
                duration_ms=clip.duration_ms,
                cost_usd=cost,
            )
        except (StaleAttempt, WrongState):
            self._objects.delete_seasonal_media(medium.tenant_id, medium.brand_id, [object_key])
            logger.info("seasonal_ai.dropped media=%s attempt=%s", medium.id, medium.attempt)
            return
        logger.info(
            "seasonal_ai.ready tenant=%s media=%s model=%s tokens=%d cost=%s prompt=%s",
            medium.tenant_id,
            medium.id,
            self._model,
            tokens,
            cost,
            AI_PROMPT_VERSION,
        )

    # -- helpers -------------------------------------------------------------------------

    def _runnable(self, job: JobContext) -> AiMedium | None:
        media_id = getattr(job, "seasonal_media_id", None)
        if job.kind != KIND_SEASONAL_VIDEO or media_id is None:
            return None
        medium = self._reads.medium(job.tenant_id, media_id)
        if (
            medium is None
            or medium.attempt != getattr(job, "attempt", 0)
            or medium.status not in ("pending",)
            or medium.recipe != AI_RECIPE
            or medium.kind != "video"
        ):
            return None
        return medium

    def _brand_of(self, job: JobContext) -> UUID:
        medium = self._reads.medium(job.tenant_id, getattr(job, "seasonal_media_id", None))
        if medium is None:
            raise ValueError("seasonal job without its row")
        return medium.brand_id

    def _photo(self, medium: AiMedium):  # noqa: ANN202
        try:
            draft_ids = [
                UUID(part.strip()) for part in medium.source_ref.split(",") if part.strip()
            ]
        except ValueError:
            draft_ids = []
        keys = self._reads.piece_image_keys(medium.tenant_id, medium.brand_id, draft_ids[:1])
        if not keys:
            self._fail(medium, NO_SOURCE)
            raise ValueError("no approved photo piece to animate")
        stream = self._objects.open_object(medium.tenant_id, keys[0])
        try:
            data = stream.read(MAX_PHOTO_BYTES + 1)
        finally:
            getattr(stream, "close", lambda: None)()
        if len(data) > MAX_PHOTO_BYTES:
            self._fail(medium, NO_SOURCE)
            raise ValueError("photo over the size limit")
        return load_image(data, rgba=False)

    def _real_cost(self, tokens: int) -> Decimal:
        if tokens <= 0:  # no usage reported: the estimate, never zero
            logger.warning("seasonal_ai.no_usage model=%s", self._model)
            return estimate_ai_video_cost_usd(self._model, pricing=self._pricing)
        return video_cost_usd(self._pricing, self._model, AI_VIDEO_RESOLUTION, tokens)

    def _record(self, medium: AiMedium, tokens: int, cost: Decimal) -> None:
        self._ledger.record(
            tenant_id=medium.tenant_id,
            brand_id=medium.brand_id,
            model_id=self._model,
            tokens=tokens,
            cost_usd=cost,
            pricing_version=getattr(self._pricing, "version", AI_PRICING_VERSION),
            occurred_at=self._clock(),
        )

    def _fail(self, medium: AiMedium, reason: str) -> None:
        try:
            self._marks.mark_failed(
                tenant_id=medium.tenant_id,
                brand_id=medium.brand_id,
                media_id=medium.id,
                attempt=medium.attempt,
                reason=reason,
            )
        except (StaleAttempt, WrongState):
            pass


class KindRoutedExecutor:
    """One executor per vendor pool (the runner's contract), routed by job kind: the
    Seedance pool's generator jobs to their executor, `seasonal_video` to the seasonal
    one — so both share the pool's slots (ADR 41's cap)."""

    def __init__(self, default: Any, by_kind: dict[str, Any]) -> None:
        """`by_kind` maps a kind to an executor or to a zero-argument factory of one,
        built on first use (the seasonal executor opens R2 only when a job needs it)."""
        self.default = default
        self._by_kind = dict(by_kind)

    def _for(self, job: JobContext) -> Any:
        chosen = self._by_kind.get(job.kind)
        if chosen is None:
            return self.default
        if callable(chosen) and not hasattr(chosen, "submit"):
            chosen = self._by_kind[job.kind] = chosen()
        return chosen

    def submit(self, job: JobContext) -> str:
        return self._for(job).submit(job)

    def poll(self, job: JobContext, vendor_task_id: str) -> TaskPoll:
        return self._for(job).poll(job, vendor_task_id)

    def finish(self, job: JobContext, vendor_task_id: str | None, status: str) -> None:
        self._for(job).finish(job, vendor_task_id, status)


# --- production wiring --------------------------------------------------------------------


class PostgresAiReads:
    def medium(self, tenant_id: UUID, media_id: UUID) -> AiMedium | None:
        from qualify_api.whatsapp.seasonal import PostgresSeasonalRepository  # noqa: PLC0415

        m = PostgresSeasonalRepository().get(tenant_id=tenant_id, media_id=media_id)
        if m is None:
            return None
        return AiMedium(
            id=m.id,
            tenant_id=m.tenant_id,
            brand_id=m.brand_id,
            season_key=m.season_key,
            kind=m.kind,
            recipe=m.recipe,
            source_kind=m.source_kind,
            source_ref=m.source_ref,
            status=m.status,
            attempt=m.attempt,
        )

    def piece_image_keys(
        self, tenant_id: UUID, brand_id: UUID, draft_ids: Sequence[UUID]
    ) -> list[str]:
        from qualify_api.creative.seasonal_job import PostgresSeasonalSources  # noqa: PLC0415

        return PostgresSeasonalSources().piece_image_keys(tenant_id, brand_id, draft_ids)

    def budget(self, tenant_id: UUID, brand_id: UUID) -> Budget | None:
        from qualify_api.creative.service import PostgresContentRepository  # noqa: PLC0415

        state = PostgresContentRepository().budget_state(tenant_id=tenant_id, brand_id=brand_id)
        return Budget(remaining_usd=state.remaining_usd) if state is not None else None


class PostgresUsageLedger:
    """`creative_usage_events` (draft-less: `draft_id` NULL) + `creative_engine_config.
    budget_spent_usd`, in ONE `tenant_session` — where the generator records every paid
    call, so the brand's monthly cap counts seasonal AI videos too. A business's monthly
    Seedance total: `SUM(cost_usd)` of its `creative_usage_events` with `provider =
    'byteplus'` and `model_id LIKE 'seedance%'` over the month (`seasonal_ai_month_total`)."""

    def record(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        model_id: str,
        tokens: int,
        cost_usd: Decimal,
        pricing_version: str,
        occurred_at: datetime,
    ) -> None:
        from qualify_creative.enums import PaidBy  # noqa: PLC0415
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.creative import models as orm  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            session.add(
                orm.CreativeUsageEvent(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    draft_id=None,
                    provider=PROVIDER,
                    model_id=model_id,
                    unit="token",
                    output_tokens=tokens,
                    cost_usd=cost_usd,
                    paid_by=PaidBy.PLATFORM.value,
                    pricing_table_version=pricing_version,
                    occurred_at=occurred_at,
                )
            )
            config = session.scalar(
                select(orm.CreativeEngineConfig)
                .where(orm.CreativeEngineConfig.brand_id == brand_id)
                .with_for_update()
            )
            if config is not None:
                config.budget_spent_usd = Decimal(config.budget_spent_usd) + cost_usd


def seasonal_ai_month_total(tenant_id: UUID, brand_id: UUID, month_start: datetime) -> Decimal:
    """What the business spent on Seedance since `month_start` (all its Seedance calls:
    generator and seasonal library alike) — read from `creative_usage_events`."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import func, select  # noqa: PLC0415

    from qualify_api.creative import models as orm  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        total = session.scalar(
            select(func.coalesce(func.sum(orm.CreativeUsageEvent.cost_usd), 0)).where(
                orm.CreativeUsageEvent.brand_id == brand_id,
                orm.CreativeUsageEvent.provider == PROVIDER,
                orm.CreativeUsageEvent.model_id.like("seedance%"),
                orm.CreativeUsageEvent.occurred_at >= month_start,
            )
        )
    return Decimal(total or 0)


def production_seasonal_ai_executor(adapter: Any) -> SeasonalAiVideoExecutor:
    import contextlib  # noqa: PLC0415

    import httpx  # noqa: PLC0415
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    from qualify_api.creative.composition import PlatformKeyResolver  # noqa: PLC0415
    from qualify_api.creative.worker.downloads import stream_to_tempfile  # noqa: PLC0415
    from qualify_api.creative.worker.pipeline import SubmissionRecorder  # noqa: PLC0415
    from qualify_api.whatsapp.seasonal import production_seasonal_service  # noqa: PLC0415

    keys = PlatformKeyResolver()

    @contextlib.contextmanager
    def download(url: str) -> Iterator[Path]:
        with httpx.Client(timeout=120) as client, stream_to_tempfile(url, client=client) as path:
            yield path

    return SeasonalAiVideoExecutor(
        adapter=adapter,
        reads=PostgresAiReads(),
        objects=ObjectGate(R2ObjectStore(R2Settings.from_env())),
        marks=production_seasonal_service(),
        ledger=PostgresUsageLedger(),
        api_key=lambda tenant, brand: (
            keys.resolve(tenant_id=tenant, brand_id=brand, provider=CREDENTIAL_PROVIDER).api_key
        ),
        download=download,
        recorder=SubmissionRecorder,
    )
