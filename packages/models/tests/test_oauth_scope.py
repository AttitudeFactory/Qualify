"""Tests for the OAuth-reachability applicability matrix.

These pin *judgements*, not model behaviour, so they run offline with no
weights. The point of pinning them is that the matrix is consumed by
`eval/fase0_cost.py`: if someone flips a verdict, the cost model silently
starts pricing a different product, and these tests make that loud.
"""

from __future__ import annotations

import itertools

import pytest

from qualify_models.oauth_scope import (
    APPLICABILITY,
    SURFACE_PROFILES,
    CascadeStage,
    ContentSurface,
    Verdict,
    lookup,
    oauth_reachable_surfaces,
    profile_for,
    requires_enrichment_gate,
    stages_for_surface,
    surfaces_for_stage,
)


def test_matrix_is_total_and_unique() -> None:
    """Every (stage, surface) pair appears exactly once.

    A missing cell would silently read as "not billable" in the cost model.
    """
    seen = [(cell.stage, cell.surface) for cell in APPLICABILITY]
    expected = list(itertools.product(CascadeStage, ContentSurface))
    assert len(seen) == len(set(seen)), "duplicate cell in APPLICABILITY"
    assert set(seen) == set(expected)
    assert len(APPLICABILITY) == len(CascadeStage) * len(ContentSurface)


def test_every_surface_has_a_profile() -> None:
    profiled = {p.surface for p in SURFACE_PROFILES}
    assert profiled == set(ContentSurface)
    assert len(SURFACE_PROFILES) == len(ContentSurface)


def test_every_cell_carries_a_reason() -> None:
    for cell in APPLICABILITY:
        assert cell.reason.strip(), f"{cell.stage}/{cell.surface} has no reason"


def test_sentiment_on_owned_comments_is_the_unchanged_bridge() -> None:
    """The near-term win: the one cell that transfers with no modification.

    docs/fase0-zernio-mercado.md §4.3. If this ever stops being
    APPLIES_UNCHANGED, the whole "runnable today" claim needs rewriting.
    """
    cell = lookup(CascadeStage.SENTIMENT, ContentSurface.OWNED_MEDIA_COMMENTS)
    assert cell.verdict is Verdict.APPLIES_UNCHANGED
    assert cell.billable


def test_sentiment_is_the_only_unchanged_stage_on_owned_surfaces() -> None:
    """Owned media itself yields no unchanged stage — everything is repurposed
    or inapplicable. This is the "reuse is thinner than it looks" finding."""
    owned = [c for c in APPLICABILITY if c.surface is ContentSurface.OWNED_MEDIA]
    assert all(c.verdict is not Verdict.APPLIES_UNCHANGED for c in owned)


def test_filter_does_not_apply_to_owned_media() -> None:
    """The OAuth grant already answers the relevance question."""
    cell = lookup(CascadeStage.FILTER, ContentSurface.OWNED_MEDIA)
    assert cell.verdict is Verdict.DOES_NOT_APPLY
    assert not cell.billable


@pytest.mark.parametrize("surface", [ContentSurface.MENTIONED_MEDIA, ContentSurface.TAGS])
def test_discard_gate_survives_on_third_party_media(surface: ContentSurface) -> None:
    """Third-party media volume is unbounded and an @-mention proves only that
    the brand was named — so the cheap-gate-before-expensive-stage shape
    survives, even though siglip2 is the wrong instrument to fill the slot."""
    cell = lookup(CascadeStage.FILTER, surface)
    assert cell.verdict is Verdict.APPLIES_REPURPOSED
    assert requires_enrichment_gate(surface)


@pytest.mark.parametrize(
    "surface",
    [
        ContentSurface.OWNED_MEDIA,
        ContentSurface.OWNED_MEDIA_COMMENTS,
        ContentSurface.MENTIONED_COMMENT,
    ],
)
def test_ungated_surfaces(surface: ContentSurface) -> None:
    """Owned media is bounded by the client's own publishing rate; text-only
    surfaces have no expensive stage to gate."""
    assert not requires_enrichment_gate(surface)


def test_vision_transfers_wholesale_only_to_third_party_media() -> None:
    """The single surface family where the Fase 1 cascade is reused verbatim."""
    unchanged = {
        c.surface
        for c in APPLICABILITY
        if c.stage is CascadeStage.VISION and c.verdict is Verdict.APPLIES_UNCHANGED
    }
    assert unchanged == {ContentSurface.MENTIONED_MEDIA, ContentSurface.TAGS}


@pytest.mark.parametrize(
    "surface", [ContentSurface.OWNED_MEDIA_COMMENTS, ContentSurface.MENTIONED_COMMENT]
)
def test_text_only_surfaces_bill_for_sentiment_alone(surface: ContentSurface) -> None:
    """No visual or audio track means three of four stages cannot run at all."""
    profile = profile_for(surface)
    assert not profile.has_visual_track
    assert not profile.has_audio_track
    assert stages_for_surface(surface) == (CascadeStage.SENTIMENT,)


@pytest.mark.parametrize(
    "surface",
    [ContentSurface.COMPETITOR_CONTENT, ContentSurface.UNAFFILIATED_CREATOR_CONTENT],
)
def test_unreachable_surfaces_bill_nothing_for_any_stage(surface: ContentSurface) -> None:
    """The structural finding: no OAuth grant can reach these, so no stage runs.

    docs/fase0-zernio-mercado.md §4.2 — this is not a limitation that scale or
    spend removes, which is why it is modeled rather than omitted.
    """
    assert not profile_for(surface).oauth_reachable
    for stage in CascadeStage:
        cell = lookup(stage, surface)
        assert cell.verdict is Verdict.UNREACHABLE
        assert not cell.billable
    assert stages_for_surface(surface) == ()


def test_oauth_reachable_surfaces_are_exactly_the_five_instagram_ones() -> None:
    assert set(oauth_reachable_surfaces()) == {
        ContentSurface.OWNED_MEDIA,
        ContentSurface.OWNED_MEDIA_COMMENTS,
        ContentSurface.MENTIONED_MEDIA,
        ContentSurface.MENTIONED_COMMENT,
        ContentSurface.TAGS,
    }


def test_reachable_surfaces_declare_a_graph_api_edge() -> None:
    for profile in SURFACE_PROFILES:
        if profile.oauth_reachable:
            assert profile.graph_api_edge, f"{profile.surface} missing an edge"
        else:
            assert profile.graph_api_edge is None


def test_no_stage_is_billable_on_an_unreachable_surface() -> None:
    """Cross-check of the invariant the cost model depends on."""
    for stage in CascadeStage:
        for surface in surfaces_for_stage(stage):
            assert profile_for(surface).oauth_reachable


def test_lookup_rejects_unknown_pairs() -> None:
    with pytest.raises(KeyError):
        lookup(CascadeStage.VISION, "not_a_surface")  # type: ignore[arg-type]
