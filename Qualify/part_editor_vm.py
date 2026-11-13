"""The part editor's draft and availability rules (UI-4, m-24921078), without I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from qualify_creative.schemas import PART_DESCRIPTION_MAX, PARTS_REMOVED_MAX, VideoPartPlan

from . import reel_parts_vm as parts

MAX_PARTS = 6
MAX_PARTS_TEXT = "Tu video ya tiene 6 partes, el máximo. Quita o junta una para añadir otra."
#: The parent keeps at most PARTS_REMOVED_MAX removed parts (`too_many` beyond it):
#: «Quitar» stops there and points to «Cambiar», which keeps the part's place.
MAX_REMOVED = PARTS_REMOVED_MAX
MAX_REMOVED_TEXT = (
    "Ya no puedes quitar más partes de este video. "
    "Toca «Cambiar» para hacer esta parte de otra forma."
)
QUESTION = "¿Cómo la hacemos?"
DESCRIPTION_LABEL = "¿Qué pasa en esta parte?"
DESCRIPTION_EXAMPLE = "Ej.: «Una mano acerca el vaso»."
DESCRIBE_ACTION = "Escribir qué pasa"
EXTEND_REASON = "Por ahora no está disponible. Hazla nueva."
EXTEND_FIRST_REASON = "La primera parte no tiene una anterior."
MORE_LABEL = "Video o audio tuyo"
SHEET_HELP = "Cambia solo esta parte; las demás quedan igual."
DESCRIPTION_REQUIRED = "Cuéntanos qué muestra esta parte para guardarla."
EDIT_HELP = "Conservamos el movimiento, el fondo y el ritmo; ponemos tu producto y tu marca."
REFERENCE_HELP = "Creamos una parte nueva con tu producto. La persona será otra."
NEW_HELP = "Creamos una parte nueva con tu producto y tu marca."
EXTEND_HELP = "Empieza donde termina la parte anterior."
GROUP_ID = "q-part-editor-question"
CHANGE_ID = "q-part-change-"
ADD_ID = "q-part-add"


def position(raw: object, count: int) -> int:
    """A URL names a current 1-based position, never a Python index or a foreign key."""
    if isinstance(raw, list | tuple):
        raw = raw[0] if raw else ""
    text = str(raw or "")
    if not text.isascii() or not text.isdigit():
        return 0
    value = int(text)
    return value if 1 <= value <= count else 0


def new_entry() -> dict[str, Any]:
    """One uncommitted manual part, appended only by Guardar."""
    return parts.entries_from_plan(
        None, [VideoPartPlan(mode="reference", seconds=5, notices=("describe_it",))]
    )[0]


def edit_reason(
    entry: Mapping[str, Any],
    *,
    images: Sequence[Mapping[str, str]],
    videos: Sequence[Mapping[str, str]],
    audios: Sequence[Mapping[str, str]],
    durations: Mapping[str, float | None],
) -> str:
    """An own source replaces the analysed original; neither its face status nor its
    duration is guessed. An unreadable duration never enables a false working edit."""
    plan = entry["plan"]
    if audios:
        return "Para conservar el video, quita el audio tuyo o haz esta parte nueva."
    if len(videos) > 1:
        return "Para conservar el video, deja solo un video tuyo o haz esta parte nueva."
    if videos:
        seconds = durations.get(videos[0]["key"])
        required = max(int(plan.get("seconds") or 0), 4)
        if seconds is None:
            return (
                "No pudimos comprobar cuánto dura tu video. Haz esta parte nueva o usa otro video."
            )
        if abs(seconds - required) > 0.5:
            return (
                f"Tu video debe durar {required} s para conservarlo en esta parte. "
                "Usa otro o hazla nueva."
            )
    else:
        if plan.get("original_mode") == "extend":
            return "Esta parte continúa un tramo del original. Hazla nueva o agrega un video tuyo."
        if not plan.get("analysis_id"):
            return f"Agrega un video tuyo en «{MORE_LABEL}», más abajo."
        if entry.get("person"):
            return "Aquí aparece una persona y no podemos usar ese video."
        reason = entry.get("edit_original_reason", entry.get("reason"))
        if reason == parts.REASON_UNCLEAR:
            return (
                "No pudimos comprobar si aparece una persona. "
                "Haz esta parte nueva o agrega un video tuyo."
            )
        if reason in (parts.REASON_NO_SOURCE, parts.REASON_NOT_VERTICAL):
            return "No podemos usar el video original. Haz esta parte nueva o agrega uno tuyo."
        seconds = int(plan.get("seconds") or 0)
        if seconds < 4:
            return (
                f"Esta parte dura {seconds} s y para conservar el original necesita al menos 4. "
                "Júntala con la siguiente o hazla nueva."
            )
    if not images:
        return "Agrega una foto de tu producto para conservar el video."
    return ""


def options(
    entry: Mapping[str, Any],
    index: int,
    *,
    images: Sequence[Mapping[str, str]],
    videos: Sequence[Mapping[str, str]],
    audios: Sequence[Mapping[str, str]],
    durations: Mapping[str, float | None],
    has_product: bool = True,
) -> list[dict[str, str]]:
    original = bool(entry["plan"].get("analysis_id"))
    return [
        {
            "mode": "edit",
            # no original video to keep: the only «edit» is the owner's own video
            "label": "Tu video, con tu marca" if videos or not original else parts.FORM_EDIT,
            "help": EDIT_HELP,
            "reason": edit_reason(
                entry, images=images, videos=videos, audios=audios, durations=durations
            ),
        },
        {
            "mode": "reference",
            "label": parts.FORM_INSPIRED
            if original
            else (parts.FORM_NEW if has_product else parts.FORM_NEW_BRAND),
            "help": REFERENCE_HELP
            if original and (entry.get("person") or entry.get("reason") == parts.REASON_UNCLEAR)
            else NEW_HELP,
            "reason": "",
        },
        {
            "mode": "extend",
            "label": parts.FORM_EXTEND,
            "help": EXTEND_HELP,
            # VE-13 is not built yet: «Continuar la anterior» stays off for every part.
            "reason": EXTEND_FIRST_REASON if index == 1 else EXTEND_REASON,
        },
    ]


def describe_action(blocked: Sequence[int]) -> str:
    """The button that opens the first part still missing what it shows: «Escribir qué
    pasa en la parte 2» when only one is; «Escribir qué pasa» with several."""
    return f"{DESCRIBE_ACTION} en la parte {blocked[0]}" if len(blocked) == 1 else DESCRIBE_ACTION


def change_action(unsupported: Sequence[int]) -> str:
    """«Cambiar la parte 3»: the first part that cannot be created as it is."""
    return f"Cambiar la parte {unsupported[0]}" if unsupported else "Cambiar la parte"


def more_opens(entry: Mapping[str, Any]) -> bool:
    """«Video o audio tuyo» unfolds by itself only when an own video is the one way to
    use «Igual al original»: the part has no analysed original video to keep."""
    return not entry.get("plan", {}).get("analysis_id")


#: Why «Juntar con la siguiente» did not work, by `parts_plan.PLAN_MERGE_*` code.
MERGE_DESCRIPTION_TEXT = "Acorta las descripciones de las dos partes antes de juntarlas."
MERGE_PHOTOS_TEXT = "Usa las mismas fotos en las dos partes para juntarlas."
MERGE_UNAVAILABLE_TEXT = (
    "No podemos juntar estas partes conservando el original. Haz esta parte nueva."
)


def merge_refusal_text(reason: str) -> str:
    """The owner's words for a refused «Juntar con la siguiente» (`PartsPlanRefused.reason`)."""
    if reason == "merge_description":
        return MERGE_DESCRIPTION_TEXT
    if reason == "merge_photos":
        return MERGE_PHOTOS_TEXT
    return MERGE_UNAVAILABLE_TEXT


def merged_text(index: int) -> str:
    """The confirmation once «Juntar con la siguiente» worked (1-based, as shown)."""
    return f"Listo: las partes {index} y {index + 1} quedan juntas al guardar."


def media_limit_text(kind: str) -> str:
    """Why one more photo/video/audio does not fit in the part."""
    if kind == "image":
        return "Ya tienes 9 fotos, el máximo. Quita una para agregar otra."
    noun = "videos" if kind == "video" else "audios"
    return f"Ya tienes 3 {noun}, el máximo. Quita uno para agregar otro."


def save_reason(
    mode: str,
    description: str,
    choices: Sequence[Mapping[str, str]],
    *,
    preserved_extend: bool = False,
    has_own_media: bool = False,
) -> str:
    if not description.strip():
        return DESCRIPTION_REQUIRED
    if len(description) > PART_DESCRIPTION_MAX:
        return f"Describe esta parte en {PART_DESCRIPTION_MAX} caracteres o menos."
    if mode == "extend" and has_own_media:
        return "Para usar tu video o audio, elige hacer esta parte nueva."
    if mode == "extend" and preserved_extend:
        return ""
    return next(
        (o["reason"] for o in choices if o["mode"] == mode), "Elige cómo hacemos esta parte."
    )


def updated_plan(
    original: Mapping[str, Any],
    *,
    mode: str,
    description: str,
    images: Sequence[Mapping[str, str]],
    inherit_images: bool,
    videos: Sequence[Mapping[str, str]],
    audios: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """Keep cut identity/timing/provenance. Media is explicit per part; only photos
    have the deliberate None=inherited, []=cleared distinction."""
    return {
        **original,
        "mode": mode,
        "description": description.strip(),
        "clip_image_keys": None if inherit_images else [item["key"] for item in images],
        "clip_image_roles": []
        if inherit_images
        else [item.get("role") or "product" for item in images],
        "clip_video_keys": [item["key"] for item in videos],
        "clip_audio_keys": [item["key"] for item in audios],
    }
