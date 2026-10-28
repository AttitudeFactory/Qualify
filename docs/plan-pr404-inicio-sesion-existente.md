# Plan de cierre del PR 404 — agregar un negocio con una cuenta existente

Ticket: **m-24849194 (S7)**. Épica: **m-24849186**, varios negocios en una sola sesión.
El objetivo es agregar un negocio separado mediante una invitación del fundador y la
contraseña actual, sin modificar el negocio anterior ni crear otro inicio de sesión.

Estado: implementación local y validación técnica terminadas. Para cerrar la entrega al
cliente faltan la configuración del campo en Meegle y la integración del selector de S3/S4.

## Trabajo en paralelo

| Frente | Archivos principales | Resultado verificable |
|---|---|---|
| Backend y correo | `auth/service.py`, `auth/invites.py`, `auth/invite_email.py`, `meegle/onboarding.py`, modelo de invitaciones | Con el campo en no, un correo registrado produce error y devuelve Datos; con el campo en sí, se autentica la cuenta y se crea otro tenant. Correo HTML y texto coherentes. |
| Interfaz | `Qualify/auth_state.py`, `Qualify/auth_pages.py` y sus pruebas | La invitación pide solamente la contraseña actual. Funciona con y sin sesión previa, sin mezclar cuentas. Incluye los textos del ticket y una salida clara. |
| Pruebas de aceptación | `packages/api/tests/` | Comprueba separación de datos, membresías owner, rechazo sin efectos, invitaciones inválidas e idempotencia. |

Los agentes comparten el contrato de `InviteView.is_add_business` y mantienen la firma de
`register_business`. Cada frente modifica archivos distintos. No se cambia el entorno
compartido mediante `uv sync` durante la ejecución.

## Criterios de integración

- [x] Campo en no y correo existente: no se crean invitación, tenant ni marca; Estado Qualify
  queda en error, Datos vuelve atrás y se registra el comentario exacto del ticket.
- [x] Campo en sí: se verifica primero la contraseña existente; nunca se crea una identidad.
- [x] El tenant nuevo tiene una marca y una membresía owner del mismo inicio de sesión.
- [x] `memberships_for` devuelve ambos negocios; las filas del negocio anterior no cambian.
- [x] Contraseña incorrecta e invitaciones vencidas, usadas o de otro correo no crean datos.
- [x] Reintentar una invitación o evento no crea otro negocio.
- [x] Dos invitaciones normales distintas para el mismo correo, procesadas a la vez,
  no agregan una segunda marca al negocio de la primera.
- [x] Pantalla, asunto, botones y mensajes cumplen el texto acordado; correo HTML y texto
  plano ofrecen la misma acción.
- [x] Pruebas focalizadas, `just ci-lint`, `just ci-test` y pruebas DB pertinentes en verde.
- [x] Compilación de Reflex, revisión independiente del diff y revisión UX con sus límites
  documentados; las sugerencias se muestran al fundador.

## Límites y dependencias

- El selector global de negocios corresponde a S3/S4. S7 conserva la sesión con su negocio
  actual; no cambia el tenant activo sin la validación y limpieza de estado requeridas.
  El texto de éxito del ticket depende de que el selector exista antes de entregar la
  experiencia completa al cliente.
- El formulario de contraseña usa los valores de ubicación predeterminados del registro
  para el nuevo negocio; no modifica la ubicación del anterior.
- La consulta de metadatos de Altas en Meegle del 2026-10-28 no encontró el campo
  «Inicio de sesión existente». Falta crearlo y agregarlo al layout, como prevé el ticket.
  Crear campos o modificar el layout de Meegle es una operación administrativa externa.
- Los cambios quedan en la rama del PR para revisión. Publicar actualizaciones, modificar
  el ticket, mergear y desplegar se informan por separado según su autorización.

## Cierre

Registrar los resultados reales de las verificaciones y las limitaciones pendientes.
Revisar nuevamente cualquier corrección material antes de considerar el PR listo para merge.

## Validación de la implementación

- Pruebas focalizadas de backend: 100 en verde.
- Pruebas focalizadas de interfaz y acceso: 105 en verde.
- Pruebas DB focalizadas: 18 en verde, incluidas 10 nuevas de S7.
- Suite DB completa tras integrar main: 1.257 en verde, con `uv run --no-sync pytest -m db`
  sobre una base temporal vacía.
- `just ci-test` tras integrar main: 10.076 pruebas en verde y una omitida; cobertura total
  del 84,1 %.
- `just ci-lint`, compilación de Reflex y `git diff --check`: en verde.
- La revisión independiente de aceptación y transacciones no encontró otros defectos
  confirmados después de corregir la carrera entre invitaciones distintas.
- La revisión inicial se realizó con agentes independientes porque `review-agent` no estaba
  disponible. La reparación posterior de migraciones y su integración con Altas se revisaron
  de forma independiente con esa skill, ya disponible.
- El grafo local se actualizó; se excluyeron del diff los cambios de caché generados.

## Sugerencias de UX

Alcance: flujo de invitación en la app real con Chromium local, a 360 px y en escritorio,
con autenticación y datos de prueba. Se comprobaron formulario, contraseña incorrecta y éxito.
La revisión se limita a este flujo; el selector global pertenece a S3/S4.
La pasada final usó las dependencias fijadas del proyecto: sin errores de página, un solo
campo de contraseña actual, controles de 44 px y ancho del documento igual al de la ventana
tanto a 360 px como a 1.280 px. El correo largo ya no produce desbordamiento horizontal.

- **Aplicada:** permitir que los correos largos se partan en varias líneas para evitar
  desplazamiento horizontal en móvil.
- **Pendiente:** el mensaje de éxito exige que exista el selector superior de negocios.
  Integrarlo con S3/S4 antes de entregar la experiencia completa al cliente.

## Integración de migraciones con main

La comprobación de CI detectó que la revisión `0106` de este PR colisionaba con la cadena
de main. Se integró main en la rama del PR, incluidas `0106_connection_purge`,
`0107_webhook_consent_privacy` y `0108_connection_purge_scheduler`. Se renumeró únicamente
la migración de este trabajo a `0109_signup_invites_is_add_business`, con predecesora `0108`.
Las revisiones publicadas permanecen intactas.

La validación final en un Postgres 16 temporal comprobó una sola cabecera `0109`, el ciclo
`upgrade head → downgrade base → upgrade head` y la columna booleana no nula con valor
predeterminado falso. También pasaron 119 pruebas focalizadas de autenticación y Altas.
La base local de pruebas existente se conservó intacta.
