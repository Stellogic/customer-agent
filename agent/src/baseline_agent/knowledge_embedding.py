"""冻结 BGE 编码协议；运行阶段仅接受经过校验的本地模型。"""

from __future__ import annotations

import hashlib
import os
import threading
from functools import lru_cache
from pathlib import Path

from baseline_agent.rag_eval_v1 import load_rag_eval_v1


def verify_model_directory(directory: Path) -> Path:
    directory = directory.resolve(strict=True)
    for name, metadata in load_rag_eval_v1().protocol.model.files.items():
        path = directory / name
        if not path.is_file() or not path.resolve().is_relative_to(directory):
            raise ValueError(f"缺少本地模型文件: {name}")
        data = path.read_bytes()
        if metadata.size_bytes is not None and len(data) != metadata.size_bytes:
            raise ValueError(f"模型文件长度不符: {name}")
        if metadata.sha256 and hashlib.sha256(data).hexdigest() != metadata.sha256:
            raise ValueError(f"模型文件校验失败: {name}")
        if metadata.git_blob_sha1:
            blob = f"blob {len(data)}\0".encode() + data
            if hashlib.sha1(blob, usedforsecurity=False).hexdigest() != metadata.git_blob_sha1:
                raise ValueError(f"模型文件校验失败: {name}")
    return directory


class OfflineBgeEncoder:
    def __init__(self, directory: Path):
        path = verify_model_directory(directory)
        # 延迟导入：未配置/校验失败时不加载框架，更不会尝试联网取模型。
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self._protocol = load_rag_eval_v1().protocol.model
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(path),
            local_files_only=True,
            trust_remote_code=False,
            truncation_side=self._protocol.truncation_side,
            do_lower_case=False,
        )
        self._model = (
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
        self._lock = threading.Lock()

    def encode(self, texts: list[str], *, query: bool) -> list[list[float]]:
        if (
            not isinstance(texts, list)
            or not 1 <= len(texts) <= 32
            or any(
                not isinstance(text, str) or not text.strip() or len(text) > 16000 for text in texts
            )
        ):
            raise ValueError("编码批次必须包含 1-32 条非空且长度不超过 16000 的文本")
        instruction = self._protocol.query_instruction if query else ""
        with self._lock, self._torch.inference_mode():
            tokens = self._tokenizer(
                [instruction + text for text in texts],
                padding=True,
                truncation=self._protocol.truncation_strategy,
                max_length=self._protocol.max_seq_length,
                return_tensors="pt",
            )
            vectors = self._model(**tokens).last_hidden_state[:, 0]
            vectors = self._torch.nn.functional.normalize(vectors, p=2, dim=1)
            if vectors.shape != (len(texts), self._protocol.output_dimensions):
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
