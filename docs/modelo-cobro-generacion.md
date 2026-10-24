# Modelo de cobro y costo de la generación: creaciones, videos y vistas previas

Autor: data scientist / FDE · Fecha: 2026-10-24 · Para: Darwin (cofundador), que no estuvo en
estas conversaciones · Ticket: [m-24852128](https://project.larksuite.com/5h2wsx/issue/detail/24852128),
dentro de la épica de Deivid [m-24848869](https://project.larksuite.com/5h2wsx/story/detail/24848869)
(«Generación: pruebas de modelos, costos y modelo de cobro»).

Versiones vigentes: pesos **`pesos-creaciones-v2`** sobre la tabla de precios **`v7`**
(`packages/creative/src/qualify_creative/pricing_data/v7.json`). Modelo de video:
`dreamina-seedance-2-5-260628`. Presentador: OmniHuman 1.5. Imagen: `seedream-5-0-lite-260128`.
Texto: `claude-opus-5-5`.

**Cómo leer las cifras.** Cada número dice de dónde sale. Hay tres clases y no se mezclan:

- **medido**: sale de una factura, de una tarea real del proveedor o de la base de producción;
- **calculado**: sale de la tabla de precios `v7` y de la fórmula de tokens del proveedor, sin una
  tarea real que lo confirme;
- **hipótesis**: una suposición que todavía no comprobó ninguna prueba (§7).

Los costos son techos (p95 o peor caso), no promedios, salvo que se diga otra cosa.

---

## 1. Resumen para Darwin

**Qué ve el dueño.** Nunca dinero. Ve tres contadores que se renuevan el día 1 de cada mes:

| Contador | Cupo al mes | Qué gasta de él | Cuándo se descuenta |
|---|---:|---|---|
| **Creaciones** | 30 | Imágenes, carruseles, plantillas, guiones y el presentador (5/9/13/25 creaciones para 5/10/15/30 s) | Al crear; se devuelve si la generación falla |
| **Videos** | 4 | Cada video generado con Seedance (clip, avatar de Seedance, cada diapositiva animada de un carrusel), de 5 o 10 s | **Al aprobar**, que es cuando se encarga el video final en alta calidad |
| **Vistas previas** | 20 | Cada versión en calidad baja de un video, para decidir antes de aprobar | Al crear; no se devuelve salvo que el proveedor no haya entregado nada |

**Por qué así, en tres frases.**

1. La imagen, que es casi todo lo que se crea hoy, cuesta **USD 0,063 (p50) y 0,068 (p95)**
   (**medido** en producción, 23 pedidos, 2026-10-23). Con 1 creación = USD 0,15, 30
   creaciones son **USD 4,50 al mes por negocio como máximo** y un mes típico ronda USD 1,80.
2. Un video de Seedance 2.5 cuesta **unas 50 veces más que una imagen**: USD 3,44 el de 5 s y
   6,82 el de 10 s (**calculado** con `v7`). Medido en creaciones serían 23 y 46 de las 30 del
   mes, así que el video **no cabía** en las creaciones y pasó a tener su propio cupo de 4.
3. Del costo de un video, la vista previa en calidad baja es **~17 %** y el final en alta calidad
   **~83 %**. Por eso el video se cuenta al aprobar: descartar una vista previa no le cuesta un
   video al dueño, y así no le da miedo probar. Las vistas previas tienen su propio tope (20)
   para que probar sin límite no se vuelva un riesgo de costo.

**Lo que cuesta al equipo en el peor caso:** unos **USD 50 a 55 por negocio y mes** si el dueño
agota todo y sin videos de referencia (§6). Con videos de referencia de duración desconocida el
techo sube a unos USD 110 (§6, depende de dos hipótesis).

**Lo que está decidido y lo que falta.**

- En código ya fusionado (`main`): la tabla `v7`, el modo de vista previa de Seedance 2.5 (#304),
  la caducidad de 7 días y la reutilización del final ya pagado.
- En el PR #299 (abierto): creaciones del mes, pesos v1 → v2 y el cupo de 4 videos.
- En curso, sin commit todavía: contar el video al aprobar y el tope de 20 vistas previas.
- Pendiente: la fecha de caducidad en la tarjeta, el aviso en Inicio y «Pedir más a Qualify»
  (decisión 11).

**Lo que no se sabe todavía (§7):** cuánto cuesta de verdad un final a 1080p (no se ha medido
ninguno en vivo), si BytePlus cobra las tareas que fallan y si el final vuelve a cobrar el video
de referencia. Ningún cliente real ha creado todavía un video en producción.

---

## 2. El recorrido de un video y lo que cuesta cada paso

Ejemplo: un clip de Seedance 2.5 de 5 s y otro de 10 s, sin video de referencia, en 3:4 (la
proporción con más píxeles, que es la más cara). Costos **calculados** con `v7` según
`docs/creaciones-del-mes-medicion.md` §5.2 (rama del PR #299), salvo donde dice **medido**.

```
 ┌──────────────┐   ┌─────────────────────────┐   ┌──────────────┐   ┌─────────────────────┐   ┌───────────┐
 │ 1. Crear     │──▶│ 2. Vista previa (480p)  │──▶│ 3. Aprobar   │──▶│ 4. Final (1080p)    │──▶│ 5. Publicar│
 │ texto+imagen │   │ Seedance 2.5, borrador  │   │ el dueño     │   │ desde el mismo      │   │ IG / FB   │
 │ de partida   │   │ vive 7 días             │   │ decide       │   │ borrador, H.264     │   │           │
 └──────────────┘   └─────────────────────────┘   └──────────────┘   └─────────────────────┘   └───────────┘
   USD 0,068 fijo     5 s: 0,53  · 10 s: 1,06       USD 0              5 s: 2,85 · 10 s: 5,70      USD 0
   (texto p95 0,033   (medido 5 s: 0,5315)
   + imagen 0,035)
   ─────────────────────────────────────────         ─────────────     ───────────────────────────
   Cuenta 1 de 20 vistas previas (al crear)          Cuenta 1 de 4     Si falla: se devuelve el
                                                     videos            video y el reintento no
                                                                       cuenta otra vez
   Si nadie aprueba en 7 días: la vista previa vence, no se cuenta ningún video,
   la tarjeta ofrece «Crearla otra vez».
```

| Paso | Qué pasa (código) | 5 s (USD) | 10 s (USD) | Tipo de cifra |
|---|---|---:|---:|---|
| 1. Texto e imagen de partida | Claude escribe el texto (p95 0,033) y Seedream hace la imagen de partida (0,035) | 0,068 | 0,068 | medido en producción (`creaciones-del-mes-medicion.md` §2) |
| 2. Vista previa 480p | `draft: true` en Seedance 2.5; 9 870 tokens/s × USD 10,70 por millón = 0,1056/s | 0,53 | 1,06 | calculado; **medido 0,5315** a 5 s (49 673 tokens, tarea `cgt-20261024000242-qe2h5`, m-24849137, SD25-001) |
| **Subtotal hasta la vista previa** | | **0,60** | **1,12** | |
| 3. Aprobar | El dueño aprueba; se encarga el final con el id del borrador (`MediaProducer.finalize`) | 0 | 0 | — |
| 4. Final 1080p | 48 672 tokens/s × USD 11,70 por millón = 0,5695/s; pasa a H.264 y reemplaza la vista previa en la misma fila (`draft_mode.py`) | 2,85 | 5,70 | **calculado, nunca medido en vivo** (#304, «Pendiente en vivo») |
| **Total del video** | | **3,44** | **6,82** | calculado (`creaciones-del-mes-medicion.md` §5.5 y §6.4) |
| Parte de la vista previa | | 17 % | 16 % | calculado |
| Parte del final | | 83 % | 84 % | calculado |

Nota sobre el redondeo: en la conversación del 2026-10-24 se usaron 0,60 + 2,84 (5 s) y
1,19 + 5,63 (10 s). Los totales (3,44 y 6,82) coinciden con los de esta tabla; el reparto de
10 s difiere en unos centavos por cómo se asigna el fijo de 0,068. Ninguna decisión cambia: la
vista previa es entre 16 y 17 % del costo en los dos casos.

**De dónde salen los tokens.** ModelArk cobra el video por tokens: ancho × alto × 24 × segundos
/ 1024 al tamaño de salida (`estimate_video_tokens`, `byteplus_ark.py`). Vista previa 3:4 =
560 × 752; final 3:4 = 1248 × 1664. La fórmula quedó **confirmada** sin video de referencia:
estimaba ~49 350 tokens para 5 s a 480p y BytePlus cobró 49 673
(`docs/modelos-generativos/seedance-2-5.md`, SD25-001).

**Con video de referencia** (el dueño sube un video para que el clip copie su movimiento) la
tarifa baja (USD 6,40 por millón a 480p, 7,00 a 1080p), pero **se cobran también los segundos
del video de entrada** al tamaño de salida. Medido en SD25-001: 5 s con una referencia de
7,33 s facturaron 115 690 y 118 851 tokens (USD 0,74 y 0,76), frente a ~48 000 sin
referencia; con 22 s de referencias, 259 802 tokens (USD 1,66). La fórmula «segundos de salida +
segundos de entrada» encaja con las tres mediciones (118 461–121 697 estimados frente a 115 690 y
118 851 cobrados; 259 403–266 490 frente a 259 802).

**El presentador (OmniHuman 1.5) no tiene vista previa.** Se genera de una vez a USD 0,12 por
segundo de voz (`v7`, fuente `omnihuman-1-5`), más el guion (0,033) y la voz (Seed Speech,
USD 30 por millón de caracteres, ~15 caracteres por segundo). Por eso sigue en creaciones y no
pasa por este recorrido.

---

## 3. Decisiones, una por una

Todas las decisiones de producto son del fundador (Herwin). La regla de pesos, las mediciones y
las recomendaciones son de data-scientist-fde. Cada decisión dice qué se decidió, por qué y con
qué evidencia.

### D1 — El dueño nunca ve dinero, solo «creaciones del mes» (2026-10-23)

- **Qué:** el dueño lee «Te quedan 18 de 30 este mes». El costo en dólares lo ve solo el equipo,
  en el informe de creaciones (`creations_report`, PR #299).
- **Quién y dónde:** fundador, decisión 8 de la épica de experiencia
  (`docs/epica-ux-navegacion-experiencia.md` §2, fila 8; historia CREAR-5, m-24848531).
- **Por qué:**
  - El cliente es una PYME con presupuesto ajustado. Un precio por pieza en dólares («USD 0,51»)
    le genera la duda «¿me van a cobrar esto cada vez?». La revisión de experiencia lo registró
    tal cual: hoy `main` muestra «Borrador · 480p · USD 0,51» y «Consume créditos», tres monedas
    distintas a la vez (`docs/ux-revision-equipo-2026-10-24.md`, hallazgo 1).
  - El costo por pieza varía 50 veces entre una imagen y un video (§2). Un número de
    creaciones fijo por tipo es predecible; un monto en dólares no lo es.
  - Si cambian el proveedor o sus precios, cambia la tabla de precios y no lo que lee el dueño.
- **Estado:** textos en el PR #299. El hallazgo 1 propone quitar la insignia con dólares que
  `main` muestra desde #304; al fusionar hay que comprobar que #299 la quitó.

### D2 — 1 creación = USD 0,15; pesos versionados (v1 → v2), tabla de precios v5 → v7 (2026-10-23 y 2026-10-24)

- **Qué:** el peso de un pedido es ⌈costo p95 del pedido / 0,15⌉, mínimo 1. Los pesos viven en
  archivos versionados (`creations_data/pesos-creaciones-v1.json`, `-v2.json`) y cada cobro guarda
  su peso, la versión de pesos y la versión de la tabla de precios (procedencia).
- **Quién y dónde:** propuesta de data-scientist-fde aceptada en la revisión de CREAR-5
  (`epica-ux-navegacion-experiencia.md` §4, fila CREAR-5, 2026-10-23); medición en
  `docs/creaciones-del-mes-medicion.md` §1.
- **Por qué USD 0,15:**
  - Es un **techo**, no un promedio: la imagen, el pedido más común, cuesta p95 USD 0,068
    (medido, 23 pedidos). Con 0,15 la imagen vale 1 creación con un margen de 2,2× sobre su p95
    (§2 de la medición). Si el texto o la imagen suben un poco de precio, el peso no cambia.
  - Deja números chicos y fáciles de leer: imagen 1, carrusel 1 a 3, presentador de 30 s 25.
- **Por qué versionar:** el 2026-10-24 la v1 dejó de cuadrar con `main` en seis puntos
  (duración del clip, presentador de 5 y 10 s, vista previa + final, video de referencia, versión
  de la tabla y sonido; `ux-revision-equipo-2026-10-24.md` §«Pesos de #299»). En vez de editar v1,
  se creó v2 (m-24851828), así cada cobro viejo sigue explicándose con los pesos que tenía.
- **Por qué v7:** la v5 solo tenía la tarifa de Seedance 2.5 **sin** video de entrada (10,70 por
  millón). En SD25-001, las tres tareas con video de referencia se registraron por USD 5,29
  frente a 3,16 reales, un **67 % de más**. La `v7` agrega la tarifa con video (6,40 / 7,00) y
  `main` la usa (`composition.py`, `PRICING_VERSION = "v7"`).
- **Lo que no está confirmado:** solo el peso de la imagen está confirmado con producción. Los
  demás pesos salen de la tabla de precios, sin uso real (medición §2 y §3).
- **Estado:** v1 y v2 en el PR #299; `v7` en `main` (#304).

### D3 — 30 creaciones al mes para todo lo que no es video, iguales para todos los negocios (2026-10-23 y 2026-10-24)

- **Qué:** imágenes, carruseles, plantillas, guiones y el presentador usan el cupo de 30. El
  mismo cupo para todos, también Bianki y Polette, que opera el equipo; no hay excepción por
  negocio. `QUALIFY_CREATIONS_QUOTA=off` es el interruptor de emergencia de toda la instalación
  (`composition.py`, `CREATIONS_QUOTA_ENV`, rama del PR #299).
- **Quién y dónde:** recomendación de data-scientist-fde (medición §4, 2026-10-23) confirmada por
  el fundador (`epica-ux-navegacion-experiencia.md` §2b-3b); «el mismo cupo para todos» el
  2026-10-24 (medición §6.1, rama del PR #299).
- **Por qué 30:** no hay uso real que medir (3 días, 2 negocios de prueba, solo imágenes), así
  que el cupo se dimensionó con un negocio tipo del segmento que publica unas 15 veces al mes
  (medición §4, **estimación**, no medición):

  | Escenario (supuesto) | Mezcla del mes | Creaciones |
  |---|---|---:|
  | Típico | 10 imágenes + 3 otras versiones + 2 carruseles de 5 | 17 (20 con el video de 5 s que v1 incluía) |
  | Exigente | 12 imágenes + 5 otras versiones + 3 carruseles de 5 | 23 (33 con los 2 videos de 10 s de v1) |

  Con el video fuera de las creaciones (D5), 30 cubre los dos escenarios. Costo máximo: 30 ×
  0,15 = **USD 4,50 al mes**; con la mezcla típica, ≈ USD 1,80, porque una imagen cuesta 0,07 y
  no 0,15 (medición §4).
- **Por qué el mismo cupo para Bianki y Polette:** son los únicos negocios reales que van a
  generar uso pronto. Si tienen cupo ilimitado, la segunda medición (§8) no dirá nada sobre un
  cliente que paga; además el producto se prueba como lo vive el cliente.
- **Estado:** PR #299.

### D4 — El presentador (OmniHuman 1.5) se queda en creaciones: 5/10/15/30 s = 5/9/13/25; no 45 ni 60 s; no se evalúa OmniHuman 2.0 (2026-10-23 y 2026-10-24)

- **Qué:** el presentador cuesta 5, 9, 13 o 25 creaciones. 45 y 60 s no se ofrecen. Si el saldo
  no alcanza, la pantalla ofrece el más largo que sí alcance.
- **Quién y dónde:** fundador. Mantener 25 para 30 s y no evaluar 2.0: 2026-10-23 (medición §3).
  Las duraciones 5/10/15/30 sin 45/60: 2026-10-24 (medición §5.1). Que el dueño pueda pedir el de
  30 s, con aviso previo: `epica-ux-navegacion-experiencia.md` §2b-3a.
- **Por qué esos pesos (calculado con `v7`):** costo = 0,033 (guion) + 0,12 × s (OmniHuman 1.5) +
  voz (USD 30 por millón de caracteres, 15 caracteres/s):

  | Duración | USD | ⌈USD / 0,15⌉ |
  |---:|---:|---:|
  | 5 s | 0,64 | 5 |
  | 10 s | 1,24 | 9 |
  | 15 s | 1,84 | 13 |
  | 30 s | 3,65 | 25 |
  | 45 s | 5,45 | 37: no cabe en 30 |
  | 60 s | 7,26 | 49: no cabe en 30 |

  45 y 60 s **no caben en un mes entero**, así que no tiene sentido ofrecerlos.
- **Por qué sigue en creaciones y no en videos:** OmniHuman no tiene vista previa ni final; se
  paga de una vez y su costo por segundo (0,12) es una quinta parte del de Seedance 2.5 (0,68
  sumando vista previa y final). Cabe en las creaciones.
- **Por qué no OmniHuman 2.0 todavía:** costaría USD 0,07/s (30 s → 2,15 → 15 creaciones), pero
  necesita su propia prueba de calidad; la propia página de BytePlus muestra dos precios (0,07 y
  0,12) y enlaza el informe técnico de la 1.5 (`docs/investigacion-avatar-omnihuman-vs-heygen.md`;
  fuente `omnihuman-2-0` de `v7`). No hay ninguna prueba de 2.0 en `docs/modelos-generativos/`.
- **Lo que no está medido:** no hay ningún presentador en producción (`template_runs` = 0 y cero
  presentadores, medición §2); los pesos salen solo de la tabla de precios.
- **Estado:** PR #299.

### D5 — Los videos de Seedance tienen cupo propio: 4 al mes, de hasta 10 s; un carrusel con N diapositivas animadas usa N videos (2026-10-24)

- **Qué:** cada video de Seedance (clip, avatar de Seedance, cada diapositiva animada, clip que
  sigue un video de referencia) cuenta 1 video, dure 5 o 10 s, tenga o no sonido o referencia. No
  usa creaciones. 15 s no se ofrece.
- **Quién y dónde:** fundador; `docs/creaciones-del-mes-medicion.md` §6.1 (rama del PR #299,
  commit `c5e15617`). Es la opción D de §5.6.
- **Por qué (los números de v2):** con los pesos v2, el video en creaciones quedaba así
  (medición §5.5):

  | Video de Seedance 2.5 | USD (calculado, `v7`) | Creaciones de 30 |
  |---|---:|---:|
  | 5 s | 3,44 | **23** |
  | 10 s | 6,82 | **46**: no cabe en un mes |
  | 15 s | 10,19 | **68**: no cabe en un mes |
  | 5 s con referencia de duración desconocida (se cuentan 30 s) | 14,20 | **95** |

  Un dueño que pidiera un clip de 5 s se quedaba con 7 creaciones para el resto del mes. La
  causa es el modelo: Seedance 1.0 pro a 720p, con el que se calculó v1, costaba USD 0,054/s;
  Seedance 2.5 cuesta 0,68/s (vista previa + final), **12 veces más por segundo** (medición
  §5.6). Un cupo aparte separa dos productos de costo muy distinto: no obliga a elegir entre
  imágenes y un video.
- **Por qué 10 s como máximo:** 15 s costaría USD 10,19 por video (calculado). Con 4 videos al
  mes serían ~41 dólares solo en videos; con 10 s el techo es ~27 (§6).
- **Por qué N videos para N diapositivas:** cada diapositiva animada es una tarea de Seedance con
  su propia vista previa y su propio final; cuesta lo mismo que un clip.
- **Estado:** PR #299 (`c5e15617`, `ff1f93d2`).

### D6 — El video se cuenta cuando el dueño APRUEBA, no al crear (2026-10-24)

- **Qué:** crear la vista previa no gasta un video. Aprobar, que es cuando se encarga el final
  1080p, sí. Una vista previa descartada, rechazada o vencida no cuesta ningún video.
- **Quién:** fundador, 2026-10-24. Reemplaza «todo se cobra al crear» (D10a).
- **Por qué:**
  - El gasto grande ocurre al aprobar: el final es **~83 %** del costo de un video (5 s:
    USD 2,85 de 3,44; 10 s: 5,70 de 6,82; calculado, §2). La vista previa es ~17 % (0,60 /
    1,12).
  - Si el video se contara al crear, cada vista previa descartada le costaría al dueño 1 de sus 4
    videos aunque al equipo le haya costado solo el 17 %. El dueño aprendería a no probar, y el
    modo de vista previa existe justamente para eso: probar barato antes de pagar el final.
  - Contar al aprobar alinea lo que el dueño siente que «gastó» con lo que el equipo gastó de
    verdad.
- **Riesgo que crea y cómo se contiene:** sin otro límite, el dueño podría pedir vistas previas
  sin fin. Eso lo cubre D7.
- **Estado:** **en curso, sin commit.** El PR #299 (`ff1f93d2`) todavía dice «se cobra al crear»
  (§6.1 de la medición en esa rama). El cambio está en el árbol de trabajo de la rama `work-299`
  (`creations.py` y `pesos-creaciones-v2.json`), sin publicar.

### D7 — Tope de 20 vistas previas al mes, que se cuentan al crear (2026-10-24)

- **Qué:** cada vista previa de Seedance cuenta 1 de 20 al crearse. No se devuelve, salvo que el
  proveedor no haya entregado nada.
- **Quién:** fundador, 2026-10-24.
- **Por qué hace falta:** D6 hace gratis probar desde el punto de vista del dueño; alguien tiene
  que poner el límite. Una vista previa sí le cuesta al equipo: USD 0,60 (5 s) a 1,12 (10 s)
  sin referencia (calculado; **medido** 0,53 de video a 5 s).
- **Por qué 20:** la decisión no dejó escrito el razonamiento. Lectura de data-scientist-fde: 20
  son unas **5 vistas previas por cada uno de los 4 videos** aprobados; con 10 s, las 20 cuestan
  ≈ USD 22,5, lo mismo que los 4 finales (≈ 22,8). Así el costo de probar nunca supera al de
  producir.
- **Por qué no se devuelve:** la vista previa ya se pagó al proveedor y el dueño la vio. Solo se
  devuelve si el proveedor no entregó nada (la tarea falló o fue moderada).
- **Techo de costo que deja (D6 + D7 + D3):** ≈ USD 27 (4 videos de 10 s) + ≈ 24 (20 vistas
  previas) + 4,50 (30 creaciones) ≈ **USD 55 por negocio y mes**. Es una cota conservadora:
  cuenta dos veces las 4 vistas previas de los videos aprobados. Sin esa doble cuenta da ≈ USD 50
  (§6).
- **Estado:** **en curso, sin commit** (`monthly_preview_quota: 20` en `pesos-creaciones-v2.json`,
  árbol de trabajo de `work-299`).

### D8 — La vista previa vence a los 7 días si no se aprueba (2026-10-24)

- **Qué:** la tarjeta muestra la fecha en que vence. Inicio avisa 2 días antes. Al vencer no se
  cuenta ningún video (nunca se aprobó) y la tarjeta ofrece «Crearla otra vez». La vista previa
  usada no se devuelve (D7).
- **Quién:** fundador, 2026-10-24.
- **Por qué 7 días:** no es una elección nuestra; es el límite del proveedor. Un id de borrador
  de Seedance 2.5 solo puede convertirse en final durante 7 días desde su `created_at`
  (`DRAFT_TTL_SECONDS = 7 * 24 * 3600`, `packages/creative/src/qualify_creative/adapters/byteplus_ark.py`,
  según la documentación de `create-video-generation-task-api`). Después, el final ya no se puede
  pedir sin generar otra vista previa.
- **Por qué avisar antes:** si la vista previa vence sin que el dueño lo note, pierde una de sus
  20 y tiene que esperar otra generación. Dos días de aviso le dan tiempo de aprobar.
- **Detalle del código (`packages/api/src/qualify_api/creative/draft_mode.py`):**
  - `draft_expired` usa los 7 días desde `created_at`;
  - un borrador cuyo final ya se pagó y quedó guardado (`raw_final`) **nunca vence**, porque ya
    no necesita al proveedor;
  - el texto actual es «Las vistas previas duran 7 días. Crea la publicación otra vez para tener
    una nueva.» (`DRAFT_EXPIRED_TEXT`).
- **Estado:** caducidad de 7 días en `main` (#304). Fecha en la tarjeta, aviso en Inicio y botón
  «Crearla otra vez»: **pendientes**.

### D9 — Un final que falla devuelve el video; reintentar no cuenta otra vez (2026-10-24)

- **Qué:** si el final 1080p falla, el video vuelve al cupo. Reintentar no lo cuenta de nuevo.
- **Quién y dónde:** fundador, 2026-10-24 (medición §5.7 y §6.1; ya regía antes de D6).
- **Por qué:** el fallo es nuestro o del proveedor, no del dueño. Que el dueño pague dos veces
  por algo que no recibió rompe la confianza en el contador.
- **Por qué no le cuesta al equipo pagar dos veces (`draft_mode.py`, #304):**
  - **El proveedor entregó y falló nuestro procesamiento** (pasar a H.264, guardar en R2): el
    archivo 1080p pagado se guarda en cuanto llega (`raw_final`, `kept_raw_final`) y el reintento
    lo termina **sin volver a pagar** al proveedor. Ese borrador no vence (D8).
  - **Falló la tarea del proveedor:** el reintento vuelve a encargar el final desde el mismo
    borrador mientras viva (`final_retryable`, estado `failed`, sujeto a `draft_expired`). Un final
    que se quedó «rendering» más de 20 minutos (`FINAL_STALE_SECONDS`) también se puede
    reintentar.
  - Cada final se reserva por intento con bloqueo de fila, y el cobro es idempotente por
    (`draft_id`, `revision`): un reintento nunca paga dos veces al proveedor (PR #304) ni cobra dos
    veces al dueño (`creation_charges`, PR #299).
  - En un carrusel, si falla el final de una diapositiva, vuelve ese video; los demás quedan
    contados (`final_refunded_assets`, medición §6.3).
- **Hipótesis:** «BytePlus no cobra las tareas que fallan». El adaptador lo asume
  (`byteplus_ark.py`: «The video task ended failed/cancelled/expired — not billed»), pero
  **ninguna prueba ni factura lo confirma**. Si fuera falso, cada final fallido que se reintenta
  costaría un final más al equipo, hasta USD 5,70 por intento a 10 s. Cómo verificarlo: §7, H1.
- **Estado:** reutilización de `raw_final` y reintentos en `main` (#304); devolución del video
  en el PR #299.

### D10 — Decisiones anteriores reemplazadas

| Decisión anterior | Cuándo | Qué la reemplazó | Por qué cambió |
|---|---|---|---|
| **a. «Todo se cobra al crear»**: la vista previa y el final se cobran juntos al crear; aprobar no cobra; si el final falla se devuelve la parte del final | 2026-10-24 (medición §5.1; sigue escrita en §6.1 del PR #299, `ff1f93d2`) | D6: el video se cuenta al aprobar, más D7 (tope de vistas previas) | Se decidió y se revirtió el mismo día. Cobrar al crear castigaba descartar una vista previa con el costo entero del video (el 83 % que nunca se gastó) y desalentaba probar |
| **b. El ejemplo de las 6 creaciones**: en v1 un video generado de 15 s costaba 6 creaciones (5 s = 3, 10 s = 5); la revisión de experiencia encontró además que un clip de 5 s se cobraba como si fuera de 15 s, 6 en lugar de 3 | 2026-10-23 (medición §3; `ux-revision-equipo-2026-10-24.md` §«Pesos de #299», punto 1) | v2 (D2) y el cupo de videos (D5) | v1 se calculó con Seedance 1.0 pro a 720p (USD 0,054/s). Con Seedance 2.5 y el final a 1080p cuesta 0,68/s, 12 veces más. Además el clip se cobraba por `media_duration` en vez de `clip_duration` |
| **c. El video dentro de las creaciones**: 23/46/68 creaciones para 5/10/15 s | 2026-10-24 (medición §5.5) | D5: 4 videos al mes aparte | Un clip de 5 s usaba 23 de 30; 10 y 15 s no cabían ni con el mes entero |
| d. Presentador con saldo insuficiente: siempre se ofrece el de 15 s | 2026-10-23 (§2b-3a) | Se ofrece el más largo que alcance (medición §5.5) | Con presentadores de 5 y 10 s, ofrecer siempre 15 s dejaba fuera opciones que sí cabían |
| e. Con 0 videos, «Crear» activo pero con rechazo, o «Crear una imagen en su lugar» | Opciones abiertas el 2026-10-24 | D11 | Ver D11 |

### D11 — Sin saldo, el botón se desactiva y aparece «Pedir más a Qualify» (2026-10-24)

- **Qué:** cuando quedan 0 creaciones, 0 videos o 0 vistas previas, el botón de crear de **ese
  tipo** se desactiva. Aparece «Pedir más a Qualify», que manda un pedido al equipo. El equipo
  envía a mano un enlace de pago y concede unidades extra para ese mes. La concesión se guarda con
  procedencia (quién, cuándo, cuántas, por qué) y solo la ve el equipo.
- **Quién:** fundador, 2026-10-24.
- **Qué reemplaza:** las dos opciones que estaban abiertas: dejar «Crear» activo y rechazar al
  final, y ofrecer «Crear una imagen en su lugar».
- **Por qué:**
  - Un botón activo que al final dice «no» hace perder tiempo y frustra: el dueño llena los
    pasos y se entera al final. Desactivarlo antes es honesto.
  - «Crear una imagen en su lugar» cambia lo que el dueño quería por otra cosa; no resuelve su
    necesidad.
  - Vender unidades extra a mano no necesita un proveedor de pagos nuevo hoy (regla de la casa:
    ningún proveedor nuevo sin una tabla de opciones y la decisión del fundador). Con pocos
    clientes, el trabajo manual cuesta poco y deja aprender cuánto se pide de verdad antes de
    automatizarlo.
  - La procedencia permite que el informe del equipo separe el cupo normal de lo concedido y que
    la segunda medición (§8) no confunda una concesión con uso normal.
- **Abierto:** precio del paquete, proveedor de pago y si lo concedido vence a fin de mes (§9).
- **Estado:** **pendiente**, sin código.

---

## 4. Tabla de decisiones

Estados: **main** = fusionado; **PR #299** = en el PR abierto (`feat/m-24848531-creaciones-del-mes`,
último commit `ff1f93d2`, 2026-10-24 14:09); **en curso** = cambio sin commit en el árbol de trabajo
de `work-299`; **pendiente** = sin código.

| # | Decisión | Fecha | Quién | Evidencia o prueba | Impacto en costo | Estado |
|---|---|---|---|---|---|---|
| D1 | El dueño ve creaciones, nunca dinero | 2026-10-23 | Fundador (decisión 8) | `epica-ux-navegacion-experiencia.md` §2; `ux-revision-equipo-2026-10-24.md` hallazgo 1 | Ninguno directo | PR #299 |
| D2 | 1 creación = USD 0,15; peso = ⌈p95/0,15⌉; pesos v1 → v2; tabla v5 → v7 | 2026-10-23 / 2026-10-24 | Data scientist (regla), fundador (acepta) | Producción: imagen p95 USD 0,068 (23 pedidos); SD25-001: v5 registraba 67 % de más con referencia | Techo de 0,15 por creación | PR #299 (pesos); main (`v7`, #304) |
| D3 | 30 creaciones al mes, iguales para todos; `QUALIFY_CREATIONS_QUOTA=off` de emergencia | 2026-10-23 / 2026-10-24 | Data scientist (recomienda), fundador | Medición §4 (escenarios **supuestos**); §2b-3b | Techo USD 4,50/mes; típico ≈ 1,80 | PR #299 |
| D4 | Presentador OmniHuman 1.5 en creaciones: 5/9/13/25; sin 45/60 s; sin 2.0 por ahora | 2026-10-23 / 2026-10-24 | Fundador | `v7` (`omnihuman-1-5` USD 0,12/s); medición §3, §5.1, §5.3 | 30 s = USD 3,65 | PR #299 |
| D5 | 4 videos de Seedance al mes, hasta 10 s; N diapositivas animadas = N videos | 2026-10-24 | Fundador | Medición §5.5 (23/46/68 creaciones) y §5.6 (12× por segundo frente a v1) | Techo 4 × 6,82 = USD 27,27 | PR #299 |
| D6 | El video se cuenta al aprobar (al encargar el final) | 2026-10-24 | Fundador | §2: final ~83 % del costo; vista previa ~17 % | Ninguno sobre el techo; quita al dueño el costo de descartar | En curso |
| D7 | 20 vistas previas al mes, contadas al crear, sin devolución salvo entrega nula | 2026-10-24 | Fundador | §2; SD25-001 (vista previa 5 s medida: 0,5315) | Techo ≈ USD 22,5 (10 s, sin referencia) | En curso |
| D8 | La vista previa vence a los 7 días; fecha en la tarjeta, aviso 2 días antes en Inicio, «Crearla otra vez» | 2026-10-24 | Fundador | `DRAFT_TTL_SECONDS` (ModelArk) en `byteplus_ark.py`; `draft_mode.py` | Ninguno (una vista previa vencida no cuenta video) | main (caducidad); pendiente (fecha, aviso, botón) |
| D9 | Un final que falla devuelve el video; reintentar no cuenta otra vez; `raw_final` se reutiliza | 2026-10-24 | Fundador | `draft_mode.py` (`kept_raw_final`, `final_retryable`); PR #304 | Hasta USD 5,70 por reintento de 10 s **si** BytePlus cobra las tareas fallidas (H1) | main (#304); PR #299 (devolución) |
| D10 | Reemplazadas: cobrar todo al crear; el ejemplo de las 6 creaciones; el video dentro de creaciones | 2026-10-23 / 2026-10-24 | Fundador | Ver tabla de D10 | — | Reemplazadas |
| D11 | Sin saldo: botón desactivado + «Pedir más a Qualify»; el equipo vende extras a mano, con procedencia | 2026-10-24 | Fundador | — (decisión de producto) | Ingreso extra; sin proveedor nuevo | Pendiente |

---

## 5. Costo por unidad

p50 solo existe donde hay datos de producción. Donde no hay datos, la casilla dice «—» y el p95
es un techo calculado.

| Unidad | USD p50 | USD p95 / techo | Tipo de cifra | Fuente | Tabla |
|---|---:|---:|---|---|---|
| Imagen con texto (incluye su juego de ángulos) | 0,063 | 0,068 (máx. 0,134, el que se repitió) | **medido**, 23 pedidos, 2026-10-21 a 23 | `creaciones-del-mes-medicion.md` §2 | v5 al medir; mismas tarifas en v7 |
| Solo el texto (Claude `claude-opus-5-5`) | 0,028 | 0,033 | medido | ídem | v5/v7 |
| Imagen Seedream 5.0 lite | 0,035 | 0,035 | precio fijo, medido | ídem; `v7` `seedream-5-0-lite-260128` | v7 |
| Juego de ángulos | ≈ 0,025 | — | medido (3 juegos) | ídem | v5 |
| Carrusel de 2–3 / 4–7 / 8–10 imágenes | — | 0,14 / 0,28 / 0,38 | calculado | medición §3 | v5 |
| Video con plantilla (Remotion, sin video generado) | — | 0,07 | calculado (Remotion = USD 0, servidor propio) | medición §3; `v7` `remotion_selfhost` | v5/v7 |
| Presentador OmniHuman 1.5, 5 / 10 / 15 / 30 s | — | 0,64 / 1,24 / 1,84 / 3,65 | calculado | medición §5.3; `v7` `omnihuman-1-5` | v7 |
| Ranura de voz clonada (una vez por marca) | — | 2,00 | precio de lista | `v7` `seed-icl-2.0-slot` | v7 |
| Vista previa Seedance 2.5, 5 s, sin referencia (con el fijo de 0,068) | — | 0,60 | calculado; **medido** 0,5315 solo el video (m-24849137) | §2; SD25-001 | v7 |
| Vista previa Seedance 2.5, 10 s, sin referencia | — | 1,12 | calculado | §2 | v7 |
| Vista previa 5 s con una referencia de 7,33 s (solo el video) | — | 0,74 / 0,76 | **medido** (2 tareas) | SD25-001; m-24849431 | v7 |
| Vista previa 5 s con 22 s de referencias (solo el video) | — | 1,66 | **medido** (1 tarea) | SD25-001; m-24848887 | v7 |
| Final 1080p, 5 s, sin referencia | — | 2,85 | calculado, **nunca medido** | §2 | v7 |
| Final 1080p, 10 s, sin referencia | — | 5,70 | calculado, **nunca medido** | §2 | v7 |
| Video completo 5 s / 10 s, sin referencia | — | 3,44 / 6,82 | calculado | medición §5.5 y §6.4 | v7 |
| Video completo 5 s / 10 s con referencia de duración desconocida (se cuentan 30 s, y el final vuelve a cobrar la entrada) | — | 14,20 / 16,22 | calculado sobre H2 y H3 | medición §6.4 | v7 |

Para comparar (medición §5.6): con Seedance 1.0 pro a 720p (v1) un video costaba USD 0,054 por
segundo. Seedance 2.5 cuesta 0,1056 (vista previa) + 0,5695 (final) = 0,675 por segundo.

---

## 6. Peor caso por negocio y mes

El dueño agota los tres cupos. Videos de 10 s, la duración más cara que se ofrece.

**Sin videos de referencia:**

| Parte | Cálculo | USD |
|---|---|---:|
| 20 vistas previas de 10 s | 20 × 1,12 | 22,48 |
| 4 finales de 10 s (4 de esas vistas previas se aprobaron) | 4 × 5,70 | 22,78 |
| 30 creaciones al techo | 30 × 0,15 | 4,50 |
| **Total exacto** | | **≈ 49,8** |
| Cota de la decisión (4 videos completos ≈ 27 + 20 vistas previas ≈ 24 + 4,50) | cuenta dos veces 4 vistas previas | **≈ 55** |

La cota de USD 55 usada al decidir es **conservadora**: los 4 videos aprobados ya incluyen su
vista previa, que vuelve a sumarse entre las 20. Para presupuestar conviene usar 55, porque
también absorbe redondeos.

**Con videos de referencia de duración desconocida** (el brief no guarda cuánto dura el video,
así que los pesos cuentan el máximo de una tarea, 30 s; medición §5.2):

| Parte | Cálculo (tarifa con video de entrada) | USD |
|---|---|---:|
| 20 vistas previas de 10 s + 30 s de entrada | 20 × (0,068 + 0,0632 × 40) | 51,92 |
| 4 finales, **si** el final vuelve a cobrar la entrada (H3) | 4 × 0,3407 × 40 | 54,51 |
| 4 finales, si **no** la vuelve a cobrar | 4 × 0,3407 × 10 | 13,63 |
| 30 creaciones | | 4,50 |
| **Total** | | **≈ 70 a 111** |

Es un techo teórico: exige que las 24 tareas lleven una referencia de 30 s. La referencia real
medida fue de 7,33 s y 22 s (SD25-001). La estimación previa al gasto ya lee la duración real del
video con PyAV y usa 30 s solo si no puede leerla (`docs/modelos-generativos/seedance-2-5.md`,
hallazgo 2); lo que falta es que el **peso** también la use.

**Lo normal será mucho menos.** Con la mezcla típica de creaciones (≈ USD 1,80) y, por ejemplo,
2 videos de 5 s con 2 vistas previas cada uno: 4 × 0,60 + 2 × 2,85 + 1,80 ≈ **USD 9,90**
(**estimación**, sin datos de uso real).

**La red de seguridad en dólares no está alineada.** Cada marca tiene
`creative_engine_config.monthly_budget_cap_usd` con `hard_stop_on_cap` encendido por defecto
(`migrations/postgres/versions/0009_creative.py`; `service.py`, `budget_state`). Si ese tope
queda por debajo del peor caso, **bloquea videos que el cupo promete**. La propuesta original del
ticket (1,5 × 4,50 = USD 6,75) no alcanza ni para dos videos de 5 s (medición §6.4). Ver §9.

---

## 7. Riesgos e hipótesis

| # | Hipótesis | Qué pasa si es falsa | Cómo verificarla |
|---|---|---|---|
| H1 | **BytePlus no cobra las tareas de video que fallan** (`failed`, `cancelled`, `expired`). El adaptador lo asume (`byteplus_ark.py`); para Seedream la página de precios dice que una imagen moderada no se cobra, pero para Seedance no hay prueba | Cada final fallido que se reintenta le cuesta al equipo otro final (hasta USD 5,70 a 10 s). El dueño no lo nota (D9), pero el peor caso de §6 sube | Cruzar la primera factura de BytePlus, tarea por tarea (`cgt-…`), con las tareas que `creative_usage_events` marca como fallidas. Documentar el resultado en `docs/modelos-generativos/seedance-2-5.md` |
| H2 | **El final 1080p cuesta lo que dice la fórmula** (48 672 tokens/s a 3:4, USD 0,5695/s) | Todo el costo de video y la cota de USD 55 se mueven; el final es el 83 % del video | Aprobar una vista previa real y leer `usage.completion_tokens` del final. Está pendiente desde #304 («Pendiente en vivo: aprobar un borrador y medir el final 1080p»). El ticket m-24849137 tiene marcado el criterio de anotar el costo del final, pero no anota ningún número |
| H3 | **El final de una vista previa con video de referencia vuelve a cobrar los segundos de entrada** (supuesto conservador de v2) | Si no los cobra, el video con referencia cuesta mucho menos (5 s con 7,33 s de entrada: ≈ USD 1,70 en vez de ≈ 4,20 de final, SD25-001 «Pendiente») | Un final real de una vista previa con video de referencia, leyendo sus tokens |
| H4 | **Duración del video de referencia desconocida = 30 s** en los pesos | Sobreestima el costo; con la regla anterior (video dentro de creaciones) hacía imposible usar referencias. Con el cupo de videos (D5) ya no afecta al dueño, solo al techo del equipo | Guardar en el brief la duración leída con PyAV (ya se lee para la estimación previa) y usarla en el techo |
| H5 | **El sonido no cambia el precio** de Seedance 2.5 | Habría que versionar `v8` y la tabla de pesos | Medido en SD25-001: el clip con sonido (115 690 tokens) y la diapositiva sin sonido (118 851) encajan en la misma fórmula. Falta confirmarlo con la factura (medición §5.4) |
| H6 | **El cupo de 30 creaciones alcanza** para un negocio real | Si el p90 real pasa de 30, los dueños se quedan sin saldo antes de fin de mes | Segunda medición (§8) |
| H7 | **Las tarifas de `v7` son las vigentes** | La página de precios de ModelArk carga sus precios con JavaScript; el 2026-10-24 no se pudo releer (medición §5.4) | Primera factura de BytePlus |
| H8 | **OmniHuman 1.5 cuesta USD 0,12 por segundo de voz** | El presentador quedaría mal pesado | Factura; no hay ningún presentador en producción (medición §2) |

**Riesgos que no son hipótesis:**

- **La medición de producción es casi vacía:** 3 días, 2 negocios de prueba, 23 pedidos, solo
  imágenes (medición §2). Solo el peso de la imagen está confirmado.
- **D6 y D7 aún no están en el PR #299.** Si el PR se fusiona como está (`ff1f93d2`), el video se
  cobra al crear y no hay tope de vistas previas.
- **Las pruebas en vivo son pocas y de un solo negocio de prueba** (Nibbles' Burgers, entorno
  local): 4 tareas de vista previa y ningún final (m-24848887, m-24849137, m-24849431). Este
  documento cita solo sus costos y tokens, no sus textos.

---

## 8. Cuándo volver a medir

**Disparador:** cuando **3 negocios reales** (Bianki, Polette y uno de inmobiliaria o de viajes)
tengan **30 días de uso** (medición §4; `epica-ux-navegacion-experiencia.md` §2b-3b).

**Qué medir** (la misma lectura agregada de solo lectura del 2026-10-23: solo conteos y sumas,
sin textos ni datos de clientes finales):

1. Creaciones, videos y vistas previas por negocio y mes: p50 y p90. Si el p90 pasa del cupo,
   subirlo.
2. Costo p95 por tipo de pedido. Si un p95 supera peso × 0,15, subir ese peso y versionar
   `pesos-creaciones-v3`.
3. Vistas previas por video aprobado (para saber si 20 es mucho o poco).
4. Cuántas vistas previas vencen sin aprobarse (D8).
5. Finales fallidos y reintentos, cruzados con la factura (H1).
6. Pedidos de «Pedir más a Qualify» (D11): cuántos, de qué tipo y en qué día del mes.

**Antes de eso, en cuanto se pueda (no esperan a los 30 días):**

- el primer final 1080p real, sin y con video de referencia (H2, H3);
- la primera factura de BytePlus (H1, H5, H7, H8).

Cada resultado se documenta el mismo día en `docs/modelos-generativos/` y, si cambia un peso, en
una nueva versión de pesos.

---

## 9. Preguntas abiertas

1. **Precio del paquete extra** (D11): cuánto cuesta y cuántas unidades trae cada paquete de
   creaciones, de videos y de vistas previas. Referencia de costo: una creación cuesta como mucho
   USD 0,15, un video de 10 s ≈ 6,82 y una vista previa de 10 s ≈ 1,12 (§5).
2. **Proveedor de pago** (D11): hoy el enlace se manda a mano. Un proveedor nuevo necesita una
   tabla de opciones y la decisión del fundador (regla de la casa).
3. **¿Lo concedido vence a fin de mes?** (D11): si vence, el dueño compra justo antes de
   necesitarlo; si no vence, hay que llevar un saldo que pasa de un mes a otro.
4. **Tope en dólares por marca (`monthly_budget_cap_usd`):** hoy no se toca (medición §6.4). Para
   no bloquear lo que el cupo promete tendría que quedar por encima del peor caso: ≈ USD 55 sin
   referencias, o más si se aceptan referencias de duración desconocida (§6). La medición §6.4
   proponía unos USD 75. Las concesiones de D11 también tendrían que subirlo.
5. **Final a 720p en vez de 1080p** (opción B, medición §5.6): bajaría el costo de cada video
   unas 2,4 veces sin tocar el cupo. Necesita una prueba de calidad (la misma vista previa con
   final a 720p y a 1080p, vista por una dueña en un teléfono).

---

## 10. Glosario

| Palabra | Qué significa aquí |
|---|---|
| **Creación** | La unidad que ve el dueño para todo lo que no es video de Seedance. Vale como mucho USD 0,15 de costo de proveedor |
| **Peso** | Cuántas creaciones usa un pedido. Se calcula como el costo p95 del pedido dividido entre 0,15, redondeado hacia arriba |
| **Cupo** | Cuántas unidades trae el mes: 30 creaciones, 4 videos, 20 vistas previas. Se renueva el día 1 en la zona horaria del negocio |
| **Video** | Un video hecho con Seedance: un clip, un avatar de Seedance o una diapositiva animada de un carrusel. Se cuenta al aprobar |
| **Vista previa** | La versión en calidad baja (480p) de un video, para decidir rápido. En el código se llama «borrador» (`draft`). Dura 7 días |
| **Final** | El mismo video en alta calidad (1080p), hecho desde la vista previa cuando el dueño aprueba. Es el que se publica |
| **Presentador** | Un video con una persona que habla a cámara, hecho con OmniHuman. Usa creaciones, no videos |
| **Video de referencia** | Un video que sube el dueño para que el clip copie su movimiento y su ritmo. El proveedor cobra también sus segundos |
| **p50 / p95** | El valor que no supera la mitad de los casos / el 95 % de los casos. Con el p95 se fijan los techos |
| **Techo** | El costo más alto razonable, no el promedio |
| **Token** | La unidad con la que el proveedor cobra el video: depende del tamaño de la imagen, de los cuadros por segundo y de los segundos |
| **Tabla de precios (`v5`, `v7`)** | El archivo versionado con las tarifas de cada proveedor que usa el código para calcular costos |
| **Versión de pesos (`v1`, `v2`)** | El archivo versionado con cuántas creaciones vale cada pedido |
| **Procedencia** | Lo que se guarda con cada cobro para poder explicarlo después: peso, versión de pesos y versión de la tabla de precios |
| **Devolución** | Cuando un cobro vuelve al cupo porque la generación falló |
| **`raw_final`** | El archivo 1080p ya pagado que se guarda en cuanto llega, para no pagarlo dos veces si falla el paso siguiente |
| **Concesión** | Unidades extra que el equipo da a mano a un negocio para el mes (D11) |

---

## 11. Fuentes

- `docs/creaciones-del-mes-medicion.md`: en `main`, §1–§4 (v1, 2026-10-23); en la rama del PR #299
  (`origin/feat/m-24848531-creaciones-del-mes`, `ff1f93d2`), §5 (v2) y §6 (videos del mes).
- `docs/modelos-generativos/seedance-2-5.md`, prueba SD25-001 (2026-10-23).
- `docs/modelos-generativos/seedream-5-0-lite.md`, `claude-haiku-5-5.md`;
  `docs/investigacion-avatar-omnihuman-vs-heygen.md` (OmniHuman 1.5 y 2.0; no hay ficha de
  OmniHuman en `docs/modelos-generativos/`). `docs/modelos-generativos/pruebas.md` no existe en
  `main` (la ficha de Seedance 2.5 dice que está sin commit en otra rama).
- `packages/creative/src/qualify_creative/pricing_data/v5.json` y `v7.json` (fuentes y tarifas de
  `dreamina-seedance-2-5-260628`, `omnihuman-1-5`, `omnihuman-2-0`, `seedream-5-0-lite-260128`,
  `seed-icl-2.0`, `remotion_selfhost`).
- `packages/api/src/qualify_api/creative/draft_mode.py` y
  `packages/creative/src/qualify_creative/adapters/byteplus_ark.py` (`DRAFT_TTL_SECONDS`) en `main`.
- PR #304 (Seedance 2.5 en modo borrador, tabla `v7`), fusionado el 2026-10-24: descripción y
  «Pendiente en vivo».
- PR #299 (creaciones del mes), abierto: commits `c5e15617` y `ff1f93d2`. Cambios en curso de D6 y
  D7: árbol de trabajo de `work-299` (`creations.py`, `pesos-creaciones-v2.json`), sin commit.
- Lectura de producción del 2026-10-23 (medición §2): 3 días, solo imágenes, p50 USD 0,063 y p95
  0,068 por imagen.
- `docs/ux-revision-equipo-2026-10-24.md`: hallazgos 1 y 2 y §«Pesos de #299».
- `docs/epica-ux-navegacion-experiencia.md` §2 (decisión 8), §2b (3a y 3b), §4 (CREAR-5) y la
  historia CREAR-5.
- Meegle, épica m-24848869 y sus pruebas: m-24848887 (clip con 2 videos de referencia, 259 802
  tokens), m-24849137 (galería con diapositiva animada sin referencia, 49 673 tokens, USD 0,5315)
  y m-24849431 (clip y galería con una referencia de 7,33 s, 115 690 y 118 851 tokens).
- Código de presupuesto por marca: `migrations/postgres/versions/0009_creative.py`
  (`monthly_budget_cap_usd`, `hard_stop_on_cap`), `packages/api/src/qualify_api/creative/service.py`
  (`budget_state`).
