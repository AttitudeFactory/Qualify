# Cuentas propias reservadas por marca — qué hace hoy y qué queda por decidir

`[IMPLEMENTADO 2026-10-06, PR #86 · DECISIONES ABIERTAS]`

Petición (2026-10-06): *si a@gmail.com se registró con su usuario de Instagram y b@gmail.com quiere usar ese mismo usuario, que no pueda: son datos sensibles y no deben compartirse.*

Este documento recoge lo que se construyó, cómo se comporta en cada caso y las decisiones que quedaron pendientes. El detalle técnico está en `docs/ui-brandkit-wizard.md` §4.11, en `qualify_api.creative.account_claims` y en el docstring de la migración 0044.

## 1. Qué hace hoy

- En **Tu cuenta** del Brand Kit, al pulsar Instagram o TikTok, la cuenta escrita se **reserva para la marca de la sesión antes de leer nada** (ni la caché ni Scrape Creators).
- Si otra marca (otro correo) ya la tiene reservada, no se lee y aparece: *"Esta cuenta ya está registrada en Qualify con otro correo. Si es tuya, entra con el correo con el que la registraste."* El mensaje no dice de quién es la cuenta. No redirige a ningún sitio: la persona se queda en Tu cuenta y puede escribir otro usuario.
- Si la lectura falla (por ejemplo, un usuario mal escrito), la reserva recién hecha se libera.
- Si la lectura sale bien, la marca se queda solo con esa cuenta en esa red y la que tenía antes queda libre.
- Instagram y TikTok son cuentas distintas aunque el nombre coincida. "@MiduDev" y "midudev" son la misma cuenta.
- Tabla `social_account_claims` (migración 0044). Cada tenant solo ve sus propias filas (RLS), pero la regla "una cuenta = una marca" se aplica a todos los tenants. La segunda marca sabe que la cuenta está tomada sin ver nada de la primera.
- Al migrar se reservaron las cuentas que los Brand Kits ya tenían guardadas. Si había empate, ganó el tenant con cuenta creada frente al borrador sin cuenta y, después, el más antiguo.

## 2. Cómo se comporta en cada caso

La reserva se hace **al leer el perfil**, no al registrarse. En el asistente, el correo de la primera pantalla (`/brand/start`) ya crea un tenant borrador (migración 0037), y ese tenant es el que reserva la cuenta.

| Caso | Qué pasa |
|---|---|
| a lee su cuenta, termina el Brand Kit y se registra | La cuenta es de a. b no puede leerla. |
| a lee su cuenta, termina el Brand Kit pero **no se registra** | **También queda bloqueada para b.** El borrador de a la retiene aunque a nunca haya creado la cuenta. A nadie se le pide registrarse. |
| a vuelve más tarde con el **mismo correo** | Se retoma el mismo borrador (`find_open_draft`), así que es el mismo tenant y puede volver a leer su cuenta. Si se registra con ese correo, el registro adopta el borrador (`claim_draft`) y la reserva sigue siendo suya. |
| a vuelve con **otro correo** | Es otro tenant: queda bloqueado por su propio borrador anterior. |
| a abandona en Tu cuenta tras leer su cuenta | La cuenta queda reservada (los borradores no caducan). |
| a escribe mal su usuario y la lectura falla | No queda nada reservado. |
| a lee una cuenta y después otra en la misma red | La primera queda libre. |
| b agrega la cuenta de a como **referente, competencia o detractor** | Permitido: no pasa por la reserva (ver §3). |

## 3. Qué NO toca: el scrape de referentes

La reserva solo protege la cuenta **propia** de Tu cuenta (`BrandConnectState.analyze`). La búsqueda de referentes (`run_discovery`, `creator_discovery`, el pool compartido `creators` de la migración 0036) y "Agrégalo a mano" no pasan por `account_claims` y funcionan igual que antes.

Consecuencia: la cuenta de a puede aparecer como referente para b, con los datos públicos que guarda el pool, porque leer perfiles públicos de otras marcas es parte del producto (escucha y competencia). Lo que b no obtiene es lo que ve a como dueño: el perfil leído como **su** cuenta, la caché de su tenant, el historial de crecimiento (`growth_provider`) y el kit construido sobre él. Si se quiere cerrar también este camino, es la decisión D3.

## 4. Decisiones abiertas

### D1 — ¿Puede un borrador sin registrar retener una cuenta?

Hoy sí, sin límite de tiempo. Riesgo: alguien que nunca se registra (o que escribe a propósito el usuario de otra marca) bloquea al dueño real.

- **A. Dejarlo así.** Es simple y el dueño real puede reclamarlo por soporte.
- **B. Caducidad.** Las reservas de borradores sin registrar (`brand_kit_drafts.claimed_at IS NULL`) dejan de contar tras N días. Requiere un filtro o un barrido periódico.
- **C. Solo bloquea una cuenta registrada.** El borrador lee sin reservar y la reserva se toma al registrarse. Esto deja una ventana: dos borradores pueden leer la misma cuenta, y el segundo que se registre choca con el primero.

Recomendación: **B**, con N = 7 días (la misma ventana que la caché de perfil).

### D2 — ¿Cómo se demuestra que una cuenta es tuya?

Hoy gana quien la reserva primero, sin verificación.

- **A. Primero en llegar + soporte manual.** Es lo de hoy; para liberar una cuenta se borra su fila de `social_account_claims`.
- **B. Verificar por OAuth con Meta** (`qualify_api.connections`, ya construido). Quien conecta la cuenta de verdad gana y desplaza una reserva no verificada. TikTok no tiene un camino equivalente hoy.
- **C. Verificar con un código en la bio** (pegar un código temporal y volver a leer el perfil). Funciona en las dos redes, pero cuesta una lectura extra de Scrape Creators.

Recomendación: **A** ahora y **B** cuando el flujo de conexión con Meta llegue al Brand Kit.

### D3 — ¿La cuenta propia de una marca registrada puede aparecer como referente de otra?

Hoy sí (§3).

- **A. Sí.** Son datos públicos y es el núcleo de la escucha social y del análisis de competencia.
- **B. No.** Se excluyen de los resultados de referentes las cuentas reservadas por otros tenants. Cuesta poco (la reserva ya existe), pero quita valor al producto, porque la competencia de un cliente suele ser otro cliente.

Recomendación: **A**. Que b no vea los datos de a como dueño ya está cubierto.

### D4 — ¿El mensaje debe ofrecer una salida?

Hoy solo informa. Opciones:
- un enlace a "Entrar" (login);
- un "¿Es tuya? Escríbenos" para las disputas (va con D2);
- cambiar "registrada" por "en uso", que es más exacto mientras D1 siga en A, porque un borrador sin registrar también la retiene.

## 5. En desarrollo

Una cuenta de prueba (p. ej. `midu.dev`) queda reservada por el primer tenant de pruebas que la lee. Para leerla con otro correo:
- se usa el mismo correo (retoma el borrador), o
- se borra la fila:

```sql
DELETE FROM social_account_claims WHERE network = 'instagram' AND handle_key = 'midu.dev';
```

Ese `DELETE` lo hace `qualify_owner` o `qualify_admin` (`qualify_app` solo ve las filas de su tenant).
