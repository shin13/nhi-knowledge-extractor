# Project Intent — NHI Knowledge Extraction

> Captured 2026-05-21. This document exists to make the *goal* and the *pain* obvious before designing a successor repo. It is not a spec for the current code; it is a brief for the next one.

---

## 1. The Goal in One Sentence

**Convert Taiwan NHI (National Health Insurance) medication regulation documents into a knowledge-base–ready format — automatically, repeatably, and with zero manual hand-fixing.**

The output feeds a downstream RAG / database used for medical patient-education and clinical-pharmacy lookups. Each output unit is a "knowledge item" — a self-contained chunk of regulation that an LLM can retrieve and cite.

---

## 2. The Source Material (and Why It's Hard)

- **Where**: <https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html>
- **Format**: ODT files (also published as DOCX) — one file per 節 (section) plus附表 (appendices)
- **Cadence**: NHI updates irregularly (last seen: 0930, 1023, 1126, 1229, 20260123, 20260226, 20260324, 20260424). Each update needs re-ingestion.
- **Structure**: Hierarchical — 節 → 條 → 項 → 款 → 目, expressed as numeric headings like `9.69.1.1.`. **Up to at least 4 levels deep.**
- **Embedded tables**: Some regulations contain decision-matrix tables (e.g. drug × indication × required PD-L1 cutoff). These are *structurally significant* — losing them loses meaning.
- **Language**: Traditional Chinese body, mixed-language drug names (Chinese + English + brand names with parentheses), ROC-calendar dates (民國年).

---

## 3. The Real Problem (Why the Current Pipeline Hurts)

The current code treats the document as **a flat list of paragraphs split by a regex on heading numbers**. This model is wrong in three ways:

### 3.1 Hierarchy is collapsed, not preserved

`odt_converter.py` only recognises 2-level and 3-level headings (`N.N.` and `N.N.N.`) and *actively rejects* 4-level (`N.N.N.N.`) as content. So a regulation like `9.69.` (immune checkpoint inhibitors) accumulates **every sub-rule, every sub-sub-rule, and every table** beneath it into a single CSV cell. By the time the linter complains the cell is 10 000+ tokens, the structure that *would have* let us split it cleanly has already been destroyed.

### 3.2 Tables are silently flattened

`odfpy.getElementsByType(P)` returns `<text:p>` elements only. The `<table:table>` / `<table:table-row>` / `<table:table-cell>` grid in the source is never reconstructed. When a regulation contains a "drug × indication" matrix (e.g. `第9節` row 85 / `9.69.`), the cells get serialised as adjacent paragraphs and the matrix is lost. The current "fix" is a human round-trip: **download DOCX → paste into Google Docs → export Markdown → LLM-convert table to CSV → paste back**. This happens every release.

### 3.3 The token budget is a linter, not a contract

The conversion has no awareness of the `< 7000 tokens / row` constraint. We discover overflow with `token_counter.py` *after* the CSV exists, then patch it with `csv_splitter.py` (a regex re-split on `^\d+\.`) — which doesn't know about the original heading hierarchy and re-splits at arbitrary places. Two files (`第8節`, `第9節`) overflow every single release. One of them (`第9節`) cannot be fixed by the splitter at all because the overflow includes a table.

### 3.4 The output schema is the wrong shape

`(topic, content, reference)` is a flat triple. The source is a tree. Every part of the current pipeline is fighting that mismatch:

- `Regulation.get_topic_path()` flattens the chain to `"document_title > parent_heading"` (only one level of parent)
- The current heading is *prepended into content*, not stored as its own field — so downstream consumers can't filter or group by it
- `reference` is one of `"網站更新日期：YYYY/MM/DD"` or `"條目產製日期：…"` — a string, not a structured date or URL

---

## 4. What "Done Right" Looks Like

The successor repo should let a fresh release run as:

```bash
$ nhi-extract sync
✓ checked source — 47 documents, 3 changed since last run (20260424)
✓ downloaded 3 ODTs
✓ parsed → 312 knowledge items (was 309)
✓ all items within token budget (max: 4 821, limit: 7 000)
✓ packaged → 藥品給付規定_20260521.zip
✓ no manual interventions required
```

…with **no human in the loop**, no Google Docs roundtrip, no `csv_splitter.py` invocations.

### 4.1 Core capabilities the new repo must have

1. **Hierarchy-preserving parser.** Walk the ODT/DOCX as a tree, not a paragraph stream. Recognise heading depth from the source's actual style information *and* from the numbering (`N.N.N.N.…`), to arbitrary depth.
2. **Table-aware extraction.** Read `<table:table>` directly. Emit each table as Markdown (or structured JSON) inline within its parent regulation. Never lose row/column structure.
3. **Token-budget–aware chunking.** When a leaf regulation exceeds the budget, split at the *next available semantic boundary* (sub-heading, numbered list item, sentence) — chosen by the parser, not patched by a downstream tool. Splits should be deterministic and explainable.
4. **Structured output, not just flat CSV.** Preserve the hierarchy as machine-readable fields (e.g. `section`, `path: ["第9節", "9.69.", "9.69.1."]`, `heading`, `body`, `tables: [...]`, `source_url`, `update_date`). Flat CSV becomes one *projection* of this, not the source of truth.
5. **Idempotent + diff-able.** Re-running on the same source should produce the same output. Running on a new release should produce a diff (added / removed / modified items) for review before delivery.
6. **Tests against real fixtures.** Pin the current pain cases (`第8節` row 13, `第9節` row 85 with its table) as regression tests so the next refactor can't reintroduce them.

### 4.2 Non-goals (don't get distracted)

- Not a general-purpose ODT/DOCX library. Optimise for the NHI document shape.
- Not a RAG system. The output is the input *to* a RAG system.
- Not a UI. CLI is enough. Delivery is still a zip to a human (邦漢).
- Not a scheduler. NHI updates are irregular and human-triggered.

---

## 5. The Failure Modes to Design Against

Use these as test cases / acceptance criteria:

| Failure mode                                                     | Today                                                          | Must become                                                  |
| ---------------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------ |
| Deep nesting (`9.69.1.1.`)                                       | Silently flattened into parent row                             | Preserved as its own item with full ancestor path            |
| Embedded decision-matrix table                                   | Flattened into paragraph-soup; manual Google Docs reconstruct | Extracted as Markdown table inline                           |
| Single regulation > 7 000 tokens                                 | Linter warning + manual `csv_splitter.py` invocation           | Auto-split at semantic boundary; budget never exceeded       |
| New release with one changed section                             | Re-process everything; no diff                                 | Re-process changed only; emit diff for human review          |
| Topic prefix change                                              | Edit constant, re-run whole pipeline                           | Prefix is a render-time option, not baked in                 |
| ROC calendar date in the document body                           | Treated as opaque text                                         | Parsed into structured date; both ROC and Western available |
| Drug name with parentheses & semicolons (`atezolizumab；nivolumab…`) | Fine in cell, but breaks naive downstream splitting          | Stable as a single token; structured drug-list field optional |

---

## 6. The Domain Vocabulary (use these terms in code)

| Term                | Meaning                                                                 |
| ------------------- | ----------------------------------------------------------------------- |
| **節 (section)**    | Top-level chapter, e.g. 第9節抗癌瘤藥物. One source ODT file per section. |
| **條 (article)**    | Numbered top-level regulation within a section, e.g. `9.69.`            |
| **項 (clause)**     | Sub-rule, e.g. `9.69.1.`                                                |
| **款 (subclause)**  | Further nested, e.g. `9.69.1.1.`                                        |
| **目 (item)**       | Deepest level — numbered list items like `1.`, `2.`, `3.` within a 款 |
| **附表 (appendix)** | Standalone supplementary documents — separate ODTs, often forms or tables |
| **knowledge item**  | One emitted unit — a leaf in the tree, sized to fit the token budget    |
| **topic path**      | Full ancestor chain for a knowledge item — used for retrieval context   |

---

## 7. Open Questions for the Successor Design

These were never answered in the current repo and the new repo should answer them explicitly:

1. **Granularity contract**: Should knowledge items always be at one level (e.g. always 條-level)? Or variable depth based on token budget? Pick one and write it down.
2. **Table representation**: Markdown inline in `body`, or a separate `tables: [...]` field? Downstream RAG retrieval quality should drive this — talk to 邦漢.
3. **Deduplication across releases**: NHI republishes the full document each time, even if only one 節 changed. Do we keep per-item version history, or just snapshot the latest?
4. **Source authority**: ODT or DOCX? DOCX preserves tables better in most parsers — worth re-evaluating the format choice.
5. **What is a "reference"?** Today it's a free-form Chinese string. Should it be `{source_url, document_filename, update_date_roc, update_date_iso, section_id}`?

---

## 8. What to Carry Over from the Current Repo

- The **`TOPIC_PREFIX`** value and its purpose (downstream namespace tag for the RAG corpus).
- The **dated-zip delivery convention** (`藥品給付規定_YYYYMMDD.zip` → 邦漢).
- The **CSS selector and ROC-date parsing** for the website update date — that part works.
- The **list of past deliverables** in `data/regulations/medication/` as regression input.

## 9. What to Throw Away

- `csv_splitter.py` — the existence of this tool is the bug.
- The 4-level heading rejection logic in `_parse_heading_level`.
- The `_get_text_from_element` recursion that flattens table cells into paragraph text.
- The `(topic, content, reference)` flat schema as the *source of truth* (keep it as a renderable view).
- The dummy-regulation fallbacks (`"Empty document content"`, `"Additional Information"` etc.) — they hide bugs.

---

*Next step: brainstorm the successor architecture against this brief.*
