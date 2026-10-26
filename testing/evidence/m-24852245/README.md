# PASOS-6: Publicar ahora — m-24852245

Prueba local en navegador a **360 × 800 px**, el 26 de octubre de 2026, con una sesión y fotos sintéticas. No se publicó contenido ni se enviaron mensajes.

- [Paso 1 con diez fotos](paso-1-10-fotos.png): cabeza y «Siguiente» visibles sin desplazar hasta el final.
- [Paso 2](paso-2.png): al avanzar, el contenedor vuelve arriba (`scrollTop = 0`). Se comprobó el recorrido atrás/adelante del navegador conservando las diez fotos.
- [Paso 3](paso-3.png): revisión de las diez fotos, texto y botón «Publicar» visible, con 44 px de alto. Se añadió una cuenta de Instagram sintética sin credenciales, exclusivamente al tenant de prueba, para alcanzar esta pantalla. No se tocó «Publicar».
- [Seguir desde Inicio](seguir-en-inicio.png): «Seguir después» abre Inicio; «Seguir» restaura el asistente y la selección.

La captura del paso 2 conserva el caso inicial sin cuenta conectada; el paso 3 corresponde al pase posterior con la cuenta sintética. La aprobación final no se ejecutó.

**Sugerencia de experiencia aplicada:** el pie explica qué falta cuando «Siguiente» está deshabilitado, junto al botón.
