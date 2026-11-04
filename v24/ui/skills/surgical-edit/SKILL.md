---
name: surgical-edit
description: Make precise edits in one file.
---

1. `read(path=..., limit=...)`; page via `offset`.
2. One `edit` batch of all `edits[{oldText,newText}]`: unique, nonoverlapping matches against the same original.
3. On `edit_ambiguous`, expand `oldText` context; retry.
4. Read back; report changes/verification.

No `apply_edits.rewrite` for small changes.

Large content: small `write(append=true)` (`write.append`) chunks. `MAX_SAFE_ARGS_BYTES=128`: keep complete tool-call args at or below 128 bytes.
