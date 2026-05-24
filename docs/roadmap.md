# Future Plans

Categorised by priority and stance toward YAGNI. Status here reflects 2026-05-24.

## P0 — Demand-triggered (currently YAGNI)

Do not start until a real user need surfaces.

| Item | Trigger | Estimate | Design status |
|---|---|---|---|
| **Task G — appendix forms (附表) structured CSV** | A downstream RAG user reports "appendix X not found" | 1–2 days | Drafted in `docs/next-fixes.md` Task G |
| **`--allow-over-budget` flag** | Embedding model upgrade + user insists on "one drug class per row" for 9.69-style cases | 0.5 day | Designed (Q2 (b) path in `docs/emit-depth-plan.md`) |
| **PDF-only document handling** | Appendix 13 / 15 specifically requested | 1 day | Sub-problem of Task G |

## P1 — Public-repo polish (post-push)

Run these once the repo is live on GitHub.

| Item | Why | Estimate |
|---|---|---|
| `gh repo create … --push` | Make the repo a public asset | 5 min — **done in this session** |
| README badges (CI, license, Python version) | Standard public-repo signaling | 10 min |
| `CONTRIBUTING.md` | Required when accepting outside PRs | 30 min |
| GitHub Actions CI (pytest) | Auto-gate PRs | 30 min — **done in this session** |
| Add `ruff check` to CI | Style + dead-code guardrail | 30 min |
| Add `mypy src/` to CI | Type-drift guardrail (start non-strict) | 2–4 hr |
| PyPI release | `pip install nhi-knowledge-extractor` instead of cloning | 1 hr (trusted publisher setup) |

## P2 — Code-quality (raise the bar)

| Item | Pain it solves | Estimate |
|---|---|---|
| **ruff** | Unified style, catch unused imports | 30 min |
| **mypy strict** | Catch type drift; some functions still un-annotated | 2–4 hr |
| **pre-commit hooks** | Gate at local commit, not just CI | 30 min |
| **Coverage threshold + badge** | Encourage tests with new features | 30 min |

## P3 — Feature expansion (changes how the tool is used)

| Item | Description | Estimate |
|---|---|---|
| **Richer `--diff`** | Show paragraph-level diff, not just added/modified/removed lists | 1 day |
| **Multi-release sync** | Crawl N past NHI releases, produce a time-series dataset | 2 days |
| **MANIFEST audit fields** | per-doc `max_depth_in_tree`, `emit_depth_used`, polluted-row count | 0.5 day |
| **`chunk --verbose`** | Show budget utilisation, parent_id groupings per row | 0.5 day |
| **Per-section stats dashboard** | A self-contained HTML visualisation of a release | 1–2 days |

## P4 — Cross-project integration (downstream / upstream)

| Item | Description | Where it lives |
|---|---|---|
| **RAG hydration sample** | LangChain `ParentDocumentRetriever` / LlamaIndex `AutoMergingRetriever` example | downstream RAG repo, not here |
| **Bulk ingestion into RAG backend** | Script in the consuming RAG service to ingest a release zip | consuming repo |
| **Medical-LLM backend integration** | Reference link from a medical assistant to specific NHI items | consuming repo |
| **Drug-info API cross-reference** | Drug query API surfaces the matching regulation link / summary | sibling drug-info repo |

## P5 — Pipeline robustness

| Item | Trigger | Estimate |
|---|---|---|
| `fetch` retry / backoff | NHI occasionally returns 429 / timeout | 0.5 day |
| Schema migration script | When CSV columns change and we need to migrate old releases | 0.5 day |
| Scheduled weekly sync (cron / CI workflow) | Auto-fetch + diff + notify | 0.5 day |
| Incident log on failed sync | Traceability | 0.25 day |
| Retire `_char_split_oversized` | It's a band-aid for a pathological test; remove once spec confirms it's unreachable | 0.5 day |

## P6 — Ideas box (record, may never do)

- Other NHI regulation classes (醫材給付, 特材給付, 診療規範) — separate project or expansion?
- English translation (LLM-assisted, but medical accuracy is risky)
- Appendix → JSON Schema for hospital form generation (huge effort, unclear demand)
- Historical version lookup ("Pembrolizumab regulation diff between 110/1/1 and 113/12/1")
- GraphQL / REST API wrapper around the CSV (over-engineering; CSV is enough today)

---

## Recommended sequence (whenever the project is touched again)

1. Confirm downstream RAG integration works with current 11-column schema + hydration pattern
2. Add ruff to CI (low cost, high signal)
3. Wait for demand to drive P0 items (don't pre-build)

The repo is feature-complete for its stated scope as of commit `f0f6a5f` (2026-05-23).
107 / 107 tests green. 16 docs, 543 items, max 5992 tokens per row, no polluted rows.
