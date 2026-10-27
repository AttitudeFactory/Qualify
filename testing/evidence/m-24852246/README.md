# PASOS-3: revisión local

Playwright, Chromium, viewport 360 × 800. Sólo tenant sintético Pasos Cuatro y conexiones sin credenciales. No se enviaron mensajes, publicaron contenidos ni ejecutaron generaciones. Las capturas no contienen datos de clientes reales.

Comprobado en navegador: Catálogo abre y conserva paso/nombre al volver, avanzar y recargar; la entrada nueva a /catalog cierra el cajón y deja la URL limpia. Menú avanza a paso 2 y Atrás/Adelante del navegador restauran los pasos 1/2. Mensaje aprobado restaura sus pasos y cerrar limpia el flujo. WhatsApp y Responder restauran pestaña y ficha mediante UUID; un UUID desconocido no conserva la ficha anterior. Planner abre la ficha del evento sintético cancelado, conserva semana/vista al cerrar y trata un UUID desconocido con error seguro.

Marca mínima: entrada directa a pasos 5, 1 y 4, hidratación de campos y Atrás 4→1 comprobados. En compilación b0e6715, muestreo por requestAnimationFrame con CPU 6× sólo registró el contador solicitado: paso 1 a 419 ms y paso 4 a 443 ms; no apareció el contador anterior. Las capturas marca-1 y marca-4 corresponden a esta compilación.

Reprueba b0e6715: /brand/manual?paso=6 normaliza a paso 2 de 7 y /brand/connect?paso=7 a paso 1 de 12. Crear registra una sola entrada al avanzar 1→2 y la secuencia 3→Atrás de la app→2→Atrás del navegador→1 conserva URL y pantalla coherentes. Reprueba final 0d7262c: Marca mínima con negocio incompleto normaliza /brand?paso=5 y paso=4 al paso 2, con URL y pantalla coherentes. En contexto nuevo, /create?paso=99 sin producto y /publish?paso=99 sin archivos normalizan al paso 1. Capturas create-guard1 y publish-guard1 de esta compilación. No quedan hallazgos abiertos en los casos revisados.

Las fichas de WhatsApp, Responder, Planner y Catálogo se capturaron durante las pasadas previas de esta misma revisión; los retests f90481d, b0e6715 y 0d7262c comprobaron específicamente Catálogo limpio, historial de Menú/Mensaje aprobado y Marca. Aislamiento entre tenants revisado en código/pruebas; en navegador se usó UUID desconocido, no un registro de un segundo tenant. No se probaron generación, envío, publicación ni confirmación del evento cancelado.
