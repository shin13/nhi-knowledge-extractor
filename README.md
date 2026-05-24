# nhi-knowledge-extractor

Convert Taiwan NHI medication regulation documents — <https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html> — into RAG-ingestion-ready CSVs.

Successor to `NHI-Knowledge-Extraction`. Design rationale in [`docs/spec.md`](docs/spec.md).

## Why

The predecessor needed two manual fix-ups per release: hand-splitting `第8節` row 13 with `csv_splitter.py`, and a Google Docs → Markdown → LLM roundtrip for `第9節` row 85's embedded table. Both came from the same root cause — heading-based splitting flattens hierarchy, and the parser couldn't see tables.

This pipeline replaces both with a variable-depth chunker (token budget as a **contract**), a parser that reads DOCX/ODT tables natively, and explicit `EMIT_DEPTH` granularity so RAG row shape doesn't drift when you swap embedding models.

## Quickstart

```bash
git clone https://github.com/shin13/nhi-knowledge-extractor.git
cd nhi-knowledge-extractor
uv sync
uv run nhi-extract sync   # fetch → parse → chunk → render → package
```

Output:

```
Fetched: 16 documents, release date 2026-04-24
Skipped 76 (75 appendix_form, 1 unrecognized_title) — see MANIFEST.json
  通則_113.05.28更新_1150424.odt: 1 items
  第一節_神經系統藥物_115.3.23更新_1150424.docx: 49 items
  ...
  第九節_抗癌瘤藥物_115.4.23更新_1150424.docx: 146 items
Total: 543 items, max token count 5992
Wrote: data/regulations/medication/藥品給付規定_20260424.zip
```

Each release zip contains one CSV per chapter, plus `MANIFEST.json` and `CHANGES_YYYYMMDD.md`.

### Other commands

```bash
uv run nhi-extract sync --skip-fetch       # use already-downloaded chapters/
uv run nhi-extract sync --dry-run          # build + print stats, don't write zip
uv run nhi-extract sync --emit-depth 4     # coarser chunks (default 5)
uv run nhi-extract parse <doc>             # debug: print parsed tree
uv run nhi-extract chunk <doc>             # debug: print emitted items
uv run nhi-extract diff <dir_a> <dir_b>    # diff two release folders
```

## Output schema

11 columns per CSV row. Full schema reference: [`docs/spec.md`](docs/spec.md) §2.2 (canonical).

At a glance, each row carries: identifiers (`item_id`, `parent_id`, `part_index`, `total_parts`), content (`content`, `heading`, `topic`, `section_path`), and traceability (`source_file`, `source_url`, `update_date`).

### Worked example — split row family

`sec9-9.69` (immune-checkpoint inhibitors) exceeds the 7000-token hard budget, so it splits into 5 rows:

| item_id | parent_id | part_index | total_parts | content (truncated) |
|---|---|---|---|---|
| `sec9-9.69-part1` | `sec9-9.69` | 1 | 5 | `## 9.69. … 1. 本類藥品得 …` |
| `sec9-9.69-part2` | `sec9-9.69` | 2 | 5 | `## 9.69. … 2. 本類藥品得併用 …` |
| `sec9-9.69-part3-1` | `sec9-9.69` | 3 | 5 | `## 9.69. … 3. 使用條件：…` |
| `sec9-9.69-part3-2` | `sec9-9.69` | 4 | 5 | `## 9.69. … 3. 使用條件（續）：II. …` |
| `sec9-9.69-part4` | `sec9-9.69` | 5 | 5 | `## 9.69. … 4. 登錄與結案 …` |

### RAG hydration pattern

When a retrieved row has `total_parts > 1`, fetch every row with the same `parent_id` and concatenate before sending to the LLM (the LangChain `ParentDocumentRetriever` / LlamaIndex `AutoMergingRetriever` pattern).

Without hydration, "Pembrolizumab usage conditions" gets only the part containing `使用條件` and misses the indications in `part1`.

## EMIT_DEPTH — granularity knob

`EMIT_DEPTH` (default `5`) is the minimum tree depth at which a node may emit as a single row. Below this depth the chunker **must** descend, even if the subtree fits `TARGET_BUDGET`. Decouples editorial intent ("what's a row?") from embedding ceiling.

NHI numbering varies by chapter:
- 第九節 `9.70 Pertuzumab` → `level=(9,70)`, depth 2 = drug level
- 第四節 `4.1.2.1 短效型 G-CSF` → `level=(4,1,2,1)`, depth 4 = drug level

Default 5 covers the deepest natural NHI level (款 in 第五節/第八節). Higher has no effect; lower (3, 4) merges drugs into one row — use only when you want coarser chunks.

## Docs

- [`docs/intent.md`](docs/intent.md) — original problem & failure modes
- [`docs/spec.md`](docs/spec.md) — full design (pipeline, types, chunker, schema)
- [`docs/emit-depth-plan.md`](docs/emit-depth-plan.md) — `EMIT_DEPTH` + RAG metadata + anchor preamble rationale
- [`docs/roadmap.md`](docs/roadmap.md) — future plan (P0–P6)
- [`docs/next-fixes.md`](docs/next-fixes.md) — open issues (Task G — 附表 forms)
- [`CLAUDE.md`](CLAUDE.md) — commands, layout, conventions, lessons

## Issues & Feedback

Bug reports, questions about output behaviour, or schema-related discussion: **[open an issue](https://github.com/shin13/nhi-knowledge-extractor/issues/new/choose)**. A bug-report template guides you through the fields that help reproduce the problem (NHI release date, pipeline version, the source filename involved).

For private matters (commercial use, security disclosure), reach the maintainer through their GitHub profile: <https://github.com/shin13>.

## License

MIT — see [`LICENSE`](LICENSE).

---

## 中文使用說明

把健保署「藥品給付規定」的 DOCX / ODT 文件自動轉成可直接給 RAG 使用的 CSV，省去人工切欄、補表格、對版本的功夫。

### 安裝與執行

```bash
git clone https://github.com/shin13/nhi-knowledge-extractor.git
cd nhi-knowledge-extractor
uv sync
uv run nhi-extract sync
```

跑完會在 `data/regulations/medication/` 下產生一個 zip，內含每節一份 CSV、`MANIFEST.json`、以及本次 release 的變動清單。下次健保署有新版本時再跑一次 `sync`，工具會自動抓新檔、產出新版 zip，並列出新增、修改、移除的條目。

### CSV 怎麼用

每一列就是一個給 RAG embedder 用的 chunk，直接整份餵下去即可。實務上會用到的欄位：

- `content` — 規定本文（Markdown 格式，包含表格）
- `item_id` — 條目的穩定 ID，可拿來做版本 diff
- `parent_id` / `part_index` / `total_parts` — 同一條規定被切成多列時的關聯欄位

### 重要：RAG 端要做 hydration

當檢索命中的列 `total_parts > 1`，代表這條規定（例如免疫檢查點抑制劑 `sec9-9.69`）因為太長被切成數列。請把同 `parent_id` 的所有列**一起撈出來組合**，再餵給 LLM。

不這麼做的話 LLM 只會看到片段：問「Pembrolizumab 的使用條件」時只看到「使用條件」那段，看不到 part1 的適應症列表，回答會殘缺。

對應的是 LangChain `ParentDocumentRetriever` / LlamaIndex `AutoMergingRetriever` 那一類 pattern。

### 常用指令

```bash
uv run nhi-extract sync --skip-fetch     # 用已下載的檔案，不重抓
uv run nhi-extract sync --dry-run        # 跑流程印統計，不寫 zip
uv run nhi-extract sync --emit-depth 4   # 較粗粒度切塊
uv run nhi-extract diff <舊版> <新版>     # 比對兩次 release 的差異
```

`diff` 範例 — 比對兩次 release 看健保署這次改了什麼：

```bash
uv run nhi-extract diff \
  data/regulations/medication/藥品給付規定_20260301 \
  data/regulations/medication/藥品給付規定_20260424
```

輸出會分三段列出 `item_id`：

```
Added:    1
  + sec9-9.71
Modified: 1
  ~ sec2-2.5
Removed:  1
  - sec5-5.3
```

拿到清單後再去對應的 CSV 找該 `item_id` 看實際內容變動，或交給下游做版本更新通知。

### 想調切塊粒度？

`EMIT_DEPTH`（預設 5）控制「一個 row 應該切到第幾層」。預設值對應 NHI 文件最深的「款」層，確保每條藥品規定獨立成列、不會跟相鄰藥物的規定混在同一列。

若想要較粗粒度（例如以節為單位）可改用 `--emit-depth 3` 或 `4`，但要注意：合併後一列會包含多個藥物的規定，RAG 檢索時的相關性會跟著下降。

### 問題回報

遇到 bug、輸出結果不如預期、或對 schema 有疑問：請到 **[GitHub Issues](https://github.com/shin13/nhi-knowledge-extractor/issues/new/choose)** 開單。會有 bug 回報範本引導你填關鍵欄位（NHI release 日期、工具版本、出問題的檔名），這些資訊對重現問題很關鍵。

不適合公開的事項（商用授權詢問、資安通報等）：可透過維護者的 GitHub profile 聯絡：<https://github.com/shin13>。
