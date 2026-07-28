# Research parking lot

Running log of research findings (papers, checkpoints, techniques) surfaced during
Fase 1-3 model work that are interesting but don't map to a currently-scoped roadmap
phase or a decision this package owns today. Per the project convention established
in `docs/backlog-features-gtm.md` ("Parking lot — Fase N" sections) and
`docs/backlog-crm-workflows.md` §5.4: record the finding plus its phase dependency
instead of silently dropping it or force-fitting it into current scope. Entries here
are datasci-owned (`packages/models`), dated, and each carries an explicit verdict —
parked, or (rarely) promoted into a backlog item owned by product-owner/architect.

Do not treat an entry's presence here as a commitment. Nothing in this file is wired
into the cascade, the `Provider` protocol, or the golden-set evaluation
(`docs/arquitectura.md` §7) until a separate ADR/backlog item says so.

---

## 2026-07-26 — Dynamic-budget superpixel active learning for semantic segmentation

**Citation:** Yuemin Wang and Ian Stavness (Department of Computer Science, University
of Saskatchewan), "Dynamic-budget superpixel active learning for semantic
segmentation," *Frontiers in Artificial Intelligence*, vol. 7, article 1498956.
Received 2024-09-19, accepted 2024-12-16, published 2025-01-09.
DOI: [10.3389/frai.2024.1498956](https://doi.org/10.3389/frai.2024.1498956).
Also available via PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC11754207/.
Code: https://github.com/yuw422/dynamic-budget-superpixel-active-learning.
Accessed 2026-07-26.

**Not an arXiv paper.** The task that produced this entry asked for an arXiv
ID/URL. I searched both the Hugging Face Hub papers index
(`hf_fs search hf://papers "Dynamic Budget Superpixel Active Learning for Semantic
Segmentation"`) and the web for this exact title. The title matches exactly (modulo
capitalization/hyphenation: "Dynamic-budget superpixel active learning..."), but the
paper was published directly in *Frontiers in Artificial Intelligence* — a
peer-reviewed journal, not an arXiv preprint — and I could not find any arXiv listing
for it under this title or these authors. The Frontiers article page itself does not
link an arXiv preprint. Reporting the DOI/PMC links above instead of fabricating an
arXiv ID.

### Method summary (from the published article, `doi:10.3389/frai.2024.1498956`)

- **Dynamic budget vs. fixed budget.** Standard regional active learning for semantic
  segmentation labels a *fixed percentage* of superpixels in every selected image each
  round ("static budget"), regardless of how much genuinely high-uncertainty content
  that image contains. This paper's dynamic-budget strategy instead clusters
  superpixels within each candidate image by uncertainty (Jenks natural breaks) and
  queries only the high-uncertainty cluster, so the number of labeled superpixels
  varies image-to-image — avoiding both over-labeling of already-easy images and
  under-labeling of hard ones. (DOI page, "Abstract" / "Dynamic vs. Static Budget"
  section.)
- **Superpixels as the query unit.** The pipeline first ranks whole candidate images
  by an uncertainty acquisition function (BALD, via MC-Dropout with T=5 forward
  passes), takes the top *b* images (e.g., 50 in the low-budget setting), and only
  then ranks superpixels *within* those images for the actual per-region label query
  — cheaper than ranking every superpixel in the full unlabeled pool (claimed
  complexity reduction from O(nm log nm) to O(n log n + bm log m)) and more
  label-efficient than per-pixel or whole-image queries because superpixels track
  object contours and reduce cross-class label mixing. (DOI page, "Superpixel-Based
  Querying" section.)
- **Datasets and reported gains.** Evaluated on Nassar 2020 (UAV wheat-field
  weed/crop/background segmentation, 3 classes, heavily background-dominated) and
  Cityscapes (19 classes, downsampled to 1024x512). In the low-budget regime, dynamic
  budgeting beat static budgeting by **+5.6% mIoU at 200 labeled images** on Nassar
  (+3.6% at 150 images) and **+2.4% mIoU at 100-150 labeled images** on Cityscapes;
  gains concentrate on minority/hard classes (e.g., +14% IoU on the weed class,
  +6.9% IoU on the Cityscapes fence class). In the high-budget regime the advantage
  shrinks to <1% and is not noticeable on Cityscapes at all. Models: UNet (Nassar),
  DeepLabv3+/Xception (Cityscapes). (DOI page, "Results" section, per-dataset
  subsections.)

### Relevance assessment for Qualify

This is a **training-efficiency technique for a supervised semantic segmentation
model** — it reduces annotation cost when *training* a segmenter from scratch via
active learning rounds. Checked against the two docs that would need to be the entry
point for this to matter:

- `docs/modelos-multimodal-fase1.md`: the current vision stage is zero-shot
  classification (`google/siglip2-base-patch16-224`) plus free-text VLM captioning
  (`Qwen/Qwen3-VL-4B-Instruct` de facto, `moondream3-preview` unvalidated/BSL). Neither
  is a trained pixel-level segmenter, and nothing in that doc proposes training one.
- `docs/arquitectura.md` §7: the golden-set evaluation methodology validates
  *pretrained* zero-shot/VLM checkpoints against labeled fixtures (filter
  precision/recall, ASR WER, VLM description quality, sentiment accuracy) — it is an
  evaluation harness, not a model-training loop, and has no active-learning
  annotation-budget component.

**Verdict on today's roadmap:** this paper does not inform any decision on the
roadmap phase map as scoped today. Qualify does not train, and has no scoped plan to
train, any segmentation model in Fase 1-3. It is "interesting" without a current phase
or decision it informs, which per project convention means it gets parked here rather
than pursued or force-fit into the golden-set eval work.

**Where it could become relevant later (explicitly speculative, not planned):** Fase
3's backlog mentions "logo/product detection" and "visual clustering" as future work,
with the model approach for logo/product detection still undecided between (a)
zero-shot VLM prompting over the existing cascade, or (b) a purpose-trained
detector/segmenter. Only under path (b) — and only if that segmenter's training set
must be hand-annotated at meaningful volume — would a superpixel-based dynamic-budget
active-learning loop like this one be a candidate for cutting the annotation bill. No
such decision exists yet; `docs/backlog-features-gtm.md`'s Fase 3 parking lot does not
currently commit to a trained segmenter for this feature, and this note does not
attempt to make that call.

**Parked — no current phase owner; revisit only if Fase 3 logo/product detection is
scoped as a trained segmenter instead of zero-shot VLM prompting.**
