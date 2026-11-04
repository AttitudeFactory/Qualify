# Épica — Video por partes: armar un video plano por plano desde un reel (o sin él)

`[ADR 44 DECIDIDO por Deivid Vargas el 2026-11-02 · m-24921048 · sin implementar]` · Pedido del fundador (Deivid, 2026-11-02). Fila 44 en [`arquitectura.md`](arquitectura.md) §6 (sin commit).

Épica en Meegle: [m-24921048](https://project.larksuite.com/5h2wsx/story/detail/24921048).
Documentos de origen, escritos el mismo día por los cuatro agentes y verificados contra `main` en `56746531`:

| Documento | Autor | Qué aporta |
|---|---|---|
| [`diseno-video-por-planos.md`](diseno-video-por-planos.md) | principal-architect | §1–§12: modelo (cada parte = pieza hija), ruta por modo, unión local, avatares, contratos, costos, riesgos. **§13 (decisiones del 2026-11-02) manda sobre §1–§12 donde se contradicen:** tablas globales, `reels-worker`, cadena mínima de ADR 42, cupo en segundos, entrada C |
| [`ux-video-por-planos.md`](ux-video-por-planos.md) | ux-designer | Nombres en pantalla, flujo guiado de punta a punta con mockups (escritorio y 375 px), copy de todos los estados, historias de UI UI-1…UI-10, preguntas P1–P6 |
| [`traspasos/historias-video-por-partes-backend.md`](traspasos/historias-video-por-partes-backend.md) | backend-engineer | VE-03, VE-04a/b/c/d, VE-12 reescritas el 2026-11-02 a global + `reels-worker`; contrato con la UI; qué suma cada R de ADR 42; riesgos |
| [`traspasos/historias-video-por-partes-creative.md`](traspasos/historias-video-por-partes-creative.md) | creative-engineer | VE-02, VE-06…VE-10b, VE-13…VE-20 verificadas contra el código, cobro y cupo, orden de entrega, riesgos N1–N12 |

Investigación previa: m-24880680 (decisiones D1–D3: Haiku como VLM, rostros en la misma llamada, familias cualitativas cerradas) y m-24888194 (inventario real de ScrapeCreators: transcripción con tiempos, filtros, costos).

## 1. Qué se quiere

Como dueño/a de un negocio quiero que mi video se arme **por partes** —cada parte es un plano del reel que elegí en «Ideas para tus reels», o una parte que agrego sin reel—, elegir para cada parte cómo se hace, darle su contexto y sus fotos, rehacer solo la parte que no me gustó y recibir **un solo video completo** para aprobar.

Los tres modos de Seedance 2.5, en palabras del dueño (UX §2):

| Modo | En pantalla | Qué hace | Por defecto cuando |
|---|---|---|---|
| `edit` | «Igual al original, con tu producto» | Rehace ese plano del reel con el producto y la marca: conserva encuadre, cámara y acción | el plano no muestra personas ni rostros (`not_observed`) |
| `reference` | «Nueva, inspirada en el original» (sin reel: «Nueva, con tu producto») | Crea un plano nuevo que sigue la ficha de Haiku y las fotos del producto; ningún byte del reel va al proveedor | personas o rostros `observed` o `unknown`; partes sin reel |
| `extend` | «Sigue a la anterior» | Continúa la parte anterior ya generada | plano > 10 s partido en dos; elección del dueño; entrada «Alargar un video que ya tienes» |

Lo que fijan las decisiones y los cuatro documentos:

- **No es un tipo de publicación nuevo en pantalla:** es un Clip (o un Avatar) con más de una parte; un video de una parte es el Clip de hoy.
- **Cada parte es una pieza hija** (`content_drafts.parent_draft_id`, `part_index`) con su prompt, sus referencias, su modo, sus versiones y su final; usa la cola de ADR 41 **ya construida** (0096/0098/0099, `creative-worker`) sin tipos de trabajo nuevos.
- **El reel se analiza al listar, en la corrida semanal de ADR 42, en tablas globales** (`public_reel_analyses`, `public_reel_analysis_shots`, sin tenant, precedente 0036) y **solo lo ejecuta el `reels-worker`**: baja el video a archivo temporal mientras la URL del CDN vive, detecta planos con PyAV (sin dependencia nueva) y pide a Haiku una ficha por plano con personas y rostros (≈ USD 0,0055 por reel). La pantalla solo encola (`wanted_at`, para un reel aún sin análisis) y consulta. Reflex nunca analiza nada.
- **La IA junta cortes seguidos en partes de 4–10 s, tope 6** (P2); modo por defecto: `edit` sin personas observadas, `reference` con personas o duda; nunca pasar solo a Avatar (F6).
- **La unión es local y determinista** (PyAV, costo 0). Unir con `edit` de Seedance queda como prueba medida (VE-18) y, solo si sale bien, como opción «Suavizar las uniones con IA» (VE-19).
- **Una sola aprobación** del video completo (F8) cobra los **segundos** de todas las partes (F1 = b, todo o nada) y pide los finales 1080p en el carril nocturno; el video unido pasa por la confirmación de ADR 41. Los finales de parte quedan en `part_final`, nunca publicables.
- **Retención (F9):** fuente y fotogramas del reel ajeno a 30 días, la ficha a 90; purga global del `reels-worker`.
- **«Extender video» es la entrada C** (P5): «Alargar un video que ya tienes» = Parte 1 fija (tu video, sin cobro) + Parte 2 «Sigue a la anterior».

## 2. Correcciones al diseño que trajeron los ingenieros (ya incorporadas a los tickets)

| # | Hallazgo | Quién | Dónde queda |
|---|---|---|---|
| 1 | La clave única no puede llevar el hash (se conoce después de bajar el video). Va `UNIQUE (network, post_id, analysis_version)`; el hash es procedencia | backend | VE-03 |
| 2 | Reflex en producción es **un solo proceso de 512 MiB**; nada de bajar ni decodificar reels allí. Resuelto de raíz con F3/F5: lo hace el `reels-worker` | backend / ADR 44 | VE-04a |
| 3 | La transcripción con tiempos de Instagram **ya se paga al listar y se descarta**; los subtítulos de TikTok traen tiempos gratis. Se guardan (`public_reels.transcript_segments` en R3) | backend | VE-04b, R3 |
| 4 | Cobrar los videos en la pieza padre no funciona: el ejecutor de ADR 41 rechaza el final de una hija sin cargo propio. Va `charge_videos_many` (segundos por hija, una transacción) | creative | VE-10b, VE-21 |
| 5 | Un video sin bloque `draft` es publicable: la vista previa unida de 480p saldría a Instagram. El unido lleva su bloque `finish: "join"`; el padre nunca espera en `drafting` | creative | VE-10a |
| 6 | Partes de 4 o 6–9 s no pasan el validador de duración; crear N hijas no es atómico; cada hija llamaría a Claude; una versión no recuerda su brief (`piece_versions.brief_id`) | creative | VE-06, VE-08, VE-03 |
| 7 | La salida cruda de cada parte ya la guarda el worker (`.bin`); hay que anotar la clave y copiarla a `.mp4` para `extend` | creative | VE-09, VE-13 |
| 8 | **Bug previo, fuera de la épica:** la referencia de una diapositiva animada no pasa el control de negocio (`_key_problems`) | creative | BUG-01, antes de VE-09 |
| 9 | `PURGEABLE_ROOTS` y `require_tenant_prefix` solo conocen claves `t/{tenant}/`: la fuente pública necesita una puerta aparte en `qualify_shared` acotada a `public/reel-analyses/` (la reutiliza R12) | backend / architect | VE-03, VE-12 |
| 10 | `consumption_scope` exige un negocio: el costo de un análisis compartido queda en la fila (`cost_usd`, tokens) y en Langfuse, no en el libro de consumo de un negocio | backend / architect | VE-04c |

## 3. Historias en Meegle

Áreas: **AR** principal-architect · **BE** backend-engineer · **CR** creative-engineer · **UI** reflex-ui-engineer (revisión de ux-designer antes del PR) · **DS** data-scientist-fde · **PL** platform-engineer. Tamaño S/M/L. Un ticket = un PR (`Resolves m-<id>`). Las dependencias están cargadas en Meegle como «Bloqueado por». VE-01 queda cerrada en cuanto se abra el PR con la fila del ADR 44 y este documento.

### Fase 1 · pista ADR 42 (tickets de la épica m-24854843; entran aquí en paralelo, no se duplican)

| Ticket | Id | Título | Área | Qué suma para el análisis | Depende de |
|---|---|---|---|---|---|
| [m-24854844](https://project.larksuite.com/5h2wsx/issue/detail/24854844) | R1 | Mudar el cliente de ScrapeCreators y el pipeline de reels a `packages/api` | BE | Los lectores de transcripción con tiempos (VE-04b) nacen allí; `ReelSource` se arma en el servicio | — |
| [m-24854847](https://project.larksuite.com/5h2wsx/issue/detail/24854847) | R2 | Puerta medida de ScrapeCreators (reducida: sin alerta a Lark) | BE | El test estático cubre `reel_analysis*` sin excepciones; la transcripción pasa por la puerta | R1 |
| [m-24854845](https://project.larksuite.com/5h2wsx/issue/detail/24854845) | R3 | Migración de reels públicos globales y tablas por negocio con RLS | BE | `public_reels.video_url` + `video_url_at` y `transcript_segments`; `reel_id` = `post_id` del análisis (sin FK) | — |
| [m-24854848](https://project.larksuite.com/5h2wsx/issue/detail/24854848) | R4 | Corrida persistente que comprueba el brief antes de pagar | BE | Al cerrar la corrida `ok`, encola el análisis de cada idea (`analyze_run_ideas`); adelanta las 6–8 ideas de R11 | R2, R3 |
| [m-24854849](https://project.larksuite.com/5h2wsx/issue/detail/24854849) | R5 | Topes por negocio | BE | Tope de análisis por corrida y negocio (10) y de flota (1.500/día); el análisis no gasta créditos | R2, R3 |
| [m-24854855](https://project.larksuite.com/5h2wsx/issue/detail/24854855) | R8 | `reels-worker` con la corrida semanal | BE + PL | Único ejecutor de `run_analysis`: rol `qualify_reels_worker`, carril de análisis (`drain_once`), purga global diaria; `mem_limit` medido | R4, R5 |
| [m-24854854](https://project.larksuite.com/5h2wsx/issue/detail/24854854) | R7 | La vista lee la BD: abrir no llama al proveedor | UI + UX | Tarjeta con «Aparece una persona» / «Sin analizar»; sin R7 la corrida analizaría reels que el dueño no ve | R4 |

### Fase 1 · análisis, partes «Nueva» e «Igual al original», unión local, cupo en segundos, pantalla

| Ticket | Id | Título | Área | P | T | Bloqueado por |
|---|---|---|---|---|---|---|
| [m-24921049](https://project.larksuite.com/5h2wsx/issue/detail/24921049) | VE-01 | Arquitectura: firmar el ADR 44 «Video por partes» y resolver F1–F10 | AR → fundador | P0 | S | — (decidido; falta el PR) |
| [m-24921086](https://project.larksuite.com/5h2wsx/issue/detail/24921086) | BUG-01 | Generador: la referencia de una diapositiva animada no pasa el control de negocio (fuera de la épica) | CR | P1 | S | — |
| [m-24921139](https://project.larksuite.com/5h2wsx/issue/detail/24921139) | VE-21 | Generador: cupo de video en segundos al mes (F1 = b) para clips, galería, avatar y video por partes | CR + BE + UI | P1 | L | VE-01; cifras 40/80/160 s por confirmar con Herwin |
| [m-24921062](https://project.larksuite.com/5h2wsx/issue/detail/24921062) | VE-02 | Video: detectar planos, sacar fotogramas y cortar ventanas con PyAV | CR | P1 | M | VE-01 |
| [m-24921055](https://project.larksuite.com/5h2wsx/issue/detail/24921055) | VE-03 | Migración: análisis global de reels y partes de un video | BE | P1 | M | VE-01, R3 (siguiente número libre después de R3: hoy `main` llega a 0116 y R3 toma 0117) |
| [m-24921064](https://project.larksuite.com/5h2wsx/issue/detail/24921064) | VE-07 | Video: unir partes con PyAV | CR (+PL) | P1 | M | VE-01 |
| [m-24921056](https://project.larksuite.com/5h2wsx/issue/detail/24921056) | VE-04a | Referentes: encolar y ejecutar el análisis de un reel en reels-worker | BE | P1 | M | VE-03, R1, R4 |
| [m-24921057](https://project.larksuite.com/5h2wsx/issue/detail/24921057) | VE-04b | Referentes: guardar con sus tiempos la transcripción que ya se paga | BE | P2 | S | R1, R3 |
| [m-24921063](https://project.larksuite.com/5h2wsx/issue/detail/24921063) | VE-06 | Generador: tipos del plan de partes y sus validadores | CR | P1 | M | VE-01, VE-03 |
| [m-24921058](https://project.larksuite.com/5h2wsx/issue/detail/24921058) | VE-04c | Referentes: ficha del reel por planos con Haiku (familias D3 y rostros), en reels-worker | BE | P1 | L | VE-04a, VE-02, R8 |
| [m-24921059](https://project.larksuite.com/5h2wsx/issue/detail/24921059) | VE-04d | Referentes: cortar de la fuente pública la ventana de una parte «Igual al original» | BE | P1 | S | VE-04a, VE-02 |
| [m-24921050](https://project.larksuite.com/5h2wsx/issue/detail/24921050) | VE-05 | Medición: cortes y rostros del análisis de reels en 20 reels reales | DS | P1 | M | VE-04c |
| [m-24921065](https://project.larksuite.com/5h2wsx/issue/detail/24921065) | VE-08 | Generador: plan desde el análisis, piezas hijas y «Crear otra versión» de una parte | CR | P1 | L | VE-03, VE-06, VE-21 |
| [m-24921066](https://project.larksuite.com/5h2wsx/issue/detail/24921066) | VE-09 | Generador: parte «Nueva, inspirada en el original» y parte «Igual al original» | CR | P1 | L | VE-02, VE-08, VE-04d, BUG-01 |
| [m-24921067](https://project.larksuite.com/5h2wsx/issue/detail/24921067) | VE-10a | Generador: unir las vistas previas de las partes en el worker | CR | P1 | M | VE-07, VE-09 |
| [m-24921068](https://project.larksuite.com/5h2wsx/issue/detail/24921068) | VE-10b | Generador: aprobar el video completo, finales de las partes y unión final | CR (+PL) | P1 | L | VE-10a, VE-21 |
| [m-24921060](https://project.larksuite.com/5h2wsx/issue/detail/24921060) | VE-12 | Retención: borrar a los 30 días el video y los fotogramas del reel ajeno | BE | P2 | S | VE-03, VE-04a, R8 |
| [m-24921069](https://project.larksuite.com/5h2wsx/issue/detail/24921069) | VE-20 | Generador: las partes se conservan y se avisan con su video completo | CR | P2 | S | VE-10b |
| [m-24921075](https://project.larksuite.com/5h2wsx/issue/detail/24921075) | UI-1 | Generador: «Hacer uno parecido» en Ideas para tus reels abre Video por partes (+ «Aparece una persona» / «Sin analizar») | UI | P1 | S | R7 |
| [m-24921076](https://project.larksuite.com/5h2wsx/issue/detail/24921076) | UI-2 | Generador: espera del análisis (reducida: solo reels sin análisis) y sus estados de error | UI | P1 | S | UI-1, VE-04a |
| [m-24921077](https://project.larksuite.com/5h2wsx/issue/detail/24921077) | UI-3 | Generador: lista «Tu video, parte por parte» en el paso 2 | UI | P1 | L | UI-2, VE-08 |
| [m-24921078](https://project.larksuite.com/5h2wsx/issue/detail/24921078) | UI-4 | Generador: hoja para ajustar una parte (forma, qué pasa, fotos) | UI | P1 | M | UI-3 |
| [m-24921079](https://project.larksuite.com/5h2wsx/issue/detail/24921079) | UI-5 | Generador: armar un video por partes sin reel (mitad «Prefiero armarlas yo» en fase 1; «Proponerme las partes» en fase 2) | UI | P2 | M | UI-3 (VE-14 solo para la mitad con IA) |
| [m-24921081](https://project.larksuite.com/5h2wsx/issue/detail/24921081) | UI-6 | Generador: «Revisa y crea» por partes en el paso 5 | UI | P1 | S | UI-3, VE-21 |
| [m-24921082](https://project.larksuite.com/5h2wsx/issue/detail/24921082) | UI-7 | Generador: progreso y fallos por parte en el resultado | UI | P1 | L | UI-6, VE-09 |
| [m-24921083](https://project.larksuite.com/5h2wsx/issue/detail/24921083) | UI-8 | Generador: revisar y rehacer una parte («Me gusta así» / «Crear otra versión») | UI | P1 | M | UI-7, VE-08 |
| [m-24921084](https://project.larksuite.com/5h2wsx/issue/detail/24921084) | UI-9 | Generador: «Tu video completo», aprobar, vencimiento y «Cambiar una parte» | UI | P1 | M | UI-7, VE-10a, VE-10b, VE-21 |

### Fase 2 — «Sigue a la anterior» y entrada C, partes propuestas con IA, voz y subtítulos

| Ticket | Id | Título | Área | P | T | Bloqueado por |
|---|---|---|---|---|---|---|
| [m-24921070](https://project.larksuite.com/5h2wsx/issue/detail/24921070) | VE-13 | Generador: parte «Sigue a la anterior» (extend por parte) + entrada «Alargar un video que ya tienes» | CR | P2 | M | VE-10b, m-24880328 (entrega `extend`, sin pantalla propia) |
| [m-24921071](https://project.larksuite.com/5h2wsx/issue/detail/24921071) | VE-14 | Generador: «Proponer partes» sin reel | CR | P2 | M | VE-08 |
| [m-24921072](https://project.larksuite.com/5h2wsx/issue/detail/24921072) | VE-15 | Generador: «Voz de tu marca» y subtítulos en el video completo | CR | P2 | M | VE-10b |
| [m-24921052](https://project.larksuite.com/5h2wsx/issue/detail/24921052) | VE-16 | Medición: continuidad de «Sigue a la anterior» en 1080p y si el final vuelve a cobrar el video de entrada | DS | P2 | S | VE-13 |
| (por crear) | UI-11 | Generador: entrada «Alargar un video que ya tienes» dentro de Video por partes | UI | P2 | M | VE-13 |

### Fase 3 — presentador por partes y unión con IA

| Ticket | Id | Título | Área | P | T | Bloqueado por |
|---|---|---|---|---|---|---|
| [m-24921073](https://project.larksuite.com/5h2wsx/issue/detail/24921073) | VE-17 | Generador: parte con presentador (OmniHuman) dentro de un video por partes | CR | P3 | L | VE-10b |
| [m-24921085](https://project.larksuite.com/5h2wsx/issue/detail/24921085) | UI-10 | Generador: avatar por partes («¿Quién aparece?» por parte) | UI | P3 | L | UI-3, VE-17 |
| [m-24921054](https://project.larksuite.com/5h2wsx/issue/detail/24921054) | VE-18 | Prueba: unir las partes con el modo edit de Seedance (3 uniones de 15 s medidas) | DS + CR | P3 | M | VE-10b, VE-16 |
| [m-24921074](https://project.larksuite.com/5h2wsx/issue/detail/24921074) | VE-19 | Generador: «Suavizar las uniones con IA» (solo si VE-18 sale bien) | CR + UI | P3 | M | VE-18 |

### Orden de entrega (diseño §13.4, creative §5)

1. **Pista ADR 42 (ruta crítica):** R1 → (R2 ∥ R3) → R4 → R5 → R8 → R7.
2. **Pista del análisis, en paralelo:** VE-02 ∥ VE-03 → VE-04a (contra un almacén en memoria y un MP4 sintético; `just reel-analysis-tick` en local) → VE-04c (+ VE-05) → se enchufa al bucle cuando R8 esté en `main` (lo hace el segundo que llega). VE-04b tras R1 y R3.
3. **Pista creative:** BUG-01 → VE-02 ∥ VE-07 → VE-06 (con VE-03 en main) → VE-21 → VE-08 → VE-09 → VE-10a → VE-10b → VE-20; prueba con el análisis de ejemplo de VE-04a, sin esperar a la pista ADR 42.
4. **Pista UI:** UI-1 tras R7; UI-2…UI-9 siguiendo sus bloqueos; UI-5 (mitad manual) con UI-3.
5. **Antes de producción:** platform-engineer confirma `QUALIFY_CREATIVE_DISPATCHER=queue` (no aparece en `deploy/`; VE-08 rechaza el modo con hilos) y fija el `mem_limit` del `reels-worker` (objetivo ≤ 384 MiB).

## 4. Decisiones (ADR 44, Deivid Vargas, 2026-11-02)

| # | Pregunta | Decisión | Fuente |
|---|---|---|---|
| **F1** | ¿Cómo cuenta un video por partes en el plan? | **(b) Segundos de video al mes** para todo video de Seedance; reemplaza D5. Cifras propuestas: Básico 40 s, Plus 80 s, Pro 160 s, paquete +20 s (`[PROPUESTO]` hasta que Herwin las confirme: D5 y D15 las firmó él). Cada parte cuenta sus segundos pedidos; D6/D7 siguen; D9 devuelve en segundos | diseño §13.5, VE-21 |
| F2 | ¿Unión local o con `edit` de Seedance? | Local; `edit` solo tras VE-18 | diseño §5 |
| F3 | ¿Cuándo analizar el reel? | **Al listar, en la corrida semanal de ADR 42**; cola bajo demanda (`wanted_at`) para un reel sin análisis | diseño §13.3 |
| F4 | ¿Alcance y muestreo? | Reel completo ≤ 60 s; 2 fotogramas por plano + 3 anclas; 720×1280; tope 32 | diseño §4.1 |
| F5 | ¿Análisis global o por negocio? | **Global, sin negocio, junto a `public_reels`, hecho por el `reels-worker`** | diseño §13.2 |
| F6 | ¿Modo por defecto según personas? | `edit` sin personas observadas; `reference` con personas o duda; nunca pasar solo a Avatar | diseño §4.2 |
| F7 | ¿Partes sin reel en la fase 1? | A mano en la fase 1; «Proponer partes» con IA en la 2 | diseño §3 |
| F8 | ¿Una aprobación o una por parte? | Una, del video completo | diseño §3.2 |
| F9 | ¿Retención del reel ajeno? | Fuente y fotogramas a 30 d; ficha a 90 d; purga global del `reels-worker`. Pendiente aparte: lectura legal de guardar MP4 ajenos (solo referencia interna) | diseño §13.8 |
| F10 | ¿Se firma como ADR 44? | Sí (fila en `arquitectura.md` §6) | — |
| P2 | ¿Una parte es siempre un corte? | La IA junta cortes seguidos en partes de 4–10 s, tope 6 | UX §7 |
| P3 | ¿Voz y vista previa del presentador? | Su voz solo en sus partes; sin vista previa barata (se cobra en creaciones por segundos) | UX §3f |
| P5 | ¿«Extender video» es la entrada C? | Sí: «Alargar un video que ya tienes» = Parte 1 fija + Parte 2 «Sigue a la anterior»; m-24880328 entrega `extend` sin pantalla propia | diseño §13.6 |
| P6 | ¿Avisar que «Igual al original» conserva manos y fondo de otra cuenta? | Validar con 3 dueños; sin aviso en la fase 1 | UX §7 |
| Orden | ADR 42 no existe en main | R1, R2, R3, R4, R5, R7 y R8 entran en la fase 1 de esta épica, en paralelo | diseño §13.4 |

**Queda por decidir (no bloquea el arranque):** las cifras del cupo en segundos (Herwin); si R8 se parte en R8a (servicio, rol, análisis, purga) y R8b (corridas programadas) (backend §6); el texto de «Sin analizar» (ux-designer).

## 5. Tickets que esta épica absorbe, reemplaza o ajusta (comentarios ya dejados el 2026-11-02)

- **m-24880681** (replicar reel con persona vía VLM) → absorbido por VE-09.
- **m-24820834** (blueprint con Gemini y PySceneDetect) → reemplazado por VE-04c + VE-02; golden set de 20 en VE-05.
- **m-24880328 / m-24880378** (Extender video) → entrega `extend`; su pantalla se reemplaza por la entrada C (VE-13 + UI-11).
- **m-24880680** → sus pendientes quedan respondidos (F3, F4, F6); D1–D3 no se reabren.
- **ADR 42 R1–R5, R7, R8** → comentario con lo que suma cada uno para el análisis; R14 → UI-1; **ADR 41 §3.2** → `part_final` no pasa por `final_ready`; **D5** → reemplazada por F1 (VE-21).

## 6. Prompt para `/qualify-team-dev`

```
Épica m-24921048 «Video por partes», ADR 44 decidido 2026-11-02. Fase 1, un PR por ticket, tres pistas en paralelo:
- Pista ADR 42 (backend-engineer, platform-engineer para R8): m-24854844 (R1) → m-24854847 (R2, reducida) ∥ m-24854845 (R3) → m-24854848 (R4) → m-24854849 (R5) → m-24854855 (R8) → m-24854854 (R7, con reflex-ui-engineer). Cada uno lleva en su comentario lo que suma para el análisis.
- Pista del análisis (backend-engineer): m-24921055 (VE-03) → m-24921056 (VE-04a) → m-24921058 (VE-04c) → m-24921059 (VE-04d); m-24921057 (VE-04b) tras R1/R3; m-24921060 (VE-12) con R8; data-scientist-fde: m-24921050 (VE-05) con VE-04c en main.
- Pista creative (creative-engineer): m-24921086 (BUG-01) → m-24921062 (VE-02) ∥ m-24921064 (VE-07) → m-24921063 (VE-06) → m-24921139 (VE-21, con backend para la migración y UI para los textos) → m-24921065 (VE-08) → m-24921066 (VE-09) → m-24921067 (VE-10a) → m-24921068 (VE-10b) → m-24921069 (VE-20).
- Pista UI (reflex-ui-engineer, revisión de ux-designer antes de cada PR): m-24921075 (UI-1) tras R7; UI-2…UI-9 y la mitad manual de UI-5 siguiendo sus «Bloqueado por».
- platform-engineer: confirmar QUALIFY_CREATIVE_DISPATCHER=queue en producción, arnés de memoria para VE-07/VE-10b y mem_limit del reels-worker.
Cada brief cita docs/epica-video-por-partes.md, docs/diseno-video-por-planos.md §13 y el documento de su área en docs/traspasos/.
```
