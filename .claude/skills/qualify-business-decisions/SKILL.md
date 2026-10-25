---
name: qualify-business-decisions
description: Prepares Qualify decisions that sit between business and engineering for the founder to sign — pricing and packaging (what each plan includes, plan limits such as how many businesses per subscription, quotas, packs, discounts), unit economics (cost per creation, video or business per month, gross and contribution margin, break-even, CAC/LTV), build-vs-buy and vendor choices judged by business impact, and any trade-off that needs the founder's call. Fixed procedure — frame, evidence tiers [V]/[S]/[H], cost per unit from the real cost model and a bundled calculator, options table, one-way vs two-way door, pre-mortem, recommendation, founder decides, record in docs/ and Meegle. Use for «¿cuántos negocios por suscripción?», «¿cobramos por pieza o por plan?», «¿vale la pena construir X o comprarlo?», «¿qué incluye el plan Plus?», «¿nos sale rentable?». Not for measuring a model (qualify-measure), writing stories (qualify-backlog) or a purely technical ADR (principal-architect).
---

# Qualify — decisions between business and engineering

The founder (Herwin) decides; this skill prepares the decision so he can sign it in one reading.
His standing rules: **the idea before the technical** (what the owner gets and what we optimize,
before how to build it), and **an options table with a recommendation, then he picks** — nothing
is built before the pick. Signed decisions are constraints (`qualify-context` §3); reopening one
is allowed only out loud, naming it.

**Is this the right skill?** Price, plan content, limits, quotas, packs, discounts, margin, cost per
unit, build-vs-buy *with a business impact*, «¿nos conviene…?» → yes. Model quality or a prompt
change → `qualify-measure` (this skill consumes its unit costs). Stories and tickets after the
decision → `qualify-backlog`. Module boundaries, schema, a technical ADR → `principal-architect`.
Generic pricing methods (Van Westendorp surveys, tier design theory) → the `pricing` skill.

## Procedure

Copy this checklist into the work and tick it:

```
- [ ] 1 Frame the decision (business first)
- [ ] 2 Read what is already decided and measured
- [ ] 3 Evidence inventory with tiers; delegate the gaps
- [ ] 4 Cost per unit and margin (run the calculator)
- [ ] 5 Value metric and packaging check (pricing/plan decisions)
- [ ] 6 Options table (2–4 options, one is «keep what we have»)
- [ ] 7 Door type; pre-mortem if one-way
- [ ] 8 Recommendation with reopen criteria and a review date
- [ ] 9 Founder decides — present, wait
- [ ] 10 Record it (doc + Meegle + hand-off)
```

**1. Frame.** One question in the founder's words, the trigger (who asked, which client, which
deadline), and **what we optimize this time — pick one first**: learn the real price/cost,
adoption (more businesses using it), margin, or cash this month. Most fights about options are
undeclared fights about this. State what the owner (a small-business owner on a phone, short on
time and budget — `qualify-ux`) gets or loses, before any technical consideration.

**2. Read what exists.** `docs/modelo-cobro-generacion.md` (D1–D27, unit costs §5, worst case
§6), `docs/precios-planes-qualify.md` (competition, WTP, the 2026-10-24 price decision),
`docs/modelo-negocio-operador-multi-emprendimiento.md` §4, `docs/epica-multi-negocio-una-sesion.md`,
the ADR log (`docs/arquitectura.md` §6), and the disk: the newest
`packages/creative/src/qualify_creative/pricing_data/vN.json` and `creations_data/`. A doc that
cites a version the disk does not have is describing an open PR — say so. Search Meegle for an
open ticket on the topic before creating one.

**3. Evidence inventory.** Every number and claim gets a tier, and a computed number inherits the
**weakest** tier of its inputs:

| Tier | What counts | Equivalents in house docs |
|---|---|---|
| `[V]` | Code or data on disk, a production read, an invoice or vendor task id, an official price page with URL and access date, a fact a real client said (founder-reported, with who and when) | `[P]` (market-analyst), «medido»; «calculado» from `[V]` prices is `[V]` but **say «calculado»** |
| `[S]` | Third-party comparisons, benchmarks, blogs, books | `[S]` |
| `[H]` | Estimates, analogies, our arithmetic over guesses, the founder's own businesses used as «the market» | `[H]`, «hipótesis»; a founder *estimate* is `[H]`; a founder *decision* is a constraint, not evidence (`[F]`) |

For each gap: the cheapest experiment that would close it and who runs it. Delegate evidence, in
parallel when independent (briefs per `qualify-lead` §2):

| Gap | Delegate to |
|---|---|
| Competitor prices, vendor offers, what substitutes cost (CM, agency) | `market-analyst`, mode **OFERTA** |
| Objections, what a buyer would demand to pay X | `market-analyst`, mode **DEMANDA** (output is `[H]` by construction) |
| Measured cost per unit, worst case, re-measurement | `data-scientist-fde` (`qualify-measure`) |
| Cost and risk of building, what the schema/Meta lanes impose, vendor data terms | `principal-architect` |
| How the owner will read a limit, a plan name or a «se acabó tu cupo» | `ux-designer` |

**4. Cost per unit.** Name the unit of the decision (per creation, video, preview, business,
connected account, message) and split cost into: **variable** (vendor per call, from the pricing
table), **per business** (voice slot, storage, scraping at the Alta, emails, *team time*), and
**fixed** (VPS shared with Pedidos, paid tiers). Typical prices the plan; worst case sizes caps
and quotas — never blend them. Run the calculator on a copy of the parameters file:

```bash
cp .claude/skills/qualify-business-decisions/references/params-planes-2026-10-24.json /tmp/params.json  # edit the copy
uv run --no-sync python .claude/skills/qualify-business-decisions/scripts/unit_economics.py /tmp/params.json \
    [--price Básico=59] [--tenants 25] [--target-margin 0.3] [--json]
```

It prints a Spanish Markdown table (margin per plan × scenario, first month, contribution,
minimum price for a target margin, break-even, alert cap vs cost, LTV/CAC when churn and CAC
exist) and lists every `[H]` input the result rests on. Every input must carry `amount`, `tier`
and `source`; it refuses bare numbers. Paste its output, do not retype numbers.

**5. Value metric and packaging** (price, plan or limit decisions). Check the candidate charging
unit against the criteria in [references/frameworks.md](references/frameworks.md) §2 (tracks
value, trusted count, grows with the customer, **does not punish adoption**, follows our cost
driver), and the bundle against §3 (leaders/fillers/killers; limits go on what drives cost, never
on what drives activation; few doubling tiers). The owner sees units, never money (D1).

**6. Options table.** 2–4 options. Always include **keep what we have** and **the simplest thing
already at hand**; a new vendor, runtime or datastore needs this table by house rule. Columns in
the template below. Build-vs-buy questions and total cost of ownership: frameworks §5.

**7. Door type.** Classify each option: two-way (versioned quota files, alert caps, manual
processes — decide fast, measure, adjust) or one-way (a price announced to paying clients, client
data to a vendor that keeps it, identity/schema with real users, a public free tier, Meta lanes).
Map in frameworks §6. Offer a way to turn a one-way door into a two-way one (pilot with one
client, time-boxed launch price, flag). One-way → run the **pre-mortem** and the bias check
(frameworks §7) and put the top reasons in the output.

**8. Recommendation.** One option, the reason in one sentence tied to the goal of step 1, what
it costs to be wrong, **what would make us reopen it** (a number and a date: «si la renovación del
segundo mes baja de 60 % con 10 negocios»), and the cheapest validation.

**9. Founder decides.** Present the template; ask; wait. Do not implement, file stories or change
code before the pick. If he picks against the recommendation, that is his call: record it, keep
the analysis, and carry the risk forward honestly (as `precios-planes-qualify.md` did on
2026-10-24).

**10. Record.** In the topic doc (Spanish): a «Decisión del fundador (AAAA-MM-DD)» section on top
that rules over the analysis, numbered entries (`Dn`) with why, cost, rejected options and what
reopens it, status `[PROPUESTO]` → `[FIRMADO]`. A comment on the Meegle ticket (`meegle-ticket` to
create one). Architectural consequences → ADR via `principal-architect`. A changed business model
→ update `qualify-context`. Stories → `product-owner` / `qualify-backlog`. Set the re-measure
trigger (as `modelo-cobro-generacion.md` §8). Ship per `qualify-pr`.

## Output for the founder (Spanish, plain, no anglicisms)

```markdown
## Decisión: <la pregunta, en sus palabras>

**Qué buscamos esta vez:** <aprender | más negocios usándolo | margen | caja> — <por qué>.
**Para el dueño del negocio:** <qué gana o pierde, en una frase>.

**Lo que sabemos** — [V] … · [S] … · [H] … (fuente de cada cifra)
**Lo que no sabemos** — <hueco> → <experimento más barato, quién, cuándo>

| Opción | Qué es | Para el dueño | Costo / margen por negocio | Esfuerzo | ¿Se puede deshacer? | Riesgo principal | Evidencia |
|---|---|---|---|---|---|---|---|
| A. Dejar como está | | | | | | | |
| B. … | | | | | | | |

<tabla de la calculadora si hay precios o márgenes>

**Si sale mal (pre-mortem, solo puertas de una vía):** 1. … (señal temprana · qué hacemos)

**Recomendación:** <opción> — <una frase>. **La reabrimos si** <cifra y fecha>.
**Validación más barata:** <…>.

**Necesito que decidas:** <pregunta cerrada, A/B/C>.
```

## Anti-patterns

- **Technical first.** Opening with schema, vendors or code before the owner's benefit and the goal.
- **One option, or seven.** One is a disguised decision; seven is an abdication. 2–4.
- **Cost-plus or copy-the-competitor pricing.** Cost is the floor, value the ceiling, competitors
  the reference.
- **Blending typical and worst case**, or an average that hides two groups of clients.
- **The founder's businesses as the market.** Bianki and Polette are the founder's; their usage
  is a test bench, not willingness to pay.
- **Borrowed metrics as ours.** No industry churn or CAC in our LTV; «sin datos» plus the date.
- **Precision theater.** Decimals over `[H]` inputs; a WTP «finding» from five conversations.
- **Limits on activation.** Charging per business penalizes the multi-business owner (the wedge);
  hard caps that block units the client already paid (D18's lesson).
- **Silent reopening** of a signed decision, or deciding for the founder.
- **Ignoring the local reality:** USD-only billing (VE/CO), IVA on top (19 % CO, 22 % UY), FX
  absorbed when pricing in USD and collecting in local currency.
- **A new vendor/runtime without the options table and the founder's pick.**

## Bundled files

- [references/frameworks.md](references/frameworks.md) — unit economics, value metric,
  packaging, WTP, build-vs-buy, door types, pre-mortem and bias check, decision records; each
  applied to Qualify.
- [references/sources.md](references/sources.md) — the research behind it, with URLs.
- `references/params-planes-2026-10-24.json` — parameters of the 2026-10-24 plans; copy it for
  a new decision (it is also the calculator test's fixture — do not edit it in place).
- `scripts/unit_economics.py` — the calculator (run it, no need to read it). Tests:
  `uv run --no-sync pytest .claude/skills/qualify-business-decisions/scripts -q`.
