# -*- coding: utf-8 -*-
"""
CVRP 调度模型求解模块

模型：带载重约束的车辆路径问题（Capacitated Vehicle Routing Problem），
针对校园单车「搬出堆积区 -> 投放空缺区」的调度场景：
  - 调度车辆从调度中心(depot)出发，依次访问各失衡区域，最后返回调度中心；
  - 每个区域有净需求量 demand：正数=需运走(堆积区, pickup)，负数=需投放(空缺区, delivery)；
  - 车辆从调度中心出发时可携带初始载荷（调度中心是车辆/单车的集散地），
    因此「先送货后取货」也可能是可行的；
  - 载重约束：任一时刻车上单车数必须落在 [0, capacity] 内；
  - 目标：在满足载重约束与车辆数上限的前提下最小化车队总行驶距离。

载重可行性判定（本模块的统一口径）
-----------------------------------
对一条路径的净需求序列 d1..dk，记前缀和 S0=0, Sj=Σ(i<=j) di，
则车上载重 = L0 + Sj，其中 L0 是出发点初始载荷。
存在合法 L0 使 0 <= L0 + Sj <= capacity 的充要条件是：

    max(Sj) - min(Sj) <= capacity

且最优初始载荷 L0 = max(0, -min(Sj))，该趟任务峰值载重 = max(Sj) - min(Sj)。
本模块的遗传算法与 OR-Tools 求解器都采用这一口径，
避免了「取货/送货都按需求绝对值累加」导致载重只增不减的错误建模。

求解器
------
1. GeneticCVRPSolver（默认，对应选题报告）：改进遗传算法
   - 贪心最近邻构造初始种群
   - 顺序交叉（OX, Order Crossover）
   - 2-opt 局部搜索
   - 精英保留策略
2. CVRPSolver：OR-Tools RoutingModel（对照实现）
   - 距离矩阵（米，整数）+ 载重维度（有符号需求 + 自由初始载荷）
"""

import math
import random

import numpy as np

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geo import haversine_m

# 不可行解的惩罚权重（米），远大于任何真实路径长度
_BIG = 1e7


def _prefix_range(route_demands):
    """返回净需求序列前缀和的 (min, max)；空序列返回 (0, 0)。"""
    s = 0
    lo = hi = 0
    for d in route_demands:
        s += d
        if s < lo:
            lo = s
        if s > hi:
            hi = s
    return lo, hi


def _route_peak_load(route_demands):
    """一条路径的峰值载重（= 前缀和极差）。"""
    lo, hi = _prefix_range(route_demands)
    return hi - lo


def _initial_load(route_demands):
    """满足载重下限所需的最小初始载荷 L0 = max(0, -min(Sj))。"""
    lo, _ = _prefix_range(route_demands)
    return max(0, -lo)


class _BaseCVRP:
    """CVRP 公共部分：距离矩阵、可行性判定、任务构造。"""

    def __init__(self, depot, nodes, capacity=40, vehicle_num=5):
        self.depot = depot
        self.nodes = list(nodes)
        self.n = len(self.nodes)
        self.capacity = capacity
        self.vehicle_num = vehicle_num
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

    def _demand(self, node_idx):
        """node_idx 为 1..n 的节点编号，返回有符号净需求。"""
        return float(self.nodes[node_idx - 1]["demand"])

    def _route_feasible(self, route):
        """route: 节点编号列表（不含 depot）。载重极差不超过容量即可行。"""
        demands = [self._demand(x) for x in route]
        return _route_peak_load(demands) <= self.capacity + 1e-9

    def _route_distance(self, route):
        """route: 节点编号列表（不含 depot），返回含往返 depot 的距离（米）。"""
        if not route:
            return 0.0
        seq = [0] + list(route) + [0]
        return float(sum(self.dist[seq[i], seq[i + 1]]
                         for i in range(len(seq) - 1)))

    # ------------------------------------------------------------------ 输出
    def _route_record(self, route):
        """把一条路径整理为对外输出结构。"""
        demands = [self._demand(x) for x in route]
        seq = [0] + list(route) + [0]
        return {
            "path": seq,
            "load": float(_route_peak_load(demands)),
            "initial_load": float(_initial_load(demands)),
            "dist": self._route_distance(route),
        }

    def _build_tasks(self, routes):
        """将路径方案转换为可执行的调度任务列表"""
        tasks = []
        for vi, r in enumerate(routes):
            stops = []
            for idx in r["path"]:
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


# ===========================================================================
# 求解器一：改进遗传算法（默认）
# ===========================================================================
class GeneticCVRPSolver(_BaseCVRP):
    """
    改进遗传算法 CVRP 求解器。

    染色体编码：客户节点的一个排列（permutation），
    解码时按载重可行性贪心切分为若干条车辆路径。
    这样任何排列都能解码出可行路径，交叉/变异只需保持排列合法性。
    """

    def __init__(self, depot, nodes, capacity=40, vehicle_num=5,
                 pop_size=60, generations=120, crossover_rate=0.85,
                 mutation_rate=0.2, elite_ratio=0.15, tournament_k=3,
                 two_opt_passes=1, seed=0, time_limit_seconds=None,
                 **_ignored):
        super().__init__(depot, nodes, capacity, vehicle_num)
        self.pop_size = max(4, int(pop_size))
        self.generations = max(1, int(generations))
        self.crossover_rate = float(crossover_rate)
        self.mutation_rate = float(mutation_rate)
        self.elite_num = max(1, int(self.pop_size * float(elite_ratio)))
        self.tournament_k = max(2, int(tournament_k))
        self.two_opt_passes = max(0, int(two_opt_passes))
        self.time_limit_seconds = time_limit_seconds
        self.rng = random.Random(seed)

    # -------------------------------------------------------------- 解码/评估
    def decode(self, perm):
        """排列 -> 路径列表（每条为节点编号列表）。超出载重即换车。"""
        routes = []
        cur = []
        for node in perm:
            trial = cur + [node]
            if cur and not self._route_feasible(trial):
                routes.append(cur)
                cur = [node]
            else:
                cur = trial
        if cur:
            routes.append(cur)
        return routes

    def evaluate(self, perm):
        """返回 (代价, 路径列表)；不可行部分以惩罚计入代价。"""
        routes = self.decode(perm)
        total = sum(self._route_distance(r) for r in routes)
        penalty = 0.0
        if len(routes) > self.vehicle_num:
            penalty += _BIG * (len(routes) - self.vehicle_num)
        for r in routes:
            if not self._route_feasible(r):
                penalty += _BIG
        return total + penalty, routes

    # -------------------------------------------------------------- 初始种群
    def _greedy_perm(self, start=None):
        """贪心最近邻构造：每次挑最近且不违反载重约束的未访问节点。"""
        remaining = list(range(1, self.n + 1))
        self.rng.shuffle(remaining)
        perm = []
        cur_route = []
        last = 0
        while remaining:
            feasible = [x for x in remaining
                        if self._route_feasible(cur_route + [x])]
            if not feasible:
                # 当前车装不下任何剩余节点 -> 换车
                cur_route = []
                last = 0
                feasible = [x for x in remaining
                            if self._route_feasible([x])] or remaining
            nxt = min(feasible, key=lambda x: self.dist[last, x])
            perm.append(nxt)
            cur_route.append(nxt)
            last = nxt
            remaining.remove(nxt)
        return perm

    def _init_population(self):
        """
        构造初始种群：约一半贪心个体 + 一半随机排列。

        注意：节点排列空间大小为 n!，当 pop_size 大于 n! 时，
        「凑满 pop_size 个互异个体」是不可能完成的（例如 n=4 只有 24 种排列，
        却要求 60 个互异个体），朴素写法会陷入死循环。
        这里先按 min(pop_size, n!) 定目标，并对长期凑不出新个体的情形兜底退出，
        最后允许用已有个体补齐，保证一定终止。
        """
        pop = []
        greedy = self._greedy_perm()
        pop.append(greedy)
        seen = {tuple(greedy)}

        max_distinct = math.factorial(self.n)
        target = min(self.pop_size, max_distinct)
        stall = 0
        while len(pop) < target:
            if self.rng.random() < 0.5:
                cand = self._greedy_perm()
            else:
                cand = list(range(1, self.n + 1))
                self.rng.shuffle(cand)
            key = tuple(cand)
            if key in seen:
                stall += 1
                if stall >= 200:      # 兜底：排列空间接近耗尽，允许重复个体
                    pop.append(list(cand))
                    stall = 0
                continue
            stall = 0
            seen.add(key)
            pop.append(cand)

        # 排列空间不足时用已有个体补齐到 pop_size（允许重复）
        while len(pop) < self.pop_size:
            pop.append(list(pop[self.rng.randrange(len(pop))]))
        return pop

    # -------------------------------------------------------------- 遗传算子
    def _select(self, population, costs):
        """锦标赛选择。"""
        best = None
        best_cost = None
        for _ in range(self.tournament_k):
            i = self.rng.randrange(len(population))
            if best_cost is None or costs[i] < best_cost:
                best, best_cost = population[i], costs[i]
        return list(best)

    def _order_crossover(self, p1, p2):
        """顺序交叉（OX）：保留 p1 的一段连续基因，其余按 p2 顺序补齐。"""
        n = len(p1)
        if n < 2:
            return list(p1)
        a, b = sorted(self.rng.sample(range(n), 2))
        child = [None] * n
        child[a:b + 1] = p1[a:b + 1]
        used = set(child[a:b + 1])
        fill = [g for g in p2 if g not in used]
        k = 0
        for i in list(range(b + 1, n)) + list(range(0, a)):
            child[i] = fill[k]
            k += 1
        return child

    def _mutate(self, perm):
        """变异：交换 / 片段反转（等价于对排列做 2-opt 扰动）。"""
        n = len(perm)
        if n < 2:
            return perm
        if self.rng.random() < 0.5:
            i, j = sorted(self.rng.sample(range(n), 2))
            perm[i], perm[j] = perm[j], perm[i]
        else:
            i, j = sorted(self.rng.sample(range(n), 2))
            perm[i:j + 1] = reversed(perm[i:j + 1])
        return perm

    def _two_opt(self, route):
        """对单条路径做 2-opt 局部搜索，返回更优路径。"""
        if len(route) < 3:
            return route
        best = list(route)
        best_d = self._route_distance(best)
        improved = True
        while improved:
            improved = False
            for i in range(len(best) - 1):
                for j in range(i + 1, len(best)):
                    cand = best[:i] + list(reversed(best[i:j + 1])) + best[j + 1:]
                    if not self._route_feasible(cand):
                        continue
                    d = self._route_distance(cand)
                    if d + 1e-9 < best_d:
                        best, best_d = cand, d
                        improved = True
            if not improved:
                break
        return best

    def _two_opt_individual(self, perm):
        """对个体的每条路径分别做 2-opt，再拼回排列。"""
        routes = self.decode(perm)
        new_perm = []
        for r in routes:
            new_perm.extend(self._two_opt(r))
        return new_perm

    # ------------------------------------------------------------------ 求解
    def solve(self, verbose=False):
        if self.n == 0:
            return {"routes": [], "total_distance": 0.0, "tasks": [],
                    "status": "empty", "algorithm": "ga"}
        if self.n == 1:
            route = self._route_record([1])
            if not self._route_feasible([1]):
                return {"routes": [], "total_distance": 0.0, "tasks": [],
                        "status": "infeasible", "algorithm": "ga",
                        "message": "单节点需求超过车辆载重"}
            return {"routes": [route], "total_distance": round(route["dist"], 1),
                    "tasks": self._build_tasks([route]),
                    "status": "ok", "algorithm": "ga"}

        population = self._init_population()
        costs = [self.evaluate(p)[0] for p in population]
        best_perm = list(population[int(np.argmin(costs))])
        best_cost, best_routes = self.evaluate(best_perm)

        for gen in range(self.generations):
            order = sorted(range(len(population)), key=lambda i: costs[i])
            elites = [list(population[i]) for i in order[:self.elite_num]]
            new_pop = elites
            while len(new_pop) < self.pop_size:
                p1 = self._select(population, costs)
                p2 = self._select(population, costs)
                child = (self._order_crossover(p1, p2)
                         if self.rng.random() < self.crossover_rate else list(p1))
                if self.rng.random() < self.mutation_rate:
                    child = self._mutate(child)
                # 以一定概率对子代做 2-opt 局部搜索
                if self.two_opt_passes and self.rng.random() < 0.3:
                    child = self._two_opt_individual(child)
                new_pop.append(child)
            population = new_pop
            costs = [self.evaluate(p)[0] for p in population]
            gen_best = int(np.argmin(costs))
            if costs[gen_best] + 1e-9 < best_cost:
                best_perm = list(population[gen_best])
                best_cost, best_routes = self.evaluate(best_perm)
            if verbose and gen % 20 == 0:
                print(f"[GA] gen={gen} best={best_cost/1000:.2f} km")

        # 收敛后再对最优个体做一轮完整 2-opt 精修
        if self.two_opt_passes:
            polished = best_perm
            for _ in range(self.two_opt_passes):
                polished = self._two_opt_individual(polished)
            p_cost, p_routes = self.evaluate(polished)
            if p_cost + 1e-9 < best_cost:
                best_perm, best_cost, best_routes = polished, p_cost, p_routes

        if len(best_routes) > self.vehicle_num or best_cost >= _BIG:
            return {"routes": [], "total_distance": 0.0, "tasks": [],
                    "status": "infeasible", "algorithm": "ga",
                    "message": f"在 {self.vehicle_num} 辆车内无法满足全部需求，"
                               f"最少需要 {len(best_routes)} 趟"}

        routes = [self._route_record(r) for r in best_routes]
        total = sum(r["dist"] for r in routes)
        return {"routes": routes, "total_distance": round(total, 1),
                "tasks": self._build_tasks(routes), "status": "ok",
                "algorithm": "ga"}


# ===========================================================================
# 求解器二：OR-Tools（对照实现）
# ===========================================================================
class CVRPSolver(_BaseCVRP):
    """
    基于 Google OR-Tools RoutingModel 的 CVRP 求解器。

    载重维度采用「有符号需求 + 自由初始载荷」建模：
      - demand_callback 返回有符号需求（pickup 为正、delivery 为负）；
      - fix_start_cumul_to_zero=False，允许求解器自行选择出发点初始载荷，
        等价于本文档开头的可行性判定 L0 ∈ [max(0,-min Sj), capacity-max Sj]。
    """

    def __init__(self, depot, nodes, capacity=40, vehicle_num=5,
                 ortools_params=None, seed=0):
        super().__init__(depot, nodes, capacity, vehicle_num)
        params = ortools_params or {}
        self.time_limit = params.get("time_limit_seconds", 2)
        self.first_solution = params.get("first_solution_strategy",
                                         "PATH_CHEAPEST_ARC")
        self.local_search = params.get("local_search", "GUIDED_LOCAL_SEARCH")
        self.seed = seed

    def solve(self, verbose=False):
        from ortools.constraint_solver import routing_enums_pb2, pywrapcp

        if self.n == 0:
            return {"routes": [], "total_distance": 0.0, "tasks": [],
                    "status": "empty", "algorithm": "ortools"}
        if self.n == 1:
            route = self._route_record([1])
            if not self._route_feasible([1]):
                return {"routes": [], "total_distance": 0.0, "tasks": [],
                        "status": "infeasible", "algorithm": "ortools"}
            return {"routes": [route], "total_distance": round(route["dist"], 1),
                    "tasks": self._build_tasks([route]),
                    "status": "ok", "algorithm": "ortools"}

        manager = pywrapcp.RoutingIndexManager(self.n + 1, self.vehicle_num, 0)
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_index, to_index):
            f = manager.IndexToNode(from_index)
            t = manager.IndexToNode(to_index)
            return int(self.dist[f][t])

        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        # 有符号需求：pickup 为正、delivery 为负
        def demand_callback(from_index):
            node = manager.IndexToNode(from_index)
            if node == 0:
                return 0
            return int(round(self.nodes[node - 1]["demand"]))

        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        # fix_start_cumul_to_zero=False：允许出发点带初始载荷，从而支持「先投后取」
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index,
            0,
            [self.capacity] * self.vehicle_num,
            False,
            "Capacity",
        )

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
            return {"routes": [], "total_distance": 0.0, "tasks": [],
                    "status": "no_solution", "algorithm": "ortools",
                    "message": "OR-Tools 未在时间上限内找到可行解"}

        raw_routes = []
        for v in range(self.vehicle_num):
            route = []
            idx = routing.Start(v)
            while not routing.IsEnd(idx):
                node = manager.IndexToNode(idx)
                if node != 0:
                    route.append(node)
                idx = solution.Value(routing.NextVar(idx))
            if route:
                raw_routes.append(route)

        routes = [self._route_record(r) for r in raw_routes]
        total = sum(r["dist"] for r in routes)
        return {"routes": routes, "total_distance": round(total, 1),
                "tasks": self._build_tasks(routes), "status": "ok",
                "algorithm": "ortools"}


# ===========================================================================
# 统一入口
# ===========================================================================
def create_solver(depot, nodes, capacity=40, vehicle_num=5, params=None,
                  seed=0, algorithm="ga"):
    """
    按 algorithm 选择求解器：
      - "ga"      ：改进遗传算法（默认，对应选题报告）
      - "ortools" ：OR-Tools RoutingModel（对照实现）
    """
    params = dict(params or {})
    if algorithm == "ortools":
        return CVRPSolver(depot, nodes, capacity=capacity,
                          vehicle_num=vehicle_num, ortools_params=params,
                          seed=seed)
    return GeneticCVRPSolver(depot, nodes, capacity=capacity,
                             vehicle_num=vehicle_num, seed=seed, **params)


# ---------------------------------------------------------------------------
# 聚类结果 -> CVRP 输入构建
# ---------------------------------------------------------------------------
def _split_demand(node, capacity):
    """
    将需求拆分为多个不超过车辆容量的虚拟节点。
    例如 demand=77, capacity=40 -> 拆为 40 + 37 两个同位置节点。
    保证单个节点自身可被一辆车服务。
    """
    sign = 1 if node["demand"] > 0 else -1
    remaining = abs(node["demand"])
    pieces = []
    while remaining > 0:
        q = min(remaining, capacity)
        pieces.append({**node, "demand": sign * q})
        remaining -= q
    return pieces


def summarize_cvrp_input(nodes):
    """
    统计 CVRP 输入的供给/需求总量。

    调度本质是「把堆积区的车搬到空缺区」，因此搬出总量应与投放总量匹配。
    当两者严重失衡时（例如只有堆积区、没有任何空缺区），调度会搬运一批
    无处安放的单车——这属于需求识别问题而非路径问题，需要显式暴露给使用者。
    """
    pickup = sum(int(n["demand"]) for n in nodes if n["demand"] > 0)
    delivery = sum(-int(n["demand"]) for n in nodes if n["demand"] < 0)
    return {
        "pickup_total": pickup,
        "delivery_total": delivery,
        "net_total": pickup - delivery,
        "balanced": pickup == delivery,
    }


def build_cvrp_input(clusters, shortage, depot, capacity=40):
    """
    由双阶段聚类结果构建 CVRP 输入：
      - 堆积区（level>=1）-> pickup 节点（demand = 超额车辆数）
      - 空缺区 -> delivery 节点（demand = 需投放车辆数，取负）
    超额量超过车辆容量的节点自动拆分，保证单节点需求 <= 容量。

    注意：这里不再依赖 ratio>1.0 这一冗余条件（level>=1 已由分级保证），
    只要存在正超额/正缺口就生成节点，避免临界堆积区被整体漏掉。
    """
    nodes = []
    for c in clusters:
        if c.get("level", 0) >= 1:
            surplus = int(c["count"] - c["capacity"])
            if surplus > 0:
                nodes.extend(_split_demand(
                    {"id": c["id"], "lat": c["lat"], "lng": c["lng"],
                     "demand": surplus}, capacity))
    for s in shortage:
        need = int(s["expected"] - s["actual"])
        if need > 0:
            nodes.extend(_split_demand(
                {"id": s["id"], "lat": s["lat"], "lng": s["lng"],
                 "demand": -need}, capacity))
    return nodes


if __name__ == "__main__":
    # 自测：构造 3 个堆积区 + 2 个空缺区，对比 GA 与 OR-Tools
    nodes = [
        {"id": 1, "lat": 34.1435, "lng": 108.8405, "demand": 15},
        {"id": 2, "lat": 34.1425, "lng": 108.8425, "demand": 12},
        {"id": 3, "lat": 34.1445, "lng": 108.8390, "demand": 10},
        {"id": 4, "lat": 34.1415, "lng": 108.8410, "demand": -20},
        {"id": 5, "lat": 34.1430, "lng": 108.8430, "demand": -17},
    ]
    depot = {"lat": 34.1430, "lng": 108.8415}
    for algo in ("ga", "ortools"):
        solver = create_solver(depot, nodes, capacity=40, vehicle_num=3,
                               params={"time_limit_seconds": 2,
                                       "pop_size": 40, "generations": 60},
                               seed=42, algorithm=algo)
        res = solver.solve()
        print(f"[{algo}] status={res['status']} "
              f"total={res['total_distance']} m routes={len(res['routes'])}")
        for t in res["tasks"]:
            print("   vehicle", t["vehicle_id"], "load", t["load"],
                  "stops", [(s["op"], s["qty"]) for s in t["stops"]])
