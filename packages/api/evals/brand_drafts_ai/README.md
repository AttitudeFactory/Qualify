# Evaluación B1 — m-24854330

El cambio implementa la propuesta B1 detrás de `QUALIFY_ALTA_PREFILL_DRAFTS_ENABLED=0`.
No se ha medido con las 30 cuentas reales ni con las dos personas de la rúbrica.
No se habilita en producción hasta completar esa evaluación.

El comando `validate_predictions.py predictions.json` reproduce sin conexión la
validación de fuentes y la abstención por campo. No llama proveedores ni aprueba la
calidad del modelo. El archivo de predicciones y los textos reales se guardan fuera
del repositorio. El formato está en la ayuda del comando.

Pendiente para PB6-002: conjunto desarrollo 10 / prueba 20, dos evaluadores humanos,
κ, fidelidad, invenciones, abstención, utilidad y tono por campo; comparación del
rubro y etiquetas con y sin B1, p50/p95/máximo del gasto observado y recomendación de
encendido por campo. US$0,15 es una referencia experimental, no un límite comercial
aprobado; el bloqueo operativo autorizado el 2026-10-28 es US$5 por Alta.
