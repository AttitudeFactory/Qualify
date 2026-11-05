# Épica — Creadores (Instagram primero)

`[VIGENTE 2026-11-04]` · Épica en Meegle: **m-24880379** «Invitaciones a influencers locales por
afinidad con la empresa» (PM Deivid Vargas), ampliada con la sección «Plan ampliado 2026-11-04
(decisión del fundador)». Diseño técnico: `docs/diseno-modulo-creadores.md`; experiencia y textos:
`docs/ux-creadores.md`; enmienda de la ADR 33: `docs/arquitectura.md` §6 (en redacción por
principal-architect). Si este documento y esos difieren en diseño o en textos, mandan esos.

## 1. Objetivo

Que el dueño de un negocio pequeño pueda **elegir con datos reales** a qué creadores de Instagram
invitar, cuánto ofrecerles y llevar la conversación hasta un acuerdo, **sin agencia** y sin que
Qualify hable por él. Primero lo usa el equipo interno (negocios de los fundadores, detrás de un
interruptor); después los clientes.

**Evidencia:** decisión del fundador (Herwin, 2026-11-04, en chat) `[F]`; la épica de Deivid
(m-24880379, 2026-10-27) ya describía campaña, encaje explicable e invitación asistida.

## 2. Lo que ya existe en el disco (2026-11-04, `main` en `fef94c29`)

- `/creadores` es una pantalla «Pronto» (`Qualify/creators_page.py`, menú en `Qualify/ui/layout.py`).
- `qualify_api.creators`: un pool **global** de cuentas públicas (`creators`, `creator_sightings`,
  `vendor_payloads`; migración 0036, sin `tenant_id` por diseño, como el catálogo de hashtags 0023).
- `qualify_api.vendors.scrapecreators.metered_get`: la **única puerta medida** de llamadas pagadas a
  ScrapeCreators (ADR 42: piso global de 500 créditos, alerta a Lark bajo 2.000, topes por negocio
  de 150 créditos/día y 600/mes).
- `public_reels` (0117) y `qualify_api.referentes.reel_store`: reels públicos guardados una vez para
  todos los tenants.
- No existe: lista de creadores seguidos por negocio, métricas por creador, ficha, comparación,
  campaña, encaje, invitación, oferta ni negociación.

## 3. Las cinco entregas

| # | Entrega | Qué gana el dueño | Estado de bloqueo |
|---|---|---|---|
| 1 | **Analizar** (+ **Comparar creadores**) | Ver de verdad cuánto rinde un creador y ponerlo al lado de otros antes de decidir | Libre — empieza primero |
| 2 | **Encajar** | Saber por qué un creador le sirve a *su* campaña, con reels concretos como prueba | Libre de la ADR; **no se enciende** sin pasar la evaluación (golden set) |
| 3 | **Invitar** | Un mensaje con la voz de su marca listo para copiar y mandar él mismo | **Bloqueada hasta la firma de la ADR que enmienda la 33** |
| 4 | **Presupuestar** | Saber cuánto le cuesta cada 1.000 vistas esperadas y si se pasa de su tope | **Bloqueada hasta la firma de la ADR que enmienda la 33** |
| 5 | **Negociar** | Llevar ofertas y contraofertas ordenadas, con respuestas sugeridas que él aprueba | **Bloqueada hasta la firma de la ADR que enmienda la 33** |

**Analizar.** Agregar un creador de Instagram por @usuario, a mano; se leen su perfil y sus últimos
48 reels (≈ 5 créditos: 1 de perfil + ~4 páginas de reels — `[H]`, se confirma con el CLI). Ficha:
seguidores, vistas de un reel típico (mediana) y promedio, vistas por seguidor, interacción, ritmo
de publicación, reels con más vistas, reels destacados (≥ 2 veces su propia mediana), duración que
mejor le funciona, colaboraciones pagadas, audios que más usa; botón «Actualizar» manual.

**Comparar creadores.** De 2 a 4 lado a lado sobre la misma ventana; se resalta el mejor de cada
fila; **no hay puntaje sumado**; aviso «datos de hace N días» si están viejos; lo desconocido se ve
como «sin dato», nunca como cero; en el teléfono, 2 por pantalla y se desliza. Comparar no gasta
créditos si los datos están frescos.

**Encajar.** Campaña (qué quiere lograr, producto del catálogo, ciudad, fecha, presupuesto máximo,
canje / pago / experiencia) y un puntaje de encaje por dimensión con razones que citan reels
concretos, marcadas comprobado / inferido / desconocido; preseleccionar o descartar con historial.

**Invitar.** Borrador con la voz de la marca; mandar es una acción explícita del dueño. La API de
Instagram no deja que el negocio escriba primero: copiar el texto y abrir el chat desde el teléfono
(Instagram, WhatsApp o correo), marcar «invitado». Las respuestas que llegan al Direct de Instagram
o al WhatsApp del negocio aparecen en Conversaciones, unidas al candidato. Un borrador nunca cuenta
como enviado; reintentar no duplica.

**Presupuestar.** Oferta por creador (entregables, fecha, derechos de uso, monto o canje), costo por
cada 1.000 vistas esperadas a partir de su mediana real, total frente al presupuesto máximo.

**Negociar.** Ofertas y contraofertas con versión; estados propuesta enviada → contraoferta →
aceptada / rechazada; respuestas asistidas en Conversaciones (nunca autónomas); resumen del acuerdo
para copiar.

## 4. Historias (Meegle, Issues bajo m-24880379)

Orden de construcción de la entrega 1: **m-24946121 → m-24946127 → m-24946129 → m-24946132** (1b puede empezar con datos de prueba
cuando 1a fije el formato guardado).

| Id | Historia | Área dueña | P | Tamaño | Depende de |
|---|---|---|---|---|---|
| 1a · m-24946121 | Creadores: seguir un creador de Instagram y leer su perfil y reels por la puerta medida | backend | P1 | M | — |
| 1b · m-24946127 | Creadores: métricas del creador con una fórmula versionada | backend (revisa datasci) | P1 | S | 1a |
| 1c · m-24946129 | Creadores: pantalla con la lista, agregar creador, ficha y «Actualizar» | ui | P1 | M | 1a, 1b |
| 1d · m-24946132 | Creadores: comparar de 2 a 4 creadores lado a lado | ui | P2 | M | 1b, 1c |
| ev · m-24946136 | Creadores: golden set del encaje negocio-creador (~20 pares juzgados por el fundador) | datasci | P2 | S | 1b |
| 2 · m-24946139 | Creadores: campaña y encaje explicable por creador (Encajar) | backend + datasci + ui | P2 | L | 1b, ev, diseño |
| 3 · m-24946140 | Creadores: invitación con la voz de la marca, enviada por el dueño (Invitar) | backend + ui | P3 | M | 2, **ADR** |
| 4 · m-24946141 | Creadores: oferta por creador y costo por cada 1.000 vistas (Presupuestar) | backend + ui | P3 | M | 2, **ADR** |
| 5 · m-24946143 | Creadores: ofertas y contraofertas con respuestas asistidas (Negociar) | backend + ui | P3 | L | 3, 4, **ADR** |

## 5. Dependencias

- **Puerta medida y topes (ADR 42):** toda lectura pagada pasa por `metered_get`; el gasto de
  Creadores se carga al negocio que lo dispara.
- **Pool global (0036/0117):** perfil y reels públicos se guardan una vez para todos; lo que es del
  negocio (a quién sigue, campañas, notas, ofertas, mensajes) va con `tenant_id` y RLS.
- **Interruptor:** con él apagado, `/creadores` sigue igual que hoy («Pronto»).
- **ADR que enmienda la 33:** la 33 dejó el contacto con creadores manual y descartó el
  marketplace (QUA-70-C). Las entregas 3–5 la reabren; ninguna se empieza antes de la firma.
- **Evaluación del encaje:** la entrega 2 no se enciende sin superar el umbral escrito antes de
  medir (`qualify-measure`).
- **Conversaciones / WhatsApp:** las entregas 3 y 5 reutilizan la bandeja y la cola aprobada que ya
  existen; no hay envío propio nuevo.

## 6. Fuera de alcance

Pagos o custodia de dinero, contratos firmados, cuentas de creadores dentro de Qualify, envío
masivo. **Más adelante:** resultados con `mentions`, TikTok, Meta Creator Marketplace, tarifario
propio de LATAM a partir de las ofertas registradas.

## 7. Ítems viejos relacionados

- **m-24789474** «Outlier score» (parking): absorbido por m-24946127 (reels destacados = ≥ 2 veces la mediana
  propia del creador). Enlazado, no cerrado.
- **m-24789507** «Módulo Creator Fit (umbrella)»: su frontera (ADR 33) se reabre con la enmienda; el
  plan vigente vive en esta épica. Comentado, no cerrado.

## 8. Preguntas abiertas para el fundador

1. **Tope de créditos de Creadores:** ¿comparte los 150/día y 600/mes de ADR 42 con «Ideas para tus
   reels», o lleva un tope propio (p. ej. 10 creadores nuevos al día)? Hasta decidir, comparte.
2. **Frescura:** ¿cuántos días valen los datos de un creador antes del aviso «datos de hace N días»
   y antes de que «Comparar» pida actualizar? Propuesta: 7 días.
3. **Interruptor:** ¿la lista de negocios internos la fija una variable de entorno por tenant (como
   los demás interruptores) o un ajuste de plan?
4. **Umbral del golden set:** ¿qué acuerdo con tu juicio exiges para encender Encajar? Propuesta del
   equipo de datos, escrita antes de medir.
5. **Moneda de Presupuestar:** el monto en la moneda del negocio; ¿se permite pagar en dólares a
   creadores de otro país?
