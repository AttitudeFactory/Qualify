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
