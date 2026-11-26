"""B6 (m-25048789): «Arma tu video» hands the backend the video it shows. End to end and
offline: the editor's state → «Crear» → the brief `creative_provider.build_brief` really
builds → what EF-06 reads of it (`video_pipeline.recipe.recipe_of`, its gates) — the same
stretches, texts and effects, at the same seconds, as the preview in sequence plays
(`CreativeState._clip_sequence`). No service, database, worker or vendor is touched: the
service's `create_draft` is replaced by the backend's own pure gates.

Also: the editor's warnings before «Crear» (EF-06 option A, «avisar y no crear»), the
backend's refusals in the owner's words, EF-15's daily cap, a brief stored with the old
`media.edit_recipe`, and that nothing the screen sends is something the backend cannot
make."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_api.creative.local_cap import LocalDailyCapReached
from qualify_api.creative.video_pipeline.local import (
    LOCAL_SOURCE_TOO_LONG_TEXT,
    effects_version_for,
    is_local_recipe,
)
from qualify_api.creative.video_pipeline.recipe import (
    RecipeRefused,
    clip_seconds,
    is_built_layer,
    recipe_of,
    refuse_unbuilt_recipe,
)
from qualify_creative.effects import RecipeProblem, load_effects
from qualify_creative.schemas import (
    LOCAL_TOTAL_MAX_S,
    LOCAL_TOTAL_MIN_S,
    SEGMENT_SOURCE_MAX_S,
    VIDEO_TEXT_FADE_DEFAULT_S,
    ContentBrief,
    EffectUse,
)

from . import clip_editor_vm
from . import creative_state as module
from . import editor_preview_contract as contract
from .creative_provider import build_brief
from .creative_state import CreativeState
from .test_generator_campaign import _Proxy

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND = UUID("c0000000-0000-4000-8000-000000000003")
_USER = UUID("d0000000-0000-4000-8000-000000000004")
_PHOTO = f"uploads/{_TENANT}/clip/foto.jpg"
_OWN = f"uploads/{_TENANT}/clip/video.mp4"
_SECOND = f"uploads/{_TENANT}/clip/otro.mp4"


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)


def _session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def session_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
        return _TENANT, _BRAND, _USER

    async def refresh(self: CreativeState, tenant_id: UUID, brand_id: UUID) -> None:
        return None

    monkeypatch.setattr(CreativeState, "_session_ids", session_ids)
    monkeypatch.setattr(CreativeState, "_refresh_creations", refresh)
    monkeypatch.setattr(module, "brand_campaign_options", lambda *a: [])
    monkeypatch.setattr(module, "apply_post_choice", lambda *a, **k: None)


def _editor() -> CreativeState:
    """A photo (2 s), the own video (20 s, at ×2 = 10 s) and a second video (8 s): a
    20 s video, with a text moved to 3–15 s and Vapor from 4 to 9 s."""
    state = CreativeState()
    state.choose_category("clip")
    state.brief_topic = "Promoción de 2×1 los martes"
    state.clip_images = [{"key": _PHOTO, "name": "foto.jpg", "source": "upload", "role": "product"}]
    state.clip_videos = [
        {"key": _OWN, "name": "video.mp4", "source": "upload"},
        {"key": _SECOND, "name": "otro.mp4", "source": "upload"},
    ]
    state.clip_sequence = [_PHOTO, _OWN, _SECOND]
    CreativeState.report_clip_source.fn(state, _OWN, 20.0, 1080, 1920)
    CreativeState.report_clip_media.fn(state, _SECOND, 8.0, 1080, 1920)
    CreativeState.set_clip_block_speed.fn(state, _OWN, "2")
    # ED-13: one text «Arriba» with its own seconds (dragged there)
    state.clip_text_uses = [_text(3.0, 15.0)]
    # ED-04: Vapor is a block with its own seconds (dragged there)
    state.clip_effect_uses = [
        {"uid": "u1", "effect_id": "vapor_capa", "start": 4.0, "end": 9.0, "lane": 0, "blocks": []}
    ]
    return state


def _text(start: float, end: float) -> dict[str, object]:
    """«2×1 hoy» «Arriba» with its own seconds (`end` -1 = to the end)."""
    return {
        "uid": "t1",
        "text": "2×1 hoy",
        "place": "top",
        "start": start,
        "end": end,
        "blocks": [],
        "fade": 0.5,
    }


async def _crear(state: CreativeState) -> list[object]:
    return [event async for event in CreativeState.submit_generator_form.fn(_Proxy(state))]


def _backend_create(seen: list[ContentBrief]):  # noqa: ANN202 — a test double
    """`submit_brief` with the real brief and the service's real gates on it (everything
    `create_draft` checks before a row: validity, what the engine makes, ownership)."""

    def create(tenant_id: UUID, brand_id: UUID, user_id: UUID, **form: object) -> UUID:
        brief = build_brief(brand_id, **form)  # type: ignore[arg-type]
        refuse_unbuilt_recipe(brief, tenant_id=tenant_id)
        seen.append(brief)
        return uuid4()

    return create


async def test_crear_sends_the_video_the_preview_shows(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _session(monkeypatch)
    seen: list[ContentBrief] = []
    monkeypatch.setattr(module, "submit_brief", _backend_create(seen))
    state = _editor()
    assert state._form_problem() == ""
    assert state.clip_edit_problem == ["", ""]
    preview = state._clip_sequence()

    await _crear(state)
    assert state.create_error == ""
    (brief,) = seen

    # EF-06 takes it: ONE `local` part with stretches, stamped for the local pipeline
    assert is_local_recipe(brief) and effects_version_for(brief) == 1
    assert brief.media.clip_reference_mode == "local"
    assert not brief.requires_ai_disclosure  # made here: not AI imagery
    (part,) = recipe_of(brief)

    # the stretches: every block of the preview, in its order, at its speed and turn
    assert len(part.segments) == len(preview.blocks) == 3
    for segment, block in zip(part.segments, preview.blocks, strict=True):
        assert segment.key == block.key
        if block.kind == "photo":
            assert (segment.kind, segment.start_s, segment.end_s) == ("photo", 0.0, block.dur)
        else:
            assert segment.kind == "video"
            assert (segment.start_s, segment.end_s) == (block.src_start, block.src_end)
            assert (segment.speed, segment.rotate) == (block.speed, block.rotate)
    assert [s.speed for s in part.segments] == [1.0, 2.0, 1.0]
    # the same length: the backend's (stretches at their speed) and the preview's clock
    assert clip_seconds(part) == pytest.approx(preview.total, abs=0.01) == 20.0

    # the text: the same words, place and seconds, with EF-05's fade (the preview's too)
    (text,) = part.text_layers
    (shown,) = preview.texts
    assert (text.text, text.place) == (shown.text, shown.place) == ("2×1 hoy", "top")
    assert (text.start_s, text.end_s) == (shown.start, shown.end) == (3.0, 15.0)
    assert text.fade_s == VIDEO_TEXT_FADE_DEFAULT_S
    assert (text.layout_id, text.layout_version) == ("scrim", contract.TEXT_LAYOUT_VERSION)

    # the effect: the same layer, at the same seconds, and one the backend lays (EF-08)
    (use,) = part.effects
    (layer,) = preview.effects
    assert use.effect_id == layer.effect_id == "vapor_capa"
    assert (use.start_s, use.end_s) == (layer.start, layer.end) == (4.0, 9.0)
    assert is_built_layer(use)


async def test_an_untouched_text_and_effect_cover_the_whole_video(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Untouched, the text runs to the end and the effect covers the whole video (no
    span): as the preview shows them, and inside the backend's own length."""
    _session(monkeypatch)
    seen: list[ContentBrief] = []
    monkeypatch.setattr(module, "submit_brief", _backend_create(seen))
    state = _editor()
    state.clip_text_uses = [_text(0.0, -1.0)]
    # untouched: on every block of the video (as «+ Efecto» puts it with nothing chosen)
    state.clip_effect_uses = []
    CreativeState.add_clip_effect.fn(state, "vapor_capa")
    await _crear(state)
    (part,) = recipe_of(seen[0])
    assert (part.text_layers[0].start_s, part.text_layers[0].end_s) == (0.0, None)
    assert (part.effects[0].start_s, part.effects[0].end_s) == (None, None)


async def test_cortar_sends_several_stretches_of_the_same_video(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _session(monkeypatch)
    seen: list[ContentBrief] = []
    monkeypatch.setattr(module, "submit_brief", _backend_create(seen))
    state = _editor()
    CreativeState.set_clip_block_speed.fn(state, _OWN, "1")  # back to 0–15 s
    CreativeState.select_clip_block.fn(state, _OWN)
    CreativeState.hear_clip_time.fn(state, 7.0, "pause")  # 5 s into the own video
    CreativeState.cut_clip_video.fn(state)
    await _crear(state)
    (part,) = recipe_of(seen[0])
    assert [(s.key, s.start_s, s.end_s) for s in part.segments] == [
        (_PHOTO, 0.0, 2.0),
        (_OWN, 0.0, 5.0),
        (_OWN, 5.0, 15.0),
        (_SECOND, 0.0, 8.0),
    ]


def test_a_video_made_here_uses_nothing_of_the_month(editor_on: None) -> None:
    """EF-06 (D3): the editor's video uses no creation, vista previa nor video second —
    the screen prices it as the service does, and hides the AI's «Duración» and sound."""
    state = _editor()
    price = state._creations_price()
    assert price is not None and (price.weight, price.videos, price.video_seconds) == (0, 0, 0)
    assert state.clip_edit_local and state.clip_edit_seconds == "20"
    state.go_to_view(str(len(state.gen_views) - 1))  # «Crear»'s summary
    summary = {row["label"]: row["value"] for row in state.gen_summary}
    assert summary["Publicación"].endswith(" · 20 s")
    assert "Sonido" not in summary


# -- warnings before «Crear» (EF-06 option A: avisar y no crear) ------------------------------


async def test_under_three_seconds_crear_says_how_long_and_creates_nothing(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _session(monkeypatch)
    seen: list[ContentBrief] = []
    monkeypatch.setattr(module, "submit_brief", _backend_create(seen))
    state = CreativeState()
    state.choose_category("clip")
    state.brief_topic = "Promoción"
    state.clip_images = [{"key": _PHOTO, "name": "foto.jpg", "source": "upload", "role": "product"}]
    # only photos, nothing faster: «Velocidad» is not offered
    words = "Tu video dura 2 s y necesita al menos 3 s. Agrega otra foto o video."
    assert state.clip_edit_problem == [words, "warn"]  # under the timeline, before «Crear»
    assert state._form_problem() == words
    await _crear(state)
    assert state.create_error == words and seen == []


def test_over_sixty_seconds_says_how_long(editor_on: None) -> None:
    state = CreativeState()
    state.choose_category("clip")
    keys = [f"uploads/{_TENANT}/clip/v{n}.mp4" for n in range(5)]
    state.clip_videos = [{"key": key, "name": "v.mp4", "source": "upload"} for key in keys]
    CreativeState.report_clip_source.fn(state, keys[0], 15.0, 1080, 1920)
    for key in keys[1:]:
        CreativeState.report_clip_media.fn(state, key, 15.0, 1080, 1920)
    assert state.clip_edit_problem == [
        "Tu video dura 75 s y puede durar hasta 60 s. Quita alguna foto o bloque de video, o "
        "hazlo más rápido en «Velocidad».",
        "warn",
    ]


def test_a_video_not_measured_yet_waits_and_one_that_cannot_be_read_says_so(
    editor_on: None,
) -> None:
    state = _editor()
    state.clip_media_seconds = {}  # the second video's length not read yet
    assert state.clip_edit_problem == [clip_editor_vm.CUT_WAITING, "info"]
    gallery = f"gallery/{_TENANT}/m1/v.mp4"  # an R2 video: its path is minted first
    state.clip_videos = [
        *state.clip_videos[:1],
        {"key": gallery, "name": "G", "source": "existing"},
    ]
    state.clip_sequence = [_PHOTO, _OWN, gallery]
    assert state.clip_edit_problem == [clip_editor_vm.CUT_WAITING, "info"]
    state._clip_media_urls = {gallery: ""}  # …it could not be minted: the preview cannot
    assert state.clip_edit_problem == [clip_editor_vm.LENGTH_UNKNOWN, "warn"]


def test_a_text_alone_has_nothing_to_go_over(editor_on: None) -> None:
    state = CreativeState()
    state.choose_category("clip")
    # ED-13: «+ Texto» puts nothing without a photo or a video, and says why
    CreativeState.open_clip_flow.fn(state, "text")
    assert state.clip_text_uses == [] and not state.clip_text_panel_on
    assert state.clip_text_add_reason == clip_editor_vm.NEEDS_MEDIA
    # a text kept while its photos and videos left: it has nothing to go over
    state.clip_text_uses = [_text(0.0, -1.0)]
    assert state.clip_edit_problem == [clip_editor_vm.NEEDS_MEDIA, "warn"]
    assert state._clip_edit_media() == {}  # nothing of the editor goes out


def test_what_only_an_ai_reads_does_not_go_in(editor_on: None) -> None:
    state = _editor()
    state.clip_audios = [{"key": f"uploads/{_TENANT}/clip/a.mp3", "name": "a.mp3"}]
    assert state.clip_edit_problem == [clip_editor_vm.NOT_IN_VIDEO, "warn"]


def test_without_anything_on_the_timeline_the_clip_is_the_ais_as_before(
    editor_on: None,
) -> None:
    state = CreativeState()
    state.choose_category("clip")
    assert state._clip_edit_media() == {} and state.clip_edit_problem == ["", ""]
    assert state._clip_media()["clip_reference_mode"] == "motion"
    assert not state.clip_edit_local


# -- the backend's refusals in the owner's words --------------------------------------------


async def _refused(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> CreativeState:
    _session(monkeypatch)

    def create(*args: object, **kwargs: object) -> UUID:
        raise exc

    monkeypatch.setattr(module, "submit_brief", create)
    state = _editor()
    await _crear(state)
    assert not state.is_submitting
    return state


async def test_the_backends_length_refusal_says_the_seconds(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    problem = RecipeProblem(
        code="local_length_out_of_range", part=None, field="segments", duration_s=61.5
    )
    state = await _refused(monkeypatch, RecipeRefused([problem]))
    assert state.create_error == clip_editor_vm.length_out_of_range_line(
        61.5, fast=True, video=True
    )
    assert state.create_error.startswith("Tu video dura 61,5 s y puede durar hasta 60 s")


async def test_a_part_out_of_range_of_a_video_by_parts_is_not_said_as_the_whole_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review B6: a video by parts (not the Clip made here) whose local part lasts out of
    3–60 s keeps the generic line — never «Tu video dura X s» with the part's seconds."""
    _session(monkeypatch)
    part = RecipeProblem(
        code="local_length_out_of_range", part=1, field="segments", duration_s=72.0
    )

    def create(*args: object, **kwargs: object) -> UUID:
        raise RecipeRefused([part])

    monkeypatch.setattr(module, "submit_brief", create)
    state = CreativeState()
    state.choose_category("clip")
    state.brief_topic = "Promoción"
    assert not state._clip_local()
    await _crear(state)
    assert state.create_error == module._BRIEF_INVALID
    assert "72" not in state.create_error
    # the same problem of the whole piece (no `part`) is said with its seconds
    whole = RecipeProblem(
        code="local_length_out_of_range", part=None, field="segments", duration_s=72.0
    )

    def create_whole(*args: object, **kwargs: object) -> UUID:
        raise RecipeRefused([whole])

    monkeypatch.setattr(module, "submit_brief", create_whole)
    await _crear(state)
    assert state.create_error == clip_editor_vm.length_out_of_range_line(72.0)


async def test_the_queue_off_and_any_other_refusal(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    off = RecipeRefused([RecipeProblem(code="local_unavailable", part=None, field="mode")])
    assert (await _refused(monkeypatch, off)).create_error == clip_editor_vm.LOCAL_UNAVAILABLE
    other = RecipeRefused([RecipeProblem(code="recipe_unavailable", part=None, field="effects")])
    assert (await _refused(monkeypatch, other)).create_error == clip_editor_vm.RECIPE_REFUSED


async def test_a9s_refusal_is_said_in_a9s_words(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ED-03: the backend's `segment_source_too_long` (A9, m-25042483) reaches «Crear» in
    the same words the editor says before it."""
    problem = RecipeProblem(
        code="segment_source_too_long", part=None, field="segments", duration_s=90.0
    )
    state = await _refused(monkeypatch, RecipeRefused([problem]))
    assert state.create_error == clip_editor_vm.SOURCE_TOO_LONG_REFUSED


def test_the_editors_a9_words_and_minute_are_the_backends() -> None:
    assert clip_editor_vm.SOURCE_TOO_LONG_REFUSED == LOCAL_SOURCE_TOO_LONG_TEXT
    assert clip_editor_vm.SOURCE_MAX_SECONDS == SEGMENT_SOURCE_MAX_S


async def test_the_daily_cap_is_said_on_the_editors_crear(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EF-15: today's videos made with the owner's photos and videos are spent — its own
    sentence reaches «Crear» on the editor's video too."""
    cap = LocalDailyCapReached(used=10, cap=10)
    state = await _refused(monkeypatch, cap)
    assert state.create_error == cap.text != ""


# -- what the screen sends is what the backend makes --------------------------------------


def test_every_effect_the_editor_sends_is_a_layer_the_backend_lays() -> None:
    library = load_effects()
    for effect in contract.CLIP_EFFECTS:
        if effect.effect_id == contract.FAST_MOTION:
            continue  # a speed of the stretch, never an effect (D-T3)
        use = EffectUse(effect_id=effect.effect_id, version=effect.version)
        assert is_built_layer(use, library), effect.effect_id
    recipe = clip_editor_vm.recipe_of(
        video_key="k",
        start=0,
        end=10,
        rotate=0,
        effects=[contract.FAST_MOTION],
        speed=2,
        text="",
        place="bottom",
    )
    assert recipe.effects == () and recipe.segments[0].speed == 2.0


def test_the_editors_length_bounds_are_ef06s() -> None:
    assert (clip_editor_vm.LOCAL_MIN_SECONDS, clip_editor_vm.LOCAL_MAX_SECONDS) == (
        LOCAL_TOTAL_MIN_S,
        LOCAL_TOTAL_MAX_S,
    )


def test_a_brief_stored_with_the_old_edit_recipe_still_opens_and_creates() -> None:
    """Before B6 the screen sent `media.edit_recipe` (never read): a brief stored with it
    builds, validates and goes through the service's gates without an error."""
    old = {
        "effects": [{"effect_id": "camara_rapida", "version": 1, "params": {}}],
        "text_layer": {"text": "Hola", "place": "bottom"},
        "segments": [{"key": _OWN, "start_s": 0, "end_s": 10, "speed": 5, "rotate": 0}],
    }
    brief = build_brief(
        _BRAND,
        objective="awareness",
        content_type="promotion",
        topic="Promoción",
        product_ref="",
        intent="organic",
        image_route="",
        source_media_key="",
        must_mention="",
        must_avoid="",
        kind="clip",
        media={"duration_seconds": 5, "edit_recipe": old},
    )
    assert "edit_recipe" not in brief.media.model_dump()
    assert brief.media.clip_reference_mode == "motion" and not brief.media.segments
    refuse_unbuilt_recipe(brief, tenant_id=_TENANT)  # nothing to refuse: as before B6
    stored = ContentBrief.model_validate(
        {
            **brief.model_dump(mode="json"),
            "media": {**brief.media.model_dump(mode="json"), "edit_recipe": old},
        }
    )
    assert stored.media == brief.media
