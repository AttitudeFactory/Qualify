"""Which product capabilities a set of granted OAuth scopes unlocks, and why.

This is the permission -> capability matrix (backlog C-05). It is the sibling of
`oauth_scope.py`, and deliberately shares *no* types with it: `oauth_scope.py`
maps (content surface x cascade stage) -- what Qualify may *analyze* -- while this
module maps (granted scope -> product capability) -- what the connected account
may *do*. Orthogonal axes, so a shared enum would be a false economy.

Design constraints, all load-bearing (see `docs/refinamiento-sprint1.md` §C-05
and the QUA-17 refinement comment):

- **Literal/logic separation.** The pure decision logic in `assess_capabilities`
  operates on abstract `ScopeKey`s, never on Meta's literal scope strings. The
  literals live in one versioned table (`SCOPE_LITERALS`) resolved empirically
  against the live authorization endpoint. This is what absorbs the `[V]`
  blocker: every spelling is unverified-against-the-endpoint, but the capability
  logic is testable *today* without knowing the real names.
- **No fuzzy matching.** `resolve_scope_keys` does an EXACT reverse-index lookup.
  Fuzzy/embedding matching is prohibited: it would inject non-determinism and
  could map a brand-new Meta scope onto the wrong key, silently over-granting.
- **Unrecognized literals are surfaced, not swallowed.** `resolve_scope_keys`
  returns the literals it could not place alongside the resolved keys, so a
  future/renamed scope shows up as "unknown" instead of a phantom denial.
- **Version stamped on the result.** `ASSESSMENT_VERSION` is copied onto every
  `CapabilityVerdict`, so a stored verdict records which matrix produced it, not
  just which module happened to be imported at read time.

## PESSIMISTIC encoding of the comment ladder (founder decision, 2026-07-25)

The strongest onboarding claim (`§2.5`) was "reading/analyzing comments does not
depend on being able to reply". The harvested corpus does NOT support it: Meta's
`ig-media/comments.md` puts read (GET) and reply (POST) under the *same*
`manage_comments` requirement at the edge level, and the only reading path that
would rescue the ladder (inline field-expansion under `basic`) is unconfirmed in
the corpus. Per the founder ruling (QUA-17), the ladder is therefore encoded
CONSERVATIVELY: `READ_COMMENTS` and `ANALYZE_COMMENTS` both `requires=MANAGE_COMMENTS`
and are flagged `provisional=True`. The UI (C-06) shows "needs this permission",
never a runtime 403. If the live check below proves reading is reachable with a
lesser grant, relax these two rows to the optimistic model and clear the flag.

## LIVE VERIFICATION PLAN (follow-up, does NOT block C-05)

Goal: settle whether *reading/analyzing* IG comments is reachable without the
`manage_comments` grant, i.e. whether the pessimistic rows above can be relaxed.

1. Prereq: the founder's own IG Business/Creator account is connected through the
   Sprint-1 OAuth flow (C-04), producing a real access token. Use a token that
   was granted `instagram_business_basic` but NOT `instagram_business_manage_comments`
   -- i.e. re-run the consent screen and decline the comments permission, so the
   token genuinely lacks it. (A token that holds every scope cannot answer this.)
2. Take one of the account's own media ids (`GET /me/media`).
3. Probe reading two ways against the live Graph API:
   a. edge read:   `GET /<IG_MEDIA_ID>/comments`
   b. inline read: `GET /<IG_MEDIA_ID>?fields=comments{text,username,timestamp}`
   Record HTTP status + error subcode for each.
4. Interpretation:
   - Both 200 with the basic-only token  -> reading is NOT gated by manage_comments.
     Relax `READ_COMMENTS`/`ANALYZE_COMMENTS` to `requires=BASIC`, clear
     `provisional`, bump `ASSESSMENT_VERSION`, and notify the PO to restore the
     `§2.5` onboarding claim.
   - Either returns 403 / OAuthException (missing-permission subcode) -> the
     pessimistic encoding is correct as-is; keep it and mark `§2.5` false.
   - `4b` succeeds where `4a` fails -> the field-expansion rescue path is real;
     model it explicitly (a distinct read path under BASIC) before relaxing.
5. This is an authorization-behavior probe, not a model/network test in this
   package's test suite. It runs by hand (or a marked integration script that
   holds a real token) and its outcome edits `SCOPE_LITERALS`/the rules here --
   the pure logic and its offline tests stay untouched either way.

The scope literals below are seeded from the harvested Meta corpus
(`reference/meta-instagram-platform/DISCREPANCIES.md` §1 and
`LOGIN-FORK-AND-MENTIONS.md`), and every one carries a `[V]`: strong evidence,
but the corpus itself warns that a wrong `scope` string fails the OAuth call, so
the live authorization endpoint -- not documentation -- is the authority.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

ASSESSMENT_VERSION = "perm-capability-v1"


class ScopeKey(StrEnum):
    """An abstract permission family -- NOT a Meta literal scope string.

    The logic in `assess_capabilities` only ever speaks this vocabulary. The
    mapping to the (ambiguous, login-fork-dependent, historically renamed) Meta
    literals is isolated in `SCOPE_LITERALS` so it can be corrected against the
    live endpoint without touching a single capability rule.
    """

    BASIC = "basic"
    CONTENT_PUBLISH = "content_publish"
    MANAGE_COMMENTS = "manage_comments"
    MANAGE_MESSAGES = "manage_messages"
    MANAGE_INSIGHTS = "manage_insights"


class Capability(StrEnum):
    """A product-facing thing the connected account can do once a scope is held."""

    CONNECT_ACCOUNT = "connect_account"
    PUBLISH_CONTENT = "publish_content"
    READ_COMMENTS = "read_comments"
    ANALYZE_COMMENTS = "analyze_comments"
    REPLY_COMMENTS = "reply_comments"
    MANAGE_DMS = "manage_dms"
    READ_INSIGHTS = "read_insights"


# --- literal table: the only place Meta's real scope strings appear ----------
#
# [V] EVERY spelling below is provisional against the live authorization endpoint.
# Seeded from the harvested corpus, which lists, per family:
#   - the Instagram-Login vocabulary (`instagram_business_*`), current;
#   - the Facebook-Login vocabulary (`instagram_*`), the login-fork alternative
#     (LOGIN-FORK-AND-MENTIONS.md); and
#   - the pre-2025-01-27 deprecated vocabulary (`business_*`) still in circulation
#     (DISCREPANCIES.md §1).
# content-publish additionally has TWO live Instagram-Login spellings that Meta's
# own docs disagree on (`...content_publish` vs `...content_publishing`,
# DISCREPANCIES.md §1) -- both are seeded so neither is silently rejected.
#
# Multiple grafias per key is the point: `resolve_scope_keys` must map any of them
# onto the single ScopeKey, and the capability logic never sees which spelling won.
SCOPE_LITERALS: dict[ScopeKey, tuple[str, ...]] = {
    ScopeKey.BASIC: (
        "instagram_business_basic",  # [V] Instagram Login (current)
        "instagram_basic",  # [V] Facebook Login fork
        "business_basic",  # [V] deprecated 2025-01-27
    ),
    ScopeKey.CONTENT_PUBLISH: (
        "instagram_business_content_publish",  # [V] IG Login, business-login.md
        "instagram_business_content_publishing",  # [V] IG Login, app-review.md (Meta self-conflict)
        "instagram_content_publish",  # [V] Facebook Login fork
        "instagram_content_publishing",  # [V] Facebook Login fork, alt spelling
        "business_content_publish",  # [V] deprecated 2025-01-27
    ),
    ScopeKey.MANAGE_COMMENTS: (
        "instagram_business_manage_comments",  # [V] Instagram Login (current)
        "instagram_manage_comments",  # [V] Facebook Login fork
        "business_manage_comments",  # [V] deprecated 2025-01-27
    ),
    ScopeKey.MANAGE_MESSAGES: (
        "instagram_business_manage_messages",  # [V] Instagram Login (current)
        "instagram_manage_messages",  # [V] Facebook Login fork
        "business_manage_messages",  # [V] deprecated 2025-01-27
    ),
    ScopeKey.MANAGE_INSIGHTS: (
        "instagram_business_manage_insights",  # [V] Instagram Login (current)
        "instagram_manage_insights",  # [V] Facebook Login fork
    ),
}


def _build_reverse_index() -> dict[str, ScopeKey]:
    """literal -> ScopeKey, asserting no literal is claimed by two families.

    A collision would make resolution ambiguous, so it is a build-time error
    rather than a silent last-writer-wins.
    """
    index: dict[str, ScopeKey] = {}
    for key, literals in SCOPE_LITERALS.items():
        for literal in literals:
            if literal in index:
                raise ValueError(
                    f"literal {literal!r} claimed by both {index[literal]!r} and {key!r}"
                )
            index[literal] = key
    return index


_LITERAL_TO_KEY: dict[str, ScopeKey] = _build_reverse_index()


class CapabilityVerdict(BaseModel):
    """The assessed state of one capability for a given grant set.

    `reason` is the human-readable explanation of a DISABLED capability (why the
    feature is greyed out), following `oauth_scope.py`'s convention that every
    record always carries a populated reason. `provisional` marks a verdict whose
    gating is not yet confirmed against a second source / the live endpoint (see
    the module docstring: the comment-ladder rows). `assessment_version` is
    stamped from `ASSESSMENT_VERSION` so a persisted verdict is self-describing.
    """

    capability: Capability
    enabled: bool
    requires: ScopeKey | None
    reason: str
    provisional: bool
    assessment_version: str


class _CapabilityRule(BaseModel):
    """Static spec of one capability's gate. Pure data, no grant applied yet."""

    capability: Capability
    requires: ScopeKey | None
    provisional: bool
    disabled_reason: str


# The matrix, as data. `requires=None` means the capability has no scope gate in
# this pure layer. Exactly one rule per Capability (pinned by test).
CAPABILITY_RULES: tuple[_CapabilityRule, ...] = (
    _CapabilityRule(
        capability=Capability.CONNECT_ACCOUNT,
        requires=ScopeKey.BASIC,
        provisional=False,
        disabled_reason=(
            "No account can be connected without the basic Instagram permission; it "
            "is the floor every other capability stands on."
        ),
    ),
    _CapabilityRule(
        capability=Capability.PUBLISH_CONTENT,
        requires=ScopeKey.CONTENT_PUBLISH,
        provisional=False,
        disabled_reason=(
            "Publishing reels/stories/posts is off because the content-publishing "
            "permission was not granted. Reading, comments and DMs are unaffected."
        ),
    ),
    _CapabilityRule(
        capability=Capability.READ_COMMENTS,
        requires=ScopeKey.MANAGE_COMMENTS,
        provisional=True,
        disabled_reason=(
            "Reading comments is off because the comments permission was not granted. "
            "PROVISIONAL: encoded pessimistically (founder ruling 2026-07-25). The "
            "corpus puts comment read and reply under the same manage_comments gate; "
            "whether basic-only reading exists is pending a live-endpoint check "
            "(see module docstring). Until confirmed, reading is gated with reply."
        ),
    ),
    _CapabilityRule(
        capability=Capability.ANALYZE_COMMENTS,
        requires=ScopeKey.MANAGE_COMMENTS,
        provisional=True,
        disabled_reason=(
            "Sentiment/topic/intent analysis of comments is off because the comments "
            "permission was not granted. PROVISIONAL: analysis reads the same comment "
            "data as READ_COMMENTS, so it inherits that row's pessimistic, "
            "not-yet-verified gate (founder ruling 2026-07-25)."
        ),
    ),
    _CapabilityRule(
        capability=Capability.REPLY_COMMENTS,
        requires=ScopeKey.MANAGE_COMMENTS,
        provisional=False,
        disabled_reason=(
            "Replying to / moderating comments is off because the comments permission "
            "was not granted. This is the one comment capability the corpus "
            "unambiguously gates on manage_comments."
        ),
    ),
    _CapabilityRule(
        capability=Capability.MANAGE_DMS,
        requires=ScopeKey.MANAGE_MESSAGES,
        provisional=False,
        disabled_reason=(
            "The DM inbox is off because the messages permission was not granted. "
            "Publishing, comments and listening are unaffected."
        ),
    ),
    _CapabilityRule(
        capability=Capability.READ_INSIGHTS,
        requires=ScopeKey.MANAGE_INSIGHTS,
        provisional=False,
        disabled_reason=(
            "Account/media insights are off because the insights permission was not "
            "granted. Finding A: insights do NOT fall under the basic permission."
        ),
    ),
)


def resolve_scope_keys(
    granted_literals: frozenset[str],
) -> tuple[frozenset[ScopeKey], frozenset[str]]:
    """Translate Meta's granted scope strings into abstract keys, EXACT match only.

    Returns ``(resolved_keys, unrecognized_literals)``. Any literal not present in
    `SCOPE_LITERALS` is returned in the second element rather than dropped, so a
    renamed/new Meta scope surfaces as "unknown" instead of a phantom denial. No
    fuzzy matching -- an unknown string stays unknown.
    """
    resolved: set[ScopeKey] = set()
    unrecognized: set[str] = set()
    for literal in granted_literals:
        key = _LITERAL_TO_KEY.get(literal)
        if key is None:
            unrecognized.add(literal)
        else:
            resolved.add(key)
    return frozenset(resolved), frozenset(unrecognized)


def assess_capabilities(granted: frozenset[ScopeKey]) -> tuple[CapabilityVerdict, ...]:
    """Resolved scope keys -> one verdict per capability, with a reason for each.

    Pure and total: emits exactly one `CapabilityVerdict` per `Capability`, in
    `CAPABILITY_RULES` order, each stamped with `ASSESSMENT_VERSION`. A capability
    is enabled iff its single `requires` key is in `granted` (or `requires is None`).
    The connection precondition is modeled as its own capability
    (`CONNECT_ACCOUNT`), not folded silently into every downstream gate -- the UI
    consumes CONNECT_ACCOUNT separately, and keeping `requires` single-valued is
    what makes each row match the founder's pinned onboarding table.
    """
    verdicts: list[CapabilityVerdict] = []
    for rule in CAPABILITY_RULES:
        enabled = rule.requires is None or rule.requires in granted
        verdicts.append(
            CapabilityVerdict(
                capability=rule.capability,
                enabled=enabled,
                requires=rule.requires,
                reason=rule.disabled_reason,
                provisional=rule.provisional,
                assessment_version=ASSESSMENT_VERSION,
            )
        )
    return tuple(verdicts)


def rule_for(capability: Capability) -> _CapabilityRule:
    """The static gating rule for one capability."""
    for rule in CAPABILITY_RULES:
        if rule.capability is capability:
            return rule
    raise KeyError(f"No rule for capability {capability!r}")


def enabled_capabilities(verdicts: tuple[CapabilityVerdict, ...]) -> frozenset[Capability]:
    """The subset of a verdict tuple that is enabled -- convenience for the UI."""
    return frozenset(v.capability for v in verdicts if v.enabled)


def assessment_is_provisional(verdicts: tuple[CapabilityVerdict, ...]) -> bool:
    """Whether any capability in this assessment rests on an unverified gate.

    C-06 shows the PROVISIONAL mark when this is True: the UI must not assert a
    capability whose gate is not yet confirmed as if it were settled.
    """
    return any(v.provisional for v in verdicts)
