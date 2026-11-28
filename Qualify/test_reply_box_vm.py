"""m-25027374 (BU-A7): the reply box's flags come from the channel's descriptor."""

from __future__ import annotations

import pytest
from qualify_api.inbox.channels import (
    CHANNEL_CAPABILITIES,
    CHANNEL_INSTAGRAM_DM,
    CHANNEL_WHATSAPP,
    INSTAGRAM_DM,
    WHATSAPP,
    UnknownChannel,
)

from .reply_box_vm import (
    INSTAGRAM_BOX,
    MENU_PAUSE_NOTE,
    PLUS_CATALOGUE,
    SEND_DOORS,
    TOOL_BUTTONS,
    TOOL_FILE,
    TOOL_HEART,
    TOOL_PHOTO,
    TOOL_SAVED,
    TOOL_SUGGEST,
    TOOL_VOICE,
    WHATSAPP_BOX,
    box_for,
    draws,
    missing_doors,
    plus_rows,
    reply_box_vm,
)
from .ui.primitives import ORBIT_MAX_ITEMS, ORBIT_MAX_TEXT, ORBIT_MIN_ITEMS


@pytest.mark.parametrize("caps", list(CHANNEL_CAPABILITIES.values()), ids=lambda c: c.channel)
def test_every_flag_is_the_descriptor(caps) -> None:  # noqa: ANN001
    box = reply_box_vm(caps)
    assert box.channel == caps.channel
    assert box.can_photo == bool({"image", "video"} & caps.attachments)
    assert box.can_file == ("document" in caps.attachments)
    assert box.can_voice == ("audio" in caps.attachments)
    assert box.can_heart == (caps.stickers == "heart_only")
    assert box.can_stickers == (caps.stickers == "native")
    assert box.can_buttons == (caps.max_buttons > 0)
    assert box.max_buttons == caps.max_buttons
    assert box.can_saved == caps.saved_messages
    assert box.can_suggest == caps.suggest_reply
    assert box.can_close == caps.close_reopen
    assert box.can_assign == caps.assign
    assert box.has_menu_handoff == caps.menu_handoff
    assert box.has_payments == caps.payments
    assert box.can_send_approved == (caps.after_window == "approved_template")


def test_whatsapp_never_draws_suggest_reply_while_bu_a18_does_not_exist() -> None:
    assert WHATSAPP.suggest_reply is False
    assert not draws(WHATSAPP_BOX, TOOL_SUGGEST)
    assert draws(INSTAGRAM_BOX, TOOL_SUGGEST)


def test_the_plus_is_one_catalogue_each_channel_only_removes_rows() -> None:
    order = [key for key, _icon, _text in PLUS_CATALOGUE]
    for box in (WHATSAPP_BOX, INSTAGRAM_BOX):
        keys = [row.key for row in plus_rows(box)]
        assert keys == [k for k in order if k in keys]
        assert all(draws(box, k) for k in keys)


def test_whatsapp_keeps_todays_plus_rows_in_todays_order() -> None:
    assert [r.text for r in plus_rows(WHATSAPP_BOX)] == [
        "Tus productos",
        "Tu oferta",
        "Tu menú",
        "Formas de pago",
        "Cómo llegar",
        "Fotos y videos",
    ]


def test_instagram_plus_has_payments_and_directions_never_the_menu() -> None:
    """m-25143229: the same rows, names, icons and order as WhatsApp, minus «Tu menú»
    (no automatic menu on Instagram) — and, until their doors land, minus «Tus
    productos», «Tu oferta» and «Fotos y videos». `payments` (the «Pago por revisar»
    flow) stays WhatsApp's: SENDING the business's payment data does not need it."""
    assert INSTAGRAM_DM.payments is False
    rows = plus_rows(INSTAGRAM_BOX)
    assert [(r.key, r.icon, r.text) for r in rows] == [
        ("products", "package", "Tus productos"),
        ("offer", "tag", "Tu oferta"),
        ("payments", "wallet", "Formas de pago"),
        ("directions", "map-pin", "Cómo llegar"),
    ]
    whatsapp = {(r.key, r.icon, r.text) for r in plus_rows(WHATSAPP_BOX)}
    assert all((r.key, r.icon, r.text) in whatsapp for r in rows)
    assert "Tu menú" not in [r.text for r in rows]
    assert ORBIT_MIN_ITEMS <= len(rows) <= ORBIT_MAX_ITEMS  # two rows: the «+» is drawn
    # 2026-11-15: photo, file and voice stay tools (a real tap on the file input).
    for key in (TOOL_PHOTO, TOOL_FILE, TOOL_VOICE):
        assert draws(INSTAGRAM_BOX, key)


def test_the_plus_fits_the_orbit_menu_rules() -> None:
    rows = plus_rows(WHATSAPP_BOX)
    assert ORBIT_MIN_ITEMS <= len(rows) <= ORBIT_MAX_ITEMS
    assert all(0 < len(r.text) <= ORBIT_MAX_TEXT for r in rows)


def test_a_door_is_never_drawn_where_the_descriptor_refuses() -> None:
    for box in (WHATSAPP_BOX, INSTAGRAM_BOX):
        for key in SEND_DOORS[box.channel]:
            if key == TOOL_HEART:
                assert draws(box, key) == box.can_heart
    assert not draws(WHATSAPP_BOX, TOOL_HEART)  # WhatsApp's stickers are native, not ❤


def test_missing_doors_name_what_the_api_allows_but_no_screen_sends() -> None:
    # BU-A8: WhatsApp has no saved-messages library yet; m-25143229 opened Instagram's
    # payments and directions, its products, offer and media are still to come.
    assert TOOL_SAVED in missing_doors(WHATSAPP_BOX)
    assert "file" in missing_doors(WHATSAPP_BOX)
    assert missing_doors(INSTAGRAM_BOX) == ("media",)
    assert "menu" not in missing_doors(INSTAGRAM_BOX)  # not allowed: not a missing door
    assert TOOL_BUTTONS not in missing_doors(INSTAGRAM_BOX)


def test_an_unknown_channel_has_no_box() -> None:
    with pytest.raises(UnknownChannel):
        box_for("comment")
    assert box_for(CHANNEL_WHATSAPP) == WHATSAPP_BOX
    assert box_for(CHANNEL_INSTAGRAM_DM) == INSTAGRAM_BOX


def test_the_menu_note_uses_the_founders_name_for_the_menu() -> None:
    assert "respuesta automática" not in MENU_PAUSE_NOTE
    assert "tu menú de bienvenida" in MENU_PAUSE_NOTE
