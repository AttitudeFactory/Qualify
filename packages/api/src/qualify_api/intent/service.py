"""The intent service (m-24789644): classifies the pending comments of one connection
and persists one `IntentSignal` each, versioned. Same posture as `sentiment.service`:
one pass when asked, synchronous, no scheduler — who triggers it is the composition/UI
layer's decision.

A comment the classifier gave no usable answer for is NOT recorded: it stays pending and
is retried on the next pass, instead of being stored as a class nobody assigned.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_api.intent.classifier import IntentClassifier
from qualify_api.intent.contract import IntentSignal
from qualify_api.intent.repository import IntentRepository
from qualify_api.sentiment.repository import AnalysisVersion


@dataclass(frozen=True)
class IntentAnalysisSummary:
    comments_checked: int
    new_results: int
    # Whitespace-only comments: counted, never sent to the model.
    skipped_empty: int
    # The model answered nothing usable for these; they stay pending.
    unclassified: int


class IntentService:
    def __init__(
        self,
        *,
        repository: IntentRepository,
        version: AnalysisVersion,
        classifier: IntentClassifier,
    ) -> None:
        if version.model_id != classifier.model_id:
            raise ValueError(
                f"version model {version.model_id!r} is not the classifier's "
                f"{classifier.model_id!r}: rows would lie about what produced them"
            )
        self._repository = repository
        self._version = version
        self._classifier = classifier

    def analyze_pending_intents(
        self, *, tenant_id: UUID, connection_id: UUID
    ) -> IntentAnalysisSummary:
        pending = self._repository.list_pending_for_intent(
            tenant_id=tenant_id, connection_id=connection_id, version=self._version
        )
        to_classify = [comment for comment in pending if comment.text.strip()]
        predictions = self._classifier.classify([comment.text for comment in to_classify])
        if len(predictions) != len(to_classify):
            raise RuntimeError(
                f"classifier returned {len(predictions)} predictions for "
                f"{len(to_classify)} comments"
            )

        new_results = 0
        unclassified = 0
        for comment, classes in zip(to_classify, predictions, strict=True):
            if not classes:
                unclassified += 1
                continue
            signal = IntentSignal(
                comment_id=comment.message_id,
                source_id=comment.source_id,
                classes=classes,
                detector_version=self._version.detector_version,
                pipeline_version=self._version.pipeline_version,
                model_id=self._version.model_id,
                model_revision=self._version.model_revision,
            )
            if self._repository.record_intent_result(
                tenant_id=tenant_id, connection_id=connection_id, signal=signal
            ):
                new_results += 1
        return IntentAnalysisSummary(
            comments_checked=len(pending),
            new_results=new_results,
            skipped_empty=len(pending) - len(to_classify),
            unclassified=unclassified,
        )
