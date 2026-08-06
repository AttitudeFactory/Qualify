# Spike: detección de *hooks* publicitarios en vídeo corto (inmobiliario)

**Owner:** datasci (FDE) · **Fecha:** 2026-08-05 · **Estado:** Fases A y B entregadas; **Fase C bloqueada esperando al fundador**; Fase D diseñada y ejecutable, sin datos.
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
- [Fase B — el extractor y su esquema de salida](#fase-b)
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

**F4 es la que hay que comprobar primero y es la más barata**: 30 vídeos, dos personas, media hora. Si la taxonomía no es reproducible entre humanos, ningún modelo la va a reproducir tampoco, y todo lo demás sobra.

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

### B.5 HALLAZGO OPERATIVO: el VLM local no sirve para un corpus

Medido en esta máquina, no estimado. **Qwen3-VL-4B local (`LocalQwenVisionProvider`) tardó más de 20 minutos en una sola llamada de hook y no había terminado cuando lo corté** (20 min 48 s de reloj, ~50 % de CPU, pesos descargados a disco — `transformers` avisa: *"Some parameters are on the meta device because they were offloaded to the disk"*). Configuración: hoja de contactos 3×3 de 9 fotogramas a 320 px por celda (960×1707 px) y `max_new_tokens=256`.

**Consecuencia directa para la Fase C, y corrige la línea "VLM local = $0" de la tabla de costes:** a 20 min/vídeo, los 217 vídeos del plan son **~72 horas de portátil**. El dinero es cero; el reloj no. **La corrida del corpus necesita o un VLM alojado o una GPU de verdad.**

Y ahí hay un bloqueo conocido, ya documentado en `providers.py`: el único Inference Provider que sirve Qwen3-VL es **featherless-ai**, y `provider="auto"` devuelve `400 model_not_supported` para esta cuenta. **Resolver el acceso al VLM alojado es un prerrequisito de la Fase C, no un detalle de última hora.**

Mitigación ya aplicada en el código (reduce, no resuelve): la hoja de contactos ahora **submuestrea a 6 fotogramas y 256 px por celda** — el nivel determinista sigue leyendo los 9, porque es gratis. Eso recorta ~53 % de píxeles enviados al modelo.

**Lo que esto NO cambia:** el nivel determinista y el léxico corren enteros en segundos, sin red y sin pesos. El extractor sigue siendo ejecutable hoy; lo que no es ejecutable hoy a escala es la columna que escribe el VLM.

<a id="como-ejecutarlo"></a>

## Cómo ejecutarlo

Desde la raíz del repo. **Nunca `uv sync`**; `--no-sync` es de sólo lectura y no toca el venv compartido.

**a) Modo determinista — sin red, sin pesos, segundos.** Es el que se puede correr hoy mismo:

```bash
PYTHONPATH=packages/models/src uv run --no-sync python -m qualify_models.hooks \
  --video packages/models/tests/fixtures/sample_source.mp4 \
  --source-id sample_tiktok \
  --no-vlm --no-asr --keep-artifacts \
  --out-dir /tmp/hooks
```

**b) Completo — Qwen3-VL local para la imagen + whisper alojado para el audio:**

```bash
PYTHONPATH=packages/models/src uv run --no-sync python -m qualify_models.hooks \
  --video packages/models/tests/fixtures/sample_source.mp4 \
  --source-id sample_tiktok --keep-artifacts \
  --out-dir /tmp/hooks
```

> El `PYTHONPATH=...` es un rodeo a la instalación editable rota del venv compartido que documenta `CLAUDE.md` (`import qualify_models` falla desde la raíz). No es parte del diseño.

Salida en `--out-dir`:
- `hook_features.jsonl` — el registro completo por vídeo (todo, incluida la salida cruda del VLM si falló el parseo).
- `hook_features.csv` — **una fila plana por (vídeo × ventana)**. Ésta es la tabla que se abre en una hoja de cálculo y la que se une con las métricas en la Fase D.
- `artifacts/<source_id>/frames/*.jpg` y `sheet_3s.jpg` — con `--keep-artifacts`. **Mira la hoja de contactos**: es la forma más rápida de ver exactamente lo que se le enseñó al modelo.

Tests: `PYTHONPATH=src:../shared/src uv run --no-sync --project .. python -m pytest tests/test_hooks.py -q` desde `packages/models` → **42 pasan**, offline, sin pesos.

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

**Requisito no obvio, y es el que más riesgo tiene:** el diseño compara tipos de hook **dentro de cada cuenta**. Una cuenta que siempre abre igual **no aporta nada** al análisis, por muchos vídeos que tenga. Al elegir las 8 cuentas hace falta **variedad de aperturas**, y eso sólo se puede comprobar *después* de extraer. Es la segunda cosa que mide el piloto.

### C.3 Cuánto cuesta

Con `corpus.estimate_corpus_cost()` sobre el plan de 217 vídeos (≈11.100 registros contando 50 comentarios por post):

| Partida | Coste | Fuente |
|---|---|---|
| Adquisición vía **Data365** | **$6,64** | `docs/alternativas-fase1.md` §2a: ~$0,60/1K registros |
| Adquisición vía **Apify** | $18,81 | ibíd.: ~$1,70/1K |
| Adquisición vía **Zyte** | **no calculable** | El repo sólo cita el **plan** ($100/mes), nunca un precio por request. No lo invento |
| Transcripción (15 s/vídeo × 217) | **$0,04** | Groq whisper-v3 ~$0,04/h |
| Visión, Qwen3-VL **local** | **$0 en dinero, ~72 h de portátil** | Ver §B.5: >20 min/vídeo medidos. **No es viable a escala de corpus** |
| Visión, alojada | **no calculable** | Las formas de token de `fase0_cost.py` nunca se trazaron contra este prompt |
| **Total en dinero** | **≈ $7** | Data365 + ASR alojado + VLM local |

**El dinero no es el cuello de botella. Siete dólares.** El coste real es otro:

| Partida | Coste real |
|---|---|
| **Etiquetado humano del golden set** (100 vídeos × 2 personas × 2 min) | **≈ 6,7 horas-persona** |
| Escribir el runner de corpus (no existe) | trabajo de ingeniería, ver C.4 |
| Tú eligiendo y nombrando las 8-12 cuentas | tu tiempo |

Si el VLM no está validado contra etiquetas humanas, `hook_type` es una columna que nadie puede defender — y entonces los $7 de scraping no compran nada. **Las 6,7 horas son el precio de entrada, no un extra.**

### C.4 El runner no existe — y propongo dónde va, no lo creo

`packages/scraper` tiene cliente Zyte y parsers de TikTok/IG, pero **no hay nada que baje N vídeos de M cuentas**, y no existe `scripts/`. Propuesta, para que la valide quien corresponda antes de que yo escriba una línea:

- **Va en `packages/scraper/src/qualify_scraper/harvest.py`** (o en un `scripts/harvest_corpus.py`), **no en `packages/models/`**. Descargar es trabajo de scraper, y hay otra developer en `packages/api/`; mi territorio es `packages/models/`.
- Salida a disco: `corpus/<account>/<post_id>.mp4` + un `corpus/metrics.csv` con `source_id, account_id, posted_at, likes, comments, views`. Ese CSV es exactamente lo que `analysis.PostObservation` consume — la costura entre las dos mitades ya está definida.
- **Es de la Parte 2, no de la Parte 3.** Nada de Celery, R2 ni esquemas analíticos: un script que escribe ficheros.

### C.5 Lo que te pido — y hasta que respondas, paro

1. **¿Qué cuentas?** Necesito **8-12 handles** de asesores inmobiliarios con al menos ~30 vídeos publicados cada uno. Tienes que nombrarlas tú; yo no sé cuáles son relevantes para tu mercado.
2. **¿TikTok o Instagram Reels?** Mezclar plataformas mete un confusor más (algoritmos distintos). Prefiero una sola para el piloto.
3. **¿España o LatAm?** El nivel léxico está escrito en español peninsular; funciona igual, pero el vocabulario de precios y ubicación cambia.
4. **¿Puedes poner ~7 horas de etiquetado** (tú + una segunda persona)? Si sólo hay una persona, se puede etiquetar igual **pero no se puede correr el test F4** — y entonces no sabremos si la taxonomía es siquiera reproducible entre humanos.
5. **¿Autorizas el piloto primero?** **Mi recomendación fuerte: sí.** **50 vídeos de 3 cuentas, ≈$1,50**, para medir dos cosas que ahora mismo son conjeturas: la distribución real de tipos de hook, y si esas cuentas varían sus aperturas lo suficiente para que el diseño funcione. Con esas dos medidas el plan de 217 deja de ser una estimación.
6. **Prerrequisito técnico, no negociable, que sale de §B.5:** hay que **desbloquear un VLM alojado** (featherless-ai rechaza esta cuenta hoy) o conseguir una GPU. Con el VLM local, 217 vídeos son ~72 horas de portátil. Esto se puede resolver en paralelo mientras decides las cuentas.

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

### D.7 Un cambio de variable que probablemente mejora el estudio

Tu enunciado incluye *"comentarios con análisis de sentimiento positivo"*. **Esa es mejor variable de resultado que los likes**, y merece la pena decirlo: el **ratio** de comentarios positivos ya viene normalizado por volumen, así que arrastra bastante menos el confusor de tamaño de audiencia que un conteo absoluto. `Outcome.POSITIVE_SENTIMENT_RATIO` ya está soportado en `analysis.py` y usa `sentiment.py` (robertuito) tal cual.

Dos avisos: **robertuito sigue sin licencia declarada en el Hub** (verificado en sesiones anteriores, sin resolver), y el ratio necesita suficientes comentarios por post para no ser ruido — con menos de ~20 comentarios la proporción salta demasiado.

<a id="provenance"></a>

## Provenance

**Medido en esta sesión (2026-08-05), no estimado:**

- `python -m qualify_models.hooks --no-vlm --no-asr` sobre `tests/fixtures/sample_source.mp4` (1080×1920, 30 fps, 61,1 s): **funciona end-to-end en segundos**. Ventana de 3 s → 9 fotogramas, `cut_count=2`, `motion_energy=0,130`, `brightness=0,463`, `saturation=0,397`, paleta `#5b5a5f #dedae6 #a6989c #241423`. Ventana de 7 s → 21 fotogramas, `cut_count=5`.
- **Validación visual del proxy de cortes:** la hoja de contactos de 3 s (`sheet_3s.jpg`) muestra **3 planos distintos** — calle, interior con cortina metalizada morada, plano de una mano — o sea **2 cortes**, que es exactamente lo que contó `cut_count`. Una coincidencia sobre un vídeo no es una calibración, pero es la primera evidencia de que el proxy no está roto.
- El fixture **no es inmobiliario** (es un vídeo de evento de TikTok con rótulos "HOUSE OF CONFESSIONS"). Sirve para probar la fontanería, no la taxonomía.
- **42 tests nuevos** en `tests/test_hooks.py`, todos offline, sin pesos ni red: pasan. `ruff check` limpio sobre todo lo nuevo.
- **La suite raíz sigue en 298/298** (`uv run --no-sync pytest -m "not integration"`). No he tocado `packages/api/`, `packages/shared/`, `migrations/` ni `Qualify/`.

**Hallazgo de entorno, preexistente y ajeno a este trabajo:** en el venv compartido de la raíz **no está instalado `jiwer`**, que vive en el grupo `eval` de `packages/models`. Nueve módulos de test del paquete (`test_eval_*`, `test_calibration`, `test_crm_cost`, `test_conversation_cost`, `test_fase0_cost`) **no se pueden ni recolectar** desde ahí. No afecta a la puerta de CI (la raíz no recolecta `packages/models/tests`) ni a nada de este spike, pero significa que "la suite de models pasa" no se puede afirmar hoy desde el venv compartido. Los 122 tests de models que no dependen de `jiwer` sí pasan.

**Cifras de coste:** todas calculadas por `hooks/corpus.py` con tarifas **citadas de `docs/alternativas-fase1.md`** (Data365 ~$0,60/1K registros; Apify ~$1,70/1K; Groq whisper-v3 ~$0,04/h). **Zyte por request y VLM alojado por vídeo se reportan como `None`**, no como cero: el repo no tiene esas tarifas y no se han inventado.

**Cifras de tamaño de muestra:** calculadas por `hooks/analysis.py` (cuantil normal por la aproximación de Acklam, recargo por test de rangos documentado en el código). No hay ningún n copiado de una tabla.

**Documentos leídos y respetados:** `NOTES_fase0_agentive_layer.md` (§1.2 y §3.2 completas), `docs/oportunidades-mercado-inmobiliario.md` T-3, `docs/ingenieria-inversa-sortfeed.md` §5.1 y la tabla de roadmap, `docs/research-features-gtm.md` §"Profundidad del análisis de contenido".

**Sobre competencia:** `docs/research-features-gtm.md:52` documenta que **Kuli ya vende análisis de hook, audio, pacing y caption**, y que Syncly Social cubre audio+visual. En este documento no aparece en ningún sitio la afirmación de que nadie lo haga, porque sería falsa.

---

## Resumen de una línea

La Fase A cierra la condición que `sortfeed.md:396` llevaba abierta (ya hay definición de hook, falsable, con cuatro tests de refutación escritos por delante); la Fase B es código que corre hoy sobre el fixture real y produce una tabla comparable entre posts con provenance en cada fila; la Fase C necesita que el fundador nombre 8-12 cuentas y autorice **≈$7 de scraping más ~7 horas de etiquetado**, con un piloto de $1,50 recomendado antes; y la Fase D está diseñada para poder decir *"con este corpus esto todavía no se puede concluir"* — que es el resultado que espero y que sería un entregable válido.
