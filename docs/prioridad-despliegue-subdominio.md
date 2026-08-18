# PRIORIDAD — despliegue de Qualify en `qualify.attitudefactory.co`

**Estado:** **prioridad activa, bloqueante**. El dominio ya está comprado y operativo; lo que falta es el despliegue de Qualify. Queda **una sola decisión abierta**: dónde se aloja (§4).
**Veredicto en una línea:** el dominio estable ya existe (`attitudefactory.co`, comprado 2026-08-12), lo que retira los túneles `cloudflared` efímeros de la ruta crítica; el bloqueante real es que **Qualify no tiene despliegue de ningún tipo**, y **Vercel no es opción** porque Reflex necesita backend persistente con WebSockets.
**Pregunta que responde:** ¿qué falta exactamente para que Qualify tenga un redirect URI de OAuth estable, y cómo se encadena eso con la verificación de negocio de Meta y el programa Tech Provider?
**Método:** sesión de trabajo con el fundador desde el repo `attitude-site` (2026-08-12). Disponibilidad de dominio verificada vía RDAP + whois de registro; precios vía API de registrador de Vercel; requisitos de Meta vía documentación oficial. Todas las verificaciones son de esa fecha y **caducan**.
**Alcance:** este documento **no** decide el host ni escribe infraestructura. Documenta el estado verificado, la bifurcación pendiente y el orden de las dependencias.

> **Supersede parcialmente** la decisión interina de `docs/naming-dominios-exploracion.md` (2026-08-10): "el producto se despliega bajo el dominio del sitio de Attitude" sigue siendo cierto en la intención, pero **ese dominio ya no está indefinido** — es `attitudefactory.co`.

---

## 1. Lo que ya está resuelto (verificado 2026-08-12)

| Ítem | Valor | Estado |
|---|---|---|
| Dominio | `attitudefactory.co` | Comprado, propiedad de `hlrd1993-8781`, equipo Vercel `attitude1` |
| Registro | Creado `2026-08-12T06:47:01Z` vía Name.com (registrador de respaldo de Vercel) | Vence 2027-08-12, renovación US$24.80/año |
| DNS | Nameservers `ns1/ns2.vercel-dns.com`, propagados | Zona administrada en Vercel |
| Sitio raíz | `https://attitudefactory.co` → 307 → `/en` → 200, TLS válido | Sirve el sitio de Attitude (proyecto `attitude-site`) |
| Handle de Instagram | `@attitudefactory.ai` | Registrado 2026-08-11. **Aún personal**: falta pasarlo a cuenta profesional y vincularlo a una Page del portfolio |

**Por qué el TLD es `.co` y no `.ai`:** ccTLD de Colombia, coherente con el RUT de Cúcuta con el que se hará la verificación de negocio; US$4.99 el primer año frente a ~US$160/2 años del `.ai` (Identity Digital subió el mayorista del `.ai` en marzo 2026 — no existe registrador barato para ese TLD). Meta **no restringe TLDs**: verifica el dominio raíz (eTLD+1) por TXT de DNS, meta tag o archivo HTML.

**Consecuencia directa para este repo:** verificar `attitudefactory.co` en Meta **cubre automáticamente** `qualify.attitudefactory.co`. Los subdominios no se verifican por separado.

## 2. El bloqueante real — Qualify no tiene despliegue

Confirmado leyendo el repo (2026-08-12), y consistente con `CLAUDE.md` ("*nothing is deployed*"):

- No hay `Dockerfile` en ninguna parte del repo.
- No hay `infra/`, ni workflow de deploy (`.github/workflows/ci.yml` corre lint + migraciones + pytest, sin job de despliegue).
- `docker-compose.yml` solo levanta `postgres:16` y `redis:7` — no hay servicio de API ni de worker.
- `rxconfig.py` está desnudo: sin `api_url`, sin `frontend_port`/`backend_port`, sin `cors_allowed_origins`. Un despliegue los necesita.
- `qualify.toml` es un archivo de 0 bytes.
- El mecanismo actual de URL pública es un túnel **efímero**: `cloudflared tunnel --url http://127.0.0.1:8010`, y hay que re-registrar `QUALIFY_META_REDIRECT_URI` en Meta **en cada arranque**.

## 3. Por qué Vercel no sirve para Qualify

Vercel aloja el sitio de Attitude (Next.js) y administra el DNS de la zona, pero **no puede alojar Qualify**:

- Reflex necesita un **backend persistente con WebSockets**; el modelo serverless de Vercel no lo sostiene.
- Hacen falta Postgres 16 y Redis 7 vivos, más los tres roles de base de datos con RLS (`qualify_owner` / `qualify_admin` / `qualify_app` + `qualify_credential`).
- La custodia de credenciales usa cifrado de sobre con **la llave maestra inyectada por el entorno de ejecución, fuera de Postgres** — eso asume un host controlado, no funciones efímeras.

**Lo que sí aporta Vercel:** la zona DNS. Apuntar `qualify.attitudefactory.co` a cualquier servidor es **un registro A/CNAME de un minuto** (`vercel dns add`) una vez exista el destino.

## 4. La bifurcación pendiente — DECISIÓN DEL FUNDADOR

| | **Hetzner VPS** | **Railway / Fly.io** |
|---|---|---|
| Costo | ~€4–6/mes (CX22 cubre API + Postgres + Redis en Docker) | ~US$5–20/mes |
| Coherencia con lo ya documentado | Alta — es el host nombrado en `CLAUDE.md` §Stack y en `docs/integracion-cuentas-conectadas-meta.md` ("aloja el Postgres donde vive `oauth_credentials`") | Rompe el supuesto de host controlado |
| Custodia de credenciales | Bajo control propio, consistente con el diseño de cifrado de sobre | Las credenciales OAuth de clientes viven en infra de terceros |
| Trabajo para llegar a "funcionando" | Mayor: provisionar servidor, Docker, Caddy/Traefik para TLS, pipeline de deploy | Menor: Postgres y Redis gestionados, deploy desde GitHub, WebSockets soportados |
| Velocidad | Días | Horas |

**Criterio de desempate sugerido:** si aprieta el reloj de Meta (App Review tarda 4–6 semanas y **requiere Business Verification previa**), Railway desbloquea el callback estable esta semana y se migra a Hetzner con calma. Si no se quiere mover el modelo de custodia de credenciales, ir directo a Hetzner.

## 5. Alcance mínimo para desbloquear Meta

**No hace falta desplegar todo Qualify.** Lo único que debe vivir de forma estable en el subdominio es el endpoint de OAuth de FastAPI:

```
https://qualify.attitudefactory.co/api/connections/callback
```

Ese valor va en `QUALIFY_META_REDIRECT_URI` y se registra en *Facebook Login for Business → Settings → Valid OAuth Redirect URIs* (`developers.facebook.com/apps/<app_id>/fb-login/settings/`). App ID actual: `1670943920870196`.

La UI de Reflex puede desplegarse después; el orden natural es **API primero, UI después**.

## 6. Cadena de dependencias hacia Tech Provider

El orden importa: cada eslabón es prerrequisito literal del siguiente.

```
attitudefactory.co (✅ hecho)
  └─> Business Verification del portfolio con RUT de Cúcuta
        └─> App Review con Advanced Access
              └─> Tech Provider
```

1. **Business Verification** — prerrequisito duro; sin ella no se puede iniciar App Review. Requiere nombre legal del Business Manager **idéntico** a la razón social del RUT (causa nº1 de rechazo), RUT vigente, y sitio web vivo en HTTPS (ya cumplido con `attitudefactory.co`).
2. **App Review con Advanced Access** — para esta integración: `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`. Exige ícono de app, política de privacidad pública, instrucciones de borrado de datos (Data Deletion Callback URL o URL de documentación) y videos demo del flujo. **Aquí es donde el subdominio deja de ser opcional**: hay que enseñar el flujo corriendo en una URL estable.
3. **Tech Provider** — 4–6 semanas típicas según Meta. Consistente con el veredicto ya documentado en `docs/research-modelo-acceso-tech-provider.md` §9: el status de partner es *consecuencia* de haber escalado, no atajo.

**Nota de arquitectura de marca (decidido con el fundador, 2026-08-12):** la entidad legal y verificada es **Attitude**; **Qualify es un producto/app dentro del portfolio**, no una entidad legal. En el RUT nunca va "Qualify". Business Portfolio existente: `Attitude.org.ve` (`218896178911983`).

## 7. Pasos concretos cuando se retome

1. **Decidir host** (§4). Es lo único que bloquea todo lo demás.
2. Escribir el `Dockerfile` de `qualify_api` (sirve igual para Hetzner, Railway o Fly — trabajo agnóstico del host).
3. Completar `rxconfig.py`: `api_url`, puertos y `cors_allowed_origins` apuntando al dominio real.
4. Desplegar Postgres 16 + Redis 7 con los cuatro roles y correr `alembic upgrade head` contra el entorno nuevo. **Ojo:** hasta hoy las migraciones se editan **en sitio** (ADR 27 R8a) precisamente porque nada estaba desplegado — el primer despliegue **cierra esa puerta** y obliga a migraciones aditivas de aquí en adelante.
5. Inyectar la llave maestra de cifrado por entorno (nunca en Postgres) y el resto de `QUALIFY_*`.
6. TLS y proxy inverso (Caddy/Traefik en Hetzner; automático en Railway/Fly).
7. `vercel dns add attitudefactory.co qualify A <IP>` — o CNAME si el host da hostname.
8. Registrar el redirect URI definitivo en la app de Meta y **borrar los túneles `cloudflared`** de la documentación operativa.
9. Recién entonces: lanzar Business Verification.

## 8. Referencias cruzadas

- `docs/naming-dominios-exploracion.md` — exploración de marca; su decisión interina queda concretada por este documento.
- `docs/integracion-cuentas-conectadas-meta.md` — flujo OAuth, custodia de credenciales, y el diseño del webhook que sigue **deliberadamente sin construir** (postura POLL-FIRST; los webhooks exigen Live mode + Advanced Access + Business Verification).
- `docs/research-modelo-acceso-tech-provider.md` §9 — por qué Tech Provider no es atajo.
- `docs/arquitectura.md` §6 R9 — IDs del Business Portfolio y Pages.
