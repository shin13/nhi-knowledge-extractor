# Spec — NHI Knowledge Extractor

- **Date:** 2026-05-21 (initial), updated 2026-05-24 for v0.1.0
- **Status:** Implemented (v0.1.0)
- **Predecessor:** `NHI-Knowledge-Extraction` — see [`intent.md`](intent.md) for problem statement

---

## 1. Goal

Convert Taiwan NHI medication regulation DOCX/ODT documents into a RAG-ingestion-ready CSV deliverable — automatically, repeatably, with **zero manual interventions**. The predecessor needed hand-fixing two files every release (`第8節` row 13, `第9節` row 85 including a Google Docs roundtrip). The successor eliminates both.

> **NHI domain vocabulary** (通則 / 節 / 條 / 項 / 款 / 目 / 附表) is glossed in [`intent.md`](intent.md) §Domain vocabulary. This spec uses those terms throughout; quick reference also in §Glossary at the bottom.

## 2. Output contract

### 2.1 Deliverable shape

- One CSV per source document
- All CSVs zipped into `藥品給付規定_YYYYMMDD.zip` along with `MANIFEST.json` and `CHANGES_YYYYMMDD.md`

### 2.2 CSV schema (11 columns)

> **Canonical reference.** README mirrors a brief summary; this table is the source of truth. Any schema change updates here first.

| Column | Notes |
|---|---|
| `topic` | Required by RAG import. `TOPIC_PREFIX` + ` > `-joined `section_path`. |
| `content` | Required by RAG import. Markdown body — prose + inline tables. |
| `heading` | Numeric heading of this knowledge item (e.g. `9.69.1.`). |
| `section_path` | Human-readable ancestor chain without prefix (e.g. `第9節 抗癌瘤藥物 > 9.69. > 9.69.1.`). |
| `item_id` | Stable across releases — the diff key (e.g. `sec9-9.69.1`). |
| `parent_id` | Logical-unit id. Equals `item_id` when not split; split siblings share it. RAG hydrates same-`parent_id` rows. |
| `part_index` | 1-based position within `parent_id` group. Non-split rows = 1. |
| `total_parts` | Count of rows sharing this `parent_id`. Non-split rows = 1. |
| `source_file` | NHI source filename. |
| `source_url` | NHI download URL. |
| `update_date` | Dual calendar (`2026/03/24 (民國115年3月24日)`). |

`TOPIC_PREFIX`:
```
臺灣全民健康保險藥品給付規定/藥品健保給付/健保規定 (Taiwan NHI) \n
```
The embedded `\n` is **literal** — prefix ends with a line break before the breadcrumb.

The RAG ingestion contract requires `topic` + `content`; additional columns are appended as text to `content` at import time.

### 2.3 Token budget — contract, not linter

- **Hard upper bound:** 7000 tokens / row (RAG import limit)
- **Target upper bound:** 6000 tokens / row (headroom for appended columns)
- **Tokenizer:** `tiktoken.cl100k_base` — OpenAI's encoding for `text-embedding-3` and `gpt-4*` models. De-facto standard for RAG token counting; matches the predecessor's `token_counter.py`.
- **Enforcement:** `chunk_document` asserts every `Item.token_count ≤ 7000` at end of chunk stage. Over-budget items fail the run with no zip produced.

## 3. Architecture

### 3.1 Five-stage layered pipeline

```
              fetch                parse               chunk              render            package
              ─────                ─────               ─────              ──────            ───────
  source_url ─────► [SourceDoc] ─────► [Document] ─────► [Item] ─────► [CsvRow] ─────► zip + CHANGES.md
                    + Manifest         tree              flat list      flat list
```

Each stage is a module. Data types are the contracts. See [`CLAUDE.md`](../CLAUDE.md) for the per-module file layout.

### 3.2 Core types

Three groups: **external** (what `fetch` returns), **tree** (parser's intermediate representation), and **output** (chunker's product).

**External types** — produced by `fetch`, identify NHI source documents.

```python
@dataclass(frozen=True)
class SourceDoc:
    path: Path             # local file (downloaded DOCX or ODT)
    url: str               # canonical NHI URL — kept in CSV for traceability
    display_name: str      # from <a title=…> on the NHI listing page
    update_date_iso: date  # release date parsed from the listing page's <time> element

@dataclass(frozen=True)
class Manifest:
    update_date_iso: date
    documents: list[SourceDoc]
    skipped_documents: list[SkippedDoc]  # 附表 + unrecognized titles, with reason
```

**Tree types** — what `parse` builds. The whole point: keep hierarchy explicit so the chunker can make budget decisions level by level.

```python
@dataclass
class Document:
    source: SourceDoc
    title: str                     # "第9節 抗癌瘤藥物"
    section_number: int | None     # 9 for sections, 0 for 通則, None for 附表
    root: Node

@dataclass
class Node:
    heading: str                   # "9.69." or "9.69.1." (numeric prefix + heading text)
    level: tuple[int, ...]         # (9, 69) or (9, 69, 1) — depth = len(level)
    body: list[Block]              # paragraphs/tables directly under this node, before any child
    children: list[Node]

Block = Paragraph | Table
```

`Node.body` is deliberately separated from `Node.children` so prose directly under a heading (before its first child heading) stays attached to that node — fixing a subtle predecessor bug where this content got misattributed to either the parent or the first child.

**Output type** — what `chunk` produces and `render` writes to CSV. One `Item` per CSV row.

```python
@dataclass(frozen=True)
class Item:
    item_id: str                   # "sec9-9.69.1" or "sec9-9.69-part3-2"  (see §3.3)
    section_path: list[str]        # ["第9節 抗癌瘤藥物", "9.69.", "9.69.1."]
    heading: str
    content_md: str                # Markdown: prose + inline tables
    source: SourceDoc
    token_count: int
    parent_id: str = ""            # see §3.4 — equals item_id when not split
    part_index: int = 1            # 1-based position within parent_id group
    total_parts: int = 1
```

Hierarchy lives only in the tree. Downstream stages (`chunk` → `render`) read it forward; nothing reaches back upstream.

### 3.3 `item_id` naming rules

Format: `sec{N}-{numeric_heading}[<suffix>]`, where `N` is the section number and the suffix is added only when the chunker splits a node.

| Pattern | Example | Meaning |
|---|---|---|
| `sec{N}-{level}` | `sec9-9.69.1` | Regular node — one CSV row per tree node |
| `sec0-{level}` | `sec0-` (root only) | 通則 (section_number = 0; uses Chinese-numeral headings, lives entirely in root body) |
| `…-part{K}` | `sec9-9.69-part3` | Leaf split into parts (Strategy 0/1/3) |
| `…-part{K}-{M}` | `sec9-9.69-part3-2` | Recursive sub-split — `part3` was over budget, sub-split into `-1`, `-2`, … |
| `…-preamble` | `sec3-3.2-preamble` | Node's own body emitted alongside its children |
| `…-tbl{K}` | `sec9-9.50-tbl2` | Oversize table split by rows |

**Worked example** — how `第9節 9.69.` becomes CSV rows:

```
Source tree                              Emitted item_id (5 rows total)
───────────────                          ─────────────────────────────
第9節 抗癌瘤藥物                          ────                 (no row — pure heading)
└─ 9.69. 免疫檢查點抑制劑    (over budget, sub-split via Strategy 0)
   ├─ group 1                            sec9-9.69-part1
   ├─ group 2                            sec9-9.69-part2
   ├─ group 3      (still over budget — recurses)
   │   ├─ sub 1                          sec9-9.69-part3-1
   │   └─ sub 2                          sec9-9.69-part3-2
   └─ group 4                            sec9-9.69-part4
```

All five rows share `parent_id = sec9-9.69` (see §3.4).

IDs are **deterministic** — same input always produces the same ID. This is what lets the differ align items across releases.

### 3.4 `parent_id` derivation

`parent_id` is derived from `item_id` by iteratively stripping chunker-added suffixes (`-partN[-M]`, `-tblN`, `-preamble`). It is **syntactic** — identifies sibling rows produced by the same split, not heading siblings.

Examples:
- `sec9-9.69-part3-2` → `parent_id = sec9-9.69` (siblings: `part1`/`part2`/`part3-1`/`part4`)
- `sec9-9.50-tbl2` → `parent_id = sec9-9.50`
- `sec3-3.2-preamble` → `parent_id = sec3-3.2`
- `sec9-9.70` → `parent_id = sec9-9.70` (unchanged)

Heading-hierarchy siblings (`sec5-5.1.1` and `sec5-5.1.2`) do NOT share `parent_id` — different logical units. Hydration is only semantically correct within a split family.

### 3.5 `EMIT_DEPTH`

Decouples editorial granularity from token budget. A node at depth `< EMIT_DEPTH` with children MUST descend, even if its subtree fits `TARGET_BUDGET`. Default 5 (NHI source tree max depth). Full rationale in [`emit-depth-plan.md`](emit-depth-plan.md).

## 4. Chunker algorithm

### 4.1 Main descent

```python
def chunk(node: Node, ancestors: list[Node], emit_depth: int = EMIT_DEPTH) -> list[Item]:
    depth = len(node.level)

    # Depth gate: force descent if shallower than emit_depth.
    if depth < emit_depth and node.children:
        items = []
        if has_significant_body(node):
            items.append(emit_item_for_body_only(node, ancestors))
        for child in node.children:
            items.extend(chunk(child, ancestors + [node], emit_depth))
        return items

    rendered = render_subtree_to_markdown(node)
    if count_tokens(rendered) <= TARGET_BUDGET:
        return [emit_item(node, ancestors, rendered)]

    # Over budget → descend if possible.
    if node.children:
        items = []
        if has_significant_body(node):
            items.append(emit_item_for_body_only(node, ancestors))
        for child in node.children:
            items.extend(chunk(child, ancestors + [node], emit_depth))
        return items

    # Leaf still over budget → semantic split.
    return split_leaf(node, ancestors)
```

**Implementation:** `chunk._chunk_node` mirrors this pseudocode; `chunk.split_leaf` implements §4.2 below.

### 4.2 Leaf-split priority (least structural damage first)

1. **Strategy 0 — multi-block numbered groups.** Scan body for `^\d+\.` paragraphs. Group blocks under whichever numbered item is "open". Each group becomes one chunk. Tables travel with the numbered item they describe.
2. **Strategy 1 — single-paragraph numbered list.** Single paragraph with embedded `1.`/`2.`/`3.` items → split at each numbered marker.
3. **Strategy 2 — oversize single table.** Split by rows, keep header on each: `-tbl1`, `-tbl2`, …
4. **Strategy 3 — greedy paragraph accumulation.** Last-resort fallback for prose-only over-budget leaves.

Tables in Strategies 1 and 3 are atomic — travel in one chunk with surrounding prose if they fit, alone if not.

**Anchor preamble on recursive sub-split:** if a Strategy 0 group itself exceeds `HARD_BUDGET` and must be sub-split, the chunker extracts the group's opener (e.g. `3. 使用條件`), strips trailing colon, and injects `{opener}（續）：` into each continuation sub-part's heading line. Self-containment for retrieval. See [`emit-depth-plan.md`](emit-depth-plan.md) §Anchor preamble.

### 4.3 `has_significant_body` rule

For a node with both `body` and `children`:

- **No body:** pure section heading. Don't emit; node contributes only to descendants' `section_path`.
- **Trivial body** (≤ 200 tokens, no tables, single paragraph): prepend to first child's content as context.
- **Significant body** (multiple paragraphs, contains a table, or > 200 tokens): emit a standalone `-preamble` item.

Eliminates the predecessor's `"General Information"` / `"Additional Information"` dummy-regulation fallbacks.

### 4.4 Hard non-goals

- **No sibling merging.** Two adjacent small leaves never combine into one row. Preserves `item_id` stability.
- **No sentence-level splitting.** If a single paragraph exceeds target budget (rare), accept an item slightly above target but below hard limit. Avoids Chinese sentence-boundary edge cases.

## 5. Other stages (brief)

- **`fetch`** — `cloudscraper` session, ROC date parsing. Groups listing links by document title; classifies as `regulation` (download) / `appendix_form` (record in `Manifest.skipped_documents`) / `unknown` (warn). Prefers `.docx`, falls back to `.odt`.
- **`parse`** — DOCX via `python-docx`; ODT natively via zipfile + lxml. Walks document body in order; dispatches Paragraph (heading detection via style + numeric prefix regex) vs. Table.
- **`render`** — Pure function `Item → dict[str, str]`. Writes CSVs with `csv.DictWriter`, `utf-8-sig` BOM (Excel-friendly).
- **`package`** — Groups items by `source.path.name`, writes per-source CSVs into dated folder, generates `MANIFEST.json` with content hashes, runs `diff` against prior release, prepends to `CHANGELOG_data.md` (gitignored), zips folder.
- **`diff`** — Compares two `MANIFEST.json` files by `item_id`. Added / Removed by ID set difference; Modified by `content_sha256` mismatch.

## 6. Testing strategy

### 6.1 Unit tests (per module)

One `test_<module>.py` per source module. Standard assertions on tree structure, table extraction, column mapping, etc.

### 6.2 Pain-case regression tests

`tests/test_chunk_pain_cases.py` — the reason this repo exists:

- `test_section8_row13_no_overflow` — fixture `第8節_免疫製劑_*.docx`. Asserts no item exceeds 7000 tokens and `8.2.4.` Etanercept emits as multiple items (chunker descended into sub-clauses).
- `test_section9_row85_table_preserved` — fixture `第9節_抗癌瘤藥物_*.docx`. Asserts the `9.69.` drug × indication table appears in some item's `content_md` containing `pembrolizumab`, `nivolumab`, `atezolizumab` columns and rows like `黑色素瘤`.

### 6.3 Budget contract property test

`test_chunk.py::test_all_fixtures_fit_budget` — for every DOCX in `tests/fixtures/`: chunker runs without exception, all `token_count ≤ 7000`, all `item_id`s unique.

Run on CI on push and PR.

## 7. Success criteria

A release run with `nhi-extract sync` is successful when:

1. Zero manual interventions required
2. Every emitted item is ≤ 7000 tokens
3. The `第9節 / 9.69.` table appears as Markdown in some item's content
4. `CHANGES_YYYYMMDD.md` lists item-level adds / removes / modifies vs. last release
5. Zip is produced and ready to deliver

All five hold as of v0.1.0.

---

## Glossary

Terms used across this spec and the rest of `docs/`. NHI domain vocabulary (通則 / 節 / 條 / 項 / 款 / 目 / 附表) is glossed separately in [`intent.md`](intent.md).

### Schema terms

| Term | Meaning |
|---|---|
| `item_id` | Unique stable id per CSV row; the diff key. Format `sec{N}-{level}[-suffix]` — see §3.3. |
| `parent_id` | Logical-unit id. Equals `item_id` when not split; split siblings share it. See §3.4. |
| `part_index` / `total_parts` | 1-based position within a `parent_id` group, and count of siblings. Both `1` for non-split rows. |
| `section_path` | Title chain from doc root to this row's heading, e.g. `["第9節 抗癌瘤藥物", "9.69.", "9.69.1."]`. |
| `topic` | CSV column required by RAG ingestion: `TOPIC_PREFIX` + ` > `-joined `section_path`. |

### Suffixes on `item_id`

| Suffix | Meaning | Example |
|---|---|---|
| `-part{K}` | One of K parts a leaf was split into | `sec9-9.69-part3` |
| `-part{K}-{M}` | Recursive sub-split — `partK` itself was over budget | `sec9-9.69-part3-2` |
| `-preamble` | Node's own body emitted as a row alongside its children's rows | `sec3-3.2-preamble` |
| `-tbl{K}` | Oversize table split by rows | `sec9-9.50-tbl2` |

### Budget / depth constants (`src/nhi_extractor/config.py`)

| Name | Default | Meaning |
|---|---|---|
| `TARGET_BUDGET` | 6000 | Soft ceiling. Chunker tries to land items below this. |
| `HARD_BUDGET` | 7000 | Hard ceiling. Items exceeding this fail the run (no zip produced). |
| `EMIT_DEPTH` | 5 | Minimum tree depth at which a node may emit as a single row. Below this, chunker MUST descend even if subtree fits budget. See [`emit-depth-plan.md`](emit-depth-plan.md). |
| `TIKTOKEN_ENCODING` | `cl100k_base` | Tokenizer used by `count_tokens`. |

### Chunker terms

| Term | Meaning |
|---|---|
| `has_significant_body` | True for a node whose body is large/structurally important enough to warrant its own row alongside its children. See §4.3. |
| Strategy 0 | `split_leaf` strategy: split multi-block leaf at top-level numbered items (`1.`, `2.`, `3.`). Tables travel with the numbered item they describe. |
| Strategy 1 | Split single-paragraph leaf at embedded numbered list markers. |
| Strategy 2 | Split oversize single table by rows, keeping header on each part. |
| Strategy 3 | Last-resort greedy paragraph accumulation for prose-only over-budget leaves. |
| Anchor preamble | When Strategy 0 recursively sub-splits an over-budget group, continuation sub-parts (part3-2 onwards) inject `{opener}（續）：` after the heading line so each row is self-contained. See [`emit-depth-plan.md`](emit-depth-plan.md). |

