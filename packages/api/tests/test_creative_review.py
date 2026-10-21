"""The human judgement as Langfuse scores (docs/plan-observabilidad-langfuse.md §8),
offline: a fake Langfuse client records what would be sent."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_shared import observability

from qualify_api.creative import review
from qualify_api.creative.fsm import APPROVED

from .test_content_service import (
    TENANT_ID,
    USER_ID,
    FakeRouter,
    _generated_draft_with_variant,
    copy_dict,
    make_kit,
    make_service,
    make_voice,
    ok_outcome,
)


class FakeLangfuse:
    """Records scores, score configs, queues and queue items. Its trace ids are the seed,
    readable in assertions."""

    def __init__(self, queues: list[Any] | None = None, configs: list[Any] | None = None):
        self.scores: list[dict[str, Any]] = []
        self.items: list[tuple[str, dict[str, Any]]] = []
        self.created_configs: list[dict[str, Any]] = []
        self.created_queues: list[dict[str, Any]] = []
        self._queues = list(queues or [])
        self._configs = list(configs or [])
        fake = self

        class ScoreConfigs:
            def get(self, **_: Any) -> Any:
                return SimpleNamespace(data=fake._configs)

            def create(self, **kwargs: Any) -> Any:
                fake.created_configs.append(kwargs)
                made = SimpleNamespace(id=f"cfg-{kwargs['name']}", name=kwargs["name"])
                fake._configs.append(made)
                return made

        class Queues:
            def list_queues(self, **_: Any) -> Any:
                return SimpleNamespace(data=fake._queues)

            def create_queue(self, **kwargs: Any) -> Any:
                fake.created_queues.append(kwargs)
                made = SimpleNamespace(id="queue-1", name=kwargs["name"])
                fake._queues.append(made)
                return made

            def create_queue_item(self, queue_id: str, **kwargs: Any) -> None:
                fake.items.append((queue_id, kwargs))

        self.api = SimpleNamespace(score_configs=ScoreConfigs(), annotation_queues=Queues())

    def create_trace_id(self, *, seed: str) -> str:
        return f"trace:{seed}"

    def create_score(self, **kwargs: Any) -> None:
        self.scores.append(kwargs)

    def flush(self) -> None:
        pass


@pytest.fixture
def langfuse() -> Iterator[FakeLangfuse]:
    fake = FakeLangfuse(queues=[SimpleNamespace(id="queue-1", name=review.REVIEW_QUEUE)])
    observability.configure(fake)
    yield fake
    observability.reset()
    observability._queue_ids.clear()


def _by_name(scores: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {score["name"]: score for score in scores}


def test_the_edit_distance_is_zero_untouched_and_grows_with_the_rewrite() -> None:
    original = copy_dict()
    assert review.edit_distance(original, None) == 0.0
    assert review.edit_distance(original, original) == 0.0
    small = review.edit_distance(original, copy_dict(hook="Hook editado a mano"))
    rewrite = review.edit_distance(
        original, copy_dict(hook="Otra cosa", caption="Un texto completamente distinto.")
    )
    assert 0 < small < rewrite <= 1


def test_approving_scores_the_generations_trace(langfuse: FakeLangfuse) -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id, variant_id = _generated_draft_with_variant(service, repo)
    edited = copy_dict(hook="Editado a mano")
    from qualify_creative.schemas import CopyPayload

    service.edit_variant(
        tenant_id=TENANT_ID,
        variant_id=variant_id,
        copy=CopyPayload.model_validate(edited),
        user_id=USER_ID,
    )
    detail = service.approve(
        tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID
    )

    assert detail.status == APPROVED
    scores = _by_name(langfuse.scores)
    revision = repo.drafts[draft_id].revision
    assert {s["trace_id"] for s in langfuse.scores} == {f"trace:{draft_id}:{revision}"}
    assert scores["aprobado"]["value"] == 1.0 and scores["aprobado"]["data_type"] == "BOOLEAN"
    assert 0 < scores["edicion"]["value"] < 1 and scores["edicion"]["data_type"] == "NUMERIC"
    assert scores["variante_elegida"]["value"] == 0.0


def test_rejecting_scores_the_rejected_generation_before_it_is_regenerated(
    langfuse: FakeLangfuse,
) -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id, _ = _generated_draft_with_variant(service, repo)
    revision = repo.drafts[draft_id].revision

    service.reject(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        reason="no suena a la marca",
        user_id=USER_ID,
        regenerate=True,
    )

    (score,) = langfuse.scores
    assert score["name"] == "aprobado" and score["value"] == 0.0
    assert score["comment"] == "no suena a la marca"
    # the trace of the generation that was rejected, not of the regeneration to come
    assert score["trace_id"] == f"trace:{draft_id}:{revision}"
    assert repo.drafts[draft_id].revision == revision + 1


def test_media_from_a_model_under_test_is_queued_for_review(langfuse: FakeLangfuse) -> None:
    draft_id = uuid4()
    review.queue_media_for_review(draft_id=draft_id, revision=2, providers={"seedream"})
    review.queue_media_for_review(draft_id=draft_id, revision=3, providers={"heygen", "remotion"})
    review.queue_media_for_review(draft_id=draft_id, revision=4, providers=set())
    assert langfuse.items == [
        ("queue-1", {"object_id": f"trace:{draft_id}:2", "object_type": "TRACE"})
    ]


def test_without_tracing_nothing_is_scored_or_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(observability.PUBLIC_KEY_ENV, raising=False)
    observability.reset()
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id, variant_id = _generated_draft_with_variant(service, repo)
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    review.queue_media_for_review(draft_id=draft_id, revision=1, providers={"seedance"})
    observability.reset()


def test_the_setup_creates_what_is_missing_and_is_idempotent() -> None:
    fake = FakeLangfuse(configs=[SimpleNamespace(id="cfg-old", name="aprobado")])
    observability.configure(fake)
    try:
        first = review.setup()
        second = review.setup()
    finally:
        observability.reset()
        observability._queue_ids.clear()

    assert first == second == "queue-1"
    created = {c["name"] for c in fake.created_configs}
    assert "aprobado" not in created  # it already existed
    assert created == {c.name for c in review.SCORE_CONFIGS} - {"aprobado"}
    numeric = next(c for c in fake.created_configs if c["name"] == "fidelidad_producto")
    assert (numeric["data_type"], numeric["min_value"], numeric["max_value"]) == ("NUMERIC", 1, 5)
    boolean = next(c for c in fake.created_configs if c["name"] == "artefactos")
    assert "min_value" not in boolean
    (queue,) = fake.created_queues  # created once
    assert queue["name"] == review.REVIEW_QUEUE
    assert set(queue["score_config_ids"]) == {f"cfg-{n}" for n in review.QUEUE_SCORES}


def test_a_queued_trace_links_to_its_draft_in_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """The trace carries no media bytes; the reviewer opens the draft (2026-10-14)."""
    draft_id = uuid4()
    monkeypatch.delenv("REFLEX_DEPLOY_URL", raising=False)
    assert review.draft_url(draft_id) == f"http://localhost:3000/drafts/{draft_id}"
    monkeypatch.setenv("REFLEX_DEPLOY_URL", "https://qualify.example.co/")
    assert review.draft_url(draft_id) == f"https://qualify.example.co/drafts/{draft_id}"


def test_an_item_can_be_queued_by_its_trace_id(langfuse: FakeLangfuse) -> None:
    observability.enqueue_for_review(review.REVIEW_QUEUE, trace_id="abc123")
    observability.enqueue_for_review(review.REVIEW_QUEUE)  # neither seed nor id: nothing
    assert langfuse.items == [("queue-1", {"object_id": "abc123", "object_type": "TRACE"})]
