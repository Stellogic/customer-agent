from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class InvestigationReasonCode(StrEnum):
    LOGISTICS_DELAY = "LOGISTICS_DELAY"
    DELAY_UNDER_24_HOURS = "DELAY_UNDER_24_HOURS"


class InvestigationJudgmentFailureCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    MODEL_CALL_FAILED = "MODEL_CALL_FAILED"


class InvestigationJudgmentFailure(Exception):
    def __init__(self, code: InvestigationJudgmentFailureCode) -> None:
        self.code = code
        message = {
            InvestigationJudgmentFailureCode.INVALID_INPUT: (
                "investigation judgment input is invalid"
            ),
            InvestigationJudgmentFailureCode.CONFIGURATION_ERROR: (
                "investigation judgment model configuration is invalid"
            ),
        }.get(code, "investigation judgment model call failed")
        super().__init__(message)


@dataclass(frozen=True)
class InvestigationJudgmentInput:
    order_reference: str
    delay_seconds: int
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class InvestigationJudgment:
    compensation_review_required: bool
    reason_code: InvestigationReasonCode


class InvestigationJudgmentModel(Protocol):
    async def judge(self, model_input: InvestigationJudgmentInput) -> InvestigationJudgment: ...


class FixedFakeInvestigationModel:
    async def judge(self, model_input: InvestigationJudgmentInput) -> InvestigationJudgment:
        validate_investigation_judgment_input(model_input)
        if model_input.delay_seconds >= 24 * 60 * 60:
            return InvestigationJudgment(
                compensation_review_required=True,
                reason_code=InvestigationReasonCode.LOGISTICS_DELAY,
            )
        return InvestigationJudgment(
            compensation_review_required=False,
            reason_code=InvestigationReasonCode.DELAY_UNDER_24_HOURS,
        )


def validate_investigation_judgment_input(model_input: InvestigationJudgmentInput) -> None:
    expected_evidence = (
        f"order:{model_input.order_reference}",
        f"logistics:{model_input.order_reference}",
    )
    if (
        not model_input.order_reference
        or not isinstance(model_input.delay_seconds, int)
        or isinstance(model_input.delay_seconds, bool)
        or model_input.delay_seconds < 0
        or model_input.evidence_refs != expected_evidence
    ):
        raise InvestigationJudgmentFailure(InvestigationJudgmentFailureCode.INVALID_INPUT)
