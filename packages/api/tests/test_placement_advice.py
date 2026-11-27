"""EF-20 phase 2 (m-25026599): the warning that a video's text may cover the product, offline.

Every model call goes to a fake client factory and every database door to a double:
nothing here reaches Anthropic or Postgres."""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image

from qualify_api.creative import placement_advice as adv
from qualify_api.creative import placement_ai as pa

TENANT = UUID("7e7e0000-0000-4000-8000-000025026599")
BRAND = UUID("7e7e0000-0000-4000-8000-0000000b0001")
SOURCE = f"t/{TENANT}/uploads/{'a' * 32}_hamburguesa.mp4"
PREVIEW = f"t/{TENANT}/uploads/previews/{uuid4()}/video.mp4"
NOW = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
REVISION = "claude-haiku-5-5-test"


# --- doubles ---------------------------------------------------------------------------


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (720, 1280), (200, 80, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _frames(n: int = 3) -> list[pa.PlacementFrame]:
    return [
        pa.PlacementFrame(jpeg=_jpeg(), width=720, height=1280, at_s=float(i)) for i in range(n)
    ]


def _answer(**overrides: Any) -> dict[str, Any]:
    return {
        "subject": "Una hamburguesa",
        "subject_bands": ["middle", "bottom"],
        "text_place": "top",
        "logo_place": "top",
        "reason": "La hamburguesa ocupa el centro y abajo; el texto va arriba.",
        **overrides,
    }


@dataclass
class FakeClaude:
    answer: Callable[[], Any] = _answer
    error: Exception | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, api_key: str) -> SimpleNamespace:
        return SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            id=f"msg_{len(self.requests)}",
            model=REVISION,
            stop_reason="tool_use",
            content=[SimpleNamespace(type="tool_use", name=pa.TOOL_NAME, input=self.answer())],
            usage=SimpleNamespace(
                input_tokens=5_200,
                output_tokens=400,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


@dataclass
class MemoryLedger:
    """`PlacementLedger` in memory, with the same caps and ids as the Postgres one."""

    fleet_used: int = 0
    events: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    reserves: int = 0

    def reserve(
        self, *, tenant_id: UUID, brand_id: UUID, source_key: str, now: datetime, fleet_cap: int
    ) -> UUID:
        self.reserves += 1
        ids = [
            adv.usage_event_id(tenant_id, source_key, n)
            for n in range(1, pa.MAX_CALLS_PER_PIECE + 1)
        ]
        free = [i for i in ids if i not in self.events]
        if not free:
            raise pa.PlacementRefused("piece_cap")
        if self.fleet_used >= fleet_cap:
            raise pa.PlacementRefused("fleet_cap")
        self.fleet_used += 1
        self.events[free[0]] = {
            "cost_usd": pa.MAX_REQUEST_USD,
            "input_tokens": 0,
            "output_tokens": 0,
            "brand_id": brand_id,
            "at": now,
        }
        return free[0]

    def settle(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        event_id: UUID,
        cost_usd: Decimal,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self.events[event_id].update(
            cost_usd=cost_usd, input_tokens=input_tokens, output_tokens=output_tokens
        )


@dataclass
class MemoryStore:
    advice: dict[str, adv.PlacementAdvice] = field(default_factory=dict)
    keeps: list[UUID] = field(default_factory=list)
    accept: bool = True

    def kept(self, tenant_id: UUID, source_key: str) -> adv.PlacementAdvice | None:
        return self.advice.get(source_key)

    def keep(self, tenant_id: UUID, job_id: UUID, advice: adv.PlacementAdvice) -> bool:
        self.keeps.append(job_id)
        if not self.accept or advice.source_key in self.advice:
            return False
        self.advice[advice.source_key] = advice
        return True


def _fetch(fetched: list[str]) -> Callable[[UUID, str, Path], None]:
    def fetch(tenant_id: UUID, key: str, target: Path) -> None:
        assert tenant_id == TENANT
        fetched.append(key)
        target.write_bytes(b"480p")

    return fetch


def _advisor(
    fake: FakeClaude,
    ledger: MemoryLedger | None = None,
    store: MemoryStore | None = None,
    *,
    env: dict[str, str] | None = None,
    frames: Callable[[Path], list[pa.PlacementFrame]] | None = None,
) -> adv.PlacementAdvisor:
    return adv.PlacementAdvisor(
        ledger=ledger or MemoryLedger(),
        store=store or MemoryStore(),
        placer_factory=lambda guard: pa.VisionPlacer(
            guard=guard, api_key="test-key", client_factory=fake
        ),
        frames_of=frames or (lambda path: _frames() if path.read_bytes() == b"480p" else []),
        clock=lambda: NOW,
        env={pa.PLACEMENT_SWITCH: "on"} if env is None else env,
    )


def _advise(advisor: adv.PlacementAdvisor, fetched: list[str] | None = None) -> str:
    return advisor.advise(
        tenant_id=TENANT,
        brand_id=BRAND,
        job_id=uuid4(),
        source_key=SOURCE,
        preview_key=PREVIEW,
        fetch=_fetch(fetched if fetched is not None else []),
    )


# --- the warning, pure ------------------------------------------------------------------


def test_covers_product_is_the_band_being_one_the_product_occupies() -> None:
    assert adv.covers_product(("middle", "bottom"), "bottom")
    assert not adv.covers_product(("middle", "bottom"), "top")
    assert not adv.covers_product((), "bottom")


@pytest.mark.parametrize(
    ("bands", "text", "reason"),
    [
        (
            ("middle", "bottom"),
            "top",
            "Tu producto se ve en el medio y abajo. Pon el texto arriba para no taparlo.",
        ),
        (("top",), "bottom", "Tu producto se ve arriba. Pon el texto abajo para no taparlo."),
        (
            ("top", "middle", "bottom"),
            "bottom",
            "Tu producto ocupa casi todo el video. Pon el texto abajo, donde lo tapa menos.",
        ),
        (
            (),
            "bottom",
            "No vimos tu producto en el video: puedes poner el texto donde quieras.",
        ),
    ],
)
def test_the_reason_is_plain_spanish_built_from_the_bands(
    bands: tuple[str, ...], text: str, reason: str
) -> None:
    assert adv.reason_text(bands, text) == reason


def _advice(**overrides: Any) -> adv.PlacementAdvice:
    values: dict[str, Any] = {
        "source_key": SOURCE,
        "preview_key": PREVIEW,
        "subject": "Una hamburguesa",
        "subject_bands": ("middle", "bottom"),
        "recommended_text_band": "top",
        "recommended_logo_band": "bottom",
        "reason_es": "Tu producto se ve en el medio y abajo. Pon el texto arriba para no taparlo.",
        "model": pa.MODEL_ID,
        "model_revision": REVISION,
        "prompt_version": pa.PLACEMENT_PROMPT_VERSION,
        "prompt_fingerprint": pa.prompt_fingerprint(),
        "frames": ({"at_s": 1.0, "width": 720, "height": 1280, "sha256": "ab" * 8},),
        "cost_usd": Decimal("0.000812"),
        "pricing_table_version": "v10",
        "made_at": NOW,
    }
    values.update(overrides)
    return adv.PlacementAdvice(**values)


def test_the_warning_shows_only_when_the_chosen_band_covers_the_product() -> None:
    advice = _advice()
    assert advice.warning("bottom") == "Aquí el texto puede tapar tu producto. Arriba no lo tapa."
    assert advice.warning("middle") is not None
    assert advice.warning("top") is None  # the recommended band
    middle = _advice(subject_bands=("top",), recommended_text_band="middle")
    assert middle.warning("top") == (
        "Aquí el texto puede tapar tu producto. En el medio no lo tapa."
    )
    full = _advice(subject_bands=("top", "middle", "bottom"), recommended_text_band="bottom")
    assert full.warning("bottom") is None  # covers least: no warning on the recommendation
    assert full.warning("top") == "Aquí el texto puede tapar tu producto. Abajo lo tapa menos."


@pytest.mark.parametrize(
    ("band", "label"),
    [
        ("top", "Poner el texto arriba"),
        ("middle", "Poner el texto en el medio"),
        ("bottom", "Poner el texto abajo"),
    ],
)
def test_the_button_names_the_band(band: str, label: str) -> None:
    assert adv.use_band_text(band) == label
    assert _advice(recommended_text_band=band).to_params()["use_band_text"] == label


def test_the_contract_round_trips_and_refuses_a_broken_one() -> None:
    advice = _advice()
    params = advice.to_params()
    assert set(params) == {
        "version",
        "source_key",
        "preview_key",
        "subject",
        "subject_bands",
        "recommended_text_band",
        "recommended_logo_band",
        "reason_es",
        "use_band_text",
        "model",
        "model_revision",
        "prompt_version",
        "prompt_fingerprint",
        "frames",
        "cost_usd",
        "pricing_table_version",
        "made_at",
    }
    assert params["subject_bands"] == ["middle", "bottom"] and params["cost_usd"] == "0.000812"
    assert adv.PlacementAdvice.from_params(params) == advice
    assert adv.PlacementAdvice.from_params({**params, "recommended_text_band": "left"}) is None
    assert adv.PlacementAdvice.from_params({**params, "subject_bands": "middle"}) is None
    assert adv.PlacementAdvice.from_params({**params, "made_at": "ayer"}) is None
    assert adv.PlacementAdvice.from_params(None) is None


def test_a_piece_of_several_videos_takes_the_union_of_their_bands() -> None:
    one = _advice()
    assert adv.combine_advice([]) is None
    assert adv.combine_advice([one]) == adv.CombinedAdvice(
        ("middle", "bottom"), "top", "bottom", one.reason_es
    )
    other = _advice(subject_bands=("top",), recommended_text_band="bottom")
    both = adv.combine_advice([one, other])
    assert both is not None
    assert both.subject_bands == ("top", "middle", "bottom")
    assert both.covers_product("top") and both.covers_product("bottom")
    assert "ocupa casi todo" in both.reason_es


def test_the_usage_ids_are_deterministic_per_video_and_call() -> None:
    first = adv.usage_event_id(TENANT, SOURCE, 1)
    assert first == adv.usage_event_id(TENANT, SOURCE, 1)
    assert first != adv.usage_event_id(TENANT, SOURCE, 2)
    assert first != adv.usage_event_id(uuid4(), SOURCE, 1)  # another business, another id
    assert adv.source_piece_id(TENANT, SOURCE) == adv.source_piece_id(TENANT, SOURCE)


# --- the run ----------------------------------------------------------------------------


def test_a_video_gets_its_advice_once_with_its_provenance_and_cost() -> None:
    fake, ledger, store, fetched = FakeClaude(), MemoryLedger(), MemoryStore(), []
    assert _advise(_advisor(fake, ledger, store), fetched) == adv.OUTCOME_MADE
    assert fetched == [PREVIEW]  # the light copy, never the original
    assert len(fake.requests) == 1
    images = [b for b in fake.requests[0]["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 3  # variant `3f`
    advice = store.advice[SOURCE]
    assert advice.subject_bands == ("middle", "bottom")
    assert advice.recommended_text_band == "top"
    # the only free band: the logo shares it with the text rather than cover the product
    assert advice.recommended_logo_band == "top"
    assert advice.reason_es.startswith("Tu producto se ve en el medio y abajo.")
    assert advice.model == pa.MODEL_ID and advice.model_revision == REVISION
    assert advice.prompt_version == pa.PLACEMENT_PROMPT_VERSION
    assert len(advice.frames) == 3 and advice.made_at == NOW
    assert Decimal(0) < advice.cost_usd < pa.MAX_REQUEST_USD
    # the reservation was settled to what the call billed
    (event,) = ledger.events.values()
    assert event["cost_usd"] == advice.cost_usd
    assert event["input_tokens"] == 5_200 and event["output_tokens"] == 400
    # asked again: the kept advice answers, nothing is fetched nor called
    assert _advise(_advisor(fake, ledger, store), fetched) == adv.OUTCOME_KEPT
    assert len(fake.requests) == 1 and fetched == [PREVIEW] and ledger.reserves == 1


def test_off_by_default_nothing_is_read_nor_called() -> None:
    fake, ledger, fetched = FakeClaude(), MemoryLedger(), []
    assert _advise(_advisor(fake, ledger, env={}), fetched) == adv.OUTCOME_OFF
    assert fetched == [] and fake.requests == [] and ledger.reserves == 0


def test_a_fallback_answer_leaves_no_advice_but_records_what_was_billed() -> None:
    fake = FakeClaude(answer=lambda: _answer(text_place="izquierda"))
    ledger, store = MemoryLedger(), MemoryStore()
    assert _advise(_advisor(fake, ledger, store)) == f"{adv.OUTCOME_FALLBACK}:bad_answer"
    assert store.advice == {} and store.keeps == []
    (event,) = ledger.events.values()
    assert Decimal(0) < event["cost_usd"] < pa.MAX_REQUEST_USD  # billed, settled


def test_at_most_two_calls_per_video_then_no_advice() -> None:
    fake = FakeClaude(error=RuntimeError("connection reset"))
    ledger, store = MemoryLedger(), MemoryStore()
    for _ in range(2):
        assert _advise(_advisor(fake, ledger, store)) == f"{adv.OUTCOME_FALLBACK}:request_error"
    assert _advise(_advisor(fake, ledger, store)) == f"{adv.OUTCOME_FALLBACK}:guard_refused"
    assert len(fake.requests) == 2 and len(ledger.events) == 2
    # a request error may still have been billed: both reservations stay at the bound
    assert all(e["cost_usd"] == pa.MAX_REQUEST_USD for e in ledger.events.values())
    assert all(e["input_tokens"] == 0 for e in ledger.events.values())


def _decision(**overrides: Any) -> pa.PlacementDecision:
    values: dict[str, Any] = {
        "text_place": "bottom",
        "logo_place": "top",
        "reason": "x",
        "source": "fallback",
        "fallback_reason": pa.FALLBACK_BAD_ANSWER,
        "cost_usd": Decimal("0.0008"),
        "provenance": {"input_tokens": 5_200, "output_tokens": 400},
    }
    values.update(overrides)
    return pa.PlacementDecision(**values)


@pytest.mark.parametrize(
    ("decision", "settled"),
    [
        (_decision(), True),  # measured usage: settled to it
        (_decision(source="model", fallback_reason=None), True),
        (_decision(fallback_reason=pa.FALLBACK_REQUEST_ERROR), False),
        (_decision(cost_usd=Decimal(0), provenance={}), False),  # nothing measured
        (_decision(provenance={"input_tokens": 0, "output_tokens": 0}), False),
    ],
)
def test_the_settle_never_undercounts(decision: pa.PlacementDecision, settled: bool) -> None:
    ledger = MemoryLedger()
    guard = adv.SourceCallGuard(
        ledger=ledger, tenant_id=TENANT, brand_id=BRAND, source_key=SOURCE, fleet_cap=10
    )
    guard.charge(uuid4())
    assert guard.settle(decision) is settled
    (event,) = ledger.events.values()
    assert event["cost_usd"] == (decision.cost_usd if settled else pa.MAX_REQUEST_USD)


def test_the_production_client_waits_at_most_a_minute_and_retries_once() -> None:
    client = adv.bounded_client("test-key")  # builds the client: no request is made
    assert client.timeout == 60.0 and adv.CLIENT_TIMEOUT_S == 60.0
    assert client.max_retries == 1
    # and the media-worker's advisor builds its placer on it
    placer = adv.production_placement_advisor().placer_factory(pa.InMemoryCallGuard())
    assert placer._client_factory is adv.bounded_client


def test_the_fleet_cap_refuses_before_the_call() -> None:
    fake, ledger = FakeClaude(), MemoryLedger(fleet_used=7)
    advisor = _advisor(fake, ledger, env={pa.PLACEMENT_SWITCH: "on", pa.FLEET_DAILY_ENV: "7"})
    assert _advise(advisor) == f"{adv.OUTCOME_FALLBACK}:guard_refused"
    assert fake.requests == [] and ledger.events == {}


def test_a_video_without_frames_or_a_failed_read_is_no_advice() -> None:
    fake, ledger = FakeClaude(), MemoryLedger()
    assert _advise(_advisor(fake, ledger, frames=lambda _p: [])) == adv.OUTCOME_NO_FRAMES

    def broken(tenant_id: UUID, key: str, target: Path) -> None:
        raise OSError("R2 hiccup")

    code = _advisor(fake, ledger).advise(
        tenant_id=TENANT,
        brand_id=BRAND,
        job_id=uuid4(),
        source_key=SOURCE,
        preview_key=PREVIEW,
        fetch=broken,
    )
    assert code == f"{adv.OUTCOME_ERROR}:OSError"
    assert fake.requests == [] and ledger.reserves == 0


def test_an_advice_kept_meanwhile_is_never_overwritten() -> None:
    store = MemoryStore(accept=False)
    assert _advise(_advisor(FakeClaude(), store=store)) == adv.OUTCOME_NOT_KEPT


# --- the kept advice, read back ----------------------------------------------------------


def test_fold_keeps_the_newest_usable_advice_of_each_video() -> None:
    other = f"t/{TENANT}/uploads/{'b' * 32}_papas.mp4"
    by_job_key = {"upload_preview:v2:" + SOURCE: SOURCE, "upload_preview:v1:" + other: other}
    rows = [
        SimpleNamespace(idempotency_key="upload_preview:v2:" + SOURCE, result={}),
        SimpleNamespace(
            idempotency_key="upload_preview:v2:" + SOURCE,
            result={adv.ADVICE_FIELD: _advice().to_params()},
        ),
        # an advice made for another file is never handed out for this one
        SimpleNamespace(
            idempotency_key="upload_preview:v1:" + other,
            result={adv.ADVICE_FIELD: _advice().to_params()},
        ),
    ]
    folded = adv.fold_advice(by_job_key, rows)
    assert list(folded) == [SOURCE] and folded[SOURCE] == _advice()


def test_another_business_video_is_never_looked_up(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_db(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("no query for another business's key")

    monkeypatch.setattr("qualify_shared.db.session.tenant_session", no_db)
    foreign = f"t/{uuid4()}/uploads/{'c' * 32}_otro.mp4"
    assert adv.placement_advice_for(TENANT, [foreign]) == {}


# --- the Postgres ledger, against a recording session --------------------------------------


class RecordingSession:
    def __init__(self, taken: list[UUID], row: Any = None) -> None:
        self.taken = taken
        self.row = row
        self.config = SimpleNamespace(budget_spent_usd=Decimal("1.000000"))
        self.calls: list[str] = []

    def execute(self, statement: Any, params: Any = None) -> None:
        self.calls.append(f"execute:{statement}:{params}")

    def scalars(self, statement: Any) -> list[UUID]:
        self.calls.append("scalars")
        return list(self.taken)

    def scalar(self, statement: Any) -> Any:
        if statement.is_insert:
            from sqlalchemy.dialects import postgresql

            values = statement.compile(dialect=postgresql.dialect()).params
            self.calls.append(f"insert:{values['unit']}:{values['cost_usd']}")
            return values["id"]
        self.calls.append("config")
        return self.config

    def get(self, _model: Any, _id: Any, with_for_update: bool = False) -> Any:
        assert with_for_update
        return self.row


def _ledger(session: RecordingSession, used: int = 0) -> adv.PostgresPlacementLedger:
    from contextlib import contextmanager

    @contextmanager
    def factory(tenant_id: UUID) -> Any:
        assert tenant_id == TENANT
        yield session

    fleet = SimpleNamespace(calls_since=lambda since: session.calls.append("fleet") or used)
    return adv.PostgresPlacementLedger(fleet, session_factory=factory)  # type: ignore[arg-type]


def _reserve(ledger: adv.PostgresPlacementLedger, cap: int = 1500) -> UUID:
    return ledger.reserve(
        tenant_id=TENANT, brand_id=BRAND, source_key=SOURCE, now=NOW, fleet_cap=cap
    )


def test_the_reservation_locks_counts_and_books_the_bound() -> None:
    session = RecordingSession(taken=[])
    event_id = _reserve(_ledger(session))
    assert event_id == adv.usage_event_id(TENANT, SOURCE, 1)
    assert session.calls[0].startswith("execute:SELECT pg_advisory_xact_lock(:k)")
    assert str(adv.GUARD_LOCK_KEY) in session.calls[0]
    assert session.calls[1:] == [
        "scalars",
        "fleet",
        f"insert:{adv.PLACEMENT_USAGE_UNIT}:{pa.MAX_REQUEST_USD}",
    ]  # the platform pays: the brand's `creative_engine_config` is never read nor locked


def test_the_second_call_takes_the_second_id_and_a_third_is_refused() -> None:
    first = adv.usage_event_id(TENANT, SOURCE, 1)
    assert _reserve(_ledger(RecordingSession(taken=[first]))) == adv.usage_event_id(
        TENANT, SOURCE, 2
    )
    both = [first, adv.usage_event_id(TENANT, SOURCE, 2)]
    session = RecordingSession(taken=both)
    with pytest.raises(pa.PlacementRefused) as refused:
        _reserve(_ledger(session))
    assert refused.value.reason == "piece_cap" and "fleet" not in session.calls


def test_a_full_fleet_refuses_without_a_reservation() -> None:
    session = RecordingSession(taken=[])
    with pytest.raises(pa.PlacementRefused) as refused:
        _reserve(_ledger(session, used=1500))
    assert refused.value.reason == "fleet_cap"
    assert not any(c.startswith("insert") for c in session.calls)


def test_the_settle_sets_what_was_billed_and_is_idempotent() -> None:
    row = SimpleNamespace(cost_usd=pa.MAX_REQUEST_USD, input_tokens=0, output_tokens=0)
    session = RecordingSession(taken=[], row=row)
    ledger = _ledger(session)
    for _ in range(2):
        ledger.settle(
            tenant_id=TENANT,
            brand_id=BRAND,
            event_id=adv.usage_event_id(TENANT, SOURCE, 1),
            cost_usd=Decimal("0.000812"),
            input_tokens=5_200,
            output_tokens=400,
        )
    assert row.cost_usd == Decimal("0.000812") and row.input_tokens == 5_200
    assert row.output_tokens == 400
    assert "config" not in session.calls  # the brand's dollar cap is never touched


def test_the_window_is_the_last_24_hours() -> None:
    seen: list[datetime] = []
    session = RecordingSession(taken=[])
    ledger = adv.PostgresPlacementLedger(
        SimpleNamespace(calls_since=lambda since: seen.append(since) or 0),  # type: ignore[arg-type]
        session_factory=_ledger(session)._session_factory,
    )
    _reserve(ledger)
    assert seen == [NOW - timedelta(hours=24)]
