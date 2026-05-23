# EMIT_DEPTH + RAG Metadata + Anchor Preamble — Implementation Plan

> Planned in session 2026-05-23. Not yet implemented. Next session should pick this up
> by re-reading this file + `HANDOFF.md` + `docs/spec.md` §4 (chunker).

## Why this change exists

The current chunker (TARGET_BUDGET=6000, HARD_BUDGET=7000) decides "one row =
what fits in budget". This conflates two independent concerns:

1. **Technical ceiling** — what the downstream embedding model can hold.
2. **Editorial intent** — what a single semantic row should be (one drug / one class).

Today they happen to coincide because 6000 tokens ≈ NHI's average condition size.
That's luck, not design. Verified pollution under current pipeline (run 2026-05-23):

- **9 / 512 rows (1.8%)** contain ≥2 markdown sub-headings = multiple sub-units merged
- Worst case: `sec5-5.1` 糖尿病用藥 has **12 sub-headings** glued into one row
  (Acarbose, miglitol, 等 12 個糖尿病藥規定併成一筆)
- Other notable: `sec2-2.8.2` (11 sub-headings, 肺動脈高血壓治療劑), `sec10-10.8.2`
  (5 sub-headings, Quinolone 類), `sec7-7.2` (4 sub-headings, 止吐劑)

If a downstream user switches to an embedding model with a 100k-token window
and naively raises HARD_BUDGET to match, the chunker collapses further toward
"整節一筆" — the problem above scales 10×.

This plan separates the two concerns:

- `EMIT_DEPTH` (new) — editorial knob: minimum depth at which a node may emit
- `HARD_BUDGET` (existing) — technical knob: ceiling for any single row

It also addresses two RAG-quality issues that result from splitting:

- Downstream RAG can't tell from `sec9-9.69-part3-1` alone that this is "part 3 of 5"
  → add `parent_id` / `part_index` / `total_parts` metadata columns
- Recursive sub-split (e.g. `part3-2`) loses its parent numbered-item anchor
  (`3. 使用條件:` is gone, content starts mid-list at `II.`)
  → inject anchor preamble `3. 使用條件（續）：` into continuation parts

## Verified design parameters

- **`EMIT_DEPTH = 5`** confirmed as default (2026-05-23 user decision)
  - NHI source max tree depth is 5 (第五節, 第八節 reach 款 layer)
  - Any value ≥5 produces identical output (539 items) — 5 is the minimum
    explicit value that captures "as deep as data goes"
  - Set lower (3, 4) gives coarser rows; set higher safe but no effect
- **Q2 (9.69 over-budget) = keep current leaf-splitter behavior**
  - Quality improved by Task K anchor preamble, not by removing the split
- **Concern 1 (TOP-K incompleteness) = Option A + B**
  - A: add `parent_id` / `part_index` / `total_parts` metadata columns
  - B: document hydration pattern in README for RAG consumers
- **Concern 2 (part3-2 missing context) = Option A**
  - Anchor preamble: inject group's first numbered-item line + `（續）：`
    into continuation sub-parts

## Expected outcomes

After all tasks land:

| Metric | Current | After |
|---|---|---|
| Total items | 512 | ~539 (+5.3%) |
| Multi-subheading rows | 9 (1.8%) | 0 |
| Rows over HARD_BUDGET | 0 | 0 (9.69 still split, just better quality) |
| CSV columns | 8 | 11 (+ parent_id, part_index, total_parts) |
| 9.69 part3-2 self-containment | broken | fixed (anchor present) |

---

## Task I — `EMIT_DEPTH` parameter

**Goal**: explicit minimum-emit-depth contract, decoupled from token budget.

### Files
- `src/nhi_extractor/config.py` — new constant + validation
- `src/nhi_extractor/chunk.py` — `_chunk_node` depth gate
- `src/nhi_extractor/cli.py` — `sync --emit-depth N` flag
- `tests/test_chunk_emit_depth.py` — **new file**

### Changes

**config.py**
```python
EMIT_DEPTH = 5   # Minimum emit depth (inclusive). Positive integer.
                  # Rule: descend to at least this depth before emitting;
                  # if a node at this depth still exceeds TARGET_BUDGET, descend further.
                  # NHI source max tree depth is 5 (款 layer in 第五節/第八節);
                  # setting >5 has no effect, setting <3 risks polluted rows.
```

Validate at CLI entry: `if not isinstance(EMIT_DEPTH, int) or EMIT_DEPTH < 1: raise`.

**chunk.py `_chunk_node`** — add depth gate before existing fits-budget check:
```python
def _chunk_node(node, ancestors, section_number, source, target_budget, emit_depth):
    depth = len(node.level)

    # Pure-heading nodes (no body, has children) always descend — existing.
    if node.children and not node.body:
        ...

    # NEW: depth below emit_depth + has children → force descend (ignore budget).
    if depth < emit_depth and node.children:
        out = []
        if has_significant_body(node):
            out.append(_emit_body_only(node, ancestors, section_number, source))
        new_ancestors = ancestors + [node]
        for c in node.children:
            out.extend(_chunk_node(c, new_ancestors, section_number, source,
                                   target_budget, emit_depth))
        return out

    # Existing logic: fits budget? → emit subtree. Else descend or leaf-split.
    ...
```

`chunk_document` reads `EMIT_DEPTH` from config as default, accepts override.

**cli.py**
```python
emit_depth: int = typer.Option(EMIT_DEPTH, "--emit-depth",
                                help="Minimum emit depth (default 5)")
```

### Tests (new file)

1. `test_emit_depth_forces_descent_when_subtree_fits_budget` — d=1 node that fits → still descends
2. `test_emit_depth_emits_at_target_when_fits` — d=5 fits → emit as single item
3. `test_emit_depth_descends_past_target_when_over_budget` — d=5 over budget → descend / leaf-split
4. `test_emit_depth_leaf_emits_regardless_of_depth` — d=2 leaf (no children) → emit
5. `test_emit_depth_too_large_is_safe` — emit_depth=10 vs 5 on real fixture → identical output
6. `test_emit_depth_validates_positive_int` — emit_depth=0 raises at CLI

### Existing test calibration
- `test_chunk_document_small_doc_one_item` — 3.1 / 3.2 at d=2 are leaves, behavior unchanged
- `test_chunk_document_descends_when_over_budget` — descends past d=3 either way, unchanged
- Pain cases will need minor metadata tweaks (handled in Task J)

---

## Task J — Item metadata: `parent_id` / `part_index` / `total_parts`

**Goal**: every row carries enough metadata for RAG consumers to know "I'm part X of Y for parent Z" and hydrate siblings.

### Files
- `src/nhi_extractor/types.py` — `Item` gains 3 fields
- `src/nhi_extractor/chunk.py` — `chunk_document` post-process step
- `src/nhi_extractor/render.py` — CSV emits 3 new columns
- `tests/test_chunk_metadata.py` — **new file**
- `tests/test_render.py` — column count assertions updated

### Changes

**types.py**
```python
@dataclass(frozen=True)
class Item:
    item_id: str
    parent_id: str          # NEW — logical-unit id; equals item_id when not split
    part_index: int         # NEW — 1-based position within parent_id group
    total_parts: int        # NEW — count of items sharing parent_id
    section_path: list[str]
    heading: str
    content_md: str
    source: SourceDoc
    token_count: int
```

**chunk.py post-process** (before HARD_BUDGET assertion in `chunk_document`):
```python
SUFFIX_RE = re.compile(r"-(part\d+(-\d+)?|tbl\d+|preamble)$")

def _derive_parent_id(item_id: str) -> str:
    while True:
        m = SUFFIX_RE.search(item_id)
        if not m:
            return item_id
        item_id = item_id[:m.start()]

def _assign_metadata(items: list[Item]) -> list[Item]:
    from collections import defaultdict
    from dataclasses import replace
    groups: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        groups[_derive_parent_id(it.item_id)].append(it)
    out = []
    for it in items:
        pid = _derive_parent_id(it.item_id)
        siblings = groups[pid]
        idx = siblings.index(it) + 1
        out.append(replace(it, parent_id=pid, part_index=idx,
                           total_parts=len(siblings)))
    return out
```

**render.py** — new column order:
```
item_id, parent_id, part_index, total_parts, section_path, heading, content, topic, source_url
```

### Tests (new file)

1. `test_single_emit_item_has_self_as_parent` — non-split row → parent_id == item_id, part_index=1, total_parts=1
2. `test_strategy0_split_shares_parent_id` — 9.69-like fixture: 4 parts → all parent_id `sec9-9.69`, part_index 1..4, total_parts=4
3. `test_recursive_subsplit_flat_numbering` — part3 → part3-1/part3-2: flat numbering (part_index 3 and 4, total_parts=5), NOT hierarchical 3.1/3.2
4. `test_preamble_parent_resolution` — `sec3-3.2-preamble` → parent_id `sec3-3.2`; if no sibling exists, total_parts=1 (standalone preamble)
5. `test_table_split_shares_parent_id` — `tbl1`/`tbl2` siblings share parent_id

### Existing test calibration
- `test_render.py` — column count from 8 → 11, dict assertions add new keys
- `test_chunk_pain_cases.py::test_section_9_69_*` — assert `all r.parent_id == 'sec9-9.69'` and `{r.part_index} == {1,2,3,4,5}`

---

## Task K — Anchor preamble for continuation sub-parts

**Goal**: when Strategy 0 recursively sub-splits an over-budget numbered group, prepend that group's opener line (e.g. `3. 使用條件:`) with `（續）：` suffix to each continuation sub-part.

### Files
- `src/nhi_extractor/chunk.py` — `split_leaf` Strategy 0 recursion block
- `tests/test_chunk_leaf.py` — new anchor tests
- `tests/test_chunk_pain_cases.py` — 9.69 part3-2 assertion

### Changes

Replace the `zip(items, groups)` block inside Strategy 0 with:

```python
out: list[Item] = []
for it, group in zip(items, groups):
    if it.token_count <= HARD_BUDGET:
        out.append(it)
        continue

    # Extract group opener (the "N." paragraph that starts this group).
    anchor = None
    for b in group:
        if isinstance(b, Paragraph) and TOP_LEVEL_ITEM_RE.match(b.text):
            anchor = b.text.split('\n')[0].rstrip('：:')
            break

    sub_leaf = Node(heading=leaf.heading, level=leaf.level, body=group)
    sub_items = _split_leaf_without_strategy_0(
        sub_leaf, ancestors=ancestors, section_number=section_number,
        source=source, target_budget=target_budget,
    )

    for j, si in enumerate(sub_items, start=1):
        new_id = f"{it.item_id}-{j}"
        if j == 1 or not anchor:
            out.append(replace(si, item_id=new_id))
        else:
            heading_line, _, rest = si.content_md.partition('\n')
            new_content = f"{heading_line}\n{anchor}（續）：\n{rest}"
            out.append(replace(
                si, item_id=new_id, content_md=new_content,
                token_count=count_tokens(new_content),
            ))
```

### Edge cases
- Anchor too long → take first line only via `split('\n')[0]`
- Trailing `:` / `：` already on anchor → `rstrip('：:')` avoids `3. 使用條件:（續）：`
- Anchor injection pushes sub-part over HARD_BUDGET → in theory possible but anchor is <30 tokens vs. ~1000-token slack in Strategy 3 accumulation; if it ever fires, chunk_document's HARD_BUDGET assertion will catch it

### Tests

1. `test_split_leaf_anchor_repeated_in_continuation` — synthetic 4-numbered-item leaf with item 3 oversized → sub-parts ≥2 contain `（續）`
2. `test_split_leaf_first_subpart_no_anchor_suffix` — first sub-part has no `（續）`
3. `test_chunk_pain_cases.py::test_section_9_69_continuation_has_anchor` — real fixture: `sec9-9.69-part3-2` contains `3. 使用條件（續）：`
4. `test_split_leaf_anchor_strips_trailing_colon` — opener `3. 使用條件:` → injected text doesn't double-colon

---

## Task L — Documentation

### Files
- `README.md` — add Output schema table, RAG hydration section, EMIT_DEPTH section
- `docs/spec.md` — update §3 (Item type), §4.1 (chunker algorithm), §4.2 (Strategy 0)
- `CHANGELOG.md` — manual breaking-schema note appended to next package-generated entry
- `CLAUDE.md` — Lessons learned: design rationale for splitting EMIT_DEPTH from HARD_BUDGET

### README content draft

```markdown
## Output schema

Each CSV row is a RAG-ingestion-ready chunk. Columns:

| Column | Description |
|---|---|
| item_id | Unique stable id (diff key). Format `sec{N}-{level}[-partK[-M]]` |
| parent_id | Logical-unit id. Equals item_id when not split; siblings of a split share it |
| part_index | 1-based position within parent_id group |
| total_parts | Count of rows sharing this parent_id |
| section_path | Title chain from doc root to this heading |
| heading | This row's heading (with numbering) |
| content | Markdown content |
| topic | Fixed prefix (臺灣全民健保藥品給付規定/…) |
| source_url | NHI source link |

### RAG hydration

When a retrieved row has `total_parts > 1`, hydrate all rows with the same
`parent_id` to recover the complete logical unit. This mirrors LangChain's
ParentDocumentRetriever and LlamaIndex's AutoMergingRetriever patterns.

Example: a query for "免疫檢查點抑制劑使用條件" hits `sec9-9.69-part3-1`.
Hydrate part1..part4 (5 rows total, all parent_id=`sec9-9.69`) for the full
9.69 regulation.

## EMIT_DEPTH — granularity control

`EMIT_DEPTH` (default 5) is the minimum tree depth at which a node may be
emitted as a single row. NHI source structure varies across sections:

- 第九節 9.70 Pertuzumab → level=(9,70), depth 2 = drug level → one drug per row
- 第四節 4.1.2.1 短效型 G-CSF → level=(4,1,2,1), depth 4 is the drug level

Default 5 captures the deepest natural NHI level (款 in 第五節/第八節). Setting
higher (6+) has no effect; setting lower (3, 4) merges multiple drugs per row
in some sections — only do this if you want coarser chunks deliberately.

Override per-run: `uv run nhi-extract sync --emit-depth 4`
```

### spec.md updates
- §3 — add 3 metadata fields to Item schema
- §4.1 — document EMIT_DEPTH gate in chunker descent
- §4.2 — document Strategy 0 anchor preamble for continuation sub-parts

### CHANGELOG manual addendum (appended after auto-generated section)

```markdown
### Schema changes (breaking)

CSV gains 3 columns: `parent_id`, `part_index`, `total_parts`. Downstream
RAG ingestion that relies on positional column index must update.
DictReader / pandas readers handle this transparently.
```

### CLAUDE.md lessons addition

```markdown
### Chunker design: decouple "what fits embedding" from "what's a row"

- **Lesson**: in early NHI chunker design TARGET_BUDGET=6000 doubled as both
  the embedding-fit ceiling AND the implicit semantic-unit size. They aligned
  by coincidence (NHI conditions ≈ 6000 tokens average). Switching embedding
  models would silently degrade chunk shape.
- **Fix**: `EMIT_DEPTH` (editorial knob) + `HARD_BUDGET` (technical knob)
  are independent. EMIT_DEPTH says "every row must be a tree node at depth ≥N";
  HARD_BUDGET says "no row may exceed this size".
- **Verification habit**: pollution audit query (find rows with ≥2 markdown
  `##` headings inside content) caught 9/512 (1.8%) merged rows under old design.
  Worth re-running per release as regression check.
```

---

## Task M — Full E2E verification

```bash
cd /Users/shin/Projects/nhi-knowledge-extractor

# Clean prior outputs (not chapters/ — those are NHI source)
rm -rf data/regulations/medication/藥品給付規定_*/
rm -f data/regulations/medication/藥品給付規定_*.zip

# Run pipeline end-to-end
uv run nhi-extract sync

# Automated verification
uv run python << 'PYEOF'
import csv, re
from pathlib import Path
d = Path('data/regulations/medication/藥品給付規定_20260424')

total_items = 0
multi_subheading_rows = 0
for p in d.glob('第*.csv'):
    with open(p, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    total_items += len(rows)
    for r in rows:
        if len(re.findall(r'^##\s', r['content'], re.MULTILINE)) >= 2:
            multi_subheading_rows += 1

print(f'Total items: {total_items}   (expect ~539)')
print(f'Multi-subheading rows: {multi_subheading_rows}   (expect 0)')

with open(next(d.glob('第九節*.csv')), encoding='utf-8-sig') as f:
    rows = [r for r in csv.DictReader(f) if r['parent_id'] == 'sec9-9.69']
print(f'\nsec9-9.69 group: {len(rows)} rows')
for r in rows:
    print(f'  {r["item_id"]:30s} pidx={r["part_index"]}/{r["total_parts"]}')

p32 = next(r for r in rows if r['item_id'] == 'sec9-9.69-part3-2')
assert '使用條件（續）' in p32['content'], f"anchor missing: {p32['content'][:200]}"
print('\nOK: part3-2 anchor injection verified')
PYEOF
```

### Acceptance criteria
- [ ] Total items = 539 ± 2
- [ ] Multi-subheading rows = 0
- [ ] sec9-9.69: 5 rows, all `parent_id=sec9-9.69`, `part_index` 1..5, `total_parts=5`
- [ ] sec9-9.69-part3-2 contains `使用條件（續）`
- [ ] Full pytest suite (83 existing + ~15 new) green
- [ ] MANIFEST.json + CHANGELOG.md correctly regenerated
- [ ] git diff shows expected file set: config.py / chunk.py / types.py / render.py / cli.py / 3 new test files / README.md / docs/spec.md / CLAUDE.md / CHANGELOG.md

---

## Execution order

**I → J → K → L → M**. Dependencies:
- J reads items produced by I's modified `_chunk_node`
- K modifies content_md that J's post-process will see (parent_id derivation must
  still work — Task K uses standard `-partN-M` suffix, which `SUFFIX_RE` matches)
- L documents the cumulative behavior of I+J+K
- M validates everything together

Per-task discipline:
1. Write failing tests first (TDD per CLAUDE.md)
2. Implement minimum to pass
3. `uv run pytest -v` — all green
4. Commit with conventional message
5. Move to next task

Estimated total: **3–4 hours**.

## Open questions for the next session

- Does the cli `--emit-depth` flag also belong on `chunk` and `diff` subcommands?
  (Probably yes for `chunk`, no for `diff` since diff reads existing CSVs.)
- Should `parent_id` self-reference (when total_parts=1) be `item_id` or empty string?
  Plan defaults to `item_id` for uniform queries; revisit if downstream finds it noisy.
- After landing, should we re-run the "multi-subheading rows" audit as part of
  `package._validate` as a hard gate? (Currently a one-off verification script.)
