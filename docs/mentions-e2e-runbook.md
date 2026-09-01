# Runbook — Mentions v1 (Instagram caption/comment): configuración y prueba E2E

**Alcance de este documento, dicho una sola vez para no repetirlo:** cubre únicamente
menciones de Instagram en **caption y comentario** (`mentioned_media`/`mentioned_comment`,
campo de webhook `mentions`, vía Facebook Login — ADR 25). **No** cubre Stories, `/tags`
(etiquetados), Facebook, Threads ni TikTok — ver el ticket Linear QUA-97 ("Fuera de
alcance") y QUA-49 (Backlog, parking-lot) para el estado de esas superficies.

Módulo de código: `packages/api/src/qualify_api/mentions/`. Ticket: QUA-97 (Done en
código/tests). Este runbook existe para que la primera prueba real, cuando Business
Verification la desbloquee, tarde minutos y no una sesión de investigación.

## 1. Variables de entorno

Todas con default de desarrollo si no se definen — un despliegue real debe fijar las tres
primeras o la verificación de firma falla contra cualquier payload real de Meta:

| Variable | Usada por | Default de dev (NUNCA en producción) |
|---|---|---|
| `QUALIFY_META_APP_SECRET` | HMAC del webhook (`mentions/config.py`) — el mismo secreto que el intercambio OAuth | `dev-app-secret` |
| `QUALIFY_META_WEBHOOK_VERIFY_TOKEN` | Handshake GET (`hub.verify_token`) | `dev-only-webhook-verify-token` |
| `QUALIFY_META_SCOPES` | Scopes solicitados en el connect flow (CSV) — nunca hardcodeados, ver `config.py` | `""` (ninguno) |
| `QUALIFY_META_APP_ID` | Connect flow | `dev-app-id` |
| `QUALIFY_GRAPH_BASE_URL` | Cliente de `mentioned_media`/`mentioned_comment` (`MetaOAuthSettings.graph_url`) | `https://graph.facebook.com` |
| `QUALIFY_META_API_VERSION` | Versión de Graph API | `v21.0` |
| `QUALIFY_META_GRAPH_AUTH_SCHEME` | Header `Authorization` contra `graph.facebook.com` | `Bearer` |

Los scopes efectivamente **concedidos** por Meta (no los solicitados) se leen de
`social_connections.granted_scopes` para la conexión real — no de ninguna variable de
entorno ni de este repo.

## 2. Configuración en el Meta App Dashboard

1. Webhooks → suscribir la app al campo **`mentions`** sobre el objeto `instagram`.
2. Callback URL → `https://<host>/api/mentions/webhook`. Certificado TLS válido
   obligatorio (self-signed no es soportado por Meta).
3. Verify Token del formulario = exactamente el valor de `QUALIFY_META_WEBHOOK_VERIFY_TOKEN`.
4. **Confirmar el modo de la app** (Development vs. **Live**) y el nivel de acceso
   (Standard vs. **Advanced**) para `instagram_manage_comments` — **ver §5, es el bloqueo real hoy.**

## 3. Precondiciones de cuenta (nada de esto es negociable, todas documentadas por Meta)

- La cuenta **conectada** debe ser Instagram **Profesional** (Business/Creator), con
  **Página de Facebook vinculada** (ADR 25), y configurada como **pública**.
- La cuenta que **menciona** (el tercero de prueba) debe ser **pública** — si es privada,
  Meta descarta el webhook en silencio, sin error ni reintento.

## 4. Procedimiento de prueba E2E — paso a paso

Ejecutar sólo después de que §5 esté resuelto (app Live + Advanced Access para
`instagram_manage_comments`).

1. Confirmar que la suscripción al campo `mentions` sigue activa y el Callback URL
   apunta al entorno correcto.
2. Confirmar que la cuenta conectada es pública y su Página de Facebook sigue vinculada.
3. Desde una cuenta de Instagram **pública, distinta** de la conectada: publicar un
   Reel/foto con `@handle_de_la_cuenta_conectada` en el caption, **o** comentar
   `@handle_de_la_cuenta_conectada` en cualquier post.
4. **Logs** — buscar una de estas dos líneas (nunca ambas para el mismo evento):
   - Éxito: `mentions webhook: resolved tenant=... connection=... media_id=... comment_id=... mention_id=...`
   - Fallo de atribución (no debería pasar con una cuenta ya conectada):
     `mentions webhook: orphan event...` o `AMBIGUOUS external_account_id=...`
   - Si aparece `mentions webhook: tenant=... resolved but NOT persisted` → bug real, reportar
     (indica que la resolución de tenant funcionó pero la lectura de `ig_user_id` de la
     conexión falló — no debería ocurrir con una conexión sana).
5. Confirmar ausencia de reintentos: no debe repetirse el mismo `media_id`/`comment_id`
   minutos después (eso indicaría que no se respondió 200 a tiempo).
6. **Base de datos** — `SELECT * FROM mentions WHERE media_id = '<id-real>'`:
   - Debe existir **exactamente una** fila.
   - `enrichment_status`:
     - `'ENRICHED'` → éxito completo (el permiso de lectura de contenido también funcionó).
     - `'ENRICHMENT_FAILED'` → éxito parcial. Buscar en logs la línea
       `mentions enrichment failed... platform_code=... platform_subcode=... http_status=...`
       — ese código es la evidencia de SI el fallo es "Advanced Access todavía no
       concedida" (esperable hoy) o un bug real (inesperado una vez concedida).
7. **Dashboard de Menciones** (`/`, Reflex) — confirmar que la fila aparece con
   caption/texto/autor reales, no con el estado vacío ("Aún no hay menciones").
8. La prueba se considera exitosa sólo con (4)+(6)+(7) en verde, con datos **reales** —
   nunca con el botón "Test" del App Dashboard (ese sólo prueba HMAC + infraestructura
   con un payload sintético, ya verificado en QUA-97).

## 5. El bloqueo real — qué falta y de qué lado está

Ver la auditoría completa (sesión 2026-09-01) para el detalle; resumen accionable:

| Falta | ¿De quién es la tarea? |
|---|---|
| App en modo **Live** | Meta App Dashboard, una vez Advanced Access esté aprobada |
| **Advanced Access** para `instagram_manage_comments` (gatea webhook `mentions` + `mentioned_media`/`mentioned_comment`) | App Review de Meta, requiere Business Verification aprobada primero |
| **Business Verification** | **Nuestra**, y hoy no ha empezado: dominio, entidad legal, documentos — proyecto Linear "Verificación Meta Business — Qualify" (QUA-5..QUA-12), 100% en Backlog |

**Ninguna acción de ingeniería adelanta esto.** El código está listo para recibir el
evento real desde el primer día en que la app pase a Live con Advanced Access — no
requiere ningún deploy ni cambio adicional cuando eso ocurra.

## 6. Qué queda deliberadamente sin poder probarse hasta entonces

- Que Meta realmente entregue un webhook `mentions` disparado por un tercero genuino.
- Que `mentioned_media`/`mentioned_comment` devuelvan una respuesta real de Graph API
  (hoy sólo verificado contra el corpus harvesteado — `meta_client.py` lo marca
  `[UNVERIFIED LIVE]` explícitamente).
- El código exacto de error que Meta devuelve cuando `instagram_manage_comments` falta
  (no documentado por Meta; se observará en el primer intento real vía el log de
  `platform_code`/`platform_subcode` del paso 6 de arriba).
