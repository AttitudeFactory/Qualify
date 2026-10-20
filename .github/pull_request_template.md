<!--
Título del PR: termina con el número del ticket de Meegle entre paréntesis, p. ej.
  feat(conversations): borradores de DM desde comentarios (24789646)
La rama también lo lleva: feat/24789646-dm-propuesto
Sin otros números sueltos en el título (Meegle enlaza por [0-9]+). Abrir el PR pasa el
ticket a revisión y el merge lo pasa a Done.
-->

## Ticket de Meegle

<!-- Número(s) del ticket: https://project.larksuite.com/5h2wsx/issue/detail/<número> -->

## Qué trae

<!-- Una o dos frases: qué cambia y por qué. Enlaza el issue / doc / ADR si aplica. -->

## Verificación

- [ ] El título y la rama llevan el número del ticket de Meegle
- [ ] `just ci-lint` y `just ci-test` en verde localmente (o el run de `ci` en este PR)
- [ ] Si toca `migrations/postgres/`: `just migrate-down` → `just migrate` lo deja limpio
- [ ] Si toca `packages/render/`: `npm run typecheck` pasa
- [ ] Docs / `CLAUDE.md` actualizados cuando cambia un comando, una tabla o una decisión

## Fuera de alcance

<!-- Lo que este PR deliberadamente NO hace, para que nadie lo busque aquí. -->
