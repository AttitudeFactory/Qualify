"""«‹ Tu semana» on a ficha opened from Tu semana (m-24842987, PUBLICAR-6, rule N7).

Tu semana opens a publication's ficha (`/drafts/<id>`) with `?desde=semana&semana=…&vista=…`
(`planner_vm.week_return_query`). The ficha reads that on load and, when it is there, its
way back says «‹ Tu semana» and returns to the same week, in the same view. Without it the
ficha keeps its own way back. A tiny state of its own, so the ficha's state (another
module's) is not touched for one link.
"""

from __future__ import annotations

import reflex as rx

from .planner_vm import BACK_TO_WEEK, back_to_week_href
from .ui import tokens as T

# N12: a target a thumb can hit on a phone.
_TOUCH_MIN = "44px"


class WeekBackState(rx.State):
    """Where «‹ Tu semana» goes on the current ficha; "" when it was not opened from there."""

    href: str = ""

    @rx.event
    def read(self) -> None:
        """on_load of a ficha: read `?desde=semana…` from the address."""
        try:
            params = self.router.url.query_parameters
        except Exception:  # noqa: BLE001 — no router outside a page (tests)
            params = {}
        self.href = back_to_week_href(params)


def back_to_week_link() -> rx.Component:
    """«‹ Tu semana»: the ficha's way back to the week and view it was opened from."""
    return rx.link(
        rx.button(
            rx.icon("chevron-left", size=T.ICON_MD),
            BACK_TO_WEEK,
            variant="ghost",
            size="3",
            min_height=_TOUCH_MIN,
        ),
        href=WeekBackState.href,
    )
