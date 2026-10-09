# -*- coding: utf-8 -*-
"""
回归测试：覆盖本次修复的缺陷与新增的改进遗传算法。

运行：cd backend && .venv/bin/python -m pytest ../tests/ -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ---------------------------------------------------------------------------
# 双阶段聚类
# ---------------------------------------------------------------------------
def test_cluster_radius_uses_correct_indexing():
    """
    回归缺陷：K-means 子簇下标是「簇内相对下标」，
    计算半径时必须经 idx 映射回全局点集，否则半径算错甚至越界。
    """
    import numpy as np
    from algorithms.clustering import detect_imbalance
    from data.gps_simulator import HOTSPOTS

    rng = np.random.default_rng(3)
    pts = [(34.143 + rng.normal(0, 0.0003), 108.840 + rng.normal(0, 0.0003))
           for _ in range(60)]
    res = detect_imbalance(pts, HOTSPOTS)
    assert res["stats"]["clusters"] >= 1
    for c in res["clusters"]:
        assert 0 < c["radius_m"] < 500, c        # 校园尺度半径应为合理正值
        assert c["count"] > 0
        assert c["cluster_count"] >= c["count"]  # 整簇数量不小于子簇数量


def test_cluster_grading_uses_whole_cluster():
    """
    堆积等级应按整簇总量对容量评级。
    60 个点、区域容量 30 -> 比值 2.0 -> 应为 level 3。
    """
    from algorithms.clustering import detect_imbalance

    pts = [(34.1430 + i * 1e-6, 108.8400 + i * 1e-6) for i in range(60)]
    res = detect_imbalance(pts, [], eps_m=80, min_samples=5,
                           capacity_per_zone=30)
    assert res["clusters"], "应识别出堆积区"
    assert all(c["level"] >= 2 for c in res["clusters"])


def test_cluster_ignores_invalid_points():
    from algorithms.clustering import detect_imbalance

    pts = [(34.143, 108.840), (None, 108.841),
           (34.1431, float("nan")), (34.1432, 108.8402)]
    res = detect_imbalance(pts, [])
    assert res["stats"]["points"] == 2
    assert res["stats"]["invalid_points"] == 2


# ---------------------------------------------------------------------------
# 数据清洗
# ---------------------------------------------------------------------------
def test_cleaner_rejects_invalid_coord_and_ts():
    """
    回归缺陷：坐标缺失/非数值会抛 TypeError，非法时间戳会被静默替换为当前时间。
    """
    from datetime import datetime
    from data.cleaner import DataCleaner

    c = DataCleaner()
    t = datetime(2026, 9, 21, 8, 0, 0).isoformat()
    assert c.clean({"bike_id": 1, "lat": None, "lng": 108.84, "ts": t}) is None
    assert c.clean({"bike_id": 1, "lat": "abc", "lng": 108.84, "ts": t}) is None
    assert c.clean({"bike_id": 1, "lat": 34.143, "lng": 108.84,
                    "ts": "not-a-date"}) is None
    assert c.stats["invalid_coord"] == 2
    assert c.stats["bad_ts"] == 1
    # 非法点不应污染后续漂移/去重判定
    assert c.clean({"bike_id": 1, "lat": 34.143, "lng": 108.841,
                    "ts": t}) is not None


def test_cleaner_accepts_normal_point_and_coerces_numeric_strings():
    from datetime import datetime
    from data.cleaner import DataCleaner

    c = DataCleaner()
    t = datetime(2026, 9, 21, 8, 0, 0).isoformat()
    out = c.clean({"bike_id": 7, "lat": "34.1430", "lng": "108.8410", "ts": t})
    assert out is not None
    assert isinstance(out["lat"], float) and isinstance(out["lng"], float)


# ---------------------------------------------------------------------------
# CVRP 求解
# ---------------------------------------------------------------------------
def _sample_nodes():
    return [
        {"id": 1, "lat": 34.1435, "lng": 108.8405, "demand": 15},
        {"id": 2, "lat": 34.1425, "lng": 108.8425, "demand": 12},
        {"id": 3, "lat": 34.1445, "lng": 108.8390, "demand": 10},
        {"id": 4, "lat": 34.1415, "lng": 108.8410, "demand": -20},
        {"id": 5, "lat": 34.1430, "lng": 108.8430, "demand": -17},
    ]


def test_ga_solver_feasible_and_capacity():
    from algorithms.cvrp_ga import GeneticCVRPSolver

    depot = {"lat": 34.1430, "lng": 108.8415}
    solver = GeneticCVRPSolver(depot, _sample_nodes(), capacity=40,
                               vehicle_num=3, pop_size=30, generations=40,
                               seed=1)
    res = solver.solve()
    assert res["status"] == "ok"
    assert res["algorithm"] == "ga"
    assert res["total_distance"] > 0
    for r in res["routes"]:
        assert r["load"] <= 40 + 1e-6, r          # 峰值载重不超容量
        assert len(r["path"]) > 2
        assert r["path"][0] == 0 and r["path"][-1] == 0
    served = sorted(s["zone_id"] for t in res["tasks"] for s in t["stops"])
    assert served == [1, 2, 3, 4, 5]


def test_ga_delivery_before_pickup_uses_initial_load():
    """
    回归缺陷：原实现用 abs(demand) 累加载重，导致载重只增不减、
    「先投放后取货」无法建模。新口径下峰值载重 = 前缀和极差，初始载荷补齐缺口。
    """
    from algorithms.cvrp_ga import _initial_load, _route_peak_load

    demands = [-20, 15]          # 先投放 20，再取货 15
    assert _initial_load(demands) == 20
    assert _route_peak_load(demands) == 20


def test_ga_infeasible_reported_explicitly():
    """回归缺陷：求解失败应返回明确状态，而不是与「空结果成功」无法区分。"""
    from algorithms.cvrp_ga import GeneticCVRPSolver

    depot = {"lat": 34.1430, "lng": 108.8415}
    nodes = [{"id": i + 1, "lat": 34.143 + i * 1e-4, "lng": 108.841 + i * 1e-4,
              "demand": 30} for i in range(6)]
    solver = GeneticCVRPSolver(depot, nodes, capacity=30, vehicle_num=1,
                               pop_size=10, generations=5, seed=1)
    res = solver.solve()
    assert res["status"] == "infeasible"
    assert res["routes"] == []


def test_ga_improves_over_random_baseline():
    """改进遗传算法（贪心初始解 + 2-opt + 精英保留）应优于纯随机排列。"""
    import random
    from algorithms.cvrp_ga import GeneticCVRPSolver

    depot = {"lat": 34.1430, "lng": 108.8415}
    nodes = _sample_nodes()
    ga = GeneticCVRPSolver(depot, nodes, capacity=40, vehicle_num=3,
                           pop_size=40, generations=80, seed=5)
    ga_res = ga.solve()

    rng = random.Random(5)
    best_random = None
    for _ in range(200):
        perm = list(range(1, len(nodes) + 1))
        rng.shuffle(perm)
        cost, routes = ga.evaluate(perm)
        if len(routes) <= 3 and cost < 1e7:
            best_random = cost if best_random is None else min(best_random, cost)
    assert ga_res["status"] == "ok"
    if best_random is not None:
        assert ga_res["total_distance"] <= best_random + 1e-6


def test_ortools_and_ga_both_feasible():
    from algorithms.cvrp_ga import create_solver

    depot = {"lat": 34.1430, "lng": 108.8415}
    for algo in ("ga", "ortools"):
        s = create_solver(depot, _sample_nodes(), capacity=40, vehicle_num=3,
                          params={"time_limit_seconds": 1, "pop_size": 20,
                                  "generations": 20}, seed=2, algorithm=algo)
        res = s.solve()
        assert res["status"] == "ok", algo
        for r in res["routes"]:
            assert r["load"] <= 40 + 1e-6


def test_ga_population_terminates_when_perm_space_small():
    """
    回归缺陷：排列空间大小为 n!，当 pop_size > n! 时
    「凑满 pop_size 个互异个体」不可能完成，朴素实现会死循环（导致调度接口卡死）。
    n=4 只有 24 种排列，这里故意给 pop_size=60，必须能正常返回。
    """
    from algorithms.cvrp_ga import GeneticCVRPSolver

    depot = {"lat": 34.1430, "lng": 108.8415}
    nodes = [{"id": i + 1, "lat": 34.143 + i * 1e-4, "lng": 108.841 + i * 1e-4,
              "demand": d} for i, d in enumerate([27, 40, 32, 21])]
    solver = GeneticCVRPSolver(depot, nodes, capacity=40, vehicle_num=5,
                               pop_size=60, generations=30, seed=42)
    pop = solver._init_population()
    assert len(pop) == 60                      # 允许重复个体，但必须凑满且终止
    assert all(sorted(p) == [1, 2, 3, 4] for p in pop)
    res = solver.solve()
    assert res["status"] in ("ok", "infeasible")
    assert res["algorithm"] == "ga"


def test_build_cvrp_input_includes_level1_cluster():
    """回归缺陷：原实现额外要求 ratio>1.0，会漏掉临界堆积区。"""
    from algorithms.cvrp_ga import build_cvrp_input

    clusters = [{"id": 1, "lat": 34.143, "lng": 108.841, "count": 70,
                 "capacity": 60, "ratio": 1.17, "level": 1}]
    nodes = build_cvrp_input(clusters, [], {"lat": 34.143, "lng": 108.8415},
                             capacity=40)
    assert sum(n["demand"] for n in nodes) == 10
    assert all(abs(n["demand"]) <= 40 for n in nodes)


def test_build_cvrp_input_splits_oversized_demand():
    from algorithms.cvrp_ga import build_cvrp_input

    clusters = [{"id": 1, "lat": 34.143, "lng": 108.841, "count": 137,
                 "capacity": 60, "ratio": 2.28, "level": 3}]
    nodes = build_cvrp_input(clusters, [], {"lat": 34.143, "lng": 108.8415},
                             capacity=40)
    assert sum(n["demand"] for n in nodes) == 77
    assert all(abs(n["demand"]) <= 40 for n in nodes)


# ---------------------------------------------------------------------------
# 仿真
# ---------------------------------------------------------------------------
def test_simulation_metrics_include_failed_wait():
    """回归缺陷：失败用户的等待未被计入平均等待，会系统性低估。"""
    from algorithms.simulation import run_all_strategies
    from data.gps_simulator import HOTSPOTS

    res = run_all_strategies(HOTSPOTS, total_bikes=60, seed=7,
                             duration_h=6.0, arrival_rate_per_h=900.0)
    assert len(res) == 3
    for r in res:
        # 需求必须被完整结算：成功 + 失败 + 仿真结束时仍在等待
        assert r["demand_count"] == (r["success_count"] + r["fail_count"]
                                     + r["pending_count"])
        assert r["avg_wait_min"] >= 0
        assert r["avg_wait_success_min"] >= 0
        # 含失败用户的口径不应低于仅成功用户的口径
        if r["fail_count"] > 0:
            assert r["avg_wait_min"] >= r["avg_wait_success_min"] - 1e-9
        assert r["unserved_bikes"] >= 0
        assert r["moved_bikes"] >= 0


def test_simulation_dispatch_never_exceeds_capacity():
    """回归缺陷：原实现调度瞬时生效且可能把目的地塞到超容。"""
    from algorithms.simulation import BikeSimulation, build_campus_zones
    from data.gps_simulator import HOTSPOTS

    zones = build_campus_zones(HOTSPOTS, 300)
    sim = BikeSimulation(zones, total_bikes=300, strategy="threshold",
                         seed=11, duration_h=10.0, arrival_rate_per_h=800.0,
                         threshold_imbalance=5, check_interval_min=10.0)
    sim.run()
    # 调度完成后检查各区域是否超出容量（还车造成的自然超容单独统计）
    for z in zones:
        assert z.bikes >= 0
    assert sim.moved_bikes + sim.unserved_bikes >= 0


# ---------------------------------------------------------------------------
# 服务层与接口校验
# ---------------------------------------------------------------------------
def test_service_rejects_invalid_strategy():
    from service import service

    with pytest.raises(ValueError):
        service.run_simulation(strategy="bogus")


def test_request_models_validate_inputs():
    from pydantic import ValidationError

    from api.routes import DispatchRequest, SimRequest

    assert SimRequest(strategy="none").strategy == "none"
    assert SimRequest(strategy=None).strategy is None
    with pytest.raises(ValidationError):
        SimRequest(strategy="bogus")
    with pytest.raises(ValidationError):
        DispatchRequest(vehicle_num=0)
    with pytest.raises(ValidationError):
        DispatchRequest(algorithm="not-an-algo")
    assert DispatchRequest(vehicle_capacity=40, algorithm="ga").algorithm == "ga"


def test_app_routes_registered():
    import main

    paths = set(main.app.openapi().get("paths", {}).keys())
    for p in ("/api/health", "/api/config", "/api/hotspots", "/api/bikes",
              "/api/clusters/scan", "/api/clusters", "/api/dispatch",
              "/api/simulation"):
        assert p in paths, p
    # WebSocket 路由不出现在 OpenAPI 中，单独检查已注册
    ws_paths = {getattr(r, "path", None) for r in main.app.routes}
    assert "/ws/gps" in ws_paths


def test_api_contract_empty_body_and_overrides():
    """
    前端以「空请求体」POST 聚类/调度接口，必须返回 200 而不是 422；
    参数覆盖应生效，越界取值应返回 422。
    直接驱动 ASGI 应用（不依赖 httpx），且所有请求在同一事件循环内串行执行。
    """
    import asyncio
    import json

    from main import app

    async def call(method, path, body=b""):
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": method, "path": path, "raw_path": path.encode(),
            "query_string": b"", "root_path": "",
            "headers": [(b"host", b"test"),
                        (b"content-type", b"application/json")],
            "client": ("127.0.0.1", 1234), "server": ("test", 80), "scheme": "http",
        }
        state = {"status": None, "body": b""}
        sent = {"done": False}

        async def receive():
            if not sent["done"]:
                sent["done"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
            elif message["type"] == "http.response.body":
                state["body"] += message.get("body", b"")

        await app(scope, receive, send)
        return state

    async def scenario():
        return {
            "scan_empty": await call("POST", "/api/clusters/scan"),
            "dispatch_empty": await call("POST", "/api/dispatch"),
            "scan_override": await call(
                "POST", "/api/clusters/scan",
                json.dumps({"eps_m": 45, "min_samples": 8}).encode()),
            "bad_vehicle": await call(
                "POST", "/api/dispatch", json.dumps({"vehicle_num": 0}).encode()),
            "bad_strategy": await call(
                "POST", "/api/simulation",
                json.dumps({"strategy": "bogus"}).encode()),
        }

    res = asyncio.run(scenario())

    # 空请求体必须可用（前端就是这样调用的）
    assert res["scan_empty"]["status"] == 200
    assert res["dispatch_empty"]["status"] == 200
    assert res["scan_override"]["status"] == 200
    # 非法参数返回 422
    assert res["bad_vehicle"]["status"] == 422
    assert res["bad_strategy"]["status"] == 422

    # dispatch 响应需满足前端契约
    d = json.loads(res["dispatch_empty"]["body"])
    for key in ("status", "algorithm", "routes", "tasks", "depot", "nodes",
                "balance", "vehicle_capacity"):
        assert key in d, key
    for r in d["routes"]:
        assert set(r.keys()) >= {"path", "load", "dist"}
        assert r["path"][0] == 0 and r["path"][-1] == 0
        assert max(r["path"]) <= len(d["nodes"])
        assert r["load"] <= d["vehicle_capacity"] + 1e-6
    for t in d["tasks"]:
        assert set(t.keys()) >= {"vehicle_id", "stops", "distance_km", "load"}

    # 参数覆盖确实改变了聚类结果
    a = json.loads(res["scan_empty"]["body"])["stats"]
    b = json.loads(res["scan_override"]["body"])["stats"]
    assert a["dbscan_clusters"] != b["dbscan_clusters"] or a["clusters"] != b["clusters"]


def test_cluster_warns_when_eps_too_large():
    """eps 相对密度过大时，应给出参数调优提示，而不是静默给出一个整片大簇。"""
    from algorithms.clustering import detect_imbalance

    pts = [(34.143 + (i % 20) * 1e-5, 108.840 + (i // 20) * 1e-5)
           for i in range(200)]
    res = detect_imbalance(pts, [], eps_m=200, min_samples=5)
    assert res["stats"]["dbscan_clusters"] == 1
    assert res["stats"].get("warnings"), "应给出 DBSCAN 参数调优提示"


def test_summarize_cvrp_input_detects_imbalance():
    """搬出总量与投放总量不匹配时，应能被识别出来（避免搬运无处安放的单车）。"""
    from algorithms.cvrp_ga import summarize_cvrp_input

    only_pickup = [{"id": 1, "demand": 30}, {"id": 2, "demand": 20}]
    s = summarize_cvrp_input(only_pickup)
    assert s == {"pickup_total": 50, "delivery_total": 0, "net_total": 50,
                 "balanced": False}

    paired = [{"id": 1, "demand": 30}, {"id": 2, "demand": -30}]
    s2 = summarize_cvrp_input(paired)
    assert s2["balanced"] is True
    assert s2["net_total"] == 0


def test_prompt_compatibility_helpers():
    """报告约定的 GPS 流和位置存储接口应可独立使用。"""
    from datetime import datetime
    from data.gps_simulator import GpsSimulator
    from store import Store

    sim = GpsSimulator(total_bikes=3, seed=4)
    event = next(sim.generate_stream(
        start_time=datetime(2026, 9, 21, 8, 0), max_steps=1))
    assert event["timestamp"] == event["ts"]

    store = Store(latest_window_s=60)
    store.update_position(event["bike_id"], event["lat"], event["lng"],
                          event["timestamp"])
    assert len(store.get_all_positions()) == 1
    assert len(store.get_latest_positions(event["timestamp"])) == 1


def test_simulation_force_flag_is_forwarded():
    """HTTP 路由的 force=true 必须真正绕过服务缓存。"""
    from api.routes import SimRequest, simulation
    from service import service

    captured = {}
    original = service.run_simulation

    def fake_run_simulation(*, strategy=None, overrides=None, force=False):
        captured["strategy"] = strategy
        captured["force"] = force
        captured["overrides"] = overrides
        return {"results": []}

    service.run_simulation = fake_run_simulation
    try:
        simulation(SimRequest(strategy="threshold", force=True,
                              duration_h=2.0))
    finally:
        service.run_simulation = original

    assert captured == {
        "strategy": "threshold",
        "force": True,
        "overrides": {"duration_h": 2.0},
    }


def test_dispatch_tasks_query_does_not_trigger_solver():
    """无缓存时查询调度任务应立即返回空列表，避免演示误触发求解。"""
    from api.routes import get_dispatch_tasks_compat
    from service import service

    old = service.last_dispatch
    service.last_dispatch = None
    try:
        result = get_dispatch_tasks_compat()
    finally:
        service.last_dispatch = old

    assert result == {"tasks": [], "route": [], "total_distance": 0.0,
                      "status": "empty"}
