# Públicos de Instagram y públicos similares

Entrega de `m-24828983`. El asistente permite consultar los públicos creados desde
Qualify para la cuenta y marca actuales, preparar un público de interacciones o
mensajes y crear un público similar desde uno de esos públicos ya comprobados.
Crear un público no crea anuncios, no activa promociones y no acepta términos por
el cliente. Las listas de clientes quedan fuera de alcance.

## Creación y aislamiento

La sesión debe conservar pertenencia al negocio. Se comprueban la publicación, su
conexión de Instagram, marca, cuenta seleccionada y versión de credencial. La fuente
de Instagram sale de esa conexión, nunca de un identificador enviado por la pantalla.
La cuenta remota debe devolver su identidad exacta y
`tos_accepted.custom_audience_tos` como entero `1`. Ausencia, otros tipos o una cuenta
distinta no prueban aceptación. Un entero `0` pide aceptar los términos en Meta y
volver a consultar; Qualify no los acepta automáticamente.

Cada creación exige confirmación humana y conserva intención, contenido, identidad
del aprobador, fecha y procedencia en `ad_custom_audiences`. La clave de solicitud
es única por negocio. Una reclamación confirmada se guarda antes del único envío.
Una repetición exacta consulta su resultado; una clave con otro contenido se rechaza.
Si el envío queda incierto o el proceso muere, no se repite. La pantalla indica que
hay que revisar Meta antes de crear otro público. No se recuperan públicos buscando
por nombre ni se atribuyen a otra marca los públicos de una cuenta compartida.

Los términos se consultan antes del envío. La pertenencia y vinculación se comprueban
otra vez después de esperas del cliente HTTP. La tabla tiene RLS forzada, claves
foráneas compuestas y una protección de identidad e intención inmutables. La purga
de una conexión elimina también este registro local.

## Selección y consentimiento de la promoción

Solo se ofrecen públicos creados desde esta cuenta, marca, conexión y versión de
credencial. Para ofrecerlos, Meta debe devolver la misma identidad, cuenta y regla
de origen, además de códigos enteros `200` en operación y entrega. Un resultado
incompleto, en preparación, no disponible o con origen distinto queda sin seleccionar.
Esto es una observación puntual, no una garantía de alcance o entrega futura.

La selección conserva identidad local, identidad de Meta, nombre y tipo en la copia
inmutable aprobada. Cambiarla cambia la huella de aprobación. Al guardar y al crear
una promoción persistente se contrasta esa identidad con el registro del servidor.
No se admiten identificadores libres ni un público similar etiquetado como otro tipo.
Con «Vivienda» no se ofrecen públicos similares y el servidor rechaza esa combinación.
Las aprobaciones antiguas sin estos públicos conservan exactamente su representación
y huella anteriores.

**El uso en promociones reales sigue pendiente de comprobación.** El control de
producción del asistente rechaza las selecciones de estos públicos antes de crear o
activar anuncios. La integración completa de selección y destino se prueba con el
adaptador simulado; no habilita gasto real. La creación independiente de públicos sí
tiene un adaptador real con confirmación explícita. No hay temporizadores nuevos.

## Evidencia y límites

Revisión del 2026-11-12, sin llamadas a cuentas reales de Meta. La documentación
actual de guías respondió con restricciones de acceso; no se presenta una prueba
simulada como validación real. Las fuentes oficiales recuperadas son:

- [Ejemplo oficial de público de interacción](https://github.com/facebook/facebook-python-business-sdk/blob/main/examples/AdAccountCustomAudiencesPostPlatformEngagementCustomAudience.py):
  estructura de inclusiones, fuentes, filtro de evento y retención en segundos.
- [Ejemplo oficial de público similar](https://github.com/facebook/facebook-python-business-sdk/blob/main/examples/AdAccountCustomAudiencesPostValueBasedLookalikeCustomAudience.py):
  `LOOKALIKE`, origen y proporción mediante `custom_ratio`.
- [Cambio oficial de términos](https://developers.facebook.com/docs/graph-api/changelog/version2.4/):
  claves de `tos_accepted` y valores enteros; copia local en
  `reference/meta-instagram-platform/docs/graph-api/changelog/version2.4.md`.
- [Cambio oficial de eventos de mensajes](https://developers.facebook.com/docs/graph-api/changelog/non-versioned-changes/dec-2-2020/):
  eventos `ig_business_profile_all` e `ig_user_messaged_business`; los mensajes están
  separados de la interacción general y existen restricciones regionales históricas.
- [Cambio oficial de públicos](https://developers.facebook.com/docs/graph-api/changelog/non-versioned-changes/oct-1-2014/):
  códigos de operación/entrega y origen de un público similar.

La regla de Instagram combina la estructura del ejemplo oficial con los eventos del
cambio oficial y el alcance del ticket; su aceptación actual es una inferencia que
Meta decide al recibir la solicitud. El intervalo local de uno a setecientos treinta
días proviene del ticket, no de una medición actual de un límite admitido. Meta puede
rechazar periodos, orígenes, regiones o públicos insuficientes. No se prometen menor
costo, entrega ni un tamaño de público.

Para cerrar el ticket completo falta crear un público en una cuenta autorizada,
comprobar su disponibilidad y usarlo en una promoción mediante evidencia real de
compatibilidad. Esa comprobación y cualquier activación con gasto requieren el
flujo de autorización ya existente; esta entrega no las ejecuta.
