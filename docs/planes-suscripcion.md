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
```

## Lo que falta (depende de otras historias)

- **Saldo común entre los negocios de una suscripción** (ADR 43 F2, §2.9): hoy cada negocio tiene el cupo completo de su plan. Con una suscripción por negocio (todos los de hoy) da lo mismo. Lo construye S10 (m-24854773): `subscription_pool_*`, `pool_reserve` / `pool_release` / `pool_balance`, rol `qualify_pool`, revisión de `security-review`. Ahí `business_plans` puede quedar como está o pasar a leerse por `pool_balance()`.
- **Paquetes de 90 días** (m-24852129): de la suscripción y gastados después del plan (D17). El informe ya los cobra a precio completo en cuanto existan sus compras.
- **Fijar el plan desde el Alta de Meegle** (m-24852131) y el control de negocios incluidos / techo (S7).
- `tenants.subscription_id NOT NULL` y la suscripción creada en el Alta (S10 / S7).
- «Pedir otra versión» de un final = 1 vista previa + 1 video (comentario del 2026-10-24): llega con los finales de noche (m-24852169).
