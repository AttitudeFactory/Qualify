## Contexto

- Issue / tarea: <!-- QUA-123, URL o `N/A` con motivo -->
- Problema que resuelve:
- Resultado esperado:

## Cambios

-

## Riesgo y reversión

- Riesgo principal:
- Cómo se revierte:
- [ ] No cambia datos ni contratos externos
- [ ] Incluye migración reversible y plan de despliegue/reversión
- [ ] Incluye cambio de secreto, permiso o configuración operativa

<!-- Marca solo las afirmaciones aplicables. Si ninguna aplica, deja marcada la primera. -->

## Verificación

- [ ] Añadí o actualicé pruebas para el comportamiento modificado.
- [ ] Ejecuté `just ci-lint` y `just ci-test`, o el check `test` está verde.
- [ ] Si toca `migrations/postgres/`: `just migrate-down` → `just migrate` lo deja limpio.
- [ ] Si toca `packages/render/`: `npm run typecheck` pasa.
- [ ] Si cambié una integración externa: documenté cómo se verificó o por qué no pudo verificarse.
- [ ] Si cambié UI: adjunté captura, vídeo o expliqué por qué no aplica.

## Documentación y decisiones

- [ ] Actualicé documentación, runbook, ADR o contrato cuando corresponde.
- [ ] No hay una decisión de producto pendiente que cambie materialmente esta implementación.
- [ ] Hay una decisión pendiente: <!-- enlace y efecto -->

## Fuera de alcance

<!-- Lo que este PR deliberadamente NO hace, para que nadie lo busque aquí. -->
