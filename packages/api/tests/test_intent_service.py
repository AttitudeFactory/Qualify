"""`IntentService` and the composition seams (m-24789644) over the memory repository and
a stub classifier: what gets classified, what gets stored, what stays pending."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest

from qualify_api.intent import (
    CURRENT_INTENT_VERSION,
    IntentClass,
    IntentModelUnavailable,
    IntentService,
    MemoryIntentRepository,
)
from qualify_api.intent.classifier import Prediction
from qualify_api.intent.composition import production_intent_service

TENANT = UUID("e0000000-0000-4000-8000-0000000000a4")
CONNECTION = uuid4()


class StubClassifier:
    """Answers from a text -> prediction table; unknown texts get no prediction."""

    model_id = CURRENT_INTENT_VERSION.model_id
    model_revision = None

    def __init__(self, answers: dict[str, Prediction]) -> None:
        self.answers = answers
        self.seen: list[list[str]] = []

    def classify(self, texts: Sequence[str]) -> list[Prediction]:
        self.seen.append(list(texts))
        return [self.answers.get(text, {}) for text in texts]


def _seed(repo: MemoryIntentRepository, text: str | None, **kwargs: object) -> UUID:
    message_id = uuid4()
    repo.seed_message(
        message_id=message_id,
        connection_id=CONNECTION,
        source_id=f"src-{message_id}",
        text=text,
        **kwargs,  # type: ignore[arg-type]
    )
    return message_id


def _service(repo: MemoryIntentRepository, classifier: StubClassifier) -> IntentService:
    return IntentService(repository=repo, version=CURRENT_INTENT_VERSION, classifier=classifier)


def test_pending_comments_are_classified_and_stored_with_provenance() -> None:
    repo = MemoryIntentRepository()
    price = _seed(repo, "¿precio?")
    general = _seed(repo, "¡lindo!")
    classifier = StubClassifier(
        {"¿precio?": {IntentClass.PRICE: 0.9}, "¡lindo!": {IntentClass.GENERAL: 0.95}}
    )

    summary = _service(repo, classifier).analyze_pending_intents(
        tenant_id=TENANT, connection_id=CONNECTION
    )

    assert (summary.comments_checked, summary.new_results) == (2, 2)
    signals = repo.get_signals(
        tenant_id=TENANT, message_ids=[price, general], version=CURRENT_INTENT_VERSION
    )
    assert signals[price].commercial_intent is True
    assert signals[general].commercial_intent is False
    assert signals[price].detector_version == CURRENT_INTENT_VERSION.detector_version
    assert signals[price].source_id == f"src-{price}"


def test_whitespace_only_comments_are_counted_and_never_sent() -> None:
    repo = MemoryIntentRepository()
    _seed(repo, "   \n")
    classifier = StubClassifier({})

    summary = _service(repo, classifier).analyze_pending_intents(
        tenant_id=TENANT, connection_id=CONNECTION
    )

    assert (summary.comments_checked, summary.skipped_empty, summary.new_results) == (1, 1, 0)
    assert classifier.seen == [[]]


def test_a_comment_without_a_usable_answer_stays_pending() -> None:
    repo = MemoryIntentRepository()
    message_id = _seed(repo, "algo raro")
    service = _service(repo, StubClassifier({}))

    summary = service.analyze_pending_intents(tenant_id=TENANT, connection_id=CONNECTION)

    assert summary.unclassified == 1 and summary.new_results == 0
    pending = repo.list_pending_for_intent(
        tenant_id=TENANT, connection_id=CONNECTION, version=CURRENT_INTENT_VERSION
    )
    assert [p.message_id for p in pending] == [message_id]


def test_a_second_pass_classifies_nothing_new() -> None:
    repo = MemoryIntentRepository()
    _seed(repo, "¿precio?")
    classifier = StubClassifier({"¿precio?": {IntentClass.PRICE: 0.9}})
    service = _service(repo, classifier)
    service.analyze_pending_intents(tenant_id=TENANT, connection_id=CONNECTION)

    summary = service.analyze_pending_intents(tenant_id=TENANT, connection_id=CONNECTION)

    assert summary.comments_checked == 0
    assert classifier.seen[-1] == []


def test_deleted_comments_are_never_analyzed() -> None:
    repo = MemoryIntentRepository()
    _seed(repo, "¿precio?", deleted=True)
    classifier = StubClassifier({"¿precio?": {IntentClass.PRICE: 0.9}})

    summary = _service(repo, classifier).analyze_pending_intents(
        tenant_id=TENANT, connection_id=CONNECTION
    )

    assert summary.comments_checked == 0


def test_the_version_must_name_the_classifiers_model() -> None:
    classifier = StubClassifier({})
    classifier.model_id = "another-model"  # type: ignore[misc]

    with pytest.raises(ValueError, match="another-model"):
        _service(MemoryIntentRepository(), classifier)


def test_a_classifier_returning_the_wrong_count_is_refused() -> None:
    class Short(StubClassifier):
        def classify(self, texts: Sequence[str]) -> list[Prediction]:
            return []

    repo = MemoryIntentRepository()
    _seed(repo, "¿precio?")

    with pytest.raises(RuntimeError, match="predictions"):
        _service(repo, Short({})).analyze_pending_intents(
            tenant_id=TENANT, connection_id=CONNECTION
        )


def test_production_service_refuses_without_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(IntentModelUnavailable):
        production_intent_service()


def test_production_service_uses_the_current_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", "test-key")

    service = production_intent_service()

    assert service._version == CURRENT_INTENT_VERSION  # noqa: SLF001
