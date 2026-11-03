---
name: surgical-edit
description: Make several precise changes within one file using a single edit batch.
---

# Surgical edit

1. Read the original with `read(path=..., limit=...)`, paging with `offset` as needed.
2. Submit one `edit` call containing all `edits[{oldText,newText}]`. Match each `oldText` against the same original document, choose unique context, and keep the matched spans nonoverlapping. The tool applies the validated batch in reverse source order.
3. If `edit_ambiguous` occurs, expand `oldText` with surrounding original context and retry. Exact matching is preferred; the tool can fall back to NFKC, whitespace, quote, and dash normalization. Re-read after a successful edit before planning another batch.
4. Read back the changed region and report the changes and relevant verification briefly.

Do not use `apply_edits.rewrite` for small changes. Pi `edit` has one batch mode; RPCE `apply_edits` requires exactly one of `rewrite`, `search` plus `replace`, or `edits`. Its `on_missing` applies only to rewrite, and its statuses are `success`, `partial`, `failed`, and `no_change`.

For large new content, split the work into small `write` calls with `append=true` (`write.append`). `MAX_SAFE_ARGS_BYTES` is currently unmeasured (`None`); no numeric safe argument limit is established, so do not invent one and keep each chunk small. Respect the threshold if a measured `MAX_SAFE_ARGS_BYTES` is provided in the future. The 512-token reply cap includes reasoning; `finish_reason="length"` causes `finish_length` and fails the whole round, rather than shortening arguments. Avoid generating a large tool call in one reply.
