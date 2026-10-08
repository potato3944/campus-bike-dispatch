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


def _grade(ratio, thresholds=(0.35, 0.6, 1.0)):
    """按「单车数 / 区域容量」比值划分堆积等级 0~3。"""
    if ratio >= thresholds[2]:
        return 3
    if ratio >= thresholds[1]:
        return 2
    if ratio >= thresholds[0]:
        return 1
    return 0


def _finite_mask(points):
    """过滤坐标缺失/非有限值的点位，避免污染聚类与距离计算。"""
    mask = []
    for p in points:
        try:
            lat, lng = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            mask.append(False)
            continue
        mask.append(math.isfinite(lat) and math.isfinite(lng))
    return np.array(mask, dtype=bool)


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
    # 过滤坐标缺失/非有限值的点，避免后续距离计算抛出异常或产生 NaN 聚类
    raw_n = len(points)
    mask = _finite_mask(points)
    points = [p for p, ok in zip(points, mask) if ok]
    n = len(points)
    if n == 0:
        result["stats"] = {"points": 0, "clusters": 0, "shortage": 0,
                           "invalid_points": raw_n}
        return result
    if raw_n != n:
        result["stats"]["invalid_points"] = raw_n - n

    X = _to_xy(points)

    # ---- 阶段一：DBSCAN 粗粒度聚集区 ----
    db = SkDBSCAN(eps=eps_m, min_samples=min_samples).fit(X)
    labels = db.labels_
    n_clusters = int(labels.max()) + 1 if len(labels) > 0 else 0
    result["stats"]["dbscan_clusters"] = max(n_clusters, 0)

    # 参数调优提示：单车平均间距小于 eps 时 DBSCAN 会把整片校园串成一个大簇，
    # 此时堆积区无法被区分出来（对应选题报告提到的「双阶段聚类参数调优」关键问题）。
    warnings = []
    if n_clusters == 1 and n >= 4 * min_samples:
        warnings.append(
            f"DBSCAN 仅形成 1 个簇（eps_m={eps_m}），说明邻域半径相对当前单车密度过大，"
            "堆积区可能被串成一片；建议减小 eps_m 或增大 min_samples 后重新扫描。")
    noise_ratio = float((labels == -1).sum()) / n if n else 0.0
    if noise_ratio > 0.8:
        warnings.append(
            f"噪声点占比 {noise_ratio:.0%}，说明 eps_m={eps_m} 相对过小，"
            "大部分单车未被归入任何聚集区。")
    if warnings:
        result["stats"]["warnings"] = warnings

    # ---- 阶段二：K-means 二次聚类 + 堆积等级 ----
    # 注意：K-means 只在簇内点位（X[idx]）上拟合，其标签/质心均为「簇内相对下标」，
    # 回查原始点集时必须经 idx 映射，否则会取错点、算错半径。
    cluster_id = 0
    lat0, lng0 = points[0]
    m_per_deg_lng = 111320.0 * math.cos(math.radians(lat0))
    for c in range(n_clusters):
        idx = np.where(labels == c)[0]
        if len(idx) < min_samples:
            continue

        # 堆积等级按「整个 DBSCAN 簇」的总量对容量评级：
        # 若按 K-means 子簇各自评级，会把一个明显超载的大堆积区拆成若干「未超载」子区，低估堆积程度。
        cluster_count = int(len(idx))
        cluster_ratio = cluster_count / capacity_per_zone
        level = _grade(cluster_ratio)

        # K-means 仅用于在空间上把一个堆积区拆成若干标记点，便于热力与标注展示
        k = min(k_levels, cluster_count)
        sub_labels = None
        centroids_xy = None
        if k >= 2:
            # 全同坐标会让 K-means 退化告警，先判断是否有点间差异
            if np.unique(X[idx], axis=0).shape[0] >= k:
                km = SkKMeans(n_clusters=k, init="k-means++", n_init=10,
                              random_state=c).fit(X[idx])
                sub_labels = km.labels_
                centroids_xy = km.cluster_centers_
        if sub_labels is None:
            sub_labels = np.zeros(cluster_count, dtype=int)
            centroids_xy = X[idx].mean(axis=0, keepdims=True)
            k = 1

        for s in range(k):
            sub_idx = np.where(sub_labels == s)[0]      # 相对 X[idx] 的下标
            count = len(sub_idx)
            if count == 0:
                continue
            # 簇中心还原为经纬度
            cx, cy = centroids_xy[s]
            lat = float(lat0 + cy / 111320.0)
            lng = float(lng0 + cx / m_per_deg_lng)
            # 区域半径：簇内点到质心距离的 85 分位（必须经 idx 映射回全局点集）
            dists = [haversine_m(lat, lng,
                                 points[idx[j]][0], points[idx[j]][1])
                     for j in sub_idx]
            radius = float(np.percentile(dists, 85)) if dists else 60.0
            cluster_id += 1
            result["clusters"].append({
                "id": cluster_id,
                "lat": round(lat, 7),
                "lng": round(lng, 7),
                "count": int(count),
                "capacity": int(capacity_per_zone),
                "ratio": round(count / capacity_per_zone, 3),
                "cluster_count": cluster_count,
                "cluster_ratio": round(cluster_ratio, 3),
                "level": level,
                "radius_m": round(radius, 1),
            })
            result["heat"].append({"lat": round(lat, 7), "lng": round(lng, 7),
                                   "intensity": round(float(min(cluster_ratio, 2.0)), 3)})

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

    stats = {
        "points": n,
        "clusters": len(result["clusters"]),
        "shortage": len(result["shortage"]),
        "dbscan_clusters": n_clusters,
    }
    if raw_n != n:
        stats["invalid_points"] = raw_n - n
    if warnings:
        stats["warnings"] = warnings
    result["stats"] = stats
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
