# -*- coding: utf-8 -*-
"""
校园共享单车智能调度管理平台 - 后端入口
FastAPI 应用：REST 接口 + WebSocket 实时 GPS 通道 + 前端静态托管

启动：uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from service import service
from api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动 GPS 模拟线程
    service.start()
    yield
    service.stop()


app = FastAPI(title="校园共享单车智能调度管理平台", version="1.0.0",
              lifespan=lifespan)

# CORS：允许本地 Vite 开发服务器跨域访问。
# 生产托管模式同源访问，不需要开放任意来源；关闭 credentials 也避免
# 浏览器拒绝「* + credentials」这一无效组合。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


# ---------------------------------------------------------------------------
# WebSocket 实时 GPS 数据通道
# 推送频率：每 2 秒推一批清洗后的 GPS 点
# ---------------------------------------------------------------------------
async def _receive_gps(ws: WebSocket):
    """接收外部 GPS 点；读取失败只结束当前连接的接收任务。"""
    try:
        while True:
            message = await ws.receive_json()
            if isinstance(message, dict):
                service.ingest_point(message)
    except (WebSocketDisconnect, RuntimeError):
        return
    except Exception as exc:  # noqa: BLE001 - 单个数据源不应影响服务
        service.last_error = f"WebSocket GPS 接收失败: {type(exc).__name__}: {exc}"


@app.websocket("/ws/gps")
async def ws_gps(ws: WebSocket):
    await ws.accept()
    receiver = asyncio.create_task(_receive_gps(ws))
    try:
        while True:
            # 在锁内取一致快照，避免读到「点位/时间/统计」互相错位的中间状态
            snap = service.snapshot()
            if snap["points"]:
                await ws.send_json({
                    "sim_time": snap["sim_time"],
                    "points": snap["points"],
                    "cleaner_stats": snap["cleaner_stats"],
                    # 附带最近一次聚类结果（含 clusters/heat/shortage），
                    # 供「实时监测」模式渲染聚类圈与热力图
                    "clusters": snap["clusters"],
                })
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        pass
    except Exception:      # noqa: BLE001 - 单个连接异常不应影响其它连接
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        receiver.cancel()


# ---------------------------------------------------------------------------
# 前端静态托管（前端构建产物 dist 目录）
# ---------------------------------------------------------------------------
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
