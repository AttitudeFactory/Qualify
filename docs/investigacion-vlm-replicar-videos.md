# VLM para "ver" reels y devolver un blueprint replicable — investigación

**Fecha de la investigación:** 2026-10-20. Todos los precios, nombres de modelo y límites salen de páginas leídas ese día (sección 6). Donde algo no se pudo verificar, lo digo.
**Alcance:** elegir un modelo que vea un reel (MP4 vertical de 5 a 90 s, audio en español, texto en pantalla, música) y devuelva un JSON con el gancho, la lista de planos con timestamps, el texto en pantalla, el guion, la música y el ritmo, el CTA y por qué funciona. Ese JSON alimentará Seedance, Seedream y Remotion.

> **Aviso sobre las cifras de calidad.** Casi todos los benchmarks de vídeo publicados en 2026 los mide el propio proveedor. Ninguno mide la tarea que necesitamos (planos con cortes de menos de 1 s, texto en pantalla en español, reels 9:16). La decisión final tiene que salir de una prueba con nuestro golden set (sección 4.6). Esta investigación sirve para elegir a quién probar, no para declarar un ganador.

---

## 1. Resumen y recomendación

### Para empezar (comprar): **Gemini 3.8 Flash** (`gemini-3.8-flash`), modo `static`, resolución de medios alta y `fps` 2 (en reels con cortes rápidos, entre 2 y 4)
- Es el único candidato que cumple todo en una sola llamada: vídeo y audio nativos, timestamps `MM:SS`, salida forzada a **JSON Schema**, contexto de 1M, Files API de hasta 20 GB y control de `fps` y recorte. Es estable y salió el 2026-09-02.
- Tiene la mejor evidencia publicada de comprensión de vídeo (LVBench 87.1 % en static y 87.8 % en agentic, según el propio Google). Su documentación es la más madura de los candidatos.
- **Coste:** unos USD 0.023 por reel de 30 s y unos 0.037 por reel de 60 s (cálculo en la §2). **Atención:** Google publica que su precio **se duplica el 2027-01-01** (entrada de 0.75 a 1.50 y salida de 3.75 a 7.50 USD por millón de tokens). Aun así sigue en céntimos por reel.
- **Variante barata del mismo proveedor:** `gemini-3.5-flash-lite` (0.30/2.50) o `gemini-3.1-flash-lite` (0.25/1.50, audio a 0.50) cuesta alrededor de USD 0.01 por reel, con la misma API y el mismo esquema. Conviene incluirla en la prueba.

### Segunda opción, más barata y ya con cuenta: **ByteDance Seed 2.0 Lite** (`seed-2-0-lite-260428`) en BytePlus ModelArk
- **Ya tenemos cuenta y clave en `ap-southeast-1`**: no hay que dar de alta otro proveedor ni firmar otro DPA. El endpoint `/responses` o `/chat/completions` es el mismo que ya usamos para Seedance.
- Acepta vídeo con su **pista de audio** en la misma llamada (ASR en 19 idiomas, español incluido). Admite `fps` entre 0.2 y 5, inserta el timestamp `"4.0 second"` antes de cada frame y la documentación recomienda el modo `json_schema`.
- **Coste:** unos USD 0.015 por reel de 30 s y unos 0.025 por reel de 60 s con fps 2. `seed-2-0-mini-260428` baja a unos 0.004 y 0.008.
- **Ventaja estratégica:** es la misma familia que Seedance. Describe los vídeos con un vocabulario cercano al que Seedance entiende, pero eso es una hipótesis que hay que medir.
- **Lo débil:** casi no hay benchmarks de vídeo verificables. El VideoMME 87.7 de Lite solo aparece en fuentes de terceros. La documentación solo se lee con JavaScript activado.
- **Opción ultrabarata:** `qwen3.8-omni-flash` (Alibaba Model Studio, internacional). Ve vídeo y oye audio, cuesta unos USD 0.005 por reel de 30 s y está disponible en Virginia, Frankfurt y Singapur. **No soporta JSON Schema**, solo JSON Mode, y salió hace un mes (2026-09-18). Sirve como tercera opción en la prueba, no como primera.

### Para autoalojar más adelante: **Qwen3.6-35B-A3B** (Apache-2.0) para vídeo y OCR, más **whisper-large-v3-turbo** (ya está en el repo) para la voz
- Tiene pesos abiertos con licencia Apache-2.0 y es un MoE con 3B de parámetros activos, así que es barato de servir. Según Qwen: VideoMME 82.5 sin subtítulos, MVBench 74.6 y CC-OCR 81.9. Se sirve con vLLM.
- No oye audio, pero eso encaja con la arquitectura propuesta: Whisper y el análisis de música van aparte de todos modos (§4).
- **Alternativa de un solo modelo:** **Qwen3-Omni-30B-A3B-Instruct** (Apache-2.0, vídeo y audio, voz en español). Su ficha pide unos **88.5 GB en BF16 para un vídeo de 30 s** y unos 108 GB para uno de 60 s, o sea dos GPUs o cuantización. Es claramente peor en vídeo (VideoMME 70.5).
- **Sobre lo que hay hoy en el repo:** el Qwen3-VL-4B que usamos es de la generación anterior. Recomiendo no construir el blueprint sobre él.

**Lo que no recomiendo:**
- **OpenAI:** a 2026-10-20 no acepta vídeo en Responses ni en Chat. Solo trabaja con frames sueltos.
- **Twelve Labs Pegasus 1.6:** está especializado en vídeo, pero es más caro, no publica la lista de idiomas y obliga a pagar un plan de USD 99 al mes para el uso por consumo.
- **Amazon Nova 2 Lite:** no procesa el audio, deforma cada frame a 672×672 y su propia documentación admite una comprensión limitada del texto multilingüe en los frames.

---

## 2. Tabla comparativa

**Supuestos de coste por reel (iguales para todos):**
- Prompt de texto con instrucciones y esquema: 2,000 tokens.
- Salida JSON, incluido el razonamiento: 4,000 tokens para 30 s y 6,000 para 60 s. Si el modelo razona mucho, la salida puede duplicarse, y la salida es el componente dominante del coste.
- Muestreo indicado en cada fila. Las fórmulas están debajo de la tabla.

| Modelo (id) | Vídeo nativo | Audio en la misma llamada | Duración / tamaño máx. | Timestamps | OCR de texto en español | Salida JSON estructurada | Coste reel 30 s | Coste reel 60 s | Regiones del hosting | Licencia / pesos | Debilidades conocidas |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Gemini 3.8 Flash** `gemini-3.8-flash` | Sí | Sí (32 tok/s) | ~1 h en alta resolución o ~3 h en baja con 1M de contexto; File API 20 GB (pago) | Sí, `MM:SS`; 1 fps por defecto, fps configurable | Sin cifra pública específica; hay que probarlo | **JSON Schema** (`response_format.schema`) | **≈ $0.023** (→ $0.046 desde 2027-01) | **≈ $0.037** (→ $0.074) | Gemini API global; regiones de Vertex no verificadas | Propietario, sin pesos | Precio ×2 en enero de 2027; a 1 fps se pierden cortes rápidos (lo dice la propia documentación) |
| Gemini 3.5 Flash-Lite `gemini-3.5-flash-lite` | Sí | Sí | Igual (1M) | Igual | No verificado | JSON Schema | ≈ $0.013 | ≈ $0.021 | Igual | Propietario | Sin benchmarks de vídeo publicados |
| Gemini 3.1 Flash-Lite `gemini-3.1-flash-lite` | Sí | Sí (audio a $0.50/M) | Igual | Igual | No verificado | JSON Schema | ≈ $0.009 | ≈ $0.014 | Igual | Propietario | Generación anterior |
| Gemini 4 Argon / 3.1 Pro | Sí | Sí | 1M | Sí | No verificado | JSON Schema | ≈ $0.061 / $0.069 | ≈ $0.099 / $0.111 | Igual | Propietario | De 3 a 5 veces más caro; Argon sube el 2026-12-01 |
| **Seed 2.0 Lite** `seed-2-0-lite-260428` (ModelArk) | Sí (frames con timestamps) | Sí (pista de audio del vídeo, ~6.25 tok/s, $3.75/M) | Files API 512 MB (2 GB con TOS); URL 50 MB; 16 a 1,280 frames; 80K tokens de vídeo por defecto | Sí: inserta "`N.N second`" antes de cada frame; fps de 0.2 a 5 | Sin cifra pública; ASR en es con timestamps por carácter | `json_schema` (recomendado en la ficha) | **≈ $0.015** (fps 2) | **≈ $0.025** (fps 2) | ap-southeast-1 y eu-west-1 | Propietario | Benchmarks de vídeo no verificables; razonamiento profundo puede inflar la salida; documentación solo con JS |
| Seed 2.0 Mini `seed-2-0-mini-260428` | Sí | Sí ($1.50/M) | Igual | Igual | No verificado | `json_schema` | ≈ $0.004 | ≈ $0.008 | Igual | Propietario | Modelo pequeño; calidad por medir |
| Seed 2.0 Pro `seed-2-0-pro-260328` | Sí | **No** (sin precio de audio ni fila en "Audio understanding") | Igual | Igual + visual grounding | No verificado | No aparece en la lista de capacidades | ≈ $0.025 sin audio | ≈ $0.042 sin audio | Igual | Propietario | — |
| **Qwen3.8-Omni-Flash** `qwen3.8-omni-flash` (Model Studio) | Sí | Sí (7 tok/s) | 2 h; URL 2 GB; base64 <10 MB | Sí; la documentación espera ~0.5–1 s en cortes | No verificado | **Solo JSON Mode, sin JSON Schema** | **≈ $0.005** | ≈ $0.008 | Beijing, Singapur, HK, Tokio, Frankfurt, Virginia | Propietario (API-only según la prensa) | Lanzado el 2026-09-18; precio del audio no desglosado (asumí el mismo $0.15) |
| Qwen3-VL-Plus `qwen3-vl-plus` | Sí | **No** ("no entiende la pista de audio") | 1 h, 2 GB | Alineación texto-timestamp | Qwen3-VL: OCR en 39 idiomas, >70 % en 32 (prensa) | `response_format` (no verificado para vídeo) | ≈ $0.010 + Whisper | ≈ $0.025 + Whisper | Singapur | Propietario (familia con pesos abiertos) | Hay que añadir ASR aparte |
| Qwen3-VL-235B-A22B / 30B-A3B / 8B / 4B (pesos) | Sí | No | 20 min (open-source en Model Studio) | Alineación texto-timestamp; Charades-STA 64.8 (235B) y 56 (8B), cifras de agregador | 32 idiomas (ficha HF) | Según el servidor (vLLM admite guided JSON) | Terceros: OpenRouter/Fireworks ~$0.20–0.22 in / $0.88 out (precio de vídeo no verificado) | — | Proveedores varios; HF lista solo DeepInfra para 235B | **Apache-2.0** | Generación de 2025; 4B claramente por debajo |
| **Qwen3.6-35B-A3B** (pesos) | Sí | No | Hasta escala de horas (~224K tokens de vídeo) | Sin cifra de grounding temporal publicada | CC-OCR 81.9 | Según el servidor | Self-host (coste de GPU) | — | HF lista Scaleway | **Apache-2.0** | Sin audio |
| Qwen3-Omni-30B-A3B-Instruct (pesos) | Sí | Sí (`use_audio_in_video`), voz en es | Limitado por VRAM | — | — | Según el servidor | Self-host: 88.5 GB BF16 para 30 s | 107.7 GB para 60 s | Sin proveedor hosted en HF | **Apache-2.0** | VideoMME 70.5; mucha VRAM |
| Twelve Labs Pegasus 1.6 | Sí (especializado) | Sí, aparentemente (los ejemplos citan audio; la documentación no lo afirma) | Hasta 2 h según marketing; 1 h en síncrono según la API | Sí: `segment_definitions` con `start_time`/`end_time` | Ejemplos en español; lista de 12 idiomas no publicada | Sí, formato propio de segmentos | ≈ $0.015 de vídeo + salida (precio de salida no verificado; ≈ $0.045 si son $7.5/M) | ≈ $0.029 + salida (≈ $0.074) | SaaS; Bedrock tiene Pegasus 1.2 | Propietario | El consumo exige el plan Pro de $99 al mes; sin benchmarks numéricos públicos |
| Amazon Nova 2 Lite (Bedrock) | Sí | **No** (documentación oficial) | S3 1 GB; inline 25 MB; 1 fps hasta 16 min | "Temporal segmentation" | **Limitado en texto multilingüe** (documentación oficial) | Sí, vía Converse | ≈ $0.013 (8,640 tok según la tabla oficial; precio de terceros) | ≈ $0.022 | AWS | Propietario | Deforma a 672×672 (malo para 9:16); sin audio |
| OpenAI GPT-6 Sol / Luna | **No** (solo texto e imagen) | No en Responses | — | — | — | Structured Outputs | No calculado (frames sueltos) | — | — | Propietario | Petición de soporte de vídeo cerrada como "not planned" |
| GLM-4.6V (Z.ai) | Sí (según terceros) | No | 128K de contexto | — | — | — | $0.30 / $0.90 (terceros) | — | Z.ai | MIT (pesos abiertos; licencia inconsistente según las fuentes) | No verificado contra la documentación oficial de Z.ai |

**Fórmulas** (precios en USD por millón de tokens):

- **Gemini 3.8 Flash, alta resolución y 1 fps.** Se cobran 258 tokens por frame más 32 tokens de audio por segundo, unos 290 tok/s en total.
  - 30 s: 30 × 290 = 8,700 tokens de vídeo + 2,000 de prompt = 10,700 tokens × $0.75 = $0.0080. Salida: 4,000 × $3.75 = $0.0150. **Total: $0.023.**
  - 60 s: 17,400 + 2,000 = 19,400 × $0.75 = $0.0146. Salida: 6,000 × $3.75 = $0.0225. **Total: $0.037.**
  - Con fps 2 en alta resolución (548 tok/s), 30 s sale a unos $0.029.
  - En resolución baja (unos 100 tok/s), 30 s sale a unos $0.019.
  - La página de precios no desglosa el audio de 3.8 Flash. Asumí la misma tarifa de entrada.
- **Gemini 3.5 Flash-Lite.**
  - 30 s: 10,700 × $0.30 = $0.0032. Salida: 4,000 × $2.50 = $0.010. **Total: $0.013.**
  - 60 s: 19,400 × $0.30 + 6,000 × $2.50 = **$0.021.**
- **Gemini 3.1 Flash-Lite.**
  - 30 s: vídeo y prompt 9,740 × $0.25 = $0.0024. Audio: 960 × $0.50 = $0.0005. Salida: 4,000 × $1.50 = $0.006. **Total: $0.009.**
- **Gemini 4 Argon.**
  - 30 s: 10,700 × $2 = $0.0214. Salida: 4,000 × $10 = $0.040. **Total: $0.061.**
- **Seed 2.0 Lite, fps 2.** Se cobran 384 tokens por frame (el valor por defecto en Seed 2.0+).
  - 30 s: 60 frames × 384 = 23,040 tokens + 2,000 de prompt = 25,040 × $0.25 = $0.0063. Audio: 30 × 6.25 = 188 tokens × $3.75 = $0.0007. Salida: 4,000 × $2.00 = $0.008. **Total: $0.015.**
  - 60 s: 46,080 + 2,000 = 48,080 × $0.25 = $0.0120. Audio: 375 × $3.75 = $0.0014. Salida: 6,000 × $2 = $0.012. **Total: $0.025.**
  - Todo cae en el tramo de 0 a 128K tokens. Un reel de 90 s a fps 2 da 69,120 tokens de vídeo, por debajo del tope de 81,920.
- **Seed 2.0 Mini, fps 2.**
  - 30 s: 25,040 × $0.10 + 188 × $1.50 + 4,000 × $0.40 = **$0.0044.**
- **Qwen3.8-Omni-Flash, fps 2.** Fórmula: `ceil(frames/2) × (H/32) × (W/32)`. Con un frame 9:16 de 576×1024 salen 576 tokens por cada par de frames.
  - 30 s: 30 × 576 = 17,280 tokens + 210 de audio + 2,000 de prompt = 19,490 × $0.15 = $0.0029. Salida: 4,000 × $0.47 = $0.0019. **Total: $0.005.**
- **Qwen3-VL-Plus, fps 2.**
  - 30 s: 19,280 × $0.20 + 4,000 × $1.60 = **$0.010.**
  - 60 s: 36,560 tokens, que cae en el tramo de 32K a 128K: × $0.30 + 6,000 × $2.40 = **$0.025.**
- **Twelve Labs.** $1.75 por hora de vídeo = $0.0292 por minuto, así que 30 s cuestan $0.0146 de vídeo. La salida de $7.5 por millón la reporta solo una calculadora de terceros. No la pude verificar.

**Latencia.** Ningún proveedor publica la latencia de vídeo de forma comparable. Hay que medirla en la prueba (p50 y p95). Gemini avisa de que el modo agentic aumenta el tiempo hasta el primer token. ModelArk y Gemini procesan el fichero subido antes de poder usarlo (estado `processing` → `active`), lo que añade unos segundos.

---

## 3. Fichas por candidato

### 3.1 Google Gemini (3.8 Flash, 3.5 y 3.1 Flash-Lite, 4 Argon, 3.1 Pro)

**Puntos fuertes:**
- Vídeo y audio se procesan juntos en una llamada.
- Ofrece un modo `static`, que muestrea a 1 fps por defecto con `processing.fps` configurable y recorte con `start_offset`/`end_offset`.
- Ofrece un modo `agentic`, en el que el modelo navega por la línea de tiempo. Está disponible en 4 Argon, 3.8 Flash, 3.6 Flash y 3.5 Flash-Lite, pero en clips cortos puede gastar más tokens.
- `media_resolution`: 66 tokens por frame en baja y 258 en alta. Para leer texto en pantalla conviene alta.
- JSON Schema con `response_format`, que cubre enum, min/max y prefixItems. Ojo: `minLength` y `maxLength` se eliminan sin aviso, así que hay que validarlos en nuestro código.
- Batch y Flex cuestan alrededor del 50 % del precio estándar, útil para analizar en lote los reels de "Descubrir".
- Acepta URLs de YouTube (en preview y gratis), aunque no nos sirve para TikTok ni Instagram.

**Puntos débiles:**
- La documentación avisa de que a 1 fps los cambios de escena rápidos pueden perder detalle. Por eso hay que subir el fps y detectar los cortes con ffmpeg o PySceneDetect (§4).
- 3.8 Flash duplica su precio el 2027-01-01 y Argon el 2026-12-01.
- La documentación no dice nada sobre la precisión de los timestamps.
- El free tier usa los datos para entrenar y tiene revisión humana, así que **solo se puede usar el tier de pago**. En pago, Google no entrena con nuestros datos y conserva un registro limitado para abuso (Términos Adicionales, modificados el 2026-04-28).
- No se verificó la disponibilidad regional para LatAm.

**Benchmarks:**
- LVBench (model card de 3.8 Flash): 87.8 % en agentic y 87.1 % en static, frente a 85.4 % de 3.7 Flash, 82.1 % de GPT-5.6 Sol y 75.4 % de Claude Opus 5. **Lo reporta Google.** La propia ficha dice que Claude se evaluó con menos frames.
- No encontré Video-MME ni benchmarks de OCR de vídeo para 3.8 Flash ni para 3.5 Flash-Lite.

### 3.2 ByteDance Seed en ModelArk (Seed 2.0 Lite, Mini y Pro; Dola Seed 2.1 Turbo)

**Puntos fuertes:**
- **Ya hay cuenta, clave y base URL** (`https://ark.ap-southeast.bytepluses.com/api/v3`).
- `seed-2-0-lite-260428` y `seed-2-0-mini-260428` aparecen a la vez en "Visual understanding" y en "Audio understanding" de la lista oficial. El tutorial de audio usa `seed-2-0-lite-260428` precisamente para analizar el audio embebido en un vídeo.
- Entrada por Files API (512 MB, guardado entre 1 y 30 días, 7 por defecto), por base64 (<10 MB) o por URL (≤50 MB).
- `fps` entre 0.2 y 5 (1 por defecto). Entre 64 y 384 tokens por frame (384 por defecto). Mínimo 16 frames y máximo 1,280. `max_video_tokens` de 81,920 por defecto.
- Antes de cada frame se inserta un texto con su timestamp ("4.0 second"). Eso es grounding temporal explícito.
- El ASR cubre 19 idiomas, español incluido, con timestamps por carácter o por frase y diarización.
- Se ofrece en ap-southeast-1 y, solo la serie seed-2-0, en eu-west-1.

**Puntos débiles:**
- No encontré cifras de vídeo verificables. El blog de lanzamiento (2026-02-14) afirma liderazgo en TVBench, TempCompass y MotionBench sin dar números. El VideoMME 87.7 de Lite aparece solo en un sitio de terceros (apiyi), y su valor coincide con el MMLU-Pro de la misma página, posible error de copia.
- `seed-2-0-pro` no figura con audio ni con structured output.
- seed-1-6 y seed-1-8 están en "Retiring".
- El razonamiento profundo puede inflar la salida, así que hay que probar a desactivarlo o limitarlo.
- No revisé los términos de uso de datos de BytePlus para este análisis. **Pendiente.**

### 3.3 Qwen (Alibaba Model Studio internacional y pesos abiertos)

**API:**
- `qwen3.8-omni-flash`, lanzado el 2026-09-18:
  - Entrada de texto, imagen, audio y vídeo, incluido el audio del vídeo (se factura por separado). Salida solo en texto.
  - Vídeos de hasta 2 h, 1M de contexto y 7 tokens de audio por segundo.
  - Se ofrece en Beijing, Singapur, HK, Tokio, Frankfurt y Virginia.
  - **JSON Mode sí, JSON Schema no.**
  - La documentación da precisiones esperadas: cortes de plano entre 0.5 y 1 s, diálogo en décimas de segundo. Recomienda segmentos de 2 min o menos para el máximo detalle.
  - Precio en Singapur: $0.15 de entrada y $0.47 de salida.
- `qwen3-vl-plus`: $0.20 / $1.60 (0–32K). **No entiende la pista de audio del vídeo** (documentación oficial).
- Vision: `fps` de 2.0 por defecto, rango de 0.1 a 10, 32×32 px por token.

**Pesos abiertos (Apache-2.0):**
- Qwen3-VL en 2B, 4B, 8B, 32B, 30B-A3B y 235B-A22B (informe técnico de nov-2025). Tiene "alineación texto-timestamp" y OCR en 32 idiomas según la ficha de HF. La prensa reporta OCRBench 875 para el modelo insignia y aciertos por encima del 70 % en 32 de 39 idiomas.
- Charades-STA: 64.8 para 235B y 56 para 8B-Instruct. **Son cifras de agregador**, sin que conste la métrica (mIoU o R@0.5).
- Qwen3.6-35B-A3B (abril de 2026), según la ficha de HF: VideoMME 82.5 sin subtítulos y 86.6 con ellos; MLVU 86.2, MVBench 74.6, LVBench 71.4 y CC-OCR 81.9.
- Qwen3-Omni-30B-A3B: vídeo y audio, VideoMME 70.5, ASR en 19 idiomas incluido el español. En BF16 pide 88.5 GB para 30 s y 107.7 GB para 60 s. Ningún proveedor lo sirve hosted en HF.

**Debilidades:** el modelo Omni más nuevo no tiene pesos abiertos. Qwen3.5-Omni y Qwen3.6-Plus son propietarios según Wikipedia y la prensa. El riesgo de depender de un solo proveedor en HF Inference Providers sigue igual que con el 4B actual.

### 3.4 Twelve Labs (Pegasus 1.6 y Marengo 3.0)

**Puntos fuertes:** es un producto pensado para vídeo, con `analysis_mode: "time_based_metadata"` y `segment_definitions`, que devuelven segmentos con `start_time`, `end_time` y campos que definimos nosotros. No necesita indexar antes ("zero pre-indexing"). Tiene SDKs y un servidor MCP.

**Puntos débiles:**
- Precio de consumo de $1.75 por hora de vídeo, pero **el consumo solo existe en el plan Pro de $99 al mes**. El plan Plus de $29 corta al llegar al límite.
- Los "12 idiomas" no están listados.
- No publica benchmarks numéricos; su comparación con Gemini y GPT es una tabla de marketing.
- La duración máxima es contradictoria: 2 h en marketing frente a 1 h en el endpoint síncrono.
- Bedrock solo ofrece Pegasus 1.2.

### 3.5 OpenAI
El changelog muestra GPT-6 Sol y Luna (2026-09-22) con entrada de texto e imagen, y GPT-6.1 Sol (2026-09-29). **No hay entrada de vídeo** ni en Responses ni en Chat. La issue que pedía vídeo nativo en openai-node (#1778) se cerró como "not planned". La vía documentada es extraer frames con ffmpeg y transcribir el audio aparte. No aporta nada sobre Gemini o Seed para este caso.

### 3.6 Amazon Nova 2 Lite
Documentación oficial:
- "No audio support".
- Deforma cada frame a 672×672, lo que destroza el 9:16 y el texto pequeño.
- "Limited understanding of multilingual images and video frames".
- No identifica a personas.

**Descartado.**

### 3.7 Otros
- **GLM-4.6V (Z.ai):** licencia MIT, acepta vídeo. Solo pude contrastar el precio y la licencia en sitios de terceros, que además se contradicen sobre la licencia. Puede servir como opción de autoalojamiento.
- **Gemma 4:** Apache-2.0. Según terceros, los modelos 26B y 31B aceptan vídeo de hasta 60 s, pero la ficha de NVIDIA del 31B no lista audio. Son fuentes no oficiales, así que no lo incluyo.
- **InternVL 3.5, Kimi-VL, VideoLLaMA3, Mistral y Llama 4:** no aparecieron como opciones hosted con vídeo y audio competitivas en 2026 dentro del tiempo de esta investigación. **No verificado**, por eso no están en la tabla.

---

## 4. Arquitectura propuesta en Qualify

### 4.1 Principio: lo determinista para lo medible, el VLM para lo que necesita comprensión
Los VLM muestrean entre 1 y 5 fps. En un reel hay cortes de 0.3 a 0.8 s, así que los cortes y el ritmo no se le deben pedir al VLM. Se miden con herramientas exactas y baratas, y el VLM recibe esas medidas como contexto:

```
MP4 (Descubrir reels o subida del operador)
 ├─ ffprobe            → duración, fps, resolución, ¿tiene audio?
 ├─ ffmpeg/PySceneDetect → lista de cortes exactos (s) → cortes/segundo, duración media de plano
 ├─ whisper-large-v3-turbo (ya en el repo) → transcript con timestamps por palabra (es)
 ├─ librosa (beat tracking) → BPM, beats, ¿cortes sincronizados al beat?
 └─ VLM (Gemini 3.8 Flash | Seed 2.0 Lite) con: vídeo + cortes + transcript en el prompt
        → JSON "blueprint" validado con Pydantic (response_format = JSON Schema)
            → post-validación: cada shot.start/end se ajusta al corte detectado más cercano (±0.3 s)
```

Ventajas de esta división:
- Los timestamps de los planos vienen de PySceneDetect, no de la memoria del VLM.
- El transcript es el de Whisper, que ya está evaluado aquí.
- El VLM se ocupa de lo que solo él puede hacer: qué se ve, el encuadre, el movimiento de cámara, la lectura del texto en pantalla, el gancho, el CTA y el porqué.
- Si cambiamos de VLM, no cambia nada más. Se implementa detrás de un `Provider`, el mismo patrón que `GenerationProvider` en `qualify_creative`.

### 4.2 Borrador del JSON Schema del blueprint (`reel_blueprint` v1)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ReelBlueprint",
  "type": "object",
  "required": ["schema_version", "source", "format", "hook", "shots", "on_screen_text", "voice", "audio", "pacing", "cta", "why_it_works"],
  "additionalProperties": false,
  "properties": {
    "schema_version": {"type": "string", "enum": ["reel_blueprint.v1"]},
    "source": {
      "type": "object",
      "required": ["duration_s", "aspect_ratio", "model", "model_revision", "pipeline_version"],
      "properties": {
        "duration_s": {"type": "number"},
        "aspect_ratio": {"type": "string", "enum": ["9:16", "1:1", "4:5", "16:9", "other"]},
        "platform": {"type": ["string", "null"], "enum": ["tiktok", "instagram", "upload", null]},
        "post_id": {"type": ["string", "null"]},
        "model": {"type": "string"},
        "model_revision": {"type": "string"},
        "pipeline_version": {"type": "string"}
      }
    },
    "format": {
      "type": "object",
      "required": ["archetype", "style", "people_on_camera", "language"],
      "properties": {
        "archetype": {"type": "string", "enum": ["product_showcase", "talking_head", "tutorial_recipe", "before_after", "pov", "list_top_n", "unboxing", "behind_the_scenes", "testimonial", "trend_meme", "slideshow", "other"]},
        "style": {"type": "string", "description": "ej. 'UGC handheld, luz natural, ritmo rápido'"},
        "people_on_camera": {"type": "integer", "minimum": 0},
        "faces_visible": {"type": "boolean"},
        "language": {"type": "string"}
      }
    },
    "hook": {
      "type": "object",
      "required": ["end_s", "visual", "spoken", "on_screen_text", "hook_type"],
      "properties": {
        "end_s": {"type": "number", "maximum": 5},
        "visual": {"type": "string"},
        "spoken": {"type": ["string", "null"]},
        "on_screen_text": {"type": ["string", "null"], "description": "texto literal, con tildes"},
        "hook_type": {"type": "string", "enum": ["question", "bold_claim", "visual_surprise", "pain_point", "result_first", "curiosity_gap", "trend_audio", "other"]}
      }
    },
    "shots": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["index", "start_s", "end_s", "framing", "subject", "action", "camera_movement", "setting", "lighting", "transition_in", "product_visible"],
        "properties": {
          "index": {"type": "integer"},
          "start_s": {"type": "number"},
          "end_s": {"type": "number"},
          "framing": {"type": "string", "enum": ["extreme_close_up", "close_up", "medium", "medium_wide", "wide", "overhead_top_down", "pov", "screen_recording"]},
          "camera_angle": {"type": "string", "enum": ["eye_level", "high", "low", "top_down", "dutch"]},
          "subject": {"type": "string"},
          "action": {"type": "string"},
          "camera_movement": {"type": "string", "enum": ["static", "handheld", "pan", "tilt", "push_in", "pull_out", "dolly", "orbit", "tracking", "zoom", "whip", "gimbal"]},
          "setting": {"type": "string"},
          "lighting": {"type": "string"},
          "transition_in": {"type": "string", "enum": ["hard_cut", "jump_cut", "match_cut", "whip_pan", "zoom_transition", "fade", "dissolve", "swipe", "none"]},
          "speed": {"type": "string", "enum": ["normal", "slow_motion", "speed_ramp", "timelapse"]},
          "product_visible": {"type": "boolean"},
          "product_role": {"type": ["string", "null"], "enum": ["hero", "in_use", "background", "packshot", null]},
          "generation_hint": {"type": "string", "enum": ["seedance_clip", "seedream_still_plus_motion", "remotion_text_card", "real_footage_needed"]}
        }
      }
    },
    "on_screen_text": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["start_s", "end_s", "text", "role"],
        "properties": {
          "start_s": {"type": "number"}, "end_s": {"type": "number"},
          "text": {"type": "string", "description": "transcripción literal en español"},
          "role": {"type": "string", "enum": ["hook", "caption_subtitle", "list_item", "price", "cta", "label", "other"]},
          "position": {"type": "string", "enum": ["top", "center", "bottom", "other"]},
          "style": {"type": "string", "description": "ej. 'sans bold blanco con caja negra, animación pop'"}
        }
      }
    },
    "voice": {
      "type": "object",
      "required": ["kind", "segments"],
      "properties": {
        "kind": {"type": "string", "enum": ["voiceover", "on_camera_speech", "tts_voice", "none"]},
        "tone": {"type": "string"},
        "segments": {"type": "array", "items": {"type": "object", "required": ["start_s", "end_s", "text"], "properties": {"start_s": {"type": "number"}, "end_s": {"type": "number"}, "text": {"type": "string"}, "source": {"type": "string", "enum": ["whisper", "vlm"]}}}}
      }
    },
    "audio": {
      "type": "object",
      "required": ["music_present", "music_style"],
      "properties": {
        "music_present": {"type": "boolean"},
        "music_style": {"type": "string", "description": "género/energía, sin identificar la canción"},
        "bpm": {"type": ["number", "null"]},
        "trending_sound_suspected": {"type": "boolean"},
        "sfx": {"type": "array", "items": {"type": "object", "properties": {"t_s": {"type": "number"}, "kind": {"type": "string"}}}}
      }
    },
    "pacing": {
      "type": "object",
      "required": ["cuts_per_second", "avg_shot_s", "cuts_on_beat_ratio"],
      "properties": {
        "cuts_per_second": {"type": "number"},
        "avg_shot_s": {"type": "number"},
        "cuts_on_beat_ratio": {"type": ["number", "null"], "minimum": 0, "maximum": 1}
      }
    },
    "product_moments": {"type": "array", "items": {"type": "object", "properties": {"start_s": {"type": "number"}, "end_s": {"type": "number"}, "how": {"type": "string"}}}},
    "cta": {
      "type": "object",
      "required": ["present"],
      "properties": {"present": {"type": "boolean"}, "start_s": {"type": ["number", "null"]}, "text": {"type": ["string", "null"]}, "channel": {"type": ["string", "null"], "enum": ["comment", "dm", "link_in_bio", "visit_store", "follow", "save_share", "other", null]}}
    },
    "why_it_works": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    "replication_notes": {"type": "string", "description": "qué conservar (estructura/ritmo) y qué NO copiar (música, texto literal, personas)"}
  }
}
```

Nota: `pacing` y los `start_s`/`end_s` de `shots` los rellena el código a partir de PySceneDetect y librosa. El VLM los puede proponer, pero el código los corrige al corte detectado más cercano. Gemini elimina `maxLength` y similares sin aviso, así que la validación completa la hace Pydantic.

### 4.3 Cómo se convierte el blueprint en generación
- **Seedance 1.0, clips de 2 a 12 s, sin audio:** cada grupo de planos marcado `generation_hint = seedance_clip` produce un prompt. Seedance genera clips de al menos 2 s y los reels tienen planos más cortos, así que se agrupan de 2 a 4 planos por clip y el corte final lo hace Remotion. El prompt se arma con plantilla: `{framing} {camera_angle} de {producto de la marca} {action}, {camera_movement}, {setting}, {lighting}, {style}`.
- **Seedream:** sirve para los frames de producto (`packshot`, `hero`) y como `first_frame` o imagen de referencia de Seedance cuando el plano depende de cómo se ve el producto.
- **Remotion:** ya es nuestra pieza de composición. Monta los clips con la duración exacta de cada plano según el blueprint y las transiciones de `transition_in`. Pone los textos de `on_screen_text` reescritos para la marca (ver riesgos), con su posición, estilo y tiempos. Sincroniza los cortes al BPM de una música de librería y coloca el CTA final. Es una nueva "receta" de plantilla: `reel_replica` con puertos tipados para clips y textos.
- **Copy:** Claude reescribe el gancho, los textos y el guion para la marca a partir del blueprint, que es texto y por eso encaja bien con Claude.
- **Vídeo de referencia subido por el operador:** se analiza igual. Con Seedance 2.x (pendiente de activar) se envía el vídeo como `reference_video` **y además** el blueprint en texto, de modo que el modelo recibe la estructura explícita. Con modelos que no aceptan vídeo de referencia (Seedance 1.0, Seedream y Remotion) el blueprint es la única entrada y funciona igual. La referencia de Seedance 2.x tiene límites: hasta 3 clips de 15 s en 2.0 o 30 s en 2.5, y rechaza caras reales.

### 4.4 Persistencia y procedencia
Cada blueprint se guarda con `model`, `model_revision`, `pipeline_version`, `post_id` y la clave del MP4 en R2. Es la regla de procedencia del repo. El blueprint es un dato derivado y se puede regenerar, así que cambiar de VLM supone un relanzamiento, no una migración.

### 4.5 Cómo usar cada modelo
- **Gemini:**
  - Subida por Files API (los reels pesan menos de 20 MB, así que también vale inline).
  - Parámetros: `processing: {type: "static", fps: 2}`, `media_resolution` alta y `response_format` con el esquema.
  - Para el análisis masivo de "Descubrir", usar Batch o Flex (alrededor del 50 % más barato).
- **Seed:**
  - Llamar a `files.create(... preprocess_configs={"video": {"fps": 2}})` y luego a `/responses` con `input_video` y `file_id`.
  - Usar `json_schema` y probar con el razonamiento profundo encendido y apagado.

### 4.6 Evaluación: golden set mínimo
- **Muestra:**
  - 40 reels: 20 de TikTok y 20 de Instagram. 5 nichos: restaurante, cafetería, moda, belleza y tienda de barrio.
  - Mezcla de formatos: hablado a cámara, solo producto con música, receta y lista.
  - Duraciones de 7 a 90 s.
  - 10 reels con mucho texto en pantalla, con tildes, ñ y precios.
- **Anotación humana, de 1 a 2 h por reel la primera vez:**
  - Cortes al cuadro.
  - Texto en pantalla literal con sus tiempos.
  - Transcript.
  - Gancho, CTA, momentos de producto, tipo de plano y movimiento de cámara.
- **Métricas:**
  1. Validez del esquema: porcentaje de respuestas que pasan Pydantic a la primera.
  2. Cortes: F1 con tolerancia de ±0.25 s, para el VLM solo y para el pipeline con PySceneDetect.
  3. Texto en pantalla: CER y porcentaje de coincidencia exacta por línea. Los acentos cuentan.
  4. Transcript: WER del modelo con audio frente a Whisper.
  5. Precisión de etiquetas (`framing`, `camera_movement`, `transition_in`, `hook_type`): accuracy frente a la anotación.
  6. Alucinaciones: textos u objetos que no existen.
  7. **Replicabilidad:** se genera una réplica con Seedance y Remotion a partir del blueprint, y 3 personas puntúan de 1 a 5 si "tiene la misma estructura y el mismo ritmo". Es la métrica que de verdad importa.
  8. Coste real (tokens devueltos) y latencia p50 y p95.
- **Candidatos de la prueba:** Gemini 3.8 Flash, Gemini 3.5 Flash-Lite, Seed 2.0 Lite y Qwen3.8-Omni-Flash. Correr los 40 reels con los cuatro cuesta menos de USD 5.

---

## 5. Riesgos

- **Licencias de los modelos:**
  - Gemini, Seed y Qwen3.8-Omni son propietarios, de uso por API y sin pesos.
  - Las rutas de autoalojamiento recomendadas (Qwen3.6-35B-A3B, Qwen3-Omni-30B-A3B y Qwen3-VL) son **Apache-2.0**.
  - GLM-4.6V es MIT, pero las fuentes se contradicen.
  - Evitar repetir el caso de moondream (BSL).
- **Términos de las plataformas al analizar reels de terceros:**
  - Términos de TikTok (actualizados el 2025-12-01), sección 5: prohíben "use automated scripts to collect information from… the Services".
  - Términos de Instagram: prohíben "collecting information in an automated way without our express permission".
  - Analizar el vídeo no es en sí lo que prohíben, pero obtenerlo de forma automatizada sí está en zona gris. Es el mismo riesgo que ya asumen "Descubrir reels" y el scraper de Zyte, y no lo crea el VLM.
  - Hay que decidirlo con asesoría legal, no por ingeniería.
- **Derechos de autor:**
  - Replicar estructura, ritmo y tipos de plano es razonable. Copiar literalmente textos, guion, música o tomas no lo es.
  - El blueprint debe marcar qué no se copia (`replication_notes`). El copy se reescribe siempre y la música es siempre de librería con licencia (solo se guarda `music_style`, sin identificar la canción).
- **Privacidad de caras:**
  - El blueprint describe a las personas de forma genérica ("mujer joven a cámara") y nunca las identifica.
  - No guardar frames con caras más tiempo del necesario. Los Files de ModelArk caducan a los 7 días por defecto.
  - Seedance 2.x ya rechaza caras reales como referencia. Hay que diseñar la réplica sin personas reales o con el flujo de activos verificados.
  - Las leyes de datos de LatAm aplican. No las revisé en esta investigación.
- **Uso de datos por el proveedor:**
  - Gemini **solo en tier de pago**: en el gratuito usa los datos para mejorar sus productos y hay revisión humana.
  - No verifiqué los términos de datos de BytePlus ni de Alibaba para este caso. **Pendiente** antes de producción.
- **Dependencia de un proveedor:** se mitiga con el esquema propio como contrato, el VLM detrás de un `Provider` y los cortes, el ASR y el BPM deterministas. Cambiar de VLM solo cambia el prompt y el adaptador.
- **Coste por volumen (1,000 reels al mes, 60 % de 30 s y 40 % de 60 s):**
  - Gemini 3.8 Flash: 0.6 × 0.023 + 0.4 × 0.037 = **unos USD 29 al mes** (unos 57 desde enero de 2027; con Batch, alrededor de la mitad).
  - Seed 2.0 Lite: **unos USD 19 al mes**.
  - Gemini 3.5 Flash-Lite: **unos USD 16 al mes**.
  - Qwen3.8-Omni-Flash: **unos USD 6 al mes**.
  - Twelve Labs: unos USD 20 de vídeo más la salida más el plan Pro de 99.
  - **El coste del VLM es irrelevante frente al de generación:** un solo clip de Seedance 2.0 de 5 s cuesta entre 0.19 y 9.33 USD según la tabla oficial. El riesgo de coste está en regenerar, no en analizar.
- **Riesgo técnico:** un VLM a 1 o 2 fps no ve cortes de menos de 0.5 s ni textos que duran pocos frames. Por eso PySceneDetect y Whisper van en el pipeline, y el fps se sube a 3–4 solo en los reels con muchos cortes.

---

## 6. Fuentes (todas leídas el 2026-10-20)

**Google:**
- https://ai.google.dev/gemini-api/docs/pricing — precios ("Last updated 2026-10-19")
- https://ai.google.dev/gemini-api/docs/video-understanding — vídeo, modos static y agentic, tokens por segundo, fps ("Last updated 2026-10-13")
- https://ai.google.dev/gemini-api/docs/models — lista de modelos ("Last updated 2026-10-19")
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash — ficha de 3.8 Flash
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite — ficha de 3.5 Flash-Lite
- https://ai.google.dev/gemini-api/docs/structured-output — JSON Schema ("Last updated 2026-10-20")
- https://deepmind.google/models/model-cards/gemini-3-8-flash/ — model card, LVBench
- https://ai.google.dev/gemini-api/terms — términos adicionales (modificados el 2026-04-28)

**OpenAI:**
- https://developers.openai.com/api/docs/changelog — GPT-6 Sol y Luna, sin vídeo
- https://github.com/openai/openai-node/issues/1778 — petición de vídeo nativo cerrada como "not planned" (vista vía búsqueda)

**BytePlus ModelArk** (leído en el navegador porque la documentación requiere JavaScript):
- https://docs.byteplus.com/en/docs/ModelArk/video-understanding (actualizado el 2026-10-06)
- https://docs.byteplus.com/en/docs/ModelArk/audio-understanding (actualizado el 2026-10-06)
- https://docs.byteplus.com/en/docs/ModelArk/model-list
- https://docs.byteplus.com/en/docs/ModelArk/model-pricing (actualizado el 2026-10-19)

**ByteDance Seed:**
- https://seed.bytedance.com/en/blog/seed-2-0-official-launch (post del 2026-02-14)
- https://github.com/ByteDance-Seed/Seed2.0
- https://docs.apiyi.com/en/news/seed-2-0-lite-launch (terceros; VideoMME 87.7 no verificado)

**Alibaba y Qwen:**
- https://www.alibabacloud.com/help/en/model-studio/model-pricing (actualizado el 2026-10-19)
- https://www.alibabacloud.com/help/en/model-studio/vision (actualizado el 2026-10-11)
- https://www.alibabacloud.com/help/en/model-studio/qwen-omni (actualizado el 2026-10-16)
- https://technode.com/2026/09/18/alibabas-qwen-releases-qwen3-8-omni-flash-with-1m-token-context/
- https://huggingface.co/Qwen/Qwen3-VL-235B-A22B-Instruct
- https://huggingface.co/Qwen/Qwen3.6-35B-A3B
- https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct
- https://qwen.ai/blog?id=qwen3.6-35b-a3b
- https://arxiv.org/abs/2511.21631 — informe técnico de Qwen3-VL (las tablas no se pudieron extraer)
- https://the-decoder.com/qwen3-vl-can-scan-two-hour-videos-and-pinpoint-nearly-every-detail/ — OCRBench 875, OCR en 32 de 39 idiomas (prensa)
- https://anotherwrapper.com/tools/llm-pricing/evals/charadessta — Charades-STA (agregador; métrica no indicada)
- https://pricepertoken.com/pricing-page/model/qwen-qwen3-vl-235b-a22b-instruct — precios de terceros

**Twelve Labs:**
- https://www.twelvelabs.io/pricing
- https://www.twelvelabs.io/overage
- https://www.twelvelabs.io/pegasus
- https://www.twelvelabs.io/blog/what%E2%80%99s-new-pegasus-1.6
- https://docs.twelvelabs.io/docs/concepts/models/pegasus
- https://beta.docs.twelvelabs.io/docs/concepts/models/pegasus
- https://www.usagepricing.com/tools/pricing-calculator/twelve-labs (terceros; salida a $7.5/M no verificada)

**AWS:**
- https://docs.aws.amazon.com/nova/latest/nova2-userguide/using-multimodal-models.html
- https://www.techplained.com/amazon-nova-2 (precio de terceros)

**OpenRouter:**
- https://openrouter.ai/docs/features/multimodal/videos (vía búsqueda)

**Otros (terceros):**
- https://openrouter.ai/z-ai/glm-4.6v y https://glm-v.com/ — GLM-4.6V
- https://docs.api.nvidia.com/nim/reference/google-gemma-4-31b-it — Gemma 4

**Términos de las plataformas:**
- https://www.tiktok.com/legal/page/row/terms-of-service/en (actualizado el 2025-12-01)
- https://www.facebook.com/help/instagram/termsofuse (sin fecha visible)

**Contexto interno** (no se volvió a verificar, salvo lo citado de la documentación oficial): nota de memoria del proyecto sobre ModelArk y Seedance 2.x (referencias de vídeo y rechazo de caras reales).
