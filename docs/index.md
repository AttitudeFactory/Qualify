# Qualify — Documentación

Plataforma agentiva de CRM/GTM para social listening sobre TikTok/IG Reels. Tesis central: leer **contenido primario** (video, audio, captions, comentarios) en vez de bios o metadata autodeclarada.

## Empezar por acá

- **[Registro de validación de features](registro-validacion-features.md)** — qué feature está respaldada por qué investigación de mercado, organizada por eje (inbound/outbound) y nicho. El árbol visual de todo el trabajo de investigación está ahí.
- **[Proceso para futuras investigaciones](proceso-investigacion-oportunidades.md)** — cómo y cuándo se dispara una nueva investigación de nicho.
- **[Arquitectura general](arquitectura.md)** — decisiones de sistema, ADRs, reglas arquitectónicas duras.
- **[Exploración de naming y dominios](naming-dominios-exploracion.md)** — candidatos de marca validados (disponibilidad, SEO, audiencia), podio al cierre y la decisión interina de desplegar bajo el dominio de Attitude (2026-08-10).

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
