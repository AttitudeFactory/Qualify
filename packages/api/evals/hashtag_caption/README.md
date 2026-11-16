# Eval «Sugerir con IA» — hashtags de un texto (m-25032581)

Mide `qualify_api.hashtags.caption.suggest_for_caption` (Claude `claude-haiku-4-5`,
herramienta forzada `sugerir_hashtags`, hasta 12 etiquetas; el editor marca las 5
primeras como «Mejor»). Ticket m-25032581, épica m-25026375.

- **Fase 1 (esta):** set de oro, reglas, corredor y **línea base** con el prompt de hoy
  (`caption-hashtags/1`, sin `watched`).
- **Fase 2 (2026-11-15):** el prompt nuevo (`caption-hashtags/2`) recibe `watched`, las
  etiquetas que acompañan a las del rubro en los videos más vistos del rubro, y debe tomar
  solo las que encajan con el texto. **Resultado: pasa en dev, NO pasa la barra en test**
  (ver «Resultados»).

Gasta dinero real (Anthropic): se corre a mano, nunca en CI.

```bash
PYTHONUTF8=1 uv run --no-sync python packages/api/evals/hashtag_caption/run_eval.py \
    --env-file .env --split dev --variants none,own --repeats 3
# solo puntuar de nuevo un resultado guardado (sin llamadas):
uv run --no-sync python packages/api/evals/hashtag_caption/run_eval.py --rescore results/<archivo>.json
```

## Archivos

| Archivo | Qué es |
|---|---|
| `cases.json` | 34 casos (textos reales anonimizados), la partición dev/test, la lista `watched` y las etiquetas de oro por caso |
| `lexicon.json` | Listas globales de trampas (otros negocios, relleno, lugares, región amplia) y las adjudicaciones |
| `weekly_snapshot.json` | Los 25 videos públicos de TikTok que guardó la lectura semanal del piloto (foto del 2026-11-15) |
| `build_watched.py` | Arma `watched` con el código del producto a partir de la foto (ver «Lista vigilada») |
| `run_eval.py` | Corredor + puntuador local (no necesita servidor); escribe `results/<fecha>-<split>-<variantes>.json` y, mientras corre, `.partial.jsonl` |
| `test_labels.py` | Pruebas sin red de las reglas de etiquetado |
| `results/` | Respuestas crudas por caso y repetición, con modelo, revisión y versión del prompt |

## Datos de origen

Exportados de producción, solo lectura, el 2026-11-15 por el líder (no se volvieron a
consultar): 69 textos distintos de borradores del negocio piloto (shawarma y ensaladas en
San Cristóbal, Táchira; etiquetas del rubro `shawarma, comidaarabe, sancristobaltachira,
tachira, ensaladas`) y los 25 videos públicos de TikTok que guardó la lectura semanal.
Los archivos crudos NO se suben al repositorio.

**Anonimización** (lo que sale de la base): el nombre del negocio → `MiNegocio`
(`#MiNegocio`); el nombre del local donde atiende → `la Plaza` (`#LaPlaza`); se quitan
teléfono, dirección (avenida, punto de referencia), sitio web y la etiqueta de la
avenida. El español queda tal cual (con sus «parce», «tinto», «calientico»).

## Selección de casos (34) y por qué

De los 69 textos se tomaron 34: con 69 hay muchos casi idénticos (≈25 variantes de
«Shawarma Mixto + café» de una misma semana) que repiten la misma medición. Se priorizan
los aprobados/seleccionados y se cubre el rango del negocio:

| Grupo | Casos | Qué prueba |
|---|---|---|
| `corto_aprobado` | 9 | Textos cortos aprobados y publicados, con `#` en el propio texto |
| `aprobado_largo` | 3 | Aprobados largos (carne, pollo a domicilio, «¿dónde queda?») |
| `shawarma_cafe` | 7 | Época en que la marca se presentaba como cafetería: shawarma + café |
| `shawarma_plaza` | 10 | Época «la Plaza»: almuerzo de oficina, con o sin ensalada, reacciones |
| `helado` | 2 | Producto distinto (helado artesanal), sin shawarma |
| `jugo_otra_ciudad` | 1 | Jugo natural en **Barquisimeto** (otra ciudad: San Cristóbal es la trampa aquí) |
| `sin_comida` | 2 | **Control real** sin palabra de comida: tutorial de videojuegos (Godot) que vive en el mismo negocio. Toda etiqueta de comida es error |

No hay casos sintéticos: los dos de control son textos reales del inquilino.

**Partición fija** (en `cases.json`, campo `split`): dentro de cada grupo, ordenado por
índice de exportación, se alterna dev/test empezando por dev; el único `jugo_otra_ciudad`
va a test. Resultado: **dev 18 / test 16**. Nunca se ajusta un prompt mirando test.

## Reglas de etiquetado (escritas ANTES de etiquetar)

Cada etiqueta propuesta (sin `#`, plegada a minúsculas sin tildes) cae en UNA clase, en
este orden de prioridad:

1. **`competidor`** (trampa) — nombre de otro negocio o de otro creador de comida:
   `amirexpress`, `yaalashawarma`, `shawarmaelcompadre`, `shawarmacaracas`, `javivi`,
   `manosalsazon` (lista en `lexicon.json`; la amplía la adjudicación).
2. **`relleno`** (trampa) — no dice nada del contenido: `viral`, `parati`, `fyp`,
   `foryou`, `like`, `love`, `instagood`, `explore`, `trending`, `reels`, `tiktok`…
3. **`otro_lugar`** (trampa) — un lugar que no es el del texto: ciudades/regiones de
   `lexicon.json` que no contienen ninguno de los `lugares_ok` del caso (para el negocio
   de San Cristóbal: `sancristobal`, `tachira`, `venezuela`, `gocho`, `sc`). Para el caso
   de Barquisimeto, San Cristóbal y Táchira son `otro_lugar`. Para el control de
   videojuegos, cualquier lugar lo es.
4. **`vigilada_no_encaja`** (trampa) — una etiqueta de la lista `watched` que el caso NO
   marca como encajada ni aceptable: las de un solo video viral ajenas a la comida
   (`navidad`, `cashea`, `contenido`) y las de comida que no describen ESTE texto
   (`recetasfaciles`, `recetasrapidas`, `recetafacil`, `recipes`: el negocio vende comida,
   no enseña recetas; `ensalada` en un texto que no habla de ensaladas).
5. **`encaja`** — describe lo que el texto dice (producto, ingrediente, ocasión, lugar del
   texto, marca anonimizada `minegocio`/`laplaza`, tono): está en `encaja` del caso o
   contiene una de sus `raices` (p. ej. `shawarma`, `almuerzo`, `sancristobal`).
6. **`aceptable`** — no es error pero aporta poco o es amplia (`foodie`, `foodtok`,
   `comer`, `gochosvenezolanos`): lista `aceptable` del caso.
7. **`no_encaja`** — lista `no_encaja` del caso (p. ej. `cafe` en un texto sin café,
   cualquier etiqueta de comida en el control de videojuegos).
8. **`sin_etiqueta`** — nada de lo anterior. Tras cada corrida se adjudica a mano CON
   ESTAS REGLAS (no según convenga al resultado) y se añade al caso en `adjudicado`; las
   adjudicaciones quedan marcadas y fechadas.

**Vigiladas por caso** (`watched_fit` = lo que el prompt nuevo DEBERÍA tomar si encaja):
`arabe` en todo texto de shawarma; `pollo` / `carne` si el texto los nombra; `ensalada`,
`ensaladasaludable`, `comidasaludable` si el texto habla de ensaladas (y
`comidasaludable` en el jugo natural sin azúcar); `probandocomida` en los textos de
reacción al primer mordisco. Aceptables (`watched_ok`): `foodie`, `foodtok`, `comer` en
textos de comida; `gochosvenezolanos` y `tachira_venezuela🇻🇪` en textos de San
Cristóbal; `comidareal` si el texto insiste en que la foto es real; `comidacasera` si dice
«casera»; `cocina` en el del trompo. Todo lo demás de `watched` es `vigilada_no_encaja`
(o `competidor`).

## Métricas (definición exacta)

Se calculan por repetición completa del split y se informa media y rango (mín–máx) de
las 3 repeticiones.

- **Tasa de trampa por clase** (`competidor`, `relleno`, `otro_lugar`,
  `vigilada_no_encaja`): trampas de esa clase / etiquetas propuestas, en el **top 5** y en
  **todas**. Además, **casos con ≥1 trampa en el top 5** / casos.
- **Encaja** = (`encaja` + `aceptable` + `generica`) / propuestas, top 5 y todas; `no_encaja` y
  `sin_etiqueta` se informan aparte.
- **Toma de vigiladas en el top 5** (fase 2): en los casos con ≥1 `watched_fit` que la
  lista ofrece de verdad, media de |top5 ∩ F| / min(5, |F|), con F = `watched_fit` ∩
  `watched`. En la línea base el modelo no
  ve la lista, así que mide lo que acierta por su cuenta.
- **Respaldo del catálogo**: propuestas con `seen_count > 0` / propuestas (solo tiene
  sentido en la variante `own`).
- **Estabilidad**: Jaccard medio del top 5 entre repeticiones del mismo caso.
- **Costo**: USD por llamada con el uso de tokens real y `qualify_api.claude_tools.PRICES`
  (tabla `PRICING_TABLE_VERSION`), y por negocio al mes con el supuesto declarado.

## Variantes

El catálogo real del piloto (`seen`) no se pudo reproducir (no hay acceso a producción):

- `none` — `seen=()`: el modelo recibe «El catálogo no tiene hashtags para este tema
  todavía».
- `own` — `seen` = las etiquetas que el texto ya tenía en producción, cada una con conteo
  1. Es una aproximación optimista (son etiquetas hechas para ESE texto).
- `watched` / `own+watched` — lo mismo, más la lista vigilada (`caption-hashtags/2`).

## Adjudicaciones del 2026-11-15

Las reglas de arriba dejaron etiquetas sin clase (`sin_etiqueta`) y otras que una raíz
daba por buenas aunque estaban mal escritas (`comidaderrapida` contiene `comida`). Se
adjudicaron con las mismas reglas en `lexicon.json` → `adjudicado` (y `c61.adjudicado`),
sin mirar las métricas, en tres pasadas:

1. **Tras la línea base** (dev y test): ~280 etiquetas `sin_etiqueta`.
2. **Tras la primera corrida de `/2` en dev:** se releyeron UNA vez todas las etiquetas
   que una raíz marcaba `encaja` en TODOS los archivos de resultados, línea base incluida
   (669 distintas). Las mal escritas pasaron a `mal_escrita`; recetas y cocinas de otros
   países a `no_encaja`; `yalashawarma` y `shalimsancristobal` a `competidor`; Perú,
   Monterrey, Caracas y Chile a `otro_lugar`.
3. **Tras cada ronda y tras test:** solo las etiquetas nuevas de esa corrida.

Las pasadas 2 y 3 cambiaron también los números de la línea base: los de abajo son los
vigentes, recalculados con `--rescore` (la línea base de la fase 1 decía 6–7 % de mal
escritas en el top 5; con la segunda pasada son 10–14 %).

Clases añadidas, declaradas porque llegaron después de ver datos (ninguna cambia una
clase existente):

- **`mal_escrita`** (parte de `no_encaja`, no es trampa ni encaja): `sancrystobal`,
  `sancristo`, `enalada`, `streetsood`, `comidaderrapida`, `pollofreshco`… Una etiqueta mal
  escrita no la busca nadie.
- **`generica`** (parte de `aceptable`, cuenta como encaja): `negociolocal`,
  `emprendimiento`, `apoyalocal`.
- **Región amplia:** una región que CONTIENE el lugar del texto (`latinoamerica`,
  `latam`) no es `otro_lugar`; queda `aceptable` como mucho. Es un eco del SYSTEM
  («marcas de Latinoamérica»). `pedidosya` (app de domicilios) es `competidor`;
  `bancolombia` es aceptable en c61 porque el texto la nombra como medio de pago.

Las adjudicaciones `mal_escrita`, `no_encaja` y `generica` mandan sobre una raíz; las
positivas solo llenan huecos. **Límite:** la revisión de etiquetas mal escritas es humana
y de una sola lectura; alguna se habrá escapado en las dos direcciones.

## Lista vigilada (`watched`): la arma el código del producto

`build_watched.py` toma la foto de los 25 videos (`weekly_snapshot.json`) y hace lo que
hará producción después de la próxima lectura semanal:
1. pasa cada etiqueta por `weekly.readable_tag`;
2. guarda los avistamientos en `MemoryHashtagRepository`;
3. aplica las clases que la foto ya tenía (como `classified_by="ai"`: supuesto, la
   exportación no dice quién decidió) y después `weekly.rule_classifications`;
4. pide `companions(...)` con las cinco etiquetas del rubro, los valores por defecto del
   producto y `now` = 2026-11-15.

- **`tachira_venezuela🇻🇪` ya no llega al modelo**: `readable_tag` la descarta (3
  avistamientos). `gochosvenezolanos` tampoco aparece en la lista.
- **Lista (top 20, `now` = 2026-11-15):** recetasfaciles (2 videos), amirexpress (2),
  yaalashawarma (2), comidasaludable, comidacasera, comidareal, manosalsazon,
  recetasrapidas, arabe, carne, comer, pollo, cocina, foodtok, navidad, recipes,
  ensalada, ensaladasaludable, recetafacil, contenido (1 video cada una).
- **La lista de producción cambia cada semana.** Desde el 2026-11-16 la ventana de 90
  días saca el video del 18-ago. Sin él salen `comidasaludable` (2,4 M de vistas, la
  vigilada más útil para ensaladas) y uno de los dos `recetasfaciles`, y entra
  `probandocomida`. Queda (`watched_without_0818` en `cases.json`): amirexpress (2),
  yaalashawarma (2), comidacasera, comidareal, manosalsazon, recetasfaciles,
  recetasrapidas, arabe, carne, comer, pollo, cocina, foodtok, navidad, recipes,
  ensalada, ensaladasaludable, recetafacil, contenido, probandocomida.
- **La medición usa la foto del 15-nov:** es reproducible.
- **Lo que la lista trae:** de 20 etiquetas, solo 5–7 sirven a algún texto (arabe,
  carne, pollo, ensalada, ensaladasaludable, comidasaludable, foodtok). Tres son nombres
  de otros negocios o creadores, y seis son recetas.

## Resultados — `claude-haiku-4-5` (revisión `claude-haiku-4-5-20251001`)

Celda = media (mín–máx de las pasadas completas). «top 5» = las que el editor marca
«Mejor».
- **Línea base** `caption-hashtags/1`: 3 repeticiones. Sin `watched` el módulo envía el
  prompt anterior byte a byte (verificado en los 34 casos × 2 `seen` contra `d6098140`) y
  lo registra como `/1`.
- **`/2` final:** dev con 1 repetición (ronda 2) y test con 2, por el tope de gasto (ver
  «Gasto»).

### Barra (acordada con el líder antes de correr `/2`, decidida en dev, confirmada UNA vez en test)

1. Cero etiquetas de otros negocios en el top 5.
2. Ninguna clase de trampa más de 2 puntos por encima de su línea base.
3. Mal escritas y «encaja» no peores que la base en más de 2 puntos.
4. Toma de vigiladas en el top 5 claramente por encima de la base (se informa el número).

### Dev (`none` → `watched`; las rondas cambian solo `WATCHED_ADDENDUM`)

| métrica (top 5 salvo indicación) | base `none` (3 rep.) | `/2` original (3 rep.) | ronda 1 (1 rep.) | ronda 2 = final (1 rep.) |
|---|---|---|---|---|
| competidor | 0 | **0.133 (0.100–0.167)** | 0 | 0 |
| relleno | 0 | 0 | 0 | 0 |
| otro_lugar | 0.011 | 0.004 | 0 | 0.011 |
| vigilada_no_encaja | 0.007 (0–0.011) | **0.155 (0.111–0.233)** | 0 | 0 |
| casos con ≥1 trampa | 0.093 | 0.722 | 0 | 0.056 |
| encaja | 0.852 (0.833–0.867) | 0.667 (0.600–0.722) | 0.867 | 0.911 |
| mal escrita | 0.104 (0.089–0.111) | 0.026 | 0.111 | 0.067 |
| toma de vigiladas | 0.030 (0.013–0.065) | 0.300 (0.231–0.356) | 0.062 | **0.507** |

En `own+watched`, el `/2` original con 3 repeticiones dio:
- competidor en el top 5 0.052 (0.033–0.067);
- vigilada_no_encaja 0.074;
- encaja 0.852 (base `own`: 0.952);
- toma 0.045.

La redacción final no se corrió en dev con `own+watched`, por el tope de gasto.

### Test, UNA corrida con la redacción final (2 repeticiones) — **no pasa la barra**

| métrica | base `none` | `/2` `watched` | base `own` | `/2` `own+watched` |
|---|---|---|---|---|
| competidor, top 5 | 0.004 (0–0.013) | **0** ✓ | 0 | **0** ✓ |
| competidor, todas | 0.002 | 0 | 0.002 | 0.003 |
| relleno, top 5 | 0 | 0 ✓ | 0 | 0 ✓ |
| otro_lugar, top 5 | 0.004 (0–0.013) | 0.006 (0–0.013) ✓ | 0.004 | 0 ✓ |
| vigilada_no_encaja, top 5 | 0.021 (0.013–0.025) | **0.044 (0.037–0.050) ✗ +2,3** | 0.004 (0–0.013) | **0.037 (0.025–0.050) ✗ +3,3** |
| · con `comidacasera` aceptable | 0.000 | 0.044 ✗ +4,4 | 0.000 | 0.031 ✗ +3,1 |
| casos con ≥1 trampa, top 5 | 0.125 | 0.188 | 0.042 | 0.156 (0.125–0.188) |
| encaja, top 5 | 0.800 (0.775–0.825) | 0.887 (0.875–0.900) ✓ | 0.975 (0.963–1.000) | **0.944 (0.938–0.950) ✗ −3,1** |
| mal escrita, top 5 | 0.138 (0.113–0.163) | 0.044 (0.037–0.050) ✓ | 0.017 | 0.019 ✓ |
| toma de vigiladas, top 5 | 0.013 (0–0.024) | **0.408 (0.398–0.419)** | 0 | **0.275 (0.268–0.282)** |
| estabilidad (Jaccard top 5) | 0.18 | 0.28 | 0.59 | 0.59 |
| USD por llamada | 0.00335 | 0.00413 | 0.00329 | 0.00405 |

**Veredicto: dev pasa (con una sola repetición); test NO pasa.** Cumple cero
competidores en el top 5 y toma 30–40 veces más vigiladas que encajan. Falla por:
- `vigilada_no_encaja`: +2,3 y +3,3 puntos, con `comidacasera` como trampa o como
  aceptable;
- «encaja» en `own+watched`: −3,1 puntos.

Las trampas de test son vigiladas de comida puestas en textos que no las nombran:
- `carne` y `pollo` en «¿Cómo llegar?» (c48);
- `comidasaludable` en «Con salsa de la casa… vegetales frescos» (c31) y en el horario
  nocturno (c26);
- `carne` en un «Shawarma Mixto» que no dice carne (c08).

Algunas son discutibles (un mixto lleva carne), pero las etiquetas no se tocaron después
de ver test.

**Ejemplos reales (`/1` → `/2`, top 5):**
- **Bueno:** c13 «¿Pollo o carne? … el mixto trae los dos». `/1` daba
  `polloycarnealmohada`, `comidafasil` y `sandwichcasero`; `/2` da `pollo`, `carne` y
  `arabe`.
- **Bueno:** c21 «el shawarma y la ensalada se arman al momento». `/2` agrega
  `ensalada` y `arabe`, y quita `comidaalfrescor`.
- **Malo:** c48 «¿Cómo llegar? 📍 Estamos en la Plaza…». `/2` pone `carne` y `pollo`,
  que el texto no nombra.
- **Malo:** c26, horario nocturno. `/2` saca `comidaarabeperu` (otro país) y
  `comidasaludable`.
- **Malo en la versión original:** `yaalashawarma` en el top 5 40 de 108 veces, con
  motivo «hashtag específico del rubro de shawarmas». `amirexpress` salió con motivo
  «Negocio similar del rubro»: lo reconoció como negocio y lo eligió igual.

### Rondas de ajuste (solo `WATCHED_ADDENDUM`; SYSTEM y la petición sin vigiladas intactos)

- **Original (commit `e112d8d3`):** «Prefiérelos cuando encajen… Nunca elijas el nombre
  de otro negocio…». Haiku no reconoce nombres de locales escritos como una palabra.
- **Ronda 1:**
  - avisa que los publicó gente que no es este negocio;
  - pide tomarlos solo si nombran algo que el texto dice;
  - da la prueba de la palabra común (nombre propio, apodo o marca, con ejemplos
    inventados `#tacosdonpepe`, `#burgerlarry`);
  - recetas solo si el texto enseña a cocinar;
  - las vistas no hacen que encaje.

  Trampas a 0, pero la toma bajó a 0.062.
- **Ronda 2 (final):** agrega «El que sí encaja (el ingrediente o el tipo de comida que
  el texto nombra, en una palabra común) ponlo entre los cinco primeros». La toma sube a
  0.507 en dev; en test arrastra vigiladas de comida a textos que no las nombran.

**Recomendación (de quien midió, no decisión):** no publicar `/2` con esta lista tal
cual. Lo que falla no es solo el prompt: 13 de las 20 vigiladas no sirven a ningún texto
del negocio. Hay dos caminos:
- filtrar la lista antes del modelo (sin nombres de cuentas y sin recetas para un
  negocio que vende comida, con un clasificador o la clase del catálogo);
- dar al modelo solo las vigiladas cuya palabra aparece en el texto (pollo, carne,
  ensalada).

Cualquiera de los dos se mide con este mismo set. Test ya se usó y la próxima versión
debería medirse con casos nuevos de test.

## Costo

USD por llamada, medido con los tokens reales y `PRICES` (`PRICING_TABLE_VERSION` v7:
Haiku 4.5 = US$1 / US$5 por millón; el SYSTEM no llega al mínimo de caché de Haiku):
- **`/1` US$0.0034** (≈1.250 tokens de entrada, ≈420 de salida);
- **`/2` US$0.0041** (≈1.980 de entrada, ≈430 de salida).

Por negocio y mes (supuesto, `[H]`):
- el piloto generó 69 textos distintos en 26 días (21-oct → 15-nov), ≈80 al mes;
- con 1–2 pulsaciones de «Sugerir con IA» por publicación revisada son 60–160 llamadas;
- **US$0.20–0.55 al mes con `/1` y US$0.25–0.66 con `/2`.**

## Gasto

| Fase | Llamadas registradas | USD registrados | Sin registrar |
|---|---|---|---|
| 1 (línea base) | 206 | 0.690 | — |
| 2 (`/2`: dev 108, rondas 18 + 18, test 64) | 208 | 0.846 | ≤ 0.44 (abajo) |
| **Total** | 414 | **1.536** | ≤ 0.44 |

Gasto sin registrar de la fase 2:
- **Corrida duplicada de dev:** por un error de comando corrió dos veces; la segunda se
  detuvo a los ~63 s. Con 4 hilos y ≥4 s por llamada son como mucho ~60 llamadas,
  ≤ US$0.25.
- **Ronda de 2 repeticiones colgada:** quedó 26 minutos en conexiones muertas y se mató
  sin escribir. Su propio tope era US$0.175, así que como mucho ≈ US$0.19.

Ninguna de las dos dejó resultados. Desde entonces el corredor:
- usa un cliente con 60 s de espera y 1 reintento;
- escribe cada llamada en `.partial.jsonl` en cuanto termina.

Peor caso de la fase 2: 0.846 + 0.44 = 1.29 (tope US$1.30).

## Receta `just` (la agrega el líder; no se editó el `justfile`)

```just
# m-25032581: «Sugerir con IA» de hashtags del texto — gasta dinero real (centavos).
eval-hashtags-caption *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/hashtag_caption/run_eval.py --env-file .env {{args}}
```
