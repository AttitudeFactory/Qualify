"""m-25029799 (BU-A11, second part): WhatsApp's chats are attended only in «Por
responder»; the WhatsApp screen keeps its configuration («Tu número»).

Seeded by `chat_fixtures.seed_chats` (`chats_page`) plus a second WhatsApp number
(`seed_second_number`); nothing reaches Meta or R2 and nothing is sent: no test taps
«Enviar».

`test_capture_whatsapp_config_only` only takes screenshots (360 px and 1280 px, light and
dark) of the WhatsApp screen, of the old list address and of «Por responder» narrowed to
WhatsApp; it runs when `QUALIFY_E2E_SHOTS` names a directory (`QUALIFY_E2E_SHOTS_LABEL`
prefixes the files: «antes» on `origin/main`, «despues» on the branch).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from .conftest import expect

pytestmark = pytest.mark.e2e

PHONE = {"width": 360, "height": 780}
DESKTOP = {"width": 1280, "height": 800}

#: Where the owner is: the address, the page's title, the lit menu entries, the side
#: menu's «WhatsApp» and «Por responder» entries (where they lead and their badge), the
#: filters on screen and whether anything slides sideways.
_WHERE = """
() => {
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden';
  };
  const entry = (name) => {
    const a = [...document.querySelectorAll('a')]
      .find((el) => el.textContent.trim().startsWith(name) && el.closest('nav, aside'));
    return a ? { href: a.getAttribute('href'), text: a.textContent.trim() } : null;
  };
  const h1 = document.querySelector('h1');
  const groups = [...document.querySelectorAll('[role="group"]')].filter(shown)
    .map((g) => ({ label: g.getAttribute('aria-label'),
                   items: [...g.querySelectorAll('button')].filter(shown)
                     .map((b) => b.textContent.trim()) }));
  return {
    url: location.pathname + location.search,
    title: h1 ? h1.textContent.trim() : '',
    lit: [...document.querySelectorAll('[aria-current="page"]')].filter(shown)
      .map((el) => el.textContent.trim()),
    whatsappEntry: entry('WhatsApp'),
    respondEntry: entry('Por responder'),
    groups,
    rows: [...document.querySelectorAll('.q-conv-row')].filter(shown).length,
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  };
}
"""


def _origin(page) -> str:  # noqa: ANN001
    return page.url.split("/", 3)[0] + "//" + page.url.split("/", 3)[2]


def _settle(page) -> None:  # noqa: ANN001
    expect(page.locator("h1").first).to_be_visible(timeout=60_000)
    page.wait_for_timeout(2_500)


@pytest.mark.skipif(not os.environ.get("QUALIFY_E2E_SHOTS"), reason="QUALIFY_E2E_SHOTS not set")
def test_capture_whatsapp_config_only(chats_page) -> None:  # noqa: ANN001
    from .chat_fixtures import seed_second_number

    page = chats_page
    seed_second_number(page._qualify_e2e_tenant_id, page._qualify_e2e_user_id)
    out = Path(os.environ["QUALIFY_E2E_SHOTS"])
    out.mkdir(parents=True, exist_ok=True)
    label = os.environ.get("QUALIFY_E2E_SHOTS_LABEL", "shot")
    report: dict[str, object] = {}
    views = (
        ("whatsapp", "/whatsapp"),
        ("lista-vieja", "/whatsapp?tab=chats&filtro=abiertos"),
        ("por-responder-whatsapp", "/responder?tab=mensajes&canal=whatsapp&filtro=todos"),
    )
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        page.evaluate(f"localStorage.setItem('theme', '{scheme}')")
        for size_name, size in (("360", PHONE), ("1280", DESKTOP)):
            page.set_viewport_size(size)
            for name, address in views:
                page.goto(_origin(page) + address)
                _settle(page)
                key = f"{label}-{name}-{size_name}-{scheme}"
                page.screenshot(path=str(out / f"{key}.png"))
                report[key] = page.evaluate(_WHERE)
    (out / f"{label}-where.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8"
    )
