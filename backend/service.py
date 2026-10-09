# -*- coding: utf-8 -*-
"""
运行时服务层
管理 GPS 模拟线程、数据清洗、缓存、聚类与调度结果的实时状态，
供 REST 接口与 WebSocket 消费。

健壮性约定：
  - 后台模拟线程内任何异常都会被捕获并记录，不会静默终止线程；
  - 对外读取状态统一走 snapshot()，在锁内复制，避免 WebSocket 读到半更新快照；
  - 被清洗模块拒绝的 GPS 点不会刷新缓存时间戳，避免出现「坐标是旧的、时间是新的」的错位数据；
  - 重计算（聚类 / 调度 / 仿真）只在锁内做快照与写回，耗时计算放在锁外，
    避免阻塞 GPS 模拟线程与 WebSocket 推送。

参数可配置：
  - 运行时参数集中在 self.config（config.py 的深拷贝），所有计算都读 self.config，
    因此 POST /api/config 修改后立即生效，无需重启；
  - 支持的结果缓存可通过 force=True 强制失效。
"""

import copy
import threading
import time
import traceback
from datetime import datetime, timedelta

import config
from data.gps_simulator import GpsSimulator, HOTSPOTS
from data.cleaner import DataCleaner
from algorithms.clustering import detect_imbalance
from algorithms.cvrp_ga import create_solver, build_cvrp_input, summarize_cvrp_input
from algorithms.simulation import run_all_strategies

VALID_STRATEGIES = ("none", "threshold", "predictive")

# POST /api/config 允许修改的白名单：(分组, 键, 类型, 最小值, 最大值)
# 只暴露对演示/实验有意义、且不会破坏系统稳定性的参数。
CONFIG_WHITELIST = {
    "cluster": {
        "eps_m": (float, 20.0, 200.0),
        "min_samples": (int, 2, 20),
        "k_levels": (int, 1, 10),
        "scan_interval_s": (int, 5, 3600),
    },
    "cvrp": {
        "vehicle_capacity": (int, 1, 1000),
        "vehicle_num": (int, 1, 50),
    },
    "simulation": {
        "duration_h": (float, 1.0, 72.0),
        "arrival_rate_per_h": (float, 1.0, 100000.0),
        "seed": (int, 0, 2 ** 31 - 1),
        "threshold_imbalance": (int, 0, 10000),
        "predict_window_min": (float, 1.0, 720.0),
        "check_interval_min": (float, 1.0, 240.0),
    },
    "bike": {
        "total": (int, 1, 5000),
        "capacity_per_zone": (int, 1, 2000),
    },
}


class ConfigError(ValueError):
    """参数配置非法（键不在白名单 / 取值越界 / 类型错误）。"""


class BikeService:
    """校园单车系统运行时状态（单例）"""

    def __init__(self):
        # 深拷贝，避免运行时改参污染 config 模块常量
        self.config = copy.deepcopy({
            "map": config.MAP,
            "bike": config.BIKE,
            "cluster": config.CLUSTER,
            "cvrp": config.CVRP,
            "simulation": config.SIMULATION,
        })
        self.hotspots = HOTSPOTS
        self.simulator = GpsSimulator(total_bikes=self.config["bike"]["total"], seed=7)
        self.cleaner = DataCleaner(
            max_speed_kmh=self.config["bike"]["max_speed_kmh"])
        self._lock = threading.Lock()
        self.sim_time = datetime(2026, 9, 21, 7, 30, 0)   # 模拟起始：早高峰开始
        self.all_bikes = {}
        for b in self.simulator.bikes:
            pt = b.to_dict(self.sim_time.isoformat())
            self.all_bikes[b.id] = pt
        self.bike_points = list(self.all_bikes.values())
        self.recent_points = list(self.bike_points)
        self.last_cluster = None
        self.last_dispatch = None
        self.last_simulation = None
        self.rejected_points = 0        # 被清洗模块丢弃的点位计数
        self._last_scan_sim_time = None
        self._running = False
        self._thread = None
        self.last_error = None

    # ------------------------------------------------------------------ 线程
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="bike-sim-loop")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def _loop(self):
        """模拟推进循环：每 1 秒推进 10 秒模拟时间"""
        while self._running:
            t0 = time.time()
            try:
                self._step_once()
            except Exception as exc:      # noqa: BLE001 - 后台线程必须兜住所有异常
                self.last_error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
            # 控制节奏：1 秒墙钟 = 10 秒模拟时间
            time.sleep(max(0.1, 1.0 - (time.time() - t0)))

    def _step_once(self):
        """推进一个模拟步：生成事件 -> 清洗 -> 更新缓存 -> 周期性聚类。"""
        with self._lock:
            self.sim_time += timedelta(seconds=10)
            events = self.simulator.step(self.sim_time, dt_s=10.0)
            for ev in events:
                pt = self.cleaner.clean(ev)
                if pt is not None:
                    self.all_bikes[pt["bike_id"]] = pt
                else:
                    # 被拒绝的点不更新缓存：保留上一个有效位置，
                    # 也不刷新时间戳，避免「旧坐标 + 新时间」的错位快照。
                    self.rejected_points += 1
            self.recent_points = list(self.all_bikes.values())
            self.bike_points = list(self.all_bikes.values())
            should_scan = self._due_for_scan()
        # 聚类较重，放到锁外执行，避免长时间阻塞 WebSocket 快照读取
        if should_scan:
            self.scan_clusters()

    def ingest_point(self, point):
        """接收外部 GPS 点并走同一套清洗、去重和缓存流程。

        内置模拟线程和 ``/ws/gps`` 外部推送都调用这条路径，确保数据质量
        规则一致；被拒绝的点不会覆盖上一条有效位置。
        """
        normalized = dict(point or {})
        if normalized.get("ts") is None and normalized.get("timestamp") is not None:
            normalized["ts"] = normalized["timestamp"]
        with self._lock:
            cleaned = self.cleaner.clean(normalized)
            if cleaned is None:
                self.rejected_points += 1
                return None
            self.all_bikes[cleaned["bike_id"]] = cleaned
            self.recent_points = list(self.all_bikes.values())
            self.bike_points = list(self.all_bikes.values())
            return dict(cleaned)

    def _due_for_scan(self):
        """判断是否到达聚类扫描周期（调用方需持有锁）。"""
        interval_s = max(1, int(self.config["cluster"]["scan_interval_s"]))
        if self._last_scan_sim_time is None:
            return True
        elapsed = (self.sim_time - self._last_scan_sim_time).total_seconds()
        return elapsed >= interval_s

    # ------------------------------------------------------------------ 快照
    def snapshot(self):
        """在锁内复制一份一致的状态快照，供 WebSocket / REST 读取。"""
        with self._lock:
            return {
                "sim_time": self.sim_time.isoformat(),
                "points": list(self.recent_points),
                "bike_points": list(self.bike_points),
                "cleaner_stats": dict(self.cleaner.stats),
                "rejected_points": self.rejected_points,
                # 附带最近一次聚类结果（含 heat/shortage），
                # 供「实时监测」模式直接渲染聚类圈与热力图，无需额外计算。
                "clusters": self.last_cluster,
            }

    # ------------------------------------------------------------------ 配置
    def apply_config(self, patch):
        """
        按白名单更新运行时参数（POST /api/config）。

        patch: {"cluster": {"eps_m": 120}, "cvrp": {...}, ...}
        校验不通过抛 ConfigError（接口层转 422）；成功则失效相关缓存。
        """
        if not isinstance(patch, dict):
            raise ConfigError("请求体必须是 JSON 对象")
        touched = []
        # 先在副本上校验，全部通过后再一次性写回，避免半更新
        draft = copy.deepcopy(self.config)
        for group, values in patch.items():
            if values is None:
                continue
            if group not in CONFIG_WHITELIST:
                raise ConfigError(f"不支持修改配置分组 '{group}'")
            if not isinstance(values, dict):
                raise ConfigError(f"配置分组 '{group}' 必须是对象")
            for key, val in values.items():
                if key not in CONFIG_WHITELIST[group]:
                    raise ConfigError(f"不支持修改配置项 '{group}.{key}'")
                cast, lo, hi = CONFIG_WHITELIST[group][key]
                try:
                    num = cast(val)
                except (TypeError, ValueError):
                    raise ConfigError(
                        f"配置项 '{group}.{key}' 类型非法，期望 {cast.__name__}")
                if isinstance(val, bool) or not (lo <= num <= hi):
                    raise ConfigError(
                        f"配置项 '{group}.{key}' 取值 {val} 越界，允许范围 [{lo}, {hi}]")
                draft[group][key] = num
                touched.append(f"{group}.{key}={num}")
        if not touched:
            return self.config

        with self._lock:
            self.config = draft
            # 改参后所有派生结果失效
            self.last_cluster = None
            self.last_dispatch = None
            self.last_simulation = None
            self._last_scan_sim_time = None
        return self.config

    # ------------------------------------------------------------------ 计算
    def _scan_locked(self, overrides=None):
        """执行双阶段聚类扫描（调用方需已持有锁）"""
        ov = overrides or {}
        cfg = self.config
        params = {
            "eps_m": ov.get("eps_m", cfg["cluster"]["eps_m"]),
            "min_samples": ov.get("min_samples", cfg["cluster"]["min_samples"]),
            "k_levels": ov.get("k_levels", cfg["cluster"]["k_levels"]),
            "capacity_per_zone": ov.get(
                "capacity_per_zone", cfg["bike"]["capacity_per_zone"]),
        }
        pts = [(p["lat"], p["lng"]) for p in self.bike_points]
        res = detect_imbalance(pts, self.hotspots, **params)
        res["sim_time"] = self.sim_time.isoformat()
        res["params"] = params
        self.last_cluster = res
        self._last_scan_sim_time = self.sim_time
        return res

    def scan_clusters(self, overrides=None):
        """执行双阶段聚类扫描（对外接口，自行加锁）"""
        with self._lock:
            return self._scan_locked(overrides)

    def run_dispatch(self, overrides=None):
        """
        运行 CVRP 调度求解。

        - 锁内只做「快照 + 写回」，耗时求解放在锁外，避免阻塞 GPS 模拟线程与 WS 推送；
        - 默认同时运行改进遗传算法（主结果，题目要求）与 OR-Tools（对照），
          在 solver_comparison 中给出两者的里程与耗时对比；
        - 传 compare=False 可只跑主算法，节省时间。
        """
        ov = overrides or {}
        # ---- 锁内：仅取快照 ----
        with self._lock:
            if self.last_cluster is None:
                self._scan_locked()
            cluster_snapshot = copy.deepcopy(self.last_cluster)
            sim_time = self.sim_time.isoformat()
            cfg = copy.deepcopy(self.config)

        capacity = int(ov.get("vehicle_capacity", cfg["cvrp"]["vehicle_capacity"]))
        vehicle_num = int(ov.get("vehicle_num", cfg["cvrp"]["vehicle_num"]))
        algorithm = ov.get("algorithm", cfg["cvrp"].get("algorithm", "ga"))
        compare = ov.get("compare", True)

        nodes = build_cvrp_input(
            cluster_snapshot["clusters"],
            cluster_snapshot["shortage"],
            cfg["cvrp"]["depot"],
            capacity=capacity,
        )

        # ---- 锁外：求解 ----
        def _solve(algo):
            if algo == "ortools":
                params = {**cfg["cvrp"]["solver"], **ov.get("solver", {})}
            else:
                params = {**cfg["cvrp"]["ga"], **ov.get("ga", {})}
            solver = create_solver(
                cfg["cvrp"]["depot"], nodes,
                capacity=capacity, vehicle_num=vehicle_num,
                params=params, seed=cfg["simulation"]["seed"], algorithm=algo,
            )
            t0 = time.perf_counter()
            out = solver.solve()
            out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
            return out

        primary = _solve(algorithm)

        solver_comparison = {
            algorithm: {"total_distance": primary.get("total_distance", 0.0),
                        "elapsed_ms": primary.get("elapsed_ms", 0.0),
                        "status": primary.get("status")},
        }
        if compare:
            other = "ortools" if algorithm != "ortools" else "ga"
            try:
                alt = _solve(other)
                solver_comparison[other] = {
                    "total_distance": alt.get("total_distance", 0.0),
                    "elapsed_ms": alt.get("elapsed_ms", 0.0),
                    "status": alt.get("status"),
                }
            except Exception as exc:      # noqa: BLE001 - 对照算法失败不影响主结果
                solver_comparison[other] = {
                    "total_distance": None, "elapsed_ms": None,
                    "status": "error", "message": f"{type(exc).__name__}: {exc}",
                }

        # ---- 锁内：仅写回 ----
        res = dict(primary)
        res["sim_time"] = sim_time
        # 附加绘图所需信息
        res["depot"] = cfg["cvrp"]["depot"]
        res["nodes"] = nodes
        res["vehicle_capacity"] = capacity
        res["vehicle_num"] = vehicle_num
        res["algorithm"] = algorithm
        res["solver_comparison"] = solver_comparison
        # 供给/需求守恒诊断：搬出总量与投放总量是否匹配
        balance = summarize_cvrp_input(nodes)
        res["balance"] = balance
        if not balance["balanced"] and res.get("status") == "ok":
            res.setdefault("warnings", []).append(
                f"搬出总量 {balance['pickup_total']} 与投放总量 "
                f"{balance['delivery_total']} 不匹配，"
                "说明空缺区识别结果与堆积区不成对，调度计划可能搬运无处安放的单车。")

        with self._lock:
            self.last_dispatch = res
        return res

    def run_simulation(self, strategy=None, overrides=None, force=False):
        """
        运行 SimPy 仿真对比实验（可指定单策略，默认三类全跑）。

        force=False 时若已有缓存且参数一致则直接返回缓存，
        避免演示时每次打开页面都要等 30~60 秒重算。
        """
        if strategy is not None and strategy not in VALID_STRATEGIES:
            raise ValueError(
                f"非法策略 '{strategy}'，可选：{', '.join(VALID_STRATEGIES)}")
        ov = dict(overrides or {})
        ov.pop("force", None)
        sim_cfg = {**self.config["simulation"], **ov}
        params = {
            "duration_h": sim_cfg["duration_h"],
            "arrival_rate_per_h": sim_cfg["arrival_rate_per_h"],
            "seed": sim_cfg["seed"],
            "threshold_imbalance": sim_cfg["threshold_imbalance"],
            "predict_window_min": sim_cfg["predict_window_min"],
            "vehicle_cost_per_km": sim_cfg["vehicle_cost_per_km"],
            "fix_cost_per_task": sim_cfg["fix_cost_per_task"],
            "wait_penalty_per_min": sim_cfg["wait_penalty_per_min"],
            "check_interval_min": sim_cfg["check_interval_min"],
        }

        cached = self.last_simulation
        if (not force and cached is not None
                and cached.get("params") == params
                and self.config["bike"]["total"] == cached.get("total_bikes")):
            results = cached["results"]
        else:
            results = run_all_strategies(self.hotspots,
                                         total_bikes=self.config["bike"]["total"],
                                         **params)
            self.last_simulation = {
                "results": results,
                "params": params,
                "total_bikes": self.config["bike"]["total"],
                "cached": True,
            }
        if strategy:
            return {"results": [r for r in results if r["strategy"] == strategy],
                    "params": params, "total_bikes": self.config["bike"]["total"]}
        return self.last_simulation


service = BikeService()
