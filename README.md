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

&#x20;               │ REST + WebSocket

┌───────────────▼─────────────────────────────────────────────┐

│                   后端（Python 3.11+ / FastAPI）             │

│  数据层: GPS模拟生成器(随机游走+潮汐) → 清洗(漂移过滤/去重) │

│  算法层: DBSCAN+K-means 双阶段聚类(scikit-learn)          │

│           → CVRP 车辆路径求解(Google OR-Tools)             │

│  仿真层: SimPy 离散事件仿真(无调度/阈值/预测 三类策略)      │

└─────────────────────────────────────────────────────────────┘
```

## 目录结构



```
校园共享单车智能调度系统/

├── backend/                     # 后端（FastAPI）

│   ├── main.py                  # 应用入口 + WebSocket

│   ├── config.py                # 全局可配置参数

│   ├── geo.py                   # 像素<->经纬度映射、距离计算

│   ├── service.py               # 运行时状态管理（模拟线程/缓存）

│   ├── data/

│   │   ├── gps\_simulator.py     # 模拟GPS数据源（随机游走+潮汐）

│   │   └── cleaner.py           # GPS漂移过滤、重复去重

│   ├── algorithms/

│   │   ├── clustering.py        # DBSCAN + K-means 双阶段聚类

│   │   ├── cvrp\_ga.py           # CVRP + 改进遗传算法求解

│   │   └── simulation.py        # SimPy 离散事件仿真

│   ├── api/routes.py            # REST 接口

│   └── assets/campus\_map.jpg    # 校园俯瞰图

├── frontend/                    # 前端（Vue3 + Vite + Leaflet）

│   └── src/

│       ├── App.vue              # 主布局

│       └── components/

│           ├── MapView.vue      # 底图/热力图/区域/路线

│           ├── TaskPanel.vue    # 调度任务面板

│           └── SimChart.vue     # 仿真对比图表

└── tests/                       # 自动化测试
```

## 快速运行

### 1. 后端（端口 8000）



```
cd backend

python3 -m venv .venv

.venv/bin/pip install -r requirements.txt   # fastapi/uvicorn/numpy/simpy/scikit-learn/ortools

.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2. 前端（端口 5173，开发模式）



```
cd frontend

npm install

npm run dev
```

浏览器访问 [http://localhost:5173](http://localhost:5173) 。

### 3. 生产模式（后端托管前端构建产物）



```
cd frontend && npm run build

\# 构建完成后直接访问 http://localhost:8000 即可
```

## 主要接口



| 方法   | 路径                 | 说明               |
| ---- | ------------------ | ---------------- |
| GET  | /api/health        | 系统状态             |
| GET  | /api/config        | 全部可配置参数          |
| GET  | /api/hotspots      | 校园热点列表           |
| GET  | /api/bikes         | 当前单车位置快照         |
| POST | /api/clusters/scan | 手动触发双阶段聚类扫描      |
| GET  | /api/clusters      | 最近一次聚类结果         |
| POST | /api/dispatch      | CVRP 遗传算法求解调度方案  |
| POST | /api/simulation    | SimPy 三类调度策略仿真对比 |
| WS   | /ws/gps            | 实时 GPS 数据流       |

## 地图标定说明

校园俯瞰图（`campus_map.jpg`）与真实经纬度的映射关系配置在

`backend/config.py` 的 `MAP` 字段（四角经纬度）。

**当前默认值仅为演示标定**，请按实际校园俯瞰图四角坐标修改：



```
MAP = {

&#x20;   "top\_left":     {"lat": ..., "lng": ...},   # 底图左上角

&#x20;   "top\_right":    {"lat": ..., "lng": ...},   # 底图右上角

&#x20;   "bottom\_left":  {"lat": ..., "lng": ...},   # 底图左下角

&#x20;   "bottom\_right": {"lat": ..., "lng": ...},   # 底图右下角

}
```

## 关键技术实现

### 双阶段聚类（`algorithms/clustering.py`，基于 scikit-learn）



* **阶段一 DBSCAN**：`sklearn.cluster.DBSCAN` 识别聚集区域与噪声点（经纬度先投影为米制坐标）

* **阶段二 K-means**：`sklearn.cluster.KMeans` 对簇内点位二次聚类，按 `单车数/区域容量` 划分堆积等级 (1\~3 级)

* **空缺区识别**：热点周边 150m 内单车密度低于期望值的 40% 判定为空缺区

### CVRP 调度求解（`algorithms/cvrp_ga.py`，基于 Google OR-Tools）



* `ortools` RoutingModel：距离矩阵（米）+ 容量维度（AddDimensionWithVehicleCapacity）

* 初始解策略 `PATH_CHEAPEST_ARC` + 引导式局部搜索 `GUIDED_LOCAL_SEARCH`

* 求解时间上限可配置（`config.py` 中 `CVRP.solver.time_limit_seconds`）

* 需求超过车辆容量的区域自动拆分为多趟任务

### SimPy 离散事件仿真（`algorithms/simulation.py`）



* 泊松到达 + 教学日潮汐模型模拟借还行为

* 三类策略对比：无调度 / 阈值触发 / 预测性

* 评估指标：周转率、调度成本、供需匹配率、平均等待时间

## 测试



```
cd backend

.venv/bin/python data/gps\_simulator.py        # 数据生成器自测

.venv/bin/python data/cleaner.py              # 清洗自测

.venv/bin/python algorithms/clustering.py     # 聚类自测

.venv/bin/python algorithms/cvrp\_ga.py        # CVRP 自测

.venv/bin/python algorithms/simulation.py     # 仿真自测

.venv/bin/python -m pytest ../tests/          # 自动化测试（需安装 pytest）
```