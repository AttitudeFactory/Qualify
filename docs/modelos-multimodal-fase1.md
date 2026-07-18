# Selección de modelos open-weight para la cascada multimodal (Fase 1, Parte 1)

**Alcance:** modelos concretos para las 3 etapas que sí se construyen en Fase 1 — filtro CLIP (F2), visión/VLM (F3), transcripción (F1) — más sentiment, ya confirmado.
**Método:** consulta directa al Hugging Face Hub (`hf models info` / `hf models card`, vía `hf-cli`) el 2026-07-17. Todos los candidatos son Apache-2.0.
**Por qué existe este doc:** `alternativas-fase1.md` compara proveedores/precios (buy vs build a nivel de infraestructura); este doc compara **qué pesos abiertos usar** dentro de la opción "build", porque son los mismos pesos que se pueden servir vía API gestionada (HF Inference Endpoints) o self-hosted (RunPod/Modal) sin reescribir el pipeline — ver la nota de cierre.

---

## F2 — Filtro CLIP (zero-shot, barato)

| Modelo | Parámetros | Licencia | Notas |
|---|---|---|---|
| `openai/clip-vit-base-patch32` (el propuesto originalmente) | ~151M | MIT | Más adoptado históricamente (23M descargas), rápido, pero accuracy zero-shot inferior a SigLIP2 |
| **`google/siglip2-base-patch16-224`** (recomendado) | 375M | Apache-2.0 | Misma arquitectura de uso en `transformers` (`pipeline(task="zero-shot-image-classification")`), mejor accuracy zero-shot que CLIP clásico por diseño del pretraining (loss sigmoide + mezcla de objetivos) |
| `google/siglip2-so400m-patch14-384` | 1.1B | Apache-2.0 | Mejor aún, pero 3× más pesado — erosiona la ventaja de costo de "filtro barato antes del VLM"; **no** recomendado para F2 |

**Implicación:** cambiar CLIP → SigLIP2-base es un swap de una línea (mismo pipeline de `transformers`), sin costo adicional relevante, con mejor accuracy. Usar el `so400m` solo si un benchmark propio muestra que `base` pierde demasiados candidatos válidos.

---

## F3 — Visión / VLM (análisis semántico profundo)

| Modelo | Params (activos) | Licencia | Notas |
|---|---|---|---|
| `Qwen/Qwen2.5-VL-7B-Instruct` (el propuesto originalmente) | 8.3B (denso) | Apache-2.0 | Sigue siendo el más adoptado (10M descargas), maduro, bien documentado |
| `Qwen/Qwen3-VL-4B-Instruct` / `Qwen/Qwen3-VL-8B-Instruct` | 4.4B / 8.8B (denso) | Apache-2.0 | Generación más nueva: OCR en 32 idiomas (vs. 19), mejor grounding espacial/2D-3D, contexto nativo 256K, "reconoce todo" (marcas, productos, landmarks) — relevante para detección de marca/producto que hoy es diferenciador de Qualify |
| **`vikhyatk/moondream2`** (el propuesto originalmente) | 1.9B (denso) | Apache-2.0 | Ahora "generación anterior" según su propio model card — Moondream recomienda migrar a v3 |
| **`moondream/moondream3-preview`** (recomendado) | 9.3B total, **~2B activos** (MoE, 8 de 64 expertos por token) | Apache-2.0 | SOTA reportado por el propio Moondream reteniendo el costo de inferencia de un modelo ~2B gracias a MoE; expone **skills estructuradas** (`caption`, `query`, `detect`, `point`) que devuelven JSON/bounding-boxes directamente — mucho menos parsing/prompt-engineering que pedirle texto libre a un modelo chat genérico como Qwen-VL |

**Implicación:** `moondream3-preview` es la recomendación primaria — mismo patrón de "skills tipadas" que ya usaba Moondream2 (fit natural con el requisito de **provenance** y salidas estructuradas de `docs/arquitectura.md`), con el salto de calidad de MoE. Riesgo: sigue en estado "preview" — **fijar `revision` al descargar** y no asumir estabilidad de API entre releases. Fallback si el golden-set de validación (ya planeado en `arquitectura.md` §7) muestra accuracy insuficiente en detección de marca: `Qwen/Qwen3-VL-4B-Instruct` (denso, más maduro, mejor OCR/reconocimiento amplio, pero requiere más prompt-engineering para output estructurado y ~2× el costo de inferencia de moondream3-preview al no ser MoE).

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

## Sentiment (confirmado, sin cambios)

`pysentimiento/robertuito-sentiment-analysis` sigue siendo, por lejos, el modelo de sentiment en español para tweets/redes más adoptado (589K descargas vs. <1K de cualquier alternativa encontrada). No se investiga más — se mantiene la elección original.

---

## Recomendación final F2/F3/F1 (self-hosted / vía HF Inference Endpoints)

```
F2 filtro   → google/siglip2-base-patch16-224
F3 visión   → moondream/moondream3-preview  (fallback: Qwen/Qwen3-VL-4B-Instruct)
F1 audio    → openai/whisper-large-v3-turbo
sentiment   → pysentimiento/robertuito-sentiment-analysis
```

**Por qué esto resuelve también la decisión API-vs-self-hosted que quedó pendiente:** los cuatro son checkpoints públicos en el Hub. Se pueden servir hoy vía **HF Inference Endpoints** (`hf endpoints deploy`, pago por uso, cero infra propia) para validar el pipeline end-to-end sin esperar a tener GPU serverless propia, y migrar después a RunPod/Modal self-hosted **sin cambiar de modelo ni reescribir el pipeline** — el adaptador de proveedor solo cambia el endpoint HTTP, no el contrato de datos. Esto es lo mismo que la "Opción 3 (interfaz intercambiable)" discutida antes, ahora con modelos concretos en vez de una decisión abstracta.

**Pendiente real, no resuelto por este research:** validar estos cuatro modelos contra el golden-set de videos etiquetados que ya menciona `docs/arquitectura.md` §7 antes de comprometerse en código — este doc reduce el espacio de búsqueda, no reemplaza la evaluación empírica.
