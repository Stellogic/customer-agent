import pytest

from baseline_agent.deepseek_intake_model import DeepSeekIntakeModel
from baseline_agent.intake_model import FixedFakeIntakeModel
from baseline_agent.intake_model_runtime import configured_intake_model


def test_intake_defaults_to_the_explicit_fixed_fake_ci_mode() -> None:
    model, mode = configured_intake_model({})

    assert isinstance(model, FixedFakeIntakeModel)
    assert mode == "fixed-fake-intake-v1"


def test_formal_intake_requires_deepseek_credentials_and_never_falls_back() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        configured_intake_model({"INVESTIGATION_MODEL_MODE": "deepseek-formal"})

    model, mode = configured_intake_model(
        {
            "INVESTIGATION_MODEL_MODE": "deepseek-formal",
            "DEEPSEEK_API_KEY": "synthetic-test-key",
        }
    )
    assert isinstance(model, DeepSeekIntakeModel)
    assert mode == "deepseek-formal-intake-v1"
