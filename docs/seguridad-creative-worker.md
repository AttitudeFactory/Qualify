# Revisión de seguridad — el reclamo entre negocios de `creative-worker`

**Estado:** `[PROPUESTO — principal-architect, 2026-10-24; parte de ADR 41, pendiente de firma del fundador]`
**Ticket:** m-24852157 · **Decisión:** `docs/adr-41-cola-generacion-concurrencia.md`.
**Implementan:** m-24852160 (migración `creative_jobs` + `vendor_slots` + rol) y m-24852163 (worker). Esta revisión fija lo que esas dos historias deben cumplir; un cambio a estas reglas es un cambio a ADR 41.

## 1. Por qué hay un reclamo entre negocios

`creative_jobs` tiene RLS forzado por `tenant_id`, como toda tabla de negocio. Pero el semáforo de 10 es **de la cuenta de BytePlus, no de un negocio**: para repartir 10 cupos entre todos, el worker tiene que ver la fila de todos. Por `tenant_session` eso es imposible (ve un solo negocio). Es el mismo problema que resolvieron `planner/discovery.py` (qué negocios tienen publicaciones pendientes) y `webhook_worker_session` (a qué negocio pertenece un evento de Meta), y se resuelve igual: **una puerta propia, estrecha, solo para decidir el orden; todo lo demás, por `tenant_session`.**

## 2. La puerta: `creative_worker_session()`

Rol nuevo `qualify_creative_worker`, módulo `packages/shared/src/qualify_shared/db/creative_worker.py`, DSN propio (`QUALIFY_CREATIVE_WORKER_DSN`, contraseña en `.env.prod` por `just env-push`). Mismo molde que `qualify_shared/db/webhook.py`: motor privado y perezoso, una transacción por bloque, sin fijar `app.tenant_id`.

| Regla | Detalle | Por qué |
|---|---|---|
| **NOBYPASSRLS** | A diferencia de `qualify_webhook_worker` (0050), que tiene BYPASSRLS | BYPASSRLS vale para **toda** tabla en la que el rol tenga GRANT. Si mañana alguien le concede por error `SELECT` en `content_drafts`, ese rol leería las piezas de todos. Con NOBYPASSRLS, un GRANT de más sigue chocando con RLS (`app.tenant_id` vacío → cero filas) |
| **Política RLS solo para ese rol, solo en `creative_jobs`** | `CREATE POLICY creative_worker_claim ON creative_jobs FOR ALL TO qualify_creative_worker USING (true) WITH CHECK (true)` | Permisiva y acotada a una tabla: el permiso entre negocios existe en un solo lugar, legible en la migración |
| **GRANT por columna en `creative_jobs`** | `SELECT` de las columnas de la cola (`id`, `tenant_id`, `kind`, `vendor_model`, `lane`, `status`, `priority`, `not_before`, `deadline`, `queued_at`, `claimed_by`, `claim_token`, `lease_until`, `attempts`, `vendor_task_id`). `UPDATE` solo de `status`, `claimed_by`, `claim_token`, `lease_until`, `attempts`. **Ni `INSERT` ni `DELETE`** | El worker decide el orden, no el contenido: no ve el prompt, ni el `draft_id`, ni la procedencia, ni el resultado. No puede crear trabajos (gastar) ni borrar la evidencia |
| **`vendor_task_id` no lo escribe esta puerta** | Lo escribe el paso de envío **dentro de `tenant_session`**, una sola vez (disparador: `vendor_task_id` pasa de NULL a un valor y nunca cambia) | Quien controle la puerta no puede borrar el id de una tarea pagada para provocar un segundo envío |
| **`vendor_slots`: `SELECT`, `UPDATE`** | Ningún otro rol tiene privilegios en esa tabla; `qualify_app` tampoco | El semáforo solo lo mueve el worker |
| **Ningún otro privilegio** | Ni `content_drafts`, ni `image_assets`, ni `tenants`, ni credenciales | Un GRANT nuevo a este rol es un cambio de esta revisión, no un detalle de implementación |
| **Solo la importa el worker** | Prueba estática en la línea de la de C-01: `creative_worker_session` no se importa fuera de `qualify_api.creative.worker` | Que ninguna ruta de la petición pueda tomarla por accidente |

## 3. El trabajo de cada negocio va por `tenant_session`

Lo que hace el worker con un trabajo reclamado, en orden:

1. Con la puerta del worker: reclamar (`FOR UPDATE SKIP LOCKED`), escribir `claimed_by`, un `claim_token` nuevo (contador que crece en cada reclamo, sirve de ficha de exclusión), `lease_until` y el cupo. Sale de esa transacción **solo con `(job_id, tenant_id, claim_token)`**.
2. Abrir `tenant_session(job.tenant_id)` con el `tenant_id` **leído de la fila reclamada**, nunca de otra fuente. Dentro: leer el trabajo completo y la pieza (RLS los aísla), comprobar `draft.tenant_id == job.tenant_id`, pasar el guardián de precio y del cupo del plan, enviar a BytePlus, guardar `vendor_task_id`. Cada escritura lleva `WHERE claim_token = :token`: si otro reclamo lo adelantó, la escritura no toca nada y el paso se abandona.
3. Una `tenant_session` por paso y por trabajo, corta; **nunca** una sesión compartida entre trabajos ni guardada en el worker.
4. Las claves de BytePlus son de la plataforma (variables de entorno), no credenciales del negocio: `credential_session` no entra en este flujo.

## 4. `vendor_slots` sin `tenant_id` ni RLS: justificación

La regla de la casa es RLS en toda tabla. Esta es una excepción deliberada, del mismo tipo que `ingestion.raw_payloads` (ADR 18) y las tablas de entrada de webhooks de Meta (0050, aisladas por GRANT):

- **No guarda datos de ningún negocio.** Columnas: `vendor_model`, `slot_no`, `holder_job_id` (uuid de un trabajo, o NULL), `lease_until`, `updated_at`. No tiene `tenant_id` a propósito: el reparto justo se calcula sobre `creative_jobs`, no aquí.
- **Es un recurso de la cuenta de BytePlus**, que es una sola para todos: partirla por negocio contradice lo que modela.
- **Aislada por GRANT:** solo `qualify_creative_worker` la lee y la escribe.
- **Lo que podría filtrar** es cuántos cupos están ocupados en un momento, sin decir de quién. Un `holder_job_id` no se puede resolver a un negocio sin leer `creative_jobs`, y `qualify_app` no ve los trabajos de otros negocios.
- **Candado en el código:** una prueba de esquema falla si `vendor_slots` gana una columna fuera de esa lista (en particular `tenant_id`, `draft_id`, `brand_id` o cualquier texto libre). La migración lo dice en su docstring.

## 5. Qué podría hacer un atacante o un error

| # | Escenario | Qué pasaría sin mitigación | Mitigación |
|---|---|---|---|
| 1 | **Error de código:** el worker abre la sesión con el `tenant_id` equivocado | Escribir el resultado en la pieza de otro negocio | El `tenant_id` sale solo de la fila reclamada; la pieza se lee por id dentro de esa sesión, así que con el negocio equivocado RLS no la encuentra y el paso falla cerrado; comprobación explícita `draft.tenant_id == job.tenant_id`; prueba `-m db`: un trabajo del negocio A procesado con la sesión de B no lee ni escribe nada |
| 2 | **Trabajo falsificado:** un negocio inserta un trabajo con el `draft_id` de otro | Generar (y cobrar) sobre la pieza de otro negocio, o leer su resultado | `WITH CHECK` de RLS fija `tenant_id` al de quien inserta; **clave foránea compuesta** `(tenant_id, draft_id) → content_drafts(tenant_id, id)` que rechaza la fila al insertar; y aunque pasara, el paso 2 del §3 no ve la pieza ajena |
| 3 | **Un negocio acapara la fila** (error en un bucle de la UI, o abuso) | Gastar en BytePlus y dejar a los demás detrás | Máximo 2 a la vez por negocio y modelo; turnos entre negocios; tope de trabajos en espera por negocio (p. ej. 20) al insertar; el guardián de cupo del plan al insertar **y** otra vez antes de enviar (regla 7); la clave natural `UNIQUE` impide encolar dos veces lo mismo |
| 4 | **Se filtra la contraseña de `qualify_creative_worker`** | Ver la fila de todos; reordenar, cancelar o reintentar trabajos | Solo ve metadatos de la cola (tipo, modelo, horas), nunca contenido ni `draft_id`; no puede insertar (no puede gastar con trabajos nuevos) ni borrar; no puede tocar `vendor_task_id` (no puede forzar un segundo envío pagado); como mucho atrasa o hace fallar trabajos, y eso se ve en los avisos a Lark (m-24852167). El DSN solo existe en el contenedor del worker; rotación con `just env-push` |
| 5 | **Dos workers** (o uno reiniciado) procesan el mismo trabajo cuando vence la concesión | Dos envíos y dos cobros | `SKIP LOCKED` al reclamar; `claim_token` en cada escritura; **un trabajo con `vendor_task_id` nunca se reenvía, solo se consulta**. Riesgo residual: un proceso que muere **entre** el `POST` a BytePlus y guardar el id deja una tarea pagada huérfana (BytePlus no acepta una clave de idempotencia en la creación, a verificar en vivo, regla 6). Se concilia con el listado de tareas de BytePlus por ventana de tiempo y modelo; el caso se registra para medirlo |
| 6 | **Se pierde un cupo** (el worker muere con un cupo tomado) | Cupos que nunca vuelven y la cola se para; o, al revés, soltar un cupo cuya tarea sigue viva y pasar de 10 | La concesión vence y el siguiente worker la recupera, pero **si el trabajo tiene `vendor_task_id` y la tarea sigue viva, retoma la consulta con el cupo tomado** en vez de soltarlo; el cupo se suelta solo con la tarea terminada en BytePlus. Si aun así pasamos de 10, BytePlus encola (no falla) y la consulta por id lo recoge |
| 7 | **La espera estimada delata la actividad de otros negocios** | Un negocio deduce cuánto genera la competencia | El aviso muestra minutos redondeados, no cantidades ni posiciones; el agregado en Redis no lleva ids ni negocios; con menos de 3 negocios activos en la fila se muestra un texto genérico |
| 8 | **Un final se publica sin que nadie lo vea** (nocturno, inmediato o de «Publicar ahora») | Un video que el dueño no aprobó sale a Instagram | El estado `final_ready` no es publicable: lo rechaza el guardián que ya existe (`planner/publishable.py`); la confirmación queda atada al hash del objeto (ADR 41 §3); prueba `-m db` del ejecutor: un evento con final `final_ready` queda `scheduled` y no crea intento |
| 8b | **El correo de la mañana** (ADR 41 §3.6) | Un enlace reenviado o filtrado confirma o publica un video sin el dueño, o abre la pieza de un negocio a quien no tiene sesión | El enlace solo abre la pieza **después de iniciar sesión** y bajo `tenant_session` del usuario; nunca lleva un token que confirme o publique por sí solo; la confirmación es siempre un clic dentro de la app. Clave de idempotencia `(tenant_id, fecha)` para no mandar el correo dos veces |
| 9 | **Fugas en los registros** | Prompts, textos de la marca o claves en los logs del worker | El worker registra solo ids, modelo, estado y tiempos; nunca el prompt ni la respuesta del proveedor; la clave de BytePlus nunca en el log (el cliente ya la oculta) |
| 10 | **`callback_url` de BytePlus** (si se adopta, §4.0 de la evidencia) | Un punto de entrada público que cualquiera podría llamar para marcar trabajos como terminados | Fuera de este ADR: por defecto se consulta. Si se adopta, va con su propia revisión: firma o token por tarea, y el callback solo despierta al worker, que vuelve a consultar a BytePlus; nunca asienta un resultado con lo que trae el callback |

## 6. Pruebas que las historias deben traer

- `-m db`: el negocio A no ve los trabajos de B por `tenant_session`; `qualify_app` no lee `vendor_slots`; `qualify_creative_worker` no lee `content_drafts` (aunque se le conceda por error un GRANT en una prueba, RLS devuelve cero filas); no puede `INSERT` ni `DELETE` en `creative_jobs` ni escribir `vendor_task_id`.
- `-m db`: la clave foránea compuesta rechaza un trabajo con la pieza de otro negocio.
- Sin base: el reclamo no supera 10 cupos ni 2 por negocio con 50 trabajos de 5 negocios; el reparto es por turnos.
- Estática: `creative_worker_session` solo se importa desde el worker; `vendor_slots` no gana columnas.
- Ejecutor del calendario: `final_ready` → `NOT_READY`, el evento sigue `scheduled`; hash distinto al confirmado → no se publica.
