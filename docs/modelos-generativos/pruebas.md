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
