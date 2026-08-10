# Spike: detección de *hooks* publicitarios en vídeo corto (inmobiliario)

**Owner:** datasci (FDE) · **Fecha:** 2026-08-05, **corregido el 2026-08-06** · **Estado:** Fases A y B entregadas; **Fase C esperando al fundador (cuentas y etiquetado) y al runner de corpus**, que no es de este paquete; Fase D diseñada y ejecutable, sin datos.

> **CORRECCIONES 2026-08-06 — lee esto antes que nada si ya habías leído este documento.** Dos, y ninguna es cosmética:
>
> 1. **El "prerrequisito técnico no negociable" no existía.** La versión anterior decía que había que desbloquear un VLM alojado porque *"featherless-ai rechaza esta cuenta"*. **Era falso.** El VLM alojado funciona y siempre funcionó; lo que estaba mal era un valor por defecto de mi propio CLI. El corpus de 217 vídeos pasa de **84 h a 0,9 h** de reloj y **no necesita GPU**. Detalle en §B.5; lo que sí sigue bloqueando, en §C.6.
> 2. **El nivel léxico era peninsular y el corpus es de la frontera colombo-venezolana.** No rompía: devolvía valores plausibles y equivocados —`price_reveal` hundido en el lado colombiano, `command_cta` desaparecido para quien habla de *usted*—. Corregido y medido en **§B.2.1**, con un test de refutación nuevo (**F5**, §A.3) porque el registro *usted*/*tú* es además un confusor entre países.
**Alcance:** spike. No es la Parte 3. No hay Celery, ni R2, ni esquemas `ingestion`/`search`/`signals`. Salida a disco (JSON + CSV) y punto.

**Encargo, en palabras del fundador:** *"si el vídeo arranca con '¿estás cansado de la ciudad?' y muestra un terreno de campo, y eso correlaciona con 10.000 likes y comentarios positivos, quiero detectar que **el hook fue arrancar así**"* — y correrlo contra vídeos de varios asesores inmobiliarios.

**Precedente que este documento respeta o refuta explícitamente:**
- `NOTES_fase0_agentive_layer.md:166` — el valor no es la descripción, es **extracción estructurada de rasgos comparables entre posts**, con prompt y esquema distintos a los de la cascada de Fase 1, sobre la misma costura `Provider`. **Respetado, es la base de la Fase B.**
- `NOTES_fase0_agentive_layer.md` §3.2 — "por qué funcionó este post" no es contestable para una sola cuenta. **Respetado y extendido**: la Fase D describe qué diseño sí es contestable con varias cuentas, y cuál es el n mínimo.
- `docs/ingenieria-inversa-sortfeed.md:396` — "Viral hooks library" es GO-WITH-CHANGES y **exige definir 'hook'**. **Esa condición se cierra aquí, en la Fase A.**
- `docs/research-features-gtm.md:52` — **Kuli ya vende esto** ("breaks down the hook, audio, pacing, caption"). En este documento no se afirma en ningún sitio que nadie lo haga.

---

## Índice

- [Fase A — qué es un "hook", operativamente](#fase-a)
- [Fase B — el extractor y su esquema de salida](#fase-b) · [B.2.1 dialecto de la frontera](#fase-b)
- [Cómo ejecutarlo](#como-ejecutarlo)
- [Fase C — el corpus: cuánto hace falta y cuánto cuesta](#fase-c)
- [Fase D — la correlación: qué se puede y qué no se puede concluir](#fase-d)
- [Provenance](#provenance)

<a id="fase-a"></a>

## Fase A — qué es un "hook", operativamente

`sortfeed.md:396` puso una condición y nadie la cumplió: **definir "hook"**. Sin definición operativa, todo lo que viene después es ruido con decimales. Ésta es la definición que implementa el código, y está escrita para poder ser refutada.

### A.1 La definición

> **Hook** = todo lo que la plataforma le entrega al espectador durante los **primeros 3 segundos** del vídeo, en **tres canales simultáneos**:
> 1. **lo dicho** — la transcripción del audio en esa ventana,
> 2. **lo mostrado** — la secuencia de fotogramas de esa ventana (escenario, personas, encuadre, ritmo de corte),
> 3. **lo escrito en pantalla** — el texto sobreimpreso, que en vídeo corto suele llevar el gancho **aunque no haya voz**.
>
> El hook es **el trío**, no cualquiera de los tres por separado. Un vídeo sin voz con un rótulo "*Nadie te dice esto antes de comprar*" sobre un dron de una parcela **tiene hook**; medir sólo transcripción lo habría contado como "sin hook".

**Lo que explícitamente NO es hook aquí:** el caption del post, los hashtags, la portada/cover elegida, la hora de publicación y el sonido de tendencia. Son variables reales y probablemente influyentes, pero **no viven en los primeros 3 segundos del fichero de vídeo**. Aparecen en la Fase D como **confusores**, no como rasgos del hook. Mezclarlos sería exactamente el error que produce una conclusión falsa que suena bien.

### A.2 Por qué N = 3 s y no otro

Tres razones, y ninguna es "porque lo dice el marketing":

1. **Lingüística — es el ancho mínimo que cabe una frase entera.** En español conversacional el ritmo está en torno a 2,5–3,3 palabras/segundo. A 3 s eso son ~8–10 palabras: una oración completa. El propio ejemplo del fundador, *"¿estás cansado de la ciudad?"*, son 5 palabras ≈ 1,8 s. Con N=2 s se corta a la mitad y el clasificador ve *"¿estás cansado de…"*, que es otra cosa. Con N=3 s entra completa y sobra margen.
2. **Visual — es el ancho mínimo que contiene una *secuencia*, no una foto.** El montaje de vídeo corto corta cada 1–2 s. A 30 fps, 3 s son 90 fotogramas y típicamente 2–3 planos: suficiente para medir ritmo de corte y cambio de escenario. Con N=1 s mides una imagen fija y el "ritmo" no existe.
3. **Por arriba — pasados ~7 s ya no describes la apertura, describes el cuerpo del vídeo.** Ese es el límite superior del rango que tiene sentido explorar.

### A.3 Cómo se falsa esta definición (y por qué el código la deja falsable)

**La definición es una hipótesis, no un axioma**, así que el extractor emite los rasgos **a tres ventanas anidadas: 3 s, 5 s y 7 s**, en la misma pasada. Los rasgos deterministas y léxicos de las tres ventanas son gratis (no cuestan ni una llamada a modelo), así que la comparación no tiene coste.

Criterios de refutación, escritos por delante para que no se puedan reinterpretar después:

| # | Si ocurre esto… | …entonces la definición está mal y cambia así |
|---|---|---|
| F1 | Con el corpus de Fase C, la asociación hook↔rendimiento es **sistemáticamente más fuerte en la ventana de 7 s** que en la de 3 s | N sube. La apertura útil es más larga de lo que dice A.2 |
| F2 | Más del ~30 % de los vídeos del corpus salen `hook_type = none_detected` en 3 s pero tienen tipo claro en 5–7 s | N sube. 3 s corta demasiado en este nicho concreto |
| F3 | El canal **texto en pantalla** resulta vacío en casi todo el corpus | El hook es par (dicho+mostrado), no trío. Se simplifica |
| F4 | Dos personas etiquetando a mano el mismo vídeo asignan `hook_type` distinto **más del 20 % de las veces** | La taxonomía A.4 no es medible; hay que fusionar categorías antes de medir nada |
| F5 | El **registro de trato** (`second_person_register`: *tú* / *usted*) resulta asociado al rendimiento, **o** se reparte de forma marcadamente desigual entre los dos países del corpus | El registro deja de ser un detalle de parseo y pasa a ser **confusor de pleno derecho** en §D.3: hay que estratificar por registro, o por país, antes de comparar tipos de hook — y si no hay n para estratificar, el informe lo dice y no compara |

**F4 es la que hay que comprobar primero y es la más barata**: 30 vídeos, dos personas, media hora. Si la taxonomía no es reproducible entre humanos, ningún modelo la va a reproducir tampoco, y todo lo demás sobra.

**F5 se añade el 2026-08-06, cuando el corpus dejó de ser hipotético.** El nicho elegido —San Cristóbal (Táchira, VE) y Cúcuta (Norte de Santander, CO)— es **dos países en un solo corpus**, y el registro de trato es justo la variable que los separa: Santander es territorio de *usted*, y el Táchira lo usa mucho más que Caracas. El riesgo no es lingüístico, es estadístico: si los asesores colombianos hablan de *usted* y los venezolanos de *tú*, entonces **"registro" y "país" son la misma columna con dos nombres**, y país arrastra mercado, moneda, poder adquisitivo y algoritmo. Un efecto atribuido al hook podría ser un efecto de frontera. Por eso el registro **se mide y se guarda en cada fila** (`second_person_register`), en vez de resolverse a un booleano: una variable que no está en la tabla no se puede controlar después. Nótese que F5 se cumple **también** si el registro no correlaciona con el rendimiento pero sí se reparte por país — el reparto desigual basta para exigir estratificación.

### A.4 La taxonomía de tipo de hook (vocabulario cerrado)

Para que dos posts sean **comparables** el tipo tiene que salir de una lista cerrada; prosa libre no se agrega. 11 categorías + 2 de escape:

| `hook_type` | Qué es | Ejemplo (inmobiliario) |
|---|---|---|
| `question` | Abre preguntando al espectador | *"¿Estás cansado de la ciudad?"* |
| `pain_point` | Nombra un problema del espectador sin preguntar | *"Pagas 900 € de alquiler por 45 m²."* |
| `direct_claim` | Afirmación rotunda sobre el inmueble/mercado | *"Esta casa cuesta menos que tu coche."* |
| `curiosity_gap` | Promete algo que aún no enseña | *"No vas a creer lo que hay detrás de esta puerta."* |
| `numeric_list` | Abre con un número que estructura el vídeo | *"3 cosas que nadie te dice antes de comprar."* |
| `negation_warning` | Advierte / prohíbe | *"No firmes nada sin ver esto."* |
| `command_cta` | Imperativo directo | *"Mira este salón."* |
| `personal_story` | Primera persona, anécdota | *"Hace dos años yo vivía en un piso interior."* |
| `social_proof` | Testimonio o cifra de terceros | *"Esta familia lo compró en 3 días."* |
| `price_reveal` | Abre con el precio como gancho | *"85.000 €. Con parcela."* |
| `location_reveal` | Abre con el sitio como gancho | *"Esto está a 40 minutos de Madrid."* |
| `none_detected` | Ni voz ni texto en pantalla en la ventana | (dron mudo con música) |
| `unknown` | El modelo no devolvió una categoría válida | (fallo de parseo — **nunca se rellena a ojo**) |

`none_detected` y `unknown` son **categorías distintas a propósito**: la primera es un hallazgo sobre el vídeo, la segunda es un fallo del extractor. Confundirlas contamina cualquier estadística posterior.

<a id="fase-b"></a>

## Fase B — el extractor y su esquema de salida

### B.1 Qué se ha construido

Un paquete nuevo, `packages/models/src/qualify_models/hooks/`, **sin tocar nada de la cascada de Fase 1**:

| Fichero | Qué hace | ¿Necesita modelo? |
|---|---|---|
| `spec.py` | La definición de la Fase A como constantes: ventanas, fps de muestreo, taxonomía cerrada | No |
| `media.py` | ffmpeg: muestrea los fotogramas de la ventana, extrae el audio de la ventana, monta la *hoja de contactos* | No |
| `visual.py` | Rasgos deterministas de píxel: cortes, movimiento, brillo, saturación, paleta | No |
| `lexical.py` | Marcadores de superficie en español + clasificador léxico de tipo de hook | No |
| `vlm.py` | El prompt del hook y el parseo estricto a JSON | Sí (VLM) |
| `extract.py` | El orquestador: mp4 → una fila `HookFeatures` | Opcional |
| `schema.py` | El esquema de salida + la fila plana para CSV | No |
| `analysis.py` | Fase D: normalización dentro de cuenta, efectos, potencia, confusores | No |
| `corpus.py` | Fase C: tamaño de corpus y coste | No |
| `cli.py` | `python -m qualify_models.hooks` | — |

**Reutiliza la costura `Provider` tal cual**: `VisionProvider` y `TranscriptionProvider` se inyectan igual que en la cascada. Cambiar Qwen3-VL local por un VLM alojado, o whisper alojado por uno propio, es un argumento del constructor. **No se ha bifurcado el pipeline.**

**Es un prompt distinto y un esquema distinto**, exactamente como pedía `NOTES_fase0_agentive_layer.md:166`: el prompt de la cascada pide una descripción en prosa para *brand listening*; éste pide un objeto JSON con vocabulario cerrado. No comparten ni una línea.

### B.2 Los tres niveles de rasgo (y por qué importa la distinción)

Cada columna de la salida pertenece a uno de tres niveles, y **la confianza que merece depende del nivel**:

| Nivel | Qué es | Coste | ¿Necesita golden set? |
|---|---|---|---|
| **Determinista** | Píxeles: `cut_count`, `motion_energy`, `brightness`, `saturation`, `dominant_colors` | 0 € | **No.** Es aritmética, es exacto y es reproducible |
| **Léxico** | Regex sobre el transcript: `has_question_mark`, `has_second_person`, `has_price_token`, `hook_type_lexical` | 0 € | **No para el marcador**, sí para el transcript que lo alimenta (WER) |
| **De modelo** | Lo que escribe el VLM: `setting`, `face_present`, `on_screen_text`, `text_density`, `hook_type_vlm` | VLM | **Sí. Es el único nivel que hay que validar antes de creérselo** |

Esto no es pedantería de esquema: significa que **si el VLM resulta poco fiable, el análisis de la Fase D no se queda a cero.** Los niveles determinista y léxico siguen en pie, y `hook_type_lexical` sigue existiendo como clasificador independiente.

Detalle de idioma que costó un test y merece quedar escrito: **el español elide el pronombre.** *"¿Estás cansado de la ciudad?"* interpela al espectador sin que aparezca ningún "tú". Un detector de segunda persona basado sólo en pronombres se habría dejado la mayoría de los hooks — justo el marcador más interesante. `lexical.py` detecta además las formas verbales, y distingue `estás` (verbo) de `estas` (demostrativo, "estas casas") comprobando el texto **con** tildes para ese caso.

#### B.2.1 Dialecto: el nivel léxico era peninsular y el corpus no lo es (corregido 2026-08-06)

El fundador eligió el nicho: **San Cristóbal (Táchira, VE) y Cúcuta (Norte de Santander, CO)**. Eso contesta mi pregunta C.5.3 —ni España ni "LatAm" en genérico, sino **la frontera colombo-venezolana**— y obligó a revisar este fichero entero, que estaba escrito en español peninsular. **El modo de fallo era el peligroso: nada reventaba, devolvía valores plausibles y equivocados.** Medido antes y después, con las tres afirmaciones que me llegaron:

| Afirmación | Veredicto | Medida |
|---|---|---|
| `has_price_token` es "de forma de euro" y no ve los precios de la región | **Confirmada a medias** | **Venezuela ya funcionaba** (los inmuebles se cotizan en dólares y `$`/`dólares` ya estaban): 3/4. **Colombia no**: 0/4 en *"250 millones de pesos"*, *"300 millones"*, *"180 millones"*, *"300 palos"* — que es como se dice un precio en Cúcuta. El único caso que acertaba (*"250.000.000 COP"*) acertaba **por accidente**, por el separador de miles, no por reconocer "COP" |
| El detector de segunda persona sólo ve formas de *tú* y se pierde el *usted* | **Confirmada** | Los pronombres `usted/ustedes` sí estaban; **las formas verbales no**. Las 9 frases de *usted* probadas daban `has_second_person=False`. **Y el daño mayor no era el marcador**: los imperativos de *usted* perdían el tipo de hook entero — *"Mire este apartamento"* → `None`, frente a *"Mira este apartamento"* → `command_cta`. Un asesor que hable de *usted* se quedaba **sin la categoría `command_cta`**, y el informe habría dicho que en esa mitad del corpus no se usan hooks de mandato |
| El vocabulario de vivienda es peninsular (`piso`, `parcela`, `dormitorio`) | **Refutada, con una excepción** | `piso`, `parcela` y `dormitorio` **no aparecen en ninguna regla**: el nivel léxico se apoya en verbos, puntuación y estructuras, no en sustantivos de vivienda. La única regionalidad real era verbal: `alquilar` (ES/VE) sin `arrendar` (CO) |

Lo que se cambió, con los peninsulares intactos (se **añade** registro, no se sustituye uno por otro):

1. **Precios en tres monedas.** Pesos/millones/palos (CO), dólares/`$`/"verdes" (VE), euros/`€` (ES), más `COP`/`USD`/`bolívares`/`Bs`. `millones`, `palos` y `verdes` **exigen numeral delante**, para que *"un millón de razones"* y *"las paredes verdes"* no se conviertan en precios.
2. **`usted` en tres niveles de evidencia**, porque *usted* **no es simétrico de *tú***: sus formas verbales son idénticas a las de tercera persona. Pronombre explícito → seguro. Imperativo (`mire`, `venga`, `fíjese`, `no firme`) → seguro. Indicativo (`está`, `tiene`, `quiere`…) → **sólo cuenta dentro de una interrogativa**, porque los hooks que interpelan de usted son abrumadoramente preguntas (*"¿Está pagando arriendo?"*) mientras que la lectura de tercera persona es abrumadoramente declarativa (*"Mi cliente quiere comprar"*).
3. **Columna nueva `second_person_register`** (`tu` / `usted` / `ambiguous` / `none`). **`ambiguous` es la aportación de diseño**, no un valor de relleno: un verbo con forma de *usted* sin nada que lo desambigüe **no** activa `has_second_person`. Resolverlo a `usted` inventaría interpelación; resolverlo a `none` escondería cuánto del corpus es indecidible. Ahora la Fase D puede preguntar el tamaño de ese cubo en vez de heredar una suposición callada.
4. **Imperativos de mandato y de advertencia en ambos registros** (`mira`/`mire`, `no firmes`/`no firme`), conjugados por clase verbal: los verbos en `-ar` hacen `-e` en usted y los de `-er/-ir` hacen `-a`, así que un patrón único `[ea]` habría contado *"no espera"* (indicativo, tercera persona) como si fuera *"no espere"*. Dos omisiones deliberadas: **`entre`** es mucho más veces la preposición (*"entre 200 y 300 millones"*) que el imperativo de "entrar", y **`pare`** choca con "para".
5. **Bug preexistente, encontrado de paso y arreglado:** `para` estaba en la lista de imperativos y se buscaba en cualquier posición, así que *"ideal **para** comprar"* activaba `has_imperative_marker` sin que hubiera ningún mandato.
6. **`arrendar` junto a `alquilar`**, y `queda a`/`vía a` en el detector de ubicación, que es como se dice la distancia allí.

**Tres cosas más que salieron al revisar los ejemplos concretos que me pasó el lead** (`mírala` → `mírela`), y que no son de dialecto sino bugs que el dialecto destapó:

7. **Imperativos con pronombre enclítico.** El español pega el pronombre al imperativo y sale una sola palabra: *mírala*, *mírela*, *cómprela*, *muéstrame*, *véalo*. **Ninguna se detectaba** — `"Mírala bien"` y `"Mírela bien"` daban las dos `hook_type=None`. El fallo era **simétrico entre registros**, así que era un bug de siempre, no un problema de dialecto. Arreglado en los dos. Para los verbos cuyo imperativo choca con un sustantivo corriente (`compra`, `llama`) **se exige el enclítico**: *"cómprela"* cuenta, *"la compra de esta casa"* no, porque los sustantivos no llevan enclíticos.
8. **Sesgo que yo mismo introduje y cacé al medir, escrito aquí porque es el más peligroso de los tres.** En la primera versión de este cambio sólo los imperativos de *usted* alimentaban el registro; los de *tú* no. Efecto: las cuentas que hablan de *usted* parecían **interpelar más** al espectador que las de *tú*. Eso no es un fallo de recall, es **un sesgo plantado justo dentro de la columna que F5 usa** para comprobar si el registro va con el país — habría fabricado la correlación que F5 busca. Corregido y con test de regresión (`test_both_registers_get_credit_for_imperatives`).
9. **Los imperativos desnudos son homógrafos de la tercera persona en los dos registros** (*"espera"* = "¡espera!" y "él espera"; *"mira"* = "¡mira!" y "ella mira"). Por eso un imperativo cuenta como **interpelación** sólo si **abre la ventana** o **lleva enclítico** — la misma evidencia que ya exigía la regla `command_cta`. `has_imperative_marker` se queda como marcador laxo (busca en cualquier posición); el **registro** es el estricto, porque alimenta un análisis de confusores y ahí el error caro es el falso positivo. Coste asumido y dicho: *"Y mire esto que le traigo"* no cuenta como interpelación.

Y un homógrafo más, del mismo tipo que el que ya documentaba §B.2: **`esta` (demostrativo) contra `está` (verbo de usted)**. Plegando tildes, *"esta casa"* —que abre medio corpus inmobiliario— parecía el verbo, y mandaba casi todas las filas al cubo `ambiguous`, dejándolo inservible como diagnóstico. Se resuelve igual que en el camino de *tú*: las formas acentuadas se buscan sobre el texto **sin plegar**.

**Lo que esto no arregla, dicho por delante:** la detección de *usted* es **inherentemente ambigua**, y ninguna regla la va a hacer exacta. Por eso el registro se **mide y se guarda** en cada fila en vez de resolverse a un booleano — y por eso existe el test de refutación **F5** (§A.3), que trata el reparto *usted*/*tú* como confusor y no sólo como problema de parseo.

### B.3 Decisiones de implementación que un lector debe conocer

1. **Una sola decodificación de ffmpeg por vídeo**, no una por ventana. Los fotogramas se muestrean una vez a 3 fps sobre la ventana más ancha; las ventanas estrechas son prefijos de esa secuencia.
2. **Una llamada ASR por ventana.** Los proveedores de transcripción del repo devuelven texto sin marcas de tiempo por palabra, así que el transcript de 3 s **no se puede derivar** del de 7 s sin inventar dónde cortar. Tres llamadas cortas son exactas y cuestan céntimos; interpolar sería un número inventado.
3. **Una sola llamada al VLM por vídeo**, sobre una **hoja de contactos** (los 9 fotogramas de la ventana en mosaico 3×3). El modelo ve la *secuencia* — que es lo que distingue una apertura de una foto — y el coste queda lineal en vídeos, no en fotogramas.
4. **`cut_count` es un *proxy*, y está etiquetado como tal en el código.** Cuenta diferencias entre fotogramas consecutivos por encima de un umbral fijo, así que también salta con un barrido rápido de cámara o un zoom brusco. Llamarlo "cortes" es cómodo, no está validado: nadie lo ha comprobado contra cortes etiquetados a mano.
5. **`unknown` nunca se rellena a ojo.** Si el VLM devuelve algo fuera del vocabulario, el valor es `unknown`, se guarda su salida cruda entera para diagnóstico, y **eso se ve en la tabla**. Nada de "el valor más plausible".

### B.4 La comprobación gratis que trae de serie

El extractor emite `hook_type_vlm` y `hook_type_lexical` **por separado**, además del `hook_type` resuelto. Eso da, sin etiquetar nada:

- **Tasa de acuerdo VLM↔léxico** sobre todo el corpus. Es una señal de calidad barata: si el VLM discrepa del léxico en el 60 % de los vídeos con voz clara, algo va mal en uno de los dos y hay que mirarlo **antes** de correlacionar nada.
- **`hook_type_source` por fila.** Un corpus donde la mayoría de tipos vinieron del respaldo léxico sostiene afirmaciones muy distintas de uno donde respondió el VLM. Esa diferencia desaparece en cuanto se borra la columna, así que viaja en cada fila.

Lo que **no** sustituye: el acuerdo entre dos métodos automáticos no es exactitud. Sigue haciendo falta el golden set humano (~100 vídeos, dos etiquetadores) del test F4 de la Fase A. Está presupuestado en la Fase C.

### B.5 HALLAZGO OPERATIVO, CORREGIDO EL 2026-08-06: el VLM local no sirve para un corpus — pero el alojado sí funciona y siempre funcionó

**Esta sección tenía una conclusión falsa y se retira aquí, explícitamente, en vez de editarla en silencio.** La medida seguía siendo correcta; la causa que le atribuí, no.

**(a) Lo que se midió con el VLM local, y sigue en pie.** Medido en esta máquina, no estimado. Dos corridas, y la segunda **cierra** lo que la primera dejaba abierto:

| Corrida | Configuración | Resultado |
|---|---|---|
| 2026-08-05, **cortada** | Hoja 3×3 de 9 fotogramas a 320 px (960×1707), `max_new_tokens=256` | **> 20 min 48 s**, sin terminar. Sólo daba una **cota inferior** |
| 2026-08-06, **completada** | La configuración que **de verdad se envía**: una ventana de 3 s, hoja de 6 fotogramas a 256 px, 1 llamada ASR | **23 min 12,89 s** de reloj (35 s user, 450 s system, 34 % CPU) |

La segunda es la buena: terminó, así que es una **duración** y no una cota, y es la configuración real del CLI. **A 23 min/vídeo, los 217 del plan son 84 h de portátil** (`corpus.estimate_corpus_cost().extraction_hours_local_vlm`, no prosa). En ambas, `transformers` avisa: *"Some parameters are on the meta device because they were offloaded to the disk"*. Eso corrige, y sigue corrigiendo, la línea "VLM local = $0" de la tabla de costes: el dinero es cero, el reloj no.

**Nota que refuerza el valor por defecto alojado:** la corrida local completada produjo **exactamente la misma lectura** que la alojada sobre el mismo vídeo — `hook_type=curiosity_gap`, `setting=urban_street`, `face_present=false`, `person_count=2`, `on_screen_text="We are here today at"` (el rótulo real del vídeo, leído bien), `text_density=high`, `vlm_parse_ok=true`. **Las 23 horas-vídeo de diferencia no compran ninguna calidad extra.** El transcript alojado de whisper en esa misma corrida fue *"We are here today."*, coherente con el rótulo; el nivel léxico devolvió `None` porque sus reglas son españolas y el fixture está en inglés — que es el comportamiento correcto, no un fallo.

**(b) Lo que se midió el 2026-08-06 con el VLM alojado, y refuta la conclusión.**

| Camino | Reloj por vídeo | Origen |
|---|---|---|
| `LocalQwenVisionProvider` (pesos locales, CPU) | **> 20 min** (cortado sin terminar) | medido 2026-08-05 |
| `HFInferenceVisionProvider` (featherless-ai), sólo ventana de 3 s, sin ASR | **5,8 / 6,2 / 7,4 s** (tres corridas) | medido 2026-08-06 |
| `HFInferenceVisionProvider`, configuración completa por defecto (3 ventanas → 3 llamadas ASR + 1 VLM) | **11,7 s y 17,8 s** (dos corridas) | medido 2026-08-06 |

`vlm_parse_ok=True` en todas ellas, con salida correcta (`setting=urban_street`, `person_count=2`, texto en pantalla leído del rótulo real del vídeo). **La diferencia es ~80×.**

**(c) La causa real: un valor por defecto en mi propio código, no el acceso a la cuenta.** `extract.py` fijaba `LocalQwenVisionProvider()` como proveedor por defecto cuando no se inyectaba ninguno, y `cli.py` no exponía ninguna forma de elegir el alojado. Es decir: **el CLI sólo podía correr el camino lento, y no lo decía.** Sobre el `400`:

- `InferenceClient(model="Qwen/Qwen3-VL-4B-Instruct", provider="featherless-ai")` → **HTTP 200**, respuesta correcta, segundos.
- El mismo modelo con `provider="auto"` → `400 ... "is not supported by any provider you have enabled"`.
- El Hub confirma featherless-ai en estado `live` para Qwen3-VL-4B (y 8B). Es el único proveedor del modelo.

O sea: **lo que está roto es la resolución `auto` para esta cuenta, no la cuenta.** `HFInferenceVisionProvider` ya pasaba `provider="featherless-ai"` explícito desde el día uno y ya funcionaba; nadie lo había llamado desde el CLI. La frase *"featherless-ai rechaza esta cuenta"* venía de un docstring desactualizado de `LocalQwenVisionProvider`, que yo leí como evidencia en vez de comprobarlo. **Lección, y es la que vale más de este documento: un `400` no dice por qué; sólo la llamada explícita lo dice. Un docstring no es una medición.**

**(d) Qué cambió en el código para que esto no vuelva a pasar** (detalle en "Cómo ejecutarlo"):

- `--vision {hosted,local,none}` en el CLI, **`hosted` por defecto**. Motivo: la otra llamada a modelo del extractor (ASR) ya era alojada por defecto, así que "local por defecto" en visión no era una política, era una incoherencia que salía 80× más cara en reloj. `--vision local` sigue a un argumento de distancia para corridas sin red, y `--vision none` es el modo offline de verdad.
- `--no-vlm` sigue funcionando y **gana** sobre `--vision`, para que ningún comando ya documentado se convierta solo en una corrida alojada de pago.
- Nueva columna de provenance **`vlm_backend`** (`hosted` / `local` / `injected`) en el JSONL y en el CSV. El `vlm_model_id` es idéntico en los dos caminos, así que sin esta columna una fila no puede decir cuál corrió.

**(e) El reloj del corpus, recalculado.** Ya no es prosa: `corpus.estimate_corpus_cost()` lo devuelve. Para los 217 vídeos del plan, en serie y en un solo proceso: **0,9 h alojado frente a 84,0 h local.** Con cualquier paralelismo modesto el alojado baja a minutos. **La corrida del corpus deja de necesitar una GPU.**

Mitigación anterior, que se queda porque sigue siendo buena: la hoja de contactos **submuestrea a 6 fotogramas y 256 px por celda** — el nivel determinista sigue leyendo los 9, porque es gratis.

**Lo que esto NO cambia:** el nivel determinista y el léxico siguen corriendo enteros en segundos, sin red y sin pesos; y el camino local sigue siendo inviable a escala de corpus. Lo único que se retira es la conclusión de que el corpus estaba bloqueado por falta de acceso a un VLM alojado.

<a id="como-ejecutarlo"></a>

## Cómo ejecutarlo

Desde la raíz del repo. **Nunca `uv sync`**; `--no-sync` es de sólo lectura y no toca el venv compartido.

El backend de visión se elige con **`--vision {hosted,local,none}`**, y por defecto es `hosted`.

**a) Completo, alojado — el modo por defecto y el que sirve para un corpus.** Qwen3-VL vía featherless-ai + whisper alojado. **~15 s por vídeo, medido:**

```bash
PYTHONPATH=packages/models/src uv run --no-sync python -m qualify_models.hooks \
  --video packages/models/tests/fixtures/sample_source.mp4 \
  --source-id sample_tiktok --keep-artifacts \
  --out-dir /tmp/hooks
```

**b) Modo determinista — sin red, sin pesos, segundos.** Corre antes de decidir ningún modelo:

```bash
PYTHONPATH=packages/models/src uv run --no-sync python -m qualify_models.hooks \
  --video packages/models/tests/fixtures/sample_source.mp4 \
  --source-id sample_tiktok \
  --vision none --no-asr --keep-artifacts \
  --out-dir /tmp/hooks
```

**c) Pesos locales — sin proveedor externo, pero >20 min por vídeo.** Un vídeo, nunca un corpus:

```bash
PYTHONPATH=packages/models/src uv run --no-sync python -m qualify_models.hooks \
  --video packages/models/tests/fixtures/sample_source.mp4 \
  --source-id sample_tiktok --vision local \
  --out-dir /tmp/hooks
```

> `--no-vlm` sigue siendo válido: es el alias antiguo de `--vision none` y **tiene prioridad** sobre `--vision`, para que un comando copiado de una versión anterior de este documento no empiece a llamar a un modelo de pago por su cuenta.

> El `PYTHONPATH=...` es un rodeo a la instalación editable rota del venv compartido que documenta `CLAUDE.md` (`import qualify_models` falla desde la raíz). No es parte del diseño.

Salida en `--out-dir`:
- `hook_features.jsonl` — el registro completo por vídeo (todo, incluida la salida cruda del VLM si falló el parseo) y la columna **`vlm_backend`**, que dice qué camino corrió realmente.
- `hook_features.csv` — **una fila plana por (vídeo × ventana)**. Ésta es la tabla que se abre en una hoja de cálculo y la que se une con las métricas en la Fase D.
- `artifacts/<source_id>/frames/*.jpg` y `sheet_3s.jpg` — con `--keep-artifacts`. **Mira la hoja de contactos**: es la forma más rápida de ver exactamente lo que se le enseñó al modelo.

Tests: `PYTHONPATH=src:../shared/src uv run --no-sync --project .. python -m pytest tests/test_hooks.py -q` desde `packages/models` → **92 pasan**, offline, sin pesos (42 originales + 6 del backend de visión + 39 de dialecto y sus bugs + 5 de la puerta de viabilidad).

<a id="fase-c"></a>

## Fase C — el corpus: cuánto hace falta y cuánto cuesta

**Aquí me paro. Esto es lo que necesito de ti antes de gastar un céntimo.**

### C.1 Qué hace falta exactamente

Vídeos reales de **varios asesores inmobiliarios**, y por cada vídeo:

1. el fichero de vídeo (para los primeros 7 s),
2. sus métricas: likes, comentarios, (views si el scraper las trae),
3. la fecha de publicación — sin ella no se puede quitar la tendencia de crecimiento de la cuenta,
4. los comentarios en texto, si quieres la variante de sentimiento.

### C.2 Cuántos, y por qué ese número

Calculado con `corpus.plan_corpus()`, no a ojo. Es re-ejecutable con tus supuestos:

| Objetivo | Posts por tipo de hook | **Total de vídeos** | Cuentas | Vídeos/cuenta |
|---|---|---|---|---|
| Detectar diferencias **grandes** (d=0,8) entre los 4 tipos más comunes | 26 | **217** | 8 | 28 |
| Lo mismo, si el tipo más raro resulta ser el 5 % y no el 12 % | 26 | **520** | 8 | 65 |
| Detectar diferencias **medianas** (d=0,5) | 66 | **550** | 8 | 69 |

**Mi recomendación: la primera fila. 217 vídeos, 8 cuentas.** Compra la capacidad de detectar *"los hooks de pregunta claramente rinden mejor que los de afirmación"*, y **no** la de detectar una ventaja sutil de 5 percentiles. Perseguir el efecto mediano multiplica el corpus por 2,5 para un hallazgo que, si existiera, tampoco cambiaría lo que graba un agente mañana.

**El supuesto más frágil, dicho por delante:** que el tipo de hook más raro de los cuatro comparados sea ~12 % del corpus. **Nadie ha tipificado nunca una biblioteca real de inmobiliaria en español**, así que es una conjetura. Si resulta ser el 5 %, el corpus necesita ser 2,4× más grande. Medir esa distribución es exactamente lo que compra el piloto de C.5.

**¿Cambian estos números con la corrección de dialecto del 2026-08-06? Hoy no, y digo por qué en vez de re-ejecutar `plan_corpus()` en silencio.** El razonamiento era correcto —si `price_reveal` se hundía, el supuesto de "el tipo más raro es el ~12 %" se movía y el corpus con él— pero **la premisa ya no se cumple: `price_reveal` está arreglado en las tres monedas**, y `command_cta` recuperado para el registro de *usted*. Los dos tipos que iban a colapsar ya no colapsan, así que **217 sigue en pie**.

**Lo que sí puede cambiarlos, y no lo puedo decidir yo desde aquí:** si se cumple **F5** y hay que **estratificar por país o por registro**, la comparación deja de correr sobre 217 vídeos y pasa a correr sobre dos mitades. Para detectar el mismo efecto *dentro de cada país* harían falta ~217 **por país**, es decir **~434 en total**. **No re-planifico ahora**, porque si hace falta estratificar es exactamente una de las dos cosas que mide el piloto de C.5 — junto con la distribución real de tipos. Re-ejecutar `plan_corpus()` hoy sería sustituir una conjetura por otra más cara.

**Requisito no obvio, y es el que más riesgo tiene:** el diseño compara tipos de hook **dentro de cada cuenta**. Una cuenta que siempre abre igual **no aporta nada** al análisis, por muchos vídeos que tenga. Al elegir las 8 cuentas hace falta **variedad de aperturas**, y eso sólo se puede comprobar *después* de extraer. Es la segunda cosa que mide el piloto.

### C.3 Cuánto cuesta

Con `corpus.estimate_corpus_cost()` sobre el plan de 217 vídeos (≈11.100 registros contando 50 comentarios por post):

| Partida | Coste | Fuente |
|---|---|---|
| Adquisición vía **Data365** | **$6,64** | `docs/alternativas-fase1.md` §2a: ~$0,60/1K registros |
| Adquisición vía **Apify** | $18,81 | ibíd.: ~$1,70/1K |
| Adquisición vía **Zyte** | **no calculable** | El repo sólo cita el **plan** ($100/mes), nunca un precio por request. No lo invento |
| Transcripción (15 s/vídeo × 217) | **$0,04** | Groq whisper-v3 ~$0,04/h |
| Visión, Qwen3-VL **local** | **$0 en dinero, 84,0 h de portátil** | Ver §B.5: 23 min 13 s/vídeo medidos a terminación. **No es viable a escala de corpus** |
| Visión, **alojada** (featherless-ai) | **sigue sin ser calculable en dinero — pero 0,9 h de reloj**, medidas | Ver abajo |
| **Total en dinero** | **≈ $7** | Data365 + ASR alojado + VLM (local o alojado: el alojado no está tarifado) |

**Por qué la visión alojada sigue en "no calculable", y qué ha cambiado.** Ahora existe una llamada real que funciona, así que la mitad que faltaba ya está medida: **371 tokens por vídeo** (316 de prompt + 55 de salida, reportados por la propia API sobre la hoja de contactos de 6 fotogramas). Lo que falta es la **tarifa**, y no la invento:

- HF documenta que **cobra la tarifa del proveedor sin recargo** y publica precios por token por par (modelo, proveedor) en su catálogo de router — pero **Qwen3-VL-4B no está en ese catálogo** y su `inferenceProviderMapping` no trae bloque de precios (comprobado contra la API del Hub el 2026-08-06).
- featherless.ai publica **planes** ($25/mes plano, $50/mes "billed per token") y **ninguna tarifa por token** para ningún modelo concreto.

**Qué lo cerraría, y es barato:** correr el piloto de 50 vídeos de C.5 y leer el gasto real en `huggingface.co/settings/inference-providers/overview`, que desglosa el consumo por modelo y proveedor. Eso convierte la cifra en una medición en vez de una estimación — que es la única clase de número de coste que acepta `corpus.py`.

> **CORRECCIÓN 2026-08-06, del agente de adquisición, y la acepto entera.** Toda la tabla de arriba tiene un supuesto que nadie escribió: **que pagar por un registro te da un vídeo descargable.** No es cierto. Los $6,64 tarifan **registros de metadatos**; conseguir los *bytes* del vídeo es un problema aparte y sin resolver en el camino de pago. Así que **$6,64 es un suelo para metadatos, no un precio de corpus**.
>
> Y ha dejado de importar, porque la adquisición **se resolvió a $0**: `yt-dlp` baja el mp4 real (5,7 MB en ~4 s) más `timestamp`, `view_count`, `like_count`, `comment_count` y `duration`, de una cuenta inmobiliaria real de Cúcuta. Sin proveedor, sin cuenta, sin gasto. **Plataforma decidida: TikTok**; Instagram queda aparcada porque rechaza sesión anónima en bytes, métricas *y* enumeración. Nota adyacente que no me afecta pero explica el camino: el `playAddr` que extrae `parsers/tiktok.py` está **muerto** (403 con cualquier cabecera; TikTok pone la CDN detrás de un reto anti-bot en JS), y por eso la vía es `yt-dlp` y no el cliente existente.
>
> **La conclusión honesta: el coste de adquisición dejó de ser el número interesante.** Lo que queda caro sigue siendo lo de siempre — las horas de etiquetado — y ahora, por delante de eso, la pregunta de si el nicho tiene varianza (§D.7-ter).

**El dinero no es el cuello de botella. Siete dólares — y por la vía libre, cero.** El coste real es otro:

| Partida | Coste real |
|---|---|
| **Etiquetado humano del golden set** (100 vídeos × 2 personas × 2 min) | **≈ 6,7 horas-persona** |
| Escribir el runner de corpus (no existe) | trabajo de ingeniería, ver C.4 |
| Tú eligiendo y nombrando las 8-12 cuentas | tu tiempo |
| Extracción de los 217 vídeos, **alojada** | **≈ 0,9 h de reloj**, en serie (medido; con paralelismo, minutos) |

Si el VLM no está validado contra etiquetas humanas, `hook_type` es una columna que nadie puede defender — y entonces los $7 de scraping no compran nada. **Las 6,7 horas son el precio de entrada, no un extra.**

### C.4 El runner no existe — y propongo dónde va, no lo creo

`packages/scraper` tiene cliente Zyte y parsers de TikTok/IG, pero **no hay nada que baje N vídeos de M cuentas**, y no existe `scripts/`. Propuesta, para que la valide quien corresponda antes de que yo escriba una línea:

- **Va en `packages/scraper/src/qualify_scraper/harvest.py`** (o en un `scripts/harvest_corpus.py`), **no en `packages/models/`**. Descargar es trabajo de scraper, y hay otra developer en `packages/api/`; mi territorio es `packages/models/`.
- Salida a disco: `corpus/<account>/<post_id>.mp4` + un `corpus/metrics.csv` con `source_id, account_id, posted_at, likes, comments, views`. Ese CSV es exactamente lo que `analysis.PostObservation` consume — la costura entre las dos mitades ya está definida.
- **Es de la Parte 2, no de la Parte 3.** Nada de Celery, R2 ni esquemas analíticos: un script que escribe ficheros.

### C.5 Lo que te pido — y hasta que respondas, paro

1. **¿Qué cuentas?** Necesito **8-12 handles** de asesores inmobiliarios con al menos ~30 vídeos publicados cada uno. Tienes que nombrarlas tú; yo no sé cuáles son relevantes para tu mercado.
2. **¿TikTok o Instagram Reels?** Mezclar plataformas mete un confusor más (algoritmos distintos). Prefiero una sola para el piloto.
3. ~~**¿España o LatAm?**~~ **CONTESTADO 2026-08-06: la frontera colombo-venezolana** (San Cristóbal/Táchira y Cúcuta/Norte de Santander). El nivel léxico ya está adaptado a los tres registros —peninsular, *tú* latinoamericano y *usted*— y a las tres monedas; ver §B.2.1. **Queda una pregunta nueva para ti:** ¿el piloto mezcla los dos países o empieza por uno? Mezclarlos mete el confusor de F5 desde el primer dato; empezar por uno lo evita pero no mide el reparto de registros. **Mi recomendación: mezclar en el piloto** —justamente para medir el reparto barato— y decidir la estratificación con ese dato en la mano.
4. **¿Puedes poner ~7 horas de etiquetado** (tú + una segunda persona)? Si sólo hay una persona, se puede etiquetar igual **pero no se puede correr el test F4** — y entonces no sabremos si la taxonomía es siquiera reproducible entre humanos.
5. **¿Autorizas el piloto primero?** **Mi recomendación fuerte: sí** — y ahora es gratis, así que la pregunta ya no es de dinero. **50 vídeos de 3 cuentas, $0** por la vía `yt-dlp`.
6. ~~**Prerrequisito técnico, no negociable:** desbloquear un VLM alojado o conseguir una GPU.~~ **RETIRADO el 2026-08-06. No era un prerrequisito y no era real.** El VLM alojado funciona (`--vision hosted`, ~15 s/vídeo medidos); lo que fallaba era un valor por defecto de mi propio CLI, no el acceso a la cuenta — ver §B.5. Los 217 vídeos son **0,9 h de reloj**, no 84 h, y no hace falta ninguna GPU. **Nada técnico bloquea hoy la Fase C.**

### C.5-bis Qué mide el piloto ahora, y qué NO puede reportar nunca (2026-08-06)

**La pregunta del piloto cambió de orden.** Antes era "¿cuál es la distribución real de tipos de hook?" con la variedad de aperturas en segundo lugar. Con los datos de engagement que han llegado, **la pregunta principal pasa a ser la de la varianza**:

> **¿Este nicho produce siquiera variedad de hooks y dispersión de rendimiento?**

Si la respuesta es no, el resto del plan sobra, y sobra *antes* de gastar 6,7 horas-persona de etiquetado. El piloto se corre contra `assess_viability()` (§D.7-ter) **antes** de mirar ninguna correlación, y el orden de las tres preguntas queda:

1. ¿Hay dispersión en el resultado y variedad de hook dentro de cada cuenta? (**puerta**; si falla, se para aquí)
2. ¿Cuál es la distribución real de tipos de hook? (el supuesto frágil del 12 % de §C.2)
3. ¿Cómo se reparte el registro *tú*/*usted* entre las cuentas? (el confusor F5)

**Frontera dura, y hay que escribirla para que nadie cite luego el piloto como si fuera un hallazgo:**

> **Ningún resultado del piloto puede reportarse como un hallazgo sobre hooks.** Sólo como un hallazgo sobre **si merece la pena construir el corpus**.

La razón es del propio diseño, no una precaución genérica. §C.2 pide **8 cuentas como mínimo** y §D.2 regla 3 exige que un tipo de hook aparezca en **al menos 3 cuentas** para contar como patrón y no como costumbre de una casa. Un piloto de **3 cuentas está en el suelo exacto de esa regla**: podría producir como mucho **una** comparación admisible, sobre 3 cuentas, sin intervalo que merezca reportarse. **El piloto es incapaz por construcción de sostener una afirmación sobre hooks**, y eso no es un defecto del piloto —su trabajo es la viabilidad, no la inferencia— sino una frontera que hay que dejar escrita antes de que existan los datos, no después.

#### C.5-bis.1 LEER ESTO ANTES DE INTERPRETAR UN RESULTADO NULO DEL PILOTO

**Si el piloto sale "no hay variedad" o "no hay dispersión", eso NO es todavía un veredicto sobre la tesis del hook.** Puede significar *"no lo pudimos ver"* en vez de *"no está ahí"*, y hay **dos causas independientes** que lo provocan. Están medidas, no son hipotéticas, y hay que comprobar las dos antes de leer un nulo como respuesta:

| Causa | Qué la produce | Cómo se comprueba |
|---|---|---|
| **Margen cero de cuentas** | Sólo hay **3 cuentas** en TikTok y mi propia regla exige que un tipo de hook aparezca en **≥3 cuentas**. Un tipo tiene que salir en **las tres**: que una sola cuenta no lo use lo borra del estudio (§C.5-ter) | `assess_corpus_feasibility()` devuelve `accounts_margin=0` y `kind=measurement_only` |
| **Span conseguido < span pedido** | Los picks de los extremos fallan (~50 % de fallo por vídeo). Un tipo usado sólo en los meses perdidos está **ausente** del corpus y se lee como "esta cuenta no varía" (§C.5-septies) | `hook_temporal_separation()` devuelve `negative_findings_interpretable=False` si la cobertura < 50 % |

**La asimetría, que es lo que hay que retener:**

> **Un resultado POSITIVO del piloto es válido pase lo que pase** — si se observó variedad, la variedad existe. **Un resultado NEGATIVO sólo vale si las dos comprobaciones de arriba pasan.**

Y como el trabajo del piloto es **precisamente** falsar la hipótesis pesimista, **un negativo no interpretable es su peor resultado posible**: parece una respuesta decisiva, cierra la línea de trabajo, y no lo es. Por eso las dos comprobaciones son campos tipados en la salida y no advertencias en prosa.

### C.5-ter DECISIÓN (2026-08-06): el techo son 3 cuentas en TikTok — y el plan de 8 no se rebaja

Me llega la medida: de las 9 candidatas no descartadas, **sólo tres tienen catálogo usable en TikTok** — `@inmobiliarialunaroman` (365), `@inmobiliariamarelsa` (196), `@inmobiliariatonchala` (150) = **711 vídeos**. Instagram tiene ~9 más y es donde vive el nicho, pero no admite sesión anónima ni para bytes, ni para métricas, ni para enumerar.

Se me deja la decisión entre tres opciones: rebajar `min_accounts`, correr con 3 como piloto de medición, o pagar Instagram. **La tomo, y son dos decisiones, no una.**

**1. `min_accounts=8` no se rebaja. Se queda en 8.** Bajar un suelo porque los datos no lo alcanzan es exactamente cómo un estudio fabrica un hallazgo. El suelo dice lo que **cuesta la pregunta**; no cede ante lo que ofrece el mundo. Lo que cede es **la afirmación**.

**2. El piloto se corre igual, con 3 cuentas, y se declara `measurement_only`.** No es un premio de consolación: es lo que convierte en números los tres supuestos sobre los que se apoya todo el plan.

Esto ya **no es prosa**: `corpus.assess_corpus_feasibility(plan, available_accounts, videos_available)` devuelve un `CorpusStudyKind` tipado —`inferential` / `measurement_only` / `not_viable`— más `supports_hook_performance_claim: bool`. Con 3 cuentas y 711 vídeos devuelve `measurement_only`, `margin=0`, `claim=False`. Está en tests, incluido uno que comprueba que la función **nunca** rebaja `plan.min_accounts` para que encaje.

**La aritmética que hay que ver, y no es la que se busca primero.** Con exactamente 3 cuentas y una regla que exige que un tipo de hook aparezca en ≥3 cuentas, **el margen es cero**: un tipo tiene que salir en **las tres**. Que una sola cuenta no use un tipo lo borra del estudio entero. Así que 3 cuentas no es "el plan de 8, más pequeño"; es **otra clase de estudio**.

**El reencuadre que más importa, y que corrige la forma de la pregunta:**

> **La restricción que ata no es el número de cuentas. Es la variedad de aperturas *dentro* de cada cuenta.**

Estos son anunciantes de plantilla (`🏡✨ CASA EN VENTA – <BARRIO> ✨ 🆔 ÍTEM: <n>`). Si cada cuenta abre siempre igual, el diseño de §D.2 —que compara tipos de hook **dentro** de la cuenta— no tiene nada que comparar, **y eso no lo arregla ningún número de cuentas**. Ocho anunciantes de plantilla fracasarían igual que tres. Por eso `assess_viability()` mide variedad intra-cuenta y es una **puerta**, no un informe.

**Consecuencia sobre pagar Instagram: se aplaza, y no por dinero.** Comprar acceso a IG antes de medir la variedad puede comprar nueve anunciantes de plantilla más. La secuencia correcta es: piloto gratis en TikTok → ¿hay variedad? → **sólo entonces** tiene sentido la pregunta de IG. Gastar antes es comprar denominador sin saber si hay numerador.

**Lo que sí acepto y pido:** el re-sondeo de handles con variantes de escritura es gratis (~30 s por handle) y ya encontró una cuenta que la pasada exacta había dado por ausente. Que se corra sobre cualquier handle nuevo antes de darlo por inexistente. Pero es **secundario**: más cuentas no resuelve la pregunta de la variedad, sólo mueve el techo.

### C.5-quater La costura métricas↔rasgos, cerrada por los dos lados (2026-08-06)

Mi regla de *"`engagement_rate` devuelve `None`, nunca 0"* destapó un fallo real **en el escritor del corpus**, y al arreglarlo se vio que **me faltaba la mitad de la garantía a mí**.

**El fallo del lado del runner (ya arreglado por pipeline):** `_post_from_info` hacía `int(info.get("view_count") or 0)`. Ese idioma convierte *"la métrica no vino"* en **`0`**. Inofensivo mientras views era incidental; letal ahora que views es el resultado primario y el denominador de `engagement_rate`: un post sin views declaradas habría llegado a mi CSV como `0` y **mi guarda de `None` nunca habría saltado, porque nunca habría visto una celda vacía.** Un cero silencioso rankea ese post como el peor de su biblioteca.

**Lo que faltaba de mi lado, y era peor de lo que parecía:** yo **no tenía lector**. La costura existía sólo en prosa. Peor: `PostObservation.views` es `float | None`, así que una celda vacía leída con un `csv.DictReader` ingenuo llega como `""` y **pydantic la habría rechazado** — el contrato no sólo no estaba garantizado, es que ni siquiera cargaba.

**Cerrado: `hooks/join.py`.** Une `corpus/metrics.csv` (runner) con `hook_features.csv` (extractor) y produce la lista de `PostObservation` de la Fase D. Reglas que hace cumplir, todas con test:

| Regla | Por qué |
|---|---|
| Celda vacía → `None`; `"0"` → `0.0` | Son **valores distintos** y tienen que seguir siéndolo hasta el análisis. `float(x or 0)` los colapsa y el colapso es invisible después, porque `0.0` es un número perfectamente válido |
| `engagement` pasa a ser **opcional** | Es un **compuesto** de likes + comentarios. 8 likes con comentarios sin reportar **no es engagement 8**: es engagement desconocido. `(likes or 0) + (comments or 0)` lo habría puesto por debajo de un post con 9 medidos que quizá rinde menos |
| `engagement_rate` exige **las dos mitades** | Numerador desconocido o denominador vacío → `None`. Un ratio necesita ambos |
| `posted_at` acepta timestamp UTC completo | El runner escribe el `timestamp` de yt-dlp, no el `upload_date` de sólo fecha. Se parsea explícito: no me fío de que pydantic coaccione un ISO *datetime* a `date` en silencio |
| Falta una columna obligatoria → **excepción** | Un `account_id` ausente rompe el diseño entero de §D.2; que falle al cargar, no a mitad del análisis |
| Lo que **no** une se cuenta y se devuelve | `JoinResult.missing_hook_features`, `missing_metrics`, `join_rate`. **Una unión que se come la mitad del corpus en silencio es exactamente lo que hace que un estudio sin potencia parezca que la tiene** |
| `follower_count` se carga aparte, de `accounts.csv` | Es por cuenta, no por post. Mantenerlo fuera de `metrics.csv` evita que alguien lo use como covariable por post en un diseño que **nunca** compara entre cuentas |

**La lección que vale más que el arreglo:** una convención de datos acordada en prosa entre dos agentes no es un contrato. Lo fue cuando hubo un test a cada lado de la costura — el de pipeline comprobando que escribe vacío, el mío comprobando que leo `None`.

### C.5-octies El patrón del día: cuatro guardas apuntadas al peligro correcto, colocadas donde no podían dispararse

Al final de la sesión el hallazgo transversal ya no es ninguno de los bugs sueltos, sino su **forma común**. Cuatro casos, dos paquetes, un solo día:

| Guarda | Peligro correcto | Por qué no podía dispararse |
|---|---|---|
| `int(view_count or 0)` (runner) | Métrica ausente | Convertía el hueco en `0`, así que **el hueco nunca llegaba** al guard que lo esperaba |
| `> 0.5` en separación temporal (mío) | Hook colineal con la fecha | 0,50 es el **máximo** de una cuenta equilibrada de dos tipos. Nunca podía superarse |
| Spearman en el chequeo de residuo (mío) | Deriva no monótona | La Spearman de una U simétrica es ≈0: daba aprobado justo a la forma que buscaba |
| Muestreo por recencia (runner) | Ventana no representativa | Tomaba la cabeza del catálogo, así que **el span nunca se ensanchaba** |

**Ninguna la encontró la suite que la cubría.** Todas salieron de correr una mitad contra la otra.

**La regla que me llevo, y que apliqué a mi propio código en el acto:** *una guarda necesita un test que la haga **dispararse**, no sólo un test que pase estando ella presente.*

**Auditoría de mis guardas bajo esa regla — y encontró la misma forma:**

- **`CorrelationReport.conclusive` sólo se afirmaba `False`.** Nunca había un test donde saliera `True`. Es decir: **todo el camino positivo de la puerta de la Fase D —lo único que autorizaría reportar un hallazgo— estaba sin probar.** Si alguien la hubiera cableado de modo que jamás pudiera devolver `True`, ningún test habría fallado.
- **`HookTypeEffect.separates_from_chance`: cero tests.**
- `meets_min_posts` nunca se afirmaba en `True`.

Ya están los tests que las hacen disparar, incluido un corpus sintético con efecto real (4 cuentas × 40 posts por tipo) donde `conclusive` sale `True`. **Resultado de la auditoría: las guardas eran correctas, sólo estaban sin demostrar.** Que salgan bien no invalida la auditoría — el coste de comprobarlo fueron veinte minutos y el coste de no comprobarlo era descubrir en el piloto que la puerta no abre nunca.

### C.5-nonies Los 10 vídeos reales confirman el diseño con más fuerza de la que yo esperaba

El runner comprometió su corpus real como fixture (`packages/scraper/tests/fixtures/corpus/metrics.csv`, 10 posts de dos cuentas de Cúcuta, 2026-08-06) y ya está cargado por mis tests. La costura aguanta: **10/10 unidos, `join_rate` 1.0**, `follower_count` correctamente ausente (yt-dlp no lo da).

Y los números dicen algo que merece quedar escrito, porque es la mejor evidencia empírica que ha recibido el diseño:

| Cuenta | Views | Rango interno |
|---|---|---|
| `@inmobiliarialunaroman` | 426, 590, 623, 750, **12800** | **30×** |
| `@inmobiliariamarelsa` | 10, 17, 18, 18, 21 | 2,1× |

Tres lecturas, todas ya en tests:

1. **Entre cuentas hay ~40× de diferencia de escala.** Un análisis agrupado estaría **enteramente determinado** por la primera cuenta: todos sus posts baten a todos los de la segunda. Con ranking dentro de cuenta, el mejor post de la cuenta pequeña supera al peor de la grande. Es exactamente el confusor de §D.1, medido en datos reales en vez de argumentado.
2. **Un solo post viral (12800 contra una base de ~600) domina su propia cuenta.** Es la justificación de usar **mediana con bootstrap** y no media: con media, el hook de ese único vídeo se convertiría en "hallazgo general".
3. **La dispersión es radicalmente heterogénea entre cuentas** (30× frente a 2,1×). Esto matiza mi propia postura anterior: no es que el nicho tenga o no tenga varianza — **es que unas cuentas la tienen y otras puede que no**. La puerta de viabilidad hoy reporta medianas y un único `viable`, lo que puede tapar que una cuenta sirva y otra esté muerta. Anotado como refinamiento pendiente; no lo cierro hoy porque con n=5 por cuenta cualquier medida de dispersión es anecdótica.

### C.5-septies El span conseguido no es el span pedido — y eso invalida sólo los negativos (2026-08-06)

Medida que llega del runner y que toca directamente a la puerta de viabilidad: una corrida acotada a **365 días** devolvió 6/6 vídeos pero abarcando **98 días**. Los picks de los dos extremos fallaron y sólo sobrevivieron los suplentes interiores. Con ~50 % de fallo por vídeo, **eso es lo normal, no mala suerte**.

**La consecuencia es asimétrica, y la asimetría es lo importante:**

| Hallazgo del piloto | ¿Le afecta un span corto? |
|---|---|
| **"Sí hay variedad"** | **No.** Se observó variedad, luego existe. Una muestra más ancha sólo habría encontrado más |
| **"No hay variedad"** | **Sí, y lo invalida.** Un tipo de hook que la cuenta usara *sólo* en los meses que se perdieron está sencillamente ausente del corpus, y la puerta lo leería como *"esta cuenta no varía"* cuando sí varía |

Y como **el trabajo del piloto es precisamente falsar la hipótesis pesimista**, un negativo no interpretable es su **peor resultado posible**: parece una respuesta decisiva y no lo es.

**Cerrado en código.** `hook_temporal_separation(..., requested_span_days=N)` calcula `min_span_coverage` (span conseguido / span pedido) y devuelve `negative_findings_interpretable: bool`. Por debajo del 50 % de cobertura, el veredicto dice explícitamente que **un hallazgo negativo no es interpretable** y que uno positivo sí. Tres tests.

**Dos correcciones que me hace el runner, una a mi favor:**

1. **Mi estimación de densidad estaba mal, y en la dirección buena.** Yo proyecté ~86 posts/año repartiendo 365 posts entre 4,2 años. Medido: **269 posts en los últimos 365 días**. La aritmética era correcta; **el supuesto de ritmo uniforme no lo era** — la cuenta se ha acelerado mucho. Cualquier ventana de 12 meses tiene ~16× lo que necesita un piloto de 17 por cuenta, no 5×.
2. **El timestamp del id de TikTok es aproximado** (8 s de desfase frente al `timestamp` del payload: acuñación vs publicación). Sirve como **filtro** y no como marca de análisis. `metrics.csv` sigue llevando el `timestamp` exacto. No me cambia nada, pero que nadie los trate como intercambiables.

**Aclaración sobre el default, porque mi decisión cambió a mitad:** el runner implementó `max_age_days=365` siguiendo mi recomendación de §C.5-quinquies, **que quedó superada por §C.5-sexies**. La capacidad de acotar es buena y hay que conservarla — es la que necesitará el **corpus**. Pero **el piloto se corre sin acotar** (`max_age_days=None`), porque su trabajo es la prueba más generosa posible de la hipótesis pesimista. El ancho de la ventana del corpus lo decide después el número de separación del piloto.

### C.5-sexies RECTIFICACIÓN (2026-08-06, misma sesión): el piloto va con `spread` a catálogo completo

**Cambio de decisión. Lo de abajo (§C.5-quinquies) queda superado, y se deja escrito en vez de borrarlo.** Dije "`spread` acotado a 12 meses" y el lead me da un argumento que no habíamos puesto ninguno de los dos sobre la mesa. Tiene razón.

**El argumento que me convence:** el trabajo del piloto es **falsar la hipótesis pesimista** ("este nicho no varía"). `spread` a catálogo completo es **la prueba más generosa posible** de esa hipótesis — y **un negativo obtenido con la prueba más generosa es el negativo más informativo que existe**. Mi ventana de 12 meses debilitaba exactamente el test que más potencia necesita. Un "no hay variedad" con ventana estrecha no distingue *"no hay repertorio"* de *"la ventana era corta"*; con catálogo completo, sí.

**Mi objeción original era buena, y ya está resuelta por otra vía.** Me preocupaba que la variedad hallada fuese deriva y no repertorio. Eso era correcto — y por eso construí `hook_temporal_separation()`. Con la separación **medida**, `spread` domina, porque distingue cuatro casos donde la ventana acotada distingue dos:

| Resultado del piloto | Lectura |
|---|---|
| `spread` halla variedad, separación **baja** | **Repertorio.** Adelante con el corpus |
| `spread` halla variedad, separación **alta** | **Deriva.** El corpus necesita ventana acotada o estratificación por periodo — y el propio número dice cuál |
| `spread` **no** halla variedad | Evidencia fuerte de que no hay repertorio. Es el negativo caro pero limpio |
| Ventana acotada no halla variedad | **Ambiguo.** No sirve para decidir |

**Dónde discrepo del lead, y es un matiz que importa:** dice que el confuso temporal del piloto *"no importa porque el piloto tiene prohibido hacer afirmaciones sobre hooks"*. Eso no basta. El modo de fallo del piloto **no** es una afirmación falsa sobre hooks: es un **GO falso**. Si `spread` encuentra variedad que es pura deriva y la puerta dice "adelante", se construye el corpus de 217 y se descubre después que la variedad no servía. La prohibición de afirmar no protege de eso; **medir la separación sí**. Por eso la rectificación depende de que la medida exista, no del reencuadre.

**Decisión final, entonces:**
- **Piloto → `spread` a catálogo completo. El default de pipeline se queda como está.**
- **Corpus → ventana acotada o estratificada por periodo, y el ancho lo decide el número de separación que devuelva el piloto**, no mi conjetura de 12 meses.

**Y una comprobación más que añade el lead, aceptada y construida:** que el destrending se **verifique**, no se suponga. `analysis.detrend_residual_check()` divide el catálogo de cada cuenta en tres eras y compara la media ajustada; si el destrending funcionó, las tres rondan 0,5. Sobre un corpus de varios años esto deja de ser higiene y pasa a ser carga estructural, que es justo el argumento del lead.

**Dos errores míos que encontró esa comprobación al construirla, y ambos merecen quedar escritos:**

1. **`RECENCY_ADJUSTED` rankeaba ruido de coma flotante.** Cuando la tendencia explica la biblioteca por completo, los residuos son ~1e-16 — polvo numérico. Como el percentil es invariante de escala, ese polvo se amplificaba a un ranking completo de 0 a 1: **un orden confiado sobre nada.** Arreglado: por debajo de un suelo de ruido, todos los posts salen a 0,5 ("todos promedio"), que es la codificación honesta de "aquí no queda señal del hook".
2. **Mi primer diagnóstico no podía ver el caso para el que lo escribí.** Usaba correlación de Spearman entre recencia y resultado ajustado. Pero el residuo que hay que cazar **no es monótono**: una cuenta que creció y luego decayó deja una U simétrica, y **la Spearman de una U simétrica es ≈ 0** (medido: 0,01). Habría dado un certificado de buena salud precisamente a la forma que debía detectar. Sustituido por la comparación de medias entre tres eras, que caza tanto lo monótono como lo curvo.

De paso quedó pinchada una propiedad que conviene saber al leer resultados: el ajuste es **lineal sobre rangos**, así que **absorbe cualquier tendencia monótona** — crecimiento sostenido, o un salto único tras un post viral. Lo que **no** absorbe es la deriva no monótona. Un salto escalonado no es un contraejemplo, y un test anterior mío suponía que sí.

**Sobre la tasa de éxito sesgada por antigüedad (0,40 en `spread` frente a 0,56-0,80 en recencia):** es un sesgo de segundo orden real — si los posts viejos fallan más, la lista de *intentos* está repartida pero el conjunto *obtenido* vuelve a inclinarse hacia lo reciente. **Recomiendo medirlo, no modelarlo**: basta comparar la distribución de fechas pedidas con la obtenida al final del piloto. Si coinciden, no hay problema; si no, el número de separación se lee con esa advertencia. Acepto los ~125 intentos y 45-60 min.

### C.5-quinquies (SUPERADO por §C.5-sexies) DECISIÓN (2026-08-06): el muestreo del piloto — ni `recent` ni `spread`, sino `spread` acotado

Me llega una medida que cambia el diseño del piloto: la enumeración devuelve del más nuevo al más viejo, así que **coger los primeros N es un muestreo de recencia**. En `@inmobiliarialunaroman`, con 365 posts sobre **1.549 días (4,2 años)**, los 50 más recientes cubren **95 días — el 6,1 % del catálogo**. Un piloto así habría medido **una ventana de tres meses** de un anunciante y la habría reportado como "la variedad de esa cuenta".

Se me ofrece elegir entre `recent` y `spread`, con `spread` por defecto porque *"puede falsar la hipótesis pesimista y recency no"*. Ese argumento es correcto. **Y aun así no acepto ninguna de las dos.**

**Por qué `spread` a catálogo completo es peligroso, y no por la razón obvia.** Repartir el muestreo sobre 4,2 años maximiza la variedad que *ves* y, a la vez, maximiza la probabilidad de que esa variedad **no sirva**. Si la cuenta usaba `question` en 2022 y `price_reveal` en 2026, la tabla de frecuencias muestra dos tipos de hook — pero **el tipo de hook es entonces un sustituto de la fecha**. Y la fecha arrastra crecimiento de seguidores, cambios de algoritmo y estacionalidad, que es exactamente lo que `Normalization.RECENCY_ADJUSTED` existe para quitar. **Si el hook es colineal con la fecha, quitar la tendencia temporal borra el efecto del hook con ella.** No queda varianza que pertenezca al hook.

Dicho corto: **hay variedad de repertorio y variedad de deriva, y en una tabla de frecuencias son idénticas. Sólo una sirve.**

Hay un segundo problema, más simple: **el ranking dentro de cuenta supone que la cuenta es aproximadamente constante.** Sobre 4,2 años no lo es. Un post de 2022 y uno de 2026 de la misma cuenta tienen audiencias, algoritmo y número de seguidores distintos. `RECENCY_ADJUSTED` corrige una tendencia monótona, no cuatro años de cambio de plataforma.

**La decisión: `spread`, pero acotado a una ventana de recencia. Propongo 12 meses.**

| Opción | Qué gana | Qué rompe |
|---|---|---|
| `recent` (50 últimos ≈ 3 meses) | Contexto homogéneo | Puede ser **una sola campaña**; no puede falsar "esta cuenta no varía" |
| `spread` sobre 4,2 años | Máxima variedad observable | La variedad probablemente es **deriva**, colineal con el confusor más fuerte |
| **`spread` dentro de 12 meses** | Falsa la hipótesis pesimista **y** mantiene la cuenta comparable consigo misma | Menos variedad observable si la cuenta cambió de estilo hace años — asumido a propósito |

Los números salen: a ~86 posts/año en esa cuenta, 12 meses dan ~86 posts disponibles para muestrear ~17 por cuenta en un piloto de 50/3 cuentas. **Sobra factor 5.** Y 12 meses cubre la variación estacional del inmobiliario sin cruzar eras de plataforma.

**Y lo que importa más que la elección: el piloto ahora mide si acertó.** `analysis.hook_temporal_separation()` calcula, por cuenta, la separación temporal entre tipos de hook — la distancia entre el percentil de recencia medio del tipo más antiguo y el del más reciente. Si supera el umbral, el veredicto es `hook_type_is_confounded_with_time=True` y **la variedad encontrada no es utilizable**, por mucha que haya.

Detalle aritmético que hubo que corregir sobre la marcha y que merece quedar escrito, porque el umbral evidente es inalcanzable: con dos tipos de igual tamaño perfectamente segregados en el tiempo, los percentiles medios son 0,25 y 0,75 → separación **0,50**, que es el **máximo** que puede producir una cuenta equilibrada de dos tipos, no un punto medio. Un umbral de 0,5 con `>` estricto **jamás habría disparado en el caso exacto que debía cazar**. El umbral queda en **0,25** — el punto medio real entre entrelazado perfecto (0) y segregación completa (0,5). Está pinchado en un test.

**Consecuencia práctica sobre el coste que me pasan:** acepto los ~125 intentos y 45-60 min para 50 vídeos. Acotar a 12 meses debería además **subir** la tasa de éxito respecto al 0,40 del `spread` a catálogo completo, porque el fallo se concentra en los posts viejos — pero eso es una predicción mía, no una medida, y el piloto la comprobará sola.

### C.6 Qué bloquea hoy la Fase C, después de la corrección del 2026-08-06

Con el prerrequisito 6 retirado, conviene decir con precisión qué queda, porque **"ya no está bloqueado por el VLM" no es lo mismo que "está desbloqueado"**. Verificado contra el disco hoy, no recordado:

| # | Qué falta | ¿De quién depende? | Estado |
|---|---|---|---|
| 1 | **Nombrar 8-12 cuentas** (C.5.1-3) | Fundador | Abierto. Sigue siendo el bloqueo principal |
| 2 | ~~El runner de corpus no existe~~ | — | **CERRADO 2026-08-06.** `yt-dlp` baja mp4 + métricas + fecha, gratis y sin cuenta. Enumeración también gratis: 711 vídeos en tres cuentas candidatas |
| 3 | ~~El camino de adquisición barato no tiene código~~ | — | **CERRADO — y la pregunta se disolvió.** La adquisición sale **$0**, así que la comparación Data365/Apify/Zyte deja de importar. Ver la corrección en §C.3: los $6,64 tarifaban **metadatos**, y nadie había comprobado que pagar un registro diera un vídeo descargable |
| 4 | ~~Bajar los bytes del vídeo no está verificado~~ | — | **CERRADO, con matiz.** Verificado que **sí** se puede (5,7 MB en ~4 s), pero **no** por la vía que yo suponía: el `playAddr` de `parsers/tiktok.py:65-69` está **muerto** (403 con cualquier cabecera, reto anti-bot en JS). La vía es `yt-dlp` |
| 5 | **~7 horas-persona de etiquetado** (C.5.4) | Fundador + una segunda persona | Abierto. Sin dos etiquetadores no se puede correr el test F4. **Ya no es el primer gasto**: la puerta de viabilidad (§D.7-ter) va antes y puede evitarlo entero |
| 6 | ~~VLM alojado / GPU~~ | — | **CERRADO 2026-08-06. Nunca fue real** |
| 7 | ~~El nivel léxico era peninsular~~ | — | **CERRADO 2026-08-06.** Ver §B.2.1 |
| **8** | **¿Tiene el nicho varianza que explicar?** | **El piloto** | **ABIERTO, y es ahora el riesgo principal.** Engagement medido casi plano (likes 2-14, comentarios 0-3) y una candidata publicando sobre una sola plantilla. Si no hay varianza, no hay estudio — ver §D.7-ter. **Es lo primero que mide el piloto, por delante del etiquetado** |

**Detalle del punto 7, el dialecto.** El nivel léxico era peninsular y el corpus es de la frontera colombo-venezolana (`docs/corpus-candidatos-inmobiliario-tachira-cucuta.md`, gtm-specialist). Sin arreglarlo, `price_reveal` se hundía en el lado colombiano y `command_cta` desaparecía para los asesores que hablan de *usted* — dos de los cuatro tipos que compara el diseño. **Arreglado y medido: ver §B.2.1.** Consecuencia sobre el tamaño del corpus: **ninguna hoy** (217 sigue en pie); ver el párrafo añadido en §C.2 para el único escenario que sí lo cambiaría.

**Cómo ha cambiado la forma del riesgo en un día, que es lo que hay que leer de esta tabla.** Empezó siendo *"esto está bloqueado por acceso a modelos y por dinero de scraping"*. Los dos han resultado falsos: el VLM funcionaba y la adquisición sale gratis. Lo que queda es **una pregunta empírica sobre el nicho** —¿varía?— y **una decisión del fundador** —¿qué cuentas?—. **Ningún blocker que quede es técnico.**

**Riesgo nuevo y pequeño, que no bloquea pero conviene tener escrito:** al no haber tarifa citable para featherless-ai, tampoco se sabe cuánto crédito consumen 217 llamadas. HF da créditos mensuales gratuitos modestos y luego cobra; una corrida podría pararse a mitad por crédito agotado. **El piloto de 50 vídeos lo mide antes de que importe** — es un argumento más para hacer el piloto primero, no una razón para no correr.

<a id="fase-d"></a>

## Fase D — la correlación: qué se puede y qué no se puede concluir

### D.1 El análisis ingenuo produce una conclusión falsa que suena bien

"Agrupa por tipo de hook, haz la media de likes, ordena" es **peor que no hacer nada**. Entre vídeos de cuentas distintas, lo que más manda en los likes es **el tamaño de la audiencia**, no el creativo. Una cuenta de 200k seguidores gana a una de 2k en todos los tipos de hook que use, y una media entre cuentas acabará acreditando las costumbres de esa cuenta.

Hay un test en la suite que ejecuta exactamente ese fallo y comprueba que el diseño lo evita (`test_within_account_normalization_removes_the_follower_confound`).

### D.2 El diseño que sí aguanta

1. **Cada cuenta es su propio control.** La variable de resultado no son los likes, es el **percentil del post dentro de la biblioteca de su propia cuenta**. Seguidores, antigüedad, nicho, idioma y cadencia son constantes dentro de una cuenta: ordenar dentro de ella los elimina **todos a la vez, sin tener que medir ninguno**.
2. **Ajuste de recencia dentro de la cuenta.** Una biblioteca crece con su audiencia, así que los posts tardíos parten con ventaja. `RECENCY_ADJUSTED` quita esa tendencia por regresión.
3. **Un tipo de hook tiene que aparecer en varias cuentas** (mínimo 3) para contar. Si no, "los hooks de pregunta ganan" puede significar "un agente prolífico que además es bueno usa preguntas".
4. **Intervalo de confianza bootstrap sobre la MEDIANA**, no la media: el engagement tiene cola pesada y un solo vídeo viral arrastraría la media y convertiría el hook de ese vídeo en un "hallazgo general".
5. **Corrección de comparaciones múltiples** (Bonferroni). Con 13 tipos, un α=0,05 sin corregir espera ~0,65 falsos positivos por ejecución — y el informe los presentaría como hallazgos sin pestañear.
6. **El informe se declara no concluyente él solo** si el corpus no da: `CorrelationReport.conclusive` exige n suficiente, cuentas suficientes **y** que el intervalo excluya el 0,5.

### D.3 Qué controlo, qué controlo a medias y qué no controlo

Esta tabla vive en el código (`analysis.CONFOUNDERS`) y **se serializa dentro de cada informe**, no en una diapositiva de la que se cae al copiarla.

| Confusor | Estado | Cómo |
|---|---|---|
| Número de seguidores | **Controlado** | Ranking dentro de cuenta; es constante dentro de la biblioteca |
| Calidad y nicho del agente | **Controlado** | Mismo mecanismo: la comparación nunca cruza cuentas |
| Crecimiento de audiencia a lo largo de la biblioteca | **A medias** | `RECENCY_ADJUSTED`, cuando hay fechas |
| Duración del vídeo | **A medias** | Se captura y se puede comprobar |
| **Tema y calidad del inmueble** | **NO controlado** | Un caserón espectacular rinde da igual cómo empiece. Y probablemente correlaciona con el hook elegido → **los efectos salen inflados** |
| **Hora de publicación y algoritmo** | **NO controlado** | No medible desde datos scrapeados |
| **Música y caption** | **NO controlado** | Correlacionan con engagement y con estilo de hook |
| **Supervivencia de la biblioteca** | **NO controlado** | Los vídeos malos borrados nunca aparecen: sesga el corpus hacia arriba. Afecta a todo estudio sobre bibliotecas scrapeadas |
| **Error de medida del propio `hook_type`** | **NO controlado hoy** | Un VLM que se equivoca en el 20 % **atenúa todos los efectos hacia cero**. Se cierra con el golden set de C.3 |
| **País y registro de trato (*usted*/*tú*)** | **A medias** | El ranking dentro de cuenta ya lo absorbe mientras cada cuenta sea de un solo país y un solo registro, que es el caso normal. Lo que **no** absorbe es un tipo de hook ligado al registro: si los asesores que hablan de *usted* prefieren los mandatos, *"los mandatos ganan"* y *"Colombia gana"* son la misma frase. `second_person_register` viaja en cada fila para poder comprobarlo — test **F5** |

### D.4 El n mínimo, en números

| Pregunta | n necesario |
|---|---|
| Diferencia **grande** (d=0,8) entre dos tipos de hook | **26 posts por tipo** |
| Diferencia **mediana** (d=0,5) | **66 posts por tipo** |
| Diferencia **pequeña** (d=0,2) | 184 posts por tipo |
| Correlación de Spearman ρ=0,3 (p. ej. ritmo de habla ↔ percentil) | **91 posts** |
| Correlación ρ=0,2 | 206 posts |

Todos a 80 % de potencia, α=0,05 bilateral, con el recargo de test por rangos.

### D.5 Qué se podrá afirmar — y qué no, nunca, con este diseño

**Se podrá afirmar (si el corpus llega):**
> *"Entre estos 8 asesores, los posts que abrieron con una pregunta quedaron en el percentil X de su propia cuenta, frente al percentil Y de los que abrieron con una afirmación, con un intervalo que excluye el azar."*

**No se podrá afirmar, con ningún tamaño de corpus alcanzable:**
- *"Usar hook de pregunta **causa** más engagement."* No hay aleatorización ni contrafactual: nunca observas el mismo vídeo publicado sin ese hook.
- *"Abre así y tendrás 10.000 likes."* Los 10.000 likes son sobre todo la audiencia de la cuenta, no el hook.
- Nada sobre tipos de hook raros. Con 217 vídeos, un tipo que sea el 3 % del corpus tiene ~6 posts: no es medible, y aparecerá en el informe marcado como tal en vez de callado.

### D.6 Mi predicción, escrita por delante para que sea falsable

Siguiendo el precedente de `NOTES_fase0_agentive_layer.md` §3.2, dejo la apuesta antes de ver los datos:

> **Espero que las diferencias entre tipos de hook queden por debajo del umbral detectable con 217 vídeos, y que el informe salga `conclusive = False`.** La razón es D.3: tema/inmueble, música y caption no están controlados y plausiblemente pesan más que la apertura. Si sale que sí se detecta, es un resultado real y acepto la corrección.
>
> **Y si sale así, eso es un entregable válido y hay que decirlo tal cual.** "Con este corpus esto no se puede concluir todavía" es información: ahorra construir un producto sobre un efecto que no existe. Lo que **no** es aceptable es publicar el ranking igualmente porque queda bien en una demo.

### D.7-bis DECISIÓN (2026-08-06): la variable de resultado primaria pasa a ser **views**

Me pasan medidas de una cuenta candidata real de Cúcuta, seis vídeos: **views 383-1324, likes 2-14, comentarios 0-3**. La propuesta que me llega es ponderar views en vez de likes+comentarios, y se me deja la decisión. **La tomo: views pasa a ser el resultado primario.** Dos razones, y la segunda importa más que la primera.

**1. Resolución — y no es un argumento de muestra pequeña, es de aritmética.** Con los likes confinados a 2-14 hay **13 valores posibles**. En una biblioteca de ~30 posts, el principio del palomar obliga a que **al menos el 57 % de las comparaciones dentro de cuenta sean empates** (1 − 13/30), *sea cual sea la distribución*. El diseño de §D.2 rankea dentro de cuenta: con 57 % de empates el ranking casi no ordena nada. Con views (383-1324, ~940 valores posibles en 30 posts) no hay empates forzados. Esto está ahora en el código como test (`test_small_integer_likes_are_mostly_ties_by_pigeonhole`) y como criterio en `assess_viability()`, no como opinión.

**2. Qué significa cada columna, que es lo que me piden que no me salte.** No es cambiar de columna, es cambiar de pregunta:

| Variable | Qué mide realmente | Qué se puede afirmar con ella |
|---|---|---|
| **views** (nueva primaria) | **Distribución algorítmica.** En TikTok la distribución la manda la retención temprana — que es exactamente lo que compra un hook | *"Las aperturas de tipo X se distribuyeron más lejos dentro de su propia cuenta."* Es la variable **más cercana al mecanismo** que estudiamos |
| **engagement** (likes+comentarios) | Preferencia declarada de quien ya lo vio | Sigue reportándose como secundaria. Con estos rangos es en gran parte ruido de conteo entero |
| **engagement_rate** = engagement/views | Preferencia **condicionada** a haber sido mostrado; quita el componente de distribución | Útil como control, **pero no arregla el ruido: lo traslada.** Con 2 likes, un like es un 50 % de variación. El numerador sigue siendo el entero pequeño |
| **positive_sentiment_ratio** | Sentimiento de comentarios | **No usable en este nicho**: con 0-3 comentarios por post la proporción no es una proporción. Esto retira, para este corpus, la recomendación que hacía §D.7 |

**Lo que views empeora, dicho por delante:** es la variable **más contaminada por el algoritmo** y por todo lo que no es el hook (hora de publicación, sonido, velocidad de seguidores, sembrado). El ranking dentro de cuenta absorbe lo que sea constante en la cuenta, pero no absorbe lo que varía post a post. Así que el cambio **mejora la medida y empeora la limpieza**, y ese intercambio hay que decirlo cada vez que se reporte un resultado, no una vez.

**Los tres se calculan; la primaria es views.** `Outcome.VIEWS`, `Outcome.ENGAGEMENT_RATE` y `PostObservation.views` ya existen en `analysis.py`. `engagement_rate` devuelve `None` —nunca 0— cuando no hay views: un denominador vacío es una medida ausente, no un rendimiento bajo, e imputar 0 rankearía los posts no medidos como los peores de su biblioteca.

### D.7-ter PRECONDICIÓN (2026-08-06): puede que no haya varianza que explicar

Y esta es la parte que me preocupa más que la elección de columna. El diseño de §D.2 necesita **varianza por los dos lados**: dispersión en el resultado **y** variedad de hook dentro de cada cuenta. Los datos que llegan amenazan las dos: engagement casi plano, y una cuenta candidata publicando cinco vídeos seguidos sobre **una sola plantilla de caption**.

**El fallo sería silencioso**, que es lo peligroso: `_percentiles` mapea una biblioteca completamente empatada a 0,5 en todas las filas, así que un corpus sin varianza no da error — da efectos centrados exactamente en "no hay diferencia". Correcto como comportamiento, pésimo de descubrir tarde.

Por eso hay ahora una **puerta previa en código**, `analysis.assess_viability()`, que corre **antes** de cualquier correlación y puede vetarla. Mide y reporta:

- **fracción de empates** dentro de cuenta (umbral 0,5 — los likes medidos lo superan por aritmética),
- **valores distintos por cuenta** (umbral 5: por debajo, un percentil es una nota ordinal disfrazada de percentil),
- **cuentas con variedad de hook** (≥2 tipos con ≥2 posts cada uno): si sale **0**, no hay nada que comparar **por mucho que crezca el corpus**,
- **razón de dispersión** máx/mín dentro de cuenta, que se **reporta y no se usa como umbral**, porque no tengo un umbral defendible para ella.

**Un veredicto negativo aquí es un entregable, no un fallo.** Dice que el nicho no varía lo suficiente para estudiarlo, y eso ahorra construir producto sobre un efecto que nadie podría haber medido — exactamente el espíritu de §D.6.

**Donde discrepo, y es matiz que importa:** que views tenga 3,5× de rango **no es evidencia de que haya varianza sana**; es evidencia de que hay **resolución**. Son cosas distintas y confundirlas sería el error que llevo todo el día señalando. 383-1324 en una cuenta es un rango **estrecho** para este propósito: un hook que funciona de verdad en TikTok produce saltos de orden de magnitud, no de 3,5×. Un rango tan comprimido es compatible con que el algoritmo sencillamente **no esté diferenciando** entre esos vídeos. Y con **seis** vídeos no se mide varianza de ninguna manera: seis es una comprobación de resolución, no una medida de dispersión. La conclusión práctica no cambia —views sigue siendo la primaria— pero **no doy por medido que haya varianza**; eso lo tiene que contestar el piloto.

### D.7 Un cambio de variable que probablemente mejora el estudio

Tu enunciado incluye *"comentarios con análisis de sentimiento positivo"*. **Esa es mejor variable de resultado que los likes**, y merece la pena decirlo: el **ratio** de comentarios positivos ya viene normalizado por volumen, así que arrastra bastante menos el confusor de tamaño de audiencia que un conteo absoluto. `Outcome.POSITIVE_SENTIMENT_RATIO` ya está soportado en `analysis.py` y usa `sentiment.py` (robertuito) tal cual.

Dos avisos: **robertuito sigue sin licencia declarada en el Hub** (verificado en sesiones anteriores, sin resolver), y el ratio necesita suficientes comentarios por post para no ser ruido — con menos de ~20 comentarios la proporción salta demasiado.

> **Retirado para este corpus el 2026-08-06.** El segundo aviso se cumplió antes de empezar: los posts medidos tienen **0-3 comentarios**. La condición "~20 comentarios por post" no se acerca, así que `POSITIVE_SENTIMENT_RATIO` **no es una variable usable en este nicho**. La recomendación sigue siendo correcta en general y no aplica aquí. Ver §D.7-bis.

<a id="provenance"></a>

## Provenance

**Medido en la sesión de corrección (2026-08-06), no estimado:**

- **VLM alojado, extremo a extremo por el CLI nuevo:** `--vision hosted` sobre el fixture real → `vlm_backend=hosted`, `vlm_parse_ok=True`, `setting=urban_street`, `person_count=2`, `text_density=high`, texto en pantalla leído correctamente del rótulo del vídeo. 38,3 s de reloj **incluyendo** el arranque de `uv`/Python; el propio `extract_hook_features` tardó **5,8-7,4 s** (ventana de 3 s, sin ASR, tres corridas) y **11,7-17,8 s** (configuración completa por defecto: 3 ventanas → 3 llamadas ASR + 1 VLM, dos corridas).
- **La discriminación `auto` vs explícito:** `provider="featherless-ai"` → 200; `provider="auto"` → `400 model_not_supported`. `GET /api/models/Qwen/Qwen3-VL-4B-Instruct?expand[]=inferenceProviderMapping` devuelve **featherless-ai en `status: live`** y ningún otro proveedor.
- **Forma de tokens del prompt de hook**, reportada por la API sobre la hoja de contactos real: **316 prompt + 55 completion = 371 tokens**. Aviso honesto: no he podido verificar si ese conteo incluye los tokens de imagen.
- **Ausencia de tarifa, comprobada y no supuesta:** el catálogo de router de HF (`/v1/models`, 129 modelos) trae bloque `pricing` por proveedor pero **no contiene Qwen3-VL-4B**; el `inferenceProviderMapping` del modelo tampoco trae precios; featherless.ai publica planes ($25/mes plano, $50/mes por token) y ninguna tarifa por token por modelo. Por eso `VLM_USD_PER_VIDEO` sigue siendo `None`.
- **Reloj del corpus, ahora calculado por código:** `corpus.estimate_corpus_cost(plan_corpus())` → `extraction_hours_hosted_vlm = 0.9`, `extraction_hours_local_vlm = 72.3` para 217 vídeos en serie.
- **Dialecto (§B.2.1), medido antes y después con una batería de frases de la región**, no razonado de memoria: precios 0/4 → 4/4 en la forma colombiana, 3/4 → 4/4 en la venezolana, 2/2 en la peninsular; `usted` 0/9 → 9/9 en interpelación, con los tres negativos de tercera persona (*"El apartamento está en el centro"*, *"Mi cliente quiere comprar rápido"*, *"La casa tiene tres cuartos"*) **manteniéndose en `False`** y clasificados como `ambiguous`. El falso positivo preexistente de `para` (*"ideal para comprar"* → imperativo) confirmado y arreglado.
- **Aritmética de empates, no simulación.** Con los likes medidos (2-14) hay 13 valores posibles; en una biblioteca de 30 posts el principio del palomar fuerza **≥57 % de empates** dentro de cuenta sea cual sea la distribución. Con views (383-1324) no hay empates forzados. Es la base de la decisión de §D.7-bis y está en un test.
- **Lo que NO he medido y no afirmo:** que haya varianza de rendimiento en el nicho. Seis vídeos de una cuenta miden **resolución**, no dispersión, y un rango de 3,5× en views es estrecho para este propósito. La puerta `assess_viability()` existe precisamente para que eso lo conteste el piloto y no yo.
- **Suite:** `tests/test_hooks.py` pasa **92/92** offline (42 originales + 6 del backend de visión + 39 de dialecto y de los bugs que destapó + 5 de la puerta de viabilidad). La suite completa de `packages/models` pasa **252/252** y la raíz **311/311**. `ruff check` y `ruff format --check` limpios sobre todo lo tocado. Ficheros modificados: `providers.py`, `hooks/{extract,cli,schema,corpus,lexical,analysis}.py`, `tests/test_hooks.py`, este documento. **No he tocado `packages/api/`, `packages/scraper/`, `packages/shared/`, `migrations/` ni `Qualify/`.**

**Medido en la sesión original (2026-08-05), no estimado:**

- `python -m qualify_models.hooks --no-vlm --no-asr` sobre `tests/fixtures/sample_source.mp4` (1080×1920, 30 fps, 61,1 s): **funciona end-to-end en segundos**. Ventana de 3 s → 9 fotogramas, `cut_count=2`, `motion_energy=0,130`, `brightness=0,463`, `saturation=0,397`, paleta `#5b5a5f #dedae6 #a6989c #241423`. Ventana de 7 s → 21 fotogramas, `cut_count=5`.
- **Validación visual del proxy de cortes:** la hoja de contactos de 3 s (`sheet_3s.jpg`) muestra **3 planos distintos** — calle, interior con cortina metalizada morada, plano de una mano — o sea **2 cortes**, que es exactamente lo que contó `cut_count`. Una coincidencia sobre un vídeo no es una calibración, pero es la primera evidencia de que el proxy no está roto.
- El fixture **no es inmobiliario** (es un vídeo de evento de TikTok con rótulos "HOUSE OF CONFESSIONS"). Sirve para probar la fontanería, no la taxonomía.
- **42 tests nuevos** en `tests/test_hooks.py`, todos offline, sin pesos ni red: pasan (hoy son 48, ver arriba). `ruff check` limpio sobre todo lo nuevo.
- **La suite raíz sigue en 298/298** (`uv run --no-sync pytest -m "not integration"`). No he tocado `packages/api/`, `packages/shared/`, `migrations/` ni `Qualify/`.

**Hallazgo de entorno, preexistente y ajeno a este trabajo:** en el venv compartido de la raíz **no está instalado `jiwer`**, que vive en el grupo `eval` de `packages/models`. Nueve módulos de test del paquete (`test_eval_*`, `test_calibration`, `test_crm_cost`, `test_conversation_cost`, `test_fase0_cost`) **no se pueden ni recolectar** desde ahí. No afecta a la puerta de CI (la raíz no recolecta `packages/models/tests`) ni a nada de este spike, pero significa que "la suite de models pasa" no se puede afirmar hoy desde el venv compartido. Los 122 tests de models que no dependen de `jiwer` sí pasan.

**Cifras de coste:** todas calculadas por `hooks/corpus.py` con tarifas **citadas de `docs/alternativas-fase1.md`** (Data365 ~$0,60/1K registros; Apify ~$1,70/1K; Groq whisper-v3 ~$0,04/h). **Zyte por request y VLM alojado por vídeo se reportan como `None`**, no como cero: el repo no tiene esas tarifas y no se han inventado. Los segundos por vídeo de los dos backends de visión, en cambio, **sí son medidos** y viven en el mismo módulo.

**Cifras de tamaño de muestra:** calculadas por `hooks/analysis.py` (cuantil normal por la aproximación de Acklam, recargo por test de rangos documentado en el código). No hay ningún n copiado de una tabla.

**Documentos leídos y respetados:** `NOTES_fase0_agentive_layer.md` (§1.2 y §3.2 completas), `docs/oportunidades-mercado-inmobiliario.md` T-3, `docs/ingenieria-inversa-sortfeed.md` §5.1 y la tabla de roadmap, `docs/research-features-gtm.md` §"Profundidad del análisis de contenido".

**Sobre competencia:** `docs/research-features-gtm.md:52` documenta que **Kuli ya vende análisis de hook, audio, pacing y caption**, y que Syncly Social cubre audio+visual. En este documento no aparece en ningún sitio la afirmación de que nadie lo haga, porque sería falsa.

---

## Resumen de una línea

La Fase A cierra la condición que `sortfeed.md:396` llevaba abierta (ya hay definición de hook, falsable, con cuatro tests de refutación escritos por delante); la Fase B es código que corre hoy sobre el fixture real —**con el VLM alojado, en ~15 s por vídeo**— y produce una tabla comparable entre posts con provenance en cada fila; la Fase C ya **no** necesita ningún desbloqueo de VLM ni ninguna GPU (eso era un error mío, corregido en §B.5): necesita que el fundador nombre 8-12 cuentas, ponga ~7 horas de etiquetado y que alguien escriba el runner de corpus en `packages/scraper`, por **≈$7** más **~1 h de reloj**; y la Fase D está diseñada para poder decir *"con este corpus esto todavía no se puede concluir"* — que es el resultado que espero y que sería un entregable válido.
