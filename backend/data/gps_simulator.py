# -*- coding: utf-8 -*-
"""
模拟 GPS 数据源
基于「随机游走 + 潮汐模型」生成校园共享单车 GPS 数据流：
  - 校园热点（教学楼/图书馆/食堂/宿舍/运动场等）按像素坐标定义，映射到真实经纬度；
  - 潮汐模型：不同时段各热点吸引力不同，模拟教学日借还高峰；
  - 随机游走：使用中的单车向目标热点移动，空闲单车在原地小范围抖动并等待被借走；
  - 输出含 GPS 漂移与重复数据的原始流，供清洗模块处理。
"""

import math
import os
import random
import sys
import time
import asyncio
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geo import pixel_to_latlng, haversine_m

# ---------------------------------------------------------------------------
# 校园热点定义（像素坐标基于 campus_map.jpg，657x661）
# ---------------------------------------------------------------------------
HOTSPOTS = [
    {"name": "教学楼主楼区", "type": "teaching", "px": 210, "py": 170, "weight": 1.0},
    {"name": "教学楼西区",   "type": "teaching", "px": 130, "py": 260, "weight": 0.8},
    {"name": "图书馆",       "type": "library",  "px": 330, "py": 240, "weight": 0.9},
    {"name": "中心广场",     "type": "plaza",    "px": 330, "py": 330, "weight": 0.6},
    {"name": "第一食堂",     "type": "canteen",  "px": 250, "py": 400, "weight": 0.9},
    {"name": "第二食堂",     "type": "canteen",  "px": 430, "py": 420, "weight": 0.8},
    {"name": "运动场",       "type": "gym",      "px": 500, "py": 280, "weight": 0.5},
    {"name": "宿舍区东",     "type": "dorm",     "px": 520, "py": 540, "weight": 1.0},
    {"name": "宿舍区西",     "type": "dorm",     "px": 150, "py": 520, "weight": 0.9},
    {"name": "校门/通勤点",  "type": "gate",     "px": 330, "py": 620, "weight": 0.7},
]

for _h in HOTSPOTS:
    _ll = pixel_to_latlng(_h["px"], _h["py"])
    _h["lat"] = _ll["lat"]
    _h["lng"] = _ll["lng"]


def _tide_factor(hour: float, hotspot_type: str) -> float:
    """
    潮汐模型：返回某时段、某类型热点的吸引力系数。
    模拟教学日 6:00-22:00 的借还潮汐：
      - 上课前(7:30-8:30, 13:30-14:30) 向教学区/图书馆聚集
      - 下课后(12:00-12:40, 17:30-18:30) 向食堂/宿舍聚集
      - 晚间(19:00-22:00) 向运动场/宿舍回流
    """
    base = 0.25
    if hotspot_type in ("teaching", "library"):
        if 7.5 <= hour <= 8.8 or 13.5 <= hour <= 14.8:
            return 1.6
        if 9.0 <= hour <= 11.8 or 15.0 <= hour <= 17.2:
            return 0.9
        if 12.0 <= hour <= 13.0 or 18.0 <= hour <= 19.0:
            return 0.3
    elif hotspot_type == "canteen":
        if 11.5 <= hour <= 12.8 or 17.2 <= hour <= 18.6:
            return 1.8
        if 6.8 <= hour <= 8.2:
            return 1.0
        return 0.4
    elif hotspot_type == "dorm":
        if 21.0 <= hour <= 22.5:
            return 1.5
        if 12.0 <= hour <= 14.0 or 18.5 <= hour <= 21.0:
            return 0.8
        if 7.5 <= hour <= 8.8:
            return 0.5
        return 0.35
    elif hotspot_type == "gym":
        if 17.5 <= hour <= 21.0:
            return 1.2
        return 0.3
    elif hotspot_type == "gate":
        if 7.5 <= hour <= 9.0 or 17.5 <= hour <= 19.0:
            return 1.1
        return 0.4
    elif hotspot_type == "plaza":
        return 0.5
    return base


class Bike:
    """一辆单车的状态"""

    def __init__(self, bike_id, lat, lng, status="idle"):
        self.id = bike_id
        self.lat = lat
        self.lng = lng
        self.status = status          # idle=空闲停放 / moving=使用中
        self.target = None            # 使用中的目标热点
        self.move_speed_kmh = 10.0    # 骑行速度

    def to_dict(self, ts):
        return {
            "bike_id": self.id,
            "lat": round(self.lat, 7),
            "lng": round(self.lng, 7),
            "status": self.status,
            "ts": ts,
        }


class GpsSimulator:
    """校园共享单车 GPS 数据生成器（随机游走 + 潮汐模型）"""

    def __init__(self, total_bikes: int = 600, seed: int = 7):
        self.total = total_bikes
        self.rng = random.Random(seed)
        np.random.seed(seed)
        self.bikes = []
        # 单车初始位置：围绕各热点高斯散布，权重高的热点停放更多
        weights = np.array([h["weight"] for h in HOTSPOTS], dtype=float)
        probs = weights / weights.sum()
        for i in range(total_bikes):
            h = HOTSPOTS[int(np.random.choice(len(HOTSPOTS), p=probs))]
            lat = h["lat"] + self.rng.gauss(0, 0.00035)
            lng = h["lng"] + self.rng.gauss(0, 0.00035)
            self.bikes.append(Bike(i + 1, lat, lng))
        self._seq = 0

    # -- 潮汐 / 需求 -------------------------------------------------------
    def demand_weights(self, sim_time: datetime):
        """当前时刻各热点需求强度（借车概率权重）"""
        hour = sim_time.hour + sim_time.minute / 60.0
        w = []
        for h in HOTSPOTS:
            w.append(_tide_factor(hour, h["type"]) * h["weight"])
        return np.array(w, dtype=float)

    def _pick_target(self, sim_time):
        """按潮汐权重随机挑选一个目标热点"""
        w = self.demand_weights(sim_time)
        w = w / w.sum()
        return HOTSPOTS[int(np.random.choice(len(HOTSPOTS), p=w))]

    # -- 状态推进 ---------------------------------------------------------
    def step(self, sim_time: datetime, dt_s: float = 10.0):
        """
        推进一个时间步（默认 10 秒），返回本步产生的 GPS 事件列表。
        事件包含：位置更新（全部单车）与状态切换（借/还）。
        """
        events = []
        dt_h = dt_s / 3600.0
        hour = sim_time.hour + sim_time.minute / 60.0

        for b in self.bikes:
            if b.status == "moving":
                # 向目标热点移动：按骑行速度前进，到达后还车（变为空闲）
                h = b.target
                dist = haversine_m(b.lat, b.lng, h["lat"], h["lng"])
                step_m = b.move_speed_kmh * 1000 * dt_h
                if dist <= step_m or dist < 5.0:
                    b.lat, b.lng = h["lat"], h["lng"]
                    b.status = "idle"
                    b.target = None
                    events.append({**b.to_dict(sim_time.isoformat()), "event": "return"})
                else:
                    # 沿大圆方向前进一小步（随机游走 + 方向噪声）
                    bearing = math.atan2(
                        (h["lng"] - b.lng) * math.cos(math.radians(b.lat)),
                        h["lat"] - b.lat,
                    )
                    d_lat = step_m / 111320.0
                    d_lng = step_m / (111320.0 * math.cos(math.radians(b.lat)))
                    noise = self.rng.gauss(0, 0.00006)  # GPS 噪声
                    b.lat += d_lat * math.cos(bearing) + noise
                    b.lng += d_lng * math.sin(bearing) + noise
                    events.append({**b.to_dict(sim_time.isoformat()), "event": "move"})
            else:
                # 空闲单车：小范围随机游走抖动（停放位置微扰）
                b.lat += self.rng.gauss(0, 0.00004)
                b.lng += self.rng.gauss(0, 0.00004)
                # 按潮汐需求概率被借走（上课高峰、下课高峰借车概率高）
                w = self.demand_weights(sim_time)
                total_w = float(w.sum())
                p_borrow = min(0.35, 0.15 * total_w / (len(HOTSPOTS) * 0.9))
                if self.rng.random() < p_borrow:
                    b.target = self._pick_target(sim_time)
                    b.status = "moving"
                    b.move_speed_kmh = self.rng.uniform(8.0, 12.0)
                    events.append({**b.to_dict(sim_time.isoformat()), "event": "borrow"})
                else:
                    events.append({**b.to_dict(sim_time.isoformat()), "event": "idle"})
        return events

    def generate_stream(self, start_time: datetime | None = None,
                        step_seconds: float = 60.0,
                        max_steps: int | None = None,
                        realtime: bool = False):
        """持续生成原始 GPS 事件，供 WebSocket 或独立脚本消费。

        每个 ``yield`` 是一个包含 ``bike_id/lat/lng/status/ts/event`` 的字典。
        ``max_steps`` 便于测试和演示；留空时持续运行。设置 ``realtime`` 后，
        每一步按墙钟等待 ``step_seconds``，默认关闭以便仿真快速推进。
        """
        if step_seconds <= 0:
            raise ValueError("step_seconds 必须大于 0")
        sim_time = start_time or datetime.now().replace(microsecond=0)
        step = 0
        while max_steps is None or step < max_steps:
            for event in self.step(sim_time, dt_s=step_seconds):
                event = dict(event)
                # Prompt/报告使用 timestamp 命名；保留现有 ts 字段以兼容清洗器。
                event.setdefault("timestamp", event.get("ts"))
                yield event
            step += 1
            sim_time += timedelta(seconds=step_seconds)
            if realtime:
                time.sleep(step_seconds)


async def push_stream(uri: str = "ws://localhost:8000/ws/gps",
                      total_bikes: int = 300,
                      step_seconds: float = 10.0) -> None:
    """把模拟 GPS 流推送到后端 WebSocket，供独立数据源进程使用。"""
    import json
    import websockets

    simulator = GpsSimulator(total_bikes=total_bikes)
    async with websockets.connect(uri) as websocket:
        for event in simulator.generate_stream(step_seconds=step_seconds,
                                                realtime=True):
            await websocket.send(json.dumps(event, ensure_ascii=False))
            await asyncio.sleep(0)


if __name__ == "__main__":
    # ``python data/gps_simulator.py`` 运行本地自测；加 --push 时作为独立
    # WebSocket 数据源连接已启动的 FastAPI 服务。
    if "--push" in sys.argv:
        asyncio.run(push_stream())
        raise SystemExit(0)

    # 简单自测：运行 1 分钟数据流
    sim = GpsSimulator(total_bikes=20)
    t0 = datetime(2026, 9, 21, 7, 30, 0)
    n = 0
    for i in range(6):
        t = t0 + timedelta(seconds=10 * i)
        evs = sim.step(t, 10.0)
        n += len(evs)
        print(t.strftime("%H:%M:%S"), "events:", len(evs),
              "moving:", sum(1 for b in sim.bikes if b.status == "moving"))
    print("total events:", n)
