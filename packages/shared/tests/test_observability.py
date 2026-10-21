"""`qualify_shared.observability`: offline, against an in-memory span exporter — the same
OpenTelemetry spans the SDK would send to the self-hosted Langfuse, never sent."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from qualify_shared import observability

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def spans() -> Iterator[Any]:
    with observability.capture_spans() as exporter:
        yield exporter


def _by_name(exporter: Any) -> dict[str, object]:
    observability.flush()
    return {span.name: span for span in exporter.get_finished_spans()}


def test_without_keys_nothing_is_traced_and_the_work_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(observability.PUBLIC_KEY_ENV, raising=False)
    monkeypatch.delenv(observability.SECRET_KEY_ENV, raising=False)
    observability.reset()
    with observability.trace("generar", session_id="d") as root:
        with observability.generation("copy", model="m") as call:
            call.finish(output="x", usage={"input": 1}, cost={"input": 0.1})
        root.finish(output="ok")
    assert observability.enabled() is False
    observability.flush()  # a no-op, not an error
    observability.reset()


def test_a_generation_nests_under_its_trace_with_usage_and_cost(
    spans: Any,
) -> None:
    with observability.trace(
        "generar static_flyer",
        session_id="draft-1",
        tags=("static_flyer", "feed_4_5"),
        metadata={"tenant_id": "t-1", "voice_version": None},
    ):
        with observability.generation("copy", model="claude-opus-5-5", input={"user": "hola"}) as o:
            o.finish(
                output={"hook": "Nuevo"},
                usage={"input": 1200, "output": 350},
                cost={"input": 0.0048, "output": 0.007},
            )
    found = _by_name(spans)
    root, call = found["generar static_flyer"], found["copy"]
    assert call.parent.span_id == root.context.span_id  # type: ignore[attr-defined]
    attrs = call.attributes  # type: ignore[attr-defined]
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.observation.model.name"] == "claude-opus-5-5"
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {"input": 1200, "output": 350}
    assert json.loads(attrs["langfuse.observation.cost_details"])["output"] == 0.007
    # the trace's session, tags and metadata reach the nested call
    assert attrs["session.id"] == "draft-1"
    assert tuple(attrs["langfuse.trace.tags"]) == ("static_flyer", "feed_4_5")
    assert attrs["langfuse.trace.metadata.tenant_id"] == "t-1"
    assert "langfuse.trace.metadata.voice_version" not in attrs  # None is not sent


def test_personal_data_secrets_and_bytes_are_masked_before_export(
    spans: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with observability.trace("t"):
        with observability.generation(
            "copy",
            input={
                "user": "Escríbeme a ana@marca.co o al +57 300 123 4567",
                "key": "sk-ant-api03-abcdefghijklmnop",
                "photo": b"\x89PNG....",
                "ref": "data:image/jpeg;base64,/9j/4AAQ",
            },
        ) as o:
            o.finish(output="ok")
    sent = json.loads(_by_name(spans)["copy"].attributes["langfuse.observation.input"])  # type: ignore[attr-defined]
    assert sent["user"] == "Escríbeme a <email> o al <phone>"
    assert sent["key"] == "<secret>"
    assert sent["photo"] == "<8 bytes>"
    assert sent["ref"].startswith("<data url")
    # masked BEFORE the SDK sees it: no attempt to upload the data URL as Langfuse media
    assert not [r for r in caplog.records if "Media upload" in r.getMessage()]


def test_the_callers_error_propagates_and_marks_the_observation(
    spans: Any,
) -> None:
    with pytest.raises(ValueError, match="vendor down"):
        with observability.trace("t"):
            with observability.generation("imagen"):
                raise ValueError("vendor down")
    found = _by_name(spans)
    attrs = found["imagen"].attributes  # type: ignore[attr-defined]
    assert attrs["langfuse.observation.level"] == "ERROR"
    assert "vendor down" in attrs["langfuse.observation.status_message"]
    assert found["t"].attributes["langfuse.observation.level"] == "ERROR"  # type: ignore[attr-defined]


class _BrokenClient:
    """An SDK that fails on every call: the traced work must not notice."""

    def start_as_current_observation(self, **_: object) -> object:
        raise RuntimeError("langfuse exploded")

    def flush(self) -> None:
        raise RuntimeError("langfuse exploded")


def test_a_failing_sdk_never_breaks_the_traced_work() -> None:
    observability.configure(_BrokenClient())
    try:
        with observability.trace("t") as root:
            with observability.generation("copy") as call:
                call.finish(output="x", usage={"input": 1})
                result = 42
            root.finish(output=result)
        observability.flush()
        assert result == 42
    finally:
        observability.reset()


def test_only_the_observability_module_imports_langfuse() -> None:
    """One door to the SDK (rule 3 of the module): a vendor or major-version swap is a
    change to one file."""
    allowed = REPO / "packages" / "shared" / "src" / "qualify_shared" / "observability.py"
    roots = [*sorted((REPO / "packages").glob("*/src")), REPO / "Qualify"]
    offenders = [
        str(path.relative_to(REPO))
        for root in roots
        for path in root.rglob("*.py")
        if path != allowed
        and any(
            line.strip().startswith(("import langfuse", "from langfuse"))
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    ]
    assert offenders == []


# -- datasets and experiments (plan §6-§7), against a fake client ----------------------


class _FakeDataset:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.kwargs: dict[str, Any] = {}

    def run_experiment(self, **kwargs: Any) -> Any:
        from types import SimpleNamespace

        self.kwargs = kwargs
        results = []
        for item in self.items:
            output = kwargs["task"](item=item)
            evaluations = [
                e
                for evaluator in kwargs["evaluators"]
                for e in evaluator(
                    input=item.input, output=output, expected_output=None, metadata={}
                )
            ]
            results.append(SimpleNamespace(item=item, output=output, evaluations=evaluations))
        run_evaluations = [
            e for evaluator in kwargs["run_evaluators"] for e in evaluator(item_results=results)
        ]
        return SimpleNamespace(
            run_name=kwargs["run_name"],
            item_results=results,
            run_evaluations=run_evaluations,
            dataset_run_url="http://localhost:3100/run",
        )


class _FakeClient:
    def __init__(self, dataset: _FakeDataset | None = None) -> None:
        self.dataset = dataset
        self.created: list[dict[str, Any]] = []
        self.items: list[dict[str, Any]] = []

    def get_dataset(self, name: str) -> _FakeDataset:
        if self.dataset is None:
            raise RuntimeError("not found")
        return self.dataset

    def create_dataset(self, **kwargs: Any) -> None:
        self.created.append(kwargs)

    def create_dataset_item(self, **kwargs: Any) -> None:
        self.items.append(kwargs)

    def flush(self) -> None:
        pass


def test_an_experiment_needs_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(observability.PUBLIC_KEY_ENV, raising=False)
    observability.reset()
    with pytest.raises(observability.TracingNotConfigured):
        observability.sync_dataset("d", [])
    observability.reset()


def test_a_dataset_is_created_once_and_its_items_upserted_masked() -> None:
    client = _FakeClient()
    observability.configure(client)
    try:
        written = observability.sync_dataset(
            "copy-briefs",
            [
                {
                    "id": "a",
                    "input": {"topic": "escríbenos a ana@x.co"},
                    "metadata": {"k": 1},
                }
            ],
            description="briefs",
        )
    finally:
        observability.reset()
    assert written == 1
    assert client.created == [{"name": "copy-briefs", "description": "briefs"}]
    (item,) = client.items
    assert item["id"] == "copy-briefs:a" and item["dataset_name"] == "copy-briefs"
    assert item["input"] == {"topic": "escríbenos a <email>"}


def test_a_case_removed_locally_is_archived_and_no_longer_run() -> None:
    """The voice dataset kept running a sample deleted from cases.json (2026-10-14): Langfuse
    cannot free an id, so the removed item is archived and runs skip it."""
    from types import SimpleNamespace

    from langfuse.api import DatasetStatus

    kept = SimpleNamespace(id="d:kept", input={"n": 1}, status=DatasetStatus.ACTIVE)
    gone = SimpleNamespace(
        id="d:gone", input={"n": 5}, expected_output=None, metadata=None, status="ACTIVE"
    )
    client = _FakeClient(_FakeDataset([kept, gone]))
    observability.configure(client)
    try:
        observability.sync_dataset("d", [{"id": "kept", "input": {"n": 1}}])
        statuses = {i["id"]: i["status"] for i in client.items}
        assert statuses == {"d:kept": DatasetStatus.ACTIVE, "d:gone": DatasetStatus.ARCHIVED}
        gone.status = DatasetStatus.ARCHIVED
        summary = observability.run_experiment(
            "d", name="exp", run_name="r", task=lambda case: case["n"]
        )
    finally:
        observability.reset()
    assert [o.output for o in summary.outcomes] == [1]


def test_an_experiment_scores_items_and_the_run_and_summarises_them() -> None:
    from types import SimpleNamespace

    dataset = _FakeDataset([SimpleNamespace(input={"n": 1}), SimpleNamespace(input={"n": 3})])
    observability.configure(_FakeClient(dataset))

    def doubled(output: Any) -> list[observability.Score]:
        return [observability.Score("ok", output > 2), observability.Score("valor", float(output))]

    def run_total(outcomes: Any) -> list[observability.Score]:
        return [observability.Score("total", sum(o.scores["valor"] for o in outcomes))]

    try:
        summary = observability.run_experiment(
            "d",
            name="exp",
            run_name="config · 1",
            task=lambda case: case["n"] * 2,
            evaluators=[lambda case, output, expected, meta: doubled(output)],
            run_evaluators=[run_total],
            metadata={"variants": 2},
        )
    finally:
        observability.reset()

    assert dataset.kwargs["metadata"] == {"variants": "2"}
    assert summary.items == 2 and summary.run_name == "config · 1"
    assert summary.means == {"ok": 0.5, "valor": 4.0}
    assert summary.run_scores == {"total": 8.0}
    assert summary.url == "http://localhost:3100/run"
    assert [o.output for o in summary.outcomes] == [2, 6]


def test_a_trace_seed_fixes_the_trace_id() -> None:
    """Approving a draft later scores the trace found again from its seed (plan §8)."""
    with observability.capture_spans() as exporter:
        with observability.trace("generar static_flyer", trace_seed="draft-1:2"):
            pass
        expected = observability.trace_id_for("draft-1:2")
        observability.flush()
        (root,) = exporter.get_finished_spans()
    assert expected is not None and format(root.context.trace_id, "032x") == expected
    assert observability.trace_id_for("draft-1:2") is None  # tracing off again


def test_a_file_is_attached_only_when_wrapped_on_purpose() -> None:
    """`media` opts a file in (the eval's fictional brands); raw bytes stay masked."""
    assert observability.media(b"\xff\xd8\xff", "image/jpeg") is None  # tracing off
    with observability.capture_spans():
        attached = observability.media(b"\xff\xd8\xff", "image/jpeg")
        assert type(attached).__name__ == "LangfuseMedia"
        assert observability._mask(data={"imagen": attached})["imagen"] is attached
        assert observability._mask(data={"imagen": b"\xff\xd8\xff"})["imagen"] == "<3 bytes>"


def test_the_current_trace_id_is_the_open_spans() -> None:
    assert observability.current_trace_id() is None
    with observability.capture_spans() as exporter:
        with observability.trace("t"):
            inside = observability.current_trace_id()
        observability.flush()
        (root,) = exporter.get_finished_spans()
    assert inside == format(root.context.trace_id, "032x")
