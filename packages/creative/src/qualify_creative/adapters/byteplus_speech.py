"""BytePlus Seed Speech — the brand's cloned voice and the voice that reads a script
(§ request 2026-10-16: «migremos todo lo que está en HeyGen… esto incluye el clonador de
voz del brandkit»).

A product apart from ModelArk: its own console, key and host
(`voice.ap-southeast-1.bytepluses.com`, header `X-Api-Key`; an ARK key answers 401).
Read from the official docs on 2026-10-16 (`docs.byteplus.com/en/docs/byteplusvoice/…`:
`voicereplication-v3-voice-training`, `…-voice-status-query`, `unidirectional_tts_http`,
`voicereplication`, `voicelist`):

- **Clone** — `POST /api/v3/tts/voice_clone` with the sample as Base64 (wav/mp3/ogg/m4a/
  aac/pcm, ≤ 10 MB, 10-15 s suggested). Post-paid voices: we choose the id
  (`custom_speaker_id`, 8-256 `[A-Za-z0-9_-]`, starts with a letter, never `xx_…`), and
  `speaker_id` carries the fixed value `"custom_speaker_id"`. `language` (es = 3, es-MX =
  16) sets the demo clip's language; `text` makes the service check the sample against
  words read aloud (a consent sentence, error 45001109 when they differ).
- **Status** — `POST /api/v3/tts/get_voice`: `status` 2 or 4 = ready for TTS, 3 = failed;
  `demo_audio` is a URL valid ONE hour (copy it, never keep the URL).
- **Synthesis** — `POST /api/v3/tts/unidirectional`, `X-Api-Resource-Id` `seed-icl-2.0` for
  a cloned voice (the id in `req_params.speaker`) or `seed-tts-1.0` for a public one, and
  the fixed `X-Api-App-Key`. The answer is a stream of JSON lines whose `data` is Base64
  audio; `code` 20000000 closes it.
- **Money and permanence** — the first real synthesis with a post-paid clone charges its
  slot (USD 2) and FIXES the voice: it can no longer be retrained. A voice only tested and
  never used is deleted after 7 days. There is no API to delete or export a voice.
- **Not verified live** (no key yet): that a post-paid clone synthesizes with its id
  straight in `speaker` (the guide's words: «pass the trained SpeakerID to the TTS
  synthesis APIs through the speaker parameter»).

httpx is imported lazily (the `video` extra), like every other vendor adapter.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from qualify_creative.enums import GenerationTask
from qualify_creative.providers import GenerationRequest, GenerationResult, PricingTable, Usage

BASE_URL = "https://voice.ap-southeast-1.bytepluses.com"
API_KEY_ENV = "QUALIFY_BYTEPLUS_SPEECH_API_KEY"
#: Fixed by the TTS docs for the X-Api-Key authentication.
APP_KEY = "aGjiRDfUWi"
#: Voice Replication 2.0 — what a cloned voice synthesizes on.
CLONE_RESOURCE = "seed-icl-2.0"
#: TTS 1.0 — where the public Spanish voices live (voicelist, read 2026-10-16).
PUBLIC_RESOURCE = "seed-tts-1.0"
#: `speaker_id` when the voice is a post-paid one with our own id.
CUSTOM_SPEAKER_MARKER = "custom_speaker_id"
#: The language codes the clone API takes (voice_training, 2026-10-16).
LANGUAGE_CODES = {"es": 3, "es-MX": 16, "mx": 16, "en": 1, "pt": 5, "pt-BR": 17}
#: The text the voice's demo clip reads (4-80 characters, in the voice's language).
DEMO_TEXT = "Hola, esta es la voz de mi marca. Así sonarán mis videos."
#: `get_voice` statuses: TTS can run on 2 (success) or 4 (active).
STATUS_READY = frozenset({2, 4})
STATUS_FAILED = 3
#: The synthesis stream's closing code.
TTS_DONE = 20_000_000
#: A clone sample the API accepts (10 MB).
MAX_SAMPLE_BYTES = 10 * 1024 * 1024
#: Characters a request may carry before the vendor refuses (`40402003`); generous for a
#: 60 s script, which is ~900 characters in Spanish.
MAX_TEXT_CHARS = 3000
#: Public Spanish voices of TTS 1.0 (voicelist, 2026-10-16) — the only Spanish ones the
#: list offers. The picker shows these; the producer accepts nothing else (besides the
#: brand's own clone), so a made-up id never reaches the vendor.
_VOICES = (
    # (id, name shown, gender, style) — the ids exactly as the voicelist prints them
    ("multi_female_sophie_conversation_wvae_bigtts", "Sofía", "female", "suave"),
    ("multi_female_maomao_conversation_wvae_bigtts", "Luna", "female", "clara"),
    ("multi_female_shuangkuaisisi_moon_bigtts", "Vale", "female", "vivaz"),
    ("multi_male_M100_conversation_wvae_bigtts", "Lucio", "male", "grave"),
    ("multi_male_xudong_conversation_wvae_bigtts", "Mateo", "male", "profunda"),
    ("multi_male_jingqiangkanye_moon_bigtts", "Tomás", "male", "divertida"),
)
PUBLIC_SPANISH_VOICES: tuple[dict[str, str], ...] = tuple(
    {"id": vid, "name": name, "gender": gender, "style": style}
    for vid, name, gender, style in _VOICES
)
PUBLIC_VOICE_IDS = frozenset(v["id"] for v in PUBLIC_SPANISH_VOICES)


class SeedSpeechError(Exception):
    """A Seed Speech call failed. Never carries the key nor the audio."""

    def __init__(self, message: str, *, code: int | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class SeedSpeechNotConfigured(SeedSpeechError):
    pass


@dataclass(frozen=True)
class VoiceStatus:
    speaker_id: str
    status: int
    demo_audio_url: str = ""
    language: int | None = None
    message: str = ""
    trainings_left: int | None = None

    @property
    def ready(self) -> bool:
        return self.status in STATUS_READY

    @property
    def failed(self) -> bool:
        return self.status == STATUS_FAILED


def language_code(tag: str) -> int:
    """The clone API's code for a regional tag (`es-MX` → 16, `es-CO` → 3)."""
    if tag in LANGUAGE_CODES:
        return LANGUAGE_CODES[tag]
    if tag.lower().startswith("es-mx"):
        return 16
    return LANGUAGE_CODES.get(tag.split("-")[0].lower(), 3)


def new_speaker_id() -> str:
    """An opaque post-paid id: `qlf-` + 24 hex — never the tenant in clear, never a
    reserved prefix (`xx_`, `S_`, `ICL_`…)."""
    return f"qlf-{uuid.uuid4().hex[:24]}"


class SeedSpeechClient:
    """The three Seed Speech calls. Every method takes the key explicitly."""

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        transport: Any = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout_seconds

    def _client(self, api_key: str, **headers: str) -> Any:
        if not api_key:
            raise SeedSpeechNotConfigured(f"{API_KEY_ENV} is not set")
        import httpx  # lazy: optional dependency

        return httpx.Client(
            base_url=self._base_url,
            headers={
                "X-Api-Key": api_key,
                "X-Api-Request-Id": str(uuid.uuid4()),
                "Content-Type": "application/json",
                **headers,
            },
            timeout=self._timeout,
            transport=self._transport,
        )

    @staticmethod
    def _json(response: Any) -> Mapping[str, Any]:
        try:
            body = response.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        code = body.get("code")
        if response.status_code >= 400 or (isinstance(code, int) and code not in (0, TTS_DONE)):
            raise SeedSpeechError(
                f"Seed Speech answered HTTP {response.status_code} code {code}: "
                f"{str(body.get('message') or '')[:200]}",
                code=code if isinstance(code, int) else None,
                status=response.status_code,
            )
        return body

    @staticmethod
    def _status(body: Mapping[str, Any], speaker_id: str) -> VoiceStatus:
        status = body.get("status")
        return VoiceStatus(
            speaker_id=str(body.get("speaker_id") or speaker_id),
            status=int(status) if isinstance(status, int) else 1,
            demo_audio_url=str(body.get("demo_audio") or ""),
            language=body.get("language") if isinstance(body.get("language"), int) else None,
            message=str(body.get("message") or ""),
            trainings_left=(
                body.get("available_training_times")
                if isinstance(body.get("available_training_times"), int)
                else None
            ),
        )

    def clone_voice(
        self,
        *,
        api_key: str,
        speaker_id: str,
        audio: bytes,
        language: int,
        audio_format: str | None = None,
        text: str | None = None,
        demo_text: str = DEMO_TEXT,
    ) -> VoiceStatus:
        """Train (or retrain, while never synthesized) the post-paid voice `speaker_id`
        on `audio`. Returns the status the service reports right away (training)."""
        if not audio:
            raise SeedSpeechError("the voice sample is empty")
        if len(audio) > MAX_SAMPLE_BYTES:
            raise SeedSpeechError("the voice sample is over 10 MB")
        sample: dict[str, object] = {"data": base64.b64encode(audio).decode("ascii")}
        if audio_format:
            sample["format"] = audio_format
        body: dict[str, object] = {
            "speaker_id": CUSTOM_SPEAKER_MARKER,
            "custom_speaker_id": speaker_id,
            "audio": sample,
            "language": language,
            "extra_params": {"demo_text": demo_text[:80]},
        }
        if text:
            body["text"] = text
        with self._client(api_key) as client:
            response = client.post("/api/v3/tts/voice_clone", json=body)
        return self._status(self._json(response), speaker_id)

    def get_voice(self, *, api_key: str, speaker_id: str) -> VoiceStatus:
        body = {"speaker_id": CUSTOM_SPEAKER_MARKER, "custom_speaker_id": speaker_id}
        with self._client(api_key) as client:
            response = client.post("/api/v3/tts/get_voice", json=body)
        return self._status(self._json(response), speaker_id)

    def synthesize(
        self,
        *,
        api_key: str,
        text: str,
        speaker: str,
        resource_id: str,
        explicit_language: str = "es",
        sample_rate: int = 24_000,
        bit_rate: int = 128_000,
        tone_fidelity: bool = False,
    ) -> bytes:
        """`text` read by `speaker`, as MP3 bytes."""
        text = " ".join(text.split())
        if not text:
            raise SeedSpeechError("nothing to read")
        if len(text) > MAX_TEXT_CHARS:
            raise SeedSpeechError(f"the script is over {MAX_TEXT_CHARS} characters")
        additions: dict[str, object] = {
            "explicit_language": explicit_language,
            "disable_markdown_filter": True,
            "disable_emoji_filter": False,
        }
        if tone_fidelity:
            additions["tone_fidelity"] = True
        body = {
            "req_params": {
                "text": text,
                "speaker": speaker,
                "audio_params": {"format": "mp3", "sample_rate": sample_rate, "bit_rate": bit_rate},
                "additions": json.dumps(additions),
            }
        }
        chunks: list[bytes] = []
        with self._client(
            api_key, **{"X-Api-Resource-Id": resource_id, "X-Api-App-Key": APP_KEY}
        ) as client:
            with client.stream("POST", "/api/v3/tts/unidirectional", json=body) as response:
                if response.status_code >= 400:
                    response.read()
                    self._json(response)  # raises with the vendor's code
                for line in response.iter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    code = event.get("code")
                    if code == TTS_DONE:
                        break
                    if code not in (0, None):
                        raise SeedSpeechError(
                            f"Seed Speech synthesis failed: code {code}: "
                            f"{str(event.get('message') or '')[:200]}",
                            code=code if isinstance(code, int) else None,
                        )
                    data = event.get("data")
                    if isinstance(data, str) and data:
                        chunks.append(base64.b64decode(data))
        audio = b"".join(chunks)
        if not audio:
            raise SeedSpeechError("Seed Speech returned no audio")
        return audio


#: The pricing table's model id for a post-paid clone's slot: charged once, on the
#: voice's first real synthesis (voicereplicationbilling, read 2026-10-15).
VOICE_SLOT_MODEL = "seed-icl-2.0-slot"


def speech_cost_usd(pricing: PricingTable, resource_id: str, characters: int) -> Decimal:
    """Characters × the resource's price per million (pricing table `per_mchar`)."""
    price = pricing.unit_price(model_id=resource_id, unit="per_mchar")
    return (price * Decimal(characters) / Decimal(1_000_000)).quantize(Decimal("0.000001"))


class SeedSpeechVoiceoverAdapter:
    """``GenerationProvider`` for a voiceover (`GenerationTask.VOICEOVER`).

    ``request.params``: ``text`` (the script, read as is), ``speaker`` (a public voice
    id or the brand's clone id — the producer decides which, never the browser),
    ``resource_id`` (`seed-icl-2.0` for a clone, `seed-tts-1.0` for a public voice),
    ``language`` (`es` | `es-mx`). The payload is the MP3's bytes."""

    name = "seed_speech"
    supports = frozenset({GenerationTask.VOICEOVER})

    def __init__(self, client: SeedSpeechClient | None = None) -> None:
        self._client = client or SeedSpeechClient()

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        params = request.params
        text = str(params.get("text") or "")
        resource = str(params.get("resource_id") or PUBLIC_RESOURCE)
        audio = self._client.synthesize(
            api_key=api_key,
            text=text,
            speaker=str(params.get("speaker") or ""),
            resource_id=resource,
            explicit_language=str(params.get("language") or "es"),
            tone_fidelity=resource == CLONE_RESOURCE,
        )
        characters = len(" ".join(text.split()))
        return GenerationResult(
            payload=audio,
            model_id=resource,
            provider=self.name,
            usage=Usage(pieces=1, input_tokens=characters),
            model_revision=resource,
        )

    def estimate_cost_usd(
        self, request: GenerationRequest, pricing: PricingTable, *, api_key: str | None = None
    ) -> Decimal:
        text = str(request.params.get("text") or "")
        resource = str(request.params.get("resource_id") or PUBLIC_RESOURCE)
        return speech_cost_usd(pricing, resource, len(" ".join(text.split())))


def poll_voice(
    client: SeedSpeechClient,
    *,
    api_key: str,
    speaker_id: str,
    timeout_seconds: float = 300.0,
    interval_seconds: float = 4.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> VoiceStatus:
    """`get_voice` until the voice is ready or failed, or the window closes (then the
    last status, still training)."""
    started = monotonic()
    while True:
        status = client.get_voice(api_key=api_key, speaker_id=speaker_id)
        if (
            status.ready
            or status.failed
            or monotonic() - started + interval_seconds > timeout_seconds
        ):
            return status
        sleep(interval_seconds)
