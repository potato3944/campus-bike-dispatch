# 校园共享单车智能调度管理平台

基于 **聚类算法 + 仿真模拟** 的校园共享单车智能调度系统。

对应综合工程设计选题报告《基于位置感知的智能校园共享单车调度系统》。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                       前端（Vue3 + Vite）                    │
│  MapView(Leaflet底图/热力图/区域标注/调度路线)               │
│  TaskPanel(调度任务)  SimChart(ECharts仿真对比)             │
└───────────────┬─────────────────────────────────────────────┘
                │ REST + WebSocket
┌───────────────▼─────────────────────────────────────────────┐
│                   后端（Python 3.11+ / FastAPI）             │
│  数据层: GPS模拟生成器(随机游走+潮汐) → 清洗(漂移过滤/去重)  │
│  算法层: DBSCAN+K-means 双阶段聚类(scikit-learn)            │
│           → CVRP 车辆路径求解(改进遗传算法 / OR-Tools 可切换) │
│  仿真层: SimPy 离散事件仿真(无调度/阈值/预测 三类策略)       │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
校园共享单车智能调度系统/
├── backend/                     # 后端（FastAPI）
│   ├── main.py                  # 应用入口 + WebSocket
│   ├── config.py                # 全局可配置参数（可经 POST /api/config 运行时覆盖）
│   ├── geo.py                   # 像素<->经纬度映射、距离计算
│   ├── service.py               # 运行时状态管理（模拟线程/缓存/参数配置）
│   ├── data/
│   │   ├── gps_simulator.py     # 模拟GPS数据源（随机游走+潮汐）
│   │   ├── cleaner.py           # GPS漂移过滤、重复去重
│   │   └── scenario_engine.py   # 预设潮汐场景演化帧生成（带结果缓存）
│   ├── algorithms/
│   │   ├── clustering.py        # DBSCAN + K-means 双阶段聚类
│   │   ├── cvrp_ga.py           # CVRP 求解（改进遗传算法 + OR-Tools 对照）
│   │   └── simulation.py        # SimPy 离散事件仿真
│   ├── api/routes.py            # REST 接口
│   └── assets/campus_map.jpg    # 校园俯瞰图
├── frontend/                    # 前端（Vue3 + Vite + Leaflet）
│   └── src/
│       ├── App.vue              # 主布局
│       └── components/
│           ├── MapView.vue      # 底图/热力图/区域/路线
│           ├── TaskPanel.vue    # 调度任务面板
│           └── SimChart.vue     # 仿真对比图表
├── docs/                        # 运行截图与演示剧本
├── tests/                       # 自动化测试
└── start.sh                     # 一键启动（后端 + 前端生产托管）
```

## 快速运行

### 0. 一键启动（推荐，生产托管模式）

```bash
./start.sh          # 自动构建前端（如缺失）并启动后端，浏览器访问 http://localhost:8000
```

### 1. 后端（端口 8000）

```
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # fastapi/uvicorn/numpy/simpy/scikit-learn/ortools/pytest
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2. 前端（开发模式，端口以 vite.config.js 为准，默认 5174）

```
cd frontend
npm install
npm run dev
```

浏览器访问 [http://localhost:5174](http://localhost:5174)。

### 3. 生产模式（后端托管前端构建产物）

```
cd frontend && npm run build
# 构建完成后直接访问 http://localhost:8000 即可
```

## 主要接口

| 方法   | 路径                 | 说明               |
| ---- | ------------------ | ---------------- |
| GET  | /api/health        | 系统状态             |
| GET  | /api/config        | 全部可配置参数          |
| POST | /api/config        | 运行时修改参数（白名单校验，改完即生效） |
| GET  | /api/hotspots      | 校园热点列表           |
| GET  | /api/bikes         | 当前单车位置快照         |
| POST | /api/clusters/scan | 手动触发双阶段聚类扫描（可覆盖聚类参数） |
| GET  | /api/clusters      | 最近一次聚类结果         |
| POST | /api/dispatch      | CVRP 求解调度方案（返回 GA / OR-Tools 对比） |
| POST | /api/simulation    | 三类调度策略仿真对比（结果缓存，可 `force` 重算） |
| GET  | /api/scenarios     | 预设潮汐场景列表         |
| GET  | /api/scenario/{id} | 指定场景的演化帧序列（带缓存）  |
| GET  | /api/evolution     | 早高峰聚集演化回放帧       |
| WS   | /ws/gps            | 实时 GPS 数据流（附带最近聚类结果） |

### 参数覆盖示例

聚类 / 调度 / 仿真接口均支持在请求体中覆盖默认参数，便于做参数敏感性实验；
取值越界由接口统一返回 `422`。

```bash
# 用更小的 eps 重新扫描聚类
curl -X POST http://localhost:8000/api/clusters/scan \
  -H 'Content-Type: application/json' \
  -d '{"eps_m": 45, "min_samples": 8}'

# 指定用 OR-Tools 作为主算法，并调整车辆数
curl -X POST http://localhost:8000/api/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"algorithm": "ortools", "vehicle_num": 8}'

# 只跑预测性策略，缩短仿真时长
curl -X POST http://localhost:8000/api/simulation \
  -H 'Content-Type: application/json' \
  -d '{"strategy": "predictive", "duration_h": 4}'

# 运行时改参（改完失效缓存，下一次计算即生效）
curl -X POST http://localhost:8000/api/config \
  -H 'Content-Type: application/json' \
  -d '{"cluster": {"eps_m": 120}, "cvrp": {"vehicle_num": 6}}'
```

## 地图标定说明

校园俯瞰图（`campus_map.jpg`）与真实经纬度的映射关系配置在
`backend/config.py` 的 `MAP` 字段（四角经纬度）。

**当前默认值仅为演示标定**，请按实际校园俯瞰图四角坐标修改：

```
MAP = {
    "top_left":     {"lat": ..., "lng": ...},   # 底图左上角
    "top_right":    {"lat": ..., "lng": ...},   # 底图右上角
    "bottom_left":  {"lat": ..., "lng": ...},   # 底图左下角
    "bottom_right": {"lat": ..., "lng": ...},   # 底图右下角
}
```

## 关键技术实现

### 双阶段聚类（`algorithms/clustering.py`，基于 scikit-learn）

* **阶段一 DBSCAN**：`sklearn.cluster.DBSCAN` 识别聚集区域与噪声点（经纬度先投影为米制坐标）
* **阶段二 K-means**：`sklearn.cluster.KMeans` 对簇内点位二次聚类，按 `单车数/区域容量` 划分堆积等级（1~3 级）
  - 堆积等级按**整个 DBSCAN 簇**的总量评级；K-means 子簇仅用于把一个堆积区拆成若干标记点便于展示
  - 子簇半径计算经 `idx` 映射回全局点集，避免用簇内相对下标取错点
* **空缺区识别**：热点周边 150m 内单车密度低于期望值的 40% 判定为空缺区
* **参数调优提示**：`eps_m` 相对密度过大导致整片校园串成一个大簇时，`stats.warnings` 会给出提示

### CVRP 调度求解（`algorithms/cvrp_ga.py`）

提供两种可切换实现，由 `config.py` 中 `CVRP.algorithm` 决定（默认 `"ga"`）：

* **`ga`：改进遗传算法（默认，对应选题报告）**
  - 贪心最近邻构造初始种群
  - 顺序交叉（OX, Order Crossover）
  - 2-opt 局部搜索（子代扰动 + 最优个体收敛后精修）
  - 精英保留策略
  - 染色体为节点排列，解码时按载重可行性切分为车辆路径，保证任何排列都对应可行解

* **`ortools`：Google OR-Tools RoutingModel（对照实现）**
  - 距离矩阵（米）+ 载重维度，初始解策略 `PATH_CHEAPEST_ARC` + `GUIDED_LOCAL_SEARCH`
  - 求解时间上限可配置（`config.py` 中 `CVRP.solver.time_limit_seconds`）

`POST /api/dispatch` 默认同时运行两个求解器，在 `solver_comparison` 字段中给出
两者的总里程与耗时对比（前端任务面板底部展示），主结果取 `algorithm` 指定的算法。

**载重模型（两种实现统一口径）**
区域净需求 `demand` 正数表示需运走（堆积区），负数表示需投放（空缺区）。
车辆可从调度中心携带初始载荷出发，因此「先投放后取货」也可能可行。
记路径净需求序列的前缀和为 `S_j`，则车上载重 = `L0 + S_j`，其中 `L0` 为初始载荷。
路径可行的充要条件为 `max(S_j) - min(S_j) <= capacity`，
最优初始载荷 `L0 = max(0, -min(S_j))`，峰值载重为前缀和极差。

> 早期实现用 `abs(demand)` 累加载重，会让载重只增不减、无法建模「先投放后取货」，
> 该问题已修正；求解失败时返回 `status="infeasible"` 并说明所需趟数，不再返回空结果冒充成功。

**模型简化假设**：同一车次允许混排取送任务，载重按净需求前缀和口径核算；
未建模严格的时间窗与取送先后约束（PDPTW），列入后续工作。

### SimPy 离散事件仿真（`algorithms/simulation.py`）

* 泊松到达 + 教学日潮汐模型模拟借还行为
* 三类策略对比：无调度 / 阈值触发 / 预测性
  - 预测性策略在预测窗口上均匀采样多个时点求平均（而非用同一未来值重复凑数）
* 调度任务按里程/车速消耗行驶时间后落车，且搬运量受「来源可用量」与「目的地剩余容量」双重约束
* 评估指标：周转率、调度成本、供需匹配率、平均等待时间、实际搬运量、未服务量、超容还车次数
  - 平均等待时间默认覆盖全部需求（含等待后仍失败的用户），并同时给出仅统计成功用户的口径
  - `demand = success + fail + pending`，仿真结束时仍在等待的请求单列为 `pending_count`

## 性能与缓存

* 仿真结果按参数缓存，重复调用直接命中（`POST /api/simulation` 传 `force: true` 可强制重算）
* 预设场景演化帧按 `(scenario_id, total_bikes, num_frames)` 缓存，切换场景秒开
* 调度求解只在锁外进行，求解期间 GPS 模拟线程与 WebSocket 推送不中断

## 测试

```
cd backend
.venv/bin/pip install -r requirements.txt          # 已包含 pytest
.venv/bin/python data/gps_simulator.py        # 数据生成器自测
.venv/bin/python data/cleaner.py              # 清洗自测
.venv/bin/python algorithms/clustering.py     # 聚类自测
.venv/bin/python algorithms/cvrp_ga.py        # CVRP 自测（GA 与 OR-Tools 对照）
.venv/bin/python algorithms/simulation.py     # 仿真自测
.venv/bin/python -m pytest ../tests/ -v       # 自动化测试
.venv/bin/python ../tests/api_contract_check.py   # 接口契约自检（独立进程）
```

测试覆盖：数据生成、GPS 清洗（含非法坐标/时间戳拒绝）、双阶段聚类（含半径索引与分级口径）、
CVRP 载重可行性与失败状态、GA 与 OR-Tools 一致性、仿真指标守恒、接口参数校验与路由注册。
