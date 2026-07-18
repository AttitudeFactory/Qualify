from __future__ import annotations

from pathlib import Path

from qualify_models.providers import LocalQwenVisionProvider, VisionProvider
from qualify_models.schemas import VisionResult

DETECTOR_VERSION = "vision-v1"
DEFAULT_PROMPT = (
    "Describe this image for a brand social-listening pipeline: mention any "
    "products, logos, or brand-relevant objects, and the overall scene."
)


def run_vision(
    image_path: Path,
    source_id: str,
    pipeline_version: str,
    provider: VisionProvider | None = None,
    prompt: str = DEFAULT_PROMPT,
) -> VisionResult:
    provider = provider or LocalQwenVisionProvider()
    description = provider.describe(image_path, prompt)
    return VisionResult(
        source_id=source_id,
        detector_version=DETECTOR_VERSION,
        pipeline_version=pipeline_version,
        description=description,
        model_id=provider.model_id,
    )
