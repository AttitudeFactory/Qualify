"""Shared fixtures for the `qualify_creative` tests."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping

import pytest

#: What `reproducible_x264` adds to an x264 table: one thread, and x264 told to make the
#: same decisions whatever CPU code paths it picks (`cpu-independent=1`).
REPRODUCIBLE_X264_PARAMS = "cpu-independent=1"


@pytest.fixture
def reproducible_x264(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., None]:
    """Make libx264 write the same bytes for the same frames, for one test.

    Call it with the x264 option tables a test encodes with (e.g. `fit.REFERENCE_X264`,
    `text_overlay.OVERLAY_X264`): each table is changed IN PLACE with
    `monkeypatch.setitem`, so the defaults bound at import time
    (`x264: Mapping[str, str] = OVERLAY_X264`) see the change too, and every key is put
    back after the test. It sets `threads=1` and adds `cpu-independent=1` to
    `x264-params` (joined with `:` to whatever the table already passes there).

    Why (m-25029128, measured 2026-11-20). The same call —
    `fit_reference(video-portrait-2s.mp4, short_side=90)` — gave other bytes depending on
    how long the process had been running: 200 encodes in one fresh process gave 18
    distinct MP4s, whatever the order of the tests. Ruled out, with evidence:

    - the input: the frames handed to x264 are identical (with `qp=0`, lossless, 80/80
      encodes gave the same bytes);
    - threads: with `threads=1` it still drifts;
    - the order of the tests: one process encoding the same thing in a loop drifts too.

    What makes it stable (40/40 identical each): `mbtree=0`, `rc-lookahead=0`,
    `bframes=0`, `asm=0`, or `cpu-independent=1` — the last gives the same bytes as
    `asm=0`. Root cause: the SIMD assembly of x264's macroblock-tree propagation in the
    lookahead (`mbtree_propagate_cost` / `mbtree_propagate_list`), whose results depend
    on the state of the process's memory (measured as a drift with the process's age, not
    traced to one instruction), so the rate control picks slightly different quantizers
    and the bytes change while the frames going in do not. Every switch above either
    turns the macroblock tree off or forces the portable C path that does not depend on
    it. This also explains EF-08's earlier finding that `rc-lookahead=0` made the layer
    overlay stable and that copying the loop frames changed how often it drifted (it moved
    the buffers).

    Production is NOT changed: with `DETAIL_X264` at 1080×1920 no drift appeared in the
    sample, the visual effect of the drift is a level or two on a few pixels, and
    `cpu-independent=1` costs speed. Tests that pin bytes opt in with this fixture; it is
    not autouse. Do not use it on `cut.WINDOW_X264` or `join.JOIN_X264` from here
    without checking the modules that own them.
    """

    def apply(*tables: MutableMapping[str, str]) -> None:
        for table in tables:
            monkeypatch.setitem(table, "threads", "1")
            current = table.get("x264-params")
            if current is None:
                params = REPRODUCIBLE_X264_PARAMS
            elif REPRODUCIBLE_X264_PARAMS in current.split(":"):
                params = current
            else:
                params = f"{current}:{REPRODUCIBLE_X264_PARAMS}"
            monkeypatch.setitem(table, "x264-params", params)

    return apply
