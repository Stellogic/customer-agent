"""离线诊断HTTP客户端初始化耗时,不发出任何网络请求。"""
import asyncio
import json
import os
import time

import certifi
import httpx


async def main():
    previous = os.environ.pop("SSL_CERT_FILE", None)
    measurements = []
    try:
        for source in ("windows-default", "explicit-certifi"):
            if source == "explicit-certifi":
                os.environ["SSL_CERT_FILE"] = certifi.where()
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
    print(json.dumps(measurements, indent=2))


asyncio.run(main())
