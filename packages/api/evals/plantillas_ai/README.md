# Experimento — Seedream 5.0 pro: color a un objeto y textura a un logo

Ticket Meegle **m-24849234** («Pruebas: Seedream 5.0 pro para transferir colores a un objeto y
aplicar textura a un logo»). Este es el **PR 1**: la matriz, el costo y los candados de gasto.
Todavía no se llama a ningún proveedor.

## Para qué

Medir si Seedream 5.0 pro (`dola-seedream-5-0-pro-260628`) sirve para dos transformaciones que
hoy no hace el generador:

1. **Color** — una foto de un objeto más una imagen de referencia de color: el objeto toma la
   paleta de la referencia y todo lo demás queda igual (forma, material, texto impreso, luz,
   fondo).
2. **Textura** — un logo o una palabra más una imagen de textura: las letras toman ese material
   y el texto sigue siendo el mismo, legible.

Contra los dos va una **línea base determinista**: el mismo logo pintado de un color plano con
Pillow (bloque `flat`). Es gratis y es lo que la textura generada tiene que superar.

## Matriz (`cases.json`)

| Bloque | Qué | Ítems | Modelo |
|---|---|---|---|
| `color` | 10 objetos × 3 referencias de color, más 2 casos de prueba del repo | 32 | Seedream 5.0 pro |
| `texture` | 10 logos o textos × 5 texturas, más 2 casos de prueba del repo | 52 | Seedream 5.0 pro |
| `flat` | los mismos 12 logos, color plano `#C0392B` | 12 | Pillow (costo 0) |

- Las rutas son relativas a `imagenes/` (en `.gitignore`: los archivos se ponen a mano). Los
  nombres actuales describen la imagen que falta conseguir.
- Los casos con `fixture: true` apuntan a archivos que ya están en git
  (`packages/render/public/sample/photo-*.jpg`, `assets/qualify-*-email.png`), con sus propias
  referencias. Van primero, así `--limit 2` usa solo archivos reales.
- **Lista cerrada de carpetas para los fixtures** (`FIXTURE_ROOTS` en `template_transfer.py`):
  solo `assets/` y `packages/render/public/sample/`, relativas a la raíz del repositorio. Una
  ruta fuera de ellas (subidas de clientes como `uploaded_files/...`, `Qualify/...`, `.web/...`
  o cualquier otra carpeta del repositorio) es una matriz inválida: código 2 en el simulacro y
  la corrida pagada nunca llega a enviar nada. `fixture: true` solo se acepta en un caso; sus
  referencias lo heredan, y la clave se rechaza en una referencia del caso o del bloque. El
  simulacro imprime, bajo cada fila de fixture, las rutas del repositorio que lee.
- `--configs` no admite el mismo modelo dos veces (código 2 antes de planificar).
- Cada logo lleva `expected_text`: lo que la verificación de legibilidad (PR siguiente) tendrá
  que leer de vuelta.
- Solo marcas ficticias o material propio de Qualify. Ninguna foto ni logo de un cliente.

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

El simulacro arma toda la matriz, cotiza cada llamada, imprime la tabla y los totales, y lista
las imágenes que faltan sin fallar. **No hace ninguna solicitud de red**: un gancho de auditoría
de Python bloquea y cuenta cualquier conexión o consulta DNS mientras dura, y al final imprime
`Solicitudes de red: 0`. Si contara alguna, sale con código 4.

Opciones: `--limit N` (primeros N casos de cada bloque), `--block color|texture|flat`
(repetible), `--configs` (ids de modelo separados por coma; por defecto
`dola-seedream-5-0-pro-260628`; el modelo va explícito en cada solicitud), `--size` (`1K` por
defecto; `1.5K`, `2K` o `AnchoxAlto`), `--max-usd` (tope, por defecto 10), `--env-file`,
`--results-dir`, `--skip-fixtures` (deja fuera los casos y referencias `fixture: true`; sin
ellos la matriz completa son 80 llamadas pagadas, USD 3.84 a 1K: color 30 por USD 1.44,
textura 50 por USD 2.40, y 10 de color plano gratis).

La tabla muestra todos los ítems de los bloques elegidos, con su origen (`fixture` o `real`)
y si las opciones actuales lo incluyen; el costo se suma solo para los incluidos.

## Corrida pagada

**Gasta dinero real y el fundador la autoriza cada vez.** No arranca sin
`--i-have-spend-authorization`. En este PR la ruta está conectada pero no se ha ejecutado.

Antes de la primera solicitud la corrida se niega a empezar si: falta un precio en la tabla
(código 3), o con código 2 si falta una imagen de entrada, si el máximo de la corrida pasa el
tope (el simulacro lo avisa con el mismo mensaje: reduce el alcance con `--limit`, `--block`,
`--skip-fixtures` o `--size`, o ajusta `--max-usd`) o si no hay
`QUALIFY_BYTEPLUS_ARK_API_KEY`. Las imágenes salen en `imagenes/salidas/<fecha>/` y los números
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
ítem que falla (por ejemplo, un logo dañado en el bloque de color plano) queda con
`estado: "error"` y la corrida sigue con los demás. Cada corrida usa un sello único (fecha con
microsegundos, y un sufijo si ya existe), así dos corridas seguidas no se pisan.

Si el tope detiene los ítems pagados, los de color plano (gratis, no tocan el libro de gasto)
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
  2K**. La matriz completa (84 ítems pagados) estima **USD 4.032 a 1K** y **USD 7.812 a 2K**.
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

1. La corrida pagada autorizada sobre los casos de prueba (`--limit 2`) y luego la matriz completa,
   documentada en `docs/modelos-generativos/` el mismo día.
2. Trazas, conjunto de datos y cola de revisión humana en Langfuse, como `scenes_ai`.
3. La verificación de legibilidad con visión de Claude (lee el texto y lo compara con
   `expected_text`) y métricas de color (distancia de paleta en Lab, PSNR fuera del objeto).
4. `layer_decomposition` y `background: "transparent"` en el adaptador (hoy no los envía).
5. Limpieza pendiente de la revisión de código: un solo `_load_env` compartido por todos los
   experimentos (hoy hay nueve copias) y una sola función de transparencia (`has_transparency`
   repite `compose._has_transparency` con otro umbral).
6. Dónde cabe `layer_decomposition` en la matriz: la API pide exactamente una imagen de entrada
   y cada ítem pagado lleva dos, así que hoy el simulacro no puede cotizarla sobre esta matriz.
7. HEIC y otros formatos de teléfono: leer las entradas con `load_normalized` y añadir un
   `to_reference_png` en `qualify_creative/photo/normalize.py` (hoy un logo con transparencia se
   codifica aquí, en `spend_control.encode_reference`).
8. Dinero repetido en el informe: `spent_usd`, `ceiling_usd` y `reservations` arriba, `ledger`
   (la foto del libro) y `totales` dicen lo mismo de tres maneras; dejar una sola.
9. Idioma de las claves del JSON: hoy se mezclan (`estado`, `totales`, `gastado_usd` con
   `stamp`, `ledger`, `pricing_version`). Decidir uno antes de que otro experimento lo lea.
10. Eficiencia: cada imagen se decodifica dos veces (`has_transparency` y luego
    `to_reference_jpeg` o el PNG); se puede abrir una sola vez.
11. El guardián de red del simulacro es un *audit hook* de Python (`sys.addaudithook`): se
    instala una vez por proceso y no se puede quitar (fuera del simulacro no hace nada), y no
    ve código nativo que abra sockets sin pasar por el módulo `socket`.

## Dependencias abiertas

- **Langfuse local:** no está inicializado en esta máquina (`infra/langfuse/.env` no existe).
  Hay que levantarlo (`langfuse-init`, `langfuse-up`, `langfuse-setup`) antes del PR de trazas.
- **Imágenes y la regla de datos de BytePlus:** `dola-seedream-5-0-pro-260628` es un modelo
  preautorizado que cede datos a BytePlus. Solo van imágenes ficticias, de stock con licencia o
  propias de Qualify; ninguna foto ni logo de un cliente. Para usar material de clientes primero
  hace falta un endpoint personalizado (`ep-…`) no autorizado, con su propia fila de precios.
  Falta conseguir las 10 fotos de objetos, 3 referencias de color, 10 logos y 5 texturas.
- **Autorización de gasto:** el fundador autoriza cada corrida pagada y su tope (máximo
  USD 10).
