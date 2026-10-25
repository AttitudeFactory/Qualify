"""m-24852495: the recovery pass (m-24852492) asks OmniHuman, by id, about a presenter's
pending render — a read that never submits — and the pass resumes the draft once the
render ended. Offline: the adapter and the key are fakes."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.adapters.byteplus_omnihuman import OmniHumanError

from qualify_api.creative import vendor_recovery as rec
from qualify_api.creative.vendor_recovery import ENDED, STILL_RUNNING, UNKNOWN, PendingTask

from .test_creative_vendor_recovery import TENANT_A, _Adapter, _Credentials

TASK = PendingTask("omnihuman-1", "oh-1", "omnihuman")


@pytest.mark.parametrize(
    ("vendor", "ours"),
    [
        ("in_queue", "queued"),
        ("generating", "running"),
        ("done", "succeeded"),
        ("expired", "expired"),
        ("canceled", "cancelled"),
        ("not_found", UNKNOWN),
    ],
)
def test_omnihuman_states_read_in_the_passs_words(vendor: str, ours: str) -> None:
    adapter, credentials = _Adapter({"status": vendor}), _Credentials()
    reader = rec.OmniHumanTaskStatus(adapter, credentials)
    assert reader.status(TASK, tenant_id=TENANT_A, brand_id=uuid4()) == ours
    assert adapter.asked == [("oh-1", "ark-key")] and credentials.providers == ["omnihuman"]
    # the pass acts only on an ended (or unknown) render, and waits on the rest
    assert ours in ENDED | STILL_RUNNING | {UNKNOWN}


def test_a_refused_render_reads_failed_and_an_answer_about_nothing_raises() -> None:
    refused = rec.OmniHumanTaskStatus(
        _Adapter(OmniHumanError("post-filter", code=50511, task_id="oh-1")), _Credentials()
    )
    assert refused.status(TASK, tenant_id=TENANT_A, brand_id=uuid4()) == "failed"

    for unknown in (
        OmniHumanError("HTTP 503", code=None, task_id="oh-1"),  # down
        OmniHumanError("access denied", code=50400, task_id="oh-1"),  # a key problem
    ):
        reader = rec.OmniHumanTaskStatus(_Adapter(unknown), _Credentials())
        with pytest.raises(OmniHumanError):
            reader.status(TASK, tenant_id=TENANT_A, brand_id=uuid4())


class _Fixed:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def status(self, task: PendingTask, **_: Any) -> str:
        self.asked.append(task.vendor_task_id)
        return self.answer


def test_each_task_is_asked_of_its_own_vendor() -> None:
    seedance, omnihuman = _Fixed("running"), _Fixed("succeeded")
    reader = rec.StatusByProvider(seedance, omnihuman)
    brand = uuid4()
    assert reader.status(TASK, tenant_id=TENANT_A, brand_id=brand) == "succeeded"
    seed = PendingTask("seedance-1", "cgt-1", "seedance")
    assert reader.status(seed, tenant_id=TENANT_A, brand_id=brand) == "running"
    assert omnihuman.asked == ["oh-1"] and seedance.asked == ["cgt-1"]


def test_the_production_parts_ask_omnihuman_for_a_presenter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUALIFY_OMNIHUMAN_REQ_KEY", "realman_avatar_picture_omni20_cv")
    parts = rec._production_parts()
    statuses = parts["statuses"]
    assert isinstance(statuses, rec.StatusByProvider)
    assert isinstance(statuses._omnihuman, rec.OmniHumanTaskStatus)
    # the same OmniHuman version the generation submits with
    assert statuses._omnihuman._adapter.req_key == "realman_avatar_picture_omni20_cv"
