# Reglas de `main` en GitHub

**Objetivo (fundador, 2026-10-05):** nadie mergea a `main` con el CI en rojo; solo un
administrador del repo puede saltarse la regla, y a propósito.

**Estado:** la organización `AttitudeFactory` está en GitHub **Free** y el repo es privado, y
GitHub devuelve `403 Upgrade to GitHub Pro or make this repository public` tanto para la
protección de ramas como para los rulesets (verificado 2026-10-05 contra la API). Por eso la
regla no puede estar activa hoy.

## Cuando se active (GitHub Team, o repo público)

`ruleset-main.json` es la regla lista: exige PR y exige en verde los jobs de
`.github/workflows/ci.yml` `changes`, `lint`, `test`, `test-db`, `node-render` y `docker-deploy`.
Un job saltado cuenta como verde; por eso `changes` también es requerido: si falla, los jobs que
dependen de él se saltan y sin esa regla pasarían como verdes. También prohíbe borrar o
reescribir `main`, y da bypass **solo** al rol *Admin* del repositorio (`actor_id: 5`,
`RepositoryRole`). Aplicarla es un comando:

```bash
just protect-main
```

(`gh api -X POST repos/AttitudeFactory/Qualify/rulesets --input infra/github/ruleset-main.json`.)
Actualizarla después: `gh api -X PUT repos/AttitudeFactory/Qualify/rulesets/<id> --input ...`.

Costo del plan Team: USD 4 por usuario al mes (la org tiene 7 asientos ocupados; bajar
asientos baja el costo). Decisión D3 de `docs/plan-cicd-staging.md`.

## Mientras tanto: la puerta es `just merge`

Sin regla en GitHub, el botón «Merge» no se bloquea. El acuerdo del equipo es **mergear solo
con `just merge <pr>`**, que se niega si falta algún check requerido o alguno falló; un
administrador puede forzarlo a propósito con `just merge <pr> --admin`, que deja constancia
en el comentario del PR. Los agentes de Claude Code mergean por la misma receta.
