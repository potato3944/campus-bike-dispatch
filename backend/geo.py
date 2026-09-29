# -*- coding: utf-8 -*-
"""
地图坐标映射工具
实现校园俯瞰图像素坐标 <-> 真实经纬度的双向映射，
以及常用地理距离计算（Haversine 公式）。
"""

import math
from config import MAP

# 标定角点（便于后续引用）
_TL = MAP["top_left"]
_TR = MAP["top_right"]
_BL = MAP["bottom_left"]
_BR = MAP["bottom_right"]
_W, _H = MAP["image_size"]


def _lerp(a, b, t):
    """线性插值"""
    return a + (b - a) * t


def pixel_to_latlng(px, py):
    """
    像素坐标 -> 经纬度
    使用双线性插值：先按 y 在上下边之间插值，再按 x 在左右边之间插值。
    px, py 为底图像素坐标（左上角为原点）。
    """
    tx = px / _W if _W else 0.0
    ty = py / _H if _H else 0.0
    # 上边、下边分别插值
    top = {"lat": _lerp(_TL["lat"], _TR["lat"], tx),
           "lng": _lerp(_TL["lng"], _TR["lng"], tx)}
    bottom = {"lat": _lerp(_BL["lat"], _BR["lat"], tx),
              "lng": _lerp(_BL["lng"], _BR["lng"], tx)}
    return {"lat": _lerp(top["lat"], bottom["lat"], ty),
            "lng": _lerp(top["lng"], bottom["lng"], ty)}


def latlng_to_pixel(lat, lng):
    """经纬度 -> 像素坐标（双线性插值逆运算，近似解）"""
    # 构建线性方程组：lat = a*px + b*py + c, lng = d*px + e*py + f
    # 用最小二乘拟合三个未知系数（两行方程组，用闭式解）
    import numpy as np
    pts = [_TL, _TR, _BL, _BR]
    X = np.array([[0, 0, 1], [_W, 0, 1], [0, _H, 1], [_W, _H, 1]], dtype=float)
    lat_arr = np.array([p["lat"] for p in pts], dtype=float)
    lng_arr = np.array([p["lng"] for p in pts], dtype=float)
    # 解最小二乘：A @ coeff = y
    coeff_lat, *_ = np.linalg.lstsq(X, lat_arr, rcond=None)
    coeff_lng, *_ = np.linalg.lstsq(X, lng_arr, rcond=None)
    a, b, c = coeff_lat
    d, e, f = coeff_lng
    # 解二元一次方程组
    det = a * e - b * d
    if abs(det) < 1e-12:
        return 0, 0
    px = (e * (lat - c) - b * (lng - f)) / det
    py = (a * (lng - f) - d * (lat - c)) / det
    return px, py


def haversine_m(lat1, lng1, lat2, lng2):
    """两经纬度点间球面距离（米）"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
