# Auditoría de prompts de «Clip» (Seedance 2.5) tras el compilador v1 — 2026-11-03

> Estado: terminado (creative-engineer, 2026-11-03). Investigación de solo lectura: sin llamadas
> pagadas, sin cambios de código, sin commit. Ticket de contexto: m-24820842.

## 1. Alcance y fuentes

- Queja del fundador: los prompts de las piezas «Clip» (Seedance 2.5: clip de movimiento y
  réplica de reel) perdieron calidad desde el trabajo del compilador v1
  (`MediaInputs.prompt_compiler_version`).
- Código auditado: copia fija tomada a las 12:32 del 2026-11-03 de
  `packages/api/src/qualify_api/creative/media.py`,
  `packages/api/src/qualify_api/creative/brand_references.py`,
  `packages/creative/src/qualify_creative/{prompt_text.py,scene_plan.py,schemas.py}` y
  `packages/api/tests/prompt_quality.py`. Otro agente editaba `media.py` y `scene_plan.py`
  en paralelo; los números de línea de este informe son los de esa copia. Esos archivos
  eran idénticos a los de la copia principal (`Qualify/`), que es la que sirve el servidor
  de desarrollo y escribió `reflex.log`.
- Tres versiones del código, reconstruidas fuera del repositorio:
  - **base** = `56746531` (`main`, antes de todo el trabajo de recursos de marca de
    m-24820842);
  - **HEAD** = `5048b047` (la rama, sin los cambios sin commit del compilador v1);
  - **actual** = el árbol de trabajo (compilador v0 y v1).
- Mismas entradas en las tres: el caso real de Nibbles' Burgers que aparece en el log, más
  la fixture anonimizada `packages/api/tests/fixtures/clip_edit_budget_real_20261102_anonymized.json`
  para la réplica.

## 2. Prompts reales recogidos de `reflex.log`

`reflex.log` solo contiene el 2026-11-03, de 11:35 a 12:27. **Todos los prompts que tiene
son del compilador 1. No hay ningún prompt «de antes» en el log.** El «antes» sale de la
reconstrucción del §3.

| Borrador | Ruta | Referencias | Tamaño | Compilador |
|---|---|---|---|---|
| `cfde8564` | clip de movimiento (`clip_reference_mode=motion`) | fotograma inicial y final (Image 1 y 2), 1 video, **0 recursos de marca**, audio sí | 2289 c / 361 p | 1 |
| `ddfcafc9` | clip de movimiento | fotograma inicial y final, 1 video, 1 logo (imagotipo, Image 3), audio no | 2967 c / 463 p | 1 |
| `320257e3` (diapositiva 2/3) | diapositiva animada, sin video de referencia | `first_frame` + isologo nombrado | — | 1 |

- **No hubo ninguna réplica de reel en el log** (`clip_reference_mode=edit` solo se activa si
  el video viene de «Descubrir reels», `Qualify/creative_state.py:3905`). Los dos «Clip» del
  log usan un video subido como guía de movimiento. La réplica se audita solo con la
  reconstrucción.
- Las dos copias de Claude (`PROMPT → Claude (copy)`) piden: «no words on screen: the visuals
  carry it» y tres tomas. Claude escribe las tomas **sin ver** los fotogramas ni el video de
  referencia.

## 3. Reconstrucción offline v0 vs v1 (y frente a `main`)

Script de lectura fuera del repositorio. Llama a `clip_prompt` de cada árbol con las mismas
entradas. Cuando el v0 rechaza por pasar 2950, se vuelve a compilar sin tope para poder leer
el texto completo.

**Validación:** la reconstrucción del clip `ddfcafc9` con el compilador 1 es **idéntica byte
a byte** al prompt del log (2967 c / 463 p).

**v0 actual = HEAD:** idéntico byte a byte en los 5 escenarios. La promesa «v0 igual que
antes» se cumple.

| Escenario | base (`main`) | v0 (= HEAD) | v1 |
|---|---:|---:|---:|
| A. Fotogramas 1+2 + video + 1 logo (= `ddfcafc9`) | 1805 c / 319 p, sin logo | 2931 c / 451 p (**tomas recortadas**) | 2967 c / 463 p |
| B. 2 fotos de producto + video + 1 logo | 1838 c / 325 p, sin logo | 2931 c / 453 p (tomas recortadas) | 2944 c / 460 p |
| C. 2 fotos + video + 3 logos, sin tomas | — | 2935 c / 449 p | 2793 c / 430 p |
| D. Réplica (fixture), 1 foto + imagotipo | 2498 c / 382 p (recortada, sin logo) | **rechazada** (2966 > 2950); sin tope: 3475 c / 505 p | 2869 c / 407 p |
| E. Réplica, 2 fotos + 3 logos | — | rechazada; sin tope: 3711 c / 532 p | 3031 c / 427 p |
| F. Réplica con «textos de marca» | — | — | 3121 c / 447 p |

### 3.1 Clip de movimiento: lo que cambia de v0 a v1 (frase por frase)

1. **Tomas: v0 las cortaba a mitad de frase; v1 las manda enteras.** Antes (v0, `ddfcafc9`):
   `Shot 1 (0-2 s): "…sobre la plancha humeante; los bordes chisporrotean".` Después (v1):
   `…los bordes chisporrotean y se doran al instante formando la costra.".` La toma 3 v0
   perdía «en la fachada desenfocada al fondo», es decir, dónde va el logo. **v1 mejora
   aquí.**
2. **Se quita** `Preserve authentic product/manufacturer labels and the exact supplied logo
   lettering.`. Queda dicho en la línea de tipografías («Keep supplied logo lettering as its
   exact image… Preserve authentic product labels in their original typeface.»). Se pierde
   «manufacturer» y la frase pasa de regla de fidelidad a regla tipográfica.
3. **Con fotos de producto** (ronda 8), se quita `It shows the client's real product,
   "super smash", exactly as it is: shape, colors, label.` (posición 3, justo después del
   tema). El nombre pasa a `Images 1 and 2: the client's real product, "super smash",
   shown in the video — keep it exactly as it is (shape, colors, label).` (posición 9–10,
   después de toda la historia).

Nada más cambia en el clip de movimiento. **Para esta ruta v1 no explica una degradación:
manda más texto útil que v0.**

### 3.2 Réplica: lo que cambia de v0 a v1

- Sale la guía en español (10 frases, «App production directions (trusted…)») y entran
  líneas fijas en inglés: «using it as the sequence guide only, not its visual style» (en
  la **primera** frase), «never copy its music or promotions», `Client product: "…"`, «do
  not invent a visual hook, new shots…», «Do not keep the source-owner's slogans or
  wording…».
- **Nuevo en la réplica:** los datos clave con la coletilla del clip de movimiento («Let
  them shape the story — what is shown and how urgent it feels»).
- La identidad pasa de `Client identity: <recortada>` a `Client identity: "<entera>"`.

### 3.3 Lo que de verdad cambió para el fundador: `5048b047`, el mismo 2026-11-02

Todas las frases telegráficas del prompt actual entraron en el commit `5048b047` (2026-11-02,
«wip: unpushed m-24820842 work recovered from the 2026-10-30 review snapshot»), **no** en v1:
«Headlines/CTAs assigned to local composition…», «Reference videos guide camera/actions
only…», «Integrate EVERY reference below…», «Brand graphics/approved text accents…»,
«Restyle existing/approved client text…», «Preserve choreography, shots/cuts/timing…»,
«Categories override filenames». Comprobado con `git log -S`. Esas frases se escribieron
comprimidas para caber en 2950 caracteres, y llegaron el mismo día que v1. Comparado con
`main` (base):

| `main` (base) | Actual (v0 y v1 por igual) |
|---|---|
| `No text on screen.` | `Only render existing or explicitly approved client wording; no invented text, source-owner captions, instructions or extra watermarks. Headlines/CTAs assigned to local composition are added afterwards, not in this scene.` + `Restyle existing/approved client text in these families.` |
| `Use the brand colors as accents where natural: #305046, #da2220, #f9ecc9, #1d1f1e.` | `Brand graphics/approved text accents: <9 hex>. Keep natural product, authentic labels and supplied wordmark colors exact.` |
| `The brand's typeface is Baloo 2: let the visual style match its personality, without drawing any letters.` | `Client typefaces: headlines=Baloo 2; body=Nunito. Restyle existing/approved client text in these families. Keep supplied logo lettering as its exact image, never redraw it. Preserve authentic product labels in their original typeface.` |
| Réplica: `Keep the original shot count, shot order, cut timings, framing, camera angle, camera trajectory, gestures, hand positions, actions, motion and pacing…` | `Preserve choreography, shots/cuts/timing, framing, camera, hands/actions, geometry and duration/ratio; REPLACE BRAND GRAPHICS below.` |
| Réplica: `The replacement product must match the supplied photos: ingredients, layers, shape, colors, proportions and packaging, consistently throughout the actions. Preserve every stage of assembly; do not show the fully assembled product early.` | `@Image1: real product identity/ingredients/labels, not its photo background/props. Replace product from first appearance/actions; preserve assembly stages and natural colors.` |
| Réplica: `Do not recreate its original music or speech.` | `never copy its music or promotions` (y nada sobre el habla) |
| — | Bloque de logos: `Integrate EVERY reference below in its own role; none is optional. Honor usage notes. Logo alternatives were already resolved. … Categories override filenames. … Used assets: exact identity/colors/proportions; no merged roles/logos or printed notes.` |

## 4. Hallazgos (ordenados por severidad)

**Resumen.** La degradación es real si se compara con `main`. Casi toda viene de `5048b047`:
es la redacción comprimida para caber en 2950 caracteres, y v1 la heredó sin
devolverle claridad, aunque el tope ya no existe. Lo que v1 introduce por su cuenta pesa
poco en el clip de movimiento (incluso lo mejora: ya no corta las tomas). En la réplica sí
introduce dos contradicciones y un cambio de orden. Origen: **[v1]** = cambio del compilador
1; **[5048b047]** = redacción de recursos de marca, que v0 y v1 comparten; **[siempre]** =
ya estaba en `main`. Líneas de la copia fija de `media.py`.

### H1 — Alta · [5048b047] · La regla de texto en pantalla pasó de prohibir a permitir

- `main`: `No text on screen.`.
- Ahora, en el clip de movimiento: `Only render existing or explicitly approved client
  wording; no invented text, source-owner captions, instructions or extra watermarks.
  Headlines/CTAs assigned to local composition are added afterwards, not in this scene.`,
  junto con `Restyle existing/approved client text in these families.` y `Brand
  graphics/approved text accents: …`.
- Seedance lee aquí que **hay** texto aprobado que puede dibujar y estilizar en Baloo 2. El
  gancho («¿Rutina? Rómpela con una Super Smash a 6$») es copia aprobada y el pedido dice
  «shown — never written». Las dos órdenes chocan. La copia de Claude, en cambio, dice «no
  words on screen».
- «Headlines/CTAs … are added afterwards» es falso en un clip: no se superpone nada después.
  Es una nota interna de la ruta de imagen.
- Código: `media.py:5488-5493` (`_media_text_rule`, aplicación ≥ 2), `6920-6938`
  (`_brand_typefaces_line`) y `6769`.
- Guardián: no lo detecta. `_assert_media_intent` (`prompt_quality.py:275-277`) **exige** las
  frases «logo lettering», «authentic product» y «no invented text». Es decir, protege la
  redacción nueva.

### H2 — Alta · [siempre, agravado por la selección] · La toma pide un logo que no se envía

- Borrador `cfde8564`, toma 3 (escrita por Claude): `"La Super Smash armada aparece de frente
  sobre su papel de envoltura con el Imagotipo de Nibbles' Burgers integrado en la escena…"`.
  El pedido a Seedance: `referencias: 0 fotos + 0 recursos de marca`, y el prompt no tiene
  bloque de logos ni regla de «no dibujes logos».
- La copia se escribe **antes** del selector de recursos: su encargo lista «Logo «Imagotipo»:
  integrated inside the scene…». Después, el selector puede quitar el logo o pasarlo a firma
  (`media.py:2295-2420`). El log no dice cuál de las dos pasó aquí.
- Resultado: Seedance inventa un logo con el nombre de la marca, que es justo lo que la
  marca no quiere.
- Guardián: ninguno compara las tomas con las referencias que se envían.

### H3 — Alta-media · [5048b047, v1 no lo deshizo] · Redacción telegráfica y notas internas, ya sin razón

Sin tope de caracteres, la compresión ya no hace falta. La guía de Seedance pide «concise…
avoid semantic conflicts», no barras ni jerga. Pérdidas reales frente a `main` en la réplica
(ninguna aparece en v0 ni en v1):

| `main` decía | Ahora | Qué se perdió |
|---|---|---|
| «Preserve every stage of assembly; do not show the fully assembled product early.» | «preserve assembly stages and natural colors» (`7009`) | **no mostrar el producto armado antes de tiempo** |
| «ingredients, layers, shape, colors, proportions and packaging, consistently throughout the actions» | «real product identity/ingredients/labels» | capas, proporciones, constancia a lo largo de las acciones |
| «Keep the original shot count, shot order, cut timings… camera trajectory, gestures, hand positions» | «shots/cuts/timing, framing, camera, hands/actions» | número y orden de planos, trayectoria de cámara |
| «Do not recreate its original music or speech.» | «never copy its music or promotions» | **el habla** (voces del reel ajeno) |
| «Do not cut to a catalog still or a new final hero shot.» | «do not invent … a new ending» | el corte a foto de catálogo |

Jerga que Seedance no puede interpretar (`brand_references.py:274, 351, 372, 374`):
- «Logo alternatives were already resolved.» y «principal imagotipo»: Seedance no sabe qué
  hubo antes;
- «Categories override filenames.»: el modelo nunca ve los nombres de archivo;
- «Used assets: exact identity/colors/proportions; no merged roles/logos or printed notes.»;
- «Headlines/CTAs assigned to local composition…».

Guardián: no mide legibilidad. Además, `REPLICATION_PROSE_V1_COVERAGE` (`prompt_text.py:343`)
**exige** frases telegráficas literales («Preserve choreography, shots/cuts/timing, framing,
camera»). Reescribirlas rompe la prueba.

### H4 — Media · [v1] · Réplica: los datos clave contradicen «no cambies las tomas»

- Nuevo en v1 (`media.py:7045`): `Key facts of this offer (…): {"precio": "10$"}. Let them
  shape the story — what is shown and how urgent it feels — never write them on screen…`.
- El mismo prompt dice `Preserve choreography, shots/cuts/timing…` y `do not invent a visual
  hook, new shots… or a new ending`.
- «Shape the story / what is shown» invita a cambiar el contenido de una edición que debe
  quedar en su sitio. Es un conflicto semántico de los que la guía de Seedance pide evitar.
- Guardián: no lo detecta. Peor, `prompt_quality.py:114` **exige** el dato clave en la
  réplica.

### H5 — Media · [v1] · Réplica: «not its visual style» subió a la primera frase

- v0: `Edit @Video1 in place. Preserve choreography…`, y «Es solo la guía de secuencia, no su
  estilo visual.» viajaba al final, en español, como contexto.
- v1 (`media.py:6999`): `Edit @Video1 in place, using it as the sequence guide only, not its
  visual style.`
- En una edición en el sitio, el estilo visual (luz, gradación, textura) **es** el metraje.
  Puesta en la posición de más peso, la frase choca con «Preserve … framing, camera,
  geometry». Puede empujar a Seedance a regenerar la escena y bajar la fidelidad de manos y
  producto, o ser ignorada. Lo que se quería decir es más estrecho: «no copies la paleta, la
  tipografía ni los textos de la marca ajena».
- Guardián: la tabla de cobertura exige la frase literal, sin mirar su posición.

### H6 — Media · [v1] · Réplica: la prioridad de la marca se «cubre» con el prefijo de la paleta

- La guía decía «Aplica MI identidad de marca por encima: los colores, la tipografía, los
  textos y el CTA del Brand Kit … tienen prioridad sobre el look del reel ajeno».
- La tabla de cobertura (`prompt_text.py:354-357`) la da por dicha con `"Client palette: "`
  más «Use only existing text…».
- Se pierden la noción de prioridad y la unidad «textos y CTA». Con la opción «textos de
  marca» apagada (la opción por defecto), el prompt dice lo contrario: «do not invent …
  CTAs». En v0 viajaban las dos frases, contradictorias; v1 resolvió la contradicción en
  silencio.
- Guardián: es circular. Comprueba el prompt contra la misma tabla que lo produjo.

### H7 — Media-baja · [v1, ronda 8] · El nombre del producto se movió al final del clip

- Con fotos de producto, sale `It shows the client's real product, "super smash", exactly as
  it is…` (posición 3, `media.py:6696-6706`).
- El nombre reaparece después de las tres tomas: `Images 1 and 2: the client's real product,
  "super smash", shown in the video — keep it…` (`6722-6727`).
- Va contra la guía de BytePlus («place important content at the front»), y «shown in the
  video» es más débil que «It shows». Sin tope, la repetición de 15 palabras no cuesta nada.
- Guardián: comprueba las unidades de sentido (`prompt_quality.py:212`), no su posición.

### H8 — Media-baja · [v1 lo amplía] · Réplica: el posicionamiento de marca entra entero

- `Client identity: "<posicionamiento completo>"` (`media.py:7047`, protegido). En el caso
  real son unas 70 palabras de marketing («redefine la experiencia… alta gama urbana
  accesible…»), sin ninguna orden visual. Diluye el prompt y abre la puerta a inventar
  escenografía.
- v0 lo recortaba por el tope.
- Guardián: `prompt_quality.py:136` exige que vaya **entero**, así que impide arreglarlo.

### H9 — Baja · [v1] · Regla de etiquetas absorbida por la línea de tipografías

- Sale `Preserve authentic product/manufacturer labels and the exact supplied logo
  lettering.` (`media.py:6062-6082`).
- Queda `Preserve authentic product labels in their original typeface.`: se pierde
  «manufacturer» y la orden pasa de fidelidad («no cambies la etiqueta») a tipografía («no
  cambies su letra»).
- Guardián: busca «authentic product», que también aparece en la frase nueva.

### H10 — Baja · [v1 mantiene] · Topes por campo sin tope global

- Las tomas se cortan a 260 caracteres (`_SHOT_MAX`, `media.py:6399/6429`), el gancho a 160,
  el llamado a la acción a 120, el producto a 120 y los datos clave a 500 caracteres de JSON
  (`_FACTS_MAX`, `5513`). Lo que pasa de ahí se descarta en silencio.
- Guardián: replica la misma regla de 500 (`prompt_quality.py:108-112`), así que nunca puede
  ver un dato perdido.

## 5. Cobertura de los guardas (`prompt_quality.py`)

Los guardas (`assert_prompt_keeps_intent`, `assert_video_prompt_keeps_intent`,
`_assert_media_intent`) solo comprueban que ciertas **subcadenas** estén presentes. Además:
techo de palabras, nada recortado y ninguna frase de más de 40 caracteres repetida.

| Hallazgo | ¿Lo detecta? | Por qué no |
|---|---|---|
| H1 texto en pantalla | No; **exige** la redacción nueva | Busca «no invented text», no «no text on screen» |
| H2 logo pedido y no enviado | No | No cruza el texto de las tomas con las referencias que viajan |
| H3 telegráfico y jerga | No; la tabla de cobertura **exige** frases telegráficas | No hay ninguna medida de legibilidad ni lista de jerga prohibida |
| H4 datos clave en la réplica | No; **exige** el dato | No detecta contradicciones entre líneas |
| H5 «not its visual style» al frente | No | No mira posiciones |
| H6 prioridad de la marca | No | Es circular: usa la misma tabla `REPLICATION_PROSE_V1_COVERAGE` que el compilador |
| H7 producto movido | No | Comprueba unidades, no orden |
| H8 identidad entera | No; **exige** que vaya entera | — |
| H9 «manufacturer» | No | «authentic product» aparece en otra frase |
| H10 topes por campo | No | Repite el mismo tope de 500; las pruebas usan tomas cortas |

Además, **todas** las comparaciones son v1 contra v1 o v1 contra v0. Ninguna compara contra
`main`, que es donde se perdió la redacción explícita (§3.3). Lo que falta en los guardas:
1. Una lista de **unidades de sentido de `main`** por ruta (por ejemplo «not … assembled
   product early», «speech», «No text on screen» en el clip de movimiento), exigidas en
   inglés claro.
2. **Pares contradictorios** prohibidos en un mismo prompt: «shape the story» junto a
   «Edit @Video1 in place»; «approved client wording» junto a «never written»; «Restyle …
   client text» en una ruta sin texto.
3. **Coherencia de referencias:** si una toma o el tema mencionan «logo», «imagotipo»,
   «isologo» o el nombre de la marca y no viaja ningún logo, el prompt debe llevar una línea
   de «no dibujes logos».
4. **Posición:** el producto y la orden principal (editar en el sitio / contar la historia)
   en el primer 20 % del prompt.
5. **Jerga prohibida:** «filenames», «already resolved», «local composition», «principal»
   sin explicar, frases unidas con barras.

## 6. Debilidades previas a v1 (no son culpa del compilador)

- **[siempre] Las tomas se escriben a ciegas.** Claude no ve los fotogramas ni el video. La
  toma 1 puede contradecir a Image 1 (fotograma inicial), y «Primerísimo plano / Cámara
  lenta» pueden chocar con «Refer to the camera movement… of Video 1». Ninguna línea dice qué
  manda. Arreglo: «Image 1 and Image 2 are the exact first and last frames; adapt the shots
  to them. Camera movement and pacing come from Video 1; the shots say what is shown.».
- **[5048b047] Guía de movimiento contra guía de marca** en el clip de movimiento:
  `Reference videos guide camera/actions only. Replace source-owner names, logos and printed
  graphics … on existing surfaces` (`media.py:6759`). La segunda frase da por hecho que las
  superficies del video aparecen en el resultado, y la primera dice que no. Además, el video
  suele ser del propio cliente.
- **[siempre] Sin dirección de sonido.** `cfde8564` pidió audio y el prompt no dice qué debe
  sonar: ni voz en off, ni música, ni sonido ambiente. Con un gancho en español «shown —
  never written», Seedance puede decirlo en voz alta o no.
- **[siempre] El tema del operador como orden visual:** `It is about (in Spanish): "…Cierro
  afuera del local, con la super smash en primer plano y el llamado a pedirla."` trae un
  llamado a la acción y «6$ con envío gratis», que el resto del prompt prohíbe escribir. Sin
  texto del operador, el tema es solo «super smash» (`cfde8564`): una línea vacía.
- **[5048b047] Paleta de 9 hex** como «text accents». Los modelos de video siguen mal los
  hexadecimales; `main` mandaba 4 y «where natural».
- **[siempre] Sintaxis mezclada en la réplica:** `@Video1` / `@Image1` en el cuerpo e
  `Image 2:` en el bloque de logos. Ya estaba anotado en el diagnóstico del 2026-11-02 y
  sigue sin tocarse.
- **[siempre] El orden de la réplica:** las instrucciones del operador van en la posición
  ~22 de 33, después de la identidad.
- **Diapositiva animada sin video** (`320257e3`, fuera de los clips): el bloque de logos
  dice `Integrate EVERY reference below…; none is optional … Scene resource 1: principal
  isologo` pero no viaja ninguna imagen de logo (solo `first_frame`, `media.py:4381-4383`).
  El logo, si está, ya viene dentro de la foto. «Integrate» invita a añadir un segundo
  logo; la orden debería ser «keep the logo already in the photograph unchanged». Además,
  «Let them shape the story» no encaja con «slow, smooth camera move».
- **Fuera del prompt, pero confunde la evaluación:** desde el 2026-10-23 todo sale como
  **borrador a 480p**. Cualquier comparación visual contra clips anteriores a 720p o 1080p
  mezcla las dos causas.

## 7. Arreglos propuestos (en orden)

Todos van detrás de un **compilador 2** (`prompt_compiler_version = 2`), para que los
borradores ya congelados se compilen igual. Antes de activarlo hay que medir, según
`qualify-measure`: A/B pagado en horario nocturno, con `QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY`,
mismo borrador y misma semilla, brazos `main` / v1 / v2, rúbrica ciega (texto en pantalla,
logo correcto o ausente, fidelidad del producto, orden de planos, rastro de la marca ajena).
Costo estimado: ~USD 0,75 por tarea de 5 s con video de referencia.

1. **H1:** en clip de movimiento, video hablado y diapositiva, cambiar la regla por: «Do
   not show any written text, captions, subtitles or titles. The only lettering allowed is
   the supplied logo and the real product's own label, both unchanged.» Quitar «Restyle
   existing/approved client text…» y «Headlines/CTAs assigned to local composition…» en
   esas rutas. En la réplica, dejar una versión propia: «replace only text the source
   already shows».
2. **H2:** después del selector, si no viaja ningún logo, añadir: «No logo image is supplied:
   do not draw any logo, brand name or sign lettering; leave surfaces the shots mention for
   a logo plain.». Mejor aún: pasar a la copia la selección ya hecha, o quitar de las tomas
   las menciones al logo. Nuevo guardián: menciones de logo contra referencias enviadas.
3. **H3:** reescribir en frases llanas las líneas de `5048b047`, recuperando las unidades de
   `main` de la tabla del §4 (producto armado no antes de tiempo, capas y proporciones, habla,
   orden de planos, foto de catálogo). Borrar del bloque de logos «Logo alternatives were
   already resolved», «Categories override filenames», «principal» (decir «the client's
   logo») y la lista con barras de «Used assets». Actualizar `REPLICATION_PROSE_V1_COVERAGE`
   con las frases nuevas.
4. **H4:** en la réplica, cambiar la coletilla de los datos clave por: «Context only: do not
   add or change shots for them and never write them on screen.». O no mandarlos: la
   réplica no cambia la historia y el texto de la publicación ya los lleva.
5. **H5:** primera frase de la réplica: «Edit @Video1 in place: keep its footage, shots,
   cuts, timing, camera and actions; change only its branding.». Mover la orden sobre la
   marca ajena a la línea de reemplazo: «do not keep the source brand's palette, fonts or
   wording».
6. **H6:** hacer honesta la cobertura. Una línea explícita «The client's brand look (palette,
   typefaces, logo) takes priority over the source reel's look.». Con «textos de marca»
   apagado, que la guía de la pantalla no prometa «los textos y el CTA del Brand Kit».
7. **H7 y H9:** volver a poner `It shows the client's real product, "<p>", exactly as it
   is…` en la posición 3, aunque la línea de las fotos lo repita. Restaurar la regla de
   etiquetas en su forma de fidelidad: «Keep the real product's own labels and packaging
   exactly as they are».
8. **H8:** quitar `Client identity` de los prompts de video, o sustituirla por 1 o 2 rasgos
   visuales del Brand Kit. Cambiar el guardián para que deje de exigirla entera.
9. **H10:** en 2.x con compilador 2, quitar los topes por campo (`_SHOT_MAX`,
   `_HOOK_IN_CLIP`, `_CTA_IN_CLIP`, `_FACTS_MAX`). El techo de 1000 palabras basta.
10. **Guardas:** añadir los cinco controles del §5 y una prueba «unidades de `main`» por ruta.
    Las pruebas actuales que exigen frases telegráficas literales se tienen que cambiar
    junto con la redacción.

## 8. Qué se verificó y qué no

- **Verificado:** el prompt reconstruido con v1 es idéntico byte a byte al del log
  (`ddfcafc9`). v0 actual es idéntico a HEAD en los 5 escenarios. Las frases telegráficas
  vienen de `5048b047` (`git log -S`). Las cinco pérdidas de la réplica frente a `main` no
  aparecen en v0 ni en v1.
- **No verificado:** ninguna afirmación sobre el video resultante. No hubo llamadas a
  BytePlus ni a Anthropic. Qué decidió el selector en `cfde8564` (el log no lo registra).
  Si Seedance 2.5 interpreta «@Image1» e «Image 1» igual.
- El log no tiene prompts anteriores al compilador 1 ni ninguna réplica. El «antes» sale de
  la reconstrucción sobre `main` (`56746531`) y HEAD (`5048b047`) con las mismas entradas.

## 9. Compilador v2 (2026-11-03)

> Aprobado por el fundador el 2026-11-03. Está implementado sin commit en la rama
> `fix/m-24820842-prompt-budget` (creative-engineer). No hubo llamadas pagadas: todo lo de
> abajo es una reconstrucción offline con el código del árbol de trabajo.

### 9.1 Qué cambia

- **Versión del compilador.** Toda ejecución nueva recibe
  `MediaInputs.prompt_compiler_version = 2` (`PROMPT_COMPILER_VERSION`,
  `MediaProducer.prepare_new_brief`).
- **Borradores congelados.** Los que tienen 0 o 1 se compilan igual, byte a byte. Se
  comprobó en los 11 escenarios del §3 (mismo script de la auditoría, salida idéntica) y con
  los dos prompts del log (`ddfcafc9` y `cfde8564`). Una prueba fija el sha256 de v0 y de v1
  por ruta.
- **Rutas que cambian.** Solo las tres rutas de Seedance 2.x de «Clip»:
  - clip de movimiento (`_clip_prompt_v2`);
  - réplica de reel (`_reel_edit_lines_v2`);
  - diapositiva animada de la galería (`_carousel_motion_v2`).

  La imagen, el video hablado y las plantillas compilan como en v1.
- **H1. Texto en pantalla.** El prompt prohíbe todo texto escrito: «Do not show any written
  text, captions, subtitles or titles». Solo se permiten las letras del logo enviado y la
  etiqueta real del producto, sin cambios. Se quitan «Restyle…», «Headlines/CTAs assigned to
  local composition…» y «approved text accents».
- **H2. Logo no enviado.** Si después del selector no viaja ningún logo, el prompt dice: «No
  logo image is supplied: do not draw any logo, brand name or sign lettering, and where a
  shot mentions a logo, leave that surface plain».
  - No se reordenó la copia. El selector corre dentro de la generación, después de la copia;
    moverlo antes cambiaría el costo y la reanudación.
- **H3. Redacción.** Todas las líneas son frases completas.
  - El bloque de recursos se reescribió (`brand_reference_block_v2`). Ya no lleva
    «principal», «already resolved», «Categories override filenames» ni la lista con barras.
  - Vuelven los puntos de `main`: número y orden de planos, trayectoria de cámara, no
    mostrar el producto armado antes de tiempo, capas y proporciones constantes, no copiar ni
    la música **ni el habla**, no cortar a una foto de catálogo.
- **H4. Datos clave en la réplica.** Son solo contexto: «do not add or change shots for them
  and never write them on screen».
- **H5. Primera frase de la réplica.** Ahora dice que conserve el metraje y cambie solo dos
  cosas: el producto y la marca ajena («keep its footage… Change only two things…»). Sale
  «not its visual style».
- **H6. Prioridad de la marca.** La réplica dice «The client's brand look takes priority over
  the source reel's look». La tabla de cobertura de v1 queda anotada como incompleta en ese
  punto.
- **H7 y H9. Producto y etiqueta.** El producto vuelve a la segunda frase del clip. La
  etiqueta se protege como regla de fidelidad, no de tipografía.
- **H8. Posicionamiento.** Ninguna de las tres rutas manda el posicionamiento de marca.
- **H10. Topes por campo.** En 2.x no hay topes en las tomas, el gancho, el llamado a la
  acción, el producto ni los datos clave. El techo de 1000 palabras se revisa antes de pagar.
  En Seedance 1.x siguen los topes y el presupuesto de caracteres.
- **Debilidades del §6 que se arreglaron:**
  - Fotogramas, video y tomas dicen qué manda cada uno: «starts exactly on Image 1… adapt the
    shots to them» y «Follow the camera movement… of Video 1; the shots above say what is
    shown».
  - La réplica usa solo `@ImageN`, igual que `@Video1`.
  - En el clip y la diapositiva, la paleta son los 4 colores principales, «where they fit
    naturally».
  - La diapositiva ya no pide «Integrate EVERY reference», que invitaba a añadir un segundo
    logo. Ahora dice que los recursos ya están en la foto y que no agregue otra copia.

### 9.2 Subtítulos como opción

- **Dato nuevo.** `MediaInputs.clip_subtitles`, apagado por defecto y en todo brief anterior.
- **Pantalla.** En «Crear publicación», paso ③, «Más opciones», aparece «Agregar subtítulos
  con tu texto». Debajo, la ayuda: «Tu frase de apertura al inicio y tu invitación a comprar
  al final, con la letra y los colores de tu marca.». El resumen muestra la fila
  «Subtítulos».
- **Cómo se ponen.** Ya existía una forma de superponer texto: `compose.subtitle_layer` y
  `VideoFitter.subtitle`, los subtítulos del video hablado (m-24828920). Se usa esa, así que
  no hizo falta una composición nueva de Remotion. La opción no cambia el prompt de
  Seedance: siempre pide cero texto.
- **Con la opción encendida:**
  - el gancho sale al inicio y el llamado a la acción al final;
  - cada uno ocupa el 40 % del clip (al menos 2,5 s) y no se solapan;
  - usan la tipografía y la paleta del Brand Kit;
  - se ponen en el borrador y otra vez en el final de 1080p, con las mismas líneas, que
    quedan guardadas en los parámetros del clip.
- **Si fallan:**
  - en el borrador, se conserva el clip pagado y queda un aviso;
  - en el final, el final falla, pero el archivo de 1080p sin procesar queda guardado y el
    reintento no se paga de nuevo.

### 9.3 Guardianes

`prompt_quality.assert_video_prompt_v2_quality` revisa la calidad y no la redacción:

- los puntos de `main` de cada ruta, escritos en el propio guardián (no se importan del
  compilador);
- que no haya pares de órdenes contradictorias;
- que las menciones de logo coincidan con los logos enviados;
- que el producto y la orden principal estén en el primer 20 % del prompt;
- que no haya jerga interna ni palabras unidas con barras;
- que use una sola sintaxis para las imágenes;
- que ninguna palabra de la marca ajena aparezca fuera de los metadatos no confiables;
- que cada dato vaya literal, sin recortes y sin el posicionamiento.

Una prueba comprueba que el guardián **rechaza** los prompts v1 de las tres rutas. Los
guardianes anteriores siguen protegiendo los prompts v0 y v1 congelados.

### 9.4 Tamaños (Seedance 2.5, mismas entradas)

| Caso | v1 | v2 |
|---|---:|---:|
| cfde8564 (fotogramas 1+2, 1 video, sin recursos de marca) | 2289 c / 361 p | 2234 c / 391 p |
| ddfcafc9 (fotogramas 1+2, 1 video, 1 logo imagotipo) | 2967 c / 463 p | 2875 c / 512 p |
| Réplica (fixture anonimizada, 1 foto + imagotipo) | 2869 c / 407 p | 3307 c / 549 p |
| Diapositiva animada (sin video de referencia, isologo en la foto) | 1601 c / 230 p | 1110 c / 189 p |

En el clip y la réplica, v2 tiene más palabras: las frases son completas y la réplica
recupera los puntos de `main`. Todos los casos quedan lejos del techo de 1000 palabras. La
diapositiva es más corta porque pierde el bloque de recursos y las reglas de «texto
aprobado».

### 9.5 Prompts antes y después

### cfde8564 (fotogramas 1+2, 1 video, sin recursos de marca)

**v1** (2289 caracteres, 361 palabras):

```text
A vertical 9:16 advertising video for social media that tells a short story, cinematic and well lit, with no presenter talking to the camera. It is about (in Spanish): "super smash". It shows the client's real product, "super smash", exactly as it is: shape, colors, label. It opens on this hook, shown — never written (in Spanish): "¿Ya escuchaste cómo cruje una Super Smash?". The story, shot by shot (in Spanish): Shot 1 (0-2 s): "Primerísimo plano a ras de plancha: una espátula prensa con fuerza una bola de carne sobre el hierro humeante y los bordes empiezan a chisporrotear y dorarse al instante.". Shot 2 (2-4 s): "Se voltea la carne mostrando la costra oscura y crujiente; una lámina de queso cae encima y se derrite lentamente mientras el pan se tuesta al lado en la misma plancha.". Shot 3 (4-5 s): "La Super Smash armada aparece de frente sobre su papel de envoltura con el Imagotipo de Nibbles' Burgers integrado en la escena, el queso escurriendo por el borde mientras una mano la levanta hacia cámara.". The opening frame is Image 1. The closing frame is Image 2. Refer to the camera movement, motion and pacing of Video 1, keeping the motion details consistent, with the client's product and scene. Key facts of this offer (the client's own data, as JSON): {"precio": "6$"}. Let them shape the story — what is shown and how urgent it feels — never write them on screen: the post's text carries them. Brand graphics/approved text accents: #305046, #da2220, #f9ecc9, #1d1f1e, #d4221f, #eab4a3, #fcfbe3, #bc8f84, #cc4c43. Keep natural product, authentic labels and supplied wordmark colors exact. Client typefaces: headlines=Baloo 2; body=Nunito. Restyle existing/approved client text in these families. Keep supplied logo lettering as its exact image, never redraw it. Preserve authentic product labels in their original typeface. Reference videos guide camera/actions only. Replace source-owner names, logos and printed graphics with the selected client identity and palette on existing surfaces; preserve natural food/skin/product colors and geometry. Only render existing or explicitly approved client wording; no invented text, source-owner captions, instructions or extra watermarks. Headlines/CTAs assigned to local composition are added afterwards, not in this scene.
```

**v2** (2234 caracteres, 391 palabras):

```text
A vertical 9:16 advertising video for social media that tells a short story, cinematic and well lit, with no presenter talking to the camera. It shows the client's real product, "super smash", exactly as it is: shape, colors, label. It is about (in Spanish): "super smash". It opens on this hook, shown — never written (in Spanish): "¿Ya escuchaste cómo cruje una Super Smash?". The story, shot by shot (in Spanish): Shot 1 (0-2 s): "Primerísimo plano a ras de plancha: una espátula prensa con fuerza una bola de carne sobre el hierro humeante y los bordes empiezan a chisporrotear y dorarse al instante.". Shot 2 (2-4 s): "Se voltea la carne mostrando la costra oscura y crujiente; una lámina de queso cae encima y se derrite lentamente mientras el pan se tuesta al lado en la misma plancha.". Shot 3 (4-5 s): "La Super Smash armada aparece de frente sobre su papel de envoltura con el Imagotipo de Nibbles' Burgers integrado en la escena, el queso escurriendo por el borde mientras una mano la levanta hacia cámara.". The video starts exactly on Image 1 (the opening frame) and ends exactly on Image 2 (the closing frame); adapt the shots to them. Follow the camera movement, motion and pacing of Video 1; the shots above say what is shown, with the client's product and scene. If it shows another brand's name, logo or printed graphics, do not copy them. Key facts of this offer (the client's own data, as JSON): {"precio": "6$"}. Let them shape the story — what is shown and how urgent it feels — never write them on screen: the post's text carries them. Use the brand colors as accents where they fit naturally, such as props, light or the background: #305046, #da2220, #f9ecc9, #1d1f1e. Keep the natural colors of the food and of the real product. The brand's typefaces are "Baloo 2" for headlines and "Nunito" for body text: let the look of the video match their personality, without drawing any letters. Do not show any written text, captions, subtitles or titles. No logo image is supplied: do not draw any logo, brand name or sign lettering, and where a shot mentions a logo, leave that surface plain. The only lettering allowed is lettering the supplied images already show, such as the real product's own label, unchanged.
```

### ddfcafc9 (fotogramas 1+2, 1 video, 1 logo imagotipo)

**v1** (2967 caracteres, 463 palabras):

```text
A vertical 9:16 advertising video for social media that tells a short story, cinematic and well lit, with no presenter talking to the camera. It is about (in Spanish): "Quiero un clip de la promo de la super smash a 6$ con envío gratis, dirigido a jóvenes y universitarios que buscan salir de la rutina. Que sientan antojo y ganas de compartir. Cierro afuera del local, con la super smash en primer plano y el llamado a pedirla.". It shows the client's real product, "super smash", exactly as it is: shape, colors, label. It opens on this hook, shown — never written (in Spanish): "¿Rutina? Rómpela con una Super Smash a 6$". The story, shot by shot (in Spanish): Shot 1 (0-2 s): "Primerísimo plano de la espátula aplastando la bola de carne sobre la plancha humeante; los bordes chisporrotean y se doran al instante formando la costra.". Shot 2 (2-4 s): "Cámara lenta: el queso se derrite sobre la carne doble, se tapa con el pan tostado y unas manos jóvenes la pasan entre amigos riendo en una mesa del local.". Shot 3 (4-5 s): "Afuera del local de noche, la Super Smash en primer plano sostenida hacia la cámara, con el imagotipo de Nibbles' Burgers iluminado en la fachada desenfocada al fondo.". The opening frame is Image 1. The closing frame is Image 2. Refer to the camera movement, motion and pacing of Video 1, keeping the motion details consistent, with the client's product and scene. Key facts of this offer (the client's own data, as JSON): {"precio": "6$"}. Let them shape the story — what is shown and how urgent it feels — never write them on screen: the post's text carries them. Brand graphics/approved text accents: #305046, #da2220, #f9ecc9, #1d1f1e, #d4221f, #eab4a3, #fcfbe3, #bc8f84, #cc4c43. Keep natural product, authentic labels and supplied wordmark colors exact. Client typefaces: headlines=Baloo 2; body=Nunito. Restyle existing/approved client text in these families. Keep supplied logo lettering as its exact image, never redraw it. Preserve authentic product labels in their original typeface. Reference videos guide camera/actions only. Replace source-owner names, logos and printed graphics with the selected client identity and palette on existing surfaces; preserve natural food/skin/product colors and geometry. Integrate EVERY reference below in its own role; none is optional. Honor usage notes. Logo alternatives were already resolved. Keep logos on suitable existing surfaces; no invented marks/props. Image 3: principal imagotipo. imagotipo: keep internal layout/proportions unless its note requests change. Categories override filenames. Never add logos to food/bare skin. Used assets: exact identity/colors/proportions; no merged roles/logos or printed notes. Keep used assets consistent across shots. Only render existing or explicitly approved client wording; no invented text, source-owner captions, instructions or extra watermarks. Headlines/CTAs assigned to local composition are added afterwards, not in this scene.
```

**v2** (2875 caracteres, 512 palabras):

```text
A vertical 9:16 advertising video for social media that tells a short story, cinematic and well lit, with no presenter talking to the camera. It shows the client's real product, "super smash", exactly as it is: shape, colors, label. It is about (in Spanish): "Quiero un clip de la promo de la super smash a 6$ con envío gratis, dirigido a jóvenes y universitarios que buscan salir de la rutina. Que sientan antojo y ganas de compartir. Cierro afuera del local, con la super smash en primer plano y el llamado a pedirla.". It opens on this hook, shown — never written (in Spanish): "¿Rutina? Rómpela con una Super Smash a 6$". The story, shot by shot (in Spanish): Shot 1 (0-2 s): "Primerísimo plano de la espátula aplastando la bola de carne sobre la plancha humeante; los bordes chisporrotean y se doran al instante formando la costra.". Shot 2 (2-4 s): "Cámara lenta: el queso se derrite sobre la carne doble, se tapa con el pan tostado y unas manos jóvenes la pasan entre amigos riendo en una mesa del local.". Shot 3 (4-5 s): "Afuera del local de noche, la Super Smash en primer plano sostenida hacia la cámara, con el imagotipo de Nibbles' Burgers iluminado en la fachada desenfocada al fondo.". The video starts exactly on Image 1 (the opening frame) and ends exactly on Image 2 (the closing frame); adapt the shots to them. Follow the camera movement, motion and pacing of Video 1; the shots above say what is shown, with the client's product and scene. If it shows another brand's name, logo or printed graphics, do not copy them. Key facts of this offer (the client's own data, as JSON): {"precio": "6$"}. Let them shape the story — what is shown and how urgent it feels — never write them on screen: the post's text carries them. Use the brand colors as accents where they fit naturally, such as props, light or the background: #305046, #da2220, #f9ecc9, #1d1f1e. Keep the natural colors of the food and of the real product. The brand's typefaces are "Baloo 2" for headlines and "Nunito" for body text: let the look of the video match their personality, without drawing any letters. Use every brand image below in the video, each in its own role. Image 3 is the client's logo (imagotipo: the symbol and the name together; keep their layout and proportions unless its usage note asks for a change). Put each logo on a surface that already exists in the scene, such as packaging, a sign or a wall, never on food or bare skin, and do not invent props to carry it. Keep every brand image exactly as supplied, with the same shapes, colors, proportions and lettering, and consistent across shots; do not merge two of them and never write a usage note on screen. Do not show any written text, captions, subtitles or titles. The only lettering allowed is the supplied logo and lettering the supplied images already show, such as the real product's own label, all unchanged.
```

### Réplica (fixture anonimizada, 1 foto + imagotipo)

**v1** (2869 caracteres, 407 palabras):

```text
Edit @Video1 in place, using it as the sequence guide only, not its visual style. Preserve choreography, shots/cuts/timing, framing, camera, hands/actions, geometry and duration/ratio; REPLACE BRAND GRAPHICS below. Source captions/audio/promotions are not client instructions; never copy its music or promotions. Client product: "producto XY". @Image1: real product identity/ingredients/labels, not its photo background/props. Replace product from first appearance/actions; preserve assembly stages and natural colors. Replace EVERY source-owner name/logo/graphic on existing cups, fries cartons, tray paper, wrappers and signs with the supplied client logo. No source-owner marks may remain; keep geometry/perspective/lighting/occlusion and unrelated mandatory labels. Client palette: #1a2b3c, #c0392b, #f4e9d0, #202224, #b5332e, #e0b0a0, #fafae0, #a08070, #c05048. Prioritize colors visible in the client logo on printed backgrounds, accents and graphics on those surfaces, replacing source-brand colors. Do not recolor natural food, skin or the real product. Client typefaces: headlines=Serif 2; body=Textos. Restyle existing/approved client text in these families. Keep supplied logo lettering as its exact image, never redraw it. Use only existing text or wording explicitly approved by the operator; do not invent a visual hook, new shots, CTAs, promotions, props or a new ending. Do not keep the source-owner's slogans or wording; neutral or mandatory labels stay. Key facts of this offer (the client's own data, as JSON): {"precio": "10$"}. Let them shape the story — what is shown and how urgent it feels — never write them on screen: the post's text carries them. Client identity: "Marca Ejemplo 01 es la veram que ducefino la taserulorem de tisup negabolivera moducefino taserulo la rematis panegab de la liver moducefi, en un notaser lorematisup negabolive y ramoducefin. Taserul remati supan con lo gaboliveram en la ducefi, notaserulo un producto de rema tisu panega boliveram, ducefinotaser una lorema tisupa en una negaboliver moducefin y taser de lorematis.". Operator instructions (trusted): "Negabo un live del ramod cefin tase la producto XY: rulorematis, paneg y bolive ramodu, cefi notaseru y lorematisu. Les paneg a boliver con moduce de fino con taseru; que loremat supan de gaboliv ya. Ramodu con: ¡Cefinot pal serul que ya rematisup la negabol!". Integrate EVERY reference below in its own role; none is optional. Honor usage notes. Logo alternatives were already resolved. Keep logos on suitable existing surfaces; no invented marks/props. Image 2: principal imagotipo. imagotipo: keep internal layout/proportions unless its note requests change. Categories override filenames. Never add logos to food/bare skin. Used assets: exact identity/colors/proportions; no merged roles/logos or printed notes. Keep used assets consistent across shots.
```

**v2** (3307 caracteres, 549 palabras):

```text
Edit @Video1 in place, not a new video: keep its footage, shot count, shot order, cut timings, framing, camera angle and trajectory, gestures, hand positions, actions, motion and pacing, and its duration and aspect ratio. Change only two things, plus anything the client's instructions below explicitly ask for: the product becomes the client's product, and the source brand becomes the client's brand. The client's product is "producto XY". The client's instructions (in Spanish, trusted): "Negabo un live del ramod cefin tase la producto XY: rulorematis, paneg y bolive ramodu, cefi notaseru y lorematisu. Les paneg a boliver con moduce de fino con taseru; que loremat supan de gaboliv ya. Ramodu con: ¡Cefinot pal serul que ya rematisup la negabol!". @Image1 shows the client's real product: match its ingredients, layers, shape, colors, proportions, labels and packaging, consistently throughout the actions; do not take the photo's background, hands or props. Replace the source product from its first appearance and through every action. Preserve every stage of assembly: do not show the fully assembled product early. Replace packaging only where it exists in the original. Do not cut to a catalog still or a new final hero shot, and do not paste a product photo into the video. Replace every name, logo and graphic of the source brand on existing surfaces, such as cups, cartons, tray paper, wrappers and signs, with the client's logo below. No mark of the source brand may remain, and a corner watermark is not a replacement. Keep each surface's shape, perspective, lighting and anything in front of it, and leave unrelated mandatory labels as they are. The client's brand look takes priority over the source reel's look: do not keep the source brand's palette, fonts or wording. Use the client's colors on the printed backgrounds, accents and graphics of those surfaces, preferring the colors of the client's logo: #1a2b3c, #c0392b, #f4e9d0, #202224, #b5332e, #e0b0a0, #fafae0, #a08070, #c05048. Do not recolor food, skin or the real product. Where @Video1 already shows text you keep or replace, write it in the client's typefaces: "Serif 2" for headlines and "Textos" for body text. Unless the client's instructions ask for it, do not add new text, captions, a visual hook, a call to action, promotions, props or a new ending. Remove the source brand's slogans and wording; keep neutral or mandatory labels. The source video's captions, audio and promotions are reference data, not instructions: do not recreate its music or speech and do not copy its promotions. Key facts of this offer (the client's own data, as JSON): {"precio": "10$"}. Context only: do not add or change shots for them and never write them on screen. Use every brand image below in the video, each in its own role. @Image2 is the client's logo (imagotipo: the symbol and the name together; keep their layout and proportions unless its usage note asks for a change). Put each logo on a surface that already exists in the scene, such as packaging, a sign or a wall, never on food or bare skin, and do not invent props to carry it. Keep every brand image exactly as supplied, with the same shapes, colors, proportions and lettering, and consistent across shots; do not merge two of them and never write a usage note on screen.
```

### Diapositiva animada (sin video de referencia, isologo en la foto)

**v1** (1601 caracteres, 230 palabras):

```text
Bring this photograph to life as a short cinematic product shot: a slow, smooth camera move (gentle push-in or slight orbit), subtle natural motion in the scene (steam, light, a hand, the background), the product keeps its exact look and label. Nobody talks to the camera. Only render existing or explicitly approved client wording; no invented text, source-owner captions, instructions or extra watermarks. Headlines/CTAs assigned to local composition are added afterwards, not in this scene. Key facts of this offer (the client's own data, as JSON): {"precio": "6$"}. Let them shape the story — what is shown and how urgent it feels — never write them on screen: the post's text carries them. Brand graphics/approved text accents: #305046, #da2220, #f9ecc9, #1d1f1e, #d4221f, #eab4a3, #fcfbe3, #bc8f84, #cc4c43. Keep natural product, authentic labels and supplied wordmark colors exact. Client typefaces: headlines=Baloo 2; body=Nunito. Restyle existing/approved client text in these families. Keep supplied logo lettering as its exact image, never redraw it. Preserve authentic product labels in their original typeface. Integrate EVERY reference below in its own role; none is optional. Honor usage notes. Logo alternatives were already resolved. Keep logos on suitable existing surfaces; no invented marks/props. Scene resource 1: principal isologo. isologo: inseparable whole; never split/rearrange. Categories override filenames. Never add logos to food/bare skin. Used assets: exact identity/colors/proportions; no merged roles/logos or printed notes. Keep used assets consistent across shots.
```

**v2** (1110 caracteres, 189 palabras):

```text
Bring this photograph to life as a short cinematic product shot: a slow, smooth camera move (gentle push-in or slight orbit) and subtle natural motion in the scene (steam, light, a hand, the background). The product keeps its exact look and label. Nobody talks to the camera. Key facts of this offer (the client's own data, as JSON): {"precio": "6$"}. Context only: never write them on screen. Keep the photograph's colors; the brand colors in it (#305046, #da2220, #f9ecc9, #1d1f1e) stay as they are. The brand's typefaces are "Baloo 2" for headlines and "Nunito" for body text: let the look of the video match their personality, without drawing any letters. The photograph already shows the client's brand resources: the client's logo (isologo: the symbol and the name fused into one unit; never split or rearrange it). Keep each one exactly where and as it is while the camera moves; do not add a second logo or any other mark. Do not show any written text, captions, subtitles or titles. The only lettering allowed is what the photograph already shows, such as a logo or the product's own label, unchanged.
```

### 9.6 A/B nocturno pendiente (estimado, no ejecutado)

Condiciones, según `qualify-measure`:

- clave de evaluación `QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY`;
- de 23:00 a 05:00, hora de Bogotá, con un máximo de 3 tareas a la vez;
- borradores de 480p y 5 s;
- la misma copia congelada y la misma semilla en los tres brazos (`main`, v1 y v2);
- rúbrica ciega: texto en pantalla, logo correcto o ausente, fidelidad del producto, orden de
  planos y rastro de la marca ajena.

| Conjunto | Casos | Brazos | Semillas | Tareas | US$/tarea | US$ |
|---|---:|---:|---:|---:|---:|---:|
| Clip con video de referencia (`ddfcafc9`; `cfde8564`; 2 fotos + 1 logo; 2 fotos + 3 logos, sin tomas) | 4 | 3 | 2 | 24 | ≈0,75 | ≈18,0 |
| Réplica (fixture con 1 logo; 2 fotos + 3 logos + textos de marca) | 2 | 3 | 2 | 12 | ≈0,75 | ≈9,0 |
| Diapositiva animada sin video | 2 | 3 | 2 | 12 | ≈0,53 | ≈6,4 |
| **Total** | 8 | | | **48** | | **≈33,4** |

- **Precio por tarea:** sale de `seedance-2-5.md` (2026-10-23). Con video de referencia
  cuesta ≈ US$0,75; sin video, ≈ US$0,53.
- **Versión mínima:** 1 semilla, 24 tareas, ≈ US$16,7.
- **Duración:** unos 50 minutos con 3 tareas en paralelo.
- **Costos aparte:** la copia no se paga, porque se reutilizan las del log. Juzgar los videos
  con Claude Haiku cuesta menos de US$1.
