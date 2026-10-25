# Guía para etiquetar el sentimiento de comentarios

Ticket m-24854495 · versión 1 · 2026-10-25

Vas a leer comentarios que la gente deja en publicaciones de Instagram y Facebook de pequeños negocios (comida, servicios, inmobiliaria, turismo). Para cada uno decides **qué tono tiene quien comenta hacia el negocio**. Con tus etiquetas se mide si Qualify acierta antes de mostrarle ese dato a los dueños.

## Cómo llenar la hoja

| Columna | Qué escribir |
|---|---|
| `sentimiento` | **POS**, **NEG** o **NEU**. Obligatoria. |
| `sarcasmo` | **si** cuando el comentario dice lo contrario de lo que quiere decir. Vacía si no. |
| `dudoso` | **si** cuando dudaste entre dos etiquetas. Vacía si no. |
| `nota` | Opcional, corta: por qué dudaste. |

- **Trabaja sola o solo.** No compares con tu compañero ni le preguntes a una IA: se mide justamente si dos personas coinciden sin ponerse de acuerdo.
- No cambies el orden ni la columna `id`. Las menciones aparecen como `@usuario` y los teléfonos como `[teléfono]`: es a propósito.
- Calcula unos 20 a 30 segundos por comentario. Si uno te toma más, marca `dudoso`, elige la que mejor te parezca y sigue.
- Haz pausas cada 100 comentarios; el cansancio también cambia las etiquetas.

## Las reglas

- **S1. El tono hacia el negocio.** POS: elogio, agradecimiento, entusiasmo, ganas de ir o de comprar («qué rico», «los amo», «gracias», «tengo que ir»). NEG: queja, reclamo, molestia, desconfianza, burla o mala reseña, **aunque sea educada**. NEU: todo lo que no tiene tono claro.
- **S2. Sarcasmo.** «Excelente servicio, tres horas esperando» es **NEG** y se marca `sarcasmo = si`. Si no sabes si es sarcasmo, marca `dudoso`.
- **S3. Solo emojis.** ❤️ 😍 🔥 👏 🤤 🙌 son **POS**. 😡 👎 🤮 😒 son **NEG**. 😂 sola, 👀, 🤔 o emojis que no dicen nada del negocio son **NEU**.
- **S4. Preguntas.** Una pregunta sin tono es **NEU** («¿precio?», «¿dónde quedan?», «info»). Con elogio es **POS** («¡qué belleza! ¿cuánto cuesta?»). Con molestia es **NEG** («¿hasta cuándo esperando el pedido?», «¿nadie responde?»).
- **S5. Quejas.** Todo reclamo al negocio es **NEG**: pedido, demora, trato, calidad, precio («carísimo»), no responder, desconfianza («¿esto es estafa?»).
- **S6. Mezclas.** Si hay elogio y una queja concreta, gana la queja: «muy rico pero llegó frío» es **NEG**. Un «pero» sin queja real («caro pero vale la pena») es **POS**.
- **S7. Etiquetar a otra persona.** Se juzga el tono del texto. «@usuario mira» es **NEU**. «@usuario vamos, se ve buenísimo» es **POS**. «@usuario ya no es lo que era» es **NEG**.
- **S8. Solo el texto.** No supongas lo que muestra la publicación ni quién comenta. Spam, publicidad de otros o texto sin sentido son **NEU**. En otro idioma, etiqueta por el significado.

## Qué pasa con tu hoja

Unos 100 comentarios los etiquetan las dos personas. Con ellos se calcula cuánto coinciden (κ de Cohen; hace falta 0,70 o más). Si no se llega, se ajustan estas reglas y se vuelve a etiquetar. Cuando dos etiquetas no coinciden, decide una tercera persona. Ninguna etiqueta la pone Claude ni ningún modelo.
