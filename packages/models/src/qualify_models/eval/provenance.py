from __future__ import annotations

from pydantic import BaseModel


class StageProvenance(BaseModel):
    """Which checkpoint produced a stage's metrics on a given run.

    `revision` is the HF Hub commit sha of the checkpoint; None means it could
    not be resolved (e.g. an offline run). It is never fabricated — an
    unresolved revision stays None so a report can't imply provenance it
    doesn't have.
    """

    stage: str
    model_id: str
    detector_version: str | None = None
    revision: str | None = None


def resolve_revision(model_id: str) -> str | None:
    """Best-effort resolution of a checkpoint's current Hub commit sha. Hits the
    network, so callers running offline should pass a stub resolver instead.
    Returns None on any failure rather than raising — provenance is recorded as
    unresolved, not invented."""
    try:
        from huggingface_hub import HfApi

        return HfApi().model_info(model_id).sha
    except Exception:
        return None
