"""Live gallery test (2026-11-03): an inspiration photo on a slide is a GUIDE; the owner
says which product photo appears in it, the brief carries it and «Crear» works — for a
generated slide and for the «Video animado» one. Plus the refusal said in the owner's
words, the topic that follows the product and the phrase field that cannot merge."""

from __future__ import annotations

from uuid import UUID

import pytest
from qualify_api.creative.brand_references import BrandReferenceError
from qualify_creative.scene_plan import ScenePlanError, carousel_scene_plans
from qualify_creative.schemas import MediaInputs

from . import creative_state as creative_state_module
from .content_generator import _section_rules, _slide_guide_product
from .creative_state import CreativeState, _new_slide

GUIDE = "t/tenant/stock/pixabay/1/guia.jpg"
PHOTO_A = "uploads/tenant/hamburguesa.jpg"
PHOTO_B = "uploads/tenant/papas.jpg"


def _slide(source: str, photo: str, name: str) -> dict[str, str]:
    slide = _new_slide(source)
    slide.update(photo_key=photo, photo_name=name)
    return slide


def _gallery(first: str = "generated") -> CreativeState:
    state = CreativeState()
    state.choose_category("carousel")
    state.carousel_slides = [
        _slide(first, GUIDE, "Inspiración"),
        _slide("generated", PHOTO_A, "Hamburguesa"),
        _slide("generated", PHOTO_B, "Papas"),
    ]
    state.carousel_selected = 0
    return state


def _plans(state: CreativeState):
    photos, slides = state._carousel_slides_payload(False)
    media = MediaInputs.model_validate({"product_keys": photos, "slides": slides})
    return photos, slides, carousel_scene_plans(media)


@pytest.mark.parametrize("first", ["generated", "animated"])
def test_a_guide_slide_offers_the_gallery_products_and_defaults_to_the_first(first: str) -> None:
    state = _gallery(first)
    choices = state.slide_guide_choices
    assert [c["key"] for c in choices] == [PHOTO_A, PHOTO_B]
    assert [c["chosen"] for c in choices] == ["1", ""]
    assert choices[0]["name"] == "Hamburguesa · diapositiva 2"
    photos, slides, plans = _plans(state)  # «Crear» no longer refuses
    assert slides[0]["guide_product_index"] == photos.index(PHOTO_A)
    assert plans[0].photo_keys == (PHOTO_A, GUIDE)
    # the guide is slide 1's alone (live test 2026-11-03, draft 320257e3)
    assert [plan.photo_keys for plan in plans[1:]] == [(PHOTO_A,), (PHOTO_B,)]


@pytest.mark.parametrize("first", ["generated", "animated"])
def test_the_owner_changes_the_guide_slides_product(first: str) -> None:
    state = _gallery(first)
    CreativeState.set_slide_guide_product.fn(state, PHOTO_B)
    assert [c["chosen"] for c in state.slide_guide_choices] == ["", "1"]
    photos, slides, plans = _plans(state)
    assert slides[0]["guide_product_index"] == photos.index(PHOTO_B)
    assert plans[0].photo_keys == (PHOTO_B, GUIDE)
    CreativeState.set_slide_guide_product.fn(state, "uploads/tenant/otra.jpg")  # not here
    assert state.carousel_slides[0]["guide_key"] == PHOTO_B


def test_a_product_slide_has_nothing_to_choose_and_sends_nothing_new() -> None:
    state = _gallery()
    state.carousel_selected = 1
    assert state.slide_guide_choices == []
    _photos, slides, _plans_ = _plans(state)
    assert "guide_product_index" not in slides[1] and "guide_product_index" not in slides[2]


def test_a_removed_choice_falls_back_to_the_first_product() -> None:
    state = _gallery()
    CreativeState.set_slide_guide_product.fn(state, PHOTO_B)
    state.carousel_slides = state.carousel_slides[:2]  # the slide with B was removed
    photos, slides, plans = _plans(state)
    assert slides[0]["guide_product_index"] == photos.index(PHOTO_A)


def test_a_guide_alone_needs_no_choice() -> None:
    """(b) only an inspiration photo and no product photo in the gallery."""
    state = CreativeState()
    state.choose_category("carousel")
    state.carousel_slides = [_slide("animated", GUIDE, "Inspiración"), _new_slide("generated")]
    state.carousel_selected = 0
    assert state.slide_guide_choices == []
    _photos, slides, plans = _plans(state)
    assert "guide_product_index" not in slides[0] and plans[0].photo_keys == (GUIDE,)


def test_the_choice_renders_as_a_radio_group() -> None:
    rendered = str(_slide_guide_product())
    assert "set_slide_guide_product" in rendered and "radiogroup" in rendered


# -- the refusal in the owner's words -----------------------------------------------------


async def test_a_scene_plan_refusal_is_shown_as_written(monkeypatch) -> None:
    async def session_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
        tenant = UUID("a0000000-0000-4000-8000-000000000001")
        return (tenant, tenant, tenant)

    def refuse(*args: object, **kwargs: object) -> None:
        raise ScenePlanError("Esta guía tiene varias fotos de producto posibles. Elige una.")

    monkeypatch.setattr(CreativeState, "_session_ids", session_ids)
    monkeypatch.setattr(creative_state_module, "submit_brief", refuse)
    state = CreativeState()
    state.is_submitting = True
    assert await state._create_draft({}) is None
    assert state.create_error.startswith("Esta guía tiene varias fotos de producto")

    def wrapped(*args: object, **kwargs: object) -> None:
        # the real submit path: `prepare_new_brief` re-raises the plan's refusal
        raise BrandReferenceError("Esta guía tiene varias fotos de producto posibles. Elige una.")

    monkeypatch.setattr(creative_state_module, "submit_brief", wrapped)
    await state._create_draft({})
    assert state.create_error.startswith("Esta guía tiene varias fotos de producto")

    def invalid(*args: object, **kwargs: object) -> None:
        raise ValueError("internal detail")

    monkeypatch.setattr(creative_state_module, "submit_brief", invalid)
    await state._create_draft({})
    assert state.create_error == creative_state_module._BRIEF_INVALID  # never internals


# -- item 2: the default topic follows the product ----------------------------------------


def _catalog_state() -> CreativeState:
    state = CreativeState()
    state.catalog_items = [
        {"id": "p1", "name": "Smash doble", "photo_key": "", "photo_keys": "", "video_keys": ""},
        {"id": "p2", "name": "Super smash", "photo_key": "", "photo_keys": "", "video_keys": ""},
    ]
    return state


def test_the_default_topic_follows_the_product() -> None:
    state = _catalog_state()
    CreativeState.choose_product.fn(state, "p1")
    assert state.brief_topic == "Smash doble"
    CreativeState.choose_product.fn(state, "p2")
    assert state.brief_topic == "Super smash"
    CreativeState.choose_product.fn(state, "p2")  # unpicked: its name goes with it
    assert state.brief_topic == ""


def test_the_owners_own_topic_is_never_replaced() -> None:
    state = _catalog_state()
    CreativeState.choose_product.fn(state, "p1")
    state.set_brief_topic("Promo de viernes con la smash")
    CreativeState.choose_product.fn(state, "p2")
    assert state.brief_topic == "Promo de viernes con la smash"


# -- item 3: a phrase added with Intro can never merge with the next one ------------------


def test_the_submit_takes_the_phrase_the_browser_sent() -> None:
    state = CreativeState()
    # the draft already holds the next keystrokes when the submit is processed
    state.brief_must_mention_draft = "Pide por WhatsAppCarne"
    CreativeState.submit_must_mention.fn(state, {"phrase": "Pide por WhatsApp"})
    assert state.brief_must_mention_items == ["Pide por WhatsApp"]
    assert state.brief_must_mention_draft == ""
    CreativeState.submit_must_mention.fn(state, {"phrase": "Carne smash hecha al momento"})
    assert state.brief_must_mention_items == ["Pide por WhatsApp", "Carne smash hecha al momento"]
    CreativeState.submit_must_avoid.fn(state, {"phrase": "barato"})
    assert state.brief_must_avoid == "barato"


def _forms(component: object) -> list:
    found = []
    if type(component).__name__ == "Form":
        found.append(component)
    for child in getattr(component, "children", []):
        found.extend(_forms(child))
    return found


def test_the_phrase_field_is_a_form_that_resets_itself() -> None:
    section = _section_rules()
    forms = _forms(section)
    assert len(forms) == 2
    handlers = " ".join(str(form.event_triggers.get("on_submit")) for form in forms)
    assert "submit_must_mention" in handlers and "submit_must_avoid" in handlers
    assert all(str(form.reset_on_submit) in ("true", "True") for form in forms)
    rendered = str(section)
    assert 'type:"submit"' in rendered


def test_the_field_is_emptied_in_the_same_tick_as_the_submit() -> None:
    """Live regression 2026-11-03 («Pide por WhaCarne…tsApp»): the browser-side submit
    handler (the JS Reflex compiles for each form) reads the field and then empties it
    synchronously — no `await`, no server round-trip in between — and the field has no
    `value`/`defaultValue`/`key` a server update could use to put an old phrase back or
    remount it while the owner types."""
    for form in _forms(_section_rules()):
        (hook,) = form.add_hooks()
        body = hook.split("useCallback((ev) => {", 1)[1]
        read = body.index("new FormData($form)")
        send = body.index("addEvents(")
        reset = body.index("$form.reset()")
        assert read < send < reset
        assert "await" not in body and "setTimeout" not in body
        (field,) = _all(form, "TextFieldRoot")
        props = str(field)
        for prop in ("value:", "defaultValue:", "key:"):
            assert prop not in props, prop


def test_agregar_keeps_the_focus_in_the_field() -> None:
    """A click on «Agregar» does not move the focus off the field (its mousedown is
    prevented), so the next phrase is typed straight into the emptied field."""
    for form in _forms(_section_rules()):
        (button,) = _all(form, "Button")
        assert "preventDefault" in str(button.event_triggers.get("on_mouse_down"))


def _all(component: object, name: str) -> list:
    found = [component] if type(component).__name__ == name else []
    for child in getattr(component, "children", []):
        found.extend(_all(child, name))
    return found


def test_intro_submits_the_phrase_form() -> None:
    """Live regression 2026-11-03: Intro added nothing. HTML implicit submission (Intro
    or the phone's «Listo» in the form's one text field) clicks the form's submit button
    — and does NOTHING if that button is disabled. So each form has exactly one text
    field, one submit button never disabled by the draft (only when the list is full),
    and no key handler of its own that could swallow Intro."""
    for form in _forms(_section_rules()):
        inputs = [c for c in _all(form, "TextFieldRoot")]
        buttons = [c for c in _all(form, "Button")]
        assert len(inputs) == 1 and len(buttons) == 1
        field, button = inputs[0], buttons[0]
        assert "on_key_down" not in field.event_triggers
        assert str(field.name) in ('"phrase"', "phrase")
        assert str(button.type) in ('"submit"', "submit")
        disabled = str(button.disabled)
        assert "draft" not in disabled and "length" in disabled  # only «full»
        assert "on_click" not in button.event_triggers  # the form's submit, nothing else


def test_a_typed_phrase_never_added_still_counts_on_leaving() -> None:
    state = CreativeState()
    state.set_brief_must_mention_draft("envío gratis")
    state._flush_phrase_drafts()
    assert state.brief_must_mention == "envío gratis" and state.brief_must_mention_draft == ""


def test_an_inspiration_video_is_a_motion_reference_never_a_product_photo() -> None:
    """«Video animado» with an inspiration photo and an inspiration VIDEO: the video is
    the motion reference only — it never enters the product photos or the guide choice."""
    state = _gallery("animated")
    state.carousel_slides[0]["ref_key"] = "t/tenant/stock/pixabay/2/movimiento.mp4"
    photos, slides, plans = _plans(state)
    assert slides[0]["reference_video_key"] == "t/tenant/stock/pixabay/2/movimiento.mp4"
    assert "t/tenant/stock/pixabay/2/movimiento.mp4" not in photos
    assert plans[0].photo_keys == (PHOTO_A, GUIDE)
