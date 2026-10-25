# Planes Básico / Plus / Pro sobre la suscripción (m-24852145)

**Estado:** construido en la rama `feat/m-24852145-planes` (migración `0093_subscription_plans`).
**Decisiones:** D14–D19 de `docs/modelo-cobro-generacion.md`, precios de `docs/precios-planes-qualify.md`
(opción C), reglas de cobro en los comentarios de m-24852145 (2026-10-24/25) y **ADR 43**
(`docs/adr-43-un-login-varios-negocios.md`, firmado 2026-10-25): el plan es **de la suscripción**,
no de cada negocio.

## Qué hay

| Pieza | Dónde | Qué hace |
|---|---|---|
| Catálogo de planes | `packages/api/src/qualify_api/plans/data/planes-v1.json` | Básico 30/4/20 (aviso USD 120, 2 negocios), Plus 60/8/40 (USD 240, 3), Pro 120/16/80 (USD 480, 5); techo 8 negocios |
| Precios | `…/plans/data/precios-planes-v1.json` | 79 / 149 / 279 al mes; primer mes 39 / 75 / 139; paquetes +2 videos 29, +20 creaciones 12, +10 vistas previas 19. Un cambio de precio es un archivo nuevo (`precios-planes-v2`) |
| `subscriptions` | 0093 | Quien paga. Sin `tenant_id`, aislada por GRANT (RLS forzada sin política, solo `qualify_admin`). Relleno 1:1 con los negocios que ya existen |
| `tenants.subscription_id` | 0093 | Nullable por ahora; el negocio no puede cambiarlo (`qualify_app` solo actualiza nombre, país, zona y moneda) |
| `subscription_plan_assignments` | 0093 | Historial que nunca se edita: plan, plan anterior, desde qué mes, origen, motivo, quién, cuándo, versión de planes y de precios, clave de idempotencia |
| `business_plans` | 0093 | Lo único que lee la app: el plan vigente del negocio y, si hay, la bajada pendiente. RLS por negocio, `qualify_app` solo lectura. Sin fila = Básico |
| `subscription_cost_alerts` | 0093 | Un aviso por suscripción y mes al cruzar el tope en USD. Solo `qualify_admin` |
| Cupo | `qualify_api/creative/creations.py` (`quota_for`) | El saldo del mes sale del plan del negocio, leído en la misma transacción bloqueada del cobro |
| Configuración | `Qualify/settings_page.py` («Tu plan») | «Tu plan: Básico · 30 creaciones, 4 videos y 20 vistas previas al mes» + «Pedir más a Qualify» (pedido de soporte con tema `more_creations`). Sin precios |

## Reglas

- **Subir de plan** vale desde el mes en curso; lo ya usado se descuenta del plan nuevo (usó 20 de 30 → le quedan 40 de 60).
- **Bajar de plan** vale desde el mes siguiente. Una subida posterior anula una bajada pendiente.
- Un solo cambio pendiente a la vez.
- **Cobro (informe del equipo):** primer mes a mitad de precio del plan con el que empezó; subir a mitad de mes cobra la diferencia como línea aparte (normal 149 − 79 = 70; primer mes 149 − 39 = 110); paquetes siempre a precio completo. Cada línea dice qué versión de precios usó. La suscripción empieza a facturarse con el primer `just set-plan`.
- **Tope en USD:** el trabajo diario del `calendar-worker` (o `just plan-cost-alerts`) suma el costo real de proveedor del mes (UTC) de todos los negocios de la suscripción y, al cruzar el tope del plan, avisa una vez en el canal de `QUALIFY_SUPPORT_WEBHOOK_URL`. **Nunca pausa ni bloquea nada.**
- Asignar un plan pone `creative_engine_config.monthly_budget_cap_usd` = tope del plan y `hard_stop_on_cap = false` en los negocios de la suscripción.

## Comandos (solo equipo, `admin_session`)

```bash
just set-plan --tenant <uuid> --plan plus --reason "Pidió más videos" --by herwin@attitudefactory.co
just set-plan --tenant <uuid> --plan basico --from 2026-12 --reason "…" --by …
just plans                      # catálogo vigente (sin precios)
just plans --tenant <uuid>      # historial de la suscripción de ese negocio
just plan-report [--month 2026-10] [--tenant <uuid>]   # costo contra cobro
just plan-cost-alerts [--tenant <uuid>]                # avisos de tope (también corre a diario)
just add-pack --tenant <uuid> --paquete "+2 videos" --reason "Pidió más" --by herwin@attitudefactory.co \
              [--support <id del pedido>] [--usd 29] [--payment-ref "Zelle 1234"]
just packs --tenant <uuid>      # paquetes del negocio: lo que queda, vencimiento, lo pagado
just revoke-pack <id> --reason "…" --by …
```

## Paquetes de 90 días y «Pedir más a Qualify» (m-24852129)

**Estado:** construido en la rama `feat/m-24852129-pedir-mas` (migración `0095_creation_packs`).
Diseño: segunda revisión de arquitectura en los comentarios de m-24852129, con la forma de ADR 43.

| Pieza | Dónde | Qué hace |
|---|---|---|
| Paquetes fijos | `precios-planes-v1` + `PACK_NAMES` en `plans/catalog.py` | «+2 videos» (USD 29), «+20 creaciones» (USD 12), «+10 vistas previas» (USD 19). Se eligen **por nombre**; una cantidad suelta o un nombre que no existe se rechaza sin escribir nada |
| `creation_packs` | 0095 | Un paquete dado: negocio, marca, suscripción, código, versión de precios, unidades (leídas de la tabla), `granted_at`, `expires_at = granted_at + 90 días` (CHECK), origen, motivo, quién, clave de idempotencia, revocación (nunca se borra). RLS por negocio; `qualify_app` solo lectura |
| `creation_allocations` | 0095 | Qué fuente pagó cada unidad de cada cargo (plan o paquete), escrito en la misma transacción bloqueada del cargo y devuelto con él. Los cargos de antes de 0095 se rellenaron como «plan» sin código de plan |
| `creation_payments` | 0095 | Lo que el equipo cobró por un paquete (USD, versión de precios, referencia, quién). RLS por negocio y **ningún permiso para `qualify_app`** |
| Saldo | `qualify_api/plans/packs.py` + `creative/creations.py` | Primero el cupo del mes del plan; después los paquetes vigentes, el que vence antes primero (D17). Lo que queda de un paquete pasa al mes siguiente y deja de contar el día 91 |
| «Pedir más a Qualify» | `qualify_api/plans/ask_more.py`, `Qualify/ask_more_*` | Pedido de soporte `more_creations` con qué se agotó, el plan y el contacto (WhatsApp conectado del negocio o, si no hay, el correo). Uno por mes mientras nadie lo atienda: el botón queda en «Pedido enviado» hasta fin de mes o hasta que llegue un paquete o un cambio de plan |
| Crear | `Qualify/content_generator.py` | Con un contador en 0 para la pieza (videos, vistas previas o creaciones), «Crear» queda desactivado y aparece el aviso con «Pedir más a Qualify». Con videos en 0 una imagen se sigue creando |
| Configuración | `Qualify/settings_page.py` | «Pedir más a Qualify» siempre, junto al plan |

**Reglas y decisiones:**

- **Cambio frente a CREAR-5:** antes, sin videos se podía crear la vista previa de un video y el freno llegaba al aprobar. Este ticket pide lo contrario («Con saldo 0 en videos, el botón de crear video está desactivado»), así que ahora un video sin videos del mes no se crea.
- El saldo con extras se muestra aparte por contador: «Te quedan 5 de 6 videos este mes (2 extra, vencen el 22 de enero).» Con varios paquetes, la suma de lo que queda y la fecha del que vence antes.
- Una unidad devuelta a un paquete ya vencido se pierde (poco frecuente).
- Hasta el saldo común de S10, un paquete lo gasta el negocio y la marca a la que se dio, aunque quede registrado en su suscripción.
- El informe `just plan-report` suma cada paquete al mes en que se dio, por lo cobrado (o por el precio de la tabla si no hay pago).
- El equipo nunca muestra precios dentro de la app: el enlace de pago va por WhatsApp o correo, a mano (D19).

## Lo que falta (depende de otras historias)

- **Saldo común entre los negocios de una suscripción** (ADR 43 F2, §2.9): hoy cada negocio tiene el cupo completo de su plan. Con una suscripción por negocio (todos los de hoy) da lo mismo. Lo construye S10 (m-24854773): `subscription_pool_*`, `pool_reserve` / `pool_release` / `pool_balance`, rol `qualify_pool`, revisión de `security-review`. Ahí `business_plans` puede quedar como está o pasar a leerse por `pool_balance()`.
- **Paquetes en el saldo común** (S10): hoy un paquete lo gasta el negocio al que se dio; con `pool_reserve` pasa a sumar al cupo de la suscripción.
- **Sección del equipo en Configuración** para sumar paquetes: espera el ADR de identidad del equipo (superadmin). Hoy solo por `just add-pack`.
- **Fijar el plan desde el Alta de Meegle** (m-24852131) y el control de negocios incluidos / techo (S7).
- `tenants.subscription_id NOT NULL` y la suscripción creada en el Alta (S10 / S7).
- «Pedir otra versión» de un final = 1 vista previa + 1 video (comentario del 2026-10-24): llega con los finales de noche (m-24852169).
