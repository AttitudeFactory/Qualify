"""m-24828920: the generator's words in the brand's type and colours, and the avatar
video's optional subtitles — through the real `MediaProducer`, vendors faked. The voice
analysis and the encode are PyAV's (tested in `packages/creative`); here they are
stubbed so the producer's choices are what is under test."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.compose import TextStyle
from qualify_creative.enums import ContentKind
from qualify_creative.video import FittedVideo, SubtitleLayer

from qualify_api.creative import media as media_module
from qualify_api.creative.brand_fonts import DbBrandFontFiles
from qualify_api.creative.brand_kit_store import BrandAsset
from qualify_api.creative.media import (
    BRAND_COLORS_DEFAULT,
    BRAND_FONT_DEFAULT,
    SUBTITLES_FAILED_TEXT,
    SUBTITLES_NO_VOICE_TEXT,
    SUBTITLES_NOT_ADDED,
    generated_key,
)

from .test_creative_media_byteplus import (
    BRAND_ID,
    BUDGET,
    COPY,
    PUBLIC_VOICE,
    TENANT_ID,
    FakeLinks,
    FakeOmniHuman,
    FakeSeedance,
    FakeSeedream,
    FakeSpeech,
    MemoryStore,
    _brief,
    _kit,
    _presenter,
    _presenter_brief,
    _producer,
    _seedance_brief,
    _store,
)

FONT = (
    Path(__file__).resolve().parents[2] / "creative" / "tests" / "fixtures" / "DejaVuSans.ttf"
).read_bytes()
FONT_KEY = f"t/{TENANT_ID}/brand/{BRAND_ID}/font/heading/abc_Marca-Bold.ttf"
SPANS = [(0.3, 1.6), (2.1, 4.0)]


class SubtitlingFitter:
    """Draws the subtitles for a 720×1280 video, as the real fitter does once it has
    opened the file, and stands in for the encode."""

    def __init__(self, *, fail: bool = False) -> None:
        self.layers: list[SubtitleLayer] = []
        self.calls = 0
        self.fail = fail

    def subtitle(
        self, data: bytes, *, layers: Callable[[tuple[int, int]], Sequence[SubtitleLayer]]
    ) -> FittedVideo:
        self.calls += 1
        if self.fail:
            raise ValueError("the file has no video stream")
        self.layers = list(layers((720, 1280)))
        return FittedVideo(data=b"subtitled-" + data, width=720, height=1280, duration_sec=4.0)


@pytest.fixture
def voice(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """The voice analysis: SPANS for anything but a "silent" file. Records what it was
    asked to analyse."""
    heard: list[bytes] = []

    def spans(data: bytes) -> list[tuple[float, float]]:
        heard.append(data)
        return [] if data.startswith(b"silent") else SPANS

    monkeypatch.setattr(media_module, "voice_spans", spans)
    return heard


def _omni(store: MemoryStore, fitter: SubtitlingFitter, **kw: Any) -> Any:
    producer = _presenter(
        store, seedream=FakeSeedream(), speech=FakeSpeech(), omni=FakeOmniHuman(), links=FakeLinks()
    )
    producer._fitter = fitter
    for name, value in kw.items():
        setattr(producer, f"_{name}", value)
    return producer


def _run(producer: Any, brief: Any, kit: Any = None) -> tuple[Any, UUID]:
    draft_id = uuid4()
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=brief,
        kit=kit or _kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None, outcome.detail
    return outcome, draft_id


def _codes(outcome: Any) -> list[str]:
    return [warning.code for warning in outcome.warnings]


# -- the avatar video's subtitles ---------------------------------------------------------


def test_subtitles_are_burnt_in_when_asked_for_timed_on_the_voice(voice: list[bytes]) -> None:
    store, fitter = _store(), SubtitlingFitter()
    store.files[FONT_KEY] = FONT
    producer = _omni(store, fitter, brand_fonts=lambda **_: FONT_KEY)
    outcome, draft_id = _run(producer, _presenter_brief(voice_id=PUBLIC_VOICE, subtitles=True))

    # the stored video is the subtitled one, timed on the Seed Speech track it was made
    # from — the short MP3, not a decode of the whole video (review 2026-10-22)
    assert store.files[generated_key(TENANT_ID, draft_id, "video.mp4")] == b"subtitled-omni-mp4"
    assert voice == [b"ID3-mp3-bytes"]
    lines = " ".join(COPY.script.split())
    assert fitter.layers and fitter.layers[0].start == SPANS[0][0]
    assert all(SPANS[0][0] <= layer.start < layer.end for layer in fitter.layers)
    assert fitter.layers[-1].end <= SPANS[-1][1] + 0.4 + 1e-9
    assert len(fitter.layers) >= len(lines) // 42
    # the row says the size the video was encoded at
    (video,) = outcome.media
    assert (video.width, video.height) == (720, 1280)
    # the brand's font file was found, and the kit has a palette: nothing to warn
    assert _codes(outcome) == []


def test_without_the_switch_the_video_is_untouched_and_no_style_is_read(
    voice: list[bytes],
) -> None:
    store, fitter = _store(), SubtitlingFitter()
    fonts: list[Any] = []
    producer = _omni(store, fitter, brand_fonts=lambda **kw: fonts.append(kw))
    outcome, draft_id = _run(producer, _presenter_brief(voice_id=PUBLIC_VOICE))
    assert store.files[generated_key(TENANT_ID, draft_id, "video.mp4")] == b"omni-mp4"
    assert fitter.calls == 0 and voice == [] and fonts == []
    assert _codes(outcome) == []


def test_a_voice_that_cannot_be_found_keeps_no_subtitles_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heard: list[bytes] = []

    def spans(data: bytes) -> list[tuple[float, float]]:
        heard.append(data)
        return []

    monkeypatch.setattr(media_module, "voice_spans", spans)
    store, fitter = _store(), SubtitlingFitter()
    outcome, draft_id = _run(
        _omni(store, fitter), _presenter_brief(voice_id=PUBLIC_VOICE, subtitles=True)
    )
    assert store.files[generated_key(TENANT_ID, draft_id, "video.mp4")] == b"omni-mp4"
    # the track first; the video's own audio only because the track yielded nothing
    assert heard == [b"ID3-mp3-bytes", b"omni-mp4"]
    assert fitter.calls == 0
    (warning,) = [w for w in outcome.warnings if w.code == SUBTITLES_NOT_ADDED]
    assert warning.detail == SUBTITLES_NO_VOICE_TEXT


def test_a_failed_burn_in_keeps_the_paid_video(voice: list[bytes]) -> None:
    store, fitter = _store(), SubtitlingFitter(fail=True)
    outcome, draft_id = _run(
        _omni(store, fitter), _presenter_brief(voice_id=PUBLIC_VOICE, subtitles=True)
    )
    assert store.files[generated_key(TENANT_ID, draft_id, "video.mp4")] == b"omni-mp4"
    (warning,) = [w for w in outcome.warnings if w.code == SUBTITLES_NOT_ADDED]
    assert warning.detail == SUBTITLES_FAILED_TEXT


def test_a_seedance_video_never_gets_subtitles(voice: list[bytes]) -> None:
    """Review 2026-10-22: a Seedance clip lasts a fraction of the script and mixes ambient
    sound into its voice — subtitled, it would flash lines it never says. Asked for
    anyway (an old brief, the API), the video is left as it is and nothing is read."""
    store, fitter = _store(), SubtitlingFitter()
    producer = _producer(store, seedream=FakeSeedream(), seedance=FakeSeedance())
    producer._fitter = fitter
    fonts: list[Any] = []
    producer._brand_fonts = lambda **kw: fonts.append(kw)
    outcome, draft_id = _run(producer, _seedance_brief(subtitles=True))
    assert store.files[generated_key(TENANT_ID, draft_id, "video.mp4")] == b"mp4-bytes"
    assert fitter.calls == 0 and voice == [] and fonts == []
    assert _codes(outcome) == []


def test_only_a_piece_that_prints_words_reads_the_brand_style() -> None:
    """Review 2026-10-22: the font warning showed on pieces without a single word."""
    from qualify_creative.enums import SlideSource, SlideText, VideoEngine
    from qualify_creative.schemas import CarouselSlide

    from qualify_api.creative.media import _prints_words

    piece = f"t/{TENANT_ID}/generated/{uuid4()}/r1/slide-1.jpg"
    reused = CarouselSlide(source=SlideSource.EXISTING, object_key=piece)
    worded = CarouselSlide(source=SlideSource.GENERATED, text=SlideText.HOOK, scene_prompt="x")
    assert _prints_words(_brief(ContentKind.STATIC_FLYER))
    assert not _prints_words(_brief(ContentKind.CAROUSEL, slides=(reused, reused)))
    assert _prints_words(_brief(ContentKind.CAROUSEL, slides=(reused, worded)))
    assert _prints_words(_brief(ContentKind.CAROUSEL, slides=(reused,), closing_slide=True))
    assert _prints_words(_presenter_brief(subtitles=True))
    assert not _prints_words(_presenter_brief())
    seedance = _presenter_brief(subtitles=True).media.model_copy(
        update={"video_engine": VideoEngine.SEEDANCE}
    )
    assert not _prints_words(_presenter_brief().model_copy(update={"media": seedance}))
    assert not _prints_words(_brief(ContentKind.CLIP, subtitles=True))


# -- the brand's type and colours ---------------------------------------------------------


def _ad_styles(monkeypatch: pytest.MonkeyPatch) -> list[TextStyle]:
    """The style every advertising image is composed with."""
    seen: list[TextStyle] = []
    real = media_module.render_ad_slides

    def spy(**kwargs: Any) -> list[bytes]:
        seen.append(kwargs["style"])
        return real(**kwargs)

    monkeypatch.setattr(media_module, "render_ad_slides", spy)
    return seen


def test_the_ad_image_is_drawn_in_the_brand_font_file_and_palette(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _ad_styles(monkeypatch)
    store = _store()
    store.files[FONT_KEY] = FONT
    producer = _producer(store, seedream=FakeSeedream())
    producer._brand_fonts = lambda **_: FONT_KEY
    google: list[str] = []
    producer._google_fonts = lambda family: google.append(family)
    outcome, _ = _run(producer, _brief(ContentKind.STATIC_FLYER))
    (style,) = seen
    assert style.font == FONT
    # the kit's two colours reach only 2.5:1 together: its first, outlined in black
    assert style.colors == ("#C4622D", "#000000")
    assert google == [] and _codes(outcome) == []


def test_without_a_file_the_family_comes_from_google_fonts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _ad_styles(monkeypatch)
    producer = _producer(_store(), seedream=FakeSeedream())
    asked: list[str] = []
    producer._google_fonts = lambda family: asked.append(family) or FONT
    kit = _kit().model_copy(update={"font_heading": "Lobster", "font_body": "Lobster"})
    outcome, _ = _run(producer, _brief(ContentKind.STATIC_FLYER), kit)
    assert asked == ["Lobster"] and seen[0].font == FONT
    assert _codes(outcome) == []


def test_a_font_that_cannot_be_drawn_is_the_default_with_a_warning_never_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _ad_styles(monkeypatch)
    store = _store()
    store.files[FONT_KEY] = b"wOF2-not-drawable"
    producer = _producer(store, seedream=FakeSeedream())
    producer._brand_fonts = lambda **_: FONT_KEY
    producer._google_fonts = lambda family: None
    kit = _kit().model_copy(update={"font_heading": "Marca Sans"})
    outcome, _ = _run(producer, _brief(ContentKind.STATIC_FLYER), kit)
    assert seen[0].font is None
    (warning,) = outcome.warnings
    assert warning.code == BRAND_FONT_DEFAULT and "«Marca Sans»" in warning.detail


def test_a_kit_with_neither_font_nor_colours_renders_with_the_defaults_and_two_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _ad_styles(monkeypatch)
    kit = _kit().model_copy(update={"palette_rgb": ()})
    outcome, _ = _run(
        _producer(_store(), seedream=FakeSeedream()), _brief(ContentKind.STATIC_FLYER), kit
    )
    assert seen[0] == TextStyle()
    assert sorted(_codes(outcome)) == [BRAND_COLORS_DEFAULT, BRAND_FONT_DEFAULT]


def test_an_unreadable_kit_never_fails_the_piece(monkeypatch: pytest.MonkeyPatch) -> None:
    _ad_styles(monkeypatch)
    producer = _producer(_store(), seedream=FakeSeedream())

    def down(**_: Any) -> str:
        raise RuntimeError("database is down")

    producer._brand_fonts = down
    outcome, _ = _run(producer, _brief(ContentKind.STATIC_FLYER))
    assert _codes(outcome) == [BRAND_FONT_DEFAULT]


# -- the kit's font file -------------------------------------------------------------------


class FakeKitStore:
    def __init__(self, assets: list[BrandAsset]) -> None:
        self.assets = assets

    def list_assets(self, *, tenant_id: UUID, brand_id: UUID) -> list[BrandAsset]:
        return self.assets


def _asset(kind: str, slot: str, key: str) -> BrandAsset:
    return BrandAsset(kind=kind, slot=slot, object_key=key, filename=key, content_type="")


def test_the_kits_font_file_is_its_heading_tile_then_an_old_body_one() -> None:
    both = FakeKitStore(
        [
            _asset("logo", "", "l.png"),
            _asset("font", "body", "b.ttf"),
            _asset("font", "heading", "h.ttf"),
        ]
    )
    assert DbBrandFontFiles(both)(tenant_id=TENANT_ID, brand_id=BRAND_ID) == "h.ttf"
    body = FakeKitStore([_asset("font", "body", "b.ttf")])
    assert DbBrandFontFiles(body)(tenant_id=TENANT_ID, brand_id=BRAND_ID) == "b.ttf"
    assert DbBrandFontFiles(FakeKitStore([]))(tenant_id=TENANT_ID, brand_id=BRAND_ID) is None
