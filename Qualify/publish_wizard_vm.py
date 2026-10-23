"""Pure view model of «Publicar ahora» in three steps (PUBLICAR-4, m-24842986).

`/publish` is a three-step assistant (navigation guide N6): ① ¿Qué vas a publicar?
② ¿Dónde sale? ③ Revisa y publica — and it ends with a persistent «listo» plus the
next step (N3), never only a toast. Everything here is plain Python (no Reflex, no
network) so the rules — which step may advance, the review sentence, the closing
message — are unit-tested on their own (`test_publish_wizard_vm.py`).

`flow` uses the same two values as `publish_hub_state.FLOW_POSTS`/`FLOW_STORIES`
(«posts» = a publication on the profile, «stories» = a 24-hour historia); they are
repeated here as literals so this module imports nothing from the Reflex layer.
"""

from __future__ import annotations

FLOW_POSTS = "posts"
FLOW_STORIES = "stories"

STEP_WHAT = 1
STEP_WHERE = 2
STEP_REVIEW = 3
TOTAL_STEPS = 3

STEP_TITLES: dict[int, str] = {
    STEP_WHAT: "¿Qué vas a publicar?",
    STEP_WHERE: "¿Dónde sale?",
    STEP_REVIEW: "Revisa y publica",
}

# Why «Historia» cannot be picked with this selection — shown inside its own choice
# card, next to the title, as `ui.choice_card` asks for a disabled choice.
STORY_NEEDS_ONE_FILE = "Una historia lleva una sola foto o un solo video."

# The assistant card's DOM id. Changing step scrolls back to its top, so after a long
# step 1 (6-10 files) the owner lands on «Paso N de 3» and the new title, not on the
# buttons at the bottom (PUBLICAR-4 UX review).
ASSISTANT_ID = "publish-assistant"
SCROLL_TO_ASSISTANT = (
    f"document.getElementById('{ASSISTANT_ID}')?.scrollIntoView({{block: 'start'}})"
)

# Why a pick was refused. Formats and sizes are said only here, in the error
# (criterion 2): in the toast and in step 1's lasting callout.
REJECTED_FILE_TITLE = "Ese archivo no se puede usar"
REJECTED_FILE_HELP = (
    "Elige fotos JPG o videos MP4 o MOV: hasta 300 MB por video, 8 MB por foto y 10 a la vez."
)

_PLATFORM_NAMES = {"instagram": "Instagram", "facebook": "Facebook"}


def clamp_step(step: int) -> int:
    """The step a value asks for, kept inside 1..3."""
    return max(STEP_WHAT, min(TOTAL_STEPS, int(step)))


def step_counter(step: int) -> str:
    """«Paso N de 3» — M is always the real number of steps (N6)."""
    return f"Paso {clamp_step(step)} de {TOTAL_STEPS}"


def story_allowed(file_count: int) -> bool:
    """A historia carries exactly one photo or video (Meta never makes a carousel of
    one), so «Historia» is only a valid choice with one file selected."""
    return file_count == 1


def can_advance(step: int, *, file_count: int, flow: str, connection_id: str) -> bool:
    """Whether «Siguiente» may move on from `step`: step 1 needs at least one file, step 2
    a chosen account and a kind that fits the selection. Step 3 is the last one — it
    publishes instead of advancing."""
    if step == STEP_WHAT:
        return file_count > 0
    if step == STEP_WHERE:
        if not connection_id or file_count <= 0:
            return False
        return flow == FLOW_POSTS or (flow == FLOW_STORIES and story_allowed(file_count))
    return False


def next_step(step: int, *, file_count: int, flow: str, connection_id: str) -> int:
    """The step «Siguiente» lands on — the same step when the current one is not complete."""
    if can_advance(step, file_count=file_count, flow=flow, connection_id=connection_id):
        return clamp_step(step + 1)
    return clamp_step(step)


def previous_step(step: int) -> int:
    """The step «Atrás» lands on; never below the first."""
    return clamp_step(step - 1)


def platform_name(platform: str) -> str:
    """The network's name as the owner writes it («instagram» → «Instagram»)."""
    key = (platform or "").strip().lower()
    return _PLATFORM_NAMES.get(key, key.capitalize() if key else "Instagram")


def account_handle(username: str) -> str:
    """«@cuenta», whether or not the stored username already carries the @."""
    name = (username or "").strip().lstrip("@")
    return f"@{name}" if name else ""


def connection_label(username: str, platform: str) -> str:
    """How step 2's account picker names an account — «@bianki · Instagram», the same
    words as step 3's review sentence (never «bianki · instagram»)."""
    handle = account_handle(username)
    where = platform_name(platform)
    return f"{handle} · {where}" if handle else where


def review_sentence(flow: str, *, username: str, platform: str) -> str:
    """The last step's review, in words (N6): where and how it goes out, right now."""
    where = platform_name(platform)
    handle = account_handle(username)
    target = f"{where} {handle}" if handle else where
    if flow == FLOW_STORIES:
        return f"Sale ahora en {target} como historia (se ve 24 horas)."
    return f"Sale ahora en {target} como publicación."


def done_message(flow: str, *, platform: str = "instagram") -> str:
    """The persistent «listo» once the network confirmed it (N3)."""
    where = platform_name(platform)
    if flow == FLOW_STORIES:
        return f"Listo, tu historia ya está en {where} (se ve 24 horas)."
    return f"Listo, ya está en tu {where}."
