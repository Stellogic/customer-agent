import pytest

from baseline_agent.investigation_action_loop import (
    ActionBudget,
    ActionDecision,
    ActionKind,
    ActionLoop,
    ActionLoopFailure,
    ActionLoopFailureCode,
    ActionUsage,
    DeterministicActionModel,
)


def _decision(
    kind: ActionKind | str,
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


@pytest.mark.asyncio
async def test_deterministic_model_selects_one_allowed_action_until_submission() -> None:
    model = DeterministicActionModel()
    facts: dict = {}
    expected = [
        ActionKind.CONFIRM_ORDER,
        ActionKind.READ_LOGISTICS,
        ActionKind.READ_PAYMENT_AND_REFUNDS,
        ActionKind.READ_COMPENSATION_AND_PENDING_ACTIONS,
        ActionKind.READ_APPLICABLE_POLICY,
        ActionKind.SUBMIT_CONCLUSION,
    ]

    selected = []
    for kind in expected:
        decision = await model.choose(facts)
        selected.append(decision.action.kind)
        facts.update(_progress_for(kind))

    assert selected == expected
    assert all(kind in ActionKind for kind in selected)


@pytest.mark.asyncio
async def test_loop_allows_different_legal_tool_order_and_records_only_controlled_results() -> None:
    decisions = iter(
        [
            _decision(ActionKind.CONFIRM_ORDER),
            _decision(ActionKind.READ_APPLICABLE_POLICY, "ORDER-120"),
            _decision(ActionKind.READ_LOGISTICS, "ORDER-120"),
            _decision(ActionKind.READ_PAYMENT_AND_REFUNDS, "ORDER-120"),
            _decision(ActionKind.READ_COMPENSATION_AND_PENDING_ACTIONS, "ORDER-120"),
            _decision(ActionKind.SUBMIT_CONCLUSION),
        ]
    )

    async def choose(_: dict) -> ActionDecision:
        return next(decisions)

    async def execute(action) -> dict:
        return _progress_for(action.kind)

    result = await ActionLoop(choose, ActionBudget()).run(execute)

    assert result.terminal_action is ActionKind.SUBMIT_CONCLUSION
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
            [_decision(ActionKind.CONFIRM_ORDER), _decision(ActionKind.CONFIRM_ORDER)],
            ActionBudget(max_repeated_actions=0),
            ActionLoopFailureCode.REPEATED_NO_PROGRESS,
        ),
        (
            [_decision(ActionKind.CONFIRM_ORDER, tokens=101)],
            ActionBudget(max_tokens=100),
            ActionLoopFailureCode.BUDGET_EXHAUSTED,
        ),
        (
            [_decision(ActionKind.CONFIRM_ORDER, cost_micros=11)],
            ActionBudget(max_cost_micros=10),
            ActionLoopFailureCode.BUDGET_EXHAUSTED,
        ),
        (
            [_decision(ActionKind.CONFIRM_ORDER, provider_attempts=3)],
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
        return {} if action.kind is ActionKind.CONFIRM_ORDER else _progress_for(action.kind)

    with pytest.raises(ActionLoopFailure) as captured:
        await ActionLoop(lambda _: _async_next(iterator), budget).run(execute)

    assert captured.value.code is expected


async def _async_next(iterator) -> ActionDecision:
    return next(iterator)


def _progress_for(kind: ActionKind) -> dict:
    return {
        ActionKind.CONFIRM_ORDER: {
            "matchStatus": "UNIQUE",
            "orderReference": "ORDER-120",
            "evidenceRefs": ["order:ORDER-120"],
        },
        ActionKind.READ_LOGISTICS: {
            "delayHours": 80,
            "delaySeconds": 288000,
            "evidenceRefs": ["logistics:ORDER-120"],
        },
        ActionKind.READ_PAYMENT_AND_REFUNDS: {
            "paid": True,
            "cancelled": False,
            "fullyRefunded": False,
            "evidenceRefs": ["payment:ORDER-120"],
        },
        ActionKind.READ_COMPENSATION_AND_PENDING_ACTIONS: {
            "existingCompensation": False,
            "pendingActionCount": 0,
            "evidenceRefs": ["compensation:ORDER-120", "order-actions:ORDER-120"],
        },
        ActionKind.READ_APPLICABLE_POLICY: {
            "policyVersion": "delay-policy-v1",
            "evidenceRefs": ["policy:delay-policy-v1"],
        },
        ActionKind.SUBMIT_CONCLUSION: {},
        ActionKind.REQUEST_CLARIFICATION: {},
        ActionKind.HANDOFF: {},
    }[kind]
