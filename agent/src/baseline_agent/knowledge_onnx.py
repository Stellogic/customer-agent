"""#168 可选 feature-extraction 图导出与 CPU 执行,不加载/复制 #190 编码器。"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import asdict
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

from baseline_agent.knowledge_embedding import (
    TOKENIZER_FILES,
    load_feature_model,
    load_tokenizer,
    tokenize_texts,
)
from baseline_agent.knowledge_embedding import (
    verify_model_directory as verify_bge_directory,
)
from baseline_agent.rag_eval_v1 import load_rag_eval_v1

TOKEN_INPUTS = ("input_ids", "attention_mask", "token_type_ids")
# 集成方从已校验路径离线构造 CPU/eager feature model 和一批正确分词的示例。
# 本模块不访问 OfflineBgeEncoder._model/_tokenizer,也不复制其加载代码。
FeatureSource = Callable[[Path], tuple[Any, dict[str, Any]]]


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def export_feature_extraction(
    model_directory: Path,
    destination: Path,
    *,
    verify_model_directory: Callable[[Path], Path],
    feature_source: FeatureSource,
) -> dict[str, Any]:
    """只在获批持锁窗口调用;调用者提供 #190 校验器及尚待集成的加载接缝。"""
    verified_path = verify_model_directory(model_directory)
    protocol = load_rag_eval_v1().protocol.model
    torch = import_module("torch")
    onnx = import_module("onnx")
    model, tokens = feature_source(verified_path)
    if set(tokens) != set(TOKEN_INPUTS):
        raise ValueError("导出需要 BERT 三项输入")
    shape = tuple(tokens["input_ids"].shape)
    if len(shape) != 2 or not 1 <= shape[0] <= 32 or not 1 <= shape[1] <= protocol.max_seq_length:
        raise ValueError("导出示例批次/长度超出冻结编码契约")
    if any(
        tuple(value.shape) != shape or value.dtype != torch.int64 or value.device.type != "cpu"
        for value in tokens.values()
    ):
        raise ValueError("导出输入须为同形状 CPU int64 张量")

    class ClsNormalizedFeatureModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.encoder = model.to("cpu").eval()

        def forward(self, input_ids: Any, attention_mask: Any, token_type_ids: Any) -> Any:
            hidden = self.encoder(
                input_ids=input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
            ).last_hidden_state
            return torch.nn.functional.normalize(hidden[:, 0], p=2, dim=1)

    # 不覆盖既有模型/证据。失败可留下无 manifest 的目录,不能被运行器加载。
    destination.mkdir(parents=True, exist_ok=False)
    artifact = destination / "model.onnx"
    with torch.inference_mode():
        torch.onnx.export(
            ClsNormalizedFeatureModel().eval(),
            tuple(tokens[name] for name in TOKEN_INPUTS),
            str(artifact),
            input_names=list(TOKEN_INPUTS),
            output_names=["embeddings"],
            opset_version=17,
            dynamo=False,
            external_data=False,
            dynamic_axes={
                **{name: {0: "batch", 1: "sequence"} for name in TOKEN_INPUTS},
                "embeddings": {0: "batch"},
            },
        )
    onnx.checker.check_model(str(artifact))
    manifest = {
        "schema": "knowledge-onnx-feature-v1",
        "model_protocol": asdict(protocol),
        "task": "feature-extraction",
        "pooling_in_graph": "cls",
        "normalization_in_graph": "l2",
        "opset": 17,
        "exporter": "torch.onnx/dynamo=False",
        "input_names": list(TOKEN_INPUTS),
        "output_name": "embeddings",
        "sha256": file_sha256(artifact),
        "versions": {name: version(name) for name in ("torch", "transformers", "onnx")},
        "consistency_status": "NOT_RUN",
        "resource_status": "NOT_RUN",
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


class OnnxFeatureExtractor:
    """只接收分词张量,不是文本 Encoder;query 指令/截断适配留给集成方。"""

    def __init__(self, directory: Path) -> None:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        artifact = directory / "model.onnx"
        self._protocol = load_rag_eval_v1().protocol.model
        if (
            manifest["schema"] != "knowledge-onnx-feature-v1"
            or manifest["model_protocol"] != asdict(self._protocol)
            or manifest["sha256"] != file_sha256(artifact)
        ):
            raise ValueError("ONNX 来源协议或文件校验不符")
        runtime = import_module("onnxruntime")
        self._numpy = import_module("numpy")
        options = runtime.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = runtime.ExecutionMode.ORT_SEQUENTIAL
        self._session = runtime.InferenceSession(
            str(artifact), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._session.disable_fallback()
        if [item.name for item in self._session.get_inputs()] != list(TOKEN_INPUTS):
            raise ValueError("ONNX 图输入不符")

    def extract(self, tokens: dict[str, Any]) -> list[list[float]]:
        if set(tokens) != set(TOKEN_INPUTS):
            raise ValueError("ONNX 需要 BERT 三项输入")
        shape = tuple(tokens["input_ids"].shape)
        if (
            len(shape) != 2
            or not 1 <= shape[0] <= 32
            or not 1 <= shape[1] <= self._protocol.max_seq_length
        ):
            raise ValueError("ONNX 批次/长度超出编码契约")
        if any(
            tuple(value.shape) != shape or value.dtype != self._numpy.int64
            for value in tokens.values()
        ):
            raise ValueError("ONNX 输入须为同形状 int64 数组")
        vectors = self._session.run(["embeddings"], tokens)[0]
        if (
            vectors.shape != (shape[0], self._protocol.output_dimensions)
            or not self._numpy.isfinite(vectors).all()
        ):
            raise ValueError("ONNX 输出维度不符或包含非有限值")
        return vectors.tolist()


def bge_feature_source(directory: Path) -> tuple[Any, dict[str, Any]]:
    """复用 CPU 特征图和真实分词,不读 OfflineBgeEncoder 私有成员。"""
    tokenizer = load_tokenizer(directory)
    tokens = tokenize_texts(
        tokenizer, ["物流延迟处理", "退款审批规则"], query=False, return_tensors="pt"
    )
    return load_feature_model(directory), dict(tokens)


def export_bge_model(model_directory: Path, destination: Path) -> dict[str, Any]:
    manifest = export_feature_extraction(
        model_directory,
        destination,
        verify_model_directory=verify_bge_directory,
        feature_source=bge_feature_source,
    )
    tokenizer_directory = destination / "tokenizer"
    tokenizer_directory.mkdir()
    for name in TOKENIZER_FILES:
        shutil.copyfile(model_directory / name, tokenizer_directory / name)
    return manifest


class OnnxBgeEncoder:
    """与 OfflineBgeEncoder 相同的文本接口;目录只含图和冻结分词文件。"""

    def __init__(self, directory: Path) -> None:
        self._tokenizer = load_tokenizer(directory / "tokenizer")
        self._extractor = OnnxFeatureExtractor(directory)

    def encode(self, texts: list[str], *, query: bool) -> list[list[float]]:
        tokens = tokenize_texts(self._tokenizer, texts, query=query, return_tensors="np")
        return self._extractor.extract(dict(tokens))
