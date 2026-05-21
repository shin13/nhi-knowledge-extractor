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

## Docs

- [`docs/intent.md`](docs/intent.md) — original problem & failure modes
- [`docs/spec.md`](docs/spec.md) — full design (pipeline, types, chunker algorithm, schema)
- [`docs/next-fixes.md`](docs/next-fixes.md) — known issues + planned fixes
- [`CLAUDE.md`](CLAUDE.md) — command reference, layout, conventions, lessons learned

## License

MIT — see [`LICENSE`](LICENSE).
