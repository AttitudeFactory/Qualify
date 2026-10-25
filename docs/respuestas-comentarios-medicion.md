# Respuestas a cualquier comentario — cómo se mide la clasificación y los borradores

`[PENDIENTE DE DATOS REALES · 2026-10-23 · ATENDER-4a (m-24848532)]`

Este documento explica cómo se mide, antes de responder a todos los comentarios (ATENDER-4b, m-24848533), si Qualify clasifica bien cada comentario y si sus borradores de respuesta se pueden aprobar sin miedo. Sigue el método de [`intencion-comercial-medicion.md`](intencion-comercial-medicion.md).

## Resultado

- **Sentimiento (2026-10-25, m-24854495):** el sentimiento se mide aparte, sobre comentarios reales y contra robertuito, con su propia guía ([`guia-etiquetado-sentimiento.md`](guia-etiquetado-sentimiento.md)) y el prompt `atender4a.2` del clasificador (con confianza). Plan y estado en la [bitácora, SENT-HAIKU-001](modelos-generativos/pruebas.md#sent-haiku-001).

- **La medición sigue pendiente.** Las herramientas están listas y probadas. Lo que falta son los datos: un conjunto real de unos 400 comentarios, etiquetado por dos personas que no vean las etiquetas de la otra, y una persona que revise los borradores. La sección 8 dice exactamente qué tiene que conseguir el fundador.
- **Prueba de humo sintética (2026-10-23):** se hizo con 80 comentarios que escribió el agente. No hay acuerdo entre etiquetadores (κ) porque solo hubo uno, y los negocios son ficticios. La prueba sirve para comprobar que las herramientas funcionan. **No mide calidad.** En esos comentarios, el clasificador candidato pasó todos los umbrales en `test`. Los borradores no inventaron precios ni hablaron en tercera persona según los controles automáticos. La parte «usable» sigue sin revisión humana.
- **Hallazgo sobre el sistema actual:** en producción solo se preparan borradores para comentarios con intención comercial. La imagen de producción no trae torch, así que robertuito nunca corre y ningún comentario recibe sentimiento. Con ese criterio, el sistema actual **no detecta ninguna queja**: «necesita respuesta» tuvo una cobertura de 0,55 tanto en `dev` como en `test`, frente a una meta de 0,95. Ese hueco es el que cierra ATENDER-4b.

## 1. Qué se mide y con qué umbral

Los umbrales vienen del ticket m-24848532 y están en el código (`qualify_api/evals/comment_replies.py`).

| Qué | Umbral | Quién lo decide |
|---|---|---|
| Acuerdo entre etiquetadores, por campo (sentimiento, tipo, necesita respuesta) | κ de Cohen ≥ 0,70 en al menos 50 comentarios con doble etiqueta | código |
| Cada clase de sentimiento (`pos`, `neu`, `neg`) y de tipo (`praise`, `question`, `complaint`, `other`) | precisión ≥ 0,80, cobertura ≥ 0,70, al menos 8 ejemplos en `test` | código |
| Cobertura de negativos (`neg`) | ≥ 0,90 | código |
| Cobertura de «necesita respuesta» | ≥ 0,95 (precisión ≥ 0,80) | código |
| Borradores con datos inventados | 0 | persona (el código solo marca los sospechosos) |
| Borradores en tercera persona | 0 | persona (el código solo marca los sospechosos) |
| Borradores que prometen o admiten algo en público (columna `promete_o_admite`: «¿admite o promete algo?») | 0 | persona |
| Borradores usables | ≥ 90 % en positivos y neutros; ≥ 80 % en negativos | persona |
| Precios | un precio aparece solo si está en el catálogo (`assisted/grounding.py`); si no, el borrador declina e invita a seguir por mensaje privado | código |
| Aperturas repetidas (las 3 primeras palabras) | ninguna en más del 20 % de los borradores (se mide desde 10 borradores) | código |

**Usable = el dueño la enviaría tal cual o cambiando una palabra, sin miedo a que diga algo falso, prometa algo o suene a otro negocio.**

Una clase que no llega a su umbral se marca como **no fiable** y se informa con nombre propio. Nunca se esconde dentro de un promedio.

## 2. Reglas de etiquetado

Hay que escribirlas antes de etiquetar, y las dos personas usan las mismas.

- **E1 — Sentimiento** es el tono de quien comenta hacia el negocio. `pos`: elogio, agradecimiento o entusiasmo. `neg`: queja, molestia, desconfianza, burla o mala reseña, aunque sea educada. `neu`: todo lo demás.
- **E2 — Mezclas.** Una pregunta con elogio («¡qué belleza! ¿cuánto cuesta?») es `pos`. Una pregunta con molestia («¿hasta cuándo esperando?») es `neg`. El sarcasmo («excelente servicio, dos horas esperando») es `neg`.
- **E3 — Tipo.** `complaint` es un reclamo al negocio. `question` es una pregunta o un pedido al negocio, aunque no tenga signos («precio», «info», «dm»). `praise` es solo elogio. `other` son etiquetas a otras personas, conversación entre usuarios, publicidad ajena, spam o emojis sueltos. Si un comentario se queja y también pregunta, es `complaint`. Si elogia y pregunta, es `question`.
- **E4 — Necesita respuesta.** Siempre `true` en `question` y `complaint` (el código rechaza una fila que no lo cumpla). Es `false` en `praise`, porque agradecer es opcional, y en `other`.
- **E5 — Etiquetar a otra persona sin pedir nada** es `other`, aunque el tono sea negativo («ya no es lo que era @carlos» es `neg` + `other`).
- **E6 — Solo el texto.** Se etiqueta lo que dice el comentario, sin suponer lo que muestra la publicación.

## 3. El conjunto real (lo que falta)

1. **Unos 400 comentarios** de cuentas reales en español de Colombia, Venezuela y Uruguay, con quejas y preguntas suficientes para tener al menos 8 de cada clase en `test`. Lo recomendable son 15 o más.
2. **Anonimizados:** solo el texto. Sin usuarios ni enlaces a perfiles, y con las menciones reemplazadas por `@usuario`. Si un comentario sale de la base, sale así.
3. **Dos personas etiquetan cada comentario sin ver la etiqueta de la otra** (la persona A en `sentiment`/`kind`/`needs_reply` y la persona B en `second`), al menos en 50 comentarios; mejor en los 400. Si κ < 0,70 en algún campo, se ajustan las reglas y se vuelve a etiquetar antes de medir. Los desacuerdos los resuelve una tercera persona, y esa etiqueta final es la que se usa.
4. **División `dev`/`test`** estratificada por la clase más rara de cada comentario. El prompt se ajusta solo con `dev`. `test` se mide una sola vez por versión del prompt.
5. **Catálogo de cada negocio** en el formato de `packages/api/evals/replies_ai/catalogs.json`, para poder comprobar los precios.

Formato de cada línea (`qualify_api.evals.comment_replies`):

```json
{"text": "llegó frío el pedido", "sentiment": "neg", "kind": "complaint", "needs_reply": true,
 "asks_price": false, "business": "<clave en catalogs.json>", "split": "test",
 "source": "tenant:<rubro>:<país>", "labeler": "A",
 "second": {"sentiment": "neg", "kind": "complaint", "needs_reply": true, "labeler": "B"}}
```

## 4. Cómo se corre

En `packages/api/evals/replies_ai/` (`README` en el docstring de `run_experiment.py`). Todo menos `--agreement` gasta créditos de Claude, así que se corre a mano y nunca en CI:

```bash
just eval-replies --golden <set>.jsonl --agreement                       # κ, sin costo
just eval-replies --golden <set>.jsonl --split dev  --classify --baseline   # para ajustar
just eval-replies --golden <set>.jsonl --split test --classify --baseline --drafts
# una persona llena results/<run>-revision.csv (usable / invented / third_person / promete_o_admite: si/no)
just eval-replies --golden <set>.jsonl --score-review results/<run>-revision.csv --results results/<run>.json
```

Cada informe registra el modelo, la versión del prompt, el sha256 del conjunto y el costo. Los borradores se generan con el **tipo y el tono de la etiqueta real**, no con lo que diga el clasificador, para medir su calidad sin arrastrar los errores de la clasificación.

**Qué se compara:**

- **Línea base (sistema actual):** `intent.ClaudeIntentClassifier` (`intent-claude-v2`). Hoy un comentario recibe borrador solo si tiene intención comercial, así que «necesita respuesta» equivale a «tiene intención comercial». robertuito no entra en la línea base porque no corre en producción (falta torch en la imagen) y no tiene licencia declarada.
- **Candidato:** `replies.triage.ClaudeCommentTriager`. Es una sola llamada a Claude Haiku 5.5 (`claude-haiku-5-5`, esfuerzo `low`, herramienta estricta `registrar_comentarios`, prompt `atender4a.1`) que devuelve sentimiento, tipo y si necesita respuesta. Reemplaza a robertuito en el camino de comentarios.
- **Borradores candidatos:** `replies.any_comment_drafts` (prompt `atender4a.2`) sobre el generador con hechos validados de Fase B. Siempre en primera persona, nunca con precio en público (D1), sin una frase de apertura fija, y en las quejas pide disculpas sin admitir ni prometer nada, sin emojis, e invita a la persona a escribir ella por mensaje privado («escríbenos por mensaje privado»): nunca promete que el negocio le va a escribir.

## 5. Prueba de humo sintética — 2026-10-23

- **Conjunto:** `packages/api/evals/replies_ai/synthetic_smoke.jsonl`, 80 comentarios (40 en `dev` y 40 en `test`; 10 por tipo en cada mitad) de tres negocios ficticios: una arepera en Cúcuta, una dulcería en Caracas y una pizzería en Montevideo. Los escribió y etiquetó el agente, que también escribió el prompt. **Eso infla el resultado:** los comentarios son más claros que los reales.
- **Informes:** `results/20261023-141654.json` (`dev`) y `results/20261023-141720.json` (`test`, con borradores y la hoja de revisión `20261023-141720-revision.csv`).

### Clasificador en `test` (40 comentarios)

| Clase | Ejemplos | Precisión | Cobertura | Umbral de cobertura | ¿Fiable? |
|---|---|---|---|---|---|
| sentimiento `pos` | 14 | 1,00 | 0,86 | 0,70 | sí |
| sentimiento `neu` | 14 | 0,88 | 1,00 | 0,70 | sí |
| sentimiento `neg` | 12 | 1,00 | 1,00 | 0,90 | sí |
| tipo `praise` | 10 | 1,00 | 1,00 | 0,70 | sí |
| tipo `question` | 10 | 1,00 | 1,00 | 0,70 | sí |
| tipo `complaint` | 10 | 0,91 | 1,00 | 0,70 | sí |
| tipo `other` | 10 | 1,00 | 0,90 | 0,70 | sí |
| necesita respuesta | 20 | 0,95 | 1,00 | 0,95 | sí |

Hubo tres errores. «🔥» y «jajaja @nico mirá vos» salieron `neu` en lugar de `pos`, y en esos casos la regla es discutible. «Mi vecino dice que antes era mejor @ana» se leyó como queja, cuando según E5 es `other`. Este último error es por exceso, del lado seguro. En `dev` el resultado fue el mismo: todas las clases fiables y 2 errores del mismo tipo.

**Línea base en el mismo `test`:** «necesita respuesta» tuvo precisión 1,00 y **cobertura 0,55**. Detectó las 10 preguntas y una de las quejas, y dejó sin respuesta las otras 9. En `dev` fallaron 9 de las 10 quejas.

### Borradores en `test` (40), controles automáticos

| Control | Resultado |
|---|---|
| Errores del modelo | 0 |
| Precio fuera del catálogo o pregunta de precio sin declinar | **0**: las 3 preguntas de precio declinaron e invitaron a mensaje privado |
| Marcas de tercera persona | **0** |
| Marcas de dato posiblemente inventado | 12. Todas son `model_unsupported`: el propio modelo dice «no tengo ese dato» al derivar a mensaje privado. No hay teléfonos, enlaces, horarios ni promociones |
| Revisión humana (usable / inventado / tercera persona) | **pendiente**: la hoja está lista |

Lectura del agente, que **no reemplaza la revisión humana**:

- Los elogios, las preguntas y las quejas leen bien, en primera persona y sin inventar nada. Un caso para revisar: «Tienes razón, y lamentamos no haber respondido antes» reconoce un hecho que el negocio no confirmó.
- **Los comentarios `other` no deberían recibir borrador.** El modelo le contestó al spam («Gana dinero desde casa»: «con gusto te orientamos…») y a etiquetas entre amigos («@sofi_m para tu cumple»). Recomendación para ATENDER-4b: preparar borrador solo si `needs_reply` o `kind = praise`.
- Casi todos los borradores empiezan con «Gracias por escribirnos». Suenan repetidos y todavía no usan la voz de la marca. Medir «en mi voz» exige darle al generador el tono del negocio, cosa que hoy no recibe.
- «Te escribimos por mensaje privado» compromete al dueño a escribir, y si nadie escribe queda una promesa pública incumplida. Lo corrigió `atender4a.2` (abajo).
- Se repite el hallazgo de FASEB-001: derivar a mensaje privado dispara `model_unsupported`. El costo es poco, porque solo pide revisión; sigue abierto en `atender4a.2` (10 marcas).

### Borradores `atender4a.2` en el mismo `test` — 2026-10-23, tras la revisión de UX

La revisión de UX de este ticket encontró que los borradores de `atender4a.1` prometían escribirle a quien se quejó, admitían culpas («Tienes razón…»), prometían resolver, ponían 🙏 en las quejas y empezaban casi siempre con «¡Gracias por escribirnos!». Se cambió el prompt a `atender4a.2` y se volvieron a generar los 40 borradores de `test` (informe `results/20261023-143235.json`, hoja `20261023-143235-revision.csv`, US$0,0066). Detalle en la prueba ATENDER4A-002 de la [ficha de Claude Haiku 5.5](modelos-generativos/claude-haiku-5-5.md).

| Control automático | `atender4a.1` | `atender4a.2` |
|---|---|---|
| Errores / precios / tercera persona | 0 / 0 / 0 | 0 / 0 / 0 |
| Borradores con «te escribimos» | 10 | **0** |
| Quejas con «tienes razón» / «resolverlo» / emoji | 1 / 7 / 8 | **0 / 0 / 0** |
| Apertura más repetida | «gracias por escribirnos», 27,5 % (falla) | «qué bueno que», 20,0 % (pasa, en el límite) |

Queda por ver: las 10 quejas cierran casi igual («Escríbenos por mensaje privado y lo revisamos contigo», el ejemplo del prompt). Lo tiene que juzgar la persona que revise.

**«En mi voz» no se mide todavía.** El generador no recibe el tono de la marca, así que ningún resultado de esta sección dice que los borradores suenen al dueño. ATENDER-4b no debe darlo por cumplido hasta que el generador reciba el tono de la marca y una persona lo revise.

## 6. Costo

Precios: US$0,10 / US$0,50 por millón de tokens de entrada / salida (`claude_tools.PRICES`, skill `claude-api`).

| Qué | Medido | Por cliente al mes (300 comentarios, unos 200 borradores) |
|---|---|---|
| Clasificar (lotes de 25) | US$0,000019 por comentario; la meta del ticket es ≤ US$0,0005 | ≈ US$0,006 |
| Borrador | US$0,00017 por borrador | ≈ US$0,033 |
| Línea base (intención) | US$0,000018 por comentario | (ya se paga hoy) |
| Esta prueba de humo, completa (dev + test, con línea base y borradores) | ≈ US$0,010 | — |
| Medición real estimada (400 comentarios, 5 vueltas de ajuste en `dev`, una en `test` con borradores) | ≈ US$0,15–0,30, por debajo de los ≈ US$1,5 que estimó la épica | — |

## 7. Procedencia de cada borrador

Cada borrador guarda:

- `generator_version`, que nombra el prompt y el modelo;
- `model_id`;
- `input_tokens` y `output_tokens`;
- `cost_usd`.

Los borradores de Fase B ya lo hacían. Desde este cambio también lo hacen los agradecimientos (`qua22.2`): `ClaudeReplyDraftProvider.last_stats` pasa a `DraftProvenance`. No hizo falta migración, porque las columnas existen desde la 0080. El candidato `atender4a.1` viaja por el mismo contrato (`Proposal`) que Fase B.

## 8. Lo que tiene que dar el fundador

1. **Autorizar la fuente de los ~400 comentarios.** Hay dos opciones:
   - Exportar solo el texto, anonimizado, de los comentarios de las cuentas conectadas de los negocios reales (Bianki, Polette, PuntoServis, la inmobiliaria, la agencia de viajes). Esto exige su permiso explícito para leer comentarios de producción, que este ticket no tenía.
   - Usar como base los 408 comentarios públicos de `packages/api/eval_data/intent_golden_v1.jsonl` y completarlos con quejas reales. Esa base no son clientes, y tiene pocas quejas.
2. **Dos personas que etiqueten por separado** con las reglas de la sección 2 (por ejemplo Raul y Yesika), al menos 50 comentarios en común y mejor todos. Calcula unas 3 horas por persona para 400 comentarios.
3. **Una persona que revise los 40 o más borradores de `test`** en la hoja CSV (usable / inventado / tercera persona / promete o admite).
4. **El catálogo de cada negocio** del conjunto, en `catalogs.json`.

Con eso, un agente corre la sección 4 y reemplaza la sección 5 por la medición real.
