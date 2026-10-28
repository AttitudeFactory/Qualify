# Sources

Accessed 2026-10-25 unless stated. Tier: `[V]` primary text read; `[S]` secondary summary of a
primary work (book, paper) that was not read in full — cite it as a framework, not as data.

## Writing the skill (Anthropic)

- `[V]` Anthropic, *Skill authoring best practices* —
  https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — description
  in third person with what + when (≤ 1,024 chars), body under 500 lines, references one level
  deep, table of contents in references over 100 lines, scripts for deterministic work ("solve,
  don't defer", no voodoo constants), checklists for multi-step workflows, templates for output,
  feedback loops, evaluation before extensive docs, test with the models that will run it.
- `[V]` Anthropic Engineering, *Equipping agents for the real world with Agent Skills* —
  https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills —
  the three levels of progressive disclosure (metadata → SKILL.md → bundled files) and why
  scripts are token-efficient and repeatable.
- House protocol: `.agents/skills/compass-skill-synthesis/SKILL.md`.

## Unit economics

- `[V]` David Skok, *SaaS Metrics 2.0* — https://www.forentrepreneurs.com/saas-metrics-2/ — LTV/CAC
  above 3 («sometimes as high as 7 or 8»), profitability «anemic» if CAC recovery takes over 12
  months, best businesses 5–7; net revenue churn above 2 %/month is a warning; early on, churn
  matters less than later.
- `[S]` Martin Casado & Matt Bornstein (a16z), *The New Business of AI (and How It's Different
  From Traditional Software)*, 2020-02-16 —
  https://a16z.com/the-new-business-of-ai-and-how-its-different-from-traditional-software/ —
  anecdotal 50–60 % gross margins for AI companies vs 60–80 %+ for SaaS; predates current LLMs.

## Pricing and packaging

- `[S]` Madhavan Ramanujam & Georg Tacke, *Monetizing Innovation* (Wiley, 2016). Read through:
  Yevgeniy Brikman's notes — https://www.ybrikman.com/blog/2023/04/01/monetizing-innovation/ — and
  Simon-Kucher on the four failures — https://alumni.simon-kucher.com/news/99051 — design the
  product around the price; WTP conversation early (problem → solution → value → price);
  segment by WTP; leaders/fillers/killers; Good-Better-Best distribution targets; feature shock,
  minivation, hidden gem, undead.
- `[S]` Patrick Campbell (ProfitWell), in Lenny's Newsletter, *SaaS pricing strategy* —
  https://www.lennysnewsletter.com/p/saas-pricing-strategy — value metric criteria, packaging
  after segments and value metric, discounts ≤ 20 % (bigger ones correlate with churn), revisit
  monetization every quarter.
- `[S]` ProfitWell Report, value-metric benchmarks —
  https://paddle.com/studios/shows/profitwell-report/value-metric-benchmarks (2018).
- Generic methodology already installed: `.agents/skills/pricing/` (Van Westendorp, tiers).

## Decisions under uncertainty

- `[V]` Jeff Bezos, 2015 Letter to Shareholders (Amazon, filed with the SEC 2016) —
  https://www.sec.gov/Archives/edgar/data/1018724/000119312516530910/d168744dex991.htm — Type 1
  (one-way door) vs Type 2 (two-way door) decisions.
- `[S]` Gary Klein, *Performing a Project Premortem*, Harvard Business Review 85(9), 2007 — via
  https://archive.phf.org/resourcestools/Documents/Pre_Mortem_Analysis.pdf; the ~30 % figure is
  from Mitchell, Russo & Pennington, *Back to the Future: Temporal Perspective in the Explanation
  of Events*, J. Behavioral Decision Making 2(1), 1989 (more failure reasons identified, not
  better project outcomes).
- `[S]` Daniel Kahneman, Dan Lovallo & Olivier Sibony, *Before You Make That Big Decision…*,
  Harvard Business Review 89(6), 2011 — https://store.hbr.org/product/the-big-idea-before-you-make-that-big-decision/R1106B
  — 12-question checklist for bias in a team's recommendation.
- `[S]` Michael Nygard, *Documenting Architecture Decisions*, 2011-11-15 — summarized at
  https://www.martinfowler.com/bliki/ArchitectureDecisionRecord.html — context / decision /
  status / consequences (negative ones included).
- `[S]` Simon Wardley, *Wardley Maps* (evolution axis genesis → custom → product → commodity) —
  https://medium.com/wardleymaps — the lens behind «buy commodity, build the core».

## Qualify's own inputs (read the current version, these are the 2026-10-25 state)

- `docs/modelo-cobro-generacion.md` — unit costs (§5), worst case per business (§6), D1–D27.
- `docs/precios-planes-qualify.md` — competitor prices, WTP by country, the founder's 2026-10-24
  price decision and recomputed margins.
- `docs/modelo-negocio-operador-multi-emprendimiento.md` — operator model, pricing forms (§4).
- `docs/epica-multi-negocio-una-sesion.md` — several businesses in one session (2026-10-23).
- `packages/creative/src/qualify_creative/pricing_data/vN.json` — vendor price table. Docs cite
  `v7`, but on `main` (2026-10-25) the newest file on disk is `v5.json`: `v6`/`v7` live in open
  PRs. Always check which version the disk has before quoting a cost as `[V]`.
