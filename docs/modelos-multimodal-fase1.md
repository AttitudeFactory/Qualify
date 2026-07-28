# Selección de checkpoints para la cascada multimodal (Fase 1, Parte 1)

> ⚠️ **No describir este stack como "open-weight" de forma uniforme.** Tres de los cuatro
> checkpoints comprometidos son licencias OSI estándar (Apache-2.0 / MIT), pero el de visión
> **no lo es** (BSL 1.1) y el de sentiment **no declara licencia**. Ver la corrección de la
> sección F3 y el caveat de `pysentimiento`. Este aviso refleja la corrección ya registrada en
> `CLAUDE.md` (2026-07-21) y no debe divergir de ella.

**Alcance:** modelos concretos para las 3 etapas que sí se construyen en Fase 1 — filtro CLIP (F2), visión/VLM (F3), transcripción (F1) — más sentiment, ya confirmado.
**Método:** consulta directa al Hugging Face Hub (`hf models info` / `hf models card`, vía `hf-cli`) el 2026-07-17, con re-verificaciones en vivo el 2026-07-18, el 2026-07-21 y el 2026-07-23. El filtro (F2) y la transcripción (F1) sí son licencias OSI estándar (Apache-2.0 y MIT respectivamente). Las dos excepciones son: `moondream/moondream3-preview` — **BSL 1.1, no open-weight** (el Hub solo declara `other`; ver corrección en la sección de visión) — y `pysentimiento/robertuito-sentiment-analysis`, que **no declara licencia** en el Hub (ver caveat en la sección de sentiment).
**Por qué existe este doc:** `alternativas-fase1.md` compara proveedores/precios (buy vs build a nivel de infraestructura); este doc compara **qué pesos abiertos usar** dentro de la opción "build", porque son los mismos pesos que se pueden servir vía API gestionada (HF Inference Endpoints) o self-hosted (RunPod/Modal) sin reescribir el pipeline — ver la nota de cierre.

---

## F2 — Filtro CLIP (zero-shot, barato)

| Modelo | Parámetros | Licencia | Notas |
|---|---|---|---|
| `openai/clip-vit-base-patch32` (el propuesto originalmente) | ~151M | MIT | Más adoptado históricamente (23M descargas), rápido, pero accuracy zero-shot inferior a SigLIP2 |
| **`google/siglip2-base-patch16-224`** (recomendado) | 375M | Apache-2.0 | Misma arquitectura de uso en `transformers` (`pipeline(task="zero-shot-image-classification")`), mejor accuracy zero-shot que CLIP clásico por diseño del pretraining (loss sigmoide + mezcla de objetivos) |
| `google/siglip2-so400m-patch14-384` | 1.1B | Apache-2.0 | Mejor aún, pero 3× más pesado — erosiona la ventaja de costo de "filtro barato antes del VLM"; **no** recomendado para F2 |

**Implicación:** cambiar CLIP → SigLIP2-base es un swap de una línea (mismo pipeline de `transformers`), sin costo adicional relevante, con mejor accuracy. Usar el `so400m` solo si un benchmark propio muestra que `base` pierde demasiados candidatos válidos.

> **⚠️ Estado real en código (architect, 2026-07-24) — leer antes de usar F2 en cualquier estimación.** La elección de checkpoint de arriba sigue en pie; **lo que no está en pie es el comportamiento del filtro tal como está implementado**. `run_filter` devuelve `passed=False` para toda entrada (scores ~1e-4 contra umbral 0,22), luego **descarta el 100 %, no el ~25 % que documenta `arquitectura.md` §3.4**, y deja la etapa de visión inalcanzable vía `run_cascade`. Es la tarea #13 y **no está diagnosticada**: compiten una hipótesis de unidades (SigLIP emite sigmoides independientes, no softmax — y 0,22 parece calibrado como si fuera softmax) y una de torre de texto rota (`bos/eos_token_id` en rango CLIP sobre vocabulario de ~32k). **Implican arreglos distintos.** Deliberadamente **no se propone aquí un umbral nuevo**: recalibrar sobre una torre de texto rota quemaría el esfuerzo de etiquetado del golden set y seguiría fallando. El umbral se fija cuando la causa raíz esté resuelta y exista medición. Análisis completo en `arquitectura.md` §3.4, nota de reconciliación.

---

## F3 — Visión / VLM (análisis semántico profundo)

| Modelo | Params (activos) | Licencia | Notas |
|---|---|---|---|
| `Qwen/Qwen2.5-VL-7B-Instruct` (el propuesto originalmente) | 8.3B (denso) | Apache-2.0 | Sigue siendo el más adoptado (10M descargas), maduro, bien documentado |
| `Qwen/Qwen3-VL-4B-Instruct` / `Qwen/Qwen3-VL-8B-Instruct` | 4.4B / 8.8B (denso) | Apache-2.0 | Generación más nueva: OCR en 32 idiomas (vs. 19), mejor grounding espacial/2D-3D, contexto nativo 256K, "reconoce todo" (marcas, productos, landmarks) — relevante para detección de marca/producto que hoy es diferenciador de Qualify |
| **`vikhyatk/moondream2`** (el propuesto originalmente) | 1.9B (denso) | Apache-2.0 | Ahora "generación anterior" según su propio model card — Moondream recomienda migrar a v3 |
| ~~**`moondream/moondream3-preview`** (recomendado)~~ **→ degradado a candidato no validado, ver corrección abajo** | **9.27B totales** (~18.5 GB), ~2B activos (MoE, 8 de 64 expertos por token) | **BSL 1.1** (Business Source License, licenciante M87 Labs) — **no open-weight**; el Hub solo declara `other` | SOTA reportado por el propio Moondream reteniendo el costo de inferencia de un modelo ~2B gracias a MoE; expone **skills estructuradas** (`caption`, `query`, `detect`, `point`) que devuelven JSON/bounding-boxes directamente. **Sin ningún Inference Provider y nunca ejecutado en este repo** |

**Implicación (corregida 2026-07-21, ver abajo):** la recomendación primaria de este doc era `moondream3-preview` por sus "skills tipadas" (fit natural con el requisito de **provenance** y salidas estructuradas de `docs/arquitectura.md`) y su costo de inferencia MoE. **Esa recomendación ya no se sostiene tal como estaba escrita.** El camino de visión de facto es `Qwen/Qwen3-VL-4B-Instruct` — denso, más maduro, mejor OCR/reconocimiento amplio, requiere más prompt-engineering para output estructurado, y es **el único camino de visión que alguna vez ha funcionado en este repo**. Riesgo propio a registrar: lo sirve **un solo** Inference Provider (featherless-ai), que además exige nombrarlo explícitamente (ver la actualización del 2026-07-17 más abajo).

### Corrección del checkpoint de visión (verificado contra el Hub en vivo el 2026-07-21; re-confirmado el 2026-07-23)

Fuente: `packages/models/NOTES_fase0_agentive_layer.md` §1.2, con el `LICENSE.md` completo descargado del repo. Replicado en `CLAUDE.md` y en el addendum del ADR 19 de `docs/arquitectura.md` — **esta sección debe mantenerse consistente con esas dos, no divergir.** Supersede la corrección parcial del 2026-07-18, que solo decía "licencia `other`": describirlo así **subestima** el problema, porque BSL es un objeto materialmente distinto de una licencia sin etiquetar.

Tres defectos, todos verificados en vivo, ninguno de ellos "rot" — son problemas preexistentes:

- **Licencia: BSL 1.1 (Business Source License), licenciante M87 Labs — no open-weight.** El metadato del Hub dice `license: other`; el `LICENSE.md` real es BSL con un *Additional Use Grant* que permite uso en producción **excepto** ofrecer el trabajo a terceros de forma hosted/embebida para competir con las versiones de pago de M87. *Change Date*: dos años post-release, y entonces pasa a Apache-2.0. El uso de Qualify **probablemente** está permitido — un CRM de social listening no "se solapa significativamente" con una API de VLM — pero eso es una lectura legal, no de ingeniería. **El ADR 13 rechazó modelos de embeddings CC-BY-NC por motivos de uso comercial: BSL merece el mismo test explícito, no un aprobado implícito.**
- **9.27B parámetros (~18.5 GB) y cero Inference Providers.** El plan posiciona la etapa de visión como GPU-serverless-o-hosted. A 9.27B y sin ningún provider, **la opción "comprarlo hosted para empezar" no existe para este checkpoint**: exige GPU propia desde el día uno, lo que **invierte la secuencia buy-first** de `docs/alternativas-fase1.md`.
- **Nunca se ha ejecutado en este repo.** La caché local contiene 16 KB (un puntero `refs/main` y un blob); los pesos jamás se descargaron. El checkpoint de visión que este doc recomendaba ha producido **cero salidas** en el proyecto.

**Estado honesto:** `Qwen/Qwen3-VL-4B-Instruct` (Apache-2.0 confirmado) es el checkpoint de visión **de facto**, y `moondream3-preview` es una **aspiración no validada**, no una decisión. Reevaluarlo en Parte 3 (con GPU serverless propia) es legítimo, pero solo después de (a) pasar el test de licencia comercial del ADR 13 y (b) validarse contra el golden-set de `arquitectura.md` §7 — que sigue sin ejecutarse.

### 2026-07-17 — Actualización tras implementar Parte 1: ni Featherless ni Moondream2 funcionaron

Al implementar `packages/models`, ninguna de las dos rutas de arriba resultó viable en la práctica, por razones distintas a la calidad del modelo:

- **`moondream3-preview` vía API:** no tiene ningún Inference Provider que lo sirva (`inferenceProviderMapping` vacío) — solo se puede usar self-hosted, lo cual no aplica todavía (Parte 3, sin GPU serverless).
- **`Qwen/Qwen3-VL-4B-Instruct` vía HF Inference Providers (`featherless-ai`, único proveedor que lo sirve):** falla con `400 model_not_supported` — *"not supported by any provider you have enabled"* — a pesar de que el toggle de Featherless AI aparece activado en `huggingface.co/settings/inference-providers` sin custom key, de generar un token fine-grained nuevo con el permiso `Make calls to Inference Providers`, y de probar `bill_to` apuntando a un org con billing propio (Agromileto). No se identificó la causa exacta — parece un problema del lado de HF/Featherless para esta cuenta específica, no reproducible por documentación. **No perseguir más sin evidencia nueva** (p. ej. un caso similar reportado en el foro de HF); si se retoma, la vía más prometedora es crear cuenta directa en featherless.ai y usar su API key nativa como "custom key" en vez de depender del routing compartido de HF.

  **2026-07-18 — evidencia nueva (parcialmente obsoleta, ver causa raíz abajo):** Verificado en vivo vía `huggingface.co/Qwen/Qwen3-VL-4B-Instruct` (widget de chat, autenticado con sesión de navegador): dos llamadas completaron exitosamente vía Featherless AI y se facturaron a la cuenta. Se probó también con dos tokens de API distintos (fine-grained existente y un "Read" clásico recién creado, ambos con `Make calls to Inference Providers` activo) y ambos fallaban con el mismo `400 model_not_supported` — lo cual en su momento hizo parecer que la diferencia real era auth por token vs. sesión de navegador.

  **Causa raíz encontrada (mismo día, investigación posterior vía MCP hf-mcp-server + reproducción directa):** no es un problema de auth. Es `provider="auto"` en `InferenceClient` — el problema no era el token ni la sesión, sino que ambas pruebas con token usaban `provider="auto"`, y el widget del navegador no pasa por ese resolver. Confirmado por `hub_repo_details` (MCP hf-mcp-server) que Featherless AI es el **único** Inference Provider que sirve este modelo, marcado `live`. Reproducido con `huggingface_hub.InferenceClient` usando el mismo token de API:

  ```python
  InferenceClient(model="Qwen/Qwen3-VL-4B-Instruct", provider="auto")
  # → 400 model_not_supported: "not supported by any provider you have enabled"

  InferenceClient(model="Qwen/Qwen3-VL-4B-Instruct", provider="featherless-ai")
  # → 200 OK, funciona (probado con texto y con tests/fixtures/sample_frame.jpg)
  ```

  Es decir: cuando solo hay un provider habilitado para un modelo, el resolver de `"auto"` no lo está encontrando para esta cuenta — nombrar el provider explícitamente evita el problema por completo. `openai/whisper-large-v3-turbo` (F1, transcripción) **no** tiene este problema — `provider="auto"` funciona bien ahí (probado en vivo), así que el fix se aplicó solo a `HFInferenceVisionProvider`, no a `HFInferenceTranscriptionProvider`. No hace falta reportarlo en el foro de HF ni seguir investigando auth — ya no es la causa.
- **`vikhyatk/moondream2` local (CPU):** carga pero **rompe al inicializar** con `transformers==5.14.1`: su clase `trust_remote_code` (`HfMoondream`) no define `all_tied_weights_keys`, atributo que el `_finalize_model_loading` interno de esa versión de `transformers` ya asume que existe. Es una incompatibilidad de la librería con código remoto no mantenido para versiones nuevas (moondream2 está discontinuado a favor de moondream3), no algo arreglable desde nuestro código sin parchear la clase.

**Decisión final para Parte 1 (la que implementa el código):** `Qwen/Qwen3-VL-4B-Instruct` **local**, vía la clase nativa `Qwen3VLForConditionalGeneration` de `transformers` (no remote-code, sin las incompatibilidades de arriba). Costo: 8.8B parámetros densos (~2× el tamaño de moondream3-preview activo) y sin las skills estructuradas de Moondream — pero es la única opción de las evaluadas que efectivamente corre hoy sin depender de una cuenta de terceros. `moondream3-preview` self-hosted queda como candidato a revisar en Parte 3 cuando haya GPU serverless propia.

**Nota tras el fix de `provider="auto"` (mismo día):** con la causa raíz resuelta, `HFInferenceVisionProvider` (API, sin descargar/correr 8.8B params localmente) es ahora una opción viable para `Qwen/Qwen3-VL-4B-Instruct` — ya no está bloqueada. No se cambia el provider por defecto en `vision.py` (sigue siendo `LocalQwenVisionProvider`) como parte de este fix; es una decisión de costo/latencia (local vs. buy) a evaluar aparte, no una consecuencia automática de arreglar el bug.

---

## F1 — Transcripción

| Modelo | Notas |
|---|---|
| **`openai/whisper-large-v3-turbo`** (recomendado, ya implícito en el plan vía faster-whisper) | Mismo encoder que `whisper-large-v3`, decoder podado de 32→4 capas → mucho más rápido con degradación mínima. Es el mismo modelo que corre por debajo tanto `faster-whisper` (self-host, CTranslate2) como Groq (API) — **no hay decisión de modelo real aquí, solo de quién lo hostea** (ver alternativas-fase1.md) |
| `mistralai/Voxtral-Mini-4B-Realtime-2602` | Modelo de streaming en tiempo real (<500ms de latencia), 13 idiomas, Apache-2.0. No aplica a Fase 1 (transcripción batch de contenido ya scrapeado) — candidato a evaluar en fases posteriores si Qualify agrega alertas en vivo sobre streams/lives |

**Implicación:** no cambia nada del plan original — se confirma `whisper-large-v3-turbo` (o `large-v3` si el 1-2% de accuracy extra importa más que la velocidad) como el checkpoint, indistintamente de si se sirve vía Groq (buy) o `faster-whisper` (self-host).

---

## Sentiment — ~~confirmado, sin cambios~~ **REABIERTO (F1, 2026-07-24). La decisión ya no es de procurement: es de golden-set**

`pysentimiento/robertuito-sentiment-analysis` sigue siendo, por lejos, el modelo de sentiment en español para redes más adoptado. ~~No se investiga más — se mantiene la elección original.~~ **Esa frase se retira.** `datasci` hizo el barrido en vivo del Hub y el resultado invierte el supuesto sobre el que descansaba.

### El supuesto que era falso

La postura por defecto era *"aceptar y anotar: si algún día legal dice que no, se cambia el modelo"*. Eso sólo es un plan si **existe un reemplazo equivalente y con licencia**. El barrido dice que casi no existe:

| Candidato | Licencia | Por qué no cierra |
|---|---|---|
| `pysentimiento/robertuito-sentiment-analysis` | **Ninguna declarada** | El incumbente. Además **sin Inference Provider** → self-host es la única vía |
| `cardiffnlp/twitter-xlm-roberta-base-sentiment` (53,4M desc.) | **Ninguna declarada** | Mismo problema, no es salida |
| `cardiffnlp/...-multilingual` (11,2M desc.) | **Ninguna declarada** | Ídem |
| `finiteautomata/beto-sentiment-analysis` (23,8M desc.) | **Ninguna declarada** | **Mismos autores y mismo paper que pysentimiento** → el hueco es el mismo *por construcción*, no por coincidencia |
| `tabularisai/multilingual-sentiment-analysis` | **cc-by-nc-4.0** | Exactamente la clase que **ADR 13 ya rechazó** por uso comercial |
| `nlptown/bert-base-multilingual-uncased-sentiment` | MIT | Forma equivocada: es un valorador de **reseñas de producto** de 1–5 estrellas, no polaridad de texto social |
| `UMUTeam/roberta-spanish-sentiment-analysis` | **apache-2.0**, 3 clases | Base (`roberta-base-bne`) = corpus de noticias/BOE, **no texto social**; no publica métricas; 29,5K descargas. Sigue siendo contendiente de golden-set, ya **no** el único |
| **`clapAI/modernBERT-base-multilingual-sentiment`** | **apache-2.0**, 3 clases (neg/neu/pos) | **Contendiente primario (adopción/calidad).** ModernBERT (ene 2025), multilingüe incl. `es`, **hf-inference en vivo** (resuelve el hueco de provider del incumbente). Drop-in label-compatible con robertuito → cero cambio de contrato `SentimentProvider` |
| **`clapAI/mmBERT-small-multilingual-sentiment`** | **MIT**, 3 clases | **Contendiente primario (coste/licencia).** mmBERT-small (sep 2025), el más barato y de licencia más limpia. Drop-in label-compatible. Mismo caveat de dominio |

**Verificado en vivo por `datasci-rm` + el lead contra el Hub (2026-07-24): los tres campos de licencia de los candidatos clapAI son OSI estándar (apache-2.0 / MIT).** Retira la conclusión previa *"UMUTeam el único viable"* — que precedía a la familia clapAI y a la instrucción del fundador de buscar un modelo más moderno.

**Por eso la decisión cambia de naturaleza — y el caveat load-bearing sobrevive intacto:** ahora **sí** existen reemplazos con licencia limpia y moderna, pero **todos son multilingües de dominio mixto/reseñas, NO específicos de texto social en español** como el entrenamiento TASS-tweets de robertuito. El swap cambia **coincidencia de dominio por licencia limpia**, y si eso cuesta exactitud sobre texto social uruguayo/colombiano es **una pregunta de golden-set (~100 comentarios etiquetados), no de compras**. La medición es el entregable, no la elección de modelo. *"Lo cambiamos si hace falta"* dejó de tener cola ilimitada (el fallback existe y está licenciado); lo que queda es medir cuánto se degrada.

### El error de intuición que hacía sentir segura la opción de aceptar-y-anotar

Conviene decirlo explícitamente porque es contraintuitivo y sesga en la dirección peligrosa: **"sin licencia declarada" no significa "sin restricciones". Significa lo contrario.** A falta de una concesión expresa, aplica el copyright por defecto, es decir **ninguna licencia de uso**. Una CC-BY-NC es *mejor* información que la ausencia de licencia: con NC sabes los términos y sabes que son incompatibles; sin licencia no tienes concesión de la que partir.

**Consecuencia de coherencia con ADR 13:** si CC-BY-NC se rechazó por motivos de uso comercial, un modelo **sin ninguna licencia** no puede pasar por la vía implícita. Debe someterse **al mismo test explícito**, con el mismo criterio.

### Ruling (architect, PROPUESTO — la aceptación final del riesgo la firma el fundador, no ingeniería)

1. **Gate:** robertuito **puede** usarse en desarrollo y evaluación. **No puede ser la única vía de sentiment en GA** sin que el fundador acepte el riesgo explícitamente y por escrito. Es una decisión de riesgo de negocio, no técnica.
2. **Construir el seam `SentimentProvider` ahora**, no cuando haga falta. Convierte un riesgo de cola ilimitada en uno acotado: si la respuesta legal es "no", se sustituye una implementación, no un pipeline. Es el mismo patrón de `Provider` que `packages/models` ya usa para VLM/ASR — no es diseño nuevo, es aplicar el que ya existe a la etapa que hoy no lo tiene.
3. **El seam no basta por sí solo, y ésta es la parte que no se puede aplazar:** hay que **medir los candidatos de licencia limpia contra el golden-set**, junto al incumbente. Contendientes primarios: **`clapAI/modernBERT-base-multilingual-sentiment` (apache-2.0)** y **`clapAI/mmBERT-small-multilingual-sentiment` (MIT)** — ambos drop-in label-compatibles con robertuito, uno vía adopción/calidad y el otro vía coste/licencia; `UMUTeam/roberta-spanish-sentiment-analysis` (apache-2.0) queda como tercer contendiente. Sin esa medición el seam sólo traslada la incertidumbre, porque los tres son de dominio no-social-español y el coste de exactitud es desconocido hasta medirlo. Es un ítem de golden-set con nombre y apellidos (cierra R6).
4. **No se propone ningún umbral ni ninguna sustitución a ciegas.** Igual que con el defecto del filtro F2, recalibrar o cambiar sin medición quema esfuerzo y no cierra nada.

### Sobre la concentración de riesgo — se atenúa por una decisión ya tomada, y hay que verificar que no se ha mudado

El planteamiento original era que, en la vía de cuentas conectadas, robertuito pasaría de ser 1 de 4 etapas a **toda la propuesta de valor de IA del día uno**. **Eso ya no es exacto**, y la razón es el ruling de `integracion-cuentas-conectadas-meta.md` §3.4(b): el valor diferenciado del bucle de atención está en la clasificación de **intención y urgencia** (zero-shot NLI), no en la polaridad de 3 clases. El sentiment es un input de ese bucle, no su producto.

**Pero eso mueve la concentración, no la elimina** — y el sitio al que la mueve es `MoritzLaurer/bge-m3-zeroshot-v2.0`. Ese checkpoint debía pasar el mismo test de licencia del ADR 13 antes de apoyar nada en él, y **lo pasa: verificado en vivo por el lead contra el Hub (2026-07-24) como MIT.** El target de concentración de §3.4(b) es de licencia limpia — no se cambió un modelo sin licencia por otro, el problema **no** migró con el mismo nombre. Queda el mismo caveat de dominio que los candidatos de sentiment: MIT no garantiza exactitud sobre texto social ES, que sigue siendo pregunta de golden-set.

---

## Clasificador zero-shot de texto (propuesto, Fase 3 — fuera de alcance de este doc, registrado aquí por continuidad de stack)

**Nota de scope:** este doc cubre solo Fase 1 Parte 1 (F1/F2/F3 + sentiment, ya implementados en `packages/models`). Esta sección se añade porque `packages/models/NOTES_pain_signal_feasibility.md` (datasci, 2026-07-18) identificó un gap que bloquea la Fase 3 tal como está descrita en `backlog-features-gtm.md` (P3-1, librería de señales tipadas): **robertuito solo emite polaridad de 3 clases**, y la mayoría de señales de valor (queja de pago, fricción de brand-deal, intención de sponsorship, "crisis" más allá de negatividad genérica) son *tópico/intención*, no polaridad — la polaridad sola no puede separarlas. No hay ningún checkpoint de FTC/ad-disclosure dedicado en el Hub; la vía práctica es reglas + NLI zero-shot.

| Checkpoint (verificado en vivo contra el Hub, 2026-07-18) | Tarea | Params | Licencia | Notas |
|---|---|---|---|---|
| **`MoritzLaurer/bge-m3-zeroshot-v2.0`** (recomendado) | Clasificación de texto zero-shot (NLI) | 567.8M (xlm-roberta) | **MIT** | Multilingüe incl. ES; labels candidatas arbitrarias, sin datos de entrenamiento etiquetados. Comparte base con `BAAI/bge-m3` (ya propuesto para embeddings de lookalike/RAG en `arquitectura.md` §4/§8.1) → sinergia de familia de checkpoint, no un modelo aislado más. Disponible en HF Inference Providers (patrón buy-primero del resto del stack) |
| `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | Clasificación de texto zero-shot (NLI) | 278.8M | MIT | Fallback más barato (~½ params, menor latencia/costo, calidad algo menor). Multilingüe incl. ES |
| `pysentimiento/robertuito-emotion-analysis` | Emoción (ES) | ~109M | *no declarada en metadata del Hub* | Mismo patrón/infra que el sentiment ya comprometido (cero infra nueva, mismo CPU worker) — refina burnout/ansiedad (ejes miedo/tristeza) pero no reemplaza el clasificador de tópico |

**Costo:** corre solo sobre texto que ya sobrevivió las etapas baratas del cascade (caption siempre, transcript si F1 corrió, top-N comentarios) — nunca sobre contenido descartado. Estimado **<5% del costo por video del cascade completo** (dominado por VLM+ASR); self-hosted en Fase 3 el costo incremental es ruido de cómputo. Ver detalle de cálculo en `packages/models/NOTES_pain_signal_feasibility.md` §5.

**Caveat de licencia (heredado, no nuevo):** el Hub no declara licencia para los repos `pysentimiento/robertuito-*`, lo que incluye el sentiment **ya comprometido** en Fase 1, no solo la adición de emoción — verificar contra el repo/paper original antes de considerarlo cerrado para uso comercial (aplica el mismo guardrail que ADR 13 de `arquitectura.md` para embeddings no-comerciales). Si resulta no-comercial, los modelos zero-shot (MIT) pueden emitir labels tipo emoción también, como sustituto limpio.

**Estado: propuesto, no lockeado.** Es un candidato a stack de Fase 3, condicionado a que la librería de señales tipadas (P3-1) entre a sprint — no se fija en código hasta esa decisión de scope y su propia validación en el golden-set (extensión descrita en `NOTES_pain_signal_feasibility.md` §4: labels multi-label a nivel de fragmento, sobre los mismos ~100 videos, con calibración de umbral por señal — recall-first para crisis/pago, precision-first para señales que disparan acción automática).

---

## Recomendación final F2/F3/F1 (self-hosted / vía HF Inference Endpoints)

```
F2 filtro   → google/siglip2-base-patch16-224                 (Apache-2.0)
F3 visión   → Qwen/Qwen3-VL-4B-Instruct                       (Apache-2.0) — DE FACTO, el único que ha corrido aquí
              moondream/moondream3-preview                    (BSL 1.1)    — NO validado; bloqueado por test de licencia + golden-set
F1 audio    → openai/whisper-large-v3-turbo                   (MIT)
sentiment   → pysentimiento/robertuito-sentiment-analysis     (SIN licencia declarada) — incumbente, dev/eval only, no GA sin firma del fundador
              clapAI/modernBERT-base-multilingual-sentiment   (Apache-2.0) — contendiente primario de golden-set (drop-in, hf-inference en vivo)
              clapAI/mmBERT-small-multilingual-sentiment      (MIT)        — contendiente primario (coste/licencia); UMUTeam apache-2.0 = 3.º
              (los tres son de dominio no-social-ES: la elección la decide el golden-set, no la licencia)
texto (Fase 3, propuesto) → MoritzLaurer/bge-m3-zeroshot-v2.0 (MIT, verificado 2026-07-24)  (fallback: mDeBERTa-v3-base-xnli-multilingual-nli-2mil7, MIT)
```

**Por qué esto resuelve *parcialmente* la decisión API-vs-self-hosted:** los checkpoints de F2, F1, sentiment y el zero-shot de texto son públicos en el Hub y se pueden servir hoy vía **HF Inference Endpoints** (`hf endpoints deploy`, pago por uso, cero infra propia) para validar el pipeline end-to-end sin esperar a tener GPU serverless propia, y migrar después a RunPod/Modal self-hosted **sin cambiar de modelo ni reescribir el pipeline** — el adaptador de proveedor solo cambia el endpoint HTTP, no el contrato de datos ("Opción 3, interfaz intercambiable"). Esa propiedad la garantiza el `Provider` Protocol ya implementado en `packages/models/src/qualify_models/providers.py`.

**Dónde *no* aplica, y es la excepción que importa:** la etapa de visión (F3).

- `moondream3-preview` **no tiene ningún Inference Provider**, así que la ruta "comprar hosted primero" simplemente no existe para él (ver corrección de la sección F3).
- `Qwen3-VL-4B-Instruct` sí tiene ruta hosted, pero con **un único proveedor** (featherless-ai) que además hay que nombrar explícitamente.

Es decir: **la secuencia buy-first de `docs/alternativas-fase1.md` se sostiene para tres de las cuatro etapas, pero no para la más cara.** Eso es exactamente lo contrario de lo que conviene y debería pesar en cualquier decisión de hosting de Fase 1 Parte 3.

**Pendiente real, no resuelto por este research:** validar estos cuatro modelos contra el golden-set de videos etiquetados que ya menciona `docs/arquitectura.md` §7 antes de comprometerse en código — este doc reduce el espacio de búsqueda, no reemplaza la evaluación empírica.
