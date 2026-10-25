# robertuito — sentimiento de comentarios y menciones

| Campo | Valor |
|---|---|
| Proveedor | Local (Hugging Face `transformers`, CPU), sin llamadas a terceros: el texto no sale del servidor |
| Modelo | `pysentimiento/robertuito-sentiment-analysis` · sin revisión fijada (`model_revision=None`) · `DETECTOR_VERSION` `robertuito-sentiment-v1` |
| Clases | `POS` / `NEG` / `NEU` |
| Límite de entrada | **128 tokens** (`tokenizer.model_max_length`; 130 posiciones contando el desfase de RoBERTa). Desde m-24852236 el texto se trunca a los primeros 128 tokens |
| Uso en Qualify | `qualify_models.providers.LocalRobertuitoSentimentProvider` → `sentiment.SentimentService` (comentarios, automático desde m-24852204) y `mentions.sentiment.MentionSentimentService` |
| Licencia | El Hub no declara licencia para `pysentimiento/robertuito-*` (verificado 2026-07-23; ver `docs/modelos-multimodal-fase1.md`). Pendiente de resolver, heredado |
| Costo | US$0 por comentario (CPU del VPS); el costo es tiempo de CPU |

## Prueba ROB-TRUNC-001 — 2026-10-24 (m-24852236)

- **Quién:** Claude Code (data-scientist-fde), por el error encontrado sembrando una demo local.
- **Qué se probó:** la llamada anterior (`pipeline(texto)`, sin truncar) contra la nueva
  (`pipeline(texto, truncation=True, max_length=128)`), mismos pesos, CPU, `transformers` 5.17.0,
  pesos en caché (`HF_HUB_OFFLINE=1`).
- **Material:** los 408 comentarios reales del golden set de intención
  (`packages/api/eval_data/intent_golden_v1.jsonl`, español de negocios hispanohablantes) y un
  comentario sintético de 134 tokens (40 comentarios del set unidos).

| Medida | Valor |
|---|---|
| Longitud en tokens (mediana / p95 / máx.) | 7 / 29 / 164 |
| Comentarios reales de más de 128 tokens | **2 de 408 (0,5 %)** |
| Llamada anterior sobre esos 2 | **falla** (`RuntimeError` en CPU; `AcceleratorError` en MPS; `IndexError` según la versión) |
| Llamada nueva sobre los otros 406 | etiqueta **406/406 idéntica**, puntaje idéntico (diferencia < 1e-6) |
| Llamada nueva sobre los largos | clasifica (el sintético: `NEU` 0,51) |
| Tiempo | 32 s para las 816 inferencias (≈ 40 ms por comentario, Mac M-series en CPU) |

**Resultado:**

- Con 0,5 % de comentarios largos, una tanda de 100 (la del análisis automático) trae al menos uno
  con probabilidad ≈ 1 − 0,995¹⁰⁰ ≈ **39 %**. Antes del arreglo, esa tanda fallaba entera y volvía
  a fallar en cada pasada, porque el comentario largo seguía pendiente.
- Truncar no cambia nada en los textos que caben: **no se cambia la versión de análisis**
  (`current_analysis_version()`). Los comentarios largos nunca tuvieron un resultado guardado, así
  que no hay filas viejas que queden con otro significado; se analizan en la próxima pasada bajo
  la misma versión.
- Límite conocido: en un comentario largo solo cuentan los primeros 128 tokens. Para comentarios
  de redes es aceptable (p95 = 29 tokens); para menciones con textos largos (subtítulos,
  transcripciones) habría que medir si conviene promediar por fragmentos antes de cambiarlo.
- Además, `SentimentService` ya no deja que un comentario que falle tumbe la tanda: se registra
  `message_id` + clase del error (nunca el texto) y el resto se analiza.

## Prueba SENT-HAIKU-001 — línea base contra Claude Haiku 5.5 (m-24854495) — 2026-10-25 · PENDIENTE

- **Por qué:** el fundador decidió el 2026-10-25 (opción C) pasar el sentimiento a Claude Haiku 5.5. robertuito queda apagado por defecto en producción (PR #340) y se usa como **línea base** de la medición: Haiku tiene que igualar o superar su macro-F1 en `test`.
- **Cómo corre:** `just eval-replies --sentiment --robertuito [--no-haiku]`, local en CPU con el grupo `ml`, revisión `a2cc0f67ebd705c55191e25a05ba23d885fcc09b` (leída del `config._commit_hash` de los pesos en caché), un comentario a la vez y cronometrado por lotes de 25 para comparar la latencia con la de Haiku. Los pesos se cargan antes de empezar a medir.
- **Prueba de humo (2026-10-25):** 10 comentarios públicos, 0,07 s (p50) por lote de 5, US$0. Coincidió con Haiku en 8 de 10.
- **Estado:** pendiente de etiquetas. Ver la [entrada SENT-HAIKU-001 de la bitácora](pruebas.md#sent-haiku-001).
