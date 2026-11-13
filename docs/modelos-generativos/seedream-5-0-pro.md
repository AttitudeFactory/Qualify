# Seedream 5.0 pro — transferir colores y aplicar textura (m-24849234) · BORRADOR

## Verificación acotada — 2026-11-10

Una generación directa de imagen sintética a 1K con la llave local
`QUALIFY_BYTEPLUS_ARK_API_KEY` terminó correctamente. La API devolvió el identificador
`dola-seedream-5-0-pro-260628`. Esto demuestra acceso local a la generación con Pro;
no verifica el acceso en producción ni la calidad para casos de clientes. No se hizo una
comparación de calidad con Lite ni se desplegó el cambio.
El prompt exacto fue `A plain blue ceramic mug on a white background, no text, no logo`.
No se capturaron la duración ni el cargo real de esa llamada; la tarifa publicada para
una salida 1K sin referencias adicionales es US$0,045.

Para m-24993446 se preparó la tabla inmutable `v8` y Pro pasa a ser el modelo
predeterminado cuando `QUALIFY_SEEDREAM_MODEL` está vacío. La variable permite
sobrescribirlo. La evaluación PLANTILLAS-002 y sus métricas siguen pendientes.

El precio oficial consultado el 2026-11-10 mantiene US$0,045 y US$0,09 por imagen y
US$0,003 desde la segunda referencia. Las páginas oficiales consultadas discrepan
en el corte entre tramos: una indica 2,36 MP y otra 2,61 MP. La cotización de `v8`
usa 2,36 MP para evitar una reserva insuficiente.
Fuentes: [página inglesa indexada](https://docs.byteplus.com/docs/ModelArk/1099320)
y [página japonesa actualizada](https://docs.byteplus.com/ja/docs/modelark/model-pricing).

| Campo | Valor |
|---|---|
| Proveedor | BytePlus ModelArk (`SeedreamImageAdapter`), llave `QUALIFY_BYTEPLUS_ARK_API_KEY`, endpoint `https://ark.ap-southeast.bytepluses.com/api/v3/images/generations` |
| Modelo | `dola-seedream-5-0-pro-260628` · devuelto por la API en generación sintética local del 2026-11-10 |
| Precio (tabla `v6`, docs.byteplus.com/en/docs/modelark/model-pricing, «Last updated: October 23, 2026», verificado el 2026-10-23) | Imagen hasta 2.61 MP (1K y 1.5K): US$0,045 (`per_image_1k`) · más de 2.61 MP (2K): US$0,09 (`per_image_2k`) · imágenes de entrada: la primera gratis, desde la segunda US$0,003 cada una (`per_extra_reference_image`) · descomposición en capas: US$0,0225 / US$0,045 por capa según su tramo (`per_layer_1k` / `per_layer_2k`). Solo se cobran las imágenes generadas con éxito |
| Uso en Qualify | Experimento `packages/api/evals/plantillas_ai/` pendiente. Producción aún no verificada; el código preparado para m-24993446 usa `v8` y Pro por defecto cuando `QUALIFY_SEEDREAM_MODEL` está vacío. |
| Datos | **No cede los datos a BytePlus** (corregido el 2026-11-12, m-25017372): el fundador revisó la consola de ModelArk › Data Collaboration el 2026-11-12 y confirmó que ni Seedream 5.0 pro ni 5.0 lite están autorizados para compartir datos. Esta ficha decía antes «Modelo preautorizado: cede los datos a BytePlus»; esa fila venía copiada de la de 5.0 lite y no la respaldaba ninguna revisión de la consola. Con esa confirmación, las fotos del catálogo de un cliente pueden ir a Pro por el identificador del modelo (`dola-seedream-5-0-pro-260628`). Si alguien autoriza Pro en la campaña de datos, esta fila y el envío de fotos de clientes cambian ese mismo día. Cláusula de BytePlus (docs.byteplus.com/en/docs/ModelArk/BytePlus_ModelArk_Data_Processing, actualizada el 2026-09-10): sin autorización previa del cliente no usa sus datos para entrenar sus modelos; procesa en Malasia, Indonesia y/o UE/EEE, y guarda 180 días en Malasia lo que dispara el filtro de contenido |

## Prueba STICKERS-KAWAII-001 — 2026-11-12 (m-25017372)

Personaje tierno de un producto del catálogo para un sticker de WhatsApp. Imagen a imagen con
una sola foto de Bianki como referencia, a 1K, por el identificador del modelo. Detalle completo en
[pruebas.md](pruebas.md#stickers-kawaii-001).

| Medida | Valor |
|---|---|
| Llamadas pagadas | 7 (6 generaciones + 1 `layer_decomposition`), ningún reintento, cada POST bajo `LedgerTransport` con la tabla `v8` |
| Gasto real | US$0,315 (6 × US$0,045 + capas: 2 imágenes facturadas × US$0,0225). Tope autorizado: US$0,50 |
| Latencia por imagen | 26,7–42,4 s (mediana 28,7 s); capas 28,9 s |
| Revisión del modelo | `dola-seedream-5-0-pro-260628` |
| Fondo plano pedido `#FF00FF` | Sale magenta rosado uniforme, RGB (239–248, 24–37, 157–195), nunca el valor exacto: el recorte debe medir el color del borde, no suponerlo |
| Producto reconocible | 6 de 6 (shawarma de carne, de pollo, papas, salchipapa) |
| Texto en la imagen | 0 de 6 (el prompt lo prohíbe; el mensaje lo pone Remotion) |
| `layer_decomposition` | Devuelve un PNG con transparencia del personaje (690×729) más la base. La capa **se vuelve a dibujar**: no coincide píxel a píxel con la entrada (su caja es 622×660) y cambia detalles menores. Facturó 2 imágenes (US$0,045) con un prompt que pide una sola capa; sin prompt pueden ser hasta 17 (US$0,3825 en el peor caso) |

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

- Confirmar acceso y configuración del modelo en el entorno donde se ejecute la prueba. La generación local sintética del 2026-11-10 funcionó.
- Autorización de gasto del fundador para cada paso.
- Las 8 fotos de productos propios (3 bastan para la muestra).
- `--check-readiness` sin pendientes para la matriz elegida.
