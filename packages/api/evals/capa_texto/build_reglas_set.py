"""REGLAS-001 (m-25017292): builds `reglas_set.json`, the labelled set of the text layer's two
free-text rules — price figures (`qualify_creative.layer_spec.free_text_problems`, «currency» /
«price figure») and invented claims (`image_pipeline.layer.unsupported_claims`).

Each row: `text`, `slot`, the `context` the rule sees (the piece's brief — topic, scene,
approved hook and invitation —, the saved data and the catalog's product names), `price`
(the text carries an amount of money), `claim` (the claim type the text makes that the
context does not support, or null), `source`, and `split` (dev/test, stratified, fixed seed).

Sources:
- `capa`: every title, subtitle and call phrase of CAPA-001/002/003 (real `claude-sonnet-5-5`
  output), with the context of its case in `../scene_text_v4/cases.json`; labels as recorded
  in `pruebas.md` (`labels_002.json`) plus the CAPA-003 miss.
- `review`: every case named in the review rounds of #674/#696 and their «Antes de encender».
- `hand`: written and labelled by the creative engineer (2026-11-15) for how small businesses
  in Colombia, Venezuela and Uruguay write prices and promotions — food, real estate, travel
  and fashion — real claims and innocent look-alikes, with and without supporting context.

Labelling rule for `claim`: a promise about days, every day / always, opening hours, a
closure, a discount, something free, delivery, a promotion (2x1, combos at a deal) or a
novelty (inauguración, nuevo local/horario) that the context does not state with the SAME
type — and, for days, the same days. Product names never support a claim (a product named
«Combo Domingo» is not a schedule). An invitation for today/tonight («Te esperamos hoy») is
no claim.

    uv run --no-sync python packages/api/evals/capa_texto/build_reglas_set.py \\
      --capa001 <smoke_out/results.json> --capa002 <results.jsonl> --capa003 <e2e/results.jsonl>
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
CASES = HERE.parent / "scene_text_v4" / "cases.json"
OUT = HERE / "reglas_set.json"
SEED = 20261115
_PRODUCTS = {
    "shawarma_carne": "Shawarma de carne",
    "shawarma_pollo": "Shawarma de pollo",
    "combo_carne": "Combo de shawarma de carne",
    "salchipapa": "Salchipapa",
    "papas": "Papas para compartir",
}


def ctx(
    topic: str = "",
    *,
    scene: str = "",
    hook: str = "",
    cta: str = "",
    hours: str | None = None,
    location: str | None = None,
    contact: str | None = None,
    payment: str | None = None,
    products: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "topic": topic,
        "scene": scene or topic,
        "hook": hook,
        "cta": cta,
        "facts": {
            k: v
            for k, v in (
                ("hours", hours),
                ("location", location),
                ("contact", contact),
                ("payment", payment),
            )
            if v
        },
        "products": list(products),
    }


# -- contexts for the hand-written rows ----------------------------------------------------

PLAIN = ctx("Empanadas recién horneadas en la panadería", products=("Empanada de carne",))
SHAWARMA = ctx("Shawarma de carne recién hecho", products=("Shawarma de carne",))
TUE_SUN = ctx("Salchipapa doradita para picar", hours="Martes a domingo, 5 p. m. a 11 p. m.")
EVERY_DAY = ctx("Arepas rellenas para el desayuno", hours="Lunes a domingo de 6 a. m. a 2 p. m.")
H24 = ctx("Perros calientes en la esquina", hours="Abierto 24 horas")
PROMO_TUE = ctx("Martes de 2x1 en shawarma de pollo", products=("Shawarma de pollo",))
DELIVERY = ctx("Llevamos tu pedido a domicilio en todo el barrio")
DISCOUNT = ctx("20 % de descuento en todo el menú este fin de semana")
FREE = ctx("Gaseosa gratis con tu combo", products=("Combo de shawarma de carne",))
NEW = ctx("Inauguramos nuestro nuevo local en el centro")
CLOSED = ctx("Cerrado por vacaciones del 20 al 27 de diciembre")
COMBO_SUNDAY = ctx("Combos para compartir", products=("Combo Domingo",))
REALTY = ctx("Apartamento en venta en Cúcuta, 3 habitaciones y 2 baños")
TRAVEL = ctx("Plan a Cartagena, 4 días y 3 noches con hotel")
FASHION = ctx("Nueva colección de vestidos de temporada")
FASHION_SALE = ctx("Rebajas de fin de temporada: 30 % en vestidos")
CTA_DELIVERY = ctx("Shawarma de pollo", cta="Pide a domicilio por WhatsApp")
HOOK_FRIDAY = ctx("Pizza artesanal", hook="Este viernes, 2x1 en pizzas medianas")


def row(
    text: str,
    context: dict[str, Any],
    *,
    price: bool = False,
    claim: str | None = None,
    source: str = "hand",
    slot: str = "title",
    note: str = "",
) -> dict[str, Any]:
    return {
        "text": text,
        "slot": slot,
        "context": context,
        "price": price,
        "claim": claim,
        "source": source,
        "note": note,
    }


# -- price: amounts in every way the three markets write them --------------------------------

PRICE_POS = [
    # Colombia: pesos with separators, «mil», «lucas», «k», «$»
    "Combo a $25.000",
    "Solo $18.000 el shawarma",
    "Empanadas a 2.500",
    "Por 15 mil, tu combo",
    "15mil el combo",
    "Dos por 20 mil",
    "A solo 12 lucas",
    "Combo de 10 lucas",
    "Por 15k",
    "Solo 25k hoy",
    "Almuerzo a 14.900",
    "Desde $9.900",
    "Desde 2500",
    "Precio: 18",
    "Precio 18.000",
    "Empanadas a 2000",
    "Llévate 3 por 2000",
    "Combo por 25",
    "Solo 99",
    "Desde 15",
    "Shawarma en 25",
    "Empanadas 2000",
    "Tu combo 2026",
    "Por veinte mil",
    "A quince mil el combo",
    "Solo 25.000",
    "Ahora 10,50",
    "Cuesta 18 mil",
    "Vale 30 mil",
    "Te sale en 12 mil",
    "Combo familiar 45.000",
    "$ 35.000 el combo",
    "El kilo a 22 mil",
    "Llévate 3 x 2000",
    "Empanadas de 2000",
    "Desde 2000 el café",
    "COP 25.000",
    "25.000 pesos",
    "Solo 20 mil pesitos",
    "Bandeja paisa a 28 mil",
    # Venezuela: bolívares, dólares, REF, «Bs»
    "A 20bs",
    "Por 5usd",
    "USD 5",
    "Solo 5 $",
    "Combo en 8$",
    "Desde 3 dólares",
    "Hamburguesa a 6 REF",
    "Solo 4 ref",
    "Pepito en 7 dólares",
    "Bs 250 el tequeño",
    "Tequeños a 300 Bs",
    "Pago en divisas: 10 $",
    "A 2,50 $ la empanada",
    "Combo 9,99 USD",
    "Cachapa a 4 verdes",
    "Por 3 dólares más, la bebida",
    "Arepa a 2$",
    "Desde 1,5 $",
    "Solo 15 bolívares",
    "VES 180",
    # Uruguay: pesos uruguayos, UYU, $U
    "Chivito a $U 450",
    "UYU 390 la milanesa",
    "Por 350 pesos",
    "Torta frita a 40 pesos",
    "Menú del día $ 320",
    "Pancho a 120",
    "Solo 590 la pizza",
    "A 1.200 la docena",
    "Desde $ 890",
    "Pizza a 499",
    # other currencies and travel / realty / fashion
    "20 soles el menú",
    "Desde 180 USD por noche",
    "Plan a Cartagena desde $ 1.290.000",
    "Paquete por 990 dólares",
    "Tiquetes desde 199 mil",
    "Hotel a 250 mil la noche",
    "Apartamento en 250 millones",
    "Casa por 380 millones",
    "Arriendo a 1.800.000",
    "Apartaestudio por 1,2 millones",
    "Lote desde 45 millones",
    "Cuota inicial de 30 millones",
    "Vestidos a 89.900",
    "Blusas desde 39 mil",
    "Jeans a 120 mil",
    "Todo a 50 mil",
    "Zapatos por 99.900",
    "Camisas a 2x 60 mil",
    "Bolsos desde $ 75.000",
    "Gorras a 25k",
    "Solo por 19.900",
    "Llévalo por 59 mil",
    "Por solo 9.990",
    "Te cuesta 15 lucas",
    "15 luquitas el combo",
    "Un palo el arriendo",
    "A 2 palos",
    "Combo personal 12.500",
    "Inversión desde 120 millones",
    "Excursión a 350.000",
    "Noche a 220.000",
    "A tan solo 8.000",
    "Por apenas 5 mil",
    "Te lo dejamos en 40",
    "Valor: 45.000",
    "Desde US$ 49",
    "Entrada general 20 mil",
    "Clase a 35 mil",
    "Corte a 20 mil",
    "Kilo de carne a 32.000",
    "Libra a 11.000",
    "Docena a 18 mil",
    "Media docena a 9 mil",
    "Botella a 15 mil",
    "Café a 3 mil",
    "Tinto a 2 mil",
    "Jugo a 5.000",
    "Combo pareja: 38.000",
    "Ahora en 19.990",
    "Por menos de 20 mil",
    "Menos de 10 dólares",
    "Con 5 mil te alcanza",
    "Lleva 2 por 15.000",
    "3 por 10 mil",
    "2 por 25",
    "4 x 10.000",
    "Pide ya: 14.500",
]

PRICE_NEG = [
    "Novedades 2026",
    "Desde 1998 contigo",
    "100% natural",
    "500 g de pollo",
    "Mil sabores en tu mesa",
    "Pesos pesados del sabor",
    "1 litro de limonada",
    "En 2026, más sabores",
    "Edición 2026",
    "Temporada 2026",
    "Navidad 2026 en tu mesa",
    "Desde 2000 contigo",
    "Listo en 5 minutos",
    "A 2 cuadras de ti",
    "Por 2 personas, un combo",
    "Solo 3 ingredientes",
    "Tu combo de 2",
    "Listo en 1 hora",
    "Combo para 4",
    "Pizza de 8 porciones",
    "Hamburguesa de 200 g",
    "Media libra de carne",
    "Café de 12 onzas",
    "Botella de 1,5 litros",
    "Torta para 20 personas",
    "Caja de 6 donas",
    "Docena de empanadas",
    "3 habitaciones y 2 baños",
    "Apartamento de 72 m²",
    "Piso 5 con vista",
    "Lote de 300 m2",
    "A 10 minutos del centro",
    "4 días y 3 noches",
    "Vuelo de 2 horas",
    "Tour de 6 horas",
    "Plan para 2 personas",
    "Talla 38 a 42",
    "Tallas S, M y L",
    "Colección 2026",
    "Verano 2026",
    "Desde 2010 vistiéndote",
    "Más de 20 años contigo",
    "Top 10 de la ciudad",
    "Tu combo número 1",
    "La número 1 del barrio",
    "Los 3 favoritos",
    "Las 5 más pedidas",
    "Calle 10 # 4-25, local 3",
    "Carrera 7 con 45",
    "Local 12 del centro comercial",
    "Avenida 5 de Julio",
    "Km 3 vía al mar",
    "Sector 4, manzana 2",
    "Edificio Torre 2, piso 9",
    "Llámanos al 300 123 4567",
    "WhatsApp 0412 555 1234",
    "Escríbenos al 099 123 456",
    "Cumplimos 15 años",
    "Celebra tus 15",
    "Hecho con 3 quesos",
    "Arepa con 2 rellenos",
    "Pizza de 4 sabores",
    "1 de cada 3 pide doble",
    "Ref. 2045, vestido largo",
    "Modelo 300 en negro",
    "Mil gracias por venir",
    "Ciento por ciento casero",
    "Mitad y mitad",
    "Doble carne",
    "Triple queso",
    "Para compartir entre 4",
    "Sirve 2 porciones",
    "Tus 2 favoritos juntos",
    "Un combo para 2",
    "Dos tazas de café",
    "La 10 de la carta",
    "Pide el 7",
    "Mesa para 6",
    "Vista al mar desde el piso 12",
    "Estrato 4",
    "A 300 metros de la playa",
    "Habitación para 3",
    "5 estrellas",
    "Pasaporte al día",
]


# -- claims: one list per type, written unsupported, then the same with supporting context --

CLAIMS: dict[str, list[tuple[str, dict[str, Any], dict[str, Any] | None]]] = {
    # (text, context where it is NOT supported, context where it IS supported or None)
    "day": [
        ("Te esperamos el sábado", PLAIN, TUE_SUN),
        ("Este domingo te esperamos", COMBO_SUNDAY, TUE_SUN),
        ("Los viernes, pizza para todos", PLAIN, HOOK_FRIDAY),
        ("Martes de shawarma 2x1", SHAWARMA, PROMO_TUE),
        ("Ven este jueves", PLAIN, TUE_SUN),
        ("Los lunes abrimos temprano", TUE_SUN, None),
        ("Te esperamos el lunes", TUE_SUN, EVERY_DAY),
        ("Fin de semana de empanadas", PLAIN, DISCOUNT),
        ("Este fin de semana, 2x1", PLAIN, None),
        ("Miércoles de arepas", PLAIN, None),
        ("Sábados de parrilla", SHAWARMA, None),
        ("El domingo, almuerzo en familia", PLAIN, TUE_SUN),
        ("Hasta el viernes", FASHION, HOOK_FRIDAY),
        ("Solo este martes", PLAIN, PROMO_TUE),
        ("De lunes a viernes, almuerzo ejecutivo", PLAIN, EVERY_DAY),
        ("Los domingos abrimos", COMBO_SUNDAY, TUE_SUN),
        ("Feria de los jueves", FASHION, None),
        ("Este festivo abrimos", PLAIN, None),
        ("Los martes, empanada doble", PLAIN, PROMO_TUE),
        ("Sábado de feria", FASHION, None),
    ],
    "every_day": [
        ("Tu salchipapa, cada noche", TUE_SUN, EVERY_DAY),
        ("Todos los días contigo", TUE_SUN, EVERY_DAY),
        ("Abierto 24 horas", TUE_SUN, H24),
        ("Siempre abiertos para ti", PLAIN, H24),
        ("Cada día, pan recién hecho", TUE_SUN, EVERY_DAY),
        ("Todos los días, desayuno", PLAIN, EVERY_DAY),
        ("24/7 para tus antojos", PLAIN, H24),
        ("Te esperamos cada noche", TUE_SUN, H24),
        ("Abiertos toda la semana", TUE_SUN, EVERY_DAY),
        ("De lunes a domingo", TUE_SUN, EVERY_DAY),
        ("Sin días de descanso", PLAIN, EVERY_DAY),
        ("Los 7 días de la semana", TUE_SUN, EVERY_DAY),
        ("Abierto toda la noche", TUE_SUN, H24),
        ("Siempre listos para atenderte", PLAIN, H24),
        ("Abiertos siempre", PLAIN, H24),
        ("Todos los días de 7 a 7", TUE_SUN, None),
    ],
    "hours": [
        ("Abierto hoy hasta tarde", PLAIN, TUE_SUN),
        ("Estamos abiertos", PLAIN, TUE_SUN),
        ("Abrimos de martes a domingo", PLAIN, TUE_SUN),
        ("Ya abrimos", PLAIN, TUE_SUN),
        ("Abrimos temprano", PLAIN, EVERY_DAY),
        ("Abrimos hasta la medianoche", PLAIN, None),
        ("Seguimos abiertos", PLAIN, H24),
        ("Atendemos hasta tarde", PLAIN, TUE_SUN),
        ("Abierto desde temprano", PLAIN, EVERY_DAY),
        ("Nuevo horario extendido", PLAIN, None),
        ("Horario extendido esta semana", PLAIN, None),
        ("Abrimos hoy", PLAIN, TUE_SUN),
    ],
    "closure": [
        ("Cerrado por vacaciones", PLAIN, CLOSED),
        ("Cerrado los lunes", PLAIN, None),
        ("Hoy cerramos temprano", PLAIN, None),
        ("Cerramos este festivo", PLAIN, None),
        ("Estamos cerrados por inventario", FASHION, None),
        ("Cerramos el 24 de diciembre", PLAIN, CLOSED),
        ("Cerrado por remodelación", PLAIN, None),
        ("No abrimos el domingo", PLAIN, None),
    ],
    "discount": [
        ("Ahora con 20% de descuento", PLAIN, DISCOUNT),
        ("50 % off en postres", PLAIN, DISCOUNT),
        ("Hasta 30 % menos", FASHION, FASHION_SALE),
        ("Descuento en todo el menú", PLAIN, DISCOUNT),
        ("Rebajas en vestidos", FASHION, FASHION_SALE),
        ("Mitad de precio", PLAIN, None),
        ("Precios de locura", PLAIN, None),
        ("-20 % en tu primer pedido", PLAIN, None),
        ("Liquidación total", FASHION, None),
        ("Oferta especial de lanzamiento", NEW, None),
        ("Descuentos en planes a Cartagena", TRAVEL, None),
        ("Precio rebajado", REALTY, None),
        ("Black Friday en ropa", FASHION, None),
        ("30 % menos en accesorios", FASHION, FASHION_SALE),
        ("Ahorra 15 %", PLAIN, DISCOUNT),
    ],
    "free": [
        ("Bebida gratis con tu combo", PLAIN, FREE),
        ("Gaseosa gratis", SHAWARMA, FREE),
        ("Domicilio gratis", PLAIN, None),
        ("Envío gratis", FASHION, None),
        ("Postre de regalo", PLAIN, None),
        ("Papas gratis los martes", SHAWARMA, None),
        ("Te regalamos el café", PLAIN, None),
        ("Sin costo de envío", FASHION, None),
        ("Asesoría sin costo", REALTY, None),
        ("Cortesía de la casa", PLAIN, None),
        ("Gratis para niños", TRAVEL, None),
        ("Llévate un obsequio", FASHION, None),
        ("2 tintos gratis", PLAIN, None),
    ],
    "delivery": [
        ("Domicilio a toda la ciudad", PLAIN, DELIVERY),
        ("Envío sin costo", FASHION, None),
        ("Te lo llevamos a casa", PLAIN, DELIVERY),
        ("Pide a domicilio", SHAWARMA, CTA_DELIVERY),
        ("Delivery en tu zona", PLAIN, DELIVERY),
        ("Envíos a todo el país", FASHION, None),
        ("Llevamos tu pedido", PLAIN, DELIVERY),
        ("A domicilio en minutos", PLAIN, DELIVERY),
        ("Domicilios hasta las 10", PLAIN, None),
        ("Hacemos envíos nacionales", FASHION, None),
        ("Tu pedido llega a casa", PLAIN, DELIVERY),
        ("Despachos a domicilio", PLAIN, DELIVERY),
        ("Entregas a domicilio todo el día", PLAIN, DELIVERY),
    ],
    "promotion": [
        ("Shawarma 2x1", SHAWARMA, PROMO_TUE),
        ("2x1 en pizzas", PLAIN, HOOK_FRIDAY),
        ("3x2 en empanadas", PLAIN, None),
        ("Dos por uno en pollo", SHAWARMA, PROMO_TUE),
        ("Lleva 2 y paga 1", PLAIN, None),
        ("Papas que no se acaban", PLAIN, None),
        ("Combo al doble", PLAIN, None),
        ("Segunda unidad a mitad de precio", FASHION, None),
        ("Promo del mes", PLAIN, None),
        ("Paga 1, lleva 2", PLAIN, None),
        ("Hamburguesa doble por la sencilla", PLAIN, None),
        ("Refill ilimitado", PLAIN, None),
        ("Promoción solo hoy", PLAIN, None),
        ("Noche extra de regalo", TRAVEL, None),
        ("Combo 2x1 para compartir", PLAIN, None),
    ],
    "novelty": [
        ("Inauguramos local", PLAIN, NEW),
        ("Gran inauguración", PLAIN, NEW),
        ("Nuevo local en el centro", PLAIN, NEW),
        ("Nuevo horario para ti", PLAIN, None),
        ("Estrenamos sede", PLAIN, NEW),
        ("Reapertura este sábado", PLAIN, None),
        ("Ahora en un nuevo local", PLAIN, NEW),
        ("Abrimos nueva sede", FASHION, None),
        ("Volvemos a abrir", PLAIN, None),
        ("Nuevo menú", PLAIN, None),
        ("Nueva sede en Chapinero", FASHION, None),
        ("Recién inaugurados", PLAIN, NEW),
    ],
}

#: innocent look-alikes: no claim whatever the context
CLAIM_NEG = [
    ("Cielo abierto", PLAIN),
    ("Recién abierto el horno", PLAIN),
    ("Tu sábado sabe mejor", PLAIN),
    ("Para tus domingos en familia", PLAIN),
    ("Tu Combo Domingo", COMBO_SUNDAY),
    ("Abrimos el horno a las brasas", PLAIN),
    ("Te esperamos hoy", PLAIN),
    ("Ven esta noche", PLAIN),
    ("Pídelo por WhatsApp", PLAIN),
    ("Tu shawarma, al momento", SHAWARMA),
    ("100% natural", PLAIN),
    ("500 g de pollo", PLAIN),
    ("Fresca como la mañana", PLAIN),
    ("Tu nuevo antojo", PLAIN),
    ("Un sabor nuevo cada vez", PLAIN),
    ("Siempre con amor", PLAIN),
    ("Hecho como siempre", PLAIN),
    ("El sabor de siempre", PLAIN),
    ("Mañana de café", PLAIN),
    ("Noche de pizza", PLAIN),
    ("Tu cena perfecta", PLAIN),
    ("Gratitud en cada bocado", PLAIN),
    ("Libre de gluten", PLAIN),
    ("Sin conservantes", PLAIN),
    ("Envuelto con cariño", PLAIN),
    ("Abierto a nuevas ideas", FASHION),
    ("Puertas abiertas", REALTY),
    ("Tu nuevo hogar", REALTY),
    ("Nueva colección", FASHION),
    ("Lo nuevo de la temporada", FASHION),
    ("Siempre a la moda", FASHION),
    ("Viaja cada vez más", TRAVEL),
    ("Tu próximo viaje", TRAVEL),
    ("Días de playa", TRAVEL),
    ("Noches de luna", TRAVEL),
    ("Pide hoy mismo", PLAIN),
    ("Recién hecho", PLAIN),
    ("Listo para llevar", PLAIN),
    ("Para llevar o comer aquí", PLAIN),
    ("Te esperamos esta noche", PLAIN),
    ("Doradita y crocante", PLAIN),
    ("Precio justo, sabor grande", PLAIN),
    ("Tu regalo ideal", FASHION),
    ("Regálale un detalle", FASHION),
    ("Gana tiempo", PLAIN),
    ("Cerca de ti", PLAIN),
    ("Siempre fresco", PLAIN),
    ("Cada bocado cuenta", PLAIN),
    ("Todo el sabor", PLAIN),
    ("Todo listo para ti", PLAIN),
    ("Abre tu apetito", PLAIN),
    ("Abre la puerta al sabor", PLAIN),
    ("Cierra el día con postre", PLAIN),
    ("Un domingo cualquiera", PLAIN),
]


def capa_rows(path001: Path, path002: Path, path003: Path) -> list[dict[str, Any]]:
    cases = {c["id"]: c for c in json.loads(CASES.read_text("utf-8"))["cases"]}

    def case_ctx(case_id: str, data: bool) -> dict[str, Any]:
        case = cases[case_id]
        by = {n.lower(): v for n, v in case.get("highlights") or []}
        return ctx(
            case["topic"],
            cta=case["cta_or_place"] if isinstance(case.get("cta_or_place"), str) else "",
            hours=by.get("horario"),
            location=by.get("dirección"),
            contact=by.get("pedido") or by.get("domicilio"),
            payment="Efectivo · Nequi" if data else None,
            products=tuple(_PRODUCTS[p] for p in case.get("products") or [] if p in _PRODUCTS),
        )

    labels = {
        # pruebas.md CAPA-002 (labels_002.json) and CAPA-003
        ("CAPA-002", "F3-horario-r1-v4#0.title"): "every_day",
        ("CAPA-002", "G2-salchipapa-galeria-carrusel-5#3.subtitle"): "promotion",
        ("CAPA-003", "F3-horario-r1-v5#0.subtitle"): "every_day",
    }
    rows = []
    for item in json.loads(path001.read_text("utf-8")):
        case_id = item["case"]
        for slot in ("title", "subtitle", "call_phrase"):
            if item.get(slot):
                rows.append(
                    row(
                        item[slot],
                        case_ctx(case_id, False),
                        source="capa:CAPA-001",
                        slot=slot,
                        note=item["photo"],
                    )
                )
    for name, path in (("CAPA-002", path002), ("CAPA-003", path003)):
        for line in path.read_text("utf-8").splitlines():
            item = json.loads(line)
            for pos, layer in (item.get("layers") or {}).items():
                for slot in ("title", "subtitle", "call_phrase"):
                    text = layer.get(slot)
                    if not text:
                        continue
                    key = f"{item['id']}#{pos}.{slot}"
                    rows.append(
                        row(
                            text,
                            case_ctx(item["case"], bool(item.get("data"))),
                            claim=labels.get((name, key)),
                            source=f"capa:{name}",
                            slot=slot,
                            note=key,
                        )
                    )
    return rows


REVIEW = [
    # (#674/#696 reviews and «Antes de encender»: leaks and false rejections)
    row("Listo en 1 hora", PLAIN, source="review"),
    row("Empanadas de 2000", PLAIN, price=True, source="review"),
    row("Desde 2000", PLAIN, price=True, source="review", note="ambiguous; read as a price"),
    row("Precio: 18", PLAIN, price=True, source="review"),
    row("Llévate 3 x 2000", PLAIN, price=True, source="review"),
    row("Abierto toda la noche", PLAIN, claim="every_day", source="review"),
    row("Cerrado por vacaciones", PLAIN, claim="closure", source="review"),
    row("Este domingo te esperamos", COMBO_SUNDAY, claim="day", source="review"),
    row("Martes de sabor", PLAIN, source="review", note="slogan; known hard case"),
    row("Abrimos el horno a las brasas", PLAIN, source="review"),
    row("Tu sábado sabe mejor", PLAIN, source="review"),
    row("Cielo abierto", PLAIN, source="review"),
    row("Recién abierto el horno", PLAIN, source="review"),
    row("Tu salchipapa, cada noche", TUE_SUN, claim="every_day", source="review"),
    row("Papas que no se acaban", PLAIN, claim="promotion", source="review"),
    row("Por veinte mil", PLAIN, price=True, source="review"),
    row("Pide a domicilio", CTA_DELIVERY, source="review"),
    row("Martes de 2x1", ctx("Shawarma", hook="Este martes, 2x1 en shawarmas"), source="review"),
    row("Tu Combo Domingo", COMBO_SUNDAY, source="review"),
    row("Te esperamos, abrimos hoy", TUE_SUN, source="review"),
    row("Envíos a toda la ciudad", ctx("Hacemos envíos a toda la ciudad"), source="review"),
    row(
        "Domicilio en tu barrio",
        ctx("Shawarma", scene="Pedido a domicilio en moto"),
        source="review",
    ),
]


def build(capa: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(capa) + REVIEW
    rows += [row(t, PLAIN, price=True) for t in PRICE_POS]
    rows += [row(t, PLAIN) for t in PRICE_NEG]
    for kind, items in CLAIMS.items():
        for text, unsupported, supported in items:
            rows.append(row(text, unsupported, claim=kind))
            if supported is not None:
                rows.append(row(text, supported, note=f"{kind} supported by context"))
    rows += [row(t, c) for t, c in CLAIM_NEG]
    # a row is unique by (text, context): the first wins (review rows over hand-written)
    seen, unique = set(), []
    for r in rows:
        key = (r["text"], json.dumps(r["context"], sort_keys=True))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    # stratified split, fixed seed: by (price, has claim, source family)
    rng = random.Random(SEED)
    strata: dict[tuple, list[dict[str, Any]]] = {}
    for r in unique:
        strata.setdefault(
            (r["price"], r["claim"] is not None, r["source"].split(":")[0]), []
        ).append(r)
    for members in strata.values():
        rng.shuffle(members)
        cut = max(1, round(len(members) * 0.35)) if len(members) > 1 else 0
        for i, r in enumerate(members):
            r["split"] = "test" if i < cut else "dev"
    # written AFTER the rules were frozen, never used to change them: an honest look at new
    # phrasings (the dev/test rows were written by the same person who wrote the tables)
    for r in FRESH:
        r["split"] = "fresh"
        unique.append(r)
    # the reviewer's misses and the bugs of the 2026-11-15 review: tuned on from then on,
    # so a dev-like split, reported apart
    for r in REVISION:
        r["split"] = "revision"
        unique.append(r)
    for i, r in enumerate(unique):
        r["id"] = i
    return unique


UY = ctx("Chivitos al pan en Montevideo")
REVISION = [
    # the independent reviewer's misses (2026-11-15)
    row("Receta de la abuela desde 1985", PLAIN, source="revision"),
    row("Colección otoño 2026", FASHION, source="revision"),
    row("Vista abierta a los cerros", REALTY, source="revision"),
    row(
        "Cada noche, un atardecer distinto",
        TRAVEL,
        source="revision",
        note="description, not an availability promise: known hard case",
    ),
    row("Tu look de viernes, listo", FASHION, source="revision"),
    row("Ya abrimos en Pocitos", UY, claim="hours", source="revision"),
    row("Happy hour de 6 a 8", PLAIN, claim="promotion", source="revision"),
    row("Tours diarios a Isla Margarita", TRAVEL, claim="every_day", source="revision"),
    row(
        "Separa tu apartamento sin cuota inicial",
        REALTY,
        claim="financing",
        source="revision",
        note="financing promise: outside the nine types, left out by design",
    ),
    # the review's bugs, as rows
    row("Por 20 años contigo", PLAIN, source="revision"),
    row("Celebra el año 2026 con nosotros", PLAIN, source="revision"),
    row("Abierto mañana", PLAIN, claim="hours", source="revision"),
    row("Te esperamos el sábado", ctx("Abrimos de viernes a lunes"), source="revision"),
    row(
        "Te esperamos el miércoles",
        ctx("Abrimos de viernes a lunes"),
        claim="day",
        source="revision",
    ),
    row(
        "Domicilio gratis",
        ctx(
            "Pizzas al horno",
            hours="Martes a domingo",
            contact="No hacemos domicilios ni nada gratis",
        ),
        claim="delivery",
        source="revision",
    ),
    row(
        "Envío Gratis en toda la ciudad",
        ctx("Ropa de temporada", products=("Envío Gratis",)),
        claim="delivery",
        source="revision",
    ),
    row("Te esperamos el domingo", ctx("Pan de bono", hours="Lun-Dom 7 a 20"), source="revision"),
    row("Ven el sábado", ctx("Pan de bono", hours="L a V 7 a 20"), claim="day", source="revision"),
    row(
        "Este finde, música en vivo",
        ctx("Bar", hours="Findes de 6 p. m. a 2 a. m."),
        source="revision",
    ),
]
FRESH = [
    row("Abrimos todos los festivos", PLAIN, claim="day", source="fresh"),
    row("Atención de corrido toda la semana", PLAIN, claim="every_day", source="fresh"),
    row("Pedidos a cualquier hora", PLAIN, claim="every_day", source="fresh"),
    row("Te lo mandamos a tu casa", PLAIN, claim="delivery", source="fresh"),
    row("Llega en moto a tu casa", PLAIN, claim="delivery", source="fresh"),
    row("Dos hamburguesas por el precio de una", PLAIN, claim="promotion", source="fresh"),
    row("Combo dúo con 15 % menos", PLAIN, claim="discount", source="fresh"),
    row("Envío express", FASHION, claim="delivery", source="fresh"),
    row("Primera visita sin cargo", REALTY, claim="free", source="fresh"),
    row("Hasta agotar existencias", FASHION, claim="promotion", source="fresh"),
    row("Reabrimos el lunes", PLAIN, claim="novelty", source="fresh"),
    row("Estrenamos carta", PLAIN, claim="novelty", source="fresh"),
    row("Nuevos horarios desde este mes", PLAIN, claim="hours", source="fresh"),
    row("Abierto de 8 a 8 de lunes a sábado", PLAIN, claim="hours", source="fresh"),
    row("Cada fin de semana, música en vivo", PLAIN, claim="day", source="fresh"),
    row("Feriados también abrimos", UY, claim="day", source="fresh"),
    row("Domingos y feriados", UY, claim="day", source="fresh"),
    row("Hoy y mañana, 2x1", PLAIN, claim="promotion", source="fresh"),
    row("Happy hour de 5 a 7", PLAIN, claim="promotion", source="fresh"),
    row("Descuentazo en botas", FASHION, claim="discount", source="fresh"),
    row("Ofertón del día", PLAIN, claim="discount", source="fresh"),
    row("Te lo llevamos sin costo", PLAIN, claim="delivery", source="fresh"),
    row("Envíos gratis a todo Montevideo", UY, claim="delivery", source="fresh"),
    row("Promo 2 x 15.000", PLAIN, price=True, claim="promotion", source="fresh"),
    row("Recogé tu pedido en el local", UY, source="fresh"),
    row("Tu viernes empieza aquí", PLAIN, source="fresh"),
    row("Sabor de domingo en casa", PLAIN, source="fresh"),
    row("Abierto al público", PLAIN, source="fresh"),
    row("Cerrado al vacío para que dure", PLAIN, source="fresh"),
    row("Hecho en casa", PLAIN, source="fresh"),
    row("Siempre fresco y crujiente", PLAIN, source="fresh"),
    row("Gratinado al horno", PLAIN, source="fresh"),
    row("Envío de amor en cada caja", PLAIN, source="fresh"),
    row("Nuestra nueva receta", PLAIN, source="fresh"),
    row("Promesa de sabor", PLAIN, source="fresh"),
    row("Abrimos los domingos", TUE_SUN, source="fresh"),
    row("Solo 9.990 COP", PLAIN, price=True, source="fresh"),
    row("Por 7 lucas", PLAIN, price=True, source="fresh"),
    row("A 3 dolaritos", PLAIN, price=True, source="fresh"),
    row("Combo a 12 mil quinientos", PLAIN, price=True, source="fresh"),
    row("Apto de 3 alcobas por 280 millones", REALTY, price=True, source="fresh"),
    row("A $ 2.000 la unidad", PLAIN, price=True, source="fresh"),
    row("Desde 99 mil por persona", TRAVEL, price=True, source="fresh"),
    row("Sale en 18", PLAIN, price=True, source="fresh"),
    row("Precio por kilo: 22.000", PLAIN, price=True, source="fresh"),
    row("12.000 cada uno", PLAIN, price=True, source="fresh"),
    row("Cuesta lo mismo que un tinto", PLAIN, source="fresh"),
    row("Vale la pena", PLAIN, source="fresh"),
    row("Paquete de 5 noches", TRAVEL, source="fresh"),
    row("Llévalo en 3 cuotas", FASHION, source="fresh"),
    row("En 2 sabores", PLAIN, source="fresh"),
    row("Calle 72 # 10-34", PLAIN, source="fresh"),
    row("Edición 15 del festival", PLAIN, source="fresh"),
    row("Desde el 2015 en el barrio", PLAIN, source="fresh"),
    row("Pizza familiar de 12 porciones", PLAIN, source="fresh"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--capa001", required=True)
    parser.add_argument("--capa002", required=True)
    parser.add_argument("--capa003", required=True)
    args = parser.parse_args()
    rows = build(capa_rows(Path(args.capa001), Path(args.capa002), Path(args.capa003)))
    OUT.write_text(
        json.dumps({"seed": SEED, "rows": rows}, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )
    by = lambda f: sum(1 for r in rows if f(r))  # noqa: E731
    print(
        f"{len(rows)} rows; price+ {by(lambda r: r['price'])}; claim+ "
        f"{by(lambda r: r['claim'])}; test {by(lambda r: r['split'] == 'test')}; "
        f"capa {by(lambda r: r['source'].startswith('capa'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
