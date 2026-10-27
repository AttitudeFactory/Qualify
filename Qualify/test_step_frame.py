"""PASOS-2 (m-24852241, docs/design-system.md §4.5, rule N6b): the step frame.

Offline: «Paso N de M» counts the visible steps only, «Atrás» never shows on step 1, the
head and the foot sit outside the scrolling body, the step scripts scroll the panel
(never `window`) and focus the title, `?paso=` round-trips, and the CSS hides the bottom
bar while a frame is mounted (≤ 640 px), lets the foot step aside for the keyboard and
adds no backdrop-filter.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import reflex as rx

from Qualify.ui import steps
from Qualify.ui import steps_vm as vm

_CSS = (Path(__file__).parent.parent / "assets" / "qualify.css").read_text(encoding="utf-8")


def _has(rendered: str, text: str) -> bool:
    escaped = json.dumps(text)[1:-1]
    return any(form in rendered for form in (text, escaped, escaped.replace("\\", "\\\\")))


class _Demo(rx.State):
    n: int = 1
    m: int = 3


# ---------------------------------------------------------------------------------------
# The counter: real M
# ---------------------------------------------------------------------------------------


def test_counter_counts_only_visible_steps() -> None:
    flow = ["negocio", "horario", "mensaje", "revisar"]
    visible = vm.visible_steps(flow, skipped={"horario"})
    assert visible == ["negocio", "mensaje", "revisar"]
    assert vm.step_position("mensaje", visible) == (2, 3)
    assert vm.step_label(*vm.step_position("revisar", visible)) == "Paso 3 de 3"
    # Without the skip the same step is further along a longer flow.
    assert vm.step_position("mensaje", vm.visible_steps(flow)) == (3, 4)


def test_counter_never_reads_a_step_nobody_reaches() -> None:
    visible = ["a", "b", "c"]
    assert vm.step_position("skipped", visible) == (1, 3)
    assert vm.step_position("a", []) == (1, 1)
    assert vm.step_label(0, 3) == "Paso 1 de 3"
    assert vm.step_label(5, 3) == "Paso 3 de 3"
    assert vm.step_percent(1, 3) == 33
    assert vm.step_percent(3, 3) == 100
    assert vm.step_percent(1, 0) == 100


def test_counter_renders_label_and_bar() -> None:
    rendered = str(steps.step_progress(2, 4).render())
    assert _has(rendered, "Paso 2 de 4")
    assert "50%" in rendered
    assert "progressbar" in rendered
    # A Var counter is a template over the state, never a frozen number.
    dynamic = str(steps.step_progress(_Demo.n, _Demo.m).render())
    assert "Paso " in dynamic and "n" in dynamic and "q-step-bar-fill" in dynamic


# ---------------------------------------------------------------------------------------
# The foot: no «Atrás» on step 1
# ---------------------------------------------------------------------------------------


def _foot(step: int | rx.Var[int]) -> str:
    return str(
        steps.step_foot(
            "Siguiente",
            step=step,
            on_primary=rx.console_log("next"),
            on_back=rx.console_log("back"),
            on_later=rx.console_log("later"),
        ).render()
    )


def test_foot_has_no_back_on_step_one() -> None:
    assert not vm.shows_back(1)
    assert vm.shows_back(2)
    first = _foot(1)
    assert not _has(first, "Atrás")
    assert _has(first, "Siguiente") and _has(first, "Seguir después")
    assert _has(_foot(2), "Atrás")


def test_foot_hides_back_on_step_one_when_dynamic() -> None:
    rendered = _foot(_Demo.n)
    # Rendered under a condition on the step, so it cannot show on step 1.
    assert _has(rendered, "Atrás")
    assert re.search(r"n\S*\s*>\s*1", rendered) or "> 1" in rendered


def test_foot_is_the_bottom_island_on_a_page_and_plain_in_a_drawer() -> None:
    assert "q-step-slot" in _foot(2)
    drawer_foot = str(
        steps.step_foot(
            "Siguiente", step=2, on_primary=rx.console_log("x"), in_drawer=True
        ).render()
    )
    assert "q-step-foot--drawer" in drawer_foot and "q-step-slot" not in drawer_foot


# ---------------------------------------------------------------------------------------
# The frame: head and foot outside the scrolling body, one h1
# ---------------------------------------------------------------------------------------


def _frame() -> rx.Component:
    return steps.step_frame(
        rx.text("cuerpo-del-paso"),
        head=steps.step_head(
            "¿Qué quieres decir?",
            step=2,
            total=3,
            back_label="Tus publicaciones",
            back_href="/publicaciones",
        ),
        foot=steps.step_foot("Siguiente", step=2, on_primary=rx.console_log("next")),
        step=2,
    )


def test_frame_puts_head_and_foot_outside_the_body() -> None:
    frame = _frame()
    head, body, foot = frame.children
    assert "q-step-head" in str(head.render()) and "q-page-header" in str(head.render())
    assert "q-step-body" in str(body.render())
    assert "cuerpo-del-paso" in str(body.render())
    assert "q-step-slot" in str(foot.render())
    # Neither the head nor the foot lives inside the body that scrolls and re-mounts.
    assert "q-step-head" not in str(body.render())
    assert "q-step-slot" not in str(body.render())


def test_head_shows_the_way_out_and_one_h1() -> None:
    rendered = str(_frame().render())
    assert _has(rendered, "Tus publicaciones") and "/publicaciones" in rendered
    assert _has(rendered, "Volver a Tus publicaciones")
    assert _has(rendered, "Paso 2 de 3")
    assert rendered.count('"h1"') == 1


def test_head_needs_exactly_one_exit() -> None:
    with pytest.raises(ValueError):
        steps.step_head("T", step=1, total=2, back_label="Inicio")


# ---------------------------------------------------------------------------------------
# Step change: the panel back to the top, focus on the title, `?paso=`
# ---------------------------------------------------------------------------------------


def test_settle_scrolls_the_panel_not_the_window_and_focuses_the_title() -> None:
    page = steps.step_settle_script("page")
    assert "main.q-panel" in page and "scrollTo" in page
    assert "window.scrollTo" not in page
    assert ".q-step-title" in page and "focus" in page
    assert ".q-drawer-body" in steps.step_settle_script("drawer")


def test_step_address_round_trips() -> None:
    url = vm.step_url("/crear", 2, volver="/semana")
    assert url == "/crear?volver=%2Fsemana&paso=2"
    assert vm.parse_step_param("2", 3) == 2
    assert vm.parse_step_param(["3"], 3) == 3
    assert vm.parse_step_param("9", 3) == 3
    assert vm.parse_step_param("", 3) == 1
    assert vm.parse_step_param("abc", 3) == 1
    assert vm.parse_step_param(None, 3) == 1
    assert vm.step_direction(2, 1) == vm.DIR_BACK
    assert vm.step_direction(1, 2) == vm.DIR_NEXT
    assert vm.step_direction(2, 2, vm.DIR_BACK) == vm.DIR_BACK


def test_frame_answers_popstate_itself() -> None:
    frame = steps.step_frame(
        rx.text("x"),
        head=steps.step_head("T", step=1, total=2, back_label="Inicio", back_href="/"),
        foot=steps.step_foot("Siguiente", step=1, on_primary=rx.console_log("n")),
        step=1,
        on_pop=rx.console_log("pop"),
    )
    assert "q-step-pop" in str(frame.render())
    assert "popstate" in steps.step_settle_script() and ".q-step-pop" in steps.step_settle_script()


def test_go_to_step_pushes_the_address_then_settles() -> None:
    spec = steps.go_to_step("/crear", 2)
    rendered = str(spec)
    assert "pushState" in rendered and "paso=2" in rendered and "main.q-panel" in rendered


# ---------------------------------------------------------------------------------------
# CSS: one island at the bottom, keyboard, no new glass, reduced motion
# ---------------------------------------------------------------------------------------


def _phone_css() -> str:
    return "\n".join(re.findall(r"@media \(max-width: 640px\) \{(.*?)\n\}", _CSS, re.S))


def test_bottom_bar_hides_while_a_frame_is_mounted_on_a_phone() -> None:
    phone = _phone_css()
    assert re.search(r"\.q-ground:has\(\.q-step-frame\) \.q-bottom-bar \{ display: none; \}", phone)
    assert re.search(r"\.q-ground:has\(\.q-step-frame\) \{ --q-bottom-bar-h:", phone)
    assert "position: fixed" in phone and ".q-step-slot" in phone


def test_foot_steps_aside_for_the_keyboard() -> None:
    assert ":is(.q-bottom-bar, .q-step-slot)" in _phone_css()


def test_foot_shares_the_bottom_bar_material_and_adds_no_glass() -> None:
    assert ".q-step-foot:not(.q-step-foot--drawer) {\n  align-items: stretch;" in _CSS
    block = _CSS[_CSS.index("── Step frame") : _CSS.index("`viewport-fit=cover`")]
    block = re.sub(r"/\*.*?\*/", "", block.split("*/", 1)[1], flags=re.S)
    assert "backdrop-filter" not in block
    assert "#" not in block
    assert "position: sticky" in block


def test_entrance_follows_direction_and_respects_reduced_motion() -> None:
    assert '.q-step-body[data-dir="back"]' in _CSS
    assert "translateX(8px)" in _CSS and "translateX(-8px)" in _CSS
    assert re.search(
        r"prefers-reduced-motion: reduce\) \{\s*\.q-step-body > \* \{ animation: none; \}", _CSS
    )


def test_design_sample_renders_three_steps() -> None:
    from Qualify import styleguide_page as page

    rendered = str(page.styleguide_steps().render())
    assert "q-step-frame" in rendered and "q-step-slot" in rendered
    assert len(vm.visible_steps(page._FRAME_STEPS, ("horario",))) == 3
    assert _has(str(page._step_frame_sample().render()), "Abrir la muestra de 3 pasos")


def test_drawer_variant_puts_the_counter_in_the_fixed_header() -> None:
    from Qualify.ui import drawer

    rendered = str(
        drawer(
            rx.text("x"),
            open=True,
            on_open_change=rx.console_log("o"),
            title="Programar",
            step=steps.step_progress(2, 3),
            footer=steps.step_foot(
                "Siguiente", step=2, on_primary=rx.console_log("n"), in_drawer=True
            ),
        ).render()
    )
    head = rendered[rendered.index("q-drawer-head") : rendered.index("q-drawer-body")]
    assert _has(head, "Paso 2 de 3") and "q-step-bar" in head
    # The title takes the focus on a step change.
    assert "q-step-title" in head and "tabIndex:-1" in head


# ---------------------------------------------------------------------------------------
# UX review of PR #359 (ux-designer, 2026-10-26)
# ---------------------------------------------------------------------------------------


def test_bar_has_its_own_line_under_the_exit_row() -> None:
    head = steps.step_head(
        "T", step=1, total=3, back_label="Tus publicaciones", back_href="/publicaciones"
    )
    row, bar, *_ = head.children
    assert "q-step-exit" in str(row.render()) and "q-step-count" in str(row.render())
    assert "q-step-bar" not in str(row.render())
    assert "q-step-bar" in str(bar.render())


def test_title_is_described_by_the_counter_without_a_live_region() -> None:
    rendered = str(_frame().render())
    assert f'"aria-describedby":"{steps.COUNT_ID_PAGE}"' in rendered.replace(" ", "") or (
        "aria-describedby" in rendered and steps.COUNT_ID_PAGE in rendered
    )
    assert "aria-live" not in rendered and "ariaLive" not in rendered


def test_disabled_primary_reads_as_disabled() -> None:
    rendered = str(
        steps.step_foot(
            "Siguiente", step=1, on_primary=rx.console_log("n"), primary_disabled=True
        ).render()
    )
    assert "aria-disabled" in rendered or "ariaDisabled" in rendered
    rule = re.search(r"\.q-step-primary:is\(:disabled, \[data-disabled\]\) \{(.*?)\}", _CSS, re.S)
    assert rule and "gray-a3" in rule.group(1) and "transform: none" in rule.group(1)


def test_back_is_a_thumb_target() -> None:
    assert ".q-step-foot .rt-Button.q-step-back { min-height: 44px; }" in _CSS


def test_sample_fields_have_visible_labels() -> None:
    from Qualify import styleguide_page as page

    for key, label, field_id in (
        ("negocio", "Nombre del negocio", "q-demo-business"),
        ("horario", "Tu horario", "q-demo-hours"),
        ("mensaje", "Tu mensaje", "q-demo-message"),
    ):
        rendered = str(page._frame_step(key).render())
        assert _has(rendered, label) and field_id in rendered and "htmlFor" in rendered


def test_loading_head_keeps_the_exit_but_never_invents_a_progress_number() -> None:
    head = str(
        steps.step_head(
            "Tu marca",
            step=5,
            total=5,
            back_label="Inicio",
            back_href="/",
            show_progress=False,
        )
    )
    assert "Inicio" in head and "Tu marca" in head
    assert "progressbar" not in head
    assert "Paso 5 de 5" not in head
