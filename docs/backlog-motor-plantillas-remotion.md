# Backlog — Motor de Plantillas (Remotion)

> **`[OBSOLETO]` HeyGen — decisión del fundador, 2026-10-16.** Los videos con avatar migran a la suite de ByteDance (BytePlus): **OmniHuman** (el avatar que habla), **Seedance** (el video), **Seedream** (la imagen y el primer fotograma) y **Seed Speech** (la voz clonada). Toda mención a HeyGen en este documento describe el estado anterior o una alternativa ya descartada: no la tomes como decisión vigente. **La migración aún no está hecha en el código** (medido el 2026-10-16): el detalle y lo que falta está en [Pendientes del generador §6](pendientes-generador-contenido.md).

**Fecha:** 2026-10-05 · **Estado:** `[PLAN — decisiones del fundador cerradas 2026-10-05, listo para abrir historias]`
**Origen:** doc del fundador «Qualify — Módulo de Plantillas de Contenido: investigación y objetivo semanal» (Claude Docs, 2026-10-04) y la revisión contra el repo del 2026-10-05.
**Semana objetivo:** 5 al 11 de octubre de 2026, demo con tienda piloto el domingo 11.
**Plan por fases y contrato:** [plan-mvp-plantillas-remotion.md](plan-mvp-plantillas-remotion.md) — ordena estas historias en Fases 0 a 3, define el manifiesto de plantilla, el catálogo de producto y la biblioteca de prompts por nicho × ángulo.
**Módulo padre:** [Motor de Contenido de Marca](backlog-motor-contenido-marca.md) · [diseño técnico](diseno-motor-contenido-marca.md). Este backlog **no crea un módulo nuevo**: convierte el tipo de contenido «Con plantilla» (hoy un badge «Próximamente» que el brief rechaza) en el camino por defecto del generador.

---

## 0. Decisión rectora (fundador, 2026-10-05)

> **El motor de plantillas es Remotion. Se abandona el render Pillow.**

Esto revierte el §1.9 del diseño técnico (D15, `BrandTemplate` + render Pillow determinista, validado con POC el 2026-08-18) y el §5 de [research-bucle-vision-plantillas.md](research-bucle-vision-plantillas.md) («no cambies el target de render»). Se deja constancia para que nadie lo lea como un olvido. El código del POC (`packages/creative/src/qualify_creative/templates/`) queda como está hasta que el adaptador Remotion lo reemplace; no se borra en esta semana.

**Qué cambia para el producto, no para el código:**

| Antes (Pillow) | Ahora (Remotion) | Consecuencia visible |
|---|---|---|
| Imagen fija 4:5, un motor por salida | **Una plantilla, varias salidas**: video 9:16 y, cuando aplica, imagen fija 4:5 e historia, en una sola corrida (`renderStill` para las fijas) | Se replica el modelo de ElevenCreative Templates: un molde, varios assets. El flyer local deja de ser un tipo aparte |
| ~56 ms, sincrónico | 10 a 60 s, asíncrono | La pantalla necesita un estado «renderizando» con progreso, igual que hoy con HeyGen |
| $0 por pieza | Centavos por pieza (AWS) + licencia | Aparece un **costo estimado antes de ejecutar**, que hoy no existe para ninguna ruta |
| Sin dependencia externa | Cuenta AWS + licencia Remotion (gratis con equipo de 3 o menos; ver §0.1) | Un costo fijo que se activa con la cuarta persona del equipo, no con el primer cliente |
| Una plantilla = JSON | Una plantilla = composición TSX + JSON de mapeo | Las plantillas las escribe el equipo; el cliente nunca las ve ni las edita |

Lo que **no cambia**: el Post (`ContentDraft`) sigue siendo la columna vertebral; las piezas de imagen fija siguen existiendo, pero salen de la misma plantilla y no de un motor aparte; el brand kit, los assets y el producto se cargan donde ya se cargan; HeyGen sigue siendo el motor para «una persona hablando»; la aprobación humana sigue antes de publicar; música y audio siguen fuera (se ponen en la app de Instagram, ver diseño §1.7).

### 0.1 Licencia de Remotion — verificado en la fuente el 2026-10-05

Pregunta del fundador: ¿hay licencia «tech provider» con precio por consumo? **No existe un tier con ese nombre.** Remotion v5 tiene tres situaciones ([terms](https://www.remotion.dev/docs/terms), [FAQ](https://www.remotion.dev/docs/license/faq)):

| Situación | Precio | Aplica a Qualify |
|---|---|---|
| **Licencia gratuita** | USD 0 | Mientras el equipo sea de **3 personas o menos**. Los contratistas y agencias **cuentan** en ese número. Vale para uso comercial. |
| **Remotion for Creators** (asientos) | USD 25 por asiento al mes, sin mínimo | No: es para personas que editan con Remotion, no para pipelines |
| **Remotion for Automators** (renders) | **USD 0,01 por render**, cobrado en bloques de 1.000 (USD 10), con **mínimo de USD 100 al mes** | Sí: es el tier para «pipelines de video automatizados y herramientas prompt-to-video». Es el **precio por consumo**, con piso |

Tres datos que cambian el plan:

- **El piso de USD 100 cubre 10.000 renders al mes.** Con 100 clientes a 20 piezas son 2.000 renders: hasta ese volumen el consumo es irrelevante, se paga el piso. El costo por consumo real empieza a existir por encima de 10.000 renders.
- **Una imagen fija cuenta como un render**, igual que un video. Si cada plantilla saca video + imagen + historia en una corrida, son **tres renders**, no uno. El costo estimado que se muestra al usuario debe contarlo así.
- **La licencia la dispara el tamaño del equipo, no el cobrar por renders.** Hoy el repo tiene tres personas commiteando (Herwin, Deivid, yroa). A la cuarta persona, o al primer contratista, hay que pasar a Automators. **MP-05 queda resuelta:** gratis mientras el equipo sea de 3; Automators con la cuarta persona. La licencia se activa con una clave de `remotion.pro` en la configuración de render y reporta por telemetría; sin telemetría hay que mandar un reporte mensual.

### Lo que el doc del fundador asumía y el repo ya tiene

El doc partía de cero. Estas piezas **ya existen** y las historias las reutilizan, no las reconstruyen:

- El **Post**: brief + voz de marca + variantes de copy + FSM `drafting → generated → approved → staged → published`.
- El **brand kit** completo (logo, paleta, tipografía, tono, voz clonada) y la **biblioteca de assets** en R2, con wizard antes del login (PR #63, mergeado 2026-10-05).
- El **router** con presupuesto por tenant y registro de costos (`creative_usage_events`), que hoy elige proveedor de copy e imagen.
- Tres **motores con adaptador**: flyer local, HeyGen (avatar real y animado) y Canva como ida y vuelta de última milla.
- El tipo de contenido **«Con plantilla»** declarado en el enum, visible y deshabilitado.

Lo que el doc aporta y el repo **no** tiene: elegir la **receta** según los assets disponibles, una **biblioteca de plantillas de nicho** con nombre y versión, el **costo estimado de las tres opciones antes de ejecutar**, y la base para medir **plantilla × métricas**.

---

## 1. Objetivo de la semana

Que un Post real de Qualify, de una tienda de comida, termine en un video 9:16 publicable, renderizado por Remotion con las fotos reales del cliente, sin que el usuario elija herramienta ni plantilla: elige **qué comunicar** y el sistema propone la receta con su costo.

**Criterio de hecho al cierre (domingo 11):**

- [ ] Un Post aprobado con 2 o más fotos produce un MP4 9:16 descargable desde `/drafts/{id}`.
- [ ] Antes de renderizar, el usuario ve **tres opciones con costo** y la sugerida marcada; puede cambiarla.
- [ ] Existen **tres plantillas** de nicho comida con nombre y versión.
- [ ] El costo real queda registrado junto al estimado; la diferencia es visible al operador.
- [ ] HeyGen y UGC sintético aparecen en el selector como opciones con costo, aunque UGC no renderice todavía.
- [ ] Demo con la tienda piloto, video publicado o listo para publicar.

**Fuera de alcance esta semana:** editor visual de plantillas, que el cliente cree las suyas, publicación automática del video (va por el flujo de publicación existente), audio y música, UGC sintético renderizando de verdad.

---

## 2. Las tres plantillas iniciales

| Plantilla | Cuándo la sugiere el router | Qué recibe del Post | Qué sale |
|---|---|---|---|
| **Promo de plato** | 2 o más fotos del producto, sin video | gancho, fotos, precio, CTA, paleta y logo | Fotos con movimiento suave, texto que entra y sale, precio destacado, cierre con logo |
| **Menú del día** | el ángulo es «menú del día» o lista de varios productos | varios productos con foto y precio | Grid animado de platos, un precio por plato, cierre con CTA |
| **Corte de video real** | hay al menos un video del local | el clip, gancho, promo, CTA | El clip con marco de marca, tarjetas de texto con fade, cierre |

**Decidido (fundador, 2026-10-05):** la tercera plantilla es **«Corte de video real»**, no «testimonio con foto real». Un testimonio pide una persona hablando, que es la regla 1 del router y terreno de HeyGen, y la regla 3 del router exige una plantilla con video embebido.

**Cada plantilla produce varias salidas en una corrida**, como un template de ElevenCreative: el video 9:16 siempre; la **imagen fija 4:5** para feed y la **historia 9:16 fija** cuando la plantilla lo declara. Promo de plato y Menú del día sacan las tres; Corte de video real saca solo video. Esto reemplaza al tipo «Imagen tipo flyer» local, que se retira cuando las plantillas cubran el caso (MP-13).

---

## 3. El router, en términos de producto

El router mira el Post y devuelve **siempre tres opciones con costo**, marcando la sugerida. El usuario ve que una plantilla vale centavos y un UGC vale dólares, y decide. Cada decisión se guarda con la regla que la motivó y si el usuario la cambió, para ajustar reglas después.

| Orden | Si el Post… | Sugiere | Costo típico (30 s) |
|---|---|---|---|
| 1 | pide una persona hablando a cámara y el tenant tiene avatar | HeyGen, testimonio con avatar | USD 0,50 a 2,00 |
| 2 | tiene 2 o más fotos del producto, sin video | Remotion, Promo de plato | ~USD 0,03 |
| 3 | tiene al menos 1 video real del local | Remotion, Corte de video real | ~USD 0,12 |
| 4 | es «menú del día» o lista varios productos | Remotion, Menú del día | ~USD 0,03 |
| 5 | no tiene assets o pide una escena que el cliente no tiene | UGC sintético + voz (solo cotiza esta semana) | USD 1,50 a 3,50 |
| 6 | nada aplica | Remotion, Promo de plato con la foto principal | ~USD 0,02 |

Si el tenant tiene límite de gasto mensual y la sugerida lo excede, cae a la siguiente regla. Los precios son de octubre de 2026 y viven en configuración, nunca en código.

---

## 4. Historias

Convención: `MP-##`. Dueños según los agentes del repo. Tamaño S/M/L.

### Slice 0 — Decisión y contrato (lunes 5)

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **MP-00** | Enmienda al diseño técnico: §1.9 pasa de Pillow a Remotion con la tabla de consecuencias de §0 de este doc; se nombra lo que queda huérfano (POC de plantillas, research del bucle de visión). Foldeada en `arquitectura.md` §6 como ADR o enmienda. | — | principal-architect | S |
| **MP-01** | Contrato de **Template** (motor, nicho, requisitos de assets, mapeo de campos del Post a props, modelo de costo) y contrato de **adaptador de render** (`estimate`, `render`, `status`, `cancel`) como extensión del `GenerationProvider` existente, no como seam nuevo. Tarifas en `pricing` versionado. | MP-00 | principal-architect + pipeline | S |

**Aceptación MP-01:** un Post de prueba y una plantilla producen una estimación de costo y tiempo sin tocar red.

### Slice 1 — Orquestación (lunes 5 a martes 6)

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **MP-02** | El tipo «Con plantilla» deja de rechazarse en el brief; el draft que lo pide entra a la FSM existente y queda en «renderizando» hasta que el job termine. Reaper cubre renders colgados. | MP-01 | pipeline | M |
| **MP-03** | Adaptador stub que devuelve un MP4 fijo, para probar el flujo completo antes de tener Remotion. | MP-01 | pipeline | S |

**Aceptación:** un Post con tipo «Con plantilla» termina en `/drafts/{id}` con un video reproducible, aunque sea el fijo.

### Slice 2 — Remotion real (martes 6 a miércoles 7)

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **MP-04** | Proyecto Remotion en `packages/render/` con su `Dockerfile`, y adaptador real: recibe Post + plantilla, lanza el render (`renderMedia` / `renderStill`), reporta progreso y deja las salidas en el almacenamiento del tenant. **En Docker desde la Fase 1**: servicio `render` en `docker-compose.yml`, levantado por `just up`; Fase 2 despliega la misma imagen al VPS. **Lambda no es requisito** (plan §2.3). | MP-03 | pipeline | L |
| **MP-05** | Licencia Remotion, **resuelta en §0.1**: gratuita mientras el equipo sea de 3 personas o menos (contratistas incluidos); Automators (USD 0,01/render, piso USD 100/mes) con la cuarta persona. Queda escrita en `arquitectura.md` junto a MP-00, y el conteo de renders por corrida (video + imagen + historia = 3) entra en el modelo de costo de MP-01. | MP-00 | principal-architect | S |

**Aceptación MP-04:** render de la composición de prueba desde la API en menos de 30 s, con costo real registrado.

### Slice 3 — Plantillas de comida (miércoles 7 a viernes 9)

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **MP-06** | Plantilla **Promo de plato**: fotos reales + movimiento + texto + precio + cierre de marca. Duración derivada del libreto, no fija. Paleta y tipografía del brand kit por props. **Salidas:** video 9:16, imagen fija 4:5, historia fija 9:16, en una corrida. | MP-04 | reflex-ui-engineer / pipeline | M |
| **MP-07** | Plantilla **Menú del día**: grid animado de varios productos con precio. **Salidas:** video 9:16, imagen fija 4:5, historia fija 9:16. | MP-04 | ídem | M |
| **MP-08** | Plantilla **Corte de video real**: clip del cliente con marco de marca, tarjetas con fade, cierre. Incluye la **normalización del video al subir** con FFmpeg del lado Python (recorte a 7 a 15 s, sin audio, rotación corregida, H.264 1080×1920 para que el navegador lo previsualice); el encuadre y el fondo difuminado van en la composición. Cámara lenta y congelado en la composición; reversa y boomerang fuera del MVP (plan §2.4). **Salida:** solo video 9:16. | MP-04 | ídem | M |

**Aceptación:** tres MP4 9:16 más las imágenes fijas de Promo de plato y Menú del día, con fotos reales de prueba, revisados a ojo por el fundador. Cada salida queda en el draft con su posición, como hoy el carrusel. Si el jueves hay menos de dos listas, se lanza con dos y «Corte de video real» pasa a la semana 2.

### Slice 4 — Router y costo visible (viernes 9)

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **MP-09** | Router de receta con las seis reglas de §3, sobre el router existente. Devuelve tres opciones con costo y la sugerida marcada; guarda regla aplicada y si el usuario la cambió. Respeta el límite de gasto del tenant. | MP-01 | pipeline | M |
| **MP-10** | Pantalla: antes de renderizar, el usuario ve las tres opciones con costo y elige; durante el render ve progreso; al terminar ve el video, el costo estimado y el real. | MP-09, MP-02 | reflex-ui-engineer | M |

**Aceptación:** un test por regla; costo estimado contra real dentro del 30 %.

### Slice 5 — Integración y demo (sábado 10 y domingo 11)

| ID | Historia | Dep. | Dueño | Tamaño |
|---|---|---|---|---|
| **MP-11** | Un Post aprobado del generador actual dispara el render sin pasos manuales; el video queda en el draft y sigue el flujo de publicación existente. | MP-04..10 | pipeline | M |
| **MP-12** | Demo con la tienda piloto: registrar costos reales, lo que el usuario cambió al router y la lista de ajustes de la semana 2. | MP-11 | fundador | S |
| **MP-13** | Retirar el tipo «Imagen tipo flyer» local del generador cuando Promo de plato y Menú del día entreguen la imagen fija: la opción desaparece del selector, los drafts viejos siguen abriéndose, y el código de composición local queda marcado como reemplazado. Sin borrar código esta semana. | MP-06, MP-07 | reflex-ui-engineer | S |

---

## 4.1 Estado al cierre del día 1 (2026-10-05)

Construido y verificado en el worktree (sin commitear al escribir esto):

| Historia | Estado | Evidencia |
|---|---|---|
| MP-00 | parcial | decisión registrada en `CLAUDE.md`, plan y este backlog; la enmienda formal en `arquitectura.md` §6 sigue pendiente |
| MP-01 | **hecha** | `packages/render/CONTRACT.md`; `qualify_creative.render` (manifest, registry, props, recipes, client, adapter); 27 tests |
| MP-02 | **hecha** | `ContentKind.TEMPLATE` habilitado; `MediaProducer._template`; `template_runs` persistido; 8 tests |
| MP-03 / MP-04 | **hecha en host, Docker en construcción** | `packages/render/` renderiza `hello_world` y `promo_producto` (Reel 9,5 s + feed + historia) en la máquina; la imagen Docker se construye al cierre |
| MP-05 | **hecha** | licencia gratuita (≤3 personas) en §0.1; `remotion_selfhost` = 0,00 explícito en `pricing_data/v2.json` |
| MP-06 | **v1 hecha** | `promo_producto` v1 con tres salidas; revisión de diseño pendiente con fotos reales |
| MP-09 | **hecha** | `suggest_recipes` con las seis reglas; 10 tests |
| MP-10 | **hecha** | paso «Receta» en el generador con tres opciones, costo, ETA y sugerida; «Tu paquete» por salida |
| Catálogo (plan §2.1 #1) | **hecho** | migración 0038, `CatalogService` (fotos Pillow, video FFmpeg), pantalla `/catalog` |
| MP-11 | **hecha (PR `feat/mp11-publish-per-output`, pendiente de merge)** | «programar y publicar por salida»: migración **0040** `calendar_events.output_port` (0039 reservado a QUA-117), `PlannerService.schedule(output_port=)`, `get_publishable(output_port=)` con `media_product_type` derivado del puerto (`reel`→REELS, `feed`→IMAGE, `story`→STORIES, historia de imagen incluida), chips por salida y control «Salida» en el Planificador; sección «Eventos por salida (MP-11)» en `automatizacion-calendario-qua111.md`. Lo que el enunciado original de MP-11 llamaba «el video queda en el draft y sigue el flujo de publicación existente» es exactamente esto: el paquete llega a Instagram por el Planificador, una salida por evento |
| MP-07, MP-08, MP-12, MP-13 | pendientes | según calendario de §5 del plan |

**Huecos detectados al cablear la UI (semana 2):**

- **El router no sabe si el negocio tiene avatar.** `PostFacts.has_avatar` llega en `False`; la clonación de voz existe por marca pero el presentador se elige por pieza. Hace falta un hecho persistido «este negocio tiene presentador HeyGen» para que la regla 1 pueda disparar.
- **La marca no tiene nicho.** Los manifiestos declaran `niche`, pero el brand kit no tiene campo; hoy se filtra con `niche=None` y toda plantilla publicada aplica. Un campo `niche` en `brands` o en el kit hace útil el filtro.
- **El brief lleva el nombre del producto, no su id.** `product_ref` es texto y se resuelve por slug / nombre exacto / prefijo; un producto renombrado o dos con prefijo común pueden resolver mal. Un `product_id` en el brief lo hace exacto.

## 5. Riesgos

| Riesgo | Señal | Mitigación |
|---|---|---|
| Render en servidor más lento o pesado de lo previsto | un Reel de 30 s tarda más de 2 min en el VPS | Contenedor con CPUs asignadas y un render a la vez por tenant; Lambda detrás del mismo adaptador si no alcanza |
| Las composiciones consumen más días | jueves con menos de 2 listas | Lanzar con 2; «Corte de video real» a semana 2 |
| Fotos de clientes con tamaños dispares | videos con bordes o recortes feos | Normalizar a 1080×1920 con fondo difuminado antes del render (MP-08) |
| El costo Remotion es cero en el VPS y el estimado pierde sentido | todas las opciones Remotion muestran USD 0,00 | Mostrar tiempo de render junto al costo; HeyGen y UGC siguen con costo real, la comparación se mantiene |
| Dos runtimes en el repo (Python + Node para Remotion) | el `justfile` no sabe levantar Remotion | Nombrarlo en MP-00; un recipe `just render-dev` desde el día 1 |
| Cada corrida son 3 renders, no 1 | el costo estimado sale 3 veces menor que el real | El modelo de costo de MP-01 cuenta renders por salida; mientras el equipo sea de 3 el costo de licencia es cero y solo cuenta AWS |
| Un cuarto colaborador entra sin avisar | la licencia gratuita deja de aplicar | Regla escrita en MP-05; revisar headcount al sumar contratistas |

---

## 6. Preguntas cerradas por el fundador (2026-10-05)

| # | Pregunta | Respuesta |
|---|---|---|
| Q1 | Tercera plantilla | **Corte de video real.** |
| Q2 | Licencia Remotion | No hay tier «tech provider». El consumo es **Automators**, USD 0,01/render con piso de USD 100/mes; **gratis mientras el equipo sea de 3 o menos**. Detalle en §0.1. |
| Q3 | Flyer estático local | **Se retira.** Las plantillas cubren la imagen fija; se replica el modelo de ElevenCreative, un molde con varias salidas. Historia MP-13. |

---

## 7. Referencia: ElevenCreative Templates, leído en la fuente (2026-10-05)

Qualify replica el **modelo** de este feature, no su producto. Fuentes abiertas, no snippets: [Templates (docs)](https://elevenlabs.io/docs/eleven-creative/products/templates.md), [Flows (docs)](https://elevenlabs.io/docs/eleven-creative/products/flows.md), [List Templates](https://elevenlabs.io/docs/api-reference/flows/templates/list), [Create Template Run](https://elevenlabs.io/docs/api-reference/flows/templates/runs/create), [Get Template Run](https://elevenlabs.io/docs/api-reference/flows/templates/runs/get), [blog de lanzamiento de Templates (13 may 2026)](https://elevenlabs.io/blog/introducing-elevencreative-templates), [blog de la API (26 sep 2026)](https://elevenlabs.io/blog/introducing-the-image-video-and-templates-apis).

### 7.1 Qué es, en sus palabras

Un template es «un Flow con entradas y salidas definidas, empaquetado para correrlo sin ver ni editar el grafo de nodos». Se crea desde un Flow existente («Create Template») o desde cero; el autor marca qué nodos son **entradas** (lo que el usuario aporta en cada corrida) y qué nodos son **salidas** (al menos una). Se publica con alcance «solo yo», «workspace», «por enlace» o «Explore» (galería pública, con aprobación). Está en **beta**, disponible en todos los planes; el video solo en planes de pago.

### 7.2 El contrato que vale la pena copiar

| Pieza | Cómo lo hace ElevenCreative | Qué toma Qualify |
|---|---|---|
| **Puertos tipados** | Cada entrada y salida es un puerto con `id` y `content_schema`: `string` (con `enum` opcional), `image`, `video`, `audio`, `voice`, `number`, `integer`, `boolean`, `array` | El Template de MP-01 declara entradas y salidas como puertos tipados, no como «props sueltos». Permite validar un Post contra una plantilla antes de cotizar |
| **Versiones publicadas** | Un template tiene `versions[]`; cada corrida fija un `version_id` o usa `latest`. Una versión es un snapshot inmutable | Cada pieza guarda `template_id` + `template_version`. Es lo que hace calculable «la v2 rinde mejor que la v1» (diseño D16) |
| **Varias salidas por corrida** | `outputs` es un mapa por puerto; el ejemplo oficial devuelve un título, un still y un video de la misma corrida | Promo de plato devuelve video 9:16 + imagen 4:5 + historia en una corrida (MP-06) |
| **Estado por salida, y el global se deriva** | Cada salida tiene su `status`; el de la corrida es `pending` → `generating` → `completed`, o `failed` si alguna falló y todas terminaron | El draft muestra cada salida con su estado; una imagen lista no espera al video. Un fallo parcial conserva lo que sí salió (coherente con lo que hoy hace el draft con el guion cuando HeyGen falla) |
| **Motivo de fallo tipado** | `timeout`, `model_error`, `moderated`, `invalid_parameters`, `dependency_failed`, `charging_failed`, `internal_error` | La FSM ya exige motivo legible por máquina para `failed`; se adopta esta lista como base |
| **Webhook o polling** | `webhook` opcional en la corrida; sin él, consultar la corrida «a intervalo modesto» hasta estado terminal | El adaptador Remotion ya va por progreso + reaper; nada nuevo |
| **Costo estimado antes de correr** | En la UI: «puedes previsualizar el costo estimado antes de ejecutar». Créditos del plan, al mismo precio que correr los modelos a mano | MP-09/MP-10: tres opciones con costo antes de ejecutar. **Ojo:** la API de ElevenCreative **no devuelve costo ni créditos** en la corrida; Qualify sí lo guarda (estimado y real) porque es lo que alimenta al router |
| **URLs firmadas que caducan** | `content_url` vence a la hora | Igual que con HeyGen: descargar al almacenamiento propio apenas termine |

### 7.3 Lo que no se copia, confirmado

- **La galería como punto de entrada.** Su gallería son utilidades de propósito general: «Talking Avatar», «Remove background», «Change outfit», «T-Shirt Prints», «Device mockup», «Un-blur image». Ninguna es de nicho ni conoce la marca. En Qualify el usuario no elige plantilla; elige qué comunicar y el router elige la receta.
- **El canvas Flows.** Es donde se autoría: nodos de texto, subida de medios, generación (voz, imagen con 50+ modelos, video, música, SFX), lipsync, upscale, composición. Semanas de trabajo para una necesidad que el dueño de una tienda de comida no tiene. Las plantillas de Qualify las escribe el equipo en Remotion.
- **Sin brand kit.** Ni la documentación ni los blogs mencionan brand kit, paleta o consistencia de marca: la marca va metida en los prompts y referencias fijas de cada template. Qualify ya tiene el brand kit como activo versionado; la plantilla lo recibe por props. Es la ventaja estructural.
- **Modelos generativos como base.** Sus salidas son generadas (Veo, Sora, Kling, Nano Banana, Flux). Qualify compone **fotos y videos reales** del cliente. En comida, lo sintético delata (diseño §1.7).

### 7.4 Dos cosas que ElevenCreative ya resolvió y Qualify todavía no tiene en el backlog

1. **Entradas como referencias reutilizables.** Una corrida acepta `{"type":"asset","asset_id":…}` o la salida de una generación anterior (`{"type":"generation",…}`). En Qualify los assets ya viven en R2 por tenant; falta que el Template los reciba por referencia y no por copia. Entra en MP-01.
2. **Compartir una plantilla por enlace y por workspace.** Para Qualify es futuro (el cliente no autoría), pero el día que un operador administre varios negocios querrá la misma receta en todos. Queda anotado, fuera de esta semana.

**Posible proveedor, no competidor.** Su Templates API acepta un template publicado en su workspace y devuelve assets por webhook. Si algún día conviene una salida generativa (una escena que el cliente no tiene), ElevenCreative entra como un adaptador más detrás de la misma interfaz, en la regla 5 del router.
