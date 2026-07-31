# Nicho #1 — Marca regulada responsable de contenido de terceros: de mercado a **features**

> **Analista de mercado externo (market-opportunity-analyst) · 2026-07-30**
> **Estado: CERRADO.**
>
> # 🛑 CONCLUSIÓN: recomiendo DECLINAR el nicho #1 como mercado — ver §9
>
> Las cinco afirmaciones que lo sostenían cayeron: los vendors **sí** analizan video (§2) y Compliverity **hace más que nosotros**; el caso insignia colombiano es de **primera parte** (una empresa multada por su propia publicidad, con el influencer como dueño) y **no** precedente de vigilar a terceros (§9.1); el presupuesto de compliance solo rompe el techo de precio **si vendes seguro**, y ADR 21 lo prohíbe (§8.3); el ancla real es el salario de un revisor colombiano (**~US$1.000-2.000/mes de coste empresa**), no una multa de $190-200k (§9.2). Y la tijera final: **la mitad de la tarea que es gratis es exactamente donde el enforcement está demostrado** (§9.3).
>
> **Sobrevive una sola pieza, y es ingeniería, no mercado: F2** (timestamps de transcripción + expediente con procedencia) — tres archivos, sin modelo nuevo, sin GPU. **Sobrevive precisamente porque nunca dependió de este nicho.**
>
> Condiciones de reapertura en §9.5. La más plausible: **que el comprador sea la agencia y no la marca** — es el candidato B-5 del doc de screening, puesto 2, **y sigue sin investigarse**.
>
> ## ⚠ LEER PRIMERO: la premisa por la que se eligió este nicho está REFUTADA (§2)
>
> **Vendors existentes SÍ analizan video en TikTok/IG** — Sedric, Compliverity, Brandwatch e influData transcriben audio y/o escanean frames. La afirmación *"el claim hablado es el punto ciego del listening de texto"* que aparece en varios docs de este proyecto **es falsa**, y Compliverity **hace más de lo que Qualify tiene construido** (detección de logos por frame; nosotros no la tenemos).
>
> **Aun así el documento entrega tesis de feature (§5), pero ninguna sobrevive por el motivo original.** Sobreviven porque: la 1 es deuda técnica útil pase lo que pase, la 2 se apoya en una **norma escrita** (el disclosure en caption es insuficiente para video — §3) y no en un hueco de mercado, y la 3 es barata de refutar. Si el nicho se eligió por el whitespace de video, **esa razón ya no existe**.
>
> ## 🟢 Y LEER SEGUNDO: §7 añade una feature mejor que las cinco de §4
>
> ## 🔴 Y LEER TERCERO: §8 encuentra una TIJERA que reordena todo
>
> Benchmark revisado por pares (arXiv 2510.08111): la clasificación patrocinado/no-patrocinado sale a **F1 0,93 con un LLM genérico**, pero el **anuncio encubierto falla un 28,57%**. Es decir: **el caso fácil es commodity y el caso difícil es invendible** (en compliance un falso negativo es una multa). Combinado con ADR 21 —que prohíbe permanentemente lo *autónomo* impreciso y solo admite lo *asistido*— el producto viable es **"ayudamos a tu revisor a mirar más rápido"**, no *"garantizamos tu cumplimiento"*. Eso lo paga el **coste del revisor**, no el tamaño de la multa, y **devuelve el techo de precio LATAM a la mesa**. Ver §8.2 y §8.3.
>
> El hallazgo de jurisdicción de `gtm` (a) **cierra el paso 0** — la obligación vive en **Colombia y EE. UU., no en Uruguay**, así que **el comprador de este nicho NO es el cliente uno** y no hay entrada caliente; y (b) aporta **F6**, donde el regulador colombiano (SIC) **recomienda expresamente revisar periódicamente los comentarios de la audiencia del influencer** — es decir **earned media**, recurrente, sin necesidad de visión ni embeddings ni GPU. Es lo inverso de lo que mató a farmacovigilancia. **Su falsador se resuelve leyendo un documento** (§7.2).
> Lado de la **demanda/mercado**. El lado de la **oferta/competencia** lo escribe `gtm` en `docs/oferta-mercado-marca-regulada.md`.

## 0. Encargo y cambio de formato

El fundador eligió este nicho desde `docs/oportunidades-mercado-pipeline-candidatos.md` (§7, puesto 1). **Redirección explícita del encargo: el entregable NO es prosa de tesis de mercado, son FEATURES concretas** que un product-owner pueda convertir en historias de backlog.

Consecuencia de formato, y la asumo: donde la pasada de screening producía tesis (`El cambio / El dolor / Sustitutos / …`), **este documento produce candidatos de feature con adyacencia verificada contra disco, falsador y validación más barata.** La tesis de mercado es el insumo, no el producto.

**Nota de encuadre que me obligo a respetar (corrección del fundador):** el inmobiliario **no está muerto como cliente** — solo murió la tesis de *listening de earned media* allí. No arrastro ese marco a la puntuación de este nicho.

### Tiering de evidencia

`[P]` primaria (URL + fecha de acceso) · `[S]` secundaria · `[H]` hipótesis. **Ninguna cifra de mercado inventada:** lo desconocido queda vacío con el experimento que lo resolvería.

### La pregunta que sostiene todo el nicho

> **¿Algún vendor existente analiza el CONTENIDO DE VIDEO** —viendo/transcribiendo lo que un afiliado *dice en cámara*— **o todos trabajan sobre texto, hashtag y metadatos?**

Si trabajan sobre video, no hay hueco y el nicho cae. Si trabajan sobre texto, el hueco es exactamente el activo diferenciado de Qualify. **Nada aguas abajo debe apoyarse en esto hasta que esté resuelto con fuente primaria** — la pasada de screening solo tenía un inventario de *nombres* de vendors, que no es evidencia sobre su tecnología.

---

## 1. Verificación contra disco — hecha ANTES de proponer features, no después

`[P]` Inspección directa del filesystem, 2026-07-30. Esto es la parte del documento con la evidencia más dura, porque no depende de ninguna fuente externa. **Cinco hallazgos, y tres de ellos cambian qué features son proponibles.**

### 1.1 — La procedencia es real y está en cada resultado ✅

`packages/models/src/qualify_models/schemas.py`: existe una clase base `Provenance(BaseModel)` con `source_id`, `detector_version`, `pipeline_version`, y **la heredan los cuatro resultados** (`FilterResult`, `VisionResult`, `TranscriptionResult`, `SentimentResult`). No es aspiracional: está en el tipo, así que un resultado sin procedencia no compila.

**Por qué importa para este nicho más que para cualquier otro:** un expediente de compliance no vale por la detección, vale por poder **demostrar** de dónde salió. Aquí la procedencia deja de ser higiene arquitectónica y pasa a ser el objeto que el comprador compra.

### 1.2 — ⚠ La transcripción NO tiene marcas de tiempo, y el contrato tampoco las admite

**El hallazgo más importante de esta sección**, porque afecta a casi toda feature de compliance sobre video.

```python
# providers.py:20 — el Protocol mismo no tiene sitio para segmentos
class TranscriptionProvider(Protocol):
    def transcribe(self, audio_path: Path) -> tuple[str, str | None]: ...

# providers.py:184-186 — y el provider real devuelve texto plano y descarta el idioma
def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
    return output.text, None
```

`TranscriptionResult` es `text: str` + `language` + `model_id` + procedencia. **No hay segmentos, ni `start`/`end`, ni offsets.** El transcript es un blob.

Tres consecuencias concretas:

1. **"El claim prohibido está en el minuto 0:47" no es construible hoy.** Esa frase aparece en la pasada de screening como si fuera una capacidad; **no lo es**. Se puede decir *que* el claim aparece en el video, no *dónde*.
2. **El coste de arreglarlo es acotado pero no trivial:** Whisper devuelve segmentos de forma nativa — **los está descartando el wrapper**. Arreglarlo toca el `Protocol`, el provider y el schema (tres archivos, un cambio de contrato), no requiere modelo nuevo ni GPU. Es la mejora de mayor palanca por línea de código que veo en este nicho.
3. **`language` se devuelve como `None` literal.** La detección de idioma no está cableada, pese a que el schema tiene el campo. Relevante porque el compliance multi-mercado necesita saber en qué idioma se hizo el claim.

### 1.3 — ⚠ `VisionResult` es descripción libre, no detección de marcas

`schemas.py:26-29` → `class VisionResult(Provenance): description: str; model_id: str`.

Es **texto libre describiendo la escena**. No hay clase de objeto, ni bounding box, ni confianza por marca, ni detección de logotipo. Confirma lo que la pasada de screening ya sospechaba, pero ahora con el tipo delante: **cualquier feature que requiera "detectar la marca X en pantalla" es capacidad nueva, no configuración.** Esto mata la adyacencia de la feature de valoración de patrocinio y hay que decirlo aquí también, porque el fundador puso ese nicho en el #2.

### 1.4 — ⚠ CERO embeddings en el repositorio — la feature *lookalike* no tiene cimiento

Busqué `embedding` y `SentenceTransformer` en `packages/` y `Qualify/`. **Todas las coincidencias son prosa** — `README.md` del scraper, tres `NOTES_*.md`, `permission_capability.py`, un `eval/conversation_cost.py`, un fixture de docs-harvester. **Ni una implementación.**

**Esto es directamente relevante para el ejemplo que dio el fundador.** "Feature de lookalike de marca/comercio" es el item de Fase 4 del roadmap (`crm.creators` con centroides de embeddings de contenido) y **no existe nada de su base**: sin embeddings, sin `search.embeddings`, y sin ClickHouse donde vivirían. Lo trato en §4 como candidato de feature igualmente —porque el encargo lo pide explícitamente— pero **con la adyacencia real, que es la peor de todas las candidatas**, no con la que sugiere el roadmap.

### 1.5 — Lo que sí está y es aprovechable tal cual

| Activo | Estado | Fuente en disco |
|---|---|---|
| Cascada `filter → vision → transcription → sentiment` composable | ✅ existe | `cascade.py:24 run_cascade` |
| Procedencia en los 4 resultados | ✅ existe | `schemas.py:6` |
| Transcripción vía HF Inference (sin GPU propia) | ✅ existe | `providers.py:176` |
| `connections`/OAuth Meta | ✅ lo más maduro del repo | verificado en la pasada anterior |
| Comentarios de IG de cuentas conectadas | ✅ existe | `qualify_models/social/ig_comments.py` |
| **Celery / scheduler** | ❌ **no existe** | cero coincidencias, verificado pasada anterior |
| **ClickHouse** | ❌ no existe | ídem |
| **Embeddings** | ❌ no existe | §1.4 |
| **Detección de logos/marcas** | ❌ no existe | §1.3 |
| **Timestamps de transcripción** | ❌ no existe | §1.2 |

> **Restricción que domina toda propuesta de feature en este nicho:** **sin scheduler no hay producto de vigilancia, solo un script que alguien ejecuta a mano.** Toda feature de compliance es vigilancia por definición. **Ninguna de las features de §4 es entregable sin resolver esto primero**, y no lo repito en cada ficha: se aplica a todas.

---

## 2. 🔴 La pregunta que sostenía el nicho tiene respuesta, y es NO: el whitespace no existe

**Este es el hallazgo principal del documento y contradice la premisa por la que el nicho fue elegido.** Lo pongo antes que las features porque, si sobrevive a la revisión de `gtm`, cambia qué features tiene sentido proponer.

La pasada de screening (`oportunidades-mercado-pipeline-candidatos.md` §1) afirmaba que el claim prohibido *"vive hablado dentro del video, no en el caption — es exactamente el punto ciego que el listening de texto no ve"*, y trataba a los vendors de compliance como un **inventario de nombres** sin verificar su tecnología. El lead pidió expresamente verificarlo antes de que nada dependiera de ello. **Verificado: es falso.**

### 2.1 — Cuatro vendors que ya analizan contenido de video, no texto

| Vendor | Qué hace sobre video, en sus propias palabras | Tier |
|---|---|---|
| **Sedric** | *"escanea continuamente posts, captions, stories **y videos** de influencers, marcando contenido con lenguaje promisorio (**'rentabilidad garantizada', 'sin riesgo'**), disclosures engañosos o llamadas a la acción no conformes"*; y aparte *"transcribe y traduce automáticamente en 40+ idiomas"* | `[S]` |
| **Compliverity** | *"transcripción instantánea + coincidencia de keywords de seguridad contra las guías FTC 2025, diseñado específicamente para compliance de TikTok"*; **"sus redes neuronales escanean CADA FRAME buscando texto de disclosure, logos de competidores e imaginería restringida"**, con análisis en **<90 segundos** por video | `[S]` |
| **Brandwatch** | *"transcripción audio-a-texto que captura menciones habladas de tu marca o de características de producto **que no están escritas en el caption ni en los hashtags**"* | `[S]` |
| **influData** | *"analiza comentarios, captions **y transcripciones** a lo largo del historial de un creator"*, con brand safety flags | `[S]` |

Fuentes (acceso 2026-07-30): [Sedric — Marketing Compliance](https://www.sedric.ai/solutions/marketing) · [Sedric — Affiliate/Partner Compliance](https://www.sedric.ai/partner-compliance) · [Sedric — Finfluencers en el radar de FINRA](https://www.sedric.ai/blog/when-social-clout-meets-compliance-finfluencers-in-finras-crosshairs) · [Compliverity](https://www.compliverity.com/) · [Syncly — mejores herramientas de listening TikTok 2026](https://syncly.app/blog/best-tiktok-social-listening-tool) · [influData](https://infludata.com/) · [Influencers-Time — TikTok Shop Live Selling Compliance](https://www.influencers-time.com/tiktok-shop-live-selling-compliance-framework-that-stops-ftc/)

### 2.2 — Tres afirmaciones del corpus de Qualify que esto refuta

1. **"El listening de texto no ve el claim hablado."** Brandwatch —el incumbente genérico más grande— **vende explícitamente transcripción de audio para capturar menciones que no están en el caption**. El punto ciego que varios docs de este proyecto citan como el hueco más limpio del mercado **está cubierto por el líder de la categoría**.
2. **"Leer el contenido, no el perfil" es diferenciador.** Lo hacen los cuatro. Como *principio de diseño* sigue siendo correcto; **como foso, no lo es.**
3. **Y la peor: Compliverity hace MÁS que lo que Qualify tiene construido.** Escanea *cada frame* buscando **logos** y texto de disclosure. Qualify **no tiene detección de logos** (§1.3) ni **timestamps de transcripción** (§1.2). En este nicho concreto, **un competidor pequeño está tecnológicamente por delante de nuestro estado en disco**, no por detrás.

### 2.3 — Qué queda vivo, dicho con precisión y sin rescatar el nicho a la fuerza

Hay que separar dos afirmaciones que es tentador confundir ahora:

- **"Nadie analiza video"** → **REFUTADO.** Con fuente. No vuelve.
- **"Nadie lo analiza *bien*, o en español, o con procedencia auditable"** → **ABIERTO.** Pero es una posición categóricamente más débil: pasa de *crear una categoría* a *desplazar a un incumbente por calidad*, y la calidad relativa no la he medido.

**Tres huecos residuales que sí podrían sostener algo, todos `[H]` y ninguno verificado:**

1. **Profundidad semántica vs. keywords.** Compliverity dice *"keyword safety matching"* y Sedric enumera frases literales (*"rentabilidad garantizada"*, *"sin riesgo"*). **Si el estado del arte es coincidencia de keywords sobre el transcript**, entonces un claim parafraseado (*"esto me quitó el insomnio en tres días"*) se les escapa, y ahí la cascada multimodal + un clasificador semántico tendría delta real. **Esto es lo único de este nicho que me parece que merece una comprobación empírica**, y es barato: pasar 20 claims parafraseados por la demo de un vendor.
2. **Español / LATAM.** Los cuatro son anglófonos. Sedric dice 40+ idiomas para *llamadas*, no necesariamente para video social. Sin verificar.
3. **Procedencia como expediente exportable.** Ninguno describe un expediente auditable con `detector_version` por señal. Es especulación mía a partir de lo que *no* dicen sus webs, que es evidencia débil.

### 2.4 — Salvedad de método que juega EN CONTRA de mi propio hallazgo

Todo lo anterior es `[S]`: **son webs de marketing de vendors, y la web de un vendor es el lugar donde más se exagera la capacidad.** "Nuestras redes neuronales escanean cada frame" puede ser una implementación seria o un OCR con un clasificador encima. **No he visto ninguna demo, ningún benchmark, ningún caso técnico.**

Pero la asimetría importa y es la razón por la que el hallazgo aguanta: para **refutar** "nadie hace video" basta con que estos vendors *lo intenten y lo vendan*, porque un comprador que ya compró Compliverity **no percibe el hueco** independientemente de la calidad real. La exageración del vendor degrada su producto, **no restaura nuestro whitespace.**

**Enrutado a `gtm`:** el teardown técnico real de Compliverity y Sedric (¿keywords o semántica? ¿español? ¿qué precio?) es lado de oferta y es su archivo (`docs/oferta-mercado-marca-regulada.md`). **Es ahora la pregunta más valiosa del nicho** y se la paso, en vez de duplicarla.

---

## 3. Alcance regulatorio preciso: ¿hay que VER el video, o basta con comprobar el hashtag?

**Respuesta: hay que ver Y oír el video. El hashtag en el caption es explícitamente insuficiente.** Y esto es lo único de este documento que **rescata** una feature concreta, así que conviene leerlo entero.

### 3.1 — Nota de tier, por delante

`[S]` **concordante entre cinco despachos independientes** (Davis+Gilbert, Manatt, Hall Render, Kelley Drye, Morgan Lewis) resumiendo la misma norma primaria. **La primaria es 16 CFR Part 255 (Endorsement Guides, revisadas 2023), §255.0(f).**

**No he podido acceder a la primaria con mis herramientas:** `ecfr.gov` redirige a una pasarela anti-bot y `ftc.gov` devuelve 403 a la descarga directa. **Un humano sí puede** — [16 CFR Part 255 en eCFR](https://www.ecfr.gov/current/title-16/chapter-I/subchapter-B/part-255) y [§255.0](https://www.ecfr.gov/current/title-16/chapter-I/subchapter-B/part-255/section-255.0). Lo dejo señalado en vez de presentar como `[P]` algo que no verifiqué. Cinco despachos AmLaw concordantes es evidencia bastante mejor que el marketing de vendor de §2, pero no es la norma.

### 3.2 — Lo que la norma exige, específicamente para video

| Requisito | Formulación | Consecuencia técnica |
|---|---|---|
| **Correspondencia de modalidad** | *Si el endorsement es visual, el disclosure debe ser visual; si es audible, audible; si es ambos, **ambos**.* | Hay que analizar **audio y frames por separado**, no el post como un objeto |
| **El caption NO basta** | *Los influencers que hacen endorsements en video deben hacer el disclosure **en el video mismo**, no en la descripción del post, porque "los espectadores pueden fácilmente ver un video sin leer los disclosures del texto".* | **Un `#ad` en el caption puede coexistir con un video no conforme** |
| **Doble disclosure en video** | *Audio **y** texto en pantalla* — porque algunos ven sin sonido y otros se pierden el texto superpuesto. | Se necesita **OCR sobre frames** + **transcripción**, no uno de los dos |
| **Las etiquetas de plataforma no sustituyen** | *Las herramientas de disclosure de la plataforma (p. ej. el tag "Paid Partnership" de Instagram) **no son sustituto** del disclosure propio en el contenido.* | **El campo de la API de Meta no resuelve el cumplimiento** — dato relevante porque es el atajo que cualquiera intentaría primero |
| **Debe ser inevitable** | En medios electrónicos interactivos, el disclosure debe ser *unavoidable*. | Criterio cualitativo, no automatizable de forma limpia |

Fuentes `[S]` (acceso 2026-07-30): [Davis+Gilbert — The Deep Dive: FTC Updates Endorsement Guides](https://www.dglaw.com/the-deep-dive-ftc-updates-endorsement-guides-for-modern-marketing-and-advertising/) · [Manatt — In-Depth Look, Part 2](https://www.manatt.com/insights/newsletters/advertising-law/an-in-depth-look-at-the-ftcs-updates-2) · [Hall Render — A Year Later](https://hallrender.com/2024/07/17/a-year-later-revisiting-ftcs-updated-endorsement-guides/) · [Kelley Drye — FTC Warning Letters over Disclosures](https://www.kelleydrye.com/viewpoints/blogs/ad-law-access/ftc-sends-warning-letters-to-companies-and-influencers-over-disclosures-in-posts) · [Morgan Lewis](https://www.morganlewis.com/pubs/2023/07/ftc-updates-endorsement-guides-proposes-endorsement-related-rule)

### 3.3 — ⚠ Por qué esto es más valioso que la premisa que murió en §2

La premisa original era *"detectar el claim prohibido"* — una tarea **semántica, abierta y difícil de acotar** (¿qué es un claim de salud? ¿está sustanciado?), con listón de precisión altísimo y competidores que ya la atacan.

Lo que la norma exige aquí es distinto en naturaleza: **verificación de presencia de un disclosure en dos modalidades.** Es una tarea **cerrada, mecánica y falsable**:

- ¿Hay una **enunciación** de disclosure en el transcript? → sí/no
- ¿Hay **texto superpuesto** de disclosure en algún frame? → sí/no
- ¿Hay `#ad` en el caption? → sí/no (trivial)

**Y el output interesante es la DISCREPANCIA entre las tres**, que es precisamente lo que una herramienta de texto no puede ver:

> **Un post con `#ad` en el caption y ningún disclosure dentro del video le parece conforme a cualquier herramienta basada en texto — y según la FTC es NO conforme.** Ese falso negativo es un hecho verificable, no una opinión de modelo.

Esto convierte la propuesta de *"clasificar si un claim es ilegal"* (juicio legal, que ningún vendedor de software debería prometer) en *"verificar si un elemento requerido está presente en cada modalidad"* (comprobación auditable). **Es una feature mucho mejor definida y con un falsador limpio.**

**Contrapeso obligatorio, porque §2 no desaparece:** Compliverity afirma escanear *"cada frame buscando texto de disclosure"* — es decir, **ya cubre la mitad visual de esto**. Lo que no sé es si cubre la mitad **audible** y si cruza las tres fuentes para producir la discrepancia. **Ésa es la pregunta que decide si esta feature tiene hueco**, y se la he pasado a `gtm`.

---

## 4. Candidatos de FEATURE — el entregable principal

Cinco candidatos. Cada uno con **adyacencia verificada contra disco por feature** (no por nicho), qué falta exactamente, y una nota honesta de si un competidor ya lo hace.

**Recordatorio que aplica a las cinco y no repito:** sin scheduler no hay vigilancia, solo ejecución manual (§1.5).

### Tabla resumen

| # | Feature | Adyacencia | Qué falta exactamente | ¿Competidor ya lo hace? |
|---|---|---|---|---|
| **F1** | **Auditoría de disclosure en tres modalidades** (audio / frame / caption) y reporte de discrepancia | **MEDIA — la mejor del conjunto** | OCR sobre frames; timestamps de transcripción; regla de decisión | **Parcialmente** (Compliverity dice frames; audio sin verificar) |
| **F2** | **Timestamps de transcripción + expediente exportable con procedencia** | **ALTA — la más cercana a disco** | Cambio de contrato en 3 archivos; renderizador de expediente | No lo describe ninguno |
| **F3** | **Detección semántica de claim parafraseado** (más allá de keywords) | **MEDIA-BAJA** | Clasificador nuevo + golden set + calibración | Sí, en su versión keyword. Semántica: `[H]` sin verificar |
| **F4** | **Lookalike: dado un infractor conocido, encontrar cuentas con contenido similar** | **BAJA — la más lejana de todas** | Embeddings (cero en disco), almacén vectorial, ClickHouse | No en compliance; sí en discovery (Modash, Kuli) |
| **F5** | **Detección de logo/marca en frame** (para patrocinio y para uso no autorizado de marca) | **BAJA** | Capacidad de visión nueva + golden set | **Sí — Compliverity lo afirma explícitamente** |

---

### F1 · Auditoría de disclosure en tres modalidades

**Qué hace.** Para cada video de un afiliado: (a) ¿hay enunciación de disclosure en el audio? (b) ¿hay texto de disclosure superpuesto en algún frame? (c) ¿hay `#ad`/`#publicidad` en el caption? Salida: matriz 3×sí/no + **veredicto de discrepancia**, con el requisito de correspondencia de modalidad de §3.2 aplicado.

**Por qué es la mejor del conjunto.** Es la única feature del documento que sale **directamente de un requisito normativo escrito** (§3.2) en vez de de una intuición de producto, y su output es un **hecho comprobable** (presente/ausente por modalidad), no un juicio legal. El caso estrella es el falso negativo de las herramientas de texto: `#ad` en caption + video mudo = **no conforme y aparentemente conforme**.

**Adyacencia: MEDIA.** Reusa `run_cascade`, la transcripción y la procedencia tal como están. Falta:
- **OCR sobre frames** — `VisionResult.description` es texto libre (§1.3); describir una escena no es leer texto superpuesto. Es capacidad nueva, aunque mucho más acotada que detección de logos: OCR es commodity comprable (Tesseract/PaddleOCR/API de visión), no requiere entrenamiento.
- **Timestamps** (§1.2) — para *demostrar* dónde estaba el disclosure. Ver F2.
- La **regla de decisión** de correspondencia de modalidad. Nótese la trampa: `filter_decision.py` existe pero QUA-23 está abierta con un golden set de **un ítem** — este proyecto ya tiene un precedente de regla de decisión sin cablear, y ésta no debe repetirlo.

**Falsador.** Que Compliverity (o Sedric) ya cruce las tres modalidades y reporte la discrepancia. Si lo hacen, F1 no tiene hueco. **Sin resolver — es la pregunta que pasé a `gtm`.**

**Validación más barata.** Coger **20 posts reales de afiliados con `#ad` en el caption**, ver los videos a mano y contar en cuántos falta el disclosure dentro del video. Si es una fracción alta, el falso negativo es real y medible sin construir nada. **Horas, sin hablar con nadie, sin escribir código.** Es la validación más barata de todo el documento.

---

### F2 · Timestamps de transcripción + expediente exportable con procedencia

**Qué hace.** Que cada señal derivada apunte a `(post_id, segundo_inicio, segundo_fin, detector_version, pipeline_version)` y que exista un render exportable: *"el 2026-07-14, en este post, entre 0:44 y 0:51, se dijo «X», detectado por claim-detector-v3"*.

**Por qué está aquí como feature y no como tarea técnica.** Porque **es el objeto que el comprador de compliance compra.** §1 de la pasada de screening ya lo decía sin poder verificarlo: la obligación regulatoria no es "detectar", es **poder demostrar que vigilaste**. Sedric vende *"audit trails"* como argumento de venta central; es la parte de su propuesta que ninguna de las otras tres describe con detalle.

**Adyacencia: ALTA — la más cercana a disco de las cinco.** La procedencia ya existe y es obligatoria por tipo (§1.1). El cambio es acotado y conocido:
- `providers.py:20` — ampliar el `Protocol` (`transcribe()` hoy devuelve `tuple[str, str|None]`, sin sitio para segmentos)
- `providers.py:184` — dejar de descartar los segmentos que **Whisper ya devuelve**
- `schemas.py:31` — añadir segmentos a `TranscriptionResult`

**Tres archivos, un cambio de contrato, sin modelo nuevo, sin GPU.** Es la mejora de mayor palanca por línea de código del nicho.

**Falsador.** Que los compradores acepten el transcript completo sin timestamps como evidencia suficiente. Si el revisor de compliance va a ver el video entero de todos modos, el timestamp es comodidad y no producto.

**Validación más barata.** Preguntar a un responsable de compliance qué exige su expediente: ¿basta "se dijo en este post" o necesita "en este segundo"? Una conversación. **Y es la única feature del documento que se puede construir sin haber resuelto §2**, porque no compite en detección — mejora la evidencia.

---

### F3 · Detección semántica de claim parafraseado

**Qué hace.** Detectar el claim prohibido cuando **no coincide con ninguna keyword**: *"esto me quitó el insomnio en tres días"* en vez de *"cura el insomnio"*.

**Por qué está vivo pese a §2.** Es el único hueco residual con una hipótesis mecánica detrás: **si el estado del arte es keyword matching** (Compliverity dice literalmente *"keyword safety matching"*; Sedric enumera frases literales), la paráfrasis se les escapa por construcción.

**Adyacencia: MEDIA-BAJA, y aquí hay que ser duro.** La cascada da el transcript, pero el clasificador **no existe**, y este proyecto **ya documentó ese hueco exacto**: `packages/models/NOTES_pain_signal_feasibility.md` concluyó que el modelo de sentimiento comprometido (3 clases de polaridad) no puede cargar señales de intención/dolor. La conclusión traslada directamente. Requiere: clasificador nuevo (probablemente el zero-shot de texto ya propuesto pero **no comprometido**), golden set etiquetado por alguien con criterio regulatorio, y calibración con listón de recall alto — **un falso negativo en compliance es incumplimiento, no un informe flojo**.

**Falsador.** Que los vendors ya hagan semántica y no keywords. `[H]` sin verificar; es la mitad de la pregunta que pasé a `gtm`.

**Validación más barata.** **Escribir 20 paráfrasis de claims prohibidos y pasarlas por la demo de un vendor.** Si las detecta, F3 muere ese día. Si no, hay delta medido, no supuesto. Coste: una tarde y quizá una demo comercial.

---

### F4 · Lookalike de infractores *(la feature que el fundador pidió considerar explícitamente)*

**Qué hace.** Dado un afiliado que hizo un claim prohibido, encontrar **otras cuentas publicando contenido similar** — el item de Fase 4 del roadmap (centroides de embeddings de contenido) aplicado a compliance en vez de a discovery.

**Veredicto honesto: es la feature más lejana de disco de las cinco, y el encargo pedía comprobar si encaja o es un estirón. Es un estirón — hoy.**

**Adyacencia: BAJA.** No es que falte una pieza; **falta la base entera**:
- **Cero embeddings en el repositorio** (§1.4) — verificado: todas las coincidencias de `embedding` son prosa en READMEs y NOTES, ni una implementación
- **Sin `search.embeddings`** y **sin ClickHouse** donde viviría
- Sin almacén vectorial ni índice de similitud

**Y hay un problema de encaje conceptual, no solo de construcción, que importa más:** el lookalike de Fase 4 está diseñado para **descubrimiento** — *"encuéntrame creators parecidos a los que me funcionan"*, donde un falso positivo cuesta un pitch perdido. En compliance, **un falso positivo es acusar a alguien de una infracción que no cometió.** El mismo mecanismo con un coste de error radicalmente distinto. La similitud de contenido dice *"esta cuenta habla de temas parecidos"*, que **no es** *"esta cuenta cometió una infracción"* — y la distancia entre esas dos frases es exactamente el riesgo legal del comprador.

**Reformulación que sí me parece defendible, y la ofrezco porque el fundador pidió considerar la feature en serio:** no lookalike *de infractores* sino **priorización de cola de revisión** — ordenar qué videos mira primero un revisor humano por similitud con infracciones confirmadas. El output es *"revisa esto antes"*, no *"esto es una infracción"*. Mismo mecanismo técnico, coste de falso positivo aceptable, y encaja con "assisted, no autonomous" que este proyecto ya tiene como principio (ADR 21: precisión del 65% = 1 de cada 3 borradores mal).

**Falsador.** Que los revisores de compliance no tengan problema de volumen. Si un afiliado publica 5 videos al mes, no hay cola que priorizar y la feature no tiene razón de existir.

**Validación más barata.** Preguntar cuántos videos de afiliados revisa una marca al mes y cuántos puede ver un humano. Si los números están cerca, no hay problema de cola. **Una conversación, y decide la feature entera.**

---

### F5 · Detección de logo/marca en frame

**Qué hace.** Detectar la marca en pantalla — para valoración de patrocinio (nicho #2) y para uso no autorizado de marca.

**Adyacencia: BAJA.** `VisionResult` es `description: str`, texto libre (§1.3). No hay clase de objeto, bounding box ni confianza por marca. Es capacidad de visión nueva con su propio golden set.

**Y aquí el competidor está por delante:** Compliverity afirma escanear cada frame buscando **logos de competidores**. No es un hueco; es una desventaja.

**La incluyo por una razón sola:** es la dependencia técnica del nicho #2 (valoración de patrocinio) que el fundador también eligió. **Que aparezca aquí con adyacencia BAJA es información para ese nicho**, y confirma desde otro ángulo lo que la pasada de screening ya concluyó — N-2 es el candidato más lejano al disco.

---

## 5. Síntesis — tres tesis de feature en formato accionable para product-owner

Formato pensado para convertirse en historia de backlog sin traducción intermedia. **Orden = orden de ejecución recomendado**, y no es el orden de atractivo comercial: es el orden en que cada una desbloquea a la siguiente y arriesga menos.

---

### TESIS DE FEATURE 1 — «Expediente con procedencia al segundo» (F2)

| Campo | Contenido |
|---|---|
| **Historia** | *Como responsable de compliance de una marca con afiliados, quiero que cada señal detectada apunte al segundo exacto del video en que ocurrió, con versión de detector, para poder presentar un expediente auditable sin volver a ver el video.* |
| **Por qué primero** | **Es la única tesis que no depende de resolver §2.** No compite en detección: mejora la evidencia. Se puede construir aunque el hueco de mercado resulte inexistente, porque **también es deuda técnica que cualquier otra feature de este nicho necesita**. |
| **Adyacencia** | **ALTA, verificada.** `Provenance` ya es obligatoria por tipo (`schemas.py:6`). Whisper **ya devuelve segmentos y el wrapper los tira** (`providers.py:184`). |
| **Alcance técnico** | 3 archivos: ampliar `TranscriptionProvider.transcribe()` (hoy `-> tuple[str, str\|None]`, sin sitio para segmentos), dejar de descartar segmentos, añadirlos a `TranscriptionResult`. **Sin modelo nuevo, sin GPU.** Bonus del mismo cambio: `language` hoy se devuelve `None` literal — se arregla de paso. |
| **Falsador** | Que a un revisor de compliance le baste "se dijo en este post" y vaya a ver el video completo igualmente. Entonces el timestamp es comodidad, no producto. |
| **Validación más barata** | Una conversación con un responsable de compliance: *¿tu expediente exige el segundo o basta el post?* |
| **Riesgo** | Bajo. Es el único item del documento que **mejora el producto aunque el nicho entero se caiga**. |

---

### TESIS DE FEATURE 2 — «Auditoría de disclosure en tres modalidades» (F1)

| Campo | Contenido |
|---|---|
| **Historia** | *Como responsable de compliance, quiero saber en qué videos de mis afiliados falta el disclosure DENTRO del video (audio y/o texto en pantalla) aunque el caption lleve `#ad`, porque la FTC considera insuficiente el disclosure en la descripción del post.* |
| **Por qué es la tesis central** | Es la única que sale de un **requisito normativo escrito** (§3.2) y no de una intuición de producto, y su output es un **hecho verificable por modalidad**, no un juicio legal — que es lo que ningún proveedor de software debería prometer. El caso estrella es un **falso negativo estructural de toda herramienta basada en texto**. |
| **Adyacencia** | **MEDIA.** Reusa `run_cascade` + transcripción + procedencia. Falta **OCR sobre frames** (commodity comprable: PaddleOCR/Tesseract/API de visión — **no** entrenamiento) y los timestamps de la Tesis 1. |
| **Falsador** | **Que Compliverity o Sedric ya cruce las tres modalidades y reporte la discrepancia.** Compliverity ya afirma escanear frames buscando texto de disclosure — cubre la mitad visual. **Sin resolver: es la pregunta que decide esta tesis, y está con `gtm`.** |
| **Validación más barata** | **20 posts reales de afiliados con `#ad` en caption; ver los videos a mano; contar en cuántos falta el disclosure dentro del video.** Sin código, sin entrevistas, horas. **Empezar por aquí antes de escribir una línea.** |
| **Riesgo** | Medio, y concentrado en el falsador: si el competidor ya lo hace, no hay hueco. La norma no cambia; la posición competitiva sí. |

---

### TESIS DE FEATURE 3 — «Priorización de cola de revisión» (F4 reformulada)

| Campo | Contenido |
|---|---|
| **Historia** | *Como revisor de compliance con más videos de afiliados que capacidad de verlos, quiero que la cola venga ordenada por similitud con infracciones ya confirmadas, para mirar primero lo más probable.* |
| **Por qué así y no como pidió el encargo** | El encargo pedía valorar *"lookalike: dado un infractor, encontrar otras cuentas con contenido similar"*. **La reformulo, y explico por qué en vez de entregar la versión pedida:** el lookalike de Fase 4 se diseñó para descubrimiento, donde un falso positivo cuesta un pitch. En compliance **un falso positivo acusa a alguien de una infracción que no cometió.** "Habla de temas parecidos" **no es** "cometió una infracción", y esa distancia es el riesgo legal del comprador. Como **priorización** el output es *"revisa esto antes"*, el coste del error es aceptable, y encaja con el principio *assisted, no autonomous* que este proyecto ya tiene firmado (ADR 21). |
| **Adyacencia** | **BAJA, y es la peor del documento.** No falta una pieza, falta la base: **cero embeddings en el repo** (§1.4, verificado), sin `search.embeddings`, sin ClickHouse, sin índice vectorial. |
| **Falsador** | **Que no exista problema de volumen.** Si una marca recibe 5 videos de afiliado al mes, no hay cola que priorizar y la feature no tiene razón de existir. |
| **Validación más barata** | *¿Cuántos videos de afiliados te llegan al mes y cuántos puede ver una persona?* Si los números están cerca, **la tesis muere en una conversación** — antes de tocar embeddings. |
| **Riesgo** | Alto en construcción, bajo en descubrimiento: **es cara de construir y baratísima de refutar.** Por eso va tercera y por eso su validación debe ejecutarse *antes* que las otras dos, aunque su construcción vaya después. |

---

## 6. Lo que este documento NO establece

1. **El nicho perdió su premisa (§2) y las tres tesis sobreviven por razones distintas a la original.** La Tesis 1 sobrevive porque es deuda técnica útil pase lo que pase; la Tesis 2 porque se apoya en una norma escrita y no en un hueco de mercado; la Tesis 3 porque es barata de matar. **Ninguna sobrevive por el argumento por el que el nicho fue elegido.** Si el fundador eligió el nicho por el whitespace de video, esa razón ya no está.
2. **Cero compradores entrevistados, otra vez.** Las tres validaciones más baratas son conversaciones o inspección manual — ninguna requiere código. **Ese es el trabajo que sigue, y es de horas.**
3. **§2 es `[S]` de marketing de vendors y §3 es `[S]` de despachos.** Nada aquí es `[P]` salvo la verificación contra disco de §1, que es la única parte que no depende de nadie externo. Las primarias regulatorias están citadas y accesibles a un humano; a mí me las bloquearon (403 / anti-bot).
4. **No he tocado el lado de oferta.** El teardown técnico de Compliverity y Sedric —¿keywords o semántica? ¿español? ¿precio?— es de `gtm` y es ahora **la pregunta más valiosa del nicho**. Está enrutada.
5. **Jurisdicción, sin resolver y sigue siendo el paso 0.** Todo §3 es **derecho estadounidense** (FTC, 16 CFR 255). Si el comprador objetivo es LATAM, hay que rehacer §3 contra el régimen local **antes** de construir la Tesis 2, que es la única que depende enteramente de una norma. Éste es el error que ya mató a T-1 en el inmobiliario; lo señalo por tercera vez porque sigue sin cerrarse.
6. **Nicho #2 (valoración de patrocinio) recibe un dato desde aquí:** su dependencia técnica es F5 (detección de logo/marca), adyacencia **BAJA** y con **un competidor que ya lo afirma**. Confirma desde otro ángulo que era el candidato más lejano al disco.

> **⚠ El punto 5 (jurisdicción) quedó RESUELTO horas después de escribirse. Ver §7, que además añade una feature nueva y mejor que las cinco de §4.**

---

## 7. Addendum — el hallazgo de jurisdicción de `gtm` cambia tres cosas

`[P]`/`[S]` vía `gtm`, `docs/oferta-mercado-marca-regulada.md` §1 (verificado por el lead: 82 líneas, caso de enforcement fechado). Integro tres consecuencias, y **la segunda produce la mejor feature del documento**.

### 7.1 — Jurisdicción resuelta: Colombia y EE. UU. sí, Uruguay no. Y el comprador NO es el cliente uno

- **Colombia tiene dientes:** guía específica de influencers de la SIC + Ley 1480, y **un caso real de enforcement con fecha e importe** — Resolución 20777, 2025-04-15, Grupo Cossio S.A.S., **COP 813M (~$190-200k)**.
- **Uruguay no:** solo protección al consumidor genérica, sin guía específica de influencers, sin caso encontrado.

**Cierra el paso 0 que llevo señalando tres veces**, y lo cierra con la respuesta incómoda: **este nicho no es una extensión del cliente uno.** Consecuencias comerciales que nombro porque son las que más fácilmente se pasan por alto cuando una tesis técnica funciona:

1. **No hay entrada caliente.** El único cliente que paga está en Uruguay, que es precisamente donde la obligación no existe. Este nicho es **venta en frío en un mercado nuevo**, sin la relación existente como palanca.
2. **El techo de precio LATAM que hundió al inmobiliario podría no aplicar aquí** — una multa de ~$190-200k reordena el cálculo de un comprador colombiano frente a los $50-185/mes que `gtm` midió para software de PYME. Pero ojo: **eso es una hipótesis sobre disposición a pagar, no un precio observado.** Sin verificar.
3. **Y acepto el razonamiento de `gtm` de que esto NO repite el error T-1.** En el inmobiliario el comprador estaba fijado a Uruguay por el repositorio y se midió el mercado equivocado. Aquí **la obligación regulatoria misma es más fuerte en EE. UU./Colombia**, así que ahí viven legítimamente el deber y la oferta. La diferencia es real: allí la geografía se asumió, aquí se eligió con motivo.

### 7.2 — 🟢 F6: el regulador colombiano escribió la especificación de producto, y es EARNED media

La SIC **recomienda expresamente** a los anunciantes:

> *"revisar periódicamente los comentarios y reseñas de los consumidores que constituyen la audiencia del influenciador"*

Tres propiedades que hacen de esto la mejor feature del documento, y conviene ver por qué **cada una** resuelve un problema que mató a un candidato anterior:

| Propiedad | Por qué importa |
|---|---|
| **Es EARNED media, no owned** | Comentarios en el post **del influencer**, no en el de la marca. **Esto es exactamente lo inverso de lo que mató a N-1 farmacovigilancia**, cuyo alcance obligatorio eran superficies propias y por tanto comprables por $1-6/cuenta/mes vía Zernio. Aquí la superficie obligatoria es la **no comprable**. Pasa E-FOSO por el mejor motivo posible. |
| **"Periódicamente" es una obligación recurrente** | No es una auditoría puntual: es vigilancia continua, escrita en la recomendación del regulador. Convierte el scheduler de deuda técnica en **el requisito funcional del producto**. |
| **No necesita visión, ni embeddings, ni logos, ni GPU** | Es texto: comentarios. Evita las tres capacidades ausentes que lastran F1, F4 y F5. |

**Adyacencia: MEDIA, y verificada contra disco — con un hueco preciso que hay que nombrar.**

Lo que **sí** existe y se reusa tal cual:
- `packages/models/src/qualify_models/social/ig_comments.py` — `parse_comments_payload`, `analyze_comment`, `analyze_comments`, `CommentSentimentSummary` con `negative_share`, y procedencia
- El scraper Zyte + parsers de TikTok/IG (`packages/scraper/`), que es el activo de adquisición de earned media

Lo que **no** existe, y es el hueco entero:
- **`ig_comments.py` es para cuentas CONECTADAS** — su propio docstring lo dice: *"a connected account"*. Consume un payload del Graph API de una cuenta propia. **No sirve para leer comentarios del post de un tercero.**
- **El scraper NO extrae cuerpos de comentarios.** Verificado: la única aparición de `comment` en `packages/scraper/src/qualify_scraper/` es `schemas.py:66 → comments_count: int = 0`. **Tenemos el número de comentarios, no lo que dicen.**

> **El hueco, dicho con precisión: la mitad de ANÁLISIS de comentarios está construida y es reusable; la mitad de ADQUISICIÓN para posts de terceros no existe.** Es trabajo en el scraper —que existe y funciona— no una capacidad nueva de modelo. Es el hueco más acotado y mejor definido de todo el documento.

**Falsador.** Que la recomendación de la SIC sea *"recomienda"* y no *"exige"*, y que por tanto ninguna marca colombiana destine presupuesto a cumplirla. **Una recomendación regulatoria sin sanción asociada no crea demanda** — y el caso Grupo Cossio sanciona publicidad engañosa, **no** el incumplimiento de esta recomendación concreta de monitorización. **Ésta es la debilidad real de F6 y no la maquillo.**

**Validación más barata.** Leer la resolución 20777 y comprobar si la falta de monitorización de comentarios figura entre los fundamentos de la sanción, o si es solo publicidad engañosa. **Un documento, una tarde, y decide si F6 tiene motor económico o es una recomendación decorativa.**

### 7.3 — F1 se endurece: no es "¿hay disclosure?" sino "¿dónde y cuánto tiempo?"

`gtm` precisa que el estándar FTC 2023 depende de **dónde** aparece el texto en pantalla y **cuánto tiempo** permanece — un disclosure pequeño en una esquina mostrado brevemente puede no cumplir, y una mención solo verbal puede no bastar.

**Corrijo mi propia estimación de §4-F1, al alza en dificultad.** Dije que el hueco era "OCR sobre frames, commodity comprable". Es insuficiente: hace falta
- **posición** del texto en el frame (no solo su existencia),
- **persistencia temporal** a través de frames consecutivos (cuántos segundos),
- y por tanto **muestreo de frames a cadencia conocida**, no un frame representativo.

`run_filter` opera sobre `image_path` — **un frame suelto** (`cascade.py:37`). Medir duración exige una pasada temporal que la cascada actual no tiene. **F1 baja de MEDIA a MEDIA-BAJA** y su hueco es "OCR + tracking temporal", no "OCR".

Nota compensatoria, y es lo que salva a F1 de caer más: **eso mismo la hace más difícil de replicar.** Es la única feature del documento que **no es derivable de caption, hashtag ni métricas de engagement** — hay que ver el video y saber qué había en pantalla y durante cuánto. Es trabajo de cascada de visión, no de clasificador de texto, y refuerza el argumento de §3.3 de que el output es un hecho verificable y no un juicio.

### 7.4 — Ranking de tesis actualizado

| Orden | Tesis | Cambio | Motivo |
|---|---|---|---|
| **1** | **F2 — Expediente con procedencia al segundo** | sin cambio | Sigue siendo la más cercana a disco y la única que paga aunque el nicho caiga |
| **2** | **F6 — Monitorización de comentarios en posts de influencers** ⬆ **NUEVA** | entra directa al 2 | **El regulador escribió la especificación**; es earned media (pasa E-FOSO por el mejor motivo); no necesita visión/embeddings/GPU; el hueco es acotado (adquisición en el scraper). **Su falsador —"recomienda" ≠ "exige"— se resuelve leyendo un documento** |
| **3** | F1 — Auditoría de disclosure en tres modalidades | ⬇ del 2 | Sigue viva y sigue apoyada en norma escrita, pero **más difícil de lo que estimé** (§7.3) y su falsador competitivo sigue sin resolver |
| 4 | F4 — Priorización de cola de revisión | sin cambio | Cara de construir, baratísima de refutar |

**Lo que no cambia, y es lo mismo que en cada ronda de esta sesión:** cero compradores entrevistados. Las tres validaciones más baratas del documento —los 20 posts de §5-Tesis-2, la resolución 20777 de §7.2, y la pregunta de volumen de §5-Tesis-3— **son horas de trabajo, ninguna requiere código, y las tres pueden matar su tesis.** Ese es el siguiente trabajo, no más análisis.

---

## 8. El benchmark de `gtm` cierra la pregunta que le pasé — y la respuesta reordena el nicho entero

Tres consecuencias, y la primera es una **corrección contra mi propia tesis #1**.

### 8.1 — Corrijo F2: pierde su afirmación de diferenciación (no su valor)

En la tabla de §4 escribí, en la columna *"¿Competidor ya lo hace?"* para F2: **«No lo describe ninguno»**. **Es falso.** `gtm` verificó que Compliverity ofrece *"audit-ready **timestamped** reports for every video"*, además de lotes de 50+ videos en <5 min. **Eso es exactamente el expediente con marca de tiempo que F2 propone.**

**Lo que NO cambia, y es la razón por la que F2 sigue en el puesto 1:** su justificación nunca fue competitiva. Lo escribí así en §5 y se sostiene entero: *"es la única tesis que no depende de resolver §2. No compite en detección: mejora la evidencia. Se puede construir aunque el hueco de mercado resulte inexistente, porque también es deuda técnica que cualquier otra feature de este nicho necesita."*

**F2 sobrevive como deuda técnica interna con retorno garantizado; muere como argumento de venta.** Son cosas distintas y las estaba mezclando en una sola fila. Corregido.

### 8.2 — 🔴 La tijera: el caso fácil es commodity, el caso difícil es invendible

`gtm` aportó la mejor evidencia del nicho, y **no es marketing de vendor** — es trabajo revisado por pares: *"Evaluating LLM-Generated Legal Explanations for Regulatory Compliance in Social Media Influencer Marketing"*, [arXiv 2510.08111](https://arxiv.org/abs/2510.08111) / [ACL NLLP 2025](https://aclanthology.org/2025.nllp-1.12/). Tier `[V]` — referencia verificada, **paper no leído íntegro** por ninguno de los dos.

1.143 posts de Instagram, GPT vs Gemini, niveles de conocimiento legal controlados:

- **Clasificación patrocinado / no patrocinado: F1 hasta 0,93.**
- **Pero** *"el rendimiento cae significativamente en casos ambiguos"*, y **los anuncios encubiertos son la peor clase con 28,57% de fallo**.

**Esto responde mi pregunta reformulándola, que es mejor que responderla.** No es *"¿keywords o semántica?"*. Es que la tarea se parte en dos mitades con economías opuestas:

| Mitad | Estado del arte | Consecuencia comercial |
|---|---|---|
| **Caso fácil** (el disclosure está o no está, sin ambigüedad) | **Resuelto, F1 0,93, con un LLM genérico y prompting** | **Es capacidad de mercado, no foso de nadie.** Nadie paga una prima por lo que un LLM genérico hace bien |
| **Caso difícil** (ambiguo, anuncio encubierto) | **~28% de fallo, el mejor número público** | **No se puede vender como garantía.** En compliance un falso negativo es una multa |

> **La tijera: el valor está en una banda que o es gratis o es imposible.** El caso fácil no sostiene precio porque cualquiera lo hace; el caso difícil no sostiene promesa porque nadie lo hace lo bastante bien. **Es la misma forma que la tijera que mató a farmacovigilancia en §8.2 del doc de screening** —allí la superficie obligatoria era la comprable y la defendible no era obligatoria— y me preocupa reconocerla dos veces en dos nichos consecutivos.

**Consecuencia inmediata para F3 (detección semántica de paráfrasis): degradada a marginal.** Mi hipótesis era que los vendors usan keywords y la paráfrasis se les escapa. El benchmark sugiere que **la paráfrasis simple ya la resuelve un LLM genérico a 0,93**, así que el delta que imaginaba probablemente no existe. Lo que queda sin resolver es el caso encubierto, donde el estado del arte falla 1 de cada 3,5 veces. **F3 baja al último puesto.**

### 8.3 — El régimen de precisión de ADR 21 no mata el nicho: le dicta la forma, y eso tiene precio

`gtm` señala la conexión y tiene razón en que es de campo. Lo que sigue es la lectura de producto, que sí me corresponde.

`CLAUDE.md:226` `[P]`, verificado en disco hoy:

> *"**assisted** replies (draft + human approval). **Autonomous** replies stay permanently out — a precision problem (65% precision = 1 in 3 drafts wrong), not a phase problem."*

Un detector que falla ~28% en el caso difícil está **en ese mismo régimen** — y aquí un falso negativo es una multa, no un DM incómodo. Pero el principio de ADR 21 **no dice "no construyas cosas imprecisas"**: dice *no construyas cosas imprecisas **autónomas**; asistidas sí*. Aplicado literalmente:

- ❌ **Veredicto autónomo de cumplimiento** («este video es conforme») — **descartado por principio ya firmado**, no por opinión mía. Y es exactamente lo que un comprador de compliance querría comprar.
- ✅ **Flujo asistido** (marcar, priorizar, mostrar evidencia al revisor humano) — es el patrón que ADR 21 bendice explícitamente.

**Y esto valida retroactivamente la reformulación de F4** que hice en §4 antes de conocer el benchmark: convertí «lookalike de infractores» en «priorización de cola de revisión» precisamente porque un falso positivo en compliance acusa a alguien. **Resulta que ése no era un ajuste prudente sino la única forma admisible bajo un ADR ya firmado.** F4 sube.

**El precio de la forma asistida, y es el hallazgo comercial de esta sección:**

> Si el producto es *"ayudamos a tu revisor a mirar más rápido"* y no *"garantizamos tu cumplimiento"*, entonces es una **herramienta de productividad**, no un **seguro**. Y se paga contra el **coste del revisor**, no contra el **tamaño de la multa**.

Eso desmonta el argumento que hacía atractivo al nicho entero. En §7.1 escribí que una multa de ~$190-200k reordena el cálculo del comprador frente al techo de $50-185/mes. **Ese razonamiento solo funciona si vendes seguro.** Vendiendo productividad, el ancla vuelve a ser el salario del revisor, y **el techo de precio LATAM vuelve a la mesa** — el mismo que hundió al inmobiliario. `[H]`: no he medido cuánto cuesta un revisor de compliance en Colombia; **es exactamente la cifra que decide el nicho y no la voy a inventar.**

### 8.4 — Ranking final, con la tijera y el régimen ADR 21 aplicados

| Orden | Tesis | Cambio | Motivo |
|---|---|---|---|
| **1** | **F2 — Expediente con procedencia al segundo** | se mantiene, **con la justificación corregida** | Ya no por diferenciación (§8.1 la refuta) sino porque es **deuda técnica con retorno garantizado**: la necesitan F1, F4 y F6, y se paga aunque el nicho caiga entero |
| **2** | **F6 — Comentarios en posts de influencers** | sin cambio | **La menos tocada por la tijera de §8.2**, porque no es un problema de veredicto legal sino de *adquirir y resumir* texto de terceros. Sigue siendo earned media, sigue sin necesitar visión. Su falsador («recomienda» ≠ «exige») sigue siendo el más barato de resolver del documento |
| **3** | **F4 — Priorización de cola de revisión** | ⬆ del 4 | **Sube porque el régimen ADR 21 la convierte de opción prudente en la única forma admisible.** Un producto asistido es el único compatible con un 28% de fallo en el caso difícil |
| **4** | F1 — Auditoría de disclosure en tres modalidades | ⬇ del 3 | Sigue apoyada en norma escrita, pero acumula tres golpes: Compliverity cubre frame+logo+timestamps, necesita OCR **más** tracking temporal (§7.3), y su mitad fácil es commodity a 0,93 |
| 5 | F3 — Detección semántica de paráfrasis | ⬇ al último | El benchmark sugiere que el delta que suponía **no existe**: la paráfrasis simple ya sale a 0,93 con un LLM genérico |

### 8.5 — Lo que ahora decide el nicho, y no es una pregunta de tecnología

Tras dos rondas de refutación, **ninguna pregunta técnica sigue abierta como bloqueante.** Las dos que deciden son comerciales y ambas son baratas:

1. **¿Cuánto cuesta un revisor de compliance en Colombia?** Es el ancla de precio real bajo la forma asistida (§8.3). Sin ella, la disposición a pagar es especulación.
2. **¿Sanciona la Resolución 20777 la falta de monitorización, o solo la publicidad engañosa?** (§7.2) Decide si F6 tiene motor económico.

**Recomendación:** ninguna de las dos se resuelve escribiendo más documento. **Congelar el análisis aquí**, igual que en la pasada de screening y por la misma razón — con el añadido de que ahora el patrón está diagnosticado dos veces en dos nichos, así que repetirlo sería deliberado.

> **Las dos preguntas de §8.5 fueron respondidas por `gtm` el mismo día. Las dos van en contra del nicho. Ver §9, que es la conclusión del documento.**

---

## 9. Conclusión — **recomiendo DECLINAR el nicho #1 como mercado**, y quedarse con una sola pieza de ingeniería

Las dos preguntas comerciales que quedaban abiertas se cerraron, y **ninguna de las dos sobrevive a favor**. Esta sección es el entregable final.

### 9.1 — La demanda regulatoria no está demostrada: el caso colombiano es de PRIMERA PARTE

`gtm` fue a mirar la Resolución 20777 y **su hallazgo debilita su propio titular**, que es lo que le da peso:

- El sancionado es **GRUPO COSSIO S.A.S.**, y el influencer **es dueño de la empresa sancionada** `[V]`.
- El fundamento es **publicidad engañosa en anuncios propios**: que el curso te hacía rico en cinco meses y recuperabas la inversión con el primer video. La SIC valoró frases como *"tapados en seguidores, en plata"* y las consideró **promesas objetivas que inducen a error**, no exageración retórica `[S]`.
- **Ninguna fuente muestra que la resolución se apoye en un deber de vigilar contenido de terceros.** `[H]` — cerrarlo del todo exige el texto íntegro.

> **El caso insignia colombiano es OWNED media: una empresa multada por su propia publicidad, donde anunciante e influencer son la misma persona. No es precedente de "marca multada por no vigilar a su afiliado".**

**Esto golpea a F6 en su motor económico, que era su único punto débil declarado.** El falsador que escribí en §7.2 era exactamente *"que la SIC recomiende y no exija, y que ninguna marca destine presupuesto"*. La respuesta es que **no hay enforcement demostrado del deber de monitorización**. La *guía* de la SIC y la Ley 1480 siguen existiendo; lo que no existe es la prueba de que incumplir la recomendación cueste dinero. **Una obligación sin sanción observada no crea presupuesto**, y todo el atractivo del nicho descansaba en que el gasto fuera defensivo y no discrecional.

### 9.2 — El ancla de precio real es un orden de magnitud menor que la que hacía atractivo al nicho

`[S]` Revisor de compliance en Colombia: **US$700–1.375/mes bruto** (COP 2,8–5,5M, Talent.com + Indeed + dos ofertas vivas de 2026); **~US$1.000–2.000/mes de coste empresa** con prestaciones (`[H]`, el factor de carga es supuesto de `gtm`, sin verificar).

Aplicando la forma asistida de §8.3 —que es la única admisible bajo ADR 21— la aritmética se cierra sola:

| Magnitud | Valor |
|---|---|
| Coste empresa de un revisor | ~US$1.000–2.000/mes |
| Valor de ahorrarle un 30% | **~US$300–600/mes** |
| Captura realista (fracción de eso) | **decenas a bajos cientos de USD/mes** |
| La cifra que hacía atractivo el nicho (§7.1) | **~US$190.000–200.000** (multa) |

**Y el cruce que lo remata, aportado por `gtm`:** a precio de lista de CreatorScore, un roster de 200 creators cuesta **~US$1.798/mes — más que el coste totalmente cargado del revisor colombiano al que asistiría.** **A precios de lista estadounidenses, la herramienta cuesta más que la persona.**

Esto confirma lo que escribí en §8.3 como hipótesis y ahora tiene números: **el techo de precio LATAM vuelve, y esta vez por una vía distinta a la del inmobiliario.** Allí el comprador no estaba en el mercado de productos de información. Aquí sí lo está, pero **la forma de producto que la precisión permite (productividad) no puede anclarse en la cifra que hacía interesante al comprador (la multa)**.

### 9.3 — La tijera, en su versión final y peor

`gtm` afila §8.2 de una manera que la empeora sustancialmente, y es correcta:

> **La mitad gratis es precisamente donde el enforcement está demostrado.**

El caso Cossio es exactamente el tipo de afirmación **llana, objetiva y sin ambigüedad** que un LLM genérico clasifica a **F1 0,93**. La banda difícil del **28,57% de fallo** es donde **no existe precedente sancionador** *y* **nadie rinde bien**.

**Las dos mitades están desalineadas con la demanda además de con la capacidad:**

| | Capacidad | Enforcement demostrado | Vendible |
|---|---|---|---|
| **Caso fácil** | resuelto (0,93, LLM genérico) | **sí** (Cossio) | **no** — commodity, nadie paga prima |
| **Caso difícil** | ~28% de fallo | **no encontrado** | **no** — ni como garantía ni como demanda probada |

No hay celda donde capacidad, demanda y vendibilidad coincidan. **Eso no es un nicho difícil: es un nicho sin cuadrante.**

### 9.4 — Recomendación

**DECLINAR el nicho #1 como mercado.** Y lo digo entendiendo que el fundador lo eligió, que dos agentes hemos pasado un día en él, y que decir esto es el motivo por el que existe este rol.

Balance de lo que quedó en pie tras dos rondas de refutación mutua:

| Afirmación que sostenía el nicho | Estado final |
|---|---|
| "El claim hablado es el punto ciego del listening de texto" | ❌ refutado (§2) — cuatro vendors hacen video |
| "Ningún vendor cubre el eje frame/logo/timestamps" | ❌ refutado — Compliverity los cubre, y **hace más que nosotros** |
| "El regulador escribió la especificación" (F6) | ⚠ la escribió como **recomendación sin sanción demostrada** (§9.1) |
| "El presupuesto de compliance rompe el techo de precio" | ❌ solo si vendes seguro, y **ADR 21 prohíbe vender seguro** (§8.3) |
| "La multa de ~$190-200k reordena el cálculo del comprador" | ❌ es un caso de primera parte; y el ancla real es el salario del revisor (§9.2) |

**Lo único que sobrevive, y hay que construirlo igual: F2 (timestamps + expediente con procedencia).** Tres archivos —ampliar el `Protocol` de `transcribe()`, dejar de descartar los segmentos que Whisper ya devuelve, añadirlos a `TranscriptionResult`— sin modelo nuevo y sin GPU, y de paso arregla que `language` devuelva `None` literal. **Su justificación es deuda técnica interna con retorno garantizado, no este mercado** (§8.1), así que **sobrevive precisamente porque nunca dependió del nicho.** Es el único item que pasa a manos del product-owner.

### 9.5 — Qué tendría que ser cierto para reabrirlo

Registro las condiciones de reversión, porque un descarte sin ellas es un prejuicio y no una conclusión. Cualquiera de estas lo reabre:

1. **Aparece una resolución de la SIC (o de la FTC) que sancione a una marca por NO vigilar a un tercero.** Convierte la recomendación en obligación con precio y restaura el motor económico de F6.
2. **El comprador deja de ser la marca y pasa a ser la agencia.** Una agencia amortiza la herramienta entre N clientes, lo que rompe la aritmética de §9.2 — que es una comparación contra **un** revisor. Esto es literalmente el candidato **B-5 del doc de screening (puesto 2)** y **no está investigado**. Es la reapertura más plausible de las cinco.
3. **El caso difícil deja de fallar un 28%.** Cambia el régimen ADR 21 y vuelve a permitir vender garantía en vez de productividad.
4. **Se demuestra que los vendores anglófonos rinden mal en español.** Sigue sin medirse; `gtm` lo dejó abierto y es la única ventaja no refutada que queda.
5. **El comprador resulta ser estadounidense y no colombiano.** Sube el ancla de precio, pero exige competir de frente con Compliverity/Sedric/PerformLine **con menos capacidad construida que ellos** — así que reabre el mercado y empeora la posición a la vez.

### 9.6 — Nota de método, porque es el activo más transferible de esta sesión

Este nicho no murió por falta de investigación: **murió porque tres preguntas concretas se hicieron antes de construir nada.** Cada una costó horas y cada una mató una capa:

1. *¿Algún vendor analiza video?* → refutó la premisa (§2)
2. *¿El caso insignia sanciona lo que creemos?* → refutó la demanda (§9.1)
3. *¿Cuánto cuesta la persona a la que sustituimos?* → refutó el precio (§9.2)

Ninguna requirió código, entrevistas ni acceso especial. **El coste total de declinar este nicho fue de un día; el coste de descubrirlo construyendo habría sido de meses.** Y las tres se hicieron porque el lead exigió verificar la capacidad concreta antes de que nada dependiera de ella — **ninguno de los dos analistas eligió ese encuadre por sí mismo**, cosa que conviene recordar la próxima vez.
