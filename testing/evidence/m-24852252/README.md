# PASOS-11: movimiento, archivo y materiales

Playwright/Chromium, viewport 360 × 800. Preview conjunto PASOS-7/8/9/10/11 en localhost:3480 desde este worktree. Sólo datos sintéticos Pasos Cuatro; ningún envío, publicación ni generación.

## App real

Primario sólido desactivado de Publicar: 44 px, background-image none y transform none. Los eventos animationstart del contenido registraron q-content-in con duración CSS 0.24s y opacidad 0.55→1 en la primera compilación conjunta. La navegación real de los cuatro pasos del menú, Atrás y retomar desde Inicio está documentada en PASOS-8.

En la última compilación se comprobó Publicar con un JPEG de fixture → paso 2 → Atrás → paso 1: misma identidad del input y del cuerpo DOM, miniatura conservada y primario habilitado. El menú Más móvil resuelve fondo rgb(24,25,27), igual al material opaco #18191b. Capturas archivo-retomado y mas-opaco de la app real.

## Último ajuste: callback generado real en DOM aislado

La revisión corrigió dos fallos: duración CSS 0.38s interpretada como 0.38 ms en Web Animations, y destino de Atrás pendiente con/sin barra final que ejecutaba history.back dos veces. El segundo se volvió a comprobar en la app real, como se describe arriba.

Para la duración se exportó el texto real de WhatsAppMenuState._guided_settle desde la fuente final (guided-settle.generated.js) y se ejecutó en Chromium con assets/qualify.css del proyecto. No se reprodujo manualmente su lógica. El JSON adjunto registra tres llamadas reales: tokens 0.38s y 380ms producen 380 ms, next entra desde +8 px y back desde −8 px. Se conserva el mismo panel, el mismo input y un archivo seleccionado. La tarjeta cargada usa 240 ms y opacidad 0.55→1. Con movimiento reducido no se añade ninguna llamada de animación (3→3) y el fade CSS pasa a none. La captura callback-dom-aislado está rotulada expresamente como DOM aislado.

Este último ajuste no se presenta como interacción funcional del menú en la última app: una migración reciente de main añadió social_connections.reconnect_reason, columna ausente en la base de prueba compartida. No se alteró ni migró esa base. Se verificó el callback generado real en DOM y las pruebas focales, mientras que el flujo real completo ya había pasado antes de incorporar ese cambio de modelo ajeno a PASOS. Sin sugerencias abiertas en el alcance revisado.
