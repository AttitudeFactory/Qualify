"""The VLM half of hook extraction: one call per window, structured JSON out.

This is the "different prompt, different output schema, same Provider seam" that
`NOTES_fase0_agentive_layer.md:166` specifies. It does **not** reuse
`qualify_models.vision.DEFAULT_PROMPT`: that prompt asks for a brand-listening prose
description, which is the exact output this feature has no use for.

Failure policy: a model that returns something unparseable yields `parse_ok=False` and
the raw text is kept verbatim. It never yields a guessed category. `HookType.UNKNOWN`
means "the extractor failed here", and it is a different value from
`HookType.NONE_DETECTED`, which means "this video genuinely opens in silence".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from qualify_models.hooks.spec import HookType, Setting, TextDensity
from qualify_models.providers import VisionProvider

# Pinned in provenance alongside the checkpoint. Two hook tables produced by different
# prompt versions are not comparable, and without this field that fact is invisible.
HOOK_PROMPT_VERSION = "hook-vlm-prompt-1"

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_HOOK_TYPES = ", ".join(t.value for t in HookType if t is not HookType.UNKNOWN)
_SETTINGS = ", ".join(s.value for s in Setting if s is not Setting.UNKNOWN)
_DENSITIES = ", ".join(d.value for d in TextDensity if d is not TextDensity.UNKNOWN)

_PROMPT_TEMPLATE = """You are analysing the OPENING of a short-form social video posted \
by a real-estate agent. The image is a contact sheet: {n_frames} frames sampled in \
chronological order from the first {window_seconds:g} seconds, read left to right, top to \
bottom.

This is what the speaker says in those same seconds (may be empty if silent):
\"\"\"{spoken_text}\"\"\"

Classify the opening. Answer with ONE JSON object and nothing else — no prose, no code \
fence.

{{
  "hook_type": one of [{hook_types}],
  "setting": one of [{settings}],
  "face_present": true or false,
  "person_count": integer,
  "on_screen_text": the text burned onto the frames, verbatim, "" if none,
  "text_density": one of [{densities}]
}}

Rules:
- "hook_type" describes the rhetorical move of the opening, judging the spoken words AND \
the on-screen text together. If the opening has neither speech nor on-screen text, use \
"none_detected".
- If an opening both asks a question and states a problem, choose "question".
- Report only what is visible in these frames. Do not infer what happens later in the \
video."""


@dataclass
class VlmReading:
    """One parsed VLM answer, plus the honesty flags."""

    hook_type: HookType
    setting: Setting
    face_present: bool | None
    person_count: int | None
    on_screen_text: str | None
    text_density: TextDensity
    parse_ok: bool
    raw_output: str


def build_prompt(spoken_text: str, n_frames: int, window_seconds: float) -> str:
    return _PROMPT_TEMPLATE.format(
        n_frames=n_frames,
        window_seconds=window_seconds,
        spoken_text=spoken_text.strip(),
        hook_types=_HOOK_TYPES,
        settings=_SETTINGS,
        densities=_DENSITIES,
    )


def read_visual_hook(
    provider: VisionProvider,
    contact_sheet_path: Path,
    spoken_text: str,
    n_frames: int,
    window_seconds: float,
) -> VlmReading:
    prompt = build_prompt(spoken_text, n_frames, window_seconds)
    raw = provider.describe(contact_sheet_path, prompt)
    return parse_vlm_output(raw)


def parse_vlm_output(raw: str) -> VlmReading:
    """Tolerant of surrounding chatter, strict about vocabulary.

    Models wrap JSON in code fences or preamble routinely, so the object is located
    rather than assumed. But a value outside the closed vocabulary is NOT coerced to
    something plausible — it becomes `unknown`, which is a visible failure in the output
    table instead of a silent miscategorisation in the statistics.
    """
    match = _JSON_RE.search(raw or "")
    if match is None:
        return _failed(raw)
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _failed(raw)
    if not isinstance(payload, dict):
        return _failed(raw)

    hook_type = _enum(HookType, payload.get("hook_type"), HookType.UNKNOWN)
    return VlmReading(
        hook_type=hook_type,
        setting=_enum(Setting, payload.get("setting"), Setting.UNKNOWN),
        face_present=_bool(payload.get("face_present")),
        person_count=_int(payload.get("person_count")),
        on_screen_text=_text(payload.get("on_screen_text")),
        text_density=_enum(TextDensity, payload.get("text_density"), TextDensity.UNKNOWN),
        # A JSON object that parsed but whose hook_type was not in the vocabulary is a
        # partial failure, and is reported as one.
        parse_ok=hook_type is not HookType.UNKNOWN,
        raw_output=raw,
    )


def _failed(raw: str) -> VlmReading:
    return VlmReading(
        hook_type=HookType.UNKNOWN,
        setting=Setting.UNKNOWN,
        face_present=None,
        person_count=None,
        on_screen_text=None,
        text_density=TextDensity.UNKNOWN,
        parse_ok=False,
        raw_output=raw,
    )


def _enum[EnumT: StrEnum](enum_cls: type[EnumT], value: object, default: EnumT) -> EnumT:
    if not isinstance(value, str):
        return default
    try:
        return enum_cls(value.strip().lower())
    except ValueError:
        return default


def _bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    return None


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _text(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
