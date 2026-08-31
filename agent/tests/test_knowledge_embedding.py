from pathlib import Path

import pytest

from baseline_agent.knowledge_embedding import (
    OfflineBgeEncoder,
    load_model_protocol,
    load_tokenizer,
    tokenize_texts,
)


def test_missing_local_model_fails_before_framework_or_network_loading(tmp_path: Path):
    with pytest.raises(ValueError, match="缺少本地模型文件"):
        OfflineBgeEncoder(tmp_path)


def test_corrupt_weight_fails_before_framework_or_network_loading(tmp_path: Path):
    (tmp_path / "model.safetensors").write_bytes(b"not a model")
    with pytest.raises(ValueError, match="模型文件长度不符"):
        OfflineBgeEncoder(tmp_path)


def test_shared_tokenization_keeps_query_instruction_and_padding_contract():
    calls = []

    def tokenizer(texts, **options):
        calls.append((texts, options))
        return {"input_ids": "tokens"}

    protocol = load_model_protocol()
    for query, tensors in ((True, "pt"), (False, "np")):
        assert tokenize_texts(tokenizer, ["物流延迟"], query=query, return_tensors=tensors) == {
            "input_ids": "tokens"
        }
    assert calls == [
        (
            [protocol["query_instruction"] + "物流延迟"],
            {
                "padding": True,
                "truncation": "longest_first",
                "max_length": 512,
                "return_tensors": "pt",
            },
        ),
        (
            ["物流延迟"],
            {
                "padding": True,
                "truncation": "longest_first",
                "max_length": 512,
                "return_tensors": "np",
            },
        ),
    ]


def test_shared_tokenization_rejects_invalid_input_before_tokenizer_call():
    def tokenizer(*args, **kwargs):
        raise AssertionError("invalid input must not reach tokenizer")

    with pytest.raises(ValueError, match="编码批次"):
        tokenize_texts(tokenizer, [" "], query=False, return_tensors="np")


def test_tokenizer_missing_files_fails_without_requiring_model_weights(tmp_path):
    with pytest.raises(ValueError, match=r"config\.json"):
        load_tokenizer(tmp_path)
