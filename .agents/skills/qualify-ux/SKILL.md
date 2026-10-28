---
name: qualify-ux
description: The UX checklist for anything a Qualify client sees — who the user is (small-business owner in CO/VE/UY, on the phone, short on time), benefit language instead of feature language, the banned-words list, splitting multi-input screens into guided atomic steps by domain, accessibility and mobile basics, and how to report UX suggestions for a PR's «Sugerencias de UX» section. Use when reviewing or designing a screen, flow, empty state, email or message template, and before opening every PR that touches client-facing paths.
---

# Qualify — UX checklist

Start from the person, not the screen: read `docs/perfil-cliente-pyme.md` first. The copy rules
(Spanish only, no slang, errors say what to do next) live in **`qualify-copy-es`** — that skill is
the source of truth for wording; this one adds the product lenses on top of it.

## 1. Lenses, in priority order

1. **Who is this for?** An owner of a small business with a tight or no marketing budget, who
   does not want to deal with marketers and designers but wants a presence on social media; not a
   marketer, on the phone, between customers. Every screen should save them an agency, money or
   time. Ask of every screen: could a shawarma shop owner finish this in two minutes with
   one hand, without asking anyone?
2. **Benefit, not feature.** Titles, buttons, empty states and onboarding say what the owner
   *gets*, not what the tool *has*.
3. **No technical or English words** (§3).
4. **Atomic steps.** One decision per step; repeated processes become a guided sequence (§4).
5. **Accessibility and mobile** (§5).

## 2. Benefit vs feature — rewrites

| ❌ Feature language | ✅ What the owner gets |
|---|---|
| Planificador de contenido | Tus publicaciones de la semana, listas para aprobar |
| Funcionalidad de generación con IA | Crea una publicación con la foto de tu producto en un minuto |
| Brand Kit / Configurar Brand Kit | Tu marca: colores, logo y forma de hablar, para que todo salga con tu estilo |
| Bandeja de entrada / Inbox | Nadie se queda sin respuesta: tus comentarios y mensajes en un solo lugar |
| Intención comercial detectada | Esta persona quiere comprar: respóndele hoy |
| Catálogo de productos (CRUD) | Tus productos, listos para usarlos en publicaciones |
| Conectar cuenta (OAuth) | Conecta tu Instagram para publicar desde aquí |
| Referentes / análisis de competencia | Ideas de lo que le funciona a negocios como el tuyo |
| Métricas de engagement | Cuántas personas vieron, comentaron y te escribieron |

Rule of thumb: if the sentence still makes sense with any other tool's name in it, it is a feature
description — rewrite it around the owner's result (time saved, sales, customers answered).
Never promise what is not built or what contradicts a signed decision (nothing is published or
sent without the owner's approval).

## 3. Banned words (client-facing)

Extends `qualify-copy-es` §1; if they disagree, `qualify-copy-es` wins and this list is fixed.

| Never | Say instead |
|---|---|
| post, posteo | publicación |
| story | historia |
| — | «reel (video corto)» is allowed (founder, 2026-10-23): «reel», with «video corto» as the gloss where the owner picks a format; never «story» |
| feed | tu perfil, tus publicaciones |
| inbox | conversaciones, chats |
| engagement, reach, insights | interacción, cuántas personas lo vieron, resultados |
| dashboard | resumen, inicio |
| Brand Kit | tu marca, identidad de marca |
| prompt | instrucciones, idea, «cuéntanos qué quieres» |
| template | plantilla |
| CTA, call to action | invitación a comprar / a escribir |
| hashtag (en explicaciones largas) | etiqueta (en el botón se acepta «#») |
| upload, download | subir, descargar |
| scheduling, schedule | programar |
| lead | cliente interesado |
| funcionalidad, módulo, feature, configurar, parámetro, token, API | what it does for them (§2) |
| error 4xx/5xx, id interno, nombre de tabla | qué pasó y qué hacer ahora (`qualify-copy-es` §3) |

## 4. Atomic steps by domain

**Smell:** a screen with more than ~3 inputs, inputs from different domains mixed together (brand
+ product + publication), or a process the owner repeats every week done in one long form.

**Pattern:**

1. Group the inputs by **domain** (the thing the owner thinks about: *tu producto*, *tu mensaje*,
   *dónde y cuándo*), one domain per step.
2. **One decision per step**, with the main action as a big verb button («Siguiente», «Aprobar»).
3. **Show progress** («Paso 2 de 4») and always allow **going back** without losing data.
4. **Pre-fill defaults** from what Qualify already knows (identity, last choice, catalog) so a
   repeat run is mostly «Siguiente, Siguiente, Aprobar».
5. **Last step = review in plain words** («Se publicará el jueves a las 7 p. m. en Instagram»), then
   the owner approves.
6. Optional or advanced settings go behind «Más opciones», never on the main path.

**Before / after — creating a piece (illustrative):**

```
ANTES (una pantalla)                 DESPUÉS (pasos cortos)
┌───────────────────────────┐        ① ¿Qué quieres mostrar?
│ Producto        [▼]        │          [foto Combo Vecino ✓]  (de tu catálogo)
│ Ángulo          [▼]        │          [ Siguiente ]
│ Formato         [▼]        │        ② ¿Qué quieres lograr?
│ Texto           [______]   │          (•) Que vengan hoy  ( ) Dar a conocer
│ Hashtags        [______]   │          [ Atrás ] [ Siguiente ]
│ Fecha / hora    [__] [__]  │        ③ Elige tu favorita
│ Red             [▼]        │          [ A ] [ B ] [ C ]   ↻ Otra idea
│ [ Generar ]                │        ④ Revisa y aprueba
└───────────────────────────┘          «Instagram, jueves 7 p. m.»  [ Aprobar ]
```

Propose the concrete step breakdown for the screen you review: step names in the owner's words,
which inputs go in each, which defaults pre-fill them.

## 5. Accessibility and mobile basics

- Works at 360 px width in one column; no horizontal scroll; touch targets ≥ 44 px.
- Nothing only on hover; every icon button has a text label or `aria-label`.
- Contrast AA (the design-system tokens already pass: do not hand-pick colours, see
  `docs/design-system.md`); state is never shown by colour alone (use `signal_pill`/`tone_badge` text).
- Every field has a visible label (placeholder is not a label) and an example of a valid answer.
- Loading, empty and error states exist and say what happens next.
- For deeper checks run `design:accessibility-review`; for copy, `design:ux-copy`; for a full
  critique, `design:design-critique`; for planning interviews, `design:user-research`.

## 5b. Navigation

Every screen follows `docs/ux-guia-navegacion.md` (rules N1–N13: one name per place, every task
ends with the next step, everything has its own URL, no dead-end empty states, «volver» says where,
assisted never autonomous). Cite the rule number in findings («incumple N3»).

## 5c. «¿Dónde estoy?» — run it on every route you review

Checked **in the browser** (`ux-designer` rule 7), on load *and* after moving by tapping the menu
without reloading, on desktop and at 360 px:

1. **Exactly one menu entry is lit** (sidebar and bottom bar agree), including sub-screens
   (`/drafts/<id>` lights «Por aprobar»; opened from Tu semana → «Tu semana») and routes that
   redirect. Lit = `aria-current="page"` + accent colour + weight 600, never the glass capsule alone.
   Known trap: `router.page.path` is the route *pattern* (`/index` for «/», `/drafts/[draft_id]`);
   compare against the browser path (`router.url.path`) — m-24852260.
2. **Tab title = menu entry = `h1`** (N1).
3. **Back says where and does not scroll away** (N7); the phone/browser back returns one step or
   closes the panel, never leaves the module (N5).
4. **In a flow: the step is visible without scrolling** («Paso N de M», M real) and the primary
   action is in reach at the bottom (N6; `docs/ux-navegacion-pasos-2026-10-24.md`).

A review that skipped this section says so in its first line.

## 6. Reporting on a PR

The UX review runs **locally, before the PR is opened** (never in GitHub Actions — founder,
2026-10-23); `qualify-pr` step 5 makes it mandatory for every PR that touches client-facing paths.

- **Suggest, never block.** No approve/request-changes; the founder decides.
- **Return the suggestions to the caller**, who shows them to the founder in the same turn and
  pastes them into the PR description under a **«Sugerencias de UX»** section, each marked
  **aplicada** or **pendiente** (with the reason). You do not post PR comments.
- **Ranked findings, at most 8**, highest first: (1) the owner cannot finish the task, (2) feature
  language or banned words, (3) too many inputs in one step, (4) accessibility/mobile, (5) polish.
- Each finding: **file:line**, **what the owner would feel or say** («¿Qué es un prompt?»),
  **the suggested fix** (exact replacement string, or the step breakdown with a small mockup like §4).
- If the PR touches nothing client-facing in practice, say exactly
  «Revisión de experiencia: sin sugerencias.» and stop.
- Never invent a client's words or data; when a suggestion depends on an assumption about the
  user, mark it «hipótesis» and point to the question in `docs/perfil-cliente-pyme.md` §5.
