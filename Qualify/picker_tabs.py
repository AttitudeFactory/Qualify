"""Keep the active source visible without moving the page or its keyboard focus."""

from __future__ import annotations

import json


def reveal_picker_tab_script(host_id: str) -> str:
    """Observe only one source bar, including restored selections and resizing."""
    return (
        "(() => { const bar = document.getElementById(" + json.dumps(host_id) + ");"
        "if (!bar) return; let frame = 0;"
        "const reveal = item => { if (!item || !bar.contains(item)) return;"
        "const b = bar.getBoundingClientRect(), r = item.getBoundingClientRect();"
        "if (r.left < b.left) bar.scrollLeft -= b.left-r.left;"
        "else if (r.right > b.right) bar.scrollLeft += r.right-b.right; };"
        "const stop = () => { changes.disconnect(); size.disconnect();"
        "bar.removeEventListener('focusin', focus); cancelAnimationFrame(frame); };"
        "const schedule = () => { cancelAnimationFrame(frame);"
        "frame = requestAnimationFrame(() => { if (!bar.isConnected) {stop(); return;}"
        "reveal(bar.querySelector('[role=radio][aria-checked=true], [data-state=on]')); }); };"
        "const focus = event => {reveal(event.target.closest('[role=radio]'));};"
        "const changes = new MutationObserver(schedule);"
        "const size = new ResizeObserver(schedule);"
        "changes.observe(bar, {subtree:true, childList:true, attributes:true,"
        "attributeFilter:['aria-checked','data-state']});"
        "size.observe(bar); bar.addEventListener('focusin', focus); schedule(); })()"
    )


def upload_host_id(target: str) -> str:
    """The box that holds a slot's «Subir» drop zone (always mounted, m-25017273)."""
    return f"picker-upload-{target}"


def open_upload_picker_script(bar_id: str, host_id: str) -> str:
    """m-25017273: a tap on «Subir» opens the file picker at once — no second tap on
    the drop zone. A native listener on the source bar clicks the zone's hidden file
    input INSIDE the tap itself (a phone opens a picker only from a real user gesture,
    never after a round trip to the server). Only a trusted click: Radix's arrow-key
    navigation clicks the radio by script, and that must not open a picker. Attached
    once per bar element."""
    return (
        "(() => { const bar = document.getElementById(" + json.dumps(bar_id) + ");"
        "if (!bar || bar.dataset.uploadOpener) return; bar.dataset.uploadOpener = '1';"
        "bar.addEventListener('click', event => { if (!event.isTrusted) return;"
        "if (!event.target.closest('[data-picker-tab=upload]')) return;"
        "const host = document.getElementById(" + json.dumps(host_id) + ");"
        "const input = host && host.querySelector('input[type=file]');"
        "if (input && !input.disabled) input.click(); }); })()"
    )
