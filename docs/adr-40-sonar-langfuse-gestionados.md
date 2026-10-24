# ADR 40 — SonarQube y Langfuse pasan a sus nubes gestionadas

`[APROBADO — decisión del fundador 2026-10-24 · m-24852185]` · Origen: la tabla de opciones de
[`offboarding-desarrollador.md` §7.2](offboarding-desarrollador.md) (PR #311, m-24852090). Épica
de Langfuse: m-24852178. Resumen en [`arquitectura.md` §6](arquitectura.md), fila 40.

## 1. Contexto

SonarQube (Community Build) y Langfuse (v4 autoalojado, `infra/langfuse/`) corrían solo en la
máquina de un desarrollador (Deivid). Si esa persona se va o su equipo falla, se pierden el
historial de evaluaciones que exige `qualify-measure` y el de Sonar, y nadie más puede correr
`just eval-*` contra los mismos datos. Producción no depende de ninguno de los dos: el VPS no tiene
claves `LANGFUSE_*` y el workflow `sonar` sale *skipped* sin `SONAR_ENABLED`.

El repo `AttitudeFactory/Qualify` es **público desde el 2026-10-24**, lo que hace gratis a
SonarQube Cloud y a los minutos de Actions en *runners* estándar.

## 2. Opciones consideradas

| Opción | SonarQube | Langfuse | Por qué no / por qué sí |
|---|---|---|---|
| **A. Dejarlo en la máquina de Deivid + exportación periódica** | Reanalizar `main` cuando haga falta | `pg_dump` + copia de ClickHouse/MinIO a R2 cada semana | $0, pero sigue siendo de una persona: solo reduce la pérdida. Nadie más ve las trazas. |
| **B. En el VPS de Hetzner** | Community Build detrás del Caddy compartido | Los seis contenedores de Langfuse v4 | No cabe: medido 1,4 GB de RAM libres de 4 GB; Langfuse pide 16 GB y Sonar 4 GB libres y un `sysctl` del host. El VPS es compartido con Pedidos, que pagaría la carga y el corte del Caddy. Agrandar cuesta del orden de 15–30 €/mes. |
| **C. Gestionado (elegida para los dos)** | **SonarQube Cloud**, plan gratis mientras el repo sea público; analiza ramas y PRs (la Community Build no) | **Langfuse Cloud, región EU**, plan *Hobby* ($0: ≈50 000 unidades/mes, 30 días de datos, 2 usuarios) | Quita la dependencia de una persona, cuesta $0 y no toca el VPS. A cambio: un proveedor nuevo que, en el caso de Langfuse, verá textos de clientes si algún día se le mandan trazas de producción. |

## 3. Decisión

1. **SonarQube → SonarQube Cloud** (`https://sonarcloud.io`), organización ligada a la
   organización de GitHub `AttitudeFactory`. Solo ve código, que ya es público. Si el repo vuelve a
   privado, se apaga (`SONAR_ENABLED` fuera): `semgrep` + `bandit` del workflow `security` cubren
   lo esencial.
2. **Langfuse → Langfuse Cloud, región EU** (`https://cloud.langfuse.com`, AWS `eu-west-1`,
   Irlanda — no Fráncfort, como decía la tabla del §7.2 antes de esta revisión), organización
   «Attitude Factory», proyectos `qualify-dev` y `qualify-prod` (épica m-24852178).
3. **Esta decisión no habilita las trazas de producción.** Mandarlas (m-24852181) espera a que el
   fundador revise el DPA y decida qué datos de clientes pueden salir. Hasta entonces solo se usa
   `qualify-dev`, para evaluaciones y pruebas locales.

## 4. Lo que cambia en el repo (este PR)

- `.github/workflows/sonar.yml`: apunta a SonarQube Cloud (`SONAR_HOST_URL=https://sonarcloud.io`
  como valor fijo, ya no es secreto), acciones fijadas por SHA (antes iban por etiqueta) y la misma
  puerta: sin la variable `SONAR_ENABLED=true` el job no arranca y no gasta minutos.
- `sonar-project.properties`: `sonar.organization=attitudefactory` y
  `sonar.projectKey=AttitudeFactory_Qualify`. Son **marcadores**: las claves que SonarQube Cloud
  propone por defecto al importar desde GitHub. Si la pantalla de importación muestra otras, se
  copian ahí; con una clave distinta el análisis falla con «project not found».
- `infra/sonarqube/README.md` queda marcado como retirado; se borra junto con
  `infra/sonarqube/` cuando SonarQube Cloud haya analizado `main` una vez.
- `.env.example`: el bloque de Langfuse documenta el host EU.

**Minutos de Actions.** Un job de ≈3–4 min (instalar dependencias, la suite offline para la
cobertura y el análisis) por cada push a `main` que toque código. Con el repo público los
*runners* estándar no se facturan («GitHub Actions usage is free for self-hosted runners and for
public repositories that use standard GitHub-hosted runners», docs de GitHub, 2026-10-24). Si el
repo vuelve a privado serían ≈3–4 min facturados por merge de código contra los 2 000/mes de
GitHub Free: entonces se apaga. El análisis de PRs que ofrece SonarQube Cloud **no** se enciende
en este PR; sumarlo es un cambio aparte que declara su costo.

## 5. Cómo leen la app y las evaluaciones las variables de Langfuse

Verificado en el código y en el SDK instalado (`langfuse` 4.18.0) el 2026-10-24:

- **Una sola puerta**: `packages/shared/src/qualify_shared/observability.py` crea
  `Langfuse(mask=_mask)` solo si existen `LANGFUSE_PUBLIC_KEY` y `LANGFUSE_SECRET_KEY`; sin ellas
  todo es un no-op. El host, `LANGFUSE_TRACING_ENVIRONMENT` y `LANGFUSE_RELEASE` los lee el SDK
  directamente del entorno.
- **El host lo da `LANGFUSE_BASE_URL`.** `LANGFUSE_HOST` está deprecado en el SDK.
  **Ojo: si `LANGFUSE_BASE_URL` falta, el SDK usa `https://cloud.langfuse.com`** (su valor por
  defecto, la región EU). Con claves de Cloud y sin host, las trazas van a Cloud EU; con claves
  del Langfuse local y sin host, fallan la autenticación (no se pierde nada, pero no se traza).
- **Evaluaciones** (`packages/api/evals/*/run_experiment.py`): cargan el `.env` de la app sin
  pisar lo que ya trae la terminal y fijan `LANGFUSE_TRACING_ENVIRONMENT=eval`.
  `scenes_ai/export_images.py` lee las tres variables del entorno o de `--env-file`.
  `just langfuse-setup` usa `--env-file .env`. Ninguna tiene `localhost` escrito en el código.
- **Tests**: `conftest.py` borra las claves en cada test, así que ni la suite ni CI mandan trazas.
- **Lo único atado al Langfuse local**: `just langfuse-up` comprueba la salud en
  `http://localhost:3100` y `infra/langfuse/`. Siguen sirviendo para quien quiera un servidor
  local; para Cloud no se usan.

Para apuntar una máquina a Cloud EU (cuando el fundador entregue las claves de `qualify-dev`),
en el `.env` local, nunca en el repo:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...      # de qualify-dev
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
```

## 6. Qué hay en el Langfuse de Deivid y qué hay que mover

| Dato | ¿Existe ya fuera de su máquina? | Qué se hace |
|---|---|---|
| **Datasets** (`copy-generador`, `brand-kit-documentos`, `escenas-imagen`, `voz-transcripcion`, `referentes-revisar` y los de hashtags y pilotos) | Sí: los casos están versionados en `packages/api/evals/*/cases*.json` y en `qualify_api/evals/` | Se exportan e importan con sus ids (paso 3 del §8): así los experimentos nuevos se comparan contra los mismos ítems. |
| **Configuraciones de puntuación y la cola «Revisión de imagen y video»** | Sí: las crea `just langfuse-setup`, idempotente | Se recrean con `just langfuse-setup` contra Cloud. No se importan. |
| **Prompts** | No se usan: el código no llama a la gestión de prompts de Langfuse | Se exporta la lista por si alguien creó alguno a mano; si sale vacía, no hay nada que mover. |
| **Resúmenes de experimentos** | Sí: `packages/api/evals/*/results/*.json` están en git | Nada. |
| **Detalle de cada experimento** (entrada, salida, puntuaciones por ítem) y **anotaciones humanas** de la cola | **No: solo en su máquina** | Se exportan a JSON como archivo histórico. Langfuse no tiene una API para importar corridas de experimentos ni anotaciones; si hace falta compararlas en Cloud, se vuelve a correr el experimento (cuesta llamadas reales a Claude). |
| Trazas de desarrollo sueltas | No | No se migran (fuera de alcance de la épica). |

## 7. Pasos del fundador

Todo lo que pide su cuenta, su firma o un secreto. En este orden.

**SonarQube Cloud**

- [ ] Entrar en <https://sonarcloud.io> con la cuenta de GitHub del fundador → *Import an
      organization* → elegir **AttitudeFactory**, instalar la app de SonarQube Cloud en esa
      organización **solo para el repo `Qualify`**, región EU, plan **Free**.
- [ ] Confirmar la clave de la organización y la del proyecto que proponga la pantalla. Si no son
      `attitudefactory` y `AttitudeFactory_Qualify`, pasárselas a un agente para que cambie
      `sonar-project.properties` (un PR de una línea).
- [ ] Importar el proyecto `Qualify`; código nuevo = *Previous version*.
- [ ] En el proyecto: *Administration → Analysis Method* → **apagar Automatic Analysis** (si queda
      encendido, el análisis de CI falla) y elegir GitHub Actions.
- [ ] Generar el token (*My Account → Security*, con vencimiento) y subirlo sin pegarlo en ningún
      comando: `gh secret set SONAR_TOKEN --repo AttitudeFactory/Qualify` (lo pide por la terminal).
- [ ] Encender: `gh variable set SONAR_ENABLED --body true --repo AttitudeFactory/Qualify`.
- [ ] Lanzar el primer análisis: `gh workflow run sonar --ref main --repo AttitudeFactory/Qualify`
      y abrir el enlace del resumen del run.
- [ ] Avisar a Deivid de que puede apagar su Sonar local (`docker compose down -v` en
      `infra/sonarqube/`), y pedir el PR que borra `infra/sonarqube/`.

**Langfuse Cloud** (coincide con m-24852180 de la épica)

- [ ] Crear la cuenta en <https://cloud.langfuse.com> (región **EU**) con el correo de la empresa;
      organización «Attitude Factory», plan **Hobby**, sin tarjeta.
- [ ] **Revisar el DPA antes de subir ningún dato.** `langfuse.com/dpa` lleva al *Data Processing
      Addendum* de ClickHouse (dueña de Langfuse): forma parte del contrato que se acepta al
      registrarse, no tiene firma aparte, incluye las cláusulas tipo de la UE y la lista de
      subencargados (se avisa de cambios con antelación; hay 10 días para objetar). Decidir si los
      datasets — que incluyen cuentas reales de referentes e imágenes generadas — y, más adelante,
      las trazas de producción pueden salir. Si la respuesta es no, parar aquí.
- [ ] Crear los proyectos `qualify-dev` y `qualify-prod`. Las claves de `qualify-prod` **no** se
      generan ni se suben al VPS hasta decidir m-24852181.
- [ ] Invitar a Deivid (el segundo usuario del plan).
- [ ] Generar las claves de `qualify-dev` y dárselas a Deivid por un canal privado (nunca en
      Meegle, el repo ni un grupo).
- [ ] Acordar con Deivid el día de la exportación (§8). La corre **Deivid** en su máquina;
      **Herwin** coordina, recibe el archivo y comprueba los conteos.
- [ ] Guardar el archivo de la exportación en un sitio privado del fundador (no en el repo: lleva
      salidas de modelos y cuentas reales).
- [ ] Con los conteos comprobados en Cloud, autorizar a Deivid a borrar su instancia local (§8,
      paso 6).

## 8. Exportar el Langfuse de Deivid e importarlo en Cloud

Lo corre Deivid en su máquina, con su Langfuse levantado (`just langfuse-up`). Endpoints y
campos de paginación (`meta.totalPages`, `meta.cursor`) verificados el 2026-10-24 contra la
referencia de la API pública (`api.reference.langfuse.com`) y los tipos del SDK 4.18;
su servidor es v4.58, así que tiene las APIs nuevas (`experiment-items`, `v3/scores`). Ningún
comando lleva una clave escrita: se leen de archivos con `set -a; . archivo`.

**Paso 0 — preparar.** Carpeta de trabajo fuera del repo y credenciales de las dos puntas:

```bash
mkdir -p ~/langfuse-export && cd ~/langfuse-export
# Local: las claves del proyecto local están en infra/langfuse/.env del repo.
set -a; . ~/ruta/al/repo/Qualify/infra/langfuse/.env; set +a
LOCAL=http://localhost:3100
LAUTH="$LANGFUSE_INIT_PROJECT_PUBLIC_KEY:$LANGFUSE_INIT_PROJECT_SECRET_KEY"
```

**Paso 1 — respaldo en frío** (por si algo sale mal; no se sube a ningún lado):

```bash
docker compose -f ~/ruta/al/repo/Qualify/infra/langfuse/docker-compose.yml exec -T postgres \
  pg_dump -U postgres postgres > langfuse-postgres.sql
```

**Paso 2 — exportar** (solo lectura):

```bash
get() { curl -fsS -u "$LAUTH" "$LOCAL$1"; }
get "/api/public/v2/datasets?limit=100"          > datasets.json
get "/api/public/v2/prompts?limit=100"           > prompts.json
get "/api/public/score-configs?limit=100"        > score-configs.json
get "/api/public/annotation-queues?limit=100"    > annotation-queues.json
# Ítems de cada dataset (paginado de 100 en 100)
for name in $(jq -r '.data[].name' datasets.json); do
  page=1
  while :; do
    get "/api/public/dataset-items?datasetName=$(jq -rn --arg n "$name" '$n|@uri')&limit=100&page=$page" \
      > "items-$name-$page.json"
    [ "$(jq '.meta.totalPages' "items-$name-$page.json")" -le "$page" ] && break
    page=$((page+1))
  done
done
# Detalle de experimentos con entradas, salidas y puntuaciones (cursor)
cursor=""; n=1
while :; do
  get "/api/public/experiment-items?fromStartTime=2026-01-01T00:00:00Z&limit=100&fields=core,dataset,io,metadata,scores${cursor:+&cursor=$cursor}" \
    > "experiment-items-$n.json"
  cursor=$(jq -r '.meta.cursor // empty' "experiment-items-$n.json")
  [ -z "$cursor" ] && break; n=$((n+1))
done
# Todas las puntuaciones, incluidas las anotaciones humanas de la cola
cursor=""; n=1
while :; do
  get "/api/public/v3/scores?limit=100&fields=details,subject,annotation${cursor:+&cursor=$cursor}" \
    > "scores-$n.json"
  cursor=$(jq -r '.meta.cursor // empty' "scores-$n.json")
  [ -z "$cursor" ] && break; n=$((n+1))
done
```

Si una respuesta no trae lo esperado (otra versión del servidor), ajustar el `jq` y repetir: este
paso solo lee, no hay nada que deshacer.

**Paso 3 — importar en `qualify-dev`** (Cloud EU). Las claves de Cloud en un archivo propio,
`~/langfuse-export/cloud.env`, con `LANGFUSE_PUBLIC_KEY` y `LANGFUSE_SECRET_KEY`:

```bash
set -a; . ~/langfuse-export/cloud.env; set +a
CLOUD=https://cloud.langfuse.com
CAUTH="$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY"
post() { curl -fsS -u "$CAUTH" -H 'Content-Type: application/json' -X POST "$CLOUD$1" -d @-; }
# Datasets: mismo nombre, descripción y metadatos
jq -c '.data[] | {name, description, metadata}' datasets.json | while read -r d; do
  printf '%s' "$d" | post /api/public/v2/datasets >/dev/null
done
# Ítems: se conserva el id, así repetir el paso no duplica (el id actualiza el ítem)
cat items-*.json | jq -c '.data[] | {id, datasetName, input, expectedOutput, metadata,
  sourceTraceId: null, sourceObservationId: null, status}' | while read -r it; do
  printf '%s' "$it" | post /api/public/dataset-items >/dev/null
done
```

Los ítems se importan sin `sourceTraceId`: esas trazas no existen en Cloud.

**Paso 4 — recrear configuraciones y cola** desde el repo, con el `.env` local ya apuntando a
Cloud (§5): `just langfuse-setup`.

**Paso 5 — comprobar.** Número de datasets e ítems iguales en las dos puntas:

```bash
for name in $(jq -r '.data[].name' datasets.json); do
  l=$(cat items-"$name"-*.json | jq -s 'map(.data|length)|add')
  c=$(curl -fsS -u "$CAUTH" "$CLOUD/api/public/dataset-items?datasetName=$(jq -rn --arg n "$name" '$n|@uri')&limit=1" | jq '.meta.totalItems')
  echo "$name local=$l cloud=$c"
done
```

Comprimir la carpeta (`tar czf langfuse-export-$(date +%F).tgz ~/langfuse-export`, **sin**
`cloud.env`) y entregarla a Herwin por un canal privado.

**Paso 6 — dar de baja la instancia local**, solo con el visto bueno de Herwin sobre los conteos
y el archivo en su poder: `just langfuse-reset` (borra los volúmenes), borrar
`infra/langfuse/.env` y `~/langfuse-export/cloud.env`, y quitar del `.env` las claves locales.
Para Sonar: `docker compose down -v` en `infra/sonarqube/`.

## 9. Consecuencias

- Ya no hay una herramienta del equipo que viva en una sola máquina. Las dos dependen de cuentas
  del fundador, como el resto de credenciales críticas (§7 de `offboarding-desarrollador.md`).
- El plan *Hobby* tiene 2 usuarios y 30 días de datos: el historial largo de evaluaciones son los
  `results/*.json` en git y el archivo de la exportación, no Langfuse.
- Si el repo vuelve a privado, SonarQube Cloud deja de ser gratis: se apaga, no se paga.
- `docs/plan-observabilidad-langfuse.md` (decisión del 2026-10-13 «autoalojado») se actualiza en
  la épica m-24852178.
