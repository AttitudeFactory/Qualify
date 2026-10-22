# Proceso para disparar investigación de nichos y oportunidades de mercado

**Propósito de este documento.** No es investigación de mercado — es el *proceso* que decide cuándo y cómo se dispara una. Se escribe después de la sesión de investigación del 2026-07-29/30 (real estate → pipeline de nichos → marca regulada → modelo de agencia), que sirvió como el primer recorrido completo del ciclo y dejó lecciones concretas, algunas costosas. Este documento las convierte en procedimiento para que la próxima sesión no las repita.

**Dueño:** `qualify-lead` (sesiones `/team-research`; hasta 2026-10-22 lo era `research-lead`). Este documento se actualiza cada vez que una sesión de investigación descubre un fallo de proceso nuevo — igual que el ledger de SAGE, pero para el *método*, no para los resultados.

---

## 1. Qué dispara una investigación de nicho

No es un calendario fijo. Se dispara por cualquiera de estas señales, en orden de fuerza:

1. **Un cliente real lo pide o lo insinúa.** La señal más fuerte posible — ya hay alguien pagando o a punto de pagar. (Así arrancó esta sesión: cliente uno es inmobiliario y no tenía doc de research.)
2. **Una asimetría en el propio portafolio de research.** Si un nicho tiene cliente pagando y cero investigación (o viceversa: mucha investigación y cero cliente), esa asimetría es en sí misma una señal — inspeccionarla primero.
3. **Un hallazgo de otra investigación la menciona de pasada.** Ej.: la investigación de real estate mencionó "agencias que gestionan múltiples clientes" como hipótesis de escape (§9.5 de `docs/oportunidades-mercado-marca-regulada.md`) — eso es una nominación, no una decisión, y debe tratarse como tal hasta que se investigue.
4. **El fundador tiene una intuición de negocio.** Válida como disparador, **no** como validación — toda intuición entra al mismo embudo de la sección 2, sin atajos.
5. **Cadencia de mantenimiento.** A falta de señales 1-4, revisar el portafolio completo (todos los nichos con doc) cada ~2-3 meses por el motivo de la sección 4 (sesgo geográfico/temporal que se acumula sin que nadie lo note).

**Regla dura, aprendida esta sesión:** un nicho nominado por señal 3 o 4 NO se trata como validado hasta pasar el embudo completo. La investigación de real estate perdió tiempo real tratando implícitamente EE. UU. como el mercado por defecto — la intuición inicial no vino marcada como hipótesis a verificar.

---

## 2. El embudo — tres pasos obligatorios, en este orden, antes de construir nada

### Paso 0 — Fijar jurisdicción/comprador ANTES de puntuar nada

**La lección más cara de toda la sesión, repetida tres veces (real estate T-1, pipeline de nichos, marca regulada).** Antes de asignar un score de adyacencia o de demanda a cualquier candidato:

- ¿Quién es el comprador real (país, tipo de empresa, tamaño)? No asumir que es el mismo que el cliente actual — puede ser un mercado nuevo, y eso está bien, pero debe decidirse explícitamente, no heredarse por defecto.
- Si el nicho se apoya en un marco regulatorio (compliance, protección de datos, publicidad), **verificar que ese marco aplica en la jurisdicción del comprador real**, no en la jurisdicción donde se encontró la fuente más fácil de buscar (inglés, EE. UU.).
- Si la respuesta cambia según el país, **documentar los dos regímenes por separado**, como se hizo en `docs/oferta-mercado-inmobiliario.md` §5 y `docs/oferta-mercado-marca-regulada.md` §1.

**Costo de saltarse este paso:** la mejor tesis de la sesión de real estate (T-1, riesgo de fair-housing) se cayó por completo cuando se verificó la jurisdicción — y para entonces ya se le habían dedicado varias rondas de análisis.

### Paso 1 — Verificar la oferta y el foso (E-FOSO), no solo la demanda

Pregunta única: **¿puede un competidor adquirir este contenido/capacidad sin construir lo que Qualify construye?** Tres vías de escape conocidas que anulan el foso (ver `docs/oportunidades-mercado-pipeline-candidatos.md` §8.2 para el detalle):

- El contenido vive en **YouTube** (Gemini lo ingiere por URL, ~$0,001/vídeo — cero ventaja de adquisición).
- El contenido vive en **cuentas propias del cliente** (owned media — comprable vía agregador tipo Zernio, $1-6/cuenta/mes, App Review incluido).
- El contenido son **reseñas o web pública** (comoditizado).

**El foso real de Qualify hoy existe solo en earned media sobre TikTok/Instagram.** Cualquier candidato que no viva ahí necesita una razón distinta para ser interesante (ej.: distribución/canal, no tecnología).

**Corolario del E-FOSO⁺:** el foso es más fuerte donde el sujeto observado tiene incentivo activo a NO ser observado — ahí el consentimiento es inexistente en principio, no solo caro. Un sujeto que coopera con su propia medición (ej. un creator patrocinado feliz de que lo midan) tiene un foso más débil que uno que no coopera (ej. un afiliado haciendo un claim prohibido).

### Paso 2 — Verificar la demanda con **E1**, y no confundirla con el foso

Pregunta separada: **¿el comprador ya paga hoy por ALGÚN producto de información sobre el mundo exterior** (no sobre su propia actividad)? Un vendor cobrando por esto es evidencia de que la categoría existe — no de que el comprador específico, en esta geografía, a este precio, la compre.

**Trampa documentada dos veces esta sesión, y hay que vigilarla activamente:** es fácil puntuar el mismo hecho (un vendor establecido cobra por esto) con signos opuestos según de quién sea el candidato — "el mercado ya está servido" si es el candidato de otro analista, "la categoría está probada" si es el propio. Separar SIEMPRE en dos preguntas: (a) ¿existe presupuesto para esta clase de información? y (b) ¿hay espacio para entrar? — la (a) sube con cada vendor nuevo, la (b) baja.

**La tijera a vigilar (apareció dos veces, en farmacovigilancia y en marca regulada):** cuando la superficie *obligatoria* (por ley o contrato) es la misma que la superficie *comprable* (owned media, ya resuelta por un agregador barato), y la superficie *defendible* (earned media, foso real) no es la que la ley obliga a mirar — el negocio no tiene motor económico. Preguntar explícitamente: **¿la parte que la ley exige es la parte que Qualify puede defender, o son partes distintas?**

### Paso 3 — Verificar contra disco, no contra los docs

Toda afirmación de "esto ya está construido" o "esto es fácil de construir" se verifica leyendo el código, no citando `CLAUDE.md` o `arquitectura.md` (que describen arquitectura objetivo, no estado real). Ver el propio README del proyecto: "antes de asumir que un archivo, servicio o comando existe, revisa el filesystem." Esta sesión encontró repetidamente que "encaja limpio con lo que hay en disco" se usaba como señal de foso cuando en realidad solo mide costo de construcción — dos variables distintas que pueden moverse en direcciones opuestas (ver `docs/oportunidades-mercado-marca-regulada.md` §9, farmacovigilancia).

---

## 3. Disciplina de equipo — lo que se aprendió sobre CÓMO correr esto, no sobre QUÉ investigar

- **Fijar el presupuesto de profundidad ANTES de spawnear, explícitamente, no solo el entregable.** "Pase liviano" no bastó para frenar una espiral de auto-corrección mutua entre dos analistas que llegó a 700+ líneas antes de que el lead tuviera que cortarla. Decir: "máximo N rondas" o "máximo N horas-agente", no solo "rápido".
- **No dejar tareas del tablero compartido sin dueño asignado.** Un agente idle puede auto-reclamar una tarea sin dueño y duplicar trabajo — a veces productivo (forzó un criterio nuevo), pero no es gratis y no es controlable. Asignar `owner` siempre al crear la tarea.
- **La ronda adversarial es obligatoria, no decorativa.** Cuando dos analistas convergen fácilmente, sospechar que comparten el mismo sesgo (mismo brief, mismo idioma de búsqueda) antes de leerlo como validación independiente.
- **El eje de ventas (`market-analyst` en modo demanda; antes `sales-consultant`) es hipótesis, nunca evidencia.** No mezclar sus rehearsals con hallazgos anclados a fuente real. Si no hay corpus público de compradores de ese nicho, decirlo — no rellenar con marketing de vendor disfrazado de demanda.
- **Un hallazgo que llega solo por mensaje entre agentes no sobrevive si la sesión muere.** Todo lo que cambie una conclusión debe tocar disco, por quien lo descubre — no basta con que el lead lo sepa.

---

## 4. Qué hacer con el resultado

- **Si el nicho sobrevive el embudo:** pasa a `docs/registro-validacion-features.md` como feature(s) validada(s), con nicho, evidencia y eje (inbound/outbound) asignados. Desde ahí lo toma `product-owner` (`/team-po`) para convertirlo en backlog.
- **Si el nicho NO sobrevive:** se documenta igual, como **decline**, con las condiciones de reapertura explícitas (qué tendría que cambiar para que valga la pena reabrirlo). Un decline bien documentado es tan valioso como una validación — evita que el mismo nicho se re-investigue desde cero en un año.
- **Nunca se decide silenciosamente.** Toda decisión de seguir o no seguir con un nicho, o de qué construir primero, se presenta al fundador antes de tocar el backlog real.
