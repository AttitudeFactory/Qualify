"""m-24852129: «Pedir más a Qualify» — the zero state of each counter in Crear, the
button that is never there while something is left, the two confirmations (WhatsApp /
email), the balance with the 90-day extras, and no money anywhere the owner looks."""

from __future__ import annotations

import pathlib
import re

import pytest

from .ask_more_vm import (
    ASK_MORE_BUTTON,
    ASK_MORE_SENT_BUTTON,
    ask_more_sent_text,
    exhausted_kind,
    exhausted_text,
)
from .creative_state import CreativeState
from .creative_vm import creations_left_label

_HERE = pathlib.Path(__file__).resolve().parent


@pytest.fixture
def on_summary(monkeypatch):  # noqa: ANN201
    monkeypatch.setattr(CreativeState, "_on_summary", lambda self: True)


def _image(left: int = 18) -> CreativeState:
    state = CreativeState()
    state.choose_category("image")
    state.creations_left, state.creations_quota = left, 30
    state.videos_left, state.videos_quota = 4, 4
    state.previews_left, state.previews_quota = 20, 20
    return state


def _clip(*, videos_left: int = 4, previews_left: int = 20, video_quota: int = 4) -> CreativeState:
    state = CreativeState()
    state.choose_kind("clip")
    state.clip_duration = "5"
    state.creations_left, state.creations_quota = 30, 30
    state.videos_left, state.videos_quota = videos_left, video_quota
    state.previews_left, state.previews_quota = previews_left, 20
    return state


# --- the literal texts -----------------------------------------------------------------


def test_the_zero_state_texts_read_literally() -> None:
    assert exhausted_text("videos", 4) == (
        "Ya usaste tus 4 videos de este mes. ¿Necesitas más? Pídelos y te enviamos el "
        "enlace de pago."
    )
    assert exhausted_text("creations", 30) == (
        "Ya usaste tus 30 creaciones de este mes. ¿Necesitas más? Pídelas y te enviamos el "
        "enlace de pago."
    )
    assert exhausted_text("previews", 20) == (
        "Ya usaste tus 20 vistas previas de este mes. ¿Necesitas más? Pídelas y te enviamos "
        "el enlace de pago."
    )


def test_the_two_confirmations_read_literally() -> None:
    assert ask_more_sent_text(True) == "Listo. Te escribimos por WhatsApp con el enlace de pago."
    assert ask_more_sent_text(False) == "Listo. Te escribimos a tu correo con el enlace de pago."
    assert ASK_MORE_BUTTON == "Pedir más a Qualify"
    assert ASK_MORE_SENT_BUTTON == "Pedido enviado"


def test_the_balance_with_extras_is_the_founders_example() -> None:
    # Básico + «+2 videos», 1 video used
    text = creations_left_label(30, 30, 5, 6, 20, 20, extras=(0, "", 2, "22 de enero", 0, ""))
    assert "Te quedan 5 de 6 videos este mes (2 extra, vencen el 22 de enero)." in text
    assert text.startswith("Te quedan 30 de 30 creaciones este mes.")


def test_without_extras_the_balance_is_crear5s() -> None:
    assert creations_left_label(18, 30, 3, 4, 12, 20, extras=(0, "", 0, "", 0, "")) == (
        "Te quedan 18 de 30 creaciones y 3 de 4 videos este mes."
    )
    assert "(" not in creations_left_label(18, 30, 3, 4, 12, 20)


def test_one_extra_left_is_singular() -> None:
    text = creations_left_label(31, 50, 4, 4, 20, 20, extras=(1, "3 de febrero", 0, "", 0, ""))
    assert "Te quedan 31 de 50 creaciones este mes (1 extra, vence el 3 de febrero)." in text


# --- which counter is at 0, per kind ---------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"weight": 1, "videos": 0, "creations_left": 0}, "creations"),
        ({"weight": 1, "videos": 0, "creations_left": 5}, ""),
        ({"weight": 0, "videos": 1, "videos_left": 0}, "videos"),
        ({"weight": 0, "videos": 1, "previews_left": 0}, "previews"),
        ({"weight": 0, "videos": 1}, ""),
        # an image with no videos left is still made
        ({"weight": 1, "videos": 0, "videos_left": 0, "previews_left": 0}, ""),
    ],
)
def test_exhausted_kind(kwargs: dict, expected: str) -> None:
    base = {
        "weight": 0,
        "videos": 0,
        "creations_left": 30,
        "videos_left": 4,
        "video_quota": 4,
        "previews_left": 20,
        "preview_quota": 20,
    }
    assert exhausted_kind(**{**base, **kwargs}) == expected


@pytest.mark.usefixtures("on_summary")
def test_with_something_left_pedir_mas_is_not_in_crear() -> None:
    assert _image(18).gen_exhausted == ""
    assert _clip().gen_exhausted == ""
    assert _clip(videos_left=1, previews_left=1).gen_exhausted == ""


@pytest.mark.usefixtures("on_summary")
def test_each_counter_at_zero_disables_its_kind() -> None:
    assert _image(0).gen_exhausted == "creations"
    assert _clip(videos_left=0).gen_exhausted == "videos"
    assert _clip(previews_left=0).gen_exhausted == "previews"


@pytest.mark.usefixtures("on_summary")
def test_videos_at_zero_and_creations_left_an_image_still_works() -> None:
    image = _image(18)
    image.videos_left = 0
    assert image.gen_exhausted == "" and image._creations_problem() == ""


@pytest.mark.usefixtures("on_summary")
def test_the_number_is_the_real_quota_plan_plus_extras() -> None:
    clip = _clip(videos_left=0, video_quota=6)
    assert clip._creations_problem().startswith("Ya usaste tus 6 videos de este mes.")


def test_no_quota_wired_never_shows_the_zero_state(on_summary) -> None:  # noqa: ARG001
    state = _image(-1)
    assert state.gen_exhausted == ""


# --- the screens -----------------------------------------------------------------------


def test_crear_disables_its_button_and_offers_pedir_mas() -> None:
    page = (_HERE / "content_generator.py").read_text(encoding="utf-8")
    assert 'CreativeState.gen_exhausted != ""' in page
    for kind in ("videos", "previews", "creations"):
        assert f'ask_more_block("{kind}")' in page
    assert "en su lugar" not in page


def test_configuracion_always_has_pedir_mas() -> None:
    page = (_HERE / "settings_page.py").read_text(encoding="utf-8")
    assert 'ask_more_block("settings")' in page


def test_the_block_fits_a_phone() -> None:
    block = (_HERE / "ask_more_ui.py").read_text(encoding="utf-8")
    assert 'max_width="100%"' in block and 'white_space="normal"' in block


_MONEY = re.compile(r"USD|\$|precio|dólar", re.IGNORECASE)


def test_no_money_in_what_the_owner_reads() -> None:
    texts = [exhausted_text(kind, 4) for kind in ("creations", "videos", "previews")] + [
        ask_more_sent_text(True),
        ask_more_sent_text(False),
        ASK_MORE_BUTTON,
        ASK_MORE_SENT_BUTTON,
        creations_left_label(5, 6, 5, 6, 10, 30, extras=(1, "1 de enero", 2, "x", 10, "y")),
    ]
    assert not [t for t in texts if _MONEY.search(t)]


# --- reload: «Pedido enviado» still says where the link arrives -------------------------


@pytest.mark.parametrize(
    ("pending", "by_whatsapp", "sent", "notice"),
    [
        (True, True, True, "Listo. Te escribimos por WhatsApp con el enlace de pago."),
        (True, False, True, ask_more_sent_text(False)),
        (False, True, False, ""),
    ],
)
def test_reload_keeps_the_confirmation_next_to_pedido_enviado(
    monkeypatch: pytest.MonkeyPatch, pending: bool, by_whatsapp: bool, sent: bool, notice: str
) -> None:
    """UX review (m-24852129): after a reload the grey «Pedido enviado» used to stand
    alone; now it carries the same D13 confirmation (WhatsApp or email)."""
    import asyncio
    from uuid import uuid4

    from qualify_api.plans.ask_more import AskMoreStatus

    from . import ask_more_state
    from .ask_more_state import AskMoreState

    state = AskMoreState()
    state.notice = "stale"

    async def _tenant(self):  # noqa: ANN001, ANN202
        return uuid4()

    class _Ctx:
        async def __aenter__(self):  # noqa: ANN204
            return state

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(AskMoreState, "_tenant", _tenant)
    monkeypatch.setattr(AskMoreState, "__aenter__", _Ctx.__aenter__, raising=False)
    monkeypatch.setattr(AskMoreState, "__aexit__", _Ctx.__aexit__, raising=False)
    monkeypatch.setattr(
        ask_more_state, "read_status", lambda _t: AskMoreStatus(pending, by_whatsapp)
    )
    asyncio.run(AskMoreState.load.fn(state))
    assert (state.sent, state.notice) == (sent, notice)
