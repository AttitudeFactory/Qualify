# Interacciones · Fase B — respuestas públicas a comentarios con intención comercial

`[IMPLEMENTADO 2026-10-23 · m-24789645 · PR 1–4 (#224, #230, #231 y el de esta documentación) · prueba real hecha en local contra Meta el 2026-10-23]`

Este documento explica qué hace la Fase B de Interacciones, de qué depende (modelo, datos comerciales, permisos de Meta) y cómo salió la prueba real. La Fase A (detectar la intención comercial) está en [intencion-comercial-medicion.md](intencion-comercial-medicion.md); la Fase C (seguir por mensaje privado), en [conversaciones-limitaciones-meta.md §7](conversaciones-limitaciones-meta.md#7-fase-c--continuar-en-privado-m-24789646-estado-por-origen).

El código está en `packages/api/src/qualify_api/replies/` (puerta, generador público, servicio, repositorio, cliente de Meta) y `packages/api/src/qualify_api/assisted/` (hechos validados y aprobación humana). La pantalla es la tarjeta de borrador de `/inbox` (`Qualify/inbox_page.py`, reglas en `Qualify/replies_vm.py`).

## 1. Qué hace, de punta a punta

Un comentario público de Instagram que pregunta algo comercial («¿cuánto cuesta?», «¿tienen en talla M?») recibe un **borrador de respuesta pública** basado solo en el catálogo del negocio. Una persona lo revisa y lo aprueba; nada se publica solo.

1. **Señal (Fase A).** «Analizar intención» guarda en `comment_intent_results` si el comentario tiene intención comercial y qué clases pregunta, con su versión de detector (`intent-claude-v2` / `intent-pipeline-v1`, `intent/composition.py`).
2. **Candidatos.** «Generar borradores» (`replies/composition.py:84`, siempre a mano, sin programador) lista los comentarios entrantes, no borrados, de la conexión elegida, que **no tienen ningún borrador** y tienen sentimiento `POS` o intención comercial en la versión actual (`replies/repository.py:462`).
3. **Puerta barata** (`replies/gate.py:82`). Determinista, sin red ni modelo: decide si el comentario merece borrador y por qué ruta (`commercial` o `sentiment`). Sección 3.
4. **Hechos validados** (`assisted/grounding.py:215`, `catalog_grounding_for`). Conexión → su marca (`social_connections.brand_id`) → nombre de la marca y productos activos de `brand_products`, ordenados por `position` y nombre, leídos con `tenant_session`. Cada producto lleva su id y su `updated_at` para quien revisa.
5. **Generación pública** (`replies/service.py:213`, `_compose`). El modelo recibe esos hechos **sin precios** (`Grounding.without_prices()`, `grounding.py:117`: también borra montos dentro de la descripción y la categoría), el comentario sin nombre ni usuario del autor (`public_drafts.py:186`) y un contexto con lo que la persona pregunta (`public_context`, `public_drafts.py:127`). Responde con la herramienta estricta `propose_reply`. Sección 5.
6. **Motivos de revisión** (`public_drafts.py:145`, `review_reasons`). El código, no el modelo, decide si el borrador «Requiere revisión». Sección 3.
7. **Borrador guardado** como `proposed` en `comment_reply_drafts`, con los hechos que vio el modelo, los motivos, el costo y la señal de intención que lo dejó pasar (migraciones 0080 y 0081). Nunca se envía al generarlo.
8. **Decisión humana** en la tarjeta: «Aceptar y enviar», «Editar» → «Guardar y enviar», «Regenerar» o «Descartar». Si hay un motivo bloqueante, el envío exige marcar «Ya revisé estos puntos» (`Qualify/replies_vm.py:345`, comprobado en el servidor dentro de `Qualify/replies_state.py`, no solo en el botón).
9. **Envío** (`replies/service.py:417`). Exige un `HumanApproval` (`assisted/approval.py`) que nombre **este** borrador (`require_approval`, `service.py:101`) y que el borrador esté `accepted` o `edited`. Marca `sending` **antes** de llamar a Meta y luego hace `POST /{ig-comment-id}/replies` (`replies/client.py:124`). Resultado: `sent` con el id de la respuesta, `send_failed` (Meta la rechazó) o `send_ambiguous` (falló el transporte: pudo haber salido; nadie reintenta, una persona lo comprueba en Instagram).

«Regenerar» (`service.py:328`) solo vale para un borrador `proposed`: vuelve a pasar la puerta con las señales actuales y, en una sola transacción, descarta el viejo y guarda el nuevo (`supersede_draft`). Un borrador aprobado o enviado nunca se regenera.

## 2. Decisiones del fundador (2026-10-23)

| | Decisión | Cómo la hace cumplir el código |
|---|---|---|
| **D1** | **En público nunca se da un precio.** Si preguntan el precio, se invita a seguir por mensaje privado. | Dos veces: el modelo no recibe precios (`without_prices()`), y cualquier cosa con forma de precio en su texto añade `price_token` (bloqueante). La tarjeta tampoco muestra el precio junto a los productos usados («En público no se dan precios: si preguntan, el borrador invita a escribir por mensaje privado.»). |
| **D2** | **En la v1 solo el catálogo es fuente validada.** Disponibilidad, local, ubicación y horario no están validados en ninguna tabla. | `UNVALIDATED_CLASSES` (`public_drafts.py:92`): si el comentario pregunta por `availability`, `store`, `location` o `hours`, el borrador lleva `unvalidated:<clase>` (bloqueante), y el prompt prohíbe afirmar existencias, direcciones, sucursales, horarios, envíos, plazos o promociones. |
| **Nota suave** | **Una clase «no fiable» es una nota, no un bloqueo.** | `unreliable:<clase>` es el único motivo suave (`SOFT_REASON_PREFIXES`, `public_drafts.py:100`): se guarda y se muestra en tono tranquilo, pero no pone «Requiere revisión». La puerta solo usa `commercial_intent`, que sí está medido como fiable (precisión 0,96, recall 0,98 en Fase A). |

## 3. La puerta y los motivos de revisión

### Reglas de la puerta (`replies/gate.py`)

Un comentario pasa solo si se cumplen **todas**:

1. El canal es `comment`. Un DM se rechaza nombrando el bloqueo real (Advanced Access y verificación del negocio, QUA-20/QUA-69).
2. El texto no está vacío.
3. No hay un borrador **vivo** para ese comentario (`proposed`, `accepted`, `edited`, `sending`, `send_ambiguous` o `sent`; índice parcial `uq_reply_draft_live_message`, migración 0080). «Regenerar» evalúa la puerta sin esta condición, porque reemplaza el borrador vivo.
4. Nadie aprobó ya un mensaje privado para ese comentario (seguimiento de Fase C en `approved`). Uno `open` o `discarded` no bloquea.
5. Tiene una señal que merece respuesta pública:
   - intención comercial **en la versión actual** del detector → ruta `commercial` (este documento);
   - si no, sentimiento `POS` → ruta `sentiment`, el agradecimiento de QUA-22, sin catálogo.

Si un comentario cumple las dos, gana `commercial`: «¡me encanta! ¿cuánto cuesta?» no debe ir al generador de agradecimientos, que no tiene hechos. Una señal comercial guardada con una versión anterior del detector no cuenta, y la razón del rechazo pide volver a analizar la intención.

### Motivos de revisión

Los calcula `review_reasons` (`public_drafts.py:145`) y se guardan en `grounding.review_reasons`. `needs_review` es verdadero si hay **al menos un motivo bloqueante**. Un código que esta versión no conozca cuenta como bloqueante (`is_blocking_reason`, `public_drafts.py:103`: falla cerrado). Los textos que lee el dueño están en `Qualify/replies_vm.py:61` y `:79`.

| Código | Cuándo | Qué lee el dueño | ¿Bloquea? |
|---|---|---|---|
| `model_unsupported` | El modelo dice que usó algo fuera de los hechos (`uses_only_given_facts = false`) o lista alguna afirmación que no pudo respaldar | «El borrador dice algo que no está en tu catálogo; revisa que sea cierto.» Debajo, «Lo que no encontramos en tu catálogo: …» con esas afirmaciones | Sí |
| `price_token` | El texto tiene algo con forma de precio (`has_price_token`, `grounding.py:51`) | «La respuesta menciona un precio y en público no damos precios: quítalo con «Editar» o toca «Regenerar».» | Sí |
| `unvalidated:<clase>` | El comentario pregunta por disponibilidad, local, ubicación u horario (D2) | «Preguntan si hay disponible» / «…en qué local comprar» / «…dónde queda tu negocio» / «…el horario», seguido de «Eso no se confirma en público: revisa que la respuesta no lo confirme e invite a la persona a escribirte por privado.» | Sí |
| `empty_catalog` | La marca no tiene ningún producto activo, o la conexión no tiene marca | «Tu catálogo está vacío, así que la respuesta no habla de ningún producto. Agrega tus productos en Catálogo para que las próximas respuestas sean más completas.» | Sí |
| `price_unknown` | Preguntan el precio y ningún producto del catálogo tiene precio: hasta «te escribimos por DM con el precio» promete una cifra que nadie validó | «Preguntan el precio y tu catálogo no lo tiene; revisa que el borrador no prometa uno.» | Sí |
| `unreliable:<clase>` | Una clase preguntada (distinta de `general`) no es fiable para el detector actual (`intent/reliability.py`). Con `intent-claude-v2` son fiables `general`, `price`, `availability` y `location`; las demás no | Nota: «No estamos seguros de que pregunten por «<clase>»: mira que la respuesta conteste lo que pidieron.» | No (nota suave) |

Un borrador guardado antes de la nota suave, con `needs_review = true` solo por `unreliable:*`, deja de bloquear: la pantalla decide con los motivos, no con la columna (`build_draft_vm` en `replies_vm.py`). Un borrador marcado sin ningún motivo guardado sigue bloqueando, con un texto genérico.

## 4. Lo que se guarda por borrador

Tabla `comment_reply_drafts` (migración 0014, ampliada por 0080 y 0081). Cada borrador de la ruta comercial guarda su procedencia completa:

| Columna | Qué es |
|---|---|
| `generator_version` | `m24789645.1:claude-haiku-5-5` (`PUBLIC_GENERATOR_VERSION`, `public_drafts.py:61`). Un borrador de agradecimiento lleva `qua22.2:claude-haiku-5-5` |
| `gate_reason` | Por qué lo dejó pasar la puerta, con la versión del detector |
| `intent_result_id` | La fila de Fase A que lo hizo candidato. Clave foránea compuesta con `tenant_id`: no puede apuntar a la señal de otro tenant |
| `sentiment_result_id`, `sentiment_label` | El sentimiento, si existe; desde 0081 pueden ser NULL (un borrador puede apoyarse solo en la intención). `ck_reply_draft_has_signal` exige al menos una señal |
| `grounding` (JSONB) | Los hechos que vio el modelo: nombre del negocio y productos con `product_id`, nombre, categoría y `updated_at`, **sin precio** (`prices_withheld: true`), más `review_reasons` |
| `needs_review`, `unsupported_claims` | El veredicto de revisión y lo que el modelo no pudo respaldar |
| `model_id`, `model_revision`, `input_tokens`, `output_tokens`, `cost_usd` | El modelo, la revisión que devolvió la API, los tokens y el costo en USD (`NUMERIC(10,6)`). NULL donde el generador no lo informó: «no medido» no se lee como «costo cero» |
| `decided_by_user_id`, `final_text`, `status`, `external_reply_id`, `send_error_code` | Quién decidió, el texto final (si se editó), el estado del envío y el id de la respuesta en Meta |

La aplicación no tiene permiso de `DELETE` sobre la tabla: un borrador descartado queda como registro de la decisión de la persona.

## 5. Dependencias de IA

### Modelo y llamada

| Campo | Valor |
|---|---|
| Modelo | `claude-haiku-5-5`, esfuerzo `low` (`conversations/suggest.py:78`, `DRAFT_MODEL`): el mismo modelo y la misma configuración que los borradores privados de Conversaciones |
| Versión del generador | `m24789645.1:claude-haiku-5-5`. El prefijo nombra **este** prompt (`PUBLIC_SYSTEM_PROMPT`, `public_drafts.py:67`); hay que subirlo cada vez que el prompt cambie |
| Cómo se llama | `ClaudeDraftGenerator` (`conversations/suggest.py:196`) con el prompt público (`replies/composition.py:55`). Una sola llamada a la Messages API por `claude_tools.create_turn`: prompt de sistema con `cache_control`, herramienta estricta `propose_reply` (`reply`, `uses_only_given_facts`, `unsupported_claims`), `tool_choice: auto` porque el modelo razona, `max_tokens` 2048 (`suggest.py:83`, deja espacio al razonamiento). Si no llama a la herramienta o el texto sale vacío, falla (`ClaudeToolError`) y no se guarda nada |
| Precio | US$0,10 / US$0,50 por millón de tokens de entrada / salida (`claude_tools.py:42`, `PRICES`, tomado de la skill `claude-api`). El costo del borrador se calcula con esa tabla a partir del uso que devuelve la respuesta (`CallStats.cost_usd`, `claude_tools.py:91`) |
| Llave | `QUALIFY_ANTHROPIC_API_KEY`. El cliente se crea en la primera propuesta, así que sin llave el servicio arranca y solo falla al generar |
| Datos que salen a Anthropic | El nombre de la marca, los productos (nombre, categoría, descripción de hasta 160 caracteres, sin precio) y el texto del comentario. Nunca el nombre ni el usuario del autor |

### Costo medido (2026-10-23, prueba local real)

Del log de la app (`conversations.draft model=… input_tokens=… output_tokens=… cost_usd=…`, `suggest.py:290`), borradores públicos de la ruta comercial:

- **Entrada:** 263–283 tokens. **Salida:** 128–181 tokens (incluye el razonamiento de esfuerzo `low`).
- **Costo:** **US$0,000090–0,000118 por borrador.**

**Estimación** (no medida en producción) para un cliente con **300 comentarios comerciales al mes**: 300 × US$0,000090–0,000118 ≈ **US$0,027–0,035 al mes**. Si cada borrador se regenerara una vez, el doble: ≈ US$0,07 al mes. A eso se suma la clasificación de Fase A, que se cobra por comentario analizado y no solo por los comerciales (≈ US$0,02 por cada 1.000 comentarios, [intencion-comercial-medicion.md](intencion-comercial-medicion.md)). El costo de IA de Fase B es despreciable frente a cualquier otro costo del cliente.

### QUA-144 (observabilidad del gasto): dónde queda el costo hoy

- **En la base de datos: sí.** Cada borrador comercial guarda `model_id`, `model_revision`, `input_tokens`, `output_tokens` y `cost_usd`. Se puede sumar por tenant y por mes con SQL.
- **En el log: sí**, una línea por llamada (`conversations.draft …`). Pero la línea es la misma para los borradores privados de Conversaciones y para los públicos de Fase B: el log no dice de qué superficie viene.
- **En Langfuse: solo donde hay llaves.** `claude_tools.messages_create` (`claude_tools.py:200`) registra cada llamada como una generación «claude» con entrada, salida, tokens y costo, y no hace nada sin `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`. Hoy Langfuse corre solo en local (etapa A de [plan-observabilidad-langfuse.md](plan-observabilidad-langfuse.md) §3); `deploy/` no configura esas llaves, así que **producción no envía trazas**. Además, la generación pública no está envuelta en `observability.traced` (el agradecimiento de QUA-22 sí: `replies/claude_drafts.py:67`), así que en Langfuse aparece como una generación suelta, sin traza propia ni etiqueta que la distinga.

Lo que falta para observar el gasto:

1. Un lugar donde mirarlo sin SQL: un panel o consulta de costo por tenant, superficie y mes (borradores públicos, privados, intención, generador).
2. Distinguir la superficie: `@observability.traced("respuesta comercial", tags=("inbox",))` alrededor de la generación pública, y un nombre de log propio.
3. Langfuse en producción (etapa B del plan), si se quiere ver ahí.
4. Ojo con el caché: `CallStats.cost_usd` suma solo `input_tokens` y `output_tokens`; Langfuse cuenta además los tokens leídos o escritos en caché, a precio completo. Con un prompt de unos 270 tokens no hay caché, pero si el prompt creciera lo bastante como para cachearse, `cost_usd` del borrador se quedaría corto.
5. `cost_usd` se redondea a 6 decimales (`cost_decimal`, `public_drafts.py:181`): con estos montos la diferencia es de menos de una millonésima de dólar por borrador.

## 6. Dependencias de datos comerciales

**La única fuente validada es el catálogo** (`brand_products` de la marca enlazada a la conexión), leído en cada generación con `catalog_grounding_for` (`assisted/grounding.py:215`):

- Solo productos con `is_active = true`, ordenados por `position` y luego por nombre.
- De cada uno: nombre, precio y moneda (que el modelo **no** recibe en público), categoría, descripción, id y `updated_at`.
- El nombre del negocio es el de la marca (`brands.name`).
- Dentro de una misma generación se lee una vez por conexión (`_BatchCache`, `service.py:146`).

### La marca de la conexión es obligatoria

Si `social_connections.brand_id` es NULL, `catalog_grounding_for` devuelve un `Grounding` vacío (`grounding.py:232`): **ni productos ni nombre del negocio**. Todos los borradores comerciales de esa conexión salen con `empty_catalog` («Tu catálogo está vacío…») aunque la marca tenga productos cargados, y el modelo ve «Nombre del negocio: (no indicado)».

Lo encontramos el 2026-10-23 en la prueba local: la conexión no tenía marca y los borradores decían «catálogo vacío». **Recomendación:** antes de encender Fase B para un cliente, comprobar que **todas las conexiones de producción tienen `brand_id`**, por ejemplo:

```sql
-- como qualify_admin; cuenta las conexiones sin marca por tenant
SELECT tenant_id, count(*) FROM social_connections WHERE brand_id IS NULL GROUP BY tenant_id;
```

Y enlazar las que falten antes de generar. El mensaje de la tarjeta («Agrega tus productos en Catálogo…») no ayuda en ese caso: el catálogo puede estar lleno y lo que falta es el enlace.

### Observación abierta: «Nuevo producto» en Catálogo

El 2026-10-23, en local, el formulario «Nuevo producto» del Catálogo **no creó el producto**: no mostró error ni dejó nada en el log. **No está confirmado como error**: queda para quien es dueño del Catálogo (`qualify_api.catalog`, `Qualify/` del catálogo) reproducirlo y decidir. Si se confirma, afecta a Fase B directamente: un dueño que no puede cargar productos solo recibe borradores con `empty_catalog`.

### Lo que no existe

No hay campos de **existencias, local, ubicación ni horario** en ninguna tabla que un tenant valide. Por eso D2 manda esas preguntas a revisión y a mensaje privado. Añadirlos (al catálogo, al Brand Kit o a una tabla de sedes) es una decisión aparte, con su propio ticket, y cambiaría `UNVALIDATED_CLASSES` y el prompt (nueva versión del generador).

## 7. Permisos de plataforma (Meta)

Detalle y evidencia en [conversaciones-limitaciones-meta.md](conversaciones-limitaciones-meta.md) (§2 y §7).

- **Permiso:** la respuesta pública usa `POST /{ig-comment-id}/replies` con `instagram_manage_comments` (el corpus lista además `instagram_basic` y `pages_show_list`/`pages_read_engagement`; `replies/client.py`). En la matriz de capacidades es `REPLY_COMMENTS`, que exige `MANAGE_COMMENTS` y está confirmada (QUA-95, `packages/models/src/qualify_models/permission_capability.py`). Ese permiso **ya está concedido**: lo lleva la conexión de prueba `@rauldevgames` (§6 de ese documento) y con él se hizo la prueba real de la sección 10.
- **El envío no consulta la matriz antes de llamar a Meta.** Con un token sin el permiso, Meta rechaza la llamada y el borrador queda `send_failed` con `platform:<código>`, o la conexión pasa a `degraded` si la respuesta es 401/190 (`service.py:451`).
- **Acceso Standard = solo personas con rol en la app.** Mientras no haya Advanced Access y App Review de esos permisos (QUA-140, QUA-142), solo se puede responder a comentarios de cuentas con rol (administrador, desarrollador o tester) en la app de Meta. Para clientes reales hace falta esa revisión.
- **Tiempo de espera de 60 s** (`REPLY_TIMEOUT`, `replies/client.py:82`, PR #215). Medido el 2026-10-22 en la R4 de Fase C: `POST /{comment-id}/replies` tardó más que los 5 s por defecto de httpx, el cliente cortó y la respuesta **sí** se había publicado. Con 60 s la segunda prueba quedó `posted` con su id. Fase B usa el mismo cliente, así que el arreglo le aplica.
- **Sin clave de idempotencia en Meta.** Por eso el borrador se marca `sending` antes de llamar y un fallo de transporte queda `send_ambiguous`, sin reintento automático.

## 8. Aislamiento entre tenants

- `comment_reply_drafts` (0014) y `comment_intent_results` (0069) tienen `tenant_id`, RLS `ENABLE` + `FORCE` y la política con `NULLIF(current_setting('app.tenant_id', true), '')::uuid`. 0080 y 0081 no cambian la RLS y las columnas nuevas (incluido `grounding`) quedan cubiertas.
- Las claves foráneas son compuestas con `tenant_id` (`fk_reply_draft_intent_tenant`): un borrador no puede apuntar a la señal ni al comentario de otro tenant.
- El catálogo se lee con `tenant_session(tenant_id)`: nunca se mezclan productos de otro tenant.

Tests que lo prueban (todos `-m db`, contra el Postgres de compose):

| Test | Qué prueba |
|---|---|
| `packages/api/tests/test_replies_public_drafts_db.py::test_a_tenants_draft_never_uses_another_tenants_catalog_or_intent_rows` | El tenant B no ve el comentario ni la intención de A aunque nombre sus ids; `catalog_grounding_for(B, conexión de A)` no devuelve productos; cada borrador lleva solo los productos de su tenant |
| `packages/api/tests/test_replies_repository_db.py::test_rls_hides_another_tenants_drafts_and_grounding` | B no lee el borrador ni su `grounding` de A (ni con SQL directo sobre el JSONB), y no puede escribir un borrador sobre un comentario de A |
| `packages/api/tests/test_replies_repository_db.py::test_intent_result_fk_is_tenant_consistent_and_not_swallowed` | La FK compuesta rechaza apuntar a la señal de intención de otro tenant, y el error no se confunde con «ya hay borrador» |
| `packages/api/tests/test_replies_repository_db.py::test_rls_isolates_another_tenants_draft` | La RLS básica de la tabla: B no ve un borrador de A |
| `packages/api/tests/test_replies_send_sanctity.py` | Prueba estática: `post_reply` solo se llama desde el envío aprobado y el aviso de Fase C, y todo llamador de `send`/`send_draft` pasa un `HumanApproval` |

## 9. Limitaciones conocidas

1. **«15 mil» no se detecta como precio.** `has_price_token` exige un símbolo o código de moneda junto a la cifra. Comprobado el 2026-10-23: «15 mil», «cuesta 15 mil pesos», «15k» y «quince mil» pasan sin `price_token`; «15.000 pesos», «$15.000», «15000 COP», «Bs 20» y «U$S 300» sí se detectan. La primera barrera de D1 sigue en pie (el modelo no recibe precios), así que una cifra así solo saldría si el modelo la inventa.
2. **El modelo a veces reporta su propia derivación a DM como afirmación no respaldada** («te escribimos por DM con el precio» en `unsupported_claims`). Eso añade `model_unsupported` y pide revisión a un borrador que estaba bien. Observado en la prueba local del 2026-10-23. Se podría filtrar en código o aclarar en el prompt (nueva versión del generador).
3. **Un doble clic en «Regenerar» puede pagar dos llamadas al modelo.** Solo una reemplaza el borrador (`supersede_draft`); la otra devuelve el borrador ganador. El comentario nunca queda con dos borradores vivos (`service.py:328`). Con estos precios el costo extra es de una diezmilésima de dólar.
4. **La identidad de quien aprueba no se guarda como aprobación.** El borrador guarda `decided_by_user_id` (quien tocó «Aceptar» o «Editar»), y en la pantalla esa misma pulsación envía, así que en la práctica es la misma persona. Pero el `HumanApproval` que exige el envío (usuario y hora) solo queda en el log (`replies.send draft_id=… approved_by=… approved_at=…`, `service.py:437`): no hay columna `approved_by`/`approved_at`, y `send` no comprueba que el aprobador sea quien decidió.
5. **Solo comentarios de Instagram en publicaciones propias** que Qualify sincroniza. Las historias no admiten comentarios (§6 de [conversaciones-limitaciones-meta.md](conversaciones-limitaciones-meta.md)).
6. **Nada se genera solo.** «Generar borradores» es manual; un comentario con un borrador descartado no vuelve a ser candidato (solo «Regenerar» lo reemplaza).

## 10. Prueba real (criterio 3) — 2026-10-23

`[HECHA 2026-10-23 · local contra la API real de Meta · visible en Instagram: por confirmar]`

| Campo | Valor |
|---|---|
| Entorno | Qualify en local contra la API real de Meta |
| Conexión | `@rauldevgames`, Facebook Login for Business, acceso Standard, app «QualifyMkt Connector» |
| Comentario | «Cuanto cuesta?», de `@raul._.rangel` (tester con rol en la app), en una publicación de `@rauldevgames` |
| Flujo | «Sincronizar comentarios» → «Analizar intención» (clase: precio) → «Generar borradores» |
| 1.er borrador, catálogo vacío | Motivos `empty_catalog` + `price_unknown`: «Requiere revisión» |
| Tras cargar un producto con precio y «Regenerar» | Sin motivos de revisión. Fuente: «Curso de Godot desde cero · actualizado el 23 oct 2026». El precio no se mostró ni se dijo (D1) |
| Texto del borrador | «¡Hola! Te escribimos por DM con el precio 😊» |
| Aprobación | «Aceptar y enviar» por el usuario con sesión iniciada. Log: `replies.send draft_id=0c222719-… approved_by=d2bcd063-…` |
| Resultado | Estado `sent`, `external_reply_id = 17931155721421749`, `send_error_code` vacío |
| Tiempo de Meta | ≈ 6 s (aprobado 15:30:49 UTC → `sent_at` 15:30:55 UTC): más que los 5 s por defecto de httpx, dentro de los 60 s de #215 |
| Visible bajo el comentario en Instagram | **Por confirmar** (lo confirma el fundador) |

Qué demuestra:

- El recorrido completo funciona contra Meta: puerta → catálogo → generación sin precios → aprobación humana → `POST /{comment-id}/replies` → `sent` con el id que devolvió Meta. La forma de respuesta `{"id": …}` que `_parse_reply_response` esperaba según el corpus quedó observada en vivo.
- Los motivos de revisión responden al catálogo: vacío, bloquean; con un producto con precio, desaparecen.
- La respuesta de Meta tardó más de 5 s también en Fase B: el tiempo de espera de 60 s era necesario.

### Cómo repetirla

1. Con una conexión de Instagram que tenga `instagram_manage_comments` y **marca enlazada** (`social_connections.brand_id`, sección 6), y al menos un producto activo con precio en el Catálogo de esa marca.
2. Desde una cuenta **con rol en la app de Meta** (tester, desarrollador o administrador: acceso Standard), comentar una pregunta de precio en una publicación de la cuenta conectada.
3. En `/inbox`: «Sincronizar comentarios» → «Analizar intención» → «Generar borradores».
4. En la tarjeta, comprobar las fuentes («Productos de tu catálogo que usamos»), que no aparezca ningún precio y los motivos de revisión. Si hay motivos bloqueantes, marcar «Ya revisé estos puntos».
5. «Aceptar y enviar».
6. Anotar: id del borrador, `status` (`sent`), `external_reply_id`, `send_error_code`, `approved_at` y `sent_at` (del log y de la fila), tokens y `cost_usd`.
7. Abrir la publicación en Instagram y comprobar que la respuesta está **bajo el comentario**, publicada por la cuenta del negocio.
