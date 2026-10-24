# Modelo de negocio — el operador multi-emprendimiento

**Fecha:** 2026-08-16 · **Estado:** `[FIRMADO como requisito por el fundador, 2026-08-16]` — el modelo es obligatorio («sí o sí»). **Ruling final del fundador, mismo día: `1 login = 1 tenant = 1 negocio`, sin switch** (ver §6.1, que sustituye toda mención anterior al switcher). Quedan abiertas D1/D4.
> **REVERTIDO por el fundador el 2026-10-23:** un login puede manejar varios negocios (tenants separados) desde una sola sesión, con selector para cambiar. El ruling de §6.1 deja de estar vigente; el diseño y las historias están en [`epica-multi-negocio-una-sesion.md`](epica-multi-negocio-una-sesion.md) (Meegle [m-24849186](https://project.larksuite.com/5h2wsx/story/detail/24849186)) y el ADR que lo firma es su historia S0.
**Origen:** instrucción del fundador (2026-08-16): *«agreguemos al modelo de negocio el gestionar desde una cuenta múltiples emprendimientos — en mi caso locales de comida rápida, inmobiliaria, agencia digital, etc.»*, refinada el mismo día en dos pasos: primero *«poderme switchear rápido»*, después el ruling final — *«mejor 1 login - 1 tenant - 1 negocio (olvidemos lo del switch), yo lo resuelvo con logout y login con credenciales guardadas; lo que sí, aseguremos que al hacer logout no se crucen datos de otro tenant en el UI, localStorage, cache, etc., por `tenant_id`»*.
**Convención de confianza:** `[V]` verificado contra fuente primaria (código en disco o corpus de Meta) · `[S]` fuente secundaria · `[H]` hipótesis o aritmética del autor.
**Documentos que este extiende, sin sustituir:** [`arquitectura.md`](arquitectura.md) §6 (nota de soporte *«Qualify como agencia»*, 2026-07-30, y ADR 24), [`oferta-mercado-agencia-gestionada.md`](oferta-mercado-agencia-gestionada.md), [`research-modelo-acceso-tech-provider.md`](research-modelo-acceso-tech-provider.md) §10.

---

## 0. Qué se agrega, en una frase

**La unidad de cuenta deja de ser la marca y pasa a ser el operador.** Una persona con un solo login gobierna **N emprendimientos heterogéneos** —negocios distintos, en países, monedas y rubros distintos— y necesita verlos por separado *y* en conjunto, sin cambiar de cuenta ni de contraseña.

No es un caso hipotético: es el fundador. `[V]` Hoy la base sembrada tiene dos tenants (`PuntoServis`, CO, y `Inmobiliaria UY`, UY — `packages/api/src/qualify_api/seed.py:115-154`) y la tabla `tenants` ya lleva `country`, `timezone` y `currency` por fila `[V]` (`tenancy/models.py:29-42`), es decir, **el esquema ya asume que dos negocios del mismo dueño pueden vivir en jurisdicciones distintas**. Súmese la agencia digital y los locales de comida rápida y el retrato está completo.

**Por qué esto es un cambio de modelo de negocio y no una feature:** cambia *quién compra*, *qué se cuenta para cobrar* y *en qué carril regulatorio de Meta cae el producto*. Las tres cosas se tratan abajo.

---

## 1. Tres niveles, y cómo mapean a lo que ya existe

| Nivel | Qué es | En el modelo de datos actual | Estado `[V]` |
|---|---|---|---|
| **Operador** | La persona que gobierna la cartera. Un login | **No existe** | `users.tenant_id NOT NULL` + `UNIQUE(tenant_id, email)` → la identidad es *local a un tenant* |
| **Emprendimiento** | Un negocio: la inmobiliaria, la agencia, la cadena de comida | `tenants` — ya lleva país/moneda/huso | Existe y encaja |
| **Activo** | Un local, una marca, una cuenta social conectada | `brands` + `social_connections` | Existe |

**Los locales de comida rápida son el caso que obliga a decidir el nivel más bajo.** Tres locales de la misma cadena no son tres emprendimientos: son tres activos de uno. La regla que propongo, coherente con la ya firmada en ADR 24 (*`brand_id` = qué se observa; `tenant_id` = quién puede verlo*):

> **Un local es una `brand` si tiene identidad social propia** (su cuenta, su contenido, sus comentarios). Si comparte la cuenta de la cadena, no es nada en el modelo: es un atributo del negocio, y a lo sumo un filtro de reporting. **Un emprendimiento es un `tenant` cuando cambia el país, la moneda, la fiscalidad o la propiedad** — porque son exactamente las columnas que `tenants` ya distingue, y porque es la frontera que uno querría poder vender, cerrar o ceder por separado.

---

## 2. Esto **no** es el modelo agencia, y la diferencia importa más de lo que parece

`arquitectura.md` §6 ya investigó *«Qualify como agencia»* (2026-07-30): usar la herramienta para gestionar más clientes de los que se gestionarían a mano, cobrando por servicio. **La máquina es la misma; el contrato y el carril regulatorio no.**

| | Agencia (ya investigado) | **Operador multi-emprendimiento (esto)** |
|---|---|---|
| De quién son los negocios | De terceros | **Del propio operador** |
| Qué se vende | Servicio gestionado (US$200–600/mes freelance, US$500–1.500 agencia en LATAM `[S]`) | **Software** — la cartera propia no se factura a sí misma un servicio |
| Techo de escala | ~8 clientes básicos o ~4 estándar por persona `[S]` (`oferta-mercado-agencia-gestionada.md` §2) | El techo lo pone el dueño, no la capacidad de atención |
| Carril de Meta | *«Tech Provider … serves multiple businesses»* → **Advanced Access + App Review requerido** `[V]` | *«My app is only for a business I own or manage»* → **Standard Access, App Review no requerido** `[V]` |

### 2.1 El hallazgo que hace valiosa esta adición — y el matiz que impide cantar victoria

`[V]` La tabla de *Development scenarios* del corpus de Meta (`reference/meta-instagram-platform/documentation/instagram-platform/app-review.md:11-16`, transcrita completa en `research-modelo-acceso-tech-provider.md` §10.2) tiene exactamente cuatro filas, y la exención de App Review depende del **escenario**, no de la etiqueta:

- *«My app is only for a business I own or manage»* → Standard Access, **App Review: Not required** (en **ambas** ramas de login).
- *«I am a Tech Provider and my app serves multiple businesses»* → Advanced Access, **App Review: Required**.

`[V]` Y la definición de Tech Provider (§10.1) dice *«on behalf of **other** individuals or businesses»*.

`[H]` **La lectura que esto habilita:** una cartera de negocios **propios** cae del lado *own or manage* aunque sean varios, porque el predicado que separa las filas es *«otros»*, no el plural. Si eso se sostiene, **el operador multi-emprendimiento es el único segmento que Qualify puede servir hoy sin el reloj administrativo** (Business Verification + App Review) que bloquea todo lo demás — el mismo reloj que `CLAUDE.md` declara vinculante en cliente uno y que la [prioridad de despliegue](prioridad-despliegue-subdominio.md) intenta arrancar.

**El matiz, y es serio:** `research-modelo-acceso-tech-provider.md` §10.2 deja explícitamente **sin resolver** (`V-TP-7`, del architect) la contradicción entre esa tabla y la definición de Tech Provider, que sí incluye *«a single integration on behalf of an individual client»*. Además, la cartera del fundador es **mixta**: la comida rápida y la agencia son suyas, pero la inmobiliaria es de un tercero cuyo stack él administra (ADR 29). **Basta un negocio ajeno en la cartera para que el carril pueda cambiar.** Por tanto:

> **No se planifica ningún lanzamiento asumiendo la exención.** Se registra como la hipótesis de mayor valor pendiente de verificar, y se verifica empíricamente contra el dashboard de la app — nunca contra documentación (misma regla que ADR 25 impone para las grafías de scope).

---

## 3. La consecuencia técnica: hoy no existe identidad global, y la ventana barata se cierra pronto

`[V]` Verificado hoy en disco, y ya documentado en `arquitectura.md` §6 (nota *«Qualify como agencia»*, §3):

1. `users.tenant_id NOT NULL` con `UNIQUE(tenant_id, email)` → **el fundador operando tres negocios son tres filas `users` sin relación entre sí** que casualmente comparten una cadena de email.
2. La política RLS es de igualdad de valor único (`tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`) y `tenant_session()` admite **un** tenant por transacción. Una consulta cruzada por el rol de aplicación no es difícil: es imposible.
3. `Qualify/tenant.py` es un selector de tenant **de desarrollo, sin login** (QUA-66 diferido): se elige un negocio, se trabaja, se cambia al siguiente. `[V]` Su propio docstring lo dice. **Eso ya es la forma del operador, hecha a mano.**

Aquella nota ya evaluó las tres formas posibles y dictaminó: **(b) N `tenant_session` secuenciales unidos en la aplicación** es la correcta hoy (cero migración, cero puerta nueva, holgada a N=5-10), y **(c) una tercera puerta `operator_session(operator_id)`** —que exige una tabla de identidad global deliberadamente **no** tenant-scoped, la primera grieta en *«todo lleva tenant_id»*— es *«correcta a futuro, merece ADR propia»*.

**Lo único que este documento cambia de aquel veredicto es la fecha.** Mientras el operador multi-emprendimiento era un caso teórico, (c) podía esperar indefinidamente. Ahora es el ICP, y hay una fecha concreta a la que llega: **el login (QUA-66)**. Y aquí aplica exactamente el argumento que ya ganó una vez, en ADR 24 — *«es greenfield ahora mismo; ésta es la última ventana en la que la decisión es barata»*:

> ~~**Regla que pido fijar antes de escribir el login:** el login no puede resolver `usuario → tenant` como una relación 1:1…~~ **SUPERSEDIDA por el ruling del fundador del mismo día (§6.1): `1 login = 1 tenant` ES el diseño.** Se conserva tachada porque su advertencia sigue siendo el precio conocido de la puerta que queda abierta: si algún día se quiere identidad global de operador, habrá que migrar credenciales de usuarios reales. El fundador firma sabiéndolo.

Nótese que `tenant_members` **ya** es una tabla de pertenencia con rol `[V]` — si esa puerta se reabre, la pieza que faltará no es la relación, es que la fila de identidad (`users`) deje de estar dentro de un tenant.

---

## 4. Qué se cobra `[H]` — toda esta sección es hipótesis, ninguna cifra está validada con un comprador

Tres formas posibles, y la que recomiendo no es la intuitiva:

| Forma | Cómo se ve | Problema |
|---|---|---|
| Por emprendimiento | US$X por negocio/mes | **Penaliza exactamente el wedge.** El dueño de cinco negocios pequeños paga cinco veces por cinco negocios que facturan poco cada uno. Es el modelo que lo expulsa |
| Plano por cartera | Una tarifa, negocios ilimitados | El coste real de Qualify (polls, tokens de modelo, almacenamiento) **sí** escala con los activos. Invita a la cartera que rompe el margen |
| **Por activo conectado, con la cartera como agrupación** | Base por operador + precio por cuenta social conectada | **Recomendada.** Es la unidad que cuesta dinero de verdad y la que ya usa el mercado: un agregador vende publicación+DM a **$1–6/cuenta conectada/mes** `[S]` (nota de tensión abierta en `CLAUDE.md`, verificada contra el reference de endpoints de Zernio) |

Dos consecuencias de elegir la tercera, que hay que aceptar de frente:

- **Fija un suelo competitivo.** Si el agregador cobra $1–6 por cuenta por hacer publicación y DM, Qualify no puede cobrar mucho más *por eso mismo*; lo que justifica el precio es la capa de listening/insights que el agregador no vende. **Vender esta cartera sólo con publicación es competir contra $1/mes.**
- **El local sin cuenta propia no paga**, lo cual es correcto y además coherente con §1: si no tiene identidad social, Qualify no ingiere nada por él.

---

## 5. Lo que puede tumbar la tesis (criterios de muerte)

1. **Si la exención de Meta no aplica a carteras mixtas** (§2.1), el segmento deja de ser «el que no espera el reloj» y pasa a ser uno más detrás de App Review. Sigue siendo un ICP válido; deja de ser un atajo.
2. **Si el operador no quiere vista unificada sino sólo cambio rápido de contexto**, entonces (c) nunca hace falta y el selector actual con login encima basta. **Esto se pregunta, no se supone** — ver §6.
3. **Si los negocios de la cartera son demasiado heterogéneos para compartir producto** (una inmobiliaria y una hamburguesería no comparten ni contenido ni métrica ni comprador), el valor unificado se reduce a facturación y accesos, que es una capa de administración, no un producto. `[H]` La hipótesis contraria —que el trabajo repetitivo (publicar, responder, medir) *sí* es idéntico entre rubros— es lo que sostiene todo el módulo, y hoy no está medida.

---

## 6. Decisiones que necesita el fundador

| # | Pregunta | Recomendación |
|---|---|---|
| **D1** | ¿Un emprendimiento = un `tenant`, con la regla de §1 (país/moneda/propiedad)? | Sí. Es la única frontera que ya distingue el esquema y la única que permite ceder o cerrar un negocio sin tocar los otros |
| **D2** | ¿Vista **unificada** entre negocios, o sólo **cambio de contexto**? | Empezar por cambio de contexto con login (forma (b)). La vista unificada sólo tiene sentido cuando haya estado cruzado que mirar |
| **D3** | ¿El login se escribe con identidad global desde el día uno? | **Sí, y es lo urgente de este documento.** No hace falta construir (c) entera; hace falta no hornear 1:1 en `users` |
| **D4** | ¿Precio por activo conectado (§4)? | Sí, con base por operador. Pero no se fija cifra sin un comprador delante |
| **D5** | ¿La cartera propia se usa como banco de pruebas antes que cualquier cliente externo? | Sí — es el único segmento posiblemente exento del reloj administrativo, y es el que el fundador puede instrumentar sin pedir permiso a nadie |

### 6.1 ~~Ruling final del fundador (2026-08-16): `1 login = 1 tenant = 1 negocio` — el switch se elimina~~ `[REVERTIDO 2026-10-23]`

> **Revertido por decisión explícita del fundador (Herwin, 2026-10-23).** Nuevo objetivo: un dueño maneja varios negocios desde una sola sesión, con selector para cambiar; primer caso real, Bianki y Polette. D2 y D3 se reabren y se resuelven en [`epica-multi-negocio-una-sesion.md`](epica-multi-negocio-una-sesion.md) (ADR en la historia S0). Lo de abajo se conserva como historia. **Los criterios de higiene de logout siguen vigentes**: el cambio de negocio de la épica (S4) los hereda, ahora también para el cambio sin salir.

El mismo día hubo dos rulings sucesivos y **gana el segundo**: primero se pidió un switch rápido entre negocios; después el fundador lo revocó — *«mejor 1 login - 1 tenant - 1 negocio, olvidemos lo del switch; yo lo resuelvo con logout y login con credenciales guardadas en el navegador»*. Estado resultante:

| # | Estado | Resolución |
|---|---|---|
| **D2** | **RESUELTA** | Ni switch ni vista unificada: **cambiar de negocio = logout + login**. El gestor de contraseñas del navegador hace de "switcher" fuera del producto |
| **D3** | **RESUELTA — en contra de la recomendación de §3, por decisión del fundador** | **Identidad local por tenant.** Que el fundador sean N filas `users` sin relación deja de ser una limitación y pasa a ser el diseño. Coste de construcción adicional: **cero** — es exactamente lo que el esquema ya hace `[V]` |
| El modelo en sí | **FIRMADO** | «Sí o sí»: N emprendimientos propios sobre la misma instalación, cada uno como tenant |
| D1, D4 | Abiertas | La regla local-vs-emprendimiento de §1 y el pricing de §4 siguen sin firma |

**Lo que se pierde con este ruling, aceptado con los ojos abiertos:** el sistema **no sabe** que los N negocios comparten dueño. Sin vista de cartera, sin facturación unificada dentro del producto (la «base por operador» de §4 queda sin sujeto: se cobra por tenant), y la hipótesis Meta de §2.1 no se ve afectada (la propiedad de los negocios es un hecho del mundo, no del esquema). La puerta no se cierra: `tenant_members` ya es relacional y un operador global puede añadirse después — pagando entonces la migración de credenciales reales que §3 advirtió. Se firma sabiéndolo.

**El requisito duro que sustituye al switch: higiene de logout.** En palabras del fundador: *«aseguremos que al hacer logout no se crucen datos de otro tenant en el UI, localStorage, cache, etc., por `tenant_id`»*. Si el logout/login va a ser el mecanismo de cambio de negocio, va a ejecutarse **muchas veces al día sobre el mismo navegador y el mismo perfil** — el caso raro se vuelve el camino caliente, y una fuga de estado rancio entre tenants deja de ser cosmética.

#### Criterios de aceptación de la higiene de logout (QUA-66 los hereda)

1. **Server-side primero, porque en Reflex el estado vive en el servidor.** Logout destruye el estado Reflex de la sesión y **rota/invalida el token de sesión**, de modo que un websocket viejo no pueda seguir empujando deltas del tenant anterior a una pestaña abierta. La app recarga a la pantalla de login — no «limpia» la UI en sitio.
2. **Namespace por `tenant_id` en TODA clave persistida en el cliente** (`rx.LocalStorage`, `rx.Cookie`, caches propios): defensa en profundidad — aunque el purge falle, una clave del tenant A es irrecuperable desde la sesión del tenant B porque el nombre no coincide. Prohibido persistir datos de negocio en una clave sin prefijo de tenant; se verifica con un test (grep/AST sobre los usos de `rx.LocalStorage`/`rx.Cookie` en `Qualify/`), no con una convención.
3. **Purge además del namespace, no en lugar de.** El logout borra las claves del tenant saliente. (El namespace protege la *confidencialidad entre tenants*; el purge evita además acumular basura de N negocios en un solo perfil de navegador.)
4. **La garantía de datos sigue siendo RLS.** Cada request del backend sigue entrando por `tenant_session(tenant_id)`; la higiene del cliente evita *pintar* estado rancio, no es el mecanismo de aislamiento. Nada de este punto relaja el criterio ya vigente «la sesión A nunca pinta datos del tenant B».
5. **Test E2E del ciclo completo:** login A → poblar UI (roster de conexiones, dashboards) → logout → login B en el mismo navegador → (a) nada del tenant A visible, (b) `localStorage`/`sessionStorage` sin claves de A legibles bajo B, (c) el websocket de la pestaña vieja de A quedó muerto, no re-suscrito como B.
6. **Resolución determinista `credencial → tenant`.** `users` permite el mismo email en N tenants (`UNIQUE(tenant_id, email)` `[V]`), así que un login con email solo es ambiguo. Regla: si un email existe en más de un tenant, el login **rechaza y pide desambiguar** — nunca adivina. **Confirmado por el fundador (2026-08-16): la estrategia operativa es `hlrd1993+[negocio]@gmail.com`, un alias por negocio** — todos entregan al mismo buzón, y cada entrada del gestor de contraseñas del navegador queda asociada a un negocio distinto, que es lo que hace útiles las credenciales guardadas como mecanismo de cambio. Consecuencia para el código: el login compara el email **literal** (`hlrd1993+puntoservis@…` ≠ `hlrd1993@…`); prohibido «normalizar» quitando el sufijo `+…`, porque destruiría exactamente la desambiguación que la estrategia aporta.

---

## 7. Qué **no** cambia

- **No reabre ADR 24.** `tenant_id` sigue siendo la frontera de aislamiento y `brand_id` sigue siendo lo observado. El operador es un nivel **por encima**, no un reemplazo — y, como ya advirtió `arquitectura.md` §6, una dimensión de operador **no** entra en las claves del plano analítico: operador→tenants es un mapeo pequeño que se resuelve *antes* de la consulta.
- **No adelanta trabajo de Fase 6.** Cuotas por tenant, aislamiento de cómputo y auditoría multi-tenant siguen donde estaban.
- **No cambia el orden de construcción** que fijó `arquitectura.md` §6 §4: primero cablear **un** bucle recurrente de punta a punta (ingesta de comentarios) para **un** negocio. Un panel de cartera con tres negocios vacíos sigue siendo una hoja de cálculo.
- **No convierte a Qualify en agencia ni deja de serlo.** Son dos modelos que conviven sobre la misma máquina; este documento sólo añade el que no requiere vender horas.
