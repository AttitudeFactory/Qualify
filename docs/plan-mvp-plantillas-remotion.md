# Plan y MVP — Motor de Plantillas con Remotion

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

**Fecha:** 2026-10-05 · **Estado:** `[PLAN — para ejecución; decisiones del fundador del 2026-10-05 incorporadas]`
**Qué reemplaza:** el render Pillow del Motor de Contenido de Marca (diseño §1.9, D15) y el tipo «Imagen tipo flyer». **Qué replica:** el modelo de ElevenCreative Templates, leído en la fuente ([backlog §7](backlog-motor-plantillas-remotion.md)).
**Pilotos:** **Bianki** (shawarma) y **Polette** (helado de yogurt), los dos emprendimientos del fundador en Korner, San Cristóbal: **un mismo dueño que las maneja por separado, como dos marcas, con un solo inicio de sesión** (fundador, 2026-10-23; cómo encaja con `1 login = 1 tenant` está pendiente: [diseño §7.7](diseno-motor-contenido-marca.md)). **Confirmado por el fundador el 2026-10-05 como decisión final para las dos marcas.**
**Historias:** [backlog-motor-plantillas-remotion.md](backlog-motor-plantillas-remotion.md) (`MP-00…13`); este plan las ordena en fases y les da el contrato.

> **Nota sobre los pilotos.** Los docs de agosto describían otra oferta; la [estrategia de contenido](estrategia-contenido-bianki-polet.md) ya está corregida. El fundador confirmó el 2026-10-05 (y de nuevo el 2026-10-23) que la oferta final es shawarma y ensaladas (Bianki) y helado de yogur (Polette, antes Polet). Se toma esa decisión; la **Fase 1 incluye refrescar el catálogo de producto y el brand kit de las dos marcas** con las fotos reales que él suba, que es exactamente lo que el módulo necesita para existir.

---

## 1. La idea en una frase

> **Subes fotos reales de tu producto una vez, y cada plantilla de tu nicho las convierte en un paquete de piezas (Reel, imagen de feed, historia) para cada ángulo de campaña, en segundos y por centavos, sin que elijas herramienta ni plantilla.**

Es el momento ElevenCreative de «agregas un SKU al catálogo y recibes packshots, variantes por canal y video», aplicado a una tienda de comida: **agregas un producto, recibes su paquete de contenido.** Con dos diferencias que son el foso: la marca entra por el brand kit (no por prompts sueltos) y los píxeles del producto son reales (no generados). En comida, lo sintético delata; la [investigación de agosto](estrategia-contenido-bianki-polet.md) §2 lo documenta.

### Qué se abandona y por qué conviene decirlo entero

| Se va | Entra | Qué gana el producto |
|---|---|---|
| Render Pillow (imagen fija, 56 ms, $0) | **Remotion** (video 9:16 + stills 4:5 y 9:16 desde la misma composición) | Movimiento, texto animado, cierre de marca; una plantilla sirve a tres formatos |
| `ContentKind.STATIC_FLYER` como tipo aparte | La plantilla declara sus salidas; la imagen fija es una salida más | Un solo camino para la pieza visual; menos opciones en el selector |
| Plantilla = JSON de cajas + Pillow | Plantilla = **composición TSX + manifiesto JSON** con puertos tipados y versión | Autoría con herramientas de video reales; versión inmutable por pieza (plantilla × métricas) |
| Un runtime (Python) | Dos runtimes: Python (negocio) + Node (render) | Costo asumido; se contiene en un paquete y un `just` |

Lo que **no** se abandona: el Post (`ContentDraft`), la FSM con aprobación humana, el brand kit y su voz, el router con presupuesto, HeyGen para «persona hablando», Canva para la última milla, el flujo de publicación y el Planificador.

---

## 2. Arquitectura del MVP

```
 Catálogo de producto ─┐
 Brand kit ────────────┤
 Biblioteca de prompts ├──► Post (brief + copy por ángulo) ──► Router de receta ──► Cotización (3 opciones)
 (nicho × ángulo)      │                                                                │ usuario elige
                       │                                                                ▼
                       │                                            Job de render ──► Remotion (Node)
                       │                                              │                  ├─ video 9:16
                       │                                              │                  ├─ still 4:5
                       │                                              │                  └─ still 9:16
                       │                                              ▼
                       └────────────────────────────────────── Draft con N salidas ──► HITL ──► Planificador / Publicar
                                                                       │
                                                                       └── costo estimado vs real, plantilla+versión, prompt+versión
```

### 2.1 Las seis piezas

| # | Pieza | Qué es | Dónde vive | Nuevo o existente |
|---|---|---|---|---|
| 1 | **Catálogo de producto** | Producto con nombre, precio, descripción, categoría, **fotos reales** (varias) y videos cortos del local. Las fotos pasan al subir por la normalización que **ya existe** en Python (`qualify_creative.photo.normalize`: rotación EXIF, HEIC, Display P3 → sRGB, export limpio) | Postgres (`brand_products`, `product_media`) + R2 bajo el prefijo del tenant | **Nuevo** el catálogo; **existente** la normalización. Hoy el brief lleva `product_ref: str` y claves de subida sueltas; no hay entidad producto |
| 2 | **Biblioteca de prompts por nicho × ángulo** | Para cada nicho (shawarma, helado) y cada ángulo (`ContentType`: producto, promoción, combo, menú, precio, fidelidad, temporada, agotado…), el prompt que produce los **campos que la plantilla imprime**: gancho, línea de precio, promo, CTA, textos de escena. Versionada; cada pieza guarda `prompt_id` + `prompt_version` | Repo: `packages/creative/src/qualify_creative/prompts/<nicho>/<ángulo>.md` + registro | **Nuevo.** Hoy el prompt es uno por tipo de contenido (`brand/render.py`), sin nicho |
| 3 | **Plantilla** | Composición Remotion + **manifiesto**: id, versión, nicho, ángulos que sirve, puertos de entrada tipados, puertos de salida, requisitos de assets, modelo de costo | Repo: `packages/render/templates/<nicho>/<id>/` (TSX + `manifest.json`) | **Nuevo.** Reemplaza `qualify_creative/templates/` (Pillow) |
| 4 | **Router de receta** | Mira el Post (ángulo, assets del producto, avatar del tenant, límite de gasto) y devuelve **tres opciones con costo**, la sugerida marcada; guarda regla aplicada y si el usuario la cambió | Python, sobre el `CreativeRouter` existente | Extiende |
| 5 | **Servicio de render** | Paquete Node con Remotion **en Docker desde la Fase 1** (decisión del fundador, 2026-10-05): un servicio `render` en el `docker-compose.yml` junto a Postgres y Redis, la misma imagen en desarrollo y en el VPS. Expone HTTP: `estimate`, `render`, `status`, `cancel`. Lambda queda como opción futura, no como requisito | `packages/render/` (Node + `Dockerfile`) + adaptador Python `RemotionAdapter` que implementa el `GenerationProvider` existente | **Nuevo** |
| 6 | **Draft con N salidas** | Cada corrida produce varias salidas; cada una con su estado, formato, posición y puerto de origen. El draft se aprueba entero o por salida | `image_assets` ya tiene `media_type` + `position`; se agrega `output_port` y la provenance de plantilla/prompt | Extiende |

### 2.2 El contrato de plantilla (lo que copiamos de ElevenCreative)

Un manifiesto por plantilla, versionado en git. Ejemplo de la primera plantilla:

```json
{
  "id": "promo_producto",
  "version": 1,
  "niche": ["shawarma", "helado"],
  "serves_angles": ["product", "new_product", "promotion", "price", "sold_out"],
  "inputs": {
    "hook":        {"type": "string", "max": 60},
    "price_line":  {"type": "string", "max": 24, "optional": true},
    "cta":         {"type": "string", "max": 40},
    "photos":      {"type": "image[]", "min": 2, "max": 4},
    "brand":       {"type": "brand_kit"}
  },
  "outputs": {
    "reel":   {"type": "video", "aspect": "9:16", "duration": "from_script"},
    "feed":   {"type": "image", "aspect": "4:5"},
    "story":  {"type": "image", "aspect": "9:16"}
  },
  "cost_model": {"renders": 3, "aws_usd_per_video_sec": 0.0012, "aws_usd_per_still": 0.004}
}
```

Reglas del contrato, tomadas de la API de ElevenCreative y adaptadas:

- **Puertos tipados.** Un Post se valida contra el manifiesto **antes** de cotizar: si faltan fotos o el gancho es más largo que el puerto, la plantilla no se ofrece o se ofrece con aviso. Sin validar, el LLM escribe un gancho de 90 caracteres y la plantilla lo corta.
- **Versión inmutable.** Cambiar la composición o el manifiesto sube la versión. Cada pieza guarda `template_id` + `template_version`. Nunca se edita una versión publicada.
- **Varias salidas, estado por salida.** El estado del job se deriva: `pending` → `generating` → `completed`, o `failed` si alguna salida falló y todas terminaron. Una imagen lista no espera al video; un fallo parcial conserva lo que salió.
- **Motivo de fallo tipado**, sumado al enum `FailureReason` existente: `timeout`, `model_error` → `render_error`, `invalid_parameters`, `dependency_failed`, `charging_failed`.
- **Entradas por referencia.** Las fotos se pasan por clave de R2, no por copia. El servicio de render las lee con URL firmada de corta vida.
- **Costo antes de correr**, por salida. Mientras el equipo sea de 3 personas, la licencia es gratis y solo cuenta AWS ([backlog §0.1](backlog-motor-plantillas-remotion.md)); cada salida cuenta como un render para el día que entre Automators.

### 2.3 El servicio de render, sin romper la casa

El repo es Python. Remotion es Node. Reglas para que no sean dos proyectos:

- **Un paquete, un contenedor, un `just`.** `packages/render/` con su `package.json` y su `Dockerfile`; el servicio `render` vive en `docker-compose.yml` y **`just up` lo levanta con Postgres y Redis**. `just render-dev` abre Remotion Studio para autoría de composiciones (fuera del contenedor, con hot reload); `just render-build` reconstruye la imagen. El `justfile` ya es la puerta de todo lo demás.
- **Python nunca importa Node.** El `RemotionAdapter` habla con el contenedor por HTTP desde el primer día (`POST /render`, `GET /jobs/{id}`), igual en desarrollo que en el VPS. Cambiar dónde corre el contenedor no toca el negocio.
- **Lambda no es la única vía ni la primera.** Remotion documenta cinco formas de renderizar en servidor: la API de Node (`renderMedia`) en cualquier máquina, **Docker** (imagen oficial sobre `node:22-bookworm-slim` con Chrome Headless Shell), AWS Lambda, Vercel Sandbox, GitHub Actions; Cloud Run está en alfa y «no se desarrolla activamente». Para el volumen de los pilotos (decenas de piezas por semana) **un contenedor en el VPS que ya tiene Qualify es suficiente y es gratis**: sin cuenta AWS, sin IAM, sin cold start, y el costo por pieza es cero más allá del servidor. Arrancar en Docker desde la Fase 1 evita además el salto «funcionaba en mi máquina»: la imagen que renderiza la demo del domingo es la que se despliega. Lambda vale la pena cuando haya colas de renders simultáneos o se necesite 1 minuto de video en 15 segundos; ese día entra detrás del mismo adaptador. Reglas del contenedor: CPUs asignadas explícitamente, `enableMultiProcessOnLinux`, fuentes instaladas en la imagen.
- **Props, no lógica.** La composición recibe un JSON de props (textos, claves de fotos, brand kit resuelto a colores y fuentes). Toda decisión de negocio queda en Python; la composición solo dibuja.
- **Duración desde el libreto.** `calculateMetadata` deriva la duración del número de escenas y textos, no de un valor fijo. Las stills salen de la misma composición en frames elegidos (`renderStill`).
- **Fuentes del brand kit.** Google Fonts por nombre o fuente subida al kit; se cargan en la composición. Una fuente no disponible cae a la del kit por defecto y se registra.
- **La normalización de fotos se queda en Python, donde ya está.** `qualify_creative.photo.normalize` resuelve hoy los cuatro fallos silenciosos de una foto de teléfono (EXIF girado, HEIC que no abre, colores P3 lavados, export que Instagram recomprime mal) y corre al subir al catálogo. Es preparación de insumos, no render: la decisión «se abandona Pillow» aplica al **motor de plantillas**, no a utilidades de imagen que ya funcionan. El encuadre a 9:16 o 4:5 y el fondo difuminado sí van en la composición Remotion (`object-fit` + blur), porque dependen de la plantilla y no de la foto. Lo único que la composición no puede hacer es abrir un HEIC: por eso la conversión ocurre antes, en Python.
- **Audio fuera.** La música se pone en la app de Instagram; Instagram penaliza audio externo (diseño §1.7). La voz en off de ElevenLabs/HeyGen es una capa posterior y opcional.

### 2.4 FFmpeg: dónde sí y dónde no

Verificado en la documentación de Remotion el 2026-10-05 ([ffmpeg](https://www.remotion.dev/docs/ffmpeg), [OffthreadVideo](https://www.remotion.dev/docs/offthreadvideo)).

| Uso | ¿Hace falta FFmpeg aparte? | Dónde vive |
|---|---|---|
| **Renderizar** video y stills | **No.** «Desde Remotion v4.0, Remotion viene con una versión ligera de FFmpeg incluida. Ya no hace falta instalar FFmpeg.» La imagen Docker del servicio `render` no instala FFmpeg | Dentro de Remotion |
| **Leer el video del cliente** en la composición (Corte de video real) | **No.** `OffthreadVideo` extrae frames con su FFmpeg interno y acepta H.264, **HEVC** (el `.mov` del iPhone), VP8/VP9, AV1 y ProRes | Dentro de Remotion |
| **Cámara lenta, rampa de velocidad, congelado** | **No.** `playbackRate` entre 0,0625 y 16; la rampa se hace acumulando la velocidad por frame | En la composición |
| **Reversa y boomerang** | **Sí.** «Reproducir un video en reversa no está soportado.» Si una plantilla los quiere, el clip invertido se genera antes | Python, al subir |
| **Normalizar el video al subir al catálogo** (recortar a 7 a 15 s, quitar audio, corregir rotación del `.mov`, transcodificar a H.264 para que el navegador lo previsualice) | **Sí.** El render acepta HEVC, pero **Remotion Studio y la pantalla del catálogo previsualizan con `<video>` del navegador**, que no reproduce HEVC. Sin transcodificar, el fundador sube el video y no lo ve | Python, al subir, como la normalización de fotos |
| **Keyframes y audio para la ingesta** (Fase 1 Parte 3 del pipeline) | Sí, pero es otro módulo y no cambia | `extract-worker`, cuando exista |

**Regla:** FFmpeg es una dependencia del lado **Python**, para preparar insumos al subir, igual que Pillow lo es para las fotos. **Nunca entra a la imagen de render.** El diseño de agosto (§1.7) ponía los efectos de velocidad en FFmpeg; con Remotion esos efectos pasan a la composición, y a FFmpeg le queda solo lo que Remotion no hace: reversa, boomerang y la normalización de entrada. Igual que con las fotos, la normalización de video corre **siempre** al subir, no es opcional.

Lo que necesita el contenedor de la API: el binario `ffmpeg` instalado en la imagen (paquete `ffmpeg` de Debian) y un envoltorio fino en `qualify_creative.video.normalize` con el mismo contrato que `photo.normalize`: entra el archivo del teléfono, sale un MP4 H.264 1080×1920 sin audio, de duración acotada, más su duración y su primer frame como miniatura.

---

## 3. Las plantillas de los pilotos

Cada plantilla sirve a varios ángulos; el **ángulo** cambia el prompt (qué dice), la **plantilla** cambia la forma (cómo se ve). Ese cruce es la biblioteca.

### 3.1 Plantillas del MVP (compartidas por los dos nichos)

| Plantilla | Para qué ángulos | Entradas | Salidas | Fase |
|---|---|---|---|---|
| **Promo de producto** | producto, producto nuevo, promoción, precio, agotado | 2 a 4 fotos del producto, gancho, precio, CTA | Reel 9:16, feed 4:5, historia 9:16 | 1 |
| **Menú / varios productos** | menú, combo, menú del día | 2 a 6 productos con foto y precio | Reel 9:16 (grid animado), feed 4:5 (grid), historia | 2 |
| **Corte de video real** | producto, promoción, detrás de escena | 1 video del local (vertido del helado, armado del shawarma), gancho, promo, CTA | Reel 9:16 | 2 |
| **Fidelidad / tarjeta** | fidelidad, horario y ubicación | sin foto obligatoria; brand kit + textos | feed 4:5, historia | 3 |

### 3.2 Lo que cambia por nicho

| | **Bianki (shawarma)** | **Polette (helado de yogurt)** |
|---|---|---|
| Qué foto manda | La porción real en la mano, con el precio a la vista. Enseñar el tamaño es la ventaja de quien no miente | El vaso de cerca: el yogurt, los toppings y el color de la fruta. El servido con los toppings cayendo es el Reel que gana |
| Ángulos que más rinden (hipótesis a validar en Fase 3) | precio, combo, hora pico / antojo, catering de oficina | sabor o topping de la semana, combo dúo, temporada, tarjeta de sellos, el ángulo «saludable» propio del yogurt |
| Voz (del brand kit) | Casual, humor, léxico local | Cálida, personal, narrativa de origen |
| Prompts iniciales | `shawarma/{product,promotion,combo,price,catering}.md` | `helado/{product,promotion,combo,seasonal,loyalty}.md` |

### 3.3 Cómo se pulen los prompts (el bucle que pidió el fundador)

El fundador quiere subir fotos e **ir puliendo los prompts de cada nicho para los diferentes ángulos**. Eso necesita un lugar donde probar y una memoria de qué salió bien:

1. **Laboratorio** (pantalla, Fase 2): elegir marca → producto → ángulo → plantilla, generar, ver las salidas al lado de los campos que el prompt produjo (gancho, precio, CTA).
2. **Calificar** cada corrida: 1 a 5 y una nota de una línea («el gancho suena a anuncio», «el precio quedó chico»). Se guarda con `prompt_id`, `prompt_version`, `template_id`, `template_version`, producto y ángulo.
3. **Revisar el prompt** en el repo y subir su versión. Las corridas siguientes llevan la versión nueva; las calificaciones viejas quedan atadas a la vieja. En dos semanas se ve qué versión del prompt de «promoción» para helado promedia mejor.
4. **Cuando lleguen métricas reales** (Fase 3, insights de la cuenta de Instagram por la conexión Meta existente), la calificación humana se cruza con alcance e interacción por `template_version` y `prompt_version`. Es el loop de aprendizaje del diseño (D16) aterrizado.

Contención, igual que en el diseño: el prompt compone **dentro** del brand kit (paleta, tipografía y tono salen del kit, no del prompt) y **las versiones que funcionan se congelan**. La pieza de cada día quiere estabilidad.

---

## 4. Campañas

Una **campaña** es la unidad que convierte el catálogo en semanas de contenido: un conjunto de productos × un conjunto de ángulos × un rango de fechas × un canal. Genera N Posts, cada uno pasa por el router y el render, el fundador aprueba uno por uno (o en lote cuando el prompt ya está estable) y los aprobados caen al Planificador, que ya publica a su hora (QUA-111).

| Ejemplo | Productos | Ángulos | Fechas | Piezas |
|---|---|---|---|---|
| «Semana del shawarma mixto» (Bianki) | 1 producto, 3 fotos | producto, precio, combo, hora pico | lun a vie | 4 Reels + 4 feed + 4 historias |
| «Sabores de octubre» (Polette) | 4 sabores, 2 fotos cada uno | sabor de la semana × 4, combo dúo | 4 semanas | 5 paquetes |

**Fase 1** no tiene pantalla de campaña: se generan los Posts uno a uno desde el generador existente. **Fase 2** agrega el lote. Lo que sí entra desde la Fase 1 es que cada draft guarde `campaign_id` opcional, para que el lote de la Fase 2 no requiera migrar nada.

---

## 5. Fases

### Fase 0 — Decisión y contrato (lunes 5)

- Enmienda al diseño técnico (`MP-00`): Pillow → Remotion, con la tabla de §1. Licencia gratuita hasta 3 personas (`MP-05`).
- Contrato de plantilla y de adaptador (`MP-01`), en Python, sin Node todavía: manifiesto, puertos, validación de un Post contra una plantilla, cotización por salida.
- Migración `0038`: `brand_products`, `product_media`, `template_runs` (job: plantilla, versión, prompt, versión, estimado, real, regla del router, override), `output_port` en `image_assets`, `campaign_id` opcional en drafts. RLS en la misma revisión.

**Hecho cuando:** un Post de prueba contra el manifiesto de «Promo de producto» devuelve «válido, 3 salidas, USD 0,03» sin tocar red.

### Fase 1 — MVP: una plantilla, tres salidas, dos marcas (martes 6 a domingo 11)

| Día | Entrega | Verificación |
|---|---|---|
| Mar 6 | `packages/render/` con Remotion, `Dockerfile` y servicio `render` en `docker-compose.yml`; `just up` lo levanta; composición HelloWorld; `RemotionAdapter` por HTTP; stub primero (`MP-03`), real después (`MP-04`) | Un MP4 renderizado desde Python contra el contenedor |
| Mié 7 | **Catálogo de producto**: pantalla mínima para crear producto con precio y subir 2 a 6 fotos; normalización con `sharp`; fotos en R2 | Fundador sube los productos reales de Bianki y Polette |
| Mié 7 a Jue 8 | Plantilla **Promo de producto** v1 (`MP-06`): Reel + feed + historia; brand kit por props; duración desde el libreto | Tres salidas por marca, revisadas a ojo |
| Jue 8 | Prompts v1 de los 5 ángulos por nicho; el copy del Post se genera con el prompt del nicho × ángulo y llena los puertos | Gancho, precio y CTA entran en los límites del puerto en 9 de 10 corridas |
| Vie 9 | Router de receta (`MP-09`) + cotización de tres opciones (`MP-10`): Remotion / HeyGen / UGC (solo cotiza) | Test por regla; estimado vs real dentro del 30 % |
| Sáb 10 | Draft con N salidas, estado por salida, descarga por salida; «Con plantilla» deja de rechazarse (`MP-02`); Post aprobado dispara render (`MP-11`) | Un Post real termina en Reel + feed + historia descargables |
| Dom 11 | **Demo con los dos pilotos** (`MP-12`): un paquete por marca publicado o listo para publicar; costos reales anotados | Video en la cuenta o en el Planificador |

**Fuera de la Fase 1:** el despliegue del contenedor al VPS (la imagen ya existe; falta publicarla), campañas en lote, Laboratorio, Menú y Corte de video, retirar el flyer, audio.

### Fase 2 — Biblioteca y bucle (12 al 18 de octubre)

- Plantillas **Menú / varios productos** (`MP-07`) y **Corte de video real** (`MP-08`), con subida de videos cortos al catálogo y su normalización con FFmpeg (§2.4).
- **Laboratorio de prompts** con calificación (§3.3). Prompts v2 de los ángulos que peor calificaron.
- **Campañas en lote** (§4): productos × ángulos × fechas → drafts → Planificador.
- La **misma imagen de render desplegada en el VPS**, detrás del mismo adaptador. Lambda no entra salvo que el volumen lo pida.
- Retirar «Imagen tipo flyer» del selector (`MP-13`).

**Hecho cuando:** una campaña de una semana para una marca se genera en lote, se aprueba y queda programada, con cada pieza llevando plantilla, versión, prompt y versión.

### Fase 3 — Aprender (19 de octubre en adelante)

- **Plantilla × métricas**: insights de la cuenta propia por la conexión Meta, cruzados con `template_version` y `prompt_version`. Primera frase calculable: «la v2 del prompt de promoción en helado rinde X % más».
- Plantilla **Fidelidad / tarjeta**; historias con sticker de enlace.
- Variantes asistidas por LLM **dentro** del contrato: el modelo propone props alternativos (otro gancho, otro orden de fotos), nunca layouts nuevos a ciegas. La lección de la [investigación del bucle de visión](research-bucle-vision-plantillas.md) sigue valiendo aunque el motor cambie: validar determinista primero, visión al final y por muestreo.
- Voz en off opcional (ElevenLabs o la voz clonada en HeyGen) como capa sobre el Reel, si los pilotos la piden.

---

## 6. Criterios de hecho del MVP (Fase 1)

- [ ] Los productos reales de Bianki y Polette están en el catálogo con sus fotos, subidas por el fundador desde la pantalla.
- [ ] Un Post con ángulo «promoción» y 2 o más fotos produce Reel 9:16, feed 4:5 e historia 9:16 en una corrida, con la paleta y tipografía del brand kit.
- [ ] Antes de renderizar, el usuario ve tres opciones con costo y la sugerida marcada; puede cambiarla.
- [ ] Cada salida tiene estado propio; una imagen lista se ve antes de que termine el video.
- [ ] Cada pieza guarda plantilla, versión, prompt, versión, regla del router, costo estimado y real.
- [ ] El copy sale del prompt del nicho × ángulo y entra en los límites de los puertos.
- [ ] Un Post aprobado sigue el flujo de publicación existente sin pasos manuales.
- [ ] Demo con los dos pilotos el domingo 11.

---

## 7. Riesgos

| Riesgo | Señal | Mitigación |
|---|---|---|
| Node + Remotion en un repo Python se vuelve «el otro proyecto» | nadie corre `just render-dev`; el adaptador se prueba solo con stub | Un paquete, un `just`, contract test del adaptador contra un render real en `integration` |
| El contenedor de render en el VPS compite por CPU con la app | renders de más de 2 minutos o la app lenta mientras renderiza | CPUs asignadas al contenedor, cola de un render a la vez por tenant; si no alcanza, Lambda detrás del mismo adaptador |
| Las composiciones consumen más días | jueves sin «Promo de producto» completa | Reel primero; feed e historia son stills de la misma composición y salen casi gratis después |
| Fotos de teléfono dispares (HEIC, giradas, vertical/horizontal mezcladas) | bordes, recortes, colores lavados | Normalización Python al subir (ya existe), obligatoria y no desactivable; encuadre y fondo difuminado en la composición |
| El copy rompe el puerto (gancho largo, precio con formato raro) | textos cortados en la pieza | Validación contra el manifiesto antes de cotizar; el prompt declara los límites; `invalid_parameters` como fallo tipado |
| El costo por pieza en el VPS es cero y el estimado deja de significar algo | el usuario ve «USD 0,00» en todas las opciones Remotion | El estimado muestra tiempo de render y, si algún día hay Lambda o licencia, su costo; HeyGen y UGC siguen con costo real. La comparación entre opciones sigue siendo honesta |
| Un cuarto colaborador entra y la licencia gratuita deja de aplicar | headcount 4 | Regla escrita en `MP-05`; Automators a USD 100/mes |
| Los pilotos cambiaron de oferta y los docs no | el brand kit tiene la oferta de agosto, el catálogo tiene helado de yogurt | Refrescar brand kit y catálogo en Fase 1, con el fundador en la pantalla |

---

## 8. Decisiones que siguen siendo del fundador

1. ~~Cuenta AWS para Lambda~~ **No hace falta para arrancar.** El render corre en Docker en el VPS de Qualify (Fase 2). Lambda solo si el volumen lo pide; ese día se decide la cuenta.
2. **Quién escribe las composiciones TSX.** Es trabajo de diseño en movimiento, no de backend; conviene una persona que mire las piezas con ojo de marca.
3. **Fuentes.** Si el brand kit de Polette o Bianki usa una fuente comercial, hace falta su licencia para servidor; Google Fonts evita el problema.
4. ~~Confirmar la oferta actual de cada piloto~~ **Cerrado 2026-10-05: shawarma y helado de yogurt.** Falta solo qué productos entran al catálogo el miércoles 7.
