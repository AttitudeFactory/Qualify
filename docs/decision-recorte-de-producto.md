# Decisión: ¿dónde quitamos el fondo de la foto del producto?

> **Estado: [PROPUESTO]**, esperando la firma del fundador. Lo pidió Herwin el 2026-11-27.
> Historia m-25042543 («tabla de opciones del recorte»), que bloquea a m-25042551 («producto
> recortado sobre el disco»), épica m-25042540. Nada se construye ni se contrata antes de su elección.
> Lo preparó principal-architect el 2026-11-27, con el procedimiento `qualify-business-decisions`.

**Qué buscamos esta vez:** calidad. Queremos que la pieza se parezca a los volantes de referencia de
Bianki sin cambiar el producto real y sin sacar fotos del cliente de nuestra casa. El costo es
secundario porque el volumen es mínimo (ver abajo).

**Para el dueño del negocio:** su producto aparece recortado y grande sobre el color de su marca,
como en un volante hecho por un diseñador. Hoy la foto aparece entera, con su fondo, dentro de un
círculo. La hoja antes/después está solo en el disco local:
`/Users/herwin/dev/qualify-eval-out/sistema-visual/recorte/render/antes-despues.jpg`.

Etiquetas de evidencia: **[V]** medido o leído (código, producción, página oficial con fecha) ·
**[S]** fuente de terceros · **[H]** hipótesis o estimación nuestra. Una cifra calculada hereda la
etiqueta más débil de sus datos.

## 1. Lo que sabemos

**Volumen.** Lo leímos en producción con `SELECT count(*)` solo, el 2026-11-27 [V]:

- Hay 13 negocios dados de alta y 4 con productos: 28 productos en total, 15 de ellos con foto.
- Hay **20 fotos de producto en total**: 8 en octubre y 12 en noviembre, siempre de 2 negocios por
  mes. Por negocio, el reparto es 9, 4, 4 y 3. El día con más subidas tuvo 9 fotos.
- El recorte se hace **una vez por foto**, no una vez por pieza. Hoy eso son **~10 recortes al mes en
  toda la plataforma**.
- Con 100 negocios estimamos [H] ~5–10 fotos por negocio al darse de alta y ~2–3 al mes después. Eso
  da **~250 recortes al mes** en régimen, más 500–1.000 en el mes en que entran.

**Servidor.** Lo medimos en el servidor el 2026-11-27 a las 05:12 UTC, la hora más tranquila [V]:

| Dato | Valor |
|---|---|
| CPU | **2 vCPU** (`nproc`) |
| RAM | **3,8 GB** en total, **1,2 GB disponibles** |
| Swap | 2 GB, con 331 MB ya en uso |
| Carga | 0,14 |
| Topes de memoria de los contenedores (`mem_limit`) | Suman **~7,0 GB**. Ese total es una cuenta nuestra sobre `deploy/docker-compose.prod.yml` |
| Uso real de los contenedores | ~2,0 GB de Qualify y ~0,2 GB de Pedidos y otro producto |
| Reflex | 356 de 768 MB |
| render | 48 de 1.536 MB en reposo; pico medido de 327 MB por pieza (spike §7.5) |

> **Diferencia con los documentos.** La memoria del repositorio y el encargo llaman a este servidor
> «CAX21 de 4 GB». Según la lista de Hetzner, 2 vCPU y 4 GB es un **CAX11**. Un **CAX21 tiene
> 4 vCPU y 8 GB**. El nombre se comprueba en la consola de Hetzner (solo el fundador tiene acceso).
> La opción B de abajo usa la lista de precios, no el nombre.

**El recorte, según lo que ya se midió.** El detalle está en RECORTE-001 de la rama
`spike/m-25042530-sistema-visual-marca`, en §7.6 del spike y en la ficha
`isnet-general-use.md`. La medición nueva del ingeniero de plataforma está en el anexo §8.

| Modelo | Calidad en las 10 fotos reales | RAM en Linux arm64 | Licencia |
|---|---|---|---|
| `birefnet-general-lite` | La mejor | **Muere por falta de memoria aun con 6 GB** | MIT |
| `isnet-general-use` | Casi igual a la mejor; deja manchas suaves en 1 de 3 fotos de teléfono | Pico de **~1,08 GB** con una sesión de onnxruntime liviana (anexo §8), y **~1,56 GB** con la sesión por defecto de rembg, que no cabe en 1.500 MB | Código Apache-2.0; **los pesos no traen licencia propia** |
| `u2net` | Pierde una tapa y un segundo producto | 0,96 GB | Igual que IS-Net |
| Recorte por color (`chroma_key`) | **Solo sirve con fondo plano.** En foto de teléfono borra partes de las botellas | <200 MB | Nuestro |

## 2. Lo que no sabemos

| Hueco | Cómo se cierra, al menor costo | Quién |
|---|---|---|
| Pico real y tiempo en **el servidor real** (no se midió ahí) | Un proceso de una foto, con tope de 1.200 MB, a la hora más cargada, mirando `free` y la swap | platform-engineer, con el sí del fundador (es producción) |
| **Licencia de los pesos de IS-Net** | Leer `DIS5K-Dataset-Terms-of-Use.pdf`, enlazado desde `github.com/xuebinqin/DIS`. El repositorio llama a sus pesos «academic version» [V, 2026-11-27]. Si los términos dicen «solo investigación» o no son claros, pedir permiso escrito al autor. Sin permiso, el camino libre es BiRefNet (MIT), que pide un servidor más grande | principal-architect lee; el fundador decide si basta |
| Calidad con fotos de varios negocios | Conjunto de oro de ~30 fotos reales con reglas escritas antes. Pasa con ≥ 80 % | data-scientist-fde |
| Si Hetzner deja agrandar hoy un servidor Arm | La página marca los planes Arm como «currently unavailable» [V, 2026-11-27]. Hay que verlo en la consola | El fundador |
| Calidad de las API pagadas y de Seedream con estas fotos | No se probó. Sería una llamada paga o enviar fotos del cliente | Solo si se eligen C o D |

## 3. Opciones

El costo variable sale de ~10 recortes al mes hoy [V] y ~250 con 100 negocios [H]. El tipo de
cambio es €1 = US$1,15 [H]. Los precios de Hetzner van sin IVA.

| Opción | Qué es | Para el dueño | Costo hoy (13 negocios) · con 100 negocios | Memoria y operación | ¿Salen datos? | Calidad en fotos de teléfono | Riesgo de licencia | ¿Se puede deshacer? |
|---|---|---|---|---|---|---|---|---|
| **0. Dejar como está** | La foto va dentro del disco de la marca, como en SISVIS-002 | Lo ve al instante, pero queda lejos de la referencia | US$0 · US$0 | Nada | No | No hay recorte | Ninguno | Sí |
| **A. IS-Net en el servidor actual** | Un trabajo de una sola foto, con sesión liviana y tope propio de ~1.200 MB, uno a la vez en todo el servidor, de noche o en cola | Recorte a la mañana siguiente [H]. Mientras tanto ve el disco | US$0 · US$0. CPU: 250 × ~5 s ≈ 21 min al mes [V×H] | **Ajustado:** el pico de 1,08 GB [V, contenedor] contra 1,2 GB disponibles [V] deja ~140 MB y empuja a otros servicios a la swap. Es un proceso nuevo en la caja | No | Casi la mejor [V, 10 fotos] | Pesos sin licencia propia (§2) | Sí: el modelo se cambia y la máscara se recalcula |
| **B. Agrandar el servidor + IS-Net al subir la foto** | Pasar de 2 vCPU/4 GB a **CAX21 (4 vCPU/8 GB)**. El mismo trabajo de A, pero en el momento en que el dueño sube la foto | Recorte en **~35–40 s la primera vez y ~3–5 s después** [V, contenedor con 2 CPU; con 4 CPU, [H] algo menos] | **+€4,50 al mes** (€6,49 → €10,99 [V, hetzner.com/cloud/cost-optimized, 2026-11-27]) ≈ **US$5,2** [H, cambio]. Son US$0,40 por negocio hoy y US$0,05 con 100 | Holgura para el recorte y alivio para toda la caja: los topes suman 7 GB sobre 3,8 GB, ya hay swap en uso, y Reflex y render comparten. Hace falta apagar el servidor unos minutos, y Pedidos se apaga con él [H] | No | Casi la mejor [V] | Igual que A | Sí, si se cambian solo CPU y RAM sin agrandar el disco (Hetzner solo deja volver atrás en ese caso [S, documentación de Hetzner, no releída hoy]) |
| **C. API pagada** | Photoroom (US$0,02 por imagen, plan Basic de US$20 al mes por 1.000 imágenes [V, photoroom.com/api/pricing, 2026-11-27]). remove.bg sale **~US$0,20 por imagen** en pago por uso [S, comparativas]; su página no da el precio de la API y anuncia que **pasa a Leonardo.Ai desde el 2026-12-01** [V, remove.bg/api] | Recorte en 1–3 s [H] | **US$20 al mes** como mínimo práctico del plan · US$20 (250 fotos caben). Son US$1,5 por negocio hoy y US$0,20 con 100 | Nada en el servidor | **Sí.** Photoroom procesa en EE. UU., no ofrece residencia en la UE y **los planes sin contrato entrenan con las imágenes salvo que uno lo apague** (su página de seguridad se contradice en esto). El contrato de tratamiento de datos (DPA) es solo para Enterprise [V, photoroom.com/platform/security] | Buena según el proveedor; **no se probó** [S] | Ninguno: es un servicio comercial | **No del todo:** el código se quita, pero las fotos ya enviadas no vuelven |
| **D. Seedream redibuja el producto sobre fondo plano + recorte por color** | Como las figuritas: una llamada por foto | Recorte en ~10–30 s [H] | **US$0,045 por foto** (`pricing_data/v10.json`, `dola-seedream-5-0-pro-260628`) [V]. US$0,45 al mes hoy y ~US$11 con 100 negocios | Casi nada (numpy, <200 MB) [V] | Va a BytePlus, que con Seedream 5.0 pro **no** se queda con los datos (fundador, 2026-11-12) | **Puede cambiar el producto real:** la etiqueta, el teléfono impreso o cuántas botellas hay. Va contra la regla del fundador de conservar el producto real. No se probó | Ninguno | Sí en el código. Una pieza publicada con un producto inventado no se deshace |
| **E. Recortar en el teléfono del dueño** | Un modelo que corre en el navegador al subir la foto | — | — | — | No | — | **Descartada.** La librería que más se usa, `@imgly/background-removal`, es **AGPL-3.0** y pide licencia paga para uso comercial cerrado [V, github.com/imgly/background-removal-js, 2026-11-27]. RMBG-1.4/2.0 es no comercial. BiRefNet (MIT) pesa más de 200 MB, mucho para bajar en un teléfono económico con datos de Venezuela [H], y no es un rubro donde Reflex nos dé ventaja | — |

**Variante que no se agrega:** BiRefNet alojado por un tercero (fal.ai, Replicate). Tiene la mejor
calidad y licencia MIT, pero las fotos igual salen y la página no dio un precio claro [V, 2026-11-27].
Si se eligiera C, se compara ahí.

**Calculadora** (`unit_economics.py`, `--tenants 13`, con copias del archivo de parámetros del
2026-10-24): el costo fijo mensual era de US$8,00 [H, VPS sin factura leída].

| Caso | Fijo al mes | Fijo por negocio | Margen operativo típico (Básico / Plus / Pro) |
|---|---|---|---|
| Base | 8,00 | 0,62 | 74 % / 73 % / 71 % |
| + B | 13,20 | 1,02 | 73 % / 72 % / 71 % |
| + C | 28,00 | 2,15 | 72 % / 72 % / 71 % |

Ninguna opción mueve el precio ni el margen del plan. A y D cuestan menos de US$0,15 por negocio.
La decisión es de calidad, de datos y de riesgo operativo, no de plata.

## 4. Tipo de puerta

| Opción | Puerta | Por qué |
|---|---|---|
| 0, A, B | De dos vías | El modelo se cambia y la máscara se recalcula. El servidor vuelve al tamaño anterior si no se agranda el disco |
| C | **De una vía** | Las fotos del cliente ya enviadas a un tercero no se recuperan. Antes pide un ADR y el DPA |
| D | De dos vías en el código, **de una vía en cada pieza publicada** | Una pieza publicada con un producto alterado no se deshace |

### Si sale mal (pre-mortem)

1. **A tumba la caja.** Un recorte coincide con un render y con Reflex bajo carga: alguien muere por
   falta de memoria, o la swap pone lento a Pedidos.
   - Señal temprana: la swap pasa de 1 GB, o aparece un OOM en `dmesg`.
   - Qué hacemos: pausar el trabajo (la pieza vuelve al disco) o pasar a B.
2. **La licencia de IS-Net resulta ser solo para investigación.**
   - Señal: los términos de DIS5K lo dicen.
   - Qué hacemos: pedir permiso al autor. Si no lo da, la salida libre es BiRefNet MIT, que no corrió
     con 6 GB; pediría un CAX31 (16 GB, €21,49 [V]) y medirlo antes. Por eso el código guarda el
     modelo y el md5 de los pesos en cada máscara: se recalcula.
3. **El recorte falla en fotos que no vimos** (comida con vapor, varios productos).
   - Señal: el conjunto de oro baja de 80 %.
   - Qué hacemos: la regla de rechazo devuelve la foto al disco. Nunca se publica un recorte roto,
     porque la pieza sigue teniendo aprobación doble.
4. **C: un cliente pregunta dónde están sus fotos**, o Photoroom cambia sus condiciones.
   - Por eso C queda como último recurso.

**Revisión de sesgos.** La opción local es la que medimos, y eso la favorece. C y D no se probaron
para no pagar ni enviar fotos. Si el fundador quiere compararlas de verdad, alcanza con 10 fotos
nuestras (no de clientes) en Photoroom: US$0, porque las 10 primeras llamadas son gratis [V].

## 5. Recomendación

**B: agrandar el servidor a CAX21 y recortar con IS-Net (sesión liviana) al subir la foto, una a la
vez, con tope propio de ~1.500 MB.**

- Es la única opción que acerca la pieza a la referencia **sin inventar el producto y sin sacar
  fotos de casa**.
- Los €4,50 al mes también alivian una caja que hoy ya promete 7 GB sobre 3,8 GB.
- A logra lo mismo sin gasto, pero con ~140 MB de margen a la hora más tranquila, en un servidor que
  compartimos con otro producto. Es mucho riesgo para ~10 fotos al mes.

**Tiene que ser cierto que:**

1. La medición en el servidor real dé un pico ≤ 1,2 GB y menos de ~20 s por foto.
2. La licencia de los pesos quede cerrada (§2).
3. El conjunto de oro pase con ≥ 80 %.
4. Exista la regla de rechazo que vuelve al disco.
5. Hetzner deje agrandar el servidor sin cambiar de máquina.
6. El fundador acepte el proceso nuevo en el servidor.

**La reabrimos si:**

- la swap pasa de 1 GB o hay un OOM en el primer mes;
- el conjunto de oro baja de 80 %;
- pasamos de 1.000 recortes al mes;
- o BiRefNet llega a correr con menos de 2 GB.

Revisión: **2026-12-31**.

**Validación más barata:** medir una foto en el servidor actual, con tope de 1.200 MB, hoy, antes de
agrandar nada. Si cabe con holgura, A queda como piloto mientras se decide B.

## 6. Necesito que decidas

**¿Cómo hacemos el recorte del producto?**

1. **B (recomendada):** agrandamos el servidor a CAX21 (+€4,50 al mes) y recortamos con IS-Net cuando
   el dueño sube la foto, después de medir en el servidor y leer la licencia.
2. **A:** IS-Net en el servidor de hoy, de noche y una foto a la vez, sin gasto. Es un piloto con
   riesgo de memoria y el recorte llega al día siguiente.
3. **Dejar como está:** la foto dentro del disco hasta que haya más negocios con fotos. Lo reabrimos
   en la fecha de revisión.

## 7. Qué pasa después de la firma

- Esta página pasa a **[FIRMADO]**, con la sección «Decisión del fundador (AAAA-MM-DD)» al inicio.
- Fila en el ADR log (`docs/arquitectura.md` §6): un proceso nuevo en el servidor y, si fuera B, el
  tamaño nuevo.
- Historias por product-owner. El cambio de `SEGMENTATION_MODEL` y del docstring de
  `LocalBiRefNetSegmenter` lo hace creative-engineer. platform-engineer hace el tope y el cambio de
  tamaño del servidor (`qualify-prod-ops`: cambiar el tamaño pide el sí del fundador).

## 8. Anexo a RECORTE-001 (2026-11-27, platform-engineer)

`docs/modelos-generativos/pruebas.md` en `main` **no tiene** la entrada RECORTE-001: vive solo en la
rama `spike/m-25042530-sistema-visual-marca`. Por eso este anexo va aquí. Cuando esa rama llegue a
`main`, se pasa debajo de RECORTE-001 y se corrige la ficha `isnet-general-use.md`, que dice
«~1,3 GB», «2 CPU» y «Docker Desktop».

| | Valor |
|---|---|
| **Entorno** | Contenedor Linux **arm64** (la arquitectura de producción). **No** es el servidor real |
| `isnet-general-use`, sesión por defecto de rembg | **No cabe en un tope de 1.500 MB:** muere por falta de memoria en la segunda foto. Pico real ~**1,56 GB** |
| `isnet-general-use`, sesión liviana de onnxruntime (sin la reserva de memoria de la CPU, sin la memoria reservada por adelantado, hilos = CPU) | Pico ~**1,08 GB** |
| Tiempo por foto | **4,6–5,5 s** con 1 CPU; **2,5–3,5 s** con 2 CPU |
| Primera solicitud | **30–35 s** (carga de las librerías) |
| `birefnet-general-lite` | Pide 2,4–4,7 GB y muere por falta de memoria en Linux aun con 6 GB |
| Pendiente | Medir en el servidor real |

**Consecuencia:** el trabajo de recorte tiene que crear su propia sesión liviana. Con la sesión por
defecto de `rembg`, IS-Net no cabe en ningún tope razonable.
