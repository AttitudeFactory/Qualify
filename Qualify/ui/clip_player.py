"""`clip_player` — a stretch of a video played in its own picture, in place (m-24992893,
m-24992894).

The picture (a scene of the original reel, a part's poster) stays as it is with a round
▶ in its middle. Tapping ▶ plays the video IN THE SAME FRAME — muted, with a sound
toggle in the bottom-right corner — and the frame never grows or moves. Tapping the
playing video pauses it and the picture comes back with its ▶. A stretch (`start`,
`end`, in seconds) plays only that stretch and stops at its end, no loop.

Everything that moves is the browser's (`assets/clip-player.js`, mounted ONCE per screen
with `clip_player_script()`): a server poll that re-renders the rows never restarts what
is being watched, because

- the video's address is a `data-clip-src` attribute, not the `<video>`'s `src`: the
  script hands it to the `<video>` only on ▶ (`preload="none"` until then — nothing is
  downloaded for a scene nobody plays), so a new address on a later render (a renewed
  token) waits for the next ▶ instead of reloading the playing one;
- the playing / idle / broken state is a `data-clip-state` attribute React never
  renders, so a re-render leaves it alone;
- `key` (the row's stable id) makes React mount a new player when another part takes
  this row's place, never when the same part re-renders.

The script also: plays one video at a time on the page (a clip pauses any other video,
«Tu video completo» included, and any other video pauses the clips); stops a clip when
its picture is hidden (a folded list) or a drag starts (`slide-drag.js`); keeps ←/→ on
its buttons from reaching a list's keyboard; and when the video cannot be played (gone,
purged) puts the picture back WITHOUT ▶ for every clip of that same file, saying
`broken_text` once to screen readers when given.

States (`data-clip-state`): idle → loading (▶ dimmed and pulsing, the picture still
shown) → playing (from the video's `playing` event: never a black frame over the
scene while it waits) → idle; or broken. A screen may show the broken words as text
too (`clip_player_notice()`, under its list). A clip with `renew` (short-lived
`/r2media` addresses) does not break on its first error: it asks the screen for fresh
addresses (`clip_player_renew(event)`, a hidden button the script presses) and plays
again once its `data-clip-src` changes; only a second error on the new address breaks.

The video fills its frame like its picture (`object-fit: cover`), so it plays in the
same place the scene was.

Only design-system material: the `.q-thumb` frame (`framed`), the round black-alpha
buttons of the generator's stock previews (same size, colour and focus ring), tokens.
Screens: the parts of «Orden del clip» (step 2) and the rows «Para revisar» / «Lista» of
«Creando tus partes».
"""

from __future__ import annotations

import reflex as rx

from . import tokens as T
from .primitives import asset_script

#: The script's name under `assets/` (`clip_player_script`).
SCRIPT = "clip-player.js"

#: The sound toggle's accessible name; `aria-pressed` says whether the sound is on.
SOUND_LABEL = "Activar sonido"


def clip_player_script() -> rx.Component:
    """Mount `assets/clip-player.js` once on a screen that shows `clip_player`s (its
    guard keeps one set of listeners however many times it runs)."""
    return rx.box(display="none", on_mount=rx.call_script(asset_script(SCRIPT)))


def _glyph(icon: str, size: int) -> rx.Component:
    return rx.icon(icon, size=size, aria_hidden="true")


def _poster(poster: rx.Component | rx.Var[str] | str) -> rx.Component:
    """The still picture: a component as given, or a picture URL ("" → a film glyph)."""
    if isinstance(poster, rx.Component):
        return poster
    url = rx.Var.create(poster)
    return rx.cond(
        url != "",
        rx.image(src=url, alt="", width="100%", height="100%", object_fit="cover"),
        rx.center(
            _glyph("film", 20),
            width="100%",
            height="100%",
            color=T.TEXT_MUTED,
        ),
    )


def clip_player(
    poster: rx.Component | rx.Var[str] | str,
    *,
    src: rx.Var[str] | str,
    label: rx.Var[str] | str,
    pause_label: rx.Var[str] | str,
    start: rx.Var[str] | str = "",
    end: rx.Var[str] | str = "",
    broken_text: str = "",
    key: rx.Var[str] | str | None = None,
    framed: bool = False,
    small: bool = False,
    renew: bool = False,
    **props: object,
) -> rx.Component:
    """A picture that plays `src` in place.

    `poster`: what shows while nothing plays (a component, or a picture URL). `src`: the
    video's address, with its `#t=start,end` fragment when it plays a stretch; "" → no
    ▶ (render the picture alone instead when it is known to be ""). `label`: ▶'s name
    («Ver la parte 2 del original»); `pause_label`: the playing video's («Pausar la
    parte 2»). `start` / `end`: the stretch in seconds, as text ("" = the whole video).
    `broken_text`: said once when the file cannot be played ("" = silent). `framed`:
    the system's `.q-thumb` frame (else it fills its parent). `small`: the 2rem ▶ of a
    narrow picture. `renew`: a failed play asks for fresh addresses first (see the
    module docstring). Other props size the root."""
    host_attrs: dict[str, object] = {
        "data-clip": "",
        "data-clip-src": src,
        "data-clip-start": start,
        "data-clip-end": end,
    }
    if broken_text:
        host_attrs["data-clip-broken-text"] = broken_text
    if renew:
        host_attrs["data-clip-renew"] = ""
    if key is not None:
        props["key"] = key
    size = 14 if small else 22
    return rx.box(
        _poster(poster),
        rx.el.video(
            preload="none",
            muted=True,
            plays_inline=True,
            tab_index=-1,
            aria_hidden="true",
            custom_attrs={"data-clip-video": ""},
            class_name="q-clip__video",
        ),
        rx.el.button(
            _glyph("play", size),
            type="button",
            aria_label=label,
            title=label,
            custom_attrs={"data-clip-play": ""},
            class_name="q-clip__btn q-clip__play q-clip__play--sm"
            if small
            else ("q-clip__btn q-clip__play"),
        ),
        # the whole playing frame pauses it (a real button: the keyboard reaches it,
        # and `slide-drag.js` never lifts a card from a button)
        rx.el.button(
            rx.box(_glyph("pause", size), class_name="q-clip__pause-mark"),
            type="button",
            aria_label=pause_label,
            title=pause_label,
            custom_attrs={"data-clip-pause": ""},
            class_name="q-clip__pause",
        ),
        rx.el.button(
            rx.box(_glyph("volume-x", 14), class_name="q-clip__sound-off"),
            rx.box(_glyph("volume-2", 14), class_name="q-clip__sound-on"),
            type="button",
            aria_label=SOUND_LABEL,
            title=SOUND_LABEL,
            aria_pressed="false",
            custom_attrs={"data-clip-sound": ""},
            class_name="q-clip__btn q-clip__sound",
        ),
        custom_attrs=host_attrs,
        class_name="q-clip q-thumb" if framed else "q-clip",
        **props,
    )


def clip_player_notice() -> rx.Component:
    """Where the script writes a clip's `broken_text` as visible text (once per file),
    under the screen's list; empty (and not displayed) until then. The script fills the
    one nearest to the clip. A polite status: it is also what screen readers hear."""
    return rx.el.p(
        role="status",
        custom_attrs={"data-clip-notice": ""},
        class_name="q-clip-notice",
    )


def clip_player_renew(on_renew: object) -> rx.Component:
    """The hidden button a `renew` clip presses (through the script) when its address
    failed: `on_renew` must re-read the screen's addresses. Never shown, never in the
    reading order; the script presses the one nearest to the clip."""
    return rx.el.button(
        type="button",
        on_click=on_renew,
        tab_index=-1,
        aria_hidden="true",
        display="none",
        custom_attrs={"data-clip-renew-trigger": ""},
    )


__all__ = [
    "SCRIPT",
    "SOUND_LABEL",
    "clip_player",
    "clip_player_notice",
    "clip_player_renew",
    "clip_player_script",
]
