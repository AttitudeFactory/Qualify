# Creadores — experiencia, pantallas y textos

`[v1 · 2026-11-04 · agente ux-designer]` · **Estado:** propuesta para el fundador. Nada se construye
sin su visto bueno en lo marcado **⚑ Decisión**. **Para quién:** `reflex-ui-engineer` (entregas 1 y
Comparar, con detalle de construcción), `product-owner` (historias), `principal-architect` (lo que
toca datos). Hermanos que escriben otros agentes y que este documento no toca:
`docs/epica-creadores.md`, `docs/diseno-modulo-creadores.md`, `docs/arquitectura.md`.

> Esto es una **propuesta de diseño**, no una revisión: no se abrió la app. La pantalla de hoy
> (`/creadores`, el «Pronto» de `Qualify/creators_page.py`) se leyó en el código. Los números de
> los mockups son **datos de ejemplo**; las cuentas `@…` de los mockups son inventadas.

Fuentes: decisión del fundador del 2026-11-04 (el encargo: Analizar · Comparar · Encajar · Invitar ·
Presupuestar · Negociar); persona `docs/perfil-cliente-pyme.md`; reglas N1–N13
`docs/ux-guia-navegacion.md`; componentes `docs/design-system.md` §5 y `Qualify/ui/primitives.py`;
patrón de pestañas de `Qualify/results_page.py`; carrusel de `Qualify/media_carousel.py`.

**Maqueta visual:** `docs/mockups/creadores.html` (primera visita, revisar con error, ficha, comparar en
celular y escritorio, candidato e invitación). Ábrela en el navegador; es estática.

## 0. El trabajo del dueño, en una frase

> «Antes de darle producto o plata a alguien para que me recomiende, quiero saber si de verdad lo
> ve gente, y elegir al que más me conviene.» `[H]` — por analogía con el segmento del perfil §0
> (poco presupuesto: cada peso cuenta). Se valida con la pregunta 9 del perfil §5.

Todo en este módulo se juzga contra eso: **¿le evita pagarle a quien no lo ve nadie?, ¿le ahorra
tiempo de revisar perfiles a mano?** El beneficio que se dice en pantalla no es «análisis de
creadores» sino **«Mira cuánta gente ve de verdad a un creador antes de pagarle»**.

Quién lo usa primero: el equipo de Attitude Factory por el negocio (perfil §3). La pantalla se
escribe igual **para el dueño** (perfil §1, «Quién usa la pantalla hoy»).

## 1. Arquitectura de información

### 1.1 Una sola entrada del menú, un solo lugar

**Creadores** sigue siendo **una** entrada del menú, donde ya está (`Qualify/ui/layout.py:97`, grupo
de Resultados). No se agregan entradas: Comparar y Campañas viven **dentro** de Creadores. Cuando la
entrega 1 salga, la entrada pierde el «Pronto» (N10) y pasa a `enabled=True`.

```
Creadores                       /creadores                     (menú: «Creadores», h1: «Creadores»)
 ├─ pestaña «Tus creadores»     /creadores?tab=creadores       entrega 1 — la lista (por defecto)
 ├─ pestaña «Campañas»          /creadores?tab=campanas        entrega 3 — NO se muestra hasta que exista (N10)
 │
 ├─ Agregar creador             /creadores?flujo=agregar       cajón (drawer) encima de la lista
 ├─ Ficha de un creador         /creadores/[creator_id]        ilumina «Creadores» en el menú
 ├─ Comparar                    /creadores/comparar?ids=a,b,c  ilumina «Creadores»; 2 a 4 ids internos
 │
 ├─ Nueva campaña (asistente)   /creadores/campanas/nueva?paso=N        entrega 3
 └─ Una campaña                 /creadores/campanas/[campaign_id]?tab=… entrega 3–6
      └─ Un candidato           /creadores/campanas/[id]/[candidate_id] entrega 4–6 (ficha + historial)
```

- **Todo tiene su dirección (N5):** la pestaña, la ficha, la comparación y cada paso del asistente.
  Recargar o el «atrás» del celular dejan al dueño donde estaba. La URL lleva **ids internos**, nunca
  el @usuario ni montos (contrato de direcciones de la guía §4).
- **Una sola entrada iluminada (qualify-ux §5c):** toda ruta que empieza por `/creadores` ilumina
  «Creadores» en el menú y en «Más» del celular; comparar contra `router.url.path`, no el patrón
  (trampa conocida m-24852260).
- **Pestañas:** el mismo patrón de `results_page._tab_strip` (segmented control desde `md`, select a
  ancho completo en el celular). Mientras solo exista «Tus creadores», **no hay barra de pestañas**:
  una pestaña sola es ruido.
- **Comparar no es una pestaña:** es lo que se hace con la lista (elegir 2–4 → «Comparar»). Así el
  menú interno no crece y el dueño llega a comparar desde donde ya está mirando.
- **¿Por qué no una entrada «Campañas» propia?** Porque el dueño piensa «quiero que alguien me
  recomiende», no «voy a gestionar campañas»: todo el trabajo con creadores en un lugar.

**⚑ Decisión 1 — la palabra «campaña».** Ya existe «Campaña» en la app: agrupa publicaciones
(QUA-143, `Qualify/campaign_state.py`, campo «Campaña» de `/drafts/[id]`). Si el trabajo con
creadores se llama igual pero es otra cosa, la misma palabra significa dos cosas (glosario §7.2 del
sistema de diseño). Opciones:

| Opción | Qué ve el dueño | Contra |
|---|---|---|
| **A (recomendada)** — es **la misma campaña** | «Lanzamiento Combo Vecino» junta sus publicaciones **y** sus creadores | Hay que extender la campaña existente (lo decide `principal-architect`) |
| B — otra palabra | «Búsqueda de creadores» | Una palabra más que aprender; dos listas parecidas |
| C — misma palabra, otra cosa | «Campaña» en dos lugares con significados distintos | Confunde; incumple el glosario |

### 1.2 Primera visita: el estado vacío y su única acción

Al quitar el «Pronto», la primera visita no es una pantalla vacía (N8): explica qué obtiene y tiene
**un** botón sólido.

```
┌──────────────────────────────────────┐ 360 px
│ Creadores                            │ ← page_header (h1)
│ Mira cuánta gente ve de verdad a un  │   subtítulo
│ creador antes de darle producto o    │
│ pagarle                              │
├──────────────────────────────────────┤
│              (icono users)           │
│   Todavía no revisaste a ningún      │ ← empty_state título (h2)
│   creador                            │
│   Escribe su usuario de Instagram y  │
│   en unos segundos ves cuántas       │
│   personas ven sus reels, qué le     │
│   funciona y con qué marcas trabajó. │
│                                      │
│      [  Revisar un creador  ]        │ ← único botón sólido (size 3)
│                                      │
│  ¿No sabes a quién? Empieza por      │ ← rx.text size 2, TEXT_MUTED
│  alguien que ya recomendó un negocio │
│  de tu ciudad.                       │
└──────────────────────────────────────┘
```

Construcción: `app_shell(page_header("Creadores", <subtítulo>), page_body(empty_state("users",
<título>, <cuerpo>, action=rx.button("Revisar un creador", size="3", on_click=<abrir cajón>))))`.

| Pieza | Texto final |
|---|---|
| Título de pestaña | `Qualify · Creadores` |
| h1 | Creadores |
| Subtítulo | Mira cuánta gente ve de verdad a un creador antes de darle producto o pagarle |
| Vacío, título | Todavía no revisaste a ningún creador |
| Vacío, cuerpo | Escribe su usuario de Instagram y en unos segundos ves cuántas personas ven sus reels, qué le funciona y con qué marcas trabajó. |
| Botón | Revisar un creador |
| Ayuda debajo | ¿No sabes a quién? Empieza por alguien que ya recomendó un negocio de tu ciudad. |

El verbo del módulo es **«Revisar»** (no «Analizar», que suena a herramienta): «Revisar un
creador» → «Revisando a @usuario…» → «Listo: ya puedes ver cómo le va a @usuario» (§7.3 del sistema
de diseño, verbo → resultado).

## 2. Entrega 1 — Revisar un creador (detalle para construir)

### 2.1 La lista «Tus creadores»

Ciclo de vida de lista del sistema de diseño §6.1: `load_error` → `callout("error")` en lugar de la
lista; `is_loading` → `skeleton_card()` × 3 (nunca spinner); vacío → §1.2; si no, la lista.

```
CELULAR (360 px)                          ESCRITORIO (≥ 1024 px)
┌──────────────────────────────────────┐  ┌───────────────────────────────────────────────────────┐
│ Creadores       [Revisar un creador] │  │ Creadores               [Comparar] [Revisar un creador]│
│ Mira cuánta gente ve de verdad…      │  │ Mira cuánta gente ve de verdad a un creador antes…     │
│ [ Comparar creadores ]  (outline)    │  │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │
│ ┌──────────────────────────────────┐ │  │ │(o) María V.  │ │(o) Ruta Cúc. │ │(o) Tachira S.│     │
│ │ (o) María Valentina              │ │  │ │@comeconmaria │ │@rutacucuta   │ │@tachirasabe  │     │
│ │     @comeconmaria                │ │  │ │12,4 mil seg. │ │48,1 mil seg. │ │6.900 seg.    │     │
│ │ 12,4 mil seguidores              │ │  │ │8.300 vistas  │ │9.100 vistas  │ │7.800 vistas  │     │
│ │ 8.300 vistas típicas por reel    │ │  │ │típicas       │ │típicas       │ │típicas       │     │
│ │ Datos de hace 3 días             │ │  │ │hace 3 días   │ │hace 21 días ⚠│ │hoy           │     │
│ └──────────────────────────────────┘ │  │ └──────────────┘ └──────────────┘ └──────────────┘     │
│ ┌──────────────────────────────────┐ │  └───────────────────────────────────────────────────────┘
│ │ (o) Ruta Cucuteña  @rutacucuta   │ │
│ │ 48,1 mil seguidores              │ │
│ │ 9.100 vistas típicas por reel    │ │
│ │ [Datos viejos] Hace 21 días      │ │  ← tone_badge("Datos viejos","warn") + texto
│ └──────────────────────────────────┘ │
│ ┌──────────────────────────────────┐ │
│ │ (spinner) @tachirasabe           │ │  ← fila «trabajando»: loading_spinner("sm") + frase
│ │ Revisando sus reels…             │ │
│ └──────────────────────────────────┘ │
└──────────────────────────────────────┘
```

- **Cada tarjeta** es un enlace a la ficha: `rx.link(card(..., interactive=True), href=/creadores/<id>)`
  (como `results_page._card_link`). Dentro: `media_thumb(foto, size="48px", round=True,
  icon="user")`, nombre (`rx.text weight=bold`, h3 semántico), `mono("@usuario")`, dos cifras
  (seguidores y **vistas típicas por reel**, la cifra que más dice) y la línea de frescura.
- **Orden:** el último revisado primero. Con más de 8 creadores aparece un buscador
  (`rx.input` con `rx.input.slot(rx.icon("search"))`, etiqueta visible «Buscar por nombre o
  usuario»). Nada de filtros en la entrega 1.
- **Frescura** (misma regla en lista, ficha y comparación):

| Edad de los datos | Texto | Marca |
|---|---|---|
| hoy | Datos de hoy | — |
| 1 día | Datos de ayer | — |
| 2–13 días | Datos de hace N días | — |
| ≥ 14 días | Datos de hace N días | `tone_badge("Datos viejos", "warn", icon="clock")` |

  El umbral de 14 días es una propuesta; la ventana real la fija `docs/diseno-modulo-creadores.md`.
- **Fila «trabajando»** (un creador que se está revisando): `card` sin enlace con
  `loading_spinner("sm")` + «Revisando sus reels…». Al terminar se convierte en la tarjeta normal.
- **Acción principal:** «Revisar un creador» (sólido) en el encabezado. «Comparar creadores»
  (`outline`) aparece solo con 2 o más creadores.

**Modo comparar (elegir 2–4).** Tocar «Comparar creadores» cambia la lista a casillas: cada tarjeta
pasa a `choice_card(role="checkbox", selected=…)` (nunca un enlace con una casilla adentro: dos
controles anidados). Un pie fijo (la anatomía del pie de `step_foot`, §4.5) dice cuántos lleva:

```
┌──────────────────────────────────────┐
│ ‹ Creadores    Elige de 2 a 4        │ ← cabeza: salir del modo vuelve a la lista
│ [✓] María Valentina  @comeconmaria   │
│ [ ] Ruta Cucuteña    @rutacucuta     │
│ [✓] Táchira Sabe     @tachirasabe    │
├──────────────────────────────────────┤
│ [ Cancelar ]   [ Comparar 2 creadores ]│ ← sólido; deshabilitado con 0–1 y motivo visible
│ Elige al menos uno más               │   «Elige al menos uno más» / «Puedes comparar hasta 4»
└──────────────────────────────────────┘
```

| Pieza | Texto final |
|---|---|
| Botón que entra al modo | Comparar creadores |
| Cabeza del modo | Elige de 2 a 4 |
| Botón del pie (n = elegidos) | Comparar {n} creadores |
| Motivo con 0–1 | Elige al menos {2−n} más |
| Al intentar un quinto | Puedes comparar hasta 4. Quita uno para elegir otro. |

### 2.2 Revisar un creador (el cajón)

Un solo paso, así que **no** lleva marco de pasos (§4.5: un formulario de un paso no lo lleva). Es un
`drawer(title="Revisar un creador", icon="user-search", footer=…)` con `?flujo=agregar` (N5).

```
┌──────────────────────────────────────┐
│ Revisar un creador               [✕] │ ← drawer title; ✕ con aria-label «Cerrar»
│ Te mostramos cuánta gente ve sus     │ ← description
│ reels de verdad.                     │
├──────────────────────────────────────┤
│ Usuario de Instagram                 │ ← etiqueta visible (size 2, medium)
│ ┌──────────────────────────────────┐ │
│ │ @ │ ej.: comeconmaria            │ │ ← rx.input + slot «@»; placeholder = ejemplo
│ └──────────────────────────────────┘ │
│ Está arriba en su perfil. También    │ ← ayuda (size 1, TEXT_MUTED)
│ puedes pegar el enlace de su perfil. │
├──────────────────────────────────────┤
│ [ Cancelar ]   [ Ver cómo le va ]    │ ← pie: soft + sólido (loading=Var)
└──────────────────────────────────────┘
```

- **Acepta lo que el dueño pegue:** `@usuario`, `usuario`, `instagram.com/usuario`, el enlace con
  `?igsh=…` de «Compartir perfil». Se limpia antes de buscar; nunca se le pide «quitar la arroba».
  Campo con `autocapitalize="none"`, `autocorrect="off"`, `inputmode="text"`, `enterkeyhint="go"`.
- **Botón deshabilitado** mientras el campo está vacío, con la ayuda visible (§5.5).

**Esperando** (trabajo en curso que bloquea el cajón → `progress_panel`, §5.4; nunca skeleton):

```
│ Revisando a @comeconmaria                │ ← progress_panel title
│ ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░                     │
│ Leyendo sus últimos 48 reels             │ ← etapa en curso
│ Tarda unos segundos. Si cierras esto,    │ ← detail
│ sigue en tu lista y te avisamos.         │
```

Etapas (`steps`): «Buscando su perfil» · «Leyendo sus últimos 48 reels» · «Sacando sus números».
Si el dueño cierra el cajón, la revisión sigue y aparece como fila «Revisando sus reels…» en la
lista (§2.1). Al terminar con el cajón abierto, el cajón **se cierra y abre la ficha** (N3: el
resultado es la ficha, no un aviso flotante).

**Cuando algo sale mal** — `callout` **encima del botón**, el campo conserva lo escrito, el botón
vuelve a estar disponible (§5.6). Ningún mensaje dice «créditos», «API», «scraping» ni un código.

| Situación | Tono | Texto final | Acción |
|---|---|---|---|
| No existe | `error` | No encontramos a @{usuario} en Instagram. Revisa que esté bien escrito o pega el enlace de su perfil. | El mismo botón |
| Cuenta privada | `warn` | La cuenta de @{usuario} es privada: solo sus seguidores ven sus reels, así que no podemos contarlos. Prueba con otra cuenta o pídele sus números directamente. | «Revisar otra cuenta» (limpia el campo) |
| Sin reels | `warn` | @{usuario} todavía no tiene reels, así que no hay vistas que contar. | «Revisar otra cuenta» |
| Pocos reels (1–5) | — (sí se revisa) | En la ficha: «Solo encontramos {n} reels. Con tan pocos, los números todavía dicen poco.» | — |
| Ya está en tu lista | `info` | Ya revisaste a @{usuario} hace {N} días. | «Ver sus resultados» + «Actualizar» |
| Es tu propia cuenta | `info` | Esa es la cuenta de tu negocio. Tus resultados están en Resultados. | «Ir a Resultados» |
| Instagram no respondió / tardó demasiado | `error` | No pudimos leer Instagram en este momento. Inténtalo de nuevo en unos minutos. | «Intentar de nuevo» |
| Se acabó lo del mes (ver ⚑ Decisión 4) | `warn` | Este mes ya revisaste {n} creadores, lo que incluye tu plan. Podrás revisar más el {1 de diciembre}. | «Ver los que ya revisaste» |

Al reintentar desde una fila de la lista que falló: la fila muestra el mismo texto en
`callout` compacto con «Intentar de nuevo» dentro (estado degradado accionable, §6.3).

### 2.3 La ficha del creador — `/creadores/[creator_id]`

Lo más importante arriba y en palabras; el detalle, abajo. Una columna en el celular; en escritorio,
las cifras en una fila de 4 o 5 y las listas en dos columnas.

```
┌──────────────────────────────────────┐ 360 px
│ ‹ Creadores                          │ ← N7: vuelve a la lista, con el mismo filtro
│ (o) María Valentina                  │ ← h1 = nombre visible (o @usuario si no hay)
│     @comeconmaria · Ver en Instagram ↗│ ← mono + enlace externo (N9)
│ Datos de hace 3 días     [Actualizar]│ ← soft, loading=Var
├──────────────────────────────────────┤
│ ┌───────────────┐ ┌───────────────┐  │ ← stat_card × 4 (2×2), hint visible
│ │Vistas típicas │ │Interacción    │  │
│ │por reel       │ │               │  │
│ │ 8.300         │ │ 4,1 %         │  │
│ │lo que suele   │ │de cada 100 que│  │
│ │ver un reel    │ │lo ven, 4 dan  │  │
│ │suyo      (?)  │ │me gusta o co… │  │
│ └───────────────┘ └───────────────┘  │
│ ┌───────────────┐ ┌───────────────┐  │
│ │Seguidores     │ │Vistas frente a│  │
│ │ 12,4 mil      │ │seguidores     │  │
│ │               │ │ 67 %          │  │
│ └───────────────┘ └───────────────┘  │
│ Publica unos 3 reels por semana. (?) │ ← frase, no tarjeta
├──────────────────────────────────────┤
│ Sus reels con más vistas             │ ← h2
│ [mini] 45 mil vistas · hace 12 días  │ ← media_thumb + cifra + fecha
│        «Probé el shawarma más…»  ↗   │   «Ver en Instagram ↗»
│ [mini] 31 mil vistas · hace 5 días ↗ │
│ [mini] 22 mil vistas · hace 1 mes  ↗ │
├──────────────────────────────────────┤
│ Reels que se salieron de lo normal   │ ← h2
│ 5 de sus últimos 48 reels tuvieron   │
│ más del doble de sus vistas típicas. │
│ [mini] 5 veces lo normal · 45 mil  ↗ │
│ [mini] 4 veces lo normal · 31 mil  ↗ │
│ Ver los 5                            │ ← despliega (rx.accordion), no navega
├──────────────────────────────────────┤
│ Lo que mejor le funciona             │ ← h2
│ Duración: sus reels de 15 a 30 s     │
│ tienen más vistas (9.800 típicas,    │
│ frente a 6.100 los de más de 60 s).  │
│ Audios que más usa:                  │
│ [Audio original · 31] [Tusa… · 4]    │ ← tag() con conteo
├──────────────────────────────────────┤
│ Colaboraciones con marcas            │ ← h2
│ 6 de sus últimos 48 reels son con    │
│ marcas. Esos tienen 5.200 vistas     │
│ típicas, menos que sus 8.300.        │
│ @burgerhouse · @heladeriaxyz · …     │ ← tag() por marca
├──────────────────────────────────────┤
│ Contamos sus últimos 48 reels, del   │ ← pie de confianza (size 1, muted)
│ 2 de agosto al 1 de noviembre.       │
├──────────────────────────────────────┤
│ [   Compararlo con otro creador   ]  │ ← el ÚNICO sólido (N3: el siguiente paso)
│ Quitar de tu lista                   │ ← ghost + alert_dialog (§6.2)
└──────────────────────────────────────┘
```

**Las cifras, una por una.** Cada `stat_card` lleva su `hint` **siempre visible** (el dueño no pasa
el mouse por encima: en el celular un `rx.tooltip` no existe). La explicación más larga
(«¿Cómo lo contamos?») va en un `rx.popover` abierto por un `rx.icon_button("circle-help",
variant="ghost", aria_label="Qué quiere decir {nombre}")` — se abre con un toque, no al pasar el
mouse. Los nombres son **los mismos** en la ficha, la lista y la comparación (N1, aplicado a cifras).

| Nombre en pantalla | Ejemplo | Ayuda visible (`hint`, una frase) | «¿Cómo lo contamos?» (popover) | Qué es por dentro |
|---|---|---|---|---|
| **Seguidores** | 12,4 mil | — (no necesita) | Cuántas personas siguen su cuenta hoy. Es fácil de inflar: mira también las vistas típicas. | `follower_count` |
| **Vistas típicas por reel** | 8.300 | Lo que suele ver un reel suyo | Ordenamos sus reels por vistas y tomamos el del medio. Así un reel que se volvió muy famoso no infla el número. | mediana de vistas de la ventana |
| **Vistas frente a seguidores** | 67 % | Más de 100 % quiere decir que llega a gente que no lo sigue | Dividimos sus vistas típicas entre sus seguidores. 67 % es que un reel típico lo ven tantas personas como 67 de cada 100 seguidores. | mediana ÷ seguidores |
| **Interacción** | 4,1 % | De cada 100 que lo ven, 4 dan me gusta o comentan | Sumamos los me gusta y comentarios de cada reel y los dividimos entre sus vistas. Mostramos el valor típico. | mediana de (me gusta + comentarios) ÷ vistas — **confirmar fórmula** con `diseno-modulo-creadores.md` |
| **Reels por semana** | unos 3 | — (se dice en frase: «Publica unos 3 reels por semana») | Contamos cuántos reels publicó en las últimas semanas y sacamos el promedio por semana. | reels de la ventana ÷ semanas |
| **Se salió de lo normal** | 5 veces lo normal | Tuvo más del doble de sus vistas típicas | Un reel se sale de lo normal cuando tiene por lo menos el doble de las vistas que suele tener. | vistas ≥ 2 × mediana; «N veces» = vistas ÷ mediana, redondeado |
| **Duración que mejor le funciona** | de 15 a 30 s | — | Agrupamos sus reels por duración y comparamos las vistas típicas de cada grupo. | grupos: < 15 s · 15–30 s · 30–60 s · > 60 s; se muestra solo si el grupo ganador tiene ≥ 5 reels |
| **Audios que más usa** | Audio original · 31 | — | Los audios que más se repiten en sus últimos reels. | conteo por audio |
| **Colaboraciones con marcas** | 6 de 48 | — | Reels que Instagram marca como «colaboración pagada» o que publicó junto con otra cuenta. | `is_paid_partnership` + coautores |

**Formato de números** (es-CO/VE/UY): punto de miles y coma decimal. Hasta 9.999, completo
(«8.300»); de 10.000 a 999.999, «12,4 mil»; desde un millón, «1,2 millones». Porcentajes con una
cifra decimal («4,1 %», espacio antes de %). Duraciones en segundos «15 s». Fechas relativas
(«hace 12 días», «hace 1 mes») y la fecha exacta en el pie de confianza.

**«Sin dato», nunca cero.** Si Instagram no da una cifra (seguidores ocultos, un reel sin vistas
públicas), la tarjeta muestra **«Sin dato»** en `TEXT_MUTED`, sin tono, con el `hint`: «Instagram no
lo muestra para esta cuenta». Un cero solo aparece cuando de verdad es cero (p. ej., «0 de 48 reels
con marcas»). Una lista sin elementos dice la frase que corresponde:
- Ninguno salido de lo normal: «Ninguno de sus últimos 48 reels se salió de lo normal: sus vistas son parejas.»
- Sin colaboraciones: «En sus últimos 48 reels no encontramos colaboraciones con marcas.»
- Duración sin ganador claro: «Sus reels largos y cortos tienen vistas parecidas.»

**Actualizar.** El botón `soft` «Actualizar» (`loading=Var`) vuelve a leer el perfil; mientras
trabaja dice «Actualizando…» con `loading_spinner("sm")` y **la ficha vieja sigue a la vista** (la
lista sigue siendo verdad, §6.1). Al terminar: «Datos de hoy». Con datos de 14 días o más, arriba
de las cifras va un `callout` `warn` con el botón dentro (§6.3):

> Estos números son de hace {N} días. Actualízalos antes de decidir. **[Actualizar]**

**Quitar.** `rx.alert_dialog`: título «Quitar de tu lista», cuerpo «**@{usuario}** deja de aparecer
en tu lista. Puedes volver a revisarlo cuando quieras.», botones «Cancelar» / «Quitar». Resultado:
vuelve a la lista con «Quitaste a @{usuario} de tu lista.» arriba (N3: no solo un toast).

**Fila de textos de la ficha**

| Pieza | Texto final |
|---|---|
| Volver | ‹ Creadores |
| Enlace externo | Ver en Instagram ↗ |
| Frescura | Datos de hoy / Datos de ayer / Datos de hace {N} días |
| Botón | Actualizar → «Actualizando…» → «Datos de hoy» |
| Sección 1 (h2) | Sus reels con más vistas |
| Sección 2 (h2) | Reels que se salieron de lo normal |
| Frase de sección 2 | {n} de sus últimos {total} reels tuvieron más del doble de sus vistas típicas. |
| Sección 3 (h2) | Lo que mejor le funciona |
| Sección 4 (h2) | Colaboraciones con marcas |
| Frase de sección 4 | {n} de sus últimos {total} reels son con marcas. Esos tienen {x} vistas típicas, {más/menos} que sus {y}. |
| Pie de confianza | Contamos sus últimos {total} reels, del {fecha} al {fecha}. |
| Botón principal | Compararlo con otro creador |
| Quitar | Quitar de tu lista |

«Compararlo con otro creador» abre la lista en modo comparar **con este creador ya marcado** (N4:
quien sale a buscar algo vuelve con eso elegido). Con un solo creador en la lista, el botón principal
es «Revisar otro creador» (abre el cajón).

## 3. Comparar creadores — `/creadores/comparar?ids=…`

**Reglas que no se negocian** (fundador, 2026-11-04): 2 a 4 creadores, **la misma ventana de tiempo
para todos**, el mejor de cada fila marcado, **nunca un puntaje sumado**, «Sin dato» nunca es cero,
aviso de datos viejos, un gráfico de vistas por reel de todos juntos, y en el celular 2 por pantalla
deslizando.

### 3.1 Escritorio

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ‹ Creadores                                                                             │
│ Comparar creadores                                                         (h1)         │
│ Con los reels de los últimos 90 días de cada uno. Marcamos el mejor de cada fila;       │
│ tú decides qué pesa más para tu negocio.                                                │
│ ┌─[!] Los datos de @rutacucuta son de hace 21 días y los demás, de esta semana.───────┐ │
│ │     Actualízalos para comparar parejo.                    [Actualizar @rutacucuta]  │ │ ← callout warn + botón
│ └────────────────────────────────────────────────────────────────────────────────────┘ │
│ ┌──────────────────────┬───────────────────┬───────────────────┬───────────────────┐    │
│ │                      │ (o) María V.      │ (o) Ruta Cucuteña │ (o) Táchira Sabe  │    │ ← cabecera: foto + nombre
│ │                      │ @comeconmaria  ✕  │ @rutacucuta    ✕  │ @tachirasabe   ✕  │    │   ✕ = quitar de la comparación
│ ├──────────────────────┼───────────────────┼───────────────────┼───────────────────┤    │
│ │ Vistas típicas       │ 8.300             │ 9.100  [Mejor]    │ 7.800             │    │
│ │ por reel         (?) │                   │                   │                   │    │
│ │ Vistas frente a      │ 67 %              │ 19 %              │ 113 %  [Mejor]    │    │
│ │ seguidores       (?) │                   │                   │                   │    │
│ │ Interacción      (?) │ 4,1 %  [Mejor]    │ 1,2 %             │ 3,8 %             │    │
│ │ Reels que se salie-  │ 5 de 30  [Mejor]  │ 1 de 12           │ 3 de 26           │    │
│ │ ron de lo normal (?) │                   │                   │                   │    │
│ │ Seguidores           │ 12,4 mil          │ 48,1 mil          │ 6.900             │    │ ← sin «Mejor» (ver nota)
│ │ Reels por semana     │ unos 2            │ 1                 │ unos 2            │    │ ← sin «Mejor»
│ │ Duración que mejor   │ 15 a 30 s         │ Sin dato          │ menos de 15 s     │    │ ← categórica: sin «Mejor»
│ │ le funciona          │                   │                   │                   │    │
│ │ Colaboraciones con   │ 4 de 30           │ 7 de 12           │ 0 de 26           │    │ ← informativa
│ │ marcas               │                   │                   │                   │    │
│ │ Datos de             │ hace 3 días       │ hace 21 días      │ hoy               │    │
│ │                      │                   │ [Datos viejos]    │                   │    │
│ └──────────────────────┴───────────────────┴───────────────────┴───────────────────┘    │
│                                                                                         │
│ Vistas de cada reel                                                         (h2)        │
│ [gráfico, §3.3]                                                                         │
│                                                                                         │
│ [ Agregar otro a la comparación ]  (outline, solo con < 4)                              │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

Construcción: `rx.table.root(variant="surface")` dentro de `rx.box(overflow_x="auto")` (§5.7);
números a la derecha con `q-nums`; la primera columna es `rx.table.row_header_cell` (lectores de
pantalla anuncian «Interacción, María Valentina, 4,1 %»). El mejor de la fila: la cifra en
`weight="bold"` **y** `tone_badge("Mejor", "ok", icon="trophy")` al lado — **nunca solo color**
(P1 del sistema de diseño). Empate: `Mejor` en todos los empatados. Si algún creador tiene «Sin
dato» en esa fila, el «Mejor» se calcula entre los que sí tienen dato.

**Qué filas llevan «Mejor»** (propuesta; ⚑ Decisión 6): solo las que dicen si el reel **rinde**:
vistas típicas, vistas frente a seguidores, interacción y reels que se salieron de lo normal (como
proporción, no como cantidad: «5 de 30» gana a «6 de 48»). **No** llevan «Mejor»: seguidores (más
seguidores suele ser más caro y no siempre más vistas), reels por semana, duración y colaboraciones
(son información, no mérito). El orden de filas pone primero las que llevan «Mejor».

**No hay fila de total, ni puntaje, ni «ganador general».** La frase de arriba lo dice en palabras
del dueño: «tú decides qué pesa más para tu negocio».

**La misma ventana.** Arriba siempre se dice cuál: «Con los reels de los últimos {90} días de cada
uno». Si en esa ventana un creador tiene menos de 6 reels, su columna lleva debajo del nombre, en
`size=1 TEXT_MUTED`: «Solo {n} reels en este tiempo». La ventana exacta la decide
`docs/diseno-modulo-creadores.md`; aquí solo se exige que se diga.

**Datos viejos.** Si algún creador tiene datos de 14 días o más, **o** si entre el más nuevo y el
más viejo hay más de 7 días, va el `callout` `warn` con el botón dentro. Con varios: «Los datos de
@a y @b son de hace más de dos semanas. Actualízalos para comparar parejo. [Actualizar los 2]».
Mientras actualiza, la tabla sigue a la vista y la columna que se actualiza muestra
`loading_spinner("sm")` + «Actualizando…» en la cabecera.

**Quitar uno** (✕ en la cabecera, `aria_label="Quitar a @usuario de la comparación"`): cambia la
URL (N5). Con 2, el ✕ no aparece (no se puede comparar uno solo).

### 3.2 Celular — 2 por pantalla, deslizando

A 360 px no caben 4 columnas ni la columna de nombres de filas. Cada creador es una **columna
tarjeta** con **todas** sus filas, y cada cifra lleva su nombre encima (así cada valor se entiende
solo, también con lector de pantalla). Se ven **2 columnas a la vez**; se desliza de a pares.

```
┌──────────────────────────────────────┐ 360 px
│ ‹ Creadores                          │
│ Comparar creadores                   │
│ Últimos 90 días de cada uno. El mejor│
│ de cada fila va marcado.             │
│ ┌[!] Los datos de @rutacucuta son ──┐│
│ │ de hace 21 días. [Actualizar]      ││
│ └────────────────────────────────────┘│
│ ┌────────────────┐┌────────────────┐ │
│ │(o) María V.    ││(o) Ruta Cuc.   │ │ ← cabecera fija de cada columna
│ │@comeconmaria   ││@rutacucuta     │ │
│ ├────────────────┤├────────────────┤ │
│ │Vistas típicas  ││Vistas típicas  │ │ ← nombre repetido en cada celda
│ │8.300           ││9.100 [Mejor]   │ │
│ │Vistas frente a ││Vistas frente a │ │
│ │seguidores      ││seguidores      │ │
│ │67 %            ││19 %            │ │
│ │Interacción     ││Interacción     │ │
│ │4,1 % [Mejor]   ││1,2 %           │ │
│ │…               ││…               │ │
│ └────────────────┘└────────────────┘ │
│  [‹ Anteriores]   1–2 de 3  [Siguientes ›]│ ← botones visibles + contador en texto
│                                      │
│ Vistas de cada reel           (h2)   │
│ [gráfico, §3.3]                      │
└──────────────────────────────────────┘
```

- **Reutilizar `Qualify/media_carousel.py`** (flechas, puntos y contador «1 / 2»): cada «diapositiva»
  es un **par** de columnas. Hoy ese carrusel **no tiene deslizar con el dedo** («Swiping on a phone
  is not wired», su docstring) y avanza solo cada 10 s: para comparar hay que **apagar el avance
  automático** y **agregar el deslizar**. Es extender un componente que existe, no uno nuevo; aun
  así, ⚑ Decisión 5 lo confirma. Deslizar **nunca** es la única forma: los botones «‹ Anteriores» /
  «Siguientes ›» (texto, ≥ 44 px) y el contador en texto («1–2 de 3») quedan siempre visibles.
- Con 3 creadores, la segunda pantalla muestra el 3.º **junto al 1.º** (el que el dueño eligió
  primero), así nunca queda una columna sola.
- **«Mejor» es de toda la comparación**, no de las 2 columnas visibles: la etiqueta dice «Mejor»
  igual; el lector de pantalla oye «Mejor de los 3».
- Las filas de cada columna tienen **la misma altura** que en la columna vecina (misma estructura y
  el valor en una línea), para que el ojo compare en horizontal.
- No hay desplazamiento horizontal de la página (N12): solo el carrusel se mueve, dentro de su caja.

### 3.3 El gráfico «Vistas de cada reel»

Para ver de un vistazo **quién es parejo y quién vive de un golpe de suerte**. Propuesta: **un
gráfico pequeño por creador, uno debajo del otro, con la misma escala** (no cuatro líneas de colores
encima de una sola gráfica):

```
Vistas de cada reel                          (misma escala para todos)
@comeconmaria   ▁▂▁▃▂▁█▂▁▂▃▂▁▂▅▁▂▁▂▁  ── típicas 8.300
@rutacucuta     ▁▁▂▁▁▁▁▂▁▁▁▁                 ── típicas 9.100
@tachirasabe    ▂▃▂▂▃▂▆▂▃▂▂▃▂▂▃▂▂▃▂▂▃▂▂▃  ── típicas 7.800
                ago            sep            oct           nov
```

- Una barra por reel, en orden de fecha; una línea punteada marca las **vistas típicas** de cada
  uno. Los reels que se salieron de lo normal (≥ ×2) en el tono del acento lleno; el resto, más
  tenue. **Un solo color** (el acento): no hace falta una paleta de colores por creador, y cada
  gráfico lleva el @usuario escrito (nunca se identifica a alguien solo por el color).
- Accesible: cada gráfico tiene `aria-label` con la frase («@comeconmaria: 30 reels; vistas típicas
  8.300; 5 salieron de lo normal; el más visto, 45 mil») y, debajo, «Ver como lista» que despliega
  la tabla de reels (fecha, vistas, «Ver en Instagram ↗»).
- En el celular, cada gráfico ocupa el ancho completo y ~80 px de alto; los 4 caben sin desplazarse
  demasiado.

**⚑ Decisión 3 — el gráfico es un patrón nuevo.** En la app no hay ningún gráfico (no se usa
`rx.recharts` en `Qualify/`). Según el sistema de diseño §9.2, un patrón nuevo se documenta primero
en `docs/design-system.md` y lo aprueba el fundador; `reflex-ui-engineer` **no lo construye antes**.
Opciones:

| Opción | Qué es | A favor | En contra |
|---|---|---|---|
| **A (recomendada)** — gráficos pequeños, un color | `rx.recharts.bar_chart` por creador, misma escala, color del acento | Sin colores nuevos; se lee en el celular; nada depende del color | Ocupa más alto que uno solo |
| B — un gráfico con una línea por creador | `rx.recharts.line_chart` con 2–4 series | Compacto en escritorio | Necesita una paleta de 4 colores que no existe (decisión de sistema); ilegible a 360 px |
| C — sin gráfico en la entrega 1 | Solo la tabla y «Ver como lista» | Sale antes | El fundador pidió el gráfico |

## 4. Entregas 3 a 6 — de «quiero que me recomienden» a «quedamos así» (flujo general)

Un hilo para el dueño: **campaña → candidatos → invitación → propuesta → acuerdo.** Cada candidato
tiene **un estado** y **una sola cosa que hacer ahora**, y eso es lo que se ve en su tarjeta.

### 4.1 Los estados de un candidato

| Estado (texto en `signal_pill`) | Tono | Qué ve el dueño como siguiente paso (botón de la tarjeta) |
|---|---|---|
| **Sugerido** | `neutral` | «Lo quiero» / «No me sirve» |
| **Elegido** | `accent` | «Invitarlo» |
| **Invitación copiada** | `neutral` | «¿Ya le escribiste?» → «Sí, ya le escribí» / «Todavía no» |
| **Invitado** | `neutral` | «Esperando su respuesta» (sin botón; a los 3 días: «Escribirle de nuevo») |
| **Te respondió** | `warn` (alguien espera respuesta) | «Ver su respuesta» → Por responder › Mensajes |
| **Negociando** | `accent` | «Anotar su propuesta» / «Ver lo que van hablando» |
| **Acordado** | `ok` | «Copiar lo que acordaron» |
| **No se dio** | `neutral` | — (se puede reabrir) |
| **Descartado** | `neutral` | «Volver a considerarlo» |

«Te respondió» es el único `warn`: es el único momento en que **alguien espera al dueño** (misma
regla que los contadores del menú, `NAV_COUNTERS`). Ese aviso **no suma un contador nuevo** en
«Creadores»: el mensaje ya cuenta en «Por responder» y contarlo dos veces confunde.

### 4.2 Encajar — «Nueva campaña» (asistente, marco de pasos §4.5)

`/creadores/campanas/nueva?paso=N`, con «‹ Campañas», «Paso N de 5», «Atrás» sin perder datos y
«Seguir después» (N6, N6b). Valores ya rellenados con lo que Qualify sabe.

| Paso | Título (h1 del paso) | Qué decide | Ya rellenado con |
|---|---|---|---|
| 1 | ¿Qué quieres lograr? | `choice_card` (radio): «Que vengan a probar» · «Que más gente de tu ciudad te conozca» · «Vender un producto en especial» · «Lanzar algo nuevo» | — |
| 2 | ¿Qué quieres que muestren? | `choice_card` de tu catálogo (foto + nombre) o «Todo mi negocio» | el producto más reciente; sin productos → «Agregar producto» y vuelve con él elegido (N4) |
| 3 | ¿Dónde y para cuándo? | Ciudad (`rx.select`) + «Antes del…» (fecha) | ciudad del negocio; fecha = dentro de 2 semanas |
| 4 | ¿Cuánto quieres invertir? | Tope (monto en la moneda del negocio) + cómo: «Producto a cambio (canje)» · «Pago» · «Una experiencia en tu local» (`choice_card` checkbox) | la moneda del negocio (USD en Venezuela, decisión 10) |
| 5 | Revisa y busca | La frase: «Buscamos creadores en **Cúcuta** que muestren tu **Combo Vecino** antes del **sábado 15**. Tienes hasta **300.000 pesos**, en producto o en pago.» | — |

Botón final: **«Buscar creadores»** → `progress_panel` «Buscando creadores que encajen…» → la
campaña con sus sugeridos. Nada se envía a nadie en este paso (N13).

### 4.3 La campaña y sus candidatos — `/creadores/campanas/[id]`

```
┌──────────────────────────────────────┐ 360 px
│ ‹ Campañas                           │
│ Combo Vecino en Cúcuta               │ ← h1 = nombre de la campaña
│ Antes del sáb 15 · hasta 300.000 COP │
│ Llevas 120.000 de 300.000            │ ← entrega 5
│ [Por decidir 8|Elegidos 3|Hablando 2|Acordados 1] │ ← 4 pestañas (N12); select en el celular
├──────────────────────────────────────┤
│ ┌──────────────────────────────────┐ │
│ │ (o) María V.  @comeconmaria      │ │
│ │ (·) Sugerido                     │ │ ← signal_pill
│ │ 8.300 vistas típicas · 4,1 %     │ │
│ │ Por qué encaja:                  │ │
│ │ [Comprobado] Hizo un reel en un  │ │ ← tone_badge + frase + reel citado
│ │ local de comida de Cúcuta que    │ │
│ │ tuvo 3 veces sus vistas típicas. │ │
│ │ Ver ese reel ↗                   │ │
│ │ [Inferido] Su público parece ser │ │
│ │ de Cúcuta: etiqueta lugares de   │ │
│ │ allí en 20 de 30 reels.          │ │
│ │ [No sabemos] Cuánto cobra.       │ │
│ │ [ No me sirve ]   [ Lo quiero ]  │ │ ← soft + sólido, ≥ 44 px, al alcance del pulgar
│ └──────────────────────────────────┘ │
│ Ver 4 descartados                    │
└──────────────────────────────────────┘
```

- **Orden por encaje, sin número de encaje.** No se muestra «87 % de encaje» ni un puntaje: el orden
  ya lo dice, y las razones explican por qué. (Coherente con «nunca un puntaje sumado» de Comparar.)
- **Cada razón lleva su etiqueta de certeza en texto**, con `tone_badge`: **«Comprobado»** (`ok`,
  sale de un dato o un reel que se puede abrir), **«Inferido»** (`info`, lo deducimos; el `hint` dice
  de qué), **«No sabemos»** (`neutral`; la app no inventa). Máximo 3 razones visibles; «Ver más
  razones» despliega el resto. Una razón «Comprobado» **siempre** enlaza el reel que la prueba.
- **«No me sirve»** mueve la tarjeta a «Descartados» y deja en su lugar, por unos segundos, «Lo
  quitaste de esta campaña. **Deshacer**» (en la página, no un toast suelto). Pedir motivo es
  opcional: tres `tag` tocables «Muy caro» · «No es mi público» · «Otro».
- Desde cada tarjeta, el nombre abre la ficha del creador (§2.3) **con «‹ Combo Vecino en Cúcuta»**
  como volver (N7).

### 4.4 Invitar — el salto al celular (la parte delicada)

Instagram no deja que un negocio le escriba primero a alguien desde otra aplicación. Así que **el
dueño envía la invitación desde su propio Instagram**, y Qualify le deja todo listo para que le tome
20 segundos. Es un `drawer` con la cabeza del marco de pasos («Paso N de 3»).

```
① Revisa el mensaje                 ② Envíalo desde tu Instagram        ③ ¿Ya se lo enviaste?
┌────────────────────────────┐       ┌────────────────────────────┐      ┌────────────────────────────┐
│ ‹ Combo Vecino   Paso 1 de 3│       │ ‹ Combo Vecino   Paso 2 de 3│      │ ‹ Combo Vecino   Paso 3 de 3│
│ Revisa el mensaje           │       │ Envíalo desde tu Instagram  │      │ ¿Ya se lo enviaste a María? │
│ ┌────────────────────────┐ │       │ Instagram solo deja enviar  │      │                            │
│ │ ¡Hola, María! Somos    │ │       │ este primer mensaje desde   │      │ Si se lo enviaste, la      │
│ │ Bianki, en el Korner.  │ │ ←chat_│ tu propia aplicación.       │      │ marcamos como invitada y   │
│ │ Vimos tu reel en …     │ │ bubble│                            │      │ te avisamos cuando conteste│
│ │ ¿Te gustaría probar el │ │  out  │ 1. [ Copiar mensaje ]  ✓    │      │                            │
│ │ Combo Vecino y …?      │ │       │    Copiado                  │      │                            │
│ └────────────────────────┘ │       │ 2. [ Abrir su chat en       │      │                            │
│ [Editar]  [Otra versión]   │       │      Instagram ↗ ]          │      │                            │
│ Escrito con tu forma de    │       │ Pega el mensaje y envíalo.  │      │                            │
│ hablar.                    │       │ Luego vuelve aquí.          │      │                            │
├────────────────────────────┤       ├────────────────────────────┤      ├────────────────────────────┤
│ [Atrás]  [Usar este mensaje]│      │ [Atrás]   [Siguiente]       │      │[Todavía no] [Sí, ya lo envié]│
└────────────────────────────┘       └────────────────────────────┘      └────────────────────────────┘
```

- **Paso 1:** el borrador en `chat_bubble(direction="out")`, escrito con la voz de la marca. «Editar»
  lo vuelve un `rx.text_area`; «Otra versión» pide otra. Nada se envía (N13).
- **Paso 2, en orden y numerado:** «Copiar mensaje» (sólido) → al copiar cambia a «✓ Copiado» y el
  sólido pasa a **«Abrir su chat en Instagram ↗»** (enlace a `ig.me/m/<usuario>`, que en el celular
  abre la app de Instagram en el chat; en la computadora, Instagram en el navegador). Dice que sale de
  Qualify (N9).
- **El regreso:** cuando el dueño vuelve a la pestaña de Qualify, el cajón ya está en el **paso 3**
  con la pregunta. Si no vuelve, la tarjeta queda en **«Invitación copiada»** con «¿Ya le escribiste?»
  la próxima vez que abra la campaña. **Qualify nunca marca «Invitado» solo:** lo marca el dueño.
- **«Todavía no»** deja el estado en «Elegido» con el mensaje guardado.
- Resultado del paso 3 (N3): «Listo: María está invitada. Te avisamos en Por responder cuando te
  conteste.» + «Invitar al siguiente» (sólido, si hay más elegidos) / «Volver a la campaña».

**Cuando el creador responde.** El mensaje llega a **Por responder › Mensajes** (la pantalla que la
guía de navegación llama así; antes «Conversaciones»). Ese chat lleva arriba un `tag`
«Creador · Combo Vecino en Cúcuta» que enlaza a la ficha del candidato; la tarjeta del candidato pasa
a **«Te respondió»** con «Ver su respuesta» → `/responder?tab=mensajes&chat=<id>`.

### 4.5 Presupuestar — anotar y comparar propuestas

En la ficha del candidato, «Anotar su propuesta» abre un `drawer` de 4 pasos (una decisión cada uno):

| Paso | Pregunta | Entrada |
|---|---|---|
| 1 | ¿Qué te entrega? | `choice_card` checkbox: «Reel» · «Historias» · «Publicación» · «Visita a tu local», con cantidad (− 1 +) |
| 2 | ¿Para cuándo? | fecha (rellenada con la de la campaña) |
| 3 | ¿Puedes usar su video? | «Solo lo publica en su cuenta» · «También puedes publicarlo en tu perfil» · «También en tus anuncios, por {30} días» |
| 4 | ¿Cuánto cuesta? | «Pago»: monto · «Producto a cambio»: qué y **cuánto te cuesta a ti** («2 combos ≈ 40.000 pesos») — se pide para poder comparar |

La pestaña «Hablando» de la campaña muestra las propuestas lado a lado (misma tabla que Comparar):

| Fila | Ejemplo | Ayuda visible |
|---|---|---|
| Te entrega | 1 reel + 3 historias | — |
| Para cuándo | vie 14 | — |
| Puedes usar su video | En tu perfil y anuncios, 30 días | — |
| Cuesta | 150.000 pesos | — |
| **Te cuesta cada mil vistas** | 18.000 pesos `[Mejor]` | Lo que pagas por cada mil personas que suelen ver sus reels. Más bajo es mejor. |

«Te cuesta cada mil vistas» = costo ÷ (vistas típicas × reels que entrega) × 1.000 — **esperadas,
no prometidas**: el popover lo dice («Es una estimación con sus vistas típicas; un reel puede tener
más o menos.»). Arriba, «Llevas {x} de {tope}»; si las propuestas elegidas pasan el tope, `callout`
`warn`: «Con estas propuestas te pasas {x} de tu tope de {tope}.» Nunca se bloquea: el dueño decide.

### 4.6 Negociar — historial, respuestas sugeridas y el acuerdo

- **Historial** en la ficha del candidato, en orden, en palabras: «Tú le ofreciste: 1 reel por 2
  combos (lun 3)» · «Te pidió: 150.000 pesos y 1 combo (mar 4)» · «Tú le ofreciste: 120.000 pesos
  (mar 4)». Cada línea se anota con «Anotar su propuesta» / «Anotar lo que le ofreciste».
- **Respuestas sugeridas** en el chat de Por responder › Mensajes, como las demás respuestas
  asistidas: «Qualify te sugiere» + 2 opciones («Aceptar 150.000», «Proponer 120.000 + 1 combo») →
  «Usar esta respuesta» la pone en el cuadro; el dueño la revisa y la **envía él** (N13). Nunca se
  envía sola.
- **«Quedamos así»:** «Marcar como acordado» abre la revisión del acuerdo en palabras y un botón
  **«Copiar lo que acordaron»** para pegarlo en el chat:

> ¡Listo, María! Quedamos así: 1 reel y 3 historias en tu cuenta antes del viernes 14, mostrando el
> Combo Vecino. Podemos publicar tu video en nuestro perfil y en anuncios por 30 días. A cambio,
> 120.000 pesos. ¿Te parece bien?

  El estado pasa a **Acordado**; «Llevas {x} de {tope}» se actualiza.

## 5. Decisiones de palabras

| Usar | Nunca | Por qué |
|---|---|---|
| **creador** / creadores | influencer, influenciador, *creator* | Ya está en el glosario del sistema de diseño §7.2; «influencer» solo en textos de mercadeo, fuera de la app |
| **revisar** un creador | analizar, escanear, auditar | Lo que hace una persona, no una herramienta |
| **vistas** | views, reproducciones, visualizaciones | Corta y simple. Instagram en español dice «visualizaciones»: `[H]`, pregunta 4 del perfil §5 |
| **vistas típicas por reel** | mediana, promedio, *median views* | «Mediana» es técnica y «promedio» sería falso (no es un promedio) |
| **vistas frente a seguidores** | alcance, *reach*, ratio, tasa | Se explica sola con el `hint` |
| **interacción** | engagement, *ER*, tasa de interacción | Lista de palabras prohibidas de `qualify-ux` §3 |
| **se salió de lo normal** / «N veces lo normal» | viral, *outlier*, atípico | «Viral» promete algo que el dato no dice |
| **colaboración con marcas** / «colaboración pagada» | publi, *paid partnership*, *branded content* | «Colaboración pagada» es lo que Instagram muestra en español |
| **audio** | *sound*, música en tendencia | Instagram en español dice «audio» |
| **reel** | video corto (como nombre), *clip* | Decisión 11 del fundador: «reel» se usa |
| **Producto a cambio (canje)** | *barter*, intercambio | «Canje» es la palabra del medio, pero no todos los dueños la conocen: se aclara `[H]` (pregunta 9 del perfil §5) |
| **campaña** | proyecto, búsqueda, *brief* | ⚑ Decisión 1 |
| **Lo quiero** / **No me sirve** | preseleccionar, descartar, *shortlist* | Lo que diría el dueño; «Elegido» y «Descartado» como estado |
| **invitar**, invitación, invitado | contactar, *outreach*, DM | — |
| **propuesta**, «Te pidió» / «Le ofreciste» | contraoferta, *counter*, cotización | Más corto y dice quién hizo qué |
| **¿Puedes usar su video?** | derechos de uso, licencia, *whitelisting* | Lo que el dueño quiere saber, no el término legal |
| **Te cuesta cada mil vistas** | CPM, costo por mil | El nombre es la explicación |
| **Datos de hace N días** / **Actualizar** | última sincronización, *refresh*, caché | — |
| **Sin dato** | 0, N/A, —, «null» | Regla del fundador: sin dato nunca es cero |
| (nada) | créditos, costo de la consulta, ScrapeCreators | El dueño nunca ve créditos (encargo) ni proveedores |
| **Comprobado** · **Inferido** · **No sabemos** | verificado/estimado/desconocido, *confidence* | «Desconocido» suena a error; «No sabemos» es honesto (§6.4 del sistema de diseño) |

Número y moneda: punto de miles, coma decimal, «12,4 mil», «1,2 millones»; montos enteros en la
moneda del negocio («300.000 pesos», «150 dólares»), nunca centavos (`qualify-copy-es` §5).

## 6. Decisiones para el fundador (⚑)

1. **«Campaña»**: ¿la campaña con creadores es la misma «Campaña» que ya agrupa publicaciones
   (QUA-143)? Recomendado: sí (§1.1). Si no, «Búsqueda de creadores».
2. **Zona del menú:** Creadores se queda en el grupo de Resultados (donde ya está, sin cambio de
   arquitectura). ¿O prefiere moverlo a «Publica» cuando lleguen las campañas? Recomendado: quedarse
   por ahora.
3. **Gráfico:** aprobar un patrón de gráfico para el sistema de diseño (opción A de §3.3: pequeños, un
   color, misma escala) antes de construirlo.
4. **Lo que cuesta revisar:** ¿revisar o actualizar un creador descuenta de las «creaciones del mes»
   (decisión 8 de la guía), tiene su propio cupo, o no tiene límite visible? El texto de §2.2 («Este
   mes ya revisaste {n} creadores…») asume un cupo propio contado en creadores, nunca en dinero.
5. **Deslizar en el celular:** extender `media_carousel` con deslizar con el dedo y sin avance
   automático (§3.2), en lugar de un componente nuevo.
6. **«Mejor» en Seguidores:** recomendado no marcar el mejor en seguidores ni en reels por semana
   (§3.1). ¿De acuerdo, o lo quiere en todas las filas numéricas?
7. **Quién lo ve primero:** mientras lo usa solo el equipo de Attitude Factory, ¿el dueño sigue
   viendo «Pronto», o se abre a todos cuando salga la entrega 1?

## 7. Lo que necesita `reflex-ui-engineer` (entregas 1 y Comparar)

- **Componentes, todos existentes:** `app_shell`, `page_header`, `page_body`, `empty_state`, `card`
  (`interactive=True` con `rx.link`), `stat_card(label, value, hint=)`, `media_thumb`, `mono`, `tag`,
  `tone_badge`, `signal_pill`, `callout`, `skeleton_card`, `loading_spinner`, `progress_panel`,
  `drawer`, `choice_card(role="checkbox")`, `media_carousel` (extendido, ⚑5), y de Radix
  `rx.table`, `rx.popover`, `rx.alert_dialog`, `rx.accordion`, `rx.input` con slot, `rx.select`,
  `rx.segmented_control`. **Nada nuevo** salvo el gráfico, que espera ⚑3.
- **Rutas y direcciones:** `/creadores` (`?tab=`, `?flujo=agregar`), `/creadores/[creator_id]`,
  `/creadores/comparar?ids=<uuid>,<uuid>[,…]` (2–4, validados contra el negocio; inválidos →
  vuelve a la lista con «Elige de 2 a 4 creadores para comparar.»). Se quita el «Pronto» de
  `creators_page.py` y de `NAV_RESULTS` en el mismo cambio.
- **Menú:** toda ruta `/creadores…` ilumina «Creadores» (sidebar y «Más»), comparando con la URL del
  navegador; título de pestaña `Qualify · Creadores` en la lista; `Qualify · @{usuario}` en la ficha;
  `Qualify · Comparar creadores` en la comparación.
- **Estados por pantalla:** carga (skeleton con la forma de la tarjeta / de la ficha / de la tabla),
  vacío (§1.2), error de carga (`callout` en lugar del contenido), trabajando (spinner + frase),
  error de acción (`callout` encima, el contenido sigue), datos viejos (`callout warn` con botón).
- **Celular (360 px):** una columna; botones ≥ 44 px; ningún `rx.tooltip` como única explicación;
  el pie del modo comparar fijo abajo; el carrusel con botones visibles además de deslizar.
- **Lo que el modelo de vista entrega ya formateado** (el texto, no el número crudo): cifra con
  formato es-CO, «Sin dato» cuando falta, frescura en palabras, «N veces lo normal», la frase de
  colaboraciones con «más/menos», y qué celdas llevan «Mejor» (calculado en el servidor, con empates).
- **Pruebas que conviene dejar:** «Sin dato» nunca se muestra como 0; «Mejor» nunca va solo como
  color; no aparece ninguna palabra de la lista prohibida (`test_*_copy_words` como en otros módulos);
  la comparación no acepta ni 1 ni 5 ids.

## 8. Lo que todavía es hipótesis

- Que el dueño quiera revisar creadores **antes** de pagar, y que «vistas típicas» le diga más que
  «seguidores» `[H]` → pregunta 9 del perfil §5.
- Que conozca «canje» y que su forma habitual de pagar sea producto a cambio `[H]` → pregunta 9.
- Que diga «vistas» y no «reproducciones» o «visualizaciones» `[H]` → pregunta 4.
- Que el salto «copiar → abrir Instagram → volver» se entienda sin ayuda `[H]` → probarlo con un
  dueño real (pregunta 6, «mostrarle una pantalla real») antes de construir la entrega 4.
