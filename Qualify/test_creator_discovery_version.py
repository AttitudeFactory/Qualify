"""Guard for `creator_discovery.PHASED_PLAN_VERSION` — the number every stored referentes
result is stamped with, and the one thing that tells a cached or persisted phase it was
computed by an older algorithm and must be recomputed.

The 2026-09-15 location rework changed the algorithm without bumping it, so cached
phases kept serving the old answer. This test makes that impossible to repeat: it
fingerprints the algorithm's CODE (module-level functions, classes, tables and tunables,
compared as `ast.unparse` output with docstrings dropped — so comments, docstrings and
formatting never count) and pins one fingerprint per version. Changing the algorithm
without bumping the version fails here.

What is deliberately NOT part of the fingerprint (`_NOT_ALGORITHM`): caching, retries,
concurrency, avatars, card presentation and the CLI — changing those does not change
which accounts a phase finds, so it must not force a recompute that spends credits.
A NEW top-level name counts by default: forgetting to exclude something only costs an
unneeded bump, forgetting to include something would hide a real change.

Python is pinned to 3.12.13 locally and in CI (`.python-version`, the workflow), which
keeps `ast.unparse` output stable.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from qualify_api.referentes import discovery_seed

from . import creator_discovery as cd

#: The algorithm lives in two modules since m-24852195: the seed read from the brand's
#: own account and the tables it stands on moved to the backend (`discovery_seed`), the
#: phased search stayed here. Both are fingerprinted, in this order.
_MODULES = (Path(discovery_seed.__file__), Path(cd.__file__))

_NOT_ALGORITHM = frozenset(
    {
        # the version itself, logging, paths, schema of the CLI output
        "PHASED_PLAN_VERSION",
        "logger",
        "DISCOVERY_DIR",
        "DISCOVERY_SCHEMA",
        "DEFAULT_MAX_CREDITS",
        # transport: timeouts, retries, parallelism, the vendor's own cache age
        "_DISCOVERY_TIMEOUT_SECONDS",
        "_RETRY_DELAY_SECONDS",
        "_get_retry",
        "NOT_FOUND_STATUS",
        "PoolClient",
        "_run_parallel",
        "_run_networks",
        "NETWORKS",
        "lookup_account",
        "PARALLEL_CALLS",
        "_PROFILE_CACHE_MAX_AGE",
        "_dump_raw",
        # the run's memory of profile reads (Postgres since 2026-10-01) and the runner
        "ProfileStore",
        "facts_to_document",
        "facts_from_document",
        "PhasedDiscovery",
        "phase_signature",
        # avatars and card presentation
        # phase titles the owner reads (NAV-11, m-24849129): words, not which accounts
        "phase_title",
        "owner_phase_title",
        "SIMILAR_PREFIX",
        "compact_count",
        "_compact",
        "_tiktok_avatar",
        "_RENDERABLE_EXTENSIONS",
        "_renderable_url",
        "AVATAR_ROUTE",
        "AVATAR_DIR",
        "avatar_path",
        "_compact",
        "_reason",
        "_likes_label",
        "_ai_share",
        "account_card",
        "KIND_LABELS",
        "phase_to_dict",
        # the card's reach signal (presentation over the phase's medians, 2026-10-01)
        "REACH_OUTLIER",
        "ENGAGEMENT_DEFICIT",
        "REACH_SIGNAL",
        "reach_signals",
        "_median",
        # the filter-JSON CLI bench
        "result_path",
        "save_result",
        "_load_dotenv",
        "_print_summary",
        "main",
    }
)

#: One fingerprint per version. When the test below fails because the algorithm
#: changed: bump `PHASED_PLAN_VERSION` and add the new version's line here (the failure
#: message prints it). Never edit an existing line — that would be changing what an old
#: version meant.
FINGERPRINTS: dict[int, str] = {
    5: "1bf8506d5df38d5ed0c39769fa5c8b4acaac3735d7ce5c981750ec59eacfca4b",
    6: "3f2cd2348040999347648ca37a942c2204566a4f0f5d04042642caf3cdf0b48a",
    7: "940189c1e6f88972ea55fd3cc8624719a9138ffd05f2f21771df392f65ecd6f8",
    8: "029d966521ac0bad41ad0523c75a129d7871ebbbaa2d35561c92c4a29abb2ab0",
    9: "7fad47a4258303b5324b3d1cfb53d5495d05b32cae01d0c07edcf7e747ee7317",
    # 10: the same accounts as 9 — `run_phase` only changed to walk both networks at once
    10: "1da80e375db2e53fbe9b9381725b0aa7b130100e63cca39937163a335c51607c",
    # 11: the same accounts as 10 — `Candidate` gained the profile link and the count of
    # AI-labelled videos seen, read on the feeds; the profile reads moved to Postgres
    11: "c33c339245106ebaaae4f29fd9499e355b5b73d62d132fe528f8cfed82c08dda",
    # 12 re-pinned, not bumped (NAV-11, m-24849129): `phase_title` moved to
    # `_NOT_ALGORITHM` — the owner's words for a phase, not which accounts it finds; a bump
    # would recompute every brand's saved search and spend credits for the same accounts.
    # Was "1f3513dc18d2911b3bdbe8766dc43b11a99ab2440f3301f8d59182bc40fa6efe".
    # Re-pinned again, not bumped (m-24852195): `seed_from_profile` and the pure tables it
    # reads moved verbatim to `qualify_api.referentes.discovery_seed`, and the fingerprint
    # now covers both modules. Same code, same accounts. Was
    # "1fc685cc844f93fa7b18792c0d704e725e1dc6b5b48d24af93e78bb5d199fad8".
    12: "48c38afca303731b21563875114286b3ae48512849d4f1b1c51d3705813c0d44",
}


def _names(node: ast.stmt) -> set[str]:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {ast.unparse(target) for target in node.targets}
    if isinstance(node, ast.AnnAssign):
        return {ast.unparse(node.target)}
    return set()


def _parsed(source: str) -> ast.Module:
    tree = ast.parse(source)
    _strip_docstrings(tree)
    return tree


def _strip_docstrings(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]


def algorithm_fingerprint(*sources: str) -> str:
    kept = []
    for node in (node for source in sources for node in _parsed(source).body):
        if isinstance(node, ast.Import | ast.ImportFrom):
            continue
        if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
            continue
        if _names(node) & _NOT_ALGORITHM:
            continue
        kept.append(ast.unparse(node))
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()


def test_algorithm_changes_bump_the_plan_version() -> None:
    version = cd.PHASED_PLAN_VERSION
    current = algorithm_fingerprint(*(m.read_text(encoding="utf-8") for m in _MODULES))
    pinned = FINGERPRINTS.get(version)
    assert pinned is not None, (
        f"PHASED_PLAN_VERSION is {version} but FINGERPRINTS has no entry for it. "
        f'Add `{version}: "{current}",` to FINGERPRINTS in this file.'
    )
    assert current == pinned, (
        "The referentes algorithm (discovery_seed.py + creator_discovery.py) changed but "
        "PHASED_PLAN_VERSION "
        f"is still {version}. Stored results would keep serving the old algorithm's "
        f"answer. Bump PHASED_PLAN_VERSION to {version + 1} and add "
        f'`{version + 1}: "{current}",` to FINGERPRINTS. (If the change is not about '
        "which accounts are found — caching, presentation, CLI — add the name to "
        "_NOT_ALGORITHM instead.)"
    )


def test_versions_only_move_forward() -> None:
    assert max(FINGERPRINTS) == cd.PHASED_PLAN_VERSION


# --------------------------------------------------------------------------------------
# the fingerprint itself: blind to prose, sensitive to logic
# --------------------------------------------------------------------------------------

_SAMPLE = '''
"""module doc"""
import re

PHASED_PLAN_VERSION = 1
MAX_PER_PHASE = 8


def pick(items):
    """doc"""
    return items[:MAX_PER_PHASE]  # a comment


def account_card(item):
    return {"name": item}
'''


def test_comments_docstrings_and_formatting_do_not_count() -> None:
    reworded = (
        _SAMPLE.replace('"""doc"""', '"""a longer, reworded docstring"""')
        .replace("# a comment", "# another comment")
        .replace("items[:MAX_PER_PHASE]", "items[ : MAX_PER_PHASE ]")
    )
    assert algorithm_fingerprint(reworded) == algorithm_fingerprint(_SAMPLE)


def test_a_tunable_or_logic_change_counts() -> None:
    base = algorithm_fingerprint(_SAMPLE)
    assert algorithm_fingerprint(_SAMPLE.replace("= 8", "= 10")) != base
    assert algorithm_fingerprint(_SAMPLE.replace("items[:", "items[1:")) != base


def test_excluded_names_and_the_version_itself_do_not_count() -> None:
    base = algorithm_fingerprint(_SAMPLE)
    assert algorithm_fingerprint(_SAMPLE.replace("= 1\n", "= 2\n")) == base
    assert algorithm_fingerprint(_SAMPLE.replace('{"name"', '{"title"')) == base
