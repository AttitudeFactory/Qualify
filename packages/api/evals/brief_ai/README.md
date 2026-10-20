# Experimento — lectura de documentos del Brand Kit

Mide la ruta de producción que lee un documento de marca y propone cambios al kit:
`read_document` y luego `propose_kit_changes` (`qualify_api.creative.brief_ai`), con las
cuatro comprobaciones de `verify_proposal`, contra un kit vacío. Las métricas viven en
`qualify_api.evals.brief_reading` y tienen tests offline.

Gasta dinero real (centavos) y necesita el servidor de Langfuse. Se corre a mano, nunca
en CI:

```bash
just langfuse-up
just eval-documentos
just eval-documentos --configs sonnet-5.5@medium
```

Los resultados quedan en Langfuse, en Datasets → `brand-kit-documentos`, y aquí en
`results/`.

## Casos (`cases.json`)

Ocho documentos de marcas **ficticias** escritos para este experimento. Ninguno es de un
tenant. Tienen formas distintas a propósito:

- Briefs con secciones y documentos en prosa.
- Un manual con el lema de un competidor como trampa (`cafe-especialidad`).
- Uno sin afirmaciones prohibidas (`panaderia-sin-restricciones`).

`expected` define, por campo, lo que el documento dice. Una lista vacía significa que el
documento no dice nada de ese campo: cualquier propuesta ahí es inventada.

## Métricas

- **cobertura**: campos esperados que recibieron propuesta.
- **recall / precisión de ítems**: en los campos de lista, ítems encontrados e ítems
  propuestos que sí estaban en el documento.
- **inventados**: propuestas para un campo del que el documento no habla. Es el error
  que más daña, porque el kit termina diciendo algo que la marca no dijo.
- **citas verificadas**: propuestas cuya cita aparece literal en el documento.
- **costo** por documento y **segundos** p50.

## Resultado — 2026-10-14 (`results/20261014-065810.json`)

Una corrida por configuración.

| Configuración | Cobertura | Recall | Precisión | Citas verificadas | Inventados | $/doc | p50 s |
|---|---|---|---|---|---|---|---|
| **`claude-sonnet-5` @ medium (producción)** | **0.982** | **0.979** | **0.984** | 0.979 | **0** | 0.0086 | 6.8 |
| `claude-sonnet-5-5` @ medium | 0.961 | 0.958 | 0.954 | **1.000** | 1 | 0.0087 | **5.6** |

Lectura:

- **Producción se queda en Sonnet 5 @ medium.** Cuesta lo mismo y es mejor en todo,
  menos en citas verificadas.
- Sonnet 5.5 inventó una propuesta en `cafe-especialidad`, un campo que el documento no
  llena. Ese manual es justo el que lleva la trampa del lema ajeno.
- Los dos pierden lo mismo en `inmobiliaria-prosa`: el documento en prosa es el más
  difícil de leer para ambos.
- La única ventaja de Sonnet 5.5 es la latencia, y en una acción que el usuario lanza una
  vez por documento no compensa un campo inventado.
