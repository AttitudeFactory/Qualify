"""`edit_preview` — the editor's live preview (ED-01 m-25026605, epic «Video automático con efectos,
por pasos», D-E1 = A): the owner's video as it will come out, simulated in the browser,
free, with nothing decoded in Reflex nor on the server.

What it shows, all in one 9:16 frame:

- **the stretch** (`start`→`end`, seconds of the source): the `<video>` plays only that
  and goes back to the stretch's start at its end (a loop, unlike `clip_player`, which
  stops); `assets/edit-preview.js` keeps it there;
- **the turn** (`rotate` 0/90/180/270): a CSS `rotate()`; at 90/270 the video is laid
  out with its sides swapped so it still fills the 9:16 frame (`.q-edit-preview__video`
  in `assets/qualify-creative.css`);
- **9:16**: `object-fit: cover`, centred (EF-03's crop);
- **«Cámara rápida»**: `playbackRate` = the speed, up to ×16 (browsers' limit); above it
  the screen says the preview is slower (`slower_text`);
- **the text** over the video: an HTML layer drawn as #674's catalog `scrim` layout
  (m-25017283, `editor_preview_contract.PreviewTextDesign`) at the top / middle / bottom,
  inside the catalog's 9:16 safe zone (x 64–1016, y 270–1536 of 1080×1920)
  — to scale;
- **the effects**: each a looping, muted `<video>` with `mix-blend-mode: screen` (their
  `preview_asset`). A missing file is never rendered (the screen passes only addresses
  that exist), so nothing 404s.

ONE sound: the main video (muted until the owner turns the sound on); the layers are
always muted. When the video cannot be played, the frame keeps its picture and
`broken_text` shows under it. The script reports on EVERY `loadedmetadata` the source's
length and upright size through a hidden button (`on_duration`) — the only facts the
server learns from the browser — and a failure the same way (a negative length: an
`error`, or no length after ~15 s), so «Cortar» never waits forever.

Under the frame, in the fixed zone: «{t} de {total} · Así va quedando» (the time written
by the script, in the final video's time), or «Deshacer» while a change is fresh.
"""

from __future__ import annotations

import reflex as rx

from . import tokens as T
from .primitives import asset_script

#: The script's name under `assets/` (`edit_preview_script`).
SCRIPT = "edit-preview.js"
#: The global the script fills before pressing the hidden duration button.
REPORT_GLOBAL = "window.__qEditPreviewReport"


def edit_preview_script() -> rx.Component:
    """Mount `assets/edit-preview.js` once (its guard keeps one set of listeners)."""
    return rx.box(display="none", on_mount=rx.call_script(asset_script(SCRIPT)))


def _duration_trigger(on_duration: object) -> rx.Component:
    """The hidden button the script presses once it knows the video's length; the
    handler receives `(key, seconds, width, height)` read from `REPORT_GLOBAL` at that moment."""
    key = rx.Var(f"String(({REPORT_GLOBAL} || {{}}).key || '')", _var_type=str)
    seconds = rx.Var(f"Number(({REPORT_GLOBAL} || {{}}).seconds || 0)", _var_type=float)
    width = rx.Var(f"Math.round(Number(({REPORT_GLOBAL} || {{}}).width || 0))", _var_type=int)
    height = rx.Var(f"Math.round(Number(({REPORT_GLOBAL} || {{}}).height || 0))", _var_type=int)
    return rx.el.button(
        type="button",
        on_click=on_duration(key, seconds, width, height),  # type: ignore[operator]
        tab_index=-1,
        aria_hidden="true",
        display="none",
        custom_attrs={"data-edit-duration-trigger": ""},
    )


def _resolve_trigger(on_resolve: object) -> rx.Component:
    """The hidden button the script presses when the screen marks the video «pending»
    (`data-edit-pending`): the screen mints the address it can be played from."""
    return rx.el.button(
        type="button",
        on_click=on_resolve,
        tab_index=-1,
        aria_hidden="true",
        display="none",
        custom_attrs={"data-edit-resolve-trigger": ""},
    )


def _effect_layer(src: rx.Var) -> rx.Component:
    return rx.el.video(
        src=src,
        muted=True,
        loop=True,
        auto_play=True,
        plays_inline=True,
        preload="auto",
        tab_index=-1,
        aria_hidden="true",
        custom_attrs={"data-edit-effect": ""},
        class_name="q-edit-preview__effect",
    )


def edit_preview(
    *,
    src: rx.Var[str],
    video_key: rx.Var[str],
    poster: rx.Var[str],
    start: rx.Var[float],
    end: rx.Var[float],
    speed: rx.Var[float],
    rate: rx.Var[float],
    rotate: rx.Var[int],
    text: rx.Var[str],
    place: rx.Var[str],
    text_long: rx.Var[bool],
    text_layout: str,
    effect_srcs: rx.Var[list[str]],
    focus: rx.Var[str],
    play_nonce: rx.Var[int],
    known: rx.Var[bool],
    remote: rx.Var[bool],
    pending: rx.Var[bool],
    on_resolve: object,
    on_duration: object,
    note_text: str,
    remote_text: str,
    broken_text: str,
    slower_text: str,
    slower: rx.Var[bool],
    empty_text: str,
    play_label: str,
    pause_label: str,
    sound_label: str,
    region_label: str,
    undo: rx.Component | None = None,
    undo_on: rx.Var[bool] | bool = False,
) -> rx.Component:
    """The preview of one recipe. `src`: the owner's video ("" = none: the frame shows
    `poster`, a photo or a video's thumbnail, or `empty_text`). `video_key` names it for
    the reports. `rate`: the playbackRate the browser can use; `speed` the real one (the
    time shown is the final video's). `focus` «start»/«end»: the handle «Cortar» moves
    (the frame jumps to it); `play_nonce` changes when a handle is released (the stretch
    plays). `remote`: the screen knows this video cannot play here (`remote_text` says
    so); `broken_text` is only for a real playback error (the script's `broken`).
    `undo` takes the note's place in the fixed zone while `undo_on` (D-E6)."""
    has_video = src != ""
    picture = rx.cond(
        poster != "",
        rx.image(
            src=poster,
            alt="",
            class_name="q-edit-preview__poster",
        ),
        rx.cond(
            ~has_video & ~remote,
            rx.center(
                rx.icon("film", size=T.ICON_LG, aria_hidden="true"),
                rx.text(empty_text, size="2", text_align="center"),
                class_name="q-edit-preview__empty",
            ),
        ),
    )
    controls = rx.fragment(
        # one announcement: the label changes («Ver…» / «Pausar…»), no `aria-pressed`
        rx.el.button(
            rx.icon("play", size=22, aria_hidden="true", class_name="q-edit-preview__glyph-play"),
            rx.icon("pause", size=22, aria_hidden="true", class_name="q-edit-preview__glyph-pause"),
            type="button",
            aria_label=play_label,
            title=play_label,
            custom_attrs={"data-edit-play-btn": "", "data-pause-label": pause_label},
            class_name="q-clip__btn q-edit-preview__play",
        ),
        rx.el.button(
            rx.box(
                rx.icon("volume-x", size=14, aria_hidden="true"), class_name="q-clip__sound-off"
            ),
            rx.box(rx.icon("volume-2", size=14, aria_hidden="true"), class_name="q-clip__sound-on"),
            type="button",
            aria_label=sound_label,
            title=sound_label,
            aria_pressed="false",
            custom_attrs={"data-edit-sound": ""},
            class_name="q-clip__btn q-clip__sound q-edit-preview__sound",
        ),
    )
    frame = rx.box(
        picture,
        rx.cond(
            has_video,
            rx.el.video(
                src=src,
                muted=True,
                plays_inline=True,
                preload="metadata",
                tab_index=-1,
                aria_hidden="true",
                custom_attrs={"data-edit-video": ""},
                class_name="q-edit-preview__video",
            ),
        ),
        rx.foreach(effect_srcs, _effect_layer),
        rx.cond(
            text != "",
            rx.box(
                rx.el.p(text, class_name="q-edit-preview__text-line"),
                class_name="q-edit-preview__text",
                custom_attrs={
                    "data-place": place,
                    "data-layout": text_layout,
                    "data-long": rx.cond(text_long, "true", "false"),
                },
            ),
        ),
        rx.cond(has_video, controls),
        class_name="q-edit-preview__frame",
        custom_attrs={"data-rotate": rotate.to(str)},
    )
    note = rx.hstack(
        rx.cond(
            has_video,
            rx.fragment(
                rx.el.span(
                    custom_attrs={"data-edit-time": ""},
                    class_name="q-edit-preview__time q-nums",
                ),
                rx.text("·", size="1", color=T.TEXT_MUTED, aria_hidden="true"),
            ),
        ),
        rx.text(note_text, size="1", color=T.TEXT_MUTED),
        spacing="1",
        align="center",
        justify="center",
        wrap="wrap",
        width="100%",
        class_name="q-edit-preview__note",
    )
    status_line = note if undo is None else rx.cond(undo_on, undo, note)
    return rx.box(
        frame,
        rx.vstack(
            status_line,
            rx.cond(
                has_video & slower,
                rx.text(slower_text, size="1", color=T.TEXT_MUTED, text_align="center"),
            ),
            rx.cond(
                remote,
                rx.text(remote_text, size="1", color=T.TEXT_MUTED, text_align="center"),
            ),
            # always mounted: only the script's «broken» (a real playback error) shows it;
            # a polite status, so a screen reader hears it once
            rx.el.p(broken_text, role="status", class_name="q-edit-preview__broken"),
            spacing="1",
            align_items="center",
            width="100%",
        ),
        _duration_trigger(on_duration),
        _resolve_trigger(on_resolve),
        role="region",
        aria_label=region_label,
        custom_attrs={
            "data-edit-preview": "",
            "data-edit-key": video_key,
            "data-edit-start": start.to(str),
            "data-edit-end": end.to(str),
            "data-edit-speed": speed.to(str),
            "data-edit-rate": rate.to(str),
            "data-edit-focus": focus,
            "data-edit-play": play_nonce.to(str),
            "data-edit-known": rx.cond(known, "true", "false"),
            "data-edit-pending": rx.cond(pending, "true", "false"),
        },
        class_name="q-edit-preview",
    )


__all__ = ["REPORT_GLOBAL", "SCRIPT", "edit_preview", "edit_preview_script"]
