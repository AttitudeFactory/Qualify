"""VE-08 (m-24921065): a video by parts — the plan from a reel's analysis, the parts as
child drafts charged all or nothing, «Crear otra versión» of one part, and the cap on
the parent's new texts. Offline: the in-memory ledger, a fake router and fake media.
The Postgres side (one transaction, RLS between businesses, the listings) is in
`test_creative_parts_db.py`."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    PART_DESCRIPTION_MAX,
    ContentBrief,
    MediaInputs,
    PartRef,
    VideoPartPlan,
)

from qualify_api.creative.creations import (
    InMemoryCreationsLedger,
    NotEnoughCreations,
    PreviewCharge,
)
from qualify_api.creative.fsm import DRAFTING, GENERATED
from qualify_api.creative.media import MediaOutcome, MediaWrite
from qualify_api.creative.parts import (
    NOTICE_TEXTS,
    PARENT_TEXT_CAP_TEXT,
    PARENT_TEXT_DAILY_CAP,
    ExtendTooShort,
    ParentTextCapReached,
    ParentTextMissing,
    PartChanges,
    PartNeedsDescription,
    PartsOverBudget,
    PartsService,
    PartsUnavailable,
    check_extend_parts,
    clip_description,
    join_unique,
    neutral_people,
    part_label,
    plan_from_analysis,
    product_noun,
)
from qualify_api.creative.service import (
    BudgetState,
    ContentService,
    DraftRecord,
    check_part_link,
)
from qualify_api.referentes.reel_analysis_types import (
    NOT_OBSERVED,
    OBSERVED,
    UNKNOWN,
    AnalysisProvenance,
    ReelAnalysis,
    ShotAnalysis,
)

from .test_content_service import (
    BRAND_ID,
    TENANT_ID,
    USER_ID,
    FakeBrand,
    FakePricing,
    FakeRouter,
    FakeVoice,
    InMemoryRepository,
    RecordingDispatcher,
    StaticKeyResolver,
    copy_dict,
    make_brief,
    make_kit,
    make_voice,
    ok_outcome,
)

FIXTURE = Path(__file__).parent / "fixtures" / "reel_analysis_sample.json"
ANALYSIS_ID = UUID("5e1f0000-0000-4000-8000-0000000000a8")

# ---------------------------------------------------------------------------
# Builders


def _family(value: str | None) -> dict[str, Any]:
    if value is None:
        return {"status": UNKNOWN, "value": "", "evidence_frames": []}
    return {"status": OBSERVED, "value": value, "evidence_frames": ["00-0"]}


def shot(
    index: int,
    start: float,
    end: float,
    *,
    people: str = NOT_OBSERVED,
    faces: str = NOT_OBSERVED,
    subject: str | None = "producto en primer plano",
    spoken: str = "",
    product: str | None = None,
) -> ShotAnalysis:
    families = {"subject": _family(subject)}
    if product is not None:
        families["product"] = _family(product)
    return ShotAnalysis(
        shot_index=index,
        start_s=start,
        end_s=end,
        people_presence=people,
        visible_faces=faces,
        families=families,
        spoken_text=spoken,
    )


def analysis(
    *shots: ShotAnalysis,
    width: int = 720,
    height: int = 1280,
    reel_sheet: dict[str, Any] | None = None,
) -> ReelAnalysis:
    return ReelAnalysis(
        id=ANALYSIS_ID,
        network="instagram",
        post_id="p1",
        analysis_version=6,
        post_url="https://www.instagram.com/reel/p1/",
        source_seconds=shots[-1].end_s if shots else 0.0,
        width=width,
        height=height,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=shots[-1].end_s if shots else 0.0,
        edit_eligible=True,
        source_available=True,
        transcript_text="",
        transcript_segments=(),
        transcript_source="none",
        reel_sheet=reel_sheet or {},
        shots=tuple(shots),
        provenance=AnalysisProvenance(
            model_id="claude-haiku-5-5",
            model_revision=None,
            prompt_version="reel-sheet-prompt-7",
            schema_version="reel-sheet-schema-3",
            detector_version="d1",
            sampling_version="s1",
            sampling_params={},
            source_sha256="0" * 64,
        ),
        finished_at=datetime(2026, 11, 5, tzinfo=UTC),
    )


def parent_brief(*parts: VideoPartPlan, **media: Any) -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.SHOT_VIDEO,
        format=ContentFormat.REELS_9_16,
        topic="Smash burger doble",
        media=MediaInputs(parts=parts, product_keys=("uploads/t/burger.jpg",), **media),
    )


FOUR_PARTS = (
    VideoPartPlan(seconds=5, description="La hamburguesa sobre la mesa."),
    VideoPartPlan(seconds=4, description="Manos que sirven papas."),
    VideoPartPlan(seconds=6, description="Una persona muerde la hamburguesa y sonríe."),
    VideoPartPlan(seconds=3, description="El logo del local."),
)

VIDEO = MediaWrite(
    position=0,
    media_type="video",
    media_url="generated/t/d/part.mp4",
    object_key="generated/t/d/part.mp4",
    width=480,
    height=854,
    aspect_ratio="9:16",
    model_id="seedance-2-5",
    provider="byteplus",
)


class PartsRepository(InMemoryRepository):
    """The in-memory repository with what parts need: chosen ids, the parent link, a
    brief per version and the count of a parent's new texts."""

    def __init__(self) -> None:
        super().__init__()
        self.versions: list[tuple[UUID, int, UUID]] = []  # (draft, revision, brief)
        self.parent_texts = 0

    def insert_brief_and_draft(  # type: ignore[override]
        self,
        *,
        tenant_id,  # noqa: ANN001
        user_id,  # noqa: ANN001
        brief,  # noqa: ANN001
        voice_profile_version,  # noqa: ANN001
        pipeline_version,  # noqa: ANN001
        request_key=None,  # noqa: ANN001
        draft_id=None,  # noqa: ANN001
        parent_draft_id=None,  # noqa: ANN001
        part_index=None,  # noqa: ANN001
    ):  # noqa: ANN201
        check_part_link(brief, parent_draft_id, part_index)
        made = super().insert_brief_and_draft(
            tenant_id=tenant_id,
            user_id=user_id,
            brief=brief,
            voice_profile_version=voice_profile_version,
            pipeline_version=pipeline_version,
        )
        record = replace(
            self.drafts.pop(made),
            id=draft_id or made,
            parent_draft_id=parent_draft_id,
            part_index=part_index,
        )
        self.drafts[record.id] = record
        return record.id

    def finish_generation(self, **kwargs):  # noqa: ANN003, ANN201
        before = self.drafts[kwargs["draft_id"]]
        super().finish_generation(**kwargs)
        after = self.drafts[kwargs["draft_id"]]
        if before.status == DRAFTING and after.status == GENERATED:
            self.versions.append((after.id, after.revision, after.brief_id))

    def list_drafts(self, *, tenant_id, brand_id, status, limit, offset):  # noqa: ANN001, ANN201
        rows = super().list_drafts(
            tenant_id=tenant_id, brand_id=brand_id, status=status, limit=limit, offset=offset
        )
        return tuple(d for d in rows if d.parent_draft_id is None)

    def parts_of(self, *, tenant_id, parent_id):  # noqa: ANN001, ANN201
        removed = getattr(self, "removed", {})
        rows = [
            d
            for d in self.drafts.values()
            if d.parent_draft_id == parent_id and d.id not in removed
        ]
        return tuple(sorted(rows, key=lambda d: d.part_index or 0))

    def removed_part_indexes(self, *, tenant_id, parent_id):  # noqa: ANN001, ANN201
        removed = getattr(self, "removed", {})
        return frozenset(
            int(d.part_index or 0)
            for d in self.drafts.values()
            if d.parent_draft_id == parent_id and d.id in removed
        )

    def mark_part_removed(self, *, tenant_id, draft_id, user_id):  # noqa: ANN001, ANN201
        """m-24985192: the mark, kept beside the record (who removed it)."""
        if not hasattr(self, "removed"):
            self.removed = {}
        if draft_id in self.removed:
            return False
        self.removed[draft_id] = user_id
        return True

    def replace_brief(self, *, tenant_id, draft_id, user_id, brief):  # noqa: ANN001, ANN201
        draft = self.drafts[draft_id]
        check_part_link(brief, draft.parent_draft_id, draft.part_index)
        brief_id = uuid4()
        self.briefs[brief_id] = brief
        self.drafts[draft_id] = replace(draft, brief_id=brief_id)
        return brief_id

    def parent_texts_regenerated_today(self, *, tenant_id):  # noqa: ANN001, ANN201
        return self.parent_texts


class PartsMedia:
    """The producer double: a parent makes no media, a part makes its 480p preview."""

    def __init__(self) -> None:
        self.calls: list[ContentBrief] = []

    def produce(self, *, brief, **_):  # noqa: ANN001, ANN003, ANN201
        self.calls.append(brief)
        if brief.kind.is_parts_parent:
            return MediaOutcome()
        return MediaOutcome(media=(VIDEO,))


def world(
    *,
    previews_used: int = 0,
    plan: tuple[VideoPartPlan, ...] = FOUR_PARTS,
    media: dict[str, Any] | None = None,
) -> tuple[
    PartsService,
    ContentService,
    PartsRepository,
    InMemoryCreationsLedger,
    RecordingDispatcher,
    FakeRouter,
    UUID,
]:
    """A parent of `plan` with its text made (one Claude call), ready for its parts."""
    repo = PartsRepository()
    ledger = InMemoryCreationsLedger(previews_used=previews_used)
    router = FakeRouter([ok_outcome(copy_dict())])
    dispatcher = RecordingDispatcher()
    content = ContentService(
        router=router,  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
        dispatcher=dispatcher,
        media=PartsMedia(),  # type: ignore[arg-type]
        creations=ledger,
    )
    parent = content.create_draft(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        brief=parent_brief(*plan, **(media or {})),
        user_id=USER_ID,
    )
    content.run_generation(tenant_id=TENANT_ID, draft_id=parent)
    assert repo.drafts[parent].status == GENERATED
    dispatcher.calls.clear()
    parts = PartsService(content, require_queue=lambda: True)
    return parts, content, repo, ledger, dispatcher, router, parent


def _children(repo: PartsRepository, parent: UUID) -> list[DraftRecord]:
    return list(repo.parts_of(tenant_id=TENANT_ID, parent_id=parent))


def _part_rows(ledger: InMemoryCreationsLedger, ids: list[UUID]) -> dict[tuple[UUID, int], Any]:
    return {key: row for key, row in ledger.rows.items() if key[0] in ids}


# ---------------------------------------------------------------------------
# plan_from_analysis (pure)


def test_edit_only_where_nobody_is_seen_and_people_unknown_is_made_new() -> None:
    plan = plan_from_analysis(
        analysis(
            shot(0, 0.0, 5.0),
            shot(1, 5.0, 10.0, people=OBSERVED, faces=NOT_OBSERVED, subject="manos sirviendo"),
            shot(2, 10.0, 15.0, people=UNKNOWN, faces=UNKNOWN),
        )
    )
    assert [p.mode for p in plan] == ["edit", "reference", "reference"]
    assert [p.notices for p in plan] == [(), (), ("people_unclear",)]
    assert all(p.analysis_id == ANALYSIS_ID for p in plan)


def test_a_source_that_is_not_vertical_is_always_made_new() -> None:
    plan = plan_from_analysis(analysis(shot(0, 0.0, 5.0), width=1080, height=1080))
    assert [p.mode for p in plan] == ["reference"]


def test_short_cuts_join_up_to_ten_seconds_never_across_the_edit_line() -> None:
    plan = plan_from_analysis(
        analysis(
            shot(0, 0.0, 1.5),
            shot(1, 1.5, 3.0),
            shot(2, 3.0, 6.0),
            shot(3, 6.0, 7.5, people=OBSERVED, faces=OBSERVED),
            shot(4, 7.5, 9.0, people=OBSERVED, faces=OBSERVED),
            shot(5, 9.0, 12.0, people=OBSERVED, faces=OBSERVED),
        )
    )
    assert [p.shot_indexes for p in plan] == [(0, 1, 2), (3, 4, 5)]
    assert [(p.mode, p.seconds) for p in plan] == [("edit", 6), ("reference", 6)]


def test_never_more_than_six_parts() -> None:
    shots = [shot(i, i * 4.5, (i + 1) * 4.5) for i in range(12)]
    plan = plan_from_analysis(analysis(*shots))
    assert len(plan) == 6
    assert all(1 <= p.seconds <= 10 for p in plan)
    # the plan is a valid parent: it validates as a video by parts
    parent_brief(*plan)


def test_a_cut_over_ten_seconds_is_split_and_continued() -> None:
    plan = plan_from_analysis(analysis(shot(0, 0.0, 3.0), shot(1, 3.0, 17.0), shot(2, 17.0, 42.0)))
    assert [(p.mode, p.seconds, p.shot_indexes) for p in plan] == [
        ("edit", 3, (0,)),
        ("edit", 7, (1,)),
        ("extend", 7, (1,)),
        ("edit", 9, (2,)),
        ("extend", 8, (2,)),
        ("extend", 8, (2,)),
    ]
    check_extend_parts(plan, analysis(shot(0, 0.0, 3.0), shot(1, 3.0, 17.0), shot(2, 17.0, 42.0)))
    parent_brief(*plan)


def test_someone_talks_to_the_camera_only_with_speech_and_a_face() -> None:
    plan = plan_from_analysis(
        analysis(
            shot(0, 0.0, 5.0, people=OBSERVED, faces=OBSERVED, spoken="Pruébala hoy"),
            shot(1, 5.0, 10.0, people=OBSERVED, faces=NOT_OBSERVED, spoken="Pruébala hoy"),
            shot(2, 10.0, 15.0, people=OBSERVED, faces=OBSERVED),
        )
    )
    assert [p.talks_to_camera for p in plan] == [True, False, False]


def test_a_cut_the_analysis_could_not_see_asks_the_owner_to_describe_it() -> None:
    (part,) = plan_from_analysis(analysis(shot(0, 0.0, 5.0, subject=None)))
    assert part.description == "" and part.notices == ("describe_it",)
    assert NOTICE_TEXTS["describe_it"] == (
        "No pudimos ver qué pasa en esta parte. Cuéntanos en una frase qué quieres que muestre."
    )
    assert NOTICE_TEXTS["people_unclear"] == (
        "No pudimos ver bien si en esta parte aparece alguien. "
        "La crearemos de cero con las fotos de tu producto."
    )


def test_descriptions_never_assume_age_nor_gender() -> None:
    (part,) = plan_from_analysis(
        analysis(
            shot(
                0,
                0.0,
                5.0,
                people=OBSERVED,
                faces=OBSERVED,
                subject="un hombre joven muerde el producto y sonríe",
            )
        ),
        products=("la hamburguesa",),
    )
    assert part.description == "Una persona muerde la hamburguesa y sonríe."
    assert neutral_people("dos mujeres y la chica señalan") == "dos personas y la persona señalan"


def test_a_part_never_repeats_a_consecutive_cut() -> None:
    (part,) = plan_from_analysis(
        analysis(
            *(
                shot(i, float(i), i + 1.0, subject="una persona presenta y prueba sliders")
                for i in range(4)
            )
        )
    )
    assert part.shot_indexes == (0, 1, 2, 3)
    assert part.description == "Una persona presenta y prueba sliders."


def test_a_part_never_repeats_a_cut_seen_earlier() -> None:
    (part,) = plan_from_analysis(
        analysis(
            shot(0, 0.0, 2.0, subject="filetes de pescado sobre rejilla; luego harina"),
            shot(1, 2.0, 4.0, subject="manos sirviendo"),
            shot(2, 4.0, 6.0, subject="filetes de pescado sobre rejilla; luego harina"),
        )
    )
    assert part.description == "Filetes de pescado sobre rejilla; luego harina. Manos sirviendo."


def test_a_repeat_that_differs_only_in_case_spaces_or_final_period_is_dropped() -> None:
    (part,) = plan_from_analysis(
        analysis(
            shot(0, 0.0, 2.0, subject="Manos  sirviendo el plato"),
            shot(1, 2.0, 4.0, subject="manos sirviendo el PLATO."),
            shot(2, 4.0, 6.0, subject="  MANOS sirviendo   el plato  "),
        )
    )
    assert part.description == "Manos  sirviendo el plato."


def test_a_cut_is_only_left_out_whole_so_no_word_is_lost() -> None:
    texts = ["Llega al Edif. Central.", "Sale del Edif. Central."]
    assert join_unique(texts) == "Llega al Edif. Central. Sale del Edif. Central."
    assert join_unique(["Manos sirviendo.", "Primer plano del plato. Manos sirviendo."]) == (
        "Manos sirviendo. Primer plano del plato. Manos sirviendo."
    )
    assert join_unique(["", "  ", "Manos sirviendo"]) == "Manos sirviendo"


def test_a_part_without_repeats_keeps_its_description() -> None:
    (part,) = plan_from_analysis(
        analysis(
            shot(0, 0.0, 1.0, subject="filetes sobre rejilla"),
            shot(1, 1.0, 2.0, subject="harina en un plato"),
            shot(2, 2.0, 3.0, subject=None),
            shot(3, 3.0, 4.0, subject="manos sirviendo"),
        )
    )
    assert part.description == "Filetes sobre rejilla. Harina en un plato. Manos sirviendo."


def test_the_description_is_cut_to_its_maximum_after_the_repeats_go() -> None:
    long_subject = "plano " + "muy " * 160 + "largo"
    (part,) = plan_from_analysis(
        analysis(
            shot(0, 0.0, 2.0, subject=long_subject),
            shot(1, 2.0, 4.0, subject=long_subject),
            shot(2, 4.0, 6.0, subject="manos sirviendo"),
        )
    )
    expected = "Plano " + "muy " * 160 + "largo. Manos sirviendo."
    assert len(expected) > PART_DESCRIPTION_MAX
    assert len(part.description) <= PART_DESCRIPTION_MAX
    assert expected.startswith(part.description) and part.description.endswith(" muy")
    assert part.description.count("Plano muy") == 1


def test_the_description_is_cut_after_its_last_whole_sentence_that_fits() -> None:
    text_ = "Manos sirven el plato. Una persona come. " + "Plano largo " * 60
    assert clip_description(text_, limit=60) == "Manos sirven el plato. Una persona come."
    assert clip_description("corto", limit=60) == "corto"
    assert clip_description("palabra " * 20, limit=30) == "palabra palabra palabra"
    # a sentence that keeps almost nothing loses to the last whole word
    assert clip_description("Ok. " + "palabra " * 100, limit=60).startswith("Ok. palabra")


# ---------------------------------------------------------------------------
# m-24992913: the reel's own product named in a description becomes the owner's

SLIDERS = "Sliders de pescado rebozado con salsa"


def _noun(value: str) -> str | None:
    found = product_noun(value)
    return found.noun if found else None


def test_the_reel_product_noun_is_the_first_noun_of_its_product_value() -> None:
    found = product_noun(SLIDERS)
    assert found is not None and found.noun == "sliders"
    assert found.phrase_words == {"pescado", "rebozado"}  # «con salsa» is not the noun
    assert _noun("Dos hamburguesas dobles") == "hamburguesas"
    assert _noun("Vaso de batido de fresa") == "batido"
    assert _noun("Bolsillo de la chaqueta") == "chaqueta"
    # an ingredient list, a bare container, a generic word or nothing name no product
    assert _noun("Pan, queso, pescado frito, salsa") is None
    assert _noun("Vaso blanco") is None
    assert _noun("Logo de la marca") is None
    assert _noun("") is None
    assert _noun("Pan; queso; pescado") is None  # a list with «;» too
    # an opening adjective or a person is never the product noun
    assert _noun("Deliciosa hamburguesa doble") == "hamburguesa"
    assert _noun("Mujer con vestido rojo") == "vestido"
    assert _noun("Mujer sonriente") is None


def test_an_adjective_or_a_person_never_becomes_the_owners_product() -> None:
    plan = plan_from_analysis(
        analysis(
            shot(
                0,
                0.0,
                5.0,
                subject="Una deliciosa ensalada y otra deliciosa sopa",
                product="Deliciosa hamburguesa doble",
            ),
            shot(1, 5.0, 10.0, subject="Una mujer camina con vestido rojo", product="Mujer"),
        ),
        products=("super smash",),
    )
    assert [p.description for p in plan] == [
        "Una deliciosa ensalada y otra deliciosa sopa.",
        "Una persona camina con vestido rojo.",
    ]
    (part,) = plan_from_analysis(
        analysis(
            shot(
                0,
                0.0,
                5.0,
                subject="Una mujer camina con vestido rojo",
                product="Mujer con vestido rojo",
            )
        ),
        products=("Pizza",),
    )
    assert part.description == "Una persona camina con Pizza."


def test_the_reels_product_becomes_the_owners_in_every_cut_whose_product_names_it() -> None:
    plan = plan_from_analysis(
        analysis(
            shot(
                0, 0.0, 5.0, subject="Hombre presenta y prueba sliders de pescado", product=SLIDERS
            ),
            shot(1, 5.0, 10.0, subject="Manos cierran el slider y pincelan", product="Slider"),
            shot(2, 10.0, 15.0, subject="Primer plano de los sliders de pescado", product=SLIDERS),
            shot(3, 15.0, 20.0, subject="Sliders de pescado en bandeja", product="Sliders"),
            shot(4, 20.0, 25.0, subject="Muerde un slider con salsa", product="Slider y salsa"),
        ),
        products=("super smash",),
    )
    assert [p.description for p in plan] == [
        "Una persona presenta y prueba super smash.",
        "Manos cierran super smash y pincelan.",
        "Primer plano de super smash.",
        "Super smash en bandeja.",
        "Muerde super smash con salsa.",
    ]


def test_a_cut_that_names_no_product_keeps_its_text() -> None:
    plan = plan_from_analysis(
        analysis(
            shot(0, 0.0, 5.0, subject="Una persona prueba sliders", product=SLIDERS),
            shot(1, 5.0, 10.0, subject="Una persona señala los sliders"),
            shot(2, 10.0, 15.0, subject="Manos arman el slider", product="Pan y queso"),
        ),
        products=("super smash",),
    )
    assert [p.description for p in plan] == [
        "Una persona prueba super smash.",
        "Una persona señala los sliders.",
        "Manos arman el slider.",
    ]


def test_without_an_owner_product_or_a_reel_product_nothing_changes() -> None:
    reel = analysis(shot(0, 0.0, 5.0, subject="Una persona prueba sliders", product=SLIDERS))
    (part,) = plan_from_analysis(reel)
    assert part.description == "Una persona prueba sliders."
    listed = analysis(
        shot(0, 0.0, 5.0, subject="Manos arman el slider", product="Pan, queso, pescado, salsa")
    )
    (part,) = plan_from_analysis(listed, products=("super smash",))
    assert part.description == "Manos arman el slider."


def test_a_recipes_ingredients_are_not_the_reels_product() -> None:
    """Each cut's own product is NOT replaced: in a recipe they are the ingredients."""
    plan = plan_from_analysis(
        analysis(
            shot(0, 0.0, 5.0, subject="Una persona prueba sliders de pescado", product=SLIDERS),
            shot(1, 5.0, 10.0, subject="Manos cascan huevo y añaden agua", product="Huevo y agua"),
            shot(2, 10.0, 15.0, subject="Filetes de pescado sobre rejilla", product="Filetes"),
        ),
        products=("super smash",),
    )
    assert [p.description for p in plan] == [
        "Una persona prueba super smash.",
        "Manos cascan huevo y añaden agua.",
        "Filetes de pescado sobre rejilla.",
    ]


def test_the_hook_cut_names_the_reels_product_before_the_first_cut() -> None:
    reel = analysis(
        shot(0, 0.0, 5.0, subject="Manos pelan papas", product="Papas"),
        shot(1, 5.0, 10.0, subject="Una persona muerde las hamburguesas", product="Hamburguesas"),
        reel_sheet={"hook": {"shot": 1, "status": OBSERVED, "value": "Muerde"}},
    )
    plan = plan_from_analysis(reel, products=("Pollo Crispy",))
    assert [p.description for p in plan] == [
        "Manos pelan papas.",
        "Una persona muerde Pollo Crispy.",
    ]


def test_the_sample_analysis_makes_a_valid_plan() -> None:
    sample = ReelAnalysis.from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))
    plan = plan_from_analysis(sample)
    assert 1 <= len(plan) <= 6
    assert all(p.mode != "edit" or not p.notices for p in plan)
    parent_brief(*plan)


# ---------------------------------------------------------------------------
# Criterion 8: «Sigue a la anterior» on a shared cut only past 10 s


def _extend_plan(seconds_of_cut: float) -> tuple[ReelAnalysis, tuple[VideoPartPlan, ...]]:
    reel = analysis(shot(0, 0.0, seconds_of_cut))
    plan = (
        VideoPartPlan(mode="reference", seconds=5, analysis_id=ANALYSIS_ID, shot_indexes=(0,)),
        VideoPartPlan(mode="extend", seconds=5, analysis_id=ANALYSIS_ID, shot_indexes=(0,)),
    )
    return reel, plan


def test_an_extend_on_a_cut_over_ten_seconds_is_accepted() -> None:
    reel, plan = _extend_plan(10.5)
    check_extend_parts(plan, reel)


@pytest.mark.parametrize("seconds", [6.0, 10.0])
def test_an_extend_on_a_cut_of_ten_seconds_or_less_is_refused(seconds: float) -> None:
    reel, plan = _extend_plan(seconds)
    with pytest.raises(ExtendTooShort):
        check_extend_parts(plan, reel)


def test_an_extend_on_a_cut_without_its_analysis_is_refused() -> None:
    _, plan = _extend_plan(12.0)
    with pytest.raises(ExtendTooShort):
        check_extend_parts(plan, None)


def test_an_extend_without_cuts_continues_freely() -> None:
    check_extend_parts((VideoPartPlan(seconds=5), VideoPartPlan(mode="extend", seconds=5)), None)


def test_create_parts_refuses_a_short_shared_cut_before_anything_exists() -> None:
    reel, plan = _extend_plan(8.0)
    parts, _, repo, ledger, dispatcher, _, parent = world(plan=plan)
    rows = dict(ledger.rows)
    with pytest.raises(ExtendTooShort):
        parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, analysis=reel)
    assert _children(repo, parent) == [] and ledger.rows == rows and dispatcher.calls == []


# ---------------------------------------------------------------------------
# charge_many on the in-memory ledger


def _charges(n: int) -> list[PreviewCharge]:
    from qualify_creative.creations import CreationPrice

    return [
        PreviewCharge(uuid4(), 1, CreationPrice("generated_video", 0, videos=1, video_seconds=5))
        for _ in range(n)
    ]


def test_charge_many_is_all_or_nothing_in_memory() -> None:
    ledger = InMemoryCreationsLedger(previews_used=17)  # 3 of 20 left
    with pytest.raises(NotEnoughCreations) as refused:
        ledger.charge_many(tenant_id=TENANT_ID, brand_id=BRAND_ID, charges=_charges(4))
    assert refused.value.missing_previews == 1
    assert ledger.rows == {}
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_left == 3


def test_charge_many_charges_as_charge_would_and_skips_what_was_charged() -> None:
    ledger = InMemoryCreationsLedger()
    one_by_one = InMemoryCreationsLedger()
    charges = _charges(4)
    ids = ledger.charge_many(tenant_id=TENANT_ID, brand_id=BRAND_ID, charges=charges)
    for c in charges:
        one_by_one.charge(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            draft_id=c.draft_id,
            revision=c.revision,
            price=c.price,
        )
    assert len(ids) == 4
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID) == one_by_one.balance(
        tenant_id=TENANT_ID, brand_id=BRAND_ID
    )
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used == 4
    # seconds of video are charged at approval (VE-10b), never at creation
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).videos_used == 0
    assert ledger.charge_many(tenant_id=TENANT_ID, brand_id=BRAND_ID, charges=charges) == []
    assert len(ledger.rows) == 4


# ---------------------------------------------------------------------------
# Criteria 1 and 2: creating the parts


def test_criterion_1_three_free_previews_and_four_parts_make_nothing() -> None:
    parts, _, repo, ledger, dispatcher, _, parent = world(previews_used=17)
    rows = dict(ledger.rows)
    drafts = set(repo.drafts)
    with pytest.raises(NotEnoughCreations):
        parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    assert set(repo.drafts) == drafts and _children(repo, parent) == []
    assert ledger.rows == rows  # nothing charged
    assert dispatcher.calls == []


def test_criterion_2_four_parts_four_previews_four_jobs_no_claude() -> None:
    parts, content, repo, ledger, dispatcher, router, parent = world()
    claude_calls = len(router.requests)
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)

    children = _children(repo, parent)
    assert [c.id for c in children] == ids and [c.part_index for c in children] == [1, 2, 3, 4]
    rows = _part_rows(ledger, ids)
    assert sorted(rows) == sorted((child, 1) for child in ids)
    assert all(row.price.videos == 1 and row.price.weight == 0 for row in rows.values())
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used == 4
    assert dispatcher.calls == [(TENANT_ID, child) for child in ids]

    for child in ids:
        content.run_generation(tenant_id=TENANT_ID, draft_id=child)
    assert len(router.requests) == claude_calls  # 0 calls to Claude for the parts
    parent_text = repo.variants_for(tenant_id=TENANT_ID, draft_id=parent)[0].copy
    for child in ids:
        assert repo.drafts[child].status == GENERATED
        (variant,) = repo.variants_for(tenant_id=TENANT_ID, draft_id=child)
        assert variant.copy == parent_text
    briefs = [repo.briefs[c.brief_id] for c in children]
    assert [b.kind for b in briefs] == [ContentKind.CLIP] * 4
    assert [b.media.duration_seconds for b in briefs] == [5, 4, 6, 4]  # 3 s → made at 4
    assert [b.media.part.description for b in briefs if b.media.part] == [
        p.description for p in FOUR_PARTS
    ]
    assert all(b.media.clip_image_keys == ("uploads/t/burger.jpg",) for b in briefs)


def test_creating_the_parts_again_returns_them_and_charges_nothing() -> None:
    parts, _, repo, ledger, dispatcher, _, parent = world()
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    rows, calls = dict(ledger.rows), list(dispatcher.calls)
    again = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    assert again == ids and ledger.rows == rows and dispatcher.calls == calls
    assert len(_children(repo, parent)) == 4


def test_parts_need_the_queue() -> None:
    parts, content, repo, ledger, _, _, parent = world()
    rows = dict(ledger.rows)
    with pytest.raises(PartsUnavailable):
        PartsService(content, require_queue=lambda: False).create_parts(
            tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID
        )
    assert _children(repo, parent) == [] and ledger.rows == rows


def test_parts_need_the_parents_text() -> None:
    parts, _, repo, ledger, _, _, parent = world()
    repo.drafts[parent] = replace(repo.drafts[parent], status=DRAFTING)
    with pytest.raises(ParentTextMissing):
        parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    assert _children(repo, parent) == []


def test_a_part_to_describe_waits_for_its_description() -> None:
    plan = (VideoPartPlan(seconds=5, notices=("describe_it",)), VideoPartPlan(seconds=5))
    parts, _, repo, _, _, _, parent = world(plan=plan)
    with pytest.raises(PartNeedsDescription) as refused:
        parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    assert refused.value.text == "Antes de crear la parte 1, cuéntanos qué quieres que muestre."
    assert _children(repo, parent) == []


def test_the_dollar_cap_is_checked_once_on_the_estimated_total() -> None:
    parts, _, repo, ledger, dispatcher, _, parent = world()
    rows = dict(ledger.rows)
    repo.budget = BudgetState(remaining_usd=Decimal("5"), hard_stop=True)
    with pytest.raises(PartsOverBudget) as refused:
        parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    assert refused.value.estimated_usd > Decimal("5")
    assert _children(repo, parent) == [] and ledger.rows == rows and dispatcher.calls == []
    # a soft cap only warns: the team's spend is checked again per call by the router
    repo.budget = BudgetState(remaining_usd=Decimal("5"), hard_stop=False)
    assert len(parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)) == 4


def test_the_parent_shows_part_n_of_m() -> None:
    parts, _, _, _, _, _, parent = world()
    planned = parts.parts(tenant_id=TENANT_ID, parent_id=parent)
    assert [p.status for p in planned] == ["planned"] * 4
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    made = parts.parts(tenant_id=TENANT_ID, parent_id=parent)
    assert [p.label for p in made] == [
        "Parte 1 de 4",
        "Parte 2 de 4",
        "Parte 3 de 4",
        "Parte 4 de 4",
    ]
    assert [p.draft_id for p in made] == ids and part_label(2, 4) == "Parte 2 de 4"
    assert made[2].description == "Una persona muerde la hamburguesa y sonríe."


# ---------------------------------------------------------------------------
# Criterion 3: «Crear otra versión» of part 2


def test_criterion_3_another_version_of_part_2() -> None:
    parts, content, repo, ledger, dispatcher, router, parent = world()
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    for child in ids:
        content.run_generation(tenant_id=TENANT_ID, draft_id=child)
    before = {c.id: c for c in _children(repo, parent)}
    first_brief = before[ids[1]].brief_id
    previews = ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used
    dispatcher.calls.clear()

    child = parts.regenerate_part(
        tenant_id=TENANT_ID,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(
            description="Papas recién fritas.", photo_keys=("uploads/t/papas.jpg",)
        ),
        user_id=USER_ID,
    )

    assert child == ids[1]
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used == previews + 1
    assert (child, 2) in ledger.rows and ledger.rows[(child, 2)].price.videos == 1
    assert dispatcher.calls == [(TENANT_ID, child)]
    after = {c.id: c for c in _children(repo, parent)}
    for sibling in (ids[0], ids[2], ids[3]):
        assert after[sibling] == before[sibling]  # untouched
    new_brief = repo.briefs[after[child].brief_id]
    assert after[child].brief_id != first_brief and after[child].revision == 2
    assert new_brief.media.part is not None and new_brief.media.part.mode == "reference"
    assert new_brief.media.part.description == "Papas recién fritas."
    assert new_brief.media.clip_image_keys == ("uploads/t/papas.jpg",)

    content.run_generation(tenant_id=TENANT_ID, draft_id=child)
    versions = [(rev, brief) for draft, rev, brief in repo.versions if draft == child]
    assert versions == [(1, first_brief), (2, after[child].brief_id)]
    old = repo.briefs[first_brief].media.part
    assert old is not None and old.description == "Manos que sirven papas."  # v1 keeps it
    assert len(router.requests) == 1  # only the parent's text ever asked Claude


def test_another_version_names_the_part_it_redoes() -> None:
    parts, content, _repo, _ledger, _dispatcher, _router, parent = world()
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    for child in ids:
        content.run_generation(tenant_id=TENANT_ID, draft_id=child)
    reasons: list[str] = []
    real_reject = content.reject

    def spy(**kwargs: Any) -> Any:
        reasons.append(kwargs["reason"])
        return real_reject(**kwargs)

    content.reject = spy  # type: ignore[method-assign]
    parts.regenerate_part(
        tenant_id=TENANT_ID,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Papas recién fritas."),
        user_id=USER_ID,
    )

    assert reasons == ["Pediste otra versión de la parte 2"]


def test_another_version_without_previews_left_changes_nothing() -> None:
    parts, content, repo, ledger, _, _, parent = world(previews_used=16)
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    for child in ids:
        content.run_generation(tenant_id=TENANT_ID, draft_id=child)
    rows = dict(ledger.rows)
    before = repo.drafts[ids[1]]
    with pytest.raises(NotEnoughCreations):
        parts.regenerate_part(
            tenant_id=TENANT_ID,
            parent_id=parent,
            part_index=2,
            changes=PartChanges(description="Otra cosa."),
            user_id=USER_ID,
        )
    assert ledger.rows == rows and repo.drafts[ids[1]].revision == before.revision


# ---------------------------------------------------------------------------
# Criterion 6: a part has its parent, and only a part has one


def test_criterion_6_the_part_and_its_parent_go_together() -> None:
    part = make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(part=PartRef(index=2, seconds=5), duration_seconds=5),
    )
    loose = make_brief()
    parent = uuid4()
    check_part_link(part, parent, 2)
    check_part_link(loose, None, None)
    for brief, parent_id, index in (
        (part, None, None),  # a part without its parent
        (part, parent, None),
        (loose, parent, 1),  # a parent for a piece that is not a part
        (part, parent, 3),  # the plan's place disagrees with the draft's
    ):
        with pytest.raises(ValueError):
            check_part_link(brief, parent_id, index)


def test_criterion_6_create_draft_never_makes_a_loose_part() -> None:
    _, content, repo, _, _, _, _ = world()
    drafts = set(repo.drafts)
    part = make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(part=PartRef(index=1, seconds=5), duration_seconds=5),
    )
    with pytest.raises(ValueError):
        content.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=part, user_id=USER_ID)
    assert set(repo.drafts) == drafts


# ---------------------------------------------------------------------------
# Criterion 7: the parent's new texts are capped per business per day


def test_criterion_7_the_parents_new_texts_are_capped() -> None:
    _, content, repo, ledger, dispatcher, router, parent = world()
    router.script.append(ok_outcome(copy_dict("Otro hook")))
    repo.parent_texts = PARENT_TEXT_DAILY_CAP - 1
    content.reject(
        tenant_id=TENANT_ID, draft_id=parent, reason="otro", user_id=USER_ID, regenerate=True
    )
    content.run_generation(tenant_id=TENANT_ID, draft_id=parent)
    assert repo.drafts[parent].revision == 2

    repo.parent_texts = PARENT_TEXT_DAILY_CAP
    rows, calls = dict(ledger.rows), list(dispatcher.calls)
    with pytest.raises(ParentTextCapReached) as refused:
        content.reject(
            tenant_id=TENANT_ID, draft_id=parent, reason="otro", user_id=USER_ID, regenerate=True
        )
    assert str(refused.value) == PARENT_TEXT_CAP_TEXT
    assert PARENT_TEXT_CAP_TEXT == (
        "Hoy ya pediste 20 textos nuevos para tu negocio. Mañana puedes pedir otros 20."
    )
    assert repo.drafts[parent].revision == 2 and repo.drafts[parent].status == GENERATED
    assert ledger.rows == rows and dispatcher.calls == calls


def test_the_cap_is_only_for_the_parents_text() -> None:
    _, content, repo, _, _, router, _ = world()
    repo.parent_texts = PARENT_TEXT_DAILY_CAP
    router.script.extend([ok_outcome(copy_dict()), ok_outcome(copy_dict("Otro"))])
    flyer = repo.seed_draft(make_brief(variants=1))
    content.run_generation(tenant_id=TENANT_ID, draft_id=flyer)
    content.reject(
        tenant_id=TENANT_ID, draft_id=flyer, reason="otro", user_id=USER_ID, regenerate=True
    )
    assert repo.drafts[flyer].revision == 2


def test_a_part_carries_the_selected_text_of_its_parent() -> None:
    parts, content, repo, _, _, _, parent = world()
    (variant,) = repo.variants_for(tenant_id=TENANT_ID, draft_id=parent)
    repo.set_edited_copy(
        tenant_id=TENANT_ID, variant_id=variant.id, edited_copy={"hook": "Hook del dueño"}
    )
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    content.run_generation(tenant_id=TENANT_ID, draft_id=ids[0])
    (inherited,) = repo.variants_for(tenant_id=TENANT_ID, draft_id=ids[0])
    assert inherited.copy["hook"] == "Hook del dueño"
    assert inherited.fidelity["inherited_from"] == str(variant.id)


def test_the_morning_mail_never_lists_a_part() -> None:
    """Criterion 5 for «el correo»: both of its queries leave the parts out (the rest of
    the listings are proven against Postgres in `test_creative_parts_db.py`)."""
    import inspect

    from qualify_api.mail import final_summary

    assert inspect.getsource(final_summary).count("d.parent_draft_id IS NULL") == 2


def test_the_month_limit_names_the_business() -> None:
    from qualify_api.creative.parts import PARTS_OVER_BUDGET_TEXT

    assert PARTS_OVER_BUDGET_TEXT == (
        "No pudimos crear las partes: tu negocio llegó a su límite de este mes. "
        "Escríbenos y lo revisamos contigo."
    )


def test_parts_made_by_a_concurrent_ask_are_found_inside_the_unit() -> None:
    """Review fix: the parts are looked for again inside the unit (under the parent's
    lock in Postgres) — a concurrent ask that made them first wins, nothing is doubled."""
    parts, _, repo, ledger, dispatcher, _, parent = world()
    first = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    rows, calls = dict(ledger.rows), list(dispatcher.calls)
    real = repo.parts_of
    seen: list[int] = []

    def parts_of(**kwargs):  # noqa: ANN003, ANN202
        seen.append(1)
        return () if len(seen) == 1 else real(**kwargs)  # the first look misses them

    repo.parts_of = parts_of  # type: ignore[method-assign]
    assert parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID) == first
    assert len(seen) == 2 and ledger.rows == rows and dispatcher.calls == calls


class _FenceSession:
    """Answers the parent fence's three reads in order: its events, its status, whether
    its files were purged (m-24921069)."""

    def __init__(self, *, purged: bool) -> None:
        self.answers: list[object] = [[], "generated", purged]
        self.sql: list[str] = []

    def execute(self, statement: object, params: object = None) -> _FenceSession:
        self.sql.append(str(statement))
        self.answer = self.answers.pop(0)
        return self

    def scalars(self) -> _FenceSession:
        return self

    def all(self) -> object:
        return self.answer

    def scalar(self) -> object:
        return self.answer


@pytest.mark.parametrize("purged", [True, False])
def test_no_part_changes_under_a_video_whose_files_were_purged(purged: bool) -> None:
    from qualify_api.creative.parts import (
        PURGED_PARENT_TEXT,
        PartChangeRefused,
        lock_parent_for_part_change,
        refuse_if_parent_purged,
    )

    session = _FenceSession(purged=purged)
    if purged:
        with pytest.raises(PartChangeRefused) as refused:
            lock_parent_for_part_change(session, uuid4())  # type: ignore[arg-type]
        assert str(refused.value) == PURGED_PARENT_TEXT
    else:
        assert lock_parent_for_part_change(session, uuid4()) == "generated"  # type: ignore[arg-type]
    assert "FOR UPDATE" in session.sql[1] and "media_purged_at" in session.sql[2]
    # the same refusal create_parts runs under the parent's row lock
    alone = _FenceSession(purged=purged)
    alone.answers = [purged]
    if purged:
        with pytest.raises(PartChangeRefused):
            refuse_if_parent_purged(alone, uuid4())  # type: ignore[arg-type]
    else:
        refuse_if_parent_purged(alone, uuid4())  # type: ignore[arg-type]
