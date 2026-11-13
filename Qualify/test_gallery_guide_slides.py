"""The carousel slide by slide (m-24985141 round 14, Deivid: «Uno para todo»): each
generated or animated slide chooses its photo (the product), its style (a guide) and, an
animated one, its motion; ONE background for the whole carousel, used per slide. The brief
validates against the real `MediaInputs` and `carousel_scene_plans`. Plus the refusal
said in the owner's words, the topic that follows the product and the phrase field that
cannot merge."""

from __future__ import annotations

from uuid import UUID

import pytest
from qualify_api.creative.brand_references import BrandReferenceError
from qualify_creative.scene_plan import ScenePlanError, carousel_scene_plans
from qualify_creative.schemas import MediaInputs

from . import creative_state as creative_state_module
from .content_generator import _section_rules, _slide_assignment
from .creative_state import CreativeState, _new_slide

A, B = "uploads/tenant/a.jpg", "uploads/tenant/b.jpg"
STYLE = "t/tenant/stock/pixabay/1/estilo.jpg"
PLACE = "uploads/tenant/local.jpg"
MOTION = "uploads/tenant/mov.mp4"


def _carousel(*sources: str) -> CreativeState:
    state = CreativeState()
    state.choose_category("carousel")
    state.carousel_slides = [_new_slide(src) for src in (sources or ("generated",) * 3)]
    state.carousel_selected = 0
    # what the drawer lists: uploads and a piece's files are the slot's own picks
    state.piece_items = [
        {"key": k, "label": k, "media_type": "image", "view": ""} for k in (A, B, STYLE, PLACE)
    ] + [{"key": MOTION, "label": "mov", "media_type": "video", "view": ""}]
    return state


def _on(state: CreativeState, n: int, target: str, key: str) -> None:
    state.carousel_selected = n
    state.pick_media(target, "pieces", key)


def _brief(state: CreativeState):
    media = MediaInputs.model_validate(state._media_inputs())
    return media, carousel_scene_plans(media)


@pytest.mark.parametrize(
    ("photo", "style", "expected"),
    [
        (A, "", {"product_index": A, "guide": None, "alone": False}),
        (A, STYLE, {"product_index": STYLE, "guide": A, "alone": False}),
        ("", STYLE, {"product_index": STYLE, "guide": None, "alone": True}),
        ("", "", {"product_index": None, "guide": None, "alone": False}),
    ],
    ids=["product", "product-and-style", "style-alone", "nothing"],
)
def test_the_translation_table(photo: str, style: str, expected: dict) -> None:
    state = _carousel("generated")
    if photo:
        _on(state, 0, "slide", photo)
    if style:
        _on(state, 0, "slide_style", style)
    media, plans = _brief(state)
    slide, keys = media.slides[0], list(media.product_keys)
    want = expected["product_index"]
    assert slide.product_index == (keys.index(want) if want else None)
    guide = expected["guide"]
    assert slide.guide_product_index == (keys.index(guide) if guide else None)
    assert slide.guide_alone is expected["alone"]
    roles = dict(zip(keys, media.product_image_roles, strict=True)) if keys else {}
    assert roles.get(STYLE, "composition") == "composition"
    assert roles.get(A, "product") == "product"
    assert len(plans) == 1


def test_one_background_for_every_slide_used_per_slide() -> None:
    state = _carousel()
    for n, key in enumerate((A, B, A)):
        _on(state, n, "slide", key)
    _on(state, 1, "background", PLACE)  # chosen from the 2nd slide
    assert state.media_background_key == PLACE
    state.carousel_selected = 0
    assert state.media_background_key == PLACE  # the same on every slide
    state.toggle_slide_background(2)  # the 3rd does not use it
    media, plans = _brief(state)
    assert media.background_key == PLACE and PLACE not in media.product_keys
    assert [slide.use_background for slide in media.slides] == [True, True, False]
    assert list(media.product_keys) == [A, B]
    assert len(plans) == 3


def test_taking_things_out() -> None:
    state = _carousel("animated")
    _on(state, 0, "slide", A)
    _on(state, 0, "slide_style", STYLE)
    _on(state, 0, "slide_reference", MOTION)
    _on(state, 0, "background", PLACE)
    assert state.carousel_current_plan == {"photo": A, "guide": STYLE, "motion": MOTION}
    state.clear_slide_photo()
    state.clear_slide_style()
    state.clear_slide_reference()
    state.clear_background()
    assert state.carousel_current_plan == {"photo": "", "guide": "", "motion": ""}
    assert state.media_background_key == ""
    _brief(state)


def test_motion_only_on_the_animated_slides() -> None:
    state = _carousel("generated", "animated")
    _on(state, 0, "slide_reference", MOTION)  # a generated slide takes none
    _on(state, 1, "slide_reference", MOTION)
    plan = state._carousel_plan()
    assert plan[0]["motion"] == "" and plan[1]["motion"] == MOTION
    _on(state, 1, "slide", A)
    media, _plans = _brief(state)
    assert media.slides[1].reference_video_key == MOTION


def test_the_drawer_closes_once_the_slot_holds_the_choice() -> None:
    state = _carousel()
    state.open_slide_drawer("photo")
    assert state.media_drawer_open and state.media_drawer_target == "slide"
    assert state.clip_source_tab == "catalog" or state.picker_tab_view["slide"] == "catalog"
    event = state.pick_media("slide", "pieces", A)
    assert not state.media_drawer_open and "slide-open-photo" in str(event)


def test_a_draft_from_before_keeps_its_slides() -> None:
    """A draft whose slide photo is an inspiration image (the guide of 2026-11-03) and
    its chosen product: read as its style and its photo."""
    state = _carousel("generated")
    state.carousel_slides[0].update(photo_key=STYLE, guide_key=A)
    assert state.carousel_current_plan == {"photo": A, "guide": STYLE, "motion": ""}
    media, _plans = _brief(state)
    assert media.slides[0].guide_product_index is not None


def test_the_slide_renders_its_elements() -> None:
    slide = str(_slide_assignment(True))
    for text in ("open_slide_drawer", "slide-open-photo", "slide-open-style", "Usar el fondo"):
        assert text in slide, text
    assert "El fondo es el mismo en todas las diapositivas." in slide


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


def test_a_change_of_kind_keeps_the_slides_choices() -> None:
    """Review: generated ↔ animated keeps the photo, the style, «Sin …» and the
    background switch; the motion only while it stays animated."""
    state = _carousel("generated", "generated")
    _on(state, 0, "slide", A)
    _on(state, 0, "slide_style", STYLE)
    state.toggle_slide_background(0)
    state.carousel_selected = 0
    state.set_slide_source("animated")
    _on(state, 0, "slide_reference", MOTION)
    assert state.carousel_current_plan == {"photo": A, "guide": STYLE, "motion": MOTION}
    assert state.carousel_slides[0]["background"] == ""
    state.set_slide_source("generated")
    assert state.carousel_current_plan == {"photo": A, "guide": STYLE, "motion": ""}
    assert state.carousel_slides[0]["background"] == ""
    state.clear_slide_style()  # «Sin estilo» stays «Sin estilo»
    state.set_slide_source("animated")
    assert state.carousel_current_plan["guide"] == ""


def test_changing_slide_closes_its_drawer() -> None:
    state = _carousel()
    state.open_slide_drawer("style")
    assert state.media_drawer_open
    state.select_carousel_slide(1)
    assert not state.media_drawer_open


# -- review (round 15): one photo, a product here and a style there ----------------------


def test_a_photo_and_the_same_photo_as_style_elsewhere() -> None:
    """(a) A is slide 1's photo and slide 2's style alone: two entries, each with its
    role — never «Una diapositiva de solo estilo necesita una foto de estilo»."""
    state = _carousel("generated", "generated")
    _on(state, 0, "slide", A)
    _on(state, 1, "slide_style", A)
    media, plans = _brief(state)
    assert list(media.product_keys) == [A, A]
    assert list(media.product_image_roles) == ["product", "composition"]
    assert media.slides[0].product_index == 0
    assert media.slides[1].product_index == 1 and media.slides[1].guide_alone
    assert len(plans) == 2


def test_a_style_first_never_moves_another_slides_product() -> None:
    """(b) style A on 1, photo A on 2, photo B on 3: slide 2 is made with A, never B."""
    state = _carousel()
    _on(state, 0, "slide_style", A)
    _on(state, 1, "slide", A)
    _on(state, 2, "slide", B)
    media, plans = _brief(state)
    keys, roles = list(media.product_keys), list(media.product_image_roles)
    second = media.slides[1].product_index
    assert keys[second] == A and roles[second] == "product"
    assert [photo.key for photo in plans[1].photos] == [A]
    assert [photo.key for photo in plans[2].photos] == [B]


def test_a_style_with_two_products_around_it() -> None:
    """(c) two products and A as one slide's style and another's photo: no «Esta guía
    tiene varias fotos de producto posibles»."""
    state = _carousel()
    _on(state, 0, "slide", A)
    _on(state, 0, "slide_style", B)
    _on(state, 1, "slide", B)
    _on(state, 2, "slide", A)
    _on(state, 2, "slide_style", STYLE)
    media, plans = _brief(state)
    assert len(plans) == 3
    first = plans[0]
    assert {photo.key for photo in first.photos} == {A, B}


def test_a_new_slide_with_an_inspiration_photo_is_its_style_alone() -> None:
    """Re-review: an inspiration image chosen as a new slide's photo never brings a
    product the owner did not choose — the slide goes out with that style alone."""
    state = _carousel()
    state.carousel_selected = 0
    state.pick_media("slide", "pieces", STYLE)
    _on(state, 1, "slide", A)
    plan = state._carousel_plan()
    assert plan[0] == {"photo": "", "guide": STYLE, "motion": ""}
    media, _plans = _brief(state)
    assert media.slides[0].guide_alone


def test_the_same_photo_as_photo_and_style_is_the_photo_alone() -> None:
    state = _carousel("generated")
    _on(state, 0, "slide", A)
    _on(state, 0, "slide_style", A)
    # the panel keeps what the owner chose; only what is sent drops the style
    assert state.carousel_current_plan == {"photo": A, "guide": A, "motion": ""}
    media, _plans = _brief(state)
    assert media.slides[0].guide_product_index is None and not media.slides[0].guide_alone
    assert list(media.product_keys) == [A] and list(media.product_image_roles) == ["product"]


def test_more_than_ten_entries_hold_crear_with_its_reason() -> None:
    from .creative_state import CAROUSEL_TOO_MANY

    state = _carousel()
    state.carousel_slides = [_new_slide("generated") for _ in range(6)]
    state.piece_items = [
        {"key": f"uploads/tenant/{n}.jpg", "label": str(n), "media_type": "image", "view": ""}
        for n in range(12)
    ]
    for n in range(6):
        _on(state, n, "slide", f"uploads/tenant/{n}.jpg")
        _on(state, n, "slide_style", f"uploads/tenant/{n + 6}.jpg")
    state.gen_step = len(state._gen_steps()) - 1
    assert state.create_primary_disabled and state.create_reason == CAROUSEL_TOO_MANY
    assert CAROUSEL_TOO_MANY == (
        "Tu carrusel usa más de 10 fotos contando Foto y Estilo de cada diapositiva. Quita "
        "alguna para crearlo."
    )
