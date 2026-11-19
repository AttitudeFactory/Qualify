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
by the script, in the final video's time).
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


# -- ED-01b m-25029106: the preview in sequence ----------------------------------------

#: The pure clock the sequence engine uses (`window.__qEditSeqCore`, tested with node).
SEQ_CORE_SCRIPT = "edit-sequence-core.js"
#: The global the script fills before pressing the hidden time button.
TIME_GLOBAL = "window.__qEditSeqTime"


def edit_sequence_script() -> rx.Component:
    """Mount the sequence's clock and `assets/edit-preview.js` (sequence mode included);
    both guard against running twice — a second run only attaches new previews."""
    script = asset_script(SEQ_CORE_SCRIPT) + ";" + asset_script(SCRIPT)
    return rx.box(display="none", on_mount=rx.call_script(script))


def _time_trigger(on_time: object) -> rx.Component:
    """The hidden button the script presses on a PAUSE and after a SEEK (never per
    frame): the handler receives `(t, reason)` — «pause» or «seek»."""
    t = rx.Var(f"Number(({TIME_GLOBAL} || {{}}).t || 0)", _var_type=float)
    reason = rx.Var(f"String(({TIME_GLOBAL} || {{}}).reason || '')", _var_type=str)
    return rx.el.button(
        type="button",
        on_click=on_time(t, reason),  # type: ignore[operator]
        tab_index=-1,
        aria_hidden="true",
        display="none",
        custom_attrs={"data-edit-seq-time-trigger": ""},
    )


def _seq_text(row: rx.Var) -> rx.Component:
    """A text of the sequence: hidden until the script marks it on (`data-on`)."""
    return rx.box(
        rx.el.p(row["text"], class_name="q-edit-preview__text-line"),
        class_name="q-edit-preview__text q-edit-seq__overlay",
        custom_attrs={
            "data-place": row["place"],
            "data-layout": "scrim",
            "data-long": "false",
            "data-seq-text": row["index"],
        },
    )


def _seq_effect(row: rx.Var) -> rx.Component:
    """An effect's loop (only when its file exists), shown while it is on."""
    return rx.cond(
        row["url"] != "",
        rx.el.video(
            src=row["url"],
            muted=True,
            loop=True,
            plays_inline=True,
            preload="auto",
            tab_index=-1,
            aria_hidden="true",
            custom_attrs={"data-edit-effect": "", "data-seq-effect": row["index"]},
            class_name="q-edit-preview__effect q-edit-seq__overlay",
        ),
    )


def edit_sequence_preview(
    *,
    sequence: rx.Var[str],
    texts: rx.Var[list[dict[str, str]]],
    effects: rx.Var[list[dict[str, str]]],
    slower: rx.Var[bool],
    on_duration: object,
    on_time: object,
    note_text: str,
    broken_text: str,
    slower_text: str,
    play_label: str,
    pause_label: str,
    sound_label: str,
    mute_label: str,
    region_label: str,
    clock: bool = True,
) -> rx.Component:
    """The preview of a whole video in order (ED-01b): `sequence` is
    `edit_sequence.PreviewSequence.to_json()`; `texts`/`effects` its overlays as rows
    (`text`, `place`, `url`, `index` — strings), drawn here and switched on and off by
    the script on the final video's clock. Two `<video>` take turns (the next one is
    preloaded), a photo is an `<img>`, a block with nothing to show (or a failed video) a
    card with its name — and `broken_text` when it failed. Put it and a `timeline` in
    one `[data-edit-sync]` box and their clocks are one. The sound button says
    `sound_label` while muted and `mute_label` while the sound is on (the script swaps
    them, like ▶/❚❚). The single-stretch `edit_preview` is unchanged.

    ``clock`` False (ED-10's editor): no «{t} de {total}» under the frame — the linked
    timeline's clock over the tracks is the only one; with ``note_text`` "" too, the
    line under the frame is not drawn at all (the frame gets its height)."""
    layer = "q-edit-preview__video q-edit-seq__layer"
    frame = rx.box(
        rx.image(
            alt="",
            class_name="q-edit-preview__poster q-edit-seq__layer",
            custom_attrs={"data-edit-seq-photo": ""},
        ),
        rx.el.div(
            class_name="q-edit-seq__card q-edit-seq__layer",
            custom_attrs={"data-edit-seq-card": ""},
        ),
        *(
            rx.el.video(
                muted=True,
                plays_inline=True,
                preload="auto",
                tab_index=-1,
                aria_hidden="true",
                custom_attrs={"data-edit-seq-video": name},
                class_name=layer,
            )
            for name in ("a", "b")
        ),
        rx.foreach(effects, _seq_effect),
        rx.foreach(texts, _seq_text),
        # the notice is announced when it appears: its live region is always rendered
        rx.el.div(
            rx.el.p(
                broken_text,
                class_name="q-edit-seq__broken q-edit-seq__overlay",
                custom_attrs={"data-edit-seq-broken": ""},
            ),
            aria_live="polite",
            class_name="q-edit-seq__live",
        ),
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
            custom_attrs={"data-edit-sound": "", "data-mute-label": mute_label},
            class_name="q-clip__btn q-clip__sound q-edit-preview__sound",
        ),
        class_name="q-edit-preview__frame",
    )
    time = (
        [
            rx.el.span(
                custom_attrs={"data-edit-seq-time": ""},
                class_name="q-edit-preview__time q-nums",
            ),
            # « · » only once the clock has a time (CSS: an empty time hides it)
            rx.text(
                "·", size="1", color=T.TEXT_MUTED, aria_hidden="true", class_name="q-edit-seq__dot"
            ),
        ]
        if clock
        else []
    )
    note = (
        [
            rx.hstack(
                *time,
                *([rx.text(note_text, size="1", color=T.TEXT_MUTED)] if note_text else []),
                spacing="1",
                align="center",
                justify="center",
                wrap="wrap",
                width="100%",
            )
        ]
        if clock or note_text
        else []
    )
    return rx.box(
        frame,
        *note,
        rx.cond(slower, rx.text(slower_text, size="1", color=T.TEXT_MUTED, text_align="center")),
        _duration_trigger(on_duration),
        _time_trigger(on_time),
        role="region",
        aria_label=region_label,
        custom_attrs={"data-edit-seq-host": "", "data-edit-seq": sequence},
        class_name="q-edit-preview q-edit-seq",
    )


__all__ = [
    "REPORT_GLOBAL",
    "SCRIPT",
    "SEQ_CORE_SCRIPT",
    "edit_preview",
    "edit_preview_script",
    "edit_sequence_preview",
    "edit_sequence_script",
]
