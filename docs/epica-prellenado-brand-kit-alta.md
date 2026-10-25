# Épica — Identidad de marca precargada desde el Alta de cliente

**Fecha:** 2026-10-24 · **Estado:** `[HISTORIAS · implementada · diseño aprobado 2026-10-24 · tope fijado 2026-10-25 (US$0,15 por Alta) · precarga ENCENDIDA en producción desde 2026-10-25 (piloto), sin el límite duro de tokens]` · **Meegle:** épica [m-24852192](https://project.larksuite.com/5h2wsx/story/detail/24852192) (mapa de tickets en §4)
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
   - Hoy el tope limita llamadas, no tokens: falta un límite duro de tokens y de turnos en el camino del Alta.
   - **Encendida en producción el 2026-10-25 por decisión del fundador, sin ese límite** (`QUALIFY_ALTA_PREFILL_ENABLED=1`, `QUALIFY_ALTA_PREFILL_MAX_USD=0.15`, con `just env-push`): los clientes invitados son de la fase piloto y el fundador acepta el riesgo de que un Alta pase algo del tope (un turno de hashtags lleno ≈ US$0,16). El límite duro de tokens sigue pendiente y debe estar antes de abrir las Altas fuera del piloto.
3. **Sin Instagram, cuenta privada o lectura fallida:** la invitación se envía igual; el cliente completa el asistente como hoy; y el ítem del Alta en Meegle lleva un comentario que dice que no hubo precarga y por qué.
4. **m-24823674:** cerrado como reemplazado por m-24852192, con un comentario que apunta a la nueva épica. m-24852192 queda vinculada a la épica de altas m-24786482.

**Decisiones del 2026-10-25:**

5. **Primer ingreso «Esto es lo que vimos en tu Instagram»** (propuesta de UX con los datos medidos de ScrapeCreators): borradores hechos con IA de «qué te hace distinto», «quién te compra» y el tono (opción B1). El dueño confirma cada uno.
6. **«Cada cuánto publicas» y «La que más gustó»** se muestran solo si la cuenta publicó en los últimos 30 días. En TikTok se muestra «El más visto» (+1 crédito).
7. **Enlaces del perfil:** «Pedir por WhatsApp» con el número enmascarado. El número completo queda solo en el tenant: fuera de los registros y nunca va a BytePlus.
8. **Aviso para TikTok:** se decide cuando llegue TikTok.

## 6. Revisión pendiente

- data-scientist-fde: costo medido en PB-6 ([PB6-001](modelos-generativos/pruebas.md#pb6-001), 2026-10-25, precios verificados). El tope ya está fijado (§5.2). Encendida en producción el 2026-10-25 para el piloto, sin el límite duro de tokens (§5.2).
- Ola 2 (§7): revisada por principal-architect y data-scientist-fde el 2026-10-25 (§7.11); sus cambios ya están en las historias. Tickets creados el 2026-10-25 (§7.0); los 26 textos nuevos fueron aprobados por el fundador el 2026-10-25 (§7.10).

---

## 7. Ola 2 — «Esto es lo que vimos en tu Instagram»

`[HISTORIAS EN MEEGLE · product-owner · 2026-10-25 · revisadas por arquitectura y datos · creadas con el visto bueno del fundador el 2026-10-25 · textos nuevos aprobados el 2026-10-25 (§7.10)]`

**Evidencia común a todas las historias:** decisiones del fundador del 2026-10-25 (§5 puntos 5–8 y
las del encargo de esta ola, abajo); propuesta de UX v2 [`ux-esto-es-lo-que-vimos.md`](ux-esto-es-lo-que-vimos.md)
(ux-designer, 2026-10-25) con su maqueta de 360 px [`maquetas/esto-es-lo-que-vimos.html`](maquetas/esto-es-lo-que-vimos.html);
descubrimiento de ScrapeCreators medido con la CLI [`scrapecreators-canales-perfil.md`](scrapecreators-canales-perfil.md)
(2026-10-24); medición de costo [PB6-001](modelos-generativos/pruebas.md#pb6-001); revisión de
principal-architect y de data-scientist-fde contra `main` (2026-10-25, §7.11).

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

Todas: tipo **Issue**, plantilla Default Issue, Feature [m-24852192](https://project.larksuite.com/5h2wsx/story/detail/24852192),
Reporter y Assignee Herwin (reasignar al tomarla). Código: `just ci-test` verde, aislamiento por
tenant con test, procedencia en todo dato derivado. **Sin migración:** todo vive en JSONB de tablas
que ya tienen RLS. Textos nuevos: **aprobados** por el fundador el 2026-10-25 (tabla de §7.10); los
cinco textos aprobados de PB-5 se mantienen literales.

### 7.0 Resumen

| # | Ticket | Título en Meegle | Etiquetas | Prioridad · talla | Dueño | Depende de |
|---|---|---|---|---|---|---|
| OL2-0 | [m-24854322](https://project.larksuite.com/5h2wsx/issue/detail/24854322) | Brand Kit: medidor en dólares por turno en la precarga del Alta | Deuda técnica | P1 · M | creative | — (bloquea encender PB-4 y B1) |
| OL2-7 | [m-24854323](https://project.larksuite.com/5h2wsx/issue/detail/24854323) | Brand Kit: enmascarar teléfonos antes de enviar la bio y los textos a cualquier proveedor o registro | Bug (los teléfonos ya salen hoy) | P1 · S | creative (+ `security-review`) | — |
| OL2-1a | [m-24854324](https://project.larksuite.com/5h2wsx/issue/detail/24854324) | Referentes: leer las 12 publicaciones y los enlaces de la bio desde el perfil (instantánea 5) | Improvement | P1 · M | backend | — |
| OL2-1b | [m-24854325](https://project.larksuite.com/5h2wsx/issue/detail/24854325) | Brand Kit: «lo que vimos» en la propuesta, aparte de lo que se aprueba | Improvement | P1 · M | creative | OL2-1a |
| OL2-3 | [m-24854326](https://project.larksuite.com/5h2wsx/issue/detail/24854326) | Brand Kit: borradores de «qué te hace distinto», «quién te compra» y el tono en la llamada de rubro (B1) | Feature | P1 · M | creative (el mismo dueño que OL2-1b) | OL2-0, OL2-1b, OL2-7 |
| OL2-2 | [m-24854328](https://project.larksuite.com/5h2wsx/issue/detail/24854328) | Brand Kit: copiar las miniaturas a R2 y borrarlas cuando ya no sirven | Improvement | P1 · M | creative | OL2-1b (m-24852537 ya está en Done) |
| OL2-5 | [m-24854329](https://project.larksuite.com/5h2wsx/issue/detail/24854329) | Brand Kit: pantalla «Esto es lo que vimos en tu Instagram» con «Corregir» por fila | Feature, UI | P1 · L | ui (+ creative en `brand_prefill_review`, + revisión ux) | contrato de OL2-1b (empieza con datos de prueba); OL2-2 para las miniaturas reales |
| OL2-6 | [m-24854331](https://project.larksuite.com/5h2wsx/issue/detail/24854331) | Brand Kit: después de aprobar, «Te faltan 3 cosas que solo tú sabes» y «Tu marca está lista» | Feature, UI | P1 · M | ui (+ revisión ux) | — (en paralelo); borradores: OL2-3 + OL2-4 |
| OL2-4 | [m-24854330](https://project.larksuite.com/5h2wsx/issue/detail/24854330) | Brand Kit: medir B1 con un golden set de 30 cuentas antes de encenderlo | Testing | P1 · M | datasci | OL2-3 |

**Enlaces en Meegle:** las dependencias de esta tabla están cargadas en «Bloqueado por», y OL2-6
lleva «Relacionado con» OL2-3 y OL2-4. Meegle no deja enlazar ítems cerrados: m-24852537 (foto de
perfil a R2) y m-24852198 / m-24852200 (PB-4 y su tope) ya están en Done, así que se citan en la
descripción de OL2-2 y de OL2-0, no en los campos.

**Orden (principal-architect):** (1) en paralelo OL2-0, OL2-1a y OL2-7; (2) OL2-1b, que fija el
contrato de `observed`, y luego OL2-3 cuando OL2-0 esté, con el mismo dueño (los dos tocan
`brand_prefill.py`); (3) OL2-2 tras OL2-1b y m-24852537; OL2-5 arranca con datos de prueba en cuanto
el contrato de OL2-1b esté fijo; OL2-6 en paralelo desde el principio; (4) OL2-4 al final.
OL2-6 sale con las preguntas vacías y el ejemplo del rubro; el borrador se enciende después sin
cambiar la pantalla.

### 7.1 OL2-0 ([m-24854322](https://project.larksuite.com/5h2wsx/issue/detail/24854322)) — Brand Kit: medidor en dólares por turno en la precarga del Alta

Tarea técnica · Deuda técnica · **P1 · M** · creative-engineer · bloquea el encendido de PB-4 (m-24852198) y de B1

**Contexto**
PB6-001 midió que `CallCaps` limita llamadas, no tokens: techo teórico ≈ US$1,7 por Alta frente al
tope de US$0,15 (§5.2). Un tope por paso no basta: `select_hashtags` usa `max_tokens = 16000` con
razonamiento (`hashtags/ai.py:457`), y **un solo turno lleno cuesta US$0,16, más que el tope
entero**. El fundador encendió la precarga el 2026-10-25 para el piloto sin este límite (§5.2); hace falta antes de abrir las Altas fuera del piloto.

**Qué hay que hacer**
- Un medidor en dólares por corrida en `claude_tools`, pasado a `create_turn`. Antes de cada turno,
  el peor costo = entrada acumulada × precio de entrada × 1,25 + `max_tokens` × precio de salida.
  Si no cabe en lo que queda, el turno no se hace; si cabe solo con menos salida, se baja
  `max_tokens` a lo que cabe.
- `CallBudget` / `caps_for_budget` pasan a dólares, con los créditos de ScrapeCreators en el mismo saldo.
- Presupuesto por paso (data-scientist-fde): ScrapeCreators 6 créditos (2 con OL2-1a), peor caso
  US$0,011 · rubro + B1 con `max_tokens` 1.500 (hoy 4.000), 2 intentos, entrada ≤ 4k → US$0,046 ·
  etiquetas del catálogo con `max_turns` 3–4 (hoy 8), `max_tokens` 1.200 por turno (hoy 16.000),
  entrada acumulada ≤ 22k → US$0,092 · llamada de creación apagada en el Alta (`claude_calls = 2`)
  → 0. Total ≈ US$0,149.
- `max_turns` y un esfuerzo más bajo llegan hasta `CatalogHashtags.suggest` → `select_hashtags`.
  El arquitecto propone ~3 turnos y datos 4: se elige con `just eval-precarga` el menor que no
  empeore las etiquetas; el medidor garantiza el tope en los dos casos.
- Un corte por `max_tokens` hoy lanza `ClaudeToolError`: en el Alta tiene que caer a las etiquetas
  que dio la llamada de rubro (o a las propias de la cuenta), no fallar.
- Recalcular `CLAUDE_MAX_TURNS` y `MAX_RUN_SECONDS`.
- El asistente web conserva sus valores actuales salvo decisión del dueño del módulo.

**Cómo verificarlo**
Test offline del peor caso; `just eval-precarga` antes y después, con el resultado en
`docs/modelos-generativos/pruebas.md`.

**Criterios de aceptación**
- [ ] El peor caso calculado de una corrida del Alta (créditos máximos + cada turno con su
  `max_tokens` lleno) es ≤ US$0,15, con test.
- [ ] Test: un turno que no cabe en el saldo no se hace; uno que cabe con menos salida sale con el
  `max_tokens` reducido.
- [ ] Test: si el medidor corta las etiquetas del catálogo, la propuesta usa las etiquetas de la
  llamada de rubro o las de la cuenta, y la corrida termina `ok`.
- [ ] La invitación nunca se ve afectada por un corte.
- [ ] `just eval-precarga`: costo y etiquetas antes y después anotados en `pruebas.md`
  (`qualify-measure`).
- [ ] `just ci-test` verde.

**Fuera de alcance**
- Encender la precarga en producción (decisión del fundador, después de este ticket).

### 7.2 OL2-7 ([m-24854323](https://project.larksuite.com/5h2wsx/issue/detail/24854323)) — Brand Kit: enmascarar teléfonos antes de cualquier proveedor o registro

Bug · **P1 · S** · creative-engineer, con la skill `security-review` · sin dependencias

**Contexto**
La decisión 7 del fundador dice que el número completo queda solo en el tenant. Pero la bio y los
textos de las publicaciones traen teléfonos a menudo (las dos cuentas de TikTok medidas los escriben
a mano), y hoy esos textos ya van a Claude, a Langfuse (`_traceable` solo quita imágenes), a la
procedencia y a la bio que lee `brand_context.build_context` (y de ahí, a la generación). Cubrir
solo el enlace de la bio no cumple la decisión (principal-architect, 2026-10-25).

**Qué hay que hacer**
- Una función que enmascara teléfonos (formatos de CO, VE y UY, con y sin `+`, enlaces `wa.me/…`)
  y se aplica antes de cualquier proveedor (Claude, BytePlus), de Langfuse, de los registros y de la
  procedencia.
- El número completo, si hace falta, vive solo en `connect.contact.whatsapp` del tenant.

**Cómo verificarlo**
Tests con bios y textos grabados que llevan teléfonos; revisión con `security-review` en el PR.

**Criterios de aceptación**
- [ ] Test: con una bio y un texto que llevan un teléfono, lo que reciben el cliente de Claude, la
  traza de Langfuse, los registros, la procedencia y `build_context` lleva el número enmascarado.
- [ ] Test: el número completo solo aparece en `connect.contact.whatsapp` del tenant.
- [ ] Sin falsos positivos en precios, fechas y horarios del golden set de textos (test).
- [ ] Hallazgos de `security-review` resueltos o anotados en el PR.
- [ ] `just ci-test` verde.

**Fuera de alcance**
- Correos y direcciones (no se observaron en las 4 cuentas medidas; queda como pregunta para otra ola).

### 7.3 OL2-1a ([m-24854324](https://project.larksuite.com/5h2wsx/issue/detail/24854324)) — Referentes: leer las 12 publicaciones y los enlaces de la bio desde el perfil

Tarea técnica · Improvement · **P1 · M** · backend-engineer · sin dependencias

**Contexto**
`referentes/scrapecreators_client.py` lo comparten el asistente web, Referentes y la precarga. La
lectura del perfil de Instagram ya trae (y pagamos) las 12 publicaciones recientes y los enlaces de
la bio (`bio_links`), pero la instantánea (`SNAPSHOT_SCHEMA = 4`) los descarta y pide aparte
`user-posts`.

**Qué hay que hacer**
- Sacar `recentPosts`, los textos y las etiquetas de los 12 elementos del perfil, y `bio_links`.
  Subir `SNAPSHOT_SCHEMA` a 5.
- Pedir `user-posts` solo si la publicación no fijada más antigua de las 12 sigue dentro de los 7
  días, o si el perfil llegó sin publicaciones.
- Bajar el tope de ScrapeCreators del Alta a 2 pedidos.
- Verificar con la CLI si los 12 textos del perfil llegan completos o cortados; el comando va en el PR.

**Cómo verificarlo**
Tests con respuestas grabadas; `just eval-precarga` antes y después (créditos, etiquetas, tiempo).

**Criterios de aceptación**
- [ ] Con respuestas grabadas (12 publicaciones, 0 publicaciones, cuenta con `wa.me`), la
  instantánea 5 trae publicaciones, textos, etiquetas y enlaces; 0 publicaciones → listas vacías,
  nunca un error.
- [ ] El asistente web y Referentes dan el mismo resultado (tests existentes verdes).
- [ ] Instagram típico = 1 crédito por Alta, comprobado con `just sc balance` antes y después; la
  caída de señal para las etiquetas (12 publicaciones en vez de hasta 5 páginas) medida con
  `just eval-precarga`, **no se da por supuesto que no cambia nada**.
- [ ] Una instantánea de esquema 4 en caché se vuelve a leer una vez (1 crédito por cuenta,
  anotado en el PR).
- [ ] `just ci-test` verde.

**Fuera de alcance**
- La propuesta y la pantalla (OL2-1b, OL2-5). TikTok.

### 7.4 OL2-1b ([m-24854325](https://project.larksuite.com/5h2wsx/issue/detail/24854325)) — Brand Kit: «lo que vimos» en la propuesta, aparte de lo que se aprueba

Feature/mejora · Improvement · **P1 · M** · creative-engineer · depende de OL2-1a

**Contexto**
La pantalla de OL2-5 necesita lo que leyó la precarga. Pero «Aprobar» copia `proposal["profile"]`
entero a lo que lee la generación (`_decide`, `brand_prefill_review.py:402`): lo que se ponga ahí
termina en las piezas. Por eso lo visto va en una clave aparte que nunca se promueve.

**Qué se quiere**
Como dueño de un local de comida que entra por primera vez, quiero ver mis publicaciones, mis
enlaces y de qué publico, para reconocer mi marca en lo que Qualify preparó.

**Propuesta**
- Clave nueva `proposal.observed`, sin depender de la red: `stable_id`,
  `links[{title, url, kind: whatsapp|web|social|other}]` (WhatsApp ya enmascarado),
  `recent_media[{id, kind, taken_at, caption, likes, comments, views, place, is_owner}]`,
  `top_media_ids[]` + `top_media_basis` («últimas 12»), `top_hashtags`, `posts_count`,
  `total_likes` (nulo en Instagram), `category` + `category_es` (tabla fija),
  `place_hint{city, country_code, source: bio|tag}`, `posted_last_30d`, `posts_per_week`.
- El número completo de WhatsApp, en `connect.contact.whatsapp` (OL2-7).
- Textos cortados a 280 caracteres (documento de ~15 KB); las URL del CDN se borran una vez
  copiadas a R2 (OL2-2).

**Criterios de aceptación**
- [ ] Test: «Aprobar» no copia nada de `observed` a lo que lee la generación; `build_context` no lo ve.
- [ ] `recent_media` y sus cifras no entran en ningún prompt (test).
- [ ] «La que más gustó» = la de más me gusta + comentarios de las últimas 12, solo entre las
  publicaciones del dueño (`is_owner`).
- [ ] `posts_per_week` y `top_media_ids` solo si hubo al menos una publicación en los últimos 30
  días; si no, nulos.
- [ ] Una cuenta con `is_professional_account = false` no guarda enlaces de tipo `whatsapp`.
- [ ] Procedencia: `snapshot_schema` y `PREFILL_VERSION` nuevos en el documento.
- [ ] `just ci-test` verde; aislamiento por tenant con test.

**Fuera de alcance**
- Miniaturas en R2 (OL2-2). TikTok (`popular`, «El más visto», portadas). Leer el Linktree o la web.

### 7.5 OL2-3 ([m-24854326](https://project.larksuite.com/5h2wsx/issue/detail/24854326)) — Brand Kit: borradores de «qué te hace distinto», «quién te compra» y el tono (B1)

Feature/mejora · Feature · **P1 · M** · creative-engineer (el mismo dueño que OL2-1b) · depende de OL2-0, OL2-1b y OL2-7

**Contexto**
Decisión 1 del fundador (2026-10-25). Hoy, después de aprobar, el dueño encuentra dos campos vacíos
y una frase por escribir. La llamada de rubro (`from_profile.generate`, `claude-sonnet-5`, 1 turno,
US$0,003–0,005 medidos en PB6-001) ya lee la bio y los textos.

**Qué se quiere**
Como dueño de un local de shawarma, quiero encontrar en borrador las tres cosas que solo yo sé, para
confirmarlas con un toque en lugar de escribirlas desde cero.

**Propuesta**
- La herramienta ampliada va detrás de un parámetro que **solo enciende el camino del Alta**, con su
  propia versión de prompt; sin él, el asistente web manda exactamente la herramienta de hoy.
- Los borradores van en un objeto aparte `borradores`: `distinto`, `quien_compra`, `frase_ejemplo`
  y `tono` (los deslizadores de «Cómo hablas»). Cada campo puede venir vacío y cada uno trae
  `fuente`, un fragmento literal de los textos del negocio.
- Solo se leen los textos del propio dueño (`is_owner`), nunca colaboraciones; mínimo 3 textos
  contados entre esos. Con menos, no se piden borradores y la pantalla muestra el ejemplo del rubro.
- Validación campo por campo: si la `fuente` no está en los textos, o el campo trae precios,
  teléfonos o direcciones, ese campo queda vacío y el resto sigue (el rubro nunca se pierde).
- Si la respuesta sale cortada con B1 encendido, se reintenta con la herramienta de antes, sin
  borradores.
- Los borradores no llegan a lo que lee la generación hasta que el dueño los confirme (OL2-6).

**Contrato con la pantalla (OL2-6, ya construida — reflex-ui-engineer, 2026-10-25).** La pantalla
lee los borradores de `connect.prefill.proposal.borradores` **solo cuando `connect.prefill.state`
es `approved`** (`Qualify/brand_answers_vm.drafts_from`). Forma que debe escribir OL2-3:

```json
"borradores": {
  "distinto":      {"texto": "Helado de yogur hecho cada mañana.", "fuente": "<fragmento literal>"},
  "quien_compra":  {"texto": "…", "fuente": "…"},
  "frase_ejemplo": {"texto": "…", "fuente": "…"},
  "tono":          {"formal_casual": 70, "sober_enthusiastic": 60, "technical_plain": 80, "brief_elaborate": 30}
}
```

- Claves fijas: `distinto` → «¿Qué te hace distinto?» (`positioning`), `quien_compra` →
  «¿Quién te compra?» (`audience`), `frase_ejemplo` → «¿Cómo le dirías a un cliente que llegó
  algo nuevo?» (primera línea de `do_examples`). `tono` lo lee la pantalla más adelante (hoy no).
- Un campo sin `texto`, con `texto` vacío, o que no sea objeto ni cadena, es **sin borrador**: la
  pregunta sale vacía con el ejemplo del rubro (T22–T25). La pantalla no valida `fuente`; eso es
  de OL2-3.
- El borrador **nunca se escribe en el kit al leerlo**: solo «Sí, así es» lo guarda tal cual, o
  «Corregir» seguido de «Continuar» guarda lo que el dueño dejó en el campo (test en
  `Qualify/test_brand_answers.py`). Sin borradores (B1 apagado) la pantalla funciona igual.

**Criterios de aceptación**
- [ ] Sigue siendo **una** llamada a Claude para rubro + borradores (`PrefillUsage.claude_calls` no sube).
- [ ] Con B1 apagado o fuera del Alta, la herramienta que se envía es idéntica a la de hoy y la
  versión de prompt no cambia (test).
- [ ] Test: una `fuente` que no está en los textos deja ese campo vacío; los demás y el rubro siguen.
- [ ] Test: un campo con precio, teléfono o dirección queda vacío.
- [ ] Test: una respuesta cortada se reintenta sin borradores y la corrida termina `ok`.
- [ ] Con 0–2 textos propios (aunque haya bio): borradores vacíos, sin llamada extra.
- [ ] `just eval-hashtag-ai` sin regresión.
- [ ] Apagado por un ajuste (p. ej. `QUALIFY_ALTA_PREFILL_DRAFTS_ENABLED`, apagado por defecto)
  hasta que OL2-4 lo apruebe.
- [ ] Costo extra estimado +US$0,004–0,006 por Alta (media 0,0275 → ≈ 0,033), dentro de lo que
  OL2-0 asigna al paso de rubro.
- [ ] `just ci-test` verde.

**Fuera de alcance**
- La evaluación (OL2-4). Borradores para TikTok.

### 7.6 OL2-2 ([m-24854328](https://project.larksuite.com/5h2wsx/issue/detail/24854328)) — Brand Kit: copiar las miniaturas a R2 y borrarlas cuando ya no sirven

Feature/mejora · Improvement · **P1 · M** · creative-engineer · depende de OL2-1b y de m-24852537

**Contexto**
Las URL de imagen de Instagram vencen a las ~104–108 h (TikTok, ~23 h). Si el dueño entra cinco días
después del Alta, la cuadrícula sale rota. m-24852537 guarda la foto de perfil en R2; esto extiende
el mismo mecanismo a las miniaturas. Hoy `ObjectGate.delete_prefix` solo permite borrar bajo
`generated/` (ADR 39), así que sin una raíz nueva quedarían objetos huérfanos.

**Qué se quiere**
Como dueño de una heladería que entra días después de su Alta, quiero ver mis publicaciones en la
pantalla, para no encontrar recuadros vacíos.

**Propuesta**
- En el mismo trabajo del Alta, descargar hasta 6 miniaturas (~480 px) con las reglas de
  `fetch_picture` (solo hosts del CDN, tope de bytes, redirecciones a mano) y subirlas a R2 bajo el
  prefijo del tenant; guardar `thumb_r2_key` en `observed.recent_media` y borrar la URL del CDN.
- Una raíz de borrado nueva para las imágenes de la precarga, compartida con m-24852537 (que guarda
  en `t/{tenant}/brand/{brand}/kept/{kind}/…`): acordar un solo nombre con su dueño.
- Las miniaturas se borran al «Aprobar» o «Empezar de cero», y a los 30 días si el dueño nunca entra.
- Apéndice de ADR 39 para la raíz nueva (lo escribe principal-architect).

**Criterios de aceptación**
- [ ] 0 créditos extra de ScrapeCreators (nunca `--download-media`, que cuesta 10 por publicación).
- [ ] Una miniatura que no se descarga queda sin `thumb_r2_key` y la corrida sigue; la pantalla la
  oculta, nunca muestra un recuadro roto.
- [ ] Repetir la precarga del mismo Alta no duplica objetos (clave idempotente por publicación).
- [ ] Test: «Aprobar», «Empezar de cero» y el vencimiento de 30 días borran las miniaturas de ese
  tenant y de ningún otro.
- [ ] Una sola raíz de borrado con m-24852537, anotada en el apéndice de ADR 39.
- [ ] `just ci-test` verde.

**Fuera de alcance**
- La foto de perfil (m-24852537). Videos completos.

### 7.7 OL2-5 ([m-24854329](https://project.larksuite.com/5h2wsx/issue/detail/24854329)) — Brand Kit: pantalla «Esto es lo que vimos en tu Instagram» con «Corregir» por fila

Feature/mejora · Feature, UI · **P1 · L** · reflex-ui-engineer (+ creative-engineer para
`edit_prefill_field` en `brand_prefill_review.py`; revisión local de ux-designer antes del PR) ·
depende del contrato de OL2-1b (empieza con datos de prueba) y de OL2-2 para las miniaturas reales

**Contexto**
Pedido del fundador (2026-10-25): «que viera lo que ya obtuvimos de su perfil para generar esa
sensación de asombro». Hoy la tarjeta de PB-5 (`Qualify/brand_proposal.py`) muestra cuenta, rubro,
lugar, colores y etiquetas. Maqueta: [`maquetas/esto-es-lo-que-vimos.html`](maquetas/esto-es-lo-que-vimos.html).

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
  bloqueo `FOR UPDATE` que `approve_prefill`, que acepta solo una lista fija de campos: cambia la
  propuesta, no aprueba.

**Criterios de aceptación**
- [ ] Textos aprobados, literales: el aviso «Preparamos una propuesta de tu identidad de marca a
  partir de tu cuenta de Instagram @{usuario}. Revísala y apruébala para empezar a crear
  publicaciones.» y los botones «Aprobar», «Cambiar», «Empezar de cero».
- [ ] Textos nuevos: los de §7.10 marcados OL2-5 (aprobados el 2026-10-25).
- [ ] Cada bloque sin datos se oculta; **ninguna cifra en cero** en pantalla. Cuenta sin
  publicaciones: sin cuadrícula, sin «La que más gustó», sin frecuencia, y con la línea T14.
- [ ] «Cada cuánto publicas» y «La que más gustó» solo con `posted_last_30d = true`; la miniatura
  marcada dice «La que más gustó» con texto, no solo con color.
- [ ] El número de WhatsApp se enmascara en el modelo de vista, **antes** del estado de Reflex
  (que viaja al navegador); test sobre el estado: el número completo no está.
- [ ] La categoría se muestra solo si tiene traducción (`category_es`).
- [ ] «Corregir» abre un cajón con un solo campo lleno; «Guardar» cambia la propuesta y la fila;
  «Cancelar» no cambia nada; corregir no aprueba; un campo fuera de la lista fija se rechaza; un
  doble toque o una segunda pestaña no duplica (test del bloqueo).
- [ ] Nada se usa para generar piezas hasta «Aprobar» (igual que PB-5).
- [ ] Funciona a 360 px sin desplazamiento horizontal; miniaturas con texto alternativo.
- [ ] Revisión local de ux-designer, con sus sugerencias en la sección «Sugerencias de UX» del PR.
- [ ] `just ci-test` verde; aislamiento por tenant con test.

**Fuera de alcance**
- La pantalla de TikTok y su aviso (decisión 4). El flujo después de aprobar (OL2-6).

### 7.8 OL2-6 ([m-24854331](https://project.larksuite.com/5h2wsx/issue/detail/24854331)) — Brand Kit: después de aprobar, «Te faltan 3 cosas que solo tú sabes» y «Tu marca está lista»

Feature/mejora · Feature, UI · **P1 · M** · reflex-ui-engineer (revisión local de ux-designer) ·
sin dependencias para empezar; los borradores, de OL2-3 + OL2-4

**Contexto**
Hoy «Aprobar» cae en «Paso 2 de 5 · Tu negocio y rubro» con dos campos vacíos, y se lee como «¿no
estaba hecho?» ([propuesta de UX](ux-esto-es-lo-que-vimos.md) §2). Decisión 5 del fundador.
Funciona también tras la tarjeta actual de PB-5, así que va en paralelo con OL2-5.

**Qué se quiere**
Como dueño de una agencia de viajes que acaba de aprobar su propuesta, quiero ver que solo me faltan
tres respuestas y contestarlas una por una, para terminar mi marca y crear mi primera publicación.

**Propuesta**
- Pantalla «te faltan» → tres pantallas de una pregunta («¿Qué te hace distinto?», «¿Quién te
  compra?», «¿Cómo le dirías a un cliente que llegó algo nuevo?» con el tono opcional) → «Tu marca
  está lista». Se reutilizan los campos de `brand_minimal.py`; terminar llama a
  `brand_finish.save_brand_kit` como hoy.
- Con borrador (OL2-3 encendido): el campo llega lleno, con «Sí, así es» y «Corregir». Sin
  borrador o con un campo vacío: vacío, con el ejemplo del rubro.

**Criterios de aceptación**
- [ ] Arriba de la primera pantalla, literal: «Listo. Guardamos tu identidad de marca.»
- [ ] Después de «Aprobar» no aparece «Paso N de 5»; el contador es «{n} de 3».
- [ ] «Lo hago después» guarda lo respondido y deja el kit sin terminar (como «Guardar para
  después» hoy); al volver, retoma en la primera pregunta sin responder.
- [ ] «Sí, así es» guarda el borrador como respuesta del dueño, y solo entonces llega a lo que lee
  la generación (`brand_context.build_context`), con test.
- [ ] Sin borrador: campo vacío con el ejemplo del rubro (§7.10) como texto de ayuda, nunca como
  respuesta guardada.
- [ ] Siempre se puede volver atrás sin perder lo escrito.
- [ ] «Crear mi primera publicación» abre Crear pieza; «Ver mi identidad de marca» abre la identidad
  de marca terminada.
- [ ] «Cambiar» y «Empezar de cero» siguen abriendo los pasos como en PB-5.
- [ ] Textos nuevos de §7.10 marcados OL2-6 (aprobados el 2026-10-25); funciona a 360 px.
- [ ] Revisión local de ux-designer; `just ci-test` verde; aislamiento por tenant con test.

**Fuera de alcance**
- Rediseñar «Cambiar» / «Empezar de cero» (épica UX m-24842956). TikTok.

### 7.9 OL2-4 ([m-24854330](https://project.larksuite.com/5h2wsx/issue/detail/24854330)) — Brand Kit: medir B1 con un golden set de 30 cuentas antes de encenderlo

Tarea técnica · Testing · **P1 · M** · data-scientist-fde · depende de OL2-3

**Contexto**
El fundador pidió medir B1 con `qualify-measure` y que quepa en US$0,15 por Alta. Riesgo R7 de la
propuesta de UX: borradores que inventan. Cargar más trabajo en la misma llamada puede empeorar el
rubro y las etiquetas, así que también se vuelven a medir.

**Qué hay que hacer**
- Golden set de 30 cuentas públicas de CO, VE y UY: comida 10, heladería 5, inmobiliaria 5,
  agencia de viajes 5, otros 5. 20 con ≥ 3 textos, 5 con 1–2, 5 solo con bio. Desarrollo 10 /
  prueba 20. Lectura ≈ 30 créditos (US$0,06); respuestas guardadas fuera del repositorio y
  reproducidas sin conexión.
- Rúbrica por campo: fiel 0/1 · inventado 0/1 (grave) · español neutro sin anglicismos 0/1 ·
  usable tal cual 0/1/2 · se abstiene cuando no hay base 0/1. Tono correcto si queda a ±1 paso del
  deslizador.
- Verdad de referencia: dos personas (el fundador y una más), con κ sobre el conjunto de prueba. Un
  juez de IA de otro modelo solo para fidelidad, calibrado en desarrollo.
- Volver a medir el acierto del rubro y de las etiquetas con y sin B1.
- Costo p50 / p95 / máximo con y sin B1; peor caso calculado ≤ lo que OL2-0 asigna al paso de rubro.

**Cómo verificarlo**
`just eval-borradores` en `packages/api/evals/brand_drafts_ai/`, conjunto de datos en Langfuse;
resultado **PB6-002** en `docs/modelos-generativos/pruebas.md` y en la ficha de `claude-sonnet-5`.

**Criterios de aceptación**
- [ ] Umbrales para encender, en el conjunto de prueba: 0 inventados, fidelidad ≥ 95 %, abstención
  100 %, usable ≥ 70 % por campo, tono ≥ 80 %. Un campo bajo su umbral se apaga y se muestra vacío
  con el ejemplo del rubro.
- [ ] Rubro y etiquetas sin regresión con B1 frente a sin B1.
- [ ] κ entre las dos personas anotado.
- [ ] Costo p50 / p95 / máximo anotado; máximo observado ≤ US$0,15.
- [ ] Recomendación de encendido campo por campo entregada al fundador.

**Fuera de alcance**
- Encender B1 en producción (decisión del fundador).

### 7.10 Textos nuevos — aprobados por el fundador el 2026-10-25

**Aprobados los 26 (T1–T26) tal como están en la tabla** (Herwin, 2026-10-25). Se usan literales.

Se conservan literales (aprobados en PB-5): el aviso de Instagram, «Aprobar», «Cambiar», «Empezar
de cero», «Listo. Guardamos tu identidad de marca.» y los avisos de cuenta ilegible y privada. La
revisión técnica no agregó ni quitó textos.

| # | Historia | Dónde | Texto aprobado |
|---|---|---|---|
| T1 | OL2-5 | Título | Esto es lo que vimos en tu Instagram |
| T2 | OL2-5 | Cifras | {n} seguidores · {n} publicaciones |
| T3 | OL2-5 | Cuadrícula · fuente | Tus últimas publicaciones · De tu perfil, hoy. |
| T4 | OL2-5 | Marca en miniatura · fuente | La que más gustó · {n} me gusta. De tus últimas 12. |
| T5 | OL2-5 | Bio · enlaces | Así te presentas · Tus enlaces |
| T6 | OL2-5 | WhatsApp | Pedir por WhatsApp · {número enmascarado: código de país + dos últimas cifras} |
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
| T22 | OL2-6 | Ejemplo sin borrador (comida) | Por ejemplo: «Hacemos todo el mismo día, con receta de la casa.» · «Familias y oficinas de la zona que piden a domicilio.» · «Llegó el combo nuevo: pruébalo esta semana.» |
| T23 | OL2-6 | Ejemplo (heladería) | Por ejemplo: «Helados de yogur sin azúcar añadida.» · «Gente que cuida lo que come y quiere darse un gusto.» · «Llegó un sabor nuevo: ven a probarlo.» |
| T24 | OL2-6 | Ejemplo (inmobiliaria) | Por ejemplo: «Te acompañamos desde la visita hasta la firma.» · «Familias que buscan su primera casa.» · «Tenemos un apartamento nuevo en la zona que buscabas.» |
| T25 | OL2-6 | Ejemplo (agencia de viajes) | Por ejemplo: «Armamos el viaje completo, tú solo haces la maleta.» · «Parejas y familias que viajan en vacaciones.» · «Abrimos cupos para un destino nuevo.» |
| T26 | OL2-6 | Final | Tu marca está lista · Cada publicación que crees va a salir con tu logo, tus colores y tu forma de hablar. Nada se publica sin que lo apruebes. · Crear mi primera publicación · Ver mi identidad de marca |

**Agregados después de la revisión de UX de OL2-6 — aprobados por el fundador el 2026-10-25:**

| # | Historia | Dónde | Texto aprobado |
|---|---|---|---|
| T27 | OL2-6 | Bajo «Continuar» (o «Terminar mi marca») apagado, con la respuesta vacía | Para seguir, escribe tu respuesta. |
| T28 | OL2-6 | Aviso al tocar «Lo hago después» (lleva a la pantalla «Te faltan 3 cosas…») | Guardamos lo que llevas. Cuando vuelvas, sigues con lo que te falta. |

Descartado por la decisión 1: «Lo escribimos con lo que dice tu perfil.» (sin publicaciones no hay
borrador). Aplazados con TikTok (decisión 4): su aviso, «Tus últimos videos», «El más visto», «{n}
reproducciones. De todos tus videos.», «{n} me gusta recibidos» y «Subes unos {n} videos por
semana.».

### 7.11 Revisión técnica (2026-10-25) y lo que cambió

**principal-architect** (contra `main`, solo lectura) y **data-scientist-fde** (solo lectura).
Cambios frente al borrador v1:

- OL2-0 pasa de S a **M**: de un tope por paso a un **medidor en dólares por turno** (un turno lleno
  de `select_hashtags` ya supera el tope), con el presupuesto por paso de datos y la caída a las
  etiquetas de la llamada de rubro.
- OL2-1 se **divide**: 1a (backend, cliente compartido de ScrapeCreators) y 1b (creative,
  `proposal.observed`, que nunca se promueve porque `_decide` copia `profile` entero). «1 crédito»
  se mide, no se promete sin cambios.
- **Nueva OL2-7:** teléfonos enmascarados antes de cualquier proveedor o registro; cubrir solo el
  enlace de la bio no cumplía la decisión 7.
- OL2-2 pasa de S a **M**: raíz de borrado nueva (ADR 39) compartida con m-24852537, y borrado al
  aprobar, al empezar de cero y a los 30 días.
- OL2-3: herramienta nueva solo en el camino del Alta, con su versión de prompt; objeto
  `borradores` con `fuente` literal, validación campo por campo, reintento sin borradores, solo
  textos del dueño; `just eval-hashtag-ai` sin regresión.
- OL2-4 pasa de S a **M**: golden set de 30 cuentas, rúbrica, dos personas con κ, umbrales de
  encendido por campo, rubro y etiquetas medidos de nuevo; PB6-002.
- OL2-5: el número se enmascara en el modelo de vista, antes del estado de Reflex; «Corregir» acepta
  una lista fija de campos.
- OL2-6 ya no depende de OL2-5: va en paralelo.

**Filas de ADR propuestas** (las escribe principal-architect; este documento no las crea):

| Dónde | Fila | Estado |
|---|---|---|
| Apéndice de ADR 39 | Raíz de borrado para las imágenes de la precarga (foto de perfil y miniaturas), compartida con m-24852537; se borran al aprobar, al empezar de cero o a los 30 días sin ingreso | `[PROPUESTO]` |
| `arquitectura.md` §6 | Los teléfonos se enmascaran antes de cualquier proveedor o registro; el número completo vive solo en `connect.contact` del tenant | `[PROPUESTO]` |
| `arquitectura.md` §6 | El tope de costo del Alta es un medidor en dólares por turno, no un conteo de llamadas | `[PROPUESTO]` |

**Riesgos que quedan:** regresiones en el cliente compartido de ScrapeCreators (asistente web y
Referentes); el cambio de esquema vuelve a leer cada perfil en caché una vez (1 crédito por cuenta);
borradores inventados; objetos huérfanos en R2 si falla el borrado.

### 7.12 Preguntas abiertas para el fundador

1. «La que más gustó»: además de «publicó en los últimos 30 días», ¿exigimos al menos 3
   publicaciones (regla de la propuesta de UX)?
2. B1 con bio pero sin publicaciones (Bianki hoy): ¿confirmas que la bio sola no basta para un
   borrador? (Datos propone 5 cuentas «solo bio» en el golden set para medir la abstención.)
3. Ejemplos por rubro (T22–T25): ¿bastan estos cuatro rubros para empezar? ¿El resto usa el de
   comida o ninguno?
4. OL2-4: ¿quién es la segunda persona que etiqueta el golden set contigo? ¿Apruebas leer ≈ 30
   cuentas públicas que no son tuyas (≈ 30 créditos, US$0,06)?
5. ¿Apruebas los umbrales de encendido de B1 que propone datos (0 inventados, fidelidad ≥ 95 %,
   usable ≥ 70 %, tono ≥ 80 %)?

