# ADR 50 — Video con efectos, por pasos: un motor sobre el Clip, efectos locales a costo 0 y un editor guiado con línea de tiempo

**Estado:** `[APROBADO — firmado por Deivid Vargas el 2026-11-20]` · redactado por principal-architect el 2026-11-20 (m-25026568, EF-00). Deivid firmó las decisiones D1–D8 y D-E1…D-E6 el **2026-11-13**. Al revisar este ADR pidió **reflejar lo construido** (2026-11-20, por medio de «creacion de tickets»). Por eso §2 dice cada decisión **como quedó en `main`**. Donde la decisión cambió, una nota guarda el texto firmado el 2026-11-13, con la fecha y el PR del cambio. El mismo día respondió las preguntas abiertas; sus respuestas están en §2 y §2.3 y se resumen en §6.3. Lo firmó solo Deivid, el 2026-11-20 («Firmar y mergear»). Lo que sigue abierto, con su ticket, está en §6 («Pendiente»). Los umbrales que reabren decisiones (§4 y §8: ~600 MiB, ~200 entradas, el 10 % de los negocios activos) los propuso el arquitecto y quedaron firmados con este ADR el 2026-11-20.
**Épica:** m-25026566 «Video automático con efectos, por pasos» · **Ticket:** m-25026568 (EF-00).
**Evidencia:** la descripción de la épica y de EF-00 en Meegle (leídas el 2026-11-20), `main` en `ab39151a` (2026-11-20), `docs/design-system.md` §5.10 y `docs/armado-local-medicion.md`.
**Numeración:** el 49 es `docs/adr-49-pipeline-imagen-carrusel.md`. Esta decisión es la **50**. El código ya la cita como «ADR 50» y por sección (§1.2 receta, §1.3 regla de modo, §1.4 biblioteca, §1.6 compatibilidad); esa numeración se respeta abajo.
**Relación con otros ADR:** se apoya en ADR 44 (plan de partes), ADR 41 (cola y `creative-worker`), ADR 47 (`media-worker` y `gallery_jobs`, donde corre el normalizador local) y ADR 49 (diseños cerrados de la capa de texto, Remotion). No enmienda ninguno; precisa F1 de ADR 44 (§3).

## 0. Contexto

Las piezas de @bianki.sc de noviembre se hicieron a mano con scripts:

- se enderezó el material de GoPro;
- se hizo la cámara rápida con ffmpeg;
- el fuego fue procedural;
- Seedance 2.5 partió de un cuadro real, con borrador en 480p y final en 1080p;
- los textos de marca se pusieron encima como capa transparente.

Deivid quiere eso dentro de Qualify, sobre el plan del video por partes (ADR 44), y **también en el Clip normal, sin obligar a pasar por partes** (Deivid, 2026-11-13): «si por ejemplo a un video solo quiero ponerle un texto y un efecto tendría que hacerlo por partes a juro y no quiero eso».

Lo que quiere el dueño: subir su video, ponerle un texto y uno o varios efectos, y recibir el video armado. Debe salir **gratis si los efectos se hacen aquí; la IA entra solo cuando el efecto la necesita**. Vale tanto para un Clip como para cada parte de un video por partes.

## 1. Decisión

**Un solo motor de efectos, por pasos, que trabaja sobre la pieza `CLIP` (con padre o sin él), y una sola pantalla de edición guiada, con estilo de línea de tiempo, que reemplaza las pantallas del Clip y de la hoja de parte.**

- Lo que se hace en el servidor con nuestro código cuesta US$0 y no descuenta cupo: preparar, cámara rápida, capas grabadas, textos con Remotion y unión.
- Seedance entra solo cuando el efecto lo necesita, y solo con efectos medidos.

### 1.1 Un motor, dos pantallas

- El motor trabaja sobre la pieza `CLIP`. Toda parte de un video por partes ya es un `CLIP` hijo (ADR 44, `content_drafts.parent_draft_id`), así que el mismo código sirve al Clip suelto y a cada parte.
- Los pasos, en orden:
  1. **Planear.**
  2. **Preparar:** girar, recortar a 9:16, elegir tramos, color con rango explícito.
  3. **Herramientas locales:** cámara rápida, capas.
  4. **Seedance**, solo si el efecto lo necesita.
  5. **Componer:** texto, capas, transiciones, unión.
  6. **Revisar:** hoja de contacto.
  7. **Final 1080p**, que se vuelve a componer con la misma receta.
  8. **Procedencia**, en los `params` del asset.
- Hoy está construido el camino `local` hasta el asset: pasos 1–3 y 5, sin transiciones. Lo demás está en §6.

### 1.2 La receta (`video_pipeline/recipe.py`)

- `recipe_of(brief)` devuelve:
  - **1 parte** para un Clip, desde su `MediaInputs`;
  - **1 parte** para un Clip hijo, desde su `media.part`;
  - **N partes** para el padre `SHOT_VIDEO`: las entradas del plan, cada una con su `transition_in`.
- `validate_recipe` devuelve **todos** los problemas como `RecipeProblem`, con código estable y sin lanzar, para que la pantalla lo llame en cada cambio. Con `tenant_id` también comprueba que cada tramo sea del negocio (`owned_by`).
- `refuse_unbuilt_recipe` / `unbuilt_recipe_problems` cierra en falso lo que el motor todavía no dibuja (`recipe_unavailable`): no se escribe, no se cobra y no se manda a Seedance.
- La receta no tiene migración. Los campos nuevos viven en el JSON del brief con valor por defecto: `PartRecipe`, `VideoRecipe`, `SourceSegment`, `text_layers`, `effects`.

### 1.3 La regla de modo (`video_pipeline/mode_choice.py`)

- Está en código, **sin LLM (US$0)**. Es pura y barata, porque la vista previa la llama en cada cambio.
- Deja un **motivo visible** (`mode_reason`) y una versión (`mode_rule_version`). El dueño puede cambiar el modo, y el cambio queda marcado (`mode_changed_by_owner`).
- Qué modo elige:

| Caso | Modo |
|---|---|
| Video propio | `local` |
| Reel sin personas, con fuente vertical editable | `edit` |
| Reel con personas, o con duda | `reference` (F6 de ADR 44) |
| Segunda mitad de un corte de más de 10 s, con el interruptor `QUALIFY_PARTS_EXTEND` de m-24880328 encendido | `extend` |
| Esa misma segunda mitad, con el interruptor apagado | `reference`, con su motivo |

- `choose_part_mode` está conectada al plan de partes (EF-09, #687). `choose_clip_mode` existe, pero todavía no la usa ninguna pantalla (§6).

### 1.4 La biblioteca de efectos (`qualify_creative/effects.py`, `effects_data/vN.json`)

- Es un **JSON versionado en el repo, sin tabla**. Cada entrada dice:
  - en qué paso actúa (`stage`);
  - su versión y sus parámetros;
  - su archivo de vista previa (`preview_asset`);
  - si se ofrece (`offered`);
  - su tasa de éxito medida (`measured`);
  - desde la v3, sus categorías cerradas.
- Una entrada **nunca se edita en su lugar**: un cambio de parámetros, de prompt o de archivo es una entrada nueva en `version + 1`. Un brief guarda la versión con la que se hizo. Hay una sola excepción documentada: la v3 ofrece las capas en versión 1 sin cambiar sus bytes.
- Los archivos de vista previa y de capa son globales, de solo lectura y van empaquetados en la imagen (`effects_assets/`). Nunca viven bajo el `t/` de un negocio ni en R2.
- Lo que trae hoy la v3:
  - **Ofrecidos:** `texto`; las capas `humo_capa`, `brasas_capa` y `vapor_capa`; las transiciones `corte`, `fundido` y `barrido`. Deivid decidió el 2026-11-20 ocultar `fundido` y `barrido` hasta EF-16 y ofrecer mientras tanto solo `corte` (D9, §2.3).
  - **No ofrecidos:** `camara_rapida`, porque la velocidad es una acción del bloque (D-T3), y las cinco plantillas de Seedance (D5).
- La **v4** hace eso: son las mismas entradas de la v3, en las mismas versiones, y solo `fundido` y `barrido` pasan a `offered: false` (su versión de entrada sigue en 1, porque no cambió nada del efecto). Elegir una de las dos es `not_offered`.
- La **v5** (EF-16, m-25026594) las vuelve a ofrecer, porque la unión ya las dibuja: agrega `fundido` y `barrido` en la **versión 2**, con `duration_s` de 0,3 a 0,8 s (el rango de la unión; la versión 1 admitía 0,2–1,5 y 0,2–1,0 s). Las entradas en versión 1 se quedan sin ofrecer, para que un brief hecho con ellas se siga leyendo. Es la biblioteca que usan las solicitudes nuevas.
- Cómo une (`video/join.py`): las dos partes **se solapan** lo que dura la transición. Los últimos cuadros de una se mezclan con los primeros de la siguiente (fundido) o la siguiente entra desde un borde (barrido), y el sonido se cruza en esos mismos milisegundos. El video dura la suma de las partes menos cada transición; los segundos cobrados son los de las partes y no cambian. Con `corte`, la unión es la de antes, byte por byte.

### 1.5 Modo local: «Tu video, con efectos»

- `PartMode` gana el modo `local`: sin Seedance y a **costo 0**, solo con video o fotos propios del negocio y sin efectos de Seedance.
- Corre en el `creative-worker` (preparación del trabajo `preview` de ADR 41), nunca en Reflex: el despachador `inline` lo rechaza.
- Las fuentes de más de 4K o de más de 8 bits se normalizan antes en el `media-worker` (ADR 47, trabajo `normalize_local` en `gallery_jobs`, revisión `0171`).
- El asset lleva `ai_generated=False` y no lleva bloque `draft`: no hay final de Seedance que pedir, así que se publica tal cual. Un Clip con un tramo hecho con IA (un video de Seedance o una imagen de Seedream del generador, o un bloque de avatar de OmniHuman) sale `ai_generated=True`: ver el §9.

### 1.6 Compatibilidad con lo guardado

- `effects_pipeline_version = 0` deja intactas las piezas anteriores.
- En un brief nuevo, el servidor sella la versión del motor **solo cuando es una receta `local` con tramos**. Cualquier otro brief queda en 0 (`effects_version_for`, `local.py`). Funciona como `prompt_compiler_version`.
- Los briefs guardados antes de la receta se siguen leyendo igual (`test_brief_fixtures_ef02.py`).

### 1.7 La pantalla: estilo de editor con línea de tiempo, **no un editor de video**

- **«Arma tu video»** es el paso 1 del Clip y está detrás de `QUALIFY_CLIP_EDITOR` (ED-02 #685, ED-10 #739, ED-03 #743, ED-04 #759). De arriba abajo tiene:
  - la vista previa en secuencia, en el navegador;
  - la línea de tiempo, con regla, cabezal y **tres pistas**: «Fotos y videos», «Textos» y «Efectos»;
  - el botón «Agregar» (Foto o video · Texto · Efecto · Pedir una idea);
  - el panel del bloque elegido, con «Listo».
- Cómo se edita en la línea de tiempo:
  - Videos y fotos se reordenan arrastrando.
  - Textos y efectos se deslizan en el tiempo con imán de ½ s y se recortan con tiradores.
  - La pista «Efectos» suma filas sola cuando dos efectos se encimarían, y un efecto pasa de una fila a otra arrastrándolo (Deivid, 2026-11-20).
  - Un video propio se recorta o se alarga dentro de su archivo con dos tiradores.
- **El estilo es el de un editor con línea de tiempo, pero no se construye un editor de video.** Quedan fuera:
  - el zoom de la línea de tiempo (D-T5);
  - los fotogramas clave;
  - el recorte cuadro a cuadro;
  - las capas libres;
  - las pistas de audio aparte;
  - los huecos o bloques encimados en la pista de video;
  - las pistas que el dueño crea a mano (no hay «+ Pista»).
- Cada acción hace una sola pregunta guiada.
- En pantalla nunca se escriben «timeline», «track», «clip», «capa», «frame», «render», «split» ni «trim».
- El patrón visual vive en `docs/design-system.md` §5.10 (ED-00b, m-25029104), que está desactualizado (§6).
- Historia de esta frontera:
  - la nota de diseño de la épica (2026-11-13) decía «sin pistas múltiples […] ni arrastre libre en el tiempo»;
  - la línea de tiempo con tres pistas y arrastre la pidió Deivid el 2026-11-14 (D-T1…D-T6);
  - las filas de efectos, el 2026-11-20 (#759).

## 2. Decisiones de Deivid, como quedaron en `main`

Cada fila dice lo que hoy hace el código. Cuando la decisión cambió, la columna «Firmado el 2026-11-13» guarda el texto original. Las respuestas de Deivid del 2026-11-20 cierran D1 y D7, mantienen en pie el cuadro del servidor de D-E1 y agregan D9 (§2.3); lo que aún no está construido figura en §6.

### 2.1 Motor

| # | Decisión, como está construida | Firmado el 2026-11-13 → cambio (fecha · PR) |
|---|---|---|
| D1 | El texto sobre el video lo dibuja **Remotion** (plantilla `video_text`): una capa PNG transparente de 1080×1920 con el mismo bloque de texto de ADR 49 (`scrim`). PyAV la pone sobre cada cuadro, con un tiempo de entrada y salida que elige el dueño (0,3–1,0 s; 0,5 por defecto). Admite hasta 3 textos por parte o Clip y funciona en piezas `local`, también en la porción mínima. Se usa la **licencia gratis de Remotion**, y `remotion_selfhost` queda en US$0,00. **Enmienda ED-13 (Deivid, 2026-11-23, m-25029108):** el texto admite **4 fondos cerrados** — «Sombra» (`scrim`, el de siempre y el que se usa si no se elige), «Franja» (`band`: franja de ancho completo ajustada al texto, ±48 px, siempre oscura y neutra —#111111 con letras blancas—, sea cual sea la marca), «Recuadro de tu color» (`brand_fill`: caja ajustada solo detrás de las letras, ±48 px y esquinas de 24 px, en el color de acento) y «Sin fondo» (`shadow`: solo las letras blancas, limpias, **sin sombra ni contorno** —Deivid, 2026-11-23, al revisar en vivo—) — **en «Franja» y «Recuadro de tu color» el dueño elige el color** (Deivid, 2026-11-23): los colores de la paleta de su Brand Kit, negro o blanco (`VideoTextLayer.box_color`, `#RRGGBB`; si no elige, el de siempre), y las letras salen blancas o casi negras (#111111), lo que contraste más; **en «Sin fondo» el dueño elige el color de las letras** con esos mismos colores (Deivid, 2026-11-23, tras ver los videos finales; `VideoTextLayer.text_color`, `#RRGGBB`; si no elige, blancas), siempre sin sombra ni contorno — y **animaciones cerradas**: al entrar «Aparece», «Sube», «Crece» o «Letra por letra» (hasta 40 caracteres, 0,06 s por letra); al salir «Desaparece», «Baja», «Se encoge» o «De golpe». Cada animación dura como máximo **un tercio** del tiempo en pantalla del texto (antes, el fundido de entrada llegaba a la mitad). El texto se dibuja con el **archivo de tipografía del Brand Kit** cuando el negocio lo subió y es una fuente válida; si no, con su familia, como antes, sin que la pieza falle. Lo dibuja `video_text` **v2**; `video_text` v1 sigue publicada y dibuja igual que antes los textos que no piden nada nuevo. Siguen siendo diseños cerrados: el dueño elige entre opciones, nunca un estilo propio. Ronda 4 (Deivid, 2026-11-23): el dueño elige el **tamaño de las letras** («Pequeña», «Mediana», «Grande»; `text_size`), «Grande» solo hasta 40 caracteres. | Firmado: «decisión de pago pendiente de Deivid», porque la licencia es gratis hasta 3 personas y el equipo es de 5. → Deivid, 2026-11-16 · #724: «usemos la free solo somos 3 personas»; confirmado el 2026-11-20: «Somos 3». **Cerrada:** se queda la licencia gratis. → Deivid, 2026-11-23 · ED-13 (m-25029108): «Sí, las 5 zonas»; 4 fondos cerrados y animaciones de entrada y salida, un tercio como máximo. |
| D2 | Humo, brasas y vapor son **bucles hechos una vez y versionados**: VP9 WebM sobre negro, generados por procedimiento con `packages/creative/scripts/make_effect_loops.py` y puestos con mezcla `screen`. Son los mismos píxeles en la vista previa y en el video final (EF-08). | Firmado: «bucles grabados con transparencia». → 2026-11-17 · #733: no salen de una cámara sino de un script, una sola vez. |
| D3 | Lo local **no descuenta cupo**, ni segundos de F1 ni vistas previas: el cobro es una fila en cero. Lo limita un **tope de 10 armados locales por negocio y por día**, que cuenta cada armado (pieza nueva y «otra versión»). El tope se cambia con `QUALIFY_LOCAL_DAILY_CAP` (`creative/local_cap.py`). | Firmado: «tope diario que sale de la medición de EF-15», con la cifra pendiente. → Deivid, 2026-11-16 · #735: «10 al día (Recomendado)», medido en `docs/armado-local-medicion.md`. |
| D4 | **Nunca `edit` cuando aparece una persona, tampoco en el video propio.** Un video propio siempre sale `local`, con efecto de Seedance o sin él; la fila `own_video_ai_effect` es inalcanzable (`mode_choice.py`). | Sin cambio. |
| D5 | Solo se ofrecen **efectos de Seedance medidos** (éxito ≥ 2/3 con n ≥ 4). Las cinco plantillas de Seedance de la v3 tienen `offered: false` y `measured: null`. | Sin cambio. |
| D6 | Banco pagado de efectos de 5 s: **≈ US$28, tope US$30**, y **solo con OK explícito de Deivid antes de correrlo** (EF-12, m-25026587). Todavía no se ha corrido. | Sin cambio. |
| D7 | **Preparar trabaja con todos los archivos del negocio:** los subidos al generador, los de la **Galería** (`gallery/…`) y los de las **Publicaciones** (decisión firmada por Deivid el 2026-11-20). Una publicación de la Galería es una sola ficha y trae todos sus archivos. Cada tramo pasa por `owned_by`. Lo ajeno queda fuera: un reel de inspiración nunca se vuelve un tramo propio. | Firmado: «Preparar solo sobre lo subido en el generador». → Deivid, 2026-11-14 · #685 (Galería y Publicaciones en el selector) y 2026-11-17 · #739 (una publicación es una ficha); firmada así el 2026-11-20. |
| D8 | **Revisa solo el dueño**, sin revisión de Claude en la fase 1. Hoy revisa el video armado, porque la hoja de contacto (EF-18) no está construida. | Firmado: «la hoja de contacto la revisa solo el dueño». La hoja está pendiente (§6). |

### 2.2 Editor

| # | Decisión, como está construida | Firmado el 2026-11-13 → cambio (fecha · PR) |
|---|---|---|
| D-E1 | Vista previa **en el navegador**, en vivo y gratis: el video como va a salir, en secuencia y con un solo reloj para todo el video, sin decodificar nada en Reflex ni en el servidor (ED-01 #683, ED-01b #722). **Más un cuadro real de cada video, que siempre saca el servidor y nunca el navegador**; llega con ED-11b (m-25029110). | Firmado: «… más un cuadro real del servidor». → Sigue en pie (Deivid, 2026-11-20); falta construirlo (§6). |
| D-E2 | La vista previa reproduce el **archivo original**: lo subido, desde el almacenamiento local, y lo que está en R2 (Galería, Publicaciones), por su ruta `/r2media/`. | Firmado: «archivo local del teléfono al subir y después una copia liviana de 480p». → La copia de 480p (ED-09) está pendiente (§6); hoy el teléfono descarga el original. |
| D-E3 | **Línea de tiempo editable en el celular y en escritorio** (D-T1…D-T6, §2.3): foto quieta de 1–5 s, hasta 3 textos, «Velocidad» como acción del bloque, un cuadro por bloque, sin zoom y, en el celular, solo arrastrar. | Firmado: «fichas “Todo · 1 · 2 · 3…” en el celular y línea de tiempo de solo lectura en escritorio». → Reemplazada por D-T1…D-T6 (Deivid, 2026-11-14) y construida en ED-10 · #739 (2026-11-17). |
| D-E4 | **«Idea» vive dentro del editor**, como la opción «Pedir una idea» de «Agregar» y como pestaña del panel lateral (#739). | Firmado: «… y el video pasa a 3 pasos». → El paso a 3 pasos (ED-06, m-25026636) está pendiente (§6). |
| D-E5 | Una parte ya creada se cambia **en el mismo editor** («Rehacer esta parte»). | Sin cambio en la decisión; falta construirla (ED-08 m-25026640, después de ED-07; §6). |
| D-E6 | Los cambios se **guardan al momento**, sin botón «Guardar», y la línea viva del editor anuncia cada uno. **No hay «Deshacer».** | Firmado: «se guarda al momento, con “Deshacer”». → Deivid, 2026-11-19 · #743: se quita «Deshacer». |

### 2.3 Otras decisiones de Deivid tomadas al construir

| Fecha | Decisión | Dónde quedó | Toca |
|---|---|---|---|
| 2026-11-14 | D-T1…D-T6 de la línea de tiempo: foto quieta de 1–5 s; hasta 3 textos y un efecto que se puede repetir; «Velocidad» es acción del bloque, no un efecto; un cuadro por bloque ya y la tira después; sin zoom; en el celular solo arrastrar | `docs/design-system.md` §5.10 | D-E3 |
| 2026-11-16 | Licencia gratis de Remotion: «usemos la free solo somos 3 personas» | #724, m-25026573 | D1 |
| 2026-11-16 | Tope de 10 armados locales por negocio y por día | #735, `docs/armado-local-medicion.md` | D3 |
| 2026-11-16 | El dueño elige el fundido de cada texto: 0,3–1,0 s, 0,5 s por defecto | #724 | D1 |
| 2026-11-16 | Categorías cerradas de efectos (comida, texto, transición, movimiento, general) para filtrar, sin ocultar nada; el editor muestra primero los del rubro del negocio | `effects_data/v3.json`, #759 | §1.4 |
| 2026-11-16 | Si la cámara rápida da un resultado de menos de 3 s o de más de 60 s, se avisa y no se crea | EF-06 | §1.5 |
| 2026-11-17 | Velocidades ×2, ×3, ×5, ×10 y ×20, cada una solo si el resultado dura 3–60 s; sin «Desde/Hasta» | #739 | D-T3 |
| Antes del 2026-11-17 (merge de #741; lo decidió el fundador, m-25042483) | Fuentes de más de 4K o de más de 8 bits: «Bajarlos a 4K 8 bits» en el `media-worker` antes del armado | revisión `0171`, #741 | §1.5 |
| 2026-11-19 | Sin «Deshacer» en el editor | #743 | D-E6 |
| 2026-11-20 | La pista «Efectos» suma filas sola; un efecto pasa de una fila a otra arrastrándolo; no hay «+ Pista» | #759 | §1.7 |
| 2026-11-20 | El equipo es de 3 personas («Somos 3»): se queda la licencia gratis de Remotion | este ADR | D1 |
| 2026-11-20 | Preparar trabaja con todos los archivos del negocio: los del generador, la Galería y las Publicaciones | este ADR | D7 |
| 2026-11-20 | El cuadro real de cada video lo saca el servidor, nunca el navegador, y llega con ED-11b (m-25029110) | este ADR | D-E1 |
| 2026-11-20 | **D9:** `fundido` y `barrido` se ocultan hasta EF-16; mientras tanto solo se ofrece `corte`. Lo hace un PR chico aparte | `effects_data/v4.json`, en este PR | §1.4 |
| 2026-11-20 | `qualify-context` (equipo de 3) y `design-system.md` §5.10 (firmada y sin «Deshacer») se actualizan en un PR aparte, solo de documentación | este ADR; PR pendiente (§6.2) | §6.2 |
| 2026-11-20 | Normalizador con `bframes=1`, no 3 (con 3 llega a 679 MiB, demasiado cerca de 768m) | #760, m-25071265 | §1.5 |
| 2026-11-23 | «Texto en pantalla»: 4 fondos cerrados (Sombra, Franja, Recuadro de tu color, Sin fondo), animaciones cerradas de entrada (Aparece, Sube, Crece, Letra por letra) y de salida (Desaparece, Baja, Se encoge, De golpe), cada una de como máximo un tercio del tiempo del texto; «Letra por letra» solo hasta 40 caracteres; la tipografía sale del archivo del Brand Kit cuando existe | ED-13 · m-25029108 (`video_text` v2, `video_text_compose-v3`) | D1 |
| 2026-11-23 | Tras revisar en vivo: «Sin fondo» va **sin sombra ni contorno** (letras blancas limpias); en «Franja» y «Recuadro de tu color» **el dueño elige el color** entre los de la paleta de su Brand Kit, negro y blanco (círculos de color bajo la opción; si no elige, el de siempre: franja #111111, recuadro en el color principal), con letras blancas o #111111 según el contraste; «Cómo entra y sale» siempre a la vista en el panel | ED-13 · m-25029108 (`VideoTextLayer.box_color`, rechazo `bad_text_box_color`) | D1 |
| 2026-11-23 | Tras ver los videos finales: en «Sin fondo» **el dueño elige el color de las letras** con los mismos círculos (paleta del Brand Kit, negro y blanco; si no elige, blancas), sin sombra ni contorno; la sombra de «Sombra» solo va con «Sombra» en la vista previa; todas las opciones del panel de texto se pliegan | ED-13 · m-25029108 (`VideoTextLayer.text_color`, rechazo `bad_text_color`) | D1 |
| 2026-11-23 | Tras revisar la ronda 3: se quita «¿En qué partes va?» del panel (el texto va del marcador al final y se ajusta arrastrando las puntas de su bloque); **el dueño elige el tamaño de las letras**: «Pequeña», «Mediana» (la de siempre, por defecto) y «Grande» (escala ×0,75 / ×1 / ×1,25 del rango del título 9:16, 112 → 76 px). «Grande» solo para textos de hasta 40 caracteres (medido con el motor de `layout.ts` y las negritas más anchas: 40 caracteres caben en 4 líneas o menos a 95 px); con un texto más largo se apaga con su motivo, y si el dueño lo alarga vuelve sola a «Mediana» y se lo dice. Campo `text_size` al final de `VideoTextLayer`, rechazos `unknown_text_size` y `text_too_long_for_large` al final; «Mediana» no cambia ningún digest ni job id | m-25029108 | D1 |
| 2026-11-24 | «Siempre más chica» (Deivid, opción A): con los rangos escalados, un texto largo salía igual en «Pequeña» y «Mediana» (84→57 y 112→76 se pisan y el render elige el mayor que cabe). Ahora el render mide primero «Mediana» para ese texto: «Pequeña» es siempre el 75 % de ese tamaño y «Grande» el 125 % (si no cabe, baja hasta el mayor que cabe, nunca menos que «Mediana» ni que 95 px). La vista previa ya los dibujaba así. Además, el panel avisa «palabra demasiado larga para la pantalla» antes del video final, con el criterio del render (`word_too_wide`: más ancha que 952 px al tamaño mínimo 57 / 76 / 95 px) | m-25029108 | D1 |
| 2026-11-24 | «Que siempre esté centrado» (Deivid): el texto va centrado en los 3 tamaños, los 3 lugares y los 4 fondos; el «Recuadro de tu color» también queda centrado en la pantalla, la «Franja» sigue de borde a borde. Lo dibuja `video_text` v2 (`layout.ts` `centred`); por eso **todo texto** se pide ahora a v2, también el de «Sombra» sin nada elegido, que cambia de job id (la imagen alineada a la izquierda de v1 no se vuelve a servir). v1 sigue publicada para lo que ya dibujó. Orden de despliegue: render antes que la app | m-25029108 | D1 |

## 3. Encaje con las reglas y los ADR firmados

| Regla / ADR | Cómo encaja |
|---|---|
| Aislamiento por negocio | Cada tramo pasa por `owned_by` (raíces `t/`, `gallery/`, `uploads/`, `generated/` y `reel-windows/` del negocio) y se copia por `ObjectGate`. `gallery_jobs` va por `tenant_session` con RLS. La biblioteca y sus bucles son globales y de solo lectura, sin datos de ningún negocio. |
| Un Postgres (ADR 31) | Ni tabla ni servicio nuevo para el motor: la receta va en el JSON del brief y la biblioteca en el repo. La única revisión de la épica, `0171`, agrega un tipo de trabajo a una cola que ya existía (ADR 47). |
| Comprar lo genérico, construir el núcleo | Seedance sigue comprado. Lo que construimos es lo barato y propio (preparar, cámara rápida, capas, texto, unión), con PyAV y el Remotion que ya teníamos. |
| Asistido, nunca autónomo | Nada se publica solo: la pieza local se aprueba como cualquier otra, y los finales de Seedance siguen la confirmación de ADR 41. D8: revisa el dueño. |
| Procedencia | En `params.local` del asset: contrato de receta, versión del motor, tabla de precios, versiones de cada paso, `sha256` de cada bucle y sonido por tramo. En cada parte, `mode_rule_version` y `mode_reason`. |
| Idempotencia | Reintentar una preparación reescribe las mismas llaves de la misma revisión. El cobro es una fila en cero por revisión. `normalize_local` usa `ON CONFLICT DO NOTHING`. El `jobId` de Remotion se deriva del contenido, como en ADR 49. |
| Trabajo caro fuera de la petición | Todo armado corre en el `creative-worker` y la normalización en el `media-worker`. Reflex solo simula en el navegador (D-E1). |
| ADR 44 F1 (cupo en segundos de Seedance) | Se precisa: una pieza o parte `local` no descuenta segundos ni vistas previas (D3); la protege el tope diario. |
| ADR 44 F6 | D4 la extiende al video propio. |
| ADR 49 | El texto usa sus diseños cerrados (hoy solo `scrim`, plantilla `video_text` v1) y su motor de capa. El carrusel queda fuera de esta épica. |
| Etiqueta de IA | `ai_generated` se lee de lo que se hizo, no del tipo de pieza: una pieza local sale `False` y una con Seedance, `True`. |

## 4. Alternativas descartadas

Los umbrales numéricos de la última columna son propuesta del arquitecto (ver Estado).

| Alternativa | Por qué no | Qué la reabriría |
|---|---|---|
| **El Clip como un `SHOT_VIDEO` de una sola parte** (todo pasa por «Video por partes») | Deivid no quiere pasar por partes para poner un texto y un efecto. Además, un padre con una sola parte duplica la unión y la aprobación de un video de un tramo. El motor sobre `CLIP` sirve a los dos casos sin eso. | Que el Clip y la parte necesiten ciclos de vida que no quepan en un solo editor. |
| **Tabla de efectos en Postgres** | Los efectos los escribimos nosotros, no los negocios. Git les da revisión y procedencia exacta, se validan una vez al cargar (como `pricing_data/`) y no piden migración ni RLS. | Efectos propios de un negocio, efectos que suba el dueño, o más de ~200 entradas *(propuesta del arquitecto)*. |
| Elegir el modo con un LLM | Costaría en cada cambio de la vista previa y no es reproducible. Una tabla de reglas da un motivo legible a US$0. | Que la regla se equivoque más de lo que acepte el golden set de EF-10. |
| Texto con Pillow o con `drawtext` de ffmpeg | ADR 49 descartó Pillow para dibujar, y dos motores de texto darían dos estilos de marca. | Que Remotion pase a ser de pago y el costo pese (D1). |
| Fuego y humo generados en cada pieza (en el servidor o con Seedance) | Gastan CPU o dinero en cada pieza. Un bucle hecho una vez se ve igual en la vista previa y en el video final. | Un efecto que dependa del contenido del cuadro (EF-13, con Seedance medido). |
| Revisión de la hoja de contacto por Claude | No hay una medición que la justifique en la fase 1 (D8). | Quejas de calidad repetidas, o una medición con errores que el dueño no ve. |
| Un editor de video completo | No es lo que necesita un dueño en el teléfono, y multiplica el costo de construirlo y de explicarlo. | Pedidos repetidos de clientes reales por algo de la lista de §1.7. |

## 5. Costo y volumen

- **Proveedor:** US$0 por pieza local (`local_video` = US$0,00 por segundo). Remotion propio cuesta US$0 mientras rija la licencia gratis (D1).
- **Servidor** `[V]` (EF-15, `docs/armado-local-medicion.md`):
  - memoria: 150–550 MiB anónimos, bajo el límite de 768m del `creative-worker`;
  - tiempo de worker por pieza: de ~2–2,5 min (1080p, a 1080×1920 desde m-25041163) a ~5–12 min (4K de celular);
  - con el tope de 10 al día: ~**1,7 h de worker por negocio y día** con 4K típico, y unas 4–5 h en el peor caso medido (5K de 112 s, ~25–30 min por pieza).
- **Seedance**, solo cuando el efecto la pide: el cupo en segundos de ADR 44 F1, sin cambios.
- **Banco de medición (D6):** ≈ US$28, tope US$30, una sola vez y con el OK de Deivid.
- **Filas:** ninguna tabla nueva. `gallery_jobs` suma, como mucho, un trabajo `normalize_local` por archivo grande.

## 6. Pendiente

### 6.1 Sin construir o sin encender

| # | Qué falta | Ticket | Decisión |
|---|---|---|---|
| 1 | Copia liviana de 480p al subir al generador. Hoy el teléfono descarga el original para la vista previa y para «Cortar». Está en curso en otra rama, todavía sin mergear. | ED-09 · m-25026643 | D-E2 |
| 2a | PR chico que oculta `fundido` y `barrido` y deja solo `corte` (D9): biblioteca v4. Antes, la v3 las ofrecía (`offered: true`) y el motor las rechazaba al crear (`recipe_unavailable`). | en este PR | D9 |
| 2b | Transiciones al unir partes. Con ellas, `fundido` y `barrido` se vuelven a ofrecer (biblioteca v5). Falta el control en el editor (ED-07). | EF-16 · m-25026594, en este PR | D9, §1.4 |
| 3 | Hoja de contacto para revisar el video antes de aprobarlo. | EF-18 · m-25026598 | D8 |
| 4 | El editor en Video por partes: fichas, modo con motivo, transiciones y orden. | ED-07 · m-25026638 | §1.1 |
| 5 | «Rehacer esta parte» desde el resultado. | ED-08 · m-25026640 | D-E5 |
| 6 | El video en 3 pasos, con «Idea» como paso del editor. | ED-06 · m-25026636 | D-E4 |
| 7 | El cuadro real de cada video, sacado por el servidor (nunca por el navegador), al lado de la vista previa. | ED-11b · m-25029110 | D-E1 |
| 8 | Texto y capas sobre una pieza hecha con Seedance (hoy se rechazan), y el final 1080p vuelto a componer con la misma receta. | EF-14 · m-25026592 | D1 |
| 9 | Efectos de Seedance: el banco pagado (con OK de Deivid), Seedance sobre lo preparado y «objeto en una zona del cuadro». | EF-12 · m-25026587, EF-11 · m-25026585, EF-13 · m-25026589 | D5, D6 |
| 10 | Golden set de modos (150 partes) y `just eval-modo-partes`. `choose_clip_mode` todavía no la usa ninguna pantalla. | EF-10 · m-25026578 | §1.3 |
| 11 | Miniaturas en la barra de «Cortar» (la tira de cuadros del servidor, D-T4). | ED-11 · m-25026650 | D-T4 |
| 12 | Texto y logo fuera del producto, según lo que muestra el video. | EF-20 · m-25026599 | D1 |
| 13 | `QUALIFY_CLIP_EDITOR` está apagado en producción. Encenderlo necesita la prueba de punta a punta con Deivid, su OK y `env-push`. Hasta entonces sigue abierto el criterio de la épica «el caso mínimo funciona en producción». | épica m-25026566 | §1.7 |

### 6.2 Documentación desactualizada

| # | Qué | Dónde |
|---|---|---|
| 14 | La §5.10 sigue diciendo «pendiente de firma» (m-25029104) aunque ya está en `main`, y todavía describe «Deshacer (sin temporizador, 10 pasos)», «+ Pista» y la pista de efectos con «una fila más si dos se pisan». Se marca como firmada y sin «Deshacer» en un **PR aparte de documentación, decidido el 2026-11-20**. | `docs/design-system.md` §5.10 |
| 15 | `qualify-context` no menciona el armado local a costo 0, el tope de 10 al día ni el editor «Arma tu video», y nombra a cinco personas en el equipo, cuando son 3. Va en el mismo **PR aparte de documentación, decidido el 2026-11-20**. | `.claude/skills/qualify-context/SKILL.md` §1–§2 |
| 16 | **Normalizador local sin ADR propio.** ADR 47 es la Galería y su `media-worker`. El normalizador local (m-25042483) corre en ese worker, pero no tiene ADR propio. | `docs/arquitectura.md` §6 |

### 6.3 Preguntas para Deivid — respondidas y firmadas el 2026-11-20

- **P1 · ¿Texto firmado o lo construido?** → «Reflejar lo construido». Es la razón de esta versión.
- **P2 · Licencia de Remotion** → «Somos 3». Se queda la licencia gratis y D1 queda cerrada.
- **P3 · Preparar (D7)** → trabaja con todos los archivos: los del generador, los de la Galería y los de las Publicaciones.
- **P4 · Cuadro real (D-E1)** → sigue en pie. Lo saca el servidor, nunca el navegador, y llega con ED-11b (m-25029110).
- **P5 · Quién firma** → solo Deivid.
- **P6 · Documentación** → `qualify-context` y `design-system.md` §5.10 se actualizan en un PR aparte, solo de documentación.
- **P7 · Transiciones** → `fundido` y `barrido` se ocultan hasta EF-16 y mientras tanto solo se ofrece `corte` (D9), en un PR chico aparte.

## 7. Consecuencias

- Hay un solo camino de código para el Clip y para la parte. Un efecto nuevo es una entrada más en el JSON y, si hace falta, un paso del motor. Lo que el motor no dibuja se rechaza antes de cobrar.
- El `creative-worker` carga CPU de verdad, no solo espera a proveedores. El tope diario y la normalización previa en el `media-worker` lo mantienen dentro de 768m.
- La vista previa y el video final usan los mismos bucles y el mismo reloj: lo que se ve gratis es lo que sale.
- La frontera «estilo de editor, no editor» se ha movido con cada decisión de pantalla: tres pistas el 2026-11-14 y filas de efectos el 2026-11-20 (§1.7). Se vigila en `design-system.md` §5.10.

## 8. Qué lo reabriría

Los umbrales numéricos marcados son propuesta del arquitecto (ver Estado).

- Que la licencia gratis de Remotion deje de cubrir al equipo real, por ejemplo si el equipo pasa de 3 personas, o que Remotion cambie sus términos (D1).
- Que un armado local pase de ~600 MiB anónimos *(propuesta del arquitecto)*.
- Que el tope de 10 al día frene a más del 10 % de los negocios activos en un mes *(propuesta del arquitecto)* (D3).
- Que un efecto de Seedance llegue a ≥ 2/3 con n ≥ 4 en el banco (D5/D6): entonces entra a la oferta como entrada nueva de la biblioteca.
- Un análisis barato del video del dueño que diga si aparece una persona (reabre D4 y la fila `own_video_ai_effect`).
- Quejas repetidas de clientes por algo de la lista de §1.7.
- Que la regla de modo falle más de lo que acepte el golden set de EF-10 (m-25026578).

## 9. Enmienda `[APROBADO — firmado por Deivid Vargas el 2026-11-25]` — bloque de avatar dentro del Clip (m-25112920, 2026-11-24)

**Estado:** `[APROBADO — firmado por Deivid Vargas el 2026-11-25]` · redactada por creative-engineer el 2026-11-24 con las decisiones de Deivid del mismo día (vía «creacion de tickets»). **Firma de Deivid:** «Firmo el §9 del ADR 50», escrito por Deivid en la sesión «quailify-deivid» el 2026-11-25. Los dos interruptores siguen apagados en todos los entornos; encenderlos es otra decisión.

**Qué cambia.** El §1.5 dice que el modo `local` es «sin IA» y que su asset lleva `ai_generated=False`. Con esta enmienda, un Clip `local` puede llevar un **bloque de avatar**: un video donde el avatar de la marca habla, hecho con OmniHuman 1.5. Si la receta del Clip toca un bloque, el video armado sale con `ai_generated=True`. Esto sigue la regla del §3 («la etiqueta se lee de lo que se hizo»).

**Cómo encaja.**

- El bloque es un borrador hijo del Clip (`parent_draft_id`, el enlace de la revisión `0119`). Su tipo es `AVATAR_VIDEO` (presentador humano) o `ANIMATED_AVATAR_VIDEO` (personaje animado). Su `part_index` solo marca su lugar bajo el Clip (1 a 6). No es una parte de un video por partes: no lleva `media.part`.
- El brief del bloque lleva `media.clip_avatar_block=True`. Lo pone solo el servidor y vive en el JSON del brief: no hay migración.
- El bloque se hace por el camino del presentador que ya existe: Seedream dibuja al presentador, Seed Speech lee el guion del dueño y OmniHuman 1.5 mueve los labios.
- Su video entra a la receta del Clip como un `SourceSegment` de tipo `video`, de 0 a su largo y a ×1 (`clip_avatar.place_block`). El armado local lo une con las fotos y los videos del dueño.
- Un bloque solo va a ×1: a otra velocidad el armado pondría silencio y se perdería la voz (m-25049580). El armado rechaza un bloque a otra velocidad o un bloque de otro video antes de leer nada.
- Cada bloque queda en `params.local.avatar_blocks` del asset del Clip: borrador, revisión, asset, proveedor, modelo y largo. El costo y el prompt quedan en las filas del propio bloque.

**La etiqueta de IA, para todos los tramos (decisión de Deivid, 2026-11-24).** Esto corrige el §1.5 aparte del avatar, y vale **aunque los interruptores del avatar estén apagados**.

- Un Clip `local` sale con `ai_generated=True` si **cualquier** tramo es imagen hecha con IA. Puede ser un video de Seedance o una imagen de Seedream del generador que el dueño eligió (P3), o un bloque de OmniHuman. Basta uno.
- Se lee de lo que se hizo (§3), en el asset del generador que dio ese archivo, nunca por la ruta. Primero cuenta lo que el propio asset anotó (`params.ai_generated`, que escriben el armado local, la unión y el final por partes). Después, su proveedor, si es un proveedor de generación (Seedance, Seedream, OmniHuman). Por último, `requires_ai_disclosure` de su borrador, que se calcula de lo que ese borrador hizo.
- Solo se buscan los archivos que guardó el generador. Las fotos y los videos que subió el dueño, los de la Galería y las ventanas de reels son suyos: no se buscan y no cuentan como IA.
- Un Clip solo con fotos y videos propios sigue en `False`.
- **La etiqueta falla hacia el lado seguro.** Un archivo que guardó el generador y no tiene fila en `image_assets` cuenta como IA: por ejemplo, la vista previa 480p de Seedance cuya fila pisó el final, un póster o el presentador de Seedream. Queda en `ai_sources` como `unknown_generated`. Hacer fallar el Clip sería peor para el dueño.
- El avatar de la marca (`t/{negocio}/brand/{marca}/avatar/…`) lo dibuja Seedream: si entra como tramo, cuenta como IA (`brand_avatar`). Los logos y demás archivos de la marca, la Galería (solo guarda lo que sube el negocio), las copias normalizadas de los videos del dueño y las ventanas de reels son del dueño.
- Cada tramo de IA queda en `params.local.ai_sources` del asset del Clip: borrador, asset, proveedor y modelo.
- Si hay archivos del generador en la receta y el armado no puede consultarlos, el Clip no se arma: nunca sale sin saber si lleva la etiqueta.
- Antes de este cambio, un Clip con un video de Seedance elegido por el dueño salía `False`. Ahora sale `True` a propósito.

**Cupo y gasto (enmienda a D3 solo para los bloques).**

- Crear el bloque no descuenta nada: escribe su fila de cobro en cero, como cualquier pieza, y con ella la cola encuentra la reserva de la generación.
- Sus segundos se descuentan del cupo de video del mes cuando se aprueba el Clip, como un clip de Seedance. El cobro queda en la fila del propio bloque, así que aprobar otra versión del Clip no lo vuelve a cobrar.
- El servidor rechaza crear el bloque si el mes no alcanza para sus segundos y los de **todos** los bloques de la marca que aún no se cobraron: no hay llamada de pago sin cupo. Cuentan todos los bloques sin cobrar cuyo Clip todavía no se aprobó, en cualquier Clip de la marca y sin importar el mes en que se crearon (un bloque del día 31 aprobado el día 1 sigue contando). Un bloque que nunca se colocó deja de contar al aprobarse su Clip o con la retención.
- **Tope diario (decisión de Deivid, 2026-11-24):** un negocio crea como máximo 3 bloques al día, en su propio día (zona horaria del negocio, como el tope de videos con fotos y videos propios). Cuentan todos los bloques creados ese día, aprobados o no. No cuenta uno que falló antes de pagar nada. El cuarto se rechaza antes de escribir nada y de cualquier llamada de pago: «Ya creaste 3 avatares hoy. Mañana puedes crear más.»
- Máximo 30 s por bloque. Se rechaza al crearlo, con el largo estimado del guion, y otra vez con la voz real, antes de pedir OmniHuman.
- Las fotos y los videos propios del dueño siguen sin descontar nada (D3).

**Interruptores.** `QUALIFY_CLIP_AVATAR_PRESENTER` y `QUALIFY_CLIP_AVATAR_ANIMATED`, apagados en todos los entornos. El servidor rechaza crear o poner un bloque de un tipo apagado. Con los dos apagados no puede existir ningún bloque, así que nada más cambia. Los borradores `avatar_video` y `animated_avatar_video` sueltos siguen igual.

**Fuera de esta enmienda.** La pantalla (m-25112921), la música y el volumen entre bloques, y la medición pagada (m-25112919).

## 10. Enmienda `[APROBADO — firmado por Deivid Vargas el 2026-11-25]`: transiciones en la unión de los bloques del Clip

**Estado:** `[APROBADO — firmado por Deivid Vargas el 2026-11-25]` · redactado por creative-engineer el 2026-11-24 (m-25114465, épica m-25026566, carril A). Firmado por Deivid el 2026-11-25.

**Interruptor:** el código está detrás de `QUALIFY_CLIP_BLOCK_TRANSITIONS`, que queda **apagado** (`off`, por defecto) en todos los entornos. La firma no lo enciende: encenderlo es otra decisión, y no se enciende hasta que la regla «uniones con avatar = solo corte» (m-25119867) esté en `main`. Apagado, el servidor rechaza cualquier transición entre bloques distinta de «Corte» con `recipe_unavailable` y el texto de «no disponible».

**Firma de Deivid:** `[x]` «Firmo el §10», escrito por Deivid en la sesión «quailify-deivid» · fecha: 2026-11-25

### 10.1 Contexto

- Hasta hoy, en un Clip normal no había transiciones: el servidor rechazaba cualquiera con `transition_on_clip`, y el armado local pegaba los bloques de «Fotos y videos» con corte.
- EF-16 (m-25026594) ya hace `fundido` y `barrido` en la unión de **partes** (`video/join.py`), pero la pantalla del Clip nunca tuvo el selector.
- Deivid lo pidió el 2026-11-24 al armar un Clip (m-25114465): entre cada dos bloques hay un punto en la línea de tiempo, y al tocarlo se elige «Corte», «Fundido» o «Barrido». Por defecto, «Corte».

### 10.2 Decisión propuesta

- **Dónde vive:** en cada bloque, `SourceSegment.transition_in`. Es una entrada de la biblioteca de etapa `transition` y dice cómo se une ese bloque con el anterior. No lleva tramo propio (`start_s`/`end_s`).
- **Corte no cambia nada:** «Corte» es `None`. Si llega `corte` explícito, se lee como `None`, y un `None` nunca se escribe en el JSON. Un Clip con solo cortes se guarda, se serializa y tiene el mismo digest que antes de este cambio.
- **Qué se dibuja:** `fundido` y `barrido` en versión 2 (biblioteca v5, 0,3–0,8 s), los mismos de EF-16. No hay clases nuevas de transición.
- **Cómo se une:** el paso local arma los bloques con corte, como siempre (`speed`). Si hay al menos una transición, corta ese video en las uniones que mezclan y lo vuelve a unir con el mismo código de EF-16 (`encode_segment`, `encode_transition`, `JoinTransition`, `concat_segments`), con un decodificador a la vez y 1 hilo. Va antes de las capas y los textos (`video_pipeline/block_join.py`). Los bloques se solapan lo que dura la transición y el sonido se cruza en esos mismos milisegundos. El Clip dura la suma de sus bloques menos cada transición (`clip_seconds`). Los textos y efectos se miden sobre ese largo. Sigue siendo costo 0.
- **Procedencia:** `params.local.transitions` guarda la versión del paso, los cuadros por segundo y cada unión mezclada (bloque, efecto, versión, tipo, duración, dirección y cuadros). `params.local.steps.block_join` guarda la versión, y la transición elegida queda también en `params.local.segments`.
- **Rangos:** los da la biblioteca, que es la única fuente (`transition_duration_range`). En la v5, `fundido` v2 y `barrido` v2 van de 0,3 a 0,8 s, con 0,5 y 0,4 s por defecto. Las entradas v1 (0,2–1,5 y 0,2–1,0 s) siguen en la biblioteca, pero no se ofrecen.
- **Holgura:** cada bloque que se une con otro debe durar las transiciones que lo comen, la de entrada y la de salida, **más 9 cuadros propios** (0,3 s a 30 fps, `BLOCK_MIN_FREE_FRAMES`). Con menos, la unión quedaba vacía o de pocos cuadros y el armado fallaba (revisión de código). Si no cabe, el servidor lo rechaza antes de crear la pieza con `transitions_longer_than_block` y el texto «El bloque N es muy corto para sus transiciones. Alárgalo, acorta sus transiciones o deja una de sus uniones con «Corte».». La pantalla puede avisar antes con `block_transition_room_s` y `block_transition_room_problems`. Si un bloque real sale un cuadro más corto que en la receta, la unión se hace con corte y queda anotado en `fallback_cuts` y en `params.local.warnings`. El video no falla. Si la unión falla por algo nuestro, el dueño lee «No pudimos hacer las transiciones de tu video por un problema nuestro…», sin cobro y con «Corte» como salida. Mientras corre, el borrador da señal de vida antes, durante (cada 60 s) y después de cada tramo, para que `reap_stale_drafts` no lo dé por muerto.

### 10.3 Qué sigue rechazado

- Una transición sobre el Clip entero o entre sus efectos: `transition_on_clip`, con el texto «Las transiciones van en la unión entre dos bloques…».
- Con el interruptor apagado: cualquier transición entre bloques distinta de «Corte» (`recipe_unavailable`).
- Una transición en el primer bloque: `transition_on_first_block`.
- Una transición en los bloques de un Clip que no se arma con fotos y videos propios (`local`), o de una parte de «Video por partes»: `recipe_unavailable` en `segments[i].transition_in`. Las partes siguen uniendo sus bloques con corte. Sus transiciones son las de la unión de partes (EF-16, ED-07).
- Una versión que la unión no dibuja (`fundido`/`barrido` v1), un efecto que no es transición, o una duración fuera de rango: `not_offered`, `transition_not_a_transition`, `param_out_of_range`.

### 10.4 Memoria

Medido el 2026-11-24 con `deploy/measure/local-video-memory.sh` (casos nuevos `blocks3_*`), `--memory 768m --memory-swap 768m --cpus 1`, amd64. Clip de 1080×1920 con 3 bloques: 20 s de 4K a ×2, 15 s de 1080p a ×1 y 20 s de 4K a ×2, o sea 35 s con corte y 33,4 s con 2 uniones de 0,8 s. Detalle en `docs/armado-local-medicion.md`.

| Caso | Pico anon MiB (tope 768) | Paso de unión, anon MiB | CPU s | Pared s | OOM |
|---|---|---|---|---|---|
| Solo cortes (referencia) | 327 | no corre | 537 | 542 | no |
| 2 fundidos de 0,8 s | **341** | 275 | 908 | 914 | no |
| 2 barridos de 0,8 s | 338 | 262 | 1053 | 1060 | no |

Lectura: el pico sigue siendo el paso `prepare` del 4K. La unión no lo sube: queda en ~275 MiB anónimos, lejos de los ~600 de §8. Lo que cuesta es el tiempo: con 1 CPU suma ~6 a 9 minutos a este Clip de 35 s, porque vuelve a codificar todo el video y lee el anterior desde el principio en cada unión. El lease del worker se renueva durante el armado (`produce_local`). En arm64 tardará más; no está medido.

Medido de nuevo el 2026-11-25 (punta `cf3d0a53`, con la búsqueda del cuadro clave, mismas condiciones), con el Clip más largo: 60 s en 8 bloques que alternan 4K a ×2 y 1080p a ×1. El latido se midió pasando a `render_local_part` un `beat` que anota la hora, como el del worker.

| Caso | Pico anon MiB (tope 768) | Paso de unión, anon MiB | CPU s | Pared s | Unión s | Hueco más largo sin latido | OOM |
|---|---|---|---|---|---|---|---|
| 2 barridos de 0,8 s (3 bloques, 33,4 s) | 333 | 259 | 1157 | 1162 | 422 | 474 s (`speed`) | no |
| 8 bloques, solo cortes (60 s) | **343** | no corre | 1378 | 1385 | — | **867 s** (`speed`) | no |
| 8 bloques, 7 uniones mezcladas (54,4 s) | 340 | 278 | 1706 | 1715 | 708 | 636 s (`speed`) | no |

Lectura: la memoria no cambia con 7 uniones (278 MiB en la unión, pico en `prepare`). El Clip más largo con 7 uniones tarda ~29 min a 1 CPU, 12 de ellos en la unión, y la unión da latido cada ≤60 s. El hueco largo está antes, en el paso `speed` (`render_speed`), que no da latidos: 14,5 min con 8 bloques y solo cortes, contra los 20 min del reaper. No lo trae esta enmienda (pasa igual sin transiciones), pero conviene un latido periódico ahí antes de medir en arm64. Detalle en `docs/armado-local-medicion.md`.

### 10.5 Consecuencias

- El Clip con transiciones se codifica una vez más entera (los segmentos de la unión, con los ajustes de `JOIN_SEGMENT_X264`). Un Clip con solo cortes no cambia: ni bytes ni tiempo.
- La pantalla del Clip (selector en la unión, accesible y a 375 px) y el lugar automático de lo nuevo en la línea de tiempo quedan para el carril de la pantalla de m-25114465.
- Esta sección se numera §10 y va después de §9 (avatar en el Clip, PR #795, ya firmado).

## 11. Enmienda `[APROBADO — firmado por Deivid Vargas el 2026-11-25]`: el avatar desde el primer «Crear» del Clip (m-25119867, opción B)

**Estado:** `[APROBADO — firmado por Deivid Vargas el 2026-11-25]` · redactado por creative-engineer el 2026-11-25 (m-25119867, épica m-25026566). Recoge las respuestas de Deivid del 2026-11-25 a las preguntas P1–P6 de `docs/contrato-avatar-primer-crear.md` §3, que llegaron por «creacion de tickets», y su decisión sobre las uniones.

**Firma de Deivid:** `[x]` «Firmo el §11», elegido por Deivid en la sesión «quailify-deivid» · fecha: 2026-11-25. Los interruptores del avatar siguen apagados: no se encienden antes del PR 2 de m-25119867.

**Qué cambia del §9.**

- **Opción B.** El dueño puede elegir hasta 3 avatares en el primer «Crear» de un Clip local. El Clip y sus bloques se crean juntos, en una sola transacción. Los bloques se hacen primero. El Clip **espera en `drafting`** hasta que todos terminan y después se arma una sola vez. Se revisan las mismas reglas del §9 antes de escribir nada y antes de pagar: interruptores, 30 s, tope diario, cupo de todos los bloques sin cobrar, cobro al aprobar y `ai_generated=True`. La opción A sigue igual.
- **P1. «Intentar de nuevo» un avatar cuenta para el tope de 3 al día.** Cada intento pagado es un avatar más del día. Se construye con `retry_block` (PR 2).
- **Tope diario en el primer «Crear».** Con 3 avatares ya creados en el día, la opción B dice: «Ya creaste 3 avatares hoy. Mañana puedes crear más. Quita el avatar para crear tu video ahora.» Es el texto del §9 más qué hacer ahora, porque todavía no hay video (decisión de Deivid, 2026-11-25). La opción A queda igual.
- **P2.** Si un avatar falló, el Clip espera **72 h** a que el dueño elija. Después falla con `avatar_block_failed` y se devuelve lo cobrado (PR 2).
- **P5.** No hay Clip hecho solo de avatares: las fotos y videos del dueño tienen que sumar **3 s o más** por sí solos.
- **P6. Cupo.** Un bloque cuyo Clip **falló** deja de contar en el cupo en ese momento. Esto completa la regla del §9, según la cual un bloque deja de contar «al aprobarse su Clip o con la retención». Se lee del estado del Clip, así que vale para las dos opciones.
- **Uniones (decisión de Deivid, 2026-11-25).** Una unión junto a un avatar solo puede ser «Corte», en las dos opciones y también en el armado. Un fundido mezclaría hasta 0,8 s del final de la voz con el tramo siguiente. El código es `avatar_join_cut_only`. La regla lee la unión de cada tramo (`SourceSegment.transition_in`, del §10) y vale con `QUALIFY_CLIP_BLOCK_TRANSITIONS` apagado o encendido: es la condición para encenderlo.

- **Efectos y textos sobre un avatar (punto 8, decidido por Deivid el 2026-11-25, según informó el coordinador; se construye en el PR 2).** «Textos sí, efectos no». Se aceptan textos sobre el tramo de un avatar. Se rechazan `humo_capa`, `brasas_capa` y `vapor_capa` cuando se cruzan con un bloque de avatar, con `avatar_block_effect`.
- **No se encienden** `QUALIFY_CLIP_AVATAR_PRESENTER` ni `QUALIFY_CLIP_AVATAR_ANIMATED` antes del PR 2. Hasta entonces, un Clip cuyo avatar falla espera para siempre.

**Fuera de esta enmienda.** La pantalla (m-25112921), la medición pagada (m-25112919) y el correo de aviso, que va en un ticket aparte.

## 12. Enmienda `[PROPUESTO]`: el personaje en su escena reemplaza al bloque de presentador (m-25128784)

**Estado:** `[PROPUESTO]` · redactada por principal-architect el 2026-11-26 (m-25128784, épica m-25026566). Recoge las decisiones de Deivid del 2026-11-26 (descripciones de m-25128784, m-25129385, m-25129386 y m-25129387 en Meegle, leídas el 2026-11-26), la medición AVESC-001 (PR #831; `docs/modelos-generativos/seedance-2-5.md`, «Prueba AVESC-001», y `pruebas.md`) y la investigación de m-25129387 sobre los datos de clientes en BytePlus (`docs/byteplus-datos-de-clientes.md`, 2026-11-26). Deivid respondió P1 a P5 el 2026-11-26 (§12.11). Solo la firma Deivid (P5 del §6.3).

**Firma de Deivid:** `[ ]` «Firmo el §12» · fecha: ____

**Evidencia:** `main` en `f9e784b7` (2026-11-26): `qualify_api/creative/clip_avatar.py` (§9 y §11 construidos: `ClipAvatarPlacement`, `fit_plan`, `avatar_join_cut_only`, tope diario, espera de 72 h), migración `0186_clip_avatar_failure_mails` (correo de falla, m-25120319), tabla de precios `v10` y `pesos-creaciones-v3`. Las cifras marcadas «calculado» salen de la tabla `v10` y son `[V]`; las marcadas `[H]` son estimaciones.

### 12.1 Qué cambia

**Antes (§9 y §11).** El avatar era un **presentador**: un bloque propio dentro del Clip, a pantalla completa, hecho en tres pasos (Seedream dibuja, Seed Speech pone la voz, OmniHuman 1.5 mueve los labios), que se **insertaba entre** dos tramos del dueño y alargaba el video.

**Ahora.** El avatar es un **personaje** que actúa y habla **dentro de una escena** con el fondo y el producto del negocio: toma el producto, lo muestra, lo come y dice su línea con los labios sincronizados. La escena la hace **Seedance 2.5 omni en una sola tarea** con tres imágenes de referencia (personaje, producto, fondo) y la línea entre comillas. No hay paso de voz ni de labios aparte.

- **Se reemplaza del §9:** el camino del bloque (Seedream + Seed Speech + OmniHuman 1.5, `AVATAR_BLOCK_REQ_KEY`), el tope de 30 s por bloque y la idea de un bloque que se **inserta** y alarga el Clip.
- **Se reemplaza del §11:** la ubicación del bloque entre tramos (`ClipAvatarPlacement(at)`) y su encaje en `fit_plan`, que movía los textos y efectos al alargarse el video.
- **Sigue valiendo, sin cambios, ahora para las escenas:**
  - el hijo del Clip (`parent_draft_id`, revisión `0119`), con su lugar en `part_index` y sin `media.part`;
  - `ai_generated=True` en el Clip que lleva una escena, con la regla del §9 («se lee de lo que se hizo») y su lado seguro;
  - el cobro al aprobar el Clip, en la fila del propio hijo, para que aprobar otra versión no cobre dos veces;
  - el rechazo antes de pagar si el mes no alcanza para los segundos de **todas** las escenas sin cobrar de la marca, y el fin de esa cuenta al aprobarse, al fallar (P6 del §11) o con la retención;
  - el tope de **3 por negocio y por día**, en el día del negocio, con «Intentar de nuevo» contado como una más (P1 del §11);
  - el Clip que espera en `drafting` a sus hijos (P4 del §14 de `docs/diseno-video-por-planos.md`) y las **72 h** para elegir si uno falla, después `avatar_block_failed` y devolución (P2 del §11);
  - **3 s o más** de material propio del dueño a la vista (P5 del §11);
  - «**Textos sí, efectos no**»: se aceptan textos sobre la escena; `humo_capa`, `brasas_capa` y `vapor_capa` se rechazan si se cruzan con ella;
  - el correo de falla de m-25120319 (PR #828, migración `0186`), que también sale cuando falla una escena.
- **Cambia:**
  - el largo: **5 a 10 s enteros** por escena, en vez de hasta 30 s;
  - la escena **no alarga** el Clip: ocupa una ventana del tiempo y **reemplaza** lo que el dueño tenía en esos segundos;
  - el borrador es de 480p y el final de 1080p se hace al aprobar (§12.4);
  - las uniones junto a la escena: la entrada admite cualquier transición y la salida, solo «Corte» (§12.6).

### 12.2 La receta en el Clip

- **Una pista nueva, «Personajes»**, en el brief del Clip (`media.character_scenes`, en el JSON del brief). Cada aparición es un ítem: `character_id`, `product`, `background`, `line`, `start` y `duration`. Esta pista la escribe el editor; el servidor la valida entera antes de escribir una fila o de pagar.
- **Cada aparición es una escena propia:** un borrador hijo del Clip, de un tipo nuevo `CHARACTER_SCENE` (`character_scene`). Se descarta reusar `AVATAR_VIDEO` o `ANIMATED_AVATAR_VIDEO`: esos tipos llevan al productor por el camino del presentador. El tipo nuevo amplía `ck_content_briefs_kind` en una migración reversible, con el siguiente número libre (hoy `0187`; m-25129385 también pide una: se numera la que llegue primero a `main`).
- **El tramo:** la escena ocupa `[start, start + duration)` del Clip. En esos segundos se ve la escena y suena **su** audio: lo del dueño que caía ahí no se muestra y su sonido se calla. La línea de tiempo no se corre: el Clip dura lo mismo que sin la escena. Si el video real de la escena sale unos cuadros más corto que lo pedido (AVESC-001: 4,96 s de 5), el último cuadro se sostiene; no falla.
- **Validaciones, todas antes de escribir nada y de pagar:**
  - `duration` entera de 5 a 10 s;
  - máximo **3 escenas por video**;
  - una a la vez: dos escenas no se cruzan en el tiempo;
  - ninguna pasa del final del video principal;
  - máximo **3 escenas por negocio y por día** (el tope del §9, que ahora cuenta escenas);
  - la línea cabe en la escena: como máximo `15 × (duration − 2,5)` caracteres, o sea 37 a 5 s, 82 a 8 s y 112 a 10 s. `[H]`: sale de AVESC-001, donde el personaje empezó a hablar entre el segundo 2,0 y el 5,9 y leyó a unos 14 caracteres por segundo; las líneas de más de 55 caracteres no se midieron.
- **Lo que no cambió no se paga de nuevo.** Al editar un Clip y volver a «Crear», una escena con las mismas entradas (personaje, producto, fondo, línea y largo) se reusa. Su clave de pedido es el resumen de esas entradas, así que no se pide otra tarea ni se cuenta otra vez en el tope.

### 12.3 Las entradas

| Entrada | De dónde sale | Regla |
|---|---|---|
| Personaje (`character_id`) | Un personaje guardado del negocio (m-25129385). El dueño lo describe, Seedream dibuja 2 o 3 opciones y él elige una. Máximo 5 por negocio, con `tenant_id` y RLS. | El personaje solo vale si lo generó **Seedream 5.0 en nuestra cuenta, sin editar y hace menos de 30 días** (`docs/byteplus-datos-de-clientes.md` §1.4). Por eso el dibujo viaja **byte a byte**, sin recortar ni recomprimir. El personaje realista se ofrece desde el primer día y se dibuja desde una descripción. Pasados 30 días, se redibuja como dice P5 (R7). Seedance nunca recibe una foto de una persona real ni un personaje hecho con otra herramienta. Dibujar el personaje a partir de una foto real queda como opción pendiente de medición (§12.12). |
| Producto (`product`) | Un producto del Catálogo y una de sus fotos. | Va como referencia; no se dibuja de nuevo. |
| Fondo (`background`) | Una foto del local que subió el dueño, o un fondo que el dueño describe y Seedream dibuja. | Al dibujar un fondo, el prompt pide «sin carteles ni letras» (R6). |
| Línea (`line`) | La escribe el dueño, o la sugiere Claude Haiku con «Sugerir con IA» (m-25129386, gratis, hasta 10 por escena y por día). | Los nombres en inglés se escriben como se pronuncian (R2). La aprueba el dueño: nunca se usa una línea que no vio. |

### 12.4 Resolución, cobro y cupo

- **Borrador:** al «Crear», cada escena se hace en **480p** (480×854, 24 cuadros por segundo, 9:16), con audio. El Clip borrador se arma a 1080×1920 con la escena agrandada: se ve más suave, y eso es lo esperado en un borrador. **No descuenta segundos de video.** **Descuenta 1 vista previa del mes** por escena, como cualquier video de Seedance (D7 de `docs/diseno-video-por-planos.md`). La vista previa se devuelve si BytePlus no entrega nada (P2). Si al dueño no le quedan vistas previas, la escena se rechaza antes de pagar nada. Una escena que se reusa sin cambios (§12.2) no descuenta otra.
- **Final:** al aprobar el Clip, cada escena se regenera en **1080p** desde su borrador (`draft_task_id`, como el final de Seedance de hoy) y el Clip se vuelve a armar con los finales. El final puede salir un poco distinto del borrador. El Clip queda «listo» con los finales y el dueño lo ve antes de programarlo: nada se publica solo.
- **Cupo:** los segundos **pedidos** de cada escena (5 a 10) se descuentan del cupo de segundos de video del mes al aprobar, una sola vez, como una parte de Seedance (§13.5 de `docs/diseno-video-por-planos.md`). Si falla el final de una escena, vuelven sus segundos (D9 de ese documento), sale el correo de falla y el Clip queda aprobado y esperando ese final, con «Intentar de nuevo».
- **Guarda de precio:** cada tarea de Seedance (borrador y final) y cada dibujo de Seedream pasan por la guarda de precio, con la tabla vigente, y dejan su evento de uso con el costo en `creative_usage_events`.
- **Idempotencia:** el pedido de la escena lleva su clave (§12.2); el final lleva la clave `(escena, revisión)`, así que aprobar dos veces o reintentar no genera ni cobra dos veces.
- **Fuera del pedido web:** borradores y finales corren en el `creative-worker` (ADR 41), una tarea a la vez por escena.

**Costo por escena** (tabla `v10`; borrador medido en AVESC-001, final calculado):

| Largo | Borrador 480p (medido) | Final 1080p (calculado, 11,70 US$/M × 48.600 tokens/s) | Escena aprobada |
|---|---|---|---|
| 5 s | US$0,52 | US$2,84 | US$3,36 |
| 8 s | US$0,83 | US$4,55 | US$5,38 |
| 10 s | US$1,03 | US$5,69 | US$6,72 |

- El personaje se dibuja una vez: 3 opciones × US$0,045 = **US$0,14** (m-25129385).
- **Con el cupo del plan Básico** (40 s al mes): los finales cuestan como mucho 40 × 0,569 = **US$22,7** al mes, dentro del techo de §13.5 de `docs/diseno-video-por-planos.md`.
- **Peor caso de borradores sin aprobar** (calculado). Sin descontar vista previa, el tope de 3 al día permitía 90 borradores de 10 s al mes: **US$92,7 por negocio y mes**, por encima del techo de ≈ US$61 del Básico. Con la vista previa (P2), los borradores quedan bajo las vistas previas del plan, que se comparten con los demás videos de Seedance: Básico 20 × US$1,03 = **US$20,6**, Plus 40 → **US$41,2** y Pro 80 → **US$82,4** al mes. Esto cabe en los techos del §13.5 de `docs/diseno-video-por-planos.md`, que ya cuentan esas vistas previas.
- **Tiempo:** 67 a 78 s por borrador (AVESC-001); el final, 38 s medidos y 60 s para planificar (SD25-002, n = 1, sin referencias). Un Clip con 3 escenas espera unos 4 min antes de armarse.
- **Filas:** como mucho 3 hijos por Clip y 3 al día por negocio; ≤ 1.100 borradores de escena por negocio y año. Ninguna tabla nueva aparte de la de personajes (m-25129385).

### 12.5 Interruptores y tipos actuales

- **Interruptor nuevo (P3, decidido):** `QUALIFY_CLIP_CHARACTER_SCENE`, **apagado** en todos los entornos (`.env.example`, `deploy/.env.prod.example`). Cubre **la escena, los personajes guardados (m-25129385) y «Sugerir con IA» (m-25129386)**. Apagado, el servidor rechaza los tres antes de leer nada, con `switched_off` y el texto de «todavía no está disponible».
- **`QUALIFY_CLIP_AVATAR_PRESENTER` y `QUALIFY_CLIP_AVATAR_ANIMATED`** siguen apagados y no se encienden. El camino del bloque de OmniHuman en el Clip queda sin uso.
- **Se elimina** `ClipAvatarPlacement(at)` del brief (m-25128784). **Lo demás del camino de OmniHuman en el Clip** (`place_block`, `clip_avatar_block`, `AVATAR_BLOCK_REQ_KEY` y la ruta del presentador en el Clip) **se retira en un ticket de limpieza después de que la escena esté en `main`** (P4, decidido). Los borradores sueltos no entran en esa limpieza.
- **Lo que se reusa del código del §9 y del §11:** el tope diario, la cuenta de lo que falta cobrar, la espera en `drafting`, las 72 h, `retry_block`, el correo de falla y la regla de efectos sobre el tramo.
- **Los borradores sueltos** `avatar_video` y `animated_avatar_video` no cambian.

### 12.6 Uniones junto a la escena

El §11 dejó «solo Corte» junto a un avatar (`avatar_join_cut_only`) porque un fundido mezclaba hasta 0,8 s del final de la voz con el tramo siguiente. m-25128784 pedía **eliminar** esa regla y aceptar cualquier transición. La medición muestra que el riesgo **sigue a la salida, no a la entrada**:

- **Entrada:** en las 6 escenas el personaje empezó a hablar en el segundo 2,0 o después. Un fundido o un barrido de hasta 0,8 s no toca la voz.
- **Salida:** en las escenas de 5 s la línea terminó en el segundo 4,7. Un fundido de 0,8 s se come la última palabra.

**Decisión de Deivid (2026-11-26, P1):** la **entrada** de la escena admite **cualquier transición** y la **salida**, **solo «Corte»**. `avatar_join_cut_only` se reemplaza por esta regla, que se lee de `SourceSegment.transition_in` del tramo que sigue a la escena. La regla vale con `QUALIFY_CLIP_BLOCK_TRANSITIONS` apagado o encendido.

### 12.7 Procedencia

Cada escena queda en `params.local.character_scenes` del asset del Clip:

- borrador, revisión y asset de la escena;
- proveedor `seedance`, modelo `dreamina-seedance-2-5-260628` y versión del prompt (`personaje-escena-v1`, que sale de `avatar-escena-v1` de AVESC-001);
- `character_id`, más el asset y el modelo de su dibujo (`dola-seedream-5-0-pro-260628`);
- el producto (id y clave de la foto) y el fondo (clave de la foto o asset del dibujo);
- la línea, y si la sugirió la IA (con la versión de su prompt, m-25129386);
- segundos pedidos y reales, ids de las tareas de borrador y de final, y su costo.

Además, `ai_sources` anota la escena como `character_scene`. El personaje guardado lleva su propia procedencia en su fila (m-25129385): la descripción del dueño, el modelo y la versión del prompt.

### 12.8 Riesgos de AVESC-001

| # | Riesgo | Qué se hace | Estado |
|---|---|---|---|
| R1 | **La voz no se controla:** cada escena inventa la suya, y el mismo personaje puede sonar distinto en dos escenas del mismo Clip. | Se acepta para empezar. El dueño oye el borrador antes de aprobar. Elegir o clonar la voz queda fuera (m-25128784). | Aceptado; se reabre (§12.10) |
| R2 | **Pronunciación** de nombres en inglés («Nibbles», «super smash») y de algún fonema: 3 de 6 con dudas. | La línea se escribe como se pronuncia. «Sugerir con IA» lo hace solo (m-25129386) y el editor lo recuerda junto al campo. | Mitigado |
| R3 | **Volumen:** la voz del personaje animado sale unos 5 dB más baja. | El armado local normaliza el volumen de cada escena (costo 0, en el mismo paso que la une). | A construir en m-25128784 |
| R4 | **Escala y forma del producto** cambian (producto enorme, grieta en el pan). | El prompt pide el tamaño real en la mano. El dueño revisa cada escena en el borrador y puede repetirla (cuenta para el tope). | Aceptado, con revisión humana |
| R5 | **Saturación al masticar** y **la mano que no gira con el producto** en el animado (Deivid). | Se aceptan en el borrador. Un prompt `personaje-escena-v2` se mide con `qualify-measure` antes de cambiarlo. | Aceptado |
| R6 | **Letras falsas** en el fondo dibujado. | El fondo dibujado se pide sin carteles ni letras. | Mitigado |
| R7 | **Personaje de más de 30 días:** Seedance 2.x rechaza caras humanas reales. Solo acepta como personaje una salida de Seedream 5.0 de nuestra cuenta, sin editar y de menos de 30 días. Un personaje de otra herramienta, editado o más viejo puede ser bloqueado (`docs/byteplus-datos-de-clientes.md` §1.4). | El dibujo se guarda intacto y con su fecha. Pasados 30 días, la primera vez que el dueño usa el personaje ve «Tu personaje necesita un dibujo nuevo» y elige entre 2 o 3 redibujos hechos desde su descripción guardada (≈ US$0,14, sin descontar cupo). El dibujo nuevo no sale idéntico; por eso lo elige el dueño (P5). | Decidido (P5) |
| R8 | **Sin probar:** el final 1080p desde un borrador omni con referencias y audio, la foto real del local y la repetición (una muestra por casilla). | Una medición pagada de un final, con el OK de Deivid (≈ US$2,84 a 5 s), antes de encender. | Condición C2 |
| R9 | **El momento de la línea** no se controla (en 10 s habla en la segunda mitad). | Tope de caracteres por largo (§12.2). | Mitigado en parte |
| R10 | **Ruta de datos de BytePlus para las fotos del cliente** (producto, local), según `docs/byteplus-datos-de-clientes.md` §1.1 a §1.3. El endpoint está en **Johor (Malasia)** y el procesamiento puede pasar a **Indonesia o a la UE**. Las entradas y salidas que **marca el filtro** de contenido se guardan **180 días**. BytePlus **entrena** con los datos solo si el modelo está inscrito en la **«Colaboración de datos»**, que es una **cesión perpetua** e irreversible. No hay plazo publicado para las entradas de una tarea normal. | Ningún modelo que reciba datos de clientes puede estar inscrito en la «Colaboración de datos». Lo prueba una captura de la consola (C1). | Condición C1 |
| R11 | **Condiciones de video para plataformas** (Service Specific Terms › Model Services §4.2): prohíben ofrecer el video en «herramientas de creación de contenido con IA», con una penalidad del 10 al 20 %. No se sabe si Qualify entra en esa categoría (`docs/byteplus-datos-de-clientes.md` §1.5). Es una puerta de una vía: el riesgo es perder la cuenta y pagar la penalidad. | Respuesta escrita de BytePlus antes de ofrecerlo a clientes externos (C1). Ya se le pasó a Deivid. | Abierto; puede cambiar la decisión |
| R12 | **Venezuela no está** entre los países del servicio, y esa lista también vale para nuestros usuarios finales (`docs/byteplus-datos-de-clientes.md` §1.5). | No se generan escenas para negocios de Venezuela hasta que BytePlus responda por escrito (C1). Ya se le pasó a Deivid. | Abierto; puede cambiar la decisión |

### 12.9 Condiciones antes de encender `QUALIFY_CLIP_CHARACTER_SCENE`

Firmar el §12 no enciende nada. Para encenderlo con clientes hace falta:

- **C1 · Ruta de datos de BytePlus** (m-25129387, `docs/byteplus-datos-de-clientes.md`, 2026-11-26). Lo que se sabe está en R10, R11 y R12. La recomendación sale del §5 de ese documento:
  - Encender **solo para los negocios del fundador en Colombia y Uruguay**, y solo **después de una captura de la consola** que muestre que ningún modelo que recibe datos de clientes (Seedance, Seedream, OmniHuman, Seed Speech) está inscrito en la «Colaboración de datos». La captura se guarda junto a ese documento, con su fecha.
  - Los **clientes externos** y **Venezuela** esperan una **respuesta escrita de BytePlus** a las preguntas 1 (§4.2, «herramientas de creación de contenido con IA») y 2 (Venezuela) del §4 de ese documento.
  - Dos reglas del mismo documento: nunca se pide el diagnóstico de BytePlus sobre una tarea con datos de clientes, porque esos datos pueden ir a China; y el aviso de privacidad y los términos nombran a BytePlus como subencargado.
  - **Deivid revisó la conclusión:** `[ ]` · fecha: ____
- **C2 · Final 1080p medido** (R8): un final desde un borrador omni con referencias y audio, pagado con el OK escrito de Deivid y anotado en `docs/modelos-generativos/seedance-2-5.md`. Confirma que los labios y la voz se mantienen y que el costo es el calculado.
- **C3 · Prueba de punta a punta con Deivid**, su OK y `env-push`, como el resto de los interruptores de este ADR.

Mientras falte la captura de la consola, el interruptor solo se enciende en local. Con la captura, se enciende para los negocios del fundador en Colombia y Uruguay. Con la respuesta escrita de BytePlus, se enciende para clientes externos y, si la respuesta lo permite, para Venezuela.

### 12.10 Alternativas descartadas y qué lo reabriría

| Alternativa | Por qué no |
|---|---|
| Camino B: OmniHuman + Seed Speech, el presentador del §9 | No hay llaves para medirlo, y pone al presentador **fuera** de la escena: no toma ni come el producto. |
| Dos pasos: Seedream dibuja el cuadro (personaje + producto + fondo) y después Seedance lo anima con la voz | Paga dos llamadas y suma un dibujo intermedio que el dueño no pidió. La tarea omni hizo las 6 escenas en un solo paso. |
| Mantener el presentador del §9 (pantalla completa o círculo en una esquina) | Deivid lo descartó el 2026-11-26. |
| Reusar los tipos `AVATAR_VIDEO`/`ANIMATED_AVATAR_VIDEO` con una marca en el brief | Ahorra una migración de una línea, pero arriesga que el productor tome el camino del presentador. |

**Lo reabre:**

- que BytePlus permita fijar o clonar la voz en Seedance, o que lleguen las llaves de OmniHuman y Seed Speech (R1);
- quejas repetidas de clientes por la voz distinta entre escenas;
- que más de 1 de cada 4 finales salga distinto de su borrador, a juicio del dueño o de Deivid;
- que BytePlus rechace más de 1 de cada 10 referencias de personaje (R7);
- la respuesta escrita de BytePlus sobre §4.2 y Venezuela (R11, R12): si dice que no, la escena no se ofrece a clientes externos o en Venezuela;
- que el tope de 3 al día frene a más del 10 % de los negocios activos en un mes (umbral del §8);
- que la conclusión de m-25129387 sea «no se puede»: entonces la escena solo usa fondos y productos dibujados, o se cambia de proveedor (fuera de esta enmienda).

### 12.11 Preguntas para Deivid — decididas por Deivid el 2026-11-26

Las cinco llegaron por «creacion de tickets» el 2026-11-26. Cada una dice cómo quedó y dónde se aplica.

- **P1 · Uniones junto a la escena → decidida.** La entrada de la escena admite cualquier transición; la salida, solo «Corte». Ver §12.6.
- **P2 · Vista previa → decidida: sí.** El borrador de una escena descuenta 1 vista previa del mes, y se devuelve si BytePlus no entrega nada. Ver §12.4. Con eso, el peor caso en borradores baja de US$92,7 a US$20,6 al mes en el Básico.
- **P3 · Interruptor → decidida: uno nuevo.** `QUALIFY_CLIP_CHARACTER_SCENE` cubre la escena, los personajes y «Sugerir con IA». Ver §12.5.
- **P4 · OmniHuman en el Clip → decidida.** Se retira en un ticket de limpieza después de que la escena esté en `main`. Ver §12.5.
- **P5 · Personaje realista → decidida.** Se ofrece desde el primer día y se dibuja desde una descripción. Pasados 30 días, la primera vez que el dueño usa el personaje ve «Tu personaje necesita un dibujo nuevo» y elige entre 2 o 3 redibujos (≈ US$0,14, sin descontar cupo). Ver R7.

### 12.12 Opción pendiente de medición: el personaje realista dibujado a partir de una foto real

**Estado:** `[PENDIENTE DE MEDICIÓN]`. **No se construye todavía.** La pidió Deivid el 2026-11-26. Si la medición sale bien, entra con su propia enmienda o con una línea firmada en este §12.

**Qué es.** El dueño sube la **foto de una persona real que le dio su permiso por escrito**. Seedream dibuja el personaje a partir de esa foto, y **ese dibujo es lo único que va a Seedance**. Seedance nunca recibe la foto. El dibujo intermedio de Seedream es lo que lo hace posible: Seedance rechaza caras humanas reales y solo acepta salidas propias de Seedream (§12.3, R7).

**Medición** (con `qualify-measure` y el OK escrito de Deivid antes de pagar):

- **Muestra:** unas **3 fotos** de personas que dieron su permiso por escrito.
- **Costo** `[H]`: unos **US$3**. Por foto: 2 o 3 dibujos de Seedream (≈ US$0,14) y una escena de 5 s en borrador (≈ US$0,52). Son ≈ US$2,0 en total, más margen para repetir.
- **Qué mide:**
  1. si Seedream acepta la foto y dibuja el personaje, o si la rechaza (por ejemplo, con el filtro de figuras públicas);
  2. si Seedance acepta ese dibujo como referencia. Es la pregunta clave: `docs/byteplus-datos-de-clientes.md` §1.4 nombra salidas de Seedream 5.0 **texto a imagen**, y un dibujo hecho desde una foto es **imagen a imagen**;
  3. **qué tanto se parece** el personaje a la persona, a juicio de Deivid y de la persona de la foto.
- Se anota en `docs/modelos-generativos/` el mismo día, como AVESC-001.

**Permiso:**

- El permiso escrito de la persona de la foto, como `avatar_rights_confirmed` en el código de hoy (`AvatarBlockRequest`). Queda guardado en la fila del personaje, con la fecha.
- Para clientes, suma una **casilla de consentimiento** antes de subir la foto: el dueño confirma que tiene el permiso escrito de esa persona. El texto de la casilla pasa por `qualify-copy-es`.

**Riesgo: caras de personas reales en BytePlus.** Hay que cruzarlo con `docs/byteplus-datos-de-clientes.md`:

- **§1.4:** Seedance 2.x rechaza caras reales y solo admite tres caminos: personajes de la biblioteca, salidas propias de Seedream o de Seedance, o una persona real que verificó su identidad con su propia cuenta. Somos responsables de tener los derechos sobre la imagen de la persona (AI Terms §1.2 y §1.8). Si el dibujo se parece a una figura pública, el filtro bloquea la salida.
- **La foto sí llega a BytePlus**, aunque sea a Seedream y no a Seedance. Le aplican los mismos riesgos de datos de R10: Johor (Malasia), con paso posible a Indonesia o a la UE; 180 días si la marca el filtro; ninguna cesión siempre que el modelo no esté inscrito en la «Colaboración de datos».
- **§2 de ese documento:** una cara es un dato personal. En Colombia es un dato **biométrico sensible** si se usa para reconocer a alguien. En Uruguay, el consentimiento tiene que ser informado y cubrir el envío al exterior. El permiso escrito tiene que decir que la foto va a BytePlus y para qué se usa.
- **La regla de §12.3 no cambia:** Seedance no recibe fotos de personas reales. Esta opción solo manda a Seedance el dibujo de Seedream.
- **Condiciones:** las mismas de §12.9 (C1 a C3), más la medición de arriba y el texto del permiso revisado.

**Fuera de esta enmienda.** La pantalla (m-25112921), crear y guardar personajes (m-25129385), «Sugerir con IA» (m-25129386), la captura de la consola y la respuesta escrita de BytePlus (m-25129387), construir el personaje desde una foto real (§12.12, pendiente de medición), elegir la voz y encender cualquier interruptor.
