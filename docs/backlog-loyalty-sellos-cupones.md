# Backlog — Iniciativa Loyalty: sellos por compra + cupones/promociones por comunidad

**Fecha:** 2026-08-16 · **Estado:** `[INICIATIVA DEL FUNDADOR — alcance PROPUESTO, pendiente de refinamiento]`
**Origen:** instrucción del fundador (2026-08-16): *«programas de loyalty para los clientes que ya han comprado — para mis dos locales, sellos que se acumulan en cada compra; cupones de descuento o acceso a promociones por pertenecer a X comunidad; yo genero esos descuentos desde mi portafolio, quedan activados, y se los envío a su WhatsApp o correo para redimir en X cantidad de tiempo sujeto a condiciones comerciales»*.
**Track:** dogfooding sobre medio propio (el patrón de ADR 21) — cliente cero son los dos locales del fundador. **No toca el camino crítico de Fase 1 Parte 3, no necesita ninguna API de Meta ni App Review** en su primer slice.
**Docs relacionados:** [`modelo-negocio-operador-multi-emprendimiento.md`](modelo-negocio-operador-multi-emprendimiento.md) `[FIRMADO 2026-08-16]` · migración en vuelo `0005_leads` (ver §2, es la dependencia clave) · [`arquitectura.md`](arquitectura.md) §6.

---

## 0. Qué es y qué no es

**Es:** un módulo de retención para clientes finales que **ya compraron** — (a) tarjeta de sellos digital que se acumula por compra y canjea un premio al completarse, y (b) cupones/promociones dirigidos, generados por el operador, entregados por WhatsApp o correo, con ventana de redención y condiciones comerciales.

**No es:**
- El CRM de creators de Fase 4 (`crm.creators` — otra entidad, otro propósito).
- Outreach de Fase 5 (Instantly/Smartlead — eso es prospección fría a creators/leads B2B; esto es retención B2C de compradores existentes).
- `billing.usage_events` (los créditos que Qualify cobra a sus tenants — nada que ver con los descuentos que un tenant da a sus clientes).
- Mensajería autónoma. El envío es **asistido u operado por el fundador** — coherente con la línea ya firmada en ADR 21 (asistido sí, autónomo no).

---

## 1. Encaje con el modelo recién firmado — y la palabra «portafolio» hay que pincharla

El fundador dice *«yo generaré esos descuentos desde mi portafolio»*. Bajo el modelo firmado **el mismo día** (`1 login = 1 tenant = 1 negocio`, sin identidad global de operador), **el sistema no tiene portafolio**: tiene N tenants que no saben que comparten dueño. Consecuencias, dichas de frente:

1. **Los cupones y programas de sellos se crean y viven DENTRO de cada negocio** (tenant). «Desde mi portafolio» se implementa como: entrás al negocio con su login, generás ahí. Para los dos locales de comida rápida esto no cuesta nada **si los dos locales son un solo tenant** (la cadena), que es lo que la regla de D1 del doc de operador ya recomendaba: un local no es un emprendimiento, es un activo. **El programa de sellos es de la cadena y el sello registra en qué local se compró** — el cliente acumula comprando en cualquiera de los dos. Esto convierte a D1 de recomendación en necesidad: **LOY-00 la firma o este backlog no arranca.**
2. **Un cupón cross-negocio** (comprá en la hamburguesería, descuento en la agencia de viajes) **está bloqueado por diseño**, no por olvido: exigiría la identidad de operador que el ruling del 2026-08-16 descartó a sabiendas. Si algún día se quiere, es la reapertura de esa puerta (con su migración de credenciales), no un feature de este módulo. Se nombra y se deja fuera.
3. **La «comunidad» no es cross-tenant tampoco:** es un segmento de clientes *dentro* de un negocio («los del grupo de WhatsApp del local», «los seguidores del gimnasio X con quien hice alianza»). La pertenencia la administra el operador como etiqueta/lista; de dónde viene la lista (alianza comercial, grupo, evento) es un hecho del mundo, no del esquema.

---

## 2. La dependencia que cambia el diseño: la entidad persona YA está en construcción

Verificado en el working tree (2026-08-16, **sin commitear aún** — migración `0005_leads` + `packages/api/src/qualify_api/leads/`, de otra sesión en vuelo): existe un plano de **leads** por tenant con exactamente las decisiones que loyalty necesita:

- `UNIQUE(tenant_id, whatsapp_phone)` — el teléfono como identidad de persona portable, dedup por tenant con upsert idempotente. **La misma persona puede ser cliente de dos negocios del fundador: dos filas, una por tenant.** Coherente con §1.
- **Consentimiento como hecho, no como flag:** `consent_at` + `consent_policy_version` `NOT NULL` — una fila no puede existir sin registrar cuándo y contra qué texto legal consintió (Ley 1581/habeas data CO; el texto legal es por tenant porque sigue al país del negocio). **Loyalty hereda este patrón sin discusión:** guardar el WhatsApp de un comprador para mandarle cupones es tratamiento de datos personales con fin comercial, y el consentimiento del formulario de captura debe cubrir ese fin o pedirse aparte.
- **WhatsApp por `wa.me` handoff, sin WhatsApp Business API.** El módulo de leads ya entrega por link `wa.me` con mensaje pre-llenado. Ésa es la casa apostando por el camino sin WABA, y loyalty lo reutiliza (ver LOY-06).

**Regla para quien construya esto: loyalty NO crea una segunda entidad de persona.** El cliente de loyalty es el lead que compró — una extensión/estado del plano de leads, no una tabla `customers` paralela que duplique teléfono y consentimiento. Si `0005` cambia antes de aterrizar (está sin commitear), este backlog se re-verifica contra lo que aterrice — **contra el filesystem, no contra este doc**.

---

## 3. El hueco duro del que nadie hablará si no se escribe: Qualify no ve las compras

Los sellos se acumulan *«en cada compra»* — y la compra ocurre en el mostrador del local, fuera de Qualify. No hay POS integrado, no hay webhook de ventas. **El evento de compra es el input crítico del programa y hoy no existe ninguna fuente para él.** Opciones, de menos a más infraestructura:

| Mecanismo | Cómo | Coste | Veredicto |
|---|---|---|---|
| **Manual por el staff** | El cajero busca al cliente (teléfono) en la UI del tenant y marca el sello | Cero integración; fricción en mostrador ~segundos | **Día uno.** Es además el único que funciona en ambos locales sin importar qué caja usen |
| QR del cliente | El cliente muestra un QR con su identidad; el staff escanea y sella | UI extra, mismo backend | Slice 2 si la fricción manual duele |
| Webhook del POS (p. ej. Shopify) | La venta dispara el sello sola | Integración real; depende del POS de cada local | Sólo si el POS lo soporta — **investigar qué caja usan los locales antes de prometerlo** (LOY-00) |

El criterio de muerte del programa entero vive aquí (§5): si sellar cuesta más fricción en el mostrador que el valor que percibe el cliente, el programa muere por abandono del staff, no del cliente.

---

## 4. Items

### LOY-00 — [GATE] Decisiones previas del fundador + verificación del terreno

- **Tipo:** decisión + investigación corta. Bloquea todo lo demás.
- **Contenido:**
  1. **Firmar D1 del doc de operador en su forma concreta:** los dos locales = **un** tenant (la cadena); el local es un atributo del sello, no un tenant. Sin esto no hay programa compartido entre locales.
  2. Responder qué **caja/POS** usa cada local (¿algo integrable, o mostrador puro?) — decide el techo de LOY-03.
  3. Confirmar que el **texto de consentimiento** del formulario de leads cubre el fin «envío de promociones/cupones»; si no, redactar la versión que sí y versionarla (`consent_policy_version` ya existe para esto).
  4. Formalizar el alcance como ADR propio en `arquitectura.md` §6 (el siguiente número libre — el 35 está reservado por RET-01 del backlog de retención).
- **Prioridad / tamaño:** Bloqueante / S.

### LOY-01 — El cliente comprador sobre el plano de leads (no una entidad nueva)

- **Historia:** Como operador, quiero que un lead que compró quede marcado como cliente con su historial de sellos y cupones, para no administrar dos listas de la misma persona.
- **Criterios de aceptación:**
  - Extensión del plano de leads (estado/flag de comprador + relación a sellos/cupones), **cero duplicación** de teléfono/consentimiento. Migración Alembic con RLS en la misma revisión (regla de la casa, patrón `0005`).
  - Alta manual desde la UI del tenant (el cajero registra al cliente nuevo con su teléfono en el momento de la primera compra) además de la vía formulario público ya existente.
  - Todas las tablas nuevas: `tenant_id NOT NULL` + RLS con el `NULLIF` de R7. Nada de esto entra al plano analítico.
- **Dependencias:** LOY-00; que `0005_leads` haya aterrizado (verificar contra disco).
- **Prioridad / tamaño:** Alta / M.

### LOY-02 — Programa de sellos configurable

- **Historia:** Como operador, quiero definir por negocio un programa «N sellos → premio» con sus condiciones comerciales, para que la mecánica sea un dato y no código.
- **Criterios de aceptación:**
  - Config por tenant: N requerido, descripción del premio, condiciones (texto), vigencia del programa, y si el sello exige monto mínimo (condición declarada, validación humana en mostrador).
  - Una tarjeta activa por cliente y programa; al completar N, la tarjeta pasa a `reward_earned` y el premio se redime como un cupón más (reutiliza LOY-04 — un solo flujo de redención, no dos).
  - Cambiar N en un programa con tarjetas vivas **no** re-escribe tarjetas existentes: versionar el programa (patrón provenance de la casa: la tarjeta apunta a la versión bajo la que se abrió).
- **Dependencias:** LOY-01. · **Prioridad / tamaño:** Alta / M.

### LOY-03 — Registrar el sello (el evento de compra)

- **Historia:** Como cajero, quiero marcar el sello de un cliente en segundos desde el mostrador, para que la cola no se detenga.
- **Criterios de aceptación:**
  - Búsqueda por teléfono (últimos dígitos) en la UI del tenant → un tap → sello registrado. Objetivo: **< 10 s** de fricción total en mostrador.
  - **Idempotencia real:** dos taps del cajero nervioso = un sello. Ventana de dedup (mismo cliente, mismo local, < X min) declarada, no accidental.
  - Cada sello lleva provenance: quién lo otorgó (usuario), en qué local, cuándo. El local es un atributo del sello (LOY-00.1).
  - Deshacer (anular un sello) existe y queda auditado — el error de mostrador es cotidiano.
- **Dependencias:** LOY-02. · **Prioridad / tamaño:** Alta / M. QR/POS = slices posteriores, sólo si LOY-00.2 lo habilita.

### LOY-04 — Cupones: generación, activación, ciclo de vida

- **Historia:** Como operador, quiero generar un cupón o promoción (descuento o regalo), activarlo, y que tenga código único, ventana de redención y condiciones comerciales, para controlarlo de punta a punta.
- **Criterios de aceptación:**
  - Ciclo de vida explícito como FSM (patrón C-03 de la casa): `draft → active → sent → redeemed | expired | cancelled`. Transiciones auditadas.
  - Código único por otorgamiento (cupón asignado a una persona), no un código genérico compartido — es lo que hace la redención verificable y de un solo uso. Los cupones «de comunidad» se materializan como otorgamientos masivos a los miembros del segmento.
  - Ventana de redención (*«en X cantidad de tiempo»*): `valid_from`/`valid_until` obligatorios; expirado es un estado alcanzado por el reloj, verificado en la redención (no hace falta un job que "expire" filas para el día uno).
  - Condiciones comerciales: texto por cupón, visible para el cliente antes de redimir y para el staff al redimir. El sistema las **muestra**; la validación de fondo (monto mínimo, no acumulable) es del humano en mostrador — no se pretende motor de reglas en el slice 1.
- **Dependencias:** LOY-01. · **Prioridad / tamaño:** Alta / M.

### LOY-05 — Comunidades como segmentos de elegibilidad

- **Historia:** Como operador, quiero agrupar clientes en comunidades (alianzas, grupos, eventos) y dirigirles promociones por pertenecer, para premiar la pertenencia sin repartir descuento a todo el mundo.
- **Criterios de aceptación:**
  - Comunidad = etiqueta/lista por tenant con nombre y origen; membresía administrada a mano por el operador (alta/baja). Nada de detección automática en este slice.
  - Un otorgamiento masivo a una comunidad genera un cupón individual por miembro (código único cada uno — LOY-04).
  - Un cliente puede pertenecer a N comunidades; la comunidad nunca cruza tenants (§1.3).
- **Dependencias:** LOY-04. · **Prioridad / tamaño:** Media / S.

### LOY-06 — Envío asistido a WhatsApp o correo

- **Historia:** Como operador, quiero enviarle el cupón al cliente por WhatsApp o correo con un mensaje listo, para que le llegue donde de verdad lo lee.
- **La decisión de diseño que evita comprar un reloj ajeno:** el envío del slice 1 es **asistido, sin WhatsApp Business API**: el sistema genera el mensaje (código, premio, vigencia, condiciones) y un link `wa.me` pre-llenado — el patrón que el módulo de leads ya usa — y **el operador toca "enviar" desde su propio WhatsApp**. Cero WABA, cero plantillas por aprobar, cero costo por conversación, cero Business Verification en el camino. El envío por correo y el WhatsApp API (envío masivo real) son slices posteriores y **son compra, no build** (regla de la casa: mailbox/mensajería es infraestructura comprada).
- **Criterios de aceptación:**
  - Desde el cupón otorgado: botón «enviar por WhatsApp» → `wa.me/<phone>?text=<mensaje>` con el mensaje completo; el estado pasa a `sent` con canal y timestamp.
  - El mensaje incluye siempre: qué gana, código, hasta cuándo, condiciones. Sin sorpresas en mostrador.
  - Registro de a quién se envió qué y cuándo (es la mitad de la medición de LOY-08).
  - Envío masivo a comunidad = cola de envíos asistidos uno a uno (el operador avanza tocando), honesta sobre su fricción — si duele, ése es el dato que justifica pagar WABA, y se sabrá con números.
- **Dependencias:** LOY-04. · **Prioridad / tamaño:** Alta / S.

### LOY-07 — Redención en mostrador

- **Historia:** Como cajero, quiero validar un cupón por su código en segundos y marcarlo redimido, para aplicar el descuento sin discutir con nadie.
- **Criterios de aceptación:**
  - Buscar por código → el sistema muestra: válido/no (vigencia, estado), qué otorga, condiciones. Un tap → `redeemed`, idempotente (redimir dos veces es imposible por estado, no por atención del cajero).
  - Fuera de ventana o ya redimido → mensaje claro de rechazo con el motivo. El override (aceptarlo igual por cortesía comercial) existe, requiere el rol dueño y queda auditado.
  - La redención registra local, usuario y timestamp — misma provenance que el sello.
- **Dependencias:** LOY-04. · **Prioridad / tamaño:** Alta / S.

### LOY-08 — Medición mínima (la que decide si esto vive)

- **Historia:** Como fundador, quiero ver tasa de redención, sellos activos y frecuencia de recompra de clientes con tarjeta vs sin ella, para saber si el programa mueve la caja o solo reparte descuento.
- **Criterios de aceptación:** por tenant y por periodo: cupones otorgados/enviados/redimidos (funnel), tarjetas abiertas/completadas, tiempo medio entre sellos. Todo sale de las tablas transaccionales con queries directas — **sin** plano analítico, **sin** Celery.
- **Dependencias:** LOY-03, LOY-07. · **Prioridad / tamaño:** Media / S.

---

## 5. Riesgos y criterios de muerte

1. **Fricción en mostrador (el asesino probable).** Si sellar/redimir toma más de ~10 s o exige pelear con una búsqueda, el staff deja de hacerlo en la segunda semana y el programa muere en silencio. Por eso LOY-03/LOY-07 llevan objetivo de segundos y por eso QR/POS esperan datos, no fe. **Kill criterion: si a 4 semanas del piloto en un local la mitad de las compras de clientes registrados no registran sello, el mecanismo manual está muerto — se integra POS o se mata el programa.**
2. **Habeas data (Ley 1581, CO).** Enviar promociones al WhatsApp de un comprador exige consentimiento para ese fin, revocable, con el texto versionado. El patrón de `0005` ya lo resuelve **si LOY-00.3 confirma que el texto cubre el fin promocional.** Sin eso, no se envía nada.
3. **Fraude de redención.** Mitigado por diseño barato: código único por persona + un solo uso por estado + validación humana de condiciones. No se construye motor anti-fraude para dos locales.
4. **El envío asistido no escala** — y está bien. Es la versión que mide si los clientes redimen antes de pagar WABA/email por volumen. Si la cola de envíos duele, ese dolor con números es la justificación de compra (regla de la casa: buy, no build, para mensajería).
5. **Dependencia en vuelo.** `0005_leads` no está commiteado. Si no aterriza o cambia de forma, LOY-01 se re-especifica contra lo que exista en disco.

---

## 6. Decisiones que necesita el fundador (resumen)

| # | Pregunta | Recomendación |
|---|---|---|
| **L1** | ¿Los dos locales = un tenant (la cadena), con el local como atributo? | **Sí** — sin esto no hay sellos compartidos entre locales (§1.1). Firma D1 del doc de operador de paso |
| **L2** | ¿Qué POS/caja usa cada local? | Responder antes de prometer integración; el día uno es manual igualmente |
| **L3** | ¿El texto de consentimiento actual cubre el envío de promociones? | Verificar; si no, nueva versión del texto (el esquema ya versiona) |
| **L4** | ¿Cupón cross-negocio? | **No** — bloqueado por el modelo firmado `1 login = 1 tenant`; reabrirlo es reabrir la identidad de operador, no un feature de loyalty (§1.2) |
| **L5** | ¿Primer piloto? | Un solo local, programa de sellos simple (p. ej. 7 compras → 1 gratis), 4 semanas, medición LOY-08 antes de encender cupones de comunidad |
