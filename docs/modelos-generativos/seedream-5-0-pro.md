# Seedream 5.0 pro — transferir colores y aplicar textura (m-24849234) · BORRADOR

> **Borrador de preparación (PR 4).** Solo hay datos verificables de la documentación del
> proveedor y del plan de la prueba. Ningún resultado de 5.0 pro existe todavía: cada campo de
> resultado dice **PENDIENTE: requiere activación de Pro y autorización de gasto**.

| Campo | Valor |
|---|---|
| Proveedor | BytePlus ModelArk (`SeedreamImageAdapter`), llave `QUALIFY_BYTEPLUS_ARK_API_KEY`, endpoint `https://ark.ap-southeast.bytepluses.com/api/v3/images/generations` |
| Modelo | `dola-seedream-5-0-pro-260628` · revisión que devuelve la API: PENDIENTE: requiere activación de Pro y autorización de gasto |
| Precio (tabla `v6`, docs.byteplus.com/en/docs/modelark/model-pricing, «Last updated: October 23, 2026», verificado el 2026-10-23) | Imagen hasta 2.61 MP (1K y 1.5K): US$0,045 (`per_image_1k`) · más de 2.61 MP (2K): US$0,09 (`per_image_2k`) · imágenes de entrada: la primera gratis, desde la segunda US$0,003 cada una (`per_extra_reference_image`) · descomposición en capas: US$0,0225 / US$0,045 por capa según su tramo (`per_layer_1k` / `per_layer_2k`). Solo se cobran las imágenes generadas con éxito |
| Uso en Qualify | Experimento `packages/api/evals/plantillas_ai/`. No está en producción: `v6` no le pone `per_piece`, así que el enrutador de producción no puede elegirlo por accidente |
| Datos | Modelo preautorizado: cede los datos a BytePlus (por eso solo material ficticio o propio de Attitude Factory; ningún dato de un cliente). Cláusula de BytePlus (docs.byteplus.com/en/docs/ModelArk/BytePlus_ModelArk_Data_Processing, actualizada el 2026-09-10): sin autorización previa del cliente no usa sus datos para entrenar sus modelos; procesa en Malasia, Indonesia y/o UE/EEE, y guarda 180 días en Malasia lo que dispara el filtro de contenido |

## Capacidades verificadas (API, docs.byteplus.com/en/docs/modelark/image-generation-api, «Last updated: October 17, 2026»)

- **Tamaños:** `1K`, `1.5K` o `2K` (por defecto `2K`), o `AnchoxAlto` entre 921 600 y 4 624 220
  píxeles, proporción entre 1/16 y 16. 1.5K cuesta lo mismo que 1K.
- **Imágenes de referencia:** hasta 10. Formatos jpeg, png, webp, bmp, tiff, gif, heic o heif,
  hasta 30 MB cada una, como `data:image/<formato>;base64,…` o URL.
- **Transparencia:** acepta PNG con canal alfa. `background: "transparent"` (salida PNG) solo en
  imagen a imagen con exactamente una entrada con alfa; con `output_format: jpeg` o una entrada
  sin alfa la solicitud da error. **El adaptador de Qualify todavía no envía `background`.**
- **Control por región:** sin parámetro de máscara; etiquetas normalizadas `<point>x y</point>` y
  `<bbox>x1 y1 x2 y2</bbox>` (0–999) dentro del prompt, para marcar qué cambiar y qué conservar.
- **`layer_decomposition`:** con exactamente una imagen de entrada devuelve una imagen base y
  hasta 16 capas PNG con alfa; si falla una capa, falla la solicitud entera. **El adaptador
  todavía no la envía**; el cotizador sí la cubre.
- **Texto:** genera texto en español, entre otros idiomas; la guía del proveedor pide el texto
  entre comillas dobles.

## Intento PLANTILLAS-000 — 2026-10-23

- Sonda de 1 ítem de textura a 1K con tope de US$0,05: **`HTTP 404 ModelNotOpen`**, la cuenta no
  tiene activado el modelo (id de solicitud `021792797677254718115c1869987166c12ff7f50db9b4e196ec6`,
  en `packages/api/evals/plantillas_ai/results/20261023-192110-896122.json`). Gasto US$0; la
  reserva de US$0,048 se liberó. Por eso la prueba exploratoria se hizo con 5.0 lite (ver
  [seedream-5-0-lite.md](seedream-5-0-lite.md)).

## Prueba planificada PLANTILLAS-002

- **Prompts:** `plantillas-ai-v1` (los mismos de la prueba con 5.0 lite, para comparar) y
  `plantillas-ai-v2` (color que nombra los colores en `#RRGGBB` y prohíbe copiar la composición
  de la referencia; textura `plano` o `volumen`). Texto exacto de los dos en el README del
  experimento, sección «Prompts versionados».
- **Matriz:** `cases.json`, 110 ítems (68 pagados, US$3,264 a 1K): color 2 objetos sintéticos con
  su paleta + 8 fotos propias × 3 paletas; textura 2 marcas piloto con su textura + 8 marcas
  ficticias × 5 texturas; los mismos pares en acabado plano (gratis). Muestra intermedia:
  `cases-muestra.json`, 19 llamadas pagadas (US$0,912 a 1K).
- **Pasos y costos:** sonda US$0,048 → piloto US$0,192 → muestra US$0,912 → matriz completa
  US$3,264 (todo a 1K; a 2K: US$0,093 / 0,372 / 1,767 / 6,324). Procedimiento y autorizaciones
  en el README, sección «Procedimiento de comparación Lite vs Pro».
- **Lector de legibilidad:** `claude-sonnet-5` con su propio tope (máximo 50 lecturas y US$0,50).

### Resultados

| Medida | Valor |
|---|---|
| Revisión del modelo | PENDIENTE: requiere activación de Pro y autorización de gasto |
| PNG con transparencia aceptado | PENDIENTE: requiere activación de Pro y autorización de gasto |
| Gasto real y llamadas | PENDIENTE: requiere activación de Pro y autorización de gasto |
| Latencia por llamada (`latencia_s`) | PENDIENTE: requiere activación de Pro y autorización de gasto |
| Color: ΔE de paleta y PSNR del fondo | PENDIENTE: requiere activación de Pro y autorización de gasto |
| Color: ¿copia la composición de la referencia? | PENDIENTE: requiere activación de Pro y autorización de gasto |
| Textura: legibilidad (Claude) y forma de las letras | PENDIENTE: requiere activación de Pro y autorización de gasto |
| Textura con volumen | PENDIENTE: requiere activación de Pro y autorización de gasto |
| Comparación con 5.0 lite (`compare_runs.py`) | PENDIENTE: requiere activación de Pro y autorización de gasto |

### Requisitos antes de correrla

- Activar `dola-seedream-5-0-pro-260628` en la consola de Ark (cuenta del fundador).
- Autorización de gasto del fundador para cada paso.
- Las 8 fotos de productos propios (3 bastan para la muestra).
- `--check-readiness` sin pendientes para la matriz elegida.
