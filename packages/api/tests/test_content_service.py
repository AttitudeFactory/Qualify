"""ContentService tests (MC backlog #6).

Pure block: the service against an in-memory repository and scripted router/dispatcher
fakes — the FSM discipline, the readiness/policy gates, the idempotency-by-state rule
and the §7.4 every-exit-terminal guarantee, no Postgres involved.

`db` block at the bottom: the full happy path against the compose Postgres with a fake
adapter injected into the REAL router (no network, no anthropic SDK): create → run →
GENERATED with variants persisted → approve → `approved_creative` returns the artifact.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_creative.adapters.anthropic_copy import CopyRefused
from qualify_creative.enums import (
    BriefObjective,
    ContentFormat,
    ContentKind,
    ContentType,
    GenerationTask,
    ImageRoute,
    PaidBy,
    PostCategory,
    ReuseType,
    VoiceProfileStatus,
    default_category,
)
from qualify_creative.providers import GenerationResult, ResolvedKey, Usage
from qualify_creative.router import BudgetContext, Hop, HopAction, RouterOutcome
from qualify_creative.schemas import (
    BrandKit,
    BrandVoiceProfile,
    ContentBrief,
    CopyPayload,
    MediaInputs,
    ToneAxes,
)

from qualify_api.creative.fsm import (
    APPROVED,
    DRAFTING,
    FAILED,
    GENERATED,
    InvalidTransition,
)
from qualify_api.creative.media import MediaOutcome, MediaUsage, MediaWrite
from qualify_api.creative.service import (
    BrandNotReady,
    BudgetState,
    ContentService,
    DraftBundle,
    DraftRecord,
    DuplicateDraftRequest,
    ImageRecord,
    RouteBlockedByPolicy,
    UnknownVariant,
    UsageWrite,
    VariantRecord,
    VariantWrite,
    preview_of,
)

TENANT_ID = uuid4()
BRAND_ID = uuid4()
USER_ID = uuid4()

_TONE = ToneAxes(formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=40)

GOOD_CAPTION = (
    "Llegó la arepa de chócolo: maíz dulce molido en casa, queso costeño derretido y"
    " mantequilla de verdad, como se hace en Cali."
)


def make_kit(**overrides: object) -> BrandKit:
    base: dict[str, object] = {
        "brand_id": BRAND_ID,
        "positioning": "artisan arepas, zero shortcuts",
        "audience": "walk-in customers in Cali",
        "tone_axes": _TONE,
        "banned_words": ("gourmet",),
    }
    base.update(overrides)
    return BrandKit.model_validate(base)


def make_voice(version: int = 3) -> BrandVoiceProfile:
    return BrandVoiceProfile(
        brand_id=BRAND_ID,
        version=version,
        status=VoiceProfileStatus.ACTIVE,
        tone_axes=_TONE,
    )


def make_brief(variants: int = 2, **overrides: object) -> ContentBrief:
    base: dict[str, object] = {
        "brand_id": BRAND_ID,
        "objective": BriefObjective.SALE,
        "content_type": ContentType.MENU,
        "topic": "arepa de chócolo nueva",
        "image_route": ImageRoute.TEMPLATE_ONLY,
        "variants_requested": variants,
    }
    base.update(overrides)
    return ContentBrief.model_validate(base)


def copy_dict(hook: str = "Nueva arepa de chócolo", caption: str = GOOD_CAPTION) -> dict:
    return {"hook": hook, "caption": caption, "hashtags": ["arepas", "cali"], "cta": "Pide ya"}


def ok_outcome(payload: dict, hook_provider: str = "anthropic") -> RouterOutcome:
    result = GenerationResult(
        payload=payload,
        model_id="claude-opus-5",
        provider=hook_provider,
        usage=Usage(input_tokens=1000, output_tokens=500),
        model_revision="rev-1",
    )
    return RouterOutcome(result=result, hops=(Hop(hook_provider, HopAction.SUCCEEDED),))


BUDGET_BLOCKED = RouterOutcome(
    result=None,
    hops=(Hop("anthropic", HopAction.BUDGET_BLOCKED, "estimated $1 exceeds remaining $0"),),
)

#: A CopyRefused swallowed by the real router shows up as a FAILED hop naming the class.
REFUSAL_HOP = RouterOutcome(
    result=None,
    hops=(Hop("anthropic", HopAction.FAILED, "CopyRefused: refused by claude-opus-5"),),
)


# ---------------------------------------------------------------------------
# Fakes


class FakeBrand:
    def __init__(self, kit: BrandKit | None) -> None:
        self._kit = kit

    def kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit | None:
        return self._kit


class FakeVoice:
    def __init__(self, voice: BrandVoiceProfile | None) -> None:
        self._voice = voice

    def active(self, *, tenant_id: UUID, brand_id: UUID) -> BrandVoiceProfile | None:
        return self._voice


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    def dispatch_generation(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        self.calls.append((tenant_id, draft_id))


class FakeRouter:
    """Scripted: each `run` pops the next item — a RouterOutcome or an Exception."""

    def __init__(self, script: list[object] | None = None) -> None:
        self.script = list(script or [])
        self.budgets: list[BudgetContext] = []
        self.requests: list[object] = []

    def run(self, *, tenant_id, brand_id, chain, request, budget):  # noqa: ANN001, ANN201
        self.budgets.append(budget)
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakePricing:
    version = "test-v0"

    def unit_price(self, *, model_id: str, unit: str) -> Decimal:
        return {"per_mtok_in": Decimal("5"), "per_mtok_out": Decimal("25")}[unit]


class StaticKeyResolver:
    def resolve(self, *, tenant_id: UUID, brand_id: UUID, provider: str) -> ResolvedKey:
        return ResolvedKey(api_key="test-key", paid_by=PaidBy.PLATFORM, fingerprint="static")


class InMemoryRepository:
    """ContentRepository over dicts, faithful to the Postgres one's semantics."""

    def __init__(self) -> None:
        self.briefs: dict[UUID, ContentBrief] = {}
        self.drafts: dict[UUID, DraftRecord] = {}
        self.variants: dict[UUID, VariantRecord] = {}
        self.usage: list[UsageWrite] = []
        self.budget: BudgetState | None = None
        self.spend_added = Decimal("0")
        self.media: dict[UUID, list[ImageRecord]] = {}
        self.template_runs = {}
        self.recent: tuple[str, ...] | Exception = ()

    def insert_brief_and_draft(
        self, *, tenant_id, user_id, brief, voice_profile_version, pipeline_version
    ):  # noqa: ANN001, ANN201
        brief_id, draft_id = uuid4(), uuid4()
        self.briefs[brief_id] = brief
        self.drafts[draft_id] = DraftRecord(
            id=draft_id,
            brand_id=brief.brand_id,
            brief_id=brief_id,
            status=DRAFTING,
            failure_reason=None,
            selected_variant_id=None,
            voice_profile_version=voice_profile_version,
            pipeline_version=pipeline_version,
            requires_ai_disclosure=brief.requires_ai_disclosure,
            approved_by=None,
            approved_at=None,
            created_at=datetime.now(UTC),
            title=brief.topic[:120],
            category=default_category(brief.kind, brief.format).value,
        )
        return draft_id

    def seed_draft(self, brief: ContentBrief, status: str = DRAFTING) -> UUID:
        draft_id = self.insert_brief_and_draft(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            brief=brief,
            voice_profile_version=3,
            pipeline_version="creative-v1",
        )
        if status != DRAFTING:
            self.drafts[draft_id] = replace(self.drafts[draft_id], status=status)
        return draft_id

    def get_draft(self, *, tenant_id, draft_id):  # noqa: ANN001, ANN201
        return self.drafts.get(draft_id)

    def get_brief(self, *, tenant_id, brief_id):  # noqa: ANN001, ANN201
        return self.briefs.get(brief_id)

    def budget_state(self, *, tenant_id, brand_id):  # noqa: ANN001, ANN201
        return self.budget

    def recent_openings(self, *, tenant_id, brand_id, limit=8):  # noqa: ANN001, ANN201
        if isinstance(self.recent, Exception):
            raise self.recent
        return self.recent

    def finish_generation(
        self,
        *,
        tenant_id,
        draft_id,
        brand_id,
        new_status,
        failure_reason,
        variants,
        usage,
        spent_usd,
        media=(),
        failure_detail=None,
        template_run=None,
        requires_ai_disclosure=None,
    ):  # noqa: ANN001, ANN201
        if template_run is not None:
            self.template_runs[template_run.id] = template_run
        if media or variants:
            # as Postgres: a generation that wrote copy replaces the media rows, also
            # when it made none (a failed regeneration shows no stale images)
            self.media.pop(draft_id, None)
            self.drafts[draft_id] = replace(self.drafts[draft_id], preview_key=preview_of(media))
        if variants:
            # as Postgres: the new copy replaces the old, and a selection of the old goes
            self.variants = {k: v for k, v in self.variants.items() if v.draft_id != draft_id}
            self.drafts[draft_id] = replace(self.drafts[draft_id], selected_variant_id=None)
        if requires_ai_disclosure is not None:
            self.drafts[draft_id] = replace(
                self.drafts[draft_id], requires_ai_disclosure=requires_ai_disclosure
            )
        if media:
            self.media[draft_id] = [
                ImageRecord(
                    id=uuid4(),
                    media_url=item.media_url,
                    width=item.width,
                    height=item.height,
                    aspect_ratio=item.aspect_ratio,
                    media_type=item.media_type,
                    position=item.position,
                    params=item.params,
                )
                for item in media
            ]
        for write in variants:
            assert isinstance(write, VariantWrite)
            variant_id = uuid4()
            self.variants[variant_id] = VariantRecord(
                id=variant_id,
                draft_id=draft_id,
                ordinal=write.ordinal,
                copy=write.copy,
                edited_copy=None,
                fidelity=write.fidelity,
                model_id=write.model_id,
                model_revision=write.model_revision,
            )
        self.usage.extend(usage)
        self.spend_added += spent_usd
        draft = self.drafts[draft_id]
        if draft.status == DRAFTING:
            self.drafts[draft_id] = replace(
                draft,
                status=new_status,
                failure_reason=failure_reason,
                failure_detail=failure_detail,
            )

    def update_status(self, *, tenant_id, draft_id, new_status, failure_reason):  # noqa: ANN001, ANN201
        self.drafts[draft_id] = replace(
            self.drafts[draft_id], status=new_status, failure_reason=failure_reason
        )

    def set_approved(self, *, tenant_id, draft_id, new_status, variant_id, user_id, approved_at):  # noqa: ANN001, ANN201
        self.drafts[draft_id] = replace(
            self.drafts[draft_id],
            status=new_status,
            selected_variant_id=variant_id,
            approved_by=user_id,
            approved_at=approved_at,
            approved_revision=self.drafts[draft_id].revision,
        )

    def bump_revision(self, *, tenant_id, draft_id):  # noqa: ANN001, ANN201
        draft = self.drafts[draft_id]
        self.drafts[draft_id] = replace(draft, revision=draft.revision + 1)
        return draft.revision + 1

    def update_post(self, *, tenant_id, draft_id, title, category, reuse_type):  # noqa: ANN001, ANN201
        draft = self.drafts[draft_id]
        self.drafts[draft_id] = replace(
            draft,
            title=draft.title if title is None else title,
            category=draft.category if category is None else category,
            reuse_type=draft.reuse_type if reuse_type is None else (reuse_type or None),
        )

    def list_drafts(self, *, tenant_id, brand_id, status, limit, offset):  # noqa: ANN001, ANN201
        rows = [
            d
            for d in self.drafts.values()
            if d.brand_id == brand_id and (status is None or d.status == status)
        ]
        rows.sort(key=lambda d: d.created_at, reverse=True)
        return tuple(rows[offset : offset + limit])

    def variants_for(self, *, tenant_id, draft_id):  # noqa: ANN001, ANN201
        rows = [v for v in self.variants.values() if v.draft_id == draft_id]
        return tuple(sorted(rows, key=lambda v: v.ordinal))

    def image_for(self, *, tenant_id, draft_id):  # noqa: ANN001, ANN201
        items = self.media.get(draft_id) or []
        return items[0] if items else None

    def media_for(self, *, tenant_id, draft_id):  # noqa: ANN001, ANN201
        return tuple(self.media.get(draft_id) or ())

    def brief_kind(self, *, tenant_id, brief_id):  # noqa: ANN001, ANN201
        brief = self.briefs.get(brief_id)
        return None if brief is None else brief.kind.value

    def get_variant(self, *, tenant_id, variant_id):  # noqa: ANN001, ANN201
        return self.variants.get(variant_id)

    def set_edited_copy(self, *, tenant_id, variant_id, edited_copy):  # noqa: ANN001, ANN201
        self.variants[variant_id] = replace(self.variants[variant_id], edited_copy=edited_copy)


def make_service(
    *,
    router: FakeRouter | None = None,
    kit: BrandKit | None = None,
    voice: BrandVoiceProfile | None = None,
    repo: InMemoryRepository | None = None,
    dispatcher: RecordingDispatcher | None = None,
    media: object | None = None,
) -> tuple[ContentService, InMemoryRepository, RecordingDispatcher]:
    repo = repo or InMemoryRepository()
    dispatcher = dispatcher or RecordingDispatcher()
    service = ContentService(
        router=router or FakeRouter(),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(voice),
        brand_service=FakeBrand(kit),
        repository=repo,
        dispatcher=dispatcher,
        media=media,  # type: ignore[arg-type]
    )
    return service, repo, dispatcher


# ---------------------------------------------------------------------------
# preview_prompt (§ request 2026-10-06: the prompt in the console before Generar)


def test_preview_prompt_prints_the_real_prompt_and_creates_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from qualify_creative.brand import render_prompt
    from qualify_creative.enums import GenerationTask

    caplog.set_level(logging.INFO, logger="qualify_api.creative.trace")
    kit, voice, brief = make_kit(), make_voice(), make_brief()
    router = FakeRouter()
    service, repo, dispatcher = make_service(router=router, kit=kit, voice=voice)
    assert service.preview_prompt(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief)
    first, second = (
        render_prompt(kit=kit, voice=voice, brief=brief, task=GenerationTask.COPY, variant=index)
        for index in range(2)
    )
    assert "VISTA PREVIA DEL PROMPT" in caplog.text
    assert first.stable_prefix in caplog.text
    assert first.volatile_suffix in caplog.text and second.volatile_suffix in caplog.text
    assert repo.drafts == {} and repo.briefs == {} and dispatcher.calls == []
    assert router.budgets == []  # no vendor call


def test_preview_prompt_says_what_is_missing(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="qualify_api.creative.trace")
    service, _, _ = make_service(kit=make_kit(), voice=None)
    assert not service.preview_prompt(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief())
    assert "no se puede armar, falta: voice_profile" in caplog.text


# ---------------------------------------------------------------------------
# create_draft


def test_create_draft_raises_brand_not_ready_before_any_row() -> None:
    service, repo, dispatcher = make_service(kit=make_kit(), voice=None)
    with pytest.raises(BrandNotReady) as excinfo:
        service.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(), user_id=USER_ID
        )
    assert excinfo.value.missing == ("voice_profile",)
    assert repo.drafts == {} and repo.briefs == {}
    assert dispatcher.calls == []


def test_create_draft_blocks_route_by_policy_before_any_row() -> None:
    # The default ImagePolicy allows only TEMPLATE_ONLY/FROM_UPLOAD.
    service, repo, dispatcher = make_service(kit=make_kit(), voice=make_voice())
    with pytest.raises(RouteBlockedByPolicy):
        service.create_draft(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            brief=make_brief(image_route=ImageRoute.GENERATE),
            user_id=USER_ID,
        )
    assert repo.drafts == {} and dispatcher.calls == []


def test_create_draft_persists_drafting_row_and_dispatches() -> None:
    service, repo, dispatcher = make_service(kit=make_kit(), voice=make_voice(version=7))
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(), user_id=USER_ID
    )
    draft = repo.drafts[draft_id]
    assert draft.status == DRAFTING
    assert draft.voice_profile_version == 7
    assert draft.pipeline_version == "creative-v1"
    assert draft.requires_ai_disclosure is False  # TEMPLATE_ONLY needs no disclosure
    assert dispatcher.calls == [(TENANT_ID, draft_id)]


# ---------------------------------------------------------------------------
# run_generation


def test_run_generation_is_noop_past_drafting() -> None:
    router = FakeRouter()  # any call would pop an empty script and blow up
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(), status=GENERATED)
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert router.budgets == []
    assert repo.drafts[draft_id].status == GENERATED


def test_run_generation_happy_path_generates_and_records_spend() -> None:
    router = FakeRouter([ok_outcome(copy_dict("Hook uno")), ok_outcome(copy_dict("Hook dos"))])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=2))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    draft = repo.drafts[draft_id]
    assert draft.status == GENERATED and draft.failure_reason is None
    variants = repo.variants_for(tenant_id=TENANT_ID, draft_id=draft_id)
    assert [v.ordinal for v in variants] == [0, 1]
    assert all(v.fidelity["passed"] for v in variants)
    assert variants[0].copy["hook"] == "Hook uno"

    # (1000 in * $5 + 500 out * $25) / 1e6 per call.
    per_call = Decimal("0.0175")
    assert len(repo.usage) == 2
    assert all(u.cost_usd == per_call for u in repo.usage)
    assert all(u.paid_by == "platform" for u in repo.usage)
    assert all(u.pricing_table_version == "test-v0" for u in repo.usage)
    assert repo.spend_added == per_call * 2

    # No config row → unlimited, soft; the second call's remaining reflects real spend.
    assert router.budgets[0].hard_stop is False
    assert router.budgets[0].remaining_usd - router.budgets[1].remaining_usd == per_call


def test_each_variant_is_asked_its_own_angle_and_told_the_recent_openings() -> None:
    router = FakeRouter([ok_outcome(copy_dict("Hook uno")), ok_outcome(copy_dict("Hook dos"))])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    repo.recent = ("Mano, pilla esta arepa", "Pide ya")
    draft_id = repo.seed_draft(make_brief(variants=2))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    assert repo.drafts[draft_id].status == GENERATED
    first, second = (request.rendered_prompt for request in router.requests)
    assert first.stable_prefix == second.stable_prefix  # the cache still hits
    assert "This is variant 1 of 2" in first.volatile_suffix
    assert "This is variant 2 of 2" in second.volatile_suffix
    assert all("- Mano, pilla esta arepa" in p.volatile_suffix for p in (first, second))


def test_unreadable_recent_openings_never_fail_the_generation() -> None:
    router = FakeRouter([ok_outcome(copy_dict("Hook uno")), ok_outcome(copy_dict("Hook dos"))])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    repo.recent = RuntimeError("db down")
    draft_id = repo.seed_draft(make_brief(variants=2))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    assert repo.drafts[draft_id].status == GENERATED
    assert all("used recently" not in r.rendered_prompt.volatile_suffix for r in router.requests)


def test_recent_openings_are_hooks_and_ctas_newest_first_without_repeats() -> None:
    from qualify_api.creative.service import _openings

    assert _openings(
        [
            {"hook": "Pilla esta", "cta": "Pide ya"},
            {"hook": "Pilla esta", "cta": ""},
            None,
            {"hook": " Otra ", "cta": "Pide ya"},
        ]
    ) == ("Pilla esta", "Pide ya", "Otra")


def test_run_generation_passes_configured_budget_hard_stop() -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    repo.budget = BudgetState(remaining_usd=Decimal("10"), hard_stop=True)
    draft_id = repo.seed_draft(make_brief(variants=1))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert router.budgets[0].remaining_usd == Decimal("10")
    assert router.budgets[0].hard_stop is True
    assert repo.drafts[draft_id].status == GENERATED


def test_all_variants_hard_failing_is_fidelity_rejected() -> None:
    bad = copy_dict(caption=GOOD_CAPTION + " Un toque gourmet inolvidable.")
    router = FakeRouter([ok_outcome(bad), ok_outcome(bad)])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=2))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    draft = repo.drafts[draft_id]
    assert draft.status == FAILED and draft.failure_reason == "fidelity_rejected"
    # The variants are persisted anyway — the recorded failures are the evidence.
    variants = repo.variants_for(tenant_id=TENANT_ID, draft_id=draft_id)
    assert len(variants) == 2
    assert all(not v.fidelity["passed"] for v in variants)
    assert repo.usage and repo.spend_added > 0


def test_one_passing_variant_is_enough_for_generated() -> None:
    bad = copy_dict(caption=GOOD_CAPTION + " Un toque gourmet inolvidable.")
    router = FakeRouter([ok_outcome(bad), ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=2))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert repo.drafts[draft_id].status == GENERATED


def test_refusal_exception_fails_with_refusal_reason() -> None:
    router = FakeRouter([CopyRefused("claude-opus-5")])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=1))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    draft = repo.drafts[draft_id]
    assert draft.status == FAILED and draft.failure_reason == "refusal"


def test_refusal_swallowed_into_hops_is_still_refusal() -> None:
    router = FakeRouter([REFUSAL_HOP])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=1))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    draft = repo.drafts[draft_id]
    assert draft.status == FAILED and draft.failure_reason == "refusal"


def test_budget_block_fails_terminal_and_keeps_prior_usage() -> None:
    router = FakeRouter([ok_outcome(copy_dict()), BUDGET_BLOCKED])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=2))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    draft = repo.drafts[draft_id]
    assert draft.status == FAILED and draft.failure_reason == "budget_exceeded"
    # The first call's money was spent: its usage row and spend survive the failure.
    assert len(repo.usage) == 1
    assert repo.spend_added == Decimal("0.0175")
    assert repo.variants_for(tenant_id=TENANT_ID, draft_id=draft_id) == ()


def test_unexpected_exception_still_exits_terminal() -> None:
    """§7.4: a draft stuck in DRAFTING forever is the failure mode run_generation
    exists to prevent — an arbitrary crash must land in FAILED/provider_error."""
    router = FakeRouter([RuntimeError("boom")])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=1))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    draft = repo.drafts[draft_id]
    assert draft.status == FAILED and draft.failure_reason == "provider_error"


# ---------------------------------------------------------------------------
# HITL #2


def _generated_draft_with_variant(
    service: ContentService, repo: InMemoryRepository
) -> tuple[UUID, UUID]:
    draft_id = repo.seed_draft(make_brief(variants=1))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    (variant,) = repo.variants_for(tenant_id=TENANT_ID, draft_id=draft_id)
    return draft_id, variant.id


def test_edit_variant_stores_only_passing_copy() -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    _, variant_id = _generated_draft_with_variant(service, repo)

    bad_edit = CopyPayload.model_validate(
        copy_dict(caption=GOOD_CAPTION + " Sabor gourmet garantizado.")
    )
    failures = service.edit_variant(
        tenant_id=TENANT_ID, variant_id=variant_id, copy=bad_edit, user_id=USER_ID
    )
    assert failures and failures[0].rule == "banned_word"
    assert repo.variants[variant_id].edited_copy is None  # NOT stored — not overridable

    good_edit = CopyPayload.model_validate(copy_dict(hook="Editado a mano"))
    assert (
        service.edit_variant(
            tenant_id=TENANT_ID, variant_id=variant_id, copy=good_edit, user_id=USER_ID
        )
        == ()
    )
    assert repo.variants[variant_id].edited_copy["hook"] == "Editado a mano"


def test_a_human_edit_may_have_any_caption_length() -> None:
    """The kit's caption length guides generation; it never blocks the operator's own
    text (founder, 2026-10-06). The other rules still do."""
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    _, variant_id = _generated_draft_with_variant(service, repo)
    short = CopyPayload.model_validate(copy_dict(caption="Corto."))
    assert (
        service.edit_variant(
            tenant_id=TENANT_ID, variant_id=variant_id, copy=short, user_id=USER_ID
        )
        == ()
    )
    assert repo.variants[variant_id].edited_copy["caption"] == "Corto."


def test_approve_stamps_and_requires_matching_variant() -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id, variant_id = _generated_draft_with_variant(service, repo)

    with pytest.raises(UnknownVariant):
        service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=uuid4(), user_id=USER_ID)

    detail = service.approve(
        tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID
    )
    assert detail.status == APPROVED
    assert detail.selected_variant_id == variant_id
    assert detail.approved_by == USER_ID
    assert detail.approved_at is not None


def test_reject_with_regenerate_reenters_drafting_and_redispatches() -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, dispatcher = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id, _ = _generated_draft_with_variant(service, repo)

    detail = service.reject(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        reason="off voice",
        user_id=USER_ID,
        regenerate=True,
    )
    assert detail.status == DRAFTING
    assert dispatcher.calls == [(TENANT_ID, draft_id)]


# ---------------------------------------------------------------------------
# db: full happy path against Postgres, fake adapter injected (no network)


DB_TENANT = UUID("a0000000-0000-4000-8000-0000000000e1")


class FakeCopyAdapter:
    """A real GenerationProvider for the REAL CreativeRouter — no SDK, no network."""

    name = "anthropic"
    supports = frozenset({GenerationTask.COPY})

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request, *, api_key):  # noqa: ANN001, ANN201
        assert api_key == "test-key"  # the resolver's key reaches the adapter
        self.calls += 1
        return GenerationResult(
            payload=copy_dict(hook=f"Hook {self.calls}"),
            model_id="claude-opus-5",
            provider=self.name,
            usage=Usage(input_tokens=1200, output_tokens=400),
            model_revision="claude-opus-5-20260501",
        )

    def estimate_cost_usd(self, request, pricing, *, api_key=None):  # noqa: ANN001, ANN201
        return Decimal("0.02")


@pytest.fixture
def db_seeded() -> tuple[UUID, UUID, UUID]:
    """Tenant + brand + user + a ready brand substrate (kit row and ACTIVE voice row),
    insert-if-absent so local re-runs stay green. Returns (tenant, brand, user)."""
    from qualify_shared.db.admin import admin_session
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    from qualify_api.creative import models as orm
    from qualify_api.tenancy.models import Brand, Tenant, User

    with admin_session() as session:
        if session.get(Tenant, DB_TENANT) is None:
            session.add(
                Tenant(
                    id=DB_TENANT,
                    name="content-service-t",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        brand = session.scalar(select(Brand).where(Brand.tenant_id == DB_TENANT))
        if brand is None:
            brand = Brand(tenant_id=DB_TENANT, name="content-service-brand")
            session.add(brand)
            session.flush()
        brand_id = brand.id
        user = User(tenant_id=DB_TENANT, email=f"content-{uuid4()}@t.co", display_name="Approver")
        session.add(user)
        session.flush()
        user_id = user.id

    with tenant_session(DB_TENANT) as session:
        if session.scalar(select(orm.BrandKit).where(orm.BrandKit.brand_id == brand_id)) is None:
            session.add(
                orm.BrandKit(
                    tenant_id=DB_TENANT,
                    brand_id=brand_id,
                    positioning="artisan arepas, zero shortcuts",
                    audience="walk-in customers in Cali",
                    language="es",
                    regional_variant="es-CO",
                    tone_axes={
                        "formal_casual": 70,
                        "sober_enthusiastic": 60,
                        "technical_plain": 80,
                        "brief_elaborate": 40,
                    },
                    banned_words=["gourmet"],
                    emoji_policy="sparse",
                    image_policy={"allowed_routes": ["template_only", "from_upload"]},
                )
            )
        if (
            session.scalar(
                select(orm.BrandVoiceProfile).where(orm.BrandVoiceProfile.brand_id == brand_id)
            )
            is None
        ):
            session.add(
                orm.BrandVoiceProfile(
                    tenant_id=DB_TENANT,
                    brand_id=brand_id,
                    version=1,
                    status="active",
                    profile={
                        "tone_axes": {
                            "formal_casual": 70,
                            "sober_enthusiastic": 60,
                            "technical_plain": 80,
                            "brief_elaborate": 40,
                        },
                        "lexicon": ["chócolo"],
                        "sentence_rhythm": "short and warm",
                    },
                    sources=[{"kind": "manual_kit", "ref": "brand_kit", "excerpt": "seed"}],
                    distilled_by_model="test-distiller",
                )
            )
    return DB_TENANT, brand_id, user_id


@pytest.mark.db
def test_full_happy_path_create_run_approve_and_read_seam(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.router import CreativeRouter
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    from qualify_api.creative import models as orm
    from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
    from qualify_api.creative.read import approved_creative, list_approved

    tenant_id, brand_id, user_id = db_seeded
    adapter = FakeCopyAdapter()
    pricing = JsonPricingTable("v1")
    router = CreativeRouter(
        providers={"anthropic": adapter}, pricing=pricing, credentials=StaticKeyResolver()
    )
    service = ContentService(
        router=router,
        pricing=pricing,
        credentials=StaticKeyResolver(),
        voice_service=DbVoiceProfileReader(),
        brand_service=DbBrandKitReader(),
        dispatcher=None,  # run synchronously below — deterministic in a test
    )

    brief = make_brief(variants=2, brand_id=brand_id)
    draft_id = service.create_draft(
        tenant_id=tenant_id, brand_id=brand_id, brief=brief, user_id=user_id
    )
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail is not None and detail.status == DRAFTING

    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail is not None
    assert detail.status == GENERATED
    assert [v.ordinal for v in detail.variants] == [0, 1]
    assert detail.variants[0].copy["hook"] == "Hook 1"
    assert all(v.fidelity["passed"] for v in detail.variants)
    assert detail.image is None  # copy-only draft is legal (no template asset)

    # Idempotent by state: a second run is a no-op, no double spend, no new variants.
    calls_before = adapter.calls
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    assert adapter.calls == calls_before
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail is not None and len(detail.variants) == 2

    # Cost provenance landed: one platform-paid usage row per call, v1 pricing.
    with tenant_session(tenant_id) as session:
        events = session.scalars(
            select(orm.CreativeUsageEvent).where(orm.CreativeUsageEvent.draft_id == draft_id)
        ).all()
        assert len(events) == 2
        assert all(e.paid_by == "platform" for e in events)
        assert all(e.pricing_table_version == "v1" for e in events)
        assert all(Decimal(e.cost_usd) > 0 for e in events)

    # The read seam refuses work in progress...
    assert approved_creative(tenant_id=tenant_id, draft_id=draft_id) is None

    detail = service.approve(
        tenant_id=tenant_id,
        draft_id=draft_id,
        variant_id=detail.variants[0].id,
        user_id=user_id,
    )
    assert detail.status == APPROVED

    # ...and hands out the artifact once a human approved.
    artifact = approved_creative(tenant_id=tenant_id, draft_id=draft_id)
    assert artifact is not None
    assert artifact.copy.hook == "Hook 1"
    assert artifact.brand_id == brand_id
    assert artifact.provenance["pipeline_version"] == "creative-v1"
    assert artifact.provenance["copy_model_id"] == "claude-opus-5"
    assert artifact.provenance["voice_profile_version"] == 1
    assert artifact.image_media_url is None

    listed = list_approved(tenant_id=tenant_id, brand_id=brand_id, since=None, intent=None)
    assert draft_id in {a.draft_id for a in listed}


def test_regenerating_an_already_rejected_draft_skips_the_second_reject() -> None:
    router = FakeRouter([ok_outcome(copy_dict()), ok_outcome(copy_dict())])
    service, repo, dispatcher = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id, _ = _generated_draft_with_variant(service, repo)
    service.reject(tenant_id=TENANT_ID, draft_id=draft_id, reason="no", user_id=USER_ID)
    detail = service.reject(
        tenant_id=TENANT_ID, draft_id=draft_id, reason="again", user_id=USER_ID, regenerate=True
    )
    assert detail.status == DRAFTING
    assert dispatcher.calls == [(TENANT_ID, draft_id)]


def test_rejecting_an_already_rejected_draft_is_an_invalid_transition() -> None:
    from qualify_api.creative.fsm import InvalidTransition

    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id, _ = _generated_draft_with_variant(service, repo)
    service.reject(tenant_id=TENANT_ID, draft_id=draft_id, reason="no", user_id=USER_ID)
    with pytest.raises(InvalidTransition):
        service.reject(tenant_id=TENANT_ID, draft_id=draft_id, reason="no", user_id=USER_ID)


# ---------------------------------------------------------------------------
# content kinds: the media half of a draft (§ request 2026-09-25)


class FakeMedia:
    """A `MediaProducer` stand-in: records what it was asked, answers a set outcome."""

    def __init__(self, outcome: MediaOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[ContentBrief, CopyPayload]] = []

    def produce(self, *, tenant_id, draft_id, brief, kit, copy, budget, revision=1):  # noqa: ANN001, ANN201, E501
        self.calls.append((brief, copy))
        return self.outcome


FLYER_MEDIA = MediaWrite(
    position=0,
    media_type="image",
    media_url="generated/t/d/slide-1.png",
    object_key="generated/t/d/slide-1.png",
    width=1080,
    height=1350,
    aspect_ratio="4:5",
    model_id="qualify-compose-v1",
    provider="local",
)


def test_a_flyer_draft_keeps_its_media_built_from_the_first_passing_variant() -> None:
    bad = copy_dict("Hook malo", caption=GOOD_CAPTION + " Un toque gourmet inolvidable.")
    router = FakeRouter([ok_outcome(bad), ok_outcome(copy_dict("Hook bueno"))])
    media = FakeMedia(MediaOutcome(media=(FLYER_MEDIA,)))
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice(), media=media)
    draft_id = repo.seed_draft(make_brief(variants=2, kind=ContentKind.STATIC_FLYER))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    assert repo.drafts[draft_id].status == GENERATED
    ((_, winner),) = media.calls
    assert winner.hook == "Hook bueno"  # the variant that passed layer 1, not the first
    detail = service.get_draft(tenant_id=TENANT_ID, draft_id=draft_id)
    assert detail is not None and detail.kind == "static_flyer"
    assert [m.media_url for m in detail.media] == ["generated/t/d/slide-1.png"]


SEEDREAM_MEDIA = replace(
    FLYER_MEDIA, model_id="seedream-5-0-lite-260128", provider="seedream", ai_generated=True
)


def _old_flyer_brief() -> ContentBrief:
    """A flyer brief as stored before `ad_mode` existed: no mode, a product photo."""
    return make_brief(
        variants=1,
        kind=ContentKind.STATIC_FLYER,
        media=MediaInputs(product_keys=(f"uploads/{TENANT_ID}/p1.jpg",)),
    )


def test_an_old_flyer_made_by_seedream_is_labelled_ai_even_without_ad_mode() -> None:
    """PR #100 review: the brief's a-priori label says no (no `ad_mode`), the producer
    rendered it with Seedream anyway — the draft's label follows the media."""
    router = FakeRouter([ok_outcome(copy_dict())])
    media = FakeMedia(MediaOutcome(media=(SEEDREAM_MEDIA,)))
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice(), media=media)
    brief = _old_flyer_brief()
    assert brief.media.ad_mode is None and brief.requires_ai_disclosure is False
    draft_id = repo.seed_draft(brief)
    assert repo.drafts[draft_id].requires_ai_disclosure is False  # as created

    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    draft = repo.drafts[draft_id]
    assert draft.status == GENERATED and draft.requires_ai_disclosure is True


def test_a_regeneration_relabels_the_draft_from_the_media_it_made() -> None:
    router = FakeRouter([ok_outcome(copy_dict()), ok_outcome(copy_dict("Otro hook"))])
    media = FakeMedia(MediaOutcome(media=(FLYER_MEDIA,)))  # the local composition first
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice(), media=media)
    draft_id = repo.seed_draft(_old_flyer_brief())
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert repo.drafts[draft_id].requires_ai_disclosure is False

    service.reject(
        tenant_id=TENANT_ID, draft_id=draft_id, reason="otra", user_id=USER_ID, regenerate=True
    )
    media.outcome = MediaOutcome(media=(SEEDREAM_MEDIA,))  # Seedream wired since
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    draft = repo.drafts[draft_id]
    assert draft.status == GENERATED and draft.revision == 2
    assert draft.requires_ai_disclosure is True


def test_a_failed_regeneration_does_not_keep_the_previous_revisions_media() -> None:
    """PR #100 review (finding 3): new copy came out, the media did not — the draft is
    FAILED with the new text and NO images, not the previous revision's."""
    router = FakeRouter([ok_outcome(copy_dict()), ok_outcome(copy_dict("Otro hook"))])
    media = FakeMedia(MediaOutcome(media=(FLYER_MEDIA,)))
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice(), media=media)
    draft_id = repo.seed_draft(_old_flyer_brief())
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert repo.drafts[draft_id].preview_key == FLYER_MEDIA.media_url

    service.reject(
        tenant_id=TENANT_ID, draft_id=draft_id, reason="otra", user_id=USER_ID, regenerate=True
    )
    media.outcome = MediaOutcome(failure="provider_error", detail="boom")
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    draft = repo.drafts[draft_id]
    assert draft.status == FAILED and draft.failure_reason == "provider_error"
    assert draft.preview_key is None
    detail = service.get_draft(tenant_id=TENANT_ID, draft_id=draft_id)
    assert detail is not None and list(detail.media) == []
    assert [v.copy["hook"] for v in detail.variants] == ["Otro hook"]


def test_a_failed_video_fails_the_draft_but_keeps_the_script_and_the_money_spent() -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    spent = MediaUsage(
        provider="heygen",
        model_id="heygen_prompt_avatar",
        unit="piece",
        quantity=1,
        cost_usd=Decimal("0.50"),
    )
    media = FakeMedia(MediaOutcome(usage=(spent,), failure="provider_error", detail="boom"))
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice(), media=media)
    brief = make_brief(
        variants=1,
        kind=ContentKind.AVATAR_VIDEO,
        media=MediaInputs(avatar_look_id="lk", voice_id="vo"),
    )
    draft_id = repo.seed_draft(brief)
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)

    draft = repo.drafts[draft_id]
    assert draft.status == "failed" and draft.failure_reason == "provider_error"
    assert len(repo.variants_for(tenant_id=TENANT_ID, draft_id=draft_id)) == 1
    heygen = [u for u in repo.usage if u.provider == "heygen"]
    assert [(u.unit, u.pieces, u.cost_usd) for u in heygen] == [("piece", 1, Decimal("0.50"))]
    assert repo.spend_added == Decimal("0.0175") + Decimal("0.50")


def test_a_creator_script_never_asks_for_media() -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    media = FakeMedia(MediaOutcome())
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice(), media=media)
    draft_id = repo.seed_draft(make_brief(variants=1, kind=ContentKind.CREATOR_SCRIPT))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert repo.drafts[draft_id].status == GENERATED and media.calls == []


def test_an_edit_is_merged_over_the_stored_copy() -> None:
    stored = {**copy_dict(), "script": "Hola, soy el guion.", "ads_headline": "Titular"}
    router = FakeRouter([ok_outcome(stored)])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=1))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    (variant,) = repo.variants_for(tenant_id=TENANT_ID, draft_id=draft_id)
    current = service.variant_copy(tenant_id=TENANT_ID, variant_id=variant.id)
    assert current.script == "Hola, soy el guion." and current.ads_headline == "Titular"


# ---------------------------------------------------------------------------
# the POST fields (0027, QUA-109)


def test_a_new_post_is_titled_by_its_topic_and_categorised_by_its_kind() -> None:
    service, repo, _ = make_service(kit=make_kit(), voice=make_voice())
    flyer = repo.seed_draft(make_brief(kind=ContentKind.STATIC_FLYER))
    script = repo.seed_draft(make_brief(kind=ContentKind.CREATOR_SCRIPT))
    detail = service.get_draft(tenant_id=TENANT_ID, draft_id=flyer)
    assert detail is not None
    assert (detail.title, detail.category, detail.revision) == (
        "arepa de chócolo nueva",
        "galeria",
        1,
    )
    assert detail.reuse_type is None and detail.approved_revision is None
    assert repo.drafts[script].category == "reel"


def test_approval_pins_the_revision_and_an_edit_moves_past_it() -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=1))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    (variant,) = repo.variants_for(tenant_id=TENANT_ID, draft_id=draft_id)

    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant.id, user_id=USER_ID)
    assert (repo.drafts[draft_id].revision, repo.drafts[draft_id].approved_revision) == (1, 1)

    edited = CopyPayload.model_validate({**copy_dict(), "hook": "Otra entrada"})
    assert (
        service.edit_variant(
            tenant_id=TENANT_ID, variant_id=variant.id, copy=edited, user_id=USER_ID
        )
        == ()
    )
    draft = repo.drafts[draft_id]
    # the edit is revision 2; what was approved is still revision 1 — and the draft is
    # back in review (the FSM's `edit` edge), not "approved" with an unapproved revision
    assert (draft.revision, draft.approved_revision) == (2, 1)
    assert draft.status == "generated"

    # Approving again pins the edited revision: the POST is approvable, not a dead end.
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant.id, user_id=USER_ID)
    draft = repo.drafts[draft_id]
    assert (draft.status, draft.revision, draft.approved_revision) == ("approved", 2, 2)


def test_an_edit_in_review_keeps_the_draft_in_review() -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id, variant_id = _generated_draft_with_variant(service, repo)
    edited = CopyPayload.model_validate({**copy_dict(), "hook": "Otra entrada"})
    assert (
        service.edit_variant(
            tenant_id=TENANT_ID, variant_id=variant_id, copy=edited, user_id=USER_ID
        )
        == ()
    )
    assert repo.drafts[draft_id].status == "generated"


@pytest.mark.parametrize("status", ["published", "staged", "failed", "drafting"])
def test_a_draft_that_is_not_editable_refuses_the_edit_and_stores_nothing(status: str) -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id, variant_id = _generated_draft_with_variant(service, repo)
    repo.drafts[draft_id] = replace(repo.drafts[draft_id], status=status)
    revision = repo.drafts[draft_id].revision
    edited = CopyPayload.model_validate({**copy_dict(), "hook": "Otra entrada"})
    with pytest.raises(InvalidTransition):
        service.edit_variant(
            tenant_id=TENANT_ID, variant_id=variant_id, copy=edited, user_id=USER_ID
        )
    assert repo.variants[variant_id].edited_copy is None
    assert repo.drafts[draft_id].revision == revision


def test_a_regeneration_is_a_new_revision() -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=1), status=GENERATED)
    service.reject(
        tenant_id=TENANT_ID, draft_id=draft_id, reason="otra", user_id=USER_ID, regenerate=True
    )
    assert repo.drafts[draft_id].revision == 2


def test_the_post_fields_are_set_and_validated() -> None:
    service, repo, _ = make_service(kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief())
    detail = service.update_post(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        title="  Arepa del viernes  ",
        category=PostCategory.STORY.value,
        reuse_type=ReuseType.RECURRENTE.value,
    )
    assert (detail.title, detail.category, detail.reuse_type) == (
        "Arepa del viernes",
        "story",
        "recurrente",
    )
    cleared = service.update_post(tenant_id=TENANT_ID, draft_id=draft_id, reuse_type="")
    assert cleared.reuse_type is None and cleared.category == "story"
    for bad in ({"category": "carrusel"}, {"reuse_type": "evergreen"}, {"title": "   "}):
        with pytest.raises(ValueError):
            service.update_post(tenant_id=TENANT_ID, draft_id=draft_id, **bad)


def test_the_preview_is_the_video_thumbnail_or_the_first_image() -> None:
    slides = tuple(
        MediaWrite(
            position=n,
            media_type="image",
            media_url=f"g/slide-{n + 1}.png",
            object_key=f"g/slide-{n + 1}.png",
            width=1080,
            height=1350,
            aspect_ratio="4:5",
            model_id="m",
            provider="local",
        )
        for n in (1, 0)
    )
    assert preview_of(slides) == "g/slide-1.png"
    video = MediaWrite(
        position=0,
        media_type="video",
        media_url="g/video.mp4",
        object_key="g/video.mp4",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        model_id="heygen_avatar_iv",
        provider="heygen",
        params={"thumbnail_key": "g/thumbnail.jpg"},
    )
    assert preview_of((video,)) == "g/thumbnail.jpg"
    assert preview_of(()) is None


def test_a_story_format_makes_a_story_post() -> None:
    service, repo, _ = make_service(kit=make_kit(), voice=make_voice())
    story = repo.seed_draft(
        make_brief(kind=ContentKind.STATIC_FLYER, format=ContentFormat.STORY_9_16)
    )
    assert repo.drafts[story].category == "story"


def test_a_media_failure_keeps_its_reason_in_words() -> None:
    router = FakeRouter([ok_outcome(copy_dict())])
    media = FakeMedia(
        MediaOutcome(
            failure="provider_error",
            detail="La generación no está disponible ahora mismo. Avisa al equipo.",
        )
    )
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice(), media=media)
    brief = make_brief(
        variants=1,
        kind=ContentKind.AVATAR_VIDEO,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(avatar_look_id="lk", voice_id="vo"),
    )
    draft_id = repo.seed_draft(brief)
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    detail = service.get_draft(tenant_id=TENANT_ID, draft_id=draft_id)
    assert detail is not None and detail.failure_reason == "provider_error"
    assert detail.failure_detail == "La generación no está disponible ahora mismo. Avisa al equipo."


# -- the business context reaches the prompt (§ request 2026-10-01) ----------------------


class RecordingRouter(FakeRouter):
    def __init__(self, script: list[object] | None = None) -> None:
        super().__init__(script)
        self.requests: list[object] = []

    def run(self, *, tenant_id, brand_id, chain, request, budget):  # noqa: ANN001, ANN201
        self.requests.append(request)
        return super().run(
            tenant_id=tenant_id, brand_id=brand_id, chain=chain, request=request, budget=budget
        )


class FakeContext:
    def __init__(self, context: object = None, fail: bool = False) -> None:
        self._context = context
        self._fail = fail

    def context(self, *, tenant_id: UUID, brand_id: UUID) -> object:
        if self._fail:
            raise RuntimeError("database down")
        return self._context


def _generate_with(reader: FakeContext) -> RecordingRouter:
    router = RecordingRouter([ok_outcome(copy_dict("Hook uno"))])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    service._context = reader  # the composition passes `context_reader=`
    draft_id = repo.seed_draft(make_brief(variants=1))
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert repo.drafts[draft_id].status == GENERATED
    return router


def test_the_saved_business_context_is_part_of_the_prompt() -> None:
    from qualify_creative.schemas import BrandContext

    context = BrandContext(sector="cafetería", hashtags=("cafe",))
    router = _generate_with(FakeContext(context))
    prefix = router.requests[0].rendered_prompt.stable_prefix  # type: ignore[attr-defined]
    assert "== Business context ==" in prefix and "#cafe" in prefix


def test_an_unreadable_context_never_fails_generation() -> None:
    router = _generate_with(FakeContext(fail=True))
    prefix = router.requests[0].rendered_prompt.stable_prefix  # type: ignore[attr-defined]
    assert "Business context" not in prefix


# -- the costs are printed for auditing (§ request 2026-10-01) ---------------------------


def test_every_call_and_the_draft_total_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    router = FakeRouter([ok_outcome(copy_dict("Hook uno")), ok_outcome(copy_dict("Hook dos"))])
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=2))
    with caplog.at_level(logging.INFO, logger="qualify_api.creative.costs"):
        service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    lines = [r.getMessage() for r in caplog.records if r.name == "qualify_api.creative.costs"]
    calls = [line for line in lines if line.startswith("creative.cost draft=")]
    totals = [line for line in lines if line.startswith("creative.cost.total")]
    assert len(calls) == 2 and len(totals) == 1
    assert f"draft={draft_id}" in calls[0]
    assert "model=claude-opus-5" in calls[0] and "in=1000 out=500" in calls[0]
    assert "cost_usd=0.017500" in calls[0]
    assert "calls=2 cost_usd=0.035000 outcome=ok" in totals[0]


def test_a_failed_generation_still_logs_what_it_spent(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    router = FakeRouter([ok_outcome(copy_dict("Hook uno")), BUDGET_BLOCKED])  # 2nd: no money left
    service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
    draft_id = repo.seed_draft(make_brief(variants=2))
    with caplog.at_level(logging.INFO, logger="qualify_api.creative.costs"):
        service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    totals = [r.getMessage() for r in caplog.records if "creative.cost.total" in r.getMessage()]
    # the first call's money was spent and is accounted for; the outcome says why it failed
    assert len(totals) == 1 and "calls=1 cost_usd=0.017500" in totals[0]
    assert "outcome=ok" not in totals[0]


# ---------------------------------------------------------------------------
# Langfuse (docs/plan-observabilidad-langfuse.md §4): one trace per generation


def test_a_generation_is_one_langfuse_trace_whose_session_is_the_draft() -> None:
    import json as _json

    from qualify_shared import observability

    with observability.capture_spans() as exporter:
        router = FakeRouter([ok_outcome(copy_dict("Hook uno"))])
        service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
        brief = make_brief(variants=1)
        draft_id = repo.seed_draft(brief)
        service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
        observability.flush()

    (root,) = exporter.get_finished_spans()
    attrs = dict(root.attributes)
    assert root.name == f"generar {brief.kind.value}"
    assert attrs["session.id"] == str(draft_id)
    assert set(attrs["langfuse.trace.tags"]) == {brief.kind.value, brief.format.value}
    assert attrs["langfuse.trace.metadata.tenant_id"] == str(TENANT_ID)
    assert _json.loads(attrs["langfuse.observation.input"])["topic"] == brief.topic
    assert repo.drafts[draft_id].status == GENERATED  # tracing changed nothing


def test_a_printed_kind_sends_its_printed_limits_and_a_spoken_one_none() -> None:
    """2026-10-13: the copy adapter holds the answer to the printed hook/CTA limits the
    prompt asks for — the service tells it which, per kind."""
    from qualify_creative.enums import ContentKind

    for kind, expected in (
        (ContentKind.STATIC_FLYER, {"max_lengths": {"hook": 50, "cta": 32}}),
        (ContentKind.CREATOR_SCRIPT, {}),
    ):
        router = FakeRouter([ok_outcome(copy_dict("Hook uno"))])
        service, repo, _ = make_service(router=router, kit=make_kit(), voice=make_voice())
        brief = make_brief(variants=1).model_copy(
            update={"kind": kind, "format": kind.default_format}
        )
        draft_id = repo.seed_draft(brief)
        service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
        (request,) = router.requests
        assert dict(request.params) == expected, kind


# ---------------------------------------------------------------------------
# request_key (ticket 24803289): the same key never creates nor pays a second draft


class KeyedRepository(InMemoryRepository):
    """The in-memory repository with `content_drafts.request_key` and its unique index:
    `race_winner` makes the next keyed insert lose to a concurrent create."""

    def __init__(self) -> None:
        super().__init__()
        self.by_key: dict[UUID, UUID] = {}
        self.race_winner: UUID | None = None

    def draft_id_for_request(self, *, tenant_id: UUID, request_key: UUID) -> UUID | None:
        return self.by_key.get(request_key)

    def insert_brief_and_draft(  # type: ignore[override]
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        brief: ContentBrief,
        voice_profile_version: int,
        pipeline_version: str,
        request_key: UUID | None = None,
    ) -> UUID:
        if request_key is not None and self.race_winner is not None:
            # another call inserted this key between our lookup and our insert
            self.by_key[request_key] = self.race_winner
            raise DuplicateDraftRequest(self.race_winner)
        draft_id = super().insert_brief_and_draft(
            tenant_id=tenant_id,
            user_id=user_id,
            brief=brief,
            voice_profile_version=voice_profile_version,
            pipeline_version=pipeline_version,
        )
        if request_key is not None:
            self.by_key[request_key] = draft_id
        return draft_id


def test_a_request_key_creates_one_draft_and_dispatches_it_once() -> None:
    repo = KeyedRepository()
    service, _, dispatcher = make_service(kit=make_kit(), voice=make_voice(), repo=repo)
    key = uuid4()
    first = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(), user_id=USER_ID, request_key=key
    )
    again = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(), user_id=USER_ID, request_key=key
    )
    assert again == first and len(repo.drafts) == 1
    assert len(dispatcher.calls) == 1  # the paid generation runs once
    assert service.draft_for_request(tenant_id=TENANT_ID, request_key=key) == first
    assert service.draft_for_request(tenant_id=TENANT_ID, request_key=uuid4()) is None


def test_a_concurrent_create_with_the_same_key_returns_the_winner_without_dispatching() -> None:
    repo = KeyedRepository()
    service, _, dispatcher = make_service(kit=make_kit(), voice=make_voice(), repo=repo)
    repo.race_winner = uuid4()
    draft_id = service.create_draft(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        brief=make_brief(),
        user_id=USER_ID,
        request_key=uuid4(),
    )
    assert draft_id == repo.race_winner and dispatcher.calls == []


def test_without_a_key_every_call_is_a_new_draft_as_before() -> None:
    # the plain InMemoryRepository has no notion of keys: callers that send none are
    # untouched by the change
    service, repo, dispatcher = make_service(kit=make_kit(), voice=make_voice())
    for _ in range(2):
        service.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(), user_id=USER_ID
        )
    assert len(repo.drafts) == 2 and len(dispatcher.calls) == 2


# ---------------------------------------------------------------------------
# get_drafts (ticket 24803289, PR 4): N drafts in one repository read


class BatchRepository(InMemoryRepository):
    """The in-memory repository with `details_for`, built from its own single reads so
    a mismatch with `get_draft` can only come from the service."""

    def __init__(self) -> None:
        super().__init__()
        self.batch_calls: list[tuple[UUID, ...]] = []

    def details_for(self, *, tenant_id: UUID, draft_ids: Sequence[UUID]) -> dict[UUID, DraftBundle]:
        self.batch_calls.append(tuple(draft_ids))
        out: dict[UUID, DraftBundle] = {}
        for draft_id in draft_ids:
            record = self.drafts.get(draft_id)
            if record is None:
                continue
            out[draft_id] = DraftBundle(
                record=record,
                variants=self.variants_for(tenant_id=tenant_id, draft_id=draft_id),
                image=self.image_for(tenant_id=tenant_id, draft_id=draft_id),
                media=self.media_for(tenant_id=tenant_id, draft_id=draft_id),
                kind=self.brief_kind(tenant_id=tenant_id, brief_id=record.brief_id),
            )
        return out


def test_get_drafts_equals_get_draft_per_id_in_one_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import qualify_api.creative.service as service_module

    reaped: list[UUID] = []
    monkeypatch.setattr(
        service_module, "reap_stale_drafts", lambda *, tenant_id: reaped.append(tenant_id) or 0
    )
    repo = BatchRepository()
    service, _, _ = make_service(kit=make_kit(), voice=make_voice(), repo=repo)
    ids = [repo.seed_draft(make_brief()) for _ in range(3)]
    unknown = uuid4()
    batch = service.get_drafts(tenant_id=TENANT_ID, draft_ids=[*ids, unknown])
    assert set(batch) == set(ids)  # an id not visible is simply absent
    for draft_id in ids:
        assert batch[draft_id] == service.get_draft(tenant_id=TENANT_ID, draft_id=draft_id)
    assert repo.batch_calls == [(*ids, unknown)]  # ONE repository read for all
    assert reaped == [TENANT_ID]  # stale drafts are failed first, as on listing


def test_get_drafts_of_nothing_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    import qualify_api.creative.service as service_module

    reaped: list[UUID] = []
    monkeypatch.setattr(
        service_module, "reap_stale_drafts", lambda *, tenant_id: reaped.append(tenant_id) or 0
    )
    repo = BatchRepository()
    service, _, _ = make_service(kit=make_kit(), voice=make_voice(), repo=repo)
    assert service.get_drafts(tenant_id=TENANT_ID, draft_ids=[]) == {}
    assert repo.batch_calls == [] and reaped == []
