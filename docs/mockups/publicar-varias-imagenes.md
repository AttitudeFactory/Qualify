# «Publicar ahora» con varias fotos: carrusel, una por una (mural) o historias

> ux-designer, 2026-11-12. Especificación para `reflex-ui-engineer`. Maqueta:
> `docs/mockups/publicar-varias-imagenes.html` (abrirla en el navegador; móvil primero).
> **Diseño hecho sobre el código** (`Qualify/publishing_page.py`, `publish_wizard_vm.py`,
> `publish_hub_state.py`, `ui/steps.py`, `ui/primitives.py`) **y no en la app en marcha**: quien lo
> construya revisa en el navegador los puntos marcados «verificar».

Decisiones firmadas por el fundador el 2026-11-12 (no se reabren aquí): con varias fotos el dueño
elige **«Juntas en un carrusel»** o **«Una por una»**; en «Una por una» el orden es **cómo se verá su
perfil** y Qualify publica de la última a la primera; **una historia por archivo**, en el orden
elegido y sin texto; en «Publicar» **solo cuentas de Instagram** (WhatsApp no aparece; Facebook,
apagada con su motivo).

---

## 1. El flujo en una línea por paso

Cada paso hace **una sola pregunta**. M es real: los pasos que no aplican no se cuentan (N6).

| # | Título del paso (el `h1`) | La única decisión | Cuándo aparece |
|---|---|---|---|
| 1 | ¿Qué vas a publicar? | qué fotos o videos | siempre |
| 2 | ¿Cómo sale? (1 archivo) · ¿Cómo salen? (2 o más) | publicación o historia · carrusel, una por una o historias | siempre |
| 3 | Elige el orden del carrusel · Así se verá tu perfil · ¿En qué orden se ven? | el orden | solo con 2 o más archivos |
| 4 | ¿En qué Instagram sale? | la cuenta | solo con 2 o más cuentas de Instagram activas |
| 5 | Revisa y publica | la descripción (o descripciones) y «Publicar» | siempre |

Recorridos típicos (un solo Instagram, el caso común):

- 1 foto → **Paso 1 de 3** ¿Qué…? → **2 de 3** ¿Cómo sale? → **3 de 3** Revisa y publica.
- 6 fotos en mural → 1 de 4 → 2 de 4 (Una por una) → 3 de 4 (Así se verá tu perfil) → 4 de 4.
- Con dos Instagram se suma «¿En qué Instagram sale?» y M sube en uno.

**Cambio respecto de hoy:** el paso 2 actual «¿Dónde sale?» pregunta dos cosas (tipo + cuenta). Se
parte: el tipo queda en el paso 2 y la cuenta pasa a un paso propio que **se salta** cuando hay una
sola cuenta de Instagram (queda preelegida y se nombra en la revisión).

**M cambia en vivo.** Si en el paso 1 el dueño pasa de 1 a 2 archivos, aparece el paso de orden;
la cabeza dice siempre el número real.

---

## 2. Límites

| Modo | Máximo | Por qué |
|---|---|---|
| Juntas en un carrusel | **10** | Límite de Instagram para un carrusel; el mismo de la galería hoy. |
| Una por una | **9** | Tres filas completas del perfil. Cada publicación sale **en serie y con la pantalla abierta**: con 9, la espera se queda en unos minutos, que un dueño entre clientes puede aguantar; con 12 ya es mucho rato con el teléfono quieto. 3, 6 y 9 dejan filas completas; no se obliga (4, 5, 7… se permiten). |
| Historias | **10** | El mismo tope de la galería; cada historia es una foto o un video. |

- La galería sigue aceptando hasta 10. Con 10 elegidos, la tarjeta «Una por una» aparece **apagada
  con su motivo** («Una por una llega hasta 9. Quita 1 en el paso anterior.»), nunca escondida.
- **Sugerencia de múltiplos de 3**, una sola vez y solo en el paso de orden del mural, cuando el
  número no es múltiplo de 3: «Con 3, 6 o 9 tus filas quedan completas. Con 5, la última fila
  lleva una publicación que ya tenías.» Nunca bloquea.

---

## 3. Paso por paso: estados y textos finales

Todos los textos son finales. `{n}` = cantidad, `{k}` = posición, `@cuenta` = `account_handle()`.

### Paso 1 — ¿Qué vas a publicar?

Igual que hoy (galería, «Agregar», ✕ por archivo, motivo de rechazo persistente, «Primero conecta
tu Instagram» si no hay ninguna). Dos cambios:

- **Se quita** la línea «Con dos o más, salen juntas en una sola publicación que se desliza
  (carrusel), en este orden.»: ya no es verdad; cómo salen se decide en el paso 2.
- Con 2 o más archivos, debajo de la galería: «En el paso siguiente eliges si salen juntas o una
  por una.» (`size="2"`, gris).
- Los números de las losetas siguen (orden en que se eligieron); el orden se cambia en el paso 3,
  no aquí.
- «Primero conecta tu Instagram» cuenta **solo cuentas de Instagram activas**: un negocio con
  WhatsApp o Facebook pero sin Instagram ve este aviso.

Motivo junto a «Siguiente» sin archivos: «Elige al menos una foto o un video.» (sin cambio).

### Paso 2 — ¿Cómo sale? / ¿Cómo salen?

Un grupo de `choice_card` con `role="radio"` (`role="radiogroup"`, `aria-label="Cómo salen"`).
**Preelegida:** la última opción que el dueño usó con esa cantidad de archivos; si no hay, la
primera de la lista.

**Con 1 archivo** (no hay pregunta de carrusel ni de orden):

| Tarjeta | Icono | Título | Descripción |
|---|---|---|---|
| publicación | `layout-grid` | Publicación en tu perfil | Queda en tu perfil, con su descripción. |
| historia | `circle-dashed` | Historia (24 h) | Se ve durante 24 horas, sin texto. |

**Con 2 o más archivos:**

| Tarjeta | Icono | Título | Descripción |
|---|---|---|---|
| carrusel | `gallery-horizontal` | Juntas en un carrusel | Una sola publicación que se desliza, con una descripción. |
| una por una | `layout-grid` | Una por una | Cada foto es su propia publicación, con su descripción. Así se arma un mural en tu perfil. |
| historias | `circle-dashed` | Como historias | Una historia por cada foto o video, una tras otra. Se ven 24 horas, sin texto. |

- «Una por una» apagada con más de 9: la descripción se cambia por «Una por una llega hasta 9.
  Quita {n−9} en el paso anterior.»
- Con videos entre los archivos, las tres opciones valen (ver §5). No se agrega texto extra aquí.
- El texto actual `STORY_NEEDS_ONE_FILE` («Una historia lleva una sola foto o un solo video.») **se
  retira**: ya no hay caso en que una historia quede bloqueada por la cantidad.

### Paso 3 — el orden (solo con 2 o más)

Componentes: filas o losetas `DragCard` (`class_name="q-rank-card"`, un `data-rank-group` por
pantalla) con `sort_handle` y el «⋯» de siempre. **Arrastrar nunca es la única forma**: el «⋯» de
cada una tiene «Primero · Subir uno · Bajar uno · Último · Quitar». «Quitar» saca el archivo de la
publicación (es el mismo ✕ del paso 1; no borra nada del teléfono) y muestra un toast
«Quitamos la foto {k}.» con «Deshacer».

Línea de ayuda (encima de la lista): «Mantén presionada una foto y muévela, o toca ⋯.»
`aria-live` tras cada movimiento: «Foto {k}, ahora en la posición {k'} de {n}.»

**3a. Carrusel — «Elige el orden del carrusel».** Lista vertical: asa · miniatura 56 px ·
«Foto {k}» / «Video {k}» · `tone_badge` «Portada» en la primera · «⋯».

Aviso de recorte (Meta recorta todo el carrusel a la forma de la primera):

- **Se muestra solo si los archivos no tienen la misma forma** (cuadrada, vertical, horizontal). Si
  todas tienen la misma forma, o la forma no se conoce, no se dice nada.
- `callout` tono `warn`, debajo de la lista:
  «Instagram corta todas a la forma de la primera ({forma}). Si alguna se ve cortada, pon primero
  la que tiene la forma que quieres.» — `{forma}` = «cuadrada» | «vertical» | «horizontal».
- **Cuando un movimiento cambia cuál es la primera** y las formas difieren, el aviso se actualiza
  con la nueva forma y lo anuncia el `aria-live` («Ahora la portada es la foto {k}: todas salen
  {forma}s.»). No es un toast: queda mientras el paso esté a la vista.
- Para saber la forma: la miniatura ya se lee en el navegador (`ui/image_preview.py`,
  `ui/video_preview.py`); hace falta guardar también ancho y alto. **Verificar** que el helper lo
  permite sin tocar el backend; si no, el aviso se muestra solo cuando hay fotos **y** videos
  mezclados (el caso que el código ya documenta como riesgo, `publishing_page.py:43-49`).

**3b. Una por una — «Así se verá tu perfil».** Grilla de **3 columnas**, losetas 3:4 (como la grilla
actual del perfil de Instagram; **verificar** la proporción vigente al construir), número de
posición arriba a la izquierda y «⋯» arriba a la derecha (44 px). La posición 1 es la de arriba a
la izquierda: la que se verá primero.

- Debajo de las nuevas, en la misma grilla, losetas tenues con la palabra «Antes» rellenan la
  última fila cuando {n} no es múltiplo de 3, para que el dueño vea qué publicación vieja queda al
  lado. Son decorativas (`aria-hidden`), sin foto: no leemos su perfil.
- Texto bajo el título: «Ordénalas como quieres verlas en tu perfil. Nosotros las publicamos en el
  orden correcto para que el mural quede armado.»
- Sugerencia de múltiplos de 3 (§2), cuando aplica.
- Aviso del mural, **una vez**, al pie de la grilla, gris: «Si después publicas una sola cosa, tu
  mural se corre un lugar. Si publicas de a 3, se mantiene.»
- **Arrastre en grilla:** `rank-drag.js` suelta sobre la tarjeta que queda debajo del dedo, lo que
  debería valer en dos dimensiones; ↑/↓ del teclado mueven una posición en orden de lectura.
  **Verificar.** Si no funciona en grilla, ver §7 (compromiso).
- En la loseta **no** va el asa de 44 px (no cabe junto al número y al «⋯» en 105 px): se levanta
  con pulsación larga sobre la loseta, y el teclado usa el «⋯». Ver §7.

**3c. Historias — «¿En qué orden se ven?»** Lista vertical igual a 3a, sin «Portada» ni aviso de
recorte. Texto: «Se publican en este orden: la primera es la que se ve primero.»

Motivo junto a «Siguiente»: ninguno; el orden siempre es válido.

### Paso 4 — ¿En qué Instagram sale? (solo con 2 o más Instagram activos)

Grupo de `choice_card` (`role="radio"`), una por cuenta, con `platform_badge` y «@cuenta».
Reemplaza el `rx.select` de hoy (en el teléfono, tarjetas grandes en vez de una lista desplegable).

- **Solo Instagram se puede elegir.** WhatsApp **no aparece**.
- **Facebook aparece apagada** (`choice_card(disabled=True)`), con su motivo escrito dentro de la
  tarjeta, nunca solo en `title` (el Planificador hoy lo pone en `title`, que en el teléfono no se
  ve): «Todavía no publicamos en Facebook desde aquí.»
- Preelegida: la última usada; si no hay, la primera de Instagram.
- Con **una sola** cuenta de Instagram el paso no aparece; si además hay una de Facebook, tampoco
  (no hay nada que elegir).
- Sin cuentas de Instagram: el aviso del paso 1 ya lo cubre; de respaldo, el `empty_state` de hoy.

Motivo junto a «Siguiente»: «Elige la cuenta donde vas a publicar.»

### Paso 5 — Revisa y publica

Arriba, la frase de revisión (icono `send`) y las miniaturas en el orden elegido.

| Modo | Frase de revisión |
|---|---|
| 1 publicación | Sale ahora en Instagram @cuenta como publicación. *(sin cambio)* |
| 1 historia | Sale ahora en Instagram @cuenta como historia (se ve 24 horas). *(sin cambio)* |
| Carrusel | Sale ahora en Instagram @cuenta: una publicación con {n} fotos que se deslizan. |
| Una por una | Salen ahora en Instagram @cuenta: {n} publicaciones, una tras otra, en el orden de tu mural. Tarda unos minutos. |
| Historias | Salen ahora en Instagram @cuenta: {n} historias, en este orden (se ven 24 horas). |

(«fotos» se cambia por «fotos y videos» o «videos» según lo que haya.)

**Descripción — carrusel o 1 publicación:** un solo campo. Rótulo «Descripción (opcional)»,
ejemplo «Ej.: Hoy combo vecino a mitad de precio hasta las 9 p. m.», ayuda «Sale tal como la
escribas.» (hoy dice «Texto de la publicación (opcional)»: se alinea con «descripción»).

**Descripciones — una por una:** una tarjeta por foto, en el orden del mural: miniatura 56 px +
«Foto {k}» + campo de 3 filas, rótulo visible «Descripción de la foto {k} (opcional)».

- **Recomendación: vacía permitida.** Instagram la acepta, y en un mural muchas piezas no necesitan
  texto; obligarla haría escribir 9 veces antes de poder publicar. Nada bloquea «Publicar».
- Debajo del primer campo, con 2 o más fotos, un botón `soft`: «Usar este texto en las demás».
  Llena **solo las vacías**; toast «Listo, lo pusimos en {m} descripciones vacías.» con «Deshacer».
  Se apaga si el primer campo está vacío. *Hipótesis:* que el dueño quiera el mismo texto en
  varias (pregunta §5.5 de `docs/perfil-cliente-pyme.md`: ¿le cuesta escribir el texto?).
- Es el mismo dato repetido (un solo dominio: el texto de cada foto), no un formulario mezclado.

**Historias:** sin campo. Texto: «Las historias salen sin texto.» Si hay **una sola**, sigue «Si
quieres escribirle algo, ábrela en Instagram.» con el «o» y «Abrir en Instagram ↗» de hoy; con
varias, esa salida no aparece (compartir abre un solo archivo).

**Botón principal (N13):**

| Modo | Botón |
|---|---|
| 1 publicación / carrusel | Publicar en Instagram |
| 1 historia | Publicar historia |
| Una por una | Publicar las {n} |
| Historias | Publicar las {n} historias |

---

## 4. Publicando, fallas y final

### 4.1 Una sola publicación (1 archivo o carrusel)

Igual que hoy: `_status_block` («Subiendo tus fotos y videos...», luego la espera de Instagram con
el tiempo transcurrido y `_WAIT_EXPLANATION`) y su falla (`callout` error con el motivo).

### 4.2 Varias en serie (una por una e historias)

Al tocar «Publicar las {n}», el paso 5 cambia a la vista de progreso **dentro del mismo marco**: la
cabeza conserva «Revisa y publica», el pie muestra solo el botón ocupado (`primary_loading`) y
«Atrás» se esconde.

- `progress_panel(title, detail, value=…)` con valor real (publicadas ÷ total):
  - título: «Publicando {i} de {n}…» (`i` = la que está saliendo ahora, contando desde 1);
  - detalle: «Deja esta pantalla abierta hasta que terminen. Puede tardar unos minutos.»
- Debajo, la misma grilla del mural (o la lista de historias) con un `signal_pill` por pieza,
  **siempre con texto**, nunca solo color:
  - «Publicada» (`ok`), «Publicando…» (`warn`), «En espera» (`neutral`), «No salió» (`error`).
- En el mural, las losetas se van marcando **de la última a la primera**: así ve el dueño cómo se
  arma su perfil, sin tener que pensar en el orden al revés. El contador cuenta publicaciones, no
  posiciones.
- Las historias salen de la primera a la última.
- Cada pieza espera a que Instagram confirme la anterior antes de empezar (lo que ya hace el
  servicio). Con videos, la espera de cada uno usa `_WAIT_EXPLANATION`.

**Si el dueño intenta salir mientras publica:**

- Tocar el menú, la cabeza «‹ Inicio» o el «atrás» del teléfono abre un `rx.alert_dialog` (patrón
  §6.2):
  - título «¿Salir mientras se publican?»;
  - texto «Las que ya salieron se quedan en tu perfil. Las {r} que faltan no se publicarán.»;
  - botones «Seguir aquí» (sólido, el que tiene el foco) y «Salir igual» (soft).
- Cerrar la pestaña: el aviso nativo del navegador (`beforeunload`) mientras haya piezas en espera.
  Su texto lo pone el navegador.
- Si vuelve a «Publicar» en la misma sesión y quedaron piezas sin salir: arriba del paso 1, un
  `callout` `warn` «Te quedaron {r} sin publicar de tu mural.» (o «de tus historias») con
  «Continuar» (sólido, va directo a la vista de progreso y sigue) y «Descartar» (soft). Si la
  sesión se perdió, no se muestra nada: **verificar** qué sobrevive en el estado de Reflex.

### 4.3 Falla en medio (algunas salieron, una no)

Se detiene la serie en la que falló (no se salta: en un mural, saltarla lo desarma).

- `callout` tono `error`, encima de la grilla:
  - «Salieron {s} de {n}. La foto {k} no salió.» (o «El video {k}»);
  - el motivo, con el texto de error que ya produce el servicio (`PublishState.error`), que dice
    qué pasó y qué hacer;
  - «Las que salieron ya están en tu perfil. Si continúas, seguimos desde la foto {k} y tu mural
    queda en orden.» (historias: «…seguimos desde la historia {k}.»)
- Botones: «Continuar desde la foto {k}» (sólido) y «Dejar así» (soft).
- «Continuar» reintenta **esa misma pieza** y sigue con las demás en el mismo orden.
- «Dejar así» lleva al final parcial (4.4). En el mural, antes, un `rx.alert_dialog`: «¿Dejar el
  mural sin terminar?» / «En tu perfil quedan {s} de las {n}. Puedes publicar las otras después,
  pero si publicas otra cosa en medio, el mural se corre.» / «Dejar así» · «Volver».
- Si el motivo es la cuenta desconectada, «Continuar» se cambia por el enlace de siempre a
  «Tus redes» («Conectar mi Instagram»), y la serie queda esperando (4.2, «Te quedaron…»).

### 4.4 Final (N3, persistente, con el siguiente paso)

`callout` `ok` + «Ver mi semana» (sólido) + «Publicar otra» (soft), como hoy.

| Caso | Texto |
|---|---|
| 1 publicación | Listo, ya está en tu Instagram. *(sin cambio)* |
| 1 historia | Listo, tu historia ya está en Instagram (se ve 24 horas). *(sin cambio)* |
| Carrusel | Listo, tu carrusel ya está en Instagram. |
| Una por una | Listo, tus {n} publicaciones ya están en Instagram. Tu mural quedó armado. |
| Historias | Listo, tus {n} historias ya están en Instagram (se ven 24 horas). |
| Parcial | Salieron {s} de {n}. Las otras {r} no se publicaron. *(tono `warn`, no `ok`)* |

El toast de hoy sigue como extra.

---

## 5. Casos de borde

- **1 archivo:** sin pregunta de carrusel, sin paso de orden. 3 pasos (o 4 con dos Instagram).
- **Fotos y videos mezclados:** valen los tres modos. Carrusel: es el caso más probable del aviso
  de recorte (3a). Una por una: cada video sale como su propia publicación de video y se ve en la
  grilla; la loseta lleva el icono `film` junto al número. **Verificar** que un video solo sale
  hoy con la opción de mostrarse en el perfil (si saliera solo en la pestaña de reels, el mural se
  rompería). Historias: un video por historia.
- **Quitar:** en el paso 1 (✕) o en el paso 3 («⋯ › Quitar», con «Deshacer»). Si al quitar quedan
  menos de 2, desaparece el paso de orden y el modo vuelve a «Publicación en tu perfil» o
  «Historia» según lo que era (carrusel y una por una → publicación; historias → historia).
- **Agregar después de ordenar:** el archivo nuevo entra al final; el orden ya hecho se conserva.
- **Cambiar de modo después de ordenar:** el orden se conserva (es la misma lista).
- **Más de 9 y elige «Una por una»:** imposible, la tarjeta está apagada con su motivo (§2).
- **Descripción vacía:** permitida en todos los modos (§3, paso 5).

---

## 6. Título de la pestaña y del menú (N1)

- Pestaña: **«Qualify · Publicar ahora»** = entrada del menú «Publicar ahora» (`ui/layout.py:108`).
  El `h1` es el nombre del paso, según el marco de pasos (§4.5 del sistema de diseño).
- El código ya declara ese título (`Qualify/Qualify.py:351`). Si la pestaña muestra «Por aprobar»,
  es que el título de otra ruta (`Qualify/Qualify.py:560`) se queda al navegar dentro de la app:
  **reproducirlo en el navegador** (entrar a `/publish` desde el menú, sin recargar) y corregirlo;
  no se arregla solo cambiando el texto.

---

## 7. Dónde el sistema de diseño obligó a ceder

Nada de esto pide un componente ni un color nuevo; todo se arma con `choice_card`, `DragCard` +
`sort_handle` + «⋯», `media_thumb`, `callout`, `signal_pill`, `tone_badge`, `progress_panel`,
`rx.alert_dialog` y el marco `step_frame` / `step_head` / `step_foot`.

1. **Grilla ordenable (mural).** `sort_handle` y `rank-drag.js` nacieron para listas verticales. Se
   usan en una grilla de 3 columnas sin el asa visible en la loseta (no cabe en ~105 px junto al
   número y al «⋯»); se levanta con pulsación larga y el «⋯» es la vía de teclado y lector de
   pantalla. Si el arrastre no funciona en dos dimensiones, **plan B sin componente nuevo**: la
   grilla queda como vista previa (solo mirar) y debajo va la misma lista vertical de 3a para
   ordenar. Que el fundador lo vea si se llega a ese plan B.
2. **Losetas «Antes»** del mural: son la loseta de la galería (`q-pub-tile`) vacía y tenue, con una
   palabra; no un componente nuevo.
3. **Forma de cada archivo** (aviso de recorte): extiende un helper que ya existe para guardar
   ancho y alto; si no se puede, el aviso cae al caso de fotos y videos mezclados (3a).

---

## 8. Lo que `reflex-ui-engineer` necesita (resumen)

- `publish_wizard_vm.py`: modos `posts` / `stories` → agregar `carousel`, `one_by_one`,
  `stories_many` (nombres a criterio); pasos dinámicos con M real; `STEP_TITLES` por modo; límites
  `CAROUSEL_MAX = 10`, `ONE_BY_ONE_MAX = 9`, `STORIES_MAX = 10`; las frases de §3–§4 como
  funciones puras con sus tests; quitar `STORY_NEEDS_ONE_FILE`.
- Estado: el orden como **una sola lista** (`pending_items`), movida por el arrastre y por el «⋯»;
  una descripción por archivo en «Una por una»; la serie con índice de la pieza actual, publicadas,
  fallida y su motivo; «Continuar» reanuda desde la fallida.
- Mural: el envío en orden inverso lo hace la pantalla (o el servicio); el dueño nunca lo ve.
- Cuentas: filtrar a Instagram activas; Facebook apagada con su motivo visible; WhatsApp fuera.
- Pruebas en el navegador, a 360 px y en escritorio, con lo marcado «verificar» en este documento.
