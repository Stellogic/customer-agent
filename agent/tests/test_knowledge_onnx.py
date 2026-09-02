import json

import pytest

from baseline_agent.knowledge_onnx import (
    OnnxBgeEncoder,
    OnnxFeatureExtractor,
    export_feature_extraction,
)
from baseline_agent.rag_eval_v1 import load_rag_eval_v1


def test_synthetic_graph_exports_pooling_normalization_and_dynamic_batch_sequence(tmp_path):
    # 可选 onnx 依赖组未安装时可跳过;正式 ONNX 窗口必须安装并实际执行。
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    dimensions = load_rag_eval_v1().protocol.model.output_dimensions

    class FeatureModel(torch.nn.Module):
        def forward(self, input_ids, attention_mask, token_type_ids):
            from types import SimpleNamespace

            offsets = torch.arange(1, dimensions + 1, dtype=torch.float32)
            values = (input_ids + attention_mask + token_type_ids).float().unsqueeze(-1)
            return SimpleNamespace(last_hidden_state=values + offsets)

    def tokens(batch, length):
        return {
            "input_ids": torch.arange(batch * length).reshape(batch, length),
            "attention_mask": torch.ones(batch, length, dtype=torch.int64),
            "token_type_ids": torch.zeros(batch, length, dtype=torch.int64),
        }

    verified = []

    def verify(path):
        verified.append(path)
        return path

    def source(path):
        assert verified == [path]
        return FeatureModel(), tokens(2, 4)

    target = tmp_path / "export"
    manifest = export_feature_extraction(
        tmp_path, target, verify_model_directory=verify, feature_source=source
    )
    assert manifest["consistency_status"] == "NOT_RUN"
    extractor = OnnxFeatureExtractor(target)
    for batch, length in ((1, 2), (3, 7), (1, 512)):
        inputs = tokens(batch, length)
        expected = torch.nn.functional.normalize(
            FeatureModel()(**inputs).last_hidden_state[:, 0], p=2, dim=1
        )
        actual = extractor.extract({name: value.numpy() for name, value in inputs.items()})
        assert torch.allclose(torch.tensor(actual), expected, atol=1e-6)


def test_export_rejects_unverified_source_before_loading_framework(tmp_path):
    def reject(path):
        raise ValueError("model hash mismatch")

    def never_load(path):
        raise AssertionError("must not load unverified weights")

    with pytest.raises(ValueError, match="hash mismatch"):
        export_feature_extraction(
            tmp_path, tmp_path / "export", verify_model_directory=reject, feature_source=never_load
        )
    assert not (tmp_path / "export").exists()


def test_wrong_artifact_protocol_is_rejected_before_runtime_load(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="协议"):
        OnnxFeatureExtractor(tmp_path)


def test_onnx_text_encoder_reuses_shared_tokenization_without_feature_model(monkeypatch, tmp_path):
    from baseline_agent import knowledge_onnx

    marker = object()
    calls = []
    tokens = {"input_ids": "synthetic tokens"}

    def tokenizer_loader(directory):
        assert directory == tmp_path / "tokenizer"
        return marker

    def tokenize(tokenizer, texts, *, query, return_tensors):
        assert tokenizer is marker
        calls.append((texts, query, return_tensors))
        return tokens

    class Extractor:
        def __init__(self, directory):
            assert directory == tmp_path

        def extract(self, supplied):
            assert supplied == tokens
            return [[1.0, 0.0]]

    def forbidden(*args):
        raise AssertionError("ONNX 文本编码不得加载 PyTorch 特征模型")

    monkeypatch.setattr(knowledge_onnx, "load_tokenizer", tokenizer_loader)
    monkeypatch.setattr(knowledge_onnx, "tokenize_texts", tokenize)
    monkeypatch.setattr(knowledge_onnx, "load_feature_model", forbidden)
    monkeypatch.setattr(knowledge_onnx, "OnnxFeatureExtractor", Extractor)
    encoder = OnnxBgeEncoder(tmp_path)
    assert encoder.encode(["物流"], query=True) == [[1.0, 0.0]]
    assert encoder.encode(["政策"], query=False) == [[1.0, 0.0]]
    assert calls == [(["物流"], True, "np"), (["政策"], False, "np")]
