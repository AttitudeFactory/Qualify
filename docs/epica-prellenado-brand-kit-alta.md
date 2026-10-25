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
- Ola 2 (§7): falta el desafío de principal-architect (factibilidad contra el código, dependencias ocultas) y de data-scientist-fde (costo y medición de B1) antes de crear los tickets.

---

## 7. Ola 2 — «Esto es lo que vimos en tu Instagram»

`[BORRADOR · product-owner · 2026-10-25 · sin crear en Meegle: el fundador aprueba primero]`

**Evidencia común a todas las historias:** decisiones del fundador del 2026-10-25 (§5 puntos 5–8 y
las del encargo de esta ola, abajo); propuesta de UX v2 «Ya saben de mi marca» (ux-designer,
2026-10-25) con su maqueta de 360 px; descubrimiento de canales de ScrapeCreators medido con la CLI
(2026-10-24, 12 créditos); medición de costo [PB6-001](modelos-generativos/pruebas.md#pb6-001); y el
código de `main`: `creative/brand_prefill.py`, `creative/brand_prefill_review.py`,
`referentes/scrapecreators_client.py`, `hashtags/from_profile.py`, `Qualify/brand_proposal.py`,
`brand_proposal_vm.py`, `brand_minimal.py`. La propuesta de UX y el descubrimiento viven hoy fuera
del repositorio (carpeta de trabajo de la sesión): ver la pregunta abierta 1.

**Decisiones del fundador que esta ola codifica (Herwin, 2026-10-25):**

1. **B1:** una sola llamada de IA —se amplía la de rubro que ya existe (`from_profile.generate`),
   sin una llamada aparte si se puede evitar— redacta «qué te hace distinto», «quién te compra» y el
   tono a partir de los textos de las publicaciones. El dueño confirma cada borrador («Sí, así es»).
   Sin publicaciones, llegan vacíos con un ejemplo del rubro. Se mide (`qualify-measure`) y cabe en
   el tope de US$0,15 por Alta.
2. «Cada cuánto publicas» y «La que más gustó» solo si la cuenta publicó en los últimos 30 días. En
   TikTok, «El más visto» (+1 crédito), **cuando llegue TikTok**.
3. Enlaces de la bio: «Pedir por WhatsApp» con el número enmascarado; el número completo solo en el
   tenant, nunca en registros, nunca a BytePlus.
4. El aviso de TikTok se decide cuando llegue TikTok: el diseño y el modelo de datos no dependen de
   la red, pero **TikTok no se construye ahora**.
5. Después de «Aprobar», en lugar de «Paso 2 de 5»: «Te faltan 3 cosas que solo tú sabes» → tres
   pantallas de una pregunta → «Tu marca está lista» → «Crear mi primera publicación». Es el flujo
   largo de la propuesta de UX; la «alternativa corta» queda descartada.

**Ya en Meegle, no se duplican:** [m-24852537](https://project.larksuite.com/5h2wsx/issue/detail/24852537)
(foto de perfil a R2; OL2-2 se apoya en ella), [m-24852538](https://project.larksuite.com/5h2wsx/issue/detail/24852538)
(memoria de `webhook-worker`), [m-24852539](https://project.larksuite.com/5h2wsx/issue/detail/24852539)
(precios en caché).

**Hallazgo de esta revisión:** el límite duro de tokens y de turnos que §5.2 exige antes de encender
la precarga **no tiene rama ni PR** en el disco. B1 agrega salida a la misma corrida, así que se
propone como OL2-0 (si ya tiene ticket, se enlaza en vez de crearlo).

Todas: tipo **Issue**, plantilla Default Issue, Feature [m-24852192](https://project.larksuite.com/5h2wsx/story/detail/24852192),
Reporter y Assignee Herwin (reasignar al tomarla). Código: `just ci-test` verde, aislamiento por
tenant con test, procedencia en todo dato derivado. Textos nuevos: **BORRADOR** hasta que el
fundador apruebe la tabla de §7.8; los cinco textos aprobados de PB-5 se mantienen literales.

### 7.0 Resumen

| # | Título en Meegle | Etiquetas | Prioridad · talla | Dueño | Depende de |
|---|---|---|---|---|---|
| OL2-0 | Brand Kit: límite duro de tokens y turnos en la precarga del Alta | Deuda técnica | P1 · S | creative | — (bloquea el encendido de PB-4 y de B1) |
| OL2-1 | Brand Kit: guardar en la propuesta lo que hoy descartamos del perfil | Improvement | P1 · M | creative (+ backend en `referentes/`) | — |
| OL2-2 | Brand Kit: copiar las miniaturas de las publicaciones a R2 en la precarga | Improvement | P1 · S | creative | OL2-1, m-24852537 |
| OL2-3 | Brand Kit: borradores de «qué te hace distinto», «quién te compra» y el tono en la llamada de rubro (B1) | Feature | P1 · M | creative | OL2-0 |
| OL2-4 | Brand Kit: medir B1 (calidad y costo) antes de encenderlo | Testing | P1 · S | datasci | OL2-3 |
| OL2-5 | Brand Kit: pantalla «Esto es lo que vimos en tu Instagram» con «Corregir» por fila | Feature, UI | P1 · L | ui (+ creative en `brand_prefill_review`, + revisión ux) | OL2-1, OL2-2 |
| OL2-6 | Brand Kit: después de aprobar, «Te faltan 3 cosas que solo tú sabes» y «Tu marca está lista» | Feature, UI | P1 · M | ui (+ revisión ux) | OL2-5; borradores: OL2-3 + OL2-4 |

Orden sugerido: OL2-0 y OL2-1 en paralelo → OL2-2 y OL2-3 → OL2-4 y OL2-5 → OL2-6. OL2-6 puede
salir antes que OL2-4 con las preguntas vacías y el ejemplo del rubro: el borrador se enciende
después sin cambiar la pantalla.

### 7.1 OL2-0 — Brand Kit: límite duro de tokens y turnos en la precarga del Alta

Tarea técnica · Deuda técnica · **P1 · S** · creative-engineer · bloquea el encendido de PB-4 (m-24852198)

**Contexto**
PB6-001 midió que `CallCaps` limita llamadas, no tokens: `select_hashtags` puede llegar a 8 turnos
de hasta 16.000 tokens de salida, con un techo teórico de ≈ US$1,7 por Alta frente al tope de
US$0,15 (§5.2). El fundador dejó la precarga apagada hasta que exista este límite. B1 (OL2-3)
agrega salida a la llamada de rubro, así que el límite va antes.

**Qué hay que hacer**
- En el camino del Alta (`brand_prefill.prefill_brand_kit` desde el worker), fijar `max_tokens` y
  número de turnos por paso para que la suma de los peores casos quepa en
  `QUALIFY_ALTA_PREFILL_MAX_USD` (0,15) con los precios de `claude_tools.PRICES`.
- El asistente web conserva sus valores actuales salvo decisión del dueño del módulo.

**Cómo verificarlo**
Un test offline calcula el costo máximo posible de una corrida del Alta con los límites configurados
y falla si supera el tope; `just eval-precarga` sin cambio de resultados.

**Criterios de aceptación**
- [ ] El peor caso calculado (créditos máximos + cada paso con su `max_tokens` y sus turnos llenos)
  es ≤ US$0,15, con test.
- [ ] Una corrida que llega al límite de turnos o de tokens termina con un resultado registrado (no
  una excepción sin manejar) y la invitación no se ve afectada.
- [ ] Resultado anotado en `docs/modelos-generativos/pruebas.md` (`qualify-measure`).
- [ ] `just ci-test` verde.

**Fuera de alcance**
- Encender la precarga en producción (decisión del fundador, después de este ticket).

### 7.2 OL2-1 — Brand Kit: guardar en la propuesta lo que hoy descartamos del perfil

Feature/mejora · Improvement · **P1 · M** · creative-engineer (toca `referentes/scrapecreators_client.py`, de backend) · sin dependencias

**Contexto**
La lectura del perfil ya trae (y pagamos) los enlaces de la bio, las 12 publicaciones recientes con
sus cifras, los lugares etiquetados y el total de publicaciones, pero la instantánea
(`SNAPSHOT_SCHEMA = 4`) y la propuesta los descartan. La pantalla de OL2-5 los necesita. Además,
hoy Instagram gasta 2 créditos cuando el perfil ya trae las 12 publicaciones.

**Qué se quiere**
Como dueño de un local de comida que entra por primera vez, quiero ver mis publicaciones, mis
enlaces y de qué publico, para reconocer mi marca en lo que Qualify preparó.

**Propuesta**
- Subir `SNAPSHOT_SCHEMA` a 5 y guardar, con nombres que no dependen de la red, en la instantánea y
  en `proposal.profile`: `stable_id`, `links[{title, url, kind: whatsapp|web|social|other}]`,
  `recent_media[{id, url, kind, taken_at, caption, likes, comments, views, place, is_owner}]`,
  `top_media_ids[]` + `top_media_basis` («últimas 12»), `top_hashtags`, `posts_count`,
  `total_likes` (nulo en Instagram), `category` + `category_es`,
  `place_hint{city, country_code, source: bio|tag}`, `posted_last_30d` y `posts_per_week`.
- Instagram: leer las 12 publicaciones de `edge_owner_to_timeline_media` del perfil y pedir
  `user-posts` solo si las 12 caben en la ventana de 7 días de las métricas (cuenta muy activa).
- Categoría traducida con una tabla fija; si no está en la tabla, `category_es` queda vacío.
- Enlace de WhatsApp: el número completo solo dentro del documento del tenant.

**Criterios de aceptación**
- [ ] Con respuestas grabadas de Instagram (cuenta con 12 publicaciones, cuenta con 0 y cuenta con
  enlace `wa.me`), la propuesta trae todos los campos de arriba; con 0 publicaciones → listas
  vacías y `posted_last_30d = false`, nunca un error.
- [ ] Instagram típico = **1 crédito** por Alta (antes 2), medido en `PrefillUsage` y comprobado con
  `just sc balance` antes y después de una corrida real; el comando va en el PR.
- [ ] «La que más gustó» = la de más me gusta + comentarios de las últimas 12, solo entre las
  publicaciones del dueño (`is_owner`: las colaboraciones ajenas no cuentan).
- [ ] `posts_per_week` y `top_media_ids` se calculan solo si hubo al menos una publicación en los
  últimos 30 días; si no, quedan nulos.
- [ ] Una cuenta con `is_professional_account = false` no guarda enlaces de tipo `whatsapp`.
- [ ] El número de WhatsApp no aparece en los registros, en `provenance` ni en lo que
  `brand_context.build_context` entrega a la generación (BytePlus), con un test para cada uno.
- [ ] Una instantánea de esquema 4 en `creator_profile_cache` se trata como vencida y se vuelve a leer.
- [ ] Procedencia: `snapshot_schema` y `PREFILL_VERSION` nuevos en el documento.
- [ ] `just ci-test` verde; aislamiento por tenant con test.

**Fuera de alcance**
- Miniaturas en R2 (OL2-2). TikTok (`popular`, «El más visto», portadas): cuando llegue TikTok.
- Leer el Linktree o la web enlazada.

### 7.3 OL2-2 — Brand Kit: copiar las miniaturas de las publicaciones a R2 en la precarga

Feature/mejora · Improvement · **P1 · S** · creative-engineer · depende de OL2-1 y de m-24852537

**Contexto**
Las URL de imagen de Instagram vencen a las ~104–108 h (las de TikTok, a las ~23 h). Si el dueño
entra cinco días después del Alta, la cuadrícula sale rota. m-24852537 resuelve la foto de perfil;
esta historia extiende el mismo mecanismo a las miniaturas.

**Qué se quiere**
Como dueño de una heladería que entra días después de su Alta, quiero ver mis publicaciones en la
pantalla, para no encontrar recuadros vacíos.

**Propuesta**
- En el mismo trabajo del Alta, descargar hasta 6 miniaturas (~480 px) con las reglas de
  `fetch_picture` (solo hosts del CDN, tope de bytes, redirecciones a mano), subirlas a R2 bajo el
  prefijo del tenant y guardar `thumb_r2_key` en cada elemento de `recent_media`.

**Criterios de aceptación**
- [ ] 0 créditos extra de ScrapeCreators (nunca `--download-media`, que cuesta 10 por publicación).
- [ ] Una miniatura que no se descarga queda sin `thumb_r2_key` y la corrida sigue; la pantalla la
  oculta, nunca muestra un recuadro roto.
- [ ] Las claves de R2 están bajo el prefijo del tenant y siguen la retención de ADR 39, con test.
- [ ] Repetir la precarga del mismo Alta no duplica objetos en R2 (clave idempotente por publicación).
- [ ] `just ci-test` verde.

**Fuera de alcance**
- La foto de perfil (m-24852537). Videos completos.

### 7.4 OL2-3 — Brand Kit: borradores de «qué te hace distinto», «quién te compra» y el tono (B1)

Feature/mejora · Feature · **P1 · M** · creative-engineer · depende de OL2-0

**Contexto**
Decisión 1 del fundador (2026-10-25). Hoy, después de aprobar, el dueño encuentra dos campos vacíos
y una frase por escribir. La llamada de rubro (`from_profile.generate`, `claude-sonnet-5`, 1 turno,
US$0,003–0,005 medidos en PB6-001) ya lee la bio y los textos de las publicaciones.

**Qué se quiere**
Como dueño de un local de shawarma, quiero encontrar en borrador las tres cosas que solo yo sé, para
confirmarlas con un toque en lugar de escribirlas desde cero.

**Propuesta**
- Ampliar la herramienta de `from_profile.generate` con `distinto`, `quien_compra`, `frase_ejemplo`
  y `tono` (los valores de los deslizadores que ya usa «Cómo hablas»), en la misma llamada, solo con
  frases sacadas de lo que el negocio escribe; vacío cuando no hay base.
- Sin publicaciones (o con menos de 3 textos): no se piden borradores; la propuesta los lleva vacíos
  y la pantalla muestra el ejemplo del rubro (§7.8).
- Guardar los borradores en la propuesta (`proposal.drafts`), nunca en lo que lee la generación
  hasta que el dueño los confirme (OL2-6).

**Criterios de aceptación**
- [ ] Sigue siendo **una** llamada a Claude para rubro + borradores (`PrefillUsage.claude_calls` no sube).
- [ ] Con respuestas grabadas: cuenta con ≥ 3 textos → los cuatro borradores; cuenta con 0
  publicaciones (aunque tenga bio) → los cuatro vacíos, sin llamada extra.
- [ ] Un borrador nunca nombra precios, direcciones, teléfonos ni datos que no estén en los textos
  (test con un caso trampa grabado).
- [ ] El asistente web (`propose=False`) y las etiquetas siguen dando el mismo resultado (tests
  existentes verdes).
- [ ] Versión de prompt nueva en la procedencia (`rubro_prompt_version`).
- [ ] Apagado por un ajuste (p. ej. `QUALIFY_ALTA_PREFILL_DRAFTS_ENABLED`, apagado por defecto)
  hasta que OL2-4 lo apruebe.
- [ ] `just ci-test` verde.

**Fuera de alcance**
- La evaluación de calidad y costo (OL2-4). Borradores para TikTok.

### 7.5 OL2-4 — Brand Kit: medir B1 (calidad y costo) antes de encenderlo

Tarea técnica · Testing · **P1 · S** · data-scientist-fde · depende de OL2-3

**Contexto**
El fundador pidió medir B1 con `qualify-measure` y que quepa en US$0,15 por Alta. Riesgo R7 de la
propuesta de UX: borradores que inventan.

**Qué hay que hacer**
- Golden set con las 6 cuentas de PB6-001 y al menos 4 con publicaciones (comida, heladería,
  inmobiliaria, agencia de viajes), etiquetado a mano: ¿el borrador sale del texto del negocio?
  ¿lo aceptaría el dueño?
- Medir tokens y US$ por Alta con B1 encendido, en vivo y con caché.

**Cómo verificarlo**
`just eval-precarga` (o un eval nuevo en `packages/api/evals/`), con el resultado en
`docs/modelos-generativos/pruebas.md` y en la ficha del modelo.

**Criterios de aceptación**
- [ ] 0 borradores con datos inventados en el golden set; el porcentaje «lo aceptaría» queda
  anotado y el umbral para encender lo fija el fundador.
- [ ] Costo medio y máximo por Alta con B1 anotados; máximo observado ≤ US$0,15.
- [ ] Recomendación de encendido (sí / no / qué cambiar) entregada al fundador.

**Fuera de alcance**
- Encender B1 en producción (decisión del fundador).

### 7.6 OL2-5 — Brand Kit: pantalla «Esto es lo que vimos en tu Instagram» con «Corregir» por fila

Feature/mejora · Feature, UI · **P1 · L** · reflex-ui-engineer (+ creative-engineer para
`edit_prefill_field` en `brand_prefill_review.py`; revisión local de ux-designer antes del PR) ·
depende de OL2-1 y OL2-2

**Contexto**
Pedido del fundador (2026-10-25): «que viera lo que ya obtuvimos de su perfil para generar esa
sensación de asombro». Hoy la tarjeta de PB-5 (`Qualify/brand_proposal.py`) muestra cuenta, rubro,
lugar, colores y etiquetas. Maqueta de 360 px de ux-designer.

**Qué se quiere**
Como dueño de una heladería que entra por primera vez, quiero ver lo que Qualify leyó de mi cuenta y
corregir lo que esté mal, para aprobar una identidad de marca que reconozco como mía.

**Propuesta**
- Reemplaza la tarjeta de PB-5 con primitivas que ya existen (`card`, `callout`, `media_thumb`,
  `tag`, `drawer`, `kv`). Orden: aviso literal → cuenta (foto, nombre, seguidores, publicaciones) →
  cuadrícula de 6 → bio y enlaces → filas con fuente y «Corregir» (a qué te dedicas, dónde estás,
  tu logo, tus colores) → de qué publicas, cada cuánto, etiquetas sugeridas → botones literales y
  nota de privacidad.
- `edit_prefill_field(tenant_id, brand_id, field, value)` en `brand_prefill_review`, bajo el mismo
  bloqueo `FOR UPDATE` que `approve_prefill`: cambia la propuesta, no aprueba.

**Criterios de aceptación**
- [ ] Textos aprobados, literales: el aviso «Preparamos una propuesta de tu identidad de marca a
  partir de tu cuenta de Instagram @{usuario}. Revísala y apruébala para empezar a crear
  publicaciones.» y los botones «Aprobar», «Cambiar», «Empezar de cero».
- [ ] Textos nuevos: los de §7.8 marcados OL2-5, una vez aprobados por el fundador.
- [ ] Cada bloque sin datos se oculta; **ninguna cifra en cero** en pantalla. Cuenta sin
  publicaciones: sin cuadrícula, sin «La que más gustó», sin frecuencia, y con la línea T14.
- [ ] «Cada cuánto publicas» y «La que más gustó» solo con `posted_last_30d = true`; la miniatura
  marcada dice «La que más gustó» con texto, no solo con color.
- [ ] «Pedir por WhatsApp» muestra el número enmascarado (código de país + dos últimas cifras,
  p. ej. «+58 ••• ••12»); el número completo no llega al navegador (test sobre el estado de Reflex).
- [ ] La categoría se muestra solo si tiene traducción (`category_es`).
- [ ] «Corregir» abre un cajón con un solo campo lleno; «Guardar» cambia la propuesta y la fila;
  «Cancelar» no cambia nada; corregir no aprueba; un doble toque o una segunda pestaña no duplica
  (test del bloqueo).
- [ ] Nada se usa para generar piezas hasta «Aprobar» (igual que PB-5).
- [ ] Funciona a 360 px sin desplazamiento horizontal; miniaturas con texto alternativo.
- [ ] Revisión local de ux-designer, con sus sugerencias en la sección «Sugerencias de UX» del PR.
- [ ] `just ci-test` verde; aislamiento por tenant con test.

**Fuera de alcance**
- La pantalla de TikTok y su aviso (decisión 4). El flujo después de aprobar (OL2-6).

### 7.7 OL2-6 — Brand Kit: después de aprobar, «Te faltan 3 cosas que solo tú sabes» y «Tu marca está lista»

Feature/mejora · Feature, UI · **P1 · M** · reflex-ui-engineer (revisión local de ux-designer) ·
depende de OL2-5; los borradores, de OL2-3 + OL2-4

**Contexto**
Hoy «Aprobar» cae en «Paso 2 de 5 · Tu negocio y rubro» con dos campos vacíos, y se lee como «¿no
estaba hecho?» (propuesta de UX §2). Decisión 5 del fundador.

**Qué se quiere**
Como dueño de una agencia de viajes que acaba de aprobar su propuesta, quiero ver que solo me faltan
tres respuestas y contestarlas una por una, para terminar mi marca y crear mi primera publicación.

**Propuesta**
- Pantalla «te faltan» → tres pantallas de una pregunta («¿Qué te hace distinto?», «¿Quién te
  compra?», «¿Cómo le dirías a un cliente que llegó algo nuevo?» con el tono opcional) → «Tu marca
  está lista». Se reutilizan los campos de `brand_minimal.py`; terminar llama a
  `brand_finish.save_brand_kit` como hoy.
- Con borrador (OL2-3 encendido): el campo llega lleno, con «Sí, así es» y «Corregir». Sin
  borrador: vacío, con el ejemplo del rubro.

**Criterios de aceptación**
- [ ] Arriba de la primera pantalla, literal: «Listo. Guardamos tu identidad de marca.»
- [ ] Después de «Aprobar» no aparece «Paso N de 5»; el contador es «{n} de 3».
- [ ] «Lo hago después» guarda lo respondido y deja el kit sin terminar (como «Guardar para
  después» hoy); al volver, retoma en la primera pregunta sin responder.
- [ ] «Sí, así es» guarda el borrador como respuesta del dueño, y solo entonces llega a lo que lee la
  generación (`brand_context.build_context`), con test.
- [ ] Sin publicaciones: campos vacíos con el ejemplo del rubro (§7.8) como texto de ayuda, nunca
  como respuesta guardada.
- [ ] Siempre se puede volver atrás sin perder lo escrito.
- [ ] «Crear mi primera publicación» abre Crear pieza; «Ver mi identidad de marca» abre la identidad
  de marca terminada.
- [ ] «Cambiar» y «Empezar de cero» siguen abriendo los pasos como en PB-5.
- [ ] Textos nuevos de §7.8 marcados OL2-6, una vez aprobados; funciona a 360 px.
- [ ] Revisión local de ux-designer; `just ci-test` verde; aislamiento por tenant con test.

**Fuera de alcance**
- Rediseñar «Cambiar» / «Empezar de cero» (épica UX m-24842956). TikTok.

### 7.8 Textos nuevos — BORRADOR para que el fundador apruebe

Se conservan literales (aprobados en PB-5): el aviso de Instagram, «Aprobar», «Cambiar», «Empezar
de cero», «Listo. Guardamos tu identidad de marca.» y los avisos de cuenta ilegible y privada.

| # | Historia | Dónde | Texto propuesto (BORRADOR) |
|---|---|---|---|
| T1 | OL2-5 | Título | Esto es lo que vimos en tu Instagram |
| T2 | OL2-5 | Cifras | {n} seguidores · {n} publicaciones |
| T3 | OL2-5 | Cuadrícula · fuente | Tus últimas publicaciones · De tu perfil, hoy. |
| T4 | OL2-5 | Marca en miniatura · fuente | La que más gustó · {n} me gusta. De tus últimas 12. |
| T5 | OL2-5 | Bio · enlaces | Así te presentas · Tus enlaces |
| T6 | OL2-5 | WhatsApp | Pedir por WhatsApp · {número enmascarado} |
| T7 | OL2-5 | Fuente del rubro | Lo leímos en tu descripción y tus publicaciones. |
| T8 | OL2-5 | Fuente del lugar | Lo leímos en tu descripción. / Lo marcaste en {n} publicaciones. |
| T9 | OL2-5 | Logo · fuente | Tu logo: tu foto de perfil · Salen de tu foto de perfil. |
| T10 | OL2-5 | De qué publicas | De qué publicas · Las etiquetas que más usas. |
| T11 | OL2-5 | Frecuencia | Publicas unas {n} veces por semana. |
| T12 | OL2-5 | Sugeridas | Etiquetas que te sugerimos |
| T13 | OL2-5 | Fila · cajón | Corregir · Corrige este dato · Guardar · Cancelar |
| T14 | OL2-5 | Cuenta sin publicaciones | Tu cuenta está empezando. Tus primeras publicaciones las armamos juntos. |
| T15 | OL2-5 | Privacidad (ya existe en `PUBLIC_READ_NOTE`) | Solo miramos lo que ya es público en tu perfil. |
| T16 | OL2-6 | Pantalla «te faltan» | Te faltan 3 cosas que solo tú sabes · Responder ahora · Lo hago después |
| T17 | OL2-6 | Contador | {n} de 3 |
| T18 | OL2-6 | Lista de lo hecho y lo que falta | Tu cuenta · A qué te dedicas · Tu logo y tus colores · Tus etiquetas · Qué te hace distinto · Quién te compra · Cómo le hablas a tus clientes |
| T19 | OL2-6 | Preguntas | ¿Qué te hace distinto? · ¿Quién te compra? · ¿Cómo le dirías a un cliente que llegó algo nuevo? |
| T20 | OL2-6 | Borrador B1 | Lo escribimos leyendo tus publicaciones. Cámbialo si no es así. · Sí, así es · Corregir |
| T21 | OL2-6 | Tono | Ajustar el tono (opcional) |
| T22 | OL2-6 | Ejemplo sin publicaciones (comida) | Por ejemplo: «Hacemos todo el mismo día, con receta de la casa.» · «Familias y oficinas de la zona que piden a domicilio.» · «Llegó el combo nuevo: pruébalo esta semana.» |
| T23 | OL2-6 | Ejemplo (heladería) | Por ejemplo: «Helados de yogur sin azúcar añadida.» · «Gente que cuida lo que come y quiere darse un gusto.» · «Llegó un sabor nuevo: ven a probarlo.» |
| T24 | OL2-6 | Ejemplo (inmobiliaria) | Por ejemplo: «Te acompañamos desde la visita hasta la firma.» · «Familias que buscan su primera casa.» · «Tenemos un apartamento nuevo en la zona que buscabas.» |
| T25 | OL2-6 | Ejemplo (agencia de viajes) | Por ejemplo: «Armamos el viaje completo, tú solo haces la maleta.» · «Parejas y familias que viajan en vacaciones.» · «Abrimos cupos para un destino nuevo.» |
| T26 | OL2-6 | Final | Tu marca está lista · Cada publicación que crees va a salir con tu logo, tus colores y tu forma de hablar. Nada se publica sin que lo apruebes. · Crear mi primera publicación · Ver mi identidad de marca |

Descartado por la decisión 1: «Lo escribimos con lo que dice tu perfil.» (sin publicaciones no hay
borrador). Aplazados con TikTok (decisión 4): su aviso, «Tus últimos videos», «El más visto»,
«{n} reproducciones. De todos tus videos.», «{n} me gusta recibidos» y «Subes unos {n} videos por
semana.».

### 7.9 Preguntas abiertas para el fundador

1. ¿Traemos a `docs/` la propuesta de UX v2, la maqueta y el descubrimiento de ScrapeCreators? Hoy
   solo existen en la carpeta de trabajo de la sesión, y los tickets los citan.
2. «La que más gustó»: además de «publicó en los últimos 30 días», ¿exigimos al menos 3
   publicaciones (regla de la propuesta de UX)?
3. B1 con bio pero sin publicaciones (Bianki hoy): la decisión dice vacío con ejemplo. ¿Confirmas que
   la bio sola no basta para un borrador?
4. Ejemplos por rubro (T22–T25): ¿bastan estos cuatro rubros para empezar? ¿El resto usa el de
   comida o ninguno?
5. OL2-0: ¿lo aceptas como requisito de esta ola, o el límite duro de tokens ya tiene dueño en otro
   ticket?
