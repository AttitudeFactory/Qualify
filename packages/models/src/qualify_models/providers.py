from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Literal, Protocol

from PIL import Image


class VisionProvider(Protocol):
    model_id: str

    def describe(self, image_path: Path, prompt: str) -> str: ...


class TranscriptionProvider(Protocol):
    model_id: str

    def transcribe(self, audio_path: Path) -> tuple[str, str | None]: ...


class SentimentProvider(Protocol):
    """Text polarity classification. Returns (label, score).

    Added so the sentiment stage can be exercised without weights or network:
    `run_sentiment` previously constructed a `transformers.pipeline` inline,
    which made every test of it a network test on a cold cache.
    """

    model_id: str

    def classify(self, text: str) -> tuple[str, float]: ...


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
    LocalMoondreamVisionProvider.

    The offline path, not the fast one: measured >20 min for a single hook call
    on this machine with the weights offloaded to disk (NOTES_hook_pattern_spike.md
    §B.5), against 14.6 s end-to-end for HFInferenceVisionProvider. Use it when
    the run must not touch the network or a vendor; use the hosted provider for
    anything corpus-shaped.

    Correction (measured 2026-08-06): an earlier version of this docstring said no
    Inference Provider serves an account-enabled chat VLM because "featherless-ai
    rejects this account". That is false. featherless-ai serves Qwen3-VL for this
    account and answers in seconds when named explicitly; what fails is
    provider="auto" resolution. See HFInferenceVisionProvider below."""

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

    provider="featherless-ai" is explicit, not "auto", and the distinction is the
    whole reason this class works. Re-measured 2026-08-06 for Qwen3-VL-4B on this
    account:

    * provider="featherless-ai" -> HTTP 200, correct answer, seconds. The Hub
      reports featherless-ai as `live` for both Qwen3-VL-4B and -8B.
    * provider="auto"           -> `400 model_not_supported` ("is not supported by
      any provider you have enabled").

    So the account is fine and the provider is fine; only "auto" resolution is
    broken for it. Do not read the 400 as an access problem — that misreading cost
    this repo a documented "hosted VLM is blocked" conclusion that was never true.
    Never drop the explicit provider argument here."""

    def __init__(
        self, model_id: str = "Qwen/Qwen3-VL-4B-Instruct", provider: str = "featherless-ai"
    ) -> None:
        # Lazy on purpose: `huggingface_hub` lives in the `ml` dependency group,
        # deliberately excluded from the default `backend` install (CI included).
        # Importing `qualify_models.providers` for an unrelated provider (e.g.
        # `SentimentProvider`, from `qualify_api.sentiment`) must not require it.
        from huggingface_hub import InferenceClient  # noqa: PLC0415

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


VisionBackend = Literal["hosted", "local", "none"]
"""The vision backends a caller may ask for by name.

`"none"` is a first-class choice, not an error case: the deterministic and lexical
tiers of the hook extractor run without any model, so "no VLM" is a real, useful mode
and deserves a name instead of a negative flag."""

VisionBackendLabel = Literal["hosted", "local", "injected"]
"""What actually ran, recorded in output rows. `"injected"` covers a caller-supplied
provider that is neither of the two known classes (a fake in tests, a future
self-hosted endpoint) — labelling it honestly beats guessing it into one of the others."""


def build_vision_provider(
    backend: VisionBackend, model_id: str = "Qwen/Qwen3-VL-4B-Instruct"
) -> VisionProvider | None:
    """Resolve a backend name to a provider. `"none"` returns None.

    Neither branch touches the network or the disk at construction time: the hosted
    client is lazy about requests and the local one is lazy about weights, so picking a
    backend is free and only using it costs anything.
    """
    if backend == "none":
        return None
    if backend == "hosted":
        return HFInferenceVisionProvider(model_id=model_id)
    if backend == "local":
        return LocalQwenVisionProvider(model_id=model_id)
    raise ValueError(f"unknown vision backend: {backend!r}")


def label_vision_backend(provider: VisionProvider | None) -> VisionBackendLabel | None:
    """Which backend a provider instance represents, for provenance.

    Recorded per row because "the VLM said `urban_street`" means different things
    depending on whether that came from a vendor endpoint or from offloaded local
    weights — and that difference is invisible from the model id alone, which is
    identical for both.
    """
    if provider is None:
        return None
    if isinstance(provider, HFInferenceVisionProvider):
        return "hosted"
    if isinstance(provider, LocalQwenVisionProvider | LocalMoondreamVisionProvider):
        return "local"
    return "injected"


class LocalRobertuitoSentimentProvider:
    """Runs robertuito locally via transformers (CPU-friendly, ~109M params).

    Spanish social-media polarity, 3-class (POS/NEG/NEU). This is the default
    and — on the OAuth/CRM path — currently the only model in the day-one
    increment, so note that the Hub declares NO LICENSE for the
    `pysentimiento/robertuito-*` repos (re-verified 2026-07-23). That caveat is
    inherited, not new: see docs/modelos-multimodal-fase1.md:91 and
    NOTES_fase0_oauth_crm.md §4 for why the concentration changes its weight.
    """

    def __init__(self, model_id: str = "pysentimiento/robertuito-sentiment-analysis") -> None:
        self.model_id = model_id
        self._pipeline: Any = None

    def _get_pipeline(self) -> Any:
        if self._pipeline is None:
            from transformers import pipeline

            self._pipeline = pipeline(task="text-classification", model=self.model_id)
        return self._pipeline

    def classify(self, text: str) -> tuple[str, float]:
        output = self._get_pipeline()(text)[0]
        return str(output["label"]), float(output["score"])


class HFInferenceTranscriptionProvider:
    """Calls a hosted ASR model via HF Inference Providers. Swap for
    faster-whisper self-hosted once GPU serverless infra exists (Parte 3)."""

    def __init__(self, model_id: str = "openai/whisper-large-v3-turbo") -> None:
        # Lazy on purpose — same reason as `HFInferenceVisionProvider.__init__`.
        from huggingface_hub import InferenceClient  # noqa: PLC0415

        self.model_id = model_id
        self._client = InferenceClient(model=model_id, provider="auto")

    def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        output = self._client.automatic_speech_recognition(str(audio_path), model=self.model_id)
        return output.text, None
