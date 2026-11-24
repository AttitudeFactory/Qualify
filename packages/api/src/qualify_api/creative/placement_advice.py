"""The warning that a video's text may cover the product, and the better band (EF-20 phase 2,
m-25026599).

Deivid's decision (2026-11-23): «no quiero que bloquee si se pone el texto, sino que haya
una advertencia de que puede tapar el producto y que muestre la mejor posición». So the
server NEVER moves the text or the logo: it reads, once per uploaded video, which bands
of the frame the product occupies and which band it recommends for the text (and, as a
secondary hint, for the logo), and keeps that ADVICE. The editor (lane B) compares the
owner's chosen band with `subject_bands` — `covers_product`, pure and free — and shows the
warning with «Usar esta posición» when it covers the product.

**When it is made.** Once per video the owner uploads to the generator, on its light 480p
copy (ED-09, `upload_previews`: upright, whole length, before any compose), right after the
`media-worker` settles that copy (`catalog.media_worker._process_upload_preview`). The
copy is downloaded, 3 frames are sampled at 20/50/80 % of its length (variant `3f` of the
LUGAR-001 measurement: 48 of 51 frames with a free band left uncovered, 94 %) and
`placement_ai.VisionPlacer` asks Claude Haiku 5.5 once. Best effort: the switch off
(`QUALIFY_VIDEO_PLACEMENT_AI`), no key, a guard that says no, a fallback answer or any error
leaves no advice and the piece goes on exactly as before.

**Where it is kept.** In the `result` of that `upload_preview` job (`gallery_jobs`, JSONB,
tenant-scoped with RLS), under `ADVICE_FIELD`: the job is already one per uploaded file
(`uq_gallery_jobs_upload_preview`), so the advice is too — no migration. Idempotent: a
kept advice is never asked again (`AdviceStore.kept` is read BEFORE any call, and `keep`
writes only into a `done` row that has none). The editor reads it with
`placement_advice_for(tenant_id, source_keys)` (one query; another business's key is left
out, never looked up).

**Guards, backed by Postgres** (`PostgresPlacementLedger`): every call is RESERVED in
`creative_usage_events` BEFORE it is made, at the bound of one request
(`placement_ai.MAX_REQUEST_USD`), under one transaction-scoped advisory lock
(`GUARD_LOCK_KEY`) — so the cap check and the reservation are one step across processes
and retries:

- **per video:** at most `MAX_CALLS_PER_PIECE` (2) calls per uploaded file, ever (per
  `ADVICE_VERSION`). The reservation's id is `usage_event_id(tenant, source, n)`, n = 1..2:
  deterministic, so the count is the rows that exist and a retried reservation cannot
  add a third;
- **per fleet:** at most `placement_ai.fleet_daily()` calls (`QUALIFY_VIDEO_PLACEMENT_FLEET
  _DAILY`, 1500) in the last 24 h for every business together. The count is ONE integer
  read through `admin_session` (`AdminFleetCounter`), the same door the `media-worker`
  already uses to discover which tenants have jobs (ids only): no row of any business
  leaves it. Under the lock a second process counts only after the first one committed
  its reservation.

**Cost record.** The reservation IS the usage event (`unit = PLACEMENT_USAGE_UNIT`,
provider `anthropic`, draft-less, paid by the platform): after the call it is SETTLED to
what was billed (tokens and USD from the meter) — only when usage was measured: a request
error, or a call that measured nothing, leaves it at the bound. The platform pays the call
(`paid_by=platform`), so the brand's own dollar cap
(`creative_engine_config.budget_spent_usd`) is never touched: the event (`Numeric(12,6)`)
is the only record of the cost. The call has no vendor task id; its idempotency key is the
event id itself (uuid5 above) — a second settle of the same event changes nothing. A
process that dies between the call and the settle leaves the reservation at the bound: an
overcount of at most US$0.0021, never an undercount. The call is ALSO booked to the
business's consumption ledger by `claude_tools` (feature `video-placement`), as every
Claude call is; no report adds the two (the plan report and the cost alerts read
`creative_usage_events`, the consumption summary reads `consumption_ledger`).

Provenance in the advice: model id and revision, prompt version and fingerprint, the
frames sent (time, size, sha256 prefix), cost and pricing table version, the source and
copy keys, and when it was made.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

from qualify_creative.schemas import VIDEO_TEXT_PLACES

from qualify_api.creative import placement_ai as pa

logger = logging.getLogger(__name__)

#: The advice's own shape — bump on any change of what it records or how it is made
#: (a new version may be asked for again, within its own per-video cap).
ADVICE_VERSION = 1
#: The key under the `upload_preview` job's `result`.
ADVICE_FIELD = "placement_advice"
#: `creative_usage_events.unit` of a placement call: the marker the fleet cap counts.
PLACEMENT_USAGE_UNIT = "video_placement_token"
PROVIDER = "anthropic"
#: The advisory lock of the reservation (count + insert in one step, every process).
#: Next to the reel analysis' `4_492_105_601` / `_602`.
GUARD_LOCK_KEY = 4_492_105_620
_USAGE_NAMESPACE = UUID("6f1c2b7e-3d5a-4e8f-9a20-25026599a002")
_SOURCE_NAMESPACE = UUID("6f1c2b7e-3d5a-4e8f-9a20-25026599a003")

#: How the warning names each band (Spanish, `qualify-copy-es`).
#: The editor's own options read «Arriba / En el medio / Abajo».
BAND_WORDS: Mapping[str, str] = {"top": "arriba", "middle": "en el medio", "bottom": "abajo"}

#: What `PlacementAdvisor.advise` answers (logged by the worker; never shown to the owner).
OUTCOME_OFF = "off"
OUTCOME_KEPT = "kept"
OUTCOME_MADE = "made"
OUTCOME_NO_FRAMES = "no_frames"
OUTCOME_NOT_KEPT = "not_kept"
OUTCOME_FALLBACK = "fallback"
OUTCOME_ERROR = "error"


# --- the advice and its contract with the editor -------------------------------------------


def _bands(raw: Iterable[Any]) -> tuple[str, ...]:
    """The bands in `raw` that exist, in frame order (top, middle, bottom), once each."""
    wanted = {str(b) for b in raw}
    return tuple(band for band in VIDEO_TEXT_PLACES if band in wanted)


def covers_product(subject_bands: Iterable[str], band: str) -> bool:
    """Whether a layer in `band` covers the product: the band is one the product occupies.
    Pure and free — the editor calls it on every change of the owner's band."""
    return band in set(subject_bands)


def _join(words: Sequence[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " y " + words[-1]


def reason_text(subject_bands: Sequence[str], text_band: str) -> str:
    """The reason the owner reads, built from the bands (never from the model's own words,
    which may name a band `resolve_places` then moved)."""
    covered = _bands(subject_bands)
    where = BAND_WORDS.get(text_band, "")
    if not covered:
        return "No vimos tu producto en el video: puedes poner el texto donde quieras."
    if _fills_frame(covered):
        return f"Tu producto ocupa casi todo el video. Pon el texto {where}, donde lo tapa menos."
    seen = _join([BAND_WORDS[b] for b in covered])
    return f"Tu producto se ve {seen}. Pon el texto {where} para no taparlo."


def _fills_frame(subject_bands: Iterable[str]) -> bool:
    return len(_bands(subject_bands)) == len(VIDEO_TEXT_PLACES)


def _capitalized(band: str) -> str:
    words = BAND_WORDS.get(band, "")
    return words[:1].upper() + words[1:]


def use_band_text(band: str) -> str:
    """The label of the warning's button, which puts the text in `band` («Usar esta
    posición»): «Poner el texto arriba / en el medio / abajo»."""
    return f"Poner el texto {BAND_WORDS.get(band, '')}"


def warning_text(advice: PlacementAdvice, chosen_band: str) -> str | None:
    """The warning for the owner's `chosen_band`, or None when there is nothing to warn:
    the band does not cover the product, or it already is the recommended one (when the
    product fills every band, the recommended band is the one that covers it least)."""
    if chosen_band == advice.recommended_text_band:
        return None
    if not covers_product(advice.subject_bands, chosen_band):
        return None
    better = _capitalized(advice.recommended_text_band)
    if _fills_frame(advice.subject_bands):
        return f"Aquí el texto puede tapar tu producto. {better} lo tapa menos."
    return f"Aquí el texto puede tapar tu producto. {better} no lo tapa."


@dataclass(frozen=True)
class PlacementAdvice:
    """Where the product is in an uploaded video and where its text (and logo) would not
    cover it. The editor's contract is `to_params()`; see the module docstring."""

    source_key: str
    subject_bands: tuple[str, ...]
    recommended_text_band: str
    recommended_logo_band: str
    reason_es: str
    model: str
    prompt_version: str
    frames: tuple[Mapping[str, Any], ...]
    cost_usd: Decimal
    made_at: datetime
    subject: str | None = None
    preview_key: str | None = None
    model_revision: str | None = None
    prompt_fingerprint: str | None = None
    pricing_table_version: str | None = None
    version: int = ADVICE_VERSION

    def covers_product(self, band: str) -> bool:
        return covers_product(self.subject_bands, band)

    def warning(self, chosen_band: str) -> str | None:
        return warning_text(self, chosen_band)

    def to_params(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_key": self.source_key,
            "preview_key": self.preview_key,
            "subject": self.subject,
            "subject_bands": list(self.subject_bands),
            "recommended_text_band": self.recommended_text_band,
            "recommended_logo_band": self.recommended_logo_band,
            "reason_es": self.reason_es,
            # the warning's button («Usar esta posición»), worded for the recommended band
            "use_band_text": use_band_text(self.recommended_text_band),
            "model": self.model,
            "model_revision": self.model_revision,
            "prompt_version": self.prompt_version,
            "prompt_fingerprint": self.prompt_fingerprint,
            "frames": [dict(f) for f in self.frames],
            "cost_usd": str(self.cost_usd),
            "pricing_table_version": self.pricing_table_version,
            "made_at": self.made_at.isoformat(),
        }

    @classmethod
    def from_params(cls, raw: Any) -> PlacementAdvice | None:
        """The kept advice, or None when `raw` is not a usable one (never raises)."""
        if not isinstance(raw, Mapping):
            return None
        text, logo = raw.get("recommended_text_band"), raw.get("recommended_logo_band")
        bands = raw.get("subject_bands")
        if text not in VIDEO_TEXT_PLACES or logo not in VIDEO_TEXT_PLACES:
            return None
        if not isinstance(bands, list) or any(b not in VIDEO_TEXT_PLACES for b in bands):
            return None
        try:
            cost = Decimal(str(raw.get("cost_usd", "0")))
            made_at = datetime.fromisoformat(str(raw.get("made_at")))
            version = int(raw.get("version", 0))
        except (InvalidOperation, TypeError, ValueError):
            return None
        frames = raw.get("frames")
        return cls(
            source_key=str(raw.get("source_key") or ""),
            subject_bands=_bands(bands),
            recommended_text_band=text,
            recommended_logo_band=logo,
            reason_es=str(raw.get("reason_es") or ""),
            model=str(raw.get("model") or ""),
            prompt_version=str(raw.get("prompt_version") or ""),
            frames=tuple(f for f in frames if isinstance(f, Mapping))
            if isinstance(frames, list)
            else (),
            cost_usd=cost,
            made_at=made_at,
            subject=raw.get("subject") or None,
            preview_key=raw.get("preview_key") or None,
            model_revision=raw.get("model_revision") or None,
            prompt_fingerprint=raw.get("prompt_fingerprint") or None,
            pricing_table_version=raw.get("pricing_table_version") or None,
            version=version,
        )


def advice_from_decision(
    decision: pa.PlacementDecision,
    *,
    source_key: str,
    preview_key: str | None,
    made_at: datetime,
) -> PlacementAdvice | None:
    """The advice of a model answer; None for a fallback (today's places are no advice)."""
    if decision.fell_back:
        return None
    prov = decision.provenance
    return PlacementAdvice(
        source_key=source_key,
        preview_key=preview_key,
        subject=decision.subject,
        subject_bands=_bands(decision.subject_bands),
        recommended_text_band=decision.text_place,
        recommended_logo_band=decision.logo_place,
        reason_es=reason_text(decision.subject_bands, decision.text_place),
        model=str(prov.get("model_id") or pa.MODEL_ID),
        model_revision=prov.get("model_revision"),
        prompt_version=str(prov.get("prompt_version") or pa.PLACEMENT_PROMPT_VERSION),
        prompt_fingerprint=prov.get("prompt_fingerprint"),
        frames=tuple(dict(f) for f in prov.get("frames") or ()),
        cost_usd=decision.cost_usd,
        pricing_table_version=prov.get("pricing_table_version"),
        made_at=made_at,
    )


@dataclass(frozen=True)
class CombinedAdvice:
    """The advice of a piece made of several uploaded videos: the text keeps one band for
    the whole piece, so the product's bands are the union of every video's."""

    subject_bands: tuple[str, ...]
    recommended_text_band: str
    recommended_logo_band: str
    reason_es: str

    def covers_product(self, band: str) -> bool:
        return covers_product(self.subject_bands, band)


def combine_advice(advices: Sequence[PlacementAdvice]) -> CombinedAdvice | None:
    """One advice for a piece with several uploaded videos (None without any): the union
    of their bands, and the first free band of the usual preference for the text and the
    logo (`placement_ai.resolve_places`). One video: its own advice, as it was made."""
    if not advices:
        return None
    if len(advices) == 1:
        one = advices[0]
        return CombinedAdvice(
            one.subject_bands, one.recommended_text_band, one.recommended_logo_band, one.reason_es
        )
    covered = _bands(b for a in advices for b in a.subject_bands)
    text, logo, _ = pa.resolve_places(
        advices[0].recommended_text_band, advices[0].recommended_logo_band, covered
    )
    return CombinedAdvice(covered, text, logo, reason_text(covered, text))


# --- the Postgres-backed guard and the cost record ----------------------------------------


def source_piece_id(tenant_id: UUID, source_key: str) -> UUID:
    """The «piece» `VisionPlacer` counts calls for: the uploaded video itself."""
    return uuid5(_SOURCE_NAMESPACE, f"{tenant_id}:{source_key}")


def usage_event_id(tenant_id: UUID, source_key: str, call: int) -> UUID:
    """The `creative_usage_events.id` of the `call`-th call (1-based) for one uploaded
    video: deterministic, so the reservation is idempotent and the per-video cap is the
    count of these rows."""
    return uuid5(_USAGE_NAMESPACE, f"{tenant_id}:{source_key}:v{ADVICE_VERSION}:{call}")


class FleetCounter(Protocol):
    """How many placement calls every business made since `since` (a count only)."""

    def calls_since(self, since: datetime) -> int: ...


class PlacementLedger(Protocol):
    def reserve(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        source_key: str,
        now: datetime,
        fleet_cap: int,
    ) -> UUID:
        """Reserve the next call for this video BEFORE it is made, or raise
        `placement_ai.PlacementRefused` (`piece_cap`, `fleet_cap`)."""
        ...

    def settle(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        event_id: UUID,
        cost_usd: Decimal,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Set the reservation to what the call billed (idempotent)."""
        ...


class AdminFleetCounter:
    """The fleet's placement calls through `admin_session`: ONE integer, no row of any
    business. Only the `media-worker` (which already discovers tenants through this door)
    builds it."""

    def calls_since(self, since: datetime) -> int:
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415 — worker only
        from sqlalchemy import func, select  # noqa: PLC0415

        from qualify_api.creative import models as orm  # noqa: PLC0415

        with admin_session() as session:
            used = session.scalar(
                select(func.count())
                .select_from(orm.CreativeUsageEvent)
                .where(
                    orm.CreativeUsageEvent.unit == PLACEMENT_USAGE_UNIT,
                    orm.CreativeUsageEvent.occurred_at >= since,
                )
            )
        return int(used or 0)


class PostgresPlacementLedger:
    """`PlacementLedger` over `creative_usage_events` (see the module docstring). The
    tenant's rows go through `tenant_session` (RLS); the fleet's count through
    `fleet` (a count only)."""

    def __init__(self, fleet: FleetCounter, *, session_factory: Any = None) -> None:
        self._fleet = fleet
        self._session_factory = session_factory

    def _session(self, tenant_id: UUID) -> Any:
        if self._session_factory is not None:
            return self._session_factory(tenant_id)
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        return tenant_session(tenant_id)

    def reserve(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        source_key: str,
        now: datetime,
        fleet_cap: int,
    ) -> UUID:
        from qualify_creative.enums import PaidBy  # noqa: PLC0415
        from sqlalchemy import select, text  # noqa: PLC0415
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        from qualify_api.claude_tools import PRICING_TABLE_VERSION  # noqa: PLC0415
        from qualify_api.creative import models as orm  # noqa: PLC0415

        ids = [
            usage_event_id(tenant_id, source_key, n) for n in range(1, pa.MAX_CALLS_PER_PIECE + 1)
        ]
        with self._session(tenant_id) as session:
            # One reserver at a time, every process: the count and the insert are one step
            # (released at commit, after the reservation is visible to the next one).
            session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": GUARD_LOCK_KEY})
            taken = set(
                session.scalars(
                    select(orm.CreativeUsageEvent.id).where(orm.CreativeUsageEvent.id.in_(ids))
                )
            )
            free = [event_id for event_id in ids if event_id not in taken]
            if not free:
                raise pa.PlacementRefused(
                    "piece_cap", f"video: {pa.MAX_CALLS_PER_PIECE} calls already made"
                )
            used = self._fleet.calls_since(now - timedelta(hours=24))
            if used >= fleet_cap:
                raise pa.PlacementRefused("fleet_cap", f"fleet: {fleet_cap} calls a day")
            event_id = free[0]
            booked = session.scalar(
                insert(orm.CreativeUsageEvent)
                .values(
                    id=event_id,
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    draft_id=None,
                    provider=PROVIDER,
                    model_id=pa.MODEL_ID,
                    unit=PLACEMENT_USAGE_UNIT,
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_creation_tokens=0,
                    pieces=0,
                    cost_usd=pa.MAX_REQUEST_USD,
                    paid_by=PaidBy.PLATFORM.value,
                    pricing_table_version=PRICING_TABLE_VERSION,
                    occurred_at=now,
                )
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(orm.CreativeUsageEvent.id)
            )
            if booked is None:  # taken in between (cannot happen under the lock): refuse
                raise pa.PlacementRefused("piece_cap", "reservation already taken")
        return event_id

    def settle(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        event_id: UUID,
        cost_usd: Decimal,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        from qualify_api.creative import models as orm  # noqa: PLC0415

        with self._session(tenant_id) as session:
            row = session.get(orm.CreativeUsageEvent, event_id, with_for_update=True)
            if row is None:
                return
            # the platform pays this call: `creative_engine_config.budget_spent_usd` (the
            # brand's own dollar cap) is never touched — the event is the only record
            row.cost_usd = cost_usd
            row.input_tokens = int(input_tokens)
            row.output_tokens = int(output_tokens)


@dataclass
class SourceCallGuard:
    """`placement_ai.CallGuard` for ONE uploaded video, over a `PlacementLedger`: `charge`
    reserves the call (or raises `PlacementRefused`) and remembers the reservation, which
    `settle` then sets to what was billed."""

    ledger: PlacementLedger
    tenant_id: UUID
    brand_id: UUID
    source_key: str
    fleet_cap: int
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    reserved: list[UUID] = field(default_factory=list)

    def charge(self, piece_id: UUID) -> None:
        self.reserved.append(
            self.ledger.reserve(
                tenant_id=self.tenant_id,
                brand_id=self.brand_id,
                source_key=self.source_key,
                now=self.clock(),
                fleet_cap=self.fleet_cap,
            )
        )

    def settle(self, decision: pa.PlacementDecision) -> bool:
        """Set the reservation to the MEASURED usage; True when it did. A request error
        (the call may have been billed with no answer read) or a call that measured no
        usage leaves it at the bound: an overcount, never an undercount."""
        if not self.reserved:
            return False
        prov = decision.provenance
        input_tokens = int(prov.get("input_tokens") or 0)
        output_tokens = int(prov.get("output_tokens") or 0)
        if decision.fallback_reason == pa.FALLBACK_REQUEST_ERROR:
            return False
        if not (input_tokens or output_tokens) or decision.cost_usd <= 0:
            return False
        self.ledger.settle(
            tenant_id=self.tenant_id,
            brand_id=self.brand_id,
            event_id=self.reserved[-1],
            cost_usd=decision.cost_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return True


# --- where the advice is kept -------------------------------------------------------------


class AdviceStore(Protocol):
    def kept(self, tenant_id: UUID, source_key: str) -> PlacementAdvice | None: ...

    def keep(self, tenant_id: UUID, job_id: UUID, advice: PlacementAdvice) -> bool: ...


def _preview_job_keys(source_key: str) -> list[str]:
    from qualify_api.creative.upload_previews import (  # noqa: PLC0415
        READ_VERSIONS,
        preview_job_key,
    )

    return [preview_job_key(source_key, version) for version in READ_VERSIONS]


class GalleryJobAdviceStore:
    """The advice in the `result` of the video's `upload_preview` job (`tenant_session`)."""

    def kept(self, tenant_id: UUID, source_key: str) -> PlacementAdvice | None:
        return placement_advice_for(tenant_id, [source_key]).get(source_key)

    def keep(self, tenant_id: UUID, job_id: UUID, advice: PlacementAdvice) -> bool:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.catalog.business_media_models import (  # noqa: PLC0415
            JOB_UPLOAD_PREVIEW,
            STATUS_DONE,
            GalleryJob,
        )

        with tenant_session(tenant_id) as session:
            row = session.get(GalleryJob, job_id, with_for_update=True)
            if row is None or row.kind != JOB_UPLOAD_PREVIEW or row.status != STATUS_DONE:
                return False
            result = dict(row.result or {})
            if ADVICE_FIELD in result:  # kept by an earlier run: never overwritten
                return False
            result[ADVICE_FIELD] = advice.to_params()
            row.result = result  # a new dict: JSONB change detected
        return True


def placement_advice_for(tenant_id: UUID, source_keys: Sequence[str]) -> dict[str, PlacementAdvice]:
    """THE editor's read: the kept advice of each of `source_keys` (ONE query). A key that
    is not this tenant's uploaded video is left out, never looked up; a video without
    advice is simply absent."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.catalog.business_media_models import (  # noqa: PLC0415
        JOB_UPLOAD_PREVIEW,
        STATUS_DONE,
        GalleryJob,
    )
    from qualify_api.creative.upload_previews import is_previewable  # noqa: PLC0415

    keys = [key for key in dict.fromkeys(source_keys) if is_previewable(tenant_id, key)]
    if not keys:
        return {}
    by_job_key = {job_key: key for key in keys for job_key in _preview_job_keys(key)}
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(GalleryJob.idempotency_key, GalleryJob.result)
            .where(
                GalleryJob.kind == JOB_UPLOAD_PREVIEW,
                GalleryJob.status == STATUS_DONE,
                GalleryJob.idempotency_key.in_(list(by_job_key)),
            )
            .order_by(GalleryJob.created_at.desc(), GalleryJob.id)
        ).all()
    return fold_advice(by_job_key, rows)


def fold_advice(by_job_key: Mapping[str, str], rows: Iterable[Any]) -> dict[str, PlacementAdvice]:
    """The first usable advice per source key among `rows` (newest first)."""
    out: dict[str, PlacementAdvice] = {}
    for row in rows:
        key = by_job_key.get(row.idempotency_key)
        if key is None or key in out:
            continue
        advice = PlacementAdvice.from_params((row.result or {}).get(ADVICE_FIELD))
        if advice is not None and advice.source_key == key:
            out[key] = advice
    return out


# --- the run -------------------------------------------------------------------------------


def preview_frames(path: Path) -> list[pa.PlacementFrame]:
    """The `3f` frames (20/50/80 %) of the copy at `path`; none when its length is unknown."""
    from qualify_creative.video.source_limits import read_header  # noqa: PLC0415

    duration = read_header(path).duration_s
    if not duration:
        return []
    return pa.sample_placement_frames(path, float(duration))


Fetch = Callable[[UUID, str, Path], None]


@dataclass
class PlacementAdvisor:
    """Makes and keeps the advice of one uploaded video (see the module docstring). Never
    raises: every outcome is a code the worker logs."""

    ledger: PlacementLedger
    store: AdviceStore
    placer_factory: Callable[[pa.CallGuard], pa.VisionPlacer] = field(
        default=lambda guard: pa.VisionPlacer(guard=guard)
    )
    frames_of: Callable[[Path], list[pa.PlacementFrame]] = preview_frames
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    env: Mapping[str, str] | None = None

    def advise(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        job_id: UUID,
        source_key: str,
        preview_key: str,
        fetch: Fetch,
    ) -> str:
        try:
            return self._advise(
                tenant_id=tenant_id,
                brand_id=brand_id,
                job_id=job_id,
                source_key=source_key,
                preview_key=preview_key,
                fetch=fetch,
            )
        except Exception as exc:  # noqa: BLE001 — best effort: no advice, the piece goes on
            logger.warning("video placement advice failed: %s", type(exc).__name__)
            return f"{OUTCOME_ERROR}:{type(exc).__name__}"

    def _advise(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        job_id: UUID,
        source_key: str,
        preview_key: str,
        fetch: Fetch,
    ) -> str:
        if not pa.placement_enabled(self.env):
            return OUTCOME_OFF
        if self.store.kept(tenant_id, source_key) is not None:
            return OUTCOME_KEPT  # idempotent: one advice per uploaded video
        with tempfile.TemporaryDirectory(prefix="qualify-placement-") as tmp:
            copy = Path(tmp) / "preview.mp4"
            fetch(tenant_id, preview_key, copy)
            frames = self.frames_of(copy)
        if not frames:
            return OUTCOME_NO_FRAMES
        guard = SourceCallGuard(
            ledger=self.ledger,
            tenant_id=tenant_id,
            brand_id=brand_id,
            source_key=source_key,
            fleet_cap=pa.fleet_daily(self.env),
            clock=self.clock,
        )
        decision = self.placer_factory(guard).place(
            frames,
            tenant_id=tenant_id,
            piece_id=source_piece_id(tenant_id, source_key),
            brand_id=brand_id,
        )
        try:
            guard.settle(decision)
        except Exception as exc:  # noqa: BLE001 — the reservation stays at the bound
            logger.warning("video placement usage not settled: %s", type(exc).__name__)
        advice = advice_from_decision(
            decision, source_key=source_key, preview_key=preview_key, made_at=self.clock()
        )
        if advice is None:
            return f"{OUTCOME_FALLBACK}:{decision.fallback_reason}"
        if not self.store.keep(tenant_id, job_id, advice):
            return OUTCOME_NOT_KEPT
        return OUTCOME_MADE


#: The `media-worker` runs one job at a time: a hung request must not hold the queue.
#: 60 s and one retry at most (the measured call takes ~7 s).
CLIENT_TIMEOUT_S = 60.0
CLIENT_MAX_RETRIES = 1


def bounded_client(api_key: str) -> Any:
    """Anthropic with a bounded wait (`CLIENT_TIMEOUT_S`, `CLIENT_MAX_RETRIES`)."""
    import anthropic  # noqa: PLC0415 — lazy, like `claude_tools.default_client`

    return anthropic.Anthropic(
        api_key=api_key, timeout=CLIENT_TIMEOUT_S, max_retries=CLIENT_MAX_RETRIES
    )


def production_placement_advisor() -> PlacementAdvisor:
    """The `media-worker`'s advisor: Postgres guards, advice in the preview job, a bounded
    Anthropic client."""
    return PlacementAdvisor(
        ledger=PostgresPlacementLedger(AdminFleetCounter()),
        store=GalleryJobAdviceStore(),
        placer_factory=lambda guard: pa.VisionPlacer(guard=guard, client_factory=bounded_client),
    )


__all__ = [
    "ADVICE_FIELD",
    "ADVICE_VERSION",
    "BAND_WORDS",
    "CLIENT_MAX_RETRIES",
    "CLIENT_TIMEOUT_S",
    "GUARD_LOCK_KEY",
    "PLACEMENT_USAGE_UNIT",
    "AdminFleetCounter",
    "AdviceStore",
    "CombinedAdvice",
    "FleetCounter",
    "GalleryJobAdviceStore",
    "PlacementAdvice",
    "PlacementAdvisor",
    "PlacementLedger",
    "PostgresPlacementLedger",
    "SourceCallGuard",
    "advice_from_decision",
    "bounded_client",
    "combine_advice",
    "covers_product",
    "fold_advice",
    "placement_advice_for",
    "preview_frames",
    "production_placement_advisor",
    "reason_text",
    "source_piece_id",
    "usage_event_id",
    "use_band_text",
    "warning_text",
]
