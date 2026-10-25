"""Pure rules of «Tu marca» in five steps (m-24848529, MARCA-4).

The founder's decision 6 (2026-10-23): the mandatory Brand Kit is five named steps —
Tus redes, Tu negocio y rubro, Tu logo, Tus colores, Cómo hablas — and everything else
(typography, banned words, the recorded voice, referentes) moves to «Mejora tu marca
(opcional)». This module holds what can be decided without Reflex or a database:

- the step names, their headings and their order;
- how a draft left halfway through either OLD flow (the seven-screen manual one and the
  twelve-screen connect one, saved by position) maps to the new step that holds the same
  data, so both old flows collapse into the same path (`step_from_progress`);
- where a returning owner resumes: the saved step, but never past the first step whose
  required data is still missing (`resume_step`);
- what each step requires to continue (`step_complete`);
- the one example phrase «Cómo hablas» asks for, merged into the kit's `do_examples`
  without losing the ones already there (`with_example_phrase`).

Progress is stored by NAME (architect, 2026-10-23), so a future reorder of the steps
never sends an owner to the wrong screen.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: The flow key this path saves its progress under (`brand_finish.PROGRESS_KEY`).
MINIMAL_FLOW = "minimo"

STEP_SOCIALS = "redes"
STEP_BUSINESS = "negocio"
STEP_LOGO = "logo"
STEP_COLOURS = "colores"
STEP_VOICE = "voz"

#: (name, title, subtitle) in order — the single source of truth for the counter
#: («Paso N de 5») and the heading.
STEPS: tuple[tuple[str, str, str], ...] = (
    (
        STEP_SOCIALS,
        "Tus redes",
        "Escribe tu usuario de Instagram o TikTok y tomamos de ahí tu logo, tus colores "
        "y a qué te dedicas.",
    ),
    (
        STEP_BUSINESS,
        "Tu negocio y rubro",
        "A qué te dedicas, qué te hace distinto y quién te compra.",
    ),
    (STEP_LOGO, "Tu logo", "Lo ponemos en cada publicación que crees."),
    (STEP_COLOURS, "Tus colores", "Los colores con los que te reconocen tus clientes."),
    (
        STEP_VOICE,
        "Cómo hablas",
        "Así escribimos tus publicaciones: como le hablas a tus clientes.",
    ),
)
#: Under the profile read of Tus redes (m-24842969): reading a public profile is not the
#: Meta connection that lets Qualify publish — said once, so the owner is not left
#: wondering why Tus redes asks again later.
PUBLIC_READ_NOTE = (
    "Solo miramos lo que ya es público en tu perfil. Para publicar desde Qualify, "
    "conecta tu Instagram después en Tus redes."
)

STEP_NAMES: tuple[str, ...] = tuple(name for name, _title, _subtitle in STEPS)
TOTAL_STEPS = len(STEPS)
FIRST_STEP = STEP_NAMES[0]
LAST_STEP = STEP_NAMES[-1]

#: The old manual flow's screens, by position (`creative_wizard_pages.STEPS`): ¿Quién es
#: la marca?, ¿Ya tienes logo?, Tu logo, Tipografía, Paleta, ¿Todo correcto?, Así quedó.
_MANUAL_TO_STEP: tuple[str, ...] = (
    STEP_BUSINESS,
    STEP_LOGO,
    STEP_LOGO,
    STEP_COLOURS,  # Tipografía is optional now: its neighbour Paleta takes the owner on
    STEP_COLOURS,
    STEP_VOICE,
    STEP_VOICE,
)
#: The old connect flow's screens, by position (`creative_wizard_pages.CONNECT_STEPS`):
#: Tu cuenta, Esto es lo que vemos, ¿Eres influencer o una marca?, Tu rubro y ubicación,
#: ¿Quién es la marca?, ¿Ya tienes logo?, Tu logo, Tipografía, Paleta, ¿Todo correcto?,
#: ¿Cómo ves estas cuentas?, Así se ve tu cuenta hoy.
_CONNECT_TO_STEP: tuple[str, ...] = (
    STEP_SOCIALS,
    STEP_SOCIALS,
    STEP_BUSINESS,
    STEP_BUSINESS,
    STEP_BUSINESS,
    STEP_LOGO,
    STEP_LOGO,
    STEP_COLOURS,
    STEP_COLOURS,
    STEP_VOICE,
    STEP_VOICE,
    STEP_VOICE,
)
_OLD_FLOWS: dict[str, tuple[str, ...]] = {
    "manual": _MANUAL_TO_STEP,
    "connect": _CONNECT_TO_STEP,
}


def step_index(name: str) -> int:
    """Position of a step (0-based); an unknown name is the first step."""
    try:
        return STEP_NAMES.index(name)
    except ValueError:
        return 0


def clamp_step(name: object) -> str:
    """A step name from the client or the database, or the first step."""
    return name if isinstance(name, str) and name in STEP_NAMES else FIRST_STEP


def next_step(name: str) -> str:
    return STEP_NAMES[min(step_index(name) + 1, TOTAL_STEPS - 1)]


def previous_step(name: str) -> str:
    return STEP_NAMES[max(step_index(name) - 1, 0)]


def step_from_progress(progress: Mapping[str, Any] | None) -> str | None:
    """The new step a saved position stands for — this flow's own (by name) or either
    old flow's (by position, mapped to the step that holds the same data). None when
    there is no usable position."""
    if not progress:
        return None
    flow = str(progress.get("flow", ""))
    raw = progress.get("step")
    if flow == MINIMAL_FLOW:
        return raw if isinstance(raw, str) and raw in STEP_NAMES else None
    mapping = _OLD_FLOWS.get(flow)
    if mapping is None:
        return None
    try:
        position = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    position = max(0, min(position, len(mapping) - 1))
    return mapping[position]


@dataclass(frozen=True)
class KitFacts:
    """What the stored kit and answers already hold — enough to know which step still
    has a gap. Built from the database on entry, so it never depends on the order the
    page's loads land in."""

    socials_answered: bool = False  # a profile was read, or «No tengo redes»
    rubro: str = ""
    positioning: str = ""
    audience: str = ""
    has_logo_answer: bool = False  # files, a brief, or the profile picture as logo
    palette: str = ""
    example: str = ""

    @property
    def business_complete(self) -> bool:
        return bool(self.rubro.strip() and self.positioning.strip() and self.audience.strip())


def first_gap(facts: KitFacts) -> str | None:
    """The first step after Tus redes whose required data is missing; None when the
    five are complete."""
    if not facts.business_complete:
        return STEP_BUSINESS
    if not facts.has_logo_answer:
        return STEP_LOGO
    if not facts.palette.strip():
        return STEP_COLOURS
    if not facts.example.strip():
        return STEP_VOICE
    return None


def resume_step(saved: str | None, facts: KitFacts) -> str:
    """Where an owner coming back opens: the step they were on, but never past the first
    step that still misses data (a draft from an old flow may have walked past an empty
    screen). With no saved position, the first gap — or Tus redes when nothing at all
    was done yet."""
    gap = first_gap(facts)
    if saved is None:
        if not facts.socials_answered and gap == STEP_BUSINESS and not _any_data(facts):
            return FIRST_STEP
        return gap or LAST_STEP
    if saved == STEP_SOCIALS:
        return STEP_SOCIALS
    if gap is None:
        return saved
    return STEP_NAMES[min(step_index(saved), step_index(gap))]


def _any_data(facts: KitFacts) -> bool:
    return (
        any(
            value.strip()
            for value in (
                facts.rubro,
                facts.positioning,
                facts.audience,
                facts.palette,
                facts.example,
            )
        )
        or facts.has_logo_answer
    )


def step_complete(
    name: str,
    *,
    profile_read: bool,
    facts: KitFacts,
) -> bool:
    """What Continuar needs on each step — the same rule the page's gate draws with
    Vars. Tus redes moves on with a read profile (its other way out is «No tengo
    redes»)."""
    if name == STEP_SOCIALS:
        return profile_read
    if name == STEP_BUSINESS:
        return facts.business_complete
    if name == STEP_LOGO:
        return facts.has_logo_answer
    if name == STEP_COLOURS:
        return bool(facts.palette.strip())
    if name == STEP_VOICE:
        return bool(facts.example.strip())
    return False


def step_completes(facts: KitFacts) -> list[bool]:
    """Whether each of the five steps, in order, is answered — what `steps_vm.guard_step`
    needs to keep `?paso=N` from opening past an unanswered step (PASOS-4, N6b). Tus
    redes counts as answered with a read profile or «No tengo redes»."""
    return [
        facts.socials_answered,
        facts.business_complete,
        facts.has_logo_answer,
        bool(facts.palette.strip()),
        bool(facts.example.strip()),
    ]


def logo_answered(has_logo: str, *, has_files: bool, brief: str, from_profile: str) -> bool:
    """Tu logo is answered: the profile picture as logo, an upload on «Sí», or the first
    brief question on «Todavía no» — the page's own gate (`_can_continue`), in Python."""
    if has_logo == from_profile:
        return True
    if has_logo == "si":
        return has_files
    if has_logo == "no":
        return bool(brief.strip())
    return False


#: What a step still needs, said under its controls while Continuar is off (UX review
#: of m-24848529: a button that is off without a reason reads as «se trabó»). Tus redes
#: has none: it shows no Continuar until a profile is read.
MISSING_HINTS: dict[str, str] = {
    STEP_BUSINESS: "Para seguir, responde las tres preguntas de arriba.",
    STEP_LOGO: "Para seguir, sube tu logo o responde la primera pregunta.",
    STEP_COLOURS: "Para seguir, toca la rueda y elige al menos un color.",
    STEP_VOICE: "Para terminar, escribe cómo se lo dirías a un cliente.",
}


def account_country(current: str, account: str | None, known: frozenset[str]) -> str:
    """The country Tu negocio y rubro starts with: what is already there (a read profile,
    a draft), else the account's own country — chosen at signup (m-24842967), so it is
    never asked twice — when the step knows how to name it."""
    if current.strip():
        return current
    code = (account or "").strip().upper()
    return code if code in known else ""


def first_example(do_examples: str) -> str:
    """The phrase «Cómo hablas» shows: the kit's first example, if any."""
    for line in do_examples.splitlines():
        if line.strip():
            return line.strip()
    return ""


def with_example_phrase(do_examples: str, previous: str, phrase: str) -> str:
    """`do_examples` (one per line) with `phrase` in the place of `previous` — the
    phrase this screen wrote before — or first when it was not there. The other
    examples (from a document, or the editor) stay as they were."""
    lines = [line for line in do_examples.splitlines() if line.strip()]
    previous, phrase = previous.strip(), phrase.strip()
    if previous and previous in (line.strip() for line in lines):
        index = next(i for i, line in enumerate(lines) if line.strip() == previous)
        if phrase:
            lines[index] = phrase
        else:
            lines.pop(index)
    elif phrase:
        lines.insert(0, phrase)
    # never two copies of the same phrase
    seen: set[str] = set()
    unique: list[str] = []
    for line in lines:
        key = line.strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)
    return "\n".join(unique)


#: The brandboard file kinds that answer «Tu logo» (`brand_kit_store`): a logo, one of its
#: versions or another element of the brand.
LOGO_FILE_KINDS = frozenset({"logo", "logo_version", "extra"})


def progress_of(connect: Mapping[str, Any] | None, key: str = "progress") -> dict[str, Any]:
    """The saved position inside the `connect` document, or an empty dict."""
    raw = (connect or {}).get(key)
    return dict(raw) if isinstance(raw, Mapping) else {}


def kit_finished(has_kit: bool, progress: Mapping[str, Any]) -> bool:
    """The same rule as `brand_finish.kit_status`: a kit row and no unfinished progress."""
    return has_kit and progress.get("completed") is not False


def facts_from_saved(
    *,
    positioning: str,
    audience: str,
    palette: str,
    do_examples: str,
    connect: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    logo_brief: Mapping[str, Any] | None,
    file_kinds: tuple[str, ...] | list[str],
    progress: Mapping[str, Any] | None,
) -> KitFacts:
    """`KitFacts` from what the database holds for the brand — the kit form's fields, the
    connect flow's answers, the account as read, the logo brief and the brandboard."""
    connect = connect or {}
    progress = progress or {}
    rubro = str(connect.get("rubro_text") or "").strip() or str(connect.get("sector") or "")
    has_logo_answer = (
        any(kind in LOGO_FILE_KINDS for kind in file_kinds)
        or bool(str((logo_brief or {}).get("style", "")).strip())
        or bool(progress.get("logo_from_profile"))
    )
    return KitFacts(
        socials_answered=bool((profile or {}).get("username"))
        or bool(progress.get("started_without_socials")),
        rubro=rubro,
        positioning=positioning,
        audience=audience,
        has_logo_answer=has_logo_answer,
        palette=palette,
        example=first_example(do_examples),
    )
