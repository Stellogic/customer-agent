import pytest

from baseline_agent.intake_model import (
    FixedFakeIntakeModel,
    IntakeModelInput,
    VisibleOrder,
)


@pytest.mark.asyncio
async def test_fixed_fake_proposes_only_a_spring_visible_order() -> None:
    model = FixedFakeIntakeModel()

    result = await model.understand(
        IntakeModelInput(
            customer_message="我的包裹好几天没动了，帮我看看",
            visible_orders=(VisibleOrder("ORDER-DELAY-001", "配送中的合成订单"),),
        )
    )

    assert result.intent == "UNDERSTANDING"
    assert result.status == "READY_TO_CONFIRM"
    assert result.candidate_order_reference == "ORDER-DELAY-001"
    assert result.issue_kind == "LOGISTICS_DELAY"
    assert "请确认" in result.assistant_message


@pytest.mark.asyncio
async def test_fixed_fake_prefers_the_full_reference_over_its_fixture_prefix() -> None:
    model = FixedFakeIntakeModel()

    result = await model.understand(
        IntakeModelInput(
            customer_message="订单 ORDER-DELAY-E2E-NORMAL-a1b2：物流延迟",
            visible_orders=(
                VisibleOrder("ORDER-DELAY-E2E-NORMAL", "验收模板"),
                VisibleOrder("ORDER-DELAY-E2E-NORMAL-a1b2", "本次验收订单"),
            ),
        )
    )

    assert result.status == "READY_TO_CONFIRM"
    assert result.candidate_order_reference == "ORDER-DELAY-E2E-NORMAL-a1b2"


@pytest.mark.asyncio
async def test_fixed_fake_keeps_the_customer_description_as_the_issue_summary() -> None:
    model = FixedFakeIntakeModel()

    result = await model.understand(
        IntakeModelInput(
            customer_message="订单 ORDER-DELAY-001 的物流延迟问题：React 全栈验收",
            visible_orders=(VisibleOrder("ORDER-DELAY-001", "配送中的合成订单"),),
        )
    )

    assert result.issue_summary == "React 全栈验收"


@pytest.mark.asyncio
async def test_fixed_fake_asks_a_natural_clarification_when_issue_is_unclear() -> None:
    model = FixedFakeIntakeModel()

    result = await model.understand(
        IntakeModelInput(
            customer_message="有点问题",
            visible_orders=(VisibleOrder("ORDER-DELAY-001", "配送中的合成订单"),),
        )
    )

    assert result.status == "NEEDS_CLARIFICATION"
    assert result.candidate_order_reference == "ORDER-DELAY-001"
    assert result.issue_kind is None
    assert result.assistant_message.startswith("你说的是不是")


@pytest.mark.asyncio
async def test_confirmation_keeps_the_existing_candidate() -> None:
    model = FixedFakeIntakeModel()

    result = await model.understand(
        IntakeModelInput(
            customer_message="可以，就按这个处理",
            visible_orders=(VisibleOrder("ORDER-DELAY-001", "配送中的合成订单"),),
            current_order_reference="ORDER-DELAY-001",
            current_issue_summary="物流已经延迟多日",
        )
    )

    assert result.intent == "CONFIRM"
    assert result.status == "CONFIRMED"
    assert result.candidate_order_reference == "ORDER-DELAY-001"
