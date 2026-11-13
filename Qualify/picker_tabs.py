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
