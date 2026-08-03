# Sprint 2 — estado 2026-07-29 (equipo trabajando mientras el fundador duerme)

Escrito y mantenido por el dev-lead. **Todo verificado contra filesystem, Linear, la plataforma real
de Meta y ejecución de tests por el propio lead** — no contra reportes de agentes sin cruzar.
Nada commiteado: 26 ficheros en el working tree (15 nuevos) esperando revisión del fundador.

**Suites, corridas por el lead (última actualización tras R11 completo):**
`uv run --no-sync pytest -m "not integration"` → **266 passed**
`uv run --no-sync pytest -m "db"` → **36 passed**

Progresión del gate durante el turno, y **el número subió por la razón correcta, no por tests nuevos
de relleno**: 217 → 258 (+41: los tests del contrato entran al gate al mudarse a `packages/shared`)
→ 263 (+5: la auditoría de cobertura del gate, R11d) → **266** (+3: los tests de conformidad del
fixture, R11a). Cada delta verificado por nombre con `--collect-only`, no deducido del total.

---

## 1. LO QUE EL FUNDADOR TIENE QUE HACER AL DESPERTAR (por orden de valor)

### (a) Cinco minutos de Meta — completar la conexión de la tienda

La escalera de diagnóstico de R9(e) está en el paso 2. El paso 1 **ya se ejecutó y falló**:

| Paso | Estado |
|---|---|
| 1. Re-ejecutar el flujo con conteos | ✅ **HECHO → `page_access_required`, `pages=0`, `pages_with_ig=0`**. La hipótesis del artefacto del Explorador queda **REFUTADA**: con el token real tampoco llegan Páginas |
| 2. Re-consentir añadiendo `ads_management` | ⏳ **Requiere al fundador** (scope nuevo sobre su cuenta) |
| 3. Asignar tarea explícita (Contenido/Control total) en Meta Business Suite y re-consentir | ⏳ **Requiere al fundador** |

**Causa raíz establecida (R9c):** `/me/accounts` filtra **por TAREAS asignadas, no por propiedad**.
*"This will return a collection of Facebook Pages that **the user can perform tasks on**"*
(`business-login-for-instagram.md:118`). **Ser admin del Business Portfolio que posee la Página NO
es tener una tarea sobre ella.** Las dos Páginas del fundador (`Cultura Geeks` `488367684569819`,
`Attitude.org.ve` `997310210389105`) cuelgan del portfolio `Attitude.org.ve` (`218896178911983`).

**No tocar el código de la arista:** R9(a) fijó `/me/accounts` como correcto y R9(b) refutó que
existan alternativas vigentes (`assigned_pages` deprecado en 2019; `owned_pages` sólo en changelog
de 2017 sin página de referencia).

### (b) Decisión de plata — ¿financiar etiquetar ~100 vídeos?

Es el **único** desbloqueo de QUA-23. Números de datasci (análisis de potencia real, no estimación):
**~50 relevantes + ~50 no-relevantes ≈ 100 ítems**, porque precisión y recall tienen denominadores
distintos; n≈34 por estimando da ±10pp al 95%. **Valida de forma independiente el "~100" de
`docs/arquitectura.md` §7**, que parecía puesto a ojo y estaba bien fundado.

Estado actual del golden set: **1 ítem, etiquetado positivo, 0 negativos** → precisión **inmedible a
cualquier umbral**; recall = Bernoulli único con Wilson 95% de **[0.21, 1.00]**. Y ese único ítem
tiene el transcript marcado como placeholder vacío. **Mientras no haya datos, QUA-23 queda abierto y
honestamente bloqueado — decisión tomada, no omisión.**

### (c) Firmar ADR 28 (sigue `[PROPUESTO]`)

Ahora es una decisión más chica que ayer: sólo vídeo, cero superficie HTTP pública.

---

## 2. ENTREGADO Y VERIFICADO

| Historia | Estado | Verificación del lead |
|---|---|---|
| **QUA-67** contrato de comentarios | ✅ **ENTREGADO** | 54 passed en caché fría; 217 raíz sin regresiones |
| **QUA-19 / A1** puerta de objetos | ✅ | en `packages/shared/.../objects/` + 3 tests |
| **QUA-19 / A2** migración `0003_publishing` | ✅ | aplicada, revertida y re-aplicada contra Postgres real |
| **QUA-20 / B2** migración `0004_inbox` | ✅ | idem; `relforcerowsecurity=true` en las 4 tablas |
| **R9.f** partir `link_required` | ✅ | **validado en producción en su primera corrida** |
| QUA-19 / A3 cliente de publicación | 🔄 en curso | |
| QUA-23 filtro | 🔄 en curso | |

### R9.f se pagó solo en la primera ejecución real

`ConnectOutcome.PAGE_ACCESS_REQUIRED` (cero Páginas) quedó separado de `LINK_REQUIRED` (hay Páginas,
ninguna con IG). **Sin ese cambio, el resultado del paso 1 habría salido como `link_required` y le
habríamos dicho al operador *"vinculá tu Instagram"* cuando lo que falta es *"dale acceso a tu
Página"* — instrucción opuesta.** El invariante de R4 intacto: cero credencial, cero conexión, jti
gastado igual, en ambos desenlaces.

### Leer el contrato antes del DDL cambió tres decisiones reales

`messages.posted_at`, `author_external_id` y `author_username` son **NULLABLE** porque el contrato
marca esos campos como `IF_REQUESTED` / `REQUIRES_PERMISSION`. Escritas NOT NULL, habrían rechazado
payloads que Meta manda legítimamente, y se habría descubierto contra la cuenta real.

---

## 3. RULINGS DEL ARCHITECT DE ESTE TURNO (todos en `docs/arquitectura.md` §6)

- **R9** — cierra el `[V]` de R4. `/me/accounts` es el endpoint correcto; la causa es el filtro por
  tareas; `link_required` estaba sobrecargado y se parte; escalera empírica de 3 pasos.
- **ADR 25 (O8)** — **el coste de la bifurcación en el eje DM nunca se tasó, y es real.** Bajo
  Facebook Login, leer DMs de clientes reales exige Advanced Access + verified business
  (`business-messaging/instagram-messaging/overview.md:122`: *"Apps with Standard Access can only
  interact with people who have a role on the app"*). **La bifurcación NO se reabre**: volver a
  Instagram Login costaría mentions/tags (ADR 25) **y** la subida resumible (ADR 28).
- **DDL de 0003/0004 firmado** con tres condiciones, todas implementadas: settle write-once por
  **TRIGGER** (no por convención de repositorio), `scheduled_tz NOT NULL`, y `last_inbound_at` como
  **única** base de la ventana de mensajería.
- **Ventana de mensajería = 24 h, citada** (`overview.md:178`). Los **7 días NO son una ventana más
  larga**: son una extensión que sólo existe bajo el tag `human_agent` → capacidad separada
  explícita, **nunca por defecto**.
- **Sede del contrato:** `packages/shared` como `qualify_shared.social.ig_shapes`, con la condición
  de que sea **estrictamente contrato** (sin DB, sin HTTP, sin lógica de negocio). **Mudanza
  pendiente, asignada a datasci** (el fichero es suyo); después pipeline actualiza el docstring de
  `0004_inbox.py`.

---

## 4. TRAMPAS METODOLÓGICAS DESCUBIERTAS (valen para todo el repo)

1. **Gates que no ejecutan nada.** `uv run pytest -q` da 175/217 en verde **sin colectar un solo
   test de `packages/models/`** — `testpaths` los excluye a propósito. **Cualquier criterio de
   aceptación escrito con ese comando es decorativo.** Corrección transversal pendiente.
2. **Verde que no significa lo que parece.** Un test del trigger pasaba porque Postgres coacciona el
   string `"now()"` a timestamp. Pipeline no se fió del verde: miró el valor guardado y reescribió
   el helper.
3. **El `changelog.md` es registro histórico, no estado actual.** Su línea 695 prohíbe la Content
   Publishing API a cuentas Creator — es del **22-may-2019** y está superada.
4. **La trampa inversa:** dos copias byte-idénticas de una página **no** implican antigüedad. La copia
   `v2.10` de `page/conversations.md` declara en su cabecera **Graph API v25.0** → el harvester
   guardó la página *actual* bajo dos rutas. **Hay que mirar la cabecera de versión.**
5. **Una frase de permisos dentro de un doc de feature está acotada a esa feature** mientras no se
   demuestre lo contrario (pipeline sobreextendió `moderate-conversations.md:20` y se corrigió).
6. **Mina activa, sin resolver (R9d):** el corpus dice **quince veces** que hace falta
   `ads_management`/`ads_read` si el rol vino por Business Manager, **pero** `ig-hashtag-search.md:36`
   dice *"one of: `ads_management`, `business_management`, **or `pages_read_engagement`**"* — y ése sí
   está concedido. **Según qué página se lea, el requisito ya se cumple o no. No hardcodear ninguna
   lectura.**
7. **Test de citas auto-verificable** (idea de datasci, adoptada): verifica que cada cita al corpus
   resuelve (fichero + línea + texto). **Con control negativo probado** en 4 modos de fallo. Alcance
   correcto: sólo donde la fuente es **ajena y mutable** (corpus harvesteado), nunca sobre código
   propio.

---

## 5. HALLAZGOS DE PRODUCTO QUE NO SE DEBEN PERDER

- **`instagram_manage_comments` bloquea el edge ENTERO de comentarios**, no sólo el campo `username`
  (`ig-media/comments.md:70-73`). Con los grants de hoy el poll devolvería vacío. **No es puerta de
  verificación: es Standard Access auto-aprobado, sólo hay que pedirlo.** Añadir a
  `QUALIFY_META_SCOPES` y re-consentir.
- **Precondición HUMANA, no un scope:** el dueño debe activar a mano *Instagram Settings → Messages
  and story replies → Message controls → Connected Tools → Allow Access to Messages*
  (`get-started.md:129`). **Un poll vacío es ambiguo entre "no hay mensajes" y "el toggle está
  apagado"** — una bandeja que pinte silencio como cero estaría reportando un hueco de permisos como
  desinterés del cliente. Codificado como dato en el contrato.
- **Trampa de UX del diálogo de Meta:** el botón **"Reconectar"** intenta restaurar la configuración
  previa y **se cuelga si no existe o está incompleta**. El camino que funciona es **"Editar
  configuración"**. **La UI de conexiones (C-06) debe guiar a "Editar configuración".**

---

## 6. SEGURIDAD

- **`.env` NO estaba en `.gitignore`** — con la `app_secret` real dentro. **Corregido**, y verificado
  que **nunca entró al historial de git** (`git log --all -- .env` vacío). **No hace falta rotar.**
- La `app_secret` **nunca fue leída ni transcrita** por el lead ni por ningún agente.
- **NO se pulsó "Solicitar acceso avanzado"** en el dashboard: arranca Business Verification (B0-1b),
  el reloj administrativo que el fundador no ha iniciado. No debe dispararse por accidente.

---

## 7. INFRA LEVANTADA (se cae si se cierra la sesión)

- Docker: Postgres + Redis sanos. **Se paró el Postgres nativo de Homebrew**
  (`brew services stop postgresql@15`) porque robaba el 5432.
- Migraciones aplicadas hasta `0004`, seed hecho (PuntoServis + Inmobiliaria).
- Backend: `uv run --no-sync --with uvicorn uvicorn "qualify_api.http.app:create_app" --factory`
- Túnel: `https://lightning-worm-nutten-medline.trycloudflare.com` (cloudflared anónimo).
  **Si se corta, la URL cambia y hay que re-registrarla en Meta.**
- **TRAMPA DEL VENV:** editable-installs rotos; `uv sync` no arregla y alternar grupos empeora.
  Usar **siempre** `uv run --no-sync` + `PYTHONPATH` explícito. Para deps faltantes (`uvicorn`,
  `jiwer`): **`uv run --no-sync --with <dep>`**, que no toca el venv.

---

## 8. DEUDA REGISTRADA

- **`uvicorn` no declarado** en `packages/api` pese a exponer rutas HTTP. Pipeline lo declara al final
  (toca `uv.lock` → fuerza sync → riesgo de venv). **Avisar antes de correrlo.**
- **`jiwer` declarado pero ausente del venv** → 8 ficheros de test de models no colectan. Workaround
  sin sync: `uv run --no-sync --with jiwer`.
- **Tenants de prueba** (`t-A`, `t-B`, `tenant-A`, `tenant-B`, `ui-a`, `ui-b`) contaminan la base de
  dev junto a los dos reales.
- **`filter.py` con deriva de formato** pre-existente (`ruff format --check` lo marca). Se pliega en
  QUA-23, donde ese fichero se edita igual.
- Meta procesa con **v25.0**; el default del código es **v21.0**. Debería ser elección deliberada.

---

## 9. MUDANZAS Y RENOMBRES — ESTADO ACTUAL (mirar acá ANTES de reasignar)

> **Convención nueva, 2026-07-29, obligatoria: quien EJECUTA una mudanza o renombre lo anota en esta
> sección apenas termina, no sólo por mensaje.** Origen: propuesta de `datasci` tras el incidente de
> abajo. Razón: el lead verifica el disco antes de reasignar, pero **el disco cambia entre su
> verificación y la llegada de su mensaje**; las notas del ejecutor no son donde el lead mira. Los
> agentes tienen permiso explícito para editar **sólo esta sección** de este fichero.

| Fecha | Qué se movió | De → A | Ejecutor | Estado |
|---|---|---|---|---|
| 2026-07-29 | `ig_shapes.py` + sus tests | `packages/models/…/social/` → `packages/shared/src/qualify_shared/social/` | `datasci` | ✅ **COMPLETA Y VERIFICADA** |
| 2026-07-29 | `synthetic_ig_comments.json` + `test_ig_fixture_shape.py` (R11a) | `packages/models/tests/` → `packages/shared/tests/` | `pipeline` | ✅ **COMPLETA Y VERIFICADA** |

Detalle de la mudanza R11(a), ejecutada por `pipeline` con excepción de propiedad explícita del lead:
- `packages/shared/tests/fixtures/synthetic_ig_comments.json` ✅ (`git mv`, historial preservado) ·
  `packages/shared/tests/test_ig_fixture_shape.py` ✅ (`mv` normal: el fichero era **untracked**, así
  que `git mv` falla — dato para la próxima).
- `packages/models/tests/fixtures/` conserva **sólo** los media (`sample_audio.wav`, `sample_frame.jpg`,
  `sample_source.mp4`); no se tocaron.
- **Dirección de dependencia respetada:** `test_ig_comments.py` (sentimiento) **se queda en `models`** y
  ahora alcanza hacia `packages/shared/tests/fixtures/`. El consumidor alcanza al contrato; nunca al
  revés. Mover sólo los tests habría obligado a `shared` a mirar dentro de `models`.
- **Los 3 tests de conformidad YA se colectan en el gate por defecto** — confirmado con
  `--collect-only` y por nombre, no deducido del total.
- **Suite raíz: 266 passed** (era 263 tras R11d, que a su vez era 258). El delta **+3 son exactamente
  los tests movidos**; nada más entró.
- Test de citas del corpus: **verde tras la mudanza**. Tests de sentimiento en `models`: **11 verdes**,
  encuentran el fixture en su nueva ubicación.
- Contenido no editado salvo lo que exigió la reubicación: el docstring describía su propia ubicación
  ("Lives here rather than beside the contract") y habría quedado mintiendo.

**RENOMBRE (R12) — `pipeline`, 2026-07-29. Relevante fuera de su módulo, por eso se anota acá.**

`connections/resolver.py`: **`_BearerClient` → `_InjectedAuthClient`**, y `client_for()` pasa a
`client_for(connection_id, *, scheme)` **sin valor por defecto**.

- **Por qué el renombre:** el nombre viejo pasó a ser mentira en cuanto R12 estableció que
  `rupload.facebook.com` exige `OAuth` y no `Bearer`. Es la **puerta de credenciales**, que se
  audita; un nombre rancio ahí engaña a quien la mire dentro de seis meses.
- **Por qué sin default:** un default de `Bearer` hace **invisible el caso seguro y opt-in el
  peligroso** — quien olvide el parámetro obtiene `Bearer` contra `rupload` y lo descubre en
  producción.
- **Llamadores actualizados:** `connections/verifier.py` (nombra `settings.graph_auth_scheme`
  explícitamente) y `tests/test_connections_resolver.py`. **Si alguien tiene código en vuelo que
  llame a `client_for()`, ahora falla en firma** — es intencional, no un descuido.
- El esquema vive en `MetaOAuthSettings` (`graph_auth_scheme` / `rupload_auth_scheme`),
  sobreescribible por `QUALIFY_META_GRAPH_AUTH_SCHEME` / `QUALIFY_META_RUPLOAD_AUTH_SCHEME`.
  **El literal no está en el publicador** — pasarlo desde ahí sólo habría mudado el hardcode.
- **Andamio borrado, no mergeado:** el transporte propio que `HttpPublishClient` construía fue
  rechazado por el architect como segunda puerta pasando la verja de credenciales. Ahora toma
  **dos clientes ya autenticados** y no hay ningún token en ese fichero.
- Suite tras el rework: **298 passed**. `DISCREPANCIES.md` §4 documenta la contradicción.

**R11(d) — también de `pipeline`, mismo turno:** `testpaths` pasa a **deny-list auditada**.
`[[tool.qualify.test-gate.excluded]]` en el `pyproject.toml` raíz (con razón por entrada) +
`packages/shared/tests/test_gate_coverage.py` (5 tests). **Decisión consciente sobre la tercera
instancia:** `packages/docs-harvester/tests` queda **excluido con justificación escrita** (sus tests
sólo afectan a su propio paquete), no olvidado. Verificado **rompiéndolo**: se creó un
`packages/ghostpkg/tests` real, la auditoría falló nombrándolo, y se borró.

Detalle de esa mudanza, verificado por el lead ejecutando los comandos:
- `packages/shared/src/qualify_shared/social/ig_shapes.py` ✅ · `ig_shapes` ya **no** está en `models` ✅
- Tests del contrato (**41**) en `packages/shared/tests/`; tests de instancia del fixture (**3**) se
  quedan a propósito en `packages/models/tests/test_ig_fixture_shape.py`, junto al fixture que leen.
- `0004_inbox.py`: **ambas** citas ya apuntan a `qualify_shared.social.ig_shapes` ✅
- **Suite raíz: 258 passed** (subió de 217, no bajó) — **+41 porque `packages/shared/tests` SÍ está en
  `testpaths` y `packages/models/tests` no.** El contrato y su test de citas pasan a correr en el gate
  por defecto: mitigación directa de la trampa del gate vacío (§4.1).
- Rutas al corpus verificadas **con el control negativo re-ejecutado desde la nueva ubicación** (los 4
  modos de fallo se siguen detectando), no asumidas.
- La condición del architect ("estrictamente contrato") **pasó de inspección a test**:
  `test_the_contract_stays_strictly_a_contract` falla si el módulo importa sqlalchemy, psycopg, httpx,
  requests, fastapi, `qualify_api`, `qualify_models` o `qualify_shared.db`.
- Hizo falta `pythonpath = ["src", "../shared/src"]` en `packages/models/pyproject.toml` (la
  declaración de dependencia `qualify-shared` es correcta pero **sin sincronizar**: trampa del venv).
  **No se corrió `uv sync`.**

### 9.1 Hueco abierto que dejó la mudanza (enrutado al architect)

Los 3 tests de `test_ig_fixture_shape.py` viven en `packages/models/tests`, que **no** está en
`testpaths`. Medido por el lead: **0 colectados** en el gate por defecto, **3 passed** si se corren
explícitamente. Son justo los que afirman que el fixture sigue validando contra el contrato — o sea,
**los que deberían saltar si el contrato deriva son los que no corren**. Decisión pendiente del
architect entre: (a) meter `models/tests` en `testpaths` (arrastra la suite `ml` y hoy ni colecta sin
`jiwer`), (b) mover esos 3 tests a `shared/tests`, (c) deuda documentada. Se le pidió además el
invariante general que impida que un test que protege un contrato quede fuera del gate.

---

## 10. ERROR DE COORDINACIÓN DEL LEAD, PARA EL LEDGER

**`ig_shapes` se reasignó CUATRO veces** entre `datasci` y `pipeline`. **Nadie perdió trabajo y nada
quedó roto**, pero por poco: la duplicación real se detuvo inspeccionando el working tree (el
contrato ya existía, 748 líneas) justo antes de que `pipeline` lo reconstruyera.

**Causa raíz — corregida respecto de mi primer diagnóstico, gracias a `datasci`:** yo lo atribuí a
haber dado una excepción de propiedad, y **esa atribución era falsa**. La excepción acotada funcionó
bien: `datasci` tocó exactamente `social/` y `test_ig_shapes.py`, nunca `objects/` donde trabajaba
`pipeline`, y `pipeline` no tuvo que mover fichero ajeno. **Lo que falló fue la latencia**: tres
reasignaciones, cada una razonable por separado, ninguna emitida con el estado más reciente a la
vista.

**Mitigación adoptada:** la convención de §9 — el ejecutor anota la mudanza **en este fichero**, que
es donde el lead mira, en vez de sólo en sus notas o por mensaje. "Verificar el disco antes de
reasignar" **no alcanza por sí solo**, porque el disco cambia entre la verificación y la llegada del
mensaje.

**Patrón reutilizable de los agentes, que es lo que evitó el daño:** `pipeline` recibió un brief
desactualizado (mover un fichero que ya no estaba), **verificó antes de ejecutar**, y al encontrar la
tarea hecha **auditó la mudanza ajena en vez de rehacerla** — incluida la reconciliación de 40 vs 43
tests reportados, que confirmó que los 3 faltantes se habían reubicado a propósito y no perdido.
