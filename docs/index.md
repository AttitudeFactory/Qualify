# Qualify — Documentación

Plataforma agentiva de CRM/GTM para social listening sobre TikTok/IG Reels. Tesis central: leer **contenido primario** (video, audio, captions, comentarios) en vez de bios o metadata autodeclarada.

## Empezar por acá

- **[Runbook — Mentions v1: configuración y prueba E2E](mentions-e2e-runbook.md)** — QUA-97 está Done en código/tests (IG caption/comment); este es el procedimiento corto y accionable para la primera prueba real en cuanto Business Verification desbloquee Advanced Access — no requiere volver a investigar nada.
- 🔴 **[PRIORIDAD — despliegue en `qualify.attitudefactory.co`](prioridad-despliegue-subdominio.md)** — el dominio ya está comprado y vivo (2026-08-12); falta desplegar Qualify para tener un redirect URI de OAuth estable. Bloquea toda la cadena hacia Business Verification y Tech Provider. **Una sola decisión abierta: dónde se aloja.**
- **Motor de Contenido de Marca** (track paralelo, 2026-08-16) — generación de copy + imagen con la voz de la marca del cliente: [backlog](backlog-motor-contenido-marca.md) · [diseño técnico cerrado](diseno-motor-contenido-marca.md).
- 🟡 **[UI — Brand Kit por pasos](ui-brandkit-wizard.md)** `[EN CURSO, sesiones 2026-09-02/03]` — `/brand` pasó de acordeón a dos flujos guiados (manual de 9 pasos, "ya tengo redes" de 11); el acordeón original sigue en el código sin ruta. Incluye la división de la paleta (rueda agrega, swatch edita) y el cambio de `app_shell` a panel con scroll propio, que **afecta a todas las pantallas**. Sin commitear.
- **[Registro de validación de features](registro-validacion-features.md)** — qué feature está respaldada por qué investigación de mercado, organizada por eje (inbound/outbound) y nicho. El árbol visual de todo el trabajo de investigación está ahí.
- **[Proceso para futuras investigaciones](proceso-investigacion-oportunidades.md)** — cómo y cuándo se dispara una nueva investigación de nicho.
- **[Arquitectura general](arquitectura.md)** — decisiones de sistema, ADRs, reglas arquitectónicas duras.
- **[UX/UI y Design System](design-system.md)** — `[v1 2026-08-18]` principios, tokens (teal/slate, Plex Sans+Mono, tonos por rol), shell de página, primitivas (`Qualify/ui/`), patrones de estado, escritura UX y accesibilidad. Guía viva renderizada en la ruta `/design` de la app.
- **[Modelo de negocio — operador multi-emprendimiento](modelo-negocio-operador-multi-emprendimiento.md)** — `[FIRMADO 2026-08-16]` N negocios propios sobre la misma instalación, **`1 login = 1 tenant = 1 negocio`, sin switch** (se cambia de negocio con logout + login). Fija para QUA-66 la higiene de logout: estado Reflex destruido, token de sesión rotado, y todo lo persistido en el cliente namespaced por `tenant_id`.
- **[Plan — QUA-66: Supabase Auth conectado a `tenant_id`](plan-integracion-supabase-auth-tenant.md)** — `[PLAN, alcance confirmado 2026-08-18]` Supabase como proveedor de identidad (los datos siempre en el Postgres propio): el mapeo `credencial → tenant` vive en `app_metadata.tenant_id`, **registro autoservicio que auto-crea el tenant** (`/signup`), login server-side en Reflex, muerte del selector de dev. Fases F0-F4 hasta el primer negocio real logueado: **Polet Bubble Tea** (`polet.attitudefactory.co`).
- **[Iniciativa Loyalty — sellos + cupones](backlog-loyalty-sellos-cupones.md)** — retención para clientes que ya compraron: tarjeta de sellos por compra (los dos locales) y cupones/promociones por comunidad, enviados asistido por `wa.me` sin WhatsApp Business API. Gate: LOY-00 (los dos locales = un tenant; consentimiento promocional; qué POS hay).
- **[Retención de datos y coste de R2](backlog-retencion-datos-r2.md)** — la regla de guardar los binarios de earned media 7 días (techo 30) y purgar lo demás, con el modelo de coste y la única pregunta abierta al fundador (`RET-08`: si la purga alcanza también a las filas de Postgres).
- **[Exploración de naming y dominios](naming-dominios-exploracion.md)** — candidatos de marca validados (disponibilidad, SEO, audiencia) y podio al cierre. Su decisión interina (desplegar bajo el dominio de Attitude) ya se concretó: ver el documento de prioridad de arriba.

## Los dos ejes de producto

```mermaid
graph LR
    Q[Qualify] --> IN[Inbound<br/>social listening]
    Q --> OUT[Outbound<br/>gestión de cuentas / agencia]

    IN --> IN1[Leer contenido propio]
    IN --> IN2[Leer contenido ajeno<br/>earned media]

    OUT --> OUT1[Publicar en cuentas propias]
    OUT --> OUT2[Responder DMs/comentarios<br/>asistido, no autónomo]
    OUT --> OUT3[Gestionar N clientes<br/>modelo agencia]

    style Q fill:#4f46e5,color:#fff
    style IN fill:#0891b2,color:#fff
    style OUT fill:#ea580c,color:#fff
```

Ver el [registro completo](registro-validacion-features.md) para el árbol detallado de features, evidencia y estado por nicho.
