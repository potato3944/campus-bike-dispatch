# -*- coding: utf-8 -*-
"""
SimPy 离散事件仿真模块

模拟教学日（6:00~22:00）校园共享单车借还运行，对比三类调度策略：
  1. none        ：无调度（放任自然分布）
  2. threshold   ：阈值触发调度（区域单车数偏离容量超阈值即触发搬运）
  3. predictive  ：预测性调度（依据潮汐模型预测未来需求，提前调车到即将缺车区域）

评估指标：
  - 周转率       ：总成功借车次数 / 投放车辆总数
  - 调度成本     ：固定成本 * 任务数 + 单位距离成本 * 总调度里程
  - 供需匹配率   ：成功借车次数 / 总需求次数
  - 用户平均等待时间：需求产生到成功借车的平均时长（分钟）
  - 系统综合得分（成本口径）：调度成本 + 等待惩罚
"""

import math
import os
import random
import sys

import simpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geo import haversine_m


# ---------------------------------------------------------------------------
# 潮汐需求函数（教学日）
# ---------------------------------------------------------------------------
def tide_factor(hour: float, zone_type: str) -> float:
    """某时段、某类型区域的借车需求强度系数（0~2.0）"""
    if zone_type in ("teaching", "library"):
        if 7.5 <= hour <= 8.8 or 13.5 <= hour <= 14.8:
            return 1.8
        if 9.0 <= hour <= 11.8 or 15.0 <= hour <= 17.2:
            return 0.9
        return 0.3
    if zone_type == "canteen":
        if 11.5 <= hour <= 12.8 or 17.2 <= hour <= 18.6:
            return 1.9
        return 0.4
    if zone_type == "dorm":
        if 21.0 <= hour <= 22.5:
            return 1.6
        if 12.0 <= hour <= 14.0 or 18.5 <= hour <= 21.0:
            return 0.9
        return 0.35
    if zone_type == "gym":
        if 17.5 <= hour <= 21.0:
            return 1.3
        return 0.25
    if zone_type == "gate":
        if 7.5 <= hour <= 9.0 or 17.5 <= hour <= 19.0:
            return 1.2
        return 0.4
    if zone_type == "plaza":
        return 0.5
    return 0.3


# ---------------------------------------------------------------------------
# 区域
# ---------------------------------------------------------------------------
class Zone:
    def __init__(self, zone_id, name, zone_type, lat, lng, capacity):
        self.id = zone_id
        self.name = name
        self.type = zone_type
        self.lat = lat
        self.lng = lng
        self.capacity = capacity
        self.bikes = 0

    def __repr__(self):
        return f"<Zone {self.id} {self.name} bikes={self.bikes}/{self.capacity}>"


# ---------------------------------------------------------------------------
# 仿真主类
# ---------------------------------------------------------------------------
class BikeSimulation:
    def __init__(self, zones, total_bikes=600, strategy="none", seed=42,
                 duration_h=16.0, arrival_rate_per_h=400.0,
                 threshold_imbalance=25, predict_window_min=30.0,
                 vehicle_cost_per_km=2.0, fix_cost_per_task=5.0,
                 wait_penalty_per_min=0.5, check_interval_min=5.0,
                 vehicle_speed_kmh=20.0, max_user_wait_min=10.0):
        self.env = simpy.Environment()
        self.zones = zones
        self.total_bikes = total_bikes
        self.strategy = strategy
        self.rng = random.Random(seed)
        self.duration_h = duration_h
        self.arrival_rate = arrival_rate_per_h
        self.threshold_imbalance = threshold_imbalance
        self.predict_window = predict_window_min
        self.vehicle_cost = vehicle_cost_per_km
        self.fix_cost = fix_cost_per_task
        self.wait_penalty = wait_penalty_per_min
        self.check_interval = check_interval_min
        self.vehicle_speed = max(vehicle_speed_kmh, 1e-6)   # 调度车行驶速度
        self.max_user_wait = max_user_wait_min              # 用户最长等待（分钟）

        # 指标统计
        self.demand_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.total_wait_min = 0.0          # 仅成功借车的等待合计
        self.total_wait_all_min = 0.0      # 含失败用户的等待合计（失败按最长等待计）
        self.dispatch_tasks = 0
        self.dispatch_distance_km = 0.0
        self.moved_bikes = 0               # 实际搬运成功的单车数
        self.unserved_bikes = 0            # 因目的地容量/来源不足未能搬运的数量
        self.overflow_returns = 0          # 目的地已满仍还车（超容乱停放）次数
        self.rides = 0
        self.borrow_events = []     # (time, zone_id)
        self.return_events = []     # (time, zone_id)
        self._check_interval = check_interval_min   # 调度检查间隔（分钟）

        # 单车初始分布：按区域容量均匀投放
        cap_sum = sum(z.capacity for z in self.zones)
        for z in self.zones:
            z.bikes = int(total_bikes * z.capacity / cap_sum)

    # ------------------------------------------------------------------ 事件
    def _current_hour(self):
        return 6.0 + self.env.now / 60.0

    def user_process(self):
        """用户借车需求生成进程（泊松到达，到达率随潮汐变化）"""
        while self.env.now < self.duration_h * 60:
            hour = self._current_hour()
            # 总到达率 = 基础率 * 当前时段平均潮汐强度
            avg_tide = sum(tide_factor(hour, z.type) for z in self.zones) / len(self.zones)
            rate = self.arrival_rate * avg_tide
            interval = self.rng.expovariate(max(rate / 60.0, 1e-6))  # 分钟
            yield self.env.timeout(interval)
            self.demand_count += 1
            # 选择借车区域：潮汐权重随机
            weights = [tide_factor(hour, z.type) for z in self.zones]
            total = sum(weights)
            probs = [w / total for w in weights]
            z = self.rng.choices(self.zones, weights=probs)[0]
            self.env.process(self.borrow(z))

    def borrow(self, zone):
        """借车过程：有车立即借走，无车等待（最多等 max_user_wait 分钟）"""
        waited = 0.0
        while zone.bikes <= 0 and waited < self.max_user_wait:
            yield self.env.timeout(1.0)
            waited += 1.0
        if zone.bikes > 0:
            zone.bikes -= 1
            self.success_count += 1
            self.rides += 1
            self.total_wait_min += waited
            self.total_wait_all_min += waited
            self.borrow_events.append((self.env.now, zone.id))
            # 骑行后还车到另一区域（目的地按潮汐选）
            self.env.process(self.ride_and_return(zone))
        else:
            # 失败用户同样等满了最长等待时间，应计入总体等待，否则平均等待会被系统性低估
            self.fail_count += 1
            self.total_wait_all_min += waited

    def ride_and_return(self, from_zone):
        """骑行一段时间后还车到目的地"""
        ride_min = self.rng.uniform(5, 15)
        yield self.env.timeout(ride_min)
        hour = self._current_hour()
        weights = [tide_factor(hour, z.type) for z in self.zones]
        total = sum(weights)
        probs = [w / total for w in weights]
        dest = self.rng.choices(self.zones, weights=probs)[0]
        # 目的地容量限制：超出容量时仍允许还车（模拟真实中的超容乱停放），
        # 但单独计数，便于后续分析「超容区域」这一失衡信号。
        if dest.bikes >= dest.capacity:
            self.overflow_returns += 1
        dest.bikes += 1
        self.return_events.append((self.env.now, dest.id))

    # ------------------------------------------------------------------ 调度
    def dispatch_process(self):
        """周期检查区域平衡并触发调度（每趟任务按距离耗时异步执行）"""
        while self.env.now < self.duration_h * 60:
            yield self.env.timeout(self._check_interval)
            tasks = self._plan_dispatch()
            for task in tasks:
                self.env.process(self._execute_dispatch(task))

    def _zone_imbalance(self, zone):
        """区域不平衡量：>0 表示堆积（需运走），<0 表示空缺（需投放）"""
        ideal = zone.capacity * 0.6
        return zone.bikes - ideal

    def _plan_dispatch(self):
        """根据策略生成调度任务列表"""
        if self.strategy == "none":
            return []
        hour = self._current_hour()
        tasks = []
        if self.strategy == "threshold":
            for z in self.zones:
                imb = self._zone_imbalance(z)
                if abs(imb) >= self.threshold_imbalance:
                    qty = int(abs(imb) * 0.7)   # 搬运失衡量的 70%，避免过调
                    tasks.append({"zone": z, "qty": qty, "direction": "out" if imb > 0 else "in"})
        elif self.strategy == "predictive":
            # 预测未来 predict_window 内各区域需求变化：
            # 在预测窗口上均匀采样多个时点求平均，而不是用同一个未来值重复凑数。
            samples = 5
            horizon_h = self.predict_window / 60.0
            for z in self.zones:
                future = sum(
                    tide_factor(hour + horizon_h * (i + 1) / samples, z.type)
                    for i in range(samples)) / samples
                current = tide_factor(hour, z.type)
                # 未来需求显著高于当前 -> 需补车；显著低于 -> 可调出
                diff = future - current
                if diff > 0.5 and z.bikes < z.capacity * 0.5:
                    tasks.append({"zone": z,
                                  "qty": int(z.capacity * 0.4 - z.bikes),
                                  "direction": "in"})
                elif diff < -0.5 and z.bikes > z.capacity * 0.7:
                    tasks.append({"zone": z,
                                  "qty": int(z.bikes - z.capacity * 0.4),
                                  "direction": "out"})
        # 配对：运出(direction=out) -> 运入(direction=in)，生成搬运任务
        return self._pair_tasks(tasks)

    def _pair_tasks(self, tasks):
        outs = [t for t in tasks if t["direction"] == "out" and t["qty"] > 0]
        ins = [t for t in tasks if t["direction"] == "in" and t["qty"] > 0]
        paired = []
        for o in outs:
            for i in ins:
                if o["qty"] <= 0:
                    break
                move = min(o["qty"], i["qty"])
                if move <= 0:
                    continue
                dist_km = haversine_m(o["zone"].lat, o["zone"].lng,
                                      i["zone"].lat, i["zone"].lng) / 1000.0
                paired.append({"from": o["zone"], "to": i["zone"],
                               "qty": move, "dist_km": dist_km})
                o["qty"] -= move
                i["qty"] -= move
        return paired

    def _execute_dispatch(self, task):
        """
        执行一次搬运：先按距离消耗行驶时间，再落车。
        搬运量受三重约束：任务计划量、来源可用量、目的地剩余容量，
        未能搬运的部分计入 unserved_bikes，避免出现「目的地超容」这种不物理的结果。
        """
        f, t = task["from"], task["to"]
        # 行驶时间：里程 / 车速（小时 -> 分钟）
        travel_min = task["dist_km"] / self.vehicle_speed * 60.0
        if travel_min > 0:
            yield self.env.timeout(travel_min)

        qty = min(task["qty"], f.bikes, max(0, t.capacity - t.bikes))
        qty = max(0, int(qty))
        if qty <= 0:
            self.unserved_bikes += max(0, int(task["qty"]))
            return
        f.bikes -= qty
        t.bikes += qty
        self.moved_bikes += qty
        self.unserved_bikes += max(0, int(task["qty"] - qty))
        self.dispatch_tasks += 1
        self.dispatch_distance_km += task["dist_km"]

    # ------------------------------------------------------------------ 运行
    def run(self):
        self.env.process(self.user_process())
        self.env.process(self.dispatch_process())
        self.env.run(until=self.duration_h * 60)
        return self.metrics()

    def metrics(self):
        """汇总评估指标"""
        turnover = self.rides / self.total_bikes if self.total_bikes else 0.0
        match_rate = (self.success_count / self.demand_count
                      if self.demand_count else 0.0)
        # 平均等待：默认口径覆盖全部需求（含等待后仍失败的用户），
        # 否则只统计成功用户会系统性低估等待水平。
        avg_wait = (self.total_wait_all_min / self.demand_count
                    if self.demand_count else 0.0)
        avg_wait_success = (self.total_wait_min / self.success_count
                            if self.success_count else 0.0)
        dispatch_cost = (self.fix_cost * self.dispatch_tasks +
                         self.vehicle_cost * self.dispatch_distance_km)
        wait_cost = self.total_wait_all_min * self.wait_penalty
        total_cost = dispatch_cost + wait_cost
        # 仿真结束时仍在等待中的请求：demand = success + fail + pending
        pending = max(0, self.demand_count - self.success_count - self.fail_count)
        return {
            "strategy": self.strategy,
            "demand_count": self.demand_count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "pending_count": pending,
            "turnover_rate": round(turnover, 3),
            "match_rate": round(match_rate, 3),
            "avg_wait_min": round(avg_wait, 2),
            "avg_wait_success_min": round(avg_wait_success, 2),
            "dispatch_tasks": self.dispatch_tasks,
            "dispatch_distance_km": round(self.dispatch_distance_km, 2),
            "moved_bikes": self.moved_bikes,
            "unserved_bikes": self.unserved_bikes,
            "overflow_returns": self.overflow_returns,
            "dispatch_cost": round(dispatch_cost, 2),
            "wait_cost": round(wait_cost, 2),
            "total_cost": round(total_cost, 2),
        }


# ---------------------------------------------------------------------------
# 校园区域构造（与 GPS 模拟器热点一致，容量按权重分配）
# ---------------------------------------------------------------------------
def build_campus_zones(hotspots, total_bikes=600, capacity_per_zone=60):
    zones = []
    for i, h in enumerate(hotspots):
        cap = int(capacity_per_zone * (0.6 + 0.6 * h["weight"]))
        zones.append(Zone(i + 1, h["name"], h["type"], h["lat"], h["lng"], cap))
    return zones


def run_all_strategies(hotspots, total_bikes=600, seed=42, **params):
    """运行三类调度策略对比，返回指标列表"""
    results = []
    for strategy in ("none", "threshold", "predictive"):
        zones = build_campus_zones(hotspots, total_bikes)
        sim = BikeSimulation(zones, total_bikes=total_bikes, strategy=strategy,
                             seed=seed, **params)
        results.append(sim.run())
    return results


if __name__ == "__main__":
    # 自测：快速对比三种策略
    from data.gps_simulator import HOTSPOTS
    res = run_all_strategies(HOTSPOTS, total_bikes=600,
                             duration_h=8.0, arrival_rate_per_h=300.0)
    for m in res:
        print(m)
