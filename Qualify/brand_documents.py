"""Brand documents in the Brand Kit wizard (§ request 2026-09-25): a BRIEF uploaded on
¿Quién es la marca? (and a BRANDBOARD source kept for its state), read by Claude through
the `proponer_brand_kit` tool (`qualify_api.creative.brief_ai`). The tool proposes, the
code verifies the quote against the document, and — since 2026-10-05 ("que las
propuestas se pongan directamente en donde van") — every verified change goes straight
into its field (`apply_directly`): no review panel. The person still decides, on the
fields themselves: Posicionamiento and Audiencia on the same screen, the lists on
¿Todo correcto?. The panel code (`proposals_panel`, `apply_proposals`) stays unused.

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
from collections.abc import AsyncIterator
from pathlib import PurePath
from uuid import uuid4

import reflex as rx
from qualify_api.claude_tools import ClaudeToolError, MissingAPIKey, api_key_from_env
from qualify_api.creative import brief_ai

from .auth_state import AuthState, brand_tenant_id
from .creative_state import CreativeState
from .tenant import tenant_uuid
from .ui import card, progress_panel, tone_badge
from .ui import tokens as T

logger = logging.getLogger(__name__)

BRIEF_UPLOAD_ID = "brand_brief"

#: What the brief's dropzone takes — every type `brief_ai.read_document` can read.
BRIEF_ACCEPT = {
    "application/pdf": [".pdf"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "text/plain": [".txt"],
    "text/markdown": [".md"],
    "image/*": [".png", ".jpg", ".jpeg", ".webp"],
}

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")

#: Which `CreativeState` var each proposal field writes, and how.
_TARGETS: dict[str, str] = {
    "positioning": "kit_positioning",
    "audience": "kit_audience",
    "do_examples": "kit_do_examples",
    "dont_examples": "kit_dont_examples",
    "cta_patterns": "kit_cta_patterns",
    "banned_words": "kit_banned_words",
    "forbidden_claims": "kit_forbidden_claims",
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
        do_examples=brief_ai.snapshot_lists(creative.kit_do_examples),
        dont_examples=brief_ai.snapshot_lists(creative.kit_dont_examples),
        cta_patterns=brief_ai.snapshot_lists(creative.kit_cta_patterns),
        banned_words=brief_ai.snapshot_lists(creative.kit_banned_words),
        forbidden_claims=brief_ai.snapshot_lists(creative.kit_forbidden_claims),
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
    """Write one accepted proposal into the kit field it belongs to. The tone axes are
    not among them (§ request 2026-09-29): a brief never moves the tone sliders."""
    setattr(creative, _TARGETS[field], value)


#: The two text fields a brief fills on ¿Quién es la marca? itself; the rest are lists.
_TEXT_FIELDS = frozenset({"positioning", "audience"})


def apply_directly(creative: CreativeState, proposals: list[brief_ai.FieldProposal]) -> list[str]:
    """Every verified proposal into its field, no review panel (§ request 2026-10-05).
    The proposals are always the same seven fields (`brief_ai.FIELDS`): the two texts are
    REPLACED (the brief describes the brand better than an empty or half-typed field),
    the five lists are MERGED — the brief's values are added after the ones already
    there, duplicates folded — so nothing typed by hand is lost. A proposal whose quote
    was not found in the document (`verified is False`) is left out. Returns the labels
    of the fields that changed, in order."""
    filled: list[str] = []
    for p in proposals:
        if p.verified is False or p.field not in _TARGETS:
            continue
        if p.field in _TEXT_FIELDS:
            assign(creative, p.field, p.proposed)
        else:
            current = getattr(creative, _TARGETS[p.field])
            assign(creative, p.field, _merge_lines(current, p.proposed))
        filled.append(p.label)
    return filled


def _merge_lines(current: str, proposed: str) -> str:
    """Two one-per-line lists as one: the current values first, then the new ones, each
    value once (compared case- and accent-insensitively)."""
    out: list[str] = []
    seen: set[str] = set()
    for line in (*current.splitlines(), *proposed.splitlines()):
        value = line.strip()
        key = brief_ai._fold(value) if value else ""
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return "\n".join(out)


#: How long a document's result stays on screen (§ request 2026-10-05: a pop-up, not a
#: message under the card) — long enough to read the fields it names.
_TOAST_MS = 7000


def notify(message: str, tone: str) -> rx.event.EventSpec | None:
    """A transient toast in the tone of `message` (docs/design-system.md §5.4,
    "confirmaciones transitorias → rx.toast"), or nothing for an empty one. Shared with
    Tipografía's detection, the other result that used to sit under its tile."""
    if not message:
        return None
    show = {"ok": rx.toast.success, "error": rx.toast.error, "warn": rx.toast.warning}.get(
        tone, rx.toast.info
    )
    return show(message, duration=_TOAST_MS)


def filled_message(labels: list[str]) -> str:
    """What the brief filled, said in one line under its card."""
    if not labels:
        return "El documento no trae cambios que podamos verificar en él."
    names = ", ".join(labels)
    return f"Rellenamos desde tu brief: {names}. Las listas las revisas en ¿Todo correcto?"


#: The brief's read, stage by stage, for its progress screen (§ request 2026-10-01: the
#: same screen as the voice analysis, with the steps). Real milestones, not a timer:
#: the Claude read is the long one and reports nothing until it is back.
_BRIEF_STAGE_TITLES = (
    ("preparing", "Preparamos el documento"),
    ("reading", "Leemos lo que dice de tu marca"),
    ("sorting", "Ordenamos lo encontrado"),
)
_BRIEF_STAGES = [stage for stage, _title in _BRIEF_STAGE_TITLES]
_BRIEF_STAGE_PERCENT = {"preparing": 8, "reading": 30, "sorting": 90}


class BrandDocumentState(rx.State):
    """The brief and the brandboard, and the changes they propose."""

    brief_name: str = ""
    brief_key: str = ""
    brief_busy: bool = False
    #: Where the brief's read is while `brief_busy`: "" | "preparing" | "reading" | "sorting".
    brief_stage: str = ""
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
    def brief_percent(self) -> int:
        return _BRIEF_STAGE_PERCENT.get(self.brief_stage, 0)

    @rx.var
    def brief_steps(self) -> list[dict[str, str]]:
        """The three stages for the progress screen, each done / running / pending."""
        current = _BRIEF_STAGES.index(self.brief_stage) if self.brief_stage in _BRIEF_STAGES else -1
        return [
            {
                "title": title,
                "status": "done" if i < current else "running" if i == current else "pending",
            }
            for i, (_stage, title) in enumerate(_BRIEF_STAGE_TITLES)
        ]

    def _set_stage(self, source: str, stage: str) -> None:
        if source == "brief":
            self.brief_stage = stage

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
        tenant_id = tenant_uuid(brand_tenant_id(auth))
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
            return notify(self.brief_message, self.brief_tone)
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
    async def analyze(self, source: str) -> AsyncIterator[rx.event.EventSpec | None]:
        """Claude reads the staged document with `proponer_brand_kit` and every verified
        change goes STRAIGHT into the field it belongs to (§ request 2026-10-05, "que las
        propuestas se pongan directamente en donde van, sin la mini view de la
        propuesta"): Posicionamiento and Audiencia on this same screen, the five lists on
        ¿Todo correcto?, where they are reviewed and edited (`apply_directly`). A proposal
        whose quote was NOT found in the document is still left out — it used to start
        unticked in the panel. What it filled pops up as a toast when it is done (§ request
        2026-10-05: no message left under the card). Background: a document read takes
        seconds."""
        async with self:
            key = self.brief_key if source == "brief" else self.brandboard_key
            if not key:
                return
            creative = await self.get_state(CreativeState)
            current = kit_snapshot(creative)
            self._set_busy(source, True)
            self._set_stage(source, "preparing")
            self._say(source, "Leyendo tu brief…")
        proposals: list[brief_ai.FieldProposal] = []
        message, tone = "", "neutral"
        try:
            data = await asyncio.to_thread((rx.get_upload_dir() / key).read_bytes)
            document = brief_ai.read_document(key, data)
            api_key = api_key_from_env()  # before the slow part: no key, no read
            async with self:
                self._set_stage(source, "reading")
            proposals, stats = await asyncio.to_thread(
                brief_ai.propose_kit_changes, document, current, source=source, api_key=api_key
            )
            async with self:
                self._set_stage(source, "sorting")
            logger.info(
                "brand documents: %s read by %s → %d proposals ($%.4f)",
                source,
                stats.model_revision or stats.model_id,
                len(proposals),
                stats.cost_usd,
            )
            if not proposals:
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
            if proposals:
                creative = await self.get_state(CreativeState)
                filled = apply_directly(creative, proposals)
                message, tone = filled_message(filled), "ok" if filled else "info"
            self.proposals = [r for r in self.proposals if r["source"] != source]
            self._set_busy(source, False)
            self._set_stage(source, "")
            self._say(source, message, tone)
        yield notify(message, tone)

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


def _value(value: rx.Var[str]) -> rx.Component:
    return rx.cond(
        value == "",
        rx.text("(vacío)", size="1", color=T.TEXT_FAINT),
        rx.text(value, size="1", white_space="pre-line"),
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
                _value(row["current"]),
                rx.text("Propuesta", size="1", color=T.TEXT_MUTED),
                _value(row["proposed"]),
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
        border_bottom=T.BORDER,
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
                    "Cambios que propone tu brief",
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
                        variant="soft",
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
    """Tu brief de marca: upload a brief and review what it fills in. While Claude reads
    it the whole block is the progress screen (§ request 2026-10-01), like the voice
    analysis — and the wizard's Continuar waits for it. Its result is a toast
    (`notify`), not a message under the card (§ request 2026-10-05)."""
    return rx.cond(
        BrandDocumentState.brief_busy,
        progress_panel(
            "Leyendo tu brief",
            "Claude lee el documento y rellena tu Brand Kit con lo que puede citar de él.",
            value=BrandDocumentState.brief_percent,
            steps=BrandDocumentState.brief_steps,
        ),
        _brief_card(),
    )


def _brief_card() -> rx.Component:
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
                            "Súbelo y rellenamos tu Brand Kit con lo que dice.",
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
        # no review panel since 2026-10-05: what the brief says goes straight into the
        # fields (`BrandDocumentState.analyze` → `apply_directly`)
        spacing="2",
        width="100%",
        align_items="start",
    )


# The brandboard document field that sat next to the logo (`brandboard_upload_field`) was
# removed on 2026-09-29 ("quita el tienes brief"): Tu brandboard's own dropzone takes the
# file now. The "brandboard" source in `BrandDocumentState` stays for its state/tests.
