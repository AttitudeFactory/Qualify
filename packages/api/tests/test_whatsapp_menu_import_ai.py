"""«Cargar mi menú desde una foto o desde mi página» (m-24936840), offline: a fake Claude
client, a fake fetch, a fake resolver and httpx's MockTransport."""

from __future__ import annotations

import io
import re
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from PIL import Image

from qualify_api.claude_tools import FIRST_TURN_MARGIN_TOKENS, turn_input_ceiling, worst_turn_usd
from qualify_api.creative import brief_ai
from qualify_api.whatsapp.menus import import_ai
from qualify_api.whatsapp.menus.import_ai import (
    IMPORT_BUDGET_USD,
    MAX_MEDIA_INPUT_TOKENS,
    MAX_PAGE_CHARS,
    MAX_TOKENS,
    REASON_BAD_LINK,
    REASON_SOCIAL,
    REASON_TOO_BIG,
    REASON_TOO_LONG,
    REASON_TYPE,
    REASON_UNREADABLE_PHOTO,
    SYSTEM_PROMPT,
    TOOL_NAME,
    WARN_TRUNCATED,
    FetchedPage,
    ImportSource,
    ImportUnavailable,
    NothingFound,
    SourceUnsupported,
    default_fetch,
    parse_amount,
    parse_currency,
    propose_menu_facts,
    read_source,
)

# --- fakes --------------------------------------------------------------------------------


class FakeMessages:
    def __init__(self, responses: list[Any], counted: int) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.counts: list[dict[str, Any]] = []
        self.counted = counted

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def count_tokens(self, **kwargs: Any) -> Any:
        self.counts.append(kwargs)
        return SimpleNamespace(input_tokens=self.counted)


class FakeClient:
    def __init__(self, responses: list[Any], *, counted: int = 3_000) -> None:
        self.messages = FakeMessages(responses, counted)

    def factory(self, key: str) -> FakeClient:
        return self


def _answer(
    facts: list[dict[str, str]] | None = None,
    products: list[dict[str, str]] | None = None,
    *,
    stop: str = "tool_use",
    tool: bool = True,
) -> Any:
    content: list[Any] = []
    if tool:
        content.append(
            SimpleNamespace(
                type="tool_use",
                name=TOOL_NAME,
                input={"facts": facts or [], "products": products or []},
            )
        )
    else:
        content.append(SimpleNamespace(type="text", text="no sé"))
    return SimpleNamespace(
        model="claude-sonnet-5-5-20261001",
        stop_reason=stop,
        usage=SimpleNamespace(input_tokens=2_500, output_tokens=700, cache_read_input_tokens=0),
        content=content,
    )


def _fact(key: str, value: str, evidence: str) -> dict[str, str]:
    return {"key": key, "value": value, "evidence": evidence}


def _product(name: str, price: str, evidence: str, description: str = "") -> dict[str, str]:
    return {"name": name, "price_text": price, "description": description, "evidence": evidence}


def _png(size: tuple[int, int] = (64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << >>\n%%EOF\n"

PAGE = """<!doctype html><html><head><title>Bianki Shawarma</title>
<meta name="description" content="Shawarma y ensaladas en Cúcuta. Domicilios gratis en el centro.">
<style>body { color: red }</style><script>var horario = "24 horas";</script></head>
<body><nav>Inicio | Menú | Contacto</nav>
<h1>Bianki</h1><p>Horario: Lun a Sáb 12m – 10pm</p>
<p>Dirección: Av. 0 # 12-34, Barrio Blanco, Cúcuta</p>
<ul><li>Shawarma mixto $18.000</li><li>Ensalada César COP 15.000</li><li>Limonada</li></ul>
<p>Pagos: Efectivo, Nequi y transferencia</p></body></html>"""


def _page_fetch(body: str = PAGE, content_type: str = "text/html") -> Any:
    seen: list[str] = []

    def fetch(url: str) -> FetchedPage:
        seen.append(url)
        return FetchedPage(url, content_type, "utf-8", body.encode("utf-8"))

    fetch.seen = seen  # type: ignore[attr-defined]
    return fetch


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", "test-key")


# --- image --------------------------------------------------------------------------------


def test_image_happy_path_sends_the_photo_and_proposes_with_a_check_warning() -> None:
    client = FakeClient(
        [
            _answer(
                [
                    _fact(
                        "hours",
                        "de lunes a domingo, de 12:00 m. a 10:00 p. m.",
                        "Lun a Dom 12m - 10pm",
                    ),
                    _fact("payment_methods", "Pago móvil y efectivo", "Pago móvil · Efectivo"),
                ],
                [_product("Shawarma mixto", "6 $", "Shawarma mixto ....... 6 $")],
            )
        ]
    )
    proposal = propose_menu_facts(
        ImportSource(filename="IMG_0001.png", data=_png()), client_factory=client.factory
    )
    assert proposal.source_kind == "image" and proposal.source_label == "IMG_0001.png"
    assert [f.key for f in proposal.facts] == ["hours", "payment_methods"]
    product = proposal.products[0]
    assert product.price_amount == Decimal("6") and product.price_currency == ""  # bare «$»
    assert any("Revisa cada dato con tu foto" in w for w in proposal.warnings)
    assert proposal.model_id == "claude-sonnet-5-5" and proposal.prompt_version == "wa-import-1"
    assert proposal.input_tokens == 2_500 and proposal.output_tokens == 700
    call = client.messages.calls[0]
    blocks = call["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png"
    assert call["model"] == "claude-sonnet-5-5"
    assert call["output_config"] == {"effort": "low"}
    assert client.messages.counts, "a photo is measured before the paid call"


def test_the_type_comes_from_the_bytes_not_the_name() -> None:
    doc = read_source(ImportSource(filename="menu.jpg", data=_png()))
    assert doc.kind == "image" and doc.blocks[0]["source"]["media_type"] == "image/png"


def test_a_big_image_is_downscaled_by_the_brief_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brief_ai, "MAX_IMAGE_BYTES", 100)
    doc = read_source(ImportSource(filename="menu.png", data=_png((300, 300))))
    assert doc.blocks[0]["source"]["media_type"] == "image/jpeg"


def test_unsupported_type_too_big_empty_and_broken_photo() -> None:
    with pytest.raises(SourceUnsupported, match=re.escape(REASON_TYPE)):
        read_source(ImportSource(filename="menu.docx", data=b"PK\x03\x04 a word file"))
    with pytest.raises(SourceUnsupported, match=re.escape(REASON_TYPE)):
        read_source(ImportSource(filename="menu.gif", data=b"GIF89a......"))
    with pytest.raises(SourceUnsupported) as big:
        read_source(ImportSource(filename="menu.png", data=b"\x89PNG" + b"0" * (10 * 1024 * 1024)))
    assert str(big.value) == REASON_TOO_BIG
    with pytest.raises(SourceUnsupported, match=re.escape(REASON_UNREADABLE_PHOTO)):
        read_source(ImportSource(filename="menu.png", data=b""))
    with pytest.raises(SourceUnsupported, match=re.escape(REASON_UNREADABLE_PHOTO)):
        read_source(ImportSource(filename="menu.png", data=b"\x89PNG\r\n\x1a\n broken"))


def test_exactly_one_source() -> None:
    with pytest.raises(SourceUnsupported):
        read_source(ImportSource())
    with pytest.raises(SourceUnsupported):
        read_source(ImportSource(filename="a.png", data=_png(), url="https://bianki.com"))


# --- PDF ----------------------------------------------------------------------------------


def test_pdf_inline_path() -> None:
    client = FakeClient(
        [_answer([_fact("reservations", "Sí, por WhatsApp", "Reservas por WhatsApp")])]
    )
    proposal = propose_menu_facts(
        ImportSource(filename="carta.pdf", data=PDF), client_factory=client.factory
    )
    assert proposal.source_kind == "pdf"
    assert any("tu archivo" in w for w in proposal.warnings)
    block = client.messages.calls[0]["messages"][0]["content"][0]
    assert block["type"] == "document" and block["source"]["media_type"] == "application/pdf"


def test_a_heavy_pdf_goes_through_the_files_api_and_is_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(brief_ai, "INLINE_PDF_MAX_BYTES", 10)
    uploads: list[tuple[str, bytes]] = []
    deleted: list[str] = []
    monkeypatch.setattr(
        import_ai,
        "_upload_pdf",
        lambda client, name, data: uploads.append((name, data)) or "file_1",
    )
    monkeypatch.setattr(import_ai, "_delete_file", lambda client, fid: deleted.append(fid))
    client = FakeClient([_answer([_fact("address", "Av. 0 # 12-34", "Av. 0 # 12-34, Cúcuta")])])
    propose_menu_facts(ImportSource(filename="carta.pdf", data=PDF), client_factory=client.factory)
    assert uploads == [("carta.pdf", PDF)] and deleted == ["file_1"]
    block = client.messages.calls[0]["messages"][0]["content"][0]
    assert block == {"type": "document", "source": {"type": "file", "file_id": "file_1"}}


def test_the_uploaded_pdf_is_deleted_even_when_the_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(brief_ai, "INLINE_PDF_MAX_BYTES", 10)
    deleted: list[str] = []
    monkeypatch.setattr(import_ai, "_upload_pdf", lambda *a: "file_2")
    monkeypatch.setattr(import_ai, "_delete_file", lambda client, fid: deleted.append(fid))
    client = FakeClient([ConnectionError("down")])
    with pytest.raises(ImportUnavailable):
        propose_menu_facts(ImportSource(filename="c.pdf", data=PDF), client_factory=client.factory)
    assert deleted == ["file_2"]


def test_a_too_long_pdf_is_refused_before_any_paid_call() -> None:
    client = FakeClient([], counted=MAX_MEDIA_INPUT_TOKENS + 1)
    with pytest.raises(SourceUnsupported, match=re.escape(REASON_TOO_LONG)):
        propose_menu_facts(ImportSource(filename="c.pdf", data=PDF), client_factory=client.factory)
    assert client.messages.calls == []


def test_the_upload_cap_is_below_the_inline_pdf_limit() -> None:
    # so in practice every PDF travels inline; the Files API branch is a safety net
    assert import_ai.MAX_UPLOAD_BYTES < brief_ai.INLINE_PDF_MAX_BYTES


# --- URL ----------------------------------------------------------------------------------


def test_url_path_html_to_text_and_verified_quotes() -> None:
    fetch = _page_fetch()
    client = FakeClient(
        [
            _answer(
                [
                    _fact(
                        "hours",
                        "de lunes a sábado, de 12:00 m. a 10:00 p. m.",
                        "Horario: Lun a Sáb 12m – 10pm",
                    ),
                    _fact(
                        "payment_methods",
                        "Efectivo, Nequi y transferencia",
                        "Efectivo, Nequi y transferencia",
                    ),
                    _fact("delivery_zone", "El centro de Cúcuta", "Domicilios gratis en el centro"),
                ],
                [
                    _product("Shawarma mixto", "$18.000", "Shawarma mixto $18.000"),
                    _product("Ensalada César", "COP 15.000", "Ensalada César COP 15.000"),
                    _product("Limonada", "", "Limonada"),
                ],
            )
        ]
    )
    proposal = propose_menu_facts(
        ImportSource(url="www.bianki.com/menu"), client_factory=client.factory, fetch=fetch
    )
    assert fetch.seen == ["https://www.bianki.com/menu"]
    assert proposal.source_kind == "url" and proposal.source_label == "bianki.com"
    assert [f.key for f in proposal.facts] == ["hours", "delivery_zone", "payment_methods"]
    by_name = {p.name: p for p in proposal.products}
    assert by_name["Shawarma mixto"].price_amount == Decimal("18000")
    assert by_name["Shawarma mixto"].price_currency == ""
    assert by_name["Ensalada César"].price_currency == "COP"
    assert by_name["Limonada"].price_amount is None
    assert proposal.warnings == ()
    text = client.messages.calls[0]["messages"][0]["content"][0]["text"]
    assert "Lun a Sáb 12m – 10pm" in text and "Bianki Shawarma" in text
    assert "Domicilios gratis en el centro" in text  # the meta description
    assert "color: red" not in text and "24 horas" not in text  # styles and scripts out
    assert client.messages.counts == []  # text is bounded by its bytes, no count needed


def test_a_long_page_is_truncated_with_a_warning() -> None:
    body = "<html><body>" + "".join(f"<p>Línea {i} del menú</p>" for i in range(3000))
    doc = read_source(ImportSource(url="https://bianki.com"), fetch=_page_fetch(body))
    assert len(doc.text or "") <= MAX_PAGE_CHARS
    assert doc.warnings == (WARN_TRUNCATED,)


def test_a_page_without_text_or_of_another_type_is_refused() -> None:
    with pytest.raises(SourceUnsupported):
        read_source(ImportSource(url="https://bianki.com"), fetch=_page_fetch("<div id=app></div>"))
    with pytest.raises(SourceUnsupported, match=re.escape(REASON_BAD_LINK)):
        read_source(
            ImportSource(url="https://bianki.com"),
            fetch=_page_fetch("{}", content_type="application/json"),
        )


@pytest.mark.parametrize(
    "url",
    ["ftp://bianki.com", "https://user:pw@bianki.com", "https://bianki.com:8080/", "a b"],
)
def test_bad_links(url: str) -> None:
    with pytest.raises(SourceUnsupported, match=re.escape(REASON_BAD_LINK)):
        read_source(ImportSource(url=url), fetch=_page_fetch())


@pytest.mark.parametrize(
    "url", ["instagram.com/bianki", "https://www.facebook.com/bianki", "https://vm.tiktok.com/x"]
)
def test_social_links_are_out_of_scope(url: str) -> None:
    fetch = _page_fetch()
    with pytest.raises(SourceUnsupported, match="Instagram"):
        read_source(ImportSource(url=url), fetch=fetch)
    assert fetch.seen == []
    assert "Instagram" in REASON_SOCIAL


# --- SSRF ---------------------------------------------------------------------------------


def _resolver(table: dict[str, list[str]]) -> Any:
    def resolve(host: str, port: int) -> list[str]:
        return table[host]

    return resolve


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no request may leave: {request.url}")


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.4.4", "169.254.169.254", "100.64.0.1",
     "0.0.0.0", "::1", "fd00:ec2::254", "::ffff:10.0.0.1", "224.0.0.1"],
)  # fmt: skip
def test_private_addresses_are_refused_before_any_request(address: str) -> None:
    with pytest.raises(SourceUnsupported, match=re.escape(REASON_BAD_LINK)):
        default_fetch(
            "https://evil.example/",
            resolve=_resolver({"evil.example": [address]}),
            transport=httpx.MockTransport(_no_network),
        )


def test_localhost_resolves_to_loopback_and_is_refused() -> None:
    with pytest.raises(SourceUnsupported):
        default_fetch("http://localhost/", transport=httpx.MockTransport(_no_network))


def test_one_private_answer_among_public_ones_is_refused() -> None:
    with pytest.raises(SourceUnsupported):
        default_fetch(
            "https://mixed.example/",
            resolve=_resolver({"mixed.example": ["93.184.216.34", "10.1.1.1"]}),
            transport=httpx.MockTransport(_no_network),
        )


def test_the_request_goes_to_the_checked_address_with_host_and_sni() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=PAGE)

    page = default_fetch(
        "https://bianki.com/menu?x=1",
        resolve=_resolver({"bianki.com": ["93.184.216.34"]}),
        transport=httpx.MockTransport(handler),
    )
    request = seen[0]
    assert request.url.host == "93.184.216.34" and request.url.path == "/menu"
    assert request.headers["host"] == "bianki.com"
    assert request.extensions["sni_hostname"] == "bianki.com"
    assert request.headers["user-agent"] == import_ai.USER_AGENT
    assert "cookie" not in request.headers and "authorization" not in request.headers
    assert page.content_type == "text/html" and page.charset == "utf-8"


def test_a_redirect_to_a_private_host_is_refused() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["host"])
        return httpx.Response(302, headers={"location": "http://internal.example/admin"})

    with pytest.raises(SourceUnsupported):
        default_fetch(
            "https://bianki.com/",
            resolve=_resolver({"bianki.com": ["93.184.216.34"], "internal.example": ["10.0.0.7"]}),
            transport=httpx.MockTransport(handler),
        )
    assert seen == ["bianki.com"]  # the private hop was never requested


def test_more_than_three_redirects_are_refused() -> None:
    hops: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hops.append(request.url.path)
        return httpx.Response(301, headers={"location": f"/r{len(hops)}"})

    with pytest.raises(SourceUnsupported):
        default_fetch(
            "https://bianki.com/",
            resolve=_resolver({"bianki.com": ["93.184.216.34"]}),
            transport=httpx.MockTransport(handler),
        )
    assert len(hops) == 4  # the first request and three redirects


def test_cookies_set_by_a_redirect_are_not_sent_back() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "/menu", "set-cookie": "sid=1; Path=/"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text=PAGE)

    default_fetch(
        "https://bianki.com/",
        resolve=_resolver({"bianki.com": ["93.184.216.34"]}),
        transport=httpx.MockTransport(handler),
    )
    assert "cookie" not in seen[1].headers


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        ({"content-type": "application/pdf"}, b"%PDF"),
        ({"content-type": "text/html"}, b"x" * (2 * 1024 * 1024 + 1)),
        ({"content-type": "text/html", "content-length": str(50 * 1024 * 1024)}, b"x"),
    ],
)
def test_wrong_type_or_too_big_body_is_refused(headers: dict[str, str], body: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=headers, content=body)

    with pytest.raises(SourceUnsupported, match=re.escape(REASON_BAD_LINK)):
        default_fetch(
            "https://bianki.com/",
            resolve=_resolver({"bianki.com": ["93.184.216.34"]}),
            transport=httpx.MockTransport(handler),
        )


def test_a_timeout_or_a_404_is_a_bad_link() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    for handler in (timeout, lambda request: httpx.Response(404)):
        with pytest.raises(SourceUnsupported, match=re.escape(REASON_BAD_LINK)):
            default_fetch(
                "https://bianki.com/",
                resolve=_resolver({"bianki.com": ["93.184.216.34"]}),
                transport=httpx.MockTransport(handler),
            )


def test_the_timeouts_are_the_specified_ones() -> None:
    assert import_ai.FETCH_TIMEOUT.connect == 5.0 and import_ai.FETCH_TIMEOUT.read == 10.0


# --- verification -------------------------------------------------------------------------


def test_a_quote_that_is_not_on_the_page_is_dropped_and_counted() -> None:
    client = FakeClient(
        [
            _answer(
                [
                    _fact(
                        "hours",
                        "de lunes a sábado, de 12:00 m. a 10:00 p. m.",
                        "Lun a Sáb 12m – 10pm",
                    ),
                    _fact(
                        "delivery_cost", "Gratis", "Domicilio gratis a toda la ciudad las 24 horas"
                    ),
                ],
                [
                    _product("Shawarma mixto", "$18.000", "Shawarma mixto $18.000"),
                    _product("Falafel", "$9.000", "Falafel $9.000"),
                ],
            )
        ]
    )
    proposal = propose_menu_facts(
        ImportSource(url="https://bianki.com"), client_factory=client.factory, fetch=_page_fetch()
    )
    assert [f.key for f in proposal.facts] == ["hours"]
    assert [p.name for p in proposal.products] == ["Shawarma mixto"]
    assert proposal.warnings == ("Dejamos fuera 2 datos que no pudimos comprobar en tu página.",)


def test_a_number_the_evidence_does_not_have_is_dropped_even_from_a_photo() -> None:
    client = FakeClient(
        [
            _answer(
                [
                    _fact(
                        "hours",
                        "todos los días, de 7:00 a. m. a 10:00 p. m.",
                        "Lun a Dom 12m - 10pm",
                    ),
                    _fact("delivery_time", "En unos 30 minutos", "Entrega en 30 min"),
                ],
                [
                    _product("Shawarma", "7 $", "Shawarma 6 $"),  # price not in the quote
                    _product("Falafel", "5 $", "Ensalada 5 $"),  # name not in the quote
                ],
            )
        ]
    )
    proposal = propose_menu_facts(
        ImportSource(filename="m.png", data=_png()), client_factory=client.factory
    )
    assert [f.key for f in proposal.facts] == ["delivery_time"]
    assert proposal.products == ()
    assert proposal.warnings[0] == "Dejamos fuera 3 datos que no pudimos comprobar en tu foto."


def test_an_empty_quote_drops_the_item_and_one_fact_per_key() -> None:
    client = FakeClient(
        [
            _answer(
                [
                    _fact("address", "Av. 0 # 12-34", ""),
                    _fact("payment_methods", "Efectivo", "Efectivo y Zelle"),
                    _fact("payment_methods", "Zelle", "Efectivo y Zelle"),
                    _fact("menu_url", "x", "Efectivo y Zelle"),
                ]
            )
        ]
    )
    proposal = propose_menu_facts(
        ImportSource(filename="m.png", data=_png()), client_factory=client.factory
    )
    assert [(f.key, f.value) for f in proposal.facts] == [("payment_methods", "Efectivo")]
    assert proposal.warnings[0] == "Dejamos fuera 1 dato que no pudimos comprobar en tu foto."


def test_a_description_not_in_the_source_is_blanked() -> None:
    client = FakeClient(
        [_answer(products=[_product("Limonada", "", "Limonada", description="Natural y fría")])]
    )
    proposal = propose_menu_facts(
        ImportSource(url="https://bianki.com"), client_factory=client.factory, fetch=_page_fetch()
    )
    assert proposal.products[0].description == ""


def test_products_are_capped_with_a_warning() -> None:
    lines = "".join(f"<p>Plato {i} $1.000</p>" for i in range(60))
    products = [_product(f"Plato {i}", "$1.000", f"Plato {i} $1.000") for i in range(60)]
    client = FakeClient([_answer(products=products)])
    proposal = propose_menu_facts(
        ImportSource(url="https://bianki.com"),
        client_factory=client.factory,
        fetch=_page_fetch(f"<html><body>{lines}</body></html>"),
    )
    assert len(proposal.products) == import_ai.MAX_PRODUCTS
    assert proposal.warnings == ("Tu menú tiene muchos productos: te mostramos los primeros 50.",)


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("$12.000", Decimal("12000")),
        ("6 $", Decimal("6")),
        ("6,50 $", Decimal("6.50")),
        ("US$ 4.5", Decimal("4.5")),
        ("1.234,50", Decimal("1234.50")),
        ("1,234.50", Decimal("1234.50")),
        ("12 mil", Decimal("12000")),
        ("12k", Decimal("12000")),
        ("Bs. 250", Decimal("250")),
        ("5 - 6 $", None),
        ("2x10", None),
        ("gratis", None),
        ("1.2.3", None),
        ("0", None),
    ],
)
def test_prices_are_parsed_conservatively(text: str, amount: Decimal | None) -> None:
    assert parse_amount(text) == amount


@pytest.mark.parametrize(
    ("text", "currency"),
    [
        ("$12.000", ""),
        ("6 $", ""),
        ("COP 15.000", "COP"),
        ("US$ 4", "USD"),
        ("U$S 10", "USD"),
        ("$U 250", "UYU"),
        ("Bs. 250", "VES"),
        ("10 dólares", "USD"),
        ("USD 5 / Bs. 200", ""),
    ],
)
def test_the_currency_is_never_guessed(text: str, currency: str) -> None:
    assert parse_currency(text) == currency


# --- failures -----------------------------------------------------------------------------


def test_nothing_found() -> None:
    client = FakeClient([_answer([], [])])
    with pytest.raises(NothingFound):
        propose_menu_facts(
            ImportSource(filename="m.png", data=_png()), client_factory=client.factory
        )
    assert len(client.messages.calls) == 1  # an honest empty answer is not retried


def test_nothing_left_after_verification_is_nothing_found() -> None:
    client = FakeClient([_answer([_fact("hours", "24 horas", "Abierto siempre")])])
    with pytest.raises(NothingFound):
        propose_menu_facts(
            ImportSource(url="https://bianki.com"),
            client_factory=client.factory,
            fetch=_page_fetch(),
        )


def test_a_refusal_is_retried_once_then_unavailable() -> None:
    client = FakeClient([_answer(stop="refusal"), _answer(stop="refusal")])
    with pytest.raises(ImportUnavailable) as exc:
        propose_menu_facts(
            ImportSource(filename="m.png", data=_png()), client_factory=client.factory
        )
    assert not isinstance(exc.value, NothingFound)
    assert len(client.messages.calls) == 2


def test_a_retry_that_answers_is_used() -> None:
    client = FakeClient(
        [_answer(tool=False, stop="end_turn"), _answer([_fact("hours", "Lun a Sáb", "Lun a Sáb")])]
    )
    proposal = propose_menu_facts(
        ImportSource(filename="m.png", data=_png()), client_factory=client.factory
    )
    assert [f.key for f in proposal.facts] == ["hours"]
    assert len(client.messages.calls) == 2


def test_transport_errors_and_no_key_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import anthropic

    rate_limited = anthropic.RateLimitError(
        "slow down",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com")),
        body=None,
    )
    for error in (ConnectionError("down"), rate_limited):
        client = FakeClient([error])
        with pytest.raises(ImportUnavailable, match="transport error"):
            propose_menu_facts(
                ImportSource(filename="m.png", data=_png()), client_factory=client.factory
            )
        assert len(client.messages.calls) == 1
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY")
    with pytest.raises(ImportUnavailable):
        propose_menu_facts(
            ImportSource(filename="m.png", data=_png()), client_factory=FakeClient([]).factory
        )


def test_an_exhausted_budget_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(import_ai, "IMPORT_BUDGET_USD", Decimal("0.0001"))
    client = FakeClient([_answer()])
    with pytest.raises(ImportUnavailable, match="budget"):
        propose_menu_facts(
            ImportSource(filename="m.png", data=_png()), client_factory=client.factory
        )
    assert client.messages.calls == []


def test_an_unavailable_message_carries_no_model_text() -> None:
    client = FakeClient([_answer(tool=False, stop="end_turn")] * 2)
    with pytest.raises(ImportUnavailable) as exc:
        propose_menu_facts(
            ImportSource(filename="m.png", data=_png()), client_factory=client.factory
        )
    assert "no sé" not in str(exc.value)


# --- cost and boundaries ------------------------------------------------------------------


def test_the_budget_pays_two_worst_turns_of_the_largest_input() -> None:
    # a photo or PDF: the largest measured prompt, with the count's slack and margin
    media = int(MAX_MEDIA_INPUT_TOKENS * import_ai.COUNT_SLACK) + FIRST_TURN_MARGIN_TOKENS
    worst_media = worst_turn_usd("claude-sonnet-5-5", media, MAX_TOKENS)
    assert worst_media is not None and 2 * worst_media <= IMPORT_BUDGET_USD
    # a page: the heaviest text the caps let through (escaped quotes, multi-byte letters)
    body = "<html><body>" + "".join(f'<p>"ñ€" {i} "😀"</p>' for i in range(5000))
    doc = read_source(ImportSource(url="https://" + "a" * 60 + ".com"), fetch=_page_fetch(body))
    messages = import_ai._messages(doc, None)
    ceiling, _ = turn_input_ceiling(SYSTEM_PROMPT, messages, [import_ai._tool()])
    worst_page = worst_turn_usd("claude-sonnet-5-5", ceiling, MAX_TOKENS)
    assert worst_page is not None and 2 * worst_page <= IMPORT_BUDGET_USD
    assert IMPORT_BUDGET_USD == Decimal("0.30")


def test_a_photo_turn_is_reserved_from_its_measured_count_not_its_base64() -> None:
    # 2 MB of base64 would be ~2M "tokens" by bytes and never fit; measured, it does.
    client = FakeClient([_answer([_fact("hours", "Lun a Sáb", "Lun a Sáb")])], counted=1_800)
    noisy = Image.effect_noise((900, 900), 100).convert("RGB")
    out = io.BytesIO()
    noisy.save(out, format="PNG")
    proposal = propose_menu_facts(
        ImportSource(filename="m.png", data=out.getvalue()), client_factory=client.factory
    )
    assert proposal.facts and client.messages.calls[0]["max_tokens"] == MAX_TOKENS


def test_the_module_opens_no_db_door_and_logs_no_content(caplog: pytest.LogCaptureFixture) -> None:
    import inspect

    imports = [
        line
        for line in inspect.getsource(import_ai).splitlines()
        if line.lstrip().startswith(("import ", "from "))
    ]
    assert not [line for line in imports if "qualify_shared.db" in line or "sqlalchemy" in line]
    client = FakeClient([_answer([_fact("hours", "Lun a Sáb 12m – 10pm", "Lun a Sáb 12m – 10pm")])])
    with caplog.at_level("DEBUG", logger="qualify_api.whatsapp.menus.import_ai"):
        propose_menu_facts(
            ImportSource(url="https://bianki.com"),
            client_factory=client.factory,
            fetch=_page_fetch(),
        )
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "facts=1" in logged and "12m" not in logged and "bianki" not in logged.lower()
