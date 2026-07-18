from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Protocol

from huggingface_hub import InferenceClient
from PIL import Image


class VisionProvider(Protocol):
    model_id: str

    def describe(self, image_path: Path, prompt: str) -> str: ...


class TranscriptionProvider(Protocol):
    model_id: str

    def transcribe(self, audio_path: Path) -> tuple[str, str | None]: ...


def _image_to_data_uri(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    suffix = image_path.suffix.lstrip(".") or "jpeg"
    return f"data:image/{suffix};base64,{encoded}"


class LocalMoondreamVisionProvider:
    """Runs moondream2 locally via transformers (CPU-friendly, ~1.9B params).
    BROKEN as of transformers 5.14.1: moondream2's trust_remote_code class
    predates a transformers internal API change (expects `all_tied_weights_keys`,
    which its custom `HfMoondream` class doesn't define) — see
    docs/modelos-multimodal-fase1.md. Kept for when that's fixed upstream or
    transformers is pinned older; LocalQwenVisionProvider is the default."""

    def __init__(self, model_id: str = "vikhyatk/moondream2", revision: str = "2025-06-21") -> None:
        self.model_id = model_id
        self._revision = revision
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            from transformers import AutoModelForCausalLM

            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_id, revision=self._revision, trust_remote_code=True
            )
        return self._model

    def describe(self, image_path: Path, prompt: str) -> str:
        model = self._get_model()
        image = Image.open(image_path)
        return model.query(image, prompt)["answer"]


class LocalQwenVisionProvider:
    """Runs a Qwen VL model locally via transformers' native (non-remote-code)
    model class — avoids the trust_remote_code compatibility issues that hit
    LocalMoondreamVisionProvider. Default vision provider: no Inference
    Provider currently serves a working, account-enabled chat VLM for us
    (hf-inference has none; featherless-ai rejects this account) — see
    docs/modelos-multimodal-fase1.md."""

    def __init__(self, model_id: str = "Qwen/Qwen3-VL-4B-Instruct") -> None:
        self.model_id = model_id
        self._model: Any = None
        self._processor: Any = None

    def _get_model_and_processor(self) -> tuple[Any, Any]:
        if self._model is None:
            from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

            self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                self.model_id, dtype="auto", device_map="auto"
            )
            self._processor = AutoProcessor.from_pretrained(self.model_id)
        return self._model, self._processor

    def describe(self, image_path: Path, prompt: str) -> str:
        model, processor = self._get_model_and_processor()
        image = Image.open(image_path)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        inputs = processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(model.device)
        generated_ids = model.generate(**inputs, max_new_tokens=256)
        trimmed = generated_ids[:, inputs["input_ids"].shape[1] :]
        return processor.batch_decode(trimmed, skip_special_tokens=True)[0].strip()


class HFInferenceVisionProvider:
    """Calls a hosted VLM via HF Inference Providers. Swap for a self-hosted
    provider (same Protocol) once GPU serverless infra exists (Fase 1 Parte 3).

    provider="featherless-ai" is explicit, not "auto": for this model/account,
    "auto" resolves to `400 model_not_supported` ("not supported by any
    provider you have enabled") even though featherless-ai is the live,
    account-enabled provider and works when named directly — see
    docs/modelos-multimodal-fase1.md."""

    def __init__(
        self, model_id: str = "Qwen/Qwen3-VL-4B-Instruct", provider: str = "featherless-ai"
    ) -> None:
        self.model_id = model_id
        self._client = InferenceClient(model=model_id, provider=provider)

    def describe(self, image_path: Path, prompt: str) -> str:
        completion = self._client.chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_to_data_uri(image_path)}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            model=self.model_id,
        )
        return completion.choices[0].message.content or ""


class HFInferenceTranscriptionProvider:
    """Calls a hosted ASR model via HF Inference Providers. Swap for
    faster-whisper self-hosted once GPU serverless infra exists (Parte 3)."""

    def __init__(self, model_id: str = "openai/whisper-large-v3-turbo") -> None:
        self.model_id = model_id
        self._client = InferenceClient(model=model_id, provider="auto")

    def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        output = self._client.automatic_speech_recognition(str(audio_path), model=self.model_id)
        return output.text, None
