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
async def test_multiple_mentioned_orders_are_processed_one_at_a_time() -> None:
    model = FixedFakeIntakeModel()
    orders = (
        VisibleOrder("ORDER-DELAY-001", "配送中的合成订单"),
        VisibleOrder("ORDER-DELAY-002", "配送中的合成订单"),
    )

    first = await model.understand(
        IntakeModelInput(
            customer_message="ORDER-DELAY-001 没收到，ORDER-DELAY-002 物流延迟",
            visible_orders=orders,
        )
    )

    assert first.candidate_order_reference == "ORDER-DELAY-001"
    assert first.remaining_order_references == ("ORDER-DELAY-002",)

    continued = await model.understand(
        IntakeModelInput(
            customer_message="ORDER-DELAY-001 没收到，ORDER-DELAY-002 物流延迟",
            visible_orders=(orders[1],),
        )
    )

    assert continued.candidate_order_reference == "ORDER-DELAY-002"
    assert continued.remaining_order_references == ()


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


@pytest.mark.asyncio
async def test_multiple_issues_are_proposed_only_after_uncertain_issue_is_clarified() -> None:
    model = FixedFakeIntakeModel()
    orders = (VisibleOrder("ORDER-MULTI-001", "配送中的合成订单"),)

    first = await model.understand(
        IntakeModelInput(
            customer_message="ORDER-MULTI-001 的包裹没收到，而且疑似重复扣款",
            visible_orders=orders,
        )
    )

    assert first.status == "NEEDS_CLARIFICATION"
    assert [issue.kind for issue in first.issues] == ["PACKAGE_NOT_RECEIVED"]
    assert first.pending_issue_kinds == ("DUPLICATE_CHARGE",)
    assert "重复扣款" in first.assistant_message

    clarified = await model.understand(
        IntakeModelInput(
            customer_message="是的，确实重复扣款",
            visible_orders=orders,
            current_order_reference="ORDER-MULTI-001",
            current_issues=first.issues,
            current_pending_issue_kinds=first.pending_issue_kinds,
        )
    )

    assert clarified.status == "READY_TO_CONFIRM"
    assert [issue.kind for issue in clarified.issues] == [
        "PACKAGE_NOT_RECEIVED",
        "DUPLICATE_CHARGE",
    ]
    assert clarified.pending_issue_kinds == ()


@pytest.mark.asyncio
async def test_uncertain_duplicate_charge_denial_never_enters_proposed_issues() -> None:
    model = FixedFakeIntakeModel()
    orders = (VisibleOrder("ORDER-MULTI-001", "配送中的合成订单"),)
    first = await model.understand(
        IntakeModelInput(
            customer_message="ORDER-MULTI-001 的包裹没收到，而且疑似重复扣款",
            visible_orders=orders,
        )
    )

    denied = await model.understand(
        IntakeModelInput(
            customer_message="没有重复扣款，只扣了一次",
            visible_orders=orders,
            current_order_reference="ORDER-MULTI-001",
            current_issues=first.issues,
            current_pending_issue_kinds=first.pending_issue_kinds,
        )
    )

    assert denied.status == "READY_TO_CONFIRM"
    assert [issue.kind for issue in denied.issues] == ["PACKAGE_NOT_RECEIVED"]
    assert denied.pending_issue_kinds == ()


@pytest.mark.asyncio
async def test_multiple_uncertain_issues_are_retained_and_clarified_one_at_a_time() -> None:
    model = FixedFakeIntakeModel()
    orders = (VisibleOrder("ORDER-MULTI-001", "配送中的合成订单"),)
    first = await model.understand(
        IntakeModelInput(
            customer_message="ORDER-MULTI-001 的包裹可能没收到，而且疑似重复扣款",
            visible_orders=orders,
        )
    )
    assert first.issues == ()
    assert first.pending_issue_kinds == ("PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE")

    package_confirmed = await model.understand(
        IntakeModelInput(
            customer_message="确认，至今没收到",
            visible_orders=orders,
            current_order_reference="ORDER-MULTI-001",
            current_issues=first.issues,
            current_pending_issue_kinds=first.pending_issue_kinds,
        )
    )
    assert package_confirmed.status == "NEEDS_CLARIFICATION"
    assert [issue.kind for issue in package_confirmed.issues] == ["PACKAGE_NOT_RECEIVED"]
    assert package_confirmed.pending_issue_kinds == ("DUPLICATE_CHARGE",)


@pytest.mark.asyncio
async def test_clarified_pending_head_is_appended_after_existing_issues() -> None:
    model = FixedFakeIntakeModel()
    orders = (VisibleOrder("ORDER-MULTI-001", "配送中的合成订单"),)
    first = await model.understand(
        IntakeModelInput(
            customer_message="ORDER-MULTI-001 的包裹可能没收到，而且确实重复扣款",
            visible_orders=orders,
        )
    )
    assert [issue.kind for issue in first.issues] == ["DUPLICATE_CHARGE"]
    assert first.pending_issue_kinds == ("PACKAGE_NOT_RECEIVED",)

    clarified = await model.understand(
        IntakeModelInput(
            customer_message="确认，至今没收到",
            visible_orders=orders,
            current_order_reference="ORDER-MULTI-001",
            current_issues=first.issues,
            current_pending_issue_kinds=first.pending_issue_kinds,
        )
    )

    assert clarified.status == "READY_TO_CONFIRM"
    assert [issue.kind for issue in clarified.issues] == [
        "DUPLICATE_CHARGE",
        "PACKAGE_NOT_RECEIVED",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("uncertain_message", "denial_message", "pending_kind"),
    [
        (
            "ORDER-MULTI-001 的包裹可能没收到，而且确实重复扣款",
            "已经收到，不是没收到",
            "PACKAGE_NOT_RECEIVED",
        ),
        (
            "ORDER-MULTI-001 的物流可能延迟，而且确实重复扣款",
            "没有延迟，物流正常",
            "LOGISTICS_DELAY",
        ),
    ],
)
async def test_denied_pending_issue_never_enters_proposed_issues(
    uncertain_message: str, denial_message: str, pending_kind: str
) -> None:
    model = FixedFakeIntakeModel()
    orders = (VisibleOrder("ORDER-MULTI-001", "配送中的合成订单"),)
    first = await model.understand(
        IntakeModelInput(customer_message=uncertain_message, visible_orders=orders)
    )
    assert [issue.kind for issue in first.issues] == ["DUPLICATE_CHARGE"]
    assert first.pending_issue_kinds == (pending_kind,)

    denied = await model.understand(
        IntakeModelInput(
            customer_message=denial_message,
            visible_orders=orders,
            current_order_reference="ORDER-MULTI-001",
            current_issues=first.issues,
            current_pending_issue_kinds=first.pending_issue_kinds,
        )
    )

    assert denied.status == "READY_TO_CONFIRM"
    assert [issue.kind for issue in denied.issues] == ["DUPLICATE_CHARGE"]
    assert denied.pending_issue_kinds == ()
