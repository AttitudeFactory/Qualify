"""«Sugerir con IA» the line of a character's scene (m-25129386, epic m-25129420, ADR 50
§12.2): Claude Haiku 5.5 proposes what the business's saved character says to the camera
in a 5 to 10 second scene, about one Catálogo product. The owner reads it, may edit it,
and only then it goes into the scene (`CharacterSceneItem.line_suggested` +
`line_prompt_version`): a line the owner did not see is never used.

**What the server trusts.** Only ids from the editor: the character, the product, the
brand and the scene's key. The saved character (`business_characters`, status `saved`,
this brand), the product (`brand_products`, active, this brand) and the Brand Kit are
read here through `tenant_session` (RLS) — never their text from the editor. With the
switch off (`QUALIFY_CLIP_CHARACTER_SCENE`, ADR 50 §12.5, P3) the request is refused with
`switched_off` before anything is read.

**The prompt** (`LINE_PROMPT_VERSION`): plain neutral Spanish, first person, ONE sentence,
aimed at `max_chars - LINE_MARGIN_CHARS` so a slightly long answer still fits — said in
characters AND words, with an example sentence of the right size, and asked TWICE in the
same call (`line`, then a shorter `shorter_line`): the first that fits is kept, the call
counts once (v2; strict tools do not enforce `maxLength`, so the length is checked
here); no price,
promotion, date or fact that is not in the input (the catalog price is never sent: a
spoken price is the one fact a scene must not get wrong, so the line has none — brand rule
7, «whole or not at all»); no emojis, hashtags, digits or English words, and a foreign
name is written the way it sounds (R2 of ADR 50 §12.9). One strict tool, `propose_line`,
that also lists any fact the model added; a refusal (`stop_reason == "refusal"`) or a
listed fact is a failed suggestion. The Brand Kit's palette and typefaces are left out on
purpose: a spoken line has nothing to colour or set in a font; its voice (positioning,
audience, tone, banned words and claims) goes in.

**What comes back** is normalized like the schema's own `_line_said` (one space between
words) and validated by building a `CharacterSceneItem` with it — the length the scene
takes (`character_line_max_chars`: 37 characters at 5 s, 82 at 8 s, 112 at 10 s). Never
retried (the client is built with `max_retries=0` and the service asks once): a line too
long, empty, refused or with an invented fact is `line_suggestion_failed`, and it COUNTS
for the day — it was paid.

**Free for the owner, capped for us.** No creación and no vista previa are used. Each
suggestion is ONE `creative_usage_events` row (`unit = 'character_line'`, provider
`anthropic`, draft-less, `subject_key` = the scene's key, migration 0192), RESERVED before
the call in one `tenant_session` under the business's and the scene's transaction locks:

- a repeated tap (`id = uuid5(tenant, scene_key, request_key)` already there) is
  `suggestion_repeated` and the model is NOT called;
- at most `SCENE_DAILY_SUGGESTIONS` (10) a scene and `BUSINESS_DAILY_SUGGESTIONS` (30) a
  business per day of the business (`tenants.timezone`, empty → UTC) — the business cap
  (the coordinator's decision, 2026-11-27, for Deivid to review) stops made-up scene
  keys from getting past the scene's;
- the brand's monthly dollar cap (`creative_engine_config`, hard stop) must hold the
  reservation (`LINE_MAX_USD`), which is added to its spend at once.

After the call the row is SETTLED to what was billed (tokens and USD from the meter) and
the brand's spend corrected by the difference. Known limit: `budget_spent_usd` is
`numeric(10,2)` in the database (0009, while the ORM says 12,6), so a sub-cent call rounds
away from the brand's spend once settled; the exact cost stays on the event row
(`numeric(12,6)`) and in the consumption ledger. Only when nothing was billed (the meter
refusing the turn, an API error with no answer) is the reservation given back: the
row is VOIDED (`unit = 'character_line_released'`, US$0 — the app role has no DELETE on
the cost table, 0009), it no longer counts, its dollars return to the brand and the same
tap may ask again. A dropped connection or a timeout may have been billed: the row stays
at the bound — an overcount, never an undercount. The run's `DollarMeter` is
`LINE_MAX_USD` (US$0.01). The call is ALSO booked to the consumption ledger by
`claude_tools` (feature `sugerir-linea-personaje`); no report adds the two.

There is no HTTP route here: the button and the screen are m-25112921.
"""

from __future__ import annotations

import logging
import os
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import UUID, uuid5

from pydantic import ValidationError
from qualify_creative.schemas import (
    CHARACTER_SCENE_MAX_S,
    CHARACTER_SCENE_MIN_S,
    CharacterSceneItem,
    character_line_max_chars,
)
from qualify_shared import observability

from qualify_api.claude_tools import (
    Attribution,
    BudgetExhausted,
    ClaudeToolError,
    ClientFactory,
    DollarMeter,
    Meter,
    MissingAPIKey,
    ModelConfig,
    api_key_from_env,
    create_turn,
    forced_or_auto,
    strict_tool,
    tool_uses,
)
from qualify_api.creative.character_scene import (
    CHARACTER_MISSING,
    SWITCHED_OFF,
    scene_enabled,
)
from qualify_api.creative.clip_avatar import ClipAvatarRefused

if TYPE_CHECKING:
    from qualify_creative.schemas import BrandKit

logger = logging.getLogger("qualify_api.creative.character_line_ai")

LINE_MODEL: Final = ModelConfig("claude-haiku-5-5", effort="low")
#: v2 (2026-11-27): v1's only live sample came back too long (LINEA-001, 1 of 1 over 82
#: characters at 8 s). v2 states the length in characters AND words, shows a sentence of the
#: right length, and asks for TWO candidates in the same call (the second shorter); the
#: first that fits is kept. Not measured live yet.
LINE_PROMPT_VERSION: Final = "personaje-linea-v2"
#: About this many characters per spoken Spanish word, space included (for the word cap).
CHARS_PER_WORD: Final = 6
TOOL_NAME: Final = "propose_line"
#: The function the consumption ledger books these calls to (m-24955649).
FEATURE: Final = "sugerir-linea-personaje"
#: The prompt aims this many characters below the scene's limit.
LINE_MARGIN_CHARS: Final = 5
#: Room for low-effort thinking plus a one-sentence tool call.
MAX_TOKENS: Final = 2048
#: The run's dollar meter AND the reservation of one suggestion (Haiku 5.5 at its card:
#: a ~1.5K-token prompt and the whole `MAX_TOKENS` cost about US$0.0012).
LINE_MAX_USD: Final = Decimal("0.01")
SCENE_DAILY_SUGGESTIONS: Final = 10
#: The coordinator's decision (2026-11-27, for Deivid to review): so made-up scene keys
#: cannot pass the scene's cap.
BUSINESS_DAILY_SUGGESTIONS: Final = 30
#: `creative_usage_events.unit` of one suggestion.
USAGE_UNIT: Final = "character_line"
#: The unit of a reservation whose call billed nothing (voided at US$0, never counted).
RELEASED_UNIT: Final = "character_line_released"
PROVIDER: Final = "anthropic"
REQUEST_KEY_MAX: Final = 100
_USAGE_NAMESPACE: Final = UUID("2d6a51c4-8b1e-4f0a-9c33-251293860001")
#: Placeholders that let the answer be validated as a real scene (never stored).
_CHECK_PHOTO_KEY: Final = "check/line"
_CHECK_BACKGROUND_KEY: Final = "check/place"

# -- codes the screen reads (never the text) ---------------------------------------------

LINE_DAILY_CAP: Final = "line_daily_cap"
LINE_BUSINESS_DAILY_CAP: Final = "line_business_daily_cap"
PRODUCT_MISSING: Final = "product_missing"
LINE_SUGGESTION_FAILED: Final = "line_suggestion_failed"
LINE_SUGGESTION_UNAVAILABLE: Final = "line_suggestion_unavailable"
#: The brand's monthly dollar cap (hard stop) holds no more suggestions this month.
LINE_BUDGET_CAP: Final = "line_budget_cap"
SUGGESTION_REPEATED: Final = "suggestion_repeated"
SCENE_DURATION: Final = "character_scene_duration"

# -- what the owner reads (Spanish, `qualify-copy-es`; the screen is m-25112921) ---------

REFUSAL_TEXT: Final[Mapping[str, str]] = {
    SWITCHED_OFF: (
        "Las sugerencias para tu personaje todavía no están disponibles. "
        "Mientras tanto, escribe tú lo que dice."
    ),
    CHARACTER_MISSING: (
        "No encontramos el personaje de esta escena. Elige uno y vuelve a pedir la sugerencia."
    ),
    SCENE_DURATION: (
        f"Cada escena dura de {CHARACTER_SCENE_MIN_S} a {CHARACTER_SCENE_MAX_S} segundos. "
        "Cambia cuánto dura y vuelve a pedir la sugerencia."
    ),
    PRODUCT_MISSING: (
        "No encontramos ese producto en tu catálogo. Elige otro producto para la escena."
    ),
    LINE_DAILY_CAP: (
        f"Hoy ya pediste {SCENE_DAILY_SUGGESTIONS} sugerencias para esta escena. "
        "Escribe tú lo que dice tu personaje, o pide más mañana."
    ),
    LINE_BUSINESS_DAILY_CAP: (
        f"Hoy ya pediste {BUSINESS_DAILY_SUGGESTIONS} sugerencias, que es lo máximo por día. "
        "Escribe tú lo que dice tu personaje, o pide más mañana."
    ),
    LINE_SUGGESTION_FAILED: ("No nos salió una buena frase esta vez. Pide otra o escríbela tú."),
    LINE_SUGGESTION_UNAVAILABLE: (
        "Ahora no podemos sugerir lo que dice tu personaje. Inténtalo en unos minutos o "
        "escríbelo tú."
    ),
    LINE_BUDGET_CAP: "Este mes ya no podemos sugerir lo que dice tu personaje. Escríbelo tú.",
    SUGGESTION_REPEATED: "Ya pediste esta sugerencia. Si no aparece en unos segundos, pide otra.",
}


def left_today_text(left: int, *, scene: bool = False) -> str:
    """How many suggestions the owner still has today: `left` is the lower of both caps,
    `scene` whether the scene's cap is the one that binds (then the words say so — the
    business may still have suggestions for another scene)."""
    where = " para esta escena" if scene else ""
    if left <= 0:
        if scene:
            return (
                "Ya no te quedan sugerencias para esta escena hoy. Puedes pedirlas en otra escena."
            )
        return "Ya no te quedan sugerencias hoy. Mañana tienes más."
    if left == 1:
        return f"Te queda 1 sugerencia{where} hoy."
    return f"Te quedan {left} sugerencias{where} hoy."


class CharacterLineRefused(ClipAvatarRefused):
    """A suggestion refused or failed: a stable `code` for the screen and the owner's
    `owner_message` (never `str(exc)`, which is English)."""

    def __init__(self, code: str, raw: str = "") -> None:
        super().__init__(code, REFUSAL_TEXT[code], raw)


@dataclass(frozen=True)
class LineSuggestion:
    """One suggested line, with what the screen shows next to it and its provenance."""

    line: str
    max_chars: int
    left_today: int
    prompt_version: str
    model_id: str
    cost_usd: Decimal
    #: Whether `left_today` is the scene's cap (else the business's).
    left_for_scene: bool = False

    @property
    def left_today_text(self) -> str:
        return left_today_text(self.left_today, scene=self.left_for_scene)


# -- what the server reads (never trusted from the editor) ---------------------------------


@dataclass(frozen=True)
class LineCharacter:
    name: str
    style: str
    description: str


@dataclass(frozen=True)
class LineProduct:
    name: str
    category: str
    description: str


class LineReads(Protocol):
    def character(
        self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID
    ) -> LineCharacter | None:
        """The SAVED character of this brand, or None."""
        ...

    def product(self, *, tenant_id: UUID, brand_id: UUID, product_id: UUID) -> LineProduct | None:
        """The ACTIVE Catálogo product of this brand, or None."""
        ...

    def kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit | None: ...

    def brand_name(self, *, tenant_id: UUID, brand_id: UUID) -> str: ...


@dataclass(frozen=True)
class Reservation:
    event_id: UUID
    #: Suggestions left today AFTER this one (the lower of both caps).
    left_today: int
    #: Whether the scene's cap is the lower one.
    left_for_scene: bool = False


def _left(scene_used: int, business_used: int, event_id: UUID) -> Reservation:
    """The reservation after this one: the lower cap, and whether it is the scene's."""
    scene_left = SCENE_DAILY_SUGGESTIONS - scene_used - 1
    business_left = BUSINESS_DAILY_SUGGESTIONS - business_used - 1
    return Reservation(
        event_id=event_id,
        left_today=max(0, min(scene_left, business_left)),
        left_for_scene=scene_left < business_left,
    )


class LineLedger(Protocol):
    def reserve(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        scene_key: UUID,
        event_id: UUID,
        bound_usd: Decimal,
        now: datetime,
    ) -> Reservation:
        """Count, check and reserve in ONE step, or raise `CharacterLineRefused`
        (`suggestion_repeated`, `line_daily_cap`, `line_business_daily_cap`,
        `line_budget_cap` for the brand's dollar cap)."""
        ...

    def settle(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        event_id: UUID,
        cost_usd: Decimal,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int,
        model_id: str,
    ) -> None:
        """Set the reservation to what was billed (idempotent)."""
        ...

    def release(self, *, tenant_id: UUID, brand_id: UUID, event_id: UUID) -> None:
        """Void the reservation and give its dollars back: nothing was billed."""
        ...


def usage_event_id(tenant_id: UUID, scene_key: UUID, request_key: str) -> UUID:
    """One tap, one row: a repeated `request_key` of the same scene is the same row."""
    return uuid5(_USAGE_NAMESPACE, f"{tenant_id}:{scene_key}:{request_key}")


# -- the prompt ----------------------------------------------------------------------------

SYSTEM_PROMPT: Final = (
    "Eres el guionista de un negocio pequeño. Te llega el personaje del negocio, un "
    "producto de su catálogo y la voz de la marca. Escribe lo que el personaje le dice a "
    "la cámara en un video corto mientras muestra el producto.\n\n"
    "Reglas sin excepción:\n"
    "- UNA sola frase, en primera persona (habla el personaje), en español claro y neutro, "
    "de tú, cálida y natural. Sin jerga ni palabras de una sola región.\n"
    "- Respeta el largo máximo que se indica, en caracteres (contando espacios y signos) Y "
    "en palabras. Más corta está bien; más larga no sirve y se descarta. Antes de "
    "responder, cuenta las palabras de cada frase.\n"
    "- Propón DOS frases distintas: la segunda, más corta que la primera.\n"
    "- NO inventes hechos: ningún precio, promoción, descuento, fecha, horario, dirección, "
    "cifra, ingrediente, premio ni afirmación que no esté en los datos que se te dan. "
    "Nunca digas un precio.\n"
    "- Sin números escritos con cifras: escríbelos con letras.\n"
    "- Sin emojis, sin hashtags, sin comillas, sin arrobas y sin palabras en inglés. Si un "
    "nombre es extranjero, escríbelo como se pronuncia en español (por ejemplo, "
    "«Nibbles» se escribe «Níbols»).\n"
    "- Di qué gana quien lo prueba (el sabor, la comodidad, un buen momento), usando solo "
    "lo que está en los datos.\n"
    "- Respeta las palabras y las afirmaciones prohibidas de la marca.\n\n"
    "Responde ÚNICAMENTE llamando a la herramienta propose_line."
)


def _brand_lines(kit: BrandKit | None, brand_name: str) -> list[str]:
    lines = [f"Negocio: {brand_name}"] if brand_name else []
    if kit is None:
        return lines
    if kit.positioning.strip():
        lines.append(f"Qué ofrece la marca: {kit.positioning.strip()}")
    if kit.audience.strip():
        lines.append(f"A quién le habla: {kit.audience.strip()}")
    tone = kit.tone_axes
    lines.append(
        "Tono (0 a 100): "
        f"formal→casual {tone.formal_casual}, sobrio→entusiasta {tone.sober_enthusiastic}, "
        f"técnico→sencillo {tone.technical_plain}"
    )
    if kit.banned_words:
        lines.append("Palabras prohibidas: " + ", ".join(kit.banned_words))
    if kit.forbidden_claims:
        lines.append("Afirmaciones prohibidas: " + "; ".join(kit.forbidden_claims))
    return lines


def render_request(
    *,
    character: LineCharacter,
    product: LineProduct,
    kit: BrandKit | None,
    brand_name: str,
    duration_s: int,
    target_chars: int,
) -> str:
    """The user turn: the server's own reads, one fact per line. The price is NOT sent."""
    lines = [
        "MARCA",
        *_brand_lines(kit, brand_name),
        "",
        "PERSONAJE",
        f"Nombre: {character.name}" if character.name else "Nombre: (sin nombre)",
        f"Estilo: {'dibujo animado' if character.style == 'animated' else 'realista'}",
        f"Cómo es: {character.description}",
        "",
        "PRODUCTO",
        f"Nombre: {product.name}",
    ]
    if product.category.strip():
        lines.append(f"Categoría: {product.category.strip()}")
    if product.description.strip():
        lines.append(f"Descripción: {product.description.strip()}")
    lines += [
        "",
        f"La escena dura {duration_s} segundos.",
        f"Largo máximo de cada frase: {target_chars} caracteres y "
        f"{max_words(target_chars)} palabras.",
        f"Ejemplo de una frase de largo correcto ({len(length_example(target_chars))} "
        f"caracteres): {length_example(target_chars)}",
    ]
    return "\n".join(lines)


#: Sentences of a known length, about no product in particular: the longest that fits the
#: target is shown as the size to aim for.
_LENGTH_EXAMPLES: Final = (
    "Pruébalo y me cuentas.",
    "Pruébalo hoy, te va a encantar.",
    "Mira qué rico se ve, pruébalo hoy y vas a querer repetir con tus amigos.",
    "Hola, mira esto que preparamos con tanto cariño: pruébalo hoy y vas a querer repetir conmigo.",
)


def max_words(target_chars: int) -> int:
    """The word cap that goes with `target_chars` (at least 3)."""
    return max(3, target_chars // CHARS_PER_WORD)


def length_example(target_chars: int) -> str:
    """The longest example sentence that fits `target_chars`."""
    fitting = [text for text in _LENGTH_EXAMPLES if len(text) <= target_chars]
    return max(fitting, key=len) if fitting else _LENGTH_EXAMPLES[0]


def line_tool(target_chars: int) -> dict[str, Any]:
    return strict_tool(
        TOOL_NAME,
        "Propone lo que dice el personaje en la escena.",
        {
            "line": {
                "type": "string",
                "description": (
                    f"Una sola frase de hasta {target_chars} caracteres y "
                    f"{max_words(target_chars)} palabras, en primera persona, sin comillas."
                ),
            },
            "shorter_line": {
                "type": "string",
                "description": (
                    "Otra frase distinta y MÁS CORTA que la primera, con las mismas reglas."
                ),
            },
            "added_facts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Cada hecho (precio, promoción, fecha, dato, cifra) de la frase que NO "
                    "esté en los datos dados. Vacío si no añadiste ninguno."
                ),
            },
        },
    )


# -- the answer ----------------------------------------------------------------------------

_QUOTES: Final = "\"'«»“”‘’"
#: What a spoken line never carries: a price or a figure in digits, a hashtag, a mention.
_FORBIDDEN_CHARS: Final = frozenset("#@$%€")


def _has_emoji(text: str) -> bool:
    return any(
        unicodedata.category(char) == "So" or 0x1F000 <= ord(char) <= 0x1FAFF for char in text
    )


def normalize_line(raw: str) -> str:
    """One space between words (the schema's `_line_said`), without wrapping quotes."""
    line = " ".join(str(raw).split())
    while len(line) >= 2 and line[0] in _QUOTES and line[-1] in _QUOTES:
        line = line[1:-1].strip()
    return line


def check_line(line: str, *, duration_s: int, character_id: UUID, product_id: UUID) -> str | None:
    """Why `line` cannot be the scene's (an English reason, logged), or None. The schema
    has the last word: a `CharacterSceneItem` is built with it."""
    if not line:
        return "empty"
    if any(char.isdigit() for char in line) or _FORBIDDEN_CHARS.intersection(line):
        return "digits, prices, hashtags or mentions"
    if _has_emoji(line):
        return "emoji"
    try:
        CharacterSceneItem(
            character_id=character_id,
            product={"product_id": product_id, "photo_key": _CHECK_PHOTO_KEY},
            background={"key": _CHECK_BACKGROUND_KEY},
            line=line,
            start=0,
            duration=duration_s,
            line_suggested=True,
            line_prompt_version=LINE_PROMPT_VERSION,
        )
    except ValidationError as exc:
        return ",".join(sorted({str(e.get("type")) for e in exc.errors()}))
    return None


def _maybe_billed(exc: BaseException) -> bool:
    """A dropped connection or a timeout may have reached the model and been billed."""
    names = {klass.__name__ for klass in type(exc).__mro__}
    return bool(names & {"APIConnectionError", "APITimeoutError", "TimeoutError"})


def no_retry_client(api_key: str) -> Any:
    """Anthropic itself with the SDK's own retries off: a suggestion is asked ONCE."""
    import anthropic  # noqa: PLC0415 — optional dependency (`qualify-creative[llm]`)

    return anthropic.Anthropic(api_key=api_key, max_retries=0)


# -- the service ---------------------------------------------------------------------------


class CharacterLineService:
    """`suggest` — see the module docstring."""

    def __init__(
        self,
        *,
        reads: LineReads,
        ledger: LineLedger,
        client_factory: ClientFactory = no_retry_client,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._reads = reads
        self._ledger = ledger
        self._client_factory = client_factory
        self._clock = clock
        self._env = env

    @observability.traced("sugerir línea del personaje", tags=("generador",))
    def suggest(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID,
        scene_key: UUID,
        request_key: str,
        character_id: UUID,
        product_id: UUID,
        duration_s: int,
        language: str = "es",
    ) -> LineSuggestion:
        if not scene_enabled(self._env if self._env is not None else os.environ):
            raise CharacterLineRefused(SWITCHED_OFF, "QUALIFY_CLIP_CHARACTER_SCENE is off")
        if language != "es":
            raise ValueError(f"only Spanish lines are suggested, not {language!r}")
        key = (request_key or "").strip()
        if not key or len(key) > REQUEST_KEY_MAX:
            raise ValueError("request_key must be 1 to 100 characters")
        if (
            isinstance(duration_s, bool)
            or not isinstance(duration_s, int)
            or not CHARACTER_SCENE_MIN_S <= duration_s <= CHARACTER_SCENE_MAX_S
        ):
            raise CharacterLineRefused(SCENE_DURATION, f"duration {duration_s!r}")
        character = self._reads.character(
            tenant_id=tenant_id, brand_id=brand_id, character_id=character_id
        )
        if character is None:
            raise CharacterLineRefused(CHARACTER_MISSING, f"character {character_id}")
        product = self._reads.product(tenant_id=tenant_id, brand_id=brand_id, product_id=product_id)
        if product is None:
            raise CharacterLineRefused(PRODUCT_MISSING, f"product {product_id}")
        kit = self._reads.kit(tenant_id=tenant_id, brand_id=brand_id)
        brand_name = self._reads.brand_name(tenant_id=tenant_id, brand_id=brand_id)
        max_chars = character_line_max_chars(duration_s)
        target = max_chars - LINE_MARGIN_CHARS
        try:
            client = self._client_factory(api_key_from_env())
        except MissingAPIKey as exc:  # before any reservation: nothing to give back
            raise CharacterLineRefused(LINE_SUGGESTION_UNAVAILABLE, str(exc)) from exc
        event_id = usage_event_id(tenant_id, scene_key, key)
        reservation = self._ledger.reserve(
            tenant_id=tenant_id,
            brand_id=brand_id,
            scene_key=scene_key,
            event_id=event_id,
            bound_usd=LINE_MAX_USD,
            now=self._clock(),
        )
        meter = Meter(LINE_MODEL)
        budget = DollarMeter(limit_usd=LINE_MAX_USD)
        attribution = Attribution(
            tenant_id=tenant_id,
            brand_id=brand_id,
            feature=FEATURE,
            prompt_version=LINE_PROMPT_VERSION,
        )
        try:
            response = create_turn(
                client,
                LINE_MODEL,
                meter,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": render_request(
                            character=character,
                            product=product,
                            kit=kit,
                            brand_name=brand_name,
                            duration_s=duration_s,
                            target_chars=target,
                        ),
                    }
                ],
                tools=[line_tool(target)],
                tool_choice=forced_or_auto(LINE_MODEL, TOOL_NAME),
                max_tokens=MAX_TOKENS,
                attribution=attribution,
                budget=budget,
            )
        except BudgetExhausted as exc:  # the meter refused the turn: nothing was sent
            self._give_back(tenant_id, brand_id, event_id)
            raise CharacterLineRefused(LINE_SUGGESTION_UNAVAILABLE, str(exc)) from exc
        except ClaudeToolError as exc:  # a refusal or a truncation: answered, so billed
            self._settle(tenant_id, brand_id, event_id, meter)
            raise CharacterLineRefused(LINE_SUGGESTION_FAILED, str(exc)) from exc
        except Exception as exc:
            if meter.turns or _maybe_billed(exc):
                # may have been billed: the reservation stays at its bound (an overcount)
                logger.warning(
                    "character_line.maybe_billed tenant=%s scene=%s error=%s",
                    tenant_id,
                    scene_key,
                    type(exc).__name__,
                )
            else:
                self._give_back(tenant_id, brand_id, event_id)
            raise CharacterLineRefused(LINE_SUGGESTION_UNAVAILABLE, type(exc).__name__) from exc
        self._settle(tenant_id, brand_id, event_id, meter)
        stats = meter.stats()
        calls = [use for use in tool_uses(response) if use.name == TOOL_NAME]
        answer = (calls[0].input or {}) if calls else {}
        added = [str(fact).strip() for fact in answer.get("added_facts") or () if str(fact).strip()]
        line = ""
        problem = f"no {TOOL_NAME} call" if not calls else "added facts" if added else None
        if problem is None:
            # both candidates came in the ONE paid call: the first that fits is kept
            problems: list[str] = []
            for field_name in ("line", "shorter_line"):
                candidate = normalize_line(answer.get(field_name) or "")
                why = check_line(
                    candidate,
                    duration_s=duration_s,
                    character_id=character_id,
                    product_id=product_id,
                )
                if why is None:
                    line, problems = candidate, []
                    break
                problems.append(f"{field_name}: {why}")
            problem = "; ".join(problems) or None
        logger.info(
            "character_line.suggested tenant=%s brand=%s user=%s scene=%s model=%s in=%s "
            "out=%s cost=%.6f chars=%s max=%s problem=%s prompt=%s",
            tenant_id,
            brand_id,
            user_id,
            scene_key,
            stats.model_revision or stats.model_id,
            stats.input_tokens,
            stats.output_tokens,
            stats.cost_usd,
            len(line),
            max_chars,
            problem,
            LINE_PROMPT_VERSION,
        )
        if problem is not None:
            raise CharacterLineRefused(LINE_SUGGESTION_FAILED, problem)
        return LineSuggestion(
            line=line,
            max_chars=max_chars,
            left_today=reservation.left_today,
            left_for_scene=reservation.left_for_scene,
            prompt_version=LINE_PROMPT_VERSION,
            model_id=stats.model_id,
            cost_usd=Decimal(str(stats.cost_usd)),
        )

    def _settle(self, tenant_id: UUID, brand_id: UUID, event_id: UUID, meter: Meter) -> None:
        stats = meter.stats()
        if not (stats.input_tokens or stats.output_tokens):
            return  # nothing measured: the reservation stays at its bound
        try:
            self._ledger.settle(
                tenant_id=tenant_id,
                brand_id=brand_id,
                event_id=event_id,
                cost_usd=Decimal(str(stats.cost_usd)).quantize(Decimal("0.000001")),
                input_tokens=stats.input_tokens,
                output_tokens=stats.output_tokens,
                cache_read_tokens=stats.cache_read_tokens,
                cache_creation_tokens=stats.cache_creation_tokens,
                model_id=stats.model_id,
            )
        except Exception as exc:  # noqa: BLE001 — the row stays at its bound (an overcount)
            logger.error(
                "character_line.settle_failed event=%s error=%s", event_id, type(exc).__name__
            )

    def _give_back(self, tenant_id: UUID, brand_id: UUID, event_id: UUID) -> None:
        try:
            self._ledger.release(tenant_id=tenant_id, brand_id=brand_id, event_id=event_id)
        except Exception as exc:  # noqa: BLE001 — an overcount, never an undercount
            logger.error(
                "character_line.release_failed event=%s error=%s", event_id, type(exc).__name__
            )


# -- in memory (tests and the screen's own tests, m-25112921) ------------------------------


@dataclass
class _MemoryRow:
    tenant_id: UUID
    scene_key: UUID
    cost_usd: Decimal
    day: str
    input_tokens: int = 0
    output_tokens: int = 0


class MemoryLineLedger:
    """`LineLedger` with the same rules as `PostgresLineLedger`, in a dict. The day is
    the UTC date of `now`; `spent` is the brand's spend, `remaining` its cap (None =
    none)."""

    def __init__(self, *, remaining_usd: Decimal | None = None) -> None:
        self.rows: dict[UUID, _MemoryRow] = {}
        self.spent_usd = Decimal(0)
        self.remaining_usd = remaining_usd

    def reserve(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        scene_key: UUID,
        event_id: UUID,
        bound_usd: Decimal,
        now: datetime,
    ) -> Reservation:
        if event_id in self.rows:
            raise CharacterLineRefused(SUGGESTION_REPEATED, f"event {event_id}")
        day = now.astimezone(UTC).date().isoformat()
        today = [r for r in self.rows.values() if r.tenant_id == tenant_id and r.day == day]
        scene_used = sum(1 for r in today if r.scene_key == scene_key)
        if scene_used >= SCENE_DAILY_SUGGESTIONS:
            raise CharacterLineRefused(LINE_DAILY_CAP, f"scene {scene_key}")
        if len(today) >= BUSINESS_DAILY_SUGGESTIONS:
            raise CharacterLineRefused(LINE_BUSINESS_DAILY_CAP, "business")
        if self.remaining_usd is not None and bound_usd > self.remaining_usd - self.spent_usd:
            raise CharacterLineRefused(LINE_BUDGET_CAP, "brand cap")
        self.rows[event_id] = _MemoryRow(tenant_id, scene_key, bound_usd, day)
        self.spent_usd += bound_usd
        return _left(scene_used, len(today), event_id)

    def settle(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        event_id: UUID,
        cost_usd: Decimal,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int,
        model_id: str,
    ) -> None:
        row = self.rows.get(event_id)
        if row is None:
            return
        self.spent_usd += Decimal(cost_usd) - row.cost_usd
        row.cost_usd = Decimal(cost_usd)
        row.input_tokens, row.output_tokens = input_tokens, output_tokens

    def release(self, *, tenant_id: UUID, brand_id: UUID, event_id: UUID) -> None:
        row = self.rows.pop(event_id, None)
        if row is not None:
            self.spent_usd -= row.cost_usd


# -- production wiring ---------------------------------------------------------------------


class PostgresLineReads:
    """Every read through `tenant_session` (RLS): only this business's rows."""

    def character(
        self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID
    ) -> LineCharacter | None:
        from qualify_api.creative.business_characters import (  # noqa: PLC0415
            STATUS_SAVED,
            PostgresCharacterRepository,
        )

        found = PostgresCharacterRepository().get(tenant_id=tenant_id, character_id=character_id)
        if (
            found is None
            or found.brand_id != brand_id
            or found.status != STATUS_SAVED
            or found.deleted_at is not None
        ):
            return None
        return LineCharacter(
            name=found.name or "", style=found.style, description=found.description
        )

    def product(self, *, tenant_id: UUID, brand_id: UUID, product_id: UUID) -> LineProduct | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.catalog.models import BrandProduct  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(BrandProduct).where(
                    BrandProduct.id == product_id,
                    BrandProduct.brand_id == brand_id,
                    BrandProduct.is_active.is_(True),
                )
            )
            if row is None:
                return None
            return LineProduct(
                name=row.name, category=row.category or "", description=row.description or ""
            )

    def kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit | None:
        from qualify_api.creative.brand_service import BrandKitService  # noqa: PLC0415

        return BrandKitService().get_kit(tenant_id=tenant_id, brand_id=brand_id)

    def brand_name(self, *, tenant_id: UUID, brand_id: UUID) -> str:
        from qualify_api.creative.brand_names import DbBrandNames  # noqa: PLC0415

        return DbBrandNames()(tenant_id=tenant_id, brand_id=brand_id)


_DAY_START_SQL: Final = """
    (date_trunc('day', now() AT TIME ZONE z.zone) AT TIME ZONE z.zone)
"""
_ZONE_CTE: Final = """
    WITH z AS (
      SELECT COALESCE(NULLIF(
        (SELECT timezone FROM tenants WHERE id = :tenant), ''), 'UTC') AS zone
    )
"""


class PostgresLineLedger:
    """`LineLedger` over `creative_usage_events` + the brand's `creative_engine_config`
    (see the module docstring). Every write in ONE `tenant_session` per step."""

    def __init__(self, *, session_factory: Callable[[UUID], Any] | None = None) -> None:
        self._session_factory = session_factory

    def _session(self, tenant_id: UUID) -> Any:
        if self._session_factory is not None:
            return self._session_factory(tenant_id)
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        return tenant_session(tenant_id)

    def reserve(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        scene_key: UUID,
        event_id: UUID,
        bound_usd: Decimal,
        now: datetime,
    ) -> Reservation:
        from sqlalchemy import func, select, text  # noqa: PLC0415

        from qualify_api.creative import models as orm  # noqa: PLC0415

        with self._session(tenant_id) as session:
            # the business first, then the scene: the same order everywhere, and the
            # business's lock is what keeps its 30 a day exact across scenes
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('character_line'), hashtext(:t))"),
                {"t": str(tenant_id)},
            )
            session.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtext('character_line_scene'), hashtext(:s))"
                ),
                {"s": str(scene_key)},
            )
            existing = session.get(orm.CreativeUsageEvent, event_id, with_for_update=True)
            if existing is not None and existing.unit != RELEASED_UNIT:
                raise CharacterLineRefused(SUGGESTION_REPEATED, f"event {event_id}")
            counted = session.execute(
                text(
                    _ZONE_CTE
                    + """
                    SELECT count(*) AS business,
                           count(*) FILTER (WHERE u.subject_key = :scene) AS scene
                    FROM creative_usage_events u, z
                    WHERE u.tenant_id = :tenant AND u.unit = :unit
                      AND u.subject_key IS NOT NULL AND u.created_at >= """
                    + _DAY_START_SQL
                ),
                {"tenant": tenant_id, "unit": USAGE_UNIT, "scene": scene_key},
            ).one()
            scene_used, business_used = int(counted.scene or 0), int(counted.business or 0)
            if scene_used >= SCENE_DAILY_SUGGESTIONS:
                raise CharacterLineRefused(LINE_DAILY_CAP, f"scene {scene_key}: {scene_used}")
            if business_used >= BUSINESS_DAILY_SUGGESTIONS:
                raise CharacterLineRefused(LINE_BUSINESS_DAILY_CAP, f"business: {business_used}")
            config = session.scalar(
                select(orm.CreativeEngineConfig)
                .where(orm.CreativeEngineConfig.brand_id == brand_id)
                .with_for_update()
            )
            if config is not None:
                remaining = Decimal(config.monthly_budget_cap_usd) - Decimal(
                    config.budget_spent_usd
                )
                if config.hard_stop_on_cap and bound_usd > remaining:
                    raise CharacterLineRefused(LINE_BUDGET_CAP, f"brand cap: {remaining} left")
            if existing is not None:
                # a tap whose call billed nothing (released): the same tap may ask again
                existing.unit = USAGE_UNIT
                existing.cost_usd = bound_usd
                existing.occurred_at = now
                existing.created_at = func.now()
                booked = existing.id
            else:
                booked = self._insert(
                    session, tenant_id, brand_id, scene_key, event_id, bound_usd, now
                )
            if booked is None:  # another business's row with this id, or a race
                raise CharacterLineRefused(SUGGESTION_REPEATED, f"event {event_id} taken")
            if config is not None:
                config.budget_spent_usd = Decimal(config.budget_spent_usd) + bound_usd
        return _left(scene_used, business_used, event_id)

    @staticmethod
    def _insert(
        session: Any,
        tenant_id: UUID,
        brand_id: UUID,
        scene_key: UUID,
        event_id: UUID,
        bound_usd: Decimal,
        now: datetime,
    ) -> UUID | None:
        from qualify_creative.enums import PaidBy  # noqa: PLC0415
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        from qualify_api.claude_tools import PRICING_TABLE_VERSION  # noqa: PLC0415
        from qualify_api.creative import models as orm  # noqa: PLC0415

        return session.scalar(
            insert(orm.CreativeUsageEvent)
            .values(
                id=event_id,
                tenant_id=tenant_id,
                brand_id=brand_id,
                draft_id=None,
                provider=PROVIDER,
                model_id=LINE_MODEL.model_id,
                unit=USAGE_UNIT,
                subject_key=scene_key,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                pieces=0,
                cost_usd=bound_usd,
                paid_by=PaidBy.PLATFORM.value,
                pricing_table_version=PRICING_TABLE_VERSION,
                occurred_at=now,
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(orm.CreativeUsageEvent.id)
        )

    def settle(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        event_id: UUID,
        cost_usd: Decimal,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int,
        model_id: str,
    ) -> None:
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.creative import models as orm  # noqa: PLC0415

        with self._session(tenant_id) as session:
            row = session.get(orm.CreativeUsageEvent, event_id, with_for_update=True)
            if row is None or row.unit != USAGE_UNIT:
                return
            delta = Decimal(cost_usd) - Decimal(row.cost_usd)
            row.cost_usd = cost_usd
            row.model_id = model_id
            row.input_tokens = int(input_tokens)
            row.output_tokens = int(output_tokens)
            row.cache_read_tokens = int(cache_read_tokens)
            row.cache_creation_tokens = int(cache_creation_tokens)
            if delta:
                config = session.scalar(
                    select(orm.CreativeEngineConfig)
                    .where(orm.CreativeEngineConfig.brand_id == brand_id)
                    .with_for_update()
                )
                if config is not None:
                    config.budget_spent_usd = Decimal(config.budget_spent_usd) + delta

    def release(self, *, tenant_id: UUID, brand_id: UUID, event_id: UUID) -> None:
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.creative import models as orm  # noqa: PLC0415

        with self._session(tenant_id) as session:
            row = session.get(orm.CreativeUsageEvent, event_id, with_for_update=True)
            if row is None or row.unit != USAGE_UNIT:
                return
            cost = Decimal(row.cost_usd)
            # voided, not deleted: the app role has no DELETE on the cost table (0009),
            # and the voided row still says a tap was asked and billed nothing
            row.unit = RELEASED_UNIT
            row.cost_usd = Decimal(0)
            config = session.scalar(
                select(orm.CreativeEngineConfig)
                .where(orm.CreativeEngineConfig.brand_id == brand_id)
                .with_for_update()
            )
            if config is not None:
                config.budget_spent_usd = Decimal(config.budget_spent_usd) - cost


def production_character_line_service() -> CharacterLineService:
    return CharacterLineService(reads=PostgresLineReads(), ledger=PostgresLineLedger())


__all__ = [
    "BUSINESS_DAILY_SUGGESTIONS",
    "FEATURE",
    "LINE_MAX_USD",
    "LINE_MODEL",
    "LINE_PROMPT_VERSION",
    "SCENE_DAILY_SUGGESTIONS",
    "CharacterLineRefused",
    "CharacterLineService",
    "LineSuggestion",
    "left_today_text",
    "production_character_line_service",
]
