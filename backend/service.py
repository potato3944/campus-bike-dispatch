# -*- coding: utf-8 -*-
"""
运行时服务层
管理 GPS 模拟线程、数据清洗、缓存、聚类与调度结果的实时状态，
供 REST 接口与 WebSocket 消费。
"""

import threading
import time
from datetime import datetime, timedelta

import config
from data.gps_simulator import GpsSimulator, HOTSPOTS
from data.cleaner import DataCleaner
from algorithms.clustering import detect_imbalance
from algorithms.cvrp_ga import CVRPSolver, build_cvrp_input
from algorithms.simulation import run_all_strategies


class BikeService:
    """校园单车系统运行时状态（单例）"""

    def __init__(self):
        self.config = {
            "map": config.MAP,
            "bike": config.BIKE,
            "cluster": config.CLUSTER,
            "cvrp": config.CVRP,
            "simulation": config.SIMULATION,
        }
        self.hotspots = HOTSPOTS
        self.simulator = GpsSimulator(total_bikes=config.BIKE["total"], seed=7)
        self.cleaner = DataCleaner(max_speed_kmh=config.BIKE["max_speed_kmh"])
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
        self._running = False
        self._thread = None

    # ------------------------------------------------------------------ 线程
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        """模拟推进循环：每 1 秒推进 10 秒模拟时间"""
        while self._running:
            t0 = time.time()
            with self._lock:
                self.sim_time += timedelta(seconds=10)
                events = self.simulator.step(self.sim_time, dt_s=10.0)
                cleaned = []
                for ev in events:
                    pt = self.cleaner.clean(ev)
                    if pt is not None:
                        cleaned.append(pt)
                        self.all_bikes[pt["bike_id"]] = pt
                    else:
                        bid = ev.get("bike_id")
                        if bid in self.all_bikes:
                            self.all_bikes[bid]["ts"] = self.sim_time.isoformat()
                            self.all_bikes[bid]["status"] = ev.get("status", "idle")
                self.recent_points = list(self.all_bikes.values())
                self.bike_points = list(self.all_bikes.values())
            # 周期聚类扫描
            scan_interval_min = max(1, config.CLUSTER["scan_interval_s"] // 60)
            if int(self.sim_time.minute) % scan_interval_min == 0 and self.sim_time.second == 0:
                self.scan_clusters()
            # 控制节奏：1 秒墙钟 = 10 秒模拟时间
            time.sleep(max(0.1, 1.0 - (time.time() - t0)))

    # ------------------------------------------------------------------ 计算
    def _scan_locked(self):
        """执行双阶段聚类扫描（调用方需已持有锁）"""
        pts = [(p["lat"], p["lng"]) for p in self.bike_points]
        res = detect_imbalance(
            pts, self.hotspots,
            eps_m=config.CLUSTER["eps_m"],
            min_samples=config.CLUSTER["min_samples"],
            k_levels=config.CLUSTER["k_levels"],
            capacity_per_zone=config.BIKE["capacity_per_zone"],
        )
        res["sim_time"] = self.sim_time.isoformat()
        self.last_cluster = res
        return res

    def scan_clusters(self):
        """执行双阶段聚类扫描（对外接口，自行加锁）"""
        with self._lock:
            return self._scan_locked()

    def run_dispatch(self):
        """运行 CVRP 调度求解"""
        with self._lock:
            if self.last_cluster is None:
                self._scan_locked()
            nodes = build_cvrp_input(
                self.last_cluster["clusters"],
                self.last_cluster["shortage"],
                config.CVRP["depot"],
                capacity=config.CVRP["vehicle_capacity"],
            )
            solver = CVRPSolver(
                config.CVRP["depot"], nodes,
                capacity=config.CVRP["vehicle_capacity"],
                vehicle_num=config.CVRP["vehicle_num"],
                ortools_params=config.CVRP["solver"],
                seed=config.SIMULATION["seed"],
            )
            res = solver.solve()
            res["sim_time"] = self.sim_time.isoformat()
            # 附加绘图所需信息
            res["depot"] = config.CVRP["depot"]
            res["nodes"] = nodes
            res["vehicle_capacity"] = config.CVRP["vehicle_capacity"]
            self.last_dispatch = res
        return res

    def run_simulation(self, strategy=None):
        """运行 SimPy 仿真对比实验（可指定单策略，默认三类全跑）"""
        params = {
            "duration_h": config.SIMULATION["duration_h"],
            "arrival_rate_per_h": config.SIMULATION["arrival_rate_per_h"],
            "seed": config.SIMULATION["seed"],
            "threshold_imbalance": config.SIMULATION["threshold_imbalance"],
            "predict_window_min": config.SIMULATION["predict_window_min"],
            "vehicle_cost_per_km": config.SIMULATION["vehicle_cost_per_km"],
            "fix_cost_per_task": config.SIMULATION["fix_cost_per_task"],
            "wait_penalty_per_min": config.SIMULATION["wait_penalty_per_min"],
            "check_interval_min": config.SIMULATION["check_interval_min"],
        }
        results = run_all_strategies(self.hotspots,
                                     total_bikes=config.BIKE["total"], **params)
        self.last_simulation = {"results": results, "params": params}
        if strategy:
            return {"results": [r for r in results if r["strategy"] == strategy],
                    "params": params}
        return self.last_simulation


service = BikeService()
