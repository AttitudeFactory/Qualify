# ADR 41 — Cola de generación en Postgres y servicio `creative-worker`

**Estado:** `[PROPUESTO — principal-architect, 2026-10-24; el fundador aprobó el servicio nuevo ese día con el ADR primero; pendiente de su firma]`
**Ticket:** m-24852157 · **Épica:** m-24852152 (`docs/epica-escalar-generacion.md`).
**Evidencia:** `docs/escalar-generacion-concurrencia.md` (data-scientist-fde, 2026-10-24: límites de BytePlus citados de la fuente, duración medida de las tareas, simulación de demanda).
**Revisión de seguridad:** `docs/seguridad-creative-worker.md` (forma parte de esta decisión).
**Numeración:** la épica habla de «ADR 40», pero el 40 se firmó el mismo día para SonarQube y Langfuse (`docs/adr-40-sonar-langfuse-gestionados.md`, PR #314). Esta decisión es la **41**.

## 1. Contexto

### 1.1 Lo que limita BytePlus (verificado en la fuente el 2026-10-24)

| Hecho | Valor | Consecuencia para el diseño |
|---|---|---|
| Tareas a la vez, Seedance 2.5 | **10 por modelo y por cuenta principal**, sumando versiones y subcuentas | Una llave aparte para desarrollo o evaluaciones **no** da más cupo: comparte las 10 |
| Borradores y finales | **Comparten las mismas 10** (el borrador es `draft: true` del mismo modelo) | Un final nocturno compite con las vistas previas del día si no se separan por horario |
| Pasarse de 10 | **No da error:** la tarea espera en una cola de BytePlus hasta 48 h (`execution_expires_after`) | El exceso es invisible para nosotros y para el dueño; nuestro adaptador abandona a los 8 min y el video se cobra igual |
| Pasarse de 600 por minuto | HTTP 429 (`ModelAccountRpmRateLimitExceeded`) | Hace falta espera adaptativa ante 429 (m-24852159) |
| OmniHuman 1.5 | **1 tarea a la vez** | Un carril propio de capacidad 1; dos presentadores a la vez ya hacen fila de ~12 min |
| `priority` 0–9 | Gratis, solo ordena la cola de BytePlus | No sirve como cobro: mientras nosotros no pasemos de 10, la cola de BytePlus está vacía |
| Modo flex o lotes con descuento | **No existe para Seedance 2.5** | «Agendar» no ahorra nada de proveedor |

### 1.2 Lo que hace hoy nuestro código

`InlineDispatcher` (`creative/dispatch.py`) lanza un `threading.Thread` por cada generación o final, sin tope, sin reparto por negocio y sin persistencia: el hilo muere con el proceso en cada despliegue. El adaptador espera 8 min **desde que crea la tarea, cola incluida**, y nadie llama a `get_task` después. El reaper da por muerto un carrusel animado largo que sigue vivo. Dos de esas fallas (m-24852154, m-24852156) cuestan dinero hoy y se arreglan sin este ADR; el resto necesita una cola que sobreviva al proceso.

### 1.3 Cuándo duele (simulación, uso típico al 50 % del cupo)

10 tareas a la vez sobran para 10 y 50 negocios en todos los escenarios. Con uso típico alcanzan hasta **~500 negocios**; en el peor caso (todos agotan el cupo y BytePlus va el doble de lento), hasta **~200**. OmniHuman se satura en el pico del fin de semana hacia **~420**.

### 1.4 Decisiones del fundador que dan forma a este ADR (2026-10-24)

1. Servicio nuevo `creative-worker`, ADR primero.
2. **Los finales de las publicaciones programadas se hacen de noche, con una segunda mirada:** el dueño confirma el final en «Tu semana» antes de que se publique. ux-designer diseña los indicadores.
3. El ticket a BytePlus para subir el cupo se manda hacia los **100 negocios** (m-24852172).
4. «Generar ya» solo se cobra en la **Fase 2** (m-24852171).

## 2. Decisión

1. **La cola vive en el único Postgres** (ADR 31). Una tabla `creative_jobs` (con `tenant_id`, RLS y la política `NULLIF` de siempre) guarda cada trabajo de generación que llama a un proveedor de pago: vista previa, final, presentador, escena animada de carrusel. El pedido del dueño solo **inserta** la fila, en la misma transacción que cambia el estado de la pieza (patrón outbox). Nada caro corre en la petición (regla 7).
2. **Un semáforo global por proveedor y modelo**, `vendor_slots`: una fila por cupo (`byteplus:seedance-2-5` × 10, `byteplus:omnihuman-1-5` × 1, …). Un trabajo solo se envía a BytePlus si tiene un cupo tomado, y lo suelta cuando la tarea de BytePlus termina (no cuando nuestro proceso muere). Así **nunca pasamos de 10 en BytePlus**: la fila que se forma es la nuestra, visible y ordenable, y no la de BytePlus, que es ciega. La tabla no tiene `tenant_id` ni RLS, a propósito (justificación en `docs/seguridad-creative-worker.md` §4).
3. **Un servicio nuevo, `creative-worker`**: un worker CLI en bucle, igual que `calendar-worker` o `whatsapp-worker`, con la **misma imagen `app`**. No es un runtime nuevo: es otro contenedor de Python del mismo código. Cada vuelta:
   1. recupera cupos con la concesión vencida (sin soltar los que tienen una tarea de BytePlus todavía viva: la vuelve a consultar por su id);
   2. por cada modelo con cupo libre, elige el siguiente trabajo con **reparto justo**: como máximo **2 a la vez por negocio y modelo**, por turnos entre negocios (el que menos tiene en curso y lleva más tiempo esperando va primero), respetando el carril y el plazo;
   3. **reclama** el trabajo y el cupo por la puerta propia del worker (`creative_worker_session`, §2.6) con `FOR UPDATE SKIP LOCKED`;
   4. **todo lo demás lo hace dentro de `tenant_session(job.tenant_id)`**: leer la pieza, volver a pasar el guardián de precio y de cupo del plan antes de la llamada de pago, enviar, guardar el `vendor_task_id` **antes** de esperar, consultar, asentar el resultado;
   5. suelta el cupo cuando BytePlus da la tarea por terminada (éxito, falla o `expired`).
4. **Dos carriles por modelo, sin cobro:**
   - **Inmediato** (vista previa, regenerar, final pedido a mano): lo que el dueño espera en pantalla. Siempre tiene **2 cupos reservados** de Seedance que el carril nocturno no puede tomar de día.
   - **Nocturno** (final de una publicación programada): se envía entre las **00:00 y las 06:00** hora del negocio, con plazo. 10 a la vez × 6 h ÷ 60 s por final ≈ **3 600 finales por noche**. 1 000 negocios con el cupo agotado hacen ~6 400 finales al mes (4 / 8 / 16 por plan, mezcla 60/30/10): ~210 por noche, el 6 % de esa capacidad.
   - «Generar ya» con prioridad y costo extra **no se construye ahora**: es la Fase 2 (m-24852171), cuando la espera p95 en el pico pase de ~3–5 min.
5. **El plazo de un final nocturno** = el más temprano de: (a) la hora de publicación menos 12 h, para dejar al dueño una mañana para confirmarlo; (b) la creación del borrador + 7 días − 15 min (el id del borrador de BytePlus caduca a los 7 días, m-24852168). Si la publicación está a menos de ~12 h o no queda una noche antes del plazo, el final va al carril inmediato con prioridad, como hoy. Detalle y estados en el §3.
6. **La puerta del worker** es un rol nuevo, `qualify_creative_worker`, con su módulo `qualify_shared/db/creative_worker.py`, hermano de `webhook_worker_session` (migración 0050). **Sin BYPASSRLS**: una política RLS de solo ese rol en `creative_jobs` y GRANT por columna (las de la cola, nunca el contenido), y GRANT en `vendor_slots`. Ningún otro privilegio. Detalle, amenazas y mitigaciones en `docs/seguridad-creative-worker.md`.
7. **`dispatch.py` cambia de implementación, no de contrato.** `TaskDispatcher` ya prevé el cambio: un `QueueDispatcher` inserta en `creative_jobs` en lugar de lanzar un hilo, con la misma firma de dos UUID. `InlineDispatcher` queda solo para pruebas y desarrollo local sin el worker. El reaper pasa a contar desde que BytePlus empieza a hacer la tarea (`running`) y desde la concesión del cupo, no desde la creación de la fila (m-24852166).
8. **Idempotencia y procedencia** (regla 5): clave natural `UNIQUE (tenant_id, draft_id, kind, revision, position)`, de modo que pedir dos veces el mismo final no paga dos; `vendor_task_id` se escribe una sola vez y un trabajo con `vendor_task_id` nunca se vuelve a enviar, solo se consulta; cada fila guarda el modelo, la versión de la tabla de precios y `queued_at` / `submitted_at` / `running_at` / `finished_at` para medir (m-24852158).
9. **Visibilidad sin fuga entre negocios:** la app no puede contar los trabajos de otros negocios (RLS). El worker publica en Redis, por modelo, solo agregados (cupos ocupados, largo de la fila, espera estimada), sin ids ni negocios, como ya hace el latido de `calendar-worker`. El aviso «Tu video está en fila…» (m-24852170) lee eso.

## 3. Finales nocturnos con confirmación del dueño

### 3.1 Estados del final

El bloque `params["draft"]` de `image_assets` (`creative/draft_mode.py`) gana estados. El nombre en código va en inglés; lo que ve el dueño lo decide ux-designer con `qualify-copy-es`.

| Estado (`status`) | Qué significa | ¿Se publica? |
|---|---|---|
| `draft` | La vista previa a 480p, aprobada o por aprobar | No |
| `final_scheduled` | **Nuevo.** La vista previa está aprobada y la pieza programada; el final espera su noche en `creative_jobs` (carril nocturno, con plazo) | No |
| `rendering` | El final se está haciendo | No |
| `final_ready` | **Nuevo.** El final a 1080p está en R2, **esperando que el dueño lo confirme** | **No** |
| `final` | El dueño confirmó el final (`confirmed_by`, `confirmed_at`, `confirmed_sha256` del objeto confirmado) | Sí |
| `failed` | El final falló; se reintenta mientras viva el id del borrador | No |

Hoy `draft_pending(params)` = `status != "final"`, y el Planificador ya rechaza publicar un video pendiente (`R.MEDIA_DRAFT_PENDING` en `planner/publishable.py`). **Por eso la regla «nada se publica sin confirmación» queda en el dato, no en la pantalla:** `final_ready` es «pendiente» para el mismo guardián que ya existe. Se agrega un motivo propio, `R.MEDIA_FINAL_UNCONFIRMED`, para que el Planificador diga por qué no salió.

### 3.2 La confirmación

- Se confirma desde «Tu semana» (indicadores de ux-designer) o desde la ficha de la pieza: **una sola decisión**, «usar este video» o «volver a hacerlo».
- La confirmación queda atada **al objeto** que el dueño vio (`confirmed_sha256` y la clave de R2). Si el final se rehace, la confirmación anterior no vale y el estado vuelve a `final_ready`. El guardián de publicación compara el hash del objeto que va a publicar con el confirmado.
- La confirmación es por pieza y revisión, no por evento: una pieza recurrente se confirma una vez.
- Es la **segunda aprobación humana** de la regla 4 aplicada al archivo que de verdad se publica: la primera es el ángulo y la vista previa; la segunda, el final.

### 3.3 Qué pasa a la hora de publicar si no está confirmado

**No se publica.** El ejecutor del calendario ya trata un `NotPublishable` antes de reclamar como `NOT_READY` (`planner/executor.py`, `try_execute`): el evento **sigue `scheduled`**, no se crea intento de publicación y no se llama a Meta. Consecuencias, todas con piezas que ya existen:

1. Si el dueño confirma **dentro de la ventana de ejecución de 24 h** (`planner/rules.py`, `EXECUTION_WINDOW`), la publicación sale en la primera vuelta de `calendar-worker` después de confirmar (≤ 60 s), con retraso respecto de su hora.
2. Si pasan 24 h sin confirmar, el evento queda **«Venció»** (`BLOCKED_EXPIRED`, QUA-115) y hay que reprogramarlo. Nunca se publica tarde por su cuenta.
3. Si el final falló de noche y no se pudo rehacer antes de la hora, pasa lo mismo: no hay archivo confirmado, no se publica.
4. Avisos al dueño antes de llegar ahí (diseño de ux-designer, sin decidir aquí): indicador en «Tu semana» en cuanto el final está listo y un recordatorio unas horas antes de la publicación.

### 3.4 Cambio de comportamiento para el dueño

Hoy un video en borrador **no se puede programar** (el aviso de `MEDIA_DRAFT_PENDING` en la galería y en Crear pieza). Con este ADR **sí se puede programar con la vista previa aprobada**: el final se encola como `final_scheduled` en lugar de pedirse en ese momento. El final pedido a mano desde la pieza (sin programar) sigue yendo al carril inmediato, como hoy. **Punto abierto para el fundador:** si ese final inmediato también debe pasar por `final_ready` (la regla «ningún video se publica sin que alguien vea el final» sería entonces universal) o si basta con que el dueño lo vea aparecer en pantalla. La recomendación es universal: un estado menos que razonar en el guardián, y un toque más solo cuando el dueño ya está mirando la pieza.

## 4. Opciones consideradas

| Opción | Qué es | Costo | A favor | En contra | Veredicto |
|---|---|---|---|---|---|
| **A. Servicio nuevo `creative-worker`** + cola en Postgres | Un contenedor más de la imagen `app`, worker CLI en bucle | USD 0 de proveedor; ~150–250 MB de RAM en el VPS (hipótesis: un proceso de Python como `whatsapp-worker`, a medir); 0 minutos de Actions nuevos (misma imagen, ningún workflow nuevo) | Sobrevive a despliegues; un fallo de generación no toca la publicación; patrón ya probado en el repo (outbox + worker idempotente + puerta propia); despliegue y reinicio independientes | Un servicio más que vigilar (latido y avisos a Lark, m-24852167) | **Elegida** |
| B. Bucle dentro de `calendar-worker` | Otra tarea en el worker que publica | USD 0 y ningún contenedor nuevo | Lo más barato de operar | Mezcla esperas de hasta 40 min (OmniHuman) con el proceso que **publica de verdad**; un cuelgue o una fuga de memoria en la generación detiene las publicaciones; ese worker ya corre la purga de piezas (ADR 39); su vuelta es de 60 s | Descartada: el radio de daño cae sobre lo más delicado |
| C. Hilos + semáforo en el proceso de la app | Un `threading.Semaphore(10)` alrededor de `InlineDispatcher` | USD 0, esfuerzo XS | Arregla el tope dentro de un proceso | No coordina entre procesos (API, Reflex, evaluaciones); muere en cada despliegue con lo que tenía en curso; no guarda la fila ni el reparto justo; no permite carril nocturno ni medir la espera | Descartada: no arregla la durabilidad, que es la mitad del problema |
| D. Celery con Redis de cola | Lo que `dispatch.py` llamaba `CeleryDispatcher` | Un runtime nuevo y Redis como cola (Redis hoy es caché y latido) | Ecosistema conocido, reintentos de serie | ADR 31 y la regla de la casa: sin Celery ni cola nueva sin tabla de opciones; los límites de Celery son por worker, no globales, así que el semáforo de 10 y el reparto justo se escriben igual; dos fuentes de verdad (cola en Redis, estado en Postgres) | Descartada |

## 5. Encaje con ADR 31

- **Ningún almacén nuevo.** La cola y el semáforo son dos tablas del Postgres que ya corre, creadas por Alembic (`qualify-migration`, m-24852160). Redis solo para los agregados de visibilidad y el latido, como ya hace `calendar-worker`; si Redis cae, la cola sigue funcionando y solo se pierde el aviso de espera.
- **Volumen** (de la simulación, 38,4 tareas por negocio al mes con el cupo entero): con uso típico, ~19 filas por negocio al mes → **~23 000 filas al año a 100 negocios** y **~230 000 a 1 000**. Las vueltas del worker son una consulta indexada cada 2 s. Ninguna se acerca a los umbrales de ADR 31.
- **Borrado:** las filas terminadas se pueden purgar a los 90 días (como las piezas, ADR 39); la procedencia del video queda en `image_assets`.

## 6. Consecuencias

- **Positivas.** Ningún video pagado se pierde por esperar (la tarea se consulta por su id hasta 48 h). La fila es nuestra: reparto justo, espera visible y carril nocturno. Los finales salen del pico del día: son el **83 % del costo** y nadie los espera en pantalla. El final que se publica siempre lo vio el dueño.
- **Negativas.** Un servicio más en producción. Una pieza programada pasa a depender de que el dueño confirme a tiempo: si no confirma, no se publica, y eso se verá como «no salió» si los avisos de ux-designer no llegan bien. Un estado más en el bloque del borrador y un motivo más en el guardián de publicación.
- **No crea capacidad.** A 1 000 negocios el viernes sigue habiendo 35–52 min de espera; solo deja de fallar y de cobrarse, y se ve. La capacidad viene del ticket a BytePlus (hacia los 100 negocios) y, como último recurso, de varias cuentas (m-24852174, solo con el visto bueno escrito de BytePlus).
- **Desarrollo y evaluaciones comparten las 10** con producción. Las evaluaciones con video corren fuera del horario de los comercios; el worker deja un margen configurable (por defecto 0) para restar cupos cuando haya una evaluación grande.
- **Cambia el contrato de seguridad:** un rol nuevo con lectura entre negocios, acotada. Ver `docs/seguridad-creative-worker.md`.

## 7. Qué lo reabriría

- La consulta de reclamo pasa de **1 s en p95** o la tabla genera bloqueos visibles en Postgres (más de ~50 reclamos por segundo): mirar `LISTEN/NOTIFY` primero y, solo si no alcanza, una cola dedicada con su tabla de opciones.
- Hace falta más de una máquina para los workers (el semáforo en Postgres funciona igual, pero el costo de red y la latencia del reclamo cambian).
- BytePlus ofrece un modo diferido con descuento para Seedance 2.5: el carril nocturno pasaría a ese modo y «agendar» sí tendría ahorro que trasladar.
- BytePlus sube el cupo a un número que hace innecesario el reparto justo para nuestra escala (p. ej. 100 a la vez).
- La confirmación del final resulta un freno medido (publicaciones que vencen sin confirmar por encima del ~5 % durante un mes): replantear el estado `final_ready` con el fundador.
