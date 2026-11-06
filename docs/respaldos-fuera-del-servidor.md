# Respaldos fuera del servidor (R2 + age)

`[VIGENTE 2026-11-05 · m-24824122]` · Dueño: plataforma. Complementa
[`despliegue-hetzner.md`](despliegue-hetzner.md) §8 (el `pg_dump` local).

> **Pendiente del fundador antes del primer respaldo:** §3, crear la llave y subir la pública.
> Mientras no esté, no se sube nada y cada noche llega una alerta al canal del equipo.

## 1. Qué se respalda y dónde

Cada noche, el cron de las 03:15 UTC corre `deploy/backup-db.sh`. Ese script hace el
`pg_dump` local de siempre y al terminar llama a `deploy/backup-offsite.sh`, que sube a R2:

| Objeto en R2 | Qué es |
|---|---|
| `backups/<respaldo>/qualify.dump.age` | el `pg_dump -Fc` de esa corrida |
| `backups/<respaldo>/globals.sql.age` | los roles (`pg_dumpall --roles-only`) |
| `backups/<respaldo>/uploads.tar.age` | el volumen `qualify-prod_uploads`: fotos y videos del catálogo, archivos subidos al generador y documentos de marca |
| `backups/<respaldo>/MANIFEST.json` | tamaños y sha256; se escribe al final, y un respaldo sin manifiesto está incompleto |

`<respaldo>` es la hora UTC de inicio, por ejemplo `20261106T031500Z`. Cada corrida crea uno nuevo,
así que un `just deploy-backup` manual el mismo día nunca pisa el de la noche.

- **Bucket:** el de la app (`QUALIFY_R2_BUCKET`), bajo `backups/`, fuera del espacio de los negocios
  (`t/{tenant}/`). Se puede usar otro bucket con su propio token (`QUALIFY_BACKUP_R2_*`, §6).
- **Cifrado:** `age`, con la llave **pública** `QUALIFY_BACKUP_AGE_RECIPIENT`. La privada no está en
  el servidor. Sin llave pública no se sube nada.
- **Cómo:** todo corre con `docker exec` dentro del contenedor `api` de `qualify-prod`. Ese
  contenedor ya tiene las credenciales de R2, el volumen montado y `age`, que va en la imagen. El
  script no toca contenedores ni volúmenes de otro proyecto (Pedidos).
- **Retención:** todos los respaldos de las últimas 2 semanas, más el último de cada semana de las
  últimas 8. Uno incompleto se borra a los 2 días. El último respaldo completo nunca se
  borra. La copia local sigue siendo de 14 días.
- **Lo que no entra:** `avatars` (caché de fotos de perfil, se vuelve a bajar), `reflex_states`
  (sesiones: perderlas solo cierra sesión), `redisdata`, `renders` (24 h). Las piezas generadas y el
  Brand Kit ya viven en R2.

## 2. Costo

Medido en el servidor el 2026-11-05: `du -sh` da **18 MB** en `/data/uploaded_files` y **617 MB** en
`/opt/qualify/backups` (14 noches), unos **44 MB por dump** `[V]`. Cada día ocupa unos **62 MB**
(las fotos y videos ya vienen comprimidos, así que el tar no se comprime). Con unos 22 días
guardados como máximo, eso es **~1,4 GB** `[V tamaño, H crecimiento]`.

R2 Standard: 10 GB-mes gratis por cuenta, luego US$0,015/GB-mes; 1 M de operaciones de escritura
gratis al mes; salida gratis `[S: tarifa pública de Cloudflare, no reverificada hoy]`. Este respaldo
hace unas 10 escrituras por noche. **Costo: US$0/mes** dentro del nivel gratis. Si la cuenta ya pasó
los 10 GB, son unos US$0,02/mes. Con 10 veces más datos (~14 GB), entre US$0,06 y US$0,21/mes,
según cuánto del nivel gratis use ya la app `[H]`. No usa minutos de Actions: corre en el cron
del servidor.

## 3. Llave de cifrado (una vez, en el Mac del fundador)

```bash
brew install age
age-keygen -o ~/qualify-backup.agekey      # imprime "Public key: age1…"
```

1. Guardar `~/qualify-backup.agekey` (la **privada**) en el gestor de contraseñas y borrar el
   archivo del disco. Sin ella no se puede restaurar nada.
2. Poner la pública en el `.env` local: `QUALIFY_BACKUP_AGE_RECIPIENT=age1…`.
3. `just env-push qualify-prod --dry-run QUALIFY_BACKUP_AGE_RECIPIENT` y luego sin `--dry-run`.
   Es una variable nueva en `.env.prod`, así que la sube el fundador o un agente con su sí. No es un
   secreto, pero quien la cambie decide quién puede leer los respaldos.

Para rotarla: generar otra llave, subir la nueva pública y guardar la privada vieja mientras
queden respaldos cifrados con ella (8 semanas). Se pueden poner dos llaves separadas por coma, por
ejemplo una del fundador y otra del cofundador.

## 4. Si falla

`backup-offsite.sh` sale con código distinto de 0. Escribe `backup-offsite: FAILED at '<paso>'` en
`/opt/qualify/backups/backup.log` y manda un mensaje al canal del equipo
(`QUALIFY_SUPPORT_WEBHOOK_URL`). El `pg_dump` local ya quedó escrito antes de esto. Si todo sale
bien, se actualiza `/opt/qualify/backups/offsite.ok`, y `just deploy-status qualify-prod` muestra
`off-site backup (R2) … Nh ago`: `WARN` si pasan más de 30 h o si nunca se completó. Eso no hace
fallar un deploy. Para desactivarlo en una emergencia, poner `QUALIFY_BACKUP_OFFSITE=off` en el
entorno del cron.

Causas probables y qué hacer:

| Paso que falló | Causa probable | Qué hacer |
|---|---|---|
| `check` | falta `QUALIFY_BACKUP_AGE_RECIPIENT`, o R2 no responde | §3; si la llave está, revisar las credenciales de R2 |
| `locate api` | el contenedor `api` está caído | `just deploy-status qualify-prod` y avisar al fundador |
| `put …` con «MiB free» | quedan menos de 1 GB libres en el disco del servidor (compartido con Postgres y Pedidos) | liberar espacio; el respaldo se detiene antes de llenar el disco |
| `put …` o `finish` | red o R2 | se reintenta sola la noche siguiente; si se repite, revisar R2 |

Un respaldo que falla a la mitad queda incompleto (sin manifiesto): no se usa para restaurar y se
borra a los 2 días.

## 5. Simulacro de restauración (paso a paso)

Se hace en un Postgres **desechable**, nunca sobre producción. Restaurar en producción es la
sección «Restaurar un respaldo» de `despliegue-hetzner.md` §8 y la pide el fundador.

1. **Ver qué hay** (desde el checkout principal, con las llaves de R2 de producción en el `.env`
   local, las mismas que usa `env-push`):

   ```bash
   just offsite-backup list
   ```

2. **Bajar los tres objetos** del respaldo elegido (el valor `snapshot` de la lista):

   ```bash
   d=20261106T031500Z; mkdir -p ~/restore-$d && cd ~/restore-$d
   for f in qualify.dump globals.sql uploads.tar; do
     (cd ~/dev/Qualify && just offsite-backup get backups/$d/$f.age) > $f.age
   done
   ```

3. **Descifrar** con la llave privada, que se saca un momento del gestor de contraseñas y se
   borra después:

   ```bash
   for f in qualify.dump globals.sql uploads.tar; do age -d -i ~/qualify-backup.agekey -o $f $f.age; done
   ```

4. **Restaurar Postgres en un contenedor desechable**, sin puertos publicados:

   ```bash
   docker run -d --name restore-pg -e POSTGRES_DB=qualify -e POSTGRES_USER=qualify_owner \
     -e POSTGRES_PASSWORD=desechable pgvector/pgvector:pg16
   sleep 5
   docker exec -i restore-pg psql -U qualify_owner -d postgres < globals.sql   # «qualify_owner ya existe»: ignorar
   docker exec -i restore-pg pg_restore -U qualify_owner -d qualify --exit-on-error < qualify.dump
   docker exec restore-pg psql -U qualify_owner -d qualify -Atc \
     "select version_num from alembic_version; select count(*) from pg_policies; select count(*) from tenants"
   ```

   Comprobar que `alembic_version` es la de producción, que hay políticas RLS y que están los
   negocios.

5. **Uploads:** `mkdir uploads && tar -C uploads -xf uploads.tar`. Abrir una foto de un producto
   (`uploads/uploads/<tenant>/catalog/<producto>/…jpg`) y comparar con `product_media.object_key`
   de la base restaurada.

6. **Limpiar:** `docker rm -f restore-pg`, borrar `~/restore-$d` y la llave privada del disco.

7. **Anotar** la fecha, el día restaurado y el resultado en la tabla de §7.

**En un servidor nuevo** (si se perdió el VPS): después de `bootstrap-server.sh` y el primer deploy,
se restaura la base con §8 de `despliegue-hetzner.md`, usando el `qualify.dump` y el `globals.sql`
descifrados. Los uploads se cargan con
`docker exec -i <api> tar -C /data/uploaded_files -xf - < uploads.tar`. Eso escribe en producción,
así que lo pide el fundador.

## 6. Límites conocidos

- **El mismo token de la app puede borrar los respaldos.** Si alguien roba el token de R2, puede
  leer lo cifrado (no lo puede abrir sin la llave privada) y también borrarlo. La mejora, que
  todavía no se hizo, es un bucket `qualify-backups` con un token **de solo escritura** y retención
  por reglas de ciclo de vida de R2 (`QUALIFY_BACKUP_R2_BUCKET`, `_ACCESS_KEY_ID`,
  `_SECRET_ACCESS_KEY`, `QUALIFY_BACKUP_PRUNE=off`). No necesita cambios de código, pero sí crear el
  token, que hace el fundador.
- Cada objeto se sube con un solo PUT, después de cifrarlo en `/tmp` del contenedor. El límite de
  R2 es de 5 GB por objeto, y el disco necesita libre el tamaño del tar más 1 GB de reserva
  (`QUALIFY_BACKUP_MIN_FREE_MB`); si no alcanza, se detiene y avisa. Hoy son 18 MB.
- `just offsite-backup get` carga el objeto entero en memoria del Mac antes de escribirlo. Con
  ~45 MB no importa; si los respaldos llegan a varios GB, conviene cambiarlo a lectura por partes. Cuando las
  fotos del catálogo pasen a R2 (CM-9, épica m-24955913), el tar se achica solo.
- Pérdida máxima de datos: 24 h (un respaldo por noche). Restaurar la base y los uploads lleva
  menos de 1 h con estos tamaños `[H]`.

## 7. Simulacros hechos

| Fecha | Dónde | Resultado |
|---|---|---|
| 2026-11-05 (03:28 UTC del 06) | Local (Mac): imagen `deps` de Qualify + `age` 1.1.1 de Debian bookworm, dos `pgvector:pg16` desechables en una red sin salida, un contenedor «api» con las mismas etiquetas de compose, y un directorio en lugar de R2 (`QUALIFY_BACKUP_LOCAL_DIR`). Se repitió después de la revisión de código | `backup-offsite.sh` real: 3 objetos cifrados (`age-encryption.org/v1`) y el manifiesto. La primera corrida se detuvo bien, con alerta, porque la máquina virtual de Docker tenía 1,3 GB libres: la reserva de disco funciona. Al descifrar, el dump es idéntico byte a byte; `pg_restore` recupera la fila, `alembic_version`, la política RLS y el rol; la foto del tar es idéntica. **OK.** El simulacro contra R2 real queda para después del primer respaldo en producción. |
