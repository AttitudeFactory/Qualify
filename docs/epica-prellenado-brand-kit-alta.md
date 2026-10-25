# Épica — Identidad de marca precargada desde el Alta de cliente

**Fecha:** 2026-10-24 · **Estado:** `[HISTORIAS · sin implementar · diseño aprobado 2026-10-24 · tope fijado 2026-10-25 (US$0,15 por Alta) · precarga apagada en producción hasta el límite duro de tokens]` · **Meegle:** épica [m-24852192](https://project.larksuite.com/5h2wsx/story/detail/24852192) (mapa de tickets en §4)
**Decisión del fundador (Herwin, 2026-10-24):** cuando un cliente se da de alta con el ítem «Alta de cliente» de Meegle, Qualify genera su identidad de marca (Brand Kit) antes de que entre, para que la encuentre precargada en su primer ingreso. Origen: ticket [m-24823674](https://project.larksuite.com/5h2wsx/issue/detail/24823674) (2026-10-21, «precargar el kit de marca y el nicho desde el handle del ticket»), que esta épica reemplaza (cerrado el 2026-10-24). Pertenece a la épica de altas [m-24786482](https://project.larksuite.com/5h2wsx/story/detail/24786482).
**Revisión técnica:** principal-architect, 2026-10-24, contra el código en disco. Talla total: **M**. El fundador aprobó el diseño de §2 el 2026-10-24 (§5).
**Restricciones firmadas que aplican:** asistido, nunca autónomo (la propuesta se aprueba en el primer ingreso); compra lo genérico (ScrapeCreators, Claude), construye el núcleo; un solo Postgres; procedencia en todo dato derivado; idempotencia en todo worker; única puerta de entrada = el ítem «Alta de cliente» (2026-10-23).

---

## 0. Resumen en cinco líneas

1. La inteligencia y el guardado del Brand Kit **ya están en el backend**; lo que falta es sacar la orquestación de la pantalla de Reflex y dispararla desde el Alta.
2. El Alta no pide hoy ninguna cuenta de Instagram: se agrega el campo «Cuenta de Instagram».
3. Al completar «Datos», después de enviar la invitación, se crea un borrador de Brand Kit para el correo y se encola la precarga en `webhook-worker` (nunca dentro del webhook).
4. El cliente ve una **propuesta** en su primer ingreso y la aprueba, la cambia o empieza de cero. Nada se genera con IA de imagen antes del login.
5. Se cierra antes un hueco de seguridad: hoy un borrador se puede retomar escribiendo el correo, sin verificarlo.

## 1. Qué existe hoy (medido por el arquitecto, 2026-10-24)

| Pieza | Estado | Dónde |
|---|---|---|
| Servicio y guardado del Brand Kit | En el backend | `packages/api/src/qualify_api/creative/brand_service.py:108` (`BrandKitService`), `creative/brand_kit_store.py:115` (`BrandKitStore`) |
| IA del Brand Kit | En el backend | `creative/brief_ai.py`, `creative/font_ai.py:174`, `creative/voice_analysis.py:212`, `hashtags/from_profile.py:192`, `creative/account_claims`, `referentes/profile_cache` |
| Lectura del perfil de Instagram | Todavía en `Qualify/` (Python puro, sin Reflex) | `Qualify/scrapecreators_client.py` (`fetch_profile_and_posts` :862), `Qualify/creator_discovery.py` (`seed_from_profile`), `Qualify/logo_palette.py` |
| Orquestación de los pasos | Dentro del estado de Reflex | `BrandConnectState.analyze` (`Qualify/creative_wizard_pages.py:5204`), `apply_logo_colours` (:881), `suggest_hashtags` (:4173) |
| Lectura de sitio web | No existe en el flujo | — |
| Webhook del Alta | Guarda el evento; `webhook-worker` lo procesa; al completar «Datos» llama a `start_invitation` | `meegle/receiver.py:44`, `meegle/handlers.py:136-152`, `meegle/onboarding.py:152-199` |
| Campos que lee el Alta | Nombre del ítem, «Correo», «Nombre de la persona», «Nota personal». **Ninguno de Instagram, web o nicho** | `meegle/settings.py:130-132` |
| Tenant | No existe hasta el registro | `auth/service.py:232` (`register_business`) |
| Borrador de Brand Kit antes de la cuenta | Existe: crea tenant + usuario sin login por correo; el registro lo adopta | `auth/drafts.py:118` (`start_brand_kit_draft`), `drafts.py:154` (`claim_draft`), `service.py:257`, migración 0037 |
| Riesgo | El borrador se retoma con solo escribir el correo, sin verificarlo | `auth/drafts.py:16-18` |

## 2. Diseño (principal-architect, 2026-10-24 — aprobado por el fundador el 2026-10-24)

1. **Campo «Cuenta de Instagram»** en el tipo «Alta de cliente» (configuración de Meegle + `meegle/settings.py`). Se resuelve por nombre, como los demás (`meegle-altas` §1).
2. **Mover sin cambios** `scrapecreators_client`, `logo_palette` y `seed_from_profile` a `packages/api`; los llamadores de `Qualify/` importan de la nueva ubicación.
3. **Extraer `prefill_brand_kit(tenant_id, brand_id, network, handle)`**, que reproduce `analyze` sin estado de Reflex. El asistente web lo reutiliza: una sola implementación.
4. **Al completar «Datos»**, después de la invitación: `start_brand_kit_draft(email)` y se encola un trabajo de precarga que procesa `webhook-worker`. Clave de idempotencia por ítem + versión del usuario de Instagram. Nunca dentro de la petición del webhook.
5. **Asistido:** los resultados quedan como propuesta en `brand_kit_details.connect/profile`; el cliente revisa y aprueba en su primer ingreso. Sin generación de logo o avatar con IA antes del login.
6. **Tope de costo:** estimación del arquitecto ~2 créditos de ScrapeCreators + 1–2 llamadas a Haiku ≈ US$0,01–0,05 por Alta (precios **sin verificar**). **Sin tope fijo todavía** (fundador, 2026-10-24): PB-6 mide el costo real y propone un tope; el fundador lo fija. Hasta entonces la precarga sale **apagada por defecto** en producción. Un solo reintento. El costo de Claude ya se registra en `claude_tools`.
7. **Procedencia** en el documento `connect`: id del ítem de Meegle, versión de la lectura, modelo y versión del prompt.
8. **Seguridad:** un borrador creado desde el Alta queda **reservado a la invitación**: solo se adopta por el flujo de la invitación, nunca escribiendo el correo en la primera pantalla del Brand Kit.

## 3. Historias

Todas: Reporter y Assignee Herwin (reasignar al tomarla), épica [m-24852192](https://project.larksuite.com/5h2wsx/story/detail/24852192), evidencia = decisión del fundador 2026-10-24 + revisión del arquitecto 2026-10-24 + m-24823674. Código: `just ci-test` verde y aislamiento por tenant con test.

| # | Historia | Dueño | Prioridad | Talla | Depende de |
|---|---|---|---|---|---|
| PB-0 | Borradores del Alta reservados a la invitación | backend-engineer | P1 | S | — |
| PB-1 | Campo «Cuenta de Instagram» en el Alta | backend-engineer (+ fundador en la UI de Meegle) | P1 | S | — |
| PB-2 | Mover lectura de perfil, paleta y semillas a `packages/api` | creative-engineer | P1 | S | — |
| PB-3 | `prefill_brand_kit` sin Reflex, reutilizado por el asistente web | creative-engineer | P1 | M | PB-2 |
| PB-4 | Precarga encolada al completar «Datos», apagada por defecto, con tope y procedencia | backend-engineer | P1 | M | PB-0, PB-1, PB-3; encendido en producción: PB-6 |
| PB-5 | Revisar y aprobar la propuesta en el primer ingreso | reflex-ui-engineer (+ revisión ux-designer) | P1 | M | PB-4 |
| PB-6 | Medir el costo real por Alta y proponer el tope | data-scientist-fde | P1 | S | PB-3 |

### PB-0 — Borradores del Alta reservados a la invitación
- **Historia:** Como dueño de un negocio dado de alta por Attitude Factory, quiero que solo yo, desde mi invitación, pueda abrir la identidad de marca preparada para mí, para que nadie la vea escribiendo mi correo.
- **Criterios:** un borrador creado por el Alta lleva una marca de origen (`alta`, id del ítem); `start_brand_kit_draft` con ese correo desde la pantalla pública **no** lo retoma; `claim_draft` lo adopta solo desde `register_business` con un código de invitación válido del mismo ítem; test de las tres rutas; migración reversible con RLS si hace falta columna (`qualify-migration`).
- **Fuera de alcance:** verificación de correo para los borradores web existentes (queda como riesgo aceptado en `drafts.py`).

### PB-1 — Campo «Cuenta de Instagram» en el Alta
- **Historia:** Como fundador que da de alta a un cliente, quiero escribir su cuenta de Instagram en el Alta, para que Qualify prepare su identidad de marca sin pedírsela.
- **Criterios:** el campo de texto «Cuenta de Instagram» existe en el tipo «Alta de cliente» y en el diseño de la página de detalle (cambio en la UI de Meegle, lo hace el fundador o Chrome con su go); `meegle/settings.py` lo lee por nombre (`QUALIFY_MEEGLE_FIELD_*`); acepta `@usuario`, `usuario` y la URL del perfil y guarda el usuario normalizado; vacío no rompe la invitación; `meegle-altas` §1 actualizado.
- **Fuera de alcance:** sitio web, nicho, TikTok.

### PB-2 — Mover lectura de perfil, paleta y semillas a `packages/api`
- **Historia (técnica):** Como equipo, queremos que la lectura del perfil y la paleta del logo vivan en el backend, para que el worker las use sin importar la app de Reflex.
- **Criterios:** `scrapecreators_client`, `logo_palette`, `seed_from_profile` movidos sin cambiar comportamiento; los llamadores de `Qualify/` importan de la nueva ubicación; ningún módulo de `packages/api` importa de `Qualify/`; tests existentes verdes.
- **Fuera de alcance:** cambiar el proveedor o el prompt.

### PB-3 — `prefill_brand_kit` sin Reflex
- **Historia (técnica):** Como equipo, queremos una sola función que arme la propuesta de identidad de marca desde una cuenta, para que el asistente web y el Alta den el mismo resultado.
- **Criterios:** `prefill_brand_kit(tenant_id, brand_id, network, handle)` reproduce `BrandConnectState.analyze`, `apply_logo_colours` y `suggest_hashtags`; escribe solo en `brand_kit_details.connect/profile` como propuesta; guarda procedencia (versión de lectura, modelo, versión del prompt); `analyze` del asistente la llama; test offline con respuestas grabadas; tope de llamadas por ejecución.
- **Fuera de alcance:** logo o avatar generados con IA; lectura de sitio web.

### PB-4 — Precarga encolada al completar «Datos»
- **Historia:** Como dueño de un local recién dado de alta, quiero encontrar mi identidad de marca ya propuesta al entrar, para empezar a crear publicaciones sin llenar formularios.
- **Criterios:** después de `start_invitation`, si hay «Cuenta de Instagram»: `start_brand_kit_draft` (reservado, PB-0) y un trabajo encolado que procesa `webhook-worker`; ajuste de encendido (p. ej. `QUALIFY_ALTA_PREFILL_ENABLED`) **apagado por defecto** y, apagado, el Alta funciona como hoy; tope de costo por Alta configurable sin valor fijado en el código, y sin tope configurado la precarga no corre; **no se enciende en producción hasta que el fundador fije el tope con los datos de PB-6**; clave de idempotencia ítem + usuario de Instagram (completar «Datos» dos veces no duplica ni cobra dos veces); un solo reintento; procedencia con el id del ítem de Meegle; el registro adopta el borrador con la propuesta; comentario en el ítem «Identidad de marca propuesta» al terminar; sin «Cuenta de Instagram», cuenta privada o lectura fallida: la invitación sale igual, el cliente completa el asistente como hoy y el ítem lleva un comentario con el motivo («No se precargó la identidad de marca: no hay cuenta de Instagram en el Alta.» / «…: la cuenta de Instagram es privada.» / «…: no se pudo leer la cuenta de Instagram.»), con test de los tres casos; la precarga nunca bloquea ni retrasa la invitación.
- **Fuera de alcance:** completar el nodo «Kit de marca listo» automáticamente.

### PB-5 — Revisar y aprobar la propuesta en el primer ingreso
- **Historia:** Como dueño de una heladería que entra por primera vez, quiero ver la identidad de marca que me prepararon y aprobarla o cambiarla, para que nada salga con mi marca sin que yo lo vea.
- **Criterios:** si hay propuesta pendiente, la pantalla de identidad de marca la muestra con este texto literal:
  - Aviso: «Preparamos una propuesta de tu identidad de marca a partir de tu cuenta de Instagram @{usuario}. Revísala y apruébala para empezar a crear publicaciones.»
  - Botones: «Aprobar», «Cambiar», «Empezar de cero».
  - Al aprobar: «Listo. Guardamos tu identidad de marca.»
  - Si no se pudo leer la cuenta: «No pudimos leer tu cuenta de Instagram. Completa tu identidad de marca en unos pasos.»
  - Si la cuenta es privada: «Tu cuenta de Instagram es privada, así que no pudimos leerla. Completa tu identidad de marca en unos pasos.»
  - Nada se usa para generar piezas hasta «Aprobar»; funciona en celular; revisión local de ux-designer antes del PR; aislamiento por tenant con test.
- **Fuera de alcance:** rediseñar el asistente completo (épica UX m-24842956).

### PB-6 — Medir el costo real por Alta y proponer el tope (bloquea el encendido de PB-4)
- **Historia (técnica):** Como fundador, quiero saber cuánto cuesta preparar cada identidad de marca, para fijar un tope con datos y no con estimaciones.
- **Criterios:** corrida sobre 5 cuentas reales administradas por el fundador; créditos de ScrapeCreators y tokens de Claude medidos; resultado en `docs/modelos-generativos/pruebas.md` (`qualify-measure`); precios del proveedor verificados; propuesta de tope por Alta entregada al fundador con su justificación; el tope que fije el fundador queda registrado en §5.
- **Fuera de alcance:** mostrar el costo en Meegle (m-24823681).

## 4. Mapa de tickets

| # | Ticket | Título | Dueño | Prioridad · talla | Bloqueado por |
|---|---|---|---|---|---|
| Épica | [m-24852192](https://project.larksuite.com/5h2wsx/story/detail/24852192) | Épica — Identidad de marca precargada desde el Alta de cliente | — | — | — |
| PB-0 | [m-24852193](https://project.larksuite.com/5h2wsx/issue/detail/24852193) | Altas en Meegle: borradores de identidad de marca reservados a la invitación | backend | P1 · S | — |
| PB-1 | [m-24852194](https://project.larksuite.com/5h2wsx/issue/detail/24852194) | Altas en Meegle: campo «Cuenta de Instagram» en el Alta de cliente | backend | P1 · S | — |
| PB-2 | [m-24852195](https://project.larksuite.com/5h2wsx/issue/detail/24852195) | Brand Kit: mover lectura de perfil, paleta del logo y semillas a packages/api | creative | P1 · S | — |
| PB-3 | [m-24852197](https://project.larksuite.com/5h2wsx/issue/detail/24852197) | Brand Kit: prefill_brand_kit sin Reflex, reutilizado por el asistente web | creative | P1 · M | m-24852195 |
| PB-4 | [m-24852198](https://project.larksuite.com/5h2wsx/issue/detail/24852198) | Altas en Meegle: precargar la identidad de marca al completar «Datos» | backend | P1 · M | m-24852193, m-24852194, m-24852197, m-24852200 (encendido) |
| PB-5 | [m-24852199](https://project.larksuite.com/5h2wsx/issue/detail/24852199) | Brand Kit: revisar y aprobar la identidad de marca propuesta en el primer ingreso | ui (+ ux) | P1 · M | m-24852198 |
| PB-6 | [m-24852200](https://project.larksuite.com/5h2wsx/issue/detail/24852200) | Altas en Meegle: medir el costo real de la precarga por Alta y fijar el tope | datasci | P1 · S | m-24852197 |

Origen: [m-24823674](https://project.larksuite.com/5h2wsx/issue/detail/24823674), cerrado como Done el 2026-10-24 con un comentario que apunta a esta épica. Meegle no tiene un campo que enlace una Feature con otra, así que el vínculo con la épica de altas m-24786482 quedó como comentario en las dos épicas y en la descripción de m-24852192. Las dependencias están cargadas en el campo «Bloqueado por».

## 5. Decisiones del fundador (Herwin, 2026-10-24)

1. **Diseño de §2: aprobado** tal como se propuso, incluido PB-0 (un borrador del Alta solo se adopta por la invitación de ese mismo Alta).
2. **Tope de costo: sin valor fijo todavía.** Se decide después de medir: PB-6 entrega el costo real y una propuesta de tope. PB-4 sale con la precarga **apagada por defecto** y no se enciende en producción hasta que el fundador fije el tope. PB-6 sube a P1 porque bloquea la salida. Se descarta la propuesta de US$0,10.
   - **Tope fijado por el fundador el 2026-10-25: US$0,15 por Alta** (`QUALIFY_ALTA_PREFILL_MAX_USD=0.15`), con base en la medición [PB6-001](modelos-generativos/pruebas.md#pb6-001) (media medida US$0,0275, máximo US$0,0375).
   - Hoy el tope limita llamadas, no tokens: antes de encender la precarga falta un límite duro de tokens y de turnos en el camino del Alta.
   - La precarga sigue **apagada** en producción hasta que ese límite exista.
3. **Sin Instagram, cuenta privada o lectura fallida:** la invitación se envía igual; el cliente completa el asistente como hoy; y el ítem del Alta en Meegle lleva un comentario que dice que no hubo precarga y por qué.
4. **m-24823674:** cerrado como reemplazado por m-24852192, con un comentario que apunta a la nueva épica. m-24852192 queda vinculada a la épica de altas m-24786482.

**Decisiones del 2026-10-25:**

5. **Primer ingreso «Esto es lo que vimos en tu Instagram»** (propuesta de UX con los datos medidos de ScrapeCreators): borradores hechos con IA de «qué te hace distinto», «quién te compra» y el tono (opción B1). El dueño confirma cada uno.
6. **«Cada cuánto publicas» y «La que más gustó»** se muestran solo si la cuenta publicó en los últimos 30 días. En TikTok se muestra «El más visto» (+1 crédito).
7. **Enlaces del perfil:** «Pedir por WhatsApp» con el número enmascarado. El número completo queda solo en el tenant: fuera de los registros y nunca va a BytePlus.
8. **Aviso para TikTok:** se decide cuando llegue TikTok.

## 6. Revisión pendiente

- data-scientist-fde: costo medido en PB-6 ([PB6-001](modelos-generativos/pruebas.md#pb6-001), 2026-10-25, precios verificados). El tope ya está fijado (§5.2). El encendido en producción espera el límite duro de tokens.
