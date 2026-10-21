"""Which intent classes are reliable enough to show (m-24789644, B3). Fails closed: a
class is reliable only when the committed report for the current `detector_version`
(`data/reliability/<detector_version>.json`, written by `python -m qualify_api.intent.eval
--write-reliability`) says so. No report, or a class below the thresholds or with too
few golden examples, means «no fiable» — without blocking the other classes.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Final

from qualify_api.intent.contract import IntentClass

#: A class is reliable at or above both, with at least `MIN_SUPPORT` golden examples.
#: Starting values; PR 3b may move them with the measured numbers in hand.
MIN_PRECISION: Final = 0.80
MIN_RECALL: Final = 0.70
MIN_SUPPORT: Final = 8

RELIABILITY_DIR: Final = "reliability"


def class_reliability(detector_version: str) -> dict[IntentClass, bool]:
    report_file = (
        resources.files("qualify_api.intent")
        / "data"
        / RELIABILITY_DIR
        / f"{detector_version}.json"
    )
    reliable: dict[IntentClass, bool] = {c: False for c in IntentClass}
    if not report_file.is_file():
        return reliable
    per_class = json.loads(report_file.read_text(encoding="utf-8")).get("per_class", {})
    for name, entry in per_class.items():
        try:
            reliable[IntentClass(name)] = bool(entry.get("reliable"))
        except ValueError:
            continue
    return reliable
