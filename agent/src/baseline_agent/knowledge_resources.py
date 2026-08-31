"""显式单进程 CPU 编码基准;每次 spawn 隔离模型加载与操作系统峰值 RSS。"""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import multiprocessing
import os
import platform
import time
from dataclasses import asdict, dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol


class Encoder(Protocol):
    def encode(self, texts: list[str], *, query: bool) -> list[list[float]]: ...


@dataclass(frozen=True)
class ResourceWorkload:
    batches: tuple[tuple[str, ...], ...]
    query: bool
    warmup_passes: int
    measured_passes: int

    def __post_init__(self) -> None:
        if not self.batches or any(
            not 1 <= len(batch) <= 32
            or any(not text.strip() or len(text) > 16000 for text in batch)
            for batch in self.batches
        ):
            raise ValueError("需要满足编码器契约的非空文本批次")
        if self.warmup_passes < 0 or self.measured_passes < 1:
            raise ValueError("warmup 必须非负，measured 必须为正数")


def summarize_latencies(
    latencies_ms: list[float], documents: int, elapsed_ms: float
) -> dict[str, float]:
    if not latencies_ms or documents < 1 or not math.isfinite(elapsed_ms) or elapsed_ms <= 0:
        raise ValueError("资源指标需要非空、有效的测量")
    if any(not math.isfinite(value) or value <= 0 for value in latencies_ms):
        raise ValueError("延迟必须为有限正数")
    ordered = sorted(latencies_ms)
    # nearest-rank,无插值;延迟单位是一次 batch encode,吞吐单位是文本/秒。
    return {
        "p50_batch_ms": ordered[math.ceil(len(ordered) * 0.50) - 1],
        "p95_batch_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "documents_per_second": documents * 1000 / elapsed_ms,
    }


def peak_rss_bytes() -> int:
    """OS 高水位,不是权重体积或定时采样的最大值。"""
    if os.name == "nt":
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PeakWorkingSetSize
    resource = import_module("resource")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if platform.system() == "Darwin" else peak * 1024)


def _worker(
    connection: Any, factory: str, directory: str, workload: ResourceWorkload, started: float
) -> None:
    try:
        # factory 必须是显式选择的可信本地 module:callable,在新进程内加载。
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["MKL_NUM_THREADS"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        module, name = factory.split(":", 1)
        load_started = time.perf_counter()
        encoder: Encoder = getattr(import_module(module), name)(Path(directory))
        loaded = time.perf_counter()
        encoder.encode(list(workload.batches[0]), query=workload.query)
        first_finished = time.perf_counter()
        for _ in range(workload.warmup_passes):
            for batch in workload.batches:
                encoder.encode(list(batch), query=workload.query)
        latencies = []
        measured_started = time.perf_counter()
        for _ in range(workload.measured_passes):
            for batch in workload.batches:
                batch_started = time.perf_counter()
                encoder.encode(list(batch), query=workload.query)
                latencies.append((time.perf_counter() - batch_started) * 1000)
        elapsed_ms = (time.perf_counter() - measured_started) * 1000
        # 在包元数据读取和结果序列化前取高水位,包含加载、首推理和所有测量。
        peak = peak_rss_bytes()
        versions = {}
        for package in ("torch", "transformers", "onnx", "onnxruntime", "numpy"):
            try:
                versions[package] = version(package)
            except PackageNotFoundError:
                versions[package] = None
        connection.send(
            {
                "status": "MEASURED",
                "cold_start_to_first_result_ms": (first_finished - started) * 1000,
                "import_and_load_ms": (loaded - load_started) * 1000,
                "first_encode_ms": (first_finished - loaded) * 1000,
                "peak_rss_bytes": peak,
                "latencies_batch_ms": latencies,
                "measured_elapsed_ms": elapsed_ms,
                "metrics": summarize_latencies(
                    latencies,
                    sum(map(len, workload.batches)) * workload.measured_passes,
                    elapsed_ms,
                ),
                "environment": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "processor": platform.processor(),
                    "logical_cpus": os.cpu_count(),
                    "threads": 1,
                    "versions": versions,
                },
            }
        )
    except Exception as error:
        connection.send({"status": "ERROR", "error_type": type(error).__name__, "metrics": None})
    finally:
        connection.close()


def measure_encoder(
    factory: str,
    directory: Path,
    workload: ResourceWorkload,
    *,
    timeout_seconds: float,
    hardware_id: str,
) -> dict[str, Any]:
    """调用即启动真实进程/推理,必须由获批的外层持锁入口调用。"""
    if not hardware_id.strip() or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("必须记录硬件标识和有限正超时")
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    started = time.perf_counter()
    process = context.Process(
        target=_worker, args=(writer, factory, str(directory), workload, started)
    )
    process.start()
    writer.close()
    try:
        if not reader.poll(timeout_seconds):
            result = {"status": "ERROR", "error_type": "TimeoutError", "metrics": None}
        else:
            try:
                result = reader.recv()
            except EOFError:
                result = {"status": "ERROR", "error_type": "WorkerExited", "metrics": None}
    finally:
        reader.close()
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join()
    payload = json.dumps(asdict(workload), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        **result,
        "factory": factory,
        "hardware_id": hardware_id,
        "workload": asdict(workload),
        "workload_sha256": hashlib.sha256(payload).hexdigest(),
        "cold_start_definition": "fresh_process_to_first_encode_including_import_and_load",
        "filesystem_cache": "UNCONTROLLED_OS_CACHE",
        "peak_rss_scope": "worker_process_lifetime_before_report_serialization",
    }
