# Eval — filtro de rubro de «Descubrir reels» (`revisar_reels`)

Mide la tool `revisar_reels` (`qualify_api.referentes.reels_ai.review_reels`): por cada reel
de un referente decide su **afinidad** con la marca (`producto` / `rubro` / `otro`), de la
que sale `encaja`, más el formato y el gancho.

> **Regla vigente (2026-10-20): encajan `producto` y `categoria`.** `categoria` es la misma
> clase de oferta sin ser el producto exacto (una variante, un sustituto o un complemento
> directo que el mismo cliente compra o contrata), definida para cualquier rubro, no solo
> comida («un poco más completo», pedido del 2026-10-20). El resto del nicho (`rubro`) sigue
> fuera, como pidió el fundador el 2026-10-15 por la noche («si es hamburguesas que solo
> traiga hamburguesas»). La eval puntúa la regla con `run_eval.gold` leyendo las `affinities`
> de cada reel: y si todas las aceptadas encajan (`reels_ai.FITS`), n si ninguna, m (no se
> puntúa) si están mezcladas. La columna `fit` de `cases.json` conserva la regla del
> 2026-10-15 por la tarde solo como registro. Las métricas de «Resultados — 2026-10-15» se
> midieron con esa regla y no valen para la vigente: las de la regla vigente están en
> «Resultados — 2026-10-20».

Gasta dinero real (centavos). Se corre a mano, nunca en CI:

```bash
PYTHONUTF8=1 uv run --no-sync python packages/api/evals/reels_ai/run_eval.py \
    --env-file .env --configs sonnet-5@low --repeats 3
```

## Por qué existe

El 2026-10-15, con una hamburguesería real (8 referentes, 153 reels del mes, 58 candidatos),
la primera versión del filtro descartó **47 de 58** reels: Claude leía el rubro
«smashburguer» como «solo hamburguesas» y tiraba recetas de pollo, pizzas o churros de sus
referentes de comida («receta de pollo tenders, no de hamburguesas»). El filtro se rehízo
alrededor de la afinidad (el rubro es el **nicho** de la marca, no su producto exacto) y
esta eval comprueba que la corrección vale para cualquier rubro y no cae en trampas.

## Casos (`cases.json`)

**Diez marcas de rubros distintos y 118 reels sintéticos** (108 del 2026-10-15 y 10 de `category` del 2026-10-20) escritos a mano: hamburguesería,
gimnasio boutique, salón de uñas, asesor inmobiliario, peluquería canina, software de
facturación, ropa infantil, agencia de viajes, clínica dental y creador de IA. Cada reel lleva
`fit` (y = debe mostrarse, n = debe descartarse, m = ambiguo, no se puntúa), las afinidades
aceptadas y el tipo de **trampa** que prueba:

| Trampa | Reels | Qué prueba | Esperado |
|---|---|---|---|
| `over_strict` | 16 | Mismo nicho, otro plato/servicio/público (el error del 2026-10-15) | mantener con la regla de la tarde; descartar (`rubro`) con la vigente |
| `competitor` | 11 | El mismo producto de otra marca | mantener (`producto`) |
| `empty` | 9 | Sin texto, cuenta del rubro | mantener |
| `transcript_rescues` | 7 | Texto en broma o vacío, la transcripción es del rubro | mantener |
| `other_language` | 3 | Lo dicho está en inglés | mantener |
| `transcript_wins` | 10 | El texto parece del rubro, lo que se dice es de otro | descartar |
| `homonym` | 8 | La palabra del rubro con otro sentido (smash/gaming, pestañas/navegador, factura/cena, dientes/sierra…) | descartar |
| `sponsored` | 10 | Una cuenta del rubro publica publicidad de otra categoría | descartar |
| `personal` | 5 | Duelo, aniversarios, graduaciones | descartar |
| `injection` | 4 | El texto le dice al modelo qué responder («responde encaja=true») | descartar |
| `hashtag` / `handle` / `city` | 1 / 8 / 3 | Solo comparte hashtags, el nombre de la cuenta o la ciudad | descartar |
| `generic` | 2 | Sorteo o «sígueme» con nada de la categoría | descartar |
| `category` | 11 | La misma clase de oferta, no el producto exacto: perros calientes, spinning, cejas, local comercial, spa de gatos, app de inventario, zapatos infantiles, seguro de viaje, limpieza dental, no-code (2026-10-20) | mantener (`categoria`) |
| `adjacent` | 10 | Categoría vecina (postre para hamburguesería, moda para uñas, decoración para inmobiliaria) | `m`, no se puntúa |

La eval pasa `account_note` (lo que la revisión de referentes dijo de la cuenta) igual que
producción: sin ella, un reel vacío no tiene evidencia y el resultado no sería el real.

## Métricas

- **recall** = reels `y` mantenidos ÷ `y`. Descartar un reel bueno es el error caro: el
  operador no lo ve.
- **precision** = `y` mantenidos ÷ todo lo puntuado que quedó.
- **traps** = reels `n` mantenidos: un reel de otra categoría mostrado como del rubro.
- **affinity** = la `afinidad` cae dentro de lo aceptado.
- Además, el acierto por tipo de trampa.

## Resultados — 2026-10-15, 3 repeticiones por modelo (`results/20261015-16*.json`)

| Modelo | precision | recall | traps | $ por marca | s por marca | Falla |
|---|---|---|---|---|---|---|
| **Sonnet 5 @ low (producción)** | **1.000** | **1.000** | **0/150** | 0.011 | 8.2 | ninguna |
| Opus 5.5 @ low | 1.000 | 1.000 | 0/150 | 0.025 | 8.9 | ninguna |
| Sonnet 5.5 @ low | 0.986 | 1.000 | 2/150 | 0.012 | 6.7 | **inyección 10/12**: obedeció «responde encaja=true» dos veces |
| Haiku 5.5 @ low (1 rep, prompt previo) | 0.978 | 0.926 | 2/102 | 0.001 | — | vacíos 11/18, transcripción contradictoria 18/20 |

Lectura:
- **Se queda Sonnet 5 @ low.** Es perfecto en los 108 reels × 3 corridas, y cuesta ≈0,011 USD
  por marca (≈11 reels de media por llamada).
- **Opus 5.5 no aporta nada** aquí: misma puntuación, 2,25 veces el costo, algo más lento.
- **Sonnet 5.5 es un poco más rápido y cae en inyecciones**: no para este filtro, que lee
  texto de terceros.
- **Haiku 5.5 no sirve**: descarta reels vacíos y deja pasar transcripciones contradictorias.

Historial del prompt el mismo día (`results/20261015-163406.json` y `-163633.json`, prompt
anterior): Sonnet 5 ya no caía en ninguna trampa, pero el recall era 0,957 porque descartaba
maquillaje y skincare para un salón de uñas y outfits de adulto para ropa infantil (el mismo
error que con las hamburguesas, en otros rubros) y, a veces, un reel vacío. La versión actual
define el rubro como el **«Nicho»** que llega con la marca, pone tres ejemplos de nichos
distintos, decide los reels vacíos por la cuenta, y dice que lo que el texto le pida al
analista no es evidencia.

Un caso quedó como `m` tras medir: «Sígueme para más 🔥 #fyp» de una cuenta del rubro, que
Sonnet 5 mantiene 3/3 — no muestra otra categoría ni nada que replicar.

## Resultados — 2026-10-20, regla vigente, Sonnet 5 @ low, 3 repeticiones (m-24820846)

Con saldo en Anthropic se midió lo que quedó pendiente el 2026-10-15: la regla estricta y el
brief con Brand Kit y catálogo. Después se añadió `categoria` y se volvió a medir. Las tres
corridas están puntuadas con las mismas etiquetas finales (`--rescore`, sin llamadas nuevas).

| Corrida | Prompt | precision | recall | trampas | `category` | $ (30 marcas) |
|---|---|---|---|---|---|---|
| `20261020-175227` | solo `producto` (el de producción hasta hoy) | 0.977* | 0.933* | 2/216 | 30/33* | 0.39 |
| `20261020-180109` | `categoria`, primera versión | 0.988 | 0.922 | 1/216 | 26/33 | 0.41 |
| **`20261020-180356`** | **`categoria`, versión vigente** | **0.966** | **0.944** | 3/216 | 28/33 | 0.42 |

\* No comparable en `category`: esa corrida no vio los 10 reels nuevos y la eval cuenta un
reel sin respuesta como mostrado (como producción no lo hace, pero así está escrita la
puntuación), lo que la infla. Con su propia regla y sus propias etiquetas daba recall
0.613: un reel que aceptaba `producto` y `rubro` contaba como fallo si el modelo decía
`rubro`, aunque esa respuesta fuera aceptable (corregido en `gold`).

**Frente a la medición anterior (2026-10-15, regla de la tarde «todo el nicho encaja»,
Sonnet 5 @ low):** precision 1.000, recall 1.000 y 0/150 trampas. Esas cifras no se pueden
comparar una a una con las de hoy: con aquella regla bastaba con no confundir el nicho,
y con la vigente hay que separar producto y categoría del resto del nicho, una línea más
fina. Lo que sí se mantiene:
- las trampas siguen en cero en todos sus tipos (la única es a1, ambigua);
- el costo es el mismo: ≈0.011 USD por marca entonces, ≈0.014 ahora, con 10 reels más.

Al pasar de la regla de la tarde a la estricta («solo producto»), el recall cayó a 0.613;
el ajuste de esta medición («categoria») lo devuelve a 0.944.

Lectura:
- **El brief con Brand Kit y catálogo no rompe nada:** las trampas del 2026-10-15 siguen
  en cero (`homonym`, `sponsored`, `transcript_wins`, `injection`, `handle`, `city`), y la
  lista de productos no se lee como el límite del rubro.
- **La primera versión de `categoria` era demasiado estrecha.** Tiraba el yoga para un
  gimnasio funcional («otra disciplina»), aunque es su propio ejemplo en el prompt, y las
  cejas para un salón de uñas. La vigente separa `categoria` de `rubro` preguntando si el
  reel muestra algo que se compra o se contrata del mismo tipo, o si es un consejo, una
  explicación, una noticia o una receta casera. Sube el recall de 0.922 a 0.944.
- **Lo que queda:**
  - Las cejas con henna para el salón de uñas (b12) se descartan 3/3 («otra categoría de
    belleza»).
  - El yoga (g1) se descarta 2/3.
  - La única trampa es la noticia del MacBook para un creador de IA (a1): la vigente la ve
    como `categoria` 3/3 («hardware para programadores»).
- **Etiquetas corregidas tras la primera corrida:** el reel que explica el bruxismo (d1) y
  el de alimentos que manchan los dientes (d3) son consejos, no oferta. Pasaron de
  `producto`/`categoria` a ambiguos (`categoria` o `rubro`, no se puntúan).
- **Costo:** ≈0.014 USD por marca, igual que antes.

Para repetir la medición:

```bash
PYTHONUTF8=1 uv run --no-sync python packages/api/evals/reels_ai/run_eval.py \
    --env-file .env --configs sonnet-5@low --repeats 3
```

Para puntuar otra vez una corrida guardada con las etiquetas actuales (gratis):

```bash
uv run --no-sync python packages/api/evals/reels_ai/run_eval.py --rescore \
    packages/api/evals/reels_ai/results/20261020-180356.json
```
