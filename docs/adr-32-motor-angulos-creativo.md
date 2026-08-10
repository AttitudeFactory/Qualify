# ADR 32 — Motor de Ángulos: la pata de creativo como *wedge de insight*, no como generador

**Estado:** `[APROBADO]` — **firmado por el fundador 2026-08-10 (en chat).** Fila foldeada a `docs/arquitectura.md` §6. Backlog seedeado en Linear (equipo `Qualify-market`).
**Fecha:** 2026-08-10 · **Fase:** 5 (GTM activation) · **Depende de:** Fase 1 Parte 3 (plano analítico earned media) + capa de señales (Fase 3).
**Documentos hermanos:** `docs/comparativa-apis-creativo-motor-angulos.md` (evidencia de vendors/precios), `docs/brief-decisiones-motor-angulos.md` (las 16 decisiones atómicas), `docs/ingenieria-reversa-otimify.md` (el contraejemplo que motiva la disciplina).

---

## Contexto

Se identificó una pata débil de Qualify: **no hay capa de creación/asistencia de contenido** para redes sociales (los "ángulos" de un producto/servicio, el creativo de campaña). El mercado de creativo con IA crece fuerte (~26% CAGR; casi 90% de anunciantes usan o planean usar IA generativa para video). La hipótesis inicial —"es difícil de reemplazar con Stable Diffusion"— resultó **directionalmente correcta pero mal enunciada**: la generación de píxeles ya es commodity (<$5/pieza); lo difícil y valioso es **saber qué ángulo/gancho convierte ahora en una categoría**, que es precisamente lo que exige leer el mercado real.

El riesgo de entrar mal está documentado en el teardown de **Otimify** (`docs/ingenieria-reversa-otimify.md`): revender una capa commodity con buen envoltorio es un negocio frágil (arbitraje de ignorancia, sin foso). Construir un generador genérico repetiría ese error con otra cara.

## Decisión

Se aprueba construir la pata de creativo **como un *wedge de insight*** llamado **Motor de Ángulos**, con las siguientes resoluciones atómicas (numeradas D1–D16 en el brief):

1. **Qué construimos (D2, puerta de una sola dirección):** un **Motor de Ángulos** = insight → brief → **orquestación** de generación. **NO** un generador propio (commodity) **NI** un marketplace de diseñadores (recae en el modelo servicio-agencia con cuello de botella humano — el error de Otimify).
2. **Generación = buy, nunca build (D4):** la generación de imagen/video/UGC se orquesta vía APIs de terceros. El diferenciador es el **brief fundamentado en datos earned media propios**, no el generador.
3. **Cuándo (D3):** Fase 5. Es dependencia dura, no preferencia — el motor no puede existir sin `search.content_index`/`signals` vivos (Parte 3 no arrancada).
4. **Arquitectura de orquestación (D5, D6):** **fal.ai como agregador primario + Replicate como espejo obligatorio**. El motor habla un `GenerationProvider` protocol (mismo seam que el `Provider` de `packages/models` y el `VideoFetcher` del scraper); fal/Replicate son dos implementaciones. Modelos fuera de agregador (HeyGen, Runway, GPT-Image-2, Captions/Mirage) → adaptador dedicado, habilitado solo si la cuenta lo justifica.
5. **HITL = el marketer que administra la cuenta (D7):** dos puntos de aprobación humana — (a) selección de ángulo, (b) aprobación de creativo antes de publicar. **Nunca autónomo** (coherente con ADR 21 Parte 4-B: draft + human approval).
6. **Presupuesto por cuenta (D8):** cap duro mensual configurable desde el admin + **tabla de precios versionada y cacheada** (nunca literales en código; los precios de agregador fluctúan 2–4x). Gasto contabilizado en `billing.usage_events`. Credenciales por adaptador bajo el patrón `qualify_credential`/`oauth_credentials.ciphertext` (nunca en claro).
7. **Alcance del MVP (D9, D10, D11):** **imagen de producto primero** (más barata, más rápida de validar), **1 primario + 1 fallback por capa** (imagen: FLUX.2 [pro] → Seedream 4.0), loop de aprendizaje diferido a v2.
8. **Gobernanza (D12, D13, D14):** flag `data_residency_restricted` por cuenta desde el día 1 (Kling/Seedance/Hailuo son chinos); **no integrar** la capa ad-creative-insight (Omneky/Pencil/AdCreative) — su scoring de "qué convierte" solapa con el diferenciador propio, integrarla sería subcontratar el foso a un competidor; ADR/licencia previa antes de tocar FLUX.2-dev self-host (licencia BFL) o clonado de avatares (consentimiento + App Review).
9. **Kill criterion instrumentado desde el día 1 (D16):** si tras N campañas los ángulos generados-por-evidencia no superan en performance a los briefs manuales del marketer, el wedge no tiene foso y se apaga. Sin esta métrica el proyecto se vuelve irrefutable.

## Alternativas rechazadas

| Alternativa | Por qué se rechaza |
|---|---|
| Construir un generador de creativo propio (modelos, pipeline de render) | Commodity (<$5/pieza, docenas de tools); sin foso; compite de frente con HeyGen/Creatify. |
| Marketplace/red de diseñadores como producto propio | Modelo servicio-agencia: cuello de botella humano, márgenes de servicio, no escala. Es el patrón de Otimify que este ADR evita. Se admite solo como partnership/referral premium, nunca como core. |
| Un solo agregador (solo fal) | Punto único de fallo; sin espejo no hay cadena de fallback real ni ruta a modelos fine-tuned propios. |
| Integrar Omneky/Pencil/AdCreative como motor | Su capa de insight ES el diferenciador de Qualify; integrarla ata el foso a un competidor. |
| Generación autónoma sin HITL | Precisión insuficiente para publicar en nombre de una marca; incoherente con ADR 21 (asistido, no autónomo). |
| Entrar ahora (antes de Parte 3) | Sin datos earned media el "motor de ángulos" sería un wrapper de una API — exactamente lo que este ADR prohíbe. |

## Consecuencias

- **Positivas:** el creativo pasa de pata débil a extensión natural del listening ("read the content, not the profile" aplicado a creativo); el valor se acumula en datos propios + loop de aprendizaje (compone), no en horas humanas; márgenes brutos estimados 50–90% por pieza; arquitectura sin lock-in de proveedor (opuesto a Otimify↔GHL).
- **Costos/deuda:** superficie de adaptadores y credenciales por proveedor; dependencia de agregadores cuyos precios/versiones churnean (mitigado con tabla de precios versionada + tests de contrato por modelo); un modelo de datos nuevo con provenance (`angles`/`briefs`/`creative_assets`/`generation_jobs`).
- **Reversibilidad:** D2/D3 son puertas de una sola dirección (definen identidad del producto y su timing). D4–D15 son mayormente reversibles: cambiar agregador, ampliar capas, o añadir modelos son cambios acotados por el seam de adaptador.

## Gates y condiciones

1. **Gate de datos:** no se escribe código del wedge de insight (Epic B del backlog) hasta que `search.content_index` + comentarios + `signals` existan (Parte 3 + Fase 3). La fundación de orquestación (Epic A) y el MVP de imagen (Epic C) *pueden* prototiparse antes contra fixtures, pero sin el insight es solo un generador — no shippear como producto hasta cerrar el gate de datos.
2. **Gate de firma:** este ADR entra en vigor al firmarse y foldearse en `arquitectura.md` §6 (fila ADR 32 + esta narrativa).
3. **Gate de licencia:** ADR específica antes de FLUX.2-dev self-host o clonado de avatares.

---

**Fila para `arquitectura.md` §6 (al firmar):**

| ADR | Decisión | Alternativa | Racional |
|---|---|---|---|
| 32 | **[APROBADO — firmado por el fundador 2026-08-10]** Pata de creativo = **Motor de Ángulos** (insight→brief→orquestación), Fase 5. Generación = buy vía fal.ai (primario) + Replicate (espejo) tras un `GenerationProvider` seam; HITL = marketer con doble aprobación; presupuesto/cadenas de fallback configurables por cuenta; imagen primero; NO integrar ad-creative-insight; kill criterion instrumentado | Generador propio / marketplace de diseñadores / un solo agregador / generación autónoma / entrar antes de Parte 3 | El diferenciador es el brief fundamentado en earned media propio (que nadie vende armado), no la generación (commodity). Evita el modelo frágil de reventa-de-commodity del teardown de Otimify (ADR contexto). Sin lock-in de proveedor; el valor compone en datos + loop, no en horas humanas |
