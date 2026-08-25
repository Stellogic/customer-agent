import asyncio

import pytest

from baseline_agent.investigation_action_loop import (
    ActionBudget,
    ActionDecision,
    ActionLoop,
    ActionLoopFailure,
    ActionLoopFailureCode,
    ActionUsage,
    DeterministicActionModel,
    InvestigationCapability,
    TerminalAction,
)


def _decision(
    kind: InvestigationCapability | TerminalAction | str,
    order_reference: str | None = None,
    *,
    tokens: int = 1,
    cost_micros: int = 1,
    provider_attempts: int = 1,
) -> ActionDecision:
    parameters = {} if order_reference is None else {"orderReference": order_reference}
    return ActionDecision.from_values(
        kind,
        parameters,
        ActionUsage(tokens=tokens, cost_micros=cost_micros, provider_attempts=provider_attempts),
    )


@pytest.mark.parametrize(
    ("tokens", "cost_micros", "provider_attempts"),
    [(-1, 0, 1), (0, -1, 1), (0, 0, 0), (True, 0, 1)],
)
def test_action_usage_rejects_values_that_could_bypass_budgets(
    tokens: int, cost_micros: int, provider_attempts: int
) -> None:
    with pytest.raises(ValueError):
        ActionUsage(
            tokens=tokens,
            cost_micros=cost_micros,
            provider_attempts=provider_attempts,
        )


@pytest.mark.asyncio
async def test_deterministic_model_selects_one_allowed_action_until_submission() -> None:
    model = DeterministicActionModel()
    facts: dict = {}
    expected = [
        InvestigationCapability.CONFIRM_ORDER,
        InvestigationCapability.READ_LOGISTICS,
        InvestigationCapability.READ_PAYMENT_AND_REFUNDS,
        InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS,
        InvestigationCapability.READ_APPLICABLE_POLICY,
        TerminalAction.SUBMIT_CONCLUSION,
    ]

    selected = []
    for kind in expected:
        decision = await model.choose(facts)
        selected.append(decision.action.kind)
        facts.update(_progress_for(kind))

    assert selected == expected


@pytest.mark.asyncio
async def test_loop_allows_different_legal_tool_order_and_records_only_controlled_results() -> None:
    decisions = iter(
        [
            _decision(InvestigationCapability.CONFIRM_ORDER),
            _decision(InvestigationCapability.READ_APPLICABLE_POLICY, "ORDER-120"),
            _decision(InvestigationCapability.READ_LOGISTICS, "ORDER-120"),
            _decision(InvestigationCapability.READ_PAYMENT_AND_REFUNDS, "ORDER-120"),
            _decision(InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS, "ORDER-120"),
            _decision(TerminalAction.SUBMIT_CONCLUSION),
        ]
    )

    async def choose(_: dict) -> ActionDecision:
        return next(decisions)

    async def execute(action) -> dict:
        return _progress_for(action.kind)

    result = await ActionLoop(choose, ActionBudget()).run(execute)

    assert result.terminal_action is TerminalAction.SUBMIT_CONCLUSION
    assert result.facts["policyVersion"] == "delay-policy-v1"
    assert [record.action_type for record in result.records] == [
        "CONFIRM_ORDER",
        "READ_APPLICABLE_POLICY",
        "READ_LOGISTICS",
        "READ_PAYMENT_AND_REFUNDS",
        "READ_COMPENSATION_AND_PENDING_ACTIONS",
        "SUBMIT_CONCLUSION",
    ]
    serialized = repr(result.records)
    assert "raw payload" not in serialized
    assert "reasoning" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decisions", "budget", "expected"),
    [
        ([{"action": "UNKNOWN"}], ActionBudget(), ActionLoopFailureCode.UNKNOWN_ACTION),
        (
            [
                _decision(InvestigationCapability.CONFIRM_ORDER),
                _decision(InvestigationCapability.CONFIRM_ORDER),
            ],
            ActionBudget(max_repeated_actions=0),
            ActionLoopFailureCode.REPEATED_NO_PROGRESS,
        ),
        (
            [_decision(InvestigationCapability.CONFIRM_ORDER, tokens=101)],
            ActionBudget(max_tokens=100),
            ActionLoopFailureCode.BUDGET_EXHAUSTED,
        ),
        (
            [_decision(InvestigationCapability.CONFIRM_ORDER, cost_micros=11)],
            ActionBudget(max_cost_micros=10),
            ActionLoopFailureCode.BUDGET_EXHAUSTED,
        ),
        (
            [_decision(InvestigationCapability.CONFIRM_ORDER, provider_attempts=3)],
            ActionBudget(max_provider_attempts=2),
            ActionLoopFailureCode.BUDGET_EXHAUSTED,
        ),
    ],
)
async def test_loop_fails_closed_for_unknown_repeated_or_exhausted_actions(
    decisions: list[object], budget: ActionBudget, expected: ActionLoopFailureCode
) -> None:
    iterator = iter(decisions)

    async def execute(action) -> dict:
        return (
            {}
            if action.kind is InvestigationCapability.CONFIRM_ORDER
            else _progress_for(action.kind)
        )

    with pytest.raises(ActionLoopFailure) as captured:
        await ActionLoop(lambda _: _async_next(iterator), budget).run(execute)

    assert captured.value.code is expected
    if expected is ActionLoopFailureCode.REPEATED_NO_PROGRESS:
        assert captured.value.facts == {}
        assert [record.action_type for record in captured.value.records] == ["CONFIRM_ORDER"]


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_boundary", ["model", "tool"])
async def test_wall_clock_budget_cancels_slow_model_and_tool_calls(slow_boundary: str) -> None:
    async def choose(_: dict) -> ActionDecision:
        if slow_boundary == "model":
            await asyncio.sleep(0.05)
        return _decision(InvestigationCapability.CONFIRM_ORDER)

    async def execute(_) -> dict:
        if slow_boundary == "tool":
            await asyncio.sleep(0.05)
        return _progress_for(InvestigationCapability.CONFIRM_ORDER)

    with pytest.raises(ActionLoopFailure) as captured:
        await ActionLoop(choose, ActionBudget(max_wall_clock_ms=5)).run(execute)

    assert captured.value.code is ActionLoopFailureCode.BUDGET_EXHAUSTED


@pytest.mark.asyncio
async def test_loop_preserves_sanitized_model_failure_attempts_after_completed_tools() -> None:
    decisions = iter([_decision(InvestigationCapability.CONFIRM_ORDER)])

    async def choose(_: dict) -> ActionDecision:
        try:
            return next(decisions)
        except StopIteration:
            raise ActionLoopFailure(
                ActionLoopFailureCode.MODEL_CALL_FAILED,
                provider_attempts=2,
            ) from None

    with pytest.raises(ActionLoopFailure) as captured:
        await ActionLoop(choose, ActionBudget()).run(
            lambda action: _async_result(_progress_for(action.kind))
        )

    assert captured.value.code is ActionLoopFailureCode.MODEL_CALL_FAILED
    assert captured.value.provider_attempts == 3
    assert [record.action_type for record in captured.value.records] == ["CONFIRM_ORDER"]
    assert [call.call_number for call in captured.value.model_calls] == [1, 2]
    assert captured.value.model_calls[-1].selected_action == ""
    assert captured.value.model_calls[-1].provider_attempts == 2


async def _async_result(value: dict) -> dict:
    return value


async def _async_next(iterator) -> ActionDecision:
    return next(iterator)


def _progress_for(kind: InvestigationCapability | TerminalAction) -> dict:
    return {
        InvestigationCapability.CONFIRM_ORDER: {
            "matchStatus": "UNIQUE",
            "orderReference": "ORDER-120",
            "evidenceRefs": ["order:ORDER-120"],
        },
        InvestigationCapability.READ_LOGISTICS: {
            "delayHours": 80,
            "delaySeconds": 288000,
            "evidenceRefs": ["logistics:ORDER-120"],
        },
        InvestigationCapability.READ_PAYMENT_AND_REFUNDS: {
            "paid": True,
            "cancelled": False,
            "fullyRefunded": False,
            "evidenceRefs": ["payment:ORDER-120"],
        },
        InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS: {
            "existingCompensation": False,
            "pendingActionCount": 0,
            "evidenceRefs": ["compensation:ORDER-120", "order-actions:ORDER-120"],
        },
        InvestigationCapability.READ_APPLICABLE_POLICY: {
            "policyVersion": "delay-policy-v1",
            "evidenceRefs": ["policy:delay-policy-v1"],
        },
        TerminalAction.SUBMIT_CONCLUSION: {},
        TerminalAction.REQUEST_CLARIFICATION: {},
        TerminalAction.HANDOFF: {},
    }[kind]
