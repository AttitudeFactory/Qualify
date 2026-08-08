"""Output schema for hook extraction: structured, closed-vocabulary, comparable
across posts — deliberately NOT prose.

`NOTES_fase0_agentive_layer.md:166` is the spec this implements: the value of running
a VLM over owned/competitor content is not the description, it is a table of
`(post_id -> hook type, on-screen text density, face presence, cut rate, ...)` that can
be joined against engagement metrics. A description cannot be aggregated; these rows can.

Every field is one of three tiers, and the tier matters when reading a result:

* **deterministic** — computed from pixels/text by code. Exact, free, no eval needed.
* **lexical** — Spanish surface markers matched by regex. Exact, free, but only as good
  as the ASR text it reads.
* **model-derived** — written by the VLM. Costs money, can be wrong, and is the only
  tier that needs the golden-set treatment before anyone trusts it.

Provenance is mandatory per `CLAUDE.md`: every row carries `source_id`,
`detector_version`, `pipeline_version`, `hook_spec_version`, and the model id +
Hub revision of anything a model wrote. An unresolved revision stays `None`; it is
never invented.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from qualify_models.hooks.spec import HookType, Setting, TextDensity
from qualify_models.providers import VisionBackendLabel

SecondPersonRegister = Literal["tu", "usted", "ambiguous", "none"]
"""How the opening addresses the viewer, when it does.

Kept as a register rather than folded into `has_second_person` because the corpus spans
the Venezuela-Colombia border, where *usted* and *tú* are both live and the choice is
regional and social, not stylistic. Two consequences that a boolean would hide:

* *usted* address is **grammatically ambiguous with the third person** ("¿Está cansado?"
  addresses the viewer; "El apartamento está listo" does not). `"ambiguous"` is the honest
  label for an opening carrying an *usted*-shaped verb with nothing to disambiguate it —
  it is neither a detection nor a denial.
* the *usted*/*tú* split is itself a candidate confounder for Fase D (see falsification
  test F5): it tracks country, and country tracks market, prices and algorithm.
"""

HookTypeSource = Literal["vlm", "lexical", "unknown"]
"""Which tier produced the resolved `hook_type`. Recorded per row because a corpus where
most types came from the lexical fallback supports very different claims from one where
the VLM answered — and that difference is invisible once the column is dropped."""


class SpokenHook(BaseModel):
    """Channel 1: what is said in the window. Tier: lexical (over ASR text)."""

    has_speech: bool
    text: str
    word_count: int
    # Speech pace. A hook delivered at 4 words/s is a different creative choice from the
    # same words at 2 words/s, and pace is one of the few things a marketer can act on.
    words_per_second: float

    # Model-free Spanish surface markers. They exist so the correlation in Fase D is not
    # 100% hostage to VLM quality: these are exact given the transcript, so if the VLM
    # turns out unreliable there is still a signal layer that stands on its own.
    has_question_mark: bool
    has_numeral: bool
    has_second_person: bool  # tú/te/tu/usted/vuestro... -> speaks *to* the viewer
    # Which register that address is in. "ambiguous" means an usted-shaped verb with no
    # disambiguating evidence, and does NOT set has_second_person: on a two-country corpus
    # guessing here would manufacture direct address that may not exist.
    second_person_register: SecondPersonRegister = "none"
    has_negation: bool
    has_imperative_marker: bool
    has_price_token: bool  # "€", "euros", "90.000"


class VisualHook(BaseModel):
    """Channels 2 and 3: what is shown, and what is written on screen."""

    n_frames_sampled: int

    # --- deterministic (pixels; no model, no network) ---
    cut_count: int
    cuts_per_second: float
    motion_energy: float = Field(description="mean inter-frame difference, 0-1")
    brightness: float = Field(description="mean luma, 0-1")
    saturation: float = Field(description="mean HSV saturation, 0-1")
    dominant_colors: list[str] = Field(default_factory=list, description="hex, most-used first")

    # --- model-derived (VLM). None everywhere means the VLM did not run. ---
    setting: Setting | None = None
    face_present: bool | None = None
    person_count: int | None = None
    on_screen_text: str | None = None
    text_density: TextDensity | None = None
    vlm_parse_ok: bool | None = None
    # Kept verbatim when parsing fails so a bad run is diagnosable instead of silently
    # collapsing to `unknown`. Never used as a feature.
    vlm_raw_output: str | None = None


class HookWindowFeatures(BaseModel):
    """All three channels for one window width (3 s / 5 s / 7 s)."""

    window_seconds: float
    spoken: SpokenHook
    visual: VisualHook

    # Two independent readings of the same window, kept side by side on purpose: their
    # agreement rate is a free, label-free quality signal on the VLM (see §B.4). Do not
    # collapse them into one field.
    hook_type_vlm: HookType | None = None
    hook_type_lexical: HookType | None = None

    hook_type: HookType
    hook_type_source: HookTypeSource


class HookFeatures(BaseModel):
    """One video's hook, at every window. This is the unit that joins to metrics."""

    # --- identity + provenance (hard rule, CLAUDE.md) ---
    source_id: str
    detector_version: str
    pipeline_version: str
    hook_spec_version: str
    extracted_at: datetime

    video_path: Path
    video_sha256: str
    duration_seconds: float | None = None

    asr_model_id: str | None = None
    asr_model_revision: str | None = None
    vlm_model_id: str | None = None
    vlm_model_revision: str | None = None
    # Which backend produced the model-derived tier: "hosted", "local" or "injected".
    # The model id is the same string for hosted and local Qwen3-VL, so without this the
    # row cannot say whether a value came from a vendor endpoint or from local weights —
    # and those differ in latency, cost, quantization and vendor exposure.
    vlm_backend: VisionBackendLabel | None = None

    windows: list[HookWindowFeatures]

    def window(self, seconds: float) -> HookWindowFeatures | None:
        for w in self.windows:
            if w.window_seconds == seconds:
                return w
        return None

    def to_flat_row(self, window_seconds: float) -> dict[str, Any]:
        """One flat dict per (video, window) — the shape that goes into CSV and, later,
        into a dataframe for Fase D. Flattening happens here rather than at the writer so
        column names are defined in exactly one place."""
        w = self.window(window_seconds)
        if w is None:
            raise ValueError(f"no window of {window_seconds}s in this extraction")
        return {
            "source_id": self.source_id,
            "window_seconds": w.window_seconds,
            "hook_type": w.hook_type.value,
            "hook_type_source": w.hook_type_source,
            "hook_type_vlm": w.hook_type_vlm.value if w.hook_type_vlm else None,
            "hook_type_lexical": w.hook_type_lexical.value if w.hook_type_lexical else None,
            "spoken_text": w.spoken.text,
            "has_speech": w.spoken.has_speech,
            "word_count": w.spoken.word_count,
            "words_per_second": round(w.spoken.words_per_second, 3),
            "has_question_mark": w.spoken.has_question_mark,
            "has_numeral": w.spoken.has_numeral,
            "has_second_person": w.spoken.has_second_person,
            "second_person_register": w.spoken.second_person_register,
            "has_negation": w.spoken.has_negation,
            "has_imperative_marker": w.spoken.has_imperative_marker,
            "has_price_token": w.spoken.has_price_token,
            "setting": w.visual.setting.value if w.visual.setting else None,
            "face_present": w.visual.face_present,
            "person_count": w.visual.person_count,
            "on_screen_text": w.visual.on_screen_text,
            "text_density": w.visual.text_density.value if w.visual.text_density else None,
            "cut_count": w.visual.cut_count,
            "cuts_per_second": round(w.visual.cuts_per_second, 3),
            "motion_energy": round(w.visual.motion_energy, 4),
            "brightness": round(w.visual.brightness, 4),
            "saturation": round(w.visual.saturation, 4),
            "dominant_colors": "|".join(w.visual.dominant_colors),
            "n_frames_sampled": w.visual.n_frames_sampled,
            "duration_seconds": self.duration_seconds,
            # Provenance travels with every row, not just with the report header: a CSV
            # gets copied into a spreadsheet and detached from its manifest immediately.
            "detector_version": self.detector_version,
            "pipeline_version": self.pipeline_version,
            "hook_spec_version": self.hook_spec_version,
            "asr_model_id": self.asr_model_id,
            "asr_model_revision": self.asr_model_revision,
            "vlm_model_id": self.vlm_model_id,
            "vlm_model_revision": self.vlm_model_revision,
            "vlm_backend": self.vlm_backend,
            "video_sha256": self.video_sha256,
            "extracted_at": self.extracted_at.isoformat(),
        }


FLAT_ROW_COLUMNS: tuple[str, ...] = (
    "source_id",
    "window_seconds",
    "hook_type",
    "hook_type_source",
    "hook_type_vlm",
    "hook_type_lexical",
    "spoken_text",
    "has_speech",
    "word_count",
    "words_per_second",
    "has_question_mark",
    "has_numeral",
    "has_second_person",
    "second_person_register",
    "has_negation",
    "has_imperative_marker",
    "has_price_token",
    "setting",
    "face_present",
    "person_count",
    "on_screen_text",
    "text_density",
    "cut_count",
    "cuts_per_second",
    "motion_energy",
    "brightness",
    "saturation",
    "dominant_colors",
    "n_frames_sampled",
    "duration_seconds",
    "detector_version",
    "pipeline_version",
    "hook_spec_version",
    "asr_model_id",
    "asr_model_revision",
    "vlm_model_id",
    "vlm_model_revision",
    "vlm_backend",
    "video_sha256",
    "extracted_at",
)
"""Column order for CSV output. Kept as a literal so the header is stable across runs
even if the dict order in `to_flat_row` ever shifts — a moving header silently breaks
any spreadsheet or join built on top of it."""
