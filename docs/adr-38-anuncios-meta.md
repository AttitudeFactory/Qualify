# ADR 38 — Anuncios de Meta desde Qualify: se levanta el «orgánico primero» y se construye sobre la Marketing API

**Estado:** `[APROBADO]`, decisiones del fundador del 2026-10-21 (D1–D6 de `docs/epica-anuncios-meta.md` §6).
**Fecha:** 2026-10-21 · **Épica:** Meegle m-24828970 · **Ticket:** m-24789462 (ADS-01)
**Modifica:** ADR 21. La publicidad pagada deja de ser «ítem futuro fuera de alcance» (`arquitectura.md` §6, nota (2) de soporte a ADR 21).
**Toca:** la tensión build-vs-agregador del 2026-07-30 (Zernio), solo para la superficie de anuncios. ADR 29 aplica tal cual a la secuencia.
**Investigación:** `docs/epica-anuncios-meta.md`.

---

## Contexto

ADR 21 decidió el 2026-07-24 publicar orgánico primero. Dejó la publicidad pagada (`ads_management`, método de pago, Business Manager) fuera de alcance, «con su propia pasada de investigación y ADR». Esa investigación se hizo el 2026-10-21 contra la documentación de Meta (Marketing API v26.0), y el fundador pidió la épica: las publicaciones que genera Qualify ya son aceptables y ahora hay que poder convertirlas en anuncios con el botón «Más información», configurados desde Qualify.

Tres hechos de la investigación sostienen esta decisión:

1. Una publicación de Instagram ya publicada se convierte en anuncio (`source_instagram_media_id` + `instagram_user_id`) y admite `call_to_action` `LEARN_MORE` con enlace. El MVP no pide crear creativos nuevos.
2. El gasto se cobra en la cuenta publicitaria del cliente con su método de pago. Qualify no toca tarjetas, solo lee el estado de la cuenta.
3. Sin acceso avanzado a `ads_management`/`ads_read`, la app solo maneja cuentas publicitarias de quien tiene rol en la app. Por ADR 29 eso incluye a los clientes que administra el fundador. La verificación del negocio está hecha (2026-10-05) y la app está en modo Live (2026-10-21).

## Decisión

| # | Pregunta | Decisión |
|---|---|---|
| **D1** | ¿Se levanta el «orgánico primero» para anuncios? | **Sí.** La publicidad pagada entra en alcance como la épica m-24828970. ADR 21 sigue vigente para todo lo demás. |
| **D2** | ¿Marketing API propia o agregador (Zernio vende anuncios en 6 redes)? | **Construir el MVP sobre la Marketing API.** El anuncio sale de nuestras piezas y desemboca en nuestros Chats, y un agregador no ahorra el App Review del cliente. Comprar no se descarta para más adelante: si el costo de mantener la integración supera al de un agregador, se reabre con esa medición. |
| **D3** | ¿Con quién se empieza? | **Con los clientes que administra el fundador** (Bianki, Polette, la inmobiliaria), por acceso estándar (ADR 29). En paralelo va el App Review de `ads_management`/`ads_read`/`pages_manage_ads` (m-24828986, épica de Meta App Review), que es lo que abre el cliente dos. |
| **D4** | ¿Primer objetivo del anuncio? | **El MVP construye «Visitas a tu web» con «Más información»** (ADS-06), y el siguiente es clic a WhatsApp / Instagram Direct (ADS-10). **El objetivo que se le propone a cada cliente depende de su nicho**: comida y viajes venden por mensaje (WhatsApp), la inmobiliaria por contacto (WhatsApp o formulario) y quien vende en su web por visitas. El asistente sugiere el objetivo según el rubro de la marca y el cliente puede cambiarlo. Mientras solo exista el objetivo del MVP, se ofrece ese. |
| **D5** | ¿«Vivienda» encendida por defecto para la inmobiliaria? | **Apagada.** El cliente puede encenderla. Única excepción, que no es opción de Qualify sino regla de Meta: si la segmentación llega a EE. UU., Canadá o países de Europa donde Meta exige la categoría, Qualify la enciende y lo dice. |
| **D6** | ¿Qualify cobra por anuncio gestionado? | **No en el MVP: va incluido.** El modelo de cobro (créditos o plan) se decide con uso medido, dentro de la épica de Suscripciones (m-24828931). Desde el MVP se registra cada promoción con su gasto para tener esa medición. |

## Consecuencias

- `arquitectura.md` §6: la nota (2) de soporte a ADR 21 deja de llamar «ítem futuro» a la publicidad pagada y apunta aquí.
- La épica sigue el orden de `docs/epica-anuncios-meta.md` §4: E0 (ADS-00 prueba en vivo) → E1 MVP «Promocionar» → E2 clic a mensajes → E3 leads → E4 anuncio nuevo desde una pieza → E5 públicos y Advantage+.
- ADS-06 lleva la sugerencia de objetivo por rubro como requisito de diseño (D4). Mientras E2 no exista, solo se muestra «Visitas a tu web».
- ADS-07 deja «Es un anuncio de vivienda» apagado por defecto y solo lo fuerza cuando Meta lo exige (D5).
- ADS-04 guarda el gasto por promoción, que es la medición que necesita D6.
- Ninguna llamada que gasta dinero se hace sin consentimiento explícito del cliente (ADS-16). Esto no se decide aquí: es condición de las Self-Serve Ad Terms de Meta.

## Qué reabriría esta ADR

- Que el App Review de los permisos de anuncios se rechace sin un camino razonable: D2 se reabre a favor de un agregador que ya tenga la aprobación.
- Que mantener la integración (versiones de la Marketing API, que caducan antes que las de Graph) cueste más que la tarifa de un agregador por cuenta conectada.
