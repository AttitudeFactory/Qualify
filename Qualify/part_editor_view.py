"""UI-4's part sheet: the existing drawer, with the clip's existing media pickers."""

from __future__ import annotations

import reflex as rx
from qualify_creative.schemas import PART_DESCRIPTION_MAX

from . import part_editor_vm as vm
from .creative_state import CreativeState as S
from .r2_media import BACKEND_BASE
from .ui import callout, drawer
from .ui import tokens as T


def _choice(option: rx.Var) -> rx.Component:
    reason_id = "q-part-mode-reason-" + option["mode"]
    return rx.el.button(
        rx.flex(
            rx.icon(rx.cond(S.reel_edit_mode == option["mode"], "circle-dot", "circle"), size=18),
            rx.vstack(
                rx.text(option["label"], size="2", weight="medium"),
                rx.text(option["help"], size="1", color=T.TEXT_MUTED),
                rx.cond(
                    option["reason"] != "",
                    rx.text(
                        option["reason"],
                        size="1",
                        color=T.TEXT_MUTED,
                        id=reason_id,
                        class_name="q-choice-reason",
                    ),
                ),
                spacing="1",
                align_items="start",
                width="100%",
            ),
            align="start",
            gap="0.75rem",
            width="100%",
        ),
        type="button",
        role="radio",
        aria_checked=S.reel_edit_mode == option["mode"],
        tab_index=rx.cond(S.reel_edit_tab_mode == option["mode"], 0, -1),
        aria_disabled=option["reason"] != "",
        aria_describedby=rx.cond(option["reason"] != "", reason_id, ""),
        on_click=S.set_reel_edit_mode(option["mode"]),
        class_name=rx.cond(
            S.reel_edit_mode == option["mode"],
            "q-choice-card q-part-choice q-choice-card--on",
            "q-choice-card q-part-choice",
        ),
        width="100%",
        min_height="44px",
        padding="0.75rem",
        text_align="left",
        border=T.BORDER,
        border_radius=T.RADIUS_CONTROL,
        background=T.SURFACE_BG_RAISED,
        color=T.TEXT_STRONG,
        cursor=rx.cond(option["reason"] != "", "not-allowed", "pointer"),
    )


def part_editor(images: rx.Component, videos: rx.Component, audios: rx.Component) -> rx.Component:
    preview = S.reel_edit_preview
    form = rx.form(
        rx.vstack(
            rx.cond(
                preview["source"] != "",
                rx.video(
                    src=BACKEND_BASE
                    + preview["source"]
                    + "#t="
                    + preview["start"]
                    + ","
                    + preview["end"],
                    controls=True,
                    auto_play=False,
                    loop=False,
                    width="100%",
                    max_height="14rem",
                    aria_label="Vista previa de la parte " + S.reel_edit_index.to(str),
                ),
            ),
            rx.text(preview["seconds"] + " s", size="1", color=T.TEXT_MUTED),
            rx.vstack(
                rx.text(vm.QUESTION, weight="medium", size="3"),
                rx.foreach(S.reel_edit_options, _choice),
                id=vm.GROUP_ID,
                role="radiogroup",
                aria_label=vm.QUESTION,
                tab_index=-1,
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.cond(
                S.reel_merge_shown,
                rx.vstack(
                    rx.button(
                        "Juntar con la siguiente",
                        type="button",
                        variant="soft",
                        min_height="44px",
                        aria_disabled=S.reel_merge_reason != "",
                        aria_describedby="q-part-merge-reason",
                        on_click=S.merge_reel_part,
                    ),
                    rx.text(
                        S.reel_merge_reason, size="1", color=T.TEXT_MUTED, id="q-part-merge-reason"
                    ),
                    spacing="1",
                    width="100%",
                    align_items="start",
                ),
            ),
            rx.vstack(
                rx.el.label(vm.DESCRIPTION_LABEL, html_for="q-part-description"),
                rx.text_area(
                    value=S.reel_edit_text,
                    on_change=S.set_reel_edit_text,
                    name="description",
                    id="q-part-description",
                    max_length=PART_DESCRIPTION_MAX,
                    aria_describedby="q-part-description-example",
                    width="100%",
                    min_height="7rem",
                ),
                rx.text(
                    vm.DESCRIPTION_EXAMPLE,
                    size="1",
                    color=T.TEXT_MUTED,
                    id="q-part-description-example",
                ),
                spacing="1",
                width="100%",
                align_items="start",
            ),
            rx.text("Fotos de tu producto", size="3", weight="medium"),
            images,
            rx.button(
                rx.icon(rx.cond(S.reel_edit_more, "chevron-down", "chevron-right"), size=16),
                vm.MORE_LABEL,
                type="button",
                variant="ghost",
                min_height="44px",
                aria_expanded=S.reel_edit_more,
                aria_controls="q-part-more",
                on_click=S.toggle_reel_edit_more,
            ),
            rx.cond(
                S.reel_edit_more,
                rx.vstack(
                    rx.text("Video tuyo", size="2", weight="medium"),
                    videos,
                    rx.text("Audio tuyo", size="2", weight="medium"),
                    audios,
                    id="q-part-more",
                    spacing="3",
                    width="100%",
                    align_items="start",
                ),
            ),
            rx.cond(S.reel_edit_notice != "", callout(S.reel_edit_notice, "info")),
            rx.cond(S.reel_edit_error != "", callout(S.reel_edit_error, "warn")),
            spacing="3",
            width="100%",
            align_items="start",
            custom_attrs={"data-part-editor": "open"},
        ),
        id="q-part-editor-form",
        on_submit=S.save_reel_part,
        reset_on_submit=False,
        width="100%",
    )
    foot = rx.vstack(
        rx.text(S.reel_edit_save_reason, id="q-part-save-reason", size="1", color=T.TEXT_MUTED),
        rx.flex(
            rx.button(
                "Cancelar",
                variant="soft",
                color_scheme="gray",
                min_height="44px",
                on_click=S.set_reel_edit_open(False),
            ),
            rx.button(
                "Guardar",
                type="submit",
                custom_attrs={"form": "q-part-editor-form"},
                # aria-disabled keeps it focusable; save_reel_part ignores the click.
                aria_disabled=S.reel_edit_save_reason != "",
                aria_describedby="q-part-save-reason",
                min_height="44px",
                opacity=rx.cond(S.reel_edit_save_reason != "", "0.6", "1"),
                cursor=rx.cond(S.reel_edit_save_reason != "", "not-allowed", "pointer"),
            ),
            justify="end",
            gap="0.75rem",
            width="100%",
            wrap="wrap",
        ),
        width="100%",
        spacing="2",
        align_items="start",
    )
    return drawer(
        form,
        open=S.reel_edit_open,
        on_open_change=S.set_reel_edit_open,
        title=S.reel_edit_title,
        description=vm.SHEET_HELP,
        footer=foot,
        on_open_auto_focus=rx.call_script(
            "document.getElementById('q-part-editor-question')?.focus({preventScroll:true});"
        ).prevent_default,
        on_close_auto_focus=S.restore_reel_edit_focus.prevent_default,
    )
