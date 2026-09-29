# -*- coding: utf-8 -*-
"""
双阶段聚类模块（DBSCAN + K-means）

阶段一 DBSCAN：粗粒度识别车辆聚集区域（堆积区）与稀疏区域（空缺区）；
阶段二 K-means：对聚集区内点位二次聚类，并按「单车数量 / 区域容量」划分堆积等级。

本模块使用 scikit-learn 成熟的 DBSCAN / KMeans 实现，
经纬度坐标先投影为近似米制平面坐标，便于直接使用米为单位的邻域参数。
"""

import math

import numpy as np
from sklearn.cluster import DBSCAN as SkDBSCAN
from sklearn.cluster import KMeans as SkKMeans

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geo import haversine_m


# ---------------------------------------------------------------------------
# 坐标转换
# ---------------------------------------------------------------------------
def _to_xy(points):
    """
    经纬度 -> 近似米制平面坐标（以首点为原点，局部等距投影）。
    校园尺度（约 1km）内误差可忽略。
    points: list[(lat, lng)]
    """
    lat0, lng0 = points[0]
    cos_lat = math.cos(math.radians(lat0))
    xy = []
    for lat, lng in points:
        x = (lng - lng0) * 111320.0 * cos_lat
        y = (lat - lat0) * 111320.0
        xy.append([x, y])
    return np.array(xy, dtype=float)


# ---------------------------------------------------------------------------
# 聚类主流程
# ---------------------------------------------------------------------------
def detect_imbalance(points, hotspots, eps_m=80.0, min_samples=5,
                     k_levels=3, capacity_per_zone=60.0):
    """
    双阶段聚类识别堆积区与空缺区（基于 scikit-learn）。

    points:   当前全部单车 GPS 点 list[(lat, lng)]
    hotspots: 校园热点（含 type/lat/lng/weight），用于空缺判定
    返回 dict：
      - clusters: 堆积区列表 [{id, lat, lng, count, capacity, ratio, level, radius_m}]
      - shortage: 空缺区列表 [{id, name, lat, lng, expected, actual, shortage_ratio, level}]
      - heat: 热力数据点 [{lat, lng, intensity}]
      - stats: 统计信息
    """
    result = {"clusters": [], "shortage": [], "heat": [], "stats": {}}
    n = len(points)
    if n == 0:
        result["stats"] = {"points": 0, "clusters": 0, "shortage": 0}
        return result

    X = _to_xy(points)

    # ---- 阶段一：DBSCAN 粗粒度聚集区 ----
    db = SkDBSCAN(eps=eps_m, min_samples=min_samples).fit(X)
    labels = db.labels_
    n_clusters = int(labels.max()) + 1 if len(labels) > 0 else 0
    result["stats"]["dbscan_clusters"] = max(n_clusters, 0)

    # ---- 阶段二：K-means 二次聚类 + 堆积等级 ----
    cluster_id = 0
    for c in range(n_clusters):
        idx = np.where(labels == c)[0]
        if len(idx) < min_samples:
            continue
        k = min(k_levels, len(idx))
        if k >= 2:
            km = SkKMeans(n_clusters=k, init="k-means++", n_init=10,
                          random_state=c).fit(X[idx])
            sub_labels = km.labels_
            centroids_xy = km.cluster_centers_
        else:
            sub_labels = np.zeros(len(idx), dtype=int)
            centroids_xy = X[idx].mean(axis=0, keepdims=True)

        for s in range(k):
            sub_idx = np.where(sub_labels == s)[0]
            count = len(sub_idx)
            # 簇中心还原为经纬度
            cx, cy = centroids_xy[s]
            lat = points[0][0] + cy / 111320.0
            lng = points[0][1] + cx / (111320.0 * math.cos(math.radians(points[0][0])))
            # 区域半径：簇内点到质心距离的 85 分位
            dists = [haversine_m(lat, lng, points[i][0], points[i][1]) for i in sub_idx]
            radius = float(np.percentile(dists, 85)) if dists else 60.0
            ratio = count / capacity_per_zone
            if ratio >= 1.0:
                level = 3
            elif ratio >= 0.6:
                level = 2
            elif ratio >= 0.35:
                level = 1
            else:
                level = 0
            cluster_id += 1
            result["clusters"].append({
                "id": cluster_id,
                "lat": round(lat, 7),
                "lng": round(lng, 7),
                "count": int(count),
                "capacity": int(capacity_per_zone),
                "ratio": round(ratio, 3),
                "level": level,
                "radius_m": round(radius, 1),
            })
            result["heat"].append({"lat": round(lat, 7), "lng": round(lng, 7),
                                   "intensity": round(float(min(ratio, 2.0)), 3)})

    # ---- 空缺区识别：热点周边单车密度过低 ----
    bike_lats = np.array([p[0] for p in points])
    bike_lngs = np.array([p[1] for p in points])
    shortage_id = 0
    for h in hotspots:
        dists = np.array([haversine_m(h["lat"], h["lng"], la, ln)
                          for la, ln in zip(bike_lats, bike_lngs)])
        actual = int((dists <= 150.0).sum())
        expected = max(20, int(h["weight"] * capacity_per_zone * 0.8))
        ratio = actual / expected if expected else 0.0
        if ratio < 0.4 and actual < 15:
            shortage_id += 1
            result["shortage"].append({
                "id": shortage_id,
                "name": h["name"],
                "lat": round(h["lat"], 7),
                "lng": round(h["lng"], 7),
                "expected": expected,
                "actual": actual,
                "shortage_ratio": round(1 - ratio, 3),
                "level": 2 if ratio < 0.2 else 1,
            })

    result["stats"] = {
        "points": n,
        "clusters": len(result["clusters"]),
        "shortage": len(result["shortage"]),
        "dbscan_clusters": n_clusters,
    }
    return result


if __name__ == "__main__":
    # 自测：构造三堆聚集点 + 若干离群点
    rng = np.random.default_rng(1)
    pts = []
    for (la, ln, num) in [(34.143, 108.840, 40), (34.142, 108.842, 30),
                          (34.145, 108.839, 25)]:
        pts += [(la + rng.normal(0, 0.0003), ln + rng.normal(0, 0.0003))
                for _ in range(num)]
    pts += [(34.144, 108.844) for _ in range(3)]   # 噪声
    from data.gps_simulator import HOTSPOTS
    res = detect_imbalance(pts, HOTSPOTS)
    print("stats:", res["stats"])
    print("clusters:", len(res["clusters"]), "shortage:", len(res["shortage"]))
    for c in res["clusters"][:5]:
        print("  cluster", c["id"], "count", c["count"], "level", c["level"],
              "ratio", c["ratio"])
