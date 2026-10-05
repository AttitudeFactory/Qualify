"""Lottie in Reflex, at zero cost (docs/ux-post-journey-termico.md §3).

Wraps ``LottieLight`` from `lottie-react` (MIT) — the SVG-only, expression-free build of
the engine, which is all a hand-made shape animation needs and ~45 KB gzipped instead
of ~90 KB for the full `lottie-web`. The npm dependency is declared on the component
(``library`` + ``lib_dependencies``), so `reflex` installs it with the rest of the
frontend; nobody runs `bun add` by hand.

Three rules the helper enforces, so a screen cannot get them wrong:

* **Deferred.** ``NoSSRComponent``: the engine chunk is a lazy ``import()`` that only
  loads when the first animation mounts — a page without one pays nothing.
* **Reduced motion is a static icon, not a frozen frame.** ``lottie(...)`` always renders
  the fallback (a lucide icon) next to the animation; ``assets/qualify.css`` shows one
  or the other through ``prefers-reduced-motion``. No JS media query, no flash.
* **Decorative.** ``aria-hidden`` on the animation; the word next to it carries the
  meaning (design-system P1: a state is colour + glyph + word, never the glyph alone).

Verified 2026-10-05 against lottie-react 3.1.2's shipped ``build/index.d.ts``: named
exports ``Lottie`` (full engine), ``LottieSvg``, ``LottieLight``; props ``src`` (path or
parsed object), ``loop`` (bool | int), ``autoplay``, ``speed``, ``direction``
("forward" | "reverse"), ``segment``, ``lottieRef``, ``subscriptions``; standard HTML
attributes land on the rendered ``div``. Peer deps react ^18.2 || ^19 (Reflex 0.9.7
ships React 19.2).
"""

from __future__ import annotations

import reflex as rx

from . import tokens as T

#: Pinned on purpose (docs/design-system.md §9.2 and the Reflex wrapping guide both ask
#: for a pin): a minor bump of either package is a deliberate change, not a surprise.
LOTTIE_REACT = "lottie-react@3.1.2"
LOTTIE_WEB = "lottie-web@5.13.0"

Direction = str  # "forward" | "reverse"


class LottieLight(rx.NoSSRComponent):
    """`LottieLight` from lottie-react: SVG renderer, no expression engine, lazily
    imported on the client."""

    library = LOTTIE_REACT
    lib_dependencies: list[str] = [LOTTIE_WEB]
    tag = "LottieLight"

    #: Path (served from ``assets/``, e.g. ``/lottie/flame.json``) or URL of the file.
    src: rx.Var[str]
    #: ``True`` forever, ``False`` once. (lottie-react also takes a repeat count.)
    loop: rx.Var[bool]
    autoplay: rx.Var[bool]
    #: Playback rate; ``1`` is the file's own.
    speed: rx.Var[float]
    #: ``"forward"`` or ``"reverse"``. **Do not rely on a reversed autoplay**: verified
    #: 2026-10-05 against lottie-react 3.1.2 + lottie-web 5.13 — on load the engine starts
    #: at frame 0 and only then gets ``setDirection(-1)``, so it is "finished" before it
    #: draws; and ``initialSegment`` with a descending range draws nothing at all. A
    #: backwards animation ships as its own file (``lottie_shapes.thaw``).
    direction: rx.Var[str]


def lottie(
    src: str | rx.Var[str],
    *,
    loop: bool = False,
    autoplay: bool = True,
    size: str = "1.5rem",
    reduced_motion_fallback: str = "circle",
    direction: Direction = "forward",
    speed: float = 1.0,
    tone: str = "neutral",
    class_name: str = "",
) -> rx.Component:
    """One animation, with its reduced-motion twin.

    ``src`` is the file under ``assets/lottie/``; ``size`` is the square it draws in;
    ``reduced_motion_fallback`` is the lucide icon shown instead when the viewer asked
    for less motion, coloured in ``tone`` so the fallback matches the animation's own
    colour. Both are always in the DOM: ``.q-lottie`` / ``.q-lottie-static`` decide which
    one is visible (``assets/qualify.css``, "Lottie").
    """
    animation = rx.box(
        LottieLight.create(
            src=src,
            loop=loop,
            autoplay=autoplay,
            speed=speed,
            direction=direction,
            style={"width": size, "height": size},
            aria_hidden="true",
        ),
        class_name=f"q-lottie {class_name}".strip(),
        width=size,
        height=size,
        min_width=size,
        line_height="0",
    )
    static = rx.box(
        rx.icon(reduced_motion_fallback, size=_icon_px(size), color=T.tone_color(tone, 9)),
        class_name="q-lottie-static",
        width=size,
        height=size,
        min_width=size,
        aria_hidden="true",
    )
    return rx.fragment(animation, static)


def _icon_px(size: str) -> int:
    """A lucide size that sits inside a ``size`` box: rem → px at 16, px as given, else
    the badge icon size. The static twin must not be bigger than the animation it
    replaces."""
    try:
        if size.endswith("rem"):
            return max(T.ICON_SM, round(float(size[:-3]) * 16 * 0.8))
        if size.endswith("px"):
            return max(T.ICON_SM, round(float(size[:-2]) * 0.8))
    except ValueError:
        pass
    return T.ICON_SM
