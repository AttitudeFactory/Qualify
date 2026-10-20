<!--
El ticket de Meegle va como m-<número> (el número de la URL del ticket):
  rama:    feat/m-24789646-dm-propuesto
  título:  feat(conversations): borradores de DM desde comentarios (m-24789646)
  aquí:    Resolves m-24789646
Abrir el PR pasa el ticket a revisión y el merge lo pasa a Done. Sin «m-» no se enlaza.
-->

## Ticket de Meegle

Resolves m-<número>

## Qué trae

<!-- Una o dos frases: qué cambia y por qué. Enlaza el issue / doc / ADR si aplica. -->

## Verificación

- [ ] Rama, título y descripción llevan `m-<número>` del ticket de Meegle
- [ ] `just ci-lint` y `just ci-test` en verde localmente (o el run de `ci` en este PR)
- [ ] Si toca `migrations/postgres/`: `just migrate-down` → `just migrate` lo deja limpio
- [ ] Si toca `packages/render/`: `npm run typecheck` pasa
- [ ] Docs / `CLAUDE.md` actualizados cuando cambia un comando, una tabla o una decisión

## Fuera de alcance

<!-- Lo que este PR deliberadamente NO hace, para que nadie lo busque aquí. -->
