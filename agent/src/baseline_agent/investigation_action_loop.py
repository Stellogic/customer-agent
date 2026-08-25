import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class InvestigationCapability(StrEnum):
    CONFIRM_ORDER = "CONFIRM_ORDER"
    READ_LOGISTICS = "READ_LOGISTICS"
    READ_PAYMENT_AND_REFUNDS = "READ_PAYMENT_AND_REFUNDS"
    READ_COMPENSATION_AND_PENDING_ACTIONS = "READ_COMPENSATION_AND_PENDING_ACTIONS"
    READ_APPLICABLE_POLICY = "READ_APPLICABLE_POLICY"


CAPABILITY_PARAMETER_NAMES: dict[InvestigationCapability, tuple[str, ...]] = {
    InvestigationCapability.CONFIRM_ORDER: (),
    InvestigationCapability.READ_LOGISTICS: ("orderReference",),
    InvestigationCapability.READ_PAYMENT_AND_REFUNDS: ("orderReference",),
    InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS: ("orderReference",),
    InvestigationCapability.READ_APPLICABLE_POLICY: ("orderReference",),
}


class TerminalAction(StrEnum):
    REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION"
    SUBMIT_CONCLUSION = "SUBMIT_CONCLUSION"
    HANDOFF = "HANDOFF"


ActionKind = InvestigationCapability | TerminalAction


class ActionLoopFailureCode(StrEnum):
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    MODEL_CALL_FAILED = "MODEL_CALL_FAILED"
    REPEATED_NO_PROGRESS = "REPEATED_NO_PROGRESS"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    TOOL_FAILURE = "TOOL_FAILURE"
    INVALID_TOOL_RESPONSE = "INVALID_TOOL_RESPONSE"


@dataclass(frozen=True)
class ActionUsage:
    tokens: int = 0
    cost_micros: int = 0
    provider_attempts: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.tokens) is not int
            or self.tokens < 0
            or type(self.cost_micros) is not int
            or self.cost_micros < 0
            or type(self.provider_attempts) is not int
            or self.provider_attempts < 1
        ):
            raise ValueError("action usage must contain non-negative integer consumption")


@dataclass(frozen=True)
class InvestigationAction:
    kind: ActionKind
    parameters: tuple[tuple[str, str], ...] = ()

    @property
    def parameter_map(self) -> dict[str, str]:
        return dict(self.parameters)


@dataclass(frozen=True)
class ActionDecision:
    action: InvestigationAction
    usage: ActionUsage = ActionUsage()

    @classmethod
    def from_values(
        cls, kind: ActionKind | str, parameters: dict[str, str], usage: ActionUsage
    ) -> "ActionDecision":
        try:
            controlled_kind: ActionKind = InvestigationCapability(kind)
        except ValueError:
            try:
                controlled_kind = TerminalAction(kind)
            except ValueError as error:
                raise ActionLoopFailure(ActionLoopFailureCode.UNKNOWN_ACTION) from error
        expected = (
            set(CAPABILITY_PARAMETER_NAMES[controlled_kind])
            if isinstance(controlled_kind, InvestigationCapability)
            else set()
        )
        if set(parameters) != expected or not all(
            isinstance(value, str) and value for value in parameters.values()
        ):
            raise ActionLoopFailure(ActionLoopFailureCode.UNKNOWN_ACTION)
        return cls(InvestigationAction(controlled_kind, tuple(sorted(parameters.items()))), usage)


@dataclass(frozen=True)
class ActionBudget:
    max_actions: int = 8
    max_wall_clock_ms: int = 30_000
    max_tokens: int = 4_000
    max_cost_micros: int = 100_000
    max_provider_attempts: int = 8
    max_repeated_actions: int = 0

    @classmethod
    def configured(cls) -> "ActionBudget":
        return cls(
            max_actions=_bounded("AGENT_INVESTIGATION_MAX_ACTIONS", 8, 1, 32),
            max_wall_clock_ms=_bounded("AGENT_INVESTIGATION_MAX_WALL_CLOCK_MS", 30_000, 1, 300_000),
            max_tokens=_bounded("AGENT_INVESTIGATION_MAX_TOKENS", 4_000, 0, 1_000_000),
            max_cost_micros=_bounded(
                "AGENT_INVESTIGATION_MAX_COST_MICROS", 100_000, 0, 100_000_000
            ),
            max_provider_attempts=_bounded("AGENT_INVESTIGATION_MAX_PROVIDER_ATTEMPTS", 8, 1, 32),
            max_repeated_actions=_bounded("AGENT_INVESTIGATION_MAX_REPEATED_ACTIONS", 0, 0, 3),
        )


@dataclass(frozen=True)
class ActionRecord:
    action_type: str
    evidence_references: tuple[str, ...]
    result_code: str


@dataclass(frozen=True)
class ActionModelCallRecord:
    call_number: int
    selected_action: str
    provider_attempts: int
    tokens: int
    cost_micros: int


class ActionLoopFailure(Exception):
    def __init__(
        self,
        code: ActionLoopFailureCode,
        facts: dict | None = None,
        records: tuple[ActionRecord, ...] = (),
        provider_attempts: int = 0,
        model_calls: tuple[ActionModelCallRecord, ...] = (),
    ) -> None:
        self.code = code
        self.facts = dict(facts or {})
        self.records = records
        self.provider_attempts = provider_attempts
        self.model_calls = model_calls
        super().__init__(code.value)


@dataclass(frozen=True)
class ActionLoopResult:
    terminal_action: TerminalAction
    facts: dict
    records: tuple[ActionRecord, ...]
    tokens: int
    cost_micros: int
    provider_attempts: int
    model_calls: tuple[ActionModelCallRecord, ...]


class DeterministicActionModel:
    async def choose(self, facts: dict) -> ActionDecision:
        if "matchStatus" not in facts:
            return _decision(InvestigationCapability.CONFIRM_ORDER)
        if facts["matchStatus"] == "AMBIGUOUS":
            return _decision(TerminalAction.REQUEST_CLARIFICATION)
        reference = facts.get("orderReference")
        if not isinstance(reference, str) or not reference:
            return _decision(TerminalAction.HANDOFF)
        for field, kind in (
            ("delaySeconds", InvestigationCapability.READ_LOGISTICS),
            ("paid", InvestigationCapability.READ_PAYMENT_AND_REFUNDS),
            (
                "existingCompensation",
                InvestigationCapability.READ_COMPENSATION_AND_PENDING_ACTIONS,
            ),
            ("policyVersion", InvestigationCapability.READ_APPLICABLE_POLICY),
        ):
            if field not in facts:
                return _decision(kind, {"orderReference": reference})
        return _decision(TerminalAction.SUBMIT_CONCLUSION)


class InvestigationActionModel(Protocol):
    async def choose(self, facts: dict) -> ActionDecision: ...


class ActionLoop:
    def __init__(
        self,
        choose: Callable[[dict], Awaitable[ActionDecision]],
        budget: ActionBudget,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._choose = choose
        self._budget = budget
        self._clock = clock

    async def run(
        self, execute: Callable[[InvestigationAction], Awaitable[dict]]
    ) -> ActionLoopResult:
        started = self._clock()
        facts: dict = {}
        records: list[ActionRecord] = []
        model_calls: list[ActionModelCallRecord] = []
        seen: dict[InvestigationAction, int] = {}
        tokens = cost_micros = provider_attempts = 0
        while True:
            remaining_seconds = self._remaining_seconds(started)
            if remaining_seconds <= 0:
                raise self._failure(
                    ActionLoopFailureCode.BUDGET_EXHAUSTED,
                    facts,
                    records,
                    provider_attempts,
                    model_calls,
                )
            try:
                async with asyncio.timeout(remaining_seconds):
                    decision = await self._choose(dict(facts))
            except TimeoutError as error:
                raise self._failure(
                    ActionLoopFailureCode.BUDGET_EXHAUSTED,
                    facts,
                    records,
                    provider_attempts,
                    model_calls,
                ) from error
            except ActionLoopFailure as error:
                failed_calls = list(model_calls)
                if error.provider_attempts > 0:
                    failed_calls.append(
                        ActionModelCallRecord(
                            call_number=len(failed_calls) + 1,
                            selected_action="",
                            provider_attempts=error.provider_attempts,
                            tokens=0,
                            cost_micros=0,
                        )
                    )
                raise self._failure(
                    error.code,
                    facts,
                    records,
                    provider_attempts + error.provider_attempts,
                    failed_calls,
                ) from error
            except Exception as error:
                raise self._failure(
                    ActionLoopFailureCode.UNKNOWN_ACTION,
                    facts,
                    records,
                    provider_attempts,
                    model_calls,
                ) from error
            if not isinstance(decision, ActionDecision):
                raise self._failure(
                    ActionLoopFailureCode.UNKNOWN_ACTION,
                    facts,
                    records,
                    provider_attempts,
                    model_calls,
                )
            tokens += decision.usage.tokens
            cost_micros += decision.usage.cost_micros
            provider_attempts += decision.usage.provider_attempts
            model_calls.append(
                ActionModelCallRecord(
                    call_number=len(model_calls) + 1,
                    selected_action=decision.action.kind.value,
                    provider_attempts=decision.usage.provider_attempts,
                    tokens=decision.usage.tokens,
                    cost_micros=decision.usage.cost_micros,
                )
            )
            if (
                len(records) >= self._budget.max_actions
                or tokens > self._budget.max_tokens
                or cost_micros > self._budget.max_cost_micros
                or provider_attempts > self._budget.max_provider_attempts
            ):
                raise self._failure(
                    ActionLoopFailureCode.BUDGET_EXHAUSTED,
                    facts,
                    records,
                    provider_attempts,
                    model_calls,
                )
            repeats = seen.get(decision.action, 0)
            if repeats > self._budget.max_repeated_actions:
                raise self._failure(
                    ActionLoopFailureCode.REPEATED_NO_PROGRESS,
                    facts,
                    records,
                    provider_attempts,
                    model_calls,
                )
            seen[decision.action] = repeats + 1
            if isinstance(decision.action.kind, TerminalAction):
                records.append(ActionRecord(decision.action.kind.value, (), "SELECTED"))
                return ActionLoopResult(
                    decision.action.kind,
                    facts,
                    tuple(records),
                    tokens,
                    cost_micros,
                    provider_attempts,
                    tuple(model_calls),
                )
            try:
                remaining_seconds = self._remaining_seconds(started)
                if remaining_seconds <= 0:
                    raise self._failure(
                        ActionLoopFailureCode.BUDGET_EXHAUSTED,
                        facts,
                        records,
                        provider_attempts,
                        model_calls,
                    )
                async with asyncio.timeout(remaining_seconds):
                    result = await execute(decision.action)
            except TimeoutError as error:
                raise self._failure(
                    ActionLoopFailureCode.BUDGET_EXHAUSTED,
                    facts,
                    records,
                    provider_attempts,
                    model_calls,
                ) from error
            except ActionLoopFailure as error:
                raise self._failure(
                    error.code,
                    facts,
                    records,
                    provider_attempts,
                    model_calls,
                ) from error
            except Exception as error:
                raise self._failure(
                    ActionLoopFailureCode.TOOL_FAILURE,
                    facts,
                    records,
                    provider_attempts,
                    model_calls,
                ) from error
            if not isinstance(result, dict):
                raise self._failure(
                    ActionLoopFailureCode.TOOL_FAILURE,
                    facts,
                    records,
                    provider_attempts,
                    model_calls,
                )
            before = dict(facts)
            facts.update(
                {
                    key: value
                    for key, value in result.items()
                    if key not in {"capability", "evidenceRefs"}
                }
            )
            evidence = result.get("evidenceRefs", [])
            controlled_evidence = (
                tuple(evidence)
                if isinstance(evidence, list) and all(isinstance(value, str) for value in evidence)
                else ()
            )
            records.append(
                ActionRecord(
                    decision.action.kind.value,
                    controlled_evidence,
                    "PROGRESSED" if facts != before else "NO_PROGRESS",
                )
            )

    def _remaining_seconds(self, started: float) -> float:
        return self._budget.max_wall_clock_ms / 1000 - (self._clock() - started)

    @staticmethod
    def _failure(
        code: ActionLoopFailureCode,
        facts: dict,
        records: list[ActionRecord],
        provider_attempts: int = 0,
        model_calls: list[ActionModelCallRecord] | None = None,
    ) -> ActionLoopFailure:
        return ActionLoopFailure(
            code,
            facts,
            tuple(records),
            provider_attempts=provider_attempts,
            model_calls=tuple(model_calls or ()),
        )


def _decision(kind: ActionKind, parameters: dict[str, str] | None = None) -> ActionDecision:
    return ActionDecision.from_values(kind, parameters or {}, ActionUsage())


def _bounded(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(max(value, minimum), maximum)
