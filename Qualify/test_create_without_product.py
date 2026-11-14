"""m-24985141: create without choosing a catalog product first; everything is chosen in
ONE media drawer («Tus productos · Tu Galería · Subir · Publicaciones · Inspiración»).

Pins:
1. The product is optional and chosen in «Tus productos»: a Clip takes the product's
   photo as a «Producto» reference; changing or removing the product takes the earlier
   one's photos out — and says so.
2. «Tu Galería»: the limits (9 photos, 3 videos, counting the grid; a slot of one file
   replaces), the category by the token tapped (`n:` «Lugar», `p:` «Producto»), the copy
   of a business medium made once per session, and a slot of another kind.
3. The drawer: the design system's `drawer`, one button in the Clip (the same in a video
   by parts), «Agregar» closes it, nothing in it talks about parts, the side panel's row.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import pytest

from . import gen_gallery_pick_provider as provider
from .creative_state import CreativeState
from .gen_gallery_pick_provider import GalleryPick, resolve_picks
from .gen_gallery_pick_vm import (
    NOTHING_ADDED,
    added_note,
    chosen_text,
    clip_role,
    origin_of_token,
    pick_limit,
    reference_name,
)

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND = UUID("b0000000-0000-4000-8000-000000000001")
_BIZ = UUID("e0000000-0000-4000-8000-000000000001")
_PROD = UUID("e0000000-0000-4000-8000-000000000002")


def _clip_with_catalog() -> CreativeState:
    state = CreativeState()
    state.gen_category, state.brief_kind = "clip", "clip"
    state.catalog_items = [
        {"id": "p1", "name": "Smash", "photo_key": "t/p1.jpg", "photo_keys": "t/p1.jpg"},
        {"id": "p2", "name": "Wrap", "photo_key": "t/p2.jpg", "photo_keys": "t/p2.jpg"},
    ]
    return state


# ---------------------------------------------------------------------------
# 1. the optional product, in «Tus productos»


def test_a_clip_takes_the_product_photo_and_a_change_says_what_went() -> None:
    state = _clip_with_catalog()
    state.pick_catalog_product("p1")
    assert state.brief_product_ref == "Smash"
    assert [(i["key"], i["source"], i["role"]) for i in state.clip_images] == [
        ("t/p1.jpg", "catalog", "product")
    ]
    state.pick_catalog_product("p2")  # another product: the earlier photo goes
    assert [i["key"] for i in state.clip_images] == ["t/p2.jpg"]
    assert state.product_change_note == "Quitamos de tus referencias las fotos de “Smash”."
    state.remove_catalog_product()
    assert state.clip_images == [] and state.brief_product_ref == ""


def test_without_a_product_the_clip_can_still_be_created() -> None:
    state = _clip_with_catalog()
    assert state._clip_problem() == ""
    assert not state.create_primary_disabled and state.create_reason == ""


def test_the_side_panel_row_opens_the_drawer_on_tus_productos() -> None:
    state = _clip_with_catalog()
    state.catalog_loaded = True
    state.change_product()
    assert state.media_drawer_open and state.media_drawer_target == "clip"
    assert state.clip_source_tab == "catalog"
    state.set_media_drawer_open(False)
    state.gen_category, state.brief_kind = "image", "static_flyer"
    state.change_product()
    assert state.media_drawer_target == "product"
    assert state.media_drawer_title == "Tus productos"


def test_a_replica_needs_a_photo_marked_producto() -> None:
    """Review #5: a place or a style is not what replaces the original's product."""
    state = CreativeState()
    state.gen_category, state.brief_kind = "clip", "clip"
    state.clip_videos = [{"key": "r.mp4", "name": "Reel", "source": "reel"}]
    state.clip_images = [{"key": "a.jpg", "name": "a", "source": "upload", "role": "place"}]
    assert "«Tus productos»" in state._clip_problem()
    state.set_clip_image_role("a.jpg", "product")
    assert state._clip_problem() == ""


# ---------------------------------------------------------------------------
# 2. «Tu Galería»


def test_the_galleria_categories_names_and_texts() -> None:
    assert origin_of_token(f"n:{_BIZ}") == "business"
    assert origin_of_token(f"p:{_PROD}") == "product" and origin_of_token("x:1") == ""
    assert clip_role("product") == "product" and clip_role("business") == "place"
    assert reference_name("product", "image", "Smash") == "Foto de Smash"
    assert reference_name("business", "video") == "Video de tu negocio"
    assert chosen_text(0) == "" and chosen_text(1) == "1 elegida"
    assert chosen_text(3) == "3 elegidas"
    assert added_note(2, 2) == "" and added_note(2, 0) == NOTHING_ADDED
    assert added_note(3, 2).startswith("Una de las que elegiste ya no está en tu Galería")
    assert added_note(4, 2).startswith("2 de las que elegiste ya no están")


def test_a_tap_stays_within_the_room() -> None:
    media = {"n:1": "image", "n:2": "image", "p:3": "video"}
    chosen, note = pick_limit([], media, "n:1", photo_room=1, video_room=0)
    assert chosen == ["n:1"] and note == ""
    chosen, note = pick_limit(chosen, media, "n:2", photo_room=1, video_room=1)
    assert chosen == ["n:1"]
    assert note.startswith("Ya llegaste a 9 fotos, el máximo del clip. Toca una de las elegidas")
    chosen, note = pick_limit(chosen, media, "n:1", photo_room=1, video_room=0)
    assert chosen == [] and note == ""
    # a slot of one file: the new tap replaces the earlier one
    chosen, note = pick_limit(["n:1"], media, "n:2", photo_room=1, video_room=0, clip=False)
    assert chosen == ["n:2"] and note == ""
    assert pick_limit([], media, "x:9", photo_room=9, video_room=3) == ([], "")


def test_a_business_photo_enters_as_lugar_and_a_products_as_producto() -> None:
    """QA 2026-11-12: a business photo entered as «Producto»."""
    state = CreativeState()
    state.gen_category, state.brief_kind = "clip", "clip"
    picks = [
        GalleryPick("t/x/uploads/gallery/a.jpg", "image", "Foto de tu negocio", "place", "n:1"),
        GalleryPick("t/x/uploads/catalog/b.jpg", "image", "Foto de Smash", "product", "p:2"),
        GalleryPick("t/x/uploads/gallery/c.mp4", "video", "Video de tu negocio", "", "n:3"),
    ]
    assert state.add_gallery_picks(picks) == 3
    assert [(i["key"], i["role"], i["source"]) for i in state.clip_images] == [
        ("t/x/uploads/gallery/a.jpg", "place", "gallery"),
        ("t/x/uploads/catalog/b.jpg", "product", "gallery"),
    ]
    assert [v["key"] for v in state.clip_videos] == ["t/x/uploads/gallery/c.mp4"]
    roles = {t["key"]: t["role"] for t in state.clip_reference_tiles if t["kind"] == "image"}
    assert roles["t/x/uploads/gallery/a.jpg"] == "place"
    # the same again is not added twice (and still counts as in)
    assert state.add_gallery_picks(picks[:1]) == 1 and len(state.clip_images) == 2


def test_a_slot_of_another_kind_takes_only_its_type() -> None:
    state = CreativeState()
    picks = [
        GalleryPick("t/x/uploads/gallery/a.jpg", "image", "Foto de tu negocio", "place", "n:1"),
        GalleryPick("t/x/uploads/gallery/c.mp4", "video", "Video de tu negocio", "", "n:3"),
    ]
    assert state.add_gallery_picks(picks, "background") == 1
    assert state.media_background_key == "t/x/uploads/gallery/a.jpg"
    assert state.add_gallery_picks(picks, "products") == 1
    assert "t/x/uploads/gallery/a.jpg" in state.media_product_keys
    assert state.gallery_room("reference") == (0, 1)


def test_no_room_left_adds_nothing() -> None:
    state = CreativeState()
    state.gen_category, state.brief_kind = "clip", "clip"
    state.clip_images = [
        {"key": f"t/x/{n}.jpg", "name": "x", "source": "upload", "role": "product"}
        for n in range(9)
    ]
    pick = GalleryPick("t/x/z.jpg", "image", "Foto", "place", "n:9")
    assert state.add_gallery_picks([pick]) == 0


class _Medium:
    def __init__(self, origin: str, media_id: UUID, media_type: str, key: str) -> None:
        self.origin, self.media_id, self.media_type = origin, media_id, media_type
        self.object_key, self.poster_key, self.duration_ms = key, None, None
        self.has_audio, self.product_name = False, "Smash" if origin == "product" else ""

    @property
    def is_video(self) -> bool:
        return self.media_type == "video"


def _fake_reader(monkeypatch: pytest.MonkeyPatch, *media: _Medium) -> None:
    from qualify_api.creative.gallery_media import GalleryRef

    class Reader:
        def resolve(self, *, tenant_id, brand_id, refs):  # noqa: ANN001, ANN201
            assert (tenant_id, brand_id) == (_TENANT, _BRAND)
            return {GalleryRef(m.origin, m.media_id): m for m in media}

    monkeypatch.setattr(provider, "DbGalleryMedia", Reader)


def test_resolve_copies_a_business_medium_once_and_keeps_the_product_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    business = _Medium("business", _BIZ, "image", f"gallery/{_TENANT}/{_BIZ}/foto.jpg")
    product = _Medium("product", _PROD, "image", f"t/{_TENANT}/uploads/catalog/p.jpg")
    _fake_reader(monkeypatch, business, product)
    source = tmp_path / "foto.jpg"
    source.write_bytes(b"jpeg")
    copied: list[tuple[str, bytes]] = []

    @contextmanager
    def fake_path(tenant_id: UUID, key: str) -> Iterator[Path]:
        assert tenant_id == _TENANT and key == business.object_key
        yield source

    def fake_save(tenant_id: UUID, fileobj, name: str, *, folder: str = "") -> str:  # noqa: ANN001
        copied.append((f"{folder}/{name}", fileobj.read()))
        return f"t/{tenant_id}/uploads/gallery/new_{name}"

    monkeypatch.setattr(provider, "upload_path", fake_path)
    monkeypatch.setattr(provider, "save_upload_file", fake_save)
    tokens = [f"n:{_BIZ}", f"p:{_PROD}", "x:bad"]
    picks = resolve_picks(_TENANT, _BRAND, tokens)
    new_key = f"t/{_TENANT}/uploads/gallery/new_foto.jpg"
    assert copied == [("gallery/foto.jpg", b"jpeg")]
    assert picks == [
        GalleryPick(new_key, "image", "Foto de tu negocio", "place", f"n:{_BIZ}"),
        GalleryPick(product.object_key, "image", "Foto de Smash", "product", f"p:{_PROD}"),
    ]
    # review #4: a second «Agregar» of the same medium reuses the copy
    again = resolve_picks(_TENANT, _BRAND, tokens[:1], {f"n:{_BIZ}": new_key})
    assert len(copied) == 1 and again[0].key == new_key


def test_a_medium_the_server_does_not_find_is_left_out(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_reader(monkeypatch)
    assert resolve_picks(_TENANT, _BRAND, [f"n:{_BIZ}"]) == []
    assert resolve_picks(_TENANT, _BRAND, []) == []


# ---------------------------------------------------------------------------
# 3. the drawer


def _has(rendered: str, text: str) -> bool:
    return text in rendered or json.dumps(text)[1:-1] in rendered


def test_one_drawer_with_the_sources_in_order_and_agregar_closes_it() -> None:
    from .content_generator import _clip_drawer_body, _clip_gallery, media_drawer

    gallery = str(_clip_gallery())
    assert _has(gallery, "Elegir fotos, videos o audios") and "open_media_drawer" in gallery
    assert "Elegir de tu Galer" not in gallery  # one way in, no second button
    body = str(_clip_drawer_body())
    labels = ["Tus productos", "Tu Galería", "Subir", "Publicaciones", "Inspiración"]
    positions = [body.find(json.dumps(label)[1:-1]) for label in labels]
    assert all(p >= 0 for p in positions) and positions == sorted(positions)
    assert "partes" not in body.lower() and "parte " not in body.lower()
    drawer = str(media_drawer())
    assert "q-drawer" in drawer and "finish" in drawer and "gen-gallery-count" in drawer
    assert "aria-describedby" in drawer and "44px" in drawer
    assert "partes" not in drawer.lower()


def test_the_product_section_and_the_separate_galleria_button_are_gone() -> None:
    from .content_generator import _product_chip, _step_say, _step_show

    assert "Elige un producto de tu cat" not in str(_step_show()) + str(_step_say())
    row = str(_product_chip())
    assert _has(row, "Elegir producto") and "change_product" in row and "44px" in row


def test_the_avatars_references_are_one_section_like_the_clip() -> None:
    """Round 13 (Deivid): «adaptar los avatars a lo que está en el clip» — one
    references section, one button; photos with «Producto/Fondo/Estilo» and its
    reference video, from one drawer."""
    from .content_generator import _images_section

    section = str(_images_section(video=True))
    assert "media-open-avatar_refs" in section and "ref_items" in section
    assert "reference_video_key" in section
    state = CreativeState()
    state.gen_category, state.brief_kind = "video", "avatar_video"
    state.open_media_drawer("avatar_refs", "", "media-open-avatar_refs")
    assert state.media_drawer_title == "Referencias"
    assert state.gallery_room("avatar_refs") == (10, 1)
    picks = [
        GalleryPick("t/x/uploads/gallery/a.jpg", "image", "Foto de tu negocio", "place", "n:1"),
        GalleryPick("t/x/uploads/gallery/c.mp4", "video", "Video de tu negocio", "", "n:3"),
    ]
    assert state.add_gallery_picks(picks, "avatar_refs") == 2
    assert state.media_background_key == "t/x/uploads/gallery/a.jpg"  # «Fondo»
    assert state.reference_video_key == "t/x/uploads/gallery/c.mp4"
    media = state._media_inputs()
    assert media["background_key"] == "t/x/uploads/gallery/a.jpg"
    assert media["reference_video_key"] == "t/x/uploads/gallery/c.mp4"


def test_a_parts_sheet_embeds_the_selector_in_line() -> None:
    """UI-4's part sheet is a drawer already: its selector goes in line (never a second
    drawer), and «Tu Galería» there carries its own «Agregar» for that slot."""
    from .content_generator import _part_media_editor

    sheet = str(_part_media_editor("image"))
    assert "finish" in sheet and "part_images" in sheet
    assert "open_media_drawer" not in sheet


# ---------------------------------------------------------------------------
# round 3 (review + Deivid, 2026-11-13)


def test_a_parts_sheet_never_changes_the_product() -> None:
    """Blocker: «Tus productos» in a part's sheet shows only the chosen product's files
    — choosing or removing THE product there would close the sheet and lose the draft."""
    from .content_generator import _part_media_editor

    for kind in ("image", "video"):
        sheet = str(_part_media_editor(kind))
        assert "pick_catalog_product" not in sheet and "remove_catalog_product" not in sheet
        assert _has(sheet, "Para cambiarlo, toca «Cambiar» en el panel.")
        assert _has(sheet, "Elige el producto de tu publicación en el panel, en «Producto».")


def test_with_parts_planned_a_product_change_asks_first() -> None:
    from .content_generator import _product_confirm_dialog
    from .test_parts_start import _with_plan

    state = _with_plan()
    assert state._parts_on_screen()
    before = state.selected_product_id
    state.pick_catalog_product("other")
    assert state.product_confirm == "other" and state.selected_product_id == before
    state.set_product_confirm_open(False)  # «Dejar como está»
    assert state.product_confirm == "" and state.selected_product_id == before
    state.pick_catalog_product("other")
    state.confirm_product_change()  # «Cambiar producto»
    assert state.selected_product_id == "other" and state.product_confirm == ""
    # a plan made without a reel is made again from the new product (m-24921079)
    assert state.reel_parts_count == 0
    dialog = str(_product_confirm_dialog())
    for text in (
        "¿Cambiar el producto?",
        "Las partes de tu video se borran y las vuelves a pedir con el producto nuevo.",
        "Cambiar producto",
        "¿Quitar el producto?",
        "Las partes de tu video se borran y las vuelves a pedir sin producto.",
        "Quitar producto",
        "Dejar como está",
    ):
        assert _has(dialog, text), text


def test_taking_the_product_out_with_parts_asks_with_its_own_words() -> None:
    from .test_parts_start import _with_plan

    state = _with_plan()
    before = state.selected_product_id
    state.remove_catalog_product()
    assert state.product_confirm_removes and state.selected_product_id == before
    state.confirm_product_change()  # «Quitar producto»
    assert state.selected_product_id == "" and not state.product_confirm_removes


def test_a_reels_plan_is_never_asked_about() -> None:
    """A reel's plan stays when the product changes: nothing to confirm."""
    from .test_reel_parts_state import planned

    state = planned()
    assert state.reel_plan_shown and not state._parts_on_screen()
    state.catalog_items = [{"id": "p9", "name": "Wrap", "photo_key": "", "photo_keys": ""}]
    count = state.reel_parts_count
    state.pick_catalog_product("p9")
    assert state.product_confirm == "" and state.selected_product_id == "p9"
    assert state.reel_parts_count == count


def test_choosing_a_product_brings_all_its_photos_and_videos() -> None:
    """Deivid: «sin importar cuantas imagenes tenga solo se carga 1 … debería traer toda
    la media de ese producto»."""
    state = CreativeState()
    state.gen_category, state.brief_kind = "clip", "clip"
    state.catalog_items = [
        {
            "id": "p1",
            "name": "Smash",
            "photo_key": "t/a.jpg",
            "photo_keys": "t/a.jpg\nt/b.jpg\nt/c.jpg",
            "video_keys": "t/v.mp4",
        }
    ]
    state.pick_catalog_product("p1")
    assert [(i["key"], i["role"]) for i in state.clip_images] == [
        ("t/a.jpg", "product"),
        ("t/b.jpg", "product"),
        ("t/c.jpg", "product"),
    ]
    assert [v["key"] for v in state.clip_videos] == ["t/v.mp4"]
    assert state.clip_first_frame_key == "t/a.jpg" and state.product_seed_note == ""
    state.remove_catalog_product()  # every file it brought goes with it
    assert state.clip_images == [] and state.clip_videos == []
    assert state.product_change_note == "Quitamos de tus referencias las fotos de “Smash”."


def test_a_product_with_more_than_the_clip_takes_says_what_did_not_fit() -> None:
    state = CreativeState()
    state.gen_category, state.brief_kind = "clip", "clip"
    photos = "\n".join(f"t/{n}.jpg" for n in range(12))
    videos = "\n".join(f"t/{n}.mp4" for n in range(4))
    state.catalog_items = [
        {
            "id": "p1",
            "name": "Smash",
            "photo_key": "t/0.jpg",
            "photo_keys": photos,
            "video_keys": videos,
        }
    ]
    state.pick_catalog_product("p1")
    assert len(state.clip_images) == 9 and len(state.clip_videos) == 3
    assert state.product_seed_note == (
        "Entraron 9 fotos de “Smash”; 3 no cupieron (máximo 9 por clip). "
        "Entraron 3 videos de “Smash”; 1 no cupo (máximo 3 por clip)."
    )


def test_the_drawer_texts_and_counts() -> None:
    from .gen_gallery_pick_vm import (
        add_label,
        product_removed_note,
        product_seed_note,
        slot_held_text,
        to_add_text,
    )
    from .reel_parts_vm import FORM_NEW_BRAND, form_label

    assert to_add_text(0) == "" and to_add_text(1) == "1 por agregar"
    assert to_add_text(3) == "3 por agregar"
    assert add_label(0) == "Listo" and add_label(2) == "Agregar 2"
    assert slot_held_text(0) == "Nada elegido aún" and slot_held_text(1) == "1 foto puesta"
    assert slot_held_text(4) == "4 fotos puestas"
    assert slot_held_text(1, video=True) == "Video elegido"
    assert product_removed_note("") == (
        "Quitamos de tus referencias las fotos de tu producto anterior."
    )
    assert product_seed_note("x", photos_in=2, photos_out=0, videos_in=0, videos_out=0) == ""
    assert form_label({"mode": "reference"}, has_product=False) == FORM_NEW_BRAND
    assert FORM_NEW_BRAND == "Nueva, con tu marca"
    lim = pick_limit(
        ["n:1"], {"n:1": "image", "n:2": "image"}, "n:2", photo_room=1, video_room=0, clip=True
    )
    assert lim[1].endswith(
        "Toca una de las elegidas para quitarla, o quita una de tus referencias."
    )
    many = pick_limit(
        ["n:1"], {"n:1": "image", "n:2": "image"}, "n:2", photo_room=1, video_room=0, clip=False
    )
    assert many == (["n:2"], "")  # one file: replaced
    full = pick_limit(
        ["n:1", "n:2"],
        {"n:1": "image", "n:2": "image", "n:3": "image"},
        "n:3",
        photo_room=2,
        video_room=0,
        clip=False,
    )
    assert full[1] == "No caben más fotos aquí. Toca una de las elegidas para quitarla."
    videos = pick_limit(
        ["p:1", "p:2"],
        {"p:1": "video", "p:2": "video", "p:3": "video"},
        "p:3",
        photo_room=0,
        video_room=2,
        clip=False,
    )
    assert videos[1] == "No caben más videos aquí. Toca uno de los elegidos para quitarlo."
    assert product_seed_note("X", photos_in=0, photos_out=4, videos_in=0, videos_out=1) == (
        "No cupieron las 4 fotos de “X” (máximo 9 por clip). "
        "No cupo el video de “X” (máximo 3 por clip)."
    )
    assert pick_limit([], {"p:9": "image"}, "p:9", photo_room=0, video_room=1, clip=False)[1] == (
        "Aquí no van fotos: elige un video."
    )


def test_closing_the_drawer_does_what_agregar_does() -> None:
    state = CreativeState()
    state.open_media_drawer("clip", "gallery", "media-open-clip")
    assert "finish" in str(state.set_media_drawer_open(False))
    state.product_change_note = "x"
    state.open_media_drawer("clip", "", "media-open-clip")  # reopened: the note goes
    assert state.product_change_note == ""


# ---------------------------------------------------------------------------
# round 5 (Deivid, 2026-11-13)


def test_the_sources_are_the_kits_segmented_menu_with_icons() -> None:
    """Round 7 (Deivid): the design system's segmented menu (`lq-segmented`) with an
    icon and a name; `.q-source-seg` is its width rule (CSS checked below)."""
    from .content_generator import (
        SOURCE_TAB_ICONS,
        SOURCE_TABS_CLASS,
        _clip_drawer_body,
        _part_media_editor,
    )

    for rendered in (str(_clip_drawer_body()), str(_part_media_editor("image"))):
        assert SOURCE_TABS_CLASS in rendered and "SegmentedControl" in rendered
        assert "q-source-seg__text" in rendered and "44px" in rendered
        assert "q-choice q-choice--on" not in rendered  # no Planificador chips
        for label in ("Tus productos", "Tu Galería", "Publicaciones"):
            assert _has(rendered, label), label
    assert SOURCE_TAB_ICONS["catalog"] == "package"
    css = (Path(__file__).resolve().parent.parent / "assets" / "qualify.css").read_text(
        encoding="utf-8"
    )
    rule = css[css.index(".rt-SegmentedControlRoot.q-source-seg") :]
    rule = rule[: rule.index("}")]
    assert "min-width: 0" in rule and "grid-auto-columns: auto" in rule
    assert "max-content" not in rule
    assert '[data-state="off"] .q-source-seg__text' in css
    assert ".q-avatar-stack .rt-AvatarRoot + .rt-AvatarRoot" in css


def test_the_product_row_counts_every_reference_in_its_bubbles() -> None:
    """Round 9 (Deivid): «tiene que funcionar el +n igual si le pongo imagenes de
    inspiraciones, videos, etc» — every reference held counts, up to 4 bubbles or 3 and
    «+N», read as «y N referencias más»."""
    from .content_generator import _product_chip

    row = str(_product_chip())
    assert "q-avatar-stack" in row and "Avatar" in row
    state = CreativeState()
    state.gen_category, state.brief_kind = "clip", "clip"
    state.clip_images = [
        {"key": "t/a.jpg", "name": "a", "source": "catalog", "role": "product"},
        {"key": "t/b.jpg", "name": "b", "source": "upload", "role": "product"},
        {"key": "t/stock/i.jpg", "name": "Insp", "source": "inspiration", "role": "style"},
        {"key": "t/c.jpg", "name": "c", "source": "gallery", "role": "place"},
    ]
    state.clip_videos = [{"key": "t/v.mp4", "name": "v", "source": "upload"}]
    state.clip_audios = [{"key": "t/s.mp3", "name": "s", "source": "upload"}]
    assert [i["key"] for i in state.product_row_thumbs] == ["t/a.jpg", "t/b.jpg", "t/stock/i.jpg"]
    assert state.product_row_more == 3
    assert state.product_row_more_label == "y 3 referencias más"
    state.clip_images, state.clip_audios = state.clip_images[:2], []
    assert [i["kind"] for i in state.product_row_thumbs] == ["image", "image", "video"]
    assert state.product_row_more == 0


def test_another_kind_counts_its_photos_background_and_video() -> None:
    state = CreativeState()
    state.gen_category, state.brief_kind = "image", "static_flyer"
    state.media_product_keys, state.media_product_names = ["t/p.jpg"], ["p"]
    state.media_background_key = "t/bg.jpg"
    state.reference_video_key = "t/ref.mp4"
    assert [(i["key"], i["kind"]) for i in state.product_row_thumbs] == [
        ("t/p.jpg", "image"),
        ("t/bg.jpg", "image"),
        ("t/ref.mp4", "video"),
    ]


def test_tus_productos_opens_first_without_a_product() -> None:
    state = CreativeState()
    state.clip_source_tab = "pieces"
    state.open_media_drawer("clip", "", "media-open-clip")
    assert state.clip_source_tab == "catalog"
    state.picker_tabs = {"products": "pieces"}
    state.open_media_drawer("products", "", "media-open-products")
    assert state.picker_tab_view["products"] == "catalog"
    state.open_media_drawer("background", "", "media-open-background")
    assert state.picker_tab_view["background"] == "gallery"  # not a product


def test_the_product_row_sits_right_above_the_options() -> None:
    """Round 9 (Deivid: «Justo encima de las opciones»): under «¿Qué creamos?» and the
    month's creations, above the kind picker."""
    from .content_generator import _options_panel

    panel = str(_options_panel())
    heading = panel.index(json.dumps("¿Qué creamos?")[1:-1])
    row = panel.index("change_product")
    assert heading < row < panel.index('id:"create-kind-options"')


def test_the_product_row_stays_on_one_line() -> None:
    """Round 9: the button never drops under the name on a desktop — the row does not
    wrap; the name takes two lines and its `title` carries it whole."""
    from .content_generator import PRODUCT_ROW_NAME_CLASS, _product_chip

    row = str(_product_chip())
    assert PRODUCT_ROW_NAME_CLASS in row and "flexWrap" not in row
    assert "title" in row
    assert _has(row, "Sin producto") and _has(row, "Elegir producto")
    css = (Path(__file__).resolve().parent.parent / "assets" / "qualify-creative.css").read_text(
        encoding="utf-8"
    )
    assert ".q-cr-product-row { flex-wrap: nowrap; }" in css
    rule = css[css.index(".q-cr-product-row-name {") :]
    assert "-webkit-line-clamp: 2" in rule[: rule.index("}")]


def test_nothing_in_the_product_row_overlaps() -> None:
    """Round 10 (QA, «mira como está en escritorio»): the button sat on the name in the
    desktop's ~250 px column. The name's block shrinks (`flex: 1 1 0`, `min-width: 0`),
    the bubbles and the button never do, no `min-width: 7rem`; a narrow row shows 1
    smaller bubble + «+N», one line with «…» and the button as its icon (44×44)."""
    from .content_generator import _product_chip

    row = str(_product_chip())
    assert "7rem" not in row
    assert '"1 1 0"' in row and "q-cr-product-row-text" in row
    assert "q-cr-product-btn-icon" in row and "q-cr-product-btn-text" in row
    assert "q-avatar-more--narrow" in row and "q-avatar-more--wide" in row
    css = (Path(__file__).resolve().parent.parent / "assets" / "qualify-creative.css").read_text(
        encoding="utf-8"
    )
    assert ".q-cr-product-chip { container-type: inline-size; }" in css
    assert ".q-cr-product-row > .q-avatar-stack,\n.q-cr-product-row > .q-cr-product-btn {" in css
    assert ".q-cr-product-row-name { min-width: 0;" in css
    narrow = css[css.index("@container (max-width: 300px)") :]
    narrow = narrow[: narrow.index("\n}\n")]
    for rule in (
        ".q-avatar-thumb:nth-child(n + 3) { display: none; }",
        "-webkit-line-clamp: 1",
        ".q-cr-product-btn-text { display: none; }",
        "width: 44px",
        "width: 24px",
    ):
        assert rule in narrow, rule


def test_the_narrow_plus_counts_what_it_hides() -> None:
    state = CreativeState()
    state.gen_category, state.brief_kind = "clip", "clip"
    state.clip_images = [
        {"key": f"t/{n}.jpg", "name": "x", "source": "upload", "role": "product"} for n in range(5)
    ]
    # round 13 (Deivid): a narrow row (≈ 214 px) keeps 2 bubbles, its «+N» counts 3
    assert state.product_row_more == 2 and state.product_row_more_narrow == 3
    assert state.product_row_more_narrow_label == "y 3 referencias más"
    assert state.product_row_total_label == "5 referencias elegidas"
    state.clip_images = state.clip_images[:2]
    assert state.product_row_more_narrow == 0


def test_a_video_bubble_shows_its_poster_or_a_play_mark() -> None:
    from .content_generator import _product_bubbles

    bubbles = str(_product_bubbles())
    assert "piece_views" in bubbles  # a video with a poster shows it
    assert "\\u25b6" in bubbles or "▶" in bubbles  # one without: the play mark
    state = CreativeState()
    state.gen_category, state.brief_kind = "clip", "clip"
    state.clip_videos = [{"key": "t/v.mp4", "name": "v", "source": "upload"}]
    assert state.product_row_thumbs == [{"key": "t/v.mp4", "kind": "video"}]
    state.stock_views = {"t/v.mp4": "/r2media/poster"}
    assert state.piece_views["t/v.mp4"] == "/r2media/poster"  # the poster the bubble shows


# ---------------------------------------------------------------------------
# round 11 (Deivid): Avatar and the advertising image keep ONE list with a category


def _flyer() -> CreativeState:
    state = CreativeState()
    state.gen_category, state.brief_kind = "image", "static_flyer"
    state.media_product_keys = ["t/a.jpg", "t/b.jpg", "t/c.jpg"]
    state.media_product_names = ["a", "b", "c"]
    return state


def test_each_category_goes_where_the_brief_takes_it() -> None:
    state = _flyer()
    state.set_ref_role("t/b.jpg", "style")
    state.set_ref_role("t/c.jpg", "place")
    assert state.media_background_key == "t/c.jpg"
    # QA round 11: a change of category never moves a photo
    assert [(i["key"], i["role"]) for i in state.ref_items] == [
        ("t/a.jpg", "product"),
        ("t/b.jpg", "style"),
        ("t/c.jpg", "place"),
    ]
    media = state._media_inputs()
    assert media["background_key"] == "t/c.jpg"
    assert media["product_keys"] == ["t/a.jpg", "t/b.jpg"]
    assert media["product_image_roles"] == ["product", "composition"]
    assert media["ad_mode"] == "both"
    from qualify_creative.schemas import MediaInputs

    MediaInputs.model_validate(media)  # the schema takes it


def test_only_one_photo_is_the_place_and_the_owner_is_told() -> None:
    state = _flyer()
    state.set_ref_role("t/a.jpg", "place")
    assert state.ref_role_note == ""
    state.set_ref_role("t/b.jpg", "place")
    assert state.media_background_key == "t/b.jpg"
    assert state.ref_roles["t/a.jpg"] == "style" and "t/a.jpg" in state.media_product_keys
    assert state.ref_role_note == "Ahora esta es la foto de fondo. La anterior quedó como Estilo."
    state.set_ref_role("t/b.jpg", "product")  # the place back among the photos
    assert state.media_background_key == "" and "t/b.jpg" in state.media_product_keys
    media = state._media_inputs()
    assert media["background_key"] is None and media["ad_mode"] == "product"


def test_ad_mode_follows_the_list() -> None:
    state = _flyer()
    assert state._ad_mode() == "product"
    for key in ("t/a.jpg", "t/b.jpg", "t/c.jpg"):
        state.remove_ref(key)
    assert state._ad_mode() == "scene"
    state.media_product_keys, state.media_product_names = ["t/x.jpg"], ["x"]
    state.set_ref_role("t/x.jpg", "place")
    assert state._ad_mode() == "background"


def test_the_default_category_follows_the_source() -> None:
    state = _flyer()
    state._gallery_files = {}
    picks = [
        GalleryPick("t/n1.jpg", "image", "Foto de tu negocio", "place", "n:1"),
        GalleryPick("t/n2.jpg", "image", "Foto de tu negocio", "place", "n:2"),
        GalleryPick("t/p1.jpg", "image", "Foto de Smash", "product", "p:1"),
    ]
    assert state.add_gallery_picks(picks, "products") == 3
    assert state.media_background_key == "t/n1.jpg"  # the first business photo: the place
    assert state.ref_roles["t/n2.jpg"] == "style"  # already a place: «Estilo»
    assert state.ref_roles["t/p1.jpg"] == "product"
    state._inspiration_files = {"t/stock/i.jpg": {"name": "Insp", "media": "image"}}
    state.pick_media("products", "inspiration", "t/stock/i.jpg")
    assert state.ref_roles["t/stock/i.jpg"] == "style"


def test_the_avatar_sends_its_roles_and_the_template_does_not_change() -> None:
    state = _flyer()
    state.gen_category, state.brief_kind = "video", "avatar_video"
    state.set_ref_role("t/b.jpg", "style")
    media = state._media_inputs()
    assert media["product_image_roles"] == ["product", "composition", "product"]
    state.gen_category, state.brief_kind = "image", "template"
    media = state._media_inputs()
    assert "product_image_roles" not in media
    assert media["background_key"] is None


def test_a_new_place_keeps_the_lists_order() -> None:
    """QA round 11: marking the second of three as «Lugar» does not move it."""
    state = _flyer()
    before = [i["key"] for i in state.ref_items]
    state.set_ref_role("t/b.jpg", "place")
    assert [i["key"] for i in state.ref_items] == before


def test_the_template_keeps_a_business_photo_as_its_photo() -> None:
    """Review: the category only applies where the kind keeps one — a template takes a
    business photo from the Galería as one of its photos, never as a background it
    would drop."""
    state = CreativeState()
    state.gen_category, state.brief_kind = "image", "template"
    pick = GalleryPick("t/x/uploads/gallery/a.jpg", "image", "Foto de tu negocio", "place", "n:1")
    assert state.add_gallery_picks([pick], "products") == 1
    assert state.media_background_key == ""
    assert "t/x/uploads/gallery/a.jpg" in state.media_product_keys
    assert "t/x/uploads/gallery/a.jpg" in state._media_inputs()["product_keys"]


def test_a_photo_without_a_category_reads_as_scene_plan_does() -> None:
    from .creative_state import _role_of

    assert _role_of("", "t/x/stock/pixabay/1/a.jpg") == "composition"
    assert _role_of("", "t/x/uploads/a.jpg") == "product"
    assert _role_of("style", "t/x/uploads/a.jpg") == "composition"
    assert _role_of("product", "t/x/stock/pixabay/1/a.jpg") == "product"


def test_what_an_avatar_drop_did_not_take_is_said() -> None:
    from .gen_gallery_pick_vm import ref_uploads_left_text

    assert ref_uploads_left_text(0, 0, 10) == ""
    assert ref_uploads_left_text(2, 0, 10) == (
        "No agregamos 2 fotos: ya tienes 10, el máximo. Quita una para cambiarla."
    )
    assert ref_uploads_left_text(0, 1, 10) == (
        "No agregamos 1 video: va un solo video de referencia; usamos el primero."
    )
    state = CreativeState()
    state.ref_files_rejected(
        [{"file": {"path": "enorme.mp4"}, "errors": [{"code": "file-too-large"}]}]
    )
    assert "enorme.mp4" in state.upload_error and "200 MB" in state.upload_error


# -- re-review (round 16) ---------------------------------------------------------------


def test_the_avatar_zone_takes_several_files_and_one_file_zones_do_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blocker: `max_files=0` made the avatar's zone single-file (react-dropzone then
    refused every drop of several as «too-many-files»)."""
    from . import content_generator as cg

    seen: list[dict] = []
    real = cg.dropzone

    def spy(*children, **kwargs):  # noqa: ANN002, ANN003, ANN202
        seen.append(kwargs)
        return real(*children, **kwargs)

    monkeypatch.setattr(cg, "dropzone", spy)

    def zone(upload_id: str) -> dict:
        return next(k for k in seen if k.get("upload_id") == upload_id)

    cg._slot_drawer_body("avatar_refs")
    assert zone("creative_avatar_refs")["multiple"] is True
    assert "on_drop_rejected" in zone("creative_avatar_refs")
    cg._slot_drawer_body("slide_reference")
    assert zone("creative_slide_reference")["multiple"] is False  # one file
    cg._clip_upload_tab()
    assert zone("clip_images")["multiple"] is True  # the Clip as it was


def test_the_avatar_zone_says_it_takes_photos_and_videos() -> None:
    state = CreativeState()
    state.ref_files_rejected([{"file": {"path": "doc.pdf"}, "errors": [{"code": "x"}]}])
    assert state.upload_error.endswith("aquí van fotos PNG, JPG o WEBP, o videos MP4 o MOV.")
