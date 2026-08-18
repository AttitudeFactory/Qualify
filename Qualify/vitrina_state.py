"""State for the "Vitrina de locales" demo.

Presentation only. There is no backend here on purpose: every var below is
derived from the frozen literals in `vitrina_data`, so the module can be opened
and shown to a microcentro owner without a database, an API or a network call.

The row dataclasses are flat (str/int fields only) because they cross to the
frontend as Vars; the nested shapes stay on the `vitrina_data` side.
"""

from dataclasses import dataclass
from typing import Any

import reflex as rx

from . import vitrina_data as D

# Ordered so the segmented control and the curve lookup cannot drift apart.
_CURVAS = {"semana": D.FLUJO_SEMANA, "finde": D.FLUJO_FINDE}


@dataclass
class LocalCard:
    """One selectable local in the picker."""

    id: str
    nombre: str
    ubicacion: str
    area: str
    canon: str
    flujo: str
    apto: str  # "si" | "parcial" | "no"
    apto_label: str
    seleccionado: bool


@dataclass
class PublicoRow:
    nombre: str
    share: int
    share_label: str
    pico: str
    nota: str


@dataclass
class RequisitoRow:
    nombre: str
    estado: str  # "si" | "no" | "desconocido"
    nota: str


@dataclass
class VecinoRow:
    nombre: str
    rubro: str
    ticket: str
    horario: str
    vende: str
    distancia: str


@dataclass
class HuecoRow:
    titulo: str
    detalle: str


def _apto(loc: D.Local) -> tuple[str, str]:
    """Collapse the four requirements into one verdict.

    Three-valued and in this order: a single hard "no" beats everything (you
    cannot cook), and an unknown never silently becomes a yes.
    """
    estados = {r.estado for r in loc.cocina}
    if "no" in estados:
        return "no", "Solo frío"
    if "desconocido" in estados:
        return "parcial", "Por verificar"
    return "si", "Cocina caliente"


class VitrinaState(rx.State):
    """Selection state for the demo. Nothing is persisted."""

    local_id: str = D.LOCALES[0].id
    dia: str = "semana"

    @rx.event
    def seleccionar(self, local_id: str) -> None:
        self.local_id = local_id

    @rx.event
    def cambiar_dia(self, dia: str | list[str]) -> None:
        # `segmented_control` hands back `str | list[str]` (it also serves the
        # multi-select variant), so the handler has to accept both or Reflex
        # rejects the binding at component-construction time.
        self.dia = dia if isinstance(dia, str) else (dia[0] if dia else "semana")

    # -- the venue ---------------------------------------------------------

    @rx.var
    def resumen(self) -> list[PublicoRow]:
        # Reused shape: nombre/nota carry the label and the footnote.
        return [
            PublicoRow(nombre=label, share=0, share_label=valor, pico="", nota=nota)
            for label, valor, nota in D.RESUMEN
        ]

    # -- the picker --------------------------------------------------------

    @rx.var
    def locales(self) -> list[LocalCard]:
        cards = []
        for loc in D.LOCALES:
            apto, apto_label = _apto(loc)
            cards.append(
                LocalCard(
                    id=loc.id,
                    nombre=loc.nombre,
                    ubicacion=loc.ubicacion,
                    area=f"{loc.area_m2} m²",
                    canon=loc.canon,
                    flujo=f"{loc.flujo_pct}% del flujo",
                    apto=apto,
                    apto_label=apto_label,
                    seleccionado=loc.id == self.local_id,
                )
            )
        return cards

    @property
    def _local(self) -> D.Local:
        return D.LOCALES_POR_ID.get(self.local_id, D.LOCALES[0])

    # -- the selected local ------------------------------------------------

    @rx.var
    def local_nombre(self) -> str:
        return self._local.nombre

    @rx.var
    def local_ubicacion(self) -> str:
        return self._local.ubicacion

    @rx.var
    def local_ficha(self) -> str:
        loc = self._local
        return f"{loc.area_m2} m² · {loc.canon} · {loc.flujo_pct}% del flujo del club"

    @rx.var
    def local_resumen(self) -> str:
        return self._local.resumen

    # -- flow --------------------------------------------------------------

    @rx.var
    def flujo(self) -> list[dict[str, Any]]:
        """Venue curve scaled by how much of it reaches this particular door.

        Plain dicts, not a dataclass: recharts' `data` prop is typed as
        `Sequence[dict[str, Any]]` and rejects anything else at construction.
        """
        curva = _CURVAS.get(self.dia, D.FLUJO_SEMANA)
        pct = self._local.flujo_pct
        return [
            {"hora": h, "valor": round(v * pct / 100)} for h, v in zip(D.HORAS, curva, strict=True)
        ]

    @rx.var
    def flujo_key(self) -> str:
        """Identity of the current curve, used as the chart's React key.

        Recharts keeps its own copy of `data` and does not redraw when the prop
        changes underneath it: switching local or day updated every label on the
        card while the bars stayed on the first curve rendered. Changing the key
        remounts the chart, which is the only thing that reliably redraws it.
        """
        return f"{self.local_id}-{self.dia}"

    @rx.var
    def pico(self) -> str:
        curva = _CURVAS.get(self.dia, D.FLUJO_SEMANA)
        hora = D.HORAS[curva.index(max(curva))]
        return f"{hora}:00"

    @rx.var
    def flujo_nota(self) -> str:
        cuando = "de lunes a viernes" if self.dia == "semana" else "sábado y domingo"
        return (
            f"Índice de gasto capturado por hora, {cuando}. 100 = la hora más fuerte "
            f"del club. Sale de las ventas agregadas de 6 locales de las últimas 8 "
            f"semanas, escalado por el {self._local.flujo_pct}% del flujo que pasa "
            f"por esta puerta."
        )

    # -- audience ----------------------------------------------------------

    @rx.var
    def publicos(self) -> list[PublicoRow]:
        return [
            PublicoRow(
                nombre=p.nombre,
                share=p.share,
                share_label=f"{p.share}%",
                pico=p.pico,
                nota=p.nota,
            )
            for p in D.PUBLICOS
        ]

    # -- hot kitchen -------------------------------------------------------

    @rx.var
    def cocina(self) -> list[RequisitoRow]:
        return [
            RequisitoRow(nombre=r.nombre, estado=r.estado, nota=r.nota) for r in self._local.cocina
        ]

    @rx.var
    def cocina_veredicto(self) -> str:
        estado, _ = _apto(self._local)
        return {
            "si": "Apto para cocina caliente",
            "parcial": "Apto con verificación pendiente",
            "no": "No apto para cocina caliente",
        }[estado]

    @rx.var
    def cocina_estado(self) -> str:
        return _apto(self._local)[0]

    @rx.var
    def cocina_detalle(self) -> str:
        estado, _ = _apto(self._local)
        return {
            "si": "Los cuatro requisitos están cubiertos y con papeles vigentes.",
            "parcial": (
                "Falta confirmar al menos un requisito. No lo damos por cumplido ni "
                "por incumplido: hay que verificarlo antes de firmar."
            ),
            "no": (
                "Falta al menos un requisito físico que no se resuelve con trámite. "
                "Sirve para producto frío, terminado o de reventa."
            ),
        }[estado]

    # -- neighbours --------------------------------------------------------

    @rx.var
    def vecinos(self) -> list[VecinoRow]:
        loc = self._local
        pares = sorted(
            zip(D.VECINOS, loc.distancias_m, strict=True),
            key=lambda par: par[1],
        )
        return [
            VecinoRow(
                nombre=v.nombre,
                rubro=v.rubro,
                ticket=v.ticket,
                horario=v.horario,
                vende=v.vende,
                distancia=f"{m} m",
            )
            for v, m in pares
        ]

    @rx.var
    def huecos(self) -> list[HuecoRow]:
        return [HuecoRow(titulo=t, detalle=d) for t, d in D.HUECOS]
