"""Final-review UI: exact copy, safe returns and explicit identity-bound confirmation."""

from __future__ import annotations

from uuid import UUID

import pytest

from .creative_pages import _video_draft_notice
from .creative_vm import video_draft_vm
from .final_review_panel import final_review_panel
from .final_review_vm import (
    FinalPanelVM,
    another_version_use,
    confirmation_note,
    final_state,
    other_version_pending,
)
from .review_links import review_destination, review_href

PIECE = UUID("a0000000-0000-4000-8000-000000000001")
USER = UUID("b0000000-0000-4000-8000-000000000001")
TENANT = UUID("c0000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize(
    "raw",
    [
        "https://evil.example/planner?revisar=videos",
        "//evil.example/planner?revisar=videos",
        "/planner?revisar=videos&pieza=bad",
        "/settings?revisar=videos",
        "/planner?revisar=videos&pieza=" + str(PIECE) + "&pieza=" + str(USER),
        "/planner?revisar=videos#confirm",
        "/planner?revisar=other",
    ],
)
def test_return_refuses_external_or_ambiguous_destinations(raw: str) -> None:
    assert review_destination(raw) == ""


def test_review_return_keeps_piece_event_and_failed_filter_only() -> None:
    assert review_destination(review_href(str(PIECE))) == review_href(str(PIECE))
    assert review_destination("/planner/?revisar=videos&pieza=" + str(PIECE)) == review_href(
        str(PIECE)
    )
    value = review_destination(
        "/planner?revisar=videos&evento=" + str(PIECE) + "&fallos=1&confirm=true"
    )
    assert "evento=" + str(PIECE) in value and "fallos=1" in value and "confirm" not in value


@pytest.mark.parametrize(
    "state,kwargs,badge,note",
    [
        (
            "final_scheduled",
            {},
            "Video final mañana",
            "Tu video final estará listo mañana temprano.",
        ),
        (
            "rendering",
            {"nightly": True, "during_night": True},
            "Video final mañana",
            "Tu video final estará listo en unas horas.",
        ),
        (
            "rendering",
            {},
            "Preparando el video final",
            "Tu video final estará listo en unos minutos. "
            "Te lo mostramos aquí para que lo confirmes.",
        ),
        (
            "final_ready",
            {},
            "Revisa el video",
            "Tu video final está listo. Míralo y confírmalo para que salga.",
        ),
        ("final", {}, "Listo para publicar", "Video confirmado."),
        (
            "failed",
            {},
            "Falta el video final",
            "No pudimos preparar el video final. Inténtalo de nuevo; no usa otro video.",
        ),
        (
            "final_ready",
            {"overdue": True, "hour": "7:00 p. m."},
            "Falta tu confirmación",
            "No salió a las 7:00 p. m. porque falta que confirmes el video.",
        ),
    ],
)
def test_exact_review_copy(state, kwargs, badge, note) -> None:
    result = final_state(state, **kwargs)
    assert result[0] == badge and result[2] == note
    for banned in ("render", "1080", "HD", "notificación"):
        assert banned not in result[0] + result[2]


def test_another_version_keeps_dates_and_says_both_counters() -> None:
    assert another_version_use(3) == "Usa 1 vista previa y 1 de tus videos del mes. Te quedarían 2."
    assert another_version_use(2).endswith("Te quedaría 1.")
    assert (
        another_version_use(0, quota=4, renews="1 de noviembre")
        == "Ya usaste tus 4 videos de este mes. Vuelven el 1 de noviembre."
    )
    stem = "Estamos creando otra versión. Cuando esté, la revisas y la apruebas."
    assert other_version_pending() == stem
    assert (
        other_version_pending(dates=1, day="jueves 30", hour="7:00 p. m.")
        == stem
        + " Sigue programada para el jueves 30 a las 7:00 p. m.: "
        "si no la confirmas antes, no se publica."
    )
    assert (
        other_version_pending(dates=1, today=True, hour="7:00 p. m.")
        == stem
        + " Sigue programada para hoy a las 7:00 p. m.: si no la confirmas antes, no se publica."
    )
    assert (
        other_version_pending(dates=2)
        == stem
        + " Sigue programada en las 2 fechas que elegiste: si no la confirmas antes, no se publica."
    )


def test_confirmation_message_is_piece_wide() -> None:
    assert confirmation_note(dates=0) == "Confirmado. Ahora elige cuándo sale."
    assert (
        confirmation_note(dates=1, day="jueves 30", hour="7:00 p. m.")
        == "Confirmado. Sale el jueves 30 a las 7:00 p. m."
    )
    assert confirmation_note(dates=2) == "Confirmado. Sale en las 2 fechas que elegiste."
    assert video_draft_vm("final_scheduled", None).rendering is False
    assert video_draft_vm("final_ready", None).can_review_final


async def test_open_only_reads_manifest_and_confirm_uses_that_exact_manifest(monkeypatch) -> None:
    from qualify_api.creative.final_review import FinalIdentity

    from . import final_review_state as module
    from .final_review_state import FinalReviewState

    async def ids(self):
        return TENANT, USER

    monkeypatch.setattr(FinalReviewState, "_identity", ids)
    expected = (FinalIdentity(PIECE, "t/tenant/video.mp4", "abc", 1),)
    panel = FinalPanelVM(
        piece_id=str(PIECE),
        state="final_ready",
        can_confirm=True,
        confirmed_note="Confirmado. Ahora elige cuándo sale.",
    )
    monkeypatch.setattr(module, "load_final_panel", lambda *a: (panel, expected))
    calls = []
    monkeypatch.setattr(module, "confirm_review", lambda *args: calls.append(args))
    state = FinalReviewState()
    await FinalReviewState.open_piece.fn(state, str(PIECE))
    assert calls == []  # navigation never confirms
    assert state._manifest is expected
    await FinalReviewState.confirm.fn(state)
    assert calls == [(TENANT, PIECE, USER, expected)]
    assert state.success == panel.confirmed_note
    FinalReviewState.close.fn(state)
    assert state._manifest == () and not state.open


def test_only_panel_exposes_confirmation_and_mobile_targets() -> None:
    rendered = str(final_review_panel())
    assert "confirm_label" in rendered and "44px" in rendered
    assert "confirm" not in str(_video_draft_notice()).lower() or "FinalReviewState" not in str(
        _video_draft_notice()
    )


def test_home_counts_union_avoids_under_count_and_duplicates() -> None:
    from qualify_api.home import HomeCounts

    from .home_vm import build_home_vm

    # A failed late piece has its own card; only a ready piece asks for confirmation.
    cards = build_home_vm(
        HomeCounts(videos_to_confirm=1, videos_late=0, videos_ready_late=0, finals_failed=1)
    ).today
    review = next(card for card in cards if card.key == "final-review")
    assert review.count == 1
    assert review.label == "1 video listo para revisar"
    failed = next(card for card in cards if card.key == "final-failed")
    assert failed.count == 1
    assert failed.label == "1 video final no se pudo preparar"
    cards = build_home_vm(HomeCounts(videos_to_confirm=2, videos_late=1, videos_ready_late=1)).today
    assert next(card for card in cards if card.key == "final-review").count == 2
