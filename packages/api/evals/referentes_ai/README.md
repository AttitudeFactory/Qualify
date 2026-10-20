# Eval — revisión de referentes con IA (Haiku 4.5 vs Sonnet 5)

Mide la tool `revisar_cuentas` (`qualify_api.referentes.ai.review_accounts`), que recibe la
lista corta de cada fase de la búsqueda de referentes. Para cada cuenta decide si **encaja** con
la marca (si no, se descarta) y **qué es**: marca, creador, medio u otro.

Gasta dinero real (centavos). Se corre a mano, nunca en CI:

```bash
uv run --no-sync --with anthropic python packages/api/evals/referentes_ai/run_eval.py \
    --env-file .env --repeats 2
```

## Casos (`cases.json`)

Son cuatro marcas y 164 cuentas etiquetadas a mano. Las cuentas son **reales**: las que las
búsquedas guardadas encontraron (`brand_discovered_accounts`, 25-09-2026), con el caption que
la búsqueda trajo. La excepción son 4 cuentas `synthetic` en el caso del restaurante de autor.

| Caso | Cuentas | y / n / m | Qué prueba |
|---|---|---|---|
| `smash-burger-tachira` | 52 | 15 / 31 / 6 | Hamburguesas frente a tecnología, noticias, turismo local o humor que colaron por un hashtag o por la ciudad |
| `programming-creator` | 55 | 6 / 41 / 8 | "Programación" de TV, automotriz o del combustible; noticieros; hardware |
| `fine-dining-bogota` | 27 | 4 / 21 / 2 | **Mismo tema, otro negocio**: hamburgueserías y comida rápida para un restaurante de autor |
| `phone-store-caracas` | 30 | 11 / 13 / 6 | Mismo tema, otro negocio: cuentas de programación para una tienda de celulares |

- `y`: un par real de la marca.
- `n`: no lo es. Cuenta como trampa cuando comparte una palabra o un tema.
- `m`: ambiguo, no se puntúa.

## Métricas

- **precision** = cuentas `y` que quedaron ÷ todo lo puntuado que quedó.
- **recall** = cuentas `y` que quedaron ÷ total de `y`. Descartar un referente bueno es el error
  más caro: el operador no lo vuelve a ver.
- **traps** = cuentas `n` que quedaron. Es el error que esta función existe para evitar.
- **kind** = el `tipo` cae dentro de lo aceptado.

## Experimento en Langfuse — 2026-10-14 (`results/langfuse-20261014-065507.json`) — ACTUAL

Los mismos casos y el mismo puntaje, como corridas de dataset en Langfuse (dataset
`referentes-revisar`), con los modelos Claude 5.5 como candidatos. `run_experiment.py`
importa el runner y el puntaje de `run_eval.py`, no los copia:

```bash
just langfuse-up
just eval-referentes
just eval-referentes --configs haiku-5.5@low
```

Una corrida por configuración, sin repetir todavía.

| Modelo | precision | recall | perdidos | traps | kind | $ total |
|---|---|---|---|---|---|---|
| Sonnet 5 @ low (producción) | 1.000 | 0.758 | 9 | 0/106 | 0.917 | 0.142 |
| Sonnet 5.5 @ low | 1.000 | 0.735 | 10 | 0/106 | **0.991** | 0.130 |
| **Haiku 5.5 @ low** | 1.000 | **0.799** | **8** | 0/106 | 0.936 | **0.013** |

**El recall bajó para todos frente a septiembre (0.926), y no es el harness.** Se repitió
`run_eval.py` sin Langfuse para Sonnet 5 @ low el mismo día
(`results/20261014-071418.json`): recall 0.78 y una trampa (`matsimultiservicios`). Casi
toda la caída está en un caso:

- `phone-store-caracas` bajó a recall 0.455. Sonnet 5 descartó seis creadores tech que
  publican en inglés (`tatechtips`, `imparkerburton` en las dos redes, `reddnea` en las
  dos redes, `one.more.official`).
- Es el mismo criterio que en septiembre solo aparecía con effort medium: «público
  internacional». Hoy aparece también en low.
- `programming-creator` pierde las mismas dos cuentas discutibles de septiembre.

Lectura:

- **Haiku 5.5 es candidato fuerte para reemplazar a Sonnet 5.** Cero trampas, el mejor
  recall de los tres y 11 veces más barato. Haiku 4.5 se había descartado justo por las
  trampas.
- Antes de cambiar el default hace falta una segunda corrida, como pide el plan (§6.3).
- El caso de la tienda de celulares muestra un criterio inestable de los tres modelos con
  cuentas en otro idioma. Se arreglaría en el prompt («el idioma o el país del público no
  bastan para descartar»), pero es un cambio de producción y no se hizo aquí.

## Resultado (25-09-2026, prompt final, 2 repeticiones × 4 casos)

| Modelo | precision | recall | traps | kind | s/caso* | $/caso |
|---|---|---|---|---|---|---|
| Haiku 4.5 | 0.950 | 0.920 | **5/212** | 0.868 | 20.6 | 0.016 |
| **Sonnet 5 @ low** | **1.000** | **0.926** | **0/212** | 0.915 | 26.3 | 0.038 |
| Sonnet 5 @ medium | 1.000 | 0.911 | 0/212 | 0.948 | 41.4 | 0.052 |

\* Un caso son 27 a 55 cuentas en lotes de 30 secuenciales. En producción una fase son como
máximo 20 cuentas, en dos llamadas de 10 **en paralelo**: medido en vivo, **9 s y ~$0.02 por
fase**.

**Elección: Sonnet 5 @ low** (`REVIEW_MODEL` / `REVIEW_EFFORT`).

- **Haiku 4.5:** deja pasar trampas. Ejemplos: meal prep saludable y humor para una
  hamburguesería, vacantes de empleo para un creador de programación. En la primera versión del
  prompt, además, una vez respondió solo 25 de 55 cuentas y se le escaparon 21 trampas.
- **Sonnet 5:** 0 trampas en ambos niveles de effort.
  - `low` es un 30% más barato y rápido.
  - `medium` no mejora el recall. En una corrida descartó 6 creadores tech en inglés para la
    tienda de celulares, por "público internacional".
- **Descartes de `low` contra la etiqueta:**
  - `jean.iovino`: publica sobre empleo tech, no enseña programación.
  - `thecodingspacerd`: academia para niños de 3 a 18 años.
  - `vip_phonecity`: humor sobre tiendas.
  - Los tres son discutibles: la etiqueta `y` fue generosa.

## Un hallazgo que cambió el código

El modelo devolvía los ids de caller mal copiados. `otro:pasteleria-dona-rosa` volvía como
`pasteleria-dona-rosa` y la cuenta quedaba sin revisar. Por eso ahora cada cuenta se muestra
con un número corto (`[1]`, `[2]`…), el modelo responde con ese número y el módulo lo traduce
al id real. El cambio también mejoró a Haiku: pasó de 25 a 5 trampas.
