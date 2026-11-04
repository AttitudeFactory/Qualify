"""Pre-PR fixes of m-24820842 (2026-11-04), the `Qualify/` side: the partial gallery's
cost note only where creations apply, «¿Dónde lo ponemos?» in the words of the piece,
«Hacer otra versión de esta» only of a piece that came out, the small consistency texts,
«Ir a Tu marca» under a refusal fixed there, and the logo corner request kept out of
what the owner reads (and ready to travel as a field)."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from . import creative_provider as provider
from . import creative_state as module
from .creative_state import CreativeState
from .creative_vm import (
    BRAND_FIX_LABEL,
    BRAND_FIX_ROUTE,
    FAILURE_INFO,
    build_draft_vm,
    failure_vm,
    finish_gallery_cost_note,
    needs_brand_fix,
)
from .generator_summary_vm import (
    CLIP_MIDDLE_NOTE,
    CLIP_SUBTITLES_SUMMARY,
    LOGO_IN_SCENE_GALLERY_TEXT,
    LOGO_IN_SCENE_TEXT,
    LOGO_IN_SCENE_VIDEO_TEXT,
    LOGO_SIGNATURE_REQUEST,
    LOGO_SIGNATURE_TEXT,
    logo_in_scene_text,
    logo_placement_text,
    owner_topic,
)

_LOGOS = [
    {"key": "r2/imago.png", "label": "Imagotipo", "kind": "logo", "view": "/r2media/a"},
    {"key": "r2/iso.png", "label": "Isotipo", "kind": "logo", "view": "/r2media/b"},
]


def _js(text: str) -> str:
    return json.dumps(text)[1:-1]


class _Proxy:
    """Reflex's StateProxy in a test: `async with self` is a no-op lock."""

    def __init__(self, state: CreativeState) -> None:
        object.__setattr__(self, "_state", state)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._state, name, value)


def _summary(state: CreativeState) -> dict[str, dict[str, str]]:
    state.go_to_view(str(len(state.gen_views) - 1))  # the summary
    return {row["label"]: row for row in state.gen_summary}


def _with_logo(category: str, *, corner: bool = False) -> CreativeState:
    state = CreativeState()
    state.choose_category(category)
    state.brief_topic = "Mi smash"
    state.ad_scene_prompt = "Mi smash"
    state.brand_media_items = list(_LOGOS)
    CreativeState.toggle_brand_logo.fn(state, "r2/imago.png")
    if corner:
        CreativeState.set_brand_logo_usage.fn(state, "signature")
    return state


# -- 1. «Crear las que faltan»: the cost only where creations apply ----------------------


def test_the_cost_note_says_how_many_and_that_it_comes_back() -> None:
    assert finish_gallery_cost_note(0) == ""
    assert finish_gallery_cost_note(-1) == ""
    one = finish_gallery_cost_note(1)
    assert one.startswith("Usa 1 creación,") and one.endswith("te la devolvemos.")
    two = finish_gallery_cost_note(2)
    assert two.startswith("Usa 2 creaciones,") and two.endswith("te las devolvemos.")


def test_the_cost_note_names_the_vistas_previas_of_the_animated_slides() -> None:
    """N2 (review 2026-11-04): an animated slide's retry also uses a vista previa — said
    beside the creations, and on its own for a gallery whose quote has no creations."""
    assert finish_gallery_cost_note(2, 1) == (
        "Usa 2 creaciones y 1 vista previa, las mismas que te devolvimos cuando falló. "
        "Si vuelve a fallar, te las devolvemos."
    )
    assert finish_gallery_cost_note(1, 3).startswith("Usa 1 creación y 3 vistas previas,")
    assert finish_gallery_cost_note(0, 1) == (
        "Usa 1 vista previa, la misma que te devolvimos cuando falló. "
        "Si vuelve a fallar, te la devolvemos."
    )
    assert finish_gallery_cost_note(0, 2).startswith("Usa 2 vistas previas, las mismas")
    assert finish_gallery_cost_note(0, 0) == ""


def _quote(weight: int, previews: int = 0) -> tuple[int, int, int, str, int, int, int]:
    return (weight, 10, 30, "1 de diciembre", previews, 20, 20)


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        (None, ""),
        (_quote(1), finish_gallery_cost_note(1)),
        (_quote(2), finish_gallery_cost_note(2)),
        # the same quote the backend charges: creations AND a vista previa per animated slide
        (_quote(1, 2), finish_gallery_cost_note(1, 2)),
        (_quote(0, 2), finish_gallery_cost_note(0, 2)),
    ],
)
def test_the_piece_page_reads_the_note_with_the_regen_quote(
    monkeypatch: pytest.MonkeyPatch, quote: object, expected: str
) -> None:
    """`regeneration_creations` is None on an unlimited plan or with the quota off (main's
    `creations_balance` → None): then the note says nothing about creations."""
    monkeypatch.setattr(module, "regeneration_creations", lambda *_a: quote)
    state = CreativeState()
    state.finish_gallery_note = "stale"
    asyncio.run(CreativeState._load_regen_creations(_Proxy(state), uuid4(), uuid4(), uuid4()))  # type: ignore[arg-type]
    assert state.finish_gallery_note == expected


def test_the_create_result_reads_the_note_and_an_unreadable_quote_says_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "regeneration_creations", lambda *_a: _quote(1))
    state = CreativeState()
    asyncio.run(CreativeState._load_finish_note(_Proxy(state), uuid4(), uuid4(), uuid4()))  # type: ignore[arg-type]
    assert state.finish_gallery_note == finish_gallery_cost_note(1)

    def boom(*_a: object) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(module, "regeneration_creations", boom)
    asyncio.run(CreativeState._load_finish_note(_Proxy(state), uuid4(), uuid4(), uuid4()))  # type: ignore[arg-type]
    assert state.finish_gallery_note == ""


def test_the_button_shows_the_note_only_when_there_is_one() -> None:
    from .creative_pages import finish_gallery_button

    rendered = str(finish_gallery_button(CreativeState.finish_gallery_current, 1))  # type: ignore[arg-type]
    assert 'finish_gallery_note_rx_state_?.valueOf?.() === ""' in rendered
    assert "Usa otra vez las creaciones" not in rendered


def test_going_back_to_the_form_forgets_the_note() -> None:
    state = CreativeState()
    state.finish_gallery_note = finish_gallery_cost_note(1)
    state._back_to_form()
    assert state.finish_gallery_note == ""


# -- 2. «¿Dónde lo ponemos?» names what the piece is -------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("static_flyer", LOGO_IN_SCENE_TEXT),
        ("carousel", LOGO_IN_SCENE_GALLERY_TEXT),
        ("clip", LOGO_IN_SCENE_VIDEO_TEXT),
        ("avatar_video", LOGO_IN_SCENE_VIDEO_TEXT),
        ("animated_avatar_video", LOGO_IN_SCENE_VIDEO_TEXT),
    ],
)
def test_the_scene_answer_matches_the_piece(kind: str, expected: str) -> None:
    assert logo_in_scene_text(kind) == expected
    assert logo_placement_text(kind, in_scene=True).startswith(f"{expected}, como")
    assert logo_placement_text(kind, in_scene=False) == LOGO_SIGNATURE_TEXT


def test_no_video_reads_about_a_photo() -> None:
    assert "foto" not in LOGO_IN_SCENE_VIDEO_TEXT
    assert "video" in LOGO_IN_SCENE_VIDEO_TEXT
    assert "fotos" in LOGO_IN_SCENE_GALLERY_TEXT


@pytest.mark.parametrize(
    ("category", "expected"),
    [("image", LOGO_IN_SCENE_TEXT), ("clip", LOGO_IN_SCENE_VIDEO_TEXT)],
)
def test_the_form_and_the_summary_say_the_same(category: str, expected: str) -> None:
    state = _with_logo(category)
    assert state.logo_in_scene_label == expected
    assert _summary(state)["Dónde irá tu logo"]["value"].startswith(expected)


def test_the_brand_block_takes_the_label_from_the_state() -> None:
    from .content_generator import _brand_resources

    assert "logo_in_scene_label" in str(_brand_resources())


# -- 3. «Hacer otra versión de esta» only of a piece that came out -----------------------


def test_another_version_only_of_a_ready_piece_and_both_buttons_44px() -> None:
    from .content_generator import NEW_PIECE_LABEL, NEW_VERSION_LABEL, _result_view

    rendered = str(_result_view())
    version = rendered.index(_js(NEW_VERSION_LABEL))
    # the version button sits inside the `gen_is_ready` condition — the last one before it
    row = rendered.rfind("jsx(RadixThemesFlex", 0, version)
    assert "gen_is_ready_rx_state_?(" in rendered[row:version]
    # the new-publication button is always there, outside that condition
    piece = rendered.index(_js(NEW_PIECE_LABEL), version)
    assert "gen_is_ready" not in rendered[version:piece]
    assert rendered[row:piece].count('["minHeight"] : "44px"') == 2


# -- 4. small consistency texts ----------------------------------------------------------


def test_the_clip_subtitles_summary_matches_the_switch() -> None:
    from .content_generator import CLIP_SUBTITLES_LABEL

    assert CLIP_SUBTITLES_SUMMARY == "Frase inicial e invitación a comprar"
    assert "invitación a comprar" in CLIP_SUBTITLES_LABEL
    state = CreativeState()
    state.choose_category("clip")
    state.set_clip_subtitles(True)
    assert _summary(state)["Subtítulos"]["value"] == CLIP_SUBTITLES_SUMMARY


def test_the_clip_middle_images_have_one_wording() -> None:
    from .content_generator import _clip_references_view

    assert module._CLIP_MIDDLE_NOTE == CLIP_MIDDLE_NOTE
    rendered = str(_clip_references_view())
    assert _js(CLIP_MIDDLE_NOTE) in rendered
    assert "guía el video como referencia" not in rendered


def test_the_carried_text_button_says_what_goes() -> None:
    from .content_generator import CLEAR_CARRIED_TEXT_LABEL, _carried_text_notice

    assert CLEAR_CARRIED_TEXT_LABEL == "Borrar este texto"
    rendered = str(_carried_text_notice())
    assert _js(CLEAR_CARRIED_TEXT_LABEL) in rendered and '"Borrarlo"' not in rendered


# -- 5. «Ir a Tu marca» under a refusal fixed in «Tu marca» ------------------------------

_CATEGORY_REFUSAL = (
    "No sabemos si «Bolsa» es un logo o una imagen de tu marca. "
    "Arréglalo en Tu marca y vuelve a elegirlo."
)


def test_the_backend_refusal_still_carries_the_words_we_match() -> None:
    """The refusal has no typed reason: the screen matches its words. Pin them to the
    backend's source so a rewording there fails here, not silently in production."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "packages/api/src/qualify_api/creative/brand_references.py").read_text(
        encoding="utf-8"
    )
    assert "Arréglalo en Tu marca" in source
    assert needs_brand_fix(_CATEGORY_REFUSAL)
    assert not needs_brand_fix("Elegiste el mismo logo dos veces.")
    assert not needs_brand_fix("")


def test_a_brand_refusal_gets_the_way_to_tu_marca() -> None:
    plain = failure_vm("invalid_parameters")
    assert plain is not None and plain.action_route == FAILURE_INFO["invalid_parameters"][2]
    fixed = failure_vm("invalid_parameters", _CATEGORY_REFUSAL)
    assert fixed is not None
    assert (fixed.action_label, fixed.action_route) == (BRAND_FIX_LABEL, BRAND_FIX_ROUTE)
    assert fixed.label == plain.label  # what happened is unchanged
    vm = build_draft_vm(
        draft_id="d",
        status="failed",
        failure_reason="invalid_parameters",
        variants=(),
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=None,
        model_ids=(),
        requires_ai_disclosure=False,
        created_label="",
        failure_detail=_CATEGORY_REFUSAL,
    )
    assert vm.failure is not None and vm.failure.action_route == BRAND_FIX_ROUTE


def test_the_form_and_the_result_show_the_way_to_tu_marca() -> None:
    from .content_generator import _create_error, _failed

    state = CreativeState()
    state.create_error = "Falta algo."
    assert state.create_error_brand_fix is False
    state.create_error = _CATEGORY_REFUSAL
    assert state.create_error_brand_fix is True
    rendered = str(_create_error())
    assert "create_error_brand_fix" in rendered and _js(BRAND_FIX_LABEL) in rendered
    assert BRAND_FIX_ROUTE in rendered
    assert "gen_failure_brand_fix" in str(_failed())


def test_the_piece_page_panel_links_the_action() -> None:
    from .creative_pages import _generation_failed_panel

    rendered = str(_generation_failed_panel())
    assert "action_route" in rendered and "action_label" in rendered


# -- 6. the corner request: sent, never shown; one line to switch to a field -------------


@pytest.mark.parametrize(("corner", "placement"), [(True, "signature"), (False, "scene")])
@pytest.mark.parametrize("category", ["image", "carousel", "clip", "video"])
def test_the_placement_travels_as_a_field_and_the_topic_stays_the_owners(
    category: str, corner: bool, placement: str
) -> None:
    state = _with_logo(category, corner=corner)
    form = state._generator_form()
    assert LOGO_SIGNATURE_REQUEST not in str(form["topic"])
    assert form["media"]["brand_logo_placement"] == placement  # type: ignore[index]


@pytest.mark.parametrize("category", ["template", "script"])
def test_templates_and_scripts_never_carry_a_placement(category: str) -> None:
    state = _with_logo(category, corner=True)
    state.brand_logo_key = "r2/imago.png"
    state.brand_logo_in_scene = False
    form = state._generator_form()
    assert "brand_logo_placement" not in form["media"]  # type: ignore[operator]
    assert LOGO_SIGNATURE_REQUEST not in str(form["topic"])


def test_no_logo_no_placement() -> None:
    state = CreativeState()
    state.choose_category("image")
    assert "brand_logo_placement" not in state._generator_form()["media"]  # type: ignore[operator]


@pytest.mark.parametrize(("corner", "in_scene"), [(True, False), (False, True)])
@pytest.mark.parametrize("category", ["image", "clip"])
def test_a_real_ui_payload_validates_as_media_inputs(
    category: str, corner: bool, in_scene: bool
) -> None:
    """The screen's payload through the backend's own `MediaInputs.model_validate` (the
    same call `creative_provider.build_brief` makes): the field is accepted and the
    corner turns the main logo into the signature, never also an in-scene reference."""
    from qualify_creative.schemas import MediaInputs

    state = _with_logo(category, corner=corner)
    CreativeState.toggle_brand_logo.fn(state, "r2/iso.png")  # a second logo, a reference
    media = MediaInputs.model_validate(dict(state._generator_form()["media"]))  # type: ignore[call-overload]
    assert media.brand_logo_placement == ("signature" if corner else "scene")
    assert media.brand_logo_in_scene is in_scene
    assert media.brand_logo_key == "r2/imago.png"
    if corner:
        assert "r2/imago.png" not in media.brand_logo_reference_keys


def test_the_owner_never_reads_the_corner_request() -> None:
    assert owner_topic(f"Un vaso en la barra\n{LOGO_SIGNATURE_REQUEST}") == "Un vaso en la barra"
    replica = f"Mi smash\n{LOGO_SIGNATURE_REQUEST}\n\n— Contexto —\nGuía"
    assert owner_topic(replica) == "Mi smash\n\n— Contexto —\nGuía"
    assert owner_topic("Pon el logo grande") == "Pon el logo grande"
    assert owner_topic("") == ""


@dataclass(frozen=True)
class _Record:
    id: UUID
    brief_id: UUID
    status: str
    created_at: datetime
    failure_reason: str | None = None


def test_the_drafts_list_shows_the_owners_words(monkeypatch: pytest.MonkeyPatch) -> None:
    brief_id = uuid4()
    record = _Record(uuid4(), brief_id, "generated", datetime(2026, 11, 4, tzinfo=UTC))
    service = SimpleNamespace(list_drafts=lambda **_k: [record])
    monkeypatch.setattr(provider, "production_content_service", lambda: service)

    class _Session:
        def execute(self, _query: object) -> SimpleNamespace:
            return SimpleNamespace(
                all=lambda: [(brief_id, f"Promo del lunes\n{LOGO_SIGNATURE_REQUEST}")]
            )

    @contextmanager
    def _session(_tenant: UUID):  # type: ignore[no-untyped-def]
        yield _Session()

    monkeypatch.setattr(provider, "tenant_session", _session)
    (summary,) = provider.list_drafts(uuid4(), uuid4())
    assert summary.topic == "Promo del lunes"
