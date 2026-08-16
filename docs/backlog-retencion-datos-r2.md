# Backlog — Retención de datos y coste de R2 (Fase 1, plano de objetos)

**Fecha:** 2026-08-13 · **Estado:** `[PROPUESTO — pendiente de firma del fundador]`
**Origen:** instrucción del fundador (2026-08-13): *«guardar datos por 1 semana máximo hasta 1 mes, de modo de optimizar costos en R2, e ir eliminando datos/reels de más de 1 mes que ya no son tendencia ni relevantes para el negocio de earned media»*.
**Fase:** Fase 1 Parte 3 (pipeline de ingesta). **Ningún backlog vivo cubría esto**: `backlog-features-gtm.md` y `backlog-crm-workflows.md` están archivados, y los de Sprint 3 / Motor de Contenido son de otro alcance.
**Docs que toca:** [`plan-ingesta-social.md`](plan-ingesta-social.md) §3.9/§3.10/§4, [`arquitectura.md`](arquitectura.md) §6 (ADR 18, ADR 22, ADR 28c, ADR 31), `CLAUDE.md` (§ "Data model conventions").

---

## 0. La regla, en una frase

**Los bytes pesados de earned media viven días, no años.** El artefacto binario (video, keyframes, audio) se purga a **7 días** por defecto y **30 días como techo absoluto**; lo que sobrevive indefinidamente es lo **derivado y barato**: las filas de Postgres (métricas, transcripción, descripciones de visión, sentiment, `search.content_index`) y el **JSON crudo de hidratación**.

Un reel de hace dos meses ya no es tendencia — pero *lo que aprendimos de él* sí sigue siendo el activo. La regla purga el contenedor, no el conocimiento.

### Lo que esta regla NO hace

1. **No borra filas de Postgres.** Un histórico de sentiment/temas es exactamente lo que las Fases 2 y 3 venden (evolución, comparativas, detección de crisis contra una línea base). Borrarlo a 30 días destruye el producto para ahorrar céntimos — ver `RET-08`, que es la única pregunta abierta al fundador.
2. **No cambia la purga de `ingestion.pipeline_jobs` a 90 días** ya definida en `plan-ingesta-social.md` §3.10. Es otra tabla, otro motivo (observabilidad) y otro plano (Postgres, no R2).
3. **No aplica al media de publicación** (`t/{tenant_id}/media/…`, Sprint 3): ese ciclo de vida no es temporal, es de estado — se borra cuando la publicación termina en OK, no cuando cumple días (ver `RET-06`).

---

## 1. Por qué la regla es correcta, con números

Precios verificados contra la documentación de Cloudflare el **2026-08-13** (`developers.cloudflare.com/r2/pricing/`, últ. act. 2026-08-07): almacenamiento **Standard $0.015/GB-mes**, **Infrequent Access $0.01/GB-mes** (+ $0.01/GB de recuperación), **Class A (escrituras) $4.50/millón**, **Class B (lecturas) $0.36/millón**, **egress $0**. Free tier mensual: **10 GB-mes**, 1M Class A, 10M Class B.

**Supuestos del modelo (a validar contra el primer piloto real — hoy no hay ni un byte en R2):** 1.000 posts/día; por post ≈ 5 MB de video + 4 MB de keyframes (≈40 JPG) + 2 MB de audio WAV + **0,1 MB de JSON de hidratación**. Total ≈ **11 MB de binario y 0,1 MB de texto por post**.

| Escenario | Almacenamiento en régimen | Coste/mes | Comentario |
|---|---|---|---|
| Sin purga, a los 12 meses | ~4 TB | **~$60** y subiendo ~$5 cada mes | El problema no es el nivel, es que **crece sin techo, para siempre** |
| Binarios a 30 días | ~330 GB | **~$5** | Estable |
| **Binarios a 7 días (propuesta)** | **~77 GB** | **~$1,2** | Estable. Con 200 posts/día cabe casi entero en el free tier |
| JSON crudo retenido para siempre | ~36 GB/año | **~$0,55/mes el primer año** | **<1% de los bytes.** Purgarlo no ahorra nada y sí rompe ADR 31 |

**Los dos hallazgos que ordenan todo lo demás:**

1. **El 99% del coste de almacenamiento son los binarios; el JSON crudo es ruido contable.** Por eso la regla se aplica **por clase de artefacto**, no por fecha global. Un TTL uniforme de 30 días sobre todo el bucket ahorraría lo mismo que uno de 7 días sobre los binarios, y encima destruiría la propiedad de reversibilidad de ADR 31.
2. **A este volumen, las operaciones cuestan más que el almacenamiento.** ~42 objetos/post × 1.000 posts/día ≈ 1,3M escrituras/mes → **~$1,3/mes en Class A**, comparable al almacenamiento entero bajo TTL de 7 días, y los keyframes son el 95% de esas escrituras. Ver `RET-05`.

---

## 2. Tabla de retención por clase de artefacto

Las clases se derivan de los espacios de clave reales, verificados en disco (`qualify_scraper/shared.py:247-263`, `qualify_shared/objects/keys.py`), no de documentación.

| Clase | Prefijo R2 | TTL propuesto | Por qué |
|---|---|---|---|
| Video original | `scrape/{platform}/…` (Parte 3, aún no escrito) | **7 días** | El más pesado. Una vez extraídos frames + audio, su único uso es re-derivar con otro modelo — cubierto por la ventana de 7 días |
| Keyframes (JPG) | ídem | **7 días** | Consumidos por SigLIP/VLM en horas. Sobreviven las descripciones, no los píxeles |
| Audio WAV | ídem | **7 días** | Sobrevive la transcripción. Un WAV de 16 kHz pesa 10× su equivalente en opus |
| **JSON de hidratación (`raw_payloads`)** | `scrape/{platform}/{url_hash}` | **indefinido** (o `Infrequent Access` a 30 días) | **Es el ancla de reversibilidad de ADR 31** y de «re-parsear sin re-scrapear» (el scrape cuesta dinero por request). Pesa <1% |
| Raw de primera parte | `t/{tenant_id}/fp/…` | **indefinido** | Mismo argumento; además es dato propio del tenant, no earned media |
| Media de publicación | `t/{tenant_id}/media/{connection_id}/…` | **por estado, no por tiempo** | Se borra al confirmar publicación OK; 30 días como red de seguridad para lo que quedó colgado (`RET-06`) |
| Derivados en Postgres | — (no es R2) | **indefinido** | Es el activo. Ver `RET-08` |

> **La tensión que hay que nombrar antes de firmar.** `CLAUDE.md` dice hoy, en «Data model conventions»: *«Raw scrape payloads are always kept in R2 … **This is what keeps ADR 31 reversible**: the analytical plane is reconstructible»*. La tabla de arriba **respeta** esa propiedad al excluir el JSON de la purga. Si el fundador quiere purgar también el JSON, eso **no es un ajuste de coste sino una enmienda a ADR 31**: a partir de ahí, arreglar un bug de parser dejaría de poder rellenarse hacia atrás más allá de la ventana, y una migración futura a ClickHouse sólo podría reconstruir el último mes. Coste de conservar esa opción: **~$0,55/mes**. Recomendación: conservarla.

---

## 3. Items

### RET-01 — Firmar la política de retención por clase de artefacto (ADR)

- **Historia:** Como fundador, quiero una política de retención escrita y firmada por clase de artefacto, para que el coste de R2 tenga techo por construcción y no dependa de que alguien se acuerde de borrar.
- **Tipo:** ADR + documentación. No es código.
- **Criterios de aceptación:**
  - Nuevo ADR (35) en `arquitectura.md` §6 con la tabla de §2 de este doc, en estado `[APROBADO]`.
  - `plan-ingesta-social.md` §3.9 gana una subsección de ciclo de vida del artefacto, y §4 (definición de done de la Parte 3) gana la purga como criterio.
  - `CLAUDE.md` § «Data model conventions» refleja la regla y **conserva o enmienda explícitamente** la frase de reversibilidad de ADR 31 — no se queda contradiciéndose.
  - Queda escrito el número que hace revisar la política (ver §4).
- **Prioridad / tamaño:** Alta / S. **Dependencias:** ninguna.

### RET-02 — Implementar la purga con *object lifecycles* nativos de R2, no con código

- **Historia:** Como operador, quiero que la purga la ejecute R2 por configuración de bucket, para no mantener un worker de borrado ni abrirle un verbo `delete` a la puerta sancionada del plano de objetos.
- **Contexto verificado en disco:** `ObjectStore` expone **sólo `put` y `open`** (`qualify_shared/objects/s3.py`), y un test estático (`test_object_store_sanctity.py`) prohíbe construir un cliente S3 fuera de ese módulo. **Hoy no existe capacidad de borrado, y añadirla es una decisión de arquitectura, no un detalle.** R2 soporta reglas de ciclo de vida por prefijo (`/r2/buckets/object-lifecycles/`), que es exactamente la forma de esta regla.
- **Criterios de aceptación:**
  - Reglas de lifecycle declaradas por prefijo (`scrape/{platform}/video/`, `/frames/`, `/audio/`) con sus días, **versionadas en el repo** (wrangler/Terraform), no clicadas en el dashboard.
  - El prefijo del JSON crudo y el de `t/{tenant_id}/` quedan **explícitamente excluidos** de cualquier regla de borrado temporal.
  - `ObjectStore` **no** gana un método `delete` en este item. El borrado dirigido (offboarding de tenant, petición de supresión) es otro item, con su propio ADR — se apoyará en que las claves ya son *delete-by-prefix* por diseño (ADR 22).
  - Verificado en un bucket de staging: un objeto escrito con fecha antigua desaparece; uno del prefijo excluido no.
  - Documentado si el borrado por lifecycle factura o no como Class A (**no verificado — no asumirlo**).
- **Prioridad / tamaño:** Alta / M. **Dependencias:** que exista el bucket y el cliente R2 de la Parte 3 (`packages/shared` ya tiene `R2ObjectStore`, pero nada del pipeline escribe todavía).

### RET-03 — `purged_at`: que la base de datos sepa que el objeto ya no está

- **Historia:** Como ingeniera del pipeline, quiero que una fila que apunta a un objeto purgado lo diga en su propia columna, para que un re-proceso falle con un error tipado en vez de con un 404 misterioso dentro de un worker.
- **Por qué:** el lifecycle borra el objeto pero **no toca la fila**. `ingestion.raw_payloads.r2_key` e `ingestion.posts.hydration_json_r2_key` se convierten en punteros colgantes silenciosos.
- **Criterios de aceptación:**
  - Migración Alembic: `purged_at timestamptz NULL` en las tablas del plano analítico que guardan una clave de R2.
  - Un job de reconciliación (Celery Beat) marca `purged_at` según la misma política de días — **derivada de una sola constante**, no dos TTL escritos a mano que puedan divergir de las reglas de lifecycle.
  - `ObjectStore.open` levanta un error tipado (`ObjectNotFound`) en vez de propagar un `ClientError` de botocore.
  - Un test demuestra que re-encolar un post con `purged_at IS NOT NULL` **no** vuelve a scrapear en silencio: o falla explícito, o pasa por la ruta de re-scrape con su coste declarado.
- **Prioridad / tamaño:** Alta / M. **Dependencias:** `RET-02`.

### RET-04 — Que la purga no mienta sobre el estado del pipeline

- **Historia:** Como operador, quiero que un post cuyos binarios ya se purgaron siga siendo distinguible de uno que nunca se procesó, para que un barrido de reconciliación no lo trate como trabajo pendiente y lo re-scrapee para siempre.
- **Criterios de aceptación:** `scrape_status` sigue siendo un espejo, no un semáforo (§3.5 del plan); un post purgado con enriquecimiento completo **no** aparece en el índice parcial `WHERE scrape_status <> 'indexed'`; existe un test del ciclo purga → barrido → no re-encola.
- **Prioridad / tamaño:** Alta / S. **Dependencias:** `RET-03`.

### RET-05 — Empaquetar los keyframes en un solo objeto

- **Historia:** Como responsable del coste, quiero que los ~40 keyframes de un video se escriban como **un** objeto (tar/zip) y no como 40, porque a este volumen las operaciones Class A cuestan tanto como el almacenamiento y los frames son el 95% de ellas.
- **Criterios de aceptación:** un post = 1 objeto de frames; el extract-worker y el filtro CLIP leen del paquete sin descomprimir a disco entero; medida antes/después de escrituras Class A por post.
- **Prioridad / tamaño:** Media / M. **Dependencias:** el `extract-worker` de la Parte 3 (no existe). **Decidirlo antes de escribirlo** — cambiarlo después es re-ingesta de artefactos.

### RET-06 — El media de publicación se borra por estado, no por calendario

- **Historia:** Como operador, quiero que un asset ya publicado con éxito desaparezca de R2 al confirmarse la publicación, para no pagar 30 días de almacenamiento por bytes que Meta ya tiene.
- **Criterios de aceptación:** al pasar `publish_attempts` a estado terminal OK se libera el objeto; regla de lifecycle de 30 días **sólo** como red de seguridad para lo que quedó colgado; el borrado dirigido pasa por el `ObjectGate` (que ya fuerza el prefijo de tenant), nunca por el store crudo.
- **Prioridad / tamaño:** Media / S. **Dependencias:** `RET-02`; Sprint 3 (publishing).

### RET-07 — Medir antes de creerse el modelo

- **Historia:** Como fundador, quiero ver GB-mes y número de objetos por prefijo, para saber si los supuestos de §1 (5 MB/video, 1.000 posts/día) se parecen a la realidad — hoy son estimaciones, no medidas.
- **Criterios de aceptación:** métrica semanal de GB-mes y objetos por prefijo; el modelo de coste de §1 se corrige con la primera medida real y queda fechado; alerta si el almacenamiento crece dos semanas seguidas bajo una política que debería mantenerlo estable (síntoma de que una regla de lifecycle no está aplicando).
- **Prioridad / tamaño:** Media / S. **Dependencias:** `RET-02`.

### RET-08 — [GATE DEL FUNDADOR] ¿La regla alcanza también a las filas de Postgres?

- **La pregunta:** *«eliminar datos/reels de más de 1 mes»* — ¿sólo los bytes en R2, o también las filas de `ingestion.posts` / `search.content_index`?
- **Recomendación: sólo los bytes.** Tres razones:
  1. **El coste está en R2, no en Postgres.** ~12,5M filas/año de texto y métricas son megabytes, no terabytes; a este volumen la fila es prácticamente gratis y el video no.
  2. **El histórico *es* el producto.** «El sentiment de la marca cayó respecto al trimestre pasado», «este tema lleva 6 semanas creciendo» y la detección de crisis contra línea base son Fase 2 y 3. Con 30 días de memoria, ninguna de las tres existe.
  3. **La premisa de la instrucción se cumple igual.** «Ya no es tendencia» es cierto para *el reel*; el dato derivado de ese reel es justamente lo que convierte un feed en un histórico.
- **Si aun así se decide purgar filas:** debe entrar como agregación, no como borrado — resumen mensual por marca/tema/sentiment antes de tirar el detalle — y requiere enmienda explícita al alcance de las Fases 2 y 3. No se implementa nada de esto sin firma.
- **Prioridad / tamaño:** Bloqueante para `RET-01` / decisión, no código.

---

## 4. Criterio de revisión de la política

La política se revisa (no antes) cuando ocurra cualquiera de estas tres cosas, para no re-litigarla cada mes:

1. La factura de R2 supera **$25/mes** sostenidos → recortar el TTL de binarios o mover el JSON a `Infrequent Access`.
2. Un cliente pide re-analizar contenido **fuera de la ventana** más de una vez → el TTL de 7 días es demasiado corto para el uso real; subirlo hacia el techo de 30.
3. Aparece un requisito legal o de plataforma con ventana propia (Meta Platform Terms, GDPR/supresión) → **a verificar, no asumido**: podría *imponer* borrado más agresivo del dato de plataforma, en cuyo caso manda ese requisito y no el coste.

> Nota a favor, no verificada y por tanto no usada como justificación: una retención corta suele **facilitar** el cumplimiento de las condiciones de plataforma y de las peticiones de supresión, en vez de estorbarlo. Conviene confirmarlo cuando se prepare Business Verification.

---

## 5. Prompt de arranque para `/team-dev`

> Implementa `RET-02` + `RET-03` + `RET-04` de `docs/backlog-retencion-datos-r2.md`, **sólo después** de que `RET-01` esté firmado como ADR y `RET-08` tenga respuesta del fundador. Antes de escribir nada, verifica contra el filesystem: (a) `packages/shared/src/qualify_shared/objects/` — hoy `ObjectStore` no tiene `delete` y un test estático prohíbe crear clientes S3 fuera de ese módulo, así que **no le añadas un verbo de borrado**, la purga temporal va por reglas de lifecycle de R2; (b) las tablas del plano analítico (`ingestion.*`) **aún no existen** — `purged_at` se escribe en la misma revisión de Alembic que crea cada tabla, no en una migración posterior. `RET-05` es una decisión de formato: tómala antes de escribir el `extract-worker`, no después.
