# Bitácora de pruebas de modelos generativos

Aquí queda toda prueba real contra un modelo o un proveedor, también las que fallan (regla de `qualify-measure`). Las entradas van de la más reciente a la más antigua. Las claves no se escriben nunca, solo el nombre de la variable de entorno.

> La entrada PR-001 (smoke test de BytePlus, 2026-10-07) todavía está sin commitear en otra rama. Cuando llegue a `main`, se agrega debajo de esta.

<a id="byteplus-llave-y-horario"></a>

## Antes de una prueba con BytePlus: llave propia y horario (m-24852161)

**Las evaluaciones con video comparten la cuota de los clientes.** Seedance permite 10 tareas a la vez **por modelo y por cuenta principal, sumando todas las subcuentas** ([`escalar-generacion-concurrencia.md`](../escalar-generacion-concurrencia.md) §1.1). Una llave o una subcuenta aparte **no da más cupo**: una evaluación de 10 videos ocupa las 10 de los clientes, y sus vistas previas quedan en la cola de BytePlus. Solo una segunda cuenta principal separaría la cuota, y eso es la Fase 3 (último recurso). OmniHuman es peor: 1 tarea a la vez. Seedream (imagen, 500 por minuto) no tiene este problema.

| Regla | Detalle |
|---|---|
| Llave propia | `QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY` en el `.env` local, distinta de la de la app (`QUALIFY_BYTEPLUS_ARK_API_KEY`) y de la de producción. Sirve para separar el gasto, ver las tareas de evaluación bajo su propia llave (`arkcli`, solo lectura) y revocarla sin tocar producción. `just eval-escenas` y `plantillas_ai` la usan primero; sin ella usan la de la app y lo avisan. Nunca va a `.env.prod` |
| Comprobar que no es la de producción | La huella (8 primeros caracteres del sha256, la misma de `just env-push --dry-run`) de la llave de producción va en `QUALIFY_BYTEPLUS_ARK_PROD_KEY_FINGERPRINT`. Con ella la evaluación se niega a gastar con la llave de producción, y `just byteplus-llaves` compara las huellas sin imprimir valores (sale con 1 si dos coinciden) |
| Horario de las evaluaciones con video | **De 23:00 a 05:00, hora de Bogotá** (00:00–06:00 en Caracas, 01:00–07:00 en Montevideo): fuera del día de los comercios en los tres mercados. Correrla de día pide el visto bueno del fundador. `qualify_api.evals.byteplus_eval_guard.off_hours_refusal` lo comprueba |
| Tareas a la vez | **Como mucho 3** de las 10 (`cap_video_concurrency`), para que un cliente nocturno tenga 7 |
| Cuando exista la cola propia (ADR 41, m-24852163) | Las evaluaciones encolan en el carril `scheduled` en lugar de mirar el reloj |

Hoy ninguna evaluación del repositorio crea videos (las de BytePlus, `scenes_ai` y `plantillas_ai`, son de Seedream). La primera que lo haga llama a `off_hours_refusal` y a `cap_video_concurrency` antes de su primera tarea.

---

<a id="reelsheet-001"></a>

## REELSHEET-001 — Ficha por planos de Haiku sin salida cortada: grupos de planos cortos, valores breves y techo de 9.000 (m-24955652) — 2026-11-05

**Por qué.** En la medición VE-05 (m-24921050, mismo día) se usó el techo de producción `MAX_OUTPUT_TOKENS = 5800`: **11 de 18 fichas reales** llegaron a `max_tokens`. Esos intentos se cobraron y luego se reintentaron. Con 12.000 terminaron 10 de 11. El reel de @blogilates (47 planos en 51,7 s) no entró ni así. `Dev_ZPatWha` (@zara) devolvió `reel` como texto 3 veces. La salida crece ≈ 500–650 tokens por plano. Decisión de Deivid: ficha más corta, juntar los planos muy cortos y techo cercano a 9.000.

| Campo | Valor |
|---|---|
| Quién | agente backend-engineer (Claude Code), por encargo de Deivid; gasto aprobado ≤ USD 0,12 en Haiku y 0 créditos de ScrapeCreators |
| Modelo | `claude-haiku-5-5` con esfuerzo `low`, una llamada por reel y la herramienta `describir_reel` (no estricta) |
| Versiones | `ANALYSIS_VERSION = 7` · prompt `reel-sheet-prompt-8` · esquema `reel-sheet-schema-4` · detector `luma-diff-hist-1` · muestreo `shots-2x-anchors-1` sobre grupos `groups-min1s-max12-1` |
| Cambios | (1) **Grupos:** los planos consecutivos de menos de 1 s se juntan, con un máximo de 12 grupos (`reel_analysis_groups.py`). Haiku describe los grupos y la fila guarda los planos detectados, cada uno con la descripción de su grupo. (2) **Valores breves:** ≤ 8 palabras por plano, ≤ 12 por reel y una o dos etiquetas de evidencia. `habla` queda vacía si no hay corrección. El texto en pantalla sigue completo. (3) **Techo de 9.000.** (4) Si `reel` llega como texto con un objeto JSON, se repara; si no, falla con un aviso claro |
| Peor caso con `PRICES` | **USD 0,011462** por pedido: 12 grupos, 32 imágenes de 1.600 tokens cada una, transcripción recortada y 9.000 tokens de salida. Con 12 grupos el muestreo manda como mucho 27 imágenes, y entonces el peor caso es **USD 0,010628**. `MAX_REQUEST_USD = 0,0115` (test `test_the_worst_request_is_pinned_with_prices`). El mismo pedido costaba USD 0,009862 con 5.800 tokens de salida |
| Camino | Se llamó a `ReelDescriber` (el paso `describe` de producción) directamente sobre la **fuente ya guardada en R2** de cada fila v6 de VE-05 (`public/reel-analyses/…/source.mp4`), con la transcripción de esa fila. Los fotogramas se guardaron en una carpeta temporal y no se escribió nada en la base. No pasó por el worker, porque las URL firmadas ya vencieron. El arnés está fuera del repositorio: `%TEMP%/m24955652/live.py` |
| Material | Los 18 reels que VE-05 describió con la configuración de producción (los 20 menos los dos de la mañana), sin elegir |

**Resultado: 18 de 18 `ok` al primer intento** (antes: 6 de 18). Ningún pedido llegó a `max_tokens`, y el máximo fue 6.897 tokens de salida (77 % del techo). Total **USD 0,071856**; media **USD 0,003992** por reel, mediana USD 0,004272, rango USD 0,0011–0,0067. Antes, la mediana por ficha terminada era USD 0,0096, sumando el intento cortado. `Dev_ZPatWha` terminó bien, con `reel` como objeto: esta vez no hubo nada que reparar. @blogilates (47 planos, 12 grupos) terminó con USD 0,0060.

| Reel | Red | Planos detectados | Grupos | Imágenes | Estado | Tokens ent. / sal. | USD | s |
|---|---|---|---|---|---|---|---|---|
| DfE_7hlARpS | IG | 12 | 6 | 15 | ok | 23.018 / 3.814 | 0,004316 | 48,6 |
| Dev_ZPatWha | IG | 1 | 1 | 5 | ok | 8.886 / 1.204 | 0,001104 | 16,5 |
| Dem0JDcTNkR | IG | 1 | 1 | 5 | ok | 10.721 / 1.342 | 0,001356 | 52,7 |
| De7LIqOCfFf | IG | 1 | 1 | 5 | ok | 10.699 / 1.398 | 0,001382 | 18,0 |
| DfU1xGhEhn9 | IG | 17 | 12 | 27 | ok | 38.067 / 6.486 | 0,006663 | 84,2 |
| DfAoszqCaG8 | IG | 4 | 4 | 11 | ok | 18.225 / 3.422 | 0,003147 | 62,0 |
| De64IIPjs6r | IG | 16 | 7 | 17 | ok | 25.496 / 4.128 | 0,004227 | 38,4 |
| De9dUoCAGth | IG | 13 | 10 | 23 | ok | 33.190 / 5.596 | 0,005730 | 56,5 |
| DeY-zYDtQvt | IG | 3 | 3 | 9 | ok | 15.611 / 1.996 | 0,002172 | 17,6 |
| DeeU4qItcFx | IG | 10 | 4 | 11 | ok | 18.108 / 2.785 | 0,002816 | 19,5 |
| DewquIkOYcp | IG | 13 | 6 | 15 | ok | 23.030 / 4.033 | 0,003933 | 29,2 |
| DezCpl9RsGA | IG | 11 | 10 | 23 | ok | 32.918 / 6.390 | 0,006100 | 43,7 |
| De9ffXrO_15 | IG | 10 | 8 | 19 | ok | 28.033 / 4.874 | 0,004853 | 26,8 |
| 7704417191021645078 | TT | 13 | 7 | 17 | ok (habla corregida en el plano 9) | 18.561 / 6.036 | 0,004487 | 33,0 |
| 7702633972072828190 | TT | 47 | 12 | 27 | ok | 38.223 / 5.109 | 0,005990 | 42,5 |
| 7703998863132265751 | TT | 9 | 6 | 15 | ok | 16.729 / 4.455 | 0,003513 | 28,1 |
| 7703559161040211233 | TT | 11 | 10 | 23 | ok | 23.205 / 4.778 | 0,004323 | 34,0 |
| 7703284420895116552 | TT | 16 | 12 | 27 | ok | 26.825 / 6.897 | 0,005744 | 45,2 |

**Hallazgos y límites.**

- **Por grupo se escribe casi lo mismo que antes por plano:** ≈ 500–550 tokens. Lo que bajó la salida fue tener menos unidades descritas. Un reel con 12 grupos de mucho texto en pantalla llegó a 6.897 tokens, así que el margen hasta 9.000 es real, pero no enorme.
- **Lo que se pierde:** un plano juntado con otro hereda la descripción de su grupo. Por ejemplo, personas y rostros quedan iguales en todos los planos del grupo. VE-05 puntúa personas y rostros por plano real, así que en reels de cortes rápidos ese acierto se medirá sobre la descripción del grupo. Los cortes (F1) no cambian: los planos guardados son los del detector.
- **La forma de `reel`:** la causa del fallo de VE-05 no se reprodujo (aquí volvió como objeto), así que no se sabe qué texto llegaba. La reparación cubre JSON plano, entre ```` ``` ````, tras un prefacio o con texto detrás; un texto que no contiene un objeto falla con el aviso `reel: str of N chars, not a JSON object`, sin contenido.
- **Calidad de los valores:** se leyeron dos respuestas completas. Los valores son más cortos, aunque varios pasan de 8 palabras (≈ 10–12). Una vez el modelo escribió `unknown` dentro del texto en pantalla (`[destacado: negro, grande] Z / unknown`). No se midió el acierto descriptivo: eso es VE-05 fase 2.
- **Arnés:** las respuestas crudas quedaron en `%TEMP%/m24955652/raw/` y no se versionan, porque son material de terceros.

**Adenda (2026-11-06): personas y rostros por fotograma. La regla final y su medición en vivo están en la adenda 2; esta tabla describe el primer paso.** VE-05 anotó a mano los planos de 20 reels reales. Con los grupos, personas y rostros se decidían por grupo, y cada plano heredaba «se ve una persona» si algún plano de su grupo la mostraba. En los mismos 156 planos, los falsos «hay una persona» subieron de 6 (por plano, antes de los grupos) a 20; las personas no vistas siguieron en 0. Ejemplo: en `DewquIkOYcp` solo los planos 2, 6, 10 y 12 muestran personas, y los 13 planos salieron con persona. Importa porque un plano con persona o cara no puede usarse «Igual al original».

| Campo | Valor |
|---|---|
| Versiones | `ANALYSIS_VERSION = 8` · prompt `reel-sheet-prompt-9` · esquema `reel-sheet-schema-5`; detector, muestreo y grupos sin cambios |
| Cambio | Las familias se siguen describiendo por grupo. Para personas y rostros, Haiku contesta «si», «no» o «no_se» por **cada fotograma** que recibió (`personas_por_fotograma`, `rostros_por_fotograma`), y el código decide cada plano detectado con sus propios fotogramas: con persona si alguno dice «si»; sin persona solo si **todos** dicen «no»; en cualquier otro caso, «no se sabe». Un fotograma omitido nunca cuenta como «no». Un plano sin fotogramas propios solo hereda «se ve» de los fotogramas de su grupo, nunca «no se ve». Una cara visible cuenta como persona |
| Respaldo | `people_presence` y `visible_faces` por grupo siguen en la herramienta. Si los campos por fotograma faltan o vienen mal, o si el grupo dice «se ve» y ningún fotograma dice «si», se usa la regla anterior: la respuesta mala nunca da un resultado menos seguro que antes |
| Procedencia | `reel_sheet.presence`: lo que se contestó de cada fotograma (con la numeración guardada) y de dónde salió cada plano (`own_frames`, `group_frames`, `group_fallback`, `no_frames`) |
| Costo | Salida estimada: ≈ 16 tokens más por fotograma, ≈ 650 con 27 fotogramas. El máximo medido de 6.897 pasaría a ≈ 7.550, por debajo del techo de 9.000, que no cambia. El prompt más largo sube el peor pedido a **USD 0,011545** con 32 imágenes (**USD 0,010711** con las 27 que permiten 12 grupos), así que `MAX_REQUEST_USD` pasa de 0,0115 a **0,0116** |
| Estado | Medido en vivo el 2026-11-06: ver la adenda 2, abajo. Esa medición agregó la regla de cobertura |


**Adenda 2 (2026-11-06): medición en vivo de la versión 8 y regla de cobertura.** Se repitió VE-05 en local con Haiku real sobre los mismos 20 reels (`analyze_run_ideas`, camino de producción, 0 créditos de ScrapeCreators). 19 terminaron `ok`. Uno (TikTok 7703559161040211233) quedó `source_unavailable` porque el enlace del video ya había vencido, así que no es una falla del análisis. Costo: USD 0,078 en total, USD 0,0041 de media por reel. Se comparó contra la anotación humana por plano, **revisada**: Deivid y Claude corrigieron juntos las tomas donde la anotación se contradecía con las dos versiones del modelo (`ve05/tomas/personas_rostros_revisado.csv`, fuera del repo). La regla: una persona o cara que aparece en cualquier momento del plano cuenta, aunque sea parcial.

Medido sobre 195 planos (sin el reel caído):

| Versión | Personas: aciertos | Personas que se le pasan | Personas de más | Rostros: aciertos | Caras que se le pasan |
|---|---|---|---|---|---|
| 7 (personas por grupo) | 92,3 % | 0 | 14 | 86,7 % | 2 |
| 8 (por fotograma, un «no» basta) | 96,9 % | **1** | 4 | 89,7 % | 2 |
| 8 + regla de cobertura | 94,9 % | **0** | 10 | 87,7 % | **0** |

- **Por qué falló la 8:** en planos con un solo fotograma, ese único «no» decidía. En un plano de 1,6 s el único fotograma (7,2 s) mostraba solo el producto, y la gente pasaba al principio (5,95–6,5 s). Con la regla por grupo de la versión 7 ese plano salía «se ve».
- **Regla de cobertura (`PRESENCE_MAX_GAP_S = 0,5`, `PRESENCE_RULE_VERSION = presence-frames-gap0.5-3`, emparejada con `ANALYSIS_VERSION = 8` en `PRESENCE_RULES`):** un plano queda «no se ve» solo si cumple tres condiciones: todos sus fotogramas dicen «no»; entre el inicio del plano, sus fotogramas y el final no hay un hueco de más de 0,5 s; y el resumen del grupo coincide. Si no, toma la lectura del grupo, como en la versión 7 (`sparse_fallback` en `reel_sheet.presence`): «se ve» si algún fotograma del grupo dice «si»; «no se ve» solo si el grupo dice «no se ve» y ningún fotograma lo contradice; si no, «no se sabe». Un rostro «si» cuenta siempre como persona, aunque el campo de personas venga roto. Ese caso lo encontró la revisión independiente: podía destrabar «Igual al original» y está cubierto por un test.
- **Cómo se midió la regla:** es solo código, así que no se volvió a llamar a Haiku. Las respuestas por fotograma guardadas en vivo se pasaron por `resolve_presence` del código final. Da lo mismo que la simulación previa.
- **Un error del modelo que la regla cubre:** en un reel, Haiku contestó rostro «no» a un fotograma con la cara de frente (34,0 s) y «si» a uno donde solo se veían boca y mentón. Se confirmó en Langfuse que el pedido iba en orden y que el código guardó cada respuesta en su fotograma. Ese plano tiene un solo fotograma, así que ahora decide el grupo.
- **Lo que no cambia el riesgo:** «Igual al original» exige que no se vean personas **ni** rostros. Un rostro perdido en un plano con persona vista no lo destraba.
- **Prueba del caso riesgoso con 60 reels nuevos (2026-11-06):** 5 por cuenta, de las mismas 12 cuentas, ya listados (0 créditos de ScrapeCreators). 56 terminaron `ok`, con 961 planos y USD 0,29. El caso riesgoso es un plano que queda «no se ve» por sus propios fotogramas mientras otro plano de su grupo muestra a alguien; con la regla de la versión 7 ese plano habría quedado «se ve». Salieron 11 planos así; 4 eran el mismo video publicado en Instagram y en TikTok. Deivid revisó cada plano completo, cuadro por cuadro. Solo 2 quedaban sin persona **y** sin rostro, que es lo que destraba «Igual al original». Uno era correcto: una estatua sin gente; la persona que se veía era el primer cuadro del plano siguiente. El otro fue un error: manos que sostienen una bolsa en los últimos cuadros de un plano de 0,38 s, cuyos dos fotogramas (0 y 0,21 s) estaban oscuros. **No hubo ningún rostro perdido.**
- **Decisión de Deivid (2026-11-06):** se queda la regla nueva. Acepta el riesgo medido: 1 plano con el cuerpo de alguien, sin cara, en 1.156 planos. El bloqueo que importa es el de Seedance con caras reales, y ahí no hubo ningún error.
- **Idea abierta, fuera de este PR:** que un plano con persona se arme con un avatar de OmniHuman y después pase por Seedance. Cambia la decisión F6 del ADR 44 («nunca pasar solo a Avatar») y adelanta VE-17, así que necesita su propia decisión. Para eso lo que importa es detectar caras, y su costo son los rostros de más: 15 de 195 planos (8 %) con la regla actual. Un plano solo con manos o piernas no sirve para un avatar.

---

<a id="wa-vivo-001"></a>

## WA-VIVO-001 — Prueba en vivo del menú de WhatsApp con Bianki: «Mejorar mi texto» y lector de menú (m-24955640) — 2026-11-04/05

| Campo | Valor |
|---|---|
| Fecha | Uso del 2026-11-04 (20:01–20:07 UTC) y del 2026-11-05 (11:59–15:41 UTC). Registro hecho el 2026-11-05 |
| Quién | Probó el fundador (Herwin), a mano, desde la pantalla de WhatsApp. Registró el agente data-scientist-fde (Claude Code), con lecturas de solo consulta en producción. Ticket [m-24955640](https://project.larksuite.com/5h2wsx/issue/detail/24955640) |
| Entorno | **Producción**, cliente piloto **Bianki** (shawarma y ensaladas, San Cristóbal, Venezuela), número real de WhatsApp conectado |
| Qué se probó | Todo el flujo del menú publicado el 2026-11-04: el menú nace lleno (PR #436), «Mejorar mi texto» (PR #437, `suggest_ai`, prompt `wa-suggest-1`), cargar el menú desde una foto o la página (PRs #439 y #456, `import_ai`, `wa-import-1` y luego `wa-import-2`) y «Foto o menú» en el chat (PR #457, sin modelo) |
| Modelo | `claude-sonnet-5-5`, esfuerzo `low` (ficha [`claude-sonnet-5-5.md`](claude-sonnet-5-5.md)). Topes: US$0,17 por sugerencia, US$0,30 por importación |
| Lo que dijo el fundador | «parece funcionar bien», sin detalle |
| Fuentes | Consultas `SELECT` sobre `consumption_ledger`, `whatsapp_menus`, `whatsapp_menu_versions`, `whatsapp_outbox` y `brand_products` de este tenant; `starter.definition_gaps` corrido en local sobre las definiciones guardadas; `git log` para las horas de los merges. Nada se escribió en producción. Los textos de clientes finales no se leyeron |

**Lo que se pudo medir.**

| Medida | Valor | Fuente |
|---|---|---|
| Menús del negocio | 3 creados el 2026-11-04 (uno sin versiones, uno con 1 borrador, uno con 3 versiones). Uno solo publicado | `whatsapp_menus`, `whatsapp_menu_versions` |
| Huecos del menú publicado, por versión | v1 (20:01 UTC, el menú lleno de PR #436): **9 huecos** en 5 respuestas. v2 (20:07): **2** (tiempo de entrega y tiempo de respuesta en reservas). v3 (2026-11-05 11:59, **publicada**): **0** | `definition_gaps` sobre cada versión |
| Respuestas cambiadas v1 → v2 | 4: horario, domicilio, ubicación y formas de pago. Es el patrón de una importación aceptada (7 de los 9 huecos llenados con datos del negocio) | comparación campo a campo de las definiciones |
| Respuestas cambiadas v2 → v3 | 3: el saludo, domicilio (precio y minutos) y reservas («24 horas»). Valores cortos; no se puede saber si salieron de «Mejorar mi texto» o se escribieron a mano | ídem |
| Productos creados desde la importación | **22**, todos en el mismo minuto (2026-11-04 20:03 UTC), entre la v1 y la v2: 22 con precio (US$1,50–45,00, moneda USD, la del negocio), 10 con descripción, 21 sin foto (el flujo no trae fotos; uno la recibió después). Es todo el catálogo de la marca | `brand_products`, `product_media` |
| «Foto o menú» en el chat | 5 respuestas con adjunto el 2026-11-05 entre 15:29 y 15:41 UTC: **3 menús y 2 productos**, las 5 enviadas, 0 reintentos, 0 códigos de error. Ninguna foto suelta ni pieza. En 2 conversaciones | `whatsapp_outbox` (solo conteos) |

**Hallazgo: el error de frases como valores llegó al menú publicado y sigue ahí.** La importación del
2026-11-04 (20:03–20:07 UTC) corrió con **`wa-import-1`**: el PR #456 (`wa-import-2`) se fusionó a las
21:02 UTC, una hora después. Según el commit de la corrección, la fuente fue la página web. El lector
devolvió explicaciones enteras como valores y la pantalla las pegó en los huecos de la plantilla; es
el hallazgo de producción que motivó `wa-import-2`. Lo nuevo es que **la respuesta «Domicilio» de la
versión publicada (v3) conserva esas frases**: «Llevamos tu pedido a La cobertura se confirma por
WhatsApp según la dirección de entrega. El envío cuesta REF 2,5 el costo exacto se confirma…». El
dueño solo completó los dos huecos que quedaban y publicó. `definition_gaps` da 0 porque no queda
ningún `[hueco]`: **la comprobación de huecos no detecta un texto roto**. Ninguna fila de
`whatsapp_outbox` contiene ese texto, así que no consta que un cliente lo haya recibido (las
respuestas automáticas pueden guardar solo el paso y no el texto; no se comprobó más).
Segundo defecto menor en la misma versión: «Ubicación» dice «…Paramillo, San Cristóbal, San
Cristóbal»: la dirección leída ya traía la ciudad y la plantilla la agrega otra vez.

**Lo que no se pudo medir, dicho sin rodeos.**

- **Número de llamadas, tokens y costo real: sin medición.** `consumption_ledger` tiene **0 filas en
  toda la base de producción**, de todos los proveedores y de todas las fechas.
  `claude_tools._record_anthropic_consumption` no pasa `tenant_id` y en el código no hay ningún
  `consumption_scope(...)` abierto, así que el registro es un no-op en todos los caminos. Los logs
  (`whatsapp suggestion: … usd=…`, `whatsapp menu import: … dropped=…`) se perdieron: los contenedores
  `reflex` y `api` se recrearon el 2026-11-05 a las 18:26 UTC y el registro de Docker (`json-file`) no
  conserva los anteriores; la ventana de 72 h devolvió 0 líneas. Las trazas de Langfuse viven en
  otra máquina y no se consultaron. **Los costos de la ficha siguen siendo estimaciones offline.**
- **Cuántas veces se usó «Mejorar mi texto»:** desconocido. La propuesta no se guarda; ningún cambio
  del menú se puede atribuir con certeza al modelo. **Huecos conservados, hechos añadidos, reintentos
  o rechazos de `wa-suggest-1`: sin medición.**
- **`wa-import-2` en vivo: sin evidencia de ninguna llamada.** Después del merge no hay otra tanda de
  productos ni respuestas cambiadas con forma de importación. La clasificación `value`/`sentence`
  sigue probada solo offline.
- **Datos descartados por falta de cita (`dropped`) y aciertos letra por letra de las citas:** sin
  medición (venían en el log perdido y en la propuesta, que no se guarda). Tampoco se sabe si alguna
  importación se hizo desde foto o PDF ni si `count_tokens` aceptó el pedido.
- **Precios correctos frente a la carta:** no se comparó; los 22 precios no se cotejaron con la carta
  real de Bianki.

**Costo de este registro:** US$0. Ninguna llamada a modelos ni créditos de ScrapeCreators.

**Qué se propone (sin aplicar; dueño: backend-engineer junto con este agente).**

1. Corregir a mano «Domicilio» y «Ubicación» del menú publicado de Bianki (lo hace el dueño o el
   fundador desde la pantalla; este registro no toca producción).
2. Abrir `consumption_scope(tenant_id, brand_id, operation="wa_suggest" | "wa_import")` alrededor de
   `suggest_for_brand` e `import_menu_facts` (y revisar los demás llamadores de `claude_tools`, porque
   el registro está vacío en toda la app). Sin eso, ningún costo de Claude de producción se puede
   medir después de un despliegue.
3. Un aviso antes de publicar cuando una respuesta tiene una frase pegada dentro de otra (punto o
   mayúscula a mitad de la plantilla, ciudad repetida), además de `definition_gaps`.
4. Repetir la muestra con `wa-import-2` sobre la carta impresa y la página de Bianki con los logs o el
   registro activos, y anotar llamadas, tokens, costo, `dropped` y frases clasificadas.

---

<a id="sent-haiku-001"></a>

## SENT-HAIKU-001 — Sentimiento de comentarios: Haiku contra robertuito sobre los 408 comentarios públicos (m-24854495) — 2026-10-25 · PENDIENTE

`[PENDIENTE DE ETIQUETAS · preparado 2026-10-25]`

| Campo | Valor |
|---|---|
| Fecha | 2026-10-25 (preparación y prueba de humo). La medición se corre cuando vuelvan las etiquetas |
| Quién | Agente data-scientist-fde (Claude Code). Ticket [m-24854495](https://project.larksuite.com/5h2wsx/issue/detail/24854495) |
| Decisión que mide | Fundador, 2026-10-25, opción C: el sentimiento de comentarios y menciones pasa de robertuito a Claude Haiku 5.5 reutilizando `replies.triage.ClaudeCommentTriager`, separado de la intención. robertuito se apaga en producción por defecto (PR #340, `QUALIFY_SENTIMENT_ENABLED`) |
| Candidato | `claude-haiku-5-5`, esfuerzo `low`, herramienta estricta `registrar_comentarios`, `tool_choice: auto`, lotes de 25. Prompt **`atender4a.1-conf`** = `atender4a.1` palabra por palabra más una sección que pide `confidence` (0 a 1) del sentimiento, para que `score` siga siendo un número real. No se llama `atender4a.2` porque ese nombre ya es del prompt de borradores. `atender4a.1` sigue disponible y sigue siendo el valor por defecto en el código (`TRIAGE_PROMPTS`) |
| Línea base | `pysentimiento/robertuito-sentiment-analysis`, revisión `a2cc0f67ebd705c55191e25a05ba23d885fcc09b`, `robertuito-sentiment-v1`, local en CPU (grupo `ml`), tal como corría en producción |
| Conjunto | **Solo los 408 comentarios públicos** ya anonimizados de `intent_golden_v1.jsonl`, con la misma división `dev`/`test` (203/205), en `packages/api/eval_data/sentiment_golden_v1.public.jsonl` con la columna de sentimiento vacía. Decisión del fundador del 2026-10-25: sin exportación de producción |
| Etiquetado | A ciegas, Raul y Yesika, sin ver ninguna propuesta de modelo. Reglas S1–S8 en [`guia-etiquetado-sentimiento.md`](../guia-etiquetado-sentimiento.md). 100 comentarios en común para el κ (umbral 0,70 sobre al menos 50) y 154 propios: **254 comentarios por persona**. Los desacuerdos los decide una tercera persona. Kit final: `~/qualify-eval-data/sentiment/kit-solo-publicos/` (fuera del repositorio) |
| Umbrales para cambiar | Cada clase con P ≥ 0,80, R ≥ 0,70 y n ≥ 8 en `test`; recall de `neg` ≥ 0,90; macro-F1 de Haiku ≥ macro-F1 de robertuito. Una clase que no llega se informa como «no fiable» por nombre |
| Herramientas | `just sentiment-kit public | build | merge` ([`sentiment_kit.py`](../../packages/api/evals/replies_ai/sentiment_kit.py)); `just eval-replies --sentiment [--robertuito] [--split dev|test]` ([`run_experiment.py`](../../packages/api/evals/replies_ai/run_experiment.py)); métricas puras en `qualify_api/evals/comment_sentiment.py` |

**Comentarios reales: no usados.** La exportación de solo lectura [`export_real_comments.sql`](../../packages/api/evals/replies_ai/export_real_comments.sql) se dejó escrita y probada en local, pero **no se usó: el fundador eligió solo comentarios públicos el 2026-10-25**. Nunca se corrió en producción.

**Límite que hay que leer junto al resultado: el recall de `neg` descansa solo en datos públicos.** Los 408 son comentarios públicos de negocios hispanohablantes con pocas quejas, y casi ninguna de los rubros ni de los países de los clientes. Un `neg` fiable aquí dice poco de cómo se detectan las quejas reales de Bianki, PuntoServis o la inmobiliaria, que son las que el dueño no puede dejar pasar. **Cuántos `neg` hay en cada división se sabe al volver las etiquetas**: `just sentiment-kit merge` lo informa en `support_by_split` (`acuerdo.json`) y se copia aquí. Con menos de 8 `neg` en `test` la clase queda «no fiable» por falta de ejemplos, sin importar el modelo; con menos de 15 el recall varía mucho de una corrida a otra.

| `neg` por división | `dev` | `test` |
|---|---|---|
| Comentarios etiquetados `neg` | pendiente | pendiente |

**El país no se puede cortar.** Los 408 no traen país (`country:desconocido`), así que el corte CO/VE/UY que pide el ticket queda vacío en esta medición. Los cortes de sarcasmo y de solo emojis sí se informan.

**Prueba de humo del 2026-10-25 (la única llamada pagada de esta preparación).** Se corrió con el nombre provisional `atender4a.2`; el texto del prompt es el mismo de `atender4a.1-conf`.

| Medida | Haiku `atender4a.1-conf` | robertuito |
|---|---|---|
| Material | Los 10 primeros comentarios públicos (`pub-0001`…`pub-0010`), sin etiquetar, en 2 lotes de 5 para comprobar la caché | los mismos 10 |
| Costo | **US$0,000591** (280 tokens de entrada sin caché, 722 de salida, 1.498 escritos y luego 1.498 leídos de caché) | US$0 (CPU local) |
| Latencia por lote de 5 (p50 / p95) | 1,74 s / 4,69 s | 0,07 s / 0,37 s |
| Caché del prompt | **Se lee**: el segundo lote leyó 1.498 tokens (`cache_read_input_tokens > 0`). Haiku 5.5 cachea desde 512 tokens | — |
| Confianza devuelta | 10 de 10, entre 0,35 y 0,90, no constante | puntaje softmax 0,49–0,85 |
| Coincidencia | 8 de 10 con robertuito. Difieren «Beauty» y un elogio corto: robertuito `pos`, Haiku `neu` | |

- Las herramientas funcionan de punta a punta: ambas corridas, confianza, latencia por lote, caché y procedencia (modelo, revisión, versión del prompt, sha256 del conjunto) quedan en el informe, que se guarda fuera del repositorio.
- **Observación, no medición:** Haiku dejó «Belleza» en `neu` con confianza 0,4. Según S1 de la guía es `pos`. Si se repite en `dev` cuando haya etiquetas, se corrige el prompt **en `dev`**, con una versión nueva, nunca mirando `test`.
- El costo de la prueba de humo no sirve como costo por comentario: con lotes de 5 pesa la escritura de caché. Con lotes de 25 la medición anterior dio US$0,000019 por comentario (`atender4a.1`).

**Lo que falta, en orden.**

1. El fundador envía a Raul y a Yesika su hoja (`etiquetado_raul.csv`, `etiquetado_yesika.csv`) y la guía, desde `~/qualify-eval-data/sentiment/kit-solo-publicos/`. Nadie se las ha enviado todavía.
2. Al volver las hojas: `just sentiment-kit merge --dir ~/qualify-eval-data/sentiment/kit-solo-publicos --sheet raul=… --sheet yesika=…`. Si κ < 0,70, se ajustan las reglas y se vuelve a etiquetar; los desacuerdos van a una tercera persona (`desacuerdos.csv`, columna `decision`). Copiar aquí los `neg` por división.
3. `just eval-replies --sentiment --robertuito --golden-sentiment ~/qualify-eval-data/sentiment/kit-solo-publicos/golden.jsonl --split dev` para ajustar (si hace falta), y una sola vez `--split test`, con `atender4a.1` y con `atender4a.1-conf`.
4. Resultado aquí, en la ficha [`claude-haiku-5-5.md`](claude-haiku-5-5.md) y en [`robertuito-sentiment.md`](robertuito-sentiment.md).

**Costo estimado de la medición completa:** unas 408 clasificaciones por vuelta en total; 5 vueltas en `dev` (203) y 2 en `test` (205, los dos prompts) suman unas 1.400, a unos US$0,00002–0,00003 cada una: **≈ US$0,03–0,05**. Por cliente al mes (300 comentarios) son ≈ US$0,006–0,009.

**Gasto de esta preparación:** US$0,000591 (la prueba de humo). Ninguna otra llamada pagada; ningún crédito de ScrapeCreators.

---

<a id="pb6-001"></a>

## PB6-001 — Costo real de una precarga de identidad de marca en el Alta (m-24852200) — 2026-10-25

| Campo | Valor |
|---|---|
| Fecha | 2026-10-25 |
| Quién | Agente data-scientist-fde (Claude Code). Ticket PB-6 [m-24852200](https://project.larksuite.com/5h2wsx/issue/detail/24852200), épica [m-24852192](https://project.larksuite.com/5h2wsx/story/detail/24852192) ([`epica-prellenado-brand-kit-alta.md`](../epica-prellenado-brand-kit-alta.md) §2.6) |
| Objetivo | Medir cuánto cuesta de verdad una precarga del Alta, para que el fundador fije `QUALIFY_ALTA_PREFILL_MAX_USD` (PB-4) |
| Qué se corrió | `qualify_api.creative.brand_prefill.prefill_brand_kit(..., propose=True)` con los `CallCaps` por defecto (6 pedidos a ScrapeCreators, 3 corridas de Claude). Es el mismo camino que corre el worker del Alta, sin cambios. Pipeline `PREFILL_VERSION = 1`, `main` en `ddad1034` (con #334, que ya cobra la lectura y la escritura de caché) |
| Modelos | **`claude-sonnet-5` con razonamiento**, no Haiku. Rubro: `from_profile.generate`, esfuerzo `low`, prompt `from_profile:6c769545282d`. Etiquetas del catálogo: `hashtag_ai.select_hashtags`, esfuerzo `medium`, hasta 8 turnos con herramientas, prompt `select_hashtags:16a6035cc6d1`. Revisión devuelta por la API: `claude-sonnet-5` |
| Proveedor de lectura | ScrapeCreators: `/v1/instagram/profile` + `/v2/instagram/user/posts` (siempre 2 pedidos). Clave `SCRAPECREATORS_API_KEY` |
| Claves | `QUALIFY_ANTHROPIC_API_KEY`, `SCRAPECREATORS_API_KEY`, leídas del `.env` local dentro del proceso |
| Entorno | Solo el stack local: un tenant desechable por cuenta en el Postgres local, borrado al terminar (`brand_kit_details`, `creator_profile_cache`, `social_account_claims`, `brands`, `tenants`). Ni producción ni tenants reales; sin workers |
| Script | [`packages/api/evals/alta_prefill_cost/run_experiment.py`](../../packages/api/evals/alta_prefill_cost/run_experiment.py) (`just eval-precarga`). Los resultados crudos se guardan fuera del repositorio |
| Langfuse | No había claves `LANGFUSE_*` en el `.env` local, así que los tokens salen del `usage` de cada respuesta de la API (`CallStats`), guardado en `provenance.claude` |

**Cuentas.** Las tres cuentas que administra el fundador estaban **vacías** el día de la prueba (0 publicaciones; lo confirmó en paralelo otra consulta con la CLI de ScrapeCreators). Por eso, con su acuerdo (2026-10-25), la muestra se completó con tres cuentas públicas del mismo rubro que no son suyas. Se nombran de forma genérica y sus datos no se guardaron en el repositorio ni en ningún tenant real.

| # | Cuenta | Qué tiene |
|---|---|---|
| A | Bianki, cuenta secundaria (del fundador) | Vacía: sin biografía útil ni publicaciones |
| B | Qualify, cuenta propia de Attitude Factory | Vacía |
| C | Bianki, cuenta principal (del fundador) | Biografía y categoría, 0 publicaciones |
| D | Heladería pública de Armenia (CO) | 12 publicaciones leídas |
| E | Heladería pública del Valle (CO), dos sedes | 9 publicaciones leídas |
| F | Hamburguesería pública de delivery del Táchira (VE) | Biografía, 0 publicaciones en la ventana de lectura |

**Método.** Cada cuenta se corrió dos veces:

1. **En vivo:** tenant nuevo, sin caché del perfil, así que se lee ScrapeCreators.
2. **Con caché:** el mismo tenant. El perfil sale de la caché del tenant (0 créditos). Antes se vacía la memoria en proceso del catálogo de etiquetas, para que Claude corra otra vez como lo haría en un reintento del worker desde un proceso nuevo.

Costo de Claude: `claude_tools.cost_breakdown`. Costo de ScrapeCreators: US$0,00188 por crédito (plan Freelance).

### Resultado por cuenta

| # | Corrida | Resultado | Créditos SC | Corridas de Claude | Entrada / salida / lectura de caché / escritura de caché (tokens) | US$ Claude | US$ total | Latencia |
|---|---|---|---|---|---|---|---|---|
| A | en vivo | ok, sin propuesta de etiquetas | 2 | 0 | — | 0 | **0,0038** | 9,0 s |
| A | caché | ok | 0 | 0 | — | 0 | 0 | 0,3 s |
| B | en vivo | ok, sin propuesta de etiquetas | 2 | 0 | — | 0 | **0,0038** | 10,2 s |
| B | caché | ok | 0 | 0 | — | 0 | 0 | 0,3 s |
| C | en vivo (1.ª, caché de prompts fría) | ok, 5 etiquetas + paleta | 2 | 2 | 6.907 / 1.182 / 5.082 / 2.845 | 0,0338 | **0,0375** | 34,4 s |
| C | en vivo (2.ª, script corregido) | ok, 5 etiquetas + paleta | 2 | 2 | 7.439 / 1.266 / 7.927 / 0 | 0,0291 | 0,0329 | 23,3 s |
| C | caché | ok | 0 | 2 | 7.401 / 1.318 / 7.927 / 0 | 0,0296 | 0,0296 | 15,4 s |
| D | en vivo | ok, 4 etiquetas + paleta | 2 | 2 | 6.464 / 884 / 7.927 / 0 | 0,0234 | **0,0271** | 31,2 s |
| D | caché | ok | 0 | 2 | 6.863 / 990 / 7.927 / 0 | 0,0252 | 0,0252 | 13,3 s |
| E | en vivo | ok, 5 etiquetas + paleta | 2 | 2 | 6.309 / 867 / 7.927 / 0 | 0,0229 | **0,0266** | 32,7 s |
| E | caché | ok | 0 | 2 | 4.769 / 871 / 6.233 / 0 | 0,0195 | 0,0195 | 11,3 s |
| F | en vivo | ok, 5 etiquetas + paleta | 2 | 2 | 3.618 / 649 / 6.233 / 0 | 0,0150 | **0,0187** | 17,5 s |
| F | caché | ok | 0 | 2 | 5.749 / 1.018 / 7.927 / 0 | 0,0233 | 0,0233 | 13,2 s |

En la primera corrida de C, el script todavía no le pasaba sus `ports` a la función: los totales salen de `PrefillResult.usage` y el desglose por modelo, de la segunda corrida. El script ya está corregido.

**Por modelo y paso** (en vivo, cuentas C a F): todo es `claude-sonnet-5`.

- **Rubro** (`from_profile`): 1 turno, 215 a 1.160 tokens de entrada + 1.151 de caché y 245 a 280 de salida. Cuesta entre US$0,003 y US$0,005.
- **Etiquetas del catálogo** (`select_hashtags`): 3 o 4 turnos, 3.403 a 7.185 tokens de entrada + 5.082 a 6.776 de caché y 383 a 986 de salida. Cuesta entre US$0,012 y US$0,026, es decir **el 75–90 % del costo de Claude**.
- La tercera llamada que permite `CallCaps` (crear etiquetas cuando el rubro no propuso ninguna) **no hizo falta en ninguna cuenta**.

**Cruce con la CLI de ScrapeCreators** (`scrapecreators balance` antes y después de cada lote, tomado solo alrededor de mis corridas, porque otro agente consultaba la CLI en paralelo): 6.857 → 6.851 → 6.845 → 6.839, **18 créditos**. Coincide exactamente con los 9 pedidos en vivo × 2 que cuenta `PrefillUsage`. La caché costó 0 créditos, como se esperaba.

### Costo por Alta

| Medida | US$ |
|---|---|
| Cuenta vacía (A, B): solo la lectura | **0,0038** |
| Cuenta con contenido, en vivo: media (C 1.ª, D, E, F) | **0,0275** |
| Cuenta con contenido, en vivo: máximo observado (C, caché de prompts fría) | **0,0375** |
| Reintento con el perfil en caché: media (C a F) | 0,0244 (ScrapeCreators 0; Claude corre igual) |
| Pesimista razonable: 6 créditos + rubro + creación + etiquetas en sus 8 turnos, caché fría (extrapolado de lo medido, no observado) | ≈ 0,09 |
| Peor caso que permiten los `CallCaps` por defecto: 6 créditos + 3 corridas con su `max_tokens` lleno (4.000 + 4.000 + 8 turnos × 16.000 de salida) | ≈ **1,7** (teórico) |

**Hallazgo: los `CallCaps` limitan llamadas, no tokens.** Una corrida del catálogo puede llegar a 8 turnos de hasta 16.000 tokens de salida cada uno. Por eso el techo teórico (≈ US$1,7) queda 45 veces por encima de lo observado. Un tope en dólares que solo se revisa antes de correr (la estimación de PB-4, US$0,04) no detiene a una corrida que se dispare. Si se quiere un techo duro, debe venir de `max_tokens` y del número de turnos en el camino del Alta. Eso es un cambio en `hashtags/` y `brand_prefill.py`, con sus dueños.

**Latencia:** de 17 a 34 s en vivo con contenido, unos 10 s si la cuenta está vacía y de 11 a 15 s con caché. Corre en el worker, así que no retrasa la invitación.

### Precios verificados (2026-10-25)

| Precio | Página oficial | Valor | En el repositorio | ¿Coincide? |
|---|---|---|---|---|
| `claude-sonnet-5` | [platform.claude.com/docs/en/about-claude/pricing](https://platform.claude.com/docs/en/about-claude/pricing) | US$2 de entrada / US$10 de salida por millón; escritura de caché (5 min) US$2,50; lectura US$0,20. La nota 3 dice que US$2/US$10 queda como precio estándar: la subida a US$3/US$15 no ocurrirá | `claude_tools.PRICES` (2, 10), `CACHE_READ_PRICES` 0,20, `CACHE_WRITE_MULTIPLIER` 1,25 | Sí |
| `claude-sonnet-5-5` (no lo usa la precarga) | misma página | Lectura de caché **US$0,10** (0,05× la entrada, nota 2) | `CACHE_READ_PRICES["claude-sonnet-5-5"] = 0.20` | **No**: el repositorio cobra el doble por las lecturas. Arreglarlo en `claude_tools.py` |
| `claude-haiku-4-5` (no lo usa la precarga) | misma página | US$1 / US$5; lectura US$0,10 | (1, 5), 0,10 | Sí |
| ScrapeCreators | [scrapecreators.com](https://scrapecreators.com/) | Free: 100 créditos + hasta 7.000 de bono. Freelance: US$47 por 25.000 (US$1,88 por 1.000). Business: US$497 por 500.000 (US$0,99 por 1.000). Los créditos no vencen; «1 credit === 1 request (for most endpoints)» | `descubrir-reels-scrapecreators.md` y `adr-34`: los mismos valores | Sí |

El plan del fundador no está escrito en ningún lado. El saldo (≈ 6.840) cuadra con el bono del plan gratuito, así que hoy un crédito cuesta 0 al margen. Para el tope se usa el precio Freelance, el que habría que pagar al acabarse el bono.

**Gasto total de esta medición:** Claude ≈ US$0,24 (tres lotes), ScrapeCreators 18 créditos de precarga + 1 de la búsqueda de cuentas públicas (`instagram search-profiles`), ≈ US$0,04 a precio Freelance. **En total ≈ US$0,28**, por debajo de la guarda de US$1.

### Propuesta de tope para el fundador (sin aplicar)

**`QUALIFY_ALTA_PREFILL_MAX_USD = 0.10`**

- Queda **2,7 veces por encima del máximo observado** (US$0,0375) y 3,6 veces sobre la media con contenido (US$0,0275).
- Cubre el pesimista razonable (≈ US$0,09: etiquetas en sus 8 turnos, una corrida de creación, 6 créditos, caché fría).
- Deja pasar la estimación previa de PB-4 (US$0,04) con margen, así que ninguna Alta normal se queda sin precarga.
- No cubre el techo teórico (≈ US$1,7). Para eso hacen falta límites de tokens (hallazgo de arriba), no un tope más alto.
- En §5 de la épica se había descartado una propuesta de US$0,10, que entonces era una cifra sin medir. Esta sí sale de datos. Si el fundador prefiere un tope más justo, **US$0,06** todavía cubre todo lo observado con un 60 % de margen, pero deja fuera el pesimista razonable.

| Altas al mes | Con el costo medido (US$0,0275) | Si cada Alta llegara al tope (US$0,10) |
|---|---|---|
| 10 | US$0,28 | US$1,00 |
| 50 | US$1,38 | US$5,00 |
| 100 | US$2,75 | US$10,00 |

Un reintento suma unos US$0,024 por Alta con el perfil en caché. Una cuenta vacía cuesta unos US$0,004.

**Decisión del fundador (2026-10-25): US$0,15 por Alta** (`QUALIFY_ALTA_PREFILL_MAX_USD=0.15`), en lugar de los US$0,10 propuestos. Deja margen para los borradores de la opción B1 en el primer ingreso y para TikTok. Quedó registrada en la [épica, §5 punto 2](../epica-prellenado-brand-kit-alta.md#5-decisiones-del-fundador-herwin-2026-10-24). La precarga sigue apagada hasta que exista el límite duro de tokens y de turnos.

| Altas al mes | Si cada Alta llegara al tope fijado (US$0,15) |
|---|---|
| 10 | US$1,50 |
| 50 | US$7,50 |
| 100 | US$15,00 |

### Seguimiento OL2-0 (m-24854322) — medidor en dólares por turno — 2026-10-25

**Qué cambió.** El tope ya no cuenta llamadas: cada intento del Alta lleva un medidor en dólares (`claude_tools.DollarMeter`) con lo que queda del tope. Cada crédito de ScrapeCreators (US$0,0019) se anota antes del pedido. Cada turno de Claude se cotiza antes de enviarse a su peor costo (entrada acotada por los bytes del pedido + 1.000 tokens de margen, al precio de escritura de caché ×1,25, más `max_tokens` lleno de salida): sale como se pidió, con un `max_tokens` menor que sí cabe, o no sale. Límites del Alta: lectura de 2 créditos como máximo (instantánea 5: el perfil, y una página de publicaciones solo si hace falta), rubro con 1.500 tokens × 2 intentos (antes 4.000), etiquetas del catálogo en 3 turnos × 1.200 tokens con esfuerzo `low` y un aviso de «elige ahora» antes del último (antes 8 × 16.000 con `medium`), sin la llamada de creación. Si un turno se corta o el medidor lo rechaza, las etiquetas caen a las propias de la cuenta o a las de la llamada de rubro, y la corrida termina `ok`. El asistente web no cambia.

**Peor caso calculado** (test `test_alta_dollar_meter.py`): créditos 0,0038 + rubro 0,0465 + catálogo 0,0900 = **US$0,1403 ≤ 0,15**. Un 4.º turno del catálogo sumaría US$0,04 y rompería el tope. Corrida mínima: US$0,0501. Un test offline corre 240 Altas completas contra un Claude falso adversario (cortes, rechazos, tiempos agotados, uso informado de menos) con topes de 0,15 / 0,06 / 0,02 / 0,008: nunca se cobra ni se anota más que el tope, 0 excesos, todas terminan `ok`.

**Prueba de aceptación en vivo** (`just eval-precarga --alta-usd 0.15 --skip-cache-run --max-usd 0.30`, stack local, un tenant desechable por cuenta, borrado al terminar; `claude-sonnet-5`; las mismas cuentas públicas D, E y F de arriba):

| # | Resultado | Créditos SC | Turnos rubro / catálogo | Salida (tokens) | Medido por el medidor (US$) | PB6-001 en vivo (US$) | Turnos rechazados / bajados | Etiquetas propuestas (PB6-001) |
|---|---|---|---|---|---|---|---|---|
| D | ok | 1 | 1 / 3 | 268 / 454 | **0,0263** | 0,0271 | 0 / 0 | 4 de la propia cuenta (4) |
| E | ok | 1 | 1 / 3 | 238 / 427 | **0,0186** | 0,0266 | 0 / 0 | 5 de la propia cuenta (5) |
| F | ok | 1 | 1 / 3 | 253 / 424 | **0,0172** | 0,0187 | 0 / 0 | 5 de la llamada de rubro (5) |

- Las tres quedan muy por debajo del tope (máximo US$0,0263 frente a 0,15) y ningún turno se rechazó ni se bajó: con cuentas reales el medidor es un techo, no el camino normal.
- La lectura costó **1 crédito** en las tres (antes 2): la instantánea 5 trae las 12 publicaciones en el perfil.
- **Rubro:** igual que en PB6-001 (un turno, 238–268 tokens de salida, por debajo de los 1.500).
- **Etiquetas:** mismo número que en PB6-001 (4 / 5 / 5). Pero en las tres el catálogo usó sus 3 turnos y no eligió ninguna: una corrida de diagnóstico sobre D (US$0,019) mostró dos turnos de búsqueda y, en el tercero, tras el aviso, `elegir_hashtags` con la lista vacía (nada del catálogo local le encajó). La propuesta tomó entonces las etiquetas propias de la cuenta (D, E; incluyen lugares y el nombre de la marca) o las de la llamada de rubro (F). PB6-001 no guardó el origen de sus etiquetas, así que no se puede afirmar si antes venían del catálogo. **Queda como hallazgo para OL2-4 / el dueño del catálogo:** con el catálogo local la llamada del catálogo cuesta US$0,012–0,016 por Alta sin aportar etiquetas; medirlo con el catálogo de producción antes de decidir si se mantiene en el Alta.
- La foto de perfil no se copió a R2 (no hay R2 en el stack local); no afecta al costo ni al resultado.

**Gasto de esta prueba:** US$0,062 (las tres corridas) + US$0,019 (diagnóstico) ≈ **US$0,08** en total (Claude + 4 créditos de ScrapeCreators), dentro de la guarda de US$0,30.
