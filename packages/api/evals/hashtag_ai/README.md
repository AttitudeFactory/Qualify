# Hashtag AI eval — Haiku 4.5 vs Sonnet 5

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

## Result — 2026-09-25 (`results/20260925-113341.json`)

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
