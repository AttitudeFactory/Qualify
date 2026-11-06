"""A video by parts (ADR 44, VE-08 m-24921065): its plan from a reel's analysis, its parts
as child drafts, and «Crear otra versión» of one part.

- `plan_from_analysis` is PURE: the analysed cuts (`ReelAnalysis`, VE-04c) become 1 to
  `PARTS_MAX` parts of 1-10 s — the mode by who is seen (F6), short cuts joined (P2), a cut
  longer than 10 s split with `extend` (design §3), a source that is not 9:16 always made
  new (N5) — with what the owner should read about each part (`PartNotice`).
- `PartsService.create_parts` makes every child of a parent at once: briefs and drafts,
  their vistas previas charged all or nothing (`charge_many`, D7) and one `preview` job
  each, in ONE `tenant_unit_of_work` — a shortfall leaves no child and no charge. A child
  asks Claude nothing: its text is one of its parent's (`ContentService._inherited_copy`).
- `PartsService.regenerate_part` writes a new brief for that one part (description and
  photos; the mode stays) and regenerates it through `reject(regenerate=True)`: 1 vista
  previa at `revision + 1`, the siblings untouched, the earlier versions keep their own
  brief (`piece_versions.brief_id`).
- `check_parent_text_cap` keeps the parent's new texts (Claude, paid by the platform, 0
  creations) to `PARENT_TEXT_DAILY_CAP` per business per day.
- `mark_parent_dirty` tells the parent's `join` run (VE-10a) that a part changed.

Seconds of video (D29, VE-21) are charged when the owner approves the whole video
(VE-10b), never here: creating parts uses only vistas previas.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_creative.creations import CreationWeights, load_weights, weight_for
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    CLIP_MAX_IMAGES,
    PART_DESCRIPTION_MAX,
    PART_GENERATION_MIN_SECONDS,
    PARTS_MAX,
    ContentBrief,
    PartNotice,
    PartRef,
    VideoPartPlan,
)
from qualify_shared.db.session import tenant_unit_of_work
from sqlalchemy import text
from sqlalchemy.orm import Session

from qualify_api.creative.creations import PreviewCharge, summed_price
from qualify_api.creative.fsm import DRAFTING, FAILED
from qualify_api.creative.media import PartWindowRefused
from qualify_api.creative.queue_dispatch import queue_enabled
from qualify_api.creative.service import (
    ContentService,
    DraftRecord,
    PostgresContentRepository,
    UnknownDraft,
)
from qualify_api.referentes.reel_analysis_types import (
    NOT_OBSERVED,
    OBSERVED,
    UNKNOWN,
    ReelAnalysis,
    ShotAnalysis,
)

# ---------------------------------------------------------------------------
# What the owner reads (qualify-copy-es). `PartNotice` codes → their words (UI-3).

NOTICE_TEXTS: Mapping[str, str] = {
    "people_unclear": (
        "No pudimos ver bien si en esta parte aparece alguien. "
        "La crearemos de cero con las fotos de tu producto."
    ),
    "describe_it": (
        "No pudimos ver qué pasa en esta parte. Cuéntanos en una frase qué quieres que muestre."
    ),
}

#: Decided 2026-11-05: a business asks for a new text of its videos by parts at most this
#: many times a day — each is a Claude call the platform pays and costs 0 creations.
PARENT_TEXT_DAILY_CAP = 20
PARENT_TEXT_CAP_TEXT = (
    f"Hoy ya pediste {PARENT_TEXT_DAILY_CAP} textos nuevos para tu negocio. "
    f"Mañana puedes pedir otros {PARENT_TEXT_DAILY_CAP}."
)
PARTS_NEED_TEXT_TEXT = "Espera a que esté listo el texto de tu video para crear sus partes."
PARTS_UNAVAILABLE_TEXT = "Por ahora no podemos crear las partes de tu video. Inténtalo más tarde."
PARTS_OVER_BUDGET_TEXT = (
    "No pudimos crear las partes: tu negocio llegó a su límite de este mes. "
    "Escríbenos y lo revisamos contigo."
)


def part_label(index: int, total: int) -> str:
    """«Parte 2 de 4» — where a part sits in its video."""
    return f"Parte {index} de {total}"


def describe_part_text(index: int) -> str:
    return f"Antes de crear la parte {index}, cuéntanos qué quieres que muestre."


class PartsUnavailable(Exception):
    """The parts cannot be made now (the generation queue is off: the parent would never
    be joined again). Nothing was written."""

    def __init__(self) -> None:
        super().__init__(PARTS_UNAVAILABLE_TEXT)
        self.text = PARTS_UNAVAILABLE_TEXT


class ParentTextMissing(Exception):
    """The parent has no text that passed yet — its parts would have none to carry."""

    def __init__(self) -> None:
        super().__init__(PARTS_NEED_TEXT_TEXT)
        self.text = PARTS_NEED_TEXT_TEXT


class PartNeedsDescription(Exception):
    """A part the analysis could not see (`describe_it`) still has no description."""

    def __init__(self, index: int) -> None:
        self.text = describe_part_text(index)
        super().__init__(self.text)
        self.index = index


class PartsOverBudget(Exception):
    """The team's dollar cap of the brand cannot pay the parts together (N9): checked
    once on their estimated total, before anything exists."""

    def __init__(self, *, estimated_usd: Decimal, remaining_usd: Decimal) -> None:
        super().__init__(PARTS_OVER_BUDGET_TEXT)
        self.text = PARTS_OVER_BUDGET_TEXT
        self.estimated_usd = estimated_usd
        self.remaining_usd = remaining_usd


class ParentTextCapReached(Exception):
    """Criterion 7: today's new texts of this business's videos by parts are spent."""

    def __init__(self, used: int) -> None:
        super().__init__(PARENT_TEXT_CAP_TEXT)
        self.text = PARENT_TEXT_CAP_TEXT
        self.used = used


class ExtendTooShort(ValueError):
    """Criterion 8: an `extend` part that shares the previous part's last cut is only for
    a cut of the analysis longer than 10 s (one generation cannot hold it)."""


# ---------------------------------------------------------------------------
# The plan from an analysis (pure)

#: A part of a video holds at most this many seconds (D5's per-video ceiling).
PART_MAX_SECONDS = 10
#: 9:16 within this relative tolerance (720×1280, 1080×1920, 1080×1918…).
_VERTICAL_TOLERANCE = 0.02

#: Words that assume a person's gender or age (VE-04c's prompt already forbids them, the
#: model may still slip): «un hombre» → «una persona». Never who someone is.
_PERSON_WORDS = (
    "hombre",
    "mujer",
    "chico",
    "chica",
    "muchacho",
    "muchacha",
    "niño",
    "niña",
    "señor",
    "señora",
    "joven",
    "anciano",
    "anciana",
    "abuelo",
    "abuela",
    "adolescente",
    "caballero",
    "dama",
)
_PERSON_PLURALS = (
    "hombres",
    "mujeres",
    "chicos",
    "chicas",
    "muchachos",
    "muchachas",
    "niños",
    "niñas",
    "señores",
    "señoras",
    "jóvenes",
    "ancianos",
    "ancianas",
    "abuelos",
    "abuelas",
    "adolescentes",
    "caballeros",
    "damas",
)
_ARTICLE = r"(?:(?P<art>un|una|el|la|los|las|unos|unas|dos|tres|cuatro|varios|varias)\s+)?"
_AGE_ADJECTIVES = r"(?:\s+(?:joven|jóvenes|mayor|mayores|adulto|adulta|adultos|adultas))?"
_SINGULAR = re.compile(
    rf"\b{_ARTICLE}(?P<noun>{'|'.join(_PERSON_WORDS)}){_AGE_ADJECTIVES}\b", re.IGNORECASE
)
_PLURAL = re.compile(
    rf"\b{_ARTICLE}(?P<noun>{'|'.join(_PERSON_PLURALS)}){_AGE_ADJECTIVES}\b", re.IGNORECASE
)
_PLURAL_ARTICLES = {"los": "las", "unos": "unas", "varios": "varias"}
#: Words after which a person word is still a NOUN («con jóvenes», «para niños»); after
#: any other word it qualifies the word before it («unas manos jóvenes», «un vaso chico»).
_NOUN_INTRODUCERS = frozenset(
    "a al ante como con de del e entre hacia ni o para por que sin sobre u y".split()
)
_WORD_BEFORE = re.compile(r"(\w+)\s+$")
#: Plural nouns a plural age or gender word QUALIFIES («unas manos jóvenes», «sus caras
#: adolescentes»). After any other word a bare plural is a noun, often a subject after its
#: verb («Llegan niños corriendo»), and becomes «personas».
_PLURAL_HOSTS = frozenset(
    "manos personas caras rostros pieles voces amigos amigas clientes parejas grupos "
    "figuras siluetas".split()
)


def _qualifies_previous_word(match: re.Match[str], *, plural: bool) -> bool:
    """An adjective, so dropped, not a person to rename: no article, and right after a
    word that does not introduce a noun (singular: a bare singular person noun after a
    word is never a subject in Spanish — «un vaso chico», «una persona joven»), or, for a
    plural, right after a noun it can qualify (`_PLURAL_HOSTS`)."""
    if match.group("art"):
        return False
    before = _WORD_BEFORE.search(match.string[: match.start()])
    if before is None:
        return False
    word = before.group(1).lower()
    if plural:
        return word in _PLURAL_HOSTS
    return word not in _NOUN_INTRODUCERS


def neutral_people(text_: str) -> str:
    """The description without a person's assumed gender or age: «un hombre joven
    muerde…» → «una persona muerde…», «dos mujeres» → «dos personas». Used as an
    adjective after another word, the age or gender word is dropped instead: «unas manos
    jóvenes» → «unas manos», never «unas manos personas»."""

    def cased(match: re.Match[str], words: str) -> str:
        # «Los niños…» opens a sentence as «Las personas…», not «las personas…»
        return words[:1].upper() + words[1:] if match.group(0)[:1].isupper() else words

    def singular(match: re.Match[str]) -> str:
        if _qualifies_previous_word(match, plural=False):
            return ""
        article = (match.group("art") or "").lower()
        if article in ("el", "la"):
            return cased(match, "la persona")
        return cased(match, "una persona")

    def plural(match: re.Match[str]) -> str:
        if _qualifies_previous_word(match, plural=True):
            return ""
        article = (match.group("art") or "").lower()
        article = _PLURAL_ARTICLES.get(article, article)
        return cased(match, f"{article} personas" if article else "personas")

    out = _SINGULAR.sub(singular, _PLURAL.sub(plural, text_))
    if out == text_:
        return out
    # a dropped adjective leaves a double space or a space before punctuation
    return re.sub(r"\s+([,.;:!?)])", r"\1", re.sub(r"[ \t]{2,}", " ", out)).strip()


def _observed_value(families: Mapping[str, Any], name: str) -> str:
    family = families.get(name) or {}
    if not isinstance(family, Mapping) or family.get("status") != OBSERVED:
        return ""
    value = family.get("value")
    return value.strip() if isinstance(value, str) else ""


def _with_products(value: str, products: Sequence[str]) -> str:
    """The analysis never knows the brand: its «el producto» becomes the owner's own
    product when the piece is about one."""
    name = next((p.strip() for p in products if p and p.strip()), "")
    if not name:
        return value
    value = re.sub(r"\bdel producto\b", f"de {name}", value, flags=re.IGNORECASE)
    value = re.sub(r"\bal producto\b", f"a {name}", value, flags=re.IGNORECASE)
    return re.sub(r"\b(?:el|un) producto\b", name, value, flags=re.IGNORECASE)


def _sentence(value: str) -> str:
    value = value.strip().rstrip(".")
    if not value:
        return ""
    return value[0].upper() + value[1:] + "."


def shot_description(shot: ShotAnalysis, products: Sequence[str] = ()) -> str:
    """What the cut shows, from its sheet: the subject (what is seen and what happens),
    never who someone is. Empty when the analysis could not see it."""
    subject = _observed_value(shot.families, "subject")
    if not subject:
        return ""
    return _sentence(neutral_people(_with_products(subject, products)))


def _edit_allowed(shot: ShotAnalysis) -> bool:
    """F6: «Igual al original» only when no person and no face was seen."""
    return shot.people_presence == NOT_OBSERVED and shot.visible_faces == NOT_OBSERVED


def _people_unclear(shot: ShotAnalysis) -> bool:
    """The analysis could not tell whether someone is in the cut."""
    return shot.people_presence == UNKNOWN or (
        shot.people_presence == NOT_OBSERVED and shot.visible_faces == UNKNOWN
    )


def _talks(shot: ShotAnalysis) -> bool:
    """Someone seems to talk to the camera: speech falls in the cut and a face is seen."""
    return bool(shot.spoken_text.strip()) and shot.visible_faces == OBSERVED


def is_vertical(width: int, height: int) -> bool:
    if width <= 0 or height <= 0:
        return False
    return abs(width / height - 9 / 16) <= (9 / 16) * _VERTICAL_TOLERANCE


def _seconds(duration: float) -> int:
    return max(1, min(PART_MAX_SECONDS, round(duration)))


def _group_seconds(group: Sequence[ShotAnalysis]) -> float:
    return sum(max(shot.seconds, 0.0) for shot in group)


def _parts_needed(group: Sequence[ShotAnalysis]) -> int:
    seconds = _group_seconds(group)
    return max(1, math.ceil(seconds / PART_MAX_SECONDS)) if len(group) == 1 else 1


def _consecutive(a: Sequence[ShotAnalysis], b: Sequence[ShotAnalysis]) -> bool:
    return b[0].shot_index == a[-1].shot_index + 1


def _can_join(a: Sequence[ShotAnalysis], b: Sequence[ShotAnalysis]) -> bool:
    return _consecutive(a, b) and _group_seconds(a) + _group_seconds(b) <= PART_MAX_SECONDS


def _same_mode(a: Sequence[ShotAnalysis], b: Sequence[ShotAnalysis], editable: bool) -> bool:
    """P2: a cut where someone is (or may be) seen never joins an «Igual al original»
    part — joining across that line would make it new and lose the original's look."""
    if not editable:
        return True
    return all(_edit_allowed(s) for s in a) == all(_edit_allowed(s) for s in b)


def _groups(shots: Sequence[ShotAnalysis], editable: bool) -> list[list[ShotAnalysis]]:
    """Consecutive cuts joined while the part is shorter than Seedance's 4 s and the sum
    stays within 10 s (P2), never across the edit/new line; a cut over 10 s stays alone
    (it is split later). Past `PARTS_MAX` parts, the shortest neighbours that fit are
    joined — of the same mode first, then any."""
    groups: list[list[ShotAnalysis]] = []
    for shot in shots:
        last = groups[-1] if groups else None
        if (
            last is not None
            and _group_seconds(last) < PART_GENERATION_MIN_SECONDS
            and _can_join(last, [shot])
            and _same_mode(last, [shot], editable)
        ):
            last.append(shot)
        else:
            groups.append([shot])
    # a short last part leans on the one before it when it fits
    if (
        len(groups) > 1
        and _group_seconds(groups[-1]) < PART_GENERATION_MIN_SECONDS
        and _can_join(groups[-2], groups[-1])
        and _same_mode(groups[-2], groups[-1], editable)
    ):
        groups[-2].extend(groups.pop())
    while sum(_parts_needed(g) for g in groups) > PARTS_MAX:
        pairs = [
            (
                not _same_mode(groups[i], groups[i + 1], editable),
                _group_seconds(groups[i]) + _group_seconds(groups[i + 1]),
                i,
            )
            for i in range(len(groups) - 1)
            if _can_join(groups[i], groups[i + 1])
        ]
        if not pairs:
            break
        *_, at = min(pairs)
        groups[at].extend(groups.pop(at + 1))
    return groups


def _split(seconds: float) -> list[int]:
    """A cut over 10 s as consecutive parts of at most 10 s, as even as whole seconds go."""
    total = round(seconds)
    count = max(2, math.ceil(total / PART_MAX_SECONDS))
    base, extra = divmod(total, count)
    return [base + (1 if i < extra else 0) for i in range(count)]


def plan_from_analysis(
    analysis: ReelAnalysis, *, products: Sequence[str] = ()
) -> tuple[VideoPartPlan, ...]:
    """The parts a reel's analysis proposes, in order (pure; no I/O, no model call).

    - mode by people (F6): `edit` («Igual al original») only for cuts where no person and
      no face was seen, the source is 9:16 (N5) and can be edited; anything else
      `reference` (new, inspired by the original). People the analysis could not tell
      about → `people_unclear`, never `edit`;
    - consecutive cuts shorter than 4 s are joined up to 10 s (P2), and, past
      `PARTS_MAX` parts, the shortest neighbours that fit; past that, the first six;
    - a cut longer than 10 s becomes parts of at most 10 s, every one after the first an
      `extend` («Sigue a la anterior») that starts on that same cut;
    - `talks_to_camera` = speech in the cut and a face seen; a part whose cuts show
      nothing the analysis could see → `describe_it`, no description;
    - descriptions never assume age or gender (`neutral_people`).
    """
    shots = sorted(analysis.shots, key=lambda s: s.shot_index)
    if not shots:
        return ()
    editable = (
        analysis.edit_eligible
        and analysis.source_available
        and is_vertical(analysis.width, analysis.height)
    )
    plan: list[VideoPartPlan] = []
    for group in _groups(shots, editable):
        unclear = any(_people_unclear(shot) for shot in group)
        mode = "edit" if editable and all(_edit_allowed(s) for s in group) else "reference"
        description = " ".join(d for d in (shot_description(s, products) for s in group) if d)
        notices: list[PartNotice] = []
        if unclear:
            notices.append("people_unclear")
        if not description:
            notices.append("describe_it")
        common: dict[str, Any] = {
            "analysis_id": analysis.id,
            "shot_indexes": tuple(s.shot_index for s in group),
            "description": description[:PART_DESCRIPTION_MAX],
            "talks_to_camera": any(_talks(s) for s in group),
            "notices": tuple(notices),
        }
        if len(group) == 1 and group[0].seconds > PART_MAX_SECONDS:
            for at, seconds in enumerate(_split(group[0].seconds)):
                plan.append(
                    VideoPartPlan(mode=mode if at == 0 else "extend", seconds=seconds, **common)
                )
        else:
            plan.append(VideoPartPlan(mode=mode, seconds=_seconds(_group_seconds(group)), **common))
    return tuple(plan[:PARTS_MAX])


def check_extend_parts(parts: Sequence[VideoPartPlan], analysis: ReelAnalysis | None) -> None:
    """Criterion 8 (VE-06's schema cannot see cut lengths): an `extend` part that starts
    on the previous part's last cut is accepted only when that cut of the analysis lasts
    more than 10 s. An `extend` without cuts (no reel) continues freely."""
    previous: VideoPartPlan | None = None
    for part in parts:
        shares = (
            part.mode == "extend"
            and part.shot_indexes
            and previous is not None
            and previous.shot_indexes
            and part.shot_indexes[0] == previous.shot_indexes[-1]
        )
        if shares:
            if analysis is None or analysis.id != part.analysis_id:
                raise ExtendTooShort("an extend part on a reel's cut needs that reel's analysis")
            shot = next((s for s in analysis.shots if s.shot_index == part.shot_indexes[0]), None)
            if shot is None or shot.seconds <= PART_MAX_SECONDS:
                raise ExtendTooShort(
                    "«Sigue a la anterior» shares a cut only when that cut lasts over 10 s"
                )
        previous = part


#: A neighbour cut sharing less than this with a window does not count as «in» it (the
#: cut times are the detector's, a frame apart).
_WINDOW_SLACK_S = 0.05


def _window_clean(shots: Sequence[ShotAnalysis], own: set[int], start: int, end: int) -> bool:
    """No cut of someone else's (a person or a face seen, or unknown) inside the window."""
    for shot in shots:
        inside = min(shot.end_s, end) - max(shot.start_s, start)
        if shot.shot_index not in own and inside > _WINDOW_SLACK_S and not _edit_allowed(shot):
            return False
    return True


def part_window(
    part: VideoPartPlan | PartRef,
    shots: Sequence[ShotAnalysis],
    *,
    source_seconds: float | None,
) -> tuple[int, int, float]:
    """VE-09: the window of the original an «Igual al original» part edits, `(start_s,
    end_s, offset_s)` — whole seconds (`source_window` cuts whole seconds), as long as
    the part's `generation_seconds` (what the child asks Seedance for, so the edit's
    ±0.5 s check holds) and within the source. It starts on the part's first cut and,
    when its cuts are shorter, takes the rest from the next cut; if that one shows
    someone (or might), from the cut before; if both do, it is refused
    (`not_edit_eligible`: never put a person of the original in an edit, F6).
    `offset_s` is where the part's own cuts start inside the window, SIGNED (the join
    trims there): positive = the window opens that many seconds before the part's
    first cut (a cut at 3.2 s in a window from 3 s → 0.2); negative = the window opens
    after it, so the part's first `-offset_s` seconds are not in it. Pure."""
    own = set(part.shot_indexes)
    covered = sorted((s for s in shots if s.shot_index in own), key=lambda s: s.shot_index)
    if not covered or len(covered) != len(own):
        raise PartWindowRefused("window_unavailable")
    length = part.generation_seconds
    source_end = source_seconds if source_seconds is not None else max(s.end_s for s in shots)
    limit = math.floor(source_end + 1e-3)
    if limit < length:
        raise PartWindowRefused("window_unavailable")
    first, last = covered[0].start_s, covered[-1].end_s
    # whole seconds that keep the part's first cut whole (the lead before it is checked
    # like any neighbour), or that end where its last cut ends
    forward = min(max(0, math.floor(first + _WINDOW_SLACK_S)), limit - length)
    backward = max(0, min(math.ceil(last - _WINDOW_SLACK_S), limit) - length)
    for start in dict.fromkeys((forward, backward)):
        if _window_clean(shots, own, start, start + length):
            return start, start + length, round(first - start, 3)
    raise PartWindowRefused("not_edit_eligible")


# ---------------------------------------------------------------------------
# Children: create, regenerate, read


@dataclass(frozen=True)
class PartChanges:
    """What «Crear otra versión» of a part may change (provisional decision 2026-11-05):
    its description and its photos — never its mode. None keeps what it had."""

    description: str | None = None
    photo_keys: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PartSummary:
    """One part as the parent's screen shows it: «Parte 2 de 4», its state and the
    description its current version was made from."""

    index: int
    total: int
    draft_id: UUID | None  # None while the part is only planned
    status: str  # the child's status, or «planned»
    mode: str
    seconds: int
    description: str
    notices: tuple[str, ...]

    @property
    def label(self) -> str:
        return part_label(self.index, self.total)


PLANNED = "planned"


class PartsRepository(Protocol):
    """What parts need of the content repository besides the `ContentRepository` seam."""

    def parts_of(self, *, tenant_id: UUID, parent_id: UUID) -> tuple[DraftRecord, ...]: ...

    def replace_brief(
        self, *, tenant_id: UUID, draft_id: UUID, user_id: UUID, brief: ContentBrief
    ) -> UUID: ...


def check_parent_text_cap(repository: Any, *, tenant_id: UUID) -> None:
    """Criterion 7: refuse a new parent text once today's are spent. A repository that
    cannot count (test doubles without it) is not capped."""
    counter: Callable[..., int] | None = getattr(repository, "parent_texts_regenerated_today", None)
    if counter is None:
        return
    used = counter(tenant_id=tenant_id)
    if used >= PARENT_TEXT_DAILY_CAP:
        raise ParentTextCapReached(used)


def mark_parent_dirty(session: Session, child_id: UUID) -> None:
    """A part was made, failed or got another version back: the parent's `join` run (the
    one VE-10a opens, at the parent's current revision) must join again. In the
    caller's transaction; never creates the run — without one there is nothing to redo."""
    session.execute(
        text("""
        UPDATE creative_pipeline_runs r SET dirty_version = r.dirty_version + 1
        FROM content_drafts c
        JOIN content_drafts p ON p.tenant_id = c.tenant_id AND p.id = c.parent_draft_id
        WHERE c.id = :child AND r.tenant_id = p.tenant_id AND r.draft_id = p.id
          AND r.revision = p.revision AND r.phase = 'join'
        """),
        {"child": child_id},
    )


def _child_brief(
    parent: ContentBrief, plan: VideoPartPlan, index: int, window: str | None
) -> ContentBrief:
    """A part's own brief: a `CLIP` of the part's generation length in the part's mode,
    with the parent's product photos as its references (its words come from the
    parent's text, not from Claude). No logo, no brand resource and no subtitles: a
    part is one shot of a video joined later, which carries them once (VE-09).

    An `edit` part edits a window of the original reel. VE-09: the creative worker cuts
    it into the part's own folder when the part is made (`source_window` needs the
    part's draft id), so none is needed here; a `window` cut beforehand is kept (it is
    a key of the piece like any other, checked by `_key_problems` before any read)."""
    media = parent.media
    photos = tuple(media.product_keys[:CLIP_MAX_IMAGES])
    part = PartRef(index=index, **plan.model_dump())
    video_keys: tuple[str, ...] = ()
    if plan.mode == "edit" and window:
        video_keys = (window,)
    child_media = media.model_dump()
    child_media.update(
        parts=(),
        parts_provenance=None,  # the plan's (VE-14), the parent's alone
        part=part,
        duration_seconds=part.generation_seconds,
        clip_reference_mode={"reference": "motion", "edit": "edit", "extend": "extend"}[plan.mode],
        clip_image_keys=photos,
        clip_image_roles=tuple("product" for _ in photos),
        clip_video_keys=video_keys,
        clip_first_frame_key=None,
        clip_last_frame_key=None,
        clip_audio_keys=(),
        clip_subtitles=False,
        brand_logo_key=None,
        brand_logo_reference_keys=(),
        brand_logo_placement=None,
        brand_logo_in_scene=True,
        brand_element_keys=(),
    )
    return ContentBrief.model_validate(
        {
            **parent.model_dump(),
            "kind": ContentKind.CLIP,
            "format": ContentFormat.REELS_9_16,
            "variants_requested": 1,
            "media": child_media,
        }
    )


class PartsService:
    """The parts of a video by parts, over the content service's own collaborators."""

    def __init__(
        self,
        content: ContentService,
        *,
        weights: CreationWeights | None = None,
        require_queue: Callable[[], bool] = queue_enabled,
    ) -> None:
        self._content = content
        self._weights = weights or load_weights()
        self._queue_enabled = require_queue

    @property
    def _repo(self) -> Any:
        return self._content.repository

    def _unit(self, tenant_id: UUID) -> AbstractContextManager[Any]:
        """One transaction across every repository, ledger and outbox call (Postgres);
        the in-memory doubles have no transaction to share."""
        if isinstance(self._repo, PostgresContentRepository):
            return tenant_unit_of_work(tenant_id)
        return nullcontext()

    def _parent(self, tenant_id: UUID, parent_id: UUID) -> tuple[DraftRecord, ContentBrief]:
        parent = self._repo.get_draft(tenant_id=tenant_id, draft_id=parent_id)
        if parent is None or parent.parent_draft_id is not None:
            raise UnknownDraft(str(parent_id))  # another business's reads the same (RLS)
        brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=parent.brief_id)
        if brief is None or not brief.kind.is_parts_parent:
            raise UnknownDraft(str(parent_id))
        return parent, brief

    def _has_text(self, tenant_id: UUID, parent: DraftRecord) -> bool:
        if parent.status in (DRAFTING, FAILED):
            return False
        variants = self._repo.variants_for(tenant_id=tenant_id, draft_id=parent.id)
        return any((v.fidelity or {}).get("passed") for v in variants)

    def estimated_usd(self, briefs: Sequence[ContentBrief]) -> Decimal:
        """N9: what the parts may cost the team together (preview + final at p95)."""
        total = Decimal(0)
        for brief in briefs:
            media = brief.media
            total += self._weights.generated_video_usd(
                media.duration_seconds,
                reference_videos=len(media.clip_video_keys),
                audio=media.clip_audio,
            )
        return total

    def create_parts(
        self,
        *,
        tenant_id: UUID,
        parent_id: UUID,
        user_id: UUID,
        analysis: ReelAnalysis | None = None,
        windows: Mapping[int, str] | None = None,
    ) -> list[UUID]:
        """Create every part of the parent's plan, or none: the child ids in plan order.

        Refused (nothing written) without the generation queue (`PartsUnavailable`), while
        the parent has no text (`ParentTextMissing`), with a part still to describe
        (`PartNeedsDescription`), an `extend` on a cut of 10 s or less (`ExtendTooShort`),
        when the dollar cap cannot pay their estimate (`PartsOverBudget`, checked once)
        and when the month cannot pay their vistas previas (`NotEnoughCreations`).
        Idempotent: once the parts exist they are returned, never made twice."""
        if not self._queue_enabled():
            raise PartsUnavailable()
        parent, brief = self._parent(tenant_id, parent_id)
        existing = self._repo.parts_of(tenant_id=tenant_id, parent_id=parent_id)
        if existing:
            return [child.id for child in existing]
        if not self._has_text(tenant_id, parent):
            raise ParentTextMissing()
        plan = brief.media.parts
        for index, part in enumerate(plan, start=1):
            if "describe_it" in part.notices and not part.description.strip():
                raise PartNeedsDescription(index)
        check_extend_parts(plan, analysis)
        children: list[ContentBrief] = []
        voice_version, pipeline_version = 0, ""
        for index, part in enumerate(plan, start=1):
            child = _child_brief(brief, part, index, (windows or {}).get(index))
            child, voice_version, pipeline_version = self._content.prepare_new_generation(
                tenant_id=tenant_id, brand_id=parent.brand_id, brief=child
            )
            children.append(child)
        budget = self._repo.budget_state(tenant_id=tenant_id, brand_id=parent.brand_id)
        if budget is not None and budget.hard_stop:
            estimate = self.estimated_usd(children)
            if estimate > budget.remaining_usd:
                raise PartsOverBudget(estimated_usd=estimate, remaining_usd=budget.remaining_usd)
        ids = [uuid4() for _ in children]
        creations = self._content.creations
        charges = [
            PreviewCharge(draft_id=child_id, revision=1, price=weight_for(child))
            for child_id, child in zip(ids, children, strict=True)
        ]
        dispatcher = self._content.dispatcher
        with self._unit(tenant_id) as session:
            if session is not None:
                # two concurrent asks: the parent's row lock serializes them, and the
                # second one finds the first one's parts (never a duplicate part_index)
                session.execute(
                    text("SELECT id FROM content_drafts WHERE id = :p FOR UPDATE"),
                    {"p": parent_id},
                )
            made = self._repo.parts_of(tenant_id=tenant_id, parent_id=parent_id)
            if made:
                return [child.id for child in made]
            if creations is not None:
                # before any row: all of them or none (the ledger checks again under the
                # brand's lock when it charges)
                short = creations.balance(tenant_id=tenant_id, brand_id=parent.brand_id).shortfall(
                    summed_price(charges)
                )
                if short is not None:
                    raise short
            for index, (child_id, child) in enumerate(zip(ids, children, strict=True), start=1):
                self._repo.insert_brief_and_draft(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    brief=child,
                    voice_profile_version=voice_version,
                    pipeline_version=pipeline_version,
                    draft_id=child_id,
                    parent_draft_id=parent_id,
                    part_index=index,
                )
            if creations is not None:
                creations.charge_many(
                    tenant_id=tenant_id, brand_id=parent.brand_id, charges=charges
                )
            if dispatcher is not None:
                for child_id in ids:
                    dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=child_id)
        return ids

    def regenerate_part(
        self,
        *,
        tenant_id: UUID,
        parent_id: UUID,
        part_index: int,
        changes: PartChanges,
        user_id: UUID,
    ) -> UUID:
        """«Crear otra versión» of ONE part: a new brief with the new description and
        photos (the mode stays), then `reject(regenerate=True)` — 1 vista previa at the
        part's `revision + 1`. The siblings are not touched; the versions made before
        keep their own brief. Returns the part's draft id."""
        self._parent(tenant_id, parent_id)
        child = next(
            (
                c
                for c in self._repo.parts_of(tenant_id=tenant_id, parent_id=parent_id)
                if c.part_index == part_index
            ),
            None,
        )
        if child is None:
            raise UnknownDraft(f"{parent_id}#{part_index}")
        old = self._repo.get_brief(tenant_id=tenant_id, brief_id=child.brief_id)
        if old is None or old.media.part is None:
            raise UnknownDraft(str(child.id))
        part = old.media.part
        description = part.description if changes.description is None else changes.description
        description = description.strip()[:PART_DESCRIPTION_MAX]
        notices = tuple(n for n in part.notices if not (n == "describe_it" and description))
        media_update: dict[str, Any] = {
            "part": part.model_copy(update={"description": description, "notices": notices})
        }
        if changes.photo_keys is not None:
            photos = tuple(changes.photo_keys)[:CLIP_MAX_IMAGES]
            media_update["clip_image_keys"] = photos
            media_update["clip_image_roles"] = tuple("product" for _ in photos)
        new = ContentBrief.model_validate(
            {**old.model_dump(), "media": {**old.media.model_dump(), **media_update}}
        )
        with self._unit(tenant_id):
            self._repo.replace_brief(
                tenant_id=tenant_id, draft_id=child.id, user_id=user_id, brief=new
            )
            # a refusal (no vista previa left, a piece mid-generation) rolls the new
            # brief back with it: the part keeps the brief it had
            self._content.reject(
                tenant_id=tenant_id,
                draft_id=child.id,
                reason=f"Pediste otra versión de la parte {part_index}",
                user_id=user_id,
                regenerate=True,
            )
        return child.id

    def parts(self, *, tenant_id: UUID, parent_id: UUID) -> tuple[PartSummary, ...]:
        """«Parte N de M» for the parent's screen: every planned part with its child's
        state (planned before `create_parts`)."""
        _, brief = self._parent(tenant_id, parent_id)
        plan = brief.media.parts
        children = {
            c.part_index: c for c in self._repo.parts_of(tenant_id=tenant_id, parent_id=parent_id)
        }
        out: list[PartSummary] = []
        for index, entry in enumerate(plan, start=1):
            child = children.get(index)
            shown: Any = entry
            if child is not None:
                child_brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=child.brief_id)
                if child_brief is not None and child_brief.media.part is not None:
                    shown = child_brief.media.part
            out.append(
                PartSummary(
                    index=index,
                    total=len(plan),
                    draft_id=None if child is None else child.id,
                    status=PLANNED if child is None else child.status,
                    mode=shown.mode,
                    seconds=shown.seconds,
                    description=shown.description,
                    notices=tuple(shown.notices),
                )
            )
        return tuple(out)


__all__ = [
    "NOTICE_TEXTS",
    "PARENT_TEXT_CAP_TEXT",
    "PARENT_TEXT_DAILY_CAP",
    "PART_MAX_SECONDS",
    "PLANNED",
    "ExtendTooShort",
    "ParentTextCapReached",
    "ParentTextMissing",
    "PartChanges",
    "PartNeedsDescription",
    "PartSummary",
    "PartsOverBudget",
    "PartsRepository",
    "PartsService",
    "PartsUnavailable",
    "check_extend_parts",
    "check_parent_text_cap",
    "is_vertical",
    "mark_parent_dirty",
    "neutral_people",
    "part_label",
    "part_window",
    "plan_from_analysis",
    "shot_description",
]
