"""m-24921084: «Tu video completo» words and states (`final_video_vm`), pure — the copy of
`docs/ux-video-por-planos.md` §3e and §4, in seconds (ADR 44 F1 = (b))."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from .final_video_vm import (
    APPROVE_WAIT_JOIN_HINT,
    JOIN_FAILED_TEXT,
    JOINING_TEXT,
    PREVIEW_TEXT,
    PURGED_TEXT,
    deadline_text,
    final_video_card,
    quota_text,
    recreate_label,
    recreate_text,
    seconds_header,
)


@dataclass(frozen=True)
class Use:
    uses: int
    quota: int
    left: int
    unlimited: bool = False
    in_seconds: bool = True
    renews_on: date | None = None


@dataclass(frozen=True)
class Previews:
    uses: int
    left: int
    quota: int
    unlimited: bool = False
    renews_on: date | None = None


@dataclass(frozen=True)
class Facts:
    state: str = "ready"
    seconds: int = 18
    planned: int = 4
    can_approve: bool = True
    blocker: str | None = None
    expires_at: datetime | None = None
    expired_parts: tuple[int, ...] = ()
    failed_parts: tuple[int, ...] = ()
    redo_parts: tuple[int, ...] = ()
    video_use: Use | None = None
    recreate_use: Previews | None = None


# Thursday 5 November 2026, 15:00 UTC = 10:00 in Bogotá
THURSDAY = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)


def test_header() -> None:
    assert seconds_header(18) == "Tu video completo · 18 s · Vista previa"
    assert seconds_header(0) == "Tu video completo · Vista previa"


def test_ready_card_with_approve_on_and_the_months_seconds() -> None:
    card = final_video_card(
        Facts(video_use=Use(uses=18, quota=40, left=40), expires_at=THURSDAY),
        zone="America/Bogota",
    )
    assert card.header == "Tu video completo · 18 s · Vista previa"
    assert card.pill_word == "" and card.status_text == ""
    assert card.show_video and card.preview_text == PREVIEW_TEXT
    assert PREVIEW_TEXT == (
        "Es una vista previa en calidad baja, para que decidas rápido. Al aprobarla "
        "preparamos cada parte en alta calidad y las juntamos."
    )
    assert card.approve_visible and card.approve_enabled and card.approve_hint == ""
    assert card.approve_label == "Aprobar"
    assert card.quota_text == (
        "Este video dura 18 s y este mes te quedan 40 s de video. Al aprobarlo te quedarían 22 s."
    )
    assert card.deadline_text == (
        "Apruébalo antes del jueves 5 de noviembre para tener el video final."
    )
    assert card.change_part_visible and card.change_part_label == "Cambiar una parte"
    assert not card.rejoin_visible and not card.recreate_visible


def test_juntando_only_while_really_joining() -> None:
    for state in ("joining", "rejoining"):
        card = final_video_card(Facts(state=state, can_approve=False, blocker="joining"))
        assert (card.pill_word, card.pill_tone) == ("Juntando", "info")
        assert card.status_text == JOINING_TEXT == "Juntando tus partes…"
    for blocker in ("not_ready", "part_failed", "expired", "needs_redo"):
        card = final_video_card(Facts(state="waiting", can_approve=False, blocker=blocker))
        assert card.pill_word == "" and card.status_text == ""
    assert not final_video_card(Facts(state="joining", can_approve=False)).show_video
    assert final_video_card(Facts(state="rejoining", can_approve=False)).show_video


def test_each_blocker_has_its_own_hint() -> None:
    def hint(**kwargs) -> str:  # noqa: ANN003
        return final_video_card(Facts(state="waiting", can_approve=False, **kwargs)).approve_hint

    assert hint(blocker="not_ready") == "Disponible cuando las 4 partes tengan su vista previa."
    assert hint(blocker="part_failed", failed_parts=(2,)) == (
        "Disponible cuando decidas qué hacer con la parte 2."
    )
    assert (
        hint(blocker="needs_redo", redo_parts=(3,))
        == "Disponible cuando decidas qué hacer con la parte 3."
    )
    assert hint(blocker="part_failed", failed_parts=(1, 4), redo_parts=(3,)) == (
        "Disponible cuando decidas qué hacer con las partes 1, 3 y 4."
    )
    assert hint(blocker="expired", expired_parts=(3,)) == (
        "Disponible cuando crees otra vez la parte 3."
    )
    assert hint(blocker="expired", expired_parts=(2, 3)) == (
        "Disponible cuando crees otra vez las partes 2 y 3."
    )
    assert hint(blocker="joining") == APPROVE_WAIT_JOIN_HINT


def test_join_failed_offers_to_join_again() -> None:
    card = final_video_card(Facts(state="failed", can_approve=False, blocker="join_failed"))
    assert (card.pill_word, card.pill_tone) == ("No salió", "error")
    assert (
        card.status_text
        == JOIN_FAILED_TEXT
        == (
            "No pudimos juntar tus partes. Siguen guardadas y no se descontó nada. "
            "Toca «Juntar otra vez»."
        )
    )
    assert card.rejoin_visible and card.rejoin_label == "Juntar otra vez"
    assert card.approve_hint == ""


def test_one_recreate_button_naming_the_parts() -> None:
    card = final_video_card(
        Facts(
            state="waiting",
            can_approve=False,
            blocker="expired",
            expired_parts=(3,),
            recreate_use=Previews(uses=1, left=9, quota=20),
        )
    )
    assert card.recreate_visible and card.recreate_label == "Crear la parte 3 otra vez"
    assert card.recreate_text == (
        "Crea otra vez la parte 3. Usa 1 vista previa. Te quedan 9 vistas previas."
    )
    (notice,) = card.expired_parts
    assert notice.text == (
        "La vista previa de la parte 3 venció. Créala otra vez para tener el video final."
    )
    assert recreate_label((2, 3)) == "Crear las partes 2 y 3 otra vez"
    assert recreate_label(()) == ""


def test_recreate_text_variants() -> None:
    assert recreate_text((), None) == ""
    assert recreate_text((3,), None) == "Crea otra vez la parte 3."
    assert recreate_text(
        (2, 3), Previews(uses=2, left=1, quota=20, renews_on=date(2026, 12, 1))
    ) == (
        "Crea otra vez las partes 2 y 3. Usan 2 vistas previas y este mes te queda "
        "1 vista previa. Vuelven el 1 de diciembre."
    )
    assert recreate_text((2, 3), Previews(uses=2, left=0, quota=20)) == (
        "Crea otra vez las partes 2 y 3. Usan 2 vistas previas y este mes te quedan "
        "0 vistas previas."
    )
    assert recreate_text((1, 2, 4), Previews(uses=3, left=1, quota=20, unlimited=True)) == (
        "Crea otra vez las partes 1, 2 y 4."
    )
    assert recreate_text((3,), Previews(uses=1, left=1, quota=20)) == (
        "Crea otra vez la parte 3. Usa 1 vista previa. Te queda 1 vista previa."
    )


def test_quota_text_in_seconds() -> None:
    assert quota_text(None) == ""
    assert quota_text(Use(uses=10, quota=40, left=40, unlimited=True)) == ""
    assert quota_text(Use(uses=0, quota=40, left=40)) == ""
    assert quota_text(Use(uses=39, quota=40, left=40)) == (
        "Este video dura 39 s y este mes te quedan 40 s de video. Al aprobarlo te quedaría 1 s."
    )
    short = quota_text(Use(uses=18, quota=40, left=10, renews_on=date(2026, 12, 1)))
    assert short == (
        "Este video dura 18 s y este mes te quedan 10 s de video. Para aprobarlo, quita "
        "partes o espera al 1 de diciembre, cuando vuelven tus 40 segundos."
    )


def test_deadline_in_the_business_zone() -> None:
    late = datetime(2026, 11, 7, 2, 0, tzinfo=UTC)  # Saturday in UTC, Friday 21:00 in Bogotá
    assert deadline_text(late, "America/Bogota").startswith("Apruébalo antes del viernes 6")
    assert deadline_text(late, "UTC").startswith("Apruébalo antes del sábado 7")
    assert deadline_text(late, "Not/AZone").startswith("Apruébalo antes del sábado 7")
    assert deadline_text(None) == ""


def test_approved_hides_approve_deadline_and_quota() -> None:
    card = final_video_card(
        Facts(
            state="approved",
            can_approve=False,
            blocker="approved",
            expires_at=THURSDAY,
            video_use=Use(uses=18, quota=40, left=40),
        )
    )
    assert not card.approve_visible and card.approve_hint == ""
    assert card.deadline_text == "" and card.quota_text == "" and card.pill_word == ""


def test_purged_says_to_make_a_new_video_and_offers_no_part_action() -> None:
    from qualify_api.creative.parts import PURGED_PARENT_TEXT

    card = final_video_card(
        Facts(state="purged", can_approve=False, blocker="purged", expired_parts=(1, 2))
    )
    assert card.status_text == PURGED_TEXT == PURGED_PARENT_TEXT
    assert not card.approve_visible and not card.change_part_visible
    assert not card.recreate_visible and not card.rejoin_visible and not card.show_video
    assert card.approve_hint == "" and card.pill_word == ""


def test_no_english_words_on_the_card() -> None:
    card = final_video_card(Facts(state="failed", can_approve=False, blocker="join_failed"))
    words = " ".join(str(v) for v in card.__dict__.values()).lower()
    for banned in ("preview", "render", "join", "clip", "draft", "brand kit"):
        assert banned not in words
