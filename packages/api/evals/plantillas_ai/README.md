# Experimento — Seedream 5.0 pro: color a un objeto y textura a un logo

Ticket Meegle **m-24849234** («Pruebas: Seedream 5.0 pro para transferir colores a un objeto y
aplicar textura a un logo»). El **PR 1** trajo la matriz, el costo y los candados de gasto; el
**PR 2** trae el acabado plano real y las métricas locales (máscara, trazo, paleta Lab, fondo,
legibilidad sin lector). El **PR 3, parte A** (sin costo) trae el material ficticio completo,
el lector de legibilidad con Claude bajo su propio tope y el informe de faltantes por tipo; la
sonda y el piloto pagados los corre después el hilo principal con la autorización del fundador.
El **PR 4** (preparación, sin gasto) trae la latencia por llamada, los prompts `v2`, la
comprobación de preparación, la comparación entre corridas y el procedimiento para 5.0 pro.

## Para qué

Medir si Seedream 5.0 pro (`dola-seedream-5-0-pro-260628`) sirve para dos transformaciones que
hoy no hace el generador:

1. **Color** — una foto de un objeto más una imagen de referencia de color: el objeto toma la
   paleta de la referencia y todo lo demás queda igual (forma, material, texto impreso, luz,
   fondo).
2. **Textura** — un logo o una palabra más una imagen de textura: las letras toman ese material
   y el texto sigue siendo el mismo, legible.

Contra los dos va una **línea base determinista**: el mismo logo con la misma textura en
**acabado plano**, hecho con Pillow (bloque `flat`). Es gratis y es lo que la textura generada
tiene que superar.

## Matriz (`cases.json`)

| Bloque | Qué | Ítems | Modelo |
|---|---|---|---|
| `color` | 8 fotos propias × 3 paletas, más 2 objetos sintéticos con su paleta | 26 | Seedream 5.0 pro |
| `texture` | 8 marcas ficticias × 5 texturas, más 2 marcas piloto con su textura | 42 | Seedream 5.0 pro |
| `flat` | los mismos pares marca × textura en acabado plano | 42 | Pillow (costo 0) |

- **Solo material propio de Attitude Factory o ficticio** (decisión del fundador, 2026-10-23).
  Las fotos de muestra de Remotion (`packages/render/public/sample/photo-*.jpg`) **no se usan**:
  su licencia no está documentada; ya no aparecen en `cases.json` y su carpeta salió de la lista
  de fixtures.
- **Las 8 fotos de objetos las pone el fundador:** son fotos reales de productos propios, en
  `imagenes/color/objetos/` (en `.gitignore`, no van al repositorio). El simulacro lista
  exactamente cuáles faltan, agrupadas por tipo (objetos, máscaras, referencias de color, logos,
  texturas). Hoy faltan solo esas 8; todo lo demás está en git.
- **Material sintético** en `fixtures/`, regenerable byte a byte con
  `uv run --no-sync python packages/api/evals/plantillas_ai/fixtures/make_fixtures.py` (semillas
  fijas, sin metadatos, ninguno pasa de 13 KB):
  - 10 marcas ficticias con transparencia real, en la DejaVuSans del repositorio: «LUMA»,
    «NÚCLEO», «CAFÉ RÍO», «PIÑA», «OVO», «VELMORA», «QUIRALUNA», «ZANTERIO» y dos de trazo
    fino (solo contorno): «LÍNEA» (3 px) y «ARRECIFAL» (2 px). Nombres inventados.
  - 5 texturas de 128 px hechas por código: rayas cobre, puntos mostaza, mármol con vetas,
    metal cepillado y tejido de cesta.
  - 3 paletas de tres franjas: menta/coral/cobre, azul/arena/terracota, lavanda/oliva/mostaza.
  - 2 «objetos» con su máscara exacta: un disco azul y un rombo naranja, sobre degradados.
- **Casos piloto:** van primero, así `--limit 2` usa solo archivos del repositorio: en color, el
  disco con la paleta menta/coral/cobre y el rombo con la azul/arena/terracota; en textura,
  «LUMA» con las rayas y «NÚCLEO» con los puntos. Las otras 8 marcas y las 8 fotos usan las
  referencias del bloque (5 texturas, 3 paletas).
- **«ARRECIFAL» es un caso difícil a propósito:** su contorno de 2 px queda en ~1.4 px a 1080 y el
  acabado plano no aprueba (IoU 0.887). Las otras 9 marcas aprueban.
- **Una sola carpeta permitida para los fixtures** (`FIXTURE_ROOTS` en `template_transfer.py`):
  `packages/api/evals/plantillas_ai/fixtures/`, relativa a la raíz del repositorio. Una ruta
  fuera de ella (subidas de clientes como `uploaded_files/...`, `Qualify/...`, `.web/...`,
  `assets/`, las muestras de Remotion o cualquier otra carpeta) es una matriz
  inválida: código 2 en el simulacro y la corrida pagada nunca llega a enviar nada.
  `fixture: true` solo se acepta en un caso (sus referencias lo heredan); un bloque cuyas
  referencias son fixtures lo dice una vez con `fixture_references: true`, y la clave
  `fixture` sigue rechazada en cada referencia. El simulacro imprime, bajo cada fila de
  fixture, las rutas del repositorio que lee.
- `--configs` no admite el mismo modelo dos veces (código 2 antes de planificar).
- Cada logo lleva `expected_text`: lo que la verificación de legibilidad tendrá que leer.
- Un caso de color puede llevar `mask`: la ruta de la máscara del objeto (blanco = objeto), con
  las mismas reglas que la imagen (relativa a `imagenes/`, o bajo las carpetas de fixtures si el
  caso es `fixture: true`). Un caso de textura con `mask` es una matriz inválida.
- El bloque `flat` ya no lleva `fill` (el color plano provisional del PR 1): usa las texturas
  del bloque `texture`.
- Ninguna foto ni logo de un cliente.

## Cómo se corre (simulacro, sin gasto)

Con `just`:

```bash
just eval-plantillas --dry-run
just eval-plantillas --dry-run --limit 2
```

`just` no está instalado en todas las máquinas (Windows); el comando directo es:

```bash
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --dry-run
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --dry-run --limit 2
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --dry-run --block texture --size 2K
```

El modelo objetivo sigue siendo Seedream 5.0 pro (el valor por defecto de `--configs`). Mientras
la cuenta no lo tenga activado, la variante exploratoria con 5.0 lite es:

```bash
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --dry-run --limit 2 --configs seedream-5-0-lite-260128 --size 2K
```

El simulacro arma toda la matriz, cotiza cada llamada, imprime la tabla y los totales, y lista
las imágenes que faltan sin fallar. **No hace ninguna solicitud de red**: un gancho de auditoría
de Python bloquea y cuenta cualquier conexión o consulta DNS mientras dura, y al final imprime
`Solicitudes de red: 0`. Si contara alguna, sale con código 4.

Opciones: `--limit N` (primeros N casos de cada bloque), `--block color|texture|flat`
(repetible), `--configs` (ids de modelo separados por coma; por defecto
`dola-seedream-5-0-pro-260628`; el modelo va explícito en cada solicitud), `--size` (`1K` por
defecto; `1.5K`, `2K` o `AnchoxAlto`), `--max-usd` (tope, por defecto 10), `--env-file`,
`--results-dir`, `--skip-fixtures` (deja fuera los casos `fixture: true` y sus referencias
propias; las paletas del bloque se quedan porque las fotos reales las usan: quedan las 24
llamadas de color de las fotos del fundador, USD 1.152 a 1K), y los del lector (más abajo):
`--reader`, `--max-reads`, `--max-reader-usd`. El simulacro no genera, no mide ni lee ninguna
imagen: solo cotiza. La matriz completa son 110 ítems, 68 pagados: USD 3.264 a 1K.

La tabla muestra todos los ítems de los bloques elegidos, con su origen (`fixture` o `real`)
y si las opciones actuales lo incluyen; el costo se suma solo para los incluidos.

Más opciones (PR 4): `--prompts v1|v2` (por defecto `v1`, así las corridas anteriores siguen
siendo comparables), `--texture-finish plano|volumen` (por defecto `plano`; `volumen` solo existe
con `--prompts v2`, si no la corrida sale con código 2), `--cases <archivo>` (otra matriz con las
mismas reglas, por defecto `cases.json`) y `--check-readiness`.

### Prompts versionados

`v1` (`plantillas-ai-v1`, el de las corridas registradas) no cambia ni un byte:

- Color: «Image 1 is a product photo. Image 2 is a color reference. Recolor the object in Image 1
  with the color palette of Image 2. Keep the object's shape, material, printed text, lighting,
  shadows and the background of Image 1 unchanged.»
- Textura: «Image 1 is a logo with the text "{expected_text}". Image 2 is a material texture.
  Apply the material of Image 2 to the letters and shapes of the logo in Image 1. Keep the exact
  text "{expected_text}", the letter shapes, the layout and the background of Image 1
  unchanged.»

`v2` (`plantillas-ai-v2`), escrito después de que 5.0 lite copiara las franjas de la paleta:

- Color: «Image 1 is a product photo. Image 2 is a color reference with the colors {palette}.
  Transfer the colors of Image 2 ({palette}) onto the object in Image 1 as its own material
  colors. Do NOT reproduce the layout, stripes, bands or shapes of Image 2. Keep the object's
  geometry, material, shadows, printed text and the background of Image 1 unchanged.»
  `{palette}` son los 3 colores dominantes de la referencia en `#RRGGBB`, del más frecuente al
  menos (`image_metrics.dominant_hex`, k-means con semilla fija); se guardan en el ítem como
  `paleta_hex`.
- Textura, acabado `plano`: el mismo texto de `v1`.
- Textura, acabado `volumen`: «Image 1 is a logo with the text "{expected_text}". Image 2 is a
  material texture. Render the word "{expected_text}" as 3D letters made of the material in
  Image 2, with real volume, depth and lighting. Keep the spelling "{expected_text}" and the
  letterforms of Image 1 exactly. Use a simple studio background that matches the material.»

Cada ítem guarda la versión del TEXTO que se le envió (`prompt_version`: con `--prompts v2`, la
textura `plano` sigue diciendo `plantillas-ai-v1` porque su texto es idéntico), el SHA-256 del
prompt exacto (`prompt_sha256`; vacío en el acabado plano) y, si es de textura, su
`texture_finish`. El informe guarda las opciones pedidas (`prompt_version`, `texture_finish`).

### Latencia

Cada ítem intentado guarda `latencia_s`: el tiempo de reloj desde que empieza el ítem (lectura
de las entradas, colores de la paleta y armado de la solicitud) hasta la respuesta del proveedor
(con los reintentos del propio adaptador) o el fin del acabado plano; si falla antes o durante la
llamada, hasta el fallo. Las comprobaciones posteriores no cuentan. `totales` lleva
`latencia_media_s` por bloque y en total (los ítems sin número, como los omitidos, no cuentan).
En `legibilidad`, `latencias_s` tiene **una entrada por lectura intentada** (la primera y el
reintento, también si falló o si el tope la negó), `intentos` cuenta esas entradas y
`latencia_s` las suma. El simulacro no mide nada.

### Comprobación de preparación (`--check-readiness`)

Sin ninguna solicitud de red y con el mismo planificador que el simulacro (respeta `--configs`,
`--size`, `--block`, `--limit`, `--skip-fixtures` y `--cases`), informa: los totales de esa
matriz, el precio de un ítem pagado y el comando de la sonda PNG con su cotización para cada
modelo de `--configs`, el tope de gasto aceptado, los topes del lector, si las variables
`QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY`, `QUALIFY_BYTEPLUS_ARK_API_KEY` y `QUALIFY_ANTHROPIC_API_KEY` están en el entorno, en `.env` o
ausentes (**solo el nombre, nunca el valor**; `NOMBRE=""` cuenta como ausente), las imágenes que
faltan por tipo y cuántas fotos propias faltan. Una matriz inválida o un `--cases` que no existe
sale con código 2; un modelo sin precio en la tabla, con código 3.

```bash
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --check-readiness
```

## Corrida pagada

**Gasta dinero real y el fundador la autoriza cada vez.** No arranca sin
`--i-have-spend-authorization`. Se ejecutó por primera vez el 2026-10-23, con 5.0 lite (ver
«Corridas registradas»).

Antes de la primera solicitud la corrida se niega a empezar si: falta un precio en la tabla
(código 3), o con código 2 si falta una imagen de entrada, si el máximo de la corrida pasa el
tope (el simulacro lo avisa con el mismo mensaje: reduce el alcance con `--limit`, `--block`,
`--skip-fixtures` o `--size`, o ajusta `--max-usd`) o si no hay
llave de BytePlus (usa `QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY` y, sin ella, `QUALIFY_BYTEPLUS_ARK_API_KEY`
avisándolo; se niega si coincide con `QUALIFY_BYTEPLUS_ARK_PROD_KEY_FINGERPRINT`, m-24852161).
Las imágenes salen en `imagenes/salidas/<fecha>/` y los números
con su procedencia (proveedor, id de modelo, versión de prompt, versión de precios, costo) en
`results/<fecha>.json`.

El informe separa el dinero por ítem y en total, sin recortar nada: `estimado_usd` (la
cotización), `reservado_usd` (los peores casos retenidos antes de cada solicitud, reintentos
incluidos), `gastado_usd` (lo que reportó BytePlus), `exceso_sobre_reserva_usd`,
`exceso_sobre_tope_usd` y `retenido_usd` (debe terminar en 0). Si BytePlus reporta más de lo
reservado, la corrida imprime un AVISO, marca el ítem con `exceso: true`, rechaza la reserva
siguiente si ya pasó el tope y termina con código 5.

El JSON de resultados se escribe **siempre**, también si la corrida se detiene por el tope o por
un error inesperado (queda en `error_inesperado`), así el registro del gasto nunca se pierde. Un
ítem que falla (por ejemplo, un logo dañado en el bloque de acabado plano) queda con
`estado: "error"` y la corrida sigue con los demás. Cada corrida usa un sello único (fecha con
microsegundos, y un sufijo si ya existe), así dos corridas seguidas no se pisan.

Si el tope detiene los ítems pagados, los de acabado plano (gratis, no tocan el libro de gasto)
se siguen haciendo. El JSON no guarda rutas absolutas de la máquina: las rutas van relativas al
repositorio o con la etiqueta de su carpeta (`<imagenes>`, `<results>`). Los archivos de salida
se llaman `bloque~caso~referencia~modelo`, y como `~` no puede ir en un id, dos ítems nunca
comparten nombre.

Códigos de salida (también en `--help`):

| Código | Significado |
|---|---|
| 0 | Terminó (o simulacro sin nada enviado) |
| 2 | Argumentos o matriz inválidos, faltan imágenes, falta autorización o clave, o el peor caso pasa el tope: no se envió nada |
| 3 | Falta un precio en la tabla: no se envió nada |
| 4 | El simulacro detectó un intento de red (bloqueado) |
| 5 | El tope detuvo la corrida, o el libro de gasto dio una alerta (exceso, dinero retenido) |
| 6 | Ningún ítem pagado salió bien (todos fallaron o se omitieron) |

## Procedimiento de comparación Lite vs Pro

Cada paso necesita el anterior. Los costos salen de la tabla `v6` con 2 imágenes de entrada por
ítem pagado (5.0 pro: USD 0.045 por imagen hasta 1.5K y USD 0.09 a 2K, más USD 0.003 por la
segunda imagen; 5.0 lite: USD 0.035 por imagen, sin cobro por entradas). 5.0 lite no genera a
1K: su tamaño mínimo es 2K (2560 × 1440).

| Paso | Llamadas pagadas | 5.0 pro 1K | 5.0 pro 2K | 5.0 lite 2K | Autorización |
|---|---|---|---|---|---|
| 1. Simulacro y preparación | 0 | USD 0 | USD 0 | USD 0 | Ninguna |
| 2. Sonda PNG | 1 | USD 0.048 | USD 0.093 | USD 0.035 (hecha el 2026-10-23) | 5.0 pro activado en la cuenta y gasto autorizado por el fundador |
| 3. Piloto | 4 | USD 0.192 | USD 0.372 | USD 0.140 (hecho el 2026-10-23) | Gasto autorizado por el fundador |
| 4. Muestra con fotos propias | 19 | USD 0.912 | USD 1.767 | USD 0.665 | Gasto autorizado y 3 fotos propias en `imagenes/` |
| 5. Matriz completa | 68 | USD 3.264 | USD 6.324 | USD 2.380 | Autorización explícita del fundador y las 8 fotos propias |

La muestra (paso 4) usa `cases-muestra.json`: 3 fotos propias × 3 paletas (9 de color) y 5 marcas
× 2 texturas (10 de textura, más sus 10 acabados planos gratis). Si además se comparan los
prompts (`v1` contra `v2`, o `plano` contra `volumen`), cada variante es otra corrida de 19
llamadas: dos variantes con 5.0 pro a 1K suman USD 1.824. El lector de Claude, si se usa, tiene
su propio tope (como máximo 50 lecturas y USD 0.50).

Comandos, en orden (5.0 pro es el valor por defecto de `--configs`; para 5.0 lite se agrega
`--configs seedream-5-0-lite-260128 --size 2K`):

```bash
# 1. sin gasto
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --dry-run
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --check-readiness
# 2. sonda: ¿acepta el logo PNG con transparencia?
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --block texture --limit 1 --max-usd 0.05 --i-have-spend-authorization
# 3. piloto (a 2K, --max-usd 0.40)
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --limit 2 --max-usd 0.20 --i-have-spend-authorization
# 4. muestra con fotos propias (agregar --reader claude para la legibilidad)
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --dry-run --cases packages/api/evals/plantillas_ai/cases-muestra.json
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --cases packages/api/evals/plantillas_ai/cases-muestra.json --max-usd 1.00 --i-have-spend-authorization
# 5. matriz completa, solo con autorización explícita
uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --max-usd 3.30 --i-have-spend-authorization
# comparar dos informes (solo lee los JSON)
uv run --no-sync python packages/api/evals/plantillas_ai/compare_runs.py packages/api/evals/plantillas_ai/results/20261023-192557-350988.json packages/api/evals/plantillas_ai/results/<pro>.json
```

`compare_runs.py` imprime una tabla en Markdown con una fila por ítem, es decir por (caso,
modelo) de cada corrida (un informe puede tener varios modelos), agrupada por caso: estado,
gastado, latencia, ΔE de paleta, PSNR del fondo, acabado plano y legibilidad, y una fila de
totales por corrida y modelo. Funciona también con un solo informe y no llama a nada.

Qué necesita cada criterio del ticket:

- **PNG con transparencia aceptado:** la sonda (paso 2). Verificado para 5.0 lite; falta 5.0 pro.
- **Transferir colores** (fuera de la máscara idéntico tras recomponer; dentro, colores a menos
  del umbral en 8 de 10 casos): al menos 10 casos de color con fotos reales y su máscara, y el
  umbral de ΔE acordado (hoy 10, provisional). Fuera de la máscara la igualdad es por
  construcción; se informan `psnr_fondo_db` y `borde_recompuesto_psnr_db`.
- **Acabado plano** (silueta con menos del 1 % de diferencia, textura en el 100 % del interior,
  costo cero): ya medible sin gasto con las 10 marcas ficticias (9 aprueban; «ARRECIFAL» no).
- **Textura con volumen** (Claude lee exactamente el texto; un reintento): `--prompts v2
  --texture-finish volumen` con `--reader claude`.

### Muestras pendientes: las 8 fotos propias

Van en `packages/api/evals/plantillas_ai/imagenes/color/objetos/` (en `.gitignore`, nunca al
repositorio), una por archivo, con el nombre exacto que espera `cases.json`:

| Archivo | Qué debe mostrar |
|---|---|
| `taza-ceramica-blanca.jpg` | Una taza de cerámica blanca |
| `botella-acero.jpg` | Una botella de acero |
| `zapatilla-lona.jpg` | Una zapatilla de lona |
| `camiseta-algodon.jpg` | Una camiseta de algodón |
| `bolso-cuero.jpg` | Un bolso de cuero |
| `silla-madera.jpg` | Una silla de madera |
| `termo-plastico.jpg` | Un termo de plástico |
| `gorra-tela.jpg` | Una gorra de tela |

Fotos propias de Attitude Factory (nunca de un cliente), en JPG (si es PNG, cambia la extensión
en `cases.json`), de al menos 1080 px en el lado corto, con el objeto entero y sobre un fondo
liso y simple. Las 3 primeras bastan para la muestra del paso 4. Una vez estén las fotos, 5.0 pro
activado y la autorización: `--check-readiness` debe decir «Fotos propias pendientes: 0» para la
matriz elegida, y se sigue el procedimiento desde el paso 2. Si hacen falta máscaras de los
objetos, se agregan como `mask` en cada caso (por ahora la métrica de color usa toda la imagen y
lo marca con `origen_mascara: "none"`).

## Corridas registradas

**Evaluación exploratoria de `seedream-5-0-lite-260128` a 2K, no de 5.0 pro.** El intento con
`dola-seedream-5-0-pro-260628` respondió `HTTP 404 ModelNotOpen`: la cuenta no tiene activado
el modelo (id de solicitud `021792797677254718115c1869987166c12ff7f50db9b4e196ec6`, en el
primer informe). Con 5.0 lite se usaron los mismos prompts (`plantillas-ai-v1`), sin `<bbox>` ni
capas (5.0 lite no tiene ninguna de las dos), solo con el material ficticio de `fixtures/` y sin
lecturas de Claude. El modelo devolvió la revisión `seedream-5-0-260128`.

| Informe (`results/`) | Modelo | Ítems (pagados / gratis) | Gastado | Resultado |
|---|---|---|---|---|
| `20261023-192110-896122.json` | 5.0 pro, 1K | 1 (1 / 0) | USD 0 | Error 404 `ModelNotOpen`; la reserva de USD 0.048 se liberó |
| `20261023-192510-482582.json` | 5.0 lite, 2K (sonda) | 1 (1 / 0) | USD 0.035 | Hecho: «LUMA» con rayas cobre |
| `20261023-192557-350988.json` | 5.0 lite, 2K (piloto, `--limit 2`) | 6 (4 / 2) | USD 0.140 | 6 de 6 hechos |

Gasto real total: **USD 0.175 de los USD 0.25 autorizados** (topes de USD 0.05 para el intento
con pro y la sonda, y de USD 0.20 para el piloto). En las corridas con 5.0 lite cada reserva se
liquidó con lo que cobró BytePlus (5 reservas, 5 liquidaciones); no hubo exceso sobre la reserva
ni sobre el tope, y nada quedó retenido.

**Resultados observados** (informes y revisión visual del fundador):

- **Textura:** la forma de las letras se conserva y no falta ninguna; la textura queda dentro de
  las letras, sobre fondo blanco, plana (sin volumen 3D). La tilde de la «Ú» de «NÚCLEO» salió
  sin textura. El proveedor aceptó el logo como PNG con transparencia: el criterio queda
  verificado para 5.0 lite.
- **Color:** la forma del objeto se conserva y el fondo se parece al original, pero 5.0 lite
  copió la composición de la paleta de referencia (tres franjas verticales dentro del objeto) en
  lugar de transferir solo sus colores. ΔE de paleta 9.03 (disco) y 8.59 (rombo), dentro del
  umbral provisional de 10; PSNR del fondo antes de recomponer 24.78 dB y 24.06 dB.
- **Acabado plano:** «LUMA» IoU 0.984, trazo mínimo 34 px, 4 / 4 piezas; «NÚCLEO» IoU 0.989,
  trazo mínimo 12 px, 7 / 7 piezas. Los dos aprueban.

**Limitaciones:** es 5.0 lite, no pro; los objetos son sintéticos (faltan las 8 fotos propias);
no hay control por región; el ejecutor no registraba la latencia de cada llamada (lo hace
desde el PR 4); la legibilidad
quedó «pendiente» (el lector está implementado, pero no se ejecutó).

**Casos pendientes:** 24 de color (8 fotos × 3 paletas), 40 de textura y 40 de acabado plano.
Ajustes de prompt para probar después: en color, «usa los colores, no la composición»; en
textura, una variante «con volumen».

Las imágenes generadas quedan en `imagenes/salidas/<sello>/` (en `.gitignore`) y no se publican.

Ficha del modelo con esta prueba: [`docs/modelos-generativos/seedream-5-0-lite.md`](../../../../docs/modelos-generativos/seedream-5-0-lite.md).
Borrador de la ficha de 5.0 pro (sin resultados todavía): [`docs/modelos-generativos/seedream-5-0-pro.md`](../../../../docs/modelos-generativos/seedream-5-0-pro.md).

## Métricas locales (PR 2)

Todo en `qualify_api/evals/image_metrics.py`, con Pillow y numpy (sin scipy, scikit-image ni
OpenCV), sin proveedor y sin red. Se registran en el ítem como `metricas`.

### Acabado plano (`flat_texture_fill`) — criterio «Aplicar textura en acabado plano»

1. **Silueta:** la transparencia del logo; si el logo es opaco, la mayor diferencia por canal
   contra el color de la esquina superior izquierda, como máscara suave de 8 bits (0 hasta una
   diferencia de 32, 255 desde 64).
2. **Tamaño:** 1080 px en el lado largo (se agranda o se achica), girado según su EXIF.
3. **Textura:** se escala a la altura de las letras (la caja de la silueta) manteniendo su
   proporción y se repite en mosaico desde el borde superior de las letras; así el aspecto no
   depende de la resolución de la textura.
4. **Salida:** PNG RGBA de 1080 px con fondo transparente: el color es el de la textura y la
   transparencia es la silueta (pegar la textura sobre un lienzo transparente oscurecería los
   bordes suavizados).

Comprobaciones (`aprobado` exige todas):

| Campo | Qué mide | Umbral |
|---|---|---|
| `iou_mascara` | IoU, al tamaño original del logo, entre su silueta binarizada (≥ 128) y la transparencia de la salida devuelta a ese tamaño por área y binarizada: una sola resolución y un solo remuestreo, así un logo pequeño no falla por diferencias entre filtros | ≥ 0.98 |
| `diferencia_mascara` | Fracción de píxeles en que difieren esas dos máscaras (el «menos del 1 %» del ticket) | < 0.01 |
| `componentes_antes` / `componentes_despues` | Piezas conectadas (8 vecinos) de esas dos máscaras, al mismo tamaño; no cuentan las que medirían menos de 4 px a 1080 (el umbral se escala por la razón de áreas) | iguales |
| `trazo_minimo_px` | Grosor real de la pieza más fina a 1080: erosiones de 2 × 2, que quitan un píxel de grosor cada una, hasta que desaparece (un trazo de 2 px da 2); exacto hasta 80 px | ≥ 2 px |

La textura llena toda la silueta por construcción (el color de la salida es el de la textura y
su transparencia es la silueta), así que no se mide.

`trazo_perdido` es verdadero si baja el número de piezas o el trazo mínimo queda bajo 2 px. Una
parte fina unida a una gruesa no la ve el trazo mínimo: la detectan la IoU y la diferencia de
máscara. La palabra «LUMA» aprueba en sus tres tamaños de prueba:

| Ancho original | IoU | Diferencia | Piezas | Trazo mínimo a 1080 |
|---|---|---|---|---|
| 1118 px | 0.984 | 0.34 % | 4 / 4 | 34 px |
| 400 px | 0.997 | 0.07 % | 4 / 4 | 34 px |
| 250 px | 0.995 | 0.10 % | 4 / 4 | 34 px |

### Transferencia de color (`color_transfer_metrics`) — criterio «Transferir colores»

Se calcula en la corrida pagada, después de que el proveedor devuelve la imagen; nunca en el
simulacro.

- **Máscara:** la `mask` del caso; si no hay, la transparencia de la foto del objeto; si
  tampoco, ninguna (`origen_mascara: "none"`): la paleta se calcula sobre toda la imagen y las
  medidas de fondo quedan vacías, para que el PR 3 marque el caso.
- **Paleta en Lab:** sRGB → CIE Lab (D50, perfil LAB de LittleCMS en `ImageCms`) y k-means con
  semilla fija (3 colores, k-means++). Se extrae la de la referencia (sus píxeles opacos) y la
  del resultado dentro de la máscara (≥ 128). Primero se sortean como máximo 20 000 píxeles
  (semilla fija) y solo esos pasan a Lab, así una foto de 12 MP no se copia entera en memoria.
- `delta_e_paleta`: la distancia de paleta en los dos sentidos, el mayor de
  `delta_e_resultado_a_referencia` (promedio, sobre los colores del resultado, de la distancia
  CIE76 al color más cercano de la referencia) y `delta_e_referencia_a_resultado` (lo mismo
  al revés). En un solo sentido, un resultado pintado de un solo color de la referencia daría
  casi 0. `paleta_dentro_del_umbral` si es ≤ 10 (**umbral provisional**: el ticket lo deja por
  acordar; el PR 3 lo calibra con la corrida real).
- `psnr_fondo_db`: PSNR entre original y resultado **fuera** de la máscara (== 0) **antes** de
  recomponer: cuánto se movió el modelo. `"inf"` si es idéntico.
- **Recomposición:** el resultado pegado a través de la máscara sobre el original. Fuera de la
  máscara (== 0) es idéntico al original **por construcción**, así que no se mide; la imagen
  recompuesta se guarda como `<nombre>~recompuesto.png`.
- `borde_recompuesto_psnr_db`: PSNR entre la imagen recompuesta y el original en el borde
  suave de la máscara (0 < máscara < 255), donde se mezclan los dos; vacío con una máscara dura.
- Cada registro de color y de legibilidad lleva `metricas_version` (`metricas-v1`), como el
  bloque plano lleva `prompt_version: flat-texture-v1`.
- Si el resultado tiene otro tamaño, se lleva al del original antes de medir
  (`resultado_redimensionado`). Una máscara de otro tamaño que la foto es un error de medida:
  queda en `metricas_error` y la imagen generada se conserva.

### Legibilidad — criterio «Aplicar textura con volumen»

`LegibilityReader` (un protocolo con `read_text(imagen) -> texto`), `exact_match` y un
`FakeReader` determinista para las pruebas. La comparación usa Unicode NFC, no distingue
mayúsculas y colapsa los espacios; los acentos, la «ñ» y los signos («¡», «!») sí cuentan
(«ÑAPA» leído como «NAPA» no coincide). Si la primera lectura no coincide se lee **una vez
más** (el reintento único del ticket); el registro guarda `leido`, `coincide`, `reintento` y
`lecturas`. Sin lector, cada ítem de textura queda con `estado: "pendiente"`.

**Lector con Claude** (`qualify_api/evals/legibility_claude.py`, PR 3): `--reader claude`, solo
en la corrida pagada y después de `--i-have-spend-authorization` y de todas las comprobaciones
(en el simulacro nunca se crea). Usa `claude-sonnet-5` con esfuerzo bajo, una herramienta
estricta `transcribir_texto` y la instrucción, en español, de transcribir exactamente el texto
visible sin corregirlo ni adivinarlo (`legibilidad-claude-v1`). Necesita
`QUALIFY_ANTHROPIC_API_KEY`; sin ella la corrida sale con código 2. Langfuse queda apagado
para este experimento: el proceso quita sus claves antes de la primera llamada.

**Su tope es aparte del de Seedream** (`--max-reads`, por defecto y como máximo 50;
`--max-reader-usd`, por defecto y como máximo USD 0.50). Antes de cada lectura se reserva su
peor caso y se niega la que pasaría cualquiera de los dos topes, sin enviar nada
(`ReadBudgetExceeded`; el ítem queda «sin lectura», o conserva la primera si lo negado fue el
reintento). El peor caso es acotado: la imagen se reduce a 1092 px de lado (≤ ~1600 tokens de
imagen), la entrada se cuenta como 4000 tokens al precio de escritura de caché (1.25 × USD 2
por millón) y la salida está limitada por `max_tokens = 2048` (× USD 10 por millón): USD 0.0305
por lectura. Después se liquida con el uso real; si la solicitud falla sin respuesta, con el
peor caso. El reintento cuenta como una lectura más. El informe lleva un bloque `lector`
(modelo, versión de prompt, lecturas, gastado, retenido, topes).

## Modelo de costo

Tabla de precios **v6** (`qualify_creative/pricing_data/v6.json`), elegida de forma explícita por
este experimento. Producción sigue en `PRICING_VERSION = "v5"` y con Seedream 5.0 lite por
defecto; v6 no le pone `per_piece` a 5.0 pro, así que el enrutador de producción no puede usarlo
por accidente.

Fuente: <https://docs.byteplus.com/en/docs/modelark/model-pricing> («Last updated: October 23,
2026», leída el 2026-10-23) y la API
<https://docs.byteplus.com/en/docs/modelark/image-generation-api> («Last updated: October 17,
2026»).

| Componente (unidad en v6) | 5.0 pro | 5.0 lite | 5.0 flash |
|---|---|---|---|
| Imagen hasta 2.61 MP, 1K y 1.5K (`per_image_1k`) | USD 0.045 | — | — |
| Imagen de más de 2.61 MP, 2K (`per_image_2k`) | USD 0.09 | — | — |
| Imagen, precio único (`per_piece`) | — | USD 0.035 | USD 0.018 |
| Imagen de entrada desde la segunda (`per_extra_reference_image`) | USD 0.003 (la primera es gratis) | 0 | 0 |
| Capa de `layer_decomposition`, por tramo (`per_layer_1k` / `per_layer_2k`) | USD 0.0225 / 0.045 | sin precio | sin precio |

- Solo se cobran las imágenes generadas con éxito; una moderada o fallida no se cobra. Si falla
  una capa, falla toda la solicitud.
- Cada ítem pagado de la matriz lleva 2 imágenes de entrada: **USD 0.048 a 1K** y **USD 0.093 a
  2K**. La matriz completa (68 ítems pagados) estima **USD 3.264 a 1K** y **USD 6.324 a 2K**.
- **Descomposición en capas — cotizada, pero no enviable aún por el adaptador:** el
  cotizador (`quote(..., layer_decomposition=True)`) y sus pruebas la cubren, pero el
  experimento no tiene opción para pedirla, porque `SeedreamImageAdapter` no envía
  `layer_decomposition`. La cantidad de capas solo se sabe después de la llamada. La
  estimación es (1 imagen base + `expected_layers`) × precio por capa del tramo, con
  `expected_layers = 8` por defecto (conservador). La reserva antes de la llamada usa el peor caso
  (1 + 16 capas) y el libro de gasto liquida con el `usage.generated_images` real que devuelve
  BytePlus. Se asume que la imagen base (z_index 0) también se cobra: viene dentro de `data[]` y
  el ejemplo de la documentación muestra `generated_images: 8`.
- **Sin precio no hay llamada:** si un componente que aplica no tiene fila en la tabla (por
  ejemplo, capas con 5.0 lite) el cotizador lanza `MissingPriceError` y la corrida termina antes
  de enviar nada.
- **El tope se revisa antes de cada solicitud** (`qualify_api/evals/spend_control.py`, común a
  cualquier experimento): `SpendLedger` reserva el costo máximo bajo un
  candado justo antes de que salga cada POST (`LedgerTransport` va debajo del adaptador, así que
  sus reintentos también son reservas nuevas) y rechaza la que pasaría el tope. El tope nunca
  puede ser mayor que USD 10 por corrida.

## Lo que traen los PR siguientes

Para el PR 3, parte B (la corre el hilo principal con la autorización del fundador):

- La sonda y el piloto pagados ya corrieron con 5.0 lite (ver «Corridas registradas»); falta
  repetirlos con 5.0 pro cuando se active en la cuenta, con `--reader claude`, y la ficha del
  modelo en `docs/modelos-generativos/` el mismo día.
- La latencia por solicitud ya se registra (`latencia_s`, PR 4); falta medirla en una corrida.
- Las 8 fotos de productos propios del fundador (y, si hacen falta, sus máscaras con BiRefNet
  de `photo/segment.py`) antes de pasar del piloto.
- Acordar el umbral de ΔE de la paleta (hoy 10, provisional) con los resultados.

Después:

1. Trazas, conjunto de datos y cola de revisión humana en Langfuse, como `scenes_ai`.
2. Un resultado de otra proporción que el original se mide estirado; conviene pedir el tamaño
   del original o recortar antes de medir.
3. El ticket numera las imágenes al revés que el prompt de este experimento («paleta de la
   imagen 1», el objeto en la imagen 2); revisarlo al pasarlo a producción.
4. Eficiencia del acabado plano: la silueta y las piezas del logo se recalculan para cada
   textura (se pueden guardar por logo), y `_after_generation` vuelve a leer del disco las
   entradas que el ítem ya había leído para la solicitud.
5. `layer_decomposition` y `background: "transparent"` en el adaptador (hoy no los envía).
6. Limpieza pendiente de la revisión de código: un solo `_load_env` compartido por todos los
   experimentos (hoy hay nueve copias) y una sola función de transparencia (`has_transparency`
   repite `compose._has_transparency` con otro umbral).
7. Dónde cabe `layer_decomposition` en la matriz: la API pide exactamente una imagen de entrada
   y cada ítem pagado lleva dos, así que hoy el simulacro no puede cotizarla sobre esta matriz.
8. HEIC y otros formatos de teléfono: leer las entradas con `load_normalized` y añadir un
   `to_reference_png` en `qualify_creative/photo/normalize.py` (hoy un logo con transparencia se
   codifica aquí, en `spend_control.encode_reference`).
9. Dinero repetido en el informe: `spent_usd`, `ceiling_usd` y `reservations` arriba, `ledger`
   (la foto del libro) y `totales` dicen lo mismo de tres maneras; dejar una sola.
10. Idioma de las claves del JSON: hoy se mezclan (`estado`, `totales`, `gastado_usd` con
   `stamp`, `ledger`, `pricing_version`). Decidir uno antes de que otro experimento lo lea.
11. Eficiencia: cada imagen se decodifica dos veces (`has_transparency` y luego
    `to_reference_jpeg` o el PNG); se puede abrir una sola vez.
12. El guardián de red del simulacro es un *audit hook* de Python (`sys.addaudithook`): se
    instala una vez por proceso y no se puede quitar (fuera del simulacro no hace nada), y no
    ve código nativo que abra sockets sin pasar por el módulo `socket`.
13. Limpieza pendiente de la revisión del PR 3: un ayudante común de bloques de imagen en
    `claude_tools` (hoy `legibility_claude` toma el de `font_ai`); la transparencia de una
    paleta PNG en `downscaled_png`; la redacción del aviso cuando falta un fixture; los topes del
    lector definidos en tres lugares (constantes, argumentos y `ReadBudget`); y el bucle de
    `ImageDraw.Draw` por columna al dibujar el rombo en `make_fixtures.py`.
14. Limpieza pendiente de la revisión del PR 4: más allá del analizador común de `.env`, unir
    `_env_names` y `_load_env`; el literal `FLAT_PROVIDER` y `LITE_MODEL` repetidos en
    `compare_runs.py` y en el ejecutor; un administrador de contexto para medir tiempos; y los
    `getattr` con valor por defecto sobre los argumentos.

## Dependencias abiertas

- **Langfuse local:** no está inicializado en esta máquina (`infra/langfuse/.env` no existe).
  Hay que levantarlo (`langfuse-init`, `langfuse-up`, `langfuse-setup`) antes del PR de trazas.
- **Imágenes y la regla de datos de BytePlus:** `dola-seedream-5-0-pro-260628` es un modelo
  preautorizado que cede datos a BytePlus. Solo van imágenes ficticias, de stock con licencia o
  propias de Qualify; ninguna foto ni logo de un cliente. Para usar material de clientes primero
  hace falta un endpoint personalizado (`ep-…`) no autorizado, con su propia fila de precios.
  Marcas, texturas, paletas y los 2 objetos sintéticos ya están en `fixtures/`; faltan solo
  las 8 fotos de productos propios del fundador.
- **Autorización de gasto:** el fundador autoriza cada corrida pagada y su tope (máximo
  USD 10).
