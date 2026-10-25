# Video final de noche, con «segunda mirada» — propuesta de flujo

`[v2 · 2026-10-24 · agente ux-designer · solo sugerencias, sin código · decisiones del fundador incorporadas, §6]` · Historia
[m-24852169](https://project.larksuite.com/5h2wsx/issue/detail/24852169), épica m-24852152
(`docs/epica-escalar-generacion.md`).

**Decisión del fundador (2026-10-24), que esto respeta:** los videos finales a 1080p de las
publicaciones programadas se hacen **de noche**. El final se queda en Tu semana para que el dueño
lo mire y **solo sale si lo confirma**. Asistido, nunca autónomo (N13, ADR 21). Sus palabras:
*«aviso de que su publicación está lista con la versión final, puede ser un aviso en la
publicación, en la pieza y en el calendario; también marcar esa distinción intuitivamente con la
card o un ícono; evitar central de notificaciones o disclaimers everywhere»*.

Lo marcado **⚑ Fundador** fue decidido por el fundador el 2026-10-24 (§6): seis puntos como se
recomendaban y dos cambiados (el costo de «Pedir otra versión», §2.6, y el correo de la mañana
en lugar de WhatsApp, §8). Lo marcado **hipótesis** se apoya en algo que
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
| H | Pidió otra versión | (vuelve a «Por revisar» de hoy; **la fecha se mantiene**, ⚑ decidido) | «En revisión» (la de hoy) | `warn` | — | Revisar la nueva vista previa |

Reglas de esos estados:

1. **Si no confirma, no sale.** Nunca se publica un final que el dueño no vio (decisión firmada).
   El evento **no pasa a «Fallido»**: nada falló, falta él. Queda «Programado · Falta tu
   confirmación» con el borde ámbar que ya existe para lo que no saldrá así (`overdue`,
   `Qualify/planner_vm.py:1161-1163`), y aparece en Inicio. A las 24 h se vuelve «Vencido» con la
   regla de hoy (QUA-115): **no hace falta una regla nueva**.
   **Lo mismo con otra versión:** si el dueño pide otra versión de un final programado, la
   publicación **conserva su fecha**; si la nueva versión no está confirmada a esa hora, no sale y
   muestra «Falta tu confirmación» (estado E). ⚑ Decidido (fundador, 2026-10-24).
2. **Si confirma tarde** (estado E), el botón no publica a ciegas a otra hora: ofrece «Confirmar y
   publicar ahora» (sólido) o «Elegir otra hora» (suave). Publicar 3 horas tarde puede no
   servirle (un almuerzo a las 4 p. m.); que elija él. ⚑ Decidido (§6.3).
3. **Si el final falla**, primero se reintenta solo durante la misma noche (es generar, no
   publicar: no choca con «asistido»). Solo si sigue fallando por la mañana se muestra G. «Intentar
   de nuevo» ya existe (`retry_final_render`) y, según #299, **no usa otro video** (el video
   vuelve al fallar y reintentar no cobra, `docs/creaciones-del-mes-medicion.md` §7.2). Si G llega
   a la hora de publicar, pasa como en E: no sale, y Inicio lo dice.
4. **Confirmar es de la pieza, no del evento.** Si la misma pieza sale dos veces (reel y
   publicación, `output_label`), un solo «Confirmar video» deja listas las dos fechas.
5. **La vista previa aprobada sin fecha también recibe su final esa noche** (ya se contó el video
   al aprobar). Así «Por aprobar» y Tu semana dicen lo mismo y nada espera a que el dueño programe.
   ⚑ Decidido (§6.6).
6. **¿Qué noche?** Se propone **la primera noche después de aprobar**, no la víspera de la
   publicación: el texto «mañana temprano» es siempre verdad, el dueño tiene días para mirar y
   pedir otra versión, y se evita la carrera con el vencimiento de 7 días de la vista previa (una
   publicación programada a 10 días no llegaría a tener final la víspera). ⚑ Decidido (§6.1).
7. **Si sale antes de esa noche** (programada para hoy a las 7 p. m., o «Publicar ahora»), el
   final se hace **en el momento y con prioridad**, y **igual pide confirmación**: «Tu video
   final estará listo en unos minutos. Te lo mostramos aquí para que lo confirmes.» ⚑ Decidido
   (§6.2).
8. **Todo video final pasa por «Revisa el video» y se confirma**, también los que el dueño pide a
   mano: el de prioridad (regla 7), el de «Intentar de nuevo» y el de una versión nueva tras
   «Pedir otra versión». No hay atajo que publique un final sin mirar. ⚑ Decidido (§6.8; fundador
   sobre ADR 41 §3.4).

*Hipótesis:* el dueño revisa por la mañana, antes o al abrir el local (`perfil-cliente-pyme.md`
§5 pregunta 3). Por eso el aviso fuera de la app es **un correo por la mañana** con los videos
listos (decidido, §8), no un aviso por cada video.

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
  abre el panel con el video arriba y el botón debajo (§2.2). ⚑ Decidido (§6.4).

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
| Pedir otra versión | **1 vista previa y 1 video** (decidido por el fundador, §6.5): la vista previa al pedirla (§7.2.2) y el video de la nueva versión al aprobarla. El video del final rechazado **no vuelve**. | «Usa 1 vista previa y 1 de tus videos del mes. Te quedarían {v}.» («Te quedaría 1.» con {v} = 1) |

El fundador eligió cobrar el video (§6.5), contra la recomendación de la v1 de devolverlo. Por
eso la línea debajo del botón dice las dos cosas **antes** de tocarlo, sin diálogo: el dueño sabe
que pedir otra versión gasta uno de sus videos del mes, y puede preferir confirmar o cancelar la
fecha. Costo para el equipo de cada «otra versión»: una vista previa más un final, USD 3,45 (5 s)
a 6,81 (10 s) p95 (`creaciones-del-mes-medicion.md` §7.4), que ahora el cupo cubre.

Cuándo se cobra el video de la nueva versión: al **aprobar** su vista previa, como cualquier video
(§7.2.1). Si el dueño pide otra versión y nunca aprueba la nueva, gasta solo la vista previa; la
línea dice «1 de tus videos» porque es lo que usará si sigue el camino normal. *Hipótesis:* el
dueño entiende ese «Usa» como «va a usar» (§5 pregunta 4); si no, el texto de aprobación de la
nueva versión vuelve a decirlo («Al aprobar usas 1 de tus 4 videos del mes…», el de hoy).

Sin vistas previas o sin videos en el mes: «Pedir otra versión» queda desactivado con la frase de
hoy encima («Ya usaste tus 20 vistas previas de este mes. Vuelven el {fecha}.» o «Ya usaste tus 4
videos de este mes. Vuelven el {fecha}.») y «Confirmar video» sigue disponible.

### 2.7 Fuera de Qualify: un correo por la mañana

Lo único que sale de la app es **un correo por la mañana** cuando hay videos para revisar (decidido,
§6.7). No hay WhatsApp, ni aviso por video, ni central de avisos. Diseño completo en §8.

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
│   Usa 1 vista previa y 1 de tus     │
│   videos del mes. Te quedarían 2.   │
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
│   Usa 1 vista previa y 1 de tus     │
│   videos del mes. Te quedarían 2.   │
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
| `OTHER_VERSION_USE` | línea debajo de «Pedir otra versión» | Usa 1 vista previa y 1 de tus videos del mes. Te quedarían {v}. / … Te quedaría 1. |
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
| `NO_VIDEOS_LEFT` | ídem, sin videos en el mes (el de hoy) | Ya usaste tus 4 videos de este mes. Vuelven el {fecha}. |

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
   «Pedir otra versión» sobre un final: cobra 1 vista previa al pedirla y 1 video al aprobar la
   nueva; el video del final rechazado no vuelve (§2.6). Su precio previo, para la línea debajo
   del botón, como `ContentService.recreate_price`.
4. Reintentos automáticos del final durante la noche; si sale antes de la noche (o «Publicar
   ahora»), final en el momento y **con prioridad** en la cola. Todo final, también los pedidos
   a mano, termina en «listo sin confirmar» (regla 8).
5. `HomeCounts`: `videos_to_confirm`, `videos_late`, `finals_failed` (con RLS, como
   `videos_expiring_soon`).
6. El correo de la mañana: §8.4.

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

## 6. Lo que decidió el fundador (2026-10-24)

| # | Pregunta | Decisión |
|---|---|---|
| 6.1 | ¿Qué noche se hace el final? | **La primera noche después de aprobar** (como se recomendaba). |
| 6.2 | ¿Y si sale antes de esa noche, o «Publicar ahora»? | **Final en el momento, con prioridad, y también se confirma.** |
| 6.3 | ¿Hasta cuándo puede confirmar? | **Hasta la hora de publicar**; después «Falta tu confirmación» 24 h y luego «Vencido». Confirmar tarde ofrece «publicar ahora» u «otra hora». |
| 6.4 | ¿Se confirma desde la tarjeta? | **No**: la tarjeta abre el panel, con el video y el botón. |
| 6.5 | «Pedir otra versión» de un final, ¿qué usa? | **Cambiado:** **1 vista previa y 1 video** (la v1 recomendaba no cobrar el video). Texto y tabla en §2.6. |
| 6.6 | Aprobada sin fecha, ¿también recibe el final esa noche? | **Sí.** |
| 6.7 | ¿Aviso fuera de Qualify? | **Cambiado:** **nada de WhatsApp**. Un **correo por la mañana** con los videos listos, uno por tanda, con enlaces a Tu semana (`?revisar=videos`) y a cada video, y cómo dejar de recibirlo. Diseño en §8. |
| 6.9 | Correo: remitente, hora y destinatarios | **Remitente «Qualify»** solo para este correo (la invitación sigue con «Herwin de Qualify»); **7:00 a. m.** en la zona del negocio (a validar); a **todos los que pueden aprobar** (dueños y administradores), cada uno se da de baja por su cuenta. |
| 6.10 | Otra versión de un final programado | **Conserva la fecha**; si la nueva versión no se confirma a tiempo, no sale y muestra «Falta tu confirmación». |
| 6.8 | ¿El estado del video va en el eje «lista para salir»? | **Sí.** Y **todo final, también los pedidos a mano, pasa por «Revisa el video» y se confirma** (respuesta del fundador a ADR 41 §3.4). |

## 7. Hipótesis y cómo validarlas

| Hipótesis | Se apoya en | Pregunta (`perfil-cliente-pyme.md` §5) | Cómo validarla |
|---|---|---|---|
| El dueño abre Qualify por la mañana, antes o al abrir el local, y ahí revisa | «mañana temprano», Inicio como único aviso | 3 (dispositivo, momento del día) | Contar cuántos eventos llegan a E en las primeras 4 semanas con Bianki y Polette |
| Prefiere que no salga antes que que salga sin verlo | «si no confirma, no sale» | 8 (qué le daría miedo que hiciera sin preguntarle) | Preguntarlo con la maqueta de §3.2 |
| Entiende «vista previa» frente a «video final» sin explicación | las pastillas y notas | 4 (sus palabras) y 6 (dónde se detiene) | Mostrarle §3.3 y pedirle que diga qué falta para que salga |
| Confirmar con un toque no se vuelve un trámite que hace sin mirar | la segunda mirada | 6 | Observar si reproduce el video antes de confirmar; si no, pensar en otra forma, no en más avisos |
| La hora de envío (7:00 a. m.) le sirve — **decidido, a validar** — y lee el correo en el celular | §8 | 3 | Aperturas y toques en «Revisar mis videos» por hora local (eventos de Resend, §8.4); cuántos videos llegan a E con y sin correo abierto |
| Un correo al día como máximo no se siente como spam | §8.1 | 8 | Cuántos dueños tocan «Deja de recibir estos correos» en el primer mes |

## 8. El correo de la mañana (decisión del fundador, 2026-10-24)

### 8.1 Cuándo sale y cuándo no

- **Uno por negocio y por mañana, como máximo**, cuando termina la tanda de la noche: a las
  **7:00 a. m. en la zona del negocio**. ⚑ Decidido (fundador, 2026-10-24); queda **a validar**
  con datos reales (§7). Si a esa hora la tanda no terminó, sale con lo que esté listo y lo que
  quede llega en el correo del día siguiente, nunca en un segundo correo.
- **Sale solo si hay algo que hacer:** al menos un video que se preparó esa noche y espera
  confirmación (C), o uno que no se pudo preparar (G). Si no hay nada, no hay correo.
- **Qué incluye:** los videos preparados esa noche y, arriba de todo, los que **salen hoy** y
  siguen sin confirmar aunque se hayan preparado antes. Un video que ya salió en un correo
  anterior y no sale hoy **no vuelve a aparecer**: el recordatorio de esos es Inicio. Así nadie
  recibe el mismo aviso todos los días.
- **No sale correo** por un final hecho en el momento (regla 7): el dueño acaba de pedirlo y lo ve
  en la app en unos minutos.
- **A quién:** a **todas las personas del negocio que pueden aprobar** (dueños y administradores),
  un correo a cada una. **Cada una se da de baja por su cuenta**: apagarlo para una no lo apaga
  para las demás. Cuando lo opera el equipo, le llega también al operador: por eso el asunto
  empieza con el nombre del negocio. ⚑ Decidido (fundador, 2026-10-24).

### 8.2 El correo, texto por texto

| Parte | Texto |
|---|---|
| Remitente (nombre) | **Qualify**, ⚑ decidido: solo para este correo automático; la invitación sigue firmando «Herwin de Qualify» (dirección: la de los correos de hoy en `send.qualify.la`, `QUALIFY_MAIL_FROM`; ver §8.4) |
| Asunto, 1 video | {negocio}: tu video está listo para revisar |
| Asunto, varios | {negocio}: tus {n} videos están listos para revisar |
| Asunto, si alguno sale hoy | {negocio}: {n} video sale hoy y espera tu confirmación / {n} videos salen hoy y esperan tu confirmación |
| Asunto, solo fallos | {negocio}: no pudimos preparar {n} video / {n} videos |
| Línea de vista previa (gris junto al asunto) | Míralo y confírmalo para que salga. Sin tu confirmación, no se publica. / (plural) Míralos y confírmalos para que salgan. Sin tu confirmación, no se publican. |
| Título | Tu video está listo / Tus videos están listos |
| Saludo y entrada | Hola, {nombre}. Esta noche preparamos el video final de {n} publicación(es) de {negocio}. Míralos y confírmalos para que salgan el día que elegiste. |
| Bloque «Sale hoy» (si hay) | **Sale hoy** — y debajo sus filas |
| Fila de cada video | miniatura · **{título}** · «Sale el {día} a las {hora} · Instagram, reel» (o «Todavía sin fecha») · enlace «Ver video ›» |
| Fila de un video que falló | miniatura · **{título}** · «No pudimos preparar el video final. Ábrelo para intentarlo de nuevo; no usa otro video.» · enlace «Abrir ›» |
| Botón | **Revisar mis videos** |
| Línea de calma, debajo del botón | Nada sale sin tu confirmación. Si no confirmas un video, no se publica y lo verás en Inicio. |
| Pie | Recibes este correo porque tienes videos por revisar en Qualify para {negocio}. Te escribimos como máximo una vez al día y solo cuando hay algo listo. |
| Cómo dejar de recibirlo | ¿Prefieres no recibirlo? **Deja de recibir estos correos**. También puedes cambiarlo en Configuración. |

Con más de 4 videos se muestran los 4 primeros (los que salen antes) y una línea «y {m} más en Tu
semana». Fechas y horas en la zona del negocio, con el formato de la app («jueves 30», «7:00 p. m.»).
Sin «render», «HD», «1080», «notificación», «link» ni «click»: «enlace», «toca».

### 8.3 Maqueta (celular, ~360 px)

```
┌────────────────────────────────────┐
│ De: Qualify                          │
│ Bianki: tus 2 videos están listos    │
│ para revisar                         │
│ Míralos y confírmalos para que       │
│ salgan. Sin tu confirmación, no…     │
├────────────────────────────────────┤
│        [Q] Qualify                   │
│                                      │
│  Tus videos están listos             │
│  Hola, Ana. Esta noche preparamos    │
│  el video final de 2 publicaciones   │
│  de Bianki. Míralos y confírmalos    │
│  para que salgan el día que elegiste.│
│                                      │
│  SALE HOY                            │
│  ┌──────┐ Combo Vecino al mediodía   │
│  │ ▶    │ Sale hoy a las 12:00 p. m. │
│  │      │ · Instagram, reel          │
│  └──────┘ Ver video ›                │
│  ───────────────────────────────     │
│  ┌──────┐ Shawarma mixto en 10 s     │
│  │ ▶    │ Sale el jueves 30 a las    │
│  │      │ 7:00 p. m. · Instagram     │
│  └──────┘ Ver video ›                │
│                                      │
│  ┌────────────────────────────────┐  │
│  │      Revisar mis videos        │  │  ← botón sólido acento
│  └────────────────────────────────┘  │
│  Nada sale sin tu confirmación. Si   │
│  no confirmas un video, no se        │
│  publica y lo verás en Inicio.       │
│ ──────────────────────────────────── │
│  Recibes este correo porque tienes   │
│  videos por revisar en Qualify para  │
│  Bianki. Te escribimos como máximo   │
│  una vez al día y solo cuando hay    │
│  algo listo.                         │
│  ¿Prefieres no recibirlo? Deja de    │
│  recibir estos correos.              │
└────────────────────────────────────┘
```

Miniatura: **una imagen fija** (el primer cuadro del video final, con el ▶ dibujado encima en la
misma imagen), unos 96 × 120 px y el doble de resolución; los clientes de correo no reproducen
video. Lleva `alt` con el título («Video: Combo Vecino al mediodía»). Toda la fila es enlace, no
solo «Ver video».

### 8.4 Lo que necesitan los ingenieros

**Envío (reusar, no construir).** El correo transaccional ya existe: `qualify_api.mail`
(`ResendMailer`, `OutgoingMail`, `default_mailer`; Resend con `QUALIFY_MAIL_FROM`, hoy «Herwin de
Qualify <no-reply@send.qualify.la>»), y la invitación (`qualify_api/auth/invite_email.py`) es la
plantilla de referencia: tablas, estilos en línea, botón «a prueba de Outlook», línea de vista
previa oculta, gemelo en texto plano, modo oscuro por `prefers-color-scheme`, colores por rol del
sistema de diseño. El correo de la mañana sigue esa misma plantilla. El correo del dominio pasó a
Lark, pero **el envío de la app sigue en Resend** (`send.qualify.la`); si hay `QUALIFY_MAIL_REPLY_TO`
(un buzón de Lark que alguien lee), el pie puede decir «Responde este correo si necesitas ayuda».

Cambios que pide (dueño sugerido: `backend-engineer` para la tanda y el envío, `creative-engineer`
para la miniatura, `reflex-ui-engineer` para Configuración y la página de baja):

1. **Remitente por correo** (decidido: «Qualify» solo aquí, la invitación sigue con «Herwin de
   Qualify»): `OutgoingMail` gana `sender` opcional (el nombre «Qualify» para este
   correo, la misma dirección) y `headers` (para la baja). Hoy el remitente es uno para toda la
   instalación.
2. **Baja en un toque:** cabeceras `List-Unsubscribe` (URL firmada) y `List-Unsubscribe-Post:
   List-Unsubscribe=One-Click`; el enlace del pie abre una página sin pedir sesión que dice
   «Listo. Ya no te enviaremos el correo de tus videos listos. Los verás igual en Inicio y en Tu
   semana.» con «Volver a recibirlos». Solo apaga **este** correo, nunca la invitación ni la
   recuperación de contraseña.
3. **Destinatarios:** todas las personas con permiso de aprobar en el negocio (dueños y
   administradores), un envío por persona; la clave de idempotencia del punto 4 pasa a ser
   (negocio, persona, fecha local).
3b. **Preferencia en Configuración, por persona:** un interruptor «Avisarme por correo cuando mis videos estén
   listos», encendido por defecto, guardado por persona y negocio (tabla con `tenant_id` + RLS).
4. **Una salida por negocio y día, idempotente:** una fila en una bandeja de salida con clave
   única (negocio, fecha local); reintentar la tanda nunca manda dos correos. Guarda qué videos
   incluyó (procedencia) para no repetirlos (§8.1) y el id de Resend para cruzarlo con el webhook
   de entregas que ya existe (`/api/mail/resend`).
5. **Enlaces:** el botón va a `https://<app>/planner?revisar=videos`; cada fila a
   `/planner?revisar=videos&evento=<id>` (abre el panel de ese video). Si la sesión venció, el
   ingreso devuelve al mismo enlace (`?volver=`, N4). **El video no se abre sin sesión**: es
   contenido del negocio y confirmarlo exige entrar.
6. **Miniaturas en una dirección estable:** las de R2 vencen; el correo necesita una imagen que
   siga viéndose unos días: una URL firmada de larga duración (p. ej. 7 días) o un proxy de la app
   con token sin sesión que solo sirve la miniatura. Nada del negocio en una URL adivinable.
7. **Cupo de Resend:** el plan gratis es de 100 correos al día y 3 000 al mes
   (`qualify_api/mail/__init__.py`). Un correo diario por negocio lo supera pasados unos 100
   negocios activos: revisar el plan antes de pasar de unas decenas (decisión de costo para el
   fundador cuando llegue).
8. **Pruebas offline:** asunto y línea de vista previa en singular y plural; nada de palabras de
   la lista prohibida; sin correo cuando no hay nada; un solo correo aunque la tanda corra dos
   veces; el enlace de baja apaga solo este correo; el texto plano contiene los mismos enlaces.

**Decidido, a validar** (§7): la hora de envío (7:00 a. m.). *Hipótesis*: que el dueño lea correo en el celular por la
mañana (`perfil-cliente-pyme.md` §5 pregunta 3); que un correo al día como máximo no se sienta
como spam (pregunta 8). Se miden con las aperturas y toques que ya registra el webhook de Resend.
