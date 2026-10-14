"""The four primitives the founder approved on 2026-10-09 — `dropzone`, `choice_card`,
`media_thumb`, `chat_bubble` — build, wear their classes, and carry the ARIA the design
system promises (docs/design-system.md §5.9). Pure component construction: no page, no
state, so it runs in the offline gate."""

from __future__ import annotations

import reflex as rx

from Qualify.ui import chat_bubble, choice_card, choice_card_check, dropzone, media_thumb


def _render(component: rx.Component) -> str:
    return str(component)


def test_dropzone_is_the_unstyled_upload_wearing_the_material() -> None:
    zone = _render(dropzone(rx.text("suelta"), upload_id="u1", on_drop=None))
    assert 'className:"rx-Upload q-dropzone"' in zone  # the widget's own class + ours
    assert "border" not in zone  # the styled rx.upload would inject one inline

    compact = _render(dropzone(rx.text("x"), upload_id="u2", on_drop=None, variant="compact"))
    assert "q-dropzone q-dropzone--compact" in compact

    tile = _render(
        dropzone(rx.text("+"), upload_id="u3", on_drop=None, variant="tile", tile_size="8rem")
    )
    assert "q-dropzone q-dropzone--tile" in tile and "--q-dropzone-tile" in tile and "8rem" in tile

    bare = _render(dropzone(rx.button("Subir"), upload_id="u4", on_drop=None, variant="bare"))
    assert 'className:"rx-Upload q-dropzone--bare"' in bare


def test_choice_card_is_a_button_with_its_state_in_aria() -> None:
    on = _render(choice_card(rx.text("A"), selected=True, on_select=None))
    assert 'type:"button"' in on and 'role:"radio"' in on
    assert "q-choice-card q-choice-card--on" in on and '"aria-checked":(true' in on

    off = _render(choice_card(rx.text("B"), selected=False, disabled=True))
    assert "q-choice-card q-choice-card--off" in off and '"aria-disabled":"true"' in off
    assert "disabled:true" in off  # a real disabled button: no click, no Enter/Space
    assert "disabled:true" not in on

    multi = _render(choice_card(rx.text("C"), selected=False, role="checkbox"))
    assert 'role:"checkbox"' in multi

    check = _render(choice_card_check())
    assert "q-choice-card-check" in check and '"aria-hidden":"true"' in check


def test_media_thumb_falls_back_to_an_icon_in_the_same_frame() -> None:
    with_picture = _render(media_thumb("/a.png", size="56px", icon="film"))
    assert '"q-thumb"' in with_picture and "q-thumb--empty" in with_picture  # both branches
    assert '"56px"' in with_picture and "LucideFilm" in with_picture

    avatar = _render(media_thumb("", size="2.5rem", round=True, icon="user-round"))
    assert "q-thumb q-thumb--round" in avatar and "q-thumb--empty" in avatar

    banner = _render(media_thumb("/b.png", size=None, width="100%", height="9rem"))
    assert '"width"] : "100%"' in banner and '"height"] : "9rem"' in banner


def test_chat_bubble_knows_who_is_speaking() -> None:
    assert "q-bubble q-bubble--out" in _render(chat_bubble(rx.text("hola")))
    bubble_in = _render(chat_bubble(rx.text("hola"), direction="in", meta=rx.text("10:02")))
    assert "q-bubble q-bubble--in" in bubble_in and "10:02" in bubble_in
