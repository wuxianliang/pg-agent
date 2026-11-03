---
name: repo-recon
description: Map an unfamiliar repository before changing it.
---

# Repo recon

1. Use `get_file_tree(max_depth=2)` to map the repository.
2. Use `file_search(mode="path", pattern=...)` to locate likely entry points and configuration. Use its `filter` for scope; use `grep` when you need a `glob` or `literal` switch instead.
3. Use `read_file` to read 3-5 key files. Its `start_line` is one-based; `start_line=-N` reads the last N lines. Never combine a negative start with `limit`; zero is invalid.
4. Use `read(path=..., offset=..., limit=...)` to page through long files. It returns verbatim text without added line numbers. Follow its continuation notice using `offset`.
5. Return a structure summary of at most 120 words, naming entry points, major components, and the likely change location. Do not change files during reconnaissance.

Each reply has a 512-token cap including reasoning. Exceeding it fails the whole round with `finish_length`; it does not return a shortened answer. Leave room within that cap for the summary.
