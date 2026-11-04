"""Draft 9968b10c (live, 2026-11-03): a gallery whose slide-2 Seedance task outlived the
wait was resumed by starting over — slide 1's scene paid to Seedream again, the resource
selector paid again — and the new slide-1.jpg was refused by R2's object lock over the
one already kept, failing the piece («No pudimos guardar la pieza en R2»).

Now the task keeps what a resumed run needs (the slides finished before it, the scene
it animates, the resource plan), the resumed run pays only what is genuinely missing,
and a generated file never overwrites a key: the same bytes are reused, other bytes get
a key of their own. No network: scripted vendors behind the real router, and an R2 with
the bucket's object lock."""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.adapters.byteplus_ark import RESUME_TASK_PARAM
from qualify_creative.enums import ContentKind, SlideSource, SlideText
from qualify_creative.providers import GenerationRequest, GenerationResult, Usage
from qualify_creative.schemas import CarouselSlide

from qualify_api.creative.media import (
    GALLERY_CONTEXT,
    OCCUPIED,
    R2ReadingMediaStore,
    _Saver,
)

from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    SEEDREAM_MODEL,
    TENANT_ID,
    FakeFitter,
    FakeSeedance,
    FakeSeedream,
    _brief,
    _carousel_producer,
    _carousel_store,
    _image,
    _kit,
)
from .test_semantic_resource_selection import Selector, setup_selector


class LockedR2:
    """R2 with the bucket's object lock: a key, once written, refuses every other put.
    Keys it does not hold are read from the local files (the kit's and catalog's)."""

    def __init__(self, local: dict[str, bytes]) -> None:
        self.local = local
        self.stored: dict[str, bytes] = {}
        self.refused: list[str] = []

    def put_media(self, tenant_id: UUID, key: str, fileobj: io.BytesIO, ctype: str) -> None:
        if key in self.stored:
            self.refused.append(key)
            raise RuntimeError("ObjectLockedByBucketPolicy")
        self.stored[key] = fileobj.read()

    def object_size(self, tenant_id: UUID, key: str) -> int:
        from qualify_shared.objects.gate import ObjectNotFound

        if key not in self.stored:
            raise ObjectNotFound(key)
        return len(self.stored[key])

    @contextmanager
    def open_object(self, tenant_id: UUID, key: str) -> Iterator[io.BytesIO]:
        yield io.BytesIO(self.stored[key] if key in self.stored else self.local[key])


class VaryingSeedream(FakeSeedream):
    """Every scene is a different image, as Seedream's are."""

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.requests.append(request)
        shade = 40 * len(self.requests) % 255
        return GenerationResult(
            payload={"images": [_image((shade, 120, 200), (1728, 2160))]},
            model_id=SEEDREAM_MODEL,
            provider="seedream",
            usage=Usage(pieces=1),
        )


class QueuedSeedance(FakeSeedance):
    """A new task is accepted (its id heard), then outlives the wait; resumed, it is done."""

    def __init__(self) -> None:
        super().__init__()
        self.created = 0

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        if request.params.get(RESUME_TASK_PARAM) is None:
            self.created += 1
            task_id = f"cgt-{self.created}"
            if request.observer is not None:
                request.observer.created(task_id)
            self.requests.append(request)
            raise RuntimeError(f"ArkTaskTimeout: Seedance task {task_id} still running after 481s")
        return super().generate(request, api_key=api_key)


class Book:
    """A `VendorTaskBinding` in memory; the context goes through JSON like the jsonb row."""

    def __init__(
        self,
        known: dict[str, str] | None = None,
        contexts: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.known = dict(known or {})
        self.contexts = dict(contexts or {})
        self.settled: list[tuple[str, str]] = []

    def resume_id(self, slot: str) -> str | None:
        return self.known.get(slot)

    def resume_context(self, slot: str) -> dict[str, Any] | None:
        return self.contexts.get(slot) if slot in self.known else None

    def observer(self, slot: str, provider: str, model_id: str, *, context: Any = None) -> Any:
        book = self

        class _Obs:
            def created(self, task_id: str) -> None:
                book.known[slot] = task_id
                book.contexts[slot] = json.loads(json.dumps(dict(context or {})))

            def polled(self, task_id: str, status: str) -> None:
                pass

        return _Obs()

    def settle(self, slot: str, status: str) -> None:
        self.settled.append((slot, status))


def _gallery() -> Any:
    return _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, text=SlideText.HOOK),
            CarouselSlide(source=SlideSource.ANIMATED, scene_prompt="la smash girando"),
            CarouselSlide(source=SlideSource.GENERATED, text=SlideText.CTA),
        ),
        closing_slide=True,
    )


def _run(producer: Any, book: Book, draft_id: UUID) -> Any:
    return producer.produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=_gallery(),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        vendor_tasks=book,
    )


def test_a_resumed_gallery_pays_only_what_is_missing_and_never_rewrites_a_slide() -> None:
    local = _carousel_store()
    r2 = LockedR2(local.files)
    store = R2ReadingMediaStore(local, r2)
    seedream, seedance, draft_id = VaryingSeedream(), QueuedSeedance(), uuid4()
    producer = _carousel_producer(store, seedream, seedance, FakeFitter())  # type: ignore[arg-type]

    first = _run(producer, book := Book(), draft_id)

    assert first.pending is True and first.failure is None
    assert len(seedream.requests) == 2  # slide 1's scene, slide 2's scene
    slide_1 = f"t/{TENANT_ID}/generated/{draft_id}/r1/slide-1.jpg"
    scene_2 = f"t/{TENANT_ID}/generated/{draft_id}/r1/slide-2-scene.jpg"
    assert slide_1 in r2.stored and scene_2 in r2.stored
    kept = book.contexts["seedance-1"][GALLERY_CONTEXT]
    assert kept["position"] == 1 and kept["scene_key"] == scene_2
    assert [row["object_key"] for row in kept["slides"]] == [slide_1]
    slide_1_bytes = r2.stored[slide_1]

    # 20 minutes later BytePlus finished it: the next read resumes this revision
    resumed = Book(known=book.known, contexts=book.contexts)
    outcome = _run(producer, resumed, draft_id)

    assert outcome.failure is None, outcome.detail
    assert outcome.pending is False
    # slide 1 and slide 2's scene are NOT asked of Seedream again: only slide 3's
    assert len(seedream.requests) == 3
    assert [u.provider for u in outcome.usage] == ["seedance", "seedream"]  # video 2, scene 3
    # the recorded Seedance task is polled, never ordered again
    assert seedance.created == 1
    assert seedance.requests[-1].params[RESUME_TASK_PARAM] == "cgt-1"
    assert resumed.settled == [("seedance-1", "succeeded")]
    # slide 1 is the one already kept — same key, same bytes, provenance intact
    assert [(m.position, m.media_type) for m in outcome.media] == [
        (0, "image"),
        (1, "video"),
        (2, "image"),
        (3, "image"),
    ]
    assert outcome.media[0].object_key == slide_1 and r2.stored[slide_1] == slide_1_bytes
    assert outcome.media[0].provider == "seedream"
    assert outcome.media[1].params["task_id"] == "cgt-1"
    assert r2.refused == []  # nothing was ever put over a kept key


def test_a_slide_finished_by_seedance_before_the_waiting_one_keeps_its_slot() -> None:
    """Two animated slides: the first one's task succeeded, the second outlived the wait.
    The resumed run reuses the first video and resumes the SECOND task (seedance-2) —
    a reused slide still takes its slot, so no slide resumes another's video."""

    class SecondQueued(QueuedSeedance):
        def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
            if request.params.get(RESUME_TASK_PARAM) is None and self.created == 0:
                self.created += 1
                if request.observer is not None:
                    request.observer.created("cgt-1")
                self.requests.append(request)
                return FakeSeedance.generate(self, request, api_key=api_key)
            return super().generate(request, api_key=api_key)

    brief = _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.ANIMATED, scene_prompt="uno"),
            CarouselSlide(source=SlideSource.ANIMATED, scene_prompt="dos"),
        ),
    )
    local = _carousel_store()
    r2 = LockedR2(local.files)
    store = R2ReadingMediaStore(local, r2)
    seedream, seedance, draft_id = VaryingSeedream(), SecondQueued(), uuid4()
    producer = _carousel_producer(store, seedream, seedance, FakeFitter())  # type: ignore[arg-type]

    def run(book: Book) -> Any:
        return producer.produce(
            tenant_id=TENANT_ID,
            draft_id=draft_id,
            brief=brief,
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
            vendor_tasks=book,
        )

    assert run(book := Book()).pending
    assert book.known == {"seedance-1": "cgt-1", "seedance-2": "cgt-2"}

    outcome = run(resumed := Book(known=book.known, contexts=book.contexts))

    assert outcome.failure is None, outcome.detail
    assert len(seedream.requests) == 2 and seedance.created == 2
    assert seedance.requests[-1].params[RESUME_TASK_PARAM] == "cgt-2"
    assert resumed.settled == [("seedance-2", "succeeded")]
    assert [m.position for m in outcome.media] == [0, 1]
    assert r2.refused == []


def test_a_different_file_under_a_kept_key_gets_a_key_of_its_own() -> None:
    """(b): the bucket never lets a key be overwritten — a genuinely new render takes a
    content-named key beside it instead of failing a piece already paid for."""
    local = _carousel_store()
    r2 = LockedR2(local.files)
    store = R2ReadingMediaStore(local, r2)
    draft_id = uuid4()
    usual = f"t/{TENANT_ID}/generated/{draft_id}/r1/slide-1.jpg"
    r2.stored[usual] = b"the slide kept earlier"
    save = _Saver(store, TENANT_ID, draft_id, 1)

    key = save("slide-1.jpg", b"another render", "image/jpeg")

    assert key != usual and key.startswith(f"t/{TENANT_ID}/generated/{draft_id}/r1/slide-1-")
    assert key.endswith(".jpg") and r2.stored[key] == b"another render"
    assert r2.stored[usual] == b"the slide kept earlier" and r2.refused == []
    # the same bytes again land on the same content-named key: reused, not rewritten
    assert save("slide-1.jpg", b"another render", "image/jpeg") == key
    # and the same bytes as the kept file are that file
    assert save("slide-1.jpg", b"the slide kept earlier", "image/jpeg") == usual
    assert store.keep_outcome(TENANT_ID, usual, b"x", "image/jpeg") == OCCUPIED


def test_a_resumed_run_reuses_the_kept_resource_plan_and_pays_no_selector() -> None:
    selector = Selector()
    producer, _, brief = setup_selector(selector)
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    usage: list[Any] = []
    planned, chosen = producer._select_resources(TENANT_ID, brief, refs, BUDGET, usage)
    assert len(selector.requests) == 1 and [u.provider for u in usage] == ["anthropic"]
    kept = json.loads(json.dumps(chosen.selection))

    again: list[Any] = []
    replanned, rechosen = producer._select_resources(
        TENANT_ID, brief, refs, BUDGET, again, frozen_selection=kept
    )

    assert len(selector.requests) == 1 and again == []  # nothing asked, nothing paid
    assert rechosen.refs == chosen.refs and rechosen.overlay == chosen.overlay
    assert rechosen.selection == chosen.selection
    assert replanned.media == planned.media


@pytest.mark.parametrize("broken", [{"version": 1}, {"resource_indices": [99]}])
def test_a_kept_plan_that_no_longer_applies_asks_the_selector_again(broken: Any) -> None:
    selector = Selector()
    producer, _, brief = setup_selector(selector)
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    _, chosen = producer._select_resources(TENANT_ID, brief, refs, BUDGET, [])
    usage: list[Any] = []
    producer._select_resources(
        TENANT_ID, brief, refs, BUDGET, usage, frozen_selection={**chosen.selection, **broken}
    )
    assert len(selector.requests) == 2 and [u.provider for u in usage] == ["anthropic"]
    assert usage[0].cost_usd > Decimal(0)


def test_a_resumed_seedance_talking_video_reuses_its_first_frame() -> None:
    """(c) the same resume path on a Seedance talking video: its first frame (Seedream,
    paid) was kept as first-frame.jpg before the task — the resumed run reads it back
    instead of ordering another and failing to store it over the locked key."""
    from .test_creative_media_byteplus import _producer, _seedance_brief

    local = _carousel_store()
    r2 = LockedR2(local.files)
    store = R2ReadingMediaStore(local, r2)
    seedream, seedance, draft_id = VaryingSeedream(), QueuedSeedance(), uuid4()
    producer = _producer(store, seedream=seedream, seedance=seedance)  # type: ignore[arg-type]

    def run(book: Book) -> Any:
        return producer.produce(
            tenant_id=TENANT_ID,
            draft_id=draft_id,
            brief=_seedance_brief(),
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
            vendor_tasks=book,
        )

    assert run(book := Book()).pending
    frame = f"t/{TENANT_ID}/generated/{draft_id}/r1/first-frame.jpg"
    assert book.contexts["seedance-1"]["first_frame_key"] == frame

    outcome = run(Book(known=book.known, contexts=book.contexts))

    assert outcome.failure is None, outcome.detail
    assert len(seedream.requests) == 1 and seedance.created == 1
    assert [u.provider for u in outcome.usage] == ["seedance"]
    assert r2.refused == []
