"""The synthetic comments fixture is a valid instance of the QUA-67 contract.

Lives WITH the contract (R11a), together with the fixture itself. Two reasons, and the
second is the binding one:

1. R11's positive invariant — a test that can fail because of a change OUTSIDE its own
   package belongs in the default gate. This is exactly such a test: it exists to break
   when the contract moves. Hosted in the uncollected `packages/models/tests` it ran only
   when somebody was already suspicious, which is executable documentation, not a gate.
2. **Dependency direction.** `qualify_models` depends on `qualify_shared`; `qualify_shared`
   must not know `qualify_models` exists. Moving only the tests and leaving the fixture
   behind would force `shared` to reach into `models` — the same number of hops, in the
   forbidden direction. So the fixture moves too, and the sentiment tests that consume it
   stay in `packages/models/tests`, reaching UP to the contract package. The consumer
   reaches the contract; never the reverse.

It also matches QUA-67's own criterion that the fixture is regenerated FROM the contract:
its source is the contract's package.

Fully offline: reads one JSON file, no weights and no network.
"""

from __future__ import annotations

import json
from pathlib import Path

from qualify_shared.social.ig_shapes import SHAPE_VERSION, parse_comments_page

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_ig_comments.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_synthetic_fixture_validates_against_the_contract() -> None:
    """The fixture's shape is no longer invented — it is an instance of the type."""
    payload = _payload()
    page = parse_comments_page(payload)
    assert len(page.data) == len(payload["data"])


def test_synthetic_fixture_is_still_marked_synthetic() -> None:
    """Grounding the shape must NOT be mistaken for having real data.

    Substituting real captured payloads is QUA-21's criterion and is blocked on
    QUA-20. This marker is what forces that substitution to be a conscious act.
    """
    assert _payload()["_fixture_kind"] == "SYNTHETIC"


def test_synthetic_fixture_records_the_shape_version_it_was_built_from() -> None:
    """Ties the fixture to a contract version, so a shape bump surfaces here."""
    assert _payload()["_shape_version"] == SHAPE_VERSION
