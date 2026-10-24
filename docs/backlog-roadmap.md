# Roadmap del backlog — épicas, responsables y decisiones

**Fecha:** 2026-10-24 · **Estado:** `[VIGENTE 2026-10-24 · m-24849204]`
**Fuente de verdad:** Meegle (espacio Qualify). Este documento es la foto del orden acordado con el
fundador el 2026-10-23; si Meegle y este documento difieren, manda Meegle y se corrige este.

## 1. El orden

| Horizonte | Épica (Meegle) | Prioridad | Responsable | Por qué en este lugar |
|---|---|---|---|---|
| **Ahora** | Meta App Review — permisos, videos y Tech Provider (`m-24786384`) | P0 | Herwin (trámites en Meta) · Raul (código: 24789548, 24789547, 24789558, 24849197) | Sin App Review no se atiende a clientes cuyos activos no administra el fundador. Falta el borrado de datos a 30 días (24789547), que Meta exige. |
| **Ahora** | DevSecOps: CI, despliegue y reversión (`m-24847987`) | P1 | Darwin | Recibe las historias de la antigua épica «Entornos dev/QA/prod»: QA, `QUALIFY_ENV`, secretos y R2 por entorno. |
| **Ahora** | Observabilidad y respuesta a fallos (`m-24847989`) | P1 | Darwin | Respaldos fuera del servidor con prueba de restauración (24824122), errores, `/api/health`, avisos en Lark. Hoy los respaldos viven en el mismo VPS. |
| **Ahora** | Atender conversaciones (`m-24786383`) | P1 | Herwin | Activar la Fase C de Interacciones en producción (24840401): código ya en `main`. |
| **Ahora** | WhatsApp (Cloud API), Bianki primero (`m-24789424`) | P1 | Herwin | WA-13 (24789629): alta del número de Bianki en Qualify y primera conversación real. Sin bloqueos. |
| **Ahora** | Qualify en palabras del dueño: navegación y experiencia (`m-24842956`) | P1 | Herwin (con los agentes) | En ejecución: varias historias ya resueltas el 2026-10-23. Detalle en [epica-ux-navegacion-experiencia.md](epica-ux-navegacion-experiencia.md). |
| **Siguiente** | Anuncios de Meta desde Qualify (`m-24828970`, ADR 38) | P2 (5 historias en P1) | Raul (Meta) · Deivid (creativo: 24828975, 24828982) | Casi todo espera `ads_management` (24828986). En P1 solo lo que se puede hacer ya: 24828971, 24828972, 24828973, 24828974, 24828975. Detalle en [epica-anuncios-meta.md](epica-anuncios-meta.md). |
| **Siguiente** | Estudio de contenido (`m-24803095`) | P2 | Deivid · Yesika (24803289) | Versiones al regenerar, campaña desde un reel, avatar, Seedance. |
| **Después** | Suscripciones y niveles de servicio (`m-24828931`) | P2 | Herwin | |
| **Después** | Altas de clientes y correo de invitación (`m-24786482`) | P2 | — | |
| **Después** | Migración a qualify.la (`m-24821370`) | P2 | — | Incluye el dominio canónico `app.qualify.la` (24828507). |
| **Después** | Landing de qualify.la en Astro (`m-24789423`) | P1 | — | Redirecciones (QLA-43), Clarity, accesibilidad. |
| **Después** | Publicar contenido (Meta) (`m-24789420`) | P2 | — | |
| **En revisión** | Motor de Ángulos, Fase 5 (`m-24789422`) | P2 | — | F5-MA-01…13 se escribieron para fal, FLUX, Kling y HeyGen; el código usa BytePlus. Pendiente la revisión del arquitecto antes de cerrar lo superado. |
| **En revisión** | Deuda de la cascada multimodal (`m-24789421`) | P2 | — | |
| **Estacionado** | Parking lot — features analizadas (`m-24789418`) | — | — | Incluye el anti-roadmap: respuestas autónomas con IA, publicación programada en TikTok. |

Épicas vaciadas, por terminar desde la interfaz de Meegle: «Entornos dev/QA/prod» (`m-24824104`) y
«Buenas prácticas de desarrollo» (`m-24847973`), ambas integradas en DevSecOps.

## 2. Decisiones del fundador (2026-10-23)

| # | Decisión | Ticket | Qué desbloquea |
|---|---|---|---|
| 1 | Responsables por épica como en la tabla de §1. Darwin toma plataforma y operación; la épica de UX queda con Herwin. | — | Que el equipo pueda mover sus tickets. |
| 2 | **Excepción acotada a «asistido, nunca autónomo»:** se permite un menú automático en mensajes directos solo si el texto es fijo y lo aprueba el dueño una vez, sin IA en el envío, con «Hablar con alguien» siempre disponible hacia la bandeja asistida. En pantalla se llama «Tu menú de bienvenida». | `m-24789557` | 24789558, 24789559; alinea 24789472 y 24842995. |
| 3 | **Firmar el ADR 29:** Qualify opera como Tech Provider de Meta con una sola app y tokens por empresa cliente. Agregador descartado. | `m-24789560` | Access Verification (24789561); historia nueva 24849197 (`client_business_id`). |
| 4 | **D1 de WhatsApp no aplica:** la integración con Baileys nunca existió; el número del negocio ya está en la Cloud API. | `m-24789629` | WA-13 sin bloqueos. |
| 5 | Anuncios: épica en P2, cinco historias en P1. La prueba en vivo se hace con la cuenta publicitaria de Bianki, confirmando presupuesto antes de gastar. | `m-24828970`, `m-24828971` | — |

## 3. Pendientes que no son del backlog

- **Arquitecto (`principal-architect`):** escribir la enmienda al ADR 21 (decisión 2); pasar el
  ADR 29 de `[PROPUESTO]` a firmado (decisión 3); revisar F5-MA-01…13 contra `packages/creative`.
- **Fundador:** terminar las dos épicas vaciadas en Meegle; confirmar si alguien del local de Bianki
  atendía +58 424-8837639 desde la app de WhatsApp (si es así, WA-13 pasa a P0: los mensajes
  llegan a la API y nadie los ve hasta el alta); decidir el costo de hacer cumplir la protección de
  `main` (`infra/github/ruleset-main.json`, requiere plan de GitHub).
- **Yesika:** con la épica de UX en manos de Herwin, su carga actual es 24803289; queda capacidad
  libre por asignar.

## 4. Limpieza hecha el 2026-10-23

Cerrados con comentario en Meegle: cinco tickets de ejemplo de la plantilla de Meegle, un duplicado
(24801945 → 24828507) y siete superados o ya construidos (24789643, 24789642, 24789645, 24789641,
24789639, 24789485, 24823777), además de 24829670. Tres épicas renombradas al formato
`Épica — <tema>` y ocho tickets sueltos enlazados a su épica.
