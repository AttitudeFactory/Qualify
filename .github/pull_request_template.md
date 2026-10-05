## Qué trae

<!-- Una o dos frases: qué cambia y por qué. Enlaza el issue / doc / ADR si aplica. -->

## Verificación

- [ ] `just ci-lint` y `just ci-test` en verde localmente (o el run de `ci` en este PR)
- [ ] Si toca `migrations/postgres/`: `just migrate-down` → `just migrate` lo deja limpio
- [ ] Si toca `packages/render/`: `npm run typecheck` pasa
- [ ] Docs / `CLAUDE.md` actualizados cuando cambia un comando, una tabla o una decisión

## Fuera de alcance

<!-- Lo que este PR deliberadamente NO hace, para que nadie lo busque aquí. -->
