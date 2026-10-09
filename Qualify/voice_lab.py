"""Tu voz — the voice block (§ request 2026-09-30). Since 2026-10-05 it lives only in the
Brand Kit editor (/brand/kit, views Tu voz and ¿Cómo suena?): the wizards no longer ask for
it, so it is configured after the kit is made ("que se pueda configurar después").

Two independent actions on one recording of the brand's voice:

- **Analizar**: transcribe it LOCALLY (Whisper through `faster-whisper`, no key, nothing
  sent out — `qualify_models.providers.FasterWhisperTranscriptionProvider`; the model
  loads in the background from the moment a recording starts, `prefetch_whisper`) and let
  Claude place the brand on the four tone axes (`qualify_api.creative.voice_analysis`);
  the result pre-fills the sliders, which the operator can still move — nothing is
  saved until the kit is.
- **Clonar** (manual, with consent): upload it to HeyGen and clone it
  (`HeyGenAvatarVideoAdapter.clone_voice`), recorded per brand in `brand_voice_clones`.
  The finished clone is offered first among the voices of the avatar videos on /create.

The HeyGen calls are synchronous (`httpx`), so every one runs in a thread."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.claude_tools import ClaudeToolError, MissingAPIKey, api_key_from_env
from qualify_api.creative.voice_analysis import (
    AXES,
    TRANSCRIBE_MODEL,
    NotEnoughSpeech,
    ToneSuggestion,
    analyze_recording,
    suggest_tone,
)
from qualify_api.creative.voice_clone import (
    COMPLETE,
    FAILED,
    PROCESSING,
    VoiceClone,
    VoiceCloneService,
)
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState, brand_tenant_id
from .connections_provider import acting_user_id
from .creative_provider import HEYGEN_KEY_ENV, HeyGenNotConfigured, default_brand_id
from .creative_state import CreativeState
from .tenant import tenant_uuid
from .ui import (
    callout,
    card,
    loading_spinner,
    progress_panel,
    removable_pill,
    signal_pill,
    status_dot,
)
from .ui import tokens as T

logger = logging.getLogger(__name__)

VOICE_UPLOAD_ID = "brand_voice_sample"
_AUDIO_ACCEPT = {"audio/*": [".mp3", ".wav", ".m4a", ".ogg", ".webm", ".aac", ".flac"]}
#: How long the clone is polled after it is requested (HeyGen: "in minutes").
_CLONE_POLL_SECONDS = 4.0
_CLONE_POLL_TIMEOUT_SECONDS = 300.0

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_SAMPLE = "Sube primero una grabación de tu voz."
_NO_CONSENT = "Confirma que es tu voz, o que tienes permiso de su dueño, antes de clonarla."
_NO_CLAUDE = (
    "El análisis no está disponible: falta configurar QUALIFY_ANTHROPIC_API_KEY para leer el tono."
)
_TOO_SHORT = (
    "Se entendieron muy pocas palabras. Sube una grabación de al menos 30 segundos hablando."
)
_ANALYSIS_FAILED = "No pudimos analizar la grabación. Inténtalo de nuevo en un momento."
# § request 2026-10-08: no vendor names in what the operator reads
_HEYGEN_OFF = "La clonación de voz no está disponible ahora mismo."
_CLONE_FAILED = "No pudimos clonar la voz. Prueba con una grabación más limpia."
_CLONE_DOWN = "No pudimos pedir la clonación. Inténtalo de nuevo en un momento."
_CLONE_LIMIT = "Se alcanzó el límite de voces clonadas."
_CLONE_PLAN = "Clonar voces requiere un plan de pago de HeyGen."
_DB_ERROR = "No se pudo leer la base de datos."
#: The microphone recorder, shipped INSIDE the `rx.call_script` that starts it: the
#: app's `head_components` scripts go through react-helmet and were measured not to
#: load (2026-10-01), while `call_script` is a plain `eval`. The file is idempotent
#: (`if (window.qualifyVoice) return;`), so sending it with every Grabar is safe.
_RECORDER_JS = (Path(__file__).resolve().parent.parent / "assets" / "voice-recorder.js").read_text(
    encoding="utf-8"
)
#: What `assets/voice-recorder.js` answers when it cannot record, in the operator's words.
_RECORDER_PROBLEMS = {
    "denied": "El navegador no dio permiso al micrófono. Actívalo en el candado de la "
    "barra de direcciones y vuelve a intentarlo.",
    "nomic": "No encontramos ningún micrófono conectado.",
    "unsupported": "Este navegador no puede grabar audio. Sube un archivo en su lugar.",
    "empty": "No se grabó nada. Vuelve a intentarlo.",
    "noinput": "No pudimos guardar la grabación. Vuelve a intentarlo.",
}


# ---------------------------------------------------------------------------------------
# The work, off the event loop


def _heygen() -> tuple[Any, str]:
    from qualify_creative.adapters.heygen_video import HeyGenAvatarVideoAdapter

    key = os.environ.get(HEYGEN_KEY_ENV, "").strip()
    if not key:
        raise HeyGenNotConfigured(f"{HEYGEN_KEY_ENV} is not set")
    return HeyGenAvatarVideoAdapter(), key


#: Override the local Whisper checkpoint: a `faster-whisper` model (its own names —
#: `small`, `medium` — or a CTranslate2 repo on the Hub) when `faster-whisper` is
#: installed, a `transformers` one (`openai/whisper-small`) otherwise.
WHISPER_MODEL_ENV = "QUALIFY_WHISPER_MODEL"
_local_whisper: Any = None
_whisper_lock = threading.Lock()


def _build_whisper(model_id: str) -> Any:
    """`faster-whisper` (CTranslate2, int8) when it is installed — large-v3-turbo through
    it transcribes a 35 s recording in ~16 s on a 4-core laptop CPU where the
    `transformers` pipeline took 462 s for the same words (measured 2026-10-01) — and
    the `transformers` pipeline otherwise, so an environment without it still works."""
    try:
        import faster_whisper  # noqa: F401 — only to know it is installed
        from qualify_models.providers import FasterWhisperTranscriptionProvider
    except ImportError:
        from qualify_models.providers import LocalWhisperTranscriptionProvider

        return LocalWhisperTranscriptionProvider(model_id or TRANSCRIBE_MODEL)
    if model_id:
        return FasterWhisperTranscriptionProvider(model_id)
    return FasterWhisperTranscriptionProvider()


def _whisper() -> Any:
    """The process's one Whisper provider (built on first use, the model inside it on
    its first call or `prefetch_whisper`)."""
    global _local_whisper
    with _whisper_lock:
        if _local_whisper is None:
            _local_whisper = _build_whisper(os.environ.get(WHISPER_MODEL_ENV, "").strip())
        return _local_whisper


def _transcribe_locally(path: Path) -> str:
    """Whisper on this machine; the model loads once per process."""
    text, _language = _whisper().transcribe(path)
    return text


def prefetch_whisper() -> None:
    """Load the Whisper model on a thread of its own, now — called the moment a
    recording starts or a file lands (2026-10-01): loading the weights took a
    measurable share of the wait on Analizar, and it overlaps entirely with the seconds
    the operator spends recording. Idempotent; a load already under way is left alone
    (the provider's own lock), and a failure here is just the failure the analysis
    would report later."""
    provider = _whisper()
    warm_up = getattr(provider, "warm_up", None)
    if warm_up is None:
        return

    def run() -> None:
        try:
            warm_up()
        except Exception:  # noqa: BLE001 — reported by the analysis itself, with context
            logger.warning("voice: could not warm Whisper up", exc_info=True)

    threading.Thread(target=run, name="whisper-warm-up", daemon=True).start()


def analyze_voice_sample(path: Path) -> ToneSuggestion:
    """Transcribe the recording locally and suggest its tone. Raises `MissingAPIKey`,
    `NotEnoughSpeech` or `ClaudeToolError` (and the decoder's own errors for a file
    that is not audio)."""
    api_key = api_key_from_env()  # before the slow part: no key, no transcription
    return analyze_recording(path, transcriber=_transcribe_locally, api_key=api_key)


#: What goes to HeyGen as is; anything else (a browser recording is webm/ogg, a phone
#: one m4a) is re-encoded to WAV first — HeyGen's clone docs name mp3/wav, not webm.
_CLONE_AS_IS = {".mp3": "audio/mpeg", ".wav": "audio/wav"}
_CLONE_RATE = 44_100
_CLONE_MAX_SECONDS = 300.0


def _decode_for_clone(path: Path) -> Any:
    """The recording as mono float32 samples at `_CLONE_RATE` — PyAV, through the `ml`
    group's `qualify_models` (lazy: only a recording that is not mp3/wav needs it)."""
    from qualify_models.providers import decode_audio

    return decode_audio(path, sampling_rate=_CLONE_RATE, max_seconds=_CLONE_MAX_SECONDS)


def clone_audio(path: Path) -> tuple[bytes, str, str]:
    """(bytes, filename, content type) of the recording, ready for HeyGen."""
    suffix = path.suffix.lower()
    if suffix in _CLONE_AS_IS:
        return path.read_bytes(), path.name, _CLONE_AS_IS[suffix]
    import io
    import wave

    import numpy as np

    samples = _decode_for_clone(path)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(_CLONE_RATE)
        out.writeframes(pcm)
    return buffer.getvalue(), f"{path.stem}.wav", "audio/wav"


def start_voice_clone(
    tenant_id: UUID, brand_id: UUID, user_id: UUID, path: Path, name: str
) -> VoiceClone | None:
    """Upload the recording to HeyGen, request the clone and record it for the brand
    (consent: `user_id`, now). A clone it replaces is deleted in HeyGen, best effort."""
    adapter, key = _heygen()
    data, filename, content_type = clone_audio(path)
    asset = adapter.upload_asset(
        api_key=key, file_bytes=data, filename=filename, content_type=content_type
    )
    voice_id = adapter.clone_voice(
        api_key=key, name=name, audio_asset_id=str(asset["asset_id"]), language="es"
    )
    service = VoiceCloneService()
    replaced = service.record(
        tenant_id=tenant_id,
        brand_id=brand_id,
        heygen_voice_id=voice_id,
        name=name,
        consent_by=user_id,
        language="es",
    )
    if replaced:
        try:
            adapter.delete_voice(api_key=key, voice_id=replaced)
        except Exception as exc:  # the new clone stands either way
            logger.warning("voice clone %s not deleted in HeyGen: %s", replaced, exc)
    return service.current(tenant_id=tenant_id, brand_id=brand_id)


def refresh_voice_clone(tenant_id: UUID, brand_id: UUID) -> VoiceClone | None:
    """The brand's clone, asking HeyGen for news while it is still processing."""
    service = VoiceCloneService()
    clone = service.current(tenant_id=tenant_id, brand_id=brand_id)
    if clone is None or clone.status != PROCESSING:
        return clone
    adapter, key = _heygen()
    data = adapter.get_voice(api_key=key, voice_id=clone.heygen_voice_id)
    status = str(data.get("status") or PROCESSING)
    if status not in (PROCESSING, COMPLETE, FAILED):
        status = PROCESSING
    updated = service.update_status(
        tenant_id=tenant_id,
        brand_id=brand_id,
        heygen_voice_id=clone.heygen_voice_id,
        status=status,
        failure_message=str(data.get("failure_message") or "") or None,
        language=str(data.get("language") or "") or None,
        gender=str(data.get("gender") or "") or None,
        preview_audio_url=str(data.get("preview_audio_url") or "") or None,
    )
    return updated or clone


def brand_voice_clone(tenant_id: UUID, brand_id: UUID) -> VoiceClone | None:
    return VoiceCloneService().current(tenant_id=tenant_id, brand_id=brand_id)


# ---------------------------------------------------------------------------------------
# State


#: The analysis, stage by stage, for its progress screen (real milestones, not a timer).
_STAGE_TITLES = (
    ("preparing", "Preparamos tu grabación"),
    ("transcribing", "Transcribimos lo que dices"),
    ("reading_tone", "Leemos tu tono"),
)
_STAGES = [stage for stage, _title in _STAGE_TITLES]
_STAGE_PERCENT = {"preparing": 8, "transcribing": 30, "reading_tone": 80}
_TRANSCRIPT_EXCERPT_CHARS = 280


class VoiceLabState(rx.State):
    sample_key: str = ""
    sample_name: str = ""
    sample_error: str = ""
    #: The microphone is recording (`assets/voice-recorder.js`).
    recording: bool = False

    analyzing: bool = False
    analysis_error: str = ""
    #: One row per axis after Analizar: {"poles", "value", "reason"}.
    analysis_rows: list[dict[str, str]] = []
    #: Where the analysis is (§ request 2026-10-01: a progress screen while it runs):
    #: "" | "preparing" | "transcribing" | "reading_tone".
    analysis_stage: str = ""
    #: The start of what was heard, shown with the result on ¿Cómo suena?.
    analysis_transcript: str = ""

    consent: bool = False
    cloning: bool = False
    clone_error: str = ""
    clone_status: str = ""  # "" (no clone) | processing | complete | failed
    clone_name: str = ""
    clone_preview: str = ""
    clone_failure: str = ""

    async def _ids(self) -> tuple[UUID, UUID, UUID] | None:
        """(tenant, brand, acting user) for the session, or None. Not under the lock."""
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = brand_tenant_id(auth)
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            return None
        try:
            brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
            user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        except SQLAlchemyError:
            return None
        if brand_id is None or user_id is None:
            return None
        return tenant_id, brand_id, user_id

    def _show_clone(self, clone: VoiceClone | None) -> None:
        self.clone_status = clone.status if clone else ""
        self.clone_name = clone.name if clone else ""
        self.clone_preview = clone.preview_audio_url if clone else ""
        self.clone_failure = clone.failure_message if clone else ""

    # -- the recording ----------------------------------------------------------------

    @rx.event
    async def handle_sample_upload(self, files: list[rx.UploadFile]) -> None:
        auth = await self.get_state(AuthState)
        tenant_id = tenant_uuid(brand_tenant_id(auth))
        if tenant_id is None:
            self.sample_error = _NO_SESSION
            return
        if not files:
            return
        upload = files[0]
        try:
            data = await upload.read()
        except Exception:
            self.sample_error = "No se pudo leer el archivo. Inténtalo con otro."
            return
        name = upload.name or "voz.mp3"
        key = f"uploads/{tenant_id}/{uuid4().hex}_{name}"
        target = rx.get_upload_dir() / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.sample_key, self.sample_name = key, name
        self.recording = False
        self.sample_error = ""
        self.analysis_error = ""
        self.analysis_rows = []
        prefetch_whisper()  # the model loads while the operator reads the screen

    # -- recording from the microphone (§ request 2026-09-30) ----------------------------

    @rx.event
    def start_recording(self) -> rx.event.EventSpec:
        """Opens the microphone and starts recording; the browser asks for permission
        the first time."""
        self.sample_error = ""
        return rx.call_script(
            _RECORDER_JS + "\nwindow.qualifyVoice.start()",
            callback=VoiceLabState.recorder_started,
        )

    @rx.event
    def recorder_started(self, result: str) -> None:
        if result == "recording":
            self.recording = True
            prefetch_whisper()  # the model loads while the operator speaks
            return
        self.recording = False
        self.sample_error = _RECORDER_PROBLEMS.get(str(result), _RECORDER_PROBLEMS["nomic"])

    @rx.event
    def stop_recording(self) -> rx.event.EventSpec:
        """Detener: the recording goes to the block's dropzone, so it is stored exactly
        like an uploaded file (`handle_sample_upload`)."""
        return rx.call_script(
            "window.qualifyVoice ? window.qualifyVoice.stop() : 'idle'",
            callback=VoiceLabState.recorder_stopped,
        )

    @rx.event
    def recorder_stopped(self, result: str) -> None:
        if result == "saved":
            return  # `handle_sample_upload` ends the recording state when the file lands
        self.recording = False
        if result in _RECORDER_PROBLEMS:
            self.sample_error = _RECORDER_PROBLEMS[result]

    @rx.event
    def clear_sample(self) -> None:
        self.sample_key = ""
        self.sample_name = ""
        self.analysis_rows = []
        self.analysis_error = ""
        self.analysis_transcript = ""

    @rx.var
    def analysis_percent(self) -> int:
        return _STAGE_PERCENT.get(self.analysis_stage, 0)

    @rx.var
    def analysis_steps(self) -> list[dict[str, str]]:
        """The three stages for the progress screen, each done / running / pending."""
        current = _STAGES.index(self.analysis_stage) if self.analysis_stage in _STAGES else -1
        return [
            {
                "title": title,
                "status": "done" if i < current else "running" if i == current else "pending",
            }
            for i, (_stage, title) in enumerate(_STAGE_TITLES)
        ]

    # -- Analizar ---------------------------------------------------------------------

    @rx.event(background=True)
    async def analyze_sample(self) -> None:
        async with self:
            if self.analyzing:
                return
            if not self.sample_key:
                self.analysis_error = _NO_SAMPLE
                return
            self.analyzing = True
            self.analysis_error = ""
            self.analysis_stage = "preparing"
            path = rx.get_upload_dir() / self.sample_key
        error = ""
        suggestion: ToneSuggestion | None = None
        try:
            api_key = api_key_from_env()  # before the slow part: no key, no transcription
            async with self:
                self.analysis_stage = "transcribing"
            transcript = await asyncio.to_thread(_transcribe_locally, path)
            async with self:
                self.analysis_stage = "reading_tone"
            suggestion = await asyncio.to_thread(suggest_tone, transcript, api_key=api_key)
        except MissingAPIKey:
            error = _NO_CLAUDE
        except NotEnoughSpeech:
            error = _TOO_SHORT
        except (ClaudeToolError, OSError, ValueError) as exc:
            logger.warning("voice analysis failed: %s", exc)
            error = _ANALYSIS_FAILED
        except Exception as exc:  # the ASR provider's own errors
            logger.warning("voice analysis failed: %s", type(exc).__name__)
            error = _ANALYSIS_FAILED
        async with self:
            self.analyzing = False
            self.analysis_stage = ""
            if suggestion is None:
                self.analysis_error = error
                return
            axes = suggestion.axes
            # the sliders ARE the kit's tone axes: pre-fill them, the operator decides
            creative = await self.get_state(CreativeState)
            creative.tone_formal_casual = axes.formal_casual
            creative.tone_sober_enthusiastic = axes.sober_enthusiastic
            creative.tone_technical_plain = axes.technical_plain
            creative.tone_brief_elaborate = axes.brief_elaborate
            self.analysis_rows = [
                {
                    "poles": f"{low} ↔ {high}",
                    "value": str(getattr(axes, field)),
                    "reason": suggestion.reasons.get(field, ""),
                }
                for field, low, high in AXES
            ]
            heard = " ".join(suggestion.transcript.split())
            self.analysis_transcript = (
                heard[:_TRANSCRIPT_EXCERPT_CHARS] + "…"
                if len(heard) > _TRANSCRIPT_EXCERPT_CHARS
                else heard
            )

    # -- Clonar (manual, with consent) -------------------------------------------------

    @rx.event
    def set_consent(self, value: bool) -> None:
        self.consent = bool(value)

    @rx.event(background=True)
    async def load_clone(self) -> None:
        """On load: the brand's clone, refreshed if HeyGen was still processing it."""
        ids = await self._ids()
        if ids is None:
            return
        try:
            clone = await asyncio.to_thread(refresh_voice_clone, ids[0], ids[1])
        except HeyGenNotConfigured:
            clone = await asyncio.to_thread(brand_voice_clone, ids[0], ids[1])
        except SQLAlchemyError:
            async with self:
                self.clone_error = _DB_ERROR
            return
        except Exception as exc:
            logger.warning("voice clone refresh failed: %s", exc)
            clone = await asyncio.to_thread(brand_voice_clone, ids[0], ids[1])
        async with self:
            self._show_clone(clone)
        if clone is not None and clone.status == PROCESSING:
            await self._poll_clone(ids)

    @rx.event(background=True)
    async def clone_voice(self) -> None:
        async with self:
            if self.cloning:
                return
            if not self.sample_key:
                self.clone_error = _NO_SAMPLE
                return
            if not self.consent:
                self.clone_error = _NO_CONSENT
                return
            self.cloning = True
            self.clone_error = ""
            path = rx.get_upload_dir() / self.sample_key
            creative = await self.get_state(CreativeState)
            brand_name = creative.kit_positioning.split(".")[0][:40].strip()
        ids = await self._ids()
        if ids is None:
            async with self:
                self.cloning = False
                self.clone_error = _NO_SESSION
            return
        name = f"Voz de {brand_name}" if brand_name else "Voz de la marca"
        error = ""
        clone: VoiceClone | None = None
        try:
            clone = await asyncio.to_thread(start_voice_clone, *ids, path, name)
        except HeyGenNotConfigured:
            error = _HEYGEN_OFF
        except SQLAlchemyError:
            error = _DB_ERROR
        except Exception as exc:
            code = getattr(exc, "code", None)
            error = {
                "resource_limit_reached": _CLONE_LIMIT,
                "plan_upgrade_required": _CLONE_PLAN,
            }.get(str(code), _CLONE_DOWN)
            logger.warning("voice clone request failed: %s", exc)
        async with self:
            self.cloning = False
            if clone is None:
                self.clone_error = error
                return
            self.consent = False
            self._show_clone(clone)
        await self._poll_clone(ids)

    async def _poll_clone(self, ids: tuple[UUID, UUID, UUID]) -> None:
        waited = 0.0
        while waited < _CLONE_POLL_TIMEOUT_SECONDS:
            await asyncio.sleep(_CLONE_POLL_SECONDS)
            waited += _CLONE_POLL_SECONDS
            try:
                clone = await asyncio.to_thread(refresh_voice_clone, ids[0], ids[1])
            except Exception as exc:
                logger.warning("voice clone poll failed: %s", exc)
                continue
            async with self:
                self._show_clone(clone)
                if clone is not None and clone.status == FAILED and not self.clone_failure:
                    self.clone_failure = _CLONE_FAILED
            if clone is None or clone.status != PROCESSING:
                return


# ---------------------------------------------------------------------------------------
# UI


def _analysis_row(row: rx.Var[dict[str, str]]) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(row["poles"], size="1", weight="medium"),
            rx.text(row["value"], size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            spacing="2",
            align="center",
        ),
        rx.cond(row["reason"] != "", rx.text(row["reason"], size="1", color=T.TEXT_MUTED)),
        spacing="0",
        align_items="start",
        width="100%",
    )


def _clone_block() -> rx.Component:
    status = VoiceLabState.clone_status
    can_clone = (VoiceLabState.sample_key != "") & VoiceLabState.consent
    return rx.vstack(
        rx.text("Clonar tu voz", size="2", weight="medium"),
        rx.text(
            "Para que los videos con avatar hablen con tu voz. Solo se clona cuando tú lo pides.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.match(
            status,
            (
                PROCESSING,
                rx.hstack(
                    loading_spinner("sm"),
                    rx.text("Clonando tu voz en HeyGen…", size="2", color=T.TEXT_MUTED),
                    spacing="2",
                    align="center",
                ),
            ),
            (
                COMPLETE,
                rx.vstack(
                    signal_pill(VoiceLabState.clone_name, "ok"),
                    rx.cond(
                        VoiceLabState.clone_preview != "",
                        rx.el.audio(src=VoiceLabState.clone_preview, controls=True, width="100%"),
                    ),
                    spacing="2",
                    width="100%",
                    align_items="start",
                ),
            ),
            (
                FAILED,
                callout(
                    rx.cond(
                        VoiceLabState.clone_failure != "",
                        VoiceLabState.clone_failure,
                        _CLONE_FAILED,
                    ),
                    "error",
                ),
            ),
            rx.fragment(),
        ),
        rx.cond(
            status != PROCESSING,
            rx.vstack(
                rx.checkbox(
                    "Es mi voz, o tengo permiso de su dueño para clonarla.",
                    checked=VoiceLabState.consent,
                    on_change=VoiceLabState.set_consent,
                    size="2",
                ),
                rx.button(
                    rx.icon("audio-lines", size=T.ICON_SM),
                    rx.cond(status == COMPLETE, "Volver a clonar", "Clonar mi voz"),
                    variant="soft",
                    size="2",
                    on_click=VoiceLabState.clone_voice,
                    loading=VoiceLabState.cloning,
                    disabled=~can_clone,
                ),
                spacing="2",
                align_items="start",
            ),
        ),
        rx.cond(VoiceLabState.clone_error != "", callout(VoiceLabState.clone_error, "error")),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _recorder() -> rx.Component:
    """Grabar / Detener, with a running clock the script keeps (`#q-voice-clock`)."""
    return rx.cond(
        VoiceLabState.recording,
        rx.hstack(
            # the system's dot (error tone), next to its word (P1)
            status_dot("error", "0.6rem"),
            rx.text("Grabando", size="2", weight="medium"),
            rx.el.span("0:00", id="q-voice-clock", class_name="q-nums"),
            rx.spacer(),
            rx.button(
                rx.icon("square", size=T.ICON_SM),
                "Detener",
                color_scheme="red",
                variant="soft",
                size="2",
                on_click=VoiceLabState.stop_recording,
            ),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.button(
            rx.icon("mic", size=T.ICON_SM),
            "Grabar con el micrófono",
            variant="soft",
            size="2",
            on_click=VoiceLabState.start_recording,
            width="100%",
        ),
    )


def voice_analysis_result() -> rx.Component:
    """On ¿Cómo suena?, after an analysis: what the recording said about each axis — the
    sliders below already carry these values — and the start of what was heard."""
    return rx.cond(
        VoiceLabState.analysis_rows.length() > 0,
        card(
            rx.vstack(
                rx.hstack(
                    rx.icon("circle-check", size=T.ICON_SM, color=T.tone_color("ok", 10)),
                    rx.text("Ajustamos el tono con tu grabación", size="2", weight="medium"),
                    spacing="2",
                    align="center",
                ),
                rx.foreach(VoiceLabState.analysis_rows, _analysis_row),
                rx.cond(
                    VoiceLabState.analysis_transcript != "",
                    rx.text(
                        "Lo que escuchamos: «",
                        VoiceLabState.analysis_transcript,
                        "»",
                        size="1",
                        color=T.TEXT_FAINT,
                    ),
                ),
                rx.text(
                    "Mueve los ejes de abajo si algo no te representa.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            padding="1rem 1.25rem",
            width="100%",
        ),
    )


def voice_lab_panel() -> rx.Component:
    """Tu voz: one recording, then Analizar (a blocking progress screen, then straight
    to ¿Cómo suena? with the result) and, separately, Clonar (manual, with consent)."""
    return rx.cond(
        VoiceLabState.analyzing,
        progress_panel(
            "Analizando tu voz",
            "Suele tardar menos que la grabación. La primera vez más: se descarga "
            "el modelo que transcribe.",
            value=VoiceLabState.analysis_percent,
            steps=VoiceLabState.analysis_steps,
        ),
        _voice_lab_card(),
    )


def _voice_lab_card() -> rx.Component:
    return card(
        rx.vstack(
            rx.text("Tu voz", size="3", weight="bold"),
            rx.text(
                "Graba o sube unos 30 segundos hablando de tu marca. La analizamos "
                "para ajustar el tono de abajo y, si quieres, la clonamos para tus videos. "
                "La primera vez el análisis tarda más: se descarga el modelo que transcribe.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.cond(
                VoiceLabState.sample_key != "",
                rx.hstack(
                    removable_pill(
                        VoiceLabState.sample_name,
                        VoiceLabState.clear_sample,
                        icon="audio-lines",
                        remove_label="Quitar grabación",
                    ),
                    rx.spacer(),
                    rx.button(
                        rx.icon("sparkles", size=T.ICON_SM),
                        "Analizar mi voz",
                        variant="soft",
                        size="2",
                        on_click=VoiceLabState.analyze_sample,
                        loading=VoiceLabState.analyzing,
                    ),
                    width="100%",
                    align="center",
                    wrap="wrap",
                    spacing="2",
                ),
                rx.vstack(
                    _recorder(),
                    # Always mounted while there is no recording yet: a finished
                    # recording is handed to THIS dropzone (`assets/voice-recorder.js`).
                    rx.upload(
                        rx.vstack(
                            rx.icon("upload", size=T.ICON_MD, color=T.TEXT_FAINT),
                            rx.text(
                                "O arrastra un archivo de audio (mp3, wav, m4a…) o haz clic",
                                size="1",
                                color=T.TEXT_MUTED,
                                text_align="center",
                            ),
                            spacing="1",
                            align="center",
                            class_name="q-dropzone",
                            padding="1rem",
                            width="100%",
                        ),
                        id=VOICE_UPLOAD_ID,
                        accept=_AUDIO_ACCEPT,
                        max_files=1,
                        on_drop=VoiceLabState.handle_sample_upload(
                            rx.upload_files(upload_id=VOICE_UPLOAD_ID)
                        ),
                        # `rx.upload` paints its own dashed border unless told not to:
                        # the vstack above is the dropzone's look (`.q-dropzone`)
                        border="none",
                        padding="0",
                        width="100%",
                        cursor="pointer",
                        display=rx.cond(VoiceLabState.recording, "none", "block"),
                    ),
                    spacing="2",
                    width="100%",
                ),
            ),
            rx.cond(VoiceLabState.sample_error != "", callout(VoiceLabState.sample_error, "error")),
            rx.cond(
                VoiceLabState.analysis_error != "", callout(VoiceLabState.analysis_error, "warn")
            ),
            rx.divider(),
            _clone_block(),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
        width="100%",
    )
