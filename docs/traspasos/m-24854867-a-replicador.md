# Traspaso de inbox m-24854867 al agente del replicador m-24820836

**Estado: trabajo local del inbox terminado; puedes continuar con la actualización de
la carpeta principal y el arranque del replicador. Solo queda CI remoto pendiente.**

Fecha: 2026-10-27. No queda ninguna operación local de este agente en curso que deba
esperarse. No estoy ejecutando servidores, workers, migraciones ni operaciones de panel.
No cerré ni reemplacé paneles y no detuve el servidor del replicador en 3000/8000.

## Código y commits

- PR abierto: <https://github.com/AttitudeFactory/Qualify/pull/395>.
- Rama publicada: `origin/feat/m-24854867-inbox-disconnected`.
- Worktree limpio: `C:\Users\deivi\AppData\Local\Temp\qualify-m24854867`.
- HEAD final: `7881593c9073b1f83e8e13486e6816144efc3cf3`.
- `c622da07`: implementación del aviso, conservación de comentarios y pruebas iniciales.
- `37bc83be`: correcciones de las revisiones de UX y código, con pruebas nuevas.
- `35fb7878`: UX y revisión de código obligatorias antes de todos los PR.
- `7881593c`: aprobación explícita para merge y ticket actualizado antes de cerrar un PR.

**El inbox NO está en `origin/main`.** El PR sigue abierto y no se hizo merge ni se
habilitó auto-merge. Un pull de `main` no trae estos cambios. No fusiones el PR sin la
aprobación explícita del usuario. El trabajo del replicador puede continuar por separado;
no necesita mezclar el inbox para su arranque. Si se requiere probar ambos juntos,
debe identificarse expresamente esa integración local de la rama del PR.

El agente del replicador informó su commit local `e78d62c3`, rama
`feat/m-24820836-replicar-seedance`, sin migración propia; conserva el control de su
integración y del panel Bash libre **Servidor Reflex `w3:pB`**.

## Revisión y validación

- `ux-designer`: revisión independiente ejecutada y repetida; cuatro sugerencias
  aplicadas, sin sugerencias adicionales en el alcance revisado.
- Limitación de UX: no se pudo abrir la app del PR en navegador. Faltan navegación,
  sesión, regreso real de Facebook e interacción del cajón en una instancia accesible.
- `review-agent`: correcciones revisadas nuevamente; resultado final **No findings**.
- 161 pruebas offline relacionadas aprobadas; lint y formato del repositorio aprobados.
- Skill `qualify-pr` validada con `quick_validate.py`.
- CI anterior de `c622da07`: 9.784 offline y 1.212 de PostgreSQL/Redis aprobadas.
- CI final de `7881593c`: **pendiente** al entregar este archivo:
  <https://github.com/AttitudeFactory/Qualify/actions/runs/40518845170>.

La descripción del PR contiene «Sugerencias de UX», el resultado de revisión de código,
las capturas, la evidencia y los pendientes. No se presenta la revisión acotada como una
validación interactiva completa.

## Carpeta principal: preservar los cambios

Ruta: `C:\Users\deivi\OneDrive\Escritorio\work\Qualify`.
Al entregar, sigue en `feat/m-24828906-versiones-al-regenerar`, HEAD `cf366bfa`.
No cambié esa rama ni integré allí el inbox.

Hay cambios locales de versiones m-24828906 en `Qualify/`, `packages/api/`,
`packages/shared/src/qualify_shared/db/session.py`, pruebas y `reflex.lock/`, además de
archivos nuevos de versiones y la antigua migración `0102_piece_versions.py`. Preserva
todo el árbol de trabajo; no hagas un reset ni una limpieza de archivos sin revisar.

Cambios de instrucciones de este agente que también debes conservar:

- `AGENTS.md`: archivo local no versionado; contiene las reglas nuevas.
- `.claude/skills/qualify-pr/SKILL.md`: modificado localmente en la carpeta principal y
  publicado también en los commits del PR; ambas copias incluyen las últimas reglas.
- Este archivo de traspaso: local, no versionado en el PR del inbox.

Reglas persistidas:

1. Antes de crear o publicar cualquier PR, ejecutar `ux-designer` y `review-agent`;
   registrar sugerencias, resultados y limitaciones, y corregir defectos confirmados.
2. No hacer merge ni habilitar auto-merge sin aprobación explícita para ese merge.
   Crear o revisar el PR y tener CI verde no conceden esa autorización.
3. Antes de cerrar el PR por merge o sin merge, actualizar el ticket de Meegle con
   alcance final, estado real, enlace al PR, validación y pendientes, y leerlo de vuelta
   para comprobarlo. No marcar como entregado lo que aún no se entregó.

## Base de datos y migraciones

**Este PR del inbox no agrega una migración propia. No ejecuté migraciones, resets ni
reconciliaciones sobre la BD local.**

Estado comunicado por el agente del replicador y confirmado en los archivos:

- La BD local marca la antigua `0102`, correspondiente a `piece_versions` en la carpeta principal.
- En `origin/main` existe `0102_connection_runtime_health.py`.
- En `origin/main`, `piece_versions` pasó a `0103_piece_versions.py`.
- El respaldo local está listo y la conciliación está preparada, todavía sin ejecutar.
- La conciliación para conservar las versiones y los videos locales queda exclusivamente
  a cargo del agente del replicador durante la actualización. Este agente no tocará esa BD.

El guard de pruebas local detectó la discrepancia y evitó usar esa base; las pruebas
con PostgreSQL/Redis del PR se verifican en los contenedores limpios de GitHub Actions.

## Continuación coordinada

Puedes preservar los cambios anteriores, actualizar e integrar el replicador según la
tarea autorizada, ejecutar tu conciliación preparada y arrancar Reflex en `w3:pB`.
El PR del inbox permanece separado y abierto. No hay más escrituras locales previstas
de este agente después de este traspaso; el CI pendiente es remoto.
