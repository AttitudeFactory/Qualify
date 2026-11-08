# Medición de «Proponerme las partes» (VE-14, m-24921071)

Corre el camino de producción (`qualify_api.creative.parts_ai.propose_parts`, con su guarda
de precio y su tope por llamada) sobre briefs **reales** de una frase y lo puntúa en Langfuse
(dataset `proponer-partes`). Gasta dinero real: solo con autorización del fundador.

```bash
just langfuse-up
just eval-partes --dry-run          # cuenta los casos y cotiza el peor caso; no envía nada
just eval-partes --cap-usd 1.50     # la corrida; deja de llamar al llegar al tope
```

## Casos (`cases.json`, ignorado por git)

20 frases reales de los negocios del fundador (Bianki, Polette, la agencia de viajes), tal
como el dueño respondería «¿De qué trata tu video?». **Nada inventado** (`qualify-measure`):
si no hay 20 reales, se mide con las que haya y se dice cuántas. Sin datos personales de
clientes (teléfonos, correos, nombres de compradores).

```json
{"cases": [
  {"id": "bianki-01", "business": "bianki", "story": "<la frase real>", "target_seconds": 20,
   "product": {"name": "<del catálogo>", "description": "<del catálogo>", "photos": 2},
   "brand": {"name": "Bianki", "sector": "", "palette": ["#..."], "typeface": ""}}
]}
```

## Puntajes

Por propuesta: `partes_en_rango` (3–6), `segundos_totales`, `desvio_duracion`, `sin_precios`,
`sin_texto_en_pantalla`, `partes_distintas` (Jaccard < 0,6), `cierre_invita` (aproximación
del arco comienzo→cierre; el arco se revisa a mano), `costo_usd`, `latencia_s`, `fallo`.
Por corrida: `propuestas_usables`, `fallos`, costo medio/máximo/total y latencia p95.
Resultados en `results/<fecha>.json` y en `docs/modelos-generativos/`.
