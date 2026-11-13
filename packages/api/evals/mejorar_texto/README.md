# «Mejorar mi texto» — ¿se repite lo que propone?

m-25017274. `run_experiment.py` pasa los seis textos FICTICIOS de `cases.json` (un local de
shawarma y ensaladas: promoción 2x1, producto nuevo, horario, combo con precio, domicilios y
una escena de imagen) por `context_ai.enhance_context`, pulsando el botón dos veces por
texto, y mide cuánto se repiten las respuestas.

- Prompt `context-v3-*` (un texto que REEMPLAZA el campo): la segunda pulsación reescribe la
  salida de la primera, como hacía la pantalla.
- Prompt `context-v4-*` (tres versiones; el original se conserva): la segunda pulsación es
  «Otra versión»: el texto original otra vez y las versiones ya mostradas.

Similitud = `difflib.SequenceMatcher.ratio` sobre el texto en minúsculas (1,0 = idéntico),
junto al Jaccard de palabras. «Números nuevos» = cifras en una respuesta que no estaban en
el texto (aproximación barata a un precio u hora inventados). El costo sale de los registros
de consumo de las propias llamadas (a una lista en memoria, nunca a la base).

```bash
just eval-mejorar-texto --env-file /ruta/al/.env --label v4 --cap-usd 0.40
```

Desde `context-v5-*` (MEJORAR-TEXTO-002) hay 6 escenas con precio en «Datos clave»
(`--only escena-precio`) y la medida «pide texto en la imagen»; `--module-file` corre un
`context_ai.py` anterior (p. ej. `git show origin/main:…`) para la línea de base.

Gasta dinero real (≈ USD 0,08 por corrida de 12 llamadas con v4). Resultados en `results/`;
el análisis está en `docs/modelos-generativos/pruebas.md` (2026-11-13) y en la ficha
`docs/modelos-generativos/claude-sonnet-5-5.md`.
