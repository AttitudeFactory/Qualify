# Video por partes — propuesta de experiencia (clips y avatares)

`[propuesta ux-designer · 2026-11-02 · sin probar en la app]`

> **No es una revisión en la app:** el encargo prohibía abrir el navegador (regla 7). Lo que dice
> «hoy» sale del código de `main` del 2026-11-02, citado con su línea. El diseño de arquitectura que se
> escribe en paralelo (`docs/diseno-video-por-planos.md`) estaba vacío y, al cerrar este documento, ya no
> estaba en el disco. Lo que depende de él o del cobro aparece como pregunta (§7).
> `[F]` decisión del fundador · `[E]` evidencia en el repositorio · `[H]` hipótesis a validar (§7).

## 1. Quién y para qué

- **Quién:** el dueño de un local de comida (Bianki, Polette), una inmobiliaria o una agencia de
  viajes. Lo usa desde el celular, con una mano y entre cliente y cliente `[E]` (perfil §2).
- **Para qué:** vio un reel que funciona y quiere **uno igual con su producto**, o quiere un
  video de 15–30 s que no sea una sola escena. Ningún diseñador ni editor de video de por medio `[F]`.
- **Qué lo frena:** no sabe qué es un «plano», no quiere decidir seis veces lo mismo y le da miedo
  gastar los videos del mes en algo que salga mal `[H]` (perfil §2, «qué le frena»).

## 2. Nombres en pantalla

Un nombre por cosa (`design-system.md` §7.2): la misma palabra en lista, hoja, estados y avisos.

| Concepto (código / encargo) | En pantalla — propuesta | Alternativas | Por qué |
|---|---|---|---|
| La función | **«Video por partes»** (título del modo y de la hoja) | «Video por escenas» | Dice qué obtiene: un video armado de a pedazos. Sin «planos» ni «secuencia» |
| Entrada desde un reel (hoy «Replicar con mi marca», `Qualify/discover_reels.py:796`) | **«Hacer uno parecido»** | «Hacerlo con mi producto» | Es el nombre de ADR 42 R14 `[F]`. «Replicar» suena a copia exacta y no lo es en las partes con persona (m-24880680) |
| Entrada sin reel | **«Armar mi video por partes»** | «Hacer un video más largo» | Verbo + resultado |
| Plano / mini-clip | **«parte»** («Parte 2 de 5») | «escena» | Es la palabra más común. No se usa «toma», que en «Guion para grabar» ya es lo que graba alguien del equipo (`Qualify/creative_vm.py:869-875`), ni «plano», «clip» o «corte» |
| Modo `edit` | **«Igual al original, con tu producto»** — «Conservamos el movimiento, el fondo y el ritmo; ponemos tu producto y tu marca.» Si la parte viene de un video propio: **«Tu video, con tu marca»** | «Cambiar solo el producto» | Dice qué queda igual y qué cambia: es la «edición del original» de m-24880680 |
| Modo `reference` | Con reel: **«Nueva, inspirada en el original»** — «La creamos de nuevo siguiendo lo que pasa en el original. Se verá distinta y, si aparece una persona, será otra.» Sin reel: **«Nueva, con tu producto»** — «La creamos desde cero con tus fotos y lo que nos cuentes.» | «Hacerla de nuevo» | Explica el cambio de fidelidad que pide m-24880680 («recreación inspirada»). Avisa de antemano que la persona no será la misma |
| Modo `extend` | **«Sigue a la anterior»** — «Empieza justo donde termina la parte anterior, para que se vea como un solo video.» | «Continuación» | Beneficio: que no se note la unión |
| Unir (`concat`) | **«juntar»**: «Juntando tus partes…», y el resultado se llama **«Tu video completo»** | «unir» | Pasa sin que el dueño toque nada (§3e). No hace falta un botón |
| Aprobar una parte | **«Me gusta así»** → estado **«Lista»** | «Usar esta» | **«Aprobar» se reserva para la publicación entera**, porque es lo que gasta videos del mes (`modelo-cobro-generacion.md` D6). Dos «Aprobar» con efectos distintos confunden |
| Regenerar una parte | **«Crear otra versión»** (desde la hoja de la parte) | «Probar de nuevo» | Igual que hoy «Pedir otra versión» (`Qualify/creative_pages.py:2551`), pero de una parte |
| Borrador 480p / final 1080p | **«Vista previa»** / **«video final»**, como hoy | — | `Qualify/creative_vm.py:1255`; no se inventa otra palabra |
| Persona detectada (`people_presence=observed`) | Etiqueta **«Aparece una persona»** | «Hay alguien en esta parte» | Nunca «rostro real», «persona real» ni el código del proveedor. Si no se vio a nadie **no se pone etiqueta**, y tampoco se dice «sin personas», porque el análisis no certifica que no haya (m-24880680, D2) |

**Estados de una parte** (siempre con `signal_pill`, punto + palabra, nunca solo color — P1):

| Estado | Palabra | Tono |
|---|---|---|
| Configurada, sin crear | Sin crear | `neutral` |
| Esperando turno | En fila | `neutral` |
| Generándose | Creando | `info` |
| Vista previa lista, sin revisar | Para revisar | `warn` |
| El dueño dijo «Me gusta así» | Lista | `ok` |
| El proveedor falló | No salió | `error` |
| El proveedor rechazó el original por la persona | No se pudo con el original | `warn` |
| Sigue a una parte que cambió | Hay que rehacerla | `warn` |
| Su vista previa venció (7 días) | Venció | `warn` |

Palabras que este flujo **no** usa en pantalla: plano, corte, edit, extend, reference, render,
prompt, referencia a secas, Brand Kit, CTA, mini-clip, timeline, concatenar, 480p/1080p.

## 3. Flujo guiado de punta a punta

### 3.0 Tres decisiones de forma (propuestas)

1. **No es un tipo de publicación nuevo: es un Clip (o un Avatar) con más de una parte.** Un video de
   una parte **es** el Clip de hoy; «Añadir parte» lo convierte en video por partes. No se suma una
   séptima opción a «¿Qué creamos?» (`Qualify/creative_vm.py:869-916`).
2. **Las partes se arman en el paso 2 y se crean en el paso 5**, como las diapositivas de la Galería, y
   se ajustan una por una en el resultado. Se respeta el marco de 5 pasos firmado (PASOS-5,
   `Qualify/creative_state.py:572-580`, `:1956-1994`). Para probar barato, el paso 5 ofrece
   **«Probar solo la parte 1»**.
3. **La propuesta de la IA llega completa y con todo elegido** (forma, descripción y fotos de cada
   parte). El caso común se resuelve con «Siguiente» tres veces y «Crear».

```
Ideas para tus reels ── «Hacer uno parecido» ──┐
                                               ▼
Crear publicación › Clip/Avatar ── «Armar mi video por partes» ──► Paso 2 Qué mostrar: «Tu video, parte por parte»
   ─► Paso 3 Qué decir (ya rellenado) ─► Paso 4 Cómo la quieres (reel 9:16) ─► Paso 5 Revisa y crea
   ─► Tu publicación: las partes se crean una a una ─► Tu video completo (vista previa) ─► Aprobar
   ─► video final ─► Por aprobar / Tu semana (como hoy)
```

### 3a. Entradas

**Entrada A: desde «Ideas para tus reels».** Hoy la tarjeta dice «Replicar con mi marca», y la ayuda
habla de «base» y «planos» (`Qualify/discover_reels.py:787-805`, `:39-42`). Propuesta: botón **«Hacer
uno parecido»** (≥ 44 px) y ayuda en `size="2"`: **«Lo hacemos con tu producto y tu marca, parte por
parte. Lo revisas antes de crear nada.»** Al tocarlo se abre `/create?paso=1` con la cabeza «‹ Ideas para tus
reels» (N7), y la espera usa `progress_panel`, nunca un spinner:

```
375 px ───────────────────────────────┐
│ ‹ Ideas para tus reels   Paso 2 de 5 │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░ │
│ Qué mostrar                          │
├──────────────────────────────────────┤
│ [portada]  @smash_hiro · 18 s        │
│ Mirando el reel                      │
│ Encontramos 4 partes                 │ ← etapa en curso, encima de la barra
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░      │
│ Puedes salir: guardamos lo que       │
│ encontremos.                         │
├──────────────────────────────────────┤
│ [Atrás]          [ Siguiente ]       │ (desactivado)
│ Disponible cuando terminemos de      │
│ mirar el reel.                       │
│            Seguir después            │
└──────────────────────────────────────┘
```

Etapas, en este orden: «Bajando el video» · «Mirando qué pasa» · «Encontramos {n} partes» ·
«Revisando si aparece alguien» · «Armando tu propuesta». Con `value` real si el análisis lo
informa; si no, avance por tiempo.

**Entrada B: sin reel.** En el paso 2 de un Clip o de un Avatar, debajo de lo que se ve hoy,
aparece una tarjeta: **«¿Quieres un video más largo? Armar mi video por partes»**. Al tocarla, se hace
una sola pregunta, ya rellenada con el producto elegido:

```
375 px ───────────────────────────────┐
│ ¿De qué trata tu video?              │
│ [Smash doble: de la plancha a la    ]│
│ [mano, para pedir hoy por WhatsApp. ]│
│ Ej.: «Cómo preparamos el combo y     │
│ dónde pedirlo».                      │
│ [  Proponerme las partes  ]          │ ← principal: la IA arma 3 o 4
│ [  Prefiero armarlas yo   ]          │ ← abre 2 partes vacías
└──────────────────────────────────────┘
```

Esa frase llena el paso 3 («Qué decir»), así el dueño no la escribe dos veces. Mientras se arma
la propuesta se ve un `progress_panel` «Armando tu propuesta», con las etapas «Pensando el comienzo» ·
«Mostrando tu producto» · «Cerrando con la invitación».

### 3b. Revisar el plan: «Tu video, parte por parte» (paso 2)

```
ESCRITORIO (bajo la cabeza del paso 2, la misma de arriba) ──────────────────────┐
│ Tu video, parte por parte                    Basado en un reel de @smash_hiro ↗│
│ 4 partes · 18 s. Te proponemos cómo hacer cada una; cambia solo lo que quieras.│
│ ┌────┐ Parte 1 · 5 s                                      [Cambiar] [Quitar]  │
│ │img │ Manos arman la hamburguesa sobre una mesa negra.                       │
│ └────┘ ● Igual al original, con tu producto                                   │
│ ┌────┐ Parte 2 · 4 s  [Aparece una persona]               [Cambiar] [Quitar]  │
│ │img │ Un chico muerde la hamburguesa y sonríe a cámara.                      │
│ └────┘ ● Nueva, inspirada en el original                                      │
│        Aquí aparece una persona: la hacemos nueva con tu producto. Será otra. │
│ ┌────┐ Parte 3 · 5 s · ● Sigue a la anterior              [Cambiar] [Quitar]  │
│ ┌────┐ Parte 4 · 4 s · ● Nueva, inspirada en el original  [Cambiar] [Quitar]  │
│ [ + Añadir parte ]                                                            │
│ ┌ Lo que usa de tu mes ────────────────────────────────────────────────────┐  │
│ │ Crear las 4 partes usa 4 vistas previas. Te quedan 12.                   │  │
│ │ Al aprobar usas 18 de tus 40 segundos de video del mes. Te quedarían 22. │  │
│ └──────────────────────────────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────────────────────────────┤
│ [Atrás]                                                   [   Siguiente   ]   │
│                                Seguir después                                 │
└───────────────────────────────────────────────────────────────────────────────┘
```

```
375 px (la misma lista, vertical) ────┐
│ Tu video, parte por parte            │
│ 4 partes · 18 s · Ver el reel ↗      │
│ ┌──┐ Parte 1 · 5 s                   │
│ └──┘ Manos arman la hamburguesa.     │
│      ● Igual al original, con tu     │
│        producto                      │
│      [  Cambiar  ] [  Quitar  ]      │
│ ┌──┐ Parte 2 · 4 s                   │
│ └──┘ [Aparece una persona]           │
│      ● Nueva, inspirada en el        │
│        original. Será otra persona.  │
│      [  Cambiar  ] [  Quitar  ]      │
│ … [ + Añadir parte ]                 │
└──────────────────────────────────────┘
```

- **En 375 px**, sin desplazamiento lateral: miniatura de 72 px y «Cambiar» / «Quitar» a media fila, ≥ 44 px.
- **El porqué** (línea gris) aparece solo cuando la IA no eligió «Igual al original»: hay una persona,
  la parte es muy corta o no tiene video.
- **Quitar** no pide confirmación. En el mismo lugar se lee «Quitaste la parte 3. **Deshacer**» (N3).
- **Añadir parte** abre §3c con «Nueva, con tu producto» elegida. El máximo es 6 `[F]`; al llegar, el
  botón dice «Tu video ya tiene 6 partes, el máximo.»
- **«Siguiente»** nunca se bloquea: lo que falta lo dice el paso 5, como hoy
  (`Qualify/creative_state.py:3678-3683`).
- **Si alguien habla a cámara** en un Clip, un `callout` **ofrece** el cambio y nunca lo hace solo
  (m-24880680): «En este reel alguien habla a cámara. ¿Quieres que lo diga tu presentador?»
  **[Sí, con mi presentador]** **[No, seguir así]** (→ §3f).

### 3c. Ajustar una parte (hoja `drawer`: a la derecha en escritorio, pantalla completa en el celular)

Tres decisiones a la vista (cómo se hace, qué pasa, con qué fotos); el resto, en «Más opciones» (N6).
Es el patrón de la diapositiva de la Galería (`Qualify/content_generator.py:2922-3120`).

```
375 px ───────────────────────────────┐
│ Parte 2 de 4              ✕ Cerrar   │
├──────────────────────────────────────┤
│ [▶ el original, 4 s]                 │
│ ¿Cómo la hacemos?                    │
│ ( ) Igual al original, con tu        │ ← desactivada
│     producto. Aquí aparece una       │
│     persona y no podemos usar ese    │
│     video.                           │
│ (•) Nueva, inspirada en el original. │
│     La persona será otra.            │
│ ( ) Sigue a la anterior. Empieza     │
│     donde termina la parte 1.        │
│ ¿Qué pasa en esta parte?             │
│ [Un chico muerde la hamburguesa y   ]│ ← lo que vio la IA, editable
│ [sonríe a cámara.                   ]│
│ Ej.: «Una mano acerca el vaso».      │
│ Fotos de tu producto                 │
│ [foto 1 ✓] [foto 2 ✓] [+ Agregar]    │ ← las del paso 1
│ ▸ Más opciones (video o audio tuyo,  │
│   mover antes o después)             │
├──────────────────────────────────────┤
│ [Quitar parte]       [  Guardar  ]   │
└──────────────────────────────────────┘
```

| Forma | Cuándo no se puede | Texto debajo de la opción (nunca solo en gris) |
|---|---|---|
| Igual al original | Se vio una persona | «Aquí aparece una persona y no podemos usar ese video.» |
| Igual al original | Dura menos de 4 s (el proveedor no edita menos: `omnihuman-caras-reales-y-edicion-seedance.md` §2.4) | «Esta parte dura {s} s y para conservar el original necesita al menos 4. Júntala con la siguiente o hazla nueva.» + botón **«Juntar con la siguiente»** |
| Igual al original | Parte sin video (entrada B) | «Necesita un video. Agrega uno tuyo en Más opciones.» |
| Sigue a la anterior | Es la parte 1 | «La primera parte no tiene una anterior.» |

- **En el resultado** (§3e), el pie de la hoja cambia a **«Crear otra versión»** y **«Me gusta así»**,
  con la línea «Usa 1 vista previa. Te quedan 11.»
- **«Crear todas»** está en el paso 5 («Crear las 4 partes»). En el resultado, una parte sin crear
  muestra «Crear esta parte».
- **«Sigue a la anterior»** obliga a crear en orden: la fila dice «Se crea cuando esté la parte 2».

### 3d. Crear y esperar por partes (paso 5 → «Tu publicación»)

**Paso 5, «Revisa y crea»**, resume en palabras («Un reel de 18 s en 4 partes, con tu smash doble.
Dos conservan el original y dos se hacen nuevas.») y muestra lo que usa del mes. Botón principal: **«Crear las 4
partes»**. Secundario: **«Probar solo la parte 1»** («Usa 1 vista previa. Las demás las creas después.»).

El resultado **no se bloquea**: cada parte avanza sola y se puede revisar en cuanto está. Arriba hay un
`progress_panel` con `value` real (partes con vista previa ÷ total); cada fila lleva su `signal_pill`, sin spinner.

```
375 px ───────────────────────────────┐
│ Tu publicación (resultado del paso 5)│
├──────────────────────────────────────┤
│ Creando tus partes                   │
│ 2 de 4 listas                        │ ← comentario de etapa encima de la barra
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░      │
│ No tienes que esperar aquí: cuando   │
│ estén, aparecerán en Por aprobar.    │
│ ┌──┐ Parte 1 · 5 s   ● Para revisar  │
│ └──┘ [ Ver y decidir ]               │
│ ┌──┐ Parte 2 · 4 s   ● Creando       │
│ ┌──┐ Parte 3 · 5 s   ● En fila       │
│      Se crea cuando esté la parte 2. │
│ ┌──┐ Parte 4 · 4 s   ● No salió      │
│      No pudimos crearla. Te          │
│      devolvimos la vista previa.     │
│      [Intentar de nuevo] [Cambiar] … │
└──────────────────────────────────────┘
```

**Si una parte falla, el resto sigue.** Nada se reintenta ni cambia de forma sin que el dueño lo decida:

- **No salió:** «Intentar de nuevo» · «Cambiar» · «Quitar parte».
- **No se pudo con el original:** el proveedor rechazó el video aunque el análisis no viera a nadie,
  porque no ver a nadie no garantiza que no haya (m-24880680 D2). Botones **[Hacerla nueva]** **[Quitar parte]**, con el
  texto de §4.
- **Hay que rehacerla** (cambió la parte anterior): «La parte 2 cambió y esta empieza donde
  terminaba. Créala otra vez para que siga bien.» Botón **[Crearla otra vez]**.

### 3e. Revisar cada parte y el video completo; aprobar

**Una parte** se abre en la hoja de §3c con «Original» y «Tu versión», uno al lado del otro en escritorio y uno debajo del otro
en 375 px. Botones: **«Me gusta así»** (pasa a «Lista») o **«Cambiar y crear otra versión»**, con los tres
campos ya rellenados: así se rehace solo esa parte. «Versión 2 de 2 · Ver la anterior» permite volver a la de antes.

**«Tu video completo»** aparece **solo**, sin botón «Unir», cuando todas las partes tienen vista
previa, y se vuelve a juntar si una cambia. Mientras tanto, su cabecera lleva `signal_pill` «Juntando» (`info`)
y la frase «Juntando tus partes…», sin spinner y sin bloquear nada.

```
ESCRITORIO (debajo de la lista de partes) ───────────────────────────────────┐
│ Tu video completo · 18 s · [Vista previa]                                   │
│ ┌──────────────┐  Es una vista previa en calidad baja, para que decidas     │
│ │   ▶ video    │  rápido. Al aprobarla preparamos cada parte en alta calidad │
│ │   9:16       │  y las juntamos.                                           │
│ └──────────────┘  Apruébalo antes del jueves 6 de noviembre para tener el   │
│                   video final.                                              │
│ [ Aprobar ]  Al aprobar usas 18 de tus 40 segundos de video del mes.        │
│              Te quedarían 22 segundos.                                      │
│ [ Cambiar una parte ]   [ Descartar ]                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **«Aprobar»** se activa cuando todas las partes tienen vista previa y ninguna está en «No salió», «Hay que
  rehacerla» o «Venció». Si no, junto al botón se lee el aviso de lo que falta: «Disponible cuando las 4 partes
  tengan su vista previa.», «Disponible cuando cambies la parte 2.» (no salió o hay que rehacerla) o «Disponible
  cuando crees otra vez la parte 3.» (venció). Junto al botón, lo que usa de tu mes **en segundos** (ADR 44 F1,
  VE-21): «Al aprobar usas 18 de tus 40 segundos de video del mes. Te quedarían 22 segundos.»
  «Me gusta así» es **opcional**: sirve para recordar qué ya se revisó.
- **«Pedir otra versión»** de la publicación entera (`Qualify/creative_pages.py:2551-2560`) pasa a ser **«Cambiar
  una parte»**: rehacer las 4 partes por un detalle gastaría 4 vistas previas. Después de aprobar, todo sigue como hoy
  (`approval_notice`, `Qualify/creative_vm.py:1148`) hasta «Elegir día y hora» (N3).
- **Vencimiento:** cada parte vence 7 días después de su vista previa, y la publicación muestra la **fecha más cercana**.
  Un solo botón que nombra las partes, **«Crear la parte 3 otra vez»** («Crear las partes 2 y 3 otra vez»), rehace
  **solo las partes vencidas**: «Crea otra vez la parte 3. Usa 1 vista previa. Te quedan 9 vistas previas.» Si no
  alcanzan: «… y este mes te queda 1 vista previa. Vuelven el 1 de diciembre.»

### 3f. Con presentador (Avatar)

En un Avatar, cada parte responde «¿Quién aparece?»: **«Tu presentador»** (habla a cámara) o **«Solo tu
producto»**. La propuesta por defecto pone al presentador en la **primera** parte (el comienzo) y en la
**última** (la invitación), y deja tu producto en las del medio `[H]`.

```
375 px ── fila de una parte de Avatar ┐
│ ┌──┐ Parte 1 · ≈ 6 s                │
│ └──┘ ¿Quién aparece?                │
│      (•) Tu presentador ( ) Solo tu │
│          producto                   │
│      Dice: «¿Ya probaste el smash   │
│      doble?» (de tu guion)          │
└─────────────────────────────────────┘
```

- **El dueño decide:** quién presenta (el de Tu marca, como hoy), qué se dice (un solo guion en el paso
  3, que se reparte solo entre las partes con presentador) y en qué partes aparece.
- **No decide:** cuánto dura una parte con presentador (lo que tarda en decir su frase; «≈ 6 s» se muestra
  pero no se cambia), la sincronía de labios ni el modelo.
- Una parte con presentador **nunca es «Igual al original»**, porque OmniHuman no se edita después
  (`omnihuman-caras-reales-y-edicion-seedance.md` §6). **Un Clip nunca pasa a Avatar porque se vio a
  una persona** (m-24880680): pasa solo si el dueño toca «Sí, con mi presentador» (§3b) o elige Avatar. Ver P3 en §7.

## 4. Estados y mensajes (copy listo para pegar)

| Situación | Texto en pantalla | Acción |
|---|---|---|
| Plan vacío (entrada B, «Prefiero armarlas yo») | **Tu video todavía no tiene partes.** Agrega la primera: cuenta qué pasa y elige las fotos de tu producto. | [Añadir parte] |
| Analizando el reel | **Mirando el reel** · etapa en curso · «Puedes salir: guardamos lo que encontremos.» | — |
| Sin partes que separar | **Este reel no cambia de escena.** Lo hacemos como una sola parte; si quieres, agrega otras. | [Añadir parte] [Siguiente] |
| No se pudo analizar | **No pudimos mirar este reel.** Inténtalo de nuevo o arma tu video por partes sin él. | [Intentar de nuevo] [Armar sin el reel] |
| Parte con persona (plan) | Aquí aparece una persona: la hacemos nueva con tu producto. La persona será otra. | [Cambiar] |
| Parte en fila | En fila. Se crea cuando termine la anterior. | — |
| Parte fallida | No pudimos crear esta parte. Te devolvimos la vista previa. | [Intentar de nuevo] [Cambiar] [Quitar parte] |
| Rechazada por persona | No pudimos usar el original en esta parte porque parece que aparece una persona. Podemos hacerla nueva, inspirada en el original; la persona será otra. Te devolvimos la vista previa. | [Hacerla nueva] [Quitar parte] |
| Vista previa vencida (7 días) | La vista previa de la parte {n} venció. Créala otra vez para tener el video final. | [Crear la parte {n} otra vez] |
| Sin vistas previas suficientes | Crear las {n} partes usa {n} vistas previas y te quedan {p}. Crea primero las {p} que más te importan o espera al {día}, cuando vuelven tus {cupo}. | [Crear {p} partes] |
| Sin videos suficientes (si rige D5, §7 P1) | Tu video tiene {n} partes y este mes te quedan {v} videos. Quita {n−v} partes o espera al {día}, cuando vuelven tus {cupo}. | [Quitar partes] |
| Reel sin video para bajar | No pudimos bajar el video de este reel; a veces la red lo retira. Elige otro o arma tu video por partes sin él. | [Elegir otro reel] [Armar sin el reel] |
| No se pudieron juntar las partes | No pudimos juntar tus partes. Siguen guardadas y no se descontó nada. Toca «Juntar otra vez». | [Juntar otra vez] |
| Final de una parte fallido | No pudimos preparar en alta calidad la parte {n}. Inténtalo de nuevo; no usa otro video. | [Reintentar] |

Los textos de cupo siguen el patrón que ya existe (`not_enough_creations_text`, `previews_short_text`,
`videos_short_text`, `Qualify/creative_vm.py:1929-2052`). Nunca muestran dinero (ADR 42 §2.9;
`modelo-cobro-generacion.md` D1). Reemplazan a `REAL_PERSON_TEXT`
(`packages/api/src/qualify_api/creative/media.py:749`, «…Usa otra foto.»), que habla de una foto
cuando lo rechazado es un video.

## 5. Accesibilidad y móvil

- **375 px:** las partes van en una lista vertical (`role="list"`), nunca en un carrusel lateral. Cada fila se anuncia
  completa: «Parte 2 de 4, 4 segundos, nueva inspirada en el original, para revisar».
- **Foco:** «‹ destino» → `h1` → enlace al reel ↗ → «Cambiar» y «Quitar» de cada parte → «Añadir parte» →
  pie. La hoja retiene el foco, que empieza en «¿Cómo la hacemos?». Esc la cierra y devuelve el foco al «Cambiar»
  de esa fila.
- **Lector de pantalla:** **una** región `aria-live="polite"` por pantalla («Parte 3 lista para
  revisar», «La parte 4 no salió»). La barra lleva `aria-valuetext="2 de 4 partes listas"`.
- **Táctil:** todo ≥ 44 px. En la hoja, el pie queda fijo y el teclado no lo tapa (design-system §4.5).
- **Sin arrastrar:** si se reusa el arrastre de la Galería (`slide-drag.js`), siempre con «Mover
  antes / Mover después».
- **Opciones desactivadas:** `aria-disabled` + `aria-describedby` que apunta al motivo, que siempre se lee escrito.
- **Videos:** `controls`, sin sonido automático, con portada y etiqueta («Vista previa de la parte 2»). Con
  `prefers-reduced-motion` no se repiten en bucle.
- **Direcciones (N5):** `/create?paso=1` y, con la hoja abierta, `&parte=3`. El «atrás» del celular cierra la hoja
  antes de cambiar de paso.

## 6. Dónde vive y cómo convive

Vive en **Crear publicación** (`/create`, `Qualify/ui/layout.py:82`); en `/drafts/<id>` se ilumina **«Por aprobar»**,
y su tarjeta dice «Video en 4 partes · 1 para revisar».

| Caso | ¿Misma pieza? | Dónde | Qué ve el dueño |
|---|---|---|---|
| Clip de una parte (el de hoy) | Misma | Paso 2 | Lo de hoy, más la tarjeta «Armar mi video por partes» |
| «Añadir parte» en un Clip | Misma | Paso 2 | Lo que tenía pasa a ser la «Parte 1» |
| Hacer uno parecido (Ideas) | Pieza nueva (Clip) | Paso 2 | Cabeza «‹ Ideas para tus reels»; se guarda el reel de origen (m-24820837) |
| Cambiar una parte ya creada | Misma, versión nueva de esa parte | Resultado | La hoja de la parte |
| Galería (carrusel) | Otra pieza | Su paso 2 | Su descripción suma: «Varias fotos o videos que se deslizan. Si quieres **un solo video** armado por escenas, usa Clip por partes.» |
| Extender video (m-24880328) | Otra pieza; el original queda intacto | Hoy, módulo propio | **Propuesta (P5):** que sea una tercera entrada a este flujo: «Alargar un video que ya tienes» crea un video por partes con **Parte 1 = tu video** (fija) y **Parte 2 = «Sigue a la anterior»**. Así hay un nombre para cada cosa y una sola forma de continuar |
| Procedencia | — | Detalle de la pieza | La sección «Reel de referencia» de hoy (`Qualify/creative_pages.py:2245-2275`) suma, por parte: «Basada en 0:04–0:08 del reel» |

## 7. Riesgos de experiencia, preguntas al fundador y qué validar

**Preguntas al fundador (bloquean el copy de cupo o el plan):**

- **P1 — ¿Cuántos videos del mes usa un video por partes?** Hoy rige D5 (`modelo-cobro-generacion.md`:
  «un carrusel con N diapositivas animadas usa N videos»). Con esa regla, **6 partes = 6 videos, y el plan Básico trae 4**:
  el video no se podría terminar. Opciones: (a) 1 parte = 1 video, con tantas partes como videos queden;
  (b) contar por los segundos del video completo; (c) contarlo como 1 video, con una vista previa por parte. La
  pantalla necesita **una sola cifra** antes de «Crear». La decisión es de `qualify-business-decisions`, no de UX.
- **P2 — ¿Una parte es siempre un corte del reel?** Muchos reels cambian de escena cada 1–3 s, e «Igual al
  original» necesita ≥ 4 s. Propuesta: la IA **junta cortes seguidos en partes de 4–10 s**, con un máximo de 6. Si no se
  juntan, casi todas las partes saldrían «nuevas» y el cupo no alcanzaría.
- **P3 — Avatar:** ¿se oye la voz del presentador durante las partes de producto? ¿Las partes con
  presentador tienen vista previa barata, o se crean directo en alta calidad y gastan creaciones? Lo
  define `docs/diseno-video-por-planos.md` §6, y el copy de §3f depende de la respuesta.
- **P4 — ¿Mirar el reel usa algo del mes?** Se recomienda que no: cuesta milésimas de dólar (m-24880680). Si es así,
  la espera puede decir «No usa tus videos del mes».
- **P5 — ¿«Extender video» es la entrada C de este flujo** o un módulo aparte? (§6)
- **P6 — «Igual al original» conserva las manos y el fondo de otra cuenta.** La réplica fiel ya está
  decidida (m-24820836). ¿Debe recordarlo la pantalla antes de aprobar?

**Riesgos de experiencia (hipótesis):**

| # | Riesgo `[H]` | Qué lo mitiga aquí |
|---|---|---|
| H1 | Con 4–6 partes, el dueño se cansa de decidir | Propuesta completa por defecto; «Crear» llega en 4 toques |
| H2 | Espera una copia idéntica y las partes nuevas se ven distintas | Cada parte dice cómo se hace y por qué; «La persona será otra» |
| H3 | Las partes no casan entre sí (luz, aspecto del producto) | Las mismas fotos en todas las partes; «Sigue a la anterior» |
| H4 | Gasta el cupo del mes en un solo video y se frustra | «Lo que usa de tu mes» antes de crear; «Probar solo la parte 1» |
| H5 | Crear tarda minutos, se va y no vuelve | Nada se bloquea; la pieza aparece en Por aprobar; «Seguir después» |

**Prueba con 3 dueños** (Bianki, Polette y la agencia de viajes; perfil §5): 15 minutos con una maqueta en
HTML en el celular, mientras se anotan sus palabras literales.

1. «¿Qué crees que es una “parte” de tu video?» (§5.4, H1). Se cumple si lo explica sin usar «plano».
2. Se le muestra la parte con persona: «¿Qué crees que va a pasar con esta parte?» (§5.6, H2).
3. «¿Cambiarías algo antes de crear o tocarías “Crear” de una?» (H1). Se cuentan los toques.
4. «Este video usa 4 de tus 4 videos del mes. ¿Lo harías igual?» (§5.7, H4 y P1).
5. «¿Te preocupa que se parezca demasiado al de otra cuenta?» (§5.8, P6).
6. «Si tarda 5 minutos, ¿esperas aquí o te vas? ¿Dónde lo buscarías después?» (§5.3, H5).

Cada respuesta actualiza `docs/perfil-cliente-pyme.md` y pasa de `[H]` a `[E]`, con quién y cuándo.

## 8. Historias de UI para reflex-ui-engineer

Solo primitivas existentes (`step_frame`, `drawer`, `progress_panel`, `signal_pill`, `callout`, `empty_state`); cada una se
verifica en el navegador a 375 px y en escritorio; el backend lo define `docs/diseno-video-por-planos.md`.

| Id | Título | Pantalla / estado | Criterios de aceptación verificables | Tam. | Depende de |
|---|---|---|---|---|---|
| UI-1 | Generador: «Hacer uno parecido» en Ideas | Tarjeta de Ideas → «Qué mostrar» (paso 1) | El botón dice «Hacer uno parecido» y la ayuda «Lo hacemos con tu producto y tu marca, parte por parte. Lo revisas antes de crear nada.» con `size="2"`; abre `/create?paso=1` con la cabeza «‹ Ideas para tus reels»; no queda «Replicar» en texto visible | S | — |
| UI-2 | Generador: espera del análisis del reel | «Qué mostrar» (paso 1), analizando | `progress_panel` con las 5 etapas de §3a, la etapa encima de la barra y ningún spinner; «Siguiente» desactivado con «Disponible cuando terminemos de mirar el reel.»; los estados «no cambia de escena», «No pudimos mirar este reel» y «reel sin video» con los textos de §4 y sus botones | M | Análisis guardado y reanudable si el dueño sale (m-24880681) |
| UI-3 | Generador: lista «Tu video, parte por parte» | «Qué mostrar» (paso 1), plan | Lista vertical en 375 px sin desplazamiento horizontal; por parte: miniatura, «Parte n · s», descripción, `signal_pill` de la forma, «Aparece una persona» cuando corresponde, la línea del porqué, «Cambiar»/«Quitar» ≥ 44 px; «Quitaste la parte n. Deshacer»; tope de 6; «Lo que usa de tu mes» sin dinero; el aviso de presentador de §3b | L | UI-2 |
| UI-4 | Generador: hoja de una parte | `drawer` | Tres opciones con su línea; las desactivadas, con el motivo de la tabla de §3c y `aria-describedby`; descripción editable con ejemplo; fotos del producto ya puestas; video/audio y «Mover antes/después» bajo «Más opciones»; `&parte=n` en la URL y el «atrás» cierra la hoja; foco en el grupo de opciones y Esc lo devuelve a la fila | M | UI-3 |
| UI-5 | Generador: armar por partes sin reel | «Qué mostrar» (paso 1) de Clip/Avatar | Tarjeta «¿Quieres un video más largo? Armar mi video por partes»; una pregunta ya rellenada; «Proponerme las partes» (`progress_panel` «Armando tu propuesta») y «Prefiero armarlas yo» (2 vacías con el estado vacío de §4); la frase llena el paso 3; un Clip de una parte se ve igual que hoy | M | UI-3 |
| UI-6 | Generador: revisa y crea por partes | Paso 5 | Resumen en palabras de §3d; «Crear las n partes» y «Probar solo la parte 1»; textos de cupo de §4 cuando no alcanza; no se crea ninguna parte si falta cupo (todo o nada, como hoy) | S | UI-3, P1 |
| UI-7 | Generador: progreso y fallos por parte | Resultado | `progress_panel` con `value` = partes con vista previa ÷ total; `signal_pill` por fila con los 9 estados de §2; una región `aria-live`; «No salió», «No se pudo con el original» y «Hay que rehacerla» con sus botones, sin cambiar nunca la forma solo; no bloquea la pantalla | L | UI-6 |
| UI-8 | Generador: revisar y rehacer una parte | Resultado → hoja | «Original» y «Tu versión» (uno al lado del otro en escritorio, uno debajo del otro en 375 px); «Me gusta así» → «Lista»; «Cambiar y crear otra versión» con «Usa 1 vista previa. Te quedan {p}.»; «Versión 2 de 2 · Ver la anterior» | M | UI-7 |
| UI-9 | Generador: video completo y aprobar | Resultado | «Tu video completo» aparece solo; «Juntando tus partes…»; «Aprobar» con el motivo cuando no se puede; «Cambiar una parte» en lugar de «Pedir otra versión»; vencimiento con la fecha más cercana; «Crearla otra vez» rehace solo las partes vencidas | M | UI-7, P1 |
| UI-10 | Generador: avatar por partes | Paso 2 y resultado de Avatar | Por parte, «¿Quién aparece?: Tu presentador / Solo tu producto», con la frase del guion que dice; la duración de las partes con presentador solo se lee; no ofrece «Igual al original» en una parte con presentador; Clip pasa a Avatar solo con «Sí, con mi presentador» | L | UI-3, P3 |
