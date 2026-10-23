# Creaciones del mes — pesos y cupo medidos (CREAR-5, m-24848531)

Épica: UX m-24842956 · Historia: `CREAR-5` en `docs/epica-ux-navegacion-experiencia.md`.
Autor: data scientist / FDE · Fecha: 2026-10-23 · Pesos: **`pesos-creaciones-v1`** sobre la
tabla de precios **`v5`** (`packages/creative/src/qualify_creative/pricing_data/v5.json`).

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
