# Inventario del parking lot — extracción cruzada (features ↔ research ↔ nicho ↔ inbound/outbound)

**Autor:** `gtm-specialist` · **Fecha:** 2026-07-30
**Naturaleza:** **extracción y tabulación de docs existentes. NO es investigación nueva ni evaluación.** Insumo para el documento que ensambla `team-lead`.
**Fuentes:** `docs/backlog-features-gtm.md` (parking lot P3-0→P5-2) · `docs/backlog-crm-workflows.md` §5.4 · `packages/models/NOTES_research_parking_lot.md`

> **Por qué existe este fichero pese a que el lead dijo que no hacía falta disco.** La primera entrega se emitió como texto plano y **no llegó** — el texto plano de un agente no es visible para sus compañeros. Persistirlo es más barato que regenerarlo. Regla de `durable-findings`: lo que solo existe en una ventana de contexto ya está perdido.

---

## 1. `docs/backlog-features-gtm.md` — Parking lot (P3-0 → P5-2)

| ID | Descripción (1 línea) | Fase | Validación de mercado citada (textual) | In/Out |
|---|---|---|---|---|
| **P3-0** | Primitiva de clasificación zero-shot de texto (topic/intent/stance) + extensión del golden-set | 3, **«shippable como spike YA»** (no depende de Parte 3) | `NOTES_pain_signal_feasibility.md` §1: *«7/10 dolores resueltos por esta única primitiva»*; §5: *«coste incremental <5% del coste por video»* | **Inbound** |
| **P3-1** | Librería de detectores de señales tipados con provenance (anti-firehose) | 3 | *«la queja #1 de Trigify es "50 alertas/día, 5 accionables"»* · Contradicción #7: *«nadie lo hace en social audiovisual»* | **Inbound** |
| **P3-2** | Señal de comentaristas/audiencia como eje mapeable (engagement capture) | 3 | `research-features-gtm.md` L45 *(nadie usa la señal de comentarios)* · `ingenieria-inversa-stack-gtm.md` L77: *«engagement capture = mina de oro de Trigify»* | **Inbound** |
| **P4-1** | Lookalike de creators sobre embeddings de contenido multimodal completo | 4 | L43: *«Modash no transcribe ni usa comentarios»* · L35 redefinición del moat. **Challenged & survived** (datasci) con 4 AC obligatorias | **Inbound** |
| **P4-2** | Comentaristas como eje de similitud del lookalike («el eje que nadie usa») | 4 | L53: *«comentaristas como eje de similitud — nadie lo usa»*. **Challenged & survived** con 4 precondiciones; **dura/bloqueante sobre P3-2** | **Inbound** |
| **P4-3** | **[HIPÓTESIS]** Validación empírica del moat «español-first» | 4 (o spike antes) | L49: *«sin evidencia pública; pendiente datasci»* · L55: *«refuerzo secundario sin probar»*. **Explícitamente no-feature: tarea de research** | Transversal |
| **P4-4** | Waterfall de contacto de creator (pay-per-valid-data) | 4 | L75 (waterfall multi-región) · L79: patrón BetterContact vs anti-patrón Clay | **Outbound** |
| **P5-1** | Modelo de créditos `billing.usage_events` (cobrar por dato válido) | 5 | L67: *«Clay cobra por intento fallido, $3.000 quemados»* — queja #1 de Clay | Monetización |
| **P5-2** | Integración de outreach (buy, no build) | 5 | §Área 3b L100-108; caps HeyReach 20-25 conex/día; Smartlead Pro $94; Instantly v1 deprecada | **Outbound** |

## 2. `docs/backlog-crm-workflows.md` §5.4

| Ítem | Fase / estado | Por qué no ahora (textual, abreviado) | In/Out |
|---|---|---|---|
| **UI de asignación multi-agente** | **Sin fase** — *«sin fase — cliente uno»* | *«Específico de cliente uno → diferido por decisión 3»*. Proceso definido §4.4; `assigned_agent_id` nace en C-08; **solo la UI se aparca** | **Outbound** |
| **Canal WhatsApp** | Bloqueado por **B0-5** | *«Probablemente el canal del cliente uno»* — gate de verificación de entidad y número | **Outbound** |
| **Publicación programada en TikTok** | **Bloqueado, sin fecha** | *«la cuenta entera debe estar en privado al publicar, regardless of account ownership»*. ADR 23(c): **ni comprar ni construir** | **Outbound** |
| **Publicidad pagada / Marketing API** | Fase 5, **sin investigar** | *«Cero líneas sobre Marketing API en todo el repo»* → **candidato a /team-research, no de código** | **Outbound** |
| **Respuestas autónomas (sin humano)** | **Fuera, no es cuestión de fase** | *«1 de cada 3 mal en medio propio. Requiere evidencia nueva, no una fase nueva»* | **Outbound** |
| **Sindicación a portales** (Gallito, MercadoLibre) | Sin fase, superficie distinta | *«Es la queja real del cliente uno»* pero sin relación con APIs de Meta | **Outbound** |
| **Bandeja unificada cross-canal** | Fase 6 | C-08 cubre Instagram, no «todos los canales» | **Outbound** |
| **Listening de competidores, discovery, lookalike** | Fases 1(P2/P3)–4 | *«Estructuralmente inalcanzable por OAuth»* — exige scraping. *«Cualquier material de producto que insinúe monitorización de competidores desde cuentas conectadas es falso»* | **Inbound** |
| **Señales tipadas + zero-shot NLI** | Fase 3 (P3-0/P3-1) | *«Hueco real contra la cascada comprometida»*, pero C-09/C-10 no lo necesitan | **Inbound** |
| **Billing por créditos** | Fase 5 | *«No copiar el precio por contacto de ManyChat, copiar su cascada»* | Monetización |
| **Insights / `ingestion.owned_metrics`** | Frontera Fase 1/2 | *«Duro-bloqueado por la Parte 3»* | **Outbound** (medio propio) |

## 3. `packages/models/NOTES_research_parking_lot.md`

Un solo candidato. Fichero datasci-owned, con advertencia explícita: *«Do not treat an entry's presence here as a commitment.»*

| Ítem | Fase | Veredicto textual | In/Out |
|---|---|---|---|
| **Dynamic-budget superpixel active learning for semantic segmentation** (Wang & Stavness, *Frontiers in AI* 7:1498956, DOI 10.3389/frai.2024.1498956) | **Sin dueño de fase** | *«Parked — no current phase owner; revisit only if Fase 3 logo/product detection is scoped as a trained segmenter instead of zero-shot VLM prompting.»* · *«Qualify does not train, and has no scoped plan to train, any segmentation model in Fase 1-3»* | Inbound (visión) |

## 4. Conexiones con la investigación de esta sesión

Solo lo que saltó a la vista durante la tabulación — **no se rebuscó**.

| Ítem | Conexión |
|---|---|
| **UI de asignación multi-agente** | **La más directa.** `oferta-mercado-agencia-gestionada.md` §4.3: el **panel multicliente** es una de las **dos cosas de las que depende el 100 % del apalancamiento**. Aparcado por «específico de cliente uno» — pero bajo el modelo agencia sirve al **fundador**, no a un cliente |
| **P3-0 / P3-1** | `oferta-mercado-marca-regulada.md` §2.6: benchmark revisado por pares — **F1 0,93 en el caso fácil, 28,57 % de fallo en el ambiguo**. Primera medición externa de precisión aplicable a esta primitiva |
| **Respuestas autónomas** | Mismo §2.6: el régimen de precisión de ADR 21 (*«65 % = 1 de cada 3 mal»*) conecta con el 28,57 % del benchmark — **refuerza el «fuera permanentemente»** |
| **P4-3 moat «español-first»** | `agencia-gestionada.md` §1.2 + las tres anotaciones geográficas + `marca-regulada.md` §2.6: **los cinco vendors de compliance son anglófonos** y no verifiqué su calidad en español. Evidencia circunstancial *a favor*, aún sin medir |
| **Listening de competidores / lookalike** | `inmobiliario.md` §4 (nadie ofrece listening de contenido primario a inmobiliario) **vs** `marca-regulada.md` §2.1/§2.5 (**sí lo ofrecen**, dos veces falsado). **El mismo ítem tiene respuesta opuesta según el nicho** |
| **Sindicación a portales** | `inmobiliario.md` §1.5: los portales son **el gasto obligatorio** del nicho (InfoCasas US$92-196/mes); §1.4(a): **no hay MLS en LATAM**, los portales ocupan ese hueco |
| **P4-4 waterfall** · **P5-2 outreach** | Anotación geográfica en `research-features-gtm.md`: **cobertura de datos B2B en LATAM no medida** y **legalidad del email frío en LATAM no analizada** (Uruguay con protección de datos de grado GDPR) |
| **Insights / `owned_metrics`** | `agencia-gestionada.md` §4.2: sin ClickHouse **el reporting al cliente sigue siendo manual** — carga directa sobre las horas por cliente de §2.3 |
| **Publicidad pagada / Marketing API** | `agencia-gestionada.md` §1.2: *«si incluye pauta publicitaria»* es uno de los factores citados que **suben la tarifa** por cliente |

## 5. Dos observaciones de la extracción (sin evaluar)

1. **P4-3 y «Publicidad pagada» no son features, son tareas de investigación**, y están así etiquetadas en origen.
2. **P3-0, P4-1 y P4-2 llevan marcas de challenge previo** (`Challenged & survived`, con AC obligatorias de datasci). Conviene no perder esas condiciones al reagrupar los ítems.
