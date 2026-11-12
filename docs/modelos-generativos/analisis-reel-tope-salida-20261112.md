# Tope de salida del análisis de reels según el tamaño del pedido — 12 de noviembre de 2026

`[ESTIMADO SIN GASTAR · 2026-11-12]` Ticket: m-24993025 (épica «Video por partes»). Autor:
backend-engineer. Rama local `fix/m-24993025-reel-analysis-output-cut`, **sin commit ni PR**.
**Ninguna llamada pagada a Anthropic:** las cifras salen de los precios de `PRICES` del repo y
de las filas ya medidas de VE-05 (versión 8).

## 1. Qué pasó

En la prueba de punta a punta del 2026-11-10, dos reels de TikTok de unos 60 s
(7700577949174533398, 59,6 s, análisis `559554d2…`; 7701854220441439496, análisis `88bc1f7f…`)
fallaron en el paso de descripción (`qualify_api/referentes/reel_analysis_ai.py`, Haiku
`claude-haiku-5-5`, esfuerzo `low`). Cada intento terminó con `stop_reason = max_tokens` en el
tope fijo de 9.000. El corte se marcaba como reintentable («a cut answer may fit on a second
try»), así que cada reintento volvió a pagar ≈ USD 0,0068 (≈ 26.761 tokens de entrada y 9.000
de salida) para el mismo corte, y la fila terminó en `failed / model_failed`.

Configuración del pedido: `ModelConfig("claude-haiku-5-5", "low")`, sin campo `thinking`. En
Haiku 5.5 el pensamiento adaptativo viene encendido por defecto y sus tokens cuentan dentro de
`max_tokens`. Las filas no separan el pensamiento de la respuesta (la API solo da
`output_tokens`), así que **no se sabe qué parte de los 9.000 fue pensamiento**. Los rastros de
Langfuse de esos dos análisis sí lo muestran y leerlos no cuesta nada (§6).

## 2. Calibración con las filas medidas

No había base local levantada (Docker apagado), así que se usaron las 18 fichas `ok` de la
versión 8 guardadas en `packages/api/evals/reel_shots_ai/results/ve05-20261105-v8.json`
(misma versión de prompt que producción, `reel-sheet-prompt-9`, y el mismo tope de 9.000).

| Variable frente a tokens de salida | Lectura |
|---|---|
| Fotogramas enviados (5 a 27) | Recta `salida ≈ 309 + 265 × fotogramas`, residuo de −1.541 a +1.410; como mucho 367 por fotograma |
| Grupos (1 a 12) | Sigue a los fotogramas: con 12 grupos se envían 27 fotogramas (2 por grupo + 3 anclas) |
| Duración del reel | Poco útil: un reel de 37 s usó 2.472 y uno de 15 s, 4.644 |
| Máximo medido | 7.829 tokens con 27 fotogramas (`DfU1xGhEhn9`, 55,7 s) |

Los dos reels cortados tenían, por su entrada (≈ 26.761 tokens), 27 fotogramas: con la recta
esperaban ≈ 7.475 y pasaron de 9.000, unos 1.500 por encima del residuo más alto medido. Con 9.000
fijo el margen para 27 fotogramas era de apenas 1,15×.

## 3. Diseño elegido

El tope depende del tamaño real del pedido, contado en fotogramas enviados
(`output_token_cap`):

```
max_tokens = mín(16.000, máx(9.000, 2.000 + 450 × fotogramas))
```

| Fotogramas | 5 | 11 | 15 | 17 | 23 | 27 | 32 |
|---|---|---|---|---|---|---|---|
| Tope | 9.000 | 9.000 | 9.000 | 9.650 | 12.350 | **14.150** | 16.000 |

- **Piso 9.000:** ningún reel recibe menos que antes.
- **Techo 16.000:** lo más que la SDK acepta sin streaming (`MAX_NON_STREAMING_TOKENS`).
- La recta queda **≥ 1,5×** por encima de cada ficha medida, y para 27 fotogramas da ≈ 1,9× lo
  que predice la recta.
- Cada fila guarda el tope que usó en `sampling_params.max_output_tokens` (procedencia).

**Por qué no partir la descripción por tramos:** serían dos llamadas o más por reel, cada una
con su prefijo, y habría que unir grupos, ganchos y cierres entre tramos. Con 27 fotogramas como
máximo real, el tope de 14.150 deja casi el doble de lo medido. Si aun así hay cortes, la causa
probable es el pensamiento (§6), no el largo de la ficha.

**Corte sin reintento:** si la respuesta igual se corta, el paso falla en el acto con
`error_code = model_output_cut` y `retryable = False`. Lo gastado queda en la fila (`spent`).
Reintentar mandaría el mismo pedido, con el mismo tope y el mismo modelo, y pagaría otra vez el
mismo corte. La migración **0152** suma `model_output_cut` al CHECK `ck_pra_error_code`. Al
bajarla, esas filas vuelven a `model_failed`.

## 4. Costo por reel (precios de `PRICES`: entrada 0,10, salida 0,50, lectura de caché 0,01 y
escritura ×1,25, en USD por millón)

| Caso | Antes (9.000 fijo; corte reintentado) | Después (tope por tamaño; corte sin reintento) |
|---|---|---|
| Reel normal (mediana v8, ~15 fotogramas) | USD 0,0043 por ficha terminada (medido) | Igual: USD 0,0043. Se cobra lo usado y el tope es el mismo (9.000) |
| Reel de 60 s que termina (27 fotogramas, ≤ 7.829 de salida) | USD 0,0060–0,0073 (medido) | Igual: USD 0,0060–0,0073 |
| Reel de 60 s que necesitaba más de 9.000 (los del 2026-11-10) | 2 llamadas cortadas × ≈ 0,0068 = **≈ USD 0,0136 sin ficha** (`MAX_MODEL_CALLS = 2`) | Si termina con 10.000–12.000: ≈ USD 0,0073–0,0083 **con ficha**. Si se corta en 14.150: ≈ USD 0,0094 una sola vez, `model_output_cut` |
| Peor pedido acotado (32 imágenes en el techo, transcripción recortada) | USD 0,011545 (cota 0,0116) | USD 0,015045 (cota **0,0151**, `MAX_REQUEST_USD`); con los 27 fotogramas que dan 12 grupos: USD 0,013286 |
| Peor fila | Corte: 2 × 0,011545 = USD 0,0231 | Corte: 1 × 0,015045 = USD 0,0150. Respuesta sin herramienta o de forma equivocada (se sigue reintentando): 2 × 0,015045 = USD 0,0301 |

Entrada del reel de 60 s según el fallo real: 0,0068 − 9.000 × 0,50 / 10⁶ ≈ USD 0,0023. La cota
la fija `test_the_worst_request_is_pinned_with_prices`.

## 5. ¿Cambia la versión del análisis?

**No.** Ni `ANALYSIS_VERSION` (sigue en 8) ni `REEL_ANALYSIS_PROMPT_VERSION` (sigue en
`reel-sheet-prompt-9`). `ANALYSIS_VERSION` representa cuatro cosas: el prompt, el esquema, el
detector y el muestreo, y ninguna cambia. El modelo no lee `max_tokens`. La huella del prompt
(`prompt_fingerprint`) sigue igual porque guarda el piso de 9.000 con el que salió el prompt 9.
Una ficha que cabía en 9.000 sale del mismo pedido. Subir la versión dejaría vieja cada ficha `ok`
y obligaría a pagar todos los reels otra vez sin ganar nada. Las instrucciones del prompt no se
tocaron: siguen siendo generales, sin categorías de negocio.

## 6. Qué falta y qué no se midió

- **Leer los rastros de Langfuse** de los análisis `559554d2…` y `88bc1f7f…` (gratis): cuánto
  de los 9.000 fue pensamiento. Si el pensamiento se desbocó, la solución sería
  `thinking: {"type": "disabled"}` o un esfuerzo distinto. Eso cambia lo que hace el modelo y pide
  versión nueva y medición: no se hizo aquí.
- **Medir los dos reels de verdad** (opcional): una llamada por reel con 27 fotogramas cuesta
  como mucho USD 0,0133 y lo esperable es ≈ USD 0,008, así que los dos suman **≈ USD 0,016–0,027**.
  La descarga de ScrapeCreators con caché cuesta 0 créditos. Hace falta el visto bueno de Deivid.
- Las dos filas que fallaron siguen en `failed / model_failed` con la versión 8: nada las vuelve
  a encolar solo. Volver a mirarlas pide reiniciar esas filas a mano (operación de producción) o
  esperar a una versión nueva.

## 7. Reproducir

```bash
# cifras de §2 (sin red): fotogramas, grupos y tokens de salida de cada ficha v8
python -c "import json; d=json.load(open('packages/api/evals/reel_shots_ai/results/ve05-20261105-v8.json', encoding='utf-8')); [print(r['analysis']['sampling_params']['frames_sent'], r['analysis']['output_tokens']) for r in d['reels'] if (r.get('analysis') or {}).get('status') == 'ok']"
uv run --no-sync pytest packages/api/tests/test_reel_analysis_ai.py -m "not integration" -q
```
