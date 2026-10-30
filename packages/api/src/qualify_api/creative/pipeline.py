"""Durable preparation → vendor request → assembly (m-24852166).

The request inserts an outbox only. In the worker, preparation checkpoints every
paid synchronous step before advancing, and captures video requests without sending
them. Independent video jobs own the global slots. Assembly reads the same immutable
requests/results, so a deploy never pays copy, frames or voice a second time.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import wraps
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from qualify_creative.enums import GenerationTask
from qualify_creative.providers import GenerationRequest, GenerationResult, RenderedPrompt, Usage
from qualify_creative.queue_errors import UNCERTAIN_REASON
from qualify_creative.router import Hop, HopAction, RouterOutcome
from qualify_shared.db.session import tenant_session, tenant_unit_of_work
from sqlalchemy import text

from qualify_api.creative import job_queue as q
from qualify_api.creative.queue_dispatch import CheckpointError, GenerationDeferred

if TYPE_CHECKING:
    from qualify_api.creative.brand_references import BrandReferencesSet

LEASE = timedelta(minutes=10)


@dataclass
class Preparation:
    tenant_id: UUID
    draft_id: UUID
    revision: int
    phase: str
    token: UUID
    version: int
    step: int = 0
    video: int = 0

    def params(self) -> dict[str, Any]:
        return {"t": self.tenant_id, "d": self.draft_id, "r": self.revision, "p": self.phase}


_preparation: contextvars.ContextVar[Preparation | None] = contextvars.ContextVar(
    "creative_preparation", default=None
)
IDENTITY = "tenant_id=:t AND draft_id=:d AND revision=:r AND phase=:p"


class PipelineStore:
    def acquire(
        self, tenant_id: UUID, draft_id: UUID, revision: int, phase: str
    ) -> Preparation | None:
        now = datetime.now(UTC)
        run = Preparation(tenant_id, draft_id, revision, phase, uuid4(), 0)
        with tenant_session(tenant_id) as session:
            version = session.execute(
                text(f"""
                UPDATE creative_pipeline_runs SET lease_token=:token, lease_until=:until
                WHERE {IDENTITY} AND dirty_version > prepared_version
                  AND (lease_until IS NULL OR lease_until < :now)
                RETURNING dirty_version
            """),
                {**run.params(), "token": run.token, "until": now + LEASE, "now": now},
            ).scalar()
        if version is None:
            return None
        run.version = version
        return run

    def release(self, run: Preparation, *, completed: bool) -> None:
        with tenant_session(run.tenant_id) as session:
            session.execute(
                text(f"""
                UPDATE creative_pipeline_runs SET lease_token=NULL, lease_until=NULL,
                    prepared_version=CASE WHEN :done THEN :v ELSE prepared_version END
                WHERE {IDENTITY} AND lease_token=:token
            """),
                {**run.params(), "token": run.token, "v": run.version, "done": completed},
            )

    def load_step(self, run: Preparation, step: int) -> Mapping[str, Any] | None:
        with tenant_session(run.tenant_id) as session:
            return (
                session.execute(
                    text(f"""
                SELECT * FROM creative_pipeline_steps WHERE {IDENTITY} AND step=:s
            """),
                    {**run.params(), "s": step},
                )
                .mappings()
                .first()
            )

    def fence(self, session: Any, run: Preparation) -> None:
        now = datetime.now(UTC)
        token = session.execute(
            text(f"""
            UPDATE creative_pipeline_runs SET lease_until=:until
            WHERE {IDENTITY} AND lease_token=:token AND lease_until > :now
            RETURNING lease_token
        """),
            {**run.params(), "token": run.token, "now": now, "until": now + LEASE},
        ).scalar()
        if token is None:
            raise CheckpointError("preparation lease lost")

    def save_step(
        self, run: Preparation, step: int, request: Mapping[str, Any], job_id: UUID | None
    ) -> Mapping[str, Any]:
        with tenant_session(run.tenant_id) as session:
            # Losing the preparation lease forbids further paid steps.
            self.fence(session, run)
            session.execute(
                text("""
                INSERT INTO creative_pipeline_steps
                    (tenant_id,draft_id,revision,phase,step,job_id,request)
                VALUES (:t,:d,:r,:p,:s,:j,CAST(:req AS jsonb)) ON CONFLICT DO NOTHING
            """),
                {**run.params(), "s": step, "j": job_id, "req": json.dumps(request)},
            )
        result = self.load_step(run, step)
        if result is None:
            raise RuntimeError("preparation step not saved")
        return result

    def complete_step(
        self,
        tenant_id: UUID,
        *,
        identity: Mapping[str, Any],
        result: Mapping[str, Any] | None,
        error: str | None = None,
        run: Preparation | None = None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            if run is not None:
                self.fence(session, run)
            changed = session.execute(
                text(f"""
                UPDATE creative_pipeline_steps SET result=CAST(:result AS jsonb), error=:error
                WHERE {IDENTITY} AND step=:s AND result IS NULL
                  AND (error IS NULL OR error='in_flight')
                RETURNING step
            """),
                {
                    **identity,
                    "result": json.dumps(result) if result is not None else None,
                    "error": error,
                },
            ).scalar()
            if changed is not None:
                session.execute(
                    text(f"""
                    UPDATE creative_pipeline_runs SET dirty_version=dirty_version+1
                    WHERE {IDENTITY}
                """),
                    identity,
                )

    def video_job(self, run: Preparation, ordinal: int, provider: str) -> UUID:
        with tenant_session(run.tenant_id) as session:
            kind_filter = "kind='final'" if run.phase.startswith("final:") else "kind<>'final'"
            jobs = (
                session.execute(
                    text(f"""
                SELECT id FROM creative_jobs WHERE tenant_id=:t AND draft_id=:d AND revision=:r
                  AND {kind_filter} ORDER BY position
            """),
                    run.params(),
                )
                .scalars()
                .all()
            )
            if run.phase.startswith("final:"):
                asset = UUID(run.phase.split(":", 1)[1].split("@", 1)[0])
                attempt = int(run.phase.split("@", 1)[1]) if "@" in run.phase else 0
                return session.execute(
                    text("""
                    SELECT j.id FROM creative_jobs j JOIN image_assets a
                      ON a.draft_id=j.draft_id AND a.position=j.position AND a.id=:asset
                    WHERE j.tenant_id=:t AND j.draft_id=:d AND j.revision=:r AND j.kind='final'
                      AND j.final_attempt=:final_attempt
                """),
                    {**run.params(), "asset": asset, "final_attempt": attempt},
                ).scalar_one()
            if ordinal < len(jobs):
                return jobs[ordinal]
            # A template may contain video tasks discovered during preparation.
            return q.enqueue_job(
                session,
                tenant_id=run.tenant_id,
                draft_id=run.draft_id,
                revision=run.revision,
                kind=q.KIND_CAROUSEL_SCENE,
                position=ordinal,
                vendor_model=q.OMNIHUMAN_POOL if provider == "omnihuman" else q.SEEDANCE_POOL,
                lane=q.LANE_IMMEDIATE,
                not_before=datetime(9999, 1, 1, tzinfo=UTC),
            ).job_id

    def ready(self, run: Preparation, job_id: UUID) -> None:
        with tenant_session(run.tenant_id) as session:
            self.fence(session, run)
            moment = datetime.now(UTC)
            not_before = moment
            if run.phase.startswith("final:"):
                asset = UUID(run.phase.split(":", 1)[1].split("@", 1)[0])
                raw = session.execute(
                    text(
                        "SELECT params->'draft'->>'final_not_before' FROM image_assets WHERE id=:a"
                    ),
                    {"a": asset},
                ).scalar()
                if raw:
                    not_before = max(moment, datetime.fromisoformat(raw))
            session.execute(
                text("""
                UPDATE creative_jobs SET not_before=:when WHERE id=:j AND status='queued'
                  AND not_before > :now
            """),
                {"j": job_id, "now": moment, "when": not_before},
            )

    def intent(self, run: Preparation, step: int) -> None:
        """Crash after a paid request is ambiguous: never blindly repeat that charge."""
        with tenant_session(run.tenant_id) as session:
            self.fence(session, run)
            session.execute(
                text(f"""
                UPDATE creative_pipeline_steps SET error='in_flight'
                WHERE {IDENTITY} AND step=:s AND result IS NULL AND error IS NULL
            """),
                {**run.params(), "s": step},
            )

    def job_step(self, tenant_id: UUID, job_id: UUID) -> Mapping[str, Any]:
        with tenant_session(tenant_id) as session:
            return (
                session.execute(
                    text("""
                SELECT s.*, d.brand_id FROM creative_pipeline_steps s
                JOIN content_drafts d ON d.id=s.draft_id
                WHERE s.job_id=:j
            """),
                    {"j": job_id},
                )
                .mappings()
                .one()
            )


def frozen_inputs(**values: Any) -> tuple[Any, ...]:
    """Freeze model inputs at first preparation; a changed live brand cannot change replay."""
    run = _preparation.get()
    if run is None:
        return tuple(values.values())
    store = PipelineStore()
    row = store.load_step(run, -1)
    if row is None:
        row = store.save_step(
            run, -1, {name: obj.model_dump(mode="json") for name, obj in values.items()}, None
        )
    return tuple(type(obj).model_validate(row["request"][name]) for name, obj in values.items())


#: A distinct preparation step for the brand-reference descriptor set (m-24820842). It is
#: kept apart from `frozen_inputs`' step -1 on purpose: the descriptors are rebuilt and
#: revalidated against the LIVE Brand Kit only on a NEW generation (first capture), and a
#: retry/resume reuses the frozen snapshot verbatim — `builder` is NOT called again, so a
#: later Brand Kit update (a substituted or deleted resource) never mutates or rejects an
#: in-flight/paid job.
_BRAND_REFERENCES_STEP = -2


def frozen_brand_references(builder: Callable[[], BrandReferencesSet]) -> BrandReferencesSet:
    """Freeze the brand-reference descriptor set per execution attempt. `builder` reads
    the LIVE Brand Kit and revalidates the selection, and runs ONLY on first capture (a
    new generation); a replay returns the frozen snapshot without re-reading or
    revalidating, so the freeze boundary is one execution attempt. Outside a worker
    preparation (`_preparation` is None — the inline dispatcher, local dev) `builder` is
    called every time and nothing is frozen."""
    from qualify_api.creative.brand_references import (
        BRAND_REFERENCE_BLOCK_VERSION,
        BrandReferenceError,
        BrandReferencesSet,
    )

    run = _preparation.get()
    if run is None:
        return builder()
    store = PipelineStore()
    row = store.load_step(run, _BRAND_REFERENCES_STEP)
    if row is None:
        # A request prepared before this feature must replay its existing paid inputs;
        # never introduce today's live resources half way through an old preparation.
        if store.load_step(run, 0) is not None:
            return BrandReferencesSet()
        built = builder()
        row = store.save_step(
            run,
            _BRAND_REFERENCES_STEP,
            {"brand_refs": built.model_dump(mode="json")},
            None,
        )
    data = row["request"]["brand_refs"]
    selected = BrandReferencesSet.model_validate(data)
    if selected.block_version != BRAND_REFERENCE_BLOCK_VERSION:
        raise BrandReferenceError(
            "Las instrucciones de esta generación cambiaron. Vuelve a generar."
        )
    return selected


def request_data(request: GenerationRequest, provider: str, brand_id: UUID) -> dict[str, Any]:
    return {
        "provider": provider,
        "brand_id": str(brand_id),
        "task": request.task.value,
        "rendered_prompt": asdict(request.rendered_prompt),
        "params": dict(request.params),
        "output_schema": request.output_schema,
        "source_media_url": request.source_media_url,
    }


def request_from(data: Mapping[str, Any]) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask(data["task"]),
        rendered_prompt=RenderedPrompt(**data["rendered_prompt"]),
        params=data["params"],
        output_schema=data.get("output_schema"),
        source_media_url=data.get("source_media_url"),
    )


def encode_result(result: GenerationResult, media_store: Any, key: str, tenant_id: UUID) -> dict:
    data = asdict(result)
    data["usage"]["media_seconds"] = str(result.usage.media_seconds)

    def pack(value: Any) -> Any:
        if isinstance(value, bytes):
            object_key = f"{key}-{hashlib.sha256(value).hexdigest()[:16]}"
            keep = getattr(media_store, "keep", None)
            if keep is not None:
                if not keep(tenant_id, object_key, value, "application/octet-stream"):
                    raise CheckpointError("checkpoint media storage unavailable")
            else:
                media_store.write(object_key, value)
            return {"checkpoint_object": object_key}
        if isinstance(value, Mapping):
            return {k: pack(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [pack(v) for v in value]
        return value

    data["payload"] = pack(result.payload)
    return data


def decode_result(data: Mapping[str, Any], media_store: Any) -> GenerationResult:
    values = dict(data)
    values.pop("checkpoint_media", None)

    def unpack(value: Any) -> Any:
        if isinstance(value, dict) and set(value) == {"checkpoint_object"}:
            return media_store.read(value["checkpoint_object"])
        if isinstance(value, dict):
            return {k: unpack(v) for k, v in value.items()}
        if isinstance(value, list):
            return [unpack(v) for v in value]
        return value

    values["payload"] = unpack(values["payload"])
    usage = dict(values["usage"])
    usage["media_seconds"] = Decimal(str(usage["media_seconds"]))
    values["usage"] = Usage(**usage)
    return GenerationResult(**values)


class CheckpointRouter:
    """A worker-only router decorator. No preparation context means normal routing."""

    def __init__(self, router: Any, store: PipelineStore, media_store: Any) -> None:
        self.router, self.store, self.media_store = router, store, media_store

    def download(self, url: str) -> bytes:
        run = _preparation.get()
        if run is not None:
            with tenant_session(run.tenant_id) as session:
                key = session.execute(
                    text(f"""
                    SELECT result->>'checkpoint_media' FROM creative_pipeline_steps
                    WHERE {IDENTITY} AND result->>'media_url'=:url
                    LIMIT 1
                """),
                    {**run.params(), "url": url},
                ).scalar()
            if key:
                return self.media_store.read(key)
        from qualify_api.creative.media import _http_download

        return _http_download(url)

    def run(self, **kwargs: Any) -> RouterOutcome:
        try:
            return self._run(**kwargs)
        except (GenerationDeferred, CheckpointError):
            raise
        except Exception as exc:
            if in_preparation():
                raise CheckpointError("checkpoint preparation interrupted") from exc
            raise

    def _run(self, **kwargs: Any) -> RouterOutcome:
        run = _preparation.get()
        if run is None:
            return self.router.run(**kwargs)
        if kwargs["tenant_id"] != run.tenant_id:
            raise ValueError("checkpoint tenant mismatch")
        index = run.step
        run.step += 1
        provider = kwargs["chain"][0]
        asynchronous = provider in {"seedance", "omnihuman"}
        row = self.store.load_step(run, index)
        if asynchronous:
            job = self.store.video_job(run, run.video, provider)
            run.video += 1
        else:
            job = None
        if row is None:
            row = self.store.save_step(
                run, index, request_data(kwargs["request"], provider, kwargs["brand_id"]), job
            )
        if row["result"] is not None:
            return RouterOutcome(
                decode_result(row["result"], self.media_store),
                (Hop(provider, HopAction.SUCCEEDED),),
            )
        if row["error"] == "submitting":
            raise GenerationDeferred()
        if row["error"] is not None:
            return RouterOutcome(
                None,
                (
                    Hop(
                        provider,
                        HopAction.FAILED,
                        UNCERTAIN_REASON
                        if row["error"] in {"in_flight", "submission_uncertain"}
                        else row["error"],
                    ),
                ),
            )
        if asynchronous:
            self.store.ready(run, row["job_id"])
            raise GenerationDeferred()
        kwargs["request"] = request_from(row["request"])
        self.store.intent(run, index)
        outcome = self.router.run(**kwargs)
        identity = {**run.params(), "s": index}
        if outcome.result is not None:
            from qualify_api.creative.media import generated_object_key

            key = generated_object_key(
                run.tenant_id,
                run.draft_id,
                run.revision,
                f"checkpoint-{run.phase.replace(':', '-')}-{index}.bin",
            )
            self.store.complete_step(
                run.tenant_id,
                identity=identity,
                result=encode_result(outcome.result, self.media_store, key, run.tenant_id),
                run=run,
            )
        else:
            self.store.complete_step(
                run.tenant_id,
                identity=identity,
                result=None,
                error="; ".join(h.reason or "failed" for h in outcome.hops),
                run=run,
            )
        return outcome


@contextmanager
def preparing(run: Preparation) -> Iterator[None]:
    token = _preparation.set(run)
    try:
        yield
    finally:
        _preparation.reset(token)


def in_preparation() -> bool:
    return _preparation.get() is not None


def pipeline_assembly(method: Callable[..., Any]) -> Callable[..., Any]:
    """Fence the final database write, including all cost rows, in one transaction."""

    @wraps(method)
    def call(self: Any, *args: Any, **kwargs: Any) -> Any:
        run = _preparation.get()
        if run is None:
            return method(self, *args, **kwargs)
        with tenant_unit_of_work(run.tenant_id) as session:
            PipelineStore().fence(session, run)
            draft = (
                session.execute(
                    text("""
                SELECT revision,status FROM content_drafts WHERE id=:d FOR UPDATE
            """),
                    {"d": run.draft_id},
                )
                .mappings()
                .one()
            )
            if draft["revision"] != run.revision:
                raise CheckpointError("piece revision changed during preparation")
            if method.__name__ == "finish_generation" and draft["status"] != "drafting":
                return None
            if method.__name__ == "settle_final":
                state = session.execute(
                    text("""
                    SELECT params->'draft'->>'status' FROM image_assets
                    WHERE id=:a FOR UPDATE
                """),
                    {"a": kwargs["asset_id"]},
                ).scalar()
                if state != "rendering":
                    return None
            return method(self, *args, **kwargs)

    return call
