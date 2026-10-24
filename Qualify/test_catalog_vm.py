"""Pure tests for the catalog screen's view models (`catalog_vm`) — no Reflex, no DB.

Pins:
1. `counts_label` reads naturally in singular/plural and says «Falta la foto» at zero.
2. `build_product_vm` carries everything the card prints as plain strings/ints, with the
   primary photo first in `primary_photo_key` and media ordered by position. The screen
   no longer has a price (founder, 2026-10-19): the view model carries none.
3. The upload zone takes photos and phone videos.
4. m-24842974: the three steps of «Agregar producto» («Paso N de 3»), the currency by
   its name with the business's own as the start, and refused files in the owner's
   words (formats only there).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from qualify_api.catalog.service import MediaRecord, ProductRecord

from .catalog_vm import (
    MAIN_CURRENCIES,
    MEDIA_ACCEPT,
    MEDIA_NOT_ACCEPTED,
    MEDIA_TOO_BIG,
    MEDIA_TOO_MANY,
    MISSING_PHOTO,
    NEW_PRODUCT_STEPS,
    NO_CURRENCY,
    OTHER_CURRENCIES,
    build_product_vm,
    business_default_currency,
    counts_label,
    currency_choice,
    currency_from_choice,
    currency_name,
    media_meta_label,
    parse_price_input,
    rejection_message,
    step_counter,
    steps_done,
)

_PRODUCT_ID = UUID("d0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")


def _media(n: int, media_type: str = "image", **kw: object) -> MediaRecord:
    return MediaRecord(
        id=UUID(f"e0000000-0000-4000-8000-00000000000{n}"),
        media_type=media_type,
        object_key=f"uploads/t/catalog/p/{n}.{'mp4' if media_type == 'video' else 'jpg'}",
        filename=f"f{n}",
        content_type="video/mp4" if media_type == "video" else "image/jpeg",
        width=kw.get("width"),  # type: ignore[arg-type]
        height=kw.get("height"),  # type: ignore[arg-type]
        duration_sec=kw.get("duration_sec"),  # type: ignore[arg-type]
        bytes=None,
        is_primary=bool(kw.get("is_primary", False)),
        position=int(kw.get("position", n)),  # type: ignore[arg-type]
    )


def _product(**kw: object) -> ProductRecord:
    base: dict[str, object] = {
        "id": _PRODUCT_ID,
        "brand_id": _BRAND_ID,
        "name": "Shawarma mixto",
        "slug": "shawarma-mixto",
        "description": "Pollo y carne",
        "price_amount": Decimal("12.50"),
        "price_currency": "USD",
        "category": "shawarmas",
        "tags": (),
        "is_active": True,
        "position": 0,
        "media": (),
    }
    base.update(kw)
    return ProductRecord(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. counts and media meta


def test_counts_label_reads_naturally() -> None:
    assert counts_label(0, 0) == "Falta la foto"
    assert counts_label(1, 0) == "1 foto"
    assert counts_label(3, 0) == "3 fotos"
    assert counts_label(0, 1) == "1 video"
    assert counts_label(3, 2) == "3 fotos · 2 videos"


def test_media_meta_label() -> None:
    # A photo shows only «Foto»: pixel sizes are jargon to the owner (m-24842971).
    assert media_meta_label("image", 1080, 1350, None) == ""
    assert media_meta_label("video", 1080, 1920, 7.4) == "7 s"
    assert media_meta_label("image", None, None, None) == ""


# ---------------------------------------------------------------------------
# 2. the product card


def test_build_product_vm_carries_the_card_as_plain_values() -> None:
    # media arrive ordered by position, as `CatalogService` builds its records
    record = _product(
        media=(
            _media(1, position=0),
            _media(2, position=1),
            _media(3, "video", position=2, duration_sec=9.0),
        )
    )
    vm = build_product_vm(record)
    assert vm.product_id == str(_PRODUCT_ID)
    assert (vm.name, vm.slug, vm.category) == ("Shawarma mixto", "shawarma-mixto", "shawarmas")
    # the price is back as an OPTIONAL field (m-24803289): formatted for reading, raw
    # for the edit form, and the code as stored
    assert (vm.price_label, vm.price_amount, vm.price_currency) == ("$12.5", "12.5", "USD")
    assert (vm.photo_count, vm.video_count) == (2, 1)
    assert vm.counts_label == "2 fotos · 1 video"
    # no flagged primary → the first photo stands in
    assert vm.primary_photo_key == record.media[0].object_key
    assert [m.position for m in vm.media] == [0, 1, 2]
    assert [m.media_type for m in vm.media] == ["image", "image", "video"]
    assert vm.media[2].meta_label == "9 s"
    # every field is a plain value a Reflex var can carry
    for value in vm.__dict__.values():
        assert isinstance(value, str | int | tuple), value


def test_build_product_vm_without_price_or_photos() -> None:
    vm = build_product_vm(_product(price_amount=None, price_currency="", media=()))
    # a product with no price carries no price: the pieces then print none, never one
    # that was made up (requirement 8 of m-24803289)
    assert (vm.price_label, vm.price_amount, vm.price_currency) == ("", "", "")
    assert vm.primary_photo_key == ""
    assert vm.counts_label == MISSING_PHOTO


def test_the_flagged_primary_photo_wins_over_position() -> None:
    record = _product(media=(_media(1, position=0), _media(2, position=1, is_primary=True)))
    vm = build_product_vm(record)
    assert vm.primary_photo_key == record.media[1].object_key
    assert [m.is_primary for m in vm.media] == [False, True]


# ---------------------------------------------------------------------------
# 3. the upload zone


def test_the_upload_zone_takes_photos_and_phone_videos() -> None:
    assert "image/*" in MEDIA_ACCEPT
    assert ".mp4" in MEDIA_ACCEPT["video/mp4"]
    assert ".mov" in MEDIA_ACCEPT["video/quicktime"]


# ---------------------------------------------------------------------------
# The optional price (m-24803289)
#
# The whole point of the field is that a piece prints the catalog's price and never an
# invented one, so the parser is exact or it refuses: every ambiguous form below raises
# instead of guessing.


def test_an_empty_price_is_a_valid_answer() -> None:
    assert parse_price_input("") is None
    assert parse_price_input("   ") is None


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("89990", "89990.00"),
        ("89.990", "89990.00"),  # thousands, the LatAm way
        ("89,990", "89990.00"),
        ("1999,90", "1999.90"),  # decimals, comma
        ("1999.90", "1999.90"),  # decimals, point
        ("1.234,56", "1234.56"),  # mixed, point groups
        ("1,234.56", "1234.56"),  # mixed, comma groups
        ("$ 89990", "89990.00"),  # the symbol is noise, not data
        ("12", "12.00"),
    ],
)
def test_a_price_that_can_be_read_exactly_is_read_exactly(typed: str, expected: str) -> None:
    assert parse_price_input(typed) == Decimal(expected)


@pytest.mark.parametrize(
    "typed",
    [
        "1.234.56",  # two point separators: thousands or decimals? refused
        "abc",
        "12.3456",  # four decimals is not money this column holds
        "-5",
        "1 2 3,4,5",
        "99999999999999",  # past Numeric(12, 2)
    ],
)
def test_a_price_that_cannot_be_read_exactly_is_refused(typed: str) -> None:
    with pytest.raises(ValueError):
        parse_price_input(typed)


def test_zero_is_not_a_price() -> None:
    with pytest.raises(ValueError, match="mayor que cero"):
        parse_price_input("0")


def test_the_currency_select_never_invents_a_code() -> None:
    assert currency_choice("") == NO_CURRENCY
    assert currency_choice("CLP") == "CLP"
    assert currency_from_choice(NO_CURRENCY) == ""
    assert currency_from_choice("CLP") == "CLP"
    assert currency_from_choice("clp") == "CLP"
    # anything that is not one of the offered codes stores no currency at all
    assert currency_from_choice("inventada") == ""
    assert currency_from_choice("") == ""


# ---------------------------------------------------------------------------
# 4. «Agregar producto» in three steps (m-24842974)


def test_the_steps_read_paso_n_de_3_with_the_photo_first() -> None:
    assert NEW_PRODUCT_STEPS[0] == "La foto" and len(NEW_PRODUCT_STEPS) == 3
    assert [step_counter(i) for i in range(3)] == ["Paso 1 de 3", "Paso 2 de 3", "Paso 3 de 3"]
    assert step_counter(-4) == "Paso 1 de 3" and step_counter(9) == "Paso 3 de 3"
    assert steps_done(0) == [False, False, False]
    assert steps_done(2) == [True, True, False]


def test_a_currency_reads_by_its_name() -> None:
    assert [code for code, _ in MAIN_CURRENCIES] == ["COP", "VES", "USD", "UYU"]
    assert currency_name("COP") == "Pesos colombianos (COP)"
    assert currency_name("ves") == "Bolívares (VES)"
    assert currency_name("USD") == "Dólares (USD)"
    assert currency_name("UYU") == "Pesos uruguayos (UYU)"
    assert currency_name("") == NO_CURRENCY
    # every code the select offers has a name; none hides behind its sigla alone
    for code, name in MAIN_CURRENCIES + OTHER_CURRENCIES:
        assert name != code and f"({code})" in name
        assert currency_from_choice(code) == code


def test_the_business_currency_is_the_starting_choice_when_the_catalog_offers_it() -> None:
    assert business_default_currency("COP") == "COP"
    assert business_default_currency(" uyu ") == "UYU"
    assert business_default_currency("BRL") == ""
    assert business_default_currency(None) == ""


def test_refused_files_are_explained_in_the_owners_words() -> None:
    wrong = [{"file": {}, "errors": [{"code": "file-invalid-type", "message": "x"}]}]
    assert rejection_message(wrong) == MEDIA_NOT_ACCEPTED
    assert MEDIA_NOT_ACCEPTED == (
        "Ese archivo no es una foto ni un video. Prueba con otra foto de tu galería."
    )
    assert rejection_message([{"errors": [{"code": "too-many-files"}]}]) == MEDIA_TOO_MANY
    assert rejection_message([{"errors": [{"code": "file-too-large"}]}]) == MEDIA_TOO_BIG
    assert rejection_message([]) == MEDIA_NOT_ACCEPTED
    assert rejection_message(["garbage"]) == MEDIA_NOT_ACCEPTED


# ---------------------------------------------------------------------------
# m-24842976: what counts as an unsaved change, and the leave dialog's words


def _vm(**kw: object) -> object:
    from .catalog_vm import ProductVM

    base: dict[str, object] = {
        "product_id": "p1",
        "name": "Shawarma mixto",
        "slug": "shawarma-mixto",
        "description": "Pollo y carne",
        "price_label": "$12.5",
        "price_amount": "12.5",
        "price_currency": "USD",
        "category": "shawarmas",
        "primary_photo_key": "",
        "photo_count": 0,
        "video_count": 0,
        "counts_label": "Falta la foto",
    }
    base.update(kw)
    return ProductVM(**base)  # type: ignore[arg-type]


def _fields(**kw: str) -> dict[str, str]:
    base = {
        "name": "Shawarma mixto",
        "description": "Pollo y carne",
        "category": "shawarmas",
        "price": "12.5",
        "currency": "USD",
    }
    base.update(kw)
    return base


def test_the_editor_is_clean_when_it_shows_what_is_stored() -> None:
    from .catalog_vm import editor_is_dirty

    product = _vm()
    assert not editor_is_dirty(product, **_fields())  # type: ignore[arg-type]
    # ends trimmed by the save, and the same price written another way
    assert not editor_is_dirty(product, **_fields(name=" Shawarma mixto ", price="12,50"))  # type: ignore[arg-type]
    assert not editor_is_dirty(None, **_fields(name="x"))


@pytest.mark.parametrize(
    "change",
    [
        {"name": "Shawarma XL"},
        {"description": ""},
        {"category": "combos"},
        {"price": "13"},
        {"price": ""},
        {"price": "12,"},  # half-typed: still a change
        {"currency": "COP"},
    ],
)
def test_any_edited_field_is_a_change(change: dict[str, str]) -> None:
    from .catalog_vm import editor_is_dirty

    assert editor_is_dirty(_vm(), **_fields(**change))  # type: ignore[arg-type]


def test_the_leave_dialog_and_the_card_name_the_product() -> None:
    from .catalog_vm import (
        LEAVE_SAVE,
        LEAVE_STAY,
        LEAVE_TITLE,
        PRODUCT_QUERY,
        leave_description,
    )

    assert LEAVE_TITLE == "¿Salir sin guardar?"
    assert (LEAVE_STAY, LEAVE_SAVE) == ("Volver", "Guardar y salir")
    assert leave_description(" Helado ") == "Los cambios de «Helado» se van a perder."
    assert PRODUCT_QUERY == "producto"


# -- m-24842977 ------------------------------------------------------------------------


def test_product_count_label_says_how_many_lack_a_photo() -> None:
    from .catalog_vm import product_count_label

    assert product_count_label(1, 0) == "1 producto"
    assert product_count_label(3, 0) == "3 productos"
    assert product_count_label(3, 1) == "3 productos · 1 sin foto"
    assert product_count_label(5, 2) == "5 productos · 2 sin foto"


def test_missing_photo_filter_label() -> None:
    from .catalog_vm import missing_photo_filter_label

    assert missing_photo_filter_label(1, active=False) == "Ver el que no tiene foto"
    assert missing_photo_filter_label(2, active=False) == "Ver los 2 sin foto"
    assert missing_photo_filter_label(2, active=True) == "Ver todos los productos"


def test_remove_media_words() -> None:
    from .catalog_vm import remove_media_description, remove_media_title

    assert remove_media_title("image") == "¿Quitar esta foto?"
    assert remove_media_title("video") == "¿Quitar este video?"
    plain = remove_media_description("image", is_primary=False)
    assert plain.startswith("Esta foto ya no se usará") and "principal" not in plain
    with_other = remove_media_description("image", is_primary=True, has_other_photo=True)
    assert with_other.endswith("La siguiente foto pasa a ser la principal.")
    only = remove_media_description("image", is_primary=True, has_other_photo=False)
    assert only.endswith("Tu producto quedará sin foto hasta que subas otra.")
    assert "Si tienes" not in with_other + only
    video = remove_media_description("video", is_primary=False)
    assert video.startswith("Este video") and "principal" not in video


def test_no_photo_label_carries_pixel_sizes() -> None:
    for w, h in ((1080, 1350), (320, 240), (None, None)):
        assert "×" not in media_meta_label("image", w, h, None)
        assert "px" not in media_meta_label("image", w, h, None)
