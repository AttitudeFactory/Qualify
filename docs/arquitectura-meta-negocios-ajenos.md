# Meta: cómo administra Qualify los activos de otros negocios (portafolios, permisos y catálogo de WhatsApp)

`[v2 2026-11-13 · m-25026262 → m-25026326 · épica m-24786384 · D1–D3 FIRMADAS por el fundador 2026-11-13 · plan del video: docs/plan-video-app-review-catalog-management.md]`
· Dónde vive hoy el WhatsApp (y el catálogo) de un cliente, por qué aparece «Qualify.co», y qué
permisos y trámites hacen falta para administrar negocios que no son nuestros.
· Fecha de acceso de las fuentes de Meta: **2026-11-13**.

**Convención de evidencia** (la de `docs/opciones-catalogo-whatsapp.md`): `[V]` página oficial de
Meta leída hoy, con número de fuente (§Fuentes) · `[S]` tercero o resumen de buscador · `[H]`
inferencia nuestra · `[F]` decisión del fundador · **`[NO VERIFICADO]`** no se pudo confirmar.
Nada de este documento sale de memoria: lo que no tiene fuente lleva `[H]` o `[NO VERIFICADO]`.

Este documento **no reabre ADR 29** (firmado 2026-10-23, `docs/backlog-roadmap.md` decisión 3:
«una sola app y tokens por empresa cliente; agregador descartado»). Lo extiende de Instagram y
Facebook a WhatsApp y a su catálogo, y dice dónde la documentación actual de Meta cambia cosas que
dábamos por hechas (§9.2).

---

## Decisión del fundador (2026-11-13)

**Esta sección manda sobre el resto.** El fundador respondió en la conversación del 2026-11-13
(ticket m-25026326) tres preguntas cerradas que le hicimos con las palabras de abajo, no el
texto de §9.4. §9.4 se conserva como el análisis previo a la decisión.

**Lo que dijo** (literal, `[F]`):

| | Pregunta, tal como se le hizo | Respuesta, literal |
|---|---|---|
| **D1** | «¿El modelo actual queda solo para los negocios que tú operas, y todo cliente ajeno entra con su propio portafolio?» | «sí.» |
| **D2** | «En el modelo actual, ¿Qualify le traslada al cliente lo que Meta cobra por sus mensajes?» | Repitió la línea que se le presentó: «Recomendación: sí, al costo, salvo Bianki y Polette mientras se mide.» |
| **D3** | «¿El permiso de catálogos se pide junto con los de WhatsApp para terceros o en un envío posterior?» | «si, junto con los de whatsapp para terceros» |

**Cómo lo leemos** (análisis nuestro, `[H]` salvo donde se cita otra cosa — no son palabras del
fundador):

| | Lectura nuestra de la decisión | Qué descarta | Qué cuesta o arriesga | Qué la reabriría |
|---|---|---|---|---|
| **D1** | El Modelo A (activos del cliente dentro de Qualify.co) queda para los negocios que opera el fundador (Bianki, Polette); todo cliente ajeno entra por el Modelo B. Que «pilotos propios» cuenten como negocios del fundador, y que el Modelo B solo exista tras el App Review, es deducción nuestra, no algo que él dijera | Usar el Modelo A por defecto para clientes pequeños sin portafolio | Mientras no pase el App Review de WhatsApp, ningún cliente ajeno puede tener WhatsApp en Qualify | Que P-2 (§9.3) muestre una salida limpia y documentada |
| **D2** | Acepta la recomendación tal como se le presentó en la conversación: traslado al costo, salvo Bianki y Polette mientras se mide | Absorber el costo dentro del plan | Con D1 vigente no hay terceros en A: el traslado solo aplica a excepciones. **La acción viva es medir Bianki y Polette con el libro de consumo** (m-24955649) | Un mes de datos reales en el libro |
| **D3** | `catalog_management` va en el mismo envío de App Review que los permisos de WhatsApp para terceros, y se construye lo necesario para grabar su video (lo pidió después: «desarrollemos lo necesario para poder grabar ese video»). No dio motivo; el nuestro sería que el cliente del Modelo B sincronice su catálogo desde el día uno | El envío posterior que recomendaba §9.4 | Ver abajo | Un rechazo de `catalog_management` en ese envío; qué hacer entonces lo decide el fundador |

**D3 va contra la recomendación de §9.4**, y su riesgo se lleva adelante tal cual:

1. **El video pide funciones que no existen.** Meta exige demostrar «el proceso completo de inicio
   de sesión de Facebook» y «cómo el usuario de tu app crea, actualiza y elimina un catálogo de
   productos» `[V N-15]`. Qualify hoy ni crea ni elimina catálogos (ADR 48 §1). Construirlo pasa a
   ser **condición previa del envío de WhatsApp para terceros**: el envío espera a esa
   construcción (consecuencia de D3 que deducimos nosotros `[H]`; él no lo dijo así). Plan: `docs/plan-video-app-review-catalog-management.md`.
2. **¿Un permiso rechazado frena a los demás?** Lo que dice Meta hoy: cada permiso se evalúa con
   su propia evidencia — «no se aprobará para dicho permiso» si no se puede verificar, y ningún
   permiso que no aparezca en la grabación se aprueba `[V N-21]`, `[V N-22]`. Eso es aprobación
   **por permiso**. Pero hay un fallo que tumba **todo el envío**: «si no podemos acceder a tu app
   para evaluarla, se rechazará la solicitud completa» `[V N-21]`. Que Meta apruebe unos permisos y
   rechace otros del mismo envío solo consta en terceros (un caso de 12 de 15) `[S]`; cómo se
   reenvía solo lo rechazado: **`[NO VERIFICADO]`**. Lectura: un mal video de catálogo no debería
   arrastrar los permisos de WhatsApp `[H]`; un revisor que no pueda entrar a Qualify sí arrastra
   todo.
3. **`business_management` es dependencia de `catalog_management`** `[V N-15]`, y su propia
   página de revisión pide demostrar datos de **rendimiento de anuncios** `[V N-15]`, que Qualify no
   muestra. Si Meta exige pedirlo como permiso aparte en el mismo envío, ese punto puede salir
   rechazado `[NO VERIFICADO]`; el plan lo trata como riesgo R2.

---

## 0. La respuesta corta

- **¿Dónde vive hoy el catálogo de un cliente?** Donde vive su WhatsApp. La cuenta de WhatsApp de
  Bianki se creó dentro del **portafolio comercial «Qualify.co»** (nuestra cuenta de empresa en
  Meta, verificada el 2026-10-05), así que su catálogo se crea allí también y Qualify lo maneja con
  el token de **nuestro usuario del sistema** (un acceso automático que no depende de ninguna
  persona). Es el **Modelo A**: rápido, sin App Review (la aprobación que Meta exige para trabajar
  con datos de negocios ajenos), pero **los activos son de
  Qualify, no del cliente**, y Qualify paga a Meta sus mensajes.
- **¿Por qué «Qualify.co»?** Porque Meta solo deja trabajar sin App Review con los datos de **tu
  propio negocio** `[V N-1]`. Poner los activos del cliente dentro de nuestro portafolio es la forma
  de que cuenten como «nuestros». Sirve para los negocios que el fundador opera (Bianki, Polette).
- **¿Qué falta para un cliente con su propio portafolio?** El **Modelo B** de ADR 29: el cliente
  conserva sus activos y **le da permiso a la app de Qualify** con el registro integrado de Meta
  (Embedded Signup). Qualify recibe un token **por cliente**, el cliente paga sus mensajes a Meta
  con su tarjeta `[V N-10]`, y puede quitarnos el acceso cuando quiera. A cambio exige **App Review
  con acceso avanzado** de `whatsapp_business_messaging` y `whatsapp_business_management` `[V N-1]`
  (ticket **m-24789620**) y, para tocar su catálogo por API, de `catalog_management` (ticket
  **m-25026261**).
- **¿Y si el cliente comparte sus activos con nuestro portafolio como socio?** Meta lo permite, pero
  **para WhatsApp no ahorra el App Review**: la app del socio necesita acceso avanzado para cada
  permiso que use sobre cuentas compartidas, o la API responde error 200 `[V N-3]`. Para el catálogo
  la página no lo dice (§4).
- **Dos noticias de Meta que cambian docs nuestros (§9.2):** la «verificación de acceso» de Tech
  Provider **ya no se exige** `[V N-12]`, y Meta partió la vieja WABA en **cuenta de WhatsApp**
  (número, perfil, **catálogos**) y **cuenta de mensajería** (plantillas, **facturación**, webhooks)
  `[V N-4]`.

---

## 1. Los objetos de Meta que se confunden

Para el dueño del negocio: hay una «empresa» en Meta (el portafolio), cosas que esa empresa posee
(número, catálogo, página, Instagram), y programas (apps) a los que la empresa les presta esas cosas.
Para Qualify: **quién posee** decide quién paga, quién puede quitar el acceso y qué trámite exige
Meta.

| Objeto | Qué es | De quién es | Para qué sirve | El nuestro |
|---|---|---|---|---|
| **Portafolio comercial** (Business portfolio, antes Business Manager) | La empresa dentro de Meta; posee activos y personas | De una empresa | Dueño de activos; se verifica (documentos legales) | «Qualify.co», verificado 2026-10-05 a nombre de Attitude Factory |
| **App** | El programa de Qualify ante Meta; tiene permisos y niveles de acceso | De un portafolio; **debe ser distinto del portafolio del cliente** `[V N-14]` | Pedir permisos, recibir webhooks | `QualifyMkt Connector` (una sola, ADR 29) |
| **Usuario del sistema** (system user) | Una «persona robot» dentro de un portafolio; su token no depende de nadie | Del portafolio que lo crea | Token largo para servidores; ve lo que su portafolio **posee o tiene compartido** `[V N-2]` | El de Qualify.co; su token es `QUALIFY_WA_SYSTEM_USER_TOKEN` |
| **Usuario del sistema de integración** (BISU) | Un usuario del sistema que Meta crea **en el portafolio del cliente** cuando el cliente le da acceso a una app | Del portafolio del cliente | El token «por cliente» de un Tech Provider `[V N-2][V N-8]` | Ninguno aún |
| **Cuenta de WhatsApp** (WAAC, parte de la antigua WABA) | Identidad: número, perfil, **catálogos** | «Siempre del cliente o del desarrollador directo» `[V N-4]` | Lo que el cliente ve como «su WhatsApp» | La de Bianki está en Qualify.co |
| **Cuenta de mensajería** (Messaging account, la otra mitad; conserva el `waba_id`) | Plantillas, **facturación y método de pago**, suscripción a webhooks | Una **por socio** que atiende al cliente `[V N-4]` | Separa plantillas y cobros entre socios | La de Bianki, en Qualify.co |
| **Número** | El teléfono registrado en la Cloud API | Dentro de una cuenta de WhatsApp | Enviar y recibir; guarda historial y calidad `[V N-4]` | El de Bianki |
| **Catálogo** | Productos en Commerce Manager; **uno por jerarquía de cuentas de WhatsApp** («one catalog per WhatsApp account hierarchy») `[V N-16]` | De un portafolio; se comparte con socios | Mensajes de producto y carrito | Aún no creado (ADR 48 §10) |
| **Página de Facebook, cuenta de Instagram, cuenta publicitaria** | Activos de redes y anuncios | De un portafolio (o de una persona) | Publicar, Directos, anuncios | Las de Bianki/Polette, reclamadas en Qualify.co (2026-10-14) |

**La vieja WABA ya no es una sola cosa** `[V N-4]`: desde el 2026-09-23 Meta la separa en cuenta
de WhatsApp + cuenta de mensajería; el `waba_id` que guardamos **sigue funcionando** y hoy nombra la
cuenta de mensajería; los ids de cuenta de WhatsApp llegan con una versión nueva de la Graph API en
el primer semestre de 2027, y en 2028 serán obligatorios en las rutas que hoy usan
`phone_number_id`. Para este documento «WABA» = la pareja, salvo cuando la distinción importa.

---

## 2. Modelo A — los activos viven en el portafolio de Qualify

**Para el cliente:** no hace ningún trámite en Meta; el fundador le da de alta. **Pero su número y
su catálogo quedan a nombre de Qualify**, y si un día se va, llevárselos no es un botón (§2.4).
**Para Qualify:** se opera hoy, sin App Review y sin pantalla de permisos; a cambio, Qualify paga
los mensajes y responde ante Meta por todo lo que pase en esos activos.

### 2.1 Cómo se dio de alta Bianki (lo que hay)

1. La WABA de Bianki se creó **dentro de Qualify.co** (`docs/plan-modulo-whatsapp-cloud-api.md`
   §3.2: hereda la verificación —2.000 de límite, 20 números, 6.000 plantillas— y el método de pago
   «se configura una sola vez»).
2. En Business Settings de Qualify.co se generó un **token de usuario del sistema** con
   `whatsapp_business_messaging` + `whatsapp_business_management`.
3. `just whatsapp-connect` (`packages/api/src/qualify_api/whatsapp/connect.py`) lee el token del
   entorno una vez, comprueba con `GET /debug_token` que trae `REQUIRED_SCOPES`, y lo guarda cifrado
   en `oauth_credentials` con `token_type='system_user'` para la conexión del tenant.
4. Para el catálogo (ADR 48 §9, `whatsapp/catalog_sync/connect.py`): el fundador crea el catálogo
   en Commerce Manager **dentro de Qualify.co**, lo conecta a mano a la WABA, lo asigna al usuario
   del sistema, regenera el token con `catalog_management` + `business_management`
   (`CATALOG_REQUIRED_SCOPES`) y lo registra con `just whatsapp-catalog-connect`.

### 2.2 Por qué no hace falta App Review

Meta: si eres desarrollador directo y solo accedes a datos de tu propio negocio, no hay App Review
ni acceso avanzado `[V N-1]`; el token de usuario del sistema es el indicado para ese caso `[V N-2]`.
El acceso estándar es el que se pide a usuarios **con rol en la app** `[V N-13]`, y nuestro usuario
del sistema lo tiene. Para **`catalog_management` en acceso estándar sobre un catálogo propio**, la
página del permiso no lo dice `[V N-15]`: sigue **`[NO VERIFICADO]`** hasta la prueba P1 de ADR 48
§10 (subir un producto de Bianki y leer `finished`).

### 2.3 Quién paga a Meta

**Qualify.** La facturación vive en la cuenta de mensajería `[V N-4]`, y la de Bianki es de
Qualify.co. Desde el 2026-10-01 Meta cobra también los mensajes de servicio pasados los 1.000
gratis por número al mes, además de las plantillas (`docs/opciones-catalogo-whatsapp.md` §2.3,
`[V]` 2026-11-03). Que el método de pago de Qualify.co esté cargado y qué se ha facturado:
**`[NO VERIFICADO]`** (se mira en Business Settings → Facturación). El libro de consumo para
recuperar ese costo existe pero estaba vacío en producción (m-24955649).

### 2.4 Límites del Modelo A

- **De quién es el activo:** de Qualify.co. Meta: la cuenta de WhatsApp es siempre del cliente o
  del desarrollador directo `[V N-4]`; aquí el desarrollador directo somos nosotros.
- **Si el cliente se va:** Meta documenta cómo un cliente **deja a un socio** cuando la cuenta es
  suya (migración de la cuenta de mensajería, sin re-verificar el número) `[V N-20]`, y cómo
  compartir su cuenta con otro socio. **No documenta cómo sacar una cuenta de WhatsApp o un número
  de un portafolio que no es del cliente** `[NO VERIFICADO]`. Lo que sí dicen sus páginas: para
  cuentas del modelo nuevo «el número no se puede mover entre cuentas» por la vía de migración
  entre socios `[V N-18]`, y la página general habla de migrar «de una WABA a otra» sin mencionar
  portafolios `[V N-19]`. `plan-modulo-whatsapp-cloud-api.md` §3.2 **no cubre este caso**: allí
  «se migra el número (Meta lo permite entre WABAs del mismo portafolio)», que es mover a Bianki
  a otra cuenta **dentro de Qualify.co**, no sacarlo hacia el portafolio de un cliente. La salida
  entre portafolios es un hueco, no una contradicción. El catálogo tampoco tiene una transferencia
  documentada entre portafolios `[NO VERIFICADO]`; se puede recrear desde Qualify (Galería es la
  fuente, ADR 48).
- **Escala:** todos los números comparten el límite de mensajería y el método de pago del
  portafolio; 20 números por portafolio verificado (plan §2.4). Un incidente de calidad en un
  cliente afecta al portafolio de todos `[H]`.
- **Términos:** con activos de terceros dentro de nuestro portafolio, Meta nos ve como su único
  responsable. Para clientes que no opera el fundador esto es exactamente lo que ADR 29 descartó
  (variante B: «N clientes colgando de una identidad nuestra», sin cliente representado ante Meta).
  **El Modelo A es correcto para negocios que el fundador opera; no es un modelo de SaaS** `[H]`.

---

## 3. Modelo B — los activos viven en el portafolio del cliente y él delega

**Para el cliente:** entra a Qualify, toca «Conectar WhatsApp», inicia sesión en Meta, elige o crea
su portafolio y su número, y acepta. Su número, su catálogo y su facturación **siguen siendo suyos**;
paga sus mensajes directo a Meta; puede quitar a Qualify en cualquier momento. **Para Qualify:** un
token por cliente, sin pagar mensajes ajenos y sin custodiar activos ajenos; a cambio, App Review.

### 3.1 El flujo (Embedded Signup v4)

| Paso | Qué pasa | Evidencia |
|---|---|---|
| 1 | El cliente abre el registro integrado desde Qualify (v4; v2 y v3 se deprecaron el **2026-10-15**) | `[V N-6]` |
| 2 | Inicia sesión, elige o crea su portafolio y su cuenta de WhatsApp, verifica número y nombre visible, y **da acceso a la app** a esos activos | `[V N-6]` |
| 3 | La sesión devuelve `waba_id` (hoy = cuenta de mensajería), `phone_number_id`, **`business_id`** (su portafolio) y, si se pidió, **`catalog_ids`**, `page_ids`, `instagram_account_ids`, `ad_account_ids` | `[V N-7]` |
| 4 | El servidor cambia el código (vive **30 segundos**) por un **token de usuario del sistema de integración** (`GET /oauth/access_token`) | `[V N-7][V N-8]` |
| 5 | `POST /{waba_id}/subscribed_apps`: suscribe la app a los webhooks de la cuenta de mensajería del cliente | `[V N-8]` |
| 6 | `POST /{phone_number_id}/register` con un PIN de 6 dígitos (no en coexistencia) | `[V N-8][V N-6]` |
| 7 | El cliente carga su método de pago; queda «totalmente incorporado» | `[V N-8]` |

**Dueño después:** «los clientes incorporados por el registro integrado son dueños de todos sus
activos de WhatsApp» y tienen acceso total a WhatsApp Manager, que el socio no puede restringir
`[V N-6]`. El registro crea **una cuenta de mensajería por socio** `[V N-4][V N-5]`.

### 3.2 Quién paga

**El cliente, a Meta.** Un Tech Provider no tiene línea de crédito; sus clientes cargan su propio
método de pago; Meta les cobra el uso de la API y el Tech Provider cobra sus otros servicios
`[V N-10]`. Que Qualify pague y re-facture exige ser **Solution Partner** (línea de crédito, Meta
Business Partner), un trámite largo que Meta desaconseja si no hace falta facturar el uso
`[V N-10]`, `[S]` (blogs de proveedores). **Recomendación técnica: Tech Provider, el cliente paga.**

### 3.3 Permisos, nivel y trámites

- `whatsapp_business_messaging` y `whatsapp_business_management` con **acceso avanzado** tras App
  Review: «no podrás incorporar clientes hasta que tu app esté aprobada para acceso avanzado»
  `[V N-6]`; sin acceso avanzado, error 200 y el cliente no puede conceder el permiso en el registro
  `[V N-1]`. Videos: un mensaje enviado desde la app y recibido en WhatsApp, y una plantilla creada
  `[V N-9]`. Verificación del negocio **antes** del App Review `[V N-9]` (hecha).
- `catalog_management` (+ `business_management`, del que depende) con acceso avanzado para
  catálogos de negocios que **nos dan acceso**; el video debe mostrar al usuario **creando,
  actualizando y borrando un catálogo** en nuestra app `[V N-15]`. Hoy Qualify no crea ni borra
  catálogos; por D3 se construye: `docs/plan-video-app-review-catalog-management.md`.
- Límite: **10 clientes nuevos por 7 días**; sube a **200** tras verificación del negocio, App
  Review y verificación de acceso (la página aún la nombra) `[V N-6]`.
- **Verificación de acceso:** retirada — «Access Verification is no longer required» `[V N-12]`
  (anuncio fechado 2026-10-09 según la URL del blog y un tercero `[S]`). Ver §9.2.
- **Coexistencia** (el cliente sigue usando la app WhatsApp Business con el mismo número): sirve
  para chats 1:1 y contactos, 20 mps, historial de 180 días; **catálogos y pedidos NO funcionan
  por la Cloud API en coexistencia** `[V N-11]`. Lo que el cliente manda desde la app sigue gratis;
  lo de la API se cobra `[V N-11]`.

### 3.4 Por qué es el modelo de ADR 29

Es el mismo patrón que ADR 29 firmó para Instagram/Facebook con Facebook Login for Business: una
app, un token BISU por empresa cliente, `client_business_id` como discriminante en el plano de
Meta. El registro integrado de WhatsApp **es** la variante de Facebook Login for Business para
WhatsApp (se configura como una «login variation» `[V N-7]`), y el token es el mismo tipo
(«si eres Tech Provider, usa un token de usuario del sistema de integración» `[V N-2]`). **Sin
contradicción con ADR 29.**

---

## 4. ¿Y un portafolio que comparte activos con el portafolio de Qualify como socio?

**La idea:** Qualify.co como «portafolio que administra otros portafolios» — el cliente conserva
la propiedad y, en Business Settings, **asigna a Qualify.co como socio** sobre su número, su catálogo,
su página. Es lo que hacen las agencias. Para el cliente es parecido al Modelo B (sigue siendo
dueño); para Qualify parecería evitar el App Review porque seguiríamos usando nuestro usuario del
sistema. **No lo evita para WhatsApp.**

| Pregunta | Lo que dice Meta | Nivel |
|---|---|---|
| ¿Se puede compartir con un portafolio socio? | Sí. Cuenta de WhatsApp con hasta 5 socios, cuenta de mensajería con hasta 2; «Assign partner» con el id del portafolio del socio; hacen falta **las dos** para mensajear | `[V N-3]` |
| ¿Página, Instagram, cuenta publicitaria, catálogo? | Sí, por Business Settings → Socios; catálogo con acceso parcial (ver, anunciar) o total (ajustes, borrar); el catálogo expone los bordes `agencies` y `assigned_users` (tareas `MANAGE`, `ADVERTISE`…) | `[S]` (Centro de ayuda vía buscador; agencias) · bordes `[V N-17]` |
| ¿Nuestro usuario del sistema llega a lo compartido? | Sí: los usuarios del sistema ven cuentas «owned by, or shared with, your business portfolio» | `[V N-2]` |
| ¿Basta acceso estándar sobre WABAs compartidas? | **No.** «The partner's app must have Advanced access for every permission it uses on your accounts»; sin él, error 200 | `[V N-3]` |
| ¿Basta acceso estándar sobre un catálogo compartido? | La página del permiso habla de «businesses that grant you access» y la regla general exige revisión para datos «que no posees o administras»; **no dice si compartido = administrado** | **`[NO VERIFICADO]`** |
| ¿Es la vía que usa un Tech Provider? | No. El Tech Provider usa el registro integrado y tokens BISU `[V N-2][V N-8]`. Meta describe para socios el catálogo del cliente compartido con el socio, o creado bajo el id del socio `[V N-16]`; que la asignación de socio sea «la vía de agencias y de Solution Partners» es lectura nuestra `[H]` | `[V]` / `[H]` |

**Por qué ADR 29 eligió delegar a la app y no compartir con el portafolio**, ahora con WhatsApp:
(1) para WhatsApp **ambos caminos piden el mismo App Review** `[V N-3]`, así que compartir no compra
nada; (2) con socio, **un solo token nuestro** ve a todos los clientes: un error o una revocación
afecta a todos, que es justo lo que los tokens por cliente evitan (ADR 29 razón 5); (3) el
`client_business_id` llega en el token BISU y no en una asignación de socio `[H]`; (4) la
asignación es manual en Business Settings (2FA, admin con control total `[S]`), incompatible con
el autoservicio de m-24789620. **Uso legítimo que queda:** el fundador como agencia de un negocio
que ya tiene portafolio, mientras no hay App Review — solo para catálogo o páginas, **si** la prueba
P-4 (§9.3) muestra que el acceso estándar alcanza. Para WhatsApp no sirve.

---

## 5. Matriz de permisos

Token A = usuario del sistema de Qualify.co (env → `oauth_credentials`, `token_type='system_user'`).
Token B = usuario del sistema de integración del cliente (`token_type` nuevo, §7). «Est.» =
estándar; «Avz.» = avanzado tras App Review.

| Capacidad | Permiso | Modelo A | Modelo B | Evidencia |
|---|---|---|---|---|
| Enviar y recibir mensajes (webhook `messages`) | `whatsapp_business_messaging` | Est., token A | **Avz.**, token B | `[V N-1][V N-9]` |
| Plantillas, perfil del negocio, estado del número | `whatsapp_business_management` (+ messaging para perfil) | Est., token A | **Avz.**, token B | `[V N-1][V N-6]`; reparto por permiso: plan §2.1 |
| Registrar el número (`/register`) | `whatsapp_business_messaging` | Est., token A (hecho a mano) | **Avz.**, token B, paso 6 de §3.1 | `[V N-8]`; permiso: plan §2.1 |
| Suscribir webhooks (`/subscribed_apps`) | `whatsapp_business_management` | Est., token A | **Avz.**, token B, por cliente | `[V N-8]`; plan §2.1 |
| Leer y escribir el catálogo (`items_batch`, estado del lote) | `catalog_management` (+ `business_management`) | Est. **probable**, token A | **Avz.**, token B | `[V N-15]`; nivel en A `[NO VERIFICADO]` (P1) |
| Ver qué catálogo tiene la cuenta (`GET /{waba_id}/product_catalogs`) | los dos de WhatsApp + `catalog_management` | Est. probable, token A | **Avz.**, token B; o `catalog_ids` de la sesión del registro | ADR 48 §2 `[V]`; `[V N-7]` |
| Conectar catálogo a la cuenta (`POST /{waba_id}/product_catalogs`) | la página no lista permisos | A mano en WhatsApp Manager (ADR 48) | El cliente lo hace en el registro o en su WhatsApp Manager | ADR 48 §2; `[NO VERIFICADO]` por API |
| Crear y borrar catálogos | `catalog_management` | No se hace (ADR 48) | Exigido **para el video** del App Review | `[V N-15]` |
| Mandar producto / multiproducto | `whatsapp_business_messaging` | Est., token A | Avz., token B | `opciones-catalogo-whatsapp.md` §2.1 `[V]` |
| Recibir el carrito como pedido (webhook `order`) | `whatsapp_business_messaging` | Est. (en prod: #623) | Avz.; **no en coexistencia** | `[V N-11]`; opciones §2.3 |
| Página, Instagram, publicar, Directos | los de ADR 25 | Est. (activos del fundador) | Avz. (envíos 1 y 2) | ADR 29; épica m-24786384 |

---

## 6. Dónde vive cada cosa y de quién es

| Activo | Dueño en A | Dueño en B | Quién paga a Meta | Quién puede quitar el acceso | Si el cliente se va |
|---|---|---|---|---|---|
| Portafolio | Qualify.co (el cliente no tiene uno en este flujo) | El cliente | — | — | En A no hay nada que llevarse; en B sigue con lo suyo |
| Cuenta de WhatsApp (número, perfil) | Qualify.co | El cliente `[V N-4][V N-6]` | — | A: solo Qualify; B: el cliente, desde su Business Settings | A: salida **no documentada** `[NO VERIFICADO]`; B: deja de compartir y listo |
| Cuenta de mensajería (plantillas, webhooks) | Qualify.co | El cliente, una por socio `[V N-4]` | A: **Qualify**; B: **el cliente** `[V N-10]` | ídem | A: plantillas se pierden `[H]`; B: Meta documenta migrar la cuenta de mensajería sin re-verificar `[V N-20]` |
| Número (historial, calidad) | En la cuenta de Qualify.co | En la del cliente | (por mensaje, en la cuenta de mensajería) | ídem | A: «el número no se puede mover entre cuentas» en el modelo nuevo `[V N-18]` → **riesgo**; B: no se mueve, ya es suyo |
| Catálogo | Qualify.co (ADR 48 §10) | El cliente (vive en su cuenta de WhatsApp `[V N-4]`) | gratis `[H]` | A: Qualify; B: el cliente | A: recrearlo desde Galería en el portafolio nuevo; B: se queda con él |
| Token | Usuario del sistema de Qualify.co | BISU en el portafolio del cliente | — | A: Qualify; B: cliente o Qualify | B: revocado en Business Settings → apps conectadas (ADR 29) |
| Datos en Qualify (chats, pedidos, productos) | Tenant del cliente (RLS) | igual | — | — | Igual en A y B: export y borrado por nuestra política (m-24789547) |

---

## 7. Qué cambia en Qualify para el Modelo B

**Para el cliente:** un botón «Conectar WhatsApp» y, si tiene catálogo, que Qualify lo vea solo.
**Para Qualify:** lo que hoy hace un CLI del fundador pasa a un flujo con token por tenant. Nada de
esto es un servicio nuevo, una base nueva ni una cola nueva (ADR 31).

1. **Credenciales por negocio y tipo de token.** `oauth_credentials` ya admite el caso (ADR 29 g):
   `token_type` es texto libre → `'business_integration_system_user'`; `expires_at` nulo si Meta
   no fija vencimiento (`[NO VERIFICADO]` para WhatsApp: la página no da plazo `[V N-2]`). El
   `token_type='system_user'` de hoy se conserva para el Modelo A; **nunca** se mezclan en un tenant.
2. **Alta por autoservicio (m-24789620).** Nuevo callback en `connections` que recibe `code` +
   datos de sesión, cambia el código en < 30 s **en el servidor** (en la petición: es una llamada
   de red única y gratuita, no un trabajo caro), y encola en el worker los pasos 5–6 (suscribir,
   registrar) con clave idempotente por `waba_id` (un reintento no registra dos veces). El
   `persist_grant` de `whatsapp/connect.py` es el mismo repositorio: el CLI queda para el Modelo A.
3. **`client_business_id` (m-24849197).** Se guarda el `business_id` de la sesión del registro
   `[V N-7]` y se contrasta con el del token (`GET /me?fields=client_business_id`, ADR 29). Es lo
   que permite verificar contra Meta de quién es una conexión.
4. **El catálogo (ADR 48) — supuestos que cambian:**
   - **Quién lo crea:** vive en el portafolio del cliente. Lo crea el cliente en Commerce Manager
     o, tras el plan del video (D3), **Qualify desde Galería con el permiso del cliente**
     (`docs/plan-video-app-review-catalog-management.md`). Meta también ofrece crearlo **bajo el
     id del socio** `[V N-16]` — eso es volver al Modelo A para el catálogo; **no recomendado** `[H]`.
   - **Cómo se registra:** de la sesión del registro (`catalog_ids` `[V N-7]`, pidiendo el activo
     catálogo solo si hace falta porque Meta advierte que ahí se abandona el flujo) en lugar del CLI
     `whatsapp-catalog-connect`; la verificación `CATALOG_REQUIRED_SCOPES` se hace sobre **el token
     guardado del tenant**, no sobre la variable de entorno.
   - **`link` del artículo** «en el dominio del sitio del negocio» (ADR 48 R1): sigue igual, ahora
     con el dominio del cliente.
   - **Coexistencia:** sin catálogo ni pedidos por la API `[V N-11]` → la pantalla debe decirlo
     antes de que el cliente elija coexistencia.
   - **Crear, renombrar y eliminar desde Qualify:** ADR 48 decía que Qualify no crea catálogos;
     por D3 eso cambia — el plan `docs/plan-video-app-review-catalog-management.md` lo construye y
     enmienda ADR 48.
   - **No cambia:** Galería como fuente, `retailer_id = brand_products.id`, ruta pública firmada
     de la foto, las tres acciones disparadas por una persona, el worker existente.
5. **Webhooks por cuenta.** Una sola URL de la app; cada cliente se suscribe con
   `/subscribed_apps`. El intake ciego al tenant (`webhook_session`) ya enruta por
   `phone_number_id` → `whatsapp_phone_numbers`; añadir el evento `account_update`, que Meta pide
   para cerrar el registro `[V N-7]`. Revocación del cliente → FSM C-03 `REVOKED`.
6. **Lo que NO cambia:** asistido, nunca autónomo (todo envío pasa por aprobación humana o por el
   menú que el dueño configuró); RLS en cada tabla nueva; procedencia en el catálogo
   (`pipeline_version`); una sola app (ADR 29 R1).

---

## 8. Los dos tickets y su orden

Ambos en la épica **m-24786384** «Meta App Review (permisos, videos y Tech Provider)».

| | m-24789620 · «Conectar WhatsApp» por autoservicio | m-25026261 · `catalog_management` para catálogos de otros negocios |
|---|---|---|
| Entrega | Registro integrado v4, token BISU por cliente, registrar número, suscribir webhooks, coexistencia, límites de alta | Crear, renombrar y eliminar el catálogo de WhatsApp desde Galería (plan del video, m-25026326); lectura y escritura del catálogo del cliente con su token |
| Envío de App Review | **Uno solo (D3):** `whatsapp_business_messaging` + `whatsapp_business_management` + `catalog_management` (y `business_management` si Meta lo exige aparte, R2 del plan) | ídem |
| Gates | Verificación del negocio (hecha); 2 videos de WhatsApp `[V N-9]`; `client_business_id` (m-24849197); **ya no** verificación de acceso (m-24789561, ver §9.2) | Video que muestra inicio de sesión + crear, actualizar y eliminar `[V N-15]`; las funciones deben existir en producción antes del envío |
| Depende de | Envíos 1 y 2 no lo bloquean (la revisión es por permiso, ADR 29). **Por D3 su envío espera a que la construcción del video de catálogo esté en producción** | La construcción del plan; su ruta de inicio de sesión se elige en el paso 1 del plan (§3.1: la evidencia apunta a una configuración propia de Facebook Login for Business, porque con la app en Live el registro integrado de m-24789620 solo mostraría permisos ya aprobados `[S]`) |
| Video para Meta | (1) mensaje enviado desde Qualify y recibido en un teléfono; (2) plantilla creada desde Qualify; y el registro integrado completo | Inicio de sesión + crear catálogo, renombrarlo, subir un producto, eliminarlo **desde Qualify** (guion: plan §6) |

**Orden decidido (D3, 2026-11-13):** (1) se construye lo del video de catálogo
(`docs/plan-video-app-review-catalog-management.md`) en paralelo con m-24789620; (2) se graban los
tres videos; (3) **un solo envío** con los permisos de WhatsApp para terceros y
`catalog_management`. El envío espera a que ambas construcciones estén en producción. El orden
que recomendaba esta sección antes de la decisión (m-24789620 primero, catálogo en un envío
posterior) queda como registro en §9.4.

---

## 9. Riesgos, lo no verificado y lo que debe decidir el fundador

### 9.1 Riesgos

1. **Activos de terceros dentro de Qualify.co (Modelo A).** Si un cliente ajeno entra por A, su
   número queda a nuestro nombre y la salida no está documentada `[V N-18]`/`[NO VERIFICADO]`.
   Señal: un cliente pide «llevarme mi número». Mitigación: A solo para negocios que opera el
   fundador (D1).
2. **Qualify paga mensajes ajenos (Modelo A)** sin libro de consumo poblado (m-24955649). Señal: la
   factura de Meta de Qualify.co crece sin línea de cobro. Mitigación: D2.
3. **El video de `catalog_management` pide funciones que no construimos** (§8). Si se pide en el
   mismo envío que WhatsApp, puede rechazarse y retrasar el envío entero `[H]`. Mitigación
   propuesta: D3 en envío posterior. **Decidido 2026-11-13: mismo envío** — el riesgo pasa a ser de
   calendario (el envío espera la construcción) y se sigue en la sección «Decisión del fundador» y
   en el plan del video.
4. **Un portafolio compartido de 20 números** y un límite de mensajería común: un cliente con mala
   calidad castiga a los demás en A `[H]`.
5. **Modelo nuevo de cuentas** en despliegue (fase 1 hasta mediados de octubre; ids nuevos en 2027;
   obligatorio en 2028) `[V N-4]`: el código usa `waba_id` y `phone_number_id`, que siguen válidos
   hasta la fase 3. Deuda fechada, no urgente.

### 9.2 Lo que contradice o deja sin cubrir docs anteriores (sin elegir en silencio)

| Afirmación anterior | Dónde | Lo que dice Meta hoy | Qué lo zanja |
|---|---|---|---|
| Tech Provider exige **Access Verification** | `plan-modulo-whatsapp-cloud-api.md` §2.2; m-24789561 «In Progress» | «Access Verification is no longer required» `[V N-12]`; pero el registro integrado aún la nombra para subir el límite a 200 `[V N-6]` | Leer el anuncio del blog (2026-10-09 `[S]`) y mirar el estado en el panel de la app; si se confirma, **cerrar o re-alcanzar m-24789561** (lo hace el hilo principal) |
| «Se migra el número (Meta lo permite entre WABAs del mismo portafolio)» | plan §3.2 | No lo contradice: es **otro caso**. Meta no documenta sacar un número hacia **otro portafolio**; en el modelo nuevo «el número no se puede mover entre cuentas» por migración entre socios `[V N-18]`, y la página general solo habla de «una WABA a otra» `[V N-19]` | Preguntar a soporte de Meta, o probar con un número de prueba (P-2) |
| Mensajes de servicio gratis en ventana | plan §2.5 | Cobrados desde 2026-10-01 pasados 1.000/número/mes (`opciones-catalogo-whatsapp.md` §2.3, `[V]` 2026-11-03) | Ya zanjado; plan §2.5 está desactualizado |
| La WABA como un solo objeto | todos los docs de WhatsApp | Cuenta de WhatsApp + cuenta de mensajería; el `waba_id` nombra la segunda `[V N-4]` | Nada que probar; actualizar vocabulario al tocar esos docs |
| Etapa 0-bis de ADR 29 (probar BISU sin App Review con un negocio que el fundador controla) | ADR 29 §10.3, V-TP-7 | Facebook Login for Business mantiene la regla de prueba («role on the app and full control of the client business») `[V N-14]`; pero para WhatsApp «no podrás incorporar clientes hasta tener acceso avanzado» `[V N-6]`, y las WABAs creadas desde la propia app no pasan por el registro integrado (plan §2.3) | Prueba P-3 abajo. **No cambia el ruling de ADR 29**, solo su calendario |

Nada de lo leído hoy **contradice el ruling de ADR 29** (una app, un token BISU por cliente, el
cliente posee sus activos): lo confirma para WhatsApp `[V N-2][V N-6][V N-8]`.

### 9.3 No verificado — y la prueba que lo cierra

- **P-1** `catalog_management` en acceso estándar sobre un catálogo de Qualify.co → prueba P1 de
  ADR 48 §10.
- **P-2** Salida de un cliente del Modelo A (número y cuenta de WhatsApp a otro portafolio) →
  consulta a soporte de Meta antes de dar de alta a un cliente ajeno en A.
- **P-3** Registro integrado sin acceso avanzado, con un portafolio de prueba que el fundador
  controla y una cuenta con rol en la app → intentarlo; si falla con error 200, la etapa 0-bis no
  existe para WhatsApp.
- **P-4** Catálogo compartido como socio con Qualify.co + `items_batch` con el token del usuario
  del sistema en acceso estándar → portafolio de prueba del fundador comparte un catálogo de prueba.
- **P-5** Vencimiento del token BISU de WhatsApp (la página no lo da `[V N-2]`) → leer
  `expires_at` en `/debug_token` del primer token real.
- **P-6** Si `POST /{waba_id}/product_catalogs` (conectar) exige `catalog_management` → la
  página no lista permisos (ADR 48 §2).

### 9.4 Lo que debe decidir el fundador

`[DECIDIDO 2026-11-13 en la conversación, con preguntas redactadas allí — D1 «sí.» (lectura: opción
A) · D2: repitió la recomendación tal como se le presentó · D3 «si, junto con los de whatsapp para
terceros» (lectura: opción B, contra la recomendación). Ver «Decisión del fundador» arriba;
opciones y recomendaciones quedan como registro.]`

**D1. ¿El Modelo A queda solo para los negocios que tú operas, y todo cliente ajeno entra por el
Modelo B cuando pase el App Review?**
A) Sí: A para Bianki, Polette y pilotos propios; B para todos los demás. · B) A como opción por
defecto para clientes pequeños sin portafolio, y B solo para los que ya tienen uno.
**Recomendación: A.** Con la opción B, un cliente ajeno deja su número a nombre de Qualify sin salida
documentada (§2.4), Qualify paga sus mensajes y responde ante Meta por él; el registro integrado ya
le crea el portafolio a quien no lo tiene `[V N-6]`, así que «no tiene portafolio» no es razón para
A. Se reabre si P-2 muestra una salida limpia y documentada.

**D2. En el Modelo A, ¿Qualify traslada al cliente el costo de los mensajes que Meta le cobra?**
A) Sí, al costo, medido por el libro de consumo (m-24955649) y visible en la factura. · B) Qualify
lo absorbe dentro del plan.
**Recomendación: A** para todo tenant en A que no sea del fundador; B solo para Bianki y Polette
mientras se mide. Se reabre cuando el libro tenga un mes de datos reales.

**D3. ¿`catalog_management` va en el mismo envío que los permisos de WhatsApp (envío 3) o en uno
posterior?**
A) Posterior (envío 4), después de m-24789620 y de construir crear/borrar catálogo para el video. ·
B) Mismo envío.
**Recomendación: A.** La revisión es por permiso (ADR 29); el envío 3 no debe arriesgarse por un
video que hoy no podemos grabar (§8). Se reabre si un cliente del Modelo B necesita sincronizar
cientos de productos antes de que exista el envío 4.

---

## Fuentes de Meta (acceso 2026-11-13)

- [N-1] WhatsApp permissions — https://developers.facebook.com/docs/whatsapp/permissions
- [N-2] Access Tokens Guide (WhatsApp) — https://developers.facebook.com/documentation/business-messaging/whatsapp/access-tokens.md
- [N-3] WhatsApp accounts and Messaging accounts — https://developers.facebook.com/documentation/business-messaging/whatsapp/whatsapp-business-accounts.md
- [N-4] Account model evolution — https://developers.facebook.com/documentation/business-messaging/whatsapp/account-model-evolution.md
- [N-5] Account model: onboarding — https://developers.facebook.com/documentation/business-messaging/whatsapp/account-model-evolution/onboarding.md
- [N-6] Embedded Signup (overview) — https://developers.facebook.com/docs/whatsapp/embedded-signup/
- [N-7] Embedded Signup implementation — https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation.md
- [N-8] Onboarding customers as a Tech Provider — https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider.md
- [N-9] Get started for Tech Providers — https://developers.facebook.com/docs/whatsapp/solution-providers/get-started-for-tech-providers
- [N-10] Partners overview (tabla de tipos de socio y facturación) — https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/overview.md
- [N-11] Onboarding WhatsApp Business app users (coexistencia) — https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users.md
- [N-12] Access Verification — https://developers.facebook.com/docs/development/release/access-verification
- [N-13] Access levels — https://developers.facebook.com/docs/graph-api/overview/access-levels/
- [N-14] Facebook Login for Business — https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/
- [N-15] Permissions reference: `catalog_management` — https://developers.facebook.com/docs/permissions/reference/catalog_management
- [N-16] Upload inventory (catálogos de WhatsApp) — https://developers.facebook.com/documentation/business-messaging/whatsapp/catalogs/upload-inventory.md
- [N-17] ProductCatalog reference (bordes `agencies`, `assigned_users`) — https://developers.facebook.com/docs/marketing-api/reference/product-catalog/
- [N-18] Migrating phone numbers among Solution Partners via Embedded Signup — https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/support/migrating-phone-numbers-among-solution-partners-via-embedded-signup
- [N-19] Phone numbers — https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
- [N-20] Migrating customers off solutions via Meta Business Suite — https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/support/migrating-customers-off-solutions-via-meta-business-suite.md
- [N-21] App Review — introducción (evaluación por permiso; rechazo completo si no se puede acceder a la app) — https://developers.facebook.com/docs/app-review/introduction
- [N-22] App Review — guía de envío (cada permiso con su descripción y su grabación) — https://developers.facebook.com/docs/app-review/submission-guide
- `[S]` Aprobación parcial (caso de 12 de 15 permisos) — consultor, https://singhamandeep.com/?p=3065 (sin respaldo oficial)
- `[S]` Centro de ayuda de Meta, «Give a partner access to business assets» — https://www.facebook.com/business/help/1717412048538897 (resumen del buscador; la página no se pudo leer directamente)
- `[S]` Centro de ayuda de Meta, «Conectar un catálogo a tu cuenta de WhatsApp Business» — https://www.facebook.com/business/help/158662536425974 (solo el título fue legible)
- `[S]` Retiro de Access Verification (anuncio del 2026-10-09) — https://socialmediatoday.com/news/meta-removes-access-verification-for-developers/832678
- Precios de mensajes de servicio: [M-12] de `docs/opciones-catalogo-whatsapp.md` (acceso 2026-11-03).
