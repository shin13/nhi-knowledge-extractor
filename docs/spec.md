# Spec — NHI Knowledge Extractor (successor repo)

- **Date:** 2026-05-21
- **Status:** Approved design, ready for implementation planning
- **Predecessor:** `NHI-Knowledge-Extraction` (see `INTENT.md` in that repo for the problem statement)
- **Successor repo name:** `nhi-knowledge-extractor` (tentative)

---

## 1. Goal

Convert Taiwan NHI medication regulation DOCX documents into a RAG-ingestion–ready CSV deliverable — automatically, repeatably, with **zero manual interventions**. The current pipeline requires hand-fixing two files every release (`第8節_免疫製劑` row 13, `第9節_抗癌瘤藥物` row 85 including a Google Docs roundtrip for an embedded table). The successor must eliminate both.

## 2. Output contract

### 2.1 Deliverable shape

- One CSV per source document
- All CSVs zipped into `藥品給付規定_YYYYMMDD.zip`
- Plus `MANIFEST.json` and `CHANGES_YYYYMMDD.md` inside the zip
- Plus a rolling `CHANGELOG.md` at the **repo root** (not in the zip), prepended with each release's diff section

### 2.2 CSV schema (8 columns)

| Column         | Notes                                                                   |
| -------------- | ----------------------------------------------------------------------- |
| `topic`        | Required by RAG import. Full hierarchy: `TOPIC_PREFIX` + ` > `-joined `section_path` (document title + every ancestor heading + this item's heading). |
| `content`      | Required by RAG import. Markdown body — prose + inline tables.          |
| `heading`      | Numeric heading of this knowledge item (e.g. `9.69.1.`).                |
| `section_path` | Human-readable ancestor chain without the prefix (e.g. `第9節 抗癌瘤藥物 > 9.69. > 9.69.1.`). |
| `item_id`      | Stable across releases; the diff key (e.g. `sec9-9.69.1`).              |
| `source_file`  | Traceability (e.g. `第9節_抗癌瘤藥物_Antineoplastics_drugs_1150324.docx`). |
| `source_url`   | Traceability (e.g. `https://www.nhi.gov.tw/.../9.docx`).                |
| `update_date`  | Dual calendar (e.g. `2026/03/24 (民國115年3月24日)`).                   |

`TOPIC_PREFIX` is carried over from the predecessor verbatim:
```
臺灣全民健康保險藥品給付規定/藥品健保給付/健保規定 (Taiwan NHI) \n
```
Note the embedded newline `\n` is **literal** — the prefix ends with a line break before the breadcrumb begins.

**Worked example for one row** (the item that today is part of `第9節 / 9.69.` / row 85 — the PD-L1 cutoff sub-clause):

| Column         | Value                                                                                                                                |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `topic`        | `臺灣全民健康保險藥品給付規定/藥品健保給付/健保規定 (Taiwan NHI) \n第9節 抗癌瘤藥物 > 9.69. 免疫檢查點抑制劑 > 9.69.1. 適應症與 PD-L1 表現量對照` |
| `content`      | (Markdown: heading + prose explaining cutoff rules + the drug × indication table as a Markdown table)                                |
| `heading`      | `9.69.1.`                                                                                                                            |
| `section_path` | `第9節 抗癌瘤藥物 > 9.69. 免疫檢查點抑制劑 > 9.69.1. 適應症與 PD-L1 表現量對照`                                                       |
| `item_id`      | `sec9-9.69.1`                                                                                                                        |
| `source_file`  | `第9節_抗癌瘤藥物_Antineoplastics_drugs_1150324.docx`                                                                                |
| `source_url`   | `https://www.nhi.gov.tw/resource/.../9.docx`                                                                                         |
| `update_date`  | `2026/03/24 (民國115年3月24日)`                                                                                                      |

So `topic` always carries the **full** path — prefix + document title + every ancestor heading + this item's own heading — joined by ` > `. `section_path` is the same chain without the prefix, exposed as a separate column for filtering/grouping.

The RAG ingestion contract: it requires `topic` + `content`; any additional columns are appended as text to `content` at import time. The 6 extra columns above ride along as appended metadata.

### 2.3 Token budget — contract, not linter

- **Hard upper bound:** 7000 tokens / row (RAG import limit)
- **Target upper bound:** 6000 tokens / row (headroom for appended columns)
- **Tokenizer:** `tiktoken.cl100k_base` (consistent with the predecessor's `token_counter.py`)
- **Enforcement:** pipeline asserts at end of `chunk` that every emitted `Item.token_count ≤ 7000`. If any item exceeds, the run fails loudly with no zip produced.

## 3. Architecture

### 3.1 Five-stage layered pipeline

```
              fetch                parse               chunk              render            package
              ─────                ─────               ─────              ──────            ───────
  source_url ─────► [SourceDoc] ─────► [Document] ─────► [Item] ─────► [CsvRow] ─────► zip + CHANGES.md
                    + Manifest         tree              flat list      flat list      + CHANGELOG.md updated
```

Each stage is a module. Data types are the contracts.

### 3.2 Core types

```python
@dataclass(frozen=True)
class SourceDoc:
    path: Path             # local DOCX file
    url: str               # canonical NHI URL
    display_name: str      # from <a title=…> on the listing page
    update_date_iso: date  # parsed from the website's publish-date <time> element

@dataclass(frozen=True)
class Manifest:
    update_date_iso: date
    documents: list[SourceDoc]

@dataclass
class Document:
    source: SourceDoc
    title: str                     # e.g. "第9節 抗癌瘤藥物"
    section_number: int | None     # 9 for sections, None for 附表
    root: Node

@dataclass
class Node:
    heading: str                   # "9.69." or "9.69.1." — numeric prefix + heading text
    level: tuple[int, ...]         # (9, 69) or (9, 69, 1)
    body: list[Block]              # paragraphs/tables under this node, before any child
    children: list[Node]

Block = Paragraph | Table

@dataclass
class Paragraph:
    text: str

@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    caption: str | None

@dataclass(frozen=True)
class Item:
    item_id: str                   # e.g. "sec9-9.69.1"
    section_path: list[str]        # ["第9節 抗癌瘤藥物", "9.69.", "9.69.1."]
    heading: str
    content_md: str                # Markdown: prose + inline tables
    source: SourceDoc
    token_count: int
```

Hierarchy lives only in the tree. Downstream stages read from it; nothing reaches back.

`Node.body` is separated from `Node.children` so that prose directly under a heading (before its first child heading) stays attached to that node — fixing a subtle bug in the predecessor where this content gets misattributed.

### 3.3 `item_id` naming rules

- Regular node: `sec{N}-{numeric_heading}` → `sec9-9.69.1`
- Appendix: `appendix-{slug}` → `appendix-表14_DMARDs`
- Leaf split into parts: original ID + `-part1`, `-part2`, ...
- Preamble (node's own body emitted separately from its children): original ID + `-preamble`
- Oversize table split by rows: original ID + `-tbl1`, `-tbl2`, ...

IDs are **deterministic** — same input always produces the same ID. This is what lets the differ align items across releases.

## 4. Chunker algorithm (the heart of the design)

### 4.1 Main descent

```python
def chunk(node: Node, ancestors: list[Node]) -> list[Item]:
    rendered = render_subtree_to_markdown(node)
    if count_tokens(rendered) <= TARGET_BUDGET:
        return [emit_item(node, ancestors, rendered)]

    # Over budget → descend
    if node.children:
        items = []
        if has_significant_body(node):
            items.append(emit_item_for_body_only(node, ancestors))
        for child in node.children:
            items.extend(chunk(child, ancestors + [node]))
        return items

    # Leaf still over budget → semantic split
    return split_leaf(node, ancestors)
```

### 4.2 Leaf-split priority (least structural damage first)

When a leaf node alone exceeds the budget:

1. **Split at numbered list items.** Find `^\d+\.` list items (e.g. `1.`, `2.`, `3.` under a 條). Each item becomes one chunk, with the leaf's heading prepended so retrieval still has context.
2. **Split by paragraph.** Accumulate paragraphs until close to budget, then break.
3. **Tables are atomic.** Steps 1 and 2 treat any `Table` block as an indivisible unit. A table travels in one chunk with surrounding prose if it fits, or alone if not.
4. **Oversize-table split (last resort).** If a single table exceeds the target budget, split by rows: each chunk keeps the header + N data rows. ID suffix `-tbl1`, `-tbl2`, ...

### 4.3 `has_significant_body` rule

For a node with both `body` and `children`:

- **No body:** pure section heading (e.g. "9. 抗癌瘤藥物" with children only). Don't emit an item; the node contributes only to descendants' `section_path`.
- **Trivial body** (≤ 200 tokens, no tables, single paragraph): prepend to first child's content as context. No standalone item.
- **Significant body** (multiple paragraphs, contains a table, or > 200 tokens): emit a standalone item with `item_id` + `-preamble` suffix.

This eliminates the predecessor's `"General Information"` and `"Additional Information"` dummy-regulation fallbacks.

### 4.4 Hard non-goals

- **No sibling merging.** Even if two adjacent leaves are each small, never combine them into one row. Preserves `item_id` stability and keeps the data model simple.
- **No sentence-level splitting.** If a single paragraph exceeds the target budget (rare), accept an item slightly above target but below hard limit. Avoids Chinese sentence-boundary edge cases.

## 5. Other stages

### 5.1 `fetch`

Adapted from the predecessor's `WebScraper`. Changes:
- `ODT_LINK_PATTERN` → `.*\.docx` (NHI publishes both; we pick DOCX).
- `UPDATE_DATE_SELECTOR` unchanged.
- Returns a `Manifest` value (release's `update_date_iso` + `list[SourceDoc]`) instead of writing-then-scanning a directory.
- `cloudscraper` session, ROC date parsing, contextual filename generation all preserved.

### 5.2 `parse`

`DocxFile → Document`. Walks `python-docx`'s `document.element.body` in document order, dispatching on element type:
- `Paragraph` → check its style (`paragraph.style.name`) and/or its leading numeric prefix to determine heading vs. body
- `Table` → convert to `Table` block (header row + data rows)

Heading detection strategy: **prefer style metadata** (`Heading 1`, `Heading 2`, etc. when the DOCX has them), **fall back to numeric-prefix regex** (`^\d+(\.\d+)*\.?`) when styles are missing or unreliable. NHI documents in practice may use either approach inconsistently — the parser handles both.

Output: `Document` with a complete `Node` tree, including embedded `Table` blocks attached to the correct node's `body`.

### 5.3 `render`

Pure function `Item → dict[str, str]`. No logic, just field mapping per §2.2. Writes CSVs with `csv.DictWriter`, `utf-8-sig` BOM (so Excel opens them correctly).

```python
def render(item: Item) -> dict[str, str]:
    return {
        "topic": TOPIC_PREFIX + " > ".join(item.section_path),
        "content": item.content_md,
        "heading": item.heading,
        "section_path": " > ".join(item.section_path),
        "item_id": item.item_id,
        "source_file": item.source.path.name,
        "source_url": item.source.url,
        "update_date": format_dual_calendar(item.source.update_date_iso),
    }
```

### 5.4 `package`

1. Group `CsvRow`s by `source.path.name` → one CSV per source DOCX
2. Write all CSVs into `data/regulations/medication/藥品給付規定_{YYYYMMDD}/`
3. Generate `MANIFEST.json` inside that folder:
   ```json
   {
     "release_date": "2026-05-21",
     "items": [
       {"item_id": "sec9-9.69.1", "source_file": "...", "token_count": 4821, "content_sha256": "..."},
       ...
     ]
   }
   ```
4. Run `diff` against most recent prior release; write `CHANGES_YYYYMMDD.md` into the folder
5. Prepend that diff section to `CHANGELOG.md` at repo root
6. Zip the folder → `data/regulations/medication/藥品給付規定_{YYYYMMDD}.zip`

`MANIFEST.json` stores hashes + summary only, never full content — avoids becoming a second source of truth.

### 5.5 `diff`

Inputs: two `MANIFEST.json` files (old, new). Compare `item_id` sets:
- **Added:** in new, not in old
- **Removed:** in old, not in new
- **Modified:** in both, but `content_sha256` differs

Emit a Markdown report:

```markdown
## [YYYYMMDD] — YYYY/MM/DD（民國YYY年M月D日）
**Source manifest:** N documents, M items emitted, max token count K.

### Added
- `sec9-9.71` — 第9節 > 9.71. 標靶治療藥物

### Modified
- `sec9-9.69.1` — 第9節 > 9.69. > 9.69.1.

### Removed
- `sec3-3.4.2`
```

First-ever run (no prior release): emit only an `Added` section with header `**Initial release.**`.

## 6. CHANGELOG.md (rolling release history)

Location: `CHANGELOG.md` at the **repo root** — repo-local, not in the zip.

Format: [Keep a Changelog](https://keepachangelog.com/) style. Each release's diff section is **prepended** to the top of the file by `package`:

```markdown
# Changelog

## [20260521] — 2026/05/21（民國115年5月21日）
**Source manifest:** 47 documents, 312 items emitted, max token count 4 821.

### Added
- `sec9-9.71` — 第9節 > 9.71. 標靶治療藥物

### Modified
- `sec9-9.69.1` — 第9節 > 9.69. > 9.69.1.

### Removed
- `sec3-3.4.2`

## [20260424] — 2026/04/24（民國115年4月24日）
…
```

`MANIFEST.json` is the differ's source of truth; `CHANGELOG.md` is a human-readable derivative the pipeline maintains automatically.

## 7. Repo layout

```
nhi-knowledge-extractor/
├── pyproject.toml              # uv-managed (consistent with other projects)
├── README.md
├── CLAUDE.md
├── CHANGELOG.md                # rolling release history (auto-maintained by package stage)
├── src/nhi_extractor/
│   ├── __init__.py
│   ├── cli.py                  # CLI entry (Typer or argparse)
│   ├── config.py               # SOURCE_URL, TOPIC_PREFIX, budgets, paths
│   ├── types.py                # SourceDoc, Manifest, Document, Node, Block, Item
│   ├── fetch.py                # NHI scraper
│   ├── parse.py                # DOCX → Document
│   ├── chunk.py                # Document → [Item]
│   ├── render.py               # Item → CsvRow
│   ├── package.py              # CSVs → dated folder → zip; updates CHANGELOG.md
│   ├── diff.py                 # MANIFEST.json comparison
│   └── markdown.py             # render_subtree_to_markdown, table → md helper
├── tests/
│   ├── fixtures/               # real DOCX samples from past releases
│   │   ├── 第8節_免疫製劑_*.docx
│   │   ├── 第9節_抗癌瘤藥物_*.docx     # ← contains the row-85 table
│   │   └── 第3節_代謝及營養劑_*.docx    # a "normal" case
│   ├── test_parse.py
│   ├── test_chunk.py
│   ├── test_chunk_pain_cases.py
│   ├── test_render.py
│   └── test_diff.py
└── data/regulations/medication/  # release outputs (carry over from predecessor)
```

One module per stage, one test file per module.

## 8. CLI surface

```bash
nhi-extract sync                       # full pipeline (happy path)
nhi-extract sync --skip-fetch          # use already-downloaded DOCX (debug)
nhi-extract sync --dry-run             # build everything, print stats + CHANGES preview, write nothing
nhi-extract parse <docx>               # single-file debug: print Document tree
nhi-extract chunk <docx>               # single-file debug: print items + token counts
nhi-extract diff <release_dir_a> <release_dir_b>   # arbitrary diff
```

## 9. Testing strategy

Three layers:

### 9.1 Unit tests (per module, < 200 lines each)

- `test_parse.py` — fixture DOCX → assert tree structure, table extraction
- `test_render.py` — `Item` → assert all 8 columns mapped correctly
- `test_diff.py` — hand-built manifests → assert add/remove/modify classification

### 9.2 Pain-case regression tests (the reason this repo exists)

- `test_chunk_pain_cases.py::test_section8_row13_no_overflow`
  Fixture: `第8節_免疫製劑_*.docx`. Assert: no item exceeds 7000 tokens. Assert: the `8.2.4.` Etanercept regulation is emitted as more than one item (i.e. the chunker descended past `8.2.4.` into its sub-clauses or numbered list items, rather than producing one oversize row).

- `test_chunk_pain_cases.py::test_section9_row85_table_preserved`
  Fixture: `第9節_抗癌瘤藥物_*.docx`. Assert: no item exceeds 7000 tokens. Assert: the `9.69.` drug × indication table appears in some item's `content_md` as a Markdown table containing the columns `pembrolizumab`, `nivolumab`, `atezolizumab` and rows including `黑色素瘤`.

### 9.3 Budget contract property test

`test_chunk.py::test_all_fixtures_fit_budget` — for every DOCX in `tests/fixtures/`:
- chunker runs without exception
- every item `token_count ≤ 7000`
- all `item_id`s are unique

Run on CI / pre-commit.

Fixtures are pulled directly from past releases (the predecessor's `data/regulations/medication/chapters/` already has them). No mocking.

## 10. Carry-over and discards from predecessor

### Carry over
- `TOPIC_PREFIX` value and purpose
- Dated-zip delivery convention (`藥品給付規定_YYYYMMDD.zip`)
- `WebScraper` CSS selector + ROC date parsing
- Selected historical DOCX/ODT files from `chapters/` — copied into `tests/fixtures/` (not into the new repo's `data/`, which starts empty)

### Discard
- `csv_splitter.py` — its existence is the bug
- 4-level heading rejection in `_parse_heading_level`
- `_get_text_from_element` (which flattens table cells into paragraph text)
- Flat `(topic, content, reference)` as source of truth
- Dummy-regulation fallbacks (`"Empty document content"`, `"Additional Information"`)
- `.venv` + `requirements.txt` → replaced by `uv` + `pyproject.toml`

## 11. Open items deferred to implementation

These need answers but don't block design approval:

1. **CLI library choice — decision below.**

   Three realistic options:

   | Option         | Install                    | Style                                            | Pros                                                                                                  | Cons                                                                                          |
   | -------------- | -------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
   | **`argparse`** | stdlib (zero install)      | Manual: define parser, add args, dispatch yourself | Zero dependency; familiar; matches the predecessor; works forever                                     | Verbose for sub-commands; help output is plain; you wire dispatch by hand                     |
   | **Click**      | `pip install click`        | Decorator-based: `@click.command()`, `@click.option()` | Mature (used by Flask, Black, pip-tools, etc.); great sub-command support; colourful help; battle-tested | Decorator-heavy; type annotations aren't the source of truth (you re-declare types in options) |
   | **Typer**      | `pip install typer`        | Type-hint-based: function signature *is* the CLI  | Modern; sub-commands via nested functions; rich/coloured help; auto shell completion; very little boilerplate; type hints drive parsing and help text | Newer (smaller community than Click); pulls Click + Rich as transitive deps                   |

   Concrete `sync` command in each:

   *argparse:*
   ```python
   p = argparse.ArgumentParser()
   sub = p.add_subparsers(dest="cmd")
   sync = sub.add_parser("sync")
   sync.add_argument("--skip-fetch", action="store_true")
   sync.add_argument("--dry-run", action="store_true")
   args = p.parse_args()
   if args.cmd == "sync": run_sync(skip_fetch=args.skip_fetch, dry_run=args.dry_run)
   ```

   *Click:*
   ```python
   @click.group()
   def cli(): pass
   @cli.command()
   @click.option("--skip-fetch", is_flag=True)
   @click.option("--dry-run", is_flag=True)
   def sync(skip_fetch: bool, dry_run: bool):
       run_sync(skip_fetch=skip_fetch, dry_run=dry_run)
   ```

   *Typer:*
   ```python
   app = typer.Typer()
   @app.command()
   def sync(skip_fetch: bool = False, dry_run: bool = False):
       run_sync(skip_fetch=skip_fetch, dry_run=dry_run)
   ```

   **Recommendation: Typer.** This repo's CLI is small (6 commands) and the function signatures already express what each command takes. Typer lets the type hints *be* the spec — no duplication, less code to maintain, nicer help output for free. The extra dependency is two well-maintained packages (Click + Rich), both already used widely in the Python ecosystem. argparse would work but adds boilerplate that obscures the actual logic; Click is fine but Typer is Click with less ceremony.

   If you'd rather keep zero non-stdlib CLI deps, fall back to **argparse**. Don't pick Click — Typer dominates it for this size of CLI.
2. **NHI DOCX style reliability:** Investigate whether NHI uses Word's "Heading N" styles or just bold-numbered paragraphs. Affects `parse.py` priority order. If unreliable, the numeric-prefix regex fallback handles it — no design change.
3. **Initial fixture set:** Pick 3–5 DOCX files from past releases to include in `tests/fixtures/`. Must include `第8節_免疫製劑` and `第9節_抗癌瘤藥物` versions known to contain the pain cases.
4. **Migration of historical data:** **Decided — fresh `data/` directory.** The successor starts clean; the first `nhi-extract sync` run produces the inaugural release, and its `CHANGES_YYYYMMDD.md` will be an "Initial release" report. No carry-over of old release zips. The predecessor's `chapters/` (DOCX/ODT files) are *separately* copied into `tests/fixtures/` for regression tests, but they do not populate the new `data/`.
5. **Appendix slug rule:** `appendix-{slug}` ID format (§3.3). The slug must be derived deterministically from the appendix's source filename or document title. Concrete rule (e.g. strip ROC date suffix, drop section markers, sanitize) to be locked during implementation against the actual appendix file inventory.

## 12. Success criteria

A release run with `nhi-extract sync` is successful when:

1. ✅ Zero manual interventions required
2. ✅ Every emitted item is ≤ 7000 tokens
3. ✅ The `第9節 / 9.69.` table appears as Markdown in some item's content
4. ✅ `CHANGES_YYYYMMDD.md` lists item-level adds/removes/modifies vs. last release
5. ✅ `CHANGELOG.md` has a new section prepended
6. ✅ Zip is produced and ready to deliver
