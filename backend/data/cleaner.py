# -*- coding: utf-8 -*-
"""
GPS 数据清洗模块
对流式 GPS 数据进行实时清洗：
  1. 漂移过滤：相邻两点推算速度超过单车最大速度阈值 -> 视为 GPS 漂移点丢弃；
  2. 重复去重：同一单车在短时间窗口内位置几乎不变 -> 合并为单点；
  3. 边界过滤：超出校园地图标定范围的点丢弃。
"""

import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geo import haversine_m, MAP


class DataCleaner:
    def __init__(self, max_speed_kmh: float = 12.0, dedup_dist_m: float = 3.0,
                 dedup_window_s: float = 30.0):
        self.max_speed_kmh = max_speed_kmh
        self.dedup_dist_m = dedup_dist_m
        self.dedup_window_s = dedup_window_s
        self._last = {}          # bike_id -> (ts, lat, lng, event)
        self._last_dedup = {}    # bike_id -> (ts, lat, lng)
        self.stats = {"total": 0, "drift_removed": 0, "dup_removed": 0,
                      "out_of_bound": 0, "kept": 0}

    def _parse_ts(self, ts):
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts)
        if isinstance(ts, datetime):
            return ts
        try:
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return datetime.now()

    def _in_bounds(self, lat, lng):
        tl, br = MAP["top_left"], MAP["bottom_right"]
        return (tl["lat"] - 0.01 <= lat <= br["lat"] + 0.01 and
                tl["lng"] - 0.01 <= lng <= br["lng"] + 0.01)

    def clean(self, point: dict) -> dict | None:
        """
        清洗单个 GPS 点，返回保留后的点（含清洗标记），丢弃则返回 None。
        """
        self.stats["total"] += 1
        bike_id = point.get("bike_id")
        lat, lng = point.get("lat"), point.get("lng")
        ts = self._parse_ts(point.get("ts"))

        # 1) 边界过滤
        if not self._in_bounds(lat, lng):
            self.stats["out_of_bound"] += 1
            return None

        # 2) 漂移过滤：与上一有效点推算速度
        prev = self._last.get(bike_id)
        if prev is not None:
            prev_ts, prev_lat, prev_lng, prev_event = prev
            dt_s = max((ts - prev_ts).total_seconds(), 0.1)
            if dt_s < 300:
                dist_m = haversine_m(prev_lat, prev_lng, lat, lng)
                speed_kmh = dist_m / dt_s * 3.6
                if speed_kmh > self.max_speed_kmh * 1.8:
                    self.stats["drift_removed"] += 1
                    return None

        # 3) 重复去重：短窗口内位置几乎不变
        last_d = self._last_dedup.get(bike_id)
        if last_d is not None:
            d_ts, d_lat, d_lng = last_d
            dt_s = (ts - d_ts).total_seconds()
            dist_m = haversine_m(d_lat, d_lng, lat, lng)
            if dt_s < self.dedup_window_s and dist_m < self.dedup_dist_m:
                self.stats["dup_removed"] += 1
                return None

        # 更新状态并返回保留点
        self._last[bike_id] = (ts, lat, lng, point.get("event"))
        self._last_dedup[bike_id] = (ts, lat, lng)
        self.stats["kept"] += 1
        out = dict(point)
        out["clean"] = True
        return out


if __name__ == "__main__":
    # 自测：漂移点与重复点应被过滤
    c = DataCleaner()
    t0 = datetime(2026, 9, 21, 8, 0, 0)
    base = {"bike_id": 1, "lat": 34.143, "lng": 108.841, "event": "idle"}
    print(c.clean({**base, "ts": t0.isoformat()}))
    # 重复点
    print(c.clean({**base, "ts": (t0 + timedelta(seconds=5)).isoformat()}))
    # 漂移点（速度 50km/h）
    print(c.clean({"bike_id": 1, "lat": 34.1445, "lng": 108.842,
                   "ts": (t0 + timedelta(seconds=10)).isoformat(), "event": "move"}))
    # 正常点
    print(c.clean({"bike_id": 1, "lat": 34.14305, "lng": 108.84105,
                   "ts": (t0 + timedelta(seconds=60)).isoformat(), "event": "move"}))
    print("stats:", c.stats)
