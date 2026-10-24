# Creaciones del mes — pesos y cupo medidos (CREAR-5, m-24848531)

Épica: UX m-24842956 · Historia: `CREAR-5` en `docs/epica-ux-navegacion-experiencia.md`.
Autor: data scientist / FDE · Fecha: 2026-10-23 · Pesos: **`pesos-creaciones-v1`** sobre la
tabla de precios **`v5`** (`packages/creative/src/qualify_creative/pricing_data/v5.json`).

> **Vigentes desde 2026-10-24: `pesos-creaciones-v2` sobre la tabla `v7` (§5, m-24851828).**
> Las secciones 1 a 4 son la medición de v1 y se conservan como estaban.
>
> **Videos del mes (decisión del fundador, 2026-10-24, §6):** el video generado ya no usa
> creaciones. Cada mes trae **30 creaciones y 4 videos** aparte; cada video cuenta 1, dure 5 o
> 10 s. Lo que §5.5 y §5.6 dicen del video generado en creaciones quedó reemplazado por §6.

El dueño ve «creaciones del mes» («Te quedan 18 de 30 este mes»), nunca dinero. El equipo ve
los dólares. Esta página fija cuánto vale cada pedido en creaciones, con qué datos se midió y
cuánto queda sin medir.

## 1. Regla

- **1 creación = USD 0,15** de costo de proveedor (techo, no promedio).
- **Peso de un pedido = ⌈costo p95 del pedido en USD / 0,15⌉**, mínimo 1. El costo p95 sale de
  producción cuando hay datos y, si no, de la tabla de precios `v5` con el copy a su p95 medido.
- Se cobra **al pedir** con el peso de la duración/cantidad pedida; una generación fallida o
  moderada **devuelve** las creaciones. Si el proveedor factura más de lo estimado (por ejemplo,
  la voz dura 32 s en vez de 30 s), la diferencia la absorbe el equipo: al dueño nunca se le
  cobra más de lo que se le anunció.
- Cada cobro guarda peso, `pesos-creaciones-v1` y `v5` (procedencia).

## 2. Lo que dice producción (lectura única, solo lectura, 2026-10-23)

Autorizada por el fundador el 2026-10-23: lectura agregada, de una sola vez, por la vía
documentada (`dc exec postgres psql` en el servidor, §7 de `docs/despliegue-hetzner.md`),
dentro de `BEGIN TRANSACTION READ ONLY` y con `default_transaction_read_only=on`. Solo conteos
y sumas de `content_briefs`, `content_drafts`, `creative_usage_events`, `creative_angle_sets` y
`template_runs`; ningún texto, indicación ni dato de clientes finales. Ventana pedida: 60 días.

**Hallazgo principal: en producción no hay todavía uso real que medir.** Todo el historial de
creación empieza el **2026-10-21** (3 días, no 60), es de **un solo tipo** (imagen con texto,
`static_flyer`) y viene de dos negocios que no figuran entre los clientes reales: «Raul Dev
Games» (negocio de pruebas de un desarrollador, creado el 2026-10-21) y «Zapatería» (creado el
2026-10-07; no está en la lista de clientes de `qualify-context`). POLETTE existe y no ha creado
nada; Bianki no tiene negocio en producción. No hay ningún carrusel, video, clip, presentador
ni plantilla (`template_runs` = 0).

| Negocio | Tipo | Pedidos | Repeticiones (otra versión) | Creaciones v1 | USD real | Días activos |
|---|---|---:|---:|---:|---:|---:|
| Zapatería | Imagen con texto | 20 | 0 | 20 | 1,22 (+0,07 en 3 juegos de ángulos) | 2 (22 y 23 de octubre) |
| Raul Dev Games | Imagen con texto | 3 | 1 (imagen + texto) | 4 | 0,27 | 1 (21 de octubre) |
| POLETTE | — | 0 | 0 | 0 | 0 | 0 |
| **Total** | | **23** | **1** | **24** | **1,49** | |

Costo por pedido de imagen con texto (23 pedidos, `claude-opus-5-5` + `seedream-5-0-lite-260128`):
**p50 USD 0,063, p95 USD 0,068**, máximo 0,134 (el que se repitió). Texto (Claude) p50 0,028 /
p95 0,033; imagen 0,035 fija. Un juego de ángulos cuesta ≈ USD 0,025 (3 juegos, 20 pedidos).

**Conclusión:** el peso 1 de la imagen queda **confirmado** con datos (p95 0,068 < 0,15, con
margen 2,2×). Los demás pesos **no están confirmados con producción** y salen de la tabla `v5`.
La mediana y el p90 de creaciones por negocio y mes **no se pueden calcular**: n = 2 negocios
de prueba y 3 días; extrapolar «Zapatería 10 por día» a 300 al mes sería inventar.

## 3. Tabla de pesos `pesos-creaciones-v1`

| Pedido | Costo p95 estimado (USD) | Creaciones | Origen |
|---|---:|---:|---|
| Imagen con texto (incluye su juego de ángulos) | 0,07 | **1** | Producción (23 pedidos) |
| Otra versión de la imagen (imagen + texto) | 0,07 | **1** | Producción (1 caso) + `v5` |
| Otra versión solo del texto | 0,03 | **0** | Producción (p95 del texto) |
| Proponer ángulos de nuevo | 0,025 | **0** | Producción (3 juegos) |
| Carrusel de 2 a 3 imágenes | 0,14 | **1** | `v5` |
| Carrusel de 4 a 7 imágenes | 0,28 | **2** | `v5` |
| Carrusel de 8 a 10 imágenes | 0,38 | **3** | `v5` |
| Video con plantilla o clip propio editado (Remotion, sin video generado) | 0,07 | **1** | `v5` (Remotion = 0 USD) |
| Video generado de 5 s (Seedance 1.0 pro, 720p vertical) | 0,34 | **3** | `v5` |
| Video generado de 10 s | 0,61 | **5** | `v5` |
| Video generado de 15 s | 0,88 | **6** | `v5` |
| Presentador de 15 s (OmniHuman 1.5 + voz) | 1,84 | **13** | `v5` |
| **Presentador de 30 s (OmniHuman 1.5 + voz)** | 3,65 | **25** | `v5` |

Cálculo del video generado: Seedance 1.0 pro factura 720 × 1280 × 24 / 1024 = 21 600 tokens
por segundo a USD 2,5 por millón = **USD 0,054 por segundo**, más texto (0,033) e imagen de
partida (0,035): peso = ⌈(0,068 + 0,054 × s) / 0,15⌉.

Cálculo del presentador: OmniHuman 1.5 (`realman_avatar_picture_omni15_cv`, el predeterminado)
a **USD 0,12 por segundo** de voz, Seed Speech a USD 30 por millón de caracteres (≈ 450
caracteres en 30 s = 0,014) y el guion (0,033): 30 × 0,12 + 0,014 + 0,033 = **USD 3,65 →
25 creaciones**; en general, peso = ⌈(0,047 + 0,12 × s) / 0,15⌉. La ranura de voz clonada
(`seed-icl-2.0-slot`, USD 2,00) se paga una vez al preparar el avatar de la marca y no entra
en el pedido. Si el presentador pasara a **OmniHuman 2.0** (USD 0,07 por segundo), el de 30 s
costaría USD 2,15 → **15 creaciones**; ese cambio necesita su propia prueba de calidad
(`docs/modelos-generativos/`) antes de bajar el peso.

**Decidido (fundador, 2026-10-23):** el presentador de 30 s se queda en **25 creaciones** con el
modelo actual (OmniHuman 1.5). No se evalúa OmniHuman 2.0 por ahora.

## 4. Cupo mensual recomendado

Sin uso real, el cupo se dimensiona con un negocio tipo del segmento (PYME que publica 3 a 4
veces por semana, unas 15 publicaciones al mes) en dos escenarios:

| Escenario | Mezcla del mes | Creaciones |
|---|---|---:|
| Típico («p50» supuesto) | 10 imágenes + 3 otras versiones de imagen + 2 carruseles de 5 + 1 video de 5 s | 10 + 3 + 4 + 3 = **20** |
| Exigente («p90» supuesto) | 12 imágenes + 5 otras versiones + 3 carruseles de 5 + 2 videos de 10 s | 12 + 5 + 6 + 10 = **33** |
| Exigente + un presentador de 30 s | lo anterior + 1 presentador | 33 + 25 = **58** |

**Recomendación: mantener 30 al mes.** Cubre el escenario típico con 10 de holgura y queda
3 por debajo del exigente, que es justo donde debe avisar. Costo máximo para el equipo por
negocio que agota el cupo: 30 × 0,15 = **USD 4,50 al mes**; con la mezcla típica el costo real
es ≈ USD 1,80 (las imágenes cuestan 0,07, no 0,15).

**El presentador de 30 s no cabe junto con un mes normal:** usa 25 de 30. Decisión del
fundador (2026-10-23): el dueño sí puede pedirlo, cuesta varias creaciones y la app se lo dice
antes. Texto sugerido para la confirmación (revisar con `qualify-copy-es`): «Este video con
presentador usa 25 de tus creaciones. Te quedarían {n} este mes.» Con saldo menor a 25 no se
genera y se le ofrece el de 15 s (13 creaciones).

**Cuándo revisar:** con 30 días de uso de al menos 3 negocios reales (Bianki, Polette y uno de
inmobiliaria o viajes), repetir la misma lectura agregada y recalcular p50/p90 de creaciones por
negocio y mes y el p95 de costo por tipo. Si el p90 real pasa de 30, subir el cupo; si algún
p95 por tipo supera su peso × 0,15, subir ese peso y versionar `pesos-creaciones-v2`.

## 5. Pesos `pesos-creaciones-v2` (vigentes desde 2026-10-24, m-24851828)

Fecha: 2026-10-24 · Pesos: **`pesos-creaciones-v2`**
(`packages/creative/src/qualify_creative/creations_data/pesos-creaciones-v2.json`) sobre la
tabla de precios **`v7`**. `pesos-creaciones-v1` se conserva tal cual (versionado, no se edita)
y cada cobro sigue guardando su peso, la versión de pesos y la versión de la tabla de precios.

**Por qué hay v2.** v1 se calculó antes de #304 (Seedance 2.5 con modo borrador, m-24820142).
Sobre `main` dejaba de cuadrar en seis puntos (`docs/ux-revision-equipo-2026-10-24.md` §Pesos
de #299): duración del clip, presentador de 5 y 10 s, vista previa + final, video de
referencia, versión de la tabla y sonido.

### 5.1 Decisiones del fundador (2026-10-24)

- **Presentador:** se ofrece a **5, 10, 15 y 30 s**. **45 y 60 s quedan fuera**: no tienen
  fila, no aparecen en las duraciones del presentador y una prueba lo comprueba.
- **Modo borrador:** todo se cobra **al crear**: la vista previa a 480p y el final a 1080p que
  se hace al aprobar. **Aprobar no cobra nada.** Si el final falla, se devuelve solo la parte
  del final y se registra aparte.
- **Duración del clip:** un clip se cobra por **su** duración (`clip_duration`), no por la del
  presentador (`media_duration`). Un clip de 5 s se cobra como de 5 s.
- **Video de referencia:** se cobran sus segundos de entrada.
- **Tabla de precios:** `v7`.
- **Sonido:** lo decide data-scientist-fde (§5.4).

### 5.2 Cómo se calcula el video generado (Seedance 2.5)

El peso ya no es una fila escrita a mano: sale de la tabla `v7` al cargar los pesos, así que no
puede separarse de la tabla que cita. Modelo `dreamina-seedance-2-5-260628`, el de producción
para clip, avatar de Seedance y diapositiva animada.

| Parte | Tokens por segundo (proporción más cara, 3:4) | Tarifa `v7` sin / con video de entrada | USD por segundo sin / con video |
|---|---:|---:|---:|
| Vista previa 480p (560 × 752) | 9 870 | 10,70 / 6,40 por millón | 0,1056 / 0,0632 |
| Final 1080p (1248 × 1664) | 48 672 | 11,70 / 7,00 por millón | 0,5695 / 0,3407 |

- Tokens por segundo = ancho × alto × 24 / 1024 (fórmula de ModelArk, la misma de
  `estimate_video_tokens`). Se toma 3:4, la proporción con más píxeles; 9:16 da 9 607 y 48 600.
- Más **USD 0,068 fijos** por video (texto p95 0,033 + una imagen 0,035, medidos en producción).
  El clip no genera imagen propia; se deja el fijo de v1 como techo.
- Peso = ⌈(fijo + vista previa + final) / 0,15⌉. **Parte del final** = peso − ⌈(fijo + vista
  previa) / 0,15⌉. Esa parte es la única que se devuelve si el final falla.
- **Video de referencia:** con video de entrada la tarifa baja, pero se cobran sus segundos al
  tamaño de salida (medido en `docs/modelos-generativos/seedance-2-5.md`, SD25-001: 115 690 y
  118 851 tokens frente a ~48 000 sin entrada). v2 supone que el final a 1080p **también**
  vuelve a cobrar la entrada: no está medido en vivo, y así el peso nunca se queda corto. El
  brief no guarda cuánto dura el video de referencia, así que se cobra el máximo que acepta una
  tarea de 2.5: **30 s**.
- El clip sigue limitado a 15 s (`max_output_seconds`).

### 5.3 Presentador (OmniHuman 1.5, sin vista previa)

Costo = guion 0,033 + OmniHuman 1.5 a USD 0,12 por segundo + voz (Seed Speech, USD 30 por
millón de caracteres, 15 caracteres por segundo). OmniHuman no tiene vista previa ni final:
el presentador no tiene parte del final y no se le devuelve nada aparte.

### 5.4 Sonido: no cambia el peso

- `v7` tiene **una sola tarifa** para Seedance 2.5, con o sin sonido (página de precios leída
  el 2026-10-07 y el 2026-10-23). El 2026-10-24 se intentó releer la página en vivo y no se
  pudo: la página carga sus precios con JavaScript.
- En SD25-001 el clip con sonido (`generate_audio` encendido) facturó 115 690 tokens y la
  diapositiva sin sonido 118 851. Las dos quedan dentro de la fórmula de tokens (118 461 y
  121 697), así que el sonido **no añadió tokens**.
- **Decisión:** «Con sonido» no cambia el peso (`audio_usd_per_second = 0`). Una prueba lo
  comprueba. Si la primera factura de BytePlus cobra el sonido aparte, se pone su precio en
  `v8` y se versiona `pesos-creaciones-v3`.

### 5.5 Tabla `pesos-creaciones-v2`

| Pedido | Costo estimado (USD) | Creaciones | De ellas, parte del final | Cambio frente a v1 |
|---|---:|---:|---:|---|
| Imagen con texto (incluye su juego de ángulos) | 0,07 | **1** | — | igual |
| Otra versión de la imagen | 0,07 | **1** | — | igual |
| Otra versión solo del texto / proponer ángulos de nuevo | ≤ 0,03 | **0** | — | igual |
| Carrusel de 2 a 3 / 4 a 7 / 8 a 10 imágenes | 0,14 / 0,28 / 0,38 | **1 / 2 / 3** | — | igual |
| Guion para una persona; video con plantilla | 0,03–0,07 | **1** | — | igual |
| Clip (o avatar de Seedance) de 5 s, sin referencia | 3,44 | **23** | 19 | era 3 |
| Clip de 10 s | 6,82 | **46** | 38 | era 5 |
| Clip de 15 s | 10,19 | **68** | 56 | era 6 |
| Clip de 5 s con 3 s de video de referencia (medidos) | 3,30 | **22** | 18 | nuevo |
| Clip de 5 s con 7,33 s de referencia (el caso medido en SD25-001) | 5,05 | **34** | 28 | nuevo |
| Clip de 5 s con video de referencia de duración desconocida (se cobran 30 s) | 14,20 | **95** | 79 | nuevo |
| Diapositiva animada de 5 s en un carrusel (se suma a las imágenes) | 3,44 | **+23** | 19 | era +3 |
| Presentador de 5 s | 0,64 | **5** | — | nuevo (en v1 costaba 13) |
| Presentador de 10 s | 1,24 | **9** | — | nuevo (en v1 costaba 13) |
| Presentador de 15 s | 1,84 | **13** | — | igual |
| Presentador de 30 s | 3,65 | **25** | — | igual |
| Presentador de 45 o 60 s | — | **no se ofrece** | — | decisión del fundador |

Cuando el mes no alcanza para el presentador pedido, la pantalla ofrece **el más largo que
alcance** (con 20 creaciones, el de 15 s; con 11, el de 10 s; con 6, el de 5 s). Antes ofrecía
siempre el de 15 s.

### 5.6 Lo que los números contradicen del plan (para decidir)

Con las decisiones de §5.1 y la tabla `v7`, **el video generado no cabe en un mes de 30**:

- Un clip de **5 s usa 23 de 30**. Los de **10 s (46) y 15 s (68) no caben ni con el mes
  entero**, así que la pantalla ya no los ofrece: el control de duración del clip muestra solo
  lo que el saldo paga, y al menos el de 5 s (`clip_duration_choices`).
- Un clip con **video de referencia** pasa de 30 casi siempre: el brief no guarda la duración
  del video y se cobran 30 s (95). Con la duración medida, solo una referencia de unos 6 s o
  menos cabe en un mes completo. Hoy la pantalla deja subir el video de referencia y después
  dice «Te faltan N creaciones».
- El 84 % del costo es el **final a 1080p** (USD 0,57 por segundo, frente a 0,11 de la vista
  previa). En v1, Seedance 1.0 pro a 720p costaba 0,054 por segundo: el video generado cuesta
  ahora **12 veces más** por segundo.

Opciones (precios de `v7`, clip de 5 / 10 / 15 s):

| Opción | Creaciones | Qué cambia |
|---|---|---|
| A. Lo de hoy: vista previa 480p + final 1080p | 23 / 46 / 68 | nada |
| B. Final a **720p** en vez de 1080p | 12 / 23 / 35 | el final cuesta 2,4 veces menos por segundo; necesita una prueba de calidad en `docs/modelos-generativos/` |
| C. Sin vista previa, directo a 1080p | 20 / 39 / 58 | se pierde la vista previa barata; ahorro pequeño |
| D. Subir el cupo para quien use video, o un cupo de video aparte | — | fuera del alcance de este ticket (el cupo de 30 y el tope en dólares no se tocan) |

**Recomendación:** B, final a 720p, con una prueba de calidad antes (mismo borrador, final a
720p y a 1080p, a la vista de una dueña en un teléfono). Con B el clip de 5 s usa 12, cabe
junto a un mes normal (20 + 12 = 32, cerca de 30) y el de 10 s usa 23. Hasta que se decida,
v2 cobra lo que de verdad cuesta (A) y la pantalla no ofrece lo que no se puede pagar.

Pendiente de medir: un final a 1080p de un borrador **con** video de entrada (si vuelve a
cobrar la entrada) y la primera factura de BytePlus (tarifas y sonido). Cualquiera de los dos
puede bajar los pesos del video con referencia y lleva a `pesos-creaciones-v3`.

### 5.7 Cómo se cobra y se devuelve (código)

- `weight_for(brief)` / `weight_for_request(...)` devuelven el peso y `final_weight`, la parte
  del final. La pantalla y el servicio leen la misma regla.
- `creation_charges` (migración `0088`, antes `0084`, ahora sobre la cabeza `0086` de `main`, que encadena `0084 → 0087 → 0086`)
  guarda `final_weight`, y además `final_refunded_at` y `final_refund_reason` cuando el final
  falla. La fila sigue en `charged` por su vista previa y el saldo cuenta `weight −
  final_weight`. La devolución se hace una sola vez.
- Se devuelve la parte del final cuando el proveedor falla el final, cuando falla nuestro
  código, cuando no se puede guardar, cuando no se pudo encargar y cuando la vista previa
  venció. **Reintentar un final que falló no vuelve a cobrar**: el fallo fue nuestro o del
  proveedor, no del dueño.
- El informe del equipo (`creations_report`) cuenta la parte devuelta como devuelta.
- Pruebas: `packages/creative/tests/test_creations.py`,
  `packages/api/tests/test_creations_ledger.py` y `Qualify/test_creations_of_the_month.py`.

> **Reemplazado por §6** en lo que toca al video generado: ya no hay `final_weight`; lo que
> se devuelve cuando un final falla es el video.

## 6. Videos del mes: un cupo aparte (decisión del fundador, 2026-10-24)

Fecha: 2026-10-24 · Pesos: **`pesos-creaciones-v2`** sobre la tabla **`v7`** (el mismo archivo
de §5, con un bloque nuevo `videos`; v2 no se había publicado todavía, así que se completa en
su lugar en vez de crear una v3). Es la opción D de §5.6.

### 6.1 Qué se decidió

- **Cada mes trae 4 videos, aparte de las 30 creaciones.** Un «video» es todo video generado
  con Seedance: el clip, el avatar de Seedance, cada diapositiva animada de un carrusel y el
  clip que sigue un video de referencia.
- **Cada uno cuenta 1 video**, dure 5 o 10 s, con o sin video de referencia y con o sin sonido.
  **No usa creaciones.**
- **No se ofrecen videos de 15 s** (ni más largos): el clip, el avatar de Seedance y la
  diapositiva animada se piden a 5 o 10 s. Si llega uno más largo (un control viejo o un
  pedido armado a mano), no se ofrece y no se cobra.
- **Un carrusel con N diapositivas animadas usa N videos**, más las creaciones del propio
  carrusel (1, 2 o 3 según sus imágenes, como siempre).
- **El presentador (OmniHuman) sigue en creaciones**: 5, 9, 13 y 25 para 5, 10, 15 y 30 s.
- Imágenes, carruseles, plantillas y guiones siguen en creaciones, cupo 30.
- **Cobro:** se cobra **al crear**. Aprobar no cobra nada. Si el final a 1080p falla, **se
  devuelve el video**. Reintentar un final que falló no vuelve a cobrar.
- **El mismo cupo para todos los negocios**, también los que opera el equipo. No hay
  interruptor por negocio; `QUALIFY_CREATIONS_QUOTA=off` sigue siendo el interruptor de
  emergencia de toda la instalación.
- **El dueño nunca ve dinero** (decisión 8).

### 6.2 Lo que lee el dueño

| Dónde | Texto |
|---|---|
| Panel lateral de Crear | «Te quedan {n} de 30 creaciones y {v} de 4 videos este mes.» |
| Resumen, antes de un video | «Este video usa 1 de tus 4 videos del mes. Te quedarían {v}.» |
| Resumen, carrusel con diapositivas animadas | «Esta publicación usa 1 de tus creaciones y 2 de tus 4 videos del mes. Te quedarían 17 de 30 creaciones y 1 video.» |
| Sin videos este mes (Crear queda desactivado) | «Ya usaste tus 4 videos de este mes. Vuelven el {fecha}.» |
| Carrusel con más diapositivas animadas que videos | «Esta publicación usa 3 videos y te quedan 2 este mes. Usa menos videos animados o espera al {fecha}, cuando vuelven tus 4.» |
| «Pedir otra versión» de un video | «La nueva versión usa 1 de tus 4 videos del mes. Te quedarían {v}.» |
| Un video de más de 10 s | «Este video puede durar 5 o 10 segundos. Elige uno de los dos.» |

{fecha} es el mismo día que ya usan las creaciones: el primero del mes siguiente en la zona
horaria del negocio («1 de noviembre»); si no se conoce, «el próximo mes».

### 6.3 Cómo se guarda (código)

- `pesos-creaciones-v2.json` → `videos`: `monthly_quota` 4 y `offered_seconds` [5, 10].
  `weight_for_request` / `weight_for(brief)` devuelven `CreationPrice(weight, videos)`:
  `weight` son las creaciones y `videos` los videos. El bloque `generated_video` (tokens por
  segundo × tarifas `v7`) ya no da un peso: queda como **techo en dólares por video** para el
  equipo (`generated_video_usd`).
- `creation_charges` (migración `0088`, sobre la cabeza `0086` de `main`, RLS por inquilino):
  cada cobro guarda `weight`, **`videos`**, `monthly_quota`, **`monthly_video_quota`**,
  `weights_version` (`pesos-creaciones-v2`) y `pricing_table_version` (`v7`). Sigue siendo
  idempotente por (`draft_id`, `revision`). `final_weight` desapareció.
- **Devolución de un final que falla:** el id del video que falló se agrega a
  `final_refunded_assets` (nunca dos veces el mismo, nunca más que `videos`), con
  `final_refunded_at` y `final_refund_reason`. La fila sigue en `charged` y el saldo de videos
  cuenta `videos − cardinality(final_refunded_assets)`. En un carrusel, si falla el final de
  una diapositiva, vuelve ese video; los otros se quedan cobrados.
- El cobro toma el mismo candado por marca y revisa creaciones y videos juntos: si falta
  cualquiera de los dos, no se crea nada (`NotEnoughCreations` con `missing` y
  `missing_videos`).
- El informe del equipo (`creations_report`) muestra los videos cobrados y devueltos por pieza
  y «{n} de 4 videos» por mes.

### 6.4 Lo que cuesta al equipo (techo, tabla `v7`)

| Video (vista previa 480p + final 1080p) | USD p95 por video | 4 videos al mes |
|---|---:|---:|
| 5 s, sin referencia | 3,44 | 13,77 |
| 10 s, sin referencia | 6,82 | 27,27 |
| 5 s con video de referencia de duración desconocida (se cuentan 30 s) | 14,20 | 56,81 |
| 10 s con video de referencia de duración desconocida | 16,22 | 64,89 |

Con las 30 creaciones (techo USD 4,50), **el techo por negocio y mes pasa de USD 4,50 a unos
USD 31,77 sin referencias, y a unos USD 69,39 en el peor caso** (4 videos de 10 s con
referencia de duración desconocida). Son techos (p95 y la entrada contada también en el final),
no promedios.

**Para decidir (fundador):** la red de seguridad en dólares de cada marca
(`creative_engine_config.monthly_budget_cap_usd`) **no se toca en este cambio**. Si se fija en
1,5 × 4,50 = USD 6,75, como proponía el ticket, **bloquearía los videos** que este cupo
promete: tendría que quedar por encima del techo de arriba (por ejemplo, USD 75). Y la opción B
de §5.6 (final a 720p) bajaría el costo de cada video unas 2,4 veces sin tocar el cupo.

### 6.5 Pruebas

- `packages/creative/tests/test_creations.py`: el cupo de 4 y las duraciones 5/10; un clip, un
  clip con referencia y un avatar de Seedance usan 1 video y 0 creaciones; 15 s no se ofrece;
  un carrusel usa un video por diapositiva animada; el presentador sigue en creaciones.
- `packages/api/tests/test_creations_ledger.py`: 4 videos y el quinto se rechaza sin crear
  nada; el carrusel cobra por diapositiva; el presentador sigue en creaciones sin videos
  disponibles; un final que falla devuelve 1 video, una sola vez, y su reintento no cobra.
- `packages/api/tests/test_creation_charges_db.py` (`-m db`): lo mismo contra Postgres, el
  CHECK de `final_refunded_assets` y el aislamiento por inquilino (RLS, también con
  `app.tenant_id` vacío).
- `Qualify/test_creations_of_the_month.py`: los textos de §6.2, el control del clip y del
  avatar de Seedance (5 y 10 s), Crear desactivado sin videos y ningún texto con dinero.
