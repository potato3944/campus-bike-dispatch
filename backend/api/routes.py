# -*- coding: utf-8 -*-
"""
REST 接口层
提供系统配置、单车快照、聚类、调度、仿真等 REST 接口。
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from service import service

router = APIRouter(prefix="/api")


class SimRequest(BaseModel):
    strategy: str | None = None   # none / threshold / predictive，空则全跑


@router.get("/health")
def health():
    return {"status": "ok", "sim_time": service.sim_time.isoformat(),
            "bikes": len(service.bike_points),
            "cleaner_stats": service.cleaner.stats}


@router.get("/config")
def get_config():
    """返回全部可配置参数"""
    return service.config


@router.get("/hotspots")
def get_hotspots():
    """校园热点（区域）列表"""
    return [{"id": i + 1, "name": h["name"], "type": h["type"],
             "lat": h["lat"], "lng": h["lng"], "weight": h["weight"]}
            for i, h in enumerate(service.hotspots)]


@router.get("/bikes")
def get_bikes(limit: int = Query(2000, le=5000)):
    """当前单车位置快照"""
    return {"sim_time": service.sim_time.isoformat(),
            "count": len(service.bike_points),
            "bikes": service.bike_points[:limit]}


@router.post("/clusters/scan")
def scan_clusters():
    """手动触发一次双阶段聚类扫描"""
    return service.scan_clusters()


@router.get("/clusters")
def get_clusters():
    """获取最近一次聚类结果"""
    if service.last_cluster is None:
        return service.scan_clusters()
    return service.last_cluster


@router.post("/dispatch")
def dispatch():
    """运行 CVRP 调度求解，生成调度任务与路线"""
    return service.run_dispatch()


@router.post("/simulation")
def simulation(req: SimRequest):
    """运行 SimPy 离散事件仿真对比实验"""
    return service.run_simulation(strategy=req.strategy)


@router.get("/scenarios")
def get_scenarios():
    """获取预设经典潮汐与聚集场景列表"""
    from data.scenario_engine import scenario_engine
    return {"scenarios": scenario_engine.get_meta_list()}


@router.get("/scenario/{scenario_id}")
def get_scenario_data(scenario_id: str, bikes: int = Query(350, ge=100, le=600), steps: int = Query(60, ge=30, le=100)):
    """获取指定场景的高保真路网演化与聚集全量帧序列"""
    from data.scenario_engine import scenario_engine
    return scenario_engine.generate_scenario(scenario_id, total_bikes=bikes, num_frames=steps)


@router.get("/evolution")
def evolution(steps: int = Query(60, ge=10, le=100), bikes: int = Query(350, le=600)):
    """
    预生成单车聚集演化快照（默认早高峰潮汐聚集与调度削峰过程），供前端时间轴回放。
    包含路网平滑点位、实时热力、DBSCAN堆积警报、空缺警报以及调度车动态！
    """
    from data.scenario_engine import scenario_engine
    data = scenario_engine.generate_scenario("morning_rush", total_bikes=bikes, num_frames=steps)
    return {
        "scenario_id": data["scenario_id"],
        "meta": data["meta"],
        "start": data["time_start"],
        "end": data["time_end"],
        "steps": data["steps"],
        "frames": data["frames"],
    }

