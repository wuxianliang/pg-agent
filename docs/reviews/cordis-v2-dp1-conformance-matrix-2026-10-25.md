# Cordis v2 DP1 Conformance Matrix

P0 executed on commit `57e2c1e0fff693447f406f8202472eb73db0b285`; Python/psycopg2 and PostgreSQL were recorded by the run. Exit codes below are actual process results.

| Gate | Command | Exit | Seconds | Evidence / scope |
|---|---|---:|---:|---|
| P0 | `uv run python v24/load.py` | 0 | 0.05 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 0.72 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s1/test_ddl.py` | 0 | 0.66 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s1/test_g1.py` | 0 | 1.57 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s2/test_g3a.py` | 0 | 0.91 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s3/test_g2.py` | 0 | 4.42 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s4/test_g2b.py` | 0 | 3.03 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s5/test_g4.py` | 0 | 2.33 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s6/test_g5.py` | 0 | 2.95 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s8/test_g7.py` | 0 | 1.53 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s7/test_g6.py` | 0 | 5.61 | Existing v24 regression gate; see run output in the working run log. |
| P0 | `uv run python v24/s9/test_g8.py` | 0 | 9.83 | Existing v24 regression gate; see run output in the working run log. |

PG: 18.4 (180004), psycopg2 from environment self-check.

W1/CDP1-E loader, socket-only fixture, cleanup and catalog assertions are implemented and being exercised. Update this matrix with each actual gate result; no future or unrun result is implied.

## Frozen v24 baseline

Manifest order is exactly the following twelve rows. Full v24 loader/SQL/s1–s12 diff against 57e2c1e: exit 0. Local/upstream ahead-behind: 0/0.

| SQL | P0 SHA-256 |
|---|---|
| `00_schema.sql` | `05b6b47e0f71881e64fba3c55609c16608e4bc15c44f321ad5a87ede7979bc6d` |
| `10_schema.sql` | `a365a235edefe49258038bef4b28a3cd5f8204ab22a71336e892efc706cbae76` |
| `20_triggers.sql` | `1c75ce97c79abdba9151bd8dfd22bb7b1167c10e256ed8fa54d4adf927da5af1` |
| `30_advance.sql` | `087a5bcdb4b9132e25b2d04bc0a31606d429fba5d5cfbb0a257f0a2440715870` |
| `40_interpreters.sql` | `2ebefff558f243891a613787a47ef68dcfb825b1bcc16b78f019e328f982c5f9` |
| `45_capability.sql` | `f629ddd511754a4828da4b4dc4da278c1a4bfcb2359f15f00fd6634f9e4f332e` |
| `46_cleanup.sql` | `bb32336bf6e262f62a55a78d55bf3ac7b649c06a50bdda9eda6263f96ed083ef` |
| `47_verbs.sql` | `5c5bdc611f33f5b37d1652f29aeda97323882487c27cf800ac53371a76ea0265` |
| `48_loop.sql` | `f23a93cdd5c14966442bf30eb1339b6e110c3b1c279b95650704aa9e12870f30` |
| `49_recovery.sql` | `b46abde9f5fc4259f9ea833440ca0c0815a4a14a578e058b861f59990d90af8d` |
| `49_host_reads.sql` | `242748a0fe29cbedc723df9d5de18dd1fba7e9767cfce56a3bc218d1a17ce6c4` |
| `50_permissions.sql` | `578cba9fefc0e0238d6ffd42e458b235bd59ae56a7fa6b1f84a2de36fddbdafe` |

## W1 actual results

| Command | Exit | Assertions |
|---|---:|---|
| `uv run python v24/cordis/load.py` | 0 | Exact 15-file canonical tuple; five refusal families |
| `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | PG 18.4, one-transaction load, exact owner/catalog and database/role OID cleanup |
| `uv run python v24/cordis/dp1/test_environment.py` | 0 | CDP1-E1/E2/E3, empty/current prefix, DSN/environment rejection, caller transaction, core functions |

W2/CDP1-D and W3/CDP1-K: not implemented or run. Existing v24 s9 gate reported 23 passing named cases.
