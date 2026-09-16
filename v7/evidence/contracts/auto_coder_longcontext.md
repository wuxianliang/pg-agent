# auto-coder LongContextRAG contract (Phase 0 WI-3)

Evidence level: **E1** (Python source + tests inspected). **Not E2**. Primary tree has **no git**.

Related backend: LongContext Python orchestration is **not blocked** for contract freeze. Runtime adapters are Phase 5, not this freeze.

v4.1 reuses **external behavior**, not the old DuckDB cache schema.

## What was read

| Path | Notes |
|---|---|
| `/Users/wxl/Projects/auto_coder-3.0.74` | `pyproject.toml` `version = "3.0.74"`; **no `.git`** |
| `src/autocoder/rag/long_context_rag.py` | LongContextRAG class, context math, stream |
| `src/autocoder/rag/token_limiter.py` | TokenLimiter + 1-based ranges + retry |
| `src/autocoder/rag/doc_filter.py` | LLM relevance filter |
| `src/autocoder/rag/rag_config.py` | filter/answer config + timeouts |
| `src/autocoder/rag/llm_request_timeout.py` | stage timeout defaults |
| `src/autocoder/rag/conversation_to_queries.py` | query expansion |
| `src/autocoder/rag/stream_event/types.py` | EventType |
| `src/autocoder/rag/observability.py` | RAGEvent |
| `src/autocoder/rag/qa_conversation_strategy.py` | QA prompts |
| `src/autocoder/rag/types.py` | ChunkRange, RAGStat |
| `src/autocoder/common/__init__.py` | `AutoCoderArgs` defaults |
| `/Users/wxl/Projects/rag/auto_coder-3.0.45/src/autocoder/rag/` | secondary: same filenames (`long_context_rag.py`, `token_limiter.py`, `rag_config.py`, `doc_filter.py`, `stream_event/`). No `pyproject.toml` at that root. **Not used as the freeze authority.** |

## Frozen config defaults (`AutoCoderArgs`)

`src/autocoder/common/__init__.py:347-457` (class defaults):

| Field | Default |
|---|---|
| `index_filter_workers` | `1` |
| `rag_doc_filter_relevance` | `2` |
| `rag_context_window_limit` | `0` (resolve from model) |
| `rag_auto_window_limit` | `0` |
| `rag_recall_request_timeout` | `None` → stage default |
| `rag_chunk_request_timeout` | `None` → stage default |
| `rag_qa_request_timeout` | `None` → stage default |
| `rag_duckdb_vector_dim` | `1024` (legacy cache; **not** mdenseon) |
| `rag_duckdb_query_similarity` | `0.1` |
| `rag_duckdb_query_top_k` | `10000` |
| `rag_recall_max_queries` | `5` |
| `rag_qa_conversation_strategy` | `"multi_round"` |
| `enable_hybrid_index` | `False` |
| `hybrid_index_max_output_tokens` | `1000000` |
| `disable_segment_reorder` | `False` |
| `full_text_ratio` | `0.7` |
| `segment_ratio` | `0.2` |
| `buff_ratio` | `0.1` (derived as `1 - full - segment` in `_calculate_context_token_limits`) |
| `without_contexts` | `False` |
| `filter_batch_size` | `5` |

CLI `command_args.py` uses `rag_doc_filter_relevance` default **5**, which disagrees with `AutoCoderArgs` **2**. Freeze **class defaults** as the library contract; CLI override is a separate layer.

`_resolve_rag_context_settings` (`long_context_rag.py:3124-3126`) falls back to `5` only if the attribute is `None`. A constructed `AutoCoderArgs()` therefore uses **2**.

`DEFAULT_RAG_AUTO_WINDOW_LIMIT = 64000`  
`RAG_AUTO_WINDOW_CONTEXT_RATIO = 0.8`  
(`long_context_rag.py:2879-2880`)

Token partitions (`long_context_rag.py:2891-2908`):

```text
full_text_limit = int(window * full_text_ratio)
segment_limit   = int(window * segment_ratio)
buff_limit      = int(window * (1 - full_text_ratio - segment_ratio))
```

## Query expansion

`_retrieve_documents_for_query` (`long_context_rag.py:642-661`) calls `extract_search_queries` with `max_queries=args.rag_recall_max_queries` (default **5**).

`ConversationToQueries.generate_search_queries` prompt default `max_queries: int = 3` (`conversation_to_queries.py:81`) is the **method default**, overridden by args.

Retrieved options: original query plus expanded queries (`long_context_rag.py:638-639`).

Prompt requires JSON list of `{query, importance, purpose}` (`conversation_to_queries.py:122-136`).

v4.1 product: expansion failure → `RAG_QUERY_EXPANSION_FAILED`, run original query once. auto-coder `extract_queries` wraps generation in `try` (`conversation_to_queries.py:150`); exact fallback is in that function — freeze: do not infinite-retry expansion.

## LLM relevance filter (`DocFilter`)

Prompt `_check_relevance_with_conversation` (`doc_filter.py:148-179`): reply `yes/<relevant>` or `no/<relevant>` with score 0–10. Optional `filter_config` from `.rag_config/filter_config`.

Workers: `ThreadPoolExecutor(max_workers=self.args.index_filter_workers or 5)` (`doc_filter.py:248-249`). With AutoCoderArgs default `1`, workers = **1**. The `or 5` only fires on `0`/`None`.

Recall LLM config: `{"max_length": 10}` plus stage timeout (`doc_filter.py:264-268`).

Threshold: `self.relevant_score = self.args.rag_doc_filter_relevance` (`doc_filter.py:198`).

**Retry:** DocFilter `_run` catches **all** `Exception`, logs, returns `(None, ...)` (`doc_filter.py:283-287`). **No retry.** `None` relevance → not relevant (`doc_filter.py:41-48`).

Futures are consumed via `as_completed` then attached to the original doc (`doc_filter.py:315-322`). Final sort is by score descending (`doc_filter.py:143-145`). v4.1 requires reordering by **stable candidate key, not completion order** after scores exist — freeze that product rule even though auto-coder sorts by score only.

v4.1 product retry (transport / 429 / 5xx only) is **stricter than** auto-coder DocFilter (no retry) and **different from** TokenLimiter (retry any Exception). Implement v4.1, do not copy TokenLimiter’s blanket retry into the filter.

## TokenLimiter

Class (`token_limiter.py:280-305`): `full_text_limit`, `segment_limit`, `buff_limit`, `disable_segment_reorder`.

Line numbering (`token_limiter.py:21-26`): `enumerate(..., idx+1)` — **1-based** display lines.

Range extract (`token_limiter.py:38-41`): `start_line = item["start_line"] - 1` then `end_line` exclusive via `source_code_lines[start_line:end_line]` — **1-based closed interval** in the LLM JSON.

`ChunkRange` (`types.py:61-63`): `start_line: int`, `end_line: int`.

Document reorder (`token_limiter.py:70-99`): group by `metadata["original_doc"]`, sort by `chunk_index`, unless `disable_segment_reorder`.

Second-round extraction workers: `index_filter_workers or 5` (`token_limiter.py:535`).

`process_range_doc(..., max_retries=3)` (`token_limiter.py:732-810`): retries **any** `Exception` up to 3 attempts; then empty range. **Not** limited to transport/429/5xx.

Small-file vs large-file split is the full-text window then segment extraction (see `token_limiter.py:447-511` and log at `long_context_rag.py:3186-3187`: small file limit `single_file_token_limit / 4`, merge limit `/ 2`).

## Timeouts / RagConfig

`llm_request_timeout.py:12-20`:

| stage | field | default seconds |
|---|---|---|
| recall | `rag_recall_request_timeout` | `30.0` |
| chunk | `rag_chunk_request_timeout` | `30.0` |
| qa | `rag_qa_request_timeout` | `120.0` |

Precedence: args → `.rag_config/settings.json` → default. `0` / `""` / `None` means unset (`_normalize_timeout`). If `gen.timeout` already in llm_config, leave it (`with_stage_request_timeout:62-63`).

`RagConfig` files (`rag_config.py:23-41`): `{path}/.rag_config/filter_config`, `answer_config`, `settings.json`. Inline overrides win.

## Stream events

`stream_event/types.py:5-16`:

```text
EventType: start | thought | chunk | done | error
Event: request_id, event_type, content, index
```

`RAGEvent` (`observability.py:9-19`): `phase`, `name`, `status`, `timestamp`, `elapsed_ms`, `message`, `metrics`, `attributes`.

Observed names include `rag.initializing`, `rag.initialized`, `rag.doc_filter.start`, `rag.doc_filter.doc.complete` (`long_context_rag.py:3610-3746`, `doc_filter.py:221-230`).

v4.1 named-tool stream is a **separate** event set (`answer_delta` forbidden on deferred). Do not treat auto-coder `EventType.CHUNK` as `answer_delta` without an explicit mapping.

## `without_contexts`

`long_context_rag.py:880`: `if args.without_contexts and compute_engine_cls is not None` → skip retrieval. v4.1 freeze (`plan §3.11`): no recall, no filter, no TokenLimiter, `contexts=[]`, QA may still run.

## QA prompt (parity target)

`qa_conversation_strategy.py:108+` `_read_docs_prompt`: answer **strictly from retrieved documents**; Chinese fallback exists in `_read_docs_prompt_old` (`qa_conversation_strategy.py:74-105`) including “抱歉,文档中没有足够的信息来回答这个问题。”. Keep 中文 error strings as compatibility.

## Open unknowns

- Tokenizer identity for TokenLimiter vs QA LLM: `tokenizer_path` optional; not hashed here (F-10).
- Exact `extract_search_queries` failure fallback body (file ends at line 198; generation is try-wrapped).
- 3.0.45 vs 3.0.74 behavior diff: not diffed line-by-line; 3.0.74 is the freeze authority.

## Backend gate

Not blocked. When implementing, pin 3.0.74 line citations above; do not use `rag_duckdb_vector_dim=1024` as mdenseon dim.
