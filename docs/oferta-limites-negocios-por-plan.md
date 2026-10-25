# Oferta — cuántos negocios por plan: cómo lo limita el mercado y qué empaquetado le calza a Qualify

**Fecha:** 2026-10-25 · **Modo:** OFERTA (analista de mercado externo) · **Ticket:** [m-24854768](https://project.larksuite.com/5h2wsx/issue/detail/24854768), dentro de la épica [m-24849186](https://project.larksuite.com/5h2wsx/story/detail/24849186) · **Estado:** `[EVIDENCIA + RECOMENDACIÓN · sin precio de venta · sin código]`
**Pregunta del fundador (2026-10-25):** un dueño maneja varios negocios (tenants) desde un login y **comparte UNA suscripción**. ¿Cuántos negocios por suscripción y cómo escalan los planes?
**Convención:** `[P]` fuente primaria (URL + fecha de acceso 2026-10-25) · `[S]` secundaria (blog, reseña, agregador; a menudo de un competidor) · `[H]` hipótesis o aritmética del autor · `[V]` hecho confirmado por el fundador o por disco.
**Cómo se leyó la web:** las páginas de precios se leyeron con un extractor automático; Hootsuite, Publer, Canva y Ocoya mostraron inconsistencias o bloqueos (marcadas). Antes de citar una cifra a un cliente, verificarla en la página viva.
**Lo que este doc no hace:** no fija el precio de Qualify (D25 de [`modelo-cobro-generacion.md`](modelo-cobro-generacion.md) lo deja abierto, y [`modelo-negocio-operador-multi-emprendimiento.md`](modelo-negocio-operador-multi-emprendimiento.md) §6 D4 dice «no se fija cifra sin un comprador delante»). Aporta la evidencia y una forma de empaquetar.

---

## 0. Lo primero: tres hallazgos que contradicen o tensan lo que hay en disco

1. **El diseño de planes en disco es por negocio, no por suscripción.** `[V]` D15 de `modelo-cobro-generacion.md`: «todo negocio empieza en Básico», `tenant_plan_assignments` guarda el plan **por tenant** y cada tenant tiene su propio tope de alerta. La decisión del fundador de hoy («una suscripción compartida») **no tiene sujeto en el modelo de datos**: no existe una entidad suscripción/operador (la épica la deja fuera, `epica-multi-negocio-una-sesion.md` §7: «facturación por operador»). Con el diseño actual, 3 negocios = 3 Básicos = **3 × USD 55 de peor caso = USD 165** (`modelo-cobro-generacion.md` §6, `[V]` aritmética sobre cifras del doc). Con cupos compartidos, el peor caso queda en el del plan (USD 55) sin importar cuántos negocios. **Esto es una decisión de arquitectura que se le señala al principal-architect, no se discute aquí.**
2. **El mercado no regala «5 marcas» cuando hay generación cara detrás.** Los planes de entrada que incluyen 5 marcas (Metricool Starter, Canva Pro) venden programación y diseño, cuyo costo variable es casi cero. Los que incluyen generación con créditos topan en 1 marca (Predis Core) o 2 (Later Growth) en el escalón de entrada. Qualify gasta hasta USD 55/mes por negocio en el peor caso (`modelo-cobro-generacion.md` §6): su escalón de entrada se parece más a Predis que a Metricool. `[H]`
3. **Un tope alto de negocios cambia el carril de Meta, no solo el precio.** `[V]` `modelo-negocio-operador-multi-emprendimiento.md` §2.1: el carril *Standard Access* se apoya en «un negocio que **yo** poseo o administro»; `V-TP-7` sigue sin resolver. Un dueño con 2 negocios propios es el caso sano. Un «dueño» con 15 es, en la práctica, una agencia con clientes de terceros. Un tope de negocios por suscripción es también un **tope del riesgo regulatorio**. `[H]` — a verificar con el architect, no a asumir.

---

## 1. La tabla: cómo limitan marcas, espacios y créditos de IA

Todos los precios en USD, antes de impuestos, fecha de acceso 2026-10-25. «Anual» = facturación anual por mes. Billing: salvo que se diga, solo en USD (barrera real para VE/CO: ver §4).

| Herramienta · plan | USD/mes | Marcas / espacios incluidos | Cuentas sociales | Marca (o cuenta) extra | Créditos de IA: ¿cómo se reparten? | Fuente |
|---|---:|---|---|---|---|---|
| **Metricool** Free | 0 | 1 marca | 1 por red | — | 5 créditos **por marca** y mes | `[P]` [metricool.com/pricing](https://metricool.com/pricing/) |
| Metricool Starter | 20 (25 mensual) | **5 marcas** | 10 por red | No hay precio unitario: se sube de escalón. 5→10 marcas = USD 36 anual / 45 mensual | 20 créditos **por marca** y mes | `[P]` ídem |
| Metricool Advanced | 53 (67) / 85 (107) / 159 (210) | 15 / 25 / 50 marcas | 50 por red | Ídem (escalones) | 35 créditos **por marca** y mes | `[P]` ídem |
| **Later** Starter | 18,75 | **1 conjunto social** | 8 (1 por red) | **No se puede** comprar extra: hay que cambiar de plan | 5 créditos, nivel cuenta; extra **no** disponible | `[P]` [later.com/pricing](https://later.com/pricing/) |
| Later Growth | 37,50 | 2 conjuntos | 16 | **11,25/mes** por conjunto | 50 créditos a nivel cuenta; 3,75 por 100 extra | `[P]` ídem |
| Later Scale | 82,50 | 6 conjuntos | 48 | 11,25/mes por conjunto | 100 créditos a nivel cuenta | `[P]` ídem |
| **Buffer** Essentials / Team | 5 / 10 **por canal** | No usa marcas: cada cuenta es un canal | Sin tope; canales 1–10 a tarifa plena, bajan después | Es lineal: cada canal vale lo mismo (con descuento por tramos) | IA «créditos ilimitados» en todos los planes | `[P]` [buffer.com/pricing](https://buffer.com/pricing) |
| **Planable** Basic / Pro | 33 / 49 **por espacio** | 1 espacio = 1 marca; sin tope; descuento por volumen solo sobre 5 | 4 / 10 páginas por espacio | Cada espacio extra cuesta la tarifa completa | IA incluida por espacio; análisis +12–14 por espacio | `[P]` [planable.io/pricing](https://planable.io/pricing/) (las páginas se contradicen en los complementos) |
| **SocialBee** Bootstrap | 29 (24 anual) | 1 espacio | 5 perfiles | 10/mes por espacio; 15/mes por 5 perfiles | IA «ilimitada» | `[P]` [socialbee.com/pricing](https://socialbee.com/pricing/) |
| SocialBee Accelerate / Pro | 49 / 99 | 1 / **5** espacios | 10 / 25 | ídem | ídem | `[P]` ídem |
| SocialBee Pro50–150 (agencia) | 179 / 329 / 449 | 10 / 20 / 30 espacios | 50 / 100 / 150 | ídem | ídem | `[P]` ídem |
| **Predis.ai** Core | 19 (230/año) | **1 marca** | 10 | **5/mes** por marca | 1.300 créditos por plan; la página **no dice** si se reparten por marca | `[P]` [predis.ai/pricing](https://predis.ai/pricing/) |
| Predis Rise | 40 (474/año) | hasta **4 marcas** | 20 (tope a nivel plan, no por marca) | 5/mes por marca | 3.200 por plan; sin aclarar | `[P]` ídem |
| Predis Enterprise+ | 212 | marcas ilimitadas | 60 | — | 10.000 por plan | `[P]` ídem |
| **Publer** Free | 0 | 1 espacio | 3 cuentas | — | — | `[P]` [help center](https://publer.com/help/en/article/what-are-publers-plans-and-pricing-15h4yqh/) |
| Publer Professional / Business | desde 5 / 10 (con 1 cuenta) | **Espacios ilimitados** gratis; se paga por cuenta social | por cuenta | Cuenta extra ≈ 4 / 7 (ayuda anterior; la vigente no lista la cifra); la 10.ª gratis | Business: IA «ilimitada» | `[P]` ídem (la página de precios redirige en bucle: cifras por ayuda) |
| **Vista Social** Professional | 99 (950/año) | Sin concepto de espacio en la página | 15 perfiles | «Personalizable» sin precio | 1.000 créditos/mes, sin decir si se reparten | `[P]` [vistasocial.com/pricing](https://vistasocial.com/pricing/) |
| Vista Social Advanced / Scale | 199 / 449 | — | 30 / 70 | Perfiles en bloques de 10 (Scale) | 2.000 / 3.500 | `[P]` ídem |
| **Ocoya** Starter | 29 | no lo muestra | 5 | no lo muestra | 300 créditos | `[P]` [ocoya.com/pricing](https://www.ocoya.com/pricing) |
| Ocoya Team / Agency | 79 / 199 | no lo muestra | 20 / 100 | no lo muestra | 1.500 / 5.000, «créditos compartidos para tu equipo» | `[P]` ídem |
| **Hootsuite** Standard | 99 **por usuario** | Sin marcas: «organización» | 10 cuentas | no lo muestra | IA incluida, sin límites publicados | `[P]` [hootsuite.com/plans](https://www.hootsuite.com/plans) (FAQ: 99/199/hasta 399); `[S]` NapoleonCat da 249 para Advanced: no concilian |
| **Canva** Pro | 18 mensual / 144 anual por persona | **5 kits de marca** | — | — | Créditos por persona (no verificado) | `[S]` [canva.com/pro/brand-kit](https://www.canva.com/pro/brand-kit/) vía buscador; la página devolvió 403 |
| Canva Business | ≈ 250/año por persona | **100 kits de marca** | — | — | — | `[S]` eesel.ai y Canva Learn; no verificado en el sitio oficial |
| **mLabs** (Brasil) | **R$ 29,90 por marca** y mes (plan único) | **1 marca por R$ 29,90**, lineal | por marca | cada marca = otro R$ 29,90 | ChatGPT y Canva integrados; sin límite publicado | `[P]` [mlabs.com.br/blog/mlabs-planos](https://www.mlabs.com.br/blog/mlabs-planos/) (artículo del 2025-07-25); paga con Pix, boleto, 12 cuotas |
| **Postcron** (Argentina/México) | ≈ 8 / 24 / 58 / 166 | no verificado | no verificado | no verificado | no verificado | `[S]` solo un blog de un competidor; **sin fuente primaria — no usar** |

**Equivalencias por marca (aritmética mía `[H]`)**

| Modelo | Costo por marca | Cálculo |
|---|---:|---|
| Metricool 5 → 10 → 15 → 25 → 50 marcas (anual) | 4,00 → 3,60 → 3,53 → 3,40 → 3,18 | 20/5, 36/10, 53/15, 85/25, 159/50 |
| Predis Core / Rise (mensual) | 19 / 10 | 19/1, 40/4 |
| Later Growth (anual) | 18,75 por conjunto; el tercero cuesta 11,25 | 37,50/2 |
| SocialBee Pro | 19,80 por espacio | 99/5 |
| Planable | 33 a 49 por espacio, siempre lineal | — |
| mLabs | R$ 29,90 siempre lineal | — |

---

## 2. Patrones

| # | Patrón | Quién | Lectura |
|---|---|---|---|
| P1 | **Escalones de cantidad con precio por marca decreciente** | Metricool (1/5/10/15/25/50) | La marca extra nunca se compra suelta: se compra el escalón siguiente. El costo marginal baja de 4,00 a 3,18 por marca. Funciona porque su costo variable por marca es casi cero (programar y leer métricas) |
| P2 | **Cupo de espacios por plan + complemento por unidad** | SocialBee (5 en Pro, +10/espacio), Later (2 y 6, +11,25), Predis (4, +5) | El complemento cuesta **entre un cuarto y un tercio del plan que lo incluye**: Later 11,25 vs 37,50 (30 %); SocialBee 10 vs 99 (10 %); Predis 5 vs 40 (12,5 %) `[H]` aritmética |
| P3 | **Tope duro en el plan de entrada** | Later Starter («no disponible»), Predis Core (1 marca) | El segundo negocio **obliga a cambiar de plan**. Es el patrón con más fricción documentada (§3) |
| P4 | **Lineal por unidad** | Planable (por espacio), Buffer (por canal), mLabs (por marca) | Predecible, sin trampa, pero castiga a quien tiene varias marcas pequeñas. Es justo lo que `modelo-negocio-operador-multi-emprendimiento.md` §4 decía que «expulsa» al dueño de varios negocios |
| P5 | **Espacios gratis, se cobra la cuenta social** | Publer | Quita el concepto de marca como unidad de cobro; se cobra lo que cuesta de verdad (cuentas conectadas) |
| P6 | **Créditos de IA por marca** | Metricool (5/20/35 por marca) | La única que lo dice explícito. Cada marca recibe su propio cupo: **el costo variable crece con las marcas**, y Metricool lo absorbe porque 20–35 créditos de texto cuestan poco |
| P7 | **Créditos de IA a nivel cuenta o plan, sin decir cómo se reparten** | Later, Predis, Vista Social | La opacidad es la norma: **ninguna de las tres publica una regla de reparto entre marcas**. Ocoya es la única que dice «compartidos para tu equipo» |
| P8 | **IA «ilimitada»** | Buffer, SocialBee, Publer Business | Posible solo porque es texto; no hay referente de **video generado** ilimitado |
| P9 | **Precio por usuario, no por marca** | Hootsuite, Canva | No sirve a un dueño solo con varios negocios (paga el mismo asiento una vez): pero a USD 99+ queda fuera del segmento de todos modos |

**Lo que no existe en el mercado leído:** ninguna herramienta publica créditos de **generación de video** compartidos entre varias marcas con un precio claro. Predis, Vista Social y Ocoya publican créditos, no costo de la unidad ni regla de reparto. Esto es oportunidad (nadie lo explica) y alerta (no hay un precedente que copiar). `[H]`

---

## 3. Quejas documentadas sobre los límites

Lectura honesta: **no encontré hilos de Reddit** sobre límites de marcas (la búsqueda no los devolvió); lo que hay es reseñas de G2/Capterra y blogs, muchos de competidores.

| Herramienta | Queja | Fuente | Peso |
|---|---|---|---|
| Later | Sumar un segundo perfil «obliga a subir de plan», porque el precio es por conjunto social; Starter no puede comprar conjuntos extra | [SocialPilot](https://www.socialpilot.co/insights/later-pricing) | `[S]` competidor |
| Later | El plan Growth pasó de 3 conjuntos y 3 usuarios por 30 al mes a 2 y 2 por 37,50: **menos por más** | ídem | `[S]` competidor; no verificado en el historial de la página |
| Buffer | «El precio por canal me mató. Con 8 cuentas se volvió caro» (G2); otro: 5 o más cuentas llegan a 30–50/mes | [SocialBu](https://socialbu.com/blog/buffer-pricing), citando G2 | `[S]` de un competidor, citando G2 |
| Planable | «Cada marca necesita su espacio»: un competidor calcula 340/mes para 5 marcas en Pro con análisis; en G2 el precio alto es el contra más repetido (61 menciones, según otro competidor) | [PostPlanify](https://postplanify.com/blog/best-planable-alternatives), [G2](https://g2.com/products/planable/pricing) | `[S]` sesgado: el cálculo es suyo |
| Metricool | **No hallé queja por el límite de marcas.** Las recurrentes son publicaciones marcadas como publicadas que nunca salen, y renovaciones sin reembolso | [Trustpilot](https://ca.trustpilot.com/review/metricool.com), reseña de [ainfluencer](https://ainfluencer.com/metricool/) | `[S]` |

Lectura: **la fricción documentada está en el salto forzado** (Later, P3) **y en el cobro lineal con muchas marcas** (Buffer, Planable, P4). La estructura en escalones de Metricool (P1), la más generosa en marcas, no generó quejas de límite que pudiera encontrar. `[H]` — ausencia de evidencia no es evidencia de ausencia.

---

## 4. Qué implica para el segmento (hipótesis; nada aquí está validado con un comprador)

**Lo que sabemos `[V]`:** hay **un** caso real de un dueño con dos negocios separados: Bianki y Polette (`epica-multi-negocio-una-sesion.md`). No hay un segundo. Tampoco hay entrevista con un comprador sobre el precio (`perfil-cliente-pyme.md`: «todavía no hubo entrevistas»). **El tamaño del grupo «dueños con 2 o más negocios» es desconocido.**

**Anclas de precio que ve el dueño (lo que ya conoce) `[S]/[P]`:**

| Referencia | USD/mes | Qué da |
|---|---:|---|
| Programar por cuenta: Buffer 5, Publer 5 (primera cuenta), mLabs ≈ R$ 29,90 | ≈ 5 a 6 por marca | Solo publicar; **sin generar** |
| Marca con generación: Predis Core 19; Rise 40 por 4 marcas | 10 a 19 por marca | Texto e imagen con créditos |
| Freelance de redes en LATAM | 200 a 600 | Servicio completo (`oferta-mercado-agencia-gestionada.md` §2, `[S]`) |

Dos hechos que cuentan más que el precio:

1. **El suelo de costo de Qualify supera a los programadores.** Un Básico cuesta al equipo ≈ USD 9,90 en un mes típico `[H]` (estimación sin uso real, `modelo-cobro-generacion.md` §6) y hasta ≈ 55 en el peor caso. Un dueño anclado en «5 por marca» no es el comprador de un Básico con video, y no hay forma de cerrar la brecha con descuentos por cantidad. El comparador razonable es Predis (generación) y, por arriba, el freelance.
2. **El medio de pago pesa tanto como el precio.** Later declara «los precios se facturan en USD»; Metricool, Buffer y Planable se publican en USD/EUR `[P]`. Para VE/CO eso exige tarjeta internacional. mLabs sirve a Brasil con Pix y boleto en moneda local `[P]`. D19 de `modelo-cobro-generacion.md` (cobro a mano con transferencia, Zelle, pago móvil) es una ventaja real frente a todo lo de la tabla y **no está en ninguna de sus páginas**. No encontré una fuente confiable sobre el gasto mensual de pymes de LATAM en herramientas de marketing: sigue desconocido.

**Hipótesis sobre cuántos negocios tiene el comprador `[H]`:** el segmento («emprendimientos y pymes con presupuesto acotado», `perfil-cliente-pyme.md` §0) se parece más a quien tiene 2 o 3 negocios pequeños que a quien tiene 5 o más. Quien lleva 5 o más, y con clientes de terceros, es una agencia (otro modelo, otro carril de Meta: hallazgo 3).

---

## 5. Tres formas de empaquetarlo

Los tres respetan: el dueño nunca ve dinero, solo contadores (D1); el cobro es manual por ahora (D19); los precios de venta siguen abiertos. Los «USD» en pros y contras son de **costo para Qualify**, de `modelo-cobro-generacion.md` §6.

### Opción A — Un cupo propio por negocio, y se paga cada negocio extra (el diseño actual de D15, más un precio por negocio)

Cada tenant conserva su Básico/Plus/Pro tal como está diseñado. La «suscripción compartida» es una **factura** que agrupa varios tenants del mismo dueño, con un precio por negocio adicional (con descuento por cantidad, al estilo P1/P4).

| Pros | Contras |
|---|---|
| **Cero entidad nueva**: sirve con `tenant_plan_assignments` y con `just set-plan` tal como están. Se puede hacer a mano hoy, con Bianki y Polette | Es el modelo que `modelo-negocio-operador-multi-emprendimiento.md` §4 ya descartó: castiga al dueño de negocios pequeños. N negocios = N× el peor caso (USD 55 → 165 con 3) |
| El costo sube con los ingresos: cada negocio paga su parte | No es «una suscripción compartida»: es varias, juntas. No cumple lo que pidió el fundador |
| Sin riesgo de que un negocio gaste el cupo del otro | Cupos que sobran en un negocio y faltan en otro (estacionalidad: helados vs shawarma `[H]`): el dueño paga por lo que no usa |
| Sin tope de negocios que explicar | Sin tope no hay protección contra la cartera que es de hecho una agencia |

### Opción B — Un cupo compartido por suscripción y un tope de negocios por plan (estilo Predis/Later)

La suscripción tiene un plan (Básico/Plus/Pro) con **cupos que se comparten entre todos sus negocios**, y cada plan incluye un máximo de negocios.

| Pros | Contras |
|---|---|
| Es literalmente lo que pidió el fundador | **Exige una entidad nueva** (suscripción u operador) que no está en D15 ni en la épica: el principal-architect tiene que tocar `tenant_plan_assignments`, `creation_allocations` y el cargo |
| **El costo está acotado por el plan**, no por la cantidad de negocios: Básico USD 55, Plus 110, Pro 220, sea 1 o 5 negocios | Un negocio puede comerse el cupo del otro: necesita un contador por negocio visible, y quizá un tope interno |
| Mensaje simple: «Plus: hasta 3 negocios» | No cubre costos que sí crecen con cada negocio (consulta de comentarios, almacenamiento, soporte, mensajes de WhatsApp): `[H]` desconocidos, nadie los ha medido |
| El dueño paga lo que usa, no la suma de sus cupos | Una suscripción que el tope aprieta (3 negocios en un plan de 2) obliga al salto forzado, el patrón P3 con más fricción |

### Opción C — Híbrido: cupos de generación compartidos + una cuota baja por cada negocio incluido o extra (recomendada)

El **costo variable** (generación) se comparte; el **costo fijo por negocio** (cuenta conectada, bandeja, soporte) se cobra aparte con un precio pequeño y lineal.

| Pros | Contras |
|---|---|
| Separa lo que de verdad cuesta distinto: los créditos de video son lo caro (USD 3,44 el de 5 s) y se comparten; una cuenta más es barato y se cobra por unidad (P5, como Publer) | **También exige la entidad nueva** de B y le suma una línea de cobro por negocio: la más compleja de las tres |
| El precio por negocio extra queda anclado a precios de mercado de la unidad (5 a 11 por espacio extra: Predis 5, SocialBee 10, Later 11,25) `[H]`, sin tocar los cupos | El «complemento por negocio extra» es otro número que explicar. La regla P2 funciona mientras el complemento sea una fracción clara del plan |
| Permite un tope sin salto forzado: se puede **comprar** el negocio 3 en lugar de cambiar de plan (evita P3) | Si no se mide el costo fijo por negocio, la cuota es una cifra inventada. Hay que instrumentarlo antes de fijarla |
| Mantiene el dueño de dos negocios pequeños en un solo plan | |

### Cuántos negocios por plan (recomendación, `[H]`)

| Plan | Negocios incluidos | Negocio extra | Razón |
|---|---:|---|---|
| Básico | **2** | Se puede comprar hasta 3 en total | Es el caso real que existe (Bianki + Polette, `[V]`); Later Growth, el único otro plan con generación que incluye más de 1, también da 2; un Básico con 5 marcas ejecuta el peor caso de un solo cupo sobre 5 negocios, y el cupo compartido no escala (30 creaciones / 4 videos entre 5 negocios son 6 / 0,8 por negocio) |
| Plus | **3** | Hasta 5 | Predis Rise da 4; el cupo duplicado (60/8/40) da unos 20 creaciones y 2,7 videos por negocio con 3 |
| Pro | **5** | Hasta 8 | Iguala a Metricool Starter y a Canva Pro (5), la cifra que el dueño ya ve en otras herramientas, con el cupo más grande (120/16/80) |
| Más de 8 | No se vende como suscripción | Conversación aparte | Es una agencia; el carril de Meta y la capacidad de atención son otros (`oferta-mercado-agencia-gestionada.md`, hallazgo 3 de este doc) |

**Rango recomendado: de 2 a 5 negocios incluidos según el plan, con tope de 8 por suscripción.** El «2» de Básico es el número que hay que defender con datos: es el único que hoy tiene un cliente real detrás.

**Recomendación: Opción C, construida en dos pasos.** (1) Ahora, sin código: usar la Opción A **a mano** con Bianki y Polette (dos tenants con Básico, factura única, `just set-plan`) para medir uso real durante 60 días; no hay forma más barata de saber si el cupo compartido importa. (2) Si la medición lo confirma, pedir al principal-architect la entidad suscripción para B/C. Si no hace falta, A con descuento por segundo negocio basta y se ahorra la migración.

**Por qué no B sola:** deja sin cobrar el costo fijo por negocio, que nadie ha medido. **Por qué no A sola:** es el modelo que la propia épica ya descartó, y con 3 negocios triplica el peor caso (USD 165) sin que el dueño reciba más. `[H]`

---

## 6. Criterio de muerte

La recomendación se descarta, y se vuelve a la Opción A sin cupo compartido, si **cualquiera** de estas se cumple:

1. **El grupo no existe:** entre los primeros 10 clientes que entren (o entre los 10 candidatos que el fundador entrevista), **menos de 2** administran 2 o más negocios separados. Entonces el cupo compartido no vale su migración.
2. **Uso: el cupo compartido no se usa como compartido.** Con 60 días de datos de Bianki y Polette, **ninguno de los dos negocios** agota su Básico en un mes en que el otro sobra más del 50 %: el compartido no aporta nada frente a A.
3. **Costo:** el costo de generación real de una suscripción supera el **40 %** de lo que paga durante dos meses seguidos, con cualquier cifra de plan que se fije. Entonces el problema no es el número de negocios sino el cupo; se baja el cupo antes de tocar los topes.
4. **La demanda pide más de 5:** ≥ 3 de los primeros 10 dueños con varios negocios piden **más de 5** en el plan de entrada. Entonces el segmento es agencia y el tope de 8 protege lo que no debe: se rediseña, no se sube el número.

El umbral de 40 % y el de 2 de 10 son **elecciones mías**, sin dato; el fundador debe cambiarlos si los cree duros o blandos.

## 7. Lo que sigue desconocido y su experimento más barato

| Desconocido | Experimento mínimo |
|---|---|
| Cuántos clientes potenciales tienen 2 o más negocios | Preguntar en la lista de clientes y candidatos del fundador (una hoja, una tarde); documentar con nombres solo si el cliente lo autoriza |
| Cuánto pagaría un dueño de 2 negocios por la suma | Dos preguntas al dueño de Bianki y Polette: qué paga hoy por redes en los dos y qué haría con una factura única |
| Costo fijo real por negocio extra (consulta de comentarios, almacenamiento, mensajes) | Medir en producción por tenant durante 30 días: llamadas a Meta, GB en R2, mensajes de WhatsApp. Sin esto, la cuota por negocio no se puede fijar |
| Si el reparto entre negocios provoca quejas | Contador de uso por negocio visible desde el primer día, y registro de cuántas veces un negocio agotó lo que el otro dejó |
| Dónde queda el tope de 8 frente a Meta | Que el principal-architect resuelva `V-TP-7` antes de publicar cualquier tope en un precio |

## 8. Implicaciones para el fundador (una línea cada una)

- **Arquitectura:** la suscripción compartida necesita su entidad; hoy el plan es por tenant (D15). Decisión del principal-architect, antes de cualquier código.
- **Precio:** este doc no fija cifra; las anclas de §4 son el rango de lo que el dueño ya ve (5–19 por marca, 200–600 por servicio).
- **Canales/cobro:** el cobro en moneda local y a mano (D19) es una ventaja frente a todas las herramientas de la tabla, no una carencia.

## 9. Fuentes

Todas con fecha de acceso 2026-10-25. Páginas de precio: Metricool, Later, Buffer, Planable, SocialBee, Predis, Vista Social, Ocoya, Hootsuite (URLs en la tabla de §1). Publer: centro de ayuda (la página de precios devolvió una redirección en bucle). mLabs: blog oficial del 2025-07-25. Canva: Canva Brand Kit (403 al leerla; cifras por buscador, `[S]`). Quejas: [SocialPilot sobre Later](https://www.socialpilot.co/insights/later-pricing), [SocialBu sobre Buffer](https://socialbu.com/blog/buffer-pricing), [NapoleonCat sobre Buffer](https://napoleoncat.com/blog/buffer-pricing/), [PostPlanify sobre Planable](https://postplanify.com/blog/best-planable-alternatives), [Trustpilot de Metricool](https://ca.trustpilot.com/review/metricool.com). Costos de Qualify: [`modelo-cobro-generacion.md`](modelo-cobro-generacion.md) §5–§6 y D12–D19.
