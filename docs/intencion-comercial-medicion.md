# Intención comercial de los comentarios — golden set y medición

`[MEDIDO 2026-10-20 · m-24789644 (Interacciones · Fase A) · PR 3b]`

Este documento explica cómo se eligió el clasificador de intención comercial y qué clases se pueden mostrar como fiables. El contrato (`IntentSignal`), la tabla y el clasificador están en `packages/api/src/qualify_api/intent/`.

## Resultado

- **Modelo elegido: Claude Haiku 5.5** (`claude-haiku-5-5`, effort `low`) con el prompt `intent-claude-v2`.
- **Clases fiables** (precisión ≥ 0,80, recall ≥ 0,70 y al menos 8 ejemplos, medidas solo en la mitad de prueba): `general`, `price`, `availability` y `location`. Las demás se muestran como «no fiable» en la interfaz, sin bloquear las fiables.
- **Detectar si hay intención comercial** (el indicador que consume QUA-229): precisión 0,96, recall 0,98.
- **Costo:** unos 0,004 USD por cada 200 comentarios (0,02 USD por cada 1.000).
- **Descartado: `MoritzLaurer/bge-m3-zeroshot-v2.0`**, porque es peor en todas las clases y la imagen de producción no lleva torch.

## El golden set

Archivo: `packages/api/eval_data/intent_golden_v1.jsonl`, con 408 comentarios.

- **De dónde salen:** son comentarios públicos de publicaciones de Instagram de negocios hispanohablantes (tiendas de ropa, tecnología, panaderías, mayoristas, cosmética…). Se recogieron con Scrape Creators el 2026-10-20: búsquedas de reels más páginas de comentarios, 63 créditos en total.
- **Privacidad:** solo se guarda el texto. No hay nombres de usuario ni enlaces a perfiles; las menciones aparecen como `@usuario`. Un test (`test_intent_golden_file.py`) lo vigila.
- **Etiquetas:** Claude las propuso, Raul Rangel las revisó y las aceptó sin cambios. Después se aplicaron las cinco reglas de etiquetado de la sección siguiente, que cambiaron 7 filas (marcadas con la nota `R1`…`R4`).
- **División:** las filas se reparten en `dev` (203) y `test` (205), estratificadas por la etiqueta más rara de cada comentario (semilla 24789644). Con `dev` se ajusta el prompt; `test` solo se puntúa. La CLI no permite escribir el informe de fiabilidad con otra división.

| Clase | dev | test |
|---|---|---|
| general | 93 | 94 |
| price | 54 | 52 |
| availability | 17 | 16 |
| location | 15 | 16 |
| store | 11 | 12 |
| other_commercial | 10 | 10 |
| variants | 8 | 9 |
| product | 8 | 7 |
| quantities | 7 | 7 |
| models | 3 | 3 |
| hours | 3 | 3 |

`models` y `hours` tienen pocos ejemplos. `product` y `quantities` no llegan a 8 en test, así que **no pueden salir fiables aunque acierten todo**. Para medirlas hacen falta más comentarios de restaurantes, mayoristas y tiendas de tecnología o música.

## Las cinco reglas de etiquetado (2026-10-20)

1. Un deseo sin pregunta («quiero», «lo quiero», «necesito», «eu quero») es `general`.
2. «Información», «info» o pedir el catálogo es `product`.
3. Pedir un contacto (WhatsApp, número, «revisa tu DM») es `store`.
4. Las quejas, las reseñas y los textos del propio negocio son `general`, aunque mencionen envíos o precios.
5. Elogiar un producto («belleza», «hermoso») es `general`.

El prompt v2 recoge estas reglas y cuatro más, que salieron de los errores en `dev`:

- Describir qué producto se quiere no es `variants`.
- Nombrar un producto concreto o su código no es `models`.
- «¿Dónde lo consigo en X?» es `store`, no `location`.
- Etiquetar a otras personas o publicar información sin preguntar nada es `general`.

## Medición

| | Haiku 5.5 · prompt v1 (todo el set, antes de las reglas) | Haiku 5.5 · prompt v2 · **test** | bge-m3 zero-shot int8 · **test** |
|---|---|---|---|
| Coincidencia exacta | 0,78 | **0,87** | 0,61 |
| Intención comercial (P / R) | 0,86 / 0,995 | **0,96 / 0,98** | 0,89 / 0,71 |
| Clases fiables | general, price, availability, location | **general, price, availability, location** | price |

Precisión y recall por clase en `test`:

| Clase | ejemplos | bge P | bge R | Haiku P | Haiku R |
|---|---|---|---|---|---|
| general | 94 | 0,72 | 0,89 | 0,98 | 0,95 |
| price | 52 | 0,83 | 0,87 | 1,00 | 0,98 |
| availability | 16 | 0,50 | 0,50 | 0,82 | 0,88 |
| location | 16 | 0,67 | 0,50 | 1,00 | 0,88 |
| store | 12 | 0,50 | 0,25 | 0,73 | 0,92 |
| other_commercial | 10 | 0,50 | 0,50 | 0,77 | 1,00 |
| variants | 9 | 1,00 | 0,11 | 0,78 | 0,78 |
| product | 7 | 0,14 | 0,71 | 0,44 | 1,00 |
| quantities | 7 | 0,45 | 0,71 | 0,75 | 0,86 |
| models | 3 | 0,17 | 0,33 | 0,25 | 0,33 |
| hours | 3 | — | 0,00 | 0,75 | 1,00 |

El informe que lee la aplicación es `packages/api/src/qualify_api/intent/data/reliability/intent-claude-v2.json`. Viene de una segunda pasada sobre `test` (coincidencia exacta 0,868) y da las mismas cuatro clases fiables.

**Ajuste del prompt (solo en `dev`):** v1 → 0,78; v2 con las cinco reglas → 0,86; v2 con las cuatro reglas adicionales → 0,88. En `test` el prompt congelado da 0,86–0,87, así que el ajuste apenas sobreajustó.

**Cómo se midió bge-m3:**

- Clasificación zero-shot multietiqueta, con una hipótesis en español por clase comercial («Este comentario pregunta el precio.», etc.). `general` es lo que queda cuando ninguna clase supera su umbral.
- El umbral de cada clase se eligió en `dev` maximizando F1 y se aplicó tal cual a `test`.
- Se usó cuantización int8 dinámica en CPU (1,4 s por comentario; sin cuantizar, 14 s).
- Los umbrales salieron casi todos entre 0,10 y 0,35: el modelo apenas separa las clases.

## Cómo repetirlo

```bash
uv run --no-sync python -m qualify_api.intent.eval --golden packages/api/eval_data/intent_golden_v1.jsonl --split dev
```

- Con `--split test --write-reliability` se escribe el informe que lee la aplicación. Solo se permite con `test`.
- Con `--predictions archivo.jsonl` se guarda cada comentario con sus clases real y predicha.
- Con `--from-predictions archivo.jsonl --model-id … --detector-version …` se puntúan las predicciones de otro modelo sin llamar a Claude.

Necesita `QUALIFY_ANTHROPIC_API_KEY`. Si el SDK la toma de `ANTHROPIC_BASE_URL` o `ANTHROPIC_AUTH_TOKEN` del entorno, esas variables se imponen sobre la clave explícita; hay que quitarlas antes de medir.

## Cómo lo usa la pantalla de Interacciones

- **Análisis automático (m-24852204, decisión del fundador 2026-10-24).** Ya no hay botón: tras cada búsqueda de comentarios nuevos, Interacciones lanza en segundo plano una pasada acotada (sentimiento → intención con la versión vigente `intent-claude-v2` → consultas «Quieren comprar»), como mucho 100 comentarios por cuenta y por análisis, los más nuevos primero (`qualify_api.comment_analysis`). El `webhook-worker` repite la misma pasada cada 10 min para lo pendiente (atrasos, fallos, cortes del modelo). Un candado por cuenta (advisory lock de Postgres) evita dos pasadas a la vez. Sin `QUALIFY_ANTHROPIC_API_KEY`, o sin el modelo local de sentimiento, esa mitad se salta con un aviso en el log y el cliente no ve ningún error. Si el modelo no responde algo usable para un comentario, ese comentario queda pendiente y se reintenta en la siguiente pasada.
- **Cada comentario muestra sus clases**, de mayor a menor confianza. Una clase que el informe de `test` no respalda (por debajo de los umbrales o con menos de 8 ejemplos) se muestra igual, pero en ámbar y con «no fiable». No se oculta, porque es la mejor pista que hay; se marca para que se revise antes de actuar.
- **El filtro «Requiere atención comercial»** deja solo los comentarios con intención comercial bajo la versión vigente. Se combina con el filtro de sentimiento, la búsqueda y la paginación, porque es la misma consulta con una condición más.
