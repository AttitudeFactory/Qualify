"""m-25016656: a video by parts opened again at `/drafts/<id>` (from «Por aprobar» or
«Aprobados») shows its parts and «Tu video completo», as right after creating it.

Covers the page's branch by kind, the single piece's blocks hidden for the parent, the
parent while `drafting` (no parts' panel, no card: one poll at a time), a failed read
(another business's id, a junk id) showing nothing of a previous video — not even the
wait of a parent that was drafting —, the status at the top re-read after «Aprobar» in
the card, and that the page never starts the 1080p final poll for a parent.

The page's conditions are Vars: where it matters they are EVALUATED with Reflex's own
runtime helpers (`isTrue`, `pyAnd`, `pyOr` from its `state.js` template) under Node,
against the state `CreativeState`'s real events leave behind — skipped where Node is
not installed."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import reflex as rx
from qualify_api.creative.draft_mode import draft_rendering, draft_summary
from qualify_api.creative.part_final import FINAL_READY, JOIN_FINAL_PENDING
from qualify_api.creative.part_join import JOIN_PREVIEW_STATUS

from . import creative_pages as cp
from . import creative_state as creative_state_module
from . import final_video_card_state as card_module
from .creative_state import CreativeState
from .creative_vm import DraftVM, video_draft_vm
from .final_video_card_state import FinalVideoState
from .generation_state import GenerationState

PARENT = UUID(int=7)
FOREIGN = UUID(int=9)
_TENANT, _BRAND, _USER = UUID(int=101), UUID(int=102), UUID(int=103)

#: what only the single piece's blocks put in the page (their state vars / events)
_SINGLE_PIECE_ONLY = (
    "retention_notice",  # «Descarga esta pieza…»
    "video_draft",  # the 480p / 1080p notice
    "other_version_pending",  # «Otra versión en camino»
    "promotion_state",  # «Promocionar»
    "tik_tok",  # «Enviar a TikTok»
    "edit_mode",  # the review panel's editor
    "approve_selected",  # the decision bar's «Aprobar»
    "reject",  # the decision bar's «Descartar / Regenerar»
)


def _js(component: rx.Component) -> str:
    return str(component.render())


def _find(text: str, js: str) -> int:
    """Where `text` sits in a render, written as is or with its accents escaped; -1."""
    for form in (text, json.dumps(text)[1:-1], json.dumps(json.dumps(text)[1:-1])[1:-1]):
        if form in js:
            return js.index(form)
    return -1


def _at(text: str, js: str) -> int:
    found = _find(text, js)
    assert found >= 0, text
    return found


# -- evaluating a page condition the way the browser does -----------------------------------

_NODE = shutil.which("node")
_STATE_JS = (
    Path(rx.__file__).resolve().parent.parent
    / "reflex_base"
    / ".templates"
    / "web"
    / "utils"
    / "state.js"
)
_CREATIVE = CreativeState.get_full_name().replace(".", "__")
needs_node = pytest.mark.skipif(
    _NODE is None or not _STATE_JS.exists(), reason="Node or Reflex's state.js not available"
)


def _runtime() -> str:
    """Reflex's own `isTrue` / `pyOr` / `pyAnd`, as the compiled page imports them."""
    source = _STATE_JS.read_text(encoding="utf-8")
    parts = []
    for name in ("isTrue", "pyOr", "pyAnd"):
        found = re.search(rf"export const {name} = .*?;\n(?=\n|/)", source, re.S)
        assert found, name
        parts.append(found.group(0).replace("export ", ""))
    return "".join(parts)


def _evaluate(var: rx.Var, creative: dict[str, Any]) -> bool:
    """Condition `var` as the browser decides it (`rx.cond` tests `isTrue`), with
    `CreativeState`'s fields taken from `creative`."""
    expr = str(var).replace(f"{_CREATIVE}.", "S.").replace("_rx_state_", "")
    assert "reflex___state" not in expr, expr  # only CreativeState is read here
    script = (
        f"{_runtime()}const S = {json.dumps(creative)};\n"
        f"console.log(JSON.stringify(isTrue({expr})));"
    )
    assert _NODE is not None
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, check=True, timeout=30
    )
    return json.loads(out.stdout)


def _seen(state: CreativeState) -> dict[str, Any]:
    """What the page's conditions read of `state`, as the browser receives it."""
    draft = state.draft
    return {
        "draft": None
        if draft is None
        else {"kind": draft.kind, "is_drafting": draft.is_drafting, "draft_id": draft.draft_id},
        "detail_error": state.detail_error,
        "poll_timed_out": state.poll_timed_out,
    }


def _parent(status: str = "drafting", label: str = "Generando") -> DraftVM:
    return DraftVM(
        draft_id=str(PARENT),
        status=status,
        status_label=label,
        status_tone="blue",
        variants=(),
        is_drafting=status == "drafting",
        kind=cp.PARTS_PARENT_KIND,
    )


def _creative(
    monkeypatch: pytest.MonkeyPatch, route: UUID | None, raw: str | None = None
) -> CreativeState:
    """A `CreativeState` showing a parent still `drafting`, on the route `route` — `raw`
    is the URL's `draft_id` as typed ("" = no draft route, the generator; a junk id
    parses to `route` None)."""

    async def session_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
        return _TENANT, _BRAND, _USER

    async def login_context(self: CreativeState) -> tuple[str, str, str]:
        # main's guard (#602–#605) reads AuthState: no event context in these tests
        return str(_TENANT), str(_USER), str(_USER)

    monkeypatch.setattr(CreativeState, "_session_ids", session_ids)
    monkeypatch.setattr(CreativeState, "_edit_login_context", login_context)
    monkeypatch.setattr(CreativeState, "_route_draft_id", lambda self: route)
    # the dynamic route arg `/drafts/[draft_id]` installs (no app in these tests)
    route_text = raw if raw is not None else ("" if route is None else str(route))
    monkeypatch.setattr(CreativeState, "draft_id", route_text, raising=False)
    state = CreativeState()
    state.draft = _parent()
    return state


async def _drain(events: Any) -> list[Any]:
    if hasattr(events, "__aiter__"):
        return [event async for event in events]
    await events
    return []


def _stub(monkeypatch: pytest.MonkeyPatch, **branches: str) -> None:
    for name, word in branches.items():
        monkeypatch.setattr(cp, name, lambda word=word: rx.text(word))


# -- the page chooses by kind -------------------------------------------------------------


def test_the_page_branches_on_the_parents_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rendered: `draft` present → kind `shot_video` → the parent's page, else the single
    piece's; no draft at all (a junk id on a fresh tab) → nothing under the error."""
    assert cp.PARTS_PARENT_KIND == "shot_video"
    _stub(monkeypatch, _parts_parent_detail="BRANCH-PARTS", _single_piece_detail="BRANCH-SINGLE")
    page = str(cp.draft_detail_index())
    body = page[page.index(".detail_loading_rx_state_?(") :]
    has_draft = body.index("isTrue(" + _CREATIVE + ".draft_rx_state_)?")
    kind = body.index('=== "shot_video"', has_draft)
    parts, single = body.index("BRANCH-PARTS"), body.index("BRANCH-SINGLE")
    assert has_draft < kind < parts < single
    # no draft: an empty fragment right after the two branches close
    assert re.match(r'BRANCH-SINGLE"\)+:\(jsx\(Fragment,\{\},\)\)', body[single:])


def test_every_other_kind_keeps_its_own_review() -> None:
    single = _js(cp._single_piece_detail())
    for marker in _SINGLE_PIECE_ONLY:
        assert marker in single, marker
    # nothing of the video by parts leaks into a single piece
    assert "part_progress_state" not in single and "final_video_state" not in single


# -- the parent's page ----------------------------------------------------------------------


def test_the_parent_shows_its_card_parts_and_text_in_order() -> None:
    """m-25016656 (Deivid, «Sí, opción A»): on /drafts «Tu video completo» comes first,
    then the parts' one status line and the parts waiting for a decision."""
    made = _js(cp._parts_parent_made())
    assert "20rem minmax(0, 1fr)" in made  # the card's columns, as a piece's page
    order = [
        made.index("final_video_state.load"),  # the card's first read, on mount
        made.index("part_progress_state____part_progress_state.status_line"),
        made.index("part_progress_state____part_progress_state.decision_rows"),
        _at(cp.POST_TEXT_TITLE, made),
        _at(cp.COPY_TEXT_LABEL, made),
        made.index("campaign_state"),
    ]
    assert order == sorted(order)
    assert "rendered_caption" in made  # the text is the variant's own, read only


@pytest.mark.parametrize("marker", _SINGLE_PIECE_ONLY)
def test_the_single_pieces_blocks_are_hidden_for_the_parent(marker: str) -> None:
    for branch in (cp._parts_parent_made, cp._parts_parent_failed, cp._parts_parent_waiting):
        assert marker not in _js(branch()), (branch.__name__, marker)


def test_the_post_text_is_a_heading_and_copying_says_so() -> None:
    text = _js(cp._parts_post_text())
    title = _at(cp.POST_TEXT_TITLE, text)
    # the component that holds the title: the nearest one opened before it
    holder = text[text.rfind("'name': ", 0, title) : title]
    assert holder.startswith("'name': 'RadixThemesHeading'") and 'as:"h3"' in holder
    assert cp.COPIED_TEXT == "Texto copiado"
    _at(cp.COPIED_TEXT, text)  # the toast after «Copiar texto»


@needs_node
@pytest.mark.parametrize(
    ("variant", "shown"),
    [(None, False), ({"rendered_caption": ""}, False), ({"rendered_caption": "¡Hola!"}, True)],
)
def test_an_empty_text_draws_no_card(variant: dict | None, shown: bool) -> None:
    assert _evaluate(cp._has_post_text(), {"selected_variant": variant}) is shown


def test_a_drafting_parent_mounts_neither_the_parts_nor_the_card() -> None:
    wait = _js(cp._parts_parent_waiting())
    assert "part_progress_state" not in wait and "final_video_state" not in wait
    assert cp.PARTS_DRAFTING_TITLE == "Preparando tu video por partes…"
    assert cp.PARTS_DRAFTING_TEXT.startswith("Primero escribimos lo que dice cada parte.")
    assert cp.PARTS_DRAFTING_TEXT.endswith("Puedes salir: el video te espera en Por aprobar.")
    for text in (cp.PARTS_DRAFTING_TITLE, cp.PARTS_DRAFTING_TEXT):
        _at(text, wait)
    assert "queue" in wait  # a queued parent keeps saying its turn, as today
    # the house's loader: the bar, never a spinner
    assert "q-progress-fill" in wait and "Spinner" not in wait
    # and none of a single piece's stage badges («Texto», «Imagen», …)
    single_wait = _js(cp._drafting_panel())
    for stage in creative_state_module.GENERATION_STAGES:
        assert _find(stage, single_wait) >= 0 and _find(stage, wait) < 0, stage


def test_a_failed_read_is_checked_before_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rendered order: the failed read hides every branch, the wait included; then the
    wait wins over the failed and the made parent."""
    _stub(
        monkeypatch,
        _parts_parent_waiting="BRANCH-WAITING",
        _parts_parent_failed="BRANCH-FAILED",
        _parts_parent_made="BRANCH-MADE",
    )
    js = _js(cp._parts_parent_detail())
    stale = js.index("poll_timed_out")
    drafting = js.index('["is_drafting"]')
    assert stale < drafting < js.index("BRANCH-WAITING") < js.index("BRANCH-FAILED")
    assert js.index("BRANCH-WAITING") < js.index("BRANCH-MADE")


def test_both_header_badges_hide_on_a_failed_read(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, _parts_parent_detail="BRANCH-PARTS", _single_piece_detail="BRANCH-SINGLE")
    page = str(cp.draft_detail_index())
    header = page[: page.index("BRANCH-PARTS")]
    # the kind badge and the status badge, each behind the same «failed read» test
    assert header.count(".poll_timed_out_rx_state_") == 2


# -- a failed read after a parent, evaluated ------------------------------------------------


@needs_node
@pytest.mark.parametrize(
    ("route", "raw"), [(FOREIGN, None), (None, "junk")], ids=["another business", "junk id"]
)
async def test_a_failed_read_after_a_drafting_parent_shows_nothing_of_it(
    monkeypatch: pytest.MonkeyPatch, route: UUID | None, raw: str | None
) -> None:
    """Review: an id of another business (RLS gives nothing back) or a junk id, opened
    right after a parent still `drafting`, kept showing that parent's wait, its queue
    with «Cancelar» and its badges. `load_draft` keeps the previous draft (it is not
    ours to change); the page must not draw it."""
    state = _creative(monkeypatch, route, raw)
    monkeypatch.setattr(creative_state_module, "draft_detail", lambda tenant, draft: None)
    await _drain(CreativeState.load_draft.fn(state))
    seen = _seen(state)
    assert seen["draft"]["is_drafting"] and seen["detail_error"] != ""  # kept, said why
    assert _evaluate(cp._parts_parent_stale(), seen) is True


async def _open_elsewhere_while_polling(
    monkeypatch: pytest.MonkeyPatch, route: UUID | None, raw: str
) -> CreativeState:
    """/drafts/A (A drafting, its poll running), then /drafts/<raw>: that read fails."""
    state = _creative(monkeypatch, route, raw)
    state._polling_draft_id = str(PARENT)
    monkeypatch.setattr(creative_state_module, "draft_detail", lambda tenant, draft: None)
    await _drain(CreativeState.load_draft.fn(state))
    assert state.detail_error == creative_state_module._DRAFT_GONE
    assert state._polling_draft_id == str(PARENT)  # A's poll goes on (one per id)
    return state


@needs_node
@pytest.mark.parametrize(
    ("route", "raw"), [(FOREIGN, str(FOREIGN)), (None, "junk")], ids=["another", "junk"]
)
async def test_a_poll_left_behind_never_paints_the_wait_back(
    monkeypatch: pytest.MonkeyPatch, route: UUID | None, raw: str
) -> None:
    """Review round 2: A's poll timing out on the other URL put `poll_timed_out` and its
    error there, and the wait of A came back. Now it only times out quietly."""
    state = await _open_elsewhere_while_polling(monkeypatch, route, raw)
    monkeypatch.setattr(creative_state_module, "_POLL_BUDGET_SECONDS", 0.0)
    await _drain(CreativeState.poll_draft.fn(state))
    assert state.detail_error == creative_state_module._DRAFT_GONE  # the read's own
    assert state.poll_timed_out is False
    assert _evaluate(cp._parts_parent_stale(), _seen(state)) is True


async def test_a_poll_left_behind_never_refreshes_the_other_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """…nor does it put A back on the other URL when A's text comes out (it still ends
    and says so, as today)."""
    state = await _open_elsewhere_while_polling(monkeypatch, FOREIGN, str(FOREIGN))
    monkeypatch.setattr(creative_state_module, "_POLL_DELAYS", (0.0,))
    monkeypatch.setattr(
        creative_state_module, "draft_detail", lambda tenant, draft: _parent("generated")
    )
    events = await _drain(CreativeState.poll_draft.fn(state))
    assert state.draft.status == "drafting" and state.draft.is_drafting  # not repainted
    assert state.poll_elapsed_label == ""
    assert len(events) > 1  # the poll still ended with its own notice
    assert state._polling_draft_id == ""


@pytest.mark.parametrize(
    "raw",
    [str(PARENT), str(PARENT).upper(), ""],
    ids=["its own page", "its own page in capitals", "the generator"],
)
async def test_on_its_own_page_or_the_generator_the_poll_still_refreshes(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    state = _creative(monkeypatch, PARENT if raw else None, raw)
    state._polling_draft_id = str(PARENT)
    monkeypatch.setattr(creative_state_module, "_POLL_DELAYS", (0.0,))
    monkeypatch.setattr(
        creative_state_module, "draft_detail", lambda tenant, draft: _parent("generated")
    )
    await _drain(CreativeState.poll_draft.fn(state))
    assert state.draft.status == "generated" and not state.draft.is_drafting


@needs_node
async def test_a_wait_that_ran_long_keeps_its_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """The drafting poll's own timeout fills `detail_error` too: that parent keeps its
    wait — it is still this URL's video."""
    state = _creative(monkeypatch, PARENT)  # still on /drafts/A
    state._polling_draft_id = str(PARENT)
    monkeypatch.setattr(creative_state_module, "_POLL_BUDGET_SECONDS", 0.0)
    events = await _drain(CreativeState.poll_draft.fn(state))
    assert events == [GenerationState.refresh]
    seen = _seen(state)
    assert seen["detail_error"] != "" and seen["poll_timed_out"] is True
    assert _evaluate(cp._parts_parent_stale(), seen) is False
    assert _evaluate(CreativeState.draft.is_drafting, seen) is True


@needs_node
@pytest.mark.parametrize(
    ("kind", "error", "timed_out", "stale"),
    [
        ("shot_video", "", False, False),  # read fine
        ("shot_video", "No encontramos…", False, True),
        ("shot_video", "Está tardando…", True, False),
        ("static_flyer", "No encontramos…", False, False),  # other kinds: as before
    ],
)
def test_the_failed_read_condition(kind: str, error: str, timed_out: bool, stale: bool) -> None:
    seen = {
        "draft": {"kind": kind, "is_drafting": False, "draft_id": str(PARENT)},
        "detail_error": error,
        "poll_timed_out": timed_out,
    }
    assert _evaluate(cp._parts_parent_stale(), seen) is stale


# -- the status at the top after «Aprobar» in the card ---------------------------------------


def test_the_reread_names_the_piece_pages_own_event() -> None:
    assert card_module.PIECE_PAGE_REREAD == CreativeState.get_full_name() + ".view_version"
    event = card_module._reread_piece_page()
    assert event.name == card_module.PIECE_PAGE_REREAD
    assert event.payload == {"requested_version_id": ""}


async def test_the_reread_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """`view_version("")` reads the route's draft again WITHOUT the page's skeleton
    (`detail_loading` would swap the page and remount the card and its parts)."""
    state = _creative(monkeypatch, PARENT)
    state.draft = _parent("generated", "Listo para revisar")
    loading_while_read: list[bool] = []

    def detail(tenant: UUID, draft: UUID) -> DraftVM:
        loading_while_read.append(state.detail_loading)
        assert draft == PARENT
        return _parent("approved", "Aprobado")

    async def no_videos(self: CreativeState, *args: Any) -> None:
        return None

    monkeypatch.setattr(creative_state_module, "draft_detail", detail)
    monkeypatch.setattr(CreativeState, "_load_approval_videos", no_videos)
    await _drain(CreativeState.view_version.fn(state, ""))
    assert loading_while_read == [False] and not state.detail_loading
    assert state.draft.status == "approved" and state.draft.status_label == "Aprobado"


async def test_the_reread_does_nothing_without_a_route_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generator's result has no route draft: the event is harmless there too."""
    state = _creative(monkeypatch, None)

    def detail(*args: Any) -> None:
        pytest.fail("no read expected")

    monkeypatch.setattr(creative_state_module, "draft_detail", detail)
    await _drain(CreativeState.view_version.fn(state, ""))
    assert state.draft.status == "drafting"


#: Run in a child interpreter: installing a route arg changes the root state CLASS for
#: the rest of a process (no undo), and other tests read their route args off states
#: built standalone, without one.
_ROUTE_ARG_CHECK = """
import sys
from uuid import UUID
from reflex import constants
from reflex.istate.data import PageData
from reflex.state import State
from Qualify.final_video_card_state import FinalVideoState

parent, foreign = sys.argv[1], sys.argv[2]
State.setup_dynamic_args({"draft_id": constants.RouteArgType.SINGLE})
assert "draft_id" in FinalVideoState.vars
root = State(_reflex_internal_init=True)
card = root.get_substate(FinalVideoState.get_full_name().split(".")[1:])
card.parent_id = parent
root.rx_router_page = PageData(params={"draft_id": parent})
assert card.draft_id == parent and card._on_piece_page()
root.rx_router_page = PageData(params={"draft_id": foreign})
assert not card._on_piece_page()
root.rx_router_page = PageData(params={})
assert not card._on_piece_page()
print("ok")
"""


def test_the_card_reads_the_real_route_arg() -> None:
    """`_on_piece_page` reads `draft_id`, the dynamic arg `/drafts/[draft_id]` installs on
    the root state (`setup_dynamic_args`, what `app.add_page` does): a substate such as
    `FinalVideoState` really receives it — on its own page, not on another draft's, not
    on the generator's (no route draft)."""
    import os
    import sys

    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(root), *sys.path])}
    out = subprocess.run(
        [sys.executable, "-c", _ROUTE_ARG_CHECK, str(PARENT), str(FOREIGN)],
        capture_output=True,
        text=True,
        cwd=root,
        env=env,
        timeout=300,
    )
    assert out.returncode == 0 and out.stdout.strip().endswith("ok"), out.stderr[-2000:]


@pytest.mark.parametrize(
    ("route", "parent", "expected"),
    [
        (str(PARENT), str(PARENT), True),  # /drafts/<this video>
        (str(PARENT).upper(), str(PARENT), True),  # the same id, typed in capitals
        ("", str(PARENT), False),  # the generator's result: no route draft
        (str(UUID(int=8)), str(PARENT), False),  # another draft's page
        (None, str(PARENT), False),
    ],
)
def test_only_the_videos_own_page_is_reread(route: Any, parent: str, expected: bool) -> None:
    fake = SimpleNamespace(parent_id=parent, **({} if route is None else {"draft_id": route}))
    assert FinalVideoState._on_piece_page(fake) is expected


async def test_approving_on_the_videos_page_rereads_its_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import test_final_video_card as card_tests

    fake = card_tests.Backend()

    async def identity(self: FinalVideoState) -> tuple[UUID, UUID]:
        return card_tests.TENANT, card_tests.USER

    monkeypatch.setattr(FinalVideoState, "_identity", identity)
    monkeypatch.setattr(card_module.provider, "read_card", fake.read_card)
    monkeypatch.setattr(card_module.provider, "approve", fake.approve)

    for on_page in (True, False):
        monkeypatch.setattr(FinalVideoState, "_on_piece_page", lambda self, v=on_page: v)
        state = await card_tests._loaded(card_tests.PARENT)
        events = await card_tests._drain(FinalVideoState.approve.fn(state))
        rereads = [e for e in events if getattr(e, "name", "") == card_module.PIECE_PAGE_REREAD]
        assert len(rereads) == (1 if on_page else 0)
        assert state.approved_here
        fake.final = card_tests._final()  # back to approvable for the next round


async def test_a_refused_approval_rereads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from . import test_final_video_card as card_tests

    fake = card_tests.Backend()
    fake.fail["approve"] = RuntimeError("boom")

    async def identity(self: FinalVideoState) -> tuple[UUID, UUID]:
        return card_tests.TENANT, card_tests.USER

    monkeypatch.setattr(FinalVideoState, "_identity", identity)
    monkeypatch.setattr(card_module.provider, "read_card", fake.read_card)
    monkeypatch.setattr(card_module.provider, "approve", fake.approve)
    monkeypatch.setattr(FinalVideoState, "_on_piece_page", lambda self: True)
    state = await card_tests._loaded(card_tests.PARENT)
    events = await card_tests._drain(FinalVideoState.approve.fn(state))
    assert not [e for e in events if getattr(e, "name", "") == card_module.PIECE_PAGE_REREAD]


# -- no 1080p final poll for a parent --------------------------------------------------------


@pytest.mark.parametrize("status", [JOIN_PREVIEW_STATUS, JOIN_FINAL_PENDING, FINAL_READY])
@pytest.mark.parametrize("approved", [False, True])
def test_the_parents_join_never_starts_the_final_poll(status: str, approved: bool) -> None:
    """`load_draft` starts `poll_final` only for a video whose final is `rendering`
    (`_starts_final_poll`). A parent's one file is its join, whose `draft` block goes
    `join_preview` → `join_final_pending` → `final_ready`: never `rendering`. The
    parts' poll (`PartProgressState`) is what refreshes it."""
    params = [{"draft": {"status": status, "finish": "join"}}]
    assert draft_rendering(params) is False
    vm = video_draft_vm(
        *draft_summary(params, approved=approved),
        still_rendering=draft_rendering(params),
        approved=approved,
    )
    assert vm.rendering is False
    claimed = CreativeState._starts_final_poll(
        SimpleNamespace(_final_polling_id=""), SimpleNamespace(video_draft=vm, draft_id="p")
    )
    assert claimed is False


# -- the parts' panel on a closed video: only its own card counts ---------------------------


def _evaluate_states(var: rx.Var, states: dict[type, dict[str, Any]]) -> bool:
    """`var` as the browser decides it, each state's fields from `states`."""
    expr = str(var)
    names = []
    for i, (cls, fields) in enumerate(states.items()):
        name = f"S{i}"
        expr = expr.replace(cls.get_full_name().replace(".", "__") + ".", name + ".")
        names.append(f"const {name} = {json.dumps(fields)};")
    expr = expr.replace("_rx_state_", "")
    assert "reflex___state" not in expr, expr
    script = _runtime() + "".join(names) + f"console.log(JSON.stringify(isTrue({expr})));"
    assert _NODE is not None
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, check=True, timeout=30
    )
    return json.loads(out.stdout)


@needs_node
@pytest.mark.parametrize(
    ("closed", "card_video", "drawn"),
    [
        (False, "B", True),  # B's own card: not approved → its decisions show
        (True, "B", False),  # B approved: only to watch
        (True, "A", True),  # the card still holds approved A (B failed, no card): B decides
        (False, "", True),  # no card read yet
    ],
)
def test_only_the_panels_own_video_hides_its_decisions(
    closed: bool, card_video: str, drawn: bool
) -> None:
    from .part_progress_panel import _shows_decisions
    from .part_progress_state import PartProgressState

    panel = {"decision_rows": [{"index": 2, "state": "failed"}]}
    card = {"closed": closed, "parent_id": card_video}
    shown = _evaluate_states(
        _shows_decisions("B"), {PartProgressState: panel, FinalVideoState: card}
    )
    assert shown is drawn
    nothing = {"decision_rows": []}
    assert (
        _evaluate_states(_shows_decisions("B"), {PartProgressState: nothing, FinalVideoState: card})
        is False
    )


def test_a_decision_row_is_drawn_with_its_buttons() -> None:
    """The row the panel draws for a part to decide on: its words and, unless its
    «Quitar parte» question is open, one button per action that runs it."""
    from .part_progress_panel import _row
    from .part_progress_state import PartProgressState

    row = _js(_row(PartProgressState.decision_rows[0]))
    buttons = row[row.index('?.["buttons"]') :]
    assert "run_part_action" in buttons and "ask_remove" in buttons
    assert '?.["confirming"]' in row  # the question replaces them while it is open
    assert '"listitem"' in row
