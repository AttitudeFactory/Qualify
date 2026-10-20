"""Example `IntentSignal`s shipped with the package, so a consumer (QUA-229) can wire
the contract into its own tests and dev screens before the classifier exists.

Hand-written, not model output: every signal carries `detector_version="fixture"`, so
it can never pass for a real analysis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources

from qualify_api.intent.contract import IntentSignal

FIXTURE_RESOURCE = "intent_signals.json"


@dataclass(frozen=True)
class IntentFixture:
    """One example comment with the signal it should produce."""

    text: str
    signal: IntentSignal


def load_fixture_signals() -> tuple[IntentFixture, ...]:
    raw = (resources.files("qualify_api.intent") / "data" / FIXTURE_RESOURCE).read_text(
        encoding="utf-8"
    )
    return tuple(
        IntentFixture(text=item["text"], signal=IntentSignal.model_validate(item["signal"]))
        for item in json.loads(raw)["items"]
    )
