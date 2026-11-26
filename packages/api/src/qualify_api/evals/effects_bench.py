"""EF-12 (m-25026587): the paid bench of the «Con IA» effects of the library — the pure part.

The bench asks Seedance for each `seedance_prompt` entry of the effects library («an
object in a zone of the frame», EF-13) n times per model, on product photos of businesses
the founder runs, and a person judges every video. This module holds what needs no
network and no file: the arms of the bench, the blind judgment rows, the scores (success
per effect with its Wilson interval, Cohen's κ between two people) and the library v6 the
scores produce. The runner is `packages/api/evals/banco_efectos/run_experiment.py`.

The arms. Every `seedance_prompt` entry of the library is one arm, filled exactly as
production fills it (`seedance_effect_line`, `effect_subject`, the entry's default zone).
Two CONTROLS ask the same smoke and steam «atmospherically» — no object, no zone — to
answer the ticket's question with numbers: does «an object in a zone» beat the
atmospheric prompt for smoke and steam? A control is no library entry: it is built here
(`control_entry`, `model_construct`, never offered) and only the bench ever asks it.

Success («salió», `docs/adr-50-video-efectos-por-pasos.md` D5/D6 and the bench design):
the effect is visible (`si`; «dudoso» counts as no), it is in the zone asked, the product
did not change and no letters or logos appeared that nobody asked for. `creible` (1-3) is
reported, not part of success. A control asks no zone: its `en_zona` is not judged and
the comparison with its object arm uses the three other criteria for both arms
(`success_without_zone`).

Two people: a video «salió» only when BOTH say so (conservative); κ is computed on that
yes/no over the videos both judged, and the videos they disagree on are listed. One
person: their judgment alone, and κ is reported as missing.

D5 (`qualify_creative.effects.Measured.passes`): an effect is offered when it succeeded
in at least 2 of 3 of at least 4 tries — ON THE MODEL IT RAN ON. The library v6 is v5
with `measured` filled for every judged entry (at the same entry version: `measured` is
the one field that moves, once, from null — `effects.py`), `offered: true` only for the
ones that pass, and the `preview_asset` of each offered one: its winning video, written
to R2 under a platform key (`platform/effects/<id>/v<n>/preview.mp4`, Deivid 2026-11-25),
never into the repository — it shows a business's product (`upload_previews`).

Origin rule (Deivid, 2026-11-25, m-25120474): a preview that goes to `platform/` is made
ONLY with our own material (nibbles) or stock, never with a client's photos (Bianki…).
Judging may use any case; uploading may not. Each case declares `material_origin`
(`own` | `stock` | `client`); missing or unknown counts as `client`, the strictest, and
`upload_previews` refuses to write a preview whose origin is not `own` or `stock`.

The judges (Deivid, 2026-11-25): Deivid and Herwin (`JUDGES`), blind, each on their own.

The small version (Deivid, 2026-11-26, option A): this ticket's run is ONE try per effect
and photo (7 arms × 2 photos = 14 drafts at 480p, no 1080p finals, hard ceiling US$10). It
only measures and judges: n = 2 per effect is under D5's minimum, so no library v6 is
written and nothing reaches `platform/` (`short_of_d5`). The full measurement — n ≥ 4,
finals and the library v6 — is `FULL_MEASUREMENT_TICKET` (m-25129421). D5 is unchanged.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from qualify_creative.effects import (
    MEASURED_MIN_N,
    MEASURED_MIN_SUCCESSES_OF,
    EffectEntry,
    EffectsLibrary,
    Measured,
    effect_zone,
    platform_preview_key,
)
from qualify_creative.schemas import EffectUse

from qualify_api.evals.comment_replies import cohen_kappa

BENCH_TICKET = "m-25026587"
#: The full measurement (n ≥ 4 per effect, 1080p finals, the library v6), split off when
#: Deivid chose the small version on 2026-11-26 (option A).
FULL_MEASUREMENT_TICKET = "m-25129421"
#: The version of this bench's method (arms, controls, criteria, consensus rule).
BENCH_VERSION = 1
#: The library the bench writes (v5 is never edited).
NEW_LIBRARY_VERSION = 6
#: The two people who judge the videos, blind (Deivid, 2026-11-25). A judgment file is
#: `juicio-<judge>.csv`; `score` accepts no one else.
JUDGES: tuple[str, ...] = ("deivid", "herwin")

#: The atmospheric controls: id → (the object arm it is compared with, its template).
#: No `{zone}`: an atmospheric prompt names no place in the frame. `{subject}` is filled
#: like an entry's (`effect_subject`), so the only difference is object-in-zone vs air.
CONTROL_PROMPT_VERSION = "control-atmosferico-v1"
CONTROLS: dict[str, tuple[str, str, str]] = {
    "humo_atmosferico": (
        "humo_denso",
        "Humo en el ambiente",
        "The air of the whole scene is hazy with soft grey smoke from a grill around "
        "{subject}, a warm smoky atmosphere. Everything else stays as it is.",
    ),
    "vapor_atmosferico": (
        "vapor_sobre_comida",
        "Vapor en el ambiente",
        "The whole scene feels warm and humid, with a soft haze of steam in the air "
        "around {subject}. Everything else stays as it is.",
    ),
}

#: The yes/no criteria of a judgment, in the order of the form.
CRITERIA: tuple[str, ...] = ("visible", "en_zona", "producto_igual", "sin_letras")
#: The columns of a judgment CSV (`juicio-<persona>.csv`).
JUDGMENT_COLUMNS: tuple[str, ...] = ("video", "se_pidio", *CRITERIA, "creible", "nota")
_YES = frozenset({"si", "sí", "s", "yes", "y", "1", "true"})
#: Spanish words for the zones, for the judge's «se pidió».
ZONE_SPANISH = {"top": "arriba", "middle": "en el medio", "bottom": "abajo"}


class JudgmentError(ValueError):
    """A judgment file the bench cannot read (an unknown video, a missing column)."""


@dataclass(frozen=True)
class Arm:
    """One thing the bench asks: a library entry («objeto») or a control
    («atmosferico»). `compared_with` names the object arm a control is measured against."""

    id: str
    entry: EffectEntry
    kind: str  # "objeto" | "atmosferico"
    label: str
    compared_with: str | None = None

    @property
    def is_control(self) -> bool:
        return self.kind == "atmosferico"

    def use(self) -> EffectUse:
        """The `EffectUse` the part carries: the entry at its version, default zone."""
        zone = self.entry.params.get("zone")
        params = {"zone": zone.default} if zone is not None and not self.is_control else {}
        return EffectUse(effect_id=self.entry.id, version=self.entry.version, params=params)

    def zone(self) -> str | None:
        return None if self.is_control else effect_zone(self.entry, self.use())

    def asked(self) -> str:
        """What the judge is told was asked: the effect's label and the zone in Spanish."""
        zone = self.zone()
        where = ZONE_SPANISH.get(zone or "", "toda la escena")
        return f"{self.label} — {where}"


def control_entry(control_id: str) -> EffectEntry:
    """A control as an entry the production fill accepts (`seedance_effect_line` only
    replaces the slots it finds). Built around the validator — it has no `{zone}` — and
    never offered: only the bench asks it."""
    _, label, template = CONTROLS[control_id]
    return EffectEntry.model_construct(
        id=control_id,
        version=1,
        stage="seedance_prompt",
        scope="part",
        label=label,
        cost_note="Con IA",
        offered=False,
        params={},
        asset=None,
        preview_asset=None,
        blend=None,
        needs=("video",),
        max_per_part=1,
        categories=("comida",),
        measured=None,
        prompt_version=CONTROL_PROMPT_VERSION,
        prompt_template=template,
    )


def bench_arms(
    library: EffectsLibrary, *, controls: bool = True, only: Iterable[str] | None = None
) -> list[Arm]:
    """The arms, effect by effect in the library's order, each control right after the
    object arm it is compared with. `only`: these arm ids (an effect or a control)."""
    wanted = set(only) if only else None
    arms: list[Arm] = []
    for entry in library.entries:
        if entry.stage != "seedance_prompt":
            continue
        arms.append(Arm(id=entry.id, entry=entry, kind="objeto", label=entry.label))
        if not controls:
            continue
        for control_id, (against, label, _) in CONTROLS.items():
            if against == entry.id:
                arms.append(
                    Arm(
                        id=control_id,
                        entry=control_entry(control_id),
                        kind="atmosferico",
                        label=label,
                        compared_with=entry.id,
                    )
                )
    return [arm for arm in arms if wanted is None or arm.id in wanted]


def bench_library(library: EffectsLibrary, arms: Sequence[Arm]) -> EffectsLibrary:
    """`library` plus the controls among `arms`, so production's lookup
    (`seedance_effect_of` → `load_effects().get`) finds them. Built around the
    validator for the same reason as `control_entry`; used only inside the bench run."""
    extra = tuple(arm.entry for arm in arms if arm.is_control)
    return EffectsLibrary.model_construct(
        version=library.version, notes=library.notes, entries=(*library.entries, *extra)
    )


@dataclass(frozen=True)
class Trial:
    """One video the bench asks: arm × case × repetition."""

    arm: Arm
    case_id: str
    rep: int

    @property
    def label(self) -> str:
        return f"{self.arm.id}/{self.case_id}/{self.rep}"


def plan_trials(arms: Sequence[Arm], case_ids: Sequence[str], reps: int) -> list[Trial]:
    """Effect by effect: every case and repetition of one arm before the next arm."""
    if reps < 1:
        raise ValueError("at least one repetition")
    return [
        Trial(arm, case, rep) for arm in arms for case in case_ids for rep in range(1, reps + 1)
    ]


def min_trials_per_effect(case_ids: Sequence[str], reps: int) -> int:
    return len(case_ids) * reps


def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """The Wilson score interval of `successes` of `n` (95 % by default), rounded to 4
    decimals; (0, 1) when n is 0."""
    if n <= 0:
        return 0.0, 1.0
    if not 0 <= successes <= n:
        raise ValueError("successes between 0 and n")
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


# -- judgments -------------------------------------------------------------------------


@dataclass(frozen=True)
class Judgment:
    """One person's verdict on one blind video."""

    video: str
    visible: bool
    en_zona: bool | None  # None: not judged (a control asks no zone)
    producto_igual: bool
    sin_letras: bool
    creible: int | None
    nota: str = ""

    @property
    def success(self) -> bool:
        """«Salió»: every criterion yes (a zone not judged counts as yes)."""
        return self.success_without_zone and self.en_zona is not False

    @property
    def success_without_zone(self) -> bool:
        return self.visible and self.producto_igual and self.sin_letras


def _yes(value: str | None) -> bool:
    return (value or "").strip().lower() in _YES


def parse_judgments(rows: Iterable[Mapping[str, str]], known: Iterable[str]) -> list[Judgment]:
    """The rows of a judgment CSV. A video not in `known` is an error; a row with no
    verdict at all (every criterion empty) is skipped — not judged yet. «dudoso» or empty
    is no, except `en_zona`, which is None when empty (a control)."""
    videos = set(known)
    found: list[Judgment] = []
    for row in rows:
        video = (row.get("video") or "").strip()
        if not video:
            continue
        if video not in videos:
            raise JudgmentError(f"video {video!r} is not one of the bench's")
        values = [(row.get(name) or "").strip() for name in CRITERIA]
        if not any(values):
            continue
        zone = (row.get("en_zona") or "").strip()
        credible = (row.get("creible") or "").strip()
        found.append(
            Judgment(
                video=video,
                visible=_yes(row.get("visible")),
                en_zona=None if zone in ("", "n/a", "na", "-") else _yes(zone),
                producto_igual=_yes(row.get("producto_igual")),
                sin_letras=_yes(row.get("sin_letras")),
                creible=int(credible) if credible.isdigit() else None,
                nota=(row.get("nota") or "").strip(),
            )
        )
    return found


def read_judgment_csv(text: str, known: Iterable[str]) -> list[Judgment]:
    return parse_judgments(csv.DictReader(text.splitlines()), known)


def judgment_template_rows(videos: Sequence[tuple[str, str]]) -> list[dict[str, str]]:
    """Empty rows of the CSV form: (blind video name, what was asked)."""
    return [
        {"video": video, "se_pidio": asked, **{c: "" for c in CRITERIA}, "creible": "", "nota": ""}
        for video, asked in videos
    ]


# -- scores ----------------------------------------------------------------------------


@dataclass
class ArmScore:
    arm_id: str
    kind: str
    compared_with: str | None
    n: int = 0
    successes: int = 0
    successes_without_zone: int = 0
    credible: list[int] = field(default_factory=list)
    #: The blind video names that succeeded, best first (by credibility).
    winners: list[str] = field(default_factory=list)

    def interval(self) -> tuple[float, float]:
        return wilson(self.successes, self.n)

    def passes(self) -> bool:
        """D5's bar, as `Measured.passes`: n ≥ 4 and successes/n ≥ 2/3, in integers."""
        num, den = MEASURED_MIN_SUCCESSES_OF
        return self.n >= MEASURED_MIN_N and self.successes * den >= num * self.n

    def measured(self, *, model: str, on: date) -> Measured:
        low, high = self.interval()
        return Measured(
            successes=self.successes,
            n=self.n,
            wilson_low=low,
            wilson_high=high,
            measured_on=on,
            model=model,
        )

    def to_json(self) -> dict[str, Any]:
        low, high = self.interval()
        return {
            "arm": self.arm_id,
            "kind": self.kind,
            "compared_with": self.compared_with,
            "n": self.n,
            "successes": self.successes,
            "rate": round(self.successes / self.n, 4) if self.n else None,
            "wilson_low": low,
            "wilson_high": high,
            "successes_without_zone": self.successes_without_zone,
            "credible_mean": round(sum(self.credible) / len(self.credible), 2)
            if self.credible
            else None,
            "passes_d5": self.passes(),
            "min_n": MEASURED_MIN_N,
            "winners": list(self.winners),
        }


def consensus(
    by_rater: Mapping[str, Sequence[Judgment]],
) -> tuple[dict[str, Judgment], dict[str, Any]]:
    """One verdict per video and the agreement report. With two or more people a video
    counts only when every one of them judged it, and it «salió» only when all say so
    (its other fields: the most cautious of them); κ on «salió» between the first two."""
    raters = sorted(by_rater)
    tables = {rater: {j.video: j for j in by_rater[rater]} for rater in raters}
    if not raters:
        return {}, {"raters": [], "kappa": None, "double_judged": 0, "disagreements": []}
    common = set(tables[raters[0]])
    for rater in raters[1:]:
        common &= set(tables[rater])
    verdicts: dict[str, Judgment] = {}
    for video in sorted(common):
        each = [tables[rater][video] for rater in raters]
        zones = [j.en_zona for j in each if j.en_zona is not None]
        credible = [j.creible for j in each if j.creible is not None]
        verdicts[video] = Judgment(
            video=video,
            visible=all(j.visible for j in each),
            en_zona=all(zones) if zones else None,
            producto_igual=all(j.producto_igual for j in each),
            sin_letras=all(j.sin_letras for j in each),
            creible=min(credible) if credible else None,
            nota=" | ".join(j.nota for j in each if j.nota),
        )
    report: dict[str, Any] = {"raters": raters, "double_judged": 0, "kappa": None}
    if len(raters) >= 2:
        first, second = tables[raters[0]], tables[raters[1]]
        both = sorted(set(first) & set(second))
        a = ["si" if first[v].success else "no" for v in both]
        b = ["si" if second[v].success else "no" for v in both]
        kappa = cohen_kappa(a, b) if both else None
        report.update(
            double_judged=len(both),
            kappa=None if kappa is None else round(kappa, 3),
            kappa_ok=None if kappa is None else kappa >= 0.6,
            disagreements=[v for v, x, y in zip(both, a, b, strict=True) if x != y],
        )
    else:
        report["disagreements"] = []
    return verdicts, report


def score_arms(
    manifest: Mapping[str, Mapping[str, Any]], verdicts: Mapping[str, Judgment]
) -> dict[str, ArmScore]:
    """Per arm, over the judged videos of `manifest` (blind name → `{"arm", "kind",
    "compared_with", ...}`); a video that was not made or not judged does not count."""
    scores: dict[str, ArmScore] = {}
    for video, info in manifest.items():
        arm = str(info["arm"])
        score = scores.setdefault(
            arm,
            ArmScore(arm_id=arm, kind=str(info["kind"]), compared_with=info.get("compared_with")),
        )
        verdict = verdicts.get(video)
        if verdict is None:
            continue
        score.n += 1
        if verdict.success:
            score.successes += 1
            score.winners.append(video)
        if verdict.success_without_zone:
            score.successes_without_zone += 1
        if verdict.creible is not None:
            score.credible.append(verdict.creible)
    for score in scores.values():
        score.winners.sort(key=lambda v: -(verdicts[v].creible or 0))
    return scores


def object_vs_atmospheric(scores: Mapping[str, ArmScore]) -> list[dict[str, Any]]:
    """The ticket's question, per control: object vs atmospheric, both on the criteria a
    control can be judged on (visible, product unchanged, no letters), with Wilson
    intervals; `verdict` says «objeto», «atmosferico» or «no concluyente» (intervals
    overlap)."""
    rows: list[dict[str, Any]] = []
    for control_id, (against, _, _) in CONTROLS.items():
        control, obj = scores.get(control_id), scores.get(against)
        if control is None or obj is None or not control.n or not obj.n:
            continue
        o_low, o_high = wilson(obj.successes_without_zone, obj.n)
        c_low, c_high = wilson(control.successes_without_zone, control.n)
        if o_low > c_high:
            verdict = "objeto"
        elif c_low > o_high:
            verdict = "atmosferico"
        else:
            verdict = "no concluyente"
        rows.append(
            {
                "objeto": against,
                "atmosferico": control_id,
                "objeto_exitos": f"{obj.successes_without_zone}/{obj.n}",
                "objeto_wilson": [o_low, o_high],
                "atmosferico_exitos": f"{control.successes_without_zone}/{control.n}",
                "atmosferico_wilson": [c_low, c_high],
                "verdict": verdict,
            }
        )
    return rows


# -- the library v6 --------------------------------------------------------------------


#: Where a case's material comes from. Only `own` and `stock` may become a platform preview.
MATERIAL_ORIGINS: tuple[str, ...] = ("own", "stock", "client")
PLATFORM_PREVIEW_ORIGINS: tuple[str, ...] = ("own", "stock")


def material_origin(value: object) -> str:
    """A case's declared origin; anything missing or not in `MATERIAL_ORIGINS` is `client`
    (the strictest: its previews never reach `platform/`)."""
    return value if isinstance(value, str) and value in MATERIAL_ORIGINS else "client"


def may_be_platform_preview(origin: object) -> bool:
    """Whether a preview made with material of this origin may be uploaded to `platform/`."""
    return material_origin(origin) in PLATFORM_PREVIEW_ORIGINS


def preview_asset_path(effect_id: str, version: int) -> str:
    """Where an offered effect's «Así se ve» lives: an R2 PLATFORM key (no tenant, never a
    file in the repository — the winning video shows a business's product)."""
    return platform_preview_key(effect_id, version)


class PreviewUploadError(RuntimeError):
    """A winning video could not be written to R2 (after its retries) or read back the
    same: the library v6 is not written."""


def upload_previews(
    store: Any,
    videos: Mapping[str, tuple[int, bytes]],
    *,
    origins: Mapping[str, str | None],
    attempts: int = 3,
    refused: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Write each winning video (`effect_id → (entry version, mp4 bytes)`) to its platform
    key (`preview_asset_path`) through `store` (`put(key, fileobj, content_type)` and
    `open(key)`, as `R2ObjectStore`), each write retried up to `attempts` times (rule 3),
    then read back and compared by sha256. Idempotent: an object already there with the
    same bytes is not written again. Returns `{effect_id: {"key", "sha256", "bytes"}}`;
    raises `PreviewUploadError` naming the effect when one cannot be made to match.

    `origins` (`effect_id → material_origin`, required) is the platform rule: a video made
    with material that is not `own` or `stock` (a missing origin counts as `client`) is NOT
    uploaded; it is left out of the result and, when `refused` is given, listed there as
    `effect_id → origin`."""
    done: dict[str, dict[str, Any]] = {}
    for effect_id, (version, data) in videos.items():
        origin = material_origin(origins.get(effect_id))
        if not may_be_platform_preview(origin):
            if refused is not None:
                refused[effect_id] = origin
            continue
        key = preview_asset_path(effect_id, version)
        digest = hashlib.sha256(data).hexdigest()
        if _stored_sha256(store, key) != digest:
            for attempt in range(1, attempts + 1):
                try:
                    store.put(key, io.BytesIO(data), "video/mp4")
                    break
                except Exception as exc:  # a passing R2 failure: retry
                    if attempt == attempts:
                        raise PreviewUploadError(f"{effect_id}: {key}: {exc}") from exc
            if _stored_sha256(store, key) != digest:
                raise PreviewUploadError(f"{effect_id}: {key} does not read back the same")
        done[effect_id] = {"key": key, "sha256": digest, "bytes": len(data)}
    return done


def _stored_sha256(store: Any, key: str) -> str | None:
    try:
        handle = store.open(key)
    except Exception:  # not there (ObjectNotFound) or unreadable: write it
        return None
    with handle:
        return hashlib.sha256(handle.read()).hexdigest()


def short_of_d5(measured: Mapping[str, Measured]) -> dict[str, int]:
    """The measured effects whose sample is under D5's minimum (`MEASURED_MIN_N` judged
    tries), `effect_id → n`. Any one of them means no library v6: `measured` moves once
    from null, so writing a sample too small for D5 would fix that entry for good with a
    number that can never offer it. D5 itself is not changed here."""
    return {arm: m.n for arm, m in measured.items() if m.n < MEASURED_MIN_N}


def library_v6(
    base: Mapping[str, Any],
    measured: Mapping[str, Measured],
    *,
    notes: str,
) -> dict[str, Any]:
    """The library v6 document: `base` (v5, as parsed JSON — never edited) with every
    measured `seedance_prompt` entry carrying its `measured`, `offered` only when it
    passes D5, and then its `preview_asset` (`preview_asset_path`). Entries keep their
    version: `measured` is the one field that moves, once, from null. An entry already
    measured in `base` is left as it is. Validate the result with `parse_library` once
    the preview files are in place."""
    entries: list[dict[str, Any]] = []
    for raw in base["entries"]:
        entry = dict(raw)
        result = measured.get(str(entry["id"]))
        if entry.get("stage") == "seedance_prompt" and result is not None:
            if entry.get("measured") is not None:
                raise ValueError(f"{entry['id']} is already measured in the base library")
            entry["measured"] = result.model_dump(mode="json")
            entry["offered"] = result.passes
            entry["preview_asset"] = (
                preview_asset_path(str(entry["id"]), int(entry["version"]))
                if result.passes
                else None
            )
        entries.append(entry)
    return {"version": NEW_LIBRARY_VERSION, "notes": notes, "entries": entries}


__all__ = [
    "Arm",
    "ArmScore",
    "BENCH_TICKET",
    "BENCH_VERSION",
    "CONTROLS",
    "CONTROL_PROMPT_VERSION",
    "CRITERIA",
    "FULL_MEASUREMENT_TICKET",
    "JUDGMENT_COLUMNS",
    "Judgment",
    "JudgmentError",
    "NEW_LIBRARY_VERSION",
    "JUDGES",
    "MATERIAL_ORIGINS",
    "PLATFORM_PREVIEW_ORIGINS",
    "PreviewUploadError",
    "Trial",
    "bench_arms",
    "bench_library",
    "consensus",
    "control_entry",
    "judgment_template_rows",
    "library_v6",
    "material_origin",
    "may_be_platform_preview",
    "min_trials_per_effect",
    "object_vs_atmospheric",
    "parse_judgments",
    "plan_trials",
    "upload_previews",
    "preview_asset_path",
    "read_judgment_csv",
    "score_arms",
    "short_of_d5",
    "wilson",
]
