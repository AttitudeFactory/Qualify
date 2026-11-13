# Seedream 5.0 lite — transferir colores y aplicar textura (m-24849234)

| Campo | Valor |
|---|---|
| Proveedor | BytePlus ModelArk (`SeedreamImageAdapter`), llave `QUALIFY_BYTEPLUS_ARK_API_KEY` |
| Modelo | `seedream-5-0-lite-260128` · revisión que devolvió la API: `seedream-5-0-260128` |
| Precio | US$0,035 por imagen (`per_piece`), imágenes de entrada adicionales a US$0 (tabla de precios `v6`) |
| Uso en Qualify | Experimento `packages/api/evals/plantillas_ai/` (`run_experiment.py`, lógica en `qualify_api/evals/template_transfer.py`). No está en producción para estas dos tareas |
| Modelo objetivo | `dola-seedream-5-0-pro-260628` (5.0 pro). Esta prueba usó 5.0 lite porque pro no está activado en la cuenta |
| Datos | Corregido el 2026-11-12 (m-25017372): el fundador revisó la consola de ModelArk › Data Collaboration ese día y confirmó que 5.0 lite **no cede los datos** a BytePlus. Esta ficha decía antes «Modelo preautorizado: cede los datos a BytePlus», por la autorización de la campaña de datos registrada el 2026-10-07. Falta aclarar si esa autorización se revocó o si nunca se aplicó a este modelo. Las pruebas de esta ficha usaron solo material ficticio generado por `fixtures/make_fixtures.py` |

## Prueba PLANTILLAS-001 — 2026-10-23 (exploratoria)

- **Quién:** Claude Code (hilo principal), con la autorización de gasto del fundador: sonda y piloto, tope total US$0,25.
- **Ajustes:** tamaño `2K`, prompts `plantillas-ai-v1`, sin `<bbox>` ni descomposición en capas (5.0 lite no tiene ninguna de las dos), sin lector de legibilidad (`--reader none`).
- **Prompts** (`template_transfer.PROMPTS`, textuales):
  - Color: «Image 1 is a product photo. Image 2 is a color reference. Recolor the object in Image 1 with the color palette of Image 2. Keep the object's shape, material, printed text, lighting, shadows and the background of Image 1 unchanged.»
  - Textura: «Image 1 is a logo with the text "{expected_text}". Image 2 is a material texture. Apply the material of Image 2 to the letters and shapes of the logo in Image 1. Keep the exact text "{expected_text}", the letter shapes, the layout and the background of Image 1 unchanged.»
- **Material** (ficticio, en `packages/api/evals/plantillas_ai/fixtures/`):
  - Color: `objeto-disco.png` (disco azul, con máscara) con `paleta-menta-coral-cobre.png`; `objeto-rombo.png` (rombo naranja, con máscara) con `paleta-azul-arena-terracota.png`.
  - Textura: `luma-wordmark.png` («LUMA») con `textura-rayas-cobre.png`; `marca-nucleo.png` («NÚCLEO») con `textura-puntos-mostaza.png`. Los logos son PNG con transparencia.

### Corridas

| Informe (`results/`) | Modelo | Ítems (pagados / gratis) | Gastado | Resultado |
|---|---|---|---|---|
| `20261023-192110-896122.json` | 5.0 pro, 1K | 1 (1 / 0) | US$0 | `HTTP 404 ModelNotOpen`: la cuenta no tiene activado el modelo (id de solicitud `021792797677254718115c1869987166c12ff7f50db9b4e196ec6`). La reserva de US$0,048 se liberó |
| `20261023-192510-482582.json` | 5.0 lite, 2K (sonda) | 1 (1 / 0) | US$0,035 | Hecho: «LUMA» con rayas cobre |
| `20261023-192557-350988.json` | 5.0 lite, 2K (piloto, `--limit 2`) | 6 (4 / 2) | US$0,140 | 6 de 6 hechos |

**Costo:** 5 llamadas pagadas, **US$0,175** (0,035 + 0,140; el intento con pro, US$0), dentro de los US$0,25 autorizados. Cada reserva se liquidó con lo que cobró BytePlus; sin exceso sobre la reserva ni sobre el tope, nada retenido.

### Resultados por ítem (piloto)

| Ítem | Medidas |
|---|---|
| Color: disco + menta/coral/cobre | ΔE de paleta 9,03 (umbral provisional 10); PSNR del fondo antes de recomponer 24,78 dB; máscara del caso |
| Color: rombo + azul/arena/terracota | ΔE de paleta 8,59; PSNR del fondo 24,06 dB; máscara del caso |
| Textura: «LUMA» + rayas cobre | Legibilidad pendiente (sin lector) |
| Textura: «NÚCLEO» + puntos mostaza | Legibilidad pendiente (sin lector) |
| Acabado plano: «LUMA» + rayas (Pillow, gratis) | IoU 0,984; trazo mínimo 34 px; 4 / 4 piezas; aprobado |
| Acabado plano: «NÚCLEO» + puntos (Pillow, gratis) | IoU 0,989; trazo mínimo 12 px; 7 / 7 piezas; aprobado |

### Observaciones (revisión visual del fundador)

- **Textura:** la forma de las letras se conserva y no falta ninguna; la textura queda dentro de las letras, sobre fondo blanco, plana (sin volumen 3D). La tilde de la «Ú» de «NÚCLEO» salió sin textura. El proveedor aceptó el logo como PNG con transparencia.
- **Color:** la forma del objeto se conserva y el fondo se parece al original, pero el modelo copió la composición de la paleta (tres franjas verticales dentro del objeto) en lugar de transferir solo sus colores. Por eso el ΔE queda bajo el umbral aunque el resultado no es el pedido: el ΔE por sí solo no basta para este criterio.

### Limitaciones

- Es 5.0 lite, no 5.0 pro: no dice nada de pro, que sigue siendo el modelo objetivo.
- Los objetos son sintéticos; faltan las 8 fotos de productos propios del fundador.
- Sin control por región (5.0 lite no tiene `<bbox>`).
- El ejecutor no registra la latencia de cada llamada.
- La legibilidad quedó pendiente: el lector con Claude está implementado, pero no se ejecutó.
- 4 llamadas pagadas no son una medición: es una prueba exploratoria, no un conjunto de referencia.

### Próximos pasos

- Ajustar los prompts: en color, «usa los colores, no la composición»; en textura, una variante «con volumen».
- Activar 5.0 pro en la consola de Ark y repetir la sonda y el piloto con pro y con `--reader claude`.
- Conseguir las 8 fotos de productos propios y correr los casos pendientes: 24 de color (8 fotos × 3 paletas), 40 de textura y 40 de acabado plano.
- Registrar la latencia por solicitud en el informe.

## Diagnóstico de galería — borrador 97f35052 (2026-11-03, sin llamadas pagadas)

Galería de 3 diapositivas 4:5 (Nibbles, `seedream-5-0-lite-260128`, 1280×1600 y 1248×1664 para
la animada, compilador 2). Evidencia: `reflex.log` (los tres prompts), `image_assets.params`
(plan de referencias), R2 (`slide-1.jpg`, `slide-2-scene.jpg`, fondo y guía de Pixabay). No se
hizo ninguna llamada pagada: el defecto A se confirmó invirtiendo la sombra («scrim») sobre la
imagen publicada.

- **A — franja vacía abajo (diapositiva 1):** Seedream devolvió una franja blanca plana (~252 de
  gris en todo el ancho, filas 1128–1349 de 1350, 16,4 %) en respuesta a «Keep the top quarter
  and the bottom fifth of the frame calm and uncluttered». El «scrim» de `compose._scrim` la
  oscureció en un degradado gris 184→116. No viene del ajuste de tamaño (`_cover` recorta, nunca
  rellena) ni de la guía (sin bandas). La diapositiva 1 no lleva botón: la franja de abajo ni
  siquiera hacía falta.
- **B — el fondo común no se respetó:** el «Fondo común» es una foto de Pixabay (calle nocturna
  con el letrero «YOSHINOYA»), pero el prompt lo llamaba «the client's real place; preserve its
  identity as the setting»: el modelo conservó el letrero ajeno. La guía (sliders sobre tabla de
  madera) no aportó ese letrero. En la diapositiva 3 la frase del fondo era una sola cláusula
  después de la del producto y nada pedía dejar el fondo blanco de la foto de catálogo: salió
  bodegón de estudio.
- **C — diapositiva 2 sin producto:** el prompt no decía qué muestra esa diapositiva y citaba el
  pedido del dueño literal («dale clic al link de WhatsApp y pide tu delivery»); Seedream dibujó
  una tarjeta roja con el isologo y ese texto mal escrito. La 3:4 es intencional (Seedance no
  tiene 4:5); al encajar en 4:5 se recorta un 6,25 % del alto (≈3 % arriba y abajo).

**Cambios (compilador 3, solo ejecuciones nuevas; 0–2 byte a byte):** prompt de escena de galería
en frases simples (`_carousel_scene_v3`): qué muestra la diapositiva, el fondo común como
escenario sin copiar letreros, la guía solo para encuadre, el producto fiel y sin su fondo, el
pedido como contexto «no lo escribas», sin texto salvo logo y etiqueta, y «la foto llena todo el
cuadro». Además `qualify_creative.photo.bands.fill_blank_bands` recorta una franja plana con
borde duro que el proveedor deje arriba o abajo y vuelve a cubrir el cuadro. Pendiente: medir
con una galería real (no se gastó la llamada permitida).

**Ampliación (mismo día, decisión del fundador):** el fondo es un recurso genérico («fondo»): el
negocio, otro lugar, una textura o un color. Con el compilador 3, todas las rutas que envían un
fondo lo describen igual: «el fondo elegido para esta pieza», escenario o telón conservando
aspecto, colores y luz, sin copiar nombres de tiendas, letreros, logos ni textos. Las rutas son
anuncio o volante (`ad_scene_prompt`), primer cuadro de video (`first_frame_prompt`), clip
(`_clip_prompt_v2`), réplica de reel (`_reel_edit_lines_v2`) y galería. Los compiladores 0–2 no
cambian. La sombra de texto (`compose._scrim`) ya solo oscurece la franja que lleva palabras:
arriba con titular, abajo con botón o precio; la diapositiva de cierre conserva ambas.
