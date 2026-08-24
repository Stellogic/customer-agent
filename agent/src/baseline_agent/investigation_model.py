from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class InvestigationReasonCode(StrEnum):
    LOGISTICS_DELAY = "LOGISTICS_DELAY"
    DELAY_UNDER_24_HOURS = "DELAY_UNDER_24_HOURS"


class InvestigationJudgmentFailureCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"


class InvestigationJudgmentFailure(Exception):
    def __init__(self, code: InvestigationJudgmentFailureCode) -> None:
        self.code = code
        super().__init__("investigation judgment input is invalid")


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
        _validate_input(model_input)
        if model_input.delay_seconds >= 24 * 60 * 60:
            return InvestigationJudgment(
                compensation_review_required=True,
                reason_code=InvestigationReasonCode.LOGISTICS_DELAY,
            )
        return InvestigationJudgment(
            compensation_review_required=False,
            reason_code=InvestigationReasonCode.DELAY_UNDER_24_HOURS,
        )


def _validate_input(model_input: InvestigationJudgmentInput) -> None:
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
