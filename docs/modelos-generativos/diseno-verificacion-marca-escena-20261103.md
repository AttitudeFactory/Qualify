# Diseño: verificación de marca en la escena — logos y recursos ajenos → los nuestros (2026-11-03)

**Tipo:** diseño de arquitectura, solo lectura. Sin cambios de código, sin llamadas pagas, sin commits.
**Autor:** principal-architect. **Estado:** `[PROPUESTO]` — espera la decisión del fundador (§12).
**Pedido del fundador:** «el verificado de los logos y recursos de marca para poner los nuestros».
**Parte de:** m-24820842 (recursos de marca en imágenes y videos). Continúa el §6 de
[`analisis-ubicacion-logo-draft-fb2d9a5c-20261102.md`](analisis-ubicacion-logo-draft-fb2d9a5c-20261102.md)
(propuestas M1–M7 y la idea del mapa de superficies).

Niveles de evidencia: **[V]** leído en el código, en la tabla de precios o medido; **[H]** hipótesis o
estimación; «calculado» = aritmética sobre precios [V] con supuestos [H] declarados.

## Resumen

1. **Tres piezas, separadas a propósito:** (L) una **lectura** de la escena de referencia que lista
   cada superficie con marca ajena (vaso, caja, papel de bandeja, letrero, textos sobrepuestos,
   colores), **independiente de nuestra marca** y por eso guardable una vez por reel o por guía;
   (A) una **asignación determinista** de cada superficie a un recurso del Brand Kit (logo y su rol,
   paleta, tipografía) por pieza, sin llamada paga; (V) una **verificación** opcional de la salida
   que avisa al dueño si quedó marca ajena. Nunca regenera sola.
2. **Dónde corre:** en el trabajo de generación (creative-worker / hilo de `InlineDispatcher`),
   como paso durable de ADR 41, **antes del selector de recursos y antes de pagar Seedance o
   Seedream**, detrás de la misma guarda de precio (`self._run` con `BudgetContext`). Nunca en la
   petición web. Opcionalmente se adelanta al tocar «Replicar» para que esté lista al generar.
3. **Modelo recomendado: Claude Sonnet 5.5** (proveedor ya contratado, ya recibe imágenes en el
   selector, USD 2/10 por millón [V `pricing_data/v7.json`]). Haiku 5.5 como candidato para la
   verificación si pasa la medición; Seed 2.0 Lite (BytePlus) solo como retador en la medición, con
   la firma del fundador.
4. **Costo calculado:** lectura de un reel ≈ **USD 0,034** (una vez; las regeneraciones la
   reutilizan), verificación ≈ **USD 0,02 por clip**; frente a USD 0,597 de un borrador Seedance 2.5
   de 5 s [V], la primera generación sube ~9 % y cada regeneración ~3 %. Imagen con guía: lectura
   ≈ USD 0,013 + verificación ≈ USD 0,01, **solo si la guía tiene marcas ajenas**.
5. **No rompe los guardas de «sin pérdida de calidad»:** el bloque de superficies es aditivo,
   todo o nada; si no cabe (Seedream, 2 950 caracteres) o falta el mapa, se compila **exactamente
   el texto de hoy**. El texto ajeno leído (p. ej. «…ubbies») **nunca** viaja al generador: se
   nombra la superficie, no la palabra (evita que el modelo la vuelva a pintar y corta la inyección
   de instrucciones desde un letrero).
6. **Falla hacia lo de hoy:** cualquier error, demora o salida inválida deja el mapa vacío y la
   pieza se genera como hoy; el dueño nunca ve un error por este paso.
7. **Medición antes de activar:** golden set pequeño de réplicas de Nibbles Burger + guías de
   Inspiración, etiquetado a mano; ≈ USD 2–5 para elegir modelo y umbrales; el A/B con Seedance
   (≈ USD 10–15, brazo C del análisis del 2026-11-02) necesita su OK.

## 1. Qué existe hoy (punto de partida) [V]

| Pieza | Dónde | Qué hace / qué le falta |
|---|---|---|
| Selector semántico de recursos | `qualify_api/creative/resource_selection.py` (`SELECTION_VERSION = 2`), llamado por `MediaProducer._select_resources` en `creative/media.py` | Claude elige qué logos y fotos viajan y si el logo va integrado o como firma (`ResourcePlan.logo_placement`). **Ve un solo cuadro del reel** (el primero, a 768 px) y **no devuelve dónde** va cada logo. Costo medido USD 0,033 por pieza |
| Compilador v1 del clip en modo edición | `media._brand_applied_reel_edit_lines_v1` (`PROMPT_COMPILER_VERSION = 1`) | Una línea genérica: «Replace EVERY source-owner name/logo/graphic on existing cups, fries cartons, tray paper, wrappers and signs with the supplied client logo». Lista de clases, no de superficies reales; una sola variante de logo para todo |
| Compilador de imágenes con guía | `media.ad_scene_prompt` (rol `composition`; las guías de «Inspiración» son stock con `/stock/` en la clave) | «composition guide ONLY … never copy foreign branding». Nadie sabe qué marcas trae la guía. Presupuesto de **2 950 caracteres** (`MEDIA_PROMPT_BUDGET`) |
| Guardas de calidad | `packages/api/tests/prompt_quality.py` | Comprueban sobre el texto final: palabras del operador, producto, cada recurso con índice/alias/rol/nota, paleta, tipografías, identidad entera, cobertura de la guía de réplica, sin frases duplicadas, nada recortado, ≤ 1 000 palabras en Seedance 2.x |
| Análisis del reel | `referentes/reels_ai.py` (`REPLICATION_ANALYSIS_VERSION = 1`); la guía de réplica v1 dice «no hay análisis VLM» (`prompt_text.REPLICATION_PROSE_V1`) | Solo metadatos (texto, transcripción, formato, gancho). **Ninguna lectura visual** |
| Avisos al dueño | `media.MediaWarning` (`code`, `detail`, `fields`) | Mecanismo existente para «se produjo, pero no como se pidió» |
| Pasos durables | `creative_pipeline_steps` (migración 0098, ADR 41) | Un paso pagado completado no se repite tras una caída |
| Cuadros de video | `MediaProducer._clip_frame`, `_decode_frame` (PyAV) | Ya extrae cuadros sin dependencias nuevas |
| Modelos de visión | Claude (en producción); `packages/models` (`Qwen3-VL-4B`, grupo `ml`, nunca desplegado); investigación `docs/investigacion-vlm-replicar-videos.md` (Seed 2.0 Lite y Gemini, no contratados para esto) | — |

## 2. Flujo y lugar del paso

```
Crear pieza (petición web)  ──► encola la generación (ADR 41)          [sin cambios]
                                     │
creative-worker / hilo Inline        ▼
  copia (Claude) ─► (L) LECTURA DE ESCENA ─► selector v3 ─► (A) ASIGNACIÓN ─► compilador v1
                      │ caché por fuente      (ve el mapa)    determinista      (+ bloque de
                      │ (tenant, sha256,                                         superficies,
                      │  versión lector)                                         todo o nada)
                      ▼                                                               │
               paso durable + guarda de precio                    preflight / Seedance o Seedream
                                                                                      │
                                     (V) VERIFICACIÓN ◄── salida del proveedor ◄──────┘
                                         │
                       pieza lista ◄─────┴─► aviso al dueño si quedó marca ajena (nunca regenera sola)
```

- **(L) Lectura**: se ejecuta solo si la pieza tiene una escena ajena: un clip en modo edición con
  `source_reel` o con un video subido como referencia, o una imagen/galería con una guía de
  composición (stock de «Inspiración» o subida). Antes de llamar, busca en caché por
  `(tenant_id, sha256 del archivo, kind, reader_version)`; si está, **costo cero**. Corre antes del
  selector porque el selector la usa (§5.2) y mucho antes de pagar el video.
- **Adelanto opcional (paso 6 del plan):** al tocar «Replicar» (`Qualify/reel_replication.py::
  import_reference`) se encola la lectura como tarea de fondo; la latencia queda oculta mientras el
  dueño elige producto y opciones. Si no llegó a tiempo, el trabajo de generación la hace él mismo
  (misma clave, `INSERT … ON CONFLICT DO NOTHING`, idempotente).
- **(A) Asignación**: función pura sobre el mapa congelado + los recursos elegidos + el Brand Kit.
  Sin llamada paga; se prueba fuera de línea.
- **(V) Verificación**: después de que el proveedor entrega y **antes** de mostrar la pieza como
  lista; en el borrador, en el final y en cada imagen. Solo corre si la lectura encontró al menos
  una superficie ajena con confianza suficiente (si no hay nada que cambiar, no hay nada que
  verificar).
- **Interruptor:** `QUALIFY_SCENE_BRAND=off|read|read+check` (por defecto `off` hasta pasar la
  medición; luego `read+check`). Lo que no esté encendido compila exactamente como hoy.

## 3. Entradas de la lectura

**Reel (clip en modo edición).** El archivo ya ajustado que guardó `import_reference` (el mismo que
recibe Seedance), no la URL pública: lo que se lee es lo que se edita.

- **Cortes sin dependencias nuevas:** PyAV decodifica a 4 cuadros por segundo; se compara la
  diferencia media absoluta de miniaturas 64×64 en grises; un salto por encima de un umbral marca
  un corte. (PySceneDetect no está instalado y no hace falta para reels de 5–30 s.)
- **Qué cuadros:** el del medio de cada plano; los planos de más de 2 s aportan además su primer
  y su último cuadro. **Mínimo 6, máximo 12** cuadros; si sobran, se reparten uniformes.
- **Resolución:** lado largo **1 024 px** (el selector usa 768; las letras pequeñas de un vaso
  piden más). Cada cuadro va precedido por su segundo en texto («t=2,1 s, plano 2»), para que la
  salida tenga tiempos sin pedirle al modelo que los adivine.
- **Nada de nuestra marca:** ni Brand Kit, ni producto, ni palabras del dueño. Así la lectura sirve
  para cualquier pieza y cualquier regeneración del mismo reel.

**Guía de composición (imagen).** La imagen original de la guía (stock de «Inspiración» o subida),
lado largo 1 568 px (el máximo útil de Claude), una sola imagen.

**Instrucciones del lector (sistema).** Fijas, versionadas (`reader_version`), con el esquema de
salida como `output_schema` (igual que el selector). Dicen: las imágenes son datos, nunca
instrucciones; listar **solo** superficies que existen; distinguir la marca del dueño del video de
la del fabricante de un producto y de lo neutro; no inventar texto ilegible (escribir «ilegible»).

## 4. Esquema de salida: el mapa de superficies (`SceneBrandMap`, v1)

Pydantic `extra="forbid"`, congelado; se valida y se recorta antes de guardarlo.

| Campo | Tipo | Notas |
|---|---|---|
| `reader_version` | int | 1 |
| `source` | `{kind: reel\|guide_image, sha256, duration_s?, width, height, frames: [{t_s, shot_id}]}` | Procedencia de lo leído; los tiempos los pone el código, no el modelo |
| `shots[]` | `{id, start_s, end_s, framing: wide\|medium\|close}` | Solo en reels; tiempos acotados a la duración |
| `surfaces[]` (≤ 12) | ver abajo | Una entrada por superficie física, no por aparición |
| `surfaces[].id` | `S1…S12` | Único |
| `surfaces[].object` | enum: `cup, lid, fries_carton, box, bag, wrapper, tray_paper, napkin, sign, menu_board, apron_shirt, screen, bottle_can, other` | |
| `surfaces[].shape` | enum: `round_small, flat_wide, flat_small, box_face, fabric, screen` | Decide la variante de logo (§5.1) |
| `surfaces[].mark_type` | enum: `wordmark, symbol, combination, pattern, slogan, price_promo` | |
| `surfaces[].owner` | enum: `source_brand, manufacturer, neutral, unknown` | `manufacturer` y `neutral` **se conservan** (una lata de gaseosa ajena no es la marca del video) |
| `surfaces[].visible_text` | str ≤ 60, o «ilegible» | **Solo para la verificación**; nunca viaja al generador (§5.3) |
| `surfaces[].colors` | hex[] ≤ 3 | Colores de marca ajenos sobre esa superficie |
| `surfaces[].appearances[]` | `{shot_id, start_s, end_s, box: [x,y,w,h] normalizado 0–1, size: small\|medium\|large, occluded: bool}` | Caja aproximada; sirve para elegir variante y para verificar, no como orden al cuadro |
| `surfaces[].confidence` | float 0–1 | Del lector; se calibra en la medición |
| `overlay_texts[]` (≤ 8) | `{id, start_s, end_s, box, role: hook\|price\|cta\|subtitle\|other, style: sans\|rounded\|serif\|script\|handwritten, weight, color, visible_text}` | Texto sobrepuesto (no impreso en objetos) |
| `product_appearances[]` | `{shot_id, start_s, end_s}` | Refuerza «reemplazar desde la primera aparición» |
| `dominant_source_colors` | hex[] ≤ 4 | Paleta ajena a sustituir |

**Validación del código** (no del modelo): ids únicos, tiempos dentro de `[0, duración]`, cajas en
`[0,1]`, textos pasados por `visual_text` y recortados, superficie sin apariciones = descartada.
Un mapa inválido cuenta como «sin mapa» (§8), sin reintento pagado salvo un error 5xx.

**El resultado por pieza: el plan de superficies (`SurfacePlan`, determinista).** Una fila por
superficie que se va a tocar:

| Campo | Ejemplo (borrador `fb2d9a5c`) |
|---|---|
| `surface_id` | `S1` (el vaso) |
| `action` | `replace_logo` \| `replace_text` \| `recolor` \| `remove` \| `keep` |
| `resource` | `{asset_key, fingerprint, alias: "@Image4", category: "isotipo", main: false}` o `null` |
| `palette` | los hex del Brand Kit |
| `typeface` | familia del Brand Kit para `replace_text` |
| `confidence` | la del lector |
| `basis` | id de la regla que lo decidió (`R-round-small→isotipo`), para auditar |

## 5. Cómo el mapa se vuelve instrucciones

### 5.1 Asignación (A): superficie → recurso de NUESTRO Brand Kit

Reglas en orden (la primera que aplica gana), sobre los logos que el selector eligió:

| Superficie (`shape` / `mark_type`) | Variante preferida (en orden) | Si no existe |
|---|---|---|
| `round_small` (vaso, tapa, adhesivo) | isotipo → isologo → logo principal reducido al símbolo **solo si** su categoría lo permite | Quitar la marca y dejar la superficie en un color de la paleta |
| `flat_wide` (papel de bandeja, letrero, delantal) | imagotipo → logotipo → principal | principal |
| `box_face` / bolsa / envoltura | isologo → imagotipo → principal | principal |
| `pattern` en cualquier superficie | patrón en colores de la paleta, **sin letras**; un recurso «extra» del Brand Kit solo si su nota de uso lo pide para ese tipo de superficie | Patrón en la paleta |
| `slogan` / `price_promo` impresos | `remove`; con «Usar tus frases» encendido, `replace_text` con una frase aprobada del Brand Kit | `remove` |
| `overlay_texts` | igual que arriba: quitar, o reescribir con frase aprobada en la tipografía y colores del cliente | `remove` |
| `owner` = `manufacturer` / `neutral` | `keep` | — |

- **Umbrales:** `confidence ≥ 0,6` → la superficie se nombra; entre 0,35 y 0,6 → entra en una
  línea «revisa también …» que nombra solo el objeto; `< 0,35` → se ignora. Se recalibran con la
  medición (§10).
- **Nunca** se recorta un isologo ni se deforma un imagotipo para que quepa: si la variante no cabe,
  la regla baja a la siguiente o a `recolor`.
- Las notas de uso que escribió el dueño ganan sobre la tabla (si dice «para vasos», ese logo va
  en los vasos). La tabla es también la nota por defecto por categoría (M3 del análisis previo).

### 5.2 El selector (v3) ve el mapa, no más cuadros

`SELECTION_VERSION = 3`: el `payload` agrega `surfaces` (objeto, forma, tipo de marca, tamaño; **sin**
`visible_text`). Cambios en las reglas del sistema:

- En modo edición puede elegir **hasta dos** variantes de logo cuando el mapa trae superficies
  `round_small` **y** `flat_wide`/`box_face` (es la M4 del análisis previo; hoy «normally choose ONE»).
- `ResourcePlan` no cambia de forma: el «dónde» lo decide (A), que es determinista y verificable. Si
  más adelante se quiere que el selector proponga la asignación, se agrega `surface_logos` validado
  como hoy se validan los índices — no en esta primera versión.
- `validate_plan` agrega una regla: con superficies ajenas de confianza ≥ 0,6 y logos disponibles,
  `logo_placement` no puede ser `signature` por `no_surface` (el mapa prueba que hay superficie).
- El preflight del peor caso (`_preflight_worst_case`) ya mide cada logo solo y todos juntos; con
  dos variantes posibles no cambia.

### 5.3 El texto del video (compilador v1 del clip en modo edición)

En `_brand_applied_reel_edit_lines_v1`, **si y solo si** hay plan de superficies, la línea genérica
«Replace EVERY source-owner …» se sustituye por un bloque corto. Ejemplo para el reel del borrador
`fb2d9a5c` (números de imagen ilustrativos):

```text
Branded surfaces in @Video1 to replace (check every shot where each appears):
- Cup, right of tray, 0-2 s and 3.5-5 s: replace its source wordmark with @Image4 (isotipo).
- Fries carton, center, 0-2 s and 3.5-5 s: remove the printed slogan; put @Image3 (imagotipo) on its front.
- Tray paper, bottom, 0-5 s: client-palette pattern, no source lettering.
Any other source-owner mark not listed: remove it or replace it the same way. No source-owner
marks may remain; keep geometry/perspective/lighting/occlusion and unrelated mandatory labels.
```

- **Nunca se escribe la palabra ajena** (`visible_text`): nombrarla induce al modelo a pintarla y
  abre la puerta a que un letrero del reel dicte instrucciones. Se nombra **objeto, posición gruesa
  (izquierda/centro/derecha, cerca/lejos) y tiempos redondeados a 0,5 s**.
- **Tamaño:** ~15–20 palabras por superficie; 3–5 superficies ≈ 60–100 palabras, que **reemplazan**
  las ~45 de la línea genérica. Texto actual ~325 palabras [V, análisis previo §3.2] → ~380–430,
  lejos del techo de 1 000 de Seedance 2.x. Se sigue sin semilla fija (M7).
- **La última frase del bloque conserva literalmente** el cierre de la línea genérica, así ninguna
  intención de hoy se pierde.

### 5.4 El texto de la imagen con guía (Seedream)

En `ad_scene_prompt`, la línea «composition guide ONLY …» gana, solo con plan, una frase por
superficie de la guía («Image 1 guide, cup at left: client isotipo (Image 4); tray paper: client
palette, no lettering.»). Seedream tiene **2 950 caracteres**: el bloque es **todo o nada** y de
menor prioridad. Si no cabe, se compila sin él (el texto de hoy, byte a byte) y se registra
`scene_brand.applied=false, reason=budget`. Como el preflight mide el texto **sin** el bloque, este
paso **nunca** puede provocar un rechazo por largo.

### 5.5 Versionado y guardas (sin pérdida de calidad)

- `MediaInputs` agrega `scene_brand_map_id`, `scene_brand_map_sha256`, `surface_plan` (congelado) y
  `scene_brand_version`; se fijan al preparar la pieza y la regeneración los reutiliza. Compilar
  dos veces el mismo brief da el mismo texto.
- Sin estos campos (piezas viejas, interruptor apagado, mapa vacío) el compilador produce el texto
  de hoy. `PROMPT_COMPILER_VERSION` sigue en 1: el cambio lo gobierna `scene_brand_version`, igual
  que `resource_plan_version` gobierna el selector.
- `prompt_quality.py` agrega cuatro comprobaciones: (1) cada superficie del plan con
  `action ≠ keep` aparece con su alias y categoría correctos; (2) **ningún** `visible_text` del mapa
  aparece en el texto final; (3) si se quitó la línea genérica, su cierre literal está presente;
  (4) con el bloque descartado por presupuesto, el texto es idéntico al compilado sin mapa.
- La guía de réplica v1 dice «no hay análisis VLM». Esa frase tiene cobertura `None` (nota de
  ingeniería: cuando la guía es la v1 reconocida, no viaja a Seedance), así que **no hace falta
  tocarla para lanzar**. Cuando el paso quede encendido por defecto se publica la v2
  (`REPLICATION_PROSE_V2` + su tabla de cobertura) y `REPLICATION_ANALYSIS_VERSION` sube a 2; la v1
  sigue reconocida para borradores ya guardados.

## 6. Verificación posterior (V), opcional

- **Cuándo:** al terminar el proveedor y antes de marcar la pieza como lista: borrador, final y
  cada imagen. Solo si el plan tenía al menos una superficie con `action ≠ keep`.
- **Entradas:** en un clip, 6 cuadros de la salida **en los mismos segundos** de las apariciones
  del mapa (el modo edición conserva los tiempos), reducidos a 1 024 px; en una imagen, la imagen.
  Además, los logos elegidos en miniatura (para distinguir «cliente» de «origen») y el mapa de
  origen **con** `visible_text` — aquí sí sirve, porque quien lo recibe solo lee, no genera.
- **Salida (`SceneBrandCheck`, v1):** por superficie `status: client | source | plain |
  not_visible` + `confidence`; lista `extra_foreign_marks[]` (marcas ajenas que no estaban en el
  mapa); `verdict: pass | warn`.
- **Regla de aviso:** `warn` si alguna superficie queda `source` con confianza ≥ 0,6 (umbral
  calibrado para **no molestar**: un aviso falso enseña al dueño a ignorarlos).
- **Qué ve el dueño:** un `MediaWarning` nuevo (`code = "foreign_brand_visible"`) en la revisión de
  la pieza, con la superficie nombrada y la salida de siempre. Borrador de texto, a revisar con
  `qualify-copy-es` y `ux-designer`: «Revisa el vaso: puede que todavía se vea la marca del video
  original. Si es así, pide otra versión.»
- **Lo que nunca hace:** regenerar sola, bloquear la aprobación o cobrar otra vista previa.
  Asistido, nunca autónomo.

## 7. Modelo: opciones y recomendación

| Opción | Costo lectura de reel / verificación de clip (calculado) | A favor | En contra |
|---|---|---|---|
| **A. Claude Sonnet 5.5, llamada propia** (recomendada) | ~USD 0,034 / ~0,018 | Proveedor ya contratado, sin DPA nuevo; misma puerta (`self._run`, guarda de precio, `call_cost`, tabla v7); ya recibe imágenes en el selector; salida con esquema | Video en cuadros, no nativo: los tiempos salen del código, no del modelo |
| B. Claude Haiku 5.5 | ~USD 0,002 / ~0,001 | 20 veces más barato; en producción para clasificar | Lectura fina de letras pequeñas **sin medir**: candidato para (V) si pasa la medición |
| C. Dentro de la llamada del selector (Opus 5.5) | ~USD 0,01 adicional por pieza | Una llamada menos | Mezcla lo que no depende de la marca (cacheable) con lo que sí: se paga en **cada** regeneración y no se puede medir aparte. Descartada |
| D. Seed 2.0 Lite en BytePlus ModelArk (`seed-2-0-lite-260428`) | ~USD 0,005–0,015 por reel [S, `investigacion-vlm-replicar-videos.md`] | Mismo proveedor que Seedance; video nativo con tiempos; cuenta y clave ya existen | **Modelo nuevo** sin fila en la tabla de precios ni guarda; los preajustes autorizados ceden datos a BytePlus → la verificación (contenido del cliente) exige endpoint propio; documentación solo en JS; calidad sin medir. Requiere firma del fundador |
| E. `Qwen3-VL-4B` (`packages/models`) | sin precio | Pesos abiertos | Nunca desplegado, sin proveedor estable, runtime nuevo (ADR 31). Descartada |
| F. Gemini 3.8 Flash | ~USD 0,02 por reel de 30 s [S] | Mejor en video según su propio informe | **Proveedor nuevo** y su precio se duplica el 2027-01-01 [S]. Descartada ahora |

**Recomendación:** A para la lectura y la verificación. En la misma medición se prueba B para la
verificación (si cumple, baja el costo de (V) 20 veces). D entra como retador **solo** si el
fundador lo aprueba y si A no alcanza el umbral de recall con letras pequeñas.

### 7.1 Costo por pieza y por cliente (calculado; precios [V] `pricing_data/v7.json`, tokens [H] con la regla ancho × alto / 750)

| Llamada | Tokens de entrada | Salida | Sonnet 5.5 |
|---|---|---|---|
| Lectura de reel: 10 cuadros 576×1 024 (≈ 786 c/u) + instrucciones y esquema ≈ 1 600 | ≈ 9 500 | ≈ 1 500 | **≈ USD 0,034** (12 cuadros: 0,037) |
| Lectura de guía: 1 imagen 882×1 568 (≈ 1 850) + 1 500 | ≈ 3 350 | ≈ 600 | **≈ USD 0,013** |
| Verificación de borrador: 6 cuadros 480×854 (≈ 550 c/u) + logos ≈ 600 + mapa ≈ 800 + instrucciones ≈ 1 000 | ≈ 5 700 | ≈ 500 | **≈ USD 0,016–0,020** |
| Verificación de imagen | ≈ 3 900 | ≈ 400 | **≈ USD 0,012** |

- **Réplica, primer borrador:** 0,034 + 0,018 ≈ **USD 0,052** frente a USD 0,597 de Seedance [V] →
  **+9 %**. Cada regeneración: solo verificación, **+3 %**. El final: < 1 % de su costo.
- **Imagen con guía:** lectura (una vez por guía) + verificación ≈ USD 0,025 frente a USD 0,035 de
  Seedream 5.0 lite [V]: proporcionalmente alto, pequeño en absoluto; con Haiku para (V) baja a
  ≈ USD 0,014, y solo se verifica si la guía trae marcas ajenas.
- **Por cliente y mes** [H: 15 réplicas con 2 borradores y 1 final; 30 imágenes con guía, 30 % con
  marcas ajenas]: 15 × (0,034 + 3 × 0,019) + 30 × 0,013 + 9 × 0,012 ≈ **USD 1,9**. Flota de
  50 negocios ≈ USD 95/mes. Lo que se paga hoy en Seedance por esas 15 réplicas es del orden de
  decenas de dólares: el paso suma **3–4 %** del gasto de generación de una réplica.
- **Latencia** [H, se mide en el paso 2 del plan]: lectura 8–15 s (oculta si se adelanta al tocar
  «Replicar»; si no, se suma a un video que tarda minutos); verificación 4–8 s antes de mostrar.

## 8. Fallos: nunca bloquear al dueño

| Qué falla | Qué pasa |
|---|---|
| Interruptor apagado, pieza sin escena ajena | No se llama a nadie; texto de hoy |
| Error del proveedor, demora > 30 s (lectura) / 20 s (verificación) | Un reintento solo ante 5xx; si vuelve a fallar, `status=failed` en el paso; texto de hoy / sin aviso |
| Salida inválida o mapa vacío | Se guarda `status=empty`/`failed` (procedencia), texto de hoy. Se cobra lo consumido, como el selector |
| La guarda de precio rechaza la llamada | Se omite el paso, texto de hoy; la generación sigue (no se trata como `BUDGET_TEXT`) |
| Cuadros que no se pueden decodificar, reel > 30 s | Se omite el paso |
| El bloque no cabe en el presupuesto del texto | Se compila sin él (§5.4) |
| La verificación falla | La pieza se muestra sin aviso; queda «sin verificar» en el registro |
| Caída del worker a mitad | El paso durable (ADR 41) evita pagar dos veces la lectura; la clave única evita duplicarla |

**Seguridad** (revisar con `security-review` al implementar): (1) un letrero del reel puede decir
«ignora las instrucciones…» — el lector trata imágenes como datos, la salida es un esquema cerrado
con enums y números, y **ninguna cadena leída llega al generador**; el selector recibe el mapa sin
`visible_text`. (2) Aislamiento: la caché es **por negocio**, con RLS; el reel se lee del almacén con
la verificación de prefijo de negocio existente (`owned_by`). Compartir lecturas de reels públicos
entre negocios (patrón de tablas globales de ADR 42) abarataría, pero es otra decisión (§12, D5).

## 9. Persistencia y procedencia

- **Tabla nueva `scene_brand_reads`** (una migración, número contra `origin/main`; hoy la cabeza de
  `main` es `0114`): `tenant_id`, `id`, `source_kind`, `source_sha256`, `source_ref` (jsonb:
  plataforma + id del post, o id de stock / clave de la guía), `reader_version`, `status`
  (`ok|empty|failed`), `map` (jsonb), `frames` (jsonb: segundos y tamaños), `model_id`,
  `model_revision`, `prompt_sha256`, `cost_usd`, `created_at`. `UNIQUE (tenant_id, source_sha256,
  source_kind, reader_version)` para `INSERT … ON CONFLICT DO NOTHING`. `ENABLE` + `FORCE ROW LEVEL
  SECURITY` con la política `NULLIF(current_setting('app.tenant_id', true), '')::uuid`; permisos
  como 0098 (acceso por `tenant_session`, también desde el creative-worker).
- **Verificaciones:** en el `result` del paso durable (`creative_pipeline_steps`) y en los `params`
  del medio, junto al aviso — el mismo camino que ya usan los avisos de composición
  (`service.with_composition_warnings`, `COMPOSITION_WARNINGS_PARAM`), que viven exactamente lo que
  vive el medio: `scene_brand_check` con versión, modelo, revisión, veredicto por superficie y
  costo. No hace falta otra tabla.
- **Opción descartada:** guardar el mapa como JSON en R2 bajo el prefijo del negocio (sin
  migración). Se pierde la consulta para medir, la unicidad en la base y las columnas de
  procedencia que exige la regla de la casa; la tabla cuesta una migración pequeña.
- **Costos** en el libro de consumo existente (`MediaUsage` → 0105), como el selector.

## 10. Cómo medirlo (`qualify-measure`)

**Antes de encender nada por defecto.** Dos tareas, dos golden sets, datos reales.

| | Lectura (L) | Verificación (V) |
|---|---|---|
| Unidad | (fuente, superficie) | (salida, superficie) |
| Fuentes | ~20: todos los reels de origen de réplicas de **Nibbles Burger** que ya hay en local/R2 (incluido el de `fb2d9a5c` y la referencia de 4,8 s de las pruebas v3/v4), reels de comida de «Ideas para tus reels» ya guardados (0 créditos), 6–8 guías de «Inspiración» de comida | ~25–30 salidas ya generadas (las dos revisiones de `fb2d9a5c`, las corridas Nibbles v3/v4 y otros borradores de réplica en la base de desarrollo); **sin generar nada nuevo** |
| Etiqueta (a mano, Deivid o el fundador, planilla de 6–12 cuadros) | lista de superficies con objeto, forma, dueño y planos | por superficie: `client / source / plain / not_visible` |
| Separación | dev 8 / test 12 **por fuente** (nunca cuadros de un mismo reel en los dos) | dev 10 / test 15–20 por salida |
| Métricas | recall de superficies `source_brand` (≥ 0,6 de confianza); superficies inventadas; exactitud de `owner` (confundir la marca del video con un fabricante borra una lata ajena o deja un logo ajeno); exactitud de `shape` (decide la variante) | **recall de «quedó marca de origen»** (lo que se escapa llega publicado); precisión (avisos falsos) |
| Umbral propuesto para encender | recall ≥ 0,85, inventadas ≤ 10 %, `owner` ≥ 0,9 en test | recall ≥ 0,9 con precisión ≥ 0,7 en test |

- **Honestidad:** con 12–20 fuentes los intervalos (Wilson) son anchos; se reportan con el número.
  Sirve para elegir modelo y umbrales y detectar fallos grandes, no para prometer una tasa.
- **Arnés:** `packages/api/evals/scene_brand_ai/` (constructor del dataset con claves de R2 y
  etiquetas, no los archivos; ejecución; puntaje) y `just eval-marca-escena`, en Langfuse
  `qualify-dev` como los demás `eval-*`.
- **Costo de la medición:** lectura 20 fuentes × (Sonnet 0,034 + Haiku 0,002 + Opus ≈ 0,07) ≈
  USD 2,1; verificación 30 × (Sonnet 0,02 + Haiku 0,001) ≈ USD 0,63 → **≈ USD 3, tope USD 5**
  (Seed 2.0 Lite sumaría < USD 0,5, solo con firma).
- **Impacto en el video (lo que importa):** el A/B de §5 del análisis del 2026-11-02 con el brazo
  **C = compilador + plan de superficies**: 2 reels × 4 corridas × 3 brazos ≈ **USD 15**. Métrica
  principal: proporción de pares (clip, superficie) sin marca de origen **y** con logo del cliente;
  la verificación (V), ya medida, sirve de juez con revisión del fundador sobre una muestra.
- **Documentar** cada corrida el mismo día en `docs/modelos-generativos/` (resultado, costo real,
  umbrales elegidos).

## 11. Implementación por pasos

Cada paso es un PR con su ticket (hijo de m-24820842 o uno nuevo, vía `meegle-ticket`). Los pasos 1
y 3 no gastan; el 2 y el 7 necesitan el OK de gasto.

| # | Qué | Archivos | Dueño | Gasto |
|---|---|---|---|---|
| 0 | Texto sin lector: regla de variante por superficie (M1), lista de verificación (M2), notas por defecto por categoría (M3), planos que describen el reel (M5). La tabla de §5.1 se escribe **una vez** y la usan M1 y el paso 4 | `packages/creative/src/qualify_creative/surface_rules.py` (nuevo), `qualify_api/creative/media.py`, `brand_references.py`, `tests/prompt_quality.py` | creative-engineer (coordinar con quien edita `media.py` hoy) | 0 |
| 1 | Núcleo del lector: esquemas `SceneBrandMap`/`SceneBrandCheck`/`SurfacePlan`, instrucciones versionadas, validación y recorte; selección de cuadros con PyAV; petición por la puerta `anthropic` como `selection_request` | `packages/creative/src/qualify_creative/scene_brand.py`, `packages/creative/src/qualify_creative/video/keyframes.py`, `packages/api/src/qualify_api/creative/scene_brand_read.py`; pruebas `packages/creative/tests/test_scene_brand_schema.py`, `test_keyframes.py`, `packages/api/tests/test_scene_brand_read.py` (fuera de línea, con cuadros de prueba) | creative-engineer | 0 |
| 2 | Medición de §10, elección de modelo y umbrales | `packages/api/evals/scene_brand_ai/`, receta `eval-marca-escena` en `justfile`, `docs/modelos-generativos/eval-lectura-marca-escena-<fecha>.md` | data-scientist-fde | ≈ USD 3–5 |
| 3 | Persistencia: migración `scene_brand_reads` con RLS y prueba `-m db` de aislamiento; almacén idempotente | `migrations/postgres/versions/0NNN_scene_brand_reads.py`, `qualify_api/creative/scene_brand_store.py`, `qualify_api/creative/models.py`, `packages/api/tests/test_scene_brand_store_db.py` | backend-engineer (dueño de migraciones) | 0 |
| 4 | Conexión al flujo: paso durable antes del selector, selector v3, asignación pura, bloque en el clip de edición y en la imagen con guía, campos nuevos de `MediaInputs`, guardas nuevas, interruptor | `qualify_api/creative/media.py` (`_select_resources` y su llamador, `_brand_applied_reel_edit_lines_v1`, `ad_scene_prompt`), `resource_selection.py`, `pipeline.py`, `qualify_creative/schemas.py`, `qualify_api/creative/surface_plan.py` (nuevo), `tests/prompt_quality.py`; pruebas `test_surface_plan.py`, `test_reel_edit_surfaces.py`, `test_scene_brand_fallback.py` | creative-engineer | 0 (pruebas sin red) |
| 5 | Verificación (V) y aviso al dueño | `qualify_api/creative/scene_brand_check.py`, `media.py` (código `foreign_brand_visible`), `service.py`; la tarjeta de revisión en `Qualify/` (`content_generator.py` / vista de la pieza); texto con `qualify-copy-es` y revisión de `ux-designer` | creative-engineer + reflex-ui-engineer | 0 |
| 6 | Adelantar la lectura al tocar «Replicar» (opcional) | `Qualify/reel_replication.py`, `Qualify/creative_state.py`, encolado en la cola de ADR 41 | reflex-ui-engineer + creative-engineer | 0 |
| 7 | A/B con Seedance (brazo C) y encendido por defecto; guía de réplica v2 | `docs/modelos-generativos/…`, `prompt_text.py` (`REPLICATION_PROSE_V2`), `reels_ai.py` (`REPLICATION_ANALYSIS_VERSION = 2`), variable de entorno | data-scientist-fde + creative-engineer | ≈ USD 15 |

Orden: 0 ∥ 1 → 2 → 3 → 4 → 5 → 7; el 6 cuando haya cola. El 0 da valor solo y sirve de brazo B.

## 12. Lo que decide el fundador

| # | Decisión | Recomendación | Tipo de puerta |
|---|---|---|---|
| D1 | Encender lectura + verificación con **Claude Sonnet 5.5** tras pasar la medición: ≈ +USD 0,05 en el primer borrador de una réplica, ≈ USD 1,9 por negocio y mes [H]. Sin proveedor nuevo; el dueño no ve dinero | Sí | Dos vías (interruptor) |
| D2 | Gasto de medición: ≈ USD 3–5 (paso 2) y ≈ USD 15 (A/B del paso 7) | Sí | Dos vías |
| D3 | ¿Probar **Seed 2.0 Lite** (BytePlus) como retador? Modelo nuevo en un proveedor existente: fila de precios nueva, endpoint propio para contenido del cliente | Solo si Sonnet no alcanza el recall con letras pequeñas | Dos vías si se queda en la medición |
| D4 | Ante «quedó marca ajena»: **avisar y dejar aprobar** (recomendado) o retener la pieza hasta que el dueño confirme | Avisar | Dos vías |
| D5 | (Más adelante) compartir la lectura de un reel público entre negocios, como las tablas globales de ADR 42 | No ahora | Una vía (datos entre negocios): necesita su propia ADR |

**Qué reabre este diseño:** que la medición muestre recall < 0,85 con Sonnet y Haiku (pasar a D3
o a video nativo); que el A/B no mejore la métrica principal con 2 reels (quedarse con el paso 0 y
la verificación sola); que Seedance acepte máscaras o regiones por referencia (el mapa pasaría a
ser máscara, no texto); o más de unas miles de réplicas al mes (revisar el costo de Sonnet frente
a Haiku o Seed).

## 13. Fila ADR propuesta (para §6 de `docs/arquitectura.md`, al firmar)

Número: el siguiente libre (45 si la ADR 44 de «Video por partes» ya está en `main`).

| # | Decisión | Alternativas descartadas | Razón | Se reabre si |
|---|---|---|---|---|
| 45 | **[PROPUESTO — principal-architect, 2026-11-03; detalle en este documento · m-24820842]** Antes de pagar Seedance o Seedream, una **lectura de marca de la escena** con Claude Sonnet 5.5 lista las superficies con marca ajena del reel o de la guía (guardada por negocio y archivo, con RLS y procedencia); una **asignación determinista** las lleva a los recursos del Brand Kit y el compilador v1 las nombra sin repetir la palabra ajena; una **verificación** de la salida avisa al dueño si quedó marca ajena, sin regenerar sola. Todo fallo vuelve al texto de hoy | Dentro de la llamada del selector; Qwen3-VL-4B; Gemini; Seed 2.0 Lite como primera opción; mapa en R2 sin tabla | Lo que no depende de la marca se paga una vez y se mide aparte; sin proveedor ni runtime nuevos (ADR 31, regla de la casa); la tabla da unicidad y procedencia | Recall < 0,85 en el golden set; el A/B no mejora; Seedance acepta máscaras; > unas miles de réplicas/mes |
