# Recuperar videos de BytePlus sin depender de una pantalla (m-24852492)

**Estado:** construido en la rama `fix/m-24852492-recuperar-sin-pantalla` (2026-10-25). Sigue al
PR #325 (m-24852154), que guarda cada tarea de Seedance por id en `creative_vendor_tasks`.

## El problema

Desde el PR #325, un video que BytePlus termina después de la espera se recupera, pero solo
cuando una pantalla lee borradores (`ContentService._sweep`: `get_draft`, `get_drafts`,
`list_drafts`). Si nadie abre Qualify durante más de 24 h después de que BytePlus entrega,
la `video_url` vence, la ejecución reanudada falla y devuelve las creaciones al negocio,
**pero BytePlus ya cobró el video**.

## Qué hace ahora

Un paso de recuperación corre solo, cada `RECOVERY_EVERY_SECONDS` (60 s), al lado de los
ticks del Planificador (`calendar-worker`; también en el worker embebido). Código:
`packages/api/src/qualify_api/creative/vendor_recovery.py`, función `recover_once`.

1. **Descubrimiento** (`discover_tenants`, solo con `--all-tenants`): ids de negocios con un
   borrador `drafting` callado más de 3 min (`RECOVER_AFTER_QUIET_MINUTES`). Lectura con
   `admin_session`, solo ids, sin permisos nuevos (`qualify_admin` ya lee `content_drafts`
   desde 0009), mismos términos que `planner/discovery.py`. Con `--tenant` no hay lectura
   entre negocios.
2. Por negocio, dentro de su `tenant_session`: el segador (`reap_stale_drafts`: una tarea de
   más de 49 h se da por perdida, la pieza falla y se reembolsa) y los borradores callados con
   tareas pendientes de su revisión actual.
3. **Pregunta a BytePlus por id** (`get_task`) por cada tarea pendiente. `queued`/`running` →
   nada esta vuelta (reanudar solo dejaría un hilo esperando). Todas terminadas
   (`succeeded`, `failed`/`cancelled`/`expired`, o desconocida = 404) → paso 4.
4. **Reclama** el borrador de forma atómica (`claim_waiting_drafts(draft_ids=…)`, el mismo
   `UPDATE … RETURNING` que usa la pantalla: la pantalla y el worker nunca reanudan el mismo
   borrador) y lo **reanuda** con `ContentService.run_generation`: espera las tareas (ya
   terminadas: responde a la primera consulta), rehace la pieza con el copy guardado, guarda
   el video en R2 y asienta su costo una sola vez; o falla la pieza y devuelve las creaciones.

La reanudación corre en el hilo del paso, nunca en el tick: una vuelta lenta no atrasa
ninguna publicación, y no hay dos vueltas a la vez en el mismo proceso
(`planner.worker.run_worker`, parámetro `sidecar`). Dos procesos a la vez son seguros por el
reclamo y la idempotencia de `run_generation`.

**Tiempo:** un video entregado queda en la pieza en unos 4 min (3 min de silencio + hasta 60 s
de intervalo), muy por debajo de las 24 h de la URL y de los 10 min del ticket (test
`test_a_delivered_video_is_recovered_within_ten_minutes`).

**Memoria:** el servicio de contenido (copy, medios, Remotion, PyAV) se arma solo la primera
vez que de verdad se reanuda un borrador; la mayoría de las vueltas no lo necesita. El
contenedor `calendar-worker` tiene 320 MiB (107 MiB medidos en reposo): conviene mirar su
memoria tras la primera recuperación real.

**Interruptor:** `QUALIFY_VENDOR_RECOVERY=off` apaga el paso (se lee en cada vuelta). Por
defecto está encendido.

**Pasar a `creative-worker`** (ADR 41, m-24852163): el día que exista, llama a
`recovery_chore(scope)` (o a `recover_once` con sus propias piezas) en su bucle y el
Planificador deja de pasarle `sidecar`. Nada más cambia.

## Informe de conciliación

```bash
just creative-tasks-report --tenant <uuid> [--days 7] [--json]   # en local
just creative-tasks-report --all-tenants [--days 7] [--json]     # en PROD
```

Solo lee: nuestras filas de `creative_vendor_tasks` (cada negocio en su `tenant_session`) y
el listado de tareas de video de la cuenta (`SeedanceVideoAdapter.list_tasks`, un GET). Muestra:

- **cobradas por BytePlus y no recogidas**: BytePlus dice `succeeded` y nuestra fila sigue
  `pending` (el paso debería recogerla en minutos) o quedó `failed` (video pagado perdido);
- **tareas sin pieza**: BytePlus las lista y no tenemos fila (solo con `--all-tenants`; las
  pruebas a mano con la misma clave —arkcli, el playground— también caen aquí);
- **piezas sin tarea**: una fila cuya tarea BytePlus no lista en la ventana.

Código de salida: 0 limpio, 2 hay algo que mirar, 1 no pudo correr. No envía ni paga nada.

## Lo que NO está verificado en vivo (regla 6)

- **Forma del listado de BytePlus** (`GET /contents/generations/tasks?page_num=&page_size=`,
  respuesta `{"items": [{"id", "model", "status", "created_at"}], "total"}`, `created_at` en
  segundos Unix, `page_size` máx. 500): tomada de la documentación «Query video generation
  task list», no probada contra la API. Prueba: `just creative-tasks-report --all-tenants
  --days 7 --json` en PROD y comparar con `arkcli gen list` de los mismos días.
- **Tarea desconocida**: se asume HTTP 404 o un código con `NotFound` en `get_task`. Si BytePlus
  responde otra cosa, el paso la trata como error y no la reanuda (queda para el segador a las 49 h).

## Fuera de alcance

- OmniHuman (Issue aparte), `callback_url` de BytePlus, imágenes de Seedream de un carrusel.
- Las versiones finales a 1080p (`final:<asset>`): el paso solo mira borradores `drafting`.
- Avisar al equipo por Lark: hoy los hallazgos quedan en el registro (`creative.recovery.*`) y en
  el informe; no hay mensaje automático.
