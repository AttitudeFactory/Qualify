# Backlog — Captación en mostrador: QR → cupón de bienvenida → lead con canal WhatsApp abierto

**Fecha:** 2026-08-23 · **Estado:** `[INICIATIVA DEL FUNDADOR — alcance PROPUESTO, pendiente de refinamiento]`
**Origen:** instrucción del fundador (2026-08-23): *«para que el cliente obtenga el cupón a través de WhatsApp y ya saltarme la validación de WhatsApp para futuras campañas, dejo un QR en la tienda que abre un chat que el cliente envía al número y configuro un agente de respuesta automático con el cupón, y por detrás configuro la entrada a Qualify del lead»*.
**Track:** dogfooding sobre medio propio (patrón ADR 21) — cliente cero son los dos locales de comida del fundador (Bianki + Polet, Korner Club, San Cristóbal). Es el **upstream de la iniciativa Loyalty**: captura al comprador que loyalty después retiene. **No toca el camino crítico de Fase 1 Parte 3; su slice 1 no necesita ninguna API de Meta ni WABA.**
**Docs relacionados:** [`backlog-loyalty-sellos-cupones.md`](backlog-loyalty-sellos-cupones.md) (LOY-04/06/07 se reutilizan acá) · [`ingenieria-inversa-manychat.md`](ingenieria-inversa-manychat.md) §6 (la regla que gobierna CAP-06) · migración `0006_leads` + `packages/api/src/qualify_api/leads/` (**aterrizada y commiteada** — el backlog de loyalty la cita como «0005 en vuelo»; renumerada, verificado en disco 2026-08-23) · [`modelo-negocio-operador-multi-emprendimiento.md`](modelo-negocio-operador-multi-emprendimiento.md) `[FIRMADO]`.

---

## 0. La idea del fundador, y el ajuste que propone este doc

La idea cruda es QR → chat de WhatsApp → bot responde con el cupón → lead entra a Qualify por detrás. El objetivo real detrás de ella (dicho por el fundador): **que el cliente inicie la conversación**, para que el número quede como contacto con chat abierto y las campañas futuras no dependan de validaciones ni de que el cliente agregue el número.

El ajuste: **el mismo objetivo se cumple sin bot y sin WABA, con una pieza que el repo ya tiene construida.** La forma recomendada:

```
QR en mostrador/empaque
  → formulario público de leads (0006: nombre + teléfono + CONSENTIMIENTO versionado)
    → intake crea/upserta el lead  +  auto-otorga el cupón de bienvenida (LOY-04, código único)
      → pantalla de éxito muestra el cupón  +  botón wa.me al número del local
        con mensaje precargado: «¡Hola! Soy {nombre}, mi cupón es {CÓDIGO} 🎁»
          → el cliente ENVÍA → chat abierto en el WhatsApp Business App del local
            → saludo automático del App (estático) + respuesta rápida de la cajera
```

Por qué esta forma y no el chat directo con bot:

1. **El «agente de respuesta automático» programático no existe sin pagar uno de dos peajes.** O WhatsApp Business **Platform** (Cloud API: webhook + plantillas + Business Verification — y el número migrado a la API **deja de poder usarse en el App del teléfono** que las cajeras van a operar), o un vendor tipo ManyChat/respond.io. La casa ya falló sobre esto: *«el acceso aprobado a las APIs de mensajería es infraestructura commodity que se compra, no se construye»* (`ingenieria-inversa-manychat.md` §6.3). Ninguno de los dos peajes se justifica con volumen cero.
2. **El chat directo no captura consentimiento ni datos estructurados.** Un mensaje entrante trae un teléfono y texto libre; la fila de lead de `0006` **no puede existir** sin `consent_at` + `consent_policy_version` (decisión ya cableada en el esquema, NOT NULL). El formulario es el único punto del flujo donde el consentimiento con fin promocional se registra como hecho auditable. Sin él, loyalty no puede enviarle nada después (riesgo §5.2 del backlog LOY).
3. **La entrega del cupón ya es automática** — la hace la web en el intake, no un bot. Lo que el fundador quería del bot (respuesta inmediata con el cupón) lo da la pantalla de éxito + el mensaje precargado; el **saludo automático del WhatsApp Business App** (gratis, estático, se configura en el teléfono) cubre la cortesía de respuesta inmediata en el chat.
4. **El opt-in conversacional se logra igual o mejor:** el cliente envía el primer mensaje, con su código adentro — la cajera guarda el contacto con nombre y el hilo queda abierto para siempre en el App (sin ventana de 24 h, porque no es API).

Lo que del plan original queda para después, con datos: el bot de verdad (CAP-06, gated).

---

## 1. Verificaciones de terreno hechas en esta pasada (2026-08-23)

- **`0006_leads` aterrizó** (era «0005 en vuelo» en el backlog LOY): `leads` con `UNIQUE(tenant_id, whatsapp_phone)`, consent NOT NULL versionado, `lead_form_settings.custom_fields`, y el handoff `wa.me` post-submit ya es parte del diseño del módulo (`models.py`: «the wa.me handoff target after a successful intake»). **CAP construye sobre esto; no crea entidad de persona nueva** (misma regla que LOY-01).
- **La respuesta a LOY-00.2 (¿qué POS?) ya existe:** el fundador invierte en la **Suite Alimentos y Bebidas de a2 Softway** + impresoras fiscales homologadas SENIAT. Es un sistema Windows cerrado, sin webhooks ni API de ventas → **el sello/redención manual de LOY-03/LOY-07 se queda como diseño, no como fallback.** En mostrador el cupón se cobra como descuento autorizado en a2 (la cajera lo aplica; la factura fiscal imprime el descuento); la **validación del código y el marcado `redeemed` ocurren en Qualify** (LOY-07). a2 nunca conoce campañas; Qualify nunca toca la factura.
- Los dos locales abren **septiembre 2026** — el slice 1 debe poder operarse con el App de WhatsApp en el teléfono del local y cero dependencias nuevas de Meta.

## 2. Items

### CAP-00 — [GATE] Comparte y extiende el gate de loyalty (LOY-00)

1. Los dos locales = **un tenant** (L1 del backlog LOY — sigue sin firmar; este backlog también lo necesita).
2. El **texto de consentimiento** del formulario debe cubrir explícitamente «envío de promociones y cupones por WhatsApp» (versionarlo si no — `consent_policy_version` existe para esto). Nota de jurisdicción: los locales son en Venezuela; el patrón de `0006` cita Ley 1581 (CO) — revisar que el texto sea válido/razonable para VE, la mecánica de versionado no cambia.
3. **Decidir dónde vive el formulario público:** (a) página pública del Reflex de Qualify, o (b) una página en `attitude-site` (Next.js, donde ya viven las landings `bianki.attitudefactory.co` / `polet.attitudefactory.co`) que pegue a la API de Qualify. La (b) tiene mejor estética de marca y dominio ya desplegado; la (a) no cruza repos. Decisión chica pero bloquea CAP-01.
- **Prioridad / tamaño:** Bloqueante / S.

### CAP-01 — Campaña de captación con atribución de origen

- **Historia:** Como operador, quiero que cada QR pertenezca a una campaña con origen (`qr_mostrador_bianki`, `qr_empaque_polet`, `qr_ticket`), para saber qué superficie captura y qué marca convierte.
- **Criterios:** entidad campaña por tenant (nombre, origen, marca/local, vigencia, cupón asociado); la URL del QR lleva el identificador de campaña; el lead capturado queda atribuido a la campaña (verificar qué trae `0006` de attribution y extender solo si falta). RLS patrón R7, como todo.
- **Dependencias:** CAP-00. · **Prioridad / tamaño:** Alta / S.

### CAP-02 — Auto-otorgamiento del cupón de bienvenida en el intake

- **Historia:** Como cliente, al dejar mis datos quiero ver mi cupón al instante, para sentir que el QR me dio algo real.
- **Criterios:** el intake de un lead vía campaña con cupón asociado otorga **automáticamente** un cupón individual (código único, FSM de LOY-04: nace `active`→`sent` al mostrarse); idempotente — re-submit del mismo teléfono NO otorga segundo cupón (el upsert de `0006` + un guard por campaña); el otorgante queda registrado como `system:campaign` (nuevo valor de provenance — LOY-04 asume otorgante humano, extender).
- **Dependencias:** CAP-01, LOY-04. **Nota de orden:** si loyalty no ha construido LOY-04 aún, CAP-02 lo construye primero — es la misma tabla/FSM, no un fork.
- **Prioridad / tamaño:** Alta / M.

### CAP-03 — Pantalla de éxito + handoff `wa.me` con el cupón adentro

- **Historia:** Como cliente, tras el formulario quiero ver el cupón y un botón que abra el chat del local con mi mensaje listo, para no escribir nada.
- **Criterios:** pantalla de éxito con código, premio, vigencia y condiciones (siempre visibles — regla LOY-06); botón → `wa.me/<número_del_local>?text=` con nombre + código precargados; el número es por local/marca (config de campaña); si el cliente no toca el botón, el cupón igual quedó otorgado y visible. Documentar en la guía de operación: el **saludo automático** y las **respuestas rápidas** del WhatsApp Business App del teléfono del local (config manual, no código).
- **Dependencias:** CAP-02. · **Prioridad / tamaño:** Alta / S.

### CAP-04 — Los QR físicos y su generación

- **Historia:** Como operador, quiero generar el QR de cada campaña listo para imprimir, para ponerlo en mostrador, empaque y ticket sin pedirle nada a nadie.
- **Criterios:** QR por campaña desde la UI (PNG/SVG descargable, con URL corta propia — ver CAP-05); coordinar con Henry (branding) la pieza física (stand de mostrador, sticker de empaque). El troquel es asunto del proyecto locales, no de Qualify — Qualify entrega el QR.
- **Dependencias:** CAP-01. · **Prioridad / tamaño:** Media / S.

### CAP-05 — Funnel de la captación (la medición que decide)

- **Historia:** Como fundador, quiero ver por campaña: escaneos → formularios completados → chats iniciados → cupones redimidos, para saber si el QR del mostrador paga su espacio.
- **Criterios:** escaneos medibles vía redirect propio con contador (la URL del QR pega a Qualify y redirige al form); «chat iniciado» se aproxima por clic en el botón `wa.me` (evento de frontend) — honesto en la UI sobre que es aproximación; redimidos viene de LOY-07. Queries directas sobre transaccional, sin plano analítico, sin Celery (regla LOY-08).
- **Dependencias:** CAP-02, LOY-07. · **Prioridad / tamaño:** Media / S.

### CAP-06 — [GATED — no construir sin decisión del fundador] El bot de verdad

- Cuando el volumen de chats duela en manos de las cajeras, la respuesta automática programática es **compra, no build**: ManyChat / respond.io / WABA Cloud API directa — la misma familia de decisión que la tensión Zernio de Parte 4-A/B (aggregator vs `connections/` propio) y la regla de `ingenieria-inversa-manychat.md` §6.3. Peajes a nombrar el día que se abra: número migrado a API sale del App del teléfono (cambia la operación de las cajeras → el inbox pasaría a la UI de Qualify, que es Parte 4-B extendida a un canal más), plantillas por aprobar, Business Verification, costo por conversación.
- **El dato que lo abre:** CAP-05 mostrando N chats/día que la cajera no alcanza a responder, o LOY-06 mostrando que la cola de envíos asistidos duele. Sin ese número, este item no existe.

---

## 3. Riesgos

1. **Fricción del formulario.** Un form largo mata el escaneo-a-lead. Máximo: nombre + teléfono + checkbox de consentimiento. Todo lo demás es CAP-futuro.
2. **El QR que nadie escanea.** Sin incentivo visible no hay captación: la pieza física debe decir qué gana el cliente («tu primer topping gratis», «10% en tu próxima visita») — coordinar el copy con la estrategia de contenido de los locales (`estrategia-contenido-bianki-polet.md`).
3. **Doble canje en mostrador.** El código se valida en Qualify (estado, LOY-07) pero el descuento se aplica en a2 a mano — la cajera puede aplicar descuento sin validar código. Mitigación de proceso, no de código: regla operativa «sin `redeemed` en pantalla no hay descuento», y el reporte de descuentos de a2 vs canjes de Qualify como conciliación semanal del operador.
4. **Deriva de dependencia.** LOY sigue `[PROPUESTO]` y sin construir; CAP-02 depende de su FSM de cupones. Quien tome este backlog en el worktree verifica contra disco qué existe de LOY y construye la tabla/FSM una sola vez, del lado que arranque primero.

## 4. Decisiones que necesita el fundador

| # | Pregunta | Recomendación |
|---|---|---|
| **C1** | ¿Forma del flujo: form-primero (este doc) o chat-primero (idea original)? | **Form-primero** — consentimiento + datos estructurados + cupón instantáneo sin WABA (§0) |
| **C2** | ¿Dónde vive el form público? | `attitude-site` con API de Qualify (estética de marca, dominio vivo) — salvo que cruzar repos moleste más de lo que aporta |
| **C3** | ¿Un número de WhatsApp por marca o uno por local? | Por marca (Bianki y Polet ya tienen identidad separada); el número es config de campaña, cambiarlo no rompe nada |
| **C4** | ¿Cupón de bienvenida inicial? | Definir el premio con margen real (p. ej. topping gratis / % en segunda visita — empuja recompra, no canibaliza la primera) |
| **C5** | L1 de loyalty (un tenant para los dos locales) | Sigue pendiente y bloquea ambos backlogs — firmarla primero |

## 5. Arranque en el worktree (para la próxima sesión)

Orden sugerido: CAP-00 (decisiones C1–C5 firmadas acá o en `arquitectura.md` §6) → verificar contra disco el estado real de LOY-04 → CAP-01/02 (migración nueva sobre el patrón `0006`, RLS en la misma revisión) → CAP-03 → CAP-04/05. Recordatorios de la casa que muerden en worktrees: leer el filesystem, no los docs, para lo que existe; y la trampa `UF_HIDDEN` sobre `.venv` en `.claude/worktrees/` — el bypass es `PYTHONPATH` (documentado en `CLAUDE.md`, sección de trampas operativas) antes que pelear con `chflags`.
