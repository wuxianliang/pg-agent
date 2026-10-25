# v24 D-S7-2 fairness M-F1 execution audit (2026-10-25)

## Result

M-F1 completed as one milestone. The implementation adds the fair host-only scheduler and S12 Fake-only evidence; all 31 verification commands exited 0. No real provider was called. The broad D-S7-2 debt remains open: this evidence is finite, opportunity-dense, host-only, and Fake-based.

## Source and frozen boundary

- Worktree: `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`
- Source HEAD before the uncommitted M-F1 tree: `6d53a2d05a2e5439e7694125d4751ba053acb147`
- P0 frozen comparison base: `996cb5bc86f38fe5cbc21d058e93df54b4923620`
- Product/test tree digest (path + NUL + file SHA-256, paths listed below): `03f89ac56642b7962a04a08356c4ef3e16b11c700d80268f27999d28929900a5`
- Frozen check: `git diff --quiet 996cb5bc86f38fe5cbc21d058e93df54b4923620 -- v24/sql/00_schema.sql v24/sql/10_schema.sql v24/sql/20_triggers.sql v24/sql/30_advance.sql v24/sql/40_interpreters.sql v24/sql/45_capability.sql v24/sql/46_cleanup.sql v24/sql/47_verbs.sql v24/sql/48_loop.sql v24/sql/49_recovery.sql v24/sql/49_host_reads.sql v24/sql/50_permissions.sql v24/load.py v24/host/db.py v24/host/journal.py` → exit 0.

### Executed product/test files

| Path | SHA-256 | Bytes |
|---|---|---:|
| `v24/host/worker.py` | `a24f2af1d0bc0b98ac11555c4ec074a57bf078ab7831420a8cc14d98a127aaf4` | 62550 |
| `v24/s12/fair_support.py` | `a24d4a4dc2b839ce920b5d9f405c28780264910aa10735517f3d07176b5b1cd4` | 7397 |
| `v24/s12/test_g11.py` | `f8a6752f9ac02e9351e917b1385f75bedbdea277a1b13b9a5c700cb79d24855c` | 52990 |
| `v24/s12/README.md` | `1c9a8ca0a8376d428098ddba3cd4dc0c1f22fab49022975e1a959b66e1dfc5f3` | 4187 |

## Verification environment and evidence

- Runner directory: `/tmp/v24-mf1-evidence-20261025/`.
- `summary.json` records the exact command, Asia/Shanghai `executed_at`, exit code, duration, logfile and logfile SHA-256 for every command.
- Provider variables `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `OPENAI_API_URI`, and `OPENAI_MODEL` were removed; `UV_NO_ENV_FILE=1` was used. No real-provider flag was used.
- Unix PostgreSQL fixture sockets were allowed by the repository contract; external model/tool/plugin transports were Fake or scripted. Local Python/Node plugin subprocess checks are the existing offline M-P evidence.

## Command ledger

| # | executed_at (+08:00) | command | exit | log SHA-256 |
|---:|---|---|---:|---|
| 1 | 2026-10-25T20:04:59.111660+08:00 | `uv run python v24/s12/test_g11.py` | 0 | `89fb03a85a4ff941d32593e2ce8c997a2a19c9898b51e0e73794c54cb90791cd` |
| 2 | 2026-10-25T20:05:02.169715+08:00 | `uv run python v24/s12/test_g11.py --only G11-A` | 0 | `7061f084811df4b1f0137e2adec9dbf401c4ad2693033b7634e9cc34d34fb653` |
| 3 | 2026-10-25T20:05:04.254551+08:00 | `uv run python v24/s12/test_g11.py --only G11-B` | 0 | `c65fc7e40982f4bc4b92a08e9e0c2da3e4eadfbf7e553f2218e93ee328137394` |
| 4 | 2026-10-25T20:05:06.376759+08:00 | `uv run python v24/s12/test_g11.py --only G11-C` | 0 | `6190461460f3b603fb5f8a420ae7ec95f590975d6dc402e70eea7c06d49b20dd` |
| 5 | 2026-10-25T20:05:08.644296+08:00 | `uv run python v24/s12/test_g11.py --only G11-D` | 0 | `672585d54a9baf085aab09542ade183262e3893a11e07c6867bb376f8102c31d` |
| 6 | 2026-10-25T20:05:10.722217+08:00 | `uv run python v24/s12/test_g11.py --only G11-E` | 0 | `ec156403c8529eb82915d549e9206144a707f2866d7367b61b3cdb42498ecfc1` |
| 7 | 2026-10-25T20:05:12.768388+08:00 | `uv run python v24/s12/test_g11.py --only G11-F` | 0 | `cb90e23ec7460242d17c6c8c1a09c67cc5c713f8534a6303b62513ba3f41a3c2` |
| 8 | 2026-10-25T20:05:14.853743+08:00 | `uv run python v24/s12/test_g11.py --only G11-G` | 0 | `e42a8e7535163d398a8b0e752d641b6b5cd319e39f86553c4c969d8f4fbd2e88` |
| 9 | 2026-10-25T20:05:16.916822+08:00 | `uv run python v24/s12/test_g11.py --only G11-H` | 0 | `736e5dcf5cd9453dd33f4736149a057fd3cf35f903788edc3a6d027ab418d983` |
| 10 | 2026-10-25T20:05:18.955165+08:00 | `uv run python v24/s12/test_g11.py --only G11-I` | 0 | `a7297fbe2054486cb1112cdd9a607e13d0a22757bbe56761087986dfbf059463` |
| 11 | 2026-10-25T20:05:21.023127+08:00 | `uv run python v24/s12/test_g11.py --only G11-J` | 0 | `2533b44641ddac926b57955e9f868baba543d341f94f44169ed0faf08e125462` |
| 12 | 2026-10-25T20:05:23.080881+08:00 | `uv run python v24/s12/test_g11.py --only G11-K` | 0 | `3639b8b416a53ecb6a904fdf8e01083ce8f113b40079891d355b0c1cebe62b60` |
| 13 | 2026-10-25T20:05:25.115671+08:00 | `uv run python v24/s12/test_g11.py --only G11-L` | 0 | `88ec261fda657ab5196a686ba40751fe8821e385c51a4751b5b2ad2e694b6602` |
| 14 | 2026-10-25T20:05:27.264547+08:00 | `uv run python v24/load.py` | 0 | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 15 | 2026-10-25T20:05:27.769338+08:00 | `uv run python v24/s1/setup_db.py --self-check` | 0 | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 16 | 2026-10-25T20:05:29.303345+08:00 | `uv run python v24/s1/test_ddl.py` | 0 | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 17 | 2026-10-25T20:05:30.850632+08:00 | `uv run python v24/s1/test_g1.py` | 0 | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 18 | 2026-10-25T20:05:33.271797+08:00 | `uv run python v24/s2/test_g3a.py` | 0 | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 19 | 2026-10-25T20:05:35.097834+08:00 | `uv run python v24/s3/test_g2.py` | 0 | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 20 | 2026-10-25T20:05:40.177573+08:00 | `uv run python v24/s4/test_g2b.py` | 0 | `84f5ae35b6461d9a3c6f13a23052aee4853ee3772cc5fd1e3a09e0adb77f9782` |
| 21 | 2026-10-25T20:05:43.917821+08:00 | `uv run python v24/s5/test_g4.py` | 0 | `9141635a34c7b877c6ca639eb6d80929a082993682c0df6c948ae1d4b7fa5806` |
| 22 | 2026-10-25T20:05:47.044421+08:00 | `uv run python v24/s6/test_g5.py` | 0 | `279f0bff9fcab71d48b5196117517b5789b6ba5b14180bdfdffd18728feb6c18` |
| 23 | 2026-10-25T20:05:50.734109+08:00 | `uv run python v24/s8/test_g7.py` | 0 | `f13e1fc0b2d25624334a4c9c062b41dcec60630061881a066fa460d3cae6c374` |
| 24 | 2026-10-25T20:05:53.065544+08:00 | `uv run python v24/s7/test_g6.py` | 0 | `df5fc548b7d98ead72cfa5dd4e9b4cef1d10ee8ac8a9ab480411e66013a4bb16` |
| 25 | 2026-10-25T20:05:59.464818+08:00 | `uv run python v24/s9/test_g8.py` | 0 | `3eadebcf0f3a6c6446e647011973ab623414bb6f3bc902e8dd2d531b1c8ff09d` |
| 26 | 2026-10-25T20:06:10.517139+08:00 | `uv run python v24/s10/test_g9.py` | 0 | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 27 | 2026-10-25T20:06:13.679428+08:00 | `uv run python v24/s11/test_g10.py` | 0 | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 28 | 2026-10-25T20:06:17.159008+08:00 | `uv run python v24/s11/test_node.py --node` | 0 | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 29 | 2026-10-25T20:06:19.329876+08:00 | `uv run python -m v24.host.smoke` | 0 | `23e85076a974bd0f078bed820e81220fce5a9fece5d2d296bd2364d6bfad363c` |
| 30 | 2026-10-25T20:06:19.876778+08:00 | `uv run python -m v24.host.plugin_smoke` | 0 | `23e85076a974bd0f078bed820e81220fce5a9fece5d2d296bd2364d6bfad363c` |
| 31 | 2026-10-25T20:06:20.431976+08:00 | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `80e31eb4939a622079bfd76440ccb36782ed950ba8f1b019a484716885a6a28a` |

## Evidence limits and review fixes

- G11 full plus G11-A…L passed with 104 finite selector states and 3,168 independent model-entry scenarios. It proves the bounded FC sub-contract, strict protocol/error handling, D4 ownership/terminal reconciliation, and legacy compatibility under the listed fixtures.
- The run does not prove open-arrival starvation-freedom, wall-clock wait or debt bounds, cross-crash or multi-host fairness, or real-provider latency/availability/cost/quality. O2 burst=3 remains an unmeasured preference assumption.
- The reviewed fixes covered no-I/O finished re-entry, settlement effect identity, terminal outcome equality, per-scope pending accounting, no-I/O progress counting, pin cursor binding, independent model stopping decisions, and the D4 partial-marker starting state.

## Durable references

- Plan: [`docs/plans/v24-d-s7-2-fairness-fake-only-2026-10-25.md`](../plans/v24-d-s7-2-fairness-fake-only-2026-10-25.md)
- Design critique: [`docs/reviews/v24-d-s7-2-fairness-plan-critique-2026-10-25.md`](v24-d-s7-2-fairness-plan-critique-2026-10-25.md)
- S12 README: [`v24/s12/README.md`](../../v24/s12/README.md)

The `/tmp` logs are retained as the immediate execution evidence; the command and logfile hashes above make the durable record tamper-evident.
