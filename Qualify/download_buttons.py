"""The download buttons of a piece, shared by the draft screen (`creative_pages`) and the
generator's result (`content_generator`) — the two places a piece is downloaded.

`download_script` saves a URL under a name: it fetches the file and saves the blob,
since a browser ignores `<a download>` for another origin (the backend on its own port)
and just opens the file; when the origin refuses, it opens in a new tab instead. The code
travels with the click (m-24828908): it used to define `window.qualifyDownload` in an
`rx.script` that React mounts but never runs, so every «Descargar» did nothing.
"""

from __future__ import annotations

import reflex as rx

from .r2_media import BACKEND_BASE

_DOWNLOAD_JS = (
    "(async (url, name) => {"
    " try {"
    ' const response = await fetch(url, { mode: "cors", credentials: "omit" });'
    " if (!response.ok) throw new Error(String(response.status));"
    " const href = URL.createObjectURL(await response.blob());"
    ' const link = document.createElement("a");'
    " link.href = href; link.download = name;"
    " document.body.appendChild(link); link.click(); link.remove();"
    " setTimeout(() => URL.revokeObjectURL(href), 5000);"
    ' } catch (error) { window.open(url, "_blank", "noopener"); }'
    " })"
)


def download_script(url: rx.Var | str, name: rx.Var | str) -> rx.event.EventSpec:
    """Save `url` as `name` — the click runs this, nothing has to be loaded first."""
    return rx.call_script(f"{_DOWNLOAD_JS}('{url}', '{name}')")


def piece_download_button(
    path: rx.Var[str],
    name: rx.Var[str],
    *,
    file_url: rx.Var[str] | None = None,
    file_name: rx.Var[str] | str = "",
) -> rx.Component:
    """THE «Descargar» of a piece (m-24828908, § request 2026-10-21: «un solo botón»): the
    piece's files and its words (`texto.txt`) in one .zip — never the prompt. `path` is
    `DraftVM.download_path`; while it is "" (no token could be minted) the button falls
    back to the one file at `file_url`, as it did before, or is not shown without one."""
    button = rx.button(
        rx.icon("download", size=15),
        "Descargar",
        variant="soft",
        size="2",
        title="Archivos, título, descripción, hashtags y CTA en un .zip",
        on_click=download_script((BACKEND_BASE + path).to(str), name),
    )
    if file_url is None:
        return rx.cond(path != "", button)
    return rx.cond(
        path != "",
        button,
        rx.button(
            rx.icon("download", size=15),
            "Descargar",
            variant="soft",
            size="2",
            on_click=download_script(file_url, file_name),
        ),
    )
