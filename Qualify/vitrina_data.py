"""Static demo dataset for the "Vitrina de locales" module.

Deliberately hardcoded. This module is a **UI demo** meant to be shown to the
owner of a microcentro comercial so they can see what the product would look
like — it has no backend, no DB and no API call. Every number here is
illustrative and the page says so on screen (see `DISCLAIMER`); do not let a
"real" number leak in here without a source, because a demo that mixes measured
and invented figures is worse than one that is openly invented.

The venue modelled is Korner Club (Av. Los Agustinos, San Cristóbal, Táchira):
padel and beach-tennis courts, a bar, and a gastronomic fair whose food stalls
are what actually gets rented to emprendedores.

Shape of the data, and why it is shaped this way: the flow curve belongs to the
**venue**, but each local captures a different share of it depending on where
its door is (`flujo_pct`). That is the whole point of the module — two stalls in
the same building are not the same business, and a zone-level score cannot tell
them apart.
"""

from dataclasses import dataclass

DISCLAIMER = (
    "Demostración. Los números son ilustrativos, no medidos: sirven para mostrar "
    "qué se vería con los datos del microcentro, no para decidir nada todavía."
)

# Venue identity -----------------------------------------------------------

MICROCENTRO = "Korner Club"
LEMA = "Comida · Bar · Canchas de padel y arena"
DIRECCION = "Av. Los Agustinos, San Cristóbal"

# Headline figures shown in the stats row. Values are strings because they are
# display-only: nothing downstream computes with them.
RESUMEN = [
    ("Visitantes por semana", "4.200", "estimado sobre ventas de 6 locales"),
    ("Locales", "6 de 9 ocupados", "3 disponibles hoy"),
    ("Ticket promedio", "$6,80", "feria gastronómica, últimas 8 semanas"),
    ("Hora pico", "20:00", "de lunes a viernes"),
]


# Flow curve ---------------------------------------------------------------
# Index, not people: 100 = the venue's busiest hour. Derived from aggregated
# sales of the already-rented stalls, which is spend, not headcount — the two
# differ by ticket size, and the UI has to say so rather than dress an index up
# as a visitor count.

HORAS = [
    "10",
    "11",
    "12",
    "13",
    "14",
    "15",
    "16",
    "17",
    "18",
    "19",
    "20",
    "21",
    "22",
    "23",
]

FLUJO_SEMANA = [8, 12, 34, 42, 30, 18, 22, 38, 62, 88, 100, 92, 61, 28]
FLUJO_FINDE = [22, 41, 68, 79, 66, 48, 52, 63, 80, 95, 100, 97, 84, 52]


@dataclass(frozen=True)
class Publico:
    """One audience segment the venue already attracts."""

    nombre: str
    share: int  # percentage of visitors
    pico: str
    nota: str


PUBLICOS = [
    Publico(
        "Jugadores de padel y arena",
        38,
        "19:00 – 21:00",
        "Reservan cancha entre semana; salen con hambre y con prisa.",
    ),
    Publico(
        "Acompañantes y familias",
        27,
        "11:00 – 14:00",
        "Fin de semana. Se quedan mucho más rato que quien juega.",
    ),
    Publico(
        "After-office sin cancha",
        24,
        "18:00 – 20:00",
        "Vienen al bar. Consumo de bebida alto, comida baja.",
    ),
    Publico(
        "Torneos y eventos",
        11,
        "irregular",
        "Picos de 3 a 4 veces el flujo normal, con fecha conocida.",
    ),
]


# Hot-kitchen requirements -------------------------------------------------
# Three states on purpose: "desconocido" is the common case and must never be
# rendered as "no" — that would silently delete viable stalls — nor as "sí",
# which would sell a local that cannot legally cook.


@dataclass(frozen=True)
class Requisito:
    nombre: str
    estado: str  # "si" | "no" | "desconocido"
    nota: str


# Neighbours ---------------------------------------------------------------


@dataclass(frozen=True)
class Vecino:
    """A stall already operating in the fair — the real competition."""

    nombre: str
    rubro: str
    ticket: str  # "bajo" | "medio" | "alto"
    horario: str
    vende: str


VECINOS = [
    Vecino(
        "La Parrilla del Korner",
        "Parrilla y carnes",
        "alto",
        "12:00 – 23:00",
        "Costilla, chorizo, papas. Domina la cena del fin de semana.",
    ),
    Vecino(
        "Arepería Doña Chepa",
        "Arepas y desayunos",
        "bajo",
        "08:00 – 15:00",
        "Arepas rellenas y empanadas. Cierra antes del pico de la tarde.",
    ),
    Vecino(
        "Sushi Kōrner",
        "Sushi y rolls",
        "alto",
        "18:00 – 23:00",
        "Rolls y combos para compartir. Solo noche.",
    ),
    Vecino(
        "Frappé Bar",
        "Bebidas frías y postres",
        "bajo",
        "11:00 – 22:00",
        "Frappés, helados, brownies. Acompaña, no resuelve una comida.",
    ),
]

# What nobody in the fair sells today. This is the part an emprendedor actually
# buys: not "there is traffic", but "there is traffic that leaves without
# finding what it wanted".
HUECOS = [
    (
        "Comida rápida de salida",
        "El pico de las 21:00 sale del padel y no hay nada listo en 5 minutos.",
    ),
    ("Post-entreno saludable", "Bowls, proteína, jugos. Ningún local del pasillo lo cubre."),
    ("Café de especialidad temprano", "Antes de las 11:00 solo abre la arepería."),
    ("Opción vegetariana", "Cuatro locales, ninguno con plato sin carne."),
]


# Locales ------------------------------------------------------------------


@dataclass(frozen=True)
class Local:
    id: str
    nombre: str
    ubicacion: str
    area_m2: int
    canon: str
    flujo_pct: int  # share of the venue flow that passes this door
    cocina: tuple[Requisito, ...]
    # Metres from this local to each stall in VECINOS, same order.
    distancias_m: tuple[int, ...]
    resumen: str


LOCALES = [
    Local(
        id="L04",
        nombre="Local 04",
        ubicacion="Frente a cancha de padel 2",
        area_m2=18,
        canon="$180 / mes",
        flujo_pct=82,
        cocina=(
            Requisito("Extracción y ducto", "si", "Campana instalada, sale a techo."),
            Requisito("Conexión de gas", "si", "Compartida con el local 05."),
            Requisito("Trampa de grasas", "si", "Del local anterior, sin certificar."),
            Requisito("Concepto sanitario", "desconocido", "Nadie lo tramitó todavía."),
        ),
        distancias_m=(14, 38, 26, 9),
        resumen=(
            "El de mejor relación entre flujo y cocina. Ve pasar al jugador que sale de cancha."
        ),
    ),
    Local(
        id="L07",
        nombre="Local 07",
        ubicacion="Pasillo de entrada",
        area_m2=12,
        canon="$150 / mes",
        flujo_pct=100,
        cocina=(
            Requisito("Extracción y ducto", "no", "No hay ducto y el pasillo es cubierto."),
            Requisito("Conexión de gas", "no", "Sin acometida."),
            Requisito("Trampa de grasas", "no", "Sin desagüe propio."),
            Requisito("Concepto sanitario", "desconocido", "Depende de qué se instale."),
        ),
        distancias_m=(31, 12, 44, 18),
        resumen="Pasa todo el mundo, pero solo sirve para producto frío o terminado.",
    ),
    Local(
        id="L09",
        nombre="Local 09",
        ubicacion="Terraza, fondo",
        area_m2=26,
        canon="$210 / mes",
        flujo_pct=46,
        cocina=(
            Requisito("Extracción y ducto", "si", "Terraza abierta, salida directa."),
            Requisito("Conexión de gas", "desconocido", "Hay tubería, sin prueba de presión."),
            Requisito("Trampa de grasas", "si", "Instalada y certificada en 2025."),
            Requisito("Concepto sanitario", "si", "Vigente hasta 03/2027."),
        ),
        distancias_m=(22, 55, 19, 33),
        resumen="El más grande y el único con papeles al día. A cambio, la mitad del flujo.",
    ),
]

LOCALES_POR_ID = {loc.id: loc for loc in LOCALES}
