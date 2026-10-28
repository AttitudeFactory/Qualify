# Revisión local de la propuesta de marca y B1

Revisión independiente del 28 de octubre de 2026 sobre los componentes reales de Reflex,
con datos ficticios de «Heladería Polar». La vista temporal se sirvió en
`http://localhost:3492/` y `http://localhost:3492/answers`.

No se usaron cuentas reales, base de datos, scraping, modelos ni almacenamiento R2 real.
La lectura de imágenes y el guardado se simularon en la vista local.

## Capturas

- [Propuesta en celular, 360 × 800](qualify-independent-ux-mobile-top.png).
- [Propuesta en escritorio, 1440 × 1000](qualify-independent-ux-desktop.png).
- [Cuenta sin publicaciones, 360 × 800](qualify-independent-ux-empty.png).
- [Borrador de respuesta y tono, 360 × 1000](qualify-independent-ux-b1-before.png).

## Verificaciones

- Las seis miniaturas cargan de verdad: `naturalWidth = 480`; no basta contar etiquetas `img`.
- Sin desplazamiento horizontal en celular; cajón de corrección de 360 × 800.
- El campo del cajón tiene una etiqueta HTML asociada; guardar conserva la propuesta pendiente.
- Cancelar conserva el dato previo; los cambios muestran «Lo corregiste tú».
- Al rechazar la foto como logo, aparece «Tu logo: por elegir».
- El teléfono llega enmascarado al navegador y no aparece como un enlace de WhatsApp inválido.
- Sin publicaciones no se muestran cuadrícula, frecuencia ni cifras en cero.
- B1 permite confirmar las dos primeras respuestas y llegar a la tercera pregunta.
- Confirmar la frase deja el tono pendiente de su propia confirmación.
- La vista previa del tono es texto etiquetado de solo lectura; al confirmarlo,
  los controles toman los valores propuestos: 70, 65, 80 y 20.

## Comandos de esta revisión

```sh
# Pruebas de los componentes; no requieren servicios externos.
uv run --no-sync pytest Qualify/test_brand_proposal.py Qualify/test_brand_answers.py -q

# Automatización utilizada con la vista temporal de esta sesión.
node /private/tmp/qualify-independent-ux-review.cjs
```

La vista temporal y el script del segundo comando son recursos locales de esta sesión,
no una aplicación ni una prueba distribuida con el repositorio.

## Alcance y límites

Las capturas documentan los componentes y sus interacciones con almacenamiento simulado.
No prueban el registro, la autenticación, la persistencia real, la entrega de invitaciones
ni la calidad de las inferencias de B1. La navegación y el título de pestaña pertenecen
a la vista de prueba; no se certificó la navegación completa de `/brand` en una sesión real.
B1 sigue sujeto a su evaluación de calidad antes de encenderlo.
