"""Commercial intent of a tenant's own Instagram comments (m-24789644, Interacciones ·
Fase A): the published contract (`IntentSignal`) with its example fixture, and its
persistence (`comment_intent_results`, migration 0069). The classifier lands in a later
PR of the same ticket."""

from qualify_api.intent.contract import (
    COMMERCIAL_CLASSES,
    INTENT_CLASS_LABELS,
    IntentClass,
    IntentSignal,
)
from qualify_api.intent.fixtures import IntentFixture, load_fixture_signals
from qualify_api.intent.repository import (
    IntentRepository,
    MemoryIntentRepository,
    PostgresIntentRepository,
    signal_version,
)

__all__ = [
    "COMMERCIAL_CLASSES",
    "INTENT_CLASS_LABELS",
    "IntentClass",
    "IntentFixture",
    "IntentRepository",
    "IntentSignal",
    "MemoryIntentRepository",
    "PostgresIntentRepository",
    "load_fixture_signals",
    "signal_version",
]
