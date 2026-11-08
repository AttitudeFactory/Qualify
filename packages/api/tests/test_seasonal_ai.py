"""«Crear con IA» for the seasonal library (m-24976893), offline: the estimate from the
versioned price table, the batch and its quote, the confirmation before anything paid,
and the creative-worker executor with a FAKE Seedance adapter — no paid call, no R2 (an
in-memory store behind the real `ObjectGate`), no network."""

from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image
from qualify_creative.providers import GenerationResult, Usage
from qualify_creative.seasonal import ai as ai_mod
from qualify_creative.seasonal.ai import (
    DEFAULT_AI_VIDEO_MODEL,
    estimate_ai_video_cost_usd,
    quote,
    ratio_for,
)
from qualify_creative.seasonal.video import VideoResult
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore

from qualify_api.creative import seasonal_ai as sai
from qualify_api.creative.seasonal_ai import (
    BUDGET_CAP,
    KIND_SEASONAL_VIDEO,
    REASON_TEXT,
    VENDOR_FAILED,
    AiMedium,
    Budget,
    KindRoutedExecutor,
    PriceGuardRefused,
    SeasonalAiVideoExecutor,
)
from qualify_api.creative.worker.executor import JobContext
from qualify_api.whatsapp.seasonal import (
    AI_JOB_KIND,
    AI_RECIPE,
    STANDARD_BATCH,
    CostNotConfirmed,
    MemorySeasonalRepository,
    MemorySourceReads,
    ModeNotAvailable,
    NoPhotoToAnimate,
    SeasonalMediaService,
)

TENANT = UUID("a0000000-0000-4000-8000-0000000a1001")
BRAND = UUID("b0000000-0000-4000-8000-0000000a1001")
SEASON = "navidad-2026"


# --- the estimate -------------------------------------------------------------------------


def test_the_estimate_comes_from_the_price_table() -> None:
    # 1.0 pro fast, 480p, 5 s: the largest frame of 1:1 / 3:4 / 9:16 (480×864) — 48,600
    # tokens × US$1.0 per million
    assert estimate_ai_video_cost_usd() == Decimal("0.048600")
    assert estimate_ai_video_cost_usd(ratio="1:1") == Decimal("0.048000")
    # 2.5 as the doc measured it (≈ US$0.53)
    assert estimate_ai_video_cost_usd("dreamina-seedance-2-5-260628").quantize(
        Decimal("0.01")
    ) == Decimal("0.53")
    assert DEFAULT_AI_VIDEO_MODEL.startswith("seedance-1-0-pro-fast")


def test_the_screen_shows_cents_rounded_up_and_the_total() -> None:
    q = quote(3)
    assert (q.per_video_usd, q.total_usd, q.videos) == (Decimal("0.05"), Decimal("0.15"), 3)
    assert quote(2, per_video_usd=Decimal("0.0401")).per_video_usd == Decimal("0.05")


def test_ratio_follows_the_photo() -> None:
    assert ratio_for(Image.new("RGB", (1080, 1350))) == "3:4"
    assert ratio_for(Image.new("RGB", (1080, 1920))) == "9:16"
    assert ratio_for(Image.new("RGB", (1600, 900))) == "1:1"


# --- the service: option, quote, confirmation ---------------------------------------------


def _service(pieces: int = 3, *, ai_mode: bool = True) -> tuple[SeasonalMediaService, Any]:
    repo = MemorySeasonalRepository()
    reads = MemorySourceReads()
    reads.pieces[(TENANT, BRAND)] = [uuid4() for _ in range(pieces)]
    reads.logos[(TENANT, BRAND)] = f"t/{TENANT}/brand/{BRAND}/logo.png"
    service = SeasonalMediaService(
        repo,
        reads,
        ai_mode=ai_mode,
        ai_video_estimate_usd=estimate_ai_video_cost_usd if ai_mode else None,
    )
    return service, repo


def _quoted(service: SeasonalMediaService) -> list[UUID]:
    return [p.draft_id for p in service.quote_batch(TENANT, BRAND, "ai").photos]


def test_ai_makes_only_videos() -> None:
    assert {s.kind for s in STANDARD_BATCH["ai"]} == {"video"}
    assert {s.recipe for s in STANDARD_BATCH["ai"]} == {AI_RECIPE}
    assert all(s.recipe != AI_RECIPE for s in STANDARD_BATCH["free"])  # never the default


def test_ai_is_refused_until_wired_or_without_a_photo() -> None:
    off, _ = _service(ai_mode=False)
    with pytest.raises(ModeNotAvailable):
        off.quote_batch(TENANT, BRAND, "ai")
    with pytest.raises(ValueError):
        SeasonalMediaService(MemorySeasonalRepository(), MemorySourceReads(), ai_mode=True)
    no_photo, _ = _service(pieces=0)
    with pytest.raises(NoPhotoToAnimate):
        no_photo.quote_batch(TENANT, BRAND, "ai")


def test_the_quote_before_creating() -> None:
    service, repo = _service(pieces=3)
    q = service.quote_batch(TENANT, BRAND, "ai")
    assert (q.ai_videos, q.videos, q.stickers) == (3, 3, 0)
    assert (q.per_ai_video_usd, q.total_usd) == (Decimal("0.05"), Decimal("0.15"))
    assert repo.rows == {} and repo.jobs == []  # quoting writes nothing
    one, _ = _service(pieces=1)
    assert one.quote_batch(TENANT, BRAND, "ai").ai_videos == 1  # one photo, one video
    free, _ = _service()
    assert free.quote_batch(TENANT, BRAND, "free").total_usd == 0


def test_nothing_is_planned_without_the_confirmed_cost() -> None:
    service, repo = _service()
    for accepted in (None, Decimal("0.10")):
        with pytest.raises(CostNotConfirmed):
            service.plan_batch(
                TENANT, BRAND, SEASON, "Navidad", "ai", None, accepted_total_usd=accepted
            )
    assert repo.rows == {} and repo.jobs == []
    rows = service.plan_batch(
        TENANT,
        BRAND,
        SEASON,
        "Navidad",
        "ai",
        None,
        accepted_total_usd=Decimal("0.15"),
        accepted_draft_ids=_quoted(service),
    )
    assert len(rows) == 3 and {r.recipe for r in rows} == {AI_RECIPE}
    assert {j["kind"] for j in repo.jobs} == {AI_JOB_KIND}  # creative-worker, not media
    assert len({r.source_ref for r in rows}) == 3  # one photo each


def test_another_paid_video_asks_for_its_cost_again() -> None:
    service, _ = _service(pieces=1)
    (row,) = service.plan_batch(
        TENANT,
        BRAND,
        SEASON,
        "Navidad",
        "ai",
        None,
        accepted_total_usd=Decimal("0.05"),
        accepted_draft_ids=_quoted(service),
    )
    service.mark_failed(
        tenant_id=TENANT, brand_id=BRAND, media_id=row.id, attempt=1, reason="vendor_failed"
    )
    with pytest.raises(CostNotConfirmed):
        service.request_another(TENANT, BRAND, row.id, None)
    again = service.request_another(TENANT, BRAND, row.id, None, accepted_cost_usd=Decimal("0.05"))
    assert again.attempt == 2


def test_reasons_have_spanish_text() -> None:
    assert REASON_TEXT[BUDGET_CAP] == "Esta pieza superaría tu tope de gasto."
    assert VENDOR_FAILED in REASON_TEXT


# --- the executor -------------------------------------------------------------------------


@dataclass
class State:
    task_id: str
    status: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled", "expired")


class FakeSeedance:
    """Records every call; never reaches a network."""

    def __init__(self, *, status: str = "succeeded", tokens: int = 48_600) -> None:
        self.status = status
        self.tokens = tokens
        self.submitted: list[Any] = []
        self.data: dict[str, Any] = {}

    def submit(self, request: Any, *, api_key: str, priority: int | None = None) -> str:
        self.submitted.append(request)
        observer = request.observer
        if observer is not None:
            observer.created("task-1")
        return "task-1"

    def poll(self, task_id: str, *, api_key: str) -> State:
        return State(task_id, self.status, dict(self.data))

    def result(self, request: Any, state: State) -> GenerationResult:
        return GenerationResult(
            payload={"task_id": state.task_id, "video_url": "https://x.bytepluses.com/v.mp4",
                     "tokens": self.tokens},
            model_id=DEFAULT_AI_VIDEO_MODEL,
            provider="byteplus",
            usage=Usage(output_tokens=self.tokens),
        )  # fmt: skip

    def poll_delay(self, status: str, queued_for: float) -> float:
        return 1.0


class Reads:
    def __init__(self, repo: MemorySeasonalRepository, photo_key: str) -> None:
        self.repo = repo
        self.photo_key = photo_key
        self.remaining: Decimal | None = Decimal("5")

    def medium(self, tenant_id: UUID, media_id: UUID) -> AiMedium | None:
        m = self.repo.get(tenant_id=tenant_id, media_id=media_id)
        if m is None:
            return None
        return AiMedium(m.id, m.tenant_id, m.brand_id, m.season_key, m.kind, m.recipe,
                        m.source_kind, m.source_ref, m.status, m.attempt)  # fmt: skip

    def piece_image_keys(self, tenant_id: UUID, brand_id: UUID, draft_ids: Any) -> list[str]:
        return [self.photo_key] if draft_ids else []

    def budget(self, tenant_id: UUID, brand_id: UUID) -> Budget | None:
        return None if self.remaining is None else Budget(self.remaining)


class Ledger:
    """Keyed by the vendor task, like the Postgres ledger (the usage row's id)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(self, **row: Any) -> bool:
        if any(r["vendor_task_id"] == row["vendor_task_id"] for r in self.rows):
            return False
        self.rows.append(row)
        return True


class Recorder:
    def __init__(self, job: JobContext) -> None:
        self.job = job
        self.ids: list[str] = []

    def created(self, task_id: str) -> None:
        self.ids.append(task_id)

    def polled(self, task_id: str, status: str) -> None:
        pass


def _ctx(
    media_id: UUID,
    attempt: int = 1,
    kind: str = KIND_SEASONAL_VIDEO,
    pricing_version: str | None = "v7",
) -> JobContext:
    return JobContext(
        job_id=uuid4(),
        tenant_id=TENANT,
        draft_id=None,
        kind=kind,
        revision=0,
        position=0,
        vendor_model="byteplus:seedance-2-5",
        lane="immediate",
        vendor_priority=5,
        deadline=None,
        claim_token=1,
        seasonal_media_id=media_id,
        attempt=attempt,
        pricing_version=pricing_version,
    )


class World:
    def __init__(self, tmp_path: Path, adapter: FakeSeedance | None = None) -> None:
        self.service, self.repo = _service(pieces=1)
        (self.row,) = self.service.plan_batch(
            TENANT,
            BRAND,
            SEASON,
            "Navidad",
            "ai",
            None,
            accepted_total_usd=Decimal("0.05"),
            accepted_draft_ids=_quoted(self.service),
        )
        self.store = MemoryObjectStore()
        photo_key = f"t/{TENANT}/media/x/0.jpg"
        buf = io.BytesIO()
        Image.new("RGB", (1080, 1350), (200, 120, 40)).save(buf, format="JPEG")
        self.store.objects[photo_key] = buf.getvalue()
        self.reads = Reads(self.repo, photo_key)
        self.ledger = Ledger()
        self.adapter = adapter or FakeSeedance()
        self.recorders: list[Recorder] = []
        raw = tmp_path / "raw.mp4"
        raw.write_bytes(b"vendor-mp4")

        @contextlib.contextmanager
        def download(url: str) -> Iterator[Path]:
            yield raw

        def recorder(job: JobContext) -> Recorder:
            self.recorders.append(Recorder(job))
            return self.recorders[-1]

        self.executor = SeasonalAiVideoExecutor(
            adapter=self.adapter,
            reads=self.reads,
            objects=ObjectGate(self.store),
            marks=self.service,
            ledger=self.ledger,
            api_key=lambda t, b: "test-key-not-real",
            download=download,
            recorder=recorder,
            tmp_root=tmp_path,
        )

    def medium(self):  # noqa: ANN201
        return self.repo.get(tenant_id=TENANT, media_id=self.row.id)

    def seasonal_keys(self) -> list[str]:
        return [k for k in self.store.objects if k.startswith("seasonal/")]


@pytest.fixture
def fake_clip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def clip(raw: Path, work: Path, **kw: Any) -> VideoResult:
        out = work / "clip.mp4"
        out.write_bytes(b"clean-mp4")
        return VideoResult(out, 720, 900, 5000, 120, 9, 28, False)

    monkeypatch.setattr(sai, "clip_from_video", clip)


def test_the_price_guard_stops_before_the_vendor(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.reads.remaining = Decimal("0.01")
    with pytest.raises(PriceGuardRefused):
        w.executor.submit(_ctx(w.row.id))
    assert w.adapter.submitted == []
    assert w.medium().status == "failed" and w.medium().fail_reason == BUDGET_CAP


def test_submit_sends_the_photo_once_and_records_the_task(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.reads.remaining = Decimal("5")
    assert w.executor.submit(_ctx(w.row.id)) == "task-1"
    (request,) = w.adapter.submitted
    params = request.params
    assert params["model"] == DEFAULT_AI_VIDEO_MODEL and params["ratio"] == "3:4"
    assert str(params["first_frame"]).startswith("data:image/jpeg;base64,")  # never a URL
    assert params["resolution"] == "480p" and params["duration_seconds"] == 5
    assert w.recorders[0].ids == ["task-1"]  # recorded at acceptance, before any wait


def test_a_stale_or_settled_job_is_never_submitted(tmp_path: Path) -> None:
    w = World(tmp_path)
    for ctx in (_ctx(w.row.id, attempt=2), _ctx(w.row.id, kind="final"), _ctx(uuid4())):
        with pytest.raises(ValueError):
            w.executor.submit(ctx)
    assert w.adapter.submitted == []


def test_finish_stores_the_clip_and_records_the_real_cost(tmp_path: Path, fake_clip: None) -> None:
    w = World(tmp_path, FakeSeedance(tokens=50_000))
    w.executor.finish(_ctx(w.row.id), "task-1", "succeeded")
    m = w.medium()
    key = f"seasonal/{TENANT}/{BRAND}/{SEASON}/{w.row.id}-1.mp4"
    assert m.status == "ready" and m.object_key == key
    assert w.store.objects[key] == b"clean-mp4" and w.store.content_types[key] == "video/mp4"
    # 50,000 billed tokens × US$1.0 / million — the row and the ledger say the same
    assert m.cost_usd == Decimal("0.050000")
    (usage,) = w.ledger.rows
    assert usage["cost_usd"] == m.cost_usd and usage["tokens"] == 50_000
    assert usage["model_id"] == DEFAULT_AI_VIDEO_MODEL and usage["pricing_version"] == "v7"


def test_finish_is_idempotent(tmp_path: Path, fake_clip: None) -> None:
    w = World(tmp_path)
    w.executor.finish(_ctx(w.row.id), "task-1", "succeeded")
    puts = len(w.store.puts)
    w.executor.finish(_ctx(w.row.id), "task-1", "succeeded")  # the runner retried
    assert len(w.store.puts) == puts and len(w.ledger.rows) == 1


def test_a_failed_task_is_not_billed_and_the_row_says_why(tmp_path: Path) -> None:
    w = World(tmp_path, FakeSeedance(status="failed"))
    w.executor.finish(_ctx(w.row.id), "task-1", "failed")
    assert w.medium().fail_reason == VENDOR_FAILED and w.ledger.rows == []
    assert w.seasonal_keys() == []


def test_another_attempt_meanwhile_drops_the_result_and_its_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_clip: None
) -> None:
    w = World(tmp_path)
    real = w.service.mark_ready

    def ask_again_first(**kw: Any) -> Any:
        w.service.mark_failed(
            tenant_id=TENANT, brand_id=BRAND, media_id=w.row.id, attempt=1, reason="x"
        )
        w.service.request_another(TENANT, BRAND, w.row.id, None, accepted_cost_usd=Decimal("0.05"))
        return real(**kw)

    monkeypatch.setattr(w.service, "mark_ready", ask_again_first)
    w.executor.finish(_ctx(w.row.id), "task-1", "succeeded")
    assert w.medium().attempt == 2 and w.medium().status == "pending"
    assert w.seasonal_keys() == []  # the file attempt 1 wrote is gone


def test_the_seedance_pool_routes_by_kind() -> None:
    calls: list[str] = []

    class Probe:
        def __init__(self, name: str) -> None:
            self.name = name

        def submit(self, job: JobContext) -> str:
            calls.append(self.name)
            return self.name

    routed = KindRoutedExecutor(Probe("generator"), {KIND_SEASONAL_VIDEO: Probe("seasonal")})
    routed.submit(_ctx(uuid4()))
    routed.submit(_ctx(uuid4(), kind="final"))
    assert calls == ["seasonal", "generator"]


# --- FFmpeg post-process (skipped without ffmpeg) -----------------------------------------


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)
def test_a_vendor_clip_becomes_a_silent_main_profile_mp4(tmp_path: Path) -> None:
    from qualify_creative.seasonal.video import MAX_VIDEO_BYTES, clip_from_video

    raw = tmp_path / "vendor.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=544x736:rate=24:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
         "-c:a", "aac", "-shortest", str(raw)],
        check=True,
    )  # fmt: skip
    out = clip_from_video(raw, tmp_path)
    assert out.bytes <= MAX_VIDEO_BYTES and out.width == 720 and out.duration_ms <= 5100
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "csv=p=0:nk=0",
         "-show_entries", "stream=codec_type,profile,has_b_frames", str(out.path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert "audio" not in probe and "Main" in probe


def test_the_module_never_imports_a_network_client_at_import_time() -> None:
    assert "httpx" not in ai_mod.__dict__


# --- review of c2439c3c ---------------------------------------------------------------


def test_a_crash_after_booking_never_books_the_task_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_clip: None
) -> None:
    w = World(tmp_path)
    real = w.service.mark_ready
    calls = {"n": 0}

    def crash_once(**kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("process died before mark_ready")
        return real(**kw)

    monkeypatch.setattr(w.service, "mark_ready", crash_once)
    with pytest.raises(RuntimeError):
        w.executor.finish(_ctx(w.row.id), "task-1", "succeeded")
    w.executor.finish(_ctx(w.row.id), "task-1", "succeeded")  # the runner retries
    assert w.medium().status == "ready" and len(w.ledger.rows) == 1
    assert w.medium().cost_usd == w.ledger.rows[0]["cost_usd"]
    assert w.ledger.rows[0]["vendor_task_id"] == "task-1"


def test_the_usage_row_id_is_the_task() -> None:
    assert sai.usage_event_id("task-1") == sai.usage_event_id("task-1")
    assert sai.usage_event_id("task-1") != sai.usage_event_id("task-2")


def test_no_cap_configured_is_refused(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.reads.remaining = None
    with pytest.raises(PriceGuardRefused):
        w.executor.submit(_ctx(w.row.id))
    assert w.adapter.submitted == [] and w.medium().fail_reason == sai.NO_BUDGET_CAP
    assert REASON_TEXT[sai.NO_BUDGET_CAP] == "Tu negocio no tiene tope de gasto configurado."


class DearerTable:
    """The price table after a vendor price rise: twice the v7 rate."""

    version = "v99"

    def unit_price(self, *, model_id: str, unit: str) -> Decimal:
        return Decimal("2.0")


def test_a_price_rise_after_planning_is_refused(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.executor._pricing = DearerTable()  # noqa: SLF001
    with pytest.raises(PriceGuardRefused):
        w.executor.submit(_ctx(w.row.id))  # accepted: v7's US$0.05; now ≈ US$0.10
    assert w.adapter.submitted == [] and w.medium().fail_reason == sai.PRICE_CHANGED
    (tmp_path / "b").mkdir()
    w2 = World(tmp_path / "b")
    with pytest.raises(PriceGuardRefused):
        w2.executor.submit(_ctx(w2.row.id, pricing_version=None))  # no accepted price
    assert w2.adapter.submitted == []


def test_the_accepted_price_is_the_planned_tables_quote() -> None:
    assert sai.accepted_per_video_usd(_ctx(uuid4())) == Decimal("0.05")
    assert sai.accepted_per_video_usd(_ctx(uuid4(), pricing_version=None)) is None


def test_a_task_running_past_the_deadline_lets_the_slot_go(tmp_path: Path) -> None:
    w = World(tmp_path, FakeSeedance(status="running"))
    now = w.executor._clock().timestamp()  # noqa: SLF001
    w.adapter.data = {"created_at": now - sai.TASK_DEADLINE_SECONDS - 5}
    poll = w.executor.poll(_ctx(w.row.id), "task-1")
    assert poll.terminal and poll.status == "expired"
    w.adapter.data = {"created_at": now - 60}
    assert not w.executor.poll(_ctx(w.row.id), "task-1").terminal
    w.executor.finish(_ctx(w.row.id), "task-1", "expired")
    assert w.medium().fail_reason == sai.TIMED_OUT
    # the task may still be billed: the quoted price is booked now, under its own id …
    (booked,) = w.ledger.rows
    assert booked["cost_usd"] == Decimal("0.05") and booked["vendor_task_id"] == "task-1"
    # … so a late success books nothing more (the row is settled, the id is taken)
    w.executor.finish(_ctx(w.row.id), "task-1", "succeeded")
    assert len(w.ledger.rows) == 1 and w.seasonal_keys() == []


def test_the_deadline_counts_from_the_jobs_submitted_at(tmp_path: Path) -> None:
    """A worker restart never extends it: the clock is the job row's `submitted_at`."""
    from dataclasses import replace
    from datetime import timedelta

    w = World(tmp_path, FakeSeedance(status="running"))
    now = w.executor._clock()  # noqa: SLF001
    w.adapter.data = {"created_at": now.timestamp()}  # the vendor's own clock says «new»
    old = replace(
        _ctx(w.row.id), submitted_at=now - timedelta(seconds=sai.TASK_DEADLINE_SECONDS + 5)
    )
    assert w.executor.poll(old, "task-1").terminal
    fresh = replace(_ctx(w.row.id), submitted_at=now - timedelta(minutes=1))
    w.adapter.data = {"created_at": 0}  # an absurd vendor clock does not override the job
    assert not w.executor.poll(fresh, "task-1").terminal


def test_a_task_without_created_at_times_out_from_first_sight(tmp_path: Path) -> None:
    w = World(tmp_path, FakeSeedance(status="running"))
    clock = {"t": 1_000_000.0}
    from datetime import UTC, datetime

    w.executor._clock = lambda: datetime.fromtimestamp(clock["t"], UTC)  # noqa: SLF001
    assert not w.executor.poll(_ctx(w.row.id), "task-9").terminal
    clock["t"] += sai.TASK_DEADLINE_SECONDS + 1
    assert w.executor.poll(_ctx(w.row.id), "task-9").terminal


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://ark-content-ap-southeast-1.tos-ap-southeast-1.bytepluses.com/v", True),
        ("https://bytepluses.com/v.mp4", True),
        ("http://x.bytepluses.com/v.mp4", False),
        ("https://evilbytepluses.com/v.mp4", False),
        ("https://bytepluses.com.evil.io/v.mp4", False),
        ("https://user:pw@x.bytepluses.com/v.mp4", False),
        ("https://169.254.169.254/latest/meta-data", False),
        ("file:///etc/passwd", False),
    ],
)  # fmt: skip
def test_the_clip_comes_only_from_byteplus(url: str, ok: bool) -> None:
    assert sai.allowed_video_url(url) is ok


def test_a_foreign_video_url_is_never_downloaded(
    tmp_path: Path, fake_clip: None, caplog: pytest.LogCaptureFixture
) -> None:
    adapter = FakeSeedance()
    adapter.result = lambda request, state: GenerationResult(  # type: ignore[method-assign]
        payload={"video_url": "https://internal.example/v.mp4", "tokens": 1},
        model_id=DEFAULT_AI_VIDEO_MODEL,
        provider="byteplus",
        usage=Usage(output_tokens=1),
    )
    w = World(tmp_path, adapter)
    with caplog.at_level("ERROR", logger="qualify_api.creative.seasonal_ai"):
        w.executor.finish(_ctx(w.row.id), "task-1", "succeeded")
    assert w.medium().fail_reason == sai.VENDOR_URL_REFUSED and w.seasonal_keys() == []
    (booked,) = w.ledger.rows  # the vendor billed the task: it is booked all the same
    assert booked["vendor_task_id"] == "task-1" and booked["tokens"] == 1
    (record,) = [r for r in caplog.records if "vendor_url_refused" in r.getMessage()]
    assert record.levelname == "ERROR" and "host=internal.example" in record.getMessage()
    assert "/v.mp4" not in record.getMessage()  # the host, never the signed URL


# --- the quote names the photos; the month is the business's -------------------------


def test_the_quote_lists_the_photos_the_plan_animates() -> None:
    service, repo = _service(pieces=3)
    q = service.quote_batch(TENANT, BRAND, "ai")
    assert [p.name for p in q.photos] == ["Pieza 1", "Pieza 2", "Pieza 3"]
    rows = service.plan_batch(
        TENANT, BRAND, SEASON, "Navidad", "ai", None,
        accepted_total_usd=q.total_usd, accepted_draft_ids=[p.draft_id for p in q.photos],
    )  # fmt: skip
    assert [UUID(r.source_ref) for r in rows] == [p.draft_id for p in q.photos]


def test_a_new_photo_between_quote_and_plan_is_refused() -> None:
    from qualify_api.whatsapp.seasonal import SelectionChanged

    service, repo = _service(pieces=2)
    q = service.quote_batch(TENANT, BRAND, "ai")
    # a piece is approved meanwhile: it comes first (newest) and changes the selection
    service._sources.pieces[(TENANT, BRAND)].insert(0, uuid4())  # noqa: SLF001
    with pytest.raises(SelectionChanged):
        service.plan_batch(
            TENANT, BRAND, SEASON, "Navidad", "ai", None,
            accepted_total_usd=Decimal("1"), accepted_draft_ids=[p.draft_id for p in q.photos],
        )  # fmt: skip
    with pytest.raises(CostNotConfirmed):  # SelectionChanged is a CostNotConfirmed
        service.plan_batch(
            TENANT, BRAND, SEASON, "Navidad", "ai", None, accepted_total_usd=Decimal("1")
        )
    assert repo.rows == {} and repo.jobs == []


def test_the_month_starts_in_the_business_zone() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 12, 1, 3, 0, tzinfo=UTC)  # still 30 Nov 22:00 in Bogotá
    assert sai.month_start_in_zone(now, "America/Bogota") == datetime(2026, 11, 1, 5, 0, tzinfo=UTC)
    assert sai.month_start_in_zone(now, "UTC") == datetime(2026, 12, 1, tzinfo=UTC)


def test_the_service_gives_the_reason_text() -> None:
    from qualify_api.whatsapp import seasonal as lib

    assert lib.REASON_TEXT is sai.REASON_TEXT
    assert SeasonalMediaService.reason_text("budget_cap") == (
        "Esta pieza superaría tu tope de gasto."
    )
    assert SeasonalMediaService.reason_text("unexpected").startswith("No pudimos")
