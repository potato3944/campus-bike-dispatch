# -*- coding: utf-8 -*-
"""
校园单车多场景演化引擎 (Scenario Simulation Engine)
高保真模拟教学日真实潮汐与单车聚集过程：
1. 早高峰教学区聚集演化 (07:30 - 08:30)：宿舍/校门 -> 教学楼主楼/图书馆聚集 -> 触发Level 3堆积警报 -> 调度车削峰
2. 午间食堂聚集潮汐 (11:45 - 12:45)：教学区 -> 第一/第二食堂聚集
3. 晚间归寝回流聚集 (21:00 - 22:15)：全校 -> 东/西宿舍回流
4. 调度优化效果对照：无调度放任恶化 vs 智能调度动态平抑
"""

import math
import heapq
import random
import numpy as np
from datetime import datetime, timedelta

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geo import pixel_to_latlng, latlng_to_pixel, haversine_m
from data.gps_simulator import HOTSPOTS

# ---------------------------------------------------------------------------
# 校园路网拓扑定义 (像素坐标系统，与 campus_map.jpg 657x661 精确对齐)
# ---------------------------------------------------------------------------
WAYPOINTS = {
    # 核心热点
    "教学楼主楼区": (210, 170),
    "教学楼西区": (130, 260),
    "图书馆": (330, 240),
    "中心广场": (330, 330),
    "第一食堂": (250, 400),
    "第二食堂": (430, 420),
    "运动场": (500, 280),
    "宿舍区东": (520, 540),
    "宿舍区西": (150, 520),
    "校门/通勤点": (330, 620),
    "调度中心": (330, 330),
    
    # 道路交叉枢纽节点 (Road Intersections)
    "南门交叉口": (330, 540),
    "内环南路西口": (200, 400),
    "内环南路东口": (460, 420),
    "梧桐大道中段": (200, 300),
    "外环东路口": (510, 420),
    "外环北路口": (420, 200),
    "教学区主干道": (270, 200),
}

# 道路连接边与权重 (无向图)
EDGES = [
    ("校门/通勤点", "南门交叉口"),
    ("南门交叉口", "宿舍区西"),
    ("南门交叉口", "宿舍区东"),
    ("南门交叉口", "第一食堂"),
    ("南门交叉口", "第二食堂"),
    
    ("宿舍区西", "内环南路西口"),
    ("宿舍区西", "教学楼西区"),
    
    ("宿舍区东", "外环东路口"),
    ("外环东路口", "第二食堂"),
    ("外环东路口", "运动场"),
    
    ("第一食堂", "内环南路西口"),
    ("第一食堂", "中心广场"),
    ("第二食堂", "内环南路东口"),
    ("第二食堂", "中心广场"),
    
    ("内环南路西口", "梧桐大道中段"),
    ("梧桐大道中段", "教学楼西区"),
    ("梧桐大道中段", "中心广场"),
    ("梧桐大道中段", "教学区主干道"),
    
    ("中心广场", "图书馆"),
    ("中心广场", "教学楼西区"),
    ("中心广场", "运动场"),
    
    ("图书馆", "教学区主干道"),
    ("教学区主干道", "教学楼主楼区"),
    ("教学楼西区", "教学楼主楼区"),
    
    ("图书馆", "外环北路口"),
    ("外环北路口", "教学楼主楼区"),
    ("外环北路口", "运动场"),
]

# 构建图邻接表与最短路径缓存
ADJ = {}
for u, v in EDGES:
    pu, pv = WAYPOINTS[u], WAYPOINTS[v]
    dist = math.hypot(pu[0] - pv[0], pu[1] - pv[1])
    ADJ.setdefault(u, []).append((v, dist))
    ADJ.setdefault(v, []).append((u, dist))

def dijkstra_path(start, goal):
    if start == goal:
        return [start]
    dist = {start: 0}
    prev = {}
    pq = [(0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float('inf')):
            continue
        if u == goal:
            break
        for v, w in ADJ.get(u, []):
            if dist.get(u, 0) + w < dist.get(v, float('inf')):
                dist[v] = dist[u] + w
                prev[v] = u
                heapq.heappush(pq, (dist[v], v))
    if goal not in prev and start != goal:
        return [start, goal]
    curr = goal
    p = []
    while curr:
        p.append(curr)
        curr = prev.get(curr)
    return p[::-1]

PATH_CACHE = {}
for n1 in WAYPOINTS:
    for n2 in WAYPOINTS:
        PATH_CACHE[(n1, n2)] = dijkstra_path(n1, n2)

def get_route_coordinates(start_name, goal_name):
    """返回途径节点的像素坐标列表与对应经纬度列表"""
    names = PATH_CACHE.get((start_name, goal_name), [start_name, goal_name])
    px_coords = [WAYPOINTS[name] for name in names]
    latlngs = [pixel_to_latlng(x, y) for x, y in px_coords]
    return names, px_coords, latlngs

# ---------------------------------------------------------------------------
# 场景生成核心逻辑
# ---------------------------------------------------------------------------
class ScenarioEngine:
    def __init__(self):
        self.scenarios_meta = [
            {
                "id": "morning_rush",
                "title": "早八上课潮·教学区聚集演化",
                "tag": "早高峰重度聚集",
                "time_range": "07:30 - 08:30",
                "duration_min": 60,
                "accent_color": "#ff4d4f",
                "description": "07:30起学生自东/西宿舍和校门密集借车，沿梧桐大道流向教学楼主楼与图书馆。08:05教学楼主楼存车量突破220辆（严重堆积 Level 3），随后调度车介入削峰运往空缺宿舍区。",
                "origin_zones": ["宿舍区东", "宿舍区西", "校门/通勤点"],
                "target_zones": ["教学楼主楼区", "图书馆", "教学楼西区"],
            },
            {
                "id": "noon_canteen",
                "title": "午间干饭潮·食堂门口暴增",
                "tag": "午高峰餐饮潮汐",
                "time_range": "11:45 - 12:45",
                "duration_min": 60,
                "accent_color": "#fa8c16",
                "description": "11:45下课铃响，教学区与图书馆单车大军涌向第一食堂和第二食堂，食堂门口堆积超负荷180%，道路严重拥堵。",
                "origin_zones": ["教学楼主楼区", "图书馆", "教学楼西区"],
                "target_zones": ["第一食堂", "第二食堂"],
            },
            {
                "id": "evening_dorm",
                "title": "晚间自习归寝·宿舍潮汐回流",
                "tag": "晚高峰反向潮汐",
                "time_range": "21:00 - 22:00",
                "duration_min": 60,
                "accent_color": "#722ed1",
                "description": "晚自习与闭馆后，全校单车向东、西宿舍区和南门大幅回流，教学区排空，宿舍区停放区再次呈现饱和状态。",
                "origin_zones": ["教学楼主楼区", "图书馆", "运动场", "中心广场"],
                "target_zones": ["宿舍区东", "宿舍区西", "校门/通勤点"],
            },
            {
                "id": "dispatch_compare",
                "title": "调度对比·削峰填谷效果评估",
                "tag": "CVRP算法成效",
                "time_range": "08:00 - 08:45",
                "duration_min": 45,
                "accent_color": "#13c2c2",
                "description": "通过高亮对比调度车运作路线、搬运过程与空缺填补，直观展示无调度下的恶性堆积与智能调度后的平抑效果。",
                "origin_zones": ["宿舍区东", "宿舍区西"],
                "target_zones": ["教学楼主楼区"],
            }
        ]
        self._cache = {}

    def get_meta_list(self):
        return self.scenarios_meta

    def generate_scenario(self, scenario_id: str = "morning_rush", total_bikes: int = 380, num_frames: int = 60):
        cache_key = f"{scenario_id}_{total_bikes}_{num_frames}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        rng = random.Random(42)
        np.random.seed(42)

        # 1. 确定初始分布与迁移规划
        if scenario_id == "morning_rush":
            initial_stock = {
                "宿舍区东": 160,
                "宿舍区西": 140,
                "校门/通勤点": 50,
                "教学楼主楼区": 10,
                "教学楼西区": 8,
                "图书馆": 10,
                "第一食堂": 2,
                "第二食堂": 0,
                "运动场": 0,
                "中心广场": 0,
            }
            target_weights = {
                "教学楼主楼区": 0.62,
                "图书馆": 0.22,
                "教学楼西区": 0.16,
            }
            start_hour, start_min = 7, 30
            peak_start, peak_end = 8, 30
            dispatch_start = 33

        elif scenario_id == "noon_canteen":
            initial_stock = {
                "教学楼主楼区": 170,
                "教学楼西区": 70,
                "图书馆": 90,
                "中心广场": 10,
                "第一食堂": 12,
                "第二食堂": 10,
                "宿舍区东": 8,
                "宿舍区西": 5,
                "运动场": 5,
                "校门/通勤点": 0,
            }
            target_weights = {
                "第一食堂": 0.55,
                "第二食堂": 0.45,
            }
            start_hour, start_min = 11, 45
            peak_start, peak_end = 8, 28
            dispatch_start = 32

        elif scenario_id == "evening_dorm":
            initial_stock = {
                "教学楼主楼区": 150,
                "图书馆": 110,
                "教学楼西区": 50,
                "运动场": 35,
                "中心广场": 15,
                "第一食堂": 10,
                "第二食堂": 10,
                "宿舍区东": 0,
                "宿舍区西": 0,
                "校门/通勤点": 0,
            }
            target_weights = {
                "宿舍区东": 0.52,
                "宿舍区西": 0.38,
                "校门/通勤点": 0.10,
            }
            start_hour, start_min = 21, 0
            peak_start, peak_end = 8, 32
            dispatch_start = 999

        else: # dispatch_compare
            initial_stock = {
                "宿舍区东": 150,
                "宿舍区西": 130,
                "校门/通勤点": 40,
                "教学楼主楼区": 30,
                "教学楼西区": 15,
                "图书馆": 15,
                "第一食堂": 0,
                "第二食堂": 0,
                "运动场": 0,
                "中心广场": 0,
            }
            target_weights = {"教学楼主楼区": 0.70, "教学楼西区": 0.30}
            start_hour, start_min = 8, 0
            peak_start, peak_end = 5, 24
            dispatch_start = 25

        # 按 initial_stock 分配每辆单车的初始停放热点
        bike_assignments = []
        bid = 1
        for zone, count in initial_stock.items():
            for _ in range(count):
                if bid > total_bikes:
                    break
                bike_assignments.append({
                    "id": bid,
                    "initial_zone": zone,
                    "target_zone": None,
                    "start_step": -1,
                    "duration_steps": 0,
                    "route": [],
                })
                bid += 1

        # 为将在本次潮汐中出行的单车分配目标与出发时间
        target_keys = list(target_weights.keys())
        target_probs = list(target_weights.values())

        for b in bike_assignments:
            zone = b["initial_zone"]
            if zone in ("宿舍区东", "宿舍区西", "校门/通勤点") and scenario_id in ("morning_rush", "dispatch_compare"):
                # 早高峰：宿舍有88%概率骑走
                if rng.random() < 0.88:
                    tgt = rng.choices(target_keys, weights=target_probs)[0]
                    b["target_zone"] = tgt
                    # 出发时间在 peak_start 到 peak_end 之间
                    s_step = int(rng.uniform(peak_start, peak_end))
                    b["start_step"] = max(2, min(num_frames - 15, s_step))
                    dur = rng.randint(5, 10)  # 骑行持续 5~10 帧
                    b["duration_steps"] = dur
                    _, _, latlngs = get_route_coordinates(zone, tgt)
                    b["route"] = latlngs
            elif zone in ("教学楼主楼区", "教学楼西区", "图书馆") and scenario_id == "noon_canteen":
                if rng.random() < 0.88:
                    tgt = rng.choices(target_keys, weights=target_probs)[0]
                    b["target_zone"] = tgt
                    s_step = int(rng.uniform(peak_start, peak_end))
                    b["start_step"] = max(2, min(num_frames - 15, s_step))
                    b["duration_steps"] = rng.randint(4, 9)
                    _, _, latlngs = get_route_coordinates(zone, tgt)
                    b["route"] = latlngs
            elif zone in ("教学楼主楼区", "图书馆", "运动场", "教学楼西区") and scenario_id == "evening_dorm":
                if rng.random() < 0.90:
                    tgt = rng.choices(target_keys, weights=target_probs)[0]
                    b["target_zone"] = tgt
                    s_step = int(rng.uniform(peak_start, peak_end))
                    b["start_step"] = max(2, min(num_frames - 15, s_step))
                    b["duration_steps"] = rng.randint(6, 11)
                    _, _, latlngs = get_route_coordinates(zone, tgt)
                    b["route"] = latlngs

        # 调度车定义 (2辆调度车)
        # 车1: 教学楼主楼 -> 宿舍区东
        # 车2: 教学楼主楼/图书馆 -> 宿舍区西
        truck_configs = [
            {
                "id": 1,
                "name": "调度专车 #1",
                "capacity": 40,
                "from_zone": "教学楼主楼区",
                "to_zone": "宿舍区东",
                "start_step": dispatch_start,
                "load_duration": 4,
                "transit_duration": 10,
                "unload_duration": 4,
            },
            {
                "id": 2,
                "name": "调度专车 #2",
                "capacity": 35,
                "from_zone": "教学楼主楼区",
                "to_zone": "宿舍区西",
                "start_step": dispatch_start + 4,
                "load_duration": 4,
                "transit_duration": 9,
                "unload_duration": 4,
            }
        ]

        # 预计算路径几何
        for tc in truck_configs:
            _, _, r_out = get_route_coordinates("调度中心", tc["from_zone"])
            _, _, r_haul = get_route_coordinates(tc["from_zone"], tc["to_zone"])
            _, _, r_back = get_route_coordinates(tc["to_zone"], "调度中心")
            tc["route_out"] = r_out
            tc["route_haul"] = r_haul
            tc["route_back"] = r_back

        # 模拟生成各帧数据
        frames = []
        base_time = datetime(2026, 9, 21, start_hour, start_min, 0)
        
        # 记录每辆单车的当前状态
        current_bikes = []
        for b in bike_assignments:
            zone_name = b["initial_zone"]
            px, py = WAYPOINTS[zone_name]
            # 加一点初始泊车高斯抖动
            ll = pixel_to_latlng(px + rng.gauss(0, 10), py + rng.gauss(0, 10))
            current_bikes.append({
                "bike_id": b["id"],
                "lat": ll["lat"],
                "lng": ll["lng"],
                "status": "idle",
                "current_zone": zone_name,
                "speed": 0.0,
                "origin": zone_name,
                "destination": b["target_zone"],
            })

        for step in range(num_frames):
            cur_time = base_time + timedelta(minutes=step)
            time_str = cur_time.strftime("%H:%M")

            # 阶段判定与描述
            if step < peak_start:
                phase_name = "起步分散期"
                phase_desc = "早高峰启动前，单车均匀停放于宿舍区及通勤点，供需平衡。"
            elif peak_start <= step < peak_start + 12:
                phase_name = "潮汐涌动期"
                phase_desc = "借车潮爆发，数百辆单车密集穿行于梧桐大道与内环路，快速向教学区汇聚！"
            elif peak_start + 12 <= step < dispatch_start:
                phase_name = "严重堆积爆发期"
                phase_desc = "教学区车位告急！单车急剧暴增突破容量上限300%，触发红色警报与局部道路瘫痪！"
            elif dispatch_start <= step < dispatch_start + 14:
                phase_name = "智能调度削峰期"
                phase_desc = "调度系统自动出动厢式货车，沿最优路径对教学区超载单车进行转运投放！"
            else:
                phase_name = "供需再平衡期"
                phase_desc = "调度转运完成，教学区堆积消退，宿舍区缺口补齐，全校运转恢复正常。"

            # 推进单车位置
            active_moving = 0
            for i, b_meta in enumerate(bike_assignments):
                cb = current_bikes[i]
                s_step = b_meta["start_step"]
                dur = b_meta["duration_steps"]

                if s_step >= 0 and s_step <= step < s_step + dur:
                    # 正在骑行中
                    progress = (step - s_step) / dur
                    route = b_meta["route"]
                    if len(route) >= 2:
                        idx_float = progress * (len(route) - 1)
                        i0 = int(math.floor(idx_float))
                        i1 = min(len(route) - 1, i0 + 1)
                        frac = idx_float - i0
                        p0, p1 = route[i0], route[i1]
                        # 沿路网线性插值 + 局部随机侧移模拟真实车道
                        jitter_lat = rng.gauss(0, 0.00003)
                        jitter_lng = rng.gauss(0, 0.00003)
                        cb["lat"] = p0["lat"] + (p1["lat"] - p0["lat"]) * frac + jitter_lat
                        cb["lng"] = p0["lng"] + (p1["lng"] - p0["lng"]) * frac + jitter_lng
                        cb["status"] = "moving"
                        cb["speed"] = round(rng.uniform(9.5, 12.8), 1)
                        active_moving += 1
                elif s_step >= 0 and step >= s_step + dur and cb["current_zone"] != b_meta["target_zone"]:
                    # 到达目的地，落锁停放
                    tgt_zone = b_meta["target_zone"]
                    cb["current_zone"] = tgt_zone
                    cb["status"] = "idle"
                    cb["speed"] = 0.0
                    px, py = WAYPOINTS[tgt_zone]
                    # 集中堆积在高密度停车区
                    spread = 16 if tgt_zone in ("教学楼主楼区", "第一食堂", "图书馆") else 12
                    ll = pixel_to_latlng(px + rng.gauss(0, spread), py + rng.gauss(0, spread))
                    cb["lat"] = ll["lat"]
                    cb["lng"] = ll["lng"]

            # 推进调度货车状态
            truck_frames = []
            for tc in truck_configs:
                s = tc["start_step"]
                if step < s:
                    # 未出动，在调度中心
                    depot_ll = pixel_to_latlng(*WAYPOINTS["调度中心"])
                    truck_frames.append({
                        "id": tc["id"],
                        "name": tc["name"],
                        "lat": depot_ll["lat"],
                        "lng": depot_ll["lng"],
                        "status": "standby",
                        "status_text": "待命就绪",
                        "load": 0,
                        "capacity": tc["capacity"],
                        "action": "等待堆积警报触发",
                    })
                elif s <= step < s + 4:
                    # 出发前往堆积区
                    prog = (step - s) / 4.0
                    route = tc["route_out"]
                    p = self._interp_route(route, prog)
                    truck_frames.append({
                        "id": tc["id"],
                        "name": tc["name"],
                        "lat": p["lat"],
                        "lng": p["lng"],
                        "status": "en_route",
                        "status_text": f"开往{tc['from_zone']}",
                        "load": 0,
                        "capacity": tc["capacity"],
                        "action": f"响应严重堆积预警，前往{tc['from_zone']}",
                    })
                elif s + 4 <= step < s + 4 + tc["load_duration"]:
                    # 现场装车削峰
                    p = pixel_to_latlng(*WAYPOINTS[tc["from_zone"]])
                    load_pct = (step - (s + 4)) / tc["load_duration"]
                    cur_load = int(tc["capacity"] * load_pct)
                    truck_frames.append({
                        "id": tc["id"],
                        "name": tc["name"],
                        "lat": p["lat"],
                        "lng": p["lng"],
                        "status": "loading",
                        "status_text": "装车削峰中",
                        "load": cur_load,
                        "capacity": tc["capacity"],
                        "action": f"正在将{tc['from_zone']}过剩单车装载入箱 ({cur_load}/{tc['capacity']})",
                    })
                elif s + 4 + tc["load_duration"] <= step < s + 4 + tc["load_duration"] + tc["transit_duration"]:
                    # 运送前往空缺区
                    t_prog = (step - (s + 4 + tc["load_duration"])) / tc["transit_duration"]
                    route = tc["route_haul"]
                    p = self._interp_route(route, t_prog)
                    truck_frames.append({
                        "id": tc["id"],
                        "name": tc["name"],
                        "lat": p["lat"],
                        "lng": p["lng"],
                        "status": "hauling",
                        "status_text": f"运往{tc['to_zone']}",
                        "load": tc["capacity"],
                        "capacity": tc["capacity"],
                        "action": f"满载满运，前往{tc['to_zone']}补充缺口",
                    })
                elif s + 4 + tc["load_duration"] + tc["transit_duration"] <= step < s + 4 + tc["load_duration"] + tc["transit_duration"] + tc["unload_duration"]:
                    # 在空缺区卸车投放
                    p = pixel_to_latlng(*WAYPOINTS[tc["to_zone"]])
                    u_pct = 1.0 - (step - (s + 4 + tc["load_duration"] + tc["transit_duration"])) / tc["unload_duration"]
                    cur_load = max(0, int(tc["capacity"] * u_pct))
                    truck_frames.append({
                        "id": tc["id"],
                        "name": tc["name"],
                        "lat": p["lat"],
                        "lng": p["lng"],
                        "status": "unloading",
                        "status_text": "卸载投放中",
                        "load": cur_load,
                        "capacity": tc["capacity"],
                        "action": f"在{tc['to_zone']}精准投放车辆 ({tc['capacity'] - cur_load}已入位)",
                    })
                else:
                    # 任务完成，返回或驻泊
                    p = pixel_to_latlng(*WAYPOINTS[tc["to_zone"]])
                    truck_frames.append({
                        "id": tc["id"],
                        "name": tc["name"],
                        "lat": p["lat"],
                        "lng": p["lng"],
                        "status": "completed",
                        "status_text": "调度完成",
                        "load": 0,
                        "capacity": tc["capacity"],
                        "action": f"已成功平抑{tc['from_zone']}超负荷，弥补{tc['to_zone']}缺口",
                    })

            # 如果进入卸车期，将部分单车从堆积区扣减并移到空缺区
            # 教学楼主楼 -> 宿舍区
            if step >= dispatch_start + 8 and scenario_id in ("morning_rush", "dispatch_compare"):
                dispatched_count = min(75, int((step - (dispatch_start + 8)) * 6.5))
                # 调整显示位置
                c_disp = 0
                for cb in current_bikes:
                    if cb["current_zone"] == "教学楼主楼区" and cb["status"] == "idle":
                        if c_disp < dispatched_count:
                            target_dorm = "宿舍区东" if c_disp % 2 == 0 else "宿舍区西"
                            px, py = WAYPOINTS[target_dorm]
                            ll = pixel_to_latlng(px + rng.gauss(0, 14), py + rng.gauss(0, 14))
                            cb["lat"] = ll["lat"]
                            cb["lng"] = ll["lng"]
                            cb["current_zone"] = target_dorm
                            c_disp += 1

            # 统计各区域实时车辆数
            zone_counts = {name: 0 for name in WAYPOINTS if name not in ("调度中心", "南门交叉口", "内环南路西口", "内环南路东口", "梧桐大道中段", "外环东路口", "外环北路口", "教学区主干道")}
            for cb in current_bikes:
                zn = cb.get("current_zone")
                if zn in zone_counts:
                    zone_counts[zn] += 1

            # 识别聚集区与空缺区 (DBSCAN / 容量阈值评估)
            clusters = []
            shortages = []
            heat_points = []
            cid = 1
            sid = 1
            capacity_map = {
                "教学楼主楼区": 60,
                "教学楼西区": 50,
                "图书馆": 50,
                "第一食堂": 60,
                "第二食堂": 50,
                "中心广场": 50,
                "运动场": 40,
                "宿舍区东": 80,
                "宿舍区西": 80,
                "校门/通勤点": 50,
            }

            for zname, cnt in zone_counts.items():
                cap = capacity_map.get(zname, 50)
                px, py = WAYPOINTS[zname]
                ll = pixel_to_latlng(px, py)
                ratio = round(cnt / cap, 2)
                intensity = min(1.8, round(cnt / 40.0, 2))
                heat_points.append({"lat": ll["lat"], "lng": ll["lng"], "intensity": intensity})

                # 堆积判定
                if cnt >= cap * 1.25:
                    if ratio >= 2.5:
                        level = 3
                        lvl_desc = "严重堆积"
                    elif ratio >= 1.7:
                        level = 2
                        lvl_desc = "中度堆积"
                    else:
                        level = 1
                        lvl_desc = "轻度堆积"
                    clusters.append({
                        "id": cid,
                        "name": zname,
                        "lat": ll["lat"],
                        "lng": ll["lng"],
                        "count": cnt,
                        "capacity": cap,
                        "ratio": ratio,
                        "level": level,
                        "level_desc": lvl_desc,
                        "radius_m": int(45 + min(65, ratio * 20)),
                    })
                    cid += 1
                elif cnt < cap * 0.25 and zname in ("宿舍区东", "宿舍区西", "校门/通勤点", "教学楼主楼区"):
                    # 空缺判定
                    gap = int(cap * 0.8 - cnt)
                    shortages.append({
                        "id": sid,
                        "name": zname,
                        "lat": ll["lat"],
                        "lng": ll["lng"],
                        "count": cnt,
                        "expected": int(cap * 0.8),
                        "gap": max(5, gap),
                        "level": 3 if cnt < 10 else 2,
                    })
                    sid += 1

            # 综合统计指标
            teaching_cnt = zone_counts.get("教学楼主楼区", 0) + zone_counts.get("教学楼西区", 0) + zone_counts.get("图书馆", 0)
            dorm_cnt = zone_counts.get("宿舍区东", 0) + zone_counts.get("宿舍区西", 0)
            congestion_idx = round(min(100.0, max(10.0, (teaching_cnt / 160.0) * 85.0)), 1)
            balance_rate = round(max(30.0, 100.0 - abs(teaching_cnt - dorm_cnt) / 3.0), 1)

            frame_data = {
                "step": step,
                "time": time_str,
                "phase": phase_name,
                "phase_desc": phase_desc,
                "zone_counts": zone_counts,
                "teaching_total": teaching_cnt,
                "dorm_total": dorm_cnt,
                "active_moving": active_moving,
                "congestion_index": congestion_idx,
                "balance_rate": balance_rate,
                "clusters": clusters,
                "shortages": shortages,
                "heat": heat_points,
                "trucks": truck_frames,
                "bikes": [
                    {
                        "bike_id": cb["bike_id"],
                        "lat": round(cb["lat"], 6),
                        "lng": round(cb["lng"], 6),
                        "status": cb["status"],
                        "speed": cb["speed"],
                        "zone": cb.get("current_zone", ""),
                    }
                    for cb in current_bikes
                ]
            }
            frames.append(frame_data)

        result = {
            "scenario_id": scenario_id,
            "meta": next((m for m in self.scenarios_meta if m["id"] == scenario_id), {}),
            "total_bikes": total_bikes,
            "steps": len(frames),
            "time_start": frames[0]["time"],
            "time_end": frames[-1]["time"],
            "frames": frames,
        }
        self._cache[cache_key] = result
        return result

    def _interp_route(self, route, progress):
        if not route:
            return pixel_to_latlng(*WAYPOINTS["中心广场"])
        if len(route) == 1 or progress <= 0:
            return route[0]
        if progress >= 1.0:
            return route[-1]
        idx_f = progress * (len(route) - 1)
        i0 = int(math.floor(idx_f))
        i1 = min(len(route) - 1, i0 + 1)
        frac = idx_f - i0
        p0, p1 = route[i0], route[i1]
        return {
            "lat": p0["lat"] + (p1["lat"] - p0["lat"]) * frac,
            "lng": p0["lng"] + (p1["lng"] - p0["lng"]) * frac,
        }

scenario_engine = ScenarioEngine()
