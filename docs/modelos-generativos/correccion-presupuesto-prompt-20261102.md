# Corrección del presupuesto de indicaciones de video — 2 de noviembre de 2026

Ticket: m-24820842 (PR #412, rama local `fix/m-24820842-prompt-budget`). Autor: creative-engineer.
Fase 2 del plan `.claude/plan-presupuesto-prompt-2026-11-02.md`, con el **cambio de alcance del
fundador del mismo día**, que reemplaza partes del diseño de
`diagnostico-presupuesto-prompt-20261102.md`. **Sin llamadas pagadas, sin commit, sin PR.**

## 1. Lo que dice la documentación oficial (leída hoy)

Las páginas de docs.byteplus.com se renderizan con JavaScript, pero el índice
`https://ai.byteplus.com/ark/llms.txt` sirve cada página en Markdown (`…/docs/<página>.md`):

| Página | Qué dice del largo de las indicaciones |
|---|---|
| `create-video-generation-task-api.md` (`content.text`) | Ningún límite duro, para ningún modelo. Solo: «Recommended prompt length: no more than 500 Chinese characters or 1,000 English words. Lengthy text will lead to scattered information, and the model may ignore details…». Seedance 2.5 acepta también indicaciones en español. |
| `seedance-2-0-prompt-guide.md` | «Keep descriptions as concise as possible, avoid redundancy, and avoid semantic conflicts»; «Overly redundant copy can easily cause confusion… Remove irrelevant descriptions». |
| `video-generation-tutorial.md` | «remove unimportant parts, and place important content at the front». |
| `image-generation-api.md` (Seedream) | Tampoco hay límite duro: recomienda hasta 300 caracteres chinos o 600 palabras en inglés. |

Los topes de 3000 (`byteplus_ark.MAX_PROMPT_CHARS`) y 2950 (`media.MEDIA_PROMPT_BUDGET`) son
nuestros, del 2026-10-08 (commit 356f283b), cuando solo se usaba Seedance 1.0.

## 2. Qué cambió

Todo queda detrás de `MediaInputs.prompt_compiler_version = 1`, que se sella **solo en
ejecuciones nuevas** (`MediaProducer.prepare_new_brief`). El servicio no deja que quien llama la
elija. Un borrador ya congelado o pagado con la versión 0 se compila **byte a byte como antes**:
la fixture real sigue fallando con 2966.

| Ruta | Versión 0 | Versión 1 |
|---|---|---|
| Video en Seedance 2.x (clip de movimiento y de edición, video hablado, diapositiva animada) | se recortaba hasta 2950; fallaba si lo obligatorio no cabía | **sin tope de caracteres y sin recortes**. El único techo son las 1000 palabras recomendadas, sobre el texto completo que sale (con el diálogo). Pasar ese techo se **rechaza antes de pagar**. |
| Clip en Seedance 1.x | 2950 | el tope del adaptador, 3000 (el margen de 50 no tenía base) |
| Otras rutas de 1.x e imágenes (Seedream) | 2950 / 3000 | sin cambio |
| Adaptador (`byteplus_ark`) | 3000 para todo | Seedream y Seedance 1.x: 3000. Seedance 2.x: rechaza solo por encima de 1000 palabras, diálogo incluido (`SeedanceFamily.prompt_char_cap`, `VIDEO_PROMPT_MAX_WORDS`). |

**Clip de edición, versión 1:**
- La guía de replicación se quita **solo si coincide carácter por carácter** con la plantilla
  versionada (`qualify_creative/prompt_text.py`, que la pantalla también usa). Cada una de sus
  frases queda dicha por una línea fija en inglés, según una tabla de cobertura que hace cumplir
  una prueba. Si la guía no coincide, viaja literal.
- Se añade la línea `Client product: "…"` y los datos clave.
- La identidad de la marca va **entera y protegida**: nunca se recorta. Si un tope la obligara a
  recortarse, la pieza se rechaza antes de pagar.

**Verificación previa** (antes de la copia y del selector, que se pagan):
- Cada logo por separado **y todos juntos** tienen que caber.
- El clip de movimiento se compila con la copia más larga posible.
- En 2.x la verificación mide palabras; en 1.x, caracteres.
- Los mensajes en español dicen qué acortar y cuánto sobra («sobran {n} palabras/caracteres…»,
  «Elegiste {k} logos y no caben todos…»).

**Video hablado en 2.x:** el guion **nunca se corta ni se rechaza después de pagar**: se
dimensiona antes de escribirse (§9). Lo sigue limitando `SCRIPT_MAX` (2000 caracteres), como
antes.

**Procedencia** (parámetros del clip y traza): `prompt_compiler_version`, `prompt_chars`,
`prompt_words`, `prompt_budget` (null = sin tope de caracteres), `prompt_word_ceiling` y
`prompt_trims`.

## 3. Caso real (borrador `4ca40fc1`; la fixture conserva la estructura y los largos, con todos los textos de la marca sintéticos)

| Logos | Antes: sin recortar | Antes: lo que se enviaba (2950) | Versión 1 en 2.5 (nada recortado) | Versión 1 con la guía literal (alternativa) |
|---|---:|---:|---:|---:|
| imagotipo | 3368 c / 489 p | **rechazo** (mínimo 2966) | **2869 c / 407 p** | 3808 c / 566 p |
| isologo | 3340 c / 485 p | 2938 c / 425 p, sin identidad | 2841 c / 403 p | 3780 c / 562 p |
| isotipo | 3331 c / 486 p | 2950 c / 429 p, identidad de 1 carácter | 2832 c / 404 p | 3771 c / 563 p |
| imagotipo + isologo | 3447 c / 498 p | rechazo (3045) | 2948 c / 416 p | 3887 c / 575 p |
| imagotipo + isotipo | 3438 c / 499 p | rechazo (3036) | 2939 c / 417 p | 3878 c / 576 p |
| isologo + isotipo | 3410 c / 495 p | rechazo (3008) | 2911 c / 413 p | 3850 c / 572 p |
| los tres | 3517 c / 508 p | rechazo (3115) | 3018 c / 426 p | 3957 c / 585 p |

(c = caracteres, p = palabras separadas por espacios.)

- En la versión 1 las siete combinaciones salen sin recortes. Tienen la identidad entera, el
  producto, los datos clave, los 9 colores, las tipografías, el texto del operador literal y cada
  logo con su índice y su categoría. El guardián de calidad pasa en las siete, con «Debe evitar»
  lleno (0, 1, 3 y 5 frases) y «Debe mencionar» lleno.
- «Debe evitar» y «Debe mencionar» no cambian el pedido de video (+0). Reenviarlos sigue siendo
  decisión del fundador.
- El caso real queda a menos de la mitad del techo de 1000 palabras, incluso con la guía literal
  (572). Con el texto del operador al máximo del campo (1200 caracteres) y una identidad de 900,
  el pedido sigue entrando entero (lo comprueba una prueba).

## 4. Cada optimización del diseño, reevaluada sin el tope

Categorías: (a) sigue siendo necesaria; (b) mejora la calidad aunque no haya tope;
(c) neutra o innecesaria, se quita; (d) arriesgada para la calidad, se quita.

| Optimización | Cat. | ¿Queda? | Por qué |
|---|---|---|---|
| Quitar el tope de caracteres en 2.x | (a) | sí | Es el pedido del fundador. La documentación no fija ningún límite duro. |
| Techo de 1000 palabras en 2.x, rechazado antes de pagar | (a) | sí | Es la única cifra que publica BytePlus. Se mide sobre el texto completo, diálogo incluido. Ver §5. |
| Quitar la guía de replicación cuando coincide exacta con la plantilla | (b) | sí | Ya no hace falta para caber (con ella: 572 palabras). Se mantiene por calidad: la guía de Seedance 2.0 pide «avoid redundancy» y «remove irrelevant descriptions». La guía repite en otro idioma lo que ya dicen las líneas fijas, y 2 de sus 10 frases sobran (una apunta a un JSON ya retirado; la otra, «no hay análisis VLM», es una nota interna). Es duplicado de sentido, no de bytes: cada frase está cubierta en inglés y una prueba lo hace cumplir. Cualquier texto que no sea exactamente la plantilla viaja literal. Es la única decisión que solo una prueba A/B pagada puede confirmar. |
| Plantilla única para la pantalla y el compilador, con prueba de igualdad | (b) | sí | Sin ella, la coincidencia exacta se rompería en silencio. |
| Línea `Client product:` | (b) | sí | El producto solo aparecía dentro de la guía. |
| Datos clave en la ruta de edición | (b) | sí | Corrige una omisión: esta ruta nunca los mandaba. |
| La identidad nunca se borra | (b) | sí, ahora protegida | La versión 0 la perdía en todos los casos medidos. |
| Suelo duro de la identidad (`hard_floor`, primera oración) | (c) | **no** | La edición siempre corre en 2.5, sin tope: el suelo era código muerto. Lo reemplaza «protegida»: si algún día hubiera un tope, se rechaza en vez de recortar. |
| Recortar primero los metadatos no verificados del reel (suelo 0) | (c) | **no** | Sin tope no se recorta nada. |
| Comilla de apertura en `Client identity: "…"` | (b) | sí | Antes se cerraba una comilla que nunca se abría (+1 carácter). |
| Presupuesto de 3000 en clips de 1.x | (a) | sí | El adaptador de 1.x sigue rechazando más de 3000. El margen de 50 no tenía base. |
| Verificación previa del peor caso (cada logo y todos juntos) | (a) | sí | Hace falta mientras exista algún techo: palabras en 2.x, caracteres en 1.x. Evita pagar copia y selector por una pieza imposible. |
| Copia de peor caso en el clip de movimiento | (a) | sí | El gancho y el llamado a la acción son líneas fijas que se pagan después de la verificación. Pesa sobre todo en 1.x. |
| Mensajes que dicen qué acortar y cuánto | (a) | sí | Necesarios en cualquier rechazo. |
| Registro de recortes y procedencia | (a) | sí, más palabras y techo | Requisito de procedencia. Muestra que en 2.x no se recorta nada. |
| Versión del compilador (`prompt_compiler_version`) | (a) | sí | No reinterpreta borradores ya congelados. |

Ninguna optimización cayó en (d).

## 5. Qué hacer al pasar las 1000 palabras (pedido del fundador)

Coincido con la preferencia del fundador:
- Registrar siempre las palabras y el techo en la traza y en los parámetros.
- No recortar nunca.
- Rechazar antes de pagar solo por encima de 1000 palabras, con un mensaje que nombre qué
  acortar.

Dos matices:
1. El conteo es por palabras separadas por espacios y cuenta también el texto en español. Para
   el caso real da números parecidos a los de la documentación (407 palabras ≈ 2869 caracteres).
2. La documentación habla de calidad, no de un error del servicio. Si se quiere cuidar la
   calidad antes del techo, propongo un **aviso** (no un rechazo) a partir de ~800 palabras. No
   lo implementé: necesita un lugar en la pantalla y una decisión del fundador.

En el video hablado el guion sale de la copia, así que el techo se comprueba después de pagar la
copia, pero antes del video. La verificación previa solo puede medir la parte de movimiento.

## 6. Pruebas

- `packages/api/tests/test_prompt_budget_v1.py`, 75 pruebas:
  - versión 0 idéntica;
  - las 7 combinaciones × 4 escenarios de «Debe evitar» con el guardián de calidad;
  - textos largos enteros;
  - guía alterada o metadatos que no corresponden: viajan literales;
  - presupuestos por familia y versión, y límites de caracteres y de palabras;
  - verificación previa en palabras (logos juntos, texto del operador) y en 1.x (copia de peor
    caso);
  - video hablado y diapositiva animada en 2.x;
  - procedencia.
- Guardián: `packages/api/tests/prompt_quality.py::assert_prompt_keeps_intent`. Con
  `budget=None` exige 1000 palabras o menos, cero recortes y la identidad entera.
- Adaptador: `packages/creative/tests/test_byteplus_adapter.py`. En 2.x no hay tope de
  caracteres, el techo de palabras cuenta el diálogo y 1.x conserva el tope.
- Suites (Windows, sin red): `packages/api/tests -k "creative or brand or v9 or scene or resource
  or logo or clip or video or prompt"` → 1361 aprobadas, 4 fallidas (antes del cambio: 1253 y
  11); `packages/creative/tests` + `Qualify/test_generator_voice_and_copy.py` +
  `Qualify/test_reel_replication.py` → 700 aprobadas. Ruff 0.17.1 limpio en los 13 archivos tocados.
- Ajenos y sin tocar: `test_creative_media.py::test_the_chosen_logo_takes_the_templates_logo_slot`
  (al doble le falta el lector de recursos) y las 3 de `test_creative_memory_harness` (`bash` de
  Windows no encuentra `python`).

## 7. Lo que no se verificó y qué haría falta

- No hubo llamadas a BytePlus ni a Anthropic. Ninguna afirmación sobre la calidad visual está
  medida.
- **Prueba A/B que lo mediría** (requiere autorización del fundador y la llave de evaluación
  `QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY`):
  - mismo borrador real, mismo video de referencia, misma semilla, Seedance 2.5 en modo
    borrador a 480p;
  - brazo A: versión 1 (sin la guía duplicada); brazo B: versión 1 con la guía literal;
    opcionalmente un brazo C, la versión 0 sin recortar (3368 caracteres);
  - unas 5 réplicas por brazo con los 3 logos;
  - ventana de 23:00 a 05:00 hora de Bogotá, con 3 tareas a la vez como máximo
    (`qualify-measure`);
  - calificación ciega con una rúbrica: logo correcto en cada superficie, colores, producto,
    ningún rastro de la marca ajena, ritmo del original;
  - costo estimado: con la tabla de precios vigente, ~USD 0,5 por tarea de 5 s → ~USD 7–8 por
    15 tareas.
- Seedream no se tocó: tampoco tiene límite duro (recomienda 600 palabras). Quitarle el tope de
  3000 merece su propio ticket, con la misma lógica.
- La nota menor del diagnóstico («Image 2» frente a «@Image1») no se tocó.

## 8. Revisión independiente (2026-11-02) y opción del fundador

**Arreglos tras la revisión** (sin cambio en las cifras del §3):

1. **Peor caso en palabras.** Las copias de peor caso eran «una palabra larga por campo»: en
   2.x, donde el techo es de palabras, no medían nada. Ahora hay cuatro formas: con y sin
   tomas, densas en caracteres (para 1.x) y densas en palabras, con palabras de 2 letras más
   espacio (para 2.x). Una palabra de 1 letra rechazaría clips reales: el español promedia ~5
   letras por palabra.
   - Caso real en modo movimiento con los 3 logos: 412 palabras sin copia y 769 con la peor
     copia densa. Queda margen para el texto del operador más largo que admite el campo.
   - La verificación previa también compila la línea «Image N: style guide» que agrega el
     selector cuando convierte una foto en guía de estilo.
2. **Video hablado en 2.x: el guion se mide antes de pagar.** (Reemplazado por §9: ya no
   hay ajuste del guion en la ejecución.)
   - Guion escrito por el operador (`own_script`): la verificación previa lo cuenta entero. Si
     no cabe, se rechaza antes de la copia con «Tu guion es muy largo para este video: sobran
     N palabras. Acórtalo y vuelve a intentarlo.».
   - Guion generado: la verificación previa reserva 133 palabras (400 caracteres a 3 por
     palabra) y nombra lo que el operador puede acortar (su texto, los datos clave, las notas).
     En la ejecución, si la copia ya pagada pasara el techo, el guion se ajusta a las palabras
     que quedan en vez de rechazar la pieza. Con un movimiento de ~250 palabras quedan ~750:
     en la práctica no ocurre.
3. **Datos reales fuera del repositorio.** La fixture conserva la estructura y cada largo, pero
   el posicionamiento, el público, los ejemplos, los llamados a la acción, las afirmaciones
   prohibidas, el texto del operador, el pie del reel, la paleta, las tipografías y los hashes
   son sintéticos. Mismos caracteres y mismo número de palabras: 2966 y todas las cifras del §3
   se reproducen igual. El plan y el diagnóstico ya no nombran la marca ni llevan los
   identificadores completos.
4. Ver «Opción» más abajo.
5. **Guardián.** La frase «not its photo background/props» solo se exige si hay una foto de
   producto (`REPLICATION_COVERAGE_NEEDS_PRODUCT_PHOTO`); hay prueba para edición sin fotos y
   solo con guía o lugar. El guardián es **independiente solo en parte**: reutiliza el
   reconocedor de la plantilla (`known_replication_prose`) y la tabla de cobertura, que son el
   contrato que comprueba.
6. **Producto.** Si el operador cambió de producto después de elegir el reel, va el producto
   actual (`product_ref`), no los dos.

**Opción del fundador: «textos de marca» en la réplica** (`MediaInputs.replication_brand_text`,
**apagada por defecto**). Responde a la frase de la guía «Aplica MI identidad de marca por
encima: los colores, la tipografía, los textos y el CTA del Brand Kit y del contexto que yo doy
tienen prioridad sobre el look del reel ajeno.».

- **Apagada:** el pedido es byte a byte el de la versión 1 (los colores y las tipografías ya
  van). La regla sigue diciendo «no inventes llamados a la acción».
- **Encendida:**
  - Viajan, entre comillas y como datos, los llamados a la acción aprobados del Brand Kit
    (`cta_patterns`), solo para reemplazar texto que el reel **ya muestra**.
  - La regla de texto se reescribe para no contradecirlo: «solo en superficies donde @Video1 ya
    muestra texto; no inventes superficies de texto nuevas, promociones…».
  - Sin llamados a la acción en el Brand Kit, no cambia nada.
- Solo la lee el compilador 1. Se registra en los parámetros del clip.
- La verificación previa cuenta sus palabras. El guardián exige cada llamado a la acción literal
  y que ninguna regla prohíba lo que se lleva.

## 9. Tercera ronda (2026-11-02): guion dimensionado, frases ajenas y mensajes

**Video hablado en 2.x: el guion se dimensiona antes de escribirse** (decisión del fundador:
ni cortar ni rechazar después de pagar).

1. Antes de llamar a Claude, `MediaProducer.talking_script_word_budget` calcula las palabras
   que le quedan al guion: 1000 menos el movimiento más largo que el selector todavía puede
   producir (cada logo solo y todos juntos; en el caso real el peor es **un** logo, porque
   las variantes adicionales usan un bloque más corto) menos el envoltorio del diálogo. Si no
   alcanzan para una línea útil (133 palabras), la verificación previa rechaza antes de
   cualquier pago, con un mensaje que nombra qué acortar.
2. Ese número viaja a la copia como límite duro: «about N words … HARD LIMIT: at most N
   words», con N el menor entre la meta por segundos y lo que queda. Sin presupuesto (versión
   0, Seedance 1.x o guion escrito por el operador) el pedido de copia es byte a byte el de
   antes.
3. El guion devuelto se cuenta en palabras. Si se pasa, se pide a Claude **una** reescritura
   dentro del límite; su costo queda registrado como otra llamada de copia. Si aun así se pasa
   (en la práctica imposible tras un límite explícito y una reescritura), se trata como **error
   del proveedor**, por el mismo camino de cualquier copia fallida (costo registrado, versión
   anterior conservada). Lo elegí porque es Claude quien no respetó su instrucción, no el
   pedido del dueño. Nunca se corta el guion.
4. Se registran en los parámetros y la traza del video: `prompt_compiler_version`,
   `prompt_words` (movimiento + diálogo), `prompt_word_ceiling`, `spoken_chars`,
   `script_words`, `script_word_budget` y `script_rewrites`.
5. Cambio en el pedido de copia: solo cuando hay presupuesto. Necesita medirse con
   `just eval-copy` antes de activarlo para todos (no se corrió: es pagado).

**Frases de la marca ajena.** La frase «No imites su paleta, sus fuentes ni sus textos» ahora
tiene su línea en inglés, igual con la opción de textos de marca encendida o apagada: «Do not
keep the source-owner's slogans or wording; neutral or mandatory labels stay.». La tabla de
cobertura y el guardián la exigen. +85 caracteres / +13 palabras en cada combinación (cifras
del §3 actualizadas).

**Mensajes de rechazo** (revisión de UX, `qualify-copy-es`):

- Con la opción de textos de marca encendida, la primera salida es apagarla: «Tu video tiene
  demasiado texto: sobran N palabras. Apaga «Usar tus frases para invitar a comprar» o acorta
  lo que escribiste en «¿Qué quieres en el clip?» y vuelve a intentarlo.».
- Si el texto del dueño alcanza para cubrir el exceso: «Hay demasiado texto para este video:
  sobran N palabras. Acorta lo que escribiste en «¿Qué quieres en el clip?» a unas X palabras
  (ahora tiene Y) y vuelve a intentarlo. Conservaremos todos los recursos que elegiste.». En
  caracteres (1.x): «…y déjalo en unos X caracteres (ahora tiene Y)…».
- Se cuentan solo las palabras del dueño (sin la guía de replicación ni el JSON del reel).
- Los campos se nombran como se ven en pantalla: el encabezado de cada tipo de pieza, «tus
  «Datos clave»», «lo que escribiste sobre cuándo usar tus logos (en Tu marca, en «Logo»)».
- «Elegiste N logos…» vale ahora para cualquier tipo de pieza, no solo clips. La verificación
  del peor caso se mantiene para todas las piezas de la versión 1.
- Los mensajes genéricos ya no hablan de «indicaciones», «modelo de video» ni «texto de la
  escena»: «Hay demasiado texto para esta pieza: necesita N caracteres y admite M. Acorta lo
  que escribiste o quita alguno de los recursos que elegiste y vuelve a intentarlo.».
- «Tu guion es muy largo…» queda solo para el guion que escribió el dueño.

**Opción de textos de marca:** se aplica y se registra solo en réplicas de reel
(`clip_reference_mode == "edit"`). `ContentService.create` la apaga en cualquier otra pieza.

## 10. Cuarta ronda (2026-11-02): nada se rechaza después de pagar

1. **Guion vacío.** Si la copia no trae guion, el video dice gancho + texto + llamado a la
   acción, sin dimensionar. Ahora la etapa de copia mide **exactamente lo que se va a decir**
   (`MediaProducer.copy_overage`). Un guion vacío o pasado de presupuesto en un video hablado
   dimensionado pide la reescritura acotada.
2. **Mensaje del video hablado.** Su rechazo previo llega sin reescribir: el exceso cuenta
   movimiento + guion. Con guion propio dice «Tu guion es muy largo…».
3. **Vista previa del pedido de copia.** Aplica el mismo presupuesto de guion que la llamada
   real (`preview_script_word_budget`, con los recursos leídos en vivo).
4. `Qualify/brand_kit_editor.py` usa `catalog_vm.return_path_from_query`.
5. **Peor caso del clip.** Con palabras de 1 letra, el caso real en modo movimiento con los 3
   logos mide 955 palabras con un texto del operador de 45. Quedarían ~45 palabras libres, y
   el campo admite ~200: se rechazarían clips reales. Se mantiene la medición con palabras de
   2 letras (769 palabras) y se añade la misma salvaguarda que en el video hablado: la copia
   devuelta para un clip de movimiento en 2.x se compila con cada combinación de recursos y
   roles. Si pasara las 1000 palabras, se pide **una** reescritura acortando gancho, llamado
   a la acción y tomas, con su costo registrado. Si aun así no cabe, es error del proveedor.
   El clip nunca se rechaza por largo después de pagar por un pedido del dueño.

Hallazgo de las pruebas: en el video hablado, el primer fotograma (Seedream, tope de 2950) se
verifica antes que el movimiento. Con el texto largo del caso real ese primer fotograma ya se
pasa del tope (368 caracteres), y se rechaza antes de pagar. Seedream no se cambió.

## 11. Quinta y sexta ronda (2026-11-02): imágenes de Seedream

**Ronda 5, cancelada.** Quitar el tope de caracteres de Seedream se revirtió por decisión del
fundador: viene una versión nueva de Seedream. Mientras tanto, Seedream conserva sus
2950/3000 caracteres.

**Diagnóstico de los dos volantes rechazados** (borradores `75d29899…` y `166eedb7…`,
lectura de solo lectura, código de la ronda 3):

- Las dos piezas tienen las mismas entradas: 3 logos sin notas, fondo de Inspiración, 2 fotos
  (una guía de composición y una de producto), 3 datos clave, 3 de «Debe mencionar» y 3 de
  «Debe evitar». Solo cambió la escena: 287 caracteres en la primera, 260 en la segunda.
- La verificación previa es **determinista**. La parte fija **no creció**.
- Necesario por combinación de logos:

  | Escena | isotipo | imagotipo | isologo | los tres |
  |---|---:|---:|---:|---:|
  | 287 caracteres | 2962 | 2999 | 2971 | 3148 |
  | 260 caracteres | 2908 | 2945 | 2917 | 3094 |

- La verificación se detenía en la **primera** combinación que no cabía y daba su exceso: 12,
  el del isotipo. El peor era el de los tres logos juntos: 198. Al acortar a 260, los logos
  por separado ya cabían y apareció el de los tres juntos: 144.
- **Arreglo:** se miden todas las combinaciones y el rechazo dice el **peor** exceso, una sola
  vez.

**Limpieza del pedido de imagen** (versión 1, sin perder intención, el tope se mantiene):

1. En un volante, el tema **es** la escena (`_effective_topic`), así que el mismo texto viajaba
   dos veces: «Scene the client asked for» y «The post is about». Con la versión 1, el segundo
   se omite solo si coincide exactamente. Lo mismo en las diapositivas de galería. Si el tema
   es distinto, viaja.
2. La regla de texto repetía lo que ya dice la línea de tipografías: etiquetas en su tipografía
   y letras del logo como su imagen exacta. Con la versión 1 se quita esa primera oración solo
   cuando la línea de tipografías la dice. El resto de la regla queda («no invented text…»).

Resultado con el volante real (escena de 287 caracteres; nada recortado, guardián en verde):

| Logos | Antes (ronda 3) | Versión 1 |
|---|---:|---:|
| isotipo | rechazo 2962 | 2553 |
| imagotipo | rechazo 2999 | 2590 |
| isologo | rechazo 2971 | 2562 |
| los tres | rechazo 3148 | 2739 |

Con la escena de 260 caracteres: 2526 / 2563 / 2535 / 2712. Queda margen para la escena más
larga que admite el campo (600 caracteres): en el peor caso, los tres logos, unos 3051. Eso
todavía no cabe, y se rechaza antes de pagar con el exceso completo.

Guardián de imagen: `prompt_quality.assert_image_prompt_keeps_intent` (volante y diapositiva).
Pruebas: `packages/api/tests/test_image_prompt_v1.py`.

## 12. Ronda 7b (2026-11-02): repeticiones exactas en los pedidos de video

Con Seedance 2.x no hay tope. Quitar una repetición exacta es ganancia de calidad: la
documentación advierte que con un texto largo el modelo «may ignore details». Todo va solo en la
versión 1; la versión 0 queda byte a byte igual.

1. **Regla de etiquetas repetida.** «Preserve authentic product/manufacturer labels and the
   exact supplied logo lettering.» repetía la línea de tipografías, que ya dice «Keep supplied
   logo lettering as its exact image, never redraw it. Preserve authentic product labels in
   their original typeface.». Se quita en el clip de movimiento, en la diapositiva animada y en
   el video hablado, solo cuando la línea de tipografías lo dice.
2. **Réplica: fotos del mismo rol juntas.** Antes iban «@Image1: real product identity/…» y
   «@Image2: real product identity/…», la misma oración. Ahora va «@Image1, @Image2: real
   product identity/…», como ya lo hacía el clip de movimiento.
3. **Verificación previa del video hablado.** Su rechazo lleva el exceso, así que se compara con
   las demás combinaciones de recursos y se informa el **peor**.
4. **Traza.** «referencias: 2 fotos + 1 recurso de marca · 1 video · 0 audios». Antes decía «2
   imágenes»: el logo viajaba, como imagen 3 con el rol `integrated_logo`, pero no se contaba.
5. **Guardián.** La misma oración con otro número de imagen cuenta como repetida. El guardián
   cubre ahora el clip de movimiento, la réplica (con y sin textos de marca), el video hablado
   y la diapositiva animada (`assert_video_prompt_keeps_intent`).

Antes → después, con el caso anonimizado (c = caracteres, p = palabras):

| Ruta | Antes | Después |
|---|---:|---:|
| Clip de movimiento, 1 logo | 2723 c / 413 p | 2637 c / 403 p |
| Clip de movimiento, 3 logos | 2872 c / 432 p | 2786 c / 422 p |
| Diapositiva animada con video de referencia, 3 logos | 2001 c / 287 p | 1915 c / 277 p |
| Video hablado, 1 logo | 1851 c / 255 p | 1765 c / 245 p |
| Réplica, 2 fotos, textos de marca apagados | 2952 c / 415 p | 2878 c / 408 p |
| Réplica, 2 fotos, textos de marca encendidos | 3187 c / 454 p | 3113 c / 447 p |
| Réplica real `2174b4df…` (registrada) | 3469 c / 506 p | ≈ 3395 c / 499 p |

**Ronda 8: fusiones de sentido, aplicadas.** El fundador aprobó: «sí, haz las fusiones si no
hay una degradación en la calidad». Cada frase quitada se partió en unidades de sentido, y cada
unidad sigue dicha en lo que queda. El guardián lo exige en todas las combinaciones de logos.

1. **Clip de movimiento: el nombre del producto pasa a la línea de su foto.** Se quita «It shows
   the client's real product, "<p>", exactly as it is: shape, colors, label.». La línea que queda
   dice: «Images 1 and 2: the client's real product, "<p>", shown in the video — keep it exactly as
   it is (shape, colors, label).».

   | Unidad de la frase quitada | Dónde sigue |
   |---|---|
   | se muestra en el video | «shown in the video» |
   | es el producto real del cliente | «the client's real product» |
   | el nombre del producto, literal | `"<p>"` |
   | tal como es | «keep it exactly as it is» |
   | forma, colores, etiqueta | «(shape, colors, label)» |

   Solo se aplica si hay fotos de producto. Sin fotos, o solo con lugar o guía de estilo, la
   frase queda como antes (probado).
2. **Video hablado: «Every selected brand resource is mandatory…».** Ya no va entera. Va solo
   lo que el bloque de recursos no dice, en una línea más corta: «Keep each resource's
   requested presence/action across all relevant shots and cuts.». Se aplica solo si el bloque
   contiene sus tres frases; si no, va la frase original.

   | Unidad de la frase quitada | Dónde sigue |
   |---|---|
   | cada recurso es obligatorio / no omitir | bloque: «Integrate EVERY reference below in its own role; none is optional.» |
   | su rol | bloque: «in its own role» |
   | identidad y colores | bloque: «exact identity/colors/proportions» |
   | presencia/acción pedida, en todas las tomas **y cortes** | línea nueva (el bloque solo decía «consistent across shots») |
   | no inventar objetos | bloque: «no invented marks/props» |

Cifras con las fusiones (además de lo de la ronda 7b):

| Ruta | Ronda 7b | Ronda 8 |
|---|---:|---:|
| Clip de movimiento, 1 logo | 2637 c / 403 p | 2581 c / 394 p |
| Clip de movimiento, 3 logos | 2786 c / 422 p | 2730 c / 413 p |
| Video hablado, 1 logo | 1765 c / 245 p | 1649 c / 226 p |
| Video hablado, 3 logos (redacción corta) | 1659 c / 224 p | 1543 c / 205 p |

Pruebas: `packages/api/tests/test_video_prompt_v1.py`.
