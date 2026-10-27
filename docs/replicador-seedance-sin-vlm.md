# Replicar un reel con Seedance, sin VLM

Trabajo local de **m-24820836**. Decisión del 2026-10-27: posponer el análisis VLM de m-24820834 y probar la referencia directa de video con Seedance.

«Replicar con mi marca» prepara una referencia de movimiento y abre **Clip**, paso 1, con el producto seleccionado y sus datos clave. El contexto incluye los metadatos disponibles: texto, transcripción, sonido, formato y gancho. No vuelve a llamar a ScrapeCreators, no produce un blueprint ni inventa planos o timestamps. El generador adapta el guion con el Brand Kit cuando el operador pulsa Generar.

La referencia toma hasta los primeros **5 segundos**, sin audio, en H.264 y conservando sus proporciones (máximo 1280 px por el lado mayor, al menos 407.696 píxeles y 300 px por lado; entre 24 y 60 fps). Se descarga solo de los CDN de la red, sin seguir redirecciones y con tope de 80 MiB. Se guarda como un archivo de entrada en el espacio del tenant, igual que una subida. Solo sirve como movimiento: no se usa como fotograma inicial/final ni como video de salida. Una URL caducada mantiene la selección y permite reintentar. Abrir el formulario no consume una vista previa; Generar y aprobar siguen el cobro existente.

Por indicación del usuario, el Clip abre con duración de **5 segundos** y formato 9:16. El operador puede editar las referencias y el contexto antes de generar. La transcripción nunca se coloca en «Escribir mi propio guion».

## Prueba manual

1. Elegir un producto del catálogo y abrir Descubrir reels.
2. Pulsar Replicar con mi marca en un reel con MP4 disponible.
3. Comprobar que aparece Clip, paso 1, conservando producto y datos clave, con el reel como Movimiento.
4. Revisar Contexto: el texto del original es material para adaptar, no el guion de la marca.
5. Generar una vista previa con Seedance 2.5 y revisar producto, movimiento y texto. Aprobar el final solo si la vista previa sirve.

Usa la configuración existente de Seedance y de URL pública de medios en `docs/modelos-generativos/seedance-2-5.md`. La generación real tiene costo y puede devolver las restricciones del proveedor sobre caras reales. Esta implementación no transforma un reel para eludirlas.

La presentación de procedencia como sección propia del detalle sigue en **m-24820837**. El enlace y el identificador del reel ya viajan en el contexto guardado del brief. El nuevo flujo de Ideas para tus reels (R14, m-24854860) seguirá usando sus lecturas persistentes; este cambio trabaja sobre las tarjetas actuales de Discovery.


## Prueba local real — 2026-10-27

- Tenant local: **nibbles burger**, `9cd9637c-8bd0-4293-9d68-40a71c140c00`.
- Producto: **smash doble**, del catálogo existente.
- Reel elegido: [«LA GOTY sigue aquí», @smash_hiro](https://www.instagram.com/reel/DeZIKSUNIea/). Los primeros 5 s muestran el montaje del producto con manos, sin caras.
- Pieza guardada, sin aprobar: `4fde27b4-0cb6-4d4e-a231-14f646f44b60`.
- Tarea Seedance: `cgt-20261027214457-b2fz9`, estado `succeeded`.
- Resultado: draft 480p, 480 × 854, 24 fps, 5,041667 s, una sola variante. Costo registrado de Seedance: USD 0,617440 (no incluye copy).
- La pieza está en la BD local y su medio en el almacenamiento normal del tenant. También se guardó una copia en `uploaded_files/generated/9cd9637c-8bd0-4293-9d68-40a71c140c00/4fde27b4-0cb6-4d4e-a231-14f646f44b60/replica-smash-hiro-5s-draft.mp4`.

El primer intento (`080f81ca-48de-4203-a8c1-8fc32b45714c`) fue rechazado por ModelArk por resolución de entrada insuficiente. Se corrigió la preparación para respetar el mínimo de **407.696 píxeles**; se validan también proporción y FPS contra los [requisitos oficiales](https://docs.byteplus.com/en/docs/ModelArk/seedance-2-5). Se añadió una regresión del tamaño que falló y la referencia corregida completó la generación.

Validación: 9.791 tests offline pasaron antes del ajuste de resolución; después, 49 pruebas específicas pasaron, incluida la regresión del hallazgo en vivo. Ruff y su formato en verde; compilación Reflex dry-run completada. No se aprobó el render final, no se publicó contenido y no se abrió un PR.
