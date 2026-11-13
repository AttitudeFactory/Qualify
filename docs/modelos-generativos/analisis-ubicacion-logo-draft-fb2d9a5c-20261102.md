# Análisis: dónde cae el logo al editar un reel — borrador `fb2d9a5c` (2026-11-02)

**Tipo:** investigación de solo lectura. Sin llamadas pagas, sin cambios de código, sin commits.
**Rama de referencia del compilador actual:** `fix/m-24820842-prompt-budget` (compilador de prompt v1).
**Borrador:** `fb2d9a5c` · negocio `9cd9637c` · marca `a034e7a8` (hamburguesería) · base local de desarrollo.
**Observación del fundador:** en la primera generación el logo quedó en el vaso; en la regeneración solo aparece en la servilleta.
**Estado:** `[PROPUESTO]` — las recomendaciones de §5 y §6 esperan la decisión del fundador.

Niveles de evidencia: **[V]** leído en la base, en R2, en el disco o calculado sobre datos medidos;
**[H]** hipótesis o estimación.

## Resumen

1. **El texto enviado a Seedance fue idéntico en las dos generaciones** [V]: mismo brief, mismo
   Brand Kit (sin cambios desde 2026-10-06), mismos tres logos congelados con la misma huella, mismo
   modelo (`dreamina-seedance-2-5-260628`, modo edición, borrador 480p, 5 s). Lo único distinto fue
   la semilla aleatoria que el proveedor eligió (71963 → 88875). **La diferencia es azar del modelo,
   no una decisión nuestra.**
2. **No hubo selector semántico** [V]: el borrador es anterior a él (manifiesto `block_version 2`,
   sin bloque `selection`). Los tres logos viajaron como referencias, con notas de uso vacías.
3. **El texto no nombra ninguna superficie concreta** [V]: decía «packaging marks» y «box
   geometry»; no mencionaba vaso, caja de papas ni papel de bandeja, ni qué variante del logo va en
   cada una. Además mostraba nombres de archivo que contradicen la categoría
   («isologo.png [logo_version/imagotipo]»).
4. **Lo que se ve en los videos** [V]: en la generación 1 el vaso lleva el símbolo del cliente,
   pero el producto de la referencia no se reemplazó en los primeros planos y el final corta a la
   foto del catálogo. En la regeneración el producto sí se reemplazó en todo el video, pero **no hay
   ninguna marca del cliente**: el vaso conserva la palabra de la marca de origen, y la caja de papas
   y el papel de bandeja conservan sus gráficos y su lema. El modelo «gastó» su edición en una cosa u
   otra según la semilla.
5. **Mejorable ya, con poco riesgo** (§5): convertir la regla genérica en una lista de superficies
   con una variante de logo por tipo de superficie, usar las notas de uso de cada logo, y revisar la
   salida antes de mostrarla. Medirlo cuesta unos USD 5–15 en un A/B pequeño.
6. **El paso VLM: sí, con condiciones** (§6): la mejora clara es saber **qué superficies con marca
   existen en el reel de origen, cuándo y dónde**, y poder **verificar la salida** con la misma
   lectura. Recomiendo hacerlo con Claude (ya en producción, ya ve imágenes en el selector), no con
   `Qwen3-VL-4B-Instruct`: cuesta unos USD 0,01–0,04 por reel frente a USD 0,60 del video.

## 1. Qué hay en la base de datos (leído con `tenant_session`, transacción de solo lectura)

Lectura con `SET TRANSACTION READ ONLY` y reversión al final; scripts fuera del repositorio. [V]

| Dato | Generación 1 (revisión 1) | Regeneración (revisión 2) |
|---|---|---|
| Versión de pieza | `68fe13ae` · 2026-10-30 13:17 UTC | `45a0874b` · 2026-10-30 13:22 UTC |
| Modelo | `dreamina-seedance-2-5-260628` | igual |
| Modo | edición (`reference_mode=edit`), borrador 480p, 9:16, 5 s, sin audio | igual |
| Tarea del proveedor | `cgt-…211529-ntl77` | `cgt-…211940-dfgx3` |
| Semilla (la eligió el proveedor) | 71963 | 88875 |
| Referencias enviadas | 1 video (reel de origen) + 1 foto de producto + 3 logos | igual |
| Logos congelados (huella SHA-256) | `12ab73e9…` imagotipo (principal), `e0ad6bd7…` isotipo, `4a9457d6…` isologo | los mismos, mismas huellas |
| Notas de uso de los logos | vacías en los tres | igual |
| `pipeline_version` | `creative-v1` | igual |
| Costo Seedance | USD 0,596941 | USD 0,596941 |
| Costo del texto (Claude Opus 5.5) | USD 0,060855 | USD 0,019172 (caché) |
| Costo total de la versión | USD 0,657796 | USD 0,616113 |

Lo que **no** existe para este borrador [V]:

- **No hay pasos en `creative_pipeline_steps`** ni `rendered_prompt`: el texto exacto enviado no
  quedó guardado. Lo reconstruí ejecutando, fuera del repositorio, el compilador del commit
  `3db64355` (2026-10-30 09:09 -04:00, cinco minutos antes del borrador; su
  `BRAND_REFERENCE_BLOCK_VERSION = 2` coincide con el `block_version 2` del manifiesto) sobre el
  brief, el Brand Kit y los logos guardados. Las dos reconstrucciones son **idénticas**
  (2 484 caracteres, 348 palabras).
- **No hubo selección semántica de recursos**: el manifiesto no tiene bloque `selection`; el
  brief no tiene `resource_plan_version` ni `brand_application_version`. Los tres logos fueron
  como «principal + alternativos» (`additional_logo`).
- El contador `references.images = 1` del manifiesto engaña: contaba solo fotos de producto; el
  código de esa fecha sí envió las 4 imágenes (producto + 3 logos). El código actual ya registra
  `total_images`.

Lo que **sí** cambió entre generaciones, pero **no llega al video** [V]: Claude reescribió el
texto y los «planos» (en la 1 inventa el logo en el papel, en el empaque y en la bandeja; en la 2,
en la espátula, en el papel de envoltura y en una caja). En modo edición el compilador no usa esos
planos (`reel_edit_prompt` no recibe la copia), así que no influyeron en dónde cayó el logo. Sí
son un problema de coherencia: describen superficies que el reel de origen no tiene.

## 2. Qué se ve en cada salida

Videos descargados de R2 (solo lectura) y del reel de origen guardado localmente; cuadros extraídos
con PyAV a resolución completa (480×854). [V]

**Reel de origen** (5 s, tres planos: bandeja completa → primer plano de la hamburguesa → primer
plano de las papas). Superficies con marca del dueño del video: **vaso** (palabra de la marca +
mascota), **caja de papas** (lema impreso, corazones, banderín con el nombre), **papel de bandeja**
(letras grandes amarillas y azules), y el vaso de nuevo al fondo del primer plano.

| Superficie | Generación 1 | Regeneración |
|---|---|---|
| Vaso | **Símbolo del cliente** (hamburguesa sonriente) y parte de la palabra, bien integrado | **Marca de origen intacta** (palabra legible en todos los planos donde aparece) |
| Caja de papas | Lema y gráficos de origen; nombre de origen deformado al pie | Lema, corazones y banderín de origen intactos |
| Papel de bandeja | Letras amarillas/azules de origen | Letras amarillas/azules de origen |
| Fondo del primer plano | Un letrero con la palabra del cliente (parcial) | Vaso de origen |
| Producto | **No reemplazado** en los planos 1–2 (sigue la hamburguesa de origen); el último segundo **corta a la foto del catálogo** sostenida en la mano | **Reemplazado** desde el primer cuadro y consistente (triple carne, como la foto) |

Sobre «la servilleta»: en la regeneración guardada **no encontré ninguna marca del cliente** (revisé
los 113 cuadros con muestreo y un barrido de color). Lo más parecido a un logo en papel es la
ilustración propia de la caja de papas de origen (un corazón con cara). Si el fundador vio el logo
en otra pantalla o en otro segundo, conviene que señale el segundo exacto. [V sobre el archivo
guardado `r2/clip.mp4`, que es también la vista previa activa del borrador]

**Lectura** [H, n = 2]: con el mismo texto, una semilla aplicó la marca y no el producto; la otra,
el producto y no la marca. El modelo de edición no hace todos los cambios pedidos a la vez y el
texto no le da una lista verificable de qué debe cambiar en cada superficie.

## 3. Cómo el compilador nombra y elige hoy las superficies del logo

### 3.1 Lo que se envió el 2026-10-30 (compilador de `3db64355`, rama «logos adicionales») [V]

- Regla del logo: usar el logo principal `@Image2` para reemplazar «source-video-owner packaging
  marks», preservar «box geometry/perspective», ninguna marca de origen puede quedar, una marca de
  agua en la esquina no cuenta.
- **No nombra superficies**: ni vaso, ni caja de papas, ni papel de bandeja.
- Bloque de referencias compacto: `Image 2: isologo.png [logo_version/imagotipo]`,
  `Image 3: imagotipo.png [logo_version/isotipo]`, `Image 4: <archivo>.jpg [logo_version/isologo]`,
  cada uno con «Usage: preserve identity». **El nombre de archivo contradice la categoría** en dos de
  tres (las categorías son correctas al ver las imágenes: horizontal = imagotipo, símbolo solo =
  isotipo, apilado sobre fondo rojo = isologo).
- «Other chosen logo variants follow their notes»: las notas estaban vacías, así que las variantes
  2 y 3 no tenían ninguna indicación de dónde ir.
- La auditoría del mismo día (`auditoria-m24820842-integracion-predeterminada.md`) ya había
  señalado que esta rama compacta debilitó «reemplazar el producto en todas las acciones» y «no
  cortar a una foto del catálogo»; la generación 1 muestra exactamente ese fallo.

### 3.2 Lo que enviaría hoy el compilador v1 (rama `fix/m-24820842-prompt-budget`) [V]

Simulé, sin llamar a nadie, el compilador actual con los mismos datos, la selección semántica
eligiendo solo el imagotipo principal (lo normal del selector) y las versiones actuales
(`resource_plan_version 2`, `brand_application_version 2`, `prompt_compiler_version 1`,
instrucciones v9): **2 419 caracteres, 325 palabras**; con los tres logos, 344 palabras. Seedance
2.x no tiene tope de caracteres desde el compilador v1; el techo es 1 000 palabras.

Lo que mejoró respecto de 3.1:

- Nombra **clases** de superficie: «Replace EVERY source-owner name/logo/graphic on existing cups,
  fries cartons, tray paper, wrappers and signs with the supplied client logo».
- Usa alias tipados («principal imagotipo») y «Categories override filenames»: la contradicción
  del nombre de archivo ya no llega al modelo.
- Recupera «replace product from first appearance» y prohíbe inventar planos o un final nuevo.

Lo que sigue faltando:

1. **La lista es genérica**: no sabe qué superficies existen en *este* reel, en qué plano ni cuándo.
   El modelo no tiene forma de saber que hay tres superficies que revisar.
2. **Una sola variante para todo**: «with the supplied client logo». Un imagotipo horizontal no cabe
   bien en un vaso a 480p; el isotipo cuadrado sí. No hay regla «tipo de superficie → variante».
3. **Las notas de uso no se usan** porque nadie las escribe (vacías en los tres logos de esta marca)
   y no hay una nota por defecto por categoría.
4. **El selector ve un solo cuadro** del reel (el primero, a 768 px) y solo devuelve qué logos y si
   van integrados o como firma (`ResourcePlan.logo_placement`); no devuelve dónde.
5. **Nadie revisa la salida**: la regeneración que dejó la marca de origen intacta se mostró como
   pieza lista para aprobar.
6. **La semilla no se controla**: el adaptador trata `seed` como parámetro de la familia 1.x y no lo
   envía a 2.x; la semilla guardada es la que eligió el proveedor.

## 4. Qué cambió entre la generación 1 y la regeneración

| Hipótesis | Veredicto | Evidencia |
|---|---|---|
| El selector eligió otro logo u otro rol | **Descartado** | No hubo selector; logos, roles, categorías y huellas idénticos [V] |
| Cambió el texto sobre superficies | **Descartado** | Prompt reconstruido idéntico en ambas; Brand Kit sin cambios desde 2026-10-06 [V] |
| Cambió el modelo o sus parámetros | **Descartado** | Mismo modelo, modo, resolución, duración, referencias [V] |
| Cambió la semilla | **Sí** — 71963 → 88875, elegida por el proveedor | [V] |
| Los planos de Claude movieron el logo | **Descartado** | En modo edición no se envían a Seedance [V] |
| **Azar del modelo sobre un texto poco específico** | **Causa** | Lo único distinto es la semilla; el texto no fija superficies [V + H] |

## 5. Mejoras de bajo riesgo ya (texto y selección)

Costo en palabras sobre las 325 actuales (techo 1 000). Todas son cambios del compilador o del
Brand Kit; ninguna agrega proveedor ni infraestructura.

| # | Mejora | Palabras | Riesgo | Por qué |
|---|---|---|---|---|
| M1 | **Regla de ajuste por categoría**: «isotipo en superficies redondas o pequeñas (vasos, tapas, adhesivos); imagotipo o logotipo en superficies planas y anchas (papel de bandeja, letreros, frente de cajas); isologo en cajas y bolsas». Si el selector eligió una sola variante, la regla dice cómo adaptarla (símbolo solo si la superficie es pequeña y la categoría lo permite; nunca recortar un isologo). | ~35 | Bajo | Hoy una variante horizontal compite por un vaso; la generación 1 acertó justo con el símbolo |
| M2 | **Lista de verificación en vez de lista de clases**: «Revisa cada superficie con marca de @Video1 en cada plano donde aparezca; cada una debe mostrar el logo del cliente o quedar lisa. Una superficie que conserve letras o lemas de origen es un fallo». Nombrar también los **lemas impresos** (el lema de la caja quedó en las dos). | ~40 | Bajo | Convierte «reemplaza todo» en «nada puede quedar»; ataca el fallo de la regeneración |
| M3 | **Notas de uso por defecto por categoría** cuando el dueño no escribió ninguna (las mismas de M1, en el bloque de referencias), y una invitación en el Brand Kit a escribir «para vasos», «para bandejas». | ~10 por logo | Bajo | Hoy las notas viajan vacías; el bloque v9 ya imprime `Usage:` si hay nota |
| M4 | **Selector: en modo edición, permitir isotipo + imagotipo** cuando el reel tiene superficies redondas y planas (hoy: «normally choose ONE»). | 0 en el video; ~20 en el sistema del selector | Medio | Una sola variante obliga a deformarla en alguna superficie |
| M5 | **Los planos del texto en modo edición describen el reel, no inventan superficies** (espátula, caja). | 0 en el video | Bajo | Coherencia con lo que el dueño ve; no cambia el video |
| M6 | **Revisión de la salida antes de mostrarla** (ver §6.4): una lectura con Claude de 4–6 cuadros del video generado: «¿queda marca de origen?, ¿aparece el logo del cliente?». Si falla, la pieza se marca para el dueño con un aviso; **no** se regenera sola (asistido, nunca autónomo). | 0 | Bajo | La regeneración de este borrador habría quedado marcada |
| M7 | **Semilla**: no fijarla en producción (regenerar debe dar otra opción). Sí sirve para el A/B, pero **hay que verificar en vivo** si `dreamina-seedance-2-5` la acepta: un rechazo 400 no cuesta; una aceptación cuesta USD 0,60 y puede ser una corrida del propio A/B. | 0 | Bajo | Sin semilla, el A/B necesita más corridas por brazo |

Total de M1–M3 en el video: **~85–115 palabras**, quedando en ~410–440 de 1 000. La documentación de
Seedance advierte que un texto largo dispersa la atención; por eso propongo frases cortas y
ninguna repetición de la regla genérica que reemplazan.

### Cómo medirlo (A/B pequeño; requiere aprobación del fundador, **no ejecutado**)

- **Brazos:** A = compilador v1 actual; B = v1 + M1 + M2 + M3. Opcional C = B + mapa de superficies
  del paso VLM (§6).
- **Entradas fijas:** este reel de origen (tres superficies con marca + un lema) y un segundo reel
  con otras superficies (por ejemplo, vaso de café y bolsa); la misma foto de producto y los mismos
  logos; borrador 480p, 5 s.
- **Corridas:** 4 por brazo y reel. Costo Seedance medido: USD 0,597 por borrador de 5 s en modo
  edición [V].

| Diseño | Corridas Seedance | Costo Seedance | Selector (USD 0,033 c/u, medido) | Total aprox. |
|---|---|---|---|---|
| A vs B, 1 reel | 8 | USD 4,78 | USD 0,26 | **~USD 5** |
| A vs B, 2 reels | 16 | USD 9,55 | USD 0,53 | **~USD 10** |
| A vs B vs C, 2 reels | 24 | USD 14,33 | USD 0,79 + VLM ~USD 0,08 | **~USD 15** |

- **Métrica principal:** proporción de pares (clip, superficie) sin marca de origen **y** con logo
  del cliente. Secundarias: variante correcta por superficie, producto reemplazado desde su primera
  aparición, sin corte a la foto del catálogo.
- **Jueces:** el fundador con una planilla de 6 cuadros por clip (unos 10 minutos para 16 clips), o
  Claude como juez (~USD 0,02 por clip) con revisión del fundador de una muestra.
- **Honestidad estadística:** con 4 corridas por brazo solo se detectan efectos grandes (por ejemplo,
  de 1 de 4 a 3 de 4 superficies correctas). Si la semilla se puede fijar, se emparejan semillas entre
  brazos y la comparación mejora sin costo extra.
- Documentar el resultado el mismo día en `docs/modelos-generativos/` (regla de `qualify-measure`).

## 6. El paso VLM sobre la escena de origen

### 6.1 ¿Es claramente una mejora?

**Sí para el modo edición, por dos razones verificables; el resto es hipótesis a medir.**

1. **Hoy nadie sabe qué superficies con marca tiene el reel.** El texto dice «vasos, cajas de papas,
   papel de bandeja, envolturas y letreros» a ciegas; el selector ve un solo cuadro. Una lectura del
   reel convierte la regla genérica en una lista concreta («vaso, 0–2,1 s, a la derecha de la
   bandeja, grande, curvo»). Es la diferencia entre «no dejes marcas» y «estas tres superficies deben
   cambiar». [V sobre lo que falta; H sobre cuánto obedece Seedance]
2. **Permite verificar la salida.** La misma lectura aplicada a 4–6 cuadros del video generado dice
   si quedó la marca de origen y en qué superficie. Eso es medible sin opinión y habría marcado la
   regeneración de este borrador. Es, probablemente, la mitad más valiosa. [V sobre el fallo; H
   sobre la precisión del lector]

Lo que **no** promete: que Seedance respete posiciones y tiempos al cuadro. Los modelos de video
siguen las anclas de tiempo de forma aproximada. Por eso las coordenadas sirven sobre todo para
elegir la variante (tamaño y forma de la superficie) y para la verificación, no como orden exacta.

### 6.2 Qué debe extraer (salida estructurada, con procedencia)

Por reel de origen, una sola vez (no depende de la marca del cliente):

- **Planos:** inicio y fin en segundos de cada corte, encuadre (general, medio, primer plano),
  movimiento de cámara.
- **Superficies con marca:** por cada una, `objeto` (vaso, tapa, caja de papas, papel de bandeja,
  envoltura, caja, bolsa, letrero, delantal, pantalla), `forma` (redonda/curva, plana ancha, plana
  pequeña), `tipo de marca` (palabra, símbolo, conjunto, patrón, lema impreso), `dueño` (marca del
  video, fabricante del producto, neutro — este último **se conserva**), y por aparición: plano,
  segundo de inicio y fin, caja normalizada `[x, y, w, h]`, tamaño relativo (pequeño, medio, grande),
  oclusión.
- **Textos sobrepuestos** (no impresos en objetos): texto, segundos, posición, función (gancho,
  precio, llamado a la acción, subtítulo), estilo tipográfico (redonda, script, serif, manuscrita),
  peso y color — para reescribirlos en la tipografía y la paleta del cliente o eliminarlos.
- **Producto de origen:** en qué planos aparece y en qué estado de armado, para «reemplazar desde la
  primera aparición».
- **Procedencia:** id del reel de origen, huella del archivo de video, cuadros leídos, modelo y
  revisión, versión del prompt de lectura; y subir `REPLICATION_ANALYSIS_VERSION` de 1 a 2 (el
  campo `source_reel.analysis_version` ya existe para esto). El texto fijo de réplica que hoy dice
  «no hay análisis VLM» cambia con esa versión.

### 6.3 Cómo lo usaría el compilador

1. **Selector:** recibe el mapa en vez de un solo cuadro, y elige la variante por superficie con la
   regla M1 (salida nueva en `ResourcePlan`: una lista `superficie → índice de logo`, validada como
   hoy se validan los índices).
2. **Texto del video:** una línea por superficie, corta: «Vaso (0–2,1 s, derecha): reemplaza la
   palabra de origen por @Image3 isotipo. Caja de papas (0–2,1 s y 3,3–5 s): quita el lema impreso,
   pon @Image2 imagotipo al frente. Papel de bandeja: patrón en colores del cliente, sin letras de
   origen». Costo: ~15–20 palabras por superficie; 3–5 superficies ≈ 60–100 palabras, que
   **reemplazan** a la lista genérica de M2.
3. **Verificación de la salida (M6):** se compara el mapa de origen con la lectura de la salida;
   cada superficie queda «cliente», «origen» o «lisa». Si alguna queda «origen», la pieza llega al
   dueño con un aviso y la opción de regenerar; nunca se regenera sola.

### 6.4 Qué modelo y cuánto cuesta

| Opción | Costo por reel (≈ 8 cuadros de 432×768 ≈ 3 500 tokens de imagen + 1 500 de texto; ~800 de salida) | Estado | Riesgo |
|---|---|---|---|
| **Claude Sonnet 5.5** (USD 2/10 por millón) | **~USD 0,018** | Proveedor ya en producción; el selector ya le envía imágenes | Bajo |
| Claude Opus 5.5 (USD 4/20), dentro de la llamada del selector actual | ~USD 0,036, o ~USD 0,01 adicional si se agregan los cuadros a la llamada existente (hoy USD 0,033 medido) | Ya corre en cada pieza con recursos | Bajo |
| Claude Haiku 5.5 (USD 0,10/0,50 según la tabla v7) | ~USD 0,001 | En producción para clasificar | Medio: lectura fina de letras pequeñas sin medir |
| `Qwen/Qwen3-VL-4B-Instruct` vía HF Inference Providers | Sin precio en la tabla v7 [H] | Vive en `packages/models` (grupo `ml`), **nunca desplegado**; un solo proveedor (featherless-ai); sin guarda de precio | Alto: proveedor y tiempo de ejecución nuevos |

Precios de Claude: `pricing_data/v7.json` [V]; tokens por imagen estimados con la regla de
ancho × alto / 750 [H]. La verificación de la salida cuesta lo mismo por clip (~USD 0,02 con
Sonnet). Frente a USD 0,60 del borrador de video, **el paso completo (lectura + verificación) suma
~USD 0,04, un 6–7 %**, y la lectura del reel de origen se reutiliza en cada regeneración.

**Recomendación:** Claude, empezando por Sonnet 5.5 en una llamada propia que se guarda por reel de
origen (dentro del negocio, con su `tenant_id` y RLS; no hace falta la excepción de tablas sin
negocio). `Qwen3-VL-4B` no aporta ahorro que importe a este volumen y obligaría a la tabla de
opciones y a la firma del fundador que exige agregar un proveedor o tiempo de ejecución. Se puede
reconsiderar si el volumen de réplicas supera unas miles por mes.

### 6.5 Orden propuesto

1. M1 + M2 + M3 + M5 (solo texto, horas de trabajo) y la verificación M6 con Claude.
2. A/B de §5 (~USD 10–15) con el brazo C si el paso VLM ya existe; si no, A vs B primero.
3. Con el resultado, decidir el paso VLM completo (mapa de superficies en el selector) y M4.

**Qué reabre estas recomendaciones:** que el A/B muestre que B no mejora a A en la métrica principal
con 2 reels; o que Seedance acepte una máscara o región por referencia (entonces el mapa de
superficies se usaría como máscara y no como texto).

## Anexo: método

- Lectura de datos: `tenant_session` con `SET TRANSACTION READ ONLY` y reversión; tablas
  `content_drafts`, `content_briefs`, `piece_versions`, `image_assets`, `creative_vendor_tasks`,
  `creative_usage_events`, `brand_kits`.
- Medios: R2 con `ObjectGate.open_object` (prefijo del negocio verificado) y el reel de origen
  desde el directorio local de subidas; cuadros con PyAV; nada se escribió en R2 ni en la base.
- Reconstrucción del texto: `git archive 3db64355` en una carpeta temporal y
  `reel_edit_prompt(...)` sobre los datos guardados; simulación del compilador actual con el código de
  esta rama. Ninguna llamada a proveedores.
