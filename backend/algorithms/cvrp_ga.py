# -*- coding: utf-8 -*-
"""
CVRP 调度模型求解模块（基于 Google OR-Tools）

模型：带载重约束的车辆路径问题（Capacitated Vehicle Routing Problem）
  - 调度车辆从调度中心(depot)出发，依次访问各失衡区域，最后返回调度中心；
  - 每个区域有净需求量 demand：正数=需运走(堆积区, pickup)，负数=需投放(空缺区, delivery)；
  - 每辆车累计搬运量不得超过 capacity（载重约束）；
  - 目标：最小化车队总行驶距离。

求解器：OR-Tools RoutingModel
  - 距离矩阵（米，整数化）+ 容量维度（AddDimensionWithVehicleCapacity）
  - 初始解策略 PATH_CHEAPEST_ARC + 引导式局部搜索 GUIDED_LOCAL_SEARCH
"""

import numpy as np
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geo import haversine_m


class CVRPSolver:
    def __init__(self, depot, nodes, capacity=40, vehicle_num=5,
                 ortools_params=None, seed=0):
        """
        depot: {"lat": .., "lng": ..} 调度中心
        nodes: [{"id":.., "lat":.., "lng":.., "demand":..}] demand>0 需运走, <0 需投放
        capacity: 车辆载重上限
        vehicle_num: 可用车辆数上限
        ortools_params: {"time_limit_seconds": 2,
                         "first_solution_strategy": "PATH_CHEAPEST_ARC",
                         "local_search": "GUIDED_LOCAL_SEARCH"}
        """
        self.depot = depot
        self.nodes = nodes
        self.n = len(nodes)
        self.capacity = capacity
        self.vehicle_num = vehicle_num
        params = ortools_params or {}
        self.time_limit = params.get("time_limit_seconds", 2)
        self.first_solution = params.get("first_solution_strategy",
                                         "PATH_CHEAPEST_ARC")
        self.local_search = params.get("local_search", "GUIDED_LOCAL_SEARCH")
        self.dist = self._build_dist_matrix()

    # ------------------------------------------------------------------ 距离
    def _build_dist_matrix(self):
        """距离矩阵（米，整数）：0 = depot, 1..n = nodes"""
        pts = [(self.depot["lat"], self.depot["lng"])] + \
              [(nd["lat"], nd["lng"]) for nd in self.nodes]
        m = len(pts)
        D = np.zeros((m, m), dtype=int)
        for i in range(m):
            for j in range(i + 1, m):
                d = int(round(haversine_m(pts[i][0], pts[i][1],
                                          pts[j][0], pts[j][1])))
                D[i, j] = D[j, i] = d
        return D

    # ------------------------------------------------------------------ 求解
    def solve(self, verbose=False):
        """使用 OR-Tools 求解 CVRP，返回最优路径方案"""
        if self.n == 0:
            return {"routes": [], "total_distance": 0.0, "tasks": []}
        if self.n == 1:
            # 单节点：直接构造往返路径
            d = float(2 * self.dist[0, 1])
            route = {"path": [0, 1, 0], "load": float(abs(self.nodes[0]["demand"])),
                     "dist": d}
            tasks = self._build_tasks([route])
            return {"routes": [route], "total_distance": d, "tasks": tasks}

        manager = pywrapcp.RoutingIndexManager(self.n + 1, self.vehicle_num, 0)
        routing = pywrapcp.RoutingModel(manager)

        # 距离回调（米）
        def distance_callback(from_index, to_index):
            f = manager.IndexToNode(from_index)
            t = manager.IndexToNode(to_index)
            return int(self.dist[f][t])

        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        # 载重回调：节点需求绝对值（容量占用）
        def demand_callback(from_index):
            node = manager.IndexToNode(from_index)
            if node == 0:
                return 0
            return int(abs(self.nodes[node - 1]["demand"]))

        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index,
            0,                                     # slack 上限
            [self.capacity] * self.vehicle_num,    # 各车容量
            True,                                  # 从起点开始累计
            "Capacity",
        )

        # 搜索策略
        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = getattr(
            routing_enums_pb2.FirstSolutionStrategy, self.first_solution,
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
        search_params.local_search_metaheuristic = getattr(
            routing_enums_pb2.LocalSearchMetaheuristic, self.local_search,
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
        search_params.time_limit.seconds = self.time_limit

        solution = routing.SolveWithParameters(search_params)
        if solution is None:
            return {"routes": [], "total_distance": 0.0, "tasks": []}

        routes = []
        for v in range(self.vehicle_num):
            path = [0]
            idx = routing.Start(v)
            while not routing.IsEnd(idx):
                node = manager.IndexToNode(idx)
                if node != 0:
                    path.append(node)
                idx = solution.Value(routing.NextVar(idx))
            if len(path) == 1:
                continue
            path.append(0)
            d = sum(self.dist[path[i], path[i + 1]] for i in range(len(path) - 1))
            load = sum(abs(self.nodes[p - 1]["demand"]) for p in path if p != 0)
            routes.append({"path": path, "load": float(load),
                           "dist": float(d)})

        routes = [r for r in routes if len(r["path"]) > 2]
        total = sum(r["dist"] for r in routes)
        tasks = self._build_tasks(routes)
        return {"routes": routes, "total_distance": round(total, 1), "tasks": tasks}

    def _build_tasks(self, routes):
        """将路径方案转换为可执行的调度任务列表"""
        tasks = []
        for vi, r in enumerate(routes):
            path = r["path"]
            stops = []
            for idx in path:
                if idx == 0:
                    continue
                nd = self.nodes[idx - 1]
                stops.append({
                    "zone_id": nd["id"],
                    "lat": nd["lat"],
                    "lng": nd["lng"],
                    "op": "pickup" if nd["demand"] > 0 else "delivery",
                    "qty": int(abs(nd["demand"])),
                })
            if stops:
                tasks.append({"vehicle_id": vi + 1, "stops": stops,
                              "distance_km": round(r["dist"] / 1000.0, 3),
                              "load": r["load"]})
        return tasks


# ---------------------------------------------------------------------------
# 聚类结果 -> CVRP 输入构建
# ---------------------------------------------------------------------------
def _split_demand(node, capacity):
    """
    将需求拆分为多个不超过车辆容量的虚拟节点。
    例如 demand=77, capacity=40 -> 拆为 40 + 37 两个同位置节点。
    """
    sign = 1 if node["demand"] > 0 else -1
    remaining = abs(node["demand"])
    pieces = []
    while remaining > 0:
        q = min(remaining, capacity)
        pieces.append({**node, "demand": sign * q})
        remaining -= q
    return pieces


def build_cvrp_input(clusters, shortage, depot, capacity=40):
    """
    由双阶段聚类结果构建 CVRP 输入：
      - 堆积区（level>=1）-> pickup 节点（demand = 超额车辆数）
      - 空缺区 -> delivery 节点（demand = 需投放车辆数，取负）
    超额量超过车辆容量的节点自动拆分，保证单节点需求 <= 容量。
    """
    nodes = []
    for c in clusters:
        if c["level"] >= 1 and c["ratio"] > 1.0:
            surplus = int(c["count"] - c["capacity"])
            if surplus > 0:
                nodes.extend(_split_demand(
                    {"id": c["id"], "lat": c["lat"], "lng": c["lng"],
                     "demand": surplus}, capacity))
    for s in shortage:
        need = s["expected"] - s["actual"]
        if need > 0:
            nodes.extend(_split_demand(
                {"id": s["id"], "lat": s["lat"], "lng": s["lng"],
                 "demand": -need}, capacity))
    return nodes


if __name__ == "__main__":
    # 自测：构造 3 个堆积区 + 2 个空缺区
    nodes = [
        {"id": 1, "lat": 34.1435, "lng": 108.8405, "demand": 15},
        {"id": 2, "lat": 34.1425, "lng": 108.8425, "demand": 12},
        {"id": 3, "lat": 34.1445, "lng": 108.8390, "demand": 10},
        {"id": 4, "lat": 34.1415, "lng": 108.8410, "demand": -20},
        {"id": 5, "lat": 34.1430, "lng": 108.8430, "demand": -17},
    ]
    depot = {"lat": 34.1430, "lng": 108.8415}
    solver = CVRPSolver(depot, nodes, capacity=40, vehicle_num=3,
                        ortools_params={"time_limit_seconds": 2})
    res = solver.solve()
    print("total_distance:", res["total_distance"], "m")
    for t in res["tasks"]:
        print("vehicle", t["vehicle_id"], "stops:", t["stops"], "dist:", t["distance_km"])
