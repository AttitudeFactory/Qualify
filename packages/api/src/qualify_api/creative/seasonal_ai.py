"""«Crear con IA» for the seasonal library (m-24976893): one Seedance video per medium
attempt, run by `creative-worker` under ADR 41 — the shared Seedance slots, the price
guard at the paid boundary, the vendor task id recorded before any wait.

A seasonal AI job is a `creative_jobs` row of kind `seasonal_video` (migration 0146)
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
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

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

from qualify_api.creative.worker.executor import QUALIFY_TIMEOUT, SUCCEEDED, JobContext, TaskPoll
from qualify_api.whatsapp.seasonal import REASON_TEXT as _LIBRARY_REASON_TEXT
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
#: The brand has no monthly cap configured: a paid call is refused (the generator treats
#: «no config» as unlimited — `service._UNLIMITED_BUDGET`; a seasonal AI video does not).
NO_BUDGET_CAP = "no_budget_cap"
#: The vendor's clip URL is not on `VIDEO_HOST_SUFFIXES`: nothing is downloaded.
VENDOR_URL_REFUSED = "vendor_url_refused"
#: BytePlus expired the task before rendering it (its queue): not billed.
VENDOR_EXPIRED = "vendor_expired"
#: The price table now estimates more per video than the owner accepted when planning.
PRICE_CHANGED = "price_changed"
#: The task kept running past `TASK_DEADLINE`: the slot is let go, the row fails.
TIMED_OUT = "vendor_timeout"
#: A task running longer than this is given up (a 5 s 480p clip takes about a minute).
TASK_DEADLINE_SECONDS = 30 * 60
#: Hosts a vendor clip may be downloaded from (SSRF discipline), over https only; a name
#: must END in one of these, at a dot boundary. EVIDENCE (searched 2026-11-08: the model
#: cards `seedance-2-5.md` / `pruebas.md`, the adapter, its tests and every fixture in the
#: repo): NO recorded Seedance result URL exists — no host is evidenced. The only BytePlus
#: hosts on record are the API's own (`ark.ap-southeast.bytepluses.com`,
#: `openapi.cv.bytepluses.com`, `voice.ap-southeast-1.bytepluses.com`), hence these two
#: suffixes. Ark may serve results from TOS (`*.tos-*.bytepluses.com`, covered) or from
#: `*.volces.com` (NOT covered, unverified): the paid test (m-24976890) must read the real
#: host — a refusal logs `vendor_url_refused host=<host>` at ERROR so it shows at once.
VIDEO_HOST_SUFFIXES = ("bytepluses.com", "byteplus.com")
#: Spanish for the owner, per reason (`qualify-copy-es`).
#: (the dict lives with the library, `whatsapp.seasonal.REASON_TEXT`; same object here)
REASON_TEXT = _LIBRARY_REASON_TEXT
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
        vendor_task_id: str,
    ) -> bool:
        """One `creative_usage_events` row (draft-less) + the brand's monthly spend —
        ONCE per vendor task: a second call for the same task books nothing and returns
        False (review of c2439c3c)."""
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
        self._first_seen: dict[str, float] = {}

    # -- the contract --------------------------------------------------------------------

    def submit(self, job: JobContext) -> str:
        medium = self._runnable(job)
        if medium is None:
            raise ValueError("seasonal job is not the row's current pending AI attempt")
        image = self._photo(medium)
        ratio = ratio_for(image)
        estimate = estimate_ai_video_cost_usd(self._model, ratio=ratio, pricing=self._pricing)
        accepted = accepted_per_video_usd(job, self._model)
        if accepted is None or estimate > accepted:
            # the owner confirmed a lower price when planning: never pay more than that
            self._fail(medium, PRICE_CHANGED)
            raise PriceGuardRefused(f"estimate {estimate} over the accepted {accepted}")
        budget = self._reads.budget(medium.tenant_id, medium.brand_id)
        if budget is None:
            self._fail(medium, NO_BUDGET_CAP)
            raise PriceGuardRefused("no monthly cap configured for the brand")
        if estimate > budget.remaining_usd:
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
        status = str(state.status or "unknown")
        if not state.terminal and self._past_deadline(job, vendor_task_id, state):
            # never hold a Seedance slot forever: the job ends, `finish` fails the row
            logger.warning("seasonal_ai.timed_out task=%s status=%s", vendor_task_id, status)
            return TaskPoll(status=TIMED_OUT_STATUS)
        return TaskPoll(status=status, next_poll_seconds=self._adapter.poll_delay(status, 0.0))

    def _past_deadline(self, job: JobContext, task_id: str, state: Any) -> bool:
        """`TASK_DEADLINE_SECONDS` from the job's `submitted_at` (the database: a worker
        restart never extends it); without one, from the task's `created_at` (ModelArk,
        unix seconds); without either, from the first time this process polled it."""
        now = self._clock().timestamp()
        submitted = getattr(job, "submitted_at", None)
        if submitted is not None:
            started = submitted.timestamp()
        else:
            data = getattr(state, "data", None) or {}
            created = data.get("created_at") if isinstance(data, dict) else None
            if isinstance(created, int | float) and not isinstance(created, bool):
                started = float(created)
            else:
                started = self._first_seen.setdefault(task_id, now)
        return now - started > TASK_DEADLINE_SECONDS

    def finish(self, job: JobContext, vendor_task_id: str | None, status: str) -> None:
        medium = self._runnable(job)
        if medium is None:
            return  # settled meanwhile (or another attempt): nothing to do
        if status == TIMED_OUT_STATUS and vendor_task_id is not None:
            # No cancel in the adapter: the task may still finish and be billed. Book the
            # quoted price now (an overcount beats an undercount against a cap), under the
            # task's own usage id — a late success can never book it a second time.
            quoted = accepted_per_video_usd(job, self._model) or estimate_ai_video_cost_usd(
                self._model, pricing=self._pricing
            )
            self._record(medium, 0, quoted, vendor_task_id)
            self._fail(medium, TIMED_OUT)
            return
        if status == VENDOR_EXPIRED_STATUS:
            self._fail(medium, VENDOR_EXPIRED)  # not billed by BytePlus: nothing booked
            return
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
        tokens = int(payload.get("tokens") or result.usage.output_tokens or 0)
        cost = self._real_cost(tokens)
        if not url or not allowed_video_url(str(url)):
            # the HOST only (the full URL is a signed link); ERROR so the paid test sees it
            logger.error(
                "seasonal_ai.vendor_url_refused media=%s task=%s host=%s",
                medium.id,
                vendor_task_id,
                video_url_host(str(url or "")) or "-",
            )
            # the task was billed even if its clip cannot be fetched: book it all the same
            self._record(medium, tokens, cost, vendor_task_id)
            self._fail(medium, VENDOR_URL_REFUSED)
            return
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
            self._record(medium, tokens, cost, vendor_task_id)
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
        self._record(medium, tokens, cost, vendor_task_id)
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

    def _record(self, medium: AiMedium, tokens: int, cost: Decimal, task_id: str) -> None:
        self._ledger.record(
            tenant_id=medium.tenant_id,
            brand_id=medium.brand_id,
            model_id=self._model,
            tokens=tokens,
            cost_usd=cost,
            pricing_version=getattr(self._pricing, "version", AI_PRICING_VERSION),
            occurred_at=self._clock(),
            vendor_task_id=task_id,
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


#: `creative_usage_events.unit` of a seasonal «Con IA» booking: the marker the monthly
#: total filters by (no migration; the rows outlive the medium and its jobs, so deleting
#: a season never drops paid spend). Billed by video token, like `token`.
SEASONAL_USAGE_UNIT = "seasonal_video_token"
#: A poll answer that ends the job — OURS, never ModelArk's `expired` (a task the vendor
#: expired is not billed): the task ran past `TASK_DEADLINE_SECONDS`.
TIMED_OUT_STATUS = QUALIFY_TIMEOUT
#: ModelArk expired the task in its own queue: not billed, nothing booked.
VENDOR_EXPIRED_STATUS = "expired"
_USAGE_NAMESPACE = UUID("6f1c2a7e-5b3d-4c8e-9a10-24976893a1d0")


def usage_event_id(vendor_task_id: str) -> UUID:
    """The `creative_usage_events.id` of a seasonal AI task: the same task, the same id."""
    return uuid5(_USAGE_NAMESPACE, f"seasonal-ai:{vendor_task_id}")


def accepted_per_video_usd(job: JobContext, model: str = DEFAULT_AI_VIDEO_MODEL) -> Decimal | None:
    """What the owner accepted per video when planning: the quote of the price-table
    version recorded on the job (`creative_jobs.pricing_version`, versions are immutable),
    rounded up to the cent like the screen showed it. None when the job carries none."""
    version = getattr(job, "pricing_version", None)
    if not version:
        return None
    per = estimate_ai_video_cost_usd(model, pricing=pricing_table(version))
    return per.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def video_url_host(url: str) -> str:
    """The URL's host name, lower-case — what a refusal logs instead of the signed URL."""
    from urllib.parse import urlsplit  # noqa: PLC0415

    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def allowed_video_url(url: str) -> bool:
    """https and a BytePlus host (`VIDEO_HOST_SUFFIXES`, dot boundary) — nothing else is
    fetched with the worker's network access."""
    from urllib.parse import urlsplit  # noqa: PLC0415

    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return False
    return any(host == s or host.endswith("." + s) for s in VIDEO_HOST_SUFFIXES)


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
    seasonal-AI total: `seasonal_ai_month_total` (its `seasonal_video` tasks' rows only,
    month in the business's zone)."""

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
        vendor_task_id: str,
    ) -> bool:
        from qualify_creative.enums import PaidBy  # noqa: PLC0415
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        from qualify_api.creative import models as orm  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            # The event's id IS the task (uuid5): a second booking of the same paid task
            # conflicts on the primary key and adds nothing — no migration needed.
            booked = session.scalar(
                insert(orm.CreativeUsageEvent)
                .values(
                    id=usage_event_id(vendor_task_id),
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    draft_id=None,
                    provider=PROVIDER,
                    model_id=model_id,
                    unit=SEASONAL_USAGE_UNIT,
                    # 0009's NOT NULLs, explicit like the generator's insert: a Seedance
                    # video has no input, cache or piece count
                    input_tokens=0,
                    output_tokens=tokens,
                    cache_read_tokens=0,
                    cache_creation_tokens=0,
                    pieces=0,
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


def month_start_in_zone(now: datetime, tz_name: str) -> datetime:
    """The first instant of `now`'s calendar month in the business's zone, as UTC."""
    from qualify_api.planner.service import resolve_zone  # noqa: PLC0415

    local = now.astimezone(resolve_zone(tz_name))
    first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return first.astimezone(UTC)


def seasonal_ai_month_total(
    tenant_id: UUID,
    brand_id: UUID,
    month_start: datetime | None = None,
    *,
    now: datetime | None = None,
) -> Decimal:
    """What the business spent on seasonal «Con IA» videos this month: only the usage
    rows marked `SEASONAL_USAGE_UNIT` (never the generator's Seedance), on the
    `(brand_id, occurred_at)` index. The rows outlive their medium, season and jobs, so
    deleting a season keeps the month's spend. The month starts at midnight of day 1 in
    the business's zone (`planner.composition.tenant_timezone`) unless `month_start` is
    given."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import func, select  # noqa: PLC0415

    from qualify_api.creative import models as orm  # noqa: PLC0415

    if month_start is None:
        from qualify_api.planner.composition import tenant_timezone  # noqa: PLC0415

        month_start = month_start_in_zone(now or datetime.now(UTC), tenant_timezone(tenant_id))
    with tenant_session(tenant_id) as session:
        total = session.scalar(
            select(func.coalesce(func.sum(orm.CreativeUsageEvent.cost_usd), 0)).where(
                orm.CreativeUsageEvent.brand_id == brand_id,
                orm.CreativeUsageEvent.occurred_at >= month_start,
                orm.CreativeUsageEvent.unit == SEASONAL_USAGE_UNIT,
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
