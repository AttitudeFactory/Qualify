"""The preview in sequence (ED-01b m-25029106): what the BROWSER needs to play a whole
video — every block in order on ONE clock, the final video's time — and nothing else.

This module never changes the recipe: it READS `editor_preview_contract` (the recipe v2
of ED-15) and the timeline's rows (`ui.timeline_vm`) and builds a `PreviewSequence`, a
plain, JSON-ready object the preview script (`assets/edit-preview.js`, sequence mode)
plays. It is never stored, never sent to the backend, and imports nothing from
`qualify_creative`.

Where each field comes from:

- From the recipe (`PartRecipe`, one part): each block in `segments` order — a video's
  `key`, `src_start`/`src_end` (`SourceSegment.start_s/end_s`), `speed` and `rotate`; a
  still photo (`SourceSegment.kind == "photo"`: from 0 to `end_s`, at speed 1) gives its
  `key`, `rotate` and `dur` (= `end_s - start_s`, 1–5 s). Its texts (`text_layers`, up to
  `TEXT_LAYERS_MAX`): `text`, `place`, `start`/`end` (`VideoTextLayer`, seconds of the
  part's output — one part, so the final video's); its effects' ids and `start`/`end`
  (`EffectUse`, `None` = the whole video).
- Browser-only (never in the recipe): each block's playable `url` (`PreviewSource.url`),
  its `poster`, and an effect's loop `url` and `blend` (`PreviewEffect`).

How `VideoRecipe.parts` and the media's parts line up is ED-07's: this module plays one
part's recipe (`from_recipe`) or the timeline's rows (`from_timeline`).

The clock: block `n` starts where block `n-1` ends (`out_start`/`out_end`, no gaps); a
video lasts `(src_end - src_start) / speed`, a photo its `dur`. Texts and effects show
while `start <= t < end`. The browser plays at most ×16 (`PREVIEW_RATE_MAX`): above it
the screen says the preview is slower (`slower`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from . import editor_preview_contract as contract

_PHOTO = "photo"
_VIDEO = "video"
_DECIMALS = 3


def _r(value: float) -> float:
    return round(float(value), _DECIMALS)


@dataclass(frozen=True)
class PreviewBlock:
    """One block of the «Fotos y videos» track, placed on the final video's clock.

    `kind` "video": `src_start`→`src_end` of `key`'s source at `speed`, turned `rotate`.
    `kind` "photo": `key`'s picture shown `dur` seconds, turned `rotate`. `url` "" = nothing the
    browser can load (the block is still timed: the sequence never stops on it)."""

    key: str
    kind: str
    out_start: float
    out_end: float
    url: str = ""
    poster: str = ""
    label: str = ""
    src_start: float = 0.0
    src_end: float = 0.0
    speed: float = 1.0
    rotate: int = 0
    dur: float = 0.0

    @property
    def seconds(self) -> float:
        return self.out_end - self.out_start


@dataclass(frozen=True)
class PreviewOverlay:
    """A text or an effect on the final video's clock: shown while
    `start <= t < end`. A text has `text`/`place`; an effect its `effect_id`, its
    loop (`url` "" = not drawn: the file does not exist yet) and its `opacity` — ED-04
    (m-25026627): the library's default intensity, which with the «screen» blend is
    what the final video's compose does (humo 0,6, brasas 0,5, vapor 0,5)."""

    kind: str  # "text" | "effect"
    start: float
    end: float
    text: str = ""
    place: str = "bottom"
    effect_id: str = ""
    label: str = ""
    url: str = ""
    blend: str = "screen"
    opacity: float = 1.0


@dataclass(frozen=True)
class PreviewSequence:
    """Everything the preview plays, in order. `total` = the last block's end."""

    blocks: tuple[PreviewBlock, ...] = ()
    texts: tuple[PreviewOverlay, ...] = ()
    effects: tuple[PreviewOverlay, ...] = field(default=())

    @property
    def total(self) -> float:
        return self.blocks[-1].out_end if self.blocks else 0.0

    @property
    def slower(self) -> bool:
        """Some block plays faster than a browser can show (×16)."""
        return any(contract.preview_is_slower(b.speed) for b in self.blocks)

    def block_at(self, t: float) -> int:
        """The index of the block shown at final time `t` (-1 with no blocks); `t` past
        the end is the last block."""
        if not self.blocks:
            return -1
        for index, block in enumerate(self.blocks):
            if t < block.out_end:
                return index
        return len(self.blocks) - 1

    def overlays_at(self, t: float) -> tuple[list[int], list[int]]:
        """Which texts and effects show at final time `t` (their indexes)."""
        texts = [i for i, o in enumerate(self.texts) if o.start <= t < o.end]
        effects = [i for i, o in enumerate(self.effects) if o.start <= t < o.end]
        return texts, effects

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": _r(self.total),
            "slower": self.slower,
            "blocks": [asdict(b) for b in self.blocks],
            "texts": [asdict(o) for o in self.texts],
            "effects": [asdict(o) for o in self.effects],
        }

    def to_json(self) -> str:
        """What the preview's `data-edit-seq` attribute carries."""
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


# -- building ---------------------------------------------------------------------------


def _url(key: str, sources: Mapping[str, Any]) -> str:
    """A key's playable address: a `PreviewSource`, a plain string, or "" (none)."""
    source = sources.get(key)
    if isinstance(source, contract.PreviewSource):
        return source.url
    return str(source or "")


def _lay_out(raw: Sequence[dict[str, Any]]) -> tuple[PreviewBlock, ...]:
    """Place raw blocks end to end from 0:00 (the track never has gaps)."""
    blocks: list[PreviewBlock] = []
    at = 0.0
    for item in raw:
        if item["kind"] == _PHOTO:
            dur = float(item["dur"])
            dur = min(max(dur, contract.PHOTO_SECONDS_MIN), contract.PHOTO_SECONDS_MAX)
            length = dur
            extra: dict[str, Any] = {"dur": _r(dur), "rotate": int(item.get("rotate") or 0)}
        else:
            speed = float(item.get("speed") or 1.0)
            length = max(float(item["src_end"]) - float(item["src_start"]), 0.0) / speed
            extra = {
                "src_start": _r(item["src_start"]),
                "src_end": _r(item["src_end"]),
                "speed": speed,
                "rotate": int(item.get("rotate") or 0),
            }
        blocks.append(
            PreviewBlock(
                key=str(item["key"]),
                kind=str(item["kind"]),
                out_start=_r(at),
                out_end=_r(at + length),
                url=str(item.get("url") or ""),
                poster=str(item.get("poster") or ""),
                label=str(item.get("label") or ""),
                **extra,
            )
        )
        at += length
    return tuple(blocks)


def _effect_overlay(
    effect_id: str,
    start: float | None,
    end: float | None,
    total: float,
    assets: Any,
    opacity: float = 1.0,
) -> PreviewOverlay | None:
    effect = contract.effect_of(effect_id)
    if effect is None or not effect.preview_asset:
        return None  # «Cámara rápida» is the blocks' speed, not a layer
    url = contract.preview_effect_url(effect, assets) if assets is not None else ""
    begin = 0.0 if start is None else float(start)
    finish = total if end is None else min(float(end), total)
    return PreviewOverlay(
        kind="effect",
        start=_r(begin),
        end=_r(finish),
        effect_id=effect_id,
        label=effect.label,
        url=url,
        blend=effect.blend or "screen",
        opacity=_opacity(opacity),
    )


def _opacity(value: object) -> float:
    """An effect layer's opacity, 0–1 (1 when not known)."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    return round(min(max(number, 0.0), 1.0), 3) if number > 0 else 1.0


def _recipe_block(seg: contract.SourceSegment, sources: Mapping[str, Any]) -> dict[str, Any]:
    """A raw block of one of the recipe's stretches: a video, or a still photo (ED-15
    `kind`), whose `dur` is how long it shows (from 0 to `end_s`)."""
    row: dict[str, Any] = {
        "key": seg.key,
        "kind": _PHOTO if seg.kind == _PHOTO else _VIDEO,
        "rotate": seg.rotate,
        "url": _url(seg.key, sources),
    }
    if row["kind"] == _PHOTO:
        row["dur"] = seg.source_seconds
    else:
        row.update(src_start=seg.start_s, src_end=seg.end_s, speed=seg.speed)
    return row


def from_recipe(
    recipe: contract.PartRecipe,
    sources: Mapping[str, Any],
    *,
    assets_root: Any = None,
    effect_opacity: Mapping[str, float] | None = None,
) -> PreviewSequence:
    """The sequence of one part's recipe: its videos and photos in order, its texts
    (`text_layers`, an empty one is not shown) and its effects. `sources` maps a block's
    `key` to its playable address; `effect_opacity` an effect's id to its layer's
    opacity (`clip_editor_vm.effect_opacity`; 1 when absent)."""
    blocks = _lay_out([_recipe_block(seg, sources) for seg in recipe.segments])
    total = blocks[-1].out_end if blocks else 0.0
    texts = tuple(
        PreviewOverlay(
            kind="text",
            start=_r(layer.start_s),
            end=_r(total if layer.end_s is None else min(float(layer.end_s), total)),
            text=layer.text.strip(),
            place=layer.place,
        )
        for layer in recipe.text_layers
        if layer.text.strip()
    )
    effects = tuple(
        o
        for o in (
            _effect_overlay(
                u.effect_id,
                u.start_s,
                u.end_s,
                total,
                assets_root,
                (effect_opacity or {}).get(u.effect_id, 1.0),
            )
            for u in recipe.effects
        )
        if o is not None
    )
    return PreviewSequence(blocks=blocks, texts=texts, effects=effects)


def from_timeline(
    media: Sequence[Mapping[str, Any]],
    overlays: Sequence[Mapping[str, Any]],
    sources: Mapping[str, Any],
    *,
    effect_urls: Mapping[str, str] | None = None,
) -> PreviewSequence:
    """The sequence of the timeline's raw lists (`ui.timeline_vm`: «Fotos y videos» in
    the video's order, «Textos» and «Efectos» by time). A row's `key` (else its `id`)
    finds its address in `sources`; a photo row is timed by its `dur`. An
    effect's loop comes from `effect_urls` by label or id ("" = not drawn), by its
    `effect_id` too (ED-04: several blocks of one effect); its row's `opacity` is the
    layer's (1 when absent)."""
    raw: list[dict[str, Any]] = []
    for n, item in enumerate(media, start=1):
        key = str(item.get("key") or item["id"])
        noun = "Foto" if item["kind"] == _PHOTO else "Video"
        row: dict[str, Any] = {
            "key": key,
            "kind": item["kind"],
            "url": _url(key, sources),
            "poster": str(item.get("thumb") or ""),
            "label": f"{noun} {n}",
        }
        if item["kind"] == _PHOTO:
            row.update(dur=item["dur"], rotate=item.get("rotate", 0))
        else:
            row.update(
                src_start=item["src_start"],
                src_end=item["src_end"],
                speed=item.get("speed", 1.0),
                rotate=item.get("rotate", 0),
            )
        raw.append(row)
    blocks = _lay_out(raw)
    total = blocks[-1].out_end if blocks else 0.0
    urls = effect_urls or {}
    texts: list[PreviewOverlay] = []
    effects: list[PreviewOverlay] = []
    for item in overlays:
        start, end = _r(item["start"]), _r(min(float(item["end"]), total))
        if item["kind"] == "text":
            texts.append(
                PreviewOverlay(
                    kind="text",
                    start=start,
                    end=end,
                    text=str(item["label"]),
                    place=str(item.get("place") or "bottom"),
                )
            )
        else:
            label = str(item["label"])
            effects.append(
                PreviewOverlay(
                    kind="effect",
                    start=start,
                    end=end,
                    effect_id=str(item.get("effect_id") or item["id"]),
                    label=label,
                    url=str(
                        urls.get(label)
                        or urls.get(str(item["id"]))
                        or urls.get(str(item.get("effect_id") or ""))
                        or ""
                    ),
                    opacity=_opacity(item.get("opacity", 1.0)),
                )
            )
    return PreviewSequence(blocks=blocks, texts=tuple(texts), effects=tuple(effects))
