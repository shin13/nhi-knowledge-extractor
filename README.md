# nhi-knowledge-extractor

> 🇹🇼 **繁體中文說明見下方** → [跳至中文說明](#中文說明)

Convert Taiwan NHI (National Health Insurance) medication regulation documents from <https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html> into RAG-ingestion-ready CSV deliverables.

Successor to `NHI-Knowledge-Extraction`. Full design rationale in [`docs/spec.md`](docs/spec.md).

## Why

The predecessor required two manual fix-ups every release: re-splitting `第8節` row 13 with a separate `csv_splitter.py`, and a Google Docs → Markdown → LLM roundtrip to recover the embedded table in `第9節` row 85. Both stemmed from the same root cause — heading-based splitting flattens hierarchy, and the predecessor's parser couldn't see tables.

This pipeline replaces both with a variable-depth chunker that enforces token budget as a contract, a DOCX/ODT parser that reads tables natively, and explicit `EMIT_DEPTH` granularity control so RAG row shape doesn't drift when you change embedding models.

## Quickstart

```bash
# 1. Install
git clone https://github.com/shin13/nhi-knowledge-extractor.git
cd nhi-knowledge-extractor
uv sync

# 2. Run the full pipeline (fetch → parse → chunk → render → package)
uv run nhi-extract sync
```

Expected output:

```
Fetched: 16 documents, release date 2026-04-24
Skipped 76 (75 appendix_form, 1 unrecognized_title) — see MANIFEST.json
  通則_113.05.28更新_1150424.odt: 1 items
  第一節_神經系統藥物_115.3.23更新_1150424.docx: 49 items
  第二節_心臟血管及腎臟藥物_115.4.23更新_1150424.docx: 61 items
  ...
  第九節_抗癌瘤藥物_115.4.23更新_1150424.docx: 146 items
  ...
Total: 543 items, max token count 5992
Wrote: data/regulations/medication/藥品給付規定_20260424.zip
Diff vs prior: +543 / ~0 / -0
```

A release zip contains one CSV per chapter plus `MANIFEST.json` and `CHANGES_YYYYMMDD.md`. Each CSV row is one RAG-ingestion-ready chunk:

| item_id            | parent_id   | part_index | total_parts | heading                              | content (truncated)                |
|--------------------|-------------|------------|-------------|--------------------------------------|------------------------------------|
| `sec9-9.69-part1`  | `sec9-9.69` | 1          | 5           | 9.69. 免疫檢查點抑制劑 (atezolizumab; …) | `## 9.69. … 1. 本類藥品得 …`        |
| `sec9-9.69-part2`  | `sec9-9.69` | 2          | 5           | 9.69. 免疫檢查點抑制劑 (atezolizumab; …) | `## 9.69. … 2. 本類藥品得併用 …`     |
| `sec9-9.69-part3-1`| `sec9-9.69` | 3          | 5           | 9.69. 免疫檢查點抑制劑 (atezolizumab; …) | `## 9.69. … 3. 使用條件：…`         |
| `sec9-9.69-part3-2`| `sec9-9.69` | 4          | 5           | 9.69. 免疫檢查點抑制劑 (atezolizumab; …) | `## 9.69. … 3. 使用條件（續）：II. …` |
| `sec9-9.69-part4`  | `sec9-9.69` | 5          | 5           | 9.69. 免疫檢查點抑制劑 (atezolizumab; …) | `## 9.69. … 4. 登錄與結案 …`        |

All five rows share `parent_id=sec9-9.69` because they're parts of the same logical regulation; an RAG retriever that hits any one should hydrate all five.

### Other commands

```bash
uv run nhi-extract sync --skip-fetch       # use already-downloaded chapters/
uv run nhi-extract sync --dry-run          # build + print stats, don't write zip
uv run nhi-extract sync --emit-depth 4     # coarser chunks (default is 5)
uv run nhi-extract parse <doc.docx>        # debug: print parsed tree
uv run nhi-extract chunk <doc.docx>        # debug: print emitted items
uv run nhi-extract diff <dir_a> <dir_b>    # diff two release folders
```

## Output schema (11 columns)

| Column         | Description |
|----------------|-------------|
| `topic`        | RAG-required prefix + full breadcrumb (`臺灣全民健康保險藥品給付規定/…`) |
| `content`      | Markdown body — prose + inline tables |
| `heading`      | This chunk's heading with numbering |
| `section_path` | Title chain from document root to this heading, ` > `-joined |
| `item_id`      | Unique stable id (diff key) — `sec{N}-{level}[-partK[-M]]` |
| `parent_id`    | Logical-unit id; equals `item_id` when not split; siblings of a split share it |
| `part_index`   | 1-based position within `parent_id` group |
| `total_parts`  | Count of rows sharing this `parent_id` |
| `source_file`  | NHI source filename |
| `source_url`   | NHI download URL |
| `update_date`  | Dual calendar (`2026/04/24 (民國115年4月24日)`) |

### RAG hydration pattern

When a retrieved row has `total_parts > 1`, fetch every row with the same
`parent_id` and concatenate them before sending to the LLM. This mirrors
LangChain's `ParentDocumentRetriever` and LlamaIndex's `AutoMergingRetriever`.

The example above — `sec9-9.69` immune-checkpoint inhibitor regulation — is
split into 5 parts because the full text exceeds the 7000-token hard budget.
Without hydration, an LLM answering "Pembrolizumab usage conditions" gets
only the part containing `使用條件` and misses the indications in `part1`.

## EMIT_DEPTH — granularity control

`EMIT_DEPTH` (default `5`) is the minimum tree depth at which a node may emit
as a single row. Below this depth the chunker MUST descend, even if the whole
subtree fits `TARGET_BUDGET`. This decouples editorial intent ("what's a row?")
from the embedding-model ceiling.

NHI numbering varies across sections:
- 第九節 9.70 Pertuzumab → `level=(9,70)`, depth 2 = drug level
- 第四節 4.1.2.1 短效型 G-CSF → `level=(4,1,2,1)`, depth 4 = drug level

Default 5 covers the deepest natural NHI level (款 in 第五節/第八節). Setting
higher (6+) has no effect because no nodes go that deep. Setting lower (3, 4)
deliberately merges multiple drugs into one row in some sections — use only
when you explicitly want coarser chunks.

Override per-run:

```bash
uv run nhi-extract sync --emit-depth 4
uv run nhi-extract chunk path/to/doc.docx --emit-depth 3
```

## Docs

- [`docs/intent.md`](docs/intent.md) — original problem & failure modes
- [`docs/spec.md`](docs/spec.md) — full design (pipeline, types, chunker algorithm, schema)
- [`docs/emit-depth-plan.md`](docs/emit-depth-plan.md) — design rationale for `EMIT_DEPTH` + RAG metadata + anchor preamble
- [`docs/roadmap.md`](docs/roadmap.md) — future plan (P0–P6)
- [`docs/next-fixes.md`](docs/next-fixes.md) — open issues (Task G — appendix forms)
- [`CLAUDE.md`](CLAUDE.md) — command reference, layout, conventions, lessons learned

## License

MIT — see [`LICENSE`](LICENSE).

---

# 中文說明

將 [全民健康保險藥品給付規定](https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html) 的 DOCX / ODT 文件轉成 RAG 攝取用的 CSV 套件。

`NHI-Knowledge-Extraction` 的後繼專案。完整設計記在 [`docs/spec.md`](docs/spec.md)。

## 為什麼存在

前一代專案每次釋出都要人工修兩個地方：用獨立的 `csv_splitter.py` 重切 `第8節` 第 13 列、走 Google Docs → Markdown → LLM 來救 `第9節` 第 85 列裡那張嵌入表格。兩者根因相同 —— **以標題為界切分** 會把階層壓平，加上前一代 parser 看不到表格。

本專案以「**token 預算當契約 + 變動深度切塊 + 原生表格解析 + 明確的 `EMIT_DEPTH` 粒度旋鈕**」一次解決，下游 RAG 換 embedding model 時 row 形狀不會跟著飄。

## 快速上手

```bash
# 1. 安裝
git clone https://github.com/shin13/nhi-knowledge-extractor.git
cd nhi-knowledge-extractor
uv sync

# 2. 跑全流程（fetch → parse → chunk → render → package）
uv run nhi-extract sync
```

預期輸出（節錄）：

```
Fetched: 16 documents, release date 2026-04-24
Skipped 76 (75 appendix_form, 1 unrecognized_title) — see MANIFEST.json
  通則_113.05.28更新_1150424.odt: 1 items
  第一節_神經系統藥物_115.3.23更新_1150424.docx: 49 items
  ...
  第九節_抗癌瘤藥物_115.4.23更新_1150424.docx: 146 items
  ...
Total: 543 items, max token count 5992
Wrote: data/regulations/medication/藥品給付規定_20260424.zip
```

打包出來的 zip 含每節一份 CSV + `MANIFEST.json` + `CHANGES_YYYYMMDD.md`。CSV 每一列就是一個給 RAG 用的 chunk：

| item_id            | parent_id   | part_index | total_parts | heading                              | content（節錄）                    |
|--------------------|-------------|------------|-------------|--------------------------------------|------------------------------------|
| `sec9-9.69-part1`  | `sec9-9.69` | 1          | 5           | 9.69. 免疫檢查點抑制劑 (atezolizumab; …) | `## 9.69. … 1. 本類藥品得 …`        |
| `sec9-9.69-part2`  | `sec9-9.69` | 2          | 5           | 9.69. 免疫檢查點抑制劑 (atezolizumab; …) | `## 9.69. … 2. 本類藥品得併用 …`     |
| `sec9-9.69-part3-1`| `sec9-9.69` | 3          | 5           | 9.69. 免疫檢查點抑制劑 (atezolizumab; …) | `## 9.69. … 3. 使用條件：…`         |
| `sec9-9.69-part3-2`| `sec9-9.69` | 4          | 5           | 9.69. 免疫檢查點抑制劑 (atezolizumab; …) | `## 9.69. … 3. 使用條件（續）：II. …` |
| `sec9-9.69-part4`  | `sec9-9.69` | 5          | 5           | 9.69. 免疫檢查點抑制劑 (atezolizumab; …) | `## 9.69. … 4. 登錄與結案 …`        |

五個 row 共用 `parent_id=sec9-9.69`，因為它們是同一條規定被切開的五部分。RAG 端命中任一個，**應該把同 `parent_id` 全部撈出來 hydrate 才完整**。

### 其他指令

```bash
uv run nhi-extract sync --skip-fetch       # 用已下載的 chapters/ 不重抓
uv run nhi-extract sync --dry-run          # 跑流程印統計但不寫 zip
uv run nhi-extract sync --emit-depth 4     # 較粗粒度切塊（預設 5）
uv run nhi-extract parse <doc.docx>        # debug：印解析後的樹
uv run nhi-extract chunk <doc.docx>        # debug：印 emit 出來的所有 item
uv run nhi-extract diff <dir_a> <dir_b>    # 比對兩個 release
```

## 輸出 schema（11 欄）

| 欄位           | 說明 |
|----------------|------|
| `topic`        | RAG 必填，固定前綴 + 完整 breadcrumb（`臺灣全民健康保險藥品給付規定/…`）|
| `content`      | Markdown 內容（含內嵌表格）|
| `heading`      | 此 chunk 的標題（含編號）|
| `section_path` | 從文件 root 到此標題的階層，以 ` > ` 串接 |
| `item_id`      | 唯一穩定 ID（diff key）— `sec{N}-{level}[-partK[-M]]` |
| `parent_id`    | 邏輯單元 ID。沒 split 時等於 `item_id`；split 出來的兄弟共用此 ID |
| `part_index`   | 在 `parent_id` 群組內的位置（從 1 起算）|
| `total_parts`  | 同 `parent_id` 群組總共幾個 row |
| `source_file`  | NHI 原始檔名 |
| `source_url`   | NHI 下載連結 |
| `update_date`  | 雙曆日期（`2026/04/24 (民國115年4月24日)`）|

### RAG hydration 慣例

命中的 row 若 `total_parts > 1`，**請把同 `parent_id` 的所有 row 撈出來組合**再餵給 LLM。這跟 LangChain `ParentDocumentRetriever` / LlamaIndex `AutoMergingRetriever` 是同一個 pattern。

上面例子 `sec9-9.69` 免疫檢查點抑制劑被切成 5 個 row，是因為整段超過 7000 token 硬上限。沒 hydrate 的話，LLM 回答「Pembrolizumab 使用條件」只會看到包含「使用條件」的那段，漏掉 `part1` 的適應症列表。

## EMIT_DEPTH — 切塊粒度旋鈕

`EMIT_DEPTH`（預設 `5`）是節點 emit 為單一 row 的「最小深度」。深度低於此值的節點必須繼續往下切，即使整棵子樹塞得進 `TARGET_BUDGET`。這把「編輯意圖（一個 row 是什麼？）」與「embedding 容量上限」分開兩個旋鈕。

NHI 編號各節不一致：
- 第九節 9.70 Pertuzumab → `level=(9,70)`，深度 2 已是藥物層
- 第四節 4.1.2.1 短效型 G-CSF → `level=(4,1,2,1)`，深度 4 才是藥物層

預設 5 對應 NHI 最深的款層（第五節 / 第八節）。設更高（6+）沒效果，因為沒有節點到那麼深；設更低（3、4）會故意把多個藥物合併進同一 row，**只在你明確想要較粗粒度時用**。

單次覆寫：

```bash
uv run nhi-extract sync --emit-depth 4
uv run nhi-extract chunk path/to/doc.docx --emit-depth 3
```

## 文件

- [`docs/intent.md`](docs/intent.md) — 原始問題與 failure mode
- [`docs/spec.md`](docs/spec.md) — 完整設計（pipeline / types / chunker 演算法 / schema）
- [`docs/emit-depth-plan.md`](docs/emit-depth-plan.md) — `EMIT_DEPTH` + RAG metadata + anchor preamble 設計
- [`docs/roadmap.md`](docs/roadmap.md) — 未來計畫（P0–P6）
- [`docs/next-fixes.md`](docs/next-fixes.md) — 未做的議題（Task G — 附表表單）
- [`CLAUDE.md`](CLAUDE.md) — 指令、結構、慣例、踩雷紀錄

## 授權

MIT — 詳見 [`LICENSE`](LICENSE)。
