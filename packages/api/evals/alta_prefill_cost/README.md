# alta_prefill_cost: costo real de la precarga del Alta (PB-6, m-24852200)

Mide lo que cuesta una corrida de `prefill_brand_kit(..., propose=True)` con los `CallCaps` por defecto. Por cada cuenta registra:

- créditos de ScrapeCreators y los endpoints que llamó;
- cada corrida de Claude: modelo, prompt y tokens de entrada, salida, lectura y escritura de caché;
- el costo en dólares, la latencia y el resultado.

Cada cuenta se corre dos veces: **en vivo** (tenant nuevo, sin caché del perfil) y **con caché** (el mismo tenant otra vez).

**Gasta créditos y tokens reales**, así que se corre a mano y nunca en CI (pytest no recoge `run_*.py`). Corre **solo contra el stack local**: rechaza `QUALIFY_DEPLOY_ENV=production` y cualquier base de datos que no sea local. Crea un tenant desechable por cuenta y lo borra al terminar.

```bash
just eval-precarga --cases /ruta/fuera/del/repo/casos.json --out "$TMPDIR/pb6.json"
just eval-precarga --handles cuenta1,cuenta2 --max-usd 0.5
```

- `--cases` es una lista JSON `[{"handle": "...", "label": "heladería pública de Cúcuta"}]`.
- Las cuentas de terceros y los resultados crudos **no entran al repositorio**. En los documentos solo va la etiqueta genérica.
- `--max-usd` (por defecto 1) detiene la corrida antes de pasarse.
- En un worktree sin `.env`, pasar `--env-file /ruta/al/.env`. Lee solo `QUALIFY_ANTHROPIC_API_KEY` y `SCRAPECREATORS_API_KEY`, y nunca las imprime.

Resultados de 2026-10-25: [`docs/modelos-generativos/pruebas.md#pb6-001`](../../../../docs/modelos-generativos/pruebas.md#pb6-001).
