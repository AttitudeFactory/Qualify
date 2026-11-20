# ADR 50 — Video con efectos, por pasos: un motor sobre el Clip, efectos locales a costo 0 y un editor guiado con línea de tiempo

**Estado:** `[PROPUESTO — pendiente de la firma de Deivid Vargas]` · redactado por principal-architect el 2026-11-20 (m-25026568, EF-00). Las decisiones de §2 ya las firmó Deivid el **2026-11-13** (D1–D8 y D-E1…D-E6) y se escriben aquí como hechos firmados; las que tomó después, al construir, están en §2.3. Este documento no decide nada nuevo: deja por escrito lo firmado para que los tickets de código no se contradigan. Los umbrales que reabren decisiones (§4 y §8: ~600 MiB, ~200 entradas, el 10 % de los negocios activos) son **propuesta del arquitecto**, no decisiones firmadas: entran en vigor solo si Deivid firma este ADR. Lo que ya no coincide con `main` está en §6 («Diferencias con lo construido») y no se corrigió.
**Épica:** m-25026566 «Video automático con efectos, por pasos» · **Ticket:** m-25026568 (EF-00).
**Evidencia:** la descripción de la épica y de EF-00 en Meegle (leídas el 2026-11-20), `main` en `ab39151a` (2026-11-20), `docs/design-system.md` §5.10, `docs/armado-local-medicion.md`.
**Numeración:** el 49 es `docs/adr-49-pipeline-imagen-carrusel.md`. Esta decisión es la **50**; el código ya la cita como «ADR 50» y por sección (§1.2 receta, §1.3 regla de modo, §1.4 biblioteca, §1.6 compatibilidad), y esa numeración se respeta abajo.
**Relación con otros ADR:** se apoya en ADR 44 (plan de partes), ADR 41 (cola y `creative-worker`), ADR 47 (`media-worker` y `gallery_jobs`, donde corre el normalizador local) y ADR 49 (diseños cerrados de la capa de texto, Remotion). No enmienda ninguno; precisa F1 de ADR 44 (§3).

## 0. Contexto

Las piezas de @bianki.sc de noviembre se hicieron a mano con scripts: enderezar el material de GoPro, cámara rápida con ffmpeg, fuego procedural, Seedance 2.5 desde un cuadro real (borrador 480p, final 1080p) y textos de marca como capa transparente encima. Deivid quiere eso dentro de Qualify, sobre el plan del video por partes (ADR 44) y **también en el Clip normal, sin obligar a pasar por partes** (Deivid, 2026-11-13): «si por ejemplo a un video solo quiero ponerle un texto y un efecto tendría que hacerlo por partes a juro y no quiero eso».

Lo que quiere el dueño: subir su video, ponerle un texto y uno o varios efectos, y recibir el video armado — **gratis si los efectos se hacen aquí, y con la IA solo cuando el efecto la necesita** —, tanto en un Clip como en cada parte de un video por partes.

## 1. Decisión

**Un solo motor de efectos, por pasos, que trabaja sobre la pieza `CLIP` (con padre o sin él), y una sola pantalla de edición guiada con estilo de línea de tiempo que reemplaza las pantallas del Clip y de la hoja de parte. Lo que se hace en el servidor con nuestro código (preparar, cámara rápida, capas grabadas, textos con Remotion, unión) cuesta US$0 y no descuenta cupo; Seedance entra solo cuando el efecto lo necesita y solo con efectos medidos.**

### 1.1 Un motor, dos pantallas

- El motor trabaja sobre la pieza `CLIP`. Toda parte de un video por partes ya es un `CLIP` hijo (ADR 44, `content_drafts.parent_draft_id`), así que el mismo código sirve al Clip suelto y a cada parte.
- Pasos: **Planear → Preparar** (girar, recortar a 9:16, elegir tramos, color con rango explícito) **→ herramientas locales** (cámara rápida, capas) **→ Seedance solo si el efecto lo necesita → Componer** (texto, capas, transiciones, unión) **→ Revisar** (hoja de contacto) **→ final 1080p** que se vuelve a componer con la misma receta **→ procedencia** en `params` del asset.

### 1.2 La receta (`video_pipeline/recipe.py`)

- `recipe_of(brief)` devuelve **1 parte** para un Clip (desde su `MediaInputs`), **1** para un Clip hijo (su `media.part`) y **N** para el padre `SHOT_VIDEO` (las entradas del plan, con su `transition_in`).
- `validate_recipe` devuelve **todos** los problemas como `RecipeProblem` con código estable, sin lanzar, para que la pantalla lo llame en cada cambio; con `tenant_id` comprueba que cada tramo es del negocio (`owned_by`).
- `refuse_unbuilt_recipe` / `unbuilt_recipe_problems` cierra en falso lo que el motor todavía no dibuja (`recipe_unavailable`): no se escribe, no se cobra y no se manda a Seedance.
- Sin migración para la receta: los campos nuevos viven en el JSON del brief con valor por defecto (`PartRecipe`, `VideoRecipe`, `SourceSegment`, `text_layers`, `effects`).

### 1.3 La regla de modo (`video_pipeline/mode_choice.py`)

- En código, **sin LLM (US$0)**, pura y barata (la vista previa la llama en cada cambio), con **motivo visible** (`mode_reason`) y versión (`mode_rule_version`); el dueño puede cambiarla y queda marcado (`mode_changed_by_owner`).
- Video propio → `local`. Reel sin personas y fuente vertical editable → `edit`. Reel con personas o con duda → `reference` (F6 de ADR 44). Segunda mitad de un corte de más de 10 s → `extend` solo si el interruptor de m-24880328 está encendido; si no, `reference` con su motivo.

### 1.4 La biblioteca de efectos (`qualify_creative/effects.py`, `effects_data/vN.json`)

- **JSON versionado en el repo, sin tabla.** Cada entrada dice en qué paso actúa (`stage`), su versión, sus parámetros, `preview_asset`, si se ofrece (`offered`) y su tasa de éxito medida (`measured`).
- Una entrada **nunca se edita en su lugar**: un cambio de parámetros, prompt o archivo es una entrada nueva en `version + 1`; un brief guarda la versión con la que se hizo. Única excepción documentada: v3 ofrece las capas en versión 1 sin cambiar sus bytes.
- Los archivos de vista previa y de capa son globales, de solo lectura, empaquetados en la imagen (`effects_assets/`), nunca bajo el `t/` de un negocio ni en R2.

### 1.5 Modo local: «Tu video, con efectos»

- `PartMode` gana `local`: sin Seedance, **costo 0**, solo con video o fotos propios del negocio y sin efectos de Seedance.
- Corre en el `creative-worker` (preparación del trabajo `preview` de ADR 41), nunca en Reflex (el despachador `inline` lo rechaza). Las fuentes de más de 4K o de más de 8 bits se normalizan antes en el `media-worker` (ADR 47, trabajo `normalize_local` en `gallery_jobs`, revisión `0171`).
- El asset lleva `ai_generated=False` y no lleva bloque `draft`: no hay final de Seedance que pedir, se publica tal cual.

### 1.6 Compatibilidad con lo guardado

- `effects_pipeline_version = 0` deja intactas las piezas anteriores; en un brief nuevo, el servidor sella la versión del motor solo cuando es una receta `local` con tramos; cualquier otro brief queda en 0 (`effects_version_for`, `local.py`), como `prompt_compiler_version`. Los briefs guardados antes de la receta siguen leyendo igual (`test_brief_fixtures_ef02.py`).

### 1.7 La pantalla: estilo de editor con línea de tiempo, **no un editor de video**

- Un editor simplificado: vista previa en vivo + línea de tiempo + «Agregar» (Foto o video · Texto · Efecto · Idea) + el panel del bloque elegido. Reemplaza las pantallas del Clip y de la hoja de parte.
- **El estilo es el de un editor con línea de tiempo, pero no se construye un editor de video.** Quedan fuera: fotogramas clave, zoom de la línea de tiempo, recorte cuadro a cuadro, capas libres, pistas de audio aparte, huecos o bloques encimados en la pista de video. Cada acción hace una sola pregunta guiada. Nunca se escriben en pantalla «timeline», «track», «clip», «capa», «frame», «render», «split» ni «trim».
- El patrón visual vive en `docs/design-system.md` §5.10 (ED-00b).

## 2. Decisiones firmadas por Deivid

### 2.1 Motor — firmadas el 2026-11-13

| # | Decisión (hecho firmado) | Fecha |
|---|---|---|
| D1 | El texto sobre el video lo dibuja **Remotion desde el inicio**: una capa PNG transparente con los diseños cerrados de ADR 49, también en la porción mínima. **Riesgo de licencia:** la licencia gratis de Remotion cubre equipos de hasta 3 personas y el equipo es de 5 → **decisión de pago pendiente de Deivid** (ver §2.3 y §6, que registran su respuesta del 2026-11-16). | 2026-11-13 |
| D2 | Humo, brasas y vapor son **bucles grabados con transparencia**, hechos una vez y versionados. | 2026-11-13 |
| D3 | Lo local **no descuenta cupo** (ni segundos de F1 ni vistas previas), con un **tope diario de piezas locales por negocio** que sale de la medición de EF-15. **Cifra: pendiente de EF-15** al firmar (EF-15 la midió después: §2.3). | 2026-11-13 |
| D4 | **Nunca `edit` con una persona**, tampoco en el video propio del dueño. | 2026-11-13 |
| D5 | Solo se ofrecen **efectos de Seedance medidos**: éxito ≥ 2/3 con n ≥ 4. | 2026-11-13 |
| D6 | Banco pagado de efectos de 5 s: **≈ US$28, tope US$30**, y **solo con OK explícito de Deivid antes de correrlo** (EF-12). | 2026-11-13 |
| D7 | **Preparar** trabaja solo sobre lo subido en el generador. | 2026-11-13 |
| D8 | La hoja de contacto la **revisa solo el dueño** (sin revisión de Claude en la fase 1). | 2026-11-13 |

### 2.2 Editor — firmadas el 2026-11-13

| # | Decisión (hecho firmado) | Fecha |
|---|---|---|
| D-E1 | Vista previa **en el navegador** (en vivo, gratis) **más un cuadro real del servidor**. | 2026-11-13 |
| D-E2 | La vista previa usa el **archivo local del teléfono** al subir y después una **copia liviana de 480p**. | 2026-11-13 |
| D-E3 | **Fichas** «Todo · 1 · 2 · 3…» en el celular y **línea de tiempo de solo lectura** en escritorio. *(Reemplazada el 2026-11-14 por D-T1…D-T6, §2.3.)* | 2026-11-13 |
| D-E4 | **«Idea»** (contexto general y de la parte) vive **dentro del editor** y el video pasa a **3 pasos**. | 2026-11-13 |
| D-E5 | Una parte ya creada se cambia **en el mismo editor** («Rehacer esta parte»). | 2026-11-13 |
| D-E6 | Los cambios se **guardan al momento**, con **«Deshacer»**. *(«Deshacer» retirado el 2026-11-19, §2.3.)* | 2026-11-13 |

### 2.3 Decisiones posteriores de Deivid que precisan las anteriores (tomadas al construir)

Se registran porque el código ya las aplica; no reemplazan la firma de este ADR.

| Fecha | Decisión | Dónde quedó | Toca |
|---|---|---|---|
| 2026-11-14 | D-T1…D-T6 de la línea de tiempo: foto quieta de 1–5 s; hasta 3 textos y un efecto repetible; «Velocidad» es acción del bloque, no un efecto; un cuadro por bloque ya, tira después; sin zoom; en el celular solo arrastrar | `docs/design-system.md` §5.10 | D-E3 (la reemplaza) |
| 2026-11-16 | Licencia de Remotion: «usemos la free solo somos 3 personas»; `remotion_selfhost` sigue en US$0,00 | PR #724, m-25026573 | D1 |
| 2026-11-16 | Tope diario: **10 armados locales por negocio y por día** («10 al día (Recomendado)»); variable `QUALIFY_LOCAL_DAILY_CAP` | `docs/armado-local-medicion.md`, `creative/local_cap.py`, PR #735 | D3 |
| 2026-11-16 | El dueño elige el fundido de cada texto: 0,3–1,0 s, 0,5 s por defecto | PR #724 | D1 |
| 2026-11-16 | Categorías cerradas de efectos (comida, texto, transición, movimiento, general) para filtrar, sin ocultar | `effects_data/v3.json` | §1.4 |
| 2026-11-16 | Cámara rápida con resultado < 3 s o > 60 s → avisar y no crear | EF-06 | §1.5 |
| 2026-11-17 | Velocidades ×2 ×3 ×5 ×10 ×20, cada una solo si el resultado dura 3–60 s; sin «Desde/Hasta» | PR #739 | D-T3 |
| Antes del 2026-11-17 (merge de #741; lo decidió el fundador, m-25042483) | Fuentes de más de 4K o de más de 8 bits: «Bajarlos a 4K 8 bits» en el `media-worker` antes del armado | revisión `0171`, PR #741 | §1.5 |
| 2026-11-19 | Sin «Deshacer» en el editor | `Qualify/clip_editor_view.py` | D-E6 |
| 2026-11-20 | La pista «Efectos» gana filas que aparecen y desaparecen solas; un efecto pasa de una fila a otra arrastrándolo | PR #759 | §1.7 |
| 2026-11-20 | Normalizador con `bframes=1` (no 3: 679 MiB, demasiado cerca de 768m) | PR #760, m-25071265 | §1.5 |

## 3. Encaje con las reglas y los ADR firmados

| Regla / ADR | Cómo encaja |
|---|---|
| Aislamiento por negocio | Cada tramo pasa por `owned_by` (raíces `t/`, `gallery/`, `uploads/`, `generated/`, `reel-windows/` del negocio) y se copia por `ObjectGate`; `gallery_jobs` va por `tenant_session` con RLS. La biblioteca y sus bucles son globales y de solo lectura, sin dato de ningún negocio. |
| Un Postgres (ADR 31) | Sin tabla ni servicio nuevo para el motor: la receta va en el JSON del brief y la biblioteca en el repo. La única revisión de la épica, `0171`, agrega un tipo de trabajo a una cola que ya existía (ADR 47). |
| Comprar lo genérico, construir el núcleo | Seedance sigue comprado; lo que construimos es lo barato y propio (preparar, cámara rápida, capas, texto, unión) con PyAV y el Remotion que ya teníamos. |
| Asistido, nunca autónomo | Nada se publica solo: la pieza local se aprueba como cualquier otra; los finales de Seedance siguen la confirmación de ADR 41. D8: revisa el dueño. |
| Procedencia | `params.local` del asset: contrato de receta, versión del motor, tabla de precios, versiones de cada paso, `sha256` de cada bucle, sonido por tramo; `mode_rule_version` y `mode_reason` en cada parte. |
| Idempotencia | Reintentar una preparación reescribe las mismas llaves de la misma revisión; el cobro es una fila en cero por revisión; `normalize_local` con `ON CONFLICT DO NOTHING`; `jobId` de Remotion derivado del contenido (como ADR 49). |
| Trabajo caro fuera de la petición | Todo armado corre en el `creative-worker` y la normalización en el `media-worker`; Reflex solo simula en el navegador (D-E1). |
| ADR 44 F1 (cupo en segundos de Seedance) | Se precisa: una pieza o parte `local` no descuenta segundos ni vistas previas (D3); la protege el tope diario. |
| ADR 44 F6 | D4 la extiende al video propio. |
| ADR 49 | El texto usa sus diseños cerrados (hoy solo `scrim`, plantilla `video_text` v1) y su motor de capa; el carrusel queda fuera de esta épica. |
| Etiqueta de IA | `ai_generated` se lee de lo que se hizo, no del tipo: una pieza local sale `False`; una con Seedance, `True`. |

## 4. Alternativas descartadas

| Alternativa | Por qué no | Qué la reabriría |
|---|---|---|
| **El Clip como un `SHOT_VIDEO` de una sola parte** (todo pasa por «Video por partes») | Deivid no quiere pasar por partes para poner un texto y un efecto; además duplica padre + hijo, unión y aprobación para un video de un tramo. El motor sobre `CLIP` sirve a los dos casos sin eso. | Que el Clip y la parte necesiten ciclos de vida que no quepan en un solo editor. |
| **Tabla de efectos en Postgres** | Los efectos los escribimos nosotros, no los negocios: git les da revisión y procedencia exacta, se validan una vez al cargar (como `pricing_data/`) y no piden migración ni RLS. | Efectos propios de un negocio, efectos subidos por el dueño o más de ~200 entradas. |
| Elegir el modo con un LLM | Cuesta en cada cambio de la vista previa y no es reproducible; una tabla de reglas da motivo legible a US$0. | Que la regla se equivoque más de lo que acepte el golden set de EF-10. |
| Texto con Pillow o `drawtext` de ffmpeg | ADR 49 descartó Pillow para dibujar; dos motores de texto darían dos estilos de marca. | Que Remotion pase a ser de pago y el costo pese (D1). |
| Fuego y humo generados en cada pieza (en el servidor o con Seedance) | Gastan CPU o dinero en cada pieza; un bucle hecho una vez se ve igual en la vista previa y en el video final. | Un efecto que dependa del contenido del cuadro (EF-13, con Seedance medido). |
| Revisión de la hoja de contacto por Claude | Sin medición que la justifique en la fase 1 (D8). | Quejas de calidad repetidas o una medición con errores que el dueño no ve. |
| Un editor de video completo | Fuera de lo que necesita un dueño en el teléfono; multiplica el costo de construirlo y de explicarlo. | Pedidos repetidos de clientes reales por algo de la lista de §1.7. |

## 5. Costo y volumen

- **Proveedor:** US$0 por pieza local (`local_video` = US$0,00 el segundo; Remotion propio en US$0 mientras rija la licencia gratis, D1).
- **Servidor** `[V]` (EF-15, `docs/armado-local-medicion.md`): 150–550 MiB anónimos bajo el límite de 768m del `creative-worker`; de ~2–2,5 min de worker (1080p, a 1080×1920 desde m-25041163) a ~5–12 min (4K de celular) por pieza. Con el tope de 10 al día, ~**1,7 h de worker por negocio y día** con 4K típico; con el peor caso medido (5K de 112 s, ~25–30 min por pieza), unas 4–5 h.
- **Seedance**, solo cuando el efecto la pide: el cupo en segundos de ADR 44 F1, sin cambios. **Banco de medición (D6): ≈ US$28, tope US$30, una sola vez**, con OK de Deivid.
- **Filas:** ninguna tabla nueva; `gallery_jobs` suma a lo sumo un trabajo `normalize_local` por archivo grande.

## 6. Diferencias con lo construido (`main` en `ab39151a`, 2026-11-20)

No se «arreglaron»: se anotan para que Deivid decida si firma el texto original o lo construido.

1. **D1, licencia de Remotion.** El ticket la deja como «decisión de pago pendiente». Deivid ya respondió el 2026-11-16 en el PR #724: «usemos la free solo somos 3 personas». Pero `qualify-context` nombra a cinco personas (Herwin, Darwin, Yesika, Deivid, Raúl) y la épica también dice «el equipo es de 5». La decisión está tomada; el riesgo de licencia sigue abierto.
2. **D1, «también en la porción mínima».** Construido para piezas `local` (EF-05 #724, EF-06 #730). Sobre una pieza hecha con Seedance el texto todavía se rechaza (`unbuilt_recipe_problems`) hasta EF-14.
3. **D2.** Construido (EF-08 #733). Los bucles no salen de una cámara: son procedurales, hechos una vez con `packages/creative/scripts/make_effect_loops.py` (VP9 WebM sobre negro, mezcla `screen`). Cumplen «hechos una vez y versionados».
4. **D3, cifra del tope.** El ticket pide marcarla «pendiente de EF-15». EF-15 ya la midió y Deivid eligió **10 al día** el 2026-11-16 (`DEFAULT_LOCAL_DAILY_CAP = 10`, PR #735). §2.1 la deja como pendiente al firmar y §2.3 da la cifra.
5. **D7, «solo sobre lo subido en el generador».** El editor también acepta como tramos propios archivos de la **Galería** (`gallery/…`) y de **Publicaciones** (PR #739). `owned_by` acepta esas raíces y `local_sources` las normaliza. Lo ajeno sigue fuera: una inspiración nunca se vuelve tramo propio. En la práctica, D7 quedó ampliada a «lo propio del negocio».
6. **D8.** EF-18 (hoja de contacto, m-25026598) no tiene commits; hoy el dueño revisa el video armado sin hoja de contacto.
7. **D-E1.** La vista previa en el navegador está construida (ED-01 #683, ED-01b #722). El «cuadro real del servidor» no aparece en el código.
8. **D-E2.** ED-09 (copia de 480p, m-25026643) no está construido; hoy el teléfono descarga el original (`Qualify/creative_state.py`, `_clip_playable`).
9. **D-E3, reemplazada** el 2026-11-14 por D-T1…D-T6: línea de tiempo editable en celular y escritorio, construida en ED-10 #739. `design-system.md` §5.10 todavía dice «pendiente de firma» (m-25029104) aunque ya está en `main`.
10. **D-E4.** ED-06 (m-25026636) sin commits: el editor ya tiene la pestaña «Pedir una idea», pero el paso a 3 pasos no está.
11. **D-E5.** ED-08 (m-25026640, «Rehacer esta parte») sin commits; el editor tampoco está montado todavía en Video por partes (ED-07, m-25026638).
12. **D-E6.** Se guarda al momento, como se firmó. El «Deshacer» se quitó el 2026-11-19 por decisión de Deivid (`clip_editor_view.py`), pero `design-system.md` §5.10 todavía lo describe («sin temporizador, 10 pasos»).
13. **«Sin pistas múltiples ni arrastre libre en el tiempo»** (fuera de alcance según la épica). Lo construido tiene tres pistas (Fotos y videos, Textos, Efectos), y Efectos suma filas cuando dos efectos se encimarían (ED-04 #759, Deivid 2026-11-20). Textos y efectos se deslizan en el tiempo con imán de ½ s y se recortan con tiradores. Sigue sin zoom, sin fotogramas clave y sin recorte cuadro a cuadro. §1.7 describe lo construido; la nota de la épica era más estricta.
14. **«Sin migración en la fase 1».** La receta no la tiene. La épica sí sumó la revisión `0171` (`gallery_jobs` con `normalize_local`, m-25042483) para fuentes de 4K de 10 bits y 5K.
15. **«`extend` fuera hasta m-24880328».** La regla de modo ya devuelve `extend` para la segunda mitad de un corte largo, pero solo con el interruptor `QUALIFY_PARTS_EXTEND` de m-24880328 (en `main` desde #680). Apagado, devuelve `reference`.
16. **Transiciones.** `fundido` y `barrido` figuran como ofrecidas (`offered: true`) en v3, pero EF-16 (m-25026594) no está construido y el motor las rechaza al crear (`recipe_unavailable`). La pantalla podría ofrecer algo que después se niega.
17. **`choose_clip_mode`** existe pero no está conectada a ninguna pantalla (lo dice su docstring).
18. **D4, D5 y D6 coinciden con el código.** D4: un video propio siempre sale `local` y la fila `own_video_ai_effect` es inalcanzable. D5: las cinco plantillas de Seedance tienen `offered: false` y `measured: null`. D6: EF-12 (m-25026587) sin commits; el banco no se corrió.
19. **Normalizador local sin ADR propio.** ADR 47 es la Galería y su `media-worker`; el normalizador local (m-25042483) corre en ese worker, pero no tiene ADR propio.
20. **Puesta en marcha.** El editor está detrás de `QUALIFY_CLIP_EDITOR`, todavía apagado en producción; el criterio de la épica «el caso mínimo funciona en producción» sigue abierto.

## 7. Consecuencias

- Un solo camino de código para el Clip y para la parte; un efecto nuevo es una entrada de JSON más y, si hace falta, un paso del motor. Lo que el motor no dibuja se rechaza antes de cobrar.
- El `creative-worker` carga CPU real, no solo espera a proveedores; el tope diario y la normalización previa en el `media-worker` lo mantienen dentro de 768m.
- La vista previa y el video final usan los mismos bucles y el mismo reloj: lo que se ve gratis es lo que sale.
- La frontera «estilo de editor, no editor» se mueve con cada decisión de pantalla (§6, punto 13); se vigila en `design-system.md` §5.10.

## 8. Qué lo reabriría

- Que la licencia gratis de Remotion deje de cubrir al equipo real, o que Remotion cambie sus términos (D1).
- Que un armado local pase de ~600 MiB anónimos, o que el tope de 10 al día frene a más del 10 % de los negocios activos en un mes (D3).
- Que un efecto de Seedance llegue a ≥ 2/3 con n ≥ 4 en el banco (D5/D6): entra a la oferta como entrada nueva de la biblioteca.
- Un análisis barato del video del dueño que diga si aparece una persona (reabre D4 y la fila `own_video_ai_effect`).
- Quejas repetidas de clientes por algo de la lista de §1.7.
- Que la regla de modo falle más de lo que acepte el golden set de EF-10 (m-25026578).
