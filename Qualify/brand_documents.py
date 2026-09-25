"""Brand documents in the Brand Kit wizard (§ request 2026-09-25): a BRIEF uploaded on
¿Quién es la marca? and a BRANDBOARD uploaded next to the logo, both read by Claude
through the `proponer_brand_kit` tool (`qualify_api.creative.brief_ai`) and shown as a
reviewable list of proposed changes — current value, proposed value, the quote it comes
from and whether that quote was found in the document. Nothing reaches the Brand Kit
until the operator ticks it and presses "Aplicar": the tool proposes, the code verifies,
the person decides.

Its own state, not `BrandWizardState`/`BrandConnectState`: both flows show the same
two documents, the wizard module is already the largest file of the app, and the kit
fields a proposal writes live in `CreativeState` anyway (`apply_proposals` writes them
there, the same fields the wizard's own steps edit).

Files are staged like the logo (`BrandWizardState.handle_logo_upload`): on local disk
under the tenant-namespaced upload dir, session-only — not persisted to the Brand Kit
row (the logo is not either; `brand_kits.logo_asset_key` has no writer yet).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import PurePath
from uuid import uuid4

import reflex as rx
from qualify_api.claude_tools import ClaudeToolError, MissingAPIKey, api_key_from_env
from qualify_api.creative import brief_ai

from .auth_state import AuthState
from .creative_state import CreativeState
from .tenant import tenant_uuid
from .ui import callout, card, loading_spinner, tone_badge
from .ui import tokens as T

logger = logging.getLogger(__name__)

BRIEF_UPLOAD_ID = "brand_brief"
BRANDBOARD_UPLOAD_ID = "brand_brandboard"

#: What the brief's dropzone takes — every type `brief_ai.read_document` can read.
BRIEF_ACCEPT = {
    "application/pdf": [".pdf"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "text/plain": [".txt"],
    "text/markdown": [".md"],
    "image/*": [".png", ".jpg", ".jpeg", ".webp"],
}
#: A brandboard is a visual sheet: an image or a PDF.
BRANDBOARD_ACCEPT = {
    "application/pdf": [".pdf"],
    "image/*": [".png", ".jpg", ".jpeg", ".webp"],
}

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")

#: Which `CreativeState` var each proposal field writes, and how.
_TARGETS: dict[str, str] = {
    "positioning": "kit_positioning",
    "audience": "kit_audience",
    "tone_formal_casual": "tone_formal_casual",
    "tone_sober_enthusiastic": "tone_sober_enthusiastic",
    "tone_technical_plain": "tone_technical_plain",
    "tone_brief_elaborate": "tone_brief_elaborate",
    "do_examples": "kit_do_examples",
    "dont_examples": "kit_dont_examples",
    "cta_patterns": "kit_cta_patterns",
    "banned_words": "kit_banned_words",
    "forbidden_claims": "kit_forbidden_claims",
    "palette": "kit_palette",
}

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_UPLOAD_FAILED = "No se pudo leer el archivo. Inténtalo de nuevo."
_NO_KEY = "La lectura con IA no está disponible: falta configurar la clave de Anthropic."
_AI_FAILED = "No pudimos leer el documento ahora. Inténtalo de nuevo en un momento."


def kit_snapshot(creative: CreativeState) -> brief_ai.KitSnapshot:
    """The Brand Kit as the wizard holds it right now — what proposals are diffed against."""
    return brief_ai.KitSnapshot(
        positioning=creative.kit_positioning,
        audience=creative.kit_audience,
        tone_formal_casual=creative.tone_formal_casual,
        tone_sober_enthusiastic=creative.tone_sober_enthusiastic,
        tone_technical_plain=creative.tone_technical_plain,
        tone_brief_elaborate=creative.tone_brief_elaborate,
        do_examples=brief_ai.snapshot_lists(creative.kit_do_examples),
        dont_examples=brief_ai.snapshot_lists(creative.kit_dont_examples),
        cta_patterns=brief_ai.snapshot_lists(creative.kit_cta_patterns),
        banned_words=brief_ai.snapshot_lists(creative.kit_banned_words),
        forbidden_claims=brief_ai.snapshot_lists(creative.kit_forbidden_claims),
        palette=brief_ai.snapshot_palette(creative.kit_palette),
    )


def proposal_rows(source: str, proposals: list[brief_ai.FieldProposal]) -> list[dict[str, str]]:
    """Verified proposals → the rows the review panel renders. A proposal whose quote
    was NOT found in the document starts unticked; everything else starts ticked."""
    rows = []
    for p in proposals:
        verified = "na" if p.verified is None else ("si" if p.verified else "no")
        rows.append(
            {
                "source": source,
                "field": p.field,
                "label": p.label,
                "current": p.current,
                "proposed": p.proposed,
                "evidence": p.evidence,
                "verified": verified,
                "accepted": "0" if verified == "no" else "1",
            }
        )
    return rows


def assign(creative: CreativeState, field: str, value: str) -> None:
    """Write one accepted proposal into the kit field it belongs to."""
    target = _TARGETS[field]
    if target.startswith("tone_"):
        setattr(creative, target, max(0, min(100, int(value))))
    else:
        setattr(creative, target, value)


class BrandDocumentState(rx.State):
    """The brief and the brandboard, and the changes they propose."""

    brief_name: str = ""
    brief_key: str = ""
    brief_busy: bool = False
    #: What the brief's card says under the button — `brief_tone` colours it.
    brief_message: str = ""
    brief_tone: str = "neutral"

    brandboard_name: str = ""
    brandboard_key: str = ""
    brandboard_is_image: bool = False
    brandboard_busy: bool = False
    brandboard_message: str = ""
    brandboard_tone: str = "neutral"

    #: Every pending proposal from either document (`proposal_rows` shape).
    proposals: list[dict[str, str]] = []

    @rx.var
    def brief_proposals(self) -> list[dict[str, str]]:
        return [row for row in self.proposals if row["source"] == "brief"]

    @rx.var
    def brandboard_proposals(self) -> list[dict[str, str]]:
        return [row for row in self.proposals if row["source"] == "brandboard"]

    def _say(self, source: str, message: str, tone: str = "neutral") -> None:
        if source == "brief":
            self.brief_message, self.brief_tone = message, tone
        else:
            self.brandboard_message, self.brandboard_tone = message, tone

    def _set_busy(self, source: str, busy: bool) -> None:
        if source == "brief":
            self.brief_busy = busy
        else:
            self.brandboard_busy = busy

    async def _stage(self, source: str, files: list[rx.UploadFile]) -> str | None:
        """Save the upload under the tenant's namespace; the key, or None on failure
        (the message is already set)."""
        auth = await self.get_state(AuthState)
        tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            self._say(source, _NO_SESSION, "error")
            return None
        upload = files[0]
        try:
            data = await upload.read()
        except Exception:  # noqa: BLE001 — any read failure is the same message
            self._say(source, _UPLOAD_FAILED, "error")
            return None
        name = PurePath(upload.name or source).name
        try:
            brief_ai.read_document(name, data)  # refuse early what the model cannot read
        except brief_ai.UnsupportedDocument as exc:
            self._say(source, f"No podemos leer este archivo: {exc}.", "error")
            return None
        key = f"uploads/{tenant_id}/{source}/{uuid4().hex}_{name}"
        target = rx.get_upload_dir() / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    @rx.event
    async def handle_brief_upload(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """FOREGROUND (uploads cannot be background handlers): stage the file, then hand
        the reading to the background `analyze`."""
        if not files:
            return None
        key = await self._stage("brief", files)
        if key is None:
            return None
        self.brief_key = key
        self.brief_name = PurePath(key).name.split("_", 1)[-1]
        return BrandDocumentState.analyze("brief")

    @rx.event
    async def handle_brandboard_upload(
        self, files: list[rx.UploadFile]
    ) -> rx.event.EventSpec | None:
        if not files:
            return None
        key = await self._stage("brandboard", files)
        if key is None:
            return None
        self.brandboard_key = key
        self.brandboard_name = PurePath(key).name.split("_", 1)[-1]
        self.brandboard_is_image = PurePath(key).suffix.lower() in _IMAGE_SUFFIXES
        return BrandDocumentState.analyze("brandboard")

    @rx.event(background=True)
    async def analyze(self, source: str) -> None:
        """Claude reads the staged document with `proponer_brand_kit` and the verified
        changes land in the review panel. Background: a document read takes seconds."""
        async with self:
            key = self.brief_key if source == "brief" else self.brandboard_key
            if not key:
                return
            creative = await self.get_state(CreativeState)
            current = kit_snapshot(creative)
            self._set_busy(source, True)
            what = "tu brief" if source == "brief" else "tu brandboard"
            self._say(source, f"Leyendo {what}…")
        rows: list[dict[str, str]] = []
        message, tone = "", "neutral"
        try:
            data = await asyncio.to_thread((rx.get_upload_dir() / key).read_bytes)
            document = brief_ai.read_document(key, data)
            api_key = api_key_from_env()
            proposals, stats = await asyncio.to_thread(
                brief_ai.propose_kit_changes, document, current, source=source, api_key=api_key
            )
            rows = proposal_rows(source, proposals)
            logger.info(
                "brand documents: %s read by %s → %d proposals ($%.4f)",
                source,
                stats.model_revision or stats.model_id,
                len(rows),
                stats.cost_usd,
            )
            if rows:
                message = "Revisa lo que encontramos y aplica lo que quieras."
            else:
                message, tone = "El documento no trae cambios para tu Brand Kit.", "info"
        except MissingAPIKey:
            message, tone = _NO_KEY, "warn"
        except brief_ai.UnsupportedDocument as exc:
            message, tone = f"No podemos leer este archivo: {exc}.", "error"
        except (ClaudeToolError, OSError) as exc:
            logger.warning("brand documents: %s could not be read: %s", source, exc)
            message, tone = _AI_FAILED, "error"
        except Exception as exc:  # noqa: BLE001 — SDK/transport errors: never crash the step
            logger.warning("brand documents: %s failed: %s", source, exc)
            message, tone = _AI_FAILED, "error"
        async with self:
            self.proposals = [r for r in self.proposals if r["source"] != source] + rows
            self._set_busy(source, False)
            self._say(source, message, tone)

    @rx.event
    def toggle_proposal(self, source: str, field: str) -> None:
        self.proposals = [
            {**row, "accepted": "0" if row["accepted"] == "1" else "1"}
            if row["source"] == source and row["field"] == field
            else row
            for row in self.proposals
        ]

    @rx.event
    async def apply_proposals(self, source: str) -> None:
        """Write the ticked proposals into the Brand Kit fields (`CreativeState`), drop
        this document's pending list, and say how many landed."""
        creative = await self.get_state(CreativeState)
        applied = 0
        for row in self.proposals:
            if row["source"] == source and row["accepted"] == "1":
                assign(creative, row["field"], row["proposed"])
                applied += 1
        self.proposals = [r for r in self.proposals if r["source"] != source]
        if applied:
            plural = "cambio" if applied == 1 else "cambios"
            self._say(source, f"Aplicamos {applied} {plural}. Revísalos en cada paso.", "ok")
        else:
            self._say(source, "No aplicamos nada: no marcaste ningún cambio.")

    @rx.event
    def discard_proposals(self, source: str) -> None:
        self.proposals = [r for r in self.proposals if r["source"] != source]
        self._say(source, "")

    @rx.event
    def clear_brandboard(self) -> None:
        self.brandboard_key = ""
        self.brandboard_name = ""
        self.brandboard_is_image = False
        self.proposals = [r for r in self.proposals if r["source"] != "brandboard"]
        self._say("brandboard", "")

    @rx.event
    def reset_documents(self) -> None:
        """Both flows' finish: the next Brand Kit starts without the previous files."""
        self.reset()


# --------------------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------------------


def _status(busy: rx.Var[bool], message: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    return rx.cond(
        busy,
        rx.hstack(
            loading_spinner("sm"),
            rx.text(message, size="1", color=T.TEXT_MUTED),
            spacing="2",
            align="center",
        ),
        rx.cond(
            message != "",
            rx.match(
                tone,
                ("error", callout(message, "error")),
                ("warn", callout(message, "warn")),
                ("ok", callout(message, "ok")),
                rx.text(message, size="1", color=T.TEXT_MUTED),
            ),
        ),
    )


def _swatches(value: rx.Var[str]) -> rx.Component:
    return rx.flex(
        rx.foreach(
            value.to(str).split(","),
            lambda colour: rx.box(
                width="1.25rem",
                height="1.25rem",
                border_radius="4px",
                background=colour,
                border=f"1px solid {rx.color('gray', 6)}",
                title=colour,
            ),
        ),
        gap="1",
        wrap="wrap",
    )


def _value(field: rx.Var[str], value: rx.Var[str]) -> rx.Component:
    return rx.cond(
        value == "",
        rx.text("(vacío)", size="1", color=T.TEXT_FAINT),
        rx.cond(
            field == "palette",
            _swatches(value),
            rx.text(value, size="1", white_space="pre-line"),
        ),
    )


def _proposal_row(row: rx.Var[dict[str, str]]) -> rx.Component:
    return rx.hstack(
        rx.checkbox(
            checked=row["accepted"] == "1",
            on_change=lambda _checked: BrandDocumentState.toggle_proposal(
                row["source"], row["field"]
            ),
            size="2",
            margin_top="0.2rem",
        ),
        rx.vstack(
            rx.hstack(
                rx.text(row["label"], size="2", weight="medium"),
                rx.match(
                    row["verified"],
                    ("si", tone_badge("Cita verificada", "ok", icon="check")),
                    ("no", tone_badge("No hallamos la cita", "warn", icon="triangle-alert")),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            rx.grid(
                rx.text("Ahora", size="1", color=T.TEXT_MUTED),
                _value(row["field"], row["current"]),
                rx.text("Propuesta", size="1", color=T.TEXT_MUTED),
                _value(row["field"], row["proposed"]),
                columns="5.5rem 1fr",
                gap_x="2",
                gap_y="1",
                width="100%",
            ),
            rx.cond(
                row["evidence"] != "",
                rx.text(
                    "“", row["evidence"], "”", size="1", color=T.TEXT_MUTED, font_style="italic"
                ),
            ),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        spacing="3",
        align="start",
        width="100%",
        padding_y="0.5rem",
        border_bottom=f"1px solid {rx.color('gray', 4)}",
    )


def proposals_panel(source: str) -> rx.Component:
    """The review list for one document: tick what to keep, then Aplicar."""
    rows = (
        BrandDocumentState.brief_proposals
        if source == "brief"
        else BrandDocumentState.brandboard_proposals
    )
    return rx.cond(
        rows.length() > 0,
        card(
            rx.vstack(
                rx.text(
                    "Cambios que propone tu " + ("brief" if source == "brief" else "brandboard"),
                    size="2",
                    weight="bold",
                ),
                rx.scroll_area(
                    rx.vstack(rx.foreach(rows, _proposal_row), spacing="0", width="100%"),
                    type="auto",
                    scrollbars="vertical",
                    max_height="16rem",
                ),
                rx.hstack(
                    rx.button(
                        rx.icon("check", size=T.ICON_SM),
                        "Aplicar seleccionados",
                        on_click=BrandDocumentState.apply_proposals(source),
                        size="2",
                    ),
                    rx.button(
                        "Descartar",
                        on_click=BrandDocumentState.discard_proposals(source),
                        variant="soft",
                        color_scheme="gray",
                        size="2",
                    ),
                    spacing="2",
                ),
                spacing="3",
                width="100%",
                align_items="start",
            ),
            padding="1rem",
            width="100%",
        ),
    )


def brief_upload_card() -> rx.Component:
    """¿Quién es la marca?'s shortcut: upload a brief and review what it fills in."""
    return rx.vstack(
        card(
            rx.hstack(
                rx.icon("file-text", size=20, color=T.TEXT_MUTED),
                rx.vstack(
                    rx.text("¿Tienes un brief de marca?", size="2", weight="medium"),
                    rx.text(
                        rx.cond(
                            BrandDocumentState.brief_name != "",
                            BrandDocumentState.brief_name,
                            "Súbelo y te proponemos cómo rellenar tu Brand Kit.",
                        ),
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="0",
                    align_items="start",
                ),
                rx.spacer(),
                rx.upload(
                    rx.button(
                        rx.icon("upload", size=T.ICON_SM),
                        rx.cond(BrandDocumentState.brief_name != "", "Cambiar", "Subir brief"),
                        variant="soft",
                        size="2",
                        disabled=BrandDocumentState.brief_busy,
                    ),
                    id=BRIEF_UPLOAD_ID,
                    accept=BRIEF_ACCEPT,
                    max_files=1,
                    max_size=brief_ai.MAX_DOCUMENT_BYTES,
                    on_drop=BrandDocumentState.handle_brief_upload(
                        rx.upload_files(upload_id=BRIEF_UPLOAD_ID)
                    ),
                    border="none",
                    padding="0",
                ),
                align="center",
                spacing="3",
                width="100%",
            ),
            padding="0.75rem 1rem",
            width="100%",
        ),
        _status(
            BrandDocumentState.brief_busy,
            BrandDocumentState.brief_message,
            BrandDocumentState.brief_tone,
        ),
        proposals_panel("brief"),
        spacing="2",
        width="100%",
        align_items="start",
    )


def brandboard_upload_field() -> rx.Component:
    """Next to the logo (§ request 2026-09-25): an optional brandboard, read for its
    colours and style and reviewed like the brief."""
    return rx.vstack(
        rx.text("¿Tienes un brandboard? (opcional)", size="2", weight="medium"),
        rx.cond(
            BrandDocumentState.brandboard_key == "",
            rx.upload(
                rx.hstack(
                    rx.icon("layout-template", size=18, color=T.TEXT_FAINT),
                    rx.text("Súbelo y leemos sus colores y su estilo", size="2"),
                    rx.text("PNG, JPG, WEBP o PDF", size="1", color=T.TEXT_FAINT),
                    align="center",
                    spacing="2",
                    wrap="wrap",
                ),
                id=BRANDBOARD_UPLOAD_ID,
                accept=BRANDBOARD_ACCEPT,
                max_files=1,
                max_size=brief_ai.MAX_DOCUMENT_BYTES,
                on_drop=BrandDocumentState.handle_brandboard_upload(
                    rx.upload_files(upload_id=BRANDBOARD_UPLOAD_ID)
                ),
                border=f"1px dashed {rx.color('gray', 7)}",
                border_radius=T.RADIUS_CARD,
                padding="1rem",
                width="100%",
            ),
            card(
                rx.hstack(
                    rx.cond(
                        BrandDocumentState.brandboard_is_image,
                        rx.image(
                            src=rx.get_upload_url(BrandDocumentState.brandboard_key),
                            alt="Vista previa del brandboard",
                            height="3rem",
                            width="4.5rem",
                            object_fit="cover",
                            border_radius=T.RADIUS_CONTROL,
                        ),
                        rx.icon("file-text", size=28, color=T.TEXT_MUTED),
                    ),
                    rx.text(BrandDocumentState.brandboard_name, size="2", weight="medium"),
                    rx.spacer(),
                    rx.button(
                        rx.icon("trash-2", size=T.ICON_SM),
                        "Quitar",
                        variant="soft",
                        color_scheme=T.tone_scale("error"),
                        size="2",
                        on_click=BrandDocumentState.clear_brandboard,
                    ),
                    align="center",
                    spacing="3",
                    width="100%",
                ),
                padding="0.75rem 1rem",
                width="100%",
            ),
        ),
        _status(
            BrandDocumentState.brandboard_busy,
            BrandDocumentState.brandboard_message,
            BrandDocumentState.brandboard_tone,
        ),
        proposals_panel("brandboard"),
        spacing="2",
        width="100%",
        align_items="start",
    )
