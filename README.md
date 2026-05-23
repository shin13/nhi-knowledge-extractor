# nhi-knowledge-extractor

Convert Taiwan NHI (National Health Insurance) medication regulation DOCX documents from <https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html> into RAG-ingestion-ready CSV deliverables.

Successor to `NHI-Knowledge-Extraction`. The design and rationale are in [`docs/spec.md`](docs/spec.md).

## Why

The predecessor required two manual interventions every release: re-splitting `第8節` row 13 with `csv_splitter.py`, and a Google Docs / Markdown / LLM roundtrip to recover the embedded table in `第9節` row 85. Both are caused by the same root issue — heading-based splitting that flattens hierarchy and a parser that can't see tables. This repo replaces the pipeline with a variable-depth chunker that enforces the token budget as a contract, plus a DOCX parser that reads tables natively.

## Quickstart

```bash
uv sync
uv run nhi-extract sync     # full pipeline: fetch → parse → chunk → render → package
```

Output: `data/regulations/medication/藥品給付規定_YYYYMMDD.zip` plus a release entry prepended to `CHANGELOG.md`.

## Output schema

Each CSV row is one RAG-ingestion-ready chunk. Columns:

| Column | Description |
|---|---|
| `topic` | Fixed prefix `臺灣全民健康保險藥品給付規定/…` + section_path breadcrumb |
| `content` | Markdown content of the chunk |
| `heading` | This chunk's heading (with numbering) |
| `section_path` | `>`-joined chain from doc title to this heading |
| `item_id` | Unique stable id; diff key across releases. Format `sec{N}-{level}[-partK[-M]]` |
| `parent_id` | Logical-unit id. Equals `item_id` when not split; all rows of a split share this |
| `part_index` | 1-based position within `parent_id` group |
| `total_parts` | Count of rows sharing this `parent_id` |
| `source_file` | NHI source DOCX/ODT filename |
| `source_url` | NHI download URL |
| `update_date` | Release date in both Western and ROC calendars |

### RAG hydration pattern

When a retrieved row has `total_parts > 1`, hydrate every row with the same
`parent_id` to recover the complete logical unit before sending to the LLM.
Mirrors LangChain's `ParentDocumentRetriever` and LlamaIndex's
`AutoMergingRetriever`.

Example: query for "免疫檢查點抑制劑使用條件" retrieves `sec9-9.69-part3-1`.
Hydrate `part1`, `part2`, `part3-2`, `part4` (all `parent_id=sec9-9.69`) to
get the full 9.69 regulation as context.

## EMIT_DEPTH — granularity control

`EMIT_DEPTH` (default `5`) is the minimum tree depth at which a node may
emit as a single row. Below this depth the chunker MUST descend, even if
the whole subtree would fit `TARGET_BUDGET`. This decouples editorial
intent ("what's a row?") from the embedding-model ceiling.

NHI numbering varies across sections:
- 第九節 9.70 Pertuzumab → `level=(9,70)`, depth 2 = drug level
- 第四節 4.1.2.1 短效型 G-CSF → `level=(4,1,2,1)`, depth 4 = drug level

Default 5 covers the deepest natural NHI level (款 in 第五節/第八節).
Setting higher (6+) has no effect because no nodes go that deep. Setting
lower (3, 4) deliberately merges multiple drugs into one row in some
sections — use only when you want coarser chunks.

Override per-run:

```bash
uv run nhi-extract sync --emit-depth 4
uv run nhi-extract chunk path/to/doc.docx --emit-depth 3
```

## Docs

- [`docs/intent.md`](docs/intent.md) — original problem & failure modes
- [`docs/spec.md`](docs/spec.md) — full design (pipeline, types, chunker algorithm, schema)
- [`docs/next-fixes.md`](docs/next-fixes.md) — known issues + planned fixes
- [`CLAUDE.md`](CLAUDE.md) — command reference, layout, conventions, lessons learned

## License

MIT — see [`LICENSE`](LICENSE).
