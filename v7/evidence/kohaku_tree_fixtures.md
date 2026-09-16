# Kohaku tree fixtures (Phase 0)

**Verdict: E2 of generated fixtures** — KohakuRAG `parsers.py` + `indexer._build_tree` were executed at pin `f3d27c8d24616b75508795766355632640979e5b`. Embeddings were not computed. This is **not** a live Kohaku RAG service or LanceDB index.

| Item | Evidence |
|---|---|
| Kohaku-native markdown/text/JSON trees | **E2** — `uv run python v7/migration/kohaku_tree_fixture.py --write` then `--check`; tests `uv run python v7/tests/test_kohaku_tree_fixture.py` |
| KohakuRAG in-repo `fixtures/` | **still absent** — trees live in pg-agent `v7/tests/fixtures/kohaku/` |
| MinerU JSON → Kohaku tree | **E0** — not this artifact; range trio stays blocked |
| `NodeKind.ATTACHMENT` | declared in types, **not** created by indexer (0 attachment nodes in golden) |

## Command

```sh
# Verify the committed golden against a clean Kohaku pin (does not write):
uv run python v7/migration/kohaku_tree_fixture.py --check
uv run python v7/tests/test_kohaku_tree_fixture.py

# Regeneration is explicit and separate. Review git diff after --write:
# uv run python v7/migration/kohaku_tree_fixture.py --write
```

`--write` and `--check` are mutually exclusive. `--check` after `--write` in the same process would only compare the file it just overwrote. Generation fails if `src/kohakurag` is dirty relative to HEAD.

Kohaku root: `PG_AGENT_KOHAKURAG_ROOT` or `/Users/wxl/Projects/rag/KohakuRAG`. Package `__init__.py` is not imported (avoids `kohakuvault` / Jina / torch). The generator stubs `kohakurag.embeddings` and refuses to call `embed`.

## Frozen files

- `v7/tests/fixtures/kohaku/documents/headings.md`
- `v7/tests/fixtures/kohaku/documents/plain.txt`
- `v7/tests/fixtures/kohaku/documents/nested.json`
- `v7/tests/fixtures/kohaku/golden.v1.json` (`corpus_kind=generated_from_kohaku_source`)

Do not treat this as live corpus E2 for MinerU, legacy cache, or range_origin.
