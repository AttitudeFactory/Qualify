"""Commercial intent of a tenant's own Instagram comments (m-24789644, Interacciones ·
Fase A). For now only the published contract (`IntentSignal`) and its example fixture;
persistence and the classifier land in later PRs of the same ticket."""

from qualify_api.intent.contract import (
    COMMERCIAL_CLASSES,
    INTENT_CLASS_LABELS,
    IntentClass,
    IntentSignal,
)
from qualify_api.intent.fixtures import IntentFixture, load_fixture_signals

__all__ = [
    "COMMERCIAL_CLASSES",
    "INTENT_CLASS_LABELS",
    "IntentClass",
    "IntentFixture",
    "IntentSignal",
    "load_fixture_signals",
]
