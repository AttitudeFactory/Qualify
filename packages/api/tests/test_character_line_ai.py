"""«Sugerir con IA» the line of a character's scene (m-25129386), over a fake Claude client
fed from `fixtures/character_line/` (a fictional business): what the model is given, the
answer's checks per scene length, the caps, the repeated tap, what is given back and what
counts, the switch, and the scene's provenance rule. No real call."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import BrandKit, CharacterSceneItem, ToneAxes

from qualify_api import claude_tools
from qualify_api.claude_tools import PRICES, ClaudeConsumption
from qualify_api.creative import character_line_ai as cl
from qualify_api.creative import character_scene as cs

FIXTURES = Path(__file__).parent / "fixtures" / "character_line"
TENANT = UUID("c0000000-0000-4000-8000-000025129386")
BRAND = uuid4()
USER = uuid4()
CHARACTER = uuid4()
PRODUCT = uuid4()
ON = {cs.SCENE_SWITCH: "on"}
NOW = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)


def _block(raw: dict[str, Any]) -> Any:
    return SimpleNamespace(**raw)


def fixture(name: str) -> Any:
    raw = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return SimpleNamespace(
        id=raw["id"],
        model=raw["model"],
        stop_reason=raw["stop_reason"],
        usage=SimpleNamespace(**raw["usage"]),
        content=[_block(b) for b in raw["content"]],
    )


class FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        answer = self._responses.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class FakeFactory:
    """A `ClientFactory`: every client it builds shares one `messages`."""

    def __init__(self, *responses: Any) -> None:
        self.messages = FakeMessages(list(responses))
        self.keys: list[str] = []

    def __call__(self, api_key: str) -> Any:
        self.keys.append(api_key)
        return SimpleNamespace(messages=self.messages)


class FakeReads:
    def __init__(self, *, character: bool = True, product: bool = True) -> None:
        self.has_character = character
        self.has_product = product
        self.calls: list[str] = []

    def character(self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID) -> Any:
        self.calls.append("character")
        if not self.has_character:
            return None
        return cl.LineCharacter(
            name="Mango", style="animated", description="Un mango sonriente con gorra azul."
        )

    def product(self, *, tenant_id: UUID, brand_id: UUID, product_id: UUID) -> Any:
        self.calls.append("product")
        if not self.has_product:
            return None
        return cl.LineProduct(
            name="Copa de mango", category="Helados", description="Mango fresco con crema."
        )

    def kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit:
        self.calls.append("kit")
        return BrandKit(
            brand_id=brand_id,
            positioning="Helados de fruta hechos cada mañana.",
            audience="Familias del barrio.",
            tone_axes=ToneAxes(
                formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
            ),
            banned_words=("barato",),
            forbidden_claims=("el mejor helado del país",),
        )

    def brand_name(self, *, tenant_id: UUID, brand_id: UUID) -> str:
        self.calls.append("brand_name")
        return "Heladería La Nube"


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(claude_tools.API_KEY_ENV, "test-key")


@pytest.fixture
def booked(monkeypatch: pytest.MonkeyPatch) -> list[ClaudeConsumption]:
    rows: list[ClaudeConsumption] = []
    monkeypatch.setattr(claude_tools, "_consumption_sink", rows.append)
    return rows


def _service(
    factory: FakeFactory,
    *,
    ledger: cl.MemoryLineLedger | None = None,
    reads: FakeReads | None = None,
    env: dict[str, str] | None = None,
) -> tuple[cl.CharacterLineService, cl.MemoryLineLedger, FakeReads]:
    ledger = ledger or cl.MemoryLineLedger()
    reads = reads or FakeReads()
    service = cl.CharacterLineService(
        reads=reads,
        ledger=ledger,
        client_factory=factory,
        clock=lambda: NOW,
        env=ON if env is None else env,
    )
    return service, ledger, reads


def _suggest(
    service: cl.CharacterLineService,
    *,
    scene: UUID | None = None,
    request: str | None = None,
    duration: int = 5,
) -> cl.LineSuggestion:
    return service.suggest(
        tenant_id=TENANT,
        brand_id=BRAND,
        user_id=USER,
        scene_key=scene or SCENE,
        request_key=request or str(uuid4()),
        character_id=CHARACTER,
        product_id=PRODUCT,
        duration_s=duration,
    )


SCENE = UUID("5ce0e000-0000-4000-8000-000025129386")


# -- the model, the prompt and the tool --------------------------------------------------


def test_the_model_is_haiku_5_5_at_its_priced_card() -> None:
    assert cl.LINE_MODEL.model_id == "claude-haiku-5-5"
    assert cl.LINE_MODEL.effort == "low"
    assert PRICES["claude-haiku-5-5"] == (0.10, 0.50)
    assert cl.LINE_PROMPT_VERSION in cs.KNOWN_LINE_PROMPT_VERSIONS


@pytest.mark.parametrize(
    ("duration", "name", "limit"), [(5, "ok_5s", 37), (8, "ok_8s", 82), (10, "ok_10s", 112)]
)
def test_a_line_per_scene_length(
    duration: int, name: str, limit: int, booked: list[ClaudeConsumption]
) -> None:
    factory = FakeFactory(fixture(name))
    service, ledger, _ = _service(factory)
    got = _suggest(service, duration=duration)
    assert got.max_chars == limit
    assert got.line == fixture(name).content[0].input["line"]
    assert got.prompt_version == cl.LINE_PROMPT_VERSION
    assert got.model_id == "claude-haiku-5-5"
    assert got.left_today == 9
    assert got.left_today_text == "Te quedan 9 sugerencias para esta escena hoy."
    # cost: 820 in + 60 out at Haiku 5.5's card, booked to the row and the meter
    assert got.cost_usd == Decimal(str((820 * 0.10 + 60 * 0.50) / 1_000_000))
    (row,) = ledger.rows.values()
    assert row.cost_usd == Decimal("0.000112") and row.input_tokens == 820
    assert ledger.spent_usd == Decimal("0.000112")
    # the request: the prompt aims 5 below the limit, the tool is strict, no retries here
    (call,) = factory.messages.calls
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_config"] == {"effort": "low"}
    assert call["tool_choice"] == {"type": "auto"}
    tool = call["tools"][0]
    assert tool["name"] == cl.TOOL_NAME and tool["strict"] is True
    user = call["messages"][0]["content"]
    assert f"Largo máximo de la frase: {limit - 5} caracteres." in user
    assert f"La escena dura {duration} segundos." in user
    # the consumption ledger: the business, the brand, the feature and the prompt version
    (consumption,) = booked
    assert consumption.attribution.tenant_id == TENANT
    assert consumption.attribution.brand_id == BRAND
    assert consumption.attribution.feature == "sugerir-linea-personaje"
    assert consumption.attribution.prompt_version == "personaje-linea-v1"


def test_the_prompt_carries_the_servers_reads_and_never_a_price() -> None:
    factory = FakeFactory(fixture("ok_5s"))
    service, _, _ = _service(factory)
    _suggest(service)
    call = factory.messages.calls[0]
    user = call["messages"][0]["content"]
    for fact in (
        "Heladería La Nube",
        "Mango",
        "dibujo animado",
        "Un mango sonriente con gorra azul.",
        "Copa de mango",
        "Mango fresco con crema.",
        "barato",
        "el mejor helado del país",
    ):
        assert fact in user
    assert "Precio" not in user and "$" not in user
    system = call["system"][0]["text"]
    for rule in ("UNA sola frase", "primera persona", "Nunca digas un precio", "Sin emojis"):
        assert rule in system
    assert "como se pronuncia" in system


def test_the_answer_is_normalized_like_the_schema() -> None:
    service, _, _ = _service(FakeFactory(fixture("quoted_5s")))
    assert _suggest(service).line == "¡Esta copa de mango me encanta!"


# -- what fails, and that it counts --------------------------------------------------------


@pytest.mark.parametrize("name", ["too_long_5s", "refusal", "invented_5s", "digits_5s", "empty"])
def test_a_bad_answer_fails_counts_and_is_never_retried(name: str) -> None:
    factory = FakeFactory(fixture(name), fixture("ok_5s"))
    service, ledger, _ = _service(factory)
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service, duration=5)
    assert refused.value.code == cl.LINE_SUGGESTION_FAILED
    assert refused.value.owner_message == cl.REFUSAL_TEXT[cl.LINE_SUGGESTION_FAILED]
    assert len(factory.messages.calls) == 1  # asked once, never again
    (row,) = ledger.rows.values()  # it was paid: it stays and counts for the day
    assert row.cost_usd > 0 and row.cost_usd < cl.LINE_MAX_USD
    assert _suggest(service).left_today == 8


def test_a_line_that_fits_8_seconds_is_too_long_for_5() -> None:
    service, _, _ = _service(FakeFactory(fixture("ok_8s")))
    assert _suggest(service, duration=8).line
    service, _, _ = _service(FakeFactory(fixture("ok_8s")))
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service, duration=5)
    assert refused.value.code == cl.LINE_SUGGESTION_FAILED


@pytest.mark.parametrize(
    "error",
    [
        type("APIStatusError", (Exception,), {})("500 from the API"),
        type("BadRequestError", (Exception,), {})("400"),
    ],
)
def test_an_unbilled_error_gives_the_reservation_back(error: Exception) -> None:
    factory = FakeFactory(error)
    service, ledger, _ = _service(factory)
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service)
    assert refused.value.code == cl.LINE_SUGGESTION_UNAVAILABLE
    assert ledger.rows == {} and ledger.spent_usd == 0


def test_a_timeout_may_have_billed_so_the_bound_stays() -> None:
    connection = type("APIConnectionError", (Exception,), {})
    timeout = type("APITimeoutError", (connection,), {})("timed out")
    service, ledger, _ = _service(FakeFactory(timeout))
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service)
    assert refused.value.code == cl.LINE_SUGGESTION_UNAVAILABLE
    (row,) = ledger.rows.values()
    assert row.cost_usd == cl.LINE_MAX_USD  # an overcount, never an undercount


def test_no_key_refuses_before_any_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(claude_tools.API_KEY_ENV)
    factory = FakeFactory(fixture("ok_5s"))
    service, ledger, _ = _service(factory)
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service)
    assert refused.value.code == cl.LINE_SUGGESTION_UNAVAILABLE
    assert ledger.rows == {} and factory.messages.calls == []


def test_the_brand_dollar_cap_refuses_before_the_call() -> None:
    factory = FakeFactory(fixture("ok_5s"))
    service, ledger, _ = _service(
        factory, ledger=cl.MemoryLineLedger(remaining_usd=Decimal("0.005"))
    )
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service)
    assert refused.value.code == cl.LINE_BUDGET_CAP
    assert factory.messages.calls == [] and ledger.rows == {}


# -- the caps, the scene's key and the repeated tap -----------------------------------------


def test_the_eleventh_suggestion_of_a_scene_is_refused() -> None:
    factory = FakeFactory(*[fixture("ok_5s") for _ in range(11)])
    service, _, _ = _service(factory)
    left = [_suggest(service).left_today for _ in range(10)]
    assert left == [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service)
    assert refused.value.code == cl.LINE_DAILY_CAP
    assert "10 sugerencias para esta escena" in refused.value.owner_message
    assert len(factory.messages.calls) == 10  # the 11th never reached the model
    # another scene of the same business still has its own 10
    assert _suggest(service, scene=uuid4()).left_today == 9


def test_the_business_cap_stops_made_up_scene_keys() -> None:
    factory = FakeFactory(*[fixture("ok_5s") for _ in range(31)])
    service, _, _ = _service(factory)
    for _ in range(30):
        _suggest(service, scene=uuid4())
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service, scene=uuid4())
    assert refused.value.code == cl.LINE_BUSINESS_DAILY_CAP
    assert "30 sugerencias" in refused.value.owner_message
    assert len(factory.messages.calls) == 30


def test_left_today_is_the_lower_of_both_caps() -> None:
    factory = FakeFactory(*[fixture("ok_5s") for _ in range(30)])
    service, _, _ = _service(factory)
    for _ in range(28):
        _suggest(service, scene=uuid4())
    got = _suggest(service)  # its scene has 9 left, the business 1
    assert got.left_today == 1 and got.left_today_text == "Te queda 1 sugerencia hoy."
    assert _suggest(service).left_today_text == (
        "Ya no te quedan sugerencias hoy. Mañana tienes más."
    )


def test_the_same_scene_key_counts_across_edits() -> None:
    """The key is the scene's, not the line's: its count follows it while it is edited."""
    factory = FakeFactory(fixture("ok_5s"), fixture("ok_8s"))
    service, ledger, _ = _service(factory)
    _suggest(service, duration=5)
    assert _suggest(service, duration=8).left_today == 8
    assert {row.scene_key for row in ledger.rows.values()} == {SCENE}


def test_a_double_tap_calls_the_model_once() -> None:
    factory = FakeFactory(fixture("ok_5s"), fixture("ok_5s"))
    service, ledger, _ = _service(factory)
    _suggest(service, request="tap-1")
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service, request="tap-1")
    assert refused.value.code == cl.SUGGESTION_REPEATED
    assert len(factory.messages.calls) == 1 and len(ledger.rows) == 1


def test_the_row_id_is_one_per_business_scene_and_tap() -> None:
    one = cl.usage_event_id(TENANT, SCENE, "tap")
    assert one == cl.usage_event_id(TENANT, SCENE, "tap")
    assert one != cl.usage_event_id(uuid4(), SCENE, "tap")
    assert one != cl.usage_event_id(TENANT, uuid4(), "tap")
    assert one != cl.usage_event_id(TENANT, SCENE, "tap-2")


# -- refusals before anything is read or paid ------------------------------------------------


@pytest.mark.parametrize("env", [{}, {cs.SCENE_SWITCH: "off"}, {cs.SCENE_SWITCH: ""}])
def test_the_switch_off_refuses_before_reading_anything(env: dict[str, str]) -> None:
    factory = FakeFactory(fixture("ok_5s"))
    service, ledger, reads = _service(factory, env=env)
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service)
    assert refused.value.code == cs.SWITCHED_OFF
    assert reads.calls == [] and ledger.rows == {} and factory.keys == []


@pytest.mark.parametrize("duration", [4, 11, 0])
def test_a_scene_length_out_of_range_is_refused(duration: int) -> None:
    factory = FakeFactory(fixture("ok_5s"))
    service, ledger, reads = _service(factory)
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service, duration=duration)
    assert refused.value.code == "character_scene_duration"
    assert reads.calls == [] and ledger.rows == {}


def test_a_missing_character_or_product_is_refused_before_any_spend() -> None:
    factory = FakeFactory(fixture("ok_5s"))
    service, ledger, _ = _service(factory, reads=FakeReads(character=False))
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service)
    assert refused.value.code == cs.CHARACTER_MISSING
    service, ledger, _ = _service(factory, reads=FakeReads(product=False))
    with pytest.raises(cl.CharacterLineRefused) as refused:
        _suggest(service)
    assert refused.value.code == cl.PRODUCT_MISSING
    assert ledger.rows == {} and factory.messages.calls == []


def test_every_refusal_has_spanish_words() -> None:
    for code in (
        cs.SWITCHED_OFF,
        cs.CHARACTER_MISSING,
        "character_scene_duration",
        cl.PRODUCT_MISSING,
        cl.LINE_DAILY_CAP,
        cl.LINE_BUSINESS_DAILY_CAP,
        cl.LINE_SUGGESTION_FAILED,
        cl.LINE_SUGGESTION_UNAVAILABLE,
        cl.LINE_BUDGET_CAP,
        cl.SUGGESTION_REPEATED,
    ):
        text = cl.REFUSAL_TEXT[code]
        assert text.endswith(".") and "IA" not in text


# -- the scene: its key and the line's provenance -------------------------------------------


def _item(**changes: Any) -> CharacterSceneItem:
    base: dict[str, Any] = {
        "character_id": CHARACTER,
        "product": {"product_id": PRODUCT, "photo_key": f"uploads/{TENANT}/a.jpg"},
        "background": {"key": f"uploads/{TENANT}/b.jpg"},
        "line": "¡Esta copa de mango me encanta!",
        "start": 0,
        "duration": 5,
    }
    return CharacterSceneItem.model_validate({**base, **changes})


def test_the_scene_key_is_not_part_of_its_digest() -> None:
    assert _item().key is None
    assert cs.scene_digest(_item(key=uuid4())) == cs.scene_digest(_item(key=uuid4()))
    assert cs.scene_digest(_item(key=SCENE)) == cs.scene_digest(_item())


@pytest.mark.parametrize(
    ("suggested", "version", "ok"),
    [
        (False, None, True),
        (True, "personaje-linea-v1", True),
        (True, None, False),
        (True, "personaje-linea-v0", False),
        (False, "personaje-linea-v1", False),
    ],
)
def test_a_suggested_line_carries_a_known_prompt_version(
    suggested: bool, version: str | None, ok: bool
) -> None:
    scene = _item(line_suggested=suggested, line_prompt_version=version)
    problems = cs.scene_problems([scene], clip_seconds=20)
    codes = [p.code for p in problems]
    assert (cs.LINE_PROVENANCE not in codes) is ok
    if not ok:
        (problem,) = [p for p in problems if p.code == cs.LINE_PROVENANCE]
        assert problem.scene == 0 and "escena 1" in problem.text


def test_the_words_say_which_cap_binds() -> None:
    assert cl.left_today_text(3, scene=True) == "Te quedan 3 sugerencias para esta escena hoy."
    assert cl.left_today_text(1, scene=True) == "Te queda 1 sugerencia para esta escena hoy."
    assert cl.left_today_text(0, scene=True).endswith("Puedes pedirlas en otra escena.")
    assert cl.left_today_text(2) == "Te quedan 2 sugerencias hoy."


def test_a_released_tap_may_ask_again() -> None:
    error = type("BadRequestError", (Exception,), {})("400")
    factory = FakeFactory(error, fixture("ok_5s"))
    service, ledger, _ = _service(factory)
    with pytest.raises(cl.CharacterLineRefused):
        _suggest(service, request="tap-x")
    assert _suggest(service, request="tap-x").left_today == 9
    assert len(ledger.rows) == 1
