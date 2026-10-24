# Video final de noche, con «segunda mirada» — propuesta de flujo

`[v1 · 2026-10-24 · agente ux-designer · solo sugerencias, sin código]` · Historia
[m-24852169](https://project.larksuite.com/5h2wsx/issue/detail/24852169), épica m-24852152
(`docs/epica-escalar-generacion.md`).

**Decisión del fundador (2026-10-24), que esto respeta:** los videos finales a 1080p de las
publicaciones programadas se hacen **de noche**. El final se queda en Tu semana para que el dueño
lo mire y **solo sale si lo confirma**. Asistido, nunca autónomo (N13, ADR 21). Sus palabras:
*«aviso de que su publicación está lista con la versión final, puede ser un aviso en la
publicación, en la pieza y en el calendario; también marcar esa distinción intuitivamente con la
card o un ícono; evitar central de notificaciones o disclaimers everywhere»*.

Lo marcado **⚑ Fundador** necesita su decisión (§6). Lo marcado **hipótesis** se apoya en algo que
no sabemos del dueño y enlaza a su pregunta en `docs/perfil-cliente-pyme.md` §5.

## 0. Lo que cambia para el dueño, en una frase

**Hoy:** aprueba la vista previa → espera «Preparando el video final» con el botón apagado → recién
entonces elige día y hora. **Propuesta:** aprueba la vista previa → **elige día y hora en el acto**
→ a la mañana siguiente encuentra el video final en Tu semana → lo confirma con un toque. La espera
desaparece de su camino y la segunda mirada protege lo que más teme: que salga algo que no vio
(hipótesis, §5 pregunta 8).

Hoy, en código: aprobar pide el final en el momento (`approval_notice`, `Qualify/creative_vm.py:1070`);
mientras se hace, la tarjeta de Por aprobar queda en «Preparando el video final» con el botón
desactivado (`CARD_STATES["preparing"]`, `Qualify/planner_vm.py:704-711`) y Tu semana rechaza la
pieza (`MEDIA_DRAFT_PENDING`). Eso es lo que esta propuesta elimina del camino del dueño.

## 1. Los estados de una publicación con video programada

Tres ejes ya existen en Tu semana y **no se mezclan** (`Qualify/planner_vm.py:199-224`): la
aprobación de la pieza, el estado del evento (las **cinco palabras firmadas** de QUA-118 A1:
Programado · Pendiente · Publicado · Vencido · Fallido) y si está lista para salir
(`readiness`: «Listo para publicar» / «No listo»). **Propuesta: el video final vive en el eje
«lista para salir»**, no inventa palabras de estado del evento. Así el evento sigue diciendo
«Programado» y la segunda pastilla dice qué falta del video.

| # | Momento | Lo que lee el dueño (largo) | Corto (pastilla) | Tono | Icono Lucide | ¿Hace algo? |
|---|---|---|---|---|---|---|
| A | Aprobó la vista previa; el final todavía no se hace | «Tu video final estará listo mañana temprano» | «Video final mañana» | `neutral` | `moon` | No. Puede elegir día y hora ya |
| B | De noche, se está haciendo | (igual que A: el dueño no necesita saber que «se está haciendo») | «Video final mañana» | `neutral` | `moon` | No |
| C | El final está listo y nadie lo miró | «Tu video final está listo. Míralo y confírmalo para que salga.» | «Revisa el video» | `warn` | `clapperboard` | **Sí:** Confirmar video |
| D | Lo confirmó | «Confirmado. Sale el jueves 30 a las 7:00 p. m.» | «Listo para publicar» (la de hoy) | `ok` | — (como hoy) | No |
| E | Llegó la hora y no lo confirmó (dentro de las 24 h) | «No salió a las 7:00 p. m. porque falta que confirmes el video.» | «Falta tu confirmación» | `warn` + borde ámbar (`overdue`) | `triangle-alert` (el de hoy) | **Sí:** Confirmar y publicar ahora · Elegir otra hora |
| F | Pasaron más de 24 h sin confirmar | «Vencido» + la nota de hoy (`EXPIRED_NOTE`) | «Vencido» (el de hoy) | `warn` | `triangle-alert` | Reprogramar (como hoy) |
| G | El final no se pudo hacer (tras los reintentos de la noche) | «No pudimos preparar el video final. Inténtalo de nuevo; no usa otro video.» | «Falta el video final» (la de hoy) | `error` | `triangle-alert` | **Sí:** Intentar de nuevo |
| H | Pidió otra versión | (vuelve a «Por revisar» de hoy; la fecha se mantiene) | «En revisión» (la de hoy) | `warn` | — | Revisar la nueva vista previa |

Reglas de esos estados:

1. **Si no confirma, no sale.** Nunca se publica un final que el dueño no vio (decisión firmada).
   El evento **no pasa a «Fallido»**: nada falló, falta él. Queda «Programado · Falta tu
   confirmación» con el borde ámbar que ya existe para lo que no saldrá así (`overdue`,
   `Qualify/planner_vm.py:1161-1163`), y aparece en Inicio. A las 24 h se vuelve «Vencido» con la
   regla de hoy (QUA-115): **no hace falta una regla nueva**.
2. **Si confirma tarde** (estado E), el botón no publica a ciegas a otra hora: ofrece «Confirmar y
   publicar ahora» (sólido) o «Elegir otra hora» (suave). Publicar 3 horas tarde puede no
   servirle (un almuerzo a las 4 p. m.); que elija él. ⚑ Fundador (§6.3).
3. **Si el final falla**, primero se reintenta solo durante la misma noche (es generar, no
   publicar: no choca con «asistido»). Solo si sigue fallando por la mañana se muestra G. «Intentar
   de nuevo» ya existe (`retry_final_render`) y, según #299, **no usa otro video** (el video
   vuelve al fallar y reintentar no cobra, `docs/creaciones-del-mes-medicion.md` §7.2). Si G llega
   a la hora de publicar, pasa como en E: no sale, y Inicio lo dice.
4. **Confirmar es de la pieza, no del evento.** Si la misma pieza sale dos veces (reel y
   publicación, `output_label`), un solo «Confirmar video» deja listas las dos fechas.
5. **La vista previa aprobada sin fecha también recibe su final esa noche** (ya se contó el video
   al aprobar). Así «Por aprobar» y Tu semana dicen lo mismo y nada espera a que el dueño programe.
   ⚑ Fundador (§6.6).
6. **¿Qué noche?** Se propone **la primera noche después de aprobar**, no la víspera de la
   publicación: el texto «mañana temprano» es siempre verdad, el dueño tiene días para mirar y
   pedir otra versión, y se evita la carrera con el vencimiento de 7 días de la vista previa (una
   publicación programada a 10 días no llegaría a tener final la víspera). ⚑ Fundador (§6.1).
7. **Si sale antes de esa noche** (programada para hoy a las 7 p. m., o «Publicar ahora»), el
   final se hace en el momento, como hoy, y **igual pide confirmación**: «Tu video final estará
   listo en unos minutos. Te lo mostramos aquí para que lo confirmes.» ⚑ Fundador (§6.2).

*Hipótesis:* el dueño abre Qualify por la mañana, antes o al abrir el local, y ahí revisa
(`perfil-cliente-pyme.md` §5 pregunta 3). Si no abre Qualify a diario, el estado E será frecuente
y hará falta un recordatorio fuera de la app (§6.7).

## 2. Cómo se ve cada estado, sin central de avisos ni avisos por todos lados

Principio: **el aviso vive en la cosa**, una sola vez por superficie, y solo grita cuando hay algo
que hacer. A y B son silenciosos (icono + palabra gris); C, E y G llaman (tono `warn`/`error` +
palabra + una línea en Inicio). Nunca color solo (P1, N12): cada tono va con su palabra escrita.

### 2.1 Tu semana — la tarjeta

- **Celular (lista, siempre a 360 px, `Qualify/planner_page.py:526-604`):** la pastilla de arriba
  (`pill(event.approval_label, event.approval_tone)`) pasa a ser el estado del video con su icono:
  `tone_badge("Video final mañana", "neutral", icon="moon")`, `tone_badge("Revisa el video",
  "warn", icon="clapperboard")`, `tone_badge("Falta tu confirmación", "warn",
  icon="triangle-alert")`. La de abajo sigue siendo el estado del evento («Programado»). C, E y G
  llevan el borde ámbar de la tarjeta (`q-plist-card--overdue`, ya existe); A y B no.
- **Escritorio (calendario, una línea por chip, `Qualify/planner_page.py:220-296`):** un glifo más
  en el lugar del glifo de estado que ya existe: `moon` en gris (`T.TEXT_MUTED`) para A/B,
  `clapperboard` en `warn` para C, y el `triangle-alert` de hoy para E/G. La palabra va en el
  nombre accesible (`aria_label` ya suma `approval_label`) y en la tarjeta al pasar el puntero; un
  toque abre el panel, que lo dice en palabras (nada depende del puntero, N12).
- **No** se confirma desde el chip ni desde la tarjeta de la lista: hay que ver el video. Un toque
  abre el panel con el video arriba y el botón debajo (§2.2). ⚑ Fundador (§6.4).

### 2.2 Tu semana — el panel de la publicación

- El escenario (`_detail_body`, `Qualify/planner_drawer.py:1602`) ya muestra el video con
  controles: muestra el **final** cuando existe. Arriba a la izquierda, donde va `kind_chip`, se
  agrega `tone_badge` con el estado del video («Video final mañana» / «Revisa el video»).
- En C/E, el pie (`_detail_footer`, `Qualify/planner_drawer.py:1906`) gana una fila propia
  **encima** de Reprogramar/Cancelar, igual que la fila de revisión de hoy («Aprobar» / «No la
  quiero», m-24842984): **«Confirmar video»** (sólido, primero bajo el pulgar) y **«Pedir otra
  versión»** (suave, gris; no rojo: no destruye nada). Debajo de «Pedir otra versión», una línea
  con lo que usa (§2.6).
- Después de confirmar (N3): el panel cambia a «Confirmado. Sale el jueves 30 a las 7:00 p. m.» y
  ofrece **un** botón sólido al siguiente trabajo — «Revisar el siguiente (1 más)» si quedan
  videos por confirmar, si no «Ver Tu semana» — y el toast queda como eco, nunca como único
  resultado.

### 2.3 La página de la publicación (`/drafts/<id>`)

- La pastilla y la nota que ya existen (`_video_draft_notice`, `Qualify/creative_pages.py:1486`;
  `video_draft_vm`, `Qualify/creative_vm.py:1148`) dicen el estado A/C/D/G con las mismas palabras
  de Tu semana.
- La tarjeta «Aprobada. Todavía no se publica.» (`_approved_next`, `creative_pages.py:2334`) deja
  de esperar al final: con la vista previa aprobada ofrece **«Elegir día y hora»** de inmediato, y
  su texto pasa a «Tu video final estará listo mañana temprano. Elige ya cuándo sale: lo
  confirmas antes de que salga.»
- En C, debajo del video: «Confirmar video» (sólido) y «Pedir otra versión» (suave), como en el
  panel. Es la misma acción en los dos lugares; el dueño confirma donde esté.

### 2.4 Por aprobar (`/drafts`)

- Las tarjetas usan `CARD_STATES` (`Qualify/planner_vm.py:700-720`). Cambios propuestos:
  - `preparing` («Preparando el video final», botón desactivado) **se reemplaza** por
    `final_tomorrow`: «Video final mañana», tono `neutral`, botón **«Elegir día y hora»** si no
    tiene fecha o «Ver en Tu semana» si ya la tiene. Ya no hay botón apagado esperando.
  - Nuevo `final_review`: «Revisa el video final», tono `warn`, botón «Revisar video» (abre la
    página de la publicación, donde está el reproductor y «Confirmar video»).
  - G reutiliza «Falta el video final» con «Intentar de nuevo».
- Un filtro más en la fila de filtros: «Revisa el video final» (slug `?estado=revisar-video`, N5),
  para que Inicio abra la lista filtrada (N11).

### 2.5 Inicio — «Hoy tienes»

Una sola línea, **solo cuando hay algo que hacer** (C, E o G), con el patrón de `_today`
(`Qualify/home_vm.py:130-166`, `TodayCardVM`, icono `clapperboard`):

| Situación | Texto | Lleva a |
|---|---|---|
| Hay finales listos (C) | «1 video listo para revisar» / «{n} videos listos para revisar» | `/planner?revisar=videos` (abre el panel del primero; §5) |
| Alguno ya debía salir (E) — reemplaza a la anterior, no se suma | «1 video no salió: falta tu confirmación» / «{n} videos esperan tu confirmación; {m} ya debía salir» | igual, los atrasados primero |
| Falló el final (G) — línea aparte, rara | «1 video final no se pudo preparar» / «{n} videos finales no se pudieron preparar» | `/drafts?estado=por-completar` |

A y B **no** aparecen en Inicio: no hay nada que hacer.

### 2.6 Lo que cuesta, con las reglas de #299

| Acción | Usa | Texto (antes de tocar, en una línea debajo del botón, sin diálogo) |
|---|---|---|
| Aprobar la vista previa | **1 video** (como hoy: el video se cuenta al aprobar) | «Al aprobar usas 1 de tus 4 videos del mes. Te quedarían {v}.» (el de hoy) |
| Confirmar video | **Nada** | — (no se dice nada: no hay costo que explicar) |
| Intentar de nuevo (final falló) | **Nada** (el video vuelve al fallar, el reintento no cobra) | «No usa otro video.» |
| Pedir otra versión | **1 vista previa** (§7.2.2: cada «Pedir otra versión» de un video cuenta una). **Propuesta: el video no se cobra dos veces**: al pedir otra versión, el video de la aprobación vuelve, y se vuelve a usar al aprobar la nueva. Neto para el dueño: 1 vista previa. | «Usa 1 de tus vistas previas. Te quedan {p}.» (como `recreate_use_text`) |

Por qué no cobrar otro video: el dueño no usó el final que rechazó; cobrarle «un video» por algo que
no le sirvió rompe la confianza justo en la segunda mirada, que existe para que diga «no». El abuso
queda acotado por las 20 vistas previas del mes. Costo para el equipo de cada «otra versión»: una
vista previa más un final, USD 3,45 (5 s) a 6,81 (10 s) p95 (`creaciones-del-mes-medicion.md` §7.4).
⚑ Fundador (§6.5). Si decide cobrar el video, el texto es «Usa 1 vista previa y 1 de tus 4 videos
del mes. Te quedarían {v}.»

Sin vistas previas en el mes: «Pedir otra versión» queda desactivado con la frase de hoy encima
(«Ya usaste tus 20 vistas previas de este mes. Vuelven el {fecha}.») y «Confirmar video» sigue
disponible.

## 3. Maquetas a 360 px

Ancho útil ≈ 328 px (16 px de margen a cada lado). `[ ]` = botón; `( )` = pastilla
(`tone_badge`/`signal_pill`); `▌` = borde ámbar de la tarjeta (`overdue`). Iconos: `☾` = `moon`, `▣` = `clapperboard`, `⚠` = `triangle-alert`, `✓` = `check`, `↻` = `refresh-cw`, `◎` = marca de la red.

### 3.1 Tarjeta en Tu semana (lista del celular)

```
Estado A — aprobada, final esta noche (silenciosa)
┌────────────────────────────────────┐
│ 7:00 p. m.                          │
│ ┌──────┐ Combo Vecino al mediodía   │
│ │  ▶   │ Precio a la vista, porci…  │
│ └──────┘ ◎ @bianki · Reel           │
│          (☾ Video final mañana)     │
│          (● Programado)          ⋯  │
└────────────────────────────────────┘

Estado C — final listo, falta mirarlo (llama)
▌┌───────────────────────────────────┐
▌│ 7:00 p. m.                         │
▌│ ┌──────┐ Combo Vecino al mediodía  │
▌│ │  ▶   │ Precio a la vista, porci… │
▌│ └──────┘ ◎ @bianki · Reel          │
▌│          (▣ Revisa el video)       │
▌│          (● Programado)         ⋯  │
▌└───────────────────────────────────┘

Estado E — pasó la hora sin confirmar
▌┌───────────────────────────────────┐
▌│ 7:00 p. m.                         │
▌│ ┌──────┐ Combo Vecino al mediodía  │
▌│ │  ▶   │ ◎ @bianki · Reel          │
▌│ └──────┘ (⚠ Falta tu confirmación) │
▌│          (● Programado)         ⋯  │
▌│ ⚠ No salió a las 7:00 p. m. porque │
▌│   falta que confirmes el video.    │
▌└───────────────────────────────────┘
```

Toda la tarjeta abre el panel (como hoy). En el calendario de escritorio, el chip de una línea
suma `☾` (gris) o `▣` (ámbar) junto a la hora; el `⚠` de hoy cubre E y G.

### 3.2 Panel de la publicación en Tu semana (pantalla completa en el celular)

```
┌────────────────────────────────────┐
│ ✕   Combo Vecino al mediodía        │
├────────────────────────────────────┤
│ (Reel) (▣ Revisa el video)         │
│ ┌────────────────────────────────┐ │
│ │                                │ │
│ │          VIDEO FINAL           │ │
│ │          ▶  0:00 / 0:10        │ │
│ │                                │ │
│ └────────────────────────────────┘ │
│          Sale como reel             │
│                                     │
│ Tu video final está listo. Míralo   │
│ y confírmalo para que salga.        │
│                                     │
│ ┌ Cuándo ──────┐ ┌ Canal ────────┐ │
│ │ jue 30,      │ │ ◎ @bianki     │ │
│ │ 7:00 p. m.   │ │               │ │
│ └──────────────┘ └───────────────┘ │
│ …texto de la publicación…           │
├────────────────────────────────────┤
│ [ ✓ Confirmar video              ]  │  ← sólido, primero bajo el pulgar
│ [ ↻ Pedir otra versión           ]  │  ← suave, gris
│   Usa 1 de tus vistas previas.      │
│   Te quedan 12.                     │
│ [ Reprogramar ] [ ✕ Cancelar … ]  │
└────────────────────────────────────┘

Después de «Confirmar video» (N3):
├────────────────────────────────────┤
│ ✓ Confirmado. Sale el jueves 30 a   │
│   las 7:00 p. m.                    │
│ [ Revisar el siguiente (1 más)   ]  │  ← sólido
│ [ Ver Tu semana                  ]  │  ← suave
└────────────────────────────────────┘

Estado E (pasó la hora):
├────────────────────────────────────┤
│ ⚠ No salió a las 7:00 p. m. porque  │
│   falta que confirmes el video.     │
│ [ ✓ Confirmar y publicar ahora   ]  │
│ [ Elegir otra hora             ]  │
│ [ ↻ Pedir otra versión           ]  │
└────────────────────────────────────┘
```

### 3.3 Página de la publicación (`/drafts/<id>`)

```
Recién aprobada la vista previa (A)
┌────────────────────────────────────┐
│ ‹ Por aprobar                       │
│ Combo Vecino al mediodía            │
│ ┌────────────────────────────────┐ │
│ │        VISTA PREVIA  ▶         │ │
│ └────────────────────────────────┘ │
│ (☾ Video final mañana)              │
│ ┌────────────────────────────────┐ │
│ │ ✓ Aprobada. Todavía no se      │ │
│ │   publica.                     │ │
│ │ Tu video final estará listo    │ │
│ │ mañana temprano. Elige ya      │ │
│ │ cuándo sale: lo confirmas      │ │
│ │ antes de que salga.            │ │
│ │ [ Elegir día y hora       ]  │ │
│ │ [ Publicar ahora          ]  │ │
│ └────────────────────────────────┘ │
└────────────────────────────────────┘

A la mañana siguiente (C)
┌────────────────────────────────────┐
│ ‹ Por aprobar                       │
│ Combo Vecino al mediodía            │
│ ┌────────────────────────────────┐ │
│ │        VIDEO FINAL  ▶          │ │
│ └────────────────────────────────┘ │
│ (▣ Revisa el video)                │
│ Tu video final está listo. Míralo   │
│ y confírmalo para que salga.        │
│ Sale el jueves 30 a las 7:00 p. m.  │
│ [ ✓ Confirmar video              ]  │
│ [ ↻ Pedir otra versión           ]  │
│   Usa 1 de tus vistas previas.      │
│   Te quedan 12.                     │
└────────────────────────────────────┘

El final falló (G)
│ (⚠ Falta el video final)            │
│ No pudimos preparar el video final. │
│ Inténtalo de nuevo; no usa otro     │
│ video.                              │
│ [ ↻ Intentar de nuevo            ]  │
```

## 4. Textos exactos (`qualify-copy-es`)

Leídos en voz alta como el dueño de Bianki. Sin «render», «1080p», «HD», «notificación» ni
«borrador» de cara al cliente; «video final» y «vista previa» son las palabras que la pantalla ya
usa (`creative_vm.py:1110`, `1169`). {día} y {hora} en la zona del negocio, formato de hoy
(«jueves 30», «7:00 p. m.»).

| Clave sugerida | Dónde | Texto |
|---|---|---|
| `FINAL_TOMORROW_SHORT` | pastilla (tarjeta, panel, página, Por aprobar) | Video final mañana |
| `FINAL_TOMORROW_NOTE` | panel y página, estado A | Tu video final estará listo mañana temprano. |
| `FINAL_TOMORROW_NOTE_NIGHT` | ídem, si se aprueba de madrugada (dentro de la noche) | Tu video final estará listo en unas horas. |
| `FINAL_SOON_NOTE` | ídem, sale antes de la noche o «Publicar ahora» | Tu video final estará listo en unos minutos. Te lo mostramos aquí para que lo confirmes. |
| `APPROVED_PREVIEW_BODY` | tarjeta «Aprobada. Todavía no se publica.» | Tu video final estará listo mañana temprano. Elige ya cuándo sale: lo confirmas antes de que salga. |
| `APPROVE_DECISION_TEXT` | tarjeta de decisión «Aprobar esta versión» (`creative_pages.py:2460`) | Te quedas con esta versión. Esta noche preparamos el video final y mañana lo confirmas antes de que salga. |
| `FINAL_REVIEW_SHORT` | pastilla | Revisa el video |
| `FINAL_REVIEW_CARD` | estado de tarjeta en Por aprobar y filtro | Revisa el video final |
| `FINAL_REVIEW_NOTE` | panel y página, estado C | Tu video final está listo. Míralo y confírmalo para que salga. |
| `FINAL_REVIEW_WHEN` | página, estado C con fecha | Sale el {día} a las {hora}. |
| `CONFIRM_VIDEO` | botón sólido | Confirmar video |
| `REVIEW_VIDEO` | botón de la tarjeta de Por aprobar | Revisar video |
| `ASK_OTHER_VERSION` | botón suave | Pedir otra versión |
| `OTHER_VERSION_USE` | línea debajo (de `recreate_use_text`) | Usa 1 de tus vistas previas. Te quedan {p}. / Te queda 1. |
| `CONFIRMED_TITLE` | panel/página tras confirmar, con fecha | Confirmado. Sale el {día} a las {hora}. |
| `CONFIRMED_TWO_DATES` | ídem, la pieza tiene dos fechas | Confirmado. Sale en las 2 fechas que elegiste. |
| `CONFIRMED_NO_DATE` | ídem, sin fecha | Confirmado. Ahora elige cuándo sale. |
| `CONFIRMED_TOAST` | eco (nunca solo) | Video confirmado. |
| `REVIEW_NEXT` | botón tras confirmar | Revisar el siguiente ({n} más) |
| `BACK_TO_WEEK` | botón suave tras confirmar | Ver Tu semana |
| `LATE_SHORT` | pastilla, estado E | Falta tu confirmación |
| `LATE_NOTE` | tarjeta y panel, estado E | No salió a las {hora} porque falta que confirmes el video. |
| `CONFIRM_PUBLISH_NOW` | botón sólido, estado E | Confirmar y publicar ahora |
| `PICK_OTHER_TIME` | botón suave, estado E | Elegir otra hora |
| `FINAL_FAILED_NOTE_NIGHT` | panel y página, estado G | No pudimos preparar el video final. Inténtalo de nuevo; no usa otro video. |
| `RETRY_FINAL` | botón (el de hoy) | Intentar de nuevo |
| `OTHER_VERSION_PENDING` | panel, estado H | Estamos creando otra versión. Cuando esté, la revisas y la apruebas; la fecha no cambia. |
| `HOME_TO_REVIEW` | Inicio | 1 video listo para revisar / {n} videos listos para revisar |
| `HOME_LATE` | Inicio (reemplaza la anterior) | 1 video no salió: falta tu confirmación / {n} videos esperan tu confirmación; {m} ya debía salir |
| `HOME_FAILED` | Inicio | 1 video final no se pudo preparar / {n} videos finales no se pudieron preparar |
| `NO_PREVIEWS_LEFT` | encima de «Pedir otra versión» desactivado (el de hoy) | Ya usaste tus 20 vistas previas de este mes. Vuelven el {fecha}. |

Variante «m ya debía salir» con m = 1: «… 1 ya debía salir»; con m > 1: «… {m} ya debían salir».

## 5. Lo que necesita `reflex-ui-engineer` (y el backend antes)

Solo primitivas existentes (`Qualify/ui/primitives.py`) y reglas de `docs/design-system.md`: **ni
componentes ni colores nuevos**. Iconos Lucide que ya trae `rx.icon`: `moon`, `clapperboard`,
`triangle-alert`, `circle-check`, `refresh-cw`, `calendar-clock`.

**Backend (antes, `creative-engineer` + `backend-engineer`, fuera de este documento):**

1. Estados nuevos del video en `draft_mode`: final **en cola para la noche**, final **listo sin
   confirmar**, **confirmado** (con quién y cuándo, procedencia). Hoy son `draft`, `rendering`,
   `final`, `failed`, `expired`.
2. Tu semana **acepta programar** una pieza aprobada con el final en cola (hoy la rechaza con
   `MEDIA_DRAFT_PENDING`); quien publica (`calendar-worker`) **no toma** un evento cuyo video no
   está confirmado y lo deja `scheduled` (nunca `failed`); al pasar las 24 h vence como hoy.
3. Acciones: `confirm_final(piece)` (idempotente, deja listas todas las fechas de la pieza) y
   «Pedir otra versión» sobre un final (devuelve el video según §2.6 si el fundador lo aprueba).
4. Reintentos automáticos del final durante la noche; si sale antes de la noche, final en el
   momento.
5. `HomeCounts`: `videos_to_confirm`, `videos_late`, `finals_failed` (con RLS, como
   `videos_expiring_soon`).

**Interfaz:**

| Dónde | Qué cambia | Con qué |
|---|---|---|
| `creative_vm.py` · `video_draft_vm` | estados A, C, D, G con las claves de §4; `VideoDraftVM` gana `needs_confirm` y `late` | dataclass existente |
| `creative_vm.py` · `approval_notice` | con vista previa aprobada ya no bloquea: ofrece «Elegir día y hora» (`offer_schedule=True`) | existente |
| `planner_vm.py` · `readiness` / `build_card` | el eje «lista para salir» toma el estado del video (§1); `overdue=True` en C, E y G | `Readiness`, `EventCardVM` |
| `planner_vm.py` · `event_actions` | `can_confirm_video`, `can_ask_other_version`, `late` | `EventActions` |
| `planner_vm.py` · `CARD_STATES` | `preparing` → `final_tomorrow`; nuevos `final_review`; slug `revisar-video` | `CardStateVM` |
| `planner_page.py` · `_list_item` | la primera pastilla pasa a `tone_badge(label, tone, icon=…)` | `tone_badge` |
| `planner_page.py` · `_calendar_chip` | glifo `moon` / `clapperboard` en el `rx.match` de estado; la palabra ya está en `aria_label` | `rx.icon` + `T.tone_color` |
| `planner_drawer.py` · `_detail_body` | `tone_badge` del video en `q-stage-top`; nota del estado | `tone_badge`, `rx.text` |
| `planner_drawer.py` · `_detail_footer` | fila «Confirmar video» / «Pedir otra versión» encima de las acciones, con `q-panel-actions`; estado E con «Confirmar y publicar ahora» / «Elegir otra hora»; tras confirmar, la tarjeta N3 | `rx.button` sólido/suave `size="3"` |
| `creative_pages.py` · `_video_draft_notice`, `_approved_next` | los mismos estados y botones que el panel | `signal_pill`, `callout`, `rx.button` |
| `home_vm.py` · `_today` | las tres líneas de §2.5 (solo con conteo > 0) | `TodayCardVM` |
| `PlannerState` | `?revisar=videos` (N5) abre el panel del primer video por confirmar (atrasados primero) y «Revisar el siguiente» avanza en esa cola | estado existente del panel |

**Pruebas offline sugeridas:** cada estado dice palabra + tono (nunca color solo); ningún texto con
«render», «HD», «1080», «notificación»; «Confirmar video» no aparece sin video final; un evento sin
confirmar nunca muestra «Publicado» ni «Fallido»; Inicio sin línea en A/B; objetivos ≥ 44 px
(`_TAP_MIN_HEIGHT`).

## 6. Lo que decide el fundador

| # | Pregunta | Opciones | Recomendación |
|---|---|---|---|
| 6.1 | ¿Qué noche se hace el final? | (a) la primera noche después de aprobar · (b) la víspera de la publicación | **(a)**: «mañana temprano» siempre es verdad, hay días para pedir otra versión y no choca con el vencimiento de 7 días de la vista previa. (b) concentra el riesgo en la última noche |
| 6.2 | ¿Y si sale antes de esa noche (hoy, o «Publicar ahora»)? | (a) final en el momento, con confirmación · (b) no se permite programar antes de la noche | **(a)**, como hoy pero con la segunda mirada |
| 6.3 | ¿Hasta cuándo puede confirmar? | (a) hasta la hora de publicar; después «Falta tu confirmación» 24 h y luego «Vencido» · (b) un plazo antes (p. ej. 2 h) | **(a)**: no inventa un plazo nuevo y reusa la regla de 24 h. Confirmar tarde ofrece «publicar ahora» u «otra hora», nunca publica a otra hora sin decirlo |
| 6.4 | ¿Se confirma desde la tarjeta sin abrirla? | (a) no: un toque abre el panel con el video y el botón · (b) sí, botón en la tarjeta | **(a)**: confirmar sin ver contradice la segunda mirada; el panel está a un toque |
| 6.5 | «Pedir otra versión» de un final, ¿usa otro video? | (a) solo 1 vista previa; el video pasa a la nueva versión · (b) 1 vista previa + 1 video | **(a)**: no cobrar por lo que no le gustó; acotado por las 20 vistas previas. Costo al equipo USD 3,45–6,81 por vez (p95) |
| 6.6 | Aprobada sin fecha, ¿también recibe el final esa noche? | (a) sí · (b) solo las programadas | **(a)**: el video ya se contó al aprobar; todo dice lo mismo en todas partes |
| 6.7 | ¿Un recordatorio fuera de Qualify (WhatsApp al dueño) cuando un video espera? | (a) no por ahora · (b) uno solo, el día de la publicación | **(a)**, hasta validar la hipótesis de §1 (§5 pregunta 3). Sería un patrón nuevo y la decisión pide evitar avisos por todos lados |
| 6.8 | ¿El estado del video va en el eje «lista para salir» y no en las cinco palabras del evento? | (a) sí · (b) palabra nueva de evento | **(a)**: respeta QUA-118 A1 y no agrega estados al calendario |

## 7. Hipótesis y cómo validarlas

| Hipótesis | Se apoya en | Pregunta (`perfil-cliente-pyme.md` §5) | Cómo validarla |
|---|---|---|---|
| El dueño abre Qualify por la mañana, antes o al abrir el local, y ahí revisa | «mañana temprano», Inicio como único aviso | 3 (dispositivo, momento del día) | Contar cuántos eventos llegan a E en las primeras 4 semanas con Bianki y Polette |
| Prefiere que no salga antes que que salga sin verlo | «si no confirma, no sale» | 8 (qué le daría miedo que hiciera sin preguntarle) | Preguntarlo con la maqueta de §3.2 |
| Entiende «vista previa» frente a «video final» sin explicación | las pastillas y notas | 4 (sus palabras) y 6 (dónde se detiene) | Mostrarle §3.3 y pedirle que diga qué falta para que salga |
| Confirmar con un toque no se vuelve un trámite que hace sin mirar | la segunda mirada | 6 | Observar si reproduce el video antes de confirmar; si no, pensar en otra forma, no en más avisos |
