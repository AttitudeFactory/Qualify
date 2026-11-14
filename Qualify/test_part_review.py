"""UI-8 (m-24921083) «Revisar y rehacer una parte», offline.

The backend (`qualify_api.creative.part_review`) is replaced on the provider by a
stand-in with its final signatures and its real refusal (`PartNotReviewable` and its
`NOT_REVIEWABLE_TEXTS`); no database, no vendor.

Pins:
1. VM: the panel's words — the form read only, the versions oldest first with «Versión
   n de m», «Se hizo con: «…»», an expired one's reason, the version the tile plays, or
   why there is none, the photos the part may use, what another version uses.
2. The status line: «creadas», and how many parts the owner likes.
3. Provider: `change_part` sends the WHOLE edited description and the chosen photos
   (the bug of #610: a note replaced the description); `part_review_provider` passes
   through to the backend, signs the media and words a refusal as `NotReviewable`.
4. State: choosing a part reads its panel once and fills the fields; «Ver la anterior»
   refills them; «Crear otra versión» waits with a reason; «Usar esta versión»; «Me gusta
   así» answers at once and goes back on a refusal.
5. View: «Me gusta así» above «Cambiar esta», `aria-pressed`, the panel's region and its
   videos' names; no «Aprobar» in a part.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.creative import part_review
from qualify_api.creative.part_progress import PartProgress, PartProgressRow, PartState
from qualify_api.creative.parts import PartChanges

from . import final_video_card_provider as card_provider
from . import final_video_card_state as card_module
from . import part_progress_state as progress_module
from . import part_review_provider as review_provider
from . import part_review_vm as vm
from .final_video_card_state import FinalVideoState, PartVersionView, PhotoChoiceView
from .part_progress_state import PartProgressState
from .part_progress_vm import part_progress_vm, status_line

TENANT = UUID("a0000000-0000-4000-8000-0000000000a1")
USER = UUID("d0000000-0000-4000-8000-0000000000d1")
PARENT = UUID("e0000000-0000-4000-8000-0000000000e1")
V1 = UUID("f0000000-0000-4000-8000-0000000000f1")
V2 = UUID("f0000000-0000-4000-8000-0000000000f2")


# -- helpers -------------------------------------------------------------------------------


def _row(index: int, state: PartState, *, liked: bool = False, total: int = 4) -> PartProgressRow:
    return PartProgressRow(
        index=index,
        total=total,
        draft_id=UUID(int=index),
        mode="reference",
        seconds=4,
        state=state,
        liked=liked,
    )


def _progress(*rows: PartProgressRow) -> PartProgress:
    return PartProgress(parent_id=PARENT, parts=tuple(rows))


def _version(ordinal: int, *, current: bool = False, **kw: Any) -> vm.VersionRead:
    base: dict[str, Any] = {
        "version_id": str(V1 if ordinal == 1 else V2),
        "ordinal": ordinal,
        "total": 2,
        "current": current,
        "description": f"Descripción {ordinal}",
        "photo_keys": (f"t/x/p{ordinal}.jpg",),
        "seconds": 4.2,
    }
    base.update(kw)
    return vm.VersionRead(**base)


def _review(**kw: Any) -> vm.PartReview:
    base: dict[str, Any] = {
        "mode": "reference",
        "description": "Un chico muerde la hamburguesa y sonríe a cámara.",
        "photo_keys": ("t/x/p2.jpg", "t/x/p3.jpg"),
        "versions": (_version(1), _version(2, current=True)),
        "photos": (vm.PhotoRead("t/x/p3.jpg", "/r2media/p3"),),
        "from_reel": True,
        "quote": (0, 5, 10, "1 de diciembre", 1, 9, 20),
    }
    base.update(kw)
    return vm.PartReview(**base)


# -- 1. view model -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "from_reel", "label", "help_text"),
    [
        ("edit", True, "Igual al original, con tu producto", vm.EDIT_HELP),
        ("extend", True, "Sigue a la anterior", vm.EXTEND_HELP),
        ("reference", True, "Nueva, inspirada en el original", vm.REFERENCE_HELP),
        ("reference", False, "Nueva, con tu producto", vm.NEW_HELP),
    ],
)
def test_how_it_is_made_reads_as_step_two_says_it(
    mode: str, from_reel: bool, label: str, help_text: str
) -> None:
    assert vm.mode_words(mode, from_reel) == (label, help_text)


def test_what_another_version_uses() -> None:
    assert vm.change_use_text(None) == (vm.CHANGE_NOTE, False)
    assert vm.change_use_text((0, 0, 0, "", 1, 0, 0)) == (vm.CHANGE_NOTE, False)  # no quota
    text, out = vm.change_use_text((0, 5, 10, "1 de diciembre", 1, 9, 20))
    assert (text, out) == ("Usa 1 vista previa. Te quedan 9.", False)
    text, out = vm.change_use_text((0, 5, 10, "1 de diciembre", 1, 0, 20))
    assert out and text == "Este mes no te quedan vistas previas. Vuelven el 1 de diciembre."
    assert vm.change_use_text((0, 5, 10, "", 1, 0, 20))[0].endswith("el próximo mes.")


def test_the_ticket_words_and_ui4s_are_the_source() -> None:
    from . import part_editor_vm as ui4

    assert vm.CHANGE_USE_TEXT == "Usa 1 vista previa. Te quedan {p}."
    assert vm.change_use_text((3, 5, 10, "1 de diciembre", 2, 1, 20))[0] == (
        "Usa 1 vista previa. Te quedan 1."
    )
    for name in ("QUESTION", "DESCRIPTION_LABEL", "DESCRIPTION_EXAMPLE", "EDIT_HELP"):
        assert getattr(vm, name) is getattr(ui4, name), name


def test_versions_oldest_first_with_their_words() -> None:
    rows = vm.version_rows([_version(2, current=True), _version(1, expired=True)], 2)
    assert [r["ordinal"] for r in rows] == [1, 2]
    assert [r["label"] for r in rows] == ["Versión 1 de 2", "Versión 2 de 2"]
    assert rows[0]["made_with"] == "Se hizo con: «Descripción 1»"
    assert rows[0]["use_reason"] == "Esta versión venció. Crea otra versión."
    assert rows[1]["use_reason"] == ""


def test_the_panel_starts_on_the_current_version_with_its_fields() -> None:
    view = vm.review_view(_review(), 2)
    assert view.at == 1 and view.versions[1]["current"]
    assert view.description.startswith("Un chico muerde")
    assert view.selected == ["t/x/p2.jpg", "t/x/p3.jpg"]
    # the photos it may use: the given ones, then any a version or the part used
    assert [p["key"] for p in view.photos] == ["t/x/p3.jpg", "t/x/p1.jpg", "t/x/p2.jpg"]
    assert view.photos[0] == {
        "key": "t/x/p3.jpg",
        "url": "/r2media/p3",
        "label": "Foto 1 de tu producto",
    }
    assert view.use_text == "Usa 1 vista previa. Te quedan 9." and not view.out_of_previews


def test_the_inspiration_card_opens_https_only() -> None:
    assert vm.INSPIRATION_TITLE == "Video de inspiración"
    assert vm.INSPIRATION_BUTTON == "Ir al video ↗"
    assert vm.inspiration_href(" https://www.tiktok.com/@a/video/1 ") == (
        "https://www.tiktok.com/@a/video/1"
    )
    for unsafe in ("http://x/reel", "javascript:alert(1)", " JavaScript:void(0)", "", None):
        assert vm.inspiration_href(unsafe) == "", unsafe


def test_the_account_is_stored_or_named_by_the_page() -> None:
    page = "https://www.tiktok.com/@thegoldenbalance/video/7705422594442284301"
    assert vm.account_text("thegoldenbalance") == "@thegoldenbalance"
    assert vm.account_text("@cuenta", page) == "@cuenta"  # the stored one first
    assert vm.account_text("", page) == "@thegoldenbalance"
    assert vm.account_text("", "https://www.instagram.com/reel/abc/") == ""


def test_a_repeated_description_keeps_its_line_breaks() -> None:
    """Review of UI-8: repeated sentences go, the text is never flattened — and a text
    with nothing repeated comes back exactly as it was (no rewrite of the brief)."""
    plain = "Una mano acerca el vaso.\n\nEl vaso   brilla. Fin."
    assert vm.unique_text(plain) is plain
    lines = "Filetes sobre rejilla. Luego harina.\nFiletes sobre rejilla.\nSe sirve."
    assert vm.unique_text(lines) == "Filetes sobre rejilla. Luego harina.\nSe sirve."
    mixed = "Uno. Dos.\nTres. dos"
    assert vm.unique_text(mixed) == "Uno. Dos.\nTres."


def test_a_repeated_description_is_shown_once() -> None:
    """Live test 2026-11-13: part 2's brief reads its sentence twice (two cuts of the
    reel with the same description, joined by the plan); the field shows it once."""
    once = "Filetes de pescado sobre rejilla; luego harina."
    twice = f"{once} {once}"
    assert vm.unique_text(twice) == "Filetes de pescado sobre rejilla; luego harina."
    mixed = twice + " Una persona añade especias."
    assert vm.unique_text(mixed) == (
        "Filetes de pescado sobre rejilla; luego harina. Una persona añade especias."
    )
    view = vm.review_view(
        _review(description=twice, versions=(_version(1, current=True, description=twice),)), 2
    )
    assert view.description == "Filetes de pescado sobre rejilla; luego harina."
    assert (
        view.versions[0]["made_with"]
        == "Se hizo con: «Filetes de pescado sobre rejilla; luego harina.»"
    )


# -- 2. the status line ----------------------------------------------------------------------


def test_the_status_line_says_created_and_counts_the_likes() -> None:
    to_review = [_row(i, PartState.TO_REVIEW) for i in range(1, 5)]
    assert status_line(_progress(*to_review)) == "Tus 4 partes están creadas"
    some = [_row(1, PartState.READY, liked=True), _row(2, PartState.READY, liked=True)]
    some += [_row(3, PartState.TO_REVIEW), _row(4, PartState.TO_REVIEW)]
    assert status_line(_progress(*some)) == "Tus 4 partes están creadas. Te gustan 2 de 4."
    every = [_row(i, PartState.READY, liked=True) for i in range(1, 5)]
    assert status_line(_progress(*every)) == (
        "Te gustan tus 4 partes. Cuando quieras, aprueba tu video."
    )
    assert status_line(_progress(_row(1, PartState.TO_REVIEW, total=1))) == "Tu parte está creada"
    one = [_row(1, PartState.READY, liked=True), _row(2, PartState.TO_REVIEW, total=4)]
    one += [_row(3, PartState.TO_REVIEW), _row(4, PartState.TO_REVIEW)]
    assert status_line(_progress(*one)) == "Tus 4 partes están creadas. Te gusta 1 de 4."
    making = [_row(1, PartState.TO_REVIEW, total=2), _row(2, PartState.CREATING, total=2)]
    assert status_line(_progress(*making)) == "Creando tus partes: van 1 de 2"
    # an approved part is READY too, but not a «me gusta»
    approved = [_row(1, PartState.READY), _row(2, PartState.TO_REVIEW)]
    assert status_line(_progress(*approved)) == "Tus 2 partes están creadas"


def test_the_rows_carry_the_mark() -> None:
    data = part_progress_vm(
        _progress(_row(1, PartState.READY, liked=True), _row(2, PartState.READY))
    )
    assert [r.liked for r in data.rows] == [True, False]


# -- 3. providers ----------------------------------------------------------------------------


def test_change_part_sends_the_whole_description_and_the_photos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug of #610: «que se vea más de cerca» was sent as the description and
    REPLACED it. Now the field holds the part's own description, edited."""
    seen: list[PartChanges] = []

    class Parts:
        def __init__(self, _service: object) -> None: ...

        def regenerate_part(self, **kw: Any) -> UUID:
            seen.append(kw["changes"])
            return UUID(int=9)

    monkeypatch.setattr(card_provider, "PartsService", Parts)
    monkeypatch.setattr(card_provider, "production_content_service", lambda: None)
    text = "  Un chico muerde la hamburguesa de cerca.  "
    photos = ["t/x/p1.jpg", "", "t/x/p1.jpg", "t/x/p2.jpg"]
    card_provider.change_part(TENANT, PARENT, 2, text, USER, photos)
    card_provider.change_part(TENANT, PARENT, 2, "", USER)
    assert seen[0] == PartChanges(
        description="Un chico muerde la hamburguesa de cerca.",
        photo_keys=("t/x/p1.jpg", "t/x/p2.jpg"),
    )
    assert seen[1] == PartChanges(description=None, photo_keys=None)  # keeps what it had


class FakeReview:
    """`qualify_api.creative.part_review` with its final signatures (2026-11-12): the
    real refusal and its texts, the calls recorded."""

    PartNotReviewable = part_review.PartNotReviewable
    NOT_REVIEWABLE_TEXTS = part_review.NOT_REVIEWABLE_TEXTS

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.refuse = ""

    def set_part_liked(self, **kw: Any) -> bool:
        self.calls.append(("like", kw))
        if self.refuse:
            raise self.PartNotReviewable(self.refuse)
        return True

    def use_part_version(self, **kw: Any) -> None:
        self.calls.append(("use", kw))
        if self.refuse:
            raise self.PartNotReviewable(self.refuse)

    def part_edit_fields(self, **kw: Any) -> SimpleNamespace:
        self.calls.append(("fields", kw))
        return SimpleNamespace(
            mode="edit",
            description="Un chico toma la hamburguesa.",
            photo_keys=("t/x/p1.jpg",),
            analysis_id=uuid4(),
            shot_indexes=(2, 3),
        )

    def part_versions(self, **kw: Any) -> tuple[SimpleNamespace, ...]:
        self.calls.append(("versions", kw))
        return (
            SimpleNamespace(
                version_id=V1,
                ordinal=1,
                total=1,
                current=True,
                description="Un chico toma la hamburguesa.",
                photo_keys=("t/x/p1.jpg", "t/x/p9.jpg"),
                mode="edit",
                video_key="t/x/v1.mp4",
                poster_key="t/x/v1.jpg",
                seconds=4.0,
                liked=False,
                expired=False,
            ),
        )


@pytest.fixture
def fake_review(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeReview]:
    fake = FakeReview()
    monkeypatch.setattr(review_provider, "part_review", fake)
    yield fake


def test_the_like_and_the_version_go_to_the_backend(fake_review: FakeReview) -> None:
    assert review_provider.set_liked(TENANT, PARENT, 2, True) is True
    review_provider.use_version(TENANT, PARENT, 2, V1, USER)
    assert fake_review.calls[0] == (
        "like",
        {"tenant_id": TENANT, "parent_id": PARENT, "part_index": 2, "liked": True},
    )
    assert fake_review.calls[1][1]["version_id"] == V1
    fake_review.refuse = "no_video"
    with pytest.raises(review_provider.NotReviewable) as liked:
        review_provider.set_liked(TENANT, PARENT, 2, False)
    # the backend's own words reach the owner
    assert liked.value.text == part_review.NOT_REVIEWABLE_TEXTS["no_video"]
    fake_review.refuse = "unknown_version"
    with pytest.raises(review_provider.NotReviewable) as used:
        review_provider.use_version(TENANT, PARENT, 2, V1, USER)
    assert card_module.refusal_text(used.value, card_module.USE) == (
        "Esa versión de la parte ya no está disponible."
    )
    assert card_module.refusal_text(review_provider.NotReviewable(), card_module.USE) == (
        card_module.USE_REFUSED_TEXT
    )


def test_read_review_signs_the_photos_and_each_versions_preview(
    fake_review: FakeReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_provider, "is_r2_key", lambda key: key.startswith("t/"))
    monkeypatch.setattr(
        review_provider, "issue_view_path", lambda tenant, key, kind: f"/r2media/{kind}/{key}"
    )
    monkeypatch.setattr(review_provider, "_quote", lambda tenant, brand: None)
    review = review_provider.read_review(TENANT, PARENT, 2, UUID(int=2))
    assert review.mode == "edit" and review.from_reel
    assert [p.key for p in review.photos] == ["t/x/p1.jpg", "t/x/p9.jpg"]
    assert review.photos[0].url == "/r2media/image/t/x/p1.jpg"
    # the tile plays a version's own vista previa while the owner looks at it
    assert review.versions[0].video_url == "/r2media/video/t/x/v1.mp4"
    assert review.versions[0].poster_url == "/r2media/image/t/x/v1.jpg"


def test_the_inspiration_reel_is_the_first_part_from_a_reel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative import part_progress
    from qualify_api.referentes import reel_analysis

    first, second = uuid4(), uuid4()
    rows = (
        SimpleNamespace(analysis_id=None),
        SimpleNamespace(analysis_id=first),
        SimpleNamespace(analysis_id=second),
    )
    monkeypatch.setattr(
        part_progress, "read_part_progress", lambda **kw: SimpleNamespace(parts=rows)
    )
    page = "https://www.tiktok.com/@thegoldenbalance/video/1"
    pages = {first: page, second: "https://x/2"}
    monkeypatch.setattr(
        reel_analysis,
        "get_analysis",
        lambda tenant, aid: SimpleNamespace(post_url=pages[aid], network="tiktok", post_id="1"),
    )
    asked: list[dict] = []

    def reel_account(**kw: object) -> str:
        asked.append(kw)
        return "thegoldenbalance"

    monkeypatch.setattr(review_provider.part_review, "reel_account", reel_account)
    assert review_provider.inspiration(TENANT, PARENT) == (page, "@thegoldenbalance")
    assert asked == [{"tenant_id": TENANT, "network": "tiktok", "post_id": "1"}]
    # the stored account unreadable: the page's own still says it
    monkeypatch.setattr(
        review_provider.part_review,
        "reel_account",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("down")),
    )
    assert review_provider.inspiration(TENANT, PARENT) == (page, "@thegoldenbalance")
    monkeypatch.setattr(
        part_progress, "read_part_progress", lambda **kw: SimpleNamespace(parts=rows[:1])
    )
    assert review_provider.inspiration(TENANT, PARENT) == ("", "")


def test_the_quote_reads_the_brand_without_locking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live test 2026-11-13: «Te quedan» comes from the brand's balance — never the
    draft's `FOR UPDATE` (a join holding the part's row made the panel wait for ever)."""
    from datetime import date

    from qualify_api.creative import composition

    balance = SimpleNamespace(
        left=5, quota=10, renews_on=date(2026, 12, 1), previews_left=9, preview_quota=20
    )
    service = SimpleNamespace(creations_balance=lambda **kw: balance)
    monkeypatch.setattr(composition, "production_content_service", lambda: service)
    quote = review_provider._quote(TENANT, uuid4())
    assert quote is not None
    assert vm.change_use_text(quote)[0] == "Usa 1 vista previa. Te quedan 9."
    assert review_provider._quote(TENANT, None) is None


# -- 4. state --------------------------------------------------------------------------------


async def _drain(events: Any) -> list[Any]:
    if hasattr(events, "__aiter__"):
        return [event async for event in events]
    await events
    return []


@pytest.fixture
def card(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    seen = SimpleNamespace(change=[], use=[], review=_review(), fail=None, reads=0)

    async def identity(self: FinalVideoState) -> tuple[UUID, UUID]:
        return TENANT, USER

    async def read(self: FinalVideoState, parent: UUID, tenant_id: UUID) -> None:
        seen.reads += 1

    def change_part(*args: Any) -> UUID:
        seen.change.append(args)
        return UUID(int=1)

    def use_version(*args: Any) -> None:
        if seen.fail is not None:
            raise seen.fail
        seen.use.append(args)

    def read_review(tenant: UUID, parent: UUID, index: int, draft: UUID | None) -> vm.PartReview:
        assert (tenant, parent) == (TENANT, PARENT)
        return seen.review

    monkeypatch.setattr(FinalVideoState, "_identity", identity)
    monkeypatch.setattr(FinalVideoState, "_read", read)
    monkeypatch.setattr(card_provider, "change_part", change_part)
    monkeypatch.setattr(review_provider, "use_version", use_version)
    monkeypatch.setattr(review_provider, "read_review", read_review)
    yield seen


def _chosen() -> FinalVideoState:
    state = FinalVideoState()
    state.parent_id = str(PARENT)
    state.part_options = ["1", "2"]
    state.part_thumbs = [{"index": "1", "number": "1"}, {"index": "2", "number": "2"}]
    return state


async def _open(state: FinalVideoState, index: str = "2") -> list[Any]:
    events = FinalVideoState.choose_part.fn(state, index, str(UUID(int=2)))
    await _drain(FinalVideoState.load_review.fn(state, index, str(UUID(int=2))))
    return events


async def test_choosing_a_part_reads_its_panel_and_fills_it(card: SimpleNamespace) -> None:
    state = _chosen()
    events = await _open(state)
    assert "load_review" in str(events[0]) and card_module.CHANGE_TITLE_ID in str(events[1])
    assert state.review_ready and not state.review_loading
    assert state.change_text.startswith("Un chico muerde")  # filled in, not a blank box
    assert state.review_selected == ["t/x/p2.jpg", "t/x/p3.jpg"]
    assert state.review_version.current and state.review_version.label == "Versión 2 de 2"
    assert state.review_has_previous and not state.review_has_next
    assert state.review_mode_label == "Nueva, inspirada en el original"
    assert state.review_blocked == ""


async def test_a_read_for_a_part_no_longer_chosen_lands_nowhere(card: SimpleNamespace) -> None:
    state = _chosen()
    FinalVideoState.choose_part.fn(state, "2")
    FinalVideoState.choose_part.fn(state, "1")  # moved on before the read came back
    await _drain(FinalVideoState.load_review.fn(state, "2"))
    assert not state.review_ready and state.change_text == ""


async def test_see_the_previous_version_and_back(card: SimpleNamespace) -> None:
    state = _chosen()
    await _open(state)
    FinalVideoState.set_change_text.fn(state, "Mi cambio")
    FinalVideoState.show_version.fn(state, -1)
    assert state.review_at == 0 and not state.review_version.current
    assert state.change_text == "Descripción 1" and state.review_selected == ["t/x/p1.jpg"]
    FinalVideoState.show_version.fn(state, -1)  # nothing before the first
    assert state.review_at == 0
    FinalVideoState.show_version.fn(state, 1)
    assert state.review_version.current and state.change_text.startswith("Un chico muerde")
    assert state.review_selected == ["t/x/p2.jpg", "t/x/p3.jpg"]


async def test_photos_go_in_and_out_in_their_order(card: SimpleNamespace) -> None:
    state = _chosen()
    await _open(state)
    FinalVideoState.toggle_photo.fn(state, "t/x/p2.jpg")
    assert state.review_selected == ["t/x/p3.jpg"]
    FinalVideoState.toggle_photo.fn(state, "t/x/p1.jpg")
    assert state.review_selected == ["t/x/p3.jpg", "t/x/p1.jpg"]
    FinalVideoState.toggle_photo.fn(state, "t/x/nope.jpg")  # not one of the part's
    assert "t/x/nope.jpg" not in state.review_selected


async def test_crear_otra_version_sends_the_edited_fields(card: SimpleNamespace) -> None:
    state = _chosen()
    await _open(state)
    FinalVideoState.set_change_text.fn(state, "Un chico muerde la hamburguesa de cerca.")
    FinalVideoState.toggle_photo.fn(state, "t/x/p3.jpg")
    events = await _drain(FinalVideoState.change_part.fn(state))
    assert card.change == [
        (TENANT, PARENT, 2, "Un chico muerde la hamburguesa de cerca.", USER, ("t/x/p2.jpg",))
    ]
    assert not state.change_open and not state.review_ready
    assert events[-1].name == card_module.PART_PROGRESS_POLL


async def test_untouched_photos_are_never_sent(card: SimpleNamespace) -> None:
    """Review of UI-8: the part keeps every photo it has (place, style…) unless the owner
    changed the product ones — and back on the current version counts as untouched."""
    state = _chosen()
    await _open(state)
    FinalVideoState.show_version.fn(state, -1)
    FinalVideoState.show_version.fn(state, 1)
    FinalVideoState.set_change_text.fn(state, "Más de cerca.")
    await _drain(FinalVideoState.change_part.fn(state))
    assert card.change[0][-1] is None


async def test_touched_photos_keep_the_place_and_style_ones(card: SimpleNamespace) -> None:
    card.review = _review(
        photo_keys=("t/x/p2.jpg", "t/x/p3.jpg"),
        all_photo_keys=("t/x/local.jpg", "t/x/p2.jpg", "t/x/mood.jpg", "t/x/p3.jpg"),
    )
    state = _chosen()
    await _open(state)
    FinalVideoState.toggle_photo.fn(state, "t/x/p2.jpg")  # off
    FinalVideoState.toggle_photo.fn(state, "t/x/p1.jpg")  # a photo of version 1, on
    await _drain(FinalVideoState.change_part.fn(state))
    assert card.change[0][-1] == ("t/x/local.jpg", "t/x/mood.jpg", "t/x/p3.jpg", "t/x/p1.jpg")


def test_photos_to_send() -> None:
    every = ("local.jpg", "a.jpg", "mood.jpg", "b.jpg")
    # untouched (any order): None, the part keeps all it has
    assert vm.photos_to_send(["b.jpg", "a.jpg"], ["a.jpg", "b.jpg"], every) is None
    # mixed roles: the place and style photos stay, in the brief's order
    assert vm.photos_to_send(["b.jpg"], ["a.jpg", "b.jpg"], every) == (
        "local.jpg",
        "mood.jpg",
        "b.jpg",
    )
    # a part without product photos: untouched sends None, never ()
    assert vm.photos_to_send([], [], ("local.jpg",)) is None
    # …and a product photo added to it keeps its place photo
    assert vm.photos_to_send(["n.jpg"], [], ("local.jpg",)) == ("local.jpg", "n.jpg")


@pytest.mark.parametrize(
    ("setup", "reason", "target"),
    [
        (
            lambda s: FinalVideoState.set_change_text.fn(s, "   "),
            vm.DESCRIPTION_REQUIRED,
            "document.getElementById('q-final-video-change-description')",
        ),
        (
            lambda s: [FinalVideoState.toggle_photo.fn(s, k) for k in list(s.review_selected)],
            vm.PHOTO_REQUIRED,
            "document.querySelector('#q-final-video-change-photos button')",
        ),
    ],
)
async def test_crear_otra_version_waits_with_its_reason(
    card: SimpleNamespace, setup: Any, reason: str, target: str
) -> None:
    """UX review: the reason is heard (live region) and the keyboard goes to what is
    missing — never the card's error, drawn far above at 375 px."""
    state = _chosen()
    await _open(state)
    setup(state)
    assert state.review_blocked == reason
    events = await _drain(FinalVideoState.change_part.fn(state))
    assert card.change == [] and state.error == "" and state.announce == reason
    assert len(events) == 1 and target in str(events[0])


async def test_no_vista_previa_left_this_month(card: SimpleNamespace) -> None:
    card.review = _review(quote=(0, 5, 10, "1 de diciembre", 1, 0, 20))
    state = _chosen()
    await _open(state)
    assert state.review_out and state.review_blocked == state.review_use_text
    await _drain(FinalVideoState.change_part.fn(state))
    assert card.change == []


async def test_use_an_earlier_version(card: SimpleNamespace) -> None:
    state = _chosen()
    await _open(state)
    await _drain(FinalVideoState.use_version.fn(state))  # the current one: nothing
    assert card.use == []
    FinalVideoState.show_version.fn(state, -1)
    events = await _drain(FinalVideoState.use_version.fn(state))
    assert card.use == [(TENANT, PARENT, 2, V1, USER)]
    assert state.announce == "Usamos la versión 1 de la parte 2. Estamos juntando tu video."
    assert not state.change_open and state.busy == ""
    assert card_module.PARTS_STATUS_ID in str(events[0])
    assert events[-1].name == card_module.PART_PROGRESS_POLL


async def test_an_expired_version_is_never_used(card: SimpleNamespace) -> None:
    card.review = _review(versions=(_version(1, expired=True), _version(2, current=True)))
    state = _chosen()
    await _open(state)
    FinalVideoState.show_version.fn(state, -1)
    assert state.review_version.use_reason == vm.VERSION_EXPIRED_TEXT
    await _drain(FinalVideoState.use_version.fn(state))
    assert card.use == []


async def test_a_refused_version_says_what_to_do(card: SimpleNamespace) -> None:
    card.fail = review_provider.NotReviewable()
    state = _chosen()
    await _open(state)
    FinalVideoState.show_version.fn(state, -1)
    events = await _drain(FinalVideoState.use_version.fn(state))
    assert state.error == card_module.USE_REFUSED_TEXT and events == []
    assert card_module.refusal_text(RuntimeError("x"), card_module.USE) == (
        "No pudimos usar esa versión. Inténtalo de nuevo en un momento."
    )


async def test_a_panel_that_could_not_be_read_says_so(
    card: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: Any) -> vm.PartReview:
        raise RuntimeError("down")

    monkeypatch.setattr(review_provider, "read_review", broken)
    state = _chosen()
    await _open(state)
    assert state.review_error == "No pudimos abrir esta parte." and not state.review_ready
    # «Crear otra versión» waits: never an empty box sent as the description
    FinalVideoState.set_change_text.fn(state, "Una mano acerca el vaso.")
    assert state.review_blocked == vm.REVIEW_FAILED_TEXT
    events = await _drain(FinalVideoState.change_part.fn(state))
    assert card.change == [] and card_module.REVIEW_RETRY_ID in str(events[0])
    # [Intentar de nuevo] reads once more, and now it opens
    monkeypatch.setattr(review_provider, "read_review", lambda *_: card.review)
    retry = FinalVideoState.retry_review.fn(state)
    assert "load_review" in str(retry[0]) and state.review_loading
    await _drain(FinalVideoState.load_review.fn(state, "2", str(UUID(int=2))))
    assert state.review_ready and state.review_error == ""
    assert state.change_text.startswith("Un chico muerde")


def test_letting_the_part_go_clears_its_panel() -> None:
    state = _chosen()
    state.change_open, state.change_index = True, "2"
    state.review_ready = True
    state.review_versions = [PartVersionView(version_id="x", current=True)]
    state.review_photos = [PhotoChoiceView(key="k")]
    FinalVideoState.cancel_change.fn(state)
    assert not state.review_ready and state.review_versions == [] and state.review_photos == []


# -- «Me gusta así» ----------------------------------------------------------------------------


class Proxy:
    """`async with self` / `get_state` over a plain `PartProgressState`."""

    def __init__(self, state: PartProgressState) -> None:
        object.__setattr__(self, "state", state)

    async def __aenter__(self) -> Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_state(self, cls: type) -> Any:
        assert cls is progress_module.AuthState
        return SimpleNamespace(session_tenant_id=str(TENANT), _session_user_id=str(USER))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.state, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.state, name, value)


@pytest.fixture
def likes(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    seen = SimpleNamespace(calls=[], fail=None, during=None)

    def set_liked(tenant: UUID, parent: UUID, index: int, liked: bool) -> bool:
        seen.calls.append((tenant, parent, index, liked))
        if seen.during is not None:
            seen.during()
        if seen.fail is not None:
            raise seen.fail
        return True

    async def to_thread(fn: Any, *args: Any, **kw: Any) -> Any:
        return fn(*args, **kw)

    monkeypatch.setattr(review_provider, "set_liked", set_liked)
    monkeypatch.setattr(progress_module.asyncio, "to_thread", to_thread)
    return seen


def _shown(*rows: PartProgressRow) -> PartProgressState:
    state = PartProgressState()
    state._parent_id, state._mounted = str(PARENT), True
    state._apply(_progress(*rows))
    return state


async def test_me_gusta_asi_answers_at_once_and_is_written(likes: SimpleNamespace) -> None:
    state = _shown(_row(1, PartState.TO_REVIEW, total=2), _row(2, PartState.CREATING, total=2))
    tile = state.part_tiles[0]
    assert tile.can_like and not tile.liked and tile.word != vm.LIKED_PILL
    assert not state.part_tiles[1].can_like  # still being made

    def on_screen() -> None:  # while the write runs, the tile already says «✓ Lista»
        assert state.part_tiles[0].liked and state.part_tiles[0].word == vm.LIKED_PILL

    likes.during = on_screen
    events = [e async for e in PartProgressState.toggle_like.fn(Proxy(state), "1")]
    assert likes.calls == [(TENANT, PARENT, 1, True)]
    assert len(events) == 1  # one read follows
    # the read after the write is the truth: it says liked
    state._apply(
        _progress(
            _row(1, PartState.READY, liked=True, total=2), _row(2, PartState.CREATING, total=2)
        )
    )
    assert state.part_tiles[0].liked and state.part_tiles[0].tone == "ok"
    assert state.announce == "La parte 1 está lista."
    # a second tap takes it off
    likes.during = None
    [e async for e in PartProgressState.toggle_like.fn(Proxy(state), 1)]
    assert likes.calls[-1] == (TENANT, PARENT, 1, False)


async def test_a_refused_like_goes_back_and_says_why(likes: SimpleNamespace) -> None:
    state = _shown(_row(1, PartState.TO_REVIEW, total=1))
    likes.fail = review_provider.NotReviewable()
    [e async for e in PartProgressState.toggle_like.fn(Proxy(state), "1")]
    assert not state.part_tiles[0].liked
    assert state.like_error == vm.LIKE_REFUSED_TEXT == state.announce
    likes.fail = RuntimeError("down")
    [e async for e in PartProgressState.toggle_like.fn(Proxy(state), "1")]
    assert state.like_error == vm.LIKE_FAILED_TEXT


async def test_an_approved_part_offers_no_like(likes: SimpleNamespace) -> None:
    state = _shown(_row(1, PartState.READY, total=1))  # approved: READY, not liked
    assert not state.part_tiles[0].can_like
    [e async for e in PartProgressState.toggle_like.fn(Proxy(state), "1")]
    assert likes.calls == []


# -- 5. view ---------------------------------------------------------------------------------


def test_me_gusta_asi_sits_above_cambiar_esta() -> None:
    from . import final_video_card as view

    tile = str(view._part_card(PartProgressState.part_tiles[0]).render())
    assert "part_progress_state.toggle_like" in tile
    assert tile.index("toggle_like") < tile.index("choose_part")
    assert "Me gusta as" in tile and '"Lista"' in tile
    assert '?.["can_like"]' in tile and "final_video_state.closed" in tile
    assert '?.["draft_id"]' in tile  # the part's draft goes with «Cambiar esta»
    # its name is fixed («Me gusta así: parte N»); the state is aria-pressed alone
    from . import final_video_card as view_module

    like = str(view_module._like_button(PartProgressState.part_tiles[0]).render())
    name = like[like.index("aria-label") if "aria-label" in like else like.index("ariaLabel") :]
    assert "Lista" not in name[:120]


def test_usar_esta_version_dims_whenever_it_is_off() -> None:
    from . import final_video_card as view

    versions = str(view._versions().render())
    use = versions[versions.index("use_version") - 1500 : versions.index("use_version")]
    assert "final_video_state.working" in use and "opacity" in use


def test_the_panel_is_a_region_with_no_player_nor_skeleton() -> None:
    from . import final_video_card as view

    panel = str(view._change_panel().render())
    flat = panel.replace("_", "-")
    assert '"region"' in panel and card_module.CHANGE_TITLE_ID in panel
    for word in ("Ver la anterior", "Ver la siguiente", "Usar esta versi"):
        assert word in panel, word
    # Deivid, 2026-11-13: the tile's vista previa only; nothing while it is read
    assert "ReactPlayer" not in panel and "muted" not in panel
    assert "Skeleton" not in panel
    assert "inspiration" not in panel  # the reel's link is on the page, not here
    assert "le cambiamos?" not in panel  # the free note is gone
    assert "Aprobar" not in panel  # a part is never approved on its own
    assert "q-choice-card" in panel and ("aria-pressed" in flat or "ariaPressed" in panel)
    assert "no usa fotos" in panel


def test_the_inspiration_card_sits_above_the_campaign() -> None:
    """Deivid, 2026-11-13: «que el video original diga la cuenta y el botón de ir al
    video con su card»."""
    from . import creative_pages

    card = str(creative_pages._inspiration_card("p").render())
    assert "Video de inspiraci" in card and "Ir al video" in card
    assert "inspiration_account" in card and "inspiration_url" in card
    assert "_blank" in card and "noopener noreferrer" in card
    # «Campaña»'s head: glyph and title left, a spacer, the button flush right — one
    # row that wraps (below at 375 px) — and a decorative clapperboard in its frame
    assert '"wrap"' in card and "LucideClapperboard" in card and "q-section-glyph" in card
    assert card.index("inspiration_account") < card.index("Ir al video")
    campaign = str(creative_pages._campaign_field().render())
    for head in (card, campaign):  # the same head, so the right edges line up
        assert '"wrap"' in head and '"center"' in head and '"0.75rem"' in head
    page = str(creative_pages._parts_parent_made().render())
    assert page.index("inspiration_url") < page.index("Campa")


async def test_an_earlier_version_plays_in_the_parts_tile(card: SimpleNamespace) -> None:
    """Deivid, 2026-11-13: «quiero poder ver la versión antes de seleccionarla»."""
    state = _chosen()
    await _open(state)
    assert state.review_peek.version_id == ""  # the current one: the tile as it is
    FinalVideoState.show_version.fn(state, -1)
    peek = state.review_peek
    assert peek.version_id == str(V1) and peek.label == "Versión 1 de 2"
    assert peek.play_label == "Ver la versión 1 de 2 de la parte 2"
    FinalVideoState.show_version.fn(state, 1)
    assert state.review_peek.version_id == ""
    FinalVideoState.show_version.fn(state, -1)
    FinalVideoState.cancel_change.fn(state)  # «Cancelar»: back to the current one
    assert state.review_peek.version_id == ""
    from . import final_video_card as view

    tile = str(view._part_card(PartProgressState.part_tiles[0]).render())
    assert "review_peek" in tile and "data-clip-src" in tile


def test_while_joining_the_card_is_only_the_wait() -> None:
    """Deivid, 2026-11-13: «que se oculte todo y solo esté el loader en el medio»."""
    from . import final_video_card as view
    from .part_progress_panel import part_progress_panel

    state = FinalVideoState()
    for join, steps in (("joining", 1), ("rejoining", 1), ("failed", 0), ("ready", 0)):
        state.join_state = join
        assert len(state.joining_steps) == steps, join
    state.join_state = "joining"
    assert state.joining_steps[0]["title"] == (
        "Estamos juntando tus partes. En un momento lo ves aquí."
    )
    only = str(view._joining_only().render())
    assert "q-progress-track" in only and "part_tiles" not in only and "approve" not in only
    whole = str(view.final_video_card("p").render())
    assert "wants_refresh" in whole
    panel = str(part_progress_panel("p").render())
    assert "final_video_state.wants_refresh" in panel  # the parts' line hides too


def test_the_status_line_ids_stay_pinned() -> None:
    assert card_module.PARTS_STATUS_ID == progress_module.STATUS_ID
