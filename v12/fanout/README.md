# v12 G5 · fanout —— 行集排序（semantic_find 模式）

Gate: `uv run python v12/fanout/test_fanout.py`（退出码 0 = 通过）

## 机制

- **一个问题排整表**：一个 Choice，选项 = 行 ID（L0007 式），概率分布即
  全表排名；**存在性靠 Noul**——Choice 概率恒和为 1，自己表达不了
  「都不匹配」。
- **≤255 行单遍**（`v12_fanout_open_lines`）；**>255 行两遍**
  （`v12_fanout_open_windows` → `v12_fanout_narrow`）：先按窗口 Choice
  定位，再在胜出窗口内做行 Choice。窗口 state 携带窗口全文，行 state
  携带全部行文本——判断材料都在 state 里，instructions 只引用路径。
- **问题由 SQL 从表生成**（criteria = 行 ID 集合），**排名由 SQL 从
  答案展开回表行**（`v12_fanout_top`）——「问」与「答」都是行集操作。
- **裁决走阈值**：`v12_fanout_verdict` 读 exists 的路由带
  （fanout/exists: 0.7/0.35，fallback=absent），排名再高、存在性不足
  也判 absent。

## DuckDB 扩展点（不在 gate 内）

`fanout_docs` / `jev_batches` / `jev_decisions` 都是普通表：DuckDB 经
postgres_scanner（或 pg_duckdb）读同一批表做分析侧批量扇出——分类、
重排、实体对齐与行级打分共用同一「问题=行、答案=行」协议；离线侧再
用历史 decisions 画置信度-准确率曲线，调好的阈值写回 `thresholds`。
