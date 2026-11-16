"""ED-01 (m-25026605): `edit_preview` builds and renders on its own — no screen uses it
until «Arma tu video» (ED-02), so the app's compile check does not cover it yet."""

from __future__ import annotations

import reflex as rx

from .ui import edit_preview as ep


class _PreviewState(rx.State):
    """A stand-in for the screen's state: only the duration report the preview needs."""

    reported: list[float] = []

    @rx.event
    def on_duration(self, key: str, seconds: float, width: int, height: int) -> None:
        self.reported = [seconds, float(width), float(height)]

    @rx.event
    def on_resolve(self) -> None:
        self.reported = []


def _preview(*, undo_on: bool = False) -> rx.Component:
    v = rx.Var.create
    return ep.edit_preview(
        src=v("/_upload/t/x/video.mp4"),
        video_key=v("t/x/video.mp4"),
        poster=v(""),
        start=v(2.0),
        end=v(9.5),
        speed=v(1.0),
        rate=v(1.0),
        rotate=v(90),
        text=v("2×1 solo este fin de semana"),
        place=v("top"),
        text_long=v(False),
        text_layout="scrim",
        effect_srcs=v([]),
        focus=v(""),
        play_nonce=v(0),
        known=v(False),
        remote=v(False),
        pending=v(True),
        on_resolve=_PreviewState.on_resolve,
        on_duration=_PreviewState.on_duration,
        note_text="Así va quedando",
        remote_text="No pudimos mostrar este video aquí. Lo verás armado al crear.",
        broken_text="No pudimos mostrar tu video aquí. Igual puedes seguir: lo armamos al crear.",
        slower_text="En la vista previa se ve más lento que en el video final.",
        slower=v(False),
        empty_text="Agrega una foto o un video para ver cómo va quedando.",
        play_label="Ver cómo va quedando",
        pause_label="Pausar la vista previa",
        sound_label="Activar el sonido",
        region_label="Vista previa de tu video",
        undo=rx.button("Deshacer") if undo_on else None,
        undo_on=undo_on,
    )


def test_the_preview_renders_with_its_words_and_hooks() -> None:
    rendered = str(_preview().render())
    for needle in (
        "q-edit-preview",
        "data-edit-duration-trigger",
        "data-edit-resolve-trigger",
        "Vista previa de tu video",
        "va quedando",
    ):
        assert needle in rendered, needle


def test_the_preview_takes_an_undo_line_and_the_script_mounts() -> None:
    assert "Deshacer" in str(_preview(undo_on=True).render())
    assert ep.edit_preview_script().render()["name"] == "RadixThemesBox"


# -- ED-01b m-25029106: the preview in sequence ----------------------------------------


class _SequenceState(rx.State):
    """A stand-in for the screen's state: the length and time reports."""

    heard: str = ""

    @rx.event
    def on_duration(self, key: str, seconds: float, width: int, height: int) -> None:
        self.heard = f"{key}:{seconds}"

    @rx.event
    def on_time(self, t: float, reason: str) -> None:
        self.heard = f"{t}:{reason}"


def _sequence() -> str:
    v = rx.Var.create
    return str(
        ep.edit_sequence_preview(
            sequence=v('{"blocks": [], "texts": [], "effects": []}'),
            texts=v([]).to(list[dict[str, str]]),
            effects=v([]).to(list[dict[str, str]]),
            slower=v(False),
            on_duration=_SequenceState.on_duration,
            on_time=_SequenceState.on_time,
            note_text="Así va quedando",
            broken_text="No pudimos mostrar este video aquí. Igual lo verás completo antes de "
            "aprobarlo.",
            slower_text="En la vista previa se ve más lento que en el video final.",
            play_label="Ver cómo va quedando",
            pause_label="Pausar la vista previa",
            sound_label="Activar sonido",
            mute_label="Quitar sonido",
            region_label="Vista previa de tu video",
        ).render()
    )


def test_the_sequence_sound_button_carries_both_labels() -> None:
    rendered = _sequence()
    # «Activar sonido» while muted; the script swaps to `data-mute-label` when it sounds
    assert "Activar sonido" in rendered
    assert "data-mute-label" in rendered and "Quitar sonido" in rendered


def test_the_sequence_broken_notice_is_announced_and_the_dot_can_hide() -> None:
    rendered = _sequence()
    assert "aria-live" in rendered and "polite" in rendered
    assert "data-edit-seq-broken" in rendered
    assert "q-edit-seq__dot" in rendered  # hidden by CSS while the clock has no time
