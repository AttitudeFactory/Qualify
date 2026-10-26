"""Human commands for the final-review panel, including pieces without dates."""

from __future__ import annotations

import asyncio
from uuid import UUID

import reflex as rx
from qualify_api.creative.final_review import FinalIdentity

from .auth_state import AuthState
from .final_review_provider import (
    candidate_ids,
    confirm_review,
    event_piece,
    failed_candidate_ids,
    load_final_panel,
    request_another,
    retry_review,
)
from .final_review_vm import FinalPanelVM
from .tenant import tenant_uuid


class FinalReviewState(rx.State):
    open: bool = False
    loading: bool = False
    busy: bool = False
    error: str = ""
    success: str = ""
    panel: FinalPanelVM = FinalPanelVM()
    _manifest: tuple[FinalIdentity, ...] = ()
    _load_token: int = 0

    async def _identity(self) -> tuple[UUID, UUID] | None:
        async with self:
            auth = await self.get_state(AuthState)
            tenant = tenant_uuid(auth.session_tenant_id)
            user = tenant_uuid(auth._session_user_id)
        return (tenant, user) if tenant is not None and user is not None else None

    async def _read(self, piece_id: UUID, *, clear_success: bool = True) -> None:
        ids = await self._identity()
        if ids is None:
            async with self:
                self.error = "Vuelve a iniciar sesión para revisar el video."
            return
        async with self:
            self.open = True
            self.loading = True
            self.error = ""
            if clear_success:
                self.success = ""
            self._manifest = ()
            self._load_token += 1
            token = self._load_token
        try:
            panel, manifest = await asyncio.to_thread(load_final_panel, ids[0], piece_id, ids[1])
        except (ValueError, PermissionError) as exc:
            async with self:
                if token == self._load_token:
                    self.error = str(exc)
                    self.panel = FinalPanelVM(piece_id=str(piece_id))
        except Exception:
            async with self:
                if token == self._load_token:
                    self.error = "No pudimos abrir el video. Inténtalo de nuevo en un momento."
        else:
            async with self:
                if token == self._load_token:
                    self.panel = panel
                    self._manifest = manifest
        finally:
            async with self:
                if token == self._load_token:
                    self.loading = False

    @rx.event(background=True)
    async def open_piece(self, piece_id: str) -> None:
        parsed = tenant_uuid(piece_id)
        if parsed is not None:
            await self._read(parsed)

    @rx.event(background=True)
    async def from_route(self) -> None:
        ids = await self._identity()
        if ids is None:
            return
        async with self:
            query = dict(self.router.url.query_parameters)
        if str(query.get("revisar", "")) != "videos":
            return
        raw = str(query.get("pieza", ""))
        piece = tenant_uuid(raw)
        if not raw:
            event = tenant_uuid(str(query.get("evento", "")))
            if event is not None:
                piece = await asyncio.to_thread(event_piece, ids[0], event)
            else:
                read_candidates = (
                    failed_candidate_ids if str(query.get("fallos", "")) == "1" else candidate_ids
                )
                values = await asyncio.to_thread(read_candidates, ids[0])
                piece = tenant_uuid(values[0]) if values else None
        if piece is None:
            async with self:
                self.open = True
                self.panel = FinalPanelVM()
                self.error = "No hay videos por confirmar en este negocio."
            return
        await self._read(piece)

    @rx.event(background=True)
    async def refresh(self, _tick: str = "") -> None:
        async with self:
            piece = tenant_uuid(self.panel.piece_id)
            refresh = (
                self.open
                and not self.busy
                and not self.loading
                and self.panel.state not in {"final", "final_ready"}
            )
        if refresh and piece is not None:
            await self._read(piece, clear_success=False)

    @rx.event
    def remember_history(self):
        if not self.open:
            return None
        return rx.call_script("""(()=>{
            if(!window.__qFinalBack){
                window.__qFinalBack=()=>document.getElementById('q-final-review-close')?.click();
                window.addEventListener('popstate',window.__qFinalBack);
            }
            if(!history.state?.qFinalReview)
                history.pushState({...history.state,qFinalReview:true},'',location.href);
        })()""")

    @rx.event
    def close(self):
        self.open = False
        self._manifest = ()
        self._load_token += 1
        return rx.call_script("""(()=>{
            const clear=()=>{
                const u=new URL(location.href);
                ['revisar','pieza','evento','fallos'].forEach(k=>u.searchParams.delete(k));
                history.replaceState(history.state,'',u.pathname+u.search);
            };
            if(history.state?.qFinalReview){history.back();setTimeout(clear,0);}else clear();
        })()""")

    @rx.event
    def change_open(self, value: bool):
        if not value:
            return self.close()
        return None

    @rx.event(background=True)
    async def confirm(self) -> None:
        ids = await self._identity()
        async with self:
            piece = tenant_uuid(self.panel.piece_id)
            expected = self._manifest
            if (
                ids is None
                or piece is None
                or self.busy
                or not self.panel.can_confirm
                or not expected
            ):
                return
            self.busy = True
            note = self.panel.confirmed_note
        try:
            await asyncio.to_thread(confirm_review, ids[0], piece, ids[1], expected)
        except (ValueError, PermissionError) as exc:
            async with self:
                self.error = str(exc)
        except Exception:
            async with self:
                self.error = "No pudimos confirmar el video. Inténtalo de nuevo."
        else:
            async with self:
                self.success = note
            await self._read(piece, clear_success=False)
        finally:
            async with self:
                self.busy = False

    @rx.event(background=True)
    async def another(self) -> None:
        ids = await self._identity()
        async with self:
            piece = tenant_uuid(self.panel.piece_id)
            if ids is None or piece is None or self.busy or not self.panel.can_another:
                return
            self.busy = True
        try:
            await asyncio.to_thread(request_another, ids[0], piece, ids[1])
            await self._read(piece)
        except (ValueError, PermissionError) as exc:
            async with self:
                self.error = str(exc)
        except Exception:
            async with self:
                self.error = "No pudimos pedir otra versión. Inténtalo de nuevo."
        finally:
            async with self:
                self.busy = False

    @rx.event(background=True)
    async def retry(self) -> None:
        ids = await self._identity()
        async with self:
            piece = tenant_uuid(self.panel.piece_id)
            if ids is None or piece is None or self.busy or not self.panel.can_retry:
                return
            self.busy = True
        try:
            await asyncio.to_thread(retry_review, ids[0], piece)
            await self._read(piece)
        except Exception:
            async with self:
                self.error = (
                    "No pudimos preparar el video final. Inténtalo de nuevo; no usa otro video."
                )
        finally:
            async with self:
                self.busy = False

    @rx.event(background=True)
    async def next_review(self) -> None:
        ids = await self._identity()
        if ids is None:
            return
        values = await asyncio.to_thread(candidate_ids, ids[0])
        async with self:
            others = [value for value in values if value != self.panel.piece_id]
        if others:
            await self._read(UUID(others[0]))
        else:
            async with self:
                self.close()

    @rx.event
    def choose_time(self):
        from .planner_state import PlannerState

        piece, event = self.panel.piece_id, self.panel.event_id
        cleanup = self.close()
        action = (
            PlannerState.open_reschedule(event)
            if event
            else PlannerState.open_assign_for_post(piece)
        )
        return [cleanup, action]
