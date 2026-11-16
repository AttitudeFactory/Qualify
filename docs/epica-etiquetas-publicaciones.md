# Épica — Etiquetas (hashtags) que se están viendo

`[FIRMADO 2026-11-13]` · Épica en Meegle: **m-25026375** «Épica — Etiquetas que se están
viendo», con cuatro tickets (§4). En la app el dueño lee «etiquetas» (m-24849133); aquí «etiqueta»
y «hashtag» son lo mismo.

## Decisión del fundador (2026-11-13)

**D1 — Opción C: ajustar a cinco y elegir mejor, más una lectura semanal en TikTok.** Herwin la
eligió en chat el 2026-11-13 `[F]`. La recomendación del análisis era la opción B (lo mismo sin la
lectura en TikTok); C la incluye entera y suma la lectura. Manda esta decisión sobre el análisis.

- **Por qué:** con cinco etiquetas por publicación importa cuáles son; la lectura semanal trae las
  que acompañan hoy a los videos más vistos del rubro.
- **Costo:** unos 22 créditos de ScrapeCreators por negocio al mes ≈ USD 0,04 (calculado: 5
  etiquetas × 1 lectura × 4,3 semanas × USD 0,00188), el 4 % del tope de 600 créditos (ADR 42).
- **Riesgo que se asume:** que una etiqueta fuerte en TikTok no sirva en Instagram, que es donde
  publican los clientes `[H]`. Se mide en la entrega 4.
- **Descartado:** dejar como está (A); etiquetas de las tendencias generales (D), porque lo medido
  no tiene relación con ningún rubro.
- **Se reabre si** al 2026-12-15 la prueba con un negocio no muestra más alcance con las etiquetas
  de TikTok, o si la lectura semanal pasa de 60 créditos al mes por negocio.
- **Puerta de dos vías:** todo se apaga con un interruptor; no sale ningún dato de clientes.

**D2 —** Los negocios ya guardados conservan el máximo de 10 etiquetas; no se migra a 5. El máximo de 5 aplica a los
negocios que se guarden desde el PR #642. Mientras no exista una pantalla para elegirlo, cambiar
un negocio actual es un cambio a mano en su política. Decidido por Herwin en chat el 2026-11-13
`[F]`.

**D3 —** (2026-11-14) La lectura semanal corre dentro del proceso de reels, que la revisa
varias veces al día (cada negocio se sigue leyendo como mucho una vez por semana), solo para un
negocio piloto (Bianki) durante cuatro semanas. Descartado: un proceso nuevo (más
memoria en un servidor justo), una tarea programada en el servidor (fuera de los caminos de
despliegue) y dejarla apagada. Costo máximo: 25 créditos al mes. Se reabre si al 2026-12-15 la
entrega 4 no muestra más alcance o si la pasada retrasa las lecturas de reels. Qué negocios
cuentan como activos se decide cuando se abra a todos.

**D3, reintentos (2026-11-15, aprobado por Herwin, m-25031643).** El 2026-11-15 el piloto hizo
tres llamadas: una falló a las 04:59 UTC, una respondió bien a las 17:15:14 y la siguiente
respondió 503 a las 17:15:34. Con la regla anterior cada fallo gastó uno de los 5 créditos de la
semana y congeló al negocio 24 horas, aunque el proveedor no cobra los 503 (el 2026-11-14, 7 de
14 lecturas a mano respondieron 503 y no se cobraron). Regla nueva
(`qualify_api.hashtags.weekly`):

- Solo es «no cobrado» lo que se midió como no cobrado o lo que nunca salió: la respuesta HTTP
  503 (medida el 2026-11-14: 7 de 14 lecturas respondieron 503 y ninguna se cobró; el
  2026-11-15 volvió a aparecer en producción —2 de 3 llamadas fallaron, una con 503
  confirmado—, lo que dice cuán seguido pasa, no si se cobra) y una llamada que no llegó a enviarse (no se pudo
  conectar o no hubo conexión libre). Esa llamada no cuenta para las 5 lecturas de la semana y
  no congela el día. El negocio se vuelve a intentar en la siguiente revisión, con dos frenos
  para que los reinicios por despliegue no insistan: al menos 3 horas después del último fallo
  no cobrado (`MIN_RETRY_WAIT`; la revisión de cada 6 horas siempre entra) y como mucho 4 fallos
  no cobrados por negocio en 24 horas móviles (`MAX_UNBILLED_A_DAY`). La lista de respuestas no
  cobradas (`UNBILLED_STATUSES`) solo crece con una prueba medida y documentada del proveedor.
- Todo lo demás cuenta como lectura cobrada y espera un día, como antes, porque el proveedor
  pudo haberla cobrado: los demás 5xx (500, 502, 504, 520 a 524), un tiempo de espera agotado
  o un error después de enviar la llamada, 401/402/429 y los demás 4xx (el 404 sigue siendo una
  respuesta guardada), una respuesta sin éxito y una respuesta pagada que no se pudo guardar.
  Los bloqueos y topes del control de gasto no reservan nada. Una pasada sigue deteniéndose en
  su primer fallo.
- Cómo se distingue sin migración y sin tocar el control de gasto: el control sigue reservando 1
  crédito antes de cada llamada; después, este módulo añade una fila de 0 créditos con la misma
  clave y el sufijo `:kept` (respuesta guardada) o `:unbilled` (fallo no cobrado). Una llamada
  sin esa fila —incluidas las tres del 2026-11-15, anteriores a la regla— se trata como antes:
  cuenta como cobrada y congela el día. Los topes diarios y mensuales del negocio siguen
  contando cada llamada reservada, también las no cobradas.
- El tope semanal de lo cobrado: 5 lecturas por negocio en cualquier periodo de 7 días, sumadas
  sobre el registro y no sobre las etiquetas actuales, así que cambiar las etiquetas a mitad de
  semana no compra más. Se sostiene mientras el proveedor no cobre los 503 (el 2026-11-14, 7 de
  14 lecturas respondieron 503 y ninguna se cobró); cualquier otro fallo ya se cuenta como
  cobrado.

**Peor caso por negocio y semana:** cobrado por el proveedor, 5 créditos (25 en un mes de 31
días), con la misma condición sobre los 503. Reservado en nuestro registro si fallara cada
intento permitido: 5 + 4 × 7 = 33 créditos en 7 días (149 en 31 días, dentro del tope mensual
de 600). Los fallos que no son «no cobrados» entran en las 5 y congelan el día, así que no
cambian ninguna de las dos cifras.

**Qué pasa con el piloto al desplegar:** las tres llamadas del 2026-11-15 son anteriores a las
marcas, así que cuentan como cobradas: al piloto le quedan 2 lecturas hasta el 2026-11-22 a las
04:59 UTC y queda en espera hasta el 2026-11-16 a las 17:15 UTC. Devolver esos créditos sería
una escritura en producción que necesita el sí explícito de Herwin, y no se hizo.

**D4 — Las etiquetas leídas llegan a «Sugerir con IA» (2026-11-15/16, m-25032581).** Revisado en
producción el 2026-11-15, solo con consultas: la lectura semanal guardaba las etiquetas que
acompañan a los videos, pero casi no llegaban a las sugerencias. 40 de las 66 etiquetas leídas
quedaron sin clasificar y ninguna enlazada a las palabras del rubro; una etiqueta así solo
aparece si el texto trae esa misma palabra, y las vistas solo reordenan las etiquetas ya
enlazadas. Para un texto con «ensalada» el buscador devolvía `shawarma`, `food`, `foodie` y
`halal`, no `comidasaludable` (2,4 M de vistas) ni `ensaladasaludable`. La muestra es pequeña:
25 videos tras el filtro de español y 90 días.

- **Elegido por Herwin (2026-11-15), opción 1 de cuatro:** «Sugerir con IA» recibe además las
  etiquetas que acompañan a las del rubro del negocio en los videos leídos, con sus vistas y en
  cuántos videos aparecen, y el modelo toma las que encajan con el texto
  (`HashtagRepository.companions`, `caption.suggest_for_caption(watched=…)`, prompt
  `caption-hashtags/2`). Sin lista, la petición al modelo es la de antes, byte a byte. Esta
  consulta no escribe en el catálogo compartido ni enlaza nada a las palabras del rubro (lo
  único que escribe este cambio son las clasificaciones por regla de la lectura semanal, más
  abajo). Descartadas: enlazar por regla a las palabras del rubro (con la
  muestra de hoy enlazaba un dato útil y dos nombres de otros negocios, y es difícil de
  deshacer), lo mismo clasificando antes con IA, y no construir.
- **Medido (HASHTAGS-PIE-001, `docs/modelos-generativos/pruebas.md`):** 34 textos reales del
  piloto, anonimizados, 18 para ajustar y 16 de prueba. El prompt nuevo **no pasó la barra
  fijada antes de correr**: en la prueba, la etiqueta leída que no encaja con el texto sube 2,3
  y 3,3 puntos (barra: 2) y con catálogo las sugerencias que encajan bajan 3,1 puntos. Sí sube
  el uso de etiquetas leídas que encajan (de 1 % a 41 % sin catálogo, de 0 % a 28 % con
  catálogo) y no propone nombres de otros negocios. La recomendación del análisis era entregar
  sin activar el prompt nuevo.
- **Decisión de Herwin (2026-11-16): se entrega todo, con el prompt nuevo activo.** Manda esta
  decisión sobre la recomendación. Riesgo que se asume: entre las cinco «Mejor» puede aparecer
  una etiqueta leída que no encaja con el texto (en la prueba, cerca de 4 de cada 100; por
  ejemplo `carne` y `pollo` en un texto de «¿Cómo llegar?»). El dueño sigue eligiendo cada
  etiqueta antes de publicar.
- **También entra:** la lectura semanal clasifica por regla las etiquetas nuevas (la lista de
  genéricas, lugares y temas conocidos), lo que repara en la siguiente lectura las que quedaron
  sin clasificar, y ya no guarda la variante con emoji de una etiqueta como fila aparte.
- **Costo:** USD 0,0041 por uso de «Sugerir con IA» con la lista (USD 0,0034 sin ella), medido.
- **Se reabre si** el dueño del piloto reporta etiquetas que no encajan, o al medir la próxima
  versión (filtrar la lista antes de dársela al modelo), que necesita casos de prueba nuevos:
  los 16 de hoy ya se usaron.

## 1. Objetivo

Que las pocas etiquetas que lleva una publicación sean las que la gente del rubro está viendo, sin
que el dueño tenga que investigarlas y sin subir el costo. Qualify sugiere; el dueño aprueba.

## 2. Lo que ya existe en el disco (2026-11-13, `main` en `9a027a46`)

- Al crear la pieza, Claude escribe las etiquetas con las de la marca y su política
  (`packages/creative/src/qualify_creative/brand/render.py`). Desde el PR #642 la política trae
  un máximo de 5 por defecto (`HashtagPolicy.maximum`); una marca que ya guardó su máximo lo
  conserva (D2).
- En el editor: sugerencias al instante del catálogo y del texto (`Qualify/creative_vm.py`,
  `caption_hashtag_suggestions`) y «Sugerir con IA» (`qualify_api/hashtags/caption.py`, Claude
  Haiku, hasta 12 en popular / nicho / marca); «Sugerir con IA» marca las 5 mejores y con más de
  5 el editor avisa en una línea y deja publicar (PR #642). El editor acepta hasta 30
  (`HASHTAG_LIMIT`, lo que admite la API de Meta), también al guardar en el servidor.
- El catálogo compartido (`hashtags`, `hashtag_terms`, migración 0023) aprende de las búsquedas de
  referentes y cuenta cuántas veces vimos cada etiqueta.
- Desde el PR #644, la migración 0162 (`hashtag_post_sightings`) guarda por etiqueta las vistas y
  la fecha de cada publicación pública en que la vimos (búsquedas de referentes y lecturas de
  reels, sin gastar créditos nuevos), con su procedencia y sin ningún dato del negocio.
  `resolve_popular` ordena por vistas de los últimos 90 días sin que una coincidencia más lejana
  pase por delante de una más cercana. Las etiquetas que solo vimos en reels no entran a la cola
  de clasificación pagada.
- Desde el PR #647, el editor usa `resolve_popular`: las sugerencias del catálogo y la lista que
  recibe «Sugerir con IA» van primero con las etiquetas más vistas en los últimos 90 días.
- Entrega 3 (PR #666, m-25026378): la lectura semanal en TikTok (`qualify_api/hashtags/weekly.py`,
  migración 0167), apagada hasta encender `QUALIFY_HASHTAG_WEEKLY_READ`. Una etiqueta con una
  respuesta guardada en los últimos 7 días no se vuelve a leer; un negocio se intenta como mucho
  una vez al día; se detiene en el primer error; deja margen al dueño (no lee si el negocio ya
  gastó más de dos tercios de su tope del día o cinco sextos del mes). Tope fijo: un negocio
  nunca gasta más de 5 créditos de esta lectura en 7 días seguidos, cuente lecturas buenas o
  fallidas y aunque cambie sus etiquetas cada día; como mucho 25 en un mes. Si dos negocios
  leen la misma etiqueta a la vez, solo uno paga.
- Piloto de la entrega 3 (D3, m-25026378): el trabajador de reels de producción revisa esa
  lectura cada 6 horas, al final de su pasada (revisar seguido no cuesta: cada negocio se lee
  como mucho una vez por semana y, tras un fallo, se reintenta al día siguiente), solo para los
  negocios de `QUALIFY_HASHTAG_WEEKLY_TENANTS` (en el servicio `reels-worker` de
  `deploy/docker-compose.prod.yml`). Un negocio de la lista se lee aunque no haya abierto «Ideas
  para tus reels»; con la lista vacía no se lee a nadie aunque el interruptor esté encendido. Un
  fallo de la lectura se anota y el trabajador sigue con los reels; al apagarse (un despliegue)
  la lectura se corta entre etiquetas. `python -m qualify_api.hashtags.worker --all-tenants`
  también lee solo esa lista; `--tenant` sigue sirviendo para una prueba puntual en local.
- **Límite conocido, a decidir cuando se abra a todos (D3):** la regla de «negocios activos» que
  trae el código (hoy sin uso: durante el piloto `--all-tenants` lee solo la lista) leería solo
  los negocios que el trabajador de reels considera activos, y eso significa exactamente «una
  marca del negocio abrió la pantalla «Ideas para tus reels» en los últimos 14 días». No
  significa «cliente activo»: un negocio que publica a diario pero nunca abre esa pantalla no se
  lee, y uno que la abrió una vez y se fue se sigue leyendo dos semanas más.
- **Reparto desigual del costo:** cuando dos negocios comparten etiquetas, paga el que se procesa
  primero y el otro no paga nada por esas etiquetas esa semana. Lo que gasta cada negocio en
  esta lectura no refleja cuánto la aprovecha.
- La respuesta cruda se guarda en `vendor_payloads`, que guarda una fila por ruta y parámetros:
  cada semana reemplaza a la anterior de la misma etiqueta y país, y comparte esa fila con la
  memoria de las búsquedas de referentes. Por eso las vistas y fechas solo se pueden reconstruir
  desde la lectura más reciente; las de semanas anteriores quedan en `hashtag_post_sightings`
  pero no se pueden volver a leer.

## 3. Evidencia

| Dato | Nivel | Fuente |
|---|---|---|
| La API de Meta acepta hasta 30 etiquetas por publicación | `[V]` | Referencia de `IG User Media`, parámetro `caption`: «Maximum 2200 characters, 30 hashtags, and 20 @ tags» (leído 2026-11-13) |
| La app de Instagram limita a 5 desde el 2025-12-18 y su director dice que sirven para búsqueda, no para alcance | `[S]` | Prensa y blogs; no se encontró el anuncio original |
| `tiktok search-hashtag` da 20 videos por lectura con vistas, país, idioma y fecha; con `shawarma` y región CO: 14 de 20 en español, fechas de 2023 a 2026 | `[V]` | `just sc tiktok search-hashtag --hashtag shawarma --region CO --trim` (2026-11-13) |
| `instagram search-hashtag` da 10 publicaciones, mediana de 755 vistas, etiquetas en inglés, sin filtro de país | `[V]` | `just sc instagram search-hashtag --hashtag shawarma --date-posted last-month --media-type reels` |
| Las tendencias generales no tienen relación con un rubro (vallenato, NFL, Nvidia) | `[V]` | `just sc tiktok get-trending-feed --region CO --trim` · `just sc instagram reels-trending` |
| Cada lectura cobra 1 crédito; no hay ruta de «etiquetas en tendencia» | `[V]` | `credits_charged: 1` en las cuatro respuestas; `just sc tiktok --help` |
| Un crédito cuesta USD 0,00188 | `[V]` | `docs/adr-42-ideas-reels-costo.md` |

Las cuatro lecturas costaron 8 créditos (4 se repitieron por un error al guardar la salida).
`--cache-max-age` no existe en estas rutas.

## 4. Las cuatro entregas

| # | Entrega | Ticket | Qué gana el dueño | Depende de | Estado |
|---|---|---|---|---|---|
| 1 | **Cinco, bien elegidas** | m-25026376 | Una publicación con las cinco etiquetas que más le sirven, no doce | — | Hecha: PR #642 (2026-11-13) |
| 2 | **El catálogo sabe qué se ve** | m-25026377 | «Popular» significa vistas recientes en su rubro, no «lo vimos muchas veces» | — | Hecha: PR #644 (migración 0162) y PR #647 (el editor usa `resolve_popular`), 2026-11-13 |
| 3 | **Lectura semanal en TikTok** | m-25026378 | Etiquetas que acompañan esta semana a los videos más vistos de su rubro | 2 | Construida: PR #666 (migración 0167). Piloto (D3): el trabajador de reels la revisa cada 6 horas, solo para el negocio de la lista; se enciende en producción cuando se ponga su UUID en el servicio `reels-worker` |
| 4 | **Medir si sirve** | m-25026379 | Saber si el cambio trajo más alcance, con un negocio real | 1, 3 | Pendiente |

## 5. Criterios de aceptación (los que valen son los de cada ticket)

**1 · Generador: cinco etiquetas bien elegidas para Instagram** (Improvement, UI, P2)

- [ ] El generador escribe como máximo 5 etiquetas cuando la política de la marca no dice otra cosa.
- [ ] «Sugerir con IA» marca las 5 mejores y «Agregar todas» agrega solo esas.
- [ ] Con más de 5 el editor avisa en una línea y deja publicar: la API acepta hasta 30.
- [ ] Una marca que ya fijó su máximo lo conserva.

**2 · Etiquetas: el catálogo guarda vistas y fecha de lo que ya leemos** (Improvement, P2)

- [ ] Cada etiqueta vista en una búsqueda de referentes o una lectura de reels guarda las vistas y
      la fecha de la publicación, con la fuente (procedencia) y sin gastar créditos nuevos.
- [ ] «Popular» en «Sugerir con IA» se respalda con vistas de los últimos 90 días.
- [ ] Migración reversible, con RLS si la tabla lleva `tenant_id`.

**3 · Etiquetas: lectura semanal por etiqueta del rubro en TikTok** (Feature, P2)

- [ ] Una vez por semana y por negocio se leen hasta 5 etiquetas de su rubro, por la puerta medida
      (`metered_get`), cargadas a su tope (ADR 42), con una función nueva en `vendor_usage_events`.
- [ ] Una etiqueta leída en los últimos 7 días por cualquier negocio no se vuelve a leer.
- [ ] Solo cuentan videos en español de los últimos 90 días; se guarda la respuesta cruda.
- [ ] Repetir la corrida no duplica filas ni cobra dos veces; el worker corre con `--tenant`.
- [ ] Se apaga con un interruptor; prueba: `just sc tiktok search-hashtag --hashtag <rubro> --region CO --trim`.

**4 · Etiquetas: medir el alcance con un negocio** (Testing, P3)

- [ ] Cuatro semanas con un negocio: alcance de las publicaciones con etiquetas de la entrega 3
      frente a las cuatro semanas anteriores, escrito en este documento.
- [ ] Con el resultado se confirma o se reabre D1 antes del 2026-12-15.

## 6. Fuera de alcance

- Etiquetas de tendencias generales (opción D, descartada).
- Publicar o cambiar etiquetas sin que el dueño apruebe.
- Lecturas por etiqueta en Instagram: lo medido no alcanza.
