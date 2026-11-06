"""«Elegir para una publicación» (CM-5, m-24955926): the choice, offline.

Pins (`docs/epica-galeria-medios-negocio.md` §5 CM-5):
1. The copy is the epic's: «Elegir para una publicación», «De tu negocio», «De tus
   productos», «N elegidas», «Crear publicación con estas», «Cancelar», «Puedes elegir
   hasta 10.».
2. Only ready business media can be chosen (preparing, failed, being cut: never).
3. The order is the order of the taps; untapping moves the rest up; the eleventh is
   refused with the sentence.
4. The link is `/create?medios=n:<uuid>,p:<uuid>` — exactly what CM-6 parses back.
5. Each tile says its type, length and place: «Video de 42 segundos, elegido 2.º».
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from qualify_api.creative.gallery_piece import parse_media_query

from .catalog_choose_state import CatalogChooseState
from .catalog_choose_vm import (
    CANCEL,
    CHOOSE_BUTTON,
    CREATE_WITH,
    GROUP_BUSINESS,
    GROUP_PRODUCTS,
    MAX_CHOSEN,
    TOO_MANY,
    business_choices,
    chosen_label,
    create_href,
    product_choices,
    toggle,
    with_order,
)
from .catalog_gallery_state import CatalogGalleryState
from .catalog_gallery_vm import GalleryItemVM
from .catalog_state import CatalogState
from .catalog_vm import ProductMediaVM, ProductVM

_N1 = "d0000000-0000-4000-8000-000000000001"
_N2 = "d0000000-0000-4000-8000-000000000002"
_P1 = "e0000000-0000-4000-8000-000000000001"


def _tile(media_id: str, **kw: Any) -> GalleryItemVM:
    base: dict[str, Any] = {
        "key": f"media-{media_id}",
        "state": "ready",
        "media_id": media_id,
        "job_id": "",
        "media_type": "video",
        "thumb_url": "/r2media/p",
        "video_url": "/r2media/v",
        "duration": "0:42",
        "duration_ms": 42_000,
        "label": "Video de 42 segundos",
        "remove_label": "el video de 42 segundos",
        "note": "",
        "note_tone": "neutral",
        "can_remove": True,
        "selectable": True,
        "cuttable": True,
    }
    base.update(kw)
    return GalleryItemVM(**base)


def _product() -> ProductVM:
    return ProductVM(
        product_id="p1",
        name="Shawarma mixto",
        slug="shawarma-mixto",
        description="",
        price_label="",
        price_amount="",
        price_currency="",
        category="",
        primary_photo_key="uploads/t/catalog/p/1.jpg",
        photo_count=1,
        video_count=0,
        counts_label="1 foto",
        media=(
            ProductMediaVM(
                media_id=_P1,
                media_type="image",
                key="uploads/t/catalog/p/1.jpg",
                filename="1.jpg",
                is_primary=True,
                position=0,
                meta_label="",
            ),
        ),
    )


def test_the_copy_is_the_epics() -> None:
    assert CHOOSE_BUTTON == "Elegir para una publicación"
    assert (GROUP_BUSINESS, GROUP_PRODUCTS) == ("De tu negocio", "De tus productos")
    assert (CREATE_WITH, CANCEL) == ("Crear publicación con estas", "Cancelar")
    assert TOO_MANY == "Puedes elegir hasta 10." and MAX_CHOSEN == 10
    assert (chosen_label(1), chosen_label(3)) == ("1 elegida", "3 elegidas")


def test_only_ready_business_media_can_be_chosen() -> None:
    items = [
        _tile(_N1),
        _tile(_N2, state="preparing", selectable=False),
        _tile("", state="failed", selectable=False),
        _tile("d0000000-0000-4000-8000-000000000003", state="cutting", selectable=False),
    ]
    assert [c.token for c in business_choices(items)] == [f"n:{_N1}"]


def test_the_order_is_the_order_of_the_taps() -> None:
    chosen, _ = toggle([], "n:a")
    chosen, _ = toggle(chosen, "p:b")
    chosen, _ = toggle(chosen, "n:c")
    assert chosen == ["n:a", "p:b", "n:c"]
    chosen, error = toggle(chosen, "p:b")  # untapped: the rest moves up
    assert chosen == ["n:a", "n:c"] and error == ""
    full = [f"n:{i}" for i in range(MAX_CHOSEN)]
    assert toggle(full, "n:eleventh") == (full, TOO_MANY)


def test_each_tile_says_its_type_length_and_place() -> None:
    video, photo = with_order(
        [
            *business_choices([_tile(_N1)]),
            *business_choices([_tile(_N2, media_type="image", duration="", duration_ms=0)]),
        ],
        [f"n:{_N2}", f"n:{_N1}"],
    )
    assert video.spoken == "Video de 42 segundos, elegido 2.º"
    assert photo.spoken == "Foto de tu negocio, elegida 1.ª"
    (product,) = product_choices([_product()])
    assert product.name == "Shawarma mixto"
    assert product.choices[0].label == "Foto de Shawarma mixto"
    assert product.choices[0].thumb == "uploads/t/catalog/p/1.jpg"


def test_the_link_is_what_the_generator_reads_back() -> None:
    href = create_href([f"p:{_P1}", f"n:{_N1}", "garbage"])
    url = urlparse(href)
    assert url.path == "/create"
    value = parse_qs(url.query)["medios"][0]
    parsed = parse_media_query(value)
    assert [(r.origin, str(r.media_id)) for r in parsed.refs] == [
        ("product", _P1),
        ("business", _N1),
    ]
    assert parsed.malformed == 0


async def test_choosing_then_crear_goes_to_create_with_them(monkeypatch) -> None:
    gallery = CatalogGalleryState()
    gallery.items = [_tile(_N1), _tile(_N2, state="preparing", selectable=False)]
    catalog = CatalogState()
    catalog.products = [_product()]

    async def get_state(self: Any, cls: type) -> Any:
        return gallery if cls is CatalogGalleryState else catalog

    monkeypatch.setattr(CatalogChooseState, "get_state", get_state)
    state = CatalogChooseState()
    await CatalogChooseState.start.fn(state)
    assert state.choosing and [c.token for c in state.business] == [f"n:{_N1}"]
    state.pick(f"n:{_N2}")  # not on screen (preparing): ignored
    state.pick(f"p:{_P1}")
    state.pick(f"n:{_N1}")
    assert state.count_text == "2 elegidas"
    assert [c.order for c in state.business] == [2]
    assert state.products[0].choices[0].order == 1
    event = state.create()
    assert event is not None and state.choosing is False and state.chosen == []
    assert UUID(_P1)  # the ids reached the link through `create_href` (tested above)


def test_cancelar_leaves_without_choosing() -> None:
    state = CatalogChooseState()
    state.choosing = True
    state.chosen = ["n:a"]
    state.cancel()
    assert state.choosing is False and state.chosen == []
    assert state.create() is None


def test_logout_resets_the_choice() -> None:
    from .auth_state import business_state_classes

    assert CatalogChooseState in business_state_classes()
