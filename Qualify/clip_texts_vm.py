"""«Texto en pantalla» of «Arma tu video» (ED-13 m-25029108, D-T2 «Sí, hasta 3 textos»):
the pure rules of the editor's texts — no Reflex import, tested offline.

A promo usually carries «2×1 hoy» at the start and «Pide al 300…» at the end, so the
Clip takes up to `TEXTS_MAX` texts (contract v2, `TEXT_LAYERS_MAX`). Each text is a
**text use**, the same pattern as ED-04's effect uses (`clip_editor_vm`, «uses»):

``{"uid", "text", "place", "start", "end", "blocks", "fade", "layout", "motion_in",
"motion_out", "exit_set", "box_color", "text_color"}``

- ``uid`` — ``t1``, ``t2``…; its timeline block is ``texto-t1`` (`text_block_id`).
- ``text`` — what the owner typed, at most `contract.VIDEO_TEXT_MAX` characters.
- ``place`` — ``top`` / ``middle`` / ``bottom`` («Arriba · En el medio · Abajo»).
- ``start`` / ``end`` — seconds of the final video; ``end`` `OPEN_END` (-1) = until the
  video ends, whatever its length (a text put from the playhead with «+ Texto», and
  ED-10's one text migrated). Deivid (2026-11-20): the editor opens with no text, as
  today — the generated hook is never copied in; the owner taps «+ Texto» and writes.
- ``blocks`` — the «Fotos y videos» blocks it is stuck to. Stuck, its seconds are its
  blocks': it follows them when they move, are cut, trimmed or removed. ``[]`` = its own
  seconds (after a drag, ←/→ or «− ½ s / + ½ s», as an effect). The panel no longer
  asks «¿En qué partes va?» (Deivid 2026-11-23): nothing on screen writes ``blocks``
  any more and «+ Texto» puts a text with its own seconds, but a text that already
  carries them is still read and followed (`resolve_text_uses`, `follow_text_media`)
  — defensive and cheap.
- ``fade`` — how long it takes to appear, `FADE_MIN`–`FADE_MAX` in steps of `FADE_STEP`,
  `FADE_DEFAULT` when not chosen (EF-05 #724, `VideoTextLayer.fade_s`; Deivid: the owner
  chooses it). ED-13 D: one length for the entrance and the exit («Tarda en entrar y
  salir»), each at most a third of the text's time (`contract.motion_seconds`).
- ``layout`` — its background (Deivid 2026-11-23, «Fondo de las letras»): «Sombra»
  (`scrim`, the default), «Franja» (`band`), «Recuadro de tu color» (`brand_fill`) or
  «Sin fondo» (`shadow`) — `contract.VIDEO_TEXT_LAYOUTS`.
- ``box_color`` — the colour picked for «Franja» / «Recuadro de tu color» (Deivid
  2026-11-23: the Brand Kit's colours, black or white; `box_color_chips`), `#RRGGBB`;
  "" = that background's default (black strip, the brand's main colour). A new
  background starts on its default.
- ``text_color`` — the letters' colour picked for «Sin fondo» (Deivid 2026-11-23, round 3:
  the same chips), `#RRGGBB`; "" = white. A new background starts on white again.
- ``motion_in`` / ``motion_out`` — how it enters («Aparece · Sube · Crece · Letra por
  letra») and leaves («Desaparece · Baja · Se encoge · De golpe»); a new text enters
  and leaves with a fade. ``exit_set``: the owner chose the exit — until then it goes
  with the entrance (`EXIT_WITH`).

The times are changed on the timeline only (A1, Deivid 2026-11-23: the block's handles,
←/→).

Two texts in the same place at the same time would draw one over the other: the screen
says so (`clash_line`) and «Siguiente» waits until it is solved (`next_blocked`). The
recipe takes the texts in time order (`text_layers_for_recipe`).

Subtitles (Deivid 2026-11-23: «cuando pase eso quiero que se bloquee el poner el texto
abajo»): the Clip's «Agregar subtítulos con tu texto» lays its words at the bottom, so
with it on «Abajo» is off for a text (`place_offered`, `set_place`) and a text already
there is never moved by itself: it shows the warning and stops «Siguiente»
(`texts_problem`) until the owner moves it. The flag is an argument (`subtitles`), never
read from anywhere.

Reused from `clip_editor_vm` (imported, never copied): `part_groups`, `group_span`,
`block_spans`, `media_total`, `remap_effect_blocks` (renaming a cut piece's blocks works
for any use); from `ui.timeline_vm`: `snap` and `clock`, so a text's times read like every
other block's.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

from . import clip_editor_vm as cevm
from . import editor_preview_contract as contract
from .ui import timeline_vm as tl

# -- limits ------------------------------------------------------------------------------

#: D-T2: at most this many texts over the Clip (each group of blocks side by side counts).
TEXTS_MAX = contract.TEXT_LAYERS_MAX
TEXT_MAX_CHARS = contract.VIDEO_TEXT_MAX
PLACES: tuple[str, ...] = contract.VIDEO_TEXT_PLACES
DEFAULT_PLACE = "bottom"
#: With subtitles on, «Abajo» is theirs: a new text goes in the middle (UX, 2026-11-23).
SUBTITLES_PLACE = "bottom"
DEFAULT_PLACE_WITH_SUBTITLES = "middle"
#: The server's refusal of a text «Abajo» with subtitles on (`validate_recipe`, field
#: `text_layers`): `clip_editor_vm.refusal_line` says `SUBTITLES_BOTTOM_LINE` for it.
SUBTITLES_CODE: contract.RecipeProblem = "text_bottom_with_subtitles"
#: `end` of a text that lasts until the video ends (today's `clip_text_end` -1).
OPEN_END = -1.0
#: EF-05: how long a text takes to appear (s).
FADE_MIN = contract.VIDEO_TEXT_FADE_MIN_S
FADE_MAX = contract.VIDEO_TEXT_FADE_MAX_S
FADE_DEFAULT = contract.VIDEO_TEXT_FADE_DEFAULT_S
FADE_STEP = 0.1
#: ←/→ and «− ½ s / + ½ s» move a text by half a second; it lasts at least 1 s.
STEP_S = tl.STEP_S
MIN_S = contract.SEGMENT_MIN_SECONDS
#: The preview's tolerance for criterion 4 («cada texto solo en sus segundos ±0,1 s»).
PREVIEW_TOLERANCE_S = 0.1

TEXT_BLOCK_PREFIX = "texto-"
#: The panel's field (its `<label>` points at it; «Editar texto» and «+ Texto» put
#: the focus there).
FIELD_ID = "clip-text-field"
UID_PREFIX = "t"

# -- words (qualify-copy-es) ---------------------------------------------------------------

#: Deivid (ticket): the tab and the block are called «Texto en pantalla», with this help.
TITLE = cevm.TEXT_TITLE
HELP = "Estas palabras se ven encima de tu video."
FIELD_LABEL = "Qué dice"
EXAMPLE = cevm.TEXT_EXAMPLE
PLACE_LABEL = cevm.TEXT_PLACE_LABEL
PLACE_TEXTS: dict[str, str] = dict(cevm.TEXT_PLACES)
#: The place inside a sentence («dos textos arriba»).
PLACE_WORDS: dict[str, str] = {"top": "arriba", "middle": "en el medio", "bottom": "abajo"}
#: Deivid 2026-11-23 (A1): no «Empieza»/«Termina» in the panel — the times change on the
#: timeline (its block's handles); this line says when it shows and how to change it.
FADE_LABEL = "Tarda en entrar y salir"
FADE_IN_LABEL = "Tarda en entrar"
FADE_OUT_LABEL = "Tarda en salir"
FADE_LESS_NAME = "Que entre y salga más rápido"
FADE_MORE_NAME = "Que entre y salga más despacio"
FADE_IN_LESS_NAME = "Que entre más rápido"
FADE_IN_MORE_NAME = "Que entre más despacio"
FADE_OUT_LESS_NAME = "Que salga más rápido"
FADE_OUT_MORE_NAME = "Que salga más despacio"

# -- ED-13 C: the text's background («Fondo de las letras») --------------------------------

LAYOUT_DEFAULT = "scrim"
LAYOUT_TITLE = "Fondo de las letras"
#: `(layout id, name, what it is)`, in the order of the 2×2 grid (Deivid 2026-11-23).
LAYOUT_CHOICES: tuple[tuple[str, str, str], ...] = (
    ("scrim", "Sombra", "Tu video se oscurece detrás de las letras."),
    ("band", "Franja", "Una franja de lado a lado, del color que elijas."),
    (
        "brand_fill",
        "Recuadro de tu color",
        "Un recuadro justo detrás de las letras, del color que elijas.",
    ),
    # Deivid 2026-11-23: «Sin fondo» has no shadow nor outline any more
    ("shadow", "Sin fondo", "Solo tus letras, limpias, directo sobre tu video."),
)
LAYOUT_NAMES: dict[str, str] = {key: name for key, name, _what in LAYOUT_CHOICES}
#: Under the grid while «Sin fondo» is chosen (UX 2026-11-23): white letters with nothing
#: behind them can get lost on a light video — round 3: the owner can pick dark ones.
SHADOW_NOTE = (
    "Si tu video es claro, las letras pueden perderse: elige un color oscuro para tus letras."
)

# -- ED-13 (Deivid 2026-11-23): the colour of «Franja» and «Recuadro de tu color» -----------

#: The backgrounds whose colour the owner picks (`VideoTextLayer.box_color`).
BOX_COLOR_LAYOUTS: tuple[str, ...] = contract.VIDEO_TEXT_BOX_COLOR_LAYOUTS
#: The chips' visible title (their radiogroup's `aria-labelledby`), per background.
BOX_COLOR_TITLES: dict[str, str] = {
    "band": "Color de la franja",
    "brand_fill": "Color del recuadro",
    # round 3 (Deivid 2026-11-23): «Sin fondo» picks its letters' colour with the same chips
    "shadow": "Color de las letras",
}
#: The background whose LETTERS' colour the owner picks (`VideoTextLayer.text_color`).
TEXT_COLOR_LAYOUTS: tuple[str, ...] = contract.VIDEO_TEXT_TEXT_COLOR_LAYOUTS
#: Every background that shows colour chips.
CHIP_LAYOUTS: tuple[str, ...] = (*BOX_COLOR_LAYOUTS, *TEXT_COLOR_LAYOUTS)
TEXT_COLOR_CHANGED_LINE = "Cambiaste el color de las letras."
#: After the brand's colours: black (the strip's own, `VIDEO_TEXT_BAND_COLOR`) and white.
BLACK = contract.VIDEO_TEXT_BAND_COLOR
WHITE = "#FFFFFF"
#: The brand's colours are named by their role, never by their hex (UX 2026-11-23).
_BRAND_COLOR_NAMES: tuple[str, ...] = (
    "Color principal de tu marca",
    "Segundo color de tu marca",
    "Tercer color de tu marca",
)
BOX_COLOR_CHANGED_LINE = "Cambiaste el color del fondo."
#: A box on its default colour when that colour is none of the chips (a brand without a
#: palette, «Recuadro de tu color»).
BOX_COLOR_DEFAULT_NAME = "el color de siempre"
_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")


def brand_color_name(index: int) -> str:
    """The accessible name of the brand's colour number `index` (0 = its main one)."""
    if 0 <= index < len(_BRAND_COLOR_NAMES):
        return _BRAND_COLOR_NAMES[index]
    return f"Color {int(index) + 1} de tu marca"


def _short_name(name: str) -> str:
    """«Color principal de tu marca» → «color principal» (the folded summary's words)."""
    short = name.removesuffix(" de tu marca")
    return short[:1].lower() + short[1:]


def normalize_box_color(value: object) -> str:
    """A picked colour as `#RRGGBB` in capitals; "" = none (the background's default)."""
    text = str(value or "").strip()
    return text.upper() if _HEX6.match(text) else ""


def box_color_chips(palette: Sequence[str]) -> list[tuple[str, str]]:
    """The colours offered for a box, `(hex, name)`: the Brand Kit's palette in its order
    (each valid colour once, named by its place), then black and white unless the palette
    already has them. An empty palette leaves black and white."""
    chips: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(palette):
        if not contract.is_color(raw):
            continue
        color = contract.opaque(str(raw))
        if color in seen:
            continue
        seen.add(color)
        chips.append((color, brand_color_name(index)))
    for color, name in ((BLACK, "Negro"), (WHITE, "Blanco")):
        if color not in seen:
            seen.add(color)
            chips.append((color, name))
    return chips


def box_color_of(use: Mapping[str, object], palette: Sequence[str] = ()) -> str:
    """The colour `use`'s box is drawn in now: the picked one, else its background's
    default ("" = a background without a box)."""
    layout = normalize_layout(use.get("layout"))
    if layout not in BOX_COLOR_LAYOUTS:
        return ""
    picked = normalize_box_color(use.get("box_color"))
    return picked or contract.default_box_color(layout, contract.palette_of(palette))


def text_color_of(use: Mapping[str, object]) -> str:
    """Round 3: the colour «Sin fondo»'s letters are drawn in now — the picked one, else
    white ("" = another background: its letters are not the owner's to pick)."""
    if normalize_layout(use.get("layout")) not in TEXT_COLOR_LAYOUTS:
        return ""
    return normalize_box_color(use.get("text_color")) or WHITE


def chip_color_of(use: Mapping[str, object], palette: Sequence[str] = ()) -> str:
    """The colour the chips show chosen: the box's («Franja», «Recuadro de tu color») or
    the letters' («Sin fondo»); "" for «Sombra», which has no chips."""
    return box_color_of(use, palette) or text_color_of(use)


def box_color_name(use: Mapping[str, object], palette: Sequence[str] = ()) -> str:
    """The chosen chip's name («Color principal de tu marca», «Negro»…); "" without chips."""
    color = chip_color_of(use, palette)
    if not color:
        return ""
    names = dict(box_color_chips(palette))
    return names.get(color.upper(), BOX_COLOR_DEFAULT_NAME)


def box_color_rows(use: Mapping[str, object], palette: Sequence[str] = ()) -> list[dict[str, str]]:
    """The chips under «Franja» / «Recuadro de tu color» ([] for the other backgrounds):
    ``value`` the hex, ``name`` its accessible name, ``on`` "1" for the colour the box is
    drawn in now (the default's chip while nothing is picked), ``ink`` the colour its
    check is drawn in (`contract.box_ink`, legible on it). Round 3: «Sin fondo» shows the
    same chips for its letters (white chosen while nothing is picked)."""
    current = chip_color_of(use, palette).upper()
    if not current:
        return []
    return [
        {
            "value": color,
            "name": name,
            "on": "1" if color == current else "",
            "ink": contract.box_ink(color),
        }
        for color, name in box_color_chips(palette)
    ]


# -- ED-13 D: how it enters and leaves («Cómo entra y sale») ------------------------------

MOTION_TITLE = "Cómo entra y sale"
MOTION_IN_TITLE = "Cómo entra"
MOTION_OUT_TITLE = "Cómo sale"
MOTION_IN_DEFAULT = contract.VIDEO_TEXT_MOTION_IN_DEFAULT
#: The editor's default exit for a new text (the schema's is «De golpe», `none`).
MOTION_OUT_DEFAULT = "fade"
MOTION_IN_CHOICES: tuple[tuple[str, str], ...] = (
    ("fade", "Aparece"),
    ("slide", "Sube"),
    ("zoom", "Crece"),
    ("typewriter", "Letra por letra"),
)
MOTION_OUT_CHOICES: tuple[tuple[str, str], ...] = (
    ("fade", "Desaparece"),
    ("slide", "Baja"),
    ("zoom", "Se encoge"),
    ("none", "De golpe"),
)
MOTION_IN_NAMES: dict[str, str] = dict(MOTION_IN_CHOICES)
MOTION_OUT_NAMES: dict[str, str] = dict(MOTION_OUT_CHOICES)
#: The exit that goes with each entrance, until the owner chooses one (`exit_set`).
EXIT_WITH: dict[str, str] = {"fade": "fade", "slide": "slide", "zoom": "zoom", "typewriter": "fade"}
TYPEWRITER = "typewriter"
TYPEWRITER_MAX = contract.VIDEO_TEXT_TYPEWRITER_MAX_CHARS
TYPEWRITER_SLOW = "Tu video tardará un poco más en estar listo."
#: A text that «Letra por letra» no longer fits (written longer after choosing it).
TYPEWRITER_TOO_LONG_LINE = (
    f"«Letra por letra» es solo para textos de hasta {TYPEWRITER_MAX} letras. "
    "Acorta tu texto o elige otra forma de entrar."
)


#: The server's refusals of a text's motion (`validate_recipe`, ED-13):
#: `clip_editor_vm.refusal_line` says these words for them.
TYPEWRITER_CODE: contract.RecipeProblem = "typewriter_text_too_long"
MOTION_CODE: contract.RecipeProblem = "unknown_text_motion"
MOTION_REFUSED_LINE = (
    "No pudimos preparar cómo entra o sale uno de tus textos. "
    "Elígelo de nuevo en «Cómo entra y sale» y vuelve a intentarlo."
)
#: The server's refusal of a text's background colour (ED-13, `bad_text_box_color`).
BOX_COLOR_CODE: contract.RecipeProblem = "bad_text_box_color"
BOX_COLOR_REFUSED_LINE = (
    "No pudimos usar el color del fondo de uno de tus textos. "
    "Elígelo de nuevo en «Fondo de las letras» y vuelve a intentarlo."
)
#: The server's refusal of a text's letters colour (ED-13 round 3, `bad_text_color`).
TEXT_COLOR_CODE: contract.RecipeProblem = "bad_text_color"
TEXT_COLOR_REFUSED_LINE = (
    "No pudimos usar el color de las letras de uno de tus textos. "
    "Elígelo de nuevo en «Fondo de las letras» y vuelve a intentarlo."
)


# -- ED-13 round 4 (Deivid 2026-11-23: «3 tamaños»): the letters' size -----------------------

SIZE_TITLE = "Tamaño de las letras"
SIZE_DEFAULT = contract.VIDEO_TEXT_SIZE_DEFAULT
SIZE_CHOICES: tuple[tuple[str, str], ...] = (
    ("small", "Pequeña"),
    ("medium", "Mediana"),
    ("large", "Grande"),
)
SIZE_NAMES: dict[str, str] = dict(SIZE_CHOICES)
LARGE = "large"
LARGE_MAX = contract.VIDEO_TEXT_LARGE_MAX_CHARS
#: Under «Grande» while it is off (option A: a long text does not fit it).
LARGE_NOTE = "Tu texto es largo: con Grande no cabe. Acórtalo para usarlo."
#: A text written longer while «Grande»: it goes back to «Mediana» and says so.
SIZE_DOWN_LINE = "Tu texto es largo: lo pasamos a Mediana para que quepa."
#: Under the field (Deivid 2026-11-24) when a word is wider than the screen at its size's
#: smallest letters — the final video's `word_too_wide`, measured in the browser
#: (`assets/text-fit.js`); `{word}` is that word (cut with «…» past 24 letters).
WIDE_WORD_LINE = (
    "Tu texto tiene una palabra demasiado larga para la pantalla: «{word}». "
    "Cámbiala por una más corta o pártela en dos."
)
SIZE_CHANGED_LINE = "Cambiaste el tamaño de las letras."
#: The server's refusals of a text's size (`unknown_text_size`, `text_too_long_for_large`).
SIZE_CODE: contract.RecipeProblem = "unknown_text_size"
LARGE_CODE: contract.RecipeProblem = "text_too_long_for_large"
SIZE_REFUSED_LINE = (
    "No pudimos usar el tamaño de las letras de uno de tus textos. "
    "Elígelo de nuevo en «Tamaño de las letras» y vuelve a intentarlo."
)
LARGE_REFUSED_LINE = (
    "Uno de tus textos es largo para el tamaño Grande. "
    "Acórtalo o elige Mediana en «Tamaño de las letras»."
)


def normalize_size(value: object) -> str:
    """A use stored before the size was chosen is «Mediana»."""
    return str(value) if str(value) in contract.VIDEO_TEXT_SIZES else SIZE_DEFAULT


def large_allowed(text: object) -> bool:
    """«Grande» takes this text (up to `LARGE_MAX` characters)."""
    return contract.large_fits(str(text or ""))


def size_choice(size: object) -> str:
    """«Tamaño: Mediana» — the folded summary of «Tamaño de las letras»."""
    return f"Tamaño: {SIZE_NAMES[normalize_size(size)]}"


def typewriter_note(length: int) -> str:
    """Under «Letra por letra» while it is off: why, with the text's own count."""
    return f"Solo para textos de hasta {TYPEWRITER_MAX} letras. El tuyo tiene {int(length)}."


def cut_note(visible: float) -> str:
    """The animation is shorter than chosen (a third of the text's time at most)."""
    return (
        f"Tu texto dura {contract.seconds_text(visible)} s: "
        "la animación se acorta para que se alcance a leer."
    )


def time_line(start: float, end: float) -> str:
    """A1: when the text shows, and where to change it (under the field)."""
    return (
        f"Se ve de {tl.clock(start)} a {tl.clock(end)}. "
        "Para cambiarlo, arrastra las puntas de su bloque, abajo."
    )


DONE = "Listo"
ADD = "+ Texto"
EDIT = cevm.TEXT_EDIT
REMOVE = cevm.REMOVE
#: The chosen text's bar («Editar texto» · «Quitar»), as `timeline_vm.ACTIONS["text"]`.
ACTIONS: tuple[tuple[str, str], ...] = ((EDIT, "pencil"), (REMOVE, "trash-2"))
#: «+ Texto» off with 3 texts (criterion 2): why, and what to do.
TEXTS_FULL = f"Tu video puede tener hasta {TEXTS_MAX} textos. Quita uno para poner otro."
NEEDS_MEDIA = cevm.NEEDS_MEDIA
TEXT_REMOVED_LINE = cevm.TEXT_REMOVED_LINE
TEXT_TIME_LINE = cevm.TEXT_TIME_LINE
#: Deivid 2026-11-23 (words agreed with the server): under «Abajo» while subtitles are on,
#: what stops «Siguiente» for a text left there, and the server's refusal
#: `text_bottom_with_subtitles` (`clip_editor_vm.refusal_line`).
SUBTITLES_BOTTOM_LINE = (
    "Abajo se ven los subtítulos y tu texto se taparía. Elige otra posición o apaga los subtítulos."
)
#: Beside the control of a text that was «Abajo» when the subtitles were turned on (it is
#: never moved by itself).
SUBTITLES_COVERED_LINE = "Este texto queda debajo de los subtítulos."
#: The same, in «Dónde va el texto»'s folded summary («Abajo, debajo de los subtítulos»).
PLACE_COVERED_WORDS = "debajo de los subtítulos"


def too_many_texts_line(count: int) -> str:
    """Before «Siguiente»: a block moved under a text split it into more than fit."""
    return (
        f"Tu video tiene {int(count)} textos y puede tener hasta {TEXTS_MAX}. "
        "Quita uno para seguir."
    )


def clash_line(place: str) -> str:
    """The ticket's warning: two texts in the same place at the same time."""
    where = PLACE_WORDS.get(place, PLACE_WORDS[DEFAULT_PLACE])
    return f"Aquí se verían dos textos {where}. Pon uno en otro lugar o en otro momento."


def default_place(*, subtitles: bool = False) -> str:
    """Where a new text goes: «Abajo», or «En el medio» while the subtitles take the
    bottom."""
    return DEFAULT_PLACE_WITH_SUBTITLES if subtitles else DEFAULT_PLACE


def place_offered(place: str, *, subtitles: bool = False) -> bool:
    """A place the owner may choose now: any of the three, but «Abajo» while subtitles
    are on."""
    return place in PLACES and not (subtitles and place == SUBTITLES_PLACE)


def focus_field_script() -> str:
    """The focus to the panel's field once it is on screen («+ Texto», «Editar
    texto»): the side panel opens first, so it waits a moment."""
    return (
        "window.setTimeout(function () {"
        f" var f = document.getElementById('{FIELD_ID}'); if (f) f.focus();"
        " }, 120)"
    )


def fade_text(value: float) -> str:
    """«0,5 s», «1 s» (the choice as the owner reads it)."""
    return f"{contract.seconds_text(normalize_fade(value))} s"


def fade_line(value: float, label: str = FADE_LABEL) -> str:
    """The animation's length in the panel (Deivid 2026-11-23): «Tarda en entrar y salir:
    0,5 s» (or «Tarda en entrar» when it leaves at once)."""
    return f"{label}: {fade_text(value)}"


def fade_words(motion_in: str, motion_out: str) -> tuple[str, str, str]:
    """What the length row says and its buttons' names, by what it changes: the entrance
    and the exit; the entrance alone when it leaves «De golpe»; the exit alone with
    «Letra por letra» (whose entrance takes its own time); `("", "", "")` when it changes
    nothing (both)."""
    typing = motion_in == TYPEWRITER
    still = motion_out == "none"
    if typing and still:
        return "", "", ""
    if typing:
        return FADE_OUT_LABEL, FADE_OUT_LESS_NAME, FADE_OUT_MORE_NAME
    if still:
        return FADE_IN_LABEL, FADE_IN_LESS_NAME, FADE_IN_MORE_NAME
    return FADE_LABEL, FADE_LESS_NAME, FADE_MORE_NAME


def fade_can_step(value: float, delta: float) -> bool:
    """«− 0,1 s» / «+ 0,1 s» is on: one more step stays inside 0,3–1 s."""
    current = normalize_fade(value)
    if delta < 0:
        return current > FADE_MIN + 1e-6
    return current < FADE_MAX - 1e-6


def step_fade(
    uses: Sequence[Mapping[str, object]], uid: str, delta: float
) -> list[dict[str, object]]:
    """«− 0,1 s» / «+ 0,1 s»: the fade one step shorter or longer, never out of 0,3–1 s."""
    use = next((u for u in uses if str(u.get("uid")) == uid), None)
    if use is None:
        return [dict(u) for u in uses]
    current = normalize_fade(use.get("fade"))
    return set_fade(uses, uid, current + (FADE_STEP if delta > 0 else -FADE_STEP))


def fade_choices() -> list[dict[str, str]]:
    """«Tarda en aparecer»'s options, 0,3 s to 1 s: ``value`` (dot decimal, for the
    control) and ``text``."""
    steps = round((FADE_MAX - FADE_MIN) / FADE_STEP)
    out = []
    for n in range(steps + 1):
        value = round(FADE_MIN + n * FADE_STEP, 1)
        out.append({"value": fade_value(value), "text": fade_text(value)})
    return out


def fade_value(value: float) -> str:
    """A fade as the control's value: «0.5», «1.0»."""
    return f"{normalize_fade(value):.1f}"


# -- the model -----------------------------------------------------------------------------


def text_block_id(uid: str) -> str:
    """The timeline block of a text: `texto-t2`."""
    return TEXT_BLOCK_PREFIX + str(uid)


def text_uid(block_id: str) -> str:
    """The text a block id names ("" = not a text block)."""
    if not str(block_id).startswith(TEXT_BLOCK_PREFIX):
        return ""
    uid = str(block_id)[len(TEXT_BLOCK_PREFIX) :]
    return uid if uid.startswith(UID_PREFIX) else ""


def new_text_uid(uses: Sequence[Mapping[str, object]], taken: Sequence[str] = ()) -> str:
    """The next free text id (`t1`, `t2`…)."""
    used = {str(u.get("uid") or "") for u in uses} | set(taken)
    n = 1
    while f"{UID_PREFIX}{n}" in used:
        n += 1
    return f"{UID_PREFIX}{n}"


def _num(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        number = float(value)
    except ValueError:
        return default
    return number if math.isfinite(number) else default


def normalize_fade(value: object) -> float:
    """A fade between `FADE_MIN` and `FADE_MAX`, on the 0,1 s grid; anything unreadable
    is `FADE_DEFAULT`."""
    number = _num(value, FADE_DEFAULT)
    number = min(max(number, FADE_MIN), FADE_MAX)
    return round(round(number / FADE_STEP) * FADE_STEP, 1)


def normalize_place(value: object) -> str:
    return str(value) if str(value) in PLACES else DEFAULT_PLACE


def normalize_layout(value: object) -> str:
    """One of `contract.VIDEO_TEXT_LAYOUTS`; anything else is «Sombra» (`scrim`)."""
    return str(value) if str(value) in contract.VIDEO_TEXT_LAYOUTS else LAYOUT_DEFAULT


def normalize_motion_in(value: object) -> str:
    return str(value) if str(value) in contract.VIDEO_TEXT_MOTIONS_IN else MOTION_IN_DEFAULT


def normalize_motion_out(value: object) -> str:
    """A use without an exit (one put before ED-13 chose it) leaves with the editor's
    default, «Desaparece»."""
    return str(value) if str(value) in contract.VIDEO_TEXT_MOTIONS_OUT else MOTION_OUT_DEFAULT


def normalize_text(value: object) -> str:
    """What was typed, cut at `TEXT_MAX_CHARS` (spaces kept: the field is being typed)."""
    return str(value or "")[:TEXT_MAX_CHARS]


def normalize_text_use(raw: Mapping[str, object], uid: str = "") -> dict[str, object]:
    """A text use as the state keeps it: every key there, each value valid. ``end`` under
    0 (or missing) is `OPEN_END`; a start under 0 is 0."""
    start = max(_num(raw.get("start"), 0.0), 0.0)
    end = _num(raw.get("end"), OPEN_END)
    blocks_raw = raw.get("blocks") or []
    blocks = [str(b) for b in blocks_raw if str(b)] if isinstance(blocks_raw, list | tuple) else []
    return {
        "uid": str(raw.get("uid") or uid),
        "text": normalize_text(raw.get("text")),
        "place": normalize_place(raw.get("place")),
        "start": round(start, 2),
        "end": OPEN_END if end < 0 else round(end, 2),
        "blocks": list(dict.fromkeys(blocks)),
        "fade": normalize_fade(raw.get("fade")),
        # ED-13 C/D: its background, how it enters and leaves, and whether the owner
        # chose the exit (until then it goes with the entrance, `EXIT_WITH`)
        "layout": normalize_layout(raw.get("layout")),
        "motion_in": normalize_motion_in(raw.get("motion_in")),
        "motion_out": normalize_motion_out(raw.get("motion_out")),
        "exit_set": bool(raw.get("exit_set")),
        # ED-13 (2026-11-23): the colour picked for «Franja» / «Recuadro de tu color»,
        # "" = that background's default (a use stored before it reads as the default)
        "box_color": normalize_box_color(raw.get("box_color")),
        # round 3: «Sin fondo»'s letters, "" = white
        "text_color": normalize_box_color(raw.get("text_color")),
        # round 4: the letters' size (a use stored before it is «Mediana»)
        "size": normalize_size(raw.get("size")),
    }


def normalize_text_uses(raws: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Every use normalized, each with its own id (a missing or repeated one gets a new
    one). Never cut at `TEXTS_MAX`: past it the screen says so (`texts_problem`)."""
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raws:
        if not isinstance(raw, Mapping):
            continue
        use = normalize_text_use(raw)
        uid = str(use["uid"])
        if not uid.startswith(UID_PREFIX) or uid in seen:
            uid = new_text_uid(out, [*seen, *(str(r.get("uid") or "") for r in raws)])
            use["uid"] = uid
        seen.add(uid)
        out.append(use)
    return out


def _blocks(use: Mapping[str, object]) -> list[str]:
    raw = use.get("blocks") or []
    return [str(b) for b in raw] if isinstance(raw, list | tuple) else []


def is_open(use: Mapping[str, object]) -> bool:
    """The text lasts until the video ends."""
    return _num(use.get("end"), OPEN_END) < 0


# -- creating ------------------------------------------------------------------------------


def add_reason(uses: Sequence[Mapping[str, object]], media: Sequence[Mapping[str, object]]) -> str:
    """Why «+ Texto» is off now ("" = it is on): nothing to put it over, or 3 texts
    already (criterion 2)."""
    if not media or cevm.media_total(media) <= 0:
        return NEEDS_MEDIA
    if len(uses) >= TEXTS_MAX:
        return TEXTS_FULL
    return ""


def latest_start(total: float) -> float:
    """The latest start on the ½ s grid that still leaves 1 s of text."""
    return max(math.floor((float(total) - MIN_S) / STEP_S + 1e-6) * STEP_S, 0.0)


def text_from_playhead(
    uses: Sequence[Mapping[str, object]],
    media: Sequence[Mapping[str, object]],
    *,
    playhead: float,
    text: str = "",
    place: str = DEFAULT_PLACE,
    fade: float = FADE_DEFAULT,
) -> tuple[list[dict[str, object]], str, str]:
    """The ticket's «+ Texto»: a text from the playhead (on the ½ s grid) to the end of
    the video. `(uses, uid of the new one, "")`, or `(uses as they were, "", why not)`."""
    why = add_reason(uses, media)
    current = [dict(u) for u in uses]
    if why:
        return current, "", why
    total = cevm.media_total(media)
    start = min(max(tl.snap(float(playhead)), 0.0), latest_start(total))
    uid = new_text_uid(current)
    use = normalize_text_use(
        {"uid": uid, "text": text, "place": place, "start": start, "end": OPEN_END, "fade": fade}
    )
    return [*current, use], uid, ""


def migrate_legacy_text(
    *,
    text: str,
    place: str = DEFAULT_PLACE,
    start: float = 0.0,
    end: float = OPEN_END,
    uses: Sequence[Mapping[str, object]] = (),
) -> list[dict[str, object]]:
    """A session saved with ED-10's one text (`clip_overlay_text`, `clip_text_place`,
    `clip_text_start`, `clip_text_end`) as text 1 of the list — its own seconds (not
    stuck: it was never stuck), an `end` -1 still open. Already migrated (`uses` holds
    texts) or nothing typed: the list as it is."""
    current = normalize_text_uses(uses)
    if current or not str(text or "").strip():
        return current
    return [
        # ED-10's text left at once (it never faded out): it keeps doing so
        normalize_text_use(
            {
                "uid": "t1",
                "text": text,
                "place": place,
                "start": start,
                "end": end,
                "motion_out": "none",
            },
        )
    ]


# -- following «Fotos y videos» ------------------------------------------------------------


def _inside(start: float, end: float, total: float) -> tuple[float, float]:
    """A text's own seconds inside a video of `total` s: an open end (or one past the
    video) is the end; never under 1 s (§3.5)."""
    finish = float(total) if end < 0 else min(float(end), float(total))
    begin = min(max(float(start), 0.0), max(finish - MIN_S, 0.0))
    return begin, max(finish, begin)


def resolve_text_uses(
    uses: Sequence[Mapping[str, object]], media: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    """Each text at its seconds NOW: a stuck one from its blocks' places (a block moved,
    cut or trimmed moves it), one with its own seconds kept inside the video. A stuck
    text whose blocks all left the timeline is gone. `blocks` keeps only those still
    there; `open` says it lasts to the end (the recipe leaves that end open)."""
    spans = cevm.block_spans(media)
    total = cevm.media_total(media)
    out: list[dict[str, object]] = []
    for use in normalize_text_uses(uses):
        stuck = _blocks(use)
        present = [b for b in stuck if b in spans]
        if stuck and not present:
            continue
        if present:
            start, end = cevm.group_span(spans, present)
            open_end = False
        else:
            start, end = _inside(float(use["start"]), float(use["end"]), total)  # type: ignore[arg-type]
            open_end = is_open(use)
        out.append(
            {
                **use,
                "start": round(start, 2),
                "end": round(end, 2),
                "blocks": present,
                "open": open_end,
            }
        )
    return out


def follow_text_media(
    uses: Sequence[Mapping[str, object]],
    media: Sequence[Mapping[str, object]],
    mapping: Mapping[str, Sequence[str]] | None = None,
) -> tuple[list[dict[str, object]], int]:
    """The texts after «Fotos y videos» changed (moved, cut, trimmed, removed), as
    `clip_editor_vm.follow_media` does for effects: the own video's pieces renamed
    (`mapping`, `cut_mapping`/`removed_mapping`/…); a stuck text whose blocks are no
    longer side by side becomes one text per group (the first keeps its id); one whose
    blocks all left is gone. The texts, and how many left (for the live line)."""
    current = normalize_text_uses(uses)
    if mapping:
        current = cevm.remap_effect_blocks(current, mapping)
    spans = cevm.block_spans(media)
    out: list[dict[str, object]] = []
    taken = [str(u["uid"]) for u in current]
    gone = 0
    for use in current:
        stuck = _blocks(use)
        if not stuck:
            out.append(dict(use))
            continue
        groups = cevm.part_groups(media, stuck)
        if not groups:
            gone += 1
            continue
        for n, group in enumerate(groups):
            uid = str(use["uid"])
            if n:
                uid = new_text_uid(out, taken)
                taken.append(uid)
            start, end = cevm.group_span(spans, group)
            out.append({**use, "uid": uid, "blocks": group, "start": start, "end": end})
    return out, gone


# -- editing one text ----------------------------------------------------------------------


def _edit(
    uses: Sequence[Mapping[str, object]], uid: str, **changes: object
) -> list[dict[str, object]]:
    return [
        normalize_text_use({**u, **changes}) if str(u.get("uid")) == uid else dict(u) for u in uses
    ]


def set_text(uses: Sequence[Mapping[str, object]], uid: str, text: str) -> list[dict[str, object]]:
    """What the text says. Written past «Grande»'s limit while «Grande», it goes back to
    «Mediana» (round 4: never a size that does not fit; `size_went_down` tells the state)."""
    use = next((u for u in uses if str(u.get("uid")) == uid), None)
    if use is not None and normalize_size(use.get("size")) == LARGE and not large_allowed(text):
        return _edit(uses, uid, text=text, size=SIZE_DEFAULT)
    return _edit(uses, uid, text=text)


def size_went_down(
    before: Sequence[Mapping[str, object]], after: Sequence[Mapping[str, object]], uid: str
) -> bool:
    """`uid` was «Grande» in `before` and is not in `after` (`set_text` lowered it)."""
    old = next((u for u in before if str(u.get("uid")) == uid), None)
    new = next((u for u in after if str(u.get("uid")) == uid), None)
    return (
        old is not None
        and new is not None
        and normalize_size(old.get("size")) == LARGE
        and normalize_size(new.get("size")) != LARGE
    )


def set_size(uses: Sequence[Mapping[str, object]], uid: str, size: str) -> list[dict[str, object]]:
    """«Tamaño de las letras»; «Grande» for a text over `LARGE_MAX` characters, or a value
    that is not one of the three, leaves it."""
    use = next((u for u in uses if str(u.get("uid")) == uid), None)
    if use is None or size not in contract.VIDEO_TEXT_SIZES:
        return [dict(u) for u in uses]
    if size == LARGE and not large_allowed(use.get("text")):
        return [dict(u) for u in uses]
    return _edit(uses, uid, size=size)


def set_place(
    uses: Sequence[Mapping[str, object]], uid: str, place: str, *, subtitles: bool = False
) -> list[dict[str, object]]:
    """«Arriba · En el medio · Abajo»; any other value — or «Abajo» while subtitles are
    on — leaves it."""
    if not place_offered(place, subtitles=subtitles):
        return [dict(u) for u in uses]
    return _edit(uses, uid, place=place)


def set_fade(
    uses: Sequence[Mapping[str, object]], uid: str, fade: object
) -> list[dict[str, object]]:
    return _edit(uses, uid, fade=normalize_fade(fade))


def set_layout(
    uses: Sequence[Mapping[str, object]], uid: str, layout: str
) -> list[dict[str, object]]:
    """«Fondo de las letras»; a value that is not one of the four leaves it. Another
    background starts on its own default colour (a colour picked for «Franja» is not
    carried to «Recuadro de tu color»)."""
    if layout not in contract.VIDEO_TEXT_LAYOUTS:
        return [dict(u) for u in uses]
    use = next((u for u in uses if str(u.get("uid")) == uid), None)
    if use is not None and normalize_layout(use.get("layout")) == layout:
        return [dict(u) for u in uses]
    return _edit(uses, uid, layout=layout, box_color="", text_color="")


def set_box_color(
    uses: Sequence[Mapping[str, object]], uid: str, color: str, palette: Sequence[str] = ()
) -> list[dict[str, object]]:
    """A chip of «Color de la franja» / «Color del recuadro»: one of `box_color_chips`
    (anything else, or a background without a box, leaves it). The default's chip stores
    "" — the background's default — so the text keeps its default shape."""
    use = next((u for u in uses if str(u.get("uid")) == uid), None)
    picked = normalize_box_color(color)
    offered = {hex_ for hex_, _name in box_color_chips(palette)}
    if use is None or not picked or picked not in offered:
        return [dict(u) for u in uses]
    layout = normalize_layout(use.get("layout"))
    if layout not in BOX_COLOR_LAYOUTS:
        return [dict(u) for u in uses]
    default = contract.default_box_color(layout, contract.palette_of(palette)).upper()
    return _edit(uses, uid, box_color="" if picked == default else picked)


def set_text_color(
    uses: Sequence[Mapping[str, object]], uid: str, color: str, palette: Sequence[str] = ()
) -> list[dict[str, object]]:
    """Round 3 (Deivid 2026-11-23): a chip of «Color de las letras» under «Sin fondo»: one
    of `box_color_chips` (anything else, or another background, leaves it). White — the
    default — stores "", so the text keeps its default shape."""
    use = next((u for u in uses if str(u.get("uid")) == uid), None)
    picked = normalize_box_color(color)
    offered = {hex_ for hex_, _name in box_color_chips(palette)}
    if use is None or not picked or picked not in offered:
        return [dict(u) for u in uses]
    if normalize_layout(use.get("layout")) not in TEXT_COLOR_LAYOUTS:
        return [dict(u) for u in uses]
    return _edit(uses, uid, text_color="" if picked == WHITE else picked)


def typewriter_allowed(text: object) -> bool:
    """«Letra por letra» takes this text (up to 40 characters)."""
    return contract.typewriter_fits(str(text or ""))


def set_motion_in(
    uses: Sequence[Mapping[str, object]], uid: str, motion: str
) -> list[dict[str, object]]:
    """«Cómo entra». The exit goes with it (`EXIT_WITH`: Sube → Baja…) until the owner
    chose one. «Letra por letra» for a text over 40 characters, or a value that is not
    one, leaves it."""
    use = next((u for u in uses if str(u.get("uid")) == uid), None)
    if use is None or motion not in contract.VIDEO_TEXT_MOTIONS_IN:
        return [dict(u) for u in uses]
    if motion == TYPEWRITER and not typewriter_allowed(use.get("text")):
        return [dict(u) for u in uses]
    changes: dict[str, object] = {"motion_in": motion}
    if not use.get("exit_set"):
        changes["motion_out"] = EXIT_WITH[motion]
    return _edit(uses, uid, **changes)


def set_motion_out(
    uses: Sequence[Mapping[str, object]], uid: str, motion: str
) -> list[dict[str, object]]:
    """«Cómo sale»: chosen by the owner, it no longer goes with the entrance."""
    if motion not in contract.VIDEO_TEXT_MOTIONS_OUT:
        return [dict(u) for u in uses]
    return _edit(uses, uid, motion_out=motion, exit_set=True)


def remove_text(uses: Sequence[Mapping[str, object]], uid: str) -> list[dict[str, object]]:
    return [dict(u) for u in uses if str(u.get("uid")) != uid]


def drop_empty(uses: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """The texts with something written (a text put and left empty is not kept)."""
    return [dict(u) for u in uses if str(u.get("text") or "").strip()]


def _resolved_one(
    uses: Sequence[Mapping[str, object]], media: Sequence[Mapping[str, object]], uid: str
) -> dict[str, object] | None:
    return next((u for u in resolve_text_uses(uses, media) if u["uid"] == uid), None)


def nudge_text(
    uses: Sequence[Mapping[str, object]],
    media: Sequence[Mapping[str, object]],
    uid: str,
    edge: str,
    delta: float,
) -> list[dict[str, object]]:
    """A handle of its block dragged, or ←/→ on it: that edge moves on the
    ½ s grid, inside the video, the text never under 1 s. The text gets its own seconds
    (no longer stuck to its blocks, as an effect). Moving the start of a text that lasts
    to the end keeps it open."""
    use = _resolved_one(uses, media, uid)
    if use is None or edge not in ("start", "end"):
        return [dict(u) for u in uses]
    total = cevm.media_total(media)
    start, end = float(use["start"]), float(use["end"])  # type: ignore[arg-type]
    if edge == "start":
        start = min(max(tl.snap(start + float(delta)), 0.0), max(end - MIN_S, 0.0))
        new_end = OPEN_END if use["open"] else end
    else:
        new_end = min(max(tl.snap(end + float(delta)), start + MIN_S), total)
        if new_end >= total - 0.005 and use["open"]:
            new_end = OPEN_END
    return _edit(uses, uid, start=start, end=new_end, blocks=[])


def shift_text(
    uses: Sequence[Mapping[str, object]],
    media: Sequence[Mapping[str, object]],
    uid: str,
    delta: float,
) -> list[dict[str, object]]:
    """←/→ on a chosen text: the whole text moves ½ s, same length, inside the video."""
    use = _resolved_one(uses, media, uid)
    if use is None:
        return [dict(u) for u in uses]
    total = cevm.media_total(media)
    start, end = float(use["start"]), float(use["end"])  # type: ignore[arg-type]
    length = end - start
    new_start = min(max(tl.snap(start + float(delta)), 0.0), max(total - length, 0.0))
    if abs(new_start - start) < 1e-6:
        return [dict(u) for u in uses]
    return _edit(uses, uid, start=new_start, end=round(new_start + length, 2), blocks=[])


# -- two texts in one place at once ----------------------------------------------------------


def _shown(resolved: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [u for u in resolved if str(u.get("text") or "").strip()]


def _overlap(a: Mapping[str, object], b: Mapping[str, object]) -> bool:
    """Two texts cover the same seconds (meeting at a second is fine)."""
    a0, a1 = float(a["start"]), float(a["end"])  # type: ignore[arg-type]
    b0, b1 = float(b["start"]), float(b["end"])  # type: ignore[arg-type]
    return a0 < b1 - 1e-6 and b0 < a1 - 1e-6


def text_clashes(resolved: Sequence[Mapping[str, object]]) -> list[tuple[str, str, str]]:
    """Every pair of written texts in the same place at the same time: `(uid, uid,
    place)`, in the texts' order."""
    shown = _shown(resolved)
    out: list[tuple[str, str, str]] = []
    for i, a in enumerate(shown):
        for b in shown[i + 1 :]:
            if a["place"] == b["place"] and _overlap(a, b):
                out.append((str(a["uid"]), str(b["uid"]), str(a["place"])))
    return out


def under_subtitles(
    resolved: Sequence[Mapping[str, object]], *, subtitles: bool = False
) -> list[str]:
    """The written texts «Abajo» while subtitles are on (the subtitles would cover them)."""
    if not subtitles:
        return []
    return [str(u["uid"]) for u in _shown(resolved) if u.get("place") == SUBTITLES_PLACE]


def clashing_uids(
    resolved: Sequence[Mapping[str, object]], *, subtitles: bool = False
) -> list[str]:
    """The texts in a clash — with another text, or with the subtitles — (their blocks
    show the warning tone)."""
    out: list[str] = []
    for a, b, _place in text_clashes(resolved):
        for uid in (a, b):
            if uid not in out:
                out.append(uid)
    for uid in under_subtitles(resolved, subtitles=subtitles):
        if uid not in out:
            out.append(uid)
    return out


def typing_too_long(resolved: Sequence[Mapping[str, object]]) -> list[str]:
    """The written texts that enter «Letra por letra» but grew past its 40 characters."""
    return [
        str(u["uid"])
        for u in _shown(resolved)
        if u.get("motion_in") == TYPEWRITER and not typewriter_allowed(u.get("text"))
    ]


def texts_problem(resolved: Sequence[Mapping[str, object]], *, subtitles: bool = False) -> str:
    """What stops «Siguiente» ("" = nothing): more texts than fit, else the first clash
    (criterion 3), else a text «Abajo» under the subtitles, else one «Letra por letra»
    longer than it takes (the backend's `typewriter_text_too_long`)."""
    count = len(_shown(resolved))
    if count > TEXTS_MAX:
        return too_many_texts_line(count)
    clashes = text_clashes(resolved)
    if clashes:
        return clash_line(clashes[0][2])
    if under_subtitles(resolved, subtitles=subtitles):
        return SUBTITLES_BOTTOM_LINE
    return TYPEWRITER_TOO_LONG_LINE if typing_too_long(resolved) else ""


def next_blocked(resolved: Sequence[Mapping[str, object]], *, subtitles: bool = False) -> bool:
    """«Siguiente» waits until the texts can be made (criterion 3)."""
    return bool(texts_problem(resolved, subtitles=subtitles))


# -- the recipe, the timeline and the preview ------------------------------------------------


def _floor2(value: float) -> float:
    return math.floor(float(value) * 100 + 1e-6) / 100


def ordered(resolved: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Written texts in time order (then top to bottom, then as they were put)."""
    rank = {place: n for n, place in enumerate(PLACES)}
    indexed = list(enumerate(_shown(resolved)))
    indexed.sort(
        key=lambda pair: (
            float(pair[1]["start"]),  # type: ignore[arg-type]
            rank.get(str(pair[1]["place"]), 0),
            pair[0],
        )
    )
    return [use for _n, use in indexed]


def text_layers_for_recipe(
    resolved: Sequence[Mapping[str, object]], *, total: float | None = None
) -> tuple[contract.VideoTextLayer, ...]:
    """`PartRecipe.text_layers` (criterion 1): every written text, in time order, in
    `clip_editor_vm.recipe_of`'s shape — trimmed text, seconds to the hundredth, a start
    that leaves 1 s inside the video, an end at the video's end (or open) left None, its
    background (`layout_id`, «Sombra» = `scrim`) and the owner's fade and motions. Never
    cut at 3: past it «Siguiente» is off and the backend would refuse (`too_many_texts`)."""
    top = _floor2(total) if total is not None else None
    layers: list[contract.VideoTextLayer] = []
    for use in ordered(resolved):
        layout = normalize_layout(use.get("layout"))
        # the picked colour travels only where it counts, and only when there is one
        box_color = normalize_box_color(use.get("box_color")) if layout in BOX_COLOR_LAYOUTS else ""
        text_color = (
            normalize_box_color(use.get("text_color")) if layout in TEXT_COLOR_LAYOUTS else ""
        )
        begin = round(max(float(use["start"]), 0.0), 2)  # type: ignore[arg-type]
        finish: float | None = None if use.get("open") else round(float(use["end"]), 2)  # type: ignore[arg-type]
        if finish is not None and finish < 0:
            finish = None
        if top is not None:
            begin = min(begin, max(top - MIN_S, 0.0))
            if finish is not None and finish >= top - 0.01:
                finish = None
        layers.append(
            contract.VideoTextLayer(
                text=str(use["text"]).strip(),
                place=str(use["place"]),
                start_s=begin,
                end_s=finish,
                layout_id=layout,
                layout_version=contract.TEXT_LAYOUT_VERSION,
                fade_s=normalize_fade(use.get("fade")),
                motion_in=normalize_motion_in(use.get("motion_in")),
                motion_out=normalize_motion_out(use.get("motion_out")),
                box_color=box_color or None,
                text_color=text_color or None,
                text_size=normalize_size(use.get("size")),
            )
        )
    return tuple(layers)


def with_texts(
    recipe: contract.PartRecipe, layers: Sequence[contract.VideoTextLayer]
) -> contract.PartRecipe:
    """`recipe` with `layers` as its texts (a new recipe: `dataclasses.replace` would put
    the old first text back, see `PartRecipe`)."""
    return contract.PartRecipe(
        effects=recipe.effects, segments=recipe.segments, text_layers=tuple(layers)
    )


def timeline_text_overlays(
    resolved: Sequence[Mapping[str, object]], *, subtitles: bool = False
) -> list[dict[str, object]]:
    """The «Texto en pantalla» blocks (`ui.timeline_vm`'s raw overlays, kind "text"),
    written texts only, in time order: the preview's `edit_sequence.from_timeline` shows
    each one only in its seconds (criterion 4). ``warn``: it is in a clash (two texts in
    one place at once, criterion 3; or «Abajo» under the subtitles) — its block shows the
    warning tone."""
    clashing = set(clashing_uids(resolved, subtitles=subtitles))
    return [
        {
            "id": text_block_id(str(use["uid"])),
            "kind": "text",
            "uid": str(use["uid"]),
            "label": str(use["text"]).strip(),
            "start": float(use["start"]),  # type: ignore[arg-type]
            "end": float(use["end"]),  # type: ignore[arg-type]
            "place": str(use["place"]),
            "fade": normalize_fade(use.get("fade")),
            # ED-13: what the preview draws it over and how it moves
            "layout": normalize_layout(use.get("layout")),
            "motion_in": normalize_motion_in(use.get("motion_in")),
            "motion_out": normalize_motion_out(use.get("motion_out")),
            "box_color": normalize_box_color(use.get("box_color")),
            "text_color": normalize_box_color(use.get("text_color")),
            "size": normalize_size(use.get("size")),
            "warn": str(use["uid"]) in clashing,
        }
        for use in ordered(resolved)
    ]


def texts_on_at(resolved: Sequence[Mapping[str, object]], t: float) -> list[str]:
    """The texts the preview shows at second `t` (`start <= t < end`, as
    `edit_sequence.PreviewOverlay`)."""
    return [
        str(u["uid"])
        for u in ordered(resolved)
        if float(u["start"]) - 1e-6 <= float(t) < float(u["end"]) - 1e-6  # type: ignore[arg-type]
    ]


def text_name(text: str, start: float, end: float) -> str:
    """Criterion 5: the block's accessible name, «Texto «2×1 hoy», de 0:00 a 0:03» — the
    same words as `ui.timeline_vm.overlay_blocks`."""
    return f"Texto «{str(text).strip()}», de {tl.clock(start)} a {tl.clock(end)}"


def motion_cut(use: Mapping[str, object]) -> bool:
    """The entrance or the exit is shorter than chosen: a third of the text's time at
    most (`contract.VIDEO_TEXT_MOTION_MAX_SHARE`), so it can be read."""
    visible = max(float(use["end"]) - float(use["start"]), 0.0)  # type: ignore[arg-type]
    fade = normalize_fade(use.get("fade"))
    motion_in = normalize_motion_in(use.get("motion_in"))
    if motion_in == TYPEWRITER:
        text = str(use.get("text") or "").strip()
        wanted = len(text) * contract.VIDEO_TEXT_TYPEWRITER_S_PER_CHAR
        cut_in = contract.typewriter_seconds(text, visible) < wanted - 1e-6
    else:
        cut_in = contract.motion_is_cut(fade, visible)
    cut_out = normalize_motion_out(use.get("motion_out")) != "none" and contract.motion_is_cut(
        fade, visible
    )
    return cut_in or cut_out


def box_color_chosen_line(use: Mapping[str, object], palette: Sequence[str] = ()) -> str:
    """«Elegido: color principal de tu marca» / «Elegido: negro» under the chips ("" for a
    background without a box)."""
    name = box_color_name(use, palette)
    return f"Elegido: {name[:1].lower()}{name[1:]}" if name else ""


def layout_choice(use: Mapping[str, object], palette: Sequence[str] = ()) -> str:
    """«Franja, color principal» — what «Fondo de las letras» has chosen (the folded
    section's summary, under its title), with the box's colour when it has one — or, for
    «Sin fondo», its letters' («Sin fondo, letras negras», round 3)."""
    layout = normalize_layout(use.get("layout"))
    name = box_color_name(use, palette)
    if layout in TEXT_COLOR_LAYOUTS and name:
        return f"{LAYOUT_NAMES[layout]}, {letters_words(name)}"
    named = name and name != BOX_COLOR_DEFAULT_NAME
    color = f", {_short_name(name)}" if named else ""
    return f"{LAYOUT_NAMES[layout]}{color}"


#: «Negro» → «letras negras» (the summary of «Sin fondo»'s letters, round 3).
_LETTERS_WORDS: dict[str, str] = {"Negro": "letras negras", "Blanco": "letras blancas"}


def letters_words(name: str) -> str:
    """A chip's name as the letters' colour: «letras negras», «letras blancas», «letras en
    tu color principal»."""
    return _LETTERS_WORDS.get(name) or f"letras en tu {_short_name(name)}"


def layout_summary(use: Mapping[str, object], palette: Sequence[str] = ()) -> str:
    """«Fondo de las letras: Franja, color principal» — the title and the choice."""
    return f"{LAYOUT_TITLE}: {layout_choice(use, palette)}"


def place_choice(place: str, *, covered: bool = False) -> str:
    """«Arriba» — what «Dónde va el texto» has chosen (its folded summary); a text left
    «Abajo» under the subtitles says so there too, so it is seen with the section shut."""
    name = PLACE_TEXTS[normalize_place(place)]
    return f"{name}, {PLACE_COVERED_WORDS}" if covered else name


def motion_choice(motion_in: str, motion_out: str) -> str:
    """«Aparece · Desaparece» — how the text enters and leaves (the folded summary of
    «Cómo entra y sale»)."""
    in_name = MOTION_IN_NAMES[normalize_motion_in(motion_in)]
    out_name = MOTION_OUT_NAMES[normalize_motion_out(motion_out)]
    return f"{in_name} · {out_name}"


def text_panel_row(
    use: Mapping[str, object],
    media: Sequence[Mapping[str, object]],
    *,
    subtitles: bool = False,
    palette: Sequence[str] = (),
) -> dict[str, str]:
    """The chosen text's panel as strings (a resolved use): its title, the field, the
    place (``place_choice``: its folded summary), when it shows (``time_line``, A1: no
    «Empieza»/«Termina»), its background (``layout``, ``layout_summary``, and
    ``layout_choice`` the folded summary), how it enters and leaves (``motion_in`` /
    ``motion_out``, ``motion_summary``, ``motion_choice``) and how long that takes
    (``fade_*``: the row's words follow what it changes, ``fade_shown`` "" when it changes
    nothing). With subtitles on, «Abajo» is off (``bottom_off`` "1") and ``place_note``
    says why, under the control; a text still «Abajo» says it is under them (``covered_note``).
    «Letra por letra» is off past 40 characters (``typewriter_off``, its reason
    ``typewriter_note``); chosen, ``typewriter_slow`` warns the video takes longer;
    ``cut_note`` says the animation was shortened. «Franja» / «Recuadro de tu color» show
    their colour chips (``box_color_shown`` "1", their title ``box_color_title``, and
    ``box_color_chosen`` «Elegido: …» under them; the chips are `box_color_rows`, from the
    Brand Kit's `palette`); «Sin fondo» shows the same chips for its letters
    (``chips_for_text`` "1", round 3) and says they may get lost on a light video
    (``shadow_note``). Round 4: the letters' size (``size``, ``size_choice`` its folded
    summary), «Grande» off past `LARGE_MAX` characters (``large_off``, ``large_note``)."""
    start, end = float(use["start"]), float(use["end"])  # type: ignore[arg-type]
    text = str(use.get("text") or "")
    fade = normalize_fade(use.get("fade"))
    bottom_free = place_offered(SUBTITLES_PLACE, subtitles=subtitles)
    covered = not bottom_free and str(use.get("place")) == SUBTITLES_PLACE
    layout = normalize_layout(use.get("layout"))
    motion_in = normalize_motion_in(use.get("motion_in"))
    motion_out = normalize_motion_out(use.get("motion_out"))
    fade_label, less_name, more_name = fade_words(motion_in, motion_out)
    typing_ok = typewriter_allowed(text)
    in_name, out_name = MOTION_IN_NAMES[motion_in], MOTION_OUT_NAMES[motion_out]
    size = normalize_size(use.get("size"))
    large_ok = large_allowed(text)
    return {
        "id": text_block_id(str(use["uid"])),
        "uid": str(use["uid"]),
        "kind": "text",
        "text": text,
        "place": str(use["place"]),
        "place_choice": place_choice(str(use["place"]), covered=covered),
        "panel": f"{TITLE} · de {tl.clock(start)} a {tl.clock(end)}",
        "name": text_name(text, start, end) if text.strip() else TITLE,
        "time_line": time_line(start, end),
        "fade": fade_value(fade),
        "fade_text": fade_text(fade),
        "fade_value": fade_line(fade, fade_label) if fade_label else "",
        "fade_label": fade_label,
        "fade_less_name": less_name,
        "fade_more_name": more_name,
        "fade_shown": "1" if fade_label else "",
        # the buttons go off at the limits ("1" = off)
        "fade_less_off": "" if fade_can_step(fade, -FADE_STEP) else "1",
        "fade_more_off": "" if fade_can_step(fade, FADE_STEP) else "1",
        "bottom_off": "" if bottom_free else "1",
        "place_note": "" if bottom_free else SUBTITLES_BOTTOM_LINE,
        "covered_note": SUBTITLES_COVERED_LINE if covered else "",
        "layout": layout,
        "layout_summary": layout_summary(use, palette),
        "layout_choice": layout_choice(use, palette),
        # round 3: «Sin fondo» shows the chips too, for its letters ("1" = they pick the
        # letters' colour, `set_text_color`, instead of the box's)
        "box_color_shown": "1" if layout in CHIP_LAYOUTS else "",
        "chips_for_text": "1" if layout in TEXT_COLOR_LAYOUTS else "",
        "box_color_title": BOX_COLOR_TITLES.get(layout, ""),
        "box_color_chosen": box_color_chosen_line(use, palette),
        "shadow_note": SHADOW_NOTE if layout == "shadow" else "",
        "motion_in": motion_in,
        "motion_out": motion_out,
        "motion_summary": f"{MOTION_TITLE}: {in_name} · {out_name}",
        "motion_choice": motion_choice(motion_in, motion_out),
        "typewriter_off": "" if typing_ok else "1",
        "typewriter_note": "" if typing_ok else typewriter_note(len(text.strip())),
        "typewriter_slow": TYPEWRITER_SLOW if motion_in == TYPEWRITER else "",
        "cut_note": cut_note(end - start) if motion_cut(use) else "",
        # round 4: the letters' size; «Grande» off past `LARGE_MAX` characters, its reason
        # under the choices
        "size": size,
        "size_choice": size_choice(size),
        "large_off": "" if large_ok else "1",
        "large_note": "" if large_ok else LARGE_NOTE,
    }


# -- ED-13 B/C/D: the preview's look and motion --------------------------------------------

#: The `@font-face` family the brand's uploaded font file is registered under.
BRAND_FONT_FAMILY = "QualifyBrandHeading"
#: The CSS variable the preview's frame reads its texts' family from.
FONT_VAR = "--q-text-font"
#: How far before the moment a chosen motion is shown from (and after it, until).
DEMO_LEAD_S = 0.3


def _clean_family(name: str) -> str:
    """A family name minus what would break a CSS string (as `creative_state`'s)."""
    return " ".join(re.sub(r'["\\{};<>]', "", str(name or "")).split())


def brand_font_family(name: str, *, has_file: bool = False) -> str:
    """The texts' `font-family` in the preview: the uploaded file's face first (with the
    family name after it), else the family name (Google Fonts), "" for none (the page's
    title typography stays)."""
    clean = _clean_family(name)
    named = f'"{clean}", ' if clean else ""
    if has_file:
        return f'"{BRAND_FONT_FAMILY}", {named}sans-serif'
    return f"{named}sans-serif" if clean else ""


def preview_text_row(
    index: int,
    *,
    text: str,
    place: str,
    layout: str,
    palette: Sequence[str] = (),
    box_color: str = "",
    text_color: str = "",
    size: str = "",
) -> dict[str, str]:
    """A text of the preview in sequence as strings: what it says, where, its background
    (`layout`), whether it is long (the smaller title size), and the box's colours
    (`contract.text_box_colors`: «Franja» dark and neutral with white letters,
    «Recuadro de tu color» on the brand's accent with legible letters — or, on either,
    the colour the owner picked (`box_color`) with `contract.box_ink`'s letters).
    «Sin fondo»: its letters in the colour picked (`text_color`, round 3), else white."""
    kind = normalize_layout(layout)
    background, ink = contract.text_box_colors(
        kind, contract.palette_of(palette), normalize_box_color(box_color) or None
    )
    if kind in TEXT_COLOR_LAYOUTS:
        ink = normalize_box_color(text_color) or ink
    return {
        "text": text,
        "place": place,
        "index": str(int(index)),
        "layout": kind,
        "long": "true" if contract.text_is_long(text) else "false",
        "bg": background or "transparent",
        "ink": ink,
        # round 4: the letters' size («Mediana» = the sizes the preview had)
        "size": normalize_size(size),
    }


def motion_demo(
    use: Mapping[str, object], which: str, total: float | None = None
) -> tuple[float, float]:
    """The stretch of the video that shows a chosen motion once (`which` «in» or «out»):
    from `DEMO_LEAD_S` before it starts to as long after it ends, inside the video."""
    start, end = float(use["start"]), float(use["end"])  # type: ignore[arg-type]
    visible = max(end - start, 0.0)
    fade = normalize_fade(use.get("fade"))
    if which == "out":
        none = normalize_motion_out(use.get("motion_out")) == "none"
        length = 0.0 if none else contract.motion_seconds(fade, visible)
        begin, finish = end - length - DEMO_LEAD_S, end + DEMO_LEAD_S
    else:
        if normalize_motion_in(use.get("motion_in")) == TYPEWRITER:
            length = contract.typewriter_seconds(str(use.get("text") or ""), visible)
        else:
            length = contract.motion_seconds(fade, visible)
        begin, finish = start - DEMO_LEAD_S, start + length + DEMO_LEAD_S
    top = float(total) if total is not None else finish
    return round(max(begin, 0.0), 2), round(max(min(finish, top), 0.0), 2)


def show_motion_script(begin: float, end: float, *, force: bool = False) -> str:
    """Plays the preview from `begin` to `end` once and pauses (`edit-preview.js`
    `seq.showMotion`); with prefers-reduced-motion it plays only when ``force`` («Ver
    cómo se mueve»)."""
    return (
        "(function () { var s = window.__qEditPreview && window.__qEditPreview.seq;"
        " var h = document.querySelector('[data-edit-seq-host]');"
        f" if (s && h && s.showMotion) s.showMotion(h, {float(begin):g}, {float(end):g},"
        f" {'true' if force else 'false'}); }})()"
    )
