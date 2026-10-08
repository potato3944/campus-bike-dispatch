# CHANGELOG

本项目按改进方案（见 `改进方案.md`）分版本迭代。版本门禁：单元测试全绿 + 演示流程无卡顿无空图。

## [v1.0-baseline] - 2026-09-29
- 评审前现状固化：项目已有可运行的前后端、5 个单元测试通过。

## [v1.1] - 2026-09-29
- T2 修复预测策略无效采样：预测窗口上均匀采样 5 个时点求平均，而非同一未来值重复凑数（`algorithms/simulation.py`）
- T6 KPI 调度车辆数改为读取后端配置，不再硬编码 2（`frontend/src/App.vue`）
- T3 实时监测模式补充聚类/热力数据：WS 推送附带最近一次聚类结果，前端 `liveClusters` 正确赋值（`backend/main.py`、`backend/service.py`、`frontend/src/App.vue`）
- T5 dispatch 求解移出大锁：锁内仅快照与写回，求解期间 WebSocket 推送不中断（`backend/service.py`）

## [v1.2] - 2026-09-29
- T1 完善改进遗传算法求解 CVRP：`GeneticCVRPSolver`（贪心初始解 + 顺序交叉 OX + 2-opt + 精英保留）；
  `/api/dispatch` 默认同时运行 GA 与 OR-Tools 并返回 `solver_comparison` 对比；任务面板展示求解对比（`backend/algorithms/cvrp_ga.py`、`backend/service.py`、`frontend/src/components/TaskPanel.vue`）
- **fix: GA 种群初始化死循环**——`pop_size > n!` 时（失衡区域很少，如 n=4 仅 24 种排列却要凑 60 个互异个体）
  `_init_population` 永远无法退出，导致 `/api/dispatch` 卡死；改为按 `min(pop_size, n!)` 定目标并加兜底退出（`backend/algorithms/cvrp_ga.py`）
- T4 结果缓存：仿真结果按参数缓存（`force` 可强制重算），场景演化帧按 key 缓存，图表加载态加提示文案
- T7 新增 `POST /api/config` 运行时参数配置接口（白名单 + 范围校验，改参即失效缓存）

## [v1.3] - 2026-09-29
- T8 CVRP 载重模型修正并书面化：净需求前缀和口径，支持「先投放后取货」，失败返回 `infeasible`
- T9 仿真超容还车单独计数（`overflow_returns`），作为「乱停放」量化指标
- T10 README 清理转义残留、更新目录树与接口表；新增 `.gitignore` 与本 CHANGELOG
- T11 补充回归测试与接口契约自检脚本（`tests/test_improvements.py`、`tests/api_contract_check.py`）
- T12 新增 `start.sh` 一键启动脚本与 `docs/演示剧本.md`
- T13 重建前端 `dist` 构建产物
