# v15 stage 3 · config

Gate: `uv run python v15/config/test_config.py`（退出码 0 = 通过）

库名 `agent_v15_config`。这是前缀 gate 库，不是合运行时。合运行时只在 `SQL_LOAD_ORDER` 十一个文件都加载之后。

`setup_db.py` 先删掉每一个 `starts_with(datname, 'agent_v15_')` 的库（含 stage 1 / 2），再重建集群角色，然后 `CREATE DATABASE` 并 `load_stage(..., "config")`。角色语句不在 SQL 文件里。加载结束后 `v15_bootstrap` 改为 `NOLOGIN`。

## 内容

- `v15_resolve_config(scope_id, local_layer_id, depth)`：§8.2 的折叠。顺序是 profile，然后本 scope 上 `kind = depth` 的层按 `ordinal`，只读 `depth_map` 里该深度的十进制键，然后 `kind = plain` 按 `ordinal`，最后 local。组件整对象替换。`config_digest = md5(resolved_config::text)`
- `v15_resolve_child_config`：子路径。`local_layer_id` 非空抛 `V15_CONFIG_LOCAL`（`P1531`），否则以 NULL local 调用 resolve
- `v15_register_profile` / `v15_update_profile` / `v15_register_scope` / `v15_add_layer`：写入与校验。`EXECUTE` 只给 `v15_owner` 与 `v15_bootstrap`。resolve 与 ceilings 只给 `v15_owner`
- `v15_effective_ceilings(p_ceilings, p_parent_ceilings)`：根从清单起，`p_ceilings` 只许更小；子没有 `p_ceilings`，与当时清单逐项取 min。摘要走已有的 `v15_manifest_digest`

列是否参与折叠看 `IS NOT NULL`。depth partial 的键是否存在看 `jsonb_exists`。JSON `null` 算在场，但不是对象，抛 `V15_VALUE_INVALID`（`P1524`）。`kind = depth` 的组件列或 `extra_hooks` 非空，或 partial 含 `depth_map`，抛 `V15_DEPTH_SELF`（`P1530`）。partial 或层含 `baseline_hooks` 键抛 `V15_BASELINE_IMMUTABLE`（`P1532`）。放宽上限抛 `V15_GOVERNANCE_RAISE`（`P1505`）。

种子 profile `00000000-0000-4000-8000-0000000000a1`，scope `00000000-0000-4000-8000-0000000000b1`。组件是 §8.1 的那一份，`baseline_hooks = []`。

## 本 stage 不证明

`v15_open_invoke`、hook 安装、已打开 invoke 的推进。冻结用直接调用 resolve，再把结果写入一行 `invokes`，然后 `UPDATE` profile：新的 resolve 看见新值，已写入的 `config_digest` 不变。

§8.5 没有定义 `config_scopes.scope_digest`。这里存 `md5(profile_id::text)`，不进入 `config_digest`。profile / layer 摘要由写入函数维护；直接 `UPDATE` 列不会重算那两枚摘要，resolve 读的是列，不是摘要。
