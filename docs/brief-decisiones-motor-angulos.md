# Brief de decisiones — Motor de Ángulos (por partes atómicas)

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

**Fecha:** 2026-08-10 · **Decisión rectora:** `docs/adr-32-motor-angulos-creativo.md`.
**Evidencia:** `docs/comparativa-apis-creativo-motor-angulos.md`, `docs/ingenieria-reversa-otimify.md`.

Cada decisión es **atómica** (se resuelve sola), trae una **recomendación por defecto** (para aprobar o ajustar de a una) y marca **reversibilidad + de qué depende**. 🚪 = puerta de una sola dirección.

## Ruta recomendada (los defaults, de un vistazo)

| # | Decisión | Default recomendado | Tipo |
|---|---|---|---|
| **D1** | ¿Construir la pata de creativo? | Sí, pero como wedge de insight — no ahora | 🚪 Gate |
| **D2** | ¿Qué construimos? | **Motor de Ángulos** (insight→brief), no un generador | 🚪 Gate |
| **D3** | ¿Cuándo? | Fase 5, tras el plano earned media vivo | 🚪 Gate |
| **D4** | ¿Generación build vs buy? | Buy/orquestar. Nunca build | Barato revertir |
| **D5** | Agregador base | fal.ai primario + Replicate espejo | Medio |
| **D6** | Alcance de adaptadores en MVP | Solo agregador; dedicados después | Barato |
| **D7** | Puntos de HITL | Dos: selección de ángulo + aprobación de creativo | Barato |
| **D8** | Modelo de presupuesto | Cap duro por cuenta + tabla de precios versionada | Medio |
| **D9** | ¿Qué capa primero? | Imagen de producto | Barato |
| **D10** | ¿Cuántos modelos en MVP? | 1 primario + 1 fallback por capa | Barato |
| **D11** | Loop de aprendizaje | v2, no MVP | Barato |
| **D12** | Data residency (proveedores chinos) | Flag desde el día 1 | Barato |
| **D13** | ¿Integrar ad-creative-insight? | No (es competencia) | Barato |
| **D14** | Licencias/consentimiento | ADR antes de tocar FLUX-dev / avatares | Barato |
| **D15** | Pricing/margen al cliente | Markup por pieza + cap por tier | Reversible |
| **D16** | Kill criterion | Definirlo ahora, antes de escribir código | — |

Aprobar toda la columna de defaults da un plan coherente. Abajo, cada átomo.

---

## Bloque A — Estratégicas (las 3 puertas)

**D1 — ¿Entrar a creativo?**
Pregunta: ¿Qualify agrega generación/asistencia de contenido, o se queda en listening + activación?
Opciones: (a) Sí ahora · (b) **Sí pero como wedge de insight, más adelante** · (c) No.
Recomendación: **(b)**. El hueco es real y el mercado crece (~26% CAGR), pero entrar como "otro generador" te vuelve un competidor sin foso de HeyGen/Creatify.
Reversibilidad: es un gate; decidir "no" ahora no cierra nada. Desbloquea: todo lo demás.

**D2 — ¿Qué construimos exactamente?** *(la más importante)*
Opciones: (a) Generador · (b) **Motor de Ángulos** · (c) Marketplace de diseñadores.
Recomendación: **(b)**. El generador es commodity (<$5/pieza). El marketplace recae en el modelo servicio-agencia con cuello de botella humano (el error de Otimify). El Motor de Ángulos es lo único anclado en *tus datos earned media* = tu foso.
Reversibilidad: puerta de una sola dirección — define la identidad del producto. Depende de: D1.

**D3 — ¿Cuándo?**
Opciones: (a) Ahora · (b) **Fase 5, tras el pipeline earned media**.
Recomendación: **(b)**. El motor no puede existir sin `search.content_index`/`signals` vivos (Parte 3 sin arrancar). Sin esos datos, sería un wrapper. Es dependencia dura.

---

## Bloque B — Arquitectura (cómo se integra)

**D4 — Build vs buy la generación.** Default: **buy/orquestar**. Confirmación del principio "buy, don't build". Barato.

**D5 — Agregador base.** Opciones: fal · Replicate · **ambos**. Default: **fal primario + Replicate espejo obligatorio**. fal factura por-output (presupuesto predecible); Replicate da redundancia y la vía a modelos fine-tuned propios. Medio.

**D6 — Alcance de adaptadores en el MVP.** Opciones: (a) **Solo modelos en el agregador** · (b) + adaptadores dedicados desde el día 1. Default: **(a)**. Los dedicados multiplican superficie de credenciales; se añaden cuando una cuenta los justifique. Barato.

**D7 — Puntos de HITL (el marketer).** Default: **dos** — selección de ángulo + aprobación de creativo antes de publicar. Nunca autónomo. Barato.

**D8 — Modelo de presupuesto.** Default: **cap duro mensual por cuenta + tabla de precios versionada/cacheada** (nunca literales; los precios de agregador fluctúan 2–4x). Medio (toca `billing.usage_events`).

---

## Bloque C — Alcance del MVP

**D9 — ¿Qué capa primero?** Default: **imagen de producto** (más barata, más rápida de validar). Barato.

**D10 — ¿Cuántos modelos en el MVP?** Default: **1 primario + 1 fallback por capa** (imagen: FLUX.2 pro → Seedream). Barato.

**D11 — Loop de aprendizaje.** Default: **v2**. Necesita métricas de owned media fluyendo; no bloquear el MVP con él. Barato.

---

## Bloque D — Riesgo / gobernanza (baratas, pero explícitas)

**D12 — Data residency.** Default: **flag `data_residency_restricted` por cuenta desde el día 1** (Kling/Seedance/Hailuo son chinos). Barato ahora, caro de retrofittear.

**D13 — ¿Integrar Omneky/Pencil/AdCreative?** Default: **No**. Su scoring de "qué convierte" *es* tu diferenciador. Solo como benchmark de research.

**D14 — Licencias/consentimiento.** Default: **ADR antes de FLUX.2-dev self-host (licencia BFL; solo Klein-4B Apache limpio) o clonado de avatares (consentimiento + App Review)**.

---

## Bloque E — Negocio / validación

**D15 — Pricing y margen.** Default: **markup por pieza + cap por tier**. Coste $0.03–0.24/img y $0.37–6/video; precio al cliente $0.25–0.50/img y $3–8/video deja margen bruto 50–90%. Reversible.

**D16 — Kill criterion** *(decidir ahora)*. Propuesta: **si tras N campañas los ángulos por evidencia no superan a los briefs manuales del marketer, el wedge no tiene foso — se apaga.** Sin esta métrica de entrada, el proyecto se vuelve irrefutable.

---

**Cómo usar esto:** D1→D2→D3 son las tres puertas; hasta cerrar D2 lo demás es prematuro. D4–D16 se deciden de a una y casi todas son reversibles. Para arrancar el MVP alcanza con D1, D2, D3, D5, D9 y D16.
