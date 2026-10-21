"""`MemoryIntentRepository` (m-24789644): the invariants the Postgres implementation
must also hold — pending selection, idempotency per version, reading signals back. The
same behaviors against real Postgres live in `test_intent_repository_db.py`."""

from __future__ import annotations

from uuid import UUID, uuid4

from qualify_api.intent import IntentSignal, MemoryIntentRepository, signal_version
from qualify_api.sentiment.repository import AnalysisVersion

TENANT = UUID("e0000000-0000-4000-8000-0000000000a1")
CONNECTION = uuid4()
VERSION = AnalysisVersion(
    detector_version="intent-test-v1",
    pipeline_version="p1",
    model_id="test-model",
    model_revision=None,
)


def _signal(message_id: UUID, version: AnalysisVersion = VERSION) -> IntentSignal:
    return IntentSignal(
        comment_id=message_id,
        source_id=f"src-{message_id}",
        classes={"price": 0.9, "availability": 0.7},
        detector_version=version.detector_version,
        pipeline_version=version.pipeline_version,
        model_id=version.model_id,
        model_revision=version.model_revision,
    )


def _repo_with_message(**overrides: object) -> tuple[MemoryIntentRepository, UUID]:
    repo = MemoryIntentRepository()
    message_id = uuid4()
    fields: dict[str, object] = {
        "message_id": message_id,
        "connection_id": CONNECTION,
        "source_id": f"src-{message_id}",
        "text": "¿cuánto cuesta?",
    }
    fields.update(overrides)
    repo.seed_message(**fields)  # type: ignore[arg-type]
    return repo, message_id


def _pending_ids(repo: MemoryIntentRepository, version: AnalysisVersion = VERSION) -> set[UUID]:
    pending = repo.list_pending_for_intent(
        tenant_id=TENANT, connection_id=CONNECTION, version=version
    )
    return {p.message_id for p in pending}


def test_an_unanalyzed_comment_is_pending() -> None:
    repo, message_id = _repo_with_message()

    assert _pending_ids(repo) == {message_id}


def test_comments_without_text_deleted_or_of_another_connection_are_not_pending() -> None:
    repo = MemoryIntentRepository()
    repo.seed_message(message_id=uuid4(), connection_id=CONNECTION, source_id="a", text=None)
    repo.seed_message(
        message_id=uuid4(), connection_id=CONNECTION, source_id="b", text="hola", deleted=True
    )
    repo.seed_message(message_id=uuid4(), connection_id=uuid4(), source_id="c", text="hola")

    assert _pending_ids(repo) == set()


def test_a_recorded_comment_is_no_longer_pending_and_can_be_read_back() -> None:
    repo, message_id = _repo_with_message()
    signal = _signal(message_id)

    assert repo.record_intent_result(tenant_id=TENANT, connection_id=CONNECTION, signal=signal)
    assert _pending_ids(repo) == set()
    assert repo.get_signals(tenant_id=TENANT, message_ids=[message_id], version=VERSION) == {
        message_id: signal
    }


def test_recording_the_same_version_twice_is_a_no_op() -> None:
    repo, message_id = _repo_with_message()
    repo.record_intent_result(
        tenant_id=TENANT, connection_id=CONNECTION, signal=_signal(message_id)
    )

    assert not repo.record_intent_result(
        tenant_id=TENANT, connection_id=CONNECTION, signal=_signal(message_id)
    )


def test_a_new_version_is_pending_again_and_the_old_signal_survives() -> None:
    repo, message_id = _repo_with_message()
    repo.record_intent_result(
        tenant_id=TENANT, connection_id=CONNECTION, signal=_signal(message_id)
    )
    v2 = AnalysisVersion(
        detector_version="intent-test-v2",
        pipeline_version="p1",
        model_id="test-model",
        model_revision="rev-2",
    )

    assert _pending_ids(repo, v2) == {message_id}
    assert repo.record_intent_result(
        tenant_id=TENANT, connection_id=CONNECTION, signal=_signal(message_id, v2)
    )
    assert message_id in repo.get_signals(
        tenant_id=TENANT, message_ids=[message_id], version=VERSION
    )


def test_get_signals_omits_unanalyzed_comments() -> None:
    repo, message_id = _repo_with_message()

    assert repo.get_signals(tenant_id=TENANT, message_ids=[message_id], version=VERSION) == {}


def test_signal_version_carries_the_four_provenance_fields() -> None:
    signal = _signal(uuid4(), AnalysisVersion("d", "p", "m", "r"))

    assert signal_version(signal) == AnalysisVersion("d", "p", "m", "r")
