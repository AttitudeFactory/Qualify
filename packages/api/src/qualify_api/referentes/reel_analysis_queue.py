"""`AnalysisQueue` on Postgres, as `qualify_reels_worker` (ADR 44, m-24921056 VE-04a).

Only this module and `reel_analysis_worker` may import the role's door
(`qualify_shared.db.reels_worker`; static test `test_reel_analysis_door_sanctity.py`).

- **Claim** (`FOR UPDATE SKIP LOCKED`, the lease pattern of `creative/pipeline.py`): a
  `queued` row whose «not before» lease has passed, or a `running` row whose lease
  expired; `attempts < 3`; in the order of §13.3 — a URL still to download first (it
  expires), then the on-demand rows by `wanted_at`, then the rest, oldest first. The claim
  writes a fresh `lease_token`, `lease_until` and `attempts + 1`.
- **Every later write** carries `WHERE id = :id AND lease_token = :token AND status =
  'running'`: a process whose lease another one took writes nothing.
- **The cost guard** counts BEFORE the call, in one UPDATE: `model_calls < 2` on the row
  and the fleet's calls of the last 24 h under the cap.
- **The result** and its shots are written in ONE transaction, fenced by the token.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from qualify_shared.db.reels_worker import reels_worker_session
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from qualify_api.referentes.reel_analysis_store import (
    CALL_FLEET_CAP,
    CALL_LOST,
    CALL_OK,
    CALL_ROW_CAP,
    FLEET_CALLS_SQL,
    FLEET_LOCK_KEY,
    MAX_MODEL_CALLS,
    QUEUE_ORDER_SQL,
    URL_ERRORS,
    AnalysisRecord,
    Claimed,
    DescribeResult,
    SourceFacts,
    Spend,
    check_enqueueable,
    record_from_row,
    transcript_document,
)
from qualify_api.referentes.reel_analysis_types import (
    ANALYSIS_VERSION,
    ERROR_MODEL_FAILED,
    ERROR_SOURCE_UNAVAILABLE,
    STAGE_DONE,
    ReelSource,
)

_COLUMNS = (
    "id, network, post_id, analysis_version, status, post_url, created_at, stage, "
    "lease_token, lease_until, attempts, model_calls, error_code, wanted_at, "
    "pending_video_url, source_key, source_sha256, source_seconds, width, height, fps, "
    "covered_from_s, covered_to_s, edit_eligible, transcript, transcript_source, "
    "detector_version, sampling_version, sampling_params, model_id, model_revision, "
    "prompt_version, schema_version, input_tokens, output_tokens, cost_usd, reel_sheet, "
    "finished_at, source_purge_after, source_purged_at, frames_purged_at"
)
_A_COLUMNS = ", ".join(f"a.{c.strip()}" for c in _COLUMNS.split(","))
_CLAIMABLE = (
    "((status = 'queued' AND (lease_until IS NULL OR lease_until < :now)) "
    "OR (status = 'running' AND lease_until < :now)) AND attempts < :max_attempts"
)
_HOLDING = "id = :id AND lease_token = :token AND status = 'running'"
#: A paid call that produced no result still lands on the row (VE-04c review).
_ADD_SPEND = (
    "input_tokens = input_tokens + :spent_in, output_tokens = output_tokens + :spent_out, "
    "cost_usd = cost_usd + :spent_usd"
)


def _spend_params(spent: Spend | None) -> dict[str, Any]:
    spent = spent or Spend()
    return {
        "spent_in": spent.input_tokens,
        "spent_out": spent.output_tokens,
        "spent_usd": spent.cost_usd,
    }


class PostgresAnalysisQueue:
    """The worker's side of the shared analyses."""

    @contextmanager
    def _session(self) -> Iterator[Session]:
        with reels_worker_session() as session:
            yield session

    def _take(self, session: Session, where: str, params: dict[str, Any]) -> Claimed | None:
        token = uuid4()
        row = (
            session.execute(
                text(
                    f"WITH next AS (SELECT id FROM public_reel_analyses WHERE {where} "
                    f"ORDER BY {QUEUE_ORDER_SQL} LIMIT 1 FOR UPDATE SKIP LOCKED) "
                    "UPDATE public_reel_analyses a SET status = 'running', "
                    "lease_token = :token, lease_until = :until, attempts = a.attempts + 1 "
                    f"FROM next WHERE a.id = next.id RETURNING {_A_COLUMNS}"
                ),
                {**params, "token": token},
            )
            .mappings()
            .first()
        )
        return Claimed(record=record_from_row(row), token=token) if row else None

    def claim_next(
        self, now: datetime, lease: timedelta, *, download_only: bool, max_attempts: int
    ) -> Claimed | None:
        # A claim that may lead to a model call takes only rows of the current version:
        # an older queued row described by today's prompt would be saved under its old
        # version, paid for and never read. Downloads take any version.
        where = _CLAIMABLE + (
            " AND pending_video_url IS NOT NULL"
            if download_only
            else " AND analysis_version = :version"
        )
        with self._session() as session:
            return self._take(
                session,
                where,
                {
                    "now": now,
                    "until": now + lease,
                    "max_attempts": max_attempts,
                    "version": ANALYSIS_VERSION,
                },
            )

    def claim(
        self, analysis_id: UUID, now: datetime, lease: timedelta, *, max_attempts: int
    ) -> Claimed | None:
        with self._session() as session:
            return self._take(
                session,
                f"id = :id AND {_CLAIMABLE}",
                {"id": analysis_id, "now": now, "until": now + lease, "max_attempts": max_attempts},
            )

    def _update(self, sql: str, params: dict[str, Any]) -> bool:
        with self._session() as session:
            return session.execute(text(sql), params).rowcount == 1

    def renew(self, analysis_id: UUID, token: UUID, until: datetime) -> bool:
        return self._update(
            f"UPDATE public_reel_analyses SET lease_until = :until WHERE {_HOLDING}",
            {"id": analysis_id, "token": token, "until": until},
        )

    def set_stage(self, analysis_id: UUID, token: UUID, stage: str) -> bool:
        return self._update(
            f"UPDATE public_reel_analyses SET stage = :stage WHERE {_HOLDING}",
            {"id": analysis_id, "token": token, "stage": stage},
        )

    def record_source(
        self, analysis_id: UUID, token: UUID, facts: SourceFacts, purge_after: datetime
    ) -> bool:
        return self._update(
            "UPDATE public_reel_analyses SET pending_video_url = NULL, source_key = :key, "
            "source_sha256 = :sha, source_seconds = :secs, width = :w, height = :h, fps = :fps, "
            "covered_from_s = :cf, covered_to_s = :ct, edit_eligible = :edit, "
            f"source_purge_after = :purge WHERE {_HOLDING}",
            {
                "id": analysis_id,
                "token": token,
                "key": facts.source_key,
                "sha": facts.source_sha256,
                "secs": facts.source_seconds,
                "w": facts.width,
                "h": facts.height,
                "fps": facts.fps,
                "cf": facts.covered_from_s,
                "ct": facts.covered_to_s,
                "edit": facts.edit_eligible,
                "purge": purge_after,
            },
        )

    def add_model_call(
        self, analysis_id: UUID, token: UUID, *, now: datetime, since: datetime, fleet_cap: int
    ) -> str:
        with self._session() as session:
            row = session.execute(
                text(f"SELECT model_calls FROM public_reel_analyses WHERE {_HOLDING} FOR UPDATE"),
                {"id": analysis_id, "token": token},
            ).first()
            if row is None:
                return CALL_LOST
            if row.model_calls >= MAX_MODEL_CALLS:
                return CALL_ROW_CAP
            # One charger at a time across the fleet: count and increment are one step.
            session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": FLEET_LOCK_KEY})
            used = session.execute(text(FLEET_CALLS_SQL), {"since": since, "now": now}).scalar_one()
            if int(used) >= fleet_cap:
                return CALL_FLEET_CAP
            session.execute(
                text(
                    "UPDATE public_reel_analyses SET model_calls = model_calls + 1 "
                    f"WHERE {_HOLDING}"
                ),
                {"id": analysis_id, "token": token},
            )
            return CALL_OK

    def complete(
        self, analysis_id: UUID, token: UUID, result: DescribeResult, now: datetime
    ) -> bool:
        with self._session() as session:
            held = session.execute(
                text(f"SELECT id FROM public_reel_analyses WHERE {_HOLDING} FOR UPDATE"),
                {"id": analysis_id, "token": token},
            ).first()
            if held is None:
                return False
            session.execute(
                text("DELETE FROM public_reel_analysis_shots WHERE analysis_id = :id"),
                {"id": analysis_id},
            )
            for shot in result.shots:
                session.execute(
                    text(
                        "INSERT INTO public_reel_analysis_shots (analysis_id, shot_index, "
                        "start_s, end_s, frame_keys, frame_times_s, people_presence, "
                        "visible_faces, families, spoken_text) VALUES (:id, :i, :s, :e, "
                        "CAST(:keys AS text[]), CAST(:times AS real[]), :pp, :vf, :fam, :spoken)"
                    ).bindparams(bindparam("fam", type_=JSONB)),
                    {
                        "id": analysis_id,
                        "i": shot.shot_index,
                        "s": shot.start_s,
                        "e": shot.end_s,
                        "keys": list(shot.frame_keys),
                        "times": [float(t) for t in shot.frame_times_s],
                        "pp": shot.people_presence,
                        "vf": shot.visible_faces,
                        "fam": dict(shot.families),
                        "spoken": shot.spoken_text,
                    },
                )
            session.execute(
                text(
                    "UPDATE public_reel_analyses SET status = 'ok', stage = :done, "
                    "error_code = NULL, lease_token = NULL, lease_until = NULL, "
                    "reel_sheet = :sheet, model_id = :model, model_revision = :rev, "
                    "prompt_version = :pv, schema_version = :sv, detector_version = :dv, "
                    "sampling_version = :smv, sampling_params = :sp, "
                    "input_tokens = input_tokens + :tin, output_tokens = output_tokens + :tout, "
                    "cost_usd = cost_usd + :cost, "
                    "covered_to_s = COALESCE(CAST(:covered AS numeric), covered_to_s), "
                    f"finished_at = :now WHERE {_HOLDING}"
                ).bindparams(bindparam("sheet", type_=JSONB), bindparam("sp", type_=JSONB)),
                {
                    "id": analysis_id,
                    "token": token,
                    "done": STAGE_DONE,
                    "sheet": dict(result.reel_sheet),
                    "model": result.model_id,
                    "rev": result.model_revision,
                    "pv": result.prompt_version,
                    "sv": result.schema_version,
                    "dv": result.detector_version,
                    "smv": result.sampling_version,
                    "sp": json.loads(json.dumps(dict(result.sampling_params))),
                    "tin": result.input_tokens,
                    "tout": result.output_tokens,
                    "cost": result.cost_usd,
                    "covered": result.covered_to_s,
                    "now": now,
                },
            )
            return True

    def release(
        self,
        analysis_id: UUID,
        token: UUID,
        *,
        not_before: datetime | None = None,
        refund_call: bool = False,
    ) -> bool:
        return self._update(
            "UPDATE public_reel_analyses SET status = 'queued', "
            "lease_token = CAST(:fresh AS uuid), lease_until = :nb, "
            "attempts = GREATEST(attempts - 1, 0), "
            "model_calls = CASE WHEN :refund THEN GREATEST(model_calls - 1, 0) "
            f"ELSE model_calls END WHERE {_HOLDING}",
            {
                "id": analysis_id,
                "token": token,
                "fresh": uuid4() if not_before is not None else None,
                "nb": not_before,
                "refund": refund_call,
            },
        )

    def retry_later(
        self,
        analysis_id: UUID,
        token: UUID,
        error_code: str | None,
        not_before: datetime,
        *,
        spent: Spend | None = None,
    ) -> bool:
        return self._update(
            "UPDATE public_reel_analyses SET status = 'queued', error_code = :code, "
            f"lease_token = :fresh, lease_until = :nb, {_ADD_SPEND} WHERE {_HOLDING}",
            {
                "id": analysis_id,
                "token": token,
                "code": error_code,
                "fresh": uuid4(),
                "nb": not_before,
                **_spend_params(spent),
            },
        )

    def fail(
        self,
        analysis_id: UUID,
        token: UUID,
        error_code: str,
        now: datetime,
        *,
        spent: Spend | None = None,
    ) -> bool:
        return self._update(
            "UPDATE public_reel_analyses SET status = 'failed', error_code = :code, "
            f"lease_token = NULL, lease_until = NULL, finished_at = :now, {_ADD_SPEND} "
            f"WHERE {_HOLDING}",
            {"id": analysis_id, "token": token, "code": error_code, "now": now}
            | _spend_params(spent),
        )

    def reap_exhausted(self, now: datetime, max_attempts: int) -> int:
        with self._session() as session:
            return session.execute(
                text(
                    "UPDATE public_reel_analyses SET status = 'failed', "
                    "error_code = COALESCE(error_code, CASE WHEN source_key IS NULL "
                    "THEN :src ELSE :model END), lease_token = NULL, lease_until = NULL, "
                    "finished_at = :now WHERE status IN ('queued','running') "
                    "AND attempts >= :max AND (lease_until IS NULL OR lease_until < :now)"
                ),
                {
                    "now": now,
                    "max": max_attempts,
                    "src": ERROR_SOURCE_UNAVAILABLE,
                    "model": ERROR_MODEL_FAILED,
                },
            ).rowcount

    def ensure(
        self, source: ReelSource, version: int, now: datetime
    ) -> tuple[AnalysisRecord, bool]:
        check_enqueueable(source)
        transcript = transcript_document(source)
        with self._session() as session:
            created = session.execute(
                text(
                    "INSERT INTO public_reel_analyses (network, post_id, analysis_version, "
                    "post_url, pending_video_url, transcript, transcript_source, created_at) "
                    "VALUES (:n, :p, :v, :u, :url, :t, :ts, :now) "
                    "ON CONFLICT (network, post_id, analysis_version) DO NOTHING RETURNING id"
                ).bindparams(bindparam("t", type_=JSONB)),
                {
                    "n": source.network,
                    "p": source.post_id,
                    "v": version,
                    "u": source.post_url,
                    "url": source.video_url or None,
                    "t": transcript,
                    "ts": source.resolved_transcript_source(),
                    "now": now,
                },
            ).scalar()
            if created is None and source.video_url:
                # A queued row not downloaded yet (nor held) takes the URL just read.
                session.execute(
                    text(
                        "UPDATE public_reel_analyses SET pending_video_url = :url "
                        "WHERE network = :n AND post_id = :p AND analysis_version = :v "
                        "AND status = 'queued' AND source_key IS NULL AND lease_until IS NULL "
                        "AND pending_video_url IS DISTINCT FROM :url"
                    ),
                    {
                        "n": source.network,
                        "p": source.post_id,
                        "v": version,
                        "url": source.video_url,
                    },
                )
            if created is None and transcript is not None:
                # A row the screen made cannot carry a transcript (column grants); the
                # worker adds it the first time a run brings one.
                session.execute(
                    text(
                        "UPDATE public_reel_analyses SET transcript = :t, transcript_source = :ts "
                        "WHERE network = :n AND post_id = :p AND analysis_version = :v "
                        "AND transcript IS NULL"
                    ).bindparams(bindparam("t", type_=JSONB)),
                    {
                        "n": source.network,
                        "p": source.post_id,
                        "v": version,
                        "t": transcript,
                        "ts": source.resolved_transcript_source(),
                    },
                )
            row = (
                session.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM public_reel_analyses "
                        "WHERE network = :n AND post_id = :p AND analysis_version = :v"
                    ),
                    {"n": source.network, "p": source.post_id, "v": version},
                )
                .mappings()
                .one()
            )
        return record_from_row(row), created is not None

    def refresh_url(
        self, analysis_id: UUID, video_url: str, now: datetime, max_attempts: int
    ) -> AnalysisRecord | None:
        with self._session() as session:
            row = (
                session.execute(
                    text(
                        "UPDATE public_reel_analyses SET status = 'queued', error_code = NULL, "
                        "pending_video_url = :url, finished_at = NULL, stage = NULL "
                        "WHERE id = :id AND status = 'failed' AND error_code = ANY(:codes) "
                        "AND source_key IS NULL AND attempts < :max AND model_calls < :calls "
                        f"RETURNING {_COLUMNS}"
                    ),
                    {
                        "id": analysis_id,
                        "url": video_url,
                        "codes": list(URL_ERRORS),
                        "max": max_attempts,
                        "calls": MAX_MODEL_CALLS,
                    },
                )
                .mappings()
                .first()
            )
        return record_from_row(row) if row else None

    def get_by_key(self, network: str, post_id: str, version: int) -> AnalysisRecord | None:
        with self._session() as session:
            row = (
                session.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM public_reel_analyses "
                        "WHERE network = :n AND post_id = :p AND analysis_version = :v"
                    ),
                    {"n": network, "p": post_id, "v": version},
                )
                .mappings()
                .first()
            )
        return record_from_row(row) if row else None

    def get(self, analysis_id: UUID) -> AnalysisRecord | None:
        with self._session() as session:
            row = (
                session.execute(
                    text(f"SELECT {_COLUMNS} FROM public_reel_analyses WHERE id = :id"),
                    {"id": analysis_id},
                )
                .mappings()
                .first()
            )
        return record_from_row(row) if row else None


__all__ = ["PostgresAnalysisQueue"]
