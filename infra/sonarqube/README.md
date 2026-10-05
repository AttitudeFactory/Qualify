# SonarQube Community Build — autoalojado, costo cero

Servidor de análisis estático para el repo `Qualify`. Es la **Community Build** de
SonarQube (gratuita, open source, antes llamada *Community Edition*): analiza **una sola
rama** por proyecto y **no decora pull requests** — ambas cosas empiezan en Developer
Edition `[V 2026-10-05]` ([comparación de ediciones](https://www.sonarsource.com/products/sonarqube/downloads/),
[docs: branch/PR analysis no disponibles en Community Build](https://docs.sonarsource.com/sonarqube-server/latest/analyzing-source-code/pull-request-analysis/introduction.md)).
Por eso el workflow `.github/workflows/sonar.yml` corre solo en `push` a `main`.

El contexto completo (qué hace cada pieza, costos verificados, alternativas descartadas)
está en [`docs/calidad-codigo-revision-automatica.md`](../../docs/calidad-codigo-revision-automatica.md).

## 1. Levantarlo

Requisitos del host: Docker + Compose v2, **4 GB de RAM libres** (SonarQube lleva un
Elasticsearch embebido) y dos `sysctl` que Compose no puede fijar por sí mismo:

```bash
sudo sysctl -w vm.max_map_count=524288
sudo sysctl -w fs.file-max=131072
printf 'vm.max_map_count=524288\nfs.file-max=131072\n' | sudo tee /etc/sysctl.d/99-sonarqube.conf
```

Después:

```bash
cd infra/sonarqube
cp .env.example .env            # y cambia SONAR_DB_PASSWORD
docker compose up -d
docker compose logs -f sonarqube   # espera "SonarQube is operational"
```

Queda escuchando en `127.0.0.1:9000`. **No lo publiques en internet sin TLS**: el token
de análisis viaja en cada petición del scanner. En el VPS de staging ponlo detrás de
Caddy o Traefik, por ejemplo con Caddy (TLS automático):

```
sonar.attitudefactory.co {
    reverse_proxy 127.0.0.1:9000
}
```

En local basta con `http://localhost:9000`.

## 2. Primer login y proyecto

1. Entra con `admin` / `admin`. La UI **obliga a cambiar la contraseña** en el primer
   acceso `[V 2026-10-05]` ([docs](https://docs.sonarsource.com/sonarqube-server/try-out-sonarqube.md)).
2. **Projects → Create project → Local project**. Project display name `Qualify`,
   **project key `qualify`** (tiene que coincidir con `sonar.projectKey` en
   `sonar-project.properties` de la raíz del repo), main branch `main`.
3. En la pantalla de análisis elige *With GitHub Actions* y **genera el token** (o ve a
   **My Account → Security → Generate Tokens**, tipo *Project analysis token*, proyecto
   `qualify`, con expiración). Cópialo en el momento: no se puede volver a ver
   `[V 2026-10-05]` ([docs](https://docs.sonarsource.com/sonarqube-server/10.2/user-guide/user-account/generating-and-using-tokens.md)).
4. En GitHub, **Settings → Secrets and variables → Actions → New repository secret**:
   - `SONAR_HOST_URL` = `https://sonar.attitudefactory.co` (la URL pública con TLS).
   - `SONAR_TOKEN` = el token del paso 3.

   Sin estos dos secretos `sonar.yml` **no falla**: un job previo comprueba que existen y,
   si no, el workflow termina en verde con un aviso.
5. Lanza el workflow a mano (**Actions → sonar → Run workflow**, sobre `main`) o espera
   al próximo push a `main`. El dashboard queda en `<SONAR_HOST_URL>/dashboard?id=qualify`.

## 3. Quality gate recomendado para Python

El gate por defecto («Sonar way») exige 80 % de cobertura nueva, que hoy no es realista
para este repo. Crea uno propio en **Quality Gates → Create** (nombre `qualify`), fija
las condiciones sobre **código nuevo** y asígnalo al proyecto (*Projects → Qualify →
Project Settings → Quality Gate*):

| Condición (código nuevo) | Umbral |
|---|---|
| Coverage | ≥ 60 % |
| New bugs (reliability issues, severidad ≥ Medium) | 0 |
| New vulnerabilities (security issues) | 0 |
| New security hotspots reviewed | 100 % |
| Duplicated lines density | < 3 % |

Define también el **periodo de código nuevo** (*Project Settings → New Code*) como
*Previous version*: `sonar.yml` envía `sonar.projectVersion=<sha>` en cada push, así cada
análisis compara contra el anterior.

El gate es **informativo** en esta primera versión (`sonar.qualitygate.wait=false` en
`sonar-project.properties`). Cuando el equipo haya visto varias corridas y el ruido esté
calibrado, cambiarlo a `true` hace que `sonar.yml` falle cuando el gate esté en rojo.

## 4. Qué analiza

- Fuentes: `packages/{api,shared,scraper,creative}/src` y `Qualify/`; tests por patrón
  (`**/tests/**`, `**/test_*.py`, `**/conftest.py`). Excluidos `migrations/`,
  `graphify-out/`, fixtures, `.web/` y `packages/render/node_modules`.
- Cobertura: `coverage.xml` (Cobertura) generado en el propio job con `pytest-cov`
  sobre la suite offline (`-m "not integration and not db and not slow"`).
- Hallazgos de `ruff` importados como *external issues* (`ruff-report.json`), así el
  dashboard muestra las mismas reglas que impone `ci.yml`.

## 5. Operación

```bash
docker compose ps                        # estado
docker compose logs --tail=200 sonarqube # errores de arranque (casi siempre vm.max_map_count)
docker compose down                      # para; los volúmenes persisten
docker compose down -v                   # BORRA la base de datos y los índices
```

**Actualizar**: la imagen está fijada a un tag concreto (ver `docker-compose.yml`) para
que un `pull` desatendido no salte de versión. Para subir: haz backup de la DB
(`docker compose exec db pg_dump -U sonar sonar > sonar.sql`), cambia el tag,
`docker compose up -d` y abre `<host>/setup` para que migre el esquema.

**Backup**: el estado vive en los volúmenes `sonarqube_postgres` (DB) y `sonarqube_data`
(índices de Elasticsearch, regenerables). Con el `pg_dump` de arriba basta.
