"""冻结 BGE 编码协议;运行阶段仅接受经过校验的本地模型。"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

TOKENIZER_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "special_tokens_map.json",
)


@lru_cache(maxsize=1)
def load_model_protocol() -> dict[str, Any]:
    # 运行编码器只读取 model 字段,不导入会加载冻结查询的评测模块。
    path = Path(__file__).with_name("rag_eval_v1") / "protocol.json"
    return json.loads(path.read_text(encoding="utf-8"))["model"]


def verify_model_directory(directory: Path) -> Path:
    return _verify_files(directory, tuple(load_model_protocol()["files"]))


def _verify_files(directory: Path, names: tuple[str, ...]) -> Path:
    directory = directory.resolve(strict=True)
    for name in names:
        metadata = load_model_protocol()["files"][name]
        path = directory / name
        if not path.is_file() or not path.resolve().is_relative_to(directory):
            raise ValueError(f"缺少本地模型文件: {name}")
        data = path.read_bytes()
        if metadata.get("size_bytes") is not None and len(data) != metadata["size_bytes"]:
            raise ValueError(f"模型文件长度不符: {name}")
        if metadata.get("sha256") and hashlib.sha256(data).hexdigest() != metadata["sha256"]:
            raise ValueError(f"模型文件校验失败: {name}")
        if metadata.get("git_blob_sha1"):
            blob = f"blob {len(data)}\0".encode() + data
            if hashlib.sha1(blob, usedforsecurity=False).hexdigest() != metadata["git_blob_sha1"]:
                raise ValueError(f"模型文件校验失败: {name}")
    return directory


def load_tokenizer(directory: Path) -> Any:
    """只校验/加载冻结分词文件;ONNX 不需要 PyTorch 权重目录。"""
    path = _verify_files(directory, TOKENIZER_FILES)
    from transformers import AutoTokenizer

    protocol = load_model_protocol()
    return AutoTokenizer.from_pretrained(
        str(path),
        local_files_only=True,
        trust_remote_code=False,
        truncation_side=protocol["truncation_side"],
        do_lower_case=protocol["tokenizer_do_lower_case"],
        tokenize_chinese_chars=protocol["tokenize_chinese_chars"],
    )


def load_feature_model(directory: Path) -> Any:
    """校验固定本地模型后加载 CPU/eager 特征图,供现有编码器与 ONNX 导出复用。"""
    path = verify_model_directory(directory)
    import torch
    from transformers import AutoModel

    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    return (
        AutoModel.from_pretrained(
            str(path),
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            attn_implementation="eager",
        )
        .to("cpu")
        .eval()
    )


def tokenize_texts(tokenizer: Any, texts: list[str], *, query: bool, return_tensors: str) -> Any:
    """两种运行时共用输入、查询指令、padding 和截断规则。"""
    if (
        not isinstance(texts, list)
        or not 1 <= len(texts) <= 32
        or any(not isinstance(text, str) or not text.strip() or len(text) > 16000 for text in texts)
    ):
        raise ValueError("编码批次必须包含 1-32 条非空且长度不超过 16000 的文本")
    protocol = load_model_protocol()
    instruction = protocol["query_instruction"] if query else ""
    return tokenizer(
        [instruction + text for text in texts],
        padding=True,
        truncation=protocol["truncation_strategy"],
        max_length=protocol["max_seq_length"],
        return_tensors=return_tensors,
    )


class OfflineBgeEncoder:
    def __init__(self, directory: Path):
        # 公开加载函数先校验文件,校验失败时仍不导入框架。
        self._model = load_feature_model(directory)
        self._tokenizer = load_tokenizer(directory)
        import torch

        self._torch = torch
        self._protocol = load_model_protocol()
        self._lock = threading.Lock()

    def encode(self, texts: list[str], *, query: bool) -> list[list[float]]:
        with self._lock, self._torch.inference_mode():
            tokens = tokenize_texts(self._tokenizer, texts, query=query, return_tensors="pt")
            vectors = self._model(**tokens).last_hidden_state[:, 0]
            vectors = self._torch.nn.functional.normalize(vectors, p=2, dim=1)
            if vectors.shape != (len(texts), self._protocol["output_dimensions"]):
                raise ValueError("BGE 向量维数不符")
            if not bool(self._torch.isfinite(vectors).all()):
                raise ValueError("BGE 返回了非有限向量")
            return vectors.tolist()


@lru_cache(maxsize=1)
def configured_encoder() -> OfflineBgeEncoder:
    directory = os.environ.get("KNOWLEDGE_MODEL_PATH")
    if not directory:
        raise ValueError("未配置离线知识模型路径")
    return OfflineBgeEncoder(Path(directory))
