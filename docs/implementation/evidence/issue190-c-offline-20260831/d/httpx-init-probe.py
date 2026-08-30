"""离线诊断HTTP客户端初始化耗时,不发出任何网络请求。"""
import asyncio
import json
import os
import time

import certifi
import httpx


async def main():
    previous = os.environ.pop("SSL_CERT_FILE", None)
    previous_no_proxy = os.environ.get("NO_PROXY")
    measurements = []
    try:
        for source in ("inherited-proxy-environment", "offline-no-proxy"):
            os.environ["SSL_CERT_FILE"] = certifi.where()
            if source == "offline-no-proxy":
                os.environ["NO_PROXY"] = "*"
            started = time.perf_counter()
            async with httpx.AsyncClient() as client:
                measurements.append({
                    "certificate_source": source,
                    "initialization_seconds": time.perf_counter() - started,
                    "network_requests": 0,
                })
                assert not client.is_closed
    finally:
        if previous is None:
            os.environ.pop("SSL_CERT_FILE", None)
        else:
            os.environ["SSL_CERT_FILE"] = previous
        if previous_no_proxy is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = previous_no_proxy
    print(json.dumps(measurements, indent=2))


asyncio.run(main())
