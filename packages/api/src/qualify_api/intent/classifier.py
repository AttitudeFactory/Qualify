"""Classifiers that turn comment texts into intent classes with confidences
(m-24789644). The service only knows `IntentClassifier`; which model sits behind it is
chosen by measuring on the golden set (`qualify_api.intent.eval`), not here.

`ClaudeIntentClassifier` is the first candidate: Claude Haiku 5.5 through the shared
`claude_tools` plumbing, several comments per call, the answer as one strict tool call.
API facts it relies on (from the `claude-api` skill, 2026-10): Haiku 5.5 thinks by
default, so the tool is not forced (`effort` set → `tool_choice: auto` and the caller
checks the tool was called); strict schemas do not take `minimum`/`maximum`, so the
[0, 1] range is enforced in `normalize_prediction`, not in the schema.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from qualify_shared import observability

from qualify_api.claude_tools import (
    CallStats,
    ClaudeToolError,
    Meter,
    ModelConfig,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)
from qualify_api.intent.contract import IntentClass

#: The model the first measurement runs against (PR 3b may change it, with numbers).
CLAUDE_INTENT_MODEL: Final = "claude-haiku-5-5"
#: Classification needs little reasoning; `low` keeps thinking (and its tokens) short.
CLAUDE_INTENT_EFFORT: Final = "low"
#: Comments per call: enough to amortize the system prompt, small enough that one bad
#: answer costs little to retry.
CLAUDE_INTENT_BATCH: Final = 25
INTENT_TOOL: Final = "registrar_intencion"

Prediction = Mapping[IntentClass, float]


class IntentClassifier(Protocol):
    """`classify` returns one prediction per text, in order. An empty prediction means
    "the model gave no usable answer for this text"; the service leaves that comment
    pending rather than inventing a class."""

    model_id: str
    model_revision: str | None

    def classify(self, texts: Sequence[str]) -> list[Prediction]: ...


def normalize_prediction(pairs: Iterable[tuple[Any, Any]]) -> dict[IntentClass, float]:
    """Keep only what `IntentSignal` accepts from `(class, confidence)` pairs: known
    classes, confidences in [0, 1] (the highest wins on a repeated class), and `general`
    dropped when a commercial class is also present — a model that says "general and
    price" asked about price."""
    kept: dict[IntentClass, float] = {}
    for name, value in pairs:
        try:
            intent_class = IntentClass(name)
            confidence = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 <= confidence <= 1.0:
            kept[intent_class] = max(confidence, kept.get(intent_class, 0.0))
    if IntentClass.GENERAL in kept and len(kept) > 1:
        del kept[IntentClass.GENERAL]
    return kept


SYSTEM_PROMPT: Final = """\
Clasificas comentarios públicos que personas dejan en publicaciones de Instagram de \
negocios (tiendas, marcas, restaurantes, servicios) en Latinoamérica. Para cada \
comentario indicas qué necesita saber quien comenta.

Clases (un comentario puede tener varias):
- product: pregunta por el producto o servicio en sí (qué es, de qué está hecho, cómo funciona).
- price: precio, costo, cuánto vale, promociones o descuentos.
- availability: si hay existencias, si todavía queda, cuándo llega o vuelve a haber.
- models: otro modelo, otra versión o un producto distinto de la misma línea.
- variants: talla, color, sabor, tamaño u otra opción del mismo producto.
- quantities: unidades disponibles, pedido mínimo o venta por mayor.
- store: dónde comprar, tienda física, punto de venta, cómo hacer el pedido.
- location: dirección o ubicación del negocio.
- hours: horario de atención o apertura.
- other_commercial: cualquier otra consulta para comprar (envíos, pagos, garantía, \
facturación, cambios y devoluciones).
- general: no hay ninguna consulta comercial (elogios, emojis, etiquetar a alguien, \
quejas sin pregunta, conversación). Nunca la combines con otra clase.

Reglas:
- Clasifica lo que el comentario pide o pregunta, aunque no use signos de pregunta \
("precio", "info", "dm" cuentan).
- Si dudas entre una clase comercial y general, elige la comercial con menor confianza.
- La confianza va de 0 a 1 y refleja qué tan seguro estás de cada clase asignada.
- Responde SIEMPRE llamando a la herramienta registrar_intencion, con una entrada por \
cada comentario recibido, usando su número.
"""


def _intent_tool() -> dict[str, Any]:
    return strict_tool(
        INTENT_TOOL,
        "Registra las clases de intención de cada comentario recibido.",
        {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "classes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "class": {
                                        "type": "string",
                                        "enum": [c.value for c in IntentClass],
                                    },
                                    "confidence": {"type": "number"},
                                },
                                "required": ["class", "confidence"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["id", "classes"],
                    "additionalProperties": False,
                },
            }
        },
    )


def _user_message(texts: Sequence[str]) -> str:
    lines = "\n".join(f"{i}. {' '.join(text.split())}" for i, text in enumerate(texts, 1))
    return f"Comentarios ({len(texts)}):\n{lines}"


ClientFactory = Callable[[str], Any]


@dataclass
class ClaudeIntentClassifier:
    api_key: str
    config: ModelConfig = ModelConfig(CLAUDE_INTENT_MODEL, CLAUDE_INTENT_EFFORT)
    client_factory: ClientFactory | None = None
    batch_size: int = CLAUDE_INTENT_BATCH
    #: Alias ids are not pinned revisions — NULL, same honest-null rule as sentiment.
    model_revision: str | None = None

    def __post_init__(self) -> None:
        self._client: Any = None
        self.last_stats: list[CallStats] = []

    @property
    def model_id(self) -> str:
        return self.config.model_id

    @observability.traced("clasificar intención de comentarios", tags=("interacciones",))
    def classify(self, texts: Sequence[str]) -> list[Prediction]:
        self.last_stats = []
        predictions: list[Prediction] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            found, stats = self._classify_batch(batch)
            self.last_stats.append(stats)
            predictions.extend(found)
        return predictions

    def _classify_batch(self, texts: Sequence[str]) -> tuple[list[Prediction], CallStats]:
        if self._client is None:
            self._client = (self.client_factory or default_client)(self.api_key)
        meter = Meter(self.config)
        response = create_turn(
            self._client,
            self.config,
            meter,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_message(texts)}],
            tools=[_intent_tool()],
            tool_choice=forced_or_auto(self.config, INTENT_TOOL),
            # Room for (low-effort) thinking plus ~60 output tokens per comment.
            max_tokens=max(4096, 120 * len(texts)),
        )
        calls = [b for b in tool_uses(response) if b.name == INTENT_TOOL]
        if not calls:
            raise ClaudeToolError(f"{self.config.model_id} did not call {INTENT_TOOL}")
        meter.tool_calls = 1
        by_id: dict[int, dict[IntentClass, float]] = {}
        for item in (calls[0].input or {}).get("results") or []:
            index = item.get("id")
            if not isinstance(index, int) or not 1 <= index <= len(texts) or index in by_id:
                continue
            by_id[index] = normalize_prediction(
                (entry.get("class"), entry.get("confidence"))
                for entry in item.get("classes") or []
                if isinstance(entry, dict)
            )
        return [by_id.get(i, {}) for i in range(1, len(texts) + 1)], meter.stats()
