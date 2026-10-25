# v24 D-S7-2 fairness M-F1 execution audit (2026-10-25)

## Result

M-F1 completed as one milestone. The implementation adds the fair host-only scheduler and S12 Fake-only evidence; all 31 verification commands exited 0. No real provider was called. The broad D-S7-2 debt remains open: this evidence is finite, opportunity-dense, host-only, and Fake-based.

## Source and frozen boundary

- Worktree: `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`
- Source HEAD before the uncommitted M-F1 tree: `6d53a2d05a2e5439e7694125d4751ba053acb147`
- P0 frozen comparison base: `996cb5bc86f38fe5cbc21d058e93df54b4923620`
- Product/test tree digest (path + NUL + file SHA-256, paths listed below): `03f89ac56642b7962a04a08356c4ef3e16b11c700d80268f27999d28929900a5`
- Frozen check: `git diff --quiet 996cb5bc86f38fe5cbc21d058e93df54b4923620 -- v24/sql/00_schema.sql v24/sql/10_schema.sql v24/sql/20_triggers.sql v24/sql/30_advance.sql v24/sql/40_interpreters.sql v24/sql/45_capability.sql v24/sql/46_cleanup.sql v24/sql/47_verbs.sql v24/sql/48_loop.sql v24/sql/49_recovery.sql v24/sql/49_host_reads.sql v24/sql/50_permissions.sql v24/load.py v24/host/db.py v24/host/journal.py` → exit 0.

### Product/test and closeout-document files

| Path | SHA-256 | Bytes |
|---|---|---:|
| `v24/host/worker.py` | `a24f2af1d0bc0b98ac11555c4ec074a57bf078ab7831420a8cc14d98a127aaf4` | 62550 |
| `v24/s12/fair_support.py` | `a24d4a4dc2b839ce920b5d9f405c28780264910aa10735517f3d07176b5b1cd4` | 7397 |
| `v24/s12/test_g11.py` | `f8a6752f9ac02e9351e917b1385f75bedbdea277a1b13b9a5c700cb79d24855c` | 52990 |
| `v24/s12/README.md` | `1c9a8ca0a8376d428098ddba3cd4dc0c1f22fab49022975e1a959b66e1dfc5f3` | 4187 |

S12 README was updated after the runtime batch as a closeout artifact; its hash above identifies the submitted documentation, not executable code. The other three file hashes identify the actual executed implementation and test sources.

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

## Actual merge-candidate verification

- Main base: `fc6f3222b329bea13adfb2baae03d38202142409`. Fixed source: `57e2c1e0fff693447f406f8202472eb73db0b285`.
- Executable file digest (the three Python paths above, same algorithm): `cb76b2871b59441dc3ffa3d054a3a62a23d0926c496ed98bb26203b8715c0dcc`; byte-for-byte equal to the fixed source. Only documents were resolved/appended after merging.
- Candidate environment: `UV_NO_SYNC=1`, `UV_PROJECT_ENVIRONMENT=/Users/wxl/Projects/pg-agent/.claude/worktrees/v99/.venv`, `UV_NO_ENV_FILE=1`; provider variables removed as in the source run. Node resolved to `/opt/homebrew/bin/node`.
- First direct uv attempt exited 2 before gate entry because the candidate-relative DuckDB wheel was absent. Preserved admission-failure log SHA-256: `2fe198b7e07cea26163b5caf543a1e807a7ddc4552a3b9a6321d248adc1c471d`. Reusing the established environment resolved this prerequisite; the complete subsequent batch below passed.
- Candidate log folder: `/tmp/v24-mf1-candidate-evidence-20261025/`; log numbers match the command ledger. Result columns below preserve the actual last result line (not raw logs).

| # | executed_at (+08:00) | command | exit | result | log SHA-256 |
|---:|---|---|---:|---|---|
| 1 | 2026-10-25T20:17:18.956976+08:00 | `uv run python v24/s12/test_g11.py` | 0 | `[passed] v24 G11 Fake-only: 12 case(s)` | `a4881cbfa8527ddcc1ef9140c30d40f347fca5361c716a1421306a58fdb51880` |
| 2 | 2026-10-25T20:17:21.834155+08:00 | `uv run python v24/s12/test_g11.py --only G11-A` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `7e3f9718e038351dc10952eda17cc4661fa08a2d4f67593ff22a5dffd71a00ef` |
| 3 | 2026-10-25T20:17:23.125916+08:00 | `uv run python v24/s12/test_g11.py --only G11-B` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `7cc3f3571fb7b03651fb0ead707b8da69a7ce97f3a4a30624bb6cd186bf6ecda` |
| 4 | 2026-10-25T20:17:24.331894+08:00 | `uv run python v24/s12/test_g11.py --only G11-C` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `73d0d3d6efa15f9ad13d774791a8f3e20a3788db43fde22573e876f4a406a389` |
| 5 | 2026-10-25T20:17:25.725940+08:00 | `uv run python v24/s12/test_g11.py --only G11-D` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `d7da58314514d3b9dfa99cc499586647696c0344b85380708ad4ce3ebf5eeb07` |
| 6 | 2026-10-25T20:17:26.882715+08:00 | `uv run python v24/s12/test_g11.py --only G11-E` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `0dea33e22359e05445a37d443f411cbd1846b3b669ddbba14dc12f1d1e452430` |
| 7 | 2026-10-25T20:17:28.052660+08:00 | `uv run python v24/s12/test_g11.py --only G11-F` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `703b3efd8635536ec542cc21b4f239cfef4b6ec51c0626fd014fac3f56239dbb` |
| 8 | 2026-10-25T20:17:29.252798+08:00 | `uv run python v24/s12/test_g11.py --only G11-G` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `091f76d03bf8914fe1a93fea7a029c011c71904644d3478257fa5f715b779f5b` |
| 9 | 2026-10-25T20:17:30.407354+08:00 | `uv run python v24/s12/test_g11.py --only G11-H` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `43e96ba88c944cdc53d014c87a305728a46f26f39e7529c799cfcb0322619aec` |
| 10 | 2026-10-25T20:17:31.525017+08:00 | `uv run python v24/s12/test_g11.py --only G11-I` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `ad3395336af6f2b58aa2eec57a3acbd8b094485b0d5f65fe9daebd64b7181ffa` |
| 11 | 2026-10-25T20:17:32.687649+08:00 | `uv run python v24/s12/test_g11.py --only G11-J` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `14a6f70aabf06093a18b078f4e749df38444a006c4fc3e34ae65f17086633795` |
| 12 | 2026-10-25T20:17:33.914827+08:00 | `uv run python v24/s12/test_g11.py --only G11-K` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `a57352f8ead6f025bd6b3ed5c5c758e0ad3ccfaa53a32004eaf95b892995ac0e` |
| 13 | 2026-10-25T20:17:35.116739+08:00 | `uv run python v24/s12/test_g11.py --only G11-L` | 0 | `[passed] v24 G11 Fake-only: 1 case(s)` | `59595cd8a2124b7a48a334b8c42b51cf18d39084b25b96b44f162c60863b8374` |
| 14 | 2026-10-25T20:17:36.319645+08:00 | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `0bbe6bbe8a76de58cb90ccda01b64b63e5ba722901e7a696600775bf9858c111` |
| 15 | 2026-10-25T20:17:36.357705+08:00 | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `e3dfabf8ca6e475ea3e3d0fb991016e9fa58b984bc9e460b3bcb2a977867a775` |
| 16 | 2026-10-25T20:17:36.964013+08:00 | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `5c3faf12589c53acfd4f38456e8b8c6499a8496a6125c1a0c89865dc605d0d5b` |
| 17 | 2026-10-25T20:17:37.608986+08:00 | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `624423a1851c086aab36540f5c04750446882fa9113bb2200f8505603f0acf14` |
| 18 | 2026-10-25T20:17:39.213482+08:00 | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `738f89dc82a7a9746d36d62c121d05002555f4c4ae8f8b7e7224adc7532cd11e` |
| 19 | 2026-10-25T20:17:40.119604+08:00 | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `1a79eca302e22512d1eedfa3bec0c5d6eb326ee97d9c254120001a00639bb94f` |
| 20 | 2026-10-25T20:17:44.645519+08:00 | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `0ab36d987ffbe40416d869db674b559bcb22c8515603bced4f5ab926af899a63` |
| 21 | 2026-10-25T20:17:47.647103+08:00 | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `a6c138e637c16536ed49009da2ab837e311c8e29a16bb19c796a7ce7b6fbff18` |
| 22 | 2026-10-25T20:17:49.951621+08:00 | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `fc08facfe82f908d57b6ec82ad860ad46dde584450ea2dcff9e2968f499b0553` |
| 23 | 2026-10-25T20:17:54.302366+08:00 | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `c723740a0887678d66b1284c8cc9d6c0ec508ff25c6591c56f54e74675d4833a` |
| 24 | 2026-10-25T20:17:56.181659+08:00 | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `27c95030af0daa1ac19ac9d53280ca2176e4436e92b9288db7f174452d976dc0` |
| 25 | 2026-10-25T20:18:03.874806+08:00 | `uv run python v24/s9/test_g8.py` | 0 | `[passed] v24 G8 host reads / closure / lease / recovery: 23 case(s)` | `7c35d6d5e374dae32fcb42c0abbf42aa0511a47a66fbe98c390e028a647517f3` |
| 26 | 2026-10-25T20:18:14.662087+08:00 | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `e0c145627a487201235b787cc2eea20ff22eaf85bea88f122f7831b062a1c26d` |
| 27 | 2026-10-25T20:18:16.892897+08:00 | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `35a2720154057399faf32f2d1576846712cb950a082b0e106cdb4314f9829a19` |
| 28 | 2026-10-25T20:18:19.156219+08:00 | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/opt/homebrew/bin/node` | `d4b8f66020020ab34e8bc273a6972a7919260f35db916f1b511ca463940dacfd` |
| 29 | 2026-10-25T20:18:20.339359+08:00 | `uv run python -m v24.host.smoke` | 0 | `not_requested` | `aed9e26cb7a44d69c625f8c0842dc15a89487bab04069479642ec497b57fa6c2` |
| 30 | 2026-10-25T20:18:20.409217+08:00 | `uv run python -m v24.host.plugin_smoke` | 0 | `not_requested` | `aed9e26cb7a44d69c625f8c0842dc15a89487bab04069479642ec497b57fa6c2` |
| 31 | 2026-10-25T20:18:20.493362+08:00 | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/opt/homebrew/bin/node final=ok` | `65cd9039d7bd543fcfc02294b22d3f15859e25f6b03e8f03b9e33044e532dacb` |
