"""Pure view model of «Publicar ahora» (`/publish`) — rules and words, no Reflex.

Spec: `docs/mockups/publicar-varias-imagenes.md` (ux-designer, 2026-11-12; founder
decisions of the same day). The assistant asks one question per step (N6) and the steps
that do not apply are not counted:

1. ¿Qué vas a publicar? — the files (always).
2. ¿Cómo sale? / ¿Cómo salen? — the mode (always).
3. The order — only with 2 or more files; its title depends on the mode.
4. ¿En qué Instagram sale? — only with 2 or more Instagram accounts that can publish.
5. Revisa y publica — the description(s) and «Publicar» (always).

Modes. With one file: `post` (a publication on the profile) or `story` (a 24-hour
historia). With two or more: `carousel` (one publication that slides), `one_by_one`
(each file its own publication — a mural; published from the LAST to the FIRST so the
profile reads in the arranged order) or `stories` (one historia per file, in order).

Everything here is plain Python so the rules — limits, which step comes next, the order
the jobs run in, every sentence the owner reads — are unit-tested on their own
(`test_publish_wizard_vm.py`).
"""

from __future__ import annotations

from collections.abc import Sequence

# -- modes ---------------------------------------------------------------------------

MODE_POST = "post"
MODE_STORY = "story"
MODE_CAROUSEL = "carousel"
MODE_ONE_BY_ONE = "one_by_one"
MODE_STORIES = "stories"

SINGLE_MODES = (MODE_POST, MODE_STORY)
MANY_MODES = (MODE_CAROUSEL, MODE_ONE_BY_ONE, MODE_STORIES)
STORY_MODES = (MODE_STORY, MODE_STORIES)

#: `?flow=stories` (and `/stories`, which redirects there) arrives with historia chosen.
FLOW_POSTS = "posts"
FLOW_STORIES = "stories"

# -- limits (spec §2) ----------------------------------------------------------------

CAROUSEL_MAX = 10  # Instagram's own cap for a carousel
ONE_BY_ONE_MAX = 9  # three full profile rows, published in series with the screen open
STORIES_MAX = 10
#: The gallery takes as many as the widest mode allows.
GALLERY_MAX = max(CAROUSEL_MAX, STORIES_MAX)

_MODE_MAX = {
    MODE_POST: 1,
    MODE_STORY: 1,
    MODE_CAROUSEL: CAROUSEL_MAX,
    MODE_ONE_BY_ONE: ONE_BY_ONE_MAX,
    MODE_STORIES: STORIES_MAX,
}

# -- steps ---------------------------------------------------------------------------

STEP_WHAT = "what"
STEP_HOW = "how"
STEP_ORDER = "order"
STEP_ACCOUNT = "account"
STEP_REVIEW = "review"
ALL_STEPS = (STEP_WHAT, STEP_HOW, STEP_ORDER, STEP_ACCOUNT, STEP_REVIEW)

# The assistant card's DOM id. Changing step scrolls back to its top, so after a long
# step 1 (6-10 files) the owner lands on «Paso N de M» and the new title, not on the
# buttons at the bottom (PUBLICAR-4 UX review).
ASSISTANT_ID = "publish-assistant"
SCROLL_TO_ASSISTANT = (
    f"document.getElementById('{ASSISTANT_ID}')?.scrollIntoView({{block: 'start'}})"
)

# -- fixed copy (spec §3) --------------------------------------------------------------

REJECTED_FILE_TITLE = "Ese archivo no se puede usar"
REJECTED_FILE_HELP = (
    "Elige fotos JPG o videos MP4 o MOV: hasta 300 MB por video, 8 MB por foto y 10 a la vez."
)
PICK_NEXT_HINT = "En el paso siguiente eliges si salen juntas o una por una."
NEED_FILE = "Elige al menos una foto o un video."
NEED_ACCOUNT = "Elige la cuenta donde vas a publicar."
FACEBOOK_NOTE = "Todavía no publicamos en Facebook desde aquí."
ORDER_HELP = "Mantén presionada una foto y muévela, o toca ⋯."
MURAL_HELP = (
    "Ordénalas como quieres verlas en tu perfil. Nosotros las publicamos en el orden "
    "correcto para que el mural quede armado."
)
MURAL_SHIFT_NOTE = (
    "Si después publicas una sola cosa, tu mural se corre un lugar. Si publicas de a 3, "
    "se mantiene."
)
STORIES_ORDER_HELP = "Se publican en este orden: la primera es la que se ve primero."
BEFORE_TILE = "Antes"
COVER_BADGE = "Portada"
CAPTION_LABEL = "Descripción (opcional)"
CAPTION_EXAMPLE = "Ej.: Hoy combo vecino a mitad de precio hasta las 9 p. m."
CAPTION_HELP = "Sale tal como la escribas."
COPY_CAPTION = "Usar este texto en las demás"
STORIES_NO_TEXT = "Las historias salen sin texto."
ONE_STORY_OPEN_HINT = "Si quieres escribirle algo, ábrela en Instagram."
PROGRESS_DETAIL = "Deja esta pantalla abierta hasta que terminen. Puede tardar unos minutos."
UNDO = "Deshacer"
LEAVE_TITLE = "¿Salir mientras se publican?"
LEAVE_STAY = "Seguir aquí"
LEAVE_GO = "Salir igual"
KEEP_AS_IS = "Dejar así"
KEEP_AS_IS_TITLE = "¿Dejar el mural sin terminar?"
BACK = "Volver"
DISCARD = "Descartar"
CONTINUE = "Continuar"
RECONNECT = "Conectar mi Instagram"
#: «Continuar» with the run's own account gone (the run never switches accounts).
PINNED_ACCOUNT_GONE = (
    "La cuenta de Instagram de esta publicación ya no está conectada. Conéctala de nuevo "
    "en Tus redes para seguir."
)
#: Under the gallery once it holds the most files one publication takes.
GALLERY_FULL = f"Llegaste a {GALLERY_MAX}, el máximo por vez."

STATUS_PUBLISHED = "published"
STATUS_RUNNING = "running"
STATUS_WAITING = "waiting"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"

#: `signal_pill` per piece — always with its word, never colour alone (spec §4.2).
STATUS_PILL: dict[str, tuple[str, str]] = {
    STATUS_PUBLISHED: ("Publicada", "ok"),
    STATUS_RUNNING: ("Publicando…", "warn"),
    STATUS_WAITING: ("En espera", "neutral"),
    STATUS_FAILED: ("No salió", "error"),
    STATUS_UNKNOWN: ("No salió", "error"),
}

_PLATFORM_NAMES = {"instagram": "Instagram", "facebook": "Facebook"}

# -- modes and limits -----------------------------------------------------------------


def mode_limit(mode: str) -> int:
    """How many files `mode` takes at most."""
    return _MODE_MAX.get(mode, 1)


def mode_allowed(mode: str, file_count: int) -> bool:
    """Whether `mode` fits a selection of `file_count` files."""
    if file_count <= 0:
        return False
    if file_count == 1:
        return mode in SINGLE_MODES
    return mode in MANY_MODES and file_count <= mode_limit(mode)


def one_by_one_blocked_text(file_count: int) -> str:
    """Why «Una por una» is switched off with more than nine (spec §2), or ``""``."""
    extra = file_count - ONE_BY_ONE_MAX
    if extra <= 0:
        return ""
    return f"Una por una llega hasta {ONE_BY_ONE_MAX}. Quita {extra} en el paso anterior."


def effective_mode(kind_single: str, kind_many: str, file_count: int) -> str:
    """The mode that applies to `file_count` files, from the two remembered choices
    (one for a single file, one for several — spec §3, «la última opción que el dueño
    usó con esa cantidad de archivos»)."""
    if file_count <= 1:
        return kind_single if kind_single in SINGLE_MODES else MODE_POST
    if kind_many in MANY_MODES and mode_allowed(kind_many, file_count):
        return kind_many
    return MODE_CAROUSEL


def single_for(mode: str) -> str:
    """Back to one file: a carousel or a mural becomes a publication, historias a
    historia (spec §5, «Quitar»)."""
    return MODE_STORY if mode in STORY_MODES else MODE_POST


def many_for(mode: str) -> str:
    """From one file to several, when the owner has not chosen for several yet: a
    historia becomes historias, a publication the first card (the carousel)."""
    return MODE_STORIES if mode in STORY_MODES else MODE_CAROUSEL


def is_series(mode: str) -> bool:
    """Whether `mode` publishes several pieces one after another."""
    return mode in (MODE_ONE_BY_ONE, MODE_STORIES)


def is_story_mode(mode: str) -> bool:
    return mode in STORY_MODES


# -- steps ----------------------------------------------------------------------------


def step_ids(file_count: int, selectable_accounts: int) -> list[str]:
    """The steps this owner walks, in order — M is always the real number (N6)."""
    steps = [STEP_WHAT, STEP_HOW]
    if file_count >= 2:
        steps.append(STEP_ORDER)
    if selectable_accounts >= 2:
        steps.append(STEP_ACCOUNT)
    steps.append(STEP_REVIEW)
    return steps


def step_number(step: str, steps: Sequence[str]) -> int:
    """1-based position of `step`; a step that no longer applies counts as the last one
    before it that does (so removing a file on «el orden» never shows «Paso 0»)."""
    if step in steps:
        return list(steps).index(step) + 1
    order = list(ALL_STEPS)
    if step in order:
        earlier = [s for s in steps if order.index(s) <= order.index(step)]
        if earlier:
            return list(steps).index(earlier[-1]) + 1
    return 1


def resolve_step(step: str, steps: Sequence[str]) -> str:
    """`step` when it applies; otherwise the step `step_number` points at."""
    return step if step in steps else list(steps)[step_number(step, steps) - 1]


def step_counter(step: str, steps: Sequence[str]) -> str:
    """«Paso N de M»."""
    return f"Paso {step_number(step, steps)} de {len(steps)}"


def step_title(step: str, *, file_count: int, mode: str) -> str:
    """The step's `h1`, in the owner's words (spec §1)."""
    if step == STEP_WHAT:
        return "¿Qué vas a publicar?"
    if step == STEP_HOW:
        return "¿Cómo salen?" if file_count >= 2 else "¿Cómo sale?"
    if step == STEP_ORDER:
        if mode == MODE_ONE_BY_ONE:
            return "Así se verá tu perfil"
        if mode == MODE_STORIES:
            return "¿En qué orden se ven?"
        return "Elige el orden del carrusel"
    if step == STEP_ACCOUNT:
        return "¿En qué Instagram sale?"
    return "Revisa y publica"


def can_advance(step: str, *, file_count: int, mode: str, connection_id: str) -> bool:
    """Whether «Siguiente» may leave `step`. The review publishes instead of advancing."""
    if step == STEP_WHAT:
        return file_count > 0
    if step == STEP_HOW:
        return mode_allowed(mode, file_count)
    if step == STEP_ORDER:
        return file_count >= 2
    if step == STEP_ACCOUNT:
        return bool(connection_id)
    return False


def step_reason(step: str, *, file_count: int, mode: str, connection_id: str) -> str:
    """Why «Siguiente» is off on `step`, read next to the button (§5.8), or ``""``."""
    if file_count <= 0:
        return NEED_FILE
    if step == STEP_HOW and not mode_allowed(mode, file_count):
        return one_by_one_blocked_text(file_count) if mode == MODE_ONE_BY_ONE else ""
    if step == STEP_ACCOUNT and not connection_id:
        return NEED_ACCOUNT
    return ""


def next_step(step: str, steps: Sequence[str], *, can_go: bool) -> str:
    """The step «Siguiente» lands on — the same one when it is not complete."""
    if not can_go or step not in steps:
        return step
    index = list(steps).index(step)
    return list(steps)[min(index + 1, len(steps) - 1)]


def previous_step(step: str, steps: Sequence[str]) -> str:
    """The step «Atrás» lands on; never before the first."""
    number = step_number(step, steps)
    return list(steps)[max(number - 2, 0)]


# -- order (the one list «⋯» and the drag both move) ----------------------------------


def moved[T](items: Sequence[T], index: int, to: int) -> list[T]:
    """`items` with the one at `index` moved to `to` (remove, then insert) — the same
    move `assets/rank-drag.js` animates. Out-of-range values are clamped."""
    out = list(items)
    if not out or not 0 <= index < len(out):
        return out
    to = max(0, min(len(out) - 1, to))
    out.insert(to, out.pop(index))
    return out


def execution_order(mode: str, count: int) -> list[int]:
    """The list positions in the order they go out. A mural goes from the last to the
    first — Instagram shows the newest first, so the profile then reads in the arranged
    order (founder, 2026-11-12); historias and a carousel go in the listed order."""
    positions = list(range(count))
    return positions[::-1] if mode == MODE_ONE_BY_ONE else positions


def moved_text(label: str, position: int, total: int) -> str:
    """`aria-live` after each move (spec §3)."""
    return f"{label}, ahora en la posición {position} de {total}."


def piece_label(kind: str, number: int) -> str:
    """«Foto 3» / «Video 3» — `number` is the file's own number in the list."""
    return f"{'Video' if kind == 'video' else 'Foto'} {number}"


def removed_text(kind: str, number: int) -> str:
    """The toast after «Quitar» (it comes with «Deshacer»)."""
    return f"Quitamos {'el video' if kind == 'video' else 'la foto'} {number}."


def copied_caption_text(filled: int) -> str:
    """The toast after «Usar este texto en las demás»."""
    noun = "descripción vacía" if filled == 1 else "descripciones vacías"
    return f"Listo, lo pusimos en {filled} {noun}."


def caption_label(position: int) -> str:
    """The visible label of one piece's description in «Una por una» — by its place in
    the mural (the number its tile shows), never by the order it was picked in."""
    return f"Descripción de la publicación {position} (opcional)"


def publication_title(position: int, total: int) -> str:
    """«Publicación 2 de 4» — a description card in «Una por una»."""
    return f"Publicación {position} de {total}"


def rows_hint(count: int) -> str:
    """The multiples-of-three suggestion, only on the mural's order step (spec §2)."""
    rest = count % 3
    if count < 2 or rest == 0:
        return ""
    old = "una publicación que ya tenías" if rest == 2 else "dos publicaciones que ya tenías"
    return f"Con 3, 6 o 9 tus filas quedan completas. Con {count}, la última fila lleva {old}."


def before_tiles(count: int) -> int:
    """How many «Antes» tiles fill the mural's last row."""
    return (3 - count % 3) % 3


def shape_word(width: int, height: int) -> str:
    """«cuadrada» | «vertical» | «horizontal» — how Instagram sees a picture's form."""
    if width <= 0 or height <= 0:
        return ""
    ratio = width / height
    if 0.95 <= ratio <= 1.05:
        return "cuadrada"
    return "vertical" if ratio < 1 else "horizontal"


def crop_warning(shapes: Sequence[str]) -> str:
    """The carousel's crop notice (spec §3a): only when the known forms differ, and only
    when the first one is known."""
    known = [s for s in shapes if s]
    if len(shapes) < 2 or not shapes[0] or len(set(known)) < 2:
        return ""
    return (
        f"Instagram corta todas a la forma de la primera ({shapes[0]}). Si alguna se ve "
        "cortada, pon primero la que tiene la forma que quieres."
    )


# -- names ------------------------------------------------------------------------------


def platform_name(platform: str) -> str:
    """The network's name as the owner writes it («instagram» → «Instagram»)."""
    key = (platform or "").strip().lower()
    return _PLATFORM_NAMES.get(key, key.capitalize() if key else "Instagram")


def account_handle(username: str) -> str:
    """«@cuenta», whether or not the stored username already carries the @."""
    name = (username or "").strip().lstrip("@")
    return f"@{name}" if name else ""


def connection_label(username: str, platform: str) -> str:
    """How an account is named in the picker — «@bianki · Instagram»."""
    handle = account_handle(username)
    where = platform_name(platform)
    return f"{handle} · {where}" if handle else where


def media_noun(kinds: Sequence[str]) -> str:
    """«fotos» | «videos» | «fotos y videos» for what is selected."""
    has_video = "video" in kinds
    has_image = any(k != "video" for k in kinds)
    if has_video and has_image:
        return "fotos y videos"
    return "videos" if has_video else "fotos"


# -- review, button, progress, outcome ----------------------------------------------------


def review_sentence(mode: str, *, username: str, kinds: Sequence[str]) -> str:
    """The review in words (spec §3, paso 5)."""
    handle = account_handle(username)
    target = f"Instagram {handle}" if handle else "Instagram"
    n = len(kinds)
    if mode == MODE_STORY:
        return f"Sale ahora en {target} como historia (se ve 24 horas)."
    if mode == MODE_CAROUSEL:
        noun = media_noun(kinds)
        return f"Sale ahora en {target}: una publicación con {n} {noun} que se deslizan."
    if mode == MODE_ONE_BY_ONE:
        return (
            f"Salen ahora en {target}: {n} publicaciones, una tras otra, en el orden de tu "
            "mural. Tarda unos minutos."
        )
    if mode == MODE_STORIES:
        return f"Salen ahora en {target}: {n} historias, en este orden (se ven 24 horas)."
    return f"Sale ahora en {target} como publicación."


def publish_label(mode: str, count: int) -> str:
    """The review's primary button (N13)."""
    if mode == MODE_STORY:
        return "Publicar historia"
    if mode == MODE_ONE_BY_ONE:
        return f"Publicar las {count}"
    if mode == MODE_STORIES:
        return f"Publicar las {count} historias"
    return "Publicar en Instagram"


def progress_title(done: int, total: int) -> str:
    """«Publicando {i} de {n}…» — `i` is the one going out now, counted from 1."""
    return f"Publicando {min(done + 1, total)} de {total}…"


def progress_percent(done: int, total: int) -> int:
    return 0 if total <= 0 else round(done * 100 / total)


def done_message(mode: str, count: int) -> str:
    """The persistent «listo» (N3, spec §4.4)."""
    if mode == MODE_STORY:
        return "Listo, tu historia ya está en Instagram (se ve 24 horas)."
    if mode == MODE_CAROUSEL:
        return "Listo, tu carrusel ya está en Instagram."
    if mode == MODE_ONE_BY_ONE:
        return f"Listo, tus {count} publicaciones ya están en Instagram. Tu mural quedó armado."
    if mode == MODE_STORIES:
        return f"Listo, tus {count} historias ya están en Instagram (se ven 24 horas)."
    return "Listo, ya está en tu Instagram."


def week_hint(mode: str, count: int, *, partial: bool = False) -> str:
    """Where the owner finds what went out (m-25019217): every publication from here is
    recorded in «Tu semana» as published, and can be scheduled again from there."""
    if partial:
        return (
            "Las que salieron ya están en Tu semana, marcadas como publicadas, y en "
            "Aprobados para volver a usarlas."
        )
    if mode in (MODE_ONE_BY_ONE, MODE_STORIES) and count > 1:
        return (
            "Las verás en Tu semana, marcadas como publicadas, y en Aprobados para volver "
            "a usarlas."
        )
    return "La verás en Tu semana, marcada como publicada, y en Aprobados para volver a usarla."


def partial_message(published: int, total: int) -> str:
    """The partial end, in the `warn` tone (spec §4.4)."""
    return f"Salieron {published} de {total}. Las otras {total - published} no se publicaron."


def _the_piece(kind: str, number: int) -> str:
    return f"{'El video' if kind == 'video' else 'La foto'} {number}"


def _from_piece(mode: str, kind: str, number: int) -> str:
    if mode == MODE_STORIES:
        return f"la historia {number}"
    return f"{'el video' if kind == 'video' else 'la foto'} {number}"


def failed_headline(published: int, total: int, kind: str, number: int) -> str:
    """«Salieron {s} de {n}. La foto {k} no salió.» (spec §4.3)."""
    return f"Salieron {published} de {total}. {_the_piece(kind, number)} no salió."


def failed_followup(mode: str, kind: str, number: int) -> str:
    """What «Continuar» does, in the owner's words (spec §4.3)."""
    tail = " y tu mural queda en orden" if mode == MODE_ONE_BY_ONE else ""
    return (
        "Las que salieron ya están en tu perfil. Si continúas, seguimos desde "
        f"{_from_piece(mode, kind, number)}{tail}."
    )


def continue_label(mode: str, kind: str, number: int) -> str:
    """«Continuar desde la foto {k}»."""
    return f"Continuar desde {_from_piece(mode, kind, number)}"


def keep_as_is_text(published: int, total: int) -> str:
    """The «Dejar así» confirmation of an unfinished mural (spec §4.3)."""
    return (
        f"En tu perfil quedan {published} de las {total}. Puedes publicar las otras después, "
        "pero si publicas otra cosa en medio, el mural se corre."
    )


def leave_text(remaining: int) -> str:
    """The «¿Salir mientras se publican?» body (spec §4.2)."""
    return (
        f"Las que ya salieron se quedan en tu perfil. Las {remaining} que faltan no se publicarán."
    )


def wait_text(mode: str) -> str:
    """Next to the wait: Instagram's own processing takes minutes (QUA-99 audit)."""
    what = "tu historia" if mode in STORY_MODES else "tu publicación"
    return f"Instagram está preparando {what}. Puede tardar unos minutos."


def leftover_text(mode: str, remaining: int) -> str:
    """Back on «Publicar» with pieces still waiting (spec §4.2)."""
    where = "de tus historias" if mode == MODE_STORIES else "de tu mural"
    return f"Te quedaron {remaining} sin publicar {where}."
