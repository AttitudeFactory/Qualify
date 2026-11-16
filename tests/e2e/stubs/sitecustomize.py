"""E2E-only stub: «Sugerir con IA» answers from a fixed list, never from Claude.

Loaded by Python at start-up only when this directory is on `PYTHONPATH` (the harness
adds it to the app it boots) AND `QUALIFY_E2E_FAKE_CAPTION_HASHTAGS=1`. It replaces
`qualify_api.hashtags.caption.suggest_for_caption` — the state imports it at call time —
so no paid call is made and the picks are known (m-25032581: two watched tags the text
does not name come first, to prove they never get «Mejor»).
"""

from __future__ import annotations

import os

if os.environ.get("QUALIFY_E2E_FAKE_CAPTION_HASHTAGS") == "1":
    # The editor only offers «Sugerir con IA» with a key. A placeholder one, and any
    # other Claude call of the booted app goes to a closed local port: nothing leaves
    # the machine, nothing is paid.
    os.environ.setdefault("QUALIFY_ANTHROPIC_API_KEY", "e2e-placeholder-never-valid")
    os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
    try:
        from qualify_api.hashtags import caption as _caption

        def _fake_suggest_for_caption(caption, **_kwargs):  # noqa: ANN001, ANN202
            pick = _caption.CaptionHashtag
            return [
                pick("carne", "nicho", "Tu texto nombra la carne", watched=True),
                pick("pollo", "nicho", "Tu texto nombra el pollo", watched=True),
                pick("recienhecho", "nicho", "Tu texto habla de algo recién hecho", watched=True),
                pick("cafeteria", "popular", "La buscan quienes quieren un café cerca"),
                pick("desayuno", "popular", "Muy usada por la mañana", seen_count=1200),
                pick("barrio", "marca", "Te encuentran los vecinos"),
                pick("cafedeespecialidad", "nicho", "Para quienes cuidan el café"),
                pick("tachira", "marca", "Tu zona"),
            ]

        _caption.suggest_for_caption = _fake_suggest_for_caption
    except Exception:  # noqa: BLE001, S110 — a stub must never stop the interpreter
        pass
