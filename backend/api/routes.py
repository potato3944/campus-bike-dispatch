# -*- coding: utf-8 -*-
"""
REST 接口层
提供系统配置、单车快照、聚类、调度、仿真等 REST 接口。

参数覆盖：聚类 / 调度 / 仿真接口均支持在请求体中覆盖 config.py 的默认参数，
便于做参数敏感性实验，无需修改代码或重启服务。
"""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from service import service, ConfigError

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# 请求模型（带范围校验，非法取值由 FastAPI 统一返回 422）
# ---------------------------------------------------------------------------
class ClusterRequest(BaseModel):
    eps_m: Optional[float] = Field(None, gt=0, le=2000, description="DBSCAN 邻域半径(米)")
    min_samples: Optional[int] = Field(None, ge=2, le=200, description="DBSCAN 核心点最少样本数")
    k_levels: Optional[int] = Field(None, ge=1, le=10, description="K-means 二次聚类类别数")
    capacity_per_zone: Optional[int] = Field(None, ge=1, le=2000, description="单区域容量")


class DispatchRequest(BaseModel):
    vehicle_capacity: Optional[int] = Field(None, ge=1, le=1000, description="车辆载重上限")
    vehicle_num: Optional[int] = Field(None, ge=1, le=50, description="可用车辆数")
    algorithm: Optional[Literal["ga", "ortools"]] = Field(
        None, description="主求解算法：ga=改进遗传算法（默认），ortools=OR-Tools")
    compare: Optional[bool] = Field(
        None, description="是否同时运行对照算法，在 solver_comparison 中给出里程/耗时对比")
    ga: Optional[dict] = Field(None, description="遗传算法参数覆盖")
    solver: Optional[dict] = Field(None, description="OR-Tools 参数覆盖")


class SimRequest(BaseModel):
    strategy: Optional[Literal["none", "threshold", "predictive"]] = Field(
        None, description="调度策略，空则三类全跑")
    duration_h: Optional[float] = Field(None, gt=0, le=72)
    arrival_rate_per_h: Optional[float] = Field(None, gt=0, le=100000)
    seed: Optional[int] = Field(None, ge=0)
    threshold_imbalance: Optional[int] = Field(None, ge=0, le=10000)
    predict_window_min: Optional[float] = Field(None, gt=0, le=720)
    check_interval_min: Optional[float] = Field(None, gt=0, le=240)
    force: bool = Field(False, description="True=忽略缓存强制重算；False=参数一致时复用缓存")


class ConfigPatch(BaseModel):
    """运行时参数覆盖（POST /api/config）。仅白名单键生效，越界返回 422。"""
    cluster: Optional[dict] = Field(None, description="聚类参数：eps_m / min_samples / k_levels / scan_interval_s")
    cvrp: Optional[dict] = Field(None, description="调度参数：vehicle_capacity / vehicle_num")
    simulation: Optional[dict] = Field(None, description="仿真参数：duration_h / arrival_rate_per_h / threshold_imbalance / predict_window_min / check_interval_min / seed")
    bike: Optional[dict] = Field(None, description="单车参数：total / capacity_per_zone")


def _model_dump(model):
    """兼容不同 pydantic 版本的字典导出，并剔除未设置字段。"""
    if model is None:
        return {}
    data = model.model_dump(exclude_none=True) if hasattr(model, "model_dump") \
        else model.dict(exclude_none=True)
    return data


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------
@router.get("/health")
def health():
    snap = service.snapshot()
    return {"status": "ok", "sim_time": snap["sim_time"],
            "bikes": len(snap["bike_points"]),
            "cleaner_stats": snap["cleaner_stats"],
            "rejected_points": snap["rejected_points"],
            "last_error": service.last_error}


@router.get("/config")
def get_config():
    """返回全部可配置参数"""
    return service.config


@router.post("/config")
def update_config(patch: ConfigPatch):
    """
    运行时修改参数（选题报告功能要求「参数可配置」）。

    仅白名单键可改，取值越界 / 键不存在返回 422；修改成功后失效相关结果缓存，
    下一次聚类 / 调度 / 仿真即按新参数计算，无需重启服务。
    """
    try:
        return service.apply_config(_model_dump(patch))
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/hotspots")
def get_hotspots():
    """校园热点（区域）列表"""
    return [{"id": i + 1, "name": h["name"], "type": h["type"],
             "lat": h["lat"], "lng": h["lng"], "weight": h["weight"]}
            for i, h in enumerate(service.hotspots)]


@router.get("/bikes")
def get_bikes(limit: int = Query(2000, le=5000)):
    """当前单车位置快照"""
    snap = service.snapshot()
    return {"sim_time": snap["sim_time"],
            "count": len(snap["bike_points"]),
            "bikes": snap["bike_points"][:limit]}


@router.post("/clusters/scan")
def scan_clusters(req: Optional[ClusterRequest] = None):
    """手动触发一次双阶段聚类扫描（可覆盖聚类参数）"""
    return service.scan_clusters(_model_dump(req))


@router.get("/clusters")
def get_clusters():
    """获取最近一次聚类结果"""
    if service.last_cluster is None:
        return service.scan_clusters()
    return service.last_cluster


@router.post("/dispatch")
def dispatch(req: Optional[DispatchRequest] = None):
    """运行 CVRP 调度求解，生成调度任务与路线（可覆盖车辆与算法参数）"""
    return service.run_dispatch(_model_dump(req))


@router.post("/simulation")
def simulation(req: Optional[SimRequest] = None):
    """运行 SimPy 离散事件仿真对比实验（可覆盖仿真参数）"""
    payload = _model_dump(req)
    strategy = payload.pop("strategy", None)
    try:
        return service.run_simulation(strategy=strategy, overrides=payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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
