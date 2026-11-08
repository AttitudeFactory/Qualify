# Lecturas periódicas de anuncios

`ads-reads-worker` queda apagado por defecto: `QUALIFY_ADS_READ_WORKER_REPLICAS=0`.
Reutiliza las credenciales existentes. Solo consulta Meta; no crea, edita, activa ni
pausa anuncios. Busca cuentas seleccionadas disponibles, procesa un negocio a la vez
y adquiere una exclusión en PostgreSQL para evitar lecturas duplicadas entre réplicas.

La salud se conserva durante 24 horas. Los resultados quedan pendientes de consulta
a los 25 minutos; el bucle espera 60 segundos entre pasadas y procesa hasta 100
promociones por negocio. Ese margen no garantiza 30 minutos bajo colas grandes o
latencia de Meta: verificar la antigüedad real de los resultados después de activar.
El chequeo del contenedor solo confirma el latido del proceso, no permisos, pagos
ni la disponibilidad de Meta.

## Preparación del servidor antes de activar

La suma de los límites actuales supera la memoria física del servidor. El límite
de este proceso es 128 MiB sin intercambio. La prueba local de carga sintética
pasó dentro de ese límite; todavía debe comprobarse la memoria libre del servidor.
No activar hasta verificarla. No modificar límites de los otros servicios para acomodarlo.

El responsable con acceso al servidor debe revisar memoria libre y consumo real
durante las cargas de medios y generación. Después de verificar capacidad, configurar
en el entorno local autorizado `QUALIFY_ADS_READ_WORKER_REPLICAS=1` y preparar:

```sh
just env-push qualify-prod --dry-run QUALIFY_ADS_READ_WORKER_REPLICAS
just env-push qualify-prod QUALIFY_ADS_READ_WORKER_REPLICAS
just deploy qualify-prod <sha-revisado>
just deploy-status qualify-prod
```

No ejecutar estos pasos hasta revisar el PR y disponer del acceso autorizado.
No editar manualmente `.env.prod` ni cambiar `COMPOSE_PROFILES`. Confirmar que el
proceso esté saludable, sin reinicios por memoria, y que los resultados se actualicen
dentro del plazo esperado. Para detenerlo, configurar la misma variable en 0 y
aplicar el mismo flujo documentado de `env-push` y despliegue.

No hay cambios de secretos ni una configuración nueva de Meta. Fusionar el PR no
activa estas consultas. Docker documenta `deploy.replicas` como el número de
contenedores que deben ejecutarse:
https://docs.docker.com/reference/compose-file/deploy/#replicas

## Comprobaciones locales

`just ads-reads-tick <tenant-uuid>` ejecuta una pasada del negocio indicado.
`just ads-reads-worker <tenant-uuid>` mantiene el bucle para ese negocio.
Usar únicamente datos y credenciales de prueba autorizados. Las comprobaciones de
producción de conexión, permisos y cuenta siguen pendientes de acceso y selección
del negocio; un despliegue exitoso no demuestra esas condiciones.

`bash deploy/measure/ads-reads-import-memory.sh` mide únicamente la importación y
el latido en Docker sin red, con límite de 128 MiB. Es una cota inferior, no una
validación de carga completa ni de capacidad del servidor.

`just mem-ads-reads-worker` ejecuta la prueba completa con PostgreSQL descartable,
roles reales y una red interna sin salida. Usa el transporte de HTTP simulado,
rechaza cualquier método distinto de GET y no importa pytest. Reutiliza únicamente
las definiciones de preparación de datos de las pruebas de resultados, conserva
las restricciones de PostgreSQL y procesa 100 promociones con 28 días de resultados,
una pasada de caché y una segunda pasada vencida. Verifica que sigan existiendo
2.800 filas diarias: las lecturas repetidas no duplican resultados.

Medición local de 2026-11-08, imagen `qualify-memtest:deps`, límite 128 MiB:
RSS máximo observado 79,13 MiB, pico del grupo de memoria 59.408.384 bytes; 501 consultas GET,
200 promociones consultadas entre las dos pasadas, cero consultas no disponibles.
Una cuenta con 100 anuncios propios también recorrió su consulta diaria de salud;
la pasada posterior reutilizó esa salud sin consultar Meta otra vez. La medición
incluye la preparación de datos en el mismo proceso. No demuestra latencia real
de Meta, capacidad para todos los negocios ni memoria libre del servidor.
