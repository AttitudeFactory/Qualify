"""Compose: the owner's texts over an assembled video (EF-05, m-25026573; D1 of ADR 50).

The stage after the video is assembled (EF-06's prepare → speed → still photos → concat):
up to `TEXT_LAYERS_MAX` texts (`VideoTextLayer`), each drawn by the render service as a
transparent PNG with ADR 49's closed designs (`qualify_creative.render.video_text`, the
`layer_still` engine and components — no second drawing path, no Pillow text) and laid over
the frames it shows on by PyAV (`qualify_creative.video.text_overlay`), with a fade in.

ED-13 (m-25029108): each text enters and leaves as the owner chose (`VideoTextLayer.motion_in`
/`motion_out`: fade, slide, zoom; «Letra por letra» entering; «De golpe» leaving), each motion
at most a third of its time on screen, on one of four backgrounds (`layout_id`), in the Brand
Kit's own font file when the producer hands one (`render.video_text.BrandText`; a file that
is not a usable font was already dropped for its family, recorded as `font_file_rejected`).

Public API (EF-06 calls it at its `# EF-05` hook)::

    result = compose_text_layers(
        video_path, out_path, text_layers, brand, render_client=client_or_factory
    )
    result.path      # the video to keep: `out_path` when composed, `video_path` when not
    result.composed  # False when there is no text: nothing was rendered nor written
    result.params    # provenance to merge into the piece's params (`text_layers` key)

- `text_layers`: the part's (or Clip's) `VideoTextLayer`s, times in SECONDS OF THE ASSEMBLED
  VIDEO'S OUTPUT from its first frame (speed already applied) — the recipe's own times. An
  `end_s` past the video's end just lasts until the end.
- `brand`: the tenant's `BrandKit` (its `typeface` is the face drawn, as in the images), or
  the CONTRACT §2 brand mapping.
- `render_client`: a `RemotionRenderClient`, or a no-argument callable that builds one
  (called only when there is a text).

Failures (each one leaves `out_path` absent and `video_path` untouched, so the owner keeps
what they had; no AI provider is called, the cost is 0):

- `ComposeUnavailable` — the render service is down, timed out or failed: the piece fails
  WITHOUT charging (ADR 49 §6: a composition that cannot run never takes a creation), with
  `OWNER_MESSAGE_UNAVAILABLE`, which does not blame the owner. `transient` = retry later.
- `ComposeRejected` (a `ComposeUnavailable` with `transient` False) — the service rejected
  what we sent (a 422 that is not a refusal of the text): our bug; `OWNER_MESSAGE_REJECTED`
  promises no retry.
- `TextLayerRefused` — the service cannot draw one text in its place (a word wider than the
  screen); `index` says which text. Retrying the same text gives the same answer.
- `qualify_creative.video.text_overlay.TextOverlayError` — the assembled video itself is
  unreadable or not 9:16 (a pipeline bug, not the owner's).

Determinism: the PNG of a text is a pure function of (text, place, design, brand fonts and
palette, the two pixel revisions) — its render job id is too —, and the overlay encodes on one
thread: the same video and recipe give the same decoded frames (`decoded_frame_hashes`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qualify_creative.render.client import RemotionRenderClient, RenderServiceError
from qualify_creative.render.video_text import (
    VideoTextImage,
    VideoTextRefused,
    VideoTextRequest,
    brand_props,
    heading_font_of,
    render_video_text,
)
from qualify_creative.schemas import (
    VIDEO_TEXT_FADE_DEFAULT_S,
    VIDEO_TEXT_MOTION_MAX_SHARE,
    VIDEO_TEXT_TYPEWRITER_S_PER_CHAR,
    VideoTextLayer,
)
from qualify_creative.video.text_overlay import (
    OVERLAY_X264,
    LetterReveal,
    TimedLayer,
    overlay_text_layers,
)

#: The version of this stage (how texts become pixels over a video): bumped with any change
#: to the timing, the fade or the overlay that moves a pixel. Recorded with every piece.
#: v2 (m-25042483): the decoder bounded and x264's lookahead shortened (`OVERLAY_X264`),
#: so a 4K piece with texts stays under the creative worker's memory budget.
#: v3 (ED-13, m-25029108): entrances and exits (fade, slide, zoom, letter by letter), each
#: at most a third of the text's time on screen (it was half, for the fade in); the four
#: backgrounds and the Brand Kit's font file are the render's (`video_text` v2).
COMPOSE_VERSION = "video_text_compose-v3"
#: «Letra por letra»: the background appears whole as the first letter does, with a short
#: fade of at most this many seconds (never longer than the typing itself).
TYPEWRITER_BACKDROP_FADE_S = 0.2
#: The fade in of a text that does not choose one, in seconds. Deivid, 2026-11-16 («Que el
#: dueño elija»): each text carries its own `VideoTextLayer.fade_s`, 0.3-1.0 s (the ticket's
#: «fundido de entrada de 0,3 a 1,0 s»), 0.5 s by default — this is that default. ED-13: a
#: text shown for less than three times its fade enters (and leaves) in a third of its time
#: instead (`fade_in_seconds`, `fade_out_seconds`). The fade is PyAV's
#: alpha ramp only: it never reaches the render, so the PNG (and its job id) do not depend
#: on it; the per-text provenance records it.
FADE_IN_SECONDS = VIDEO_TEXT_FADE_DEFAULT_S
#: How long one text may wait for its render (the service draws one still in ~1-3 s).
RENDER_TIMEOUT_SECONDS = 180.0

#: What the owner reads when the render service could not draw the texts: the problem is ours,
#: nothing they did, and nothing was charged.
OWNER_MESSAGE_UNAVAILABLE = (
    "No pudimos poner los textos sobre tu video en este momento. No se descontó de tus "
    "creaciones. Inténtalo de nuevo en unos minutos."
)
#: What the owner reads when the render service rejected what we sent (a 422 that is not a
#: refusal of the text): our fault, a retry would get the same answer, so none is promised.
OWNER_MESSAGE_REJECTED = (
    "No pudimos poner los textos sobre tu video por un problema de nuestra parte. "
    "No se descontó de tus creaciones."
)
#: What the owner reads when one text cannot be drawn in its place, naming it: a word wider
#: than the screen (`word_too_wide`, by far the likely one), or any other reason.
#: `{number}` is 1-based; `{text}` is the owner's own text.
OWNER_MESSAGE_WORD_TOO_WIDE = (
    "El texto {number} («{text}») tiene una palabra demasiado larga para la pantalla. "
    "Cámbiala por una más corta o pártela en dos, y vuelve a intentarlo."
)
OWNER_MESSAGE_REFUSED = (
    "El texto {number} («{text}») no cabe en la pantalla. Acórtalo y vuelve a intentarlo."
)

RenderClientFactory = Callable[[], RemotionRenderClient]


class ComposeUnavailable(Exception):
    """The render service could not draw the texts (down, timed out, failed). The piece
    fails without charging; `owner_message` is what the owner reads."""

    code = "text_layer_unavailable"
    charge = False

    def __init__(
        self,
        detail: str,
        *,
        service_code: str | None = None,
        transient: bool = True,
        outage: bool = False,
    ):
        super().__init__(detail)
        self.detail = detail
        self.service_code = service_code
        self.transient = transient
        #: EF-14: the service did not answer (transport, 502/503/504, a timeout) — the
        #: only failure a queued Seedance clip waits for (`_passing`); `transient` keeps
        #: its EF-05 meaning (the owner may try again)
        self.outage = outage
        self.owner_message = OWNER_MESSAGE_UNAVAILABLE


class ComposeRejected(ComposeUnavailable):
    """The render service rejected what we sent (``invalid_parameters`` without a refusal of
    the text — a design v1 does not draw, a stale catalog version): our bug, NOT transient —
    retrying gives the same answer. Also fails without charging."""

    code = "text_layer_rejected"

    def __init__(self, detail: str, *, service_code: str | None = None) -> None:
        super().__init__(detail, service_code=service_code, transient=False)
        self.owner_message = OWNER_MESSAGE_REJECTED


class TextLayerRefused(Exception):
    """Text number `index` (0-based, in the order given) cannot be drawn in its place:
    `reason` is the service's (`word_too_wide`, `title_does_not_fit`, `outside_safe_zone`)."""

    code = "text_layer_refused"
    charge = False

    def __init__(self, index: int, reason: str, detail: str, text: str = "") -> None:
        super().__init__(f"text {index}: {reason} {detail}".strip())
        self.index = index
        self.reason = reason
        self.detail = detail
        self.text = text
        template = (
            OWNER_MESSAGE_WORD_TOO_WIDE if reason == "word_too_wide" else OWNER_MESSAGE_REFUSED
        )
        self.owner_message = template.format(number=index + 1, text=" ".join(text.split()))


@dataclass(frozen=True)
class ComposeResult:
    path: Path
    composed: bool
    params: Mapping[str, Any] = field(default_factory=dict)


def _shown_until(layer: VideoTextLayer, video_seconds: float | None) -> float | None:
    """When the text stops showing: its `end_s`, or the video's end when that comes first
    (None: neither is known)."""
    ends = [e for e in (layer.end_s, video_seconds) if e is not None]
    return min(ends) if ends else None


def _capped(seconds: float, layer: VideoTextLayer, video_seconds: float | None) -> float:
    """`seconds`, at most `VIDEO_TEXT_MOTION_MAX_SHARE` (a third) of the text's time on
    screen (ED-13; the fade in used to take up to half)."""
    end = _shown_until(layer, video_seconds)
    if end is None:
        return seconds
    share = (end - layer.start_s) * VIDEO_TEXT_MOTION_MAX_SHARE
    return round(max(0.0, min(seconds, share)), 6)


def fade_in_seconds(layer: VideoTextLayer, video_seconds: float | None = None) -> float:
    """How long the text takes to enter: its own `fade_s` («Aparece», «Sube», «Crece»), or
    for «Letra por letra» `VIDEO_TEXT_TYPEWRITER_S_PER_CHAR` per character — at most a third
    of its time on screen (until its `end_s`, or the video's end when that comes first)."""
    if layer.motion_in == "typewriter":
        typing = len(layer.text.strip()) * VIDEO_TEXT_TYPEWRITER_S_PER_CHAR
        return _capped(typing, layer, video_seconds)
    return _capped(layer.fade_s, layer, video_seconds)


def fade_out_seconds(layer: VideoTextLayer, video_seconds: float | None = None) -> float:
    """How long the text takes to leave (ED-13): 0 for «De golpe» (`none`), else its own
    `fade_s` — at most a third of its time on screen. 0 too when its end is not known."""
    if layer.motion_out == "none" or _shown_until(layer, video_seconds) is None:
        return 0.0
    return _capped(layer.fade_s, layer, video_seconds)


def _letter_boxes(report: Mapping[str, Any]) -> tuple[tuple[float, float, float, float, int], ...]:
    boxes = report.get("letter_boxes")
    if not isinstance(boxes, list):
        return ()
    try:
        return tuple(
            (float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"]), int(b["line"]))
            for b in boxes
        )
    except (KeyError, TypeError, ValueError):
        return ()


def _font_record(brand: Any) -> dict[str, Any]:
    """ED-13: a Brand Kit font file the producer could not use (not a font FreeType draws):
    recorded, its family drew the text instead (the piece never fails for it)."""
    if getattr(brand, "font_rejected", False) is True:
        return {"font_file_rejected": True}
    return {}


def _typed_ready(image: VideoTextImage) -> bool:
    """A drawn image «Letra por letra» can lay: its background and letters apart, with every
    character's box (a PNG kept from a preview has only the whole layer)."""
    return (
        image.backdrop_png is not None
        and image.letters_png is not None
        and bool(_letter_boxes(image.report))
    )


def _timed_layers(
    layer: VideoTextLayer, image: VideoTextImage, video_seconds: float | None
) -> list[TimedLayer]:
    """The overlay's layers for one drawn text: one, or for «Letra por letra» two — the
    background (a short fade in) under the letters (typed one by one)."""
    fade_in = fade_in_seconds(layer, video_seconds)
    fade_out = fade_out_seconds(layer, video_seconds)
    end_s = layer.end_s
    motion_out = layer.motion_out
    leaves = _shown_until(layer, video_seconds)
    if motion_out != "none" and fade_out > 0 and leaves is not None and leaves > layer.start_s:
        end_s = leaves  # an animated exit ends where the text stops showing
    else:
        motion_out, fade_out = "none", 0.0
    box = image.report.get("text_box")
    center = None
    if isinstance(box, Mapping):
        try:
            center = (float(box["x"]) + float(box["w"]) / 2, float(box["y"]) + float(box["h"]) / 2)
        except (KeyError, TypeError, ValueError):
            center = None
    common: dict[str, Any] = {
        "start_s": layer.start_s,
        "end_s": end_s,
        "motion_out": motion_out,
        "fade_out_s": fade_out,
        "center": center,
    }
    if layer.motion_in != "typewriter":
        return [TimedLayer(png=image.png, fade_in_s=fade_in, motion_in=layer.motion_in, **common)]
    assert image.backdrop_png is not None and image.letters_png is not None
    return [
        TimedLayer(
            png=image.backdrop_png,
            fade_in_s=round(min(TYPEWRITER_BACKDROP_FADE_S, fade_in), 6),
            motion_in="fade",
            **common,
        ),
        TimedLayer(
            png=image.letters_png,
            fade_in_s=0.0,
            motion_in="typewriter",
            reveal=LetterReveal(boxes=_letter_boxes(image.report), duration_s=fade_in),
            **common,
        ),
    ]


def _client(render_client: RemotionRenderClient | RenderClientFactory) -> RemotionRenderClient:
    if isinstance(render_client, RemotionRenderClient):
        return render_client
    if callable(render_client):
        try:
            return render_client()
        except Exception as exc:  # noqa: BLE001 — no client = no render: as a service down
            # our configuration, not a passing outage: never waited for (EF-14, `outage`)
            raise ComposeUnavailable(f"render client could not be built: {exc}") from exc
    return render_client  # a duck-typed client (tests)


def _draw(
    client: RemotionRenderClient, index: int, request: VideoTextRequest, timeout: float
) -> VideoTextImage:
    try:
        return render_video_text(client, request, timeout_seconds=timeout)
    except VideoTextRefused as exc:
        raise TextLayerRefused(index, exc.reason, exc.detail, request.text) from exc
    except RenderServiceError as exc:
        detail = f"text {index}: render service {exc.code}: {exc.message}"
        if exc.code == "invalid_parameters" or exc.status == 422:
            raise ComposeRejected(detail, service_code=exc.code) from exc
        raise ComposeUnavailable(detail, service_code=exc.code, outage=_passing(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — unreachable service (httpx.TransportError…)
        raise ComposeUnavailable(
            f"text {index}: render service unreachable: {exc}", outage=_passing(exc)
        ) from exc


#: HTTP statuses that mean «nobody answered» (a proxy in front of a service that is down),
#: as `image_pipeline.compose_run._OUTAGE_STATUSES`.
_OUTAGE_STATUSES = frozenset({502, 503, 504})


def _passing(exc: BaseException) -> bool:
    """EF-14: whether a render failure is an outage that may pass by itself — the service
    did not answer (transport, 502/503/504) or ran too long (`RenderTimeout`), like
    `compose_run._kind`'s `outage`. Anything else (a 4xx, a failed job, our own bug) is not:
    waiting for it would only delay the same answer."""
    from qualify_creative.render.client import RenderTimeout  # noqa: PLC0415

    if isinstance(exc, RenderTimeout):
        return True
    if isinstance(exc, RenderServiceError):
        return exc.status in _OUTAGE_STATUSES
    if isinstance(exc, ConnectionError | TimeoutError):
        return True
    try:
        import httpx  # noqa: PLC0415
    except ImportError:  # pragma: no cover — httpx comes with the render client
        return False
    return isinstance(exc, httpx.TransportError)


def _file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:  # the overlay reports a missing or unreadable file itself
        return None
    return digest.hexdigest()


def _video_seconds(path: Path) -> float | None:
    import av  # noqa: PLC0415

    try:
        with av.open(str(path)) as source:
            stream = source.streams.video[0]
            if stream.duration is not None:
                return float(stream.duration * stream.time_base)
            if source.duration is not None:
                return source.duration / 1_000_000
    except Exception:  # noqa: BLE001 — the overlay reports an unreadable file itself
        return None
    return None


def draw_text_layers(
    text_layers: Sequence[VideoTextLayer],
    brand: Any,
    *,
    render_client: RemotionRenderClient | RenderClientFactory,
    timeout_seconds: float = RENDER_TIMEOUT_SECONDS,
) -> tuple[VideoTextImage, ...]:
    """Every text drawn by the render service, in order, nothing encoded. EF-14: a piece
    made by Seedance draws its texts BEFORE the vendor is paid, so a text that does not
    fit, or a render service that is down, costs the owner nothing. Raises what
    `compose_text_layers` raises for a text; with no text no client is built."""
    layers = tuple(text_layers)
    if not layers:
        return ()
    client = _client(render_client)
    return tuple(
        _draw(client, index, _request(layer, brand), timeout_seconds)
        for index, layer in enumerate(layers)
    )


def _request(layer: VideoTextLayer, brand: Any) -> VideoTextRequest:
    """What the render service is asked for one text. ED-13: in the Brand Kit's font file
    when the producer handed one (`render.video_text.BrandText`), and «Letra por letra»
    with its background and letters apart; «Franja» / «Recuadro de tu color» in the colour
    the owner picked (`VideoTextLayer.effective_box_color`, None = the default)."""
    return VideoTextRequest(
        text=layer.text,
        place=layer.place,
        brand=brand_props(brand),
        layout_id=str(layer.layout_id) if layer.layout_id is not None else None,
        layout_version=layer.layout_version,
        font=heading_font_of(brand),
        letters=layer.motion_in == "typewriter",
        box_color=layer.effective_box_color,
        # ED-13 round 3: «Sin fondo»'s letters in the colour picked (None = white)
        text_color=layer.effective_text_color,
        # ED-13 round 4: the letters' size («Mediana» = what v1 draws)
        text_size=layer.text_size,
    )


def compose_text_layers(
    video_path: Path | str,
    out_path: Path | str,
    text_layers: Sequence[VideoTextLayer],
    brand: Any,
    *,
    render_client: RemotionRenderClient | RenderClientFactory,
    timeout_seconds: float = RENDER_TIMEOUT_SECONDS,
    effect_layers: Sequence[Any] = (),
    drawn_images: Sequence[VideoTextImage] | None = None,
) -> ComposeResult:
    """The texts over `video_path`, written to `out_path` (see the module's docstring).
    Every text is drawn BEFORE anything is encoded: a render failure writes nothing.

    `effect_layers` (EF-08): the library's layers (`layer_overlay.TimedEffectLayer`) laid
    UNDER the texts in the same single pass (`overlay_layers_and_texts`: one decode, one
    encode). Only with texts: with no text nothing runs here and the caller lays the
    layers itself. A layer problem raises `LayerOverlayError` as it is.

    `drawn_images` (EF-14): the texts already drawn by `draw_text_layers`, one per text
    in the same order; nothing is asked of the render service again."""
    video_path, out_path = Path(video_path), Path(out_path)
    layers = tuple(text_layers)
    if not layers:
        # no text: the stage does not run (the output is exactly the input)
        return ComposeResult(path=video_path, composed=False, params={})
    images = (
        tuple(drawn_images)
        if drawn_images is not None
        else draw_text_layers(
            layers, brand, render_client=render_client, timeout_seconds=timeout_seconds
        )
    )
    if len(images) != len(layers):
        raise ValueError("compose_text_layers: one drawn image per text")
    # ED-13: «Letra por letra» needs its background and letters apart; an image kept from a
    # preview carries only the whole layer — that text is drawn again (our service, cost 0)
    redraw = [
        i
        for i, (lay, img) in enumerate(zip(layers, images, strict=True))
        if (lay.motion_in == "typewriter" and not _typed_ready(img))
    ]
    if redraw:
        client = _client(render_client)
        fresh = list(images)
        for index in redraw:
            fresh[index] = _draw(client, index, _request(layers[index], brand), timeout_seconds)
        images = tuple(fresh)
    source_sha256 = _file_sha256(video_path)
    seconds = _video_seconds(video_path)
    drawn: list[tuple[VideoTextLayer, VideoTextImage, float, float]] = [
        (layer, image, fade_in_seconds(layer, seconds), fade_out_seconds(layer, seconds))
        for layer, image in zip(layers, images, strict=True)
    ]
    timed = [
        timed_layer
        for layer, image, _in, _out in drawn
        for timed_layer in _timed_layers(layer, image, seconds)
    ]
    if effect_layers:
        from qualify_creative.video import layer_overlay  # noqa: PLC0415

        result = layer_overlay.overlay_layers_and_texts(
            video_path, out_path, tuple(effect_layers), timed
        )
    else:
        result = overlay_text_layers(video_path, out_path, timed)
    params = {
        "text_layers": {
            "compose_version": COMPOSE_VERSION,
            "source_sha256": source_sha256,
            "fade_default_s": FADE_IN_SECONDS,
            "x264": dict(OVERLAY_X264),
            "cost_usd": "0",
            "frames": result.frames,
            "fps": result.fps,
            "size": [result.width, result.height],
            "layers": [
                {
                    **dict(image.provenance),
                    "place": layer.place,
                    "start_s": layer.start_s,
                    "end_s": layer.end_s,
                    # the fade the owner chose, and the one applied (shorter on a brief text)
                    "fade_s": layer.fade_s,
                    "fade_in_s": fade,
                    # ED-13: how it entered and left, and how long the exit took
                    "motion_in": layer.motion_in,
                    "motion_out": layer.motion_out,
                    "fade_out_s": fade_out,
                    "text_sha256": hashlib.sha256(layer.text.strip().encode("utf-8")).hexdigest(),
                    "png_sha256": hashlib.sha256(image.png).hexdigest(),
                    "lines": list(image.report.get("lines") or []),
                    "size_px": image.report.get("size"),
                    "cover": image.report.get("cover"),
                    **_font_record(brand),
                }
                for layer, image, fade, fade_out in drawn
            ],
        }
    }
    return ComposeResult(path=result.path, composed=True, params=params)


__all__ = [
    "COMPOSE_VERSION",
    "FADE_IN_SECONDS",
    "OWNER_MESSAGE_REFUSED",
    "OWNER_MESSAGE_UNAVAILABLE",
    "OWNER_MESSAGE_WORD_TOO_WIDE",
    "OWNER_MESSAGE_REJECTED",
    "ComposeRejected",
    "ComposeResult",
    "ComposeUnavailable",
    "RenderClientFactory",
    "TextLayerRefused",
    "compose_text_layers",
    "draw_text_layers",
    "fade_in_seconds",
    "fade_out_seconds",
]
