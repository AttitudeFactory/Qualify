"""The media sources' «Subir»: its always-mounted drop zone and the tap that opens
the file picker at once (m-25017273)."""

from __future__ import annotations

import json


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
