# Experimento — escenas de la imagen publicitaria

Mide la ruta de producción de la imagen publicitaria (`MediaProducer._ad_image`):

1. El prompt de la escena sale de `ad_scene_prompt`.
2. Seedream genera la escena al tamaño del formato, envuelto en `TracedProvider`.
3. `render_ad_slides` pone encima el hook y el CTA, y `to_meta_jpeg` deja el JPEG que
   acepta Meta.

El código solo comprueba tamaño, costo y tiempo. Lo que solo una persona puede juzgar va a
la cola de anotación **«Revisión de imagen y video»** de Langfuse:

- fidelidad al producto;
- coherencia de la escena;
- texto legible y dentro de la zona segura;
- artefactos.

La imagen terminada y la escena cruda se **adjuntan** a la traza. Aquí está permitido
porque las marcas son ficticias. Con medios de tenants, el plan (§9) no adjunta nada.

Gasta dinero real ($0.035 por imagen con Seedream 5.0 lite) y necesita el servidor de
Langfuse. Se corre a mano, nunca en CI:

```bash
just langfuse-up
just langfuse-setup        # una vez: crea la cola y sus escalas
just eval-escenas
```

## Casos (`cases.json`)

Diez escenas de las tres marcas ficticias de `../copy_ai/cases.json`, repartidas en todos
los formatos donde se ofrece la imagen publicitaria: feed 1:1, feed 4:5, story y reel.
Cada caso fija su hook y su CTA para que todos los modelos tengan las mismas palabras.

Todos los casos van en modo escena, sin fotos. Para probar los modos con foto, se agrega
`product_photo` o `background_photo` al caso, con una ruta relativa a esta carpeta.

En producción, la imagen publicitaria de un reel es un video: la imagen fija animada con
`animate_still`. El experimento juzga la imagen fija, que es de lo que está hecho el video.

## Resultado — 2026-10-14 (`results/20261014-070203.json`)

| Modelo | Imágenes | Errores | Tamaño exacto | Costo total | p50 s |
|---|---|---|---|---|---|
| `seedream-5.0-lite` | 10 | 0 | 10/10 | $0.35 | 38.4 |

El tiempo va de 30 a 75 segundos por imagen. La más lenta fue `bur-doble`, en feed 4:5.

**Pendiente: la revisión humana.** Las diez imágenes esperan puntuación en Langfuse →
Annotation queues → «Revisión de imagen y video». Sin esas puntuaciones el experimento
solo dice que Seedream entrega el tamaño correcto a tiempo, no que las imágenes sirvan.

Para verlas sin abrir cada traza, se bajan a `imagenes/` (en `.gitignore`), con la pieza
terminada, la escena cruda y una hoja de contacto (`_hoja-de-contacto.jpg`):

```bash
just eval-escenas-imagenes
```

Dos cosas a mirar en la revisión, vistas al bajarlas:

- **Espacio vacío para el texto, tomado al pie de la letra.** En `inm-llaves` (feed 1:1) la
  escena es una franja central, con una banda lisa arriba y un piso vacío abajo. En
  `inm-sala` (feed 4:5) el tercio superior queda blanco lavado. La causa probable es el
  prompt, que pide dejar «tranquilos» el cuarto superior y el quinto inferior para el
  texto.
- **Las personas no parecen latinoamericanas.** En `bur-partido` e `inm-llaves`, para
  marcas de Bogotá y Medellín, todas las personas tienen rasgos asiáticos. El prompt no
  dice nada del público, y Seedream es de ByteDance.

Las dos son cambios de producción en `ad_scene_prompt` y no se tocaron aquí.

Cuando haya candidatos nuevos, se agregan a `CONFIGS` en `qualify_api.evals.ad_scenes`;
el orden lo da `docs/comparativa-apis-creativo-motor-angulos.md` §7.
