# Eval — cortes y rostros del análisis de reels (VE-05, m-24921050)

Mide el análisis de reels por planos: el detector de planos de VE-02 (`detect_shots`, PyAV) y
personas y rostros por plano de la ficha de Haiku (`people_presence` / `visible_faces`) frente a
una anotación **humana** de 20 reels públicos reales. Informe con las cifras y el método:
`docs/modelos-generativos/ve05-medicion-cortes-rostros.md` (entrada VE05-001 de la bitácora).

```bash
just eval-cortes-rostros                  # cifras del informe (gratis, sin red)
just eval-cortes-rostros --tolerance 0.5  # sensibilidad
just eval-cortes-rostros --results packages/api/evals/reel_shots_ai/results/ve05-20261105-v8.json --cuts-results ""
```

Imprime las tablas en Markdown. Resultado del 2026-11-06: F1 de cortes 0,927 (179 / 20 / 8),
personas 94,9 % y rostros 87,7 % sobre 195 planos, sin ninguna persona ni cara perdida.

## Archivos

| Archivo | Qué es |
|---|---|
| `docs/modelos-generativos/ve05-anotacion-cortes-rostros.csv` | La verdad: cortes reales (s) y un `si`/`no` por plano real para persona y rostro |
| `results/ve05-20261105.json` | Versión 6 (2026-11-05), solo salida del modelo |
| `results/ve05-20261105-v7.json` | Versión 7; da los cortes del reel que falta en la 8 (`--cuts-results`, por defecto) |
| `results/ve05-20261105-v8.json` | Versión 8 tal como quedó guardada |
| `results/ve05-20261105-v8-replay.json` | Versión 8 con la regla de personas final: lo que puntúa `score.py` por defecto |
| `score.py` | Puntaje (`--results`, `--cuts-results`, `--tolerance`) |
| `replay_presence.py` | Genera el `replay` |

**Por qué el `replay`.** Las filas de la versión 8 se guardaron antes de la regla de cobertura
final (`presence-frames-gap0.5-3`, commit 95277026). `replay_presence.py` vuelve a aplicar
`resolve_presence` del código actual a las respuestas por fotograma guardadas en
`reel_sheet.presence.frames`. No llama al modelo; solo lee la base **local** de desarrollo
(`docker exec qualify-postgres-1 psql`, un SELECT por reel). El resumen por grupo no se guarda y
se deduce de los fotogramas del grupo. Los cortes no cambian.

**`--cuts-results`.** Un reel que falta en el resultado puntuado (en la 8, 7703559161040211233:
el enlace del video había vencido) toma los planos de otra corrida **solo para los cortes**; sus
etiquetas no cuentan. `fill_missing_cuts` se niega si el detector de esa corrida es otro.

## Métricas (`qualify_api/evals/reel_shots.py`)

- **F1 de cortes** a ±0,25 s: un corte es el inicio de cada plano salvo el primero; emparejamiento
  uno a uno, primero los pares más cercanos; F1 micro (VP/FP/FN sumados del conjunto) y por reel.
  Si F1 < 0,85 se reabre el detector (ADR 44, diseño §4.1).
- **Personas y rostros:** por **plano real** (el del anotador), en el punto medio del plano: vale
  lo que diga el plano del modelo que cubre ese instante. `unknown` cuenta como fallo en
  «acierto» y se excluye en «acierto sobre lo respondido»; las dos cifras se informan.
- Solo se puntúa el tramo que el análisis cubrió (`covered_to_s`), con el mismo límite para
  los cortes reales y los del detector.

## Test

`uv run --no-sync pytest packages/api/tests/test_eval_reel_shots.py -q` (sin red).
