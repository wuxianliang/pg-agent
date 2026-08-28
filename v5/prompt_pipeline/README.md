# v5 W4 · prompt_pipeline

`assemble_prompt_messages()` retrieves ordered slots. W4 `prepare_llm_request()`
raises `PROMPT_ASSEMBLY_ERROR` when required generatable parts are missing
(bootstrap arrives in W6).

| | |
|---|---|
| Database | `agent_v5_prompt_pipeline` |
| SQL | `prompt_pipeline.sql` |
| pgembed change | No |

## Gate

passed 14/14 (2026-08-28)
