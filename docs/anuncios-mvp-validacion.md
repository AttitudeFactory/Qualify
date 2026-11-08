# Validación del MVP con una cuenta real

Este registro separa pruebas de código, pruebas registradas por Meta y aceptación en
producción. Un resultado de CI o un transporte HTTP simulado no acredita llamadas reales
a Meta ni autoriza gasto. No se han realizado las operaciones reales de este documento.

## Datos que debe confirmar el responsable

| Dato | Estado |
|---|---|
| Negocio y persona responsable | Pendiente |
| App de Meta correspondiente al panel de pruebas | Pendiente de comprobar en la sesión autorizada |
| Página, Instagram y cuenta publicitaria elegidos | Pendiente |
| Publicación propia elegida | Pendiente |
| Presupuesto publicitario exacto en COP y fechas | Pendiente de autorización específica |
| Revisión jurídica y URL de términos publicados | Pendiente; véase m-24828985 |

No copiar tokens, secretos, cookies ni credenciales en este registro, tickets o capturas.

## Conexión y salud, sin gasto

Para m-24828972, comprobar en Tus redes que la cuenta conectada muestra nombre, moneda,
estado e Instagram correspondiente. Si pide actualizar el acceso, utilizar la conexión
principal existente y volver a elegir la cuenta de la marca. Registrar el resultado.

Para m-24828978, comprobar una cuenta válida y un caso de prueba sin pago confirmado.
No retirar el método de pago de un negocio operativo para fabricar este caso. La falta
de evidencia debe impedir abrir el asistente y ofrecer «Revisar pagos», sin afirmar que
una tarjeta no existe cuando Meta no lo confirmó.

## Prueba de objetos pausados, m-24828971

Requiere elegir y autorizar los activos antes de modificar Meta. Crear únicamente en
pausa, contrastar los identificadores y las respuestas reales y documentar las preguntas
del ticket en `docs/epica-anuncios-meta.md`, sección 3. No activar estos objetos de prueba.
Su eliminación también debe corresponder al responsable de esos objetos concretos.

## Prueba del recorrido completo, m-24828976

Requiere autorización expresa para el negocio, publicación, presupuesto y fechas:

1. Elegir una publicación propia y un enlace web admitidos por el flujo actual.
2. Comprobar permisos, cuenta, pago, propietario, moneda y validación de Meta.
3. Preparar y comprobar que los objetos quedaron en pausa. Revisar la vista previa real.
4. Contrastar en Meta el importe: COP usa unidades enteras; la conversión interna no debe
   multiplicar por cien el presupuesto enviado.
5. Confirmar el gasto desde la sesión autorizada. Comprobar la solicitud de activación,
   distinguiéndola de la aprobación y entrega posterior de Meta.

Si falta un campo, la configuración cambia o una respuesta queda incierta, registrar la
comprobación fallida. No saltar controles, inventar una coincidencia ni repetir escrituras.

## Gestión posterior, m-24828979

Sobre la promoción que ya recibió la confirmación inicial de gasto, comprobar la pausa,
el aumento de presupuesto, la fecha final y la reanudación. Cada cambio gestionado debe
mostrar condiciones actuales, nueva revisión y confirmación expresa; el aumento requiere
autorizar el nuevo importe. La aprobación original debe permanecer intacta.

Verificar historial de quién y cuándo aprobó el cambio, control de concurrencia y
enfriamiento. Una operación incierta se consulta sin volver a enviarla. Si es necesario
detener gasto mientras el control está bloqueado, pausar directamente desde Meta y
comprobar su estado allí.

Comprobar después los resultados diarios y el motivo que Meta informe para un rechazo,
cuando exista un caso válido. No provocar rechazos ni infringir políticas para fabricar
una prueba. Registrar el idioma y los campos efectivamente recibidos.

La actualización periódica requiere activar el proceso documentado en
`deploy/ads-reads-worker.md`, después de verificar capacidad del servidor. Su valor por
defecto es cero réplicas: tener el manifiesto en main no acredita ejecución periódica.

## Pruebas del panel de Meta, dependencia m-24828986

La captura aportada el 8 de noviembre de 2026 muestra:

- Marketing API Access Tier: 0 de 500 llamadas necesarias y al menos 85 % de éxito.
- `pages_manage_ads`: 0 de 1 llamada de prueba necesaria.
- `ads_read`, `ads_management`, `business_management` y `pages_read_engagement` aparecen
  completados en esa prueba.

Esto no acredita acceso avanzado aprobado ni un nivel de acceso final. La captura tampoco
indica la ventana temporal de cómputo o cuáles endpoints contabiliza cada comprobación;
esas condiciones deben verificarse en el panel y documentación vigentes.

No son 500 anuncios. Antes de ejecutar llamadas se debe comprobar app, token, activos,
permisos y endpoints admitidos; respetar los límites y la espera de la API. No crear
campañas para inflar contadores ni lanzar un lote sin verificar qué contabiliza Meta.

Las solicitudes de las pruebas HTTP y de memoria de este repositorio son simuladas. No
suman llamadas al panel, aunque utilicen la clase real del cliente HTTP. El trabajo de
App Review corresponde a m-24828986, asignado a Herwin, y está fuera de la épica de código
m-24828970; su evidencia debe quedar vinculada a la aceptación real del MVP.

## Cierre

Registrar resultado, fecha y responsable de cada comprobación realizada. Dejar como
pendiente lo no ejecutado. Solo cerrar un ticket cuando sus criterios estén acreditados;
no marcar como prueba real una simulación, un permiso configurado o un merge.
