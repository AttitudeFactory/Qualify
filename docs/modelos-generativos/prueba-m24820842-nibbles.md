# Prueba m-24820842 — Nibbles y contrato de recursos

Prueba real del 29–30 de octubre de 2026, negocio local `nibbles burger`, tenant `9cd9637c-8bd0-4293-9d68-40a71c140c00`, marca `a034e7a8-969e-4974-9d11-3ff5d3ee4cf1`; pipeline `creative-v1`, PR #412. El usuario autorizó expresamente usar sus fotos/logos en el modelo actual que cede datos a BytePlus, sólo esta tanda con máximo total USD 3, y después corregir únicamente la marca del video. No modifica la política de otros clientes. Sin publicación ni final 1080p.

## Entradas y ejecución

Foto principal del producto `super smash` (`fde5a706-51c2-4fbe-a869-7d78bc07b58e`). Galería/volante y corrección usan el **imagotipo** horizontal guardado, archivo `8161eb54e9c64eea873bcc89b7f7fb3c_isologo.png`, huella `12ab73e…cc66`: la categoría procede del espacio del Brand Kit, no del nombre del archivo. El primer clip usó el **isologo** del cartel rojo (`0352c745…jpg`, `4a9457…6a63`). Notas vacías; sin mascotas/elementos adicionales.

Fuente: [reel De98nhStqk1 de @smash_hiro](https://www.instagram.com/reel/De98nhStqk1/), guardado previamente, 720×1280, 30 fps, 5,000 s; SHA-256 `098ffc63d0d26484c82a775251346bf68ec0d3d1207e64568fad12f77c4aa675`. Sin nueva consulta a ScrapeCreators ni VLM.

`ContentService` y proveedores reales: Claude `claude-opus-5-5`, 4096 tokens máximos, una variante, sin reparación/fallback/reintento; Seedream `seedream-5-0-lite-260128`, cuatro escenas JPEG (1728×2160 y fotograma 1728×2304); Seedance `dreamina-seedance-2-5-260628`, borradores 480p sin audio. La [documentación oficial](https://docs.byteplus.com/en/docs/ModelArk/seedance-2-5) exige editar con proporción adaptativa y duración `-1`, heredando la referencia. La última reserva acotó sólo la estimación a la fuente inmutable de 5 s más 5 s de entrada: USD 0,614880; petición enviada con `-1`, reserva USD 1,30, máximo acumulado reservado USD 2,6718086.

## Uso y costo final observado

| Proveedor | Uso | USD calculados con v7 |
|---|---|---:|
| Claude | 3 llamadas; 4023 tokens entrada, 2744 salida, 5999 creación de caché, 11998 lectura | 0,103367 |
| Seedream | 4 imágenes | 0,140000 |
| Seedance | 3 tareas; 236217 tokens | 1,725383 |
| **Total redondeado** | | **1,968750** |

Ledger sin redondeo: USD 1,9687496. Uso del proveedor y tabla `v7`, no comprobación de factura. El texto del intento `d05d9c01-51e4-4641-83e1-429080fa70d8` se cobró una vez y se reutilizó con procedencia/`operator_reuse`; ningún texto ni imagen adicional para los videos posteriores. Ese intento no envió video: una reserva incorrecta de USD 1,30 chocó con la estimación genérica de 30 s. Otro guardián local (`7245c131…`) rechazó gratis la comparación de PNG original con JPEG normalizado; se corrigió la validación scratch, no el recurso.

## Resultados y corrección genérica

Galería `fb777fd3-3991-4035-9bf3-0f014a66c58b`: dos JPEG y MP4 1080×1350, 5,041667 s. Volante `9df71052-adcf-4832-b478-af7a99e676dc`: JPEG 1080×1350. Primer clip `3270be8c-374a-4ee5-aadf-4183f834bb38`: 480×854, 4,708333 s; omitió Nibbles y conservó la marca original. Galería segunda imagen sin logo; volante imprime «DM». El usuario pidió conservarlos.

La corrección pagada `cgt-20261030121938-iis3e` terminó con 93272 tokens, USD 0,596941 y 4,708333 s. Fotogramas 10/50/90 % muestran el imagotipo completo de Nibbles sobre la caja, siguiendo su perspectiva, sin la marca fuente visible. No afirma cinco segundos exactos ni reproducción completa. El SDK agotó espera; se recuperó por GET, sin otro POST. El servidor de referencias cayó durante el ensamblado posterior. Se conservó ese fallo y se incorporaron los mismos bytes ya pagados mediante un nuevo borrador normal, almacenamiento R2 y transición legal de generación: **`fa133c1d-9041-454c-aea9-babeb11c8715` — «Nibbles — réplica con imagotipo corregido»**. Costo de la tarea registrado una vez. Borrador HTTP 200; lectura parcial del video por la puerta real del reproductor HTTP 206, `video/mp4`, bytes 0–1023 de 2392046. Sin otro POST ni edición del archivo.

Se corrigieron conflictos del compilador común: categorías guardadas (logotipo: letras exactas sin símbolo añadido; isotipo: símbolo sin letras inventadas; imagotipo: conjunto elegido; isologo: unidad inseparable), selección de logo congelada pese a limpiar la firma local, letras del logo permitidas frente a `NO_TEXT`, continuidad OmniHuman con preflight de 1000 caracteres, rechazo de clasificaciones ambiguas y de elementos usados como logo. Instantáneas v1 conservan sus instrucciones; v2 congela tipo/espacio/selección; versiones desconocidas se rechazan. **92 pruebas offline pasaron** con revisión arquitectónica independiente. Cubren contratos y rutas, no fidelidad visual general: sólo se pagó una marca/reel, sin controles ni comparación estadística.
