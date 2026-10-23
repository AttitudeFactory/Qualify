# Perfil del cliente de Qualify — dueños de pymes y emprendimientos

`[v1 2026-10-23 · m-24842828]` · **Para quién es:** todo el que diseña, escribe o revisa algo que
ve un cliente (agente `ux-designer`, skill `qualify-ux`, `reflex-ui-engineer`, `product-owner`).
**Convención de confianza:** `[E]` evidencia en el repositorio (con la fuente) · `[H]` hipótesis
sin evidencia todavía: se valida con las preguntas del §5 antes de tratarla como hecho.

> Este perfil se construyó **solo con lo que ya está escrito en el repositorio**. No hubo
> entrevistas con clientes. Lo que no tiene fuente está marcado `[H]`.

## 1. Quiénes son hoy

| Negocio | Rubro | Dónde | Qué sabemos | Fuente |
|---|---|---|---|---|
| **Polet Bubble Tea** | Bebidas (bubble tea) | Korner, San Cristóbal, Táchira (VE) | Público millennial y Gen Z; combos y tarjeta de sellos (9 compras → 1 gratis); voz cálida y personal, la marca lleva el nombre de la hija del dueño | `[E]` `estrategia-contenido-bianki-polet.md` §1 |
| **Bianki Gaucha** | Comida callejera uruguaya y brasileña, catering de oficina | Puerta con puerta con Polet | Promesa «Precio a la vista, porción en mano»: la foto tiene que ser la comida real; voz casual con humor local | `[E]` `estrategia-contenido-bianki-polet.md` §1 |
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

> **Contradicción por resolver:** `qualify-context` lista «Bianki/Polette» como marcas de **moda**;
> `estrategia-contenido-bianki-polet.md` describe **Bianki Gaucha** (comida) y **Polet Bubble Tea**
> (bebidas). Hay que confirmarlo con el fundador (§5, pregunta 1) y corregir el documento que esté mal.

## 2. Persona principal — «Dueño de local que hace todo»

Retrato compuesto a partir de Polet, Bianki y la agencia de viajes. No es una persona real.

- **Quién es:** dueño o dueña de un negocio pequeño, con poco personal, que atiende, compra,
  cobra y además «tiene que estar en redes» `[H]`, por analogía con lo que se sabe de los
  locales del Korner, que abren de 7:00 o 11:00 a 21:00 `[E]`.
- **Cómo usa Qualify:** desde el **celular**, entre una tarea y otra `[E]` (`qualify-copy-es`).
  Lee rápido y abandona si algo le confunde `[H]`.
- **Qué sabe:** sabe mucho de su negocio y poco de marketing; no conoce «engagement», «feed»,
  «CTA» ni «Brand Kit» `[H]`. El dueño de la agencia de viajes es un profesional de su rubro, no un
  publicista `[E]`.
- **Qué quiere obtener** (en sus palabras, no en las nuestras):
  - «Tener publicaciones listas sin pensar qué subir cada día» `[E]`: calendario de 12–16
    publicaciones y 8–12 reels al mes (agencia de viajes, brief §3.3).
  - «Que nadie se quede sin respuesta» `[E]`: comentarios y mensajes en menos de 2 horas (brief §3.3).
  - «Que lo que publico se parezca a lo que vendo» `[E]`: foto real del producto, nunca una imagen
    inventada de la comida (`estrategia-contenido-bianki-polet.md` §0).
  - «Que vuelvan los que ya me compraron» `[E]`: sellos y cupones por WhatsApp (`backlog-loyalty-sellos-cupones.md`, origen).
- **Qué le frena:** falta de tiempo; miedo a publicar algo que no aprobó; formularios largos;
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

## 5. Preguntas para validar con clientes reales

Se responden en conversaciones cortas (15–20 min, por WhatsApp o en el local) con los dueños de
Polet, Bianki, la agencia de viajes y el inmobiliario. Cada respuesta actualiza este documento y
cambia `[H]` → `[E]` citando quién y cuándo.

1. ¿Bianki/Polette es una marca de moda, o se trata de Bianki Gaucha y Polet Bubble Tea? (Para el fundador.)
2. ¿Quién del negocio entraría a Qualify: el dueño, un empleado o nadie (lo opera el equipo)?
3. ¿Desde qué dispositivo y en qué momento del día? ¿Cuántos minutos le dedica a redes por semana?
4. ¿Qué palabras usa para lo que hace en redes? (Anotar las suyas literalmente: «subir algo»,
   «estado», «historia»…)
5. ¿Qué es lo que más le cuesta hoy: saber qué publicar, hacer la imagen, escribir el texto,
   responder o medir?
6. Mostrarle una pantalla real (p. ej. Crear pieza): ¿dónde se detiene? ¿qué no entiende?
7. ¿Qué tendría que pasar en un mes para decir «valió la pena»? (Más mensajes, más ventas, menos tiempo…)
8. ¿Qué le daría miedo que la herramienta hiciera sin preguntarle?
