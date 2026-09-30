# v13 workspace_exec

Phase B 第二段。无 SQL，无加载键。另一份脚本上的 edit、write、bash、grep、find、ls。Fake 退出码 0 不是产品可用。本目录不授权无人值守。bash 不是系统 shell。崩溃 `claimed` 行留给 G4。本 gate 不证明 material 收据。

## 使用域

PB-4 夹具的 owner 是本目录测试文件里的 `Volume`，不是 `setup_db.py`，也不是适配器。挂载、`Foo`/`foo` 探针、三标志（镜像已创建 / 已 attach / 库已 `CREATED`）、`detach` 与删镜像的独立 try，都在 `test_workspace_exec.py`。ASCII 往返在 `audit_tree`（`workspace_root_is_mount` 与 `fixture_bound_only` 各跑一次）。inode 碰撞探针在 `Volume._probe`（`a`/`ab`）以及 `audit_tree`。这些是实测位置，不是「gate 退出码 0 即视为探针已做」。

工作区根是系统临时目录树下的 cs-APFS 挂载点路径字符串本身。不是仓库根，不是 `/`，不是 `/Volumes`。不调用 `realpath` 改写它。镜像文件不是根。

挂载：`hdiutil create -size 64m -fs "Case-sensitive APFS" -type SPARSE` 写到 `$TMPDIR` 下唯一名镜像。已存在则拒绝，不覆盖。`hdiutil attach -mountpoint $TMPDIR/<唯一名>/ws`，挂载点目录预先建空。只处理本进程创建的资源。三标志分开：镜像已创建、已 attach、库已 `CREATED`。

挂载后、任何 effect 打开前，跑 `Foo`/`foo` 探针：两名字独占创建（`O_NOFOLLOW`），目录项字节互异，`st_dev`+`st_ino` 不同，然后删除且不进 `paths`。失败即停，不回落默认 APFS，非零退出，不报通过。

使用域路径分量纯 ASCII。每个声明或创建的名字做 listdir 字节往返。使用域内不同字符串不得同一 `st_dev`+`st_ino`。

NFC/NFD 查找折叠保留在使用域外。使用域内由纯 ASCII、往返和碰撞探针覆盖。不声称此卷无 Unicode 别名。台账 PB-4。

## 清理

测试 fixture 的 `finally` 里 detach、删镜像、DROP 库各自独立 try。create 成功而 attach 失败则删镜像并退出非零。探针失败则先清镜像再 DROP 库，退出非零。detach 失败只记 `[cleanup-fail]`，不阻塞 DROP，但该次运行不得记 `exit_0`。断言已过后清理失败：库仍 DROP，进程非零退出。

`setup_db.py`：建库成功后 `CREATED=True`。`load_stage` 失败则本函数独立 DROP 本次创建的库（DROP 成功则清 `CREATED`）；成功路径把库交给外层测试 fixture，由它的 `finally` DROP。

## 驱动

`driver.py` 只调用 `v13_workspace_policy`、`v13_tool_effect_open`、`v13_tool_result_accept`。打开者事务是 `READ COMMITTED`，事务内没有文件 IO。适配器在连接 `IDLE` 时运行。接受是其后的另一个事务。`replayed` 且已成功则不执行、不接受。不确定结局不调用接受，行保持 `claimed`。进程内闭集动词来自政策 `bash_verbs`，不是 shell。临时名 `.v13tmp-` 加 `attempt_key` 只由适配器创建，不得逃出根。

## Gate

`UV_FROZEN=1 uv run python v13/workspace_exec/test_workspace_exec.py`

断言名按计划 §5.2。

证据：退出码 0；54 checks（含 `temp_component_closed` / `root_fd_rechecked` / `idle_after_on_io`）；库 `ll_workspace_exec_87590_06f189`（跑完已 DROP）。Fake 退出码 0 不是产品可用。父补审 group `44C31F75` 四条 P1 已跟进。未改 `workspace_admit` SQL。
