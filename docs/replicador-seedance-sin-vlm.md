# Replicar un reel con Seedance, sin VLM

Trabajo local de **m-24820836**. Decisión del 2026-10-27: posponer el análisis VLM de m-24820834 y probar la referencia directa de video con Seedance.

«Replicar con mi marca» prepara el video original y abre **Clip**, paso 1, con el producto seleccionado y sus datos clave. El contexto incluye los metadatos disponibles: texto, transcripción, sonido, formato y gancho. No vuelve a llamar a ScrapeCreators, no produce un blueprint ni inventa planos o timestamps. El copy se adapta con el Brand Kit; la secuencia visual procede del video original.

La referencia toma hasta los primeros **5 segundos**, sin audio, en H.264 y conservando sus proporciones (máximo 1280 px por el lado mayor, al menos 407.696 píxeles y 300 px por lado; entre 24 y 60 fps). Se descarga solo de los CDN de la red, sin seguir redirecciones y con tope de 80 MiB. Se guarda como un archivo de entrada en el espacio del tenant, igual que una subida. Es la base de edición: no se usa como fotograma inicial/final ni se entrega directamente como resultado. Una URL caducada mantiene la selección y permite reintentar. Abrir el formulario no consume una vista previa; Generar y aprobar siguen el cobro existente.

Por indicación del usuario, la réplica usa los primeros **5 segundos**. Seedance 2.5 recibe `omni_reference_task_type=edit`, `ratio=adaptive` y `duration=-1`: conserva el lienzo y la duración de la entrada. Las fotos del producto se envían como referencias de apariencia, nunca como fotogramas inicial/final. El prompt conserva planos, montaje, cámara, acciones y etapas de preparación; sustituye producto e identidad sin trasladar el fondo de la foto del catálogo. No usa el guion genérico de tres tomas ni inventa un cierre publicitario. La transcripción nunca se coloca en «Escribir mi propio guion».

El modo queda guardado como `media.clip_reference_mode=edit`; los Clips normales y los briefs anteriores mantienen `motion`. Una edición exige un único video y fotos del producto, sin fotogramas forzados ni audios de referencia. Una entrada ilegible o de duración incompatible se rechaza antes de enviar el video al proveedor. Los drafts continúan en 480p, sin aprobación automática. Una edición generativa puede introducir diferencias: la revisión visual sigue siendo necesaria.

## Prueba manual

1. Elegir un producto del catálogo y abrir Descubrir reels.
2. Pulsar Replicar con mi marca en un reel con MP4 disponible.
3. Comprobar que aparece Clip, paso 1, conservando producto y datos clave, con el reel como base y las fotos como referencias de apariencia.
4. Revisar Contexto: el texto del original es material para adaptar, no el guion de la marca.
5. Generar una vista previa con Seedance 2.5 y comparar planos, acciones y ritmo con el original; revisar el producto y la identidad. Aprobar el final solo si la vista previa sirve.

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

## Corrección de fidelidad — 2026-10-27

La primera prueba tomó la referencia como inspiración y creó otra secuencia. El usuario pidió conservar el original con su producto y su marca. Se cambió únicamente la ruta de réplica al modo de edición de Seedance 2.5; los Clips comunes mantienen su comportamiento.

Nueva pieza local: `9d4bb76a-5af1-4e32-b7c3-8c76cb225ff9`, tarea `cgt-20261027230039-u8q4c`, mismo reel de Smash Hiro y mismo producto smash doble de Nibbles. Draft 480p, 480 × 854, 24 fps y **4,708333 s** para una entrada de 5 s; sin aprobar. Seedance registró USD 0,596941. Se compararon cinco fotogramas por video: conserva mesa negra, manos, carne y colocación del queso. Cambia el inicio mostrando primero el pan y adelanta algo las acciones; no es una copia exacta. La etapa de armado de estos primeros cinco segundos tampoco permite comprobar el aspecto del producto completamente terminado.

Se aplicó el imagotipo existente de Nibbles mediante la composición local habitual, sin otra generación de Seedance. El medio de la pieza y su poster están guardados en el almacenamiento del tenant; el draft original anterior se conserva. Copia local: `uploaded_files/generated/9cd9637c-8bd0-4293-9d68-40a71c140c00/9d4bb76a-5af1-4e32-b7c3-8c76cb225ff9/replica-fiel-smash-hiro-5s-draft.mp4`.

## Referencias accesibles y tipos de video

El error de la pieza `72d7e48a-eeeb-4828-b480-5e975c396079` fue `resource download failed`: la URL pública temporal no podía servir la referencia. Ahora se comprueban estado HTTP, tipo y longitud del archivo antes de enviar el trabajo de video al proveedor. La comprobación no genera otro video; no evita un cambio de conectividad posterior.

Para desarrollo local, `uv run uvicorn qualify_api.http.media_server:app --host 127.0.0.1 --port 8016 --env-file .env --no-access-log` sirve únicamente medios por token. El túnel HTTPS debe apuntar a ese puerto y permanecer activo durante la generación. Configurar su origen en `QUALIFY_PUBLIC_MEDIA_BASE_URL` y reiniciar Reflex cuando cambie. Detener el túnel invalida ese acceso aunque la variable siga definida.

La galería muestra el tipo de creación guardado en el brief y permite filtrarlo, distinguiendo avatar humano, avatar animado y Clip incluso si la generación falla. El detalle también muestra el tipo durante la espera o el error. Este dato es independiente del formato de publicación (Reel, imagen, etc.) y no necesita una migración.
