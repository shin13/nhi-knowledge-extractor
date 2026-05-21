# nhi-knowledge-extractor

Convert Taiwan NHI medication regulation DOCX documents into RAG-ingestion-ready CSV deliverables. Successor to `NHI-Knowledge-Extraction`. See `docs/spec.md`.

## Environment

- Python 3.13+, managed with `uv`
- Install: `uv sync`

## Commands

```bash
uv run nhi-extract sync                  # full pipeline
uv run nhi-extract sync --skip-fetch     # use local DOCX
uv run nhi-extract sync --dry-run        # build, print stats, write nothing
uv run nhi-extract parse <docx>          # debug: print tree
uv run nhi-extract chunk <docx>          # debug: print emitted items + tokens
uv run nhi-extract diff <dir_a> <dir_b>  # diff two release folders
```

## Layout

```
src/nhi_extractor/
  cli.py        Typer entry
  config.py     constants (TOPIC_PREFIX, budgets, paths)
  types.py      dataclasses (SourceDoc, Document, Node, Item, ...)
  fetch.py      NHI scraper → Manifest
  parse.py      DOCX → Document tree (python-docx)
  chunk.py      Document → [Item] (variable depth, budget contract)
  render.py     Item → CSV row (8 cols)
  diff.py       MANIFEST.json comparison
  package.py    CSVs + MANIFEST + CHANGES + CHANGELOG + zip
  markdown.py   table_to_markdown, render_node_to_markdown, count_tokens
tests/
  fixtures/     real DOCX from past NHI releases (gitignored if large)
  test_*.py     one file per module + test_chunk_pain_cases.py
data/regulations/medication/    release outputs (gitignored)
CHANGELOG.md                     rolling release history (auto-maintained)
```

## Conventions

- All paths and tunables in `src/nhi_extractor/config.py`. Do not hardcode elsewhere.
- The chunker's token budget is a **contract**: any item over `HARD_BUDGET` (7000) raises in `chunk_document`. Don't catch and ignore.
- New stages get a new module + a new `tests/test_<module>.py`. One responsibility per file.
- TDD: write the failing test first. The pain-case tests in `tests/test_chunk_pain_cases.py` are the regression net — never disable them.

## Pain cases the predecessor required manual fixes for (now automated)

- `第8節 row 13` (Etanercept) — over-budget; was hand-split with `csv_splitter.py`. Now handled by `chunk._chunk_node` descent + `split_leaf` numbered-list split.
- `第9節 row 85` (immune checkpoint inhibitors PD-L1 table) — over-budget AND contained an embedded matrix table. Was a Google Docs roundtrip. Now: `parse.py` reads `<w:tbl>` directly, `markdown.table_to_markdown` renders it, the chunker keeps it atomic.

## Running tests

```bash
uv run pytest                                       # all
uv run pytest tests/test_chunk_pain_cases.py -v     # the regression net
```
