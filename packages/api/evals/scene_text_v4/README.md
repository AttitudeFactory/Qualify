# Experimento — la escena de Seedream sin letras ni botones (m-25017275)

Compara el compilador de prompts 3 con el 4 sobre los mismos encargos, las mismas fotos de
referencia y el mismo tamaño. El compilador 4 pide una fotografía limpia: sin texto nuevo,
sin botones ni elementos gráficos encima, y solo las letras que ya traen el producto real,
su empaque y el logo entregado.

- Los prompts salen de las funciones de producción: `ad_scene_prompt` para la imagen
  publicitaria y `carousel_scene_prompt` para cada diapositiva de una galería.
- Se genera solo la **escena cruda** con `SeedreamImageAdapter` y el modelo por defecto
  (`DEFAULT_SEEDREAM_MODEL`). No se compone nada.
- **Nada se guarda en R2 ni en la base.** Las imágenes, los prompts y la bitácora de gasto
  (`ledger.jsonl`) quedan en la carpeta `--out`, en el disco local.
- Cada POST pasa por `LedgerTransport` con la tabla de precios `v9`. La llamada que pasaría
  `--max-usd` no sale. La bitácora suma también lo gastado en corridas anteriores.

Gasta dinero real (US$0,045 por imagen de hasta 2,36 MP, más US$0,003 desde la segunda
referencia). Se corre a mano, nunca en CI:

```bash
PYTHONPATH=packages/api/src:packages/shared/src:packages/creative/src \
  uv run --no-sync python packages/api/evals/scene_text_v4/run.py \
  --inputs <carpeta local>/manifest.json --out <carpeta local>/out \
  --env-file .env --max-usd 3 [--reps 1 --rep-start 1] [--only F1-ubicacion] [--dry-run]

uv run --no-sync python packages/api/evals/scene_text_v4/contact_sheet.py <carpeta local>/out
```

`manifest.json` asigna cada foto de `cases.json` (`shawarma_carne`, `combo_carne`,
`isotipo`…) a un archivo local. Las fotos de clientes **no entran en git**: se leen de
R2 solo para lectura y quedan fuera del repositorio.

`--dry-run` compila los 24 prompts y cotiza la corrida sin llamar a nadie.

Resultado y puntuación: `docs/modelos-generativos/pruebas.md#escena-sin-letras-001`.
