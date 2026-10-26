# PASOS-5: Crear publicación y Variaciones — m-24852244

Prueba local en Chromium a **360 × 800 px** y **1280 × 900 px**, el 26 de octubre de 2026. Se usó exclusivamente el tenant sintético «Pasos Cuatro», con un producto ficticio sin foto y sin generación de contenido ni publicaciones.

- [Paso 1](paso-1.png): selección del producto y botón «Continuar» fijo. Sin desplazamiento horizontal.
- [Paso 2](paso-2.png), [paso 3](paso-3.png) y [paso 4](paso-4.png): recorrido del tipo «Guion para grabar», que tiene cuatro pasos reales contando el producto. Cabeza y botón principal permanecen visibles; las acciones del pie miden 44 px de alto. El selector de tipo permanece resumido y «Cambiar» permite abrirlo sin alterar los campos del paso.
- [Seguir desde Inicio](seguir-en-inicio.png): «Seguir después» muestra la tarjeta pendiente y «Seguir» restaura el paso 4. Atrás/adelante del navegador recorren los pasos 3 y 4 conservando el producto.
- [Variaciones](variaciones.png): es un formulario con secciones 1/2/3, sin contador de asistente. «Generar los ángulos» permanece visible sobre la navegación móvil; no se ejecutó.
- [Escritorio](escritorio.png): el selector lateral sigue visible, no aparece el botón móvil «Cambiar» y «Crear publicación» es la única entrada activa del menú.

Con `prefers-reduced-motion: reduce`, todos los hijos del cuerpo del marco devolvieron `animation-name: none`.

**Límites:** no se generó una publicación, por lo que la pantalla de resultado y el subdetalle de un grupo de variaciones se revisaron mediante código y pruebas offline, sin captura de resultado real. Los avisos de marca de las capturas corresponden al fixture, que no tiene logo ni perfil de voz preparado. No se recorrieron en navegador todos los tipos de creación ni se midió una carga lenta de catálogo.

**Sugerencias de experiencia:** se aplicó el resumen del selector móvil para que la lista de formatos no tape el contenido de cada paso. El contenido y las opciones disponibles se conservaron.
