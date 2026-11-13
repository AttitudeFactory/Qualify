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

`--dry-run` compila los prompts y cotiza la corrida sin llamar a nadie (28 imágenes con la
pareja 3-4 desde que existe `G3-galeria-datos`; eran 24).

Resultado y puntuación: `docs/modelos-generativos/pruebas.md#escena-sin-letras-001`.

## Foto base: compilador 4 contra 5 (m-25017279, sin correr)

El compilador 5 pide solo la foto base: quita de lo que lee Seedream los «Datos clave» y
los nombres de las tipografías de la marca (la diapositiva de gancho sin logo dibujó
«UNUBND», 2 de 2, con el compilador 4; m-25019811). `--versions 4 5` corre la pareja sobre
los mismos encargos. `G3-galeria-datos` es `G2` (gancho sin logo) con «Datos clave»
(precio, 2x1, horario); entre las imágenes, F1, F3, F4 y F7 traen dirección, horario,
precio y 2x1.

Diseño mínimo — 16 imágenes, US$0,732 con la tabla v9 (US$0,045 por imagen + US$0,003 por
referencia extra):

```bash
uv run --no-sync python packages/api/evals/scene_text_v4/run.py \
  --inputs <carpeta local>/manifest.json --out <carpeta local>/base_v5 \
  --env-file .env --max-usd 1 --versions 4 5 --reps 1 \
  --only F1-ubicacion F3-horario F4-combo F7-pollo-2x1 G2-salchipapa-galeria G3-galeria-datos
```

Diseño completo — los 11 encargos, 2 repeticiones: 56 imágenes, US$2,592
(`--versions 4 5 --reps 2 --max-usd 3`).

**Corrido el 2026-11-13**: diseño completo, 56 imágenes, US$2,637. Resultado en
`docs/modelos-generativos/pruebas.md#foto-base-001`. Hoja de contacto de la pareja:
`contact_sheet.py <out> --versions 4 5`.

**Renumerado al unir con `main` (2026-11-14).** Mientras se medía, `main` publicó su propio
compilador 5 (m-24985141: redacción general para todo tipo de negocio y piezas sin
producto). La foto base pasó a ser el **compilador 6** = el 5 de `main` + quitar «Datos
clave» y tipografías. Los 28 prompts del 4 que se midieron son idénticos byte a byte a los
de hoy; los 28 del «5» medido **no** lo son con el 6 que sale: cada uno difiere solo por la
redacción general de `main` («appetizing» → «appealing», «the food» → «real subjects, such
as people, materials…», «ingredients» → «parts and detail», entre otras). Quitar los datos y
las tipografías es igual en los dos. Para medir exactamente lo que sale: `--versions 5 6`.
