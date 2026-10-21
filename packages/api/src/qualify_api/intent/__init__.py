"""Commercial intent of a tenant's own Instagram comments (m-24789644, Interacciones ·
Fase A): the published contract (`IntentSignal`) with its example fixture, its
persistence (`comment_intent_results`, migration 0069), the classifier behind a
`IntentClassifier` seam, the service that analyzes pending comments, and the golden-set
evaluation that decides which classes are reliable.

Callers outside this package use the composition seams (`analyze_pending_intents`,
`current_signals`, `class_reliability`), not the repository or the classifier."""

from qualify_api.intent.classifier import (
    ClaudeIntentClassifier,
    IntentClassifier,
    normalize_prediction,
)
from qualify_api.intent.composition import (
    CURRENT_INTENT_VERSION,
    IntentModelUnavailable,
    UnknownIntentConnection,
    analyze_pending_intents,
    current_signals,
)
from qualify_api.intent.contract import (
    COMMERCIAL_CLASSES,
    INTENT_CLASS_LABELS,
    IntentClass,
    IntentSignal,
)
from qualify_api.intent.fixtures import IntentFixture, load_fixture_signals
from qualify_api.intent.reliability import class_reliability
from qualify_api.intent.repository import (
    IntentRepository,
    MemoryIntentRepository,
    PostgresIntentRepository,
    signal_version,
)
from qualify_api.intent.service import IntentAnalysisSummary, IntentService

__all__ = [
    "COMMERCIAL_CLASSES",
    "CURRENT_INTENT_VERSION",
    "INTENT_CLASS_LABELS",
    "ClaudeIntentClassifier",
    "IntentAnalysisSummary",
    "IntentClass",
    "IntentClassifier",
    "IntentFixture",
    "IntentModelUnavailable",
    "IntentRepository",
    "IntentService",
    "IntentSignal",
    "MemoryIntentRepository",
    "PostgresIntentRepository",
    "UnknownIntentConnection",
    "analyze_pending_intents",
    "class_reliability",
    "current_signals",
    "load_fixture_signals",
    "normalize_prediction",
    "signal_version",
]
