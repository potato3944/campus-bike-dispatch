# -*- coding: utf-8 -*-
"""轻量位置存储抽象。

默认使用内存字典，接口与报告中的 ``Store`` 约定一致。服务层目前保留
自己的状态快照以支持演示回放；这个模块供独立数据源、脚本和后续 Redis
适配使用，避免调用方直接依赖具体存储实现。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import RLock
from typing import Any


class Store:
    """保存每辆车最近位置，并提供时间窗口查询。"""

    def __init__(self, latest_window_s: float = 120.0) -> None:
        self.latest_window_s = max(0.0, float(latest_window_s))
        self._positions: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value)
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValueError("timestamp 必须是 datetime、Unix 时间戳或 ISO 字符串")

    def update_position(self, bike_id: str | int, lat: float, lng: float,
                        timestamp: Any) -> dict[str, Any]:
        """写入位置；旧时间戳数据不会覆盖更新的位置。"""
        ts = self._timestamp(timestamp)
        key = str(bike_id)
        point = {"bike_id": key, "lat": float(lat), "lng": float(lng),
                 "timestamp": ts.isoformat()}
        with self._lock:
            old = self._positions.get(key)
            if old is None or self._timestamp(old["timestamp"]) <= ts:
                self._positions[key] = point
            return dict(self._positions[key])

    def get_all_positions(self) -> list[dict[str, Any]]:
        """返回所有车辆的最新位置快照。"""
        with self._lock:
            return [dict(p) for p in self._positions.values()]

    def get_latest_positions(self, now: Any | None = None) -> list[dict[str, Any]]:
        """返回时间窗口内的位置；没有数据时返回空列表。"""
        now_dt = self._timestamp(now) if now is not None else datetime.now()
        cutoff = now_dt - timedelta(seconds=self.latest_window_s)
        return [p for p in self.get_all_positions()
                if self._timestamp(p["timestamp"]) >= cutoff]
