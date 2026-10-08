# -*- coding: utf-8 -*-
"""
接口契约自检脚本（独立进程运行）

为什么独立成脚本：FastAPI 的同步端点会在线程池中执行，
在 pytest 进程内反复创建/关闭事件循环可能造成阻塞。
这里用独立进程 + 单一事件循环，既稳定又能真正验证 HTTP 层行为。

校验内容：
  1. 前端以「空请求体」POST 聚类/调度接口必须返回 200（而不是 422）；
  2. 参数覆盖生效，非法取值返回 422；
  3. dispatch 响应满足前端渲染所需的字段契约。

退出码：0 = 全部通过，1 = 存在失败。
用法：cd backend && .venv/bin/python ../tests/api_contract_check.py
"""

import asyncio
import json
import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND))

from main import app  # noqa: E402


async def call(method, path, body=b""):
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "",
        "headers": [(b"host", b"test"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234), "server": ("test", 80), "scheme": "http",
    }
    state = {"status": None, "body": b""}
    sent = {"done": False}

    async def receive():
        if not sent["done"]:
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
        elif message["type"] == "http.response.body":
            state["body"] += message.get("body", b"")

    await app(scope, receive, send)
    return state


async def scenario():
    """所有请求在同一事件循环内串行执行。"""
    return {
        "scan_empty": await call("POST", "/api/clusters/scan"),
        "dispatch_empty": await call("POST", "/api/dispatch"),
        "scan_override": await call(
            "POST", "/api/clusters/scan",
            json.dumps({"eps_m": 45, "min_samples": 8}).encode()),
        "bad_vehicle": await call(
            "POST", "/api/dispatch", json.dumps({"vehicle_num": 0}).encode()),
        "bad_strategy": await call(
            "POST", "/api/simulation", json.dumps({"strategy": "bogus"}).encode()),
    }


def main():
    res = asyncio.run(scenario())
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    # 1) 空请求体必须可用（前端就是这样调用的）
    check(res["scan_empty"]["status"] == 200,
          f"空体 POST /api/clusters/scan 返回 {res['scan_empty']['status']}，期望 200")
    check(res["dispatch_empty"]["status"] == 200,
          f"空体 POST /api/dispatch 返回 {res['dispatch_empty']['status']}，期望 200")
    check(res["scan_override"]["status"] == 200,
          f"带参数 POST /api/clusters/scan 返回 {res['scan_override']['status']}，期望 200")

    # 2) 非法参数应返回 422
    check(res["bad_vehicle"]["status"] == 422,
          f"vehicle_num=0 返回 {res['bad_vehicle']['status']}，期望 422")
    check(res["bad_strategy"]["status"] == 422,
          f"strategy=bogus 返回 {res['bad_strategy']['status']}，期望 422")

    # 3) dispatch 响应契约
    d = json.loads(res["dispatch_empty"]["body"])
    for key in ("status", "algorithm", "routes", "tasks", "depot", "nodes",
                "balance", "vehicle_capacity"):
        check(key in d, f"dispatch 响应缺少字段 {key}")
    cap = d.get("vehicle_capacity", 0)
    for r in d.get("routes", []):
        check({"path", "load", "dist"} <= set(r.keys()),
              f"route 字段不足: {sorted(r.keys())}")
        check(r["path"][0] == 0 and r["path"][-1] == 0,
              f"route path 未以 depot(0) 首尾闭合: {r['path']}")
        check(max(r["path"]) <= len(d.get("nodes", [])),
              "route path 下标越界，前端无法映射到 nodes")
        check(r["load"] <= cap + 1e-6,
              f"route 峰值载重 {r['load']} 超过容量 {cap}")
    for t in d.get("tasks", []):
        check({"vehicle_id", "stops", "distance_km", "load"} <= set(t.keys()),
              f"task 字段不足: {sorted(t.keys())}")

    # 4) 参数覆盖确实改变了聚类结果
    a = json.loads(res["scan_empty"]["body"])["stats"]
    b = json.loads(res["scan_override"]["body"])["stats"]
    check(a["dbscan_clusters"] != b["dbscan_clusters"] or a["clusters"] != b["clusters"],
          f"聚类参数覆盖未生效: 默认={a}, 覆盖后={b}")

    if failures:
        print("接口契约自检失败：")
        for f in failures:
            print("  -", f)
        return 1
    print("接口契约自检通过：空请求体 200 / 非法参数 422 / 响应字段齐全 / 参数覆盖生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
