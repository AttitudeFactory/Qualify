# Comparativa de APIs de creativo para Qualify

*Motor de Contenido/Ángulos — Fase 5. Orquestación de APIs de terceros detrás de un agregador + adaptadores, con cadenas de fallback configurables por presupuesto de cuenta. Datos a agosto 2026.*

> **Convención de etiquetas:** (DATO) = verificado en fuente; (inferencia) = estimación o dato no confirmado. Precios en USD. Cuando un precio depende del proveedor upstream (agregador), se marca porque **fluctúa** — el motor debe cachear una tabla de precios versionada, nunca hardcodear.

---

## 1. Veredicto de columna vertebral: fal.ai como primario, Replicate como respaldo estructural

**Decisión: fal.ai es el agregador base (primario); Replicate es el segundo agregador obligatorio (no opcional).** Razón:

- **fal.ai encaja mejor con el motor de fallback por presupuesto** (DATO): factura *pay-only-for-successful-outputs* y en su mayoría **por output** (por imagen, por segundo de video, por video), lo que hace el coste por-pieza **predecible y comparable** entre modelos — exactamente lo que necesita un cap de presupuesto por cuenta. Replicate factura en dos tracks y su modo dominante long-tail es **hardware-por-segundo**, que acopla el coste a la latencia/cold-start del modelo y complica el presupuesto por-ad.
- **Catálogo de video más fresco y amplio en fal** (DATO): Kling, Veo, Wan, Hailuo, Seedance, MiniMax, Runway conviven bajo una sola API con queue + webhooks + logs por request — el seam ideal para el HITL asíncrono (generar → encolar → notificar al marketer → aprobar → publicar).
- **Por qué Replicate igual es obligatorio** (no solo "nice to have"): (a) redundancia real de proveedor para la cadena de fallback cuando un modelo cae o sube de precio en fal; (b) es el **único** que permite *push* de modelos propios fine-tuned vía Cog (DATO) — la vía futura para un modelo de marca dedicado por cliente; (c) respaldo de Cloudflare tras la adquisición de fines de 2025 (DATO).

**Regla de arquitectura derivada:** el motor NO habla "fal" ni "Replicate" — habla un **adaptador por proveedor** con una interfaz común (`generate(task, params, budget_ctx) -> job`). fal y Replicate son dos implementaciones de ese adaptador; los modelos que NO están en ningún agregador (Runway, GPT-Image-2, OpenAI Sora, HeyGen, Captions/Mirage) exigen **adaptador dedicado propio** con su key y billing separados. Esto es el punto de fricción #1 de integración (ver §6).

---

## 2. Tablas comparativas por capa (ordenadas por relación precio/beneficio, mejor arriba)

### 2.1 Capa IMAGEN DE PRODUCTO (text-to-image / image-to-image / product-image)

| # | Servicio | Precio (unidad exacta) | Límites clave | Consistencia de producto/marca | Agregador | Rol fallback |
|---|----------|------------------------|---------------|-------------------------------|-----------|--------------|
| 1 | **FLUX.2 [pro]** (Black Forest Labs) | $0.03/img (Pro); Dev ~$0.025/img; escala con megapíxeles. Klein 4B $0.014 (DATO) | Coste sube con MP; Flex/Max ($0.05–0.07) para más fidelidad (DATO) | Fuerte SKU/marca; **LoRA fine-tuning** para estilo de marca fijo (DATO) | **ambos** | **standard/anchor** |
| 2 | **Seedream 4.0** (ByteDance) | $0.03/img (v4 en fal); 4.5 $0.04/img (DATO) | Gen+edit unificado; multi-ref; 2K–4K en tiers nuevos (DATO/inferencia) | Fuerte, cerca de Nano Banana Pro a fracción del precio (inferencia) | **ambos** + ModelArk directo | **budget** |
| 3 | **Ideogram 3.0** (Ideogram AI) | Turbo $0.03 / Default $0.06 / Quality $0.09 por img; con referencia $0.10/0.15/0.20 (DATO) | Flat por imagen; ~1024–1536; ref-mode es premium (DATO) | **Mejor texto-en-imagen** (90–95% vs Midjourney 30–40%): titulares/CTA/packaging (DATO) | **ambos** | **standard** (especialista texto) |
| 4 | **Recraft V3** (Recraft) | $0.04/img raster; $0.08/img vector SVG (DATO) | Params `rgb_colors`/`background_rgb_color`; brand-style reutilizable (DATO) | **Estilo de marca** (paleta + perfil reutilizable) + **vector/SVG** único aquí (DATO) | **solo fal** | **standard** (config de marca) |
| 5 | **FLUX.1 Kontext** (BFL) | 1 crédito = $0.01; ~$0.03–0.04/edición Pro (inferencia) | Edición iterativa barata; ~1024px; superado por FLUX.2 edit (DATO) | Preserva identidad de producto entre ediciones sucesivas (DATO) | **ambos** | **budget** (variaciones de un base aprobado) |
| 6 | **Nano Banana Pro** (Gemini 3 Pro Image) | ~$0.039/img @1K, **$0.134/img @1–2K, $0.24/img @4K** (token-based); Batch = mitad (DATO) | 4K nativo; hasta **14 imágenes de referencia**, 5 sujetos; cuotas RPM/TPM Gemini (DATO) | **Mejor de su clase**: 14 refs + anclaje de identidad; líder en fidelidad SKU/marca (DATO) | **solo fal** (+ /edit); no en Replicate | **primary** (calidad tope) |
| 7 | **GPT-Image-2** (OpenAI) | Token-based; per-img: Low ~$0.005, Medium ~$0.04, High ~$0.16–0.21 (inferencia) | Calidad low/med/high; hasta ~1024×1536; **sin 4K** (DATO) | Buena edición single-product/inpainting; un escalón bajo Nano Banana (inferencia) | **ninguno** (adaptador propio) | standard |
| 8 | **FLUX.2 [dev]/[klein]** (self-host) | Pesos gratis; ~$0.002–0.02/img en RunPod/Modal (inferencia) | GPU ops propias; [dev] licencia comercial de pago; Klein-4B Apache-2.0 (DATO) | Misma familia; LoRA por cliente = palanca más fuerte de marca (DATO) | ninguno (self-host) | **budget a volumen alto** |

**Lectura para Qualify:** el *anchor* racional del catálogo es **FLUX.2 [pro]** (barato, portátil en ambos agregadores, LoRA por marca). **Nano Banana Pro** entra como primario **solo cuando el cliente paga tier premium** o cuando la pieza exige fidelidad SKU extrema / 4K. **Ideogram** es el especialista obligado cuando el creativo lleva texto legible (headline/CTA/packaging). **Recraft** es la pieza para "respeta mi paleta y dame el logo en SVG".

---

### 2.2 Capa VIDEO BASE (text-to-video / image-to-video)

| # | Servicio | Precio (unidad exacta) | Límites clave | Consistencia de producto | Agregador | Rol fallback |
|---|----------|------------------------|---------------|--------------------------|-----------|--------------|
| 1 | **ByteDance Seedance** (1.0/1.5/2.0 Pro) | 1.5 Pro ~$0.0247/s; 1.0 Pro desde ~$0.010/s; 1080p/5s ~$0.74 en fal; 2.0 ~$0.09/s (DATO) | 480/720/1080p; 5s típico, 8–10s en 2.0; multi-shot en 2.0 (DATO) | Buena p/precio; I2V correcto, bajo Kling/Veo (inferencia) | **ambos** | **budget** (carril presupuesto) |
| 2 | **Kling 2.5 Turbo / 2.6 / 3.0** (Kuaishou) | 2.5 Turbo **$0.07/s en fal** (~$0.31/clip 5s); 3.0 ~$0.09–0.14/s (fluctúa) (DATO) | 5s/10s; hasta 1080p; **I2V líder** (start+end frame); 2.6 añade audio nativo (DATO) | **Mejor calidad/precio en I2V**: mantiene sujeto/producto desde frame inicial (inferencia) | **ambos** | **primary** (opción por defecto racional) |
| 3 | **MiniMax Hailuo 02 / 2.3** | $0.10 (512P/6s), $0.28 (768P/6s), $0.49 (1080P/6s); ~$0.045–0.08/s efectivo 768P (DATO) | 512/768/1080P; clips 6s/10s; I2V (DATO) | Buen movimiento/físico p/precio; bajo Kling en consistencia fina (inferencia) | **ambos** | **budget** (512P casi gratis para borradores) |
| 4 | **Luma Dream Machine Ray 2/3** (Luma AI, US) | Ray 3 ~$0.21/s ($12.60/60s); Ray 2 Flash tier económico (DATO/inferencia) | 5s/9s; hasta 1080p (4K upscale Ray 3); **keyframes start/end** (DATO) | Keyframes fijan producto al inicio/fin del plano; **proveedor US** (gobernanza) (inferencia) | **ambos** | **standard** (marcas occidentales sensibles a data-residency) |
| 5 | **Runway Gen-4 / Turbo / 4.5** | Turbo **$0.05/s**; Gen-4 full $0.12/s; Gen-4.5 $0.25/s (DATO) | 5s/10s; hasta 1080p (4.5); I2V first/last frame; **control de cámara líder** (DATO/inferencia) | References para consistencia personaje/escena; dirección de plano precisa (inferencia) | **ninguno** (adaptador propio) | **standard** (rompe patrón agregador) |
| 6 | **Google Veo 3.1 / Fast / Lite** (DeepMind) | Gemini API: Std $0.40/s, Fast $0.15/s, Lite $0.05/s (con audio); **en fal ~$0.20/s sin audio**; Vertex $0.75/s (DATO) | Clips 4/6/8s; 720p/1080p/4K; 1080p exige 8s; extend hasta ~148s (DATO) | Alta fidelidad + **único con audio nativo sincronizado** (lipsync/SFX) en una pasada (inferencia) | **ambos** | **premium-only** (calidad tope, ~10x Kling) |
| 7 | **Pika 2.x** (Pika Labs) | Por créditos; ~$0.05–0.15/s equiv. (inferencia) | ~5–10s; 1080p; efectos (Pikaffects/Pikadditions) (inferencia) | Insertar objetos en escena útil; menos consistencia plano largo (inferencia) | ninguno (poco fiable) | budget (baja prioridad) |
| — | **OpenAI Sora 2 / Pro** | $0.10/s (Sora 2); Pro $0.30–0.70/s; Batch mitad (DATO) | **API cierra 24-sep-2026** (DATO) | Realista + audio, pero política de marcas restrictiva (inferencia) | ninguno | **DESCARTAR** — riesgo existencial de cierre |

**Lectura para Qualify:** **Kling** es el primario por defecto (mejor I2V a bajo coste = fidelidad de producto desde el pack shot). **Seedance/Hailuo** cubren el carril presupuesto. **Veo** solo en premium (su ventaja de audio nativo ahorra un paso de la cadena, pero cuesta ~10x). **Runway** entra cuando se necesita dirección de cámara, aceptando el coste de un adaptador dedicado. **Sora se descarta** para producción por su fecha de cierre.

---

### 2.3 Capa UGC-AVATAR (avatar-UGC / url-to-video / testimonial)

| # | Servicio | Precio (unidad exacta) | Límites clave | Consistencia | Agregador | Rol fallback |
|---|----------|------------------------|---------------|--------------|-----------|--------------|
| 1 | **Captions / Mirage** (Captions) | **$0.175/s** video (bloques de 6s); captions $0.15/min (DATO) | Facturación por segundo pública; 9:16; clips cortos (DATO) | UGC **generativo** muy realista; actor variable entre gen.; sin producto real (inferencia) | ninguno (adaptador propio) | **primary/budget** (API por-uso, ideal fallback) |
| 2 | **HeyGen** (HeyGen Inc.) | Pay-as-you-go desde $5; Avatar IV 20 créditos/min; Avatar III 1080p ~$1.00/min; crédito $0.50–0.99 (DATO) | Hasta **10 videos concurrentes**; 1080p sin sobrecosto; API v2 + webhooks + streaming (DATO) | **Avatares/voces clonables reutilizables** (mejor consistencia de vocero); no inserta SKU (inferencia) | ninguno (adaptador propio) | **primary** (API más madura del carril) |
| 3 | **Creatify** (Creatify AI) | Starter $39/mo (~$19 anual); Pro $99/mo; 5 créditos/15s → ad 30s ~$1.65–3.30 (DATO) | 1080p; batch mode; **API solo Enterprise** (negociado) (DATO) | **Mejor del carril en PRODUCTO**: scrapea URL Shopify/Amazon e inserta el SKU real (DATO/inferencia) | ninguno | **standard** (motor ecommerce) |
| 4 | **Topview AI** (TopView.ai) | Free (10 cr); Pro $16/mo; Business $40/mo (3000 cr, video máx 25s) (DATO) | Business máx 25s; **API solo Enterprise**; avatar full-body con producto; usa Sora 2 (DATO) | Fuerte en producto (URL/imagen-to-video, avatar cuerpo completo con SKU) (DATO/inferencia) | ninguno | **budget** (ecommerce barato) |
| 5 | **Synthesia** (Synthesia Ltd.) | Free 10min; Starter $29/mo; Creator $89/mo (incluye API, ~$2.97/min) (DATO) | 10–30 min/mes por plan; API buena desde Creator/Enterprise (DATO) | Excelente avatar/vocero custom multi-idioma (140+); **sin producto** (inferencia) | ninguno | **premium** (testimonial corporativo multi-idioma) |
| 6 | **Arcads AI** (Studio Arcads) | Starter $110/mo (10 vids); Pro ~$385–550/mo (incluye API) (DATO parcial) | **API solo tier Pro**, sin docs públicas ni pricing por-uso; +1000 actores (DATO) | Mejor **realismo humano UGC** percibido; consistencia de actor; producto vía b-roll (inferencia) | ninguno | **premium-only** (API cerrada, mal para budget-config) |
| 7 | **Revid AI** (Revid.ai) | Free + planes por créditos; cifras no confirmadas (inferencia) | Clips cortos; docs API modestas (inferencia) | Media-baja producto y actor; generalista (inferencia) | ninguno | budget (fallback multiuso) |
| — | **Pippit** (CapCut/ByteDance) | Free 150 cr/semana; Starter ~$24/mo (DATO) | **SIN API pública** → no orquestable (DATO) | Estética TikTok nativa; actor poco reutilizable (inferencia) | ninguno | **NO integrable** (solo referencia de estilo) |
| — | **Icon** (icon.com) | Plataforma $39+/mo; 6 UGC humanos por $1000 (DATO) | Híbrido humano+software; latencia de días; API opaca (inferencia) | Alta (personas reales) pero **no programática** (inferencia) | ninguno | fuera de rol (fuente de insight, no generación) |

**Lectura para Qualify:** el carril UGC-avatar es el **más difícil de orquestar** porque los especialistas más útiles para ecommerce (Creatify, Topview, Arcads) esconden su API tras Enterprise/Pro negociado — **malos ciudadanos para un pricing configurable por cuenta pequeña**. Los dos únicos con API por-uso limpia y pública son **HeyGen** (vocero clonable, madura) y **Captions/Mirage** (UGC generativo por segundo). Esos dos son la espina dorsal orquestable; Creatify entra como adaptador dedicado **solo para cuentas ecommerce que justifiquen el contrato Enterprise** (por su url-to-video con SKU real, que ningún modelo base ofrece).

---

### 2.4 Capa AD-CREATIVE-INSIGHT (creativo + scoring de conversión)

| # | Servicio | Precio (unidad exacta) | Límites clave | Consistencia | Agregador | Rol |
|---|----------|------------------------|---------------|--------------|-----------|-----|
| 1 | **Omneky** | Product Gen Pro $25/mo; Creative Gen Pro $79–99/mo; Ultra $199/mo (aprox) (inferencia) | **API + MCP server (jul 2026)**; ratios 1:1/4:5/9:16/16:9 (DATO) | Centrado en marca; Omnichannel Insights con performance real (inferencia) | ninguno | **premium-only** — pero **compite** con el motor de ángulos de Qualify |
| 2 | **Pencil (Pro)** (Brandtech) | Core $14/mo (50 gen); Growth $55/mo; Pro negociado (inferencia) | Orquesta modelos frontier gobernados; SOC2/IP indemnity (DATO) | Media Performance Score (CTR, validado con >$1B spend) (DATO) | ninguno | **competidor** de la visión Qualify, no pieza a integrar |
| 3 | **AdCreative.ai** | Startup $29/mo (10 cr) … Scale-Up $149/mo (100 cr, incluye API) (DATO) | **API solo tier $149/mo**; foco banner estático, video limitado (DATO) | Brand-kit fuerte para estáticos, no video generativo (inferencia) | ninguno | premium-only — su Conversion Score **compite** con el motor propio |

**Lectura para Qualify:** esta capa **no encaja como generador** en el motor. Su "capa de insight de qué convierte" (Conversion Score de AdCreative, Media Performance Score de Pencil, Omnichannel Insights de Omneky) **solapa con el propio motor de ángulos** que Qualify quiere construir — es competencia, no complemento. **Recomendación: no integrar ninguna en el motor de generación.** A lo sumo, tratarlas como fuente externa de *benchmark* de "qué creativo gana" en investigación de producto, nunca como dependencia productiva.

---

## 3. Cadenas de fallback recomendadas por tier de presupuesto

Cada cadena: **primario → fallback 1 → fallback 2**. Criterio de salto entre eslabones:
- **(F) Fallo/timeout** del proveedor (error API, cold-start excedido, output rechazado por el filtro de éxito).
- **(P) Presupuesto agotado** — el coste proyectado de la pieza supera el cap mensual restante de la cuenta → baja a un eslabón más barato.
- **(Q) Calidad insuficiente** — la pieza no pasa el umbral (score de calidad automático o rechazo del HITL) → sube o cambia de eslabón.

> Todas las cadenas asumen **fal.ai como transporte primario y Replicate como transporte espejo**; el "salto de agregador" (fal → Replicate para el mismo modelo) es el **primer** fallback ante (F), *antes* de cambiar de modelo.

### Tier ECONÓMICO (cuenta con cap bajo, borradores y volumen)

- **Imagen de producto:** `Seedream 4.0 ($0.03) → FLUX.1 Kontext ($0.03–0.04, edición) → FLUX.2 Dev ($0.025)`
  - Salto: (P) mantiene todo ≤$0.04/img; (F) espejo fal→Replicate; (Q) sube a FLUX.2 Pro.
- **Video base:** `Seedance 1.5 Pro ($0.0247/s) → MiniMax Hailuo 768P ($0.28/6s) → Kling 2.5 Turbo ($0.07/s)`
  - Salto: (P) empieza por lo más barato/segundo; (Q) escala a Kling (mejor I2V).
- **UGC-avatar:** `Captions/Mirage ($0.175/s) → Topview (susc.) → HeyGen (pay-as-you-go)`
  - Salto: (P) Mirage por-segundo es lo más barato con API pública; (F) HeyGen como red de seguridad madura.

### Tier ESTÁNDAR (cuenta activa, calidad publicable)

- **Imagen de producto:** `FLUX.2 [pro] ($0.03) → Ideogram 3.0 Default ($0.06, si lleva texto) → Seedream 4.0 ($0.03)`
  - Salto: (Q) si el creativo lleva copy/packaging → ruta a Ideogram; (P) baja a Seedream; (F) espejo Replicate.
- **Video base:** `Kling 2.5 Turbo ($0.07/s) → Luma Ray 2 Flash (medio) → Seedance 2.0 ($0.09/s)`
  - Salto: (Q) si hace falta keyframes start/end → Luma; (P) baja a Seedance; (F) espejo.
- **UGC-avatar:** `HeyGen Avatar IV (~$1/min) → Captions/Mirage ($0.175/s) → Creatify (si es ecommerce, Enterprise)`
  - Salto: (Q) para SKU real en cuadro → Creatify; (F/P) baja a Mirage.

### Tier PREMIUM (cliente con presupuesto, máxima fidelidad)

- **Imagen de producto:** `Nano Banana Pro ($0.134 @2K / $0.24 @4K) → FLUX.2 Max ($0.07) → Ideogram Quality+ref ($0.20)`
  - Salto: (P) el cap premium es alto pero acotado → baja a FLUX.2 Max; (Q) texto crítico → Ideogram con ref.
- **Video base:** `Veo 3.1 Standard ($0.40/s, audio nativo) → Kling 3.0 ($0.09–0.14/s) → Runway Gen-4.5 ($0.25/s, adaptador propio)`
  - Salto: (P) Veo es ~10x → baja a Kling; (Q) dirección de cámara precisa → Runway.
- **UGC-avatar:** `Arcads (realismo humano, Enterprise) → HeyGen Avatar IV → Synthesia (multi-idioma)`
  - Salto: (F/contrato) si Arcads no está disponible/negociado → HeyGen; (Q) testimonial multi-idioma → Synthesia.

---

## 4. Esquema de configuración por-cuenta para el admin

Campos que un marketer/admin define por cada cuenta de cliente. Las credenciales de adaptador se guardan cifradas (patrón `oauth_credentials.ciphertext` / rol `qualify_credential` ya existente en Qualify — nunca en claro en esta config).

```jsonc
{
  "account_id": "uuid-tenant-brand",
  "creative_engine_config": {
    "monthly_budget_cap_usd": 500.00,        // cap duro; al alcanzarlo, solo eslabones "budget" o bloqueo
    "budget_spent_usd": 0.00,                 // acumulado del ciclo (reset mensual)
    "soft_alert_pct": 80,                     // notifica al admin al 80% del cap
    "default_tier": "standard",               // "economico" | "standard" | "premium"
    "hitl_required": true,                    // aprobación humana antes de publicar (siempre true en Fase 5)

    "aggregators": {
      "primary":  "fal",                      // transporte primario
      "mirror":   "replicate",                // espejo para fallback (F)
      "credentials": {                        // referencias a secretos cifrados, NO valores
        "fal":       { "secret_ref": "vault://acct/fal_key" },
        "replicate": { "secret_ref": "vault://acct/replicate_key" }
      }
    },

    // Proveedores habilitados y ORDEN de la cadena, por tipo de tarea.
    // El motor recorre la lista en orden aplicando los umbrales de salto.
    "task_chains": {
      "product_image": {
        "enabled": true,
        "chain": ["flux2_pro", "ideogram_v3_default", "seedream_v4"],
        "max_cost_per_piece_usd": 0.10,
        "quality_threshold": 0.75             // score auto 0-1; por debajo => siguiente eslabón (Q)
      },
      "base_video": {
        "enabled": true,
        "chain": ["kling_25_turbo", "luma_ray2_flash", "seedance_20"],
        "max_cost_per_piece_usd": 3.00,       // p.ej. clip 15s
        "max_duration_s": 15,
        "quality_threshold": 0.70
      },
      "ugc_avatar": {
        "enabled": false,                     // deshabilitado si la cuenta no lo contrata
        "chain": ["heygen_avatar_iv", "captions_mirage", "creatify"],
        "max_cost_per_piece_usd": 5.00,
        "dedicated_adapters": {               // proveedores NO en agregador => key propia
          "heygen":   { "secret_ref": "vault://acct/heygen_key" },
          "captions": { "secret_ref": "vault://acct/captions_key" },
          "creatify": { "secret_ref": "vault://acct/creatify_enterprise_key" }
        }
      }
    },

    // Config de marca reutilizable (alimenta consistencia de producto/estilo)
    "brand_kit": {
      "reference_images": ["r2://brand/pack_shot_1.png", "..."],  // hasta 14 refs (Nano Banana Pro)
      "palette_rgb": ["#0A2540", "#FF6B00"],                       // Recraft rgb_colors
      "locked_style_lora_ref": null,                               // LoRA FLUX.2 por cliente (opcional)
      "product_source_url": "https://tienda.myshopify.com/...",    // Creatify url-to-video
      "avatar_id": null,                                           // avatar/voz clonada HeyGen reutilizable
      "voice_id": null
    },

    "fallback_policy": {
      "on_provider_error":      "next_in_chain",   // (F)
      "on_budget_exceeded":     "downgrade_tier",  // (P) -> fuerza eslabón budget o bloquea
      "on_quality_below":       "next_in_chain",   // (Q)
      "max_retries_per_provider": 2,
      "hard_stop_on_cap":       true               // si true, al 100% del cap NO genera (evita sobrecosto)
    }
  }
}
```

**Notas de diseño:**
- `secret_ref` nunca contiene el secreto — apunta al store cifrado, coherente con la custodia de credenciales ya existente en `packages/api/connections`.
- `chain` es el contrato del motor de fallback: lista ordenada de IDs de modelo resueltos contra una **tabla de precios versionada** (los precios de agregador fluctúan — §6).
- `hard_stop_on_cap: true` es el default seguro para cuentas pequeñas; premium puede ponerlo en `false` con alertas.

---

## 5. Coste estimado por pieza (para dimensionar márgenes)

Coste **de proveedor** (lo que Qualify paga; el precio al cliente lleva markup encima). "Video UGC 15s" = clip de 15 segundos.

### Una imagen de ad (product image)

| Tier | Modelo primario | Coste/pieza | Con edición/variación | Nota |
|------|-----------------|-------------|-----------------------|------|
| Económico | Seedream 4.0 | **$0.03** | +$0.01–0.04 (Kontext) | (DATO) |
| Estándar | FLUX.2 [pro] | **$0.03** | Ideogram si lleva texto $0.06 | (DATO) |
| Premium | Nano Banana Pro @2K | **$0.134** | @4K $0.24; Batch mitad | (DATO) |

**Margen imagen:** con precio al cliente de $0.25–0.50/imagen, el coste de proveedor ($0.03–0.24) deja **margen bruto 50–90%** según tier. El tier económico es casi todo margen.

### Un video UGC de 15s

**Vía modelo base (video generativo, sin avatar):**

| Tier | Modelo | Cálculo | Coste 15s |
|------|--------|---------|-----------|
| Económico | Seedance 1.5 Pro | 15s × $0.0247/s | **~$0.37** (DATO) |
| Estándar | Kling 2.5 Turbo | 15s × $0.07/s (3 clips de 5s encadenados) | **~$1.05** (DATO) |
| Premium | Veo 3.1 Std (audio nativo) | 15s × $0.40/s (2 clips de 8s, se recorta) | **~$6.00–6.40** (DATO) |

**Vía UGC-avatar (vocero/testimonial):**

| Tier | Modelo | Cálculo | Coste 15s |
|------|--------|---------|-----------|
| Económico | Captions/Mirage | 15s → bloque 18s × $0.175/s | **~$3.15** (DATO; redondeo a 6s) |
| Estándar | HeyGen Avatar IV | 0.25 min × ~$1/min (Avatar III 1080p ref) | **~$0.25–0.35/min → ~$0.10–0.25 por 15s** (DATO/inferencia) |
| Premium | Arcads / Synthesia | contrato mensual, coste marginal difuso | **~$5–11/video** (inferencia) |

> **Observación de márgenes clave:** el video generativo base (Seedance/Kling) es **1 orden de magnitud más barato** que Veo con audio. El UGC-avatar tiene coste muy dispar: HeyGen por-minuto es sorprendentemente barato por 15s, mientras Captions/Mirage penaliza por su redondeo a bloques de 6s en clips cortos. **Para un ad UGC corto (≤15s) con vocero, HeyGen ofrece el mejor coste/pieza orquestable.** Si el precio al cliente por pieza de video se fija en ~$3–8, el tier económico/estándar deja margen sano; el premium (Veo/Arcads) exige repricing al cliente o tratarlo como upsell.

---

## 6. Riesgos de integración

1. **Proveedores que cambian precio o cierran API (riesgo #1).**
   - **Sora 2**: API con cierre anunciado **24-sep-2026** (DATO) → **descartada** para producción. Ejemplo canónico de por qué no atar el motor a un solo modelo.
   - Precios de agregador **fluctúan con el upstream** (Kling/Seedance varían entre fal/Replicate/PiAPI, hasta ~2–4x) (DATO). **Mitigación:** tabla de precios **versionada y cacheada**, refrescada por job programado; el cap de presupuesto se calcula contra la tabla, nunca contra un literal en código.
   - Version churn acelerado (Seedream 4.0→4.5→5.0; Kling 2.5→2.6→3.0; Hailuo 02→2.3) rompe adaptadores pineados (DATO). **Mitigación:** pin de versión explícito por adaptador + test de contrato por modelo.

2. **Límites de rate y concurrencia.**
   - fal cuentas nuevas: **2 requests concurrentes**, sube a 40 al comprar créditos (DATO). Replicate: rate limits no publicados + **cold starts** en modelos long-tail (DATO). **Mitigación:** el queue del propio agregador + backpressure en el motor; para volumen, negociar límites vía sales antes de onboarding de cuentas grandes.
   - Especialistas UGC (Creatify, Topview, Arcads) exponen API **solo en Enterprise/Pro negociado** sin rate limits públicos (DATO) → imposible dimensionar sin contrato. **Mitigación:** no meterlos en cadenas de cuentas pequeñas; tratarlos como adaptador dedicado gated por tier premium.

3. **Dependencia de agregador único.**
   - fal como único transporte = punto único de fallo. **Mitigación (ya en el diseño):** Replicate como espejo obligatorio; el primer fallback ante (F) es cambiar de agregador para el **mismo** modelo antes de cambiar de modelo.
   - Modelos NO en ningún agregador (**Runway, GPT-Image-2, HeyGen, Captions/Mirage, todos los UGC especialistas, Nano Banana Pro solo en fal, Recraft solo en fal**) → cada uno exige **adaptador propio con key y billing separados**, multiplicando la superficie de mantenimiento y credenciales. **Mitigación:** interfaz de adaptador estricta + los NO-agregador solo se habilitan si la cuenta los justifica.

4. **Gobernanza de datos / geopolítica.** Kling (Kuaishou), Seedance/Seedream (ByteDance), MiniMax, Hailuo, Pippit (ByteDance) son proveedores chinos (DATO) — posibles vetos de marcas occidentales por data-residency. **Mitigación:** flag `data_residency_restricted` por cuenta que fuerza la cadena a Luma (US) / Runway (US) / FLUX (BFL, EU) / Google.

5. **Licencias y consentimiento.**
   - FLUX.2 [dev] self-host comercial exige **licencia BFL de pago**; solo Klein-4B es Apache-2.0 limpio (DATO). **Mitigación:** usar Klein-4B para self-host o pagar la licencia; documentarlo como ADR (mismo rigor que el precedente BSL de Moondream en el repo).
   - Clonado de avatares (HeyGen/Arcads) requiere **consentimiento del avatar + App Review** para terceros (inferencia) — bloqueante legal para clonar personas de clientes.

6. **La capa ad-creative-insight es competencia, no dependencia.** Omneky, Pencil y AdCreative traen su propio scoring de "qué convierte" que **solapa con el motor de ángulos propio de Qualify** (DATO/inferencia). Integrarlas ataría el diferenciador de Qualify a un tercero que compite. **Recomendación firme: no integrarlas en el motor de generación.**

---

**Fuentes:** [fal.ai video model pricing (invideo, ago 2026)](https://invideo.io/blog/ai-video-model-pricing/) · [Google Veo pricing guide (costgoat, ago 2026)](https://costgoat.com/pricing/google-veo) · [Nano Banana Pro API pricing (pricepertoken)](https://pricepertoken.com/pricing-page/model/google-gemini-3-pro-image-preview) · [Nano Banana Pro pricing (glbgpt)](https://www.glbgpt.com/hub/how-much-is-nano-banana-pro/) · [Kling 3.0 Turbo pricing (ImagineArt)](https://www.imagine.art/blogs/kling-3-0-turbo-pricing) · datos de proveedor aportados por los cuatro investigadores (verificación cruzada agosto 2026).

---

## 7. Actualización 28-sep-2026 — imagen publicitaria multi-referencia (producto real + local real)

*Añadido tras redefinir el tipo `static_flyer`: ya no es un "flyer" sino una **imagen publicitaria** construida con la foto del producto, la del fondo (el local) o ambas (`AdImageMode`: `product` / `background` / `both`), más una descripción de la escena (`MediaInputs.scene_prompt`). Caso canónico: **una mano sosteniendo el vaso de la marca, con el local real desenfocado detrás**. Estado en código: la UI, el brief y la validación ya lo soportan; **ningún modelo está conectado** — la pieza se sigue componiendo en local con Pillow hasta que se decida el adaptador. Las §2.1, §3 y §5 de arriba quedan como registro de agosto; para este caso manda esta sección.*

### 7.1 Ranking para este caso (precios por imagen en fal salvo nota)

| # | Modelo (id) | Refs | Precio | Latencia | Fidelidad de producto | Debilidades |
|---|---|---|---|---|---|---|
| 1 | **Nano Banana 2** (Gemini 3.1 Flash Image) `fal-ai/nano-banana-2/edit` | 14 (10 objetos en alta fidelidad) | $0.08 (1K) / $0.12 (2K); Google directo $0.067 / $0.101, Batch −50% (DATO) | 4–12 s (DATO) | Mejor "credibilidad de producto" en test de packaging para ads (Soku, jul-2026); arena multi-imagen 1369 (DATO) | Añade lo no pedido; texto pequeño se "sangra"; marca de agua SynthID (DATO) |
| 2 | **GPT Image 2.5 Sunburst/Flare** `openai/gpt-image-2.5/sunburst/edit` | 16 | 1024×1536: $0.041 `high` / $0.165 `max`; refs cobradas como tokens de entrada (DATO) | Lento: 105–150 s medido en GPT Image 2 `high`; Flare promete −50% (DATO) | **Nº1** en arena de edición multi-imagen (1527) y en Artificial Analysis (DATO) | Lento y caro en `max`; en Replicate solo GPT Image 2, con 3 proporciones (DATO) |
| 3 | **Seedream 5.0 Pro** `bytedance/seedream/v5/pro/edit` | 10 | $0.0675 + $0.0045/ref extra; Replicate $0.056 (DATO) | 38–48 s (DATO) | Arena 1414; edición por región, deja intacto el resto (DATO) | **Inventa copy y precios no pedidos** (DATO); proveedor chino (ver §6.4) |
| 4 | **Meta Muse Image** `meta/muse-image/edit` (en fal desde 1-sep-2026) | 1–10 | **$0.01** (DATO) | p50 17.8 s (DATO) | Arena 1403 (DATO) | Color 3.4/5, flojo para colores de marca; 4:5 solo recortando 3:4; no está en Replicate (DATO) |
| 5 | **Nano Banana Pro** `fal-ai/nano-banana-pro/edit` | 6 objetos | $0.15; Google directo $0.134 (DATO) | 10–20 s | No inventa; buena tipografía de envase | Superado por Nano Banana 2 en arena y precio (DATO) |
| 6 | **FLUX.2 [pro]/[max] edit** `fal-ai/flux-2-pro/edit` | 9 | Pro ≈ **$0.06 con 2 refs** (cobra MP de entrada); Max ≈ $0.13 (DATO) | — | **Fuera de los tops de edición** (DATO) | Útil solo como opción EU (BFL) para `data_residency_restricted` |
| 7 | **Bria Product Shot** `fal-ai/bria/product-shot` | producto + 1 escena | $0.04 (DATO) | — | Conserva los píxeles del producto (`placement_type=original`); datos licenciados (DATO) | No integra manos ni el producto dentro de la escena |

**Licencias:** Qwen-Image-2.1 (20-sep) lidera los modelos abiertos pero es **solo investigación, no comercial** → descartado. Qwen-Image-Edit-2511 sí es Apache-2.0 (vía self-host, por debajo de los líderes). FLUX.2 [dev] sigue exigiendo licencia comercial de BFL.

### 7.2 Cadenas recomendadas

Sustituyen, para este caso, a la cadena "FLUX.2 [pro] → Seedream 4.0" de §2.1/§3 y de ADR 32 D9.

- **Estándar (por defecto):** Nano Banana 2 (1K borrador / 2K final) → GPT Image 2.5 Sunburst `high` → Seedream 5.0 Pro.
- **Económico:** Muse Image → Seedream 5.0 Lite (`fal-ai/bytedance/seedream/v5/lite/edit`, $0.035) → Nano Banana 2 1K.
- **Premium:** GPT Image 2.5 Sunburst `max` → Nano Banana Pro 2K → Nano Banana 2 2K.
- **`data_residency_restricted`:** sin Seedream; FLUX.2 [max] como último eslabón.

Por modo: **`product`** → Nano Banana 2 (Bria Product Shot si es un envase posado y la etiqueta debe quedar exacta al píxel) · **`background`** → Nano Banana 2 o Seedream 5.0 Pro · **`both`** → Nano Banana 2 → GPT Image 2.5 (sube al primer puesto si la etiqueta tiene texto fino).

### 7.3 Forma del pipeline

**Una sola llamada multi-referencia**, no recorte + pegado: con los dedos envolviendo el vaso, el modelo tiene que redibujarlo dentro de la mano. Pasos:

1. Recorte del producto (Bria RMBG 2.0, $0.018), enviado en alta resolución.
2. 3 borradores en paralelo.
3. Control de calidad con lo que ya existe en `packages/models`: similitud SigLIP2 del recorte generado frente a la referencia + lectura de la etiqueta con Qwen3-VL. Si falla, siguiente eslabón.
4. Final en 2K con el borrador aprobado como referencia extra.
5. 1:1 y 9:16 regenerando con la pieza aprobada como referencia.
6. Opcional, "candado de etiqueta": pegar el recorte original (el compositor Pillow actual) y armonizar la luz con `fal-ai/iclight-v2`, solo cuando el producto no está tapado.

**Coste por pieza, un formato (inferencia):** económico ≈ $0.14 · estándar ≈ $0.38 (≈ $0.32 con Google directo) · premium ≈ $0.43. **El coste de "una imagen de ad" de §5 ($0.03) se queda corto para multi-referencia.**

### 7.4 Guía de prompt (mano + vaso + local)

- Orden fijo de referencias y su rol dicho en el prompt: "Image 1 = PRODUCT, image 2 = LOCATION" (Seedream: "Figure 1"; FLUX: `@image1`).
- Bloqueo del producto: "Reproduce the glass from image 1 exactly: same shape, logo, label text «NOMBRE», colours and liquid colour. Do not redesign, restyle or add any text, logo or watermark." El texto de la etiqueta, literal y entre comillas.
- Escena: "Use image 2 as the real location; keep its decor and layout, shallow depth of field (f/1.8), background bokeh."
- Mano: "A natural adult hand holding the glass by the stem at chest height, label facing camera, 3/4 view, product sharp and dominant."
- Luz: "Warm ambient light matching image 2, coherent reflections and condensation."
- La proporción va en el parámetro, no en el prompt. El copy en español lo pone nuestro renderer después.

### 7.5 Qué quedó obsoleto arriba

- §2.1: FLUX.2 [pro] ya no es el *anchor* para edición multi-referencia, y su $0.03 no incluye los MP de entrada.
- Seedream 4.0 → 5.0 Pro / Lite.
- Nano Banana Pro ya no es el líder: lo supera Nano Banana 2 (feb-2026).
- GPT-Image-2 sí está en fal y Replicate, llega a 3840 px, y ya existe la 2.5.
- Ideogram 3.0 → 4.0 (Apache-2.0); Recraft V3 → V4.1 (también en Replicate); FLUX.1 Kontext superado.
- §6.3: Nano Banana Pro ya está en Replicate.
- Faltaban Muse Image, MAI-Image (solo Azure Foundry) y Seedream 5.

**Fuentes (28-sep-2026):** [arena multi-image edit](https://arena.ai/leaderboard/image-edit/multi-image-edit) · [Artificial Analysis editing](https://artificialanalysis.ai/image/leaderboard/editing) · [fal Nano Banana 2 edit](https://fal.ai/models/fal-ai/nano-banana-2/edit) · [fal Nano Banana Pro edit](https://fal.ai/models/fal-ai/nano-banana-pro/edit) · [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) · [fal GPT Image 2.5 Flare](https://fal.ai/models/openai/gpt-image-2.5/flare/edit) · [fal Seedream 5 Pro edit](https://fal.ai/models/bytedance/seedream/v5/pro/edit) · [fal Muse Image edit](https://fal.ai/models/meta/muse-image/edit) · [IMG.LY Muse benchmark](https://img.ly/ai-benchmarks/models/meta-muse-image/) · [fal FLUX.2 pro edit](https://fal.ai/models/fal-ai/flux-2-pro/edit) · [fal Bria product shot](https://fal.ai/models/fal-ai/bria/product-shot/api) · [fal IC-Light v2](https://fal.ai/models/fal-ai/iclight-v2) · [Segmind: precios y latencias medidos](https://blog.segmind.com/ai-image-gen-pricing-compared-nano-banana-2-vs-seedream-5-0-vs-gpt-image-2-2026/) · [Soku: test de creativos de ads](https://soku.ai/blog/gpt-image-2-vs-nano-banana-2-vs-seedream-5-pro-ad-creative) · [Qwen-Image-2.1, licencia](https://mixed-news.com/en/qwen-image-2-1-transparent-rgba-7b-open-weights-research-licence/).
