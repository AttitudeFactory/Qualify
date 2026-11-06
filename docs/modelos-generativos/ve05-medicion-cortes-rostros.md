# VE-05 — Medición de cortes y rostros del análisis de reels en 20 reels reales (m-24921050)

`[MEDIDO · 2026-11-06 · PASA EL UMBRAL]`

Mide el detector de planos de VE-02 (`qualify_creative.video.shots.detect_shots`, PyAV) y la
decisión de personas y rostros por plano de la ficha de Haiku (VE-04c, `people_presence` /
`visible_faces`) frente a una anotación **humana**. El umbral lo fija el diseño: si el F1 de
cortes queda por debajo de **0,85 a ±0,25 s**, se reabre el detector
(`docs/diseno-video-por-planos.md` §4.1, ADR 44).

**Resumen.** F1 de cortes **0,927** (0,932 sin los 2 momentos que Deivid marcó «no estoy
seguro»): pasa el umbral y no hace falta un detector alternativo. Personas **94,9 %** y rostros
**87,7 %** de acierto sobre 195 planos reales, **sin ninguna persona ni cara perdida**: los
errores son todos «de más» o «no se sabe», que es el lado seguro para «Igual al original».
Costo medido de la versión 8: **USD 0,0043** por ficha terminada (USD 0,0041 por reel
intentado). La descarga de TikTok desde el servidor de producción funciona (§9).

## 1. Golden set y corridas

20 reels públicos de ≤ 60 s, de 9 cuentas y 7 categorías; 15 de Instagram y 5 de TikTok. Se
eligieron por categoría y por la portada (persona sí/no), **no** por lo que dijo el modelo. La
hoja (§2) tiene el enlace público de cada uno y no guarda datos personales.

| Categoría | Instagram | TikTok |
|---|---|---|
| Comida | @smashack.ve ×2 | @2foodies.ve |
| Educación / creador | @mouredev ×2 | @midudev |
| Inmobiliaria | @ryanserhant ×2 | — |
| Belleza | @hudabeauty ×3 | — |
| Ropa | @zara ×3 | @zara |
| Viajes | @beautifuldestinations ×3 | @beautifuldestinations |
| Fitness / ropa deportiva | — | @blogilates |

Limitación: la mitad son grandes marcas o creadores en inglés; negocios pequeños de CO/VE hay 2.
Para cortes y rostros pesa poco (el detector no lee idioma), pero una marca global edita más
rápido que un comercio de barrio.

El análisis se corrió tres veces por el camino de producción
(`reel_analysis_worker.analyze_run_ideas`, base de desarrollo, Haiku `claude-haiku-5-5`). El
detector es el mismo en las tres (`luma-diff-hist-1`); cambian la ficha y la regla de personas.
La historia de versiones y sus cifras está en la bitácora
([REELSHEET-001](pruebas.md#reelsheet-001), adendas 1 y 2) y aquí no se repite.

| Archivo (`packages/api/evals/reel_shots_ai/results/`) | Versión | Uso en este informe |
|---|---|---|
| `ve05-20261105.json` | 6 (prompt 7) | primera corrida, 2026-11-05; 11 de 18 fichas cortadas por `max_tokens` |
| `ve05-20261105-v7.json` | 7 (grupos de planos) | **cortes del reel 7703559161040211233**, que falta en la 8 |
| `ve05-20261105-v8.json` | 8 (por fotograma), como quedó guardada | referencia |
| `ve05-20261105-v8-replay.json` | 8 con la regla final | **cifras de este informe** |

**Por qué existe el `replay`.** Las filas de la versión 8 se escribieron el 2026-11-06 hacia las
04:07 UTC, antes de que llegara la regla de cobertura final (`presence-frames-gap0.5-3`, commit
95277026). Las respuestas de Haiku por fotograma sí quedaron guardadas
(`reel_sheet.presence.frames`), así que `replay_presence.py` les vuelve a aplicar
`resolve_presence` del código de `main` y escribe el `replay`. **No llama al modelo** y solo lee
la base de desarrollo. Los cortes no cambian. Límite: el resumen por grupo que también devuelve
Haiku no se guarda, así que se deduce de los fotogramas del grupo. Con las etiquetas tal como se
guardaron, las cifras serían personas 96,9 % y rostros 89,7 %, pero con 1 persona y 2 caras
perdidas: justo lo que la regla de cobertura corrigió.

## 2. Cómo se anotó

**Cortes.** Deivid vio cada reel con un reloj de segundos sobreimpreso y pausó en cada cambio de
toma. Sus 182 marcas llegan **tarde, unos 0,27 s** (la mediana de la diferencia con el corte del
detector): es el tiempo de reacción al pausar. Se comprobó cuadro por cuadro en 3 reels: el
salto de píxeles cae justo en el corte del detector, no en la marca. Por eso:

| Verdad usada | F1 a ±0,25 s |
|---|---|
| Marcas tal cual | 0,34 |
| Marcas corridas −0,27 s | 0,82 |
| Verdad adjudicada (la de la hoja) | **0,927** |

**Adjudicación.** Los 61 momentos en que humano y detector no coincidían (34 solo del modelo, 19
solo humanos, 8 marcados por los dos con más de 0,25 s de diferencia) se cortaron en clips, y
Deivid los volvió a juzgar **a ciegas**, sin saber de quién era cada uno: 56 «sí», 1 «no» y 4
«no sé». Los «sí» se miraron cuadro a cuadro: **25 no tenían un cambio brusco de imagen** (salto
medio de píxeles menor que 25: paneos, zooms, efectos, destellos) y se quitaron, porque un
movimiento de cámara dentro de la misma toma no es un corte (regla 1 de la hoja). Las marcas
humanas que coincidían con el detector se guardan con el tiempo del cuadro del detector. Quedan
**187 cortes reales y 207 planos reales** (`ve05/real_cuts.json`, fuera del repositorio).

Sesgo a tener en cuenta: la verdad final se construyó mirando los cortes del detector (para
corregir la demora y para elegir qué revisar). Un corte que no vieron ni Deivid ni el detector
no está en la hoja. Lo compensa que la revisión fue a ciegas y que los 25 «sí» descartados se
decidieron por el salto de píxeles, no por el modelo.

**Personas y rostros.** Sobre los 207 planos reales se armó una hoja de contactos por reel (un
cuadro del medio de cada plano) y Deivid anotó, plano por plano, si aparece una persona y si se
ve su rostro. Regla: cuenta si aparece **en cualquier momento del plano**, aunque sea en parte
(manos, un hombro, de perfil), y un rostro implica persona. Hubo **dos rondas de corrección** con
Claude sobre los planos donde la anotación contradecía a las dos versiones del modelo, viendo el
plano completo. El resultado (`ve05/tomas/personas_rostros_revisado.csv`, fuera del repositorio)
se volcó a la hoja.

**La hoja:** [`ve05-anotacion-cortes-rostros.csv`](ve05-anotacion-cortes-rostros.csv), una fila
por reel con los cortes reales y un `si`/`no` por plano real, en el formato que lee
`qualify_api/evals/reel_shots.py`.

## 3. Cortes

`just eval-cortes-rostros` (tolerancia ±0,25 s, emparejamiento uno a uno, F1 micro). Solo cuenta
el tramo que cubrió el análisis (`covered_to_s`), con el mismo límite para los cortes reales y los
del detector.

| Métrica | Valor |
|---|---|
| Reels | 20 (7703559161040211233 con los cortes de la versión 7, mismo detector) |
| Verdaderos positivos / de más / faltantes | 179 / 20 / 8 |
| Precisión | 0,899 |
| Exhaustividad | 0,957 |
| **F1** | **0,927** |
| F1 sin los 2 momentos «no estoy seguro» del modelo | 0,932 (179 / 18 / 8) |
| ¿Se reabre el detector (F1 menor que 0,85)? | **No** |

**Las dos cifras.** La hoja no tiene forma de decir «no sé», así que los 4 momentos «no sé» de
la adjudicación quedaron como «no es corte». Dos eran cortes del detector en `De9dUoCAGth`
(23,80 s y 24,73 s), y el puntaje los cuenta como cortes de más. Sin ellos, el F1 es 0,932. Las
dos cifras pasan el umbral con margen; se informa la más conservadora.

| Reel | Red | VP | De más | Faltan | F1 |
|---|---|---|---|---|---|
| DfFxwl1T9_g | IG | 5 | 0 | 0 | 1,000 |
| Dem0JDcTNkR | IG | 0 | 0 | 0 | — (un plano) |
| DeXCECcCIsU | IG | 1 | 3 | 0 | 0,400 |
| De7LIqOCfFf | IG | 0 | 0 | 0 | — (un plano) |
| DfU1xGhEhn9 | IG | 15 | 1 | 0 | 0,968 |
| DfAoszqCaG8 | IG | 3 | 0 | 0 | 1,000 |
| DfE_7hlARpS | IG | 11 | 0 | 0 | 1,000 |
| De64IIPjs6r | IG | 12 | 3 | 2 | 0,828 |
| De9dUoCAGth | IG | 6 | 6 | 0 | 0,667 |
| Dev_ZPatWha | IG | 0 | 0 | 0 | — (un plano) |
| DeY-zYDtQvt | IG | 2 | 0 | 0 | 1,000 |
| DeeU4qItcFx | IG | 9 | 0 | 0 | 1,000 |
| DewquIkOYcp | IG | 12 | 0 | 0 | 1,000 |
| DezCpl9RsGA | IG | 10 | 0 | 0 | 1,000 |
| De9ffXrO_15 | IG | 9 | 0 | 0 | 1,000 |
| 7704417191021645078 | TT | 8 | 4 | 1 | 0,762 |
| 7702633972072828190 | TT | 44 | 2 | 5 | 0,926 |
| 7703998863132265751 | TT | 7 | 1 | 0 | 0,933 |
| 7703559161040211233 | TT | 10 | 0 | 0 | 1,000 |
| 7703284420895116552 | TT | 15 | 0 | 0 | 1,000 |

Los errores se concentran en tres reels con movimiento o efectos: `De9dUoCAGth` (pantalla
dividida), `DeXCECcCIsU` y `7704417191021645078`. El detector corta de más bastante más de lo
que se le pasa (20 contra 8). Para el editor por planos es el error barato: un plano partido en
dos se puede volver a unir, mientras que uno no detectado mezcla dos tomas.

## 4. Personas y rostros

Por plano real, en su punto medio: vale lo que diga el plano del modelo que cubre ese instante.

| | Aciertos | Se le pasan (dice «no» y sí hay) | De más (dice «sí» y no hay) | «No se sabe» |
|---|---|---|---|---|
| **Personas** | **185 / 195 = 94,9 %** | **0** | 10 | 0 |
| **Rostros** | **171 / 195 = 87,7 %** | **0** | 15 | 9 (91,9 % sobre lo respondido) |

| Reel | Red | Personas ok / planos | Rostros ok / planos |
|---|---|---|---|
| DfFxwl1T9_g | IG | 6/6 | 6/6 |
| Dem0JDcTNkR | IG | 1/1 | 1/1 |
| DeXCECcCIsU | IG | 2/2 | 2/2 |
| De7LIqOCfFf | IG | 1/1 | 1/1 |
| DfU1xGhEhn9 | IG | 16/16 | 15/16 |
| DfAoszqCaG8 | IG | 4/4 | 4/4 |
| DfE_7hlARpS | IG | 12/12 | 12/12 |
| De64IIPjs6r | IG | 15/15 | 15/15 |
| De9dUoCAGth | IG | 7/7 | 7/7 |
| Dev_ZPatWha | IG | — (sin ficha en la 8) | — |
| DeY-zYDtQvt | IG | 3/3 | 3/3 |
| DeeU4qItcFx | IG | 9/10 | 7/10 |
| DewquIkOYcp | IG | 10/13 | 13/13 |
| DezCpl9RsGA | IG | 11/11 | 11/11 |
| De9ffXrO_15 | IG | 10/10 | 9/10 |
| 7704417191021645078 | TT | 10/10 | 10/10 |
| 7702633972072828190 | TT | 50/50 | 38/50 |
| 7703998863132265751 | TT | 5/8 | 6/8 |
| 7703559161040211233 | TT | — (enlace vencido en la 8) | — |
| 7703284420895116552 | TT | 13/16 | 11/16 |

Todos los fallos de la tabla son «de más» o «no se sabe». Los rostros fallan sobre todo en
@blogilates (12 de 50 planos), `7703284420895116552` (5 de 16) y `DeeU4qItcFx` (3 de 10).

**Reels fuera de este cálculo (12 de los 207 planos):** `7703559161040211233` (11 planos) quedó
`source_unavailable` en la versión 8 porque el enlace firmado del video ya había vencido; no es
una falla del análisis. `Dev_ZPatWha` (1 plano) quedó sin ficha en la versión 8 (en cola tras
fallar), así que no tiene etiquetas. Los dos sí cuentan para los cortes.

Lo que importa para «Igual al original» (ADR 44) es no perder a nadie: un plano con persona o
cara no puede pasar sin cambios. Con la regla final **no se pierde ninguna persona ni ninguna
cara** en estos 195 planos. Los 10 + 15 «de más» bloquean planos que se podrían usar: cuestan
opciones, no riesgo.

**Prueba del caso riesgoso con 60 reels nuevos (2026-11-06).** Para no fiarse solo de 195 planos,
se corrió la versión 8 sobre 60 reels nuevos de las mismas cuentas (56 `ok`, 961 planos, USD
0,29). Deivid revisó cuadro por cuadro los 11 planos en que la regla nueva dice «no se ve» y la
anterior decía «se ve». **Un solo error en 961 planos:** unas manos en los últimos cuadros de un
plano de 0,38 s cuyos dos fotogramas estaban oscuros. **Ningún rostro perdido.** Deivid aceptó
ese riesgo el 2026-11-06 (detalle en [REELSHEET-001](pruebas.md#reelsheet-001), adenda 2).

## 5. Riqueza de la descripción

Juntar los planos cortos en grupos (versión 7, para que la ficha no se corte) tiene un precio
que el F1 no mide. En 160 planos comparables, los sujetos distintos descritos por plano bajaron
de **151 (versión 6) a 106 (versión 7) y 100 (versión 8)**, porque los planos de un grupo
comparten descripción. También se perdieron, en varios planos, las marcas de énfasis del texto en
pantalla (`[destacado: …]`). Personas y rostros ya no sufren por esto (se deciden por
fotograma), pero el resto de la ficha es más grueso en reels de cortes rápidos. Queda como dato
para VE-04c; no bloquea VE-05.

## 6. Costo

| Corrida | Fichas | USD | Por reel |
|---|---|---|---|
| Versión 8 en vivo (2026-11-06) | 18 `ok` de 19 intentados (el vigésimo no se pudo bajar) | 0,0783 | **USD 0,0043 por ficha terminada** (0,0770 / 18) · USD 0,0041 por reel intentado (0,0783 / 19, incluye el intento sin ficha de `Dev_ZPatWha`) |
| Versión 6 con el techo de producción de entonces (2026-11-05) | 6 `ok` al primer intento de 18 | — | mediana USD 0,0096 por ficha terminada, sumando el intento cortado |

ScrapeCreators: 22 créditos el 2026-11-05 (listas y transcripciones) y 0 en las corridas 7 y 8.
El puntaje (`just eval-cortes-rostros`) y el `replay` son gratis y sin red.

## 7. Veredicto frente al ADR 44

| Criterio | Resultado |
|---|---|
| F1 de cortes de al menos 0,85 a ±0,25 s | **Cumple:** 0,927 (0,932 sin los «no sé») |
| Propuesta de detector alternativo si no cumple | **No aplica:** se queda `luma-diff-hist-1` |
| Personas y rostros por plano | 94,9 % y 87,7 %, 0 perdidos en 195 planos; 1 error en 961 planos nuevos, aceptado |
| Costo por reel | USD 0,0043 por ficha terminada con la versión 8 (USD 0,0041 por reel intentado) |
| Descarga de TikTok desde el servidor | Funciona (§9) |

## 8. Reproducir

```bash
just eval-cortes-rostros                    # cifras de este informe: replay v8 + cortes v7 del reel que falta
just eval-cortes-rostros --tolerance 0.5    # sensibilidad
just eval-cortes-rostros --results packages/api/evals/reel_shots_ai/results/ve05-20261105-v8.json
```

Código: `packages/api/src/qualify_api/evals/reel_shots.py` (puntaje),
`packages/api/evals/reel_shots_ai/` (`score.py`, `replay_presence.py`, README) y el test sin red
`packages/api/tests/test_eval_reel_shots.py`.

## 9. Descarga de TikTok desde el servidor

`[HECHO · 2026-11-06]` Lo probó la sesión remota `qualify-prod` desde el servidor de producción
(Hetzner): un pedido de solo lectura `curl -r 0-1048575 -A "Mozilla/5.0"` a enlaces públicos de
video leídos de ScrapeCreators el 2026-11-05, sin guardar la respuesta.

| Reel | Respuesta | Bytes | Tipo |
|---|---|---|---|
| Instagram `DfFxwl1T9_g` | 206 | 1.048.576 | `video/mp4` |
| TikTok `7703284420895116552` | 206 | 1.048.576 | `video/mp4` |
| TikTok `7701854220441439496` | 206 | 1.048.576 | `video/mp4` |
| TikTok `7700733939689770258` | 206 | 1.048.576 | `video/mp4` |

**Para VE-04a: funciona.** El CDN de TikTok (`v16m.tiktokcdn-eu.com`) no devolvió 403 ni 410 a la
IP del servidor, con un User-Agent genérico. **Límites:** los tres enlaces de TikTok se firmaron
en la misma sesión del proveedor (mismo parámetro `l=20261105182308…`) y fuera del servidor, así
que no prueba que enlaces firmados por otra vía se comporten igual. Además fue un pedido de 1 MB
por rango, no una descarga completa. Los enlaces firmados no se guardan en el repositorio.
