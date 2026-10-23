# Perfil del cliente de Qualify — dueños de pymes y emprendimientos

`[v1 2026-10-23 · m-24842828]` · **Para quién es:** todo el que diseña, escribe o revisa algo que
ve un cliente (agente `ux-designer`, skill `qualify-ux`, `reflex-ui-engineer`, `product-owner`).
**Convención de confianza:** `[F]` afirmación o decisión del fundador (con fecha) · `[E]` evidencia
en el repositorio (con la fuente) · `[H]` hipótesis
sin evidencia todavía: se valida con las preguntas del §5 antes de tratarla como hecho.

> Este perfil se construyó con lo que ya está escrito en el repositorio y con lo que afirmó el
> fundador el 2026-10-23. Todavía no hubo entrevistas con clientes. Lo que no tiene fuente está
> marcado `[H]`.

## 0. A quién le vendemos — el segmento `[F]`

*Afirmación del fundador, 2026-10-23:* **dueños de emprendimientos y pymes con presupuesto acotado
para marketing, o que no quieren lidiar con marketeros y diseñadores ni gastar mucho en
marketing, pero sí quieren tener presencia en redes sociales.**

Lo que quieren resolver, en este orden:

1. **Verse presentes en redes sin contratar una agencia ni un diseñador.**
2. **Gastar poco**: el presupuesto de marketing es chico o no existe.
3. **Dedicarle poco tiempo**: el negocio se atiende primero; las redes, en los ratos libres.

Todo lo que ve el cliente se juzga contra esas tres cosas: ¿le ahorra un marketero, le ahorra
dinero, le ahorra tiempo?

## 1. Quiénes son hoy

| Negocio | Rubro | Dónde | Qué sabemos | Fuente |
|---|---|---|---|---|
| **Bianki** | Tienda de **shawarma y ensaladas** | Korner, San Cristóbal, Táchira (VE) | Promesa «Precio a la vista, porción en mano»: la foto tiene que ser la comida real; voz casual con humor local; atiende pedidos por WhatsApp | `[F]` oferta (fundador, 2026-10-05 y 2026-10-23) · `[E]` voz y promesa: `estrategia-contenido-bianki-polet.md` §1; WhatsApp: `plan-modulo-whatsapp-cloud-api.md` |
| **Polette** (antes Polet) | Tienda de **helados de yogur** | Puerta con puerta con Bianki | Voz cálida y personal, la marca lleva el nombre de la hija del dueño; tarjeta de sellos (9 compras → 1 gratis) | `[F]` oferta (fundador, 2026-10-05 y 2026-10-23) · `[E]` voz y sellos: `estrategia-contenido-bianki-polet.md` §1 (de agosto, con la oferta anterior) |
| **PuntoServis** | Comida y bebidas | — | Solo aparece en la lista de clientes reales | `[E]` skill `qualify-context` §1 |
| **El inmobiliario** | Bienes raíces | Táchira / Cúcuta | Comprador de LATAM; casi no hay reseñas públicas de herramientas de la región para conocer sus problemas | `[E]` `demanda-ventas-inmobiliario.md` §0 |
| **Agencia de viajes** | Turismo (Santa Marta, Caribe) | Cúcuta (CO), público de los dos lados de la frontera | Negocio en lanzamiento; su dueño trabajó en una aerolínea, así que sabe de su rubro, no de marketing; quiere responder comentarios y mensajes en ≤ 2 h, y luego en ≤ 1 h | `[E]` `cliente-agencia-viajes-cucuta-prioridades-mvp.md` §2 |

**Mercados:** Colombia, Venezuela y Uruguay; hispanohablantes; pequeños negocios, no equipos de
marketing de empresa grande `[E]` (`qualify-context` §1).

**Quién usa la pantalla hoy.** En la mayoría de los casos el fundador o el equipo de Attitude
Factory operan la herramienta *por* el negocio (modelo de agencia gestionada: Qualify es la
herramienta interna y el cliente paga el servicio) `[E]` (`cliente-agencia-viajes-cucuta-prioridades-mvp.md`,
recuadro «Marco de negocio»; `modelo-negocio-operador-multi-emprendimiento.md`). Las pantallas se
diseñan **para el dueño del negocio**, que es hacia donde va el producto. Cuando un dueño
opere su propia cuenta, esto deja de ser hipótesis y pasa a ser lo que se valida `[H]`.

Bianki y Polette son los dos emprendimientos del propio fundador: encajan exactamente en el
segmento del §0 y son el acceso más fácil para validar este perfil.

## 2. Persona principal — «Dueño de local que hace todo»

Retrato compuesto a partir del segmento del §0, Bianki, Polette y la agencia de viajes. No es una
persona real.

- **Quién es:** dueño o dueña de un emprendimiento o pyme, con poco personal y poco presupuesto
  para marketing, que no quiere contratar ni coordinar marketeros y diseñadores, pero sí quiere
  que su negocio se vea en redes `[F]` (fundador, 2026-10-23). Atiende, compra, cobra y además
  «tiene que estar en redes» `[H]`, por analogía con lo que se sabe de los
  locales del Korner, que abren de 7:00 o 11:00 a 21:00 `[E]`.
- **Cómo usa Qualify:** desde el **celular**, entre una tarea y otra `[E]` (`qualify-copy-es`).
  Lee rápido y abandona si algo le confunde `[H]`.
- **Qué sabe:** sabe mucho de su negocio y poco de marketing; no conoce «engagement», «feed»,
  «CTA» ni «Brand Kit» `[H]`. El dueño de la agencia de viajes es un profesional de su rubro, no un
  publicista `[E]`.
- **Qué quiere obtener** (en sus palabras, no en las nuestras):
  - «Estar en redes sin tener que pagarle a una agencia ni a un diseñador» `[F]`.
  - «Tener publicaciones listas sin pensar qué subir cada día» `[E]`: calendario de 12–16
    publicaciones y 8–12 reels al mes (agencia de viajes, brief §3.3).
  - «Que nadie se quede sin respuesta» `[E]`: comentarios y mensajes en menos de 2 horas (brief §3.3).
  - «Que lo que publico se parezca a lo que vendo» `[E]`: foto real del producto, nunca una imagen
    inventada de la comida (`estrategia-contenido-bianki-polet.md` §0).
  - «Que vuelvan los que ya me compraron» `[E]`: sellos y cupones por WhatsApp (`backlog-loyalty-sellos-cupones.md`, origen).
- **Qué le frena:** falta de tiempo y de presupuesto `[F]`; miedo a publicar algo que no aprobó; formularios largos;
  palabras que no entiende `[H]`.
- **Qué no hacemos por él:** Qualify nunca publica ni responde solo, siempre es él quien aprueba
  `[E]` (decisión firmada, ADR 21). El texto nunca promete lo contrario.

## 3. Persona secundaria — «Operador del equipo»

El fundador o alguien del equipo que maneja varios negocios, uno por sesión (`1 login = 1 negocio`,
cambiar de negocio = cerrar sesión y volver a entrar) `[E]`
(`modelo-negocio-operador-multi-emprendimiento.md`). Conoce el vocabulario técnico, pero **la
pantalla no se escribe para él**: si el dueño entra mañana, debe entenderla igual.
Lo que le importa: procesos repetidos rápidos (la misma secuencia cada semana para cada negocio) `[H]`.

## 4. Qué implica para el diseño

1. **Hablar de lo que obtiene, no de lo que tiene la herramienta.** «Tus publicaciones de la
   semana, listas para aprobar», no «Módulo Planificador» (detalle y ejemplos: skill `qualify-ux`).
2. **Cero palabras técnicas o en inglés**: lista en `qualify-copy-es` y `qualify-ux`.
3. **Un paso, una decisión.** Los procesos que se repiten (crear una pieza, completar la identidad
   de marca, dar de alta un producto) van guiados en pasos cortos, con valores ya rellenados
   y la posibilidad de volver atrás.
4. **Pensado para el celular primero**: botones grandes, una columna, nada que exija pasar el mouse por encima.
5. **Siempre se ve qué falta para terminar** y qué pasa al tocar «Aprobar» o «Publicar».

## 5. Validar con clientes reales

**A quién entrevistar.** Dueños que encajen en el segmento del §0. Primero los clientes actuales,
que son el acceso más fácil: **Bianki y Polette** (del fundador), la **agencia de viajes** de Cúcuta
y el **inmobiliario**. Después, dueños de otros emprendimientos de la zona que todavía no usan Qualify.

**Criterios para elegir a quién entrevistar** (tiene que cumplir los tres):

1. Es **el dueño o quien decide** en un emprendimiento o pyme (no un empleado de marketing).
2. Tiene **poco o ningún presupuesto de marketing**, o no quiere pagar ni coordinar marketeros y
   diseñadores.
3. **Quiere estar en redes** (Instagram, Facebook, WhatsApp) aunque hoy publique poco o nada.

Se descarta a quien ya tenga agencia o equipo de marketing propio: no es nuestro cliente.

Conversaciones cortas (15–20 min, por WhatsApp o en el local). Cada respuesta actualiza este
documento y cambia `[H]` → `[E]` citando quién y cuándo.

1. ¿Cuánto gasta hoy en marketing (dinero y horas) y qué haría falta para que lo deje en nuestras
   manos? ¿Alguna vez contrató a un marketero o diseñador? ¿Por qué lo dejó, o por qué nunca lo hizo?
2. ¿Quién del negocio entraría a Qualify: el dueño, un empleado o nadie (lo opera el equipo)?
3. ¿Desde qué dispositivo y en qué momento del día? ¿Cuántos minutos le dedica a redes por semana?
4. ¿Qué palabras usa para lo que hace en redes? (Anotar las suyas literalmente: «subir algo»,
   «estado», «historia»…)
5. ¿Qué es lo que más le cuesta hoy: saber qué publicar, hacer la imagen, escribir el texto,
   responder o medir?
6. Mostrarle una pantalla real (p. ej. Crear pieza): ¿dónde se detiene? ¿qué no entiende?
7. ¿Qué tendría que pasar en un mes para decir «valió la pena»? (Más mensajes, más ventas, menos tiempo…)
8. ¿Qué le daría miedo que la herramienta hiciera sin preguntarle?
