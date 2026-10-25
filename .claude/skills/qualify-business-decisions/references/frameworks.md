# Decision frameworks, distilled for Qualify

Only what changes a decision for a two-to-five-person SaaS selling to budget-tight small
businesses in CO/VE/UY. Every item says how to apply it here. Sources (with access dates) in
[sources.md](sources.md); numbers marked `[S]` are third-party benchmarks, never our data.

## Contents

1. Unit economics — the four numbers that matter at our size
2. Value metric — what we charge for
3. Packaging — Good-Better-Best, leaders/fillers/killers, plan limits
4. Willingness to pay — how to ask without inventing demand
5. Build vs buy — with business impact
6. Reversibility — one-way and two-way doors
7. Pre-mortem and the bias check
8. Decision records

## 1. Unit economics — the four numbers that matter at our size

| Number | Formula | How to read it at Qualify |
|---|---|---|
| **Gross margin per plan** | (price − variable cost) / price | Variable cost = generation (pricing table `v7`) + per-business vendors. Compute it **per scenario** (typical / worst / worst with references) — never one blended number. `scripts/unit_economics.py` does it |
| **Contribution per business** | price − variable cost − team time per business | At 1–20 clients the team's hours (Altas, manual payment links D19, support by WhatsApp) can exceed the vendor bill. Put a number on it, even `[H]` |
| **Break-even businesses** | fixed monthly / contribution per business | Fixed today is small (one VPS shared with Pedidos, free tiers). Its job is to show *when* a fixed cost (paid Resend, a second server, a payment provider) changes the picture |
| **LTV and CAC payback** | LTV = contribution / monthly churn · payback = CAC / contribution | Benchmarks `[S]`: LTV/CAC > 3, CAC recovered in < 12 months (best 5–7). **We have neither churn nor CAC yet** — write «sin datos» and the date they can exist, never a borrowed industry churn |

Rules of thumb:

- **Cost is the floor, value is the ceiling, competitors are the reference.** Pricing from cost
  alone leaves money on the table (Ramanujam's *minivation*); pricing from competitors alone
  copies their cost structure, not ours.
- **AI products run lower gross margins than classic SaaS** `[S]` (a16z 2020: often 50–60 % vs
  60–80 %+). A plan with a 75 % typical margin and a 30 % worst case is normal for an AI product;
  a *negative* worst case is a design problem (cap, quota or price), not bad luck.
- **Typical prices the plan; worst case sizes the guardrails** (alert caps, quotas). Mixing them
  is the most common error in our own docs' history.
- **Precision follows evidence.** Report margins as whole percentages; a decimal over an `[H]`
  input is precision theater.

## 2. Value metric — what we charge for

The value metric is the unit the price scales with. Criteria (Patrick Campbell, ProfitWell `[S]`):

1. It tracks the value the owner perceives (finished publications, answered conversations), and
   the owner can predict it.
2. Both sides trust the count — we show it in the app («creaciones del mes»), the owner never sees
   money (D1).
3. It grows with the customer: a bigger business uses more and pays more; a small one pays less
   and churns less.
4. **It does not punish adoption.** A metric that charges for the thing we want them to do more of
   (connect a second business, invite a helper) slows the wedge.
5. **For us, also:** it follows our cost driver closely enough that heavy use cannot sink the
   margin (generation, especially video, is the cost driver; tenants and logins are nearly free).

Worked example — «¿cuántos negocios por suscripción?»: our cost scales with generation and
connected accounts, not with tenants (`modelo-negocio-operador-multi-emprendimiento.md` §4); the
multi-business owner is the wedge (`epica-multi-negocio-una-sesion.md`). So a per-business price
fails criterion 4, and «unlimited businesses on one quota» fails criterion 5 only if the quota is
per login rather than per business. The options table must show both readings with numbers.

## 3. Packaging — Good-Better-Best, leaders/fillers/killers, plan limits

- **Good-Better-Best** (Monetizing Innovation `[S]`): three tiers give three points on the demand
  curve. Health check once there is data: < 30 % on Good, > 70 % on Better or Best, > 10 % on
  Best. More than 50 % on the entry tier → Good is too generous: move something up.
- **Leaders, fillers, killers:** build each tier around its *leaders* (what makes them buy);
  *fillers* are nice-to-have; a *killer* — few value it, many reject it, or it confuses — comes
  out of the bundle. For Qualify, map features before deciding a plan's content: e.g. assisted
  replies and approval from the phone are candidate leaders; voice cloning may be a filler; any
  limit the owner cannot understand in one sentence is a killer.
- **Plan limits go on what drives cost or scales with value — never on what drives activation.**
  Limiting video (expensive) is right; limiting connected accounts below what the owner already
  has, or the number of approvals, blocks the habit we sell.
- **Few, doubling steps** (D15: Plus = 2× Básico, Pro = 4×) keep margins proportional and the
  explanation short. Extras sold as named plans/packs, not loose units (D14).
- **Four monetization failures** to name when they appear: *feature shock* (too much in, priced
  too high), *minivation* (right product, priced too low), *hidden gem* (valuable, never sold),
  *undead* (nobody asked for it, shipped anyway).

## 4. Willingness to pay — how to ask without inventing demand

- Ask early, before building: **problem → solution → value → price**, never price first.
- Questions already adopted by the house: the five-question ladder of
  `precios-planes-qualify.md` §6 (Van Westendorp-style thresholds + «what do you pay today, in
  money and hours»). Add the Ramanujam probe: «del 1 al 5, ¿qué tan probable es que lo compre a
  X?» and lower the price after any answer ≤ 3; ask «¿por qué?» after every answer.
- **Segment by willingness to pay, not by industry.** Look at the spread, not the average — two
  groups (the owner who pays a community manager vs the one who does it alone) hide in a mean.
- **Five conversations are not statistics**; they tell whether the range sits near 29, 49 or 79.
  Founder-operated businesses (Bianki, Polette) are *not* buyers for this purpose: their answers
  are `[F]` context, not `[V]` demand.
- Discounts: larger discounts correlate with higher churn `[S]` (Campbell: keep ≤ 20 %). Our
  first month at 50 % is a deliberate learning investment — the decision record must name the
  renewal rate that would justify it, and measure it.
- Local realities that change the answer: USD-only billing is a barrier in VE/CO; IVA (19 % CO,
  22 % UY) may sit on top of the shown price; FX differences are absorbed by us when we price in
  USD and collect in COP/UYU/Bs.

## 5. Build vs buy — with business impact

House rule: **buy commodity, build the differentiated core** (ADR 32/34; `qualify-context` §3).
Apply it with these questions, in order:

1. **Is it core?** Does it make the owner choose Qualify (angle engine, assisted replies, intent,
   approval flow) or is it plumbing any vendor sells (generation, sending, scraping, payments)?
   Wardley's evolution axis is the lens: commodity → buy, genesis/custom that differentiates →
   build.
2. **Total cost of ownership over 12 months**, not the sticker: build = engineering days × the
   cost of what does *not* get built (the opportunity cost is the real price for a tiny team) +
   maintenance; buy = price per unit × projected volume + integration + the cost of switching away.
3. **Data terms and lock-in:** does the vendor keep or train on client data (BytePlus authorized
   presets do — client data never goes there)? Can we keep the raw payload so we can leave
   (ADR 34)? Is there a second supplier?
4. **New runtime, datastore or vendor?** Needs an options table and the founder's decision
   (CLAUDE.md hard rules). Check the simplest thing already at hand first — the founder
   consistently picked it (Docker on the existing VPS over Lambda; one process over a new service).
5. **Business impact column:** what changes for the owner (speed, price, reliability), for our
   margin per plan, and for the clock (App Review, Meta lanes).

## 6. Reversibility — one-way and two-way doors

Bezos (2015 letter `[V]`): Type 1 decisions are «consequential and irreversible or nearly
irreversible – one-way doors» and need deliberation; most are Type 2, «two-way doors», and
«can and should be made quickly by high judgment individuals or small groups». The failure mode
is using the slow process for everything.

Qualify's doors, as a starting map (check each case):

| Usually two-way (decide fast, measure, adjust) | Usually one-way (slow down, pre-mortem, founder signs) |
|---|---|
| Quotas and weights in versioned files (`planes-v1.json`, `pesos-creaciones-v2`) | A price already announced to paying clients (lowering is easy, raising costs trust; decide grandfathering up front) |
| Alert caps that only notify (D18) | Anything that ships client data to a vendor that keeps it |
| Internal cost tables, measurement cadence | Identity/schema changes once real users exist (the 1 login = 1 tenant reversal cost a migration) |
| Which plan a new client starts on | Annual prepay, contracts, a public free tier (removing a free plan is a one-way door in reputation) |
| Manual payment links (D19) | Meta lane choices (Tech Provider vs own-or-manage), App Review submissions |

A one-way door can often be converted into a two-way one: pilot with one client, time-box the
offer («precio de lanzamiento hasta…»), keep the old path behind a flag. Offer that conversion as
an option.

## 7. Pre-mortem and the bias check

**Pre-mortem** (Gary Klein, HBR 2007 `[S]`): «It is 2027-04-30 and this decision failed. Why?»
List 3–5 concrete reasons; for each, the early signal we would see and the mitigation or kill
criterion. Prospective hindsight raises the number of failure reasons people identify (~30 % in
Mitchell, Russo & Pennington 1989). Required for one-way doors; optional for two-way.

**Bias check** — a subset of Kahneman, Lovallo & Sibony's 12-question checklist (HBR 2011 `[S]`)
that bites here:

- **Saliency / small sample:** are we generalizing from the founder's own businesses?
- **Anchoring:** is the number anchored on a competitor's price, or on our first guess?
- **Sunk cost:** are we keeping something because we already built it?
- **Overconfidence / planning fallacy:** is the «typical month» an estimate dressed as a measure?
- **Disaster neglect:** what does the worst case cost, and is there a cap?
- **Confirmation:** did anyone argue the other option? (Ask the market analyst for the
  anti-flattery finding.)

## 8. Decision records

Nygard's ADR shape (2011 `[S]`) — context (forces in tension), decision («Decidimos…»), status
(`[PROPUESTO]` → `[FIRMADO]` → `[REEMPLAZADO por …]`), consequences *including the negative ones* —
is what our docs already use. For business decisions, keep it in the topic doc as numbered
entries (`D1…Dn`, like `modelo-cobro-generacion.md` §3) with a «Decisión del fundador (fecha)»
section on top that rules over the analysis below it, the rejected options kept, and «qué la
reabriría». Architectural consequences go to an ADR through `principal-architect`.
