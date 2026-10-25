"""`qualify_api.privacy.phones` (m-24854323, OL2-7): phone numbers masked in free text,
keeping the country code written and the last two digits — and nothing else touched
(prices, dates, hours, counts, hashtags, handles, other links)."""

from __future__ import annotations

import pytest

from qualify_api.privacy import MASK_BODY, mask_phones, mask_phones_in, whatsapp_numbers

M = MASK_BODY  # "••• ••• ••"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Colombia
        ("WhatsApp +57 300 123 4548", f"WhatsApp +57 {M}48"),
        ("+573001234548", f"+57 {M}48"),
        ("(+57) 300-123-4567", f"+57 {M}67"),
        ("+57 (300) 123 4567", f"+57 {M}67"),
        ("57 3001234567", f"+57 {M}67"),
        ("0057 300 123 4567", f"+57 {M}67"),
        ("Cel 3001234567", f"Cel {M}67"),
        ("Cel 300.123.4567", f"Cel {M}67"),
        ("Cel 300 123 45 67", f"Cel {M}67"),
        ("Cel 3 0 0 1 2 3 4 5 6 7", f"Cel {M}67"),
        ("Fijo 601 234 5678", f"Fijo {M}78"),
        ("Tel: 601-2345678", f"Tel: {M}78"),
        ("tel:+573001234567", f"tel:+57 {M}67"),
        # Venezuela
        ("Pedidos al 0414-123.45.67", f"Pedidos al {M}67"),
        ("0412 1234567", f"{M}67"),
        ("+58 414 123 4567", f"+58 {M}67"),
        ("+58-412-1234567", f"+58 {M}67"),
        ("llama al (0212) 555-1234", f"llama al {M}34"),
        ("4241234567", f"{M}67"),
        # Uruguay
        ("+598 99 123 456", f"+598 {M}56"),
        ("+598 2900 1234", f"+598 {M}34"),
        ("099 123 456", f"{M}56"),
        ("099123456", f"{M}56"),
        ("Tel 2900 1234", f"Tel {M}34"),
        ("Tel. 2900-1234", f"Tel. {M}34"),
        ("llámanos 94123456", f"llámanos {M}56"),
        ("📞 24001234", f"📞 {M}34"),
        # anywhere else, written internationally
        ("+1 305 123 4567", f"+{M}67"),
        ("+34 612 34 56 78", f"+{M}78"),
        # WhatsApp links
        ("https://wa.me/573001234548", f"https://wa.me/+57 {M}48"),
        ("wa.me/+584141234567", f"wa.me/+58 {M}67"),
        ("Escríbenos: wa.me/3001234567", f"Escríbenos: wa.me/{M}67"),
        (
            "api.whatsapp.com/send?phone=59899123456&text=hola",
            f"api.whatsapp.com/send?phone=+598 {M}56&text=hola",
        ),
        (
            "https://api.whatsapp.com/send/?phone=%2B573001234567&text=Hola",
            f"https://api.whatsapp.com/send/?phone=+57 {M}67&text=Hola",
        ),
        ("https://tienda.co/contacto?tel=3001234567", f"https://tienda.co/contacto?tel={M}67"),
        # several in one text, and beside a year or a price
        (
            "Escríbenos wa.me/584141234567 o llama al (0212) 555-1234",
            f"Escríbenos wa.me/+58 {M}67 o llama al {M}34",
        ),
        ("Desde 2024 3001234567", f"Desde 2024 {M}67"),
        ("Tel 300 123 4567 / 601 234 5678", f"Tel {M}67 / {M}78"),
        ("Combo $35.000 pide al 3001234567", f"Combo $35.000 pide al {M}67"),
        ("Línea 1:\n3001234567", f"Línea 1:\n{M}67"),
        # numbers glued to the word that says what they are, or to a link
        ("Tel3001234567", f"Tel{M}67"),
        ("WhatsApp3001234567", f"WhatsApp{M}67"),
        ("https://linktr.ee/x,WhatsApp:3001234567", f"https://linktr.ee/x,WhatsApp:{M}67"),
        ("https://www.tienda.co📞3001234567", f"https://www.tienda.co📞{M}67"),
        # WhatsApp Business catalog links
        ("https://wa.me/c/573001234567", f"https://wa.me/c/+57 {M}67"),
        ("whatsapp.com/catalog/573001234567", f"whatsapp.com/catalog/+57 {M}67"),
    ],
)
def test_phones_are_masked(text: str, expected: str) -> None:
    assert mask_phones(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # prices
        "Precio $25.000",
        "25.000 COP",
        "$ 1.500.000",
        "$1.500.000 el combo",
        "Bs. 350,00",
        "Bs 3500000",
        "COP 25000000",
        "US$ 1200",
        "2.500.000 pesos",
        "Desde 350 mil",
        "25.000.000",
        "1,234,567",
        "350 000",
        "Combo x 2 por $35.000 hasta el 30/11",
        # dates and years
        "2026-10-25",
        "25/10/2026",
        "25-10-2026",
        "25.10.2026",
        "20261025",
        "Desde 2019",
        "2019 2020 2021",
        "Temporada 2025-2026",
        # opening hours
        "Lun a vie 8:00-17:00",
        "de 20.00 - 23.00",
        "Abrimos 10-22h",
        "Horario 9 a 18 y 19 a 23",
        # counts and percentages
        "12.000 seguidores",
        "1.234.567 seguidores",
        "1,2 M de vistas",
        "15% off",
        "+20% de descuento",
        "+10.000 clientes felices",
        "+1.500 pedidos",
        # hashtags, handles and other links
        "#3001234567",
        "@tienda3001234567",
        "@cafe_3001234567",
        "cafe3001234567",
        "Pedido ABC3001234567",
        "https://scontent.cdninstagram.com/v/t51.2885-19/123456789_3001234567_n.jpg?oh=00_AfB&oe=67230E5A",
        "instagram.com/p/30012345678",
        "https://www.tiktok.com/@tienda/video/7301234567890123456",
        # identity numbers and bare 8 digits with no phone cue
        "NIT 900.123.456-7",
        "C.C. 1.090.123.456",
        "Pedido 25000000",
        "94123456",
        # nothing to do
        "",
        "Heladería de yogur. Postres y helados artesanales en Cúcuta 🇨🇴 Pedidos por DM",
    ],
)
def test_what_is_not_a_phone_comes_back_byte_for_byte(text: str) -> None:
    assert mask_phones(text) == text


def test_masking_is_idempotent_and_hides_the_length() -> None:
    once = mask_phones("WhatsApp +57 300 123 4548 o 099 123 456")
    assert mask_phones(once) == once
    # the mask is the same length whatever the number's
    assert len(mask_phones("3001234567")) == len(mask_phones("099123456")) == len(M) + 2


def test_a_masked_text_keeps_no_more_than_the_last_two_digits() -> None:
    text = "Pedidos +57 300 123 4548, wa.me/573001234548 y 3 0 0 1 2 3 4 5 4 8"
    masked = mask_phones(text)
    digits = "".join(ch for ch in masked if ch.isdigit())
    assert digits == "5748574848"  # each code written and last pair, nothing else


def test_nested_values_are_masked_and_the_rest_is_kept() -> None:
    profile = {
        "bio": "Pide al 3001234567",
        "recentCaptions": ["wa.me/573001234567", "Nuevo sabor"],
        "links": ({"url": "https://wa.me/573001234567", "title": "WhatsApp"},),
        "followers": 12400,
        "fetchedAt": 1729.5,
        "isPrivate": False,
        "profilePicUrl": "https://scontent.cdninstagram.com/v/123456789_3001234567_n.jpg",
    }
    masked = mask_phones_in(profile)
    assert masked["bio"] == f"Pide al {M}67"
    assert masked["recentCaptions"] == [f"wa.me/+57 {M}67", "Nuevo sabor"]
    assert masked["links"] == ({"url": f"https://wa.me/+57 {M}67", "title": "WhatsApp"},)
    assert masked["followers"] == 12400 and masked["fetchedAt"] == 1729.5
    assert masked["isPrivate"] is False
    assert masked["profilePicUrl"] == profile["profilePicUrl"]  # a CDN link keeps working
    assert profile["bio"] == "Pide al 3001234567"  # the input is not modified


def test_whatsapp_numbers_are_the_full_digits_of_each_link() -> None:
    text = (
        "wa.me/573001234567 · https://api.whatsapp.com/send?phone=59899123456 · wa.me/573001234567"
    )
    assert whatsapp_numbers(text) == ["573001234567", "59899123456"]
    assert whatsapp_numbers("Pedidos por DM") == []


def test_identifiers_are_kept_and_an_untouched_value_is_the_same_object() -> None:
    key = (
        "t/c0000000-2345-4678-8000-3001234567b3/brand/b0000000-3001-4000-8000-0000000000b3"
        "/kept/profile/3001234567aa.png"
    )
    document = {
        "username": "3001234567",
        "pic_key": key,
        "recentPosts": [{"postId": "3001234567", "likes": 5}],
        "bio": "Helados",
    }
    assert mask_phones_in(document) is document
    assert mask_phones(key) == key  # a UUID's digit groups are not a phone either
    changed = mask_phones_in(dict(document, bio="Pide al 3001234567"))
    assert changed["username"] == "3001234567" and changed["pic_key"] == key
    assert changed["recentPosts"] is document["recentPosts"]
