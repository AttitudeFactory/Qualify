# m-24854866 · Textos y estados de cuenta · Traspaso a Deivid

Entrega de Yesika Roa. Rama `codex/m-24854866-textos-estados`.
Alcance: unificar estados, acciones y avisos, con pruebas y documentación.
Este PR no completa la épica m-24854862 ni sustituye las entregas de otros responsables.
No autoriza merge ni despliegue.

## Cambios propios del ticket

- Vocabulario compartido: Conectada, Desconectada, Sin acceso y Volver a conectar.
- `active` se presenta como Conectada; `degraded`/`revoked`, como Desconectada.
  Los estados desconocidos se presentan como Sin verificar y no exponen su valor interno.
- Sin acceso requiere evidencia de permiso faltante; una desconexión conocida tiene
  prioridad en Mensajes. `revoked` también puede representar una desconexión voluntaria:
  no demuestra por sí solo que el dueño quitó un permiso.
- Avisos de desconexión y permiso faltante diferenciados, contenido guardado explicado
  y ayuda para quien no tiene acceso a Facebook.
- WhatsApp: Este arreglo lo hace el equipo de Qualify + Avisar al equipo de Qualify.
  El aviso se coloca sobre el contenido del número afectado; no inicia OAuth.
  Los errores ocultan códigos internos y referencias técnicas al proveedor.
- Corrección del falso aviso de Instagram Direct: un grant válido de mensajes no se
  interpreta como inválido por exigir `pages_messaging`, que pertenece a otra superficie.
- Actualización de docs/design-system.md §6.3 y §7.3 y tests de regresión.

## Integración con main antes de abrir el PR

El 26 de octubre se actualizó la referencia de main a `c432889`. Esa base ya contiene
el trabajo de servidor y reconexión de Raúl (#387, m-24854864/m-24854865), además de
cambios de generación/versiones. Se hizo rebase para conservar esos cambios.

Los conflictos se resolvieron manteniendo `reconnect_reason`, los resultados nuevos
`permission_missing`/`account_access_required` y la acción compartida de reconexión
con su origen firmado y panel de resultados. No se restauró el enlace antiguo de
Mensajes a `/connections`. La ayuda duplicada se retiró porque el componente de main
ya ofrece ayuda y objetivos táctiles de 44 px.

Estos mecanismos pertenecen a la base de Raúl, no se atribuyen como desarrollo nuevo
al PR de Yesika. El contrato ahora sí está disponible en
`docs/epica-cuenta-desconectada.md`.

El historial temporal de QA se compactó en tres commits de implementación, tests y
traspaso antes de publicar. Se guardó una referencia de respaldo local. Antes del
rebase se comprobó que el árbol completo conservaba exactamente el contenido validado.
Después del rebase se añadieron dos regresiones para conservar la acción compartida
y el texto de permiso faltante. No hay controles ni handlers de simulación en la entrega.

## Validación

### Revisión posterior al rebase

Código y tests estables en `8340068`, sobre main `c432889`.
Pruebas dirigidas: **225 aprobadas en 45,40 s**, sin DB ni servicios externos.
Incluyen textos, conexiones, Mensajes, reconexión y contrato de salud de servidor.
La suite completa y el build Linux de esta revisión se registran al finalizar.

### Evidencia anterior al rebase (conservada como historial)

- Suite offline completa: **9534 aprobadas, 1 omitida, 1173 deseleccionadas, 0 fallos**.
  Pytest:1415,68 s; gate completo:1547,89 s. Selección CI
  `not integration and not db and not slow`, con `PYTHONUTF8=1`.
- Cobertura global:84,1 %; Qualify:83,3 %. Ruff aprobado y formato correcto1695 archivos.
- `python -m reflex compile --dry`: aprobado,107,031 s.
- Build Linux/amd64 canónico, desde contexto limpio `git archive` del antiguo commit
  `4a88fb2`: aprobado,669,357 s. Imagen únicamente local
  `qualify-m24854866-validation-4a88fb2:local`.
- Smoke de imagen de solo lectura, sin red ni puertos publicados: Caddy válido,
  archivos HTML presentes y HTTP correcto para `/`, `/login`, `/connections`,
  `/whatsapp`, `/responder` y fallback `/drafts/local-smoke`.
- Dos exports nativos de Windows habían fallado por timeout al prerenderizar `/`.
  Ese fallo no se reprodujo en el build Linux limpio. No se omitieron rutas ni
  prerender ni se modificaron vendors para aprobar. Los intentos fallidos se conservan.

Los conteos de ejecuciones diferentes no se suman. La omisión anterior era un parámetro
vacío[NOTSET] del guard de navegación; el warning de ApprovedCreativeResponse.copy
correspondía a código fuera del ticket. No se ejecutan tests db en esta entrega porque
el PR no modifica esquema, migraciones ni repositorios. Las migraciones nuevas de
main pertenecen a su validación propia; no se aplicaron a la base local de QA.

## Pantallas y límites de la evidencia

| Pantalla | Resultado y límite |
|---|---|
| Tus redes | Yesika revisó etiquetas/avisos e hizo OAuth real; sonda de lectura de Instagram válida. No prueba una caída real ni el nuevo retorno compartido posterior al rebase. |
| Mensajes | Tres estados e historial revisados con simulación de presentación anterior. Los controles se retiraron; las capturas no prueban el servidor ni el OAuth. |
| WhatsApp | Número de pruebas autorizado, historial ficticio conservado ante caída local inducida, aviso y botón en la UI real sin simulador, recuperación y verificación de credencial aprobadas. |
| Soporte | La UI mostró una solicitud local registrada; se capturó también el botón antes de solicitar. No se acreditó recepción externa. |

Herwin autorizó usar el número de pruebas documentado. El alta administrativa se hizo
para el negocio local, con credencial cifrada. Se guardaron dos mensajes ficticios bajo
Cliente de prueba local; no se usó un destinatario real, no se enviaron mensajes ni se
revocaron permisos externos. Se indujo `degraded` mediante el servicio existente solo
en Postgres local y después se restauró `active`. La cola de envíos quedó vacía.

El token local de pruebas no es una nueva dependencia del despliegue de estos textos.
El canal de soporte no está configurado en localhost (`QUALIFY_SUPPORT_WEBHOOK_URL`):
registrar una solicitud no demuestra recepción por el equipo. El aviso automático por
caída es otro requisito. No se ejecutó `whatsapp-smoke`, que envía mensajes reales.

## Pendientes para la integración de la épica

| Requisito | Situación a partir de la base actual |
|---|---|
| Causas permanentes/racha temporal/recuperación | Contrato de Raúl disponible en main; verificar su consumo en cada pantalla y worker. |
| Facebook directo y retorno al origen | Acción compartida de Raúl presente en main y conservada en este rebase. Falta evidencia de flujo real integrado y conteo de tres toques. |
| Selectores e historial de Comentarios | Pendiente de Deivid m-24854867; Comentarios aún filtra active y Mensajes excluye revoked. |
| Permiso quitado frente a permiso nunca concedido | El servidor publica permission_missing; no atribuir una retirada por el dueño sin evidencia que la distinga. |
| Sondeo y aviso tras tres fallos temporales | Estado persistido disponible; falta comprobar la integración completa de consumidores y avisos. |
| Insignia Desconectada junto a Tus redes | No implementada en este PR; acordar responsable de la épica. |
| Lark automático por caída | No validado. Publicador local al proceso, sin promesa de outbox duradera ni recepción externa. |
| Entrega de solicitud de WhatsApp | Pendiente del canal configurado y de evidencia de recepción. |
| Regresión real de tres pantallas | Pendiente de integrar las pantallas de Deivid y probar con cuentas autorizadas. |

Correo al dueño y reconexión de WhatsApp por el dueño quedan fuera del alcance.

## Revisión para Deivid

1. Revisar solo el diff del PR: textos, presentadores, tests y documentación. No hay
   scripts de preparación, rutas de demostración ni cambios de dependencias.
2. Comprobar estados en Tus redes y avisos de Mensajes/WhatsApp con datos autorizados.
   No desconectar cuentas de producción para obtener capturas.
3. Integrar selectores/historial y consumo del contrato de Raúl. Mantener aprobación,
   permisos y ventana de respuesta antes de cualquier envío.
4. Probar fallo/recuperación reales, retorno y mensaje de éxito, racha temporal y Lark.
5. Antes de mergear/desplegar, revisar CI de la versión integrada y la arquitectura
   de despliegue ARM64; los builds locales de esta revisión son Linux/amd64.

## Limpieza, UX y paquete de evidencias

`.env`, `.states`, `.web`, cobertura, logs, capturas, scripts y objetivos de la base
local quedan fuera de Git. Los cambios ajenos de `graphify-out/cache/stat-index.json`
y `reflex.lock/*` se preservaron exactamente y se excluyeron del PR. Los tests normales
de regresión sí pertenecen a la entrega.

Revisión UX: vocabulario/avisos unificados y ayuda asistida aplicados. El componente
compartido de main resuelve los44px de Mensajes; se eliminó la ayuda duplicada.
Pendiente: reservar por verificar para incertidumbre real; revisar con el contrato
para no cambiar unilateralmente el significado de la provisionalidad de capacidades.
No se certifica una auditoría móvil completa.

El paquete local `traspaso-m-24854866.zip` contiene LEEME/RESULTADOS, capturas
etiquetadas como simuladas o reales y logs de pruebas/builds. Los informes posteriores
al rebase se guardan aparte en `pr-final-qa` y se incorporan al cierre. No incluye
credenciales ni scripts; compartir las capturas de sesión solo con el equipo del ticket.
