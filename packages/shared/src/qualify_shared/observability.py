"""Langfuse tracing of model calls — the ONE door to the Langfuse SDK
(docs/plan-observabilidad-langfuse.md §5).

Three rules, each one load-bearing:

1. **No keys, no tracing.** Without ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY``
   every helper here is a no-op, so offline tests, CI and any unconfigured machine run
   exactly as before. ``LANGFUSE_BASE_URL`` (the self-hosted server, e.g.
   ``http://localhost:3100``), ``LANGFUSE_TRACING_ENVIRONMENT`` and ``LANGFUSE_RELEASE``
   are read by the SDK itself.
2. **Never breaks the traced work.** Like ``qualify_api.creative.trace``: any failure of
   the SDK is logged and swallowed; only the caller's own exception ever propagates.
3. **Nothing else imports** ``langfuse`` (a static test enforces it), so swapping the
   vendor or the SDK major is a change to this file.

What leaves the process is masked first (``_mask``): e-mail addresses, phone numbers,
API-key-like tokens, raw bytes and ``data:`` URLs. Media travels as an R2 key, never as
its bytes (§9 of the plan). The masking runs HERE, before the SDK sees anything — not
only in the SDK's own ``mask`` hook: the SDK lifts ``data:`` URLs out of an input and
uploads them as Langfuse media BEFORE that hook runs (seen 2026-10-13), which would copy
a tenant's photo to Langfuse's storage.

Langfuse v4 ingests traces only over OpenTelemetry; the SDK exports in batches from a
background thread. A short-lived process (a CLI, an eval run) calls :func:`flush`.
"""

from __future__ import annotations

import functools
import logging
import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

PUBLIC_KEY_ENV = "LANGFUSE_PUBLIC_KEY"
SECRET_KEY_ENV = "LANGFUSE_SECRET_KEY"
#: Langfuse caps a propagated metadata value at 200 characters and drops longer ones.
_METADATA_VALUE_MAX = 200
#: A field this long is cut: a prompt is useful at a glance, not as a 2 MB blob.
_TEXT_MAX = 20_000

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<![\w-])\+?\d[\d ().-]{7,}\d(?![\w-])")
_SECRET = re.compile(r"\b(?:sk-ant-[\w-]+|sk-lf-[\w-]+|sk-[A-Za-z0-9]{20,}|Bearer\s+[\w.-]+)")

_lock = threading.Lock()
_client: Any = None
_resolved = False


def _mask_text(text: str) -> str:
    if text.startswith("data:"):
        return f"<data url, {len(text)} chars>"
    text = _SECRET.sub("<secret>", text)
    text = _EMAIL.sub("<email>", text)
    text = _PHONE.sub("<phone>", text)
    if len(text) > _TEXT_MAX:
        return text[:_TEXT_MAX] + f"… <{len(text) - _TEXT_MAX} more chars>"
    return text


def _mask(*, data: Any, **_: Any) -> Any:
    """Langfuse's `mask` hook: applied to every input, output and metadata value before
    it is exported. Returns JSON-serializable data. A file wrapped by :func:`media` is the
    one thing that passes as it is: it was attached on purpose."""
    if type(data).__name__ == "LangfuseMedia":
        return data
    if isinstance(data, str):
        return _mask_text(data)
    if isinstance(data, bytes | bytearray | memoryview):
        return f"<{len(data)} bytes>"
    if isinstance(data, Mapping):
        return {str(key): _mask(data=value) for key, value in data.items()}
    if isinstance(data, list | tuple | set | frozenset):
        return [_mask(data=value) for value in data]
    if data is None or isinstance(data, bool | int | float):
        return data
    return _mask_text(str(data))


def _build_client() -> Any:
    """The SDK client, or None when tracing is off (no keys, or the SDK cannot start)."""
    if not (os.environ.get(PUBLIC_KEY_ENV) and os.environ.get(SECRET_KEY_ENV)):
        return None
    try:
        from langfuse import Langfuse  # noqa: PLC0415 — lazy: only when tracing is on

        return Langfuse(mask=_mask)
    except Exception:  # noqa: BLE001 — tracing must never stop the app from starting
        logger.exception("Langfuse could not start; model calls are not traced")
        return None


def _get() -> Any:
    global _client, _resolved
    if not _resolved:
        with _lock:
            if not _resolved:
                _client = _build_client()
                _resolved = True
    return _client


def configure(client: Any) -> None:
    """Use `client` (a ``langfuse.Langfuse``) from now on, or None to switch tracing off.
    For tests, which pass a client exporting to memory, and for scripts that build their
    own; the app never calls it — the environment decides."""
    global _client, _resolved
    with _lock:
        _client = client
        _resolved = True


def reset() -> None:
    """Forget the client, so the next call reads the environment again (tests)."""
    global _client, _resolved
    with _lock:
        _client = None
        _resolved = False


def enabled() -> bool:
    return _get() is not None


@contextmanager
def capture_spans() -> Iterator[Any]:
    """Tests: trace into memory instead of to a server. Yields the OpenTelemetry
    `InMemorySpanExporter`; read it after :func:`flush`. The previous client (or none)
    is restored on exit. Lives here so no test imports the SDK itself (rule 3)."""
    import uuid  # noqa: PLC0415

    from langfuse import Langfuse  # noqa: PLC0415
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: PLC0415
        InMemorySpanExporter,
    )

    global _client, _resolved
    exporter = InMemorySpanExporter()
    client = Langfuse(
        # a key of its own each time: the SDK keeps one client per public key
        public_key=f"pk-lf-capture-{uuid.uuid4()}",
        secret_key="sk-lf-capture",
        base_url="http://127.0.0.1:9",
        span_exporter=exporter,
        tracer_provider=TracerProvider(),
        mask=_mask,
    )
    with _lock:
        previous = (_client, _resolved)
        _client, _resolved = client, True
    try:
        yield exporter
    finally:
        with _lock:
            _client, _resolved = previous
        client.shutdown()


def flush() -> None:
    """Export what is buffered — for processes that end right after their work."""
    client = _get()
    if client is None:
        return
    try:
        client.flush()
    except Exception:  # noqa: BLE001
        logger.exception("Langfuse flush failed")


def _inside_a_trace() -> bool:
    """Whether an observation is already open in this context — then a new unit of work
    is a child of it, not a trace of its own."""
    try:
        from opentelemetry import trace as otel_trace  # noqa: PLC0415

        return otel_trace.get_current_span().get_span_context().is_valid
    except Exception:  # noqa: BLE001
        return False


def _metadata(values: Mapping[str, Any] | None) -> dict[str, str]:
    """Propagated metadata is `dict[str, str]`, each value at most 200 characters."""
    return {
        str(key): _mask_text(str(value))[:_METADATA_VALUE_MAX]
        for key, value in (values or {}).items()
        if value is not None
    }


class Observation:
    """The open observation of :func:`generation`: report what the call returned with
    :meth:`finish`. Every method is safe to call with tracing off."""

    def __init__(self, span: Any = None) -> None:
        self._span = span

    def finish(
        self,
        *,
        output: Any = None,
        model: str | None = None,
        usage: Mapping[str, int] | None = None,
        cost: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if self._span is None:
            return
        try:
            fields: dict[str, Any] = {"output": _mask(data=output)}
            if model:
                fields["model"] = model
            if usage:
                fields["usage_details"] = {k: int(v) for k, v in usage.items()}
            if cost:
                fields["cost_details"] = {k: float(v) for k, v in cost.items()}
            if metadata:
                fields["metadata"] = _mask(data=dict(metadata))
            self._span.update(**fields)
        except Exception:  # noqa: BLE001
            logger.exception("Langfuse observation update failed")

    def fail(self, error: BaseException) -> None:
        if self._span is None:
            return
        try:
            self._span.update(level="ERROR", status_message=f"{type(error).__name__}: {error}")
        except Exception:  # noqa: BLE001
            logger.exception("Langfuse observation update failed")


@contextmanager
def trace(
    name: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
    input: Any = None,
    trace_seed: str | None = None,
) -> Iterator[Observation]:
    """The root of a unit of work — one draft's generation, one Brand Kit reading. The
    session, tags and metadata propagate to every observation opened inside it.

    `trace_seed` fixes the trace id (`trace_id_for`), so a later event — the operator
    approving the draft — scores this very trace without its id being stored anywhere.

    Opened inside another trace (the voice analysis calling the tone suggestion), it is
    a child span of that trace: the outer unit keeps its name, session and tags."""
    client = _get()
    stack = ExitStack()
    span = None
    if client is not None:
        try:
            from langfuse import propagate_attributes  # noqa: PLC0415

            if not _inside_a_trace():
                stack.enter_context(
                    propagate_attributes(
                        trace_name=name,
                        session_id=session_id,
                        user_id=user_id,
                        tags=[str(tag) for tag in tags if tag],
                        metadata=_metadata(metadata),
                    )
                )
            seeded = trace_seed and not _inside_a_trace()
            span = stack.enter_context(
                client.start_as_current_observation(
                    as_type="span",
                    name=name,
                    input=_mask(data=input),
                    trace_context=(
                        {"trace_id": client.create_trace_id(seed=trace_seed)} if seeded else None
                    ),
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("Langfuse trace could not start")
            _close(stack)
            stack, span = ExitStack(), None
    observation = Observation(span)
    try:
        yield observation
    except BaseException as exc:
        observation.fail(exc)
        _close(stack)
        raise
    _close(stack)


@contextmanager
def generation(
    name: str,
    *,
    model: str | None = None,
    input: Any = None,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[Observation]:
    """One model call, nested under the current trace. Its latency is the time the
    `with` block takes; the caller reports usage and cost through ``finish``."""
    client = _get()
    stack = ExitStack()
    span = None
    if client is not None:
        try:
            span = stack.enter_context(
                client.start_as_current_observation(
                    as_type="generation",
                    name=name,
                    model=model,
                    input=_mask(data=input),
                    metadata=_mask(data=dict(metadata)) if metadata else None,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("Langfuse generation could not start")
            _close(stack)
            stack, span = ExitStack(), None
    observation = Observation(span)
    try:
        yield observation
    except BaseException as exc:
        observation.fail(exc)
        _close(stack)
        raise
    _close(stack)


P = ParamSpec("P")
R = TypeVar("R")


def traced(
    name: str, *, tags: Sequence[str] = (), metadata: Mapping[str, Any] | None = None
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate a function that calls models: each call is one :func:`trace` named
    `name` (a child span when it runs inside another trace). Its arguments are NOT
    recorded — they can be a tenant's documents; the model calls inside record their
    own, masked, inputs."""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        where = {"function": f"{function.__module__}.{function.__qualname__}"}

        @functools.wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with trace(name, tags=tags, metadata={**where, **(metadata or {})}):
                return function(*args, **kwargs)

        return wrapper

    return decorate


def _close(stack: ExitStack) -> None:
    try:
        stack.close()
    except Exception:  # noqa: BLE001 — closing a span must not mask the caller's outcome
        logger.exception("Langfuse span could not be closed")


# ---------------------------------------------------------------------------
# Datasets and experiments (docs/plan-observabilidad-langfuse.md §6-§7)
#
# The eval scripts (packages/api/evals/*) describe cases, a task and evaluators in plain
# Python; these helpers turn them into a Langfuse dataset and a dataset run. Experiments
# spend real money, so they need a server and are never part of the offline gate.


class TracingNotConfigured(RuntimeError):
    """An experiment was asked for without LANGFUSE_* keys."""


@dataclass(frozen=True)
class Score:
    """One evaluation of an item or of a whole run — numeric, boolean or a label."""

    name: str
    value: float | bool | str
    comment: str | None = None


@dataclass(frozen=True)
class ItemOutcome:
    """What a run-level evaluator sees of one item: its input, the task's output and the
    item-level scores already computed."""

    input: Any
    output: Any
    scores: Mapping[str, float | bool | str]


@dataclass(frozen=True)
class ExperimentSummary:
    run_name: str
    items: int
    #: Mean of every numeric/boolean item-level score, by name.
    means: Mapping[str, float]
    run_scores: Mapping[str, float | bool | str]
    outcomes: tuple[ItemOutcome, ...]
    url: str | None


ItemEvaluator = Callable[[Any, Any, Any, Mapping[str, Any]], Sequence[Score]]
RunEvaluator = Callable[[Sequence[ItemOutcome]], Sequence[Score]]


def _require() -> Any:
    client = _get()
    if client is None:
        raise TracingNotConfigured(
            f"{PUBLIC_KEY_ENV}/{SECRET_KEY_ENV} are not set: experiments need the Langfuse "
            "server (`just langfuse-up`)"
        )
    return client


def sync_dataset(name: str, items: Sequence[Mapping[str, Any]], *, description: str = "") -> int:
    """Create dataset `name` if it does not exist and upsert every item by its `id`
    (`{"id", "input", "expected_output"?, "metadata"?}`), so re-running a script updates
    the cases instead of duplicating them. Returns how many items were written.

    `id` is the case's own id; Langfuse gets `"{name}:{id}"`, because its item ids are
    unique per PROJECT, across datasets — a pilot dataset reusing a case would otherwise
    collide with the full one (HTTP 409, seen 2026-10-13).

    An item of `name` that is no longer in `items` is ARCHIVED (Langfuse cannot free an
    id, and `run_experiment` skips archived items), so a case removed from the local file
    stops weighing on the run's averages; putting it back reactivates it."""
    from langfuse.api import DatasetStatus  # noqa: PLC0415

    client = _require()
    try:
        existing = client.get_dataset(name).items
    except Exception:  # noqa: BLE001 — missing: create it
        client.create_dataset(name=name, description=description or None)
        existing = []
    wanted = {f"{name}:{item['id']}" for item in items}
    for item in items:
        client.create_dataset_item(
            dataset_name=name,
            id=f"{name}:{item['id']}",
            input=_mask(data=item.get("input")),
            expected_output=_mask(data=item.get("expected_output")),
            metadata=_mask(data=item.get("metadata")),
            status=DatasetStatus.ACTIVE,
        )
    for old in existing:
        if old.id not in wanted and old.status != DatasetStatus.ARCHIVED:
            client.create_dataset_item(
                dataset_name=name,
                id=old.id,
                input=old.input,
                expected_output=old.expected_output,
                metadata=old.metadata,
                status=DatasetStatus.ARCHIVED,
            )
    return len(items)


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float):
        return float(value)
    return None


def run_experiment(
    dataset: str,
    *,
    name: str,
    run_name: str,
    task: Callable[[Any], Any],
    evaluators: Sequence[ItemEvaluator] = (),
    run_evaluators: Sequence[RunEvaluator] = (),
    description: str = "",
    max_concurrency: int = 4,
    metadata: Mapping[str, Any] | None = None,
) -> ExperimentSummary:
    """Run `task(item_input)` over every ACTIVE item of `dataset` as one Langfuse dataset run:
    each item is a trace (the model calls inside nest under it), each `evaluators`
    function scores an item from `(input, output, expected_output, metadata)`, and each
    `run_evaluators` function scores the whole run from its outcomes."""
    from langfuse import Evaluation  # noqa: PLC0415

    client = _require()

    def lf_task(*, item: Any, **_: Any) -> Any:
        return task(item.input)

    def lf_evaluator(evaluator: ItemEvaluator) -> Callable[..., list[Any]]:
        def run(*, input: Any, output: Any, expected_output: Any = None, **kwargs: Any) -> list:
            meta = kwargs.get("metadata") or {}
            return [
                Evaluation(name=s.name, value=s.value, comment=s.comment)
                for s in evaluator(input, output, expected_output, meta)
            ]

        run.__name__ = getattr(evaluator, "__name__", "evaluator")
        return run

    def outcomes_of(item_results: Sequence[Any]) -> tuple[ItemOutcome, ...]:
        return tuple(
            ItemOutcome(
                input=getattr(result.item, "input", None),
                output=result.output,
                scores={e.name: e.value for e in result.evaluations},
            )
            for result in item_results
        )

    def lf_run_evaluator(evaluator: RunEvaluator) -> Callable[..., list[Any]]:
        def run(*, item_results: Sequence[Any], **_: Any) -> list:
            return [
                Evaluation(name=s.name, value=s.value, comment=s.comment)
                for s in evaluator(outcomes_of(item_results))
            ]

        run.__name__ = getattr(evaluator, "__name__", "run_evaluator")
        return run

    from langfuse.api import DatasetStatus  # noqa: PLC0415

    data = client.get_dataset(dataset)
    data.items = [i for i in data.items if getattr(i, "status", None) != DatasetStatus.ARCHIVED]
    result = data.run_experiment(
        name=name,
        run_name=run_name,
        description=description or None,
        task=lf_task,
        evaluators=[lf_evaluator(e) for e in evaluators],
        run_evaluators=[lf_run_evaluator(e) for e in run_evaluators],
        max_concurrency=max_concurrency,
        metadata={str(k): str(v) for k, v in (metadata or {}).items()},
    )
    client.flush()
    outcomes = outcomes_of(result.item_results)
    sums: dict[str, list[float]] = {}
    for outcome in outcomes:
        for key, value in outcome.scores.items():
            number = _numeric(value)
            if number is not None:
                sums.setdefault(key, []).append(number)
    return ExperimentSummary(
        run_name=result.run_name,
        items=len(outcomes),
        means={key: sum(values) / len(values) for key, values in sums.items()},
        run_scores={e.name: e.value for e in result.run_evaluations},
        outcomes=outcomes,
        url=getattr(result, "dataset_run_url", None),
    )


# ---------------------------------------------------------------------------
# Human judgement (docs/plan-observabilidad-langfuse.md §8): scores on a trace found by
# its seed, score configs and the annotation queue for what code cannot measure.


def media(data: bytes, content_type: str) -> Any:
    """`data` as a file Langfuse stores and shows inline (an image in the review queue).
    OPT-IN and only for what may leave the process: the eval's FICTIONAL brands' generated
    images — never a tenant's file (§9 of the plan). None with tracing off."""
    if _get() is None:
        return None
    try:
        from langfuse.media import LangfuseMedia  # noqa: PLC0415

        return LangfuseMedia(content_bytes=data, content_type=content_type)
    except Exception:  # noqa: BLE001
        logger.exception("Langfuse media could not be built")
        return None


def current_trace_id() -> str | None:
    """The id of the trace open in this context (an experiment item's), or None."""
    try:
        from opentelemetry import trace as otel_trace  # noqa: PLC0415

        context = otel_trace.get_current_span().get_span_context()
        return format(context.trace_id, "032x") if context.is_valid else None
    except Exception:  # noqa: BLE001
        return None


def trace_id_for(seed: str) -> str | None:
    """The trace id `trace(..., trace_seed=seed)` used — deterministic, so nothing has
    to be stored to find a trace again. None with tracing off."""
    client = _get()
    if client is None:
        return None
    try:
        return str(client.create_trace_id(seed=seed))
    except Exception:  # noqa: BLE001
        logger.exception("Langfuse trace id could not be derived")
        return None


def score(
    name: str,
    value: float | bool,
    *,
    trace_seed: str,
    comment: str | None = None,
) -> None:
    """Score the trace of `trace_seed` — a boolean as Langfuse's BOOLEAN (1/0), a number
    as NUMERIC. Never raises: a score must not break an approval."""
    client = _get()
    if client is None:
        return
    try:
        boolean = isinstance(value, bool)
        client.create_score(
            name=name,
            value=float(value),
            trace_id=client.create_trace_id(seed=trace_seed),
            data_type="BOOLEAN" if boolean else "NUMERIC",
            comment=_mask_text(comment)[:500] if comment else None,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Langfuse score %s could not be sent", name)


@dataclass(frozen=True)
class ScoreConfig:
    """A human score's scale, as Langfuse's annotation UI offers it."""

    name: str
    data_type: str  # "NUMERIC" | "BOOLEAN"
    description: str
    min_value: float | None = None
    max_value: float | None = None


_queue_ids: dict[str, str] = {}


def ensure_review_setup(
    configs: Sequence[ScoreConfig],
    *,
    queue: str,
    queue_configs: Sequence[str],
    description: str = "",
) -> str:
    """Create the missing score configs and the annotation queue `queue` scoring
    `queue_configs`; idempotent (matched by name). Returns the queue id. Needs the server
    (`TracingNotConfigured` otherwise) — it is a setup step, run by hand."""
    client = _require()
    existing = {c.name: c.id for c in client.api.score_configs.get(limit=100).data}
    for config in configs:
        if config.name in existing:
            continue
        created = client.api.score_configs.create(
            name=config.name,
            data_type=config.data_type,
            description=config.description,
            **(
                {"min_value": config.min_value, "max_value": config.max_value}
                if config.data_type == "NUMERIC"
                else {}
            ),
        )
        existing[config.name] = created.id
    for found in client.api.annotation_queues.list_queues(limit=100).data:
        if found.name == queue:
            _queue_ids[queue] = found.id
            return found.id
    created_queue = client.api.annotation_queues.create_queue(
        name=queue,
        score_config_ids=[existing[name] for name in queue_configs],
        description=description or None,
    )
    _queue_ids[queue] = created_queue.id
    return created_queue.id


def enqueue_for_review(
    queue: str, *, trace_seed: str | None = None, trace_id: str | None = None
) -> None:
    """Put a trace — by its seed, or by its id — in the annotation queue `queue`, if that
    queue exists (`ensure_review_setup`). Never raises: a review item must not fail the
    generation that produced the media."""
    client = _get()
    if client is None or not (trace_seed or trace_id):
        return
    try:
        queue_id = _queue_ids.get(queue)
        if queue_id is None:
            queue_id = next(
                (
                    q.id
                    for q in client.api.annotation_queues.list_queues(limit=100).data
                    if q.name == queue
                ),
                None,
            )
            if queue_id is None:
                logger.info("annotation queue %r not set up: `just langfuse-setup`", queue)
                return
            _queue_ids[queue] = queue_id
        client.api.annotation_queues.create_queue_item(
            queue_id,
            object_id=trace_id or client.create_trace_id(seed=trace_seed),
            object_type="TRACE",
        )
    except Exception:  # noqa: BLE001
        logger.exception("trace could not be queued for review in %r", queue)
