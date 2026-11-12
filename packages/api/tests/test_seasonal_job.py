"""The `seasonal_media` job handler (m-24976892), offline: the real library service on its
memory repository, the real `ObjectGate` on a memory store (never R2), placeholder images
drawn in the test — and the renderer faked except where the Pillow-only path is enough."""

from __future__ import annotations

import io
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image, ImageDraw
from qualify_creative.seasonal import (
    RecipeError,
    RecipeOutput,
    RemotionStickerRenderer,
    RemotionVideoRenderer,
    run_recipe,
)
from qualify_creative.seasonal.errors import FFMPEG_FAILED, TOO_LARGE
from qualify_creative.seasonal.sticker import _encode_pillow
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore

from qualify_api.creative.seasonal_job import (
    MediaRow,
    SeasonalJob,
    SeasonalMediaJobHandler,
    sticker_renderer_from_env,
    video_renderer_from_env,
)
from qualify_api.whatsapp.seasonal import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_REJECTED,
    MemorySeasonalRepository,
    MemorySourceReads,
    SeasonalMediaService,
)

TENANT = UUID("a0000000-0000-4000-8000-0000000005e1")
OTHER = UUID("a0000000-0000-4000-8000-0000000005e2")
BRAND = UUID("b0000000-0000-4000-8000-0000000005e1")
LOGO_KEY = f"t/{TENANT}/brand/{BRAND}/logo.png"
SEASON = "navidad-2026"


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _logo() -> bytes:
    logo = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rounded_rectangle((8, 8, 392, 192), 30, fill=(200, 30, 30, 255))
    return _png(logo)


def _photo(color: tuple[int, int, int]) -> bytes:
    return _png(Image.new("RGB", (800, 1000), color))


def _row(media: Any) -> MediaRow:
    return MediaRow(
        media.brand_id,
        media.status,
        media.attempt,
        media.object_key,
        media.season_key,
        media.kind,
        media.recipe,
        media.source_kind,
        media.source_ref,
    )


class Sources:
    def __init__(self, repo: MemorySeasonalRepository) -> None:
        self.repo = repo
        self.pieces: dict[UUID, str] = {}
        self.kit_logo: str | None = LOGO_KEY

    def media_row(self, tenant_id: UUID, media_id: UUID) -> MediaRow | None:
        media = self.repo.get(tenant_id=tenant_id, media_id=media_id)
        if media is None:
            return None
        return _row(media)

    def piece_image_keys(self, tenant_id: UUID, brand_id: UUID, draft_ids: Any) -> list[str]:
        return [self.pieces[d] for d in draft_ids if d in self.pieces]

    def logo_key(self, tenant_id: UUID, brand_id: UUID) -> str | None:
        return self.kit_logo

    def palette(self, tenant_id: UUID, brand_id: UUID) -> list[str]:
        return ["#C81E1E", "#14785A"]

    def heading_font(self, tenant_id: UUID, brand_id: UUID) -> tuple[str | None, str | None]:
        return None, None


class World:
    def __init__(self, tmp_path: Path, render: Any = None) -> None:
        self.repo = MemorySeasonalRepository()
        reads = MemorySourceReads()
        self.piece_ids = [uuid4(), uuid4()]
        reads.pieces[(TENANT, BRAND)] = list(self.piece_ids)
        reads.logos[(TENANT, BRAND)] = LOGO_KEY
        self.service = SeasonalMediaService(self.repo, reads)
        self.store = MemoryObjectStore()
        self.store.objects[LOGO_KEY] = _logo()
        self.sources = Sources(self.repo)
        for i, piece in enumerate(self.piece_ids):
            key = f"t/{TENANT}/media/{piece}/0.png"
            self.store.objects[key] = _photo((40 * i + 30, 90, 160))
            self.sources.pieces[piece] = key
        self.tmp = tmp_path / "work"
        self.tmp.mkdir()
        self.sleeps: list[float] = []
        self.handler = SeasonalMediaJobHandler(
            objects=ObjectGate(self.store),
            marks=self.service,
            sources=self.sources,
            render=render or _fake_render,
            tmp_root=self.tmp,
            sleep=self.sleeps.append,
        )
        self.planned = self.service.plan_batch(TENANT, BRAND, SEASON, "Navidad 2026", "free", None)

    def job_for(self, media: Any) -> SeasonalJob:
        return SeasonalJob.from_payload(
            _payload(self.repo, media.id), tenant_id=TENANT, brand_id=BRAND
        )

    def job(self, recipe: str) -> SeasonalJob:
        return self.job_for(next(m for m in self.planned if m.recipe == recipe))

    def row(self, job: SeasonalJob):  # noqa: ANN201
        return self.repo.get(tenant_id=TENANT, media_id=job.media_id)

    def seasonal_keys(self) -> list[str]:
        return [k for k in self.store.objects if k.startswith("seasonal/")]


def _payload(repo: MemorySeasonalRepository, media_id: UUID) -> dict[str, Any]:
    """The LATEST job of the medium (one per attempt)."""
    return [j["payload"] for j in repo.jobs if j["payload"]["media_id"] == str(media_id)][-1]


def _fake_render(recipe: str, look: Any, work: Path, *, images: Any = (), text: Any = None):  # noqa: ANN202
    (work / "scratch.bin").write_bytes(b"x" * 10)  # the temp dir must be emptied after
    video = recipe.startswith("b-")
    return RecipeOutput(
        data=b"\x00" * 2048,
        kind="video" if video else "sticker",
        recipe=recipe,
        content_type="video/mp4" if video else "image/webp",
        ext="mp4" if video else "webp",
        width=720 if video else 512,
        height=720 if video else 512,
        duration_ms=4000 if video else 2000,
        frames=96 if video else 30,
        bytes=2048,
        pipeline_version="seasonal-b-1" if video else "seasonal-e-1",
        encoding="fake",
    )


def test_ready_stores_at_the_deterministic_key_and_marks_with_provenance(tmp_path: Path) -> None:
    w = World(tmp_path)
    job = w.job("e-latido")
    outcome = w.handler.handle(job)
    assert outcome.status == "done"
    expected = f"seasonal/{TENANT}/{BRAND}/{SEASON}/{job.media_id}-1.webp"
    assert outcome.object_key == expected and w.seasonal_keys() == [expected]
    row = w.row(job)
    assert row.status == STATUS_READY and row.object_key == expected
    assert (row.bytes, row.width, row.height, row.duration_ms) == (2048, 512, 512, 2000)
    assert row.cost_usd == 0
    # provenance on the row (source + recipe + library version) and in the job result
    assert (row.source_kind, row.recipe, row.pipeline_version) == (
        "logo",
        "e-latido",
        "seasonal-v1",
    )
    assert outcome.result["recipe_version"] == "seasonal-e-1"
    assert list(w.tmp.iterdir()) == []


def test_rerunning_the_same_job_neither_renders_nor_uploads_again(tmp_path: Path) -> None:
    w = World(tmp_path)
    job = w.job("b-zoom")
    assert w.handler.handle(job).status == "done"
    puts = len(w.store.puts)
    again = w.handler.handle(job)
    assert again.status == "skipped" and len(w.store.puts) == puts
    assert len(w.seasonal_keys()) == 1


def test_an_over_limit_output_is_not_stored_and_the_row_says_why(tmp_path: Path) -> None:
    def too_big(*args: Any, **kwargs: Any) -> RecipeOutput:
        raise RecipeError(TOO_LARGE, "612000 bytes at quality 50")

    w = World(tmp_path, render=too_big)
    job = w.job("e-texto")
    outcome = w.handler.handle(job)
    assert outcome.status == "failed" and outcome.reason == TOO_LARGE
    assert w.row(job).status == STATUS_FAILED and w.row(job).fail_reason == TOO_LARGE
    assert w.seasonal_keys() == [] and list(w.tmp.iterdir()) == []


def test_a_transient_ffmpeg_failure_retries_and_leaves_the_row_pending(tmp_path: Path) -> None:
    def killed(*args: Any, **kwargs: Any) -> RecipeOutput:
        raise RecipeError(FFMPEG_FAILED, "killed by signal 9", transient=True)

    w = World(tmp_path, render=killed)
    job = w.job("b-pan")
    outcome = w.handler.handle(job)
    assert outcome.status == "retry" and w.row(job).status == STATUS_PENDING
    assert w.seasonal_keys() == []


def test_a_failed_row_renders_again_on_retry(tmp_path: Path) -> None:
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> RecipeOutput:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RecipeError(FFMPEG_FAILED, "bad frame")
        return _fake_render(*args, **kwargs)

    w = World(tmp_path, render=flaky)
    job = w.job("e-giro")
    assert w.handler.handle(job).status == "failed"
    assert w.handler.handle(job).status == "done" and w.row(job).status == STATUS_READY


def test_r2_writes_retry_on_the_same_key(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.store.fail_puts = 2
    job = w.job("e-rebote")
    assert w.handler.handle(job).status == "done"
    assert w.sleeps == [2.0, 4.0] and len(w.seasonal_keys()) == 1


def test_r2_down_is_a_retry_without_marking(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.store.fail_puts = 3
    job = w.job("e-brillo")
    outcome = w.handler.handle(job)
    assert outcome.status == "retry" and outcome.reason.startswith("r2_write")
    assert w.row(job).status == STATUS_PENDING


def test_lost_lease_writes_nothing(tmp_path: Path) -> None:
    w = World(tmp_path)
    job = w.job("e-latido")
    assert w.handler.handle(job, still_ours=lambda: False).status == "lost_lease"
    assert w.seasonal_keys() == [] and w.row(job).status == STATUS_PENDING


def test_give_up_fails_the_row_and_removes_the_file(tmp_path: Path) -> None:
    w = World(tmp_path)
    job = w.job("b-xfade")
    key = w.handler.expected_key(job)
    w.store.objects[key] = b"half"  # an upload whose mark_ready never landed
    w.handler.give_up(job, "attempts_exhausted")
    assert w.row(job).status == STATUS_FAILED and key not in w.store.objects


def test_give_up_keeps_a_ready_medium(tmp_path: Path) -> None:
    w = World(tmp_path)
    job = w.job("e-latido")
    w.handler.handle(job)
    w.handler.give_up(job, "attempts_exhausted")
    assert w.row(job).status == STATUS_READY and len(w.seasonal_keys()) == 1


def test_missing_pieces_are_no_source(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.sources.pieces.clear()  # the pieces were purged or unapproved meanwhile
    job = w.job("b-zoom")
    outcome = w.handler.handle(job)
    assert outcome.reason == "no_source" and w.row(job).fail_reason == "no_source"


def test_a_payload_disagreeing_with_its_row_is_refused(tmp_path: Path) -> None:
    """Review of 58855151: season, kind, recipe and source come from the row, not trusted
    from the payload — another brand's logo key in a payload is never read."""
    w = World(tmp_path)
    job = w.job("e-latido")
    w.store.objects[f"t/{OTHER}/brand/x/logo.png"] = _logo()
    for field, value in (
        ("source_ref", f"t/{OTHER}/brand/x/logo.png"),
        ("season_key", "otra-temporada"),
        ("kind", "video"),
        ("recipe", "e-giro"),
    ):
        bad = SeasonalJob(**{**job.__dict__, field: value})
        outcome = w.handler.handle(bad)
        assert (outcome.status, outcome.reason) == ("failed", "payload_mismatch"), field
    assert w.row(job).status == STATUS_PENDING and w.seasonal_keys() == []


def test_the_logo_comes_from_the_brand_kit(tmp_path: Path) -> None:
    """The kit's logo changed after planning: the planned key is no longer the brand's,
    so nothing is read — `no_source` (plan again)."""
    w = World(tmp_path)
    job = w.job("e-latido")
    w.sources.kit_logo = f"t/{TENANT}/brand/{BRAND}/logo-new.png"
    outcome = w.handler.handle(job)
    assert outcome.reason == "no_source" and w.row(job).fail_reason == "no_source"


def test_a_payload_naming_another_tenant_is_refused(tmp_path: Path) -> None:
    w = World(tmp_path)
    payload = _payload(w.repo, w.planned[0].id)
    with pytest.raises(ValueError):
        SeasonalJob.from_payload(payload, tenant_id=OTHER, brand_id=BRAND)


def test_end_to_end_text_sticker_with_the_pillow_writer(tmp_path: Path) -> None:
    """No FFmpeg needed: the real `e-texto` recipe with Pillow's WebP writer."""
    render = partial(run_recipe, sticker_encoder=_encode_pillow, sticker_encoder_name="pillow")
    w = World(tmp_path, render=render)
    job = next(
        w.job_for(m) for m in w.planned if m.recipe == "e-texto" and "Gracias" in m.source_ref
    )
    outcome = w.handler.handle(job)
    assert outcome.status == "done", outcome
    data = w.store.objects[outcome.object_key]
    assert len(data) <= 500 * 1024 and w.store.content_types[outcome.object_key] == "image/webp"
    with Image.open(io.BytesIO(data)) as sticker:
        assert sticker.size == (512, 512) and sticker.n_frames > 1
        assert sticker.convert("RGBA").getpixel((2, 2))[3] == 0
    assert outcome.result["encoding"].startswith("pillow")
    assert list(w.tmp.iterdir()) == []


def test_a_result_of_an_older_attempt_is_dropped(tmp_path: Path) -> None:
    """«Pedir otro» while attempt 1 renders: attempt 1's result is refused (StaleAttempt),
    its file removed, the row stays on attempt 2 — no retry, no error."""
    w = World(tmp_path)
    first = w.job("e-latido")
    w.handler.handle(first)
    w.service.request_another(TENANT, BRAND, first.media_id, None)
    second = w.job("e-latido")
    assert (first.attempt, second.attempt) == (1, 2)

    # attempt 1 runs again (a late retry): skipped up front, nothing written
    puts = len(w.store.puts)
    assert w.handler.handle(first).reason == "stale_attempt" and len(w.store.puts) == puts

    # the owner asks again while attempt 2 is in flight: its mark_ready is stale
    def ask_again_mid_render(*args: Any, **kwargs: Any) -> RecipeOutput:
        w.service.request_another(TENANT, BRAND, second.media_id, None)
        return _fake_render(*args, **kwargs)

    # (attempt 2 must be requestable: make it failed first, as a render error would)
    w.service.mark_failed(
        tenant_id=TENANT, brand_id=BRAND, media_id=second.media_id, attempt=2, reason="x"
    )
    w.handler._render = ask_again_mid_render  # noqa: SLF001
    outcome = w.handler.handle(second)
    assert outcome.status == "skipped" and outcome.reason == "stale_attempt"
    assert w.row(second).attempt == 3 and w.row(second).status == STATUS_PENDING
    # the file attempt 2 wrote before its stale mark_ready is deleted through the gate
    assert w.handler.expected_key(second) in w.store.puts
    assert w.handler.expected_key(second) not in w.store.objects


def test_each_attempt_has_its_own_key(tmp_path: Path) -> None:
    w = World(tmp_path)
    first = w.job("b-zoom")
    w.handler.handle(first)
    w.service.request_another(TENANT, BRAND, first.media_id, None)
    second = w.job("b-zoom")
    assert w.handler.handle(second).status == "done"
    assert w.row(second).object_key.endswith(f"{second.media_id}-2.mp4")


def test_settled_by_another_run_of_the_same_attempt_keeps_its_file(tmp_path: Path) -> None:
    """Two runs of one attempt (a reclaimed lease): the second's mark_ready is WrongState,
    and the row points at the very key it wrote — the file stays."""
    w = World(tmp_path)
    job = w.job("e-latido")
    assert w.handler.handle(job).status == "done"

    # the second run read the row while it was still `pending`, then re-reads it
    def reread(t: UUID, m: UUID) -> MediaRow | None:
        media = w.repo.get(tenant_id=t, media_id=m)
        return _row(media)

    first_read = {"done": False}

    def pending_then_real(t: UUID, m: UUID) -> MediaRow | None:
        if not first_read["done"]:
            first_read["done"] = True
            return MediaRow(BRAND, STATUS_PENDING, 1)
        return reread(t, m)

    w.sources.media_row = pending_then_real  # type: ignore[method-assign]
    outcome = w.handler.handle(job)
    assert (outcome.status, outcome.reason) == ("skipped", "settled")
    assert w.handler.expected_key(job) in w.store.objects
    assert w.row(job).status == STATUS_READY


def test_settled_otherwise_deletes_the_file_it_wrote(tmp_path: Path) -> None:
    """The row was rejected while the job ran: WrongState, and the row does not point at
    the key just written — that file is deleted, no orphan under seasonal/."""
    w = World(tmp_path)
    job = w.job("e-giro")

    def reject_mid_render(*args: Any, **kwargs: Any) -> RecipeOutput:
        media = w.repo.get(tenant_id=TENANT, media_id=job.media_id)
        w.repo.rows[job.media_id] = replace(media, status=STATUS_REJECTED)
        return _fake_render(*args, **kwargs)

    w.handler._render = reject_mid_render  # noqa: SLF001
    outcome = w.handler.handle(job)
    assert (outcome.status, outcome.reason) == ("skipped", "settled")
    assert w.handler.expected_key(job) in w.store.puts
    assert w.seasonal_keys() == []


# --- m-24987158: stickers through the render service (recipe C), recipe E as fallback ------


def test_the_sticker_engine_comes_from_the_environment() -> None:
    url = "http://render:3200"
    assert isinstance(
        sticker_renderer_from_env({"QUALIFY_RENDER_URL": url}), RemotionStickerRenderer
    )
    pillow = {"QUALIFY_RENDER_URL": url, "QUALIFY_SEASONAL_STICKERS": "pillow"}
    assert sticker_renderer_from_env(pillow) is None
    assert sticker_renderer_from_env({}) is None


class _Down:
    """The render profile is off: `render` does not resolve."""

    def health(self) -> Any:
        raise ConnectionError("Name or service not known")


def test_a_sticker_falls_back_to_recipe_e_when_the_render_service_is_off(
    tmp_path: Path,
) -> None:
    renderer = RemotionStickerRenderer(_Down())  # type: ignore[arg-type]
    w = World(tmp_path, render=partial(run_recipe, sticker_renderer=renderer))
    job = next(
        w.job_for(m) for m in w.planned if m.recipe == "e-texto" and "Gracias" in m.source_ref
    )
    outcome = w.handler.handle(job)
    assert outcome.status == "done", outcome
    assert outcome.result["engine"] == "pillow"
    assert outcome.result["fallback"] == "unreachable"
    assert outcome.result["recipe_version"] == "seasonal-e-1"


# --- m-25016848: videos through the render service (recipe D), recipe B as fallback --------


def test_the_video_engine_comes_from_the_environment() -> None:
    url = "http://render:3200"
    assert isinstance(video_renderer_from_env({"QUALIFY_RENDER_URL": url}), RemotionVideoRenderer)
    ffmpeg = {"QUALIFY_RENDER_URL": url, "QUALIFY_SEASONAL_VIDEOS": "ffmpeg"}
    assert video_renderer_from_env(ffmpeg) is None
    assert video_renderer_from_env({}) is None
    # the sticker switch does not touch the videos, and the reverse
    pillow = {"QUALIFY_RENDER_URL": url, "QUALIFY_SEASONAL_STICKERS": "pillow"}
    assert isinstance(video_renderer_from_env(pillow), RemotionVideoRenderer)
    assert isinstance(sticker_renderer_from_env(ffmpeg), RemotionStickerRenderer)


class _Recorder:
    """A renderer double that keeps the look each job handed it."""

    def __init__(self) -> None:
        self.looks: list[Any] = []

    def __call__(self, recipe: str, look: Any, work: Path, **kw: Any) -> RecipeOutput:
        self.looks.append(look)
        return _fake_render(recipe, look, work, **kw)


def test_a_photo_video_carries_the_brand_logo_for_its_sign_off(tmp_path: Path) -> None:
    rec = _Recorder()
    w = World(tmp_path, render=rec)
    assert w.handler.handle(w.job("b-zoom")).status == "done"
    assert rec.looks[-1].logo is not None


def test_a_missing_logo_never_fails_a_photo_video(tmp_path: Path) -> None:
    rec = _Recorder()
    w = World(tmp_path, render=rec)
    del w.store.objects[LOGO_KEY]  # the kit names a logo the bucket no longer has
    assert w.handler.handle(w.job("b-pan")).status == "done"
    assert rec.looks[-1].logo is None
    w.store.objects[LOGO_KEY] = b"not an image"
    assert w.handler.handle(w.job("b-xfade")).status == "done"
    assert rec.looks[-1].logo is None


def test_the_logo_video_still_fails_without_its_logo(tmp_path: Path) -> None:
    w = World(tmp_path, render=_Recorder())
    del w.store.objects[LOGO_KEY]
    job = w.job("b-logo")
    assert w.handler.handle(job).status == "failed"
    assert w.row(job).fail_reason == "no_source"


class _DownVideo:
    def health(self) -> Any:
        raise ConnectionError("Name or service not known")


def test_a_video_falls_back_to_recipe_b_when_the_render_service_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.seasonal import recipes as recipes_mod  # noqa: PLC0415
    from qualify_creative.seasonal.video import VideoResult  # noqa: PLC0415

    def fake_b(recipe: str, images: Any, look: Any, work: Path) -> VideoResult:
        path = work / "b.mp4"
        path.write_bytes(b"\x00" * 4096)
        return VideoResult(path, 720, 720, 4000, 96, 4096, 28, False)

    monkeypatch.setattr(recipes_mod, "make_video", fake_b)
    renderer = RemotionVideoRenderer(_DownVideo())  # type: ignore[arg-type]
    w = World(tmp_path, render=partial(run_recipe, video_renderer=renderer))
    outcome = w.handler.handle(w.job("b-zoom"))
    assert outcome.status == "done", outcome
    assert outcome.result["engine"] == "ffmpeg"
    assert outcome.result["fallback"] == "unreachable"
    assert outcome.result["recipe_version"] == "seasonal-b-1"
