"""Tests for the permission -> capability matrix (C-05).

These pin *judgements*, not model behaviour, so they run fully offline with no
weights, no network and (deliberately) no dependence on the real Meta scope
strings -- the whole point of the literal/logic split is that the capability
logic is verifiable while the literals stay `[V]`. If a rule flips, the UI (C-06)
silently starts offering or hiding a feature, and these tests make that loud.
"""

from __future__ import annotations

from qualify_models.permission_capability import (
    ASSESSMENT_VERSION,
    CAPABILITY_RULES,
    SCOPE_LITERALS,
    Capability,
    ScopeKey,
    assess_capabilities,
    assessment_is_provisional,
    enabled_capabilities,
    resolve_scope_keys,
)


def _verdict(granted: frozenset[ScopeKey]) -> dict[Capability, bool]:
    """assess -> {capability: enabled} for terse assertions."""
    return {v.capability: v.enabled for v in assess_capabilities(granted)}


# --- structural totality -----------------------------------------------------


def test_five_scope_keys() -> None:
    """Finding A lives here: MANAGE_INSIGHTS is a first-class key, so five total."""
    assert len(ScopeKey) == 5
    assert ScopeKey.MANAGE_INSIGHTS in set(ScopeKey)
    assert set(SCOPE_LITERALS) == set(ScopeKey), "every key must seed literals"


def test_matrix_is_total_and_unique() -> None:
    """Exactly one rule per Capability; assess emits exactly one verdict each."""
    ruled = [r.capability for r in CAPABILITY_RULES]
    assert len(ruled) == len(set(ruled)), "duplicate capability rule"
    assert set(ruled) == set(Capability)

    verdicts = assess_capabilities(frozenset())
    seen = [v.capability for v in verdicts]
    assert len(seen) == len(set(seen)) == len(Capability)
    assert set(seen) == set(Capability)


def test_every_verdict_carries_reason_and_version() -> None:
    """Version is stamped ON THE RESULT, not just at module level."""
    for v in assess_capabilities(frozenset()):
        assert v.reason.strip(), f"{v.capability} has no reason"
        assert v.assessment_version == ASSESSMENT_VERSION


# --- resolve_scope_keys: literals -> keys ------------------------------------


def test_unknown_literal_falls_into_unrecognized() -> None:
    """A future/renamed scope must surface as unknown, never a phantom denial."""
    resolved, unrecognized = resolve_scope_keys(
        frozenset({"instagram_business_basic", "instagram_business_teleport"})
    )
    assert resolved == frozenset({ScopeKey.BASIC})
    assert unrecognized == frozenset({"instagram_business_teleport"})


def test_login_fork_and_deprecated_spellings_resolve_to_one_key() -> None:
    """FB-login, IG-login and pre-2025-01-27 spellings collapse onto one key."""
    for literal in (
        "instagram_business_manage_comments",  # IG login
        "instagram_manage_comments",  # FB login fork
        "business_manage_comments",  # deprecated
    ):
        resolved, unrecognized = resolve_scope_keys(frozenset({literal}))
        assert resolved == frozenset({ScopeKey.MANAGE_COMMENTS}), literal
        assert unrecognized == frozenset()


def test_both_content_publish_spellings_resolve() -> None:
    """Meta's own docs disagree on publish/publishing; neither may be rejected."""
    for literal in (
        "instagram_business_content_publish",
        "instagram_business_content_publishing",
    ):
        resolved, _ = resolve_scope_keys(frozenset({literal}))
        assert resolved == frozenset({ScopeKey.CONTENT_PUBLISH}), literal


def test_partial_grant_round_trip() -> None:
    """A realistic partial grant resolves cleanly and drives the right verdicts.

    basic + comments granted (but not publish/messages/insights): connection,
    reading, analysis and replying on; publishing, DMs and insights off. No
    literal is left unrecognized.
    """
    granted_literals = frozenset({"instagram_business_basic", "instagram_business_manage_comments"})
    keys, unrecognized = resolve_scope_keys(granted_literals)
    assert keys == frozenset({ScopeKey.BASIC, ScopeKey.MANAGE_COMMENTS})
    assert unrecognized == frozenset()

    enabled = _verdict(keys)
    assert enabled[Capability.CONNECT_ACCOUNT] is True
    assert enabled[Capability.READ_COMMENTS] is True
    assert enabled[Capability.ANALYZE_COMMENTS] is True
    assert enabled[Capability.REPLY_COMMENTS] is True
    assert enabled[Capability.PUBLISH_CONTENT] is False
    assert enabled[Capability.MANAGE_DMS] is False
    assert enabled[Capability.READ_INSIGHTS] is False


# --- the pinned onboarding table (C-05.3), pessimistic variant ---------------


def test_empty_grant_disables_everything() -> None:
    enabled = _verdict(frozenset())
    assert enabled == {cap: False for cap in Capability}


def test_basic_only_enables_only_connection_pessimistic() -> None:
    """PESSIMISTIC ladder (founder 2026-07-25): basic alone unlocks connection ONLY.

    This is the row that inverts the doc's optimistic §2.5 claim: with basic but
    no manage_comments, reading and analysis are OFF. If the live-endpoint check
    later proves basic-only reading works, this test flips with the encoding.
    """
    enabled = _verdict(frozenset({ScopeKey.BASIC}))
    assert enabled[Capability.CONNECT_ACCOUNT] is True
    assert enabled[Capability.READ_COMMENTS] is False
    assert enabled[Capability.ANALYZE_COMMENTS] is False
    assert enabled[Capability.REPLY_COMMENTS] is False
    assert enabled[Capability.PUBLISH_CONTENT] is False
    assert enabled[Capability.MANAGE_DMS] is False
    assert enabled[Capability.READ_INSIGHTS] is False


def test_comment_capabilities_are_flagged_provisional() -> None:
    """READ/ANALYZE_COMMENTS carry provisional=True; REPLY does not."""
    by_cap = {v.capability: v for v in assess_capabilities(frozenset(ScopeKey))}
    assert by_cap[Capability.READ_COMMENTS].provisional is True
    assert by_cap[Capability.ANALYZE_COMMENTS].provisional is True
    assert by_cap[Capability.REPLY_COMMENTS].provisional is False
    # requires wiring: the ladder is gated on manage_comments, not basic.
    assert by_cap[Capability.READ_COMMENTS].requires is ScopeKey.MANAGE_COMMENTS
    assert by_cap[Capability.ANALYZE_COMMENTS].requires is ScopeKey.MANAGE_COMMENTS


def test_assessment_is_provisional_tracks_the_flag() -> None:
    """Any provisional verdict makes the whole assessment provisional (for C-06)."""
    assert assessment_is_provisional(assess_capabilities(frozenset(ScopeKey))) is True
    # A grant set that lights no provisional-bearing capability is still provisional
    # because the verdict tuple always CONTAINS the (disabled) provisional rows.
    assert assessment_is_provisional(assess_capabilities(frozenset())) is True


def test_denying_reply_does_not_disable_publish_dms_or_insights() -> None:
    """Scopes are an independent ladder: withholding one does not cascade.

    Everything EXCEPT the comment family granted -> publish, DMs, insights and
    connection all on; the three comment capabilities off.
    """
    granted = frozenset(
        {
            ScopeKey.BASIC,
            ScopeKey.CONTENT_PUBLISH,
            ScopeKey.MANAGE_MESSAGES,
            ScopeKey.MANAGE_INSIGHTS,
        }
    )
    enabled = _verdict(granted)
    assert enabled[Capability.CONNECT_ACCOUNT] is True
    assert enabled[Capability.PUBLISH_CONTENT] is True
    assert enabled[Capability.MANAGE_DMS] is True
    assert enabled[Capability.READ_INSIGHTS] is True
    assert enabled[Capability.READ_COMMENTS] is False
    assert enabled[Capability.ANALYZE_COMMENTS] is False
    assert enabled[Capability.REPLY_COMMENTS] is False


def test_insights_needs_its_own_scope_not_basic() -> None:
    """Finding A pinned: insights is gated on MANAGE_INSIGHTS, absent under basic."""
    assert _verdict(frozenset({ScopeKey.BASIC}))[Capability.READ_INSIGHTS] is False
    assert _verdict(frozenset({ScopeKey.MANAGE_INSIGHTS}))[Capability.READ_INSIGHTS] is True


def test_full_grant_enables_everything() -> None:
    enabled = _verdict(frozenset(ScopeKey))
    assert enabled == {cap: True for cap in Capability}
    assert enabled_capabilities(assess_capabilities(frozenset(ScopeKey))) == frozenset(Capability)
