"""VE-09 (m-24921066): a part of a video by parts made by the clip route — «Nueva,
inspirada en el original» (product photos + the shot's sheet, no video of the original)
and «Igual al original» (the reel's window the creative worker cuts, edited in place):
no logo, never remade without its references, `refused_face` for a real person, a
refused window failing the part with its typed reason, provenance in the params, and
the part's keys under the business check. Offline: the clip tests' fakes."""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind, FailureReason
from qualify_creative.providers import GenerationResult, Usage
from qualify_creative.schemas import PartRef, VideoPartPlan

from qualify_api.creative.media import (
    PART_FAILED_TEXT,
    PART_PROMPT_VERSION,
    PART_WINDOW_TEXTS,
    REAL_PERSON_TEXT,
    REFUSED_ORIGINAL_TEXT,
    REFUSED_PHOTO_PART_TEXT,
    PartWindow,
    PartWindowRefused,
)
from qualify_api.creative.part_windows import SourcePartWindows
from qualify_api.creative.parts import part_window
from qualify_api.creative.pipeline import decode_result
from qualify_api.referentes.reel_analysis_types import NOT_OBSERVED, OBSERVED, ShotAnalysis
from qualify_api.referentes.reel_analysis_window import ForeignDraft, SourceWindowRefused

from .test_creative_clip import RecordingLinks
from .test_creative_media_byteplus import (
    TENANT_ID,
    FakeSeedance,
    MemoryStore,
    _brief,
    _produce,
    _producer,
)

V25 = "dreamina-seedance-2-5-260628"
ANALYSIS_ID = UUID("5e1f0000-0000-4000-8000-0000000000b9")
OTHER_TENANT = "00000000-0000-4000-8000-000000000099"
PHOTO = f"uploads/{TENANT_ID}/burger.jpg"


def _jpeg() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (400, 500), (200, 40, 40)).save(out, format="JPEG")
    return out.getvalue()


def _mp4(seconds: int) -> bytes:
    """A real MP4 of `seconds` (2 fps): what the edit's ±0.5 s check measures."""
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=2)
        stream.width, stream.height, stream.pix_fmt = 64, 112, "yuv420p"
        for i in range(seconds * 2):
            pixels = np.full((112, 64, 3), 10 * i, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return out.getvalue()


class ReadLog(MemoryStore):
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        super().__init__(files)
        self.reads: list[str] = []

    def read(self, key: str) -> bytes:
        self.reads.append(key)
        return super().read(key)


@dataclass
class FakeWindows:
    """`PartWindows`: cuts (once) a 4 s window into the part's folder, or refuses."""

    store: MemoryStore
    refuse: str | None = None
    key_for: Any = None
    calls: list[tuple[UUID, UUID, PartRef]] = field(default_factory=list)

    def __call__(self, *, tenant_id: UUID, draft_id: UUID, part: PartRef) -> PartWindow:
        self.calls.append((tenant_id, draft_id, part))
        if self.refuse:
            raise PartWindowRefused(self.refuse)
        key = (
            self.key_for(draft_id)
            if self.key_for
            else f"reel-windows/{tenant_id}/{draft_id}/source-window-{part.analysis_id}-3-7.mp4"
        )
        self.store.files.setdefault(key, _mp4(part.generation_seconds))
        return PartWindow(key=key, start_s=3, end_s=7, offset_s=0.4)


class DraftSeedance(FakeSeedance):
    """Seedance 2.5 answering a 480p draft, with the worker's raw file noted."""

    def __init__(self, *, refuse: str | None = None) -> None:
        super().__init__()
        self.refuse = refuse

    def generate(self, request: Any, *, api_key: str) -> GenerationResult:
        self.requests.append(request)
        if self.refuse:
            raise RuntimeError(self.refuse)
        return GenerationResult(
            payload={
                "task_id": "cgt-part",
                "video_url": "https://ark/part.mp4",
                "duration_seconds": "4",
                "resolution": "480p",
                "generate_audio": False,
                "draft": True,
                "checkpoint_media": f"t/{TENANT_ID}/generated/x/r1/queue-job.bin",
            },
            model_id=V25,
            provider="seedance",
            usage=Usage(pieces=1, media_seconds=4, output_tokens=40000),
            model_revision=V25,
            media_url="https://ark/part.mp4",
            media_expires_at_seconds=86400,
        )


def _part_brief(mode: str, *, window: str | None = None, **media: Any) -> Any:
    part = PartRef(
        index=2,
        mode=mode,  # type: ignore[arg-type]
        seconds=4,
        analysis_id=ANALYSIS_ID,
        shot_indexes=(3,),
        description="Un hombre joven sirve la hamburguesa sobre la mesa.",
    )
    fields: dict[str, Any] = {
        "part": part,
        "duration_seconds": part.generation_seconds,
        "clip_reference_mode": "edit" if mode == "edit" else "motion",
        "clip_image_keys": (PHOTO,),
        "clip_image_roles": ("product",),
        "clip_video_keys": (window,) if window else (),
        **media,
    }
    brief = _brief(ContentKind.CLIP, ContentFormat.REELS_9_16, **fields)
    return brief.model_copy(update={"product_ref": "Smash doble"})


def _setup(
    *,
    seedance: FakeSeedance | None = None,
    windows: FakeWindows | None = None,
    store: MemoryStore | None = None,
    wire_windows: bool = True,
) -> tuple[Any, MemoryStore, FakeSeedance, FakeWindows, RecordingLinks]:
    store = store if store is not None else ReadLog({PHOTO: _jpeg()})
    seedance = seedance or DraftSeedance()
    windows = windows or FakeWindows(store)
    links = RecordingLinks()
    producer = _producer(store, seedance=seedance)
    producer._seedance_reference_model = V25
    producer._seedance_model = V25
    producer._reference_links = links
    producer._part_windows = windows if wire_windows else None
    return producer, store, seedance, windows, links


# ---------------------------------------------------------------------------
# Criterion 1: the request of each mode, no logo, no fallback


def test_criterion_1_a_new_part_sends_photos_and_its_sheet_and_no_video() -> None:
    producer, _store, seedance, windows, _links = _setup()
    outcome = _produce(producer, _part_brief("reference"), uuid4())

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    params = request.params
    assert params["model"] == V25
    assert len(params["reference_images"]) == 1  # the product photo, nothing of the brand
    assert "reference_videos" not in params and "reference_audios" not in params
    assert params["omni_reference_task_type"] == "reference"
    assert params["duration_seconds"] == 4 and params["ratio"] == "9:16"
    prompt = str(params["prompt"])
    # the sheet rewritten (no assumed gender or age), one shot, no text, no logo
    assert "una persona sirve la hamburguesa" in prompt.lower()
    assert "hombre" not in prompt.lower()
    assert "one single continuous shot" in prompt
    assert "No logo image is supplied" in prompt
    assert "#C4622D" in prompt  # the palette
    assert "Video 1" not in prompt and "@Video1" not in prompt
    assert windows.calls == []  # nothing of the original is cut for a new part
    (video,) = outcome.media
    assert video.params["logo"] is False and video.params["subtitles"] == []


def test_criterion_1_an_original_part_edits_one_window_of_its_length() -> None:
    producer, store, seedance, windows, links = _setup()
    draft_id = uuid4()
    outcome = _produce(producer, _part_brief("edit"), draft_id)

    assert outcome.failure is None, outcome.detail
    ((tenant, cut_for, part),) = windows.calls
    assert (tenant, cut_for, part.index) == (TENANT_ID, draft_id, 2)  # the PART's folder
    (request,) = seedance.requests
    params = request.params
    assert params["omni_reference_task_type"] == "edit"
    assert params["ratio"] == "adaptive" and params["duration_seconds"] == -1
    assert len(params["reference_videos"]) == 1
    assert params["reference_video_seconds"] >= 4  # the window: at least Seedance's 4 s
    window_key = f"reel-windows/{TENANT_ID}/{draft_id}/source-window-{ANALYSIS_ID}-3-7.mp4"
    assert links.calls == [(window_key, "video/mp4")]
    assert "Edit video @Video1 in place" in str(params["prompt"])
    assert "No logo image is supplied" in str(params["prompt"])
    (video,) = outcome.media
    assert video.params["logo"] is False
    assert video.params["part"]["window"] == {
        "key": window_key,
        "start_s": 3,
        "end_s": 7,
        "offset_s": 0.4,
    }
    assert store.files[window_key]


def test_criterion_1_the_brand_logo_never_reaches_a_part() -> None:
    """The child brief has no logo; even one forced into it is not laid nor sent."""
    producer, _store, seedance, _windows, _links = _setup()
    brief = _part_brief("reference", brand_logo_key=PHOTO, brand_logo_in_scene=False)
    outcome = _produce(producer, brief, uuid4())

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    assert len(request.params["reference_images"]) == 1  # the photo, not a logo
    assert outcome.media[0].params["logo"] is False


@pytest.mark.parametrize(
    "refusal",
    [
        "ArkAPIError: HTTP 404 ModelNotOpen: not activated",
        "ArkAPIError: HTTP 403 AccessDenied: not activated",  # 2.5's answer
    ],
)
@pytest.mark.parametrize("mode", ["reference", "edit"])
def test_criterion_1_a_refused_model_never_remakes_the_part_without_references(
    mode: str, refusal: str
) -> None:
    producer, _store, seedance, _windows, _links = _setup(seedance=DraftSeedance(refuse=refusal))
    outcome = _produce(producer, _part_brief(mode), uuid4())

    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert len(seedance.requests) == 1  # no second call — so no second job either
    assert outcome.media == () and outcome.usage == ()


# ---------------------------------------------------------------------------
# Criterion 2 (media side): a real person refused is `refused_face`


@pytest.mark.parametrize(
    ("mode", "text"), [("edit", REFUSED_ORIGINAL_TEXT), ("reference", REFUSED_PHOTO_PART_TEXT)]
)
def test_criterion_2_privacy_information_is_refused_face(mode: str, text: str) -> None:
    refusal = "failed: InputVideoSensitiveContentDetected.PrivacyInformation"
    producer, _store, seedance, _windows, _links = _setup(seedance=DraftSeedance(refuse=refusal))
    outcome = _produce(producer, _part_brief(mode), uuid4())

    assert outcome.failure == FailureReason.REFUSED_FACE.value
    assert outcome.detail == text
    assert len(seedance.requests) == 1


def test_a_privacy_refusal_of_an_ordinary_clip_is_unchanged() -> None:
    producer, _store, _seedance, _windows, _links = _setup(
        seedance=DraftSeedance(
            refuse="HTTP 400 InputImageSensitiveContentDetected.PrivacyInformation"
        )
    )
    brief = _brief(ContentKind.CLIP, clip_image_keys=(PHOTO,), clip_image_roles=("product",))
    outcome = _produce(producer, brief, uuid4())
    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert outcome.detail == REAL_PERSON_TEXT


# ---------------------------------------------------------------------------
# Signed decision: a refused window fails the part, typed; never made new by itself


@pytest.mark.parametrize("code", sorted(PART_WINDOW_TEXTS))
def test_a_refused_window_fails_the_part_with_its_reason(code: str) -> None:
    store = ReadLog({PHOTO: _jpeg()})
    producer, _, seedance, _windows, _links = _setup(
        store=store, windows=FakeWindows(store, refuse=code)
    )
    outcome = _produce(producer, _part_brief("edit"), uuid4())

    assert outcome.failure == code == FailureReason(code).value
    assert FailureReason(code).can_make_part_new
    assert outcome.detail == PART_WINDOW_TEXTS[code]
    assert outcome.detail.endswith("Te devolvimos la vista previa.")
    assert seedance.requests == []  # not made «Nueva» silently, nothing paid


@pytest.mark.parametrize("code", ["bad_window", "wrong_process", "foreign_draft"])
def test_a_window_bug_fails_the_part_with_the_generic_words(code: str) -> None:
    store = ReadLog({PHOTO: _jpeg()})
    producer, _, seedance, _windows, _links = _setup(
        store=store, windows=FakeWindows(store, refuse=code)
    )
    outcome = _produce(producer, _part_brief("edit"), uuid4())

    assert outcome.failure == FailureReason.PART_FAILED.value
    assert outcome.detail == PART_FAILED_TEXT
    # our bug: the part keeps its form — not offered as «make it new»
    assert not FailureReason.PART_FAILED.can_make_part_new
    assert FailureReason.PART_FAILED.is_part_reason
    assert seedance.requests == []


def test_without_a_window_cutter_an_original_part_fails_before_any_spend() -> None:
    producer, _store, seedance, _windows, _links = _setup(wire_windows=False)
    outcome = _produce(producer, _part_brief("edit"), uuid4())
    assert outcome.failure == FailureReason.PART_FAILED.value
    assert outcome.detail == PART_FAILED_TEXT
    assert seedance.requests == []


def test_without_an_edit_model_an_original_part_fails_before_its_cut() -> None:
    producer, _store, seedance, windows, _links = _setup()
    producer._seedance_reference_model = "dreamina-seedance-2-0-mini-260615"  # no `edit`
    outcome = _produce(producer, _part_brief("edit"), uuid4())
    assert outcome.failure == FailureReason.PART_FAILED.value
    assert outcome.detail == PART_FAILED_TEXT and "Seedance" not in outcome.detail
    assert windows.calls == [] and seedance.requests == []


def test_a_rerun_of_the_part_reuses_its_window() -> None:
    """The queue runs the preparation more than once: the window is the same key."""
    producer, store, _seedance, windows, _links = _setup()
    draft_id = uuid4()
    first = _produce(producer, _part_brief("edit"), draft_id)
    again = _produce(producer, _part_brief("edit"), draft_id)
    assert first.failure is None and again.failure is None
    keys = {c for c in store.files if "source-window" in c}
    assert len(keys) == 1 and len(windows.calls) == 2


# ---------------------------------------------------------------------------
# Criterion 3 (media side): provenance and the draft block


def test_criterion_3_the_part_records_what_it_was_made_from() -> None:
    producer, _store, _seedance, _windows, _links = _setup()
    outcome = _produce(producer, _part_brief("edit"), uuid4())

    (video,) = outcome.media
    params = video.params
    assert params["part"]["analysis_id"] == str(ANALYSIS_ID)
    assert params["part"]["shot_indexes"] == [3]
    assert params["part"]["mode"] == "edit" and params["part"]["index"] == 2
    assert params["part"]["prompt_version"] == params["part_prompt_version"] == PART_PROMPT_VERSION
    assert video.model_id == V25 and video.provider == "seedance"
    (usage,) = outcome.usage  # what becomes the `creative_usage_events` row
    assert usage.model_id == V25 and usage.cost_usd > 0
    block = params["draft"]
    assert block["reference_mode"] == "edit"  # §1 #12: the final reads the mode here
    assert block["raw_key"] == f"t/{TENANT_ID}/generated/x/r1/queue-job.bin"  # risk 7
    assert block["model"] == V25 and block["cost_usd"] == str(usage.cost_usd)


def test_the_raw_file_the_worker_kept_reaches_the_result() -> None:
    data = {
        "payload": {"task_id": "cgt-1"},
        "media_url": "https://ark/v.mp4",
        "model_id": V25,
        "provider": "seedance",
        "usage": {"pieces": 1, "media_seconds": "4"},
        "model_revision": None,
        "media_expires_at_seconds": None,
        "checkpoint_media": "t/x/generated/y/r1/queue-j.bin",
    }
    result = decode_result(data, MemoryStore(), keep_checkpoint=True)  # a part
    assert result.payload["checkpoint_media"] == "t/x/generated/y/r1/queue-j.bin"
    # decision B: any other piece's payload is exactly as before
    assert "checkpoint_media" not in decode_result(data, MemoryStore()).payload


# ---------------------------------------------------------------------------
# Criterion 4: the part's keys are this business's before anything is read


def test_criterion_4_a_foreign_window_in_the_part_is_refused_before_any_read() -> None:
    store = ReadLog({PHOTO: _jpeg()})
    producer, _, seedance, windows, _links = _setup(store=store)
    foreign = f"reel-windows/{OTHER_TENANT}/{uuid4()}/source-window-x-0-4.mp4"
    outcome = _produce(producer, _part_brief("edit", window=foreign), uuid4())

    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert store.reads == [] and seedance.requests == [] and windows.calls == []


def test_a_window_cut_outside_the_parts_folder_is_never_read() -> None:
    store = ReadLog({PHOTO: _jpeg()})
    elsewhere = FakeWindows(store, key_for=lambda _d: f"t/{TENANT_ID}/generated/{uuid4()}/w.mp4")
    producer, _, seedance, _windows, _links = _setup(store=store, windows=elsewhere)
    outcome = _produce(producer, _part_brief("edit"), uuid4())

    assert outcome.failure == FailureReason.PART_FAILED.value
    assert outcome.detail == PART_FAILED_TEXT
    assert not [k for k in store.reads if "/w.mp4" in k] and seedance.requests == []


def test_a_window_cut_beforehand_is_used_as_it_is() -> None:
    store = ReadLog({PHOTO: _jpeg()})
    draft_id = uuid4()
    precut = f"reel-windows/{TENANT_ID}/{draft_id}/source-window-{ANALYSIS_ID}-0-4.mp4"
    store.files[precut] = _mp4(4)
    producer, _, seedance, windows, _links = _setup(store=store)
    outcome = _produce(producer, _part_brief("edit", window=precut), draft_id)

    assert outcome.failure is None, outcome.detail
    assert windows.calls == [] and len(seedance.requests) == 1
    assert outcome.media[0].params["part"]["window"] == {"key": precut}


def test_a_saved_cut_purged_after_30_days_is_source_purged_not_a_failed_read() -> None:
    """VE-12 (m-24921060): a cut saved in the brief is deleted 30 days after it was
    written; a part re-made later gets `source_purged` (it falls back to `reference`)."""
    from qualify_shared.objects.gate import ObjectNotFound

    class _R2Like(ReadLog):
        def read(self, key: str) -> bytes:
            if key.startswith("reel-windows/") and key not in self.files:
                self.reads.append(key)
                raise ObjectNotFound(key)
            return super().read(key)

    store = _R2Like({PHOTO: _jpeg()})
    draft_id = uuid4()
    purged = f"reel-windows/{TENANT_ID}/{draft_id}/source-window-{ANALYSIS_ID}-0-4.mp4"
    producer, _, seedance, windows, _links = _setup(store=store)
    outcome = _produce(producer, _part_brief("edit", window=purged), draft_id)

    assert outcome.failure == "source_purged"
    assert outcome.detail == PART_WINDOW_TEXTS["source_purged"]
    assert seedance.requests == [] and windows.calls == []


# ---------------------------------------------------------------------------
# The window: pure choice of seconds, and the adapter over VE-04d


def _shot(index: int, start: float, end: float, *, person: bool = False) -> ShotAnalysis:
    seen = OBSERVED if person else NOT_OBSERVED
    return ShotAnalysis(
        shot_index=index, start_s=start, end_s=end, people_presence=seen, visible_faces=seen
    )


def _plan(seconds: int, shots: Sequence[int]) -> VideoPartPlan:
    return VideoPartPlan(
        mode="edit", seconds=seconds, analysis_id=ANALYSIS_ID, shot_indexes=tuple(shots)
    )


def test_the_window_starts_on_the_parts_cut_and_lasts_its_generation_seconds() -> None:
    shots = [_shot(0, 0, 3.3), _shot(1, 3.3, 9.0), _shot(2, 9.0, 15.0)]
    # the window opens on the whole second before the cut: its 0.3 s lead is recorded
    assert part_window(_plan(6, [1]), shots, source_seconds=15.0) == (3, 9, 0.3)
    # a 2 s part is generated at 4 s: the window takes 2 s of the next (clean) cut
    short = [_shot(0, 0, 2.0), _shot(1, 2.0, 4.0), _shot(2, 4.0, 12.0)]
    assert part_window(_plan(2, [1]), short, source_seconds=12.0) == (2, 6, 0.0)


def test_a_fractional_first_cut_keeps_its_lead_as_a_signed_offset() -> None:
    """Review of VE-09: a cut at 3.2 s gives a window from 3 s (never 4 s, which would
    lose 0.8 s of the part), and the 0.2 s before the cut is the offset VE-10a trims."""
    shots = [_shot(0, 0, 3.2), _shot(1, 3.2, 8.0), _shot(2, 8.0, 12.0)]
    assert part_window(_plan(5, [1]), shots, source_seconds=12.0) == (3, 8, 0.2)


def test_a_window_opening_after_the_part_records_a_negative_offset() -> None:
    """The cut before shows someone and the part is longer than its window: the window
    ends with the part and opens 0.4 s into it — a negative offset, never hidden."""
    shots = [_shot(0, 0, 0.6, person=True), _shot(1, 0.6, 11.0)]
    start, end, offset = part_window(_plan(10, [1]), shots, source_seconds=11.0)
    assert (start, end) == (1, 11) and offset == -0.4


def test_the_window_leans_back_when_the_next_cut_shows_someone() -> None:
    shots = [_shot(0, 0, 3.0), _shot(1, 3.0, 5.0), _shot(2, 5.0, 9.0, person=True)]
    start, end, offset = part_window(_plan(2, [1]), shots, source_seconds=9.0)
    assert (start, end) == (1, 5) and offset == 2.0


def test_the_window_is_refused_when_both_neighbours_show_someone() -> None:
    shots = [_shot(0, 0, 3.0, person=True), _shot(1, 3.0, 5.0), _shot(2, 5.0, 9.0, person=True)]
    with pytest.raises(PartWindowRefused) as refused:
        part_window(_plan(2, [1]), shots, source_seconds=9.0)
    assert refused.value.code == "not_edit_eligible"


def test_the_window_stays_inside_the_source() -> None:
    shots = [_shot(0, 0, 6.0), _shot(1, 6.0, 8.4)]
    assert part_window(_plan(2, [1]), shots, source_seconds=8.4) == (4, 8, 2.0)
    with pytest.raises(PartWindowRefused) as refused:
        part_window(_plan(2, [5]), shots, source_seconds=8.4)
    assert refused.value.code == "window_unavailable"


@dataclass
class _Record:
    status: str = "ok"
    source_seconds: float | None = 9.0


class _Requests:
    def __init__(self, record: _Record | None, shots: list[ShotAnalysis]) -> None:
        self.record, self._shots = record, shots

    def get(self, tenant_id: UUID, analysis_id: UUID) -> _Record | None:
        return self.record

    def shots(self, tenant_id: UUID, analysis_id: UUID) -> list[ShotAnalysis]:
        return self._shots


class _Windows:
    """The duck of VE-04d's `SourceWindows`: its `requests` and `source_window`."""

    def __init__(self, *, refuse: Exception | None = None, record: _Record | None = None) -> None:
        shots = [_shot(0, 0, 4.0), _shot(1, 4.0, 9.0)]
        self.requests = _Requests(record if record is not None else _Record(), shots)
        self.refuse = refuse
        self.calls: list[tuple[Any, ...]] = []

    def source_window(self, tenant_id: UUID, analysis_id: UUID, **kw: Any) -> str:
        self.calls.append((tenant_id, analysis_id, kw))
        if self.refuse is not None:
            raise self.refuse
        return f"reel-windows/{tenant_id}/{kw['draft_id']}/source-window-x.mp4"


def _ref(shots: tuple[int, ...] = (1,)) -> PartRef:
    return PartRef(index=1, mode="edit", seconds=5, analysis_id=ANALYSIS_ID, shot_indexes=shots)


def test_the_adapter_asks_source_window_for_the_parts_seconds() -> None:
    windows = _Windows()
    draft_id = uuid4()
    cut = SourcePartWindows(windows)(tenant_id=TENANT_ID, draft_id=draft_id, part=_ref())  # type: ignore[arg-type]
    ((tenant, analysis, kw),) = windows.calls
    assert (tenant, analysis) == (TENANT_ID, ANALYSIS_ID)
    assert kw == {"draft_id": draft_id, "start_s": 4, "end_s": 9}
    assert (cut.start_s, cut.end_s, cut.offset_s) == (4, 9, 0.0)


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (SourceWindowRefused("source_purged"), "source_purged"),
        (SourceWindowRefused("bad_window"), "bad_window"),
        (SourceWindowRefused("wrong_process"), "wrong_process"),
        (ForeignDraft("not this business"), "foreign_draft"),
        (OSError("r2 down"), "window_unavailable"),
    ],
)
def test_the_adapter_turns_every_refusal_into_a_typed_code(raised: Exception, code: str) -> None:
    adapter = SourcePartWindows(_Windows(refuse=raised))  # type: ignore[arg-type]
    with pytest.raises(PartWindowRefused) as refused:
        adapter(tenant_id=TENANT_ID, draft_id=uuid4(), part=_ref())
    assert refused.value.code == code


def test_the_adapter_waits_for_an_analysis_that_is_not_ready() -> None:
    windows = _Windows(record=_Record(status="running"))
    with pytest.raises(PartWindowRefused) as refused:
        SourcePartWindows(windows)(tenant_id=TENANT_ID, draft_id=uuid4(), part=_ref())  # type: ignore[arg-type]
    assert refused.value.code == "analysis_not_ready" and windows.calls == []


def test_the_adapter_builds_the_real_windows_only_when_first_used() -> None:
    built: list[int] = []

    def factory() -> Any:
        built.append(1)
        return _Windows()

    adapter = SourcePartWindows(factory=factory)
    assert built == []
    adapter(tenant_id=TENANT_ID, draft_id=uuid4(), part=_ref())
    adapter(tenant_id=TENANT_ID, draft_id=uuid4(), part=_ref())
    assert built == [1]


# ---------------------------------------------------------------------------
# Criterion 2 (service side): the part fails, its vista previa comes back, no retry


def _parts_world(
    seedance: FakeSeedance, plan: VideoPartPlan | None = None
) -> tuple[Any, Any, Any, Any, Any, UUID]:
    """A parent of one part (`plan`, else an «Igual al original» one), with its text,
    over the REAL media producer (the clip tests' fakes behind it) and the in-memory
    ledger."""
    from qualify_creative.enums import ContentFormat as Fmt
    from qualify_creative.schemas import MediaInputs

    from qualify_api.creative.creations import InMemoryCreationsLedger
    from qualify_api.creative.parts import PartsService
    from qualify_api.creative.service import ContentService

    from .test_content_service import (
        BRAND_ID as CS_BRAND,
    )
    from .test_content_service import (
        TENANT_ID as CS_TENANT,
    )
    from .test_content_service import (
        USER_ID,
        FakeBrand,
        FakePricing,
        FakeRouter,
        FakeVoice,
        RecordingDispatcher,
        StaticKeyResolver,
        copy_dict,
        make_brief,
        make_kit,
        make_voice,
        ok_outcome,
    )
    from .test_creative_parts import PartsRepository

    photo = f"uploads/{CS_TENANT}/burger.jpg"
    store = ReadLog({photo: _jpeg()})
    producer, _, _, _, _ = _setup(seedance=seedance, store=store)
    producer._reference_links = lambda **_: "https://qualify.example/public/media/tok"
    repo = PartsRepository()
    ledger = InMemoryCreationsLedger()
    dispatcher = RecordingDispatcher()
    content = ContentService(
        router=FakeRouter([ok_outcome(copy_dict())]),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
        dispatcher=dispatcher,
        media=producer,
        creations=ledger,
    )
    plan = plan or VideoPartPlan(
        mode="edit",
        seconds=4,
        analysis_id=ANALYSIS_ID,
        shot_indexes=(0,),
        description="La hamburguesa sobre la mesa.",
    )
    parent = content.create_draft(
        tenant_id=CS_TENANT,
        brand_id=CS_BRAND,
        brief=make_brief(
            variants=1,
            kind=ContentKind.SHOT_VIDEO,
            format=Fmt.REELS_9_16,
            topic="Smash burger doble",
            media=MediaInputs(parts=(plan,), product_keys=(photo,)),
        ),
        user_id=USER_ID,
    )
    content.run_generation(tenant_id=CS_TENANT, draft_id=parent)
    (child,) = PartsService(content, require_queue=lambda: True).create_parts(
        tenant_id=CS_TENANT, parent_id=parent, user_id=USER_ID
    )
    dispatcher.calls.clear()
    return content, repo, ledger, dispatcher, CS_TENANT, child


def test_criterion_2_a_refused_face_fails_the_part_refunds_it_and_never_retries() -> None:
    seedance = DraftSeedance(refuse="failed: InputVideoSensitiveContentDetected.PrivacyInformation")
    content, repo, ledger, dispatcher, tenant, child = _parts_world(seedance)

    content.run_generation(tenant_id=tenant, draft_id=child)

    draft = repo.drafts[child]
    assert draft.status == "failed"
    assert draft.failure_reason == FailureReason.REFUSED_FACE.value
    assert draft.failure_detail == REFUSED_ORIGINAL_TEXT
    row = ledger.rows[(child, 1)]
    assert row.status == "refunded" and row.reason == FailureReason.REFUSED_FACE.value
    assert len(seedance.requests) == 1
    assert dispatcher.calls == []  # nothing put back in the queue by itself
    content.run_generation(tenant_id=tenant, draft_id=child)  # a stray re-run: a no-op
    assert len(seedance.requests) == 1


def test_a_refused_window_fails_the_part_refunded_with_its_code() -> None:
    seedance = DraftSeedance()
    content, repo, ledger, _dispatcher, tenant, child = _parts_world(seedance)
    content._media._part_windows = FakeWindows(MemoryStore(), refuse="source_purged")

    content.run_generation(tenant_id=tenant, draft_id=child)

    draft = repo.drafts[child]
    assert draft.status == "failed" and draft.failure_reason == "source_purged"
    assert draft.failure_detail == PART_WINDOW_TEXTS["source_purged"]
    assert ledger.rows[(child, 1)].status == "refunded"
    assert seedance.requests == []


def test_a_made_part_records_its_cost_as_a_usage_event() -> None:
    seedance = DraftSeedance()
    content, repo, _ledger, _dispatcher, tenant, child = _parts_world(seedance)

    content.run_generation(tenant_id=tenant, draft_id=child)

    assert repo.drafts[child].status == "generated", repo.drafts[child].failure_detail
    (asset,) = repo.media_for(tenant_id=tenant, draft_id=child)
    assert asset.params["part"]["analysis_id"] == str(ANALYSIS_ID)
    assert asset.params["part_prompt_version"] == PART_PROMPT_VERSION
    usage = [u for u in repo.usage if u.provider == "seedance"]
    assert len(usage) == 1 and usage[0].model_id == V25 and usage[0].cost_usd > 0


# ---------------------------------------------------------------------------
# m-24992565: a sentence the part's cuts repeat reaches Seedance's prompt once


@pytest.mark.parametrize(("people", "mode"), [(OBSERVED, "reference"), (NOT_OBSERVED, "edit")])
def test_a_sentence_repeated_by_the_parts_cuts_reaches_the_prompt_once(
    people: str, mode: str
) -> None:
    """End to end, offline: a reel of 4 cuts showing the same thing → `plan_from_analysis`
    → the parent's plan → `create_parts` (the child brief as the app makes it) → the
    part's generation over the real media producer → the prompt Seedance receives."""
    from qualify_api.creative.parts import plan_from_analysis

    from .test_creative_parts import analysis, shot

    subject = "una persona presenta y prueba sliders de pescado"
    reel = analysis(
        *(
            shot(i, float(i), i + 1.0, people=people, faces=people, subject=subject)
            for i in range(4)
        )
    )
    (plan,) = plan_from_analysis(reel)
    assert plan.mode == mode and plan.shot_indexes == (0, 1, 2, 3)
    seedance = DraftSeedance()
    content, repo, _ledger, _dispatcher, tenant, child = _parts_world(seedance, plan)

    content.run_generation(tenant_id=tenant, draft_id=child)

    assert repo.drafts[child].status == "generated", repo.drafts[child].failure_detail
    prompt = str(seedance.requests[-1].params["prompt"])
    assert ("Edit video @Video1 in place" in prompt) == (mode == "edit")
    assert prompt.count("Una persona presenta y prueba sliders de pescado.") == 1
    assert prompt.lower().count("presenta y prueba sliders de pescado") == 1


# ---------------------------------------------------------------------------
# m-24992913: the reel's product never reaches the prompt next to the owner's photo


@pytest.mark.parametrize(("people", "mode"), [(OBSERVED, "reference"), (NOT_OBSERVED, "edit")])
def test_the_reels_product_reaches_the_prompt_as_the_owners(people: str, mode: str) -> None:
    """End to end, offline: the reel names its product («sliders de pescado», its
    `product` family) → `plan_from_analysis` with the owner's product → the parent's plan
    → `create_parts` → the part's generation → the prompt Seedance receives."""
    from qualify_api.creative.parts import plan_from_analysis

    from .test_creative_parts import analysis, shot

    reel = analysis(
        shot(
            0,
            0.0,
            2.0,
            people=people,
            faces=people,
            subject="Hombre presenta y prueba sliders de pescado",
            product="Sliders de pescado rebozado con salsa",
        ),
        shot(
            1,
            2.0,
            4.0,
            people=people,
            faces=people,
            subject="Manos cierran el slider y pincelan",
            product="Slider terminado con hierbas",
        ),
    )
    (plan,) = plan_from_analysis(reel, products=("super smash",))
    assert plan.mode == mode and plan.shot_indexes == (0, 1)
    seedance = DraftSeedance()
    content, repo, _ledger, _dispatcher, tenant, child = _parts_world(seedance, plan)

    content.run_generation(tenant_id=tenant, draft_id=child)

    assert repo.drafts[child].status == "generated", repo.drafts[child].failure_detail
    prompt = str(seedance.requests[-1].params["prompt"])
    assert "slider" not in prompt.lower()
    assert "presenta y prueba super smash. Manos cierran super smash y pincelan." in prompt
