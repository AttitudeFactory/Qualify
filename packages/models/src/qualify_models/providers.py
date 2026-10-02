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


class ReplyDraftProvider(Protocol):
    """Text generation for one assisted reply draft (QUA-22, comments tranche).
    Returns the drafted reply text; grounding (what comment it answers, what business
    it speaks for) is entirely the caller's prompt-construction job — this Protocol
    only names the seam, same reasoning `SentimentProvider` documents for why the
    stage should be exercisable without weights or network."""

    model_id: str

    def draft_reply(self, *, comment_text: str, business_name: str | None = None) -> str: ...


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


DEFAULT_REPLY_DRAFT_MODEL_ID = "Qwen/Qwen3-VL-4B-Instruct"
"""Module-level so `qualify_api.replies.composition` can stamp `generator_version`
provenance without constructing an `HFInferenceReplyDraftProvider` (and its
`InferenceClient`) just to read a default it never otherwise needs."""

_REPLY_SYSTEM_PROMPT = (
    "Eres quien responde comentarios públicos de Instagram en nombre de un negocio. "
    "Te llega un comentario con sentimiento POSITIVO. Escribe una respuesta breve (1-2 "
    "frases), cálida y natural en español, agradeciendo o reaccionando al comentario. "
    "Básate ÚNICAMENTE en el texto del comentario — nunca inventes datos, promociones, "
    "precios ni hechos que el comentario no menciona. No uses hashtags ni emojis en "
    "exceso (máximo uno). Responde solo con el texto de la respuesta, sin comillas ni "
    "explicaciones."
)


class HFInferenceReplyDraftProvider:
    """Calls a hosted instruct LLM via HF Inference Providers for QUA-22's draft
    generator.

    Reuses the exact `(model_id, provider)` pairing `HFInferenceVisionProvider`
    already validated empirically on this account (2026-08-06, this module's own
    docstring above) — `Qwen/Qwen3-VL-4B-Instruct` via `provider="featherless-ai"`,
    explicit rather than `"auto"` for the same documented reason. Qwen3-VL is a
    chat-instruct model; calling it text-only (no `image_url` content block) is the
    same `chat_completion` request shape with one fewer content item, not a new
    integration. Deliberately does NOT introduce an unverified new model/provider pair
    for this first version — swap for a dedicated text model later via the same
    `ReplyDraftProvider` Protocol if generation quality warrants it, once real drafts
    exist to compare against.

    **Not yet exercised against a real Meta comment end-to-end** — same "corpus/design
    verified, live E2E pending" posture `replies/client.py` documents for the write
    side. The prompt in `_REPLY_SYSTEM_PROMPT` is this class's whole grounding
    contract: no comment text ever reaches the model except via this one prompt, and
    no field except the model's own text response ever leaves it.
    """

    def __init__(
        self, model_id: str = DEFAULT_REPLY_DRAFT_MODEL_ID, provider: str = "featherless-ai"
    ) -> None:
        # Lazy on purpose — same reason as `HFInferenceVisionProvider.__init__`.
        from huggingface_hub import InferenceClient  # noqa: PLC0415

        self.model_id = model_id
        self._client = InferenceClient(model=model_id, provider=provider)

    def draft_reply(self, *, comment_text: str, business_name: str | None = None) -> str:
        business_line = f" El negocio se llama {business_name}." if business_name else ""
        completion = self._client.chat_completion(
            messages=[
                {"role": "system", "content": _REPLY_SYSTEM_PROMPT + business_line},
                {"role": "user", "content": comment_text},
            ],
            model=self.model_id,
            max_tokens=120,
        )
        return (completion.choices[0].message.content or "").strip()


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


#: Whisper's own input rate.
WHISPER_SAMPLING_RATE = 16_000


def decode_audio(
    audio_path: Path,
    *,
    sampling_rate: int = WHISPER_SAMPLING_RATE,
    max_seconds: float | None = None,
) -> Any:
    """Any audio (mp3, m4a, wav, ogg, a browser's webm…) as mono float32 samples at
    `sampling_rate` — through PyAV, which bundles FFmpeg's decoders, so no `ffmpeg`
    binary has to be on PATH. `max_seconds` stops decoding early (what is analysed is
    the first stretch of a recording, never an hour of it)."""
    import av  # noqa: PLC0415 — lazy: only the transcription path needs it
    import numpy as np  # noqa: PLC0415

    limit = None if max_seconds is None else int(max_seconds * sampling_rate)
    chunks: list[Any] = []
    total = 0
    with av.open(str(audio_path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError(f"{audio_path.name} has no audio stream")
        resampler = av.AudioResampler(format="flt", layout="mono", rate=sampling_rate)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                samples = out.to_ndarray().reshape(-1)
                chunks.append(samples)
                total += samples.size
            if limit is not None and total >= limit:
                break
        else:
            for out in resampler.resample(None):  # flush what the resampler holds
                chunks.append(out.to_ndarray().reshape(-1))
    audio = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
    return audio[:limit] if limit is not None else audio


class LocalWhisperTranscriptionProvider:
    """Whisper on this machine through `transformers` (§ request 2026-09-30: transcribe
    locally — no key, nothing sent out). Same checkpoint the hosted provider calls; the
    weights download once (~1.6 GB for the turbo) and stay in the Hugging Face cache.
    The pipeline is built once per process and calls are serialized (a `transformers`
    pipeline is not meant for concurrent use). On a CPU prefer
    `FasterWhisperTranscriptionProvider` — same weights, int8, ~30× faster (measured
    2026-10-01); this one stays as the fallback when `faster-whisper` is not installed."""

    def __init__(
        self,
        model_id: str = "openai/whisper-large-v3-turbo",
        *,
        language: str = "spanish",
        max_seconds: float = 120.0,
    ) -> None:
        import threading  # noqa: PLC0415

        self.model_id = model_id
        self.language = language
        self.max_seconds = max_seconds
        self._pipeline: Any = None
        self._lock = threading.Lock()

    def _get_pipeline(self) -> Any:
        if self._pipeline is None:
            from transformers import pipeline  # noqa: PLC0415

            self._pipeline = pipeline(task="automatic-speech-recognition", model=self.model_id)
        return self._pipeline

    def warm_up(self) -> None:
        """Build the pipeline now (the weights' first read from disk takes seconds, the
        first download minutes) so a `transcribe` that follows pays none of it — meant
        for a background thread while the recording is still being made."""
        with self._lock:
            self._get_pipeline()

    def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        audio = decode_audio(audio_path, max_seconds=self.max_seconds)
        if audio.size == 0:
            return "", None
        with self._lock:
            output = self._get_pipeline()(
                {"raw": audio, "sampling_rate": WHISPER_SAMPLING_RATE},
                chunk_length_s=30,
                generate_kwargs={"language": self.language, "task": "transcribe"},
            )
        return str(output.get("text", "")).strip(), "es"


#: The large-v3-turbo weights converted for CTranslate2 (what `faster-whisper` loads).
#: Same checkpoint as `TRANSCRIBE_MODEL`, same words out (compared on real recordings
#: 2026-10-01); downloaded once (~1.6 GB) into the Hugging Face cache.
FASTER_WHISPER_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"


class FasterWhisperTranscriptionProvider:
    """Whisper on this machine through `faster-whisper` (CTranslate2, int8 on the CPU)
    — the same weights as `LocalWhisperTranscriptionProvider`, 30× faster where it
    matters (2026-10-01, a 4-core laptop CPU, a 35 s recording: 462 s through
    `transformers` in float32 against 15.6 s here, the same transcript word for word;
    the full large-v3 encoder is what `transformers` spends its time on, and int8 is
    what tames it). The default for Tu voz for that reason. Decoding goes through
    `decode_audio` as before (no `ffmpeg` binary on PATH); the model is built once per
    process and calls are serialized."""

    def __init__(
        self,
        model_id: str = FASTER_WHISPER_MODEL,
        *,
        language: str = "es",
        max_seconds: float = 120.0,
        compute_type: str = "int8",
    ) -> None:
        import threading  # noqa: PLC0415

        self.model_id = model_id
        self.language = language
        self.max_seconds = max_seconds
        self.compute_type = compute_type
        self._model: Any = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel  # noqa: PLC0415

            self._model = WhisperModel(self.model_id, device="cpu", compute_type=self.compute_type)
        return self._model

    def warm_up(self) -> None:
        """Build the model now (its first read from disk takes seconds, its first
        download minutes), so a `transcribe` that follows pays none of it."""
        with self._lock:
            self._get_model()

    def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        audio = decode_audio(audio_path, max_seconds=self.max_seconds)
        if audio.size == 0:
            return "", None
        with self._lock:
            segments, _info = self._get_model().transcribe(
                audio, language=self.language, beam_size=1, vad_filter=False
            )
            # A generator: the work happens as it is consumed, so inside the lock.
            text = " ".join(segment.text.strip() for segment in segments)
        return text.strip(), self.language


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
