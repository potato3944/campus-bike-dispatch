# -*- coding: utf-8 -*-
"""
自动化测试：数据生成、清洗、聚类、CVRP、仿真
运行：cd backend && .venv/bin/python -m pytest ../tests/ -v
"""

import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ---------------------------------------------------------------------------
def test_gps_simulator():
    from data.gps_simulator import GpsSimulator, HOTSPOTS
    from datetime import datetime, timedelta
    sim = GpsSimulator(total_bikes=50, seed=1)
    assert len(sim.bikes) == 50
    t = datetime(2026, 9, 21, 7, 30, 0)
    events = []
    for i in range(10):
        events += sim.step(t + timedelta(seconds=10 * i), 10.0)
    assert len(events) > 0
    # 所有事件都在校园经纬度范围内
    for e in events:
        assert 34.13 < e["lat"] < 34.15
        assert 108.83 < e["lng"] < 108.85
    assert len(HOTSPOTS) >= 5


def test_cleaner():
    from data.cleaner import DataCleaner
    from datetime import datetime, timedelta
    c = DataCleaner()
    t0 = datetime(2026, 9, 21, 8, 0, 0)
    base = {"bike_id": 1, "lat": 34.143, "lng": 108.841, "event": "idle"}
    assert c.clean({**base, "ts": t0.isoformat()}) is not None
    # 重复点被过滤
    assert c.clean({**base, "ts": (t0 + timedelta(seconds=5)).isoformat()}) is None
    # 漂移点被过滤
    assert c.clean({"bike_id": 1, "lat": 34.145, "lng": 108.843,
                    "ts": (t0 + timedelta(seconds=10)).isoformat()}) is None
    assert c.stats["drift_removed"] >= 1
    assert c.stats["dup_removed"] >= 1


def test_clustering():
    from algorithms.clustering import detect_imbalance
    import numpy as np
    rng = np.random.default_rng(1)
    pts = []
    for (la, ln, num) in [(34.143, 108.840, 40), (34.142, 108.842, 30)]:
        pts += [(la + rng.normal(0, 0.0003), ln + rng.normal(0, 0.0003))
                for _ in range(num)]
    from data.gps_simulator import HOTSPOTS
    res = detect_imbalance(pts, HOTSPOTS)
    assert res["stats"]["clusters"] >= 1
    for c in res["clusters"]:
        assert 0 <= c["level"] <= 3
        assert c["count"] > 0


def test_cvrp():
    from algorithms.cvrp_ga import CVRPSolver, build_cvrp_input
    clusters = [
        {"id": 1, "lat": 34.143, "lng": 108.841, "count": 137,
         "capacity": 60, "ratio": 2.28, "level": 3},
    ]
    shortage = [
        {"id": 1, "name": "宿舍", "lat": 34.145, "lng": 108.839,
         "expected": 60, "actual": 10, "shortage_ratio": 0.83, "level": 2},
    ]
    depot = {"lat": 34.143, "lng": 108.8415}
    nodes = build_cvrp_input(clusters, shortage, depot, capacity=40)
    solver = CVRPSolver(depot, nodes, capacity=40, vehicle_num=5)
    res = solver.solve()
    for r in res["routes"]:
        assert r["load"] <= 40 + 1e-6, f"容量超限: {r}"
        assert len(r["path"]) > 2
    assert res["total_distance"] > 0


def test_simulation_metrics():
    from algorithms.simulation import run_all_strategies
    from data.gps_simulator import HOTSPOTS
    res = run_all_strategies(HOTSPOTS, total_bikes=300, seed=42,
                             duration_h=4.0, arrival_rate_per_h=400.0)
    assert len(res) == 3
    strategies = [r["strategy"] for r in res]
    assert strategies == ["none", "threshold", "predictive"]
    for r in res:
        assert 0 <= r["turnover_rate"]
        assert 0 <= r["match_rate"] <= 1
        assert r["total_cost"] >= 0
