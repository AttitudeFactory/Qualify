# Revisión UX — flujo «Replicar con mi marca» (reels descubiertos)

Revisión hecha solo en código (no se abrió la app en el navegador): no es exhaustiva.
Aplica la checklist `qualify-ux` sobre `Qualify/discover_reels.py`, `Qualify/creative_state.py`,
`Qualify/reel_replication.py` y `Qualify/creative_pages.py` (el flujo no toca creative_pages directamente).

## Hallazgos (rankeados)

1. **`Qualify/content_generator.py:1506-1521`** — El formulario que se abre no dice que se está
   replicando un reel ni qué tiene que hacer el dueño. La vista «Referencias» abre igual que un
   Clip normal y la foto del producto es obligatoria, pero ese requisito solo se entera en el
   «Resumen» (paso 4) con «Elige una foto de tu producto para sustituir el del video original.».
   **Sugerencia:** añadir un callout arriba de `_clip_references_view` cuando
   `CreativeState.clip_videos` contenga un item con `source == "reel"` (nueva var
   `reel_reference_active`): «Estamos usando el ritmo y los movimientos de este reel como guía.
   Agrega una foto de tu producto: será el protagonista. Tu marca y tu texto mandan.»
   Y marcar en el propio bloque «Videos» el item reel como «Movimiento del reel original».

2. **`Qualify/discover_reels.py:39-42` y `:793-797`** — El botón «Replicar con mi marca» y su
   ayuda («Usa los primeros 5 s del reel como base, conservando planos y acciones con tu
   producto y marca, sin su audio. Podrás revisarlo antes de generar.») mezclan feature language
   («planos», «base») y no dejan claro el beneficio. **Sugerencia:** botón «Crear una
   publicación como este reel» (o mantener y reforzar la ayuda); ayuda reescrita:
   «Tomamos el movimiento y el ritmo del video (sin su sonido) y lo hacemos con tu producto
   y tu marca. Lo revisas antes de crearlo.» Hipótesis — validar con pregunta §5.6.

3. **`Qualify/reel_replication.py:21`** — El video importado se llama
   «Referencia de {handle} · {X} s», que no explica su rol (es movimiento, no estilo a copiar).
   **Sugerencia:** «Movimiento del reel original · {X} s (sin sonido)».

4. **`Qualify/reel_replication.py:28,52`** — El prompt al modelo usa «Brand Kit» y «CTA»,
   palabras prohibidas en copy para cliente (aunque sea prompt interno, conviene alinear).
   **Sugerencia:** «tu marca» y «la invitación a comprar».

5. **`Qualify/content_generator.py:3604-3614`** — El campo «¿Qué quieres en el clip?» no indica
   que, al replicar, lo que se escriba aquí es la voz de la marca y que la estructura del reel
   va por detrás. **Sugerencia:** cuando `reel_reference_active`, mostrar bajo el campo:
   «Tu texto es la voz de tu marca; la estructura del reel se usa como guía por detrás.»
   (beneficio: el dueño entiende por qué el campo puede quedar vacío.)

6. **`Qualify/content_generator.py:1506-1521`** — La replicación fija 5 s y sin audio, pero la
   pantalla no lo dice; el dueño solo lo descubre al ver el resultado. **Sugerencia:** en el
   callout del punto 1 añadir «Duración fija de 5 s y sin el sonido original, para mantener el
   ritmo del reel.»

7. **`Qualify/discover_reels.py:787-805`** — El botón tiene `min_height="44px"` (bien), pero el
   estado «Preparando referencia…» reemplaza el icono y el texto sin `aria-live`; un lector de
   pantalla no anuncia el cambio. **Sugerencia:** añadir `aria-live="polite"` al contenedor o
   usar el patrón de spinner con texto ya existente en otros botones.

8. **`Qualify/discover_reels.py:806-811`** — La ayuda bajo el botón es `size="1"` en color
   mutado; en móvil (360 px) queda muy pequeña para leer la promesa clave. **Sugerencia:**
   subir a `size="2"` o convertirla en el callout del punto 1 una vez dentro del formulario.

## Hipótesis a validar (docs/perfil-cliente-pyme.md §5)

- ¿Entiende el dueño «replicar» sin explicación? (pregunta 4 y 6).
- ¿Prefiere que la réplica sea siempre de 5 s o elegir duración? (pregunta 7).
- Marcar `[H]` hasta tener entrevistas.

## Lo que no se revisó

- No se abrió la app en el navegador (regla 7): no se verificó el menú iluminado, el título de
  pestaña ni el back en la ruta `/create?paso=1` tras replicar. Queda pendiente para
  `reflex-ui-engineer` / revisión en Chrome.
- No se revisaron los tests; los cambios sugeridos que tocan strings testeados
  («Replicar con mi marca») requerirán actualizar tests.
