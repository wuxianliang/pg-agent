# v24/s10 — G9 scripted provider extension check (M-R)

G9 is an **extension check**, not a twelfth closeout command. It proves the
M-R host worker and the v24 DeepSeek adapter against scripted transports and a
real PostgreSQL fixture. **No real socket is opened and no API key is needed.**
The historical closeout count stays 11/11.

## Run

```bash
uv run python v24/s10/test_g9.py
uv run python v24/s10/test_g9.py --only G9-A,G9-J1
```

Expected last line:

```text
[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R
```

`--only` is a debugging checkpoint; the acceptance run is the no-argument
form above.

## Cases

| ID | Contract |
|---|---|
| `G9-A` | descriptor → safe provider name (`key` + `_` + sha256 prefix), reversible journal map, two provider turns, `reasoning_content` and `tool_call_id` echoed, no `tool_choice` / `parallel_tool_calls` |
| `G9-B` | `stop`/final success, usage `prompt+completion`, `wall_ms`; DB result excludes reasoning, response id and cost; journal keeps provider-only metadata; no key/header |
| `G9-C` | provider tool-call order survives tool effects settling by effect UUID; batch barrier yields exactly one continuation; duplicate provider call ids are a failure, not a replay |
| `G9-D` | mapping table: bad args / unknown tool / missing id / >16 calls / zero calls → `failure`; contradictory finish/message / empty choices / non-JSON / untrustworthy usage → `unknown` |
| `G9-E` | `length` → `unknown` with real usage, truncated text is not final; usage over reserve keeps mapped success and the kernel turns it semantic `unknown` |
| `G9-F` | preflight credentials absent → `failure`, zero HTTP, zero reserve consumed; 400 → `failure`; 3xx/408/429/5xx and timeout / connection interruption → `unknown`, exactly one attempt |
| `G9-L` | `READ COMMITTED`, `statement_timeout=30s`, `lock_timeout=5s`, `idle_in_transaction_session_timeout=5s`; `0 < timeout_s ≤ 239`; lease 61/180/299 s for 1/120/239 s; IDLE before external IO; journal 0700/0600, POSIX lock, closed event set, version/corruption/secret rejection, truncated-tail trim |
| `G9-J1` | crash after `effect_prepared` (no dispatch): re-reads DB eligibility and executes once without a duplicate prepared record; crash after `dispatch_finished`: restart resubmits the stored outcome, zero HTTP, no duplicate effect |
| `G9-J2` | restart after the effect was recovered to `unknown`: old journaled success is a recorded conflict and cannot revive the run |
| `G9-J3` | crash after `dispatch_started`: live lease isolates with zero HTTP; after expiry one `command_recover` sweep → `unknown`, still zero HTTP |
| `G9-R` | closed ten-table catalog, no second queue/claim/journal table; `run_until_idle(max_rounds=1)` executes one of two ready effects; no fairness claim |

## Scripted transport

`ScriptTransport` returns prepared `(status, raw)` pairs. The test also denies
`socket.socket.connect`, `socket.create_connection`, `urllib.request.urlopen`
and `v15.provider.deepseek.build_opener` for the whole run, and restores them
in `finally`. A static scan rejects socket/HTTP imports in `v24/s10/*.py`,
`v24/host/{worker,journal,db,process_io}.py`, direct `FROM v24.*` SQL in the
worker/journal, and any host RPC outside the nine public readers plus
`v24.command_recover` / `v24.advance`.

The adapter uses the official root `https://api.deepseek.com`, model
`deepseek-flash`, `stream:false`, and only the documented body fields. It
reuses `StdlibTransport`, errors and pricing from `v15` without modifying
`v15/**`.

## Optional real-provider smoke

```bash
uv run python -m v24.host.smoke
uv run python -m v24.host.smoke --real-provider-smoke
```

- no flag → `not_requested`, exit 0;
- flag + no `DEEPSEEK_API_KEY` → `credentials_absent`, exit 2, no adapter
  constructed and no database opened;
- flag + key → one short start → model → final run through the real adapter.

The smoke never prints the prompt, content, reasoning or key, and keeps the
journal on failure. It is not a gate.

## Boundaries

- G9 proves the M-R host worker, journal, adapter mapping and opt-in entry. It
  does **not** prove real-provider latency, availability, cost or model
  quality; those need the opt-in smoke and are not deterministic gate claims.
- No starvation/fairness claim (`D-S7-2` stays open).
- No cross-host lease, multi-host or M-P plugin/registry claim.
- `v24/host/process_io.py` is scaffolding for a future plugin host; G9 only
  checks its bounds indirectly through the package static scan.
