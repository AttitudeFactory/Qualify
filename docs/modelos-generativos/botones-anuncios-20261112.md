# Contrato de botones publicitarios — 2026-11-12

Cambio m-24828975, contrato `piece-ad-destination-v1`. No cambia modelo, proveedor,
temperatura ni límites de gasto. El esquema de salida deja de admitir un botón libre y
las instrucciones enumeran once valores. La elección sigue dependiendo del rubro y
objetivo, con `LEARN_MORE` como opción por defecto.

## Evidencia disponible

Antes, `CopyPayload.ads_cta_type` era texto libre y las instrucciones decían «string».
Ahora el JSON Schema contiene `AdCTA`. Los textos almacenados previamente se proyectan
sin modificar los registros; el editor y las respuestas nuevas se validan estrictamente.

El enlace se excluye del esquema del modelo y no se incluye en el texto del prompt. Una
prueba del servicio introduce un enlace inventado no HTTPS en una respuesta sintética:
se guarda exclusivamente el valor declarado en la marca. Otra prueba cambia la marca
y genera de nuevo una pieza editada: conserva el enlace elegido por el dueño.

Pruebas reproducibles sin proveedor:

```sh
uv run --no-sync pytest packages/creative/tests/test_ad_destination.py \
  packages/api/tests/test_piece_ad_fields.py \
  packages/creative/tests/test_render_prompt.py \
  packages/creative/tests/test_anthropic_adapter.py -m "not db and not integration"
```

Estas son pruebas deterministas del contrato y de la procedencia, **no una evaluación
de calidad de un modelo**. No usan ejemplos de clientes como conjunto dorado ni
producen una tasa de acierto por botón. No se simuló una evaluación real con respuestas
prefijadas para atribuirle calidad al modelo.

## Medición pendiente y coste

No se ejecutó un experimento pagado ni una llamada a Claude, BytePlus o Meta. Coste de
proveedor de esta comprobación: cero. Una medición posterior de la calidad de elección
debe comparar la versión previa y esta con el mismo conjunto anonimizado de casos
reales, separar desarrollo y prueba, y publicar acierto por botón, errores y coste por
pieza. No se cambia la decisión de proveedor ni se promete una mejora sin esa medición.

La prueba real del asistente de anuncios y los permisos de la cuenta pertenecen a los
criterios operativos de la épica. Guardar un botón de WhatsApp o una reserva no habilita
por sí mismo ese destino en el flujo productivo actual.
