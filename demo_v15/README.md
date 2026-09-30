# demo_v15

Headless chain, far-recall, same-iteration fanout, and CSI meta-agent driver. Not a gate. The eight driver sources in this directory are tracked. `/demo_v15/` remains in `.gitignore`, so `reports/`, `__pycache__/`, and any file added later stay ignored until `git add -f` on that path.

```bash
uv run python demo_v15/db.py
uv run python demo_v15/db.py --drop-only
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 DEMO_MODE=fake \
  uv run python demo_v15/drive.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 DEMO_MODE=fake \
  uv run python demo_v15/drive.py --scenario recall --hops 5
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 DEMO_MODE=fake \
  uv run python demo_v15/drive.py --scenario fanout
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 DEMO_MODE=fake \
  uv run python demo_v15/drive.py --scenario csi
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 \
  uv run python demo_v15/test_harness.py
```

`DEMO_MODE` defaults to `fake`. No arguments means `--scenario chain --hops 8`. `chain` allows hops 3–8 (default 8). `recall` allows hops 5–8 (default 5). `fanout` and `csi` allow only hops 1 (default 1). `fanout` is one root plus two leaves, not a chain. `csi` is one root plus three solver children: batch-1 binds a then b; batch-2 is two `SELECT 1;` placeholders then bind c; a later reply returns via `jaz.var('c')`. 2026-09-30 `DEMO_MODE=real` CSI once: exit 1 `fail bad_tail_shape` (4 children / 7 calls; root returned t01 fail JSON). Fake and harness remain exit 0 `csi_ok`. Real mode needs a key in the environment (`source ~/.zshrc` in a non-interactive shell). Do not put a key in `.env` or the database. Real mode pins `base_url=https://api.deepseek.com/v1` and does not read `OPENAI_API_URI`.

Exit 0 is `tail_ok relay_ok` for chain and fanout, `tail_ok relay_ok recall_ok` for recall, or `tail_ok relay_ok csi_ok` for csi (real soft-fail is also 0: `tail_ok relay_soft_fail`, `tail_ok recall_soft_fail`, or `tail_ok csi_soft_fail`). Exit 1 keeps `agent_demo_v15` and prints the drop command. Exit 2 is `credentials_absent`, `mode_invalid`, `note_invalid`, `seal_invalid`, `hops_invalid`, `scenario_invalid`, or `facts_unsized`, and does not create the database.

Leaving `agent_demo_v15` in place makes the next v15 stage setup fail at `DROP ROLE v15_owner` after it has already dropped `agent_v15_*`. Run `--drop-only` first. Reports under `demo_v15/reports/` are not tracked.

## Publish notes

1. From the repository root, run `uv run python demo_v15/db.py`, `drive.py`, and `test_harness.py`. `python -m demo_v15...` is not an entry point. `db.py` puts the repository root on `sys.path` with `Path(__file__).resolve().parent.parent`. That is the script layout.
2. `source ~/.zshrc` is only for a non-interactive shell that still needs a real key from the operator's zshrc. `DEMO_MODE=fake` does not need it. Skip it when the key is already in the environment. The driver does not read that file.
3. `test_harness.py` matches `test_*.py`, but it is not a pytest suite and not a v15 gate. Do not rename it, do not move this directory under `v15/`, and do not add a pytest config that collects it.
4. `git status` does not list untracked files in this directory. Later commits must compare `git ls-files demo_v15` to the 8-path whitelist. Do not `git add -A`.
