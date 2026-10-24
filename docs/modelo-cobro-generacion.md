# Modelo de cobro y costo de la generación: creaciones, videos y vistas previas

Autor: data scientist / FDE · Fecha: 2026-10-24 · Para: Darwin (cofundador), que no estuvo en
estas conversaciones · Ticket: [m-24852128](https://project.larksuite.com/5h2wsx/issue/detail/24852128),
dentro de la épica de Deivid [m-24848869](https://project.larksuite.com/5h2wsx/story/detail/24848869)
(«Generación: pruebas de modelos, costos y modelo de cobro»).

Versiones vigentes: pesos **`pesos-creaciones-v2`** sobre la tabla de precios **`v7`**
(`packages/creative/src/qualify_creative/pricing_data/v7.json`). Modelo de video:
`dreamina-seedance-2-5-260628`. Presentador: OmniHuman 1.5. Imagen: `seedream-5-0-lite-260128`.
Texto: `claude-opus-5-5`.

**Revisión del 2026-10-24 (tarde).** Se agregaron la lectura oficial de precios del mismo día,
que confirma la tabla `v7` y resuelve las hipótesis H1 y H3 (§7), y las decisiones D12 a D19
sobre planes con nombre y paquetes extra (§3). El PR #299 ya cuenta el video al aprobar y trae el
tope de 20 vistas previas (`a09c818f`, `e1bd509c`).

**Cómo leer las cifras.** Cada número dice de dónde sale. Hay tres clases y no se mezclan:

- **medido**: sale de una factura, de una tarea real del proveedor o de la base de producción;
- **calculado**: sale de la tabla de precios `v7` y de la fórmula de tokens del proveedor, sin una
  tarea real que lo confirme;
- **hipótesis**: una suposición que todavía no comprobó ninguna prueba (§7).

Los costos son techos (p95 o peor caso), no promedios, salvo que se diga otra cosa.

---

## 1. Resumen para Darwin

**Qué ve el dueño.** Nunca dinero. Ve tres contadores que se renuevan el día 1 de cada mes. Las
cifras de esta tabla son las del plan **Básico**, con el que empieza todo negocio. Plus y Pro
duplican y cuadruplican cada cupo (D15):

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

**Lo que cuesta al equipo en el peor caso:** unos **USD 50 a 55 por negocio y mes** en Básico si
el dueño agota todo y sin videos de referencia (§6). Con videos de referencia de duración
desconocida el techo sube a unos **USD 111**: la lectura oficial del 2026-10-24 confirmó que el
final vuelve a cobrar los segundos del video de referencia (H3).

**Cuando se acaba el cupo.** El botón de ese tipo se desactiva y aparece «Pedir más a Qualify»
(D11). Se venden planes con nombre: Básico 30/4/20, Plus 60/8/40 y Pro 120/16/80 (creaciones /
videos / vistas previas al mes). Encima se pueden sumar paquetes que duran 90 días. Primero se
gasta el cupo del plan y después los paquetes, el que vence antes primero. Cada plan tiene un tope
en dólares que solo avisa al equipo en Lark y nunca bloquea lo pagado (Básico USD 120, Plus 240,
Pro 480). El enlace de pago se manda a mano (D12 a D19). Los precios de venta están pendientes.

**Lo que está decidido y lo que falta.**

- En código ya fusionado (`main`): la tabla `v7`, el modo de vista previa de Seedance 2.5 (#304),
  la caducidad de 7 días y la reutilización del final ya pagado.
- En el PR #299 (abierto, `e1bd509c`): creaciones del mes, pesos v1 → v2, el cupo de 4 videos
  contado al aprobar, el tope de 20 vistas previas, la fecha de vencimiento en la tarjeta, el
  aviso en Inicio y «Crearla otra vez».
- Diseñado, sin código: planes y paquetes (D12 a D19). El diseño de principal-architect está en
  los comentarios de m-24852129 y va en la migración `0089`, apilada sobre #299.
- Pendiente: los precios de cada plan y de cada paquete.

**Lo que ya se sabe y lo que no (§7).** La lectura oficial de precios del 2026-10-24 coincide con
`v7` en todos los modelos. BytePlus no cobra las tareas que fallan (H1, resuelta). El final 1080p
cuesta USD 0,5695 por segundo según la tarifa y la fórmula oficiales (H2: falta leer el conteo de
tokens de un final real). El final sí vuelve a cobrar el video de referencia (H3, resuelta).
Ningún cliente real ha creado todavía un video en producción.

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
| 4. Final 1080p | 48 672 tokens/s × USD 11,70 por millón = 0,5695/s; pasa a H.264 y reemplaza la vista previa en la misma fila (`draft_mode.py`) | 2,85 | 5,70 | calculado; **tarifa y fórmula confirmadas** en la lectura oficial del 2026-10-24 (el ejemplo oficial a 1080p 16:9 da 0,569/s). Falta el conteo de tokens de un final real (#304, «Pendiente en vivo») |
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

La documentación oficial (leída el 2026-10-24, `seedance-2-5` § Draft mode) confirma dos reglas
más:

- **El final vuelve a cobrar el video de entrada.** Vista previa y final se facturan por
  separado. El final paga la tarifa según si la vista previa tenía video de entrada, y «the input
  video duration is calculated based on the input video in Step 1. The Draft video is not
  counted». Ejemplo de la misma página: 5 s con 7,33 s de referencia a 1080p 3:4 = 600 126 tokens
  × USD 7,00 por millón ≈ **USD 4,20** de final.
- **Hay un consumo mínimo cuando hay video de entrada** («Minimum token consumption», página
  `model-pricing`): depende de la resolución, el formato y la duración. En los ejemplos oficiales,
  2 a 4 s de entrada cuestan lo mismo, un piso de unos 4 s. `v7` no lo modela, así que una
  referencia de menos de 4 s se estima por debajo de lo que se factura (§7, H9).

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
- **Reemplazada en parte por D15 (2026-10-24):** «el mismo cupo para todos» pasa a ser «todos
  empiezan en Básico». Las 30 creaciones de esta decisión son el cupo de Básico. Bianki y
  Polette siguen sin excepción: están en Básico mientras nadie les asigne otro plan.
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
  necesita su propia prueba de calidad. No hay ninguna prueba de 2.0 en
  `docs/modelos-generativos/`. El precio ya no es la duda: la lectura oficial del 2026-10-24
  confirmó 0,07/s para la 2.0. La tarjeta de 0,12/s de la misma página es «SOTA Lip Sync Avatar»,
  es decir OmniHuman 1.5, y no un segundo nivel de la 2.0 (comentario de precios en m-24852128).
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
- **Estado:** PR #299 (`a09c818f`, `e1bd509c`; medición §7 en esa rama). `charge_videos` cobra
  los videos al aprobar, todo o nada, y los cuenta en el mes de la aprobación
  (`videos_period_month`). Si al aprobar no quedan videos, la aprobación se rechaza sin guardar
  nada. Antes de aprobar el dueño lee «Al aprobar usas 1 de tus 4 videos del mes. Te quedarían
  {v}.»

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
- **Estado:** PR #299 (`a09c818f`; `monthly_preview_quota: 20`, columna `previews` en
  `creation_charges`). El dueño solo ve el contador cuando quedan 5 o menos: «Te quedan {p} vistas
  previas este mes.» (medición §7.2).

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
- **Dos decisiones de experiencia sobre #299 (fundador, 2026-10-24):**
  - **«Crearla otra vez» avisa lo que usa:** «Usa 1 de tus vistas previas. Te quedan {p}.» Crear
    otra vez genera una vista previa nueva, que sí cuenta (D7), y el dueño debe saberlo antes de
    tocar el botón.
  - **El aviso de Inicio abre «Por completar» ordenado por vencimiento:** el que vence antes
    aparece primero. Así el dueño llega directo a lo que está por perder.
- **Estado:** caducidad de 7 días en `main` (#304). En el PR #299 (`a09c818f`): la fecha en cada
  tarjeta («Apruébala antes del {día} {fecha} para tener el video final.»), el aviso de Inicio
  desde 2 días antes («{n} videos vencen pronto») y «Crearla otra vez» (medición §7.2). Las dos
  decisiones de experiencia de arriba se aplican sobre ese PR; comprobar los textos al
  fusionar.

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
- **Las tareas fallidas no se cobran (H1, resuelta el 2026-10-24).** Las reglas oficiales de
  facturación de video lo dicen: «You are only charged for successfully generated videos. No fee
  is charged if generation fails due to reasons such as content moderation» (`model-pricing`,
  leída el 2026-10-24). Coincide con lo que asume el adaptador (`byteplus_ark.py`). Reintentar un
  final cuya tarea falló no le cuesta un final de más al equipo. Queda una comprobación, no una
  hipótesis: cruzar la primera factura tarea por tarea (§7).
- **Estado:** reutilización de `raw_final` y reintentos en `main` (#304); devolución del video
  en el PR #299.

### D10 — Decisiones anteriores reemplazadas

| Decisión anterior | Cuándo | Qué la reemplazó | Por qué cambió |
|---|---|---|---|
| **a. «Todo se cobra al crear»**: la vista previa y el final se cobran juntos al crear; aprobar no cobra; si el final falla se devuelve la parte del final | 2026-10-24 (medición §5.1 y §6.1 en la rama del PR #299; reemplazada en §7 de esa medición, `a09c818f`) | D6: el video se cuenta al aprobar, más D7 (tope de vistas previas) | Se decidió y se revirtió el mismo día. Cobrar al crear castigaba descartar una vista previa con el costo entero del video (el 83 % que nunca se gastó) y desalentaba probar |
| **b. El ejemplo de las 6 creaciones**: en v1 un video generado de 15 s costaba 6 creaciones (5 s = 3, 10 s = 5); la revisión de experiencia encontró además que un clip de 5 s se cobraba como si fuera de 15 s, 6 en lugar de 3 | 2026-10-23 (medición §3; `ux-revision-equipo-2026-10-24.md` §«Pesos de #299», punto 1) | v2 (D2) y el cupo de videos (D5) | v1 se calculó con Seedance 1.0 pro a 720p (USD 0,054/s). Con Seedance 2.5 y el final a 1080p cuesta 0,68/s, 12 veces más. Además el clip se cobraba por `media_duration` en vez de `clip_duration` |
| **c. El video dentro de las creaciones**: 23/46/68 creaciones para 5/10/15 s | 2026-10-24 (medición §5.5) | D5: 4 videos al mes aparte | Un clip de 5 s usaba 23 de 30; 10 y 15 s no cabían ni con el mes entero |
| d. Presentador con saldo insuficiente: siempre se ofrece el de 15 s | 2026-10-23 (§2b-3a) | Se ofrece el más largo que alcance (medición §5.5) | Con presentadores de 5 y 10 s, ofrecer siempre 15 s dejaba fuera opciones que sí cabían |
| e. Con 0 videos, «Crear» activo pero con rechazo, o «Crear una imagen en su lugar» | Opciones abiertas el 2026-10-24 | D11 | Ver D11 |
| f. **El mismo cupo para todos los negocios** | 2026-10-24 (medición §6.1) | D15: tres planes; todos empiezan en Básico | Un negocio que crece necesita más cupo sin pedirlo cada mes |
| g. Lo extra vence a fin de mes y no pasa al mes siguiente (primera revisión de arquitectura, `creation_grants`) | 2026-10-24 (comentario 1 de m-24852129) | D12 (90 días) y la segunda revisión de arquitectura (`creation_packs`) | Algo pagado no debe perderse a los pocos días: una compra hecha el día 30 vencía en uno o dos días |

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
- **Lo que se decidió después:** D12 a D19 cierran el vencimiento (90 días), la forma de vender
  (planes con nombre más paquetes) y el pago (a mano). Sigue abierto el precio (§9).
- **Estado:** **pendiente**, sin código (m-24852129; extras desde el alta en m-24852131).

### D12 a D19 — Planes con nombre y paquetes extra (fundador, 2026-10-24)

Registradas por el fundador en m-24852128 el 2026-10-24. Tickets: m-24852129 («Pedir más a
Qualify»), m-24852131 (extras desde el alta) y m-24852145 (planes Básico, Plus y Pro).

**D12 — Los extras comprados duran 90 días** desde que se asignan, no hasta fin de mes.

- **Por qué:** con vencimiento a fin de mes, una compra hecha el día 30 servía uno o dos días. El
  dueño paga por unidades que no alcanza a usar y deja de comprar. Con 90 días puede comprar
  cuando lo necesita.
- **Costo:** el techo por unidad no cambia (§5). Un paquete grande puede llevar a un negocio por
  encima del tope de alerta de su plan en un mes (D18).

**D13 — Si la cuenta no tiene WhatsApp,** la confirmación de «Pedir más a Qualify» dice «Listo.
Te escribimos a tu correo con el enlace de pago.» y se usa el correo de la cuenta.

- **Por qué:** el equipo contesta por WhatsApp cuando existe, pero no todos los negocios lo tienen
  conectado. El dueño debe saber por dónde le va a llegar el enlace. Que el dueño prefiera
  WhatsApp y pague con un enlace es una hipótesis (`docs/perfil-cliente-pyme.md` §5).

**D14 — Los extras se venden como planes con nombre**, no como unidades sueltas.

- **Por qué:** un dueño entiende «paso a Plus» más fácil que «compro 12 creaciones y 2 videos».
  Además el equipo arma menos combinaciones a mano.

**D15 — Tres planes, cada uno el doble del anterior. Todo negocio empieza en Básico; encima se
suman paquetes de 90 días. Reemplaza «el mismo cupo para todos» (D3, D10f).**

| Plan | Creaciones / mes | Videos (≤ 10 s) / mes | Vistas previas / mes | Peor caso sin referencias (USD) | Peor caso con referencias de 30 s (USD) | Tope de alerta (D18) |
|---|---:|---:|---:|---:|---:|---:|
| Básico | 30 | 4 | 20 | ≈ 50 (55 con la cota conservadora) | ≈ 111 | 120 |
| Plus | 60 | 8 | 40 | ≈ 100 (110) | ≈ 222 | 240 |
| Pro | 120 | 16 | 80 | ≈ 199 (220) | ≈ 444 | 480 |

El peor caso de Plus y Pro es el de Básico multiplicado por 2 y por 4 (**calculado** a partir de
§6). Básico es el cupo actual (D3, D5, D7).

- **Por qué duplicar:** son pocos escalones y fáciles de explicar. El costo crece en proporción
  exacta con el cupo, así que el mismo margen vale en los tres planes.
- **Precios de venta pendientes:** el fundador los dejó para después de tener los costos oficiales
  de los modelos. Esos costos ya están confirmados (lectura del 2026-10-24, §7). Queda la decisión
  de precio (§9).

**D16 — El dueño ve el total y, aparte, lo extra:** «Te quedan 5 de 6 videos este mes (2 extra,
vencen el 22 de enero).»

- **Cómo se calcula** (diseño de principal-architect, m-24852129): el 6 es el cupo del plan del
  mes más lo que traían los paquetes vigentes; el 5 es lo que queda. Si hay varios vencimientos se
  muestra el más cercano.
- **Por qué:** el dueño ve un solo número para decidir y además sabe que una parte vence. Nunca ve
  dinero (D1).

**D17 — Orden de consumo: primero el cupo del mes del plan, después los paquetes, el que vence
antes primero.**

- **Por qué:** el cupo del plan se pierde a fin de mes y el paquete dura 90 días. Gastar primero
  lo que vence antes es lo que más le conviene al dueño.
- **Cómo:** se guarda en el momento del cargo qué fuente pagó cada unidad (`creation_allocations`),
  en vez de recalcularlo al leer. Si se recalculara, al devolver un cargo viejo la historia se
  movería y nadie podría decir qué paquete pagó qué (diseño de principal-architect).

**D18 — Tope en dólares por plan, solo de alerta: Básico USD 120, Plus 240, Pro 480.** Al
alcanzarlo se avisa al equipo en Lark. Nunca bloquea unidades que el negocio pagó.

- **Por qué esas cifras:** cada tope queda por encima del peor caso de su plan, incluso con
  referencias de 30 s (111 / 222 / 444, tabla de D15). Un negocio que solo usa su plan no debería
  llegar al tope; si llega, algo raro pasa (paquetes grandes, un error, un abuso) y el equipo
  quiere saberlo.
- **Por qué no bloquea:** el freno duro que existe hoy (`creative_engine_config.monthly_budget_cap_usd`
  con `hard_stop_on_cap`) podría frenar unidades ya pagadas. En el diseño, asignar un plan escribe
  `monthly_budget_cap_usd` = tope del plan y `hard_stop_on_cap = false`. El freno duro queda solo
  para la emergencia, con `QUALIFY_CREATIONS_QUOTA=off`.
- **Margen estrecho con referencias:** Básico con todo a referencias de 30 s (≈ 111) queda a
  USD 9 del tope de 120. Un negocio con paquetes encima lo cruza; el aviso debe decir cuánto vino
  de paquetes.

**D19 — El enlace de pago se manda a mano, por ahora,** con lo que el equipo ya usa
(transferencia, Zelle, pago móvil, un enlace existente). Sin proveedor nuevo; la tabla de opciones
de proveedores queda para más adelante.

- **Por qué:** regla de la casa (ningún proveedor nuevo sin tabla de opciones y decisión del
  fundador). Con pocos clientes, cobrar a mano cuesta poco y deja aprender cuánto se pide antes de
  automatizar.

**Diseño técnico (principal-architect, segunda revisión en m-24852129, 2026-10-24).** Solo diseño,
sin código todavía:

- **Catálogo de planes en código**, versionado: `qualify_creative/creations_data/planes-v1.json`
  (`basico`, `plus`, `pro`, con sus cupos y su tope). Un cambio de plan es un PR medido, no una
  fila editable.
- **`tenant_plan_assignments`:** historial de qué plan tiene cada negocio desde qué mes, con
  origen, motivo, quién lo asignó y clave de idempotencia. Sin fila = Básico. **Subir de plan vale
  desde el mes en curso; bajar, desde el mes siguiente**, para que nunca quede un saldo negativo.
- **`creation_packs`:** paquetes por negocio y marca, con `expires_at = granted_at + 90 días`,
  procedencia y revocación (nunca se borra).
- **`creation_allocations`:** qué fuente (plan o paquete) pagó cada unidad de cada cargo (D17).
- **`creation_payments`:** lo pagado en USD. Solo la lee y escribe el rol `qualify_admin`; ningún
  camino del negocio puede verla, ni con un error en la interfaz (D1).
- El equipo escribe por comandos `just` (`set-plan`, `add-pack`, `revoke-pack`) y, después, desde
  el alta en Meegle (m-24852131). No hay sección del equipo en Configuración hasta que exista un
  ADR de identidad del equipo.
- **Migración `0089`, apilada sobre #299** (que trae `0088_creation_charges`). Se propone un
  ADR 40 `[PROPUESTO]`, que se escribirá en el PR de `0089`.

---

## 4. Tabla de decisiones

Estados: **main** = fusionado; **PR #299** = en el PR abierto (`feat/m-24848531-creaciones-del-mes`,
último commit `e1bd509c`, 2026-10-24); **diseñado** = diseño de principal-architect sin código;
**pendiente** = sin código ni diseño.

| # | Decisión | Fecha | Quién | Evidencia o prueba | Impacto en costo | Estado |
|---|---|---|---|---|---|---|
| D1 | El dueño ve creaciones, nunca dinero | 2026-10-23 | Fundador (decisión 8) | `epica-ux-navegacion-experiencia.md` §2; `ux-revision-equipo-2026-10-24.md` hallazgo 1 | Ninguno directo | PR #299 |
| D2 | 1 creación = USD 0,15; peso = ⌈p95/0,15⌉; pesos v1 → v2; tabla v5 → v7 | 2026-10-23 / 2026-10-24 | Data scientist (regla), fundador (acepta) | Producción: imagen p95 USD 0,068 (23 pedidos); SD25-001: v5 registraba 67 % de más con referencia | Techo de 0,15 por creación | PR #299 (pesos); main (`v7`, #304) |
| D3 | 30 creaciones al mes; `QUALIFY_CREATIONS_QUOTA=off` de emergencia («iguales para todos» reemplazado por D15) | 2026-10-23 / 2026-10-24 | Data scientist (recomienda), fundador | Medición §4 (escenarios **supuestos**); §2b-3b | Techo USD 4,50/mes; típico ≈ 1,80 | PR #299 |
| D4 | Presentador OmniHuman 1.5 en creaciones: 5/9/13/25; sin 45/60 s; sin 2.0 por ahora | 2026-10-23 / 2026-10-24 | Fundador | `v7` (`omnihuman-1-5` USD 0,12/s, confirmado oficialmente el 2026-10-24); medición §3, §5.1, §5.3 | 30 s = USD 3,65 | PR #299 |
| D5 | 4 videos de Seedance al mes, hasta 10 s; N diapositivas animadas = N videos | 2026-10-24 | Fundador | Medición §5.5 (23/46/68 creaciones) y §5.6 (12× por segundo frente a v1) | Techo 4 × 6,82 = USD 27,27 | PR #299 |
| D6 | El video se cuenta al aprobar (al encargar el final) | 2026-10-24 | Fundador | §2: final ~83 % del costo; vista previa ~17 % | Ninguno sobre el techo; quita al dueño el costo de descartar | PR #299 |
| D7 | 20 vistas previas al mes, contadas al crear, sin devolución salvo entrega nula | 2026-10-24 | Fundador | §2; SD25-001 (vista previa 5 s medida: 0,5315) | Techo ≈ USD 22,5 (10 s, sin referencia) | PR #299 |
| D8 | La vista previa vence a los 7 días; fecha en la tarjeta, aviso 2 días antes en Inicio, «Crearla otra vez» con «Usa 1 de tus vistas previas. Te quedan {p}.»; el aviso de Inicio abre «Por completar» ordenado por vencimiento | 2026-10-24 | Fundador | `DRAFT_TTL_SECONDS` (ModelArk) en `byteplus_ark.py`; `draft_mode.py` | Ninguno (una vista previa vencida no cuenta video) | main (caducidad); PR #299 (fecha, aviso, botón); los dos textos de experiencia se aplican sobre #299 |
| D9 | Un final que falla devuelve el video; reintentar no cuenta otra vez; `raw_final` se reutiliza | 2026-10-24 | Fundador | `draft_mode.py` (`kept_raw_final`, `final_retryable`); PR #304; reglas oficiales: las tareas fallidas no se cobran (H1, resuelta) | Ninguno: un reintento de una tarea fallida no paga un final de más | main (#304); PR #299 (devolución) |
| D10 | Reemplazadas: cobrar todo al crear; el ejemplo de las 6 creaciones; el video dentro de creaciones | 2026-10-23 / 2026-10-24 | Fundador | Ver tabla de D10 | — | Reemplazadas |
| D11 | Sin saldo: botón desactivado + «Pedir más a Qualify»; el equipo vende extras a mano, con procedencia | 2026-10-24 | Fundador | — (decisión de producto) | Ingreso extra; sin proveedor nuevo | Diseñado (m-24852129) |
| D12 | Los extras comprados duran 90 días | 2026-10-24 | Fundador | — (decisión de producto) | Ninguno por unidad | Diseñado (`creation_packs`) |
| D13 | Sin WhatsApp: «Listo. Te escribimos a tu correo con el enlace de pago.» | 2026-10-24 | Fundador | Hipótesis de canal (`perfil-cliente-pyme.md` §5) | Ninguno | Pendiente (m-24852129) |
| D14 | Los extras se venden como planes con nombre | 2026-10-24 | Fundador | — | — | Diseñado |
| D15 | Básico 30/4/20, Plus 60/8/40, Pro 120/16/80; todos empiezan en Básico; paquetes de 90 días encima | 2026-10-24 | Fundador | Peor caso de §6 × 1, 2 y 4 | Peor caso ≈ 55 / 110 / 220 USD (sin referencias) | Diseñado (`planes-v1.json`, `tenant_plan_assignments`; m-24852145) |
| D16 | «Te quedan 5 de 6 videos este mes (2 extra, vencen el 22 de enero).» | 2026-10-24 | Fundador | — | Ninguno | Diseñado |
| D17 | Primero el cupo del plan, después los paquetes, el que vence antes primero | 2026-10-24 | Fundador; forma de guardarlo: principal-architect | Diseño en m-24852129 (`creation_allocations`) | Ninguno | Diseñado |
| D18 | Tope de alerta por plan: USD 120 / 240 / 480; avisa en Lark, nunca bloquea | 2026-10-24 | Fundador | Peor caso con referencias: 111 / 222 / 444 (D15) | Alerta temprana; quita el freno duro que podía bloquear lo pagado | Diseñado |
| D19 | Enlace de pago a mano, sin proveedor nuevo | 2026-10-24 | Fundador | Regla de la casa (proveedor nuevo = tabla de opciones) | Sin costo de proveedor | Vigente (proceso manual) |

---

## 5. Costo por unidad

p50 solo existe donde hay datos de producción. Donde no hay datos, la casilla dice «—» y el p95
es un techo calculado.

**Todas las tarifas de esta tabla coinciden con los precios oficiales leídos el 2026-10-24**
(comentario de precios en m-24852128; capturas guardadas con su URL y fecha). Seedance 2.5: USD
10,70 por millón a 480p/720p y 11,70 a 1080p; con video de entrada, 6,40 y 7,00. OmniHuman 1.5:
0,12/s; OmniHuman 2.0: 0,07/s. Seed Speech: 30 por millón de caracteres; ranura de voz, USD 2.
Seedream 5.0 lite: 0,035 por imagen. Claude: tabla del skill `claude-api` (caché del 2026-10-06).
Las tarifas de Seedance se leyeron con `arkcli pricing models`: es el precio de nuestra cuenta, que
no tiene descuento. La vista previa de 2.5 «se cobra como un 480p normal»: no hay descuento de
borrador.

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
| Final 1080p, 5 s, sin referencia | — | 2,85 | calculado con tarifa y fórmula oficiales; falta un conteo real | §2 | v7 |
| Final 1080p, 10 s, sin referencia | — | 5,70 | ídem | §2 | v7 |
| Final 1080p, 5 s, con una referencia de 7,33 s | — | 4,20 | ejemplo oficial (600 126 tokens × 7,00/M) | `seedance-2-5` § Draft mode, leída 2026-10-24 | v7 |
| Video completo 5 s / 10 s, sin referencia | — | 3,44 / 6,82 | calculado | medición §5.5 y §6.4 | v7 |
| Video completo 5 s / 10 s con referencia de duración desconocida (se cuentan 30 s, y el final vuelve a cobrar la entrada) | — | 14,20 / 16,22 | calculado; la regla del final quedó confirmada (H3) | medición §6.4 | v7 |

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

Esta es la cifra de **Básico**. Plus y Pro la multiplican por 2 y por 4 (tabla de D15).

**Con videos de referencia de duración desconocida** (el brief no guarda cuánto dura el video,
así que los pesos cuentan el máximo de una tarea, 30 s; medición §5.2):

| Parte | Cálculo (tarifa con video de entrada) | USD |
|---|---|---:|
| 20 vistas previas de 10 s + 30 s de entrada | 20 × (0,068 + 0,0632 × 40) | 51,92 |
| 4 finales, que vuelven a cobrar la entrada (H3, confirmada) | 4 × 0,3407 × 40 | 54,51 |
| 30 creaciones | | 4,50 |
| **Total** | | **≈ 111** |

Antes de la lectura oficial el rango era USD 70 a 111, según si el final volvía a cobrar la
entrada. Ya se sabe que sí (H3), así que queda el extremo alto. Coincide con el techo que calcula
la medición del PR #299 (§7.4, USD 110,8).

Es un techo teórico: exige que las 24 tareas lleven una referencia de 30 s. La referencia real
medida fue de 7,33 s y 22 s (SD25-001). La estimación previa al gasto ya lee la duración real del
video con PyAV y usa 30 s solo si no puede leerla (`docs/modelos-generativos/seedance-2-5.md`,
hallazgo 2); lo que falta es que el **peso** también la use.

**Lo normal será mucho menos.** Con la mezcla típica de creaciones (≈ USD 1,80) y, por ejemplo,
2 videos de 5 s con 2 vistas previas cada uno: 4 × 0,60 + 2 × 2,85 + 1,80 ≈ **USD 9,90**
(**estimación**, sin datos de uso real).

**La red de seguridad en dólares (D18).** Hoy cada marca tiene
`creative_engine_config.monthly_budget_cap_usd` con `hard_stop_on_cap` encendido por defecto
(`migrations/postgres/versions/0009_creative.py`; `service.py`, `budget_state`). Si ese tope
quedara por debajo del peor caso, **bloquearía videos que el cupo promete**: la propuesta
original del ticket (1,5 × 4,50 = USD 6,75) no alcanzaba ni para dos videos de 5 s (medición
§6.4). D18 lo resuelve con un tope por plan que solo avisa (USD 120 / 240 / 480), por encima del
peor caso de cada plan. En el diseño, asignar un plan escribe ese tope y apaga el freno duro.

---

## 7. Riesgos e hipótesis

| # | Hipótesis | Qué pasa si es falsa | Cómo verificarla |
|---|---|---|---|
| H1 | **BytePlus no cobra las tareas de video que fallan.** **RESUELTA el 2026-10-24:** las reglas oficiales dicen «You are only charged for successfully generated videos. No fee is charged if generation fails» (`model-pricing`). Coincide con lo que asume `byteplus_ark.py` | — | Queda como comprobación, no como hipótesis: cruzar la primera factura tarea por tarea (`cgt-…`) con las tareas que `creative_usage_events` marca como fallidas |
| H2 | **El final 1080p cuesta lo que dice la fórmula** (48 672 tokens/s a 3:4, USD 0,5695/s). **Precio confirmado el 2026-10-24:** tarifa oficial 11,70/M y fórmula oficial igual a la nuestra; el ejemplo oficial a 1080p 16:9 da 0,569/s. El final de 2.5 solo admite 1080p | Si el conteo real de tokens se aparta de la fórmula, se mueven el costo de video y la cota de USD 55 | Falta solo leer `usage.completion_tokens` de un final real (pendiente desde #304). El ticket m-24849137 tiene marcado el criterio de anotar el costo del final, pero no anota ningún número |
| H3 | **El final de una vista previa con video de referencia vuelve a cobrar los segundos de entrada.** **RESUELTA el 2026-10-24: sí.** «The input video duration is calculated based on the input video in Step 1. The Draft video is not counted» (`seedance-2-5` § Draft mode). 5 s con 7,33 s de referencia ≈ USD 4,20 de final, no ≈ 1,70. El supuesto conservador de v2 era el correcto | — | — |
| H4 | **Duración del video de referencia desconocida = 30 s** en los pesos | Sobreestima el costo; con la regla anterior (video dentro de creaciones) hacía imposible usar referencias. Con el cupo de videos (D5) ya no afecta al dueño, solo al techo del equipo | Guardar en el brief la duración leída con PyAV (ya se lee para la estimación previa) y usarla en el techo |
| H5 | **El sonido no cambia el precio** de Seedance 2.5 | Habría que versionar `v8` y la tabla de pesos | Medido en SD25-001: el clip con sonido (115 690 tokens) y la diapositiva sin sonido (118 851) encajan en la misma fórmula. Falta confirmarlo con la factura (medición §5.4) |
| H6 | **El cupo de 30 creaciones alcanza** para un negocio real | Si el p90 real pasa de 30, los dueños se quedan sin saldo antes de fin de mes | Segunda medición (§8) |
| H7 | **Las tarifas de `v7` son las vigentes.** **Confirmado el 2026-10-24** para todos los modelos que usa la generación (`arkcli pricing models` y las páginas oficiales, con capturas) | — | Volver a leer los precios cuando se active un modelo nuevo o se cambie la tabla |
| H8 | **OmniHuman 1.5 se cobra por segundo de voz, a USD 0,12.** La tarifa quedó confirmada el 2026-10-24 (`omnihuman1_5overview`); falta ver en factura que la duración cobrada sea la de la voz | El presentador quedaría mal pesado | Factura; no hay ningún presentador en producción (medición §2) |
| H9 | **Consumo mínimo con video de entrada no modelado** (hueco de `v7`, no una hipótesis de precio). La página oficial fija un mínimo de tokens por resolución, formato y duración cuando hay video de entrada; en los ejemplos, 2 a 4 s de entrada cuestan igual | Una referencia de menos de 4 s se estima por debajo de lo facturado; el registro de costos se queda corto | Leer las tablas oficiales de mínimos (enlazadas desde `model-pricing`, en una wiki de Lark de ByteDance, todavía no leídas) y aplicar el piso en `estimate_video_tokens`. Responsable: m-24851828 |

**Huecos de `v7` encontrados en la lectura oficial** (no se tocó código; responsable:
m-24851828, pesos v2 y precios):

- el consumo mínimo con video de entrada (H9);
- faltan las tarifas con video de Seedance 2.0 (4,3 / 4,7 por millón), 2.0 fast (3,3) y
  2.0 mini (2,1). Hoy se cobran a la tarifa sin video: el registro se pasa, nunca se queda corto,
  y ninguno de esos modelos está activado en la cuenta;
- notas de fuente viejas: `seed-tts-1.0` (ya leída: 30 por millón, deja de ser «conservador»),
  `omnihuman-2-0` (0,07 confirmado; la tarjeta de 0,12 es la 1.5) y `dreamina-seedance-2-5-260628`
  (agregar «las fallidas no se cobran» y la regla del final).

**Riesgos que no son hipótesis:**

- **La medición de producción es casi vacía:** 3 días, 2 negocios de prueba, 23 pedidos, solo
  imágenes (medición §2). Solo el peso de la imagen está confirmado.
- **Planes y paquetes son solo diseño.** Hasta que exista `0089`, «Pedir más a Qualify» no puede
  sumar unidades: el equipo no tiene por dónde escribirlas.
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
7. Cuántos negocios pasan a Plus o Pro, cuántos paquetes se compran y cuánto de cada paquete se
   usa antes de los 90 días (D12, D15).
8. Cuántas veces salta el tope de alerta de cada plan (D18) y por qué.

**Antes de eso, en cuanto se pueda (no esperan a los 30 días):**

- el conteo de tokens del primer final 1080p real (H2);
- la primera factura de BytePlus (la comprobación de H1, y H5 y H8);
- las tablas oficiales de consumo mínimo con video de entrada (H9).

Cada resultado se documenta el mismo día en `docs/modelos-generativos/` y, si cambia un peso, en
una nueva versión de pesos.

---

## 9. Preguntas abiertas

1. **Precio de cada plan y de cada paquete** (D14, D15). Los costos ya están confirmados con los
   precios oficiales (§5, §7). Referencia de costo, peor caso por mes: Básico ≈ USD 55 (111 con
   referencias), Plus ≈ 110 (222), Pro ≈ 220 (444). Por unidad: una creación cuesta como mucho
   USD 0,15, un video de 10 s ≈ 6,82 y una vista previa de 10 s ≈ 1,12.
2. **Tamaño de los paquetes y tope por paquete.** Cuántas creaciones, videos y vistas previas trae
   cada paquete de 90 días, y el tope por fila que evita un error de dedo (principal-architect
   propone, por ejemplo, no más que la cuota de Pro).
3. **Qué hace el equipo cuando salta el tope de alerta** (D18): revisar y no hacer nada, llamar al
   negocio, ofrecerle subir de plan o frenar a mano. El aviso debe decir cuánto del gasto vino de
   paquetes.
4. **¿El dueño ve el nombre de su plan?** D16 define cómo ve sus unidades, pero no si la app dice
   «Básico», «Plus» o «Pro».
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
| **Plan** | Básico, Plus o Pro: cuánto trae cada mes (D15). Todo negocio empieza en Básico |
| **Paquete** | Unidades extra compradas que duran 90 días desde que se asignan (D12). Se gastan después del cupo del plan, el que vence antes primero (D17) |
| **Tope de alerta** | Gasto en dólares por plan y mes que, al alcanzarse, avisa al equipo en Lark. Nunca bloquea (D18) |

---

## 11. Fuentes

- `docs/creaciones-del-mes-medicion.md`: en `main`, §1–§4 (v1, 2026-10-23); en la rama del PR #299
  (`origin/feat/m-24848531-creaciones-del-mes`, `e1bd509c`), §5 (v2), §6 (videos del mes) y §7 (videos
  al aprobar y 20 vistas previas).
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
- PR #299 (creaciones del mes), abierto: commits `c5e15617`, `ff1f93d2`, `a09c818f`, `7463782d` y
  `e1bd509c`.
- Lectura de producción del 2026-10-23 (medición §2): 3 días, solo imágenes, p50 USD 0,063 y p95
  0,068 por imagen.
- `docs/ux-revision-equipo-2026-10-24.md`: hallazgos 1 y 2 y §«Pesos de #299».
- `docs/epica-ux-navegacion-experiencia.md` §2 (decisión 8), §2b (3a y 3b), §4 (CREAR-5) y la
  historia CREAR-5.
- Meegle, épica m-24848869 y sus pruebas: m-24848887 (clip con 2 videos de referencia, 259 802
  tokens), m-24849137 (galería con diapositiva animada sin referencia, 49 673 tokens, USD 0,5315)
  y m-24849431 (clip y galería con una referencia de 7,33 s, 115 690 y 118 851 tokens).
- Lectura oficial de precios del 2026-10-24: comentario «Precios oficiales vs. tabla v7» en
  m-24852128, con capturas adjuntas (`model-pricing` y `seedance-2-5` de ModelArk,
  `omnihuman1_5overview`, la página de producto de OmniHuman, `voicereplicationbilling`,
  `TTS_Billing`, `arkcli pricing models`). Cada archivo lleva su URL y su fecha.
- Decisiones D12 a D19: comentario del fundador en m-24852128 (2026-10-24). Diseño de planes y
  paquetes: segunda revisión de principal-architect en m-24852129 (2026-10-24), que reemplaza los
  puntos 1, 2 y 5 de la primera.
- PR #299 en `e1bd509c`: `docs/creaciones-del-mes-medicion.md` §7 (videos al aprobar, 20 vistas
  previas, vencimiento visible).
- Código de presupuesto por marca: `migrations/postgres/versions/0009_creative.py`
  (`monthly_budget_cap_usd`, `hard_stop_on_cap`), `packages/api/src/qualify_api/creative/service.py`
  (`budget_state`).
