# ADR — EMIT_DEPTH + RAG metadata + anchor preamble

- **Date planned:** 2026-05-23
- **Status:** Implemented and shipped in v0.1.0 (2026-05-24)
- **Commits:** `a0ecd8d` (I), `1d27d12` (J), `b292f13` (K), `e8d4346` (L), `992717f` (M)

## Context

> Terminology used below (`Strategy 0`, `item_id` format like `sec9-9.69-part3-2`, `TARGET_BUDGET` / `HARD_BUDGET`, etc.) is defined in [`spec.md`](spec.md) §3.3 (item_id), §4.2 (leaf-split strategies), and §Glossary.

The chunker (`TARGET_BUDGET=6000`, `HARD_BUDGET=7000`) was deciding "one row = what fits budget". This conflated two independent concerns:

1. **Technical ceiling** — what the embedding model can hold
2. **Editorial intent** — what a single semantic row should be (one drug / one class)

They coincided by luck because 6000 tokens ≈ NHI's average condition size. Verified pollution audit on the **2026-04-24 release** (run 2026-05-23):

- **9 / 512 rows (1.8%)** contained ≥2 markdown sub-headings = multiple semantic units merged
- Worst case `sec5-5.1` 糖尿病用藥 — **12 sub-headings** glued into one row (Acarbose, miglitol, … 12 drugs)
- Other notable: `sec2-2.8.2` (11 sub-headings, 肺動脈高血壓治療劑), `sec10-10.8.2` (5, Quinolone 類), `sec7-7.2` (4, 止吐劑)

If a downstream user raised `HARD_BUDGET` to match a larger embedding window (e.g. 100k tokens), this problem would scale linearly — entire chapters would collapse to single rows.

Two secondary RAG-quality issues also surfaced during the audit:

- **TOP-K incompleteness**: from `sec9-9.69-part3-1` alone, a RAG consumer can't tell it's part 3 of 5. No metadata exists to hydrate the remaining siblings.
- **Lost anchor on recursive sub-split**: `sec9-9.69-part3-2` begins mid-list at `II.` with no link to its parent `3. 使用條件：`. Retrieval gets the rule body but loses the section heading it belongs under.

## Decision

Three independent changes, shippable separately, executed together:

### EMIT_DEPTH — editorial knob (Task I)

`EMIT_DEPTH = 5`: minimum tree depth at which a node may emit as a single row. Below this depth the chunker **must** descend, regardless of whether the subtree fits budget.

**Why 5**: NHI source tree max depth is 5 (款 layer in 第五節 / 第八節). Any value ≥ 5 produces identical output (no nodes go deeper); 5 is the minimum value that captures "as deep as the data goes". Values < 5 (3, 4) deliberately merge drugs per row — kept as a CLI override (`--emit-depth N`) for coarser-chunk consumers.

**Why this isn't just lowering `TARGET_BUDGET`**: budget controls *ceiling* of any row, not *granularity* of every row. Lowering budget would force splits where none were wanted (small adjacent leaves), while doing nothing to break up over-merged subtrees that happen to fit.

### RAG hydration metadata (Task J)

`Item` gains three fields → CSV gains three columns:

- `parent_id` — logical-unit id. Equals `item_id` when not split; siblings of a split share it.
- `part_index` — 1-based position within `parent_id` group.
- `total_parts` — count of rows sharing `parent_id`.

**Derivation rule:** see [`spec.md`](spec.md) §3.4 for the canonical definition and worked examples. Short version: strip chunker suffixes (`-partN[-M]`, `-tblN`, `-preamble`) iteratively; heading-hierarchy siblings do NOT share `parent_id`.

Downstream RAG hydrates same-`parent_id` rows when any one is retrieved — a "fetch siblings when one is hit" retrieval pattern. Implemented as `ParentDocumentRetriever` in LangChain and `AutoMergingRetriever` in LlamaIndex; trivial to do by hand for any retriever that exposes the raw matched row.

### Anchor preamble for continuation sub-parts (Task K)

When Strategy 0 recursively sub-splits an over-budget numbered group, the chunker:

1. Extracts the group's opener line (e.g. `3. 使用條件：`)
2. Strips trailing `:` / `：` to avoid double-colon (`3. 使用條件:（續）：`)
3. Injects `{opener}（續）：` after the heading in every continuation sub-part

First sub-part naturally contains the opener so needs no injection. Sub-parts 2..N now self-contain.

Edge case: if injecting the anchor pushes a sub-part over `HARD_BUDGET`, the budget contract assertion in `chunk_document` will catch it (anchor is <30 tokens vs. ~1000-token slack typical of Strategy 3 accumulation, so unlikely in practice).

## Consequences

### Verified outcomes (post-implementation, 2026-05-24)

| Metric | Before | After |
|---|---|---|
| Total items (2026-04-24 release) | 512 | 543 (+6.1%) |
| Multi-sub-heading rows | 9 (1.8%) | 0 |
| Rows over `HARD_BUDGET` | 0 | 0 |
| CSV columns | 8 | 11 |
| `9.69` part3-2 self-containment | broken | fixed |

### Breaking change
CSV column count 8 → 11. Positional readers break; `csv.DictReader` and pandas readers are transparent. Documented in CHANGELOG v0.1.0.

### Trade-off accepted
+6.1% item count is the cost of correctness — emit at depth 5 produces strictly more rows than emit at the first node that fits budget. The audit confirmed the new rows are semantically distinct, not redundant.

## Verification habits worth keeping

- **Pollution audit per release**: `grep -c '^## ' content` in each CSV row, expected `≤ 1`. Catches regression to the pre-EMIT_DEPTH behaviour.
- **Anchor presence check**: assert any `sec*-*-partN-M` row's content (after the heading line) starts with `{opener}（續）：`. Catches Strategy 0 sub-split regression.
- **Schema column count**: `csv.reader` first row → expect 11 columns. Catches accidental schema changes.

## Open questions resolved during implementation

- `--emit-depth` flag exists on `sync` and `chunk`. Not on `diff` (diff reads existing CSVs — chunker isn't involved).
- `parent_id` for non-split rows = `item_id` (uniform queries). Empty-string was considered and rejected.
- The pollution audit is **not** wired into `package._validate` as a hard gate — kept as a manual habit to avoid the chunker rejecting legitimate edge cases (e.g. a future regulation that legitimately contains nested `##` in its source). Revisit if false positives stabilize.
