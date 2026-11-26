"""Business characters (m-25129385), offline: the switch, the prompt and its price, the
round of 3 options (one job each), the caps (5 saved, 2 rounds a day, one open round),
choosing, renaming, deleting (refused while a video not approved uses it), isolation, and
the paid worker step against a Seedream double — zero paid calls."""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.adapters.byteplus_ark import (
    ArkAPIError,
    SeedreamDisconnected,
    VendorBusy,
)

from qualify_api.creative import business_characters as bc
from qualify_api.creative import job_queue as q
from qualify_api.creative.business_character_ai import (
    USAGE_UNIT,
    Budget,
    BusinessCharacterExecutor,
    PriceGuardRefused,
    SubmissionAborted,
    SwitchedOff,
    task_id_of,
    usage_event_id,
)
from qualify_api.creative.worker.executor import SUCCEEDED, JobContext

TENANT = UUID("c0000000-0000-4000-8000-000025129385")
OTHER = UUID("c0000000-0000-4000-8000-000025129386")
BRAND = UUID("b0000000-0000-4000-8000-000025129385")
USER = UUID("a0000000-0000-4000-8000-000025129385")
NOW = datetime(2026, 11, 26, 15, 0, tzinfo=UTC)
ON = {bc.CHARACTER_SCENE_SWITCH_ENV: "on", bc.ARK_KEY_ENV: "test-key"}
DESCRIPTION = "Una cocinera alegre con gorra roja y delantal verde"
#: A tiny valid JPEG header is enough: the bytes are stored, never decoded for the size.
JPEG = b"\xff\xd8\xff\xe0" + b"seedream-bytes" * 10


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Objects:
    """`ObjectGate`'s business-character methods, in memory (keys checked like the gate)."""

    def __init__(self, fail_puts: int = 0) -> None:
        from qualify_shared.objects.gate import ObjectGate
        from qualify_shared.objects.memory import MemoryObjectStore

        self.store = MemoryObjectStore()
        self.gate = ObjectGate(self.store)
        self.fail_puts = fail_puts
        self.deleted: list[str] = []

    def put_business_character(self, *args: Any) -> str:
        if self.fail_puts > 0:
            self.fail_puts -= 1
            raise OSError("r2 down")
        return self.gate.put_business_character(*args)

    def open_business_character(self, *args: Any) -> Any:
        return self.gate.open_business_character(*args)

    def delete_business_characters(
        self, tenant_id: UUID, brand_id: UUID, object_keys: list[str]
    ) -> None:
        self.deleted.extend(object_keys)
        self.gate.delete_business_characters(tenant_id, brand_id, object_keys)


class Ledger:
    def __init__(self) -> None:
        self.events: dict[UUID, dict[str, Any]] = {}

    def record(self, **kw: Any) -> bool:
        event = usage_event_id(kw["character_id"])
        if event in self.events:
            return False
        self.events[event] = kw
        return True

    @property
    def spent(self) -> Decimal:
        return sum((e["cost_usd"] for e in self.events.values()), Decimal("0"))


class FakeSeedream:
    def __init__(self, error: Exception | None = None, images: int = 1) -> None:
        self.error = error
        self.images = images
        self.calls: list[Any] = []

    def generate(self, request: Any, *, api_key: str) -> Any:
        self.calls.append((request, api_key))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            payload={"images": [JPEG] * self.images, "sizes": ["1080x1920"]},
            usage=SimpleNamespace(pieces=self.images),
            model_revision="dola-seedream-5-0-pro-260628",
            model_id=bc.MODEL_ID,
        )


def _service(
    *, env: dict[str, str] | None = None, clock: Clock | None = None
) -> tuple[bc.BusinessCharacterService, bc.MemoryCharacterRepository, Objects, Any]:
    clock = clock or Clock()
    repo = bc.MemoryCharacterRepository(clock=clock)
    usage = bc.MemoryCharacterUsage()
    objects = Objects()
    service = bc.BusinessCharacterService(
        repo=repo,
        usage=usage,
        objects=objects,
        palette=lambda _t, _b: ("#305046", "da2220", "not-a-color"),
        clock=clock,
        env=ON if env is None else env,
    )
    return service, repo, objects, usage


def _job(option_id: UUID, tenant: UUID = TENANT, kind: str = q.KIND_BUSINESS_CHARACTER) -> Any:
    return JobContext(
        job_id=uuid4(),
        tenant_id=tenant,
        draft_id=None,
        kind=kind,
        revision=1,
        position=0,
        vendor_model=q.SEEDREAM_PRO_POOL,
        lane="now",
        vendor_priority=0,
        deadline=None,
        business_character_id=option_id,
    )


class Reads:
    def __init__(self, repo: bc.MemoryCharacterRepository, budget: Budget | None = None) -> None:
        self.repo = repo
        self.budget_value = budget

    def character(self, tenant_id: UUID, character_id: UUID) -> Any:
        return self.repo.get(tenant_id=tenant_id, character_id=character_id)

    def budget(self, tenant_id: UUID, brand_id: UUID) -> Budget | None:
        return self.budget_value


def _executor(
    *,
    adapter: FakeSeedream | None = None,
    budget: Budget | None = None,
    fail_puts: int = 0,
    env: dict[str, str] | None = None,
) -> tuple[BusinessCharacterExecutor, bc.BusinessCharacterService, Any, Ledger, Any, Any]:
    service, repo, objects, _usage = _service()
    objects.fail_puts = fail_puts
    ledger = Ledger()
    adapter = adapter or FakeSeedream()
    executor = BusinessCharacterExecutor(
        adapter=adapter,
        reads=Reads(repo, budget),
        requests=repo,
        marks=service,
        objects=objects,
        ledger=ledger,
        api_key=lambda _t, _b: "platform-key",
        clock=Clock(),
        sleep=lambda _s: None,
        env=ON if env is None else env,
    )
    return executor, service, repo, ledger, objects, adapter


def _round(service: bc.BusinessCharacterService, key: str = "k1") -> bc.DrawingRound:
    return service.request_drawings(
        TENANT, BRAND, USER, description=DESCRIPTION, style="animado", request_key=key
    )


def _draw_all(executor: BusinessCharacterExecutor, round_: bc.DrawingRound) -> None:
    for option in round_.options:
        task = executor.submit(_job(option.id))
        executor.finish(_job(option.id), task, SUCCEEDED)


# --- the switch ---------------------------------------------------------------------------


def test_the_switch_name_is_the_one_scene_switch_and_it_is_off_by_default() -> None:
    assert bc.CHARACTER_SCENE_SWITCH_ENV == "QUALIFY_CLIP_CHARACTER_SCENE"
    assert bc.characters_unavailable_reason({}) == bc.SWITCHED_OFF
    assert bc.characters_unavailable_reason({bc.CHARACTER_SCENE_SWITCH_ENV: "on"}) == (
        bc.SWITCHED_OFF  # no ModelArk key
    )
    assert bc.characters_unavailable_reason(ON) is None


def test_the_env_examples_keep_the_switch_off() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for name in (".env.example", "deploy/.env.prod.example"):
        lines = (root / name).read_text(encoding="utf-8").splitlines()
        assert "QUALIFY_CLIP_CHARACTER_SCENE=off" in lines, name


def test_switched_off_every_public_method_refuses_before_reading() -> None:
    service, repo, *_ = _service(env={})
    calls = [
        lambda: service.list_characters(TENANT, BRAND),
        lambda: _round(service),
        lambda: service.drawing_round(TENANT, BRAND, uuid4()),
        lambda: service.choose_option(TENANT, BRAND, uuid4(), uuid4(), name="Nina"),
        lambda: service.discard_round(TENANT, BRAND, uuid4()),
        lambda: service.rename_character(TENANT, BRAND, uuid4(), name="Nina"),
        lambda: service.delete_character(TENANT, BRAND, uuid4()),
        lambda: service.character_reference(TENANT, BRAND, uuid4()),
    ]
    for call in calls:
        with pytest.raises(bc.CharacterRefused) as refused:
            call()
        assert refused.value.code == bc.SWITCHED_OFF
        assert refused.value.text == "Los personajes todavía no están disponibles."
    assert repo.rows == {}


# --- prompt and price ---------------------------------------------------------------------


def test_the_prompt_carries_style_description_palette_and_the_measured_frame() -> None:
    prompt = bc.build_character_prompt(
        'Una cocinera "alegre"\n con gorra', "realista", ["#305046", "DA2220", "x", "#305046"]
    )
    assert prompt.startswith("Photorealistic photo of an original, fictional person")
    assert "The character: \"Una cocinera 'alegre' con gorra\"." in prompt
    assert "brand colors #305046, #da2220." in prompt
    assert "hands empty and visible" in prompt and "No text, no logos" in prompt
    assert len(prompt) < 3000
    with pytest.raises(bc.CharacterRefused) as refused:
        bc.build_character_prompt(DESCRIPTION, "acuarela")
    assert refused.value.code == bc.STYLE_UNKNOWN


def test_three_options_at_the_v10_price_of_one_1k_seedream_image() -> None:
    table = bc.pricing_table()
    assert table.version == "v10"
    assert bc.option_quote_usd(table) == Decimal("0.045")
    assert bc.round_quote_usd(table) == Decimal("0.135")
    assert bc.OPTIONS_PER_ROUND == 3


# --- a round ------------------------------------------------------------------------------


def test_a_description_opens_one_round_of_three_options_with_one_job_each() -> None:
    service, repo, *_ = _service()
    round_ = _round(service)
    assert round_.status == bc.ROUND_DRAWING and len(round_.options) == 3
    assert [o.option_index for o in round_.options] == [1, 2, 3]
    assert {o.round_id for o in round_.options} == {round_.round_id}
    assert sorted(repo.jobs) == sorted(o.id for o in round_.options)
    first = round_.options[0]
    assert first.style == "animado" and first.source == bc.SOURCE_DRAWN
    assert first.prompt_version == "business-character-v1"
    assert first.pricing_table_version == "v10" and first.quoted_usd == Decimal("0.045")
    assert first.model_id == "dola-seedream-5-0-pro-260628"
    assert "#305046" in first.prompt and DESCRIPTION in first.prompt


def test_the_same_request_key_returns_the_same_round() -> None:
    service, repo, *_ = _service()
    first = _round(service, "same")
    again = _round(service, "same")
    assert again.round_id == first.round_id and len(repo.rows) == 3


@pytest.mark.parametrize(
    ("description", "code", "text"),
    [
        ("corta", bc.DESCRIPTION_SHORT, "Cuéntanos un poco más cómo es tu personaje."),
        ("x" * 301, bc.DESCRIPTION_LONG, "La descripción es muy larga. Usa menos de 300 letras."),
    ],
)
def test_the_description_is_checked(description: str, code: str, text: str) -> None:
    service, repo, *_ = _service()
    with pytest.raises(bc.CharacterRefused) as refused:
        service.request_drawings(
            TENANT, BRAND, USER, description=description, style="animado", request_key="k"
        )
    assert (refused.value.code, refused.value.text) == (code, text)
    assert repo.rows == {}


def test_an_unknown_style_is_refused() -> None:
    service, *_ = _service()
    with pytest.raises(bc.CharacterRefused) as refused:
        service.request_drawings(
            TENANT, BRAND, USER, description=DESCRIPTION, style="acuarela", request_key="k"
        )
    assert refused.value.code == bc.STYLE_UNKNOWN


def test_one_open_round_at_a_time() -> None:
    service, *_ = _service()
    _round(service, "a")
    with pytest.raises(bc.CharacterRefused) as refused:
        _round(service, "b")
    assert refused.value.code == bc.ROUND_OPEN
    assert refused.value.text == (
        "Elige una de las opciones que ya dibujamos, o descártalas, antes de pedir otras."
    )


def test_two_rounds_a_day_and_the_third_is_refused() -> None:
    service, *_ = _service()
    for key in ("a", "b"):
        service.discard_round(TENANT, BRAND, _round(service, key).round_id)
    view = service.list_characters(TENANT, BRAND)
    assert view.rounds_left_today == 0
    with pytest.raises(bc.CharacterRefused) as refused:
        _round(service, "c")
    assert refused.value.code == bc.DAILY_CAP
    assert refused.value.text == (
        "Hoy ya pediste 2 dibujos de personajes. Mañana puedes pedir más."
    )


def test_a_round_that_failed_without_paying_does_not_count_for_the_day() -> None:
    executor, service, repo, ledger, *_ = _executor(adapter=FakeSeedream(error=RuntimeError("x")))
    round_ = _round(service, "a")
    for option in round_.options:
        with pytest.raises(RuntimeError):
            executor.submit(_job(option.id))
    assert service.drawing_round(TENANT, BRAND, round_.round_id).status == bc.ROUND_FAILED
    assert ledger.spent == 0
    assert repo.rounds_today(tenant_id=TENANT, brand_id=BRAND) == 0
    assert service.list_characters(TENANT, BRAND).rounds_left_today == 2


def test_the_day_turns_and_rounds_come_back() -> None:
    clock = Clock()
    service, *_ = _service(clock=clock)
    for key in ("a", "b"):
        service.discard_round(TENANT, BRAND, _round(service, key).round_id)
    clock.now = NOW + timedelta(days=1)
    assert service.list_characters(TENANT, BRAND).rounds_left_today == 2


def test_a_round_left_unchosen_for_a_week_is_discarded_and_its_images_deleted() -> None:
    executor, service, repo, _ledger, objects, _ = _executor()
    round_ = _round(service)
    _draw_all(executor, round_)
    clock = Clock(NOW + bc.ROUND_TTL + timedelta(hours=1))
    service._clock = clock  # type: ignore[attr-defined]
    repo.clock = clock
    view = service.list_characters(TENANT, BRAND)
    assert view.open_round is None
    assert {r.status for r in repo.rows.values()} == {bc.STATUS_DISCARDED}
    assert len(objects.deleted) == 3


# --- choosing, renaming, deleting ---------------------------------------------------------


def test_choosing_saves_one_and_discards_the_others_with_their_images() -> None:
    executor, service, repo, _ledger, objects, _ = _executor()
    round_ = _round(service)
    _draw_all(executor, round_)
    assert service.drawing_round(TENANT, BRAND, round_.round_id).status == bc.ROUND_READY
    chosen = round_.options[1]
    saved = service.choose_option(TENANT, BRAND, round_.round_id, chosen.id, name="  Nina  ")
    assert saved.status == bc.STATUS_SAVED and saved.name == "Nina" and saved.saved_at
    others = [repo.rows[o.id] for o in round_.options if o.id != chosen.id]
    assert {o.status for o in others} == {bc.STATUS_DISCARDED}
    assert sorted(objects.deleted) == sorted(o.object_key for o in others)
    assert service.drawing_round(TENANT, BRAND, round_.round_id).status == bc.ROUND_CLOSED
    view = service.list_characters(TENANT, BRAND)
    assert [c.id for c in view.saved] == [chosen.id] and view.slots_left == 4
    assert view.open_round is None
    again = service.choose_option(TENANT, BRAND, round_.round_id, chosen.id, name="Nina")
    assert again.id == chosen.id  # idempotent


def test_an_option_still_drawing_cannot_be_chosen() -> None:
    service, *_ = _service()
    round_ = _round(service)
    with pytest.raises(bc.CharacterRefused) as refused:
        service.choose_option(TENANT, BRAND, round_.round_id, round_.options[0].id, name="Nina")
    assert refused.value.code == bc.NOT_READY


def _saved(
    executor: BusinessCharacterExecutor, service: bc.BusinessCharacterService, n: int
) -> list[bc.BusinessCharacter]:
    out = []
    for i in range(n):
        round_ = _round(service, f"r{i}")
        _draw_all(executor, round_)
        out.append(
            service.choose_option(
                TENANT, BRAND, round_.round_id, round_.options[0].id, name=f"Personaje {i}"
            )
        )
    return out


def test_the_sixth_character_of_a_business_is_refused() -> None:
    executor, service, repo, *_ = _executor()
    service.daily_rounds = 10  # the daily cap is tested on its own
    _saved(executor, service, 5)
    with pytest.raises(bc.CharacterRefused) as refused:
        _round(service, "sixth")
    assert refused.value.code == bc.LIMIT_REACHED
    assert refused.value.text == "Ya tienes 5 personajes guardados. Borra uno para crear otro."


def test_choosing_a_sixth_is_refused_even_from_a_round_opened_before() -> None:
    executor, service, *_ = _executor()
    service.daily_rounds = 10
    _saved(executor, service, 4)
    late = _round(service, "late")
    _draw_all(executor, late)
    service.max_saved = 4  # e.g. a fifth saved from another device meanwhile
    with pytest.raises(bc.CharacterRefused) as refused:
        service.choose_option(TENANT, BRAND, late.round_id, late.options[0].id, name="Otro")
    assert refused.value.code == bc.LIMIT_REACHED


def test_names_are_unique_per_business_and_bounded() -> None:
    executor, service, *_ = _executor()
    service.daily_rounds = 10
    first, second = _saved(executor, service, 2)
    with pytest.raises(bc.CharacterRefused) as refused:
        service.rename_character(TENANT, BRAND, second.id, name="personaje 0")
    assert refused.value.code == bc.NAME_TAKEN
    assert refused.value.text == "Ya tienes un personaje con ese nombre. Elige otro."
    for bad in ("", "   ", "x" * 41):
        with pytest.raises(bc.CharacterRefused) as refused:
            service.rename_character(TENANT, BRAND, second.id, name=bad)
        assert refused.value.code == bc.NAME_INVALID
    renamed = service.rename_character(TENANT, BRAND, second.id, name="Don Pepe")
    assert renamed.name == "Don Pepe" and first.name == "Personaje 0"


def test_deleting_marks_the_row_and_deletes_the_image() -> None:
    executor, service, repo, _ledger, objects, _ = _executor()
    (character,) = _saved(executor, service, 1)
    objects.deleted.clear()
    service.delete_character(TENANT, BRAND, character.id)
    stored = repo.rows[character.id]
    assert stored.status == bc.STATUS_DELETED and stored.deleted_at is not None
    assert objects.deleted == [character.object_key]
    assert service.list_characters(TENANT, BRAND).saved == ()
    service.delete_character(TENANT, BRAND, character.id)  # idempotent
    with pytest.raises(bc.CharacterRefused) as refused:
        service.character_reference(TENANT, BRAND, character.id)
    assert refused.value.code == bc.NOT_FOUND


def test_a_character_in_a_video_not_approved_yet_cannot_be_deleted() -> None:
    executor, service, repo, _ledger, objects, _ = _executor()
    (character,) = _saved(executor, service, 1)
    service._usage.in_use.add(character.id)  # type: ignore[attr-defined]
    objects.deleted.clear()
    with pytest.raises(bc.CharacterRefused) as refused:
        service.delete_character(TENANT, BRAND, character.id)
    assert refused.value.code == bc.IN_USE
    assert refused.value.text == (
        "Este personaje está en un video que aún no apruebas. "
        "Quítalo de ese video para poder borrarlo."
    )
    assert repo.rows[character.id].status == bc.STATUS_SAVED and objects.deleted == []


def test_the_scene_gets_the_saved_image_and_its_provenance() -> None:
    executor, service, *_ = _executor()
    (character,) = _saved(executor, service, 1)
    ref = service.character_reference(TENANT, BRAND, character.id)
    assert ref.object_key == (f"seasonal/{TENANT}/{BRAND}/personajes-negocio/{character.id}.jpg")
    assert ref.content_type == "image/jpeg" and ref.drawn_at == NOW
    assert ref.model_id == bc.MODEL_ID and ref.prompt_version == bc.PROMPT_VERSION
    assert ref.source == "drawn" and ref.name == "Personaje 0"


def test_another_business_never_sees_nor_touches_a_character() -> None:
    executor, service, *_ = _executor()
    (character,) = _saved(executor, service, 1)
    assert service.list_characters(OTHER, BRAND).saved == ()
    for call in (
        lambda: service.character_reference(OTHER, BRAND, character.id),
        lambda: service.rename_character(OTHER, BRAND, character.id, name="Mía"),
        lambda: service.delete_character(OTHER, BRAND, character.id),
        lambda: service.character_reference(TENANT, uuid4(), character.id),
    ):
        with pytest.raises(bc.CharacterRefused) as refused:
            call()
        assert refused.value.code == bc.NOT_FOUND


# --- the paid worker step -----------------------------------------------------------------


def test_one_option_is_one_seedream_call_booked_once_and_kept_byte_for_byte() -> None:
    executor, service, repo, ledger, objects, adapter = _executor()
    option = _round(service).options[0]
    task = executor.submit(_job(option.id))
    assert task == task_id_of(option.id)
    ((request, key),) = adapter.calls
    assert key == "platform-key"
    assert request.params == {
        "model": "dola-seedream-5-0-pro-260628",
        "prompt": option.prompt,
        "size": "1080x1920",
    }
    stored = repo.rows[option.id]
    assert stored.status == bc.STATUS_READY and stored.cost_usd == Decimal("0.045")
    assert stored.object_key and objects.store.open(stored.object_key).read() == JPEG
    assert stored.byte_size == len(JPEG) and stored.sha256 and stored.drawn_at == NOW
    assert stored.vendor_request_id == task
    (event,) = ledger.events.values()
    assert event["cost_usd"] == Decimal("0.045") and event["pricing_version"] == "v10"
    assert event["model_id"] == bc.MODEL_ID and USAGE_UNIT == "business_character_image"
    executor.finish(_job(option.id), task, SUCCEEDED)  # idempotent: already ready
    assert len(ledger.events) == 1 and len(adapter.calls) == 1


def test_the_price_guard_refuses_over_the_hard_cap_before_any_call() -> None:
    executor, service, repo, ledger, _o, adapter = _executor(
        budget=Budget(remaining_usd=Decimal("0.04"), hard_stop=True)
    )
    option = _round(service).options[0]
    with pytest.raises(PriceGuardRefused):
        executor.submit(_job(option.id))
    assert adapter.calls == [] and ledger.events == {}
    assert repo.rows[option.id].fail_reason == bc.REASON_BUDGET_CAP
    assert repo.rows[option.id].failure_text == (
        "Ahora no pudimos dibujarlo. No se te cobró. Escríbenos y lo revisamos contigo."
    )


def test_a_soft_cap_never_refuses() -> None:
    executor, service, repo, *_ = _executor(
        budget=Budget(remaining_usd=Decimal("0"), hard_stop=False)
    )
    option = _round(service).options[0]
    executor.submit(_job(option.id))
    assert repo.rows[option.id].status == bc.STATUS_READY


def test_switched_off_the_worker_fails_the_option_without_calling() -> None:
    executor, service, repo, ledger, _o, adapter = _executor()
    option = _round(service).options[0]
    executor._env = {}  # type: ignore[attr-defined]
    with pytest.raises(SwitchedOff):
        executor.submit(_job(option.id))
    assert adapter.calls == [] and ledger.events == {}
    assert repo.rows[option.id].status == bc.STATUS_FAILED


def test_busy_clears_the_stamp_and_is_retried_later() -> None:
    executor, service, repo, ledger, *_ = _executor(
        adapter=FakeSeedream(error=VendorBusy(429, "QuotaExceeded", "busy", 5.0))
    )
    option = _round(service).options[0]
    with pytest.raises(VendorBusy):
        executor.submit(_job(option.id))
    stored = repo.rows[option.id]
    assert stored.status == bc.STATUS_PENDING and stored.vendor_request_started_at is None
    assert ledger.events == {}


def test_moderation_fails_the_option_unbilled_with_its_own_words() -> None:
    executor, service, repo, ledger, *_ = _executor(
        adapter=FakeSeedream(error=ArkAPIError(200, "OutputImageSensitiveContentDetected", "x"))
    )
    option = _round(service).options[0]
    with pytest.raises(ArkAPIError):
        executor.submit(_job(option.id))
    stored = repo.rows[option.id]
    assert stored.fail_reason == bc.REASON_MODERATED and ledger.events == {}
    assert stored.failure_text == (
        "No pudimos dibujar ese personaje. Cambia un poco la descripción y vuelve a intentarlo."
    )


def test_a_dropped_connection_books_the_quote_and_fails_the_option() -> None:
    executor, service, repo, ledger, *_ = _executor(
        adapter=FakeSeedream(error=SeedreamDisconnected("ReadTimeout"))
    )
    option = _round(service).options[0]
    with pytest.raises(SeedreamDisconnected):
        executor.submit(_job(option.id))
    assert repo.rows[option.id].status == bc.STATUS_FAILED
    assert ledger.spent == Decimal("0.045")
    # paid (maybe): the round counts for the day
    assert repo.rounds_today(tenant_id=TENANT, brand_id=BRAND) == 1


def test_a_second_claim_never_posts_again() -> None:
    executor, service, repo, ledger, _o, adapter = _executor()
    option = _round(service).options[0]
    repo.start_request(tenant_id=TENANT, character_id=option.id, at=NOW)  # a dead claim
    with pytest.raises(SubmissionAborted):
        executor.submit(_job(option.id))
    assert adapter.calls == [] and ledger.spent == Decimal("0.045")
    assert repo.rows[option.id].fail_reason == bc.REASON_UNCERTAIN


def test_a_second_claim_after_the_image_was_kept_finishes_it() -> None:
    executor, service, repo, _ledger, objects, adapter = _executor()
    option = _round(service).options[0]
    repo.start_request(tenant_id=TENANT, character_id=option.id, at=NOW)
    objects.gate.put_business_character(TENANT, BRAND, option.id, io.BytesIO(JPEG), "image/jpeg")
    task = executor.submit(_job(option.id))
    executor.finish(_job(option.id), task, SUCCEEDED)
    assert adapter.calls == [] and repo.rows[option.id].status == bc.STATUS_READY


def test_an_r2_write_is_retried_and_a_lost_result_keeps_the_cost() -> None:
    executor, service, repo, *_ = _executor(fail_puts=2)
    option = _round(service).options[0]
    executor.submit(_job(option.id))
    assert repo.rows[option.id].status == bc.STATUS_READY  # third attempt wrote it

    executor, service, repo, ledger, *_ = _executor(fail_puts=3)
    option = _round(service).options[0]
    with pytest.raises(OSError):
        executor.submit(_job(option.id))
    assert repo.rows[option.id].fail_reason == bc.REASON_LOST_RESULT
    assert ledger.spent == Decimal("0.045")


def test_a_failed_redraw_never_touches_a_saved_character() -> None:
    executor, service, repo, _ledger, objects, _ = _executor()
    (character,) = _saved(executor, service, 1)
    executor._adapter = FakeSeedream(error=RuntimeError("down"))  # type: ignore[attr-defined]
    round_ = _round(service, "again")
    with pytest.raises(RuntimeError):
        executor.submit(_job(round_.options[0].id))
    assert repo.rows[character.id] == replace(character)
    assert objects.store.open(character.object_key or "").read() == JPEG


def test_give_up_fails_a_pending_option_and_other_kinds_are_not_run() -> None:
    executor, service, repo, *_ = _executor()
    option = _round(service).options[0]
    executor.give_up(_job(option.id))
    assert repo.rows[option.id].status == bc.STATUS_FAILED
    with pytest.raises(ValueError):
        executor.submit(_job(option.id, kind=q.KIND_STICKER_CHARACTER))
    executor.finish(_job(option.id, tenant=OTHER), "t", SUCCEEDED)  # RLS: nothing found
    assert repo.rows[option.id].status == bc.STATUS_FAILED


def test_the_worker_routes_the_kind_on_the_seedream_pool() -> None:
    import inspect

    from qualify_api.creative.worker import __main__ as worker_main

    source = inspect.getsource(worker_main.production_executors)
    assert "q.KIND_BUSINESS_CHARACTER: production_business_character_executor" in source
    assert q.KIND_BUSINESS_CHARACTER == "business_character"
