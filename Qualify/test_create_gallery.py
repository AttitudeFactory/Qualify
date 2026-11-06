"""«Crear» with what the owner chose in Galería (CM-7, m-24955928), offline.

Pins (`docs/epica-galeria-medios-negocio.md` §5 CM-7):
1. `?medios=` valid, of another business and malformed: the valid ones show in order,
   the rest are left out and the screen says «Una foto o video que elegiste ya no está
   en tu Galería; la dejamos fuera.».
2. «Usar el sonido de tus videos» only with a business video that has sound, OFF at
   first (D6), with «Apagado: tus videos van sin sonido.»; the voice sentence exists.
3. «Cambiar» goes back to Galería's choice with the same media; Galería reopens it.
4. The screen's base brief really becomes CM-6's carousel (or a Reel for one video).
5. «Crear publicación» makes one piece through `GalleryPieces.create` with a request key
   that holds for a double tap and is new after a piece is made; it opens in «Por
   aprobar»; CM-6's refusals read in Spanish.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from qualify_api.creative.gallery_media import GalleryMedium, GalleryRef
from qualify_api.creative.gallery_piece import (
    DROPPED_TEXT,
    GalleryPieces,
    NotEnoughMedia,
    gallery_brief,
    parse_media_query,
    resolve_selection,
)
from qualify_creative.schemas import ContentFormat, ContentKind
from reflex.istate.data import ReflexURL, RouterData

from . import create_gallery_provider as provider
from . import create_gallery_state as module
from .create_gallery_state import CreateGalleryState
from .create_gallery_vm import (
    SOUND_LABEL,
    SOUND_OFF,
    SOUND_ON,
    VOICE_TEXT,
    change_href,
    chosen_tiles,
    kind_label,
    sound_line,
)

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND = UUID("b0000000-0000-4000-8000-000000000001")
_USER = UUID("c0000000-0000-4000-8000-000000000001")
_N1 = UUID("d0000000-0000-4000-8000-000000000001")
_N2 = UUID("d0000000-0000-4000-8000-000000000002")
_P1 = UUID("e0000000-0000-4000-8000-000000000001")
_FOREIGN = UUID("f0000000-0000-4000-8000-000000000009")


def _medium(origin: str, media_id: UUID, kind: str = "image", **kw: Any) -> GalleryMedium:
    base: dict[str, Any] = {
        "origin": origin,
        "media_id": media_id,
        "media_type": kind,
        "object_key": f"gallery/{_TENANT}/{media_id}/"
        + ("video.mp4" if kind == "video" else "photo.jpg"),
        "poster_key": f"gallery/{_TENANT}/{media_id}/poster.jpg" if kind == "video" else None,
        "duration_ms": 42_000 if kind == "video" else None,
        "has_audio": kind == "video",
        "product_name": "Arepa de queso" if origin == "product" else "",
    }
    base.update(kw)
    return GalleryMedium(**base)


class _Reader:
    """This brand's live media; another business's id is simply absent (RLS)."""

    def __init__(self, *media: GalleryMedium) -> None:
        self.media = {m.ref: m for m in media}

    def resolve(self, *, tenant_id: UUID, brand_id: UUID, refs: Any) -> dict:
        return {r: self.media[r] for r in refs if r in self.media}


_VIDEO = _medium("business", _N1, "video")
_PHOTO = _medium("business", _N2)
_PRODUCT = _medium("product", _P1, object_key="uploads/t/catalog/p/1.jpg")


def test_valid_foreign_and_malformed_items() -> None:
    reader = _Reader(_VIDEO, _PHOTO, _PRODUCT)
    query = parse_media_query(f"n:{_N1},n:{_FOREIGN},garbage,p:{_P1},x:{_N2}")
    selection = resolve_selection(reader, tenant_id=_TENANT, brand_id=_BRAND, query=query)
    assert [m.media_id for m in selection.media] == [_N1, _P1]  # in the owner's order
    assert selection.dropped == 3 and selection.dropped_text == DROPPED_TEXT
    assert DROPPED_TEXT == (
        "Una foto o video que elegiste ya no está en tu Galería; la dejamos fuera."
    )


def test_the_tiles_say_order_whose_and_how_long() -> None:
    tiles = chosen_tiles([_VIDEO, _PRODUCT], lambda key, kind: f"/r2media/{kind}:{key}")
    assert [t.order for t in tiles] == [1, 2]
    assert tiles[0].thumb == f"/r2media/image:gallery/{_TENANT}/{_N1}/poster.jpg"
    assert tiles[0].duration == "0:42"
    assert tiles[0].label == "1.º: video de tu negocio, 42 segundos"
    assert tiles[1].thumb == "uploads/t/catalog/p/1.jpg"  # a product's key, as it is
    assert tiles[1].label == "2.ª: foto de Arepa de queso"


def test_the_format_is_named_as_the_owner_will_get_it() -> None:
    assert kind_label([_VIDEO, _PHOTO, _PRODUCT]) == "Carrusel de 3 fotos y videos"
    assert kind_label([_PHOTO, _PRODUCT]) == "Carrusel de 2 fotos"
    assert kind_label([_PHOTO]) == "Una foto"
    assert kind_label([_VIDEO]) == "Un video (Reel)"


def test_the_sound_switch_copy() -> None:
    assert SOUND_LABEL == "Usar el sonido de tus videos"
    assert sound_line(offered=True, on=False) == SOUND_OFF == "Apagado: tus videos van sin sonido."
    assert sound_line(offered=True, on=True) == SOUND_ON
    assert sound_line(offered=False, on=False) == ""
    assert (
        sound_line(offered=True, on=True, voiced=True)
        == VOICE_TEXT
        == ("Esta publicación lleva voz, así que tus videos van sin sonido.")
    )


def test_cambiar_goes_back_to_galeria_with_the_same_choice() -> None:
    assert change_href(f"n:{_N1},garbage,p:{_P1}") == (f"/catalog?elegir=1&medios=n:{_N1},p:{_P1}")
    assert change_href("") == "/catalog?elegir=1"


def test_the_screens_base_brief_becomes_cm6s_carousel(monkeypatch) -> None:
    """No DB: the brief `create_gallery_piece` sends really validates as the carousel —
    and as a Reel for one video."""
    sent: dict[str, Any] = {}

    class _Content:
        def create_draft(self, *, tenant_id, brand_id, brief, user_id, request_key):  # noqa: ANN001
            sent["brief"], sent["key"] = brief, request_key
            return UUID(int=77)

    pieces = GalleryPieces(content=_Content(), reader=_Reader(_VIDEO, _PHOTO, _PRODUCT))
    monkeypatch.setattr(provider, "_pieces", lambda: pieces)
    draft, dropped = provider.create_gallery_piece(
        _TENANT,
        _BRAND,
        _USER,
        medios=f"n:{_N1},p:{_P1},n:{_FOREIGN}",
        topic="",
        use_audio=True,
        request_key=UUID(int=5),
    )
    brief = sent["brief"]
    assert draft == UUID(int=77) and dropped == 1 and sent["key"] == UUID(int=5)
    assert brief.kind is ContentKind.CAROUSEL
    assert [s.gallery_media_id for s in brief.media.slides] == [_N1, _P1]
    assert brief.media.slides[0].audio is True  # a business video with sound, asked for
    assert brief.topic  # the owner wrote nothing: a topic is still there
    one = provider.create_gallery_piece(
        _TENANT,
        _BRAND,
        _USER,
        medios=f"n:{_N1}",
        topic="Así hacemos el pan",
        use_audio=False,
        request_key=UUID(int=6),
    )
    assert one[0] == UUID(int=77)
    assert sent["brief"].format is ContentFormat.REELS_9_16
    assert sent["brief"].topic == "Así hacemos el pan"


def test_nothing_usable_is_refused_by_cm6() -> None:
    selection = resolve_selection(
        _Reader(), tenant_id=_TENANT, brand_id=_BRAND, query=parse_media_query(f"n:{_FOREIGN}")
    )
    try:
        gallery_brief(None, selection)  # type: ignore[arg-type]
    except NotEnoughMedia as exc:
        assert "Elige al menos una foto o un video" in str(exc.args[0])
    else:
        raise AssertionError("an empty choice must be refused")


# -- the state ------------------------------------------------------------------------------


def _state(monkeypatch, medios: str) -> CreateGalleryState:
    async def ids(self: CreateGalleryState) -> tuple[UUID, UUID, UUID]:
        return (_TENANT, _BRAND, _USER)

    monkeypatch.setattr(CreateGalleryState, "_ids", ids)
    state = CreateGalleryState()
    state.router = RouterData(url=ReflexURL(f"http://localhost:3000/create?medios={medios}"))
    return state


def _choice(sound: bool = True) -> provider.GalleryChoice:
    tiles = chosen_tiles([_VIDEO, _PHOTO] if sound else [_PHOTO], lambda k, kind: "/r2media/x")
    return provider.GalleryChoice(
        tiles=tuple(tiles),
        kind="Carrusel de 2 fotos y videos",
        dropped=1,
        offers_sound=sound,
        single=not sound,
    )


async def test_the_screen_reads_the_choice_with_the_sound_off(monkeypatch) -> None:
    monkeypatch.setattr(module, "gallery_choice", lambda *_a: _choice())
    state = _state(monkeypatch, f"n:{_N1},n:{_N2}")
    assert state.active is True
    await CreateGalleryState.load.fn(state)
    assert len(state.tiles) == 2 and state.offers_sound
    assert state.use_audio is False and state.sound_text == SOUND_OFF  # D6
    assert state.dropped_text == DROPPED_TEXT
    assert state.change_link == f"/catalog?elegir=1&medios=n:{_N1},n:{_N2}"


async def test_no_sound_switch_without_a_business_video_with_sound(monkeypatch) -> None:
    monkeypatch.setattr(module, "gallery_choice", lambda *_a: _choice(sound=False))
    state = _state(monkeypatch, f"n:{_N2}")
    await CreateGalleryState.load.fn(state)
    state.set_use_audio(True)
    assert state.use_audio is False and state.sound_text == ""


async def test_crear_makes_one_piece_and_opens_it_in_por_aprobar(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_create(tenant_id, brand_id, user_id, **kw):  # noqa: ANN001
        calls.append(kw)
        return UUID(int=77), 0

    monkeypatch.setattr(module, "gallery_choice", lambda *_a: _choice())
    monkeypatch.setattr(module, "create_gallery_piece", fake_create)
    state = _state(monkeypatch, f"n:{_N1},n:{_N2}")
    await CreateGalleryState.load.fn(state)
    key = state._request_key
    state.set_use_audio(True)
    events = [e async for e in CreateGalleryState.create.fn(state)]
    assert len(events) == 2  # the toast and /drafts/<id>
    assert calls[0]["use_audio"] is True and calls[0]["request_key"] == UUID(key)
    assert calls[0]["medios"] == f"n:{_N1},n:{_N2}"
    assert state._request_key != key  # a later, deliberate «Crear» is a new piece
    state.creating = True  # a second tap while one is on its way: nothing
    assert [e async for e in CreateGalleryState.create.fn(state)] == []


async def test_cm6s_refusals_read_in_spanish(monkeypatch) -> None:
    def refuse(*_a, **_k):  # noqa: ANN002, ANN003
        raise NotEnoughMedia(0, 2)

    monkeypatch.setattr(module, "gallery_choice", lambda *_a: _choice())
    monkeypatch.setattr(module, "create_gallery_piece", refuse)
    state = _state(monkeypatch, f"n:{_N1}")
    await CreateGalleryState.load.fn(state)
    key = state._request_key
    assert [e async for e in CreateGalleryState.create.fn(state)] == []
    assert state.error.startswith("Elige al menos una foto o un video")
    assert state._request_key == key and state.creating is False  # a retry is the same


async def test_galeria_reopens_the_choice_from_cambiar(monkeypatch) -> None:
    """CM-5 side: `/catalog?elegir=1&medios=…` opens the choice with those media chosen,
    in order, keeping only what is still offered."""
    from . import catalog_choose_state as choose_module
    from .catalog_choose_state import CatalogChooseState
    from .catalog_gallery_provider import GallerySnapshot
    from .catalog_gallery_vm import GalleryItemVM

    tile = GalleryItemVM(
        key=f"media-{_N1}",
        state="ready",
        media_id=str(_N1),
        job_id="",
        media_type="video",
        thumb_url="",
        video_url="",
        duration="0:42",
        duration_ms=42_000,
        label="Video de 42 segundos",
        remove_label="",
        note="",
        note_tone="neutral",
        can_remove=True,
        selectable=True,
        cuttable=True,
    )

    class _Auth:
        session_tenant_id = str(_TENANT)

    async def get_state(self: Any, cls: type) -> Any:
        return _Auth()

    monkeypatch.setattr(CatalogChooseState, "get_state", get_state)
    monkeypatch.setattr(choose_module, "default_brand_id", lambda _t: _BRAND)
    monkeypatch.setattr(
        choose_module,
        "load_gallery",
        lambda *_a: GallerySnapshot(items=(tile,), waiting=0, busy=False),
    )
    monkeypatch.setattr(choose_module, "list_products", lambda *_a: ())
    query = {"elegir": "1", "medios": f"n:{_FOREIGN},n:{_N1}"}
    monkeypatch.setattr(CatalogChooseState, "_query", lambda self: dict(query))
    state = CatalogChooseState()
    events = state.sync_url()
    assert events == [CatalogChooseState.resume]
    await CatalogChooseState.resume.fn(state)
    assert state.choosing and state.chosen == [f"n:{_N1}"]  # the foreign one is not offered
    assert GalleryRef("business", _N1)  # (the token format is CM-6's, tested in CM-5)


def test_logout_resets_it() -> None:
    from .auth_state import business_state_classes

    assert CreateGalleryState in business_state_classes()
