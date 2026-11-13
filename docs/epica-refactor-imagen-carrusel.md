# Épica — Imagen y carrusel: foto limpia, textos que se leen y diseño con Remotion

`[EN CURSO · creada 2026-11-12]` · Feature Meegle **m-25017272** —
https://project.larksuite.com/5h2wsx/story/detail/25017272

## Decisión del fundador (2026-11-12)

Rige sobre todo lo demás de este documento.

- Se rehacen los módulos **Imagen** y **Carrusel** de «Crear publicación», en seis fases.
- **«Nada de pillow, todo con remotion y la IA orquestando con remotion»**: Seedream solo hace la
  foto base, Claude escribe la capa de texto, Remotion compone. Sin respaldo con Pillow.
- Diapositivas del carrusel con **«+» y borrar** (2 a 10).
- El carrusel entra en el refactor.
- Se agregan las mejoras de la Fase 5 («Repetir este diseño», otro formato, eval permanente).

## Por qué (evidencia)

**Reporte del fundador (2026-11-12):**

- «Subir» en Imagen «no sirve para nada o tarda muchísimo».
- Faltan tipos: Destacados para Instagram, íconos para destacados, flyer con
  ubicación/horarios/productos/métodos de pago, y «Otros» con texto libre.
- «Mejorar texto» «siempre da el mismo resultado».
- Las entradas guiadas empeoran a Seedream; deberían alimentar a la IA que escribe el texto.
- El resultado trae «botones innecesarios y textos horribles». En dos historias de Bianki:
  Seedream dibujó píldoras y letras sin sentido («BERIRN NON»); nuestro título va en blanco con
  borde negro sobre la zona más cargada y tapa el logo de la escena; una pieza «Ubicación» no
  tiene dirección y muestra una calle europea inventada; el logo aparece dos veces.

**Lo que muestra el código** (rutas desde la raíz; `media.py` =
`packages/api/src/qualify_api/creative/media.py`):

| Tema | Hallazgo |
|---|---|
| «Subir» | Pestaña que solo revela una zona de arrastre (`Qualify/content_generator.py:1153`, `_upload_zone` 2603-2619); `accept` png/jpg/jpeg/webp (:138) → HEIC del iPhone rechazado en silencio; sin `max_size` ni reducción; manejadores sin `yield` → sin avance (`creative_state.py:7159-7196`, `owner_uploads.py:213`) |
| «Mejorar mi texto» | `context_ai.enhance_context` (`context_ai.py:298`), Sonnet, «Conserva TODO… No añadas relleno», 300 caracteres; reemplaza el campo y se reescribe a sí mismo; no recibe tipo, formato ni fotos |
| Prompt de Seedream | `ad_scene_prompt` (`media.py:7509-7661`) recibe escena + «Datos clave»; la regla de texto v2 habla de títulos/llamados y «franjas tranquilas» → probablemente induce botones; `content_type` no llega |
| Composición | Pillow (`packages/creative/.../compose.py`: `render_ad_slides` :647, `render_carousel_slide` :683, `text_layer` :734), un solo diseño; la base cruda no se guarda; `edit_variant` (`service.py:3733`) no recompone |
| Copy | `CopyPayload` (`schemas.py:326`) solo `hook` y `cta` |
| Carrusel | Sin texto por diapositiva (`SlideText` NONE/HOOK/CTA); pantalla fija en 3 (`_GALLERY_SLIDES=3`, `creative_state.py:612`) aunque esquema y publicador admiten 2-10; sin regenerar/editar una diapositiva; camino viejo dentro de `STATIC_FLYER`; `rendered_prompt` no guardado |
| Remotion | `PromoStill.tsx` (feed/cuadrado/historia) y `sticker` v1; sin composición de carrusel; `RemotionRenderClient`/`RemotionTemplateAdapter`; perfil `render`, 1536m, concurrencia 1 |
| Precios v8 | Seedream 5.0 pro US$0.045 (+0.003 por referencia extra), lite 0.035, flash 0.018; Remotion propio US$0. Cuota del carrusel: ≤3 generadas = 1 creación, ≤7 = 2, ≤10 = 3 |
| Contrato de publicación | `slide-N.jpg`, JPEG, dimensiones exactas del formato, posiciones 0..N-1, 2-10 elementos — no se rompe |

## Reglas que aplican a todas las historias

- Aislamiento por negocio: toda tabla nueva con `tenant_id` + RLS en la misma migración.
- Procedencia en toda fila derivada (fuente + modelo/prompt/versión de pipeline).
- Idempotencia en trabajos de cola: un reintento no vuelve a llamar a Seedream ni cobra dos veces.
- Asistido, nunca autónomo: el dueño aprueba antes de publicar.
- Sin runtime ni proveedor nuevo (Remotion ya existe).
- Textos para el cliente en español (`qualify-copy-es`): «publicación», nunca «post».
- Cambios de prompt o modelo: medidos y documentados en `docs/modelos-generativos/` (`qualify-measure`).
- Responsable en Meegle: Herwin como Reporter y Assignee en todas (regla de la casa: sin
  Assignee el equipo no puede mover el ticket); se reasigna al tomarlo.

## Historias

P = prioridad, T = tamaño. «Bloqueado por» está cargado en Meegle.

### Fase 0 — Arreglos rápidos (sin dependencias, sale primero)

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25017273 | «Subir» abre las fotos al primer toque, acepta fotos del iPhone y muestra el avance | reflex-ui | P1/M | — |
| m-25017274 | «Mejorar mi texto» ofrece 2 o 3 versiones distintas y conserva lo del dueño | creative + ui (medición datasci) | P1/M | — |
| m-25017275 | Seedream no dibuja letras, botones ni etiquetas inventadas | creative (medición datasci) | P1/S | — |
| m-25017276 | Imágenes compuestas sin botón dibujado por defecto | creative | P1/S | — |

### Fase 1 — Pipeline compartido (base de todo lo demás)

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25017277 | Verificar cola de generación en producción (ADR 41) y fijar el contrato de publicación | creative (+platform) | P1/S | — |
| m-25017278 | Módulo propio del pipeline de imagen y carrusel + prompt compilado guardado | creative | P1/M | — |
| m-25017279 | Seedream solo hace la foto base, se guarda y Claude la revisa (1 regeneración) | creative | P1/M | 278, 275 |
| m-25017283 | Claude escribe la capa de texto viendo la foto (esquema cerrado, precio del catálogo, logo una vez) | creative | P1/M | 278 |
| m-25017285 | Composición Remotion de imagen y carrusel con diseños cerrados y zonas prohibidas | creative | P1/L | 278 |
| m-25017286 | «Usar mi foto»: texto sobre la foto real, sin generar imagen | creative (+ui) | P1/M | 283, 285 |
| m-25017287 | Claude mira la imagen compuesta y la corrige una vez | creative (medición datasci) | P2/S | 283, 285 |
| m-25017288 | Cambiar el texto recompone gratis, sin otra foto | creative + ui | P1/M | 279, 283, 285 |
| m-25017289 | Chequeo de salud del render con alerta | platform | P1/S | — |
| m-25017292 | Medición: pipeline nuevo vs actual, Seedream pro/lite/flash, tiempo de carrusel | datasci | P1/M | 279, 283, 285, 287 |
| m-25017293 | Quitar Pillow; si el render cae, cola y reintento («la estamos terminando») | creative | P1/M | 277, 285, 289, 292 |

### Fase 2 — Carrusel completo (depende de Fase 1)

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25017294 | Claude reparte la historia en un texto por diapositiva (portada, desarrollo, cierre) | creative | P2/M | 283, 285 |
| m-25017295 | «+» y quitar diapositivas, 2 a 10, aviso en la 4.ª y la 8.ª generada | reflex-ui | P2/M | 292 |
| m-25017298 | En la revisión: quitar, agregar, regenerar o cambiar texto de una sola diapositiva | creative + ui | P2/L | 288, 294, 295 |
| m-25017297 | Diapositivas animadas con su texto compuesto en Remotion | creative | P2/M | 285 |
| m-25017299 | Retirar el camino viejo de carrusel dentro de `STATIC_FLYER` | creative | P2/M | 293, 294 |

### Fase 3 — Tipos nuevos (depende de Fase 1; en paralelo con Fase 2)

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25017300 | Datos del negocio: dirección, horarios y métodos de pago (reusa los de WhatsApp) | backend + ui | P2/M | — (puede empezar ya) |
| m-25017301 | Spike: ¿la API de Instagram publica destacados y portadas? | backend | P2/S | — |
| m-25017303 | Tipo «Portada de destacado» con la zona del círculo | creative | P2/M | 283, 285, 301 |
| m-25017304 | Tipo «Íconos para destacados» (juego de íconos, sin Seedream) | creative | P2/M | 285, 301 |
| m-25017307 | Tipo «Flyer informativo» con datos reales; nunca un lugar inventado | creative (+ui) | P2/L | 283, 285, 300 |
| m-25017308 | Tipo «Otros»: texto libre → diseño cerrado | creative | P3/M | 283, 285 (último) |

### Fase 4 — Pantalla (depende de Fases 1–3)

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25017309 | Imagen y carrusel en cuatro pasos: tipo, foto o producto, qué debe decir, revisar textos; revisión UX antes del PR | reflex-ui | P2/L | 293, 295, 303, 304, 307 |

### Fase 5 — Mejoras sobre el pipeline (depende de Fase 1)

| Ticket | Historia | Dueño | P/T | Depende de |
|---|---|---|---|---|
| m-25017310 | «Repetir este diseño» como estilo del negocio | creative (+ui) | P3/M | 288 |
| m-25017311 | La misma pieza en otro formato sobre la misma base (con spike del recorte) | creative | P3/M | 279, 288 |
| m-25017313 | Eval permanente de imágenes (puede adelantarse al cierre de Fase 1) | datasci | P2/M | 292 |

## Tickets existentes relacionados (no duplicados)

- m-24985141 «Generador: crear sin elegir antes un producto del catálogo, y elegir referencias
  desde la Galería» (En curso) — toca la misma pantalla; enlazado con m-25017273 y m-25017309.
- m-24828975 «Generador: enlace de destino y botón del anuncio en la pieza» (En curso) — el
  botón del anuncio de Meta no se toca al quitar el botón dibujado; enlazado con m-25017276.
- m-24852173 «Grupos de cupos para OmniHuman y Seedream en la cola» — enlazado con m-25017277.

No había tickets abiertos para «Subir», «Mejorar mi texto» ni la cantidad de diapositivas.

## Precondiciones (las responde m-25017277)

- ¿Producción corre la cola de ADR 41 (`creative-worker`) para imagen y carrusel, o hilos
  `InlineDispatcher`? Sin cola no hay reintento al caer el render. — *pendiente*
- Contrato de publicación como test. — *pendiente*

## Destacados (lo responde m-25017301)

Hipótesis: la API de Instagram no publica destacados ni portadas → esos tipos son solo descarga,
sin planificador. — *pendiente*

## Preguntas abiertas para el fundador

1. **Costo de la verificación visual** (m-25017287): si la medición muestra que sube el costo por
   pieza, ¿se activa igual o queda apagada?
2. **Modelo de la foto base** (m-25017292): pro, lite o flash según calidad/costo medidos.
3. **Tope de diapositivas**: 10 si el render a concurrencia 1 lo aguanta; si no, el tope medido.
4. **«Usar mi foto»** no llama a Seedream: ¿sigue contando como una creación o cuesta menos?
   Hoy no se cambia la regla de cuota; cambiarla es decisión suya.

## Fuera de alcance

- Editor libre para arrastrar textos.
- Quitar el fondo de las fotos de producto (sería un proveedor nuevo).
- Stickers de temporada (siguen como están).
- Conversión a JPEG para Meta y reducción de subidas (se mantienen; no son composición).

## Decisiones del fundador (2026-11-13, antes de arrancar la Fase 0)

| # | Tema | Decisión |
|---|---|---|
| 1 | Alcance de la primera tanda | Fase 0 completa más m-25017277, m-25017278 y m-25017289 |
| 2 | Revisión de arquitectura de la Fase 1 | Se corre de inmediato; observaciones como comentarios en los tickets |
| 3 | Fusión | Se fusiona y despliega todo PR en verde, incluidos los cambios de regla de Seedream y de botón si la medición no muestra retroceso |
| 4 | CI en rojo | Nunca `--admin`; el PR espera abierto |
| 5 | Pruebas pagadas de Seedream | Autorizadas con tope de US$3, con fotos del catálogo de Bianki como referencia |
| 6 | Dónde se guardan las pruebas | Solo en disco local, nunca en R2 |
| 7 | Verificación en producción | En el negocio de Bianki, incluida una pieza generada (una creación); nunca se aprueba ni se publica |
| 8 | Fotos HEIC | Conversión en el servidor con `pillow-heif`; Pillow se queda solo como conversor y reductor de archivos |
| 9 | Límites de subida | 50 MB por foto; se guarda reducida a 4096 px en el lado largo |
| 10 | Botón y precio dibujados | Se quitan los dos (botón y pastilla de precio) de imagen y carrusel; el botón propio de los anuncios se conserva |
| 11 | «Mejorar mi texto» | Tres versiones en tarjetas, gratis, conserva el original |
| 12 | «Usar mi foto» | No consume creación |
| 13 | Composición | Nada de Pillow: todo en Remotion con la IA orquestando; sin respaldo en Pillow (2026-11-12) |
| 14 | Valores por defecto confirmados | Tope de 10 diapositivas sujeto a la medición del render; íconos de destacados en Remotion; stickers de temporada fuera de alcance |

## Decisiones del fundador al firmar ADR 49 (2026-11-13)

Detalle y consecuencias en `docs/adr-49-pipeline-imagen-carrusel.md` §8. Rigen sobre las «Preguntas abiertas» 1 y 2 de arriba.

| # | Tema | Decisión |
|---|---|---|
| A1 | Pillow y el carrusel viejo | m-25017293 pasa a Remotion el camino viejo de carrusel dentro de `STATIC_FLYER` antes de borrar Pillow; m-25017299 deja de ser condición para eso |
| A2 | Revisión de la foto base | Un campo dentro de la llamada de la capa: una sola llamada con la foto escribe los textos e informa letras inventadas |
| A3 | Revisión de la imagen compuesta (m-25017287) | **Activa desde el inicio** (contra la recomendación de dejarla apagada hasta medir); la medición de costo, tiempo y cuántas imágenes corrige es lo que la reabriría |
| A4 | Espera de la composición si el render cae | **10 minutos**; después la pieza queda fallida, con «Reintentar» y sin descontar otra creación |
| A5 | Piezas anteriores al pipeline | No se recomponen; solo «Crear otra» |
| A6 | Foto del dueño en «Usar mi foto» | Se usa la foto de la Galería sin copiarla, y la Galería no deja quitar una foto mientras una publicación la use (aviso con el nombre de la publicación). Quedan subpreguntas abiertas en ADR 49 §8 (6a–6d) |
| A7 | Modelo de la foto base | Seedream 5.0 pro; no se comparan modelos. m-25017292 mide solo el tiempo del carrusel y el costo de la revisión visual |
