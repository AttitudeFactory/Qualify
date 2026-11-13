"""m-24992893 / m-24992894: `ui.clip_player` plays a part in its own picture.

Offline, on the component tree (as the other screen tests): step 2's scene plays its
stretch of ONE stored original (`#t=start,end`), the result screen's rows «Para revisar»
and «Lista» play their vista previa, and neither re-mounts a player on a poll. The
browser's half (`assets/clip-player.js`) is checked for the rules it must keep."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.creative.part_progress import (
    PartProgress,
    PartProgressRow,
    PartState,
)

from . import content_generator as cg
from . import part_progress_provider as provider
from . import reel_parts_vm
from .part_progress_panel import part_progress_panel
from .part_progress_state import PartProgressState, _read
from .part_progress_vm import as_state, duration_text, part_progress_vm
from .ui.clip_player import (
    SOUND_LABEL,
    clip_player,
    clip_player_notice,
    clip_player_renew,
    clip_player_script,
)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / "assets" / "clip-player.js").read_text("utf-8")
CSS = (ROOT / "assets" / "qualify.css").read_text("utf-8")
PARENT = UUID("7a7a0000-0000-4000-8000-000000000009")


# -- the component -----------------------------------------------------------------------


def _player(**kw: Any) -> str:
    base: dict[str, Any] = {
        "src": "/v.mp4#t=1.5,4",
        "label": "Ver la parte 2 del original",
        "pause_label": "Pausar la parte 2",
        "start": "1.5",
        "end": "4",
    }
    base.update(kw)
    return str(clip_player("/p.jpg", **base).render())


def test_the_video_waits_for_play_and_its_address_is_an_attribute() -> None:
    js = _player()
    # never a `src` on the <video>: the script hands it over on ▶
    assert '"data-clip-src":"/v.mp4#t=1.5,4"' in js
    assert 'preload:"none"' in js and "muted:true" in js and "playsInline:true" in js
    assert 'src:"/v.mp4' not in js
    assert '"data-clip-start":"1.5"' in js and '"data-clip-end":"4"' in js
    # the state is the browser's: React never renders it
    assert "data-clip-state" not in js


def test_play_pause_and_sound_are_named_buttons() -> None:
    js = _player()
    assert js.count('type:"button"') == 3
    assert '"aria-label":"Ver la parte 2 del original"' in js
    assert '"aria-label":"Pausar la parte 2"' in js
    assert f'"aria-label":"{SOUND_LABEL}"' in js and '"aria-pressed":"false"' in js
    assert SOUND_LABEL == "Activar sonido"


def test_a_key_framed_and_broken_text() -> None:
    js = str(
        clip_player(
            "",
            src="/v.mp4",
            label="a",
            pause_label="b",
            key="draft-1",
            framed=True,
            broken_text="Ya no está.",
        ).render()
    )
    assert 'key:"draft-1"' in js
    assert "q-clip q-thumb" in js
    assert '"data-clip-broken-text":"Ya no est' in js
    # no poster → a film glyph, never a broken <img>
    assert "Film" in js or "film" in js


def test_the_script_is_mounted_from_assets() -> None:
    chain = str(clip_player_script().event_triggers["on_mount"])
    assert "__qClipPlayer" in chain


def test_the_script_keeps_its_rules() -> None:
    assert "if (window.__qClipPlayer) return;" in SCRIPT  # one set of listeners
    # one video at a time, «Tu video completo» included (capture: `play` does not bubble)
    assert 'addEventListener(\n    "play"' in SCRIPT
    assert 'querySelectorAll("video")' in SCRIPT
    # the stretch's end stops it; a hidden picture (folded rows) stops it
    assert "span.end - END_SLACK" in SCRIPT and "getClientRects().length === 0" in SCRIPT
    # a broken file: every clip of that file loses ▶; its words said once
    assert '"broken"' in SCRIPT and "saidFiles" in SCRIPT
    # ←/→ on its buttons never reach the parts' keyboard; a drag stops it
    assert 'window.addEventListener(\n    "keydown"' in SCRIPT and "stopPropagation" in SCRIPT
    assert '"dragstart"' in SCRIPT
    # the address reaches the <video> only on ▶
    assert 'video.setAttribute("src", src)' in SCRIPT


def test_the_styles_exist_and_nothing_is_hover_only() -> None:
    for rule in (".q-clip {", ".q-clip__play {", ".q-clip__pause {", ".q-clip__sound {"):
        assert rule in CSS
    assert '.q-clip[data-clip-state="playing"] .q-clip__sound' in CSS
    assert '.q-clip[data-clip-state="broken"] .q-clip__play' in CSS
    assert "isolation: isolate" in CSS  # a card's ✕ stays above the playing frame


def test_the_picture_stays_until_the_video_really_plays() -> None:
    # ▶ → loading (video hidden, ▶ dimmed) → `playing` event → playing
    assert 'host.setAttribute("data-clip-state", "loading")' in SCRIPT
    assert '"playing",' in SCRIPT and 'setAttribute("data-clip-state", "playing")' in SCRIPT
    assert '.q-clip[data-clip-state="loading"] .q-clip__play' in CSS
    assert '.q-clip[data-clip-state="playing"] .q-clip__video { visibility: visible; }' in CSS
    assert "object-fit: cover;" in CSS.split(".q-clip__video {")[1].split("}")[0]
    # a phone sees the pause mark when it starts; the sound's focus ring is not clipped
    assert "q-clip[data-clip-hint]" in CSS and "HINT_MS" in SCRIPT
    assert ".q-clip__sound:focus-visible { outline-offset: -2px; }" in CSS


def test_broken_words_are_written_once_per_file_in_a_visible_notice() -> None:
    js = str(clip_player_notice().render())
    assert '"data-clip-notice":""' in js and 'role:"status"' in js
    assert ".q-clip-notice:empty { display: none; }" in CSS
    assert 'nearest(host, "[data-clip-notice]")' in SCRIPT
    assert "saidFiles[file]" in SCRIPT


def test_a_renew_clip_asks_for_fresh_addresses_before_breaking() -> None:
    js = _player(renew=True)
    assert '"data-clip-renew":""' in js
    trigger = clip_player_renew(PartProgressState.renew_previews)
    assert "renew_previews" in str(trigger.event_triggers["on_click"])
    assert '"data-clip-renew-trigger":""' in str(trigger.render())
    # once per failed address; plays again when the address changes
    assert "host.__qClipRenewed === failed" in SCRIPT
    assert 'attributeFilter: ["data-clip-src"]' in SCRIPT and "trigger.click()" in SCRIPT


def test_renew_previews_reads_again_only_while_mounted() -> None:
    state = PartProgressState()
    assert state.renew_previews() == []
    state.watch(str(PARENT))
    assert len(state.renew_previews()) == 1
    state.leave()
    assert state.renew_previews() == []


def test_slide_drag_never_lifts_a_card_from_a_button() -> None:
    drag = (ROOT / "assets" / "slide-drag.js").read_text("utf-8")
    assert 'e.target.closest("a, button, input, textarea")' in drag


# -- step 2: the part's scene plays its stretch of the original ---------------------------


def _entry(**kw: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": "k1",
        "plan": {"mode": "edit", "seconds": 3, "description": "Una taza"},
        "person": False,
        "reason": "",
        "thumb": "/avatar/frame/x",
        "source": "/avatar/source/instagram/P/a?s=sig",
        "start_s": 1.5,
        "end_s": 4.0,
    }
    entry.update(kw)
    return entry


def test_part_rows_carry_the_source_and_its_stretch_as_text() -> None:
    row = reel_parts_vm.part_rows([_entry()])[0]
    assert (row["source"], row["start_s"], row["end_s"]) == (
        "/avatar/source/instagram/P/a?s=sig",
        "1.5",
        "4",
    )
    bare = reel_parts_vm.part_rows([_entry(source="", start_s=None, end_s=None)])[0]
    assert (bare["source"], bare["start_s"], bare["end_s"]) == ("", "0", "0")
    assert all(isinstance(v, str) for v in row.values())


@pytest.fixture(scope="module")
def step2() -> str:
    return str(cg._clip_parts_block().render())


def test_step2_scene_plays_its_stretch_of_one_source(step2: str) -> None:
    assert 'row_rx_state_?.["source"])+"#t=")+row_rx_state_?.["start_s"])+",")' in step2
    assert '"data-clip-start":row_rx_state_?.["start_s"]' in step2
    assert 'key:row_rx_state_?.["key"]' in step2  # a moved part re-mounts, a re-render not
    assert "Ver la parte " in step2 and " del original" in step2
    assert "Pausar la parte " in step2
    assert "Ya no podemos mostrar el reel original" in step2
    assert '"data-clip-notice":""' in step2  # the visible notice under the list


def test_step2_without_a_source_keeps_the_scene_alone(step2: str) -> None:
    # the player only in the branch with a source; the frame / glyph otherwise
    at = step2.index('row_rx_state_?.["source"]?.valueOf?.() === ""')
    assert "data-clip" in step2[at:]


def test_step2_keeps_the_cards_keyboard_and_drag(step2: str) -> None:
    assert "q-cr-slide--drag" in step2 and "q-part-card" in step2
    assert 'role:"listitem"' in step2


# -- the result screen: rows «Para revisar» and «Lista» -----------------------------------


class Preview:
    def __init__(self, url: str, poster: str = "/r2media/p", seconds: float = 4.4) -> None:
        self.video_url, self.poster_url, self.seconds = url, poster, seconds


def _row(index: int, state: PartState) -> PartProgressRow:
    return PartProgressRow(
        index=index,
        total=4,
        draft_id=uuid4(),
        mode="reference",
        seconds=4,
        state=state,
        actions=(),
    )


def _progress(*states: PartState) -> PartProgress:
    return PartProgress(
        parent_id=PARENT, parts=tuple(_row(i, s) for i, s in enumerate(states, start=1))
    )


def test_only_rows_to_review_or_ready_with_a_video_get_a_preview() -> None:
    progress = _progress(PartState.TO_REVIEW, PartState.READY, PartState.REDO, PartState.READY)
    previews = {i: Preview(f"/r2media/v{i}") for i in (1, 2, 3)}
    previews[4] = Preview("")  # no token minted: no picture
    rows = as_state(part_progress_vm(progress, previews=previews))["rows"]
    assert [r["preview_url"] for r in rows] == ["/r2media/v1", "/r2media/v2", "", ""]
    assert rows[0]["duration_text"] == "4 s" and rows[0]["poster_url"] == "/r2media/p"
    assert rows[1]["play_label"] == "Ver cómo quedó la parte 2"
    assert rows[1]["pause_label"] == "Pausar la parte 2"
    assert rows[2]["play_label"] == "" and rows[3]["duration_text"] == ""


def test_duration_text_is_whole_seconds_never_zero() -> None:
    assert [duration_text(s) for s in (0.2, 4.4, 4.5, 6.0)] == ["1 s", "4 s", "5 s", "6 s"]


def test_the_state_carries_the_preview_and_keeps_it_across_ticks() -> None:
    progress = _progress(PartState.TO_REVIEW, PartState.CREATING)
    previews = {1: provider.PartPreview(1, "/r2media/v1", "/r2media/p1", 5.0)}
    state = PartProgressState()
    state.watch(str(PARENT))
    state._apply(progress, previews)
    first = state.rows[0]
    assert (first.preview_url, first.poster_url, first.duration_text) == (
        "/r2media/v1",
        "/r2media/p1",
        "5 s",
    )
    state._apply(progress, previews)  # a tick with nothing new: the same row
    assert state.rows[0] == first
    assert state.rows[1].preview_url == ""


def test_read_signs_the_previews_in_the_same_call(monkeypatch: pytest.MonkeyPatch) -> None:
    progress = _progress(PartState.READY)
    seen: list[Any] = []
    monkeypatch.setattr(provider, "read_progress", lambda t, p: progress)

    def sign(tenant_id: UUID, read: PartProgress | None) -> dict[int, Any]:
        seen.append(read)
        return {}

    monkeypatch.setattr(provider, "part_previews", sign)
    assert _read(uuid4(), PARENT) == (progress, {})
    assert seen == [progress]


@pytest.fixture(scope="module")
def panel() -> str:
    return str(part_progress_panel("parent").render())


def test_panel_rows_with_a_preview_play_it_keyed_by_their_draft(panel: str) -> None:
    assert 'row_rx_state_?.["preview_url"]?.valueOf?.() === ""' in panel
    assert 'key:row_rx_state_?.["draft_id"]' in panel
    assert "q-clip q-thumb" in panel and '"aspectRatio"] : "9 / 16"' in panel
    assert 'row_rx_state_?.["duration_text"]' in panel
    assert 'row_rx_state_?.["play_label"]' in panel
    assert '"data-clip-renew":""' in panel and '"data-clip-renew-trigger":""' in panel


def test_panel_keeps_one_live_region_and_its_fold(panel: str) -> None:
    assert panel.count("aria-live") == 1
    assert '"part-rows"' in panel  # the fold's target, still in the page
    # watching only: no decision buttons of UI-8
    assert "Me gusta así" not in panel and "Crear otra versión" not in panel
