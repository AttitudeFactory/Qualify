"""The human judgement on generated pieces, as Langfuse scores
(docs/plan-observabilidad-langfuse.md §8).

Two sources:

- **Borradores** — approving a draft scores its generation's trace `aprobado = 1`, how
  much the copy was edited first (`edicion`, 0 = untouched) and which variant won;
  rejecting it scores `aprobado = 0` with the operator's reason. The trace is found by
  its seed (`trace_seed`), so nothing new is stored.
- **The annotation queue** «Revisión de imagen y video» — every generation that made an
  image or a video with Seedream or Seedance is queued, to be scored by a person on the
  scales of §6.2 (product and background fidelity, scene coherence, legible text, safe
  zone, artefacts, natural motion). HeyGen is out of the tests (2026-10-13).

Run the setup once per Langfuse server (score configs + the queue):

    just langfuse-setup
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from difflib import SequenceMatcher
from uuid import UUID

from qualify_creative.schemas import CopyPayload
from qualify_shared import observability
from qualify_shared.observability import ScoreConfig

#: The annotation queue for what code cannot measure in a generated image or video.
REVIEW_QUEUE = "Revisión de imagen y video"
#: Media from these providers is queued (the models under test; not Remotion). The
#: talking presenter's OmniHuman joins them since HeyGen's retirement (2026-10-16).
REVIEWED_PROVIDERS = frozenset({"seedream", "seedance", "omnihuman"})

SCORE_CONFIGS: tuple[ScoreConfig, ...] = (
    ScoreConfig("aprobado", "BOOLEAN", "El borrador se aprobó en Borradores (automático)."),
    ScoreConfig(
        "edicion", "NUMERIC", "Cuánto se editó el copy antes de aprobarlo; 0 = nada.", 0, 1
    ),
    ScoreConfig(
        "fidelidad_producto",
        "NUMERIC",
        "El producto de la foto subida se reconoce tal cual (forma, color, etiqueta).",
        1,
        5,
    ),
    ScoreConfig(
        "fidelidad_fondo", "NUMERIC", "El fondo subido (el local) se reconoce en la escena.", 1, 5
    ),
    ScoreConfig(
        "coherencia_escena", "NUMERIC", "La imagen muestra lo que pide la descripción.", 1, 5
    ),
    ScoreConfig("texto_legible", "BOOLEAN", "El titular y el botón se leen sin esfuerzo."),
    ScoreConfig(
        "zona_segura_ok",
        "BOOLEAN",
        "Reel o Story: nada importante queda bajo los botones de Instagram.",
    ),
    ScoreConfig(
        "artefactos",
        "BOOLEAN",
        "Hay manos deformes, objetos fundidos o texto inventado en la escena.",
    ),
    ScoreConfig("movimiento_natural", "NUMERIC", "Video: el movimiento se ve natural.", 1, 5),
    ScoreConfig(
        "fidelidad_primer_fotograma",
        "NUMERIC",
        "Video: el primer fotograma respeta el producto y la escena pedidos.",
        1,
        5,
    ),
)
#: What a person scores in the queue — everything but the two Borradores scores.
QUEUE_SCORES = tuple(c.name for c in SCORE_CONFIGS if c.name not in ("aprobado", "edicion"))


def draft_url(draft_id: UUID) -> str:
    """Where a reviewer opens the draft — its media, its copy — from the queued trace: the
    app's public origin (`REFLEX_DEPLOY_URL`, as Reflex itself reads it), else the local
    dev server. The trace carries no media bytes (§9), so this link is how the image is
    seen (2026-10-14)."""
    origin = (os.environ.get("REFLEX_DEPLOY_URL") or "http://localhost:3000").rstrip("/")
    return f"{origin}/drafts/{draft_id}"


def trace_seed(draft_id: UUID, revision: int) -> str:
    """The seed of one generation's trace: a regeneration is a new revision, a new trace."""
    return f"{draft_id}:{revision}"


def edit_distance(original: Mapping[str, object], edited: Mapping[str, object] | None) -> float:
    """How much the operator changed the copy, 0 (untouched) to 1 (rewritten): the
    dissimilarity of the post as it would be pasted (hook, caption, CTA, hashtags)."""
    if not edited:
        return 0.0
    before = CopyPayload.model_validate(original).rendered_caption()
    after = CopyPayload.model_validate(edited).rendered_caption()
    return round(1 - SequenceMatcher(None, before, after).ratio(), 3)


def score_approval(
    *,
    draft_id: UUID,
    revision: int,
    ordinal: int,
    copy: Mapping[str, object],
    edited_copy: Mapping[str, object] | None,
) -> None:
    seed = trace_seed(draft_id, revision)
    observability.score("aprobado", True, trace_seed=seed)
    observability.score("edicion", edit_distance(copy, edited_copy), trace_seed=seed)
    observability.score("variante_elegida", ordinal, trace_seed=seed)


def score_rejection(*, draft_id: UUID, revision: int, reason: str) -> None:
    observability.score(
        "aprobado", False, trace_seed=trace_seed(draft_id, revision), comment=reason or None
    )


def queue_media_for_review(*, draft_id: UUID, revision: int, providers: set[str]) -> None:
    """Queue the generation for a person when it made media with a model under test."""
    if providers & REVIEWED_PROVIDERS:
        observability.enqueue_for_review(REVIEW_QUEUE, trace_seed=trace_seed(draft_id, revision))


def setup() -> str:
    """Create the score configs and the review queue in the Langfuse server."""
    return observability.ensure_review_setup(
        SCORE_CONFIGS,
        queue=REVIEW_QUEUE,
        queue_configs=QUEUE_SCORES,
        description=(
            "Imágenes (Seedream) y videos (Seedance) del generador, para puntuar lo que el "
            "código no puede medir. Escalas en docs/plan-observabilidad-langfuse.md §6.2."
        ),
    )


def main() -> int:
    queue_id = setup()
    print(f"Listo: {len(SCORE_CONFIGS)} escalas y la cola «{REVIEW_QUEUE}» ({queue_id}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
