"""m-25017817: the mention-vs-reply merge truth table, shared by the in-memory test
(`test_conversations_story_mention.py`) and the Postgres one
(`test_conversations_repository_db.py`), so both repositories answer the same table.

Not a test module (no `test_` prefix): each test loads it by path
(`importlib.util.spec_from_file_location`), because `--import-mode=importlib` makes
sibling test files unimportable by name.

Rules being pinned (`repository._INSERT_MESSAGE` / `repository.merge_story_kind`):
`graph` and `attachment` are CONFIRMED mentions (Meta discriminates); `heuristic` is an
inference. A confirmed mention upgrades a heuristic or a stored reply, is never downgraded
by a reply reading, and `graph` is never lowered to `attachment`. A `story.reply_to` node
reading turns only a heuristic mention into a reply. id/URL are fill-only. Outbound rows
are never touched.
"""

from __future__ import annotations

from typing import Any

STORY = "story-7"
URL = "https://cdn.example/story"
LATER = "https://cdn.example/later"
ATT = "https://cdn.example/att"

#: Named readings of the same `mid` — `RemoteMessage` keyword arguments.
READINGS: dict[str, dict[str, Any]] = {
    "bare": {},
    "heuristic": {
        "story_mention": True,
        "story_mention_basis": "heuristic",
        "story_mention_id": STORY,
        "story_mention_url": URL,
    },
    "attachment": {
        "story_mention": True,
        "story_mention_basis": "attachment",
        "story_mention_url": ATT,
        "media_type": "other",
    },
    "graph_mention": {
        "story_mention": True,
        "story_mention_basis": "graph",
        "story_mention_id": STORY,
        "story_mention_url": LATER,
    },
    "graph_reply": {
        "story_reply_id": STORY,
        "story_reply_url": URL,
        "story_reply_confirmed": True,
    },
    "legacy_reply": {"story_reply_id": STORY, "story_reply_url": URL},
    "echo": {"direction": "outbound"},
}

#: (readings in arrival order, (basis, mention id, mention url, reply id, direction)).
CASES: list[tuple[tuple[str, ...], tuple[str | None, str | None, str | None, str | None, str]]] = [
    # the live webhook shape, redelivered, then a poll without `story`
    (("heuristic", "heuristic", "bare"), ("heuristic", STORY, URL, None, "inbound")),
    (("bare", "heuristic"), ("heuristic", STORY, URL, None, "inbound")),
    # graph confirms the heuristic, either order; id/URL fill-only
    (("heuristic", "graph_mention"), ("graph", STORY, URL, None, "inbound")),
    (("graph_mention", "heuristic"), ("graph", STORY, LATER, None, "inbound")),
    # the node's `story.reply_to` turns the inference into a reply, either order
    (("heuristic", "graph_reply"), (None, None, None, STORY, "inbound")),
    (("graph_reply", "heuristic"), (None, None, None, STORY, "inbound")),
    # a confirmed graph mention is never downgraded
    (("graph_mention", "graph_reply"), ("graph", STORY, LATER, None, "inbound")),
    # a row stored as a reply before 0155 is upgraded by a confirmed mention ...
    (("legacy_reply", "graph_mention"), ("graph", STORY, LATER, None, "inbound")),
    (("legacy_reply", "attachment"), ("attachment", STORY, ATT, None, "inbound")),
    # ... but never by a heuristic
    (("legacy_reply", "heuristic"), (None, None, None, STORY, "inbound")),
    # attachment: confirms a heuristic, ignores a later heuristic, never downgraded
    (("heuristic", "attachment"), ("attachment", STORY, URL, None, "inbound")),
    (("attachment", "heuristic"), ("attachment", None, ATT, None, "inbound")),
    (("attachment", "attachment"), ("attachment", None, ATT, None, "inbound")),
    (("attachment", "graph_mention"), ("graph", STORY, ATT, None, "inbound")),
    (("graph_mention", "attachment"), ("graph", STORY, LATER, None, "inbound")),
    (("attachment", "graph_reply"), ("attachment", None, ATT, None, "inbound")),
    (("heuristic", "attachment", "graph_reply"), ("attachment", STORY, URL, None, "inbound")),
    # outbound rows are never flagged, and an outbound reading changes nothing
    (("echo", "heuristic"), (None, None, None, None, "outbound")),
    (("echo", "attachment"), (None, None, None, None, "outbound")),
    (("heuristic", "echo"), ("heuristic", STORY, URL, None, "inbound")),
]
