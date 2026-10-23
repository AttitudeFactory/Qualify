# Auditoría de experiencia — M3 · Crear publicaciones (piezas)

`[2026-10-23 · auditoría de solo sugerencias, no se tocó código]`
Pantallas: `/create` (asistente), `/drafts` (galería «Piezas»), `/drafts/[draft_id]` (revisión).

> **Nota de alcance.** El asistente de `/create` **no** vive en `Qualify/creative_wizard_pages.py`
> (ese archivo es el asistente de la identidad de marca, `/brand/*`, y le corresponde al módulo
> Marca). `/create` es `creative_pages.create_index()` → `content_generator.generator_page()`
> (`Qualify/content_generator.py`, 4,7 mil líneas); las vistas de cada paso se definen en
> `Qualify/creative_state.py:425-494` (`generator_views`, `_VIEW_LABELS`). Esta auditoría lee ese
> archivo. De `voice_lab.py` solo se revisa lo que llega al dueño desde un video con avatar.

## (a) El trabajo del módulo, en palabras del dueño

1. «Quiero sacar una publicación de mi producto (el combo, el helado del mes) sin diseñador.»
2. «Que me la entregue lista —foto, texto y etiquetas— para mirarla y decir sí o no.»
3. «Una vez aprobada, quiero dejarla programada y volver a atender el local.»

## (b) Hallazgos (ordenados por severidad)

Severidad: 1 = no puede terminar · 2 = se pierde o abandona · 3 = palabras técnicas/en inglés ·
4 = accesibilidad/celular · 5 = pulido.

### 1. Después de aprobar en la revisión no hay a dónde ir (callejón sin salida) — sev. 1 · S
- **Dónde:** `Qualify/creative_pages.py:2121-2207` (`_decision_bar`, desaparece al aprobar) y
  `Qualify/creative_state.py:5241` (solo un aviso que se borra solo).
- **Lo que siente el dueño:** «Ya aprobé… ¿y ahora? ¿Ya se publicó? ¿Dónde la programo?» El aviso
  dice «Planificador» pero no hay botón; tiene que abrir el menú y buscar la pieza otra vez.
- **Arreglo:** al aprobar, la barra de decisión se reemplaza por una tarjeta de siguiente paso
  (componentes existentes: `card` + `button` sólido) que lleva a `/planner?post=<id>` (lo mismo
  que ya hace `GalleryState.assign`).
  ```
  ┌──────────────────────────────────────────┐
  │ ✓ Aprobada. Todavía no se publica.        │
  │ Elige el día y la hora en que sale.       │
  │ [ Programar esta publicación → ]          │
  │  Crear otra publicación                   │
  └──────────────────────────────────────────┘
  ```
  Aviso: «Publicación aprobada. Ahora elige cuándo sale.»

### 2. Ocho pantallas antes de «Generar» y lo único obligatorio va casi al final — sev. 2 · L
- **Dónde:** `Qualify/creative_state.py:425-439` (`generator_views`: `[... "rules", "topic",
  "campaign", "summary"]`), `Qualify/content_generator.py:3434-3484` («Es lo único obligatorio»).
- **Lo que siente el dueño:** producto → tipo → (tipo de avatar) → Publicación → Presentador →
  Guion y fondo → Datos clave → Contexto → Campaña → Resumen. Un Avatar humano son 10 pantallas;
  un Flyer, 8. «¿Cuánto falta?» No cabe en 2 minutos con una mano.
- **Arreglo:** 4 pasos por dominio, con todo lo opcional detrás de «Más opciones» y valores
  ya rellenados (formato por defecto según el tipo, sin campaña, «De qué trata» = Producto).
  ```
  ① ¿Qué quieres mostrar?      [foto Combo ✓] (de tu catálogo)        Paso 1 de 4
  ② ¿Qué quieres decir?        [ Promo solo este fin de semana… ]
                               [✨ Mejorar mi texto]   ▸ Más opciones (precio, qué evitar)
  ③ ¿Cómo la quieres?          (•) Imagen  ( ) Galería  ( ) Video corto  ( ) Guion para grabar
                               ▸ Más opciones (formato, campaña, fotos extra, presentador)
  ④ Revisa y crea              «Imagen 4:5 para Instagram sobre Combo Vecino»  [ Crear ]
  ```
  El paso ② (Contexto) sube al principio porque es el único obligatorio; «Datos clave» y «Campaña»
  pasan a «Más opciones».

### 3. La revisión habla en lenguaje de oficina técnica — sev. 3 · S
- **Dónde:** `Qualify/creative_pages.py:2345` «HITL #2: tú decides…»; `:2359` botón «Bandeja»;
  `:1237` «Copy → imagen → verificación»; `Qualify/Qualify.py:420` título de pestaña «Qualify ·
  Borrador» frente al encabezado «Revisión del borrador».
- **Lo que siente el dueño:** «¿Qué es HITL? ¿Bandeja de qué? ¿Copy?»
- **Arreglo (cadenas exactas):**
  - Encabezado: «Revisa tu publicación» · subtítulo: «Nada sale sin que tú la apruebes.»
  - Volver: «← Mis publicaciones»
  - Progreso: «Texto → imagen → revisión. La pantalla se actualiza sola.» (y las etapas
    `GENERATION_STAGES` en `creative_state.py:577` → «Texto», «Imagen», «Revisión»).
  - Pestaña: `title="Qualify · Revisar publicación"`.

### 4. «POST», «caption», «CTA», «Flyer», «Story», «Reel», «UGC» por toda la pantalla — sev. 3 · M
- **Dónde:** `creative_pages.py:879` «Ver POST», `:1113` «Crear POST», `:1136` «Todavía no hay
  POSTs», `:1152` «Tus POSTs…», `:1025` «¿Rechazar este POST?», `:1457`, `:2180`, `:1766`
  «Llamado a la acción (CTA)», `:1872` «El caption que acompaña al post»;
  `creative_vm.py:831-870` («Generar guion… creador UGC», «Flyer», «para el feed o la historia»,
  «Tres diapositivas en un post»); `content_generator.py:237` (tooltip «UGC»), `:4240` «Texto del
  post»; `creative_state.py:515-518` («Post 4:5», «Reel 9:16», «Story 9:16»).
- **Lo que siente el dueño:** mezcla de inglés que la regla de la casa prohíbe; «¿UGC?».
- **Arreglo (cadenas exactas):** «Ver publicación», «Crear publicación», «Todavía no tienes
  publicaciones», «Tus publicaciones y en qué punto está cada una. Nada sale sin tu aprobación.»,
  «¿Descartar esta publicación?», «Invitación a comprar o escribir», «El texto que acompaña la
  publicación en Instagram», «Texto de la publicación»; tipos: «Guion para grabar» («Te damos lo
  que hay que decir y cada toma; lo graba alguien de tu equipo o un creador.»), «Imagen»
  (en vez de «Flyer»), «Galería» («Tres fotos o videos en una sola publicación»); formatos:
  «Publicación 4:5», «Video corto 9:16» (hipótesis §5 P4: validar si el dueño dice «reel»),
  «Historia 9:16».

### 5. «Cold / Hot / evergreen» en grande sobre cada tarjeta de la galería — sev. 3 · S
- **Dónde:** `Qualify/creative_pages.py:953-965` (lo muestra); textos en
  `Qualify/planner_vm.py:1349-1356`.
- **Lo que siente el dueño:** «¿Hot? ¿Evergreen?» Es la etiqueta más grande de la tarjeta y no
  la entiende.
- **Arreglo:** «Nueva» (nunca salió) / «Ya probada» (salió N veces); ayuda: «Ya salió 3 veces en
  tus redes: se puede repetir sin problema.» El texto de ayuda no puede ir solo en `title=`
  (se ve solo al pasar el mouse): mostrarlo en la vista de la pieza.

### 6. El costo se muestra en dólares y se habla de «créditos» sin decir cuáles — sev. 2 · M
- **Dónde:** `creative_pages.py:2003-2011` («Coste: $0.06», detalle solo al pasar el mouse),
  `:2081` y `:2170` («Consume créditos»), `variations_view.py:47` («cada una se paga al generarla»).
- **Lo que siente el dueño:** «¿Me van a cobrar? ¿Cuánto en mi moneda? ¿Qué créditos tengo?» Es
  el miedo que frena al segmento (presupuesto chico). Va contra `qualify-copy-es` regla 5
  (moneda del negocio).
- **Arreglo:** en la moneda del negocio, o quitarlo de la vista del dueño mientras el equipo opera
  la cuenta (hipótesis §5 P1-P2: quién paga y quién ve). Si queda: «Pedir otra versión usa 1 de tus
  N creaciones del mes.» Nunca «Consume créditos» sin número.

### 7. En el celular, «Variaciones» y «Descubrir reels» quedan escondidos fuera de pantalla — sev. 4 · S
- **Dónde:** `assets/qualify-creative.css:394-395` (la lista de tipos es una fila que se desliza
  de lado), `content_generator.py:267-301`; las explicaciones de cada tipo viven en un
  `rx.tooltip` (`:199-230`, `_OPTION_TOOLTIPS`), que en el celular no se ve.
- **Lo que siente el dueño:** a 360 px ve «Guion · Avatar · Clip…» cortado; no sabe que hay más
  ni qué es cada uno.
- **Arreglo:** en el celular, la elección de tipo es el paso ③ del hallazgo 2, en una columna con
  `choice_card` y su descripción visible (`_choice_card` con `blurb`, que ya existe). Quitar el
  tooltip como única explicación.

### 8. Avisos de marca que apuntan a la pantalla equivocada o hablan de «Brand Kit» — sev. 2 · S
- **Dónde:** `content_generator.py:4645-4650` («completa el Brand Kit y la voz en Marca» — dentro
  de la sesión no existe «Marca», el menú dice «Brand Kit»), `:3515` («con tu Brand Kit»),
  `creative_pages.py:1894-1896` («Es una regla de tu Brand Kit» → enlace a `/brand`, que dentro
  de la sesión redirige).
- **Lo que siente el dueño:** «¿Dónde está Marca?» Busca y no lo encuentra.
- **Arreglo:** «Completa tu marca (colores, logo y forma de hablar) para que todo salga con tu
  estilo.» + botón «Completar mi marca» → `/brand/kit`. En la revisión: «Esta palabra no va con tu
  marca.» + enlace «Cambiar esta regla» → `/brand/kit`. «Potenciar con IA» → «Mejorar mi texto» con
  ayuda «Ordenamos tu texto con lo que sabemos de tu marca, sin inventar precios ni promociones.»

### 9. Nombres de proveedores y variables de servidor delante del dueño — sev. 3 · S
- **Dónde:** `variations_view.py:44` «Claude los propone», `:577` «Edita lo que Claude propuso»;
  `voice_lab.py:93` «falta configurar QUALIFY_ANTHROPIC_API_KEY»; `voice_lab.py:107` «No se pudo
  leer la base de datos.»
- **Lo que siente el dueño:** «¿Quién es Claude? ¿Qué es esa clave?»
- **Arreglo:** «Te proponemos diez ideas; tú decides cuáles siguen.», «Edita lo que te
  propusimos.», «No podemos escuchar tu tono ahora mismo. Inténtalo más tarde.», «No pudimos cargar
  tus datos. Recarga la página en un momento.»

### 10. El resultado de un guion o una imagen tiene tres botones «Copiar» y no dice qué sigue — sev. 5 · S
- **Dónde:** `content_generator.py:4170-4253` (guion, descripción, hashtags y texto, cada uno con
  su «Copiar»), `:4097` «Así quedó. También está en Piezas para revisarla.», `:4454-4458` «Crear
  otro» con flecha hacia atrás.
- **Lo que siente el dueño:** «¿Tengo que copiar todo esto? ¿Ya está aprobada?»
- **Arreglo:** subtítulo «Así quedó. Revísala y apruébala para poder programarla.»; botón
  principal «Revisar y aprobar» (ya existe, quitar «en Piezas»); secundario «Crear otra» sin flecha
  hacia atrás (icono `plus`). Los «Copiar» se quedan solo en el guion para grabar.

### 11. «Datos clave» pide dos campos lado a lado y «separado por comas» — sev. 4 · S
- **Dónde:** `content_generator.py:3721-3743` (campo con `width="38%"`, sin etiqueta visible, solo
  el texto de ejemplo), `:3780-3800` («Separado por comas.»).
- **Lo que siente el dueño:** a 360 px el campo del nombre queda de ~110 px; escribir comas en el
  teclado del celular cuesta.
- **Arreglo:** una fila por dato en una columna con etiquetas visibles «¿Qué dato?» / «¿Cuánto o
  cuál?»; «Debe mencionar» y «Debe evitar» como chips (el patrón `_add_row` + `_removable_chip`
  de `creative_pages.py:1557-1608` ya existe).

### 12. Tres nombres para lo mismo: pieza, POST, borrador, publicación — sev. 5 · S
- **Dónde:** menú `ui/layout.py:76-77` («Crear pieza», «Piezas»), `Qualify.py:409-421` (pestañas
  «Crear pieza», «Piezas», «Borrador»), galería «POST», revisión «borrador», toasts «POST aprobado».
- **Lo que siente el dueño:** «¿Una pieza es lo mismo que un borrador?»
- **Arreglo:** una sola palabra: **publicación**. Menú: «Crear publicación», «Mis publicaciones».
  Estados de la galería (`planner_vm.py:548-554`): «Por revisar», «Le falta algo», «Lista para
  programar», «Ya salió», «Descartada».

## (c) Navegación

### Hoy

```
Menú «Publicas»: Crear pieza (/create) · Piezas (/drafts) · Planificador · Publicar

/create
 ├─ Pantalla producto («¿Sobre qué producto creamos?»)  ── [Ir al catálogo] sale a /catalog y pierde el paso
 └─ Panel lateral «¿Qué creamos?» + vistas con barra de pasos (sin «Paso N de M»)
     └─ Resumen → [Generar] → «Tu pieza» (en la misma página)
          ├─ [← Crear otro]  (reinicia /create)
          └─ [Revisar y aprobar en Piezas →]  → /drafts/<id>
/drafts  (galería)  ── tarjeta: [Rechazar] [Aprobar] [Ver POST] · lista: [Programar] → /planner?post=<id>
/drafts/<id> (revisión) ── [← Bandeja] → /drafts
     └─ [Aprobar] → se queda aquí, solo un aviso   ✗ callejón sin salida
/canva/callback, /canva/return → «Volver al generador» → /create
```

Problemas: el paso final del trabajo (programar) solo se alcanza desde la galería; la revisión
termina sin siguiente paso; «Ir al catálogo» saca al dueño del asistente sin camino de vuelta; los
títulos de pestaña, encabezado y menú no coinciden (pieza / borrador / POST); la barra de pasos no
dice cuántos faltan y en el celular oculta los nombres de los pasos.

### Propuesta (patrón «crear → revisar → programar»)

```
Menú «Publicas»: Crear publicación · Mis publicaciones · Calendario · Publicar

/create  «Crear publicación»   Paso 1 de 4 … Paso 4 de 4  (Atrás siempre, sin perder datos)
   ① Qué mostrar → ② Qué decir → ③ Cómo la quieres → ④ Revisa y crea
   └─ [Crear] → espera en la misma página → lleva directo a /drafts/<id>
/drafts/<id>  «Revisa tu publicación»   migas: Mis publicaciones › Combo Vecino
   ├─ [Aprobar] → tarjeta «Aprobada. Todavía no se publica.» → [Programar esta publicación] → /planner?post=<id>
   ├─ [Pedir otra versión] → se queda aquí con la nueva versión
   └─ [Descartar] → vuelve a /drafts con aviso «Publicación descartada»
/drafts  «Mis publicaciones»  filtros por estado; cada tarjeta, un solo botón principal según su estado:
   Por revisar → [Revisar] · Lista → [Programar] · Ya salió → [Ver]
/catalog desde /create → se abre con «← Volver a crear tu publicación» (vuelve con el producto elegido)
```

Reglas del patrón para todo el módulo: (1) cada pantalla termina con **un** botón principal que
lleva al siguiente paso del trabajo; (2) el título de pestaña = encabezado = nombre del menú;
(3) «volver» dice a dónde vuelve; (4) nunca «se publicó» sin que el dueño haya programado y
aprobado.

## (d) Historias de usuario propuestas

### Grupo A — Llegar a una publicación aprobada y programada

**A1. Como dueño, quiero que al aprobar me lleve a programarla, para no tener que buscarla otra vez.**
- Al aprobar en `/drafts/<id>` aparece «Aprobada. Todavía no se publica.» con el botón «Programar
  esta publicación» que abre `/planner?post=<id>`.
- El aviso dice «Publicación aprobada. Ahora elige cuándo sale.»
- El texto nunca dice ni sugiere que ya se publicó.

**A2. Como dueño, quiero crear una publicación en 4 pasos cortos, para terminarla en 2 minutos desde el celular.**
- `/create` muestra «Paso N de 4» y los pasos ① Qué mostrar ② Qué decir ③ Cómo la quieres ④ Revisa y crea.
- Datos clave, qué evitar, campaña, formato y presentador quedan en «Más opciones», con valores ya rellenados.
- «Atrás» conserva lo escrito; una segunda publicación con los valores por defecto se completa con 3 toques de «Siguiente» y «Crear».
- A 360 px todo es una columna, sin desplazamiento lateral, botones ≥ 44 px.

**A3. Como dueño, quiero ver en la galería un solo botón claro por publicación, para saber qué me toca hacer.**
- Por revisar → «Revisar»; Lista → «Programar»; Ya salió → «Ver».
- Los estados se leen en texto («Por revisar», «Lista para programar»…), no solo por color.

### Grupo B — Palabras que el dueño entiende

**B1. Como dueño, quiero que todo diga «publicación» y no POST, borrador, pieza o caption, para no confundirme.**
- Menú, pestañas (`add_page title=`), encabezados, botones y avisos usan «publicación».
- Ninguna cadena del módulo contiene: POST, caption, CTA, Flyer, Story, UGC, HITL, Bandeja, Copy, Brand Kit.
- «Cold/Hot/evergreen» se reemplaza por «Nueva» / «Ya probada».

**B2. Como dueño, quiero que los errores no muestren nombres de proveedores ni de configuración, para saber qué hacer.**
- Ningún texto visible menciona Claude, variables `QUALIFY_*` ni «base de datos».
- Cada error dice qué pasó y qué hacer ahora (`qualify-copy-es` regla 3).

**B3. Como dueño, quiero que los avisos de «completa tu marca» me lleven al lugar correcto, para arreglarlo en un toque.**
- El aviso de `/create` y la regla rota en la revisión llevan a `/brand/kit`.
- El texto dice «tu marca», no «Brand Kit» ni «Marca».

### Grupo C — Confianza con el dinero

**C1. Como dueño, quiero saber antes de tocar «Pedir otra versión» si me cuesta y cuánto, en mi moneda, para no llevarme sorpresas.**
- El costo, si se muestra, va en la moneda del negocio o en «N de tus creaciones del mes».
- Desaparece «Consume créditos» sin número.
- Hipótesis §5 P1-P2: validar con Bianki/Polette si el dueño debe ver el costo o solo el equipo.

### Grupo D — Celular y accesibilidad

**D1. Como dueño, quiero ver todas las opciones de qué crear con su explicación en el celular, para elegir sin adivinar.**
- A 360 px los tipos (incluidos «Variaciones» y «Descubrir ideas de videos») se ven en columna con su descripción visible.
- Ninguna explicación vive solo en un tooltip o en `title=`.
- «Datos clave» usa etiquetas visibles y chips, no «separado por comas».
