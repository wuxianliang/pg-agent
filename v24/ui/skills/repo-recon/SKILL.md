---
name: repo-recon
description: Map a repository before editing.
---

1. Map with `get_file_tree(max_depth=2)`.
2. Locate entries/config with `file_search(mode="path", pattern=...)`; scope via `filter`. Use `grep` for glob/literal.
3. `read_file` 3-5 key files: one-based `start_line`, never 0; `start_line=-N` takes the tail, without `limit`.
4. Page long files via `read(path=..., offset=..., limit=...)`: verbatim text, no line numbers; follow continuation offsets.
5. Summarize entries, components and likely change location in <=120 words. No edits during recon.
