# Comparativa de video generativo: HeyGen vs Seedance (y alternativas) para el generador `/create`

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

*Investigación del 2026-10-06 (gtm-specialist). Actualiza §2.2, §2.3, §5 y §6 de `docs/comparativa-apis-creativo-motor-angulos.md` (agosto/septiembre 2026) para el caso de video; no los repite. Caso de referencia: "Nibbles' Burgers" (smash burgers, Táchira, español venezolano), 9:16, 15–60 s, Reels/Stories. Fase del roadmap: motor de contenido/ángulos (Fase 5, adelantado por el carril de dogfooding de ADR 21/ADR 32). Motivo de compra que sirve: **activación** (crear piezas), no escucha.*

> **Convención:** (DATO) = verificado en la fuente enlazada, leída el 2026-10-06 salvo otra fecha; (INFERENCIA) = deducción o estimación nuestra. Precios en USD, coste de proveedor (sin markup). Las URLs completas están en §6; en el texto se citan inline cuando el dato es decisivo.
>
> **Filas marcadas ★** = precio inequívoco o hallazgo con fuente primaria, apto para que `market-opportunity-analyst` y `sales-consultant` lo usen tal cual.

---

## 1. Veredicto

- **HeyGen sirve para lo que es: un presentador que habla a cámara.** Su motor Avatar IV/V lee un guion exacto con la voz clonada de la marca, a $0.05/s (DATO, página de precios de developers.heygen.com). No hace acciones con objetos (abrir una bolsa, comer) ni mete el producto dentro de la escena. Pedirle eso con un avatar creado desde un prompt es usar mal la herramienta.
- **Seedance 2.0/2.5 sirve para la escena con acción y producto.** Encabeza o está en el grupo de cabeza de las dos arenas de Artificial Analysis. Acepta hasta 9 imágenes de referencia (2.0) o 30 (2.5), así que producto, bolsa con logo y local entran como referencias. Genera de una sola vez hasta 15 s (2.0) o 30 s (2.5) en 9:16, con audio nativo y diálogo con lip-sync (DATO). Su gran límite es que **bloquea caras humanas reales como referencia** (DATO).
- **El hallazgo que cambia el plan:** HeyGen ya vende Seedance dentro de su propia API. Se llama **Cinematic Avatar** (`POST /v3/videos` con `type: "cinematic_avatar"`, desde el 4-jun-2026). Cuesta 7 créditos = **$3.50 por video** de 4–15 s, admite 9:16 y hasta 9 imágenes de referencia, y lo mueve "the Seedance pipeline" (DATO). Así obtenemos la escena integrada con la misma clave, la misma facturación y los mismos avatares que ya tienen consentimiento, sin abrir un proveedor chino directo.
- **Ninguno resuelve solo el caso canónico** (actuar con el producto y además decir un guion exacto en español venezolano con la voz de la marca). Lo correcto son dos tomas: la escena con acción (Seedance, directo o vía HeyGen Cinematic) y la toma hablada con el guion exacto (HeyGen Lipsync o Avatar IV sobre un fotograma de esa misma escena). Se unen con ffmpeg y se cierra con una tarjeta final de logo real hecha en Remotion.
- **Otros que compiten:** Veo 3.1 Lite ($0.05/s con audio) es el carril económico. Gemini Omni Flash y MiniMax H3 puntúan alto en la arena, pero Omni solo tiene evaluado el inglés (DATO) y H3 no documenta el español. Kling 3.0 Omni documenta español en su blog pero queda en el puesto ~19 de la arena. **Sora queda descartado**: su API se apagó el 24-sep-2026 (DATO).

---

## A. Evidencia de calidad y seguimiento de prompt (arenas, leída 2026-10-06)

**Artificial Analysis — image-to-video, vista "con audio"** (DATO, https://artificialanalysis.ai/video/leaderboard/image-to-video): 1 MiniMax H3 Max (fal) 1195 · 2 MiniMax H3 1181 · 3 Gemini Omni Flash (Google) 1178 · 4 Dreamina Seedance 2.0 720p 1176 · 5 HiDream-O1-Video 1175 · 6 Wan 3.0 1164 · … · 11 Veo 3.1 1082 · 14 Veo 3.1 Lite 1071 · 17 Veo 3.1 Fast 1066 · 19 Kling 3.0 1080p Pro 1055. **HeyGen, Sora, Runway y OmniHuman no aparecen** (no son modelos de video general o no están en la arena).

**Artificial Analysis — text-to-video, con audio** (DATO, https://artificialanalysis.ai/video/leaderboard/text-to-video): 1 Wan 3.0 1156 · 2 Utopai X (sin API) · 3 **Dreamina Seedance 2.5** 1143 · 4 MiniMax H3 768p 1137 · 7 Seedance 2.0 1116 · 8 Gemini Omni Flash 1.1 1113 · 15 Kling 3.0 Omni 1015 · 18 Veo 3.1 962.

(INFERENCIA) Lectura: la generación de video general se movió mucho desde agosto. Seedance 2.x está en el grupo de cabeza en ambas arenas; Veo 3.1 y Kling 3.0 han caído al medio de la tabla. Una arena de preferencia humana mide calidad percibida y coherencia, no seguimiento fino de un guion de acciones; para eso hace falta la prueba propia de §5.

**Avatares (fuera de la arena):** HeyGen publica para Avatar V una similitud facial de 0.840 frente a 0.714 de Veo 3.1. Es una cifra del propio proveedor, no un benchmark independiente (DATO de lo que afirman, https://www.heygen.com/blog/heygen-october-2025-release). Las quejas públicas sobre HeyGen se repiten en dos puntos. El primero es el parecido y la calidad de los avatares hechos desde foto. El segundo es que **"no sigue instrucciones"** (DATO, agregado de reseñas de Capterra: https://www.capterra.com/p/10015133/HeyGen/reviews/ ; https://kimola.com/reports/heygen-ai-video-generation-app-consumer-insights). ★ Es una queja de comprador documentada y coincide con el problema 2 del fundador.

**Acciones con comida (comer, abrir empaques):** no encontré ningún benchmark público que lo mida aislado. Las comparativas de blogs (buildfastwithai, cometapi, atlascloud) son de agregadores con interés comercial y no prueban ese caso. (INFERENCIA) Comer es un caso difícil conocido: la comida se deforma y la mordida no tiene coherencia física. Hay que medirlo en el experimento de §5, no darlo por resuelto.

---

## 2. Tabla comparativa por criterio

Precio de "15 s" = clip de 15 s a 720p en 9:16 salvo nota. Tokens de Seedance = alto × ancho × s × 24 / 1024, es decir 21.600 tokens/s a 720p (DATO, Segmind 17-ago-2026).

| Criterio | **HeyGen** (Avatar IV/V, image mode) | **HeyGen Cinematic Avatar** (Seedance dentro de HeyGen) | **Seedance 2.0** (ByteDance) | **Seedance 2.5** | **OmniHuman 1.5** (ByteDance) | **Veo 3.1** (Std/Fast/Lite) | **Gemini Omni 1.1 Flash** | **Kling 3.0 / Omni** | **MiniMax H3** |
|---|---|---|---|---|---|---|---|---|---|
| Seguimiento de prompt / calidad | Presentador estable; el prompt solo gobierna gestos y expresión (DATO, notas de may-2026). Quejas de que "no sigue instrucciones" (DATO, Capterra) | La escena, el movimiento y el encuadre los compone Seedance a partir del prompt (DATO); calidad = Seedance (INFERENCIA) | i2v #4 (1176), t2v #7 (DATO, AA) | t2v #3 (1143) (DATO, AA) | No está en la arena; el prompt solo da "influencia estilística" (DATO, fal) | i2v #11–17 (1066–1082) (DATO, AA) | i2v #3 (1178) (DATO, AA) | i2v #19 (1055) (DATO, AA) | i2v #1–2 (1181–1195) (DATO, AA) |
| Personaje que habla un guion en español | **Sí, guion exacto**, más de 175 idiomas, voz clonada de la marca (ya integrada) (DATO) | No usa guion ni voz: "describe the shot in natural language" (DATO). Hace falta una pasada de lip-sync aparte (INFERENCIA) | Audio nativo; diálogo entre comillas con lip-sync por fonema "en 8+ idiomas" (DATO de blogs secundarios); acento venezolano no controlable (INFERENCIA) | Diálogo en más de 10 idiomas, incluido el español (DATO secundario, seedance.tv) | **Sí, desde nuestro audio** (ElevenLabs o TTS de HeyGen): hasta 30 s a 1080p o 60 s a 720p (DATO) | Audio nativo con diálogo (DATO); español no documentado en la fuente leída (INFERENCIA: funciona, pero hay que probarlo) | **Solo el inglés está evaluado**; no admite audio de referencia (DATO, docs Omni) | Kling dice "español con dialectos" (DATO, blog Kling); fal dice voz en inglés/chino para 3.0 Pro (DATO, fal): **contradicción**, hay que probar | No documentado |
| Acciones con objetos (abrir bolsa, comer) | **No** (motor de cabeza/torso que habla) (INFERENCIA fuerte) | Sí, es su razón de ser (INFERENCIA) | Sí; física y multi-toma en una generación (DATO) | Sí; plano único de 30 s (DATO) | No (gestos de habla) | Sí (INFERENCIA) | Sí (INFERENCIA) | Sí (INFERENCIA) | Sí (INFERENCIA) |
| Producto y logo integrados en escena | API v3: **no hay endpoint de product placement**. El "Product Placement" de la app web (Avatar IV, 1 foto de producto + 1 de cara) es solo para planes de pago y no está en la API (DATO para la web; INFERENCIA por no encontrarlo en docs) | Hasta 9 imágenes + 3 videos como referencia (DATO) | 9 imágenes + 3 videos + 3 audios, citados como @Image1… en el prompt; también primer y último fotograma (DATO) | 30 imágenes + 10 videos + 10 audios (DATO) | No (solo foto + audio) | 3 imágenes "ingredients" (personaje, estilo, asset) (DATO) | 3 imágenes de sujeto + primer/último fotograma (DATO); sabe dibujar texto legible (DATO) | Elementos de personaje desde video o imágenes (DATO) | i2v (DATO) |
| Consistencia del personaje | **La mejor**: look reutilizable + voz clonada (DATO) | Hasta 3 looks de HeyGen (DATO) | Buena dentro de una generación; entre videos depende de referencias **sin cara real** (DATO + INFERENCIA) | Mantiene "personajes y voces" entre extensiones (DATO) | Total: es la misma foto | Buena con ingredients (DATO) | Buena (DATO, docs) | Elementos + "voice control" (DATO) | — |
| Duración máx. / 9:16 / resolución | Hasta 30 min (DATO); 9:16 sí; 720p/1080p/4K | 4–15 s; 9:16; 720p/1080p (DATO) | 4–15 s; 9:16; 480p–4K (DATO) | 4–30 s; 480p/720p **sin 1080p** (DATO) | 30 s @1080p / 60 s @720p (DATO) | 4/6/8 s por clip, extensible (DATO, doc previo); 9:16 sí (DATO) | 3–10 s, extensible a 40 s; 9:16; 720p nativo (DATO) | 3–15 s (DATO) | 6–10 s (doc previo) |
| ★ Precio (unidad exacta) | Avatar IV/V **$0.05/s** (0.1 crédito/s, crédito = $0.50); avatar por prompt 1 crédito = $0.50; Lipsync 0.05/0.1 crédito/s = **$0.025/$0.05/s** (DATO, enterprise-pricing) | **7 créditos = $3.50 por video** (DATO) | fal **$0.3024/s** (Fast $0.2419/s). BytePlus **$7.0/M tokens** (Fast $5.6/M; con video de entrada $4.3/M) ≈ $0.151/s (DATO) | fal **$0.0214/1k tokens** ≈ $0.46/s; BytePlus **$10.70/M** ≈ $0.231/s (DATO) | fal **$0.16/s** (DATO) | Gemini API con audio: Std $0.40/s, Fast $0.10/s, Lite **$0.05/s** (720p) (DATO) | **$17.50/M tokens de video**, 5.792 tokens/s → ≈ $0.10/s a 720p (DATO) | fal 3.0 Pro i2v $0.112/s sin audio, $0.168/s con audio, $0.196/s con control de voz (DATO secundario) | fal H3 Max $0.08/s a 768p (DATO) |
| 15 s | **$0.75** (+$0.50 si el avatar se crea por prompt) | **$3.50** | fal $4.54 · BytePlus **$2.27** (Fast $1.81) | fal $6.93 · BytePlus $3.47 | $2.40 | Lite **$0.80** · Fast $1.60 · Std $6.40 (2 clips de 8 s) | ≈ $1.50 (10 s + 5 s) | ≈ $2.52–2.94 | ≈ $1.20 |
| API / madurez | v3 madura, webhooks, Idempotency-Key, 10 renders concurrentes en pay-as-you-go; **v1/v2 se retiran el 31-oct-2026** (DATO, adaptador) | v3, `callback_url` (DATO) | fal (cola + webhooks) o BytePlus ModelArk; Replicate/otros (DATO) | fal desde 13-ago-2026; BytePlus API desde ago-2026 (DATO) | fal (DATO) | Gemini API / Vertex / fal (DATO) | Gemini API (GA) (DATO) | fal / API Kling (DATO) | fal (DATO) |
| Licencia, marca de agua, moderación | Uso comercial; avatares con consentimiento (DATO); voz clonada con guarda de marca ya implementada | Igual que HeyGen | Uso comercial (DATO, fal). **Rechaza caras humanas reales en referencias**: error 400 que no se cobra; la cara sintética entra por "virtual avatar ingest"; una persona real exige prueba de vida + `groupId` (DATO) | Igual que 2.0 (INFERENCIA) | No documentado en lo leído | SynthID invisible (DATO) | SynthID invisible; rechaza "ciertas personas reconocibles"; con menores hay límites en EEE/UK (DATO) | — | — |
| Proveedor / riesgo | EE. UU. | EE. UU. por fuera, ByteDance por dentro (INFERENCIA) | **China** (ByteDance; BytePlus = Singapur). BytePlus no se ofrece en EE. UU., Canadá, UK, Australia ni NZ (DATO secundario) | China | China | EE. UU. | EE. UU. | China (Kuaishou) | China |

Descartados o secundarios para este caso:
- **Sora 2.** API apagada el 24-sep-2026, sin reemplazo (DATO, https://pasqualepillitteri.it/en/news/18764/openai-sora2-api-dismessa-en).
- **Runway Gen-4.5.** $0.12/s (12 créditos a $0.01) (DATO secundario, creatify.ai ago-2026). Exige un adaptador propio y no aporta nada para el habla en español.
- **Captions/Mirage.** Sin cambios: $0.175/s en bloques de 6 s (DATO, docs Mirage, modificado el 13-ago-2026), es decir $3.15 por 15 s. No integra producto.
- **Creatify.** **Cambio frente al doc previo:** la API ya no es solo Enterprise. Hay API Starter a $99/mes (500 créditos) y API Pro a $299/mes (2.000 créditos). Aurora cuesta 1 crédito/s ≈ $0.20/s con Starter (DATO, https://docs.creatify.ai/billing). Exige suscripción y no hay pago por uso.
- **Seedance 1.x.** 1.0 Lite fue retirado de Leonardo el 13-may-2026 (DATO). 1.5 Pro cuesta $0.026–0.047/s según la plataforma (DATO secundario). Ya no compite en calidad con 2.x (INFERENCIA, no está en el top de AA).

---

## 3. Diagnóstico de los 3 problemas: proveedor vs pipeline

Verificado contra el código de `packages/api/src/qualify_api/creative/media.py` (`_video`, `_prompt_avatar`, `HUMAN_STYLE`) y `packages/creative/src/qualify_creative/compose.py` (`compose_scene`).

| # | Síntoma | Parte del pipeline (nuestra) | Parte del proveedor | Peso |
|---|---|---|---|---|
| 1 | "Los videos se ven súper mal" | (a) `compose_scene` arma un fondo plano: foto del local o degradado de la marca, con los productos pegados. HeyGen recorta (matting) al avatar y lo pone encima. La luz, la perspectiva y la escala no coinciden, y eso da el aspecto de "recortado sobre un póster". Hay quejas documentadas de fondos mal reemplazados en la API (DATO, foro docs.heygen.com). (b) `HUMAN_STYLE` pide "fondo liso, plano medio, de frente a cámara", es decir, un retrato de estudio que luego se pega sobre un local. (c) En image mode animamos una foto cualquiera, que es el caso con más quejas de calidad (DATO, Capterra). | Avatar IV desde foto o prompt tiene problemas de parecido y valle inquietante en primer plano (DATO, reseñas) | **Mayormente pipeline** (INFERENCIA): elegimos una composición que HeyGen no está hecho para renderizar bien |
| 2 | El avatar por prompt "no siguió mi prompt" (sentado en un local, bolsa, destapa, come) | (a) `POST /v3/avatars {type:"prompt"}` crea **un look, es decir, una identidad**, no una escena ni una acción. Le pasamos una descripción de escena a un endpoint de retratos. (b) Le anteponemos `HUMAN_STYLE` ("de frente a cámara, plano medio, iluminación suave, fondo liso"), que contradice "sentado en una mesa de un local". (c) Recortamos a 1.000 caracteres (límite del endpoint). | Avatar IV no hace acciones con objetos; el endpoint correcto de HeyGen para ese prompt es **Cinematic Avatar** (DATO) | **Pipeline**: usamos el endpoint equivocado para la intención. El límite del proveedor es real, pero tiene solución dentro de HeyGen |
| 3 | El producto queda superpuesto, no integrado | `compose_scene` pega los productos **a propósito** en la franja superior (6–30 % del alto), "clear of a presenter standing in the lower two thirds". Es un diseño intencional, no un bug | La API v3 de HeyGen no expone product placement (solo existe en la app web) (DATO/INFERENCIA) | **100 % pipeline**: la integración real exige un modelo de escena con referencias (Seedance, Cinematic Avatar o Nano Banana 2 como fotograma inicial) |

---

## 4. Pipeline recomendado para el caso canónico

*Personaje en el local, con la bolsa con el logo en la mesa: la destapa, come la smash triple y dice el guion (≈ 12–15 s).*

Principio: **separar "actuar" de "hablar"**. La escena con acción la hace un modelo de video con referencias. La frase exacta, con la voz de la marca y el acento correcto, la hace un modelo de lip-sync sobre un fotograma de esa misma escena. Así el personaje y el producto quedan iguales en las dos tomas. El logo exacto va en una tarjeta final de Remotion (`packages/render`, coste $0), porque los logos se deforman en movimiento (INFERENCIA).

| Paso | Qué | Modelo (estándar) | Coste 15 s |
|---|---|---|---|
| 1 | Fotograma de escena multi-referencia (producto + bolsa/logo + local, más una persona sintética o sin cara visible) | Nano Banana 2 edit 2K (ya elegido en §7 del doc previo, aún sin conectar) | $0.12–0.24 (1–2 fotogramas) |
| 2 | Acción (sentarse, abrir la bolsa, morder), 8–10 s, 9:16 | **Seedance 2.0** i2v o reference-to-video 720p, prompt multi-toma. Si la cara del paso 1 dispara el filtro: referencias sin cara y el personaje generado por texto, o la ruta HeyGen Cinematic (abajo) | BytePlus $1.51 / fal $3.02 (10 s) |
| 3 | Toma hablada, 4–5 s, guion exacto en es-VE | Audio: TTS de HeyGen con la voz clonada de la marca (~$0) o ElevenLabs v3 ($0.10/1k caracteres ≈ $0.02). Video: **HeyGen Avatar IV image mode** sobre el último fotograma del paso 2 ($0.05/s), o **HeyGen Lipsync precision** sobre una toma de Seedance (0.1 crédito/s = $0.05/s) | $0.25 |
| 4 | Unión + subtítulos + tarjeta de logo | ffmpeg + Remotion | $0 |
| | **Total estándar** | | **≈ $1.9 (BytePlus) / ≈ $3.5 (fal)** |

**Variante "todo HeyGen"** (la de menor coste de integración, porque reutiliza la clave, el adaptador, los looks consentidos y la voz clonada): Cinematic Avatar con el look de HeyGen más 3–9 referencias (producto, bolsa, local) para la acción ($3.50), luego Lipsync precision o Avatar IV para la frase (≈ $0.25). **Total ≈ $3.75.** Esquiva el filtro de caras de Seedance porque las looks ya están en el pipeline de HeyGen (INFERENCIA, hay que probarlo). Lo que no sabemos: qué versión de Seedance usa por dentro y si genera audio.

**Tiers:**

| Tier | Cadena | Coste 15 s |
|---|---|---|
| Económico | Nano Banana 2 1K ($0.08) → **Veo 3.1 Lite** i2v, 2 × 8 s con audio y la frase en el prompt ($0.80) → si el acento o el guion fallan, HeyGen image mode 5 s ($0.25) | **≈ $0.9–1.15** |
| Estándar | Tabla de arriba: Nano Banana 2 → Seedance 2.0 → HeyGen Lipsync/Avatar IV → ffmpeg. Alternativa: todo HeyGen (Cinematic + Lipsync) | **≈ $1.9–3.75** |
| Premium | Nano Banana 2 2K ×2 ($0.24) → **Seedance 2.5** en una sola toma de 15 s con hasta 30 referencias y diálogo nativo (BytePlus $3.47 / fal $6.93) → HeyGen Lipsync precision en la frase si la voz no es la de la marca ($0.25). Alternativa: Veo 3.1 Standard 2 × 8 s ($6.40) | **≈ $4.0–7.4** |

Para comparar: el pipeline actual (Avatar IV 15 s + avatar por prompt) cuesta ≈ $1.25 y no cumple el brief. El doc previo (§5) estimaba "$0.10–0.25 por 15 s" para HeyGen: **es incorrecto**, son $0.75 a $0.05/s.

---

## 5. Riesgos y qué probar primero

**Riesgos:**
1. **Filtro de caras de Seedance (el riesgo #1 técnico).** No sabemos si una cara sintética fotorrealista hecha con Nano Banana 2 pasa como fotograma inicial en fal, ni si fal ofrece la ruta "virtual avatar ingest" de ModelArk. El rechazo da 400 y no se cobra (DATO), así que probarlo es barato.
2. **Proveedor chino** (§6, punto 4, del doc previo). Seedance, OmniHuman, Kling y MiniMax son ByteDance, Kuaishou o MiniMax. Consumirlos vía fal (contrato con EE. UU., ya es el agregador elegido en ADR 32) cuesta ~2× más que BytePlus, pero no abre un contrato directo. La Cinematic Avatar de HeyGen es una tercera vía con contrato EE. UU. **No verifiqué si BytePlus atiende a Venezuela ni a Colombia.**
3. **Acento.** Ningún modelo con audio nativo documenta el venezolano. Omni solo tiene evaluado el inglés (DATO). Por eso la frase con la marca va por TTS controlado (voz clonada en HeyGen) más lip-sync, y no por audio nativo.
4. **Física de comer y fidelidad del logo en movimiento.** No hay benchmark (INFERENCIA). Mitigación: mordida corta (2–3 s), plano en el que la bolsa se lea desde el fotograma inicial, y logo exacto en la tarjeta final.
5. **Churn de versiones y precios.** Seedance 2.0 → 2.5 en 6 meses; fal cobra 2× lo que BytePlus o Segmind (DATO). La tabla `pricing_data` versionada tiene que guardar el precio por token y la fórmula, no un $/s fijo.
6. **Plazo de HeyGen.** v1/v2 se retiran el 31-oct-2026; nosotros ya estamos en v3 (DATO, adaptador), así que no hay acción.
7. **Desfase de precios en nuestra tabla.** `heygen_avatar_iv` usa $0.0667/s. La página de enterprise-pricing dice 0.1 crédito/s = $0.05/s para todos los tipos de Avatar IV y para Avatar V (DATO). Nuestra cifra es conservadora pero está desactualizada.

**Experimento mínimo (≈ $20, una tarde).** El mismo brief de Nibbles (smash triple, bolsa con logo, local real, frase de 1 línea en es-VE), 9:16, una semilla por brazo:

| Brazo | Qué | Coste |
|---|---|---|
| A | HeyGen Cinematic Avatar (look existente + foto de producto + bolsa/logo + local) + Lipsync precision 5 s con la voz clonada | $3.75 |
| B | Seedance 2.0 reference-to-video en fal, 720p, 15 s, prompt multi-toma, refs sin cara, frase entre comillas | $4.54 |
| C | Nano Banana 2 2K con persona sintética ($0.12) → Seedance 2.0 i2v 10 s en fal ($3.02): **prueba el filtro de caras** | $3.14 |
| D | Nano Banana 2 1K ($0.08) → Veo 3.1 Lite 2 × 8 s ($0.80) → Veo 3.1 Fast 1 × 8 s para comparar ($0.80) | $1.68 |
| E | HeyGen image mode 5 s sobre el último fotograma de B o C (frase exacta, voz de marca) | $0.25 |
| F | Seedance 2.5 en fal, 15 s (techo de calidad) | $6.93 |
| | **Total** | **≈ $20.3** (≈ $40 con dos semillas) |

**Rúbrica (la puntúa el fundador a ciegas, de 0 a 2 por ítem):** sentado en la mesa · bolsa con el logo legible · la destapa · come sin deformaciones · el producto se parece a la foto (más la similitud SigLIP2 del recorte, que ya existe en `packages/models`) · frase exacta · acento creíble · sin aspecto de "recortado". **Decisión:** si A ≥ B, se adopta Cinematic Avatar (cero proveedores nuevos). Si B o C ganan, se conecta Seedance vía fal. Si C falla por el filtro, la escena se genera sin cara de referencia y la consistencia se apoya en el multi-toma.

---

## 6. Fuentes (leídas el 2026-10-06)

- Artificial Analysis, arenas de video: https://artificialanalysis.ai/video/leaderboard/image-to-video · https://artificialanalysis.ai/video/leaderboard/text-to-video
- ByteDance Seed, Seedance 2.5: https://seed.bytedance.com/en/blog/one-take-creation-flexible-referencing-introducing-seedance-2-5 · https://www.cined.com/bytedance-seedance-2-5-api-goes-live-30-second-single-shot-clips-50-reference-inputs-and-3d-camera-blockouts/
- fal Seedance: https://fal.ai/models/bytedance/seedance-2.0/image-to-video · https://fal.ai/models/bytedance/seedance-2.0/reference-to-video/api · https://fal.ai/learn/devs/seedance-2-5-vs-seedance-2-0
- Fórmula de tokens y precios comparados: https://blog.segmind.com/seedance-2-5-pricing-fal-charges-95-more-per-token-than-segmind/
- BytePlus ModelArk (la página no renderiza sin JS; cifras tomadas del extracto indexado): https://docs.byteplus.com/docs/ModelArk/model-service-pricing · https://saascrmreview.com/seedance-pricing/ · https://www.cometapi.com/seedance-2-5-api-pricing/ · https://aireiter.com/blog/seedance-2-5
- Política de caras en Seedance: https://docs.apiyi.com/en/faq/seedance2-asset-face-reference · https://community.adobe.com/questions-404/reference-content-can-t-include-real-human-faces-when-using-seedance-2-0-and-seedance-2-0-fast-1631867 · https://aividpipeline.com/blog/seedance-real-human-face-rules-2026 · https://blog.segmind.com/seedance-2-0-error-guide-every-error-explained-with-fixes/
- Idiomas de Seedance (secundario): https://www.cutout.pro/learn/blog-seedance-2-0-audio-guide/ · https://www.seedance.tv/blog/seedance-2-5-supported-languages
- OmniHuman 1.5: https://fal.ai/learn/biz/omnihuman-15-vs-omnihuman-comparison · https://fal.ai/models/fal-ai/bytedance/omnihuman
- HeyGen: https://developers.heygen.com/docs/enterprise-pricing.md · https://developers.heygen.com/cinematic-avatar.md · https://developers.heygen.com/docs/choosing-the-right-video-api.md · https://developers.heygen.com/lipsync-precision.md · https://developers.heygen.com/transparent-background-videos.md · https://www.heygen.com/en-gb/tool/ai-product-placement · https://www.heygen.com/blog/heygen-october-2025-release · https://www.heygen.com/blog/heygen-may-2026-release · https://releasebot.io/updates/heygen · https://www.heygen.com/apps/seedance-2
- Quejas sobre HeyGen: https://www.capterra.com/p/10015133/HeyGen/reviews/ · https://kimola.com/reports/heygen-ai-video-generation-app-consumer-insights · https://docs.heygen.com/discuss/67c095bf88902b004b94def4
- Google: https://ai.google.dev/gemini-api/docs/pricing · https://ai.google.dev/gemini-api/docs/omni · https://blog.google/innovation-and-ai/technology/developers-tools/veo-3-1-gemini-api/ · https://blog.google/innovation-and-ai/technology/ai/veo-3-1-ingredients-to-video/
- MiniMax H3: https://blog.segmind.com/minimax-h3-release-date-open-weights-and-api-pricing-explained/ · https://www.orcarouter.ai/blog/h3-max-fal-speed-debut
- Kling 3.0: https://kling.ai/blog/kling-video-3-omni-native-lip-sync-audio-guide · https://fal.ai/kling-3
- Sora 2, cierre: https://pasqualepillitteri.it/en/news/18764/openai-sora2-api-dismessa-en · https://invideo.io/blog/sora-ai-video-generator/
- Mirage: https://captions.ai/help/docs/api/pricing.md · Creatify: https://docs.creatify.ai/billing · Runway: https://creatify.ai/blog/runway-pricing-(2026)-plans-credits-and-what-you-ll-actually-pay
- ElevenLabs v3 en español: https://www.llmreference.com/provider/elevenlabs/eleven-v3 · https://www.famulor.io/voices/elevenlabs/languages/es/accents/latin-american
- Seedance 1.x: https://docs.leonardo.ai/docs/deprecations · https://llmgateway.io/models/seedance-1-5-pro

**Qué corrige del doc previo (`comparativa-apis-creativo-motor-angulos.md`):**
- §2.2: Seedance 2.0 no cuesta "~$0.09/s". Cuesta $0.30/s en fal y ≈ $0.15/s en BytePlus a 720p.
- §2.2: faltaban Seedance 2.5, Gemini Omni, MiniMax H3 y Wan 3.0.
- §2.2: Kling ya no es "el primario racional" para I2V según la arena.
- §2.3: Avatar IV cuesta $0.05/s y existe Avatar V. HeyGen ofrece Cinematic Avatar (Seedance) y Lipsync por API. Creatify ya tiene API por suscripción.
- §5: el coste de 15 s en HeyGen es $0.75, no $0.10–0.25.
- §6.1: el cierre de Sora quedó confirmado el 24-sep-2026.
