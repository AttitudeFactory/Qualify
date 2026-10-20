# Hashtag AI eval — Haiku 4.5 vs Sonnet 5

Both calls are TOOL runs since 2026-09-25: the selection is an agent loop over two
catalog tools (`buscar_hashtags`, `hashtags_del_nicho`) that ends with `elegir_hashtags`;
the classification answers through the `clasificar_hashtags` tool. The eval gives the
model only each case's 8 most used candidates to start with and serves the rest
through the tools (`CaseCatalog`), so finding the specific tags is part of the test.

Measures the two Claude calls in `qualify_api.hashtags.ai` against hand-labelled gold
sets, and is what the model defaults in that module are chosen from. It spends real
money (cents per run), so it is run by hand, never in CI:

```bash
uv run --no-sync --with anthropic python packages/api/evals/hashtag_ai/run_eval.py --env-file .env --repeats 2
```

- `select_cases.json` — 15 brands across unrelated rubros (fine dining, food truck,
  smash burgers, vegan bakery, specialty coffee, CrossFit, yoga, dog grooming, barber,
  real estate, coding school, women's boutique, phone shop, wood-fired pizza, and a
  motorcycle shop with NO valid candidate). Each candidate is labelled `y` / `m` / `n` /
  `t` — `t` is a **trap**: same general topic, different business (`#streetfood` for a
  fine-dining restaurant, `#peluqueria` for a dog groomer, `#arriendo` for a sales
  agency). The prompt has no per-rubro rule or example; the spread of rubros is what
  checks that the principles generalise.
- `classify_cases.json` — 95 real tags from the local catalog (plus leaked test
  fixtures), with every answer a careful human would accept.

The labels are the spec. Review them; a wrong label is a wrong measurement.

## Langfuse experiment, 2026-10-13 (`results/langfuse-20261013-184511.json`) — CURRENT

Same gold sets and scorers, run as Langfuse dataset runs (`run_experiment.py`, `just
eval-hashtags`; datasets `hashtags-clasificar` and `hashtags-elegir`, environment `eval`)
with the two Claude 5.5 models as new candidates. **One run, no repeat yet**: the plan's
rule (docs/plan-observabilidad-langfuse.md §6.3) asks for a second run before a default
changes, and the selection set is 15 brands, under the rule's 30.

Classification, 95 tags in batches of 20:

| config | kind | kind+niche | total $ |
|---|---|---|---|
| `claude-haiku-4-5` (default) | 0.968 | 0.968 | 0.0220 |
| `claude-haiku-5-5` @ low | 0.968 | 0.968 | **0.0033** |

Selection, 15 brands, at most 3 picks:

| config | precision | recall@3 | traps | bad | $/brand | p50 s |
|---|---|---|---|---|---|---|
| `claude-sonnet-5` @ medium (default) | 0.917 | 0.869 | 1 | 0 | 0.00987 | 8.37 |
| `claude-sonnet-5-5` @ medium | **0.976** | **0.905** | **0** | 0 | 0.00722 | **5.71** |
| `claude-haiku-5-5` @ medium | 0.917 | 0.798 | 0 | 0 | **0.00063** | 7.15 |

Reading: Haiku 5.5 classifies exactly as well as Haiku 4.5 at about a seventh of the
cost; Sonnet 5.5 beats Sonnet 5 on every column, traps included, and is cheaper and
faster. Both are candidates to become the defaults once a second run confirms them.

## Result — tools, 2026-09-25 (`results/20260925-120905.json`)

Selection: 15 cases × 2 repeats, at most 3 picks, 8 starting candidates, the rest via
tools.

| config | precision | recall@3 | traps taken | bad picks | abstains (motos) | stability | $/run | p50 s |
|---|---|---|---|---|---|---|---|---|
| `claude-haiku-4-5` | 0.885 | 0.690 | 0 | 0 | 2/2 | 0.407 | 0.0100 | 13.6 |
| `claude-sonnet-5` @ medium | **0.923** | **0.881** | 1 | 1 | 2/2 | **0.700** | **0.0094** | **9.4** |

With tools the gap widens: Haiku searched less well (recall 0.69, unstable) and, taking
more turns, cost as much as Sonnet. Sonnet searched like an analyst (for the fine-dining
case: "menu degustacion", "fine dining", "alta cocina", "maridaje", "gourmet"). Its
misses: `#peluqueria` for the dog groomer once in two runs, and `#perrocaliente` for a
brand that uses `#perroscalientes` — the second is now dropped in code (`_same_word` is
plural-blind mid-tag). **Default stays Sonnet 5 at medium effort.**

Classification (through the tool): Haiku 0.968 kind+niche vs Sonnet medium 0.926, at a
third of the cost ($0.019 vs $0.064 for 95 tags). **Default stays Haiku 4.5.**

Live on the real local catalog (read-only), the tool run found `#iphone` and
`#smartphone` for a phone shop — tags the fixed-list version never saw — at 2–4 turns,
8–14 s and $0.010–0.024 per brand.

## Earlier result — single call over a fixed list (`results/20260925-113341.json`)

Selection: 15 cases × 2 repeats, at most 3 picks each.

| config | precision | recall@3 | traps taken | bad picks | abstains (motos) | stability | $/call | p50 s |
|---|---|---|---|---|---|---|---|---|
| `claude-haiku-4-5` | 0.906 | 0.869 | **2** | 1 | 1/2 | 0.733 | 0.0018 | 3.2 |
| `claude-sonnet-5` @ low | 0.917 | 0.881 | 0 | 2 | 2/2 | 0.967 | 0.0023 | 3.3 |
| `claude-sonnet-5` @ medium | **0.952** | **0.929** | **0** | **0** | 2/2 | 0.967 | 0.0026 | 3.2 |

Haiku's two traps are the exact failure the feature exists to prevent — both runs gave
`#comidacallejera` to the smash-burger restaurant — and it once picked `#carro` for the
motorcycle shop. Sonnet low picked `#vegana` (a spelling of the brand's own `#vegano`)
twice. **Default: Sonnet 5 at medium effort** — about $0.0008 more per search.

Classification: 95 tags, batches of 40.

| config | kind | niche (topics) | kind+niche | country (places) | total $ | seconds |
|---|---|---|---|---|---|---|
| `claude-haiku-4-5` | 0.979 | 1.0 | 0.979 | 10/10 | 0.014 | 16 |
| `claude-sonnet-5` @ low | 0.936 | 1.0 | 0.936 | 9/9 | 0.041 | 34 |
| `claude-sonnet-5` @ medium | 0.989 | 1.0 | 0.989 | 9/9 | 0.053 | 42 |

Haiku's two misses (`techtok`, `techvideos` → generic) are mild; Sonnet low classified
four junk fixtures as real topics. **Default: Haiku 4.5** — a quarter of the cost of
Sonnet medium for one point less.

Caveat: 15 brands and 95 tags are a small set. The selection gap (2 traps vs 0 in 30
runs) is directional, not a statistical proof; re-run after changing either prompt, and
grow the cases when a real brand gets a wrong pick.
