from pathlib import Path

import pytest

from baseline_agent.knowledge_embedding import OfflineBgeEncoder


def test_missing_local_model_fails_before_framework_or_network_loading(tmp_path: Path):
    with pytest.raises(ValueError, match="缺少本地模型文件"):
        OfflineBgeEncoder(tmp_path)


def test_corrupt_weight_fails_before_framework_or_network_loading(tmp_path: Path):
    (tmp_path / "model.safetensors").write_bytes(b"not a model")
    with pytest.raises(ValueError, match="模型文件长度不符"):
        OfflineBgeEncoder(tmp_path)
